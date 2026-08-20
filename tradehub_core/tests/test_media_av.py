"""Zararlı içerik taraması, karantina, retry ve dead-letter testleri (TUR-125).

Kapsam — `test_media_transcode_retry.py` ile aynı eksenler:

  Unit          : politika çözümleme, tarayıcı tespiti, imza adı ayıklama,
                  durum önceliği, yol koruması
  Integration   : `inventory.list_files` çıktısında `scan_status`
  API           : `media_admin` uçları (genel bakış, liste, retry, karantinadan
                  çıkarma, geriye dönük tarama)
  Database      : sayaç kalıcılığı, yama idempotency
  Auth          : uçlar `@frappe.whitelist` — Guest'e kapalı
  Authorization : karantinadan çıkarma yalnız System Manager
  Validation    : boş/bozuk adres, yanlış durumda retry reddi (monkey)
  E2E           : yükleme → pending → zararlı → karantina → geri alma
  Error/recovery: tarayıcı yokluğu, kuyruktayken silinen dosya, taşıma hatası

`subprocess.run` ve `frappe.enqueue` HER ZAMAN mock'lanır — makinede ClamAV
kurulu olsa da olmasa da. İki gerekçe: gerçek RQ kuyruğuna iş atmak dev
worker'larını test dosyalarının üstüne salardı, ve testler makinenin
kurulumundan bağımsız aynı sonucu vermeli. Gerçek zararlı dosya hiçbir testte
üretilmez — tarayıcının "bulundu" cevabı çıkış koduyla taklit edilir.

Aynı gerekçe fixture'a da uygulanıyor: `_insert` yükleme kancasını nötrler.
Kancanın kendi davranışı `TestKancaTetikleme` içinde ayrıca sınanıyor.

> Bu ders pahalıya öğrenildi: testler ClamAV kurulu DEĞİLKEN yazıldı ve 64'ü de
> geçti; tarayıcı kurulunca 5 test düştü, çünkü `after_insert` kancası artık
> gerçekten iş yapıyordu. Yeşil bir test paketi, ortam değiştiğinde hâlâ yeşil
> kalacağının garantisi değil.

    docker exec -w /home/frappe/frappe-bench istoc-backend bench \
        --site tradehub.localhost run-tests \
        --module tradehub_core.tests.test_media_av
"""

from __future__ import annotations

import contextlib
import os
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from tradehub_core.api import media_admin
from tradehub_core.media import av, inventory, jobs, seller_media, trash

# Koşum başına benzersiz tuz — içerik-adresli adlandırma (WP4) aynı baytları
# aynı `file_url`'e eşliyor ve bu testler `frappe.db.commit()` çağıran yollara
# giriyor, yani kayıtlar kalıcı oluyor. Tuz olmadan sonraki koşum geçen koşumun
# artığını bulurdu (`test_media_transcode_retry` ile aynı tuzak).
_KOSUM_TUZU: str = frappe.generate_hash(length=12)

# Sahte tarayıcı komutu — `scanner_command` bunu döndürünce politika "açık"
# olur ve `subprocess.run` mock'u devreye girer.
_SAHTE_TARAYICI: tuple[str, ...] = ("/usr/bin/clamdscan", "--no-summary", "--fdpass")


def _insert(alanlar: dict):
	"""`File` kaydı aç — tarama kancasını NÖTRLEYEREK.

	`File.after_insert` kancası (`av.maybe_scan_on_insert`) makinede ClamAV
	KURULUYSA gerçekten kuyruğa iş atıyor ve durumu `pending` yapıyor. O zaman
	her test kendi kurduğu başlangıç durumu yerine kancanın bıraktığı durumla
	başlıyor — ve sonuç, testin kendisiyle ilgisi olmayan bir şeye, makinede
	tarayıcı bulunup bulunmamasına bağlı hâle geliyor.

	Yaşandı: testler ClamAV kurulu DEĞİLKEN yazıldı, 64'ü de geçti; tarayıcı
	kurulunca 5 test düştü. Fixture'ı kancadan yalıtmak bu bağımlılığı kesiyor.
	Kancanın kendi davranışı `TestKancaTetikleme` içinde ayrıca sınanıyor.
	"""
	with mock.patch("tradehub_core.media.av.enqueue_scan"):
		doc = frappe.get_doc(alanlar)
		doc.insert(ignore_permissions=True)
	return doc


def _yeni_dosya(file_name: str, content: bytes | None = None):
	icerik = content if content is not None else f"icerik {_KOSUM_TUZU} {file_name}".encode()
	return _insert({"doctype": "File", "file_name": file_name, "is_private": 0, "content": icerik})


def _sil(name: str) -> None:
	"""Kaydı sil ve COMMIT et.

	`FrappeTestCase` teardown'da rollback yapıyor. Test edilen kod yolları
	(`_run_scan`, süpürücü) kendi `frappe.db.commit()`'lerini çağırdığı için
	INSERT kalıcı oluyor; temizlikteki DELETE ise rollback'e takılıp geri
	alınıyordu. Sonuç: her koşum veritabanında birkaç artık kayıt bırakıyordu
	(ölçüldü: 3 kayıt). Silmeyi de commit etmek bunu kaynağında kapatıyor.
	"""
	with contextlib.suppress(Exception):
		frappe.delete_doc("File", name, ignore_permissions=True, force=True)
		frappe.db.commit()


def _durum(name: str) -> str:
	return frappe.db.get_value("File", name, "th_media_scan_status") or ""


def _deneme(name: str) -> int:
	return int(frappe.db.get_value("File", name, "th_media_scan_attempts") or 0)


class _SahteSonuc:
	"""`subprocess.run` dönüşünün taklidi — yalnız kullanılan üç alan."""

	def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b""):
		self.returncode = returncode
		self.stdout = stdout
		self.stderr = stderr


@contextlib.contextmanager
def _tarayici(returncode: int, stdout: bytes = b"", *, side_effect=None):
	"""Tarayıcı kuruluymuş gibi davran, verilen sonucu döndür."""
	with (
		mock.patch("tradehub_core.media.av.scanner_command", return_value=_SAHTE_TARAYICI),
		mock.patch(
			"tradehub_core.media.av.subprocess.run",
			side_effect=side_effect,
			return_value=_SahteSonuc(returncode, stdout),
		) as calisan,
		mock.patch("tradehub_core.media.av.frappe.enqueue") as kuyruk,
	):
		yield calisan, kuyruk


def _karantinayi_temizle(file_url: str) -> None:
	"""Testin diskte bıraktığı karantina dosyasını sil.

	`FrappeTestCase` rollback'i diske yazılanı geri almaz; karantina taşıması
	`shutil.move` ile fiziksel yapılıyor.
	"""
	with contextlib.suppress(Exception):
		yol = av._quarantine_path(file_url)
		if os.path.exists(yol):
			os.remove(yol)


def _bekletmeyi_temizle(file_url: str) -> None:
	"""Testin diskte bıraktığı bekletme dosyasını yerine koy."""
	with contextlib.suppress(Exception):
		av.release_hold(file_url)


@contextlib.contextmanager
def _bekletme(acik: bool = True):
	"""Bekletme politikasını sabitle — makinenin kurulumundan bağımsız."""
	with mock.patch.dict(
		frappe.conf, {"media_av_hold_until_clean": 1 if acik else 0}, clear=False
	):
		yield


# ── Bekletme: taranmamış dosya servis edilmez (kabul kriteri 4) ─────────


class TestBekletme(FrappeTestCase):
	"""Kabul kriteri 4'ün geçici pencereyi de kapatan kısmı.

	Karantina yalnız KALICI açıklığı kapatıyordu: dosya, kaydın açılması ile
	taramanın bitmesi arasında saniyelerce servis edilebiliyordu. Bekletme o
	aralığı da kapatır — taranmamış dosya bir an bile canlı ağaçta durmaz.
	"""

	def setUp(self):
		self.doc = _yeni_dosya("bekletme.txt")
		self.addCleanup(lambda: _sil(self.doc.name))
		self.addCleanup(lambda: _bekletmeyi_temizle(self.doc.file_url))
		self.addCleanup(lambda: _karantinayi_temizle(self.doc.file_url))

	def test_bekletme_dosyayi_canli_agactan_cikarir(self):
		canli = av._live_path(self.doc.file_url)
		self.assertTrue(os.path.exists(canli))
		self.assertTrue(av.hold(self.doc.file_url))
		self.assertFalse(os.path.exists(canli), "bekletilen dosya canlı ağaçta kalmamalı")
		self.assertTrue(av.in_hold(self.doc.file_url))

	def test_adres_degismez(self):
		"""İçerik-adresli sözleşme korunmalı — yalnız fiziksel yer değişir."""
		onceki = self.doc.file_url
		av.hold(onceki)
		self.assertEqual(
			frappe.db.get_value("File", self.doc.name, "file_url"),
			onceki,
			"bekletme file_url'i değiştirmemeli",
		)

	def test_bekletmeden_cikarma_yerine_koyar(self):
		av.hold(self.doc.file_url)
		self.assertTrue(av.release_hold(self.doc.file_url))
		self.assertTrue(os.path.exists(av._live_path(self.doc.file_url)))
		self.assertFalse(av.in_hold(self.doc.file_url))

	def test_bekletme_idempotent(self):
		self.assertTrue(av.hold(self.doc.file_url))
		# İkinci çağrı: canlıda dosya yok, sessizce False dönmeli (patlamamalı).
		self.assertFalse(av.hold(self.doc.file_url))

	def test_bekletmedeki_dosya_servis_edilemez(self):
		frappe.db.set_value("File", self.doc.name, "th_media_scan_status", av.SCAN_PENDING)
		av.hold(self.doc.file_url)
		self.assertFalse(av.is_servable(self.doc.file_url))

	def test_kanca_yuklemede_bekletmeye_alir(self):
		"""Asıl kriter: yeni dosya, taranmadan canlı ağaçta durmamalı."""
		with _bekletme(True), _tarayici(0):
			doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"kanca-beklet-{_KOSUM_TUZU}.txt",
					"is_private": 0,
					"content": f"kanca beklet {_KOSUM_TUZU}".encode(),
				}
			)
			doc.insert(ignore_permissions=True)
		self.addCleanup(lambda: _sil(doc.name))
		self.addCleanup(lambda: _bekletmeyi_temizle(doc.file_url))

		self.assertEqual(_durum(doc.name), av.SCAN_PENDING)
		self.assertTrue(av.in_hold(doc.file_url), "taranmamış dosya bekletmede olmalı")
		self.assertFalse(os.path.exists(av._live_path(doc.file_url)))

	def test_temiz_sonuc_dosyayi_yerine_koyar(self):
		with _bekletme(True):
			av.hold(self.doc.file_url)
			with _tarayici(0):
				av._run_scan(self.doc.file_url, self.doc.name)
		self.assertEqual(_durum(self.doc.name), av.SCAN_CLEAN)
		self.assertTrue(os.path.exists(av._live_path(self.doc.file_url)), "temiz dosya geri konmalı")
		self.assertTrue(av.is_servable(self.doc.file_url))

	def test_zararli_sonuc_bekletmeden_karantinaya_gecer(self):
		"""Bekletmedeki dosya taranırken bulunmalı ve karantinaya geçmeli."""
		with _bekletme(True):
			av.hold(self.doc.file_url)
			with _tarayici(1, b"/x: Test-Sig FOUND\n"):
				av._run_scan(self.doc.file_url, self.doc.name)
		self.assertEqual(_durum(self.doc.name), av.SCAN_INFECTED)
		self.assertFalse(av.in_hold(self.doc.file_url), "karantinaya geçince bekletmede kalmamalı")
		self.assertTrue(os.path.exists(av._quarantine_path(self.doc.file_url)))

	def test_dead_letter_fail_open_bekletmeden_cikarir(self):
		"""Politika 'açık bırakıyoruz' diyorsa dosya gerçekten açık kalmalı.

		Bekletmede unutulan dosya, fail-open sözünün sessizce tersine dönmesi
		olurdu: panelde 'taranamadı, erişimde' yazarken dosya görünmezdi.
		"""
		frappe.db.set_value(
			"File", self.doc.name, "th_media_scan_attempts", av.MAX_SCAN_ATTEMPTS - 1
		)
		with _bekletme(True):
			av.hold(self.doc.file_url)
			with _tarayici(0, side_effect=RuntimeError("tarayıcı patladı")):
				av._run_scan(self.doc.file_url, self.doc.name)
		self.assertEqual(_durum(self.doc.name), av.SCAN_FAILED)
		self.assertTrue(
			os.path.exists(av._live_path(self.doc.file_url)),
			"fail-open: taranamayan dosya erişimde kalmalı",
		)

	def test_tarayici_yokken_bekletme_kapali(self):
		"""Tarayıcı yoksa bekletmek her yüklemeyi sonsuza kadar görünmez yapardı."""
		with mock.patch("tradehub_core.media.av.scanner_command", return_value=None):
			self.assertFalse(av.policy()["hold_until_clean"])

	def test_bekletme_ve_karantina_ayri_kokler(self):
		# Operatör karantina listesine bakınca yalnız KARAR verilmişleri görmeli.
		self.assertNotEqual(
			av._hold_path(self.doc.file_url), av._quarantine_path(self.doc.file_url)
		)


# ── Unit: politika ve tarayıcı tespiti ──────────────────────────────────


class TestPolitika(FrappeTestCase):
	"""Tarayıcı yoksa özellik sessizce kapalı olmalı, siteyi kilitlememeli."""

	def test_tarayici_yoksa_otomatik_kapali(self):
		with mock.patch("tradehub_core.media.av.scanner_command", return_value=None):
			self.assertFalse(av.policy()["enabled"])

	def test_tarayici_varsa_otomatik_acik(self):
		with mock.patch("tradehub_core.media.av.scanner_command", return_value=_SAHTE_TARAYICI):
			self.assertTrue(av.policy()["enabled"])

	def test_acik_ayari_otomatigi_ezer(self):
		"""Tarayıcı yokken bile elle açılabilmeli — kurulum sırası bağlayıcı olmasın."""
		with (
			mock.patch("tradehub_core.media.av.scanner_command", return_value=None),
			mock.patch.dict(frappe.conf, {"media_av_enabled": 1}, clear=False),
		):
			self.assertTrue(av.policy()["enabled"])

	def test_fail_closed_varsayilan_kapali(self):
		# Varsayılan fail-open: ClamAV kurulu değilken sıkı davranmak HER
		# yüklemeyi karantinaya atardı.
		self.assertFalse(av.policy()["fail_closed"])

	def test_kapaliyken_kuyruga_hic_girmez(self):
		doc = _yeni_dosya("politika-kapali.txt")
		self.addCleanup(
			lambda: _sil(doc.name)
		)
		with (
			mock.patch("tradehub_core.media.av.scanner_command", return_value=None),
			mock.patch("tradehub_core.media.av.frappe.enqueue") as kuyruk,
		):
			sonuc = av.enqueue_scan(doc.file_url, doc.name)
		kuyruk.assert_not_called()
		self.assertEqual(sonuc.get("skipped"), "disabled")
		# Durum BOŞ kalmalı: "hiç denenmedi" ile "denendi, olmadı" farklı şeyler.
		self.assertEqual(_durum(doc.name), "")


class TestImzaAyiklama(FrappeTestCase):
	"""Unit — clamdscan çıktısından imza adı."""

	def test_imza_adi_okunur(self):
		cikti = b"/var/x/a.jpg: Eicar-Test-Signature FOUND\n"
		self.assertEqual(av._signature_name(cikti), "Eicar-Test-Signature")

	def test_imzasiz_cikti_bos_doner(self):
		# İmzayı okuyamamak bulguyu geçersiz kılmaz — boş dönüp devam edilmeli.
		self.assertEqual(av._signature_name(b"anlamsiz cikti"), "")

	def test_bos_cikti_patlamaz(self):
		self.assertEqual(av._signature_name(b""), "")
		self.assertEqual(av._signature_name(None), "")


class TestYolKorumasi(FrappeTestCase):
	"""Validation/monkey — dizin dışına çıkma denemeleri."""

	def test_bozuk_adresler_kontrollu_hata_verir(self):
		for bozuk in ("", None, "files/x.jpg", "/etc/passwd", "/files/../../etc/passwd", "http://x/y.jpg"):
			with self.assertRaises(frappe.ValidationError, msg=f"girdi: {bozuk!r}"):
				av._split_url(bozuk)

	def test_public_ve_private_ayri_cozulur(self):
		self.assertEqual(av._split_url("/files/a/b.jpg"), ("public", "a/b.jpg"))
		self.assertEqual(av._split_url("/private/files/a/b.txt"), ("private", "a/b.txt"))

	def test_private_karantinada_ayri_alt_dizine_gider(self):
		# Geri alma dosyayı DOĞRU köke döndürebilmeli; karışırsa private bir KYB
		# belgesi public dizine geri konurdu.
		pub = av._quarantine_path("/files/x.jpg")
		priv = av._quarantine_path("/private/files/x.jpg")
		self.assertNotEqual(pub, priv)
		self.assertIn(f"{os.sep}private{os.sep}", priv)

	def test_sorgu_parametresi_yolu_bozmaz(self):
		self.assertEqual(av._split_url("/files/a.jpg?v=2"), ("public", "a.jpg"))


# ── Unit: durum önceliği ────────────────────────────────────────────────


class TestDurumOnceligi(FrappeTestCase):
	"""Aynı adrese işaret eden kayıtların durumları ayrışırsa kötü haber kazanır."""

	def setUp(self):
		self.doc = _yeni_dosya("durum-onceligi.txt")
		self.ikinci = _insert(
			{
				"doctype": "File",
				"file_name": "durum-onceligi-2.txt",
				"is_private": 0,
				"file_url": self.doc.file_url,
			}
		)
		for d in (self.doc, self.ikinci):
			self.addCleanup(
				lambda n=d.name: _sil(n)
			)

	def test_infected_clean_i_yener(self):
		frappe.db.set_value("File", self.doc.name, "th_media_scan_status", av.SCAN_CLEAN)
		frappe.db.set_value("File", self.ikinci.name, "th_media_scan_status", av.SCAN_INFECTED)
		self.assertEqual(av.current_status(self.doc.file_url), av.SCAN_INFECTED)

	def test_failed_pending_i_yener(self):
		frappe.db.set_value("File", self.doc.name, "th_media_scan_status", av.SCAN_PENDING)
		frappe.db.set_value("File", self.ikinci.name, "th_media_scan_status", av.SCAN_FAILED)
		self.assertEqual(av.current_status(self.doc.file_url), av.SCAN_FAILED)

	def test_durum_yoksa_bos_doner(self):
		self.assertEqual(av.current_status("/files/hic-olmayan-adres.jpg"), "")

	def test_infected_servis_edilemez(self):
		frappe.db.set_value("File", self.doc.name, "th_media_scan_status", av.SCAN_INFECTED)
		self.assertFalse(av.is_servable(self.doc.file_url))

	def test_failed_varsayilanda_servis_edilir(self):
		# Fail-open: taranamayan dosya erişime kapatılmaz, yalnız işaretlenir.
		frappe.db.set_value("File", self.doc.name, "th_media_scan_status", av.SCAN_FAILED)
		self.assertTrue(av.is_servable(self.doc.file_url))

	def test_failed_fail_closed_ta_servis_edilemez(self):
		frappe.db.set_value("File", self.doc.name, "th_media_scan_status", av.SCAN_FAILED)
		with mock.patch.dict(frappe.conf, {"media_av_fail_closed": 1}, clear=False):
			self.assertFalse(av.is_servable(self.doc.file_url))


# ── Kuyruğa alma ────────────────────────────────────────────────────────


class TestKuyrugaAlma(FrappeTestCase):
	def setUp(self):
		self.doc = _yeni_dosya("kuyruk-1.txt")
		self.addCleanup(
			lambda: _sil(self.doc.name)
		)

	def test_pending_yazar_ve_kuyruga_koyar(self):
		with _tarayici(0) as (_calisan, kuyruk):
			sonuc = av.enqueue_scan(self.doc.file_url, self.doc.name)
		self.assertEqual(sonuc["status"], av.SCAN_PENDING)
		self.assertEqual(_durum(self.doc.name), av.SCAN_PENDING)
		kuyruk.assert_called_once()

	def test_ikinci_cagri_idempotent(self):
		"""Aynı dosya iki yoldan tetiklenebilir; iki worker aynı dosyaya yazmasın."""
		with _tarayici(0):
			av.enqueue_scan(self.doc.file_url, self.doc.name)
		with _tarayici(0) as (_calisan, kuyruk):
			sonuc = av.enqueue_scan(self.doc.file_url, self.doc.name)
		self.assertEqual(sonuc.get("skipped"), "already")
		kuyruk.assert_not_called()

	def test_kayitsiz_adres_kontrollu_atlanir(self):
		with _tarayici(0) as (_calisan, kuyruk):
			sonuc = av.enqueue_scan(f"/files/hic-olmayan-{_KOSUM_TUZU}.jpg")
		self.assertEqual(sonuc.get("skipped"), "no_record")
		kuyruk.assert_not_called()

	def test_bos_adres_patlamaz(self):
		self.assertEqual(av.enqueue_scan("").get("skipped"), "no_url")

	def test_kanca_klasoru_atlar(self):
		sahte = frappe._dict({"is_folder": 1, "file_url": "/files/x.jpg", "name": "X"})
		with mock.patch("tradehub_core.media.av.enqueue_scan") as es:
			av.maybe_scan_on_insert(sahte)
		es.assert_not_called()

	def test_kanca_patlarsa_yuklemeyi_dusurmez(self):
		"""Best-effort: kancadaki hata kullanıcının yüklemesini engellememeli."""
		sahte = frappe._dict({"is_folder": 0, "file_url": "/files/x.jpg", "name": "X"})
		with mock.patch("tradehub_core.media.av.enqueue_scan", side_effect=Exception("patla")):
			av.maybe_scan_on_insert(sahte)  # exception dışarı sızmamalı


class TestKancaTetikleme(FrappeTestCase):
	"""`File.after_insert` kancası gerçekten kuyruğa atıyor mu.

	Diğer testlerin fixture'ı (`_insert`) kancayı bilerek nötrlüyor; kancanın
	KENDİ davranışı bu yüzden burada, açıkça sınanıyor. Aksi hâlde fixture'daki
	nötrleme özelliğin hiç sınanmadığını gizlerdi.
	"""

	def test_yeni_dosya_kuyruga_alinir(self):
		with (
			mock.patch("tradehub_core.media.av.scanner_command", return_value=_SAHTE_TARAYICI),
			mock.patch("tradehub_core.media.av.frappe.enqueue") as kuyruk,
		):
			doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"kanca-{_KOSUM_TUZU}.txt",
					"is_private": 0,
					"content": f"kanca testi {_KOSUM_TUZU}".encode(),
				}
			)
			doc.insert(ignore_permissions=True)
		self.addCleanup(lambda: _sil(doc.name))

		self.assertEqual(_durum(doc.name), av.SCAN_PENDING)
		kuyruk.assert_called_once()

	def test_tarayici_yokken_kanca_kuyruga_atmaz(self):
		"""Fail-open: tarayıcı yoksa yükleme yolu hiç dokunulmadan geçmeli."""
		with (
			mock.patch("tradehub_core.media.av.scanner_command", return_value=None),
			mock.patch("tradehub_core.media.av.frappe.enqueue") as kuyruk,
		):
			doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"kanca-kapali-{_KOSUM_TUZU}.txt",
					"is_private": 0,
					"content": f"kanca kapali {_KOSUM_TUZU}".encode(),
				}
			)
			doc.insert(ignore_permissions=True)
		self.addCleanup(lambda: _sil(doc.name))

		self.assertEqual(_durum(doc.name), "")
		kuyruk.assert_not_called()


class TestNullDurumSuzgeci(FrappeTestCase):
	"""Regresyon — "hiç taranmadı" süzgeci NULL satırları da yakalamalı.

	Alan yamayla SONRADAN eklendiği için mevcut kayıtların tamamı NULL, boş
	string DEĞİL (ölçüldü: 5.120 NULL / 30 boş string). İlk yazımda süzgeç
	`["in", ["", None]]` idi; Frappe bunu `IN ('', NULL)` diye çeviriyor ve
	SQL'de hiçbir şey NULL'a eşit olmadığı için NULL satırlar HİÇ eşleşmiyordu.

	Sonucu iki yerde birden sessiz ve ciddiydi: `scan_overview` "30 dosya
	taranmamış" diyordu (gerçek: 5.150) ve `backfill_pending` o 5.120 dosyayı
	hiç kuyruğa alamıyordu — yani geriye dönük tarama, işin %99'unu görmeden
	"bitti" görünürdü. Doğrusu `["is", "not set"]` (`IFNULL(alan, '') = ''`).
	"""

	def setUp(self):
		self.doc = _yeni_dosya("null-durum.txt")
		self.addCleanup(lambda: _sil(self.doc.name))
		# Yamanın varsayılanı boş string yazıyor; mevcut kayıtların gerçek hâlini
		# (NULL) taklit etmek için açıkça NULL'a çekiliyor.
		frappe.db.sql(
			"update tabFile set th_media_scan_status = null where name = %s", (self.doc.name,)
		)

	def test_null_satir_taranmamis_sayilir(self):
		sayi = frappe.db.count(
			"File", {"th_media_scan_status": ["is", "not set"], "name": self.doc.name}
		)
		self.assertEqual(sayi, 1, "NULL durumlu kayıt 'taranmamış' sayılmalı")

	def test_eski_in_suzgeci_null_i_KACIRIR(self):
		"""Hatanın kendisi — yanlış süzgecin neden yanlış olduğunu sabitler."""
		sayi = frappe.db.count(
			"File", {"th_media_scan_status": ["in", ["", None]], "name": self.doc.name}
		)
		self.assertEqual(sayi, 0, "IN ('', NULL) NULL'ı yakalayamaz — bu yüzden kullanılmıyor")

	def test_backfill_null_satiri_kuyruga_alir(self):
		"""Sınanan şey SÜZGEÇ: NULL satır aday listesine giriyor mu.

		`enqueue_scan` MOCK'LU. Gerçeğini çalıştırmak sitedeki yüzlerce dosyayı
		`pending` damgalar ve `_sil` temizliği commit ettiği için o durum KALICI
		olur; ardından süpürücü testleri kendi kayıtları yerine bu artıkları
		bulup düşer. Yaşandı: tek bir test 1.497 dosyayı `pending` bıraktı ve
		`TestSupurucu`'nun dört testini birden düşürdü.
		"""
		with mock.patch("tradehub_core.media.av.enqueue_scan") as es:
			es.return_value = {"status": av.SCAN_PENDING}
			av.backfill_pending(limit=500)
		# `enqueue_scan(file_url, name)` — ad ikinci konumsal argüman.
		adlar = [c.args[1] for c in es.call_args_list if len(c.args) > 1]
		self.assertIn(self.doc.name, adlar, "NULL durumlu dosya geriye dönük taramaya girmeli")

	def test_scan_overview_null_lari_sayar(self):
		sonuc = media_admin.scan_overview()
		# Bu sitede 5.000'den fazla NULL kayıt var; süzgeç bozuksa bu sayı
		# iki haneye düşer.
		self.assertGreater(
			sonuc["counts"]["unscanned"], 100, "taranmamış sayısı NULL'ları içermeli"
		)


# ── Tarama sonucu ───────────────────────────────────────────────────────


class TestTaramaSonucu(FrappeTestCase):
	def setUp(self):
		self.doc = _yeni_dosya("tarama-sonuc.txt")
		self.addCleanup(
			lambda: _sil(self.doc.name)
		)
		self.addCleanup(lambda: _karantinayi_temizle(self.doc.file_url))

	def test_temiz_sonuc_clean_yazar(self):
		with _tarayici(0):
			av._run_scan(self.doc.file_url, self.doc.name)
		self.assertEqual(_durum(self.doc.name), av.SCAN_CLEAN)

	def test_temiz_sonuc_denetime_yazilir(self):
		"""'Tarandı ve temiz' ile 'hiç taranmadı' denetimde ayırt edilebilmeli."""
		with (
			_tarayici(0),
			mock.patch("tradehub_core.media.av.audit.log_media_event") as denetim,
		):
			av._run_scan(self.doc.file_url, self.doc.name)
		denetim.assert_called_once()
		_args, kwargs = denetim.call_args
		self.assertEqual(kwargs.get("action"), "media.scan")
		self.assertEqual((kwargs.get("context") or {}).get("result"), av.SCAN_CLEAN)

	def test_zararli_sonuc_infected_yazar_ve_dosyayi_tasir(self):
		yol = av._live_path(self.doc.file_url)
		self.assertTrue(os.path.exists(yol))

		with _tarayici(1, b"/x: Eicar-Test-Signature FOUND\n"):
			av._run_scan(self.doc.file_url, self.doc.name)

		self.assertEqual(_durum(self.doc.name), av.SCAN_INFECTED)
		# Asıl kapı bu: dosya public ağaçtan FİZİKSEL olarak çıkmalı, çünkü
		# nginx public dosyaları doğrudan servis ediyor ve bayrak alanı onu
		# durdurmaz.
		self.assertFalse(os.path.exists(yol), "zararlı dosya public ağaçta kalmamalı")
		self.assertTrue(os.path.exists(av._quarantine_path(self.doc.file_url)))

	def test_zararli_sonuc_denetime_imzayla_yazilir(self):
		with (
			_tarayici(1, b"/x: Eicar-Test-Signature FOUND\n"),
			mock.patch("tradehub_core.media.av.audit.log_media_event") as denetim,
		):
			av._run_scan(self.doc.file_url, self.doc.name)
		_args, kwargs = denetim.call_args
		self.assertEqual(kwargs.get("action"), "media.quarantine")
		self.assertFalse(kwargs.get("allowed"))
		self.assertEqual((kwargs.get("context") or {}).get("signature"), "Eicar-Test-Signature")

	def test_diskte_olmayan_dosya_hata_saymaz(self):
		"""Çöpe taşınmış/silinmiş dosya taranamaz ama bu bir tarayıcı hatası değil."""
		os.remove(av._live_path(self.doc.file_url))
		with _tarayici(0):
			av._run_scan(self.doc.file_url, self.doc.name)
		self.assertEqual(_durum(self.doc.name), av.SCAN_CLEAN)
		self.assertEqual(_deneme(self.doc.name), 0, "sayaç yakılmamalı")

	def test_kuyruktayken_silinen_dosya_workeri_dusurmez(self):
		frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		with _tarayici(0):
			av._run_scan(self.doc.file_url, self.doc.name)  # sessizce dönmeli


class TestTarayiciYok(FrappeTestCase):
	"""Error/recovery — tarayıcı çökerse 'temiz' varsayılmaz."""

	def test_tarayici_kurulu_degilse_hata_atar(self):
		with mock.patch("tradehub_core.media.av.scanner_command", return_value=None):
			with self.assertRaises(FileNotFoundError):
				av.scan_path("/tmp/x")

	def test_tarayici_hata_kodu_exception_a_cevrilir(self):
		with _tarayici(2, b""):
			with self.assertRaises(RuntimeError):
				av.scan_path("/tmp/x")


# ── Retry ve dead-letter ────────────────────────────────────────────────


class TestRetryVeDeadLetter(FrappeTestCase):
	def setUp(self):
		self.doc = _yeni_dosya("retry-tarama.txt")
		self.addCleanup(
			lambda: _sil(self.doc.name)
		)
		self.addCleanup(lambda: _karantinayi_temizle(self.doc.file_url))

	def _basarisiz(self):
		with _tarayici(0, side_effect=RuntimeError("tarayıcı patladı")) as (_c, kuyruk):
			av._run_scan(self.doc.file_url, self.doc.name)
		return kuyruk

	def test_ilk_hata_sayaci_bir_yapar_failed_yazmaz(self):
		self._basarisiz()
		self.assertEqual(_deneme(self.doc.name), 1)
		self.assertNotEqual(_durum(self.doc.name), av.SCAN_FAILED)

	def test_hata_kuyruga_ANINDA_koymaz_deneme_planlar(self):
		kuyruk = self._basarisiz()
		kuyruk.assert_not_called()
		next_at = frappe.db.get_value("File", self.doc.name, "th_media_scan_next_at")
		self.assertTrue(next_at, "ilk hatadan sonra deneme planlanmalı")
		# Damga geleceğe bakmalı — geçmişse süpürücü hemen alır, backoff yok olur.
		self.assertFalse(jobs.is_due(next_at))

	def test_hak_bitince_failed_yazilir(self):
		frappe.db.set_value(
			"File", self.doc.name, "th_media_scan_attempts", av.MAX_SCAN_ATTEMPTS - 1
		)
		self._basarisiz()
		self.assertEqual(_durum(self.doc.name), av.SCAN_FAILED)
		self.assertEqual(_deneme(self.doc.name), av.MAX_SCAN_ATTEMPTS)

	def test_dead_letter_varsayilanda_karantinaya_atmaz(self):
		frappe.db.set_value(
			"File", self.doc.name, "th_media_scan_attempts", av.MAX_SCAN_ATTEMPTS - 1
		)
		self._basarisiz()
		self.assertTrue(
			os.path.exists(av._live_path(self.doc.file_url)),
			"fail-open: taranamayan dosya erişimde kalmalı",
		)

	def test_dead_letter_fail_closed_ta_karantinaya_atar(self):
		frappe.db.set_value(
			"File", self.doc.name, "th_media_scan_attempts", av.MAX_SCAN_ATTEMPTS - 1
		)
		yol = av._live_path(self.doc.file_url)
		with mock.patch.dict(frappe.conf, {"media_av_fail_closed": 1}, clear=False):
			self._basarisiz()
		self.assertEqual(_durum(self.doc.name), av.SCAN_INFECTED)
		self.assertFalse(os.path.exists(yol), "fail-closed: taranamayan dosya kapatılmalı")

	def test_sayac_db_de_kalici(self):
		self._basarisiz()
		frappe.db.commit()
		self.assertEqual(
			int(frappe.db.get_value("File", self.doc.name, "th_media_scan_attempts") or 0), 1
		)


class TestElleRetry(FrappeTestCase):
	def setUp(self):
		self.doc = _yeni_dosya("elle-retry.txt")
		self.addCleanup(
			lambda: _sil(self.doc.name)
		)

	def test_failed_dosya_sifirlanip_kuyruga_konur(self):
		frappe.db.set_value(
			"File",
			self.doc.name,
			{"th_media_scan_status": av.SCAN_FAILED, "th_media_scan_attempts": 3},
		)
		with _tarayici(0) as (_c, kuyruk):
			sonuc = av.retry_failed(self.doc.file_url)
		self.assertEqual(sonuc["status"], av.SCAN_PENDING)
		self.assertEqual(_deneme(self.doc.name), 0)
		kuyruk.assert_called_once()

	def test_infected_dosya_reddedilir(self):
		"""Zararlı bulgusunu yeniden tarayıp 'belki temiz çıkar' demek olmaz."""
		frappe.db.set_value("File", self.doc.name, "th_media_scan_status", av.SCAN_INFECTED)
		with self.assertRaises(frappe.ValidationError):
			av.retry_failed(self.doc.file_url)

	def test_clean_dosya_reddedilir(self):
		frappe.db.set_value("File", self.doc.name, "th_media_scan_status", av.SCAN_CLEAN)
		with self.assertRaises(frappe.ValidationError):
			av.retry_failed(self.doc.file_url)

	def test_durumu_bos_dosya_reddedilir(self):
		with self.assertRaises(frappe.ValidationError):
			av.retry_failed(self.doc.file_url)

	def test_monkey_bozuk_adresler_kontrollu_hata_verir(self):
		for bozuk in ("", "   ", f"/files/yok-boyle-{_KOSUM_TUZU}.jpg", "javascript:alert(1)"):
			with self.assertRaises(frappe.ValidationError, msg=f"girdi: {bozuk!r}"):
				av.retry_failed(bozuk)


# ── Karantinadan çıkarma ────────────────────────────────────────────────


class TestKarantinadanCikarma(FrappeTestCase):
	def setUp(self):
		self.doc = _yeni_dosya("karantina-geri.txt")
		self.addCleanup(
			lambda: _sil(self.doc.name)
		)
		self.addCleanup(lambda: _karantinayi_temizle(self.doc.file_url))
		with _tarayici(1, b"/x: Test-Sig FOUND\n"):
			av._run_scan(self.doc.file_url, self.doc.name)

	def test_dosya_yerine_doner_ve_durum_temizlenir(self):
		sonuc = av.release_from_quarantine(self.doc.file_url)
		self.assertTrue(sonuc["released"])
		self.assertTrue(os.path.exists(av._live_path(self.doc.file_url)))
		self.assertFalse(os.path.exists(av._quarantine_path(self.doc.file_url)))
		# Durum `clean` DEĞİL boş: dosya taramadan geçmedi, insan kararıyla geldi.
		self.assertEqual(_durum(self.doc.name), "")

	def test_geri_alma_denetime_yazilir(self):
		with mock.patch("tradehub_core.media.av.audit.log_media_event") as denetim:
			av.release_from_quarantine(self.doc.file_url)
		_args, kwargs = denetim.call_args
		self.assertEqual(kwargs.get("action"), "media.quarantine_release")

	def test_karantinada_olmayan_dosya_reddedilir(self):
		av.release_from_quarantine(self.doc.file_url)
		with self.assertRaises(frappe.ValidationError):
			av.release_from_quarantine(self.doc.file_url)

	def test_geri_alinan_dosya_yeniden_taranabilir(self):
		"""Boş durum onu yeniden tarama kapsamına sokmalı."""
		av.release_from_quarantine(self.doc.file_url)
		with _tarayici(0) as (_c, kuyruk):
			sonuc = av.enqueue_scan(self.doc.file_url, self.doc.name)
		self.assertEqual(sonuc["status"], av.SCAN_PENDING)
		kuyruk.assert_called_once()


# ── Süpürücü ────────────────────────────────────────────────────────────


class TestSupurucu(FrappeTestCase):
	def setUp(self):
		self.doc = _yeni_dosya("supurucu-tarama.txt")
		self.addCleanup(
			lambda: _sil(self.doc.name)
		)
		self.addCleanup(lambda: _karantinayi_temizle(self.doc.file_url))

	def _pending_yap(self, **degerler):
		temel = {
			"th_media_scan_status": av.SCAN_PENDING,
			"th_media_scan_attempts": 0,
			"th_media_scan_next_at": None,
			"th_media_scan_started_at": now_datetime(),
		}
		temel.update(degerler)
		frappe.db.set_value("File", self.doc.name, temel)

	def _supur(self):
		with mock.patch("tradehub_core.media.av.frappe.enqueue") as kuyruk:
			av.sweep_stuck_scans(limit=500)
		return kuyruk

	def test_zamani_gelmis_planli_deneme_kuyruga_konur(self):
		self._pending_yap(th_media_scan_next_at=add_to_date(now_datetime(), seconds=-60))
		kuyruk = self._supur()
		cagrilar = [c for c in kuyruk.call_args_list if c.kwargs.get("name") == self.doc.name]
		self.assertEqual(len(cagrilar), 1)

	def test_zamani_gelmemis_deneme_beklemede_kalir(self):
		self._pending_yap(th_media_scan_next_at=add_to_date(now_datetime(), seconds=600))
		kuyruk = self._supur()
		cagrilar = [c for c in kuyruk.call_args_list if c.kwargs.get("name") == self.doc.name]
		self.assertEqual(len(cagrilar), 0)

	def test_gercekten_calisan_is_kayip_sayilmaz(self):
		self._pending_yap(th_media_scan_started_at=now_datetime())
		self._supur()
		self.assertEqual(_deneme(self.doc.name), 0)

	def test_birakilmis_is_basarisizlik_sayilir(self):
		"""Sert kill `except`i çalıştırmaz; sayaç bu yolla ilerlemeli."""
		self._pending_yap(
			th_media_scan_started_at=add_to_date(
				now_datetime(), seconds=-(jobs.STALE_AFTER_SECONDS + 60)
			)
		)
		self._supur()
		self.assertEqual(_deneme(self.doc.name), 1)

	def test_birakilmis_is_hak_bitmisse_dead_lettera_duser(self):
		self._pending_yap(
			th_media_scan_attempts=av.MAX_SCAN_ATTEMPTS - 1,
			th_media_scan_started_at=add_to_date(
				now_datetime(), seconds=-(jobs.STALE_AFTER_SECONDS + 60)
			),
		)
		self._supur()
		self.assertEqual(_durum(self.doc.name), av.SCAN_FAILED)

	def test_damgasiz_kayit_kayip_sayilir(self):
		# Kör nokta olmasın: damga yazılamadan düşen worker da yakalanmalı.
		self._pending_yap(th_media_scan_started_at=None)
		self._supur()
		self.assertEqual(_deneme(self.doc.name), 1)

	def test_dead_letter_bir_daha_supurulmez(self):
		frappe.db.set_value("File", self.doc.name, "th_media_scan_status", av.SCAN_FAILED)
		kuyruk = self._supur()
		cagrilar = [c for c in kuyruk.call_args_list if c.kwargs.get("name") == self.doc.name]
		self.assertEqual(len(cagrilar), 0)


# ── Integration: envanter ───────────────────────────────────────────────


class TestEnvanterTaramaDurumu(FrappeTestCase):
	def setUp(self):
		self.doc = _yeni_dosya("envanter-tarama.txt")
		self.addCleanup(
			lambda: _sil(self.doc.name)
		)

	def test_list_files_scan_status_dondurur(self):
		frappe.db.set_value("File", self.doc.name, "th_media_scan_status", av.SCAN_CLEAN)
		frappe.db.commit()
		sonuc = inventory.list_files(page=1, page_size=200, search="envanter-tarama")
		satir = next((r for r in sonuc["items"] if r["file_url"] == self.doc.file_url), None)
		self.assertIsNotNone(satir, "yüklenen dosya envanterde görünmeli")
		self.assertEqual(satir["scan_status"], av.SCAN_CLEAN)

	def test_taranmamis_dosya_bos_doner_clean_degil(self):
		"""Taranmamışı 'temiz' göstermek bu alanın en tehlikeli yanlışı olurdu."""
		frappe.db.commit()
		sonuc = inventory.list_files(page=1, page_size=200, search="envanter-tarama")
		satir = next((r for r in sonuc["items"] if r["file_url"] == self.doc.file_url), None)
		self.assertEqual(satir["scan_status"], "")


class TestYamaIdempotency(FrappeTestCase):
	def test_yama_iki_kez_calisinca_kirilmaz(self):
		from tradehub_core.patches import v15_9_20_media_scan_fields as yama

		yama.execute()
		ikinci = yama.execute()
		self.assertEqual(ikinci["created"], [], "ikinci koşumda yeni alan oluşmamalı")

	def test_alanlar_gercekten_var(self):
		for alan in (
			"th_media_scan_status",
			"th_media_scan_attempts",
			"th_media_scan_next_at",
			"th_media_scan_started_at",
		):
			self.assertTrue(frappe.db.has_column("File", alan), f"{alan} eksik")


# ── API ─────────────────────────────────────────────────────────────────


class TestAdminAPI(FrappeTestCase):
	def setUp(self):
		self.doc = _yeni_dosya("api-tarama.txt")
		self.addCleanup(
			lambda: _sil(self.doc.name)
		)
		self.addCleanup(lambda: _karantinayi_temizle(self.doc.file_url))

	def test_scan_overview_politikayi_da_dondurur(self):
		"""Tarayıcı yokken panel '0 zararlı' değil 'tarama kapalı' demeli."""
		sonuc = media_admin.scan_overview()
		self.assertIn("policy", sonuc)
		self.assertIn("enabled", sonuc["policy"])
		self.assertIn("unscanned", sonuc["counts"])

	def test_list_quarantine_infected_dosyayi_gosterir(self):
		with _tarayici(1, b"/x: Test-Sig FOUND\n"):
			av._run_scan(self.doc.file_url, self.doc.name)
		frappe.db.commit()
		sonuc = media_admin.list_quarantine(page=1, page_size=200)
		adresler = [r["file_url"] for r in sonuc["items"]]
		self.assertIn(self.doc.file_url, adresler)

	def test_bos_adres_reddedilir(self):
		for uc in (media_admin.retry_scan, media_admin.release_quarantine):
			with self.assertRaises(frappe.ValidationError, msg=uc.__name__):
				uc("")

	def test_rolsuz_kullanici_reddedilir(self):
		# `frappe.only_for` hem Administrator'ı hem `flags.in_test`'i atlar;
		# gerçek reddi görmek için ikisini de kapatmak gerekiyor.
		frappe.set_user("Guest")
		self.addCleanup(lambda: frappe.set_user("Administrator"))
		onceki = frappe.flags.in_test
		frappe.flags.in_test = False
		self.addCleanup(lambda: setattr(frappe.flags, "in_test", onceki))
		with self.assertRaises(frappe.PermissionError):
			media_admin.scan_overview()

	def test_karantinadan_cikarma_yikici_yetki_ister(self):
		"""Zararlı bulgusunu iptal edebilecek kişi sayısı gereksiz büyümemeli."""
		import inspect

		kaynak = inspect.getsource(media_admin.release_quarantine)
		self.assertIn("_guard_destructive", kaynak)


# ── E2E ─────────────────────────────────────────────────────────────────


class TestUctanUca(FrappeTestCase):
	def test_tam_dongu_yukle_tara_karantina_geri_al(self):
		doc = _yeni_dosya("e2e-tarama.txt")
		self.addCleanup(
			lambda: _sil(doc.name)
		)
		self.addCleanup(lambda: _karantinayi_temizle(doc.file_url))

		# 1) Kuyruğa alınır → pending
		with _tarayici(0) as (_c, kuyruk):
			av.enqueue_scan(doc.file_url, doc.name)
		self.assertEqual(_durum(doc.name), av.SCAN_PENDING)
		kuyruk.assert_called_once()

		# 2) Tarayıcı zararlı der → infected + fiziksel karantina
		canli = av._live_path(doc.file_url)
		with _tarayici(1, b"/x: Eicar-Test-Signature FOUND\n"):
			av._run_scan(doc.file_url, doc.name)
		self.assertEqual(_durum(doc.name), av.SCAN_INFECTED)
		self.assertFalse(os.path.exists(canli))
		self.assertFalse(av.is_servable(doc.file_url))

		# 3) Yönetici yanlış pozitif der → dosya yerine döner, durum sıfırlanır
		av.release_from_quarantine(doc.file_url)
		self.assertTrue(os.path.exists(canli))
		self.assertEqual(_durum(doc.name), "")
		self.assertTrue(av.is_servable(doc.file_url))

		# 4) Yeniden taranır, bu kez temiz
		with _tarayici(0):
			av.enqueue_scan(doc.file_url, doc.name)
			av._run_scan(doc.file_url, doc.name)
		self.assertEqual(_durum(doc.name), av.SCAN_CLEAN)

class TestModulKesisimleri(FrappeTestCase):
	"""AV'nin diğer Done işlerle kesişimi — sistem taramasında çıkan kusurlar.

	Her test, iki modülün BİRBİRİNDEN HABERSİZ çalışırken ürettiği gerçek bir
	kırılmayı kilitler; hiçbiri teorik değil.
	"""

	def setUp(self):
		self.doc = _yeni_dosya(f"kesisim-{_KOSUM_TUZU}.mp4")
		self.addCleanup(lambda: _sil(self.doc.name))

	# ── TUR-296 × TUR-125: transcode, bekletmedeki videonun hakkını yakmasın ──

	def test_bekletmedeki_video_transcode_denemesi_YAKMAZ(self):
		"""Kanca sırası: transcode kuyruğa girer, av dosyayı bekletmeye alır.

		Worker dosyayı bulamayınca ffmpeg patlıyor ve deneme hakkı boşuna
		yanıyordu — bekletme + yavaş tarama, sağlıklı videoyu üç turda
		dead-letter'a düşürüyordu.
		"""
		from tradehub_core.media import transcode

		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status",
			transcode.VIDEO_STATUS_PROCESSING, update_modified=False,
		)
		frappe.db.commit()

		with (
			mock.patch("tradehub_core.media.av.in_quarantine", return_value=False),
			mock.patch("tradehub_core.media.av.in_hold", return_value=True),
			mock.patch("tradehub_core.media.transcode.subprocess.run") as ffmpeg,
		):
			transcode._run_transcode(self.doc.file_url, name=self.doc.name)

		ffmpeg.assert_not_called()
		deneme = frappe.db.get_value("File", self.doc.name, "th_media_transcode_attempts")
		self.assertEqual(int(deneme or 0), 0, "bekletme bir başarısızlık değil, sayaç artmamalı")
		# Erteleme planlandı — süpürücü işi tarama bitince yeniden alacak.
		self.assertTrue(frappe.db.get_value("File", self.doc.name, "th_media_transcode_next_at"))
		# Kullanıcı gözünde hâlâ işleniyor.
		self.assertEqual(
			frappe.db.get_value("File", self.doc.name, "th_media_video_status"),
			transcode.VIDEO_STATUS_PROCESSING,
		)

	def test_karantinadaki_video_transcode_dead_letter_olur(self):
		# `processing`de bırakmak sonsuz spinner demek; karantina kalkmadan
		# transcode imkânsız, dead-letter tek dürüst durum.
		from tradehub_core.media import transcode

		with (
			mock.patch("tradehub_core.media.av.in_quarantine", return_value=True),
			mock.patch("tradehub_core.media.transcode.subprocess.run") as ffmpeg,
		):
			transcode._run_transcode(self.doc.file_url, name=self.doc.name)

		ffmpeg.assert_not_called()
		self.assertEqual(
			frappe.db.get_value("File", self.doc.name, "th_media_video_status"),
			transcode.VIDEO_STATUS_FAILED,
		)

	def test_karantinadaki_videonun_elle_retrysi_aciklayici_reddedilir(self):
		from tradehub_core.media import transcode

		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status",
			transcode.VIDEO_STATUS_FAILED, update_modified=False,
		)
		frappe.db.commit()
		with mock.patch("tradehub_core.media.av.in_quarantine", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				transcode.retry_failed(self.doc.file_url)

	# ── TUR-131 × TUR-125: platform geri yüklemesi karantinayı delemez ──

	def test_platform_restore_karantinadaki_dosyayi_geri_yazmaz(self):
		from tradehub_core.media import restore

		sahte_manifest = {
			"set_id": "20260101_000000",
			"files": [
				{
					"scope": "public",
					"path": os.path.basename(self.doc.file_url),
					"size": 1,
					"hash": "0" * 64,
				}
			],
		}
		with (
			mock.patch("tradehub_core.media.backup.manifest_of", return_value=sahte_manifest),
			mock.patch("tradehub_core.media.backup.records_of", return_value=[]),
			mock.patch("tradehub_core.media.av.is_servable", return_value=False),
			mock.patch("tradehub_core.media.backup._blob_path") as blob,
		):
			sonuc = restore.apply("20260101_000000", records=False)

		blob.assert_not_called()
		self.assertEqual(sonuc["files_written"], 0)
		self.assertGreaterEqual(sonuc["skipped_unscanned_count"], 1)

	# ── TUR-123 × TUR-125: replace yeni baytları aklatamaz ──

	def test_replace_yeni_icerigi_yeniden_taramaya_sokar(self):
		from tradehub_core.media import files

		# Eski içerik temiz damgalı olsun — kusur tam buradaydı: yeni baytlar
		# eski damganın arkasına saklanıyordu.
		frappe.db.set_value(
			"File", self.doc.name, "th_media_scan_status", av.SCAN_CLEAN, update_modified=False
		)
		frappe.db.commit()

		with (
			mock.patch("tradehub_core.media.files.ownership.assert_owns"),
			mock.patch("tradehub_core.media.files.ownership.owners_of", return_value={"M1"}),
			mock.patch(
				"tradehub_core.media.av.enqueue_scan",
				return_value={"status": av.SCAN_PENDING},
			) as tarama,
			mock.patch(
				"tradehub_core.media.av.policy",
				return_value={
					"enabled": True,
					"hold_until_clean": False,
					"fail_closed": False,
					"scanner": "clamdscan",
				},
			),
			mock.patch("tradehub_core.media.upload_policy.check") as kapi,
		):
			files.replace(self.doc.file_url, "M1", b"yeni icerik baytlari", "yeni.mp4")

		kapi.assert_called_once()  # yükleme sözleşmesi yeni içeriğe de uygulandı
		tarama.assert_called_once()  # yeniden tarama kuyruğa girdi
		# Damga sıfırlanıp `pending`e geçmeli — eski `clean` yeni içeriği aklamamalı.
		self.assertNotEqual(
			frappe.db.get_value("File", self.doc.name, "th_media_scan_status"),
			av.SCAN_CLEAN,
		)

	def test_replace_politikaya_takilan_icerigi_YAZMAZ(self):
		from tradehub_core.media import files

		yol = frappe.get_doc("File", self.doc.name).get_full_path()
		eski_icerik = open(yol, "rb").read()
		with (
			mock.patch("tradehub_core.media.files.ownership.assert_owns"),
			mock.patch("tradehub_core.media.files.ownership.owners_of", return_value={"M1"}),
			mock.patch(
				"tradehub_core.media.upload_policy.check",
				side_effect=frappe.ValidationError("içerik reddedildi"),
			),
		):
			with self.assertRaises(frappe.ValidationError):
				files.replace(self.doc.file_url, "M1", b"<html>zararli</html>", "x.mp4")

		self.assertEqual(
			open(yol, "rb").read(), eski_icerik, "reddedilen içerik diske yazılmamalı"
		)

	# ── TUR-138 × TUR-131: geri yüklenen kaydın durumu ezilmez ──

	def test_restore_edilen_kaydin_durumu_active_ile_EZILMEZ(self):
		"""14 Ağustos'tan beri açık kusur: `states.on_file_insert` her insert'te
		Active yazıyordu; çöpteki dosya yedekten Active dönüp listeye sızıyordu.
		"""
		from tradehub_core.media import states

		doc = _insert(
			{
				"doctype": "File",
				"file_name": f"trashed-restore-{_KOSUM_TUZU}.txt",
				"is_private": 0,
				"content": f"trashed {_KOSUM_TUZU}".encode(),
				"th_media_state": states.STATE_TRASHED,
			}
		)
		self.addCleanup(lambda: _sil(doc.name))
		self.assertEqual(
			frappe.db.get_value("File", doc.name, "th_media_state"),
			states.STATE_TRASHED,
			"kancanın Active yazması, yedekten dönen çöp dosyayı listeye sızdırır",
		)

	def test_normal_yukleme_hala_active_baslar(self):
		# Düzeltme regresyonu: durumu boş gelen olağan yükleme Active kalmalı.
		from tradehub_core.media import states

		doc = _yeni_dosya(f"normal-{_KOSUM_TUZU}.txt")
		self.addCleanup(lambda: _sil(doc.name))
		self.assertEqual(
			frappe.db.get_value("File", doc.name, "th_media_state"), states.STATE_ACTIVE
		)


class TestPaketTemizligi(FrappeTestCase):
	"""Satıcı paket temizliği — `KEEP_HOURS` ölü sabitti, paketler birikiyordu."""

	def _kur(self, magaza: str, set_id: str, finished: str) -> str:
		import shutil as _shutil

		from tradehub_core.media import seller_backup

		exports = os.path.join(
			frappe.get_site_path("private", seller_backup.ROOT_DIRNAME), magaza, "exports"
		)
		os.makedirs(exports, exist_ok=True)
		self.addCleanup(
			lambda: _shutil.rmtree(os.path.dirname(exports), ignore_errors=True)
		)
		paket = os.path.join(exports, f"medya-yedegim-{set_id}-abc.zip")
		with open(paket, "wb") as fh:
			fh.write(b"paket")
		seller_backup._yaz(
			os.path.join(exports, f"{set_id}.json"),
			{
				"set_id": set_id,
				"state": "hazir",
				"file_name": os.path.basename(paket),
				"finished": finished,
			},
		)
		return paket

	def test_suresi_gecen_satici_paketi_silinir(self):
		from tradehub_core.media import seller_backup, seller_backup_export

		paket = self._kur("TEST-CLEANUP-A", "20260101_000000", "2026-01-01 00:00:00")
		sonuc = seller_backup_export.cleanup()
		self.assertGreaterEqual(sonuc["removed"], 1)
		self.assertFalse(os.path.exists(paket))
		# Durum dosyası ölü indirme bağlantısı göstermemeli.
		d = seller_backup._oku(
			os.path.join(os.path.dirname(paket), "20260101_000000.json")
		)
		self.assertEqual(d.get("state"), "")

	def test_taze_paket_silinmez(self):
		from tradehub_core.media import seller_backup_export

		paket = self._kur("TEST-CLEANUP-B", "20260102_000000", frappe.utils.now())
		seller_backup_export.cleanup()
		self.assertTrue(os.path.exists(paket), "süresi dolmamış paket silinmemeli")

class TestYazmaSonrasiTarama(FrappeTestCase):
	"""Canlı ağaca giren her bayt aynı kapıdan geçer (TUR-125 × 123/131).

	Kanca `File.after_insert`'e bağlı, yani yalnız KAYIT açan yolları görüyor.
	Baytı değiştiren üç yol daha var ve hiçbiri yeni kayıt açmıyor: `replace`,
	platform geri yüklemesi, satıcı geri yüklemesi. Bu yollarda eski damga yeni
	içeriği AKLIYORDU.
	"""

	def setUp(self):
		self.doc = _yeni_dosya(f"yazma-{_KOSUM_TUZU}.txt")
		self.addCleanup(lambda: _sil(self.doc.name))
		# Dosya daha önce taranıp TEMİZ çıkmış olsun — kusur tam buradaydı.
		frappe.db.set_value(
			"File", self.doc.name, "th_media_scan_status", av.SCAN_CLEAN, update_modified=False
		)
		frappe.db.commit()

	def _politika(self, *, enabled=True, hold=False):
		return mock.patch(
			"tradehub_core.media.av.policy",
			return_value={
				"enabled": enabled,
				"hold_until_clean": hold,
				"fail_closed": False,
				"scanner": "clamdscan",
			},
		)

	def test_damga_sifirlanir_ve_yeniden_kuyruga_girer(self):
		with self._politika(), mock.patch(
			"tradehub_core.media.av.frappe.enqueue"
		) as kuyruk:
			sonuc = av.rescan_after_write([self.doc.file_url], reason="test")

		self.assertEqual(sonuc["queued"], 1)
		kuyruk.assert_called_once()
		self.assertEqual(
			frappe.db.get_value("File", self.doc.name, "th_media_scan_status"),
			av.SCAN_PENDING,
			"eski 'clean' damgası yeni baytı aklamamalı",
		)

	def test_sifirlama_ONCE_olmali_yoksa_kural_etkisiz(self):
		"""`enqueue_scan` durumu dolu dosyayı atlıyor (idempotency).

		Sıfırlama sonra yapılsaydı bu fonksiyon sessizce hiçbir şey yapmazdı —
		en tehlikeli hata türü: çalışıyor görünen ama çalışmayan koruma.
		"""
		with self._politika(), mock.patch(
			"tradehub_core.media.av.frappe.enqueue"
		):
			av.rescan_after_write([self.doc.file_url], reason="test")
		# Kuyruğa gerçekten girdiyse durum `pending` olur; atlanmış olsaydı
		# `clean` kalırdı.
		self.assertEqual(
			frappe.db.get_value("File", self.doc.name, "th_media_scan_status"), av.SCAN_PENDING
		)

	def test_politika_bekletme_diyorsa_dosya_canli_agactan_cikar(self):
		with self._politika(hold=True), mock.patch(
			"tradehub_core.media.av.frappe.enqueue"
		):
			sonuc = av.rescan_after_write([self.doc.file_url], reason="test")
		self.assertEqual(sonuc["held"], 1)
		self.assertTrue(av.in_hold(self.doc.file_url))
		# Temizlik: dosyayı yerine koy, sonraki testler etkilenmesin.
		av.release_hold(self.doc.file_url)

	def test_karantinadaki_dosyanin_damgasi_SILINMEZ(self):
		# Bulguyu silmek, karantinayı geçersiz kılmanın sessiz yolu olurdu.
		frappe.db.set_value(
			"File", self.doc.name, "th_media_scan_status", av.SCAN_INFECTED,
			update_modified=False,
		)
		frappe.db.commit()
		with self._politika(), mock.patch(
			"tradehub_core.media.av.in_quarantine", return_value=True
		), mock.patch("tradehub_core.media.av.frappe.enqueue") as kuyruk:
			sonuc = av.rescan_after_write([self.doc.file_url], reason="test")

		kuyruk.assert_not_called()
		self.assertEqual(sonuc["queued"], 0)
		self.assertEqual(
			frappe.db.get_value("File", self.doc.name, "th_media_scan_status"),
			av.SCAN_INFECTED,
		)

	def test_tarayici_kapaliyken_damga_bozulmaz(self):
		# "Denendi, olmadı" ile "hiç denenmedi" farklı şeyler; kapalıyken
		# damgayı silmek bu ayrımı yok ederdi.
		with self._politika(enabled=False):
			sonuc = av.rescan_after_write([self.doc.file_url], reason="test")
		self.assertEqual(sonuc.get("skipped"), "disabled")
		self.assertEqual(
			frappe.db.get_value("File", self.doc.name, "th_media_scan_status"), av.SCAN_CLEAN
		)

	def test_bos_liste_ise_hicbir_sey_yapmaz(self):
		self.assertEqual(av.rescan_after_write([], reason="test")["queued"], 0)
		self.assertEqual(av.rescan_after_write(None, reason="test")["queued"], 0)

	# ── Üç kapının da kuralı çağırdığı ──

	def test_platform_geri_yuklemesi_kurali_cagirir(self):
		from tradehub_core.media import restore

		sahte = {
			"set_id": "20260101_000000",
			"files": [{"scope": "public", "path": "x.txt", "size": 1, "hash": "0" * 64}],
		}
		with (
			mock.patch("tradehub_core.media.backup.manifest_of", return_value=sahte),
			mock.patch("tradehub_core.media.backup.records_of", return_value=[]),
			mock.patch("tradehub_core.media.av.is_servable", return_value=True),
			mock.patch("tradehub_core.media.backup._blob_path", return_value="/dev/null"),
			# Blob VAR ama canlı dosya YOK → "eksik dosya" dalı, yani yazma
			# gerçekleşir. `overwrite` dalına girmeye gerek yok; oradaki
			# `getsize` gerçek diske bakıyor.
			mock.patch(
				"tradehub_core.media.restore.os.path.isfile",
				side_effect=lambda yol: yol == "/dev/null",
			),
			mock.patch("tradehub_core.media.restore.shutil.copy2"),
			mock.patch("tradehub_core.media.restore.os.replace"),
			mock.patch("tradehub_core.media.restore.os.makedirs"),
			mock.patch("tradehub_core.media.av.rescan_after_write") as kural,
		):
			restore.apply("20260101_000000", records=False)

		kural.assert_called_once()
		self.assertEqual(kural.call_args.kwargs.get("reason"), "restore")

	def test_satici_geri_yuklemesi_kurali_cagirir(self):
		from tradehub_core.media import seller_backup

		sahte = {
			"set_id": "20260101_000000",
			"files": [
				{"path": "y.txt", "file_url": "/files/y.txt", "size": 1, "hash": "0" * 64}
			],
		}
		with (
			mock.patch(
				"tradehub_core.media.seller_backup.manifest_of", return_value=sahte
			),
			mock.patch(
				"tradehub_core.media.seller_backup._uploaded_urls",
				return_value={"/files/y.txt"},
			),
			mock.patch(
				"tradehub_core.media.seller_backup._servis_edilebilir", return_value=True
			),
			mock.patch(
				"tradehub_core.media.seller_backup._blob_path", return_value="/dev/null"
			),
			mock.patch(
				"tradehub_core.media.seller_backup._live_path", return_value="/tmp/y.txt"
			),
			mock.patch("tradehub_core.media.seller_backup.os.path.isfile", return_value=False),
			mock.patch("tradehub_core.media.seller_backup.os.makedirs"),
			mock.patch("tradehub_core.media.seller_backup.shutil.copy2"),
			mock.patch("tradehub_core.media.seller_backup.os.replace"),
			mock.patch("tradehub_core.media.av.rescan_after_write") as kural,
		):
			seller_backup.apply("MAGAZA-X", "20260101_000000", records=False)

		kural.assert_called_once()
		self.assertEqual(kural.call_args.kwargs.get("reason"), "seller_restore")

	def test_replace_kurali_cagirir(self):
		from tradehub_core.media import files

		with (
			mock.patch("tradehub_core.media.files.ownership.assert_owns"),
			mock.patch("tradehub_core.media.files.ownership.owners_of", return_value={"M1"}),
			mock.patch("tradehub_core.media.upload_policy.check"),
			mock.patch("tradehub_core.media.av.rescan_after_write") as kural,
		):
			files.replace(self.doc.file_url, "M1", b"yeni baytlar", "y.txt")

		kural.assert_called_once()
		self.assertEqual(kural.call_args.kwargs.get("reason"), "replace")



# ── Ortak sahiplik: yönetici silme kapısı (TUR-298) ─────────────────────


class TestOrtakSahiplikSilme(FrappeTestCase):
	"""İçerik-adresli adlandırmanın silme tarafındaki bedeli.

	Aynı görseli iki satıcı yüklerse diskte TEK dosya, `File` tarafında iki
	kayıt olur (TUR-130). Satıcı tarafı bunu kapsam ayrımıyla çözüyor:
	`seller_media.purge` yalnız kendi kayıtlarını siler, kalan sahip varsa
	dosyaya dokunmaz. Yönetici tarafında bu kontrol YOKTU — bir yöneticinin
	silmesi, haberi olmayan başka satıcıların görselini de siliyordu
	(gerçek veriyle canlandırıldı: 4 kayıt → 0, dosya diskten gitti).

	Yönetici için engel DEĞİL onay kapısı kuruldu: platform sahibinin yasal
	kaldırma ya da zararlı içerik durumunda dosyayı herkesten kaldırabilmesi
	gerekir; amaç durdurmak değil, kaç mağazayı etkilediğini görmeden
	tıklamasını önlemek.
	"""

	def setUp(self):
		self.doc = _yeni_dosya("ortak-sahiplik.txt")
		self.addCleanup(lambda: _sil(self.doc.name))
		self.addCleanup(lambda: _bekletmeyi_temizle(self.doc.file_url))

	def _sahip_sayisi(self, n: int):
		"""`owners_of` n mağaza döndürsün — gerçek mağaza kurmadan."""
		return mock.patch(
			"tradehub_core.media.trash.ownership.owners_of",
			return_value={f"MAGAZA-{i}" for i in range(n)},
		)

	def test_tek_sahipte_engel_yok(self):
		with self._sahip_sayisi(1):
			# Onay verilmeden geçmeli — sıradan bir silme.
			self.assertEqual(trash._assert_not_shared(self.doc.file_url, shared_ok=False), 1)

	def test_cok_sahipte_onaysiz_reddedilir(self):
		with self._sahip_sayisi(4):
			with self.assertRaises(frappe.ValidationError) as ctx:
				trash._assert_not_shared(self.doc.file_url, shared_ok=False)
		# Sayı mesajda GEÇMELİ: "onay gerekiyor" demek yetmez, yönetici kaç
		# mağazayı etkilediğini görmeden karar veremez.
		self.assertIn("4", str(ctx.exception))

	def test_onay_verilirse_gecer(self):
		with self._sahip_sayisi(4):
			self.assertEqual(trash._assert_not_shared(self.doc.file_url, shared_ok=True), 4)

	def test_red_denetime_yazilir(self):
		"""Engellenen silme denemesi iz bırakmalı."""
		with self._sahip_sayisi(3), mock.patch("tradehub_core.media.trash.audit.log_media_event") as d:
			with self.assertRaises(frappe.ValidationError):
				trash._assert_not_shared(self.doc.file_url, shared_ok=False)
		_args, kwargs = d.call_args
		self.assertFalse(kwargs.get("allowed"))
		self.assertIn("shared_owners:3", kwargs.get("reason") or "")
		# Sıradan bir ürün görseli — maskelenmemeli, operatör hangi dosya
		# olduğunu görebilmeli (`_deny` docstring'indeki `in_use` gerekçesi).
		self.assertFalse(kwargs.get("sensitive"))

	def test_owner_count_patlarsa_sifir_doner_ama_kapi_acilmaz(self):
		"""Sahiplik çözülemezse "tek sahip" varsayılmamalı.

		0 dönmek kapıyı açar (0 > 1 değil) — bu bilinçli: sahiplik okunamıyorken
		yöneticiyi kilitlemek, tek bir sorgu hatasında tüm silme akışını durdurur.
		Ama 1 dönmek YANLIŞ olurdu: "tek sahip var" diye bilgi uydurmak olur.
		"""
		with mock.patch(
			"tradehub_core.media.trash.ownership.owners_of", side_effect=RuntimeError("db yok")
		):
			self.assertEqual(trash.owner_count(self.doc.file_url), 0)

	def test_cop_ve_kalici_silme_AYRI_onay_ister(self):
		"""İki adım arasında yeni bir mağaza dosyayı kullanmaya başlayabilir.

		Çöpe taşımadaki onay, kalıcı silme için yeterli sayılmamalı — ilk onayda
		görünmeyen bir sahip ikinci adımda ortaya çıkabilir.
		"""
		import inspect

		for fn in (trash.move_to_trash, trash.delete_permanently):
			self.assertIn(
				"_assert_not_shared", inspect.getsource(fn), f"{fn.__name__} kapıyı çağırmıyor"
			)

	def test_satici_yolu_baskasinin_kaydina_dokunmaz(self):
		"""Regresyon — satıcı tarafındaki mevcut koruma bozulmamalı.

		Bu davranış TUR-298'den önce de doğruydu; yönetici tarafını hizalarken
		satıcı tarafının kapsam ayrımını bozmadığımızı sabitliyor.
		"""
		import inspect

		kaynak = inspect.getsource(seller_media.purge)
		self.assertIn("_own_records", kaynak, "satıcı yalnız kendi kayıtlarını silmeli")
		self.assertIn("owners_of", kaynak, "kalan sahip kontrolü kalkmamalı")

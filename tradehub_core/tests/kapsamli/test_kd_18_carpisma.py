"""KD-18 — Aynı dosyaya müdahale eden alt sistemlerin İLİŞKİSİ.

Bir medya dosyasını fiziksel olarak taşıyan/silen **26 modül** var. Soru şu
değil: "her biri tek başına doğru mu" — bunu KD-01..17 ölçüyor. Soru şu:
**ikisi aynı dosyaya dokunduğunda ne oluyor?**

Bu dosyadaki her iddia önce kod okunarak, sonra **gerçek dosyayla
çalıştırılarak** doğrulandı; grep sayısına dayanan hiçbir sonuç yok.
(Grep `archive.py`'yi "taşıyıcı" sanmıştı; okuyunca öyle olmadığı görüldü —
o modül orijinalin kopyasını saklıyor, canlı dosyayı taşımıyor.)

ORTAM BAĞIMSIZLIĞI: ClamAV bu makinede kurulu değil (`scanner_available()`
False → `policy()["enabled"]` False → hiçbir bekletme olmaz). Bu testler
tarayıcının VARLIĞINI taklit ediyor; aksi hâlde ClamAV'li bir makinede
bambaşka davranırlardı. Memory'deki kural birebir bu: *"bir bağımlılığın
yokluğu üstüne test yazma."*
"""

from __future__ import annotations

import itertools
import os
import time
import unittest
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import av, pipeline_bridge, trash
from tradehub_core.tests.kapsamli import _yardim as y

# ── İÇERİK BENZERSİZLİĞİ ──────────────────────────────────────────────
#
# Depolama İÇERİK-ADRESLİ: aynı baytlar aynı `file_url`'e düşer. Yardımcılar
# sabit ölçüde görsel üretirken bütün testler AYNI dosyayı paylaşıyordu ve
# biri dosyayı bekletmeye/karantinaya/çöpe taşıdığında diğerleri onu orada
# buluyordu (ölçüldü: `_dosya()` varsayılanı her çağrıda
# `/files/7a/7aa9cbe1…jpg`). Sızıntı testler ARASINDA ve koşular ARASINDA
# oluyordu: `_renditions_exist` idempotency kapısı önceki koşunun türevlerini
# görüp yeni iş açmıyor, kontrol kolu ikinci koşuda sahte biçimde 0 üretiyordu.
#
# Çözüm iki katmanlı: her koşu kendi tohumunu alır (koşular ayrışır), her
# çağrı sayaçla ilerler (testler ayrışır).
_KOSU: int = int(time.time()) % 400
_SAYAC = itertools.count()

# Sapma DAR tutuluyor (< 400 piksel). İlk denemede tohum doğrudan kenara
# ekleniyordu ve 1301 + 9000 = 10301² görsel Frappe'nin 25 MB sınırını aştı.
# Koşular arası çakışma riski buradan değil, `tearDown` kalıntı temizliğinden
# kapanıyor: eski türevler silindiği için aynı içeriğin tekrarı zararsız.
_SAPMA_TAVANI: int = 400


def _benzersiz_boyut(taban: int) -> tuple[int, int]:
	"""Bu koşuya ve bu çağrıya özgü (genişlik, yükseklik) — içerik çakışmasın.

	İlk sürüm kenar başına ayrı sayaç çekiyordu ve ÇAKIŞTI (ölçüldü
	2026-08-29): taban 1349 + sayaç c ile taban 1347 + sayaç c+2 aynı ölçüyü,
	dolayısıyla aynı içerik hash'ini ve aynı `file_url`'i üretti; bir testin
	artığı diğerinin türev işini düşürdü. Çakışma iki kenarı FARKLI katsayıyla
	türeterek imkânsız kılınıyor: w = taban + c, h = taban + 2c + 1. İki
	çağrının (w, h) çifti eşit olsa taban_a + c_a = taban_b + c_b ve
	taban_a + 2c_a = taban_b + 2c_b → c_a = c_b, sayaç tekrar etmez.
	"""
	c = (_KOSU + next(_SAYAC)) % _SAPMA_TAVANI
	return taban + c, taban + 2 * c + 1


def _benzersiz_olcu(taban: int) -> int:
	"""Geriye uyum — tek kenar isteyen çağıranlar için; çift için `_benzersiz_boyut`."""
	return _benzersiz_boyut(taban)[0]


def _motor_kalintisini_temizle(dosya_adlari: list[str]) -> None:
	"""Testin KENDİ ürettiği motor kayıtlarını sil.

	`File` siliniyor ama ona bağlı `Media Asset` / `Media Version` /
	`Media Rendition` kalıyordu (ölçüldü: birkaç koşuda 112 → 115). Kalıntı
	yalnız çöp değil, sonraki koşuyu YANILTIYOR: içerik-adresli idempotency
	kapısı eski türevleri görüp yeni üretimi atlıyor.

	Yalnız bu koşuda açılan dosyalara bağlı satırlara dokunulur.
	"""
	for ad in dosya_adlari:
		for varlik in frappe.get_all("Media Asset", filters={"source_file": ad}, pluck="name"):
			for dt, alan in (("Media Rendition", "asset"), ("Media Version", "asset"),
			                 ("Media Metadata Vault", "asset"), ("Media Usage", "asset"),
			                 ("Media Processing Job", "asset")):
				for satir in frappe.get_all(dt, filters={alan: varlik}, pluck="name"):
					try:
						frappe.delete_doc(dt, satir, ignore_permissions=True, force=True,
						                  delete_permanently=True)
					except Exception:
						pass
			try:
				frappe.delete_doc("Media Asset", varlik, ignore_permissions=True, force=True,
				                  delete_permanently=True)
			except Exception:
				pass


def _public_yol(file_url: str) -> str:
	return frappe.get_site_path("public", "files", file_url.split("/files/")[-1])


class _DosyaTemeli(FrappeTestCase):
	"""File açan her fixture tarama kancasını NÖTRLER.

	Gerekçe (memory · TUR-125): ClamAV kurulu bir makinede `after_insert`
	kancası dosyayı `pending` damgalayıp bekletmeye alıyor; kancayı
	nötrlemeyen fixture'lar o makinede kırılıyor. Ölçülmüş olay: kurulum
	6 testi düşürdü.
	"""

	def setUp(self):
		super().setUp()
		self._yamalar = [
			mock.patch("tradehub_core.media.av.enqueue_scan", return_value={"skipped": "test"}),
			mock.patch("tradehub_core.media.av.maybe_scan_on_insert", return_value=None),
		]
		for p in self._yamalar:
			p.start()
			self.addCleanup(p.stop)
		self._acilan: list[str] = []

	def tearDown(self):
		_motor_kalintisini_temizle(self._acilan)
		for ad in self._acilan:
			try:
				frappe.delete_doc("File", ad, ignore_permissions=True, force=True, delete_permanently=True)
			except Exception:
				pass
		# Test edilen kod commit ediyor; DELETE'in de commit edilmesi gerekiyor
		# yoksa rollback siler-gibi yapar ve artık kayıt kalır (memory · TUR-125).
		frappe.db.commit()
		super().tearDown()

	def _dosya(self, ad: str, *, boyut: int = 220, icerik: bytes | None = None) -> str:
		"""Kapsam DIŞI dosya (ek bağı yok) — çarpışma testlerinin taşıyıcısı.

		`icerik` verildiğinde görsel üretilmez; görsel olmayan bir dosyanın
		kapsam kararını ölçmek için gerekli.
		"""
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": ad,
				"is_private": 0,
				"content": icerik if icerik is not None else y.jpeg(*_benzersiz_boyut(boyut)),
			}
		)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self._acilan.append(doc.name)
		return doc.file_url


# ══════════════════════════════════════════════════════════════════════
# 1. Bekletme (AV) ↔ Çöp — iki yön ayrı ayrı
# ══════════════════════════════════════════════════════════════════════


class TestBekletmeVeCop(_DosyaTemeli):
	def test_bi_bekletme_dosyayi_public_agactan_CIKARIYOR(self):
		"""Kurgunun temeli: hold gerçekten fiziksel taşıma."""
		url = self._dosya("kd18-hold-temel.jpg")
		self.assertTrue(os.path.isfile(_public_yol(url)))
		self.assertTrue(av.hold(url))
		self.addCleanup(av.release_hold, url)
		self.assertTrue(av.in_hold(url))
		self.assertFalse(os.path.isfile(_public_yol(url)), "hold dosyayı taşımadı")

	def test_bi_bekletme_is_private_alanini_DEGISTIRMIYOR(self):
		"""`file_url` sözleşmesi korunuyor — kayıt hâlâ public görünüyor.

		Bu, aşağıdaki bulgunun kökü: kapsam kapıları `is_private`e bakıyor,
		dosya ise fiziksel olarak private bir kökte duruyor.
		"""
		url = self._dosya("kd18-hold-private.jpg")
		ad = self._acilan[-1]
		self.assertTrue(av.hold(url))
		self.addCleanup(av.release_hold, url)
		self.assertEqual(frappe.db.get_value("File", ad, "is_private"), 0)

	def test_bi_bekletmedeki_dosya_cope_atilamiyor_ve_MESAJ_DOGRU(self):
		"""F-26 düzeltildi — mesaj sebebi söylüyor.

		Tarama dosyayı public ağaçtan fiziksel olarak çıkarıyor, `file_url`
		değişmiyor. `move_to_trash` bunu "Dosya diskte bulunamadı" diye
		raporluyordu ve operatör kaydın bozulduğunu sanıyordu. Ölçüldü: ClamAV
		kuruluyken TAZE yüklenen her dosya insert anında bekletmeye giriyor,
		yani yanlış mesaj istisnai değil normal yoldu.
		"""
		url = self._dosya("kd18-hold-cop.jpg")
		self.assertTrue(av.hold(url))
		with self.assertRaises(Exception) as ctx:
			trash.move_to_trash(url, force=True)
		mesaj = str(ctx.exception)
		self.assertIn("tarama", mesaj.lower(), mesaj)
		self.assertNotIn("bulunamadı", mesaj, "eski yanıltıcı mesaj geri geldi")

	def test_bi_karantinadaki_dosya_cope_TASINAMAZ(self):
		"""Karantina → çöp yolu KAPALI olmalı — güvenlik kararı.

		Çöp geri alınabilir bir yer ve `restore_from_trash` yeniden tarama
		yapmıyor (kodda doğrulandı). Taşımaya izin vermek
		"karantina → çöp → geri yükle" zinciriyle zararlıyı public ağaca
		döndüren bir yol açardı.
		"""
		url = self._dosya("kd18-karantina-cop.jpg")
		av._tasi(av._live_path(url), av._quarantine_path(url))
		try:
			with self.assertRaises(Exception) as ctx:
				trash.move_to_trash(url, force=True)
			mesaj = str(ctx.exception)
			self.assertIn("karantina", mesaj.lower(), mesaj)
			self.assertFalse(trash.in_trash(url), "zararlı dosya çöp ağacına taşındı")
		finally:
			av._tasi(av._quarantine_path(url), av._live_path(url))

	def test_bi_gercekten_kayip_dosya_ESKI_mesaji_koruyor(self):
		"""Üçüncü durum karışmamalı: dosya AV'de değil, gerçekten yok."""
		url = self._dosya("kd18-gercek-kayip.jpg")
		os.remove(_public_yol(url))
		with self.assertRaises(Exception) as ctx:
			trash.move_to_trash(url, force=True)
		self.assertIn("bulunamadı", str(ctx.exception))

	def test_bi_copteki_dosya_bekletmeye_ALINAMIYOR_ve_bu_dogru(self):
		"""Ters yön TEMİZ: `hold()` dosyayı bulamayınca sessizce False dönüyor,
		çöp durumu bozulmuyor, geri yükleme çalışıyor."""
		url = self._dosya("kd18-trash-hold.jpg")
		trash.move_to_trash(url, force=True)
		frappe.db.commit()
		self.assertTrue(trash.in_trash(url))

		self.assertFalse(av.hold(url), "çöpteki dosya bekletmeye alındı")
		self.assertFalse(av.in_hold(url))
		self.assertTrue(trash.in_trash(url), "hold denemesi çöp durumunu bozdu")

		trash.restore(url)
		frappe.db.commit()
		self.assertTrue(os.path.isfile(_public_yol(url)), "geri yükleme dosyayı koymadı")
		self.assertFalse(av.in_hold(url))

	def test_bi_bekletme_geri_alinabiliyor(self):
		url = self._dosya("kd18-hold-release.jpg")
		self.assertTrue(av.hold(url))
		self.assertFalse(os.path.isfile(_public_yol(url)))
		self.assertTrue(av.release_hold(url))
		self.assertTrue(os.path.isfile(_public_yol(url)), "release dosyayı geri koymadı")
		self.assertFalse(av.in_hold(url))

	def test_bi_release_hold_bekletmede_olmayan_dosyada_False(self):
		url = self._dosya("kd18-release-bos.jpg")
		self.assertFalse(av.release_hold(url))


# ══════════════════════════════════════════════════════════════════════
# 2. Bekletme (AV) ↔ Motor türev üretimi
# ══════════════════════════════════════════════════════════════════════


class TestBekletmeVeMotor(_DosyaTemeli):
	"""`hooks.py` yorumu niyeti açıkça yazıyor:

	    "durum damgası, denetim kaydı, transcode ve zararlı içerik taraması
	     yeni hattan ÖNCE koşmalı ki bir türev işi taranmamış/karantinaya
	     girecek bir dosyayı işlemeye başlamasın"

	Niyet doğru ve kanca sırası bunu sağlıyor. Bu sınıf niyetin TUTTUĞUNU
	doğruluyor — ve tutmasının bıraktığı boşluğu ölçüyor.
	"""

	def test_bi_kanca_sirasi_AV_motordan_ONCE(self):
		"""Sıra sözleşmesi kilidi — biri yer değiştirirse test kırılır."""
		from tradehub_core import hooks

		sira = hooks.doc_events["File"]["after_insert"]
		av_i = sira.index("tradehub_core.media.av.maybe_scan_on_insert")
		motor_i = sira.index("tradehub_core.media.pipeline_bridge.maybe_generate_renditions")
		self.assertLess(av_i, motor_i, "AV kancası motor kancasından SONRA çalışıyor")

	def test_bi_motor_bekletmedeki_dosyada_SESSIZCE_hicbir_sey_uretmiyor(self):
		"""Ölçüldü: hata yok, sahte türev yok, hold bozulmuyor — güvenli.

		Ama sessiz: ne bir bulgu ne bir kayıt kalıyor. "Neden bu dosyanın
		türevi yok" sorusunun cevabı hiçbir yerde yazmıyor.
		"""
		url = self._dosya("kd18-motor-hold.jpg", boyut=1200)
		ad = self._acilan[-1]
		self.assertTrue(av.hold(url))
		self.addCleanup(av.release_hold, url)

		try:
			pipeline_bridge._run_rendition_job(file_url=url)
		except Exception as exc:  # noqa: BLE001
			self.fail(f"motor bekletmedeki dosyada patladı: {type(exc).__name__}: {exc}")

		if frappe.db.has_column("Media Asset", "source_file"):
			self.assertEqual(
				frappe.db.count("Media Asset", {"source_file": ad}), 0,
				"bekletmedeki dosyadan Media Asset üretildi",
			)
		self.assertTrue(av.in_hold(url), "motor hold'u bozdu")

	def test_bi_release_hold_tetiklemesi_KAPILARI_atlamiyor(self):
		"""Tetikleme `maybe_generate_renditions` üzerinden gidiyor, kısayol değil.

		Kapsam dışı bir dosya beklemeden dönerse iş AÇILMAMALI — aksi hâlde
		düzeltme, hattın kapsam kararını by-pass eden ikinci bir yol olurdu.
		"""
		url = self._dosya("kd18-kapsam-disi.txt", boyut=0, icerik=b"duz metin")
		self.assertTrue(av.hold(url))
		with mock.patch("frappe.enqueue") as sahte_kuyruk:
			av.release_hold(url)
		self.assertEqual(
			[c for c in sahte_kuyruk.call_args_list if "pipeline_bridge" in str(c)], [],
			"kapsam dışı dosya için türev işi açıldı",
		)

	def test_bi_release_hold_dosya_kaydi_yoksa_patlamiyor(self):
		"""`File` kaydı olmayan bir adres için tetikleme sessizce geçmeli."""
		url = self._dosya("kd18-kayitsiz.jpg", boyut=900)
		ad = frappe.db.get_value("File", {"file_url": url}, "name")
		frappe.delete_doc("File", ad, ignore_permissions=True, force=True, delete_permanently=True)
		frappe.db.commit()
		self.assertTrue(av.hold(url))
		self.assertTrue(av.release_hold(url), "kayıt yokluğu geri koymayı engellememeli")

	def test_bi_YEDEK_AG_geri_doldurma_ucu_var(self):
		"""Boşluğu kapatabilecek tek mekanizma — varlığı sabitleniyor."""
		self.assertTrue(callable(pipeline_bridge.enqueue_catalog_backfill))
		self.assertTrue(callable(pipeline_bridge.rendition_backfill_status))
		durum = pipeline_bridge.rendition_backfill_status()
		self.assertIsInstance(durum, dict)


class TestGercekTarayiciIleF27(FrappeTestCase):
	"""F-27'nin GERÇEK tarayıcıyla, mock'suz kanıtı.

	Yukarıdaki testler bekletmeyi elle tetikliyor. Bu sınıf ClamAV kuruluyken
	tam zinciri koşturur: gerçek `after_insert` kancası → gerçek `hold()` →
	gerçek `_run_scan()` → gerçek `release_hold()`.

	Tarayıcı yoksa `skipTest` — ölçülemeyen şey "geçti" sayılmaz.

	KONTROL ŞART: "bekletmede 0 türev" tek başına hiçbir şey kanıtlamaz, çünkü
	kapsam dışı bir dosya da 0 üretir. İlk ölçümde tam olarak bu tuzağa
	düşüldü. Bu yüzden AYNI dosya bekletme kalktıktan sonra tekrar denenir:
	0 → 1 farkı, farkın sebebinin bekletme olduğunu gösterir.
	"""

	def setUp(self):
		super().setUp()
		if not av.scanner_available():
			self.skipTest(f"AV tarayıcısı yok ({av.scanner_command()}) — F-27 canlı ölçülemiyor")
		if not av.policy().get("hold_until_clean"):
			self.skipTest("hold_until_clean kapalı — bekletme hiç olmuyor")
		self._acilan: list[str] = []

	def tearDown(self):
		_motor_kalintisini_temizle(self._acilan)
		for ad in self._acilan:
			try:
				frappe.delete_doc("File", ad, ignore_permissions=True, force=True, delete_permanently=True)
			except Exception:
				pass
		frappe.db.commit()
		super().tearDown()

	def _kapsamdaki_dosya(self, ad: str, olcu: int):
		"""Motorun KAPSAMINA giren dosya — Listing.primary_image slotu.

		Kapsam dışı dosya her hâlükârda 0 türev üretir; kontrolün anlamlı
		olması için dosyanın gerçekten işlenebilir olması gerekiyor.
		"""
		ilan = frappe.db.sql("SELECT name FROM `tabListing` ORDER BY name LIMIT 1", as_dict=True)
		if not ilan:
			self.skipTest("Listing yok — kapsama giren dosya kurulamıyor")
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": ad,
				"is_private": 0,
				"attached_to_doctype": "Listing",
				"attached_to_field": "primary_image",
				"attached_to_name": ilan[0]["name"],
				"content": y.jpeg(*_benzersiz_boyut(olcu)),
			}
		)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self._acilan.append(doc.name)
		return doc

	def _asset_sayisi(self, ad: str) -> int:
		return frappe.db.count("Media Asset", {"source_file": ad})

	def test_bi_F27_CANLI_tarama_bitince_turev_KENDILIGINDEN_uretiliyor(self):
		"""Ölçüm — gerçek ClamAV 1.4.3, mock yok, tam zincir.

		Düzeltmeden ÖNCE (2026-08-28):
		    1) bekletme sürerken türev işi   → 0 Media Asset
		    2) tarama bitti, dosya geri geldi → 0  ← kopan halka
		    3) AYNI dosya, türev işi elle     → 1
		    K) kontrol: hiç bekletilmemiş dosya → 1

		Düzeltmeden SONRA (2) adımı kendiliğinden > 0 üretmeli. (1) ile (2)
		arasındaki tek fark taramanın bitmesidir; kontrol kolu (K) ayrı testte
		aynı yolun bekletmesiz hâlini ölçüyor.
		"""
		d = self._kapsamdaki_dosya("kd18-f27-canli.jpg", 1301)
		self.assertEqual(
			pipeline_bridge._resolve_scope(frappe.get_doc("File", d.name)), "product.image",
			"kurgu: dosya motorun kapsamına girmeli",
		)
		self.assertTrue(av.in_hold(d.file_url), "gerçek kanca dosyayı bekletmeye almadı")

		pipeline_bridge._run_rendition_job(file_url=d.file_url)
		self.assertEqual(self._asset_sayisi(d.name), 0, "bekletmedeki dosyadan türev üretildi")

		# Tetikleme İŞİ KUYRUĞA ALIR, senkron üretmez — test koşusunda worker
		# yok, o yüzden önce kuyruğa girdiği ölçülüyor, sonra iş elle
		# çalıştırılıp gerçekten türev ürettiği doğrulanıyor. "Kuyruğa girdi"
		# tek başına yetmez: yanlış argümanla girmiş olabilir.
		with mock.patch("frappe.enqueue") as sahte_kuyruk:
			av._run_scan(d.file_url, d.name)
		frappe.db.commit()
		self.assertFalse(av.in_hold(d.file_url), "tarama sonrası bekletme kalkmadı")

		turev = [
			c for c in sahte_kuyruk.call_args_list
			if "_run_rendition_job" in str(c)
		]
		self.assertEqual(
			len(turev), 1,
			f"F-27 geri geldi — tarama bitti ama türev işi açılmadı: {sahte_kuyruk.call_args_list}",
		)
		self.assertEqual(
			turev[0].kwargs.get("file_url"), d.file_url,
			"iş açıldı ama BAŞKA bir dosya için",
		)

		pipeline_bridge._run_rendition_job(**{"file_url": turev[0].kwargs["file_url"]})
		self.assertGreater(
			self._asset_sayisi(d.name), 0,
			"kuyruğa giren iş çalıştırıldı ama türev üretmedi",
		)

	def test_bi_KONTROL_bekletilmeyen_dosya_turev_uretiyor(self):
		"""Kontrol kolu: bekletme olmadan aynı yol 1 türev üretiyor.

		İçerik BENZERSİZ olmalı: motor içerik-adresli idempotency uyguluyor
		(`_renditions_exist`), aynı baytlar ikinci kez türev açtırmıyor. İlk
		kurguda kontrol bu yüzden yanlışlıkla 0 üretmişti.
		"""
		with mock.patch("tradehub_core.media.av.maybe_scan_on_insert", return_value=None):
			d = self._kapsamdaki_dosya("kd18-f27-kontrol.jpg", 1303)
		self.assertFalse(av.in_hold(d.file_url))
		pipeline_bridge._run_rendition_job(file_url=d.file_url)
		self.assertGreater(self._asset_sayisi(d.name), 0, "kontrol kolu türev üretmedi")

	def test_bi_EICAR_uctan_uca_karantinaya_giriyor(self):
		"""Gerçek zararlı içerik: pending → infected → karantina → servis dışı."""
		EICAR = (
			b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
		)
		doc = frappe.get_doc(
			{"doctype": "File", "file_name": "kd18-eicar.txt", "is_private": 0, "content": EICAR}
		)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self._acilan.append(doc.name)

		av._run_scan(doc.file_url, doc.name)
		frappe.db.commit()

		self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_scan_status"), "infected")
		self.assertTrue(av.in_quarantine(doc.file_url), "zararlı dosya karantinaya alınmadı")
		self.assertFalse(av.is_servable(doc.file_url), "karantinadaki dosya servis edilebilir")
		self.assertFalse(os.path.isfile(_public_yol(doc.file_url)), "zararlı dosya public ağaçta")

	def test_bi_temiz_dosya_taramadan_sonra_servis_edilebilir(self):
		d = self._kapsamdaki_dosya("kd18-temiz-servis.jpg", 1307)
		av._run_scan(d.file_url, d.name)
		frappe.db.commit()
		self.assertEqual(frappe.db.get_value("File", d.name, "th_media_scan_status"), "clean")
		self.assertTrue(av.is_servable(d.file_url))
		self.assertTrue(os.path.isfile(_public_yol(d.file_url)))

	def test_bi_scanner_health_DAEMON_SAGLIGINI_olcuyor(self):
		"""F-28 düzeltildi — "kurulu mu" ile "çalışıyor mu" artık ayrı sorular.

		`clamdscan` bir istemci; iş `clamd` daemon'ında. `shutil.which` bu farkı
		göremiyor. `scanner_health()` daemon'a gerçekten soruyor.
		"""
		saglik = av.scanner_health(refresh=True)
		self.assertTrue(saglik["ok"])
		self.assertTrue(saglik["scanner"], "sağlıklı tarayıcı adı boş")
		adlar = {a["name"] for a in saglik["candidates"]}
		self.assertEqual(adlar, {"clamdscan", "clamscan"}, "aday listesi daraldı")
		for a in saglik["candidates"]:
			self.assertIn("installed", a)
			self.assertIn("healthy", a)

	def test_bi_saglik_yoklamasi_clamdscan_icin_PING_kullaniyor(self):
		"""`--version` daemon'a gitmiyor — yoklama ancak `--ping` ile yoklama olur.

		Ölçüldü (2026-09-12, daemon kapalıyken): `clamdscan --version` stderr'e
		"Could not connect to clamd" basıp rc=0 döndü; `--ping 1` rc=21 verdi.
		`clamscan` ise `--ping` tanımıyor, onun için `--version` kalıyor.
		"""
		gorulen: list[list[str]] = []

		def sahte_run(args, **_kw):
			gorulen.append(list(args))
			return mock.Mock(returncode=0, stdout=b"PONG", stderr=b"")

		with mock.patch.object(av.subprocess, "run", side_effect=sahte_run):
			av._saglik_yoklamasi("/usr/bin/clamdscan")
			av._saglik_yoklamasi("/usr/bin/clamscan")

		self.assertEqual(gorulen[0][1:], ["--ping", "1"], "clamdscan --ping ile yoklanmalı")
		self.assertEqual(gorulen[1][1:], ["--version"], "clamscan --version ile yoklanmalı")

	def test_bi_saglik_yoklamasi_OLU_daemonu_goruyor(self):
		"""Regresyon: ölçülen gerçek çıktı — ulaşılamayan daemon `healthy=False` olmalı."""
		olculen = mock.Mock(
			returncode=21,
			stdout=b"",
			stderr=b"ERROR: Could not connect to clamd on LocalSocket /var/run/clamav/clamd.ctl: "
			b"Connection refused\nPING timeout exceeded; No response from clamd\n",
		)
		with mock.patch.object(av.subprocess, "run", return_value=olculen):
			saglikli, detay = av._saglik_yoklamasi("/usr/bin/clamdscan")
		self.assertFalse(saglikli, "daemon ulaşılamazken yoklama sağlıklı dedi")
		self.assertIn("Could not connect", detay)

	def test_bi_saglik_POLITIKAYA_baglanmiyor_fail_open_acmiyor(self):
		"""Bu testin kendisi bir düzeltmenin düzeltmesi.

		F-28'in ilk hâli `policy()["enabled"]`i sağlığa bağlıyordu. Sonuç:
		clamd bir an düştüğünde `hold_until_clean` de kapanıyor ve o aralıkta
		yüklenen dosyalar TARANMADAN public ağaca çıkıyordu — çözdüğünden kötü
		bir fail-open. Kurulum niyeti belirtir; daemon'ın anlık durumu tarama
		anında ele alınır.
		"""
		with mock.patch.object(av, "_saglik_yoklamasi", return_value=(False, "ölü")):
			av.scanner_health(refresh=True)
			pol = av.policy()
			self.assertTrue(pol["enabled"], "daemon düştü diye tarama kapandı — fail-open")
			self.assertTrue(pol["hold_until_clean"], "daemon düştü diye bekletme kapandı — fail-open")
			self.assertTrue(av.scanner_available())
		av.scanner_health(refresh=True)

	def test_bi_scan_path_asili_daemonda_YEDEGE_dusuyor(self):
		"""Asılı daemon → `clamscan` ile tarama tamamlanıyor.

		Ölçüldü (container, 2026-08-28): daemon SIGSTOP ile dondurulduğunda
		`clamdscan` hata VERMİYOR, donuyor (`timeout` rc=124). "Hızlı hata
		verir" varsayımı yanlıştı; kurtarma zaman aşımını da yakalamalı.
		"""
		gercek = av._tara
		cagrilar: list[str] = []

		def sahte(cmd, path):
			cagrilar.append(os.path.basename(cmd[0]))
			if "clamdscan" in cmd[0]:
				raise __import__("subprocess").TimeoutExpired(cmd[0], 120)
			return gercek(cmd, path)

		with mock.patch.object(av, "_tara", side_effect=sahte):
			sonuc, _imza = av.scan_path("/etc/hostname")

		self.assertEqual(sonuc, av.SCAN_CLEAN)
		self.assertEqual(cagrilar, ["clamdscan", "clamscan"], "yedeğe düşülmedi")

	def test_bi_scan_path_tarayici_HATA_KODUNDA_da_yedegi_deniyor(self):
		"""Zaman aşımı tek arıza biçimi değil; rc>=2 de daemon arızası olabilir."""
		gercek = av._tara
		cagrilar: list[str] = []

		def sahte(cmd, path):
			cagrilar.append(os.path.basename(cmd[0]))
			if "clamdscan" in cmd[0]:
				raise RuntimeError("tarayıcı hata kodu 2: could not connect to clamd")
			return gercek(cmd, path)

		with mock.patch.object(av, "_tara", side_effect=sahte):
			sonuc, _imza = av.scan_path("/etc/hostname")
		self.assertEqual(sonuc, av.SCAN_CLEAN)
		self.assertEqual(cagrilar, ["clamdscan", "clamscan"])

	def test_bi_yedek_de_basarisizsa_HATA_YUKSELIYOR(self):
		""""Emin değilsek temiz" DEMİYORUZ — `scan_path` sözleşmesinin ilk kuralı."""
		with mock.patch.object(av, "_tara", side_effect=RuntimeError("iki tarayıcı da öldü")):
			with self.assertRaises(RuntimeError):
				av.scan_path("/etc/hostname")

	def test_bi_yedek_komut_tercih_sirasini_izliyor(self):
		"""Yedek her zaman daha BAĞIMSIZ taraf: clamdscan → clamscan, sonrası yok."""
		clamd = av.scanner_command()
		self.assertIn("clamdscan", clamd[0])
		yedek = av._yedek_komut(clamd)
		self.assertIsNotNone(yedek)
		self.assertIn("clamscan", yedek[0])
		self.assertNotIn("clamdscan", yedek[0])
		self.assertIsNone(av._yedek_komut(yedek), "clamscan'in yedeği olmamalı")

	def test_bi_saglik_bilgisi_ONBELLEKLENIYOR(self):
		"""Tanı çağrısı ucuz olmalı — süreç içi memo + Redis, iki katman."""
		av.scanner_health(refresh=True)
		with mock.patch.object(av, "_saglik_yoklamasi", side_effect=AssertionError("yoklama tekrarlandı")):
			for _ in range(20):
				self.assertTrue(av.scanner_health()["ok"])

	def test_bi_scanner_command_KURULU_olani_ucuz_donduruyor(self):
		"""Karar yolunda alt süreç açılmamalı — `policy()` her insert'te çağrılıyor."""
		with mock.patch.object(av, "_saglik_yoklamasi", side_effect=AssertionError("yoklama yapıldı")):
			komut = av.scanner_command()
			self.assertIsNotNone(komut)
			self.assertIn("clamdscan", komut[0], "tercih sırası clamdscan olmalı")
			self.assertTrue(av.scanner_available())
			self.assertTrue(av.policy()["enabled"])


# ══════════════════════════════════════════════════════════════════════
# 2b. File silme ↔ motor kayıtları (F-33)
# ══════════════════════════════════════════════════════════════════════


class TestFileSilmeMotorKayitlari(FrappeTestCase):
	"""F-33 — kaynak `File` silinince motor kayıtları ve türevler ne oluyor.

	Ölçüldü (2026-08-29): `trash.purge_expired` File'ı kalıcı siliyor ama
	hiçbir kod Media Asset / Version / Rendition satırlarını ve türev
	DOSYALARINI silmiyordu. Her silinen ürün görseli 1 varlık + ~16 türev
	dosyası bırakıyordu. Daha kötüsü `_renditions_exist` yetim varlığı görüp
	aynı içeriğin yeni yüklemesine "zaten üretildi" diyordu — sessiz türevsizlik.
	"""

	def setUp(self):
		super().setUp()
		from tradehub_core.tests.av_notr import notrle

		notrle(self)
		self._acilan: list[str] = []
		ilan = frappe.db.sql("SELECT name FROM `tabListing` ORDER BY name LIMIT 1", as_dict=True)
		if not ilan:
			self.skipTest("Listing yok — kapsama giren dosya kurulamıyor")
		self._listing = ilan[0]["name"]

	def tearDown(self):
		_motor_kalintisini_temizle(self._acilan)
		for ad in self._acilan:
			try:
				frappe.delete_doc("File", ad, ignore_permissions=True, force=True, delete_permanently=True)
			except Exception:
				pass
		frappe.db.commit()
		super().tearDown()

	def _turevli_dosya(self, ad: str, olcu: int):
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": ad,
				"is_private": 0,
				"attached_to_doctype": "Listing",
				"attached_to_field": "primary_image",
				"attached_to_name": self._listing,
				"content": y.jpeg(*_benzersiz_boyut(olcu)),
			}
		)
		# `enqueue` KİLİTLİ: kuyruk worker'ları canlıyken `after_insert` işi
		# kuyruğa atıyor ve worker, testin kendi `_run_rendition_job` çağrısıyla
		# aynı varlığı üretmek için YARIŞIYOR (ölçüldü: tek başına geçen test
		# modül içinde `IndexError` — varlık henüz commit edilmemiş). Testi
		# süren iş burada, worker değil.
		with mock.patch("frappe.enqueue"):
			doc.insert(ignore_permissions=True)
			frappe.db.commit()
		self._acilan.append(doc.name)
		pipeline_bridge._run_rendition_job(file_url=doc.file_url)
		frappe.db.commit()
		return doc

	def _kayitlar(self, dosya_adi: str):
		varliklar = frappe.get_all("Media Asset", filters={"source_file": dosya_adi}, pluck="name")
		turevler = frappe.get_all(
			"Media Rendition",
			filters={"asset": ["in", varliklar or ["-"]]},
			fields=["name", "state", "file_url", "trash_path"],
		)
		surumler = frappe.db.count("Media Version", {"asset": ["in", varliklar or ["-"]]})
		return varliklar, turevler, surumler

	def test_bi_kanca_hooks_te_kayitli(self):
		from tradehub_core import hooks

		self.assertIn(
			"tradehub_core.media.pipeline_bridge.cleanup_on_file_trash",
			hooks.doc_events["File"]["on_trash"],
		)

	def test_bi_File_silinince_varlik_ve_surum_GIDIYOR_turevler_COPE(self):
		d = self._turevli_dosya("kd18-f33-cascade.jpg", 1341)
		varliklar, turevler, surumler = self._kayitlar(d.name)
		self.assertEqual(len(varliklar), 1, "kurgu: türev üretilmedi")
		self.assertGreater(len(turevler), 0)
		canli = [frappe.get_site_path("public", t["file_url"].lstrip("/")) for t in turevler]
		self.assertTrue(all(map(os.path.isfile, canli)), "kurgu: türev dosyaları diskte değil")
		turev_adlari = [t["name"] for t in turevler]

		frappe.delete_doc("File", d.name, ignore_permissions=True, force=True, delete_permanently=True)
		frappe.db.commit()

		v2, _, s2 = self._kayitlar(d.name)
		self.assertEqual(v2, [], "F-33 geri geldi — varlık kaldı")
		self.assertEqual(s2, 0, "sürüm satırı kaldı")
		self.assertFalse(any(map(os.path.isfile, canli)), "türev dosyası canlı diskte kaldı")
		satirlar = frappe.get_all(
			"Media Rendition", filters={"name": ["in", turev_adlari]}, fields=["state", "trash_path"]
		)
		self.assertEqual({r["state"] for r in satirlar}, {"purged"}, "türevler çöp kapısından geçmedi")
		# Kalıcı SİLİNMİYOR — geri alınabilir çöp; kalıcı silme bakım işinin.
		for r in satirlar:
			self.assertTrue(r["trash_path"], "çöp yolu yazılmadı")
			self.assertTrue(os.path.isfile(frappe.get_site_path(r["trash_path"])), "çöp dosyası yok")

	def test_gv_silinmis_icerigin_YENIDEN_yuklemesi_turevsiz_kalmiyor(self):
		"""F-33a — purged türev 'var' sayılmaz; idempotency kapısı yeniden üretime izin verir."""
		d = self._turevli_dosya("kd18-f33-idem.jpg", 1343)
		h = pipeline_bridge.content_fingerprint(d)
		self.assertTrue(pipeline_bridge._renditions_exist(h, "product.image"))
		frappe.delete_doc("File", d.name, ignore_permissions=True, force=True, delete_permanently=True)
		frappe.db.commit()
		self.assertFalse(
			pipeline_bridge._renditions_exist(h, "product.image"),
			"F-33a geri geldi — purged türev hâlâ 'var' sayılıyor",
		)

	def test_bi_legal_hold_daki_varliga_DOKUNULMUYOR(self):
		d = self._turevli_dosya("kd18-f33-hold.jpg", 1347)
		varliklar, turevler, _ = self._kayitlar(d.name)
		frappe.db.set_value("Media Asset", varliklar[0], "legal_hold", 1)
		frappe.db.commit()
		try:
			frappe.delete_doc("File", d.name, ignore_permissions=True, force=True, delete_permanently=True)
			frappe.db.commit()
			v2, t2, s2 = self._kayitlar(d.name)
			self.assertEqual(v2, varliklar, "hold altındaki varlık silindi")
			self.assertEqual({t["state"] for t in t2}, {"ready"}, "hold altındaki türev çöpe gitti")
			self.assertEqual(s2, 1)
			kayit = frappe.get_all(
				"Authorization Decision Log",
				filters={"action": "media.trash", "context": ["like", "%legal_hold_asset_orphaned%"]},
				limit=1,
			)
			self.assertTrue(kayit, "hold altında sahipsiz kalan varlık denetime yazılmadı")
		finally:
			frappe.db.set_value("Media Asset", varliklar[0], "legal_hold", 0)
			frappe.db.commit()

	def test_gv_asili_is_satiri_ayni_icerigin_YENIDEN_islenmesini_engellemiyor(self):
		"""F-33c — `_open_job` varlığı silinmiş eski iş satırını kendine onarıyor.

		İşler `içerik_hash:slot` anahtarıyla YENİDEN kullanılıyor. Kanca yokken
		oluşmuş (canlı DB'de 44/185) asılı `asset` bağlı bir satır, aynı içeriğin
		yeni yüklemesinde `job.save()`i `LinkValidationError` ile düşürüyor ve
		yeni dosya sessizce türevsiz kalıyordu. Bulunma biçimi: kendi fixture'ım
		çakışınca tam bu senaryo kendiliğinden oluştu.
		"""
		d = self._turevli_dosya("kd18-f33-asili-is.jpg", 1351)
		h = pipeline_bridge.content_fingerprint(d)
		varlik = frappe.get_all("Media Asset", filters={"source_file": d.name}, pluck="name")[0]
		job = frappe.get_all(
			"Media Processing Job", filters={"asset": varlik}, pluck="name", limit=1
		)
		self.assertTrue(job, "kurgu: iş satırı açılmadı")
		# Kanca YOKMUŞ gibi: varlığı iş satırını bırakarak sil (yığındaki durum).
		for dt in ("Media Rendition", "Media Version", "Media Metadata Vault", "Media Usage"):
			for ad in frappe.get_all(dt, filters={"asset": varlik}, pluck="name"):
				frappe.delete_doc(dt, ad, ignore_permissions=True, force=True, delete_permanently=True)
		frappe.delete_doc("Media Asset", varlik, ignore_permissions=True, force=True, delete_permanently=True)
		frappe.db.commit()
		self.assertTrue(frappe.db.exists("Media Processing Job", job[0]), "kurgu: iş satırı kalmalı")

		# Aynı içerik yeniden işleniyor — düşmemeli, iş satırı yeni varlığa bağlanmalı.
		pipeline_bridge._run_rendition_job(file_url=d.file_url)
		frappe.db.commit()
		yeni = frappe.get_all("Media Asset", filters={"source_file": d.name}, pluck="name")
		self.assertEqual(len(yeni), 1, "F-33c geri geldi — aynı içerik yeniden işlenemedi")
		self.assertEqual(
			frappe.db.get_value("Media Processing Job", job[0], "asset"), yeni[0],
			"iş satırı yeni varlığa bağlanmadı",
		)
		self.assertTrue(pipeline_bridge._renditions_exist(h, "product.image"))

	def test_bi_supurucu_kuru_kosumda_HICBIR_SEY_silmez(self):
		frappe.set_user("Administrator")
		once = frappe.db.count("Media Asset")
		r = pipeline_bridge.sweep_orphaned_assets(dry_run=True)
		self.assertTrue(r["dry_run"])
		self.assertEqual(r["deleted"], 0)
		self.assertEqual(frappe.db.count("Media Asset"), once)

	def test_bi_kanca_patlarsa_File_silme_DEVAM_eder(self):
		d = self._turevli_dosya("kd18-f33-best-effort.jpg", 1349)
		gercek = frappe.get_all

		def yalniz_varlik_sorgusu_patlar(doctype, *a, **k):
			if doctype == "Media Asset":
				raise RuntimeError("patladı")
			return gercek(doctype, *a, **k)

		# Yalnız kancanın KENDİ sorgusu patlıyor; `frappe.get_all`ı küresel
		# yamalamak Frappe'nin File silme yolunu da kırardı ve test kancayı değil
		# çerçeveyi ölçerdi.
		with mock.patch("frappe.get_all", side_effect=yalniz_varlik_sorgusu_patlar):
			frappe.delete_doc("File", d.name, ignore_permissions=True, force=True, delete_permanently=True)
		frappe.db.commit()
		self.assertFalse(frappe.db.exists("File", d.name), "kanca hatası silmeyi engelledi")


# ══════════════════════════════════════════════════════════════════════
# 3. Arşiv — grep'in yanlış suçladığı modül
# ══════════════════════════════════════════════════════════════════════


class TestArsivCakismaz(_DosyaTemeli):
	"""`archive.py` canlı dosyayı TAŞIMIYOR; optimizasyon öncesi orijinalin
	kopyasını saklıyor. Bu yüzden çöp/bekletme ile çakışmıyor.

	Kayda geçiyor çünkü `shutil.move|os.replace` taraması onu "taşıyıcı"
	göstermişti — okumadan çıkarılan sonuç yanlıştı.
	"""

	def test_bi_arsiv_canli_dosyayi_yerinde_birakiyor(self):
		from tradehub_core.media import archive

		url = self._dosya("kd18-arsiv.jpg")
		icerik = y.jpeg(120, 120)
		archive.store(url, icerik)
		self.addCleanup(archive.drop, url)

		self.assertTrue(os.path.isfile(_public_yol(url)), "arşivleme canlı dosyayı taşıdı")
		self.assertTrue(archive.exists(url))
		self.assertEqual(archive.read(url), icerik)

	def test_gv_arsiv_UZERINE_YAZMIYOR(self):
		"""İkinci koşum optimize edilmiş içeriği "orijinal" diye yazamamalı."""
		from tradehub_core.media import archive

		url = self._dosya("kd18-arsiv-ikinci.jpg")
		once = y.jpeg(120, 120)
		archive.store(url, once)
		self.addCleanup(archive.drop, url)
		archive.store(url, b"optimize-edilmis-sahte-icerik")
		self.assertEqual(archive.read(url), once, "arşiv üzerine yazıldı — geri alma kayboldu")

	def test_gv_arsiv_yol_kacisini_reddediyor(self):
		from tradehub_core.media import archive

		for kotu in ("/files/../../etc/passwd", "/files/./../gizli.jpg", "/baska/yer/x.jpg"):
			with self.subTest(kotu=kotu):
				with self.assertRaises(Exception):
					archive.absolute_path_for(kotu)


# ══════════════════════════════════════════════════════════════════════
# 4. Yedek kapsamı — motor tabloları
# ══════════════════════════════════════════════════════════════════════


class TestYedekKapsami(unittest.TestCase):
	"""Bayrak açıkken motorun ürettiği kayıtlar yedekte yoksa geri yükleme
	dosyaları getirir ama motorun hâlini getirmez."""

	def test_bi_AV_damgalari_yedege_EKLENMIS(self):
		"""Memory'de "Eksik A" diye kayıtlı 7 alan — bugün listede."""
		from tradehub_core.media import backup

		for alan in (
			"th_media_scan_status", "th_media_scan_attempts", "th_media_scan_started_at",
			"th_media_scan_next_at", "th_media_transcode_attempts",
			"th_media_transcode_started_at", "th_media_transcode_next_at",
		):
			with self.subTest(alan=alan):
				self.assertIn(alan, backup.RECORD_FIELDS, f"{alan} yedek kapsamında değil")

	def test_gv_BULGU_MOTOR_TABLOLARI_yedek_kapsaminda_DEGIL(self):
		"""BULGU F-25 — `FULL_TABLES` yalnız File + denetim izi.

		`Media Asset`, `Media Version`, `Media Rendition`, `Media Usage`,
		`Media Crop Intent` ve diğerleri hiçbir yedek modülünde geçmiyor
		(`backup.py`, `schema.py`, `backup_export.py`, `seller_backup.py`
		tarandı — sıfır eşleşme).

		Memory bunu "bayrak açılmadan önce şart" diye kaydetmiş (madde 11).
		Bayrak ARTIK AÇIK (`media_pipeline_enabled=1`, rollout %100) ve canlı
		veritabanında motor kayıtları birikmiş durumda. Geri yükleme File
		satırlarını getirir, motorun hâlini getirmez.
		"""
		from tradehub_core.media import schema

		self.assertEqual(
			schema.FULL_TABLES, ("tabFile", "tabAuthorization Decision Log"),
			"F-25 kapanmış olabilir — FULL_TABLES değişmiş",
		)
		for tablo in ("tabMedia Asset", "tabMedia Rendition", "tabMedia Version"):
			self.assertNotIn(tablo, schema.FULL_TABLES, f"{tablo} artık yedekte — bulguyu kapat")

	def test_orm_bayrak_durumu_ve_motor_veri_hacmi(self):
		"""ORTAM KAYDI — bayrak açıksa ve veri varsa F-25 aktif risktir."""
		try:
			from tradehub_core.media import pipeline_flags

			acik = pipeline_flags.is_enabled()
		except Exception:
			self.skipTest("pipeline_flags okunamadı")

		sayilar = {}
		for dt in ("Media Asset", "Media Rendition", "Media Version"):
			try:
				sayilar[dt] = frappe.db.count(dt)
			except Exception:
				sayilar[dt] = -1
		if acik and any(v > 0 for v in sayilar.values()):
			self.skipTest(
				f"bayrak AÇIK ve yedeksiz motor kaydı var: {sayilar} — F-25 aktif risk"
			)


# ══════════════════════════════════════════════════════════════════════
# 5. Ortam kaydı
# ══════════════════════════════════════════════════════════════════════


class TestOrtamKaydi(unittest.TestCase):
	def test_orm_AV_tarayicisi_kurulu_mu(self):
		"""Modülün KENDİ API'siyle sorulur — `which` tahmini değil."""
		if not av.scanner_available():
			self.skipTest(
				f"AV tarayıcısı YOK (scanner_command()={av.scanner_command()}) → "
				"policy fail-open, hiçbir yükleme taranmıyor, bekletme hiç olmuyor"
			)


if __name__ == "__main__":
	unittest.main()

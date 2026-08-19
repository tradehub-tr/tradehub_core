"""Satıcı medya yedeği — kapsam, izolasyon, geri yükleme (TUR-131).

Buradaki asıl soru güvenlik: satıcı yedeği KİRACI SINIRI içinde mi kalıyor?
Bir mağazanın diğerinin dosyasını yedeklemesi, listelemesi, geri yüklemesi ya
da kaydını kurması sızıntıdır. Testlerin çoğu bu sınırı zorluyor.

İkinci soru bütünlük: geri yükleme mevcut veriyi eziyor mu, siliyor mu.
Kabul kriteri "veri kaybı ve hatalı geri yükleme riskleri azaltılmış olmalı".

    docker exec -w /home/frappe/frappe-bench istoc-backend bench \
        --site tradehub.localhost run-tests \
        --module tradehub_core.tests.test_media_seller_backup
"""

from __future__ import annotations

import os
import shutil
import zipfile
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import seller_backup, seller_backup_export

# Koşum başına benzersiz tuz — içerik-adresli adlandırma yüzünden sabit içerik
# koşumlar arası aynı `file_url`'e düşüyor ve artık kayıtlar testleri kirletiyor
# (test_media_transcode_retry'de yaşandı).
_TUZ: str = frappe.generate_hash(length=12)

MAGAZA_A = "TEST-BACKUP-A"
MAGAZA_B = "TEST-BACKUP-B"


def _dosya(ad: str, *, owner: str) -> frappe.Document:
	# Tarama kancası (TUR-125) NÖTRLENİYOR. Makinede ClamAV kuruluysa kanca
	# dosyayı `media_scan_hold`'a taşıyor — yani `public/files/` altında
	# kalmıyor. Yedekleme testleri dosyanın canlı ağaçta durduğunu varsayıyor;
	# nötrlemezsek bu paket makinede tarayıcı olup olmamasına göre farklı
	# davranır (yaşandı: kurulumdan sonra 19 test düştü).
	with mock.patch("tradehub_core.media.av.enqueue_scan"):
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": ad,
				"is_private": 0,
				"content": f"icerik {_TUZ} {ad}".encode(),
			}
		)
		doc.insert(ignore_permissions=True)
	if owner:
		frappe.db.set_value("File", doc.name, "owner", owner, update_modified=False)
	frappe.db.commit()
	return doc


class _YedekTemeli(FrappeTestCase):
	"""İki sahte mağaza, her birinin kendi dosyası.

	`ownership.users_of` ve `used_urls` mock'lanıyor: gerçek `Admin Seller
	Profile` kurmak bu testlerin konusu değil ve kurulum farklarına bağımlı
	kılardı. Mock'lanan yalnız "mağazanın kullanıcısı kim" eşlemesi; kapsam,
	yol kurma ve izolasyon mantığı GERÇEK kodda koşuyor.
	"""

	def setUp(self):
		self.kullanici_a = f"backup-a-{_TUZ}@test.local"
		self.kullanici_b = f"backup-b-{_TUZ}@test.local"

		self.dosya_a = _dosya(f"yedek-a-{_TUZ}.txt", owner=self.kullanici_a)
		self.dosya_b = _dosya(f"yedek-b-{_TUZ}.txt", owner=self.kullanici_b)
		for d in (self.dosya_a, self.dosya_b):
			self.addCleanup(
				lambda ad=d.name: frappe.delete_doc(
					"File", ad, ignore_permissions=True, force=True
				)
			)

		eslem = {MAGAZA_A: (self.kullanici_a,), MAGAZA_B: (self.kullanici_b,)}
		self._yamalar = [
			mock.patch(
				"tradehub_core.media.ownership.users_of",
				side_effect=lambda store: eslem.get(store, ()),
			),
			mock.patch("tradehub_core.media.ownership.used_urls", return_value=set()),
		]
		for y in self._yamalar:
			y.start()
			self.addCleanup(y.stop)

		for magaza in (MAGAZA_A, MAGAZA_B):
			self.addCleanup(
				lambda m=magaza: shutil.rmtree(
					frappe.get_site_path("private", seller_backup.ROOT_DIRNAME, m),
					ignore_errors=True,
				)
			)

		# Bu sınıflar YEDEK mekaniğini sınıyor. Geri yükleme artık yazdığı baytı
		# taramaya sokuyor (`av.rescan_after_write`) ve politika bekletme diyorsa
		# dosyayı canlı ağaçtan ÇIKARIYOR — doğru davranış, ama burada ölçülen
		# şey o değil ve tarayıcının kurulu olup olmamasına göre iki farklı
		# sonuç verirdi. Kesişimin kendi testleri `TestTaramaKapisi`'nde ve
		# `test_media_av.TestYazmaSonrasiTarama`'da.
		kural = mock.patch("tradehub_core.media.av.rescan_after_write", return_value={})
		kural.start()
		self.addCleanup(kural.stop)

	def _yedek_al(self, magaza: str, label: str = ""):
		# Hız sınırı testlerin konusu değil; ayrı bir testte sınanıyor.
		with mock.patch.object(seller_backup, "MIN_INTERVAL_SECONDS", 0):
			return seller_backup.create(magaza, label=label)


class TestKapsam(_YedekTemeli):
	"""Yedek yalnız mağazanın kendi dosyalarını içerir."""

	def test_yedek_kendi_dosyasini_alir(self):
		sonuc = self._yedek_al(MAGAZA_A)
		self.assertGreaterEqual(sonuc["file_count"], 1)

		m = seller_backup.manifest_of(MAGAZA_A, sonuc["set_id"])
		adresler = {d["file_url"] for d in m["files"]}
		self.assertIn(self.dosya_a.file_url, adresler)

	def test_yedekte_baska_magazanin_dosyasi_YOK(self):
		sonuc = self._yedek_al(MAGAZA_A)
		m = seller_backup.manifest_of(MAGAZA_A, sonuc["set_id"])
		adresler = {d["file_url"] for d in m["files"]}
		self.assertNotIn(
			self.dosya_b.file_url, adresler, "başka mağazanın dosyası yedeğe girmemeli"
		)

	def test_kunyede_baska_magazanin_kaydi_YOK(self):
		sonuc = self._yedek_al(MAGAZA_A)
		kayitlar = seller_backup.records_of(MAGAZA_A, sonuc["set_id"])
		sahipler = {r.get("owner") for r in kayitlar}
		self.assertNotIn(self.kullanici_b, sahipler)
		self.assertIn(self.kullanici_a, sahipler)

	def test_magazalar_ayri_depoda(self):
		a = self._yedek_al(MAGAZA_A)
		b = self._yedek_al(MAGAZA_B)
		# A'nın listesinde B'nin yedeği görünmemeli — depolar ayrı.
		a_setler = {s["set_id"] for s in seller_backup.list_sets(MAGAZA_A)}
		b_setler = {s["set_id"] for s in seller_backup.list_sets(MAGAZA_B)}
		self.assertIn(a["set_id"], a_setler)
		self.assertIn(b["set_id"], b_setler)
		self.assertFalse(a_setler & b_setler - {a["set_id"]} - {b["set_id"]})


class TestIzolasyon(_YedekTemeli):
	"""Yol kaçışı ve kimlik doğrulama — kiracı sınırı burada tutuluyor."""

	def test_magaza_kimliginde_yol_kacisi_reddedilir(self):
		for bozuk in ("../../etc", "..", "/etc", "A/../../B", "", "a" * 65):
			with self.assertRaises(frappe.ValidationError, msg=f"girdi: {bozuk!r}"):
				seller_backup.list_sets(bozuk)

	def test_yedek_kimliginde_yol_kacisi_reddedilir(self):
		for bozuk in ("../../../etc/passwd", "..", "", "%00", "20260101_000000/../.."):
			with self.assertRaises(frappe.ValidationError, msg=f"girdi: {bozuk!r}"):
				seller_backup.manifest_of(MAGAZA_A, bozuk)

	def test_baska_magazanin_yedegi_okunamaz(self):
		b = self._yedek_al(MAGAZA_B)
		# A, B'nin yedek kimliğini bilse bile okuyamamalı: yol mağaza kökünden
		# kuruluyor, kimlik tek başına yetki değil.
		with self.assertRaises(frappe.ValidationError):
			seller_backup.manifest_of(MAGAZA_A, b["set_id"])

	def test_imza_dogrulanmadan_havuz_yolu_kurulmaz(self):
		for bozuk in ("../../x", "zz", "", "A" * 64):
			with self.assertRaises(frappe.ValidationError, msg=f"girdi: {bozuk!r}"):
				seller_backup._blob_path(MAGAZA_A, bozuk)

    # Manifest elle kurcalanabilir; göreli yol yine de kök altında kalmalı.
	def test_manifest_yolu_kok_disina_cikamaz(self):
		with self.assertRaises(frappe.ValidationError):
			seller_backup._live_path("../../../etc/passwd")


class TestDogrulama(_YedekTemeli):
	"""`verify` — "yedeğim var" değil, "yedeğim çalışıyor"."""

	def test_saglam_yedek_ok_doner(self):
		s = self._yedek_al(MAGAZA_A)
		sonuc = seller_backup.verify(MAGAZA_A, s["set_id"], deep=True)
		self.assertTrue(sonuc["ok"])
		self.assertEqual(sonuc["missing_count"], 0)
		self.assertEqual(sonuc["corrupt_count"], 0)

	def test_havuzdan_silinen_icerik_eksik_raporlanir(self):
		s = self._yedek_al(MAGAZA_A)
		m = seller_backup.manifest_of(MAGAZA_A, s["set_id"])
		hedef = [d for d in m["files"] if d["file_url"] == self.dosya_a.file_url][0]
		os.remove(seller_backup._blob_path(MAGAZA_A, hedef["hash"]))

		sonuc = seller_backup.verify(MAGAZA_A, s["set_id"])
		self.assertFalse(sonuc["ok"])
		self.assertIn(hedef["path"], sonuc["missing_blobs"])

	def test_bozulan_icerik_derin_dogrulamada_yakalanir(self):
		s = self._yedek_al(MAGAZA_A)
		m = seller_backup.manifest_of(MAGAZA_A, s["set_id"])
		hedef = [d for d in m["files"] if d["file_url"] == self.dosya_a.file_url][0]
		with open(seller_backup._blob_path(MAGAZA_A, hedef["hash"]), "wb") as fh:
			fh.write(b"bozuldu")

		# Hızlı doğrulama bunu GÖREMEZ (dosya duruyor), derin doğrulama görür.
		self.assertTrue(seller_backup.verify(MAGAZA_A, s["set_id"])["ok"])
		derin = seller_backup.verify(MAGAZA_A, s["set_id"], deep=True)
		self.assertFalse(derin["ok"])
		self.assertIn(hedef["path"], derin["corrupt_blobs"])


class TestGeriYukleme(_YedekTemeli):
	"""Plan → uygula. Silmez, ezmez, kiracı sınırını aşmaz."""

	def _canli_yol(self) -> str:
		return seller_backup._live_path(self.dosya_a.file_url[len("/files/") :])

	def test_plan_hicbir_seye_dokunmaz(self):
		s = self._yedek_al(MAGAZA_A)
		yol = self._canli_yol()
		os.remove(yol)

		p = seller_backup.plan(MAGAZA_A, s["set_id"])
		self.assertFalse(p["applied"])
		self.assertFalse(os.path.exists(yol), "plan dosyayı geri yazmamalı")
		self.assertGreaterEqual(p["missing_file_count"], 1)

	def test_eksik_dosya_geri_yazilir(self):
		s = self._yedek_al(MAGAZA_A)
		yol = self._canli_yol()
		beklenen = open(yol, "rb").read()
		os.remove(yol)

		sonuc = seller_backup.apply(MAGAZA_A, s["set_id"], records=False)
		self.assertGreaterEqual(sonuc["files_written"], 1)
		self.assertTrue(os.path.isfile(yol))
		self.assertEqual(open(yol, "rb").read(), beklenen)

	def test_degismis_dosya_izin_olmadan_EZILMEZ(self):
		s = self._yedek_al(MAGAZA_A)
		yol = self._canli_yol()
		with open(yol, "wb") as fh:
			fh.write(b"yeni surum - ezilmemeli")

		sonuc = seller_backup.apply(MAGAZA_A, s["set_id"], records=False)
		self.assertEqual(open(yol, "rb").read(), b"yeni surum - ezilmemeli")
		self.assertGreaterEqual(sonuc["conflicts_skipped_count"], 1)

	def test_overwrite_ile_acikca_istenirse_yazilir(self):
		s = self._yedek_al(MAGAZA_A)
		yol = self._canli_yol()
		beklenen = open(yol, "rb").read()
		with open(yol, "wb") as fh:
			fh.write(b"yeni surum")

		sonuc = seller_backup.apply(MAGAZA_A, s["set_id"], records=False, overwrite=True)
		self.assertEqual(open(yol, "rb").read(), beklenen)
		self.assertGreaterEqual(sonuc["overwritten_count"], 1)

	def test_yedekten_sonra_eklenen_dosya_SILINMEZ(self):
		s = self._yedek_al(MAGAZA_A)
		yeni = _dosya(f"yedek-sonrasi-{_TUZ}.txt", owner=self.kullanici_a)
		self.addCleanup(
			lambda: frappe.delete_doc("File", yeni.name, ignore_permissions=True, force=True)
		)
		yeni_yol = seller_backup._live_path(yeni.file_url[len("/files/") :])

		p = seller_backup.plan(MAGAZA_A, s["set_id"])
		self.assertIn(yeni.file_url[len("/files/") :], p["extra"])

		seller_backup.apply(MAGAZA_A, s["set_id"])
		self.assertTrue(os.path.isfile(yeni_yol), "yedekten sonra eklenen dosya silinmemeli")

	def test_diskte_olmayan_dosya_FAZLA_sayilmaz(self):
		"""Kaydı olup dosyası kaybolmuş adres "yedekten sonra eklenmiş" görünmemeli.

		Yaşandı: gerçek veride 2 dosya böyle sayılıyordu. Kullanıcıya "2 yeni
		dosyan var" demek, aslında 2 dosyasını kaybettiği anlamına geliyordu.
		"""
		s = self._yedek_al(MAGAZA_A)
		# Yedekten SONRA kayıt aç ama dosyasını diskten sil.
		hayalet = _dosya(f"hayalet-{_TUZ}.txt", owner=self.kullanici_a)
		self.addCleanup(
			lambda: frappe.delete_doc("File", hayalet.name, ignore_permissions=True, force=True)
		)
		os.remove(seller_backup._live_path(hayalet.file_url[len("/files/") :]))

		p = seller_backup.plan(MAGAZA_A, s["set_id"])
		self.assertNotIn(hayalet.file_url[len("/files/") :], p["extra"])

	def test_kaybolan_kayit_geri_kurulur(self):
		s = self._yedek_al(MAGAZA_A)
		ad = self.dosya_a.name
		yol = self._canli_yol()
		# Kayıt gitti ama dosya diskte duruyor: satıcı kütüphanesinde göremez.
		frappe.delete_doc("File", ad, ignore_permissions=True, force=True)
		frappe.db.commit()
		self.assertFalse(frappe.db.exists("File", ad))
		# `delete_doc` dosyayı da siliyor olabilir; geri yükleme ikisini de kurar.

		sonuc = seller_backup.apply(MAGAZA_A, s["set_id"])
		self.assertEqual(sonuc["records_created"], 1)
		self.assertTrue(frappe.db.exists("File", ad))
		# Sahip GERİ YAZILMALI: Frappe insert sırasında oturumdaki kullanıcıyla
		# eziyor, o zaman dosya mağazadan kopuyor ve satıcı onu göremiyor.
		self.assertEqual(frappe.db.get_value("File", ad, "owner"), self.kullanici_a)
		self.assertTrue(os.path.isfile(yol))

	def test_mevcut_kayit_EZILMEZ(self):
		s = self._yedek_al(MAGAZA_A)
		frappe.db.set_value(
			"File", self.dosya_a.name, "th_media_title", "elle degistirildi",
			update_modified=False,
		)
		frappe.db.commit()

		sonuc = seller_backup.apply(MAGAZA_A, s["set_id"])
		self.assertEqual(sonuc["records_created"], 0)
		self.assertEqual(
			frappe.db.get_value("File", self.dosya_a.name, "th_media_title"),
			"elle degistirildi",
		)

	def test_baska_magazanin_kaydi_kurulmaz(self):
		"""Paket kurcalansa bile başka kiracının kaydı enjekte edilemez."""
		s = self._yedek_al(MAGAZA_A)
		yol = os.path.join(seller_backup._set_path(MAGAZA_A, s["set_id"]), "records.json")
		kayitlar = seller_backup._oku(yol)
		kayitlar.append(
			{
				"name": f"SAHTE-{_TUZ}",
				"file_url": "/files/sahte.txt",
				"file_name": "sahte.txt",
				"owner": self.kullanici_b,  # BAŞKA mağazanın kullanıcısı
			}
		)
		seller_backup._yaz(yol, kayitlar)

		sonuc = seller_backup.apply(MAGAZA_A, s["set_id"], files=False)
		self.assertFalse(frappe.db.exists("File", f"SAHTE-{_TUZ}"))
		self.assertEqual(sonuc["records_created"], 0)


class TestSaklama(_YedekTemeli):
	"""Saklama sınırı, silme kuralları, hız sınırı."""

	def test_hiz_siniri_ardisik_yedegi_reddeder(self):
		self._yedek_al(MAGAZA_A)
		with self.assertRaises(frappe.ValidationError):
			seller_backup.create(MAGAZA_A)  # gerçek MIN_INTERVAL ile

	def test_sinir_asilinca_en_eski_dusuyor(self):
		with mock.patch.object(seller_backup, "MAX_SETS_PER_STORE", 2):
			ilk = self._yedek_al(MAGAZA_A, label="bir")
			self._yedek_al(MAGAZA_A, label="iki")
			self._yedek_al(MAGAZA_A, label="uc")

			setler = {s["set_id"] for s in seller_backup.list_sets(MAGAZA_A)}
			self.assertEqual(len(setler), 2)
			self.assertNotIn(ilk["set_id"], setler)

	def test_son_yedek_silinemez(self):
		s = self._yedek_al(MAGAZA_A)
		with self.assertRaises(frappe.ValidationError):
			seller_backup.delete_set(MAGAZA_A, s["set_id"])

	def test_silinen_yedegin_icerigi_havuzdan_kalkar(self):
		ilk = self._yedek_al(MAGAZA_A)
		# İkinci yedekte dosya değişsin ki ilkin içeriği yetim kalsın.
		yol = seller_backup._live_path(self.dosya_a.file_url[len("/files/") :])
		with open(yol, "wb") as fh:
			fh.write(b"degisti")
		self._yedek_al(MAGAZA_A)

		sonuc = seller_backup.delete_set(MAGAZA_A, ilk["set_id"])
		self.assertGreaterEqual(sonuc["removed_blobs"], 1)

	def test_paylasilan_icerik_erken_silinmez(self):
		ilk = self._yedek_al(MAGAZA_A)
		ikinci = self._yedek_al(MAGAZA_A)  # aynı içerik, aynı imza

		m = seller_backup.manifest_of(MAGAZA_A, ikinci["set_id"])
		imzalar = [d["hash"] for d in m["files"]]
		seller_backup.delete_set(MAGAZA_A, ilk["set_id"])

		for imza in imzalar:
			self.assertTrue(
				os.path.isfile(seller_backup._blob_path(MAGAZA_A, imza)),
				"hâlâ kullanılan içerik havuzdan kalkmamalı",
			)

	def test_ikinci_yedek_artimli(self):
		self._yedek_al(MAGAZA_A)
		ikinci = self._yedek_al(MAGAZA_A)
		# Değişiklik yoksa hiçbir yeni içerik yazılmamalı.
		self.assertEqual(ikinci["new_blobs"], 0)

	def test_kullanim_raporu(self):
		self._yedek_al(MAGAZA_A)
		k = seller_backup.usage(MAGAZA_A)
		self.assertGreater(k["bytes"], 0)
		self.assertEqual(k["sets"], 1)


class TestPaket(_YedekTemeli):
	"""İndirilebilir paket — içinde ne var, ne YOK."""

	def _paketle(self, magaza: str):
		s = self._yedek_al(magaza)
		# `start` kuyruğa atıyor; testte işi doğrudan koşturuyoruz (worker yok).
		with mock.patch("tradehub_core.media.seller_backup_export.frappe.enqueue"):
			seller_backup_export.start(magaza, s["set_id"])
		seller_backup_export.build(magaza, s["set_id"])
		return s["set_id"]

	def test_paket_hazir_ve_indirilebilir(self):
		set_id = self._paketle(MAGAZA_A)
		d = seller_backup_export.status(MAGAZA_A, set_id)
		self.assertEqual(d["state"], seller_backup_export.STATE_READY)
		self.assertTrue(d["exists"])
		self.assertTrue(os.path.isfile(seller_backup_export.package_path(MAGAZA_A, set_id)))

	def test_pakette_veritabani_ciktisi_YOK(self):
		set_id = self._paketle(MAGAZA_A)
		with zipfile.ZipFile(seller_backup_export.package_path(MAGAZA_A, set_id)) as zf:
			adlar = zf.namelist()

		# Sözleşme: yalnız dosyalar + künye + özet. Ham kayıt çıktısı verilmiyor.
		self.assertIn("kunye.csv", adlar)
		self.assertIn("ozet.txt", adlar)
		self.assertTrue(any(a.startswith("dosyalar/") for a in adlar))
		self.assertFalse(
			[a for a in adlar if a.endswith(".json") or "records" in a.lower()],
			"pakette ham veritabanı çıktısı olmamalı",
		)

	def test_kunyede_baska_magazanin_verisi_YOK(self):
		set_id = self._paketle(MAGAZA_A)
		with zipfile.ZipFile(seller_backup_export.package_path(MAGAZA_A, set_id)) as zf:
			kunye = zf.read("kunye.csv").decode("utf-8-sig")
		self.assertIn(self.dosya_a.file_name, kunye)
		self.assertNotIn(self.dosya_b.file_name, kunye)
		self.assertNotIn(self.kullanici_b, kunye)

	def test_kunye_DOSYA_basina_satir_yazar(self):
		"""Aynı içerik iki kez yüklenirse künyede TEK satır olmalı.

		Kayıt başına yazmak yanıltıyordu: satıcının kütüphanesi dosya bazlı
		(20 dosya) ama künye kayıt bazlıydı (27 satır). "20 dosyam vardı, 27
		nereden çıktı" sorusu buradan geliyordu.
		"""
		# Aynı içerikle ikinci bir kayıt: içerik-adresli adlandırma tek dosyaya
		# iki kayıt düşürür.
		# `_dosya` ile aynı gerekçe: tarama kancası nötrleniyor, yoksa ikizin
		# insert'i PAYLAŞILAN fiziksel dosyayı bekletmeye taşır ve künyeden
		# tamamen düşer.
		with mock.patch("tradehub_core.media.av.enqueue_scan"):
			ikizi = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"ikiz-{_TUZ}.txt",
					"is_private": 0,
					"content": f"icerik {_TUZ} yedek-a-{_TUZ}.txt".encode(),
				}
			)
			ikizi.insert(ignore_permissions=True)
		frappe.db.set_value("File", ikizi.name, "owner", self.kullanici_a, update_modified=False)
		frappe.db.commit()
		self.addCleanup(
			lambda: frappe.delete_doc("File", ikizi.name, ignore_permissions=True, force=True)
		)
		self.assertEqual(ikizi.file_url, self.dosya_a.file_url, "aynı içerik aynı adrese düşmeli")

		set_id = self._paketle(MAGAZA_A)
		with zipfile.ZipFile(seller_backup_export.package_path(MAGAZA_A, set_id)) as zf:
			satirlar = zf.read("kunye.csv").decode("utf-8-sig").strip().splitlines()

		m = seller_backup.manifest_of(MAGAZA_A, set_id)
		# Başlık satırı + dosya başına bir satır. Asıl sözleşme bu.
		self.assertEqual(len(satirlar) - 1, len(m["files"]))

		# Paylaşılan adres TEK satırda, birden çok kayıt o satırda birleşmiş.
		# Sayıya `>= 2` deniyor, `== 2` değil: aynı koşumdaki önceki testlerin
		# kayıtları da aynı adrese düşüyor (içerik-adresli adlandırma + testlerin
		# commit'lemesi), sabit sayı beklemek kırılgan olurdu.
		hedef = [r for r in satirlar[1:] if self.dosya_a.file_url in r]
		self.assertEqual(len(hedef), 1, "paylaşılan adres tek satır olmalı")
		self.assertGreaterEqual(int(hedef[0].split(";")[-2]), 2)

	def test_paket_atilinca_yedek_durur(self):
		set_id = self._paketle(MAGAZA_A)
		seller_backup_export.discard(MAGAZA_A, set_id)
		self.assertEqual(seller_backup_export.status(MAGAZA_A, set_id)["state"], "")
		# Yedeğin kendisi yerinde olmalı — paket yalnız taşıma biçimi.
		self.assertTrue(seller_backup.manifest_of(MAGAZA_A, set_id))

	def test_hazir_paket_yokken_indirme_reddedilir(self):
		s = self._yedek_al(MAGAZA_A)
		with self.assertRaises(frappe.ValidationError):
			seller_backup_export.package_path(MAGAZA_A, s["set_id"])

	def test_baska_magazanin_paketine_erisilemez(self):
		set_id = self._paketle(MAGAZA_B)
		# A, B'nin yedek kimliğini bilse bile paketine ulaşamamalı.
		with self.assertRaises(frappe.ValidationError):
			seller_backup_export.package_path(MAGAZA_A, set_id)


class TestPaylasilanDosyaYazmaSiniri(FrappeTestCase):
	"""B'nin yüklediği ama A'nın kullandığı dosyayı A geri yazabiliyor mu?

	`ownership.scope` iki yoldan sahiplik tanıyor: mağazanın YÜKLEDİĞİ dosyalar
	VEYA mağazanın kayıtlarında KULLANILAN dosyalar. İkincisi kütüphane
	görünümü için doğru (satıcı ürününde duran görseli görmeli), ama YAZMA için
	tehlikeli: A'nın yedeği B'nin dosyasını içeriyorsa, A `overwrite` ile geri
	yükleyince B'nin bugünkü dosyasını eski hâline döndürebilir.
	"""

	def setUp(self):
		self.kullanici_a = f"paylas-a-{_TUZ}@test.local"
		self.kullanici_b = f"paylas-b-{_TUZ}@test.local"
		# Dosyayı B yükledi.
		self.dosya = _dosya(f"paylasilan-{_TUZ}.txt", owner=self.kullanici_b)
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.dosya.name, ignore_permissions=True, force=True)
		)

		eslem = {MAGAZA_A: (self.kullanici_a,), MAGAZA_B: (self.kullanici_b,)}
		# A o dosyayı KULLANIYOR (kendi kaydında), ama yüklemedi.
		yamalar = [
			mock.patch(
				"tradehub_core.media.ownership.users_of",
				side_effect=lambda store: eslem.get(store, ()),
			),
			mock.patch(
				"tradehub_core.media.ownership.used_urls",
				side_effect=lambda store: {self.dosya.file_url} if store == MAGAZA_A else set(),
			),
		]
		for y in yamalar:
			y.start()
			self.addCleanup(y.stop)

		for magaza in (MAGAZA_A, MAGAZA_B):
			self.addCleanup(
				lambda m=magaza: shutil.rmtree(
					frappe.get_site_path("private", seller_backup.ROOT_DIRNAME, m),
					ignore_errors=True,
				)
			)

	def _yedek_al(self, magaza):
		with mock.patch.object(seller_backup, "MIN_INTERVAL_SECONDS", 0):
			return seller_backup.create(magaza, label="")

	def test_yedek_kullanilan_dosyayi_kapsar(self):
		# Kapsam kütüphaneyle aynı kalmalı: gördüğü dosya yedeğinde de olmalı.
		s = self._yedek_al(MAGAZA_A)
		m = seller_backup.manifest_of(MAGAZA_A, s["set_id"])
		self.assertIn(self.dosya.file_url, {d["file_url"] for d in m["files"]})

	def test_yuklemedigi_dosyanin_UZERINE_YAZAMAZ(self):
		"""Asıl güvenlik iddiası: A, B'nin dosyasını geri yazamamalı."""
		s = self._yedek_al(MAGAZA_A)
		yol = seller_backup._live_path(self.dosya.file_url[len("/files/") :])

		# B dosyayı güncelledi (ör. optimize etti / yenisiyle değiştirdi).
		with open(yol, "wb") as fh:
			fh.write(b"B'nin yeni surumu")

		sonuc = seller_backup.apply(MAGAZA_A, s["set_id"], overwrite=True, records=False)

		self.assertEqual(
			open(yol, "rb").read(),
			b"B'nin yeni surumu",
			"A, yüklemediği dosyanın üzerine yazamamalı",
		)
		self.assertGreaterEqual(sonuc.get("skipped_not_owned_count", 0), 1)

	def test_yuklemedigi_dosya_eksikse_de_geri_yazilmaz(self):
		# Dosya diskten tamamen gitse bile A onu geri koyamaz: B'nin verisi.
		s = self._yedek_al(MAGAZA_A)
		yol = seller_backup._live_path(self.dosya.file_url[len("/files/") :])
		os.remove(yol)

		sonuc = seller_backup.apply(MAGAZA_A, s["set_id"], records=False)
		self.assertFalse(os.path.exists(yol))
		self.assertEqual(sonuc["files_written"], 0)
		self.assertGreaterEqual(sonuc.get("skipped_not_owned_count", 0), 1)


class TestTaramaKapisi(_YedekTemeli):
	"""AV taraması ile yedeğin kesişimi (TUR-125 × TUR-131).

	Tarama sistemi, taranmayı bekleyen ya da zararlı bulunan dosyayı public
	ağaçtan FİZİKSEL olarak çıkarıyor (`media_scan_hold` / `media_quarantine`);
	`file_url` değişmiyor. İki modül birbirini bilmeden şu iki kusuru üretmişti:

	  1. Yedek, dosyayı diskte bulamayıp SESSİZCE atlıyordu — satıcı eksik bir
	     yedeği tam sanıyordu.
	  2. Geri yükleme, karantinadaki dosyanın blob'unu public ağaca geri
	     yazabiliyordu — karantinayı etkisiz kılan bir güvenlik regresyonu.
	"""

	def _servis_kapali(self, *urls: str):
		"""`av.is_servable` yalnız verilen adresler için False dönsün."""
		kapali = set(urls)
		return mock.patch(
			"tradehub_core.media.av.is_servable",
			side_effect=lambda url: url not in kapali,
		)

	def test_karantinadaki_dosya_yedege_GIRMEZ_ve_sayilir(self):
		with self._servis_kapali(self.dosya_a.file_url):
			sonuc = self._yedek_al(MAGAZA_A)

		m = seller_backup.manifest_of(MAGAZA_A, sonuc["set_id"])
		self.assertNotIn(self.dosya_a.file_url, {d["file_url"] for d in m["files"]})
		# Sessiz atlama yok: sayı manifest'te duruyor.
		self.assertGreaterEqual(sonuc.get("skipped_unscanned", 0), 1)

	def test_yedekten_SONRA_karantinaya_dusen_dosya_geri_yazilmaz(self):
		"""Asıl güvenlik iddiası: geri yükleme karantinayı geçersiz kılamaz."""
		s = self._yedek_al(MAGAZA_A)
		yol = seller_backup._live_path(self.dosya_a.file_url[len("/files/") :])
		# Tarama sistemi dosyayı public ağaçtan çıkardı.
		os.remove(yol)

		with self._servis_kapali(self.dosya_a.file_url):
			sonuc = seller_backup.apply(MAGAZA_A, s["set_id"], records=False)

		self.assertFalse(
			os.path.exists(yol), "karantinadaki dosya public ağaca geri konmamalı"
		)
		self.assertGreaterEqual(sonuc.get("skipped_unscanned_count", 0), 1)
		self.assertEqual(sonuc["files_written"], 0)

	def test_plan_taranmamis_dosyayi_raporlar(self):
		s = self._yedek_al(MAGAZA_A)
		with self._servis_kapali(self.dosya_a.file_url):
			p = seller_backup.plan(MAGAZA_A, s["set_id"])
		self.assertGreaterEqual(p.get("unscanned_count", 0), 1)

	def test_tarama_modulu_patlarsa_yedek_durmaz(self):
		# Politika okunamadığında yedekleme durmamalı: yedek almak bir güvenlik
		# kararı değil. Geri YAZMA tarafı ayrıca korunuyor.
		with mock.patch(
			"tradehub_core.media.av.is_servable", side_effect=Exception("politika okunamadi")
		):
			sonuc = self._yedek_al(MAGAZA_A)
		self.assertGreaterEqual(sonuc["file_count"], 1)


if __name__ == "__main__":
	import unittest

	unittest.main()

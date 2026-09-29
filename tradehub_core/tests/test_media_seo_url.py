"""SEO'lu görsel adresi — çekirdek (spec 2026-09-28-seo-gorsel-adresi-design.md).

	docker exec istoc-dev-backend-1 bench --site istoc.localhost \
		run-tests --module tradehub_core.tests.test_media_seo_url
"""

from __future__ import annotations

import hashlib
import os
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, get_files_path, now_datetime

from tradehub_core.media import retro_rename, seo_url

# Frappe v15 adaptasyonu (brief'ten farklı): `File.validate_file_on_disk` her
# zaman diskte gerçek bir dosya bekler — `copy_from_existing_file` bayrağı bu
# kontrolü atlamaz (yalnız yeniden-işlemeyi, ör. exif-strip, atlar). Testin
# sabit hash'li adresleri gerçek içerikle karşılık bulsun diye burada minik
# bir dosya yazılıyor; modül sonunda temizleniyor (disk DB rollback'ine dahil
# değil, testler arası sızmasın).
_DISK_YAZILANLAR: set[str] = set()


def _disk_yolu(url: str) -> str:
	rel = url[len("/files/") :].split("/")
	return os.path.join(get_files_path(is_private=0), *rel)


def _diskte_hazirla(url: str) -> None:
	path = _disk_yolu(url)
	os.makedirs(os.path.dirname(path), exist_ok=True)
	if not os.path.exists(path):
		with open(path, "wb") as f:
			f.write(b"seo-url-test")
		_DISK_YAZILANLAR.add(path)


_ESKI_BAYRAK = None


def setUpModule():
	global _ESKI_BAYRAK
	# Final review I-2: okunur adres `seo_image_urls` bayrağına bağlı; varsayılan açık ölçülür.
	_ESKI_BAYRAK = frappe.local.conf.get(seo_url.BAYRAK)
	frappe.local.conf[seo_url.BAYRAK] = 1


def tearDownModule():
	if _ESKI_BAYRAK is None:
		frappe.local.conf.pop(seo_url.BAYRAK, None)
	else:
		frappe.local.conf[seo_url.BAYRAK] = _ESKI_BAYRAK
	for path in _DISK_YAZILANLAR:
		if os.path.exists(path):
			os.remove(path)


def _file_row(url: str) -> str:
	_diskte_hazirla(url)
	d = frappe.get_doc(
		{"doctype": "File", "file_name": url.rsplit("/", 1)[-1], "file_url": url, "is_private": 0}
	)
	d.flags.copy_from_existing_file = True
	d.flags.ignore_seo_code = True  # kod atamasını test kendisi yapsın
	d.insert(ignore_permissions=True)
	return d.name


class TestSlug(FrappeTestCase):
	def test_turkce_ve_kisaltma(self):
		self.assertEqual(seo_url.make_slug("4 Katlı Siyah Ayakkabılık"), "4-katli-siyah-ayakkabilik")
		uzun = "Çok " * 40
		s = seo_url.make_slug(uzun)
		self.assertLessEqual(len(s), 60)
		self.assertFalse(s.endswith("-"))
		self.assertTrue(set(s.split("-")) <= {"cok"})

	def test_bos_ad(self):
		self.assertEqual(seo_url.make_slug(""), "gorsel")
		self.assertEqual(seo_url.make_slug(None), "gorsel")
		self.assertEqual(seo_url.make_slug("!!!"), "gorsel")


class TestCode(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.h1 = "abcdef01" + "1" * 24
		self.h2 = "abcdef01" + "2" * 24  # ilk 8'i aynı, içerik farklı
		self.u1 = f"/files/{self.h1[:2]}/{self.h1}.jpg"
		self.u2 = f"/files/{self.h2[:2]}/{self.h2}.jpg"

	def test_sekiz_karakter_sonra_cakismada_uzar(self):
		_file_row(self.u1)
		_file_row(self.u2)
		self.assertEqual(seo_url.assign_code(self.u1), self.h1[:8])
		self.assertEqual(seo_url.assign_code(self.u2), self.h2[:12])
		# İkinci çağrı kaydı değiştirmez
		self.assertEqual(seo_url.assign_code(self.u1), self.h1[:8])

	def test_eski_ad_kod_almaz(self):
		self.assertIsNone(seo_url.assign_code("/files/0585.jpg"))
		self.assertIsNone(seo_url.assign_code("/files/media/x/y.jpg"))

	def test_codes_for_tek_sorgu_ve_turev(self):
		_file_row(self.u1)
		seo_url.assign_code(self.u1)
		turev = f"/files/{self.h1[:2]}/{self.h1}__w384.webp"
		self.assertEqual(seo_url.codes_for([self.u1, turev, "/files/0585.jpg"]), {self.h1: self.h1[:8]})


class TestSeoImageUrl(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.h = "fedcba98" + "3" * 24
		self.u = f"/files/{self.h[:2]}/{self.h}.jpg"
		_file_row(self.u)
		seo_url.assign_code(self.u)

	def test_okunur_adres(self):
		self.assertEqual(seo_url.seo_image_url(self.u, "Ahşap Raf"), f"/files/ahsap-raf-{self.h[:8]}.jpg")

	def test_turev_son_eki_korunur(self):
		turev = f"/files/{self.h[:2]}/{self.h}__w384.webp"
		self.assertEqual(
			seo_url.seo_image_url(turev, "Ahşap Raf"), f"/files/ahsap-raf-{self.h[:8]}__w384.webp"
		)

	def test_geri_dusus(self):
		for girdi in ["/files/0585.jpg", "", None, "https://cdn.example.com/a.jpg", "/files/media/a/b.jpg"]:
			self.assertEqual(seo_url.seo_image_url(girdi, "X"), girdi or "")
		kodsuz = "/files/11/" + "1" * 32 + ".jpg"
		self.assertEqual(seo_url.seo_image_url(kodsuz, "X"), kodsuz)

	def test_query_string_atilir(self):
		self.assertEqual(seo_url.seo_image_url(self.u + "?v=1", "A"), f"/files/a-{self.h[:8]}.jpg")


class TestHookRealPath(FrappeTestCase):
	"""M-5(a) — review düzeltmesi: GERÇEK `after_insert` kancası (`ignore_seo_code`
	YOK). I-1 fix'inin doğru davrandığını kanıtlar: aynı hash'e ait ardışık iki
	INSERT de kendi satırına kısa kod alır ve ikisi de AYNI kodu paylaşır."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.h = "12ab34cd" + "9" * 24
		self.u = f"/files/{self.h[:2]}/{self.h}.jpg"
		_diskte_hazirla(self.u)

	def _insert(self) -> str:
		with mock.patch("tradehub_core.media.av.enqueue_scan"):
			d = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": self.u.rsplit("/", 1)[-1],
					"file_url": self.u,
					"is_private": 0,
				}
			)
			d.flags.copy_from_existing_file = True
			d.insert(ignore_permissions=True)
		return d.name

	def test_gercek_kanca_kod_atar_ve_ikinci_satir_ayni_kodu_paylasir(self):
		ad1 = self._insert()
		self.assertEqual(frappe.db.get_value("File", ad1, "seo_code"), self.h[:8])
		ad2 = self._insert()
		self.assertEqual(frappe.db.get_value("File", ad2, "seo_code"), self.h[:8])


class _RenameSeoBase(FrappeTestCase):
	"""`retro_rename` ile gerçek disk taşıması gerektiren SEO testleri için ortak kurulum."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=8)
		self.name = f"rr-seo-{self.suffix}.jpg"
		self.content = f"seo-{self.suffix}".encode()
		with open(os.path.join(get_files_path(is_private=0), self.name), "wb") as f:
			f.write(self.content)
		self.url = f"/files/{self.name}"
		self.h32 = hashlib.sha256(self.content).hexdigest()[:32]
		self.hedef = f"/files/{self.h32[:2]}/{self.h32}.jpg"
		with mock.patch("tradehub_core.media.av.enqueue_scan"):
			d = frappe.get_doc(
				{"doctype": "File", "file_name": self.name, "file_url": self.url, "is_private": 0}
			)
			d.flags.copy_from_existing_file = True
			d.flags.ignore_seo_code = True
			d.insert(ignore_permissions=True)
		self.file_name = d.name
		self.addCleanup(self._cleanup)

	def _cleanup(self):
		# `rename_one`/`run_job`/`run_rollback` kendi içinde commit ediyor
		# (bkz. retro_rename.py docstring'i) — FrappeTestCase'in test-başı
		# rollback'i bu satırları KAPSAMAZ. `_RenameBase._cleanup` (mevcut
		# `test_media_retro_rename.py`) deseniyle aynı: File satırını ve
		# `Media URL Redirect` satırını elle sil + commit et, yoksa her koşum
		# bir satır sızdırır (review sonrası bulundu — ilk yazımda bu adım
		# unutulmuştu, `job_key`'e göre değil KENDİ `source_url`'üne göre
		# temizleniyor ki başka bir koşunun satırına dokunmasın).
		frappe.db.rollback()
		if frappe.db.exists("File", self.file_name):
			frappe.delete_doc("File", self.file_name, force=True, ignore_permissions=True)
		frappe.db.delete("Media URL Redirect", {"source_url": self.url})
		frappe.db.commit()
		for p in (os.path.join(get_files_path(is_private=0), self.name), _disk_yolu(self.hedef)):
			if os.path.isfile(p):
				os.remove(p)
		frappe.cache.delete_value(retro_rename.ACTIVE_KEY)


class TestRenameOneAssignsCode(_RenameSeoBase):
	"""M-5(b): `rename_one` başarı dalı yeni (içerik-adresli) URL'e kod atar."""

	def test_rename_one_yeni_adrese_kod_atar(self):
		# job_key testler arası çakışmasın diye `self.suffix`'e bağlı (sabit
		# literal değil) — `Media URL Redirect.source_url` tekil olduğu için
		# zaten çakışmaz, ama job_key'in de rastgele olması ileride job_key
		# bazlı bir sorgu eklenirse sızıntıyı önler.
		out = retro_rename.rename_one(self.url, f"JOB-SEO-{self.suffix}", add_days(now_datetime(), 90))
		self.assertEqual(out["status"], "renamed")
		self.assertEqual(frappe.db.get_value("File", self.file_name, "seo_code"), self.h32[:8])


class TestRollbackClearsCode(_RenameSeoBase):
	"""M-5(c) — review I-2: geri alma eski adrese dönen satırın `seo_code`'unu temizler."""

	def test_rollback_seo_code_temizler(self):
		job_key = f"JOB-SEO-RB-{self.suffix}"
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]):
			retro_rename.run_job(job_key, dry_run=0, batch_size=10)
		self.assertEqual(frappe.db.get_value("File", self.file_name, "seo_code"), self.h32[:8])

		retro_rename.run_rollback(job_key, f"RB-{job_key}")
		self.assertEqual(frappe.db.get_value("File", self.file_name, "file_url"), self.url)
		self.assertIsNone(frappe.db.get_value("File", self.file_name, "seo_code"))


class TestCollisionIgnoresLegacyRows(FrappeTestCase):
	"""M-5(d) — review I-2: çarpışma kontrolü hash-şekilli OLMAYAN (legacy/artık)
	satırları yok sayar; aksi hâlde rollback'in kaçırdığı ya da elle set edilmiş
	bir eski kod, aynı içeriğin yeni atamasını gereksiz yere uzatırdı."""

	def test_legacy_satirdaki_kod_cakisma_saymaz(self):
		h = "aa11bb22" + "3" * 24
		u = f"/files/{h[:2]}/{h}.jpg"
		_diskte_hazirla(u)
		frappe.set_user("Administrator")
		d = frappe.get_doc(
			{"doctype": "File", "file_name": u.rsplit("/", 1)[-1], "file_url": u, "is_private": 0}
		)
		d.flags.copy_from_existing_file = True
		d.flags.ignore_seo_code = True
		d.insert(ignore_permissions=True)

		eski_url = "/files/eski-legacy-testi.jpg"
		_diskte_hazirla(eski_url)
		eski = frappe.get_doc(
			{"doctype": "File", "file_name": "eski-legacy-testi.jpg", "file_url": eski_url, "is_private": 0}
		)
		eski.flags.copy_from_existing_file = True
		eski.flags.ignore_seo_code = True
		eski.insert(ignore_permissions=True)
		# Rollback'in kaçırdığı ya da elle set edilmiş bir artık kodu simüle eder.
		frappe.db.set_value("File", eski.name, "seo_code", h[:8], update_modified=False)

		self.assertEqual(seo_url.assign_code(u), h[:8])


class TestKapsamVeBayrak(FrappeTestCase):
	"""Final review I-1 (yalnız görsel) + I-2 (kill switch) + M-4 (parçalı sorgu) + M-9 (sütun yok)."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.h = "5eed0001" + "4" * 24
		self.u = f"/files/{self.h[:2]}/{self.h}.jpg"
		_file_row(self.u)
		seo_url.assign_code(self.u)

	def test_video_ve_belge_kod_almaz(self):
		for uzanti in ("mp4", "txt", "tif", "pdf"):
			h = "5eed0002" + uzanti.encode().hex().ljust(24, "0")[:24]
			u = f"/files/{h[:2]}/{h}.{uzanti}"
			_file_row(u)
			self.assertIsNone(seo_url.assign_code(u), uzanti)

	def test_gorsel_olmayan_uzanti_okunur_adres_almaz(self):
		"""Kod elle (ör. ilk sürümün backfill'i) atanmış olsa bile mp4 ham kalır."""
		h = "5eed0003" + "5" * 24
		u = f"/files/{h[:2]}/{h}.mp4"
		_file_row(u)
		frappe.db.sql("update `tabFile` set seo_code=%s where file_url=%s", (h[:8], u))
		self.assertEqual(seo_url.seo_image_url(u, "Video"), u)

	def test_bayrak_kapaliyken_ham_adres(self):
		self.assertEqual(seo_url.seo_image_url(self.u, "Raf"), f"/files/raf-{self.h[:8]}.jpg")
		with mock.patch.dict(frappe.local.conf, {seo_url.BAYRAK: 0}):
			self.assertFalse(seo_url.acik_mi())
			self.assertEqual(seo_url.seo_image_url(self.u, "Raf"), self.u)
			self.assertEqual(seo_url.seo_image_url(self.u, "Raf", {self.h: self.h[:8]}), self.u)
		eksik = {k: v for k, v in frappe.local.conf.items() if k != seo_url.BAYRAK}
		with mock.patch.object(frappe.local, "conf", frappe._dict(eksik)):
			self.assertFalse(seo_url.acik_mi(), "anahtar yoksa kapalı (güvenli varsayılan)")

	def test_codes_for_parcali_sorgu(self):
		h2 = "5eed0004" + "6" * 24
		u2 = f"/files/{h2[:2]}/{h2}.png"
		_file_row(u2)
		seo_url.assign_code(u2)
		gercek = frappe.db.sql
		with (
			mock.patch.object(seo_url, "CODES_CHUNK", 1),
			mock.patch.object(frappe.db, "sql", side_effect=gercek) as casus,
		):
			sonuc = seo_url.codes_for([self.u, u2, "/files/0585.jpg"])
		self.assertEqual(sonuc, {self.h: self.h[:8], h2: h2[:8]})
		self.assertEqual(casus.call_count, 2)

	def test_sutun_yoksa_bos_sozluk_ve_yok(self):
		import pymysql

		hata = pymysql.err.OperationalError(1054, "Unknown column 'seo_code' in 'where clause'")
		with mock.patch.object(frappe.db, "sql", side_effect=hata):
			self.assertEqual(seo_url.codes_for([self.u]), {})
		with mock.patch.object(frappe, "get_all", side_effect=hata):
			self.assertEqual(seo_url.resolve(f"files/raf-{self.h[:8]}.jpg")["status"], "yok")
		baska = pymysql.err.OperationalError(1205, "Lock wait timeout")
		with (
			mock.patch.object(frappe.db, "sql", side_effect=baska),
			self.assertRaises(pymysql.err.OperationalError),
		):
			seo_url.codes_for([self.u])

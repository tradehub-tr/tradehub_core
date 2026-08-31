"""Medya retro-rename (MOGEM-582 alt görevi) — eski tahmin edilebilir adların
içerik-adresli ada taşınması, 301 köprüsü ve geri alma.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_retro_rename
"""

from __future__ import annotations

import hashlib
import os
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, get_files_path, now_datetime

from tradehub_core.media import refs, retro_rename

# Tarama kancası bu modülde nötrleniyor: `hold_until_clean` açıkken dosya
# insert anında public ağaçtan çıkarılıyor ve diskten okuyan testler
# `FileNotFoundError` alıyor. Gerekçe `tests/av_notr.py` başlığında.
from tradehub_core.tests.av_notr import setUpModule, tearDownModule  # noqa: F401


def _write_flat_public(name: str, content: bytes) -> str:
	"""Eski düzen: shard'sız, public/files/<name>. `/files/<name>` döner."""
	base = get_files_path(is_private=0)
	with open(os.path.join(base, name), "wb") as f:
		f.write(content)
	return f"/files/{name}"


class TestMediaUrlRedirectDoctype(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(lambda: frappe.db.delete("Media URL Redirect", {"job_key": "TEST-DT"}))

	def test_source_url_tekil(self):
		frappe.get_doc(
			{
				"doctype": "Media URL Redirect",
				"source_url": "/files/test-dt-eski.jpg",
				"target_url": "/files/ab/abcdef.jpg",
				"job_key": "TEST-DT",
				"expires_at": add_days(now_datetime(), 90),
			}
		).insert(ignore_permissions=True)
		with self.assertRaises(frappe.UniqueValidationError):
			frappe.get_doc(
				{
					"doctype": "Media URL Redirect",
					"source_url": "/files/test-dt-eski.jpg",
					"target_url": "/files/ab/ffffff.jpg",
					"job_key": "TEST-DT",
					"expires_at": add_days(now_datetime(), 90),
				}
			).insert(ignore_permissions=True)

	def test_mutlak_hedef_reddedilir(self):
		"""301 `Location`'a giden adres site-içi olmalı — aksi hâlde açık yönlendirme."""
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Media URL Redirect",
					"source_url": "/files/test-dt-mutlak.jpg",
					"target_url": "https://kotu.example/ele-gecir.jpg",
					"job_key": "TEST-DT",
					"expires_at": add_days(now_datetime(), 90),
				}
			).insert(ignore_permissions=True)

	def test_yol_gecisi_segmenti_reddedilir(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Media URL Redirect",
					"source_url": "/files/../etc/passwd",
					"target_url": "/files/ab/" + "a" * 32 + ".jpg",
					"job_key": "TEST-DT",
					"expires_at": add_days(now_datetime(), 90),
				}
			).insert(ignore_permissions=True)


class TestLegacyNameAndTarget(FrappeTestCase):
	def test_is_legacy_name(self):
		self.assertTrue(retro_rename.is_legacy_name("/files/0505.jpg"))
		self.assertTrue(retro_rename.is_legacy_name("/files/515804-5.jpg"))
		self.assertTrue(retro_rename.is_legacy_name("/files/Adsız tasarım.png"))
		self.assertFalse(retro_rename.is_legacy_name("/files/ab/" + "a" * 32 + ".jpg"))
		self.assertFalse(retro_rename.is_legacy_name("/files/media/ASSET/" + "f" * 64 + "/thumb-320.webp"))
		self.assertFalse(retro_rename.is_legacy_name("/private/files/0505.jpg"))
		self.assertFalse(retro_rename.is_legacy_name(""))
		# Alt dizinli ama hash'siz eski dosya da eski sayılır (ör. /files/eski/foto.JPG)
		self.assertTrue(retro_rename.is_legacy_name("/files/eski/foto.JPG"))
		# Cümle sonu nokta ile biten gerçek eski dosya adı — segment-düzeyi kontrol
		# alt-dizge kontrolünün (eski `".." in url`) yanlışlıkla reddettiği örnek.
		self.assertTrue(retro_rename.is_legacy_name("/files/cümle sonu..jpg"))
		# Gerçek yol-geçişi denemeleri hâlâ reddedilir.
		self.assertFalse(retro_rename.is_legacy_name("/files/../etc/passwd"))
		self.assertFalse(retro_rename.is_legacy_name("/files/a/../b.jpg"))

	def test_disk_path_yol_gecisini_reddeder(self):
		with self.assertRaises(frappe.ValidationError):
			retro_rename._disk_path("/files/../etc/passwd")

	def test_target_url_nokta_ile_biten_dosya_adi(self):
		"""Cümle sonu nokta ile biten gerçek dosya — round-trip: taşınabilir aday, target_url hesaplanır."""
		suffix = frappe.generate_hash(length=8)
		name = f"rr-nokta-{suffix}..jpg"
		content = f"nokta-{suffix}".encode()
		url = _write_flat_public(name, content)
		self.addCleanup(
			lambda: os.path.exists(p := os.path.join(get_files_path(is_private=0), name)) and os.remove(p)
		)
		self.assertTrue(retro_rename.is_legacy_name(url))
		h = hashlib.sha256(content).hexdigest()[:32]
		self.assertEqual(retro_rename.target_url(url), f"/files/{h[:2]}/{h}.jpg")

	def test_target_url_icerik_hashli_ve_shardli(self):
		suffix = frappe.generate_hash(length=8)
		name = f"rr-{suffix}.JPG"
		content = f"retro-{suffix}".encode()
		url = _write_flat_public(name, content)
		self.addCleanup(
			lambda: os.path.exists(p := os.path.join(get_files_path(is_private=0), name)) and os.remove(p)
		)
		import hashlib

		h = hashlib.sha256(content).hexdigest()[:32]
		self.assertEqual(retro_rename.target_url(url), f"/files/{h[:2]}/{h}.jpg")

	def test_target_url_dosya_yoksa_hata(self):
		with self.assertRaises(FileNotFoundError):
			retro_rename.target_url("/files/rr-yok-boyle-dosya.jpg")


class TestPlan(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=8)
		self.name = f"rr-plan-{self.suffix}.jpg"
		self.content = f"plan-{self.suffix}".encode()
		self.url = _write_flat_public(self.name, self.content)
		self.addCleanup(
			lambda: (
				os.path.exists(p := os.path.join(get_files_path(is_private=0), self.name)) and os.remove(p)
			)
		)
		for _ in range(2):  # aynı URL'yi paylaşan iki File satırı
			d = frappe.get_doc(
				{"doctype": "File", "file_name": self.name, "file_url": self.url, "is_private": 0}
			)
			# Disk'te zaten var olan blob'u yeniden işlemeden (save_file/exif-strip
			# tetiklemeden) File satırı oluştur — burada amaç sadece aynı URL'yi
			# paylaşan iki `File` kaydı üretmek, gerçek bir yükleme akışı değil.
			d.flags.copy_from_existing_file = True
			d.insert(ignore_permissions=True)
			self.addCleanup(
				lambda n=d.name: frappe.delete_doc("File", n, force=True, ignore_permissions=True)
			)
		frappe.db.commit()

	def test_plan_adayi_ve_sayaclari_listeler(self):
		p = retro_rename.plan()
		item = next(i for i in p["items"] if i["source_url"] == self.url)
		self.assertEqual(item["file_rows"], 2)
		self.assertTrue(item["orphan"])
		self.assertFalse(item["disk_missing"])
		self.assertFalse(item["collision"])
		self.assertTrue(item["target_url"].startswith("/files/"))
		self.assertGreaterEqual(p["total"], 1)
		self.assertGreaterEqual(p["orphans"], 1)

	def test_plan_diskte_olmayani_isaretler(self):
		os.remove(os.path.join(get_files_path(is_private=0), self.name))
		p = retro_rename.plan()
		item = next(i for i in p["items"] if i["source_url"] == self.url)
		self.assertTrue(item["disk_missing"])
		self.assertIsNone(item["target_url"])
		self.assertGreaterEqual(p["disk_missing"], 1)

	def test_plan_salt_okunur(self):
		before = frappe.db.get_value("File", {"file_url": self.url}, "file_url")
		retro_rename.plan()
		self.assertEqual(frappe.db.get_value("File", {"file_url": self.url}, "file_url"), before)
		self.assertTrue(os.path.isfile(os.path.join(get_files_path(is_private=0), self.name)))

	def test_plan_limit_sifir_bos_items_ama_sayaclar_tam(self):
		p = retro_rename.plan(limit=0)
		self.assertEqual(p["items"], [])
		self.assertGreaterEqual(p["total"], 1)
		self.assertGreaterEqual(p["orphans"], 1)
		self.assertTrue(p["truncated"])

	def test_plan_limit_none_cap(self):
		p = retro_rename.plan()
		self.assertEqual(len(p["items"]), min(p["total"], retro_rename.PLAN_ITEM_LIMIT))


def _make_file_row(name: str, url: str) -> str:
	"""Verilen `file_url`'i işaret eden bir `File` satırı — diskteki blob'a dokunmadan.

	`copy_from_existing_file`: Frappe'nin `before_insert`'i diskteki blob'u yeniden
	işlemesin (dev site'ta exif-strip açık → str/bytes çakışması). `enqueue_scan`
	nötrlenir: makinede ClamAV kuruluysa `after_insert` dosyayı `media_scan_hold`'a
	taşıyor ve rename "diskte yok" diyordu (test_media_access_level deseni).
	"""
	doc = frappe.get_doc({"doctype": "File", "file_name": name, "file_url": url, "is_private": 0})
	doc.flags.copy_from_existing_file = True
	doc.flags.ignore_mandatory = True
	with mock.patch("tradehub_core.media.av.enqueue_scan"):
		doc.insert(ignore_permissions=True)
	return doc.name


def _make_listing(baslik: str, primary_image: str) -> str:
	"""`primary_image` alanı retarget edilecek asgari Listing (access_level fixture deseni)."""
	doc = frappe.get_doc(
		{
			"doctype": "Listing",
			"listing_code": f"RETRO-{frappe.generate_hash(length=8)}",
			"title": baslik,
			"status": "Active",
			"currency": "TRY",
			"base_price": 100,
			"selling_price": 100,
			"primary_image": primary_image,
		}
	)
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _hedef_url(content: bytes, ext: str = ".jpg") -> str:
	h = hashlib.sha256(content).hexdigest()[:32]
	return f"/files/{h[:2]}/{h}{ext}"


class _RenameBase(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=8)
		self.name = f"rr-job-{self.suffix}.jpg"
		self.content = f"job-{self.suffix}".encode()
		self.url = _write_flat_public(self.name, self.content)
		self.files = [_make_file_row(self.name, self.url) for _ in range(3)]
		self.listing = _make_listing(f"RR {self.suffix}", self.url)
		frappe.db.commit()
		self.addCleanup(self._cleanup)

	def _cleanup(self):
		frappe.db.rollback()
		for n in self.files:
			if frappe.db.exists("File", n):
				frappe.delete_doc("File", n, force=True, ignore_permissions=True)
		if frappe.db.exists("Listing", self.listing):
			frappe.delete_doc("Listing", self.listing, force=True, ignore_permissions=True)
		frappe.db.delete("Media URL Redirect", {"source_url": self.url})
		frappe.db.commit()
		base = get_files_path(is_private=0)
		for p in [os.path.join(base, self.name), getattr(self, "_new_path", "")]:
			if p and os.path.isfile(p):
				os.remove(p)
		frappe.cache.delete_value(retro_rename.ACTIVE_KEY)

	def _expected_target(self) -> str:
		hedef = _hedef_url(self.content)
		self._new_path = os.path.join(get_files_path(is_private=0), *hedef[len("/files/") :].split("/"))
		return hedef


class TestRenameOne(_RenameBase):
	def test_tam_akis(self):
		hedef = self._expected_target()
		out = retro_rename.rename_one(self.url, "JOB-T", add_days(now_datetime(), 90))
		self.assertEqual(out["status"], "renamed")
		self.assertEqual(out["target_url"], hedef)
		self.assertFalse(os.path.isfile(os.path.join(get_files_path(is_private=0), self.name)))
		self.assertTrue(os.path.isfile(self._new_path))
		self.assertEqual(frappe.db.count("File", {"file_url": hedef}), 3)
		self.assertEqual(frappe.db.count("File", {"file_url": self.url}), 0)
		self.assertEqual(frappe.db.get_value("Listing", self.listing, "primary_image"), hedef)
		r = frappe.db.get_value(
			"Media URL Redirect",
			{"source_url": self.url},
			["target_url", "job_key", "file_rows"],
			as_dict=True,
		)
		self.assertEqual((r.target_url, r.job_key, r.file_rows), (hedef, "JOB-T", 3))

	def test_db_hatasinda_disk_geri_alinir(self):
		self._expected_target()
		with mock.patch.object(refs, "retarget", side_effect=RuntimeError("boom")):
			out = retro_rename.rename_one(self.url, "JOB-E", add_days(now_datetime(), 90))
		self.assertEqual(out["status"], "error")
		self.assertTrue(os.path.isfile(os.path.join(get_files_path(is_private=0), self.name)))
		self.assertFalse(os.path.isfile(self._new_path))
		self.assertEqual(frappe.db.count("File", {"file_url": self.url}), 3)
		self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": self.url}))

	def test_idempotent_ikinci_kosu_atlar(self):
		self._expected_target()
		retro_rename.rename_one(self.url, "JOB-I", add_days(now_datetime(), 90))
		out = retro_rename.rename_one(self.url, "JOB-I", add_days(now_datetime(), 90))
		self.assertEqual((out["status"], out["reason"]), ("skipped", "disk_missing"))

	def test_yeni_ad_zaten_hedefse_atlanir(self):
		out = retro_rename.rename_one("/files/ab/" + "c" * 32 + ".jpg", "JOB-N", None)
		self.assertEqual((out["status"], out["reason"]), ("skipped", "not_legacy"))

	def test_basarili_commit_404_onbellegini_hemen_temizler(self):
		"""İlk 25 dosya da heartbeat beklemeden 301 olarak görünür olmalı."""
		self._expected_target()
		with mock.patch.object(retro_rename, "_clear_404_cache") as clear:
			out = retro_rename.rename_one(self.url, "JOB-CACHE", add_days(now_datetime(), 90))
		self.assertEqual(out["status"], "renamed")
		clear.assert_called_once_with()


class TestRunJobAndRollback(_RenameBase):
	def test_run_job_ilerleme_ve_rollback(self):
		hedef = self._expected_target()
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]):
			retro_rename.run_job("JOB-R", dry_run=0, batch_size=10)
		p = retro_rename.read_progress("JOB-R")
		self.assertEqual(p["state"], "completed")
		self.assertEqual((p["total"], p["processed"], p["renamed"], p["errors"]), (1, 1, 1, 0))
		# Dosya sayısı ≠ referans sayısı: `_make_listing` `primary_image` alanı
		# retarget edildi, yani en az 1 referans güncellendi ve yük bunu taşımalı.
		self.assertGreaterEqual(p["refs_updated"], 1)
		self.assertEqual(p["refs_skipped"], 0)
		self.assertEqual(frappe.db.get_value("Listing", self.listing, "primary_image"), hedef)
		self.assertIsNone(frappe.cache.get_value(retro_rename.ACTIVE_KEY))

		retro_rename.run_rollback("JOB-R", "RB-1")
		rp = retro_rename.read_progress("RB-1")
		self.assertEqual(rp["state"], "completed")
		self.assertGreaterEqual(rp["refs_updated"], 1)
		self.assertTrue(os.path.isfile(os.path.join(get_files_path(is_private=0), self.name)))
		self.assertFalse(os.path.isfile(self._new_path))
		self.assertEqual(frappe.db.count("File", {"file_url": self.url}), 3)
		self.assertEqual(frappe.db.get_value("Listing", self.listing, "primary_image"), self.url)
		self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": self.url}))

	def test_run_job_website_404_onbellegini_temizler(self):
		"""`PathResolver.resolve()` custom renderer'lardan ÖNCE `website_404`'e bakıyor.

		Taşıma ile commit arasında istenen eski adres 404 olarak önbelleğe
		yazılırsa 301 bir daha çalışmaz (girdi kendiliğinden düşmez). İş nabzı ve
		`finally` bloğu anahtarı silmeli.
		"""
		self._expected_target()
		with (
			mock.patch.object(frappe.cache, "delete_value") as sil,
			mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]),
		):
			retro_rename.run_job("JOB-404", dry_run=1, batch_size=10)
		self.assertIn(mock.call("website_404"), sil.call_args_list)

	def test_dry_run_hicbir_sey_yazmaz(self):
		self._expected_target()
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]):
			retro_rename.run_job("JOB-D", dry_run=1, batch_size=10)
		p = retro_rename.read_progress("JOB-D")
		self.assertEqual(p["state"], "completed")
		self.assertTrue(p["dry_run"])
		self.assertTrue(os.path.isfile(os.path.join(get_files_path(is_private=0), self.name)))
		self.assertFalse(os.path.isfile(self._new_path))
		self.assertEqual(frappe.db.count("File", {"file_url": self.url}), 3)
		self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": self.url}))

	def test_stop_bayragi_batch_sinirinda_durdurur(self):
		self._expected_target()
		retro_rename.request_stop("JOB-S")
		self.addCleanup(lambda: frappe.cache.delete_value(retro_rename._stop_key("JOB-S")))
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]):
			retro_rename.run_job("JOB-S", dry_run=0, batch_size=1)
		self.assertEqual(retro_rename.read_progress("JOB-S")["state"], "stopped")
		self.assertTrue(os.path.isfile(os.path.join(get_files_path(is_private=0), self.name)))
		self.assertEqual(frappe.db.count("File", {"file_url": self.url}), 3)

	def test_stop_is_ortasinda_istenirse_yine_batch_sinirinda_durur(self):
		"""`_stop_requested` `expires=True` OLMADAN worker'ın TEK `frappe.init()`'lik
		ömrü boyunca ilk okuduğu `None`'ı sonsuza dek önbellekte tutardı — yukarıdaki
		`test_stop_bayragi_batch_sinirinda_durdurur` bayrağı iş BAŞLAMADAN kuruyor,
		yani bu hatayı yakalayamaz (ilk okuma zaten `1` görüyor). Bu test bayrağı
		işin ORTASINDA — ilk dosya işlendikten SONRA, worker hâlâ aynı süreçte
		çalışırken — kuruyor; `expires=True` olmadan ikinci/üçüncü dosya da işlenirdi.
		"""
		job_key = "JOB-MID-STOP"
		self.addCleanup(lambda: frappe.cache.delete_value(retro_rename._stop_key(job_key)))
		urls = [f"/files/{c}{c}/" + c * 32 + ".jpg" for c in ("a", "b", "c")]

		def fake_rename_one(url, jk, expires_at, *, dry_run=False):
			if url == urls[0]:
				retro_rename.request_stop(job_key)
			return {
				"status": "renamed",
				"reason": "",
				"target_url": "/files/xx/" + "x" * 32 + ".jpg",
				"refs_updated": 0,
				"refs_skipped": 0,
			}

		with (
			mock.patch.object(retro_rename, "legacy_urls", return_value=urls),
			mock.patch.object(retro_rename, "rename_one", side_effect=fake_rename_one),
		):
			retro_rename.run_job(job_key, dry_run=0, batch_size=1)
		p = retro_rename.read_progress(job_key)
		self.assertEqual(p["state"], "stopped")
		self.assertEqual(p["processed"], 1)

	def test_rollback_sonradan_kullanici_degisikligini_ezmez(self):
		hedef = self._expected_target()
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]):
			retro_rename.run_job("JOB-USER-REF", dry_run=0, batch_size=10)
		self.assertEqual(frappe.db.get_value("Listing", self.listing, "primary_image"), hedef)

		user_value = "/files/kullanici-sonradan-secti.jpg"
		frappe.db.set_value("Listing", self.listing, "primary_image", user_value, update_modified=False)
		frappe.db.commit()
		retro_rename.run_rollback("JOB-USER-REF", "RB-USER-REF")

		rp = retro_rename.read_progress("RB-USER-REF")
		self.assertEqual(rp["state"], "completed")
		self.assertGreaterEqual(rp["refs_skipped"], 1)
		self.assertEqual(frappe.db.get_value("Listing", self.listing, "primary_image"), user_value)


class TestActiveJobLock(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.cache.delete_value(retro_rename.ACTIVE_KEY)
		self.addCleanup(lambda: frappe.cache.delete_value(retro_rename.ACTIVE_KEY))

	def test_atomik_sahiplik_ve_compare_delete(self):
		self.assertTrue(retro_rename.claim_active("LOCK-A", ttl=60))
		self.assertFalse(retro_rename.claim_active("LOCK-B", ttl=60))
		self.assertEqual(frappe.cache.get_value(retro_rename.ACTIVE_KEY, expires=True), "LOCK-A")
		self.assertFalse(retro_rename.release_active("LOCK-B"))
		self.assertEqual(frappe.cache.get_value(retro_rename.ACTIVE_KEY, expires=True), "LOCK-A")
		self.assertTrue(retro_rename.acquire_or_refresh_active("LOCK-A", ttl=60))
		self.assertTrue(retro_rename.release_active("LOCK-A"))
		self.assertIsNone(frappe.cache.get_value(retro_rename.ACTIVE_KEY, expires=True))

	def test_worker_baska_sahibin_kilidini_ezmez(self):
		self.assertTrue(retro_rename.claim_active("LOCK-OWNER", ttl=60))
		with (
			mock.patch.object(retro_rename, "legacy_urls") as legacy,
			mock.patch.object(retro_rename, "rename_one") as rename,
		):
			retro_rename.run_job("LOCK-INTRUDER", dry_run=0, batch_size=1)
		legacy.assert_not_called()
		rename.assert_not_called()
		self.assertEqual(retro_rename.read_progress("LOCK-INTRUDER")["state"], "error")
		self.assertEqual(frappe.cache.get_value(retro_rename.ACTIVE_KEY, expires=True), "LOCK-OWNER")


class TestDedupRollback(FrappeTestCase):
	"""Dedup tuzağı: iki eski ad AYNI içeriğe sahip → tek hedef, iki redirect satırı.

	Rollback ilk satırda hedefteki TÜM `File` kayıtlarını geri çevirirse ikinci
	satıra bir şey kalmaz; `file_rows` bunu satır başına sınırlar.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		suffix = frappe.generate_hash(length=8)
		self.content = f"dup-{suffix}".encode()
		self.ad_a = f"rr-dup-a-{suffix}.jpg"
		self.ad_b = f"rr-dup-b-{suffix}.jpg"
		self.url_a = _write_flat_public(self.ad_a, self.content)
		self.url_b = _write_flat_public(self.ad_b, self.content)
		self.files = [_make_file_row(self.ad_a, self.url_a), _make_file_row(self.ad_b, self.url_b)]
		self.listing_a = _make_listing(f"RR DUP A {suffix}", self.url_a)
		self.listing_b = _make_listing(f"RR DUP B {suffix}", self.url_b)
		self.hedef = _hedef_url(self.content)
		self.hedef_path = os.path.join(get_files_path(is_private=0), *self.hedef[len("/files/") :].split("/"))
		frappe.db.commit()
		self.addCleanup(self._cleanup)

	def _cleanup(self):
		frappe.db.rollback()
		for n in self.files:
			if frappe.db.exists("File", n):
				frappe.delete_doc("File", n, force=True, ignore_permissions=True)
		for n in (self.listing_a, self.listing_b):
			if frappe.db.exists("Listing", n):
				frappe.delete_doc("Listing", n, force=True, ignore_permissions=True)
		frappe.db.delete("Media URL Redirect", {"job_key": "JOB-DUP"})
		frappe.db.commit()
		base = get_files_path(is_private=0)
		for p in [os.path.join(base, self.ad_a), os.path.join(base, self.ad_b), self.hedef_path]:
			if os.path.isfile(p):
				os.remove(p)
		frappe.cache.delete_value(retro_rename.ACTIVE_KEY)

	def test_dedup_rollback_yalniz_kendi_satirlarini_dondurur(self):
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url_a, self.url_b]):
			retro_rename.run_job("JOB-DUP", dry_run=0, batch_size=10)
		p = retro_rename.read_progress("JOB-DUP")
		self.assertEqual((p["state"], p["renamed"], p["errors"]), ("completed", 2, 0))
		self.assertEqual(frappe.db.count("File", {"file_url": self.hedef}), 2)
		self.assertTrue(os.path.isfile(self.hedef_path))
		self.assertEqual(frappe.db.count("Media URL Redirect", {"job_key": "JOB-DUP"}), 2)
		self.assertEqual(frappe.db.get_value("Listing", self.listing_a, "primary_image"), self.hedef)
		self.assertEqual(frappe.db.get_value("Listing", self.listing_b, "primary_image"), self.hedef)

		retro_rename.run_rollback("JOB-DUP", "RB-DUP")
		rp = retro_rename.read_progress("RB-DUP")
		self.assertEqual((rp["state"], rp["errors"]), ("completed", 0))
		# KİMLİK: her `File` satırı KENDİ eski adresine döner — sayı değil, ad
		# üzerinden (`Media URL Redirect.file_names`). Sayı-tabanlı geri çevirme
		# ikisini çaprazlayabiliyordu.
		self.assertEqual(frappe.db.get_value("File", self.files[0], "file_url"), self.url_a)
		self.assertEqual(frappe.db.get_value("File", self.files[1], "file_url"), self.url_b)
		self.assertEqual(frappe.db.count("File", {"file_url": self.url_a}), 1)
		self.assertEqual(frappe.db.count("File", {"file_url": self.url_b}), 1)
		self.assertEqual(frappe.db.count("File", {"file_url": self.hedef}), 0)
		self.assertEqual(frappe.db.get_value("Listing", self.listing_a, "primary_image"), self.url_a)
		self.assertEqual(frappe.db.get_value("Listing", self.listing_b, "primary_image"), self.url_b)
		base = get_files_path(is_private=0)
		self.assertTrue(os.path.isfile(os.path.join(base, self.ad_a)))
		self.assertTrue(os.path.isfile(os.path.join(base, self.ad_b)))
		self.assertFalse(os.path.isfile(self.hedef_path))
		self.assertEqual(frappe.db.count("Media URL Redirect", {"job_key": "JOB-DUP"}), 0)

	def test_dedup_dalinda_db_hatasi_eski_dosyayi_silmez(self):
		"""Dedup dalında disk adımı commit'ten SONRA: DB patlarsa eski ad yerinde kalır.

		Eski sıra (önce sil, hata → hedefi eski ada kopyala) bir başarısızlık
		modu daha taşıyordu: kopyalama da patlarsa (disk dolu/izin) `File`
		satırları diskte olmayan bir adresi gösterirdi.
		"""
		out = retro_rename.rename_one(self.url_a, "JOB-DUP", add_days(now_datetime(), 90))
		self.assertEqual(out["status"], "renamed")
		base = get_files_path(is_private=0)

		with mock.patch.object(refs, "retarget", side_effect=RuntimeError("boom")):
			out_b = retro_rename.rename_one(self.url_b, "JOB-DUP", add_days(now_datetime(), 90))

		self.assertEqual(out_b["status"], "error")
		self.assertTrue(os.path.isfile(os.path.join(base, self.ad_b)))
		self.assertTrue(os.path.isfile(self.hedef_path))
		self.assertEqual(frappe.db.count("File", {"file_url": self.url_b}), 1)
		self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": self.url_b}))

	def test_dedup_artigi_silinemezse_skip_reasons_a_yazilir(self):
		"""Commit sonrası `os.remove` patlarsa: taşıma başarılı ama eski ad diskte kalır.

		`File` satırı kalmadığı için bu artık başka hiçbir ekranda görünmez —
		tahmin edilebilir eski adres servis edilmeye devam eder. Operatör panelde
		görebilsin diye `skip_reasons` altında sayılır.
		"""
		retro_rename.rename_one(self.url_a, "JOB-DUP", add_days(now_datetime(), 90))
		with mock.patch("os.remove", side_effect=OSError("bum")):
			with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url_b]):
				retro_rename.run_job("JOB-DUP", dry_run=0, batch_size=10)
		p = retro_rename.read_progress("JOB-DUP")
		self.assertEqual((p["renamed"], p["errors"]), (1, 0))
		self.assertEqual(p["skip_reasons"].get("dedup_leftover"), 1)
		self.assertTrue(os.path.isfile(os.path.join(get_files_path(is_private=0), self.ad_b)))
		self.assertEqual(frappe.db.count("File", {"file_url": self.hedef}), 2)


class TestRenameOneDiskErrors(_RenameBase):
	def test_disk_okuma_hatasi_isi_dusurmez_dosya_yerinde_kalir(self):
		"""Dosya `isfile` ile `open` arasında kaybolursa: error, ama iş devam eder."""
		with mock.patch.object(retro_rename, "target_url", side_effect=FileNotFoundError("gitti")):
			with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]):
				retro_rename.run_job("JOB-IO", dry_run=0, batch_size=10)
		p = retro_rename.read_progress("JOB-IO")
		self.assertEqual((p["state"], p["processed"], p["errors"]), ("partial", 1, 1))
		self.assertTrue(os.path.isfile(os.path.join(get_files_path(is_private=0), self.name)))
		self.assertEqual(frappe.db.count("File", {"file_url": self.url}), 3)


class TestRollbackHedeftekiYabanciSatir(FrappeTestCase):
	"""Hedefte retro-rename DIŞINDA oluşmuş bir `File` satırı varsa blob taşınmaz.

	Senaryo: aynı içerik hem eski düzende (`/files/x.jpg`) hem de doğal yoldan
	hash'li adla yüklenmiş. Taşıma dedup'a düşer; geri alırken hedefteki ikiz
	satır hâlâ o adresi gösterdiği için blob hedefte KALMALI, eski ad KOPYA ile
	geri gelmeli. Aksi hâlde ikiz satır kırık referansa dönerdi.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		suffix = frappe.generate_hash(length=8)
		self.content = f"twin-{suffix}".encode()
		self.ad_a = f"rr-twin-{suffix}.jpg"
		self.url_a = _write_flat_public(self.ad_a, self.content)
		self.hedef = _hedef_url(self.content)
		self.hedef_path = os.path.join(get_files_path(is_private=0), *self.hedef[len("/files/") :].split("/"))
		frappe.create_folder(os.path.dirname(self.hedef_path))
		with open(self.hedef_path, "wb") as f:
			f.write(self.content)
		self.file_a = _make_file_row(self.ad_a, self.url_a)
		self.file_ikiz = _make_file_row(os.path.basename(self.hedef), self.hedef)
		self.target_listing = _make_listing(f"RR doğal hedef {suffix}", self.hedef)
		frappe.db.commit()
		self.addCleanup(self._cleanup)

	def _cleanup(self):
		frappe.db.rollback()
		for n in (self.file_a, self.file_ikiz):
			if frappe.db.exists("File", n):
				frappe.delete_doc("File", n, force=True, ignore_permissions=True)
		if frappe.db.exists("Listing", self.target_listing):
			frappe.delete_doc("Listing", self.target_listing, force=True, ignore_permissions=True)
		frappe.db.delete("Media URL Redirect", {"job_key": "JOB-TWIN"})
		frappe.db.commit()
		for p in [os.path.join(get_files_path(is_private=0), self.ad_a), self.hedef_path]:
			if os.path.isfile(p):
				os.remove(p)
		frappe.cache.delete_value(retro_rename.ACTIVE_KEY)

	def test_rollback_hedefte_satir_kalirsa_blob_tasinmaz(self):
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url_a]):
			retro_rename.run_job("JOB-TWIN", dry_run=0, batch_size=10)
		self.assertEqual(retro_rename.read_progress("JOB-TWIN")["renamed"], 1)
		self.assertEqual(frappe.db.count("File", {"file_url": self.hedef}), 2)

		retro_rename.run_rollback("JOB-TWIN", "RB-TWIN")
		rp = retro_rename.read_progress("RB-TWIN")
		self.assertEqual((rp["state"], rp["errors"]), ("completed", 0))
		self.assertTrue(os.path.isfile(self.hedef_path), "ikiz satır hâlâ hedefi gösteriyor")
		self.assertTrue(os.path.isfile(os.path.join(get_files_path(is_private=0), self.ad_a)))
		self.assertEqual(frappe.db.get_value("File", self.file_ikiz, "file_url"), self.hedef)
		self.assertEqual(frappe.db.get_value("File", self.file_a, "file_url"), self.url_a)
		self.assertEqual(frappe.db.count("File", {"file_url": self.hedef}), 1)
		self.assertEqual(
			frappe.db.get_value("Listing", self.target_listing, "primary_image"),
			self.hedef,
			"retro-rename dışında hedefi kullanan referans geri alınmamalı",
		)


class TestRollbackDiskHatasi(_RenameBase):
	def test_rollback_disk_hatasi_satiri_error_sayar_satir_durur(self):
		self._expected_target()
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]):
			retro_rename.run_job("JOB-RB-IO", dry_run=0, batch_size=10)
		with mock.patch.object(retro_rename, "_stage_rollback_source", side_effect=OSError("bum")):
			retro_rename.run_rollback("JOB-RB-IO", "RB-IO")
		rp = retro_rename.read_progress("RB-IO")
		self.assertEqual((rp["state"], rp["processed"], rp["errors"]), ("partial", 1, 1))
		# Yönlendirme satırı DURUR: geri alma tekrar denenebilmeli.
		self.assertTrue(frappe.db.exists("Media URL Redirect", {"source_url": self.url}))
		self.assertTrue(os.path.isfile(self._new_path))
		self.assertEqual(frappe.db.count("File", {"file_url": self._expected_target()}), 3)

	def test_rollback_eski_yolda_yabanci_dosyayi_ezmez(self):
		self._expected_target()
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]):
			retro_rename.run_job("JOB-RB-COLLISION", dry_run=0, batch_size=10)
		old_path = os.path.join(get_files_path(is_private=0), self.name)
		foreign = b"sonradan-yuklenen-yabanci-dosya"
		with open(old_path, "wb") as f:
			f.write(foreign)

		retro_rename.run_rollback("JOB-RB-COLLISION", "RB-COLLISION")
		rp = retro_rename.read_progress("RB-COLLISION")
		self.assertEqual((rp["state"], rp["errors"]), ("partial", 1))
		self.assertEqual(rp["skip_reasons"].get("source_collision"), 1)
		with open(old_path, "rb") as f:
			self.assertEqual(f.read(), foreign)
		self.assertTrue(os.path.isfile(self._new_path))
		self.assertTrue(frappe.db.exists("Media URL Redirect", {"source_url": self.url}))

	def test_rollback_eski_yolda_ayni_dosya_varsa_idempotent(self):
		self._expected_target()
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]):
			retro_rename.run_job("JOB-RB-SAME", dry_run=0, batch_size=10)
		old_path = os.path.join(get_files_path(is_private=0), self.name)
		with open(old_path, "wb") as f:
			f.write(self.content)

		retro_rename.run_rollback("JOB-RB-SAME", "RB-SAME")
		rp = retro_rename.read_progress("RB-SAME")
		self.assertEqual((rp["state"], rp["errors"]), ("completed", 0))
		with open(old_path, "rb") as f:
			self.assertEqual(f.read(), self.content)
		self.assertFalse(os.path.isfile(self._new_path))

	def test_referans_provenance_olmayan_eski_satir_guvenle_reddedilir(self):
		hedef = self._expected_target()
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]):
			retro_rename.run_job("JOB-RB-LEGACY-REF", dry_run=0, batch_size=10)
		row_name = frappe.db.get_value("Media URL Redirect", {"source_url": self.url}, "name")
		frappe.db.set_value("Media URL Redirect", row_name, "ref_changes", "", update_modified=False)
		frappe.db.commit()

		retro_rename.run_rollback("JOB-RB-LEGACY-REF", "RB-LEGACY-REF")
		rp = retro_rename.read_progress("RB-LEGACY-REF")
		self.assertEqual((rp["state"], rp["errors"]), ("partial", 1))
		self.assertEqual(rp["skip_reasons"].get("ref_provenance_missing"), 1)
		self.assertEqual(frappe.db.count("File", {"file_url": hedef}), 3)
		self.assertTrue(os.path.isfile(self._new_path))
		self.assertTrue(frappe.db.exists("Media URL Redirect", row_name))

	def test_file_kimligi_olmayan_eski_satir_guvenle_reddedilir(self):
		hedef = self._expected_target()
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]):
			retro_rename.run_job("JOB-RB-LEGACY-FILE", dry_run=0, batch_size=10)
		row_name = frappe.db.get_value("Media URL Redirect", {"source_url": self.url}, "name")
		frappe.db.set_value("Media URL Redirect", row_name, "file_names", "", update_modified=False)
		frappe.db.commit()

		retro_rename.run_rollback("JOB-RB-LEGACY-FILE", "RB-LEGACY-FILE")
		rp = retro_rename.read_progress("RB-LEGACY-FILE")
		self.assertEqual((rp["state"], rp["errors"]), ("partial", 1))
		self.assertEqual(rp["skip_reasons"].get("file_provenance_missing"), 1)
		self.assertEqual(frappe.db.count("File", {"file_url": hedef}), 3)
		self.assertTrue(os.path.isfile(self._new_path))
		self.assertTrue(frappe.db.exists("Media URL Redirect", row_name))


class TestErrorRateStop(_RenameBase):
	def test_hata_orani_esigi_isi_batch_sinirinda_durdurur(self):
		base = get_files_path(is_private=0)
		ekler = []
		for i in range(2):
			ad = f"rr-err-{self.suffix}-{i}.jpg"
			ekler.append(_write_flat_public(ad, f"err-{self.suffix}-{i}".encode()))
			self.addCleanup(
				lambda a=ad: os.path.isfile(os.path.join(base, a)) and os.remove(os.path.join(base, a))
			)
		urls = [self.url, *ekler]
		with mock.patch.object(refs, "retarget", side_effect=RuntimeError("boom")):
			with mock.patch.object(retro_rename, "legacy_urls", return_value=urls):
				retro_rename.run_job("JOB-RATE", dry_run=0, batch_size=1)
		p = retro_rename.read_progress("JOB-RATE")
		self.assertEqual(p["state"], "partial")
		self.assertTrue(p["message"])
		self.assertEqual((p["total"], p["processed"], p["errors"]), (3, 1, 1))
		self.assertLess(p["processed"], p["total"])
		# İlk dosya geri alındı, kalan ikisine hiç dokunulmadı.
		for ad in [self.name, f"rr-err-{self.suffix}-0.jpg", f"rr-err-{self.suffix}-1.jpg"]:
			self.assertTrue(os.path.isfile(os.path.join(base, ad)))

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


class TestRunJobAndRollback(_RenameBase):
	def test_run_job_ilerleme_ve_rollback(self):
		hedef = self._expected_target()
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]):
			retro_rename.run_job("JOB-R", dry_run=0, batch_size=10)
		p = retro_rename.read_progress("JOB-R")
		self.assertEqual(p["state"], "completed")
		self.assertEqual((p["total"], p["processed"], p["renamed"], p["errors"]), (1, 1, 1, 0))
		self.assertEqual(frappe.db.get_value("Listing", self.listing, "primary_image"), hedef)
		self.assertIsNone(frappe.cache.get_value(retro_rename.ACTIVE_KEY))

		retro_rename.run_rollback("JOB-R", "RB-1")
		rp = retro_rename.read_progress("RB-1")
		self.assertEqual(rp["state"], "completed")
		self.assertTrue(os.path.isfile(os.path.join(get_files_path(is_private=0), self.name)))
		self.assertFalse(os.path.isfile(self._new_path))
		self.assertEqual(frappe.db.count("File", {"file_url": self.url}), 3)
		self.assertEqual(frappe.db.get_value("Listing", self.listing, "primary_image"), self.url)
		self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": self.url}))

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
		self.hedef = _hedef_url(self.content)
		self.hedef_path = os.path.join(get_files_path(is_private=0), *self.hedef[len("/files/") :].split("/"))
		frappe.db.commit()
		self.addCleanup(self._cleanup)

	def _cleanup(self):
		frappe.db.rollback()
		for n in self.files:
			if frappe.db.exists("File", n):
				frappe.delete_doc("File", n, force=True, ignore_permissions=True)
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

		retro_rename.run_rollback("JOB-DUP", "RB-DUP")
		rp = retro_rename.read_progress("RB-DUP")
		self.assertEqual((rp["state"], rp["errors"]), ("completed", 0))
		self.assertEqual(frappe.db.count("File", {"file_url": self.url_a}), 1)
		self.assertEqual(frappe.db.count("File", {"file_url": self.url_b}), 1)
		self.assertEqual(frappe.db.count("File", {"file_url": self.hedef}), 0)
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

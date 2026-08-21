"""Medya retro-rename (MOGEM-582 alt görevi) — eski tahmin edilebilir adların
içerik-adresli ada taşınması, 301 köprüsü ve geri alma.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_retro_rename
"""

from __future__ import annotations

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, get_files_path, now_datetime

from tradehub_core.media import retro_rename


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

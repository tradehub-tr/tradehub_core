"""Retro-rename admin uçları (System Manager).

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_admin_retro_rename
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_admin
from tradehub_core.media import retro_rename


class TestRetroRenameEndpoints(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(lambda: frappe.cache.delete_value(retro_rename.ACTIVE_KEY))

	def test_plan_ozet_doner(self):
		with mock.patch.object(
			retro_rename,
			"plan",
			return_value={
				"total": 3,
				"renamable": 3,
				"items": [1, 2, 3],
				"orphans": 0,
				"disk_missing": 0,
				"collisions": 0,
				"refs_exact": 0,
				"refs_readonly": 0,
				"refs_embedded": 0,
				"file_rows": 3,
				"truncated": False,
			},
		):
			out = media_admin.retro_rename_plan(limit=2)
		self.assertEqual(out["total"], 3)
		self.assertEqual(len(out["items"]), 2)

	def test_count_doner(self):
		with mock.patch.object(
			retro_rename, "legacy_urls", return_value=["/files/a.jpg", "/files/b.jpg", "/files/c.jpg"]
		):
			out = media_admin.retro_rename_count()
		self.assertEqual(out, {"total": 3})

	def test_start_enqueue_eder_ve_job_key_doner(self):
		with (
			mock.patch.object(media_admin.frappe, "enqueue") as enq,
			mock.patch.object(retro_rename, "legacy_urls", return_value=["/files/a.jpg"]),
		):
			out = media_admin.start_retro_rename(dry_run=1, batch_size=50)
		self.assertTrue(out["job_key"])
		self.assertEqual(out["total"], 1)
		kwargs = enq.call_args.kwargs
		self.assertEqual(kwargs["queue"], "long")
		self.assertEqual(kwargs["dry_run"], 1)

	def test_start_gecici_kilit_kurar(self):
		"""TOCTOU: enqueue mock'landığında bile kilit worker'a bağımlı olmadan Redis'te kalıcı olur.

		Endpoint `ACTIVE_KEY`'i `get_value(..., expires=True)` ile okuyor — bu yüzden
		süreç-içi önbelleğe hiç yazılmıyor ve testin kendi okuması (aşağıda,
		`expires=True` OLMADAN) da gerçek Redis değerini görür; `frappe.local.cache`
		elle temizlemeye gerek yok.
		"""
		with (
			mock.patch.object(media_admin.frappe, "enqueue"),
			mock.patch.object(retro_rename, "legacy_urls", return_value=["/files/a.jpg"]),
		):
			out = media_admin.start_retro_rename()
		self.assertEqual(frappe.cache.get_value(retro_rename.ACTIVE_KEY), out["job_key"])

	def test_start_batch_size_kirpilir(self):
		with (
			mock.patch.object(media_admin.frappe, "enqueue") as enq,
			mock.patch.object(retro_rename, "legacy_urls", return_value=["/files/a.jpg"]),
		):
			media_admin.start_retro_rename(batch_size=-5)
			self.assertEqual(enq.call_args.kwargs["batch_size"], 1)
			frappe.cache.delete_value(retro_rename.ACTIVE_KEY)
			media_admin.start_retro_rename(batch_size=99999)
			self.assertEqual(enq.call_args.kwargs["batch_size"], 2000)

	def test_aktif_is_varken_ikinci_baslatilamaz(self):
		frappe.cache.set_value(retro_rename.ACTIVE_KEY, "X", expires_in_sec=60)
		with self.assertRaises(frappe.ValidationError):
			media_admin.start_retro_rename()

	def test_status_bilinmeyen_not_found(self):
		self.assertEqual(media_admin.get_retro_rename_status("yok")["state"], "not_found")

	def test_rollback_enqueue(self):
		with mock.patch.object(media_admin.frappe, "enqueue") as enq:
			out = media_admin.rollback_retro_rename("JOB-X")
		self.assertTrue(out["job_key"])
		self.assertEqual(enq.call_args.kwargs["job_key"], "JOB-X")

	def test_rollback_gecici_kilit_kurar(self):
		"""TOCTOU: bkz. `test_start_gecici_kilit_kurar` — aynı `expires=True` gerekçesi."""
		with mock.patch.object(media_admin.frappe, "enqueue"):
			out = media_admin.rollback_retro_rename("JOB-X")
		self.assertEqual(frappe.cache.get_value(retro_rename.ACTIVE_KEY), out["job_key"])

	def test_yetkisiz_reddedilir(self):
		frappe.set_user("Guest")
		frappe.flags.in_test = False
		try:
			with self.assertRaises(frappe.PermissionError):
				media_admin.retro_rename_plan()
		finally:
			frappe.flags.in_test = True
			frappe.set_user("Administrator")

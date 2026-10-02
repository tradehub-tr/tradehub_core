"""Kare ürün görseli admin uçları (System Manager).

	docker exec istoc-dev-backend-1 bench --site istoc.localhost \\
		run-tests --module tradehub_core.tests.test_media_admin_square
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_admin
from tradehub_core.media import retro_rename


class TestSquareEndpoints(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")

	def test_yetkisiz(self):
		frappe.set_user("Guest")
		frappe.flags.in_test = False
		try:
			with self.assertRaises(frappe.PermissionError):
				media_admin.square_count()
		finally:
			frappe.flags.in_test = True
			frappe.set_user("Administrator")

	def test_start_kuyruga_atar_ve_kilidi_alir(self):
		with (
			patch("tradehub_core.media.kare.aday_urls", return_value=["/files/aa/x.jpg"]),
			patch("frappe.enqueue") as enq,
		):
			out = media_admin.start_square(dry_run=1)
		self.addCleanup(retro_rename.release_active, out["job_key"])
		self.assertEqual(enq.call_args.args[0], "tradehub_core.media.kare.run_job")
		self.assertEqual(enq.call_args.kwargs["dry_run"], 1)
		self.assertEqual(out["total"], 1)

	def test_aday_yoksa_hata(self):
		with patch("tradehub_core.media.kare.aday_urls", return_value=[]):
			with self.assertRaises(frappe.ValidationError):
				media_admin.start_square()

	def test_rollback_kuyruga_atar(self):
		with patch("frappe.enqueue") as enq:
			out = media_admin.rollback_square("kare-abc")
		self.addCleanup(retro_rename.release_active, out["job_key"])
		self.assertEqual(enq.call_args.args[0], "tradehub_core.media.kare.run_rollback")
		self.assertEqual(enq.call_args.kwargs["job_key"], "kare-abc")

	def test_rollback_yalniz_kare_isi(self):
		with self.assertRaises(frappe.ValidationError):
			media_admin.rollback_square("retro123")

	def test_retro_rollback_kare_isini_reddeder(self):
		with self.assertRaises(frappe.ValidationError):
			media_admin.rollback_retro_rename("kare-abc")

	def test_retro_gecmisi_kare_islerini_gostermez(self):
		sfx = frappe.generate_hash(length=8)
		ortak = {
			"doctype": "Media URL Redirect",
			"expires_at": frappe.utils.add_days(frappe.utils.now_datetime(), 1),
			"file_rows": 0,
			"file_names": "[]",
			"ref_changes": "[]",
		}
		kare_row = frappe.get_doc(
			{
				**ortak,
				"source_url": f"/files/kare-hist-{sfx}.jpg",
				"target_url": f"/files/kare-hist-{sfx}.webp",
				"job_key": f"kare-hist-{sfx}",
			}
		).insert(ignore_permissions=True)
		retro_row = frappe.get_doc(
			{
				**ortak,
				"source_url": f"/files/retro-hist-{sfx}.jpg",
				"target_url": f"/files/retro-hist-{sfx}.webp",
				"job_key": f"retrohist{sfx}",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.db.delete("Media URL Redirect", {"name": ["in", [kare_row.name, retro_row.name]]})
		)
		keys = {j["job_key"] for j in media_admin.retro_rename_history()["jobs"]}
		self.assertNotIn(f"kare-hist-{sfx}", keys)
		self.assertIn(f"retrohist{sfx}", keys)

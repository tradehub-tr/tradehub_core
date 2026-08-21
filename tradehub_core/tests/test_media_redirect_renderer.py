"""301 köprüsü: eski /files/<ad> → yeni adres; süre dolunca 404.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_redirect_renderer
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from tradehub_core.media import retro_rename
from tradehub_core.media.redirect_renderer import MediaRedirectRenderer


class TestMediaRedirectRenderer(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.old = f"/files/rr-301-{frappe.generate_hash(length=8)}.jpg"
		self.new = "/files/ab/" + "d" * 32 + ".jpg"
		self.addCleanup(lambda: frappe.db.delete("Media URL Redirect", {"source_url": self.old}))

	def _row(self, days: int) -> None:
		frappe.get_doc(
			{
				"doctype": "Media URL Redirect",
				"source_url": self.old,
				"target_url": self.new,
				"job_key": "T301",
				"expires_at": add_days(now_datetime(), days),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	def test_eski_adres_301(self):
		self._row(30)
		r = MediaRedirectRenderer(self.old.lstrip("/"))
		self.assertTrue(r.can_render())
		resp = r.render()
		self.assertEqual(resp.status_code, 301)
		self.assertEqual(resp.headers["Location"], self.new)
		self.assertIn("no-store", resp.headers["Cache-Control"])

	def test_suresi_dolmus_404(self):
		self._row(-1)
		self.assertFalse(MediaRedirectRenderer(self.old.lstrip("/")).can_render())

	def test_bilinmeyen_ve_files_disi(self):
		self.assertFalse(MediaRedirectRenderer("files/rr-yok.jpg").can_render())
		self.assertFalse(MediaRedirectRenderer("urunler/x").can_render())

	def test_hook_kayitli(self):
		self.assertIn(
			"tradehub_core.media.redirect_renderer.MediaRedirectRenderer", frappe.get_hooks("page_renderer")
		)
		self.assertIn(
			"tradehub_core.media.retro_rename.purge_expired_redirects",
			frappe.get_hooks("scheduler_events")["daily"],
		)

	def test_purge_expired(self):
		self._row(-1)
		silinen = retro_rename.purge_expired_redirects()
		self.assertGreaterEqual(silinen, 1)
		self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": self.old}))

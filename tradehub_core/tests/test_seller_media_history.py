"""Faz 9 / T-093 — satıcı medya geçmişi ve kiracı izolasyonu.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_seller_media_history
"""

from __future__ import annotations

import hashlib

import frappe

from tradehub_core.api import seller_media
from tradehub_core.media import audit
from tradehub_core.tests.test_seller_media_browse import SellerBrowseTestBase


class SellerMediaHistoryTests(SellerBrowseTestBase):
	@staticmethod
	def _delete_audit(name: str) -> None:
		"""Değişmez ADL controller'ını atlayarak yalnız test satırını temizle."""
		frappe.db.delete("Authorization Decision Log", {"name": name})
		frappe.db.commit()

	def _asset(self, *, store: str, file_url: str, tag: str) -> str:
		file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
		doc = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": "product.image",
				"media_type": "image",
				"state": "ready",
				"owner_seller": store,
				"source_file": file_name,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(self._delete_and_commit, "Media Asset", doc.name)

		version_hash = hashlib.sha256(f"history-version:{tag}:{doc.name}".encode()).hexdigest()
		version = frappe.get_doc(
			{
				"doctype": "Media Version",
				"asset": doc.name,
				"version_hash": version_hash,
				"source_hash": hashlib.sha256(f"history-source:{tag}".encode()).hexdigest(),
				"width": 640,
				"height": 480,
				"engine_version": "history-test",
				"is_active": 0,
			}
		)
		version.flags.skip_source_enrichment = True
		version.insert(ignore_permissions=True)
		self.addCleanup(self._delete_and_commit, "Media Version", version.name)

		job = frappe.get_doc(
			{
				"doctype": "Media Processing Job",
				"asset": doc.name,
				"job_type": "normalize",
				"queue": "media-image-live",
				"status": "success",
				"attempt": 1,
				"idempotency_key": f"history:{tag}:{doc.name}",
				"duration_ms": 12,
				"error_trace": f"SECRET-TRACE-{tag}",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(self._delete_and_commit, "Media Processing Job", job.name)
		frappe.db.commit()
		return doc.name

	def _event(self, *, store: str, file_url: str, tag: str) -> str:
		name = audit.log_media_event(
			action=audit.ACTION_UPLOAD,
			file_url=file_url,
			tenant=store,
			context={"private_probe": f"SECRET-CONTEXT-{tag}"},
		)
		self.assertTrue(name)
		self.addCleanup(self._delete_audit, str(name))
		return str(name)

	def test_history_is_scoped_twice_and_sensitive_fields_are_absent(self):
		"""Aynı File'a bağlı yabancı Asset/olay bile A'nın yanıtına giremez."""
		own_asset = self._asset(store=self.a.store, file_url=self.a.public_url, tag="own")
		foreign_asset = self._asset(store=self.b.store, file_url=self.a.public_url, tag="foreign")
		frappe.db.set_value(
			"Media Asset",
			own_asset,
			{
				"state": "rejected",
				"rejection_code": "cover_video_too_long",
				"rejection_note": "Kapak videosu 60 saniyeden uzun.",
			},
		)
		frappe.db.commit()
		own_event = self._event(store=self.a.store, file_url=self.a.public_url, tag="own")
		foreign_event = self._event(store=self.b.store, file_url=self.a.public_url, tag="foreign")

		self._as_seller(self.a)
		result = seller_media.get_my_media_history(f"{self.a.public_url}?width=640")

		self.assertEqual(result["file_url"], self.a.public_url)
		self.assertEqual({row["name"] for row in result["assets"]}, {own_asset})
		self.assertEqual(result["assets"][0]["rejection_code"], "cover_video_too_long")
		self.assertIn("60", result["assets"][0]["rejection_note"])
		self.assertNotIn(foreign_asset, {row["name"] for row in result["assets"]})
		self.assertEqual({row["asset"] for row in result["versions"]}, {own_asset})
		self.assertEqual({row["asset"] for row in result["jobs"]}, {own_asset})
		self.assertEqual({row["name"] for row in result["audit"]}, {own_event})
		self.assertNotIn(foreign_event, {row["name"] for row in result["audit"]})
		self.assertNotIn("error_trace", result["jobs"][0])
		self.assertNotIn("context", result["audit"][0])
		self.assertNotIn("ip_address", result["audit"][0])
		self.assertTrue(result["versions"][0]["created_at"].startswith("20"))
		self.assertEqual(result["totals"], {"assets": 1, "versions": 1, "jobs": 1, "audit": 1})

	def test_foreign_file_url_is_rejected_before_history_queries(self):
		self._asset(store=self.b.store, file_url=self.b.public_url, tag="foreign-url")
		self._as_seller(self.a)
		# Varlık keşfini önlemek için yabancı adres "yetkin yok" değil "yok"
		# olarak görünür; iki hata türü arasında ayrım sızdırılmaz.
		with self.assertRaises(frappe.DoesNotExistError):
			seller_media.get_my_media_history(self.b.public_url)

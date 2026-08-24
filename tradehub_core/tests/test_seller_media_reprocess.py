"""Faz 9 / T-094 — 500 varlıklı satıcı toplu yeniden işleme.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_seller_media_reprocess
"""

from __future__ import annotations

import unittest
from unittest import mock

import frappe

from tradehub_core.api import seller_media
from tradehub_core.media import ownership, pipeline_bridge


class SellerMediaReprocessTests(unittest.TestCase):
	def setUp(self) -> None:
		self.tokens: list[str] = []

	def tearDown(self) -> None:
		for token in self.tokens:
			frappe.cache().delete_value(seller_media._seller_reprocess_meta_key(token))

	def _token(self, value: str) -> str:
		self.tokens.append(value)
		return value

	def test_500_asset_tek_kosumda_kayipsiz_planlanir(self):
		urls = [f"/files/bulk-{i}.webp" for i in range(500)]
		files = [{"name": f"FILE-{i}", "file_url": url} for i, url in enumerate(urls)]
		assets = [{"name": f"ASSET-{i}", "source_file": f"FILE-{i}"} for i in range(500)]
		token = self._token("seller-bulk-500")

		def get_all(doctype, **_kwargs):
			return files if doctype == "File" else assets if doctype == "Media Asset" else []

		with (
			mock.patch.object(seller_media, "_store", return_value="STORE-A"),
			mock.patch.object(seller_media.ownership, "owned_urls", return_value=set(urls)) as owned,
			mock.patch.object(seller_media.frappe, "get_all", side_effect=get_all),
			mock.patch.object(
				seller_media.pipeline_bridge,
				"enqueue_policy_reprocess",
				return_value={"token": token, "queued": 500, "queue": "media-image-bulk"},
			) as enqueue,
			mock.patch.object(
				seller_media.pipeline_bridge,
				"policy_reprocess_status",
				return_value={
					"token": token,
					"status": "queued",
					"total": 500,
					"processed": 0,
					"failed": 0,
				},
			),
		):
			result = seller_media.start_media_reprocess(urls)

		owned.assert_called_once_with("STORE-A", urls)
		planned = enqueue.call_args.args[0]
		self.assertEqual(len(planned), 500)
		self.assertEqual(set(planned), {f"ASSET-{i}" for i in range(500)})
		self.assertEqual(enqueue.call_args.kwargs["limit"], 500)
		self.assertEqual(result["queued"], 500)
		self.assertEqual(result["total"], 500)
		self.assertEqual(result["processed"], 0)

	def test_hazirlik_ve_worker_hatasi_tek_kismi_raporda_birlesir(self):
		token = self._token("seller-bulk-partial")
		meta = {
			"store": "STORE-A",
			"requested": 3,
			"skipped": 0,
			"preflight_failures": [
				{
					"file_url": "/files/no-asset.webp",
					"error_code": "image_asset_missing",
					"error": "asset missing",
				}
			],
			"asset_to_url": {
				"ASSET-1": "/files/ok.webp",
				"ASSET-2": "/files/failed.webp",
			},
		}
		seller_media._save_seller_reprocess_meta(token, meta)
		with (
			mock.patch.object(seller_media, "_store", return_value="STORE-A"),
			mock.patch.object(
				seller_media.pipeline_bridge,
				"policy_reprocess_status",
				return_value={
					"status": "completed",
					"total": 2,
					"processed": 2,
					"failed": 1,
					"failures": [{"asset": "ASSET-2", "error_code": "ValueError"}],
				},
			),
		):
			result = seller_media.get_media_reprocess_status(token)

		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["total"], 3)
		self.assertEqual(result["processed"], 3)
		self.assertEqual(result["succeeded"], 1)
		self.assertEqual(result["failed"], 2)
		self.assertEqual(
			{row["file_url"] for row in result["failures"]},
			{"/files/no-asset.webp", "/files/failed.webp"},
		)
		self.assertNotIn("ValueError", str(result["failures"]))

	def test_token_baska_magazaya_isin_varligini_sizdirmaz(self):
		token = self._token("seller-bulk-private")
		seller_media._save_seller_reprocess_meta(
			token,
			{
				"store": "STORE-B",
				"requested": 1,
				"skipped": 0,
				"preflight_failures": [],
				"asset_to_url": {},
			},
		)
		with (
			mock.patch.object(seller_media, "_store", return_value="STORE-A"),
			mock.patch.object(seller_media.pipeline_bridge, "policy_reprocess_status") as status,
			self.assertRaises(frappe.DoesNotExistError),
		):
			seller_media.get_media_reprocess_status(token)
		status.assert_not_called()

	def test_toplu_sahiplik_tek_file_sorgusu_ve_tek_kullanim_kumesiyle_cozulur(self):
		with (
			mock.patch.object(ownership, "users_of", return_value=("seller@test.local",)),
			mock.patch.object(ownership, "used_urls", return_value={"/files/used.webp"}) as used,
			mock.patch.object(
				ownership.frappe.db,
				"get_all",
				return_value=[{"file_url": "/files/uploaded.webp"}],
			) as get_all,
		):
			result = ownership.owned_urls(
				"STORE-A",
				["/files/uploaded.webp", "/files/used.webp", "/files/foreign.webp"],
			)

		self.assertEqual(result, {"/files/uploaded.webp", "/files/used.webp"})
		get_all.assert_called_once()
		used.assert_called_once_with("STORE-A")


class PolicyFailureLedgerTests(unittest.TestCase):
	def test_worker_hatasi_asset_kimligi_ve_makine_koduyla_sayaca_gider(self):
		with (
			mock.patch.object(pipeline_bridge.frappe, "cache") as cache,
			mock.patch.object(pipeline_bridge, "_set_bulk_status"),
			mock.patch.object(pipeline_bridge, "_run_policy_reprocess_asset", return_value=False),
			mock.patch.object(pipeline_bridge, "_update_bulk_after_item") as update,
		):
			cache.return_value.get_value.return_value = None
			pipeline_bridge._run_policy_reprocess_item("TOKEN", "ASSET-X")

		update.assert_called_once_with(
			"TOKEN",
			failed=True,
			asset_name="ASSET-X",
			error_code="reprocess_failed",
		)


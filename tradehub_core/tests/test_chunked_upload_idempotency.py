# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-081 — gerçek Frappe parçalı yüklemede idempotency ve oturum snapshot'ı.

Saf ``pipeline/api/upload.py`` testleri üç kapının algoritmasını ölçüyor; bu
dosya çalışan ``seller_media`` whitelist bağını ölçer. Kritik senaryo şudur:
sunucu File kaydını açar, HTTP yanıtı kaybolur, istemci aynı upload_id ve
Idempotency-Key ile tekrar finalize eder. İkinci çağrı aynı yanıtı döndürmeli
ve ikinci File kaydı açmamalıdır.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
from unittest import mock

import frappe

from tradehub_core import hooks
from tradehub_core.api import seller_media
from tradehub_core.media import chunked, upload_policy
from tradehub_core.tests.test_media_dedup_endpoint import _DedupUcuTesti


def _png(width: int = 1200, height: int = 1200) -> bytes:
	from PIL import Image

	buf = io.BytesIO()
	Image.new("RGB", (width, height), (47, 129, 211)).save(buf, "PNG")
	return buf.getvalue()


class TestChunkedUploadIdempotency(_DedupUcuTesti):
	def setUp(self) -> None:
		super().setUp()
		self.content = _png()
		self.sha256 = hashlib.sha256(self.content).hexdigest()
		self.key = f"faz8-{self.suffix}-upload-key"
		self.upload_id = ""
		self.result_url = ""
		self.addCleanup(self._cleanup_material)

	def _cleanup_material(self) -> None:
		frappe.set_user("Administrator")
		if self.upload_id:
			try:
				chunked.cleanup_session(self.upload_id)
			except Exception:
				pass
		if self.result_url:
			for file_name in frappe.get_all("File", filters={"file_url": self.result_url}, pluck="name"):
				for asset in frappe.get_all("Media Asset", filters={"source_file": file_name}, pluck="name"):
					self._drop("Media Asset", asset)
				self._drop("File", file_name)
		yol = chunked._finalized_path(self.tenant_b, self.key)  # noqa: SLF001 — fixture temizliği
		if yol and os.path.isfile(yol):
			os.unlink(yol)

	def _begin(self, *, declared_hash: str | None = None, key: str | None = None) -> dict:
		frappe.set_user(self.b_owner)
		sonuc = seller_media.upload_begin(
			file_name=f"faz8-{self.suffix}.png",
			total_bytes=len(self.content),
			slot="product.image",
			content_sha256=self.sha256 if declared_hash is None else declared_hash,
			idempotency_key=self.key if key is None else key,
		)
		self.upload_id = sonuc.get("upload_id") or self.upload_id
		return sonuc

	def _send_and_finish(self) -> dict:
		frappe.set_user(self.b_owner)
		seller_media.upload_chunk(
			self.upload_id,
			0,
			base64.b64encode(self.content).decode("ascii"),
		)
		with mock.patch("tradehub_core.media.av.enqueue_scan"):
			sonuc = seller_media.upload_finish(
				self.upload_id,
				idempotency_key=self.key,
				client_report={"width": 1, "height": 1, "ignored": "policyye-girmez"},
			)
		self.result_url = sonuc["file_url"]
		return sonuc

	def test_begin_policy_quota_expiry_progress_ve_scheduler_baglantisi(self) -> None:
		sonuc = self._begin()

		self.assertEqual(sonuc["idempotency_key"], self.key)
		self.assertEqual(sonuc["content_sha256"], self.sha256)
		self.assertEqual(sonuc["slot"], "product.image")
		self.assertEqual(sonuc["policy_snapshot"]["slot_key"], "product.image")
		self.assertEqual(len(sonuc["policy_snapshot"]["policy_sha256"]), 64)
		self.assertIn("quota_remaining", sonuc)
		self.assertTrue(sonuc["expires_at"])
		self.assertTrue(sonuc["upload_url"].endswith("upload_chunk"))

		durum = seller_media.upload_status(self.upload_id)
		self.assertEqual(durum["received_count"], 0)
		self.assertEqual(durum["percent"], 0)
		self.assertIn("tradehub_core.media.chunked.cleanup", hooks.scheduler_events["daily"])

	def test_ayni_finalize_tam_ayni_sonucu_dondurur_ve_tek_file_birakir(self) -> None:
		self._begin()
		birinci = self._send_and_finish()
		ikinci = seller_media.upload_finish(self.upload_id, idempotency_key=self.key)

		self.assertEqual(ikinci["file_url"], birinci["file_url"])
		self.assertEqual(ikinci["content_sha256"], self.sha256)
		self.assertTrue(ikinci["idempotent_replay"])
		self.assertEqual(
			frappe.db.count("File", {"file_url": birinci["file_url"]}),
			1,
			"aynı finalize ikinci File satırı açtı",
		)

	def test_ayni_anahtarla_yeni_begin_onceki_tam_sonucu_dondurur(self) -> None:
		self._begin()
		birinci = self._send_and_finish()
		tekrar = self._begin()

		self.assertTrue(tekrar["completed"])
		self.assertTrue(tekrar["idempotent_replay"])
		self.assertEqual(tekrar["result"]["file_url"], birinci["file_url"])
		self.assertEqual(tekrar["upload_id"], "")

	def test_ilan_edilen_hash_gercek_baytla_uyusmazsa_kayit_acilmaz(self) -> None:
		self._begin(declared_hash="0" * 64)
		frappe.set_user(self.b_owner)
		seller_media.upload_chunk(self.upload_id, 0, base64.b64encode(self.content).decode("ascii"))
		with self.assertRaises(upload_policy.UploadRejected) as ctx:
			seller_media.upload_finish(self.upload_id, idempotency_key=self.key)
		self.assertIn("[upload_content_hash_mismatch]", str(ctx.exception))
		self.assertIsNone(chunked.finalized_result(self.key, self.tenant_b))

	def test_anahtar_oturumla_eslesmezse_reddedilir(self) -> None:
		self._begin()
		with self.assertRaises(upload_policy.UploadRejected) as ctx:
			seller_media.upload_finish(self.upload_id, idempotency_key="different-safe-key")
		self.assertIn("[upload_idempotency_conflict]", str(ctx.exception))

	def test_baska_magaza_ayni_anahtarla_sonucu_goremez(self) -> None:
		self._begin()
		self._send_and_finish()
		frappe.set_user(self.a_owner)
		self.assertIsNone(chunked.finalized_result(self.key, self.tenant_a))
		with self.assertRaises(upload_policy.UploadRejected) as ctx:
			seller_media.upload_finish(self.upload_id, idempotency_key=self.key)
		self.assertIn("[upload_session_unknown]", str(ctx.exception))


if __name__ == "__main__":
	import unittest

	unittest.main()

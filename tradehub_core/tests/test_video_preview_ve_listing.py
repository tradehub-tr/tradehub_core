# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""W8 — video hattının kalanları (rapor 84 §8'in kapanan boşlukları).

  1. Hareketli önizleme klibi üretim yolunda: `pipeline_bridge.
     _produce_video_preview` transcode zincirine bağlandı; klip kanonik
     adrese (`preview-{w}.mp4`) yazılır, `Media Rendition(profile=preview)`
     satırı açılır, 1 MB görev kapısından düşen klip KAYDA GEÇMEZ.
  2. Manifest `video` bloğu `previewSrc` taşır.
  3. `get_listing_detail` video türev alanlarını (`videoPoster`/`videoHlsSrc`/
     `videoPreviewSrc`/`videoSrc`) manifest ALT KATMANINDAN
     (`media_manifest.video_bloklari`) basar — mantık kopyalanmadı.

Koşum (DB'li sınıflar site ister):

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_video_preview_ve_listing
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from tradehub_core.media.pipeline.video import poster as video_poster
from tradehub_core.media.pipeline.video import probe as P
from tradehub_core.media.pipeline.video import transcode as T

try:
	import frappe

	from tradehub_core.api import listing as listing_api
	from tradehub_core.api import media_manifest
	from tradehub_core.media import pipeline_bridge
	from tradehub_core.tests.test_video_servis import (
		VIDEO_SLOT,
		TestManifestVideo,
		_BayrakliVideoTest,
		_ornek_video_baytlari,
		_sil,
	)
except Exception:  # pragma: no cover — DB'siz koşumda modül atlanır
	frappe = None

FFMPEG = T.ffmpeg_available() and P.ffprobe_available()


if frappe is not None:

	@unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe yok — konteynerde calistir")
	class TestPreviewUretimi(_BayrakliVideoTest):
		"""Klip, worker zincirinde poster gibi bir zenginleştirme türevidir."""

		def _temizle(self, asset_name: str) -> None:
			import glob
			import shutil

			for rend in frappe.get_all("Media Rendition", filters={"asset": asset_name}, pluck="name"):
				_sil("Media Rendition", rend)
			for job in frappe.get_all("Media Processing Job", filters={"asset": asset_name}, pluck="name"):
				_sil("Media Processing Job", job)
			for surum in frappe.get_all("Media Version", filters={"asset": asset_name}, pluck="name"):
				_sil("Media Version", surum)
			_sil("Media Asset", asset_name)
			for kok in glob.glob(frappe.get_site_path("public", "files", "media", asset_name)):
				shutil.rmtree(kok, ignore_errors=True)

		def test_worker_preview_turevini_uretir_ve_kaydeder(self):
			"""PASSTHROUGH kaynak bile klip alır (klip kaynaktan üretilir)."""
			from tradehub_core.media.pipeline.core import dedup

			doc = self._dosya_ekle(
				"w8-preview.mp4",
				_ornek_video_baytlari(faststart=True, etiket=frappe.generate_hash(length=10)),
				attached_to_doctype="Listing",
				attached_to_field="video_url",
			)
			self._hatti_ac()
			pipeline_bridge._run_video_job(doc.file_url)
			parmak = pipeline_bridge.content_fingerprint(doc)
			asset_name = frappe.db.get_value(
				"Media Asset", {"content_sha256": parmak, "slot_key": VIDEO_SLOT}, "name"
			)
			self.assertTrue(asset_name, "Media Asset açılmadı")
			self.addCleanup(lambda: self._temizle(asset_name))

			turevler = {
				t.profile: t
				for t in frappe.get_all(
					"Media Rendition",
					filters={"asset": asset_name},
					fields=["profile", "width", "height", "format", "file_url", "bytes"],
				)
			}
			self.assertIn("preview", turevler, "önizleme klibi kayda geçmeli")
			klip = turevler["preview"]
			self.assertEqual(klip.format, "mp4")

			cozulen = dedup.parse_rendition_path(klip.file_url)
			self.assertIsNotNone(cozulen, f"kanonik adres değil: {klip.file_url}")
			self.assertEqual(cozulen["profile"], "preview")
			self.assertEqual(cozulen["asset"], asset_name)

			yol = frappe.get_site_path("public", klip.file_url.lstrip("/"))
			self.assertTrue(os.path.exists(yol), "klip diske yazılmadı")
			boyut = os.path.getsize(yol)
			self.assertEqual(boyut, klip.bytes)

			spec = video_poster.PreviewClipSpec.from_table()
			self.assertLessEqual(boyut, spec.max_bytes, "1 MB görev kapısı")

			kunye = P.probe(yol)
			self.assertTrue(kunye.measured)
			# Kaynak 2 sn → klip videonun tamamı; üst sınır merdivenin en uzunu.
			self.assertLessEqual(kunye.duration_s, max(spec.duration_ladder) + 0.5)
			self.assertGreater(kunye.duration_s, 0.0)
			self.assertIsNone(
				frappe.db.get_value("Media Rendition", {"asset": asset_name, "profile": "h264"}),
				"ön koşul: PASSTHROUGH kaynak h264 üretmez (klip bundan bağımsız)",
			)

		def _sahte_asset_dizinini_temizle(self) -> None:
			import shutil

			shutil.rmtree(
				frappe.get_site_path("public", "files", "media", "w8testasset"),
				ignore_errors=True,
			)

		def test_gorev_kapisindan_dusen_klip_kayda_gecmez(self):
			"""Merdiven tükenip 1 MB aşılırsa: dosya silinir, satır açılmaz."""
			self.addCleanup(self._sahte_asset_dizinini_temizle)
			dusen = video_poster.PreviewClipResult(
				path="/tmp/yok.mp4",
				start_s=0.0,
				duration_s=3.0,
				size_bytes=2_000_000,
				crf=36,
				within_task_gate=False,
				within_policy_gate=False,
			)
			with (
				mock.patch.object(video_poster, "make_preview_clip", return_value=dusen),
				mock.patch.object(pipeline_bridge, "_insert_video_rendition") as insert_m,
			):
				sonuc = pipeline_bridge._produce_video_preview(
					"/tmp/kaynak.mp4", None, "w8testasset", "0" * 64
				)
			self.assertIsNone(sonuc)
			insert_m.assert_not_called()

		def test_klip_hatasi_teslimi_dusurmez(self):
			"""Poster sözleşmesinin aynısı: best-effort, istisna sızmaz."""
			self.addCleanup(self._sahte_asset_dizinini_temizle)
			with mock.patch.object(
				video_poster, "make_preview_clip", side_effect=RuntimeError("ffmpeg dustu")
			):
				sonuc = pipeline_bridge._produce_video_preview(
					"/tmp/kaynak.mp4", None, "w8testasset", "0" * 64
				)
			self.assertIsNone(sonuc)

	class _PreviewFixtureMixin:
		"""W7 fixture'ına (`TestManifestVideo._fixture_kur`) klip satırı ekler."""

		def _preview_ekle(self, fx: dict) -> str:
			url = f"{fx['kok']}/preview-854.mp4"
			rend = frappe.get_doc(
				{
					"doctype": "Media Rendition",
					"asset": fx["asset"],
					"profile": "preview",
					"width": 854,
					"height": 480,
					"format": "mp4",
					"file_url": url,
					"bytes": 400_000,
					"benefit_gate_passed": 1,
				}
			).insert(ignore_permissions=True)
			self.addCleanup(lambda ad=rend.name: _sil("Media Rendition", ad))
			frappe.db.commit()  # nosemgrep — manifest frappe.db.sql ile okuyor
			return url

	class TestManifestPreviewSrc(_PreviewFixtureMixin, TestManifestVideo):
		"""`video` bloğu `previewSrc` taşır. Fixture kurulumunu W7 sınıfından
		MİRAS alır (aynı görünür ilan + Media zinciri); W7 testleri de bu
		sınıf üzerinde ikinci kez koşar — regresyonu bedavaya ölçer."""

		def test_preview_turevi_varsa_previewSrc_dolu(self):
			self._ayarla(media_pipeline_enabled=1, manifest_api_enabled=1)
			fx = self._fixture_kur()
			url = self._preview_ekle(fx)
			video = media_manifest.get_manifest(self.ilan["name"], slot=VIDEO_SLOT)["video"]
			self.assertEqual(video["previewSrc"], url)

		def test_preview_turevi_yoksa_previewSrc_bos(self):
			"""Eski varlıklar/kapıdan düşen klip: alan var, değer boş."""
			self._ayarla(media_pipeline_enabled=1, manifest_api_enabled=1)
			self._fixture_kur()
			video = media_manifest.get_manifest(self.ilan["name"], slot=VIDEO_SLOT)["video"]
			self.assertIn("previewSrc", video)
			self.assertEqual(video["previewSrc"], "")

	class TestListingDetailVideoAlanlari(_PreviewFixtureMixin, TestManifestVideo):
		"""`get_listing_detail` manifest alt katmanının alanlarını basar."""

		def _detay(self) -> dict:
			# Yanıt önbelleği ilan×dil anahtarlı — bayrak değişimini görsün.
			frappe.cache.delete_value(f"{listing_api._LISTING_DETAIL_CACHE_PREFIX}{self.ilan['name']}:tr")
			return listing_api.get_listing_detail(self.ilan["name"])["data"]

		def test_turevler_varken_video_alanlari_dolu(self):
			self._ayarla(media_pipeline_enabled=1, manifest_api_enabled=1)
			fx = self._fixture_kur()
			url = self._preview_ekle(fx)
			data = self._detay()
			self.assertEqual(data["videoUrl"], self.VIDEO_URL, "ham alan DEĞİŞMEZ")
			self.assertEqual(data["videoPoster"], fx["turevler"]["poster"])
			self.assertEqual(data["videoHlsSrc"], fx["turevler"]["hls"])
			self.assertEqual(data["videoSrc"], fx["turevler"]["h264"])
			self.assertEqual(data["videoPreviewSrc"], url)

		def test_bayrak_kapaliyken_alanlar_None_videoUrl_ham(self):
			self._ayarla(media_pipeline_enabled=0, manifest_api_enabled=0)
			self._fixture_kur()
			data = self._detay()
			self.assertEqual(data["videoUrl"], self.VIDEO_URL)
			self.assertIsNone(data["videoPoster"])
			self.assertIsNone(data["videoHlsSrc"])
			self.assertIsNone(data["videoPreviewSrc"])
			self.assertIsNone(data["videoSrc"])

		def test_manifest_dusse_bile_detay_ucu_dusmez(self):
			self._ayarla(media_pipeline_enabled=1, manifest_api_enabled=1)
			self._fixture_kur()
			with mock.patch.object(
				media_manifest, "video_bloklari", side_effect=RuntimeError("patladi")
			):
				data = self._detay()
			self.assertEqual(data["videoUrl"], self.VIDEO_URL)
			self.assertIsNone(data["videoPoster"])

if __name__ == "__main__":
	unittest.main(verbosity=2)

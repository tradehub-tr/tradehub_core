# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""MOGEM-569 — yükleme sonrası video doğrulama sözleşmesi.

Bu testler ffmpeg/ffprobe çalıştırmaz; worker'ın aldığı ölçülmüş ``VideoFacts``
künyesini kullanır. Böylece slot süre/geometri kapısı ile codec/motor kararı
aynı sonuçta birleşiyor mu deterministik olarak sınanır.

    python3 -m unittest tradehub_core.tests.test_media_video_validation -v
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from tradehub_core.media.pipeline.video import validation
from tradehub_core.media.pipeline.video.decision import ACTION_TRANSCODE
from tradehub_core.media.pipeline.video.probe import VideoFacts


def _video(**degisiklikler) -> VideoFacts:
	"""Motor ve iki video slotu için geçerli, ölçülmüş temel künye."""
	temel = VideoFacts(
		path="/tmp/upload.mp4",
		size_bytes=2 * 1024 * 1024,
		measured=True,
		has_video=True,
		coded_width=1280,
		coded_height=720,
		width=1280,
		height=720,
		duration_s=30.0,
		video_duration_s=30.0,
		fps=30.0,
		video_codec="h264",
		video_profile="High",
		pix_fmt="yuv420p",
		video_bitrate_bps=1_500_000,
		format_bitrate_bps=1_600_000,
		container="mov,mp4,m4a,3gp,3g2,mj2",
		container_family="mp4",
		has_audio=True,
		audio_codec="aac",
		audio_bitrate_bps=96_000,
		audio_channels=2,
		nb_streams=2,
	)
	return replace(temel, **degisiklikler)


class VideoUploadValidationTests(unittest.TestCase):
	def test_gecerli_kapak_videosu_kabul_edilir(self):
		sonuc = validation.validate("company.cover_video", _video())
		self.assertFalse(sonuc.rejected)
		self.assertEqual(sonuc.code, "")
		self.assertEqual(sonuc.stage, "")

	def test_kapak_videosu_60_saniye_ustunde_kodlu_reddedilir(self):
		sonuc = validation.validate(
			"company.cover_video",
			_video(duration_s=61.0, video_duration_s=61.0),
		)
		self.assertTrue(sonuc.rejected)
		self.assertEqual(sonuc.stage, "slot")
		self.assertEqual(sonuc.code, "cover_video_too_long")
		self.assertIn("60", sonuc.reason)

	def test_kapak_videosu_6_saniye_altinda_kodlu_reddedilir(self):
		sonuc = validation.validate(
			"company.cover_video",
			_video(duration_s=5.0, video_duration_s=5.0),
		)
		self.assertTrue(sonuc.rejected)
		self.assertEqual(sonuc.code, "cover_video_too_short")
		self.assertIn("6", sonuc.reason)

	def test_kapak_cozunurluk_alt_siniri_uygulanir(self):
		sonuc = validation.validate(
			"company.cover_video",
			_video(coded_width=640, coded_height=360, width=640, height=360),
		)
		self.assertTrue(sonuc.rejected)
		self.assertEqual(sonuc.code, "cover_video_resolution_too_low")
		self.assertIn("1280", sonuc.reason)

	def test_kapak_slot_bayt_tavani_savunma_derinliginde_yine_uygulanir(self):
		sonuc = validation.validate(
			"company.cover_video",
			_video(size_bytes=80 * 1024 * 1024 + 1),
		)
		self.assertTrue(sonuc.rejected)
		self.assertEqual(sonuc.code, "cover_video_too_large")

	def test_urun_videosunda_33_saniye_uyaridir_ret_degil(self):
		sonuc = validation.validate(
			"product.video",
			_video(duration_s=40.0, video_duration_s=40.0),
		)
		self.assertFalse(sonuc.rejected)
		self.assertIn("upload_duration_too_long", sonuc.warning_codes)

	def test_teslim_edilemeyen_codec_reddedilmez_transcode_edilir(self):
		sonuc = validation.validate("company.cover_video", _video(video_codec="hevc"))
		self.assertFalse(sonuc.rejected)
		self.assertEqual(sonuc.processing.action, ACTION_TRANSCODE)
		self.assertEqual(sonuc.processing.code, "video_codec_not_deliverable")

	def test_okunamayan_video_motor_koduyla_reddedilir(self):
		sonuc = validation.validate(
			"company.cover_video",
			_video(
				measured=False,
				has_video=False,
				width=0,
				height=0,
				coded_width=0,
				coded_height=0,
				duration_s=0.0,
				video_duration_s=0.0,
				error="ffprobe_failed",
			),
		)
		self.assertTrue(sonuc.rejected)
		self.assertEqual(sonuc.stage, "engine")
		self.assertEqual(sonuc.code, "video_probe_failed")

	def test_mutlak_motor_siniri_slot_reddinden_once_raporlanir(self):
		sonuc = validation.validate(
			"company.cover_video",
			_video(duration_s=901.0, video_duration_s=901.0),
		)
		self.assertTrue(sonuc.rejected)
		self.assertEqual(sonuc.stage, "engine")
		self.assertEqual(sonuc.code, "video_duration_over_max")


if __name__ == "__main__":
	unittest.main()

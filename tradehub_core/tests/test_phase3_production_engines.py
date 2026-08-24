"""Phase 3 production-adapter tests (no Frappe site required)."""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from PIL import Image

from tradehub_core.media.pipeline.contracts.errors import UnsupportedFormat
from tradehub_core.media.pipeline.contracts.image import ImageEngine, MasterSpec, RenditionSpec
from tradehub_core.media.pipeline.contracts.video import (
	AUDIO_STRIPPED,
	PreviewClipSpec,
	VideoEngine,
	VideoRenditionSpec,
	VideoSource,
)
from tradehub_core.media.pipeline.image.engine import PillowImageEngine
from tradehub_core.media.pipeline.video.engine import FfmpegVideoEngine
from tradehub_core.media.pipeline.video.probe import VideoFacts


def _image(fmt: str = "JPEG", size: tuple[int, int] = (320, 240), mode: str = "RGB") -> bytes:
	buffer = io.BytesIO()
	color = (18, 92, 171, 128) if mode == "RGBA" else (18, 92, 171)
	Image.new(mode, size, color).save(buffer, fmt, quality=91, dpi=(300, 300))
	return buffer.getvalue()


SOURCE_FACTS = VideoFacts(
	size_bytes=4096,
	measured=True,
	has_video=True,
	width=1920,
	height=1080,
	duration_s=8.0,
	fps=30.0,
	video_codec="h264",
	video_bitrate_bps=4_000_000,
	format_bitrate_bps=4_128_000,
	container="mov,mp4",
	container_family="mp4",
	has_audio=True,
	audio_codec="aac",
)
OUTPUT_FACTS = VideoFacts(
	size_bytes=5,
	measured=True,
	has_video=True,
	width=640,
	height=360,
	duration_s=8.0,
	fps=30.0,
	video_codec="h264",
	video_bitrate_bps=700_000,
	format_bitrate_bps=796_000,
	container="mov,mp4",
	container_family="mp4",
	has_audio=False,
)


class PillowImageEngineTest(unittest.TestCase):
	def setUp(self) -> None:
		self.engine = PillowImageEngine()

	def test_production_engine_protocolu_karsiliyor(self):
		self.assertIsInstance(self.engine, ImageEngine)

	def test_master_sabit_nokta_ve_metadata_normalizasyonu(self):
		spec = MasterSpec(max_long_edge=200, format="webp", quality=82, dpi_out=72)
		first = self.engine.make_master(_image(), spec)
		second = self.engine.make_master(first.content, spec)
		self.assertEqual((first.width, first.height), (200, 150))
		self.assertEqual(first.content, second.content)
		self.assertTrue(any(note.startswith("metadata:gps_removed") for note in first.notes))

	def test_alfa_jpeg_mastera_dusurulmez(self):
		with self.assertRaises(UnsupportedFormat) as caught:
			self.engine.make_master(
				_image("PNG", mode="RGBA"), MasterSpec(max_long_edge=320, format="jpeg")
			)
		self.assertIn("alpha_lost", caught.exception.kod)

	def test_gercek_rendition_ve_kalite(self):
		master = self.engine.make_master(
			_image(), MasterSpec(max_long_edge=320, format="webp", quality=82)
		)
		rendition = self.engine.make_rendition(
			master.content, RenditionSpec(name="w96", width=96, format="webp", quality=80)
		)
		self.assertEqual(rendition.width, 96)
		self.assertTrue(rendition.content)
		self.assertTrue(self.engine.quality_score(rendition.content, rendition.content).measured)


class FfmpegVideoEngineTest(unittest.TestCase):
	def setUp(self) -> None:
		self.engine = FfmpegVideoEngine()
		self.source = VideoSource(content=b"source-video")
		self.spec = VideoRenditionSpec(
			id="mobile",
			width=640,
			height=360,
			container="mp4",
			video_codec="libx264",
			crf=24,
			maxrate_kbps=900,
			bufsize_kbps=1800,
			audio=AUDIO_STRIPPED,
		)

	def test_production_engine_protocolu_karsiliyor(self):
		self.assertIsInstance(self.engine, VideoEngine)

	@staticmethod
	def _fake_ffmpeg(command, *, timeout):
		Path(command[-1]).write_bytes(b"video")

	def test_transcode_bellek_ciktisi_ve_ses_silme(self):
		with (
			mock.patch(
				"tradehub_core.media.pipeline.video.engine.probe_mod.probe",
				side_effect=(SOURCE_FACTS, OUTPUT_FACTS),
			),
			mock.patch(
				"tradehub_core.media.pipeline.video.engine.run_ffmpeg",
				side_effect=self._fake_ffmpeg,
			) as run,
		):
			artifact = self.engine.transcode(self.source, self.spec)
		self.assertEqual(artifact.content, b"video")
		self.assertFalse(artifact.has_audio)
		self.assertIn("audio_stripped", artifact.notes)
		command = run.call_args.args[0]
		self.assertIn("-an", command)
		self.assertEqual(command[-4:-1], ["-progress", "pipe:1", "-nostats"])

	def test_target_atomik_promote_edilir(self):
		with tempfile.TemporaryDirectory() as directory:
			target = Path(directory) / "final.mp4"
			with (
				mock.patch(
					"tradehub_core.media.pipeline.video.engine.probe_mod.probe",
					side_effect=(SOURCE_FACTS, OUTPUT_FACTS),
				),
				mock.patch(
					"tradehub_core.media.pipeline.video.engine.run_ffmpeg",
					side_effect=self._fake_ffmpeg,
				),
			):
				artifact = self.engine.transcode(self.source, self.spec, target_path=str(target))
			self.assertEqual(target.read_bytes(), b"video")
			self.assertIsNone(artifact.content)
			self.assertEqual(artifact.path, str(target))
			self.assertEqual(list(Path(directory).iterdir()), [target])

	def test_preview_contract_specini_ffmpeg_komutuna_tasir(self):
		preview_out = replace(OUTPUT_FACTS, duration_s=4.0)
		with (
			mock.patch(
				"tradehub_core.media.pipeline.video.engine.probe_mod.probe",
				side_effect=(SOURCE_FACTS, preview_out),
			),
			mock.patch(
				"tradehub_core.media.pipeline.video.engine.run_ffmpeg",
				side_effect=self._fake_ffmpeg,
			) as run,
		):
			artifact = self.engine.make_preview_clip(
				self.source,
				PreviewClipSpec(
					duration_s=4.0,
					width=640,
					height=360,
					video_codec="libx264",
					container="mp4",
				),
			)
		command = run.call_args.args[0]
		self.assertIn("4.000", command)
		self.assertIn("-an", command)
		self.assertEqual(artifact.duration_s, 4.0)
		self.assertIn("loopable", artifact.notes)

	@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe yok")
	def test_gercek_ffmpeg_ile_probe_ve_transcode(self):
		"""CI'da gerçek ikilileri kullanır; yerel makinede yoksa açıkça atlanır."""
		with tempfile.TemporaryDirectory() as directory:
			source = Path(directory) / "source.mp4"
			subprocess.run(
				[
					"ffmpeg",
					"-y",
					"-hide_banner",
					"-loglevel",
					"error",
					"-f",
					"lavfi",
					"-i",
					"testsrc2=size=320x180:rate=10",
					"-t",
					"1",
					"-c:v",
					"libx264",
					"-pix_fmt",
					"yuv420p",
					str(source),
				],
				check=True,
				capture_output=True,
				timeout=20,
			)
			probe = self.engine.probe(VideoSource(path=str(source)))
			self.assertTrue(probe.measured)
			self.assertEqual((probe.width, probe.height), (320, 180))
			artifact = self.engine.transcode(VideoSource(path=str(source)), self.spec)
			self.assertTrue(artifact.content)
			self.assertGreater(artifact.size_bytes, 0)
			self.assertLessEqual(artifact.width, self.spec.width)


if __name__ == "__main__":
	unittest.main()

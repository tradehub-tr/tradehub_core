"""T-062 — animated GIF → gerçek MP4/H.264 + WebM/VP9 + poster sözleşmesi."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tradehub_core.media.pipeline.video import animation as A
from tradehub_core.media.pipeline.video import probe as video_probe

FFMPEG = A.ffmpeg_available() and video_probe.ffprobe_available()


def _animated_gif(path: Path, size: tuple[int, int] = (192, 144)) -> None:
	from PIL import Image

	ilk = Image.new("RGB", size, (20, 80, 180))
	ikinci = Image.new("RGB", size, (220, 40, 70))
	ilk.save(path, "GIF", save_all=True, append_images=[ikinci], duration=80, loop=0, optimize=True)
	ilk.close()
	ikinci.close()


class KomutSozlesmesiTest(unittest.TestCase):
	def test_iki_video_codec_ve_poster_ayri_komutlardir(self):
		komutlar = A.build_commands("input.gif", "out.mp4", "out.webm", "poster.png")

		self.assertEqual(len(komutlar), 3)
		self.assertIn("libx264", komutlar[0])
		self.assertIn("+faststart", komutlar[0])
		self.assertIn("libvpx-vp9", komutlar[1])
		self.assertIn("-frames:v", komutlar[2])
		self.assertNotIn("benefit", " ".join(" ".join(k) for k in komutlar).lower())
		self.assertIn("max(2,trunc(min(1280,iw)/2)*2)", " ".join(komutlar[0]))

	def test_statik_gif_animasyon_diye_donusturulmez(self):
		from PIL import Image

		with tempfile.TemporaryDirectory(prefix="t062-static-gif-") as gecici:
			root = Path(gecici)
			src = root / "static.gif"
			Image.new("RGB", (32, 24), (10, 20, 30)).save(src, "GIF")

			r = A.convert(src, root / "out.mp4", root / "out.webm", root / "poster.png")

		self.assertFalse(r.ok)
		self.assertEqual(r.reason, "not_animated_gif")


@unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe yok — production image CI'da koşulur")
class GercekFfmpegTest(unittest.TestCase):
	def test_tiny_gif_buyuse_bile_mp4_webm_poster_uretilir_ve_probe_edilir(self):
		with tempfile.TemporaryDirectory(prefix="t062-animation-") as gecici:
			root = Path(gecici)
			src = root / "tiny.gif"
			mp4 = root / "tiny.mp4"
			webm = root / "tiny.webm"
			poster = root / "tiny-poster.png"
			_animated_gif(src)
			kaynak_bayt = src.stat().st_size

			r = A.convert(src, mp4, webm, poster)

			self.assertTrue(r.ok, r.reason)
			self.assertEqual(r.job_type, "video_from_animation")
			self.assertTrue(mp4.is_file() and webm.is_file() and poster.is_file())
			self.assertGreater(mp4.stat().st_size, kaynak_bayt, "tiny fixture büyümeli; benefit gate uygulanmamalı")
			mp4_facts = video_probe.probe(str(mp4))
			webm_facts = video_probe.probe(str(webm))
			self.assertTrue(mp4_facts.measured, mp4_facts.error)
			self.assertEqual((mp4_facts.container_family, mp4_facts.video_codec), ("mp4", "h264"))
			self.assertTrue(webm_facts.measured, webm_facts.error)
			self.assertEqual((webm_facts.container_family, webm_facts.video_codec), ("webm", "vp9"))
			from PIL import Image

			with Image.open(poster) as im:
				self.assertEqual((im.format, im.size), ("PNG", (192, 144)))
			self.assertEqual(
				[(o.kind, o.container, o.codec) for o in r.outputs],
				[("video", "mp4", "h264"), ("video", "webm", "vp9"), ("poster", "png", "png")],
			)

	def test_odd_boyutlu_gif_video_ciktilari_en_az_iki_ve_cifttir(self):
		"""yuv420p/libx264 odd genişlik veya yüksekliğe düşmemeli."""
		with tempfile.TemporaryDirectory(prefix="t062-animation-odd-") as gecici:
			root = Path(gecici)
			src = root / "odd.gif"
			mp4 = root / "odd.mp4"
			webm = root / "odd.webm"
			poster = root / "odd-poster.png"
			_animated_gif(src, (193, 145))

			r = A.convert(src, mp4, webm, poster)

			self.assertTrue(r.ok, r.reason)
			for yol, kap, kodek in ((mp4, "mp4", "h264"), (webm, "webm", "vp9")):
				facts = video_probe.probe(str(yol))
				self.assertEqual((facts.container_family, facts.video_codec), (kap, kodek))
				self.assertGreaterEqual(min(facts.width, facts.height), 2)
				self.assertEqual((facts.width % 2, facts.height % 2), (0, 0))


if __name__ == "__main__":
	unittest.main(verbosity=2)

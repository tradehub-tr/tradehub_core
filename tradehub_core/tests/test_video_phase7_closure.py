"""Faz 7 kapanış kapıları — T-070…T-075'in eksik kalan sözleşmeleri.

Bu suit hızlı ve deterministiktir; gerçek 4K60 ölçümü gecelik koşucudaki
``tests/golden/video/benchmark_4k60.py`` tarafından yapılır. Buradaki testler
o ölçümün tarifini, kaynak limitlerini ve üretim kablolarını kilitler.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
ISTOC_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.security import isolation  # noqa: E402
from tradehub_core.media.pipeline.video import poster as poster_mod  # noqa: E402
from tradehub_core.media.pipeline.video import probe as probe_mod  # noqa: E402
from tradehub_core.media.pipeline.video import transcode as transcode_mod  # noqa: E402

GOLDEN_DIR = ROOT / "tradehub_core" / "tests" / "golden" / "video"
GOLDEN_MANIFEST = GOLDEN_DIR / "manifest.json"


def _probe_payload(*, duration: str = "10.0", error_count: int = 0) -> dict:
	return {
		"_probe_error_count": error_count,
		"streams": [
			{
				"codec_type": "video",
				"codec_name": "hevc",
				"profile": "Main 10",
				"level": 153,
				"width": 1920,
				"height": 1080,
				"sample_aspect_ratio": "1:1",
				"display_aspect_ratio": "16:9",
				"avg_frame_rate": "60000/1001",
				"bit_rate": "8000000",
				"duration": duration,
				"start_time": "0.040",
				"pix_fmt": "yuv420p10le",
				"color_transfer": "smpte2084",
				"color_primaries": "bt2020",
				"color_space": "bt2020nc",
				"has_b_frames": 2,
				"tags": {"rotate": "90"},
			},
			{
				"codec_type": "audio",
				"codec_name": "aac",
				"bit_rate": "128000",
				"channels": 2,
				"sample_rate": "48000",
				"duration": duration,
				"start_time": "0.061",
			},
		],
		"format": {
			"format_name": "mov,mp4,m4a,3gp,3g2,mj2",
			"duration": duration,
			"bit_rate": "8128000",
			"nb_streams": 2,
		},
	}


class ProbeTamligiVeIzolasyon(unittest.TestCase):
	def test_tum_karar_alanlari_rotation_ve_hdr_ile_doner(self):
		with tempfile.NamedTemporaryFile(suffix=".mp4") as fh, mock.patch.object(
			probe_mod, "ffprobe_json", return_value=_probe_payload()
		):
			facts = probe_mod.probe(fh.name)

		self.assertTrue(facts.measured, facts.error)
		self.assertEqual((facts.coded_width, facts.coded_height), (1920, 1080))
		self.assertEqual((facts.width, facts.height), (1080, 1920), "90° metadata etkin ölçüyü döndürmeli")
		self.assertEqual(facts.rotation, 90)
		self.assertEqual(facts.video_level, 153)
		self.assertEqual(facts.sample_aspect_ratio, "1:1")
		self.assertEqual(facts.display_aspect_ratio, "9:16")
		self.assertEqual(facts.color_transfer, "smpte2084")
		self.assertEqual(facts.color_primaries, "bt2020")
		self.assertEqual(facts.color_space, "bt2020nc")
		self.assertTrue(facts.is_hdr)
		self.assertTrue(facts.has_bframes)
		self.assertEqual(facts.error_count, 0)
		self.assertAlmostEqual(facts.video_start_time_s, 0.040, places=3)
		self.assertAlmostEqual(facts.audio_start_time_s, 0.061, places=3)

	def test_duration_sifir_kesik_dosya_olarak_reddedilir(self):
		with tempfile.NamedTemporaryFile(suffix=".mp4") as fh, mock.patch.object(
			probe_mod, "ffprobe_json", return_value=_probe_payload(duration="0")
		):
			facts = probe_mod.probe(fh.name)
		self.assertFalse(facts.measured)
		self.assertIn("sure", facts.error.lower())

	def test_decode_hatasi_bozuk_dosya_olarak_reddedilir(self):
		with tempfile.NamedTemporaryFile(suffix=".mp4") as fh, mock.patch.object(
			probe_mod, "ffprobe_json", return_value=_probe_payload(error_count=2)
		):
			facts = probe_mod.probe(fh.name)
		self.assertFalse(facts.measured)
		self.assertEqual(facts.error_count, 2)
		self.assertIn("hata", facts.error.lower())

	def test_ffprobe_rlimit_altinda_calisir(self):
		payload = json.dumps(_probe_payload()).encode()
		sonuc = isolation.IsolationResult(ok=True, stdout=payload, limits_applied=["RLIMIT_AS"])
		with mock.patch.object(probe_mod.isolation, "run_command", return_value=sonuc) as run:
			veri = probe_mod.ffprobe_json("/tmp/video.mp4", timeout=7)
		self.assertEqual(veri["format"]["duration"], "10.0")
		limits = run.call_args.kwargs["limits"]
		self.assertEqual(limits.wall_timeout_s, 7)
		self.assertIsNotNone(limits.address_space_bytes)
		self.assertGreater(limits.address_space_bytes, 0)

	def test_bellek_limiti_worker_istisnasina_donusmez(self):
		sonuc = isolation.IsolationResult(ok=False, sebep=isolation.SEBEP_MEMORY)
		with tempfile.NamedTemporaryFile(suffix=".mp4") as fh, mock.patch.object(
			probe_mod.isolation, "run_command", return_value=sonuc
		):
			facts = probe_mod.probe(fh.name)
		self.assertFalse(facts.measured)
		self.assertIn("bellek", facts.error.lower())


class TranscodeDogrulama(unittest.TestCase):
	def test_vmaf_olcumu_calisma_dizinine_log_birakmaz(self):
		facts = probe_mod.VideoFacts(measured=True, has_video=True, width=1280, height=720)
		kosum = isolation.IsolationResult(ok=True, stderr=b"[Parsed_libvmaf] VMAF score: 95.250000")
		with mock.patch.object(transcode_mod, "vmaf_available", return_value=True), mock.patch.object(
			transcode_mod.probe_modulu, "probe", return_value=facts
		), mock.patch.object(transcode_mod.isolation, "run_command", return_value=kosum) as run:
			olcum = transcode_mod.measure_quality("reference.mp4", "distorted.mp4")

		filtre = run.call_args.args[0][run.call_args.args[0].index("-filter_complex") + 1]
		self.assertEqual(filtre, "[1:v]scale=1280:720:flags=bicubic[dist];[dist][0:v]libvmaf")
		self.assertNotIn("log_path", filtre)
		self.assertEqual(olcum["vmaf"], 95.25)

	def test_hdr_kaynakta_tonemap_ve_bt709_etiketleri_var(self):
		facts = probe_mod.VideoFacts(
			measured=True,
			has_video=True,
			width=3840,
			height=2160,
			fps=60,
			is_hdr=True,
			color_transfer="smpte2084",
		)
		cmd = transcode_mod.build_transcode_cmd("in.mp4", "out.mp4", transcode_mod.H264Spec(), facts)
		vf = cmd[cmd.index("-vf") + 1]
		self.assertIn("tonemap=", vf)
		self.assertIn("zscale", vf)
		self.assertEqual(cmd[cmd.index("-color_trc") + 1], "bt709")
		self.assertIn("-progress", cmd)
		self.assertIn("pipe:1", cmd)

	def test_sdr_kaynak_tonemap_yapmaz(self):
		facts = probe_mod.VideoFacts(measured=True, has_video=True, width=1280, height=720, fps=30)
		cmd = transcode_mod.build_transcode_cmd("in.mp4", "out.mp4", transcode_mod.H264Spec(), facts)
		self.assertNotIn("tonemap=", cmd[cmd.index("-vf") + 1])

	def test_av_sync_baslangic_ve_bitis_sapmasini_olcer(self):
		reference = probe_mod.VideoFacts(
			measured=True,
			has_audio=True,
			video_start_time_s=0.0,
			video_duration_s=10.0,
			audio_start_time_s=0.020,
			audio_duration_s=9.98,
		)
		distorted = probe_mod.VideoFacts(
			measured=True,
			has_audio=True,
			video_start_time_s=0.0,
			video_duration_s=10.0,
			audio_start_time_s=0.045,
			audio_duration_s=9.955,
		)
		olcum = transcode_mod.av_sync_from_facts(reference, distorted)
		self.assertTrue(olcum["measured"])
		self.assertAlmostEqual(olcum["start_delta_s"], 0.025, places=3)
		self.assertLessEqual(olcum["max_delta_s"], 0.1)

	def test_dogrulama_kapisi_sure_sync_ve_siyah_kareyi_reddeder(self):
		ok, report = transcode_mod.validate_delivery_metrics(
			duration_delta=0.101,
			av_sync_delta=0.120,
			first_frame_luma=0.4,
			has_audio=True,
		)
		self.assertFalse(ok)
		self.assertEqual(report["duration_gate"], "DUSTU")
		self.assertEqual(report["av_sync_gate"], "DUSTU")
		self.assertEqual(report["first_frame_gate"], "DUSTU")

	def test_izole_kosum_kaynak_kunyesini_dondurur(self):
		iso_result = isolation.IsolationResult(
			ok=True,
			stdout=b"progress=end\n",
			peak_rss_bytes=123456,
			cpu_user_s=1.25,
			cpu_system_s=0.25,
			limits_applied=["RLIMIT_AS", "RLIMIT_CPU"],
		)
		with mock.patch.object(transcode_mod.isolation, "run_command", return_value=iso_result) as run:
			got = transcode_mod.run_ffmpeg(["ffmpeg", "-version"], timeout=9)
		self.assertIs(got, iso_result)
		self.assertEqual(run.call_args.kwargs["limits"].wall_timeout_s, 9)
		self.assertIsNotNone(run.call_args.kwargs["limits"].resident_memory_bytes)

	def test_kodlayici_thread_sayisi_worker_cpu_tavanina_hizali(self):
		facts = probe_mod.VideoFacts(measured=True, has_video=True, width=1280, height=720, fps=30)
		spec = transcode_mod.H264Spec.from_table()
		cmd = transcode_mod.build_transcode_cmd("in.mp4", "out.mp4", spec, facts)
		self.assertEqual(spec.encoder_threads, 2)
		self.assertEqual(cmd[cmd.index("-threads:v") + 1], "2")


class PosterAnlamliKare(unittest.TestCase):
	def test_duz_kare_bulanik_desenli_kare_anlamlidir(self):
		try:
			from PIL import Image
		except Exception as exc:  # pragma: no cover - Pillow proje bagimliligi
			self.skipTest(str(exc))
		with tempfile.TemporaryDirectory() as d:
			duz = Path(d) / "duz.png"
			desen = Path(d) / "desen.png"
			Image.new("L", (128, 128), 128).save(duz)
			im = Image.new("L", (128, 128), 0)
			px = im.load()
			for y in range(128):
				for x in range(128):
					px[x, y] = 255 if (x // 8 + y // 8) % 2 else 0
			im.save(desen)
			duz_edge = poster_mod.edge_density_pct(str(duz))
			desen_edge = poster_mod.edge_density_pct(str(desen))
		self.assertLess(duz_edge, desen_edge)
		self.assertFalse(poster_mod.frame_is_meaningful(50.0, duz_edge, poster_mod.PosterSpec()))
		self.assertTrue(poster_mod.frame_is_meaningful(50.0, desen_edge, poster_mod.PosterSpec()))


class TeslimVeKaynakButcesi(unittest.TestCase):
	def test_hls_cache_kurallari_playlist_kisa_segment_immutable(self):
		conf_path = ISTOC_ROOT / "docker" / "nginx" / "gateway.conf"
		if not conf_path.is_file():
			self.skipTest("workspace Docker yapılandırması bu backend checkout'unda yok")
		conf = conf_path.read_text(encoding="utf-8")
		self.assertIn("/hls/.+\\.m3u8$", conf)
		self.assertRegex(conf, r"m3u8.+max-age=60")
		self.assertIn("/hls/.+\\.(ts|m4s|mp4)$", conf)
		self.assertRegex(conf, r"ts\|m4s\|mp4.+31536000.+immutable")

	def test_video_ayri_tek_worker_kuyrugunda(self):
		bridge = (ROOT / "tradehub_core" / "media" / "pipeline_bridge.py").read_text(encoding="utf-8")
		compose_path = ISTOC_ROOT / "docker" / "docker-compose.yml"
		if not compose_path.is_file():
			self.skipTest("workspace Docker yapılandırması bu backend checkout'unda yok")
		compose = compose_path.read_text(encoding="utf-8")
		self.assertIn("RQ_QUEUE_VIDEO: str = media_queues.VIDEO.name", bridge)
		self.assertIn("queue=RQ_QUEUE_VIDEO", bridge)
		self.assertIn("queue-media-video:", compose)
		self.assertIn('["bench", "worker", "--queue", "media-video"]', compose)

	def test_4k60_gecelik_manifesti_ve_butceleri_var(self):
		manifest = json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))
		fixture = manifest["fixture"]
		self.assertEqual((fixture["width"], fixture["height"], fixture["fps"]), (3840, 2160, 60))
		self.assertGreater(fixture["duration_s"], 60)
		budgets = manifest["budgets"]
		self.assertGreater(budgets["wall_s_max"], 0)
		self.assertGreater(budgets["cpu_s_max"], 0)
		self.assertGreater(budgets["peak_rss_bytes_max"], 0)
		self.assertEqual(budgets["max_concurrent_transcodes"], 1)
		self.assertTrue((GOLDEN_DIR / "benchmark_4k60.py").is_file())
		self.assertTrue((ROOT / ".github" / "workflows" / "faz7-video-engine.yml").is_file())


if __name__ == "__main__":
	unittest.main(verbosity=2)

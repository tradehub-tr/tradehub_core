"""T-072/T-073/T-074 testleri — transcode, fayda kapısı, poster, klip, HLS.

Testler iki kümeye ayrılıyor ve bu ayrım bilinçli:

**Komut kurulumu (ffmpeg GEREKMEZ).** ffmpeg argümanları bir sözleşmedir:
`-profile:v high`, `-movflags +faststart`, ses yoksa `-an`, `scale` filtresinin
TEK TIRNAKLI olması. Bunların hepsi ffmpeg çalıştırmadan sınanabilir ve
sınanmalıdır — çünkü bir argümanın sessizce düşmesi (`-an` unutulunca sessiz
dosyada patlayan komut, tırnaksız `min(1280,iw)` yüzünden kesilen filtre)
üretimde ancak o dosya tipi gelince görünür.

**Gerçek koşum (ffmpeg GEREKİR).** Fayda kapısının gerçekten devreye girmesi,
REMUX'un moov'u başa alması, poster'ın parlaklık kapısından geçmesi, HLS
merdiveninin büyütme yapmaması — bunlar ancak gerçek ffmpeg ile ölçülür.
Yerel makinede ffmpeg YOK; bu testler orada ATLANIR (skip), konteynerde çalışır:

    docker exec -w /home/frappe/frappe-bench/sites istoc-dev-backend-1 \
        ../env/bin/python -m unittest tests.test_video_transcode -v

Testlerdeki bütün sayı beklentileri ÖLÇÜLDÜ (ffmpeg 5.1.9-0+deb12u1,
istoc-dev-backend-1, 2026-08-18). Ölçülmeyen hiçbir sayı yazılmadı; ffmpeg
sürümüne göre değişebilecek büyüklükler kesin eşitlikle değil YÖN ve
BÜYÜKLÜK MERTEBESİ ile sınanıyor (ör. "kazanç %50'nin üstünde", "%60,89'a
eşit" değil).

**VMAF YOK.** Konteynerdeki ffmpeg `libvmaf` olmadan derlenmiş
(`T.vmaf_available()` → False, ölçüldü). Kalite ölçümü SSIM + PSNR'a düşüyor;
`measure_quality` bunu `vmaf_note` alanında açıkça söylüyor ve uydurma bir
VMAF puanı ÜRETMİYOR.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.contracts.errors import ProbeUnavailable, TranscodeFailed  # noqa: E402
from tradehub_core.media.pipeline.video import hls as H  # noqa: E402
from tradehub_core.media.pipeline.video import poster as PO  # noqa: E402
from tradehub_core.media.pipeline.video import probe as P  # noqa: E402
from tradehub_core.media.pipeline.video import transcode as T  # noqa: E402
from tradehub_core.media.pipeline.video.decision import (  # noqa: E402
	ACTION_PASSTHROUGH,
	ACTION_REJECT,
	ACTION_REMUX,
	ACTION_TRANSCODE,
	decide,
	default_table,
)

VIDEO_DIR = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "video"
FFMPEG = T.ffmpeg_available() and P.ffprobe_available()

VERIMLI = "video_efficient_720p_750k.mp4"
SISIRILMIS = "video_bloated_720p_8m.mp4"
SESSIZ = "video_silent_noaudio_720p.mp4"
BUYUK = "video_16x9_1080p.mp4"
DIKEY = "video_vertical_9x16.mp4"
KARE = "video_square_352.mp4"
UZUN = "video_long_540s_320x240.mp4"


def kunye(**d) -> P.VideoFacts:
	"""Sentetik künye — ffprobe çalıştırmadan komut kurulumu sınamak için."""
	temel = dict(measured=True, has_video=True, width=1280, height=720, duration_s=10.0,
		fps=30.0, video_codec="h264", pix_fmt="yuv420p", video_bitrate_bps=767652,
		container_family="mp4", has_audio=True, audio_codec="aac", size_bytes=1_092_127)
	temel.update(d)
	return P.VideoFacts(**temel)


# ══════════════════════════════════════════════════════════════════════════
# 1. Komut kurulumu — ffmpeg GEREKMEZ
# ══════════════════════════════════════════════════════════════════════════


class TranscodeKomutu(unittest.TestCase):
	"""H.264 komutu doğru kuruluyor mu — argüman argüman."""

	def setUp(self):
		self.spec = T.H264Spec.from_table()

	def test_hedef_h264_high_aac_faststart(self):
		"""Görev tanımının istediği üçlü: H.264 High + AAC 128k + faststart."""
		cmd = T.build_transcode_cmd("g.mp4", "c.mp4", self.spec, kunye())
		self.assertIn("libx264", cmd)
		self.assertEqual(cmd[cmd.index("-profile:v") + 1], "high")
		self.assertEqual(cmd[cmd.index("-c:a") + 1], "aac")
		self.assertEqual(cmd[cmd.index("-b:a") + 1], "128k")
		self.assertEqual(cmd[cmd.index("-movflags") + 1], "+faststart")
		self.assertEqual(cmd[cmd.index("-pix_fmt") + 1], "yuv420p")

	def test_bugunku_hattin_vp9u_URETILMIYOR(self):
		"""Belgelenmiş FARK: bugünkü hat libvpx-vp9/libopus üretiyor, bu modül üretmiyor."""
		cmd = T.build_transcode_cmd("g.mp4", "c.mp4", self.spec, kunye())
		self.assertNotIn("libvpx-vp9", cmd)
		self.assertNotIn("libopus", cmd)

	def test_scale_filtresi_TEK_TIRNAKLI(self):
		"""`min(1280,iw)` içindeki virgül filtergraph ayracıdır; tırnaksız kesilir.

		Bugünkü hat bu hatayı GERÇEK ffmpeg ile yaşamış ve yorumla kayda
		geçirmiş (transcode.py:353-355). Aynı tuzağa ikinci kez düşülmesin.
		"""
		cmd = T.build_transcode_cmd("g.mp4", "c.mp4", self.spec, kunye())
		vf = cmd[cmd.index("-vf") + 1]
		self.assertIn("scale='min(1280,iw)':-2", vf)

	def test_scale_buyutme_yapmaz(self):
		"""`min(1280,iw)` — 640 genişlikteki kaynak 1280'e ÇIKARILMAZ."""
		self.assertEqual(T._scale_filter(1280), "scale='min(1280,iw)':-2")

	def test_sessiz_kaynakta_an_yazilir(self):
		"""Ses akışı olmayan dosyaya `-c:a` vermek "Stream map matches no streams" ile düşer."""
		cmd = T.build_transcode_cmd("g.mp4", "c.mp4", self.spec, kunye(has_audio=False, audio_codec=""))
		self.assertIn("-an", cmd)
		self.assertNotIn("-c:a", cmd)
		self.assertNotIn("0:a:0?", cmd)

	def test_sesli_kaynakta_ses_haritalanir(self):
		cmd = T.build_transcode_cmd("g.mp4", "c.mp4", self.spec, kunye(has_audio=True))
		self.assertIn("0:a:0?", cmd)
		self.assertNotIn("-an", cmd)

	def test_fps_filtresi_yalniz_tavan_asilinca(self):
		"""25 fps kaynağı 30'a ÇIKARMAK kare çoğaltır, bayt harcar, hiçbir şey kazandırmaz."""
		alt = T.build_transcode_cmd("g.mp4", "c.mp4", self.spec, kunye(fps=25.0))
		self.assertNotIn("fps=30", alt[alt.index("-vf") + 1])
		ust = T.build_transcode_cmd("g.mp4", "c.mp4", self.spec, kunye(fps=60.0))
		self.assertIn("fps=30", ust[ust.index("-vf") + 1])

	def test_gop_gercek_kare_hizindan_hesaplanir(self):
		"""2 sn × fps. 25 fps → 50, 30 fps → 60, 60 fps → (tavan 30 ×2) 60."""
		for fps, beklenen in ((25.0, 50), (30.0, 60), (60.0, 60), (10.0, 20)):
			with self.subTest(fps=fps):
				cmd = T.build_transcode_cmd("g.mp4", "c.mp4", self.spec, kunye(fps=fps))
				self.assertEqual(cmd[cmd.index("-g") + 1], str(beklenen))
				self.assertEqual(cmd[cmd.index("-keyint_min") + 1], str(beklenen))

	def test_sahne_kesimi_anahtar_karesi_kapali(self):
		"""HLS segment sınırının anahtar kareye denk gelmesi buna bağlı."""
		cmd = T.build_transcode_cmd("g.mp4", "c.mp4", self.spec, kunye())
		self.assertEqual(cmd[cmd.index("-sc_threshold") + 1], "0")

	def test_yalniz_ilk_video_ve_ilk_ses_tasinir(self):
		"""Fazla akış (ikinci dil, altyazı, veri) indirilen bayta karışmasın."""
		cmd = T.build_transcode_cmd("g.mp4", "c.mp4", self.spec, kunye())
		self.assertIn("0:v:0", cmd)
		self.assertIn("0:a:0?", cmd)

	def test_nice_onceligi_korunuyor(self):
		cmd = T.build_transcode_cmd("g.mp4", "c.mp4", self.spec, kunye())
		self.assertEqual(cmd[:3], ["nice", "-n", "10"])
		self.assertEqual(T.build_transcode_cmd("g.mp4", "c.mp4", self.spec, kunye(), nice=False)[0], "ffmpeg")

	def test_kunyesiz_komut_kurulabilir(self):
		"""Künye verilmezse güvenli taraf: ses varmış gibi davranılır."""
		cmd = T.build_transcode_cmd("g.mp4", "c.mp4", self.spec, None)
		self.assertIn("-c:a", cmd)


class HizDenetimi(unittest.TestCase):
	"""T-072 — capped CRF. Tek dosya yolunda hız denetimi YOKTU (B-1)."""

	def setUp(self):
		self.spec = T.H264Spec.from_table()

	def test_tabloda_capped_crf_secili(self):
		self.assertEqual(self.spec.rate_control, "capped_crf")
		self.assertTrue(self.spec.budget_from_benefit_gate)

	def test_komutta_maxrate_ve_bufsize_var(self):
		"""CRF tek başına bayt tavanı vermez — tavan komutta GÖRÜNMELİ."""
		cmd = T.build_transcode_cmd("g.mp4", "c.mp4", self.spec, kunye())
		self.assertIn("-maxrate", cmd)
		self.assertIn("-bufsize", cmd)
		self.assertIn("-crf", cmd)
		tavan = cmd[cmd.index("-maxrate") + 1]
		tampon = cmd[cmd.index("-bufsize") + 1]
		self.assertTrue(tavan.endswith("k") and tampon.endswith("k"))
		self.assertEqual(int(tampon[:-1]), int(tavan[:-1]) * 2, "bufsize = 2 x maxrate")

	def test_rate_control_crf_TAVANI_KALDIRIR(self):
		"""Vacuity anahtarı: tabloda `crf` yazınca düzeltme geri alınır.

		Bu test düzeltmenin gerçekten bir şey yaptığını pinler — tavan
		kaldırıldığında komutta `-maxrate` KALMAMALI.
		"""
		import dataclasses

		tavansiz = dataclasses.replace(self.spec, rate_control="crf")
		cmd = T.build_transcode_cmd("g.mp4", "c.mp4", tavansiz, kunye())
		self.assertNotIn("-maxrate", cmd)
		self.assertNotIn("-bufsize", cmd)
		self.assertIn("-crf", cmd)

	def test_tavan_FAYDA_KAPISINDAN_turetiliyor(self):
		"""Tavan = kaynak toplam bitrate × (1 − %10) − çıktı ses bitrate'i.

		Gerçek dosyada ölçüldü (r2, 1920×1080, format bitrate 1.169.219 bps):
		1.169 × 0,9 − 128 = **924 kbps**.
		"""
		f = kunye(format_bitrate_bps=1_169_219, has_audio=True)
		self.assertEqual(T.rate_ceiling_kbps(self.spec, f), 924)

	def test_sessiz_kaynakta_butcenin_TAMAMI_videoya_gider(self):
		"""Ses yoksa çıkarılacak ses payı da yok — sabit çarpanın göremediği fark."""
		sesli = kunye(format_bitrate_bps=1_169_219, has_audio=True)
		sessiz = kunye(format_bitrate_bps=1_169_219, has_audio=False)
		self.assertEqual(T.rate_ceiling_kbps(self.spec, sessiz), 1052)
		self.assertGreater(
			T.rate_ceiling_kbps(self.spec, sessiz),
			T.rate_ceiling_kbps(self.spec, sesli),
		)

	def test_mutlak_tavan_ustte_taban_altta(self):
		"""8 Mbps kaynak 2.500'e, 200 kbps kaynak 300'e kelepçelenir."""
		sisik = kunye(format_bitrate_bps=8_000_000, has_audio=True)
		minik = kunye(format_bitrate_bps=200_000, has_audio=True)
		self.assertEqual(T.rate_ceiling_kbps(self.spec, sisik), self.spec.maxrate_kbps)
		self.assertEqual(T.rate_ceiling_kbps(self.spec, minik), self.spec.min_maxrate_kbps)

	def test_bitrate_olculemezse_tavan_TAHMIN_EDILMEZ(self):
		"""Ölçülemeyen kaynakta mutlak tavana düşülür, uydurma bir sayı üretilmez."""
		bos = kunye(format_bitrate_bps=0, video_bitrate_bps=0, audio_bitrate_bps=0)
		self.assertEqual(T.rate_ceiling_kbps(self.spec, bos), self.spec.maxrate_kbps)
		self.assertEqual(T.rate_ceiling_kbps(self.spec, None), self.spec.maxrate_kbps)


class GeriCekilmeKurali(unittest.TestCase):
	"""B-2 — kapıdan düşen TRANSCODE, REMUX ihtiyacını öldürmemeli."""

	def test_moov_sonda_ise_geri_cekilir(self):
		uygulanir, gerekce = T.remux_fallback_applies(kunye(moov_at_end=True))
		self.assertTrue(uygulanir)
		self.assertIn("moov", gerekce)

	def test_kap_mp4_degilse_geri_cekilir(self):
		uygulanir, gerekce = T.remux_fallback_applies(
			kunye(container_family="matroska", video_codec="h264", audio_codec="aac")
		)
		self.assertTrue(uygulanir)
		self.assertIn("kap", gerekce)

	def test_kusur_yoksa_geri_cekilme_YOK(self):
		"""REMUX bir şey düzeltmeyecekse ikinci bir ffmpeg koşumu israftır."""
		uygulanir, gerekce = T.remux_fallback_applies(kunye(moov_at_end=False, container_family="mp4"))
		self.assertFalse(uygulanir)
		self.assertIn("kusuru yok", gerekce)

	def test_vp9_kaynakta_geri_cekilme_YOK(self):
		"""`-c copy` ile VP9'u mp4'e taşımak kabı düzeltir, OYNATMAYI BOZAR."""
		uygulanir, gerekce = T.remux_fallback_applies(
			kunye(video_codec="vp9", container_family="webm", audio_codec="opus")
		)
		self.assertFalse(uygulanir)
		self.assertIn("vp9", gerekce)

	def test_opus_sesli_kaynakta_geri_cekilme_YOK(self):
		uygulanir, gerekce = T.remux_fallback_applies(
			kunye(video_codec="h264", container_family="webm", has_audio=True, audio_codec="opus")
		)
		self.assertFalse(uygulanir)
		self.assertIn("opus", gerekce)

	def test_olculemeyen_kunyede_geri_cekilme_YOK(self):
		uygulanir, _ = T.remux_fallback_applies(P.VideoFacts(measured=False))
		self.assertFalse(uygulanir)


class RemuxKomutu(unittest.TestCase):
	def test_yeniden_kodlama_yok(self):
		cmd = T.build_remux_cmd("g.mkv", "c.mp4")
		self.assertIn("-c", cmd)
		self.assertEqual(cmd[cmd.index("-c") + 1], "copy")
		self.assertNotIn("libx264", cmd)
		self.assertNotIn("-crf", cmd)

	def test_faststart_var(self):
		cmd = T.build_remux_cmd("g.mkv", "c.mp4")
		self.assertEqual(cmd[cmd.index("-movflags") + 1], "+faststart")


class SpecTablodanOkunuyor(unittest.TestCase):
	"""Hedef değerler KODA GÖMÜLÜ DEĞİL — JSON'dan geliyor."""

	def test_h264_spec_tablodan(self):
		s = T.H264Spec.from_table()
		self.assertEqual(s.max_width, 1280)
		self.assertEqual(s.profile, "high")
		self.assertEqual(s.audio_codec, "aac")
		self.assertEqual(s.audio_bitrate_kbps, 128)
		self.assertEqual(s.container, "mp4")
		self.assertTrue(s.faststart)

	def test_fayda_kapisi_tablodan(self):
		"""INV-05 — %10. Bugünkü video hattında böyle bir kapı YOK."""
		self.assertAlmostEqual(T.min_saving_ratio(), 0.1)

	def test_remux_fayda_kapisindan_muaf(self):
		muaf = default_table().targets["benefit_gate"]["exempt_actions"]
		self.assertIn(ACTION_REMUX, muaf)
		self.assertNotIn(ACTION_TRANSCODE, muaf)

	def test_kaydedilen_kazanc_orani_hesabi(self):
		r = T.TranscodeResult(action=ACTION_TRANSCODE, src_path="x", src_bytes=1000, out_bytes=400)
		self.assertAlmostEqual(r.saving_ratio, 0.6)
		buyudu = T.TranscodeResult(action=ACTION_TRANSCODE, src_path="x", src_bytes=1000, out_bytes=1500)
		self.assertAlmostEqual(buyudu.saving_ratio, -0.5)
		self.assertEqual(T.TranscodeResult(action=ACTION_TRANSCODE, src_path="x").saving_ratio, 0.0)


class KararUygulama(unittest.TestCase):
	"""PASSTHROUGH ve REJECT ffmpeg ÇALIŞTIRMAZ."""

	def test_passthrough_dosyaya_dokunmaz(self):
		with tempfile.TemporaryDirectory() as d:
			src = os.path.join(d, "a.mp4")
			with open(src, "wb") as fh:
				fh.write(b"x" * 100)
			karar = decide(kunye().variables())
			self.assertEqual(karar.action, ACTION_PASSTHROUGH)
			r = T.apply_decision(src, os.path.join(d, "b.mp4"), karar)
			self.assertTrue(r.accepted)
			self.assertTrue(r.kept_source)
			self.assertFalse(os.path.exists(os.path.join(d, "b.mp4")))

	def test_reject_hata_atmaz_karar_dondurur(self):
		"""Ret bir HATA değil bir KARARDIR; çağıran onu kullanıcıya kodlu gösterir."""
		with tempfile.TemporaryDirectory() as d:
			src = os.path.join(d, "a.mp4")
			with open(src, "wb") as fh:
				fh.write(b"x" * 100)
			karar = decide(kunye(measured=False).variables())
			self.assertEqual(karar.action, ACTION_REJECT)
			r = T.apply_decision(src, os.path.join(d, "b.mp4"), karar)
			self.assertFalse(r.accepted)
			self.assertTrue(r.kept_source)
			self.assertIn("video_probe_failed", r.notes[0])

	def test_olculemeyen_kaynakta_transcode_probeunavailable(self):
		with tempfile.TemporaryDirectory() as d:
			src = os.path.join(d, "a.mp4")
			with open(src, "wb") as fh:
				fh.write(b"video degil")
			with self.assertRaises(ProbeUnavailable):
				T.transcode(src, os.path.join(d, "b.mp4"))

	def test_gecici_dosya_hedefle_ayni_dizinde(self):
		"""`os.replace` yalnız aynı dosya sisteminde atomiktir."""
		self.assertEqual(os.path.dirname(T._temp_path("/a/b/c.mp4")), "/a/b")


class PosterPencereHesabi(unittest.TestCase):
	"""ffmpeg gerektirmeyen pencere matematiği."""

	def test_normal_pencere(self):
		"""[0,5 , min(5, süre×0,25)] — açılış siyahlığını atlar, ilk çeyrekten çıkmaz."""
		self.assertEqual(PO.poster_window(10.0), (0.5, 2.5))
		self.assertEqual(PO.poster_window(6.0), (0.5, 1.5))
		self.assertEqual(PO.poster_window(540.0), (0.5, 5.0))

	def test_cok_kisa_videoda_pencere_kendini_yemez(self):
		"""1,2 sn'lik videoda süre×0,25 = 0,3 < 0,5 — pencere ters dönerdi."""
		bas, son = PO.poster_window(1.2)
		self.assertLess(bas, son)
		self.assertEqual((bas, son), (0.0, 1.2))

	def test_ikincil_pencere_ikinci_ceyrek(self):
		self.assertEqual(PO.poster_retry_window(10.0), (2.5, 5.0))

	def test_poster_spec_tablodan(self):
		s = PO.PosterSpec.from_table()
		self.assertEqual(s.format, "webp")
		self.assertEqual(s.width, 1280)
		self.assertEqual(s.max_bytes, 122_880)
		self.assertEqual((s.min_luma_pct, s.max_luma_pct), (6.0, 94.0))
		self.assertEqual(s.max_retries, 1)

	def test_poster_komutu_thumbnail_ve_showinfo(self):
		cmd = PO.build_poster_cmd("g.mp4", "c.webp", (0.5, 2.5), PO.PosterSpec(), 78)
		vf = cmd[cmd.index("-vf") + 1]
		self.assertIn("thumbnail=n=120", vf)
		self.assertIn("showinfo", vf)
		self.assertLess(vf.index("thumbnail"), vf.index("showinfo"), "showinfo thumbnail'dan SONRA gelmeli")
		self.assertEqual(cmd[cmd.index("-frames:v") + 1], "1")
		self.assertEqual(cmd[cmd.index("-ss") + 1], "0.500")

	def test_onizleme_klibi_SESSIZ(self):
		"""Hover'da oynayan klipte ses saldırgandır — `-an` zorunlu."""
		cmd = PO.build_preview_cmd("g.mp4", "c.mp4", 1.4, 6.0, PO.PreviewClipSpec(), 28)
		self.assertIn("-an", cmd)
		self.assertNotIn("-c:a", cmd)

	def test_klip_olcegi_KISA_KENAR_butcesi(self):
		"""854×480 bir KARE BÜTÇESİDİR (≈410 bin piksel), "genişlik 854" değil.

		Yalnız genişliği kısıtlamak dikey videoda bütçeyi patlatıyordu ve bu
		ÖLÇÜLDÜ: 720×1280 kaynak 720×1280 olarak kodlanıp 842.115 bayt
		çıkıyordu — 400 KB politika hedefinin iki katından fazla.
		"""
		spec = PO.PreviewClipSpec()
		yatay = PO.preview_scale_filter(spec, kunye(width=1280, height=720))
		self.assertEqual(yatay, "scale=-2:'min(480,ih)'")
		dikey = PO.preview_scale_filter(spec, kunye(width=720, height=1280))
		self.assertEqual(dikey, "scale='min(480,iw)':-2")

	def test_klip_olcegi_kunyesiz_eski_davranisa_duser(self):
		"""Yönelim bilinmiyorken tahmin etmektense genişlik kapısında kalınır."""
		self.assertEqual(PO.preview_scale_filter(PO.PreviewClipSpec(), None), "scale='min(854,iw)':-2")

	def test_klip_spec_iki_katmanli_bayt_kapisi(self):
		"""Görev tanımı 1 MB (zorunlu), politika 400 KB (hedef) diyor — İKİSİ de tutuluyor."""
		s = PO.PreviewClipSpec.from_table()
		self.assertEqual(s.max_bytes, 1_048_576)
		self.assertEqual(s.policy_max_bytes, 409_600)
		self.assertEqual(s.duration_ladder, (6.0, 4.0, 3.0))
		self.assertEqual(min(s.duration_ladder), 3.0, "3 sn altı onizleme degil titresimdir")

	def test_parlaklik_olculemezse_kapi_uygulanmaz(self):
		"""-1 = "ölçülemedi". Ölçemediğimiz kareyi "karanlık" ilan etmek uydurma olurdu."""
		self.assertEqual(PO.mean_luma_pct("/olmayan/dosya.webp"), -1.0)


class HlsMerdiveni(unittest.TestCase):
	"""ffmpeg gerektirmeyen merdiven mantığı."""

	def setUp(self):
		self.spec = H.HlsSpec.from_table()

	def test_merdiven_tablodan_dort_basamak(self):
		self.assertEqual([r.name for r in self.spec.ladder], ["360p", "480p", "720p", "1080p"])
		self.assertEqual(self.spec.segment_duration_s, 4.0)
		self.assertEqual(self.spec.playlist_type, "vod")

	def test_buyutme_yok(self):
		"""720p kaynaktan 1080p basamağı ÜRETİLMEZ."""
		self.assertEqual([r.name for r in H.select_ladder(kunye(width=1280, height=720))],
			["360p", "480p", "720p"])
		self.assertEqual([r.name for r in H.select_ladder(kunye(width=1920, height=1080))],
			["360p", "480p", "720p", "1080p"])
		self.assertEqual([r.name for r in H.select_ladder(kunye(width=854, height=480))],
			["360p", "480p"])

	def test_dikey_videoda_olcu_KISA_KENAR(self):
		"""720×1280 dikey kaynak yüksekliğe bakan bir merdivende "1080p" sayılırdı.

		Kısa kenar (720) ölçüsü doğru sonucu verir: 360p/480p/720p.
		"""
		rungs = H.select_ladder(kunye(width=720, height=1280))
		self.assertEqual([r.name for r in rungs], ["360p", "480p", "720p"])

	def test_dikey_videoda_basamak_olculeri_dondurulur(self):
		f = kunye(width=720, height=1280)
		self.assertEqual(H.rung_dimensions(H.HlsRung("360p", 640, 360, 800, 856, 1200, 96), f), (360, 640))
		self.assertEqual(H.rung_dimensions(H.HlsRung("720p", 1280, 720, 2800, 2996, 4200, 128), f), (720, 1280))

	def test_yatay_videoda_basamak_olculeri(self):
		f = kunye(width=1920, height=1080)
		self.assertEqual(H.rung_dimensions(H.HlsRung("360p", 640, 360, 800, 856, 1200, 96), f), (640, 360))

	def test_en_alt_basamaktan_kucuk_kaynakta_tek_kaynak_basamagi(self):
		"""352×352 kaynak 360p'ye BÜYÜTÜLMEZ; kendi ölçüsünde tek basamak üretilir."""
		rungs = H.select_ladder(kunye(width=352, height=352))
		self.assertEqual(len(rungs), 1)
		self.assertEqual(rungs[0].name, "352p")
		self.assertEqual((rungs[0].width, rungs[0].height), (352, 352))

	def test_gop_hizasi_dogru(self):
		"""Segment 4 sn / anahtar kare 2 sn → tam bölünür."""
		hizali, sebep = H.check_gop_alignment(self.spec, T.H264Spec.from_table())
		self.assertTrue(hizali, sebep)

	def test_gop_hizasizligi_yakalanir(self):
		bozuk = T.H264Spec(keyframe_interval_s=3.0)
		hizali, sebep = H.check_gop_alignment(self.spec, bozuk)
		self.assertFalse(hizali)
		self.assertIn("bolunmuyor", sebep)

	def test_gop_kare_sayisi_tavandan_hesaplanir(self):
		h = T.H264Spec.from_table()
		self.assertEqual(H.gop_frames(kunye(fps=25.0), h), 50)
		self.assertEqual(H.gop_frames(kunye(fps=30.0), h), 60)
		self.assertEqual(H.gop_frames(kunye(fps=60.0), h), 60)

	def test_hls_gerekliligi_sure_esigi(self):
		self.assertTrue(H.hls_required(kunye(duration_s=61.0)).required)
		self.assertFalse(H.hls_required(kunye(duration_s=60.0, size_bytes=1000)).required)

	def test_hls_gerekliligi_bayt_esigi(self):
		g = H.hls_required(kunye(duration_s=10.0), rendition_bytes=13_000_000)
		self.assertTrue(g.required)
		self.assertIn("rendition", g.reasons[0])

	def test_hls_gerekliligi_basamak_sayisi(self):
		self.assertTrue(H.hls_required(kunye(size_bytes=1000), distinct_tiers=3).required)
		self.assertFalse(H.hls_required(kunye(size_bytes=1000), distinct_tiers=2).required)

	def test_hls_gereklilik_vekil_olcu_not_dusuyor(self):
		"""Rendition boyutu verilmediyse kaynak boyutu VEKİLDİR ve bu YAZILIR."""
		g = H.hls_required(kunye(size_bytes=1000))
		self.assertTrue(any("vekil" in s for s in g.reasons))

	def test_komut_tek_kosumda_split_kullanir(self):
		"""Basamak başına ayrı ffmpeg kaynağı N kez ÇÖZER — split bir kez çözer."""
		f = kunye(width=1920, height=1080)
		cmd = H.build_hls_cmd("g.mp4", "/o", H.select_ladder(f), f, spec=self.spec)
		filtre = cmd[cmd.index("-filter_complex") + 1]
		self.assertIn("split=4", filtre)
		self.assertEqual(cmd.count("-i"), 1, "kaynak birden fazla kez acilmamali")

	def test_komut_capped_crf_kullanir_sabit_bitrate_DEGIL(self):
		"""ÖLÇÜLDÜ: sabit bitrate merdiveni bayt ŞİŞİRİYORDU.

		`video_efficient_720p_750k.mp4` kaynağı 1.092.127 B iken sabit
		bitrate'li 360p basamağı 1.155.673 B çıkmıştı — en düşük basamak
		kaynaktan BÜYÜK. capped CRF'e geçildi.
		"""
		f = kunye(width=1280, height=720)
		cmd = H.build_hls_cmd("g.mp4", "/o", H.select_ladder(f), f, spec=self.spec)
		self.assertIn("-crf:v:0", cmd)
		self.assertNotIn("-b:v:0", cmd)
		self.assertIn("-maxrate:v:0", cmd, "tavan yine korunmali")
		self.assertIn("-bufsize:v:0", cmd)

	def test_cbr_kipi_eski_davranisi_geri_getirir(self):
		f = kunye(width=1280, height=720)
		cbr = H.HlsSpec.from_table({**default_table().hls, "rate_control": "cbr"})
		cmd = H.build_hls_cmd("g.mp4", "/o", H.select_ladder(f), f, spec=cbr)
		self.assertIn("-b:v:0", cmd)
		self.assertNotIn("-crf:v:0", cmd)

	def test_sessiz_kaynakta_ses_haritalanmaz(self):
		f = kunye(width=1280, height=720, has_audio=False, audio_codec="")
		cmd = H.build_hls_cmd("g.mp4", "/o", H.select_ladder(f), f, spec=self.spec)
		self.assertNotIn("0:a:0", cmd)
		harita = cmd[cmd.index("-var_stream_map") + 1]
		self.assertNotIn("a:", harita)
		self.assertIn("v:0,name:360p", harita)

	def test_sesli_kaynakta_her_basamagin_kendi_sesi_var(self):
		f = kunye(width=1280, height=720, has_audio=True)
		cmd = H.build_hls_cmd("g.mp4", "/o", H.select_ladder(f), f, spec=self.spec)
		harita = cmd[cmd.index("-var_stream_map") + 1]
		self.assertEqual(harita, "v:0,a:0,name:360p v:1,a:1,name:480p v:2,a:2,name:720p")

	def test_segment_ve_playlist_ayarlari(self):
		f = kunye()
		cmd = H.build_hls_cmd("g.mp4", "/o", H.select_ladder(f), f, spec=self.spec)
		self.assertEqual(cmd[cmd.index("-hls_time") + 1], "4.0")
		self.assertEqual(cmd[cmd.index("-hls_playlist_type") + 1], "vod")
		self.assertEqual(cmd[cmd.index("-hls_segment_type") + 1], "mpegts")
		self.assertIn("independent_segments", cmd)
		self.assertEqual(cmd[cmd.index("-master_pl_name") + 1], "master.m3u8")

	def test_basamak_dizini_INDISLE_DEGIL_ADLA(self):
		"""GERÇEK ffmpeg 5.1 ile ölçülen tuzak: `name:360p` verilince dizin `v0`
		değil `v360p` oluyor. İndisle yol kurmak boş dizine bakmaya yol açar."""
		rung = H.HlsRung("360p", 640, 360, 800, 856, 1200, 96)
		self.assertTrue(H.variant_dir("/o", rung).endswith("v360p"))
		self.assertTrue(H.variant_playlist("/o", rung).endswith(os.path.join("v360p", "playlist.m3u8")))

	def test_bos_merdivenle_komut_kurulmaz(self):
		with self.assertRaises(TranscodeFailed):
			H.build_hls_cmd("g.mp4", "/o", [], kunye(), spec=self.spec)


# ══════════════════════════════════════════════════════════════════════════
# 2. Gerçek ffmpeg koşumu
# ══════════════════════════════════════════════════════════════════════════


@unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe yok — konteynerde calistir")
class GercekTranscode(unittest.TestCase):
	"""ffmpeg GERÇEKTEN çalışıyor; sayılar ÖLÇÜLDÜ."""

	def setUp(self):
		self.d = tempfile.mkdtemp(prefix="faz7-")

	def tearDown(self):
		shutil.rmtree(self.d, ignore_errors=True)

	def test_sisirilmis_video_transcode_edilir_ve_kabul_edilir(self):
		"""ÖLÇÜLDÜ: 10.450.180 B → 4.087.312 B (kazanç %60,9), SSIM 0,9956."""
		src = str(VIDEO_DIR / SISIRILMIS)
		dst = os.path.join(self.d, "c.mp4")
		r = T.transcode(src, dst)
		self.assertTrue(r.accepted, r.notes)
		self.assertGreater(r.saving_ratio, 0.5, f"olculen kazanc %60,9 idi, simdi %{r.saving_ratio*100:.1f}")
		self.assertTrue(os.path.exists(dst))

	def test_cikti_gercekten_h264_high_aac(self):
		src = str(VIDEO_DIR / SISIRILMIS)
		dst = os.path.join(self.d, "c.mp4")
		T.transcode(src, dst)
		f = P.probe(dst)
		self.assertTrue(f.measured)
		self.assertEqual(f.video_codec, "h264")
		self.assertEqual(f.video_profile, "High")
		self.assertEqual(f.pix_fmt, "yuv420p")
		self.assertEqual(f.audio_codec, "aac")
		self.assertEqual(f.container_family, "mp4")
		self.assertLessEqual(f.width, 1280)

	def test_ciktida_moov_BASTA(self):
		"""`+faststart` gerçekten çalışıyor mu — aşamalı indirmenin şartı."""
		dst = os.path.join(self.d, "c.mp4")
		T.transcode(str(VIDEO_DIR / SISIRILMIS), dst)
		self.assertFalse(P.moov_at_end_of(dst))

	def test_ses_128k_civarinda(self):
		"""ÖLÇÜLDÜ: 128.030 bps."""
		dst = os.path.join(self.d, "c.mp4")
		T.transcode(str(VIDEO_DIR / SISIRILMIS), dst)
		f = P.probe(dst)
		self.assertAlmostEqual(f.audio_bitrate_bps, 128_000, delta=8_000)

	def test_FAYDA_KAPISI_verimli_kaynagi_korur(self):
		"""INV-05'in ASIL değeri: verimli bir kaynak kapıdan GEÇEMEZ.

		**Bu testin beklentisi 2026-08-19'da DEĞİŞTİ ve sebebi kayda geçiyor.**
		Eskiden burada `saving_ratio < 0` iddiası vardı: sabit CRF 23 bu dosyayı
		1.092.127 B'den 2.007.172 B'ye ÇIKARIYORDU (%84 büyüme). Hız denetimi
		(capped CRF) eklendikten sonra kapısız çıktı artık BÜYÜMÜYOR — ölçüldü:
		%4,3 KÜÇÜLÜYOR. Yani düzeltme çalıştı.

		Kapının anlamı değişmedi: %4,3 kazanç %10 eşiğinin ALTINDA, çıktı yine
		atılır ve kaynak korunur. Test artık "büyüyor mu" değil "kapı eşiğin
		altındaki kazancı reddediyor mu" diye soruyor — asıl sözleşme buydu.

		Eski davranışın hâlâ kusurlu olduğu `test_tavansiz_CRF_verimli_kaynagi_BUYUTUYOR`
		ile ayrıca pinlenmiştir (vacuity kontrolü).
		"""
		src = str(VIDEO_DIR / VERIMLI)
		dst = os.path.join(self.d, "c.mp4")
		r = T.transcode(src, dst, enforce_benefit_gate=False)
		self.assertLess(
			r.saving_ratio,
			T.min_saving_ratio(),
			"kapisiz cikti bile esigin altinda kalmali — kaynak zaten verimli",
		)

		dst2 = os.path.join(self.d, "c2.mp4")
		r2 = T.transcode(src, dst2, enforce_benefit_gate=True)
		self.assertFalse(r2.accepted)
		self.assertTrue(r2.kept_source)
		self.assertFalse(os.path.exists(dst2), "kapiyi gecemeyen cikti DISKTE KALMAMALI")
		self.assertIn("INV-05", r2.notes[0])

	def test_fayda_kapisi_1080p_kaynakta_da_devreye_giriyor(self):
		"""Çıktı bütün kabul kapılarını geçmeden kaynak yerine konmaz.

		ffmpeg 5.1 ölçümünde tasarruf %5,6 ile INV-05'e takılıyordu. Statik
		ffmpeg 8.1 + iki x264 thread ölçümünde tasarruf %14,1'e çıktı; bu kez
		1280'e küçültmenin VMAF'ı 87,55 olduğu için 93 kalite kapısı reddetti.
		Sürümden bağımsız sözleşme şudur: fayda veya kalite kapılarından biri
		düşerse çıktı atomik olarak atılır ve kaynak korunur.
		"""
		dst = os.path.join(self.d, "c.mp4")
		r = T.transcode(str(VIDEO_DIR / BUYUK), dst)
		self.assertFalse(r.accepted)
		self.assertTrue(r.kept_source)
		self.assertFalse(os.path.exists(dst))
		self.assertGreater(r.saving_ratio, 0.0)
		if r.saving_ratio < T.min_saving_ratio():
			self.assertTrue(any("INV-05" in note for note in r.notes))
		else:
			self.assertEqual(r.quality.get("vmaf_gate"), "DUSTU")
			self.assertLess(r.quality["vmaf"], r.quality["vmaf_min"])

	def test_sessiz_kaynak_transcode_edilebiliyor(self):
		"""`-an` olmasaydı burada "Stream map matches no streams" alırdık."""
		dst = os.path.join(self.d, "c.mp4")
		r = T.transcode(str(VIDEO_DIR / SESSIZ), dst, enforce_benefit_gate=False)
		self.assertGreater(r.out_bytes, 0)
		self.assertFalse(P.probe(dst).has_audio)

	def test_kalite_olculebiliyor_ama_VMAF_YOK(self):
		"""Konteynerdeki ffmpeg libvmaf olmadan derlenmiş — ÖLÇÜLDÜ.

		Uydurma bir VMAF puanı üretilmiyor; SSIM/PSNR'a düşülüyor ve bu
		açıkça yazılıyor.
		"""
		dst = os.path.join(self.d, "c.mp4")
		T.transcode(str(VIDEO_DIR / SISIRILMIS), dst)
		k = T.measure_quality(str(VIDEO_DIR / SISIRILMIS), dst)
		self.assertTrue(k["measured"])
		if not T.vmaf_available():
			self.assertIsNone(k["vmaf"])
			self.assertIn("VMAF YOK", k["vmaf_note"])
			self.assertGreater(k["ssim"], 0.95, "olculen SSIM 0,9956 idi")
			self.assertGreater(k["psnr"], 35.0, "olculen PSNR 44,5 dB idi")

	def test_SURE_FARKI_olculuyor_ve_100ms_tavaninin_altinda(self):
		"""T-072/4 — kaynak ↔ çıktı süre farkı ≤ 100 ms.

		Bu kriter bugüne kadar HİÇ ÖLÇÜLMEMİŞTİ (`34-dogrulama-faz4-7.md` §5:
		"ne test ne kod bulundu"). Ölçüm artık her transcode sonucunda
		`quality` içinde duruyor.
		"""
		dst = os.path.join(self.d, "c.mp4")
		r = T.transcode(str(VIDEO_DIR / SISIRILMIS), dst)
		self.assertTrue(r.accepted)
		self.assertIn("duration_delta_s", r.quality)
		self.assertIsNotNone(r.quality["duration_delta_s"], "sure farki OLCULEBILMELI")
		self.assertLessEqual(r.quality["duration_delta_s"], T.max_duration_delta_s())
		self.assertEqual(r.quality["duration_gate"], "GECTI")

	def test_sure_farki_OLCULEMEZSE_uydurulmuyor(self):
		"""Ölçülemeyen fark `None` döner — "0 fark" DEĞİL."""
		self.assertIsNone(T.duration_delta_s(str(VIDEO_DIR / VERIMLI), "/yok/olan/dosya.mp4"))

	def test_yarim_dosya_diskte_kalmaz(self):
		"""ffmpeg düşerse geçici dosya temizlenir, hedefe hiçbir şey yazılmaz."""
		bozuk = os.path.join(self.d, "bozuk.mp4")
		with open(bozuk, "wb") as fh:
			fh.write(b"video degil")
		dst = os.path.join(self.d, "c.mp4")
		with self.assertRaises((ProbeUnavailable, TranscodeFailed)):
			T.transcode(bozuk, dst)
		self.assertFalse(os.path.exists(dst))
		self.assertFalse(os.path.exists(T._temp_path(dst)))


@unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe yok — konteynerde calistir")
class GercekRemux(unittest.TestCase):
	"""REMUX bugünkü hatta HİÇ YOK — bu sınıf onun değerini ölçüyor."""

	def setUp(self):
		self.d = tempfile.mkdtemp(prefix="faz7-rx-")
		self.kaynak = str(VIDEO_DIR / VERIMLI)

	def tearDown(self):
		shutil.rmtree(self.d, ignore_errors=True)

	def _moov_sonda_uret(self) -> str:
		"""faststart VERİLMEDEN yeniden paketlenmiş mp4 — moov sona düşer."""
		yol = os.path.join(self.d, "moov_sonda.mp4")
		subprocess.run(["ffmpeg", "-y", "-i", self.kaynak, "-c", "copy", yol],
			capture_output=True, check=True, timeout=120)
		return yol

	def test_moov_sonda_dosya_REMUXa_yonlendirilir(self):
		yol = self._moov_sonda_uret()
		f = P.probe(yol)
		self.assertTrue(f.moov_at_end, "sentetik kaynak moov'u sonda olmali")
		karar = decide(f)
		self.assertEqual(karar.action, ACTION_REMUX)
		self.assertEqual(karar.rule_id, "moov_at_end")

	def test_remux_moovu_basa_alir_ve_YENIDEN_KODLAMAZ(self):
		"""ÖLÇÜLDÜ: 1.092.127 B → 1.092.127 B (bayt aynı), 0,065 sn."""
		yol = self._moov_sonda_uret()
		dst = os.path.join(self.d, "c.mp4")
		r = T.remux(yol, dst)
		self.assertTrue(r.accepted)
		self.assertFalse(P.moov_at_end_of(dst))
		once, sonra = P.probe(yol), P.probe(dst)
		self.assertEqual(sonra.video_codec, once.video_codec)
		self.assertEqual((sonra.width, sonra.height), (once.width, once.height))
		self.assertAlmostEqual(r.out_bytes / r.src_bytes, 1.0, delta=0.02)

	def test_remux_fayda_kapisina_TABI_DEGIL(self):
		"""Amaç bayt kazanmak değil ilk kareyi hızlandırmak; +faststart birkaç KB büyütebilir."""
		yol = self._moov_sonda_uret()
		r = T.remux(yol, os.path.join(self.d, "c.mp4"))
		self.assertTrue(r.accepted)
		self.assertIn("MUAF", r.notes[0])

	def test_KAPIDAN_DUSEN_TRANSCODE_REMUXa_GERI_CEKILIYOR(self):
		"""B-2 — ölçülmüş kusurun düzeltmesi, gerçek ffmpeg ile.

		Kusur: kapıdan düşen TRANSCODE, aynı dosyanın REMUX ihtiyacını da
		öldürüyordu. moov sonda kalıyor, geri çekilme yolu yoktu.

		Senaryo: moov'u sonda olan VERİMLİ bir kaynak. Karar tablosu bu dosyaya
		`moov_at_end` → REMUX diyor; burada TRANSCODE kararı ZORLANIYOR (dosya
		bir TRANSCODE kuralına da takılsaydı — 60 fps, verimsiz kodlama —
		olacak olan bu). Kapı çıktıyı atmalı, hat REMUX'a geri çekilmeli ve
		moov BAŞA gelmeli.
		"""
		yol = self._moov_sonda_uret()
		f = P.probe(yol)
		self.assertTrue(f.moov_at_end)
		dst = os.path.join(self.d, "c.mp4")
		karar = decide(f)
		zorlanmis = type(karar)(
			action=ACTION_TRANSCODE,
			rule_id="__b2_senaryosu__",
			code="video_fps_over_cap",
			reason="TRANSCODE kurali tetiklenmis sayiliyor",
		)
		r = T.apply_decision(yol, dst, zorlanmis, facts=f)

		self.assertEqual(r.action, ACTION_REMUX)
		self.assertEqual(r.fallback_from, ACTION_TRANSCODE)
		self.assertTrue(r.accepted)
		self.assertTrue(os.path.exists(dst))
		self.assertFalse(P.moov_at_end_of(dst), "geri cekilmenin TEK amaci buydu")
		self.assertEqual(P.probe(dst).video_codec, f.video_codec, "REMUX yeniden kodlamaz")
		self.assertTrue(any("INV-05" in n for n in r.notes))
		self.assertTrue(any("geri cekildi" in n for n in r.notes))

	def test_geri_cekilme_KAPALIYKEN_moov_SONDA_KALIR(self):
		"""Vacuity: geri çekilme kapatılınca eski kusur geri gelir."""
		yol = self._moov_sonda_uret()
		f = P.probe(yol)
		dst = os.path.join(self.d, "c.mp4")
		karar = decide(f)
		zorlanmis = type(karar)(
			action=ACTION_TRANSCODE, rule_id="__b2__", code="x", reason="y"
		)
		gercek = T.remux_fallback_applies
		try:
			T.remux_fallback_applies = lambda *a, **k: (False, "test icin kapatildi")
			r = T.apply_decision(yol, dst, zorlanmis, facts=f)
		finally:
			T.remux_fallback_applies = gercek
		self.assertEqual(r.action, ACTION_TRANSCODE)
		self.assertFalse(r.accepted)
		self.assertEqual(r.fallback_from, "")
		self.assertFalse(os.path.exists(dst), "hedefe hicbir sey yazilmaz")
		self.assertTrue(P.probe(yol).moov_at_end, "kaynagin moov'u SONDA kalir — kusur surer")

	def test_mkv_kabi_REMUX_ile_mp4ye_tasinir(self):
		"""ÖLÇÜLDÜ: 1.086.351 B → 1.094.083 B, 0,082 sn. Tam transcode olsaydı
		aynı iş saniyeler değil dakikalar sürerdi."""
		mkv = os.path.join(self.d, "a.mkv")
		subprocess.run(["ffmpeg", "-y", "-i", self.kaynak, "-c", "copy", mkv],
			capture_output=True, check=True, timeout=120)
		f = P.probe(mkv)
		self.assertNotEqual(f.container_family, "mp4")
		karar = decide(f)
		self.assertEqual(karar.action, ACTION_REMUX)
		self.assertEqual(karar.rule_id, "container_not_mp4")
		dst = os.path.join(self.d, "c.mp4")
		T.remux(mkv, dst)
		sonra = P.probe(dst)
		self.assertEqual(sonra.container_family, "mp4")
		self.assertEqual(sonra.video_codec, "h264")


@unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe yok — konteynerde calistir")
class GercekPoster(unittest.TestCase):
	def setUp(self):
		self.d = tempfile.mkdtemp(prefix="faz7-po-")

	def tearDown(self):
		shutil.rmtree(self.d, ignore_errors=True)

	def test_yedi_fixturun_hepsinde_poster_uretiliyor(self):
		"""Poster bugün HİÇ üretilmiyor — `<video>` etiketinde `poster` yok."""
		for yol in sorted(VIDEO_DIR.glob("*.mp4")):
			with self.subTest(dosya=yol.name):
				dst = os.path.join(self.d, yol.stem + ".webp")
				r = PO.make_poster(str(yol), dst)
				self.assertTrue(os.path.exists(dst))
				self.assertGreater(r.size_bytes, 0)

	def test_poster_bayt_kapisini_geciyor(self):
		"""ÖLÇÜLDÜ: 6.202 B – 27.982 B aralığı; kapı 122.880 B."""
		for yol in sorted(VIDEO_DIR.glob("*.mp4")):
			with self.subTest(dosya=yol.name):
				dst = os.path.join(self.d, yol.stem + ".webp")
				r = PO.make_poster(str(yol), dst)
				self.assertLessEqual(r.size_bytes, 122_880, r.notes)

	def test_poster_parlaklik_kapisindan_geciyor(self):
		"""ÖLÇÜLDÜ: luma %48,6 – %50,4. Kapı %6–%94."""
		for yol in sorted(VIDEO_DIR.glob("*.mp4")):
			with self.subTest(dosya=yol.name):
				r = PO.make_poster(str(yol), os.path.join(self.d, yol.stem + ".webp"))
				self.assertGreaterEqual(r.luma_pct, 6.0)
				self.assertLessEqual(r.luma_pct, 94.0)

	def test_secilen_kare_ILK_KARE_DEGIL(self):
		""""İlk kare" kötü bir tanım: açılış genelde siyah bir geçiştir.

		ÖLÇÜLDÜ: seçilen damgalar 0,92 – 2,60 sn arası — hiçbiri 0 değil.
		"""
		for yol in sorted(VIDEO_DIR.glob("*.mp4")):
			with self.subTest(dosya=yol.name):
				r = PO.make_poster(str(yol), os.path.join(self.d, yol.stem + ".webp"))
				self.assertGreater(r.timestamp_s, 0.0)
				pencere = PO.poster_window(P.probe(str(yol)).duration_s)
				self.assertGreaterEqual(r.timestamp_s, pencere[0] - 0.01)

	def test_poster_belirlenimci(self):
		"""Aynı kaynak → aynı kare. `thumbnail` filtresinde rastgelelik yok."""
		yol = str(VIDEO_DIR / VERIMLI)
		a = PO.make_poster(yol, os.path.join(self.d, "a.webp"))
		b = PO.make_poster(yol, os.path.join(self.d, "b.webp"))
		self.assertAlmostEqual(a.timestamp_s, b.timestamp_s, places=3)
		self.assertEqual(a.size_bytes, b.size_bytes)

	def test_olculemeyen_kaynakta_poster_unresolved(self):
		bozuk = os.path.join(self.d, "bozuk.mp4")
		with open(bozuk, "wb") as fh:
			fh.write(b"video degil")
		with self.assertRaises(TranscodeFailed) as c:
			PO.make_poster(bozuk, os.path.join(self.d, "c.webp"))
		self.assertEqual(c.exception.kod, PO.CODE_POSTER_UNRESOLVED)


@unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe yok — konteynerde calistir")
class GercekOnizlemeKlibi(unittest.TestCase):
	def setUp(self):
		self.d = tempfile.mkdtemp(prefix="faz7-cl-")

	def tearDown(self):
		shutil.rmtree(self.d, ignore_errors=True)

	def test_klip_1MB_kapisini_geciyor(self):
		"""ÖLÇÜLDÜ (poster damgasından başlatılarak): 80.857 B – 354.571 B.
		Görev tanımı kapısı 1.048.576 B."""
		for yol in sorted(VIDEO_DIR.glob("*.mp4")):
			with self.subTest(dosya=yol.name):
				r = PO.make_preview_clip(str(yol), os.path.join(self.d, yol.stem + ".mp4"))
				self.assertTrue(r.within_task_gate, r.notes)
				self.assertLessEqual(r.size_bytes, 1_048_576)

	def test_klip_politika_hedefini_de_tutturuyor(self):
		"""ÖLÇÜLDÜ: 7/7 fixture 400 KB politika hedefinin de altında — en büyüğü
		dikey 9:16 klibi, 354.571 B. Kısa kenar bütçesi düzeltilmeden ÖNCE aynı
		dosya 842.115 B çıkıyordu (bkz. `test_klip_olcegi_KISA_KENAR_butcesi`)."""
		for yol in sorted(VIDEO_DIR.glob("*.mp4")):
			with self.subTest(dosya=yol.name):
				r = PO.make_preview_clip(str(yol), os.path.join(self.d, yol.stem + ".mp4"))
				self.assertTrue(r.within_policy_gate, f"{r.size_bytes} B > 409.600 B")

	def test_klip_sessiz(self):
		dst = os.path.join(self.d, "c.mp4")
		PO.make_preview_clip(str(VIDEO_DIR / VERIMLI), dst)
		self.assertFalse(P.probe(dst).has_audio)

	def test_klip_suresi_3_6_sn_araliginda(self):
		"""ÖLÇÜLDÜ: 5,08 – 6,00 sn. 3 sn altına İNMEZ."""
		for yol in sorted(VIDEO_DIR.glob("*.mp4")):
			with self.subTest(dosya=yol.name):
				r = PO.make_preview_clip(str(yol), os.path.join(self.d, yol.stem + ".mp4"))
				self.assertGreaterEqual(r.duration_s, 3.0)
				self.assertLessEqual(r.duration_s, 6.0)

	def test_klip_posterin_damgasindan_basliyor(self):
		"""Görsel süreklilik: hover'da görülen ilk kare, poster'da görülen kare."""
		yol = str(VIDEO_DIR / VERIMLI)
		p = PO.make_poster(yol, os.path.join(self.d, "p.webp"))
		c = PO.make_preview_clip(yol, os.path.join(self.d, "c.mp4"), start_s=p.timestamp_s)
		self.assertAlmostEqual(c.start_s, p.timestamp_s, places=3)

	def test_kisa_kaynakta_baslangic_one_cekilir(self):
		"""6 sn'lik kaynakta 5. saniyeden 3 sn'lik klip çıkmaz — başlangıç kayar."""
		yol = str(VIDEO_DIR / KARE)
		r = PO.make_preview_clip(yol, os.path.join(self.d, "c.mp4"), start_s=5.0)
		self.assertLess(r.start_s, 5.0)
		self.assertGreater(r.duration_s, 0.0)


@unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe yok — konteynerde calistir")
class GercekHls(unittest.TestCase):
	"""HLS bugün HİÇ YOK (storefront + panelde `hls` araması 0 eşleşme)."""

	def setUp(self):
		self.d = tempfile.mkdtemp(prefix="faz7-hls-")

	def tearDown(self):
		shutil.rmtree(self.d, ignore_errors=True)

	def test_1080p_kaynakta_dort_basamak_uretiliyor(self):
		"""ÖLÇÜLDÜ: 360p 281.069 B · 480p 476.025 B · 720p 1.109.961 B · 1080p 2.212.017 B."""
		r = H.make_hls(str(VIDEO_DIR / BUYUK), os.path.join(self.d, "o"))
		self.assertEqual([v.name for v in r.variants], ["360p", "480p", "720p", "1080p"])
		for v in r.variants:
			self.assertGreater(v.segment_count, 0, f"{v.name}: segment uretilmedi")
			self.assertGreater(v.bytes_total, 0, f"{v.name}: bayt 0 — dizin yolu yanlis olabilir")

	def test_720p_kaynakta_1080p_basamagi_URETILMEZ(self):
		"""Büyütme yok. Master playlist'te 1080p satırı OLMAMALI."""
		r = H.make_hls(str(VIDEO_DIR / VERIMLI), os.path.join(self.d, "o"))
		self.assertEqual([v.name for v in r.variants], ["360p", "480p", "720p"])
		cozunurlukler = [s.get("RESOLUTION") for s in H.parse_master(r.master_path)]
		self.assertNotIn("1920x1080", cozunurlukler)
		self.assertEqual(cozunurlukler, ["640x360", "854x480", "1280x720"])

	def test_dikey_kaynakta_basamaklar_dondurulur(self):
		"""ÖLÇÜLDÜ: 720×1280 kaynak → 360×640, 480×854, 720×1280."""
		r = H.make_hls(str(VIDEO_DIR / DIKEY), os.path.join(self.d, "o"))
		cozunurlukler = [s.get("RESOLUTION") for s in H.parse_master(r.master_path)]
		self.assertEqual(cozunurlukler, ["360x640", "480x854", "720x1280"])

	def test_kucuk_kaynakta_tek_basamak(self):
		"""352×352 kaynak 360p'ye BÜYÜTÜLMEZ — kendi ölçüsünde tek basamak."""
		r = H.make_hls(str(VIDEO_DIR / KARE), os.path.join(self.d, "o"))
		self.assertEqual(len(r.variants), 1)
		self.assertEqual([s.get("RESOLUTION") for s in H.parse_master(r.master_path)], ["352x352"])

	def test_segment_suresi_GOP_ile_hizali(self):
		"""ÖLÇÜLDÜ: TARGETDURATION 4 — istenen segment süresiyle AYNI.

		Hizasız olsaydı ffmpeg segmenti bir sonraki anahtar kareye kadar uzatır
		ve TARGETDURATION 4'ten büyük çıkardı.
		"""
		r = H.make_hls(str(VIDEO_DIR / VERIMLI), os.path.join(self.d, "o"))
		for v in r.variants:
			with self.subTest(basamak=v.name):
				self.assertEqual(v.target_duration_s, 4.0)

	def test_master_playlist_var_ve_ayristirilabiliyor(self):
		r = H.make_hls(str(VIDEO_DIR / VERIMLI), os.path.join(self.d, "o"))
		self.assertTrue(os.path.exists(r.master_path))
		akislar = H.parse_master(r.master_path)
		self.assertEqual(len(akislar), len(r.variants))
		for a in akislar:
			self.assertTrue(a["URI"].endswith("playlist.m3u8"))
			self.assertTrue(int(a["BANDWIDTH"]) > 0)

	def test_en_dusuk_basamak_3G_icin_gercek_kazanc(self):
		"""HLS'in ASIL değeri: 3G'deki alıcı en düşük basamağı indirir.

		ÖLÇÜLDÜ (capped CRF): şişirilmiş 720p kaynağın 10.450.180 baytına karşı
		360p basamağı 708.609 bayt — %93 daha az.
		"""
		f = P.probe(str(VIDEO_DIR / SISIRILMIS))
		r = H.make_hls(str(VIDEO_DIR / SISIRILMIS), os.path.join(self.d, "o"), facts=f)
		en_dusuk = r.lowest
		self.assertIsNotNone(en_dusuk)
		self.assertLess(en_dusuk.bytes_total, f.size_bytes * 0.2)

	def test_sessiz_kaynakta_hls_uretilebiliyor(self):
		"""Ses akışı olmayan kaynakta `a:` eşlemesi yazılsaydı ffmpeg düşerdi."""
		r = H.make_hls(str(VIDEO_DIR / SESSIZ), os.path.join(self.d, "o"))
		self.assertEqual(len(r.variants), 3)
		for v in r.variants:
			self.assertGreater(v.bytes_total, 0)

	def test_MOBIL_VERI_TAVANI_ilk_10_saniye_olculuyor(self):
		"""T-074/3 — ilk 10 saniyede inen bayt, basamak başına.

		Bu kriter bugüne kadar HİÇ ÖLÇÜLMEMİŞTİ (`34-dogrulama-faz4-7.md`:
		"ne test ne kod var"). En yakın ölçüm TOPLAM baytı sayıyordu — o,
		mobil veri tavanının sorduğu soru değil.

		Tavan `company-cover-video.json` `video.mobile_data_budget`'tan
		geliyor: 1.250 KB = 1.280.000 bayt.
		"""
		spec = H.HlsSpec.from_table()
		self.assertEqual(spec.startup_window_s, 10.0)
		self.assertEqual(spec.startup_max_bytes, 1_280_000)

		r = H.make_hls(str(VIDEO_DIR / UZUN), os.path.join(self.d, "o"))
		for v in r.variants:
			with self.subTest(basamak=v.name):
				self.assertGreater(v.startup_segments, 0, "acilis segmenti sayilmadi")
				self.assertGreaterEqual(v.startup_covered_s, 10.0, "pencere dolmadan durulmus")
				self.assertLess(v.startup_bytes, v.bytes_total, "acilis TOPLAM degildir")
				self.assertEqual(v.startup_gate, "GECTI", f"{v.name}: {v.startup_bytes} B > 1.280.000 B")

	def test_acilis_bayti_TOPLAM_bayttan_farkli(self):
		"""Ölçünün varlık sebebi: 540 sn'lik bir pakette ikisi aynı şey değil."""
		r = H.make_hls(str(VIDEO_DIR / UZUN), os.path.join(self.d, "o"))
		en_dusuk = r.variants[0]
		self.assertLess(
			en_dusuk.startup_bytes,
			en_dusuk.bytes_total * 0.25,
			"540 sn'lik pakette ilk 10 sn toplamin kucuk bir kismi olmali",
		)

	def test_pencereyi_ASAN_segment_de_sayiliyor(self):
		"""Oynatıcı segmenti bölemez: 4 sn'lik segmentlerle 10 sn = 3 segment (12 sn)."""
		r = H.make_hls(str(VIDEO_DIR / UZUN), os.path.join(self.d, "o"))
		v = r.variants[0]
		self.assertGreaterEqual(v.startup_covered_s, 10.0)
		self.assertLessEqual(v.startup_covered_s, 10.0 + v.target_duration_s)

	def test_uzun_video_HLS_GEREKTIRIYOR(self):
		"""540 sn > 60 sn eşiği — `required_if_any` süre koşulu tetikleniyor."""
		f = P.probe(str(VIDEO_DIR / UZUN))
		g = H.hls_required(f)
		self.assertTrue(g.required)
		self.assertTrue(any("sure" in s for s in g.reasons))

	def test_capped_crf_sabit_bitrateten_daha_az_bayt_uretiyor(self):
		"""Hız denetimi değişikliğinin GEREKÇESİ — iki kip yan yana ölçülüyor.

		ÖLÇÜLDÜ: verimli 720p kaynakta 360p basamağı
		sabit bitrate 1.155.673 B → capped CRF 688.869 B.
		"""
		src = str(VIDEO_DIR / VERIMLI)
		crf = H.make_hls(src, os.path.join(self.d, "crf"))
		cbr_spec = H.HlsSpec.from_table({**default_table().hls, "rate_control": "cbr"})
		cbr = H.make_hls(src, os.path.join(self.d, "cbr"), spec=cbr_spec)
		self.assertLess(crf.bytes_total, cbr.bytes_total)
		self.assertLess(crf.lowest.bytes_total, cbr.lowest.bytes_total)

	def test_olculemeyen_kaynakta_hls_probeunavailable(self):
		bozuk = os.path.join(self.d, "bozuk.mp4")
		with open(bozuk, "wb") as fh:
			fh.write(b"video degil")
		with self.assertRaises(ProbeUnavailable):
			H.make_hls(bozuk, os.path.join(self.d, "o"))


if __name__ == "__main__":
	unittest.main(verbosity=2)

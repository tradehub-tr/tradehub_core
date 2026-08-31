"""KD-04 — Video motoru: karar tablosu, bitrate tavanı, fayda/kalite/teslim kapıları.

Kaynak okundu:
  * `media/pipeline/video/decision.py` (370)   — kural motoru + yükleme doğrulaması
  * `media/pipeline/video/transcode.py` (1140) — komut kurulumu + üç kapı
  * `media/pipeline/policy/video_decision.json` — 15 kural + hedefler
  * `media/pipeline/video/probe.py` (563)      — VideoFacts sözleşmesi

ORTAM NOTU: bu container'da `ffmpeg`/`ffprobe` KURULU DEĞİL. Bu yüzden:
  * saf karar/geometri/bütçe fonksiyonları GERÇEKTEN koşturulur,
  * dış süreç gerektiren yollar (`transcode`, `remux`) sahte `_run` ile
    koşturulur — kapı mantığı ölçülür, kodlayıcı çıktısı değil.
Ne test edildiği her testin adında ve docstring'inde açıktır; ffmpeg'e
ihtiyaç duyan hiçbir test "sessizce geçmiş" görünmez, `skipTest` ile
raporlanır.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from tradehub_core.media.pipeline.video import decision as kr
from tradehub_core.media.pipeline.video import transcode as tc
from tradehub_core.media.pipeline.video.probe import VideoFacts


def _facts(**kw) -> VideoFacts:
	"""Teslim edilebilir bir taban künye — testler yalnız farkı yazar."""
	temel = dict(
		path="/tmp/x.mp4",
		size_bytes=10_000_000,
		measured=True,
		has_video=True,
		width=1280,
		height=720,
		duration_s=30.0,
		fps=30.0,
		video_codec="h264",
		pix_fmt="yuv420p",
		video_bitrate_bps=1_500_000,
		format_bitrate_bps=1_650_000,
		container="mov,mp4,m4a,3gp,3g2,mj2",
		container_family="mp4",
		nb_streams=2,
		moov_at_end=False,
		has_audio=True,
		audio_codec="aac",
		audio_bitrate_bps=128_000,
		audio_channels=2,
		audio_sample_rate=48000,
	)
	temel.update(kw)
	return VideoFacts(**temel)


# ══════════════════════════════════════════════════════════════════════
# 1. Karar tablosu — kural motoru
# ══════════════════════════════════════════════════════════════════════


class TestKararTablosu(unittest.TestCase):
	def test_bi_tablo_yuklenir_ve_dogrulanir(self):
		t = kr.default_table()
		self.assertTrue(t.rules, "tablo boş")
		self.assertEqual(t.default_action, kr.ACTION_PASSTHROUGH)
		self.assertTrue(t.schema_version)

	def test_bi_temiz_kaynak_passthrough(self):
		k = kr.decide(_facts())
		self.assertEqual(k.action, kr.ACTION_PASSTHROUGH)
		self.assertFalse(k.writes_new_file)
		self.assertFalse(k.needs_ffmpeg)
		self.assertFalse(k.rejected)

	def test_bi_olculemeyen_kunye_reddedilir(self):
		k = kr.decide(_facts(measured=False))
		self.assertEqual(k.action, kr.ACTION_REJECT)
		self.assertEqual(k.code, "video_probe_failed")
		self.assertTrue(k.rejected)

	def test_bi_video_akisi_yoksa_reddedilir(self):
		k = kr.decide(_facts(has_video=False))
		self.assertEqual(k.code, "video_no_stream")

	def test_sn_cozunurluk_tavani_sinirlari(self):
		# 3840×2160 tam sınırda → RET YOK
		self.assertNotEqual(kr.decide(_facts(width=3840, height=2160)).code, "video_resolution_over_max")
		# 3841 → RET
		self.assertEqual(kr.decide(_facts(width=3841, height=2160)).code, "video_resolution_over_max")
		self.assertEqual(kr.decide(_facts(width=3840, height=2161)).code, "video_resolution_over_max")

	def test_sn_sure_tavani_sinirlari(self):
		self.assertNotEqual(kr.decide(_facts(duration_s=900.0)).code, "video_duration_over_max")
		self.assertEqual(kr.decide(_facts(duration_s=900.01)).code, "video_duration_over_max")

	def test_bi_ret_kurallari_transcode_kurallarindan_once(self):
		"""Sıra anlamlı: 4K + VP9 kaynakta RET kazanmalı, TRANSCODE değil."""
		k = kr.decide(_facts(width=4000, height=2200, video_codec="vp9"))
		self.assertEqual(k.action, kr.ACTION_REJECT)

	def test_bi_transcode_kurallari(self):
		durumlar = {
			"video_codec_not_deliverable": _facts(video_codec="vp9"),
			"video_pix_fmt_not_web": _facts(pix_fmt="yuv444p"),
			"video_width_over_cap": _facts(width=1920, height=1080),
			"video_bitrate_over_cap": _facts(video_bitrate_bps=2_500_001),
			"video_fps_over_cap": _facts(fps=60.0),
			"video_audio_codec_not_deliverable": _facts(audio_codec="opus"),
			"video_audio_bitrate_over_cap": _facts(audio_bitrate_bps=192_001),
		}
		for kod, f in durumlar.items():
			with self.subTest(kod=kod):
				k = kr.decide(f)
				self.assertEqual(k.action, kr.ACTION_TRANSCODE)
				self.assertEqual(k.code, kod)
				self.assertTrue(k.writes_new_file)
				self.assertTrue(k.needs_ffmpeg)

	def test_sn_bitrate_tavani_tam_sinirda_kural_tetiklenmez(self):
		"""`gt 2500000` — tam sınır bu kuralı TETİKLEMEZ.

		Dikkat: 1280×720/30 fps'te 2,5 Mbps aynı anda `bpp > 0,08` +
		`bitrate > 1,2 Mbps` koşullarını sağladığı için `inefficient_encoding`
		kuralı devreye girer ve sonuç yine TRANSCODE olur. Ölçülen şey bu
		kuralın sınırı, kararın kendisi değil — bu yüzden kod karşılaştırılıyor.
		"""
		k = kr.decide(_facts(video_bitrate_bps=2_500_000))
		self.assertNotEqual(k.code, "video_bitrate_over_cap")
		k2 = kr.decide(_facts(video_bitrate_bps=2_500_001))
		self.assertEqual(k2.code, "video_bitrate_over_cap")

	def test_sn_fps_tam_30_gecer(self):
		self.assertEqual(kr.decide(_facts(fps=30.0)).action, kr.ACTION_PASSTHROUGH)

	def test_bi_verimsiz_kodlama_iki_kosul_birlikte(self):
		"""`bpp > 0,08` VE `video_bitrate > 1,2 Mbps` — biri tek başına yetmez."""
		# bpp yüksek ama bitrate düşük → kural TETİKLENMEZ
		f_dusuk = _facts(width=320, height=240, fps=30.0, video_bitrate_bps=1_000_000)
		self.assertGreater(f_dusuk.bpp, 0.08)
		self.assertNotEqual(kr.decide(f_dusuk).code, "video_inefficient_encoding")
		# ikisi birden → tetiklenir
		f_yuksek = _facts(width=320, height=240, fps=30.0, video_bitrate_bps=1_300_000)
		self.assertEqual(kr.decide(f_yuksek).code, "video_inefficient_encoding")

	def test_bi_remux_kurallari(self):
		self.assertEqual(kr.decide(_facts(container_family="matroska")).action, kr.ACTION_REMUX)
		self.assertEqual(kr.decide(_facts(moov_at_end=True)).action, kr.ACTION_REMUX)
		self.assertEqual(kr.decide(_facts(nb_streams=3)).code, "video_extra_streams")

	def test_bi_transcode_remuxtan_once_gelir(self):
		"""Hem kap kusuru hem codec kusuru varsa TRANSCODE kazanır (sıra)."""
		k = kr.decide(_facts(container_family="matroska", video_codec="vp9"))
		self.assertEqual(k.action, kr.ACTION_TRANSCODE)

	def test_bi_karar_izi_tasiniyor(self):
		k = kr.decide(_facts(video_codec="vp9"))
		self.assertTrue(k.trace, "kural izi boş")
		bakilan = dict(k.trace)
		self.assertIn("codec_not_deliverable", bakilan)
		self.assertTrue(bakilan["codec_not_deliverable"])

	def test_bi_as_dict_sozlesmesi(self):
		d = kr.decide(_facts()).as_dict()
		self.assertEqual(
			set(d), {"action", "rule_id", "code", "reason", "writes_new_file"}
		)

	def test_bi_writes_new_file_haritasi(self):
		self.assertFalse(kr.WRITES_NEW_FILE.get(kr.ACTION_PASSTHROUGH, False))
		self.assertFalse(kr.WRITES_NEW_FILE.get(kr.ACTION_REJECT, False))
		self.assertTrue(kr.WRITES_NEW_FILE[kr.ACTION_REMUX])
		self.assertTrue(kr.WRITES_NEW_FILE[kr.ACTION_TRANSCODE])


class TestTabloDogrulamasi(unittest.TestCase):
	"""Bozuk tablo ÇALIŞMA ZAMANINDA değil, YÜKLEMEDE patlamalı."""

	def _tablo(self, kurallar, **ustune):
		veri = {"schema_version": "1.0.0", "rules": kurallar, "targets": {}}
		veri.update(ustune)
		return kr.DecisionTable(veri, kaynak="test")

	def test_gv_bilinmeyen_degisken_yuklemede_patlar(self):
		with self.assertRaises(kr.DecisionTableError) as c:
			self._tablo([{"id": "x", "action": "REJECT", "when": {"var": "uydurma", "op": "eq", "value": 1}}])
		self.assertIn("uydurma", str(c.exception))

	def test_gv_bilinmeyen_operator(self):
		with self.assertRaises(kr.DecisionTableError):
			self._tablo([{"id": "x", "action": "REJECT", "when": {"var": "width", "op": "regex", "value": 1}}])

	def test_gv_bilinmeyen_aksiyon(self):
		with self.assertRaises(kr.DecisionTableError):
			self._tablo([{"id": "x", "action": "SIL", "when": {"var": "width", "op": "gt", "value": 1}}])

	def test_gv_tekrar_eden_kural_id(self):
		kural = {"id": "x", "action": "REJECT", "when": {"var": "width", "op": "gt", "value": 1}}
		with self.assertRaises(kr.DecisionTableError):
			self._tablo([kural, dict(kural)])

	def test_gv_id_siz_kural(self):
		with self.assertRaises(kr.DecisionTableError):
			self._tablo([{"action": "REJECT", "when": {"var": "width", "op": "gt", "value": 1}}])

	def test_gv_bos_all_listesi(self):
		with self.assertRaises(kr.DecisionTableError):
			self._tablo([{"id": "x", "action": "REJECT", "when": {"all": []}}])

	def test_gv_yaprakta_var_op_zorunlu(self):
		with self.assertRaises(kr.DecisionTableError):
			self._tablo([{"id": "x", "action": "REJECT", "when": {"value": 1}}])

	def test_gv_tip_uyusmazligi_sessizce_false_donmez(self):
		"""Metin ile sayı karşılaştırması kuralı ÖLÜ bırakmamalı, patlamalı."""
		t = self._tablo([{"id": "x", "action": "REJECT", "when": {"var": "width", "op": "gt", "value": "abc"}}])
		with self.assertRaises(kr.DecisionTableError):
			t.evaluate(_facts())

	def test_bi_not_operatoru(self):
		t = self._tablo(
			[{"id": "x", "action": "REJECT", "when": {"not": {"var": "has_audio", "op": "eq", "value": True}}}]
		)
		self.assertEqual(t.evaluate(_facts(has_audio=False)).action, kr.ACTION_REJECT)
		self.assertEqual(t.evaluate(_facts(has_audio=True)).action, kr.ACTION_PASSTHROUGH)

	def test_bi_in_operatoru_bos_listede_patlamaz(self):
		t = self._tablo([{"id": "x", "action": "REJECT", "when": {"var": "video_codec", "op": "in", "value": None}}])
		self.assertEqual(t.evaluate(_facts()).action, kr.ACTION_PASSTHROUGH)


# ══════════════════════════════════════════════════════════════════════
# 2. Bitrate bütçesi — kapıdan türetilen tavan
# ══════════════════════════════════════════════════════════════════════


class TestBitrateTavani(unittest.TestCase):
	def test_bi_kunye_yoksa_mutlak_tavan(self):
		spec = tc.H264Spec()
		self.assertEqual(tc.rate_ceiling_kbps(spec, None), spec.maxrate_kbps)

	def test_bi_kapi_kapaliysa_mutlak_tavan(self):
		spec = tc.H264Spec(budget_from_benefit_gate=False)
		self.assertEqual(tc.rate_ceiling_kbps(spec, _facts(format_bitrate_bps=800_000)), spec.maxrate_kbps)

	def test_bi_butce_kapidan_turetiliyor(self):
		"""tavan = kaynak_kbps × (1 − min_saving) − çıktı_ses_kbps."""
		spec = tc.H264Spec()
		f = _facts(format_bitrate_bps=2_000_000)  # 2000 kbps
		beklenen = int(round(2000 * (1 - tc.min_saving_ratio()))) - spec.audio_bitrate_kbps
		self.assertEqual(tc.rate_ceiling_kbps(spec, f), min(spec.maxrate_kbps, beklenen))

	def test_bi_sessiz_kaynakta_ses_payi_dusulmez(self):
		spec = tc.H264Spec()
		f_sesli = _facts(format_bitrate_bps=2_000_000, has_audio=True)
		f_sessiz = _facts(format_bitrate_bps=2_000_000, has_audio=False)
		self.assertEqual(
			tc.rate_ceiling_kbps(spec, f_sessiz) - tc.rate_ceiling_kbps(spec, f_sesli),
			spec.audio_bitrate_kbps,
		)

	def test_sn_taban_altina_inmez(self):
		spec = tc.H264Spec()
		f = _facts(format_bitrate_bps=200_000)  # 200 kbps → bütçe negatife yakın
		self.assertEqual(tc.rate_ceiling_kbps(spec, f), spec.min_maxrate_kbps)

	def test_sn_mutlak_tavan_asilamaz(self):
		spec = tc.H264Spec()
		f = _facts(format_bitrate_bps=50_000_000)
		self.assertEqual(tc.rate_ceiling_kbps(spec, f), spec.maxrate_kbps)

	def test_sn_bitrate_olculemezse_mutlak_tavan(self):
		spec = tc.H264Spec()
		f = _facts(format_bitrate_bps=0, video_bitrate_bps=0, audio_bitrate_bps=0)
		self.assertEqual(tc.rate_ceiling_kbps(spec, f), spec.maxrate_kbps)

	def test_bi_format_bitrate_yoksa_akislardan_toplanir(self):
		spec = tc.H264Spec()
		f = _facts(format_bitrate_bps=0, video_bitrate_bps=1_000_000, audio_bitrate_bps=128_000)
		self.assertNotEqual(tc.rate_ceiling_kbps(spec, f), spec.maxrate_kbps)


# ══════════════════════════════════════════════════════════════════════
# 3. ffmpeg komut kurulumu — saf dizge üretimi
# ══════════════════════════════════════════════════════════════════════


class TestKomutKurulumu(unittest.TestCase):
	def _cmd(self, **kw) -> list[str]:
		return tc.build_transcode_cmd("/tmp/a.mp4", "/tmp/b.mp4", tc.H264Spec(), _facts(**kw), nice=False)

	def test_gv_scale_filtresi_tirnakli(self):
		"""Tırnak kaybolursa filtergraph virgülde kırılır — regresyon kilidi."""
		self.assertEqual(tc._scale_filter(1280), "scale='min(1280,iw)':-2")

	def test_bi_buyutme_yapmaz(self):
		"""`min(max_width, iw)` — kaynak dardan geniş yapılmaz."""
		self.assertIn("min(1280,iw)", tc._scale_filter(1280))

	def test_bi_fps_capi_yalniz_asildiginda(self):
		f_yuksek = tc._video_filters(tc.H264Spec(), _facts(fps=60.0))
		f_normal = tc._video_filters(tc.H264Spec(), _facts(fps=30.0))
		self.assertTrue(any(x.startswith("fps=") for x in f_yuksek))
		self.assertFalse(any(x.startswith("fps=") for x in f_normal))

	def test_bi_hdr_kaynak_tonemap_edilir(self):
		f = tc._video_filters(tc.H264Spec(), _facts(is_hdr=True))
		self.assertTrue(any("tonemap" in x for x in f), f)
		self.assertTrue(any("bt709" in x for x in f), f)

	def test_bi_sessiz_kaynakta_ses_kodlayici_yazilmaz(self):
		cmd = self._cmd(has_audio=False)
		self.assertIn("-an", cmd)
		self.assertNotIn("aac", cmd)

	def test_bi_sesli_kaynakta_aac_yazilir(self):
		cmd = self._cmd(has_audio=True)
		self.assertIn("aac", cmd)
		self.assertNotIn("-an", cmd)

	def test_bi_capped_crf_maxrate_ve_bufsize_yazar(self):
		args = tc._rate_control_args(tc.H264Spec(), _facts(format_bitrate_bps=2_000_000))
		self.assertIn("-maxrate", args)
		self.assertIn("-bufsize", args)
		self.assertIn("-crf", args)

	def test_bi_rate_control_crf_tavansiz(self):
		args = tc._rate_control_args(tc.H264Spec(rate_control="crf"), _facts())
		self.assertEqual(args, ["-crf", "23"])

	def test_bi_bufsize_maxrateden_kucuk_olamaz(self):
		spec = tc.H264Spec(bufsize_multiplier=0.5)
		args = tc._rate_control_args(spec, _facts(format_bitrate_bps=2_000_000))
		tavan = int(args[args.index("-maxrate") + 1].rstrip("k"))
		tampon = int(args[args.index("-bufsize") + 1].rstrip("k"))
		self.assertGreaterEqual(tampon, tavan)

	def test_bi_faststart_ve_pix_fmt(self):
		cmd = self._cmd()
		self.assertIn("+faststart", cmd)
		self.assertIn("yuv420p", cmd)

	def test_bi_nice_prefix_secilebilir(self):
		with_nice = tc.build_transcode_cmd("/a", "/b", tc.H264Spec(), _facts(), nice=True)
		self.assertEqual(with_nice[: len(tc.NICE_PREFIX)], list(tc.NICE_PREFIX))
		self.assertNotEqual(self._cmd()[0], "nice")

	def test_gv_kaynak_ve_hedef_yollar_argv_olarak_gecer(self):
		"""Kabuk yok: yol argv elemanı olmalı, dizgeye gömülmemeli (enjeksiyon)."""
		kotu = "/tmp/a b;rm -rf /.mp4"
		cmd = tc.build_transcode_cmd(kotu, "/tmp/out.mp4", tc.H264Spec(), _facts(), nice=False)
		self.assertIn(kotu, cmd)
		self.assertTrue(all(isinstance(x, str) for x in cmd))

	def test_bi_remux_komutu_kopyalar(self):
		cmd = tc.build_remux_cmd("/a.mkv", "/b.mp4", nice=False)
		self.assertIn("-c", cmd)
		self.assertIn("copy", cmd)
		self.assertIn("+faststart", cmd)


# ══════════════════════════════════════════════════════════════════════
# 4. Teslim bütünlüğü kapısı — saf değerlendirme
# ══════════════════════════════════════════════════════════════════════


class TestTeslimKapisi(unittest.TestCase):
	def test_bi_hepsi_gecerse_gecer(self):
		ok, r = tc.validate_delivery_metrics(
			duration_delta=0.01, av_sync_delta=0.02, first_frame_luma=50.0, has_audio=True
		)
		self.assertTrue(ok)
		self.assertEqual(r["duration_gate"], "GECTI")
		self.assertEqual(r["av_sync_gate"], "GECTI")
		self.assertEqual(r["first_frame_gate"], "GECTI")

	def test_sn_sure_farki_tam_sinirda_gecer(self):
		ok, r = tc.validate_delivery_metrics(
			duration_delta=tc.max_duration_delta_s(), av_sync_delta=0.0,
			first_frame_luma=50.0, has_audio=True,
		)
		self.assertTrue(ok)
		self.assertEqual(r["duration_gate"], "GECTI")

	def test_sn_sure_farki_sinirin_ustunde_duser(self):
		ok, r = tc.validate_delivery_metrics(
			duration_delta=tc.max_duration_delta_s() + 0.001, av_sync_delta=0.0,
			first_frame_luma=50.0, has_audio=True,
		)
		self.assertFalse(ok)
		self.assertEqual(r["duration_gate"], "DUSTU")

	def test_bi_sessiz_kaynakta_av_sync_uygulanmaz(self):
		ok, r = tc.validate_delivery_metrics(
			duration_delta=0.0, av_sync_delta=None, first_frame_luma=50.0, has_audio=False
		)
		self.assertTrue(ok)
		self.assertEqual(r["av_sync_gate"], "UYGULANMAZ")

	def test_gv_olculemeyen_metrik_uretim_yolunda_kapiyi_dusurur(self):
		"""`None` "sorun yok" DEĞİL — ölçülemeyen zorunlu metrik ret sebebi."""
		ok, r = tc.validate_delivery_metrics(
			duration_delta=None, av_sync_delta=0.0, first_frame_luma=50.0, has_audio=True
		)
		self.assertFalse(ok)
		self.assertEqual(r["duration_gate"], "OLCULEMEDI")

	def test_bi_olcum_zorunlulugu_kapatilabilir(self):
		ok, _ = tc.validate_delivery_metrics(
			duration_delta=None, av_sync_delta=0.0, first_frame_luma=50.0,
			has_audio=True, require_measured=False,
		)
		self.assertTrue(ok)

	def test_sn_ilk_kare_siyah_beyaz_sinirlari(self):
		alt, ust = tc.first_frame_luma_range()
		for deger, beklenen in ((alt, True), (ust, True), (alt - 0.1, False), (ust + 0.1, False)):
			with self.subTest(luma=deger):
				ok, _ = tc.validate_delivery_metrics(
					duration_delta=0.0, av_sync_delta=0.0, first_frame_luma=deger, has_audio=True
				)
				self.assertEqual(ok, beklenen)

	def test_bi_av_sync_kaynak_sessizse_uygulanmaz_bayragi(self):
		s = tc.av_sync_from_facts(_facts(has_audio=False), _facts(has_audio=False))
		self.assertTrue(s.get("not_applicable"))

	def test_gv_cikti_sesi_kaybolursa_sonsuz_sapma(self):
		"""Ses kaynakta var, çıktıda yoksa bu sonsuz sapma sayılmalı."""
		s = tc.av_sync_from_facts(_facts(has_audio=True), _facts(has_audio=False))
		self.assertTrue(s.get("audio_missing"))
		self.assertEqual(s["max_delta_s"], float("inf"))


# ══════════════════════════════════════════════════════════════════════
# 5. Fayda kapısı (INV-05) — sahte ffmpeg ile uçtan uca kapı davranışı
# ══════════════════════════════════════════════════════════════════════


class _SahteKosum:
	peak_rss_bytes = 1024
	cpu_user_s = 0.1
	cpu_system_s = 0.05
	limits_applied = ()


class TestFaydaKapisi(unittest.TestCase):
	"""`transcode()` üç kapısı: fayda → kalite → teslim.

	ffmpeg yok; `_run` sahtelenip geçici dosyaya istenen boyutta içerik
	yazılıyor. Ölçülen şey KAPI KARARIDIR, kodlayıcı çıktısı değil.
	"""

	def _kos(self, *, src_bytes: int, out_bytes: int, vmaf=None, teslim_ok=True, **tk):
		d = tempfile.mkdtemp(prefix="kd04-")
		src = os.path.join(d, "kaynak.mp4")
		dst = os.path.join(d, "cikti.mp4")
		with open(src, "wb") as fh:
			fh.write(b"\x00" * src_bytes)

		def sahte_run(cmd, **kw):
			# ffmpeg'in yapacağı işi taklit et: geçici hedefe yaz.
			hedef = cmd[-1]
			with open(hedef, "wb") as fh:
				fh.write(b"\x00" * out_bytes)
			return _SahteKosum()

		kalite = (
			{"measured": True, "metric": "vmaf", "vmaf": vmaf}
			if vmaf is not None
			else {"measured": False, "metric": "", "vmaf_note": "libvmaf yok"}
		)
		teslim = (
			(True, {"duration_gate": "GECTI", "av_sync_gate": "GECTI", "first_frame_gate": "GECTI"})
			if teslim_ok
			else (False, {"duration_gate": "DUSTU", "av_sync_gate": "GECTI", "first_frame_gate": "GECTI"})
		)
		with mock.patch.object(tc, "_run", side_effect=sahte_run), \
			mock.patch.object(tc, "measure_quality", return_value=kalite), \
			mock.patch.object(tc, "validate_delivery_metrics", return_value=teslim), \
			mock.patch.object(tc, "first_frame_luma_pct", return_value=50.0), \
			mock.patch.object(tc.probe_modulu, "probe", return_value=_facts(size_bytes=src_bytes)):
			sonuc = tc.transcode(src, dst, facts=_facts(size_bytes=src_bytes), **tk)
		return sonuc, src, dst

	def test_bi_kazanc_yeterliyse_kabul_edilir(self):
		s, _src, dst = self._kos(src_bytes=1000, out_bytes=500)
		self.assertTrue(s.accepted)
		self.assertFalse(s.kept_source)
		self.assertTrue(os.path.exists(dst))
		self.assertAlmostEqual(s.saving_ratio, 0.5, places=3)

	def test_gv_cikti_kaynaktan_buyukse_atilir(self):
		"""10 MB MP4 → 40 MB WebM vakası: format kalite seviyesi değildir."""
		s, _src, dst = self._kos(src_bytes=1000, out_bytes=4000)
		self.assertFalse(s.accepted)
		self.assertTrue(s.kept_source)
		self.assertFalse(os.path.exists(dst), "kapıdan düşen çıktı diskte kalmamalı")
		self.assertLess(s.saving_ratio, 0)
		self.assertTrue(any("INV-05" in n for n in s.notes), s.notes)

	def test_sn_kazanc_tam_esikte_kabul(self):
		esik = tc.min_saving_ratio()
		s, _s, _d = self._kos(src_bytes=1000, out_bytes=int(1000 * (1 - esik)))
		self.assertTrue(s.accepted, s.notes)

	def test_sn_kazanc_esigin_altinda_ret(self):
		esik = tc.min_saving_ratio()
		s, _s, _d = self._kos(src_bytes=1000, out_bytes=int(1000 * (1 - esik)) + 1)
		self.assertFalse(s.accepted)

	def test_bi_kapi_kapatilirsa_cikti_diskte_kalir(self):
		s, _src, dst = self._kos(src_bytes=1000, out_bytes=4000, enforce_benefit_gate=False)
		self.assertTrue(s.accepted)
		self.assertTrue(os.path.exists(dst))

	def test_gv_vmaf_esigin_altindaysa_atilir(self):
		s, _src, dst = self._kos(src_bytes=1000, out_bytes=400, vmaf=80.0)
		self.assertFalse(s.accepted)
		self.assertTrue(s.kept_source)
		self.assertEqual(s.quality["vmaf_gate"], "DUSTU")
		self.assertFalse(os.path.exists(dst))

	def test_bi_vmaf_esigin_ustunde_gecer(self):
		s, _s, _d = self._kos(src_bytes=1000, out_bytes=400, vmaf=95.0)
		self.assertTrue(s.accepted)
		self.assertEqual(s.quality["vmaf_gate"], "GECTI")

	def test_gv_vmaf_olculemezse_sayi_uydurulmaz(self):
		s, _s, _d = self._kos(src_bytes=1000, out_bytes=400, vmaf=None)
		self.assertTrue(s.accepted)
		self.assertEqual(s.quality["vmaf_gate"], "OLCULEMEDI")
		self.assertIsNone(s.quality["vmaf"])
		self.assertTrue(any("VMAF OLCULEMEDI" in n for n in s.notes), s.notes)

	def test_gv_teslim_kapisi_dusunce_atilir(self):
		s, _src, dst = self._kos(src_bytes=1000, out_bytes=400, vmaf=95.0, teslim_ok=False)
		self.assertFalse(s.accepted)
		self.assertTrue(s.kept_source)
		self.assertFalse(os.path.exists(dst))
		self.assertTrue(any("teslim butunlugu" in n for n in s.notes), s.notes)

	def test_bi_saving_ratio_sifir_kaynakta_patlamaz(self):
		r = tc.TranscodeResult(action=tc.ACTION_TRANSCODE, src_path="/a", src_bytes=0, out_bytes=100)
		self.assertEqual(r.saving_ratio, 0.0)

	def test_bi_as_dict_sozlesmesi(self):
		d = tc.TranscodeResult(action=tc.ACTION_TRANSCODE, src_path="/a").as_dict()
		for alan in ("action", "accepted", "kept_source", "fallback_from", "src_bytes",
					 "out_bytes", "saving_ratio", "quality", "notes", "limits_applied"):
			self.assertIn(alan, d)


# ══════════════════════════════════════════════════════════════════════
# 6. REMUX geri çekilmesi (B-2)
# ══════════════════════════════════════════════════════════════════════


class TestRemuxGeriCekilme(unittest.TestCase):
	def test_bi_kap_kusuru_varsa_ve_akislar_teslim_edilebilirse_uygulanir(self):
		ok, gerekce = tc.remux_fallback_applies(_facts(moov_at_end=True))
		self.assertTrue(ok)
		self.assertIn("moov", gerekce)

	def test_bi_kap_kusuru_yoksa_uygulanmaz(self):
		ok, gerekce = tc.remux_fallback_applies(_facts())
		self.assertFalse(ok)
		self.assertIn("kusuru yok", gerekce)

	def test_gv_teslim_edilemeyen_video_kodegi_ile_uygulanmaz(self):
		"""VP9'u `-c copy` ile mp4'e taşımak oynamayan dosya üretir."""
		ok, gerekce = tc.remux_fallback_applies(_facts(container_family="matroska", video_codec="vp9"))
		self.assertFalse(ok)
		self.assertIn("vp9", gerekce)

	def test_gv_teslim_edilemeyen_ses_kodegi_ile_uygulanmaz(self):
		ok, gerekce = tc.remux_fallback_applies(
			_facts(container_family="matroska", video_codec="h264", audio_codec="opus")
		)
		self.assertFalse(ok)
		self.assertIn("opus", gerekce)

	def test_bi_sessiz_kaynakta_ses_kodegi_bakilmaz(self):
		ok, _ = tc.remux_fallback_applies(
			_facts(container_family="matroska", video_codec="h264", has_audio=False, audio_codec="opus")
		)
		self.assertTrue(ok)

	def test_bi_olculemeyen_kunyede_uygulanmaz(self):
		ok, gerekce = tc.remux_fallback_applies(_facts(measured=False))
		self.assertFalse(ok)
		self.assertIn("olculemedi", gerekce)

	def test_bi_kunye_none_ise_uygulanmaz(self):
		ok, _ = tc.remux_fallback_applies(None)
		self.assertFalse(ok)

	def test_bi_tabloda_kapatilabilir(self):
		hedefler = {"benefit_gate": {"fallback": {"enabled": False}}}
		ok, gerekce = tc.remux_fallback_applies(_facts(moov_at_end=True), hedefler)
		self.assertFalse(ok)
		self.assertIn("kapali", gerekce)


class TestAksiyonUygulama(unittest.TestCase):
	def test_bi_passthrough_ffmpeg_calistirmaz(self):
		with tempfile.TemporaryDirectory() as d:
			src = os.path.join(d, "a.mp4")
			open(src, "wb").write(b"\x00" * 100)
			karar = kr.decide(_facts())
			with mock.patch.object(tc, "_run", side_effect=AssertionError("ffmpeg çağrıldı!")):
				s = tc.apply_decision(src, os.path.join(d, "b.mp4"), karar)
			self.assertEqual(s.action, kr.ACTION_PASSTHROUGH)
			self.assertTrue(s.accepted)
			self.assertTrue(s.kept_source)

	def test_bi_reject_ffmpeg_calistirmaz_ve_hata_atmaz(self):
		with tempfile.TemporaryDirectory() as d:
			src = os.path.join(d, "a.mp4")
			open(src, "wb").write(b"\x00" * 100)
			karar = kr.decide(_facts(has_video=False))
			with mock.patch.object(tc, "_run", side_effect=AssertionError("ffmpeg çağrıldı!")):
				s = tc.apply_decision(src, os.path.join(d, "b.mp4"), karar)
			self.assertEqual(s.action, kr.ACTION_REJECT)
			self.assertFalse(s.accepted)
			self.assertTrue(s.kept_source)


# ══════════════════════════════════════════════════════════════════════
# 7. Ortam kaydı
# ══════════════════════════════════════════════════════════════════════


class TestOrtam(unittest.TestCase):
	def test_orm_ffmpeg_kurulu_mu(self):
		if not tc.ffmpeg_available():
			self.skipTest("ffmpeg YOK — gerçek kodlama yolu bu ortamda ölçülemiyor")

	def test_orm_ffprobe_kurulu_mu(self):
		from tradehub_core.media.pipeline.video import probe as vp

		if not vp.ffprobe_available():
			self.skipTest("ffprobe YOK — gerçek künye ölçümü bu ortamda yapılamıyor")

	def test_orm_vmaf_kurulu_mu(self):
		if not tc.vmaf_available():
			self.skipTest("libvmaf YOK — kalite kapısı üretimde UYGULANMAZ, notla geçer")


if __name__ == "__main__":
	unittest.main()

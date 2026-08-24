"""T-070/T-071 testleri — video künyesi (`probe.py`) ve karar tablosu (`decision.py`).

Üç soruyu ayrı ayrı cevaplar:

1. **Tablo VERİ mi, kod mu?** Kararın JSON'dan geldiği, kodun sabit kaldığı
   gösterilir: `test_yeni_kural_kod_degismeden_calisir` çalışma anında geçici
   bir dizine ONALTINCI bir kural yazar ve `decision.py` değişmeden o kuralın
   uygulandığını kanıtlar. Bozuk tablo (bilinmeyen değişken/operatör/aksiyon)
   YÜKLEME ANINDA patlar — çalışma zamanına sessiz bir "eşleşmedi" bırakmaz.

2. **Her kural tetiklenebiliyor mu?** 15 kuralın her biri için, yalnız o kuralı
   tetikleyen sentetik bir künye kurulur ve dönen `rule_id` doğrulanır. Bir
   kural hiç tetiklenemiyorsa (üstünde daha genel bir kural varsa) ölüdür ve
   bu test onu yakalar.

3. **Gerçek dosyalarda ne oluyor?** 11 video fixture'ı ffprobe ile ölçülüp
   tablodan geçirilir. İlk 7 sentetik (ffmpeg 5.1.9-0+deb12u1); son 4 GERÇEK
   DEV kaynağı (W9, 2026-08-20, ffmpeg n8.1.2-44) — `real_satici_720x720_28s`,
   `real_uretim_h264_1280`, `real_uretim_preview_480`, `video_real_seller_1080p_2997fps`.
   Hepsi istoc-dev-backend-1'de ölçüldü ve `OLCULEN_FIXTURE_KARARLARI` içinde yazılı.

ffprobe GEREKTİREN testler yoksa ATLANIR (yerel makinede ffmpeg kurulu değil;
konteynerde var). Atlanan test "geçti" sayılmaz — çıktıda `skipped` görünür.

Çalıştırma:

    python3 -m unittest tests.test_video_decision -v
    docker exec -w /home/frappe/frappe-bench/sites istoc-dev-backend-1 \
        ../env/bin/python -m unittest tests.test_video_decision -v
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.contracts.video import (  # noqa: E402
	NEEDS_TRANSCODE_MAX_BITRATE_BPS,
	NEEDS_TRANSCODE_MAX_WIDTH,
)
from tradehub_core.media.pipeline.video import probe as P  # noqa: E402
from tradehub_core.media.pipeline.video.decision import (  # noqa: E402
	ACTION_PASSTHROUGH,
	ACTION_REJECT,
	ACTION_REMUX,
	ACTION_TRANSCODE,
	ACTIONS,
	DECISION_TABLE_PATH,
	DecisionTable,
	DecisionTableError,
	decide,
	default_table,
)

VIDEO_DIR = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "video"
VIDEO_PKG = ROOT / "tradehub_core" / "media" / "pipeline" / "video"

#: **ÖLÇÜLDÜ** — konteyner istoc-dev-backend-1, ffprobe 5.1.9-0+deb12u1,
#: 2026-08-18. Bu sözlük bir BEKLENTİ değil, bir ÖLÇÜM KAYDIDIR: tablo
#: değiştiğinde burası da değişmelidir, tersi değil.
OLCULEN_FIXTURE_KARARLARI = {
	# --- 7 sentetik fixture (gen_fixtures_video.sh) ---
	"video_16x9_1080p.mp4": ("TRANSCODE", "width_over_cap"),
	"video_bloated_720p_8m.mp4": ("TRANSCODE", "bitrate_over_cap"),
	"video_efficient_720p_750k.mp4": ("PASSTHROUGH", "default"),
	"video_long_540s_320x240.mp4": ("PASSTHROUGH", "default"),
	"video_silent_noaudio_720p.mp4": ("PASSTHROUGH", "default"),
	"video_square_352.mp4": ("PASSTHROUGH", "default"),
	"video_vertical_9x16.mp4": ("PASSTHROUGH", "default"),
	# --- 4 GERÇEK DEV kaynağı (W9, 2026-08-20, ffmpeg n8.1.2-44) — sentetik DEĞİL ---
	# real_satici: LST-04043 satıcı videosu, önceden sıkıştırılmış (707 kbps) → PASSTHROUGH.
	"real_satici_720x720_28s.mp4": ("PASSTHROUGH", "default"),
	# real_uretim_h264: boru hattı üretim çıktısı (9mb.mp4 REMUX türevi) → PASSTHROUGH.
	"real_uretim_h264_1280.mp4": ("PASSTHROUGH", "default"),
	# real_uretim_preview: W8 preview türevi (480×480, 6 sn) → PASSTHROUGH.
	"real_uretim_preview_480.mp4": ("PASSTHROUGH", "default"),
	# video_real_seller: gerçek satıcı yüklemesi (tabFile fc6e94877e); 1920 > 1280 → genişlik kolu.
	"video_real_seller_1080p_2997fps.mp4": ("TRANSCODE", "width_over_cap"),
}

#: Ölçülmüş künye değerleri (aynı koşum). Künye ayrıştırmasının sessizce
#: bozulmasını yakalar — `bpp` gibi türetilmiş ölçüler dahil.
OLCULEN_KUNYELER = {
	"video_16x9_1080p.mp4": {"width": 1920, "height": 1080, "fps": 25.0, "codec": "h264",
		"pix_fmt": "yuv420p", "vbitrate": 1505445, "bpp": 0.0290, "audio": False},
	"video_bloated_720p_8m.mp4": {"width": 1280, "height": 720, "fps": 30.0, "codec": "h264",
		"pix_fmt": "yuv420p", "vbitrate": 8220772, "bpp": 0.2973, "audio": True},
	"video_efficient_720p_750k.mp4": {"width": 1280, "height": 720, "fps": 30.0, "codec": "h264",
		"pix_fmt": "yuv420p", "vbitrate": 767652, "bpp": 0.0278, "audio": True},
	"video_long_540s_320x240.mp4": {"width": 320, "height": 240, "fps": 10.0, "codec": "h264",
		"pix_fmt": "yuv420p", "vbitrate": 58728, "bpp": 0.0765, "audio": False},
	# --- 4 GERÇEK DEV kaynağı (W9, 2026-08-20) ---
	"real_satici_720x720_28s.mp4": {"width": 720, "height": 720, "fps": 30.0, "codec": "h264",
		"pix_fmt": "yuv420p", "vbitrate": 707234, "bpp": 0.04548, "audio": True},
	"real_uretim_h264_1280.mp4": {"width": 1280, "height": 720, "fps": 30.0, "codec": "h264",
		"pix_fmt": "yuv420p", "vbitrate": 140555, "bpp": 0.00508, "audio": False},
	"real_uretim_preview_480.mp4": {"width": 480, "height": 480, "fps": 30.0, "codec": "h264",
		"pix_fmt": "yuv420p", "vbitrate": 151624, "bpp": 0.02194, "audio": False},
	"video_real_seller_1080p_2997fps.mp4": {"width": 1920, "height": 1080, "fps": 29.97, "codec": "h264",
		"pix_fmt": "yuv420p", "vbitrate": 1152743, "bpp": 0.01855, "audio": True},
	"video_silent_noaudio_720p.mp4": {"width": 1280, "height": 720, "fps": 25.0, "codec": "h264",
		"pix_fmt": "yuv420p", "vbitrate": 834984, "bpp": 0.0362, "audio": False},
	"video_square_352.mp4": {"width": 352, "height": 352, "fps": 25.0, "codec": "h264",
		"pix_fmt": "yuv420p", "vbitrate": 388986, "bpp": 0.1256, "audio": False},
	"video_vertical_9x16.mp4": {"width": 720, "height": 1280, "fps": 30.0, "codec": "h264",
		"pix_fmt": "yuv420p", "vbitrate": 911187, "bpp": 0.0330, "audio": True},
}

FFPROBE = P.ffprobe_available()


def temiz_kunye(**degisiklikler) -> dict:
	"""HİÇBİR kurala takılmayan künye — tek değişken değiştirilerek kullanılır.

	Değerler `video_efficient_720p_750k.mp4`'ün ÖLÇÜLEN künyesinden alındı:
	tablodan PASSTHROUGH ile çıkan gerçek bir dosya, sentetik bir "ideal"
	değil.
	"""
	temel = {
		"measured": True, "has_video": True,
		"coded_width": 1280, "coded_height": 720,
		"width": 1280, "height": 720, "pixels": 921600, "long_edge": 1280, "short_edge": 720,
		"duration_s": 10.0, "video_start_time_s": 0.0, "video_duration_s": 10.0, "fps": 30.0,
		"video_codec": "h264", "video_profile": "High", "video_level": 40,
		"sample_aspect_ratio": "1:1", "display_aspect_ratio": "16:9", "pix_fmt": "yuv420p",
		"color_transfer": "bt709", "color_primaries": "bt709", "color_space": "bt709",
		"is_hdr": False, "has_bframes": True,
		"video_bitrate_bps": 767652, "format_bitrate_bps": 873701, "bpp": 0.0278,
		"container": "mov,mp4,m4a,3gp,3g2,mj2", "container_family": "mp4",
		"has_audio": True, "audio_codec": "aac", "audio_bitrate_bps": 96286, "audio_channels": 2,
		"audio_start_time_s": 0.0, "audio_duration_s": 10.0,
		"moov_at_end": False, "size_bytes": 1092127, "rotation": 0, "nb_streams": 2,
		"error_count": 0,
	}
	temel.update(degisiklikler)
	return temel


class TabloYuklemesi(unittest.TestCase):
	"""Tablo dosyası şeklen sağlam mı, doğrulama gerçekten çalışıyor mu."""

	def test_tablo_dosyasi_var_ve_okunuyor(self):
		self.assertTrue(DECISION_TABLE_PATH.exists(), f"karar tablosu yok: {DECISION_TABLE_PATH}")
		t = default_table()
		self.assertEqual(t.schema_version, "1.0.0")
		self.assertGreaterEqual(len(t.rules), 1)

	def test_kural_idleri_tekil(self):
		idler = [k.id for k in default_table().rules]
		self.assertEqual(len(idler), len(set(idler)), f"tekrar eden kural id: {idler}")

	def test_butun_aksiyonlar_taninan_kumeden(self):
		for k in default_table().rules:
			self.assertIn(k.action, ACTIONS, f"{k.id}: taninmayan aksiyon {k.action}")

	def test_her_kuralin_kodu_ve_gerekcesi_var(self):
		"""Kodsuz bir kural kullanıcıya "reddedildi" der ama nedenini söylemez."""
		for k in default_table().rules:
			self.assertTrue(k.code, f"{k.id}: `code` bos")
			self.assertTrue(k.reason, f"{k.id}: `reason` bos")

	def test_varsayilan_passthrough(self):
		"""Hiçbir kural eşleşmediyse dosyaya DOKUNULMAZ.

		Varsayılanın TRANSCODE olması, tanımadığımız her dosyayı yeniden
		kodlamak demekti — kuyruğu boğar ve kalite kaybettirir.
		"""
		self.assertEqual(default_table().default_action, ACTION_PASSTHROUGH)

	def test_bilinmeyen_degisken_yukleme_aninda_patlar(self):
		ham = {
			"schema_version": "1.0.0",
			"rules": [{"id": "x", "action": "REJECT", "when": {"var": "yok_boyle_bir_sey", "op": "eq", "value": 1}}],
			"default": {"action": "PASSTHROUGH"},
		}
		with self.assertRaises(DecisionTableError) as c:
			DecisionTable(ham)
		self.assertIn("yok_boyle_bir_sey", str(c.exception))

	def test_bilinmeyen_operator_yukleme_aninda_patlar(self):
		ham = {
			"schema_version": "1.0.0",
			"rules": [{"id": "x", "action": "REJECT", "when": {"var": "width", "op": "yaklasik", "value": 1}}],
			"default": {"action": "PASSTHROUGH"},
		}
		with self.assertRaises(DecisionTableError):
			DecisionTable(ham)

	def test_bilinmeyen_aksiyon_yukleme_aninda_patlar(self):
		ham = {
			"schema_version": "1.0.0",
			"rules": [{"id": "x", "action": "SIKISTIR", "when": {"var": "width", "op": "gt", "value": 1}}],
			"default": {"action": "PASSTHROUGH"},
		}
		with self.assertRaises(DecisionTableError):
			DecisionTable(ham)

	def test_tekrar_eden_kural_id_patlar(self):
		ham = {
			"schema_version": "1.0.0",
			"rules": [
				{"id": "ayni", "action": "REJECT", "when": {"var": "width", "op": "gt", "value": 1}},
				{"id": "ayni", "action": "REJECT", "when": {"var": "width", "op": "gt", "value": 2}},
			],
			"default": {"action": "PASSTHROUGH"},
		}
		with self.assertRaises(DecisionTableError):
			DecisionTable(ham)

	def test_bos_kural_listesi_patlar(self):
		with self.assertRaises(DecisionTableError):
			DecisionTable({"schema_version": "1.0.0", "rules": [], "default": {"action": "PASSTHROUGH"}})

	def test_eksik_degiskenli_kunye_reddedilir(self):
		"""Yarım künyeyle karar verilmez — eksik alan sessizce "eşleşmedi"ye dönmez."""
		with self.assertRaises(DecisionTableError):
			default_table().evaluate({"width": 1920})


class YeniKuralKodDegismeden(unittest.TestCase):
	"""T-071'in ASIL iddiası: yeni karar = JSON satırı, kod değişikliği DEĞİL."""

	def test_yeni_kural_kod_degismeden_calisir(self):
		ham = json.loads(DECISION_TABLE_PATH.read_text(encoding="utf-8"))
		onceki_kural_sayisi = len(ham["rules"])
		# Yepyeni bir kısıt: 24 kare/sn altındaki kaynak reddedilsin. Bugünkü
		# tabloda fps ALT sınırı diye bir kavram YOK.
		ham["rules"].insert(0, {
			"id": "fps_under_min",
			"when": {"var": "fps", "op": "lt", "value": 24},
			"action": "REJECT",
			"code": "video_fps_under_min",
			"reason": "Test kurali — kare hizi alt sinirin altinda.",
		})
		with tempfile.TemporaryDirectory() as d:
			yol = Path(d) / "video_decision.json"
			yol.write_text(json.dumps(ham), encoding="utf-8")
			tablo = DecisionTable.load(yol)

		self.assertEqual(len(tablo.rules), onceki_kural_sayisi + 1)
		karar = tablo.evaluate(temiz_kunye(fps=10.0))
		self.assertEqual(karar.action, ACTION_REJECT)
		self.assertEqual(karar.rule_id, "fps_under_min")
		# Aynı künye, DEĞİŞMEMİŞ tabloda hâlâ PASSTHROUGH — yeni kural yalnız
		# kendi dosyasında var.
		self.assertEqual(decide(temiz_kunye(fps=10.0)).action, ACTION_PASSTHROUGH)


class KuralTetikleme(unittest.TestCase):
	"""15 kuralın her biri tetiklenebiliyor mu — ölü kural var mı."""

	def test_temiz_kunye_hicbir_kurala_takilmaz(self):
		karar = decide(temiz_kunye())
		self.assertEqual(karar.action, ACTION_PASSTHROUGH)
		self.assertEqual(karar.rule_id, "default")

	def test_olculemeyen_kunye_reddedilir(self):
		"""BUGÜNKÜ HATTAN AYRILAN NOKTA.

		`transcode.needs_transcode()` ölçülemeyen dosyada True (transcode et)
		diyor; tablo REJECT diyor. Fark bilinçli ve tabloda
		`diverges_from_today` alanında yazılı.
		"""
		karar = decide(temiz_kunye(measured=False))
		self.assertEqual(karar.action, ACTION_REJECT)
		self.assertEqual(karar.rule_id, "probe_unavailable")

	def test_video_akisi_yoksa_reddedilir(self):
		karar = decide(temiz_kunye(has_video=False))
		self.assertEqual(karar.rule_id, "no_video_stream")
		self.assertEqual(karar.action, ACTION_REJECT)

	def test_4k_ustu_reddedilir(self):
		self.assertEqual(decide(temiz_kunye(width=4096, height=2160)).rule_id, "resolution_over_max")
		self.assertEqual(decide(temiz_kunye(width=3840, height=2400)).rule_id, "resolution_over_max")

	def test_tam_4k_reddedilmez(self):
		"""Sınır DAHİL: 3840×2160 geçer, üstü geçmez."""
		karar = decide(temiz_kunye(width=3840, height=2160))
		self.assertNotEqual(karar.rule_id, "resolution_over_max")

	def test_15_dakika_ustu_reddedilir(self):
		self.assertEqual(decide(temiz_kunye(duration_s=901)).rule_id, "duration_over_engine_max")
		self.assertNotEqual(decide(temiz_kunye(duration_s=900)).rule_id, "duration_over_engine_max")

	def test_olculen_en_uzun_video_reddedilmez(self):
		"""Canlıda ölçülen en uzun video 540 sn — motor sınırı onu vurmamalı."""
		self.assertNotEqual(decide(temiz_kunye(duration_s=540)).action, ACTION_REJECT)

	def test_h264_disi_kodek_transcode(self):
		for kodek in ("hevc", "vp9", "av1", "mpeg4", "vp8", "prores"):
			with self.subTest(kodek=kodek):
				karar = decide(temiz_kunye(video_codec=kodek))
				self.assertEqual(karar.action, ACTION_TRANSCODE)
				self.assertEqual(karar.rule_id, "codec_not_deliverable")

	def test_vp9_bugunku_ciktinin_kendisi_transcode_edilir(self):
		"""Bugünkü hattın ÇIKTISI (VP9) bu tablodan geçse yeniden kodlanır.

		Bu bir çelişki değil, göçün ta kendisi: VP9/WebM birikimi H.264'e
		çevrilmeden Safari'de oynamıyor.
		"""
		self.assertEqual(decide(temiz_kunye(video_codec="vp9")).action, ACTION_TRANSCODE)

	def test_web_disi_pix_fmt_transcode(self):
		for pf in ("yuv420p10le", "yuv422p", "yuv444p", "yuv420p12le"):
			with self.subTest(pix_fmt=pf):
				self.assertEqual(decide(temiz_kunye(pix_fmt=pf)).rule_id, "pix_fmt_not_web")

	def test_genislik_tavani_bugunku_sayiyla_ayni(self):
		"""1280 sayısı bugünkü hattan KORUNUYOR — tabloda da aynı."""
		self.assertEqual(decide(temiz_kunye(width=1281)).rule_id, "width_over_cap")
		self.assertNotEqual(decide(temiz_kunye(width=1280)).rule_id, "width_over_cap")
		kural = default_table().rule("width_over_cap")
		self.assertEqual(kural.when["value"], NEEDS_TRANSCODE_MAX_WIDTH)

	def test_bitrate_tavani_bugunku_sayiyla_ayni(self):
		self.assertEqual(decide(temiz_kunye(video_bitrate_bps=2_500_001)).rule_id, "bitrate_over_cap")
		self.assertNotEqual(decide(temiz_kunye(video_bitrate_bps=2_500_000)).rule_id, "bitrate_over_cap")
		kural = default_table().rule("bitrate_over_cap")
		self.assertEqual(kural.when["value"], NEEDS_TRANSCODE_MAX_BITRATE_BPS)

	def test_fps_tavani_bugun_hic_bakilmayan_degisken(self):
		"""`transcode.py` fps'e HİÇ bakmıyor — bu kural bugünkü açığı kapatıyor."""
		karar = decide(temiz_kunye(fps=60.0, bpp=0.0139))
		self.assertEqual(karar.rule_id, "fps_over_cap")
		self.assertEqual(karar.action, ACTION_TRANSCODE)

	def test_verimsiz_kodlama_iki_kosul_birlikte(self):
		"""bpp TEK BAŞINA yetmez — mutlak bitrate tabanıyla VE'lenir."""
		# İkisi de aşılıyor → tetiklenir.
		karar = decide(temiz_kunye(bpp=0.35, video_bitrate_bps=2_400_000))
		self.assertEqual(karar.rule_id, "inefficient_encoding")
		# bpp yüksek ama mutlak bitrate düşük (352×352 fixture'ı) → tetiklenmez.
		karar = decide(temiz_kunye(width=352, height=352, bpp=0.1256, video_bitrate_bps=388_986))
		self.assertEqual(karar.action, ACTION_PASSTHROUGH)

	def test_olculen_352_fixture_bosuna_transcode_edilmiyor(self):
		"""Kanıt niteliğinde: ÖLÇÜLEN bpp 0,1256 eşiğin (0,08) üstünde ama
		mutlak bitrate tabanı (1,2 Mbps) bu boşa işi kesiyor."""
		k = OLCULEN_KUNYELER["video_square_352.mp4"]
		karar = decide(temiz_kunye(
			width=k["width"], height=k["height"], pixels=k["width"] * k["height"],
			long_edge=352, short_edge=352, fps=k["fps"], bpp=k["bpp"],
			video_bitrate_bps=k["vbitrate"], has_audio=False, audio_codec="",
			audio_bitrate_bps=0, audio_channels=0, nb_streams=1,
		))
		self.assertEqual(karar.action, ACTION_PASSTHROUGH)

	def test_teslim_edilemeyen_ses_kodegi_transcode(self):
		for kodek in ("opus", "vorbis", "pcm_s16le", "ac3", "flac"):
			with self.subTest(kodek=kodek):
				karar = decide(temiz_kunye(audio_codec=kodek))
				self.assertEqual(karar.rule_id, "audio_codec_not_deliverable")

	def test_sessiz_dosyada_ses_kurallari_tetiklenmez(self):
		"""`has_audio=False` iken ses kodeği boş — kural VE'li olduğu için susar."""
		karar = decide(temiz_kunye(has_audio=False, audio_codec="", audio_bitrate_bps=0,
			audio_channels=0, nb_streams=1))
		self.assertEqual(karar.action, ACTION_PASSTHROUGH)

	def test_yuksek_ses_bitrate_transcode(self):
		karar = decide(temiz_kunye(audio_bitrate_bps=320_000))
		self.assertEqual(karar.rule_id, "audio_bitrate_over_cap")

	def test_mp4_disi_kap_remux(self):
		"""REMUX bugün HİÇ YOK: bir .mkv için tek seçenek tam yeniden kodlamaydı."""
		for aile in ("webm", "matroska", "avi", "mpegts", "other"):
			with self.subTest(kap=aile):
				karar = decide(temiz_kunye(container_family=aile))
				self.assertEqual(karar.action, ACTION_REMUX)
				self.assertEqual(karar.rule_id, "container_not_mp4")

	def test_moov_sonda_remux(self):
		karar = decide(temiz_kunye(moov_at_end=True))
		self.assertEqual(karar.action, ACTION_REMUX)
		self.assertEqual(karar.rule_id, "moov_at_end")

	def test_fazla_akis_remux(self):
		karar = decide(temiz_kunye(nb_streams=4))
		self.assertEqual(karar.rule_id, "extra_streams")
		self.assertEqual(karar.action, ACTION_REMUX)

	def test_her_kural_en_az_bir_kez_tetiklendi(self):
		"""Ölü kural avı: tablodaki her kural id'si bu sınıfta sınanmış olmalı."""
		kaynak = Path(__file__).read_text(encoding="utf-8")
		for k in default_table().rules:
			self.assertIn(
				f'"{k.id}"', kaynak,
				f"{k.id} kurali hicbir testte sinanmiyor — olu kural olabilir",
			)


class SiraOnemli(unittest.TestCase):
	"""İLK EŞLEŞEN KAZANIR — sıra bir uygulama ayrıntısı değil, karardır."""

	def test_reject_transcodedan_once_gelir(self):
		"""4K üstü VE bitrate tavan üstü bir dosya REDDEDİLİR, transcode edilmez."""
		karar = decide(temiz_kunye(width=4000, height=2400, video_bitrate_bps=20_000_000))
		self.assertEqual(karar.action, ACTION_REJECT)

	def test_transcode_remuxtan_once_gelir(self):
		"""mkv içindeki HEVC yeniden kodlanır; yalnız kabı düzeltmek yetmez."""
		karar = decide(temiz_kunye(container_family="matroska", video_codec="hevc"))
		self.assertEqual(karar.action, ACTION_TRANSCODE)

	def test_iz_kaydi_bakilan_kurallari_tasiyor(self):
		karar = decide(temiz_kunye(width=1920))
		bakilan = [kid for kid, _ in karar.trace]
		self.assertIn("probe_unavailable", bakilan)
		self.assertIn("width_over_cap", bakilan)
		self.assertTrue(dict(karar.trace)["width_over_cap"])
		self.assertFalse(dict(karar.trace)["probe_unavailable"])

	def test_aksiyon_yeni_dosya_yaziyor_mu(self):
		self.assertFalse(decide(temiz_kunye()).writes_new_file)
		self.assertTrue(decide(temiz_kunye(width=1920)).writes_new_file)
		self.assertTrue(decide(temiz_kunye(moov_at_end=True)).writes_new_file)
		self.assertFalse(decide(temiz_kunye(measured=False)).writes_new_file)


class KunyeYardimcilari(unittest.TestCase):
	"""ffprobe GEREKTİRMEYEN saf ayrıştırma testleri."""

	def test_kesirli_kare_hizi(self):
		self.assertAlmostEqual(P.parse_frame_rate("30000/1001"), 29.97002997, places=6)
		self.assertEqual(P.parse_frame_rate("25/1"), 25.0)
		self.assertEqual(P.parse_frame_rate("30"), 30.0)

	def test_bozuk_kare_hizi_uydurmaz(self):
		"""Bölen 0 ya da metin ayrıştırılamıyorsa 0,0 — tahmin YOK."""
		self.assertEqual(P.parse_frame_rate("0/0"), 0.0)
		self.assertEqual(P.parse_frame_rate(""), 0.0)
		self.assertEqual(P.parse_frame_rate("abc"), 0.0)

	def test_kap_ailesi(self):
		self.assertEqual(P.container_family_of("mov,mp4,m4a,3gp,3g2,mj2"), "mp4")
		# ffprobe webm dosyasına "matroska,webm" der; sıra ÖNEMLİ — CONTAINER_FAMILIES
		# içinde webm matroska'dan önce geliyor ki webm "matroska" diye etiketlenmesin.
		self.assertEqual(P.container_family_of("matroska,webm"), "webm")
		self.assertEqual(P.container_family_of("avi"), "avi")
		self.assertEqual(P.container_family_of(""), "other")
		self.assertEqual(P.container_family_of("bilinmeyen"), "other")

	def test_bpp_bolen_sifirken_sifir_doner(self):
		"""Ölçülemeyen verimlilik "kötü" sayılmaz — 0,0 kuralı tetiklemez."""
		self.assertEqual(P.VideoFacts(width=1280, height=720, fps=0.0).bpp, 0.0)
		self.assertEqual(P.VideoFacts(width=0, height=0, fps=30.0).bpp, 0.0)
		karar = decide(temiz_kunye(bpp=0.0, video_bitrate_bps=2_000_000))
		self.assertNotEqual(karar.rule_id, "inefficient_encoding")

	def test_bpp_hesabi(self):
		f = P.VideoFacts(width=1280, height=720, fps=30.0, video_bitrate_bps=767652)
		self.assertAlmostEqual(f.bpp, 767652 / (1280 * 720 * 30), places=9)

	def test_turetilmis_olculer(self):
		f = P.VideoFacts(width=720, height=1280)
		self.assertEqual(f.pixels, 921600)
		self.assertEqual(f.long_edge, 1280)
		self.assertEqual(f.short_edge, 720)
		self.assertAlmostEqual(f.aspect_ratio, 720 / 1280)

	def test_olculmemis_kunye_alanlari_varsayilan(self):
		f = P.VideoFacts(path="/yok", error="ffprobe yok")
		self.assertFalse(f.measured)
		self.assertFalse(f.has_video)
		self.assertEqual(f.width, 0)
		self.assertEqual(decide(f).action, ACTION_REJECT)

	def test_probe_olmayan_dosyada_istisna_atmaz(self):
		"""Sözleşme: `probe()` HİÇBİR koşulda istisna atmaz."""
		f = P.probe("/kesinlikle/olmayan/bir/yol.mp4")
		self.assertFalse(f.measured)
		self.assertTrue(f.error)

	def test_video_olmayan_dosyada_istisna_atmaz(self):
		with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
			fh.write(b"bu bir video degil")
			yol = fh.name
		try:
			f = P.probe(yol)
			self.assertFalse(f.measured)
			self.assertTrue(f.error)
			self.assertEqual(decide(f).action, ACTION_REJECT)
		finally:
			os.unlink(yol)

	def test_moov_taramasi_video_olmayanda_false(self):
		with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
			fh.write(b"\x00" * 64)
			yol = fh.name
		try:
			self.assertFalse(P.moov_at_end_of(yol))
		finally:
			os.unlink(yol)

	def test_variables_tablodaki_her_degiskeni_kapsiyor(self):
		"""Tabloda geçen her `var` künyede bir alan olmalı — tersi de doğru olmalı
		ki tablo yazarken hangi değişkenlerin var olduğu tek yerden okunabilsin."""
		mevcut = set(P.VideoFacts().variables())
		ham = json.loads(DECISION_TABLE_PATH.read_text(encoding="utf-8"))

		def topla(kosul, cikti):
			if "all" in kosul or "any" in kosul:
				for alt in kosul.get("all") or kosul.get("any"):
					topla(alt, cikti)
			elif "not" in kosul:
				topla(kosul["not"], cikti)
			else:
				cikti.add(kosul["var"])

		kullanilan: set = set()
		for k in ham["rules"]:
			topla(k["when"], kullanilan)
		self.assertTrue(kullanilan <= mevcut, f"tabloda kunyede olmayan degisken: {kullanilan - mevcut}")
		self.assertTrue(set(ham["variables"]) <= mevcut,
			f"belgelenen ama kunyede olmayan degisken: {set(ham['variables']) - mevcut}")


class CekirdekSafligi(unittest.TestCase):
	"""`tradehub_core/media/pipeline/video/` bench/site olmadan test edilebilir olmalı."""

	def test_video_pakedinde_frappe_importu_yok(self):
		for yol in sorted(VIDEO_PKG.glob("*.py")):
			agac = ast.parse(yol.read_text(encoding="utf-8"), filename=str(yol))
			for dugum in ast.walk(agac):
				if isinstance(dugum, ast.Import):
					for ad in dugum.names:
						self.assertNotEqual(ad.name.split(".")[0], "frappe", f"{yol.name}: import frappe")
				elif isinstance(dugum, ast.ImportFrom) and dugum.module:
					self.assertNotEqual(
						dugum.module.split(".")[0], "frappe", f"{yol.name}: from frappe import"
					)

	def test_karar_modulu_dosya_acmaz(self):
		"""`decision.py` yan etkisizdir: `open` yalnız tablo yüklemesinde geçer."""
		kaynak = (VIDEO_PKG / "decision.py").read_text(encoding="utf-8")
		self.assertEqual(kaynak.count("subprocess"), 0)


@unittest.skipUnless(FFPROBE, "ffprobe yok — konteynerde calistir")
class GercekFixtureOlcumu(unittest.TestCase):
	"""11 video fixture'ı GERÇEK ffprobe ile ölçülüp tablodan geçirilir
	(7 sentetik + 4 gerçek DEV kaynağı — W9)."""

	def test_onbir_fixture_var(self):
		bulunan = sorted(p.name for p in VIDEO_DIR.glob("*.mp4"))
		self.assertEqual(len(bulunan), 11, f"beklenen 11 video fixture, bulunan: {bulunan}")
		self.assertEqual(set(bulunan), set(OLCULEN_FIXTURE_KARARLARI))

	def test_fixture_kararlari_olculenle_ayni(self):
		for ad, (aksiyon, kural) in sorted(OLCULEN_FIXTURE_KARARLARI.items()):
			with self.subTest(dosya=ad):
				karar = decide(P.probe(str(VIDEO_DIR / ad)))
				self.assertEqual(karar.action, aksiyon, f"{ad}: {karar.rule_id} -> {karar.action}")
				self.assertEqual(karar.rule_id, kural)

	def test_gorev_tanimindaki_iki_beklenti(self):
		"""FAZ 7 görev tanımının açıkça istediği iki sonuç."""
		self.assertEqual(decide(P.probe(str(VIDEO_DIR / "video_efficient_720p_750k.mp4"))).action,
			ACTION_PASSTHROUGH)
		self.assertEqual(decide(P.probe(str(VIDEO_DIR / "video_bloated_720p_8m.mp4"))).action,
			ACTION_TRANSCODE)

	def test_kunyeler_olculenle_ayni(self):
		for ad, b in sorted(OLCULEN_KUNYELER.items()):
			with self.subTest(dosya=ad):
				f = P.probe(str(VIDEO_DIR / ad))
				self.assertTrue(f.measured, f.error)
				self.assertEqual((f.width, f.height), (b["width"], b["height"]))
				self.assertAlmostEqual(f.fps, b["fps"], places=3)
				self.assertEqual(f.video_codec, b["codec"])
				self.assertEqual(f.pix_fmt, b["pix_fmt"])
				self.assertEqual(f.video_bitrate_bps, b["vbitrate"])
				self.assertAlmostEqual(f.bpp, b["bpp"], places=4)
				self.assertEqual(f.has_audio, b["audio"])

	#: ÖLÇÜLDÜ (2026-08-20, konteyner): korpustaki TEK moov-sonda dosya, gerçek
	#: satıcı yüklemesi. 7 sentetik fixture'da atom sırası ftyp, moov, free, mdat.
	MOOV_SONDA = {"video_real_seller_1080p_2997fps.mp4"}

	def test_moov_konumu_olculenle_ayni(self):
		"""Sentetik 7'de moov başta; gerçek yüklemede SONDA — `moov_at_end`
		alanı artık korpustaki gerçek bir dosyayla da temsil ediliyor (karar
		sırası gereği bu dosyada width_over_cap kuralı önce tetiklenir)."""
		for yol in sorted(VIDEO_DIR.glob("*.mp4")):
			with self.subTest(dosya=yol.name):
				self.assertEqual(
					P.moov_at_end_of(str(yol)), yol.name in self.MOOV_SONDA
				)

	def test_kap_ailesi_mp4_olarak_cozuluyor(self):
		for yol in sorted(VIDEO_DIR.glob("*.mp4")):
			with self.subTest(dosya=yol.name):
				f = P.probe(str(yol))
				self.assertEqual(f.container_family, "mp4")
				self.assertEqual(f.container, "mov,mp4,m4a,3gp,3g2,mj2")

	def test_sozlesmeye_indirgeme_calisiyor(self):
		f = P.probe(str(VIDEO_DIR / "video_efficient_720p_750k.mp4"))
		c = f.to_contract()
		self.assertEqual(c.width, 1280)
		self.assertEqual(c.container, "mp4")
		self.assertTrue(c.measured)
		self.assertAlmostEqual(c.megapixels, 0.9216, places=4)


if __name__ == "__main__":
	unittest.main(verbosity=2)

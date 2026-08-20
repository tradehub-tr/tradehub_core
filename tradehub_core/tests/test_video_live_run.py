"""W6 video koşumu testleri — GERÇEK ÇIKTI temelli (sentetik değer YOK).

Fixture (`fixtures/media/w6-video-live-run.json`) 2026-08-20 W6 koşumunda
`istoc-dev-backend-1` içinde GERÇEK DEV videolarıyla ölçüldü
(ffmpeg n8.1.2, libvmaf=1; koşumun tamamı `docs/reports/81-w6-video-kosum.md`).
İşlenen gerçek dosyalar:

    /files/Evde taze sıkılmış meyve sularının … limon.mp4  (LST-04043, 2.809.249 B)
    /files/9mb.mp4                                          (LST-04419, 9.622.535 B)
    + karar için künyesi ölçülen 2 dosya daha (LST-00862, LST-04035)

İki test kümesi:

**Fixture kümesi (ffmpeg GEREKMEZ, her yerde koşar).** Ölçülmüş künyeler karar
tablosundan yeniden geçirilir ve koşumda düşen kuralın AYNISININ düşmesi
beklenir; fayda kapısı aritmetiği ölçülmüş bayt sayılarıyla yeniden hesaplanır.
Vacuity garantisi: tablodaki `min_saving_ratio` kurcalanırsa (ör. 0,1 → 0,2)
`test_kapinin_esigi_tablodan_ve_olculen_degerde` VE
`test_gercek_cikti_kapiyi_gecti` birlikte KIRMIZI olur — çünkü gerçek koşumun
kazancı %11,44'tü ve %20'lik bir eşik onu reddederdi.

**Konteyner kümesi (DEV diski GEREKİR, yoksa ATLANIR).** W6 koşumunun diske
yazdığı çıktılar yerinde mi, remux çıktısında moov gerçekten başa alınmış mı,
master playlist büyütme yapmadan 3 basamak mı ilan ediyor.

Konteynerde koşum:

    docker exec -w /home/frappe/frappe-bench istoc-dev-backend-1 \
        env/bin/python -m unittest tradehub_core.tests.test_video_live_run -v

(`apps/tradehub_core/tradehub_core` cwd'sinden KOŞMAZ: oradaki `tradehub_core/`
Frappe modül-namespace dizini, editable kurulu paketi gölgeleyip
`tradehub_core.media`'yı görünmez kılıyor — ölçüldü.)
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.video import hls as H  # noqa: E402
from tradehub_core.media.pipeline.video import probe as P  # noqa: E402
from tradehub_core.media.pipeline.video import transcode as T  # noqa: E402
from tradehub_core.media.pipeline.video.decision import decide, default_table  # noqa: E402
from tradehub_core.media.pipeline.video.probe import VideoFacts  # noqa: E402

FIXTURE = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "w6-video-live-run.json"

#: W6 koşumunun çıktılarının durduğu DEV diski. Yerel makinede YOK — konteyner
#: kümesi o durumda atlanır (yanlış yeşil yerine dürüst skip).
SITE_PUBLIC = Path("/home/frappe/frappe-bench/sites/istoc.localhost/public")


def _fixture() -> Dict[str, Any]:
	with open(FIXTURE, "r", encoding="utf-8") as f:
		return json.load(f)


def _facts_from(kayit: Dict[str, Any]) -> VideoFacts:
	"""Ölçülmüş künye alanlarını `VideoFacts`'e geri giydir (listing alanı hariç)."""
	alanlar = {k: v for k, v in kayit.items() if k != "listing"}
	return VideoFacts(**alanlar)


FX = _fixture()


class KararTablosuGercekKunyelerle(unittest.TestCase):
	"""Halka 1-2: koşumda verilen kararlar, tablodan AYNEN yeniden çıkmalı."""

	def test_dort_gercek_dosyanin_karari_fixture_ile_ayni(self) -> None:
		for url, beklenen in FX["decisions"].items():
			facts = _facts_from(FX["facts"][url])
			karar = decide(facts)
			self.assertEqual(karar.action, beklenen["action"], url)
			self.assertEqual(karar.rule_id, beklenen["rule_id"], url)
			self.assertEqual(karar.code, beklenen["code"], url)

	def test_9mb_remux_karari_moov_sondan_geliyor(self) -> None:
		facts = _facts_from(FX["facts"]["/files/9mb.mp4"])
		self.assertTrue(facts.moov_at_end)
		self.assertEqual(decide(facts).rule_id, "moov_at_end")

	def test_hls_gerekliligi_sure_uzerinden(self) -> None:
		for url, beklenen in FX["decisions"].items():
			facts = _facts_from(FX["facts"][url])
			self.assertEqual(
				H.hls_required(facts).required, beklenen["hls_required"], url
			)


class FaydaKapisiGercekBaytlarla(unittest.TestCase):
	"""Halka 3: INV-05 — panel kartındaki 'bütçe'nin ilk gerçek sınaması."""

	def test_kapinin_esigi_tablodan_ve_olculen_degerde(self) -> None:
		# Vacuity çapası: tablo eşiği kurcalanırsa bu test KIRMIZI olur.
		self.assertEqual(T.min_saving_ratio(), FX["gate_probe"]["min_saving_ratio"])

	def test_gercek_cikti_kapiyi_gecti(self) -> None:
		g = FX["gate_probe"]
		kazanc = (g["src_bytes"] - g["out_bytes"]) / g["src_bytes"]
		self.assertAlmostEqual(kazanc, g["saving_ratio"], places=4)
		self.assertEqual(kazanc >= T.min_saving_ratio(), g["accepted"])
		self.assertTrue(g["accepted"])

	def test_kurcalanmis_esik_ayni_ciktiyi_reddederdi(self) -> None:
		# Kapı bu gerçek veri noktasında AYIRT EDİYOR: %11,44 kazanç %10'u
		# geçer, %20'yi geçemez. Her şeyi kabul eden bir kapı burada düşer.
		g = FX["gate_probe"]
		self.assertGreaterEqual(g["saving_ratio"], 0.1)
		self.assertLess(g["saving_ratio"], 0.2)

	def test_bitrate_tavani_kapidan_turetildi(self) -> None:
		g = FX["gate_probe"]
		url = g["url"]
		facts = _facts_from(FX["facts"][url])
		spec = T.H264Spec.from_table()
		self.assertEqual(T.rate_ceiling_kbps(spec, facts), g["rate_ceiling_kbps"])
		# Türetme formülünün kendisi: kaynak_kbps × (1 − eşik) − ses_kbps.
		beklenen = int(round(g["src_total_kbps"] * (1.0 - T.min_saving_ratio()))) - spec.audio_bitrate_kbps
		self.assertEqual(g["rate_ceiling_kbps"], beklenen)


class KaliteKapisiOlcumleri(unittest.TestCase):
	"""Halka 4: VMAF gerçekten ölçüldü — ve eşiğin ALTINDA çıktı."""

	def test_vmaf_olculdu_ve_esigin_altinda(self) -> None:
		v = FX["vmaf"]
		self.assertTrue(v["measured"])
		self.assertEqual(v["metric"], "vmaf")
		# Ölçülen 89,34 < eşik 93: kapı bugün hiçbir yerde UYGULANMIYOR;
		# bu test o boşluğun kaydıdır. Eşik uygulanmaya başlarsa ve bu çıktı
		# reddedilirse fixture'ın yeni koşumla yenilenmesi gerekir.
		self.assertLess(v["vmaf"], v["vmaf_min_esigi"])
		self.assertEqual(v["vmaf_min_esigi"], T.vmaf_min())

	def test_sure_kapisi_olctu_ama_atmadi(self) -> None:
		dg = FX["gate_probe"]["duration_gate"]
		self.assertEqual(dg["duration_gate"], "DUSTU")
		self.assertGreater(dg["duration_delta_s"], dg["max_duration_delta_s"])
		# Buna rağmen çıktı kabul edildi — tasarım: sapmış süre, hiç dosya
		# olmamasından iyidir (tablo `quality_gate.duration_note`).
		self.assertTrue(FX["gate_probe"]["accepted"])


class HlsMerdiveniGercekKaynakla(unittest.TestCase):
	"""Halka 6: 720 kısa kenarlı gerçek kaynakta merdiven 1080p İLAN ETMEZ."""

	def test_secilen_merdiven_buyutme_yapmaz(self) -> None:
		facts = _facts_from(FX["facts"]["/files/9mb.mp4"])
		secilen = [r.name for r in H.select_ladder(facts)]
		self.assertEqual(secilen, FX["hls"]["selected_ladder"])
		self.assertNotIn("1080p", secilen)

	def test_master_iceriginde_1080p_yok(self) -> None:
		cozunurlukler = [e["RESOLUTION"] for e in FX["hls"]["master_entries"]]
		self.assertEqual(len(cozunurlukler), 3)
		self.assertNotIn("1920x1080", cozunurlukler)
		self.assertIn("640x360", cozunurlukler)

	def test_acilis_butcesi_gecti(self) -> None:
		spec = H.HlsSpec.from_table()
		for v in FX["hls"]["variants"]:
			self.assertEqual(v["startup_gate"], "GECTI", v["name"])
			self.assertLessEqual(v["startup_bytes"], spec.startup_max_bytes, v["name"])

	def test_720p_basamagi_kaynaktan_buyuk_cikti_kaydi(self) -> None:
		# Ölçülmüş tasarım boşluğu kaydı: HLS basamağında fayda kapısı YOK;
		# 142 kbps'lik verimli kaynakta 720p basamağı kaynaktan büyük çıktı.
		v720 = next(v for v in FX["hls"]["variants"] if v["name"] == "720p")
		self.assertGreater(v720["bytes"], FX["hls"]["src_bytes"])


@unittest.skipUnless(SITE_PUBLIC.is_dir(), "DEV site diski yok — konteynerde koşulur")
class DevDiskindekiCiktilar(unittest.TestCase):
	"""Halka 5-6 disk doğrulaması: W6 koşumunun yazdıkları yerinde mi."""

	def test_uretilen_dosyalar_diskte(self) -> None:
		for ad, gorece in FX["produced_paths"].items():
			yol = SITE_PUBLIC / gorece
			self.assertTrue(yol.is_file(), f"{ad}: {yol}")
			self.assertGreater(yol.stat().st_size, 0, ad)

	def test_remux_ciktisinda_moov_basta(self) -> None:
		yol = SITE_PUBLIC / FX["produced_paths"]["remux_4419"]
		self.assertFalse(P.moov_at_end_of(str(yol)))

	def test_poster_baytlari_fixture_ile_ayni(self) -> None:
		yol = SITE_PUBLIC / FX["produced_paths"]["poster_4043"]
		self.assertEqual(yol.stat().st_size, FX["poster"]["LST-04043"]["size_bytes"])

	def test_master_playlist_diskte_3_basamak(self) -> None:
		yol = SITE_PUBLIC / FX["produced_paths"]["hls_master_4419"]
		girisler = H.parse_master(str(yol))
		self.assertEqual(len(girisler), 3)
		self.assertEqual(
			sorted(e.get("RESOLUTION") for e in girisler),
			sorted(e["RESOLUTION"] for e in FX["hls"]["master_entries"]),
		)


if __name__ == "__main__":
	unittest.main()

# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-141 S7/S8 — vitrin Playwright'ının BENCH-YARDIMCILI ölçüm ucu (W8).

Şartname (`72-faz14-test-kabul.html` → T-141):
  · S7: "Verimli 10 MB MP4 yüklenir → dokunulmaz" — kabul ölçütü bayt
    kimliğidir ve tarayıcıdan görünmez.
  · S8: "Şişik bitrate video yüklenir → küçülür, VMAF ≥ 93" — VMAF referanslı
    bir kalite metriğidir; ölçüm ffmpeg+libvmaf ile backend'de yapılır.

Bu modül `tradehubfront/tests/e2e/media-video-pipeline.spec.ts` tarafından

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        execute tradehub_core.tests.t141_bench.s7_verimli_video_dokunulmaz

deseniyle çağrılır; her fonksiyon JSON'a çevrilebilir TEK sözlük döner
(`bench execute` dönen değeri json.dumps ile basar). İddiaları BURASI vermez —
sayıları ölçer, kararı Playwright tarafındaki test verir. Böylece "sahte
yeşil" iki uçta da imkânsız: burada assert yok, orada ölçüm yok.

DİKKAT (görev şartı): `vmaf_min` kapısı gerçek türevi ATABİLİR (rapor 84 §3:
89,31 < 93 vakası). S8 fonksiyonu bu yüzden kapının SONUCUNU raporlar
(`accepted`, `vmaf`, `vmaf_gate`, eşik) — "türev üretildi" varsayımı yok.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Any

FIXTURE_DIR: str = os.path.join(
	os.path.dirname(os.path.abspath(__file__)), "fixtures", "media", "video"
)
S7_FIXTURE: str = os.path.join(FIXTURE_DIR, "video_efficient_720p_750k.mp4")
S8_FIXTURE: str = os.path.join(FIXTURE_DIR, "video_bloated_720p_8m.mp4")


def _sha256(yol: str) -> str:
	h = hashlib.sha256()
	with open(yol, "rb") as f:
		for parca in iter(lambda: f.read(1024 * 1024), b""):
			h.update(parca)
	return h.hexdigest()


def s7_verimli_video_dokunulmaz() -> dict[str, Any]:
	"""S7 ölçümü: verimli kaynak için karar + kararın uygulanma izi.

	"Dokunulmadı" iddiasının ölçülebilir üç yüzü: (1) karar PASSTHROUGH ve
	yeni dosya yazmayacağını söylüyor, (2) `apply_decision` ffmpeg koşturmadan
	kaynağı koruyarak dönüyor ve hedefe hiçbir şey yazmıyor, (3) kaynak
	dosyanın SHA-256'sı koşumdan önce ve sonra AYNI.
	"""
	from tradehub_core.media.pipeline.video import decision, probe, transcode

	once_sha = _sha256(S7_FIXTURE)
	facts = probe.probe(S7_FIXTURE)
	karar = decision.decide(facts)
	cikti: dict[str, Any] = {
		"fixture": os.path.basename(S7_FIXTURE),
		"src_bytes": os.path.getsize(S7_FIXTURE),
		"probe_measured": bool(facts.measured),
		"action": karar.action,
		"rule_id": karar.rule_id,
		"writes_new_file": bool(karar.writes_new_file),
	}
	with tempfile.TemporaryDirectory() as d:
		dst = os.path.join(d, "out.mp4")
		sonuc = transcode.apply_decision(S7_FIXTURE, dst, karar, facts=facts)
		cikti.update(
			{
				"accepted": bool(sonuc.accepted),
				"kept_source": bool(sonuc.kept_source),
				"out_file_written": os.path.exists(dst),
				"out_bytes": int(sonuc.out_bytes or 0),
				"notes": list(sonuc.notes),
			}
		)
	cikti["source_sha_unchanged"] = _sha256(S7_FIXTURE) == once_sha
	return cikti


def s8_sisik_video_kapi_sonucu() -> dict[str, Any]:
	"""S8 ölçümü: şişik kaynakta ÜRETİM YOLU kapılarıyla transcode sonucu.

	İki kapı da AÇIK (fayda + `vmaf_min`; `_produce_video_primary` ile aynı).
	VMAF ölçülemiyorsa (libvmaf'sız imaj) `vmaf_gate=OLCULEMEDI` döner ve
	sayı uydurulmaz — o durumda S8'in VMAF iddiası test tarafında SKIP olmalı.
	"""
	from tradehub_core.media.pipeline.video import decision, probe, transcode

	facts = probe.probe(S8_FIXTURE)
	karar = decision.decide(facts)
	with tempfile.TemporaryDirectory() as d:
		dst = os.path.join(d, "out.mp4")
		sonuc = transcode.transcode(S8_FIXTURE, dst, facts=facts)
		return {
			"fixture": os.path.basename(S8_FIXTURE),
			"decision_action": karar.action,
			"decision_rule": karar.rule_id,
			"vmaf_available": transcode.vmaf_available(),
			"src_bytes": int(sonuc.src_bytes or 0),
			"out_bytes": int(sonuc.out_bytes or 0),
			"saving_ratio": round(float(sonuc.saving_ratio), 4),
			"accepted": bool(sonuc.accepted),
			"kept_source": bool(sonuc.kept_source),
			"delivered_file_exists": os.path.exists(dst),
			"vmaf": sonuc.quality.get("vmaf"),
			"vmaf_gate": sonuc.quality.get("vmaf_gate"),
			"vmaf_min": sonuc.quality.get("vmaf_min", transcode.vmaf_min()),
			"notes": list(sonuc.notes),
		}

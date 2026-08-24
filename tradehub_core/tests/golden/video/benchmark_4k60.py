#!/usr/bin/env python3
"""T-075 — 60 saniyeyi aşan 4K60 kaynağın ölçülebilir kaynak regresyonu.

Fixture binary olarak repoya konmaz; manifestteki deterministik lavfi tarifiyle
üretilir. Fixture üretim süresi bütçeye dahil değildir. Ölçülen bölüm üretim
H.264 ayarlarını, INV-05'i, teslim bütünlüğü kapısını ve rlimit'leri kullanır.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.security import isolation  # noqa: E402
from tradehub_core.media.pipeline.video import decision, probe, transcode  # noqa: E402

HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "manifest.json"


def _manifest() -> dict[str, Any]:
	return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _generate_fixture(path: Path, fixture: dict[str, Any]) -> isolation.IsolationResult:
	cmd = [
		"ffmpeg", "-hide_banner", "-y",
		"-f", "lavfi",
		"-i", (
			f"testsrc2=size={fixture['width']}x{fixture['height']}:"
			f"rate={fixture['fps']}:duration={fixture['duration_s']}"
		),
		"-f", "lavfi",
		"-i", f"sine=frequency=880:sample_rate={fixture['audio_hz']}:duration={fixture['duration_s']}",
		"-map", "0:v:0", "-map", "1:a:0",
		"-c:v", "libx264", "-threads:v", "2", "-preset", "ultrafast", "-crf", "30",
		"-pix_fmt", "yuv420p",
		"-c:a", "aac", "-b:a", "128k",
		"-shortest", "-movflags", "+faststart",
		"-progress", "pipe:1", "-nostats",
		str(path),
	]
	# Üretim, ölçülen transcode bütçesinden ayrıdır ama yine worker'ı
	# öldüremeyecek aynı bellek/dosya limitleri altında çalışır.
	return isolation.run_command(
		cmd,
		limits=isolation.VIDEO_LIMITS.with_(wall_timeout_s=600.0, cpu_seconds=1100, nice=None),
	)


def run(fixture_path: Path | None = None) -> tuple[dict[str, Any], int]:
	tarif = _manifest()
	fixture = tarif["fixture"]
	budgets = tarif["budgets"]
	temp_dir = Path(tempfile.mkdtemp(prefix="faz7-4k60-"))
	generated = fixture_path is None
	src = fixture_path or temp_dir / "source-4k60.mp4"
	dst = temp_dir / "delivery-1280.mp4"
	report: dict[str, Any] = {
		"schema_version": "1.0.0",
		"task": "T-075",
		"measured_at": datetime.now(timezone.utc).isoformat(),
		"environment": {
			"python": platform.python_version(),
			"platform": platform.platform(),
			"cpu_count_visible": os.cpu_count(),
		},
		"fixture": dict(fixture),
		"budgets": dict(budgets),
		"generated": generated,
	}
	try:
		if generated:
			generation = _generate_fixture(src, fixture)
			report["fixture_generation"] = generation.to_dict()
			if not generation.ok:
				report["passed"] = False
				report["failure"] = f"fixture_generation:{generation.sebep}"
				return report, 2
		elif not src.is_file():
			report.update({"passed": False, "failure": "fixture_missing"})
			return report, 2

		facts = probe.probe(str(src))
		karar = decision.decide(facts)
		report["source"] = facts.as_dict()
		report["decision"] = karar.as_dict()
		if not facts.measured:
			report.update({"passed": False, "failure": f"probe:{facts.error}"})
			return report, 2

		sonuc = transcode.transcode(
			str(src),
			str(dst),
			facts=facts,
			timeout=int(budgets["wall_s_max"]),
			enforce_benefit_gate=True,
			# VMAF korpus kapısı ayrı gerçek fixture suitinde çalışır; bu koşumun
			# konusu CPU/RAM/concurrency ve teslim bütünlüğüdür.
			enforce_quality_gate=False,
			enforce_delivery_gate=True,
		)
		report["transcode"] = sonuc.as_dict()
		if sonuc.accepted and dst.is_file():
			report["output"] = probe.probe(str(dst)).as_dict()

		cpu_s = sonuc.cpu_user_s + sonuc.cpu_system_s
		checks = {
			"fixture_exact_4k60": (
				facts.width == int(fixture["width"])
				and facts.height == int(fixture["height"])
				and abs(facts.fps - float(fixture["fps"])) < 0.1
				and facts.duration_s > 60.0
			),
			"decision_transcode": karar.action == decision.ACTION_TRANSCODE,
			"source_preserved_or_valid_output": bool(sonuc.accepted or sonuc.kept_source),
			"inv05": bool(
				(sonuc.accepted and sonuc.saving_ratio >= transcode.min_saving_ratio())
				or sonuc.kept_source
			),
			"wall_budget": sonuc.wall_s <= float(budgets["wall_s_max"]),
			"cpu_budget": cpu_s <= float(budgets["cpu_s_max"]),
			"rss_budget": sonuc.peak_rss_bytes <= int(budgets["peak_rss_bytes_max"]),
			"rlimit_memory": "RLIMIT_AS" in sonuc.limits_applied,
			"rss_watchdog": "RSS_WATCHDOG" in sonuc.limits_applied,
			"rlimit_cpu": "RLIMIT_CPU" in sonuc.limits_applied,
			"delivery_integrity": all(
				sonuc.quality.get(k) in ("GECTI", "UYGULANMAZ")
				for k in ("duration_gate", "av_sync_gate", "first_frame_gate")
			),
		}
		report["checks"] = checks
		report["passed"] = all(checks.values())
		return report, 0 if report["passed"] else 1
	finally:
		shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--fixture", type=Path, help="Üretmek yerine mevcut 4K60 dosyayı kullan")
	parser.add_argument("--output", type=Path, help="JSON rapor yolu")
	parser.add_argument("--assert-budgets", action="store_true", help="Kapı düşerse sıfır-dışı çık")
	args = parser.parse_args()
	report, code = run(args.fixture)
	metin = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
	if args.output:
		args.output.parent.mkdir(parents=True, exist_ok=True)
		args.output.write_text(metin, encoding="utf-8")
	print(metin, end="")
	return code if args.assert_budgets else 0


if __name__ == "__main__":
	raise SystemExit(main())

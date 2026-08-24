#!/usr/bin/env python3
"""T-013 adaptif seçim ile sabit q85'i kimliksiz gerçek ürünlerde kıyasla."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.quality import compute_ssim, select_quality  # noqa: E402
from tradehub_core.media.pipeline.quality.adaptive import _encode, _prepared  # noqa: E402


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--manifest", default=".smartcrop-work/manifest.json")
	parser.add_argument("--output", default="docs/data/t013-adaptive-vs-q85.json")
	parser.add_argument("--count", type=int, default=10)
	parser.add_argument("--max-dim", type=int, default=1200)
	parser.add_argument("--target-ssim", type=float, default=0.96)
	args = parser.parse_args()
	manifest_path = (ROOT / args.manifest).resolve()
	manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
	items = list(manifest.get("items") or [])[: args.count]
	if len(items) < args.count:
		raise SystemExit(f"örnek sayısı yetersiz: {len(items)} < {args.count}")

	rows = []
	for item in items:
		path = manifest_path.parent / item["image"]
		content = path.read_bytes()
		reference = _prepared(content, args.max_dim)
		for fmt in ("jpeg", "webp", "avif"):
			try:
				adaptive = select_quality(
					content,
					fmt=fmt,
					target_ssim=args.target_ssim,
					content_class="photo",
					max_dim=args.max_dim,
				)
				q85 = _encode(reference, fmt, 85)
				q85_ssim = compute_ssim(reference, q85).value
				rows.append(
					{
						"id": item["id"],
						"format": fmt,
						"adaptive_quality": adaptive.quality,
						"adaptive_ssim": round(adaptive.ssim, 6),
						"adaptive_bytes": adaptive.size_bytes,
						"adaptive_encodes": adaptive.encodes,
						"adaptive_target_met": adaptive.ssim >= args.target_ssim,
						"adaptive_reason": adaptive.reason,
						"q85_ssim": round(q85_ssim, 6),
						"q85_bytes": len(q85),
						"q85_target_met": q85_ssim >= args.target_ssim,
						"bytes_vs_q85_ratio": round(adaptive.size_bytes / max(1, len(q85)), 6),
					}
				)
			except Exception as exc:
				rows.append({"id": item["id"], "format": fmt, "error": f"{type(exc).__name__}: {exc}"})

	summary = {}
	for fmt in ("jpeg", "webp", "avif"):
		valid = [row for row in rows if row.get("format") == fmt and not row.get("error")]
		lossy = [row for row in valid if row.get("adaptive_quality") != "lossless"]
		lossless = [row for row in valid if row.get("adaptive_quality") == "lossless"]
		summary[fmt] = {
			"samples": len(valid),
			"lossy_samples": len(lossy),
			"lossless_required_samples": len(lossless),
			"adaptive_target_met": sum(bool(row["adaptive_target_met"]) for row in valid),
			"q85_target_met": sum(bool(row["q85_target_met"]) for row in valid),
			"max_encodes": max((int(row["adaptive_encodes"]) for row in valid), default=0),
			"adaptive_bytes_mean": round(statistics.fmean(row["adaptive_bytes"] for row in valid), 2) if valid else None,
			"q85_bytes_mean": round(statistics.fmean(row["q85_bytes"] for row in valid), 2) if valid else None,
			"bytes_vs_q85_ratio_mean": round(statistics.fmean(row["bytes_vs_q85_ratio"] for row in valid), 6) if valid else None,
			"lossy_bytes_vs_q85_ratio_mean": round(statistics.fmean(row["bytes_vs_q85_ratio"] for row in lossy), 6) if lossy else None,
		}

	doc = {
		"schema_version": "1.0.0",
		"task": "T-013",
		"measured_at": datetime.now(timezone.utc).isoformat(),
		"source": "50-image anonymized live Listing sample; first deterministic N",
		"sample_count": len(items),
		"target_ssim": args.target_ssim,
		"max_dim": args.max_dim,
		"fixed_baseline_quality": 85,
		"summary": summary,
		"rows": rows,
	}
	output = (ROOT / args.output).resolve()
	output.parent.mkdir(parents=True, exist_ok=True)
	output.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	print(json.dumps({"ok": True, "output": str(output), "summary": summary}, ensure_ascii=False))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

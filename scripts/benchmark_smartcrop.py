#!/usr/bin/env python3
"""T-014 üç smartcrop yöntemini 50 görselde ölç ve JSON kanıtı üret."""

from __future__ import annotations

import argparse

import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.core.smartcrop import (  # noqa: E402
	METHOD_BACKGROUND,
	METHOD_ENTROPY_EDGE,
	METHOD_ONNX,
	SmartcropError,
	background_segmentation,
	entropy_edge,
	normalized_error,
	onnx_u2netp,
)


def percentile(values: list[float], p: float) -> float | None:
	if not values:
		return None
	ordered = sorted(values)
	index = max(0, min(len(ordered) - 1, math.ceil((p / 100.0) * len(ordered)) - 1))
	return float(ordered[index])


def aggregate(rows: list[dict], *, model_bytes: int = 0) -> dict:
	runtimes = [float(row["runtime_ms"]) for row in rows if row.get("ok")]
	errors = [float(row["error"]) for row in rows if row.get("error") is not None]
	plain = [float(row["error"]) for row in rows if row.get("error") is not None and row.get("background") == "plain"]
	complex_ = [float(row["error"]) for row in rows if row.get("error") is not None and row.get("background") == "complex"]
	return {
		"attempted": len(rows),
		"successful": sum(1 for row in rows if row.get("ok")),
		"runtime_ms_mean": round(statistics.fmean(runtimes), 4) if runtimes else None,
		"runtime_ms_p90": round(percentile(runtimes, 90), 4) if runtimes else None,
		"working_set_estimate_mb_max": round(max((row.get("working_set_estimate_bytes", 0) for row in rows), default=0) / 1024**2, 4),
		"model_mb": round(model_bytes / 1024**2, 4),
		"normalized_error_mean": round(statistics.fmean(errors), 6) if errors else None,
		"normalized_error_p90": round(percentile(errors, 90), 6) if errors else None,
		"plain_background_error_mean": round(statistics.fmean(plain), 6) if plain else None,
		"complex_background_error_mean": round(statistics.fmean(complex_), 6) if complex_ else None,
	}


def calibrate_threshold(rows: list[dict], good_error: float = 0.10) -> dict | None:
	labeled = [row for row in rows if row.get("error") is not None and row.get("ok")]
	if len(labeled) < 50:
		return None
	best = None
	for threshold in [step / 100.0 for step in range(0, 101, 5)]:
		tp = sum(1 for row in labeled if row["confidence"] >= threshold and row["error"] <= good_error)
		fp = sum(1 for row in labeled if row["confidence"] >= threshold and row["error"] > good_error)
		fn = sum(1 for row in labeled if row["confidence"] < threshold and row["error"] <= good_error)
		precision = tp / (tp + fp) if tp + fp else 0.0
		recall = tp / (tp + fn) if tp + fn else 0.0
		f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
		candidate = (f1, precision, recall, threshold)
		if best is None or candidate > best:
			best = candidate
	return {
		"threshold": best[3],
		"good_error_max": good_error,
		"f1": round(best[0], 6),
		"precision": round(best[1], 6),
		"recall": round(best[2], 6),
	}


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--manifest", default=".smartcrop-work/manifest.json")
	parser.add_argument("--labels", default="", help="annotate.html çıktısı ground-truth.json")
	parser.add_argument("--model", default=".smartcrop-work/u2netp.onnx")
	parser.add_argument("--output", default="docs/data/t014-smartcrop-benchmark.json")
	args = parser.parse_args()
	manifest_path = (ROOT / args.manifest).resolve() if not Path(args.manifest).is_absolute() else Path(args.manifest)
	manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
	items = list(manifest.get("items") or [])
	if len(items) < 50:
		raise SystemExit(f"benchmark en az 50 görsel ister; bulunan={len(items)}")
	labels: dict[str, dict] = {}
	if args.labels:
		labels_path = (ROOT / args.labels).resolve() if not Path(args.labels).is_absolute() else Path(args.labels)
		label_doc = json.loads(labels_path.read_text(encoding="utf-8"))
		if label_doc.get("label_type") != "human_click" or not label_doc.get("labeler"):
			raise SystemExit("etiket dosyası human_click türü ve labeler taşımalıdır")
		labels = {str(item["id"]): item for item in label_doc.get("items") or []}
		if len(labels) < 50:
			raise SystemExit(f"insan etiketi 50'den az: {len(labels)}")

	model_path = (ROOT / args.model).resolve() if not Path(args.model).is_absolute() else Path(args.model)
	session = None
	model_error = ""
	if model_path.is_file():
		try:
			import onnxruntime as ort

			session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
		except Exception as exc:
			model_error = f"{type(exc).__name__}: {exc}"
	else:
		model_error = "model_missing"

	by_method = {METHOD_ENTROPY_EDGE: [], METHOD_BACKGROUND: [], METHOD_ONNX: []}
	for item in items[:50]:
		image_path = manifest_path.parent / item["image"]
		label = labels.get(str(item["id"]))
		for method, fn in ((METHOD_ENTROPY_EDGE, entropy_edge), (METHOD_BACKGROUND, background_segmentation)):
			try:
				prediction = fn(image_path)
				row = {"id": item["id"], "ok": True, **prediction.to_dict()}
			except Exception as exc:
				row = {"id": item["id"], "ok": False, "reason": f"{type(exc).__name__}: {exc}"}
			if label:
				row["error"] = normalized_error(prediction, label["focal_x"], label["focal_y"]) if row["ok"] else None
				row["background"] = label.get("background")
			else:
				row["error"] = None
			by_method[method].append(row)

		if session is None:
			row = {"id": item["id"], "ok": False, "reason": model_error, "error": None}
		else:
			try:
				prediction = onnx_u2netp(image_path, model_path=model_path, session=session)
				row = {"id": item["id"], "ok": True, **prediction.to_dict()}
			except (SmartcropError, Exception) as exc:
				row = {"id": item["id"], "ok": False, "reason": f"{type(exc).__name__}: {exc}"}
			if label:
				row["error"] = normalized_error(prediction, label["focal_x"], label["focal_y"]) if row["ok"] else None
				row["background"] = label.get("background")
			else:
				row["error"] = None
		by_method[METHOD_ONNX].append(row)

	model_bytes = model_path.stat().st_size if model_path.is_file() else 0
	try:
		model_display = str(model_path.relative_to(ROOT))
	except ValueError:
		model_display = model_path.name
	aggregates = {
		method: aggregate(rows, model_bytes=model_bytes if method == METHOD_ONNX else 0)
		for method, rows in by_method.items()
	}
	calibration = {method: calibrate_threshold(rows) for method, rows in by_method.items()}
	result = {
		"schema_version": "1.0.0",
		"task": "T-014",
		"measured_at": datetime.now(timezone.utc).isoformat(),
		"images": 50,
		"human_labels": len(labels),
		"threshold_calibrated": len(labels) >= 50 and any(calibration.values()),
		"memory_metric": "estimated live numpy/Pillow buffers; not process RSS",
		"model": {
			"path": model_display,
			"bytes": model_bytes,
			"available": session is not None,
			"error": model_error,
		},
		"methods": aggregates,
		"calibration": calibration,
		"rows": by_method,
	}
	output = (ROOT / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
	output.parent.mkdir(parents=True, exist_ok=True)
	output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	print(json.dumps({"ok": True, "output": str(output), "images": 50, "human_labels": len(labels), "onnx": session is not None}))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

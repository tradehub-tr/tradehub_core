"""T-014 — üç yöntemli smartcrop odak noktası prototipi.

Yöntemler aynı, normalize ``(focal_x, focal_y)`` sözleşmesini döndürür:

* ``entropy_edge`` — kenar + yerel entropi + doygunluk enerjisi,
* ``background_segmentation`` — kenar piksellerinden düz zemin tahmini,
* ``onnx_u2netp`` — 320×320 U²-Net-P saliency maskesi.

``confidence`` model doğruluğu değildir; yöntemin kendi sinyal yoğunluğudur.
İnsan etiketli hata ölçülmeden eşik kalibre edilmiş sayılmaz.
"""

from __future__ import annotations

import io
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

METHOD_ENTROPY_EDGE = "entropy_edge"
METHOD_BACKGROUND = "background_segmentation"
METHOD_ONNX = "onnx_u2netp"
METHODS: tuple[str, ...] = (METHOD_ENTROPY_EDGE, METHOD_BACKGROUND, METHOD_ONNX)


class SmartcropError(ValueError):
	"""Smartcrop girdisi veya model sözleşmesi geçersiz."""


@dataclass(frozen=True)
class SmartcropPrediction:
	method: str
	focal_x: float
	focal_y: float
	confidence: float
	bbox: tuple[float, float, float, float]
	runtime_ms: float
	working_set_estimate_bytes: int
	model_bytes: int = 0
	available: bool = True
	reason: str = ""

	def to_dict(self) -> dict[str, Any]:
		return {
			"method": self.method,
			"focal_x": round(self.focal_x, 8),
			"focal_y": round(self.focal_y, 8),
			"confidence": round(self.confidence, 8),
			"bbox": [round(value, 8) for value in self.bbox],
			"runtime_ms": round(self.runtime_ms, 4),
			"working_set_estimate_bytes": self.working_set_estimate_bytes,
			"model_bytes": self.model_bytes,
			"available": self.available,
			"reason": self.reason,
		}


def _image(source):
	from PIL import Image, ImageOps

	if isinstance(source, Image.Image):
		return ImageOps.exif_transpose(source).convert("RGB")
	if isinstance(source, (str, Path)):
		with Image.open(str(source)) as image:
			return ImageOps.exif_transpose(image).convert("RGB")
	with Image.open(io.BytesIO(bytes(source))) as image:
		return ImageOps.exif_transpose(image).convert("RGB")


def _numpy():
	try:
		import numpy as np
	except Exception as exc:
		raise SmartcropError("smartcrop prototipi numpy gerektirir") from exc
	return np


def _preview(source, max_edge: int = 320):
	from PIL import Image

	image = _image(source)
	image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
	return image


def _bbox_from_mask(np, mask) -> tuple[float, float, float, float]:
	y, x = np.nonzero(mask)
	h, w = mask.shape
	if not len(x):
		return (0.0, 0.0, 1.0, 1.0)
	x0, x1 = int(x.min()), int(x.max()) + 1
	y0, y1 = int(y.min()), int(y.max()) + 1
	return (x0 / w, y0 / h, (x1 - x0) / w, (y1 - y0) / h)


def _prediction(method: str, weights, started: float, *, model_bytes: int = 0, extra_bytes: int = 0):
	np = _numpy()
	weights = np.asarray(weights, dtype=np.float32)
	h, w = weights.shape
	total = float(weights.sum())
	working = int(weights.nbytes + extra_bytes)
	if not math.isfinite(total) or total <= 1e-8:
		return SmartcropPrediction(
			method, 0.5, 0.5, 0.0, (0.0, 0.0, 1.0, 1.0),
			(time.perf_counter() - started) * 1000.0, working, model_bytes,
			reason="no_signal",
		)
	yy, xx = np.mgrid[0:h, 0:w]
	focal_x = float(((xx + 0.5) * weights).sum() / total / w)
	focal_y = float(((yy + 0.5) * weights).sum() / total / h)
	positive = weights > max(float(weights.max()) * 0.35, float(weights.mean()))
	bbox = _bbox_from_mask(np, positive)
	# Enerjinin en yoğun %25 pikseldeki payı; homojen harita 0'a yaklaşır.
	flat = np.sort(weights.ravel())
	k = max(1, int(flat.size * 0.25))
	share = float(flat[-k:].sum() / total)
	confidence = max(0.0, min(1.0, (share - 0.25) / 0.75))
	return SmartcropPrediction(
		method=method,
		focal_x=max(0.0, min(1.0, focal_x)),
		focal_y=max(0.0, min(1.0, focal_y)),
		confidence=confidence,
		bbox=bbox,
		runtime_ms=(time.perf_counter() - started) * 1000.0,
		working_set_estimate_bytes=working,
		model_bytes=model_bytes,
	)


def entropy_edge(source, *, max_edge: int = 256) -> SmartcropPrediction:
	"""Kenar, doygunluk ve 16×16 yerel entropi enerjisinin ağırlık merkezi."""
	started = time.perf_counter()
	np = _numpy()
	image = _preview(source, max_edge)
	rgb = np.asarray(image, dtype=np.float32)
	gray = rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114
	gx = np.zeros_like(gray)
	gy = np.zeros_like(gray)
	gx[:, 1:] = np.abs(gray[:, 1:] - gray[:, :-1])
	gy[1:, :] = np.abs(gray[1:, :] - gray[:-1, :])
	edge = np.hypot(gx, gy) / 360.624
	saturation = (rgb.max(axis=2) - rgb.min(axis=2)) / 255.0

	entropy = np.zeros_like(gray, dtype=np.float32)
	tile = 16
	for top in range(0, gray.shape[0], tile):
		for left in range(0, gray.shape[1], tile):
			block = gray[top : top + tile, left : left + tile]
			hist, _ = np.histogram(block, bins=32, range=(0, 256))
			prob = hist[hist > 0].astype(np.float64) / max(1, block.size)
			value = float(-(prob * np.log2(prob)).sum() / 5.0)
			entropy[top : top + tile, left : left + tile] = value
	weights = edge * 0.65 + saturation * 0.20 + entropy * 0.15
	return _prediction(
		METHOD_ENTROPY_EDGE,
		weights,
		started,
		extra_bytes=int(rgb.nbytes + gray.nbytes + gx.nbytes + gy.nbytes + saturation.nbytes + entropy.nbytes),
	)


def background_segmentation(source, *, max_edge: int = 320) -> SmartcropPrediction:
	"""Kenar örneğinden düz zemin rengi çıkar ve ön plan ağırlık merkezini bul."""
	started = time.perf_counter()
	np = _numpy()
	image = _preview(source, max_edge)
	rgb = np.asarray(image, dtype=np.float32)
	border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]), axis=0)
	background = np.median(border, axis=0)
	distance = np.linalg.norm(rgb - background, axis=2)
	border_distance = np.linalg.norm(border - background, axis=1)
	threshold = max(18.0, float(np.percentile(border_distance, 95)) * 2.5)
	mask = distance > threshold
	# Tek tük JPEG gürültüsü odak sayılmaz: yatay+dikey komşudan en az biri.
	neighbor = np.zeros_like(mask)
	neighbor[:, 1:] |= mask[:, :-1]
	neighbor[:, :-1] |= mask[:, 1:]
	neighbor[1:, :] |= mask[:-1, :]
	neighbor[:-1, :] |= mask[1:, :]
	mask &= neighbor
	weights = np.where(mask, np.maximum(distance - threshold, 0.0), 0.0).astype(np.float32)
	return _prediction(
		METHOD_BACKGROUND,
		weights,
		started,
		extra_bytes=int(rgb.nbytes + border.nbytes + distance.nbytes + mask.nbytes + neighbor.nbytes),
	)


def onnx_u2netp(
	source,
	*,
	model_path: str | Path | None = None,
	session=None,
) -> SmartcropPrediction:
	"""U²-Net-P ONNX maskesinden odak çıkar; runtime/model yoksa açık hata ver."""
	started = time.perf_counter()
	np = _numpy()
	model = Path(model_path) if model_path else None
	model_bytes = int(model.stat().st_size) if model and model.is_file() else 0
	if session is None:
		if not model or not model.is_file():
			raise SmartcropError("onnx_u2netp için model_path zorunludur")
		try:
			import onnxruntime as ort
		except Exception as exc:
			raise SmartcropError("onnxruntime kurulu değil") from exc
		session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])

	image = _image(source).resize((320, 320))
	array = np.asarray(image, dtype=np.float32) / 255.0
	array = (array - np.asarray([0.485, 0.456, 0.406], dtype=np.float32)) / np.asarray(
		[0.229, 0.224, 0.225], dtype=np.float32
	)
	tensor = array.transpose(2, 0, 1)[None, ...].astype(np.float32)
	try:
		input_name = session.get_inputs()[0].name
		outputs = session.run(None, {input_name: tensor})
	except Exception as exc:
		raise SmartcropError(f"ONNX inference başarısız: {type(exc).__name__}") from exc
	if not outputs:
		raise SmartcropError("ONNX çıktı üretmedi")
	mask = np.asarray(outputs[0], dtype=np.float32).squeeze()
	if mask.ndim != 2:
		raise SmartcropError(f"ONNX saliency çıktısı 2D değil: shape={mask.shape}")
	low, high = float(mask.min()), float(mask.max())
	mask = (mask - low) / max(high - low, 1e-8)
	return _prediction(
		METHOD_ONNX,
		mask,
		started,
		model_bytes=model_bytes,
		extra_bytes=int(array.nbytes + tensor.nbytes + mask.nbytes),
	)


def normalized_error(prediction: SmartcropPrediction, focal_x: float, focal_y: float) -> float:
	"""Köşeden köşeye uzaklığı 1 sayan normalize Öklid odak hatası."""
	dx = float(prediction.focal_x) - float(focal_x)
	dy = float(prediction.focal_y) - float(focal_y)
	return math.hypot(dx, dy) / math.sqrt(2.0)


__all__ = [
	"METHODS",
	"METHOD_BACKGROUND",
	"METHOD_ENTROPY_EDGE",
	"METHOD_ONNX",
	"SmartcropError",
	"SmartcropPrediction",
	"background_segmentation",
	"entropy_edge",
	"normalized_error",
	"onnx_u2netp",
]

"""T-013 — biçim sınırlarıyla adaptif SSIM kalite seçimi.

``ssim.py`` ölçüm ve ikili arama çekirdeğidir; bu modül JPEG/WebP/AVIF codec
seçimini, biçim başına arama sınırını ve kayıpsız grafik/alfa kararını ekler.
Encode bütçesi baseline q85 ölçümünden bağımsız olarak en fazla dörttür.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tradehub_core.media.pipeline.quality.ssim import (
	DEFAULT_MAX_ENCODES,
	QualitySearchResult,
	guess_content_class,
	search_quality,
)

FORMAT_QUALITY_BOUNDS: dict[str, tuple[int, int]] = {
	"jpeg": (70, 95),
	"webp": (65, 95),
	"avif": (60, 95),
}

DEFAULT_TARGETS: dict[str, float] = {
	"photo": 0.96,
	"graphic": 1.0,
	"text": 1.0,
}

LOSSLESS_FORMATS: frozenset[str] = frozenset({"png", "webp"})


class AdaptiveQualityError(ValueError):
	"""Kalite seçimi güvenilir bir çıktı üretemedi."""


@dataclass(frozen=True)
class AdaptiveQualityResult:
	content: bytes
	requested_format: str
	actual_format: str
	content_class: str
	quality: int | str
	ssim: float
	target_ssim: float
	encodes: int
	lossless: bool
	reason: str = ""
	attempts: tuple[Any, ...] = ()

	@property
	def size_bytes(self) -> int:
		return len(self.content)


def bounds_for(fmt: str) -> tuple[int, int]:
	"""JPEG/WebP/AVIF için kalibre arama sınırını döndür."""
	key = str(fmt or "").strip().lower().replace("jpg", "jpeg")
	try:
		return FORMAT_QUALITY_BOUNDS[key]
	except KeyError as exc:
		raise AdaptiveQualityError(f"Adaptif kalite biçimi desteklenmiyor: {fmt!r}") from exc


def _prepared(content: bytes, max_dim: int):
	from PIL import Image, ImageOps
	import io

	with Image.open(io.BytesIO(content)) as source:
		image = ImageOps.exif_transpose(source)
		image.load()
		if max_dim > 0:
			image.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
		return image.copy()


def has_alpha(image) -> bool:
	return image.mode in ("RGBA", "LA", "PA") or (
		image.mode == "P" and "transparency" in image.info
	)


def requires_lossless(image, content_class: str) -> bool:
	"""Şeffaf veya grafik/metin içerik kayıplı kalite aramasına sokulmaz."""
	return has_alpha(image) or content_class in {"graphic", "text"}


def _lossless_format(requested: str) -> str:
	return requested if requested in LOSSLESS_FORMATS else "png"


def _encode(image, fmt: str, quality: int | str) -> bytes:
	# Faz 6 rendition encoder'ı tek codec uygulamasıdır; burada tekrar edilmez.
	from tradehub_core.media.pipeline.image.render import LOSSLESS, encode

	data, _notes = encode(image, fmt, LOSSLESS if quality == "lossless" else int(quality))
	return data


def select_quality(
	content: bytes,
	*,
	fmt: str,
	target_ssim: float | None = None,
	content_class: str | None = None,
	max_dim: int = 0,
	max_encodes: int = DEFAULT_MAX_ENCODES,
) -> AdaptiveQualityResult:
	"""Hedef SSIM'i tutan en düşük kaliteyi en fazla dört encode ile seç.

	Grafik/metin veya alfa taşıyan girdi kayıpsız yola alınır. JPEG/AVIF
	kayıpsızlığı piksel-eş garanti etmediği için bu durumda gerçek çıktı biçimi
	PNG olur; çağıran ``actual_format`` alanını manifestte kullanmalıdır.
	"""
	if not content:
		raise AdaptiveQualityError("Boş görsel")
	if max_encodes < 1 or max_encodes > DEFAULT_MAX_ENCODES:
		raise AdaptiveQualityError(f"Encode bütçesi 1..{DEFAULT_MAX_ENCODES} olmalıdır")
	requested = str(fmt or "").strip().lower().replace("jpg", "jpeg")
	bounds = bounds_for(requested)
	image = _prepared(content, int(max_dim))
	klass = content_class or guess_content_class(image)
	target = float(DEFAULT_TARGETS.get(klass, DEFAULT_TARGETS["photo"]) if target_ssim is None else target_ssim)

	if requires_lossless(image, klass):
		actual = _lossless_format(requested)
		data = _encode(image, actual, "lossless")
		return AdaptiveQualityResult(
			content=data,
			requested_format=requested,
			actual_format=actual,
			content_class=klass,
			quality="lossless",
			ssim=1.0,
			target_ssim=target,
			encodes=1,
			lossless=True,
			reason="alpha_or_graphic_lossless",
		)

	def encoder(_content: bytes, _max_dim: int, quality: int):
		try:
			return _encode(image, requested, quality), ""
		except Exception as exc:  # codec eklentisi yoksa görünür sonuç
			return b"", f"encode_error:{type(exc).__name__}"

	search: QualitySearchResult = search_quality(
		content,
		target_ssim=target,
		max_dim=int(max_dim),
		quality_range=bounds,
		max_encodes=max_encodes,
		encoder=encoder,
		reference=image,
	)
	if not search.content:
		raise AdaptiveQualityError(f"{requested} encode başarısız: {search.reason}")
	return AdaptiveQualityResult(
		content=search.content,
		requested_format=requested,
		actual_format=requested,
		content_class=klass,
		quality=search.quality,
		ssim=search.ssim,
		target_ssim=target,
		encodes=search.encodes,
		lossless=False,
		reason=search.reason,
		attempts=tuple(search.attempts),
	)


__all__ = [
	"AdaptiveQualityError",
	"AdaptiveQualityResult",
	"DEFAULT_TARGETS",
	"FORMAT_QUALITY_BOUNDS",
	"LOSSLESS_FORMATS",
	"bounds_for",
	"has_alpha",
	"requires_lossless",
	"select_quality",
]

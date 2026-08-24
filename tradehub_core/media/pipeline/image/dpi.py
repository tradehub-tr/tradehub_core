"""T-012 — DPI metadata ve piksel bütçesini birbirinden ayıran prototip.

Bu modülün temel kuralı basittir: DPI fiziksel baskı metadata'sıdır; görüntünün
``width × height`` piksel ölçüsünü değiştirmez. Piksel küçültme kararı yalnız
``max_long_edge`` / ``max_megapixels`` ile verilir ve FR-028 gereği upscale
yapılmaz.

JPEG, PNG ve TIFF DPI'ı yerel konteyner alanında taşır. Pillow WebP/AVIF için
``info['dpi']`` döndürmez; bu iki biçimde X/YResolution EXIF etiketleri yazılır
ve :func:`read_dpi` bu taşınabilir yedeği okur. Sonuç künyesi bu farkı açıkça
``storage='native'`` veya ``storage='exif'`` diye bildirir.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from tradehub_core.media.pipeline.image.normalize import NormalizeSpec, target_size

SUPPORTED_FORMATS: tuple[str, ...] = ("JPEG", "PNG", "TIFF", "WEBP", "AVIF")
NATIVE_DPI_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "TIFF"})

EXIF_X_RESOLUTION = 0x011A
EXIF_Y_RESOLUTION = 0x011B
EXIF_RESOLUTION_UNIT = 0x0128
RESOLUTION_UNIT_INCH = 2


class DpiError(ValueError):
	"""DPI prototipi girdiyi güvenli ve doğrulanabilir biçimde işleyemedi."""


@dataclass(frozen=True)
class DpiInfo:
	dpi: tuple[float, float] | None
	storage: str = "none"


@dataclass(frozen=True)
class DpiRewriteResult:
	content: bytes
	fmt: str
	width: int
	height: int
	dpi: tuple[float, float]
	storage: str
	pixels_preserved: bool


def _format(value: str) -> str:
	fmt = str(value or "").strip().upper()
	if fmt == "JPG":
		fmt = "JPEG"
	if fmt not in SUPPORTED_FORMATS:
		raise DpiError(f"Desteklenmeyen DPI biçimi: {value!r}")
	return fmt


def _number(value: Any) -> float:
	"""Pillow IFDRational, tuple ve sayıları güvenli biçimde ``float`` yap."""
	if isinstance(value, tuple) and len(value) == 2:
		if not value[1]:
			raise ZeroDivisionError("DPI paydası sıfır")
		return float(value[0]) / float(value[1])
	return float(value)


def read_dpi(source: bytes | bytearray | memoryview) -> DpiInfo:
	"""Konteyner DPI'ını, yoksa EXIF X/YResolution etiketlerini oku."""
	from PIL import Image

	with Image.open(io.BytesIO(bytes(source))) as image:
		native = image.info.get("dpi")
		if native and len(native) >= 2:
			try:
				return DpiInfo((_number(native[0]), _number(native[1])), "native")
			except (TypeError, ValueError, ZeroDivisionError):
				pass
		try:
			exif = image.getexif()
			x = exif.get(EXIF_X_RESOLUTION)
			y = exif.get(EXIF_Y_RESOLUTION)
			if x and y and int(exif.get(EXIF_RESOLUTION_UNIT, RESOLUTION_UNIT_INCH)) == RESOLUTION_UNIT_INCH:
				return DpiInfo((_number(x), _number(y)), "exif")
		except (TypeError, ValueError, ZeroDivisionError):
			pass
	return DpiInfo(None, "none")


def _save_kwargs(fmt: str, dpi: int, exif: bytes, icc: bytes | None) -> dict[str, Any]:
	kwargs: dict[str, Any] = {"exif": exif}
	if icc:
		kwargs["icc_profile"] = icc
	if fmt in NATIVE_DPI_FORMATS:
		kwargs["dpi"] = (dpi, dpi)
	if fmt == "JPEG":
		kwargs.update(quality=95, subsampling=0, optimize=True)
	elif fmt == "PNG":
		kwargs.update(optimize=True)
	elif fmt == "TIFF":
		kwargs.update(compression="tiff_deflate")
	elif fmt == "WEBP":
		# DPI-only yeniden yazımda mevcut decode edilmiş pikselleri ikinci kez
		# kayıplı encode etmeyiz.
		kwargs.update(lossless=True, quality=100, method=4)
	elif fmt == "AVIF":
		kwargs.update(quality=100, subsampling="4:4:4")
	return kwargs


def rewrite_dpi(
	content: bytes | bytearray | memoryview,
	*,
	dpi: int = 72,
	fmt: str | None = None,
) -> DpiRewriteResult:
	"""DPI beyanını değiştir; ``width × height`` ölçüsünü kesinlikle koru.

	Bu işlev piksel bütçesi uygulamaz. Küçültme gerekiyorsa önce
	:func:`pixel_cap_size` ile karar verilip normalleştirme motoru çağrılmalıdır.
	"""
	from PIL import Image

	if int(dpi) <= 0:
		raise DpiError("DPI pozitif bir tam sayı olmalıdır")
	raw = bytes(content)
	if not raw:
		raise DpiError("Boş görsel")

	with Image.open(io.BytesIO(raw)) as image:
		image.load()
		source_size = image.size
		out_fmt = _format(fmt or image.format or "")
		exif = image.getexif()
		resolution = Fraction(int(dpi), 1)
		exif[EXIF_X_RESOLUTION] = resolution
		exif[EXIF_Y_RESOLUTION] = resolution
		exif[EXIF_RESOLUTION_UNIT] = RESOLUTION_UNIT_INCH
		icc = image.info.get("icc_profile")
		out = io.BytesIO()
		try:
			image.save(out, out_fmt, **_save_kwargs(out_fmt, int(dpi), exif.tobytes(), icc))
		except Exception as exc:  # Pillow eklentisi/codec yokluğu görünür olmalı
			raise DpiError(f"{out_fmt} DPI yazımı başarısız: {type(exc).__name__}: {exc}") from exc

	result = out.getvalue()
	if not result:
		raise DpiError("DPI yazımı boş çıktı üretti")
	with Image.open(io.BytesIO(result)) as verify:
		verify.load()
		output_size = verify.size
	if output_size != source_size:
		raise DpiError(f"DPI yazımı piksel ölçüsünü değiştirdi: {source_size} -> {output_size}")

	measured = read_dpi(result)
	if measured.dpi is None or any(abs(value - int(dpi)) > 0.1 for value in measured.dpi):
		raise DpiError(f"DPI round-trip doğrulanamadı: beklenen={dpi}, okunan={measured.dpi}")
	return DpiRewriteResult(
		content=result,
		fmt=out_fmt,
		width=output_size[0],
		height=output_size[1],
		dpi=measured.dpi,
		storage=measured.storage,
		pixels_preserved=True,
	)


def pixel_cap_size(
	width: int,
	height: int,
	*,
	max_long_edge: int = 0,
	max_megapixels: float = 0.0,
	min_long_edge: int = 0,
) -> tuple[int, int]:
	"""DPI'dan bağımsız piksel bütçesi; oranı korur ve upscale yapmaz."""
	spec = NormalizeSpec(
		max_long_edge=int(max_long_edge),
		max_megapixels=float(max_megapixels),
		min_long_edge=int(min_long_edge),
	)
	return target_size(int(width), int(height), spec)


__all__ = [
	"DpiError",
	"DpiInfo",
	"DpiRewriteResult",
	"NATIVE_DPI_FORMATS",
	"SUPPORTED_FORMATS",
	"pixel_cap_size",
	"read_dpi",
	"rewrite_dpi",
]

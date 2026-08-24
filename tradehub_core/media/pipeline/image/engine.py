"""Production ``ImageEngine`` adapter for the Phase 3 contract.

The image pipeline already had independently tested probe, normalisation,
rendition and SSIM modules.  What was missing was a single object that exposed
those modules through ``contracts.image.ImageEngine``.  This adapter is that
boundary; it remains Frappe-free and never writes to storage.
"""

from __future__ import annotations

import io
from collections.abc import Sequence

from tradehub_core.media.pipeline.contracts.errors import (
	SEBEP_ALPHA_LOST,
	SEBEP_ANIMATED_NOT_ALLOWED,
	DecodeError,
	EncodeError,
	OversizedImage,
	UnsupportedFormat,
	kod_uret,
)
from tradehub_core.media.pipeline.contracts.image import (
	METRIC_SSIM,
	EncodedImage,
	ImageProbe,
	MasterSpec,
	QualityReport,
	RenditionSpec,
)
from tradehub_core.media.pipeline.image import normalize as normalize_mod
from tradehub_core.media.pipeline.image import probe as probe_mod
from tradehub_core.media.pipeline.image import render as render_mod
from tradehub_core.media.pipeline.quality import ssim as ssim_mod

SUPPORTED_FORMATS: tuple[str, ...] = ("AVIF", "JPEG", "PNG", "TIFF", "WEBP")
ALPHA_CAPABLE_FORMATS: tuple[str, ...] = ("AVIF", "PNG", "TIFF", "WEBP")
_CONTRACT_SLOT = "product.image"


def _format(value: str) -> str:
	value = (value or "").strip().upper()
	return "JPEG" if value == "JPG" else value


def _guard(content: bytes, *, max_megapixels: float = 0.0, allow_animated: bool = True):
	"""Build a header-only guard without imposing an unrelated slot limit."""
	return probe_mod.probe_header(
		content,
		config=probe_mod.GuardConfig(
			max_megapixels=max_megapixels,
			max_bytes=max(len(content), 1),
			allow_animated=allow_animated,
			reject_extension_mismatch=False,
		),
	)


def _contract_probe(header) -> ImageProbe:
	return ImageProbe(
		fmt=_format(header.fmt or header.detected),
		width=int(header.width or 0),
		height=int(header.height or 0),
		mode=str(header.mode or ""),
		animated=bool(header.animated),
		readable=bool(header.readable and header.width and header.height),
		has_alpha=bool(header.has_alpha),
		icc_profile=bool(header.has_icc),
		dpi=header.dpi,
		exif_orientation=int(header.exif_orientation or 1),
		frame_count=int(header.frame_count or 1),
	)


def _is_canonical(content: bytes, probe: ImageProbe, spec: MasterSpec) -> bool:
	"""Recognise a fixed point without re-encoding a lossy master.

	Only inputs whose complete observable state already satisfies the master
	contract are passed through.  This makes the second invocation byte-stable
	while still normalising originals carrying EXIF/XMP/ICC metadata.
	"""
	target = probe.fmt if _format(spec.format) in ("", "PRESERVE") else _format(spec.format)
	if not probe.readable or probe.fmt != target or probe.animated:
		return False
	if spec.max_long_edge and probe.long_edge > spec.max_long_edge:
		return False
	if spec.max_megapixels and probe.megapixels > spec.max_megapixels + 1e-9:
		return False
	if spec.colorspace == "srgb" and probe.mode not in ("RGB", "RGBA"):
		return False
	if spec.orientation == "apply_exif" and probe.exif_orientation not in (0, 1):
		return False
	try:
		from PIL import Image

		with Image.open(io.BytesIO(content)) as image:
			info = image.info
			if info.get("exif") or info.get("xmp") or info.get("XML:com.adobe.xmp"):
				return False
			if info.get("icc_profile"):
				return False
			if spec.dpi_out and probe.fmt in ("JPEG", "PNG", "TIFF"):
				dpi = info.get("dpi")
				if not dpi or any(abs(float(v) - spec.dpi_out) > 1.0 for v in dpi[:2]):
					return False
			image.verify()
	except Exception:
		return False
	return True


class PillowImageEngine:
	"""Pillow-backed production implementation of the frozen image contract."""

	def supported_formats(self) -> tuple[str, ...]:
		return SUPPORTED_FORMATS

	def probe(self, content: bytes, *, max_megapixels: float = 0.0) -> ImageProbe:
		header = _guard(content, max_megapixels=max_megapixels)
		if max_megapixels and header.megapixels > max_megapixels:
			raise OversizedImage(
				"Görsel megapiksel tavanını aşıyor.",
				detay={"measured_mp": header.megapixels, "max_mp": max_megapixels},
			)
		return _contract_probe(header)

	def make_master(self, content: bytes, spec: MasterSpec) -> EncodedImage:
		probe = self.probe(content, max_megapixels=80.0)
		if not probe.readable:
			raise DecodeError("Görsel başlığı okunamadı veya içerik bozuk.")
		if probe.animated:
			raise UnsupportedFormat(
				"Animasyonlu görselden sabit master üretilemez.",
				kod=kod_uret("media", SEBEP_ANIMATED_NOT_ALLOWED),
			)
		target = probe.fmt if _format(spec.format) in ("", "PRESERVE") else _format(spec.format)
		if target not in SUPPORTED_FORMATS:
			raise UnsupportedFormat("Hedef görsel biçimi desteklenmiyor.", detay={"fmt": target})
		if probe.has_alpha and target not in ALPHA_CAPABLE_FORMATS:
			raise UnsupportedFormat(
				"Alfa kanalı taşıyan görsel alfasız biçime dönüştürülemez.",
				kod=kod_uret("media", SEBEP_ALPHA_LOST),
				detay={"fmt": target, "mode": probe.mode},
			)
		if _is_canonical(content, probe, spec):
			return EncodedImage(
				content=content,
				fmt=target,
				width=probe.width,
				height=probe.height,
				quality=int(spec.quality or 0),
				dpi=int(spec.dpi_out or 72),
				notes=("canonical_passthrough",),
			)

		result = normalize_mod.normalize(
			content,
			normalize_mod.NormalizeSpec.from_master_spec(spec),
			guard=probe_mod.GuardConfig(
				max_megapixels=80.0,
				max_bytes=max(len(content), 1),
				allow_animated=False,
				reject_extension_mismatch=False,
			),
		)
		if not result.ok:
			if result.reason == probe_mod.SEBEP_MEGAPIXEL_BOMB:
				raise OversizedImage("Görsel megapiksel tavanını aşıyor.")
			if result.reason in (probe_mod.SEBEP_UNSUPPORTED_FORMAT, probe_mod.SEBEP_ANIMATED_NOT_ALLOWED):
				raise UnsupportedFormat("Görsel biçimi veya animasyon politikası desteklenmiyor.")
			if result.reason in (probe_mod.SEBEP_DECODE_FAILED, probe_mod.SEBEP_EMPTY):
				raise DecodeError("Görsel çözülemedi.", detay={"reason": result.reason})
			raise EncodeError("Master üretilemedi.", detay={"reason": result.reason})
		return EncodedImage(
			content=result.content,
			fmt=_format(result.fmt),
			width=result.width,
			height=result.height,
			quality=int(spec.quality or 82),
			dpi=int(spec.dpi_out or 72),
			notes=tuple(result.notes),
		)

	def make_rendition(self, master: bytes, spec: RenditionSpec) -> EncodedImage:
		probe = self.probe(master)
		if not probe.readable:
			raise DecodeError("Master görsel çözülemedi.")
		fmt = _format(spec.format)
		if fmt not in SUPPORTED_FORMATS or fmt.lower() not in render_mod.PIL_FORMAT:
			raise UnsupportedFormat("Türev biçimi desteklenmiyor.", detay={"fmt": fmt})
		if probe.has_alpha and fmt not in ALPHA_CAPABLE_FORMATS:
			raise UnsupportedFormat(
				"Alfa kanalı taşıyan master alfasız türeve dönüştürülemez.",
				kod=kod_uret("media", SEBEP_ALPHA_LOST),
			)

		if spec.width >= probe.width and fmt == probe.fmt:
			return EncodedImage(
				content=master,
				fmt=probe.fmt,
				width=probe.width,
				height=probe.height,
				quality=int(spec.quality or 0),
				notes=(render_mod.NOTE_UNDER_SPEC,),
			)

		width = min(spec.width, probe.width)
		quality: object = "lossless" if spec.lossless else int(spec.quality or 82)
		profile = render_mod.RenditionProfile(
			slot_key=_CONTRACT_SLOT,
			name=spec.name,
			width=width,
			formats=(fmt.lower(),),
			fit=spec.fit,
			encoder_quality=((fmt.lower(), quality),),
			target_ratio=spec.target_ratio,
			pad_color=spec.pad_color,
			derived_from=spec.derived_from,
		)
		try:
			result = render_mod.render_rendition(
				master,
				profile,
				fmt=fmt.lower(),
				target_ssim=0.0,
				allow_passthrough=False,
			)
		except render_mod.RenderError as exc:
			raise EncodeError("Türev üretilemedi.", detay={"reason": str(exc)}) from exc
		notes = tuple(result.notes)
		if spec.width > probe.width and render_mod.NOTE_UNDER_SPEC not in notes:
			notes += (render_mod.NOTE_UNDER_SPEC,)
		return EncodedImage(
			content=result.content,
			fmt=_format(result.format),
			width=result.width,
			height=result.height,
			quality=int(result.quality or 0) if isinstance(result.quality, int) else 0,
			notes=notes,
		)

	def make_ladder(self, master: bytes, specs: Sequence[RenditionSpec]) -> dict[str, EncodedImage]:
		adlar = [spec.name for spec in specs]
		if len(adlar) != len(set(adlar)):
			raise EncodeError("Türev merdiveninde yinelenen profil adı var.")
		return {spec.name: self.make_rendition(master, spec) for spec in specs}

	def quality_score(
		self, reference: bytes, candidate: bytes, *, metric: str = METRIC_SSIM
	) -> QualityReport:
		if metric != METRIC_SSIM:
			return QualityReport(metric=metric, score=0.0, threshold=0.0, measured=False)
		reference_probe = self.probe(reference)
		candidate_probe = self.probe(candidate)
		if (
			not reference_probe.readable
			or not candidate_probe.readable
			or (reference_probe.width, reference_probe.height)
			!= (candidate_probe.width, candidate_probe.height)
		):
			return QualityReport(metric=metric, score=0.0, threshold=0.0, measured=False)
		try:
			result = ssim_mod.compute_ssim(reference, candidate)
		except Exception:
			return QualityReport(metric=metric, score=0.0, threshold=0.0, measured=False)
		return QualityReport(metric=metric, score=float(result.value), threshold=0.0, measured=True)


__all__ = ["PillowImageEngine", "SUPPORTED_FORMATS"]

"""T-061/T-062 — sınıflandırılmış kaynaktan normalize Version master'ı üret.

Bu katman sınıflandırma ile normalleştirmeyi tek kararda birleştirir. Böylece
``Media Version`` ve rendition üretimi farklı kaynak baytları kullanamaz.
Animasyon burada düzleştirilmez; ``video_from_animation`` hattına bırakılır.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from tradehub_core.media.pipeline.image import classify as classify_mod
from tradehub_core.media.pipeline.image import normalize as normalize_mod

MASTER_ENGINE_VERSION: str = "2.0.0"
PHOTO_MASTER_QUALITY: int = 88


@dataclass(frozen=True)
class MasterResult:
	"""Orijinal sınıflandırma + gerçek normalize çıktısının ortak sonucu."""

	ok: bool
	classification: classify_mod.Classification
	normalized: normalize_mod.NormalizeResult | None = None
	reason: str = ""

	@property
	def content(self) -> bytes:
		return self.normalized.content if self.normalized and self.normalized.ok else b""

	@property
	def format(self) -> str:
		return self.normalized.fmt if self.normalized else ""


def effective_spec(
	policy: Mapping[str, Any],
	classification: classify_mod.Classification,
) -> normalize_mod.NormalizeSpec:
	"""Faz 2 format tablosunu slotun geometri/metadata reçetesine uygula."""
	master_policy = dict(policy.get("master") or policy)
	base = normalize_mod.NormalizeSpec.from_policy(master_policy)

	# Foto master için terimler tablosu JPEG q88 ister. Düşük güven, kabul
	# sözleşmesi gereği kayıpsız tarafa yaklaşır; şeffaf/grafik/belge için PNG
	# hem alfa/kayıpsızlık hem de gerçek 72 DPI metadata'sını taşıyabilir.
	if classification.klass == classify_mod.SINIF_PHOTO and classification.confidence != "low":
		return replace(base, fmt="JPEG", quality=PHOTO_MASTER_QUALITY, lossless=False)
	if classification.klass in {
		classify_mod.SINIF_TRANSPARENT,
		classify_mod.SINIF_GRAPHIC,
		classify_mod.SINIF_DOCUMENT,
	} or classification.confidence == "low":
		return replace(base, fmt="PNG", lossless=True)
	if classification.klass == classify_mod.SINIF_ANIMATION:
		raise ValueError("animation_requires_video_pipeline")
	raise ValueError(f"unsupported_classification:{classification.klass}")


def make_master(
	src: bytes | bytearray | str | Path,
	policy: Mapping[str, Any],
	*,
	filename: str = "",
	classification: classify_mod.Classification | None = None,
) -> MasterResult:
	"""Kaynağı bir kez sınıflandırıp Version master'ına normalleştir.

	Sınıflandırıcı T-060 kapısını önce çalıştırır. Normalize aynı baytı ikinci
	kez guard etmez ama header'ı bellek yolu için yine okur; decode hiçbir zaman
	başarılı kapı kararından önce başlamaz.
	"""
	decision = classification or classify_mod.classify(src, filename=filename)
	if not decision.ok:
		return MasterResult(ok=False, classification=decision, reason=decision.error)
	if decision.route_to_video or decision.klass == classify_mod.SINIF_ANIMATION:
		return MasterResult(
			ok=False,
			classification=decision,
			reason=classify_mod.JOB_TYPE_VIDEO_FROM_ANIMATION,
		)
	try:
		spec = effective_spec(policy, decision)
	except ValueError as exc:
		return MasterResult(ok=False, classification=decision, reason=str(exc))

	normalized = normalize_mod.normalize(src, spec, filename=filename, skip_guard=True)
	if not normalized.ok:
		return MasterResult(
			ok=False,
			classification=decision,
			normalized=normalized,
			reason=normalized.reason or "normalize_failed",
		)
	return MasterResult(ok=True, classification=decision, normalized=normalized)


__all__ = [
	"MASTER_ENGINE_VERSION",
	"PHOTO_MASTER_QUALITY",
	"MasterResult",
	"effective_spec",
	"make_master",
]

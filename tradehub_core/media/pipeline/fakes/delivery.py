"""`DeliveryManifest`'in referans uygulaması — politikadan `srcset` üretir.

Sahte olan tarafı yok: mantık gerçek, tek varsayımı türevlerin FR-040'taki
ad şemasıyla (orijinalin yanında, aynı shard, `__<profil>.<biçim>` soneki)
üretilmiş olmasıdır. Depoya BAKMAZ — hangi profilin gerçekten üretildiğini
çağıran `available_profiles` ile bildirir.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from tradehub_core.media.pipeline.contracts.delivery import (
	LOADING_EAGER,
	LOADING_LAZY,
	RenderManifest,
	SourceSet,
	Variant,
	derivative_key,
)
from tradehub_core.media.pipeline.contracts.errors import NoProfileAvailable
from tradehub_core.media.pipeline.contracts.storage import ObjectRef

# Tarayıcı ilk desteklediği `<source>`'u seçer: en verimli biçim başta.
BICIM_SIRASI: Tuple[str, ...] = ("avif", "webp", "jpeg", "png")

# `<img src>` fallback'i için ASLA seçilmeyecek biçimler — eski tarayıcı
# desteklemezse görsel hiç görünmez.
FALLBACK_DISI: Tuple[str, ...] = ("avif",)


def _bicim_sirasi(fmt: str) -> int:
	f = (fmt or "").lower()
	return BICIM_SIRASI.index(f) if f in BICIM_SIRASI else len(BICIM_SIRASI)


class SimpleDeliveryManifest:
	"""Politika + nesne adresi → `RenderManifest`.

	`sizes_map` render bağlamına göre `sizes` dizgesini verir; sözleşme
	tanımsız bağlamda boş dizge döndürmeyi şart koşuyor (yanlış `sizes`
	yazmaktansa hiç yazmamak).
	"""

	def __init__(
		self,
		policy_engine: Any,
		*,
		sizes_map: Optional[Mapping[str, Mapping[str, str]]] = None,
	) -> None:
		self._policy = policy_engine
		self._sizes: Dict[str, Dict[str, str]] = {
			slot: dict(bag) for slot, bag in dict(sizes_map or {}).items()
		}

	# ── yardımcılar ────────────────────────────────────────────────────

	def _variants(
		self, slot_key: str, base: ObjectRef, available: Optional[Sequence[str]]
	) -> Tuple[Variant, ...]:
		izinli = set(available) if available is not None else None
		cikti = []
		for spec in self._policy.rendition_specs(slot_key):
			anahtar = derivative_key(base.key, spec.name, spec.format)
			cikti.append(
				Variant(
					profile=spec.name,
					url=ObjectRef(key=anahtar, scope=base.scope).url,
					width=spec.width,
					fmt=spec.format,
					available=izinli is None or spec.name in izinli,
				)
			)
		return tuple(cikti)

	def _sources(self, variants: Sequence[Variant], sizes: str) -> Tuple[SourceSet, ...]:
		gruplar: Dict[str, list] = {}
		for v in variants:
			if not v.available:
				continue
			gruplar.setdefault(v.fmt.lower(), []).append(v)
		cikti = []
		for fmt in sorted(gruplar, key=_bicim_sirasi):
			sirali = sorted(gruplar[fmt], key=lambda v: v.width)
			cikti.append(
				SourceSet(fmt=fmt, srcset=", ".join(v.srcset_entry for v in sirali), sizes=sizes)
			)
		return tuple(cikti)

	# ── DeliveryManifest ───────────────────────────────────────────────

	def build_image(
		self,
		slot_key: str,
		base: ObjectRef,
		*,
		intrinsic: Tuple[int, int] = (0, 0),
		alt: str = "",
		sizes: str = "",
		available_profiles: Optional[Sequence[str]] = None,
		is_lcp_candidate: bool = False,
	) -> RenderManifest:
		variants = self._variants(slot_key, base, available_profiles)
		kullanilabilir = [v for v in variants if v.available]
		if not kullanilabilir:
			raise NoProfileAvailable(
				"Teslim edilebilir türev yok", detay={"slot_key": slot_key, "url": base.url}
			)
		sizes = sizes or self.sizes_attribute(slot_key)
		sources = self._sources(variants, sizes)
		fallback_adaylari = [v for v in kullanilabilir if v.fmt.lower() not in FALLBACK_DISI]
		fallback = max(fallback_adaylari or kullanilabilir, key=lambda v: v.width)
		return RenderManifest(
			slot_key=slot_key,
			fallback_url=fallback.url,
			variants=variants,
			sources=sources,
			sizes=sizes,
			intrinsic_width=intrinsic[0],
			intrinsic_height=intrinsic[1],
			alt=alt,
			loading=LOADING_EAGER if is_lcp_candidate else LOADING_LAZY,
			decoding="sync" if is_lcp_candidate else "async",
			fetchpriority="high" if is_lcp_candidate else "",
		)

	def build_video(
		self,
		slot_key: str,
		base: ObjectRef,
		*,
		poster: Optional[ObjectRef] = None,
		captions_url: str = "",
		intrinsic: Tuple[int, int] = (0, 0),
		available_renditions: Optional[Sequence[str]] = None,
	) -> RenderManifest:
		izinli = set(available_renditions) if available_renditions is not None else None
		specs = self._policy.video_rendition_specs(slot_key)
		variants = []
		for spec in specs:
			anahtar = derivative_key(base.key, spec.id, spec.container)
			variants.append(
				Variant(
					profile=spec.id,
					url=ObjectRef(key=anahtar, scope=base.scope).url,
					width=spec.width,
					height=spec.height,
					fmt=spec.container,
					available=izinli is None or spec.id in izinli,
				)
			)
		kullanilabilir = [v for v in variants if v.available]
		if not kullanilabilir:
			raise NoProfileAvailable(
				"Teslim edilebilir rendition yok", detay={"slot_key": slot_key, "url": base.url}
			)
		# Poster ZORUNLU: verilmediyse politika profilinden türetilir (FR-042).
		if poster is None:
			poster_profil = str(
				(self._policy.load(slot_key).video.get("poster") or {}).get("profile") or "poster"
			)
			poster = ObjectRef(
				key=derivative_key(base.key, poster_profil, "webp"), scope=base.scope
			)
		return RenderManifest(
			slot_key=slot_key,
			fallback_url=max(kullanilabilir, key=lambda v: v.width).url,
			variants=tuple(variants),
			sources=self._sources(variants, ""),
			intrinsic_width=intrinsic[0],
			intrinsic_height=intrinsic[1],
			poster_url=poster.url,
			captions_url=captions_url,
		)

	def sizes_attribute(self, slot_key: str, *, context: str = "") -> str:
		return self._sizes.get(slot_key, {}).get(context or "default", "")

	def pick(self, slot_key: str, css_width_px: float, *, dpr: float = 1.0) -> Variant:
		specs = self._policy.rendition_specs(slot_key)
		if not specs:
			raise NoProfileAvailable("Profil yok", detay={"slot_key": slot_key})
		hedef = css_width_px * (dpr or 1.0)
		adaylar = sorted(specs, key=lambda s: s.width)
		secilen = next((s for s in adaylar if s.width >= hedef), adaylar[-1])
		return Variant(profile=secilen.name, url="", width=secilen.width, fmt=secilen.format)

	def overshoot(self, slot_key: str, css_width_px: float, *, dpr: float = 1.0) -> float:
		hedef = css_width_px * (dpr or 1.0)
		if hedef <= 0:
			return 0.0
		try:
			secilen = self.pick(slot_key, css_width_px, dpr=dpr)
		except NoProfileAvailable:
			return 0.0
		return secilen.width / hedef


__all__ = ["SimpleDeliveryManifest", "BICIM_SIRASI"]

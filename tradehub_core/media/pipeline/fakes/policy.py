"""`PolicyEngine`'in bellek-içi referans uygulaması.

"Sahte" olan tarafı yalnız KAYNAĞIDIR (disk yerine sözlük olabilir); karar
mantığı gerçektir ve `tradehub_core/media/pipeline/policy/slots/*.json` dosyalarını olduğu
gibi okur. Politika mantığını sahtelemek, sözleşme testini anlamsız kılardı:
test "kural doğru uygulanıyor mu"yu değil "sahte ne diyorsa o"yu ölçerdi.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from tradehub_core.media.pipeline.contracts.errors import (
	SEBEP_ANIMATED_NOT_ALLOWED,
	SEBEP_AREA_TOO_SMALL,
	SEBEP_BITRATE_EXCEEDED,
	SEBEP_COUNT_EXCEEDED,
	SEBEP_DECODE_FAILED,
	SEBEP_DURATION_OUT_OF_RANGE,
	SEBEP_EXT_CONTENT_MISMATCH,
	SEBEP_EXT_NOT_ALLOWED,
	SEBEP_MEGAPIXEL_BOMB,
	SEBEP_MIME_NOT_ALLOWED,
	SEBEP_PROBE_UNAVAILABLE,
	SEBEP_RATIO_NOT_ALLOWED,
	SEBEP_SHORT_EDGE_TOO_SMALL,
	SEBEP_TOO_LARGE,
	PolicyError,
	PolicyNotFound,
	kod_uret,
)
from tradehub_core.media.pipeline.contracts.image import ImageProbe, MasterSpec, RenditionSpec
from tradehub_core.media.pipeline.contracts.policy import (
	ACTION_MANUAL_REVIEW,
	ACTION_PASS,
	ACTION_REJECT,
	ACTION_WARN,
	LAYER_ACCEPT,
	LAYER_MASTER,
	LAYER_QUALITY,
	LAYER_REQUIRE,
	STATUS_ACTIVE,
	Decision,
	EffectiveLimits,
	SlotPolicy,
	Violation,
	en_yuksek_aksiyon,
)
from tradehub_core.media.pipeline.contracts.video import VideoProbe, VideoRenditionSpec

# Faz 2 çıktısının kanonik kökü.
VARSAYILAN_KOK: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "policy", "slots")


def _oran(deger: str) -> float:
	"""`"4:5"` → 0.8. Ayrıştırılamayan oran `PolicyError`."""
	try:
		w, _, h = deger.partition(":")
		return float(w) / float(h)
	except Exception:
		raise PolicyError(f"Geçersiz oran: {deger!r}")


# Uzantı ↔ içerik imzası uyum tablosu — `upload_policy._UYUM` ile AYNI.
# Tabloda OLMAYAN uzantı (AVIF/HEIC gibi) uyuşmazlık sayılmaz: imzası bilinmeyen
# bir biçimi "yanlış" ilan etmek sahadaki geçerli dosyaları keserdi.
_UYUM: dict[str, tuple[str, ...]] = {
	".jpg": ("jpeg",),
	".jpeg": ("jpeg",),
	".png": ("png",),
	".gif": ("gif",),
	".bmp": ("bmp",),
	".webp": ("webp",),
	".tif": ("tiff",),
	".tiff": ("tiff",),
	".pdf": ("pdf",),
	".mp4": ("mp4",),
	".m4v": ("mp4",),
	".mov": ("mp4",),
	".webm": ("webm",),
}


def _sayi(deger: Any, varsayilan: float = 0.0) -> float:
	"""`None`/boş güvenli sayı okuma — politika alanları isteğe bağlı olabilir."""
	if deger is None or deger == "":
		return varsayilan
	try:
		return float(deger)
	except (TypeError, ValueError):
		return varsayilan


class InMemoryPolicyEngine:
	"""Politika kayıt defteri — sözlükten ya da dizinden kurulur."""

	def __init__(self, policies: Mapping[str, Mapping[str, Any]] | None = None, *, root: str = "") -> None:
		self._root = root or "<memory>"
		self._raw: dict[str, Mapping[str, Any]] = dict(policies or {})
		self._cache: dict[str, SlotPolicy] = {}

	@classmethod
	def from_directory(cls, root: str = VARSAYILAN_KOK) -> InMemoryPolicyEngine:
		"""Gerçek politika dosyalarını oku (`tradehub_core/media/pipeline/policy/slots/*.json`)."""
		motor = cls(root=root)
		motor.reload()
		return motor

	# ── kayıt defteri ──────────────────────────────────────────────────

	def source_root(self) -> str:
		return self._root

	def slots(self) -> tuple[str, ...]:
		return tuple(sorted(self._raw))

	def load(self, slot_key: str) -> SlotPolicy:
		if slot_key in self._cache:
			return self._cache[slot_key]
		ham = self._raw.get(slot_key)
		if ham is None:
			raise PolicyNotFound(f"Bilinmeyen slot: {slot_key}", detay={"slot_key": slot_key})
		politika = SlotPolicy(
			slot_key=str(ham.get("slot_key") or slot_key),
			schema_version=str(ham.get("schema_version") or ""),
			status=str(ham.get("status") or "draft"),
			roles=tuple(ham.get("roles") or ()),
			accept=dict(ham.get("accept") or {}),
			require=dict(ham.get("require") or {}),
			master=dict(ham.get("master") or {}),
			quality=dict(ham.get("quality") or {}),
			profiles=tuple(ham.get("profiles") or ()),
			video=dict(ham.get("video") or {}),
			on_violation=dict(ham.get("on_violation") or {}),
			messages=dict(ham.get("messages") or {}),
			bound_to=tuple(ham.get("bound_to") or ()),
			raw=ham,
		)
		self._cache[slot_key] = politika
		return politika

	def reload(self) -> int:
		"""Ya hep ya hiç: hepsi okunur, sonra atomik olarak değiştirilir."""
		if self._root == "<memory>":
			self._cache.clear()
			return len(self._raw)
		if not os.path.isdir(self._root):
			raise PolicyError(f"Politika kökü yok: {self._root}")
		yeni: dict[str, Mapping[str, Any]] = {}
		for ad in sorted(os.listdir(self._root)):
			if not ad.endswith(".json") or ad.startswith("_"):
				continue
			yol = os.path.join(self._root, ad)
			try:
				with open(yol, encoding="utf-8") as f:
					veri = json.load(f)
			except Exception as exc:
				raise PolicyError(f"Politika okunamadı: {ad} ({exc})")
			anahtar = veri.get("slot_key")
			if not anahtar:
				raise PolicyError(f"`slot_key` yok: {ad}")
			yeni[str(anahtar)] = veri
		self._raw = yeni
		self._cache.clear()
		return len(self._raw)

	# ── limitler ───────────────────────────────────────────────────────

	def effective_limits(self, slot_key: str, *, plan_max_bytes: int = 0) -> EffectiveLimits:
		p = self.load(slot_key)
		slot_bytes = int(_sayi(p.accept.get("max_bytes")))
		adaylar = [b for b in (slot_bytes, int(plan_max_bytes or 0)) if b > 0]
		kaynak = {"slot": str(slot_bytes or "-"), "plan": str(plan_max_bytes or "-")}
		return EffectiveLimits(
			max_bytes=min(adaylar) if adaylar else 0,
			max_megapixels_hard=_sayi(p.accept.get("max_megapixels_hard")),
			max_count=int(_sayi(p.require.get("max_count"))),
			source=kaynak,
		)

	# ── kapılar ────────────────────────────────────────────────────────

	def _karar(self, p: SlotPolicy, layer: str, ihlaller: tuple[Violation, ...]) -> Decision:
		"""İhlalleri aksiyonlarına göre ret/uyarı kovalarına ayırır (FR-049)."""
		retler = tuple(v for v in ihlaller if v.action == ACTION_REJECT)
		uyarilar = tuple(v for v in ihlaller if v.action != ACTION_REJECT)
		aksiyon = en_yuksek_aksiyon([v.action for v in ihlaller]) if ihlaller else ACTION_PASS
		return Decision(slot_key=p.slot_key, action=aksiyon, violations=retler, warnings=uyarilar)

	def _ihlal(self, p: SlotPolicy, layer: str, sebep: str, **kw: Any) -> Violation:
		return Violation(
			code=kod_uret(p.error_prefix, sebep),
			layer=layer,
			sebep=sebep,
			action=p.action_for(layer),
			retryable=bool(p.on_violation.get("retryable")),
			**kw,
		)

	def check_accept(
		self,
		slot_key: str,
		*,
		file_name: str,
		size_bytes: int,
		sniffed_type: str = "",
		declared_mime: str = "",
	) -> Decision:
		p = self.load(slot_key)
		ihlaller = []
		uzanti = os.path.splitext(file_name or "")[1].lower()
		izinli_uzanti = [str(e).lower() for e in (p.accept.get("extensions") or ())]
		if izinli_uzanti and uzanti not in izinli_uzanti:
			ihlaller.append(
				self._ihlal(
					p, LAYER_ACCEPT, SEBEP_EXT_NOT_ALLOWED, measured=uzanti, expected=izinli_uzanti
				)
			)
		izinli_mime = [str(m).lower() for m in (p.accept.get("mime") or ())]
		if declared_mime and izinli_mime and declared_mime.lower() not in izinli_mime:
			ihlaller.append(
				self._ihlal(
					p, LAYER_ACCEPT, SEBEP_MIME_NOT_ALLOWED, measured=declared_mime, expected=izinli_mime
				)
			)
		tavan = self.effective_limits(slot_key).max_bytes
		if tavan and size_bytes > tavan:
			ihlaller.append(
				self._ihlal(p, LAYER_ACCEPT, SEBEP_TOO_LARGE, measured=size_bytes, expected=tavan)
			)
		beklenen = _UYUM.get(uzanti)
		if sniffed_type and beklenen is not None and sniffed_type not in beklenen:
			# Canonical slot policy owns the action; the reference and production
			# readers must not invent different decisions for the same JSON.
			ihlaller.append(
				self._ihlal(
					p,
					LAYER_ACCEPT,
					SEBEP_EXT_CONTENT_MISMATCH,
					measured=sniffed_type,
					expected=uzanti,
				)
			)
		return self._karar(p, LAYER_ACCEPT, tuple(ihlaller))

	def check_geometry(self, slot_key: str, probe: ImageProbe, *, count: int = 1) -> Decision:
		p = self.load(slot_key)
		if not probe.readable:
			return Decision(
				slot_key=p.slot_key,
				action=ACTION_REJECT,
				violations=(
					Violation(
						code=kod_uret(p.error_prefix, SEBEP_DECODE_FAILED),
						layer=LAYER_REQUIRE,
						sebep=SEBEP_DECODE_FAILED,
						action=ACTION_REJECT,
					),
				),
			)
		ihlaller = []
		sert_mp = _sayi(p.accept.get("max_megapixels_hard"))
		if sert_mp and probe.megapixels > sert_mp:
			ihlaller.append(
				Violation(
					code=kod_uret(p.error_prefix, SEBEP_MEGAPIXEL_BOMB),
					layer=LAYER_ACCEPT,
					sebep=SEBEP_MEGAPIXEL_BOMB,
					action=ACTION_REJECT,
					measured=round(probe.megapixels, 2),
					expected=sert_mp,
				)
			)
		if probe.animated and p.accept.get("allow_animated") is False:
			ihlaller.append(
				self._ihlal(p, LAYER_ACCEPT, SEBEP_ANIMATED_NOT_ALLOWED, measured=True, expected=False)
			)
		min_kisa = _sayi(p.require.get("min_short_edge"))
		if min_kisa and probe.short_edge < min_kisa:
			# `>=` — eşitlik GEÇERLİ (FR-015).
			ihlaller.append(
				self._ihlal(
					p, LAYER_REQUIRE, SEBEP_SHORT_EDGE_TOO_SMALL,
					measured=probe.short_edge, expected=int(min_kisa),
				)
			)
		min_alan = _sayi(p.require.get("min_area"))
		if min_alan and probe.area < min_alan:
			ihlaller.append(
				self._ihlal(
					p, LAYER_REQUIRE, SEBEP_AREA_TOO_SMALL, measured=probe.area, expected=int(min_alan)
				)
			)
		oranlar = [str(r) for r in (p.require.get("allowed_ratios") or ())]
		if oranlar and probe.aspect_ratio:
			tolerans = _sayi(p.require.get("ratio_tolerance"), 0.02)
			sapma = min(abs(probe.aspect_ratio - _oran(r)) / _oran(r) for r in oranlar)
			if sapma > tolerans:
				ihlaller.append(
					self._ihlal(
						p, LAYER_REQUIRE, SEBEP_RATIO_NOT_ALLOWED,
						measured=round(probe.aspect_ratio, 4), expected=oranlar,
					)
				)
		azami = int(_sayi(p.require.get("max_count")))
		if azami and count > azami:
			ihlaller.append(
				self._ihlal(p, LAYER_REQUIRE, SEBEP_COUNT_EXCEEDED, measured=count, expected=azami)
			)
		return self._karar(p, LAYER_REQUIRE, tuple(ihlaller))

	def check_video(self, slot_key: str, probe: VideoProbe) -> Decision:
		p = self.load(slot_key)
		if not p.is_video:
			raise PolicyError(f"Video olmayan slotta video kapısı: {slot_key}")
		if not probe.measured:
			# NFR-043 + FR-134: ölçülemeyen video ne reddedilir ne sessizce geçer.
			return Decision(
				slot_key=p.slot_key,
				action=ACTION_MANUAL_REVIEW,
				warnings=(
					Violation(
						code=kod_uret(p.error_prefix, SEBEP_PROBE_UNAVAILABLE),
						layer=LAYER_REQUIRE,
						sebep=SEBEP_PROBE_UNAVAILABLE,
						action=ACTION_MANUAL_REVIEW,
					),
				),
			)
		v = p.video
		ihlaller = []
		alt = _sayi(v.get("duration_min_s"))
		ust = _sayi(v.get("duration_max_s"))
		if (alt and probe.duration_s < alt) or (ust and probe.duration_s > ust):
			ihlaller.append(
				self._ihlal(
					p, LAYER_REQUIRE, SEBEP_DURATION_OUT_OF_RANGE,
					measured=probe.duration_s, expected=[alt, ust],
				)
			)
		asgari = v.get("resolution_min") or {}
		if asgari and (
			probe.width < _sayi(asgari.get("width")) or probe.height < _sayi(asgari.get("height"))
		):
			ihlaller.append(
				self._ihlal(
					p, LAYER_REQUIRE, SEBEP_SHORT_EDGE_TOO_SMALL,
					measured=[probe.width, probe.height],
					expected=[asgari.get("width"), asgari.get("height")],
				)
			)
		kap = _sayi(v.get("bitrate_cap_kbps"))
		if kap and probe.bitrate_bps > kap * 1000:
			ihlaller.append(
				Violation(
					code=kod_uret(p.error_prefix, SEBEP_BITRATE_EXCEEDED),
					layer=LAYER_REQUIRE,
					sebep=SEBEP_BITRATE_EXCEEDED,
					action=ACTION_WARN,  # transcode zaten düşürecek — ret değil.
					measured=probe.bitrate_bps,
					expected=int(kap * 1000),
				)
			)
		return self._karar(p, LAYER_REQUIRE, tuple(ihlaller))

	# ── üretim parametreleri ───────────────────────────────────────────

	def master_spec(self, slot_key: str) -> MasterSpec:
		p = self.load(slot_key)
		if not p.master:
			raise PolicyError(f"`master` bloğu yok: {slot_key}")
		m = p.master
		return MasterSpec(
			max_long_edge=int(_sayi(m.get("max_long_edge"))),
			format=str(m.get("format") or "webp"),
			min_long_edge=int(_sayi(m.get("min_long_edge"))),
			max_megapixels=_sayi(m.get("max_megapixels")),
			dpi_out=int(_sayi(m.get("dpi_out"), 72)),
			colorspace=str(m.get("colorspace") or "srgb"),
			orientation=str(m.get("orientation") or "apply_exif"),
			fit=str(m.get("fit") or "contain"),
			target_ratio=str(m.get("target_ratio") or ""),
			pad_color=str(m.get("pad_color") or ""),
			allow_crop=bool(m.get("allow_crop")),
			allow_upscale=bool(m.get("allow_upscale")),
			strip_metadata=dict(m.get("strip_metadata") or {}),
		)

	def rendition_specs(self, slot_key: str) -> tuple[RenditionSpec, ...]:
		p = self.load(slot_key)
		cikti = []
		for profil in p.profiles:
			bicimler = [str(f) for f in (profil.get("formats") or ())] or ["webp"]
			kaliteler = profil.get("encoder_quality") or {}
			for bicim in bicimler:
				ad = profil.get("name") or "profil"
				cikti.append(
					RenditionSpec(
						name=ad if len(bicimler) == 1 else f"{ad}.{bicim}",
						width=int(_sayi(profil.get("width"))),
						format=bicim,
						quality=int(_sayi(kaliteler.get(bicim))),
						fit=str(profil.get("fit") or "contain"),
						target_ratio=str(profil.get("target_ratio") or ""),
						pad_color=str(profil.get("pad_color") or ""),
						lossless=bool(profil.get("lossless")),
						derived_from=str(profil.get("derived_from") or ""),
					)
				)
		return tuple(sorted(cikti, key=lambda s: (s.width, s.format)))

	def video_rendition_specs(self, slot_key: str) -> tuple[VideoRenditionSpec, ...]:
		p = self.load(slot_key)
		if not p.is_video:
			return ()
		cikti = []
		for r in p.video.get("renditions") or ():
			cikti.append(
				VideoRenditionSpec(
					id=str(r.get("id") or "rendition"),
					width=int(_sayi(r.get("width"))),
					height=int(_sayi(r.get("height"))),
					container=str(r.get("container") or "webm"),
					video_codec=str(r.get("video_codec") or "libvpx-vp9"),
					crf=int(_sayi(r.get("crf"), 32)),
					maxrate_kbps=int(_sayi(r.get("maxrate_kbps"))),
					bufsize_kbps=int(_sayi(r.get("bufsize_kbps"))),
					audio_codec=str(r.get("audio_codec") or "libopus"),
					audio_bitrate_kbps=int(_sayi(r.get("audio_bitrate_kbps"), 96)),
					audio_channels=int(_sayi(r.get("audio_channels"), 2)),
					max_bytes=int(_sayi(r.get("max_bytes"))),
					role=str(r.get("role") or "primary"),
				)
			)
		return tuple(cikti)

	def quality_threshold(self, slot_key: str, content_class: str) -> float:
		p = self.load(slot_key)
		hedefler = p.quality.get("target_ssim_per_class") or {}
		return _sayi(hedefler.get(content_class))

	# ── kendi kendini doğrulama ────────────────────────────────────────

	def validate(self, slot_key: str = "") -> Decision:
		"""D1–D5 değişmezleri (docs/standards/README.md §6)."""
		anahtarlar = (slot_key,) if slot_key else self.slots()
		ihlaller = []
		uyarilar = []
		for anahtar in anahtarlar:
			p = self.load(anahtar)
			m = p.master
			mle = _sayi(m.get("max_long_edge"))
			mmp = _sayi(m.get("max_megapixels"))
			mnle = _sayi(m.get("min_long_edge"))
			# Policy values are published to one decimal place (4096² =
			# 16.777216 MP -> 16.8 MP). Compare at that declared precision.
			if mmp and mle and round((mle * mle) / 1e6, 1) < round(mmp, 1):
				ihlaller.append(
					Violation(
						code=kod_uret(p.error_prefix, "invariant_d1"),
						layer=LAYER_MASTER,
						sebep="invariant_d1",
						action=ACTION_REJECT,
						measured=(mle * mle) / 1e6,
						expected=mmp,
						detay={"slot_key": anahtar},
					)
				)
			if mnle and mle and mnle > mle:
				ihlaller.append(
					Violation(
						code=kod_uret(p.error_prefix, "invariant_d2"),
						layer=LAYER_MASTER,
						sebep="invariant_d2",
						action=ACTION_REJECT,
						measured=mnle,
						expected=mle,
						detay={"slot_key": anahtar},
					)
				)
			for profil in p.profiles:
				if not (profil.get("derived_from") or ""):
					ihlaller.append(
						Violation(
							code=kod_uret(p.error_prefix, "invariant_d4"),
							layer=LAYER_MASTER,
							sebep="invariant_d4",
							action=ACTION_REJECT,
							detay={"slot_key": anahtar, "profile": profil.get("name")},
						)
					)
			if p.status == STATUS_ACTIVE:
				acik = p.raw.get("open_questions") or ()
				bos_kalite = any(
					q is None
					for profil in p.profiles
					for q in (profil.get("encoder_quality") or {}).values()
				)
				if acik or bos_kalite:
					ihlaller.append(
						Violation(
							code=kod_uret(p.error_prefix, "invariant_d5"),
							layer=LAYER_QUALITY,
							sebep="invariant_d5",
							action=ACTION_REJECT,
							detay={"slot_key": anahtar, "open_questions": len(acik)},
						)
					)
			elif p.raw.get("open_questions"):
				uyarilar.append(
					Violation(
						code=kod_uret(p.error_prefix, "draft_open_questions"),
						layer=LAYER_QUALITY,
						sebep="invariant_d5",
						action=ACTION_WARN,
						detay={"slot_key": anahtar, "open_questions": len(p.raw["open_questions"])},
					)
				)
		return Decision(
			slot_key=slot_key or "*",
			action=ACTION_REJECT if ihlaller else (ACTION_WARN if uyarilar else ACTION_PASS),
			violations=tuple(ihlaller),
			warnings=tuple(uyarilar),
		)


__all__ = ["InMemoryPolicyEngine", "VARSAYILAN_KOK"]

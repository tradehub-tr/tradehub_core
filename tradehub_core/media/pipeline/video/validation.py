"""Yüklenen videonun motor ve slot kurallarını tek kararda birleştirir.

Yükleme isteğindeki ucuz kontroller (ad, uzantı, MIME imzası, bayt sınırı ve
bozuk/tehlikeli içerik) ``media.upload_policy`` tarafından dosya kaydı
açılmadan uygulanır. Süre, gerçek kare ölçüsü, bitrate ve codec ise ancak
``ffprobe`` sonrasında güvenilir biçimde ölçülebilir. Bu modül o ikinci
katmandır.

İki karar bilinçli olarak ayrı kalır:

* ``video.decision`` motorun dosyayı passthrough/remux/transcode/reject
  etmesine karar verir (codec ve mutlak kaynak sınırları),
* ``PolicyEngine`` yüklemenin ait olduğu slotun süre/geometri/boyut
  kurallarını uygular.

Çağıran tek bir ``VideoValidation`` görür; böylece worker bu iki karardan
birini unutup geçersiz bir videoyu ``ready`` yapamaz.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from tradehub_core.media.pipeline.core.probe import KIND_VIDEO, MediaProbe
from tradehub_core.media.pipeline.policy.engine import (
	Decision as SlotDecision,
	PolicyEngine,
	default_engine,
)
from tradehub_core.media.pipeline.video import decision as video_decision
from tradehub_core.media.pipeline.video.decision import VideoDecision
from tradehub_core.media.pipeline.video.probe import VideoFacts


@dataclass(frozen=True)
class VideoValidation:
	"""Motor kararı + slot kararı ve tek ret sözleşmesi."""

	processing: VideoDecision
	slot_policy: SlotDecision

	@property
	def rejected(self) -> bool:
		return self.processing.rejected or not self.slot_policy.allow

	@property
	def code(self) -> str:
		"""Kullanıcı/iş kaydına yazılacak ilk ret kodu; kabulde boş."""
		if self.processing.rejected:
			return self.processing.code or "video_rejected"
		engeller = self.slot_policy.blocking()
		return engeller[0].code if engeller else ""

	@property
	def reason(self) -> str:
		"""İlk ret için kullanıcıya gösterilebilir Türkçe açıklama."""
		if self.processing.rejected:
			return self.processing.reason or "Video teknik doğrulamadan geçemedi."
		engeller = self.slot_policy.blocking()
		if not engeller:
			return ""
		mesaj = engeller[0].message or {}
		return mesaj.get("tr") or mesaj.get("en") or engeller[0].rule

	@property
	def stage(self) -> str:
		"""Ret kaynağı: motorun mutlak kapısı veya slot politikası."""
		if self.processing.rejected:
			return "engine"
		if not self.slot_policy.allow:
			return "slot"
		return ""

	@property
	def warning_codes(self) -> tuple[str, ...]:
		return tuple(v.code for v in self.slot_policy.violations if not v.blocking)


def _policy_probe(facts: VideoFacts) -> MediaProbe:
	"""``VideoFacts``ı PolicyEngine'in ortak künyesine kayıpsız indirger.

	MIME ve magic-byte alanları burada uydurulmaz: onlar orijinal baytlar
	üzerinden yükleme öncesi kapıda doğrulandı. Bu aşamanın yeni bilgisi
	ffprobe ölçümüdür. Dosya yolu yalnız uzantı ve savunma-derinliği bayt
	tavanı için taşınır.
	"""
	measured = bool(facts.measured)
	bitrate = int(facts.video_bitrate_bps or facts.format_bitrate_bps or 0)
	return MediaProbe(
		filename=os.path.basename(facts.path or ""),
		extension=os.path.splitext(facts.path or "")[1].lower(),
		byte_size=max(0, int(facts.size_bytes or 0)),
		kind=KIND_VIDEO,
		width=max(0, int(facts.width or 0)),
		height=max(0, int(facts.height or 0)),
		readable=measured,
		duration_s=float(facts.duration_s) if measured else None,
		bitrate_bps=bitrate if measured else None,
		frame_rate=float(facts.fps) if measured else None,
		has_audio=bool(facts.has_audio) if measured else None,
		audio_codec=(facts.audio_codec or "") if measured else "",
		video_codec=(facts.video_codec or "") if measured else "",
	)


def validate(
	slot_key: str,
	facts: VideoFacts,
	*,
	role: str = "",
	policy_engine: PolicyEngine | None = None,
) -> VideoValidation:
	"""Ölçülmüş videoyu mutlak motor ve slot kurallarından geçir."""
	motor = policy_engine or default_engine()
	return VideoValidation(
		processing=video_decision.decide(facts),
		slot_policy=motor.evaluate(slot_key, _policy_probe(facts), role=role),
	)


__all__ = ["VideoValidation", "validate"]

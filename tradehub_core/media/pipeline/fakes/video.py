"""`VideoEngine`'in sentetik biçimle çalışan sahte uygulaması.

Sentetik biçim (`FVID1`)
------------------------
    FVID1|c=mp4|vc=h264|ac=aac|w=1920|h=1080|dur=30.0|br=6000000|fps=30|audio=1\n<dolgu>

ffmpeg GEREKMEZ. Doğrulanan şey kodek değil **sözleşmedir**: ölçülemeyen
kaynakta güvenli tarafa düşme, koşullu atlama eşikleri, ses silme, dosya
kapısı ölçümü, tümü-ya-hiç rendition seti.
"""

from __future__ import annotations

from typing import Dict, Sequence

from tradehub_core.media.pipeline.contracts.errors import ProbeUnavailable, TranscodeFailed
from tradehub_core.media.pipeline.contracts.image import EncodedImage
from tradehub_core.media.pipeline.contracts.video import (
	AUDIO_STRIPPED,
	NEEDS_TRANSCODE_MAX_BITRATE_BPS,
	NEEDS_TRANSCODE_MAX_WIDTH,
	PosterSpec,
	PreviewClipSpec,
	VideoArtifact,
	VideoProbe,
	VideoRenditionSpec,
	VideoSource,
)
from tradehub_core.media.pipeline.fakes.image import sentetik_gorsel

BASLIK: bytes = b"FVID1"


def sentetik_video(
	width: int = 1920,
	height: int = 1080,
	*,
	duration_s: float = 30.0,
	bitrate_bps: int = 6_000_000,
	frame_rate: float = 30.0,
	container: str = "mp4",
	video_codec: str = "h264",
	audio_codec: str = "aac",
	has_audio: bool = True,
) -> bytes:
	"""Test için sentetik video baytları üretir."""
	baslik = (
		f"FVID1|c={container}|vc={video_codec}|ac={audio_codec}|w={int(width)}|h={int(height)}"
		f"|dur={float(duration_s)}|br={int(bitrate_bps)}|fps={float(frame_rate)}"
		f"|audio={int(bool(has_audio))}\n"
	)
	dolgu = max(64, int(duration_s * bitrate_bps / 8 / 1000))
	return baslik.encode("ascii") + bytes(dolgu)


def _coz(source: VideoSource) -> Dict[str, str]:
	"""Sentetik kaynağı çöz. `path` ile gelen kaynak sahte motorda okunamaz."""
	if source.content is None:
		raise ProbeUnavailable(
			"Sahte motor dosya yolu okuyamaz — `content` ile çağırın",
			detay={"path": source.path},
		)
	icerik = source.content
	if not icerik.startswith(BASLIK):
		raise ProbeUnavailable("Sentetik video başlığı yok")
	satir = icerik.split(b"\n", 1)[0].decode("ascii", "replace")
	alanlar: Dict[str, str] = {}
	for parca in satir.split("|")[1:]:
		anahtar, _, deger = parca.partition("=")
		alanlar[anahtar] = deger
	return alanlar


class FakeVideoEngine:
	"""Sentetik biçimle çalışan `VideoEngine` uygulaması."""

	def probe(self, source: VideoSource) -> VideoProbe:
		try:
			alanlar = _coz(source)
		except ProbeUnavailable:
			# Sözleşme: `probe` HATA ATMAZ, ölçülemediğini söyler (NFR-043).
			return VideoProbe(measured=False)
		return VideoProbe(
			width=int(alanlar.get("w") or 0),
			height=int(alanlar.get("h") or 0),
			duration_s=float(alanlar.get("dur") or 0.0),
			bitrate_bps=int(alanlar.get("br") or 0),
			frame_rate=float(alanlar.get("fps") or 0.0),
			container=alanlar.get("c") or "",
			video_codec=alanlar.get("vc") or "",
			audio_codec=(alanlar.get("ac") or "") if alanlar.get("audio") == "1" else "",
			has_audio=alanlar.get("audio") == "1",
			measured=True,
		)

	def needs_transcode(
		self,
		probe: VideoProbe,
		*,
		max_width: int = NEEDS_TRANSCODE_MAX_WIDTH,
		max_bitrate_bps: int = NEEDS_TRANSCODE_MAX_BITRATE_BPS,
	) -> bool:
		if not probe.measured:
			# Ölçemediğin videoyu ATLAMAK güvenli taraf değildir.
			return True
		return probe.width > max_width or probe.bitrate_bps > max_bitrate_bps

	def transcode(
		self, source: VideoSource, spec: VideoRenditionSpec, *, target_path: str = ""
	) -> VideoArtifact:
		alanlar = _coz(source)
		sure = float(alanlar.get("dur") or 0.0)
		if sure <= 0:
			raise TranscodeFailed("Süre okunamadı", detay={"attempts": 1})
		ses_var = alanlar.get("audio") == "1" and spec.audio != AUDIO_STRIPPED
		hedef_kbps = spec.maxrate_kbps or 1600
		icerik = sentetik_video(
			spec.width,
			spec.height,
			duration_s=sure,
			bitrate_bps=hedef_kbps * 1000,
			frame_rate=min(float(alanlar.get("fps") or 30.0), float(spec.frame_rate_cap or 30)),
			container=spec.container,
			video_codec=spec.video_codec,
			audio_codec=spec.audio_codec if ses_var else "",
			has_audio=ses_var,
		)
		notlar = []
		if alanlar.get("audio") == "1" and not ses_var:
			notlar.append("audio_stripped")
		if spec.loudness_filter:
			notlar.append(f"loudnorm:{spec.loudness_filter}")
		return VideoArtifact(
			rendition_id=spec.id,
			width=spec.width,
			height=spec.height,
			duration_s=sure,
			size_bytes=len(icerik),
			container=spec.container,
			content=None if target_path else icerik,
			path=target_path,
			bitrate_bps=hedef_kbps * 1000,
			has_audio=ses_var,
			notes=tuple(notlar),
		)

	def transcode_all(
		self, source: VideoSource, specs: Sequence[VideoRenditionSpec]
	) -> Dict[str, VideoArtifact]:
		# Tümü-ya-hiç: hepsi üretilir, biri düşerse istisna yayılır.
		return {spec.id: self.transcode(source, spec) for spec in specs}

	def make_poster(self, source: VideoSource, spec: PosterSpec) -> EncodedImage:
		alanlar = _coz(source)
		sure = float(alanlar.get("dur") or 0.0)
		pencere_sonu = min(spec.window_end_s, sure * 0.25) if sure else spec.window_end_s
		if pencere_sonu < spec.window_start_s and not (
			spec.retry_window_end_s > spec.retry_window_start_s
		):
			raise TranscodeFailed("Poster penceresi seçilemedi", detay={"duration_s": sure})
		w = spec.width
		kaynak_w = int(alanlar.get("w") or w)
		kaynak_h = int(alanlar.get("h") or w)
		h = spec.height or max(1, int(w * kaynak_h / float(kaynak_w or 1)))
		return EncodedImage(
			content=sentetik_gorsel(spec.format, w, h, quality=spec.quality),
			fmt=spec.format.upper(),
			width=w,
			height=h,
			quality=spec.quality,
			notes=("poster",),
		)

	def make_preview_clip(
		self, source: VideoSource, spec: PreviewClipSpec, *, target_path: str = ""
	) -> VideoArtifact:
		alanlar = _coz(source)
		kaynak_sure = float(alanlar.get("dur") or 0.0)
		sure = min(spec.duration_s, kaynak_sure) if kaynak_sure else spec.duration_s
		icerik = sentetik_video(
			spec.width,
			spec.height,
			duration_s=sure,
			bitrate_bps=500_000,
			container=spec.container,
			video_codec=spec.video_codec,
			has_audio=not spec.silent,
		)
		# Boyut kapısı burada UYGULANMAZ — karar politikanındır (`fits()`).
		return VideoArtifact(
			rendition_id="preview",
			width=spec.width,
			height=spec.height,
			duration_s=sure,
			size_bytes=len(icerik),
			container=spec.container,
			content=None if target_path else icerik,
			path=target_path,
			bitrate_bps=500_000,
			has_audio=not spec.silent,
			notes=("silent",) if spec.silent else (),
		)


__all__ = ["FakeVideoEngine", "sentetik_video", "BASLIK"]

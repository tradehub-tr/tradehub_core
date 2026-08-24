"""T-062 — animated GIF'i video hattının gerçek çıktı sözleşmesine çevir.

Bu modül kuyruk veya Frappe bilmez. ``video_from_animation`` işi tarafından
çağrılacak saf ffmpeg yardımcısıdır ve üç çıktıyı birlikte üretir:

* MP4 / H.264 High / yuv420p / faststart
* WebM / VP9 / yuv420p
* PNG poster

Normal video transcode'undaki INV-05 fayda kapısı burada uygulanmaz. Küçük bir
GIF'in video çıktısı kaynaktan büyük olabilir; bu, animasyonu tek kareye
düşürmekten veya hiç video yayınlamamaktan daha doğru bir teslim sonucudur.
Üç çıktı da ffprobe/Pillow ile doğrulanmadan hedef adlara taşınmaz.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from tradehub_core.media.pipeline.contracts.video import FFMPEG_TIMEOUT_SECONDS
from tradehub_core.media.pipeline.video import probe as probe_module

JOB_TYPE_VIDEO_FROM_ANIMATION: str = "video_from_animation"
ANIMATION_ENGINE_VERSION: str = "1.0.0"
CODE_NOT_ANIMATED_GIF: str = "not_animated_gif"
CODE_FFMPEG_UNAVAILABLE: str = "ffmpeg_unavailable"
CODE_FFMPEG_FAILED: str = "animation_ffmpeg_failed"
CODE_OUTPUT_INVALID: str = "animation_output_invalid"
CODE_OUTPUT_PATH_INVALID: str = "animation_output_path_invalid"
CODE_PUBLISH_FAILED: str = "animation_publish_failed"


@dataclass(frozen=True)
class AnimationSpec:
	"""Animasyon video hedefleri; Phase 2 sözleşmesinin sabit parametreleri."""

	max_width: int = 1280
	frame_rate: int = 30
	h264_crf: int = 23
	h264_preset: str = "medium"
	vp9_crf: int = 32

	def __post_init__(self) -> None:
		if self.max_width <= 0 or self.frame_rate <= 0:
			raise ValueError("animation dimensions/frame rate must be positive")
		if not 0 <= self.h264_crf <= 51 or not 0 <= self.vp9_crf <= 63:
			raise ValueError("animation CRF is out of range")


@dataclass(frozen=True)
class AnimationOutput:
	kind: str
	path: str
	container: str
	codec: str
	width: int
	height: int
	size_bytes: int

	def to_dict(self) -> dict:
		return asdict(self)


@dataclass(frozen=True)
class AnimationResult:
	ok: bool
	reason: str = ""
	job_type: str = JOB_TYPE_VIDEO_FROM_ANIMATION
	outputs: tuple[AnimationOutput, ...] = ()
	notes: tuple[str, ...] = ()

	def to_dict(self) -> dict:
		return {
			"ok": self.ok,
			"reason": self.reason,
			"job_type": self.job_type,
			"outputs": [output.to_dict() for output in self.outputs],
			"notes": list(self.notes),
		}


def ffmpeg_available() -> bool:
	"""ffmpeg ikilisi çalıştırılabiliyor mu — test/healthcheck yardımcısı."""
	try:
		subprocess.run(
			["ffmpeg", "-version"],
			capture_output=True,
			check=True,
			timeout=10,
		)
		return True
	except (OSError, subprocess.SubprocessError):
		return False


def _scale_filter(spec: AnimationSpec, *, poster: bool = False) -> str:
	# `min()` içindeki virgül filtergraph ayracıdır; tek tırnak libavfilter'ın
	# expression parser'ı içindir, shell quoting değildir. Genişlik aşağı doğru
	# çift sayıya çekilir ve 1 px kaynakta en az 2 olur; -2 de yüksekliği çift
	# üretir. Böylece yuv420p/libx264 odd-dimension girdiyi reddetmez.
	genislik = f"max(2,trunc(min({spec.max_width},iw)/2)*2)"
	resize = f"scale='{genislik}':-2"
	if poster:
		return resize
	return f"{resize},fps={spec.frame_rate},format=yuv420p"


def build_commands(
	src: str | os.PathLike[str],
	mp4: str | os.PathLike[str],
	webm: str | os.PathLike[str],
	poster: str | os.PathLike[str],
	*,
	spec: AnimationSpec | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
	"""MP4, WebM ve poster ffmpeg komutlarını deterministik sırada kur."""
	spec = spec or AnimationSpec()
	kaynak = str(src)
	taban = (
		"ffmpeg",
		"-hide_banner",
		"-loglevel",
		"error",
		"-y",
		"-ignore_loop",
		"1",
		"-i",
		kaynak,
		"-map",
		"0:v:0",
		"-an",
	)
	mp4_cmd = taban + (
		"-vf",
		_scale_filter(spec),
		"-c:v",
		"libx264",
		"-profile:v",
		"high",
		"-level:v",
		"4.0",
		"-crf",
		str(spec.h264_crf),
		"-preset",
		spec.h264_preset,
		"-pix_fmt",
		"yuv420p",
		"-movflags",
		"+faststart",
		str(mp4),
	)
	webm_cmd = taban + (
		"-vf",
		_scale_filter(spec),
		"-c:v",
		"libvpx-vp9",
		"-crf",
		str(spec.vp9_crf),
		"-b:v",
		"0",
		"-row-mt",
		"1",
		"-pix_fmt",
		"yuv420p",
		str(webm),
	)
	poster_cmd = taban + (
		"-vf",
		_scale_filter(spec, poster=True),
		"-frames:v",
		"1",
		"-c:v",
		"png",
		str(poster),
	)
	return (mp4_cmd, webm_cmd, poster_cmd)


def _is_animated_gif(src: Path) -> bool:
	"""Konteyner GIF mi ve en az iki kare beyan ediyor mu."""
	try:
		from PIL import Image

		with Image.open(src) as im:
			return (im.format or "").upper() == "GIF" and int(getattr(im, "n_frames", 1) or 1) > 1
	except Exception:
		return False


def _temporary_output(destination: Path) -> Path:
	"""Hedefle aynı dosya sisteminde, doğru uzantılı atomik ara yol."""
	fd, ad = tempfile.mkstemp(
		prefix=f".{destination.stem}.animation-",
		suffix=destination.suffix,
		dir=destination.parent,
	)
	os.close(fd)
	return Path(ad)


def _video_output(path: Path, *, container: str, codec: str) -> AnimationOutput | None:
	"""ffprobe sonucu tam hedef container/codec değilse fail-closed dön."""
	facts = probe_module.probe(str(path))
	if not facts.measured:
		return None
	if (facts.container_family, facts.video_codec) != (container, codec):
		return None
	if container == "mp4" and facts.moov_at_end:
		return None
	return AnimationOutput(
		kind="video",
		path=str(path),
		container=container,
		codec=codec,
		width=facts.width,
		height=facts.height,
		size_bytes=path.stat().st_size,
	)


def _poster_output(path: Path) -> AnimationOutput | None:
	"""Poster gerçekten açılabilir PNG mi; uzantıya güvenme."""
	try:
		from PIL import Image

		with Image.open(path) as im:
			if (im.format or "").upper() != "PNG":
				return None
			im.verify()
		with Image.open(path) as im:
			width, height = im.size
		return AnimationOutput(
			kind="poster",
			path=str(path),
			container="png",
			codec="png",
			width=width,
			height=height,
			size_bytes=path.stat().st_size,
		)
	except Exception:
		return None


def convert(
	src: str | os.PathLike[str],
	mp4: str | os.PathLike[str],
	webm: str | os.PathLike[str],
	poster: str | os.PathLike[str],
	*,
	spec: AnimationSpec | None = None,
	timeout: int = FFMPEG_TIMEOUT_SECONDS,
) -> AnimationResult:
	"""Animated GIF'ten üç doğrulanmış çıktı üret; fayda kapısı uygulama."""
	spec = spec or AnimationSpec()
	kaynak = Path(src)
	hedefler = (Path(mp4), Path(webm), Path(poster))
	if not _is_animated_gif(kaynak):
		return AnimationResult(ok=False, reason=CODE_NOT_ANIMATED_GIF)

	cozulmus = [yol.resolve(strict=False) for yol in (kaynak, *hedefler)]
	if len(set(cozulmus)) != len(cozulmus) or any(not yol.parent.is_dir() for yol in hedefler):
		return AnimationResult(ok=False, reason=CODE_OUTPUT_PATH_INVALID)
	if not ffmpeg_available() or not probe_module.ffprobe_available():
		return AnimationResult(ok=False, reason=CODE_FFMPEG_UNAVAILABLE)

	geciciler: list[Path] = []
	notlar: list[str] = []
	try:
		geciciler = [_temporary_output(yol) for yol in hedefler]
		komutlar = build_commands(kaynak, *geciciler, spec=spec)
		for ad, komut in zip(("mp4", "webm", "poster"), komutlar, strict=True):
			try:
				sonuc = subprocess.run(
					komut,
					capture_output=True,
					check=False,
					timeout=timeout,
				)
			except FileNotFoundError:
				return AnimationResult(ok=False, reason=CODE_FFMPEG_UNAVAILABLE, notes=tuple(notlar))
			except subprocess.TimeoutExpired:
				return AnimationResult(
					ok=False,
					reason=CODE_FFMPEG_FAILED,
					notes=(*notlar, f"ffmpeg:{ad}:timeout"),
				)
			if sonuc.returncode:
				stderr = (sonuc.stderr or b"").decode("utf-8", "replace").strip()[-300:]
				return AnimationResult(
					ok=False,
					reason=CODE_FFMPEG_FAILED,
					notes=(*notlar, f"ffmpeg:{ad}:exit={sonuc.returncode}:{stderr}"),
				)
			notlar.append(f"ffmpeg:{ad}:ok")

		mp4_out = _video_output(geciciler[0], container="mp4", codec="h264")
		webm_out = _video_output(geciciler[1], container="webm", codec="vp9")
		poster_out = _poster_output(geciciler[2])
		if mp4_out is None or webm_out is None or poster_out is None:
			return AnimationResult(
				ok=False,
				reason=CODE_OUTPUT_INVALID,
				notes=(*notlar, "probe:exact_contract_failed"),
			)

		for gecici, hedef in zip(geciciler, hedefler, strict=True):
			os.replace(gecici, hedef)

		outputs = (
			AnimationOutput(**{**mp4_out.to_dict(), "path": str(hedefler[0])}),
			AnimationOutput(**{**webm_out.to_dict(), "path": str(hedefler[1])}),
			AnimationOutput(**{**poster_out.to_dict(), "path": str(hedefler[2])}),
		)
		return AnimationResult(
			ok=True,
			outputs=outputs,
			notes=(*notlar, "probe:mp4/h264", "probe:webm/vp9", "probe:poster/png"),
		)
	except OSError as exc:
		return AnimationResult(
			ok=False,
			reason=CODE_PUBLISH_FAILED,
			notes=(*notlar, f"publish:{type(exc).__name__}"),
		)
	finally:
		for gecici in geciciler:
			gecici.unlink(missing_ok=True)


__all__ = [
	"ANIMATION_ENGINE_VERSION",
	"AnimationOutput",
	"AnimationResult",
	"AnimationSpec",
	"CODE_FFMPEG_FAILED",
	"CODE_FFMPEG_UNAVAILABLE",
	"CODE_NOT_ANIMATED_GIF",
	"CODE_OUTPUT_INVALID",
	"CODE_OUTPUT_PATH_INVALID",
	"CODE_PUBLISH_FAILED",
	"JOB_TYPE_VIDEO_FROM_ANIMATION",
	"build_commands",
	"convert",
	"ffmpeg_available",
]

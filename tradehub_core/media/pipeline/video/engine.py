"""Production ``VideoEngine`` adapter for ffprobe/ffmpeg modules.

The adapter owns only contract translation and temporary-file lifecycle.  The
actual process isolation and coded error mapping remain in the Phase 7 probe,
transcode and poster modules.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from tradehub_core.media.pipeline.contracts.errors import TranscodeFailed
from tradehub_core.media.pipeline.contracts.image import EncodedImage
from tradehub_core.media.pipeline.contracts.video import (
	AUDIO_STRIPPED,
	FFMPEG_TIMEOUT_SECONDS,
	NEEDS_TRANSCODE_MAX_BITRATE_BPS,
	NEEDS_TRANSCODE_MAX_WIDTH,
	PosterSpec,
	PreviewClipSpec,
	VideoArtifact,
	VideoProbe,
	VideoRenditionSpec,
	VideoSource,
)
from tradehub_core.media.pipeline.video import poster as poster_mod
from tradehub_core.media.pipeline.video import probe as probe_mod
from tradehub_core.media.pipeline.video.transcode import run_ffmpeg

_TOKEN = re.compile(r"^[A-Za-z0-9_.-]+$")
_CONTAINER_SUFFIX = {
	"avi": ".avi",
	"matroska": ".mkv",
	"mkv": ".mkv",
	"mov": ".mov",
	"mp4": ".mp4",
	"ogg": ".ogv",
	"webm": ".webm",
}


def _safe_token(value: str, field: str) -> str:
	value = (value or "").strip().lower()
	if not value or not _TOKEN.fullmatch(value):
		raise TranscodeFailed(f"Geçersiz {field} değeri.", detay={"field": field})
	return value


@contextmanager
def _source_path(source: VideoSource) -> Iterator[str]:
	"""Yield a seekable source path and erase byte-backed temporary input."""
	if source.path:
		if not Path(source.path).is_file():
			raise TranscodeFailed("Video kaynağı bulunamadı.", retryable=False)
		yield source.path
		return
	with tempfile.TemporaryDirectory(prefix="media-video-source-") as directory:
		path = Path(directory) / "source.bin"
		path.write_bytes(source.content or b"")
		yield str(path)


def _video_filters(spec: VideoRenditionSpec, probe: VideoProbe) -> list[str]:
	filters = [
		f"scale='min({spec.width},iw)':'min({spec.height},ih)':"
		"force_original_aspect_ratio=decrease:force_divisible_by=2"
	]
	if spec.frame_rate_cap and probe.frame_rate > spec.frame_rate_cap:
		filters.append(f"fps={spec.frame_rate_cap}")
	return filters


def _codec_args(spec: VideoRenditionSpec) -> list[str]:
	codec = _safe_token(spec.video_codec, "video_codec")
	args = ["-c:v", codec]
	if "vpx" in codec or codec in ("vp8", "vp9"):
		args += ["-b:v", "0", "-crf", str(spec.crf), "-deadline", "good", "-cpu-used", "2"]
	else:
		args += ["-crf", str(spec.crf)]
	if spec.maxrate_kbps:
		args += ["-maxrate", f"{spec.maxrate_kbps}k"]
	if spec.bufsize_kbps:
		args += ["-bufsize", f"{spec.bufsize_kbps}k"]
	args += ["-pix_fmt", "yuv420p", "-threads:v", "2"]
	if codec in ("h264", "libx264"):
		args += ["-preset", "medium"]
	return args


def _build_command(
	src: str,
	dst: str,
	spec: VideoRenditionSpec,
	probe: VideoProbe,
	*,
	start_s: float = 0.0,
	duration_s: float = 0.0,
) -> list[str]:
	container = _safe_token(spec.container, "container")
	cmd = ["ffmpeg", "-y", "-hide_banner"]
	if start_s > 0:
		cmd += ["-ss", f"{start_s:.3f}"]
	if duration_s > 0:
		cmd += ["-t", f"{duration_s:.3f}"]
	cmd += ["-i", src, "-map", "0:v:0", "-vf", ",".join(_video_filters(spec, probe))]
	cmd += _codec_args(spec)
	if spec.keyframe_interval_s:
		fps = min(probe.frame_rate or spec.frame_rate_cap or 30, spec.frame_rate_cap or 30)
		gop = max(1, int(round(fps * spec.keyframe_interval_s)))
		cmd += ["-g", str(gop), "-keyint_min", str(gop)]
	if spec.audio == AUDIO_STRIPPED or not probe.has_audio:
		cmd += ["-an"]
	else:
		cmd += [
			"-map",
			"0:a:0?",
			"-c:a",
			_safe_token(spec.audio_codec, "audio_codec"),
			"-b:a",
			f"{spec.audio_bitrate_kbps}k",
			"-ac",
			str(spec.audio_channels),
		]
		if spec.loudness_filter:
			cmd += ["-af", spec.loudness_filter]
	if container in ("mp4", "mov"):
		cmd += ["-movflags", "+faststart"]
	cmd += ["-f", container, "-progress", "pipe:1", "-nostats", dst]
	return cmd


def _output_paths(target_path: str, container: str, directory: str) -> tuple[Path, Path | None]:
	"""Return encode path and optional atomically promoted final path."""
	if not target_path:
		return Path(directory) / f"result{_CONTAINER_SUFFIX.get(container, '.' + container)}", None
	final = Path(target_path)
	final.parent.mkdir(parents=True, exist_ok=True)
	encode = final.with_name(f".{final.name}.part-{os.getpid()}{final.suffix or '.media'}")
	return encode, final


class FfmpegVideoEngine:
	"""ffprobe/ffmpeg-backed implementation of the frozen video contract."""

	def probe(self, source: VideoSource) -> VideoProbe:
		with _source_path(source) as path:
			return probe_mod.probe(path).to_contract()

	def needs_transcode(
		self,
		probe: VideoProbe,
		*,
		max_width: int = NEEDS_TRANSCODE_MAX_WIDTH,
		max_bitrate_bps: int = NEEDS_TRANSCODE_MAX_BITRATE_BPS,
	) -> bool:
		if not probe.measured:
			return True
		return probe.width > max_width or probe.bitrate_bps > max_bitrate_bps

	def transcode(
		self, source: VideoSource, spec: VideoRenditionSpec, *, target_path: str = ""
	) -> VideoArtifact:
		with _source_path(source) as src, tempfile.TemporaryDirectory(
			prefix="media-video-output-"
		) as directory:
			facts = probe_mod.probe(src)
			probe = facts.to_contract()
			if not probe.measured:
				raise TranscodeFailed("Video künyesi okunamadı.", detay={"attempts": 1})
			if target_path and Path(src).resolve() == Path(target_path).resolve():
				raise TranscodeFailed("Kaynağın yerinde değiştirilmesi desteklenmiyor.", retryable=False)
			container = _safe_token(spec.container, "container")
			encoded, final = _output_paths(target_path, container, directory)
			try:
				run_ffmpeg(_build_command(src, str(encoded), spec, probe), timeout=FFMPEG_TIMEOUT_SECONDS)
				out_facts = probe_mod.probe(str(encoded))
				if not out_facts.measured:
					raise TranscodeFailed("Üretilen video doğrulanamadı.", detay={"attempts": 1})
				content = None if final else encoded.read_bytes()
				size = encoded.stat().st_size
				if final:
					os.replace(encoded, final)
			except Exception:
				encoded.unlink(missing_ok=True)
				raise
			notes = []
			if probe.has_audio and spec.audio == AUDIO_STRIPPED:
				notes.append("audio_stripped")
			if spec.loudness_filter:
				notes.append(f"loudnorm:{spec.loudness_filter}")
			return VideoArtifact(
				rendition_id=spec.id,
				width=out_facts.width,
				height=out_facts.height,
				duration_s=out_facts.duration_s,
				size_bytes=size,
				container=out_facts.container_family or container,
				content=content,
				path=str(final) if final else "",
				bitrate_bps=out_facts.format_bitrate_bps or out_facts.video_bitrate_bps,
				has_audio=out_facts.has_audio,
				notes=tuple(notes),
			)

	def transcode_all(
		self, source: VideoSource, specs: Sequence[VideoRenditionSpec]
	) -> dict[str, VideoArtifact]:
		ids = [spec.id for spec in specs]
		if len(ids) != len(set(ids)):
			raise TranscodeFailed("Rendition kümesinde yinelenen kimlik var.", retryable=False)
		# All artifacts remain in memory.  An exception discards the local dict,
		# so callers can never observe a partial ladder.
		return {spec.id: self.transcode(source, spec) for spec in specs}

	def make_poster(self, source: VideoSource, spec: PosterSpec) -> EncodedImage:
		fmt = _safe_token(spec.format, "poster_format")
		if fmt not in ("jpeg", "jpg", "webp"):
			raise TranscodeFailed("Poster biçimi desteklenmiyor.", retryable=False)
		with _source_path(source) as src, tempfile.TemporaryDirectory(
			prefix="media-video-poster-"
		) as directory:
			facts = probe_mod.probe(src)
			if not facts.measured:
				raise TranscodeFailed("Poster için video künyesi okunamadı.", detay={"attempts": 1})
			dst = Path(directory) / ("poster.webp" if fmt == "webp" else "poster.jpg")
			module_spec = poster_mod.PosterSpec(
				window_start_s=spec.window_start_s,
				thumbnail_frames=spec.frames,
				format="webp" if fmt == "webp" else "jpeg",
				quality_ladder=(spec.quality,),
				width=spec.width,
				min_luma_pct=spec.min_brightness,
				max_retries=1 if spec.retry_window_end_s > spec.retry_window_start_s else 0,
			)
			result = poster_mod.make_poster(src, str(dst), spec=module_spec, facts=facts)
			try:
				from PIL import Image

				with Image.open(dst) as image:
					width, height = image.size
					image.verify()
			except Exception as exc:
				raise TranscodeFailed("Üretilen poster doğrulanamadı.") from exc
			return EncodedImage(
				content=dst.read_bytes(),
				fmt="WEBP" if fmt == "webp" else "JPEG",
				width=width,
				height=height,
				quality=result.quality,
				notes=("poster", f"timestamp:{result.timestamp_s:.3f}", *tuple(result.notes)),
			)

	def make_preview_clip(
		self, source: VideoSource, spec: PreviewClipSpec, *, target_path: str = ""
	) -> VideoArtifact:
		rendition = VideoRenditionSpec(
			id="preview",
			width=spec.width,
			height=spec.height,
			container=spec.container,
			video_codec=spec.video_codec,
			crf=32,
			frame_rate_cap=30,
			audio=AUDIO_STRIPPED if spec.silent else "allowed",
			max_bytes=spec.max_bytes,
		)
		with _source_path(source) as src, tempfile.TemporaryDirectory(
			prefix="media-video-preview-"
		) as directory:
			facts = probe_mod.probe(src)
			probe = facts.to_contract()
			if not probe.measured:
				raise TranscodeFailed("Önizleme için video künyesi okunamadı.", detay={"attempts": 1})
			container = _safe_token(spec.container, "container")
			encoded, final = _output_paths(target_path, container, directory)
			duration = min(spec.duration_s, max(probe.duration_s - spec.start_offset_s, 0.0))
			if duration <= 0:
				raise TranscodeFailed("Önizleme süresi kaynak dışında kalıyor.", retryable=False)
			try:
				run_ffmpeg(
					_build_command(
						src,
						str(encoded),
						rendition,
						probe,
						start_s=spec.start_offset_s,
						duration_s=duration,
					),
					timeout=FFMPEG_TIMEOUT_SECONDS,
				)
				out_facts = probe_mod.probe(str(encoded))
				if not out_facts.measured:
					raise TranscodeFailed("Üretilen önizleme doğrulanamadı.", detay={"attempts": 1})
				content = None if final else encoded.read_bytes()
				size = encoded.stat().st_size
				if final:
					os.replace(encoded, final)
			except Exception:
				encoded.unlink(missing_ok=True)
				raise
			notes = ["silent"] if spec.silent else []
			if spec.loop:
				notes.append("loopable")
			return VideoArtifact(
				rendition_id="preview",
				width=out_facts.width,
				height=out_facts.height,
				duration_s=out_facts.duration_s,
				size_bytes=size,
				container=out_facts.container_family or container,
				content=content,
				path=str(final) if final else "",
				bitrate_bps=out_facts.format_bitrate_bps or out_facts.video_bitrate_bps,
				has_audio=out_facts.has_audio,
				notes=tuple(notes),
			)


__all__ = ["FfmpegVideoEngine"]

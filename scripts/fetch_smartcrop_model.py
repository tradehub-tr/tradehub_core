#!/usr/bin/env python3
"""T-014 U²-Net-P ONNX modelini hash doğrulamasıyla indir."""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path

URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"
SHA256 = "309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8"
MAX_BYTES = 6 * 1024 * 1024


def digest(path: Path) -> str:
	return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--output", default=".smartcrop-work/u2netp.onnx")
	args = parser.parse_args()
	target = Path(args.output).expanduser().resolve()
	if target.is_file():
		if digest(target) != SHA256:
			raise SystemExit(f"mevcut model hash'i yanlış; elle inceleyin: {target}")
		print(f"model hazır: {target} ({target.stat().st_size} bayt)")
		return 0
	target.parent.mkdir(parents=True, exist_ok=True)
	request = urllib.request.Request(URL, headers={"User-Agent": "tradehub-media-engine-t014/1"})
	with urllib.request.urlopen(request, timeout=30) as response:
		data = response.read(MAX_BYTES + 1)
	if len(data) > MAX_BYTES:
		raise SystemExit("model beklenen 6 MB tavanını aşıyor")
	if hashlib.sha256(data).hexdigest() != SHA256:
		raise SystemExit("indirilen model SHA-256 doğrulamasından geçmedi")
	fd, temporary = tempfile.mkstemp(prefix="u2netp-", suffix=".onnx", dir=str(target.parent))
	try:
		with os.fdopen(fd, "wb") as handle:
			handle.write(data)
			handle.flush()
			os.fsync(handle.fileno())
		os.replace(temporary, target)
	except Exception:
		try:
			Path(temporary).unlink(missing_ok=True)
		except Exception:
			pass
		raise
	print(f"model indirildi: {target} ({len(data)} bayt, sha256={SHA256})")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

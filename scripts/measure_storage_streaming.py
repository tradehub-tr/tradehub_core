#!/usr/bin/env python3
"""Measure T-050's 2 GiB streaming-memory acceptance without retaining data."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.storage.local import LocalDiskStorage  # noqa: E402


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--bytes", type=int, default=2 * 1024**3)
	parser.add_argument("--chunk-bytes", type=int, default=1024 * 1024)
	args = parser.parse_args()
	if args.bytes < 1 or args.chunk_bytes < 1:
		parser.error("--bytes and --chunk-bytes must be positive")

	chunk = b"\0" * min(args.chunk_bytes, args.bytes)

	def stream():
		remaining = args.bytes
		while remaining:
			part = chunk if remaining >= len(chunk) else chunk[:remaining]
			yield part
			remaining -= len(part)

	with tempfile.TemporaryDirectory(prefix="media-t050-2gib-") as tmp:
		store = LocalDiskStorage(
			os.path.join(tmp, "public"),
			os.path.join(tmp, "private"),
			fsync=False,
		)
		started = time.perf_counter()
		tracemalloc.start()
		try:
			result = store.put_stream(stream(), ".bin")
			current, peak = tracemalloc.get_traced_memory()
		finally:
			tracemalloc.stop()
		elapsed = time.perf_counter() - started
		payload = {
			"requested_bytes": args.bytes,
			"written_bytes": result.stat.size_bytes,
			"chunk_bytes": args.chunk_bytes,
			"python_current_bytes": current,
			"python_peak_bytes": peak,
			"peak_limit_bytes": 100 * 1024 * 1024,
			"within_100mb_budget": peak < 100 * 1024 * 1024,
			"elapsed_seconds": round(elapsed, 3),
			"temporary_output_removed": True,
		}
		print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
		return 0 if payload["within_100mb_budget"] and result.stat.size_bytes == args.bytes else 1


if __name__ == "__main__":
	raise SystemExit(main())

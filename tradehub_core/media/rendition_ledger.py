# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Persistent identity helpers for Media Rendition outputs.

The ledger deliberately records two different facts:

* ``output_sha256`` is the exact byte identity of the immutable output.
* ``engine_signature`` binds those bytes to the engine/versioned production
  coordinates that created them.  It is a deterministic fingerprint, not an
  authentication MAC; only the media worker writes it.

Keeping these values on every historical rendition lets an uploaded engine
output be recognised without re-encoding or relying on an expiring cache.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from typing import BinaryIO

LEDGER_SCHEMA = "media-rendition-output-v1"
_VERSION_IN_URL = re.compile(r"/files/media/[^/]+/([0-9a-f]{64})/")


def content_sha256(content: bytes) -> str:
	"""Return the lowercase SHA-256 identity of an exact byte string."""
	return hashlib.sha256(content).hexdigest()


def _chunks(handle: BinaryIO, size: int = 1024 * 1024) -> Iterator[bytes]:
	while chunk := handle.read(size):
		yield chunk


def file_sha256(path: str) -> str:
	"""Hash a file without loading the complete rendition into memory."""
	hasher = hashlib.sha256()
	with open(path, "rb") as handle:
		for chunk in _chunks(handle):
			hasher.update(chunk)
	return hasher.hexdigest()


def engine_signature(
	*,
	engine_version: str,
	version_hash: str,
	profile: str,
	width: int,
	fmt: str,
	output_sha256: str,
) -> str:
	"""Bind exact output bytes to their deterministic production coordinates."""
	payload = {
		"engine_version": str(engine_version or "unknown"),
		"format": str(fmt or "").lower(),
		"output_sha256": str(output_sha256 or "").lower(),
		"profile": str(profile or ""),
		"schema": LEDGER_SCHEMA,
		"version_hash": str(version_hash or "legacy"),
		"width": int(width or 0),
	}
	encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
	return hashlib.sha256(encoded).hexdigest()


def rendition_key(
	asset: str,
	version_hash: str | None,
	profile: str,
	width: int,
	fmt: str,
) -> str:
	"""Return the unique logical key of a rendition in one immutable version."""
	return "|".join(
		(
			str(asset or ""),
			str(version_hash or "legacy"),
			str(profile or ""),
			str(int(width or 0)),
			str(fmt or "").lower(),
		)
	)


def version_hash_from_url(file_url: str | None) -> str | None:
	"""Extract the canonical 64-hex version component from a rendition URL."""
	match = _VERSION_IN_URL.search(str(file_url or ""))
	return match.group(1) if match else None

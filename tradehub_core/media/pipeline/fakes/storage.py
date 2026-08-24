"""`StorageAdapter`'ın bellek-içi sahte uygulaması."""

from __future__ import annotations

import hmac
import time
from typing import Dict, Iterable, Iterator, Optional, Tuple

from tradehub_core.media.pipeline.contracts.errors import ObjectNotFound, StorageConflict
from tradehub_core.media.pipeline.contracts.storage import (
	SCOPE_PRIVATE,
	SCOPE_PUBLIC,
	SCOPES,
	ObjectKey,
	ObjectRef,
	ObjectStat,
	PutResult,
	content_hash,
	key_for,
)

# İmzalı URL TTL clamp'i (FR-113). Sahte uygulama da clamp'ler: sözleşme
# "üst sınır olsun" diyor, sayıyı uygulamaya bırakıyor.
MAX_TTL_SECONDS: int = 3600
DEFAULT_TTL_SECONDS: int = 300


class InMemoryStorage:
	"""Sözlük tabanlı depo. Disk yok, `frappe` yok, yan etki yok.

	İçerik-adresli davranışın tamamını taşır: aynı içeriği ikinci kez yazmak
	depoyu değiştirmez (`created=False`), aynı anahtara farklı içerik yazmak
	`StorageConflict` atar.
	"""

	def __init__(self, *, secret: bytes = b"fake-signing-key") -> None:
		# (scope, relative) -> (content, modified_at)
		self._objects: Dict[Tuple[str, str], Tuple[bytes, float]] = {}
		self._secret = secret

	# ── yardımcılar ────────────────────────────────────────────────────

	def _addr(self, ref: ObjectRef) -> Tuple[str, str]:
		return (ref.scope, ref.key.relative)

	def __len__(self) -> int:
		return len(self._objects)

	def clear(self) -> None:
		self._objects.clear()

	# ── StorageAdapter ─────────────────────────────────────────────────

	def put(self, content: bytes, extension: str, *, scope: str = SCOPE_PUBLIC) -> PutResult:
		if scope not in SCOPES:
			raise ValueError(f"Bilinmeyen kapsam: {scope!r}")
		key = key_for(content, extension)
		ref = ObjectRef(key=key, scope=scope)
		addr = self._addr(ref)
		mevcut = self._objects.get(addr)
		if mevcut is not None:
			if mevcut[0] != content:
				raise StorageConflict(
					"Aynı anahtara farklı içerik yazılamaz",
					detay={"url": ref.url},
				)
			return PutResult(ref=ref, created=False, stat=self.stat(ref))
		self._objects[addr] = (content, time.time())
		return PutResult(ref=ref, created=True, stat=self.stat(ref))

	def get(self, ref: ObjectRef) -> bytes:
		kayit = self._objects.get(self._addr(ref))
		if kayit is None:
			raise ObjectNotFound("Nesne bulunamadı", detay={"url": ref.url})
		return kayit[0]

	def put_stream(
		self,
		chunks: Iterable[bytes],
		extension: str,
		*,
		scope: str = SCOPE_PUBLIC,
	) -> PutResult:
		# Test sahte deposu küçük girdiler içindir; üretim adaptörlerinin sabit
		# bellek garantisi Local/S3 sözleşme testlerinde ayrıca ölçülür.
		return self.put(b"".join(bytes(chunk) for chunk in chunks), extension, scope=scope)

	def iter_bytes(self, ref: ObjectRef, *, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
		if int(chunk_size) < 1:
			raise ValueError("chunk_size pozitif olmalıdır")
		content = self.get(ref)
		for offset in range(0, len(content), int(chunk_size)):
			yield content[offset : offset + int(chunk_size)]

	def exists(self, ref: ObjectRef) -> bool:
		return self._addr(ref) in self._objects

	def stat(self, ref: ObjectRef) -> ObjectStat:
		kayit = self._objects.get(self._addr(ref))
		if kayit is None:
			raise ObjectNotFound("Nesne bulunamadı", detay={"url": ref.url})
		icerik, mtime = kayit
		return ObjectStat(
			size_bytes=len(icerik), content_hash=content_hash(icerik), modified_at=mtime
		)

	def delete(self, ref: ObjectRef) -> bool:
		return self._objects.pop(self._addr(ref), None) is not None

	def move(self, source: ObjectRef, target_scope: str) -> ObjectRef:
		if target_scope not in SCOPES:
			raise ValueError(f"Bilinmeyen kapsam: {target_scope!r}")
		icerik = self.get(source)
		hedef = ObjectRef(key=source.key, scope=target_scope)
		if hedef == source:
			return hedef
		mevcut = self._objects.get(self._addr(hedef))
		if mevcut is not None and mevcut[0] != icerik:
			raise StorageConflict("Hedefte farklı içerik var", detay={"url": hedef.url})
		self._objects[self._addr(hedef)] = (icerik, time.time())
		del self._objects[self._addr(source)]
		return hedef

	def iter_keys(self, *, scope: str = SCOPE_PUBLIC, prefix: str = "") -> Iterator[ObjectKey]:
		for (s, rel) in list(self._objects.keys()):
			if s != scope or not rel.startswith(prefix):
				continue
			shard, _, name = rel.partition("/")
			yield ObjectKey(shard=shard, name=name)

	def url_for(self, ref: ObjectRef, *, ttl_seconds: Optional[int] = None) -> str:
		if ref.scope != SCOPE_PRIVATE:
			# Public kapsamda TTL YOK SAYILIR — sözleşme böyle diyor.
			return ref.url
		ttl = DEFAULT_TTL_SECONDS if ttl_seconds is None else int(ttl_seconds)
		ttl = max(1, min(ttl, MAX_TTL_SECONDS))
		expires = int(time.time()) + ttl
		imza = hmac.new(self._secret, f"{ref.url}:{expires}".encode(), "sha256").hexdigest()[:16]
		return f"{ref.url}?expires={expires}&sig={imza}"


__all__ = ["InMemoryStorage", "MAX_TTL_SECONDS", "DEFAULT_TTL_SECONDS"]

"""
Sitemap XML cache + dirty flag yönetimi.

Pure logic (`SitemapCache`, `InMemoryCacheBackend`, key helpers) Frappe
runtime'a bağımlı değildir; standalone test edilebilir.

Frappe wrapper `get_default_cache()` site Redis backend'ini kullanır.
"""

from typing import Protocol

CACHE_KEY_PREFIX = "tradehub:seo:sitemap:"
DIRTY_KEY_PREFIX = "tradehub:seo:sitemap_dirty:"
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h


def cache_key_for(target: str) -> str:
	"""`'index'` veya doctype adı için Redis cache key üretir."""
	return f"{CACHE_KEY_PREFIX}{target}"


def dirty_key_for(doctype: str) -> str:
	"""Doctype için dirty flag Redis key üretir."""
	return f"{DIRTY_KEY_PREFIX}{doctype}"


class CacheBackend(Protocol):
	def get(self, key: str) -> str | None: ...
	def set(self, key: str, value: str, ttl: int) -> None: ...
	def delete(self, key: str) -> None: ...


class InMemoryCacheBackend:
	"""Test için in-memory backend. TTL ignore edilir (kısa-ömürlü test)."""

	def __init__(self):
		self._store: dict[str, str] = {}

	def get(self, key: str) -> str | None:
		return self._store.get(key)

	def set(self, key: str, value: str, ttl: int) -> None:
		self._store[key] = value

	def delete(self, key: str) -> None:
		self._store.pop(key, None)


class SitemapCache:
	"""XML + dirty flag yönetimi için cache wrapper.

	Backend dependency injection ile gelir (test'te InMemory, production'da Redis)."""

	def __init__(self, backend: CacheBackend):
		self.backend = backend

	def get_xml(self, target: str) -> str | None:
		return self.backend.get(cache_key_for(target))

	def set_xml(self, target: str, xml: str) -> None:
		self.backend.set(cache_key_for(target), xml, ttl=CACHE_TTL_SECONDS)

	def invalidate_xml(self, target: str) -> None:
		self.backend.delete(cache_key_for(target))

	def mark_dirty(self, doctype: str) -> None:
		self.backend.set(dirty_key_for(doctype), "1", ttl=CACHE_TTL_SECONDS)

	def clear_dirty(self, doctype: str) -> None:
		self.backend.delete(dirty_key_for(doctype))

	def is_dirty(self, doctype: str) -> bool:
		return self.backend.get(dirty_key_for(doctype)) == "1"


def get_default_cache() -> SitemapCache:
	"""Frappe Redis backend'ini saran default cache instance."""
	import frappe

	class FrappeRedisBackend:
		def get(self, key: str) -> str | None:
			val = frappe.cache.get_value(key)
			if val is None:
				return None
			if isinstance(val, str):
				return val
			if isinstance(val, bytes):
				return val.decode("utf-8")
			return str(val)

		def set(self, key: str, value: str, ttl: int) -> None:
			frappe.cache.set_value(key, value, expires_in_sec=ttl)

		def delete(self, key: str) -> None:
			frappe.cache.delete_value(key)

	return SitemapCache(backend=FrappeRedisBackend())

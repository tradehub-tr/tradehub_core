"""
SEO Redirect Redis cache.

Pure `RedirectCache` (in-memory backend ile test) + Frappe wrapper.
1 saat TTL, on_update invalidate.
"""

import json
from typing import Protocol

CACHE_KEY = "tradehub:seo:redirects:all"
CACHE_TTL_SECONDS = 60 * 60  # 1h


class CacheBackend(Protocol):
	def get(self, key: str) -> str | None: ...
	def set(self, key: str, value: str, ttl: int) -> None: ...
	def delete(self, key: str) -> None: ...


class InMemoryCacheBackend:
	"""Test için in-memory backend."""

	def __init__(self):
		self._store: dict[str, str] = {}

	def get(self, key: str) -> str | None:
		return self._store.get(key)

	def set(self, key: str, value: str, ttl: int) -> None:
		self._store[key] = value

	def delete(self, key: str) -> None:
		self._store.pop(key, None)


class RedirectCache:
	"""Tüm enabled redirect listesini JSON olarak cache'ler."""

	def __init__(self, backend: CacheBackend):
		self.backend = backend

	def get_all_redirects(self) -> list[dict] | None:
		raw = self.backend.get(CACHE_KEY)
		if raw is None:
			return None
		try:
			return json.loads(raw) if isinstance(raw, str) else raw
		except (json.JSONDecodeError, TypeError):
			return None

	def set_all_redirects(self, redirects: list[dict]) -> None:
		self.backend.set(CACHE_KEY, json.dumps(redirects), ttl=CACHE_TTL_SECONDS)

	def invalidate(self) -> None:
		self.backend.delete(CACHE_KEY)


def get_default_redirect_cache() -> RedirectCache:
	"""Frappe Redis backend ile wrap edilmiş default cache."""
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

	return RedirectCache(backend=FrappeRedisBackend())


def invalidate_redirect_cache(doc=None, method=None):
	"""on_update hook: SEO Redirect değişince cache temizle."""
	get_default_redirect_cache().invalidate()

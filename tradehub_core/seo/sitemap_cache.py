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


# ── Disk katmanı (BE-MAP) ────────────────────────────────────────────────────
# Milyon-URL ölçeğinde XML parçaları Redis'e sığdırılmaz; disk'e yazılır
# (public/files/sitemaps/), endpoint disk'ten okur. Redis yalnız index +
# küçük tek-parça fallback için kalır. Yazma atomiktir (tmp + os.replace).

SITEMAP_SUBDIR = "sitemaps"


def _sitemap_dir() -> str:
	import os

	import frappe

	path = frappe.get_site_path("public", "files", SITEMAP_SUBDIR)
	os.makedirs(path, exist_ok=True)
	return path


def write_sitemap_file(filename: str, xml: str) -> None:
	"""Tek parça dosyasını atomik yaz."""
	import os

	path = os.path.join(_sitemap_dir(), filename)
	tmp = f"{path}.tmp"
	with open(tmp, "w", encoding="utf-8") as f:
		f.write(xml)
	os.replace(tmp, path)


def read_sitemap_file(filename: str) -> str | None:
	"""Parça dosyasını oku; yoksa None."""
	import os

	path = os.path.join(_sitemap_dir(), filename)
	if not os.path.exists(path):
		return None
	try:
		with open(path, encoding="utf-8") as f:
			return f.read()
	except OSError:
		return None


def cleanup_stale_chunks(sub_name: str, keep_filenames: set[str]) -> None:
	"""Bir sub-sitemap'in ESKİ parça dosyalarını sil (parça sayısı düşünce).

	Bayat parça bırakmak Google'a 'coverage'da olmayan URL' servis eder."""
	import glob as _glob
	import os

	base = _sitemap_dir()
	for path in _glob.glob(os.path.join(base, f"sitemap-{sub_name}*.xml")):
		if os.path.basename(path) not in keep_filenames:
			try:
				os.remove(path)
			except OSError:
				pass


def discover_parts_from_disk() -> dict[str, int]:
	"""Glob fallback: disk'teki parça dosyalarından {sub_name: parça_sayısı}.

	Redis'teki parça sayacı kaybolursa (flush/restore) index yine de doğru
	üretilebilsin diye."""
	import glob as _glob
	import os
	import re

	parts: dict[str, int] = {}
	for path in _glob.glob(os.path.join(_sitemap_dir(), "sitemap-*.xml")):
		m = re.match(r"^sitemap-([a-z-]+?)(?:-(\d+))?\.xml$", os.path.basename(path))
		if not m:
			continue
		sub, num = m.group(1), int(m.group(2) or 1)
		parts[sub] = max(parts.get(sub, 0), num)
	return parts


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

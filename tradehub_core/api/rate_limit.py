"""Faz 5 — Redis-based Rate Limiter.

Endpoint'leri brute-force/spam'a karşı korur. Frappe'in built-in
`frappe.cache` (redis-cache) altyapısını kullanır — ayrı Redis bağlantısı
gerekmez.

Kullanım:
    @rate_limit(max_calls=10, window_seconds=60)
    @frappe.whitelist()
    def my_endpoint(...):
        ...

429-benzeri davranış: limit aşılırsa frappe.throw(TooManyRequestsError).
"""

from __future__ import annotations

import functools

import frappe
from frappe import _


class TooManyRequestsError(frappe.ValidationError):
	"""HTTP 429 karşılığı Frappe exception."""

	http_status_code = 429


def _bucket_key(name: str, user: str) -> str:
	return f"rl:{name}:{user}"


def rate_limit(
	max_calls: int = 60, window_seconds: int = 60, per_user: bool = True, scope: str | None = None
):
	"""Decorator: bir whitelisted endpoint'i rate-limit'ler.

	Args:
		max_calls: pencere içinde izin verilen maks çağrı
		window_seconds: pencere uzunluğu
		per_user: True → user başına ayrı limit; False → global
		scope: cache key prefix (default fonksiyon adı)

	Sliding window algoritması (basit fixed-window — Redis INCR + EXPIRE).
	"""

	def decorator(func):
		key_scope = scope or func.__name__

		@functools.wraps(func)
		def wrapper(*args, **kwargs):
			user = frappe.session.user if per_user else "_global"
			key = _bucket_key(key_scope, user)
			cache = frappe.cache()

			try:
				current = cache.get_value(key)
				current = int(current) if current else 0
			except Exception:
				current = 0

			if current >= max_calls:
				raise TooManyRequestsError(
					_("Çok fazla istek — {0} saniye sonra tekrar deneyin").format(window_seconds)
				)

			# Increment + TTL
			# NOT: Frappe RedisWrapper.set_value var olan key'i override etmiyor;
			# bu yüzden delete + set pattern kullanıyoruz.
			try:
				new_val = current + 1
				cache.delete_value(key)
				cache.set_value(key, new_val, expires_in_sec=window_seconds)
			except Exception:
				# Cache fail olursa endpoint'i bloke etme
				pass

			return func(*args, **kwargs)

		return wrapper

	return decorator


def get_remaining(name: str, user: str | None = None, max_calls: int = 60) -> int:
	"""Kalan çağrı sayısını döner (info amaçlı)."""
	user = user or frappe.session.user
	key = _bucket_key(name, user)
	try:
		current = frappe.cache().get_value(key)
		current = int(current) if current else 0
	except Exception:
		current = 0
	return max(0, max_calls - current)


def reset_bucket(name: str, user: str | None = None):
	"""Test/admin için bir bucket'i sıfırla."""
	user = user or frappe.session.user
	key = _bucket_key(name, user)
	try:
		frappe.cache().delete_value(key)
	except Exception:
		pass


def cleanup_old_records():
	"""Scheduled placeholder. Redis cache TTL ile expire ettiği için no-op."""
	pass

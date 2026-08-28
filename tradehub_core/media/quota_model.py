"""Tenant medya kotasının saf karar sözleşmesi.

Bu modül Frappe veya veritabanına bağımlı değildir. Kullanımın nasıl
ölçüldüğü ``media.files`` içinde, plan limitinin nereden geldiği entitlement
katmanındadır; burada yalnız bu iki sayının kullanıcıya ve yükleme kapısına
nasıl yorumlanacağı tanımlanır.

Semantik:

* plan anahtarı yoksa ``unconfigured`` ve fail-open,
* ``-1`` sınırsız,
* ``0`` medya yüklemesi kapalı,
* pozitif değer MiB cinsinden sert sınır,
* yüzde 80'den itibaren uyarı, yüzde 100'de yeni pozitif yükleme engeli.
"""

from __future__ import annotations

MIB: int = 1024 * 1024
WARNING_THRESHOLD_PERCENT: int = 80

MODE_LIMITED: str = "limited"
MODE_UNLIMITED: str = "unlimited"
MODE_UNCONFIGURED: str = "unconfigured"

STATE_OK: str = "ok"
STATE_WARNING: str = "warning"
STATE_EXHAUSTED: str = "exhausted"
STATE_EXCEEDED: str = "exceeded"


def resolve_limit_mb(value: object) -> tuple[str, int | None]:
	"""Plan değerini ``(mode, bytes)`` çiftine çevir.

	Negatif tarafta yalnız ``-1`` anlamlıdır. Başka bir negatif değer yönetim
	hatasıdır; sessizce sınırsıza çevirmek kota kapısını fark edilmeden açardı.
	"""
	if value is None:
		return MODE_UNCONFIGURED, None

	limit_mb = int(value)
	if limit_mb == -1:
		return MODE_UNLIMITED, None
	if limit_mb < -1:
		raise ValueError("quota.max_storage_mb -1 veya daha büyük olmalı")
	return MODE_LIMITED, limit_mb * MIB


def would_exceed(used_bytes: int, incoming_bytes: int, quota_bytes: int | None) -> bool:
	"""Yeni baytlar sert sınırı aşar mı?

	Eşitlik kabul edilir; mevcut ``File.before_insert`` sözleşmesi de ``>``
	kullanır. ``None`` tanımsız veya sınırsız plan demektir ve engellemez.
	"""
	if quota_bytes is None:
		return False
	return max(0, int(used_bytes)) + max(0, int(incoming_bytes)) > max(
		0, int(quota_bytes)
	)


def summarize(used_bytes: int, quota_bytes: int | None, quota_mode: str) -> dict:
	"""API/panel için kalan, yüzde ve durum alanlarını üret."""
	used = max(0, int(used_bytes or 0))
	if quota_mode in {MODE_UNLIMITED, MODE_UNCONFIGURED}:
		return {
			"quota_mode": quota_mode,
			"quota_state": quota_mode,
			"remaining_bytes": None,
			"usage_percent": None,
			"warning_threshold_percent": WARNING_THRESHOLD_PERCENT,
			"is_warning": False,
			"is_exhausted": False,
			"is_exceeded": False,
			"overage_bytes": 0,
		}

	limit = max(0, int(quota_bytes or 0))
	if limit == 0:
		percent = 100.0
		exhausted = True
		exceeded = used > 0
	else:
		percent = round((used / limit) * 100, 2)
		exhausted = used >= limit
		exceeded = used > limit

	if exceeded:
		state = STATE_EXCEEDED
	elif exhausted:
		state = STATE_EXHAUSTED
	elif percent >= WARNING_THRESHOLD_PERCENT:
		state = STATE_WARNING
	else:
		state = STATE_OK

	return {
		"quota_mode": MODE_LIMITED,
		"quota_state": state,
		"remaining_bytes": max(0, limit - used),
		"usage_percent": percent,
		"warning_threshold_percent": WARNING_THRESHOLD_PERCENT,
		"is_warning": state == STATE_WARNING,
		"is_exhausted": exhausted,
		"is_exceeded": exceeded,
		"overage_bytes": max(0, used - limit),
	}


__all__ = [
	"MIB",
	"MODE_LIMITED",
	"MODE_UNCONFIGURED",
	"MODE_UNLIMITED",
	"STATE_EXCEEDED",
	"STATE_EXHAUSTED",
	"STATE_OK",
	"STATE_WARNING",
	"WARNING_THRESHOLD_PERCENT",
	"resolve_limit_mb",
	"summarize",
	"would_exceed",
]

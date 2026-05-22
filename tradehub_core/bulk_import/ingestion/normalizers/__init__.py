"""Value normalizer registry."""

from collections.abc import Callable
from typing import Any

_REGISTRY: dict[str, Callable[[Any], Any]] = {}


def register_normalizer(name: str, fn: Callable[[Any], Any]) -> None:
	"""Yeni normalizer ekle (plugin mekanizması)."""
	_REGISTRY[name] = fn


def normalize(name: str, value: Any) -> Any:
	"""Registered normalizer'ı çalıştır; kayıtlı değilse veya hata olursa orijinal değeri dön."""
	fn = _REGISTRY.get(name)
	if fn is None:
		return value
	try:
		return fn(value)
	except Exception:
		# Normalizer hatası import flow'u durdurmamalı — orijinal değer geri döner
		return value


def get_registered_names() -> list[str]:
	"""Kayıtlı normalizer isimleri."""
	return list(_REGISTRY.keys())


# Auto-import normalizers to populate registry
from tradehub_core.bulk_import.ingestion.normalizers import (  # noqa: E402, F401
	bool_,
	currency,
	date,
	price,
	qty,
	sku,
)

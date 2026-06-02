"""
Türkçe karakterli string'leri URL-safe slug'a çeviren utility.

`slugify_tr` Frappe runtime'a bağımlı değildir; doğrudan standalone unittest
ile çalıştırılabilir:

	cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_slugify
"""

import re

_TR_MAP = str.maketrans(
	{
		"ç": "c",
		"Ç": "c",
		"ğ": "g",
		"Ğ": "g",
		"ı": "i",
		"I": "i",
		"İ": "i",
		"ö": "o",
		"Ö": "o",
		"ş": "s",
		"Ş": "s",
		"ü": "u",
		"Ü": "u",
	}
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_LEADING_TRAILING_DASH = re.compile(r"^-+|-+$")


def slugify_tr(text: str) -> str:
	"""Türkçe karakterli string'i URL-safe slug'a çevirir."""
	if not text:
		return ""
	lowered = text.translate(_TR_MAP).lower()
	cleaned = _NON_ALNUM.sub("-", lowered)
	return _LEADING_TRAILING_DASH.sub("", cleaned)

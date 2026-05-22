"""Regex Pattern Library resolver — System + Seller Override katmanları."""

import re

import frappe

PATTERN_CACHE_TTL = 300  # 5 dakika


def resolve_column_mapping(headers: list[str], seller_profile: str) -> dict[str, str]:
	"""Header listesi → {canonical_field: header} mapping.

	Strategy:
	1. Seller Override patterns (priority asc)
	2. System patterns (priority asc)
	3. Unmapped headers → manuel
	"""
	mapping: dict[str, str] = {}
	seller_patterns = _get_patterns(seller_profile, "Column Header")
	system_patterns = _get_patterns(None, "Column Header")

	for header in headers:
		if not header:
			continue
		header_lower = str(header).lower().strip()
		if not header_lower:
			continue

		target = _match_patterns(header_lower, seller_patterns)
		if not target:
			target = _match_patterns(header_lower, system_patterns)
		if target and target not in mapping:
			mapping[target] = header

	return mapping


def _match_patterns(text: str, patterns: list[dict]) -> str | None:
	"""Patterns listesinden ilk eşleşeni döndür."""
	for p in patterns:
		for entry in p.get("patterns", []):
			if not entry.get("enabled"):
				continue
			regex_str = entry.get("regex", "")
			if not regex_str or len(regex_str) > 200:
				continue
			flags = _parse_flags(entry.get("flags", ""))
			try:
				if re.search(regex_str, text, flags):
					return p["target_field"]
			except re.error:
				continue
	return None


def _parse_flags(flags_str: str | None) -> int:
	flags = 0
	if not flags_str:
		return flags
	for token in str(flags_str).upper().split(","):
		token = token.strip()
		if token == "IGNORECASE":
			flags |= re.IGNORECASE
		elif token == "UNICODE":
			flags |= re.UNICODE
		elif token == "MULTILINE":
			flags |= re.MULTILINE
	return flags


def _get_patterns(seller_profile: str | None, category: str) -> list[dict]:
	"""Pattern Library kayıtlarını getir (cached)."""
	cache_key = f"regex_patterns:{seller_profile or 'SYSTEM'}:{category}"
	cached = frappe.cache.get_value(cache_key)
	if cached is not None:
		return cached

	filters: dict = {"enabled": 1, "pattern_category": category}
	if seller_profile:
		filters["scope"] = "Seller Override"
		filters["seller_profile"] = seller_profile
	else:
		filters["scope"] = "System"

	try:
		libs = frappe.get_all(
			"Regex Pattern Library",
			filters=filters,
			fields=["name", "target_field", "priority"],
			order_by="priority asc",
		)
	except Exception:
		libs = []

	result: list[dict] = []
	for lib in libs:
		try:
			doc = frappe.get_doc("Regex Pattern Library", lib.name)
		except Exception:
			continue
		result.append(
			{
				"target_field": doc.target_field,
				"priority": doc.priority,
				"patterns": [
					{
						"regex": p.regex,
						"flags": p.flags,
						"enabled": p.enabled,
					}
					for p in (doc.patterns or [])
				],
			}
		)

	frappe.cache.set_value(cache_key, result, expires_in_sec=PATTERN_CACHE_TTL)
	return result


def clear_pattern_cache(doc=None, method=None) -> None:
	"""hooks.py'den çağrılır — Pattern library değişince cache'i temizle."""
	try:
		frappe.cache.delete_keys("regex_patterns:*")
	except Exception:
		pass


@frappe.whitelist()
def test_pattern(regex: str, sample: str, flags: str = "IGNORECASE,UNICODE") -> dict:
	"""Pattern'i örnek string'le test et. SafeRegex koruması ile.

	Returns: {"matched": bool, "match_text": str | None, "error": str | None}
	"""
	from tradehub_core.eca.safe_regex import RegexError, SafeRegex

	if not regex:
		return {"matched": False, "match_text": None, "error": "Pattern boş"}
	if not sample:
		return {"matched": False, "match_text": None, "error": "Test örneği boş"}

	flag_int = _parse_flags(flags)
	try:
		m = SafeRegex.search(regex, sample, flag_int)
		if m:
			return {"matched": True, "match_text": m.group(0), "error": None}
		return {"matched": False, "match_text": None, "error": None}
	except RegexError as e:
		return {"matched": False, "match_text": None, "error": str(e)}
	except re.error as e:
		return {"matched": False, "match_text": None, "error": f"Geçersiz regex: {str(e)[:100]}"}


@frappe.whitelist()
def get_canonical_fields() -> list[str]:
	"""Adaptive ingestion canonical fields listesi (UI dropdown için)."""
	from tradehub_core.bulk_import.ingestion.canonical_fields import get_all_targets

	return get_all_targets()

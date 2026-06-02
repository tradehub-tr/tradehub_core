"""Seller Template Profile — fingerprint-based mapping store."""

import hashlib
import json
import re

import frappe
from frappe.utils import now_datetime

PROFILE_CACHE_TTL = 3600  # 1 saat write-through cache
NEGATIVE_CACHE_TTL = 300  # 5 dakika negatif cache (yok kaydı)


def compute_fingerprint(headers: list[str], seller_profile: str, sheet_name: str | None = None) -> str:
	"""sha1(sorted_normalized_headers + seller_id) — sheet_name opsiyonel.

	Sheet_name dahil DEĞİL (kararımız: same headers different sheets = same profile).
	"""
	normalized = sorted(_normalize_header(h) for h in headers if h)
	payload = json.dumps({"headers": normalized, "seller": seller_profile}, sort_keys=True)
	return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _normalize_header(h: str) -> str:
	"""Lowercase, strip, collapse whitespace."""
	text = (h or "").lower().strip()
	text = re.sub(r"\s+", " ", text)
	return text


def lookup_profile(headers: list[str], seller_profile: str) -> dict | None:
	"""Profile'ı fingerprint ile ara. None dönerse yok demek.

	Returns: {"mapping": {field: header}, "normalizer_overrides": {...}, "profile_name": "..."}
	"""
	fp = compute_fingerprint(headers, seller_profile)
	cache_key = f"template_profile:{fp}"
	cached = frappe.cache.get_value(cache_key)
	if cached is not None:
		# Boş dict negatif cache demek
		return cached or None

	# DB lookup
	name = frappe.db.get_value(
		"Seller Template Profile",
		{"fingerprint": fp, "seller": seller_profile},
		"name",
	)
	if not name:
		# Cache negative result (short TTL)
		frappe.cache.set_value(cache_key, {}, expires_in_sec=NEGATIVE_CACHE_TTL)
		return None

	doc = frappe.get_doc("Seller Template Profile", name)
	result = {
		"profile_name": name,
		"mapping": json.loads(doc.mapping_json or "{}"),
		"normalizer_overrides": json.loads(doc.normalizer_overrides or "{}"),
	}
	frappe.cache.set_value(cache_key, result, expires_in_sec=PROFILE_CACHE_TTL)
	return result


def save_profile(
	headers: list[str],
	seller_profile: str,
	mapping: dict[str, str],
	source_format: str = "xlsx",
	sheet_name: str | None = None,
	normalizer_overrides: dict | None = None,
) -> str:
	"""Profile oluştur veya güncelle. Returns: profile name."""
	fp = compute_fingerprint(headers, seller_profile)
	existing = frappe.db.get_value(
		"Seller Template Profile",
		{"fingerprint": fp, "seller": seller_profile},
		"name",
	)
	if existing:
		doc = frappe.get_doc("Seller Template Profile", existing)
		doc.mapping_json = json.dumps(mapping)
		if normalizer_overrides is not None:
			doc.normalizer_overrides = json.dumps(normalizer_overrides)
		doc.hit_count = (doc.hit_count or 0) + 1
		doc.last_used = now_datetime()
		# ignore_permissions: sistem-yönlü bir import flow'u; user input olarak doğrulanmış mapping
		doc.save(ignore_permissions=True)
		_invalidate_cache(fp)
		return doc.name

	doc = frappe.new_doc("Seller Template Profile")
	doc.seller = seller_profile
	doc.fingerprint = fp
	doc.source_format = source_format
	doc.sheet_name = sheet_name or ""
	doc.mapping_json = json.dumps(mapping)
	doc.normalizer_overrides = json.dumps(normalizer_overrides or {})
	doc.hit_count = 1
	doc.last_used = now_datetime()
	# ignore_permissions: sistem-yönlü ilk kayıt
	doc.insert(ignore_permissions=True)
	_invalidate_cache(fp)
	return doc.name


def increment_hit_count(profile_name: str) -> None:
	"""Profile hit_count + last_used güncelle (cleanup için kritik)."""
	try:
		current = frappe.db.get_value("Seller Template Profile", profile_name, "hit_count") or 0
		frappe.db.set_value(
			"Seller Template Profile",
			profile_name,
			{
				"hit_count": current + 1,
				"last_used": now_datetime(),
			},
			update_modified=False,
		)
	except Exception as e:
		frappe.log_error(f"Profile hit_count update failed: {e}", "ingestion.profile_store")


def _invalidate_cache(fp: str) -> None:
	try:
		frappe.cache.delete_value(f"template_profile:{fp}")
	except Exception:
		# Cache invalidation hatası kritik değil — sonraki TTL'de düşecek
		pass

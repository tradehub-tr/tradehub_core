"""
Pagination yardımcıları — tüm API endpoint'lerinde tutarlı ve defansif sayfalama.

Daha önceki kodda `cint(page) or 1` kullanımı `page=-1` için 1'e fallback YAPMIYORDU
(çünkü -1 truthy). Sonuç: `start = (page-1)*page_size = negatif` → SQL OFFSET -N
→ MariaDB ProgrammingError 1064. Aynı şekilde `page_size=0` → ZeroDivisionError.

Bu helper'lar her iki uçtan da kelepçeler:
- page < 1 → 1
- page_size < 1 → default
- page_size > max → max

Kullanımı:
    page, page_size, start = normalize_pagination(page, page_size)
    # ...
    rows = frappe.get_all("DocType", limit_start=start, limit_page_length=page_size)
"""


def _safe_int(value, default):
	"""Tip-toleranslı int cast. None, '', non-numeric → default."""
	if value is None:
		return default
	try:
		return int(value)
	except (ValueError, TypeError):
		return default


def normalize_pagination(page, page_size, default_page_size=20, max_page_size=100):
	"""
	(page, page_size) tarzı pagination'ı güvenli aralığa kelepçeler.

	Returns: (page, page_size, start) — hepsi int, hepsi pozitif.
	"""
	page = max(_safe_int(page, 1), 1)
	page_size = _safe_int(page_size, default_page_size)
	if page_size < 1:
		page_size = default_page_size
	page_size = min(page_size, max_page_size)
	start = (page - 1) * page_size
	return page, page_size, start


def normalize_offset(limit_start, limit_page_length, default_length=20, max_length=100):
	"""
	(limit_start, limit_page_length) tarzı pagination'ı güvenli aralığa kelepçeler
	(rfq.py / Frappe-style). Negatif start veya 0/negatif length → kelepçele.

	Returns: (start, length) — hepsi int, start>=0, length>=1.
	"""
	start = max(_safe_int(limit_start, 0), 0)
	length = _safe_int(limit_page_length, default_length)
	if length < 1:
		length = default_length
	length = min(length, max_length)
	return start, length

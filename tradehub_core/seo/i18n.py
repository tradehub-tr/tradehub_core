"""
Multi-language helpers (Faz 7).

Pure fonksiyonlar:
  - parse_lang_from_path(path) → (lang, normalized_path)
  - get_field_with_fallback(record, field, lang) → str
  - localize_url(path, lang) → str (TR prefix'siz, EN /en/ prefix'li)
  - build_hreflang_links(canonical_tr_path, site_url) → list[dict]
  - slug_field_for(doctype, lang) → str (doctype + dil-bazlı slug field adı)

Frappe runtime'a bağımlı değil; standalone test edilebilir.
"""

SUPPORTED_LANGS = ("tr", "en")
DEFAULT_LANG = "tr"


def parse_lang_from_path(path: str) -> tuple[str, str]:
	"""Path'in başındaki dil prefix'ini ayır.

	`/en/urun/x` → ("en", "/urun/x")
	`/urun/x`    → ("tr", "/urun/x")
	`/tr/urun/x` → ("tr", "/urun/x")  # explicit tr prefix temizlenir
	`/en`        → ("en", "/")
	"""
	if not path:
		return DEFAULT_LANG, "/"
	if not path.startswith("/"):
		path = "/" + path

	for lang in SUPPORTED_LANGS:
		# `/en` veya `/en/...`
		if path == f"/{lang}":
			return lang, "/"
		prefix = f"/{lang}/"
		if path.startswith(prefix):
			remainder = "/" + path[len(prefix):]
			return lang, remainder

	return DEFAULT_LANG, path


def get_field_with_fallback(record: dict, field: str, lang: str) -> str:
	"""lang=en → record[field+'_en'] varsa o, yoksa record[field] (TR fallback).

	`url_slug` özel durum: lang=en → record['url_slug_en'] denenir.
	"""
	if not record or not field:
		return ""
	if lang == DEFAULT_LANG:
		return record.get(field, "") or ""
	en_field = f"{field}_en"
	en_value = record.get(en_field) or ""
	if en_value:
		return en_value
	return record.get(field, "") or ""


def localize_url(path: str, lang: str) -> str:
	"""TR prefix'siz, EN için `/en/` prefix ekle.

	`/urun/x` + tr → `/urun/x`
	`/urun/x` + en → `/en/urun/x`
	`/` + en → `/en/`
	"""
	if not path:
		path = "/"
	if not path.startswith("/"):
		path = "/" + path
	if lang == DEFAULT_LANG:
		return path
	if lang not in SUPPORTED_LANGS:
		return path
	# Halihazırda dil prefix'liyse tekrar ekleme
	if path.startswith(f"/{lang}/") or path == f"/{lang}":
		return path
	if path == "/":
		return f"/{lang}/"
	return f"/{lang}{path}"


def build_hreflang_links(canonical_tr_path: str, site_url: str) -> list[dict]:
	"""Tüm dil alternate link'leri + x-default.

	`canonical_tr_path` her zaman TR (prefix'siz) path olarak verilir.
	Returns: [
	  {"hreflang": "tr", "href": "https://istoc.com/urun/x"},
	  {"hreflang": "en", "href": "https://istoc.com/en/urun/x"},
	  {"hreflang": "x-default", "href": "https://istoc.com/urun/x"},
	]
	"""
	site = site_url.rstrip("/")
	links = []
	for lang in SUPPORTED_LANGS:
		links.append({
			"hreflang": lang,
			"href": f"{site}{localize_url(canonical_tr_path, lang)}",
		})
	# x-default → TR (default dil)
	links.append({
		"hreflang": "x-default",
		"href": f"{site}{canonical_tr_path}",
	})
	return links


def slug_field_for(doctype: str, lang: str) -> str:
	"""Doctype + dil-bazlı slug field adı.

	Product Category: tr → 'url_slug', en → 'url_slug_en'
	Listing/Brand/Admin Seller Profile: tr → 'slug', en → 'slug_en'
	"""
	base = "url_slug" if doctype == "Product Category" else "slug"
	if lang == DEFAULT_LANG:
		return base
	return f"{base}_en"

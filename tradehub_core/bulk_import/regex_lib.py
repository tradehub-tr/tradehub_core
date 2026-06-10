"""Regex Pattern Library resolver — System + Seller Override katmanları."""

import re

import frappe
from frappe import _

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


# ── Sütun Eşleştirmelerim — satıcı literal alternatiflerden güvenli regex ─────


def _build_safe_alias_regex(headers: list[str]) -> str:
	"""Literal başlık alternatiflerinden ReDoS'a düşmeyen güvenli regex üret.

	Her alternatif re.escape() ile kaçırılır, boşluklar `\\s+`'e dönüşür, kelime
	sınırları (`\\b...\\b`) eklenir ve OR ile birleştirilir: `(?:alt1|alt2)`.
	Üretilen desen SafeRegex._validate'i geçer (sabit, backtracking-güvenli).

	Örnek: ["renk", "color", "renk seçeneği"] -> r"\\b(?:renk|color|renk\\s+seçeneği)\\b"
	"""
	parts = []
	seen = set()
	for raw in headers:
		token = (raw or "").strip().lower()
		if not token or token in seen:
			continue
		seen.add(token)
		# Önce escape, sonra kaçırılmış boşlukları esnek boşluğa çevir.
		escaped = re.escape(token).replace("\\ ", r"\s+")
		parts.append(escaped)
	if not parts:
		frappe.throw(_("En az bir geçerli başlık gerekli"))
	return r"\b(?:" + "|".join(parts) + r")\b"


def _current_seller_profile() -> str:
	from tradehub_core.utils.tenant import _get_seller_profile_for_user

	profile = _get_seller_profile_for_user(frappe.session.user)
	if not profile:
		frappe.throw(_("Satıcı profili bulunamadı"))
	return profile


@frappe.whitelist()
def save_column_alias(my_header: str, target_field: str, alternatives: str = "") -> dict:
	"""Satıcı sütun eşleştirmesi — literal'lerden güvenli regex üretip kaydet.

	Satıcı regex GÖRMEZ; "benim başlığım" + virgülle "alternatif yazımlar" girer.
	Backend re.escape + OR ile SafeRegex-uyumlu desen üretir ve Seller Override
	"Regex Pattern Library" kaydı (pattern_category="Column Header") oluşturur.

	Args:
	    my_header: Satıcının Excel başlığı (örn. "Renk Seçeneği").
	    target_field: Eşlenecek canonical alan (örn. "variant_axis_1_type").
	    alternatives: Virgülle ayrılmış ek yazımlar (örn. "renk, color").

	Returns:
	    {"ok": True, "name": <pattern name>, "regex": <üretilen>, "target_field": ...}
	"""
	from tradehub_core.eca.safe_regex import RegexError, SafeRegex

	my_header = (my_header or "").strip()
	target_field = (target_field or "").strip()
	if not my_header:
		frappe.throw(_("Başlık zorunlu"))
	if not target_field:
		frappe.throw(_("Hedef alan zorunlu"))

	headers = [my_header] + [a for a in (alternatives or "").split(",")]
	regex = _build_safe_alias_regex(headers)

	# Üretilen deseni doğrula — catastrophic backtracking koruması.
	try:
		SafeRegex.search(regex, my_header.lower(), SafeRegex.IGNORECASE | SafeRegex.UNICODE)
	except RegexError as e:
		frappe.throw(_("Desen güvenli değil: {0}").format(str(e)))

	seller = _current_seller_profile()

	doc = frappe.new_doc("Regex Pattern Library")
	doc.pattern_name = f"{seller} — {my_header} → {target_field}"
	doc.enabled = 1
	doc.target_field = target_field
	doc.target_doctype = "Listing"
	doc.pattern_category = "Column Header"
	doc.scope = "Seller Override"
	doc.seller_profile = seller
	doc.priority = 50
	doc.append(
		"patterns",
		{
			"regex": regex,
			"flags": "IGNORECASE,UNICODE",
			"enabled": 1,
			"description": _("Satıcı sütun eşleştirmesi: {0}").format(my_header),
		},
	)
	doc.insert()

	return {"ok": True, "name": doc.name, "regex": regex, "target_field": target_field}


@frappe.whitelist()
def list_column_aliases() -> list[dict]:
	"""Satıcının kendi sütun eşleştirmelerini listele (regex gizli)."""
	seller = _current_seller_profile()
	rows = frappe.get_list(
		"Regex Pattern Library",
		filters={
			"scope": "Seller Override",
			"seller_profile": seller,
			"pattern_category": "Column Header",
		},
		fields=["name", "pattern_name", "target_field", "enabled"],
		order_by="modified desc",
	)
	return rows


@frappe.whitelist()
def delete_column_alias(name: str) -> dict:
	"""Satıcının kendi sütun eşleştirmesini sil (sahiplik doğrulanır)."""
	seller = _current_seller_profile()
	owner = frappe.db.get_value("Regex Pattern Library", name, "seller_profile")
	if owner != seller:
		frappe.throw(_("Bu eşleştirmeyi silme yetkiniz yok"))
	frappe.delete_doc("Regex Pattern Library", name)
	return {"ok": True, "name": name}


# ── Değer Eşleştirmelerim — hücre-değeri normalizasyonu (ayrı katman) ─────────


@frappe.whitelist()
def save_value_mapping(target_field: str, rows_json: str) -> dict:
	"""Satıcı değer eşleştirmesi kaydet (upsert — alan başına tek kayıt).

	"Sütun Eşleştirmelerim" kolon-ADI'nı çevirir; bu AYRI katman hücre-DEĞERİNİ
	çevirir. Satıcı "[alan] gelen [X] → hedef [Y]" satırları girer; regex YOK.

	Args:
	    target_field: Eşleştirmenin uygulanacağı canonical alan (örn. "condition",
	        "brand", "attr:beden").
	    rows_json: JSON liste — [{"source_value": "Large", "target_value": "XL"}, ...]

	Returns:
	    {"ok": True, "name": <name>, "target_field": ..., "row_count": int}
	"""
	import json

	target_field = (target_field or "").strip()
	if not target_field:
		frappe.throw(_("Hedef alan zorunlu"))

	try:
		rows = json.loads(rows_json or "[]")
	except (ValueError, TypeError):
		frappe.throw(_("Geçersiz satır verisi"))
	if not isinstance(rows, list):
		frappe.throw(_("Satır verisi liste olmalı"))

	seller = _current_seller_profile()

	existing = frappe.db.get_value(
		"Seller Value Mapping",
		{"seller_profile": seller, "target_field": target_field},
		"name",
	)
	if existing:
		doc = frappe.get_doc("Seller Value Mapping", existing)
		doc.set("rows", [])
	else:
		doc = frappe.new_doc("Seller Value Mapping")
		doc.seller_profile = seller
		doc.target_field = target_field
		doc.enabled = 1

	for r in rows:
		if not isinstance(r, dict):
			continue
		src = str(r.get("source_value") or "").strip()
		tgt = str(r.get("target_value") or "").strip()
		if not src or not tgt:
			continue
		doc.append(
			"rows",
			{
				"source_value": src,
				"target_value": tgt,
				"enabled": 1 if r.get("enabled", 1) else 0,
			},
		)

	doc.save()
	return {
		"ok": True,
		"name": doc.name,
		"target_field": target_field,
		"row_count": len(doc.rows or []),
	}


@frappe.whitelist()
def list_value_mappings() -> list[dict]:
	"""Satıcının kendi değer eşleştirmelerini satırlarıyla listele."""
	seller = _current_seller_profile()
	mappings = frappe.get_list(
		"Seller Value Mapping",
		filters={"seller_profile": seller},
		fields=["name", "target_field", "enabled"],
		order_by="modified desc",
	)
	result: list[dict] = []
	for m in mappings:
		doc = frappe.get_doc("Seller Value Mapping", m["name"])
		result.append(
			{
				"name": doc.name,
				"target_field": doc.target_field,
				"enabled": doc.enabled,
				"rows": [
					{
						"source_value": row.source_value,
						"target_value": row.target_value,
						"enabled": row.enabled,
					}
					for row in (doc.rows or [])
				],
			}
		)
	return result


@frappe.whitelist()
def delete_value_mapping(name: str) -> dict:
	"""Satıcının kendi değer eşleştirmesini sil (sahiplik doğrulanır)."""
	seller = _current_seller_profile()
	owner = frappe.db.get_value("Seller Value Mapping", name, "seller_profile")
	if owner != seller:
		frappe.throw(_("Bu eşleştirmeyi silme yetkiniz yok"))
	frappe.delete_doc("Seller Value Mapping", name)
	return {"ok": True, "name": name}


@frappe.whitelist()
def get_field_values(target_field: str) -> dict:
	"""Bir hedef alanın geçerli değerlerini döndür (hedef-değer dropdown'u için).

	Kaynak:
	- Select (örn. condition): Listing field JSON `options` newline-ayraçlı.
	- Link (brand/category/stock_uom/Country vb.): _LINK_FIELDS → get_all.
	- attr:<code>: Product Attribute value_options child tablosu.
	- Aksi: serbest metin (free) — dropdown yerine elle giriş.

	Returns:
	    {"kind": "select|link|attr|free", "values": [{value, label}], "free": bool}
	"""
	from tradehub_core.bulk_import import persister

	target_field = (target_field or "").strip()
	if not target_field:
		return {"kind": "free", "values": [], "free": True}

	if target_field.startswith("attr:"):
		return _attribute_field_values(target_field[len("attr:") :].strip())

	if target_field in persister._LINK_FIELDS:
		return _link_field_values(persister._LINK_FIELDS[target_field])

	select_vals = _select_field_values(target_field)
	if select_vals is not None:
		return select_vals

	return {"kind": "free", "values": [], "free": True}


def _select_field_values(fieldname: str) -> dict | None:
	"""Listing Select field options → değer listesi (yoksa None)."""
	try:
		field = frappe.get_meta("Listing").get_field(fieldname)
	except Exception:
		return None
	if not field or field.fieldtype != "Select":
		return None
	# currency Select'i `options:"currency"` ile Currency listesini referanslar.
	if (field.options or "").strip() == "currency":
		rows = frappe.get_all("Currency", filters={"enabled": 1}, fields=["name"], order_by="name asc")
		return {
			"kind": "select",
			"values": [{"value": r["name"], "label": r["name"]} for r in rows],
			"free": False,
		}
	options = [o.strip() for o in (field.options or "").split("\n") if o.strip()]
	return {
		"kind": "select",
		"values": [{"value": o, "label": o} for o in options],
		"free": False,
	}


def _link_field_values(doctype: str) -> dict:
	"""Link DocType kayıtları → değer listesi. Country/UOM ~200 seed olabilir."""
	label_field = f"{doctype.lower().replace(' ', '_')}_name"
	meta = frappe.get_meta(doctype)
	fields = ["name"]
	if meta.get_field(label_field):
		fields.append(label_field)
	rows = frappe.get_all(doctype, fields=fields, order_by="name asc", limit_page_length=0)
	values = []
	for r in rows:
		label = r.get(label_field) if len(fields) > 1 else None
		values.append({"value": r["name"], "label": label or r["name"]})
	return {"kind": "link", "values": values, "free": False}


def _attribute_field_values(code: str) -> dict:
	"""Product Attribute value_options → değer listesi.

	data_type Select/Multi-Select/Color değilse (value_options boş) serbest metin.
	"""
	if not code or not frappe.db.exists("Product Attribute", code):
		return {"kind": "attr", "values": [], "free": True}
	doc = frappe.get_doc("Product Attribute", code)
	values = []
	for opt in doc.value_options or []:
		val = (opt.option_value or "").strip()
		if not val:
			continue
		values.append({"value": val, "label": (opt.option_label or val).strip()})
	# Select tipi olmayan attribute'lar serbest metin hedef-değeri alır.
	free = len(values) == 0
	return {"kind": "attr", "values": values, "free": free}

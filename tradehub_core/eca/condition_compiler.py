# Copyright (c) 2026, TradeHub Team and contributors

"""ECA condition builder -> Python ifadesi derleyici.

Builder JSON yapısını (frontend görsel kural editörü) dispatcher'ın
frappe.safe_eval ile çalıştırdığı güvenli Python ifadesine çevirir.

Motor DEĞİŞMEZ — bu modül sadece condition string'i ÜRETİR. Üretilen
ifade `doc` dict context'inde (bkz. dispatcher._evaluate_condition_v2)
çalışacak şekilde `doc.get('field')` erişimi kullanır.

Builder şeması (dict):
    {
        "match": "all" | "any",
        "conditions": [
            {"field": "base_price", "op": "gt", "value": 1000},
            ...
        ],
        "groups": [
            {"match": "any", "conditions": [...], "groups": [...]},
            ...
        ]
    }

Güvenlik:
    - field SADECE whitelist'ten olabilir (Listing güvenli alanları).
    - value literal olarak güvenli serialize edilir (repr — string/sayı/bool).
    - Bilinmeyen operatör / alan / tip reddedilir (CompileError).
"""

from tradehub_core.eca.validators import (
	LISTING_SELLER_VISIBLE_FIELDS,
)

# Listing için admin'in de görebileceği ek alanlar (builder seçilebilir alan kümesi).
# Seller görünürlüğü dispatcher.filter_doc_for_seller ile runtime'da ayrıca kısıtlanır;
# burada amaç builder'da seçilebilecek tüm güvenli Listing alanlarını tanımlamak.
LISTING_BUILDER_FIELDS = frozenset(
	LISTING_SELLER_VISIBLE_FIELDS
	| {
		"selling_price",
		"discount_percentage",
		"min_order_qty",
		"max_order_qty",
		"shipping_weight",
		"condition",
		"listing_type",
		"package_type",
		"category",
		"product_type",
		"currency",
		"ships_from_country",
		"stock_uom",
		"listing_code",
		"barcode",
		"b2b_enabled",
		"is_featured",
		"is_visible",
		"track_inventory",
		"allow_backorders",
	}
)

# reference_doctype -> izinli alan kümesi. Yeni doctype eklenince genişletilir.
ALLOWED_FIELDS_BY_DOCTYPE = {
	"Listing": LISTING_BUILDER_FIELDS,
}

# Builder operatörü -> üretim stratejisi.
# Karşılaştırma operatörleri doğrudan Python operatörü.
_COMPARISON_OPS = {
	"gt": ">",
	"lt": "<",
	"gte": ">=",
	"lte": "<=",
	"eq": "==",
	"neq": "!=",
}
# Özel operatörler (membership / truthy).
_SPECIAL_OPS = frozenset({"contains", "not_contains", "in_list", "not_in_list", "is_set", "is_empty"})

_MATCH_JOINER = {"all": " and ", "any": " or "}

# describe_condition için Türkçe operatör etiketleri.
_OP_LABELS_TR = {
	"gt": "büyüktür",
	"lt": "küçüktür",
	"gte": "büyük eşittir",
	"lte": "küçük eşittir",
	"eq": "eşittir",
	"neq": "eşit değildir",
	"contains": "içerir",
	"not_contains": "içermez",
	"in_list": "şunlardan biri",
	"not_in_list": "şunlardan biri değil",
	"is_set": "dolu",
	"is_empty": "boş",
}
_MATCH_LABELS_TR = {"all": "TÜMÜ doğruysa", "any": "HERHANGİ BİRİ doğruysa"}


class CompileError(Exception):
	"""Builder JSON güvenli Python ifadesine derlenemediğinde."""


def _allowed_fields(doctype: str) -> frozenset:
	fields = ALLOWED_FIELDS_BY_DOCTYPE.get(doctype)
	if fields is None:
		raise CompileError(f"Desteklenmeyen referans doctype: {doctype}")
	return fields


def _check_field(field, doctype: str) -> str:
	if not isinstance(field, str) or not field:
		raise CompileError("Alan adı boş olamaz")
	if field not in _allowed_fields(doctype):
		raise CompileError(f"İzin verilmeyen alan: {field}")
	return field


def _serialize_value(value):
	"""Değeri güvenli Python literal'e çevir (repr — string/sayı/bool/None)."""
	if isinstance(value, bool):
		return repr(value)  # True / False
	if isinstance(value, int | float):
		return repr(value)
	if value is None:
		return "None"
	if isinstance(value, str):
		return repr(value)  # tek tırnaklı güvenli string literal
	raise CompileError(f"Desteklenmeyen değer tipi: {type(value).__name__}")


def _serialize_list(value):
	"""in_list operatörü için liste literal üret."""
	if not isinstance(value, list | tuple):
		raise CompileError("Liste operatörü için value bir dizi olmalı")
	items = ", ".join(_serialize_value(v) for v in value)
	return f"[{items}]"


def _compile_leaf(cond: dict, doctype: str) -> str:
	if not isinstance(cond, dict):
		raise CompileError("Koşul bir nesne olmalı")
	field = _check_field(cond.get("field"), doctype)
	op = cond.get("op")
	value = cond.get("value")
	accessor = f"doc.get({field!r})"

	if op in _COMPARISON_OPS:
		return f"({accessor} {_COMPARISON_OPS[op]} {_serialize_value(value)})"
	if op == "contains":
		return f"({_serialize_value(value)} in ({accessor} or ''))"
	if op == "not_contains":
		return f"({_serialize_value(value)} not in ({accessor} or ''))"
	if op == "in_list":
		return f"({accessor} in {_serialize_list(value)})"
	if op == "not_in_list":
		return f"({accessor} not in {_serialize_list(value)})"
	if op == "is_set":
		return f"(bool({accessor}))"
	if op == "is_empty":
		return f"(not {accessor})"
	raise CompileError(f"Bilinmeyen operatör: {op}")


def _compile_group(group: dict, doctype: str) -> str:
	if not isinstance(group, dict):
		raise CompileError("Grup bir nesne olmalı")
	match = group.get("match", "all")
	if match not in _MATCH_JOINER:
		raise CompileError(f"Geçersiz match değeri: {match}")

	parts = []
	for cond in group.get("conditions") or []:
		parts.append(_compile_leaf(cond, doctype))
	for sub in group.get("groups") or []:
		parts.append(_compile_group(sub, doctype))

	if not parts:
		raise CompileError("Grup en az bir koşul içermeli")
	if len(parts) == 1:
		return parts[0]
	return "(" + _MATCH_JOINER[match].join(parts) + ")"


def compile_condition(builder_json: dict, doctype: str = "Listing") -> str:
	"""Builder JSON'u dispatcher safe_eval'in kabul ettiği Python ifadesine derle.

	Örnek çıktı: (doc.get('base_price') > 1000) and (doc.get('brand') == 'Petkim')
	"""
	if not isinstance(builder_json, dict):
		raise CompileError("Builder JSON bir nesne olmalı")
	return _compile_group(builder_json, doctype)


def _describe_value(op: str, value) -> str:
	if op in ("is_set", "is_empty"):
		return ""
	if op in ("in_list", "not_in_list") and isinstance(value, list | tuple):
		return " [" + ", ".join(str(v) for v in value) + "]"
	return f" {value!r}"


def _describe_group(group: dict, doctype: str, depth: int = 0) -> str:
	match = group.get("match", "all")
	lines = []
	for cond in group.get("conditions") or []:
		field = cond.get("field", "?")
		op = cond.get("op", "?")
		label = _OP_LABELS_TR.get(op, op)
		lines.append(f"{field} {label}{_describe_value(op, cond.get('value'))}")
	for sub in group.get("groups") or []:
		lines.append("(" + _describe_group(sub, doctype, depth + 1) + ")")

	joiner = " VE " if match == "all" else " VEYA "
	return joiner.join(lines)


def describe_condition(builder_json: dict, doctype: str = "Listing") -> str:
	"""Builder JSON'dan düz Türkçe önizleme cümlesi üret (UI önizleme)."""
	if not isinstance(builder_json, dict):
		return ""
	conditions = builder_json.get("conditions") or []
	groups = builder_json.get("groups") or []
	if not conditions and not groups:
		return ""
	match = builder_json.get("match", "all")
	prefix = _MATCH_LABELS_TR.get(match, "")
	body = _describe_group(builder_json, doctype)
	return f"{prefix}: {body}" if prefix else body

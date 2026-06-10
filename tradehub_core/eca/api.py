"""ECA Rule yönetim API endpoint'leri — frontend tüketir.

Yöntemler:
- test_rule_with_sample: condition'ı sandbox'ta dene (sample doc dict ile)
- get_rule_log: ECA Rule Log audit kayıtlarını listele (filtre destekli)
- get_my_rules: oturum açan satıcının kendi Per-Seller kurallarını döner
- get_rule_schema: Kural sihirbazı için dinamik alan + eylem şeması (cascade kaynağı)
- count_matching: Bir koşula uyan Listing sayısı (tenant-scoped canlı önizleme)
- save_wizard_rule: Sihirbaz çıktısını mevcut ECA Rule + Action Template'e derler
"""

import frappe
from frappe import _

# Tip -> izinli operatör listesi. condition_compiler._COMPARISON_OPS / _SPECIAL_OPS
# ile uyumlu; sihirbaz cascade'inin kalbi (alan tipi operatör menüsünü belirler).
_TYPE_OPERATORS: dict[str, list[str]] = {
	"number": ["gt", "lt", "gte", "lte", "eq", "neq"],
	"text": ["eq", "neq", "contains", "not_contains", "is_set", "is_empty"],
	"select": ["eq", "neq", "in_list", "not_in_list"],
	"link": ["eq", "neq", "in_list", "not_in_list"],
	"boolean": ["eq"],
}

# Operatör -> frappe.get_list filtre operatörü (count_matching için).
# in_list/not_in_list/is_set/is_empty özel olarak ele alınır.
_FILTER_OPS: dict[str, str] = {
	"gt": ">",
	"lt": "<",
	"gte": ">=",
	"lte": "<=",
	"eq": "=",
	"neq": "!=",
}

# Sihirbaz alan tanımları (Listing). value_source frontend değer girişini belirler.
# Sözleşme: docs/PLAN-kurallar-pattern-schema.md §1.3 — çekirdek + brand/category/
# product_type/status; attr:* HARİÇ (V1). condition_compiler.LISTING_BUILDER_FIELDS
# whitelist'i DEĞİŞTİRİLMEZ; bu liste onun expose edilen alt kümesidir.
_RULE_FIELDS: tuple[dict, ...] = (
	{"key": "base_price", "label": "Birim Fiyat", "type": "number"},
	{"key": "selling_price", "label": "Satış Fiyatı", "type": "number"},
	{"key": "discount_percentage", "label": "İndirim %", "type": "number"},
	{"key": "stock_qty", "label": "Stok", "type": "number"},
	{"key": "min_order_qty", "label": "Min. Sipariş", "type": "number"},
	{"key": "max_order_qty", "label": "Maks. Sipariş", "type": "number"},
	{"key": "weight", "label": "Ağırlık", "type": "number"},
	{"key": "shipping_weight", "label": "Kargo Ağırlığı", "type": "number"},
	{"key": "title", "label": "Ürün Adı", "type": "text"},
	{"key": "sku", "label": "Stok Kodu (SKU)", "type": "text"},
	{"key": "barcode", "label": "Barkod", "type": "text"},
	{"key": "short_description", "label": "Kısa Açıklama", "type": "text"},
	{"key": "tags", "label": "Etiketler", "type": "text"},
	{"key": "status", "label": "Durum", "type": "select", "_enum_field": "status"},
	{"key": "condition", "label": "Ürün Durumu", "type": "select", "_enum_field": "condition"},
	{"key": "currency", "label": "Para Birimi", "type": "select", "_enum_field": "currency"},
	{"key": "brand", "label": "Marka", "type": "link", "_doctype": "Brand"},
	{"key": "product_category", "label": "Kategori", "type": "link", "_doctype": "Product Category"},
	{"key": "product_type", "label": "Ürün Tipi", "type": "link", "_doctype": "Product Type"},
	{"key": "b2b_enabled", "label": "B2B Açık", "type": "boolean"},
	{"key": "is_featured", "label": "Öne Çıkan", "type": "boolean"},
	{"key": "track_inventory", "label": "Stok Takibi", "type": "boolean"},
	{"key": "allow_backorders", "label": "Ön Sipariş İzni", "type": "boolean"},
)

# Satıcı eylemleri (5). webhook YOK — admin'de kalır (sözleşme §2 / KARAR b).
_SELLER_ACTIONS: tuple[dict, ...] = (
	{
		"key": "discount_price",
		"label": "Satış fiyatını azalt",
		"params": [{"key": "percent", "type": "number", "label": "Oran (%)"}],
	},
	{
		"key": "markup_price",
		"label": "Satış fiyatını artır",
		"params": [{"key": "percent", "type": "number", "label": "Oran (%)"}],
	},
	{
		"key": "set_field",
		"label": "Bir alanı doldur/değiştir",
		"params": [
			{"key": "field", "type": "writable_field", "label": "Alan"},
			{"key": "value", "type": "text", "label": "Değer"},
		],
	},
	{
		"key": "email",
		"label": "Bana e-posta gönder",
		"params": [{"key": "note", "type": "text", "label": "Not (opsiyonel)", "optional": True}],
	},
	{"key": "reject_row", "label": "Bu satırı reddet (yüklemede)", "params": []},
)

# Admin'e ek (webhook). Satıcı şemasında görünmez.
_ADMIN_EXTRA_ACTIONS: tuple[dict, ...] = (
	{
		"key": "webhook",
		"label": "Dış sisteme bildir (webhook)",
		"params": [{"key": "url", "type": "text", "label": "URL"}],
	},
)


@frappe.whitelist()
def test_rule_with_sample(condition: str, sample_doc_json: str = "{}", owner_role: str = "Seller") -> dict:
	"""Bir ECA condition'ı örnek doc dict'i ile sandbox'ta dene.

	Args:
		condition: Python ifadesi (frappe.safe_eval ile çalıştırılır)
		sample_doc_json: Örnek doc JSON (string formatında)
		owner_role: "Seller" | "System Manager" | "Marketplace Admin"

	Returns:
		{"result": bool, "error": str | None}
	"""
	import json

	from tradehub_core.eca.safe_regex import RegexError, SafeRegex
	from tradehub_core.eca.validators import filter_doc_for_seller

	if not condition or not condition.strip():
		return {"result": True, "error": None}

	try:
		sample = json.loads(sample_doc_json) if sample_doc_json else {}
	except json.JSONDecodeError:
		return {"result": False, "error": "Örnek doc JSON parse edilemedi"}

	if not isinstance(sample, dict):
		return {"result": False, "error": "Örnek doc bir JSON nesnesi olmalı"}

	if owner_role == "Seller":
		sample = filter_doc_for_seller(sample, doctype="Listing")

	context = {
		"doc": sample,
		"re": SafeRegex,
		"frappe": {
			"utils": {
				"cint": frappe.utils.cint,
				"flt": frappe.utils.flt,
				"getdate": frappe.utils.getdate,
				"now_datetime": frappe.utils.now_datetime,
			},
			"session": {"user": frappe.session.user},
		},
		"cint": frappe.utils.cint,
		"flt": frappe.utils.flt,
		"True": True,
		"False": False,
		"None": None,
	}

	try:
		result = bool(frappe.safe_eval(condition, context))
		return {"result": result, "error": None}
	except RegexError as e:
		return {"result": False, "error": f"Regex hatası: {e}"}
	except Exception as e:
		return {"result": False, "error": str(e)[:200]}


@frappe.whitelist()
def compile_preview(builder_json: str, reference_doctype: str = "Listing") -> dict:
	"""Builder JSON'u Python ifadesine derle + Türkçe önizleme cümlesi döner.

	Frontend canlı önizleme için kullanır.

	Args:
		builder_json: Görsel kural editörü JSON (string)
		reference_doctype: Alan whitelist'i için referans doctype

	Returns:
		{"python": str, "sentence": str, "error": str | None}
	"""
	import json

	from tradehub_core.eca.condition_compiler import (
		CompileError,
		compile_condition,
		describe_condition,
	)

	if not builder_json or not builder_json.strip():
		return {"python": "", "sentence": "", "error": None}

	try:
		builder = json.loads(builder_json)
	except json.JSONDecodeError:
		return {"python": "", "sentence": "", "error": "Builder JSON parse edilemedi"}

	try:
		python = compile_condition(builder, doctype=reference_doctype)
		sentence = describe_condition(builder, doctype=reference_doctype)
		return {"python": python, "sentence": sentence, "error": None}
	except CompileError as e:
		return {"python": "", "sentence": "", "error": str(e)}


@frappe.whitelist()
def get_rule_log(
	eca_rule: str = None, status: str = None, doctype_filter: str = None, limit: int = 100
) -> list:
	"""ECA Rule Log audit kayıtları — yetki filtresine göre.

	Args:
		eca_rule: Filtre — belirli kural adı
		status: Filtre — Success / Error / Condition False
		doctype_filter: Filtre — reference_doctype (örn. "Listing")
		limit: Maksimum kayıt sayısı (default 100)
	"""
	filters = {}
	if eca_rule:
		filters["eca_rule"] = eca_rule
	if status:
		filters["status"] = status
	if doctype_filter:
		filters["reference_doctype"] = doctype_filter

	try:
		limit_int = int(limit)
	except (TypeError, ValueError):
		limit_int = 100
	if limit_int > 500:
		limit_int = 500

	return frappe.get_list(
		"ECA Rule Log",
		filters=filters,
		fields=[
			"name",
			"eca_rule",
			"reference_doctype",
			"reference_name",
			"event",
			"execution_phase",
			"condition_result",
			"action_executed",
			"status",
			"execution_time_ms",
			"error_message",
			"bulk_import_job",
			"triggered_at",
		],
		order_by="triggered_at desc",
		limit=limit_int,
	)


@frappe.whitelist()
def get_my_rules() -> list:
	"""Satıcının kendi ECA Rule'larını döner (Per-Seller scope)."""
	seller = frappe.db.get_value(
		"Admin Seller Profile",
		{"owner": frappe.session.user},
		"name",
	)
	if not seller:
		return []
	return frappe.get_list(
		"ECA Rule",
		filters={"rule_scope": "Per-Seller", "seller_profile": seller},
		fields=[
			"name",
			"rule_name",
			"enabled",
			"reference_doctype",
			"event",
			"priority",
			"action_type",
			"last_fired_at",
			"total_fired_count",
		],
		order_by="priority asc",
	)


# ── Sihirbaz şeması (dinamik cascade kaynağı) ─────────────────────────────────


def _is_admin_caller() -> bool:
	roles = set(frappe.get_roles(frappe.session.user))
	return bool(roles & {"System Manager", "Marketplace Admin"})


def _enum_options(fieldname: str) -> list[str]:
	"""Listing Select alanının seçeneklerini DocType meta'sından çek."""
	try:
		meta = frappe.get_meta("Listing")
		df = meta.get_field(fieldname)
	except Exception:
		return []
	if not df or df.fieldtype != "Select" or not df.options:
		return []
	return [opt.strip() for opt in df.options.split("\n") if opt.strip()]


def _build_value_source(field: dict) -> dict:
	ftype = field["type"]
	if ftype == "number":
		return {"kind": "number"}
	if ftype == "text":
		return {"kind": "text"}
	if ftype == "boolean":
		return {"kind": "bool"}
	if ftype == "select":
		return {"kind": "enum", "options": _enum_options(field["_enum_field"])}
	if ftype == "link":
		return {"kind": "doctype", "doctype": field["_doctype"]}
	return {"kind": "text"}


@frappe.whitelist()
def get_rule_schema() -> dict:
	"""Kural sihirbazı için alan + eylem şeması (dinamik cascade kaynağı).

	Frontend hiçbir alan/operatör/eylem hardcode etmez; bu şemadan üretir.
	`fields[].type` operatör listesini ve değer girişini belirler. `actions`
	satıcıya 5 eylem; admin caller'da webhook eklenir.

	Returns:
	    {"fields": [{key, label, type, operators, value_source}],
	     "actions": [{key, label, params}],
	     "writable_fields": [{key, label}]}
	"""
	from tradehub_core.eca.validators import LISTING_SELLER_WRITABLE_FIELDS

	fields = []
	for f in _RULE_FIELDS:
		fields.append(
			{
				"key": f["key"],
				"label": f["label"],
				"type": f["type"],
				"operators": _TYPE_OPERATORS[f["type"]],
				"value_source": _build_value_source(f),
			}
		)

	actions = list(_SELLER_ACTIONS)
	if _is_admin_caller():
		actions = actions + list(_ADMIN_EXTRA_ACTIONS)

	# set_field hedefleri = satıcı yazılabilir whitelist (etiketler _RULE_FIELDS'ten).
	labels = {f["key"]: f["label"] for f in _RULE_FIELDS}
	writable = [{"key": k, "label": labels.get(k, k)} for k in sorted(LISTING_SELLER_WRITABLE_FIELDS)]

	return {"fields": fields, "actions": actions, "writable_fields": writable}


# ── Canlı önizleme sayacı (tenant-scoped) ─────────────────────────────────────


def _leaf_to_filter(cond: dict) -> tuple | None:
	"""Builder leaf'ini frappe.get_list filtre tuple'ına çevir.

	get_list permission_query_conditions'ı otomatik uygular (satıcı scope GARANTİ).
	Bilinmeyen alan/operatör atlanır (güvenlik: sadece şemadaki alanlar).
	"""
	field = cond.get("field")
	op = cond.get("op")
	value = cond.get("value")
	allowed = {f["key"] for f in _RULE_FIELDS}
	if field not in allowed:
		return None
	if op in _FILTER_OPS:
		return (field, _FILTER_OPS[op], value)
	if op == "contains":
		return (field, "like", f"%{value}%")
	if op == "not_contains":
		return (field, "not like", f"%{value}%")
	if op == "in_list":
		return (field, "in", value if isinstance(value, list) else [value])
	if op == "not_in_list":
		return (field, "not in", value if isinstance(value, list) else [value])
	if op == "is_set":
		return (field, "is", "set")
	if op == "is_empty":
		return (field, "is", "not set")
	return None


def _collect_filters(group: dict) -> list:
	"""Grup ağacından düz filtre listesi topla (tek seviye AND/OR varsayımı)."""
	filters = []
	for cond in group.get("conditions") or []:
		f = _leaf_to_filter(cond)
		if f:
			filters.append(f)
	for sub in group.get("groups") or []:
		filters.extend(_collect_filters(sub))
	return filters


@frappe.whitelist()
def count_matching(reference_doctype: str, condition_builder_json: str) -> dict:
	"""Bir koşula uyan kayıt sayısı + toplam (tenant-scoped canlı önizleme).

	frappe.get_list permission_query_conditions üzerinden satıcı scope'unu
	otomatik uygular — satıcı yalnızca kendi Listing'lerini sayar.

	Args:
	    reference_doctype: Şu an yalnızca "Listing".
	    condition_builder_json: ConditionBuilder JSON (string).

	Returns:
	    {"count": int, "total": int, "error": str | None}
	"""
	import json

	if reference_doctype != "Listing":
		return {"count": 0, "total": 0, "error": _("Desteklenmeyen modül")}

	# Satıcının kendi Listing'leri — açık seller_profile filtresiyle scope'la.
	# get_list rol-seviye doctype iznine takılıyordu (satıcı rolünde Listing read
	# yok; Ürünlerim ayrı API). get_all + açık tenant filtresi güvenli + izin-hatasız.
	seller = frappe.db.get_value("Admin Seller Profile", {"owner": frappe.session.user}, "name")
	if not seller:
		return {"count": 0, "total": 0, "error": _("Satıcı profili bulunamadı")}
	base = [["seller_profile", "=", seller]]

	total_count = len(frappe.get_all("Listing", filters=base, limit_page_length=0, as_list=True))

	if not condition_builder_json or not condition_builder_json.strip():
		return {"count": total_count, "total": total_count, "error": None}

	try:
		builder = json.loads(condition_builder_json)
	except json.JSONDecodeError:
		return {"count": 0, "total": total_count, "error": _("Koşul JSON çözümlenemedi")}
	if not isinstance(builder, dict):
		return {"count": 0, "total": total_count, "error": _("Koşul nesne olmalı")}

	leaf_filters = _collect_filters(builder)
	match = builder.get("match", "all")
	kwargs = {"filters": base, "limit_page_length": 0, "as_list": True}
	if match == "any" and leaf_filters:
		kwargs["or_filters"] = leaf_filters
	elif leaf_filters:
		kwargs["filters"] = base + leaf_filters

	matched = frappe.get_all("Listing", **kwargs)
	return {"count": len(matched), "total": total_count, "error": None}


# ── Sihirbaz eylem derleme (mevcut ECA Action Template + ECA Rule'a map) ───────


def _compile_action(action_key: str, params: dict) -> tuple[str, dict]:
	"""Sihirbaz eylemini (action_type, ECA Action Template alanları)'na çevir.

	Yeni DocType alanı GEREKMEZ — mevcut field_update/email/reject_row/webhook'a map.
	discount_price/markup_price -> field_update(selling_price aritmetiği).

	Returns:
	    (action_type, template_fields_dict)
	"""
	import json

	if action_key in ("discount_price", "markup_price"):
		percent = frappe.utils.flt(params.get("percent"))
		factor = f"1 - {percent}/100" if action_key == "discount_price" else f"1 + {percent}/100"
		# selling_price boşsa indirim/zammı base_price'tan hesapla.
		expr = f"flt(doc.get('selling_price') or doc.get('base_price')) * ({factor})"
		field_updates = json.dumps([{"fieldname": "selling_price", "value": expr}])
		return "field_update", {"field_updates": field_updates}

	if action_key == "set_field":
		field_updates = json.dumps([{"fieldname": params.get("field"), "value": params.get("value")}])
		return "field_update", {"field_updates": field_updates}

	if action_key == "email":
		# email_recipients oturum kullanıcısına gider; not body template'ine girer.
		return "email", {
			"email_recipients": frappe.session.user,
			"email_body_template": params.get("note") or _("Kuralınız bir ürün için tetiklendi."),
		}

	if action_key == "reject_row":
		return "reject_row", {"reject_reason": params.get("reason") or _("ECA kuralı tarafından reddedildi")}

	if action_key == "webhook":
		return "webhook", {"webhook_url": params.get("url") or "", "webhook_method": "POST"}

	frappe.throw(_("Bilinmeyen eylem: {0}").format(action_key))


def _upsert_action_template(rule_name: str, action_type: str, fields: dict) -> str:
	"""Kural için tek bir ECA Action Template oluştur/güncelle (idempotent)."""
	template_name = f"{rule_name} — Eylem"
	if frappe.db.exists("ECA Action Template", template_name):
		tpl = frappe.get_doc("ECA Action Template", template_name)
		tpl.check_permission("write")
	else:
		tpl = frappe.new_doc("ECA Action Template")
		tpl.template_name = template_name
	tpl.action_type = action_type
	for key, value in fields.items():
		setattr(tpl, key, value)
	tpl.save()
	return tpl.name


@frappe.whitelist()
def save_wizard_rule(payload: str) -> dict:
	"""Sihirbaz çıktısını ECA Rule + ECA Action Template kayıtlarına derler.

	payload (JSON string):
	    {
	        "name": "<mevcut ECA Rule adı | boş=yeni>",
	        "rule_name": "Petkim ürünlerine indirim",
	        "condition_builder": <ConditionBuilder JSON dict>,
	        "action": {"key": "discount_price", "params": {"percent": 15}},
	        "bulk_import": true,            # toplu yüklemede de uygulansın
	        "enabled": true
	    }

	Satıcı çağrısında eylem whitelist'i (validators.is_action_allowed) ve
	field_update hedefleri (is_field_writable) ile doğrulanır.
	"""
	import json

	from tradehub_core.eca.condition_compiler import CompileError, compile_condition
	from tradehub_core.eca.validators import is_action_allowed, is_field_writable

	try:
		data = json.loads(payload)
	except (json.JSONDecodeError, TypeError):
		frappe.throw(_("Geçersiz sihirbaz verisi"))
	if not isinstance(data, dict):
		frappe.throw(_("Geçersiz sihirbaz verisi"))

	is_admin = _is_admin_caller()
	owner_role = "Marketplace Admin" if is_admin else "Seller"

	seller = frappe.db.get_value("Admin Seller Profile", {"owner": frappe.session.user}, "name")
	if not is_admin and not seller:
		frappe.throw(_("Satıcı profili bulunamadı"))

	rule_name = (data.get("rule_name") or "").strip()
	if not rule_name:
		frappe.throw(_("Kural adı zorunlu"))

	# 1) Koşulu derle (whitelist alan güvenliği compile_condition'da).
	builder = data.get("condition_builder") or {}
	condition_python = ""
	if builder.get("conditions") or builder.get("groups"):
		try:
			condition_python = compile_condition(builder, doctype="Listing")
		except CompileError as e:
			frappe.throw(_("Koşul derlenemedi: {0}").format(str(e)))

	# 2) Eylemi derle + yetki doğrula.
	action = data.get("action") or {}
	action_type, template_fields = _compile_action(action.get("key"), action.get("params") or {})

	if not is_action_allowed(action_type, owner_role):
		frappe.throw(_("Bu eylem için yetkiniz yok"))
	if action_type == "field_update":
		for upd in json.loads(template_fields.get("field_updates") or "[]"):
			if not is_field_writable(upd.get("fieldname"), owner_role, doctype="Listing"):
				frappe.throw(_("Bu alana yazma yetkiniz yok: {0}").format(upd.get("fieldname")))

	# 3) Action Template oluştur/güncelle (kural başına 1 template).
	template_name = _upsert_action_template(rule_name, action_type, template_fields)

	# 4) ECA Rule oluştur/güncelle.
	existing = (data.get("name") or "").strip()
	if existing:
		rule = frappe.get_doc("ECA Rule", existing)
		rule.check_permission("write")
	else:
		rule = frappe.new_doc("ECA Rule")

	# NOT: Aktif motor evaluate_rules_two_phase yalnızca frappe.flags.in_bulk_import
	# iken fire eder (hooks.py Listing before_save/on_update/after_insert). execution_phase
	# satıcı kurallarını Faz 1, admin kurallarını Faz 2'ye yerleştirir.
	rule.rule_name = rule_name
	rule.enabled = 1 if data.get("enabled", True) else 0
	rule.reference_doctype = "Listing"
	rule.event = "before_save"
	rule.context_filter = "bulk_import" if data.get("bulk_import") else ""
	rule.rule_scope = "Platform" if is_admin else "Per-Seller"
	rule.seller_profile = None if is_admin else seller
	rule.owner_role = owner_role
	rule.execution_phase = "Admin Phase" if is_admin else "Seller Phase"
	rule.priority = 50 if is_admin else 500
	rule.condition_builder = json.dumps(builder) if builder else ""
	rule.condition = condition_python
	rule.action_type = action_type
	rule.action_template = template_name
	rule.save()

	return {"ok": True, "name": rule.name, "action_template": template_name}

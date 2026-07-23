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

from tradehub_core.bulk_import.regex_lib import _link_label_field

# Tip -> izinli operatör listesi. condition_compiler._COMPARISON_OPS / _SPECIAL_OPS
# ile uyumlu; sihirbaz cascade'inin kalbi (alan tipi operatör menüsünü belirler).
_TYPE_OPERATORS: dict[str, list[str]] = {
	"number": ["gt", "lt", "gte", "lte", "eq", "neq"],
	"text": ["eq", "neq", "contains", "not_contains", "is_set", "is_empty"],
	"select": ["eq", "neq", "in_list", "not_in_list"],
	"link": ["eq", "neq", "in_list", "not_in_list"],
	"boolean": ["eq"],
}

# Şema anahtarı -> Listing DB kolonu. Çoğu anahtar kolonla birebir; tek istisna
# canonical "sku" → fiziksel "seller_sku" (bulk_import.persister._LINK_FIELDS ile
# aynı eşleme). count/preview/test sorguları gerçek kolonla çalışmalı.
_FIELD_DB_COLUMN: dict[str, str] = {"sku": "seller_sku"}


def _db_column(field: str) -> str:
	"""Şema alan anahtarını gerçek Listing DB kolonuna çevir (sku→seller_sku)."""
	return _FIELD_DB_COLUMN.get(field, field)


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

# create_document için izin verilen (güvenli) kayıt türleri allowlist'i.
# Kullanıcıya "DocType" kelimesi GÖSTERİLMEZ — Türkçe label dropdown'da görünür.
# Bu sabit üç katmanda paylaşılır: get_rule_schema (dropdown), _compile_action
# (kayıt anı doğrulaması) ve dispatcher (çalışma anı son savunma). ignore_permissions
# ile insert eden dispatcher rastgele DocType yaratamasın diye allowlist ZORUNLU.
#
# Her giriş: doctype adı -> {"label": Türkçe ad, "fields": [{key, label}]}.
# fields = kullanıcının eşleyebileceği güvenli hedef alanlar (frontend hardcode etmez,
# get_doctype_target_fields endpoint'iyle döner).
CREATABLE_DOCTYPES: dict[str, dict] = {
	"ToDo": {
		"label": "Görev",
		"fields": [
			{"key": "description", "label": "Açıklama"},
			{"key": "date", "label": "Son Tarih"},
			{"key": "priority", "label": "Öncelik"},
			{"key": "allocated_to", "label": "Atanan"},
		],
	},
	"Note": {
		"label": "Not",
		"fields": [
			{"key": "title", "label": "Başlık"},
			{"key": "content", "label": "İçerik"},
			{"key": "public", "label": "Herkese Açık"},
		],
	},
	"Platform Notification": {
		"label": "Bildirim",
		"fields": [
			{"key": "title", "label": "Başlık"},
			{"key": "message", "label": "Mesaj"},
			{"key": "type", "label": "Tip"},
			{"key": "recipient_role", "label": "Alıcı Rol"},
			{"key": "action_url", "label": "Aksiyon URL"},
		],
	},
}


def _creatable_doctype_options() -> list[dict]:
	"""create_document "kayıt türü" dropdown'u için {key, label} listesi (Türkçe)."""
	return [{"key": dt, "label": meta["label"]} for dt, meta in CREATABLE_DOCTYPES.items()]


# Admin'e ek eylemler. Satıcı şemasında görünmez.
# add_tag/set_status/set_category/set_stock → _compile_action ile field_update'e
# derlenir (yeni DocType/action_type GEREKMEZ). webhook/create_document mevcut
# dispatcher handler'larına; custom_script GATED (yalnız admin + audit).
_ADMIN_EXTRA_ACTIONS: tuple[dict, ...] = (
	{
		"key": "add_tag",
		"label": "Etiket ekle/kaldır",
		"params": [
			{"key": "tag", "type": "text", "label": "Etiket"},
			{
				"key": "mode",
				"type": "enum",
				"label": "İşlem",
				"options": ["add", "remove"],
			},
		],
	},
	{
		"key": "set_status",
		"label": "Durumu değiştir",
		"params": [{"key": "value", "type": "enum", "label": "Durum", "_enum_field": "status"}],
	},
	{
		"key": "set_category",
		"label": "Kategoriyi değiştir",
		"params": [{"key": "value", "type": "doctype", "label": "Kategori", "_doctype": "Product Category"}],
	},
	{
		"key": "set_stock",
		"label": "Stok ayarla",
		"params": [{"key": "value", "type": "number", "label": "Stok adedi"}],
	},
	{
		"key": "webhook",
		"label": "Dış sisteme bildir (webhook)",
		"params": [{"key": "url", "type": "text", "label": "URL"}],
	},
	{
		"key": "create_document",
		"label": "Otomatik belge oluştur",
		"params": [
			# "kayıt türü" — curated allowlist dropdown (Türkçe label; "DocType" kelimesi YOK).
			{"key": "doctype", "type": "creatable_doctype", "label": "Oluşturulacak kayıt türü"},
			# "mappings" — tıklama satır eşlemesi (hedef alan <- değer); JSON kullanıcıdan gizli.
			{"key": "mappings", "type": "field_map", "label": "Alan eşlemeleri"},
		],
	},
	{
		"key": "custom_script",
		"label": "Gelişmiş betik (son çare)",
		"gated": True,
		"params": [{"key": "script", "type": "text", "label": "Python betiği"}],
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
		# is_tree → frontend ağaç-gezinme picker'ı kullanır (düz 11k dump yerine).
		return {
			"kind": "doctype",
			"doctype": field["_doctype"],
			"is_tree": _is_tree_doctype(field["_doctype"]),
		}
	return {"kind": "text"}


def _is_tree_doctype(doctype: str) -> bool:
	"""Doctype NSM ağaç mı (Product Category gibi) — picker mod seçimi için."""
	try:
		return bool(frappe.get_meta(doctype).is_tree)
	except Exception:
		frappe.log_error(f"is_tree meta okunamadı: {doctype}", "eca.api._is_tree_doctype")
		return False


def _enrich_action_params(action: dict) -> dict:
	"""Eylem parametrelerine value_source ekle (enum/doctype seçenekleri için).

	Sihirbaz param girişini (dropdown vs serbest metin) bu kaynaktan üretir;
	frontend hiçbir seçeneği hardcode etmez.
	"""
	params = []
	for p in action.get("params", []):
		entry = dict(p)
		ptype = p.get("type")
		if ptype == "enum":
			if p.get("_enum_field"):
				entry["value_source"] = {"kind": "enum", "options": _enum_options(p["_enum_field"])}
			else:
				entry["value_source"] = {"kind": "enum", "options": p.get("options", [])}
		elif ptype == "doctype" and p.get("_doctype"):
			# is_tree → set_category gibi ağaç param'ında frontend ağaç-gezinme picker'ı kullanır.
			entry["value_source"] = {
				"kind": "doctype",
				"doctype": p["_doctype"],
				"is_tree": _is_tree_doctype(p["_doctype"]),
			}
		elif ptype == "creatable_doctype":
			# Curated "kayıt türü" — {key, label} obj'leri; frontend Türkçe label gösterir.
			entry["value_source"] = {"kind": "creatable_doctype", "options": _creatable_doctype_options()}
		elif ptype == "field_map":
			# Alan eşlemesi — hedef alan listesi seçilen "kayıt türü"ne bağlı; frontend
			# get_doctype_target_fields ile yükler. Burada yalnız kind işaretlenir.
			entry["value_source"] = {"kind": "field_map"}
		params.append(entry)
	out = dict(action)
	out["params"] = params
	return out


@frappe.whitelist()
def get_rule_schema() -> dict:
	"""Kural sihirbazı için alan + eylem şeması (dinamik cascade kaynağı).

	Frontend hiçbir alan/operatör/eylem hardcode etmez; bu şemadan üretir.
	`fields[].type` operatör listesini ve değer girişini belirler. `actions`
	satıcıya 5 eylem; admin caller'da genişletilmiş eylem kütüphanesi + scope
	seçenekleri + satıcı listesi eklenir (satıcı yanıtı DEĞİŞMEZ).

	Returns:
	    {"fields": [{key, label, type, operators, value_source}],
	     "actions": [{key, label, params, gated?}],
	     "writable_fields": [{key, label}],
	     "is_admin": bool, "scopes": [...], "sellers": [...]}
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

	is_admin = _is_admin_caller()
	if is_admin:
		actions = [_enrich_action_params(a) for a in list(_SELLER_ACTIONS) + list(_ADMIN_EXTRA_ACTIONS)]
	else:
		actions = [_enrich_action_params(a) for a in _SELLER_ACTIONS]

	# set_field hedefleri = satıcı yazılabilir whitelist (etiketler _RULE_FIELDS'ten).
	labels = {f["key"]: f["label"] for f in _RULE_FIELDS}
	writable = [{"key": k, "label": labels.get(k, k)} for k in sorted(LISTING_SELLER_WRITABLE_FIELDS)]

	result = {"fields": fields, "actions": actions, "writable_fields": writable, "is_admin": is_admin}
	if is_admin:
		result["scopes"] = [
			{"key": "Platform", "label": _("Tüm Platform")},
			{"key": "Per-Seller", "label": _("Belirli Satıcı")},
		]
		result["sellers"] = get_seller_options()
	return result


@frappe.whitelist()
def get_seller_options() -> list[dict]:
	"""Admin sihirbazı "Kime?" adımı için satıcı listesi (mağaza adı dahil).

	Yalnızca admin caller; satıcı bu listeyi çekemez.
	"""
	frappe.only_for(["System Manager", "Marketplace Admin"])
	rows = frappe.get_all(
		"Admin Seller Profile",
		fields=["name", "seller_name", "company_name"],
		order_by="seller_name asc",
		limit_page_length=0,
	)
	return [
		{
			"key": r["name"],
			"label": r.get("seller_name") or r.get("company_name") or r["name"],
		}
		for r in rows
	]


@frappe.whitelist()
def get_creatable_doctypes() -> list[dict]:
	"""create_document "kayıt türü" dropdown'u — izin verilen kayıt türleri (Türkçe).

	Yalnız admin caller. value=gerçek doctype adı, label=kullanıcıya gösterilen Türkçe ad.
	Allowlist CREATABLE_DOCTYPES sabitinden gelir (rastgele DocType yaratımı engellenir).
	"""
	frappe.only_for(["System Manager", "Marketplace Admin"])
	return [{"value": opt["key"], "label": opt["label"]} for opt in _creatable_doctype_options()]


@frappe.whitelist()
def get_doctype_target_fields(doctype: str) -> list[dict]:
	"""Seçilen "kayıt türü"nün eşlenebilir hedef alanlarını döner (tıklama eşlemesi için).

	Yalnız admin caller + allowlist guard (CREATABLE_DOCTYPES dışı doctype reddedilir).
	value=alan adı, label=Türkçe ad. Frontend bu listeyi alan-eşleme satırlarının
	"hedef alan" dropdown'unda kullanır (hardcode etmez — şema sözleşmesi).
	"""
	frappe.only_for(["System Manager", "Marketplace Admin"])
	doctype = (doctype or "").strip()
	meta = CREATABLE_DOCTYPES.get(doctype)
	if not meta:
		return []
	return [{"value": f["key"], "label": f["label"]} for f in meta["fields"]]


@frappe.whitelist()
def get_link_options(doctype: str) -> list[dict]:
	"""Link-alan değer dropdown'u için okunur seçenekler (UUID name yerine ad).

	set_category gibi link-alanları ve koşul deger doctype'ları (Brand/Product
	Category/Product Type) için kullanılır. Değer = name (kayıt anahtarı), label =
	meta.title_field (okunur ad); siralama label'a göre. Yalnız admin caller.

	Returns:
	    [{"v": name, "l": display}] — frontend optKey/optValue/optLabel ile uyumlu.
	"""
	from tradehub_core.bulk_import.regex_lib import _link_field_values

	frappe.only_for(["System Manager", "Marketplace Admin"])
	doctype = (doctype or "").strip()
	# Şema sözleşmesi: yalnız _RULE_FIELDS / admin eylemlerinde geçen doctype'lar.
	allowed = {f["_doctype"] for f in _RULE_FIELDS if f.get("_doctype")}
	allowed |= {p["_doctype"] for a in _ADMIN_EXTRA_ACTIONS for p in a["params"] if p.get("_doctype")}
	if doctype not in allowed:
		return []
	values = _link_field_values(doctype).get("values", [])
	return [{"v": v["value"], "l": v["label"]} for v in values]


# ── Ağaç + arama değer seçici (büyük link alanları) ───────────────────────────
#
# get_link_options TÜM kayıtları düz döker — Product Category (11k+ düğüm) gibi
# büyük/ağaç alanlarda kullanılamaz (UUID-benzeri name'ler alfabetik sıralanır,
# sembol/sayı yapraklar başa gelir). Aşağıdaki üçlü, picker'ın AĞAÇ-GEZİNME +
# ARAMA modlarını besler: küçük flat listeler için get_link_options KALIR.


def _allowed_picker_doctypes() -> set[str]:
	"""Picker endpoint'lerinin izin verdiği doctype'lar (get_link_options ile aynı).

	Şema sözleşmesi: yalnız _RULE_FIELDS / admin eylemlerinde geçen doctype'lar —
	rastgele DocType taraması engellenir.
	"""
	allowed = {f["_doctype"] for f in _RULE_FIELDS if f.get("_doctype")}
	allowed |= {p["_doctype"] for a in _ADMIN_EXTRA_ACTIONS for p in a["params"] if p.get("_doctype")}
	return allowed


def _resolve_picker_doctype(doctype: str) -> str:
	"""Picker doctype'ını doğrula + admin guard. Geçersizse throw."""
	frappe.only_for(["System Manager", "Marketplace Admin"])
	doctype = (doctype or "").strip()
	if doctype not in _allowed_picker_doctypes():
		frappe.throw(_("Bu kayıt türü için seçici kullanılamaz: {0}").format(doctype or "—"))
	return doctype


def _tree_parent_field(doctype: str) -> str | None:
	"""Ağaç doctype'ın NSM parent alanı (Product Category → parent_product_category).

	is_tree değilse None döner — caller flat link davranışına geçer.
	"""
	meta = frappe.get_meta(doctype)
	if not meta.is_tree:
		return None
	return meta.nsm_parent_field or f"parent_{doctype.lower().replace(' ', '_')}"


def _picker_row(doctype: str, name: str, label: str, parent_field: str) -> dict:
	"""Tek ağaç düğümünü {value, label, has_children} olarak döndür."""
	return {
		"value": name,
		"label": label or name,
		"has_children": bool(frappe.db.count(doctype, {parent_field: name})),
	}


@frappe.whitelist()
def link_tree_roots(doctype: str) -> list[dict]:
	"""Ağaç (is_tree) doctype için KÖK kayıtları döndürür — picker ağaç-gezinme modu.

	Yalnız admin caller + allowlist guard. Her kök {value, label, has_children}
	(lazy chevron için) içerir. is_tree değilse boş liste (caller arama kullanmalı).

	`label` = title_field (Product Category → category_name). `value` = name.
	"""
	doctype = _resolve_picker_doctype(doctype)
	parent_field = _tree_parent_field(doctype)
	if not parent_field:
		return []
	label_field = _link_label_field(doctype) or "name"
	rows = frappe.get_all(
		doctype,
		filters={parent_field: ["is", "not set"]},
		fields=["name", label_field],
		order_by=f"{label_field} asc",
		limit_page_length=0,
	)
	return [_picker_row(doctype, r["name"], r.get(label_field), parent_field) for r in rows]


@frappe.whitelist()
def link_tree_children(doctype: str, parent: str) -> list[dict]:
	"""Ağaç doctype'ta `parent`'ın doğrudan çocukları (lazy) — {value, label, has_children}.

	Yalnız admin caller + allowlist guard. is_tree değilse veya parent boşsa boş döner.
	"""
	doctype = _resolve_picker_doctype(doctype)
	parent_field = _tree_parent_field(doctype)
	parent = (parent or "").strip()
	if not parent_field or not parent:
		return []
	label_field = _link_label_field(doctype) or "name"
	rows = frappe.get_all(
		doctype,
		filters={parent_field: parent},
		fields=["name", label_field],
		order_by=f"{label_field} asc",
		limit_page_length=0,
	)
	return [_picker_row(doctype, r["name"], r.get(label_field), parent_field) for r in rows]


def _ancestor_path(doctype: str, parent_field: str, label_field: str, parent: str | None) -> str:
	"""`parent`'tan köke ata zincirini "Hizmet › Web › .com" formatında döndürür.

	Cycle koruması (max 20 derinlik) — `_depth` kullanılıyor çünkü `_` i18n
	fonksiyonunu gölgeler ve fonksiyon başındaki throw(_(...)) ile çakışır.
	"""
	names: list[str] = []
	cursor = parent
	for _depth in range(20):
		if not cursor:
			break
		row = frappe.db.get_value(doctype, cursor, [label_field, parent_field], as_dict=True)
		if not row:
			break
		names.insert(0, row.get(label_field) or cursor)
		cursor = row.get(parent_field)
	return " › ".join(names)


@frappe.whitelist()
def link_search(doctype: str, q: str, limit: int = 20) -> list[dict]:
	"""Link alan değer araması — okunur ad (title_field) üzerinde, UUID name'de DEĞİL.

	Yalnız admin caller + allowlist guard. q < 2 ise boş döner. Ağaç doctype'ta
	her sonuç ata zinciri `path` ("Hizmet › Web › .com") taşır; flat link'te
	(Brand/Product Type) path boş. Sonuç {value, label, path}. limit max 50.
	"""
	doctype = _resolve_picker_doctype(doctype)
	query = (q or "").strip()
	if len(query) < 2:
		return []
	try:
		lim = min(50, max(1, int(limit)))
	except (ValueError, TypeError):
		lim = 20

	label_field = _link_label_field(doctype) or "name"
	parent_field = _tree_parent_field(doctype)
	fields = ["name", label_field]
	if parent_field:
		fields.append(parent_field)
	rows = frappe.get_all(
		doctype,
		filters={label_field: ["like", f"%{query}%"]},
		fields=fields,
		order_by=f"{label_field} asc",
		limit_page_length=lim,
	)
	results = []
	for r in rows:
		results.append(
			{
				"value": r["name"],
				"label": r.get(label_field) or r["name"],
				"path": (
					_ancestor_path(doctype, parent_field, label_field, r.get(parent_field))
					if parent_field
					else ""
				),
			}
		)
	return results


@frappe.whitelist()
def link_resolve(doctype: str, value: str) -> dict | None:
	"""Kayıtlı tek `value` (name) için okunur ad + path döndürür — düzenleme açılışı.

	Picker bir UUID name ile yüklendiğinde label/path göstermek için kullanılır.
	Yalnız admin caller + allowlist guard. Ağaç doctype'ta `path` ata zinciri taşır;
	flat link'te boş. Kayıt yoksa None. Sonuç {value, label, path}.
	"""
	doctype = _resolve_picker_doctype(doctype)
	value = (value or "").strip()
	if not value:
		return None
	label_field = _link_label_field(doctype) or "name"
	parent_field = _tree_parent_field(doctype)
	wanted = [label_field] + ([parent_field] if parent_field else [])
	row = frappe.db.get_value(doctype, value, wanted, as_dict=True)
	if not row:
		return None
	return {
		"value": value,
		"label": row.get(label_field) or value,
		"path": (
			_ancestor_path(doctype, parent_field, label_field, row.get(parent_field)) if parent_field else ""
		),
	}


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
	col = _db_column(field)
	if op in _FILTER_OPS:
		return (col, _FILTER_OPS[op], value)
	if op == "contains":
		return (col, "like", f"%{value}%")
	if op == "not_contains":
		return (col, "not like", f"%{value}%")
	if op == "in_list":
		return (col, "in", value if isinstance(value, list) else [value])
	if op == "not_in_list":
		return (col, "not in", value if isinstance(value, list) else [value])
	if op == "is_set":
		return (col, "is", "set")
	if op == "is_empty":
		return (col, "is", "not set")
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


def _resolve_scope_base(scope: str | None, seller_profile: str | None) -> tuple[list, str | None]:
	"""Sayım/önizleme için temel tenant filtresini çöz (rol-bilinçli).

	- Satıcı caller: HER ZAMAN kendi seller_profile'ına kilitli (scope yok sayılır).
	- Admin caller: scope="Platform" → filtresiz (tüm platform); "Per-Seller" →
	  verilen seller_profile'a kilitli.

	Returns:
	    (base_filters, error) — error doluysa çağıran 0 döndürmeli.
	"""
	if _is_admin_caller():
		if (scope or "Platform") == "Per-Seller":
			if not seller_profile:
				return [], _("Satıcı seçilmedi")
			return [["seller_profile", "=", seller_profile]], None
		return [], None  # Platform geneli — tenant filtresi yok.

	# Satıcı: kendi profili (scope/seller_profile parametreleri yok sayılır).
	seller = frappe.db.get_value("Admin Seller Profile", {"owner": frappe.session.user}, "name")
	if not seller:
		return [], _("Satıcı profili bulunamadı")
	return [["seller_profile", "=", seller]], None


@frappe.whitelist()
def count_matching(
	reference_doctype: str,
	condition_builder_json: str,
	scope: str | None = None,
	seller_profile: str | None = None,
) -> dict:
	"""Bir koşula uyan kayıt sayısı + toplam (rol-bilinçli canlı önizleme).

	Satıcı caller kendi Listing'lerini sayar (scope/seller_profile yok sayılır).
	Admin caller scope="Platform" ile tüm platformu, "Per-Seller" ile seçilen
	satıcıyı sayar. Satıcı çağrısı eskisiyle AYNI sonucu döner (regresyon yok).

	Args:
	    reference_doctype: Şu an yalnızca "Listing".
	    condition_builder_json: ConditionBuilder JSON (string).
	    scope: (admin) "Platform" | "Per-Seller".
	    seller_profile: (admin, Per-Seller) hedef satıcı.

	Returns:
	    {"count": int, "total": int, "error": str | None}
	"""
	import json

	if reference_doctype != "Listing":
		return {"count": 0, "total": 0, "error": _("Desteklenmeyen modül")}

	# Tenant taban filtresi rol/scope'a göre. get_all + açık filtre güvenli +
	# izin-hatasız (satıcı rolünde Listing read yok; Ürünlerim ayrı API).
	base, err = _resolve_scope_base(scope, seller_profile)
	if err:
		return {"count": 0, "total": 0, "error": err}

	total_count = frappe.db.count("Listing", filters=base)

	if not condition_builder_json or not condition_builder_json.strip():
		return {"count": total_count, "total": total_count, "error": None}

	try:
		builder = json.loads(condition_builder_json)
	except json.JSONDecodeError:
		return {"count": 0, "total": total_count, "error": _("Koşul JSON çözümlenemedi")}
	if not isinstance(builder, dict):
		return {"count": 0, "total": total_count, "error": _("Koşul nesne olmalı")}

	matched = _matching_listings(builder, base, fields=None, limit=0)
	return {"count": len(matched), "total": total_count, "error": None}


def _matching_listings(builder: dict, base: list, fields: list | None, limit: int) -> list:
	"""Builder koşuluna uyan Listing'leri çek (base tenant filtresiyle).

	fields=None → as_list (yalnızca sayım); aksi halde as_dict alan listesi.
	limit=0 → tümü.
	"""
	leaf_filters = _collect_filters(builder)
	match = builder.get("match", "all")
	kwargs: dict = {"filters": base, "limit_page_length": limit}
	if fields is None:
		kwargs["as_list"] = True
	else:
		kwargs["fields"] = fields
	if match == "any" and leaf_filters:
		kwargs["or_filters"] = leaf_filters
	elif leaf_filters:
		kwargs["filters"] = base + leaf_filters
	return frappe.get_all("Listing", **kwargs)


# ── DRY-RUN önizleme (PERSIST YOK) ────────────────────────────────────────────

PREVIEW_SAMPLE_LIMIT = 10


@frappe.whitelist()
def preview_rule_effect(
	reference_doctype: str,
	condition_builder_json: str,
	action_key: str,
	params_json: str = "{}",
	scope: str | None = None,
	seller_profile: str | None = None,
) -> dict:
	"""Kuralın NE yapacağını PERSIST ETMEDEN göster (dry-run).

	Eşleşen ürün sayısı + en fazla ~10 örnek üzerinde alan before/after hesaplar.
	setattr/save YOK — yalnızca value-expr eval. count_matching ile aynı
	scope/tenant mantığı (satıcı kendi, admin Platform/Per-Seller).

	Returns:
	    {"count": int, "total": int,
	     "samples": [{sku, title, field, old, new}], "error": str | None}
	"""
	import json

	from tradehub_core.eca.dispatcher import _eval_value_expr_v2

	if reference_doctype != "Listing":
		return {"count": 0, "total": 0, "samples": [], "error": _("Desteklenmeyen modül")}

	base, err = _resolve_scope_base(scope, seller_profile)
	if err:
		return {"count": 0, "total": 0, "samples": [], "error": err}

	try:
		builder = json.loads(condition_builder_json) if (condition_builder_json or "").strip() else {}
		params = json.loads(params_json or "{}")
	except json.JSONDecodeError:
		return {"count": 0, "total": 0, "samples": [], "error": _("Geçersiz veri")}
	if not isinstance(params, dict):
		params = {}

	total_count = frappe.db.count("Listing", filters=base)

	# Eylemi derle — yalnız field_update örneklerinde before/after gösterilebilir.
	owner_role = "Marketplace Admin" if _is_admin_caller() else "Seller"
	try:
		action_type, template_fields = _compile_action(action_key, params, owner_role)
	except Exception as e:
		return {"count": 0, "total": total_count, "samples": [], "error": str(e)[:200]}

	matched = _matching_listings(builder, base, fields=["name"], limit=0)
	count = len(matched)

	samples: list[dict] = []
	if action_type == "field_update":
		updates = json.loads(template_fields.get("field_updates") or "[]")
		sample_names = [r["name"] for r in matched[:PREVIEW_SAMPLE_LIMIT]]
		for name in sample_names:
			doc = frappe.get_doc("Listing", name)
			for upd in updates:
				fieldname = upd.get("fieldname")
				if not fieldname:
					continue
				old = doc.get(fieldname)
				new = _eval_value_expr_v2(upd.get("value"), doc)
				samples.append(
					{
						"sku": doc.get("seller_sku"),
						"title": doc.get("title"),
						"field": fieldname,
						"old": old,
						"new": new,
					}
				)

	return {"count": count, "total": total_count, "samples": samples, "error": None}


@frappe.whitelist()
def test_rule_on_product(
	sku_or_name: str,
	condition_builder_json: str,
	action_key: str,
	params_json: str = "{}",
	scope: str | None = None,
	seller: str | None = None,
) -> dict:
	"""Kuralı TEK ürün üzerinde dene (persist YOK) — eşleşir mi + before/after.

	preview_rule_effect mantığını tek SKU/name'e indirir. Önce ürünü tenant
	tabanıyla bulur (found); sonra builder koşulunu AND'leyerek kuralın bu ürüne
	uyup uymadığını söyler (matches). Eşleşiyorsa field_update before/after verir.

	Args:
	    sku_or_name: Listing.sku veya Listing.name.
	    condition_builder_json: ConditionBuilder JSON (string).
	    action_key: Sihirbaz eylem anahtarı (yalnız field_update before/after üretir).
	    params_json: Eylem parametreleri JSON.
	    scope: (admin) "Platform" | "Per-Seller".
	    seller: (admin, Per-Seller) hedef satıcı profili.

	Returns:
	    {"found": bool, "matches": bool, "field": str | None,
	     "before": Any, "after": Any, "samples": [...], "error": str | None}
	"""
	import json

	from tradehub_core.eca.dispatcher import _eval_value_expr_v2

	empty = {"found": False, "matches": False, "field": None, "before": None, "after": None, "samples": []}

	sku_or_name = (sku_or_name or "").strip()
	if not sku_or_name:
		return {**empty, "error": _("Ürün kodu zorunlu")}

	base, err = _resolve_scope_base(scope, seller)
	if err:
		return {**empty, "error": err}

	# Ürünü tenant tabanıyla bul (sku VEYA name) — yetki get_all'da base filtreyle.
	product = _find_listing_in_scope(sku_or_name, base)
	if not product:
		return {**empty, "error": _("Ürün bu kapsamda bulunamadı")}

	try:
		builder = json.loads(condition_builder_json) if (condition_builder_json or "").strip() else {}
		params = json.loads(params_json or "{}")
	except json.JSONDecodeError:
		return {**empty, "found": True, "error": _("Geçersiz veri")}
	if not isinstance(params, dict):
		params = {}

	# Koşul eşleşmesi: bulunan ürünü name'e kilitleyip builder filtrelerini AND'le.
	name_base = base + [["name", "=", product["name"]]]
	matched = _matching_listings(builder, name_base, fields=["name"], limit=1)
	matches = bool(matched)
	if not matches:
		return {**empty, "found": True, "matches": False, "error": None}

	owner_role = "Marketplace Admin" if _is_admin_caller() else "Seller"
	try:
		action_type, template_fields = _compile_action(action_key, params, owner_role)
	except Exception as e:
		return {**empty, "found": True, "matches": True, "error": str(e)[:200]}

	if action_type != "field_update":
		return {**empty, "found": True, "matches": True, "error": None}

	updates = json.loads(template_fields.get("field_updates") or "[]")
	doc = frappe.get_doc("Listing", product["name"])
	samples: list[dict] = []
	first_field = first_old = first_new = None
	for upd in updates:
		fieldname = upd.get("fieldname")
		if not fieldname:
			continue
		old = doc.get(fieldname)
		new = _eval_value_expr_v2(upd.get("value"), doc)
		if first_field is None:
			first_field, first_old, first_new = fieldname, old, new
		samples.append(
			{
				"sku": doc.get("seller_sku"),
				"title": doc.get("title"),
				"field": fieldname,
				"old": old,
				"new": new,
			}
		)

	return {
		"found": True,
		"matches": True,
		"field": first_field,
		"before": first_old,
		"after": first_new,
		"samples": samples,
		"error": None,
	}


def _find_listing_in_scope(sku_or_name: str, base: list) -> dict | None:
	"""Listing'i SKU (seller_sku) VEYA name ile tenant tabanı içinde bul (önce SKU)."""
	rows = frappe.get_all(
		"Listing",
		filters=base + [["seller_sku", "=", sku_or_name]],
		fields=["name"],
		limit_page_length=1,
	)
	if rows:
		return rows[0]
	rows = frappe.get_all(
		"Listing", filters=base + [["name", "=", sku_or_name]], fields=["name"], limit_page_length=1
	)
	return rows[0] if rows else None


# ── Sihirbaz eylem derleme (mevcut ECA Action Template + ECA Rule'a map) ───────


# Named-action → derlenecek Listing alanı (hepsi field_update'e map; yeni alan yok).
_FIELD_SETTER_ACTIONS: dict[str, str] = {
	"set_status": "status",
	"set_category": "product_category",
	"set_stock": "stock_qty",
}


def _compile_create_document(params: dict) -> tuple[str, dict]:
	"""create_document Karar1=A: curated doctype + tıklama satır eşlemesi derle.

	Girdi (frontend): params.doctype = allowlist key; params.mappings = tıklama
	satırları (list of {target, value}) VEYA geriye-uyum için JSON string/dict.
	Çıktı sözleşmesi (dispatcher ile UYUMLU, DEĞİŞMEZ): create_doctype string +
	create_field_mappings JSON string ({field: value_expr}).

	Allowlist + alan whitelist'i kayıt anında burada uygulanır (dispatcher son savunma).
	"""
	import json

	doctype = (params.get("doctype") or "").strip()
	meta = CREATABLE_DOCTYPES.get(doctype)
	if not meta:
		frappe.throw(_("Geçersiz kayıt türü"))

	allowed_fields = {f["key"] for f in meta["fields"]}

	raw = params.get("mappings")
	rows: list = []
	if isinstance(raw, list):
		rows = raw
	elif isinstance(raw, str) and raw.strip():
		# Geriye-uyum: eski JSON string ({field: value}) → satır listesine çevir.
		try:
			parsed = json.loads(raw)
			if isinstance(parsed, dict):
				rows = [{"target": k, "value": v} for k, v in parsed.items()]
			elif isinstance(parsed, list):
				rows = parsed
		except (ValueError, TypeError):
			rows = []
	elif isinstance(raw, dict):
		rows = [{"target": k, "value": v} for k, v in raw.items()]

	compiled: dict[str, str] = {}
	for row in rows:
		if not isinstance(row, dict):
			continue
		target = (row.get("target") or "").strip()
		value = row.get("value")
		if not target or value in (None, ""):
			continue
		if target not in allowed_fields:
			frappe.throw(_("Bu kayıt türü için geçersiz hedef alan: {0}").format(target))
		# Değer literal metindir — dispatcher _eval_value_expr_v2 ile değerlendirir;
		# repr ile literal'leştirerek serbest-eval'i engelle (kullanıcı ifade yazmaz).
		compiled[target] = repr(str(value))

	return "create_document", {
		"create_doctype": doctype,
		"create_field_mappings": json.dumps(compiled),
	}


def _compile_action(action_key: str, params: dict, owner_role: str = "Seller") -> tuple[str, dict]:
	"""Sihirbaz eylemini (action_type, ECA Action Template alanları)'na çevir.

	Yeni DocType alanı GEREKMEZ — mevcut field_update/email/reject_row/webhook/
	create_document/custom_script handler'larına map.
	discount_price/markup_price/add_tag/set_status/set_category/set_stock →
	field_update; custom_script yalnız admin (rol guard + audit).

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

	if action_key in _FIELD_SETTER_ACTIONS:
		# Sabit değerli alan ataması — eval edilmemesi için repr ile literal'leştir.
		fieldname = _FIELD_SETTER_ACTIONS[action_key]
		value = params.get("value")
		if fieldname == "stock_qty":
			value = frappe.utils.cint(value)
		field_updates = json.dumps([{"fieldname": fieldname, "value": repr(value)}])
		return "field_update", {"field_updates": field_updates}

	if action_key == "add_tag":
		tag = str(params.get("tag") or "").strip()
		if not tag:
			frappe.throw(_("Etiket zorunlu"))
		mode = params.get("mode") or "add"
		# tags virgülle ayrılmış string; ekle/kaldır idempotent değer ifadesi.
		tag_lit = repr(tag)
		if mode == "remove":
			expr = (
				f"','.join([t.strip() for t in (doc.get('tags') or '').split(',') "
				f"if t.strip() and t.strip() != {tag_lit}])"
			)
		else:
			expr = (
				f"doc.get('tags') if {tag_lit} in [t.strip() for t in (doc.get('tags') or '').split(',')] "
				f"else ((doc.get('tags') + ',' + {tag_lit}) if doc.get('tags') else {tag_lit})"
			)
		field_updates = json.dumps([{"fieldname": "tags", "value": expr}])
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

	if action_key == "create_document":
		return _compile_create_document(params)

	if action_key == "custom_script":
		# GATED — yalnızca admin. Rol guard + audit save_wizard_rule'da uygulanır.
		if owner_role not in ("System Manager", "Marketplace Admin"):
			frappe.throw(_("Gelişmiş betik için yetkiniz yok"))
		return "custom_script", {"script_body": params.get("script") or ""}

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
	        "enabled": true,
	        "scope": "Platform" | "Per-Seller",   # (admin) "Kime?" adımı
	        "seller_profile": "<satıcı>"          # (admin, Per-Seller)
	    }

	Satıcı çağrısında eylem whitelist'i (validators.is_action_allowed) ve
	field_update hedefleri (is_field_writable) ile doğrulanır. Admin çağrısında
	scope/seller_profile payload'dan gelir; custom_script GATED + audit'lidir.
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
	action_key = action.get("key")
	action_type, template_fields = _compile_action(action_key, action.get("params") or {}, owner_role)

	if not is_action_allowed(action_type, owner_role):
		frappe.throw(_("Bu eylem için yetkiniz yok"))
	if action_type == "field_update":
		for upd in json.loads(template_fields.get("field_updates") or "[]"):
			if not is_field_writable(upd.get("fieldname"), owner_role, doctype="Listing"):
				frappe.throw(_("Bu alana yazma yetkiniz yok: {0}").format(upd.get("fieldname")))

	# custom_script GATED — kim/ne zaman/hangi kural audit kaydı (son çare eylem).
	if action_type == "custom_script":
		frappe.logger("eca_audit").warning(
			f"custom_script rule saved by {frappe.session.user} at {frappe.utils.now()} rule={rule_name}"
		)
		frappe.log_error(
			message=(
				f"user={frappe.session.user} when={frappe.utils.now()} rule={rule_name} action=custom_script"
			),
			title="ECA custom_script saved (GATED)",
		)

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
	# Admin "Kime?" adımı: Platform (tüm satıcılar) veya Per-Seller (seçilen satıcı).
	# Satıcı caller her zaman kendi profiline Per-Seller.
	if is_admin:
		req_scope = "Per-Seller" if (data.get("scope") == "Per-Seller") else "Platform"
		target_seller = (data.get("seller_profile") or "").strip() or None
		if req_scope == "Per-Seller" and not target_seller:
			frappe.throw(_("Belirli satıcı seçilmedi"))
		rule_scope = req_scope
		rule_seller = target_seller if req_scope == "Per-Seller" else None
	else:
		rule_scope = "Per-Seller"
		rule_seller = seller

	rule.rule_name = rule_name
	rule.enabled = 1 if data.get("enabled", True) else 0
	rule.reference_doctype = "Listing"
	rule.event = "before_save"
	rule.context_filter = "bulk_import" if data.get("bulk_import") else ""
	rule.rule_scope = rule_scope
	rule.seller_profile = rule_seller
	rule.owner_role = owner_role
	rule.execution_phase = "Admin Phase" if is_admin else "Seller Phase"
	# ECA Rule controller priority bandını zorunlu kılar: admin 1000+, satıcı 100-999.
	# Admin Faz 2'de (yüksek priority = sonra çalışır = son söz) fire eder.
	rule.priority = 1000 if is_admin else 500
	rule.condition_builder = json.dumps(builder) if builder else ""
	rule.condition = condition_python
	rule.action_type = action_type
	rule.action_template = template_name
	rule.save()

	return {"ok": True, "name": rule.name, "action_template": template_name}


# ── Governance: çakışma uyarısı / versiyon geçmişi (yalnız admin) ─────────────


def _action_target_fields(action_key: str, params: dict, owner_role: str) -> set[str]:
	"""Bir eylemin yazdığı Listing alan kümesi (çakışma karşılaştırması için).

	_compile_action ile aynı derlemeyi kullanır; yalnız field_update tipi somut
	alan yazar. Diğer tipler (email/webhook/custom_script) alan yazmadığından boş
	küme döner — çakışma yalnız field-level overlap'te anlamlıdır.
	"""
	import json

	try:
		action_type, template_fields = _compile_action(action_key, params, owner_role)
	except Exception:
		return set()
	if action_type != "field_update":
		return set()
	fields: set[str] = set()
	for upd in json.loads(template_fields.get("field_updates") or "[]"):
		fieldname = upd.get("fieldname")
		if fieldname:
			fields.add(fieldname)
	return fields


def _template_target_fields(action_template: str | None) -> set[str]:
	"""Mevcut bir ECA Action Template'in yazdığı alan kümesini çıkar."""
	import json

	if not action_template or not frappe.db.exists("ECA Action Template", action_template):
		return set()
	tpl = frappe.get_doc("ECA Action Template", action_template)
	if tpl.action_type != "field_update":
		return set()
	fields: set[str] = set()
	try:
		for upd in json.loads(tpl.get("field_updates") or "[]"):
			fieldname = upd.get("fieldname")
			if fieldname:
				fields.add(fieldname)
	except (ValueError, TypeError):
		return set()
	return fields


@frappe.whitelist()
def detect_rule_conflicts(
	reference_doctype: str,
	condition_builder_json: str,
	action_key: str,
	scope: str,
	seller_profile: str | None = None,
	params_json: str = "{}",
	exclude_rule: str | None = None,
) -> dict:
	"""Kaydetmeden önce bu kuralın başka kurallarla çakışıp çakışmadığını döner.

	Çakışma = AYNI reference_doctype + ORTÜŞEN scope + ORTÜŞEN hedef alan +
	ORTÜŞEN ürün kümesi olan AKTİF başka kural. Salt-okunur (persist YOK). Blok
	DEĞİL — admin yine kaydedebilir; uyarı + öncelik farkı gösterilir (düşük
	priority önce çalışır, son yazan kazanır).

	Args:
	    reference_doctype: Şu an yalnızca "Listing".
	    condition_builder_json: Yeni kuralın ConditionBuilder JSON'u.
	    action_key: Sihirbaz eylem anahtarı (hedef alan çıkarımı için).
	    scope: "Platform" | "Per-Seller".
	    seller_profile: (Per-Seller) hedef satıcı.
	    params_json: Eylem parametreleri JSON.
	    exclude_rule: Düzenleme modunda kendi adını hariç tut.

	Returns:
	    {"conflicts": [{rule, rule_name, reason, priority}], "error": str | None}
	"""
	import json

	frappe.only_for(["System Manager", "Marketplace Admin"])

	if reference_doctype != "Listing":
		return {"conflicts": [], "error": _("Desteklenmeyen modül")}

	try:
		builder = json.loads(condition_builder_json) if (condition_builder_json or "").strip() else {}
		params = json.loads(params_json or "{}")
	except json.JSONDecodeError:
		return {"conflicts": [], "error": _("Geçersiz veri")}
	if not isinstance(params, dict):
		params = {}

	new_fields = _action_target_fields(action_key, params, "Marketplace Admin")
	if not new_fields:
		# Alan yazmayan eylem (webhook/email/custom_script) → field-level çakışma yok.
		return {"conflicts": [], "error": None}

	base, err = _resolve_scope_base(scope, seller_profile)
	if err:
		return {"conflicts": [], "error": err}
	new_matched = {r["name"] for r in _matching_listings(builder, base, fields=["name"], limit=0)}
	if not new_matched:
		return {"conflicts": [], "error": None}

	# Aday kurallar: aynı doctype + ortüşen scope + aktif + kendisi hariç.
	# Platform herkesle ortüşür; Per-Seller yalnız aynı satıcı + Platform ile.
	filters: dict = {"reference_doctype": "Listing", "enabled": 1}
	candidates = frappe.get_all(
		"ECA Rule",
		filters=filters,
		fields=[
			"name",
			"rule_name",
			"rule_scope",
			"seller_profile",
			"action_template",
			"priority",
			"condition_builder",
		],
		limit_page_length=0,
	)

	conflicts: list[dict] = []
	for cand in candidates:
		if exclude_rule and cand["name"] == exclude_rule:
			continue
		if not _scopes_overlap(scope, seller_profile, cand["rule_scope"], cand.get("seller_profile")):
			continue
		cand_fields = _template_target_fields(cand.get("action_template"))
		shared = new_fields & cand_fields
		if not shared:
			continue
		if not _product_sets_overlap(new_matched, cand):
			continue
		conflicts.append(
			{
				"rule": cand["name"],
				"rule_name": cand.get("rule_name") or cand["name"],
				"priority": cand.get("priority"),
				"reason": _("Aynı alan(lar) ({0}) ve ortüşen ürünler üzerinde çakışıyor").format(
					", ".join(sorted(shared))
				),
			}
		)

	return {"conflicts": conflicts, "error": None}


def _scopes_overlap(scope_a: str, seller_a: str | None, scope_b: str | None, seller_b: str | None) -> bool:
	"""İki kural scope'unun aynı ürün kümesini etkileyip etkilemediği.

	Platform herkesle ortüşür. İki Per-Seller yalnız aynı satıcıda ortüşür.
	"""
	if (scope_a or "Platform") == "Platform" or (scope_b or "Platform") == "Platform":
		return True
	return bool(seller_a) and seller_a == seller_b


def _product_sets_overlap(new_matched: set[str], candidate: dict) -> bool:
	"""Aday kuralın eşleştiği ürünlerle yeni kuralın kümesi kesişiyor mu."""
	import json

	cand_scope = candidate.get("rule_scope") or "Platform"
	cand_base, err = _resolve_scope_base(cand_scope, candidate.get("seller_profile"))
	if err:
		return False
	try:
		cand_builder = json.loads(candidate.get("condition_builder") or "{}")
	except (ValueError, TypeError):
		cand_builder = {}
	cand_matched = {r["name"] for r in _matching_listings(cand_builder, cand_base, fields=["name"], limit=0)}
	return bool(new_matched & cand_matched)


def _summarize_version_changes(data: str) -> list[dict]:
	"""Frappe Version.data JSON'undan kullanıcıya gösterilir değişiklik özeti çıkar."""
	import json

	try:
		parsed = json.loads(data or "{}")
	except (ValueError, TypeError):
		return []
	summary: list[dict] = []
	for row in parsed.get("changed") or []:
		# row = [fieldname, old, new]
		if len(row) >= 3:
			summary.append({"field": row[0], "old": row[1], "new": row[2]})
	return summary


@frappe.whitelist()
def get_rule_versions(rule_name: str) -> dict:
	"""Bir ECA Rule'un değişiklik geçmişini döner (Frappe Version'dan).

	Tenant guard: önce ECA Rule.check_permission("read"). Version sistem-meta
	DocType'ı olduğundan get_all ile okunur (kullanıcı verisi değil), ama erişim
	parent kuralın okuma yetkisine kilitlidir.

	Returns:
	    {"versions": [{version, modified, modified_by, changes}], "error": str | None}
	"""
	frappe.only_for(["System Manager", "Marketplace Admin"])

	rule_name = (rule_name or "").strip()
	if not rule_name or not frappe.db.exists("ECA Rule", rule_name):
		return {"versions": [], "error": _("Kural bulunamadı")}
	frappe.get_doc("ECA Rule", rule_name).check_permission("read")

	rows = frappe.get_all(
		"Version",
		filters={"ref_doctype": "ECA Rule", "docname": rule_name},
		fields=["name", "owner", "creation", "data"],
		order_by="creation desc",
		limit_page_length=50,
	)
	versions = [
		{
			"version": r["name"],
			"modified": r["creation"],
			"modified_by": r["owner"],
			"changes": _summarize_version_changes(r.get("data")),
		}
		for r in rows
	]
	return {"versions": versions, "error": None}


@frappe.whitelist()
def restore_rule_version(rule_name: str, version_name: str) -> dict:
	"""Bir ECA Rule'u seçilen Version'daki eski alan değerlerine geri yükler.

	Frappe Version.data sadece DELTA tutar (tam snapshot değil); bu yüzden alan-
	bazlı revert uygulanır: seçilen versiyondaki `changed` listesinin OLD değerleri
	kurala geri yazılır + save (track_changes yeni bir version yaratır, audit
	korunur). Admin guard + audit log.

	Returns:
	    {"ok": bool, "name": str, "reverted_fields": [str], "error": str | None}
	"""
	import json

	frappe.only_for(["System Manager", "Marketplace Admin"])

	rule_name = (rule_name or "").strip()
	version_name = (version_name or "").strip()
	if not rule_name or not frappe.db.exists("ECA Rule", rule_name):
		return {"ok": False, "name": rule_name, "reverted_fields": [], "error": _("Kural bulunamadı")}
	if not version_name or not frappe.db.exists("Version", version_name):
		return {"ok": False, "name": rule_name, "reverted_fields": [], "error": _("Versiyon bulunamadı")}

	rule = frappe.get_doc("ECA Rule", rule_name)
	rule.check_permission("write")

	version = frappe.get_doc("Version", version_name)
	if version.ref_doctype != "ECA Rule" or version.docname != rule_name:
		return {
			"ok": False,
			"name": rule_name,
			"reverted_fields": [],
			"error": _("Versiyon bu kurala ait değil"),
		}

	try:
		data = json.loads(version.data or "{}")
	except (ValueError, TypeError):
		return {
			"ok": False,
			"name": rule_name,
			"reverted_fields": [],
			"error": _("Versiyon verisi çözümlenemedi"),
		}

	reverted: list[str] = []
	meta = frappe.get_meta("ECA Rule")
	for row in data.get("changed") or []:
		if len(row) < 3:
			continue
		fieldname, old_value = row[0], row[1]
		# Child tablo / okunamayan alanları atla — yalnız gerçek skaler alanları geri yaz.
		df = meta.get_field(fieldname)
		if not df or df.fieldtype in ("Table", "Table MultiSelect"):
			continue
		rule.set(fieldname, old_value)
		reverted.append(fieldname)

	if not reverted:
		return {"ok": False, "name": rule_name, "reverted_fields": [], "error": _("Geri yüklenecek alan yok")}

	rule.save()

	# Audit: kim/hangi kural/hangi versiyon/hangi alanlar geri yüklendi.
	frappe.logger("eca_audit").warning(
		f"rule version restored by {frappe.session.user} at {frappe.utils.now()} "
		f"rule={rule_name} version={version_name} fields={reverted}"
	)
	frappe.log_error(
		message=(
			f"user={frappe.session.user} when={frappe.utils.now()} rule={rule_name} "
			f"version={version_name} reverted_fields={reverted}"
		),
		title="ECA Rule version restored",
	)

	return {"ok": True, "name": rule.name, "reverted_fields": reverted, "error": None}

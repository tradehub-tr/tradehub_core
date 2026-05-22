"""ECA Rule yönetim API endpoint'leri — frontend tüketir.

Yöntemler:
- test_rule_with_sample: condition'ı sandbox'ta dene (sample doc dict ile)
- get_rule_log: ECA Rule Log audit kayıtlarını listele (filtre destekli)
- get_my_rules: oturum açan satıcının kendi Per-Seller kurallarını döner
"""

import frappe


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

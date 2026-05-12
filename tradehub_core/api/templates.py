"""Faz 4 — Category Review Template API.

Bir Listing'in Product Category'sine bağlı şablon varsa, yorum formuna
ek sorular gelir. Cevaplar Listing Review.category_template_answers
(JSON cache) içine kaydedilir.

Default 4 şablon migration patch ile seed edilir:
  - Tekstil Şablonu
  - Makine/Ekipman Şablonu
  - Hammadde/Kimya Şablonu
  - Gıda Şablonu
"""

from __future__ import annotations

import json

import frappe
from frappe import _


def _ensure_logged_in():
	if frappe.session.user == "Guest":
		frappe.throw(_("Giriş yapın"), frappe.AuthenticationError)


@frappe.whitelist(allow_guest=True)
def get_category_template(category: str | None = None, listing: str | None = None):
	"""Bir kategori veya listing için aktif şablonu döner.

	listing verilirse, listing'in product_category'sinden çözer.
	"""
	if not category and listing:
		category = frappe.db.get_value("Listing", listing, "product_category")
	if not category:
		return {"template": None, "questions": []}

	tpl = frappe.db.get_value("Category Review Template", {"category": category, "is_active": 1}, "name")
	if not tpl:
		return {"template": None, "questions": []}

	doc = frappe.get_doc("Category Review Template", tpl)
	questions = [
		{
			"key": q.key,
			"label": q.label,
			"field_type": q.field_type,
			"required": bool(q.required),
		}
		for q in (doc.extra_questions or [])
	]
	return {"template": doc.name, "questions": questions}


@frappe.whitelist()
def submit_template_answers(review: str, answers):
	"""Bir Listing Review için şablon cevaplarını kaydeder."""
	_ensure_logged_in()
	if not review or not frappe.db.exists("Listing Review", review):
		frappe.throw(_("Yorum bulunamadı"), frappe.DoesNotExistError)

	if isinstance(answers, str):
		try:
			answers = json.loads(answers)
		except (ValueError, TypeError):
			frappe.throw(_("Geçersiz JSON"))
	if not isinstance(answers, dict):
		frappe.throw(_("Cevaplar dict formatında olmalı"))

	# Yetki kontrolü: yalnız review sahibi (veya admin)
	rev_user = frappe.db.get_value("Listing Review", review, "reviewer_user")
	user = frappe.session.user
	if user != rev_user and user != "Administrator":
		from tradehub_core.api.review import _is_admin

		if not _is_admin():
			frappe.throw(_("Sadece yorumun sahibi cevap girebilir"), frappe.PermissionError)

	# Şablon doğrulama
	listing = frappe.db.get_value("Listing Review", review, "listing")
	tpl_data = get_category_template(listing=listing)
	if not tpl_data["template"]:
		frappe.throw(_("Bu kategori için aktif şablon yok"))
	valid_keys = {q["key"] for q in tpl_data["questions"]}
	required_keys = {q["key"] for q in tpl_data["questions"] if q["required"]}
	filtered = {k: v for k, v in answers.items() if k in valid_keys}
	missing = required_keys - filtered.keys()
	if missing:
		frappe.throw(_("Eksik zorunlu alanlar: {0}").format(", ".join(missing)))

	frappe.db.set_value(
		"Listing Review",
		review,
		"category_template_answers",
		json.dumps(filtered, ensure_ascii=False),
		update_modified=False,
	)
	frappe.db.commit()
	return {"success": True, "saved_keys": list(filtered.keys())}


@frappe.whitelist(allow_guest=True)
def get_template_answers(review: str):
	"""Listing Review.category_template_answers JSON'ını döndürür."""
	if not review or not frappe.db.exists("Listing Review", review):
		frappe.throw(_("Yorum bulunamadı"), frappe.DoesNotExistError)
	row = frappe.db.get_value(
		"Listing Review", review, ["category_template_answers", "listing"], as_dict=True
	)
	answers = {}
	if row.category_template_answers:
		try:
			answers = json.loads(row.category_template_answers)
		except (ValueError, TypeError):
			pass
	tpl = get_category_template(listing=row.listing)
	return {"answers": answers, "template": tpl.get("template"), "questions": tpl.get("questions", [])}


# ─────────────────────────────────────────────────────────────────────────────
# Default şablon seed (patch'ten çağrılır)
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_TEMPLATES = [
	{
		"template_name": "Tekstil Şablonu",
		"category": None,
		"is_active": 1,
		"questions": [
			{
				"key": "fabric_weight_match",
				"label": "Kumaş gramajı reklamla uyumlu mu?",
				"field_type": "Yes-No",
				"required": 0,
			},
			{
				"key": "color_consistency",
				"label": "Renk tonu tutarlılığı (1-5)",
				"field_type": "Rating",
				"required": 0,
			},
			{"key": "stitch_quality", "label": "Dikiş kalitesi (1-5)", "field_type": "Rating", "required": 0},
		],
	},
	{
		"template_name": "Makine Ekipman Şablonu",
		"category": None,
		"is_active": 1,
		"questions": [
			{
				"key": "install_ease",
				"label": "Kurulum kolaylığı (1-5)",
				"field_type": "Rating",
				"required": 0,
			},
			{
				"key": "spare_parts_access",
				"label": "Yedek parça erişimi nasıl?",
				"field_type": "Yes-No",
				"required": 0,
			},
			{
				"key": "training_provided",
				"label": "Eğitim sağlandı mı?",
				"field_type": "Yes-No",
				"required": 0,
			},
		],
	},
	{
		"template_name": "Hammadde Kimya Şablonu",
		"category": None,
		"is_active": 1,
		"questions": [
			{
				"key": "purity_test",
				"label": "Saflık (lab test sonucu)",
				"field_type": "Free-Text",
				"required": 0,
			},
			{
				"key": "msds_complete",
				"label": "MSDS/SDS belgesi tam mı?",
				"field_type": "Yes-No",
				"required": 0,
			},
			{
				"key": "storage_condition",
				"label": "Depo koşulları uygun mu?",
				"field_type": "Yes-No",
				"required": 0,
			},
		],
	},
	{
		"template_name": "Gıda Şablonu",
		"category": None,
		"is_active": 1,
		"questions": [
			{
				"key": "halal_kosher",
				"label": "Halal/Kosher/ISO 22000 sertifikası var mı?",
				"field_type": "Yes-No",
				"required": 0,
			},
			{
				"key": "shelf_life_match",
				"label": "Raf ömrü uyumu (1-5)",
				"field_type": "Rating",
				"required": 0,
			},
			{"key": "packaging_intact", "label": "Ambalaj bütünlüğü", "field_type": "Yes-No", "required": 0},
		],
	},
]


def seed_default_templates():
	for tpl in DEFAULT_TEMPLATES:
		if frappe.db.exists("Category Review Template", tpl["template_name"]):
			continue
		doc = frappe.new_doc("Category Review Template")
		doc.template_name = tpl["template_name"]
		doc.category = tpl.get("category")
		doc.is_active = tpl["is_active"]
		for q in tpl["questions"]:
			doc.append("extra_questions", q)
		try:
			doc.insert(ignore_permissions=True, ignore_mandatory=True)
		except Exception:
			frappe.log_error(title="seed_template_failed", message=f"template={tpl['template_name']}")

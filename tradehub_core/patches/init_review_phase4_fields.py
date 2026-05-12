"""Faz 4 — yeni alanları initialize eder + default kategori şablonlarını seed.

Şunları yapar:
  - Listing.question_count baseline 0
  - Listing Review yeni cache alanları (current_stage default 'Initial',
    is_translation_available default 0)
  - 4 default Category Review Template (Tekstil/Makine/Hammadde/Gıda)
"""

import frappe


def execute():
	_init_listing_fields()
	_init_review_fields()
	_seed_default_templates()
	frappe.db.commit()


def _init_listing_fields():
	cols = frappe.db.get_table_columns("Listing")
	if "question_count" in cols:
		frappe.db.sql("UPDATE `tabListing` SET question_count = COALESCE(question_count, 0)")


def _init_review_fields():
	if not frappe.db.table_exists("tabListing Review"):
		return
	cols = frappe.db.get_table_columns("Listing Review")
	updates = []
	if "current_stage" in cols:
		updates.append("current_stage = COALESCE(NULLIF(current_stage, ''), 'Initial')")
	if "is_translation_available" in cols:
		updates.append("is_translation_available = COALESCE(is_translation_available, 0)")
	if "long_term_score" in cols:
		updates.append("long_term_score = COALESCE(long_term_score, 0)")
	if updates:
		frappe.db.sql("UPDATE `tabListing Review` SET " + ", ".join(updates))


def _seed_default_templates():
	if not frappe.db.table_exists("tabCategory Review Template"):
		return
	try:
		from tradehub_core.api.templates import seed_default_templates

		seed_default_templates()
	except Exception:
		frappe.log_error(
			title="phase4_template_seed_failed",
			message="Default templates seed failed",
		)

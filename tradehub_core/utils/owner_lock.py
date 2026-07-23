# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 1.5 — Owner dokunulmazlık (banka/vergi değişiklik kilidi).

Karar dosyası §6.1'e göre aşağıdaki işlemler **yalnızca** Mağaza Sahibi
(Seller Owner + tradehub_is_owner=1) tarafından yapılabilir:
  - banka bilgisi değiştirme
  - vergi numarası değiştirme
  - hesap kapatma
  - yeni Owner atama
  - subscription plan değiştirme
  - 2FA kapatma

Co-Owner bile bu işlemleri yapamaz. Bu modül `Admin Seller Profile.validate`
hook'una bağlanır ve hassas alan değişikliklerini Owner-only zorlar.

Detay: docs/yetki/01-karar-dosyasi.md §6.1
"""

from __future__ import annotations

import frappe
from frappe import _

# Owner-only alanlar (değiştirilirse Owner olmayı gerektirir)
_OWNER_ONLY_FIELDS: frozenset[str] = frozenset(
	{
		"iban",
		"bank_name",
		"bank_account_holder",
		"tax_id",
	}
)


def _caller_is_owner_of(tenant: str) -> bool:
	"""Caller, verilen tenant'ın Owner'ı mı?

	Owner kriterleri:
	  - System Manager (her zaman bypass)
	  - tradehub_is_owner=1 + Seller Owner rolü + tradehub_tenant == tenant
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		return False

	roles = set(frappe.get_roles(user))
	if "System Manager" in roles or user == "Administrator":
		return True

	if "Seller Owner" not in roles:
		return False

	user_tenant, is_owner = frappe.db.get_value("User", user, ["tradehub_tenant", "tradehub_is_owner"]) or (
		None,
		0,
	)

	return bool(is_owner) and user_tenant == tenant


def enforce_owner_only_fields(doc, method=None) -> None:
	"""Admin Seller Profile.validate hook — banka/vergi değişiklikleri Owner-only.

	Davranış:
	  - DB'den önceki değer alınır, mevcut değerle karşılaştırılır
	  - Eğer _OWNER_ONLY_FIELDS'ten biri değişmiş VE caller Owner değil →
	    PermissionError + HIGH severity audit log
	"""
	# Yeni doc → autoset (Co-Owner ilk kez doldurabilir; lock değişikliği kapsar)
	if doc.is_new() or not doc.name:
		return

	tenant = doc.name  # Admin Seller Profile.name = seller_code = tenant
	if _caller_is_owner_of(tenant):
		return

	# DB'den önceki değerleri al
	try:
		db_doc = frappe.db.get_value(
			"Admin Seller Profile",
			doc.name,
			list(_OWNER_ONLY_FIELDS),
			as_dict=True,
		)
	except Exception:
		frappe.log_error("Owner-only field DB fetch failed", "owner_lock")
		return

	if not db_doc:
		return

	changed_fields = []
	for field in _OWNER_ONLY_FIELDS:
		old_value = db_doc.get(field)
		new_value = doc.get(field)
		# None ↔ "" eşdeğer kabul (Frappe boş Data field None döner)
		if (old_value or None) != (new_value or None):
			changed_fields.append(field)

	if not changed_fields:
		return

	# HIGH severity audit log
	try:
		from tradehub_core.audit import (
			DECISION_DENY,
			LAYER_L2,
			SEVERITY_HIGH,
			log_decision,
		)

		log_decision(
			action="admin_seller_profile.owner_only_field_change_attempt",
			decision=DECISION_DENY,
			rule_id="auth.owner_only_field",
			layer=LAYER_L2,
			object_doctype="Admin Seller Profile",
			object_name=doc.name,
			tenant=tenant,
			severity=SEVERITY_HIGH,
			context={"attempted_fields": changed_fields},
		)
	except Exception:
		frappe.log_error("Owner-only field change audit log failed", "owner_lock")
		pass

	frappe.throw(
		_(
			"Bu alan(lar) yalnızca Mağaza Sahibi (Owner) tarafından değiştirilebilir: {0}. "
			"Co-Owner bile bu yetkiye sahip değildir."
		).format(", ".join(sorted(changed_fields))),
		frappe.PermissionError,
	)

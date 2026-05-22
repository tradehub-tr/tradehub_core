# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 1.4 — User doctype hook'ları (audit için).

Frappe User doctype'ın `on_update` event'inde rol/profile değişikliği
tespit edilip otomatik Role Change Log yazılır.

Detay: docs/yetki/03-doctype-sablonlari.md §7
"""

from __future__ import annotations

import frappe

from tradehub_core.audit.log import log_role_change


def on_user_update(doc, method=None) -> None:
	"""User on_update hook: rol/profile değişikliklerini log'la.

	Frappe doc.has_value_changed('roles') doğrudan child table değişiklikleri
	tespit etmez; karşılaştırma için DB snapshot alıyoruz.

	Best-effort: hata olursa user save flow'unu bozmaz.
	"""
	try:
		# Yeni doc ise — invite/create event'i
		if doc.flags.get("from_insert"):
			log_role_change(
				target_user=doc.name,
				change_type="invite",
				after_roles=[r.role for r in (doc.roles or [])],
				after_role_profiles=[doc.role_profile_name] if doc.get("role_profile_name") else [],
				reason="user_created",
			)
			return

		# Mevcut doc — rol değişikliği var mı?
		current_roles = sorted(r.role for r in (doc.roles or []))
		db_roles = sorted(
			frappe.get_all("Has Role", filters={"parent": doc.name}, pluck="role")
		)

		# enabled flag değişimi
		current_enabled = bool(doc.enabled)
		db_enabled = bool(frappe.db.get_value("User", doc.name, "enabled"))

		if current_enabled != db_enabled:
			log_role_change(
				target_user=doc.name,
				change_type="activate" if current_enabled else "deactivate",
				before_roles=db_roles,
				after_roles=current_roles,
				reason=f"enabled: {db_enabled} → {current_enabled}",
			)
			return

		# Rol kümesi değişti mi?
		if set(current_roles) != set(db_roles):
			added = sorted(set(current_roles) - set(db_roles))
			removed = sorted(set(db_roles) - set(current_roles))
			if added or removed:
				log_role_change(
					target_user=doc.name,
					change_type="role_assign" if added else "role_remove",
					before_roles=db_roles,
					after_roles=current_roles,
					reason=f"added={added}, removed={removed}",
				)
	except Exception as exc:
		try:
			frappe.log_error(
				f"on_user_update audit hook başarısız: user={doc.name}: {exc}",
				"audit.user_hooks",
			)
		except Exception:
			pass

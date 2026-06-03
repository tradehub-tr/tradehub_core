"""Faz F.2 — TH Module Registry `is_protected=1` seed.

`module_navigation_spec.py` 6 modülde `is_protected: True` etiketi taşıyor:
  - seller.dashboard (section)
  - seller.dashboard.main.home (item, /dashboard)
  - seller.store (section)
  - seller.store.profil.profilim (item, User Profile)
  - admin.system (section)
  - admin.system.yetki.console (item, /permission-console)

Ancak `v15_6_2_seed_module_registry` patch'i bu flag'i DB'ye geçirmemiş —
sonuç: `update_module_policy` korumalı modül için `mode=hidden` engelini hiç
tetiklemiyor (DB'de `is_protected=1` kayıt yok). Bu patch flag'leri uygular.

Idempotent: flag zaten 1 ise skip.
"""

from __future__ import annotations

import frappe


def execute() -> dict:
	from tradehub_core.setup.module_navigation_spec import get_all_modules

	updated: list[str] = []
	skipped_already: list[str] = []
	skipped_missing: list[str] = []

	for spec in get_all_modules():
		if not spec.get("is_protected"):
			continue
		module_key = spec["key"]
		if not frappe.db.exists("TH Module Registry", module_key):
			skipped_missing.append(module_key)
			continue
		current = frappe.db.get_value("TH Module Registry", module_key, "is_protected")
		if current:
			skipped_already.append(module_key)
			continue
		frappe.db.set_value(
			"TH Module Registry",
			module_key,
			"is_protected",
			1,
			update_modified=False,
		)
		updated.append(module_key)

	frappe.db.commit()

	# Cache flush — resolver protected flag'i okur
	try:
		from tradehub_core.utils.permission_resolver import flush_all_cache

		flush_all_cache()
	except Exception:
		frappe.log_error("cache flush failed in v15_6_16", "patch")

	return {
		"updated": updated,
		"skipped_already_protected": skipped_already,
		"skipped_missing_registry": skipped_missing,
	}

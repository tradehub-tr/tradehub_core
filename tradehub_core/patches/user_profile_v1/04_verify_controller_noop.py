"""Patch 4: Controller no-op stratejisi doğrulaması (Bloker 2 Hibrit C+B).
Buyer/Seller Profile controller'larının Sprint 2 kod PR'ında boşaltıldığını teyit eder.
Eğer boşaltılmamışsa migration durur (fail-safe) — Bloker 2 çözümü."""

import inspect

import frappe


def execute():
	from tradehub_core.tradehub_core.doctype.buyer_profile.buyer_profile import BuyerProfile
	from tradehub_core.tradehub_core.doctype.seller_profile.seller_profile import SellerProfile

	# Buyer Profile boşaltılmış olmalı (Sprint 2 kod PR kapsamı)
	bp_src = inspect.getsource(BuyerProfile)
	# `frappe.db.set_value` veya `_sync_*` aktif olmamalı
	bp_has_active_sync = any(
		pattern in bp_src
		for pattern in ['frappe.db.set_value("User"', 'frappe.db.set_value("Seller Profile"', "_sync_status"]
	)
	if bp_has_active_sync:
		frappe.throw(
			"Patch 4 FAIL: buyer_profile.py controller hook'ları henüz boşaltılmamış. "
			"Sprint 2 kod PR'ında BuyerProfile sınıfı içindeki sync metodları silinmeli."
		)

	sp_src = inspect.getsource(SellerProfile)
	sp_has_active_sync = any(
		pattern in sp_src
		for pattern in ["_sync_to_related_docs", "_sync_status", 'frappe.db.set_value("Buyer Profile"']
	)
	if sp_has_active_sync:
		frappe.throw("Patch 4 FAIL: seller_profile.py controller hook'ları henüz boşaltılmamış.")

	frappe.log_error(
		title="Patch 4: Controller no-op verified",
		message="Buyer Profile + Seller Profile controller'ları boş, migration güvenli.",
	)

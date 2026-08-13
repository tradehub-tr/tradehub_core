# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-039: Logistics Settings.default_desi_divisor backfill (idempotent).

Alan migrate sync ile eklenir; bu patch yalnız boş/0 kalan değeri
Türkiye standardı 3000 ile doldurur — dolu değere dokunmaz.
"""

from __future__ import annotations

import frappe

from tradehub_core.logistics.services.desi import DEFAULT_DESI_DIVISOR


def execute() -> None:
	"""default_desi_divisor boşsa DEFAULT_DESI_DIVISOR (3000) yaz."""
	# Yeni alan henüz sync edilmemiş olabilir (patch migrate içinde erken koşarsa).
	frappe.reload_doc("tradehub_core", "doctype", "logistics_settings")

	current = frappe.db.get_single_value("Logistics Settings", "default_desi_divisor")
	if not current:  # boş / 0 / None → varsayılan
		frappe.db.set_single_value("Logistics Settings", "default_desi_divisor", DEFAULT_DESI_DIVISOR)

	frappe.db.commit()

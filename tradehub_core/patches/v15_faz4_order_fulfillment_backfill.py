# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-056: Order.fulfillment_status backfill (idempotent).

fulfillment_status + shipment_count alanları migrate sync ile eklenir;
bu patch yalnız boş kalan fulfillment_status değerlerini varsayılan
"Unfulfilled" ile doldurur. Dolu değerlere dokunmaz — tekrar çalışması
güvenlidir (WHERE koşulu boş satır kalmayınca no-op olur).
"""

from __future__ import annotations

import frappe


def execute() -> None:
	"""fulfillment_status boş/NULL olan Order kayıtlarını Unfulfilled yap."""
	# Yeni alan henüz sync edilmemiş olabilir (patch migrate içinde erken koşarsa).
	frappe.reload_doc("tradehub_core", "doctype", "order")

	if not frappe.db.has_column("Order", "fulfillment_status"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabOrder`
		SET fulfillment_status = %s
		WHERE fulfillment_status IS NULL OR fulfillment_status = ''
		""",
		("Unfulfilled",),
	)
	frappe.db.commit()

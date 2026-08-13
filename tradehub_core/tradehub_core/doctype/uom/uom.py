# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

# ERPNext'ten devralındı (Faz 4 — erpnext decouple): şema ERPNext'in UOM'u ile
# birebir aynı (uom_name / enabled / must_be_whole_number, autoname field:uom_name)
# ki mevcut 239 kayıt ve Link referansları (RFQ.unit, Listing.stock_uom) bozulmasın.

from frappe.model.document import Document


class UOM(Document):
	pass

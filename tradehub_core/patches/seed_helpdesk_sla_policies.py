# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Seed default Helpdesk SLA Policy records — priority bazlı 4 kayıt.

Süreler endüstri standardına yakın değerlerdir; admin Helpdesk SLA Policy
doctype üzerinden override edebilir. Idempotent: priority unique key.
"""

import frappe

DEFAULTS = [
	{
		"priority": "Urgent",
		"first_response_minutes": 30,  # 30dk
		"resolution_minutes": 240,  # 4 saat
		"description": "Kritik durumlar — derhal müdahale.",
	},
	{
		"priority": "High",
		"first_response_minutes": 120,  # 2 saat
		"resolution_minutes": 480,  # 8 saat (1 iş günü)
		"description": "Yüksek öncelikli destek talepleri.",
	},
	{
		"priority": "Medium",
		"first_response_minutes": 480,  # 8 saat
		"resolution_minutes": 2880,  # 2 iş günü (48 saat)
		"description": "Standart destek talepleri.",
	},
	{
		"priority": "Low",
		"first_response_minutes": 1440,  # 24 saat
		"resolution_minutes": 5760,  # 4 iş günü
		"description": "Düşük öncelikli, beklenebilir talepler.",
	},
]


def execute():
	for spec in DEFAULTS:
		if frappe.db.exists("Helpdesk SLA Policy", spec["priority"]):
			continue
		doc = frappe.new_doc("Helpdesk SLA Policy")
		doc.is_active = 1
		for k, v in spec.items():
			doc.set(k, v)
		doc.insert(ignore_permissions=True)
	frappe.db.commit()

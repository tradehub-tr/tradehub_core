# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 3.2 — Default PII Field Policy seed.

Idempotent: aynı (ref_doctype, fieldname) varsa atlanır.

Varsayılan matrisi `_DEFAULT_POLICIES` listesindeki kayıtlardan üretir.
Tenant'lar UI'den override edebilir.
"""

from __future__ import annotations

import frappe

# Format: (ref_doctype, fieldname, category, permlevel, rules)
# rules = list of (jurisdiction, mask_strategy, cross_border_block, require_consent)
_DEFAULT_POLICIES = [
	# Identity — TC kimlik no (KVKK strict, GDPR cross-border block)
	(
		"User Profile",
		"tc_no",
		"identity",
		2,
		[
			("KVKK", "last_4", 0, 0),
			("GDPR", "block", 1, 0),
			("MENA", "full", 0, 0),
			("CIS", "full", 0, 0),
			("OTHER", "full", 0, 0),
		],
	),
	# Identity — Pasaport
	(
		"User Profile",
		"passport_no",
		"identity",
		2,
		[
			("KVKK", "last_4", 0, 0),
			("GDPR", "last_4", 0, 0),
			("MENA", "last_4", 0, 0),
			("CIS", "last_4", 0, 0),
			("OTHER", "last_4", 0, 0),
		],
	),
	# Financial — IBAN (her yerde last_4)
	(
		"User Profile",
		"iban",
		"financial",
		2,
		[
			("KVKK", "iban", 0, 0),
			("GDPR", "iban", 0, 0),
			("MENA", "iban", 0, 0),
			("CIS", "iban", 0, 0),
			("OTHER", "iban", 0, 0),
		],
	),
	# Contact — Telefon
	(
		"User Profile",
		"phone",
		"contact",
		1,
		[
			("KVKK", "last_4", 0, 0),
			("GDPR", "last_4", 0, 0),
			("MENA", "last_4", 0, 0),
			("CIS", "last_4", 0, 0),
			("OTHER", "none", 0, 0),
		],
	),
	# Contact — Email
	(
		"User Profile",
		"email",
		"contact",
		1,
		[
			("KVKK", "email", 0, 0),
			("GDPR", "email", 0, 0),
			("MENA", "email", 0, 0),
			("CIS", "email", 0, 0),
			("OTHER", "none", 0, 0),
		],
	),
	# Health — sağlık bilgisi (GDPR Article 9 — özel kategori, cross-border block)
	(
		"User Profile",
		"medical_info",
		"health",
		3,
		[
			("KVKK", "block", 0, 1),
			("GDPR", "block", 1, 1),
			("MENA", "full", 0, 0),
			("CIS", "full", 0, 0),
			("OTHER", "full", 0, 0),
		],
	),
]


def execute() -> None:
	if not frappe.db.exists("DocType", "PII Field Policy"):
		# Doctype daha migrate edilmemiş — bench migrate sıralaması bunu çözecek
		return

	for ref_doctype, fieldname, category, permlevel, rules in _DEFAULT_POLICIES:
		existing = frappe.db.get_value(
			"PII Field Policy",
			{"ref_doctype": ref_doctype, "fieldname": fieldname},
			"name",
		)
		if existing:
			continue

		doc = frappe.new_doc("PII Field Policy")
		doc.ref_doctype = ref_doctype
		doc.fieldname = fieldname
		doc.pii_category = category
		doc.permlevel = permlevel
		doc.is_active = 1
		doc.legal_basis = "FAZ 3.2 default seed"

		for jurisdiction, strategy, cross_border, require_consent in rules:
			doc.append(
				"jurisdiction_rules",
				{
					"jurisdiction": jurisdiction,
					"mask_strategy": strategy,
					"cross_border_block": cross_border,
					"require_consent": require_consent,
				},
			)

		doc.insert(ignore_permissions=True)

	frappe.db.commit()

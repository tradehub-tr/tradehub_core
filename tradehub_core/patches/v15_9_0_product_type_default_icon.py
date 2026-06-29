"""Her Product Type'a varsayılan ikon ata.

"İkon Sınıfı" (icon_class) alanı form'dan gizlendi (doctype JSON: hidden=1,
default="package"). Yeni kayıtlar default'u alır; bu patch mevcut kayıtlardan
icon_class'ı boş/NULL olanları "package" ile doldurur. Özel değerler (ör.
ELECTRONICS=cpu) korunur.

İdempotent: zaten dolu olanları atlar.
"""

from __future__ import annotations

import frappe

_DEFAULT_ICON = "package"


def execute() -> dict:
	rows = frappe.get_all(
		"Product Type",
		filters={"icon_class": ["in", [None, ""]]},
		pluck="name",
	)
	for name in rows:
		frappe.db.set_value("Product Type", name, "icon_class", _DEFAULT_ICON, update_modified=False)

	frappe.db.commit()
	return {"updated": rows}

"""FAZ 9.7 — Admin Seller Profile'da beslenemeyen performans alanlarını gizle.

Sorun:
  Performans sekmesindeki health_score (default 100) ve on_time_delivery
  (default 0) alanlarını besleyen hiçbir kod yok — admin'e gerçekmiş gibi
  görünen sahte değerler gösteriliyordu. health_score için satıcı skor motoru
  yok; on_time_delivery için Order'da teslimat-tarihi verisi yok.

Çözüm:
  Bu iki alanı Property Setter ile `hidden=1` yap. DocType JSON'ı değiştirmeden
  runtime override ekler (panelin meta'sına yansır). İdempotent: make_property_setter
  aynı (doctype, field, property) için var olan setter'ı günceller.

  Diğer performans alanları (total_orders, score_grade, response_rate,
  response_time) v15_9_8 ile gerçek veriden beslenir — onlar gizlenmez.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

_HIDE = ["health_score", "on_time_delivery"]


def execute() -> None:
	if not frappe.db.exists("DocType", "Admin Seller Profile"):
		return
	for fieldname in _HIDE:
		if not frappe.db.exists("DocField", {"parent": "Admin Seller Profile", "fieldname": fieldname}):
			continue
		make_property_setter(
			doctype="Admin Seller Profile",
			fieldname=fieldname,
			property="hidden",
			value="1",
			property_type="Check",
			validate_fields_for_doctype=False,
		)
	frappe.db.commit()

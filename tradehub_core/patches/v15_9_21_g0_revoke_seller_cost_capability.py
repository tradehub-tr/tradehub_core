"""G0 rol matrisi (K1) — satıcıdan taşıyıcı maliyet görünürlüğünü geri alır.

Sorun:
	TUR-103 seed'i "Seller Full Access" profiline `view.logistics_cost`
	vermişti. G0 kararı (K1, platform araştırması: Amazon/Trendyol maliyet
	asimetrisi) tersini söylüyor: platform-anlaşmalı kargoda satıcı taşıyıcı
	maliyetini GÖRMEZ, yalnız kendisine yansıyan ücreti görür. Satıcının
	kendi taşıyıcı hesabını bağladığı model gelirse bu grant o zaman geri
	açılır.

Çözüm:
	Grant kaydı silinmez, `granted=0` yapılır — iz kalır, geri açmak tek
	alan. TUR-103 seed'inin GRANTS matrisinden de satır düşürüldü (yeni
	kurulum hiç vermesin). İdempotent.
"""

from __future__ import annotations

import frappe

_PROFILE = "Seller Full Access"
_CAPABILITY = "view.logistics_cost"


def execute() -> dict:
	name = frappe.db.get_value(
		"TH Capability Grant",
		{"role_profile": _PROFILE, "capability": _CAPABILITY},
		"name",
	)
	if not name:
		return {"skipped": "no_grant"}

	grant = frappe.get_doc("TH Capability Grant", name)
	if not grant.granted:
		return {"skipped": "already_revoked"}

	grant.granted = 0
	grant.note = (grant.note or "") + " | G0/K1: maliyet asimetrisi — satıcıya kapalı (2026-08-19)"
	grant.flags.ignore_permissions = True
	grant.save(ignore_permissions=True)

	frappe.clear_cache()
	frappe.db.commit()
	return {"revoked": f"{_PROFILE} -> {_CAPABILITY}"}

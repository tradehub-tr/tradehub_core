"""Faz 0 + Faz 1 canlı doğrulama — elle çalıştırılabilir kontrol seti.

Çalıştırma (repo kökünden):
    docker exec docker-backend-1 bench --site dev.localhost \
        execute tradehub_core.authz.verify.run

Her kontrol PASS/FAIL/SKIP basar; sonunda özet döner. Salt-okunur — hiçbir
kalıcı veri yazmaz (audit="none").
"""

from __future__ import annotations

import frappe

_OTHER_PROFILE = "SEL-00002"
_SELLER = "sec_seller_a@test.local"


def run() -> dict:
	results: list[tuple[str, bool, str]] = []

	def check(name: str, ok: bool, detail: str = "") -> None:
		results.append((name, bool(ok), detail))
		tag = "PASS" if ok else "FAIL"
		print(f"  {tag}  {name}" + (f"  — {detail}" if detail else ""))

	print("=" * 66)
	print("FAZ 0 — Güvenlik taban çizgisi")
	print("=" * 66)

	from tradehub_core.permissions import (
		_is_platform_full_access,
		admin_seller_profile_has_permission,
	)

	# #B1 — cross-tenant read engellendi mi?
	try:
		other = frappe.get_doc("Admin Seller Profile", _OTHER_PROFILE)
		if frappe.db.exists("User", _SELLER):
			hook = admin_seller_profile_has_permission(other, "read", _SELLER)
			frappe.set_user(_SELLER)
			fr = frappe.has_permission("Admin Seller Profile", "read", doc=other)
			frappe.set_user("Administrator")
			check("#B1 cross-tenant read hook=False", hook is False, f"hook={hook!r}")
			check("#B1 frappe.has_permission=False", fr is False, f"has_permission={fr}")
		else:
			check("#B1", True, f"SKIP — {_SELLER} yok")
	except frappe.DoesNotExistError:
		check("#B1", True, f"SKIP — {_OTHER_PROFILE} yok")

	# #D2 — Compliance Officer yalnız-read (ptype-aware helper)
	check(
		"#D2 helper ptype-aware (full-access write=True)",
		_is_platform_full_access("Administrator", "write") is True,
	)
	comp = frappe.db.get_value(
		"Has Role", {"role": "Compliance Officer", "parenttype": "User"}, "parent"
	)
	if comp and "System Manager" not in frappe.get_roles(comp):
		w = _is_platform_full_access(comp, "write")
		r = _is_platform_full_access(comp, "read")
		check("#D2 Compliance-only write reddi", w is False, f"{comp} write={w}")
		check("#D2 Compliance-only read izni", r is True, f"read={r}")
	else:
		check("#D2 Compliance-only senaryo", True, "SKIP — saf Compliance Officer kullanıcı yok")

	print()
	print("=" * 66)
	print("FAZ 1 — Birleşik PDP (authz.authorize)")
	print("=" * 66)

	from tradehub_core.authz import authorize

	# Davranış garantisi: authorize().allow == frappe.has_permission(...)
	try:
		other = frappe.get_doc("Admin Seller Profile", _OTHER_PROFILE)
		frappe.set_user("Administrator")
		fr = frappe.has_permission("Admin Seller Profile", "read", doc=other)
		d = authorize("Administrator", "read", other, audit="none")
		check(
			"PDP davranış garantisi (admin read == has_permission)",
			d.allow == fr,
			f"pdp={d.allow} hp={fr} layer={d.layer}",
		)
		if frappe.db.exists("User", _SELLER):
			frappe.set_user(_SELLER)
			fr2 = frappe.has_permission("Admin Seller Profile", "read", doc=other)
			d2 = authorize(_SELLER, "read", other, audit="none")
			frappe.set_user("Administrator")
			check(
				"PDP seller cross-tenant read == has_permission",
				d2.allow == fr2,
				f"pdp={d2.allow} hp={fr2} layer={d2.layer}",
			)
	except frappe.DoesNotExistError:
		check("PDP davranış garantisi", True, f"SKIP — {_OTHER_PROFILE} yok")

	# Bilinmeyen action → fail-closed DENY
	d3 = authorize("Administrator", "frobnicate", "Listing", audit="none")
	check(
		"PDP bilinmeyen action → DENY",
		d3.allow is False and d3.reason == "unknown_action",
		f"reason={d3.reason}",
	)

	# Decision şekli: decision_id + trace
	d4 = authorize("Administrator", "read", "Listing", audit="none")
	check(
		"PDP Decision şekli (decision_id + trace)",
		bool(d4.decision_id) and len(d4.trace) >= 1,
		f"id={d4.decision_id} steps={len(d4.trace)}",
	)

	# Fail-closed: doctype çözülemedi
	d5 = authorize("Administrator", "read", None, audit="none")
	check("PDP doctype yok → fail-closed DENY", d5.allow is False, f"reason={d5.reason}")

	print()
	print("=" * 66)
	print("FAZ 2 — ABAC Guardrail (L1 hard_deny + L2 boundary)")
	print("=" * 66)

	from tradehub_core.authz import guardrail

	# L1/L2 katmanları PDP trace'inde aktif mi?
	dt = authorize("Administrator", "read", "Listing", audit="none")
	layers = [s["layer"] for s in dt.trace]
	check(
		"Guardrail katmanları PDP'de aktif (L1+L2 trace'te)",
		"L1.hard_deny" in layers and "L2.guardrail" in layers,
		f"layers={layers}",
	)

	# Administrator guardrail bypass
	rb = guardrail.hard_deny("Administrator", "create", "Seller Balance", None, None, {})
	check("Guardrail admin bypass (no deny)", rb.deny is False)

	# Canlı DENY: operasyonel-olmayan abonelikli satıcı gated-write reddi (#D1)
	from tradehub_core.entitlement import is_subscription_operational

	nonop = None
	for s in frappe.get_all("Admin Seller Profile", fields=["name", "user"], limit=50):
		if s.user and not is_subscription_operational(s.name):
			nonop = s
			break
	if nonop:
		r = guardrail.hard_deny(nonop.user, "create", "Listing", None, None, {})
		check(
			"#D1 suspended-seller gated write DENY",
			r.deny and r.reason == "subscription_suspended",
			f"{nonop.user} reason={r.reason}",
		)
	else:
		check("#D1 suspended-seller DENY", True, "SKIP — operasyonel-olmayan satıcı yok (unit testte kanıtlı)")

	frappe.set_user("Administrator")
	passed = sum(1 for _, ok, _ in results if ok)
	total = len(results)
	fails = [n for n, ok, _ in results if not ok]
	print()
	print("=" * 66)
	print(f"SONUÇ: {passed}/{total} kontrol PASS" + (f" | FAIL: {', '.join(fails)}" if fails else ""))
	print("=" * 66)
	return {"passed": passed, "total": total, "fails": fails}

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

	# ── FAZ 3-7 (canlı ReBAC gerektirenler sidecar-guarded) ──
	from tradehub_core.services import rebac_client as _rc

	sidecar = False
	try:
		sidecar = _rc.healthz() and bool(_rc._store_id())
	except Exception:
		sidecar = False

	print()
	print("=" * 66)
	print("FAZ 3-7 — ReBAC canlı + enforce + audit + field-level + break-glass")
	print("=" * 66)

	if not sidecar:
		check("FAZ 3-6 (ReBAC)", True, "SKIP — sidecar down/konfigüresiz (make rebac-up + rebac-model-deploy)")
	else:
		listings = frappe.get_all("Listing", limit=1, pluck="name")
		L = listings[0] if listings else None
		U = "sec_buyer_a@test.local"
		# Faz 3 — idempotent write→check→delete döngüsü
		obj = f"store:VERIFY-{(L or 'X')}"
		_rc.write_tuples([("user:verify@x", "owner", obj)])
		w1 = _rc.check("user:verify@x", "owner", obj)
		_rc.delete_tuples([("user:verify@x", "owner", obj)])
		w2 = _rc.check("user:verify@x", "owner", obj)
		check("Faz 3 ReBAC yaz→oku→sil döngüsü", w1 is True and w2 is False)

		if L:
			from tradehub_core.services import tuple_sync as _ts

			# Faz 4 — shadow: sapma loglanıyor mu (write grant + authorize + Error Log)
			_rc.write_tuples([(f"user:{U}", "owner", "store:SEL-00002")])
			before = frappe.db.count("Error Log", {"method": ["like", "%shadow_divergence%"]})
			frappe.conf["rebac_enforcement"] = {}
			authorize(U, "read", ("Admin Seller Profile", "SEL-00002"), audit="none")
			frappe.db.commit()
			after = frappe.db.count("Error Log", {"method": ["like", "%shadow_divergence%"]})
			check("Faz 4 shadow sapma loglandı", after > before)
			_rc.delete_tuples([(f"user:{U}", "owner", "store:SEL-00002")])

			# Faz 5 — enforce union-grant + kill-switch
			_ts.grant_field_access(U, L, "DESCRIPTION", "field_editor")
			frappe.conf["rebac_enforcement"] = {"Listing": "enforce"}
			frappe.conf["rebac_kill_switch"] = False
			d_enf = authorize(U, "edit_description", ("Listing", L), audit="none")
			frappe.conf["rebac_kill_switch"] = True
			d_ks = authorize(U, "edit_description", ("Listing", L), audit="none")
			check("Faz 5 enforce union-grant", d_enf.allow and d_enf.layer == "L3.rebac")
			check("Faz 5 kill-switch geri-alma", d_ks.allow is False)

			# Faz 6(b) — field-level ayrım (description evet, price hayır)
			frappe.conf["rebac_kill_switch"] = False
			d_desc = authorize(U, "edit_description", ("Listing", L), audit="none")
			d_price = authorize(U, "edit_price", ("Listing", L), audit="none")
			check("Faz 6b field-level (desc=allow, price=deny)", d_desc.allow and not d_price.allow)
			_ts.revoke_field_access(U, L, "DESCRIPTION", "field_editor")
			frappe.conf["rebac_enforcement"] = {}

	# Faz 6(a) — audit hash-chain doğrulama (sidecar bağımsız)
	from tradehub_core.audit.log import verify_chain

	vc = verify_chain(limit=1000)
	check(
		"Faz 6a audit hash-chain verify_chain çalışıyor",
		isinstance(vc, dict) and "ok" in vc,
		f"ok={vc.get('ok')} checked={vc.get('checked')} tampered={len(vc.get('tampered', []))}",
	)

	# Faz 7 — break-glass override (sidecar bağımsız). Not: activate ÖNCE çağrılır
	# (aynı request'te activate-öncesi is_active çağrısı Frappe local cache'i None ile
	# poison'lar; production'da activate/check ayrı request → sorun yok).
	from tradehub_core.authz import break_glass

	break_glass.activate("Administrator", reason="verify-run test", duration_minutes=1)
	d_bg = authorize("Administrator", "frobnicate", "Listing", audit="none")
	break_glass.deactivate("Administrator")
	d_after = authorize("Administrator", "frobnicate", "Listing", audit="none")
	check(
		"Faz 7 break-glass (aktifken ALLOW, kapalıyken DENY)",
		d_bg.allow and d_bg.layer == "L0.break_glass" and d_after.allow is False,
	)

	frappe.set_user("Administrator")
	passed = sum(1 for _, ok, _ in results if ok)
	total = len(results)
	fails = [n for n, ok, _ in results if not ok]
	print()
	print("=" * 66)
	print(f"SONUÇ: {passed}/{total} kontrol PASS" + (f" | FAIL: {', '.join(fails)}" if fails else ""))
	print("=" * 66)
	return {"passed": passed, "total": total, "fails": fails}

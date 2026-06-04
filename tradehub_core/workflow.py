"""Faz G.3 — Decision Pipeline orchestrator (scaffold).

Mevcut durum: 4-katmanlı yetki kontrolü (`L0 Entitlement → L1 Tenant →
L2 RBAC+ABAC+ReBAC → L3 PII permlevel`) **dağıtık** uygulanıyor:
- `permissions.py` hooks → L1 + L2 Frappe role
- `seller_capabilities.has_seller_capability` → L0 + L2 capability
- `rebac_client.check` → L2 ReBAC tuple
- `abac_context.evaluate_*` → L2 ABAC condition
- `pii_permlevel_setup` + `crm_masking` → L3
- `authorization_simulator.simulate` → DRY-RUN tüm 4 katman tek yerde

Bu fragmantasyon her endpoint'in kendi kontrol zincirini yazmasını
gerektiriyor — atlama veya yanlış sıra bypass yüzeyi doğuruyor. Bu modül
tek bir runtime API noktası sunacak:

    from tradehub_core.workflow import authorize

    decision = authorize(
        actor=frappe.session.user,
        action="order.approve",
        resource_type="Order",
        resource_name=order_name,
        context={...},
    )
    if decision["decision"] != "ALLOW":
        frappe.throw(decision["first_deny"]["detail"], frappe.PermissionError)

Şu an SCAFFOLD: `authorize` doğrudan `authorization_simulator.simulate`'i
çağırıyor (audit=True). İleride simulator'ı runtime için optimize edip
(snapshot cache, sample audit) buradan ayırabiliriz.

Tasarım kararı: orchestrator simulator ile aynı katman sırasını ve
fail-mode'u garanti eder; endpoint yazarı manuel `has_seller_capability +
check + abac` zincirini tekrar etmek zorunda kalmaz.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _


def authorize(
	actor: str | None,
	action: str,
	resource_type: str,
	resource_name: str | None = None,
	context: dict[str, Any] | None = None,
	audit: bool = True,
) -> dict[str, Any]:
	"""Tek noktadan 4-katman authorize.

	Args:
	    actor: Karar verilecek user (None → frappe.session.user)
	    action: 'order.approve', 'listing.publish', 'rfq.quote' vb.
	    resource_type: Frappe DocType (Order, Listing, Order Approval, ...)
	    resource_name: Spesifik kayıt (None → tip seviyesinde karar)
	    context: ABAC payload — amount, currency, region, request_hour, ...
	    audit: True → Authorization Decision Log kaydı (production default).
	        False sadece debug/dry-run için.

	Returns: `authorization_simulator.simulate`'in dict çıktısı.
	"""
	from tradehub_core.services import authorization_simulator

	actor = actor or frappe.session.user
	return authorization_simulator.simulate(
		actor=actor,
		action=action,
		resource_type=resource_type,
		resource_name=resource_name,
		context=context or {},
		audit=audit,
	)


def authorize_or_throw(
	actor: str | None,
	action: str,
	resource_type: str,
	resource_name: str | None = None,
	context: dict[str, Any] | None = None,
	audit: bool = True,
) -> dict[str, Any]:
	"""`authorize` + DENY/UNAVAILABLE durumunda `frappe.throw`.

	Returns the decision dict on ALLOW. Throws frappe.PermissionError on
	other outcomes — first_deny step'in `detail`'i mesaj olarak kullanılır.
	"""
	decision = authorize(
		actor=actor,
		action=action,
		resource_type=resource_type,
		resource_name=resource_name,
		context=context,
		audit=audit,
	)
	if decision.get("decision") != "ALLOW":
		first_deny = decision.get("first_deny") or {}
		message = first_deny.get("detail") or _("Bu işlem için yetkiniz yok ({0}/{1}).").format(
			action, resource_type
		)
		frappe.throw(message, frappe.PermissionError)
	return decision

"""FAZ 3.3 — Onaylı Tedarikçi (Supplier Whitelist) servisi.

Alıcı tenant'ın `Approved Supplier List`'lerini kullanarak order başlama
anında doğrulama yapar. Karar matrisi:

  - Tenant'ın hiç default list'i yok → ALLOW (geçiş aşaması)
  - Default list var, supplier listede değil → DENY
  - Supplier listede, amount limit aşıldı → DENY
  - Supplier listede, kategori filtresi var ve order item kategorisi dışında → DENY
  - Diğer → ALLOW

Audit: her doğrulama Authorization Decision Log'a yazılır (best-effort).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import frappe
from frappe import _

_CACHE_PREFIX = "supplier_whitelist:"
_CACHE_TTL = 300  # 5 dk

BYPASS_ROLES = frozenset({"System Manager", "Administrator", "Compliance Officer"})


@dataclass
class WhitelistDecision:
	decision: str  # ALLOW | DENY
	reason: str = ""
	matched_list: str | None = None
	matched_entry: dict[str, Any] | None = None


def get_default_list(tenant: str) -> dict | None:
	"""Return default Approved Supplier List for a tenant (cached)."""
	cache_key = f"{_CACHE_PREFIX}{tenant}"
	cached = frappe.cache.get_value(cache_key)
	if cached is not None:
		return cached if cached else None

	name = frappe.db.get_value(
		"Approved Supplier List",
		{"tenant": tenant, "is_default": 1, "is_active": 1},
		"name",
	)
	if not name:
		frappe.cache.set_value(cache_key, {}, expires_in_sec=_CACHE_TTL)
		return None

	doc = frappe.get_doc("Approved Supplier List", name)
	suppliers = []
	for s in doc.suppliers or []:
		if not getattr(s, "is_active", 1):
			continue
		suppliers.append(
			{
				"supplier": s.supplier,
				"min_order_amount": float(s.min_order_amount or 0),
				"max_order_amount": float(s.max_order_amount or 0),
				"allowed_categories": (s.allowed_categories or "").strip(),
			}
		)

	data = {
		"name": doc.name,
		"tenant": doc.tenant,
		"list_name": doc.list_name,
		"effective_from": str(doc.effective_from) if doc.effective_from else None,
		"effective_to": str(doc.effective_to) if doc.effective_to else None,
		"suppliers": suppliers,
	}
	frappe.cache.set_value(cache_key, data, expires_in_sec=_CACHE_TTL)
	return data


def invalidate_cache(tenant: str) -> None:
	frappe.cache.delete_value(f"{_CACHE_PREFIX}{tenant}")


def is_supplier_approved(
	tenant: str,
	supplier: str,
	amount: float = 0,
	categories: list[str] | None = None,
) -> WhitelistDecision:
	"""Pure decision function — does not audit. Suitable for UI preflight."""
	whitelist = get_default_list(tenant)
	if not whitelist:
		return WhitelistDecision(
			decision="ALLOW",
			reason="no_whitelist",
		)

	entry = next(
		(s for s in whitelist["suppliers"] if s["supplier"] == supplier),
		None,
	)
	if not entry:
		return WhitelistDecision(
			decision="DENY",
			reason=_("Supplier {0} bu tenant için onaylı listede değil").format(supplier),
			matched_list=whitelist["name"],
		)

	if entry["max_order_amount"] and amount > entry["max_order_amount"]:
		return WhitelistDecision(
			decision="DENY",
			reason=_("Order tutarı {0} izin verilen maksimumu aşıyor ({1})").format(
				amount, entry["max_order_amount"]
			),
			matched_list=whitelist["name"],
			matched_entry=entry,
		)

	if entry["min_order_amount"] and amount < entry["min_order_amount"]:
		return WhitelistDecision(
			decision="DENY",
			reason=_("Order tutarı {0} izin verilen minimumun altında ({1})").format(
				amount, entry["min_order_amount"]
			),
			matched_list=whitelist["name"],
			matched_entry=entry,
		)

	if entry["allowed_categories"] and categories:
		allowed = {c.strip() for c in entry["allowed_categories"].split(",") if c.strip()}
		offered = set(categories)
		if not offered & allowed:
			return WhitelistDecision(
				decision="DENY",
				reason=_("Order kategorileri ({0}) izin verilen listede yok ({1})").format(
					list(offered), list(allowed)
				),
				matched_list=whitelist["name"],
				matched_entry=entry,
			)

	return WhitelistDecision(
		decision="ALLOW",
		reason="approved",
		matched_list=whitelist["name"],
		matched_entry=entry,
	)


def validate_order_supplier(doc, method=None) -> None:
	"""Order.before_insert hook — block unapproved suppliers."""
	if doc.doctype != "Order":
		return

	user = frappe.session.user
	roles = set(frappe.get_roles(user)) if user else set()
	if roles & BYPASS_ROLES:
		_audit(user, doc, "ALLOW", "bypass_role", severity="LOW")
		return

	tenant = _resolve_buyer_tenant(doc)
	supplier = getattr(doc, "seller", None) or getattr(doc, "seller_profile", None)

	if not tenant or not supplier:
		return  # nothing to validate

	categories = _extract_order_categories(doc)
	amount = float(getattr(doc, "total", 0) or 0)

	decision = is_supplier_approved(tenant, supplier, amount, categories)

	if decision.decision == "DENY":
		_audit(
			user, doc, "DENY", decision.reason, severity="MEDIUM", rule_id="procurement.unapproved_supplier"
		)
		frappe.throw(decision.reason, exc=frappe.PermissionError)
	else:
		_audit(user, doc, "ALLOW", decision.reason, severity="LOW", rule_id="procurement.supplier_approved")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_buyer_tenant(order_doc) -> str | None:
	"""B2B order'da buyer'ın tenant'ını bul."""
	buyer = getattr(order_doc, "buyer", None)
	if not buyer:
		return None
	# Buyer User → tradehub_buyer_tenant veya seller_profile field.
	# has_column guard: aday alanların bir kısmı (örn. tradehub_buyer_tenant)
	# custom field olarak oluşturulmamış olabilir; olmayan kolona get_value
	# MariaDB 1054 fırlatır → var olan kolona düşmek için atlanır.
	for fieldname in ("tradehub_buyer_tenant", "tradehub_tenant", "buyer_tenant"):
		if not frappe.db.has_column("User", fieldname):
			continue
		val = frappe.db.get_value("User", buyer, fieldname)
		if val:
			return val
	return None


def _extract_order_categories(order_doc) -> list[str]:
	cats: set[str] = set()
	for item in getattr(order_doc, "items", []) or []:
		cat = getattr(item, "category", None) or getattr(item, "product_category", None)
		if cat:
			cats.add(cat)
	return list(cats)


def _audit(
	user: str,
	order_doc,
	decision: str,
	reason: str,
	severity: str = "LOW",
	rule_id: str = "procurement.supplier_check",
) -> None:
	try:
		from tradehub_core.audit import log_decision

		log_decision(
			actor=user,
			action="order.create",
			object_doctype="Order",
			object_name=getattr(order_doc, "name", "*"),
			decision=decision,
			rule_id=rule_id,
			layer="L2",
			severity=severity,
			context={
				"reason": reason,
				"supplier": getattr(order_doc, "seller", None),
				"amount": float(getattr(order_doc, "total", 0) or 0),
			},
		)
	except Exception as exc:
		frappe.log_error(f"supplier_whitelist audit failed: {exc}", "Supplier Whitelist")

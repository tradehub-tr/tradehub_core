"""FAZ 3.5 — ReBAC ↔ Frappe permission drift detection.

Daily scheduler job:
  - N kullanıcıyı örnekle (sample)
  - Her örnek için: Frappe `has_permission` vs OpenFGA `check` karşılaştır
  - Drift bulursa `Authorization Anomaly Alert` üret (rule_id=rebac.drift)

Drift senaryoları:
  - Frappe ALLOW, ReBAC DENY → "frappe_overpermits"
  - Frappe DENY, ReBAC ALLOW → "rebac_overpermits" (DAHA TEHLİKELİ)
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import now_datetime

# Sample size — production'da düşük tut, full scan pahalı
DEFAULT_SAMPLE_USERS = 20

# Sadece B2B kritik (ReBAC kapsamı) doctype'lar.
# Relation isimleri model.fga ile birebir eşleşmeli.
#
# O4 fix: Order Approval drift listesinden çıkarıldı — `can_approve_l1/l2` ABAC
# condition (amount) içerdiği için drift karşılaştırması güvenilir değildi
# (amount > 5000 doc'larda L1 check her zaman False döner, Frappe DocPerm submit
# yes ise false-positive `frappe_overpermits` patlardı). Approval doğrulaması
# için amount-aware ayrı job gerekli.
# #C4 — Yalnız model.fga'da TANIMLI tipler drift'te sorgulanır. "Store Subscription"
# çıkarıldı: model.fga'da `store_subscription` tipi YOK → OpenFGA validation error
# (400) → her Store Subscription için yanlış `frappe_overpermits` + breaker besleme.
# Abonelik gating ReBAC değil ABAC/entitlement katmanında (guardrail) yapılıyor.
DRIFT_DOCTYPES = [
	("Order", "read", "can_view"),
	("Admin Seller Profile", "read", "can_view"),
]

# Conditional tuple'lı relation'lar — defansif skip (ileride DRIFT_DOCTYPES'a
# yanlışlıkla eklenirse de _check_drift None döner).
_CONDITIONAL_RELATIONS = frozenset({"can_approve_l1", "can_approve_l2"})


def scan_drift(sample_size: int | None = None) -> dict[str, Any]:
	"""Top-level scheduler entry. Returns summary dict."""
	sample_size = sample_size or DEFAULT_SAMPLE_USERS

	# Sidecar canlı mı?
	try:
		from tradehub_core.services import rebac_client

		if not rebac_client.healthz():
			return {"skipped": "sidecar_unavailable"}
	except Exception:
		return {"skipped": "sidecar_unavailable"}

	users = (
		frappe.get_all(
			"User",
			filters={"enabled": 1},
			pluck="name",
			limit=sample_size,
		)
		or []
	)

	drift_count = 0
	checks_done = 0

	for user in users:
		for doctype, ptype, relation in DRIFT_DOCTYPES:
			candidates = frappe.get_all(doctype, fields=["name"], limit=3)
			for c in candidates:
				checks_done += 1
				drift = _check_drift(user, doctype, ptype, relation, c["name"])
				if drift:
					drift_count += 1
					_create_drift_alert(user, doctype, c["name"], drift)

	frappe.db.commit()
	return {
		"sample_users": len(users),
		"checks_done": checks_done,
		"drift_count": drift_count,
		"timestamp": str(now_datetime()),
	}


def _check_drift(
	user: str,
	doctype: str,
	ptype: str,
	relation: str,
	doc_name: str,
) -> str | None:
	"""Returns drift type or None."""
	from tradehub_core.services import rebac_client

	# O4 defensive: ABAC condition'lı relation'lar drift için güvenilir değil
	if relation in _CONDITIONAL_RELATIONS:
		return None

	try:
		frappe_allow = bool(frappe.has_permission(doctype=doctype, ptype=ptype, doc=doc_name, user=user))
	except Exception:
		return None

	rebac_object_type = _doctype_to_rebac(doctype)
	if not rebac_object_type:
		return None

	# Conditional tuple'lar için ABAC context oluştur — aksi halde
	# check her zaman False döner ve false-positive `frappe_overpermits` üretir.
	context = _build_abac_context(doctype, doc_name, relation)

	try:
		rebac_allow = rebac_client.check(
			user=f"user:{user}",
			relation=relation,
			object=f"{rebac_object_type}:{doc_name}",
			context=context,
		)
	except Exception:
		return None

	if frappe_allow and not rebac_allow:
		return "frappe_overpermits"
	if rebac_allow and not frappe_allow:
		return "rebac_overpermits"
	return None


def _build_abac_context(doctype: str, doc_name: str, relation: str) -> dict | None:
	"""Conditional relation'lar için minimum context.

	O4 sonrası `can_approve_l1/l2` drift'ten çıkarıldı → bu fonksiyon şu an
	pratikte None döner. İleride conditional drift desteği eklenirse aynı
	signature ile genişletilir.
	"""
	if doctype != "Order Approval" or relation not in _CONDITIONAL_RELATIONS:
		return None
	try:
		amount = frappe.db.get_value("Order Approval", doc_name, "amount")
		if amount is None:
			return None
		return {"amount": int(round(float(amount)))}
	except Exception:
		return None


def _doctype_to_rebac(doctype: str) -> str | None:
	# Sadece model.fga'da tanımlı tipler. RFQ/Quote tipi model'de YOK; ekleneceği
	# zaman buraya eklenecek (bkz. model.fga `type rfq`/`quote`).
	mapping = {
		"Order Approval": "order_approval",
		"Order": "order",
		"Admin Seller Profile": "store",
		"Store Subscription": "store_subscription",
	}
	return mapping.get(doctype)


def _create_drift_alert(user: str, doctype: str, doc_name: str, drift_type: str) -> None:
	"""Create an Authorization Anomaly Alert for the drift."""
	try:
		# Drift rule yoksa oluştur (idempotent)
		rule_name = _ensure_drift_rule()

		alert = frappe.new_doc("Authorization Anomaly Alert")
		alert.rule = rule_name
		alert.triggered_at = now_datetime()
		alert.status = "open"
		alert.severity = "HIGH" if drift_type == "rebac_overpermits" else "MEDIUM"
		alert.actor = user
		alert.event_count = 1
		alert.window_start = now_datetime()
		alert.window_end = now_datetime()
		alert.evidence_log_ids = f"{doctype}:{doc_name}:{drift_type}"
		alert.action_taken = "drift_detected"
		alert.insert(ignore_permissions=True)
	except Exception as exc:
		frappe.log_error(f"drift alert failed: {exc}", "ReBAC Drift Detection")


def _ensure_drift_rule() -> str:
	"""Drift için rule kaydı yoksa oluştur."""
	name = "REBAC_DRIFT"
	if frappe.db.exists("Authorization Anomaly Rule", name):
		return name

	doc = frappe.new_doc("Authorization Anomaly Rule")
	doc.rule_code = name
	doc.rule_name = "ReBAC ↔ Frappe Drift"
	doc.detection_type = "rebac_frappe_drift"
	doc.threshold_count = 1
	doc.window_minutes = 1440
	doc.severity_filter = "any"
	doc.is_active = 1
	doc.action_notify = 1
	doc.cooldown_minutes = 60
	doc.description = "Frappe permission ile OpenFGA tuple sonucunda farklı karar"
	doc.insert(ignore_permissions=True)
	return name

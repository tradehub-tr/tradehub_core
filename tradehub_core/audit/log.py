# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 1.4 — Audit log helper'ları.

İçindeki 3 fonksiyon (log_decision, log_role_change, log_override) ilgili
DocType'a `flags.audit_write = True` ile insert eder; DocType validate'i
bu flag olmadan insert'i reddeder → tek doğru yazma yolu.

Best-effort yazım: log yazımı patlasa bile asıl iş akışı (örn. listing
create) **devam etmeli**. Audit hatası business flow'u bozmaz.

Detay: docs/yetki/01-karar-dosyasi.md §4, docs/yetki/03-doctype-sablonlari.md
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe.utils import now_datetime

# --- #F1 Tamper-evident hash-chain (Authorization Decision Log) ---
# Her ADL kaydı, içeriğinin + bir önceki kaydın entry_hash'inin SHA-256'sıdır.
# Herhangi bir alanın sonradan değiştirilmesi → yeniden hesaplanan hash uyuşmaz
# (içerik kurcalaması); bir kaydın silinmesi/yeniden sıralanması → prev_hash
# linkage kopar (zincir kurcalaması). Bkz. verify_chain().
ADL_HASH_FIELDS = [
	"timestamp", "actor", "actor_role", "tenant", "buyer_org", "action",
	"object_doctype", "object_name", "decision", "rule_id", "layer", "region",
	"plan_code", "severity", "context", "request_id", "ip_address", "user_agent",
]
_GENESIS_HASH = "GENESIS"


def adl_canonical(row: Any) -> str:
	"""ADL kaydından deterministik kanonik string (dict veya doc kabul eder)."""
	get = row.get if hasattr(row, "get") else (lambda k: getattr(row, k, None))
	return json.dumps(
		{f: str(get(f) if get(f) is not None else "") for f in ADL_HASH_FIELDS},
		sort_keys=True,
		ensure_ascii=False,
	)


def adl_entry_hash(row: Any, prev_hash: str | None) -> str:
	"""entry_hash = SHA-256(kanonik_içerik | prev_hash)."""
	payload = adl_canonical(row) + "|" + (prev_hash or _GENESIS_HASH)
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_chain(limit: int = 5000, start: str | None = None) -> dict:
	"""#F1 — ADL hash-chain'ini doğrula; kurcalamayı tespit et.

	Kayıtlar creation ASC sırada yürünür. Her kayıt için:
	  - entry_hash yeniden hesaplanır → uyuşmazsa İÇERİK kurcalanmış.
	  - prev_hash bir önceki kaydın entry_hash'ine eşit olmalı → değilse
	    SIRALAMA/SİLME kurcalaması (zincir kopması).

	Returns: {"ok": bool, "checked": n, "tampered": [{name, kind}], "broken_links": [...]}
	"""
	# Yalnız hash-chain adoption'ı SONRASI kayıtlar (entry_hash dolu). Öncekiler
	# hash taşımaz → zincire dahil edilmez.
	rows = frappe.get_all(
		"Authorization Decision Log",
		filters={"entry_hash": ["is", "set"]},
		fields=["name", "prev_hash", "entry_hash", "creation", *ADL_HASH_FIELDS],
		order_by="creation asc, name asc",
		limit=limit,
	)
	tampered: list[dict] = []
	broken: list[dict] = []
	expected_prev = None  # ilk kaydın prev_hash'i GENESIS olmalı
	for i, r in enumerate(rows):
		recomputed = adl_entry_hash(r, r.get("prev_hash"))
		if recomputed != r.get("entry_hash"):
			tampered.append({"name": r["name"], "kind": "content"})
		if i == 0:
			if r.get("prev_hash") not in (None, "", _GENESIS_HASH):
				broken.append({"name": r["name"], "kind": "bad_genesis"})
		elif r.get("prev_hash") != expected_prev:
			broken.append({"name": r["name"], "kind": "broken_link"})
		expected_prev = r.get("entry_hash")
	return {
		"ok": not tampered and not broken,
		"checked": len(rows),
		"tampered": tampered,
		"broken_links": broken,
	}

# --- Constants (decision values) ---
DECISION_ALLOW = "ALLOW"
DECISION_DENY = "DENY"
DECISION_FIELD_MASKED = "FIELD_MASKED"
DECISION_ALLOW_PENDING = "ALLOW_PENDING"
DECISION_ERROR = "ERROR"

# --- Constants (layers) ---
LAYER_L0 = "L0"  # Entitlement
LAYER_L1 = "L1"  # Tenant isolation
LAYER_L2 = "L2"  # Authorization (RBAC/ReBAC/ABAC)
LAYER_L3 = "L3"  # Field/PII

# --- Constants (severity) ---
SEVERITY_LOW = "LOW"
SEVERITY_NORMAL = "NORMAL"
SEVERITY_HIGH = "HIGH"


def log_decision(
	*,
	actor: str | None = None,
	action: str,
	decision: str,
	rule_id: str | None = None,
	layer: str | None = None,
	object_doctype: str | None = None,
	object_name: str | None = None,
	tenant: str | None = None,
	buyer_org: str | None = None,
	region: str | None = None,
	plan_code: str | None = None,
	severity: str = SEVERITY_NORMAL,
	context: dict[str, Any] | None = None,
	actor_role: str | None = None,
	request_id: str | None = None,
	ip_address: str | None = None,
	user_agent: str | None = None,
) -> str | None:
	"""Authorization Decision Log kaydı oluştur (best-effort).

	Args:
	    actor: User email (None → frappe.session.user)
	    action: "listing.create", "order.approve" vb. (zorunlu)
	    decision: ALLOW / DENY / FIELD_MASKED / ALLOW_PENDING / ERROR (zorunlu)
	    rule_id: Tetiklenen kural ID'si (örn. "tenant.isolation")
	    layer: L0 / L1 / L2 / L3
	    object_doctype, object_name: Hedef nesne
	    tenant: Admin Seller Profile.name (seller-side scope)
	    buyer_org: CRM Organization.name (buyer-side scope). None bırakılırsa
	        actor'ın User.tradehub_parent_organization'ından otomatik resolve
	        edilir (Faz 5.2 — buyer audit scope için custom field).
	    region, plan_code: Snapshot
	    severity: LOW / NORMAL / HIGH
	    context: ABAC payload, request özeti
	    actor_role, request_id, ip_address, user_agent: meta

	Returns:
	    Oluşturulan ADL kaydının adı, hata olursa None.

	Best-effort: log yazımı patlasa bile exception fırlatmaz, sadece log_error.
	"""
	try:
		actor = actor or (frappe.session.user if hasattr(frappe, "session") else None)

		# O5: buyer_org otomatik resolve (caller geçirmediyse, actor'ın
		# organization'ından alınır)
		if not buyer_org and actor and actor not in ("Guest", "Administrator"):
			try:
				buyer_org = frappe.db.get_value("User", actor, "tradehub_parent_organization")
			except Exception:
				frappe.log_error(frappe.get_traceback(), "audit.log_decision_buyer_org")
				buyer_org = None

		# Context'i JSON-serializable yap
		ctx_str = None
		if context:
			try:
				ctx_str = json.dumps(context, default=str, ensure_ascii=False)[:5000]
			except (TypeError, ValueError):
				ctx_str = None

		doc = frappe.get_doc(
			{
				"doctype": "Authorization Decision Log",
				"timestamp": now_datetime(),
				"actor": actor,
				"actor_role": actor_role,
				"tenant": tenant,
				"buyer_org": buyer_org,
				"action": action,
				"object_doctype": object_doctype,
				"object_name": object_name,
				"decision": decision,
				"rule_id": rule_id,
				"layer": layer,
				"region": region,
				"plan_code": plan_code,
				"severity": severity,
				"context": ctx_str,
				"request_id": request_id,
				"ip_address": ip_address,
				"user_agent": user_agent,
			}
		)
		doc.flags.audit_write = True
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception as exc:
		# Best-effort — audit yazımı patlasa bile business flow devam etmeli
		try:
			frappe.log_error(
				f"log_decision başarısız: actor={actor}, action={action}, decision={decision}: {exc}",
				"audit.log_decision",
			)
		except Exception:
			pass
		return None


def log_role_change(
	*,
	target_user: str,
	change_type: str,
	changed_by: str | None = None,
	tenant: str | None = None,
	before_roles: list[str] | None = None,
	after_roles: list[str] | None = None,
	before_role_profiles: list[str] | None = None,
	after_role_profiles: list[str] | None = None,
	reason: str | None = None,
	is_temporary: bool = False,
	auto_revert_at: str | None = None,
) -> str | None:
	"""Role Change Log kaydı oluştur (best-effort).

	Args:
	    target_user: Rolü değişen user (zorunlu)
	    change_type: invite / activate / deactivate / role_assign / role_remove /
	                 profile_change / co_owner_promote / owner_transfer
	    changed_by: Değişikliği yapan (None → session.user)
	    tenant: Admin Seller Profile.name
	    before_roles / after_roles: Rol snapshot'ları
	    before_role_profiles / after_role_profiles: Rol Profile snapshot'ları
	    reason: Gerekçe
	    is_temporary, auto_revert_at: Geçici yetkilendirme için (Faz 3)

	Returns:
	    Log kaydı adı, hata olursa None.
	"""
	try:
		changed_by = changed_by or (frappe.session.user if hasattr(frappe, "session") else None)

		doc = frappe.get_doc(
			{
				"doctype": "Role Change Log",
				"timestamp": now_datetime(),
				"change_type": change_type,
				"changed_by": changed_by,
				"target_user": target_user,
				"tenant": tenant,
				"before_roles": json.dumps(before_roles or [], ensure_ascii=False),
				"after_roles": json.dumps(after_roles or [], ensure_ascii=False),
				"before_role_profiles": json.dumps(before_role_profiles or [], ensure_ascii=False),
				"after_role_profiles": json.dumps(after_role_profiles or [], ensure_ascii=False),
				"reason": reason,
				"is_temporary": 1 if is_temporary else 0,
				"auto_revert_at": auto_revert_at,
			}
		)
		doc.flags.audit_write = True
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception as exc:
		try:
			frappe.log_error(
				f"log_role_change başarısız: target={target_user}, type={change_type}: {exc}",
				"audit.log_role_change",
			)
		except Exception:
			pass
		return None


def log_override(
	*,
	target_object: str,
	override_action: str,
	justification: str,
	admin_user: str | None = None,
	original_decision: str = DECISION_DENY,
	final_decision: str = DECISION_ALLOW,
	severity: str = "MEDIUM",
	approved_by: str | None = None,
) -> str | None:
	"""Permission Override Log kaydı oluştur (best-effort).

	Args:
	    target_object: "DocType/Name" formatında hedef (zorunlu)
	    override_action: force_approve / delete_locked / ignore_permissions_insert vb.
	    justification: Override gerekçesi (zorunlu, audit için)
	    admin_user: Override yapan admin (None → session.user)
	    original_decision: Normal kararda olacak sonuç (default DENY)
	    final_decision: Override sonrası karar (default ALLOW)
	    severity: LOW / MEDIUM / HIGH / CRITICAL
	    approved_by: İkinci-göz onayı (Faz 3)

	Returns:
	    Log kaydı adı, hata olursa None.

	Raises:
	    ValueError: justification boşsa (zorunlu alan kontrolü).
	"""
	if not (justification or "").strip():
		raise ValueError("log_override: justification (gerekçe) zorunludur.")

	try:
		admin_user = admin_user or (frappe.session.user if hasattr(frappe, "session") else None)

		doc = frappe.get_doc(
			{
				"doctype": "Permission Override Log",
				"timestamp": now_datetime(),
				"admin_user": admin_user,
				"target_object": target_object,
				"override_action": override_action,
				"original_decision": original_decision,
				"final_decision": final_decision,
				"severity": severity,
				"approved_by": approved_by,
				"justification": justification,
			}
		)
		doc.flags.audit_write = True
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception as exc:
		try:
			frappe.log_error(
				f"log_override başarısız: target={target_object}, action={override_action}: {exc}",
				"audit.log_override",
			)
		except Exception:
			pass
		return None


# ─── F-041: PII reveal audit endpoint ──────────────────────────────────────


@frappe.whitelist()
def log_pii_reveal(doctype: str = "", name: str = "", field: str = "") -> dict:
	"""Admin panelinde maskelenmiş PII alanı açıldığında server-side audit kaydı oluşturur."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw("Authentication required", frappe.AuthenticationError)

	log_decision(
		actor=user,
		action="pii.reveal",
		decision=DECISION_ALLOW,
		rule_id="data_masking.reveal",
		layer=LAYER_L2,
		object_doctype=doctype or None,
		object_name=name or None,
		severity=SEVERITY_NORMAL,
		context={"field": field},
	)
	return {"ok": True}

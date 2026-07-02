"""Policy Decision Point (PDP) — Faz 1 iskeleti.

Tek karar noktası. Her enforcement noktası (doctype has_permission, whitelist
endpoint, storefront API) NİHAİ olarak buradan geçmeli. Simülatör de bunu
"dry-run" çağırır → simülasyon = gerçek karar (#F3).

Karar sırası (fail-closed):
    L0  registry     — bilinmeyen verb → DENY
    L1  hard_deny    — suspend / AML / KYC (Faz 2 doldurur; şimdilik no-op)
    L2  guardrail    — plan / abonelik / trial-paywall boundary (Faz 2; şimdilik pass-through)
    L3  relationship — ReBAC (Faz 4; şimdilik kapalı) ∪ role (RBAC; AKTİF: frappe.has_permission)
    L4  default_deny — hiçbir katman ALLOW demediyse reddet

DAVRANIŞ GARANTİSİ (Faz 1): L1 no-op + L2 pass-through olduğu için
`authorize(...).allow == frappe.has_permission(...)`. Yani bir enforcement
noktasını PDP'ye yönlendirmek mevcut davranışı DEĞİŞTİRMEZ (regresyonsuz taşıma).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import frappe

from tradehub_core.authz import break_glass, enforcement, guardrail, registry

RESULT_ALLOW = "ALLOW"
RESULT_DENY = "DENY"
RESULT_SKIP = "SKIP"
RESULT_ERROR = "ERROR"

# Karar loglama modu
AUDIT_DENY = "deny"  # yalnız DENY logla (varsayılan — hot-path flood önlemi)
AUDIT_ALL = "all"
AUDIT_NONE = "none"


@dataclass
class Decision:
	"""PDP kararı."""

	allow: bool
	reason: str  # makine-okunur kısa kod (örn. "rbac.allow", "default_deny")
	decision_id: str
	layer: str  # kararı veren katman (örn. "L3.rbac", "L4.default_deny")
	action: str  # "Listing.read" gibi
	actor: str
	object_doctype: str | None = None
	object_name: str | None = None
	trace: list[dict[str, Any]] = field(default_factory=list)

	@property
	def denied(self) -> bool:
		return not self.allow

	def __bool__(self) -> bool:
		return self.allow

	def to_dict(self) -> dict[str, Any]:
		return {
			"allow": self.allow,
			"reason": self.reason,
			"decision_id": self.decision_id,
			"layer": self.layer,
			"action": self.action,
			"actor": self.actor,
			"object_doctype": self.object_doctype,
			"object_name": self.object_name,
			"trace": self.trace,
		}


@dataclass
class _Layer:
	"""Bir katman adımının sonucu."""

	name: str
	result: str  # ALLOW | DENY | SKIP | ERROR
	reason: str = ""
	detail: str = ""

	def step(self) -> dict[str, Any]:
		return {"layer": self.name, "result": self.result, "reason": self.reason, "detail": self.detail}


def _new_decision_id() -> str:
	"""Karar için opak, izlenebilir kimlik."""
	try:
		return frappe.generate_hash(length=12)
	except Exception:
		import uuid

		return uuid.uuid4().hex[:12]


def _resolve_resource(resource: Any) -> tuple[str | None, str | None, Any]:
	"""resource → (doctype, name, doc).

	Kabul edilen biçimler:
	  - doc objesi (.doctype/.name)
	  - dict ({"doctype": ..., "name": ...} veya doc-benzeri)
	  - (doctype, name_or_doc) tuple
	  - str → doctype (doctype-seviyesi kontrol, doc=None)
	  - None → (None, None, None)
	"""
	if resource is None:
		return None, None, None
	if isinstance(resource, str):
		return resource, None, None
	if isinstance(resource, tuple) and len(resource) == 2:
		dt, second = resource
		if isinstance(second, str):
			return dt, second, None
		# second bir doc objesi
		return dt, getattr(second, "name", None), second
	if isinstance(resource, dict):
		return resource.get("doctype"), resource.get("name"), resource
	# doc objesi varsayımı
	return getattr(resource, "doctype", None), getattr(resource, "name", None), resource


# ── Katmanlar ────────────────────────────────────────────────────────────────


def _hard_deny(principal, verb, doctype, name, doc, ctx) -> _Layer:
	"""L1 — regülatif kesin ret (KYC / AML / abonelik-suspended).

	Fail-safe: guardrail değerlendirmesi hata verirse SKIP (base RBAC yine korur);
	regülatif katman hatası tüm erişimi kilitlemesin.
	"""
	try:
		res = guardrail.hard_deny(principal, verb, doctype, name, doc, ctx)
	except Exception as e:  # noqa: BLE001 — fail-safe, base RBAC korur
		frappe.log_error(f"PDP hard_deny eval failed: {e}", "authz.pdp")
		return _Layer("L1.hard_deny", RESULT_SKIP, detail=f"eval_error: {e}")
	if res.deny:
		return _Layer("L1.hard_deny", RESULT_DENY, reason=res.reason, detail=res.detail)
	return _Layer("L1.hard_deny", RESULT_SKIP)


def _guardrail(principal, verb, doctype, name, doc, ctx) -> _Layer:
	"""L2 — plan/abonelik feature boundary (kesişim; yalnız kısıtlar)."""
	try:
		res = guardrail.guardrail(principal, verb, doctype, name, doc, ctx)
	except Exception as e:  # noqa: BLE001 — fail-safe, base RBAC korur
		frappe.log_error(f"PDP guardrail eval failed: {e}", "authz.pdp")
		return _Layer("L2.guardrail", RESULT_SKIP, detail=f"eval_error: {e}")
	if res.deny:
		return _Layer("L2.guardrail", RESULT_DENY, reason=res.reason, detail=res.detail)
	return _Layer("L2.guardrail", RESULT_SKIP)


def _relationship_or_role(principal, ptype, doctype, name, doc, ctx) -> _Layer:
	"""L3 — ReBAC (Faz 4, kapalı) ∪ RBAC (aktif).

	RBAC = Frappe'nin gerçek yetki kararı: `frappe.has_permission` registered
	has_permission hook'larını + rol DocPerm'lerini uygular. Bu, bugünkü
	enforcement'ın BİREBİR aynısı → regresyonsuz.
	Hata durumunda fail-closed (ERROR → DENY).
	"""
	if not doctype:
		# Doctype yoksa RBAC değerlendirilemez → fail-closed.
		return _Layer("L3.rbac", RESULT_DENY, reason="no_doctype", detail="resource doctype çözülemedi")
	# Frappe has_permission doc olarak hem obje hem docname (str) kabul eder;
	# doc objesi yoksa name string'ini geçir ki tekil-doc kontrolü yapılabilsin.
	target = doc if doc is not None else name
	try:
		allowed = frappe.has_permission(doctype, ptype, doc=target, user=principal)
	except Exception as e:  # noqa: BLE001 — fail-closed; nedeni logla
		frappe.log_error(f"PDP RBAC check failed: {e}", "authz.pdp")
		return _Layer("L3.rbac", RESULT_ERROR, reason="rbac_error", detail=str(e))
	if allowed:
		return _Layer("L3.rbac", RESULT_ALLOW, reason="rbac.allow")
	return _Layer("L3.rbac", RESULT_SKIP, reason="rbac.no_grant")


# ── Ana giriş ──────────────────────────────────────────────────────────────────


def authorize(
	principal: str,
	action: str,
	resource: Any = None,
	context: dict[str, Any] | None = None,
	*,
	audit: str = AUDIT_DENY,
) -> Decision:
	"""Tek yetki kararı.

	Args:
	    principal: kullanıcı (email). Boşsa frappe.session.user.
	    action: verb ("read"/"write"/"approve" ...). Bilinmeyen verb → DENY.
	    resource: doc / dict / (doctype, name) / doctype-str / None.
	    context: ek ABAC öznitelikleri (amount, region ...) — Faz 2+ kullanır.
	    audit: "deny" (varsayılan, yalnız retleri logla) | "all" | "none".

	Returns:
	    Decision (allow, reason, decision_id, layer, trace).
	"""
	ctx = context or {}
	principal = principal or getattr(getattr(frappe, "session", None), "user", None) or "Guest"
	verb = (action or "").lower()
	doctype, name, doc = _resolve_resource(resource)
	action_label = f"{doctype}.{verb}" if doctype else verb
	did = _new_decision_id()
	trace: list[dict[str, Any]] = []

	def _finalize(allow: bool, reason: str, layer: str) -> Decision:
		# Faz 7 — Break-glass: bir DENY üretildiyse ve actor'ın AKTİF acil-erişimi
		# varsa karar ALLOW'a çevrilir ve override HIGH audit'lenir (kalıcı iz).
		if not allow:
			try:
				if break_glass.is_active(principal):
					trace.append(_Layer("L0.break_glass", RESULT_ALLOW, reason="break_glass_override").step())
					_log_break_glass_override(principal, action_label, doctype, name, did)
					allow, reason, layer = True, "break_glass_override", "L0.break_glass"
			except Exception:  # noqa: BLE001 — break-glass kontrolü kararı bozmasın
				pass
		dec = Decision(
			allow=allow,
			reason=reason,
			decision_id=did,
			layer=layer,
			action=action_label,
			actor=principal,
			object_doctype=doctype,
			object_name=name,
			trace=trace,
		)
		_maybe_audit(dec, audit)
		return dec

	# L0 — registry: bilinmeyen verb → fail-closed DENY
	ptype = registry.ptype_for(verb)
	if ptype is None:
		trace.append(_Layer("L0.registry", RESULT_DENY, reason="unknown_action").step())
		return _finalize(False, "unknown_action", "L0.registry")

	# L1 — hard deny
	l1 = _hard_deny(principal, verb, doctype, name, doc, ctx)
	trace.append(l1.step())
	if l1.result == RESULT_DENY:
		return _finalize(False, l1.reason or "hard_deny", l1.name)

	# L2 — guardrail (boundary)
	l2 = _guardrail(principal, verb, doctype, name, doc, ctx)
	trace.append(l2.step())
	if l2.result == RESULT_DENY:
		return _finalize(False, l2.reason or "guardrail_deny", l2.name)

	# L3 — relationship (ReBAC) ∪ role (RBAC)
	l3 = _relationship_or_role(principal, ptype, doctype, name, doc, ctx)
	trace.append(l3.step())
	# ReBAC'i değerlendir (shadow: her zaman karşılaştır+logla). rebac_allow bool|None.
	rebac_allow = _rebac_reconcile(principal, verb, doctype, name, l3.result == RESULT_ALLOW, ctx)

	if l3.result == RESULT_ALLOW:
		return _finalize(True, l3.reason or "allow", l3.name)
	if l3.result == RESULT_DENY:
		# katman açıkça reddetti (örn. doctype çözülemedi) — fail-closed
		return _finalize(False, l3.reason or "deny", l3.name)
	if l3.result == RESULT_ERROR:
		# fail-closed: hata = ret
		return _finalize(False, l3.reason or "error", l3.name)

	# Faz 5 — ENFORCE: RBAC grant vermedi (SKIP). Doctype enforce modundaysa ve ReBAC
	# ilişki-temelli erişim veriyorsa union ile ALLOW (RBAC ∪ ReBAC). Kill-switch veya
	# shadow modda bu dal çalışmaz → RBAC kararı (default-deny) geçerli, lock-out yok.
	if rebac_allow is True and enforcement.is_enforced(doctype):
		trace.append(_Layer("L3.rebac", RESULT_ALLOW, reason="rebac.grant").step())
		return _finalize(True, "rebac.grant", "L3.rebac")

	# L4 — default deny
	trace.append(_Layer("L4.default_deny", RESULT_DENY, reason="default_deny").step())
	return _finalize(False, "default_deny", "L4.default_deny")


def _rebac_reconcile(principal, verb, doctype, name, rbac_allow: bool, ctx: dict):
	"""ReBAC'i değerlendir → rebac_allow (True/False) veya None (uygulanamaz).

	Her modda (shadow/enforce) ÇAĞRILIR: RBAC ile uyuşmazsa 'shadow divergence'
	loglanır (Carta/Figma geçiş dersi — sapmayı 0'a indir). Dönen değer authorize()
	tarafından enforce modda union-grant için kullanılır.

	Kesinlikle fail-safe: hiçbir istisna/erişilemezlik kararı/isteği etkilemez →
	None döner (enforce union tetiklenmez, RBAC geçerli). Yalnız ReBAC konfigüreyse
	(STORE_ID var), resource modellenmişse ve kullanıcı privileged değilse değerlendirir.
	"""
	try:
		from tradehub_core.services import rebac_client

		if not rebac_client._store_id():  # noqa: SLF001 — konfigüre değil
			return None
		if not name or not doctype:
			return None
		if guardrail._is_privileged(principal, verb):  # noqa: SLF001 — admin/platform RBAC-only
			return None
		# Faz 6 — alan-bazlı action ise field object'e çöz (listing_field:name:PART);
		# değilse normal doctype→object eşlemesi.
		field_target = registry.field_target_for(doctype, verb, name)
		if field_target:
			obj, relation = field_target
		else:
			obj_type = registry.rebac_object_for(doctype)
			relation = registry.rebac_relation_for(doctype, verb)
			if not obj_type or not relation:
				return None  # bu doctype/verb ReBAC modelinde yok
			obj = f"{obj_type}:{name}"
		# Amount-gated relation'lar (can_approve_l1/l2) context ister; ctx'ten geç.
		fga_ctx = None
		if "amount_eur" in ctx or "amount" in ctx:
			fga_ctx = {"amount": int(ctx.get("amount_eur") or ctx.get("amount") or 0)}
		rebac_allow = rebac_client.check(f"user:{principal}", relation, obj, context=fga_ctx)
		if rebac_allow != rbac_allow:
			_log_shadow_divergence(principal, verb, doctype, name, relation, rbac_allow, rebac_allow)
		return rebac_allow
	except Exception:  # noqa: BLE001 — ReBAC ASLA kararı/isteği etkilemez (fail-safe)
		return None


def _log_break_glass_override(actor, action_label, doctype, name, decision_id) -> None:
	"""Break-glass ile DENY→ALLOW override'ını HIGH severity kalıcı audit'le."""
	try:
		from tradehub_core.audit import log as audit_mod

		audit_mod.log_decision(
			actor=actor,
			action=action_label,
			decision="ALLOW",
			rule_id="break_glass.override",
			layer="L0",
			object_doctype=doctype,
			object_name=name,
			severity="HIGH",
			request_id=decision_id,
			context={"break_glass": True, "reason": break_glass.reason_for(actor)},
		)
	except Exception:  # noqa: BLE001
		pass


def _log_shadow_divergence(principal, verb, doctype, name, relation, rbac_allow, rebac_allow) -> None:
	"""Sapmayı sabit bir etiketle logla (dashboard/grep için)."""
	try:
		frappe.log_error(
			message=(
				f"actor={principal} action={doctype}.{verb} object={doctype}:{name} "
				f"relation={relation} rbac={rbac_allow} rebac={rebac_allow}"
			),
			title="rebac.shadow_divergence",
		)
	except Exception:  # noqa: BLE001
		pass


def _maybe_audit(dec: Decision, mode: str) -> None:
	"""Kararı best-effort logla. Varsayılan: yalnız DENY (hot-path flood önlemi)."""
	if mode == AUDIT_NONE:
		return
	if mode == AUDIT_DENY and dec.allow:
		return
	try:
		from tradehub_core.audit import log as audit_mod

		audit_mod.log_decision(
			actor=dec.actor,
			action=dec.action,
			decision=RESULT_ALLOW if dec.allow else RESULT_DENY,
			rule_id=f"pdp.{dec.reason}",
			layer=dec.layer.split(".")[0],
			object_doctype=dec.object_doctype,
			object_name=dec.object_name,
			request_id=dec.decision_id,
			context={"trace": dec.trace},
		)
	except Exception:  # noqa: BLE001 — audit asla iş akışını bozmaz
		pass

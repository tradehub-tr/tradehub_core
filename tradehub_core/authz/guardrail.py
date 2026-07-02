"""Guardrail katmanı — Faz 2.

PDP karar hattının L1 (HARD DENY) ve L2 (GUARDRAIL / permission boundary)
katmanları. Bunlar yalnız KISITLAR (AWS permission-boundary / SCP deseni):
alttaki RBAC/ReBAC ALLOW dese bile, guardrail plan/regülasyon nedeniyle
reddedebilir. Guardrail asla izin VERMEZ (sadece boundary daraltır).

Katmanlar:
  L1 hard_deny — regülatif kesin ret: KYC eksik / AML-sanctions hit /
                 abonelik suspended (write). Ölü kod (#D1) buraya bağlanır.
  L2 guardrail — plan/abonelik feature boundary: aksiyonun gerektirdiği
                 feature aktif planda yoksa reddet (entitlement).

Bypass: Administrator + platform-full-access rolleri guardrail'a tabi değildir
(mevcut has_tenant_permission davranışıyla hizalı).

Not: Fonksiyonlar bağımlılıklarını (permissions/entitlement) TEMBEL import eder;
gerçek Frappe yokken (izole PDP stub'ı) çağrılırlarsa exception atabilirler —
PDP wrapper'ı bunu SKIP'e çevirir (base RBAC yine korur).
"""

from __future__ import annotations

from typing import Any

from tradehub_core.authz import registry


class GuardrailResult:
	"""(deny, reason) taşıyıcı."""

	__slots__ = ("deny", "reason", "detail")

	def __init__(self, deny: bool = False, reason: str = "", detail: str = ""):
		self.deny = deny
		self.reason = reason
		self.detail = detail


_ALLOW = GuardrailResult(False)


def _is_privileged(principal: str, verb: str) -> bool:
	"""Administrator / platform-full-access → guardrail'a tabi değil."""
	if principal == "Administrator":
		return True
	from tradehub_core import permissions as perm

	ptype = registry.ptype_for(verb)
	return perm._is_platform_full_access(principal, ptype)


def _seller_tenant(principal: str) -> str | None:
	"""Principal'ın satıcı mağazası (Admin Seller Profile.name) — yoksa None."""
	from tradehub_core import permissions as perm

	return perm._get_seller_profile_name(principal)


# ── L1 — HARD DENY (regülatif) ──────────────────────────────────────────────


def hard_deny(
	principal: str, verb: str, doctype: str | None, name: str | None, doc: Any, ctx: dict
) -> GuardrailResult:
	"""KYC / AML / abonelik-suspended kesin retleri. Reddederse her şeyi ezer."""
	if not doctype or _is_privileged(principal, verb):
		return _ALLOW

	from tradehub_core import permissions as perm

	# KYC — finansal doctype'lara doğrulanmamış kullanıcı erişemez.
	if not perm._check_kyc_verification(principal, doctype):
		return GuardrailResult(True, "kyc_required", f"{doctype} finansal; KYC doğrulaması gerekli")

	# AML / sanctions — flag'li kullanıcı hassas doctype'a erişemez.
	if not perm._check_aml_sanctions(principal, doctype):
		return GuardrailResult(True, "aml_blocked", f"{doctype} AML-hassas; sanctions/AML hit")

	# Abonelik operasyonel değilse gate'li doctype'larda WRITE yasak (read serbest).
	if doctype in perm.SUBSCRIPTION_GATED_DOCTYPES:
		ptype = registry.ptype_for(verb) or verb
		if ptype in ("write", "submit", "create", "delete", "cancel"):
			tenant = _seller_tenant(principal)
			if tenant and not perm._check_subscription_active(tenant, doctype, ptype):
				return GuardrailResult(
					True, "subscription_suspended", f"{tenant} aboneliği operasyonel değil (write yasak)"
				)

	return _ALLOW


# ── L2 — GUARDRAIL (plan/feature boundary) ──────────────────────────────────


def guardrail(
	principal: str, verb: str, doctype: str | None, name: str | None, doc: Any, ctx: dict
) -> GuardrailResult:
	"""Plan/abonelik feature boundary. Aksiyonun feature'ı aktif planda yoksa reddet.

	Yalnız feature-gated (registry.ACTION_TO_FEATURE) aksiyonlarda devreye girer.
	Store tenant çözülemezse (ör. buyer-tarafı action) değerlendirmez (skip) —
	guardrail yalnız plan AÇIKÇA kapsamıyorsa bloklar, belirsizde bloklamaz.
	"""
	if not doctype or _is_privileged(principal, verb):
		return _ALLOW

	feature = registry.feature_for(doctype, verb)
	if not feature:
		return _ALLOW  # bu aksiyon feature-gated değil

	tenant = _seller_tenant(principal)
	if not tenant:
		# Store scope yok → entitlement değerlendirilemez; base RBAC'a bırak.
		return _ALLOW

	from tradehub_core import entitlement as ent

	if not ent.has_feature(tenant, feature):
		return GuardrailResult(
			True, "feature_not_in_plan", f"'{feature}' aktif planda yok ({tenant})"
		)

	return _ALLOW

"""Break-glass — acil süper-erişim (Faz 7 yönetişim).

Normal yetki reddettiği hâlde gerçek bir acil durumda (incident) platform
admininin geçici, ZORUNLU-denetlenen, SÜRELİ bir bypass açmasını sağlar.

İlkeler (Alibaba süper-admin sınırı + SOC2 break-glass deseni):
  - Yalnız platform admini açabilir.
  - Gerekçe (reason) ZORUNLU.
  - Her açma/kapama + her override HIGH severity audit'lenir (kalıcı ADL kaydı).
  - SÜRELİ: TTL ile otomatik kapanır (varsayılan 30dk, max 4sa).
  - Aktif oturum frappe.cache'te (auto-expire); kalıcı denetim izi ADL'de.

PDP entegrasyonu: authorize() bir DENY üretirse ve actor'ın aktif break-glass'ı
varsa karar ALLOW'a çevrilir (layer L0.break_glass) ve override HIGH audit'lenir.
"""

from __future__ import annotations

import frappe

_CACHE_PREFIX = "authz:break_glass:"
_DEFAULT_MINUTES = 30
_MAX_MINUTES = 240

# Break-glass açabilecek roller (kill-switch/enforce ile aynı platform seti).
_ELIGIBLE_ROLES = frozenset(
	{"System Manager", "Administrator", "Platform Super Admin", "Platform Admin"}
)


def _eligible(actor: str) -> bool:
	if actor == "Administrator":
		return True
	try:
		return bool(set(frappe.get_roles(actor)) & _ELIGIBLE_ROLES)
	except Exception:  # noqa: BLE001
		return False


def _audit(actor: str, action: str, reason: str, minutes: int | None = None) -> None:
	try:
		from tradehub_core.audit import log as audit_mod

		ctx = {"reason": reason}
		if minutes is not None:
			ctx["minutes"] = minutes
		audit_mod.log_decision(
			actor=actor,
			action=action,
			decision="ALLOW",
			rule_id=action,
			layer="L0",
			severity="HIGH",
			context=ctx,
		)
	except Exception:  # noqa: BLE001 — audit iş akışını bozmaz
		pass


def activate(actor: str | None = None, reason: str = "", duration_minutes: int = _DEFAULT_MINUTES) -> dict:
	"""Acil break-glass oturumu aç. Platform admin + zorunlu gerekçe + HIGH audit."""
	actor = actor or frappe.session.user
	if not _eligible(actor):
		frappe.throw(
			frappe._("Break-glass yalnız platform admini tarafından açılabilir."),
			frappe.PermissionError,
		)
	if not reason or not reason.strip():
		frappe.throw(frappe._("Break-glass için gerekçe ZORUNLUdur."))
	minutes = max(1, min(int(duration_minutes or _DEFAULT_MINUTES), _MAX_MINUTES))
	frappe.cache().set_value(
		_CACHE_PREFIX + actor, {"reason": reason, "by": actor}, expires_in_sec=minutes * 60
	)
	_audit(actor, "break_glass.activate", reason, minutes)
	return {"actor": actor, "minutes": minutes, "reason": reason}


def is_active(actor: str | None) -> bool:
	if not actor:
		return False
	try:
		return bool(frappe.cache().get_value(_CACHE_PREFIX + actor))
	except Exception:  # noqa: BLE001 — cache okunamıyorsa güvenli taraf: aktif değil
		return False


def reason_for(actor: str) -> str | None:
	try:
		v = frappe.cache().get_value(_CACHE_PREFIX + actor)
		return v.get("reason") if isinstance(v, dict) else None
	except Exception:  # noqa: BLE001
		return None


def deactivate(actor: str | None = None) -> None:
	"""Break-glass oturumunu erken kapat (HIGH audit)."""
	actor = actor or frappe.session.user
	try:
		frappe.cache().delete_value(_CACHE_PREFIX + actor)
	except Exception:  # noqa: BLE001
		pass
	_audit(actor, "break_glass.deactivate", reason_for(actor) or "")

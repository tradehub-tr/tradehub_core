"""ReBAC enforcement kontrolü — Faz 5.

Kademeli enforce: her doctype için ReBAC'in karara KATILIP katılmayacağını ve
global bir kill-switch'i yönetir. Geri-alınabilirlik esas (Carta/Figma geçiş dersi).

Modlar (doctype başına):
  - "shadow" (VARSAYILAN): ReBAC yalnız karşılaştırılır, kararı DEĞİŞTİRMEZ.
  - "enforce": L3 kararı RBAC ∪ ReBAC (union) olur → ReBAC ilişki-temelli erişim
    EKLEYEBİLİR (RBAC'ın vermediği grant'ı verir). Union olduğu için RBAC erişimini
    ASLA KALDIRMAZ → lock-out riski yok (güvenli ilk enforce adımı).

Kill-switch (`rebac_kill_switch=true`): tüm doctype'ları anında "shadow"a düşürür
→ ReBAC enforce devre dışı, RBAC-only. Acil geri-alma (incident response).

Konfig kaynağı: site_config (migration/DocType gerektirmez). Örnek:
    bench --site <site> set-config rebac_enforcement '{"Order": "enforce"}'
    bench --site <site> set-config rebac_kill_switch true

frappe.conf request-scope cache'lidir; değişiklik clear-cache/restart gerektirebilir.
"""

from __future__ import annotations

import frappe

MODE_SHADOW = "shadow"
MODE_ENFORCE = "enforce"


def kill_switch_on() -> bool:
	"""Global acil-durdurma: True ise hiçbir doctype enforce edilmez."""
	try:
		return bool(frappe.conf.get("rebac_kill_switch", False))
	except Exception:  # noqa: BLE001 — konfig okunamıyorsa güvenli taraf: enforce yok
		return True


def enforcement_mode(doctype: str | None) -> str:
	"""Doctype için ReBAC modu: 'shadow' (varsayılan) | 'enforce'.

	Kill-switch açıksa her zaman 'shadow' döner (enforce bypass)."""
	if not doctype or kill_switch_on():
		return MODE_SHADOW
	try:
		modes = frappe.conf.get("rebac_enforcement") or {}
		if isinstance(modes, dict):
			mode = modes.get(doctype)
			return mode if mode in (MODE_SHADOW, MODE_ENFORCE) else MODE_SHADOW
	except Exception:  # noqa: BLE001 — okunamıyorsa shadow (enforce etme)
		pass
	return MODE_SHADOW


def is_enforced(doctype: str | None) -> bool:
	return enforcement_mode(doctype) == MODE_ENFORCE

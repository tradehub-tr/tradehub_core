"""3 paketlik fiyatlandırma yapısı: Basic / Pro Platinium / Enterprise.

- STARTER planını kaldır (aktif aboneliği yoksa sil; varsa güvenli biçimde pasifle).
- PRO → plan_name "Pro Platinium".
- ENTERPRISE → cta "Teklif Al" (contact_sales), trial_days 14 (en dolu paket, 14 gün deneme).
- FREE (Basic) → ücretli akış: cta_action "signup_billing", cta_label "Hemen başla".

Fiyatlara DOKUNULMAZ — süper admin "Görüntüleme ve Fiyatlandırma" sekmesinden ayarlar.
Idempotent: değerler zaten doğruysa no-op; STARTER yoksa atla.
"""

from __future__ import annotations

import frappe

from tradehub_core.api.v1.public_pricing import invalidate_pricing_cache


def _set(plan: str, values: dict) -> None:
	if frappe.db.exists("Subscription Plan", plan):
		frappe.db.set_value("Subscription Plan", plan, values, update_modified=False)


def execute():
	# PRO → Pro Platinium (ücretli akış: cta düzelt)
	_set("PRO", {"plan_name": "Pro Platinium", "cta_label": "Hemen başla"})

	# ENTERPRISE → Teklif Al + 14 gün deneme (tüm özellikler zaten dolu)
	_set(
		"ENTERPRISE",
		{"cta_label": "Teklif Al", "cta_action": "contact_sales", "trial_days": 14},
	)

	# FREE (Basic) → ücretli giriş paketi
	_set("FREE", {"cta_action": "signup_billing", "cta_label": "Hemen başla"})

	# STARTER kaldır — bağımlı abonelik varsa silme, pasifle
	if frappe.db.exists("Subscription Plan", "STARTER"):
		has_sub = frappe.db.exists("Store Subscription", {"plan": "STARTER"})
		if has_sub:
			frappe.db.set_value(
				"Subscription Plan",
				"STARTER",
				{"is_active": 0, "is_public": 0},
				update_modified=False,
			)
			frappe.logger().info("v15_6_25: STARTER aboneliği var, silinmedi; pasifleştirildi.")
		else:
			frappe.delete_doc("Subscription Plan", "STARTER", force=True, ignore_permissions=True)

	frappe.db.commit()
	invalidate_pricing_cache()

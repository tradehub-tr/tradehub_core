"""Marketplace storefront rollerinden 'desk_access' yetkisini kaldır.

Tarihçe:
Marketplace'in alıcı (Buyer) ve satıcı (Seller) rolleri Frappe Desk'e
(`/app/`) **girmemeli**. Önceden bu user_type='Website User' ile garanti
ediliyordu, ama Website User session yönetimi Redis-only olduğu için
"User None is disabled" (HTTP 417) bug'ı tetikleniyordu.

Yeni mimaride (2026-05):
  - user_type = System User (kalıcı tabSessions kaydı + restart-dayanıklı)
  - desk_access = 0 (Frappe Desk URL'ine erişim rol seviyesinde kapalı)

Bu kombinasyon:
  - Session dayanıklı (HTTP 417 bug'ı çözülür)
  - Desk URL'i fiilen kapalı (eski güvenlik felsefesi korunur)
  - Self-hosted: lisans kısıtı yok, System User sayısı sınırsız

ETKİLENMEZ:
  - System Manager / Administrator rolleri (kendi desk_access=1'leri var)
  - Verified Seller rolü (zaten desk_access=0)

Idempotent: zaten 0 olanları atlar.
"""

import frappe

ROLES_TO_DISABLE_DESK = ("Buyer", "Seller")


def execute():
	updated = 0
	already_correct = 0
	missing = 0

	for role in ROLES_TO_DISABLE_DESK:
		if not frappe.db.exists("Role", role):
			frappe.logger("patches").warning(f"  [skip] Role bulunamadı: {role}")
			missing += 1
			continue

		current = frappe.db.get_value("Role", role, "desk_access")
		if current == 0 or current is None:
			frappe.logger("patches").info(f"  [skip] {role}: desk_access zaten {current}")
			already_correct += 1
			continue

		frappe.db.set_value("Role", role, "desk_access", 0, update_modified=False)
		frappe.logger("patches").info(f"  [updated] {role}: desk_access {current} → 0")
		updated += 1

	frappe.db.commit()

	# Role + permission cache'leri temizle — yeni desk_access değeri etkili olsun
	try:
		frappe.cache.delete_value("roles")
	except Exception:
		frappe.log_error("Roles cache delete failed in disable_desk_access patch", "disable_desk_access_for_marketplace_roles")
		pass
	try:
		frappe.clear_cache()
	except Exception:
		frappe.log_error("Full cache clear failed in disable_desk_access patch", "disable_desk_access_for_marketplace_roles")
		pass

	frappe.logger("patches").info(
		f"[disable_desk_access_for_marketplace_roles] "
		f"updated={updated}, already_correct={already_correct}, missing={missing}"
	)

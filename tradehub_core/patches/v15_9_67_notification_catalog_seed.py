"""Bildirim olay kataloğu + şablon taslakları + içerik rolleri + gönderim indeksleri.

İdempotent: `notifications.seed.run` yalnız eksik kaydı ekler; ikinci çalıştırma kullanıcı
taslağını, yayını ve tercihini ezmez. Aynı fonksiyon `after_migrate`'te de çalışır (taze kurulum
geçmiş patch'leri çalıştırmadığı için).
"""

import frappe


def execute():
	for dt in (
		"platform_notification_event",
		"platform_notification_version",
		"platform_notification_template",
		"platform_notification_preference",
		"platform_notification_delivery",
		"platform_notification_settings",
		"commercial_consent_sync",
	):
		frappe.reload_doc("tradehub_core", "doctype", dt)
	from tradehub_core.notifications.seed import run

	run()

"""Platform Notification Event — yalnız bildirim servis katmanından yazılır.

Yönetim/kişisel kayıtlarda iş kuralları (revizyon kilidi, yayın, izin sırası) API katmanındadır.
Doğrudan /api/resource ya da Desk üzerinden yazma bu kuralları atlayacağından reddedilir.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.notifications.store import writing


class PlatformNotificationEvent(Document):
	def validate(self):
		if not writing():
			frappe.throw(
				_("Bu kayıt yalnız bildirim servisi üzerinden değiştirilebilir."), frappe.PermissionError
			)

	def on_trash(self):
		if not writing() and not frappe.flags.in_test:
			frappe.throw(_("Bu kayıt yalnız bildirim servisi üzerinden silinebilir."), frappe.PermissionError)

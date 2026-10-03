"""Platform Notification Settings — bildirim politikaları (özet saati, sessiz saat, test sınırları).

Sağlayıcı sırları burada tutulmaz; mevcut servis ayarlarından okunur.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document

HHMM = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


class PlatformNotificationSettings(Document):
	def validate(self):
		if self.digest_time and not HHMM.match(self.digest_time):
			frappe.throw(_("Özet saati SS:DD biçiminde olmalı."))
		if self.digest_timezone:
			from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

			try:
				ZoneInfo(self.digest_timezone)
			except (ZoneInfoNotFoundError, ValueError):
				frappe.throw(_("Geçersiz saat dilimi."))
		if (self.digest_group_limit or 0) < 1:
			self.digest_group_limit = 1

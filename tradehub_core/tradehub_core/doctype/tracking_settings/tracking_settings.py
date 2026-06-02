import re

import frappe
from frappe import _
from frappe.model.document import Document

_GTM_RE = re.compile(r"^GTM-[A-Z0-9]{5,8}$")
_NUMERIC_RE = re.compile(r"^\d+$")


class TrackingSettings(Document):
	def validate(self):
		self._validate_gtm_id()
		self._validate_numeric_id("metrica_id", "Yandex Metrica ID")
		self._validate_numeric_id("fb_pixel_id", "Facebook Pixel ID")
		self._validate_numeric_id("criteo_partner_id", "Criteo Partner ID")

	def _validate_gtm_id(self) -> None:
		val = (self.gtm_id or "").strip()
		self.gtm_id = val
		if val and not _GTM_RE.match(val):
			frappe.throw(
				_("GTM ID formatı geçersiz. Beklenen: GTM-XXXXXXX (5-8 alfanumerik karakter)."),
				frappe.ValidationError,
			)

	def _validate_numeric_id(self, field: str, label: str) -> None:
		val = (getattr(self, field, None) or "").strip()
		setattr(self, field, val)
		if val and not _NUMERIC_RE.match(val):
			frappe.throw(
				_("{0} sadece rakam içermelidir.").format(label),
				frappe.ValidationError,
			)

	def on_update(self):
		frappe.cache().delete_key("tradehub_tracking_config")

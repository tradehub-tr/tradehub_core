import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, getdate, today


ALLOWED_FILE_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png")


def _validate_tckn(value: str):
	"""Validate Turkish TCKN (11-digit, mod-10 algorithm)."""
	digits = value.strip()
	if not re.match(r"^\d{11}$", digits):
		frappe.throw(_("TCKN must be exactly 11 digits."))
	if digits[0] == "0":
		frappe.throw(_("TCKN cannot start with 0."))
	d = [int(c) for c in digits]
	odd = d[0] + d[2] + d[4] + d[6] + d[8]
	even = d[1] + d[3] + d[5] + d[7]
	if (odd * 7 - even) % 10 != d[9]:
		frappe.throw(_("Invalid TCKN."))
	if sum(d[:10]) % 10 != d[10]:
		frappe.throw(_("Invalid TCKN."))


def _validate_file_extension(file_url: str, field_label: str):
	"""Validate uploaded file extension."""
	if not file_url:
		return
	ext = file_url.rsplit(".", 1)[-1].lower() if "." in file_url else ""
	if f".{ext}" not in ALLOWED_FILE_EXTENSIONS:
		frappe.throw(
			_("{0}: Only PDF, JPG, and PNG files are allowed.").format(field_label)
		)


class KYBVerification(Document):
	def validate(self):
		self._validate_company_title()
		self._validate_tax_id()
		self._validate_trade_registry()
		self._validate_expiry_date()
		self._validate_file_attachments()

	def on_update(self):
		if self.has_value_changed("status"):
			self._sync_kyb_status()
			self._set_review_metadata()

	def _validate_company_title(self):
		if not self.company_title or not self.company_title.strip():
			frappe.throw(_("Company Title is required."))

	def _validate_tax_id(self):
		if not self.tax_id:
			return
		# MVP: only TCKN validation (tax_id_type defaults to TCKN)
		if self.tax_id_type == "TCKN":
			_validate_tckn(self.tax_id)

	def _validate_trade_registry(self):
		if self.trade_registry_number:
			cleaned = self.trade_registry_number.strip()
			if cleaned and not re.match(r"^[\d\-/]+$", cleaned):
				frappe.throw(_("Trade Registry Number must contain only digits, dashes, or slashes."))

	def _validate_expiry_date(self):
		if self.document_expiry_date:
			if getdate(self.document_expiry_date) < getdate(today()):
				frappe.throw(_("Document Expiry Date cannot be in the past."))

	def _validate_file_attachments(self):
		file_fields = [
			("identity_document", _("Kimlik Belgesi")),
			("imza_sirkuleri", _("İmza Sirküleri")),
			("ticaret_sicil_gazetesi", _("Ticaret Sicil Gazetesi")),
			("faaliyet_belgesi", _("Faaliyet Belgesi")),
			("vergi_levhasi", _("Vergi Levhası")),
		]
		for fieldname, label in file_fields:
			_validate_file_extension(self.get(fieldname) or "", label)

	def _sync_kyb_status(self):
		"""Sync KYB status to Seller Profile."""
		seller_profile = frappe.db.get_value(
			"Seller Profile", {"user": self.user}, "name"
		)
		if seller_profile:
			frappe.db.set_value(
				"Seller Profile", seller_profile, "kyb_status", self.status
			)

	def _set_review_metadata(self):
		"""Set verified_by and verified_at when status changes to Verified or Rejected."""
		if self.status in ("Verified", "Rejected"):
			if not self.verified_by:
				self.db_set("verified_by", frappe.session.user)
			if not self.verified_at:
				self.db_set("verified_at", now_datetime())

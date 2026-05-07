import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime, today

from tradehub_core.utils.notify import notify

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
		frappe.throw(_("{0}: Only PDF, JPG, and PNG files are allowed.").format(field_label))


class KYBVerification(Document):
	def validate(self):
		self._validate_company_title()
		self._validate_tax_id()
		self._validate_trade_registry()
		self._validate_expiry_date()
		self._validate_file_attachments()
		self._validate_rejection_reason()

	def _validate_rejection_reason(self):
		"""Rejected status için rejection_reason zorunlu (min 20 karakter).

		Defense in depth: status field'ı UI'da read_only olsa bile (form'dan
		manuel değiştirilemez), endpoint/console/migration'dan gelen save
		çağrılarında rejection_reason eksikse reject edilir.
		"""
		if self.status == "Rejected":
			reason = (self.rejection_reason or "").strip()
			if len(reason) < 20:
				frappe.throw(
					_(
						"Reddetme gerekçesi en az 20 karakter olmalı. Lütfen "
						"'Reddet' butonunu kullanın — gerekçe modal'ı açılır."
					),
					frappe.ValidationError,
				)

	def on_update(self):
		if self.has_value_changed("status"):
			previous = self.get_doc_before_save()
			previous_status = previous.status if previous else None
			self._sync_kyb_status()
			self._set_review_metadata()
			self._send_status_notifications(previous_status=previous_status)

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
		seller_profile = frappe.db.get_value("Seller Profile", {"user": self.user}, "name")
		if seller_profile:
			frappe.db.set_value("Seller Profile", seller_profile, "kyb_status", self.status)

	def _set_review_metadata(self):
		"""Status değişimlerinde inceleme metadata'sını güncelle.

		Semantik: ``verified_at`` / ``verified_by`` artık "ilk doğrulama" değil,
		"son inceleme" anlamı taşır (UI label'ları "Son İnceleme Tarihi" /
		"Son İnceleyen"). Her admin aksiyonu son inceleme olarak kaydedilir.

		"Pending"e geçiş = kullanıcı yeniden submit etti veya admin geri çekti;
		önceki inceleme bilgisi sıfırlanır ("henüz incelenmemiş" anlamı).

		"Verified"a geçişte eski ``rejection_reason`` temizlenir — onaylanmış
		bir kayıtta eski red gerekçesinin durması misleading.

		Tarihçe Frappe'in built-in Version DocType'ında tutuluyor
		(track_changes:1) — admin Frappe Desk Activity panelinden geçmişi görür.
		"""
		if self.status == "Pending":
			self.db_set("verified_by", None)
			self.db_set("verified_at", None)
			return

		if self.status in ("Verified", "Rejected", "Under Review", "Expired"):
			self.db_set("verified_by", frappe.session.user)
			self.db_set("verified_at", now_datetime())

		if self.status == "Verified" and self.rejection_reason:
			self.db_set("rejection_reason", "")

	def _send_status_notifications(self, previous_status: str = None):
		"""KYB durum değişikliklerinde satıcıya ve admin'e bildirim gönder.

		``previous_status`` admin bildirimini zenginleştirmek için kullanılır:
		- None / Draft / boş → ilk başvuru
		- Rejected → resubmit (admin'e "yeniden inceleme" mesajı)
		"""
		if not self.user:
			return

		company = self.company_title or self.name

		if self.status == "Under Review":
			notify(
				recipient_user=self.user,
				recipient_role="seller",
				type="system",
				title=_("KYB İncelemeye Alındı"),
				message=_("{0} için KYB doğrulama başvurunuz incelemeye alındı.").format(company),
				action_url="/pages/dashboard/kyb.html",
				reference_doctype="KYB Verification",
				reference_name=self.name,
			)
		elif self.status == "Verified":
			notify(
				recipient_user=self.user,
				recipient_role="seller",
				type="system",
				title=_("KYB Doğrulandı"),
				message=_("{0} için KYB doğrulamanız onaylandı.").format(company),
				action_url="/pages/dashboard/kyb.html",
				reference_doctype="KYB Verification",
				reference_name=self.name,
			)
		elif self.status == "Rejected":
			reason = self.rejection_reason or ""
			notify(
				recipient_user=self.user,
				recipient_role="seller",
				type="system",
				title=_("KYB Reddedildi"),
				message=_("{0} için KYB doğrulamanız reddedildi. {1}").format(company, reason),
				action_url="/pages/dashboard/kyb.html",
				reference_doctype="KYB Verification",
				reference_name=self.name,
			)
		elif self.status == "Expired":
			notify(
				recipient_user=self.user,
				recipient_role="seller",
				type="system",
				title=_("KYB Süresi Doldu"),
				message=_(
					"{0} için KYB doğrulamanızın süresi doldu. Lütfen belgelerinizi yenileyiniz."
				).format(company),
				action_url="/pages/dashboard/kyb.html",
				reference_doctype="KYB Verification",
				reference_name=self.name,
			)

		# Pending'e geçişte admin'lere bildirim — her gerçek geçişte gönderilir.
		# `has_value_changed("status")` zaten on_update'te kontrol ediliyor; aynı
		# save'de iki tetikleme olmaz. Spam önlemi: status flicker (Pending→Pending)
		# yapılmıyor (state machine kuralları + frontend hasDocumentChanges).
		if self.status == "Pending":
			# Resubmit (Rejected → Pending) ile ilk başvuruyu ayır
			is_resubmit = (previous_status or "") == "Rejected"
			if is_resubmit:
				admin_title = _("KYB Belgeleri Yenilendi")
				admin_message = _(
					"{0} reddedilmiş KYB başvurusu için yeni belgeler yükledi, yeniden inceleme bekliyor."
				).format(company)
			else:
				admin_title = _("KYB Doğrulama Başvurusu")
				admin_message = _("{0} yeni KYB doğrulama başvurusu bekliyor.").format(company)

			admins = frappe.get_all(
				"Has Role",
				filters={"role": "System Manager", "parenttype": "User"},
				fields=["parent"],
			)
			for admin in admins:
				notify(
					recipient_user=admin.parent,
					recipient_role="admin",
					type="system",
					title=admin_title,
					message=admin_message,
					action_url=f"/panel/app/kyb-verification/{self.name}",
					reference_doctype="KYB Verification",
					reference_name=self.name,
				)

"""KYC Verification controller.

Sprint 2.6 — Alıcı kimlik doğrulama. Kurumsal (default) / Bireysel toggle.
Onay → User Profile.kyc_status = Verified → satın alım kapısı açılır.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

ALLOWED_FILE_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".docx")


def _validate_vkn(value: str) -> None:
	"""Türkiye VKN: 10 veya 11 hane. Sprint 2.6 — esnek kabul (10 VKN, 11 TCKN-format)."""
	digits = (value or "").strip()
	if not re.match(r"^\d{10,11}$", digits):
		frappe.throw(_("Vergi Numarası 10-11 haneli olmalıdır."))


def _validate_tckn(value: str) -> None:
	"""Türkiye TCKN: 11 hane + mod-10 algoritması (resmi)."""
	digits = (value or "").strip()
	if not re.match(r"^\d{11}$", digits):
		frappe.throw(_("TCKN tam 11 haneli olmalıdır."))
	if digits[0] == "0":
		frappe.throw(_("TCKN '0' ile başlayamaz."))
	d = [int(c) for c in digits]
	odd = d[0] + d[2] + d[4] + d[6] + d[8]
	even = d[1] + d[3] + d[5] + d[7]
	if (odd * 7 - even) % 10 != d[9]:
		frappe.throw(_("TCKN doğrulama hatalı (10. hane)."))
	if sum(d[:10]) % 10 != d[10]:
		frappe.throw(_("TCKN doğrulama hatalı (11. hane)."))


def _validate_file_extension(file_url: str, field_label: str) -> None:
	if not file_url:
		return
	ext = file_url.rsplit(".", 1)[-1].lower() if "." in file_url else ""
	if f".{ext}" not in ALLOWED_FILE_EXTENSIONS:
		frappe.throw(_("{0}: Yalnızca PDF, JPG, PNG, WEBP, DOCX dosyaları yüklenebilir.").format(field_label))


class KYCVerification(Document):
	def validate(self) -> None:
		self._validate_required_fields()
		self._validate_tax_id()
		self._validate_identity_document()
		self._validate_rejection_reason()
		self._sync_email_field()

	def _validate_required_fields(self) -> None:
		"""Sprint 2.6: Hem Bireysel hem Kurumsal için zorunlu ortak alanlar.
		company_name yalnız Kurumsal iken zorunlu."""
		required: dict[str, str] = {
			"phone": _("Telefon"),
			"address": _("Adres"),
			"billing_address": _("Fatura Adresi"),
			"tax_id": _("Vergi Numarası"),
		}
		if self.account_type == "Business":
			required["company_name"] = _("Şirket Ünvanı")
		for fname, label in required.items():
			if not (getattr(self, fname, None) or "").strip():
				frappe.throw(_("{0} alanı zorunludur.").format(label))

	def _validate_tax_id(self) -> None:
		"""Bireysel: TCKN (11 hane mod-10). Kurumsal: VKN (10-11 hane)."""
		if not self.tax_id:
			return
		if self.account_type == "Individual":
			_validate_tckn(self.tax_id)
		else:
			_validate_vkn(self.tax_id)

	def _validate_identity_document(self) -> None:
		if not self.identity_document:
			frappe.throw(_("Kimlik Belgesi zorunludur."))
		_validate_file_extension(self.identity_document, _("Kimlik Belgesi"))

	def _validate_rejection_reason(self) -> None:
		"""Rejected/Suspended için rejection_reason zorunlu (min 20 karakter)."""
		if self.status in ("Rejected", "Suspended"):
			reason = (self.rejection_reason or "").strip()
			if len(reason) < 20:
				frappe.throw(
					_(
						"Red gerekçesi en az 20 karakter olmalı. Lütfen 'Reddet' "
						"butonunu kullanın — gerekçe modal'ı açılır."
					),
					frappe.ValidationError,
				)
			if not self.rejection_category:
				frappe.throw(
					_("Red kategorisi (Re-submit veya Suspended) seçilmelidir."),
					frappe.ValidationError,
				)

	def _sync_email_field(self) -> None:
		"""email_field her zaman User.email — kullanıcı değiştiremez (read-only)."""
		if self.user:
			self.email_field = frappe.db.get_value("User", self.user, "email") or self.user

	def on_update(self) -> None:
		if self.has_value_changed("status"):
			previous = self.get_doc_before_save()
			previous_status = previous.status if previous else None
			self._sync_kyc_status()
			self._set_review_metadata()
			self._sync_user_profile_account_type()
			self._maybe_suspend_user()
			self._send_status_notifications(previous_status=previous_status)

	def _sync_kyc_status(self) -> None:
		"""KYC.status → User Profile.kyc_status senkronu."""
		if not self.user:
			return
		up_name = frappe.db.get_value("User Profile", {"user": self.user}, "name")
		if not up_name:
			return
		# Suspended state User Profile'da ayrı handle edilir
		up_status_map = {
			"Pending": "Pending",
			"Verified": "Verified",
			"Rejected": "Rejected",
			"Suspended": "Suspended",
		}
		new_status = up_status_map.get(self.status)
		if new_status:
			frappe.db.set_value(
				"User Profile",
				up_name,
				"kyc_status",
				new_status,
				update_modified=False,
			)
			# Sprint 2.6 (revised): KYC Verified = satın alım yetkisi açılır
			if self.status == "Verified":
				frappe.db.set_value(
					"User Profile",
					up_name,
					"can_buy",
					1,
					update_modified=False,
				)
				frappe.db.set_value(
					"User Profile",
					up_name,
					"kyc_verified_at",
					now_datetime(),
					update_modified=False,
				)
			elif self.status in ("Rejected", "Suspended", "Pending"):
				frappe.db.set_value(
					"User Profile",
					up_name,
					"can_buy",
					0,
					update_modified=False,
				)

	def _set_review_metadata(self) -> None:
		"""Verified/Rejected/Suspended olduğunda reviewed_at + reviewed_by set."""
		if self.status in ("Verified", "Rejected", "Suspended"):
			if not self.reviewed_at:
				self.db_set("reviewed_at", now_datetime(), update_modified=False)
			if not self.reviewed_by:
				self.db_set("reviewed_by", frappe.session.user, update_modified=False)

	def _sync_user_profile_account_type(self) -> None:
		"""KYC Verified olduğunda User Profile.account_type ve hassas alanları
		(company_name, tax_id, phone) sync et. Cross-form prefill için."""
		if self.status != "Verified" or not self.user:
			return
		up_name = frappe.db.get_value("User Profile", {"user": self.user}, "name")
		if not up_name:
			return
		updates = {"account_type": self.account_type}
		if self.account_type == "Business":
			updates.update(
				{
					"company_name": self.company_name,
					"tax_id": self.tax_id,
					"phone": self.phone,
				}
			)
		frappe.db.set_value("User Profile", up_name, updates, update_modified=False)

	def _maybe_suspend_user(self) -> None:
		"""Suspended kategorisi → User Profile.status = 'Suspended'.
		Admin manuel olarak 'Active' yapana kadar tüm gate'ler kapalı."""
		if self.status != "Suspended" or not self.user:
			return
		up_name = frappe.db.get_value("User Profile", {"user": self.user}, "name")
		if up_name:
			frappe.db.set_value(
				"User Profile",
				up_name,
				"status",
				"Suspended",
				update_modified=False,
			)

	def _send_status_notifications(self, previous_status: str | None = None) -> None:
		"""Kullanıcı + admin'e durum değişikliği bildirimi."""
		try:
			from tradehub_core.utils.notify import notify
		except ImportError:
			return

		messages = {
			"Pending": (
				_("KYC başvurunuz alındı, inceleniyor."),
				_("Yeni KYC başvurusu — inceleyiniz."),
			),
			"Verified": (
				_("KYC doğrulamanız onaylandı, alışveriş yapabilirsiniz."),
				None,
			),
			"Rejected": (
				_("KYC başvurunuz reddedildi: {0}").format(self.rejection_reason or ""),
				None,
			),
			"Suspended": (
				_("Hesabınız askıya alındı: {0} — Destek ile iletişime geçin.").format(
					self.rejection_reason or ""
				),
				None,
			),
		}
		user_msg, admin_msg = messages.get(self.status, (None, None))

		if user_msg and self.user:
			try:
				notify(
					recipient=self.user,
					message=user_msg,
					action_url="/pages/dashboard/kyc.html",
					category="kyc",
				)
			except Exception:  # noqa: BLE001
				frappe.log_error(
					title="KYC notification failed",
					message=frappe.get_traceback(),
				)

		if admin_msg:
			try:
				notify(
					recipient_role="Marketplace Admin",
					message=admin_msg,
					action_url=f"/panel/app/kyc-verification/{self.name}",
					category="kyc_admin",
				)
			except Exception:  # noqa: BLE001
				frappe.log_error(
					title="KYC admin notification failed",
					message=frappe.get_traceback(),
				)

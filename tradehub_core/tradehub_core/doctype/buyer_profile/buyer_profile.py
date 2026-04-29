import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class BuyerProfile(Document):
	def validate(self):
		"""Form-level email_verified toggle audit + auto-fill metadata.

		Süper Admin Panel'in standart Save butonuyla yapılan toggle'lar bu hook
		üzerinden yakalanır.

		v15 dikkat: ``self.get_doc_before_save()`` validate fazında bazen None
		dönüyor; bu yüzden eski değeri DB'den **doğrudan** okuyoruz.

		Davranış:
		  • Form'dan email_verified=1 geldiyse: ``email_verified_at`` boş gelse
		    bile ``now_datetime()`` ile otomatik dolduruluyor; ``email_verified_method``
		    boşsa "admin_override" set ediliyor. (Yarı yazılmış durumu tek save'de
		    onarır — admin form'unda at boş kalmaz.)
		  • Form'dan email_verified=0 geldiyse: at + method temizlenir.
		  • State (0↔1) değişimi varsa Email Verification Log'a kayıt düşer.
		"""
		if self.is_new():
			return

		# DB'den eski değeri direkt oku (get_doc_before_save() güvenilmez)
		old_verified = bool(frappe.db.get_value("Buyer Profile", self.name, "email_verified"))
		new_verified = bool(self.email_verified)

		# Defansif auto-fill — state değişmemiş olsa bile yarı yazılmış alanları
		# tek save'de toparla (ör. method dolu, at boş gibi durumlar)
		if new_verified:
			if not self.email_verified_at:
				self.email_verified_at = now_datetime()
			if not self.email_verified_method:
				self.email_verified_method = "admin_override"
		else:
			# verified=0 ise metadata temizle (hem state değişimi hem de halihazırda 0
			# olup form'dan kalıntı değer gelmiş olabilecek durumlar için)
			self.email_verified_at = None
			self.email_verified_method = None

		# Audit log — yalnızca state gerçekten değiştiyse
		if old_verified == new_verified:
			return

		event = "admin_override" if new_verified else "unverified"
		actor = frappe.session.user

		try:
			from tradehub_core.api.v1.identity import _log_email_verification_event

			_log_email_verification_event(
				user=self.user,
				event=event,
				method=self.email_verified_method or "admin_override",
				actor=actor,
				reason="Form-level admin toggle (no reason captured)",
			)
		except Exception:
			# Audit log fail save'i engellemesin
			frappe.log_error(
				title="BuyerProfile.validate audit log failed",
				message=frappe.get_traceback(),
			)

	def on_update(self):
		if self.has_value_changed("status"):
			self._sync_status()

	def _sync_status(self):
		"""Sync User.enabled and Seller Profile status when Buyer Profile status changes."""
		enabled = 1 if self.status == "Active" else 0
		frappe.db.set_value("User", self.user, "enabled", enabled)

		# Keep Seller Profile in sync (same user, same account)
		seller_profile = frappe.db.get_value("Seller Profile", {"user": self.user}, "name")
		if seller_profile:
			frappe.db.set_value("Seller Profile", seller_profile, "status", self.status)

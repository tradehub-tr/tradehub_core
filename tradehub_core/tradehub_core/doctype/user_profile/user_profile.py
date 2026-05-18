import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class UserProfile(Document):
	def validate(self):
		self._validate_account_type_for_seller()
		self._validate_account_type_no_downgrade()
		self._audit_email_verified_state()

	def _validate_account_type_for_seller(self):
		"""KURAL: can_sell=1 ise account_type=Business ZORUNLU.
		Bireysel kullanıcı satıcı olamaz (B2B2B platform — KYB için vergi levhası şart)."""
		if self.can_sell and self.account_type != "Business":
			frappe.throw(
				_("Satıcı olabilmek için Kurumsal hesap tipi zorunludur (KYB için vergi levhası şart)."),
				title=_("Account Type Mismatch"),
			)

	def _validate_account_type_no_downgrade(self):
		"""KURAL: Individual → Business upgrade TEK YÖNLÜDÜR.
		Geri dönüş yasak çünkü historical Order'larda fatura/vergi tutarlılığı bozulur."""
		if self.is_new():
			return
		old = frappe.db.get_value("User Profile", self.name, "account_type")
		if old == "Business" and self.account_type == "Individual":
			frappe.throw(
				_("Kurumsal hesaptan Bireysel hesaba geri dönüş yapılamaz (historical Order tutarlılığı)."),
				title=_("Account Type Downgrade Forbidden"),
			)

	def _audit_email_verified_state(self):
		"""email_verified state diff yakala, Email Verification Log'a kayıt düş.
		Migration sırasında flags.ignore_validate=True ile atlatılır."""
		if self.is_new():
			return
		old_verified = bool(frappe.db.get_value("User Profile", self.name, "email_verified"))
		new_verified = bool(self.email_verified)

		if new_verified:
			if not self.email_verified_at:
				self.email_verified_at = now_datetime()
			if not self.email_verified_method:
				self.email_verified_method = "admin_override"
		else:
			self.email_verified_at = None
			self.email_verified_method = None

		if old_verified == new_verified:
			return

		event = "admin_override" if new_verified else "unverified"
		try:
			from tradehub_core.api.v1.identity import _log_email_verification_event

			_log_email_verification_event(
				user=self.user,
				event=event,
				method=self.email_verified_method or "admin_override",
				actor=frappe.session.user,
				reason="Form-level admin toggle (User Profile)",
			)
		except Exception:
			frappe.log_error(
				title="UserProfile.validate audit log failed",
				message=frappe.get_traceback(),
			)

	def on_update(self):
		if self.has_value_changed("status"):
			self._sync_user_enabled()

		if self.has_value_changed("can_sell"):
			self._on_can_sell_changed()

	def _sync_user_enabled(self):
		"""status değişimini User.enabled'e yansıt."""
		enabled = 1 if self.status == "Active" else 0
		frappe.db.set_value("User", self.user, "enabled", enabled, update_modified=False)

	def _on_can_sell_changed(self):
		"""can_sell=1 yapıldığında User.user_type System User olmalı (admin-panel erişimi).
		can_sell=0 yapıldığında ise account_type Business kalır (downgrade yasak)."""
		if self.can_sell:
			# Seller veya Hybrid → System User
			frappe.db.set_value("User", self.user, "user_type", "System User", update_modified=False)
		else:
			# can_sell kapatıldı; user_type değişmez (Hybrid → Buyer dönerse Website User'a düşmez)
			# Çünkü account_type Business kalır ve System User erişimi korunur (downgrade yasak)
			pass

	def before_insert(self):
		"""member_id auto-set: UP-XXXXXX format.
		Migration sırasında Patch 8'de bulk set edilir."""
		if not self.member_id:
			self.member_id = self._generate_member_id()
		if not self.created_via:
			self.created_via = "admin_panel"
		if not self.joined_at:
			self.joined_at = now_datetime()

	def _generate_member_id(self):
		"""UP-XXXXXX format member_id üret."""
		last = frappe.db.sql(
			"""SELECT member_id FROM `tabUser Profile`
			   WHERE member_id LIKE 'UP-%' ORDER BY creation DESC LIMIT 1"""
		)
		if last and last[0][0]:
			try:
				last_num = int(last[0][0].split("-")[1])
				return f"UP-{last_num + 1:06d}"
			except (IndexError, ValueError):
				pass
		return "UP-000001"

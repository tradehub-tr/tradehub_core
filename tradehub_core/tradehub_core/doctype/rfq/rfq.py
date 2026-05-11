import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.utils.notify import notify


class RFQ(Document):
	def before_insert(self):
		if not self.buyer:
			self.buyer = frappe.session.user

	def validate(self):
		self._validate_status_transition()

	def after_insert(self):
		self._notify_admins_new_rfq()

	def on_update(self):
		self._update_quote_count()
		self._send_status_notifications()

	def _send_status_notifications(self):
		old = self.get_doc_before_save()
		if not old or old.status == self.status:
			return

		if self.status == "Approved":
			notify(
				recipient_user=self.buyer,
				recipient_role="buyer",
				type="rfq",
				title=_("RFQ Onaylandı"),
				message=_("{0} numaralı teklif talebiniz onaylandı.").format(self.name),
				action_url=f"/buyer-dashboard?tab=rfq&rfq={self.name}",
				reference_doctype="RFQ",
				reference_name=self.name,
			)
			self._notify_matching_sellers()
		elif self.status == "Rejected":
			notify(
				recipient_user=self.buyer,
				recipient_role="buyer",
				type="rfq",
				title=_("RFQ Reddedildi"),
				message=_("{0} numaralı teklif talebiniz reddedildi.").format(self.name),
				action_url=f"/buyer-dashboard?tab=rfq&rfq={self.name}",
				reference_doctype="RFQ",
				reference_name=self.name,
			)
		elif self.status in ("Closed", "Completed"):
			self._notify_active_quote_sellers_on_close()

	def _notify_admins_new_rfq(self):
		"""A — Yeni RFQ açıldığında admin'lere bildirim."""
		admin_users = set()
		for role in ("System Manager", "Marketplace Admin"):
			try:
				role_users = frappe.get_all(
					"Has Role",
					filters={"role": role, "parenttype": "User"},
					pluck="parent",
				)
			except Exception:
				role_users = []
			for u in role_users:
				if u and u not in ("Administrator", "Guest"):
					admin_users.add(u)

		if not admin_users:
			return

		buyer_name = frappe.db.get_value("User", self.buyer, "full_name") or self.buyer
		for u in admin_users:
			notify(
				recipient_user=u,
				recipient_role="admin",
				type="rfq",
				title=_("Yeni RFQ Başvurusu"),
				message=_("{0} kullanıcısı yeni bir RFQ açtı: {1}").format(
					buyer_name, self.product_name or self.name
				),
				action_url=f"/app/rfq/{self.name}",
				reference_doctype="RFQ",
				reference_name=self.name,
			)

	def _notify_matching_sellers(self):
		"""B — Approved RFQ için eşleşen kategoride satıcılara bildirim."""
		if not self.category:
			return

		seller_profiles = set()

		# 1) Seller Category onaylı eşleşmeleri
		try:
			via_cat = frappe.get_all(
				"Seller Category",
				filters={
					"category": self.category,
					"status": "Active",
					"is_enabled": 1,
				},
				pluck="seller",
			)
			for sp in via_cat:
				if sp:
					seller_profiles.add(sp)
		except Exception:
			frappe.log_error(title="RFQ._notify_matching_sellers: Seller Category fetch")

		# 2) Aktif Listing'i olan satıcılar (Listing.seller_profile = seller_code)
		try:
			active_codes = frappe.get_all(
				"Listing",
				filters={
					"product_category": self.category,
					"status": ["in", ["Aktif", "Active"]],
				},
				pluck="seller_profile",
				distinct=True,
			)
			for code in active_codes:
				if not code:
					continue
				sp_name = frappe.db.get_value("Admin Seller Profile", {"seller_code": code}, "name")
				if sp_name:
					seller_profiles.add(sp_name)
		except Exception:
			frappe.log_error(title="RFQ._notify_matching_sellers: Listing fetch")

		if not seller_profiles:
			return

		# Profile → User (user veya email field'ından)
		profile_rows = frappe.get_all(
			"Admin Seller Profile",
			filters={"name": ["in", list(seller_profiles)]},
			fields=["name", "user", "email"],
		)

		category_label = (
			frappe.db.get_value("Product Category", self.category, "category_name") or self.category
		)
		seen_users = set()
		for sp in profile_rows:
			user = sp.get("user") or sp.get("email")
			if not user or user in seen_users:
				continue
			seen_users.add(user)
			notify(
				recipient_user=user,
				recipient_role="seller",
				type="rfq",
				title=_("Yeni Eşleşen RFQ"),
				message=_("{0} kategorisinde yeni bir teklif talebi açıldı: {1}").format(
					category_label, self.product_name or self.name
				),
				action_url=f"/pages/dashboard/inquiries.html?tab=marketplace&rfq={self.name}",
				reference_doctype="RFQ",
				reference_name=self.name,
			)

	def _notify_active_quote_sellers_on_close(self):
		"""C — RFQ Closed/Completed olduğunda aktif teklif sahiplerine bildirim."""
		quote_sellers = frappe.get_all(
			"RFQ Quote",
			filters={"rfq": self.name, "status": ["not in", ["Rejected", "Withdrawn"]]},
			fields=["seller"],
			distinct=True,
		)
		seen = set()
		title = _("RFQ Tamamlandı") if self.status == "Completed" else _("RFQ Kapatıldı")
		for q in quote_sellers:
			user = q.get("seller")
			if not user or user in seen:
				continue
			seen.add(user)
			notify(
				recipient_user=user,
				recipient_role="seller",
				type="rfq",
				title=title,
				message=_("{0} numaralı teklif talebi {1}.").format(
					self.name,
					_("tamamlandı") if self.status == "Completed" else _("kapatıldı"),
				),
				action_url=f"/app/rfq/{self.name}",
				reference_doctype="RFQ",
				reference_name=self.name,
			)

	def _validate_status_transition(self):
		if self.is_new():
			return
		old_status = self.get_doc_before_save()
		if not old_status:
			return
		old_status = old_status.status
		if old_status == self.status:
			return

		user = frappe.session.user
		is_admin = (
			user == "Administrator"
			or "System Manager" in frappe.get_roles(user)
			or "Marketplace Admin" in frappe.get_roles(user)
		)

		# Pending → Approved/Rejected: only admin
		if old_status == "Pending" and self.status in ("Approved", "Rejected"):
			if not is_admin:
				frappe.throw(_("Only administrators can approve or reject RFQs"))

	def _update_quote_count(self):
		count = frappe.db.count("RFQ Quote", {"rfq": self.name})
		if count != self.quote_count:
			self.db_set("quote_count", count)

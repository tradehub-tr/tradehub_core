import frappe
from frappe.model.document import Document


class SellerProfile(Document):
	def on_update(self):
		if self.has_value_changed("status"):
			self._sync_status()

		self._sync_to_related_docs()

	def _sync_status(self):
		"""Sync User.enabled and Buyer Profile status when Seller Profile status changes."""
		enabled = 1 if self.status == "Active" else 0
		frappe.db.set_value("User", self.user, "enabled", enabled)

		buyer_profile = frappe.db.get_value("Buyer Profile", {"user": self.user}, "name")
		if buyer_profile:
			frappe.db.set_value("Buyer Profile", buyer_profile, "status", self.status)

	def _sync_to_related_docs(self):
		"""Sync changed fields to Seller Application, Buyer Profile, and User doc."""

		# ── Seller Application sync ──
		app_name = frappe.db.get_value(
			"Seller Application", {"applicant_user": self.user}, "name"
		)
		if app_name:
			app_fields = {
				"business_name": "business_name",
				"seller_type": "seller_type",
				"tax_id": "tax_id",
				"contact_phone": "contact_phone",
				"country": "country",
				"tax_id_type": "tax_id_type",
				"tax_office": "tax_office",
				"address_line_1": "address_line_1",
				"city": "city",
				"bank_name": "bank_name",
				"iban": "iban",
				"account_holder_name": "account_holder_name",
			}
			for profile_field, app_field in app_fields.items():
				if self.has_value_changed(profile_field):
					frappe.db.set_value(
						"Seller Application", app_name, app_field, self.get(profile_field)
					)

		# ── Seller Name → Buyer Profile + User doc sync ──
		if self.has_value_changed("seller_name"):
			parts = (self.seller_name or "").strip().split(" ", 1)
			first_name = parts[0] if parts else ""
			last_name = parts[1] if len(parts) > 1 else ""

			# Update User doc
			frappe.db.set_value("User", self.user, "first_name", first_name)
			frappe.db.set_value("User", self.user, "last_name", last_name)

			# Update Buyer Profile
			buyer_profile = frappe.db.get_value("Buyer Profile", {"user": self.user}, "name")
			if buyer_profile:
				frappe.db.set_value("Buyer Profile", buyer_profile, "buyer_name", self.seller_name)

		# ── Contact Phone → Buyer Profile + User doc sync ──
		if self.has_value_changed("contact_phone"):
			frappe.db.set_value("User", self.user, "phone", self.contact_phone)
			buyer_profile = frappe.db.get_value("Buyer Profile", {"user": self.user}, "name")
			if buyer_profile:
				frappe.db.set_value("Buyer Profile", buyer_profile, "phone", self.contact_phone)

		# ── Country → Buyer Profile sync ──
		if self.has_value_changed("country"):
			buyer_profile = frappe.db.get_value("Buyer Profile", {"user": self.user}, "name")
			if buyer_profile:
				frappe.db.set_value("Buyer Profile", buyer_profile, "country", self.country)

		# ── Shared fields → Buyer Profile sync ──
		shared_fields = ["avatar", "website", "job_title", "year_established",
		                 "employee_count", "about_us", "selling_platforms",
		                 "city", "postal_code",
		                 "industry_preferences", "sourcing_frequency", "annual_spending"]
		buyer_profile = frappe.db.get_value("Buyer Profile", {"user": self.user}, "name")
		if buyer_profile:
			for field in shared_fields:
				if self.has_value_changed(field):
					frappe.db.set_value("Buyer Profile", buyer_profile, field, self.get(field))

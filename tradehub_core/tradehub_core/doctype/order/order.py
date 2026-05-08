import frappe
from frappe import _
from frappe.model.document import Document


class Order(Document):
	def validate(self):
		self._validate_seller_kyb_verified()

	def _validate_seller_kyb_verified(self):
		"""Sipariş alan satıcının KYB Verified olduğunu kanıtla.

		3 katmanlı sipariş gate'inin son sözü (cart.add_to_cart + cart.create_order +
		burada doctype-level). REST API, Frappe Desk, manuel SQL ya da bench shell
		üzerinden gelen save akışlarını da kapsar — Verified Seller rolü olmayan
		satıcı için Order kaydedilemez.

		Listing'in storefront'ta görünür olması (Active) bu kontrolden BAĞIMSIZDIR;
		burada sadece para hareketi (sipariş) engellenir. Satıcı KYB onaylanınca rol
		otomatik atanır (KYBVerification.on_update hook'u) ve sipariş kapısı açılır.
		"""
		if not self.seller:
			return

		seller_user = frappe.db.get_value("Admin Seller Profile", self.seller, "user")
		if not seller_user:
			return

		if "Verified Seller" not in frappe.get_roles(seller_user):
			seller_label = (
				frappe.db.get_value("Admin Seller Profile", self.seller, "company_name") or self.seller
			)
			frappe.throw(
				_("{0} satıcısının KYB doğrulaması tamamlanmadığı için sipariş oluşturulamaz.").format(
					seller_label
				),
				frappe.ValidationError,
			)

import frappe
from frappe import _
from frappe.model.document import Document


class CartItem(Document):
	def validate(self):
		if self.quantity is None or int(self.quantity) <= 0:
			frappe.throw(_("Miktar sıfırdan büyük olmalıdır"))

		# Numune satırları her zaman 1 adetle sınırlı (toptanla karışmasın diye ayrı row).
		if int(self.is_sample or 0) == 1 and int(self.quantity) != 1:
			frappe.throw(_("Numune için maksimum sipariş miktarı 1 adettir"))

		listing = frappe.db.get_value(
			"Listing",
			self.listing,
			[
				"status",
				"min_order_qty",
				"stock_qty",
				"track_inventory",
				"allow_backorders",
				"sample_price",
			],
			as_dict=True,
		)
		if not listing:
			frappe.throw(_("Ürün bulunamadı"))

		if listing.status != "Active":
			frappe.throw(_("Bu ürün şu an satışta değil"))

		# Numune satırları MOQ kontrolünden muaf, ama sample_price > 0 olmalı.
		if int(self.is_sample or 0) == 1:
			if not float(listing.sample_price or 0):
				frappe.throw(_("Bu ürün için numune satışı tanımlı değil"))
		else:
			min_qty = int(listing.min_order_qty or 1)
			if int(self.quantity) < min_qty:
				frappe.throw(_("Minimum sipariş miktarı: {0}").format(min_qty))

		if listing.track_inventory and not listing.allow_backorders:
			available = float(listing.stock_qty or 0)
			if available <= 0:
				frappe.throw(_("Bu ürün stokta yok"))
			if int(self.quantity) > available:
				frappe.throw(_("Yeterli stok yok. Mevcut stok: {0}").format(int(available)))

import frappe
from frappe import _
from frappe.model.document import Document


class SupportedCurrency(Document):
	def before_insert(self):
		if not self.display_order:
			max_order = frappe.db.sql(
				"SELECT MAX(display_order) FROM `tabSupported Currency`"
			)
			current_max = max_order[0][0] if max_order and max_order[0][0] else 0
			self.display_order = current_max + 1

	def validate(self):
		self.currency_code = self.currency_code.upper().strip()
		self._autofill_from_currency()

		if not self.symbol:
			frappe.throw(_("Symbol alani zorunludur. Frappe Currency tablosunda bu para birimi icin symbol tanimli degil, lutfen manuel girin."))

	def _autofill_from_currency(self):
		"""Auto-fill symbol from Frappe Currency if left empty by admin."""
		if not frappe.db.exists("Currency", self.currency_code):
			return

		if not self.symbol:
			symbol = frappe.db.get_value("Currency", self.currency_code, "symbol")
			if symbol:
				self.symbol = symbol

# Copyright (c) 2024, İstoç and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class PlatformInvoice(Document):
	def validate(self):
		self.calculate_totals()
		
	def calculate_totals(self):
		subtotal = 0.0
		total_tax = 0.0
		
		if self.items:
			for item in self.items:
				if item.quantity and item.unit_price:
					item.total_price = flt(item.quantity) * flt(item.unit_price)
					subtotal += item.total_price
					
					if item.tax_rate:
						item.tax_amount = item.total_price * (flt(item.tax_rate) / 100.0)
						total_tax += item.tax_amount
						
		self.subtotal = subtotal
		self.total_tax_amount = total_tax
		self.grand_total = subtotal + total_tax + flt(self.shipping_fee)

def flt(value):
	try:
		return float(value or 0)
	except ValueError:
		return 0.0

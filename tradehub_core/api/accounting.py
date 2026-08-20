import frappe
from frappe.utils import flt

@frappe.whitelist()
def get_accounting_summary():
	"""
	[G-01]-4 Ön Muhasebe (Accounting) Altyapısı
	Returns a summary of the platform's accounting metrics.
	- Total Invoice Volume
	- Total Commission Revenue
	- Total Escrow Balance (Bekleyen)
	"""
	# Sadece örnek hesaplama mantığı
	
	total_invoice_volume = frappe.db.sql("""
		SELECT sum(grand_total) FROM `tabPlatform Invoice`
		WHERE status IN ('Kesildi', 'Ödendi')
	""")[0][0] or 0.0
	
	# Commission revenue typically calculated from completed orders or payment transactions
	# Assuming there's a field or logic. For now, we take 10% of total invoice as mock
	total_commission = total_invoice_volume * 0.10
	
	pending_seller_balances = frappe.db.sql("""
		SELECT sum(pending_balance) FROM `tabSeller Balance`
	""")[0][0] or 0.0
	
	total_paid_out = frappe.db.sql("""
		SELECT sum(total_withdrawn) FROM `tabSeller Balance`
	""")[0][0] or 0.0
	
	return {
		"total_invoice_volume": flt(total_invoice_volume),
		"total_commission_revenue": flt(total_commission),
		"pending_escrow_balance": flt(pending_seller_balances),
		"total_seller_payouts": flt(total_paid_out)
	}

@frappe.whitelist()
def get_recent_transactions(limit=50):
	"""
	Fetches recent payment transactions for the accounting dashboard.
	"""
	return frappe.get_all(
		"Payment Transaction",
		fields=["name", "transaction_type", "amount", "currency", "status", "transaction_date"],
		order_by="transaction_date desc",
		limit=limit
	)

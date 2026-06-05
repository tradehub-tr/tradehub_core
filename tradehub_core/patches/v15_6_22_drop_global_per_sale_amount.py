import frappe


def execute():
	"""global_per_sale_amount alanı kaldırıldı — komisyon artık tamamen paket-bazlı
	(Subscription Plan). Single doctype'ın tabSingles'taki artık değerini temizle.
	İdempotent: kayıt yoksa no-op."""
	frappe.db.delete(
		"Singles",
		{"doctype": "Field Commission Settings", "field": "global_per_sale_amount"},
	)

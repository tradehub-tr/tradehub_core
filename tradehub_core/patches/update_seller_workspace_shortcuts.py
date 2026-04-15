import frappe


def execute():
	"""Delete old Satıcı Paneli workspace so migrate recreates it from JSON.
	Also hide TradeHub Core workspace from sidebar."""

	# Eski kullanıcı-customized workspace'i sil
	for name in ("Satıcı Paneli", "Tradehub Seller"):
		if frappe.db.exists("Workspace", name):
			frappe.delete_doc("Workspace", name, force=True, ignore_permissions=True)

	# TradeHub Core workspace'i sidebar'dan gizle
	if frappe.db.exists("Workspace", "TradeHub Core"):
		frappe.db.set_value("Workspace", "TradeHub Core", "public", 0)

	frappe.db.commit()

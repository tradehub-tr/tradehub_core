import frappe


def execute():
	"""Delete all Satıcı Paneli workspaces and hide TradeHub Core from sidebar.
	Migrate will recreate from JSON."""

	# Tüm eski workspace'leri sil
	for name in ("Satıcı Paneli", "Tradehub Seller"):
		if frappe.db.exists("Workspace", name):
			frappe.delete_doc("Workspace", name, force=True, ignore_permissions=True)

	# TradeHub Core workspace'i sidebar'dan gizle
	if frappe.db.exists("Workspace", "TradeHub Core"):
		frappe.delete_doc("Workspace", "TradeHub Core", force=True, ignore_permissions=True)

	frappe.db.commit()

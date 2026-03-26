import frappe


def execute():
	"""Delete old Satıcı Paneli workspace so migrate recreates it from JSON."""

	# Eski kullanıcı-customized workspace'i sil
	for name in ("Satıcı Paneli", "Tradehub Seller"):
		if frappe.db.exists("Workspace", name):
			frappe.delete_doc("Workspace", name, force=True, ignore_permissions=True)

	frappe.db.commit()

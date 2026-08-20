import frappe
from frappe import _

# ==========================================
# MODÜL 1: Lojistik Temel Altyapı & Mimari
# ==========================================

@frappe.whitelist()
def init_logistics_roles():
	"""
	02 — Rol ve yetki modelini uygula
	Ensures logistics roles exist and are assigned appropriately.
	"""
	roles = ["Logistics Manager", "Warehouse Operator", "Carrier Agent"]
	for role in roles:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": role,
				"desk_access": 1
			}).insert(ignore_permissions=True)
			
	return {"status": "success", "message": "Logistics roles initialized."}

@frappe.whitelist()
def get_logistics_catalogs():
	"""
	03 — Ana lojistik kataloglarını oluştur
	Returns active logistics providers and shipping methods.
	"""
	providers = frappe.get_all("Logistics Provider", fields=["name", "provider_name", "status"], filters={"status": "Active"})
	methods = frappe.get_all("Shipping Method", fields=["name", "method_name", "type"])
	
	return {
		"status": "success",
		"providers": providers,
		"methods": methods
	}

@frappe.whitelist()
def generate_mock_contract(tenant_id):
	"""
	MOCK-SÖZ — Mock sözleşme paketi
	Generates a mock logistics contract for a seller/tenant.
	"""
	# In a real scenario, this would create an agreement document.
	contract_id = f"CONT-LOG-{tenant_id}-001"
	frappe.logger("logistics").info(f"Mock contract {contract_id} created for tenant {tenant_id}")
	return {
		"status": "success",
		"contract_id": contract_id,
		"message": "Sözleşme taslağı başarıyla oluşturuldu."
	}

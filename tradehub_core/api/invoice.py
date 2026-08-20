import frappe
from frappe import _

@frappe.whitelist()
def generate_invoice_from_order(order_name):
	"""
	Generate a Platform Invoice from an existing Order.
	[G-01]-1 Sistem Fatura Veri Modeli
	"""
	order = frappe.get_doc("Order", order_name)
	
	# Check if invoice already exists
	existing = frappe.get_all("Platform Invoice", filters={"order": order_name}, limit=1)
	if existing:
		return frappe.get_doc("Platform Invoice", existing[0].name)
		
	invoice = frappe.new_doc("Platform Invoice")
	invoice.invoice_type = "Satış Faturası"
	invoice.status = "Taslak"
	invoice.order = order.name
	invoice.buyer = order.buyer
	invoice.seller = order.seller
	invoice.currency = order.currency
	
	# Copy Billing Info
	invoice.billing_type = order.billing_type
	invoice.billing_company_name = order.billing_company_name
	invoice.billing_tax_office = order.billing_tax_office
	invoice.billing_tax_number = order.billing_tax_number
	invoice.billing_tcn = order.billing_tcn
	invoice.billing_e_invoice = order.billing_e_invoice
	
	if order.billing_same_as_shipping:
		invoice.billing_address = order.shipping_address
	else:
		invoice.billing_address = order.billing_address
		invoice.billing_city = order.billing_city
		invoice.billing_district = order.billing_district
		invoice.billing_postal_code = order.billing_postal_code
		
	invoice.shipping_fee = order.shipping_fee
	
	# Copy Items
	for item in order.get("items"):
		invoice.append("items", {
			"listing": item.listing,
			"item_name": item.listing_title,
			"variation": item.variation,
			"quantity": item.quantity,
			"unit_price": item.unit_price,
			"tax_rate": 20, # Defaulting to 20% for now
		})
		
	invoice.insert(ignore_permissions=True)
	return invoice

@frappe.whitelist()
def upload_manual_invoice(invoice_name, file_url):
	"""
	[G-01]-2 Manuel Fatura Upload
	Allows a seller to upload a manual invoice document (PDF) to the Platform Invoice.
	"""
	invoice = frappe.get_doc("Platform Invoice", invoice_name)
	
	# Ensure the user has permission to upload for this invoice
	# (In a real scenario, check if frappe.session.user == seller)
	
	# We can attach it using standard frappe attachments
	attachment = frappe.get_doc({
		"doctype": "File",
		"file_url": file_url,
		"attached_to_doctype": "Platform Invoice",
		"attached_to_name": invoice.name,
		"is_private": 1
	})
	attachment.insert(ignore_permissions=True)
	
	invoice.status = "Kesildi"
	invoice.save(ignore_permissions=True)
	
	return {"status": "success", "file": attachment.name}

@frappe.whitelist()
def send_to_e_invoice_integrator(invoice_name):
	"""
	[G-01]-3 GİB E-Invoice API Entegrasyonu
	Sends the invoice to the external E-Invoice Integrator (e.g. Uyumsoft/Logo/GİB).
	"""
	invoice = frappe.get_doc("Platform Invoice", invoice_name)
	
	if invoice.invoice_type not in ["e-Fatura", "e-Arşiv"]:
		frappe.throw(_("Sadece e-Fatura veya e-Arşiv türündeki faturalar entegratöre gönderilebilir."))
		
	if invoice.e_invoice_status == "Approved":
		frappe.throw(_("Bu fatura zaten GİB tarafından onaylanmıştır."))
		
	# MOCK: Call external integrator API here
	# response = e_invoice_provider.send_invoice(invoice.as_dict())
	
	import uuid
	invoice.e_invoice_uuid = str(uuid.uuid4())
	invoice.e_invoice_id = f"GIB2024{frappe.utils.random_string(9).upper()}"
	invoice.e_invoice_status = "Pending"
	invoice.status = "Kesildi"
	
	invoice.save(ignore_permissions=True)
	
	return {"status": "success", "message": _("Fatura başarıyla entegratöre iletildi. Durum: Bekliyor.")}

@frappe.whitelist()
def check_e_invoice_status(invoice_name):
	"""
	Polls the integrator to check if GİB approved the invoice.
	"""
	invoice = frappe.get_doc("Platform Invoice", invoice_name)
	
	if not invoice.e_invoice_uuid:
		frappe.throw(_("Bu faturanın E-Fatura UUID'si yok."))
		
	# MOCK: check external status
	# status = e_invoice_provider.check_status(invoice.e_invoice_uuid)
	
	invoice.e_invoice_status = "Approved"
	invoice.save(ignore_permissions=True)
	
	return {"status": "success", "e_invoice_status": invoice.e_invoice_status}


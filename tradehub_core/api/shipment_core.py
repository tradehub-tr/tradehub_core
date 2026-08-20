import frappe
from frappe import _

# ==========================================
# MODÜL 2: Sevkiyat ve Operasyon Çekirdeği
# ==========================================

@frappe.whitelist()
def split_order_to_shipments(order_name):
	"""
	05 — Çok satıcılı ve bölünmüş sevkiyatı geliştir
	Splits a master order into multiple Shipment records based on the seller.
	"""
	order = frappe.get_doc("Order", order_name)
	
	if order.status not in ["Paid", "Processing"]:
		frappe.throw(_("Sipariş henüz sevkiyat aşamasında değil."))

	# Group order items by seller
	seller_items = {}
	for item in order.items:
		seller = item.seller_profile
		if not seller:
			continue
		if seller not in seller_items:
			seller_items[seller] = []
		seller_items[seller].append(item)

	created_shipments = []

	for seller, items in seller_items.items():
		shipment = frappe.new_doc("Shipment")
		shipment.order = order.name
		shipment.buyer = order.buyer
		shipment.seller_profile = seller
		shipment.status = "Pending"
		shipment.shipment_type = "Standard"
		
		# In real case, we'd also copy addresses to address_snapshots
		
		for item in items:
			shipment.append("items", {
				"item_code": item.item_code,
				"qty": item.qty,
				"rate": item.rate
			})
			
		shipment.insert(ignore_permissions=True)
		created_shipments.append(shipment.name)
		
	# Update order status to indicate shipments are created
	if created_shipments:
		frappe.db.set_value("Order", order_name, "status", "Shipped")
		
	return {
		"status": "success",
		"message": f"{len(created_shipments)} adet sevkiyat başarıyla oluşturuldu.",
		"shipments": created_shipments
	}

@frappe.whitelist()
def create_manual_shipment(seller_profile, buyer, items_data, carrier=None):
	"""
	06 — Manuel ve offline sevkiyat akışlarını geliştir
	Creates a shipment directly without an order (Offline/B2B context).
	"""
	import json
	
	shipment = frappe.new_doc("Shipment")
	shipment.seller_profile = seller_profile
	shipment.buyer = buyer
	shipment.status = "Pending"
	shipment.shipment_type = "Offline"
	shipment.carrier = carrier
	
	items = json.loads(items_data) if isinstance(items_data, str) else items_data
	for item in items:
		shipment.append("items", {
			"item_code": item.get("item_code"),
			"qty": item.get("qty", 1),
			"rate": item.get("rate", 0)
		})
		
	shipment.insert(ignore_permissions=True)
	
	return {
		"status": "success",
		"shipment_id": shipment.name
	}

@frappe.whitelist()
def update_shipment_status(shipment_name, new_status, tracking_number=None):
	"""
	07 — Satıcı teslimatı ve alıcı teslim alma akışlarını geliştir
	Updates shipment status through its lifecycle.
	"""
	valid_statuses = ["Pending", "Picked Up", "In Transit", "Out for Delivery", "Delivered", "Exception", "Returned"]
	
	if new_status not in valid_statuses:
		frappe.throw(_("Geçersiz kargo durumu."))
		
	shipment = frappe.get_doc("Shipment", shipment_name)
	shipment.status = new_status
	
	if tracking_number:
		shipment.tracking_number = tracking_number
		
	shipment.save(ignore_permissions=True)
	
	# Also record a shipment event for tracking
	event = frappe.new_doc("Shipment Event")
	event.shipment = shipment_name
	event.status = new_status
	event.timestamp = frappe.utils.now_datetime()
	event.insert(ignore_permissions=True)
	
	return {"status": "success", "message": f"Kargo durumu {new_status} olarak güncellendi."}

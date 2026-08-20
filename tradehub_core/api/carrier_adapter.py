import frappe
from frappe import _

# ==========================================
# MODÜL 3: Kargo Entegrasyon & Takip
# ==========================================

class BaseCarrierAdapter:
	"""
	09 — Kargo entegrasyon platformunu ve adapter çekirdeğini geliştir
	Base class for all carrier integrations (Yurtiçi, Aras, PTT vb.)
	"""
	def __init__(self, carrier_name):
		self.carrier_name = carrier_name
		self.settings = frappe.get_doc("Logistics Provider", carrier_name)
		
	def create_shipment(self, shipment_doc):
		"""
		10 — Her kargo firması için standart entegrasyon görev sırasını uygula
		Must return a tracking number and barcode data.
		"""
		raise NotImplementedError("create_shipment must be implemented by the specific carrier adapter.")
		
	def track_shipment(self, tracking_number):
		"""
		11 — Takip ve durum yönetimi otomasyonunu geliştir
		Returns current status from the carrier's API.
		"""
		raise NotImplementedError("track_shipment must be implemented by the specific carrier adapter.")


class YurticiKargoAdapter(BaseCarrierAdapter):
	def create_shipment(self, shipment_doc):
		# Mock API call to Yurtiçi Kargo
		frappe.logger("logistics").info(f"Yurtiçi Kargo API çağrısı yapılıyor: Sipariş {shipment_doc.order}")
		return {
			"tracking_number": f"YURTICI-{frappe.utils.generate_hash(length=8).upper()}",
			"barcode_url": "https://api.yurticikargo.com/mock/barcode.png"
		}
		
	def track_shipment(self, tracking_number):
		# Mock API tracking
		return {
			"status": "In Transit",
			"description": "Kargo yola çıktı - Transfer Merkezinde"
		}


@frappe.whitelist()
def generate_carrier_barcode(shipment_name):
	"""
	Entry point for the frontend to request a barcode generation.
	"""
	shipment = frappe.get_doc("Shipment", shipment_name)
	if not shipment.carrier:
		frappe.throw(_("Lütfen kargo firması seçiniz."))
		
	adapter = None
	if shipment.carrier == "Yurtiçi Kargo":
		adapter = YurticiKargoAdapter(shipment.carrier)
	# Diğer kargo firmaları buraya eklenebilir.
	else:
		frappe.throw(_("Seçilen kargo firması için entegrasyon bulunamadı."))
		
	result = adapter.create_shipment(shipment)
	
	shipment.tracking_number = result["tracking_number"]
	shipment.save(ignore_permissions=True)
	
	return {
		"status": "success",
		"tracking_number": result["tracking_number"],
		"barcode_url": result["barcode_url"]
	}

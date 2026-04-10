from frappe import _


def get_data():
	"""
	Seller Profile form'unun altındaki "Connections" bölümünde
	ilgili Addresses kayıtlarını listeler.
	"""
	return {
		"fieldname": "seller",
		"transactions": [
			{"label": _("Adresler"), "items": ["Addresses"]},
		],
	}

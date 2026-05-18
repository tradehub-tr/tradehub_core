from frappe import _


def get_data():
	return {
		"fieldname": "user",
		"non_standard_fieldnames": {
			"Order": "buyer",
			"Cart": "buyer",
			"RFQ": "buyer",
			"Payment Transaction": "buyer",
			"KYB Verification": "user",
			"Seller Application": "applicant_user",
			"Addresses": "user",
			"Buyer Favorite List": "user",
			"Admin Seller Profile": "user",
		},
		"transactions": [
			{
				"label": _("Alışveriş"),
				"items": ["Order", "Cart", "RFQ", "Payment Transaction"],
			},
			{
				"label": _("Mağaza"),
				"items": ["Admin Seller Profile"],
			},
			{
				"label": _("Doğrulama"),
				"items": ["KYB Verification", "Seller Application"],
			},
			{
				"label": _("Adres & Favori"),
				"items": ["Addresses", "Buyer Favorite List"],
			},
		],
	}

import frappe


def execute():
	currencies = [
		{
			"currency_code": "TRY",
			"symbol": "\u20ba",
			"name_en": "Turkish Lira",
			"name_tr": "T\u00fcrk Liras\u0131",
			"decimal_places": 2,
			"display_order": 1,
			"is_enabled": 1,
		},
		{
			"currency_code": "USD",
			"symbol": "$",
			"name_en": "US Dollar",
			"name_tr": "Amerikan Dolar\u0131",
			"decimal_places": 2,
			"display_order": 2,
			"is_enabled": 1,
		},
		{
			"currency_code": "EUR",
			"symbol": "\u20ac",
			"name_en": "Euro",
			"name_tr": "Euro",
			"decimal_places": 2,
			"display_order": 3,
			"is_enabled": 1,
		},
		{
			"currency_code": "GBP",
			"symbol": "\u00a3",
			"name_en": "British Pound",
			"name_tr": "\u0130ngiliz Sterlini",
			"decimal_places": 2,
			"display_order": 4,
			"is_enabled": 0,
		},
		{
			"currency_code": "CNY",
			"symbol": "\u00a5",
			"name_en": "Chinese Yuan",
			"name_tr": "\u00c7in Yuan\u0131",
			"decimal_places": 2,
			"display_order": 5,
			"is_enabled": 0,
		},
	]

	for c in currencies:
		if not frappe.db.exists("Supported Currency", c["currency_code"]):
			doc = frappe.new_doc("Supported Currency")
			doc.update(c)
			doc.insert(ignore_permissions=True)

	frappe.db.commit()

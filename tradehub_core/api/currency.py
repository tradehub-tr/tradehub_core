import frappe
from frappe import _


COUNTRY_CURRENCY_MAP = {
	"TR": "TRY",
	"US": "USD",
	"GB": "GBP",
	"DE": "EUR",
	"FR": "EUR",
	"IT": "EUR",
	"ES": "EUR",
	"NL": "EUR",
	"BE": "EUR",
	"AT": "EUR",
	"PT": "EUR",
	"GR": "EUR",
	"IE": "EUR",
	"FI": "EUR",
	"CN": "CNY",
	"HK": "CNY",
	"TW": "CNY",
}


@frappe.whitelist(allow_guest=True)
def get_currency_settings():
	"""Get supported currencies, exchange rates, and default currency."""
	currencies = _get_supported_currencies()
	rates = _get_exchange_rates()

	detected_country = _detect_country()
	default_currency = COUNTRY_CURRENCY_MAP.get(detected_country, "USD")

	return {
		"currencies": currencies,
		"rates": rates,
		"defaultCurrency": default_currency,
		"detectedCountry": detected_country,
		"baseCurrency": "USD",
	}


@frappe.whitelist(allow_guest=True)
def convert_price(amount, from_currency="USD", to_currency="TRY"):
	"""Convert a price from one currency to another."""
	amount = float(amount)

	if from_currency == to_currency:
		return {
			"amount": amount,
			"formatted": _format_currency(amount, to_currency),
			"currency": to_currency,
			"rate": 1,
		}

	rate = _get_exchange_rate(from_currency, to_currency)
	converted = round(amount * rate, 2)

	return {
		"amount": converted,
		"formatted": _format_currency(converted, to_currency),
		"currency": to_currency,
		"rate": rate,
	}


@frappe.whitelist()
def get_currency_info(currency_code):
	"""Return symbol, name, and next display_order for a Frappe Currency record."""
	result = {"symbol": "", "currency_name": "", "next_order": 1}

	max_order = frappe.db.sql(
		"SELECT MAX(display_order) FROM `tabSupported Currency`"
	)
	result["next_order"] = (max_order[0][0] or 0) + 1 if max_order and max_order[0] else 1

	if currency_code and frappe.db.exists("Currency", currency_code):
		info = frappe.db.get_value(
			"Currency", currency_code, ["symbol", "currency_name"], as_dict=True
		)
		if info:
			result["symbol"] = info.symbol or ""
			result["currency_name"] = info.currency_name or ""

	return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_supported_currencies():
	"""Read enabled currencies from Supported Currency DocType."""
	rows = frappe.get_all(
		"Supported Currency",
		filters={"is_enabled": 1},
		fields=["currency_code", "symbol", "name_en", "name_tr", "decimal_places"],
		order_by="display_order asc",
	)

	if rows:
		return [
			{
				"code": r.currency_code,
				"symbol": r.symbol,
				"name": r.name_en,
				"nameTr": r.name_tr,
				"decimalPlaces": r.decimal_places,
			}
			for r in rows
		]

	return [
		{"code": "TRY", "symbol": "\u20ba", "name": "Turkish Lira", "nameTr": "T\u00fcrk Liras\u0131", "decimalPlaces": 2},
		{"code": "USD", "symbol": "$", "name": "US Dollar", "nameTr": "Amerikan Dolar\u0131", "decimalPlaces": 2},
		{"code": "EUR", "symbol": "\u20ac", "name": "Euro", "nameTr": "Euro", "decimalPlaces": 2},
	]


def _get_exchange_rates():
	"""Read active exchange rates from Currency Rate Pair DocType."""
	rates = {}
	pairs = frappe.get_all(
		"Currency Rate Pair",
		filters={"is_active": 1},
		fields=["from_currency", "to_currency", "rate", "last_updated"],
	)

	for p in pairs:
		if p.from_currency not in rates:
			rates[p.from_currency] = {p.from_currency: 1}
		rates[p.from_currency][p.to_currency] = p.rate or 1
		if p.last_updated:
			rates[p.from_currency]["last_updated"] = str(p.last_updated)

	if not rates:
		rates = {
			"USD": {"USD": 1, "EUR": 0.92, "TRY": 38.50, "GBP": 0.79, "CNY": 7.25},
		}

	return rates


def _get_exchange_rate(from_currency, to_currency):
	"""Get exchange rate between two currencies."""
	rate = frappe.db.get_value(
		"Currency Rate Pair",
		f"{from_currency}-{to_currency}",
		"rate",
	)
	if rate:
		return float(rate)

	# Try reverse
	reverse_rate = frappe.db.get_value(
		"Currency Rate Pair",
		f"{to_currency}-{from_currency}",
		"rate",
	)
	if reverse_rate and float(reverse_rate) > 0:
		return 1.0 / float(reverse_rate)

	return 1.0


def _get_currency_meta(currency_code):
	"""Get symbol and decimal_places from Supported Currency."""
	meta = frappe.db.get_value(
		"Supported Currency",
		currency_code,
		["symbol", "decimal_places"],
		as_dict=True,
	)
	if meta:
		return meta
	return {"symbol": currency_code, "decimal_places": 2}


def _format_currency(amount, currency_code):
	"""Format amount with currency symbol."""
	meta = _get_currency_meta(currency_code)
	symbol = meta["symbol"]
	decimals = meta["decimal_places"]

	if currency_code == "TRY":
		formatted = f"{amount:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
		return f"{symbol}{formatted}"

	return f"{symbol}{amount:,.{decimals}f}"


def _detect_country():
	"""Detect user's country from request headers."""
	if not frappe.request:
		return "TR"

	country = frappe.request.headers.get("CF-IPCountry", "")
	if country and country != "XX":
		return country.upper()

	country = frappe.request.headers.get("X-Country", "")
	if country:
		return country.upper()

	accept_lang = frappe.request.headers.get("Accept-Language", "")
	if accept_lang:
		lang = accept_lang.split(",")[0].split("-")
		if len(lang) > 1:
			return lang[1].upper()
		lang_country = {
			"tr": "TR", "en": "US", "de": "DE", "fr": "FR",
			"it": "IT", "es": "ES", "zh": "CN", "ja": "JP",
		}
		return lang_country.get(lang[0].lower(), "US")

	return "US"

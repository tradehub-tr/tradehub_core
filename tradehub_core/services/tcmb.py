import frappe
from frappe import _
from frappe.utils import now_datetime

TCMB_TODAY_URL = "https://www.tcmb.gov.tr/kurlar/today.xml"


def fetch_and_update_rates():
	"""Daily scheduler job: fetch TCMB exchange rates and update Currency Rate Pair."""
	from xml.etree import ElementTree

	import requests

	try:
		resp = requests.get(
			TCMB_TODAY_URL,
			timeout=15,
			headers={
				"User-Agent": "TradeHub/1.0",
			},
		)
		resp.raise_for_status()
	except Exception as e:
		frappe.log_error(
			message=f"TCMB HTTP request failed: {e}",
			title=_("TCMB Kur Hatasi"),
		)
		return {"success": False, "error": str(e)}

	try:
		root = ElementTree.fromstring(resp.content)
	except Exception as e:
		frappe.log_error(
			message=f"TCMB XML parse failed: {e}",
			title=_("TCMB XML Hatasi"),
		)
		return {"success": False, "error": str(e)}

	# Read only ENABLED currencies from Supported Currency
	supported = frappe.get_all("Supported Currency", filters={"is_enabled": 1}, fields=["currency_code"])
	tracked_codes = set(sc.currency_code for sc in supported)
	tracked_codes.add("TRY")  # Always track TRY

	# Parse ALL currencies from TCMB XML (they are all TRY-based)
	try_rates = {"TRY": 1.0}

	for elem in root.findall("Currency"):
		code = elem.get("CurrencyCode")
		if not code:
			continue

		forex_selling = elem.find("ForexSelling")
		if forex_selling is None or not forex_selling.text or not forex_selling.text.strip():
			continue

		unit_elem = elem.find("Unit")
		unit = int(unit_elem.text) if unit_elem is not None and unit_elem.text else 1

		try:
			rate_per_unit = float(forex_selling.text.strip())
			try_rates[code] = rate_per_unit / unit
		except ValueError:
			continue

	if len(try_rates) < 2:
		frappe.log_error(
			message="No valid ForexSelling rates found in TCMB XML",
			title=_("TCMB Veri Hatasi"),
		)
		return {"success": False, "error": "No valid rates"}

	# Create pairs for all tracked currencies that exist in TCMB
	now = now_datetime()
	updated_pairs = []

	for from_code in tracked_codes:
		if from_code not in try_rates:
			continue
		for to_code in tracked_codes:
			if from_code == to_code:
				continue
			if to_code not in try_rates:
				continue

			rate = round(try_rates[from_code] / try_rates[to_code], 6)
			pair_name = f"{from_code}-{to_code}"

			if frappe.db.exists("Currency Rate Pair", pair_name):
				frappe.db.set_value(
					"Currency Rate Pair",
					pair_name,
					{
						"rate": rate,
						"is_active": 1,
						"last_updated": now,
					},
					update_modified=False,
				)
			else:
				doc = frappe.new_doc("Currency Rate Pair")
				doc.from_currency = from_code
				doc.to_currency = to_code
				doc.rate = rate
				doc.is_active = 1
				doc.last_updated = now
				doc.insert(ignore_permissions=True)

			updated_pairs.append(pair_name)

	# Remove pairs that no longer belong to tracked currencies
	all_pairs = frappe.get_all("Currency Rate Pair", fields=["name"])
	valid_set = set(updated_pairs)
	deleted = 0
	for p in all_pairs:
		if p.name not in valid_set:
			frappe.delete_doc("Currency Rate Pair", p.name, ignore_permissions=True)
			deleted += 1

	frappe.db.commit()

	# Y3 — Kur değişti; listing'lerin baz-birim (TRY) fiyatlarını tazele ki
	# fiyat filtresi/sıralaması güncel kurla çalışsın.
	refresh_listing_price_base()

	return {
		"success": True,
		"pairs_updated": len(updated_pairs),
		"pairs_deleted": deleted,
		"currencies": list(tracked_codes & set(try_rates.keys())),
		"updated_at": str(now),
	}


def refresh_listing_price_base():
	"""Tüm listing'lerin selling_price_base (TRY) alanını güncel kurla yeniden
	hesaplar. Para birimi başına TEK parametreli bulk UPDATE (N+1 yok).

	TCMB job'undan sonra çağrılır; ayrıca her Listing.validate'inde tekil hesap
	yapılır (bkz. Listing._to_base_price)."""
	from tradehub_core.api.currency import _get_exchange_rate_strict

	currencies = frappe.db.get_all("Listing", fields=["currency"], distinct=True, pluck="currency")
	for cur in currencies:
		code = cur or "TRY"
		rate = 1.0 if code == "TRY" else _get_exchange_rate_strict(code, "TRY")
		if rate is None:
			# Kur çifti yok — base price'ı ×1.0 ile BOZMA; son değeri koru, logla.
			frappe.log_error(
				f"{code}-TRY kuru yok; selling_price_base güncellenmedi.",
				"refresh_listing_price_base",
			)
			continue
		frappe.db.sql(
			"""UPDATE `tabListing` SET selling_price_base = ROUND(selling_price * %s, 2)
			WHERE COALESCE(currency, 'TRY') = %s""",
			(rate, code),
		)
	frappe.db.commit()


@frappe.whitelist()
def manual_refresh():
	"""Admin: manually trigger TCMB rate fetch."""
	frappe.only_for("System Manager")
	result = fetch_and_update_rates()
	if result.get("success"):
		frappe.msgprint(
			_("Kurlar guncellendi: {0} cift, {1}").format(
				result["pairs_updated"], ", ".join(sorted(result["currencies"]))
			),
			title=_("TCMB Kur Guncelleme"),
			indicator="green",
		)
	else:
		frappe.msgprint(
			_("Kur guncelleme basarisiz: {0}").format(result.get("error", "")),
			title=_("TCMB Hata"),
			indicator="red",
		)
	return result

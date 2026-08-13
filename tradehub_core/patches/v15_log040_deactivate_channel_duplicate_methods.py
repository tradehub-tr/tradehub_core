# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-040: Kanal kopyasi Shipping Method kayitlarini pasiflestir (idempotent).

Neden gerekli:
	LOG-024 ilk surumu 5 Shipping Channel'in her biri icin ayni adla bir
	Shipping Method uretmisti. Bu, TUR-104'un "tasima yontemi ile isletim kanali
	bagimsizdir" kabul kriterini veri duzeyinde cigniyor ve satici listing
	formundaki yontem dropdown'ina anlamsiz secenekler dusuruyordu.

Neden SILINMIYOR:
	Shipping Method global bir katalog ve `Shipping Method Item` uzerinden
	Listing'lere baglanabiliyor. Silmek link kirar ve geri alinamaz.
	`is_active = 0` storefront'tan dusurmeye yeterli
	(`api/listing.py` `filters={"is_active": 1}` ile okuyor) ve geri alinabilir.

Benimsenmis kayitlara DOKUNULMAZ:
	Bir satici bu yontemi bir listing'e baglamissa ya da uzerinde fiyat
	tanimlanmissa kayit artik "seed artigi" degil, kullanilan veridir — atlanir
	ve rapora yazilir.
"""

from __future__ import annotations

import frappe

# LOG-024 ilk surumunun urettigi kayit adlari (autoname field:method_name)
CHANNEL_DUPLICATE_METHODS: tuple[str, ...] = (
	"Kargo",
	"Ambar",
	"Kurye",
	"Satıcı Aracı",
	"Alıcı Teslim Alma",
)


def execute() -> dict:
	"""Kanal kopyasi yontemleri pasiflestirir; benimsenmis olanlara dokunmaz."""
	frappe.reload_doc("tradehub_core", "doctype", "shipping_method")

	deactivated: list[str] = []
	skipped_in_use: list[tuple[str, str]] = []
	already_inactive: list[str] = []
	absent: list[str] = []

	for method_name in CHANNEL_DUPLICATE_METHODS:
		if not frappe.db.exists("Shipping Method", method_name):
			absent.append(method_name)
			continue

		current = frappe.db.get_value(
			"Shipping Method", method_name, ["is_active", "base_cost"], as_dict=True
		)
		if not current.is_active:
			already_inactive.append(method_name)
			continue

		# Bir listing'e baglanmis mi? (child tablo parent'i Listing)
		reference_count = frappe.db.count(
			"Shipping Method Item", {"shipping_method": method_name}
		)
		if reference_count:
			skipped_in_use.append((method_name, f"{reference_count} listing referansi"))
			continue

		# Uzerinde fiyat tanimlanmissa insan eli degmis demektir
		if current.base_cost:
			skipped_in_use.append((method_name, f"base_cost={current.base_cost}"))
			continue

		# db.set_value bilincli: tek bayrak dusuruluyor, validate zincirine gerek yok
		frappe.db.set_value("Shipping Method", method_name, "is_active", 0)
		deactivated.append(method_name)

	if skipped_in_use:
		frappe.log_error(
			f"Kullanimda oldugu icin pasiflestirilmeyen yontemler: {skipped_in_use}",
			"v15_log040_deactivate_channel_duplicate_methods",
		)

	frappe.db.commit()
	return {
		"deactivated": deactivated,
		"skipped_in_use": skipped_in_use,
		"already_inactive": already_inactive,
		"absent": absent,
	}

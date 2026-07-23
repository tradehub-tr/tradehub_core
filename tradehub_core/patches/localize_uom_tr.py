"""
Frappe v15 default UOM kayıtlarının İngilizce name'lerini Türkçeleştirir.

`frappe.rename_doc` ile UOM rename edilir; tüm Link referansları (RFQ.unit,
Listing.stock_uom, Order Item.uom, ERPNext Item.stock_uom vb.) otomatik
güncellenir.

Idempotent: zaten Türkçeleşmiş kayıtlar atlanır. Birden fazla kez güvenle
çalıştırılabilir.
"""

import frappe
from frappe.model.rename_doc import rename_doc

UOM_TR: dict[str, str] = {
	# Sayım / genel
	"Nos": "Adet",
	"Box": "Kutu",
	"Pair": "Çift",
	"Set": "Set",
	"Unit": "Birim",
	# Uzunluk
	"Meter": "Metre",
	"Centimeter": "Santimetre",
	"Millimeter": "Milimetre",
	"Kilometer": "Kilometre",
	"Inch": "İnç",
	"Foot": "Fit",
	"Yard": "Yarda",
	"Mile": "Mil",
	# Alan
	"Square Meter": "Metrekare",
	"Square Foot": "Fitkare",
	"Square Inch": "İnçkare",
	"Square Yard": "Yardakare",
	"Hectare": "Hektar",
	# Hacim
	"Cubic Meter": "Metreküp",
	"Cubic Centimeter": "Santimetreküp",
	"Cubic Foot": "Fitküp",
	"Litre": "Litre",
	"Millilitre": "Mililitre",
	# Ağırlık
	"Kilogram": "Kilogram",
	"Kg": "Kg",
	"Gram": "Gram",
	"Tonne": "Ton",
	"Pound": "Pound",
	"Quintal": "Kental",
	# Zaman
	"Day": "Gün",
	"Hour": "Saat",
	"Minute": "Dakika",
	"Week": "Hafta",
	# Elektrik
	"Ampere": "Amper",
	"Watt": "Watt",
	"Watt-Hour": "Watt-Saat",
}


def execute() -> None:
	original_allow_rename = frappe.db.get_value("DocType", "UOM", "allow_rename")
	if original_allow_rename != 1:
		frappe.db.set_value("DocType", "UOM", "allow_rename", 1)
		frappe.db.commit()

	renamed: list[tuple[str, str]] = []
	merged: list[tuple[str, str]] = []
	name_field_updated: list[tuple[str, str]] = []
	skipped: list[tuple[str, str, str]] = []

	frappe.logger("patches").info("[localize_uom_tr] başlıyor")

	for old_name, new_name in UOM_TR.items():
		if not frappe.db.exists("UOM", old_name):
			continue

		if old_name == new_name:
			current_label = frappe.db.get_value("UOM", old_name, "uom_name")
			if current_label != new_name:
				frappe.db.set_value("UOM", old_name, "uom_name", new_name)
				name_field_updated.append((old_name, new_name))
			continue

		try:
			if frappe.db.exists("UOM", new_name):
				rename_doc(
					"UOM",
					old_name,
					new_name,
					merge=True,
					force=True,
					ignore_permissions=True,
					show_alert=False,
				)
				frappe.db.set_value("UOM", new_name, "uom_name", new_name)
				merged.append((old_name, new_name))
				frappe.logger("patches").info(f"  MERGED  {old_name} -> {new_name}")
			else:
				rename_doc(
					"UOM",
					old_name,
					new_name,
					merge=False,
					force=True,
					ignore_permissions=True,
					show_alert=False,
				)
				frappe.db.set_value("UOM", new_name, "uom_name", new_name)
				renamed.append((old_name, new_name))
				frappe.logger("patches").info(f"  RENAMED {old_name} -> {new_name}")
		except Exception as e:
			skipped.append((old_name, new_name, str(e)))
			frappe.logger("patches").error(f"  FAILED  {old_name} -> {new_name}: {e}")

	frappe.db.commit()

	if original_allow_rename != 1:
		frappe.db.set_value("DocType", "UOM", "allow_rename", original_allow_rename or 0)
		frappe.db.commit()

	frappe.logger("patches").info(
		f"[localize_uom_tr] bitti: "
		f"{len(renamed)} rename, {len(merged)} merge, "
		f"{len(name_field_updated)} sadece-uom_name, {len(skipped)} atlanan"
	)
	if skipped:
		for old, new, err in skipped:
			frappe.logger("patches").warning(f"  ATLANAN: {old} -> {new}: {err}")

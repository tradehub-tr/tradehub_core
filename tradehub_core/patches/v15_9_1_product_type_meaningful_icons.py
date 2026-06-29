"""Her bilinen Product Type'a anlamlı bir lucide ikonu ata.

v15_9_0 tüm boşları jenerik "package" yapmıştı. Bu patch seed ile gelen
tiplere semantik ikon verir. Bilinmeyen/özel tipler doctype default'u
("package") ile kalır.

İkon değerleri lucide ikon adlarıdır (ör. kategori icon_class formatı: "cpu").
İdempotent: değer zaten doğruysa atlar; her zaman hedef değere getirir.
"""

from __future__ import annotations

import frappe

# Product Type.name (tip kodu) → lucide ikon adı
_ICONS = {
	"PHYSICAL": "package",          # Fiziksel ürün
	"DIGITAL": "download",          # Dijital ürün (indirilebilir)
	"DIGITAL-LICENSE": "key",       # Dijital lisans / anahtar
	"SERVICE": "wrench",            # Hizmet
	"BUNDLE": "boxes",              # Paket ürün (çoklu)
	"CONFIGURABLE": "sliders-horizontal",  # Yapılandırılabilir
	"ELECTRONICS": "cpu",           # Elektronik
}


def execute() -> dict:
	updated: list[str] = []
	for name, icon in _ICONS.items():
		if not frappe.db.exists("Product Type", name):
			continue
		if frappe.db.get_value("Product Type", name, "icon_class") != icon:
			frappe.db.set_value("Product Type", name, "icon_class", icon, update_modified=False)
			updated.append(name)

	frappe.db.commit()
	return {"updated": updated}

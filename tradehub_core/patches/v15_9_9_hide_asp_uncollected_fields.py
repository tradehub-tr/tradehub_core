"""FAZ 9.9 — Admin Seller Profile'da toplanamayan adres alanlarını gizle.

Sorun:
  address_line2, district, postal_code alanları ASP şemasında var ama hiçbir
  çalışan kaynaktan beslenmiyor:
    - Satıcı kayıt formu (Seller Application) bunları toplamıyor.
    - postal_code/district'in doğru evi ayrı `Addresses` doctype'ı; orada da
      satıcılarda boş. address_line2 için hiçbir kaynak yok.
  Sonuç: admin'e sürekli boş alanlar gösteriliyordu.

  NOT: website bu listeden çıkarıldı — storefront satıcı self-servis formu
  (get_my_profile/update_profile) ile satıcı kendi website'ını girebiliyor
  (gerçek kaynak), o yüzden panelde görünür kalır.

Çözüm:
  Üç alanı Property Setter ile `hidden=1` yap (v15_9_7 deseninin aynısı).
  DocType JSON'ı değiştirmeden runtime override ekler (panelin meta'sına yansır).
  İdempotent: make_property_setter aynı (doctype, field, property) için var olan
  setter'ı günceller. Kolonlar DB'de kalır (veri kaybı yok), yalnızca gizlenir.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

_HIDE = ["address_line2", "district", "postal_code"]


def execute() -> None:
	if not frappe.db.exists("DocType", "Admin Seller Profile"):
		return
	for fieldname in _HIDE:
		if not frappe.db.exists("DocField", {"parent": "Admin Seller Profile", "fieldname": fieldname}):
			continue
		make_property_setter(
			doctype="Admin Seller Profile",
			fieldname=fieldname,
			property="hidden",
			value="1",
			property_type="Check",
			validate_fields_for_doctype=False,
		)
	frappe.db.commit()

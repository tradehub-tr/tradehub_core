"""
Sertifika child table validate hook'ları — parent doctype'lardan tetiklenir.

Frappe v15'te child doctype'ın `validate()` metodu parent save akışında
otomatik çağrılmıyor; bu yüzden Listing ve Admin Seller Profile için ayrı
parent-level validate hook'larını hooks.py'a kaydederiz.

v4 mimari (model A):
- Mağaza: hem Management hem Product kategorisi kabul (belge havuzu)
- Listing: SADECE Product kategori atanabilir
- Listing'e atanan cert'in parent mağaza cert'i Verified olmalı (storefront tutarlılığı)
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate


def validate_listing_certifications(doc, method=None):
	"""hooks.py: Listing.validate handler — product_certifications iterate.

	Kontroller:
	1. Cert Type 'Approved' olmalı
	2. Cert kategorisi 'Product' olmalı
	3. Listing'in satıcısının bu cert için Seller Certification'ı olmalı (havuzda)
	4. Parent mağaza cert verification_status='Verified' olmalı
	5. expiry_date >= issued_date (override edildi ise)
	"""
	seller_profile = doc.get("seller_profile") or doc.get("seller")
	for row in doc.get("product_certifications") or []:
		cert_type = getattr(row, "certification_type", None)
		if not cert_type:
			continue

		# 1 + 2. Cert Type kontrolü
		ct = frappe.db.get_value(
			"Certification Type",
			cert_type,
			["status", "category"],
			as_dict=True,
		)
		if not ct:
			frappe.throw(_("Sertifika tipi bulunamadı: {0}").format(cert_type))
		if ct.status != "Approved":
			frappe.throw(
				_("Sadece onaylanmış sertifikalar atanabilir. '{0}' durumu: {1}").format(cert_type, ct.status)
			)
		if ct.category != "Product":
			frappe.throw(_("'{0}' bir mağaza sertifikasıdır, ürüne atanamaz.").format(cert_type))

		# 3 + 4. Parent mağaza cert kontrolü
		if seller_profile:
			parent_cert = frappe.db.get_value(
				"Seller Certification",
				{
					"parent": seller_profile,
					"parenttype": "Admin Seller Profile",
					"certification_type": cert_type,
				},
				["name", "verification_status"],
				as_dict=True,
			)
			if not parent_cert:
				frappe.throw(
					_(
						"'{0}' sertifikasını ürüne atayabilmek için önce 'Sertifikalarım > "
						"Mağaza Sertifikalarım' sayfasından mağazanıza eklemelisiniz."
					).format(cert_type)
				)
			if parent_cert.verification_status != "Verified":
				frappe.throw(
					_(
						"'{0}' mağaza sertifikanız henüz admin tarafından doğrulanmamış "
						"(durum: {1}). Doğrulandıktan sonra ürünlere atayabilirsiniz."
					).format(cert_type, parent_cert.verification_status or "Pending")
				)

		# 5. Tarih
		if row.get("issued_date") and row.get("expiry_date"):
			if getdate(row.expiry_date) < getdate(row.issued_date):
				frappe.throw(_("'{0}' için bitiş tarihi verilme tarihinden önce olamaz.").format(cert_type))


def validate_seller_certifications(doc, method=None):
	"""hooks.py: Admin Seller Profile.validate handler.

	v4: Kategori kısıtı YOK — hem Management hem Product kabul edilir
	(belge havuzu modeli).

	Kontroller:
	1. Cert Type 'Approved' olmalı
	2. expiry_date >= issued_date
	"""
	for row in doc.get("certifications") or []:
		cert_type = getattr(row, "certification_type", None)
		if not cert_type:
			continue

		ct = frappe.db.get_value(
			"Certification Type",
			cert_type,
			["status", "category"],
			as_dict=True,
		)
		if not ct:
			frappe.throw(_("Sertifika tipi bulunamadı: {0}").format(cert_type))
		if ct.status != "Approved":
			frappe.throw(
				_("Sadece onaylanmış sertifikalar atanabilir. '{0}' durumu: {1}").format(cert_type, ct.status)
			)

		if row.get("issued_date") and row.get("expiry_date"):
			if getdate(row.expiry_date) < getdate(row.issued_date):
				frappe.throw(_("'{0}' için bitiş tarihi verilme tarihinden önce olamaz.").format(cert_type))

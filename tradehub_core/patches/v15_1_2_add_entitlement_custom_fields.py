"""FAZ 1.2 — Entitlement custom field migration.

Mevcut DocType'lara (Admin Seller Profile, Listing, Buyer Profile, Organization,
User) Faz 1.2 entitlement düzlemi için gerekli alanları Custom Field olarak ekler.

Patch idempotent — tekrar çalışırsa mevcut field'lar create edilmez.

Detay: docs/yetki/03-doctype-sablonlari.md §9
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# Field tanımları — `create_custom_fields` Frappe helper'ı idempotent çalışır
_CUSTOM_FIELDS: dict[str, list[dict]] = {
	"Admin Seller Profile": [
		{
			"fieldname": "subscription",
			"label": "Store Subscription",
			"fieldtype": "Link",
			"options": "Store Subscription",
			"insert_after": "user",
			"description": "Aktif Store Subscription kaydı (1:1).",
		},
		{
			"fieldname": "sb_regions",
			"label": "Satış Bölgeleri",
			"fieldtype": "Section Break",
			"insert_after": "subscription",
		},
		{
			"fieldname": "regions",
			"label": "Allowed Regions",
			"fieldtype": "Table MultiSelect",
			"options": "Subscription Plan Region",
			"insert_after": "sb_regions",
			"description": "Satış/listeleme hakkı olan bölgeler. Plan.allowed_regions kümesinin alt kümesi olmalı.",
		},
	],
	"Listing": [
		{
			"fieldname": "sb_listing_regions",
			"label": "Bölge Kısıtı",
			"fieldtype": "Section Break",
			"insert_after": "seller_profile",
			"collapsible": 1,
		},
		{
			"fieldname": "allowed_regions",
			"label": "Listeleme Bölgeleri",
			"fieldtype": "Table MultiSelect",
			"options": "Subscription Plan Region",
			"insert_after": "sb_listing_regions",
			"description": "Bu listing'in görünür olacağı bölgeler. Satıcının regions kümesinin alt kümesi olmalı; boşsa satıcının tüm regions'ı kabul edilir.",
		},
	],
	"Buyer Profile": [
		{
			"fieldname": "region",
			"label": "Buyer Region",
			"fieldtype": "Link",
			"options": "Region",
			"insert_after": "display_name",
			"description": "Buyer'ın yerleşik olduğu bölge (veri rezidansı + KVKK/GDPR uyumu için kritik).",
			"in_standard_filter": 1,
		},
	],
	"User": [
		{
			"fieldname": "sb_tradehub_tenant",
			"label": "TradeHub Tenant",
			"fieldtype": "Section Break",
			"insert_after": "roles",
			"collapsible": 1,
		},
		{
			"fieldname": "tradehub_tenant",
			"label": "Tenant (Admin Seller Profile)",
			"fieldtype": "Link",
			"options": "Admin Seller Profile",
			"insert_after": "sb_tradehub_tenant",
			"description": "Sub-user için bağlı olunan mağaza (tenant).",
		},
		{
			"fieldname": "tradehub_parent_organization",
			"label": "Parent Organization (Buyer)",
			"fieldtype": "Link",
			"options": "Organization",
			"insert_after": "tradehub_tenant",
			"description": "B2B alıcı sub-user için bağlı olunan organizasyon.",
		},
		{
			"fieldname": "tradehub_is_owner",
			"label": "Is Store Owner",
			"fieldtype": "Check",
			"insert_after": "tradehub_parent_organization",
			"default": 0,
			"description": "Mağaza Sahibi (Owner) mi? Sadece Owner banka/vergi değiştirebilir, hesap kapatabilir.",
		},
		{
			"fieldname": "tradehub_temporary_role_until",
			"label": "Temporary Role Until",
			"fieldtype": "Datetime",
			"insert_after": "tradehub_is_owner",
			"description": "Bu tarihten sonra atanmış rol otomatik kalkar (Faz 3'te işler hale gelir).",
		},
	],
}


def execute() -> None:
	"""Custom field'ları idempotent şekilde oluştur."""
	# Frappe'nin create_custom_fields helper'ı zaten idempotent —
	# var olan field'ı atlar, yeni olanı ekler.
	create_custom_fields(_CUSTOM_FIELDS, update=True)

	# Organization için ayrı işlem (mevcut alanları override edebilir,
	# o yüzden ayrı log + dikkat)
	_add_organization_fields()


def _add_organization_fields() -> None:
	"""CRM Organization'a parent_org ve org_type alanları ekle.

	CRM Organization doctype'ı external (Frappe CRM app'inden), Custom Field
	ile genişletiyoruz. parent_org self-reference, hiyerarşi için.
	"""
	org_fields = {
		"CRM Organization": [
			{
				"fieldname": "tradehub_parent_org",
				"label": "Parent Organization",
				"fieldtype": "Link",
				"options": "CRM Organization",
				"insert_after": "organization_name",
				"description": "Üst organizasyon (hiyerarşik buyer/seller grupları için).",
			},
			{
				"fieldname": "tradehub_org_type",
				"label": "Organization Type",
				"fieldtype": "Select",
				"options": "\nDepartment\nCost Center\nLocation\nProject\nHolding\nSubsidiary",
				"insert_after": "tradehub_parent_org",
				"description": "Organizasyon tipi (Faz 2 B2B alıcı hiyerarşisi için).",
			},
			{
				"fieldname": "tradehub_region",
				"label": "Organization Region",
				"fieldtype": "Link",
				"options": "Region",
				"insert_after": "tradehub_org_type",
				"description": "Organizasyonun yerleşik olduğu bölge.",
			},
		]
	}

	# CRM Organization doctype var mı kontrol et (Frappe CRM yüklü mü?)
	if not frappe.db.exists("DocType", "CRM Organization"):
		frappe.log_error(
			"CRM Organization DocType bulunamadı. Frappe CRM app yüklü değil; "
			"organization custom field'ları atlandı.",
			"v15_1_2 patch",
		)
		return

	create_custom_fields(org_fields, update=True)

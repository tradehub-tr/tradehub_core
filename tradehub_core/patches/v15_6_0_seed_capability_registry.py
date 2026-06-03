"""Sprint 6 — TH Capability Registry seed.

Sorun:
  Capability listesi `seller_capabilities.py` Python dict'inde (SELLER_CAPABILITIES).
  Süper admin yeni capability ekleyemiyor / silemiyor. DocType DB'leştirildi,
  bu patch mevcut sabit listeyi DB'ye seed eder.

Kaynak: tradehub_core.utils.seller_capabilities
  - SELLER_CAPABILITIES         → 25 normal capability
  - _OWNER_ONLY_CAPABILITIES    → 6 owner-only capability (dict'te yok, ayrı set)
  - _REQUIRES_KYC               → KYC zorunlu işaretle
  - _REQUIRES_AML_CLEAN         → AML zorunlu işaretle

Tier eşlemesi (Python frozenset → DB enum):
  _TIER_OPERATIONS → "OPERATIONS"
  _TIER_FINANCE    → "FINANCE"
  _TIER_MANAGEMENT → "MANAGEMENT"
  _TIER_COOWNER    → "COOWNER"
  _TIER_SALES      → "SALES"

İdempotent: var olan kayıtların değişmemiş field'larına dokunmaz, eksik kayıt
ekler. is_active, is_protected gibi süper admin tarafından değiştirilebilen
field'lar override edilmez (var olan kaydın değeri korunur).
"""

from __future__ import annotations

import frappe

# Module grup eşlemesi — capability_key prefix'inden çıkarsama
_MODULE_GROUP_MAP = {
	"order": "Sipariş",
	"listing": "Ürün",
	"gallery": "Galeri",
	"category": "Ürün",
	"inquiry": "Müşteri İletişimi",
	"rfq": "Müşteri İletişimi",
	"crm": "Müşteri İletişimi",
	"balance": "Finans",
	"seller_profile": "Yönetim",
	"storefront": "Yönetim",
	"cert": "Yönetim",
	"address": "Yönetim",
	"kyb": "Yönetim",
	"subuser": "Ekip",
	"view": "Görüntüleme",
	"bank_info": "Owner-Only",
	"tax_info": "Owner-Only",
	"account": "Owner-Only",
	"owner": "Owner-Only",
	"subscription": "Owner-Only",
	"two_factor": "Owner-Only",
}


def _module_group_for(capability_key: str, is_owner_only: bool) -> str:
	if is_owner_only:
		return "Owner-Only"
	prefix = capability_key.split(".", 1)[0]
	return _MODULE_GROUP_MAP.get(prefix, "Diğer")


def _tier_name_for(tier_set, tier_constants) -> str:
	"""Python frozenset → string tier adı."""
	for name, const in tier_constants.items():
		if tier_set is const:
			return name
	return "OPERATIONS"


def _readable_label(capability_key: str) -> str:
	"""'view.bank_info' → 'IBAN/Banka Bilgisi Okuma' gibi insan-okur label."""
	overrides = {
		"order.ship": "Sipariş Kargo",
		"order.confirm_payment": "Ödeme Onayı",
		"order.refund": "İade",
		"listing.write": "Ürün Yazma",
		"listing.publish": "Ürün Yayınlama",
		"listing.delete": "Ürün Silme",
		"gallery.write": "Galeri Yönetimi",
		"category.write": "Kategori Yönetimi",
		"inquiry.reply": "Müşteri Sorusu Yanıtla",
		"rfq.quote": "RFQ Teklif",
		"crm.lead_capture": "CRM Lead Yakala",
		"balance.withdraw": "Bakiye Çekme",
		"seller_profile.write": "Mağaza Profili Yazma",
		"storefront.write": "Vitrin Yazma",
		"cert.write": "Sertifika Yükleme",
		"address.write": "Adres Yazma",
		"kyb.submit": "KYB Başvurusu",
		"subuser.manage": "Ekip Yönetimi",
		"view.financial_summary": "Finansal Özet Görüntüleme",
		"view.profit_detail": "Kâr Marjı Görüntüleme",
		"view.balance": "Bakiye Görüntüleme",
		"view.bank_info": "Banka Bilgisi Görüntüleme",
		"view.customer_full": "Tam Müşteri Bilgisi",
		"view.customer_shipping": "Müşteri Kargo Bilgisi",
		"view.order_amounts": "Sipariş Tutarları",
		"bank_info.write": "Banka Bilgisi Yazma",
		"tax_info.write": "Vergi Bilgisi Yazma",
		"account.delete": "Hesap Silme",
		"owner.transfer": "Sahiplik Devri",
		"subscription.change": "Abonelik Değişikliği",
		"two_factor.disable": "2FA Kapatma",
	}
	return overrides.get(capability_key, capability_key)


def execute() -> dict:
	from tradehub_core.utils import seller_capabilities as sc

	tier_constants = {
		"OPERATIONS": sc._TIER_OPERATIONS,
		"FINANCE": sc._TIER_FINANCE,
		"MANAGEMENT": sc._TIER_MANAGEMENT,
		"COOWNER": sc._TIER_COOWNER,
		"SALES": sc._TIER_SALES,
	}

	created: list[str] = []
	skipped: list[str] = []

	# 1) SELLER_CAPABILITIES dict — normal capability'ler
	for cap_key, (tier_set, plan_feature) in sc.SELLER_CAPABILITIES.items():
		if frappe.db.exists("TH Capability Registry", cap_key):
			skipped.append(cap_key)
			continue

		tier_name = _tier_name_for(tier_set, tier_constants)
		doc = frappe.new_doc("TH Capability Registry")
		doc.capability_key = cap_key
		doc.label = _readable_label(cap_key)
		doc.module_group = _module_group_for(cap_key, False)
		doc.default_tier = tier_name
		doc.is_owner_only = 0
		doc.requires_kyc = 1 if cap_key in sc._REQUIRES_KYC else 0
		doc.requires_aml = 1 if cap_key in sc._REQUIRES_AML_CLEAN else 0
		doc.is_protected = 0
		doc.is_active = 1
		doc.plan_feature_flag = plan_feature or ""
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		created.append(cap_key)

	# 2) _OWNER_ONLY_CAPABILITIES — owner-only
	for cap_key in sc._OWNER_ONLY_CAPABILITIES:
		if frappe.db.exists("TH Capability Registry", cap_key):
			skipped.append(cap_key)
			continue

		doc = frappe.new_doc("TH Capability Registry")
		doc.capability_key = cap_key
		doc.label = _readable_label(cap_key)
		doc.module_group = _module_group_for(cap_key, True)
		doc.default_tier = "OWNER_ONLY"
		doc.is_owner_only = 1
		doc.requires_kyc = 1 if cap_key in sc._REQUIRES_KYC else 0
		doc.requires_aml = 0
		doc.is_protected = 1  # Owner-only kritik kapı, UI'dan silinmez
		doc.is_active = 1
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		created.append(cap_key)

	frappe.db.commit()

	return {
		"created": created,
		"skipped_existing": skipped,
		"total_in_db": frappe.db.count("TH Capability Registry"),
	}

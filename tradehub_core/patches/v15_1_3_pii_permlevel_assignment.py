"""FAZ 1.3 — PII alanlarına permlevel ataması (Property Setter).

Mimari karar (docs/yetki/01-karar-dosyasi.md §3):
  - permlevel 0 (default) — Herkes (rol kontrolüne göre)
  - permlevel 1 (Restricted) — Phone, email, adres gibi belirli iş rolleri
  - permlevel 2 (Sensitive) — Vergi no, IBAN, banka — Finance + Owner + Compliance
  - permlevel 3 (Critical PII) — Kimlik, KYC dokümanları — Sadece Compliance

Patch idempotent — Property Setter Frappe'nin built-in idempotent helper'ı.
Mevcut DocType JSON'ı değiştirmiyoruz; sadece runtime override ekliyoruz.

Detay: docs/yetki/01-karar-dosyasi.md §3, docs/yetki/03-doctype-sablonlari.md
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

# (doctype, fieldname) → permlevel
_PII_PERMLEVELS: list[tuple[str, str, int]] = [
	# --- Admin Seller Profile (mağaza entity'si) ---
	("Admin Seller Profile", "phone", 1),  # iletişim
	("Admin Seller Profile", "tax_id", 2),  # vergi no — Finance + Owner + Compliance
	("Admin Seller Profile", "iban", 2),  # banka IBAN
	("Admin Seller Profile", "bank_name", 2),  # banka adı
	# --- User Profile (Sprint 2 birleştirilmiş user) ---
	("User Profile", "tax_id", 2),
	# --- KYC Verification (bireysel/kurumsal kimlik) ---
	("KYC Verification", "tax_id", 2),
	("KYC Verification", "phone", 1),
	("KYC Verification", "email_field", 1),
	("KYC Verification", "address", 1),
	("KYC Verification", "billing_address", 1),
	("KYC Verification", "identity_document", 3),  # kimlik dosyası — kritik PII
	("KYC Verification", "rejection_reason", 1),
	# --- KYB Verification (kurumsal kimlik dosyaları) ---
	# Mevcut JSON'da bazı field'larda permlevel=1 zaten var; biz permlevel 3
	# olması gereken dosya alanlarını override ediyoruz.
	("KYB Verification", "identity_document", 3),
	("KYB Verification", "imza_sirkuleri", 3),
	("KYB Verification", "ticaret_sicil_gazetesi", 3),
	("KYB Verification", "faaliyet_belgesi", 3),
	("KYB Verification", "vergi_levhasi", 3),
	("KYB Verification", "bank_account_document", 3),
	("KYB Verification", "mersis_no", 1),
	("KYB Verification", "trade_registry_number", 1),
	("KYB Verification", "kep_address", 1),
]


def execute() -> None:
	"""PII field'larına permlevel set et (idempotent)."""
	applied = 0
	skipped = 0
	errors = []

	for doctype, fieldname, permlevel in _PII_PERMLEVELS:
		try:
			# Field var mı kontrol et
			if not frappe.db.has_column(f"tab{doctype}", fieldname):
				skipped += 1
				continue

			# Mevcut field meta kontrolü (DocField veya Custom Field olabilir)
			docfield_exists = frappe.db.exists("DocField", {"parent": doctype, "fieldname": fieldname})
			custom_field_exists = frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": fieldname})

			if not docfield_exists and not custom_field_exists:
				skipped += 1
				continue

			make_property_setter(
				doctype=doctype,
				fieldname=fieldname,
				property="permlevel",
				value=str(permlevel),
				property_type="Int",
				validate_fields_for_doctype=False,
			)
			applied += 1
		except Exception as e:
			errors.append(f"{doctype}.{fieldname}: {e}")
			frappe.log_error(
				f"PII permlevel ataması başarısız: {doctype}.{fieldname} → {permlevel}: {e}",
				"v15_1_3_pii_permlevel",
			)

	# Rapor
	frappe.logger("patches").info(
		f"FAZ 1.3 PII permlevel ataması: {applied} field güncellendi, {skipped} field bulunamadı (skip)."
	)
	if errors:
		frappe.logger("patches").warning(f"FAZ 1.3 PII permlevel ataması: {len(errors)} hata var:")
		for err in errors[:10]:
			frappe.logger("patches").error(f"   {err}")

	frappe.db.commit()

"""
Migration Patch: Buyer Address → Addresses rename + Seller Profile flat adres migrasyonu.

Yapılanlar (idempotent):
1. "Buyer Address" DocType'ı "Addresses" olarak rename edilir (varsa). Aynı anda
   `tabBuyer Address` tablosu `tabAddresses` olur.
2. Mevcut tüm kayıtlara `kind='Buyer'` yazılır (null/boş olanlar).
3. Seller Profile üzerindeki eski flat adres field'ları (address_line_1, city,
   postal_code) dolu olanlar için Addresses tarafına `kind='Seller'` kaydı
   oluşturulur ve `is_default=1` işaretlenir.
4. Seller Profile'daki eski kolonlar DB'de bırakılır — sonraki `bench migrate`
   JSON'dan şema ile senkron hale getirip kolonları düşürür.
"""

import frappe
from frappe import _


def execute():
	_rename_doctype()
	_backfill_kind()
	_migrate_seller_profile_addresses()
	frappe.db.commit()


# ──────────────────────────────────────────────────────────────────────────
# 1. Rename
# ──────────────────────────────────────────────────────────────────────────


def _rename_doctype():
	"""Buyer Address → Addresses. Idempotent."""
	if frappe.db.exists("DocType", "Addresses"):
		# Zaten rename edilmiş; bir şey yapma
		return
	if not frappe.db.exists("DocType", "Buyer Address"):
		# Hiç yok; fresh install, reload ile yeni Addresses gelecek
		return
	from frappe.model.rename_doc import rename_doc

	rename_doc("DocType", "Buyer Address", "Addresses", force=True, merge=False)
	frappe.reload_doc("tradehub_core", "doctype", "addresses")


# ──────────────────────────────────────────────────────────────────────────
# 2. kind backfill
# ──────────────────────────────────────────────────────────────────────────


def _backfill_kind():
	"""Eski kayıtlara kind='Buyer' yaz."""
	if not frappe.db.exists("DocType", "Addresses"):
		return
	# Tabloda kind kolonu henüz eklenmemiş olabilir — migrate sonrası çalışacak,
	# ama patch sırasında table_exists olmayabilir. Güvenli kontrol:
	if not frappe.db.has_column("Addresses", "kind"):
		# Migrate sonrasında bu kolon eklenecek; ilk çalıştırmada skip.
		return
	frappe.db.sql(
		"""
		UPDATE `tabAddresses`
		SET kind = 'Buyer'
		WHERE kind IS NULL OR kind = ''
		"""
	)


# ──────────────────────────────────────────────────────────────────────────
# 3. Seller Profile flat address migration
# ──────────────────────────────────────────────────────────────────────────


def _migrate_seller_profile_addresses():
	"""
	Seller Profile üzerindeki address_line_1/city/postal_code dolu olanları
	Addresses DocType'ına taşı (kind='Seller'). Idempotent: aynı seller için
	zaten bir Addresses varsa atla.
	"""
	if not frappe.db.has_column("Seller Profile", "address_line_1"):
		return
	if not frappe.db.exists("DocType", "Addresses"):
		return
	if not frappe.db.has_column("Addresses", "kind"):
		return

	# business_name, seller_name gibi alanların varlığını runtime'da kontrol et
	# (eski/yeni şemalar arasında tutarlı olmak için).
	has_business_name = frappe.db.has_column("Seller Profile", "business_name")
	has_seller_name = frappe.db.has_column("Seller Profile", "seller_name")
	has_contact_phone = frappe.db.has_column("Seller Profile", "contact_phone")
	has_country = frappe.db.has_column("Seller Profile", "country")

	select_cols = ["sp.name", "sp.user", "sp.address_line_1", "sp.city", "sp.postal_code"]
	if has_country:
		select_cols.append("sp.country")
	if has_contact_phone:
		select_cols.append("sp.contact_phone")
	if has_business_name:
		select_cols.append("sp.business_name AS company_name")
	if has_seller_name:
		select_cols.append("sp.seller_name")

	profiles = frappe.db.sql(
		"""
		SELECT {cols}
		FROM `tabSeller Profile` sp
		WHERE sp.address_line_1 IS NOT NULL
		  AND sp.address_line_1 != ''
		""".format(cols=", ".join(select_cols)),
		as_dict=True,
	)

	for row in profiles:
		# Idempotency: aynı seller için Addresses zaten varsa atla
		existing = frappe.db.count("Addresses", {"kind": "Seller", "seller": row.name})
		if existing:
			continue

		try:
			seller_name_val = row.get("seller_name") or ""
			company_name_val = row.get("company_name") or ""
			contact_phone_val = (row.get("contact_phone") or "").strip()
			country_val = row.get("country") or "TR"

			doc = frappe.new_doc("Addresses")
			doc.kind = "Seller"
			doc.seller = row.name
			doc.user = row.user
			doc.title = _("Ana Adres")
			doc.contact_name = seller_name_val or company_name_val or "-"
			doc.company = company_name_val or seller_name_val or "-"
			doc.phone_prefix = "+90"
			# Eski contact_phone formatsız olabilir; boşsa geçerli bir default koy
			doc.phone = contact_phone_val or "5000000000"
			doc.country = country_val
			doc.state = row.city or "İstanbul"  # state zorunlu; city'yi state olarak kullan
			doc.city = ""
			doc.street = row.address_line_1 or "-"
			doc.postal_code = row.postal_code or ""
			doc.is_default = 1
			doc.insert(ignore_permissions=True, ignore_mandatory=True)
		except Exception as e:
			frappe.log_error(
				title="Seller address migration error",
				message=f"Seller Profile {row.name}: {e}",
			)

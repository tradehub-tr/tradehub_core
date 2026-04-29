"""
Migration Patch: Tüm telefon kayıtlarını E.164 kanonik forma çevir.

Aynı kişinin telefonu DB'de farklı yerlerde farklı formatlarda saklanıyordu
(`05326542137`, `+90 532 654 21 37`, `905326542137`, vb.). Bu patch tek bir
seferlik temizlik yapar — `tradehub_core.utils.phone.canonicalize_phone`
yardımcısını kullanarak hepsini `+90XXXXXXXXXX` formatına indirger.

İdempotent: zaten kanonik olan değerler için ``set_value`` çağrılmaz; ayrıca
``canonicalize_phone`` aynı sonucu döndürdüğünde değer değişmez. Parse
edilemeyen bozuk değerler dokunulmaz (atlanır ve sayım yapılır), ki bu kayıtlar
manuel olarak temizlenebilsin.

Kapsanan DocType + alan eşlemesi:
  User                 → phone           (tek alan)
  Buyer Profile        → phone           (tek alan)
  Seller Profile       → contact_phone   (tek alan)
  Seller Application   → contact_phone   (tek alan)
  Admin Seller Profile → phone           (tek alan)
  Addresses            → phone + phone_prefix  (çift alan; phone yalnız 10
                                                   haneli yerel kısma indirgenir,
                                                   prefix "+90"/uluslararası
                                                   kalır)
"""

import frappe

from tradehub_core.utils.phone import canonicalize_phone, split_e164

# (DocType, fieldname) — tek-alan şemaları. Bu alanlar doğrudan E.164 değer
# tutar (örn. "+905326542137").
_SINGLE_FIELD_TARGETS = [
	("User", "phone"),
	("Buyer Profile", "phone"),
	("Seller Profile", "contact_phone"),
	("Seller Application", "contact_phone"),
	("Admin Seller Profile", "phone"),
]


def execute():
	totals = {
		"updated": 0,
		"skipped_already_canonical": 0,
		"skipped_unparseable": 0,
		"skipped_empty": 0,
	}

	for doctype, fieldname in _SINGLE_FIELD_TARGETS:
		if not frappe.db.exists("DocType", doctype):
			continue
		_canonicalize_single_field(doctype, fieldname, totals)

	if frappe.db.exists("DocType", "Addresses"):
		_canonicalize_addresses(totals)

	frappe.db.commit()
	print(
		"canonicalize_phone_numbers: "
		f"updated={totals['updated']} "
		f"already_canonical={totals['skipped_already_canonical']} "
		f"unparseable={totals['skipped_unparseable']} "
		f"empty={totals['skipped_empty']}"
	)


def _canonicalize_single_field(doctype, fieldname, totals):
	"""DocType'taki tek-alan telefon kolonunu E.164'e çevir."""
	rows = frappe.db.sql(
		f"SELECT name, `{fieldname}` AS phone FROM `tab{doctype}` WHERE `{fieldname}` IS NOT NULL AND `{fieldname}` != ''",
		as_dict=True,
	)
	for row in rows:
		raw = row.phone
		canonical = canonicalize_phone(raw)
		if not canonical:
			totals["skipped_unparseable"] += 1
			continue
		if canonical == raw:
			totals["skipped_already_canonical"] += 1
			continue
		frappe.db.set_value(doctype, row.name, fieldname, canonical, update_modified=False)
		totals["updated"] += 1


def _canonicalize_addresses(totals):
	"""Addresses çift-alan şemasını E.164'e çevir.

	Kayıt: ``phone_prefix="+90"`` + ``phone="5326542137"`` (yerel 10 hane).
	Eski kayıtlarda ``phone`` "+90"/"0" prefix'i içeriyor olabilir; combined
	string'i kanonikleştirip ``split_e164`` ile bölüştürerek düzeltiyoruz.
	"""
	rows = frappe.db.sql(
		"SELECT name, phone_prefix, phone FROM `tabAddresses` WHERE phone IS NOT NULL AND phone != ''",
		as_dict=True,
	)
	for row in rows:
		prefix = (row.phone_prefix or "+90").strip()
		raw = row.phone
		# Combine prefix+phone for canonicalization. If user already double-typed
		# the country code (e.g. prefix="+90" + phone="+905326542137"),
		# canonicalize_phone strips non-digits and recovers the 10-digit
		# subscriber correctly.
		combined = f"{prefix}{raw}"
		canonical = canonicalize_phone(combined)
		if not canonical:
			# Fallback: try just the raw phone (user might have typed the full
			# E.164 number into the phone field with prefix unset to a stale
			# default).
			canonical = canonicalize_phone(raw)
		if not canonical:
			totals["skipped_unparseable"] += 1
			continue
		new_prefix, new_local = split_e164(canonical)
		if new_prefix == prefix and new_local == raw:
			totals["skipped_already_canonical"] += 1
			continue
		frappe.db.set_value(
			"Addresses",
			row.name,
			{"phone_prefix": new_prefix, "phone": new_local},
			update_modified=False,
		)
		totals["updated"] += 1

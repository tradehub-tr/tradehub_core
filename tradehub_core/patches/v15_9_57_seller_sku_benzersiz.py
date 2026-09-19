"""MOGEM-665 · 1. aşama: `(seller_profile, seller_sku)` bileşik benzersiz indeks.

`seller_sku` sonradan Custom Field olarak eklendi (v15_bulk_import_init/07) ve
yalnız arama indeksi taşıyordu. Ürün API'si "aynı kod → güncelle" sözünü
veritabanı seviyesinde tutabilmek için:

1. Boş string kodlar NULL'a çekilir (benzersiz indeks NULL'ları saymaz; '' sayar
   ve ikinci boş koda izin vermezdi).
2. Mevcut çakışmalar temizlenir: aynı mağazada aynı kodlu ürünlerden en eski
   kalır, sonrakilerin kodu `<kod>#DUP2`, `#DUP3`… olarak işaretlenir ve Error
   Log'a yazılır — veri SİLİNMEZ, yalnız etiketlenir; satıcı panelden düzeltir.
3. `uniq_listing_seller_sku` benzersiz indeksi eklenir (idempotent).
"""

import frappe


def execute():
	if not frappe.db.has_column("Listing", "seller_sku"):
		return

	# 1) '' → NULL (ve kırpma)
	frappe.db.sql(
		"UPDATE `tabListing` SET seller_sku = NULLIF(TRIM(seller_sku), '') WHERE seller_sku IS NOT NULL"
	)

	# 2) Çakışanları etiketle (collation büyük/küçük harfi aynı sayar; GROUP BY de öyle)
	dups = frappe.db.sql(
		"""SELECT seller_profile, seller_sku, COUNT(*) c
		   FROM `tabListing`
		   WHERE seller_sku IS NOT NULL AND seller_profile IS NOT NULL
		   GROUP BY seller_profile, seller_sku HAVING c > 1""",
		as_dict=True,
	)
	etiketlenen = []
	for d in dups:
		rows = frappe.get_all(
			"Listing",
			filters={"seller_profile": d.seller_profile, "seller_sku": d.seller_sku},
			fields=["name", "creation"],
			order_by="creation asc",
		)
		for i, r in enumerate(rows[1:], start=2):
			yeni = f"{d.seller_sku}#DUP{i}"
			frappe.db.set_value("Listing", r.name, "seller_sku", yeni, update_modified=False)
			etiketlenen.append(f"{d.seller_profile} / {d.seller_sku} → {r.name}: {yeni}")
	if etiketlenen:
		frappe.log_error(
			title="seller_sku çakışmaları etiketlendi (MOGEM-665)",
			message="\n".join(etiketlenen),
		)

	# 3) Benzersiz indeks
	frappe.db.add_unique(
		"Listing", ["seller_profile", "seller_sku"], constraint_name="uniq_listing_seller_sku"
	)
	frappe.db.commit()

import frappe


def execute():
	"""Bozuk RFQ başlıklarını temizle.

	Kullanıcı dropdown'dan kategori seçti ama yazımı tamamlamadıysa
	(örn 'am' yazıp 'Ambalaj' tıkladı) input ham haliyle kaydedildi.
	Eğer mevcut product_name kategori adının prefix'i ise tam ada genişlet.
	İdempotent — aynı kayıt tekrar match etmez.
	"""
	rfqs = frappe.get_all(
		"RFQ",
		filters={"category": ["is", "set"]},
		fields=["name", "product_name", "category"],
	)
	updated = 0
	for rfq in rfqs:
		pn = (rfq.product_name or "").strip()
		if not pn or not rfq.category:
			continue
		cat_name = frappe.db.get_value("Product Category", rfq.category, "category_name") or ""
		if not cat_name or pn == cat_name:
			continue
		if cat_name.lower().startswith(pn.lower()):
			frappe.db.set_value("RFQ", rfq.name, "product_name", cat_name)
			updated += 1

	if updated:
		frappe.db.commit()
		frappe.logger("patches").info(f"[clean_short_rfq_titles] {updated} RFQ başlığı düzeltildi.")

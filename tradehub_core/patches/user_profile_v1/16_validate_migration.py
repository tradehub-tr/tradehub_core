"""Patch 16: Migration bütünlük doğrulaması.
Hatalı durumda log_error + print, patch FAIL olmaz (idempotent için)."""

import frappe


def execute():
	errors = []

	# 1. User Profile count vs eski toplam
	buyer_count = frappe.db.count("Buyer Profile") if frappe.db.table_exists("Buyer Profile") else 0
	seller_count = frappe.db.count("Seller Profile") if frappe.db.table_exists("Seller Profile") else 0
	overlap = 0
	if frappe.db.table_exists("Buyer Profile") and frappe.db.table_exists("Seller Profile"):
		overlap = frappe.db.sql("""
			SELECT COUNT(*) FROM `tabBuyer Profile` b
			INNER JOIN `tabSeller Profile` s ON s.user = b.user
		""")[0][0]

	up_count = frappe.db.count("User Profile")
	expected = buyer_count + seller_count - overlap

	if up_count != expected:
		errors.append(
			f"User Profile count mismatch: {up_count} != "
			f"buyer({buyer_count}) + seller({seller_count}) - overlap({overlap}) = {expected}"
		)

	# 2. Hibrit kullanıcı doğrulama
	hybrid_up = frappe.db.sql("""
		SELECT COUNT(*) FROM `tabUser Profile` WHERE can_buy=1 AND can_sell=1
	""")[0][0]
	if hybrid_up != overlap:
		errors.append(f"Hybrid user count: User Profile={hybrid_up} != expected overlap={overlap}")

	# 3. member_id format
	bad_id = frappe.db.sql("""
		SELECT COUNT(*) FROM `tabUser Profile`
		WHERE member_id IS NULL OR member_id = '' OR member_id NOT LIKE 'UP-%'
	""")[0][0]
	if bad_id > 0:
		errors.append(f"Invalid member_id: {bad_id} kayıt")

	# 4. user_type tutarlılığı (Patch 12 sonrası)
	mismatch = frappe.db.sql("""
		SELECT COUNT(*) FROM `tabUser Profile` up
		INNER JOIN `tabUser` u ON u.name = up.user
		WHERE up.can_sell = 1 AND u.user_type != 'System User'
		   AND u.name NOT IN ('Administrator', 'Guest')
	""")[0][0]
	if mismatch > 0:
		errors.append(f"can_sell=1 ama user_type != System User: {mismatch} kayıt")

	# 5. Business validate (Bloker 1)
	non_business_seller = frappe.db.sql("""
		SELECT COUNT(*) FROM `tabUser Profile`
		WHERE can_sell = 1 AND account_type != 'Business'
	""")[0][0]
	if non_business_seller > 0:
		errors.append(
			f"can_sell=1 ama account_type != Business: {non_business_seller} kayıt (Bloker 1 kuralı ihlali)"
		)

	# 6. Orphan kontrolü — Patch 9 sonrası 4 tablo
	for src, col in [
		("Seller Balance", "seller"),
		("Seller Product", "seller"),
		("RFQ Quote", "seller_profile"),
		("Addresses", "seller"),
	]:
		if not frappe.db.table_exists(src):
			continue
		try:
			orphan = frappe.db.sql(f"""
				SELECT COUNT(*) FROM `tab{src}` t
				LEFT JOIN `tabAdmin Seller Profile` asp ON asp.name = t.`{col}`
				WHERE t.`{col}` IS NOT NULL AND t.`{col}` != '' AND asp.name IS NULL
			""")[0][0]
			if orphan > 0:
				errors.append(f"Orphan {src}.{col} → Admin Seller Profile: {orphan}")
		except Exception as exc:
			errors.append(f"Orphan check {src}.{col} ERR: {exc}")

	if errors:
		msg = "\n".join(errors)
		frappe.log_error(title="Patch 16: VALIDATION FAILED", message=msg)
		frappe.logger("patches").error(f"===VALIDATION_FAILED===\n{msg}\n===END===")
	else:
		frappe.logger("patches").info("===VALIDATION_OK=== Tüm kontroller geçti")
		frappe.log_error(
			title="Patch 16: VALIDATION OK",
			message=f"User Profile count: {up_count}, Hybrid: {hybrid_up}, Buyer: {buyer_count}, Seller: {seller_count}",
		)

	frappe.db.commit()

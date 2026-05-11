"""Marketplace satıcı user'larını System User'a normalize et.

Tarihçe:
Eski mimaride satıcı user'ları "Website User" olarak tutuluyordu (eski karar:
"satıcı storefront context'inde kalsın"). Frappe v15'te Website User'lar:
  - Session yalnız Redis hash'inde, tabSessions'a yazılmaz
  - Server restart / Redis flush sonrası session kaybedilir
  - "User None is disabled" → HTTP 417 ValidationError → kullanıcı login redirect

Yeni mimaride (2026-05):
  - Tüm Active Admin Seller Profile.user → System User
  - tabSessions tablosuna kalıcı session yazılır
  - Restart'a dayanıklı
  - Frappe Desk erişimi DocPerm seviyesinde (Seller rolünün Desk yetkisi yok)
    zaten engelli — user_type değişimi güvenlik açığı yaratmaz

Idempotent: System User olanları atlar.
"""

import frappe


def execute():
	sellers = frappe.db.sql(
		"""
		SELECT DISTINCT asp.user
		FROM `tabAdmin Seller Profile` asp
		WHERE asp.user IS NOT NULL
			AND asp.user != ''
			AND asp.user != 'Administrator'
			AND IFNULL(asp.status, '') = 'Active'
		""",
		as_dict=True,
	)

	updated = 0
	already_correct = 0
	missing = 0

	for row in sellers:
		user = row.user
		if not user:
			continue
		current_type = frappe.db.get_value("User", user, "user_type")
		if current_type is None:
			missing += 1
			continue
		if current_type == "System User":
			already_correct += 1
			continue
		frappe.db.set_value("User", user, "user_type", "System User", update_modified=False)
		# Eski bozuk Redis/DB session'larını temizle — fresh session alsın
		try:
			frappe.db.sql("DELETE FROM `tabSessions` WHERE user = %s", (user,))
		except Exception:
			pass
		updated += 1
		print(f"  [updated] {user}: {current_type} → System User")

	frappe.db.commit()
	print(
		f"[normalize_seller_user_type] updated={updated}, "
		f"already_correct={already_correct}, missing_user_doc={missing}"
	)

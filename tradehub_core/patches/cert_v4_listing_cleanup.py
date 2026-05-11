"""v4 — Listing Certification.document ve verification_status alanlarını kaldır.

v4 mimari kararı:
- Sertifika belgesi yalnız Seller Certification'da (mağaza havuzu)
- Listing Certification artık SADECE atama referansı + tarih override
- verification_status parent mağaza cert'inden türetilir

Migration sırası:
1. Mevcut document/verification_status değerleri audit log'a yazılır
2. Frappe DocType sync'i field'ları DB'den otomatik kaldırır
3. Defansif olarak ALTER TABLE DROP COLUMN denemesi (idempotent)

Kullanıcı belirtti: "Bırak hiç eklemedim" — yani veriler boş, migrate sorunsuz olur.
"""

import frappe


def execute():
	# Audit — varsa dolu değerleri logla
	try:
		rows = frappe.db.sql(
			"""
			SELECT name, parent, certification_type, document, verification_status
			FROM `tabListing Certification`
			WHERE IFNULL(document, '') != '' OR IFNULL(verification_status, '') != ''
			""",
			as_dict=True,
		)
	except Exception:
		rows = []

	if rows:
		for r in rows:
			frappe.log_error(
				title="cert_v4_listing_cleanup: legacy row",
				message=f"row={r}",
			)

	# DB DROP COLUMN — idempotent
	for col in ("document", "verification_status"):
		try:
			frappe.db.sql(f"ALTER TABLE `tabListing Certification` DROP COLUMN `{col}`")
		except Exception as e:
			msg = str(e).lower()
			# 'unknown column' veya 'check that column' → zaten yok, sorun değil
			if "unknown" in msg or "doesn't exist" in msg or "check that" in msg:
				continue
			frappe.log_error(
				title=f"cert_v4_listing_cleanup: ALTER TABLE {col}",
				message=str(e),
			)

	frappe.db.commit()
	print(f"[cert_v4_listing_cleanup] Migrated, audited rows: {len(rows)}")

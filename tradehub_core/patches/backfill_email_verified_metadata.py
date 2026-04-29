"""Backfill email_verified_at and email_verified_method for existing rows.

Pattern A geçişi öncesinde Buyer Profile.email_verified=1 olan tüm kayıtlar
için yeni metadata kolonlarına default değer yazar:

    email_verified_at     = creation
    email_verified_method = 'migration'

Ayrıca User.name ile Buyer Profile.user uyumsuz olan hesapları (eski bozuk
change_email akışından kalmış olabilecek) tespit edip Error Log'a düşürür —
manuel müdahale gerekir, bu patch onları otomatik düzeltmez.

Idempotent: tekrar çalıştığında zaten dolu olan satırlara dokunmaz.
"""

import frappe


def execute():
	# 1) email_verified=1 olan kayıtların metadata'sını backfill et
	frappe.db.sql(
		"""
		UPDATE `tabBuyer Profile`
		SET email_verified_at = creation
		WHERE email_verified = 1
		  AND email_verified_at IS NULL
		"""
	)
	frappe.db.sql(
		"""
		UPDATE `tabBuyer Profile`
		SET email_verified_method = 'migration'
		WHERE email_verified = 1
		  AND (email_verified_method IS NULL OR email_verified_method = '')
		"""
	)

	# 2) Bozuk change_email akışından kalmış olabilecek hesapları tespit et
	#    Buyer Profile.user, User tablosunda yoksa inconsistency'dir
	orphans = frappe.db.sql(
		"""
		SELECT bp.name AS buyer_profile, bp.user AS buyer_user
		FROM `tabBuyer Profile` bp
		LEFT JOIN `tabUser` u ON u.name = bp.user
		WHERE u.name IS NULL
		""",
		as_dict=True,
	)

	if orphans:
		lines = ["Buyer Profile rows whose `user` does not match any `tabUser`:"]
		for row in orphans:
			lines.append(f"  - Buyer Profile {row.buyer_profile}: user={row.buyer_user}")
		lines.append("")
		lines.append(
			"Likely cause: the previous change_email() endpoint half-wrote "
			"Buyer Profile but `User` rename failed silently (try/except: pass). "
			"These accounts cannot log in with either old or new email until "
			"manually reconciled."
		)
		frappe.log_error(
			title="Email verification migration: orphaned Buyer Profile rows detected",
			message="\n".join(lines),
		)

	frappe.db.commit()

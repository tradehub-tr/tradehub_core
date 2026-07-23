"""is_verified ve verification_type field'larını DB'den temizle.

KYB Verified rolü artık tek trust sinyali. Eski iki field'ın değerleri
loglandıktan sonra silinir. Bu patch idempotent — DocType'taki field
silindikten sonra Frappe migrate field'ı DB'den otomatik kaldırır,
ama bu patch öncesi durum kayıtlı kalmalı (audit).
"""

import frappe


def execute():
	# Audit: silinmeden önce mevcut değerleri logla (regresyon kontrolü için)
	# Field'lar DocType'tan silindiğinde DB sütunu hâlâ var olabilir (Frappe sync
	# henüz çalışmadan önce çağrıldığında), o yüzden defansif kontrol.
	try:
		rows = frappe.db.sql(
			"""SELECT name, user, is_verified, verification_type
			   FROM `tabAdmin Seller Profile`
			   WHERE is_verified = 1 OR IFNULL(verification_type, '') != ''""",
			as_dict=True,
		)
	except Exception:
		# Field'lar zaten silinmişse SQL patlar — patch idempotent
		rows = []

	for r in rows:
		frappe.log_error(
			title="legacy verification cleanup",
			message=(
				f"Removed legacy verification: name={r.get('name')}, "
				f"user={r.get('user')}, is_verified={r.get('is_verified')}, "
				f"verification_type={r.get('verification_type')!r}"
			),
		)

	# Frappe varsayılan olarak field silindiğinde DB sütununu BIRAKIR (veri kaybı
	# önlemek için defansif). Audit log'u yazdıktan sonra fiziksel sütunları
	# kaldırıyoruz — meta ile DB tutarlı olur.
	for column in ("is_verified", "verification_type"):
		try:
			exists = frappe.db.sql(
				"""SELECT COUNT(*) FROM information_schema.COLUMNS
				   WHERE table_schema = DATABASE()
				     AND table_name = 'tabAdmin Seller Profile'
				     AND column_name = %s""",
				column,
			)
			if exists and exists[0][0]:
				frappe.db.sql(f"ALTER TABLE `tabAdmin Seller Profile` DROP COLUMN `{column}`")
				frappe.logger("patches").info(f"[cleanup_legacy_verification_fields] Sütun düşürüldü: {column}")
		except Exception as e:
			frappe.log_error(
				title="cleanup_legacy_verification_fields drop column",
				message=f"Failed to drop {column}: {e}",
			)

	frappe.db.commit()
	frappe.logger("patches").info(f"[cleanup_legacy_verification_fields] Loglanan kayıt: {len(rows)}")

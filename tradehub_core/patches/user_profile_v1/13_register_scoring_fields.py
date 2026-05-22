"""Patch 13: Scoring field defaults (E2 fırsat).
User Profile JSON'da 20 scoring field zaten tanımlı; bu patch default değerleri set eder."""

import frappe


def execute():
	# joined_at = User.creation
	frappe.db.sql("""
		UPDATE `tabUser Profile` up
		INNER JOIN `tabUser` u ON u.name = up.user
		SET up.joined_at = u.creation
		WHERE up.joined_at IS NULL OR up.joined_at = '0000-00-00 00:00:00'
	""")

	# last_active_at = User.last_active (varsa)
	if frappe.db.has_column("User", "last_active"):
		frappe.db.sql("""
			UPDATE `tabUser Profile` up
			INNER JOIN `tabUser` u ON u.name = up.user
			SET up.last_active_at = u.last_active
			WHERE up.last_active_at IS NULL AND u.last_active IS NOT NULL
		""")

	# account_age_days
	frappe.db.sql("""
		UPDATE `tabUser Profile`
		SET account_age_days = DATEDIFF(NOW(), joined_at)
		WHERE joined_at IS NOT NULL
	""")

	# buyer_level default Bronze
	frappe.db.sql("""
		UPDATE `tabUser Profile`
		SET buyer_level = 'Bronze'
		WHERE buyer_level IS NULL OR buyer_level = ''
	""")

	frappe.db.commit()

"""Patch 8: Tüm User Profile kayıtlarına UP-XXXXXX format member_id atar.
S8 cevabı: eski TH-... ID saklanmıyor."""

import frappe


def execute():
	profiles = frappe.db.sql(
		"""
		SELECT name FROM `tabUser Profile`
		WHERE member_id IS NULL OR member_id = '' OR member_id NOT LIKE 'UP-%'
		ORDER BY creation ASC
	""",
		as_list=True,
	)

	for i, (name,) in enumerate(profiles, start=1):
		new_id = f"UP-{i:06d}"
		frappe.db.set_value("User Profile", name, "member_id", new_id, update_modified=False)

	# Naming Series tablosunu güncelle
	if profiles:
		frappe.db.sql(
			"""
			INSERT INTO `tabSeries` (name, current)
			VALUES ('UP-', %s)
			ON DUPLICATE KEY UPDATE current = VALUES(current)
		""",
			(len(profiles),),
		)

	frappe.db.commit()
	frappe.log_error(
		title="Patch 8: member_id assignment",
		message=f"Assigned UP-000001..UP-{len(profiles):06d} to {len(profiles)} profiles",
	)

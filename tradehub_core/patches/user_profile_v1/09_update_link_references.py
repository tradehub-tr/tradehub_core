"""Patch 9: Seller Profile'a Link veren 4 tabloyu Admin Seller Profile'a yönlendir.
Bloker 3: dev console'da multi-ASP YOK, JOIN tek satır döner.
Format değişimi: email → SEL-XXXXX"""

import frappe

LINK_TARGETS_TO_ASP = [
	("Seller Balance", "seller"),
	("Seller Product", "seller"),
	("RFQ Quote", "seller_profile"),
	("Addresses", "seller"),
]


def execute():
	# Önce multi-ASP fail-safe check
	multi_asp = frappe.db.sql(
		"""
		SELECT user, COUNT(*) AS cnt FROM `tabAdmin Seller Profile`
		WHERE user IS NOT NULL AND user != ''
		GROUP BY user HAVING COUNT(*) > 1
	""",
		as_dict=True,
	)
	if multi_asp:
		frappe.throw(
			f"Patch 9 FAIL: {len(multi_asp)} kullanıcının birden fazla Admin Seller Profile'ı var. "
			"Multi-store mapping manuel karar gerektiriyor."
		)

	results = {}
	for table, column in LINK_TARGETS_TO_ASP:
		if not frappe.db.table_exists(table):
			results[f"{table}.{column}"] = "NO TABLE"
			continue
		if not frappe.db.has_column(table, column):
			results[f"{table}.{column}"] = "NO COLUMN"
			continue

		# Tablo SQL UPDATE
		frappe.db.sql(f"""
			UPDATE `tab{table}` t
			INNER JOIN `tabAdmin Seller Profile` asp ON asp.user = t.`{column}`
			SET t.`{column}` = asp.name
			WHERE t.`{column}` IS NOT NULL
			  AND t.`{column}` LIKE '%@%'
		""")
		results[f"{table}.{column}"] = "OK"

	frappe.db.commit()
	frappe.log_error(
		title="Patch 9: 4 Link target → Admin Seller Profile",
		message=str(results),
	)

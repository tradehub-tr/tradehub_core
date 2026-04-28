"""Sync Listing.min_order_qty with the first B2B pricing tier's min_qty.

When B2B Toplu Fiyatlandırma is enabled, the product detail page advertises
the first tier's minimum (e.g. "MSA: 10-49 adet"). Historically
`min_order_qty` could be set independently, producing listings where the
storefront promised 10 but the quantity stepper still started at 20. The
admin form now auto-syncs these values; this patch backfills existing rows.

Idempotent: only writes when current value differs from the first tier min.
"""

import frappe


def execute():
	rows = frappe.db.sql(
		"""
		SELECT parent, MIN(min_qty) AS first_min
		FROM `tabListing Bulk Pricing Tier`
		WHERE COALESCE(min_qty, 0) > 0
		GROUP BY parent
		""",
		as_dict=True,
	)
	if not rows:
		return

	updated = 0
	for row in rows:
		listing = row.parent
		first_min = int(row.first_min or 0)
		if first_min <= 0:
			continue

		current = frappe.db.get_value(
			"Listing",
			listing,
			["b2b_enabled", "min_order_qty"],
			as_dict=True,
		)
		if not current or not current.b2b_enabled:
			continue
		if int(current.min_order_qty or 0) == first_min:
			continue

		frappe.db.set_value(
			"Listing",
			listing,
			"min_order_qty",
			first_min,
			update_modified=False,
		)
		updated += 1

	if updated:
		frappe.db.commit()
		frappe.logger().info(f"sync_listing_min_order_qty_with_b2b_tier: updated {updated} listings")

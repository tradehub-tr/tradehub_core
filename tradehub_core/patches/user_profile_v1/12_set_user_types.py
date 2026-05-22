"""Patch 12: User.user_type set (K5 final).
- Buyer (can_buy=1, can_sell=0) → Website User
- Seller / Hybrid (can_sell=1) → System User (admin-panel erişimi)
- Platform rolüne sahip user'lar → System User (override)"""

import frappe

PLATFORM_ROLES = frozenset(
	{
		"System Manager",
		"Administrator",
		"Platform Super Admin",
		"Platform Admin",
		"Platform Helpdesk",
		"Compliance Officer",
		"Platform Finance",
	}
)


def execute():
	profiles = frappe.db.sql(
		"""
		SELECT user, can_buy, can_sell FROM `tabUser Profile`
	""",
		as_dict=True,
	)

	counts = {"System User (platform)": 0, "System User (seller)": 0, "Website User": 0}

	for p in profiles:
		user_roles = set(frappe.get_roles(p.user))
		if user_roles & PLATFORM_ROLES:
			target = "System User"
			counts["System User (platform)"] += 1
		elif p.can_sell:
			target = "System User"
			counts["System User (seller)"] += 1
		else:
			target = "Website User"
			counts["Website User"] += 1

		frappe.db.set_value("User", p.user, "user_type", target, update_modified=False)

	frappe.db.commit()
	frappe.log_error(
		title="Patch 12: user_type assignment",
		message=str(counts),
	)

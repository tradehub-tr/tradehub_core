"""Hızlı setup: Feature Catalog seed."""

import frappe

_FEATURES = [
	# Role profile features
	("feature.role.profile.seller_full_access", "Seller Full Access Profile", "role"),
	("feature.role.profile.seller_manager", "Seller Manager Profile", "role"),
	("feature.role.profile.seller_finance_staff", "Seller Finance Staff Profile", "role"),
	("feature.role.profile.seller_operations", "Seller Operations Profile", "role"),
	("feature.role.profile.seller_co_owner", "Seller Co-Owner Profile", "role"),
	("feature.role.profile.buyer_full_access", "Buyer Full Access Profile", "role"),
	("feature.role.profile.buyer_operations", "Buyer Operations Profile", "role"),
	("feature.role.profile.buyer_finance_staff", "Buyer Finance Staff Profile", "role"),
	("feature.role.profile.buyer_approver_l1", "Buyer Approver L1 Profile", "role"),
	("feature.role.profile.buyer_approver_l2", "Buyer Approver L2 Profile", "role"),
	# Core features
	("feature.core_commerce", "Core Commerce", "commerce"),
	("feature.buyer_approval_workflow", "Buyer Approval Workflow", "buyer"),
	("feature.buyer_approval_l2", "Buyer L2 Approval", "buyer"),
	("feature.buyer_team_management", "Buyer Team Management", "buyer"),
	("feature.rfq_module", "RFQ Module", "commerce"),
	("feature.custom_role_creation", "Custom Role Creation", "enterprise"),
]


def execute() -> dict:
	created = []
	skipped = []
	for key, name, category in _FEATURES:
		if frappe.db.exists("Feature Catalog", key):
			skipped.append(key)
			continue
		try:
			doc = frappe.new_doc("Feature Catalog")
			doc.feature_key = key
			doc.display_name = name
			doc.category = category
			doc.feature_type = "boolean"
			doc.default_value = "false"
			doc.introduced_in_version = "1.0"
			doc.insert(ignore_permissions=True)
			created.append(key)
		except Exception as exc:
			frappe.log_error(f"Feature seed failed {key}: {exc}", "seed_features")
	frappe.db.commit()
	return {"created": created, "skipped": skipped}

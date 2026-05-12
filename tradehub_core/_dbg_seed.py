def run():
	import frappe

	if not frappe.db.exists("Moderation Rule", "Auto-Hide Abuse 5+"):
		doc = frappe.new_doc("Moderation Rule")
		doc.rule_name = "Auto-Hide Abuse 5+"
		doc.trigger_type = "abuse_threshold"
		doc.threshold_value = 5
		doc.action = "auto_hide"
		doc.reason_template = "Auto"
		doc.is_active = 1
		doc.insert(ignore_permissions=True)
		print("Inserted 2nd rule")
	print(f"Total active rules: {frappe.db.count('Moderation Rule', {'is_active': 1})}")

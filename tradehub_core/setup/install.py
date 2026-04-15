import frappe
from frappe.permissions import add_permission


def after_install():
	"""Create custom marketplace roles. Idempotent — safe to run on every migrate."""
	_create_marketplace_roles()
	_setup_core_permissions()
	_seed_email_preference_categories()
	frappe.db.commit()


def _setup_core_permissions():
	"""Give Seller role read access to core DocTypes needed for listing management."""
	for doctype in ("Currency", "UOM", "Country"):
		add_permission(doctype, "Seller", 0)


def _create_marketplace_roles():
	roles = [
		{"role_name": "Buyer", "desk_access": 0},
		{"role_name": "Seller", "desk_access": 0},
		{"role_name": "Marketplace Admin", "desk_access": 1},
	]
	for role_data in roles:
		if not frappe.db.exists("Role", role_data["role_name"]):
			role = frappe.new_doc("Role")
			role.role_name = role_data["role_name"]
			role.desk_access = role_data["desk_access"]
			role.insert(ignore_permissions=True)


def _seed_email_preference_categories():
	"""Varsayılan e-posta tercih kategorilerini oluşturur. Idempotent."""
	if not frappe.db.exists("DocType", "Email Preference Category"):
		return

	_seed_category(
		category_key="notification",
		title="Tüm bildirim e-postaları",
		description="iSTOC.com'da önemli hesap güncellemeleri ve etkinlikleri hakkında sizi bilgilendiren e-postalar",
		sort_order=0,
		items=[
			{
				"item_key": "general_notification",
				"title": "Genel bildirim e-postaları",
				"description": "Platformdaki faaliyetleriniz tarafından tetiklenen e-postalar, önemli bildirimler, sipariş güncellemeleri ve hesap değişiklikleri hakkında bilgilendirme yapar.",
				"sort_order": 0,
			},
			{
				"item_key": "dispute_updates",
				"title": "Anlaşmazlık güncellemeleri",
				"description": "Taraf olduğunuz herhangi bir anlaşmazlık olması durumunda, iSTOC ile ilgili tüm bildirim e-postalarını buradan yönetebilirsiniz.",
				"sort_order": 1,
			},
		],
	)

	_seed_category(
		category_key="marketing",
		title="Tüm pazarlama e-postaları",
		description="iSTOC.com'da ürünler ve hizmetler hakkında tanıtım mesajları içeren e-postalar",
		sort_order=1,
		items=[
			{
				"item_key": "general_marketing",
				"title": "Genel pazarlama e-postaları",
				"description": "iSTOC ile ilgili tüm kampanya, indirim, satışlar, etkinlikler ve bunun gibi herhangi bir konu hakkında, tanıtım ve bilgilendirme e-postalarını alırsınız.",
				"sort_order": 0,
			},
			{
				"item_key": "surveys",
				"title": "Anketler",
				"description": "iSTOC ile ilgili hizmet memnuniyetini ölçen bir anket geldiğinde öncesini ve yer aldı gelen bildirimlerin yayılmasını sağlar.",
				"sort_order": 1,
			},
		],
	)


def _seed_category(category_key, title, description, sort_order, items):
	if frappe.db.exists("Email Preference Category", category_key):
		return

	doc = frappe.new_doc("Email Preference Category")
	doc.category_key = category_key
	doc.title = title
	doc.description = description
	doc.sort_order = sort_order
	doc.is_active = 1
	doc.default_enabled = 1

	for item in items:
		doc.append("items", {
			"item_key": item["item_key"],
			"title": item["title"],
			"description": item["description"],
			"default_enabled": 1,
			"sort_order": item["sort_order"],
		})

	doc.insert(ignore_permissions=True)


def cleanup_expired_tokens():
	"""Scheduled daily — Redis TTL handles expiry automatically.
	This is a placeholder for any future DB-level cleanup."""
	pass

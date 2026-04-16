import frappe


def execute():
	"""Varsayılan e-posta tercih kategorilerini ve kalemlerini oluşturur."""
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

	frappe.db.commit()


def _seed_category(category_key, title, description, sort_order, items):
	"""Kategori yoksa oluştur, varsa atla (idempotent)."""
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
		doc.append(
			"items",
			{
				"item_key": item["item_key"],
				"title": item["title"],
				"description": item["description"],
				"default_enabled": 1,
				"sort_order": item["sort_order"],
			},
		)

	doc.insert(ignore_permissions=True)

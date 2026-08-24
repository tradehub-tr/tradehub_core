import frappe
from frappe.permissions import add_permission


def after_install():
	"""Create custom marketplace roles. Idempotent — safe to run on every migrate."""
	_create_marketplace_roles()
	_setup_core_permissions()
	_seed_media_phase4_catalog()
	_seed_media_phase5_defaults()
	_seed_email_preference_categories()
	_seed_supported_currencies()
	_bootstrap_recommendations()
	frappe.db.commit()


def _setup_core_permissions():
	"""Give Seller role read access to core DocTypes needed for listing management."""
	for doctype in ("Currency", "UOM", "Country"):
		add_permission(doctype, "Seller", 0)


def _create_marketplace_roles():
	"""Kod tabanında doğrudan izin yüzeylerinde kullanılan çekirdek rolleri yarat.
	14 hiyerarşik rol (Platform/Seller/Buyer Group) Sprint 3 RBAC reformunda
	tasarlanacak ve o sırada install.py'ye + fixture'a eklenecek."""
	roles = [
		{"role_name": "Buyer", "desk_access": 0},
		{"role_name": "Seller", "desk_access": 1},
		{"role_name": "Marketplace Admin", "desk_access": 1},
		{"role_name": "Marketplace Seller", "desk_access": 1},
		{"role_name": "Marketplace Buyer", "desk_access": 0},
		{"role_name": "Media Superadmin", "desk_access": 1},
	]
	for role_data in roles:
		if not frappe.db.exists("Role", role_data["role_name"]):
			role = frappe.new_doc("Role")
			role.role_name = role_data["role_name"]
			role.desk_access = role_data["desk_access"]
			role.insert(ignore_permissions=True)


def _seed_media_phase4_catalog():
	"""Seed profiles/policies on both fresh installs and ordinary migrations.

	Frappe marks historical patches as applied when an app is first installed,
	so a patch alone only covers upgrades.  The same idempotent projector is
	therefore invoked from ``after_install``/``after_migrate`` as well.
	"""
	required = (
		"Media Profile",
		"Media Policy Profile",
		"Media Content Rule",
		"Media Policy",
		"Media Source",
	)
	if not all(frappe.db.table_exists(doctype) for doctype in required):
		return
	from tradehub_core.patches.v15_9_43_media_phase4_schema import execute
	from tradehub_core.patches.v15_9_44_media_phase4_indexes import execute as install_indexes

	execute()
	install_indexes()


def _seed_media_phase5_defaults():
	"""Fresh install'da Faz 5'in fail-closed retention varsayılanlarını ekle."""
	if not all(
		frappe.db.table_exists(doctype)
		for doctype in ("Media Storage Settings", "Media Storage Profile")
	):
		return
	from tradehub_core.patches.v15_9_45_media_phase5_schema import seed_defaults

	seed_defaults()


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


def _seed_supported_currencies():
	"""Seed default currency metadata for the storefront dropdown. Idempotent."""
	if not frappe.db.exists("DocType", "Supported Currency"):
		return

	currencies = [
		{
			"currency_code": "TRY",
			"symbol": "\u20ba",
			"name_en": "Turkish Lira",
			"name_tr": "T\u00fcrk Liras\u0131",
			"decimal_places": 2,
			"display_order": 1,
			"is_enabled": 1,
		},
		{
			"currency_code": "USD",
			"symbol": "$",
			"name_en": "US Dollar",
			"name_tr": "Amerikan Dolar\u0131",
			"decimal_places": 2,
			"display_order": 2,
			"is_enabled": 1,
		},
		{
			"currency_code": "EUR",
			"symbol": "\u20ac",
			"name_en": "Euro",
			"name_tr": "Euro",
			"decimal_places": 2,
			"display_order": 3,
			"is_enabled": 1,
		},
		{
			"currency_code": "GBP",
			"symbol": "\u00a3",
			"name_en": "British Pound",
			"name_tr": "\u0130ngiliz Sterlini",
			"decimal_places": 2,
			"display_order": 4,
			"is_enabled": 0,
		},
		{
			"currency_code": "CNY",
			"symbol": "\u00a5",
			"name_en": "Chinese Yuan",
			"name_tr": "\u00c7in Yuan\u0131",
			"decimal_places": 2,
			"display_order": 5,
			"is_enabled": 0,
		},
	]

	for c in currencies:
		if not frappe.db.exists("Supported Currency", c["currency_code"]):
			doc = frappe.new_doc("Supported Currency")
			doc.update(c)
			doc.insert(ignore_permissions=True)


def cleanup_expired_tokens():
	"""Scheduled daily — Redis TTL handles expiry automatically.
	This is a placeholder for any future DB-level cleanup."""
	pass


def _bootstrap_recommendations():
	"""Build Category Embeddings + Neighbour Cache + (if cache is empty)
	dispatch the initial full rebuild of Related Listing Cache.

	Three-stage bootstrap:
	  1. Always: rebuild embeddings + neighbour cache (cheap, ~3 min for 10K
	     categories). Idempotent — safe on every migrate.
	  2. Conditional: if Related Listing Cache is empty (first deploy or
	     post-wipe state), dispatch the sharded full rebuild. Dispatcher
	     returns immediately after enqueueing chunks; long workers do the
	     actual work and the last chunk triggers atomic swap.
	  3. If cache already has data: skip rebuild — weekly_long scheduler
	     will refresh on its normal cadence (no need to thrash on every
	     deploy).

	All steps best-effort: failures are logged but don't break the migrate.
	"""
	if not frappe.db.table_exists("Category Embedding"):
		return
	try:
		from tradehub_core.recommendations import embeddings, engine

		stats = embeddings.build_all()
		frappe.logger("tradehub").info(f"bootstrap_recommendations: embeddings={stats}")

		if not frappe.db.table_exists("Related Listing Cache"):
			return
		if frappe.db.count("Related Listing Cache") == 0:
			rebuild_stats = engine.dispatch_full_rebuild()
			frappe.logger("tradehub").info(f"bootstrap_recommendations: initial_rebuild={rebuild_stats}")
	except Exception as exc:
		frappe.log_error(
			title="bootstrap_recommendations failed",
			message=str(exc),
		)

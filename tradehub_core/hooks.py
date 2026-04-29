app_name = "tradehub_core"
app_title = "TradeHub Core"
app_publisher = "TradeHub"
app_description = "TradeHub B2B E-Commerce Backend"
app_email = "dev@tradehub.com"
app_license = "MIT"

after_install = "tradehub_core.setup.install.after_install"
after_migrate = "tradehub_core.setup.install.after_install"
app_icon = "octicon octicon-organization"
app_color = "#0066CC"

required_apps = ["frappe", "erpnext"]

app_include_js = "seller_redirect.js"

fixtures = [
	{
		"dt": "Role",
		"filters": [
			[
				"name",
				"in",
				["Marketplace Seller", "Buyer", "Seller", "Marketplace Admin", "Marketplace Buyer"],
			]
		],
	},
	{
		"dt": "Workspace",
		"filters": [["module", "=", "Tradehub Core"]],
	},
]

scheduler_events = {
	"hourly": [
		# Refresh the Complementary tab of Related Products as new orders land.
		"tradehub_core.recommendations.tasks.refresh_copurchase_lift",
	],
	"daily": [
		"tradehub_core.services.tcmb.fetch_and_update_rates",
		"tradehub_core.setup.install.cleanup_expired_tokens",
		"tradehub_core.utils.notification_cleanup.delete_old_notifications",
		"tradehub_core.api.listing.cleanup_old_search_history",
		"tradehub_core.api.tailored.cleanup_old_user_product_views",
		# Related Products light-maintenance: cheap O(C) jobs that don't
		# need long_queue. Heavy similarity matrix rebuild moved to
		# weekly_long (sharded dispatcher + atomic swap).
		"tradehub_core.recommendations.tasks.rebuild_price_tiers",
		"tradehub_core.recommendations.tasks.autoflag_accessory_categories",
	],
	"weekly_long": [
		# Category embeddings + neighbour cache (build_all tail-calls
		# neighbour_cache.rebuild_all so they stay coherent).
		"tradehub_core.recommendations.tasks.build_category_embeddings",
		# Full Related Listing Cache rebuild via sharded dispatcher.
		# Dispatcher returns fast after enqueueing chunks; chunks fan out
		# across long-queue workers and the last one triggers atomic swap.
		"tradehub_core.recommendations.tasks.rebuild_related_matrix",
	],
}

# ---------------------------------------------------------------------------
# Cache invalidation: storefront listing queries are cached for 30s. Without
# explicit invalidation, admin updates take up to 30s to appear. The hook
# below drops the cache as soon as a Listing is written, so storefront stays
# in sync with the panel.
# ---------------------------------------------------------------------------
doc_events = {
	# Tüm File yüklemelerinde XSS/RCE riskli uzantıları reddet (HATA 23).
	# SVG/HTML/JS/XML gibi browser-execute edebilir formatlar engellenir;
	# raster image, PDF, Office, video, txt güvenli kabul edilir.
	"File": {
		"before_insert": "tradehub_core.utils.security.reject_unsafe_files",
	},
	"Listing": {
		"on_update": [
			"tradehub_core.api.listing.invalidate_listing_cache",
			# Related Products cache: drop rows when the listing goes inactive/invisible.
			"tradehub_core.recommendations.engine.cleanup_cache_if_deactivated",
			# Async recompute for active listings — keeps PROD cache in sync
			# with admin/seller edits without waiting for the weekly rebuild.
			"tradehub_core.recommendations.engine.schedule_recompute_on_listing_update",
		],
		"after_insert": [
			"tradehub_core.api.listing.invalidate_listing_cache",
			"tradehub_core.recommendations.engine.schedule_recompute_on_listing_update",
		],
		"on_trash": [
			"tradehub_core.api.listing.invalidate_listing_cache",
			# Related Products cache: drop rows referencing the deleted listing
			# (as either source or target).
			"tradehub_core.recommendations.engine.cleanup_cache_on_listing_remove",
		],
	},
	# Product Category lifecycle → cascading cleanup of derived data
	# (Category Embedding + Category Neighbour Cache + Related Listing Cache
	# rows for listings under this category).
	"Product Category": {
		"on_trash": "tradehub_core.recommendations.cleanup.on_product_category_trash",
	},
	# Order pipeline → Listing.order_count for the "Çok Satan" Top Ranking
	# pill. We register on `before_save` (not on_update) because the hook
	# needs to read the *true* pre-save metrics_credited from DB and write
	# the corrected value into the in-memory doc before db_update persists
	# it. Wiring on on_update was unsafe — Frappe form saves drop hidden
	# read-only fields, so the in-memory metrics_credited would always be
	# 0 and re-credit on every save (count inflated 2x, 3x, ...).
	"Order": {
		"before_save": "tradehub_core.api.listing.bump_listing_order_counts",
		"on_update": "tradehub_core.api.tailored.invalidate_tailored_user_cache",
	},
	# Seller Review pipeline → seller-proxy rating + review_count denormalized
	# into every listing the seller owns. Drives the "En Çok Değerlendirilen"
	# Top Ranking pill (see api.listing.recompute_seller_rating_proxy).
	"Seller Review": {
		"after_insert": "tradehub_core.api.listing.recompute_seller_rating_proxy",
		"on_update": "tradehub_core.api.listing.recompute_seller_rating_proxy",
		"on_trash": "tradehub_core.api.listing.recompute_seller_rating_proxy",
	},
	# Admin Seller Profile aktiflesince helpdesk team + agent sync
	"Admin Seller Profile": {
		"on_update": "tradehub_core.utils.helpdesk_routing.on_admin_seller_profile_update",
	},
}

# ---------------------------------------------------------------------------
# Seller-Isolation Permissions
# ---------------------------------------------------------------------------
permission_query_conditions = {
	"Listing": "tradehub_core.permissions.listing_query_conditions",
	"Admin Seller Profile": "tradehub_core.permissions.admin_seller_profile_query_conditions",
	"Seller Balance": "tradehub_core.permissions.seller_balance_query_conditions",
	"Seller Review": "tradehub_core.permissions.seller_review_query_conditions",
	"Seller Category": "tradehub_core.permissions.seller_category_query_conditions",
	"Seller Gallery Image": "tradehub_core.permissions.seller_gallery_image_query_conditions",
	"KYB Verification": "tradehub_core.permissions.kyb_verification_query_conditions",
	"Order": "tradehub_core.permissions.order_query_conditions",
	"Seller Inquiry": "tradehub_core.permissions.seller_inquiry_query_conditions",
	"Certification Type": "tradehub_core.permissions.certification_type_query_conditions",
	"Search History": "tradehub_core.permissions.search_history_query_conditions",
	"Brand": "tradehub_core.permissions.brand_query_conditions",
	"Product Family": "tradehub_core.permissions.product_family_query_conditions",
	"Product Attribute": "tradehub_core.permissions.product_attribute_query_conditions",
	"HD Ticket": "tradehub_core.permissions.helpdesk_ticket_query_conditions",
}

has_permission = {
	"Listing": "tradehub_core.permissions.listing_has_permission",
	"Admin Seller Profile": "tradehub_core.permissions.admin_seller_profile_has_permission",
	"Seller Balance": "tradehub_core.permissions.seller_balance_has_permission",
	"Seller Review": "tradehub_core.permissions.seller_review_has_permission",
	"Seller Category": "tradehub_core.permissions.seller_category_has_permission",
	"Seller Gallery Image": "tradehub_core.permissions.seller_gallery_image_has_permission",
	"KYB Verification": "tradehub_core.permissions.kyb_verification_has_permission",
	"Order": "tradehub_core.permissions.order_has_permission",
	"Seller Inquiry": "tradehub_core.permissions.seller_inquiry_has_permission",
	"Certification Type": "tradehub_core.permissions.certification_type_has_permission",
	"Search History": "tradehub_core.permissions.search_history_has_permission",
	"Brand": "tradehub_core.permissions.brand_has_permission",
	"Product Family": "tradehub_core.permissions.product_family_has_permission",
	"Product Attribute": "tradehub_core.permissions.product_attribute_has_permission",
	"HD Ticket": "tradehub_core.permissions.helpdesk_ticket_has_permission",
}

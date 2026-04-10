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
		"filters": [["name", "in", ["Marketplace Seller", "Buyer", "Seller", "Marketplace Admin", "Marketplace Buyer"]]],
	},
	{
		"dt": "Workspace",
		"filters": [["module", "=", "Tradehub Core"]],
	},
]

scheduler_events = {
	"daily": [
		"tradehub_core.setup.install.cleanup_expired_tokens",
		"tradehub_core.utils.notification_cleanup.delete_old_notifications",
		"tradehub_core.api.listing.cleanup_old_search_history",
	],
}

# ---------------------------------------------------------------------------
# Cache invalidation: storefront listing queries are cached for 30s. Without
# explicit invalidation, admin updates take up to 30s to appear. The hook
# below drops the cache as soon as a Listing is written, so storefront stays
# in sync with the panel.
# ---------------------------------------------------------------------------
doc_events = {
	"Listing": {
		"on_update": "tradehub_core.api.listing.invalidate_listing_cache",
		"after_insert": "tradehub_core.api.listing.invalidate_listing_cache",
		"on_trash": "tradehub_core.api.listing.invalidate_listing_cache",
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
	},
	# Seller Review pipeline → seller-proxy rating + review_count denormalized
	# into every listing the seller owns. Drives the "En Çok Değerlendirilen"
	# Top Ranking pill (see api.listing.recompute_seller_rating_proxy).
	"Seller Review": {
		"after_insert": "tradehub_core.api.listing.recompute_seller_rating_proxy",
		"on_update":    "tradehub_core.api.listing.recompute_seller_rating_proxy",
		"on_trash":     "tradehub_core.api.listing.recompute_seller_rating_proxy",
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
}

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
		# Helpdesk SLA breach detection — Helpdesk SLA Policy'ye göre açık
		# ticket'lar için ilk yanıt + çözüm süresi aşımlarını işaretler ve
		# atanan ajan(lar)a / team'e bildirim gönderir.
		"tradehub_core.utils.sla_checker.check_sla_breaches",
		# Faz 6: Sentiment analysis (analiz edilmemiş Approved review'lar)
		"tradehub_core.api.sentiment.batch_analyze_pending",
		# Sprint 2 — E2 fırsat: Buyer metric scheduler (User Profile.metrics)
		"tradehub_core.tasks.recalculate_buyer_metrics",
	],
	"daily": [
		"tradehub_core.services.tcmb.fetch_and_update_rates",
		"tradehub_core.setup.install.cleanup_expired_tokens",
		"tradehub_core.utils.notification_cleanup.delete_old_notifications",
		"tradehub_core.api.listing.cleanup_old_search_history",
		"tradehub_core.api.tailored.cleanup_old_user_product_views",
		# Faz 3: review reputation + recency decay
		"tradehub_core.api.reputation.daily_recompute_all",
		"tradehub_core.api.rating_engine.daily_recompute_listing_weights",
		# Faz 4: Timeline reminders + translation cache cleanup
		"tradehub_core.api.timeline.send_t30_reminders",
		"tradehub_core.api.timeline.send_t90_reminders",
		"tradehub_core.api.timeline.send_t180_reminders",
		"tradehub_core.api.translation.cleanup_old_cache",
		# Faz 5: Translation usage reset + analytics snapshot
		"tradehub_core.api.translation.daily_reset_usage",
		"tradehub_core.api.analytics.daily_snapshot",
		# Faz 6: AB test winner + seller analytics
		"tradehub_core.api.ab_testing.evaluate_finished_tests",
		"tradehub_core.api.seller_analytics.compute_all_sellers",
		# Related Products light-maintenance: cheap O(C) jobs that don't
		# need long_queue. Heavy similarity matrix rebuild moved to
		# weekly_long (sharded dispatcher + atomic swap).
		"tradehub_core.recommendations.tasks.rebuild_price_tiers",
		"tradehub_core.recommendations.tasks.autoflag_accessory_categories",
		# Sertifika süre dolma kontrolü — 30/7/0 gün öncesi bildirim,
		# süresi dolanı verification_status=Rejected ile auto-disable.
		"tradehub_core.utils.cert_expiry_check.check_certificate_expiry",
		# Sprint 2 — E2 fırsat: Buyer scoring + level pipeline (daily)
		"tradehub_core.tasks.calculate_buyer_scores",
		"tradehub_core.tasks.buyer_level_tasks",
		"tradehub_core.tasks.aggregate_buyer_kpi_summaries",
		"tradehub_core.tasks.refresh_user_segments",
	],
	"weekly_long": [
		# Category embeddings + neighbour cache (build_all tail-calls
		# neighbour_cache.rebuild_all so they stay coherent).
		"tradehub_core.recommendations.tasks.build_category_embeddings",
		# Full Related Listing Cache rebuild via sharded dispatcher.
		# Dispatcher returns fast after enqueueing chunks; chunks fan out
		# across long-queue workers and the last one triggers atomic swap.
		"tradehub_core.recommendations.tasks.rebuild_related_matrix",
		# Faz 4: B2B Vine — eligible reviewer'lara yeni ürün daveti
		"tradehub_core.api.reputation.send_trusted_reviewer_invitations",
		# Sprint 2 — E2 fırsat: weekly heavy buyer KPI/grade tasks
		"tradehub_core.tasks.calculate_customer_grades",
		"tradehub_core.tasks.update_buyer_kpi_template_stats",
		"tradehub_core.tasks.calculate_buyer_kpi_scores",
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
		"validate": "tradehub_core.utils.cert_validate.validate_listing_certifications",
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
	# Listing Review pipeline (Faz 1+2+3) — ürün bazlı yorum.
	# Controller içinde de tetikleme yapılıyor; bu hook'lar savunma katmanı.
	"Listing Review": {
		"after_insert": [
			"tradehub_core.api.review.on_review_after_insert",
			"tradehub_core.api.risk.compute_and_apply_risk_score",
			"tradehub_core.api.webhooks.notify_admin_new_review",
			"tradehub_core.api.moderation.check_auto_rules",
			"tradehub_core.api.sentiment.queue_analysis",
		],
		"on_update": [
			"tradehub_core.api.review.on_review_on_update",
			"tradehub_core.api.reputation.recompute_on_review_update",
			"tradehub_core.api.push.notify_status_change",
		],
		"on_trash": "tradehub_core.api.review.on_review_on_trash",
	},
	"Listing Review Image": {
		"after_insert": "tradehub_core.api.moderation.check_image_content",
	},
	# Faz 3: helpful/abuse → reviewer reputation güncellemesi
	"Review Helpful Vote": {
		"after_insert": "tradehub_core.api.reputation.recompute_on_helpful_vote",
		"on_trash": "tradehub_core.api.reputation.recompute_on_helpful_vote",
	},
	"Review Abuse Report": {
		"after_insert": "tradehub_core.api.reputation.recompute_on_abuse_report",
	},
	# Admin Seller Profile aktiflesince helpdesk team + agent sync +
	# Marketplace Seller rolünü user'a otomatik bağla/kaldır.
	# (CRM doctype'larındaki Frappe role-level DocPerm bu role bağlı.)
	"Admin Seller Profile": {
		"validate": "tradehub_core.utils.cert_validate.validate_seller_certifications",
		"after_insert": "tradehub_core.utils.seller_role_sync.sync_marketplace_seller_role",
		"on_update": [
			"tradehub_core.utils.helpdesk_routing.on_admin_seller_profile_update",
			"tradehub_core.utils.seller_role_sync.sync_marketplace_seller_role",
		],
	},
	# CRM kayıtlarında seller'ı creator'dan otomatik resolve et + lead/deal_owner
	# alanını da creator'a sabitle (Faz 1 tek kullanıcı modeli, UI'da atama yok).
	"CRM Lead": {
		"before_insert": [
			"tradehub_core.utils.crm_seller_autoset.autoset_seller",
			"tradehub_core.utils.crm_seller_autoset.autoset_owner",
		],
	},
	"CRM Deal": {
		"before_insert": [
			"tradehub_core.utils.crm_seller_autoset.autoset_seller",
			"tradehub_core.utils.crm_seller_autoset.autoset_owner",
		],
	},
	"CRM Organization": {
		"before_insert": "tradehub_core.utils.crm_seller_autoset.autoset_seller",
	},
	"Contact": {
		"before_insert": "tradehub_core.utils.crm_seller_autoset.autoset_seller",
	},
	"CRM Task": {
		"before_insert": "tradehub_core.utils.crm_seller_autoset.autoset_seller",
	},
	"FCRM Note": {
		"before_insert": "tradehub_core.utils.crm_seller_autoset.autoset_seller",
	},
	"CRM Call Log": {
		"before_insert": "tradehub_core.utils.crm_seller_autoset.autoset_seller",
	},
	# Header Notice lifecycle → invalidate 60s Redis cache so storefront sees
	# fresh banner/notice data within the next request after any admin edit.
	"Header Notice": {
		"after_insert": "tradehub_core.api.header_notice.invalidate_cache",
		"on_update": "tradehub_core.api.header_notice.invalidate_cache",
		"on_trash": "tradehub_core.api.header_notice.invalidate_cache",
	},
	# Header Notice Settings singleton → also invalidate cache when display_mode changes.
	"Header Notice Settings": {
		"on_update": "tradehub_core.api.header_notice.invalidate_cache",
	},
}

# ---------------------------------------------------------------------------
# Seller-Isolation Permissions
# ---------------------------------------------------------------------------
permission_query_conditions = {
	# Sprint 2 — User Profile birleşmesi
	"User Profile": "tradehub_core.permissions.user_profile_query_conditions",
	"Listing": "tradehub_core.permissions.listing_query_conditions",
	"Admin Seller Profile": "tradehub_core.permissions.admin_seller_profile_query_conditions",
	"Seller Balance": "tradehub_core.permissions.seller_balance_query_conditions",
	"Seller Review": "tradehub_core.permissions.seller_review_query_conditions",
	"Listing Review": "tradehub_core.permissions.listing_review_query_conditions",
	"Review Helpful Vote": "tradehub_core.permissions.review_helpful_vote_query_conditions",
	"Review Abuse Report": "tradehub_core.permissions.review_abuse_report_query_conditions",
	"Listing Question": "tradehub_core.permissions.listing_question_query_conditions",
	"Order Dispute": "tradehub_core.permissions.order_dispute_query_conditions",
	"Trusted Reviewer Invitation": "tradehub_core.permissions.trusted_reviewer_invitation_query_conditions",
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
	# CRM scope (Marketplace Seller → kendi `seller` field'ı)
	"CRM Lead": "tradehub_core.permissions.crm_lead_query_conditions",
	"CRM Deal": "tradehub_core.permissions.crm_deal_query_conditions",
	"CRM Organization": "tradehub_core.permissions.crm_organization_query_conditions",
	"Contact": "tradehub_core.permissions.contact_query_conditions",
	"CRM Task": "tradehub_core.permissions.crm_task_query_conditions",
	"FCRM Note": "tradehub_core.permissions.fcrm_note_query_conditions",
	"CRM Call Log": "tradehub_core.permissions.crm_call_log_query_conditions",
	"Platform Notification": "tradehub_core.tradehub_core.doctype.platform_notification.platform_notification.get_permission_query_conditions",
}

has_permission = {
	# Sprint 2 — User Profile birleşmesi
	"User Profile": "tradehub_core.permissions.user_profile_has_permission",
	"Listing": "tradehub_core.permissions.listing_has_permission",
	"Admin Seller Profile": "tradehub_core.permissions.admin_seller_profile_has_permission",
	"Seller Balance": "tradehub_core.permissions.seller_balance_has_permission",
	"Seller Review": "tradehub_core.permissions.seller_review_has_permission",
	"Listing Review": "tradehub_core.permissions.listing_review_has_permission",
	"Review Helpful Vote": "tradehub_core.permissions.review_helpful_vote_has_permission",
	"Review Abuse Report": "tradehub_core.permissions.review_abuse_report_has_permission",
	"Listing Question": "tradehub_core.permissions.listing_question_has_permission",
	"Order Dispute": "tradehub_core.permissions.order_dispute_has_permission",
	"Trusted Reviewer Invitation": "tradehub_core.permissions.trusted_reviewer_invitation_has_permission",
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
	"CRM Lead": "tradehub_core.permissions.crm_lead_has_permission",
	"CRM Deal": "tradehub_core.permissions.crm_deal_has_permission",
	"CRM Organization": "tradehub_core.permissions.crm_organization_has_permission",
	"Contact": "tradehub_core.permissions.contact_has_permission",
	"CRM Task": "tradehub_core.permissions.crm_task_has_permission",
	"FCRM Note": "tradehub_core.permissions.fcrm_note_has_permission",
	"CRM Call Log": "tradehub_core.permissions.crm_call_log_has_permission",
	"Platform Notification": "tradehub_core.tradehub_core.doctype.platform_notification.platform_notification.has_permission",
	"RFQ": "tradehub_core.permissions.rfq_has_permission",
}

# ---------------------------------------------------------------------------
# Whitelisted method override'ları
# ---------------------------------------------------------------------------
# Frappe CRM app'inin `crm.api.session.get_users` endpoint'i default'ta
# sitedeki tüm aktif User'ları döner — multi-tenant marketplace'de satıcılara
# diğer tenant'ların personelini sızdırır. Aşağıdaki override Marketplace
# Seller'a sadece kendisini, admin/sales rollerine tüm sistem kullanıcılarını
# döndürür.
override_whitelisted_methods = {
	"crm.api.session.get_users": "tradehub_core.api.v1.crm_overrides.get_users",
	"crm.api.session.get_organizations": "tradehub_core.api.v1.crm_overrides.get_organizations",
}

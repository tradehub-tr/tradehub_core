app_name = "tradehub_core"
app_title = "TradeHub Core"
app_publisher = "TradeHub"
app_description = "TradeHub B2B E-Commerce Backend"
app_email = "dev@tradehub.com"
app_license = "MIT"

after_install = "tradehub_core.setup.install.after_install"
after_migrate = [
	"tradehub_core.setup.install.after_install",
]
app_icon = "octicon octicon-organization"
app_color = "#0066CC"

required_apps = ["frappe", "erpnext"]

app_include_js = "seller_redirect.js"

# SEO: staging/backend ortam yanıtlarına X-Robots-Tag noindex basar.
# `seo_noindex_guard` site-config bayrağı default=0 — bayrak açılmadan no-op.
after_request = ["tradehub_core.seo.noindex_guard.apply_noindex_header"]

fixtures = [
	{
		"dt": "Role",
		"filters": [
			[
				"name",
				"in",
				[
					"Marketplace Seller",
					"Buyer",
					"Seller",
					"Marketplace Admin",
					"Marketplace Buyer",
					# FAZ 2.4 — B2B alıcı onay zinciri rolleri
					"Buyer Approver L1",
					"Buyer Approver L2",
					# FAZ 3.2 — Compliance Officer (PII jurisdiction yetkilisi)
					"Compliance Officer",
					# FAZ 5.1 — Buyer/Seller/Platform sub-rolleri (role_profile.json'da
					# referans edilmesine rağmen DB'de yoktu — Role Profile bundle'ları
					# bunlarsız boş yetki dağıtıyordu).
					"Buyer Admin",
					"Buyer Procurement",
					"Buyer Finance",
					"Buyer Viewer",
					"Seller Admin",
					"Seller Co-Owner",
					"Seller Finance",
					"Seller Staff",
					"Seller Viewer",
					"Platform Admin",
					"Platform Finance",
					"Support Agent",
					# Saha pazarlama hakediş sistemi — saha elemanı rolü
					"Saha Pazarlama",
					# Faz C — ekip lideri onay/yönetim katmanı
					"Saha Ekip Lideri",
					# Lojistik modül rolleri (TUR-103)
					"Logistics Manager",
					"Logistics Operator",
					"Carrier Integration Manager",
				],
			]
		],
	},
	{
		"dt": "Workspace",
		"filters": [["module", "=", "Tradehub Core"]],
	},
	# FAZ 1.2 — Entitlement düzlemi (L0)
	# Region, Feature Catalog, Subscription Plan default kayıtları.
	# Süper Admin sonradan Permission Console üzerinden bu kayıtları
	# özelleştirebilir / yeni plan ekleyebilir.
	{
		"dt": "Region",
	},
	{
		"dt": "Feature Catalog",
	},
	{
		"dt": "Subscription Plan",
	},
	# version-15 — ERPNext Custom Field fixture'ları (modül scope)
	{
		"dt": "Custom Field",
		"filters": [["module", "=", "Tradehub Core"]],
	},
]

scheduler_events = {
	# Trial reminder (T-3g / T-1g / T-2s) + expiry. 2 saat hassasiyeti günlük
	# job ile yakalanamaz → 30 dakikada bir. Idempotent (reminder_*_sent flag'leri).
	"cron": {
		"*/30 * * * *": [
			"tradehub_core.services.subscription_lifecycle.process_trial_lifecycle",
		],
	},
	"hourly": [
		# Refresh the Complementary tab of Related Products as new orders land.
		"tradehub_core.recommendations.tasks.refresh_copurchase_lift",
		# Helpdesk SLA breach detection — Helpdesk SLA Policy'ye göre açık
		# ticket'lar için ilk yanıt + çözüm süresi aşımlarını işaretler ve
		# atanan ajan(lar)a / team'e bildirim gönderir.
		"tradehub_core.utils.sla_checker.check_sla_breaches",
		# Faz 6: Sentiment analysis (analiz edilmemiş Approved review'lar)
		"tradehub_core.api.sentiment.batch_analyze_pending",
		# Social Proof: 24 saatten eski view counter'ları sıfırla (rolling window)
		"tradehub_core.api.social_proof.reset_view_counters_rolling_24h",
		# Sprint 2 — E2 fırsat: Buyer metric scheduler (User Profile.metrics)
		"tradehub_core.tasks.recalculate_buyer_metrics",
		# Aktif rezervasyon penceresi dolan kayıtları Expired yap (chat gating
		# için doğru güncel state'i tutar).
		"tradehub_core.api.reservation.expire_old_reservations",
		# Bulk Import: 1 saatten uzun Running kalan stuck job'ları Failed'a çek.
		# (Project crons henüz aktif değil — hourly içine alındı.)
		"tradehub_core.bulk_import.tasks.detect_stuck_bulk_jobs",
		# FAZ 3.4 — OpenClaw anomali algılama
		"tradehub_core.services.anomaly_detector.run_detection",
		# FAZ 3.5 — Geçici yetki expire
		"tradehub_core.services.delegation_service.expire_overdue_delegations",
		# Seller XML Feed: vadesi gelen (fetch_hour == şu an, 24 saatten eski)
		# etkin feed'leri long-queue'ya çekme işine atar.
		"tradehub_core.bulk_import.feed_scheduler.process_due_feeds",
	],
	"daily": [
		# Görsel optimizasyonunda saklanan orijinallerin geri alma penceresi dolunca
		# silinmesi. Nihai depolama kazancı burada gerçekleşir — o güne kadar arşiv
		# diski geçici olarak şişirir (GORSEL-OPTIMIZASYON.md §6).
		"tradehub_core.media.archive.purge_expired",
		# Çöpe taşınan görsellerin 30 günlük geri alma penceresi dolunca kalıcı silinmesi.
		"tradehub_core.media.trash.purge_expired",
		# Medya yedeği: dosyalar + `File` kayıtları (TUR-131). Günlük, çünkü
		# ölçüm günde ~12 MB değişim gösteriyor — daha sık almanın kazancı yok,
		# daha seyrek almak bir günden fazla veri riske atıyor. Depolama
		# içerik-adresli: değişmeyen dosya yeniden yazılmıyor.
		"tradehub_core.media.backup.run_scheduled",
		# Saha hakediş kota bonusu — on-approval tetiklemesinin günlük güvenlik ağı.
		"tradehub_core.tradehub_core.utils.field_commission.process_quota_bonuses",
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
		# Mağaza profili performans metrikleri (total_orders/response/score_grade)
		"tradehub_core.tasks.recompute_seller_performance_metrics",
		# Related Products light-maintenance: cheap O(C) jobs that don't
		# need long_queue. Heavy similarity matrix rebuild moved to
		# weekly_long (sharded dispatcher + atomic swap).
		"tradehub_core.recommendations.tasks.rebuild_price_tiers",
		"tradehub_core.recommendations.tasks.autoflag_accessory_categories",
		# Sertifika süre dolma kontrolü — 30/7/0 gün öncesi bildirim,
		# süresi dolanı verification_status=Rejected ile auto-disable.
		"tradehub_core.utils.cert_expiry_check.check_certificate_expiry",
		# FAZ 3.5 — ReBAC ↔ Frappe drift detection
		"tradehub_core.services.rebac_drift_detection.scan_drift",
		# SEO sitemap rebuild — 5 doctype + index; asıl iş LONG queue'ya
		# enqueue edilir (BE-MAP: milyon-kayıt ölçeğinde parçalı disk cache).
		"tradehub_core.seo.tasks.daily_sitemap_rebuild",
		# Sprint 2 — E2 fırsat: Buyer scoring + level pipeline (daily)
		"tradehub_core.tasks.calculate_buyer_scores",
		"tradehub_core.tasks.buyer_level_tasks",
		"tradehub_core.tasks.aggregate_buyer_kpi_summaries",
		"tradehub_core.tasks.refresh_user_segments",
		# Bulk Import: 90 günden eski tamamlanmış job'ları temizle +
		# uzun süre kullanılmayan template profile'ları arşivle.
		"tradehub_core.bulk_import.tasks.cleanup_old_bulk_import_jobs",
		"tradehub_core.bulk_import.tasks.cleanup_stale_seller_template_profiles",
		# FAZ 1.4 — Audit retention (90 gün sıcak)
		"tradehub_core.audit.tasks.archive_old_decision_logs",
		# Trial lifecycle (reminder + auto-expiry) → cron */30'a taşındı
		# (bkz. scheduler_events["cron"]; 2 saat reminder hassasiyeti için).
		# FAZ 3.5 — Privacy: veri saklama politikası uygulama + export temizliği
		"tradehub_core.audit.tasks.run_data_retention_enforcement",
		"tradehub_core.audit.tasks.cleanup_expired_data_exports",
		# KVKK Madde 7 — hesap silme sonrası 30 gün geçen PII anonimleştirme
		"tradehub_core.privacy.account_deletion.anonymize_pending_deletions",
	],
	"weekly_long": [
		# A2 — ReBAC enforce-hazırlık raporu (RBAC vs ReBAC, doctype-başına verdict).
		# İnvaziv değil: read-only, enforce açmaz; özeti Error Log'a yazar
		# (title=rebac.enforce_readiness; over-grant belirirse [OVER-GRANT]).
		"tradehub_core.services.rebac_drift_detection.weekly_enforce_readiness_report",
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
		# FAZ 1.4 — Audit retention + haftalık özet
		"tradehub_core.audit.tasks.archive_old_role_change_logs",
		"tradehub_core.audit.tasks.archive_old_override_logs",
		"tradehub_core.audit.tasks.weekly_audit_summary",
		# FAZ 3.5 — Privacy: DPA süre sonu uyarısı
		"tradehub_core.audit.tasks.check_expiring_dpas",
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
		# Medya yüklemesini denetime yaz — "bu görseli hangi satıcı yükledi"
		# sorusunun tek kaynağı (TUR-140). Yalnız görsel/video uzantıları
		# kaydedilir; kanca best-effort, yüklemeyi asla engellemez.
		# İki kanca: durum damgası (TUR-138) + denetim kaydı (TUR-140).
		# Durum önce yazılır ki denetim kaydı dosyayı doğru durumda görsün.
		"after_insert": [
			"tradehub_core.media.states.on_file_insert",
			"tradehub_core.media.audit.on_file_insert",
		],
	},
	# Currency cache invalidation — admin manuel düzenlemesinde düş.
	# (tcmb_fx daily job db.set_value kullandığı için ayrıca explicit invalidate eder.)
	"Currency Rate Pair": {
		"on_update": "tradehub_core.api.currency.invalidate_currency_cache",
		"after_insert": "tradehub_core.api.currency.invalidate_currency_cache",
		"on_trash": "tradehub_core.api.currency.invalidate_currency_cache",
	},
	"Supported Currency": {
		"on_update": "tradehub_core.api.currency.invalidate_currency_cache",
		"after_insert": "tradehub_core.api.currency.invalidate_currency_cache",
		"on_trash": "tradehub_core.api.currency.invalidate_currency_cache",
	},
	"Listing": {
		# FAZ 1.1 — Tenant izolasyonu (seller_profile autoset + cross-seller koruma).
		# FAZ 1.2 — Entitlement check (multi_variant capability + max_products quota).
		# Sıra önemli: önce tenant (seller_profile set edilsin), sonra entitlement.
		"before_insert": [
			"tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
			"tradehub_core.entitlement.checks.check_listing_creation_quota",
		],
		# version-15 — SEO slug auto-generate (validate öncesi)
		"before_validate": "tradehub_core.seo.hooks_seo.auto_generate_slug",
		"validate": [
			"tradehub_core.utils.cert_validate.validate_listing_certifications",
			# FAZ 1.1 — Mevcut Listing'in seller_profile alanı değiştirilemez.
			"tradehub_core.utils.tenant.validate_seller_isolation_on_save",
			# FAZ 1.2 — Update sırasında çoklu varyant capability + bölge kontrolü.
			"tradehub_core.entitlement.checks.validate_listing_features",
			"tradehub_core.entitlement.checks.validate_listing_regions",
			# version-15 — SEO meta length warn
			"tradehub_core.seo.hooks_seo.validate_seo_lengths",
			# ECA: two-phase (Seller Phase → Admin Phase) rule dispatcher.
			# Listing save'inde her zaman çalışır; bulk_import context'inde de
			# aynı pipeline'a girer (Bulk Import Job bağlamı dispatcher içinde set edilir).
			"tradehub_core.eca.dispatcher.evaluate_rules_two_phase",
		],
		"on_update": [
			"tradehub_core.seo.hooks_seo.invalidate_url_cache",
			"tradehub_core.seo.hooks_seo.invalidate_sitemap_for",
			"tradehub_core.api.listing.invalidate_listing_cache",
			# Related Products cache: drop rows when the listing goes inactive/invisible.
			"tradehub_core.recommendations.engine.cleanup_cache_if_deactivated",
			# Async recompute for active listings — keeps PROD cache in sync
			# with admin/seller edits without waiting for the weekly rebuild.
			"tradehub_core.recommendations.engine.schedule_recompute_on_listing_update",
			# ECA two-phase dispatcher (post-save context).
			"tradehub_core.eca.dispatcher.evaluate_rules_two_phase",
			# #C2 — seller_profile değişiminde ReBAC store_link tuple'ını hizala.
			"tradehub_core.services.tuple_sync.on_listing_update",
		],
		"after_insert": [
			"tradehub_core.api.listing.invalidate_listing_cache",
			"tradehub_core.recommendations.engine.schedule_recompute_on_listing_update",
			# ECA two-phase dispatcher (after_insert context).
			"tradehub_core.eca.dispatcher.evaluate_rules_two_phase",
			# FAZ 2.3 — Listing.store_link ReBAC tuple
			"tradehub_core.services.tuple_sync.on_listing_insert",
		],
		"on_trash": [
			"tradehub_core.api.listing.invalidate_listing_cache",
			# Related Products cache: drop rows referencing the deleted listing
			# (as either source or target).
			"tradehub_core.recommendations.engine.cleanup_cache_on_listing_remove",
			# FAZ 2.3 — Tuple cleanup
			"tradehub_core.services.tuple_sync.on_listing_trash",
		],
	},
	# Product Category lifecycle → cascading cleanup of derived data
	# (Category Embedding + Category Neighbour Cache + Related Listing Cache
	# rows for listings under this category).
	"Product Category": {
		"on_trash": [
			"tradehub_core.recommendations.cleanup.on_product_category_trash",
			# Kategori silinince kategori-bağımlı storefront cache'lerini düş.
			"tradehub_core.api.listing.invalidate_category_cache",
		],
		"before_validate": "tradehub_core.seo.hooks_seo.auto_generate_slug",
		"validate": "tradehub_core.seo.hooks_seo.validate_seo_lengths",
		# Yeni kategori eklenince cache'i düş (bulk import guard'lı — bkz. invalidate_category_cache).
		"after_insert": "tradehub_core.api.listing.invalidate_category_cache",
		"on_update": [
			"tradehub_core.seo.hooks_seo.invalidate_url_cache",
			"tradehub_core.seo.hooks_seo.invalidate_sitemap_for",
			# Kategori adı/ağaç değişince kategori-bağımlı storefront cache'lerini düş.
			"tradehub_core.api.listing.invalidate_category_cache",
		],
	},
	# Brand / Seller Profile SEO altyapısı: slug auto-generate + meta length warn
	# + Cloudflare cache purge + sitemap invalidate.
	"Brand": {
		"before_validate": "tradehub_core.seo.hooks_seo.auto_generate_slug",
		"validate": "tradehub_core.seo.hooks_seo.validate_seo_lengths",
		"on_update": [
			"tradehub_core.seo.hooks_seo.invalidate_url_cache",
			"tradehub_core.seo.hooks_seo.invalidate_sitemap_for",
		],
	},
	# Statik sayfa SEO override değişince cache + sitemap dirty (Faz 4c).
	"Static Page SEO": {
		"on_update": [
			"tradehub_core.seo.hooks_seo.invalidate_url_cache",
			"tradehub_core.seo.hooks_seo.invalidate_sitemap_for",
		],
	},
	# SEO Redirect değişince Redis cache temizle (Faz 6).
	"SEO Redirect": {
		"on_update": "tradehub_core.seo.redirect_cache.invalidate_redirect_cache",
		"on_trash": "tradehub_core.seo.redirect_cache.invalidate_redirect_cache",
	},
	# Order pipeline → Listing.order_count for the "Çok Satan" Top Ranking
	# pill. We register on `before_save` (not on_update) because the hook
	# needs to read the *true* pre-save metrics_credited from DB and write
	# the corrected value into the in-memory doc before db_update persists
	# it. Wiring on on_update was unsafe — Frappe form saves drop hidden
	# read-only fields, so the in-memory metrics_credited would always be
	# 0 and re-credit on every save (count inflated 2x, 3x, ...).
	"Order": {
		# FAZ 1.1 — Tenant izolasyonu. NOT: Order bir counterparty kaydıdır
		# (seller = ürünün satıcısı, kaydı oluşturan alıcının kendi mağazası
		# DEĞİL). Bu yüzden enforce/validate hook'ları tenant.py'deki
		# COUNTERPARTY_SELLER_DOCTYPES seti üzerinden erken return yapar.
		# Order'ın izolasyonu order_query_conditions + order_has_permission ile,
		# buyer == session.user kontrolü ise cart.py checkout akışında sağlanır.
		"before_insert": [
			"tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
			# FAZ 3.3 — Procurement gating: onaylı tedarikçi + cost center bütçesi
			"tradehub_core.services.supplier_whitelist.validate_order_supplier",
			"tradehub_core.services.cost_center.validate_order_cost_center",
		],
		"validate": "tradehub_core.utils.tenant.validate_seller_isolation_on_save",
		"before_save": [
			"tradehub_core.api.listing.bump_listing_order_counts",
			# version-15 — sosyal kanıt sayaç cache temizle
			"tradehub_core.api.social_proof.invalidate_for_order",
		],
		"after_insert": [
			"tradehub_core.services.tuple_sync.on_order_insert",
			# FAZ 2.5 — approval workflow başlat (rule match → Order Approval create)
			"tradehub_core.services.order_approval_hooks.on_order_after_insert",
		],
		"on_update": [
			"tradehub_core.api.tailored.invalidate_tailored_user_cache",
			# #C2 — seller_profile/buyer_org değişiminde ReBAC link tuple'larını hizala.
			"tradehub_core.services.tuple_sync.on_order_update",
		],
		"on_trash": "tradehub_core.services.tuple_sync.on_order_trash",
	},
	# Seller Review pipeline → seller-proxy rating + review_count denormalized
	# into every listing the seller owns. Drives the "En Çok Değerlendirilen"
	# Top Ranking pill (see api.listing.recompute_seller_rating_proxy).
	"Seller Review": {
		# FAZ 1.1 — Tenant izolasyonu. Seller Review buyer tarafından yazılır;
		# buyer'ın seller'ı yok, hook field'a dokunmaz. Cross-seller attempt'i
		# (buyer seller_profile field'ını başka satıcıya işaret edecek şekilde
		# manipüle etmeye çalışırsa) hook skip eder ama permission_query_conditions
		# ve has_permission mevcut koruyu sağlar.
		"before_insert": "tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
		"validate": "tradehub_core.utils.tenant.validate_seller_isolation_on_save",
		"after_insert": "tradehub_core.api.listing.recompute_seller_rating_proxy",
		"on_update": "tradehub_core.api.listing.recompute_seller_rating_proxy",
		"on_trash": "tradehub_core.api.listing.recompute_seller_rating_proxy",
	},
	# Listing Review pipeline (Faz 1+2+3) — ürün bazlı yorum.
	# Controller içinde de tetikleme yapılıyor; bu hook'lar savunma katmanı.
	# Tenant isolation hook'ları (before_insert + validate) version-15'ten,
	# review pipeline'ı HEAD'den — ikisi birlikte tek dict altında (Python duplicate
	# dict key'lerinde ikinci birinciyi sessizce overwrite eder = pipeline kaybolur).
	"Listing Review": {
		"before_insert": "tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
		"validate": "tradehub_core.utils.tenant.validate_seller_isolation_on_save",
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
		"before_insert": "tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
		"validate": "tradehub_core.utils.tenant.validate_seller_isolation_on_save",
		"after_insert": "tradehub_core.api.reputation.recompute_on_helpful_vote",
		"on_trash": "tradehub_core.api.reputation.recompute_on_helpful_vote",
	},
	"Review Abuse Report": {
		"before_insert": "tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
		"validate": "tradehub_core.utils.tenant.validate_seller_isolation_on_save",
		"after_insert": "tradehub_core.api.reputation.recompute_on_abuse_report",
	},
	# Admin Seller Profile aktiflesince helpdesk team + agent sync +
	# Marketplace Seller rolünü user'a otomatik bağla/kaldır.
	# (CRM doctype'larındaki Frappe role-level DocPerm bu role bağlı.)
	"Admin Seller Profile": {
		# version-15 — SEO slug auto-generate
		"before_validate": "tradehub_core.seo.hooks_seo.auto_generate_slug",
		# Sprint 5 — IBAN/bank/tax_id field maskeleme (per-capability)
		"on_load": "tradehub_core.api.v1.crm_masking.mask_pii_fields",
		"validate": [
			"tradehub_core.utils.cert_validate.validate_seller_certifications",
			# FAZ 1.5 — Banka/vergi değişikliği Owner-only (Co-Owner bile yapamaz)
			"tradehub_core.utils.owner_lock.enforce_owner_only_fields",
			# version-15 — SEO meta length warn
			"tradehub_core.seo.hooks_seo.validate_seo_lengths",
		],
		"after_insert": [
			"tradehub_core.utils.seller_role_sync.sync_marketplace_seller_role",
			# FAZ 2.3 — Store entity ReBAC tuple sync
			"tradehub_core.services.tuple_sync.on_admin_seller_profile_insert",
		],
		"on_update": [
			"tradehub_core.utils.helpdesk_routing.on_admin_seller_profile_update",
			"tradehub_core.utils.seller_role_sync.sync_marketplace_seller_role",
			"tradehub_core.seo.hooks_seo.invalidate_url_cache",
			"tradehub_core.seo.hooks_seo.invalidate_sitemap_for",
			# #C2 — owner (user) değişiminde ReBAC owner/member tuple'larını hizala.
			"tradehub_core.services.tuple_sync.on_admin_seller_profile_update",
		],
		"on_trash": "tradehub_core.services.tuple_sync.on_admin_seller_profile_trash",
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
		# Saha hakediş: Won olunca otomatik Beklemede hakediş üret.
		"on_update": "tradehub_core.utils.field_commission.generate_on_deal_won",
	},
	"CRM Organization": {
		"before_insert": "tradehub_core.utils.crm_seller_autoset.autoset_seller",
		# FAZ 2.4 — parent_org cycle koruması (validate)
		"validate": "tradehub_core.utils.organization_hierarchy.validate_no_cycle",
		# FAZ 2.3 — Organization → buyer_org tuple + parent hiyerarşi
		"after_insert": "tradehub_core.services.tuple_sync.on_organization_insert",
		"on_trash": "tradehub_core.services.tuple_sync.on_organization_trash",
	},
	"Contact": {
		"before_insert": "tradehub_core.utils.crm_seller_autoset.autoset_seller",
		# Sprint 5 — view.customer_pii capability'si olmayan kullanıcı için
		# email_id, phone, mobile_no + Contact Email/Phone child satırları maskelenir.
		"on_load": "tradehub_core.api.v1.crm_masking.mask_pii_fields",
	},
	"User Profile": {
		# Sprint 5 — IBAN/bank (view.bank_info) + tax_id (view.tax_id) per-field maskeleme
		"on_load": "tradehub_core.api.v1.crm_masking.mask_pii_fields",
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
	# Category Showcase Tile lifecycle → invalidate 60s Redis cache so storefront
	# bento grid sees changes within a minute.
	"Category Showcase Tile": {
		"after_insert": "tradehub_core.api.category_showcase.invalidate_cache",
		"on_update": "tradehub_core.api.category_showcase.invalidate_cache",
		"on_trash": "tradehub_core.api.category_showcase.invalidate_cache",
	},
	# Category Showcase Settings singleton → also invalidate when toggled.
	"Category Showcase Settings": {
		"on_update": "tradehub_core.api.category_showcase.invalidate_cache",
	},
	# Hero Slide lifecycle → invalidate 60s Redis cache so storefront hero slider
	# reflects admin edits within the next request.
	"Hero Slide": {
		"after_insert": "tradehub_core.api.hero_slider.invalidate_cache",
		"on_update": "tradehub_core.api.hero_slider.invalidate_cache",
		"on_trash": "tradehub_core.api.hero_slider.invalidate_cache",
	},
	# ECA Rule lifecycle → rule cache invalidation.
	# Dispatcher Redis cache'inden hem aktif rule listesini hem de derlenmiş
	# condition AST'lerini siler. Save/trash sonrası ilk request fresh ister.
	"ECA Rule": {
		"on_update": "tradehub_core.eca.dispatcher.clear_eca_cache",
		"on_trash": "tradehub_core.eca.dispatcher.clear_eca_cache",
		"after_insert": "tradehub_core.eca.dispatcher.clear_eca_cache",
	},
	# Regex Pattern Library lifecycle → pattern cache invalidation.
	# Bulk Import pipeline derlenmiş regex'i cache'liyor; lib değişince düşür.
	"Regex Pattern Library": {
		"on_update": "tradehub_core.bulk_import.regex_lib.clear_pattern_cache",
		"on_trash": "tradehub_core.bulk_import.regex_lib.clear_pattern_cache",
		"after_insert": "tradehub_core.bulk_import.regex_lib.clear_pattern_cache",
	},
	# -------------------------------------------------------------------------
	# FAZ 1.1 — Tenant İzolasyonu (seller-scoped doctype'lar)
	# Her seller-scoped doctype için:
	#   before_insert → seller_profile autoset + cross-seller koruma
	#   validate      → mevcut kaydın seller_profile değiştirilmesini engelle
	# Detay: tradehub_core/utils/tenant.py, docs/yetki/01-karar-dosyasi.md
	# Listing/Order/Seller Review yukarıda kendi blokları içinde halloldu.
	# -------------------------------------------------------------------------
	"Seller Balance": {
		"before_insert": "tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
		"validate": "tradehub_core.utils.tenant.validate_seller_isolation_on_save",
	},
	"KYB Verification": {
		"before_insert": "tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
		"validate": "tradehub_core.utils.tenant.validate_seller_isolation_on_save",
	},
	"Seller Inquiry": {
		"before_insert": "tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
		"validate": "tradehub_core.utils.tenant.validate_seller_isolation_on_save",
	},
	"Seller Category": {
		"before_insert": "tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
		"validate": "tradehub_core.utils.tenant.validate_seller_isolation_on_save",
	},
	"Seller Gallery Image": {
		"before_insert": "tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
		"validate": "tradehub_core.utils.tenant.validate_seller_isolation_on_save",
	},
	"Listing Question": {
		"before_insert": "tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
		"validate": "tradehub_core.utils.tenant.validate_seller_isolation_on_save",
	},
	"Order Dispute": {
		"before_insert": "tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
		"validate": "tradehub_core.utils.tenant.validate_seller_isolation_on_save",
	},
	"Trusted Reviewer Invitation": {
		"before_insert": "tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
		"validate": "tradehub_core.utils.tenant.validate_seller_isolation_on_save",
	},
	# Listing Review / Review Helpful Vote / Review Abuse Report — tenant isolation
	# hook'ları yukarıdaki review pipeline tanımlarına merge edildi (duplicate dict
	# key'leri Python'da overwrite yapardı).
	# -------------------------------------------------------------------------
	# FAZ 1.2 — Entitlement cache invalidation
	# Plan veya Store Subscription değişikliğinde ilgili store'ların
	# entitlement cache'i temizlenmeli.
	# -------------------------------------------------------------------------
	"Store Subscription": {
		"on_update": "tradehub_core.entitlement.sync.on_store_subscription_update",
		"after_insert": "tradehub_core.entitlement.sync.on_store_subscription_update",
	},
	"Subscription Plan": {
		"on_update": "tradehub_core.entitlement.sync.on_subscription_plan_update",
	},
	# -------------------------------------------------------------------------
	# FAZ 1.4 — Audit: User rol/profile değişimi → Role Change Log
	# -------------------------------------------------------------------------
	"User": {
		"after_insert": "tradehub_core.services.tuple_sync.on_user_insert",
		"on_update": [
			"tradehub_core.audit.user_hooks.on_user_update",
			# FAZ 2.3 — Rol/tenant değişimi sonrası ReBAC tuple sync
			"tradehub_core.services.tuple_sync.on_user_update",
			# Sprint 6 — role_profile_name değişimi → capability cache flush
			"tradehub_core.utils.permission_resolver.on_user_role_change",
			# 2026-06-15 — role-profile sync "Verified Seller"ı silmiş olabilir;
			# KYB Verified ise rolü doğrudan yeniden garanti et (kalkan).
			"tradehub_core.utils.verified_seller.reassert_verified_seller_on_user_save",
		],
		"on_trash": "tradehub_core.services.tuple_sync.on_user_trash",
	},
	# Sprint 6 — TH Capability Registry / Grant değişimi → tüm capability cache flush
	"TH Capability Registry": {
		"on_update": "tradehub_core.utils.permission_resolver.on_capability_registry_change",
		"after_delete": "tradehub_core.utils.permission_resolver.on_capability_registry_change",
	},
	"TH Capability Grant": {
		"after_insert": "tradehub_core.utils.permission_resolver.on_capability_grant_change",
		"on_update": "tradehub_core.utils.permission_resolver.on_capability_grant_change",
		"after_delete": "tradehub_core.utils.permission_resolver.on_capability_grant_change",
	},
	"TH Module Registry": {
		"on_update": "tradehub_core.utils.permission_resolver.on_module_registry_change",
		"after_delete": "tradehub_core.utils.permission_resolver.on_module_registry_change",
	},
	"TH Module Policy": {
		"after_insert": "tradehub_core.utils.permission_resolver.on_module_policy_change",
		"on_update": "tradehub_core.utils.permission_resolver.on_module_policy_change",
		"after_delete": "tradehub_core.utils.permission_resolver.on_module_policy_change",
	},
	# -------------------------------------------------------------------------
	# Lojistik modül — Shipment lifecycle (TUR-102 iskelet)
	# -------------------------------------------------------------------------
	"Logistics Settings": {
		"on_update": "tradehub_core.logistics.cache.invalidate_logistics_dashboard",
	},
	# Lojistik Faz 3 — Carrier Account tenant izolasyonu (LOG-027/LOG-028).
	# Proje konvansiyonu: before_insert (autoset + cross-tenant koruma) +
	# validate (seller_profile değişim kilidi) çift hook.
	"Carrier Account": {
		"before_insert": "tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
		"validate": "tradehub_core.utils.tenant.validate_seller_isolation_on_save",
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
	# Bulk Import + ECA + Regex + Template Profile seller isolation.
	"Bulk Import Job": "tradehub_core.permissions.bulk_import_job_query_conditions",
	"ECA Rule": "tradehub_core.permissions.eca_rule_query_conditions",
	"ECA Rule Log": "tradehub_core.permissions.eca_rule_log_query_conditions",
	"Regex Pattern Library": "tradehub_core.permissions.regex_pattern_library_query_conditions",
	"Seller Value Mapping": "tradehub_core.permissions.seller_value_mapping_query_conditions",
	"Seller Template Profile": "tradehub_core.permissions.seller_template_profile_query_conditions",
	# FAZ 2/3 — ReBAC/Audit DocType izolasyonu
	"Order Approval": "tradehub_core.permissions.order_approval_query_conditions",
	"Approval Rule": "tradehub_core.permissions.approval_rule_query_conditions",
	"Cost Center": "tradehub_core.permissions.cost_center_query_conditions",
	"Owner Transfer Request": "tradehub_core.permissions.owner_transfer_request_query_conditions",
	"Role Delegation": "tradehub_core.permissions.role_delegation_query_conditions",
	"Authorization Decision Log": "tradehub_core.permissions.authorization_decision_log_query_conditions",
	"Role Change Log": "tradehub_core.permissions.role_change_log_query_conditions",
	"Authorization Anomaly Alert": "tradehub_core.permissions.authorization_anomaly_alert_query_conditions",
	"Authorization Anomaly Rule": "tradehub_core.permissions.authorization_anomaly_rule_query_conditions",
	"Permission Override Log": "tradehub_core.permissions.permission_override_log_query_conditions",
	"PII Field Policy": "tradehub_core.permissions.pii_field_policy_query_conditions",
	# Saha pazarlama hakediş — saha elemanı yalnız kendi (agent) kayıtlarını görür.
	"Field Commission": "tradehub_core.permissions.field_commission_query_conditions",
	# H14 fix — abonelik tenant izolasyonu (seller yalnız kendi mağaza aboneliği).
	"Store Subscription": "tradehub_core.permissions.store_subscription_query_conditions",
	# Satıcı Doğrulama — satıcı yalnız kendi başvurularını görür.
	"Seller Verification": "tradehub_core.permissions.seller_verification_query_conditions",
	# Lojistik modül (TUR-102 iskelet)
	"Logistics Settings": "tradehub_core.logistics.permissions.logistics_settings_query_conditions",
	# Lojistik Faz 3 — Carrier Account tenant izolasyonu (LOG-028)
	"Carrier Account": "tradehub_core.logistics.permissions.carrier_account_query_conditions",
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
	"Seller Certification": "tradehub_core.permissions.seller_certification_has_permission",
	"Listing Certification": "tradehub_core.permissions.listing_certification_has_permission",
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
	# Bulk Import + ECA + Regex + Template Profile per-doc kontrolleri.
	"Bulk Import Job": "tradehub_core.permissions.bulk_import_job_has_permission",
	"ECA Rule": "tradehub_core.permissions.eca_rule_has_permission",
	"Regex Pattern Library": "tradehub_core.permissions.regex_pattern_library_has_permission",
	"Seller Value Mapping": "tradehub_core.permissions.seller_value_mapping_has_permission",
	"Seller Template Profile": "tradehub_core.permissions.seller_template_profile_has_permission",
	# FAZ 2/3 — ReBAC/Audit DocType izolasyonu (per-doc)
	"Order Approval": "tradehub_core.permissions.order_approval_has_permission",
	"Approval Rule": "tradehub_core.permissions.approval_rule_has_permission",
	"Cost Center": "tradehub_core.permissions.cost_center_has_permission",
	"Owner Transfer Request": "tradehub_core.permissions.owner_transfer_request_has_permission",
	"Role Delegation": "tradehub_core.permissions.role_delegation_has_permission",
	"Authorization Decision Log": "tradehub_core.permissions.authorization_decision_log_has_permission",
	"Role Change Log": "tradehub_core.permissions.role_change_log_has_permission",
	"Authorization Anomaly Alert": "tradehub_core.permissions.authorization_anomaly_alert_has_permission",
	"Authorization Anomaly Rule": "tradehub_core.permissions.authorization_anomaly_rule_has_permission",
	"Permission Override Log": "tradehub_core.permissions.permission_override_log_has_permission",
	"PII Field Policy": "tradehub_core.permissions.pii_field_policy_has_permission",
	# Seller Owner/Co-Owner kendi sub-user'ının Notification Settings'ine erişebilsin
	# (sub-user pasifleştir/aktive et akışı User.on_update → toggle_notifications içinde tetiklenir).
	"Notification Settings": "tradehub_core.permissions.notification_settings_has_permission",
	# Saha pazarlama hakediş — saha elemanı yalnız kendi kaydına read/report.
	"Field Commission": "tradehub_core.permissions.field_commission_has_permission",
	# H14 fix — abonelik per-doc: seller kendi mağaza aboneliğini okur, yazma admin-only.
	"Store Subscription": "tradehub_core.permissions.store_subscription_has_permission",
	# Satıcı Doğrulama — per-doc: satıcı yalnız kendi başvurusunu görür.
	"Seller Verification": "tradehub_core.permissions.seller_verification_has_permission",
	# Lojistik modül (TUR-102 iskelet)
	"Logistics Settings": "tradehub_core.logistics.permissions.logistics_settings_has_permission",
	# Lojistik Faz 3 — Carrier Account tenant izolasyonu (LOG-028)
	"Carrier Account": "tradehub_core.logistics.permissions.carrier_account_has_permission",
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

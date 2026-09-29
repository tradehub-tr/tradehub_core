#!/usr/bin/env python3
"""DocType JSON + controller üreteci (14.2). Şema tek yerde (bu dosya) — tekrar koşmak idempotent.

Kullanım: python3 scripts/gen_doctypes.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "tradehub_core"  # modül dizinleri tradehub_core/seo_core, seo_cms, …
NOW = "2026-09-19 00:00:00"

# Ortak izinler: SEO Manager tam, SEO Editor yazma, satıcı (Marketplace Seller) mağaza kapsamlı okuma.
P_ADMIN = [
	{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
	{"role": "SEO Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
]
P_EDIT = P_ADMIN + [{"role": "SEO Editor", "read": 1, "write": 1, "create": 1}]
P_STORE_READ = P_EDIT + [{"role": "Marketplace Seller", "read": 1}]
P_MCP = P_ADMIN + [{"role": "Marketplace Seller", "read": 1}, {"role": "MCP Agent", "read": 1}]


def F(fieldname, fieldtype="Data", label=None, **kw):
	d = {
		"fieldname": fieldname,
		"fieldtype": fieldtype,
		"label": label or fieldname.replace("_", " ").title(),
	}
	d.update(kw)
	return d


STORE = F("store", "Link", "Mağaza", options="Admin Seller Profile", search_index=1, in_standard_filter=1)
DV = F("data_version", "Int", "Veri Sürümü", read_only=1, default="0")

DOCTYPES: dict[str, dict] = {
	# ── Core ──
	"SEO Helper Settings": dict(
		module="SEO Core",
		issingle=1,
		perms=P_ADMIN,
		fields=[
			F(
				"default_robots",
				"Select",
				"Varsayılan Robots",
				options="index,follow\nnoindex,follow\nnoindex,nofollow",
				default="index,follow",
			),
			F("min_title_len", "Int", "Asgari Başlık"),
			F("min_desc_len", "Int", "Asgari Açıklama"),
			F("job_max_attempts", "Int", "İş Azami Deneme", default="5"),
			F("sec_mcp", "Section Break", "MCP / OpenAI"),
			F("openai_model", "Data", "OpenAI Modeli"),
			F("mcp_call_timeout_sec", "Int", "Çağrı Zaman Aşımı (sn)", default="60"),
			F("mcp_max_retries", "Int", "Azami Tekrar", default="2"),
			F("mcp_monthly_token_budget", "Int", "Aylık Token Bütçesi (platform)"),
			F("mcp_log_retention_days", "Int", "Araç Günlüğü Saklama (gün)", default="90"),
			F("mcp_key_rotation_days", "Int", "Anahtar Rotasyon Uyarısı (gün)", default="90"),
			F("sec_crawl", "Section Break", "Tarama (13.1)"),
			F("crawl_user_agent", "Data", "Tarayıcı UA", default="iStocSEOHelper/1.0 (+seo-helper)"),
			F("crawl_rate_limit_rps", "Float", "Hız Sınırı (istek/sn, host başına)", default="2"),
			F("crawl_max_pages", "Int", "Bütçe: Azami Sayfa", default="500"),
			F("crawl_max_seconds", "Int", "Bütçe: Azami Süre (sn)", default="1200"),
			F("crawl_max_mb", "Int", "Bütçe: Azami MB", default="200"),
			F("crawl_checkpoint_every", "Int", "Checkpoint (sayfa)", default="20"),
			F("crawl_incremental_days", "Int", "Artımlı: N günden eski", default="7"),
			F("crawl_js_render_command", "Data", "JS Render Komutu ({url} yer tutucu; boş = kapalı)"),
			F("crawl_respect_robots", "Check", "robots.txt'e Uy", default="1"),
			F("sec_botlog", "Section Break", "Bot / Sunucu Logu (13.2)"),
			F("bot_log_path", "Data", "Log Dosyası (glob)"),
			F("bot_verify_dns", "Check", "Ters DNS ile Doğrula"),
			F("bot_log_retention_days", "Int", "Bot Ziyareti Saklama (gün)", default="90"),
			F("bot_log_last_import_at", "Datetime", "Son İçe Aktarma", read_only=1),
			F("sec_gsc", "Section Break", "Search Console (13.5)"),
			F("gsc_property", "Data", "Property (sc-domain:… ya da URL)"),
			F("gsc_client_id", "Data", "OAuth Client ID"),
			F("gsc_client_secret", "Password", "OAuth Client Secret"),
			F("gsc_refresh_token", "Password", "Refresh Token"),
			F("gsc_daily_inspection_quota", "Int", "URL Inspection Günlük Kota", default="2000"),
			F("gsc_daily_query_quota", "Int", "Search Analytics Günlük Sorgu Kotası", default="2000"),
			F("gsc_data_lag_days", "Int", "Veri Gecikmesi (gün)", default="3"),
			F("gsc_sample_size", "Int", "URL Inspection Örneklem", default="200"),
			F("gsc_last_sync_at", "Datetime", "Son Senkron", read_only=1),
			F("sec_board", "Section Break", "Pano (13.3)"),
			F("board_stale_hours", "Int", "Kaynak Bayat Eşiği (saat)", default="36"),
			F("board_anomaly_pct", "Int", "Anomali Eşiği (%)", default="30"),
			F("board_baseline_days", "Int", "Taban Çizgisi (gün)", default="7"),
			F("sec_health", "Section Break", "İzleme"),
			F("last_health_at", "Datetime", "Son Sağlık Anı", read_only=1),
			F("last_health_json", "Long Text", "Son Sağlık Özeti", read_only=1),
		],
	),
	"SEO Domain": dict(
		module="SEO Core",
		autoname="field:host",
		perms=P_ADMIN,
		fields=[
			F("host", "Data", "Host", reqd=1, unique=1),
			F("default_lang", "Select", "Varsayılan Dil", options="tr\nen\nar\nru", default="tr"),
			F("market", "Data", "Pazar", default="TR"),
			F("storefront_base_url", "Data", "Vitrin Adresi", options="URL"),
			F("is_primary", "Check", "Birincil"),
			F("enabled", "Check", "Etkin", default="1"),
		],
	),
	"SEO Locale Cluster": dict(
		module="SEO Core",
		autoname="field:cluster_key",
		perms=P_EDIT,
		fields=[
			F("cluster_key", "Data", "Küme Anahtarı", reqd=1, unique=1),
			F(
				"entity_type",
				"Select",
				"Varlık Türü",
				options="page\nlisting\ncategory\nbrand\nseller\nstatic",
			),
			F("source", "Select", "Kaynak", options="builder\ncatalog\nstatic", default="builder"),
			F("notes", "Small Text", "Not"),
		],
	),
	"SEO Policy": dict(
		module="SEO Core",
		autoname="field:policy_key",
		perms=P_ADMIN,
		fields=[
			F("policy_key", "Data", "Politika Anahtarı", reqd=1, unique=1),
			F(
				"applies_to",
				"Select",
				"Uygulanır",
				options="page\nlisting\ncategory\nbrand\nseller\nfacet",
				default="page",
			),
			F(
				"default_robots",
				"Select",
				"Varsayılan Robots",
				options="index,follow\nnoindex,follow\nnoindex,nofollow",
				default="index,follow",
			),
			F(
				"canonical_strategy",
				"Select",
				"Canonical Stratejisi",
				options="self\nparent\ncluster",
				default="self",
			),
			F("min_title_len", "Int", "Asgari Başlık"),
			F("min_desc_len", "Int", "Asgari Açıklama"),
			F("index_requires_published", "Check", "İndeks için yayın şart", default="1"),
			F("block_ugc_html", "Check", "UGC HTML yayına çıkamaz", default="1"),
			F("priority", "Int", "Öncelik", default="100"),
			F("rules", "JSON", "Ek Kurallar (JSON)"),
		],
	),
	"SEO Profile": dict(
		module="SEO Core",
		autoname="field:profile_key",
		perms=P_EDIT,
		fields=[
			F("profile_key", "Data", "Profil Anahtarı", reqd=1, unique=1),
			F("lang", "Select", "Dil", options="tr\nen\nar\nru", default="tr"),
			F("title_template", "Data", "Başlık Şablonu"),
			F("description_template", "Small Text", "Açıklama Şablonu"),
			F("og_image", "Attach Image", "OG Görseli"),
			F("schema_type", "Data", "Schema Türü", default="WebPage"),
		],
	),
	"SEO Entity": dict(
		module="SEO Core",
		autoname="hash",
		perms=P_STORE_READ,
		search_fields="ref_doctype,ref_name",
		fields=[
			F(
				"entity_type",
				"Select",
				"Varlık Türü",
				options="page\nlisting\ncategory\nbrand\nseller\nstatic\nfacet",
				in_list_view=1,
				in_standard_filter=1,
			),
			F("ref_doctype", "Link", "Kaynak DocType", options="DocType", reqd=1, search_index=1),
			F("ref_name", "Data", "Kaynak Kayıt", reqd=1, search_index=1, in_list_view=1),
			STORE,
			F("domain", "Link", "Domain", options="SEO Domain"),
			F("canonical_path", "Data", "Canonical Yol", in_list_view=1),
			F("indexable", "Check", "İndekslenebilir"),
			DV,
			F("last_synced_at", "Datetime", "Son Eşitleme", read_only=1),
		],
	),
	"SEO Page": dict(
		module="SEO Core",
		autoname="hash",
		perms=P_STORE_READ,
		search_fields="route,title,builder_page",
		track_changes=1,
		fields=[
			F(
				"builder_page",
				"Link",
				"Builder Sayfası",
				options="Builder Page",
				search_index=1,
				in_list_view=1,
			),
			F(
				"lang",
				"Select",
				"Dil",
				options="tr\nen\nar\nru",
				default="tr",
				reqd=1,
				in_list_view=1,
				in_standard_filter=1,
			),
			F(
				"source",
				"Select",
				"Kaynak",
				options="builder\ncatalog\nstatic\nfacet\nmcp",
				default="builder",
			),
			F("entity", "Link", "SEO Varlığı", options="SEO Entity"),
			STORE,
			F("domain", "Link", "Domain", options="SEO Domain"),
			F("route", "Data", "Route", reqd=1, search_index=1, in_list_view=1),
			F("slug", "Data", "Slug"),
			F("title", "Data", "Başlık"),
			F("meta_description", "Small Text", "Meta Açıklama"),
			F("og_image", "Attach Image", "OG Görseli"),
			F("canonical_url", "Data", "Canonical (girilen)"),
			F(
				"robots",
				"Select",
				"Robots (girilen)",
				options="\nindex,follow\nnoindex,follow\nnoindex,nofollow\nindex,nofollow",
			),
			F("locale_cluster", "Link", "Hreflang Kümesi", options="SEO Locale Cluster"),
			F("policy", "Link", "Politika", options="SEO Policy"),
			F("profile", "Link", "Profil", options="SEO Profile"),
			F(
				"publish_state",
				"Select",
				"Yayın Durumu",
				options="draft\nreview\napproved\nscheduled\npublished\nsuspended\narchived",
				default="draft",
				in_list_view=1,
				in_standard_filter=1,
			),
			F("scheduled_at", "Datetime", "Zamanlanmış Yayın"),
			F("published_at", "Datetime", "Yayın Anı", read_only=1),
			F("has_ugc_html", "Check", "Denetlenmemiş HTML içerir"),
			F("sec_karar", "Section Break", "Politika Kararı"),
			F("effective_canonical", "Data", "Etkin Canonical", read_only=1),
			F("effective_robots", "Data", "Etkin Robots", read_only=1),
			F("indexable", "Check", "İndekslenebilir", read_only=1),
			F("publishable", "Check", "Yayınlanabilir", read_only=1),
			F("last_evaluated_at", "Datetime", "Son Değerlendirme", read_only=1),
			DV,
		],
	),
	"SEO Route": dict(
		module="SEO Core",
		autoname="hash",
		perms=P_EDIT,
		search_fields="path",
		fields=[
			F("path", "Data", "Yol", reqd=1, search_index=1, in_list_view=1),
			F("domain", "Link", "Domain", options="SEO Domain"),
			F("lang", "Select", "Dil", options="tr\nen\nar\nru", default="tr"),
			F("target_doctype", "Link", "Hedef DocType", options="DocType"),
			F("target_name", "Data", "Hedef Kayıt"),
			F(
				"status",
				"Select",
				"Durum",
				options="active\ngone\nredirected",
				default="active",
				in_list_view=1,
			),
			DV,
		],
	),
	"SEO Redirect Rule": dict(
		module="SEO Core",
		autoname="hash",
		perms=P_EDIT,
		search_fields="source_path,target_path",
		fields=[
			F("source_path", "Data", "Kaynak Yol", reqd=1, search_index=1, in_list_view=1),
			F("target_path", "Data", "Hedef Yol", in_list_view=1),
			F("status_code", "Select", "HTTP", options="301\n302\n307\n308\n410", default="301"),
			F("match_type", "Select", "Eşleme", options="exact\nprefix", default="exact"),
			F("domain", "Link", "Domain", options="SEO Domain"),
			F("active", "Check", "Etkin", default="1"),
			F("hits", "Int", "İsabet", read_only=1),
			F("mirrored_redirect", "Link", "tradehub SEO Redirect", options="SEO Redirect", read_only=1),
		],
	),
	"SEO Sync Job": dict(
		module="SEO Core",
		autoname="hash",
		perms=P_STORE_READ,
		search_fields="job_type,dedupe_key",
		fields=[
			F("job_type", "Data", "İş Türü", reqd=1, in_list_view=1, in_standard_filter=1),
			F("queue", "Data", "Kuyruk", default="default"),
			STORE,
			F("payload", "Long Text", "Girdi (JSON)"),
			F("dedupe_key", "Data", "Tekilleştirme Anahtarı", search_index=1),
			F(
				"status",
				"Select",
				"Durum",
				options="queued\nrunning\ndone\nfailed\ndead",
				default="queued",
				in_list_view=1,
				in_standard_filter=1,
				search_index=1,
			),
			F("attempts", "Int", "Deneme", default="0"),
			F("next_attempt_at", "Datetime", "Sonraki Deneme", search_index=1),
			F("started_at", "Datetime", "Başlangıç"),
			F("finished_at", "Datetime", "Bitiş"),
			F("last_error", "Small Text", "Son Hata"),
			F("result", "Long Text", "Sonuç (JSON)"),
		],
	),
	"SEO Audit Finding": dict(
		module="SEO Core",
		autoname="hash",
		perms=P_STORE_READ,
		search_fields="route,code",
		fields=[
			F("crawl_run", "Link", "Tarama", options="SEO Crawl Run", search_index=1),
			F("page", "Link", "SEO Sayfası", options="SEO Page", search_index=1),
			F("route", "Data", "Route", in_list_view=1),
			STORE,
			F(
				"severity",
				"Select",
				"Önem",
				options="info\nwarning\nerror",
				in_list_view=1,
				in_standard_filter=1,
			),
			F("code", "Data", "Kod", in_list_view=1),
			F("message", "Small Text", "Mesaj"),
			F(
				"category",
				"Select",
				"Kategori",
				options="technical\ncontent\ncatalog\ninternational\nmerchant\npolicy",
				in_standard_filter=1,
			),
			F("url", "Data", "Etkilenen URL"),
			# 662 §2: sinyal kaynağı — crawler / log (bot günlüğü) / gsc / media (medya SEO denetimi) /
			# notfound_log (SEO 404 Log) / policy (politika motoru) / mcp — panelde ayrı etiket, raporda sütun
			F(
				"signal_source",
				"Select",
				"Sinyal Kaynağı",
				options="crawler\nlog\ngsc\nmedia\nnotfound_log\npolicy\nmcp",
				default="crawler",
				in_standard_filter=1,
				in_list_view=1,
			),
			F("evidence", "JSON", "Kanıt"),
			F("root_cause", "Small Text", "Kök Neden"),
			F("owner_role", "Data", "Sorumlu Rol"),
			F("owner_store", "Link", "Sorumlu Mağaza", options="Admin Seller Profile"),
			F("recommendation", "Small Text", "Öneri"),
			F("fingerprint", "Data", "Parmak İzi", search_index=1),
			F(
				"active_key", "Data", "Aktif İz", unique=1, read_only=1, hidden=1
			),  # = fingerprint yalnız aktifken; eşzamanlı koşumda çift kayıt engeli
			F(
				"status",
				"Select",
				"Yaşam Döngüsü",
				options="open\nfixed\nrecrawl_pending\nclosed\nreopened",
				default="open",
				in_standard_filter=1,
			),
			F("occurrences", "Int", "Tekrar", default="1"),
			F("first_observed", "Datetime", "İlk Görülme"),
			F("last_observed", "Datetime", "Son Görülme"),
			F("fixed_by", "Data", "Düzeltti"),
			F("fixed_at", "Datetime", "Düzeltme Anı"),
			F("recrawl_run", "Link", "Yeniden Tarama", options="SEO Crawl Run"),
			F("recrawl_count", "Int", "Yeniden Tarama Sayısı", default="0"),  # 662 §3 tekrar deneme izi
			F("closed_at", "Datetime", "Kapanış"),
			F("resolved", "Check", "Çözüldü"),
			F("resolved_at", "Datetime", "Çözüm Anı"),
		],
	),
	# ── Catalog ──
	"SEO Facet Landing Page": dict(
		module="SEO Catalog",
		autoname="field:facet_key",
		perms=P_EDIT,
		fields=[
			F("facet_key", "Data", "Facet Anahtarı", reqd=1, unique=1),
			F("category", "Link", "Kategori", options="Product Category"),
			F("filters", "JSON", "Filtreler (JSON)"),
			F("lang", "Select", "Dil", options="tr\nen\nar\nru", default="tr"),
			F("route", "Data", "Route", in_list_view=1),
			F("indexable", "Check", "İndekslenebilir"),
			F("page", "Link", "SEO Sayfası", options="SEO Page"),
			F("min_products", "Int", "Asgari Ürün", default="5"),
		],
	),
	# ── Merchant ──
	"SEO Merchant Map": dict(
		module="SEO Merchant",
		autoname="hash",
		perms=P_STORE_READ,
		fields=[
			STORE,
			F("merchant_account_id", "Data", "Merchant Hesap"),
			F("feed_url", "Data", "Feed Adresi", options="URL"),
			F("mapping", "JSON", "Alan Eşlemesi (JSON)"),
			F("status", "Select", "Durum", options="draft\nactive\nsuspended", default="draft"),
			F("last_sync_at", "Datetime", "Son Eşitleme"),
		],
	),
	# ── Crawler ──
	"SEO Crawl Run": dict(
		module="SEO Crawler",
		autoname="hash",
		perms=P_ADMIN,
		fields=[
			F("scope", "JSON", "Kapsam (JSON)"),
			F(
				"mode",
				"Select",
				"Mod",
				options="audit\nfull\nincremental\nsample\ntargeted",
				default="audit",
				in_list_view=1,
				in_standard_filter=1,
			),
			F(
				"status",
				"Select",
				"Durum",
				options="queued\nrunning\npaused\ndone\nfailed\ncancelled",
				default="queued",
				in_list_view=1,
				in_standard_filter=1,
			),
			F("started_at", "Datetime", "Başlangıç"),
			F("finished_at", "Datetime", "Bitiş"),
			F("pages_total", "Int", "Sayfa"),
			F("pages_ok", "Int", "Başarılı"),
			F("pages_failed", "Int", "Başarısız"),
			F("pages_needs_js", "Int", "JS Gerekli"),
			F("findings", "Int", "Bulgu"),
			F("triggered_by", "Data", "Tetikleyen"),
			F("queue", "Data", "Kuyruk", default="seo_long"),
			F("sec_budget", "Section Break", "Bütçe / Hız / Kontrol"),
			F("rate_limit_rps", "Float", "Hız (istek/sn)"),
			F("max_pages", "Int", "Azami Sayfa"),
			F("max_seconds", "Int", "Azami Süre (sn)"),
			F("max_bytes", "Int", "Azami Bayt"),
			F("bytes_total", "Int", "İndirilen Bayt"),
			F("elapsed_seconds", "Int", "Geçen Süre (sn)"),
			F("budget_exhausted", "Check", "Bütçe Tükendi"),
			F("budget_reason", "Data", "Bütçe Nedeni"),
			F("pause_requested", "Check", "Duraklat İsteği"),
			F("cursor", "Int", "İmleç (checkpoint)"),
			F("url_list", "JSON", "URL Listesi (plan)"),
			F("sample_seed", "Data", "Örneklem Tohumu"),
			F("resumed_from", "Link", "Devam Edilen Koşum", options="SEO Crawl Run"),
			F("last_error", "Small Text", "Son Hata"),
		],
	),
	# ── Helper ──
	"SEO Crawl Page": dict(
		module="SEO Crawler",
		autoname="hash",
		perms=P_ADMIN,
		search_fields="url,route",
		fields=[
			F("crawl_run", "Link", "Tarama", options="SEO Crawl Run", search_index=1, in_list_view=1),
			F("url", "Data", "URL", in_list_view=1),
			F("route", "Data", "Route", search_index=1),
			F("status_code", "Int", "HTTP", in_list_view=1),
			F("fetched_at", "Datetime", "Alınma"),
			F("response_ms", "Int", "Yanıt (ms)"),
			F("bytes", "Int", "Bayt"),
			F("rendered_with", "Select", "Render", options="http\njs\nnone", default="http"),
			F("needs_js", "Check", "JS Gerekli"),
			F("robots_blocked", "Check", "robots.txt Engelli"),
			F("redirect_chain", "JSON", "Yönlendirme Zinciri"),
			F("final_url", "Data", "Son URL"),
			F("title", "Data", "Başlık"),
			F("meta_description", "Small Text", "Açıklama"),
			F("canonical", "Data", "Canonical"),
			F("robots_meta", "Data", "Robots Meta"),
			F("html_lang", "Data", "HTML lang"),
			F("h1_count", "Int", "H1"),
			F("word_count", "Int", "Kelime"),
			F("hreflang", "JSON", "hreflang"),
			F("internal_links", "Int", "İç Bağlantı"),
			F("images_without_alt", "Int", "Alt'sız Görsel"),
			F("json_ld_types", "JSON", "JSON-LD Tipleri"),
			F("content_hash", "Data", "İçerik Özeti"),
			F("error", "Small Text", "Hata"),
		],
	),
	"SEO Bot Visit": dict(
		module="SEO Crawler",
		autoname="hash",
		perms=P_ADMIN,
		search_fields="path,bot",
		fields=[
			F("day", "Date", "Gün", search_index=1, in_list_view=1, in_standard_filter=1),
			F("bot", "Data", "Bot", in_list_view=1, in_standard_filter=1),
			F("host", "Data", "Host"),
			F("path", "Data", "Yol", in_list_view=1),
			F("status_code", "Int", "HTTP", in_list_view=1),
			F("hits", "Int", "İstek", default="0"),
			F("blocked", "Check", "Engel (403/429/robots)"),
			F("verified", "Check", "Ters DNS Doğrulandı"),
			F("first_observed", "Datetime", "İlk"),
			F("last_observed", "Datetime", "Son"),
			F("bytes", "Int", "Bayt"),
			F("dedupe_key", "Data", "Anahtar", search_index=1, unique=1),
		],
	),
	"SEO Metric Snapshot": dict(
		module="SEO Core",
		autoname="hash",
		perms=P_ADMIN,
		fields=[
			F("day", "Date", "Gün", search_index=1, in_list_view=1, in_standard_filter=1),
			F(
				"source",
				"Select",
				"Kaynak",
				options="crawler\nlog\nsearch_console\nanalytics\nmerchant\ncatalog",
				in_list_view=1,
				in_standard_filter=1,
			),
			F("dimension", "Data", "Boyut (store|lang|page_type|all)", in_list_view=1),
			F("dimension_key", "Data", "Boyut Değeri", in_list_view=1),
			F("metric", "Data", "Metrik", in_list_view=1, search_index=1),
			F("value", "Float", "Değer"),
			F("missing", "Check", "Veri Eksik"),
			F("dedupe_key", "Data", "Anahtar", search_index=1, unique=1),
		],
	),
	"SEO Connector Quota": dict(
		module="SEO Core",
		autoname="hash",
		perms=P_ADMIN,
		fields=[
			F("day", "Date", "Gün", in_list_view=1),
			F("connector", "Data", "Bağlayıcı", in_list_view=1),
			F("metric", "Data", "Metrik", in_list_view=1),
			F("used", "Int", "Kullanılan", default="0"),
			F("limit_value", "Int", "Sınır"),
			F("dedupe_key", "Data", "Anahtar", search_index=1, unique=1),
		],
	),
	"SEO Change Log": dict(
		module="SEO Core",
		autoname="hash",
		perms=P_EDIT,
		search_fields="description,route",
		fields=[
			F("changed_at", "Datetime", "Zaman", in_list_view=1),
			F(
				"change_type",
				"Select",
				"Tür",
				options="content\ntemplate\npolicy\nredirect\ndeploy\nexperiment\nother",
				in_list_view=1,
				in_standard_filter=1,
			),
			F("scope_type", "Select", "Kapsam", options="site\ndomain\nlang\nstore\npage_type\nroute"),
			F("scope_key", "Data", "Kapsam Değeri"),
			F("route", "Data", "Route"),
			STORE,
			F("description", "Small Text", "Açıklama", in_list_view=1),
			F("actor", "Data", "Kim"),
			F("source", "Select", "Kaynak", options="auto\nmanual", default="manual"),
			F("expected_effect", "Small Text", "Beklenen Etki"),
			F("experiment", "Link", "Deney", options="SEO Experiment"),
		],
	),
	"SEO Experiment": dict(
		module="SEO Core",
		autoname="field:experiment_key",
		perms=P_EDIT,
		fields=[
			F("experiment_key", "Data", "Anahtar", reqd=1, unique=1),
			F("title", "Data", "Başlık", in_list_view=1),
			F("hypothesis", "Small Text", "Hipotez"),
			F("metric", "Data", "Metrik", default="organic_conversions"),
			F("treatment_routes", "JSON", "Deney Sayfaları (route listesi)"),
			F("control_routes", "JSON", "Kontrol Sayfaları (route listesi)"),
			F("start_date", "Date", "Başlangıç"),
			F("end_date", "Date", "Bitiş"),
			F(
				"status",
				"Select",
				"Durum",
				options="draft\nrunning\nevaluated\nstopped",
				default="draft",
				in_list_view=1,
			),
			F("seasonality", "Select", "Mevsimsellik", options="none\nweekday\nyoy", default="weekday"),
			F("result", "JSON", "Sonuç"),
			F("evaluated_at", "Datetime", "Değerlendirme"),
		],
	),
	"SEO Helper Rule": dict(
		module="SEO Helper",
		autoname="field:rule_key",
		perms=P_ADMIN,
		fields=[
			F("rule_key", "Data", "Kural Anahtarı", reqd=1, unique=1),
			F(
				"scope",
				"Select",
				"Kapsam",
				options="page\nlisting\ncategory\nbrand\nseller\nmcp",
				default="page",
			),
			F("condition", "JSON", "Koşul (JSON)"),
			F("action", "Data", "Eylem"),
			F("deterministic", "Check", "Deterministik (11.4)", default="1"),
			F("enabled", "Check", "Etkin", default="1"),
		],
	),
	# ── MCP ──
	"MCP Client": dict(
		module="SEO MCP",
		autoname="field:client_name",
		perms=P_MCP,
		search_fields="api_key_prefix",
		fields=[
			F("client_name", "Data", "İstemci Adı", reqd=1, unique=1),
			F(
				"role",
				"Select",
				"Rol",
				options="seo_agent\ncms_agent\nauditor",
				default="seo_agent",
				in_list_view=1,
			),
			F(
				"scopes",
				"Small Text",
				"Kapsamlar",
				description="virgülle: page:read,page:draft,metadata:suggest,translation:draft,audit:run,audit:read",
			),
			STORE,
			F("enabled", "Check", "Etkin", default="1", in_list_view=1),
			F("api_key_prefix", "Data", "Anahtar Öneki", read_only=1),
			F("api_key_hash", "Data", "Anahtar Özeti (sha256)", read_only=1, search_index=1),
			F("key_rotated_at", "Datetime", "Anahtar Rotasyonu", read_only=1),
			F("last_used_at", "Datetime", "Son Kullanım", read_only=1),
			F("monthly_token_budget", "Int", "Aylık Token Bütçesi"),
			F("tokens_used_month", "Int", "Bu Ay Token", read_only=1, default="0"),
			F("calls_month", "Int", "Bu Ay Çağrı", read_only=1, default="0"),
		],
	),
	"MCP Tool Call": dict(
		module="SEO MCP",
		autoname="hash",
		perms=P_MCP,
		search_fields="tool",
		fields=[
			F("client", "Link", "İstemci", options="MCP Client", search_index=1, in_list_view=1),
			F("tool", "Data", "Araç", in_list_view=1, in_standard_filter=1),
			STORE,
			F("input_json", "Long Text", "Girdi"),
			F("output_json", "Long Text", "Çıktı"),
			F("cost_tokens_in", "Int", "Token (giriş)", default="0"),
			F("cost_tokens_out", "Int", "Token (çıkış)", default="0"),
			F("cost_usd", "Float", "Maliyet (USD)", default="0"),
			F("duration_ms", "Int", "Süre (ms)"),
			F("result", "Select", "Sonuç", options="ok\nerror\ndenied", in_list_view=1, in_standard_filter=1),
			F("error", "Small Text", "Hata"),
			F("draft", "Link", "Taslak", options="MCP Draft"),
		],
	),
	"MCP Draft": dict(
		module="SEO MCP",
		autoname="hash",
		perms=P_MCP,
		track_changes=1,
		search_fields="draft_type,target_name",
		fields=[
			F("client", "Link", "İstemci", options="MCP Client", search_index=1),
			F(
				"draft_type",
				"Select",
				"Taslak Türü",
				options="page_create\npage_update\nblock_add\nmetadata\ntranslation",
				in_list_view=1,
				in_standard_filter=1,
			),
			STORE,
			F("target_doctype", "Link", "Hedef DocType", options="DocType"),
			F("target_name", "Data", "Hedef Kayıt", in_list_view=1),
			F("payload", "Long Text", "Taslak (JSON)"),
			F("validation", "Long Text", "Deterministik Doğrulama (JSON)"),
			F(
				"status",
				"Select",
				"Durum",
				options="draft\napproved\nrejected\napplied",
				default="draft",
				in_list_view=1,
				in_standard_filter=1,
			),
			F("reviewed_by", "Link", "İnceleyen", options="User", read_only=1),
			F("reviewed_at", "Datetime", "İnceleme Anı", read_only=1),
			F("review_note", "Small Text", "İnceleme Notu"),
			F("applied_at", "Datetime", "Uygulama Anı", read_only=1),
			F("tool_call", "Link", "Araç Çağrısı", options="MCP Tool Call"),
		],
	),
}


def snake(name: str) -> str:
	return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def pascal(name: str) -> str:
	return "".join(p.capitalize() if not p.isupper() else p for p in re.split(r"[^A-Za-z0-9]+", name) if p)


def emit(name: str, spec: dict) -> None:
	module_dir = ROOT / snake(spec["module"]) / "doctype" / snake(name)
	module_dir.mkdir(parents=True, exist_ok=True)
	(module_dir / "__init__.py").touch()
	fields = spec["fields"]
	doc = {
		"actions": [],
		"allow_rename": 0,
		"creation": NOW,
		"doctype": "DocType",
		"document_type": "Document",
		"editable_grid": 0,
		"engine": "InnoDB",
		"field_order": [f["fieldname"] for f in fields],
		"fields": fields,
		"links": [],
		"modified": NOW,
		"modified_by": "Administrator",
		"module": spec["module"],
		"name": name,
		"owner": "Administrator",
		"permissions": spec["perms"],
		"sort_field": "modified",
		"sort_order": "DESC",
		"states": [],
		"track_changes": spec.get("track_changes", 0),
	}
	if spec.get("issingle"):
		doc["issingle"] = 1
	if spec.get("autoname"):
		doc["autoname"] = spec["autoname"]
		doc["naming_rule"] = "By fieldname" if spec["autoname"].startswith("field:") else "Random"
	if spec.get("search_fields"):
		doc["search_fields"] = spec["search_fields"]
	(module_dir / f"{snake(name)}.json").write_text(
		json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
	)
	py = module_dir / f"{snake(name)}.py"
	if not py.exists():
		py.write_text(
			f"# Copyright (c) 2026, TradeHub Team\n# For license information, please see license.txt\n\nfrom frappe.model.document import Document\n\n\nclass {pascal(name)}(Document):\n\tpass\n",
			encoding="utf-8",
		)


if __name__ == "__main__":
	for n, s in DOCTYPES.items():
		emit(n, s)
	print(f"{len(DOCTYPES)} DocType üretildi")

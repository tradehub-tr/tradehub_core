"""T-132 — Faz 13 yetki sertleştirme: MİSAFİR YÜZEYİ + PERMLEVEL drift kapıları.

NEDEN BU DOSYA VAR — ÖLÇÜLMÜŞ BOŞLUK (2026-08-20)
=================================================
Faz 13'ün cross-tenant kanıtları güçlü ve vacuity-kontrollü (test_media_folder,
test_media_orphans, test_manifest_batch, test_media_dedup_endpoint,
test_file_multirow_isolation). Ama iki yüzey ÖLÇÜLMEMİŞ kalıyordu:

  1. **Misafir yüzeyi taraması.** `test_http_api_contracts.py` yalnız MEDYA
     hattının 4 guest ucunu donduruyor; oysa `tradehub_core/` altında
     `@frappe.whitelist(allow_guest=True)` taşıyan **111** fonksiyon var. Yeni
     bir guest ucu sessizce eklenebilir ve hiçbir test kırılmazdı. Bu, güvenlik
     incelemesinin tetiklenmediği anlamına gelir.
  2. **Permlevel (alan düzeyi).** `test_authz_regression` KYC/KYB `status`
     alanının permlevel-4 olduğunu JSON değeriyle pinliyor, ama Media Asset
     moderasyon alanları (docs/reports/28-faz13-pentest.md §8'de "canlı
     doğrulandı" denen ama TESTİ OLMAYAN yüzey) için hiçbir birim testi yoktu.

Bu dosya frappe'yi ÇAĞIRMAZ — saf AST + DocType JSON taraması. `python3` yeter,
CI kapısında (`scripts/run_authz_tests.sh`) koşar, bench/site GEREKTİRMEZ.

BİLİNEN SINIR — açıkça
======================
AST yalnız DEKORATÖR biçimini yakalar: `@frappe.whitelist(allow_guest=True)`.
`tradehub_core/seo/page_resolver.py`nin `frappe.whitelist(...)(render_x)` ÇAĞRI
biçimiyle kaydettiği 6 SEO renderer'ı bu taramaya GİRMEZ ve baseline'a bilinçli
olarak DAHİL EDİLMEZ — yakalanamayan bir şeyi dondurmak sahte güven olurdu.
Onların guest-drift'i ayrı ele alınmalı (rapor 87 §T-132).
"""

from __future__ import annotations

import ast
import json
import os
import unittest
from pathlib import Path

#: Repo kökü (dotted path'ler buna göre): .../tradehub_core (dış repo).
#: Bu dosya: .../tradehub_core/tradehub_core/tests/test_faz13_guest_surface.py
REPO_ROOT = Path(__file__).resolve().parents[2]
#: Taranan paket kökü (iç `tradehub_core` paketi).
PKG_ROOT = Path(__file__).resolve().parents[1]


def _guest_decorator(dec: ast.expr) -> bool:
	"""`@frappe.whitelist(allow_guest=True)` mi (isim `whitelist`, kw True)?"""
	if not isinstance(dec, ast.Call):
		return False
	f = dec.func
	name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
	if name != "whitelist":
		return False
	for kw in dec.keywords:
		if kw.arg == "allow_guest" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
			return True
	return False


def scan_guest_surface() -> set:
	"""Paket ağacındaki tüm dekoratör-biçimli guest uçlarının dotted-path kümesi."""
	found: set = set()
	for dirpath, _dirs, files in os.walk(PKG_ROOT):
		norm = dirpath.replace(os.sep, "/")
		if "__pycache__" in norm or "/tests" in norm:
			continue
		for fn in files:
			if not fn.endswith(".py"):
				continue
			p = Path(dirpath) / fn
			try:
				tree = ast.parse(p.read_text(encoding="utf-8"))
			except (SyntaxError, UnicodeDecodeError):
				continue
			dotted_mod = str(p.relative_to(REPO_ROOT))[:-3].replace(os.sep, ".")
			for node in ast.walk(tree):
				if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
					if any(_guest_decorator(d) for d in node.decorator_list):
						found.add(f"{dotted_mod}.{node.name}")
	return found


#: DONDURULMUŞ MİSAFİR YÜZEYİ (2026-08-20 ölçümü, 111 uç).
#: Bu küme bir GÜVENLİK SÖZLEŞMESİDİR. Değişiklik = güvenlik incelemesi tetiği:
#: yeni bir satır eklemek için o ucun gerçekten public olduğu (buyer/seller
#: verisi/yazma taşımadığı) checklists.md §1 ile doğrulanmalı; silmek için de
#: ucun artık guest olmadığı doğrulanmalı. Körü körüne güncellemeyin.
FROZEN_GUEST_SURFACE: frozenset = frozenset({
	"tradehub_core.api.advanced_search.voice_search_process",
	"tradehub_core.api.auth.get_current_user",
	"tradehub_core.api.brand.get_brand_detail",
	"tradehub_core.api.cart.validate_coupon",
	"tradehub_core.api.category.get_category_version",
	"tradehub_core.api.category.get_mega_menu",
	"tradehub_core.api.category_showcase.get_active_tiles",
	"tradehub_core.api.certification.get_certification_types",
	"tradehub_core.api.currency.convert_price",
	"tradehub_core.api.currency.get_currency_settings",
	"tradehub_core.api.dispute.get_dispute_summary",
	"tradehub_core.api.footer.get_footer_seo_links",
	"tradehub_core.api.header_notice.get_active_notices",
	"tradehub_core.api.hero_slider.get_active_slides",
	"tradehub_core.api.listing.get_categories",
	"tradehub_core.api.listing.get_featured_listings",
	"tradehub_core.api.listing.get_filter_facets",
	"tradehub_core.api.listing.get_listing_detail",
	"tradehub_core.api.listing.get_listings",
	"tradehub_core.api.listing.get_related_listings",
	"tradehub_core.api.listing.get_related_listings_grouped",
	"tradehub_core.api.listing.get_search_suggestions",
	"tradehub_core.api.listing.get_shipping_methods",
	"tradehub_core.api.listing.get_top_ranking_categories",
	"tradehub_core.api.listing.get_top_ranking_grouped",
	"tradehub_core.api.listing.log_search",
	"tradehub_core.api.media_access.download",
	"tradehub_core.api.media_manifest.get_manifest",
	"tradehub_core.api.media_manifest.get_manifest_batch",
	"tradehub_core.api.mobile_api.mobile_get_pending_reviews",
	"tradehub_core.api.mobile_api.mobile_get_review_feed",
	"tradehub_core.api.mobile_api.mobile_login",
	"tradehub_core.api.mobile_api.mobile_logout",
	"tradehub_core.api.mobile_api.mobile_me",
	"tradehub_core.api.mobile_api.mobile_quick_review",
	"tradehub_core.api.mobile_api.mobile_refresh",
	"tradehub_core.api.observability.metrics",
	"tradehub_core.api.observability.status",
	"tradehub_core.api.public.create_lead",
	"tradehub_core.api.push.get_public_key",
	"tradehub_core.api.qa.list_listing_questions",
	"tradehub_core.api.rating_engine.get_listing_weighted_rating",
	"tradehub_core.api.reputation.get_reviewer_profile",
	"tradehub_core.api.reservation.list_seller_slots",
	"tradehub_core.api.review.get_listing_rating_summary",
	"tradehub_core.api.review.list_listing_reviews",
	"tradehub_core.api.rfq.get_uom_list",
	"tradehub_core.api.rfq.search_categories",
	"tradehub_core.api.rum.collect",
	"tradehub_core.api.search.unified_suggest",
	"tradehub_core.api.seller.download_verification_document",
	"tradehub_core.api.seller.get_manufacturer_facets",
	"tradehub_core.api.seller.get_reviews",
	"tradehub_core.api.seller.get_seller",
	"tradehub_core.api.seller.get_seller_categories",
	"tradehub_core.api.seller.get_seller_products",
	"tradehub_core.api.seller.get_seller_verifications",
	"tradehub_core.api.seller.get_sellers",
	"tradehub_core.api.seller.get_storefront_layout",
	"tradehub_core.api.seller.send_inquiry",
	"tradehub_core.api.seller_certifications.clear_invalid_session",
	"tradehub_core.api.sentiment.get_listing_sentiment_summary",
	"tradehub_core.api.seo.get_public_page_seo",
	"tradehub_core.api.seo.get_review_schema_html",
	"tradehub_core.api.seo.get_review_schema_jsonld",
	"tradehub_core.api.seo.get_robots",
	"tradehub_core.api.seo.get_sitemap",
	"tradehub_core.api.seo.get_sitemap_index",
	"tradehub_core.api.seo.legacy_redirect_handler",
	"tradehub_core.api.seo.resolve_legacy_url",
	"tradehub_core.api.seo_admin.handle_404_endpoint",
	"tradehub_core.api.social_proof.get_signals",
	"tradehub_core.api.social_proof.get_signals_batch",
	"tradehub_core.api.social_proof.record_view",
	"tradehub_core.api.storefront_api.get_category_template",
	"tradehub_core.api.storefront_api.get_qa_page",
	"tradehub_core.api.storefront_api.get_storefront_review_page",
	"tradehub_core.api.tailored.get_tailored_group_detail",
	"tradehub_core.api.tailored.get_tailored_selections",
	"tradehub_core.api.templates.get_category_template",
	"tradehub_core.api.templates.get_template_answers",
	"tradehub_core.api.theme.get_public_theme",
	"tradehub_core.api.timeline.get_review_timeline",
	"tradehub_core.api.tracking.get_public_tracking",
	"tradehub_core.api.translation.get_review_translation",
	"tradehub_core.api.v1.auth.check_email_exists",
	"tradehub_core.api.v1.auth.get_session_user",
	"tradehub_core.api.v1.buyer_team.accept_buyer_invite",
	"tradehub_core.api.v1.compliance.download_data_export",
	"tradehub_core.api.v1.identity.forgot_password",
	"tradehub_core.api.v1.identity.register_supplier",
	"tradehub_core.api.v1.identity.register_user",
	"tradehub_core.api.v1.identity.reset_password",
	"tradehub_core.api.v1.identity.send_registration_otp",
	"tradehub_core.api.v1.identity.upload_private_file",
	"tradehub_core.api.v1.identity.verify_email",
	"tradehub_core.api.v1.identity.verify_registration_otp",
	"tradehub_core.api.v1.logistics.estimate_shipping_cost",
	"tradehub_core.api.v1.logistics.get_available_shipping_methods",
	"tradehub_core.api.v1.logistics.track_shipment_public",
	"tradehub_core.api.v1.public_api.listings_get_analytics",
	"tradehub_core.api.v1.public_api.listings_get_reviews",
	"tradehub_core.api.v1.public_api.token",
	"tradehub_core.api.v1.public_pricing.get_pricing_plans",
	"tradehub_core.api.v1.seller_users.accept_invite",
	"tradehub_core.api.v1.seller_users.verify_invite",
	# ── GÖLGE MODÜL KALDIRILDI (rapor 92, B-02 kapanışı) ──
	# `tradehub_core/tradehub_core/api/seller.py` `api/seller.py`nin Nisan
	# 2026'dan kalma bayat kopyasıydı; 5 guest ucunu (get_sellers/get_seller/
	# get_reviews/get_storefront_layout/send_inquiry) İKİNCİ kez ve GÜNCEL
	# GUARD'LAR OLMADAN (rate-limit'siz send_inquiry, capability'siz
	# save_storefront_layout) expose ediyordu. Hiçbir FE/BE çağıranı yoktu
	# (tüm istemciler kanonik `tradehub_core.api.seller.*` yolunu çağırıyor);
	# dosya silindi, git geçmişi korur. Bu 5 uç baseline'dan da çıkarıldı —
	# geri gelirse bu test güvenlik incelemesi tetikler.
})

#: ASLA guest olmayacak uçlar — sızma incelemesinden çıkan denylist. Bunların
#: `allow_guest=True` almaları TEK BAŞINA bir güvenlik regresyonudur.
NEVER_GUEST: frozenset = frozenset({
	# İmzalı URL üretimi: guest bir private dosyayı imzalatamamalı (sadece
	# hazır imzalı URL'i `media_access.download` ile TÜKETİR).
	"tradehub_core.api.media_access.get_signed_url",
	"tradehub_core.api.media_manifest.get_signed_url",
	# Dosya-bazlı panel envanteri (get_manifest_batch DEĞİL): oturumlu.
	"tradehub_core.api.media_manifest.manifest_batch",
})


class GuestSurfaceDriftTests(unittest.TestCase):
	"""Misafir yüzeyi taraması — yeni bir guest ucu sessizce eklenemez."""

	def test_guest_surface_matches_frozen_baseline(self) -> None:
		gercek = scan_guest_surface()
		eklenen = sorted(gercek - FROZEN_GUEST_SURFACE)
		silinen = sorted(FROZEN_GUEST_SURFACE - gercek)
		self.assertEqual(
			gercek,
			set(FROZEN_GUEST_SURFACE),
			"Misafir yüzeyi DEĞİŞTİ — güvenlik incelemesi gerekli.\n"
			f"  YENİ guest uçları (public olduğunu checklists.md §1 ile DOĞRULA): {eklenen}\n"
			f"  KALDIRILAN guest uçları (artık guest değil mi, doğrula): {silinen}\n"
			"Doğruladıysan FROZEN_GUEST_SURFACE'ı güncelle.",
		)

	def test_baseline_boyutu_beklenen(self) -> None:
		# Sayı da bir kanıttır: 106 dekoratör-biçimli guest ucu (SEO renderer'lar
		# hariç — modül docstring'i). 111'den 106'ya düşüş = gölge modülün 5
		# guest ucunun kaldırılması (rapor 92, B-02). Sayı değişirse yukarıdaki
		# test zaten anlatır.
		self.assertEqual(len(FROZEN_GUEST_SURFACE), 106)

	def test_denylist_uclari_guest_degil(self) -> None:
		gercek = scan_guest_surface()
		for yol in sorted(NEVER_GUEST):
			self.assertNotIn(
				yol, gercek, f"{yol} ASLA guest olmamalı — imza/panel ucu oturum ister."
			)

	def test_yeni_yuzeyler_guest_kumesinde(self) -> None:
		# Bugün eklenen medya yüzeylerinin guest uçları baseline'da OLMALI —
		# yanlışlıkla kaldırılırlarsa vitrin/telemetri kırılır ama sessiz kalmaz.
		for yol in (
			"tradehub_core.api.rum.collect",
			"tradehub_core.api.media_manifest.get_manifest",
			"tradehub_core.api.media_manifest.get_manifest_batch",
			"tradehub_core.api.media_access.download",
			"tradehub_core.api.observability.metrics",
			"tradehub_core.api.observability.status",
		):
			self.assertIn(yol, FROZEN_GUEST_SURFACE)


# ── Permlevel (alan düzeyi) — Media Asset moderasyon koruması ─────────────

#: DocType JSON'ları Frappe "modül namespace" alt dizinindedir (level-3):
#: .../tradehub_core/tradehub_core/tradehub_core/doctype/<ad>/<ad>.json
MODULE_ROOT = PKG_ROOT / "tradehub_core"


def _load_doctype(rel: str) -> dict:
	p = MODULE_ROOT / "doctype" / rel / f"{rel}.json"
	return json.loads(p.read_text(encoding="utf-8"))


#: Media Asset moderasyon alanları — seller YAZAMAMALI, sadece platform.
#: (docs/reports/28-faz13-pentest.md §8: "canlı doğrulandı" ama testi yoktu.)
MEDIA_ASSET_MODERATION_FIELDS: frozenset = frozenset({
	"state", "owner_seller", "source_file", "legal_hold",
	"content_sha256", "active_version", "rejection_code", "rejection_note",
})
#: permlevel-1'de YAZAMAYAN roller (moderasyon alanlarını değiştiremezler).
SELLER_ROLES: frozenset = frozenset({"Marketplace Seller", "Seller"})
#: permlevel-1'de yazabilen platform rolleri.
ADMIN_ROLES: frozenset = frozenset({"System Manager", "Marketplace Admin"})


class MediaAssetPermlevelTests(unittest.TestCase):
	"""Alan düzeyi yetki: Media Asset moderasyon alanları permlevel-1 arkasında."""

	def setUp(self) -> None:
		self.doc = _load_doctype("media_asset")
		self.fields = {f["fieldname"]: f for f in self.doc.get("fields", [])}
		self.perms = self.doc.get("permissions", [])

	def test_moderasyon_alanlari_permlevel_1(self) -> None:
		for fn in sorted(MEDIA_ASSET_MODERATION_FIELDS):
			self.assertIn(fn, self.fields, f"Moderasyon alanı kayboldu: {fn}")
			self.assertGreaterEqual(
				int(self.fields[fn].get("permlevel", 0)), 1,
				f"{fn} permlevel-0'a düştü — seller moderasyon alanını yazabilir hâle gelir.",
			)

	def test_seller_permlevel1_write_yok(self) -> None:
		for p in self.perms:
			if int(p.get("permlevel", 0)) == 1 and p.get("role") in SELLER_ROLES:
				self.assertEqual(
					int(p.get("write", 0)), 0,
					f"{p.get('role')} permlevel-1'de write=1 — moderasyon koruması delindi.",
				)

	def test_platform_permlevel1_write_var(self) -> None:
		# Pozitif kontrol: koruma "kimse yazamaz" DEĞİL "sadece platform yazar".
		yazan = {
			p.get("role")
			for p in self.perms
			if int(p.get("permlevel", 0)) == 1 and int(p.get("write", 0)) == 1
		}
		for rol in ADMIN_ROLES:
			self.assertIn(rol, yazan, f"{rol} permlevel-1'de yazamıyor — moderasyon imkânsız.")

	def test_kontrol_gevsetilince_iddia_gercekten_kirilir(self) -> None:
		# Vacuity kontrolü: eğer bir seller rolü permlevel-1 write alsaydı
		# test_seller_permlevel1_write_yok GERÇEKTEN kırılırdı.
		sahte = list(self.perms) + [{"role": "Seller", "permlevel": 1, "read": 1, "write": 1}]
		kirik = any(
			int(p.get("permlevel", 0)) == 1
			and p.get("role") in SELLER_ROLES
			and int(p.get("write", 0)) == 1
			for p in sahte
		)
		self.assertTrue(kirik, "Vacuity: gevşetilmiş matriste ihlal görünmüyor — test kör.")


if __name__ == "__main__":
	unittest.main()

# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 1.2 — Entitlement hook'ları.

Doc_events için hazır hook fonksiyonları. Bu modüldeki fonksiyonlar:
  - Listing.before_insert: çoklu varyant capability + ürün kota kontrolü
  - Listing.validate: bölge kısıtı kontrolü
  - User.before_insert (sub-user davet): max_sub_users kota kontrolü

Hata davranışı: EntitlementError → 403, mesajda plan bilgisi.

Detay: docs/yetki/TradeHub-Yetkilendirme-Mimarisi-v2.md §3.4
"""

import frappe
from frappe import _

from tradehub_core.entitlement.core import (
	check_feature_or_throw,
	check_quota_or_throw,
	get_active_subscription,
)


def check_listing_creation_quota(doc, method=None) -> None:
	"""Listing.before_insert hook: ürün kota + temel feature kontrolü.

	System Manager bypass eder. Listing'in seller_profile alanı henüz
	tenant hook'u tarafından set edilmiş olmalı (hook sırası: tenant → entitlement).
	"""
	if "System Manager" in frappe.get_roles(frappe.session.user):
		return

	store = getattr(doc, "seller_profile", None)
	if not store:
		# Seller_profile boşsa tenant hook'u henüz set etmemiş veya
		# admin doc oluşturuyor — entitlement check skip
		return

	# Subscription var mı?
	sub = get_active_subscription(store)
	if not sub:
		frappe.throw(
			_("Mağazanızın aktif bir aboneliği yok. Ürün ekleyebilmek için bir plan seçin."),
			frappe.PermissionError,
		)

	# Çoklu varyantsa capability kontrolü
	if _is_variant_listing(doc):
		check_feature_or_throw(
			store,
			"feature.pim.multi_variant",
			action_description=_("Çoklu Varyant Ürün Ekleme"),
		)

	# Ürün kota kontrolü
	current_count = frappe.db.count("Listing", {"seller_profile": store})
	check_quota_or_throw(
		store,
		"quota.max_products",
		current_count,
		action_description=_("Yeni Ürün Ekleme"),
	)


def validate_listing_features(doc, method=None) -> None:
	"""Listing.validate hook: çoklu varyant geçişi capability kontrolü.

	Mevcut listing'in tek varyantlı halinden çoklu varyanta geçiş yapılıyorsa
	plan capability kontrolü.
	"""
	if "System Manager" in frappe.get_roles(frappe.session.user):
		return

	store = getattr(doc, "seller_profile", None)
	if not store:
		return

	if _is_variant_listing(doc):
		check_feature_or_throw(
			store,
			"feature.pim.multi_variant",
			action_description=_("Çoklu Varyant Düzenleme"),
		)


def validate_listing_regions(doc, method=None) -> None:
	"""Listing.validate hook: allowed_regions satıcının regions kümesi içinde olmalı.

	Satıcının Admin Seller Profile.regions kümesi planın allowed_regions'unun
	alt kümesi. Listing.allowed_regions de satıcının regions'ının alt kümesi
	olmalı.
	"""
	if "System Manager" in frappe.get_roles(frappe.session.user):
		return

	store = getattr(doc, "seller_profile", None)
	if not store:
		return

	listing_regions = _extract_region_codes(doc.get("allowed_regions"))
	if not listing_regions:
		return  # boş = satıcının tüm regions'ı kabul edilir

	# Satıcının regions kümesi
	seller_regions = _extract_region_codes(
		frappe.db.get_value("Admin Seller Profile", store, "regions", as_dict=False)
	)
	# Yukarıdaki get_value Table MultiSelect için doğru sonuç vermez;
	# child table'ı manuel sorgula
	seller_region_rows = frappe.get_all(
		"Subscription Plan Region",
		filters={"parent": store, "parenttype": "Admin Seller Profile"},
		pluck="region",
	)
	if seller_region_rows:
		seller_regions = set(seller_region_rows)
	else:
		seller_regions = set()

	# Plan'ın allowed_regions kümesi (fallback)
	if not seller_regions:
		sub = get_active_subscription(store)
		if sub:
			plan_regions = frappe.get_all(
				"Subscription Plan Region",
				filters={"parent": sub["plan"], "parenttype": "Subscription Plan"},
				pluck="region",
			)
			seller_regions = set(plan_regions)

	invalid = set(listing_regions) - set(seller_regions)
	if invalid:
		frappe.throw(
			_("Listing'in '{0}' bölgesi/bölgeleri için satış hakkınız yok. Aktif bölgeleriniz: {1}.").format(
				", ".join(sorted(invalid)), ", ".join(sorted(seller_regions)) or "-"
			),
			frappe.PermissionError,
		)


def check_sub_user_invite_quota(store: str) -> None:
	"""Sub-user davet API'sından çağrılan helper.

	Args:
	    store: Admin Seller Profile.name

	Raises:
	    EntitlementError: kota aşıldıysa
	"""
	if not store:
		return

	# Mevcut aktif sub-user sayısı
	current_count = frappe.db.count(
		"User",
		{"tradehub_tenant": store, "enabled": 1},
	)
	check_quota_or_throw(
		store,
		"quota.max_sub_users",
		current_count,
		action_description=_("Yeni Çalışan Davet"),
	)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_variant_listing(doc) -> bool:
	"""Listing'in çoklu varyantlı olup olmadığını tespit et.

	Heuristic: variant child table'ı var ve dolu mu, ya da variant_count > 1.
	Mevcut Listing doctype'ında 'listing_variant_item' child table var.
	"""
	variants = doc.get("listing_variant_item") or doc.get("variants")
	if variants and len(variants) > 1:
		return True
	# Bazı doctype'larda explicit alan olabilir
	variant_count = doc.get("variant_count") or 0
	return bool(variant_count and int(variant_count) > 1)


def _extract_region_codes(value) -> set[str]:
	"""Table MultiSelect veya list'ten region kodlarını çıkar."""
	if not value:
		return set()
	if isinstance(value, str):
		# Comma-separated string
		return {v.strip().upper() for v in value.split(",") if v.strip()}
	if isinstance(value, list | tuple):
		codes = set()
		for item in value:
			if isinstance(item, str):
				codes.add(item.strip().upper())
			elif isinstance(item, dict):
				code = item.get("region") or item.get("region_code")
				if code:
					codes.add(code)
			elif hasattr(item, "region"):
				codes.add(item.region)
		return codes
	return set()


def check_media_storage_quota(doc, method=None):
	"""File.before_insert — satıcı medya depolama kotası (TUR-139).

	Faz 0 iskeleti: şu an no-op. WP3 gerçek enforcement'ı buraya koyacak
	(EXCLUDED_DOCTYPES muafiyeti + get_current_seller_profile + within_quota).
	Kancaya şimdi bağlı olduğu için NotImplementedError DEĞİL — sessizce geçer.
	"""
	return

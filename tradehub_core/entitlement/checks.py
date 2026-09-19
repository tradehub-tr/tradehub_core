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
	get_quota_limits,
)
from tradehub_core.media import files, quota_model, upload_policy
from tradehub_core.media.presets import EXCLUDED_DOCTYPES
from tradehub_core.utils.tenant import get_current_seller_profile


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

	Listing'de child table'ın ALAN adı `variant_items` (child doctype adı
	"Listing Variant Item"). MOGEM-665 ölçümü (15 Eyl): eski kod var olmayan
	`listing_variant_item` alanını okuyup her zaman False dönüyor, plan kapısı
	(`feature.pim.multi_variant`) hiç çalışmıyordu.
	"""
	variants = doc.get("variant_items") or doc.get("listing_variant_item") or doc.get("variants")
	if variants and len(variants) > 1:
		return True
	if doc.get("has_variants") and variants:
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


def check_media_storage_quota(doc, method=None) -> None:
	"""File.before_insert — satıcı medya depolama kotası enforcement (TUR-139, WP3).

	Faz 0'daki no-op stub'ın yerini aldı. Muafiyetler (sırayla):
	  - Klasör kayıtları (`is_folder`) — depolama tüketmez.
	  - System Manager / Marketplace Admin — platform yönetimi kısıtlanmaz.
	  - `EXCLUDED_DOCTYPES` (KYB/KYC/Order/Payment Transaction vb.) — bunlar zaten
	    `media.presets`'te "kota dışı" sayılıyor (inventory/usage aynı listeyi
	    kullanıyor); aynı muafiyet burada da geçerli olmalı, aksi hâlde bir
	    belge yükleyen satıcı hiç göremediği bir sayaç yüzünden reddedilir.
	  - Bulk import kanalı (`frappe.flags.in_bulk_import_upload` / `doc.flags.
	    bulk_import_safe`) — `utils.security.reject_unsafe_files` ile aynı iki
	    bayrak kanalı.
	  - Private dosyalar — `media.files.storage_usage` yalnız `is_private=0`
	    dosyaları sayıyor (dedup `file_url` bazında); ÖLÇÜLMEYEN bir metrikle
	    private yüklemeyi reddetmek tutarsız olurdu.
	  - Mağazası çözülemeyen oturum (guest/admin/tenant'sız kullanıcı) — kota
	    kavramı mağazaya bağlı, mağazasız oturum muaf.

	Limit semantiği `entitlement.core.within_quota` ile aynı: `-1` sınırsız,
	plan'da tanımsız (`None`) → WP3 seed patch'i (`v15_9_17_seed_storage_quota`)
	çalıştıysa normalde görülmez; yine de fail-open değil fail-safe: sınır
	yoksa GÖSTERİLMEZ/UYGULANMAZ (yeni yüklemeyi engellemez) — tıpkı
	`media.files._quota()`'nın tanımsız kotayı `None` dönmesi gibi.
	"""
	if getattr(doc, "is_folder", 0):
		return

	if "System Manager" in frappe.get_roles(frappe.session.user):
		return
	if "Marketplace Admin" in frappe.get_roles(frappe.session.user):
		return

	if doc.get("attached_to_doctype") in EXCLUDED_DOCTYPES:
		return

	if getattr(getattr(doc, "flags", None), "bulk_import_safe", False):
		return
	if getattr(frappe.flags, "in_bulk_import_upload", False):
		return

	if doc.get("is_private"):
		return

	store = get_current_seller_profile()
	if not store:
		return

	limit_mb = get_quota_limits(store).get("quota.max_storage_mb")
	quota_mode, limit_bytes = quota_model.resolve_limit_mb(limit_mb)
	if quota_mode == quota_model.MODE_UNCONFIGURED:
		return  # plan'da tanımsız — seed patch atlandıysa bile yükleme reddedilmez
	if quota_mode == quota_model.MODE_UNLIMITED:
		return  # sınırsız

	incoming_bytes = int(doc.get("file_size") or len(doc.get("content") or b"") or 0)
	current_bytes = files.storage_usage(store)["bytes"]

	if quota_model.would_exceed(current_bytes, incoming_bytes, limit_bytes):
		# Ret, medya yükleme sözleşmesinden (TUR-123) geçiyor: mesajın sonuna
		# `[upload_quota_exceeded]` markörü konur ve istemci hata METNİNE değil
		# KODA bakarak karar verir. Düz `frappe.throw` bu kapıyı sözleşmenin
		# dışında bırakıyordu — panel reddi sınıflandıramıyor, kullanıcıya ham
		# sunucu metni gidiyordu.
		upload_policy.reddet(
			upload_policy.QUOTA_EXCEEDED,
			_("Depolama kotanız doldu ({0} MB). Yükleme yapılamadı.").format(
				int(limit_mb)
			),
		)

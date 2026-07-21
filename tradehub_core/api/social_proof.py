"""
Social Proof — product detail rotating badge signals.

Spec: tradehubfront/docs/superpowers/specs/2026-05-20-product-social-proof-badges-design.md
Plan: tradehubfront/docs/superpowers/plans/2026-05-20-product-social-proof-badges-plan.md

Endpoints (to be added in C2/D1/D2):
    get_signals(listing_id, supplier_id=None) — 6 metrics, threshold-filtered
    record_view(listing_id)                   — IP+listing 30min dedup, UPSERT counter

DocTypes:
    Social Proof Settings        — admin-tunable thresholds + ttls (singleton)
    Listing View Counter         — per-listing rolling 24h view count
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

from tradehub_core.api.rate_limit import rate_limit

_SETTINGS_CACHE_KEY = "social_proof_settings"
_RESPONSE_CACHE_PREFIX = "sp:"
_VIEW_DEDUP_PREFIX = "sp:view:"

_DEFAULT_THRESHOLDS = {
	"sales": 100,
	"favorites": 10,
	"cart_now": 3,
	"views_24h": 30,
	"distinct_buyers": 5,
	"seller_orders": 50,
}

# Mirrors listing.py convention — "satıldı" sayımına dahil edilen Order status'ları
SOLD_STATES = ("Kargoda", "Tamamlandı")


def _get_settings() -> dict:
	"""Social Proof Settings değerlerini döner (1 saat cache'li).

	Doc henüz install edilmemişse `_DEFAULT_THRESHOLDS`'a düşer. Cache invalidasyonu
	`SocialProofSettings.on_update()` tarafından yapılır — aynı `_SETTINGS_CACHE_KEY`
	silinir, sonraki çağrı taze değerleri okur.
	"""
	cached = frappe.cache().get_value(_SETTINGS_CACHE_KEY)
	if cached:
		return cached
	try:
		doc = frappe.get_single("Social Proof Settings")
		settings = {
			"enabled": bool(doc.enabled),
			"sales_threshold": int(doc.sales_threshold or _DEFAULT_THRESHOLDS["sales"]),
			"favorites_threshold": int(doc.favorites_threshold or _DEFAULT_THRESHOLDS["favorites"]),
			"cart_now_threshold": int(doc.cart_now_threshold or _DEFAULT_THRESHOLDS["cart_now"]),
			"views_24h_threshold": int(doc.views_24h_threshold or _DEFAULT_THRESHOLDS["views_24h"]),
			"distinct_buyers_threshold": int(
				doc.distinct_buyers_threshold or _DEFAULT_THRESHOLDS["distinct_buyers"]
			),
			"seller_orders_threshold": int(
				doc.seller_orders_threshold or _DEFAULT_THRESHOLDS["seller_orders"]
			),
			"cache_ttl_seconds": int(doc.cache_ttl_seconds or 600),
			"view_dedup_seconds": int(doc.view_dedup_seconds or 1800),
			# Field'lar Settings doc'una eklenmeden (migrate öncesi) None gelebilir —
			# None → "Yeni ürün" fallback varsayılan olarak açık, pencere sınırsız.
			"new_badge_enabled": True if doc.new_badge_enabled is None else bool(doc.new_badge_enabled),
			"new_badge_max_age_days": int(doc.new_badge_max_age_days or 0),
		}
	except Exception:
		# Settings doc henüz install edilmedi — default'lara düş
		settings = {
			"enabled": True,
			"sales_threshold": _DEFAULT_THRESHOLDS["sales"],
			"favorites_threshold": _DEFAULT_THRESHOLDS["favorites"],
			"cart_now_threshold": _DEFAULT_THRESHOLDS["cart_now"],
			"views_24h_threshold": _DEFAULT_THRESHOLDS["views_24h"],
			"distinct_buyers_threshold": _DEFAULT_THRESHOLDS["distinct_buyers"],
			"seller_orders_threshold": _DEFAULT_THRESHOLDS["seller_orders"],
			"cache_ttl_seconds": 600,
			"view_dedup_seconds": 1800,
			"new_badge_enabled": True,
			"new_badge_max_age_days": 0,
		}
	frappe.cache().set_value(_SETTINGS_CACHE_KEY, settings, expires_in_sec=3600)
	return settings


def _serialize_signal(sig_type: str, value: int, window_days: int | None = None) -> dict:
	"""Frontend `SocialProofBadge` component'inin tükettiği JSON shape'i üretir.

	`window_days` yalnızca zaman-pencereli sinyallerde (sales, distinct_buyers) eklenir.
	"""
	out = {"type": sig_type, "value": int(value)}
	if window_days is not None:
		out["window_days"] = int(window_days)
	return out


def _compute_sales(listing_id: str, supplier_id: str | None, settings: dict) -> dict:
	"""Son 30 günde satılan toplam adet.

	Auto-window (3/7/30) kaldırıldı — preview/admin tarafında filtreleme caller'da
	yapılıyor, sabit 30 gün toplamı yeterli sinyal sağlar.
	"""
	threshold = settings["sales_threshold"]
	from_dt = add_to_date(now_datetime(), days=-30)
	row = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(oi.quantity), 0)
		FROM `tabOrder Item` oi
		JOIN `tabOrder` o ON o.name = oi.parent
		WHERE oi.listing = %s
		  AND o.status IN %s
		  AND o.creation >= %s
		""",
		(listing_id, SOLD_STATES, from_dt),
	)
	qty = int(row[0][0] or 0) if row else 0
	return {"type": "sales", "value": qty, "threshold": threshold, "window_days": 30}


def _compute_favorites(listing_id: str, supplier_id: str | None, settings: dict) -> dict:
	threshold = settings["favorites_threshold"]
	count = frappe.db.count("Buyer Favorite Item", {"listing": listing_id})
	return {"type": "favorites", "value": int(count), "threshold": threshold}


def _compute_cart_now(listing_id: str, supplier_id: str | None, settings: dict) -> dict:
	"""Bu listing'i aktif sepetinde tutan distinct buyer sayısı."""
	threshold = settings["cart_now_threshold"]
	row = frappe.db.sql(
		"""
		SELECT COUNT(DISTINCT c.buyer)
		FROM `tabCart Item` ci
		JOIN `tabCart` c ON c.name = ci.parent
		WHERE ci.listing = %s
		  AND c.status = 'Active'
		""",
		(listing_id,),
	)
	count = int(row[0][0] or 0) if row else 0
	return {"type": "cart_now", "value": count, "threshold": threshold}


def _compute_views_24h(listing_id: str, supplier_id: str | None, settings: dict) -> dict:
	threshold = settings["views_24h_threshold"]
	value = frappe.db.get_value("Listing View Counter", listing_id, "view_count_24h") or 0
	return {"type": "views_24h", "value": int(value), "threshold": threshold}


def _compute_distinct_buyers(listing_id: str, supplier_id: str | None, settings: dict) -> dict:
	"""Son 30 günde bu listing'i sipariş eden distinct buyer (işletme) sayısı."""
	threshold = settings["distinct_buyers_threshold"]
	from_dt = add_to_date(now_datetime(), days=-30)
	row = frappe.db.sql(
		"""
		SELECT COUNT(DISTINCT o.buyer)
		FROM `tabOrder Item` oi
		JOIN `tabOrder` o ON o.name = oi.parent
		WHERE oi.listing = %s
		  AND o.status IN %s
		  AND o.creation >= %s
		""",
		(listing_id, SOLD_STATES, from_dt),
	)
	count = int(row[0][0] or 0) if row else 0
	return {"type": "distinct_buyers", "value": count, "threshold": threshold, "window_days": 30}


def _compute_seller_orders(listing_id: str, supplier_id: str | None, settings: dict) -> dict | None:
	"""Bu satıcının tüm zamanlardaki tamamlanmış sipariş sayısı.

	`supplier_id` verilmemişse `Listing.seller_profile`'dan türetilir.
	Listing bulunamazsa veya seller_profile boşsa None döner.
	"""
	threshold = settings["seller_orders_threshold"]
	if not supplier_id:
		supplier_id = frappe.db.get_value("Listing", listing_id, "seller_profile")
	if not supplier_id:
		return None
	count = frappe.db.count(
		"Order",
		filters={"seller": supplier_id, "status": "Tamamlandı"},
	)
	return {"type": "seller_orders", "value": int(count), "threshold": threshold}


def _is_new_listing(listing_id: str, settings: dict) -> bool:
	"""'Yeni ürün' fallback rozetinin bu listing'de gösterilip gösterilmeyeceği.

	max_age_days=0 → sinyali olmayan TÜM ürünler yeni sayılır (fallback her zaman).
	max_age_days>0 → yalnızca son N günde eklenen ürünler. Yalnızca eşik geçen sinyal
	yokken çağrılır; hot path'e (sinyalli ürün) ekstra sorgu getirmez.
	"""
	max_age = settings["new_badge_max_age_days"]
	if max_age <= 0:
		return True
	created = frappe.db.get_value("Listing", listing_id, "creation")
	if not created:
		return True
	return created >= add_to_date(now_datetime(), days=-max_age)


@frappe.whitelist(allow_guest=True)
def get_signals(listing_id: str, supplier_id: str | None = None) -> dict:
	"""
	Returns the list of social-proof signals that pass their thresholds.
	Empty list signals → frontend hides the badge entirely (no layout shift).

	Caches per-listing response for settings.cache_ttl_seconds (default 600s).
	Cache invalidated by Order.before_save hook (D4) on relevant status transitions.
	"""
	if not listing_id:
		frappe.throw(_("listing_id zorunludur"))

	settings = _get_settings()
	if not settings["enabled"]:
		return {"signals": []}

	listing_status = frappe.db.get_value("Listing", listing_id, "status")
	if listing_status == "Archived":
		return {"signals": []}

	cache_key = f"{_RESPONSE_CACHE_PREFIX}{listing_id}"
	cached = frappe.cache().get_value(cache_key)
	if cached:
		return cached

	compute_fns = (
		_compute_sales,
		_compute_favorites,
		_compute_cart_now,
		_compute_views_24h,
		_compute_distinct_buyers,
		_compute_seller_orders,
	)

	signals = []
	for fn in compute_fns:
		try:
			sig = fn(listing_id, supplier_id, settings)
			if sig and sig["value"] >= sig["threshold"]:
				signals.append(_serialize_signal(sig["type"], sig["value"], sig.get("window_days")))
		except Exception:
			frappe.log_error(title=f"social_proof.{fn.__name__}_fail")
			continue

	# Eşik geçen gerçek sinyal yoksa "Yeni ürün" fallback rozeti — kart/detay alanı
	# boş kalmasın (statik selling point kaldırıldı, alan tamamen sosyal kanıta ait).
	if not signals and settings["new_badge_enabled"] and _is_new_listing(listing_id, settings):
		signals.append(_serialize_signal("new", 0))

	response = {"signals": signals}
	frappe.cache().set_value(cache_key, response, expires_in_sec=settings["cache_ttl_seconds"])
	return response


# ── A-6: batch compute helpers (listing başına 6 sorgu → sinyal-tipi başına 1 GROUP BY) ──
# Her helper tekil _compute_* ile AYNI değeri üretir; get_signals_batch bunları kullanıp
# get_signals'in serialize/threshold mantığını birebir tekrarlar (get_signals değişmedi,
# referans olarak duruyor; eşdeğerlik get_signals_batch == {lid: get_signals(lid)} ile kanıtlanır).


def _batch_sales_and_buyers(ids: list) -> tuple[dict, dict]:
	"""_compute_sales + _compute_distinct_buyers — ortak Order join, tek sorgu."""
	if not ids:
		return {}, {}
	from_dt = add_to_date(now_datetime(), days=-30)
	rows = frappe.db.sql(
		"""
		SELECT oi.listing AS listing, COALESCE(SUM(oi.quantity), 0) AS qty,
		       COUNT(DISTINCT o.buyer) AS buyers
		FROM `tabOrder Item` oi
		JOIN `tabOrder` o ON o.name = oi.parent
		WHERE oi.listing IN %(ids)s AND o.status IN %(states)s AND o.creation >= %(dt)s
		GROUP BY oi.listing
		""",
		{"ids": tuple(ids), "states": SOLD_STATES, "dt": from_dt},
		as_dict=True,
	)
	return (
		{r.listing: int(r.qty or 0) for r in rows},
		{r.listing: int(r.buyers or 0) for r in rows},
	)


def _batch_favorites(ids: list) -> dict:
	if not ids:
		return {}
	rows = frappe.db.sql(
		"""SELECT listing, COUNT(*) AS cnt FROM `tabBuyer Favorite Item`
		   WHERE listing IN %(ids)s GROUP BY listing""",
		{"ids": tuple(ids)},
		as_dict=True,
	)
	return {r.listing: int(r.cnt or 0) for r in rows}


def _batch_cart_now(ids: list) -> dict:
	if not ids:
		return {}
	rows = frappe.db.sql(
		"""SELECT ci.listing AS listing, COUNT(DISTINCT c.buyer) AS cnt
		   FROM `tabCart Item` ci JOIN `tabCart` c ON c.name = ci.parent
		   WHERE ci.listing IN %(ids)s AND c.status = 'Active' GROUP BY ci.listing""",
		{"ids": tuple(ids)},
		as_dict=True,
	)
	return {r.listing: int(r.cnt or 0) for r in rows}


def _batch_views_24h(ids: list) -> dict:
	if not ids:
		return {}
	rows = frappe.get_all(
		"Listing View Counter",
		filters={"name": ["in", ids]},
		fields=["name", "view_count_24h"],
	)
	return {r.name: int(r.view_count_24h or 0) for r in rows}


def _batch_seller_orders(supplier_ids: list) -> dict:
	"""Satıcı başına tamamlanmış sipariş sayısı (seller_orders sinyali)."""
	if not supplier_ids:
		return {}
	rows = frappe.db.sql(
		"""SELECT seller, COUNT(*) AS cnt FROM `tabOrder`
		   WHERE seller IN %(sids)s AND status = 'Tamamlandı' GROUP BY seller""",
		{"sids": tuple(supplier_ids)},
		as_dict=True,
	)
	return {r.seller: int(r.cnt or 0) for r in rows}


@frappe.whitelist(allow_guest=True)
def get_signals_batch(listing_ids: str) -> dict:
	"""
	Birden çok listing için sosyal kanıt sinyallerini tek çağrıda döner (listing grid).

	listing_ids: virgülle ayrılmış listing id'leri ("L1,L2,L3").
	Dönüş: {listing_id: {"signals": [...]}} — get_signals ile AYNI per-listing yapı +
	aynı per-listing cache. Sinyaller tekil get_signals gibi listing başına değil,
	sinyal-tipi başına TEK GROUP BY sorgusuyla hesaplanır (60 kart × 6 = 360 → ~5 sorgu).
	"""
	if not listing_ids:
		return {}

	# Dedup + güvenlik: aşırı büyük batch'i sınırla (storefront tek sayfa ~40 ürün)
	ids = list(dict.fromkeys(s.strip() for s in listing_ids.split(",") if s.strip()))[:60]
	if not ids:
		return {}

	settings = _get_settings()
	if not settings["enabled"]:
		return {lid: {"signals": []} for lid in ids}

	# Per-listing cache — get_signals ile paylaşımlı (tekil çağrılarla tutarlı).
	out: dict = {}
	uncached: list = []
	for lid in ids:
		cached = frappe.cache().get_value(f"{_RESPONSE_CACHE_PREFIX}{lid}")
		if cached is not None:
			out[lid] = cached
		else:
			uncached.append(lid)

	if not uncached:
		return out

	# Uncached listing'lerin status + supplier bilgisi (Archived elenir).
	meta = {
		r.name: r
		for r in frappe.get_all(
			"Listing",
			filters={"name": ["in", uncached]},
			fields=["name", "status", "seller_profile"],
		)
	}
	active = [lid for lid in uncached if meta.get(lid) and meta[lid].status != "Archived"]

	# Batch compute — sinyal-tipi başına tek sorgu.
	sales_map, buyers_map = _batch_sales_and_buyers(active)
	fav_map = _batch_favorites(active)
	cart_map = _batch_cart_now(active)
	views_map = _batch_views_24h(active)
	# supplier_id = Listing.seller_profile — _compute_seller_orders'ın fallback'iyle aynı
	# (Listing'de "seller" kolonu yok; tekil compute de supplier None gelince seller_profile'a düşer).
	supplier_of = {lid: meta[lid].seller_profile for lid in active}
	seller_orders_map = _batch_seller_orders(list({s for s in supplier_of.values() if s}))

	for lid in uncached:
		m = meta.get(lid)
		if not m or m.status == "Archived":
			resp = {"signals": []}
		else:
			# get_signals ile AYNI sıra + threshold + serialize.
			raw = [
				("sales", sales_map.get(lid, 0), settings["sales_threshold"], 30),
				("favorites", fav_map.get(lid, 0), settings["favorites_threshold"], None),
				("cart_now", cart_map.get(lid, 0), settings["cart_now_threshold"], None),
				("views_24h", views_map.get(lid, 0), settings["views_24h_threshold"], None),
				("distinct_buyers", buyers_map.get(lid, 0), settings["distinct_buyers_threshold"], 30),
			]
			signals = [
				_serialize_signal(typ, val, win) for (typ, val, thr, win) in raw if val >= thr
			]
			supplier_id = supplier_of.get(lid)
			if supplier_id:
				so_val = seller_orders_map.get(supplier_id, 0)
				if so_val >= settings["seller_orders_threshold"]:
					signals.append(_serialize_signal("seller_orders", so_val, None))
			resp = {"signals": signals}

		frappe.cache().set_value(
			f"{_RESPONSE_CACHE_PREFIX}{lid}", resp, expires_in_sec=settings["cache_ttl_seconds"]
		)
		out[lid] = resp

	return out


# M16 fix — guest sayaç şişirmeye karşı IP/oturum başına rate-limit (30dk dedup'a ek).
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(max_calls=60, window_seconds=300, per_user=True)
def record_view(listing_id: str) -> None:
	"""
	Records a single view of the listing. Same IP+listing within
	settings.view_dedup_seconds (default 30min) is a no-op.

	Always returns 204 — failures must not block the frontend.
	"""
	if not listing_id:
		return

	settings = _get_settings()
	if not settings["enabled"]:
		return

	ip = (frappe.local.request_ip or "anon")[:64]
	dedup_key = f"{_VIEW_DEDUP_PREFIX}{ip}:{listing_id}"
	if frappe.cache().get_value(dedup_key):
		frappe.local.response["http_status_code"] = 204
		return

	frappe.cache().set_value(dedup_key, 1, expires_in_sec=settings["view_dedup_seconds"])

	try:
		frappe.db.sql(
			"""
			INSERT INTO `tabListing View Counter`
			  (name, listing, view_count_24h, last_event, creation, modified, owner, modified_by, docstatus, idx)
			VALUES (%s, %s, 1, NOW(), NOW(), NOW(), %s, %s, 0, 0)
			ON DUPLICATE KEY UPDATE
			  view_count_24h = view_count_24h + 1,
			  last_event = NOW(),
			  modified = NOW()
			""",
			(listing_id, listing_id, frappe.session.user, frappe.session.user),
		)
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="social_proof.record_view_fail")

	frappe.local.response["http_status_code"] = 204


_INVALIDATING_STATES = {"Kargoda", "Tamamlandı", "İptal Edildi"}
# Status'lerden biri _INVALIDATING_STATES'e girdiğinde veya çıktığında
# sales/distinct-buyers metrikleri değişebilir — cache'i temizle.


def invalidate_for_order(doc, method=None):
	"""
	Order before_save hook'u — status geçişine bağlı olarak ilgili
	listing'lerin social_proof cache'lerini siler.

	Mevcut listing.py:bump_listing_order_counts ile paralel çalışır;
	cache invalidate idempotent (silinmiş key'i tekrar silmek no-op),
	dolayısıyla ayrı bir flag tutulmuyor.
	"""
	try:
		prev_status = None
		if doc.name and not doc.is_new():
			prev_status = frappe.db.get_value("Order", doc.name, "status")
		new_status = (doc.status or "").strip()

		# Status değişmediyse hiçbir şey yapma
		if prev_status == new_status:
			return
		# İki taraftan biri _INVALIDATING_STATES'te değilse cache aynen kalsın
		if new_status not in _INVALIDATING_STATES and prev_status not in _INVALIDATING_STATES:
			return

		for item in doc.items or []:
			listing = getattr(item, "listing", None)
			if listing:
				frappe.cache().delete_value(f"{_RESPONSE_CACHE_PREFIX}{listing}")
	except Exception:
		frappe.log_error(title="social_proof.invalidate_for_order_fail")


def reset_view_counters_rolling_24h() -> None:
	"""
	Zeroes out view_count_24h for counters whose last_event is older than 24h.
	Hourly scheduled task (hooks.py).

	Counter rows are kept (not deleted) so the next view can do simple UPSERT
	without re-checking existence.
	"""
	frappe.db.sql(
		"""
		UPDATE `tabListing View Counter`
		SET view_count_24h = 0,
		    modified = NOW()
		WHERE last_event < NOW() - INTERVAL 24 HOUR
		  AND view_count_24h > 0
		"""
	)
	frappe.db.commit()


_THRESHOLD_MIN = 1
_THRESHOLD_MAX = 100000
_TTL_MIN = 60
_TTL_MAX = 86400

_THRESHOLD_FIELDS = (
	"sales",
	"favorites",
	"cart_now",
	"views_24h",
	"distinct_buyers",
	"seller_orders",
)


def _require_int_in_range(value, label: str, lo: int, hi: int) -> None:
	"""value pozitif int değil veya [lo, hi] dışındaysa frappe.ValidationError fırlatır.

	`bool` Python'da int subclass'ı olduğu için ayrıca dışlanır — admin form
	'sales: true' gibi bir payload gönderirse threshold'u 1'e düşürmemeli.
	"""
	if isinstance(value, bool) or not isinstance(value, int) or value < lo or value > hi:
		frappe.throw(
			_("{0} {1}-{2} arasında olmalı: {3}").format(label, lo, hi, value),
			exc=frappe.ValidationError,
		)


def _validate_payload(payload: dict) -> None:
	"""Admin update payload'ını doğrular. Bozuk değer → frappe.ValidationError."""
	if not isinstance(payload, dict):
		frappe.throw(_("Geçersiz payload"), exc=frappe.ValidationError)

	thresholds = payload.get("thresholds") or {}
	for field in _THRESHOLD_FIELDS:
		_require_int_in_range(thresholds.get(field), f"Eşik ({field})", _THRESHOLD_MIN, _THRESHOLD_MAX)

	_require_int_in_range(payload.get("cache_ttl_seconds"), "Önbellek TTL (sn)", _TTL_MIN, _TTL_MAX)
	_require_int_in_range(payload.get("view_dedup_seconds"), "Görüntülenme dedup (sn)", _TTL_MIN, _TTL_MAX)

	# Opsiyonel — yalnızca gönderildiyse doğrula (eski payload'larla geriye uyum).
	# 0 = tüm ürünler; üst sınır 365 gün.
	if "new_badge_max_age_days" in payload:
		_require_int_in_range(payload.get("new_badge_max_age_days"), "Yeni ürün maks. yaş (gün)", 0, 365)


_SAMPLE_CACHE_KEY = "social_proof:admin_samples"
_SAMPLE_CACHE_TTL_SEC = 300


def _pick_sample_listings() -> list[tuple[str, str]]:
	"""3 listing seç: hot (en yüksek view), warm (medyan), cold (en düşük).

	5 dk cache'li (TTL ile bounded). Admin preview için kullanıldığı için
	write-time cache invalidation eklenmedi — staleness ≤ 5 dk kabul edilebilir.
	Counter datası yoksa son 3 Active Listing fallback (boş Listing tablosunda
	sonuç boş kalır, boş listeyi cache'lemez).
	"""
	cached = frappe.cache().get_value(_SAMPLE_CACHE_KEY)
	if cached:
		return cached

	counters = frappe.db.sql(
		"""
		SELECT listing
		FROM `tabListing View Counter`
		WHERE view_count_24h > 0
		ORDER BY view_count_24h DESC
		""",
		as_dict=True,
	)

	if not counters:
		# Admin-only helper: get_all (not get_list) is intentional — System Manager /
		# Marketplace Admin must see listings across all sellers, bypassing
		# permission_query_conditions for the preview UI.
		recent = frappe.get_all(
			"Listing",
			filters={"status": "Active"},
			fields=["name"],
			order_by="creation desc",
			limit=3,
		)
		labels = ("hot", "warm", "cold")
		result = [(r.name, labels[i]) for i, r in enumerate(recent)]
	else:
		hot = counters[0]["listing"]
		cold = counters[-1]["listing"]
		warm = counters[len(counters) // 2]["listing"]
		result = [(hot, "hot"), (warm, "warm"), (cold, "cold")]

	if result:
		frappe.cache().set_value(_SAMPLE_CACHE_KEY, result, expires_in_sec=_SAMPLE_CACHE_TTL_SEC)
	return result


@frappe.whitelist()
def get_admin_settings() -> dict:
	"""Admin panel için Settings Single doc'unun tüm field'larını döner.

	System Manager veya Marketplace Admin role'ü zorunlu.
	"""
	frappe.only_for(["System Manager", "Marketplace Admin"])

	doc = frappe.get_single("Social Proof Settings")
	return {
		"enabled": bool(doc.enabled),
		"new_badge_enabled": True if doc.new_badge_enabled is None else bool(doc.new_badge_enabled),
		"new_badge_max_age_days": int(doc.new_badge_max_age_days or 0),
		"thresholds": {
			"sales": int(doc.sales_threshold),
			"favorites": int(doc.favorites_threshold),
			"cart_now": int(doc.cart_now_threshold),
			"views_24h": int(doc.views_24h_threshold),
			"distinct_buyers": int(doc.distinct_buyers_threshold),
			"seller_orders": int(doc.seller_orders_threshold),
		},
		"cache_ttl_seconds": int(doc.cache_ttl_seconds),
		"view_dedup_seconds": int(doc.view_dedup_seconds),
	}


@frappe.whitelist(methods=["POST"])
def update_admin_settings(payload: dict | str) -> dict:
	"""Settings'i günceller. SocialProofSettings.on_update() cache'i temizler.

	System Manager veya Marketplace Admin role'ü zorunlu.
	"""
	frappe.only_for(["System Manager", "Marketplace Admin"])

	if isinstance(payload, str):
		payload = json.loads(payload)

	_validate_payload(payload)

	doc = frappe.get_single("Social Proof Settings")
	doc.enabled = 1 if payload.get("enabled") is True else 0
	for sig in _THRESHOLD_FIELDS:
		setattr(doc, f"{sig}_threshold", int(payload["thresholds"][sig]))
	doc.cache_ttl_seconds = int(payload["cache_ttl_seconds"])
	doc.view_dedup_seconds = int(payload["view_dedup_seconds"])
	# Yeni ürün rozeti alanları opsiyonel — eski admin payload'ı göndermezse
	# varsayılan korunur (enabled açık, pencere sınırsız).
	doc.new_badge_enabled = 0 if payload.get("new_badge_enabled") is False else 1
	doc.new_badge_max_age_days = int(payload.get("new_badge_max_age_days") or 0)
	doc.save()
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def get_admin_preview_signals(threshold_overrides: dict | str | None = None) -> dict:
	"""3 sample listing için sinyalleri kaydedilmemiş eşiklerle hesaplar.

	Settings doc'una YAZMAZ — sadece simulate eder. System Manager veya
	Marketplace Admin role'ü zorunlu.
	"""
	frappe.only_for(["System Manager", "Marketplace Admin"])

	if isinstance(threshold_overrides, str):
		threshold_overrides = json.loads(threshold_overrides)

	settings = _get_settings().copy()
	if threshold_overrides:
		for sig, val in threshold_overrides.items():
			settings[f"{sig}_threshold"] = int(val)

	samples = _pick_sample_listings()

	compute_fns = (
		_compute_sales,
		_compute_favorites,
		_compute_cart_now,
		_compute_views_24h,
		_compute_distinct_buyers,
		_compute_seller_orders,
	)

	results = []
	for listing_id, label in samples:
		passed: list[dict] = []
		filtered: list[dict] = []
		for fn in compute_fns:
			try:
				sig = fn(listing_id, None, settings)
				if sig and sig["value"] >= sig["threshold"]:
					passed.append(_serialize_signal(sig["type"], sig["value"], sig.get("window_days")))
				elif sig:
					filtered.append(
						{
							"type": sig["type"],
							"value": sig["value"],
							"threshold": sig["threshold"],
						}
					)
			except Exception:
				frappe.log_error(title=f"social_proof.preview_{fn.__name__}_fail")
				continue

		# Canlı önizleme, gerçek get_signals ile tutarlı olsun: eşik geçen sinyal
		# yoksa "Yeni ürün" fallback rozeti burada da görünsün.
		if not passed and settings["new_badge_enabled"] and _is_new_listing(listing_id, settings):
			passed.append(_serialize_signal("new", 0))

		results.append(
			{
				"listing_id": listing_id,
				"label": label,
				"title": frappe.db.get_value("Listing", listing_id, "title") or "",
				"signals": passed,
				"filtered_out": filtered,
			}
		)

	return {"samples": results}

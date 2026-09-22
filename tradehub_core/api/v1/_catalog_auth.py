"""Ürün API'si kimlik kapısı (MOGEM-665 · 2. aşama, plan K2).

Üç uç noktanın (`catalog.upsert_products`, `update_stock`, `changes`) tek giriş
noktası. Sırasıyla:

1. `Authorization: Bearer <jeton>` — `public_api._verify_bearer` (HS256, site sırrı,
   24 saat). Yanlış şema / bozuk imza / süresi dolmuş → 401.
2. Yetki alanı (`catalog:write` · `stock:write` · `catalog:read`) — jetonun
   içindeki `scopes` listesi. Eksikse → 403.
3. Uygulama hâlâ aktif mi (jeton 24 saat yaşar; panelden kapatılınca anında
   ölmeli) ve bir mağazaya bağlı mı. Bağsız uygulama katalog yazamaz → 403.
4. Mağaza aktif mi; sahibi kim; paketinde `feature.api.access` var mı (free
   pakette yok → 403). Görev metni: "satıcının paketindeki … özellik sınırları
   korunur" — API erişimi de bir paket özelliğidir.
5. Hız sınırı: paketin `quota.api_rate_limit` değeri (pro 60 · enterprise 1.000
   istek/dk; abonelik `custom_quota_overrides` ile mağaza bazında değişir).
   Pakette tanımsız/0 ise uygulamanın katmanına göre varsayılan tablo.
6. **Oturum devri:** istek mağaza sahibinin kullanıcısı olarak koşar
   (`frappe.set_user`). Böylece tenant izolasyonu, kota kapısı ve `owner`
   alanı bugünkü panel akışıyla birebir aynı yoldan geçer; misafir oturumunda
   `enforce_feature` mağazayı bulamayıp reddediyordu (plan K2, mobil API deseni).

Çıkışta oturum her koşulda eski hâline döner (try/finally).
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

import frappe
from frappe import _

from tradehub_core.api.rate_limit import TooManyRequestsError
from tradehub_core.api.v1.public_api import _check_scope, _verify_bearer
from tradehub_core.entitlement.core import check_feature_or_throw, get_quota_limits

CATALOG_SCOPES = ("catalog:write", "stock:write", "catalog:read")
API_FEATURE = "feature.api.access"
RATE_QUOTA_KEY = "quota.api_rate_limit"
RATE_WINDOW = 60

# Paket kotası tanımsızsa (eski abonelikler) uygulama katmanına göre yedek tablo.
RATE_LIMITS = {
	"free": {"max_calls": 60, "window": RATE_WINDOW},
	"pro": {"max_calls": 600, "window": RATE_WINDOW},
	"enterprise": {"max_calls": 6000, "window": RATE_WINDOW},
}


@dataclass(frozen=True)
class CatalogContext:
	app: str
	seller: str
	owner: str
	tier: str
	scopes: tuple[str, ...]


def _rate_key(app: str) -> str:
	return f"catalog_rl:{app}"


def reset_rate_limit(app: str) -> None:
	"""Test/ops: bir uygulamanın sayacını sıfırla."""
	cache = frappe.cache()
	cache.delete(cache.make_key(_rate_key(app)))


def effective_rate_limit(seller: str, tier: str) -> dict:
	"""Mağazanın dakikalık istek sınırı: paket kotası > katman yedeği."""
	try:
		kota = int(get_quota_limits(seller).get(RATE_QUOTA_KEY) or 0)
	except (TypeError, ValueError):
		kota = 0
	if kota > 0:
		return {"max_calls": kota, "window": RATE_WINDOW}
	return RATE_LIMITS.get(tier or "free", RATE_LIMITS["free"])


def _enforce_rate_limit(app: str, seller: str, tier: str) -> None:
	limits = effective_rate_limit(seller, tier)
	cache = frappe.cache()
	# Ham Redis anahtarı (site önekiyle): INCR/EXPIRE atomik — public_api'deki
	# get→delete→set deseni yarışta kaçırıyordu (rapor 87 W7-4).
	key = cache.make_key(_rate_key(app))
	try:
		current = int(cache.incr(key))
		if current == 1:
			cache.expire(key, limits["window"])
	except Exception:
		# F-004 kararıyla aynı: Redis kesintisinde hız sınırı devre dışı kalır, API çalışmaya
		# devam eder (fail-open); kesinti Error Log'a düşer. Fail-closed tüm ERP'leri kilitlerdi.
		frappe.log_error(title="Catalog rate limiter Redis incr failed", message=f"app={app}")
		return
	if current > limits["max_calls"]:
		raise TooManyRequestsError(
			_("Hız sınırı aşıldı: {0} istek / {1} sn ({2} katmanı). Biraz sonra tekrar deneyin.").format(
				limits["max_calls"], limits["window"], tier
			)
		)


CATALOG_PATH_PREFIX = "/api/method/tradehub_core.api.v1.catalog."


def authenticate_catalog_bearer() -> None:
	"""Frappe `auth_hooks` kancası — Ürün API'si jetonunu oturuma çevirir.

	NEDEN GEREKİYOR — ÖLÇÜLDÜ (15 Eyl 2026, gerçek HTTP uçtan uca)
	---------------------------------------------------------------
	`frappe.auth.validate_auth` iki parçalı `Authorization` başlığı taşıyan HER
	isteği, bir kullanıcı atanmadıysa uç fonksiyonuna ulaşmadan 401 ile keser
	(`validate_oauth` yalnız `OAuth Bearer Token` tablosuna bakar). Süreç içi
	testler bu katmanı görmez — doğru jetonla da 401 alındı. Aynı tuzak
	`api/observability.authenticate_metrics_scrape` başlığında belgelenmiş; bu
	depoda `public_api`'nin diğer Bearer uçları da (`get_reviews` vb.) aynı
	nedenle HTTP'de çalışmıyor — bu kanca YALNIZ katalog uçlarını açar.

	NE KADAR YETKİ VERİYOR
	----------------------
	Yalnız `/api/method/tradehub_core.api.v1.catalog.*` yolunda ve yalnız
	jeton + uygulama + mağaza + paket zinciri doğrulanınca mağaza sahibi oturumu
	kurulur; başka bir yolda jeton HİÇBİR oturum açmaz (401). Yetki alanı ve hız
	sınırı uç içindeki `catalog_context` tarafından ayrıca uygulanır.
	"""
	req = getattr(frappe.local, "request", None)
	if not req or not str(getattr(req, "path", "") or "").startswith(CATALOG_PATH_PREFIX):
		return
	if not str(req.headers.get("Authorization", "") or "").startswith("Bearer "):
		return
	try:
		ctx = _identity()
	except Exception:
		# Uç fonksiyonu (catalog_context) aynı zinciri yeniden koşup doğru hatayı üretir;
		# validate_auth'un 401'i beklenen davranış. Mesaj kuyruğunu kirletme.
		frappe.clear_last_message()
		return
	# `frappe.set_user` form_dict'i SIFIRLAR (frappe/__init__.py) — istek gövdesi
	# (`products`/`items`) kaybolur, uç "liste olmalı" der. Frappe'nin kendi
	# `validate_oauth`'u da aynı nedenle sakla/geri-yükle yapıyor. Ölçüldü (15 Eyl e2e).
	form_dict = frappe.local.form_dict
	frappe.set_user(ctx.owner)
	frappe.local.form_dict = form_dict


def _identity() -> CatalogContext:
	"""Jeton → uygulama → mağaza → paket zinciri (yetki alanı ve hız sınırı HARİÇ)."""
	payload = _verify_bearer()
	app_name = payload.get("sub")
	app = frappe.db.get_value(
		"API Application",
		app_name,
		["name", "is_active", "seller_profile", "rate_limit_tier"],
		as_dict=True,
	)
	if not app or not app.is_active:
		frappe.throw(_("Uygulama kapalı ya da silinmiş; jeton geçersiz"), frappe.AuthenticationError)
	if not app.seller_profile:
		frappe.throw(
			_("Bu uygulama bir mağazaya bağlı değil; katalog işlemi yapamaz"), frappe.PermissionError
		)

	magaza = frappe.db.get_value("Admin Seller Profile", app.seller_profile, ["user", "status"], as_dict=True)
	if not magaza or not magaza.user:
		frappe.throw(_("Mağaza bulunamadı"), frappe.PermissionError)
	if magaza.status != "Active":
		frappe.throw(_("Mağaza aktif değil ({0})").format(magaza.status), frappe.PermissionError)

	# Paket kapısı: EntitlementError (PermissionError alt sınıfı, 403) — mesaj plan adını söyler.
	check_feature_or_throw(app.seller_profile, API_FEATURE, action_description=_("Ürün API'si"))
	return CatalogContext(
		app=app.name,
		seller=app.seller_profile,
		owner=magaza.user,
		tier=app.rate_limit_tier or "free",
		scopes=tuple(payload.get("scopes") or ()),
	)


def _resolve(scope: str) -> CatalogContext:
	if scope not in CATALOG_SCOPES:
		frappe.throw(_("Bilinmeyen yetki alanı: {0}").format(scope), frappe.PermissionError)
	ctx = _identity()
	_check_scope(scope, {"scopes": list(ctx.scopes)})
	_enforce_rate_limit(ctx.app, ctx.seller, ctx.tier)
	return ctx


@contextmanager
def catalog_context(scope: str):
	"""`with catalog_context("catalog:write") as ctx:` — içeride oturum mağaza sahibidir."""
	ctx = _resolve(scope)
	onceki = frappe.session.user
	frappe.set_user(ctx.owner)
	try:
		yield ctx
	finally:
		frappe.set_user(onceki)

"""Panel · Ürün API'si bağlantı yönetimi (MOGEM-665 · 2. ve 6. aşama).

Mağaza sahibi (oturumlu) kendi mağazasının API uygulamasını yönetir:
`get_connection` · `create_or_rotate_credentials` · `set_webhook` ·
`revoke_credentials` · `list_outbound_events` · `retry_outbound_event`.

Tek kural: her çağrı yalnız oturumdaki kullanıcının SAHİBİ olduğu mağazaya
dokunur. Sır (client_secret / webhook_secret) yalnız oluşturma/yenileme
cevabında bir kez döner; okuma uçları `has_*` bayrağı verir.
"""

from __future__ import annotations

import secrets

import frappe
from frappe import _

from tradehub_core.api.v1._catalog_auth import API_FEATURE, CATALOG_SCOPES, effective_rate_limit
from tradehub_core.bulk_import.feed_security import validate_feed_url
from tradehub_core.entitlement.core import check_feature_or_throw, has_feature

WEBHOOK_FEATURE = "feature.api.webhook"


def _magazam() -> str:
	"""Oturumdaki kullanıcının sahibi olduğu mağaza; yoksa PermissionError."""
	user = frappe.session.user
	if user in ("Guest", "", None):
		frappe.throw(_("Giriş yapmanız gerekiyor"), frappe.PermissionError)
	seller = frappe.db.get_value("Admin Seller Profile", {"user": user, "status": "Active"}, "name")
	if not seller:
		frappe.throw(_("Yalnız mağaza sahibi API bağlantısını yönetebilir"), frappe.PermissionError)
	return seller


def _uygulamam(seller: str):
	return frappe.db.get_value(
		"API Application",
		{"seller_profile": seller},
		["name", "client_id", "is_active", "webhook_url", "rate_limit_tier", "webhook_failures", "creation"],
		as_dict=True,
	)


@frappe.whitelist()
def get_connection() -> dict:
	seller = _magazam()
	app = _uygulamam(seller)
	paket = {
		"api_access": has_feature(seller, API_FEATURE),
		"webhook": has_feature(seller, WEBHOOK_FEATURE),
	}
	if not app:
		return {
			"seller": seller,
			"client_id": None,
			"is_active": 0,
			"scopes": [],
			"has_secret": False,
			"features": paket,
		}
	doc = frappe.get_doc("API Application", app.name)
	return {
		"seller": seller,
		"features": paket,
		"rate_limit_per_minute": effective_rate_limit(seller, app.rate_limit_tier)["max_calls"],
		"app": app.name,
		"client_id": app.client_id,
		"is_active": int(app.is_active or 0),
		"has_secret": bool(doc.get_password("client_secret", raise_exception=False)),
		"scopes": [s.scope for s in doc.scopes],
		"webhook_url": app.webhook_url or "",
		"has_webhook_secret": bool(doc.get_password("webhook_secret", raise_exception=False)),
		"webhook_failures": int(app.webhook_failures or 0),
		"rate_limit_tier": app.rate_limit_tier or "free",
		"created_at": str(app.creation) if app.creation else None,
		"token_url": "/api/method/tradehub_core.api.v1.public_api.token",
	}


@frappe.whitelist()
def create_or_rotate_credentials() -> dict:
	"""Mağaza için uygulama yoksa oluştur, varsa sırrını yenile (client_id sabit).

	Eski sır anında geçersiz olur (jeton ucu sırrı doğrudan karşılaştırır);
	daha önce verilmiş jetonlar 24 saat içinde kendiliğinden düşer — anında
	düşürmek için `revoke_credentials`.
	"""
	seller = _magazam()
	check_feature_or_throw(seller, API_FEATURE, action_description=_("Ürün API'si"))
	secret = secrets.token_urlsafe(32)
	app = _uygulamam(seller)
	if app:
		doc = frappe.get_doc("API Application", app.name)
		doc.client_secret = secret
		doc.is_active = 1
		mevcut = {s.scope for s in doc.scopes}
		for s in CATALOG_SCOPES:
			if s not in mevcut:
				doc.append("scopes", {"scope": s})
		doc.save(ignore_permissions=True)
		olustu = False
	else:
		tier = _katman(seller)
		doc = frappe.get_doc(
			{
				"doctype": "API Application",
				"app_name": f"Ürün API · {seller}",
				"developer_email": frappe.session.user,
				"is_active": 1,
				"client_id": f"istoc_{seller.lower()}_{secrets.token_hex(6)}",
				"client_secret": secret,
				"rate_limit_tier": tier,
				"seller_profile": seller,
				"scopes": [{"scope": s} for s in CATALOG_SCOPES],
			}
		).insert(ignore_permissions=True)
		olustu = True
	frappe.db.commit()
	return {
		"app": doc.name,
		"client_id": doc.client_id,
		"client_secret": secret,  # yalnız bu cevapta
		"created": olustu,
		"scopes": list(CATALOG_SCOPES),
	}


def _katman(seller: str) -> str:
	"""Abonelik planından hız katmanı: enterprise → enterprise, pro → pro, gerisi free."""
	plan = (
		frappe.db.get_value(
			"Store Subscription", {"store": seller, "status": ["in", ["active", "trial", "past_due"]]}, "plan"
		)
		or ""
	).lower()
	return plan if plan in ("pro", "enterprise") else "free"


@frappe.whitelist()
def set_webhook(webhook_url: str = "", webhook_secret: str = "") -> dict:
	"""Webhook adresi + imza sırrı. Adres SSRF süzgecinden geçer (yerel/özel ağ yasak)."""
	seller = _magazam()
	app = _uygulamam(seller)
	if not app:
		frappe.throw(_("Önce API bağlantısı oluşturun"))
	doc = frappe.get_doc("API Application", app.name)
	url = (webhook_url or "").strip()
	if url:
		check_feature_or_throw(seller, WEBHOOK_FEATURE, action_description=_("Stok Webhook'u"))
		validate_feed_url(url)
		doc.webhook_url = url
	else:
		doc.webhook_url = ""
	if webhook_secret:
		doc.webhook_secret = webhook_secret
	doc.webhook_failures = 0
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "webhook_url": doc.webhook_url or ""}


@frappe.whitelist()
def revoke_credentials() -> dict:
	"""Uygulamayı kapat: sır silinir, verilmiş jetonlar anında reddedilir."""
	seller = _magazam()
	app = _uygulamam(seller)
	if not app:
		return {"ok": True, "revoked": False}
	doc = frappe.get_doc("API Application", app.name)
	doc.is_active = 0
	doc.client_secret = ""
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "revoked": True}


@frappe.whitelist()
def list_outbound_events(status: str = "", limit: int = 50, offset: int = 0) -> dict:
	"""Mağazanın giden stok olayları (5./6. aşama: iletilemeyenler burada görülür)."""
	seller = _magazam()
	filters = {"seller_profile": seller}
	if status:
		filters["status"] = status
	limit = max(1, min(int(limit or 50), 200))
	rows = frappe.get_all(
		"Catalog Outbound Event",
		filters=filters,
		fields=[
			"name",
			"event_type",
			"listing",
			"sku",
			"stock_qty",
			"available_qty",
			"reason",
			"occurred_at",
			"status",
			"attempts",
			"next_attempt_at",
			"last_http_status",
			"last_error",
			"delivered_at",
		],
		order_by="occurred_at desc",
		limit_start=int(offset or 0),
		limit_page_length=limit,
	)
	return {
		"events": rows,
		"total": frappe.db.count("Catalog Outbound Event", filters),
		"counts": {
			s: frappe.db.count("Catalog Outbound Event", {"seller_profile": seller, "status": s})
			for s in ("queued", "sent", "failed", "dead")
		},
	}


@frappe.whitelist()
def retry_outbound_event(name: str) -> dict:
	"""Ölü/başarısız bir olayı elle yeniden kuyruğa al (yalnız kendi mağazası)."""
	from tradehub_core.integration.outbound import requeue

	seller = _magazam()
	ev = frappe.db.get_value("Catalog Outbound Event", name, ["seller_profile", "status"], as_dict=True)
	if not ev or ev.seller_profile != seller:
		frappe.throw(_("Olay bulunamadı"), frappe.PermissionError)
	if ev.status not in ("failed", "dead"):
		frappe.throw(_("Yalnız başarısız ya da ölü olaylar yeniden denenebilir"))
	requeue(name)
	return {"ok": True}

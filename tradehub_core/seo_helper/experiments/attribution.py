"""13.6 Ölçüm — organik trafiğin RFQ, mağaza iletişimi ve siparişle ilişkisi.

- Vitrin ilk isteğinde `record_landing` (guest, whitelisted) çağrılır → iniş yolu + yönlendiren +
  utm çerezi (`shc_land`, 30 gün, HttpOnly değil: vitrin JS okumaz ama yazmaz da; sunucu yazar).
- `RFQ` / `Seller Inquiry` / `Order` `after_insert` kancası çerezi okuyup Custom Field'lara yazar:
  `seo_landing_path, seo_referrer, seo_utm_source, seo_utm_medium, seo_utm_campaign, seo_is_organic`.
- Günlük toplulaştırma (`rollup_daily`) → `SEO Metric Snapshot` (analytics): organik RFQ/iletişim/sipariş,
  boyut: all / page_type / store / lang.
Saf kısım: `classify()` ve `page_type_of` (botlog ile aynı).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import date
from urllib.parse import urlsplit

SEARCH_ENGINES = {
	"google": ("google.",),
	"bing": ("bing.com",),
	"yandex": ("yandex.",),
	"duckduckgo": ("duckduckgo.com",),
	"yahoo": ("search.yahoo.",),
	"baidu": ("baidu.com",),
}
COOKIE = "shc_land"
COOKIE_DAYS = 30
CONVERSION_DOCTYPES = {"RFQ": "rfq", "Seller Inquiry": "inquiry", "Order": "order"}
FIELDS = (
	"seo_landing_path",
	"seo_referrer",
	"seo_utm_source",
	"seo_utm_medium",
	"seo_utm_campaign",
	"seo_is_organic",
	"seo_landing_lang",
)


def classify(referrer: str = "", utm_source: str = "", utm_medium: str = "") -> dict:
	"""Organik mi? utm_medium=organic ya da bilinen arama motoru yönlendirmesi (utm yoksa)."""
	src, med = (utm_source or "").strip().lower(), (utm_medium or "").strip().lower()
	if med:
		return {"organic": med == "organic", "engine": src or None, "channel": med}
	host = urlsplit(referrer or "").netloc.lower()
	if not host:
		return {"organic": False, "engine": None, "channel": "direct" if not src else "other"}
	for engine, sonekler in SEARCH_ENGINES.items():
		if any(s in host for s in sonekler):
			return {"organic": True, "engine": engine, "channel": "organic"}
	return {"organic": False, "engine": None, "channel": "referral"}


def landing_payload(path: str, referrer: str = "", utm: dict | None = None, lang: str = "") -> dict:
	utm = utm or {}
	k = classify(referrer, utm.get("utm_source", ""), utm.get("utm_medium", ""))
	return {
		"path": (urlsplit(path or "/").path or "/")[:300],
		"ref": (referrer or "")[:300],
		"utm_source": (utm.get("utm_source") or "")[:80],
		"utm_medium": (utm.get("utm_medium") or "")[:80],
		"utm_campaign": (utm.get("utm_campaign") or "")[:120],
		"lang": (lang or "")[:5],
		"organic": 1 if k["organic"] else 0,
		"engine": k["engine"] or "",
	}


def sign_payload(secret: str, payload: dict) -> str:
	"""base64(json).hmac — istemci üretemez; sunucu yazar, sunucu doğrular."""
	govde = (
		base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
		.decode()
		.rstrip("=")
	)  # dolgusuz → çerezde yüzde-kodlama yok
	imza = hmac.new(secret.encode(), govde.encode(), hashlib.sha256).hexdigest()[:32]
	return f"{govde}.{imza}"


def verify_payload(secret: str, raw: str) -> dict | None:
	if not raw or "." not in raw:
		return None
	govde, imza = raw.rsplit(".", 1)
	beklenen = hmac.new(secret.encode(), govde.encode(), hashlib.sha256).hexdigest()[:32]
	if not hmac.compare_digest(beklenen, imza):
		return None
	try:
		dolgu = "=" * (-len(govde) % 4)
		d = json.loads(base64.urlsafe_b64decode((govde + dolgu).encode()).decode())
	except (ValueError, UnicodeDecodeError):
		return None
	return d if isinstance(d, dict) else None


def _secret() -> str:
	import frappe
	from frappe.utils.password import get_encryption_key

	return str(get_encryption_key() or frappe.local.conf.get("secret") or "")


def fields_from_payload(p: dict) -> dict:
	return {
		"seo_landing_path": p.get("path") or "",
		"seo_referrer": p.get("ref") or "",
		"seo_utm_source": p.get("utm_source") or "",
		"seo_utm_medium": p.get("utm_medium") or "",
		"seo_utm_campaign": p.get("utm_campaign") or "",
		"seo_is_organic": int(bool(p.get("organic"))),
		"seo_landing_lang": p.get("lang") or "",
	}


# ── Frappe tarafı ─────────────────────────────────────────────────────────


def record_landing(
	path: str = "/",
	referrer: str = "",
	utm_source: str = "",
	utm_medium: str = "",
	utm_campaign: str = "",
	lang: str = "",
) -> dict:
	"""Guest uç: iniş bilgisini çereze yaz (ilk iniş kazanır — mevcut çerez varsa üzerine yazmaz)."""
	import frappe

	mevcut = frappe.request.cookies.get(COOKIE) if getattr(frappe, "request", None) else None
	if mevcut:
		return {"recorded": False, "reason": "existing"}
	p = landing_payload(
		path,
		referrer or (frappe.request.headers.get("Referer", "") if getattr(frappe, "request", None) else ""),
		{"utm_source": utm_source, "utm_medium": utm_medium, "utm_campaign": utm_campaign},
		lang,
	)
	frappe.local.cookie_manager.set_cookie(
		COOKIE, sign_payload(_secret(), p), max_age=COOKIE_DAYS * 86400, samesite="Lax", httponly=True
	)
	return {"recorded": True, "organic": bool(p["organic"])}


def _cookie_payload() -> dict | None:
	import frappe

	req = getattr(frappe.local, "request", None)
	raw = req.cookies.get(COOKIE) if req is not None and getattr(req, "cookies", None) else None
	if not raw:
		return None
	return verify_payload(_secret(), raw)  # imzasız/bozuk çerez → yok sayılır


def on_conversion_insert(doc, method=None):
	"""RFQ / Seller Inquiry / Order after_insert — iniş bilgisini kayda damgala (alan yoksa sessiz geç)."""
	import frappe

	p = _cookie_payload()
	if not p:
		return
	alanlar = fields_from_payload(p)
	meta = frappe.get_meta(doc.doctype)
	guncelle = {k: v for k, v in alanlar.items() if meta.has_field(k)}
	if guncelle:
		frappe.db.set_value(doc.doctype, doc.name, guncelle, update_modified=False)


def rollup_daily(day: date | None = None) -> dict:
	"""Günün dönüşümlerini organik/tümü olarak boyutlara topla → SEO Metric Snapshot (analytics)."""
	import frappe
	from frappe.utils import add_days, getdate, nowdate

	from tradehub_core.seo_helper.board import write_snapshot
	from tradehub_core.seo_helper.crawler.botlog import page_type_of

	gun = getdate(day or add_days(nowdate(), -1))
	toplam: dict[tuple[str, str, str], float] = {}
	for dt, kisa in CONVERSION_DOCTYPES.items():
		if not frappe.db.exists("DocType", dt) or not frappe.get_meta(dt).has_field("seo_is_organic"):
			continue
		alanlar = ["name", "seo_is_organic", "seo_landing_path", "seo_landing_lang"]
		if frappe.get_meta(dt).has_field("seller"):
			alanlar.append("seller")
		rows = frappe.get_all(
			dt,
			filters={"creation": ["between", [f"{gun} 00:00:00", f"{gun} 23:59:59"]]},
			fields=alanlar,
			limit_page_length=100000,
		)
		for r in rows:
			org = bool(r.get("seo_is_organic"))
			for dim, key in (
				("all", "all"),
				("page_type", page_type_of(r.get("seo_landing_path") or "")),
				("store", r.get("seller") or "-"),
				("lang", r.get("seo_landing_lang") or "-"),
			):
				toplam[(dim, key, f"{kisa}_total")] = toplam.get((dim, key, f"{kisa}_total"), 0) + 1
				if org:
					toplam[(dim, key, f"{kisa}_organic")] = toplam.get((dim, key, f"{kisa}_organic"), 0) + 1
	for (dim, key, metric), v in toplam.items():
		write_snapshot(gun, "analytics", dim, key, metric, float(v))
	org_toplam = sum(v for (dim, key, m), v in toplam.items() if dim == "all" and m.endswith("_organic"))
	write_snapshot(gun, "analytics", "all", "all", "organic_conversions", float(org_toplam))
	return {"day": gun.isoformat(), "metrics": len(toplam), "organic_conversions": org_toplam}

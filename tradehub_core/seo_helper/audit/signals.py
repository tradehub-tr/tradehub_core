"""662 §2 — Var olan sinyalleri (SEO 404 Log, medya SEO denetimi, bot günlüğü engelleri) crawler/GSC
bulgularından AYRI etiketle denetim raporuna al. Her kaynak kendi `signal_source` değeriyle yazılır;
tekilleştirme parmak iziyle (aynı 404 yolu tekrar edince kayıt çoğalmaz, `occurrences` artar).

Kaynaklar:
- `notfound_log`  → `SEO 404 Log` (tradehub_core; çözülmemiş yollar)
- `media`         → `tradehub_core.media.seo_audit.audit_batch` (görsel alt/başlık/optimizasyon)
- `log`           → `SEO Bot Visit` blocked=1 (bot engelleri: 401/403/429/503)
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, nowdate

from tradehub_core.seo_helper.audit import reporter, rules

MEDIA_SEVERITY = {"error": "error", "warn": "warning", "warning": "warning", "info": "info"}


def _site() -> str:
	from tradehub_core.seo_helper.adapters.tradehub.meta import site_url

	return site_url().rstrip("/")


def import_404_log(days: int = 30, min_hits: int = 1, limit: int = 2000) -> dict:
	"""Çözülmemiş 404 yolları → `NOTFOUND_LOG_HIT` (kaynak notfound_log). Kanıt: istek sayısı, son istek, yönlendiren."""
	if not frappe.db.exists("DocType", "SEO 404 Log"):
		return {"source": "notfound_log", "rows": 0, "skipped": "doctype yok"}
	site = _site()
	rows = frappe.get_all(
		"SEO 404 Log",
		filters={"resolved": 0, "last_hit_at": [">=", add_days(nowdate(), -int(days))]},
		fields=["name", "path", "hit_count", "first_seen_at", "last_hit_at", "last_referer"],
		order_by="hit_count desc",
		limit_page_length=int(limit),
	)
	bulgular = []
	for r in rows:
		hits = int(r.hit_count or 0)
		if hits < int(min_hits):
			continue
		yol = "/" + (r.path or "").lstrip("/")
		bulgular.append(
			rules.finding(
				"NOTFOUND_LOG_HIT",
				"technical",
				"error" if hits >= 10 else "warning",
				f"404 günlüğü: {hits} istek",
				url=f"{site}{yol}",
				evidence={
					"_key": "404log",
					"hits": hits,
					"first_seen_at": str(r.first_seen_at or ""),
					"last_hit_at": str(r.last_hit_at or ""),
					"last_referer": r.last_referer or "",
					"log": r.name,
				},
				root_cause="Silinmiş/taşınmış route hâlâ isteniyor (site içi bağlantı ya da dış kaynak)",
				recommendation="Hedef biliniyorsa 301 tanımla (SEO 404 Kayıtları → yönlendirme), yoksa sitemap/bağlantıyı düşür",
			)
		)
	for b in bulgular:
		b["signal_source"] = "notfound_log"
		b["fingerprint"] = rules.fingerprint(b)
	y = reporter.upsert_findings(bulgular, crawl_run=None, signal_source="notfound_log") if bulgular else {}
	return {
		"source": "notfound_log",
		"rows": len(bulgular),
		**{k: v for k, v in y.items() if k != "fingerprints"},
	}


def import_media_audit(limit: int = 200, deep: bool = False, urls: list[str] | None = None) -> dict:
	"""Medya SEO denetimi bulguları → `MEDIA_<KOD>` (kaynak media). Yalnız herkese açık görseller
	(`urls` verilirse yalnız onlar — test/elle seçim)."""
	try:
		from tradehub_core.media import seo_audit
	except ImportError:  # pragma: no cover — medya modülü yoksa sinyal yok
		return {"source": "media", "rows": 0, "skipped": "medya modülü yok"}
	urls = urls or frappe.get_all(
		"File",
		filters={"is_private": 0, "file_url": ["like", "/files/%"]},
		pluck="file_url",
		order_by="modified desc",
		limit_page_length=int(limit),
	)
	urls = [
		u
		for u in urls
		if u and u.lower().rsplit(".", 1)[-1] in ("jpg", "jpeg", "png", "webp", "avif", "gif", "svg")
	]
	if not urls:
		return {"source": "media", "rows": 0}
	r = seo_audit.audit_batch(urls, deep=bool(deep))
	site = _site()
	bulgular = []
	for f in r.get("files") or []:
		for b in f.get("findings") or []:
			kod = str(b.get("code") or "").upper()
			if not kod:
				continue
			bulgular.append(
				rules.finding(
					f"MEDIA_{kod}",
					"content",
					MEDIA_SEVERITY.get(str(b.get("severity") or "info").lower(), "info"),
					f"Medya: {b.get('message') or kod}",
					url=f"{site}{f.get('file_url')}",
					evidence={
						"_key": f"media:{kod}",
						"detail": b.get("detail") or "",
						"score": (f.get("score") or {}).get("overall"),
					},
					root_cause="Görsel meta verisi eksik/uyumsuz (medya SEO denetimi)",
					recommendation="Medya Kütüphanesi → SEO sekmesinden alt/başlık/optimizasyon düzelt",
				)
			)
	for b in bulgular:
		b["signal_source"] = "media"
		b["fingerprint"] = rules.fingerprint(b)
	y = reporter.upsert_findings(bulgular, crawl_run=None, signal_source="media") if bulgular else {}
	return {
		"source": "media",
		"files": len(urls),
		"rows": len(bulgular),
		**{k: v for k, v in y.items() if k != "fingerprints"},
	}


def import_bot_blocks(days: int = 7) -> dict:
	"""Bot günlüğündeki engeller (401/403/429/503) → `BOT_BLOCKED` (kaynak log)."""
	site = _site()
	rows = frappe.db.sql(
		"""select path, bot, status_code, sum(hits) as hits, max(day) as last_day
		from `tabSEO Bot Visit` where blocked=1 and day >= %s group by path, bot, status_code""",
		(add_days(nowdate(), -int(days)),),
		as_dict=True,
	)
	bulgular = []
	for r in rows:
		bulgular.append(
			rules.finding(
				"BOT_BLOCKED",
				"technical",
				"error" if int(r.status_code or 0) in (403, 503) else "warning",
				f"{r.bot} {r.status_code} aldı ({int(r.hits or 0)} istek)",
				url=f"{site}{r.path}",
				evidence={
					"_key": f"botblock:{r.bot}:{r.status_code}",
					"bot": r.bot,
					"status": int(r.status_code or 0),
					"hits": int(r.hits or 0),
					"last_day": str(r.last_day),
				},
				root_cause="Sunucu/WAF/hız sınırı botu engelliyor ya da sayfa yetki istiyor",
				recommendation="Engel kuralını ve sayfanın indekslenebilirliğini kontrol et",
			)
		)
	for b in bulgular:
		b["signal_source"] = "log"
		b["fingerprint"] = rules.fingerprint(b)
	y = reporter.upsert_findings(bulgular, crawl_run=None, signal_source="log") if bulgular else {}
	return {"source": "log", "rows": len(bulgular), **{k: v for k, v in y.items() if k != "fingerprints"}}


def import_all(kind: str = "all") -> dict:
	out: dict = {}
	if kind in ("all", "notfound_log"):
		out["notfound_log"] = import_404_log()
	if kind in ("all", "media"):
		out["media"] = import_media_audit()
	if kind in ("all", "log"):
		out["log"] = import_bot_blocks()
	return out


def daily_import() -> dict:
	"""Zamanlayıcı (günlük): var olan sinyalleri denetim raporuna al."""
	r = import_all("all")
	frappe.db.commit()
	return r

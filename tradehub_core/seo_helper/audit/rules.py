"""13.4 Denetim kuralları — saf. Beş kategori: technical · content · catalog · international · merchant.

Girdi bir "olgu" sözlüğüdür (`facts`): tarama sonucu (`crawl`), SEO Page (`page`), politika
kararı (`policy`), küme (`cluster`), katalog varlığı (`entity`), merchant eşlemesi (`merchant`).
Her bulgu: code, category, severity, message, url, evidence, root_cause, owner_role, recommendation.
`fingerprint()` tekilleştirme anahtarıdır: kategori + kod + url + kanıt anahtarı (değişmeyen kısım).
"""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit

SEVERITIES = ("info", "warning", "error")
CATEGORIES = ("technical", "content", "catalog", "international", "merchant", "policy")
OWNER = {
	"technical": "SEO Manager",
	"content": "SEO Editor",
	"catalog": "Mağaza",
	"international": "SEO Manager",
	"merchant": "Mağaza",
	"policy": "SEO Manager",
}
SLOW_MS = 2500
THIN_WORDS = 120


def _s(v) -> str:
	"""Güvenilmeyen girdi → metin (None/koleksiyon/bool → boş; NUL temizlenir)."""
	if v is None or isinstance(v, bool | list | dict | tuple | set):
		return ""
	if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
		return ""
	return str(v).replace("\x00", "").strip()


def _i(v, default: int = 0) -> int:
	if isinstance(v, bool):
		return int(v)
	try:
		f = float(v)
		if f != f or f in (float("inf"), float("-inf")):
			return default
		return int(f)
	except (TypeError, ValueError, OverflowError):
		return default


def _d(v) -> dict:
	return v if isinstance(v, dict) else {}


def _l(v) -> list:
	return list(v) if isinstance(v, list | tuple) else []


def _truthy(v) -> bool:
	return bool(_i(v)) if not isinstance(v, str) else v.strip().lower() in ("1", "true", "yes", "evet")


def finding(
	code,
	category,
	severity,
	message,
	*,
	url="",
	evidence=None,
	root_cause="",
	recommendation="",
	owner_role=None,
):
	assert category in CATEGORIES and severity in SEVERITIES
	return {
		"code": code,
		"category": category,
		"severity": severity,
		"message": message,
		"url": url or "",
		"evidence": evidence or {},
		"root_cause": root_cause,
		"owner_role": owner_role or OWNER[category],
		"recommendation": recommendation,
	}


def fingerprint(f: dict) -> str:
	sabit = _d(f.get("evidence")).get("_key", "")
	return hashlib.sha1(
		f"{f['category']}|{f['code']}|{_s(f.get('url', ''))}|{_s(sabit)}".encode()
	).hexdigest()[:20]


def _host(u: str) -> str:
	return urlsplit(u or "").netloc.lower()


# ── teknik ───────────────────────────────────────────────────────────────


def _norm_crawl(c) -> dict:
	"""Tarama olgularını tipli hâle getir (DB satırı ya da güvenilmeyen sözlük)."""
	c = _d(c)
	if not c:
		return {}
	return {
		"url": _s(c.get("url")),
		"status_code": _i(c.get("status_code")),
		"title": _s(c.get("title")),
		"meta_description": _s(c.get("meta_description")),
		"canonical": _s(c.get("canonical")),
		"robots_meta": _s(c.get("robots_meta")),
		"final_url": _s(c.get("final_url")),
		"error": _s(c.get("error")),
		"html_lang": _s(c.get("html_lang")),
		"h1_count": _i(c.get("h1_count")),
		"word_count": _i(c.get("word_count")),
		"images_without_alt": _i(c.get("images_without_alt")),
		"response_ms": _i(c.get("response_ms")),
		"needs_js": _truthy(c.get("needs_js")),
		"robots_blocked": _truthy(c.get("robots_blocked")),
		"redirect_chain": _l(c.get("redirect_chain")),
		"hreflang": [h for h in _l(c.get("hreflang")) if isinstance(h, dict)],
		"json_ld_types": [_s(t) for t in _l(c.get("json_ld_types"))],
	}


def _norm_page(p) -> dict | None:
	p = _d(p)
	if not p:
		return None
	return {
		**p,
		"effective_canonical": _s(p.get("effective_canonical")),
		"effective_robots": _s(p.get("effective_robots")),
		"indexable": _truthy(p.get("indexable")),
		"lang": _s(p.get("lang")),
	}


def normalize(facts) -> dict:
	facts = _d(facts)
	return {
		**facts,
		"url": _s(facts.get("url")),
		"crawl": _norm_crawl(facts.get("crawl")),
		"page": _norm_page(facts.get("page")),
		"cluster": _d(facts.get("cluster")) or None,
		"entity": _d(facts.get("entity")) or None,
		"merchant": (facts.get("merchant") if isinstance(facts.get("merchant"), dict) else None),
		"reciprocal_missing": [_s(x) for x in _l(facts.get("reciprocal_missing")) if _s(x)],
		"duplicate_titles": [_s(x) for x in _l(facts.get("duplicate_titles")) if _s(x)],
	}


def technical(facts: dict) -> list[dict]:
	facts = normalize(facts)
	c = facts.get("crawl") or {}
	url = c.get("url") or facts.get("url", "")
	out = []
	if not c:
		return out
	st = int(c.get("status_code") or 0)
	if c.get("robots_blocked"):
		out.append(
			finding(
				"ROBOTS_BLOCKED",
				"technical",
				"error",
				"Sayfa robots.txt ile engelli",
				url=url,
				evidence={"_key": "robots"},
				root_cause="robots.txt disallow kuralı bu yolu kapsıyor",
				recommendation="Sayfa indekslenmeliyse robots.txt kuralını daralt",
			)
		)
		return out
	if c.get("error") and not st:
		out.append(
			finding(
				"FETCH_ERROR",
				"technical",
				"error",
				f"Alınamadı: {c['error'][:120]}",
				url=url,
				evidence={"_key": "fetch", "error": c["error"]},
				root_cause="Ağ/sunucu hatası ya da zaman aşımı",
				recommendation="Sunucu günlüğüne bak; yanıt süresini ölç",
			)
		)
		return out
	if st >= 500:
		out.append(
			finding(
				"HTTP_5XX",
				"technical",
				"error",
				f"Sunucu hatası {st}",
				url=url,
				evidence={"_key": "5xx", "status": st},
				root_cause="Uygulama/sunucu hatası",
				recommendation="Error Log'u incele; sayfa botlara da 5xx dönüyor olabilir",
			)
		)
	elif st == 404 or st == 410:
		out.append(
			finding(
				"HTTP_404",
				"technical",
				"error",
				f"Sayfa yok ({st})",
				url=url,
				evidence={"_key": "404", "status": st},
				root_cause="Route silinmiş/yayından kalkmış ama hâlâ isteniyor",
				recommendation="301 yönlendirme tanımla ya da sitemap'ten düşür",
			)
		)
	elif st in (401, 403):
		out.append(
			finding(
				"HTTP_FORBIDDEN",
				"technical",
				"error",
				f"Erişim reddi ({st})",
				url=url,
				evidence={"_key": "403", "status": st},
				root_cause="Kimlik/yetki gerektiren sayfa indekslenebilir işaretli",
				recommendation="Sayfayı noindex yap ya da erişimi aç",
			)
		)
	elif 300 <= st < 400:
		out.append(
			finding(
				"REDIRECT_UNRESOLVED",
				"technical",
				"warning",
				f"Yönlendirme çözülmedi ({st})",
				url=url,
				evidence={"_key": "3xx", "status": st},
				root_cause="Yönlendirme döngüsü ya da fazla zincir",
				recommendation="Hedefi doğrudan ver",
			)
		)
	zincir = c.get("redirect_chain") or []
	if len(zincir) >= 2:
		out.append(
			finding(
				"REDIRECT_CHAIN",
				"technical",
				"warning",
				f"{len(zincir)} adımlı yönlendirme zinciri",
				url=url,
				evidence={"_key": "chain", "chain": zincir},
				root_cause="Eski yönlendirmeler üst üste binmiş",
				recommendation="İlk adımı son hedefe bağla",
			)
		)
	if st == 200:
		final = c.get("final_url") or url
		if final and _host(final) and url and _host(url) and _host(final) != _host(url):
			out.append(
				finding(
					"HOST_MISMATCH",
					"technical",
					"warning",
					"Yönlendirme başka hosta gidiyor",
					url=url,
					evidence={"_key": "host", "final_url": final},
					root_cause="Kanonik host tutarsız",
					recommendation="Tek kanonik host kullan",
				)
			)
		if c.get("needs_js") and c.get("rendered_with") != "js":
			out.append(
				finding(
					"NEEDS_JS_RENDER",
					"technical",
					"warning",
					"HTML kabuğu boş; içerik JavaScript ile geliyor, render yapılamadı",
					url=url,
					evidence={"_key": "js", "word_count": c.get("word_count")},
					root_cause="SPA sayfası; JS render komutu tanımlı değil ya da başarısız",
					recommendation="Sunucu tarafı render/prerender ekle ya da Settings'te JS render komutunu tanımla",
				)
			)
		if (c.get("response_ms") or 0) > SLOW_MS:
			out.append(
				finding(
					"SLOW_RESPONSE",
					"technical",
					"warning",
					f"Yavaş yanıt {c['response_ms']} ms",
					url=url,
					evidence={"_key": "slow", "response_ms": c["response_ms"]},
					root_cause="Sunucu/DB gecikmesi ya da ağır sayfa",
					recommendation="Cache ve sorgu sayısını ölç (rapor 666)",
				)
			)
		can = (c.get("canonical") or "").strip()
		bekl = (facts.get("page") or {}).get("effective_canonical") or ""
		if not can and not c.get("needs_js"):
			out.append(
				finding(
					"CANONICAL_MISSING",
					"technical",
					"warning",
					"Canonical etiketi yok",
					url=url,
					evidence={"_key": "canonical"},
					root_cause="Head üreticisi bu sayfayı kapsamıyor",
					recommendation="Tek head üreticisine bağla (4.3)",
				)
			)
		elif can and bekl and can.rstrip("/") != bekl.rstrip("/"):
			out.append(
				finding(
					"CANONICAL_MISMATCH",
					"technical",
					"error",
					"Canonical politika sonucundan farklı",
					url=url,
					evidence={"_key": "canonical", "html": can, "expected": bekl},
					root_cause="Şablon/Builder canonical'ı politika çıktısını eziyor",
					recommendation="Builder canonical alanını politika çıktı yuvası olarak kullan (663)",
				)
			)
		rb = (c.get("robots_meta") or "").replace(" ", "").lower()
		ist = ((facts.get("page") or {}).get("effective_robots") or "").replace(" ", "").lower()
		if rb and ist and rb != ist:
			out.append(
				finding(
					"ROBOTS_MISMATCH",
					"technical",
					"error",
					f"Robots meta '{rb}' ≠ politika '{ist}'",
					url=url,
					evidence={"_key": "robots", "html": rb, "expected": ist},
					root_cause="İkinci bir robots üreticisi var",
					recommendation="Tek robots kaynağı; çift etiketi kaldır",
				)
			)
		if (facts.get("page") or {}).get("indexable") and "noindex" in rb:
			out.append(
				finding(
					"INDEXABLE_BUT_NOINDEX",
					"technical",
					"error",
					"İndekslenebilir sayfa noindex basıyor",
					url=url,
					evidence={"_key": "noindex", "html": rb},
					root_cause="Ortam/politika uyuşmazlığı (prod dışı robots?)",
					recommendation="Ortam çözümünü ve politika kararını karşılaştır",
				)
			)
	return out


# ── içerik ───────────────────────────────────────────────────────────────


def content(facts: dict, *, min_title: int = 10, min_desc: int = 50) -> list[dict]:
	facts = normalize(facts)
	min_title, min_desc = _i(min_title, 10), _i(min_desc, 50)
	c = facts.get("crawl") or {}
	url = c.get("url") or facts.get("url", "")
	out = []
	if not c or int(c.get("status_code") or 0) != 200 or c.get("needs_js"):
		return out
	t = (c.get("title") or "").strip()
	d = (c.get("meta_description") or "").strip()
	if not t:
		out.append(
			finding(
				"TITLE_MISSING",
				"content",
				"error",
				"Başlık yok",
				url=url,
				evidence={"_key": "title"},
				root_cause="Sayfa başlığı boş",
				recommendation="Betimleyici başlık yaz",
			)
		)
	elif len(t) < min_title:
		out.append(
			finding(
				"TITLE_SHORT",
				"content",
				"warning",
				f"Başlık kısa ({len(t)})",
				url=url,
				evidence={"_key": "title", "len": len(t)},
				root_cause="Başlık yetersiz",
				recommendation=f"En az {min_title} karakter",
			)
		)
	elif len(t) > 60:
		out.append(
			finding(
				"TITLE_LONG",
				"content",
				"info",
				f"Başlık uzun ({len(t)})",
				url=url,
				evidence={"_key": "title", "len": len(t)},
				root_cause="SERP'te kesilir",
				recommendation="60 karakter altına indir",
			)
		)
	if not d:
		out.append(
			finding(
				"DESC_MISSING",
				"content",
				"warning",
				"Meta açıklama yok",
				url=url,
				evidence={"_key": "desc"},
				root_cause="Açıklama boş",
				recommendation="120–155 karakter açıklama yaz",
			)
		)
	elif len(d) < min_desc:
		out.append(
			finding(
				"DESC_SHORT",
				"content",
				"warning",
				f"Meta açıklama kısa ({len(d)})",
				url=url,
				evidence={"_key": "desc", "len": len(d)},
				root_cause="Açıklama yetersiz",
				recommendation=f"En az {min_desc} karakter",
			)
		)
	h1 = int(c.get("h1_count") or 0)
	if h1 == 0:
		out.append(
			finding(
				"H1_MISSING",
				"content",
				"warning",
				"H1 yok",
				url=url,
				evidence={"_key": "h1"},
				root_cause="Şablon H1 basmıyor",
				recommendation="Tek H1 ekle",
			)
		)
	elif h1 > 1:
		out.append(
			finding(
				"H1_MULTIPLE",
				"content",
				"info",
				f"{h1} adet H1",
				url=url,
				evidence={"_key": "h1", "count": h1},
				root_cause="Bileşenler kendi H1'ini basıyor",
				recommendation="Tek H1, gerisi H2",
			)
		)
	if (c.get("word_count") or 0) < THIN_WORDS:
		out.append(
			finding(
				"THIN_CONTENT",
				"content",
				"warning",
				f"İnce içerik ({c.get('word_count') or 0} kelime)",
				url=url,
				evidence={"_key": "thin", "word_count": c.get("word_count")},
				root_cause="Sayfada yeterli metin yok",
				recommendation=f"En az {THIN_WORDS} kelime betimleyici içerik",
			)
		)
	if (c.get("images_without_alt") or 0) > 0:
		out.append(
			finding(
				"IMG_ALT_MISSING",
				"content",
				"warning",
				f"{c['images_without_alt']} görselde alt yok",
				url=url,
				evidence={"_key": "alt", "count": c["images_without_alt"]},
				root_cause="Medya SEO alt üretimi bu sayfaya bağlı değil",
				recommendation="Medya alt zincirini (620) bağla",
			)
		)
	if "INVALID" in (c.get("json_ld_types") or []):
		out.append(
			finding(
				"JSONLD_INVALID",
				"content",
				"error",
				"Geçersiz JSON-LD",
				url=url,
				evidence={"_key": "jsonld"},
				root_cause="Bozuk yapılandırılmış veri",
				recommendation="JSON-LD'yi doğrula",
			)
		)
	dup = _l(facts.get("duplicate_titles"))
	if dup:
		out.append(
			finding(
				"TITLE_DUPLICATE",
				"content",
				"warning",
				f"Aynı başlık {len(dup)} başka sayfada",
				url=url,
				evidence={"_key": "dup_title", "others": dup[:10]},
				root_cause="Şablon başlığı sayfaya özgü değil",
				recommendation="Başlığı sayfaya özgü yap",
			)
		)
	return out


# ── katalog ──────────────────────────────────────────────────────────────


def catalog(facts: dict) -> list[dict]:
	facts = normalize(facts)
	e = facts.get("entity") or {}
	url = facts.get("url", "")
	out = []
	if not e:
		return out
	if _truthy(e.get("indexable")) and not facts.get("page"):
		out.append(
			finding(
				"ENTITY_WITHOUT_PAGE",
				"catalog",
				"error",
				"İndekslenebilir katalog varlığının SEO sayfası yok",
				url=url,
				evidence={"_key": "mirror", "entity": e.get("name")},
				root_cause="Ayna/senkron işi bu varlığı atlamış",
				recommendation="Uzlaşma işini çalıştır (reconcile)",
				owner_role="SEO Manager",
			)
		)
	if _l(e.get("duplicate_slug")):
		out.append(
			finding(
				"SLUG_DUPLICATE",
				"catalog",
				"error",
				"Aynı slug birden çok varlıkta",
				url=url,
				evidence={"_key": "slug", "others": _l(e.get("duplicate_slug"))[:10]},
				root_cause="Slug üretimi benzersizliği zorlamıyor",
				recommendation="Slug'a ayırt edici ek ver",
			)
		)
	if e.get("entity_type") == "listing" and not _s(e.get("title")):
		out.append(
			finding(
				"LISTING_META_MISSING",
				"catalog",
				"warning",
				"İlanın SEO başlığı yok",
				url=url,
				evidence={"_key": "meta"},
				root_cause="Satıcı SEO alanlarını doldurmamış",
				recommendation="Mağaza panelinden SEO alanlarını doldur",
			)
		)
	if e.get("entity_type") == "listing" and e.get("stock_status") == "out":
		out.append(
			finding(
				"LISTING_OUT_OF_STOCK_INDEXED",
				"catalog",
				"info",
				"Stoksuz ilan indekslenebilir",
				url=url,
				evidence={"_key": "stock"},
				root_cause="Stok durumu indeks politikasına bağlı değil",
				recommendation="Uzun süre stoksuz ilanı noindex yap ya da benzer ürüne yönlendir",
			)
		)
	return out


# ── uluslararası ─────────────────────────────────────────────────────────


def international(facts: dict) -> list[dict]:
	facts = normalize(facts)
	c = facts.get("crawl") or {}
	p = facts.get("page") or {}
	cl = facts.get("cluster") or {}
	url = c.get("url") or facts.get("url", "")
	out = []
	if not p:
		return out
	uyeler = [m for m in _l(cl.get("members")) if isinstance(m, dict)]  # [{lang, route, url}]
	if cl and len(uyeler) >= 2:
		html_hl = {_s(h.get("lang")).lower(): h.get("href") for h in (c.get("hreflang") or [])}
		for m in uyeler:
			lang = _s(m.get("lang")).lower()
			if (
				lang
				and lang not in html_hl
				and not c.get("needs_js")
				and int(c.get("status_code") or 0) == 200
			):
				out.append(
					finding(
						"HREFLANG_MISSING",
						"international",
						"error",
						f"hreflang '{lang}' eksik",
						url=url,
						evidence={"_key": f"hl:{lang}", "cluster": cl.get("key")},
						root_cause="Küme üyesi yayında değil ya da head üretimi kümeyi okumuyor",
						recommendation="Küme üyelerinin yayın durumunu ve head üreticisini kontrol et",
					)
				)
		if html_hl and "x-default" not in html_hl and not c.get("needs_js"):
			out.append(
				finding(
					"HREFLANG_XDEFAULT_MISSING",
					"international",
					"warning",
					"x-default yok",
					url=url,
					evidence={"_key": "xdefault"},
					root_cause="Varsayılan dil işaretlenmemiş",
					recommendation="x-default ekle",
				)
			)
		karsilik = _l(facts.get("reciprocal_missing"))
		for r in karsilik:
			out.append(
				finding(
					"HREFLANG_NO_RETURN",
					"international",
					"error",
					f"{r} karşılık bağlantısı vermiyor",
					url=url,
					evidence={"_key": f"ret:{r}"},
					root_cause="Karşı sayfa kümeyi işaretlemiyor",
					recommendation="Karşı sayfada da hreflang üret",
				)
			)
	if p.get("lang") and c.get("html_lang") and p["lang"].lower()[:2] != str(c["html_lang"]).lower()[:2]:
		out.append(
			finding(
				"LANG_MISMATCH",
				"international",
				"warning",
				f"<html lang='{c['html_lang']}'> ≠ sayfa dili '{p['lang']}'",
				url=url,
				evidence={"_key": "lang", "html_lang": c["html_lang"]},
				root_cause="Şablon dil özniteliği sabit",
				recommendation="html lang'ı sayfa dilinden üret",
			)
		)
	return out


# ── merchant ─────────────────────────────────────────────────────────────


def merchant(facts: dict) -> list[dict]:
	facts = normalize(facts)
	m = facts.get("merchant")
	e = facts.get("entity") or {}
	url = facts.get("url", "")
	out = []
	if m is None:
		return out
	if not m:
		if e.get("entity_type") == "listing":
			out.append(
				finding(
					"MERCHANT_MAP_MISSING",
					"merchant",
					"warning",
					"Mağazanın Merchant eşlemesi yok",
					url=url,
					evidence={"_key": "map", "store": e.get("store")},
					root_cause="Mağaza Merchant Center'a bağlanmamış",
					recommendation="Mağaza için SEO Merchant Map oluştur",
				)
			)
		return out
	if _s(m.get("status")) != "active":
		out.append(
			finding(
				"MERCHANT_MAP_INACTIVE",
				"merchant",
				"warning",
				f"Merchant eşlemesi '{m.get('status')}'",
				url=url,
				evidence={"_key": "status", "status": m.get("status")},
				root_cause="Eşleme askıda/taslak",
				recommendation="Eşlemeyi etkinleştir",
			)
		)
	if not _s(m.get("feed_url")):
		out.append(
			finding(
				"MERCHANT_FEED_MISSING",
				"merchant",
				"error",
				"Feed URL yok",
				url=url,
				evidence={"_key": "feed"},
				root_cause="Feed üretilmemiş",
				recommendation="Ürün feed'ini üret ve adresi kaydet",
			)
		)
	eksik = [
		k
		for k in ("id", "title", "price", "availability", "link", "image_link")
		if k not in _d(m.get("mapping"))
	]
	if eksik:
		out.append(
			finding(
				"MERCHANT_MAPPING_INCOMPLETE",
				"merchant",
				"error",
				f"Zorunlu alanlar eşlenmemiş: {', '.join(eksik)}",
				url=url,
				evidence={"_key": "mapping", "missing": eksik},
				root_cause="Merchant alan eşlemesi eksik",
				recommendation="Eksik alanları eşle",
			)
		)
	if m.get("last_sync_age_days") is not None and _i(m.get("last_sync_age_days")) > 7:
		out.append(
			finding(
				"MERCHANT_SYNC_STALE",
				"merchant",
				"warning",
				f"Son senkron {m['last_sync_age_days']} gün önce",
				url=url,
				evidence={"_key": "sync"},
				root_cause="Senkron işi çalışmıyor",
				recommendation="Merchant senkronunu çalıştır",
			)
		)
	return out


def run_all(facts: dict, *, min_title: int = 10, min_desc: int = 50) -> list[dict]:
	out = (
		technical(facts)
		+ content(facts, min_title=min_title, min_desc=min_desc)
		+ catalog(facts)
		+ international(facts)
		+ merchant(facts)
	)
	for f in out:
		f["fingerprint"] = fingerprint(f)
	return out


def summarize(findings: list[dict]) -> dict:
	by_cat: dict[str, dict[str, int]] = {}
	by_owner: dict[str, int] = {}
	for f in findings:
		by_cat.setdefault(f["category"], {"error": 0, "warning": 0, "info": 0})[f["severity"]] += 1
		by_owner[f.get("owner_role") or "?"] = by_owner.get(f.get("owner_role") or "?", 0) + 1
	return {"total": len(findings), "by_category": by_cat, "by_owner": by_owner}


def to_json(findings: list[dict]) -> str:
	return json.dumps(findings, ensure_ascii=False, default=str)

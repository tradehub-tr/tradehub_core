"""13.2 Bot / sunucu log analizi — saf ayrıştırma + Frappe içe aktarma/karşılaştırma.

Girdi: nginx "combined" satırları (ve Frappe `web.log` ile aynı biçimdeki werkzeug satırları).
Bot tespiti UA sözlüğüyle; isteğe bağlı ters-DNS doğrulaması (Googlebot/Bingbot için resmi yöntem).
Toplulaştırma günlük (gün, bot, host, yol, durum kodu). "Engel" = 403/429 ya da robots ile reddedilen.
"""

from __future__ import annotations

import glob
import gzip
import hashlib
import json
import re
import socket
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlsplit

BOTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
	# (ad, UA deseni (lower), doğrulama için ters DNS son ekleri)
	("googlebot", "googlebot", (".googlebot.com", ".google.com")),
	("google-other", "google-inspectiontool", (".googlebot.com", ".google.com")),
	("adsbot-google", "adsbot-google", (".googlebot.com", ".google.com")),
	("bingbot", "bingbot", (".search.msn.com",)),
	("yandexbot", "yandex", (".yandex.ru", ".yandex.net", ".yandex.com")),
	("duckduckbot", "duckduckbot", (".duckduckgo.com",)),
	("applebot", "applebot", (".applebot.apple.com",)),
	("baiduspider", "baiduspider", (".baidu.com", ".baidu.jp")),
	("yahoo-slurp", "slurp", (".crawl.yahoo.net",)),
	("gptbot", "gptbot", (".openai.com",)),
	("claudebot", "claudebot", (".anthropic.com",)),
	("bytespider", "bytespider", (".bytedance.com",)),
	("ahrefsbot", "ahrefsbot", (".ahrefs.com",)),
	("semrushbot", "semrushbot", (".semrush.com",)),
	("facebookexternalhit", "facebookexternalhit", (".facebook.com",)),
	("petalbot", "petalbot", (".petalsearch.com",)),
)
BLOCK_STATUSES = {401, 403, 429, 503}

_NGINX = re.compile(
	r'^(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] "(?P<method>[A-Z]+) (?P<path>\S+)(?: HTTP/[\d.]+)?" '
	r'(?P<status>\d{3}) (?P<bytes>\d+|-)(?: "(?P<ref>[^"]*)" "(?P<ua>[^"]*)")?'
)
_WERKZEUG = re.compile(
	r'^(?P<ip>\S+) - - \[(?P<ts>[^\]]+)\] "(?P<method>[A-Z]+) (?P<path>\S+) HTTP/[\d.]+" (?P<status>\d{3}) (?P<bytes>\S+)'
)
_TS_FORMATS = ("%d/%b/%Y:%H:%M:%S %z", "%d/%b/%Y:%H:%M:%S", "%d/%b/%Y %H:%M:%S")


def classify_bot(ua: str) -> str | None:
	u = (ua or "").lower()
	if not u:
		return None
	for ad, desen, _ in BOTS:
		if desen in u:
			return ad
	return None


def _ts(raw: str) -> datetime | None:
	for f in _TS_FORMATS:
		try:
			d = datetime.strptime(raw, f)
			return d.replace(tzinfo=None) if d.tzinfo is None else d.astimezone().replace(tzinfo=None)
		except ValueError:
			continue
	return None


def parse_line(line: str) -> dict | None:
	"""Tek satır → {ip, ts, method, path, status, bytes, ref, ua}; anlaşılmazsa None."""
	m = _NGINX.match(line or "") or _WERKZEUG.match(line or "")
	if not m:
		return None
	d = m.groupdict()
	ts = _ts(d["ts"])
	if ts is None:
		return None
	try:
		status = int(d["status"])
	except (TypeError, ValueError):
		return None
	b = d.get("bytes")
	return {
		"ip": d["ip"],
		"ts": ts,
		"method": d["method"],
		"path": urlsplit(d["path"]).path or "/",
		"status": status,
		"bytes": int(b) if b and b.isdigit() else 0,
		"ref": d.get("ref") or "",
		"ua": d.get("ua") or "",
	}


def verify_bot_ip(ip: str, bot: str, *, resolver=None) -> bool:
	"""Ters DNS → ileri DNS eşleşmesi (resmi doğrulama). resolver(ip) -> hostname (test için)."""
	sonekler = next((s for ad, _, s in BOTS if ad == bot), ())
	if not sonekler:
		return False
	try:
		host = resolver(ip) if resolver else socket.gethostbyaddr(ip)[0]
	except Exception:  # noqa: BLE001 — çözülmeyen ip doğrulanmamış sayılır
		return False
	host = (host or "").lower().rstrip(".")
	if not any(host.endswith(s) for s in sonekler):
		return False
	if resolver:
		return True
	try:
		return ip in {a[4][0] for a in socket.getaddrinfo(host, None)}
	except Exception:  # noqa: BLE001
		return False


def aggregate(records, *, host: str = "", verify: bool = False, resolver=None) -> dict[str, dict]:
	"""Kayıtları (gün, bot, host, yol, durum) anahtarıyla topla; yalnız bot UA'ları."""
	out: dict[str, dict] = {}
	dogrulama: dict[tuple[str, str], bool] = {}
	for r in records:
		bot = classify_bot(r.get("ua", ""))
		if not bot:
			continue
		gun = r["ts"].date().isoformat()
		dogru = False
		if (
			verify
		):  # doğrulanmış ve sahte (UA taklidi) istekler AYRI satırlarda: 'gerçek bot ziyaretleri' karışmaz
			k = (r["ip"], bot)
			if k not in dogrulama:
				dogrulama[k] = verify_bot_ip(r["ip"], bot, resolver=resolver)
			dogru = dogrulama[k]
		key = dedupe_key(gun, bot, host, r["path"], r["status"], verified=dogru)
		row = out.get(key)
		if row is None:
			row = out[key] = {
				"day": gun,
				"bot": bot,
				"host": host,
				"path": r["path"],
				"status_code": r["status"],
				"hits": 0,
				"bytes": 0,
				"blocked": r["status"] in BLOCK_STATUSES,
				"first_observed": r["ts"],
				"last_observed": r["ts"],
				"verified": dogru,
				"dedupe_key": key,
			}
		row["hits"] += 1
		row["bytes"] += r.get("bytes", 0) or 0
		row["first_observed"] = min(row["first_observed"], r["ts"])
		row["last_observed"] = max(row["last_observed"], r["ts"])
	return out


def dedupe_key(day: str, bot: str, host: str, path: str, status: int, *, verified: bool = False) -> str:
	# doğrulanmamış satır anahtarı eski biçimle aynı (geriye uyumlu); doğrulanmış satır ayrı anahtar
	ek = "|v" if verified else ""
	return hashlib.sha1(f"{day}|{bot}|{host}|{path}|{status}{ek}".encode()).hexdigest()[:24]


def parse_text(text) -> tuple[list[dict], int]:
	"""Metin (ya da satır yineleyicisi) → kayıt listesi + atlanan satır sayısı."""
	kayitlar, atlanan = [], 0
	satirlar = text.splitlines() if isinstance(text, str) else (text or [])
	for line in satirlar:
		if not line.strip():
			continue
		r = parse_line(line)
		if r is None:
			atlanan += 1
		else:
			kayitlar.append(r)
	return kayitlar, atlanan


def compare_coverage(requested: set[str], crawled: dict[str, int]) -> dict:
	"""İstenen (indekslenebilir) yollar ile fiilen taranan yollar (yol → istek) karşılaştırması."""
	istenen = {p for p in requested if p}
	taranan = {p: n for p, n in crawled.items() if p}
	kesisim = istenen & set(taranan)
	return {
		"requested": len(istenen),
		"crawled": len(taranan),
		"both": len(kesisim),
		"requested_not_crawled": sorted(istenen - set(taranan)),
		"crawled_not_requested": sorted(set(taranan) - istenen),
		"coverage_pct": round(100.0 * len(kesisim) / len(istenen), 1) if istenen else 0.0,
		"hits_on_requested": sum(taranan[p] for p in kesisim),
		"hits_wasted": sum(n for p, n in taranan.items() if p not in istenen),
	}


def page_type_of(path: str) -> str:
	p = (path or "/").lower()
	for onek, tur in (
		("/urun", "listing"),
		("/kategori", "category"),
		("/marka", "brand"),
		("/magaza", "seller"),
	):
		if p.startswith(onek + "/") or p == onek:
			return tur
	if p in ("/", ""):
		return "home"
	if p.startswith(("/sitemap", "/robots")):
		return "system"
	return "page"


# ── Frappe tarafı ─────────────────────────────────────────────────────────


def import_text(text: str, *, host: str = "", verify: bool | None = None) -> dict:
	"""Log metnini `SEO Bot Visit`'e (upsert, set semantiği → yeniden içe aktarma güvenli) yaz."""
	import frappe

	s = frappe.get_cached_doc("SEO Helper Settings")
	verify = bool(s.bot_verify_dns) if verify is None else verify
	kayitlar, atlanan = parse_text(text)
	toplu = aggregate(kayitlar, host=host, verify=verify)
	yazilan = 0
	for key, row in toplu.items():
		mevcut = frappe.db.get_value("SEO Bot Visit", {"dedupe_key": key}, "name")
		veri = {**row, "first_observed": row["first_observed"], "last_observed": row["last_observed"]}
		if mevcut:
			frappe.db.set_value("SEO Bot Visit", mevcut, veri, update_modified=True)
		else:
			frappe.get_doc({"doctype": "SEO Bot Visit", **veri}).insert(ignore_permissions=True)
		yazilan += 1
	frappe.db.set_value("SEO Helper Settings", None, "bot_log_last_import_at", frappe.utils.now_datetime())
	return {
		"lines": len(kayitlar),
		"skipped": atlanan,
		"rows": yazilan,
		"bots": sorted({r["bot"] for r in toplu.values()}),
	}


def import_scheduled() -> dict:
	"""Günlük: Settings `bot_log_path` glob'undaki dosyaları içe aktar + saklama süresi dışını sil."""
	import frappe
	from frappe.utils import add_to_date, now_datetime

	s = frappe.get_cached_doc("SEO Helper Settings")
	sonuc = {"files": 0, "rows": 0, "purged": 0}
	if s.bot_log_path:
		for yol in sorted(glob.glob(s.bot_log_path)):
			acici = gzip.open if yol.endswith(".gz") else open  # döndürülmüş loglar (access.log.2.gz)
			try:
				with acici(
					yol, mode="rt", encoding="utf-8", errors="replace"
				) as f:  # satır satır: belleğe alınmaz
					r = import_text(f, host=frappe.local.site)
				sonuc["files"] += 1
				sonuc["rows"] += r["rows"]
			except OSError as e:
				frappe.log_error(title="seo_helper bot log", message=f"{yol}: {e}")
	esik = add_to_date(now_datetime(), days=-int(s.bot_log_retention_days or 90))
	eski = frappe.get_all(
		"SEO Bot Visit", filters={"day": ["<", esik.date()]}, pluck="name", limit_page_length=5000
	)
	for n in eski:
		frappe.delete_doc("SEO Bot Visit", n, force=True, ignore_permissions=True)
	sonuc["purged"] = len(eski)
	frappe.db.commit()
	return sonuc


def requested_paths(*, wait: bool = True) -> tuple[set[str], bool]:
	"""İstenen sayfalar: yayında + indekslenebilir SEO Page route'ları + tradehub sitemap yolları.
	`wait=False` (panel): sitemap önbellekte yoksa üretim kuyruğa atılır ve yalnız SEO Page'ler döner —
	ikinci değer `partial=True` (kapsam sınırı açıkça raporlanır; HTTP isteği 25 s bloklanmaz)."""
	import frappe

	yollar = set(
		frappe.get_all(
			"SEO Page",
			filters={"publish_state": "published", "indexable": 1},
			pluck="route",
			limit_page_length=50000,
		)
	)
	partial = False
	try:
		from tradehub_core.seo_helper.adapters.tradehub import sitemap as sm

		urls = sm.all_urls() if wait else sm.cached_urls()
		if urls is None:
			partial = True
			sm.warm_urls_async()
			urls = []
		for u in urls:
			yollar.add(urlsplit(u).path or "/")
	except Exception:  # noqa: BLE001 — sitemap okunamazsa yalnız SEO Page'ler (kısmi)
		frappe.log_error(title="seo_helper requested_paths", message=frappe.get_traceback())
		partial = True
	return yollar, partial


def coverage(days: int = 7, *, wait: bool = True) -> dict:
	"""İstenen ↔ taranan karşılaştırması + sayfa türü / bot bazlı sıklık ve engeller.
	`partial=True` → sitemap henüz hazır değil (arka planda üretiliyor), istenen küme yalnız SEO Page'ler."""
	import frappe
	from frappe.utils import add_to_date, nowdate

	baslangic = add_to_date(nowdate(), days=-int(days))
	rows = frappe.get_all(
		"SEO Bot Visit",
		filters={"day": [">=", baslangic]},
		fields=["bot", "path", "status_code", "hits", "blocked", "verified"],
		limit_page_length=100000,
	)
	taranan: dict[str, int] = defaultdict(int)
	bot_sayim: dict[str, int] = defaultdict(int)
	tur_sayim: dict[str, int] = defaultdict(int)
	durum: dict[str, int] = defaultdict(int)
	engel = 0
	dogrulanmamis = 0
	for r in rows:
		taranan[r.path] += int(r.hits or 0)
		bot_sayim[r.bot] += int(r.hits or 0)
		tur_sayim[page_type_of(r.path)] += int(r.hits or 0)
		durum[str(r.status_code)] += int(r.hits or 0)
		if r.blocked:
			engel += int(r.hits or 0)
		if not r.verified:
			dogrulanmamis += int(r.hits or 0)
	istenen, partial = requested_paths(wait=wait)
	k = compare_coverage(istenen, dict(taranan))
	k.update(
		{
			"days": days,
			"partial": partial,
			"partial_reason": "sitemap_pending" if partial else "",
			"bots": dict(sorted(bot_sayim.items(), key=lambda kv: -kv[1])),
			"page_types": dict(tur_sayim),
			"status_codes": dict(durum),
			"blocked_hits": engel,
			"unverified_hits": dogrulanmamis,
			"requested_not_crawled": k["requested_not_crawled"][:200],
			"crawled_not_requested": k["crawled_not_requested"][:200],
		}
	)
	return json.loads(json.dumps(k, default=str))

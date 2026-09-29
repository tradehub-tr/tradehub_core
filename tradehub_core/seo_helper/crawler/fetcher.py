"""13.1 HTTP/HTML taraması + gerektiğinde JavaScript render.

- `Fetcher.fetch(url)` → `FetchResult` (durum, yönlendirme zinciri, süre, bayt, html, hata, robots engeli).
- `parse_html(html, base_url)` → head/içerik olguları (title, description, canonical, robots, h1,
  hreflang, iç bağlantı, JSON-LD tipleri, alt'sız görsel, kelime sayısı, içerik özeti).
- `needs_js(parsed, html)` → SPA kabuğu sezgisi (gövde boş + script paketi / bilinen kabuk imzaları).
- `JsRenderer(command)` → dış komutla render (`{url}` yer tutucu; ör. bir node/playwright betiği).
  Komut yoksa `enabled=False`; sayfa `needs_js` damgalanır ve içerik denetimi atlanır — sessiz değil,
  bulgu olarak raporlanır (audit `NEEDS_JS_RENDER`).
Frappe'ye bağımlı değil; `requests.Session` enjekte edilebilir (testte sahte).
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
import time
import urllib.robotparser as robotparser
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

DEFAULT_UA = "iStocSEOHelper/1.0 (+seo-helper)"
MAX_REDIRECTS = 5
SPA_SHELL_MARKERS = ("__SEO_HEAD__", 'id="app"', "id='app'", 'id="root"', "/@vite/client")


@dataclass
class FetchResult:
	url: str
	status: int = 0
	final_url: str = ""
	redirect_chain: list[dict] = field(default_factory=list)
	response_ms: int = 0
	bytes: int = 0
	html: str = ""
	content_type: str = ""
	error: str = ""
	robots_blocked: bool = False
	rendered_with: str = "http"

	@property
	def ok(self) -> bool:
		return 200 <= self.status < 300 and not self.error


class RobotsCache:
	"""robots.txt'i host başına bir kez okur; okunamazsa (5xx/hata) 'izinli' sayar (Google davranışı 5xx'te
	'geçici engel'dir ama tarayıcımız site sahibinin kendisi — fail-open makul, kayıt düşülür)."""

	def __init__(self, session, ua: str, timeout: float = 10.0):
		self.session, self.ua, self.timeout = session, ua, timeout
		self._cache: dict[str, robotparser.RobotFileParser | None] = {}
		self.unparseable: set[str] = set()

	def allowed(self, url: str) -> bool:
		parts = urlsplit(url)
		base = f"{parts.scheme}://{parts.netloc}"
		if base not in self._cache:
			rp = robotparser.RobotFileParser()
			try:
				r = self.session.get(
					f"{base}/robots.txt", timeout=self.timeout, headers={"User-Agent": self.ua}
				)
				metin = r.text if r.status_code == 200 else ""
				if "{{" in metin:  # render edilmemiş şablon (dev'de görüldü) → ayrıştırma yapma, kaydet
					self.unparseable.add(base)
					metin = ""
				rp.parse(metin.splitlines())
			except Exception:  # noqa: BLE001 — ağ hatası: izinli say, kaydet
				self.unparseable.add(base)
				rp.parse([])
			self._cache[base] = rp
		rp = self._cache[base]
		return rp.can_fetch(self.ua, url) if rp else True


class JsRenderer:
	"""Dış komutla JS render. `command` içinde `{url}`; stdout = render edilmiş HTML."""

	def __init__(self, command: str | None, timeout: float = 60.0, runner=None):
		self.command = (command or "").strip()
		self.timeout = timeout
		self._run = runner or self._subprocess

	@property
	def enabled(self) -> bool:
		return bool(self.command) and "{url}" in self.command

	@staticmethod
	def _subprocess(args: list[str], timeout: float) -> str:
		p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
		if p.returncode != 0:
			raise RuntimeError(f"js render rc={p.returncode}: {p.stderr[:300]}")
		return p.stdout

	def render(self, url: str) -> str:
		if not self.enabled:
			raise RuntimeError("JS render kapalı")
		args = [a.replace("{url}", url) for a in shlex.split(self.command)]
		return self._run(args, self.timeout)


class Fetcher:
	def __init__(
		self,
		session,
		*,
		ua: str = DEFAULT_UA,
		timeout: float = 20.0,
		rate_limiter=None,
		robots: RobotsCache | None = None,
		respect_robots: bool = True,
		js_renderer: JsRenderer | None = None,
		clock=time.monotonic,
		allowed_hosts: set[str] | None = None,
	):
		self.session, self.ua, self.timeout = session, ua, timeout
		self.allowed_hosts = {h.lower() for h in (allowed_hosts or set())}
		self.rate_limiter, self.robots, self.respect_robots = rate_limiter, robots, respect_robots
		self.js = js_renderer
		self.clock = clock

	def fetch(self, url: str, *, allow_js: bool = True) -> FetchResult:
		res = FetchResult(url=url)
		if self.allowed_hosts and urlsplit(url).netloc.lower() not in self.allowed_hosts:
			res.error, res.rendered_with = "host beyaz listesinde değil", "none"
			return res
		if self.respect_robots and self.robots is not None and not self.robots.allowed(url):
			res.robots_blocked, res.error, res.rendered_with = True, "robots.txt disallow", "none"
			return res
		host = urlsplit(url).netloc
		if self.rate_limiter is not None:
			self.rate_limiter.wait(host)
		t0 = self.clock()
		hops: list[dict] = []
		try:
			# Yönlendirmeler elle izlenir: her adımın hostu İSTEK ATILMADAN önce beyaz listeden geçer
			# (allow_redirects=True olsaydı iç ağ/metadata adresine giden 302 gövdesiz de olsa istenirdi).
			cur = url
			while True:
				r = self.session.get(
					cur,
					timeout=self.timeout,
					headers={"User-Agent": self.ua, "Accept": "text/html,*/*"},
					allow_redirects=False,
				)
				hops.extend(
					{"url": h.url, "status": h.status_code} for h in (getattr(r, "history", None) or [])
				)
				st = int(r.status_code)
				basliklar = getattr(r, "headers", None) or {}
				loc = str(basliklar.get("Location") or "") if hasattr(basliklar, "get") else ""
				if not (300 <= st < 400 and loc):
					break
				hops.append({"url": cur, "status": st})
				nxt = urljoin(cur, loc)
				if len(hops) > MAX_REDIRECTS:
					res.error = f"yönlendirme sınırı aşıldı ({MAX_REDIRECTS})"
					break
				if self.allowed_hosts and urlsplit(nxt).netloc.lower() not in self.allowed_hosts:
					res.response_ms = int((self.clock() - t0) * 1000)
					res.redirect_chain, res.status, res.final_url = hops[:MAX_REDIRECTS], st, nxt
					res.error = f"dış hosta yönlendirme: {urlsplit(nxt).netloc}"
					return res
				cur = nxt
			res.response_ms = int((self.clock() - t0) * 1000)
			res.redirect_chain = hops[:MAX_REDIRECTS]
			res.status = st
			res.final_url = str(getattr(r, "url", cur) or cur)
			if res.error:  # sınır aşıldı: son 3xx yanıtı kayda geçer, gövde alınmaz
				return res
			res.content_type = str(r.headers.get("Content-Type", "")) if getattr(r, "headers", None) else ""
			if self.allowed_hosts and urlsplit(res.final_url).netloc.lower() not in self.allowed_hosts:
				# site dışına yönlendirme: gövde alınmaz (SSRF/veri sızıntısı kalkanı), zincir kayıtta kalır
				res.error = f"dış hosta yönlendirme: {urlsplit(res.final_url).netloc}"
				res.bytes = 0
				return res
			govde = r.text if "html" in res.content_type.lower() or not res.content_type else ""
			res.bytes = len(r.content) if getattr(r, "content", None) is not None else len(govde.encode())
			res.html = govde
		except Exception as e:  # noqa: BLE001 — ağ hatası sonuç olarak taşınır
			res.error = f"{type(e).__name__}: {e}"[:300]
			res.response_ms = int((self.clock() - t0) * 1000)
			res.redirect_chain = hops[
				:MAX_REDIRECTS
			]  # zincir ortasında düşerse izlenen adımlar kanıt olarak kalır
			return res
		if (
			allow_js
			and res.ok
			and self.js is not None
			and self.js.enabled
			and needs_js(parse_html(res.html, url), res.html)
		):
			try:
				res.html = self.js.render(res.final_url or url)
				res.rendered_with = "js"
			except Exception as e:  # noqa: BLE001 — render düşerse HTTP sonucu kalır, hata kaydedilir
				res.error = f"js_render: {e}"[:300]
		return res


_WS = re.compile(r"\s+")


def parse_html(html: str, base_url: str = "") -> dict:
	soup = BeautifulSoup(html or "", "html.parser")
	head = soup.head or soup
	title = (soup.title.string if soup.title and soup.title.string else "").strip()
	desc = ""
	robots_meta = ""
	for m in head.find_all("meta"):
		ad = (m.get("name") or "").lower()
		if ad == "description" and not desc:
			desc = (m.get("content") or "").strip()
		elif ad == "robots" and not robots_meta:
			robots_meta = (m.get("content") or "").strip()
	canonical = ""
	hreflang = []
	for link in head.find_all("link"):
		rel = [r.lower() for r in (link.get("rel") or [])]
		if "canonical" in rel and not canonical:
			canonical = (link.get("href") or "").strip()
		if "alternate" in rel and link.get("hreflang"):
			hreflang.append({"lang": link.get("hreflang"), "href": link.get("href") or ""})
	host = urlsplit(base_url).netloc
	internal = 0
	for a in soup.find_all("a", href=True):
		href = a["href"].strip()
		if href.startswith(("#", "mailto:", "tel:", "javascript:")):
			continue
		tam = urljoin(base_url, href) if base_url else href
		if not host or urlsplit(tam).netloc in ("", host):
			internal += 1
	imgs = soup.find_all("img")
	altsiz = sum(1 for i in imgs if not (i.get("alt") or "").strip())
	jsonld = []
	for s in soup.find_all("script", type="application/ld+json"):
		try:
			d = json.loads(s.string or "")
			items = d if isinstance(d, list) else [d]
			for it in items:
				if isinstance(it, dict) and it.get("@type"):
					t = it["@type"]
					jsonld.append(t if isinstance(t, str) else ",".join(map(str, t)))
		except (ValueError, TypeError):
			jsonld.append("INVALID")
	for s in soup(["script", "style", "noscript"]):
		s.decompose()
	metin = _WS.sub(" ", (soup.body or soup).get_text(" ", strip=True)) if soup else ""
	return {
		"title": title,
		"html_lang": (soup.html.get("lang") or "").strip() if soup.html else "",
		"meta_description": desc,
		"canonical": canonical,
		"robots_meta": robots_meta,
		"h1_count": len(soup.find_all("h1")),
		"hreflang": hreflang,
		"internal_links": internal,
		"images_without_alt": altsiz,
		"images_total": len(imgs),
		"json_ld_types": jsonld,
		"word_count": len(metin.split()) if metin else 0,
		"content_hash": hashlib.sha256(metin.encode()).hexdigest()[:32] if metin else "",
		"body_text_len": len(metin),
	}


def needs_js(parsed: dict, html: str) -> bool:
	"""SPA kabuğu: anlamlı metin yok + (bilinen kabuk imzası ya da script paketi var)."""
	if (parsed.get("word_count") or 0) >= 40:
		return False
	h = html or ""
	if any(m in h for m in SPA_SHELL_MARKERS):
		return True
	return bool(re.search(r"<script[^>]+type=[\"']module[\"']", h)) and (parsed.get("word_count") or 0) < 10

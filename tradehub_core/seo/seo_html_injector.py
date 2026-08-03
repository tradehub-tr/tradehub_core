"""
HTML placeholder enjeksiyonu.

Storefront Vite build'i HTML'lerin <head> içine `<!-- {{__SEO_HEAD__}} -->`
placeholder'ı yerleştirir (Task 10). Bu modül placeholder'ı Jinja-rendered
SEO meta tag bloğuyla değiştirir.

Vite HTML template'leri hardcoded SEO meta tag'leri içerebilir (title,
description, og:*, twitter:*). ``inject_meta_into_html`` önce bu tag'leri
temizler, sonra placeholder'ı DB'den gelen değerlerle doldurur — tarayıcı
ve arama motorları her zaman güncel değerleri görür.
"""

import json
import os
import re

from jinja2 import Environment

PLACEHOLDER = "<!-- {{__SEO_HEAD__}} -->"

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
_TEMPLATE_PATH = os.path.join(_TEMPLATE_DIR, "seo_head.html")
_template_cache = None

_SEO_STRIP_RE = re.compile(
	r"[ \t]*(?:"
	# Attribute'lu title'ları da yakala (<title data-i18n="...">) — aksi halde
	# backend kendi title'ını eklerken statik title kalır → çift <title> bug'ı.
	r"<title\b[^>]*>[^<]*</title>"
	r'|<meta\b[^>]*\bname="description"[^>]*/?\s*>'
	r'|<meta\b[^>]*\bname="robots"[^>]*/?\s*>'
	r'|<meta\b[^>]*\bproperty="og:[^"]*"[^>]*/?\s*>'
	r'|<meta\b[^>]*\bname="twitter:[^"]*"[^>]*/?\s*>'
	r'|<link\b[^>]*\brel="canonical"[^>]*/?\s*>'
	# Favicon linkleri: bot yolunda tek otorite şablon olsun. Storefront dist
	# mount edilmemişse fallback HTML'de favicon hiç yoktu → Google SERP'te
	# jenerik dünya ikonu gösteriyordu.
	r'|<link\b[^>]*\brel="(?:shortcut )?icon"[^>]*/?\s*>'
	r'|<link\b[^>]*\brel="apple-touch-icon"[^>]*/?\s*>'
	r")[ \t]*\n?",
	re.IGNORECASE,
)


def _get_template():
	global _template_cache
	if _template_cache is None:
		with open(_TEMPLATE_PATH, encoding="utf-8") as f:
			source = f.read()
		env = Environment(autoescape=True)
		# Jinja2 `tojson` filter normalde var ama emniyet için kayıt et
		env.filters.setdefault("tojson", lambda v: json.dumps(v))
		_template_cache = env.from_string(source)
	return _template_cache


def render_seo_head(seo: dict) -> str:
	"""Sadece <head>'e enjekte edilecek meta blob'unu render eder.

	Pure: HTML string döner."""
	return _get_template().render(seo=seo)


def _strip_hardcoded_seo_tags(html: str) -> str:
	"""Vite build'den gelen hardcoded SEO tag'lerini temizler.

	charset, viewport, theme-color gibi non-SEO meta tag'lere dokunmaz."""
	return _SEO_STRIP_RE.sub("", html)


def inject_meta_into_html(html: str, seo: dict) -> str:
	"""HTML'deki SEO placeholder'ını render edilmiş meta tag'ler ile değiştir.

	Önce Vite build'den gelen hardcoded SEO tag'leri temizlenir (title,
	description, og:*, twitter:*, canonical), sonra placeholder DB'den
	gelen güncel değerlerle doldurulur.

	Pure: input HTML değişmez, yeni string döner. Placeholder yoksa HTML
	olduğu gibi döner."""
	if PLACEHOLDER not in html:
		return html
	html = _strip_hardcoded_seo_tags(html)
	return html.replace(PLACEHOLDER, render_seo_head(seo), 1)

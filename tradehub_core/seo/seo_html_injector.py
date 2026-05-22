"""
HTML placeholder enjeksiyonu.

Storefront Vite build'i HTML'lerin <head> içine `<!-- {{__SEO_HEAD__}} -->`
placeholder'ı yerleştirir (Task 10). Bu modül placeholder'ı Jinja-rendered
SEO meta tag bloğuyla değiştirir.
"""

import json
import os

from jinja2 import Environment

PLACEHOLDER = "<!-- {{__SEO_HEAD__}} -->"

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
_TEMPLATE_PATH = os.path.join(_TEMPLATE_DIR, "seo_head.html")
_template_cache = None


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


def inject_meta_into_html(html: str, seo: dict) -> str:
	"""HTML'deki SEO placeholder'ını render edilmiş meta tag'ler ile değiştir.

	Pure: input HTML değişmez, yeni string döner. Placeholder yoksa HTML olduğu
	gibi döner. İlk eşleşme tüketildiği için ikinci çağrı no-op."""
	if PLACEHOLDER not in html:
		return html
	return html.replace(PLACEHOLDER, render_seo_head(seo), 1)

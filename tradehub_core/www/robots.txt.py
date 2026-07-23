"""
/robots.txt override'ı — backend domain'lerine (istoc/rcistoc/betaistoc.cronbi.com)
DOĞRUDAN gelen istekler için KOŞULSUZ block-all.

Gerekçe: storefront'un kendi robots.txt'i nginx edge'de üretilir (NGX-1) ve
/robots.txt backend'e asla proxy'lenmez. Frappe'nin website router'ına düşen
her /robots.txt isteği tanım gereği backend domain'inden gelmiştir — bu
domain'ler hiçbir ortamda indexlenmemeli (fail-closed). Ortam-duyarlı içerik
GATE-A doğrulaması için ayrı route'ta: `api/seo.get_robots`.

Frappe core'un `frappe/www/robots.txt.py` sayfasını gölgeleyerek Website
Settings.robots_txt okumasını da devre dışı bırakır (restore artığı bir
Allow kuralının staging'de yayınlanmasını engeller).
"""

from tradehub_core.seo.robots_generator import BLOCK_ALL_TEMPLATE

base_template_path = "www/robots.txt"
no_cache = 1


def get_context(context):
	return {"robots_txt": BLOCK_ALL_TEMPLATE}

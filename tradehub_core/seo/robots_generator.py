"""
Environment-aware robots.txt üretici.

Pure builder fonksiyonları Frappe runtime'a bağımlı değildir.
`get_robots_txt()` Frappe wrapper site_config'den env'i okur.
"""

BLOCK_ALL_TEMPLATE = "User-agent: *\nDisallow: /\n"

_PROD_DISALLOW_PATHS = [
	"/api/",
	"/app/",
	"/pages/dashboard/",
	"/cart.html",
	"/checkout.html",
	"/pages/auth/",
	"/pages/payment-",
	"/private/",
	"/*?q=",
	"/*?utm_*",
]


def build_prod_robots(site_url: str) -> str:
	"""Production robots.txt: tam ruleset + sitemap reference."""
	lines = ["User-agent: *", "Allow: /"]
	for path in _PROD_DISALLOW_PATHS:
		lines.append(f"Disallow: {path}")
	lines.append("")
	lines.append(f"Sitemap: {site_url.rstrip('/')}/sitemap.xml")
	lines.append("")
	return "\n".join(lines)


def build_robots_txt(*, env: str, site_url: str, manual_override: str | None = None) -> str:
	"""Environment ve manual override'a göre robots.txt content üretir.

	Precedence: manual_override > env-based template.
	Bilinmeyen env güvenli default (block all)."""
	if manual_override:
		return manual_override

	if env == "prod":
		return build_prod_robots(site_url)

	return BLOCK_ALL_TEMPLATE


def get_robots_txt() -> str:
	"""Site config'den env oku + Website Settings.robots_txt override kontrolü."""
	import frappe

	from tradehub_core.seo.site_url import storefront_url

	config = frappe.get_site_config() or {}
	env = config.get("seo_environment", "beta")
	site_url = storefront_url()

	ws = frappe.get_single("Website Settings")
	manual = (ws.get("robots_txt") or "").strip()

	return build_robots_txt(
		env=env,
		site_url=site_url,
		manual_override=manual or None,
	)

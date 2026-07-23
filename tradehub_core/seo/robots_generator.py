"""
Environment-aware robots.txt üretici.

Pure builder fonksiyonları Frappe runtime'a bağımlı değildir.
`get_robots_txt()` Frappe wrapper site_config'den env'i okur.
"""

BLOCK_ALL_TEMPLATE = "User-agent: *\nDisallow: /\n"

# Site adı → ortam eşlemesi (Ç1 kararı: eşleme-ÖNCE, site_config yalnız
# eşleme-DIŞI siteler için fallback). Restore-proof: prod DB'si rc/beta'ya
# restore edilince config'te kalan `seo_environment=prod` artığı staging'i
# indexe AÇAMAZ — ortam kararını site adı verir.
_SITE_TO_ENV = {
	"istoc.cronbi.com": "prod",
	"rcistoc.cronbi.com": "rc",
	"betaistoc.cronbi.com": "beta",
	"alphaistoc.cronbi.com": "beta",
}


def resolve_env_for_site(site: str | None, config_env: str | None = None) -> str:
	"""Ortam çözümü: _SITE_TO_ENV eşlemesi önce; eşleme-dışı sitede
	(local `tradehub.localhost`, ileride yeni ortamlar) config fallback;
	o da yoksa güvenli default `beta` (= noindex tarafı)."""
	env = _SITE_TO_ENV.get((site or "").strip().lower())
	if env:
		return env
	return config_env or "beta"


def resolve_env() -> str:
	"""Frappe wrapper: aktif site için ortam. Eşleme-önce, `frappe.conf`
	yalnız eşleme-dışı fallback."""
	import frappe

	site = getattr(frappe.local, "site", None)
	return resolve_env_for_site(site, frappe.conf.get("seo_environment"))


# Prod Disallow seti — nginx $resolved_page pretty-URL map'i ile senkron.
# `$` ankrajlı satırlar tam-path engeli: `/odeme$` `/odeme-secenekleri`ni
# ENGELLEMEZ (prefix çakışması bilinçli olarak ankrajla kırılır).
_PROD_DISALLOW_PATHS = [
	"/api/",
	"/app/",
	"/private/",
	# İşlem/hesap sayfaları (pretty URL)
	"/sepet$",
	"/odeme$",
	"/odeme/",
	"/hesabim$",
	"/hesabim/",
	"/giris$",
	"/kayit$",
	"/sifremi-unuttum$",
	"/sifre-sifirla$",
	"/davet-kabul$",
	"/destek/",
	"/satici/dashboard$",
	"/satici/basvuru-bekleyen$",
	"/satici/tedarikci-kurulum$",
	"/size-ozel$",
	# Legacy .html path'leri (aynı sayfaların dosya-yolu varyantları)
	"/pages/dashboard/",
	"/pages/auth/",
	"/pages/order/",
	"/pages/cart.html$",
	"/pages/help/help-ticket",
	"/pages/seller/dashboard.html$",
	"/pages/seller/application-pending.html$",
	"/pages/seller/supplier-setup.html$",
	"/pages/tailored-selections.html$",
	# Dinamik şablonların çıplak dosya yolları (canonical'sız boş şablon —
	# gerçek URL'ler /urun|/marka|/magaza pretty path'leridir)
	"/pages/product-detail.html$",
	"/pages/brand.html$",
	"/pages/seller/seller-shop.html$",
	"/pages/seller/seller-storefront.html$",
	# Parametre duplicate'leri (crawl budget)
	"/*?q=",
	"/*?utm_",
	"/*?lng=",
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
	"""Ortamı çöz (eşleme-önce) + Website Settings.robots_txt override kontrolü."""
	import frappe

	from tradehub_core.seo.site_url import storefront_url

	env = resolve_env()
	site_url = storefront_url()

	ws = frappe.get_single("Website Settings")
	manual = (ws.get("robots_txt") or "").strip()

	return build_robots_txt(
		env=env,
		site_url=site_url,
		manual_override=manual or None,
	)

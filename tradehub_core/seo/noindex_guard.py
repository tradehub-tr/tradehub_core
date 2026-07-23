"""
Staging/backend ortamlarına X-Robots-Tag: noindex header'ı basan after_request guard'ı.

SÖZLEŞME (BE-ROB kabul kriteri):
- `seo_noindex_guard` site-config bayrağı DEFAULT=0 (KAPALI). Bayrak yokken
  veya 0 iken hiçbir yanıta header EKLENMEZ. Prod'da bayrak yalnız FAZ C
  (nginx `proxy_hide_header X-Robots-Tag` canlı + curl kanıtı) sonrası açılır.
- Ortam kararı SITE ADINDAN gelir (`robots_generator.resolve_env`, eşleme-önce):
  prod sitesi (istoc.cronbi.com) hiçbir koşulda noindex almaz — bot-proxy
  isteklerinde Host backend domain'i görünse bile.
- `X-Istoc-Storefront` marker'ı taşıyan istekler muaf: storefront nginx'i
  kendi header politikasını uygular (staging edge zaten noindex basar).

Pure karar fonksiyonu Frappe'siz test edilir (test_noindex_guard.py a-h).
"""

NOINDEX_HEADER = "X-Robots-Tag"
NOINDEX_VALUE = "noindex, nofollow"
STOREFRONT_MARKER_HEADER = "X-Istoc-Storefront"


def should_add_noindex_header(*, guard_enabled: bool, env: str, storefront_marker: bool) -> bool:
	"""Pure karar: header eklenecek mi?

	guard_enabled: site-config `seo_noindex_guard` bayrağı (default 0/False)
	env: resolve_env() çıktısı ("prod" | "rc" | "beta" | ...)
	storefront_marker: istek X-Istoc-Storefront taşıyor mu
	"""
	if not guard_enabled:
		return False
	if storefront_marker:
		return False
	return env != "prod"


def apply_noindex_header(response=None, request=None):
	"""Frappe `after_request` hook'u. Bayrak kapalıyken tamamen no-op."""
	import frappe

	if response is None:
		return
	# Bayrak default=0: yokken/0 iken hiçbir header eklenmez (sözleşme).
	if not frappe.conf.get("seo_noindex_guard"):
		return

	from tradehub_core.seo.robots_generator import resolve_env

	req = request or getattr(frappe.local, "request", None)
	marker = bool(req is not None and req.headers.get(STOREFRONT_MARKER_HEADER))

	if should_add_noindex_header(guard_enabled=True, env=resolve_env(), storefront_marker=marker):
		response.headers[NOINDEX_HEADER] = NOINDEX_VALUE

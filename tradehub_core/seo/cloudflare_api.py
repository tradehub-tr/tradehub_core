"""
Cloudflare cache purge integrasyonu.

`purge_urls(urls)` belirtilen URL'leri Cloudflare cache'ten temizler. Site
config'de `cloudflare_zone_id` ve `cloudflare_api_token` set değilse sessizce
no-op (development ortamı için güvenli).

Pure `_call_cloudflare_purge(url, token, urls, http_post)` Frappe runtime'a
bağımlı değildir; HTTP fonksiyonu inject edilebilir (test).
"""

import requests


def _call_cloudflare_purge(
	*,
	zone_id: str,
	api_token: str,
	urls: list[str],
	http_post=requests.post,
	timeout: int = 10,
):
	"""Pure: Cloudflare API'ye POST atar, response döner.

	HTTP fonksiyonu parametre olarak verildiği için test edilebilir."""
	endpoint = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache"
	headers = {
		"Authorization": f"Bearer {api_token}",
		"Content-Type": "application/json",
	}
	return http_post(endpoint, json={"files": urls}, headers=headers, timeout=timeout)


def purge_urls(urls: list[str]) -> None:
	"""Cloudflare cache'ten URL listesini temizle. Sessizce başarısız olur."""
	if not urls:
		return

	import frappe

	config = frappe.get_site_config() or {}
	zone_id = config.get("cloudflare_zone_id")
	api_token = config.get("cloudflare_api_token")

	if not zone_id or not api_token:
		# Geliştirme ortamında credential yok — sessizce dön
		return

	try:
		response = _call_cloudflare_purge(
			zone_id=zone_id,
			api_token=api_token,
			urls=urls,
		)
		if response.status_code != 200:
			frappe.log_error(
				f"Cloudflare purge başarısız: {response.status_code} {response.text}",
				"SEO cloudflare_purge",
			)
	except requests.RequestException as exc:
		frappe.log_error(f"Cloudflare purge exception: {exc}", "SEO cloudflare_purge")

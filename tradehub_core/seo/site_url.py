"""Storefront public URL helper (SEO/paylaşım URL'leri için).

`frappe.utils.get_url()` request'in Host'unu döndürür; SEO render'ı nginx
üzerinden `Host: <backend>` (ör. istoc.cronbi.com) ile proxy edildiğinden
canonical/og:url paylaşımda backend domain'ini gösterir. Public storefront
domain'i (ör. https://istoc.com) `site_config.storefront_url`'de tutulur —
identity/public API'leri zaten bunu kullanıyor; SEO modülleri de kullanmalı.
"""

import frappe


def storefront_url() -> str:
	"""Public storefront URL (sondaki `/` olmadan).

	Öncelik `site_config.storefront_url`; tanımlı değilse `frappe.utils.get_url()`
	fallback'i (lokal/dev veya config eksikse).
	"""
	return (frappe.conf.get("storefront_url") or frappe.utils.get_url()).rstrip("/")

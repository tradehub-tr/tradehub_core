"""Storefront + admin panel public URL helper (SEO/paylaşım/e-posta linkleri).

`frappe.utils.get_url()` request'in Host'unu döndürür; SEO render'ı nginx
üzerinden `Host: <backend>` (ör. istoc.cronbi.com) ile proxy edildiğinden
canonical/og:url paylaşımda backend domain'ini gösterir.

Public storefront domain'i ortam-özeldir. Ancak bu deployment'ta her ortam
(rc/beta/alpha/local), prod'un DB **ve** site_config'i restore edilerek
eşitleniyor → `site_config.storefront_url` gibi config değerleri restore ile
prod'unkiyle ezilir, yani config'e güvenilemez. Restore ile DEĞİŞMEYEN tek
kimlik backend site adıdır (`frappe.local.site`, ör. `rcistoc.cronbi.com`) —
birincil kaynak budur. Elle config override (yeni ortam vb.) yine en üstte tutulur.
"""

import frappe

# Backend site adı → public storefront URL. `frappe.local.site` prod'dan
# DB+config restore edilse bile değişmez (site kimliği config'ten değil, sitenin
# kendisinden gelir), bu yüzden her ortam doğru URL üretir.
_SITE_TO_STOREFRONT = {
	"istoc.cronbi.com": "https://istoc.com",
	"rcistoc.cronbi.com": "https://rc.istoc.com",
	"betaistoc.cronbi.com": "https://beta.istoc.com",
	"alphaistoc.cronbi.com": "https://alpha.istoc.com",
	"dev.localhost": "http://tradehub.localhost",
}


def storefront_url() -> str:
	"""Public storefront URL (sondaki `/` olmadan).

	Öncelik: elle `site_config.storefront_url` override → backend site adı
	eşlemesi (restore-proof) → `frappe.utils.get_url()` fallback.
	"""
	return (
		frappe.conf.get("storefront_url")
		or _SITE_TO_STOREFRONT.get(frappe.local.site)
		or frappe.utils.get_url()
	).rstrip("/")


def admin_panel_url() -> str:
	"""Admin/satıcı paneli URL'i (sondaki `/` olmadan).

	Tüm ortamlarda storefront ile aynı host altında `/panel` path'inde servis
	edilir. Elle override için `admin_url` config'i öncelikli.
	"""
	return (frappe.conf.get("admin_url") or f"{storefront_url()}/panel").rstrip("/")

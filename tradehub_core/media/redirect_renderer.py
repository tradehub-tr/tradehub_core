"""Eski medya adresleri için 301 köprüsü (MOGEM-582 retro-rename).

Yalnız diskte OLMAYAN `/files/…` istekleri buraya düşer (frappe-frontend nginx
`try_files public/$uri @webserver`). `Website Route Redirect` bilinçli
kullanılmadı: `resolve_redirect` her istekte tüm kuralları çekip regex ile
tarıyor; 2.843 kural her sayfayı yavaşlatırdı. Burada tek indeksli sorgu var.
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime
from frappe.website.page_renderers.redirect_page import RedirectPage


class MediaRedirectRenderer:
	def __init__(self, path: str, http_status_code: int | None = None) -> None:
		self.path = path or ""
		self.http_status_code = http_status_code
		self.target: str | None = None

	def can_render(self) -> bool:
		if not self.path.startswith("files/"):
			return False
		source = "/" + self.path.split("?")[0]
		self.target = frappe.db.get_value(
			"Media URL Redirect",
			{"source_url": source, "expires_at": (">", now_datetime())},
			"target_url",
		)
		return bool(self.target)

	def render(self):
		frappe.flags.redirect_location = self.target
		return RedirectPage(self.path, 301).render()

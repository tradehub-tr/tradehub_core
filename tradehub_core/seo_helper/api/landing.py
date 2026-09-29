"""13.6 — vitrin iniş kaydı (guest, whitelisted). İmzalı çerez `experiments.attribution` üretir."""

from __future__ import annotations

import frappe

from tradehub_core.seo_helper.experiments.attribution import record_landing as _record


@frappe.whitelist(allow_guest=True, methods=["POST"])
def record_landing(
	path: str = "/",
	referrer: str = "",
	utm_source: str = "",
	utm_medium: str = "",
	utm_campaign: str = "",
	lang: str = "",
) -> dict:
	return _record(
		str(path or "/")[:500],
		str(referrer or "")[:500],
		str(utm_source or "")[:80],
		str(utm_medium or "")[:80],
		str(utm_campaign or "")[:120],
		str(lang or "")[:5],
	)

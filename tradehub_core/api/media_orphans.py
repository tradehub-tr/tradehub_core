"""Yetim AVIF türevleri — Sistem → Medya panel uçları (yalnız System Manager).

Mantık `media/yetim_avif.py`'de. Silme ucu varsayılan olarak KURU koşudur.
"""

from __future__ import annotations

import json

import frappe

from tradehub_core.media import yetim_avif

ROL = "System Manager"


def _liste(ham) -> list[str]:
	if not ham:
		return []
	if isinstance(ham, str):
		try:
			ham = json.loads(ham)
		except ValueError:
			ham = [ham]
	return [str(x) for x in ham if x][:500]


@frappe.whitelist(methods=["GET"])
def orphan_avif_overview(page: int = 1, page_size: int = 20, slot: str = "", refresh: int = 0) -> dict:
	"""Yetim AVIF dosyaları: toplam, sebep dağılımı, varlık bazında sayfalı gruplar."""
	frappe.only_for(ROL)
	return yetim_avif.ozet(page=page, page_size=page_size, slot=slot or "", refresh=bool(int(refresh or 0)))


@frappe.whitelist(methods=["POST"])
def orphan_avif_delete(assets=None, dry_run: int = 1, confirm_token: str = "") -> dict:
	"""Varsayılan KURU koşu ("ne silinirdi"). Gerçek işlem `dry_run=0` + jeton ister."""
	frappe.only_for(ROL)
	return yetim_avif.sil(
		assets=_liste(assets), dry_run=bool(int(dry_run)), confirm_token=str(confirm_token or "")
	)

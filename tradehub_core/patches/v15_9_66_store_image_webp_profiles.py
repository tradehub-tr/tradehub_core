# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Mağaza görselleri türevleri: AVIF → WebP, oran korunur (2026-09-30).

Politikalar (`policy/slots/seller-logo.json`, `company-cover-image.json`):

- `seller.logo`: `w64`, `w128`, `w256` WebP q90, `contain` (kare kutuya
  sığdırılır, dolgu YOK, alfa korunur). `w384`, `w512`, `og1200x630` kalkar.
- `company.cover_image`: `cover_384`, `cover_768`, `cover_1280`, `cover_1536`,
  `cover_1920` WebP q80, `contain` (24:5 kırpma yok — vitrin bandı ekran
  genişliğine göre 2:1…4,8:1 arası oranda `object-cover` ile basılıyor).
  `cover_2560`, `cover_16x9_1000` kalkar.

`v15_9_23_media_profile_seed` yeni profilleri açar ve biçim/kalite/fit
alanlarını günceller; politikadan kalkanları `v15_9_63.politikaya_esitle`
kapatır. Seed politikada OLMAYAN alanı yazmadığı için eski `aspect_ratio`
(`24:5`, `1:1`) kayıtta kalıyordu; `contain` onu kullanmasa da reçete yanlış
okunmasın diye burada boşaltılır. Satır SİLİNMEZ (tarihsel `Media Rendition.profile` karşılığı).
Türevlerin yeniden üretimi migrate'e bağlanmadı: tek düğme kartındaki
"Mağaza görselleri" adımı (Prova → Başlat) yapar.
"""

from __future__ import annotations

import frappe

from tradehub_core.media.pipeline.policy.engine import PolicyRegistry
from tradehub_core.patches import v15_9_23_media_profile_seed as seed
from tradehub_core.patches import v15_9_63_product_image_webp_profiles as webp

SLOTS: tuple[str, ...] = ("seller.logo", "company.cover_image")


def execute() -> dict[str, dict[str, int]]:
	seed.execute()
	sonuc = {slot: webp.politikaya_esitle(slot) for slot in SLOTS}
	for slot in SLOTS:
		sonuc[slot]["ratio_cleared"] = _oranlari_temizle(slot)
	frappe.db.commit()
	return sonuc


def _oranlari_temizle(slot: str) -> int:
	oransiz = {
		str(p.get("name") or "")
		for p in (PolicyRegistry().get(slot).get("profiles") or ())
		if not p.get("target_ratio")
	}
	adet = 0
	for satir in frappe.get_all(
		"Media Profile",
		filters={"slot_key": slot, "policy_profile": ["in", list(oransiz) or [""]]},
		fields=["name", "aspect_ratio"],
	):
		if satir.aspect_ratio:
			frappe.db.set_value("Media Profile", satir.name, "aspect_ratio", None)
			adet += 1
	return adet

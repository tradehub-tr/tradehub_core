# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""product.image türev merdiveni: 7 basamak AVIF → 4 basamak WebP (2026-09-30).

Politika (`policy/slots/product-image.json`) artık yalnız `w192`, `w384`,
`w768`, `w1280` profillerini WebP q80 olarak tanımlıyor. `Media Profile`
kayıtları politikadan `v15_9_23_media_profile_seed` ile tohumlanıyor ama o
patch iki şeyi YAPMIYOR ve burada yapılıyor:

1. **Politikadan kalkan profili kapatmak.** Seed yalnız upsert eder; `w96`,
   `w640`, `w1920` kayıtları açık kalırsa `_generate` onları AVIF olarak
   üretmeye devam eder.
2. **Kazara kapanmış profilleri açmak.** 2026-09-28 20:05'te
   `tests/test_pipeline_bridge.py` koşusu `product.image`'ın yedi profilini
   kapatıp commit'siz geri açtı (kök neden raporu:
   `.superpowers/sdd/2026-09-29-urun-gorseli-kare/webp-renditions-report.md`).
   Seed `enabled` alanına ilk açılıştan sonra dokunmaz (operatör alanı); bu
   kapanma operatör kararı olmadığı için tek seferlik olarak burada açılır.

Kapsam yalnız `product.image`. Diğer slotların profillerine dokunulmaz.
Satır SİLİNMEZ: eski profil kayıtları tarihsel `Media Rendition.profile`
değerlerinin sözleşme karşılığıdır.
"""

from __future__ import annotations

import frappe

from tradehub_core.media.pipeline.policy.engine import PolicyRegistry
from tradehub_core.patches import v15_9_23_media_profile_seed as seed

SLOT: str = "product.image"


def execute() -> dict[str, int]:
	# Önce politikadan gelen alanlar güncellenir (biçim, kalite, fit, oran).
	seed.execute()
	sayac = politikaya_esitle(SLOT)
	frappe.db.commit()
	return sayac


def politikaya_esitle(slot: str) -> dict[str, int]:
	"""`slot`un profillerini politikaya eşitle: politikada olan açık, olmayan kapalı.

	Mağaza görselleri geçişi (`v15_9_66`) aynı kuralı `seller.logo` ve
	`company.cover_image` için kullanır. Commit ÇAĞIRANIN işidir.
	"""
	politika = {
		str(p.get("name") or "").strip()
		for p in (PolicyRegistry().get(slot).get("profiles") or ())
		if p.get("name")
	}
	sayac = {"enabled": 0, "disabled": 0}
	for satir in frappe.get_all(
		"Media Profile",
		filters={"slot_key": slot},
		fields=["name", "policy_profile", "enabled"],
	):
		hedef = 1 if str(satir.policy_profile or "") in politika else 0
		if int(satir.enabled or 0) == hedef:
			continue
		# Sistem migration'ı; `enabled` tek alan, doğrulama gerektirmiyor.
		frappe.db.set_value("Media Profile", satir.name, "enabled", hedef)
		sayac["enabled" if hedef else "disabled"] += 1
	return sayac

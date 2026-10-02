# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""product.image w1280 türevi WebP q80 → q88 (2026-09-30, ikinci karar).

`Media Profile.quality_target` politikadan tohumlanıyor; seed yalnız
`v15_9_63`'te koştu ve o anki değer 80 idi. Aynı hizalama tekrar koşulur:
seed politikadaki yeni kaliteyi yazar, etkin profil kümesi değişmez.
"""

from __future__ import annotations

from tradehub_core.patches import v15_9_63_product_image_webp_profiles as hizala


def execute() -> dict[str, int]:
	return hizala.execute()

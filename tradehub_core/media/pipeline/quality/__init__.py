"""T-013 — Kalite ölçüm ve seçim katmanı.

Bu paket, sabit `quality` sabitinin (bkz. `tradehub_core/media/presets.py` ve
`engine.to_webp`'in `quality=80` varsayılanı) yerine geçecek **ölçüme dayalı**
kalite seçimini barındırır. Encode'u kendisi yapmaz; `tradehub_core.media.pipeline`
sarılır.

Kullanım:

    from tradehub_core.media.pipeline.quality import search_quality, target_for, guess_content_class

    sinif = guess_content_class(icerik)              # "photo" | "graphic"
    hedef = target_for("product.image", sinif)        # politika JSON'undan
    if hedef is None:
        ...  # slot kayıpsız istiyor (logo) — SSIM araması yapılmaz
    else:
        sonuc = search_quality(icerik, target_ssim=hedef, max_dim=2400)
        if sonuc.ok:
            yaz(sonuc.content)   # hedefi tutan EN DÜŞÜK kalite

Ölçümler ve gerekçe: `docs/reports/11-faz1-arge.md` §T-013.
Testler: `tests/test_quality_ssim.py`.
"""

from __future__ import annotations

from tradehub_core.media.pipeline.quality.adaptive import (
	AdaptiveQualityError,
	AdaptiveQualityResult,
	DEFAULT_TARGETS,
	FORMAT_QUALITY_BOUNDS,
	bounds_for,
	requires_lossless,
	select_quality,
)

from tradehub_core.media.pipeline.quality.ssim import (
	C1,
	C2,
	DEFAULT_MAX_ENCODES,
	DEFAULT_QUALITY_RANGE,
	PURE_MAX_PIXELS,
	WIN_SIZE,
	EncodeAttempt,
	QualitySearchResult,
	SsimResult,
	compute_ssim,
	encode_at,
	guess_content_class,
	master_reference,
	search_quality,
	target_for,
	to_luma,
)

__all__ = [
	"AdaptiveQualityError",
	"AdaptiveQualityResult",
	"C1",
	"C2",
	"DEFAULT_MAX_ENCODES",
	"DEFAULT_QUALITY_RANGE",
	"DEFAULT_TARGETS",
	"FORMAT_QUALITY_BOUNDS",
	"PURE_MAX_PIXELS",
	"WIN_SIZE",
	"EncodeAttempt",
	"QualitySearchResult",
	"SsimResult",
	"compute_ssim",
	"bounds_for",
	"encode_at",
	"guess_content_class",
	"master_reference",
	"search_quality",
	"requires_lossless",
	"select_quality",
	"target_for",
	"to_luma",
]

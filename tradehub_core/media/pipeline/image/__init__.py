"""Görsel türev (rendition) üretimi — T-063 / T-064 / T-066.

GERÇEK KOD (iskelet DEĞİL).

    render.py     T-063 · profil matrisi × biçim zinciri → türev merdiveni.
                  Lanczos3, çarpılmış alfa, upscale yasağı (FR-028), adaptif
                  kalite (≤4 encode), INV-05 fayda kapısı.
    reprocess.py  T-064 · idempotensi — motorun kendi çıktısını tekrar encode
                  etmeyi türetme anahtarı + içerik parmak iziyle engeller.
    report.py     T-066 · varlık başına JSON kalite raporu + Türkçe özet.

Testleri: `tests/test_render.py` (72 test) · `tests/test_render_regression.py`
(28 test). Ölçüm koşumu: `scripts/measure_render_t063.py`.

SARILAN, YENİDEN YAZILMAYAN MODÜLLER (kural 8):
    tradehub_core/media/pipeline.py   probe / optimize / to_webp — saf Pillow.
                                    `prepare_source` onun EXIF+ICC sırasını
                                    birebir korur.
    tradehub_core/media/gates.py    6 optimizasyon kapısı (saf fonksiyon)
    tradehub_core/media/pipeline/core/crop.py       kırpma penceresi çözümü (T-041)
    tradehub_core/media/pipeline/quality/ssim.py    adaptif kalite araması (T-013)
    tradehub_core/media/pipeline/policy/engine.py   slot politikası okuma

BENCHMARK KARARI (docs/reports/05-kutuphane-benchmark.md): Pillow'da kalınıyor.
pyvips kutudan çıktığı hâliyle 0,94x YAVAŞ; yalnız >20 MP dosyalarda (canlı
korpusun %3,7'si) kazanıyor ve CMYK'de rengi bozuyor. Geçilecekse tek dosya
(`render.encode`) değişir, üst katman değişmez.
"""

from __future__ import annotations

IMPLEMENTED = True

__all__ = ["IMPLEMENTED"]

"""Faz 11 — Önizleme simülatörü.

`devices.json` (T-110) ve `placements.json` (T-111) VERİDİR; `srcset.py` (T-112)
o veriyi okuyup **tarayıcının hangi türevi indireceğini** hesaplar.

Neden var: canlıda ölçüldü — incelenen 31 görselin **0**'ında `srcset` var ve
ürün detay sayfası **13,14 MB** görsel indiriyor (900 KB hedefinin 15 katı;
`docs/reports/08-canli-olcum.md`). Türev üretmek (Faz 6, `image/render.py`) tek
başına bu sayıyı düşürmez: tarayıcının DOĞRU türevi seçmesi gerekir, o da
`sizes` dizgesinin doğruluğuna bağlıdır. Bu paket `sizes`'ı storefront'un
GERÇEK CSS'inden türetir ve seçimi sunucuda simüle eder — böylece `srcset`
yazılmadan ÖNCE hangi cihazda hangi basamağın ineceği bilinir.

Yeniden yazılmayanlar (kural 8):

    tradehub_core/media/pipeline/policy/engine.py     PolicyRegistry — profil listesi ORADAN
                                      okunur, burada kopyalanmaz.
    tradehub_core/media/pipeline/contracts/delivery.py
                                      `Variant` ve `DeliveryManifest.pick`
                                      sözleşmesi. Buradaki seçim kuralı o
                                      sözleşmenin AYNISIDIR (en küçük yeterli
                                      aday; yoksa en büyüğü).
"""

from __future__ import annotations

from pathlib import Path

SIMULATOR_DIR: Path = Path(__file__).resolve().parent
DEVICES_PATH: Path = SIMULATOR_DIR / "devices.json"
PLACEMENTS_PATH: Path = SIMULATOR_DIR / "placements.json"

IMPLEMENTED = True

__all__ = ["SIMULATOR_DIR", "DEVICES_PATH", "PLACEMENTS_PATH", "IMPLEMENTED"]

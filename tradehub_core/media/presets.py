"""Görsel optimizasyon sabitleri — yalnız veri, mantık yok.

Ayarların gerekçesi `GORSEL-OPTIMIZASYON.md` §4.1-4.3'te ölçümle kayıtlı:
  - 2000px / q88 seçildi; q75 yalnız %3 ek kazanç verip görünür bozulma üretiyor.
  - `max_dim` aynı zamanda Kapı 4'ün (`already_small`) eşiğidir: en uzun kenarı bu
    değeri AŞMAYAN dosyaya hiç dokunulmaz. Hedefli yaklaşımın tek uygulama noktası budur.
"""

from __future__ import annotations

from typing import Final

PRESETS: Final[dict[str, dict[str, int]]] = {
	"safe": {"max_dim": 2560, "quality": 90},
	"balanced": {"max_dim": 2000, "quality": 88},  # varsayılan
	"aggressive": {"max_dim": 1600, "quality": 82},
}

DEFAULT_PRESET: Final[str] = "balanced"

# 200 KB altında kazanç yok, kalite riski var (Kapı 1).
MIN_FILE_SIZE: Final[int] = 200 * 1024

# Çıktı en az bu oranda küçülmediyse yazma (Kapı 6) — marjinal yeniden encode engellenir.
MIN_SAVING_RATIO: Final[float] = 0.10

# Redis ilerleme kaydının ömrü.
PROGRESS_TTL: Final[int] = 3600

# Worker kaç dosyada bir commit + progress yazsın.
COMMIT_EVERY: Final[int] = 10

# Orijinal arşivinin site altındaki klasörü. File kaydı YARATILMAZ — envanteri
# ve kotayı şişirmesin (GORSEL-OPTIMIZASYON.md §11).
ARCHIVE_DIRNAME: Final[str] = "image_originals"

# Arşiv bu günden eskiyse purge job siler; geri alma penceresi.
ARCHIVE_RETENTION_DAYS: Final[int] = 30


# Kapsam dışı: private olmasa bile bu doctype'lara bağlı ekler ne listelenir ne
# işlenir. `inventory` ve `usage` aynı listeyi kullanmalı — aksi hâlde filtre
# sayıları liste sayılarıyla tutmaz.
EXCLUDED_DOCTYPES: Final[tuple[str, ...]] = (
	"KYB Verification",
	"KYC Verification",
	"Seller Certification",
	"Seller Verification",
	"Seller Application",
	"Order",
	"Payment Transaction",
	"Data Export Request",
)


def resolve(preset: str | None) -> dict[str, int]:
	"""Preset adını ayara çevir; bilinmeyen ad varsayılana düşer."""
	return PRESETS.get(preset or DEFAULT_PRESET, PRESETS[DEFAULT_PRESET])

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


# TUR-126 §4 CRITICAL fix — bazı hassas belgeler `File.attached_to_doctype`
# set edilmeden yükleniyor; yalnız EXCLUDED bir doctype'ın kendi Attach/Data
# alanından string olarak referanslanıyor. Canlı DB'de doğrulandı:
# `Seller Application.identity_document` 144 dosya, `Seller Certification.
# document` 2 dosya — ikisinde de `attached_to_doctype` BOŞ. `EXCLUDED_
# DOCTYPES` + `attached_to_doctype` kontrolü TEK BAŞINA bu 146 kimlik/PII
# belgesini (TC kimlik taraması dahil) yakalayamıyor; `media/access_level.py`
# `set_level()` public'e geçişten önce bu haritayla TERS REFERANS taraması
# (`frappe.db.exists(doctype, {field: file_url})`) da yapmalı.
#
# KVKK BAKIM NOTU: `EXCLUDED_DOCTYPES`'e yeni bir doctype eklenirse ve o
# doctype'ta dosya-tutan bir alan (Attach/Attach Image/Data) varsa, BU HARİTA
# da güncellenmeli — aksi hâlde o doctype'ın dosyaları toggle korumasından
# sessizce kaçar.
EXCLUDED_MEDIA_FIELDS: Final[dict[str, tuple[str, ...]]] = {
	"KYC Verification": ("identity_document",),
	"Seller Application": ("identity_document",),
	"KYB Verification": (
		"identity_document",
		"bank_account_document",
		# Ticari kimlik belgeleri: imza sirküleri imza örneği, sicil gazetesi
		# ortak/adres bilgisi, vergi levhası VKN taşır. Hepsi Attach alanı.
		"imza_sirkuleri",
		"ticaret_sicil_gazetesi",
		"faaliyet_belgesi",
		"vergi_levhasi",
	),
	"Seller Certification": ("document",),
	"Seller Verification": ("document",),
	# Bu üç doctype `EXCLUDED_DOCTYPES`ta zaten var, yani `attached_to_doctype`
	# DOLUYSA korunuyorlar. Ters referans yolu (dosya boş `attached_to_*` ile
	# yüklenmiş) ise açıktı: ölçümde 2 dosya bu yoldan `is_private=0` çıktı.
	# Toplu içe aktarımda `attached_to_*` boş kalması yaygın (bkz. K-3: ürün
	# görsellerinin %61'i böyle), o yüzden bu yol kapatılmalı.
	"Order": ("receipt_url",),
	"Payment Transaction": ("receipt_url",),
	"Data Export Request": ("file_url",),
}


def resolve(preset: str | None) -> dict[str, int]:
	"""Preset adını ayara çevir; bilinmeyen ad varsayılana düşer."""
	return PRESETS.get(preset or DEFAULT_PRESET, PRESETS[DEFAULT_PRESET])

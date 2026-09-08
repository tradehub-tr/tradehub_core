# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
SEO içerik kuralları — ürün adı (title) ve açıklama (description) için tek kaynak.

Hem tekil ürün kaydında (Listing.validate) hem toplu yüklemede (bulk_import.validator)
aynı kurallar uygulansın diye buradan çağrılır. Kurallar:
  - Başlık en az TITLE_MIN_CHARS karakter (SEO için çok kısa başlık yasak).
  - Açıklama en az DESC_MIN_CHARS görünür karakter (HTML etiketleri sayılmaz).
  - Başlıkta ve açıklamada emoji/piktografik sembol yasak.

Eşikler sabit; ileride Single bir "SEO Settings" doctype'ına taşınabilir.
"""

from __future__ import annotations

import re

# ── Ayarlanabilir eşikler ──────────────────────────────────────────────
TITLE_MIN_CHARS = 50  # Ürün adı en az 50 karakter (SEO)
TITLE_MAX_CHARS = 250
DESC_MIN_CHARS = 150  # Açıklama en az 150 görünür karakter (çok kısa yazı olmasın)

# Emoji / piktografik sembol aralıkları. Türkçe harfler (ç ğ ı ö ş ü İ) ve
# ©®™ → gibi tipografik işaretler bu aralıkların dışında, yanlış eşleşmez.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # emoji, emoticon, taşıma, piktogram blokları
    "\U00002600-\U000026FF"  # misc semboller ☀ ★ ☂
    "\U00002700-\U000027BF"  # dingbat ✂ ✅ ✈
    "\U00002B00-\U00002BFF"  # ok/yıldız ⭐ ⬛
    "\U00002300-\U000023FF"  # ⌚ ⏰ ⌛
    "\U0000FE00-\U0000FE0F"  # variation selector (emoji sunumu)
    "\U0001F1E6-\U0001F1FF"  # bayrak (bölge göstergeleri)
    "\U0000200D"             # zero-width joiner
    "]+",
    flags=re.UNICODE,
)


def contains_emoji(text) -> bool:
    """Metinde emoji/piktografik sembol var mı?"""
    return bool(_EMOJI_RE.search(str(text or "")))


def visible_text_length(html_or_text) -> int:
    """Görünür metin uzunluğu — HTML etiketlerini ve fazla boşluğu saymaz."""
    raw = str(html_or_text or "")
    # HTML etiketlerini at
    text = re.sub(r"<[^>]+>", " ", raw)
    # &nbsp; ve yaygın entity'leri boşluğa çevir
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&[a-zA-Z]+;", "", text)
    # Fazla boşlukları sadeleştir
    text = re.sub(r"\s+", " ", text).strip()
    return len(text)


def check_title(title) -> tuple[bool, str | None]:
    """(ok, hata_mesajı). title plain metin beklenir."""
    t = str(title or "").strip()
    if not t:
        return False, "Ürün adı boş olamaz."
    if contains_emoji(t):
        return False, "Ürün adında emoji veya sembol kullanılamaz."
    n = len(t)
    if n < TITLE_MIN_CHARS:
        return False, (
            f"Ürün adı SEO için en az {TITLE_MIN_CHARS} karakter olmalıdır (şu an {n}). "
            "Ürünü kategori, marka ve öne çıkan özelliğiyle betimleyin."
        )
    if n > TITLE_MAX_CHARS:
        return False, f"Ürün adı {TITLE_MAX_CHARS} karakteri aşamaz (şu an {n})."
    return True, None


def check_description(description) -> tuple[bool, str | None]:
    """(ok, hata_mesajı). description HTML ya da düz metin olabilir."""
    raw = str(description or "")
    if contains_emoji(raw):
        return False, "Ürün açıklamasında emoji veya sembol kullanılamaz."
    n = visible_text_length(raw)
    if n < DESC_MIN_CHARS:
        return False, (
            f"Ürün açıklaması SEO için en az {DESC_MIN_CHARS} karakter olmalıdır (şu an {n}). "
            "Malzeme, kullanım, ölçü gibi detayları yazın; çok kısa açıklama yeterli değildir."
        )
    return True, None

import json
import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


# CSS var adı: iki tire ile başlar, küçük harf/rakam/tire
_CSS_VAR_NAME_RE = re.compile(r"^--[a-z][a-z0-9-]*$")

# Değer içinde yasak karakterler: CSS injection önleme
_FORBIDDEN_VALUE_PATTERNS = (";", "}", "<", "url(", "expression(", "/*", "*/")

# Renk değeri formatları (lowercased)
_COLOR_VALUE_RE = re.compile(
    r"^("
    r"#[0-9a-f]{3,8}"
    r"|rgba?\([^)]+\)"
    r"|hsla?\([^)]+\)"
    r"|transparent"
    r"|currentcolor"
    r"|inherit"
    r"|var\(--[a-z0-9-]+(,\s*[^)]+)?\)"
    r")$"
)

# Sayısal değer formatı: 0 | 0.5 | 12px | 1rem | 100% | -2em
_NUMERIC_VALUE_RE = re.compile(r"^-?\d+(\.\d+)?(px|rem|em|%|vw|vh|)$")

# Küçük metin değerleri (shadow, font vs.) için genel whitelist
_TEXT_VALUE_RE = re.compile(r"^[a-zA-Z0-9\s\.,\-_#()%/]+$")


# =====================================================================
# İzinli CSS değişken anahtarları
# =====================================================================
# ⚠️  SENKRON DOSYALAR
#   - tradehubfront/src/utils/themeTokens.ts      (UI reference)
#   - admin-panel/frontend/src/data/themeTokens.js (admin panel)
# Üç tarafı da birlikte güncelleyin. Aksi halde admin panel yeni token
# göstermez veya backend save hata verir.
# =====================================================================

# --- v1: Buton tokenları ---
_BUTTON_KEYS = frozenset(
    {
        # Ortak buton tokenları
        "--radius-button",
        "--spacing-button-x",
        "--spacing-button-y",
        "--btn-font-size",
        "--btn-font-weight",
        # Solid buton
        "--btn-bg",
        "--btn-text",
        "--btn-border-width",
        "--btn-border-color",
        "--btn-shadow",
        "--btn-hover-bg",
        "--btn-hover-text",
        # Outline buton
        "--btn-outline-bg",
        "--btn-outline-text",
        "--btn-outline-border-width",
        "--btn-outline-border-color",
        "--btn-outline-hover-bg",
        "--btn-outline-hover-text",
    }
)


def _scale_keys(prefix: str) -> frozenset:
    """50..950 scale helper — `--color-primary-50`, `-100`, ... üretir."""
    return frozenset(
        f"--color-{prefix}-{step}"
        for step in (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950)
    )


# --- v2: Palet tokenları (primary/secondary/accent + semantic + surface/text/border) ---
_PALETTE_KEYS = frozenset(
    _scale_keys("primary")
    | _scale_keys("secondary")
    | _scale_keys("accent")
    | {
        # Semantic
        "--color-success-50", "--color-success-500", "--color-success-700",
        "--color-warning-50", "--color-warning-500", "--color-warning-700",
        "--color-error-50", "--color-error-500", "--color-error-700",
        "--color-info-50", "--color-info-500", "--color-info-700",
        # Surface
        "--color-surface",
        "--color-surface-muted",
        "--color-surface-raised",
        "--color-surface-overlay",
        "--color-surface-inverse",
        # Text
        "--color-text-primary",
        "--color-text-secondary",
        "--color-text-tertiary",
        "--color-text-disabled",
        "--color-text-inverse",
        "--color-text-link",
        "--color-text-link-hover",
        # Border
        "--color-border-default",
        "--color-border-strong",
        "--color-border-focus",
        "--color-border-error",
    }
)

# --- v3: Tipografi, spacing, radius tokenları ---
_TYPOGRAPHY_KEYS = frozenset(
    {
        # Font size scale (9 step)
        "--font-size-xs", "--font-size-sm", "--font-size-base", "--font-size-lg",
        "--font-size-xl", "--font-size-2xl", "--font-size-3xl", "--font-size-4xl",
        "--font-size-5xl",
        # Font weight (5 step)
        "--font-weight-normal", "--font-weight-medium", "--font-weight-semibold",
        "--font-weight-bold", "--font-weight-black",
        # Line height (6 step)
        "--line-height-none", "--line-height-tight", "--line-height-snug",
        "--line-height-normal", "--line-height-relaxed", "--line-height-loose",
        # Letter spacing (5 step)
        "--letter-spacing-tighter", "--letter-spacing-tight", "--letter-spacing-normal",
        "--letter-spacing-wide", "--letter-spacing-wider",
    }
)

_RADIUS_KEYS = frozenset(
    {
        "--radius-none", "--radius-sm", "--radius-md", "--radius-lg",
        "--radius-xl", "--radius-full",
        # Semantic radius
        "--radius-card", "--radius-input", "--radius-badge",
        "--radius-modal", "--radius-tooltip",
    }
)

_SPACING_KEYS = frozenset(
    {
        # Semantic spacing (en çok kullanılanlar — ham 0/2/4... değil)
        "--spacing-card-padding",
        "--spacing-card-gap",
        "--spacing-section-y",
        "--spacing-section-y-lg",
        "--spacing-page-x",
        "--spacing-page-x-lg",
        "--spacing-stack-sm",
        "--spacing-stack-md",
        "--spacing-stack-lg",
        "--spacing-inline-sm",
        "--spacing-inline-md",
        "--spacing-inline-lg",
        "--spacing-input-x",
        "--spacing-input-y",
    }
)

# --- v4: Input / Checkbox / Quantity stepper tokenları ---
_INPUT_KEYS = frozenset(
    {
        # Base
        "--input-bg",
        "--input-border-width",
        "--input-border-color",
        "--input-border-color-hover",
        "--input-text-color",
        "--input-placeholder-color",
        "--input-font-size",
        "--input-font-weight",
        "--input-line-height",
        # Focus
        "--input-focus-border-color",
        "--input-focus-ring-color",
        "--input-focus-ring-width",
        "--input-focus-ring-offset",
        # Disabled
        "--input-disabled-bg",
        "--input-disabled-text",
        "--input-disabled-border-color",
        "--input-disabled-opacity",
        # Error
        "--input-error-border-color",
        "--input-error-bg",
        "--input-error-text",
        "--input-error-ring-color",
        # Size variants
        "--input-height-sm",
        "--input-height-md",
        "--input-height-lg",
    }
)

_CHECKBOX_KEYS = frozenset(
    {
        "--checkbox-size",
        "--checkbox-radius",
        "--checkbox-border-width",
        "--checkbox-border-color",
        "--checkbox-bg",
        "--checkbox-checked-bg",
        "--checkbox-checked-border",
        "--checkbox-checked-icon",
        "--checkbox-disabled-opacity",
    }
)

_QUANTITY_KEYS = frozenset(
    {
        "--quantity-height",
        "--quantity-width",
        "--quantity-bg",
        "--quantity-border-width",
        "--quantity-border-color",
        "--quantity-radius",
        "--quantity-button-size",
        "--quantity-button-bg-hover",
        "--quantity-text-color",
        "--quantity-text-size",
        "--quantity-disabled-opacity",
    }
)

# --- v5: Ürün kartı tokenları (3 katmanlı cascade: generic → product-card → section) ---
_PRODUCT_CARD_KEYS = frozenset(
    {
        # --- Generic card (mini / related / featured) ---
        "--card-bg",
        "--card-border-width",
        "--card-border-color",
        "--card-title-size",
        "--card-title-weight",
        "--card-price-color",
        "--card-price-size",
        "--card-price-weight",
        "--card-desc-color",
        "--card-desc-size",
        "--card-moq-color",
        "--card-moq-size",
        "--card-badge-bg",
        "--card-badge-text",
        "--card-badge-size",
        "--card-badge-radius",
        "--card-verified-color",
        "--card-verified-size",
        "--card-supplier-color",
        "--card-supplier-size",
        # --- Product card (listing base) ---
        "--product-card-bg",
        "--product-card-border",
        "--product-card-border-width",
        "--product-card-radius",
        "--product-card-padding",
        "--product-card-shadow",
        "--product-card-hover-shadow",
        "--product-card-min-height",
        # --- Hero subcomponents: title / image / lens ---
        "--product-title-color",
        "--product-title-size",
        "--product-title-weight",
        "--product-title-line-height",
        "--product-title-letter-spacing",
        "--product-image-size",
        "--product-image-ratio",
        "--product-image-radius",
        "--product-image-padding",
        "--product-image-hover-scale",
        "--product-lens-size",
        "--product-lens-bg",
        "--product-lens-shadow",
        "--product-lens-color",
        # --- Section override'ları ---
        "--topdeals-card-bg",
        "--topdeals-card-border",
        "--topdeals-price-color",
        "--topdeals-badge-bg",
        "--topranking-card-bg",
        "--topranking-card-border",
        "--tailored-card-bg",
        "--tailored-card-border",
        "--tailored-price-color",
        "--tailored-views-color",
        "--tailored-collection-title-color",
        # --- Varyant-başına layout tokenları (--pc-{v}-*) ---
        # Default'lar orijinal görünümü korur; admin override edince sadece o
        # varyant değişir (tasarım diğer yerlerde bozulmaz).
        # Mini (shared/ProductCard)
        "--pc-mini-bg",
        "--pc-mini-border-color",
        "--pc-mini-border-width",
        "--pc-mini-radius",
        # Top Deals (top-deals.html flat)
        "--pc-topdeals-bg",
        "--pc-topdeals-border-color",
        "--pc-topdeals-border-width",
        "--pc-topdeals-radius",
        "--pc-topdeals-padding",
        # Top Ranking (top-ranking.html flat)
        "--pc-topranking-bg",
        "--pc-topranking-border-color",
        "--pc-topranking-border-width",
        "--pc-topranking-radius",
        "--pc-topranking-padding",
        # RFQ arama (rfq.ts)
        "--pc-rfq-bg",
        "--pc-rfq-border-color",
        "--pc-rfq-border-width",
        "--pc-rfq-radius",
        # Featured / HotProducts (seller/HotProducts)
        "--pc-featured-bg",
        "--pc-featured-border-color",
        "--pc-featured-border-width",
        "--pc-featured-radius",
        "--pc-featured-padding",
        # Related (product detay .rp-card)
        "--pc-related-bg",
        "--pc-related-border-color",
        "--pc-related-border-width",
        "--pc-related-radius",
    }
)

ALLOWED_THEME_KEYS = frozenset(
    _BUTTON_KEYS
    | _PALETTE_KEYS
    | _TYPOGRAPHY_KEYS
    | _RADIUS_KEYS
    | _SPACING_KEYS
    | _INPUT_KEYS
    | _CHECKBOX_KEYS
    | _QUANTITY_KEYS
    | _PRODUCT_CARD_KEYS
)

# Renk tipi olan anahtarlar (tip bazlı doğrulama için)
_COLOR_KEYS = frozenset(
    _PALETTE_KEYS  # tüm palet anahtarları renk tipidir
    | {
        # Button
        "--btn-bg",
        "--btn-text",
        "--btn-border-color",
        "--btn-hover-bg",
        "--btn-hover-text",
        "--btn-outline-bg",
        "--btn-outline-text",
        "--btn-outline-border-color",
        "--btn-outline-hover-bg",
        "--btn-outline-hover-text",
        # Input
        "--input-bg",
        "--input-border-color",
        "--input-border-color-hover",
        "--input-text-color",
        "--input-placeholder-color",
        "--input-focus-border-color",
        "--input-focus-ring-color",
        "--input-disabled-bg",
        "--input-disabled-text",
        "--input-disabled-border-color",
        "--input-error-border-color",
        "--input-error-bg",
        "--input-error-text",
        "--input-error-ring-color",
        # Checkbox
        "--checkbox-border-color",
        "--checkbox-bg",
        "--checkbox-checked-bg",
        "--checkbox-checked-border",
        "--checkbox-checked-icon",
        # Quantity
        "--quantity-bg",
        "--quantity-border-color",
        "--quantity-button-bg-hover",
        "--quantity-text-color",
        # Product card — generic card renkleri
        "--card-bg",
        "--card-border-color",
        "--card-price-color",
        "--card-desc-color",
        "--card-moq-color",
        "--card-badge-bg",
        "--card-badge-text",
        "--card-verified-color",
        "--card-supplier-color",
        # Product card — base
        "--product-card-bg",
        "--product-card-border",
        # Product card — hero subcomponents
        "--product-title-color",
        "--product-lens-bg",
        "--product-lens-color",
        # Section override renkleri
        "--topdeals-card-bg",
        "--topdeals-card-border",
        "--topdeals-price-color",
        "--topdeals-badge-bg",
        "--topranking-card-bg",
        "--topranking-card-border",
        "--tailored-card-bg",
        "--tailored-card-border",
        "--tailored-price-color",
        "--tailored-views-color",
        "--tailored-collection-title-color",
        # Varyant-başına renkler (bg + border-color × 6 varyant)
        "--pc-mini-bg",            "--pc-mini-border-color",
        "--pc-topdeals-bg",        "--pc-topdeals-border-color",
        "--pc-topranking-bg",      "--pc-topranking-border-color",
        "--pc-rfq-bg",             "--pc-rfq-border-color",
        "--pc-featured-bg",        "--pc-featured-border-color",
        "--pc-related-bg",         "--pc-related-border-color",
    }
)

# Sayısal tipte olan anahtarlar — tipografi / spacing / radius / buton / input / checkbox / quantity numeric
_NUMERIC_KEYS = frozenset(
    _TYPOGRAPHY_KEYS | _RADIUS_KEYS | _SPACING_KEYS
    | {
        # Button numeric
        "--radius-button",
        "--spacing-button-x",
        "--spacing-button-y",
        "--btn-font-size",
        "--btn-font-weight",
        "--btn-border-width",
        "--btn-outline-border-width",
        # Input numeric
        "--input-border-width",
        "--input-font-size",
        "--input-font-weight",
        "--input-line-height",
        "--input-focus-ring-width",
        "--input-focus-ring-offset",
        "--input-disabled-opacity",
        "--input-height-sm",
        "--input-height-md",
        "--input-height-lg",
        # Checkbox numeric
        "--checkbox-size",
        "--checkbox-radius",
        "--checkbox-border-width",
        "--checkbox-disabled-opacity",
        # Quantity numeric
        "--quantity-height",
        "--quantity-width",
        "--quantity-border-width",
        "--quantity-radius",
        "--quantity-button-size",
        "--quantity-text-size",
        "--quantity-disabled-opacity",
        # Product card numeric
        "--card-border-width",
        "--card-title-size",
        "--card-title-weight",
        "--card-price-size",
        "--card-price-weight",
        "--card-desc-size",
        "--card-moq-size",
        "--card-badge-size",
        "--card-badge-radius",
        "--card-verified-size",
        "--card-supplier-size",
        "--product-card-border-width",
        "--product-card-radius",
        "--product-card-padding",
        "--product-card-min-height",
        "--product-title-size",
        "--product-title-weight",
        "--product-title-line-height",
        "--product-title-letter-spacing",
        "--product-image-size",
        "--product-image-radius",
        "--product-image-padding",
        "--product-image-hover-scale",
        "--product-lens-size",
        # Varyant-başına numeric (border-width + radius + padding)
        "--pc-mini-border-width",       "--pc-mini-radius",
        "--pc-topdeals-border-width",   "--pc-topdeals-radius",   "--pc-topdeals-padding",
        "--pc-topranking-border-width", "--pc-topranking-radius", "--pc-topranking-padding",
        "--pc-rfq-border-width",        "--pc-rfq-radius",
        "--pc-featured-border-width",   "--pc-featured-radius",   "--pc-featured-padding",
        "--pc-related-border-width",    "--pc-related-radius",
    }
)


class TradehubThemeSettings(Document):
    def validate(self):
        self._normalize_overrides()
        self._validate_css_values()
        # Audit alanları
        self.last_updated_by = frappe.session.user
        self.last_updated_at = now_datetime()

    def on_update(self):
        # Public cache'i temizle — bir sonraki get_public_theme çağrısı taze okuyacak
        frappe.cache().delete_key("tradehub_public_theme")

    # ------------------------------------------------------------------
    # Dahili yardımcılar
    # ------------------------------------------------------------------

    def _normalize_overrides(self) -> None:
        if self.overrides in (None, ""):
            self.overrides = "{}"
            return
        if isinstance(self.overrides, (dict, list)):
            self.overrides = json.dumps(self.overrides)
            return
        try:
            parsed = json.loads(self.overrides)
        except (TypeError, ValueError):
            frappe.throw(_("Overrides alanı geçerli bir JSON nesnesi olmalıdır."))
            return
        if not isinstance(parsed, dict):
            frappe.throw(_("Overrides alanı bir JSON nesnesi (object) olmalıdır."))
        # Geri yaz (formatlanmış hali)
        self.overrides = json.dumps(parsed)

    def _validate_css_values(self) -> None:
        try:
            data = json.loads(self.overrides or "{}")
        except (TypeError, ValueError):
            frappe.throw(_("Overrides alanı geçerli bir JSON nesnesi olmalıdır."))
            return

        for raw_key, raw_value in data.items():
            key = str(raw_key).strip()
            value = str(raw_value).strip() if raw_value is not None else ""

            if not _CSS_VAR_NAME_RE.match(key):
                frappe.throw(_("Geçersiz CSS değişken adı: {0}").format(key))

            if key not in ALLOWED_THEME_KEYS:
                frappe.throw(_("İzin verilmeyen tema anahtarı: {0}").format(key))

            if not value:
                frappe.throw(_("{0} için boş değer verilemez.").format(key))

            lowered = value.lower()
            for pattern in _FORBIDDEN_VALUE_PATTERNS:
                if pattern in lowered:
                    frappe.throw(
                        _("{0} değeri yasak karakter içeriyor: {1}").format(key, pattern)
                    )

            if key in _COLOR_KEYS:
                if not _COLOR_VALUE_RE.match(lowered):
                    frappe.throw(
                        _("{0} geçerli bir renk değeri değil: {1}").format(key, value)
                    )
            elif key in _NUMERIC_KEYS:
                if not _NUMERIC_VALUE_RE.match(lowered):
                    frappe.throw(
                        _("{0} geçerli bir sayısal değer değil: {1}").format(key, value)
                    )
            else:
                if not _TEXT_VALUE_RE.match(value):
                    frappe.throw(
                        _("{0} geçersiz metin değeri içeriyor: {1}").format(key, value)
                    )

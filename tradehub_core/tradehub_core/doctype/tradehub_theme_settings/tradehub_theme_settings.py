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


# v1 kapsamındaki izinli CSS değişken anahtarları (button odaklı)
# İleride genişletildiğinde tradehubfront/src/utils/themeTokens.ts ile senkron tutulmalı.
ALLOWED_THEME_KEYS = frozenset(
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

# Renk tipi olan anahtarlar (tip bazlı doğrulama için)
_COLOR_KEYS = frozenset(
    {
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
    }
)

# Sayısal tipte olan anahtarlar
_NUMERIC_KEYS = frozenset(
    {
        "--radius-button",
        "--spacing-button-x",
        "--spacing-button-y",
        "--btn-font-size",
        "--btn-font-weight",
        "--btn-border-width",
        "--btn-outline-border-width",
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

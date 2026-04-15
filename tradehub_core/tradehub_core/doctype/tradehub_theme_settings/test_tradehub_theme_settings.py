"""
Unit tests for Tradehub Theme Settings whitelist & validation.

Frappe bench gerektirmez — `frappe` modülünü mock'layarak doğrudan
tradehub_theme_settings modülünü import eder ve saf doğrulama mantığını test
eder.

Çalıştırmak için:
    python -m unittest tradehub_core.tradehub_core.doctype.tradehub_theme_settings.test_tradehub_theme_settings

Bench ile:
    bench --site dev.localhost run-tests --doctype "Tradehub Theme Settings"
"""
from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Frappe mock — modülü import etmeden önce sys.modules'e yerleştir
# ---------------------------------------------------------------------------

def _install_frappe_mock() -> None:
    if "frappe" in sys.modules:
        return

    frappe_mod = types.ModuleType("frappe")

    class _PermissionError(Exception):
        pass

    class _DoesNotExistError(Exception):
        pass

    def _throw(msg, exc=None):
        raise (exc or Exception)(str(msg))

    def _translate(x):
        return x

    class _Session:
        user = "Administrator"

    def _now_datetime():
        from datetime import datetime
        return datetime.now()

    # frappe.*
    frappe_mod.throw = _throw
    frappe_mod._ = _translate
    frappe_mod.PermissionError = _PermissionError
    frappe_mod.DoesNotExistError = _DoesNotExistError
    frappe_mod.session = _Session()
    frappe_mod.cache = MagicMock()

    # frappe.model.document.Document — validate() içinde super kullanılmıyor,
    # alan erişimi için basit bir placeholder yeterli.
    class _Document:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        def save(self, *args, **kwargs):
            # Gerçek save yerine sadece validate çağıralım (testlerde manuel çağırıyoruz)
            return None

    model_mod = types.ModuleType("frappe.model")
    document_mod = types.ModuleType("frappe.model.document")
    document_mod.Document = _Document
    model_mod.document = document_mod

    utils_mod = types.ModuleType("frappe.utils")
    utils_mod.now_datetime = _now_datetime

    sys.modules["frappe"] = frappe_mod
    sys.modules["frappe.model"] = model_mod
    sys.modules["frappe.model.document"] = document_mod
    sys.modules["frappe.utils"] = utils_mod


_install_frappe_mock()

# Mock yerleştirildi — şimdi güvenle import edebiliriz
from tradehub_core.tradehub_core.doctype.tradehub_theme_settings.tradehub_theme_settings import (  # noqa: E402
    ALLOWED_THEME_KEYS,
    TradehubThemeSettings,
    _BUTTON_KEYS,
    _CHECKBOX_KEYS,
    _COLOR_KEYS,
    _INPUT_KEYS,
    _NUMERIC_KEYS,
    _PALETTE_KEYS,
    _QUANTITY_KEYS,
    _RADIUS_KEYS,
    _SPACING_KEYS,
    _TYPOGRAPHY_KEYS,
)


# ---------------------------------------------------------------------------
# Yardımcı: validate()'i doğrudan çağırabilmek için minimal bir doc
# ---------------------------------------------------------------------------

def _make_doc(overrides_dict):
    """validate()'in ihtiyacı olan alanlara sahip hafif bir doc üret."""
    doc = TradehubThemeSettings.__new__(TradehubThemeSettings)
    doc.overrides = json.dumps(overrides_dict)
    doc.last_updated_at = None
    doc.last_updated_by = None
    return doc


# ---------------------------------------------------------------------------
# Testler
# ---------------------------------------------------------------------------


class TestWhitelistSize(unittest.TestCase):
    """Whitelist matematiksel olarak doğru mu?"""

    def test_button_key_count(self):
        self.assertEqual(len(_BUTTON_KEYS), 18)

    def test_palette_key_count(self):
        # 3 scale × 11 + 12 semantic + 5 surface + 7 text + 4 border = 61
        self.assertEqual(len(_PALETTE_KEYS), 61)

    def test_typography_key_count(self):
        # 9 font-size + 5 weight + 6 line-height + 5 letter-spacing = 25
        self.assertEqual(len(_TYPOGRAPHY_KEYS), 25)

    def test_radius_key_count(self):
        # 6 base + 5 semantic = 11
        self.assertEqual(len(_RADIUS_KEYS), 11)

    def test_spacing_key_count(self):
        # 14 semantic spacing token
        self.assertEqual(len(_SPACING_KEYS), 14)

    def test_input_key_count(self):
        # 9 base + 4 focus + 4 disabled + 4 error + 3 size = 24
        self.assertEqual(len(_INPUT_KEYS), 24)

    def test_checkbox_key_count(self):
        self.assertEqual(len(_CHECKBOX_KEYS), 9)

    def test_quantity_key_count(self):
        self.assertEqual(len(_QUANTITY_KEYS), 11)

    def test_allowed_is_union(self):
        expected = (
            _BUTTON_KEYS
            | _PALETTE_KEYS
            | _TYPOGRAPHY_KEYS
            | _RADIUS_KEYS
            | _SPACING_KEYS
            | _INPUT_KEYS
            | _CHECKBOX_KEYS
            | _QUANTITY_KEYS
        )
        self.assertEqual(ALLOWED_THEME_KEYS, expected)
        # 18 + 61 + 25 + 11 + 14 + 24 + 9 + 11 = 173
        self.assertEqual(len(ALLOWED_THEME_KEYS), 173)

    def test_palette_in_color_keys(self):
        """Her palet anahtarı _COLOR_KEYS içinde olmalı (tip doğrulaması için)."""
        for key in _PALETTE_KEYS:
            self.assertIn(key, _COLOR_KEYS, f"{key} _COLOR_KEYS içinde değil")

    def test_numeric_keys_composition(self):
        """Sayısal anahtarlar: button (7) + typo (25) + radius (11) + spacing (14)
        + input (10) + checkbox (4) + quantity (7) = 78."""
        self.assertEqual(len(_NUMERIC_KEYS), 78)
        self.assertNotIn("--color-primary-500", _NUMERIC_KEYS)
        self.assertIn("--font-size-base", _NUMERIC_KEYS)
        self.assertIn("--radius-card", _NUMERIC_KEYS)
        self.assertIn("--spacing-card-padding", _NUMERIC_KEYS)
        self.assertIn("--btn-font-size", _NUMERIC_KEYS)
        self.assertIn("--input-border-width", _NUMERIC_KEYS)
        self.assertIn("--input-height-md", _NUMERIC_KEYS)
        self.assertIn("--checkbox-size", _NUMERIC_KEYS)
        self.assertIn("--quantity-button-size", _NUMERIC_KEYS)

    def test_primary_scale_complete(self):
        for step in (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950):
            self.assertIn(f"--color-primary-{step}", ALLOWED_THEME_KEYS)

    def test_secondary_scale_complete(self):
        for step in (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950):
            self.assertIn(f"--color-secondary-{step}", ALLOWED_THEME_KEYS)

    def test_accent_scale_complete(self):
        for step in (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950):
            self.assertIn(f"--color-accent-{step}", ALLOWED_THEME_KEYS)


class TestValidatePaletteColors(unittest.TestCase):
    """validate() palet renklerini doğru kabul/ret ediyor mu?"""

    def test_valid_hex_primary(self):
        doc = _make_doc({"--color-primary-500": "#3b82f6"})
        doc.validate()  # throw atmamalı
        self.assertEqual(doc.last_updated_by, "Administrator")

    def test_valid_full_primary_scale(self):
        scale = {
            f"--color-primary-{s}": hex_val for s, hex_val in [
                (50, "#eff6ff"), (100, "#dbeafe"), (200, "#bfdbfe"),
                (300, "#93c5fd"), (400, "#60a5fa"), (500, "#3b82f6"),
                (600, "#2563eb"), (700, "#1d4ed8"), (800, "#1e40af"),
                (900, "#1e3a8a"), (950, "#172554"),
            ]
        }
        doc = _make_doc(scale)
        doc.validate()

    def test_valid_rgba_surface_overlay(self):
        doc = _make_doc({"--color-surface-overlay": "rgba(0, 0, 0, 0.5)"})
        doc.validate()

    def test_reject_invalid_hex(self):
        doc = _make_doc({"--color-primary-500": "not-a-color"})
        with self.assertRaises(Exception) as ctx:
            doc.validate()
        self.assertIn("renk", str(ctx.exception).lower())

    def test_reject_unknown_key(self):
        doc = _make_doc({"--color-unknown-500": "#ff0000"})
        with self.assertRaises(Exception) as ctx:
            doc.validate()
        self.assertIn("İzin verilmeyen", str(ctx.exception))

    def test_reject_out_of_scale_number(self):
        doc = _make_doc({"--color-primary-123": "#ff0000"})
        with self.assertRaises(Exception) as ctx:
            doc.validate()
        # --color-primary-123 whitelist'te yok
        self.assertIn("İzin verilmeyen", str(ctx.exception))


class TestValidateTypography(unittest.TestCase):
    """Tipografi token'ları için numeric validation (Faz 5)."""

    def test_valid_font_size_rem(self):
        doc = _make_doc({"--font-size-base": "1.125rem"})
        doc.validate()

    def test_valid_font_size_px(self):
        doc = _make_doc({"--font-size-xl": "24px"})
        doc.validate()

    def test_valid_font_weight(self):
        doc = _make_doc({"--font-weight-bold": "700"})
        doc.validate()

    def test_valid_line_height_unitless(self):
        doc = _make_doc({"--line-height-normal": "1.625"})
        doc.validate()

    def test_valid_letter_spacing_em(self):
        doc = _make_doc({"--letter-spacing-wide": "0.025em"})
        doc.validate()

    def test_valid_letter_spacing_negative(self):
        doc = _make_doc({"--letter-spacing-tighter": "-0.03em"})
        doc.validate()

    def test_reject_font_size_garbage(self):
        doc = _make_doc({"--font-size-base": "big"})
        with self.assertRaises(Exception):
            doc.validate()


class TestValidateRadius(unittest.TestCase):
    """Radius token'ları (Faz 5)."""

    def test_valid_radius_px(self):
        doc = _make_doc({"--radius-card": "16px"})
        doc.validate()

    def test_valid_radius_pill(self):
        doc = _make_doc({"--radius-badge": "9999px"})
        doc.validate()

    def test_valid_radius_zero(self):
        doc = _make_doc({"--radius-none": "0"})
        doc.validate()


class TestValidateSpacing(unittest.TestCase):
    """Semantic spacing token'ları (Faz 5)."""

    def test_valid_card_padding(self):
        doc = _make_doc({"--spacing-card-padding": "24px"})
        doc.validate()

    def test_valid_section_y_rem(self):
        doc = _make_doc({"--spacing-section-y": "4rem"})
        doc.validate()


class TestValidateInputTokens(unittest.TestCase):
    """Input token'ları (Faz T3) — base + focus + disabled + error + size."""

    def test_valid_input_border_color_hex(self):
        doc = _make_doc({"--input-border-color": "#d1d5db"})
        doc.validate()

    def test_valid_input_focus_ring_rgba(self):
        doc = _make_doc({"--input-focus-ring-color": "rgba(204, 153, 0, 0.12)"})
        doc.validate()

    def test_valid_input_disabled_opacity(self):
        doc = _make_doc({"--input-disabled-opacity": "0.6"})
        doc.validate()

    def test_valid_input_height_variants(self):
        doc = _make_doc({
            "--input-height-sm": "32px",
            "--input-height-md": "40px",
            "--input-height-lg": "48px",
        })
        doc.validate()

    def test_valid_input_full_error_state(self):
        doc = _make_doc({
            "--input-error-border-color": "#ef4444",
            "--input-error-bg": "#fef2f2",
            "--input-error-text": "#b91c1c",
            "--input-error-ring-color": "rgba(239, 68, 68, 0.15)",
        })
        doc.validate()

    def test_reject_input_border_width_garbage(self):
        doc = _make_doc({"--input-border-width": "thick"})
        with self.assertRaises(Exception):
            doc.validate()


class TestValidateCheckboxQuantityTokens(unittest.TestCase):
    """Checkbox ve Quantity stepper token'ları (Faz T3)."""

    def test_valid_checkbox_full(self):
        doc = _make_doc({
            "--checkbox-size": "20px",
            "--checkbox-radius": "4px",
            "--checkbox-checked-bg": "#cc9900",
            "--checkbox-checked-icon": "#ffffff",
        })
        doc.validate()

    def test_valid_quantity_pill_radius(self):
        doc = _make_doc({"--quantity-radius": "9999px"})
        doc.validate()

    def test_valid_quantity_square_radius(self):
        doc = _make_doc({"--quantity-radius": "8px"})
        doc.validate()

    def test_reject_checkbox_unknown_key(self):
        doc = _make_doc({"--checkbox-hover-bg": "#fff"})  # whitelist'te yok
        with self.assertRaises(Exception) as ctx:
            doc.validate()
        self.assertIn("İzin verilmeyen", str(ctx.exception))


class TestValidateButtonTokens(unittest.TestCase):
    """Eski buton token'ları hâlâ çalışıyor mu (regresyon)?"""

    def test_valid_button_bg(self):
        doc = _make_doc({"--btn-bg": "#3b82f6"})
        doc.validate()

    def test_valid_button_numeric(self):
        doc = _make_doc({"--spacing-button-x": "28px"})
        doc.validate()

    def test_valid_button_shadow(self):
        doc = _make_doc({"--btn-shadow": "none"})
        doc.validate()


class TestValidateCssInjection(unittest.TestCase):
    """Güvenlik: CSS injection denemeleri reddedilmeli."""

    def test_reject_semicolon(self):
        doc = _make_doc({"--color-primary-500": "#ff0000; body { display:none }"})
        with self.assertRaises(Exception):
            doc.validate()

    def test_reject_url_function(self):
        doc = _make_doc({"--color-primary-500": "url(evil.com)"})
        with self.assertRaises(Exception):
            doc.validate()

    def test_reject_closing_brace(self):
        doc = _make_doc({"--color-primary-500": "#ff0000 }"})
        with self.assertRaises(Exception):
            doc.validate()

    def test_reject_html_tag(self):
        doc = _make_doc({"--color-primary-500": "#ff0000 <script>"})
        with self.assertRaises(Exception):
            doc.validate()

    def test_reject_expression(self):
        doc = _make_doc({"--color-primary-500": "expression(alert(1))"})
        with self.assertRaises(Exception):
            doc.validate()

    def test_reject_comment_open(self):
        doc = _make_doc({"--color-primary-500": "#ff0000 /* evil"})
        with self.assertRaises(Exception):
            doc.validate()


class TestValidateCssVarName(unittest.TestCase):
    """CSS değişken adı regex kontrolü."""

    def test_reject_invalid_var_name_no_prefix(self):
        doc = _make_doc({"color-primary-500": "#ff0000"})
        with self.assertRaises(Exception) as ctx:
            doc.validate()
        self.assertIn("Geçersiz CSS", str(ctx.exception))

    def test_reject_invalid_var_name_uppercase(self):
        doc = _make_doc({"--Color-Primary-500": "#ff0000"})
        with self.assertRaises(Exception):
            doc.validate()

    def test_reject_empty_value(self):
        doc = _make_doc({"--color-primary-500": ""})
        with self.assertRaises(Exception) as ctx:
            doc.validate()
        self.assertIn("boş değer", str(ctx.exception))


class TestNormalizeOverrides(unittest.TestCase):
    """_normalize_overrides() davranışı."""

    def test_empty_string_becomes_empty_dict(self):
        doc = TradehubThemeSettings.__new__(TradehubThemeSettings)
        doc.overrides = ""
        doc.last_updated_at = None
        doc.last_updated_by = None
        doc.validate()
        self.assertEqual(doc.overrides, "{}")

    def test_dict_input_serialized(self):
        doc = TradehubThemeSettings.__new__(TradehubThemeSettings)
        doc.overrides = {"--color-primary-500": "#3b82f6"}
        doc.last_updated_at = None
        doc.last_updated_by = None
        doc.validate()
        parsed = json.loads(doc.overrides)
        self.assertEqual(parsed, {"--color-primary-500": "#3b82f6"})

    def test_invalid_json_raises(self):
        doc = TradehubThemeSettings.__new__(TradehubThemeSettings)
        doc.overrides = "not-a-json"
        doc.last_updated_at = None
        doc.last_updated_by = None
        with self.assertRaises(Exception):
            doc.validate()


if __name__ == "__main__":
    unittest.main(verbosity=2)

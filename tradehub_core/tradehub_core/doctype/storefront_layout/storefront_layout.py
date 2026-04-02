import frappe
import json
from frappe import _
from frappe.model.document import Document


# Satıcının sayfasında kullanabileceği bölüm tipleri
VALID_SECTION_TYPES = {
    "hero_banner",
    "category_grid",
    "hot_products",
    "category_listing",
    "company_info",
    "certificates",
    "why_choose_us",
    "gallery",
    "company_introduction",
    "contact_form",
}

# Yeni layout oluşturulduğunda varsayılan bölüm sırası
DEFAULT_SECTIONS = [
    {"type": "hero_banner", "order": 1, "enabled": True, "settings": {"mode": "slider", "autoplay": True, "delay": 5000}},
    {"type": "category_grid", "order": 2, "enabled": True, "settings": {"columns": 4, "bgColor": ""}},
    {"type": "hot_products", "order": 3, "enabled": True, "settings": {"title": "", "bgColor": "", "count": 8}},
    {"type": "category_listing", "order": 4, "enabled": True, "settings": {"showSort": True, "viewModes": ["grid", "list"], "columns": 4}},
    {"type": "company_info", "order": 5, "enabled": False, "settings": {"bgColor": ""}},
    {"type": "certificates", "order": 6, "enabled": False, "settings": {"layout": "carousel", "columns": 4}},
    {"type": "why_choose_us", "order": 7, "enabled": False, "settings": {"bgColor": ""}},
    {"type": "gallery", "order": 8, "enabled": False, "settings": {"columns": 4, "lightbox": True}},
]

DEFAULT_THEME = {
    "primaryColor": "#1e3a5f",
    "accentColor": "#cc9900",
    "bgColor": "#ffffff",
    "navBgColor": "#1e3a5f",
    "navTextColor": "#ffffff",
}


class StorefrontLayout(Document):
    def before_insert(self):
        if not self.sections:
            self.sections = json.dumps(DEFAULT_SECTIONS)
        if not self.theme_config:
            self.theme_config = json.dumps(DEFAULT_THEME)

    def validate(self):
        self._validate_sections()
        self._validate_theme()

    def _validate_sections(self):
        if not self.sections:
            return
        try:
            sections = json.loads(self.sections) if isinstance(self.sections, str) else self.sections
        except (json.JSONDecodeError, TypeError):
            frappe.throw(_("Bölüm düzeni geçerli bir JSON olmalıdır"))
            return

        for section in sections:
            if not isinstance(section, dict):
                frappe.throw(_("Her bölüm bir nesne olmalıdır"))
            if section.get("type") not in VALID_SECTION_TYPES:
                frappe.throw(_("Geçersiz bölüm tipi: {0}").format(section.get("type")))

    def _validate_theme(self):
        if not self.theme_config:
            return
        try:
            json.loads(self.theme_config) if isinstance(self.theme_config, str) else self.theme_config
        except (json.JSONDecodeError, TypeError):
            frappe.throw(_("Tema konfigürasyonu geçerli bir JSON olmalıdır"))

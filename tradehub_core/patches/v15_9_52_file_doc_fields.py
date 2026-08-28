"""Doküman SEO alanları — sayfa sayısı + çıkarılan metin (Dosya Yöneticisi SEO, Task 1).

Karar belgesi: `.superpowers/sdd/2026-08-27-file-manager-seo/task-1-brief.md`.
`th_media_page_count`/`th_media_extracted_text` `File`'a eklenir; `media/seo.py`
`_asset_columns`/`_birlestir` width/height ve duration/poster_url ile AYNI
özel-durum desenini uygular — SEO metni değil dosyanın fiziksel gerçeği,
`SINGLE`'a girmez (`set_asset_fields`'tan yazılamaz).
İdempotent: create_custom_fields(update=True).
"""

from __future__ import annotations

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS: dict[str, list[dict]] = {
	"File": [
		{
			"fieldname": "th_media_page_count",
			"label": "TH Media Page Count",
			"fieldtype": "Int",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_extracted_text",
			"label": "TH Media Extracted Text",
			"fieldtype": "Long Text",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
	]
}


def execute() -> None:
	create_custom_fields(FIELDS, update=True)

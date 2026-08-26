"""Video SEO alanları — poster, süre, transcript, altyazı (Dilim 4).

Karar belgesi: docs/superpowers/specs/2026-08-26-medya-video-seo-design.md §3.
Başlık/açıklama/caption için YENİ kolon YOK — v15_9_37'nin 4 dilli alanları
videoda da geçerli (K3). transcript tek dil (video dilindedir).
İdempotent: create_custom_fields(update=True).
"""

from __future__ import annotations

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS: dict[str, list[dict]] = {
	"File": [
		{
			"fieldname": "th_media_duration",
			"label": "TH Media Duration (s)",
			"fieldtype": "Float",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_poster_url",
			"label": "TH Media Poster URL",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_transcript",
			"label": "TH Media Transcript",
			"fieldtype": "Long Text",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_captions_url",
			"label": "TH Media Captions URL (WebVTT)",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
	]
}


def execute() -> None:
	create_custom_fields(FIELDS, update=True)

"""Transcode deneme sayacı — `File.th_media_transcode_attempts` (TUR-296).

Retry + dead-letter için: her başarısız transcode denemesi bu sayacı artırır;
`MAX_TRANSCODE_ATTEMPTS`'e ulaşınca dosya `failed`'a (dead-letter) düşer ve
sistem elle tetiklenmeden bir daha denemez. Sayaç ayrı alanda tutuluyor çünkü
`th_media_video_status` KULLANICIYA gösterilen durumdur — retry beklerken bile
`processing` kalır; "kaç kez denendi" ise operasyonel bilgidir ve denetim
ekranı dışında kimseyi ilgilendirmez.

Boş/0 = hiç başarısız deneme yok (mevcut dosyalar için doğal varsayılan).

Idempotent: `create_custom_fields` mevcut alanı yeniden oluşturmaz.
Desen: `v15_9_16_media_video_status.py`.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS: dict[str, list[dict]] = {
	"File": [
		{
			"fieldname": "th_media_transcode_attempts",
			"label": "TH Media Transcode Attempts",
			"fieldtype": "Int",
			"default": "0",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "th_media_video_status",
			"module": "Tradehub Core",
		},
	]
}


def execute() -> dict:
	# `has_column` DOCTYPE adı ister, tablo adı değil — "tab" önekini kendisi
	# ekliyor.
	olusan = [
		alan["fieldname"]
		for alan in FIELDS["File"]
		if not frappe.db.has_column("File", alan["fieldname"])
	]
	create_custom_fields(FIELDS, ignore_validate=True)
	frappe.db.commit()
	return {"created": olusan}

"""Ses dosyası metadata alanı — sanatçı (MOGEM-620 §15).

TEK YENİ KOLON. Diğer üç alan zaten var ve YENİDEN AÇILMADI:

  başlık → `th_media_title*` (v15_9_37'nin 4 dilli alanları; `doc_meta.apply`
           PDF `/Title`'ı da oraya yazıyor — ses de aynı kapıyı kullanır)
  süre   → `th_media_duration` (v15_9_49; videoyla aynı fiziksel gerçek)
  kapak  → `th_media_poster_url` (v15_9_49; "medyayı temsil eden sabit görsel"
           videoda poster, seste kapak — AYNI kavram, ayrı kolon mükerrerlik
           olurdu ve iki yerden okunan tek bir alan doğururdu)

`th_media_artist` yeni çünkü karşılığı yok: `th_media_creator` hakları elinde
tutan kurum (lisans beşlisinin parçası), sanatçı ise sesi üreten kişi. Bir
podcast'te ikisi gerçekten farklıdır — `schema_builder.build_audio_object`
birini `creator`, diğerini `author` olarak basar.

İdempotent: create_custom_fields(update=True).
"""

from __future__ import annotations

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS: dict[str, list[dict]] = {
	"File": [
		{
			"fieldname": "th_media_artist",
			"label": "TH Media Artist",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
	]
}


def execute() -> None:
	create_custom_fields(FIELDS, update=True)

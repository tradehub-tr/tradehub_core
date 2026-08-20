# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""`Media Asset`e `original_sha256` alanını ekle (W7 — rapor 64 EK-2).

Yükleme yolu görseli `File.insert`ten ÖNCE WebP'ye çeviriyor
(`api/seller_media._kaydet`); istemcinin elindeki ORİJİNAL baytların sha256'sı
hiçbir kayda yazılmıyordu ve tekilleştirme araması bu içeriklerde kördü.
Alanı `tradehub_core/media/files.py::record_original_hash` yazar,
`tradehub_core/media/inventory.py::_find_by_original_hash` okur.

Neden CUSTOM FIELD, neden DocType JSON değişikliği değil:

  * Şartnamenin ham-yükleme künyesi `Media Source` bu app'te BİLİNÇLİ olarak
    kurulu değil (doctype_specs/_index.json — `has_alpha` kararıyla aynı
    gerekçe); tek alan için o kararı devirmek gerekmiyor.
  * `media_asset.json` Şerit A'nın (T-040/T-064) şema dosyası; tek alanlık bu
    iş, `v15_9_12`nin (File'a `th_optimized_at`) kurduğu custom-field deseniyle
    kendi patch'inde kendi kendine yeter ve `reload_doc` sırası derdi yaratmaz.

Neden `search_index`: `inventory._find_by_original_hash` alan üzerinden eşitlik
sorgusu koşuyor; indekssiz kolon tabloyla birlikte lineer büyürdü.

`unique` DEĞİL: aynı orijinal içerik iki slota (ya da iki satıcı tarafından)
yüklenebilir — tekillik `asset_key` üçlüsünde kalır.

Idempotent: `create_custom_fields` mevcut alanı yeniden oluşturmaz. Veri
yazmaz; geriye dönük doldurma YAPILAMAZ (eski yüklemelerin orijinal baytları
sunucuya hiç gelmedi — bkz. inventory.find_by_sha256 "bilinçli sınırlar").

Sıra: `v15_9_21_media_pipeline_doctypes`ten (Media Asset kurulumu) SONRA
koşmalı; tablo yoksa alan eklenecek yer de yoktur, patch açıkça patlar ki
sessizce alan eksik bir kurulum doğmasın.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS: dict[str, list[dict]] = {
	"Media Asset": [
		{
			"fieldname": "original_sha256",
			"label": "Original SHA-256",
			"fieldtype": "Data",
			"length": 64,
			"search_index": 1,
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "content_sha256",
			"description": (
				"Yükleme anında dönüştürülen (PNG/JPEG→WebP) içeriğin ORİJİNAL "
				"baytlarının tam sha256'sı — content_sha256 saklanan baytların "
				"32 haneli kısaltmasıdır, bu alan istemcinin elindeki dosyanın "
				"64 haneli kimliği (rapor 64 EK-2)."
			),
			"module": "Tradehub Core",
		},
	]
}


def execute() -> dict:
	if not frappe.db.table_exists("Media Asset"):
		frappe.throw(_("Media Asset tablosu yok — önce v15_9_21_media_pipeline_doctypes koşmalı."))

	created = [
		f["fieldname"]
		for f in FIELDS["Media Asset"]
		if not frappe.db.exists("Custom Field", {"dt": "Media Asset", "fieldname": f["fieldname"]})
	]

	create_custom_fields(FIELDS, ignore_validate=True)
	frappe.db.commit()

	return {"created": created}

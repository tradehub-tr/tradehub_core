"""İçerik çok-dilliliği — DocType controller yardımcısı (FAZ 7).

`validate()` içinde çağrılır. Dil-sufix kolonları (`{field}_tr/_en/_ar/_ru`) ile
legacy base kolon (`{field}`) arasında kaynak/varsayılan-dil senkronizasyonu yapar
ve zorunlu alanların varsayılan dilde dolu olmasını garanti eder.

Saf çözümleyici (frappe'siz) `tradehub_core.seo.i18n` içindedir.
"""

from __future__ import annotations

import frappe
from frappe import _

from tradehub_core.seo.i18n import (
	CONTENT_CHILD_TABLES,
	CONTENT_CHILD_TRANSLATABLE_FIELDS,
	CONTENT_LANGS,
	CONTENT_TRANSLATABLE_FIELDS,
	normalize_lang,
)


def _sync_field(doc, field: str, default_lang: str, required: bool = False) -> None:
	"""Tek bir alan için base ↔ default-dil senkronu (bidirectional)."""
	default_col = f"{field}_{default_lang}"
	default_val = doc.get(default_col)
	base_val = doc.get(field)
	if not default_val and base_val:
		doc.set(default_col, base_val)
		default_val = base_val
	if required and not default_val:
		frappe.throw(
			_("'{0}' alanı varsayılan dilde ({1}) zorunludur.").format(field, default_lang.upper()),
			title=_("Eksik çeviri"),
		)
	if default_val:
		doc.set(field, default_val)


def translatable_columns(doctype: str) -> set[str]:
	"""Bir doctype için yazılabilir çeviri kolonları: {field}_{lang} + content_default_lang."""
	fields = CONTENT_TRANSLATABLE_FIELDS.get(doctype, {})
	cols = {"content_default_lang"} if fields else set()
	for field in fields:
		for lang in CONTENT_LANGS:
			cols.add(f"{field}_{lang}")
	return cols


def apply_translation_payload(doc, payload) -> None:
	"""Panel'den gelen çeviri payload'ını (dict veya JSON string) doc'a uygula.

	Yalnızca o doctype'ın bilinen çeviri kolonlarına izin verilir (keyfi alan yazımı yok).
	"""
	if not payload:
		return
	if isinstance(payload, str):
		import json

		try:
			payload = json.loads(payload)
		except (ValueError, TypeError):
			return
	if not isinstance(payload, dict):
		return
	allowed = translatable_columns(doc.doctype)
	for key, value in payload.items():
		if key in allowed:
			doc.set(key, value)


def sync_content_translations(doc) -> None:
	"""Base kolon ↔ varsayılan-dil kolonu senkronu + zorunlu-dil kontrolü.

	- `content_default_lang` boş/geçersizse `tr`'ye normalize edilir.
	- Base kolon (örn. `title`) doğrudan yazılmış ama `{field}_{default}` boşsa
	  (eski/storefront create akışı), değer varsayılan-dil koluna kopyalanır.
	- Zorunlu (reqd) alanın varsayılan-dil değeri hâlâ boşsa i18n hatası verilir.
	- Aksi halde base kolon = `{field}_{default}` (Desk/arama/ERPNext-sync görsün).
	"""
	fields = CONTENT_TRANSLATABLE_FIELDS.get(doc.doctype)
	if not fields:
		return

	default_lang = normalize_lang(doc.get("content_default_lang"))
	doc.content_default_lang = default_lang

	# Parent alanları.
	for field, spec in fields.items():
		_sync_field(doc, field, default_lang, required=bool(spec.get("reqd")))

	# Child-table alanları (teknik özellikler + varyantlar) — aynı default dil.
	for table_field, child_doctype in CONTENT_CHILD_TABLES.get(doc.doctype, []):
		child_fields = CONTENT_CHILD_TRANSLATABLE_FIELDS.get(child_doctype, {})
		if not child_fields:
			continue
		for row in doc.get(table_field) or []:
			for field in child_fields:
				_sync_field(row, field, default_lang)

# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""Medya motoru ayarları — Dalga A özellik bayraklarının tek kaynağı.

Değerleri kod tarafında OKUMAK için `tradehub_core.media.pipeline_flags`
kullanılır; bu controller yalnızca doğrulama ve önbellek düşürme yapar.
Yazma yetkisi DocType JSON'ında System Manager ile sınırlı.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.media import pipeline_flags


class MediaEngineSettings(Document):
	def validate(self) -> None:
		# Frappe v15'te Document.validate yok; varsa çağır (repo konvansiyonu).
		super().validate() if hasattr(super(), "validate") else None
		self._slot_anahtarlarini_dogrula()
		self._rendition_tavanini_dogrula()

	def on_update(self) -> None:
		# Kaydeden kullanıcı aynı istekte eski değeri görmesin.
		pipeline_flags.clear_cache()

	def _slot_anahtarlarini_dogrula(self) -> None:
		"""Yazım hatası olan slot anahtarı sessizce kapalı kalırdı; erken uyar."""
		anahtarlar = pipeline_flags.parse_slot_keys(self.active_slots)
		bilinmeyen = sorted(
			anahtar
			for anahtar in anahtarlar
			if anahtar != pipeline_flags.SLOT_WILDCARD and anahtar not in pipeline_flags.KNOWN_SLOT_KEYS
		)
		if bilinmeyen:
			frappe.throw(
				_("Bilinmeyen slot anahtarı: {0}. Geçerli anahtarlar: {1}").format(
					", ".join(bilinmeyen),
					", ".join(sorted(pipeline_flags.KNOWN_SLOT_KEYS)),
				)
			)

	def _rendition_tavanini_dogrula(self) -> None:
		"""0 / negatif tavan, kaçak üretime karşı korumayı sessizce kaldırırdı."""
		if int(self.max_renditions_per_asset or 0) < 1:
			frappe.throw(_("Varlık başına maksimum rendition sayısı 1'den küçük olamaz."))

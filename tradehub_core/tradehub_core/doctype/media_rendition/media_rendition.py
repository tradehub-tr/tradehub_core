# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Media Rendition — servis edilen tek artefakt.

Bir rendition "şu Asset'in, şu profille, şu genişlikte, şu biçimde üretilmiş
hali"dir. Tarayıcıya giden `src`/`srcset` değerleri buradan çıkar; master
dosya kullanıcıya asla verilmez.

Tekillik
--------
(asset, profile, width, format) DÖRTLÜSÜ tektir. Frappe DocType JSON'u bileşik
unique index ifade edemediği için dörtlü `rendition_key` alanına indirgenir ve
UNIQUE kısıt orada durur. İkinci üretim denemesi DB'ye çarpar (UniqueValidationError); çağıran taraf
bunu idempotent davranışa çevirir (media/pipeline/core/dedup.py, INV-06).
Kaynak şema (doctype_specs/media_rendition.json) tekilliği ham SQL'deki
bileşik indekse bırakmıştı; A1a'da ham DDL çalıştırılmıyor, bu yüzden
tekilliği türetilmiş alan taşıyor — sapma bilinçlidir.

`benefit_gate_passed` 0 olan türev ÜRETİLİR ama SERVİS EDİLMEZ: kaynaktan
büyük çıkan bir "optimizasyon" sayfayı yavaşlatır.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class MediaRendition(Document):
	def validate(self) -> None:
		# Document taban sınıfında `validate` yok; repo deseni bu korumalı çağrı.
		if hasattr(super(), "validate"):
			super().validate()
		self._validate_geometry()
		self._derive_rendition_key()
		self._stamp_generated_at()

	def _validate_geometry(self) -> None:
		"""Genişlik/yükseklik pozitif olmalı — 0 piksellik türev servis edilemez."""
		if not self.width or int(self.width) <= 0:
			frappe.throw(_("Genişlik pozitif olmalı."))
		if self.height is not None and self.height != 0 and int(self.height) < 0:
			frappe.throw(_("Yükseklik negatif olamaz."))
		if self.bytes is not None and self.bytes != 0 and int(self.bytes) < 0:
			frappe.throw(_("Bayt değeri negatif olamaz."))

	def _derive_rendition_key(self) -> None:
		"""Dörtlüyü tek unique alana indirger (bileşik unique index yerine)."""
		self.rendition_key = "|".join(
			(
				self.asset or "",
				self.profile or "",
				str(int(self.width or 0)),
				self.format or "",
			)
		)

	def _stamp_generated_at(self) -> None:
		"""Dosya adresi ilk kez yazıldığında üretim zamanını damgalar.

		`creation` yeterli değil: lazy üretimde kayıt önce açılır, dosya sonra
		yazılır; ikisini karıştırmak "üretim süresi" ölçümünü bozar.
		"""
		if self.file_url and not self.generated_at:
			self.generated_at = now_datetime()

	# --- Public API ---

	def is_servable(self) -> bool:
		"""Bu türev tarayıcıya verilebilir mi (dosyası var ve fayda kapısını geçti)?"""
		return bool(self.file_url) and bool(self.benefit_gate_passed)

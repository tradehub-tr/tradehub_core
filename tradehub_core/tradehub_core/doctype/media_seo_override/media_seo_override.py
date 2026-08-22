# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt
"""Kullanım başına SEO ezmesi — controller.

Kayıt açan/okuyan tek yer `media/seo.py`; buradaki iş yalnız veri
bütünlüğü. Anahtar dörtlüsü `(file_url, ref_doctype, ref_name, ref_field)`
tekil olmalı: aynı kullanım için iki ezme, hangisinin geçerli olduğunu
belirsiz bırakırdı. Tekillik veritabanı indeksiyle de kilitleniyor
(patch `v15_9_38`), burada erken ve okunur hata veriyoruz.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class MediaSEOOverride(Document):
	def validate(self) -> None:
		# super().validate() — Frappe v15: `Document.validate` YOK (repoda
		# `eca_action_template`, `carrier_account` aynı notu taşıyor).
		self.file_url = (self.file_url or "").split("?")[0].strip()
		if not self.file_url.startswith("/"):
			frappe.throw(_("Geçersiz dosya adresi: {0}").format(self.file_url))

		ikiz = frappe.db.exists(
			"Media SEO Override",
			{
				"file_url": self.file_url,
				"ref_doctype": self.ref_doctype,
				"ref_name": self.ref_name,
				"ref_field": self.ref_field,
				"name": ["!=", self.name or ""],
			},
		)
		if ikiz:
			frappe.throw(
				_("Bu kullanım için zaten bir SEO ezmesi var: {0}").format(ikiz),
				exc=frappe.DuplicateEntryError,
			)

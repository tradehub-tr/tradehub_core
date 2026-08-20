# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Media Crop Override — profil bazlı elle kırpım (öncelik zincirinin 1. sırası).

Bu child tablo `Media Crop Intent.overrides` altında yaşar. Bir satır "şu
profilde kadraj TAM OLARAK burasıdır" der ve `core/crop.py:resolve_crop()`
zincirinin en üst seviyesidir — güvenli alan, odak, smartcrop ve merkez
seviyelerinin hepsini geçersiz kılar.

NEDEN DOĞRULAMA BURADA DA VAR
-----------------------------
`api/media_crop.py` yazma yolunda kütüphanenin doğrulayıcılarını çağırıyor.
Ama DocType'a yazan tek yol o değil: bir yama, bir konsol oturumu ya da
ileride yazılacak ikinci bir uç aynı tabloya `frappe.get_doc` ile yazabilir.
0-1 sözleşmesi (INV-10) veri katmanında da tutulmazsa, kadraj matematiği
kendisine yalan söylenen bir girdiyle çalışır.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

#: 0-1 karşılaştırmalarında kayan nokta toleransı — `api/crop.py` ile aynı değer.
EPSILON: float = 1e-6


class MediaCropOverride(Document):
	def validate(self) -> None:
		# Document taban sınıfında `validate` yok; repo deseni bu korumalı çağrı
		# (bkz. media_asset.py) — ileride taban sınıf kazanırsa zincir kırılmasın.
		if hasattr(super(), "validate"):
			super().validate()
		self._validate_unit_box()

	def _validate_unit_box(self) -> None:
		"""Dört koordinat 0-1 aralığında ve kutu kaynağın içinde olmalı.

		KELEPÇELEME DEĞİL REDDETME: aralık dışı bir değer sessizce 1.0'a
		çekilseydi, kullanıcı çizmediği bir kadrajı kaydedilmiş sanırdı.
		`envelope.require_unit` de aynı kararı veriyor (400) ve gerekçesi
		`core/crop.py` modül başlığında yazılı — piksel koordinatı kabul
		edilirse kaynak yeniden boyutlandığında kadraj kayar.
		"""
		for alan in ("x", "y", "w", "h"):
			deger = self.get(alan)
			if deger is None:
				frappe.throw(_("Kırpma istisnasında `{0}` alanı zorunlu.").format(alan))
			if not (0.0 <= float(deger) <= 1.0):
				frappe.throw(
					_("Kırpma istisnasında `{0}` 0 ile 1 arasında olmalı (normalize koordinat, INV-10): {1}").format(
						alan, deger
					)
				)

		if float(self.w) <= 0.0 or float(self.h) <= 0.0:
			frappe.throw(_("Kırpma istisnasının genişliği ve yüksekliği sıfırdan büyük olmalı."))

		if float(self.x) + float(self.w) > 1.0 + EPSILON or float(self.y) + float(self.h) > 1.0 + EPSILON:
			frappe.throw(_("Kırpma istisnası kaynağın dışına taşıyor: {0}").format(self.profile))

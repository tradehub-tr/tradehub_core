# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Media Usage — bir dosyanın NEREDE kullanıldığının KALICI kaydı.

`media/usage.py`'deki URL taraması (17 canlı + 5 sipariş alanında `LOCATE`)
bu tablonun YERİNE geçmez, onu BESLER: tarama pahalıdır (ölçüldü: derin
tarama 3.546 ms/50 dosya) ve süreç ömrü kadar yaşayan bir sözlükte tutulursa
her yeniden başlatmada kaybolur. Öksüz kararı (`retention.py`) bu satırlara
bakar.

NEDEN SİLMİYORUZ, KAPATIYORUZ
-----------------------------
Referans kaldırıldığında satır silinmez; `is_open` 0'a çekilir ve `last_seen`
damgalanır. "Hiç kullanılmadı" ile "kullanılıyordu, kaldırıldı" aynı şey
değildir: ikincisi geri alınabilir bir kullanıcı hatası olabilir ve GC'nin
kararı bu ayrıma dayanır.

NEDEN DOĞRULAMA BURADA DA VAR
-----------------------------
Üretim yolu (`core/usage.py::FrappeUsageBackend`) bilerek ham SQL kullanıyor —
22 görselli bir üründe 22 doküman kurmak okuma yolunu geciktirirdi. Ama tabloya
yazan tek yol o değil: bir yama, bir konsol oturumu ya da desk formu
`frappe.get_doc` ile yazabilir. `usage_key` türetimi iki yolda da AYNI olmak
zorunda, yoksa aynı bağ iki farklı anahtarla iki kez görünür.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

#: Dörtlüyü tek dizgeye indiren ayraç. `core/usage.py::_key` ile AYNI olmak
#: zorunda — iki yol farklı ayraç kullanırsa aynı bağ iki anahtar üretir.
AYRAC: str = "|"


def usage_key_of(asset: str, ref_doctype: str, ref_name: str, ref_field: str) -> str:
	"""(asset, ref_doctype, ref_name, ref_field) → okunabilir tekillik anahtarı."""
	return AYRAC.join((asset or "", ref_doctype or "", ref_name or "", ref_field or ""))


class MediaUsage(Document):
	def validate(self) -> None:
		# Document taban sınıfında `validate` yok; repo deseni bu korumalı
		# çağrı (bkz. media_rendition.py) — taban sınıf ileride kazanırsa
		# zincir kırılmasın.
		if hasattr(super(), "validate"):
			super().validate()
		self._validate_ref()
		self._derive_usage_key()
		self._stamp_first_seen()

	def _validate_ref(self) -> None:
		"""Dörtlünün hiçbir parçası boş olamaz.

		Boş `ref_field` ile yazılmış bir satır, `uk_usage_quad` üzerinde aynı
		(asset, doctype, name) için TEK satıra sıkışır ve ikinci alandaki
		kullanım sessizce birincinin üstüne yazılır — yani bir kullanım
		kaydı kaybolur ve dosya erken silinebilir hâle gelir.
		"""
		for alan in ("asset", "ref_doctype", "ref_name", "ref_field"):
			if not (self.get(alan) or "").strip():
				frappe.throw(_("Kullanım kaydında `{0}` alanı zorunlu.").format(alan))

	def _derive_usage_key(self) -> None:
		self.usage_key = usage_key_of(
			self.asset, self.ref_doctype, self.ref_name, self.ref_field
		)

	def _stamp_first_seen(self) -> None:
		"""İlk görülme YALNIZ bir kez yazılır — kapanıp yeniden açılsa bile.

		`creation` yeterli değil: satır kapatılıp (is_open=0) sonra aynı bağ
		yeniden kurulduğunda kayıt GÜNCELLENİR, yeniden yaratılmaz; o yüzden
		`creation` ile `first_seen` aynı şeyi ölçmez.
		"""
		if not self.first_seen:
			self.first_seen = self.last_seen or frappe.utils.now_datetime()

# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Media Asset — yeni medya hattının varlık kimliği.

Bir Media Asset "şu satıcının, şu slotta kullandığı şu içerik" demektir.
Dosyanın kendisi hâlâ Frappe `File` kaydıdır; Asset onun ÜSTÜNDE durur ve
File'ın taşıyamadığı üç şeyi taşır: slot politikası, işleme durumu, sahiplik.

`File` ile 1:1 DEĞİLDİR
----------------------
Aynı File birden çok Asset'e hizmet edebilir (aynı görsel hem ürün hem
mağaza kapağı slotunda kullanılabilir), aynı içerik iki satıcı tarafından
ayrı ayrı yüklenmiş olabilir. Bu yüzden `content_sha256` TEK BAŞINA unique
değildir; tekillik (owner_seller, slot_key, content_sha256) üçlüsündedir ve
türetilmiş `asset_key` alanı tarafından veritabanı düzeyinde zorlanır.
Aynı satıcı aynı dosyayı aynı slota ikinci kez yüklerse ikinci kayıt DB'ye
çarpar ve çağıran taraf mevcut Asset'i döndürür (INV-06, idempotency).

MEVCUT AKIŞLA İLİŞKİ (hiçbiri değiştirilmedi)
---------------------------------------------
* `media/states.py` — File'ın yaşam döngüsü (Active/Archived/Trashed/Deleted).
  Bu alan BAŞKA bir eksendir: oradaki durum "dosya çöpte mi", buradaki
  `state` "işleme hattının neresinde". İkisi birbirini geçersiz kılmaz.
* `media/engine.py:to_webp`, `media/transcode.py` — bugünkü optimize/transcode
  yolu. Asset kaydı bunları çağırmaz; yeni hat PARALEL çalışır.
* `media/audit.py` — mevcut denetim kancaları olduğu gibi durur.

DALGA A notu: `media_pipeline_enabled` bayrağı KAPALIYKEN boru hattı bu
tabloya hiçbir şey yazmaz; DocType'ın varlığı hattın davranışını değiştirmez.
W7'den (rapor 64 EK-2) beri TEK istisna var ve bayraktan bağımsızdır:
`media/files.py::record_original_hash`, dönüştürülen yüklemenin orijinal
sha256'sını `state="draft"` bir varlığa yazar — tekilleştirme araması boru
hattı kapalıyken de çalışmak zorunda, bayrağa bağlansaydı operatörün türev
üretimini kapatması dedup uyarısını da sessizce öldürürdü.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

# `ready` yayına çıkmış demektir; `published_at` bu duruma ilk geçişte damgalanır.
_PUBLISHED_STATES: frozenset[str] = frozenset({"ready"})

# Red kodu olmadan reddedilen varlık, sebebi kaybolmuş varlıktır.
_REJECTED_STATE: str = "rejected"


class MediaAsset(Document):
	def validate(self) -> None:
		# Document taban sınıfında `validate` yok; repo deseni bu korumalı çağrı
		# (bkz. seo_redirect.py) — ileride taban sınıf kazanırsa zincir kırılmasın.
		if hasattr(super(), "validate"):
			super().validate()
		self._normalize_hashes()
		self._validate_rejection()
		self._derive_asset_key()
		self._stamp_published_at()

	def _normalize_hashes(self) -> None:
		"""Hash alanları küçük harfe indirgenir — aynı içerik iki yazımla iki kayıt olmasın."""
		if self.content_sha256:
			self.content_sha256 = self.content_sha256.strip().lower()
		if self.perceptual_hash:
			self.perceptual_hash = self.perceptual_hash.strip().lower()
		if self.slot_key:
			self.slot_key = self.slot_key.strip()

	def _validate_rejection(self) -> None:
		"""state='rejected' ise red kodu zorunlu (DocType reqd yapılamaz: diğer durumlarda boş)."""
		if self.state == _REJECTED_STATE and not (self.rejection_code or "").strip():
			frappe.throw(_("Reddedilen varlık için red kodu zorunludur."))

	def _derive_asset_key(self) -> None:
		"""(owner_seller, slot_key, content_sha256) üçlüsünü tek unique alana indirger.

		Frappe DocType JSON'u bileşik unique index ifade edemez; standart çözüm
		türetilmiş tek alandır. Sistem üretimi varlıklarda satıcı boştur — boş
		parça ayraçlar arasında boş kalır, üçlünün konumu korunur.
		"""
		if not self.content_sha256:
			# Hash henüz hesaplanmamış (draft yükleme). Tekillik anahtarı da yok.
			self.asset_key = None
			return
		self.asset_key = "|".join(
			(
				self.owner_seller or "",
				self.slot_key or "",
				self.content_sha256,
			)
		)

	def _stamp_published_at(self) -> None:
		"""`ready`ye ilk geçişte yayın zamanını damgalar; geri dönüşte silmez."""
		if self.state in _PUBLISHED_STATES and not self.published_at:
			self.published_at = now_datetime()

	# --- Public API ---

	def is_servable(self) -> bool:
		"""Bu varlık son kullanıcıya servis edilebilir mi?"""
		return self.state == "ready"

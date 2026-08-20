# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Media Profile — türev üretim reçetesi (VERİ, kod değil).

Bir profil "şu slot için, şu oranda, şu genişliklerde, şu biçimlerde üret"
der. Yeni bir srcset basamağı eklemek kod değişikliği değil, kayıt
değişikliğidir. Kaynak veri: `tradehub_core/media/pipeline/policy/slots/*.json`
dosyalarındaki `profiles` blokları — tohumlama ayrı bir görevde yapılır.

`aspect_ratio` metin ("1:1"), `aspect_ratio_value` onun sayısal karşılığıdır
(G/Y) ve burada TÜRETİLİR; sorgu ve karşılaştırma metin ayrıştırmadan
yapılabilsin diye. Serbest oranda ikisi de BOŞ kalır — 0.0 yazmak "oran
serbest" ile "oran sıfır"ı karıştırırdı.

DALGA A notu: bu DocType kurulu olsa da `media_pipeline_enabled` bayrağı
kapalıyken hiçbir okuma/yazma yolu bu kayıtlara bakmaz; mevcut medya akışı
(engine.to_webp, transcode, media/states.py) DEĞİŞMEDİ.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document

# Sığdırma modu ile oran zorunluluğu ilişkisi: cover kırpar, kırpmak için
# hedef oran gerekir. contain/pad oranı korur, hedef oran opsiyoneldir.
_FIT_REQUIRES_RATIO: frozenset[str] = frozenset({"cover"})


class MediaProfile(Document):
	def validate(self) -> None:
		# Document taban sınıfında `validate` yok; repo deseni bu korumalı çağrı
		# (bkz. seo_redirect.py) — ileride taban sınıf kazanırsa zincir kırılmasın.
		if hasattr(super(), "validate"):
			super().validate()
		self._validate_widths()
		self._validate_formats()
		self._derive_aspect_ratio_value()
		self._validate_fit_ratio_consistency()

	def _validate_widths(self) -> None:
		"""`widths` artan sıralı, pozitif tamsayılardan oluşan bir dizi olmalı."""
		widths = self.get_widths()
		if not widths:
			return
		if any((not isinstance(w, int)) or w <= 0 for w in widths):
			frappe.throw(_("Genişlikler yalnız pozitif tam sayı olabilir: {0}").format(self.widths))
		if widths != sorted(widths):
			frappe.throw(_("Genişlikler artan sırada olmalı: {0}").format(self.widths))
		if len(set(widths)) != len(widths):
			frappe.throw(_("Genişlikler tekrar edemez: {0}").format(self.widths))

	def _validate_formats(self) -> None:
		"""`formats` tercih sırasına göre, bilinen biçim adlarından oluşmalı."""
		formats = self.get_formats()
		if not formats:
			return
		allowed = {"webp", "avif", "jpeg", "png", "webm", "mp4"}
		unknown = [f for f in formats if f not in allowed]
		if unknown:
			frappe.throw(
				_("Bilinmeyen biçim(ler): {0}. İzin verilen: {1}").format(
					", ".join(str(u) for u in unknown), ", ".join(sorted(allowed))
				)
			)

	def _derive_aspect_ratio_value(self) -> None:
		"""'G:Y' metnini sayısal orana çevirir; serbest oranda alanı boşaltır."""
		raw = (self.aspect_ratio or "").strip()
		if not raw:
			self.aspect_ratio_value = None
			return
		parts = raw.split(":")
		if len(parts) != 2:
			frappe.throw(_("En-boy oranı 'G:Y' biçiminde olmalı (ör. 1:1, 16:9): {0}").format(raw))
		try:
			genislik = float(parts[0])
			yukseklik = float(parts[1])
		except ValueError:
			frappe.throw(_("En-boy oranındaki değerler sayı olmalı: {0}").format(raw))
			return
		if genislik <= 0 or yukseklik <= 0:
			frappe.throw(
				_("En-boy oranı pozitif olmalı; serbest oran için alanı BOŞ bırakın: {0}").format(raw)
			)
		self.aspect_ratio_value = genislik / yukseklik

	def _validate_fit_ratio_consistency(self) -> None:
		"""cover kırpma yapar; hedef oran olmadan neye kırpacağı tanımsızdır."""
		if self.fit in _FIT_REQUIRES_RATIO and not (self.aspect_ratio or "").strip():
			frappe.throw(_("fit='cover' için en-boy oranı zorunludur (kırpma hedefi tanımsız kalır)."))

	# --- Public API ---

	def get_widths(self) -> list[int]:
		"""`widths` alanını liste olarak döner; boş/bozuk değerde boş liste."""
		return self._parse_list("widths")

	def get_formats(self) -> list[str]:
		"""`formats` alanını liste olarak döner; boş/bozuk değerde boş liste."""
		return self._parse_list("formats")

	def _parse_list(self, fieldname: str) -> list:
		"""JSON alanını listeye çevirir. Liste değilse hata verir (sessiz geçmez)."""
		val = self.get(fieldname)
		if not val:
			return []
		if isinstance(val, list):
			return val
		try:
			parsed = json.loads(val)
		except (json.JSONDecodeError, TypeError) as e:
			frappe.throw(_("{0} geçerli JSON değil: {1}").format(fieldname, str(e)))
			return []
		if not isinstance(parsed, list):
			frappe.throw(_("{0} bir JSON dizisi olmalı.").format(fieldname))
		return parsed

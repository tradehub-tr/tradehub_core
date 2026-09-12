# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Dile özel medya ezmesi (MOGEM-620 §11).

Şartname §11 son madde: "Locale-specific image, video ve poster override'ları
desteklenmeli." Kabul kriteri 14 aynı şeyi "locale-specific media override'ı
çalışır" diye tekrarlıyor.

10 Eylül 2026 denetimi: alt/title/caption dört dilde tutuluyordu ama MEDYANIN
KENDİSİ tek dildi. Arapça vitrinde Türkçe metin basılı bir ambalaj görseli
gösteriliyordu ve bunu değiştirmenin yolu yoktu.

NEDEN AYRI DOCTYPE, NEDEN `File`'DA KOLON DEĞİL
-----------------------------------------------
Dört dil için dört kolon (`th_media_variant_tr/en/ar/ru`) ilk akla gelen
çözümdü. Reddedildi: ezme SEYREK. 4.804 görselin belki 50'sinde dile özel
karşılık olacak ve dört kolon 4.804 satırın tamamında boş duracaktı. Ayrıca
poster için dört kolon daha gerekirdi — sekiz kolonun ~%99'u boş.

Satır bazlı model ayrıca "hangi dosyaların dile özel karşılığı var" sorusunu
tek sorguda cevaplıyor; kolon modelinde bu dört ayrı `IS NOT NULL` taraması
demekti.

NEDEN `Media SEO Override`'A EKLENMEDİ
--------------------------------------
O tablo KULLANIM başına (bu sayfada bu görsel), bu ise VARLIK başına (bu dilde
bu dosya yerine şu dosya). Aynı tabloda toplamak `ref_doctype`/`ref_name`
alanlarını yarı boş bırakmak ve iki farklı sözleşmeyi tek satırda anlatmak
olurdu.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.seo.i18n import CONTENT_LANGS


class MediaLocaleVariant(Document):
	def validate(self) -> None:
		# Frappe v15'te `Document.validate` YOK; repo deseni bu korumalı çağrı
		# (bkz. `media_asset.py`) — taban sınıf ileride kazanırsa zincir kırılmasın.
		if hasattr(super(), "validate"):
			super().validate()
		self.file_url = (self.file_url or "").split("?")[0].strip()
		self.variant_url = (self.variant_url or "").split("?")[0].strip()
		self.poster_url = (self.poster_url or "").split("?")[0].strip()

		if not self.file_url:
			frappe.throw(_("Kaynak medya adresi zorunlu."))
		if self.locale not in CONTENT_LANGS:
			frappe.throw(_("Geçersiz dil: {0}").format(self.locale))
		if not (self.variant_url or self.poster_url):
			# İkisi de boşsa satır hiçbir şey ezmiyor demektir. Böyle bir
			# satır sessizce durup "ezme tanımlı" yanılsaması üretirdi.
			frappe.throw(_("Dile özel medya ya da poster alanlarından en az biri dolu olmalıdır."))
		if self.variant_url == self.file_url:
			frappe.throw(_("Dile özel medya, kaynağın kendisi olamaz."))

		self._tekillik()

	def _tekillik(self) -> None:
		"""Aynı (dosya, dil, mağaza) üçlüsü için ikinci satır olamaz.

		DocType düzeyinde unique index yerine kod kontrolü: `store` NULL
		olabiliyor (platform geneli ezme) ve MariaDB'de NULL'lar unique
		index'te birbirini engellemez — yani veritabanı kısıtı tam da en
		çok gerektiği durumda (mağazasız satır) sessizce delinirdi.
		"""
		# `store` NULL DA olabilir BOŞ DİZE de — Frappe Link alanını
		# doldurulmadığında NULL, formdan boş geldiğinde "" yazıyor.
		# `{"store": ""}` filtresi NULL satırı BULMAZ ve tekillik kontrolü
		# tam da platform geneli (mağazasız) satırlarda sessizce delinirdi.
		# Ölçüldü 10 Eyl 2026: `test_ayni_dosya_dil_ikili_kaydi_reddedilir`
		# ikinci kaydı sorunsuz açıyordu.
		# `["in", ["", None]]` İŞE YARAMAZ: SQL'de `x IN (NULL)` hiçbir zaman
		# doğru değildir, yani NULL satır yine kaçardı. Frappe'nin `["is",
		# "not set"]` operatörü `IFNULL(col, '') = ''`e çevriliyor ve ikisini
		# birden yakalayan tek ifade bu.
		magaza_kosulu = ["is", "not set"] if not self.store else ["=", self.store]
		ikiz = frappe.db.get_value(
			self.doctype,
			{
				"file_url": self.file_url,
				"locale": self.locale,
				"store": magaza_kosulu,
				"name": ["!=", self.name or ""],
			},
			"name",
		)
		if ikiz:
			frappe.throw(_("Bu dosya ve dil için zaten bir ezme tanımlı: {0}").format(ikiz))

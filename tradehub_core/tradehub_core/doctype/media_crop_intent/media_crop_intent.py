# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Media Crop Intent — bir varlığın kırpma niyeti.

"Niyet" ile "kadraj" AYNI ŞEY DEĞİLDİR. Bu kayıt kullanıcının/algoritmanın ne
istediğini tutar; her profil için gerçekte kullanılacak pencereyi
`core/crop.py:resolve_crop()` öncelik zinciriyle çözer (override → güvenli
alan+odak → odak → smartcrop → merkez). Bu yüzden `method` alanı niyetin
KAYNAĞINI söyler, seçilen pencereyi değil — spec'in alan açıklamasındaki ayrım
budur ve burada korunur.

TEKİLLİK — 1:1
--------------
`autoname: field:asset` docname'i varlık adına eşitler; `asset` alanı ayrıca
`unique: 1` taşır. İkisi birlikte "bir varlığın tek niyeti olur" kuralını
veritabanı düzeyinde zorlar. `api/media_crop.save_intent` bunu ikinci bir kayıt
açmaya çalışmak yerine mevcut kaydı GÜNCELLEYEREK karşılar (idempotency); yani
uç iki kez çağrıldığında satır sayısı artmaz.

0-1 SÖZLEŞMESİ VERİ KATMANINDA DA TUTULUR
-----------------------------------------
Bütün koordinatlar normalize (INV-10). Aralık dışı değer KELEPÇELENMEZ,
REDDEDİLİR — gerekçe `media_crop_override.py:_validate_unit_box` ile aynı:
sessizce düzeltilen bir koordinat, kullanıcının çizmediği bir kadrajı
"kaydedildi" diye göstermek demektir.

KİRACI İZOLASYONU
-----------------
Bu DocType sahiplik kolonu TAŞIMAZ. İzolasyon `asset` üzerinden
`Media Asset.owner_seller`a zincirlenir; kancalar
`permissions.media_crop_intent_query_conditions` / `..._has_permission`
içindedir (Media Rendition ve Media Processing Job ile birebir aynı desen).
Denormalize bir `seller` kolonu bilinçli olarak eklenmedi: kopyalanan sahiplik
alanı, Asset devredildiğinde sessizce eskir ve kiracı sızıntısının en yaygın
kaynağı olur.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document

# Zoom sınırları çözücü katmandan gelir (`core/crop.py`, o da değerleri
# `core/crop_geometry.py` ile eş tutar — gerekçe orada). Buradan import
# edilir ki şema doğrulaması ile pencere kurulumu tek kaynaktan sapamasın.
from tradehub_core.media.pipeline.core.crop import ZOOM_MAX, ZOOM_MIN

#: 0-1 karşılaştırmalarında kayan nokta toleransı — `pipeline/api/crop.py` ile aynı değer.
EPSILON: float = 1e-6

#: Normalize koordinat taşıyan skaler alanlar.
UNIT_FIELDS: tuple[str, ...] = (
	"focal_x",
	"focal_y",
	"safe_x",
	"safe_y",
	"safe_w",
	"safe_h",
	"center_x",
	"center_y",
	"confidence",
)

#: Güvenli alanı oluşturan dörtlü — ya dördü birden yazılır ya hiçbiri.
SAFE_FIELDS: tuple[str, ...] = ("safe_x", "safe_y", "safe_w", "safe_h")

#: Odak çifti — biri yazılıp diğeri boş bırakılamaz.
FOCAL_FIELDS: tuple[str, ...] = ("focal_x", "focal_y")


class MediaCropIntent(Document):
	def validate(self) -> None:
		# Document taban sınıfında `validate` yok; repo deseni bu korumalı çağrı
		# (bkz. media_asset.py) — ileride taban sınıf kazanırsa zincir kırılmasın.
		if hasattr(super(), "validate"):
			super().validate()
		self._validate_units()
		self._validate_pairs()
		self._validate_safe_box()
		self._validate_zoom()
		self._validate_previewed_placements()
		self._validate_approval_evidence()
		self._validate_override_profiles()

	def _validate_units(self) -> None:
		"""Her normalize alan 0-1 aralığında olmalı. Boş alan geçerlidir.

		Boş = "kullanıcı hiç seçmedi"; 0.5 = "kullanıcı merkezi seçti". İki
		durum `core/crop.py:focal_of` dokümanında ayrı seviyelerdir, bu yüzden
		boş alan varsayılanla DOLDURULMAZ.
		"""
		for alan in UNIT_FIELDS:
			deger = self.get(alan)
			if deger is None or deger == "":
				continue
			if not (0.0 <= float(deger) <= 1.0):
				frappe.throw(
					_("`{0}` 0 ile 1 arasında olmalı (normalize koordinat, INV-10): {1}").format(alan, deger)
				)

	def _validate_pairs(self) -> None:
		"""Odak çifti ve güvenli alan dörtlüsü ya tam ya hiç yazılır.

		Yarım yazılmış bir odak (`focal_x` var, `focal_y` yok) zincirde sessizce
		bir alt seviyeye düşerdi; kullanıcı kadrajı kaydettiğini sanır, sistem
		merkeze düşer. Yazma tarafında sessizlik yanlıştır (aynı gerekçe
		`pipeline/api/crop.py:_parse_overrides` içinde yazılı).
		"""
		yazili = [a for a in FOCAL_FIELDS if self.get(a) is not None and self.get(a) != ""]
		if len(yazili) == 1:
			frappe.throw(_("`focal_x` ve `focal_y` birlikte verilmeli."))

		yazili_safe = [a for a in SAFE_FIELDS if self.get(a) is not None and self.get(a) != ""]
		if 0 < len(yazili_safe) < len(SAFE_FIELDS):
			frappe.throw(_("Güvenli alan dört alanıyla birlikte verilmeli: safe_x, safe_y, safe_w, safe_h."))

	def _validate_safe_box(self) -> None:
		"""Güvenli alan TANIMLIYSA kaynağın dışına taşamaz.

		"Tanımlı" = `safe_w > 0 ve safe_h > 0`. Sıfır alanlı kutu HATA DEĞİL,
		**tanımsızlıktır** — ve bunun nedeni şema: Frappe `Float` kolonları
		`NOT NULL DEFAULT 0`dır, yani "hiç yazılmadı" ile "0 yazıldı" veritabanı
		düzeyinde AYIRT EDİLEMEZ. Kayıt bir kez DB'ye gidip geri geldiğinde
		yazılmamış güvenli alan (0,0,0,0) olarak döner; burada hata fırlatmak,
		güvenli alanı hiç kullanmayan her kaydın İKİNCİ save'ini kırardı
		(ölçüldü: `test_save_intent_is_idempotent`).

		Aynı kuralı `core/crop.py:safe_region_of` zaten uyguluyor (`w <= 0 or
		h <= 0` → None), yani iki katman aynı tanımı paylaşır. Kullanıcının
		gerçekten sıfır alanlı bir kutu ÇİZMESİ ayrı bir olaydır ve API
		katmanında yakalanır: `pipeline/api/crop.py:_parse_safe_area` gövdede
		`w <= 0` görürse 400 döner.
		"""
		if any(self.get(a) is None or self.get(a) == "" for a in SAFE_FIELDS):
			return
		x, y, w, h = (float(self.get(a)) for a in SAFE_FIELDS)
		if w <= 0.0 or h <= 0.0:
			return
		if x + w > 1.0 + EPSILON or y + h > 1.0 + EPSILON:
			frappe.throw(_("Güvenli alan kaynağın dışına taşıyor."))

	def _validate_zoom(self) -> None:
		"""Zoom YAZILMIŞSA `[ZOOM_MIN, ZOOM_MAX]` içinde olmalı.

		"Yazılmış" = `zoom >= ZOOM_MIN` değil, `zoom != 0`: Frappe `Float`
		kolonu `NOT NULL DEFAULT 0`dır ve 0 "hiç yazılmadı" demektir
		(`_validate_safe_box` ile aynı şema kısıtı). 0 < zoom < 1 gibi bir
		değer ise yazılmış AMA geçersizdir — kaynağın dışını gösteren bir
		taban bölge ister ve KELEPÇELENMEZ, reddedilir (0-1 sözleşmesiyle
		aynı gerekçe: sessiz düzeltme, kullanıcının çizmediği kadrajı
		"kaydedildi" diye göstermektir).
		"""
		deger = self.get("zoom")
		if deger is None or deger == "" or float(deger) == 0.0:
			return
		z = float(deger)
		if not (ZOOM_MIN <= z <= ZOOM_MAX):
			frappe.throw(
				_("`zoom` {0} ile {1} arasında olmalı: {2}").format(ZOOM_MIN, ZOOM_MAX, z)
			)

	def _validate_previewed_placements(self) -> None:
		"""JSON alanı gerçekten ayrıştırılabilir olmalı.

		Bu alan "kullanıcı gördü ve onayladı" iddiasının KANITI. Ayrıştırılamayan
		bir gövde, kanıtın kendisini geçersiz kılar; sessizce saklamak denetimde
		var olmayan bir kanıt göstermek olurdu.
		"""
		ham = self.get("previewed_placements")
		if ham is None or ham == "":
			return
		if isinstance(ham, (list, dict)):
			return
		try:
			json.loads(ham)
		except (TypeError, ValueError):
			frappe.throw(_("`previewed_placements` geçerli bir JSON değil."))

	def _validate_approval_evidence(self) -> None:
		"""T-114 — onay, önizleme kanıtı olmadan KAYDEDİLEMEZ.

		Şartname (62-faz11-simulator.html → T-114 kabul kriterleri): "Kayıt
		sunucu tarafında da doğrulanıyor: eksik previewed_placements ile
		publish reddediliyor. Frontend atlatılamaz." Kapı bir ayara BAĞLI
		DEĞİLDİR — şartname zorunlu diyor.

		Kapı DocType katmanında durur ki uç atlanıp ORM ile yazılsa bile
		`approved_by_user=1` + boş kanıt geçemesin. Uç katman
		(`api/media_crop._FrappeCropIntents.save`) aynı kuralı 400 +
		`MEDIA_PREVIEW_REQUIRED` koduyla, kullanıcıya okunur biçimde önce
		söyler; burası son savunma hattıdır.

		Eski kayıtlar migrate'te ELLENMEZ: validate yalnız yazma anında
		çalışır. `approved_by_user=1` + boş kanıtla duran eski bir kayıt,
		bir sonraki yazımında bu kapıya takılır — iddiası ("gördü ve
		onayladı") kanıtsızsa kaydın güncellenmesi de kanıt ister.
		"""
		if not self.approved_by_user:
			return
		ham = self.get("previewed_placements")
		bos = ham is None or ham == ""
		if not bos and isinstance(ham, (list, dict)):
			bos = not ham
		elif not bos:
			try:
				bos = not json.loads(ham)
			except (TypeError, ValueError):
				# Ayrıştırılamayan gövdeyi _validate_previewed_placements
				# zaten reddediyor; burada boş saymak çifte hata üretirdi.
				bos = False
		if bos:
			frappe.throw(
				_(
					"Onay, önizleme kanıtı olmadan kaydedilemez: `previewed_placements` boş. "
					"Yerleşimleri simülatörde görüp onaylayın. (MEDIA_PREVIEW_REQUIRED)"
				)
			)

	def _validate_override_profiles(self) -> None:
		"""Aynı profil için iki istisna satırı olamaz.

		`core/crop.py:override_for` ilk eşleşen satırı alır; ikinci satır sessizce
		ölü veri olurdu. Kullanıcı iki farklı kadraj çizdiğini sanırken biri
		hiç uygulanmaz.
		"""
		gorulen: set[str] = set()
		for satir in self.get("overrides") or []:
			anahtar = (satir.get("profile") or "").strip()
			if not anahtar:
				continue
			if anahtar in gorulen:
				frappe.throw(_("Aynı profil için iki kırpma istisnası verildi: {0}").format(anahtar))
			gorulen.add(anahtar)

	# --- Public API ---

	def _focal_ciftli(self) -> tuple[float | None, float | None]:
		"""Odak çifti; YAZILMAMIŞSA `(None, None)`.

		ŞEMA KISITI: Frappe `Float` kolonu `NOT NULL DEFAULT 0`dır — "hiç
		seçilmedi" ile "(0,0) seçildi" veritabanında AYNI görünür. Bu ayrım
		`core/crop.py:focal_of` için kritik: odak yazılmamışsa zincir 5.
		seviyeye (merkez) düşmeli, yazılmışsa 3. seviyede (odak) kalmalı.

		Ayrımı korumak için tam `(0.0, 0.0)` "yazılmamış" sayılır. Bedeli
		açıktır ve kabul edilmiştir: kullanıcı odağı görselin TAM sol üst
		köşesine (0.000000, 0.000000) koyarsa niyet merkeze düşer. Bu, altı
		ondalık hassasiyetle isabet etmesi gereken tek bir noktadır ve
		köşedeki bir odağın ürettiği pencere zaten köşeye yaslanır. Alternatif
		bir `has_focal` bayrağı eklemek olurdu — spec'te olmayan bir alan icat
		etmek, kaydedilen veriye yalan söylemekten daha büyük bir sapma.

		Aynı daraltma deseni çekirdeğin kendisinde de var: `safe_region_of`
		dejenere tam kadrajı (0,0,1,1) "belirtilmemiş" sayıyor.
		"""
		x = self.focal_x
		y = self.focal_y
		if x is None or y is None:
			return (None, None)
		if abs(float(x)) < EPSILON and abs(float(y)) < EPSILON:
			return (None, None)
		return (x, y)

	def _safe_dortlu(self) -> tuple[Any, Any, Any, Any]:
		"""Güvenli alan; TANIMSIZSA dört `None`.

		Tanımsızlık ölçütü `_validate_safe_box` ve `core/crop.py:safe_region_of`
		ile aynı: `safe_w <= 0 veya safe_h <= 0`.
		"""
		w = float(self.safe_w or 0.0)
		h = float(self.safe_h or 0.0)
		if w <= 0.0 or h <= 0.0:
			return (None, None, None, None)
		return (self.safe_x, self.safe_y, self.safe_w, self.safe_h)

	def _zoom_uclu(self) -> tuple[Any, Any, Any]:
		"""Zoom üçlüsü; YAZILMAMIŞSA üç `None`.

		Nöbetçi `zoom`dur: alan `NOT NULL DEFAULT 0` olduğundan 0 "hiç
		yazılmadı" demektir ve `ZOOM_MIN=1` sayesinde 0 hiçbir zaman geçerli
		bir değer değildir — odaktaki (0,0) köşe kaybı burada YOKTUR.
		`center_x/center_y` yalnız zoom yazılmışken anlamlıdır; uç üçlüyü
		birlikte zorunlu kıldığı için yazılmış zoom'un merkezi daima
		açıktır (0 dahil — sol/üst kenar meşru bir pan merkezidir).
		"""
		z = float(self.zoom or 0.0)
		if z < ZOOM_MIN:
			return (None, None, None)
		return (self.zoom, self.center_x, self.center_y)

	def as_intent_mapping(self) -> dict:
		"""`core/crop.py:resolve_crop()`in beklediği niyet sözlüğü.

		Kadraj matematiği bu sınıfa DEĞİL, çekirdeğe aittir; burada yapılan tek
		şey alan adlarını çekirdeğin sözleşmesine taşımak. Yazılmamış alan
		`None` KALIR, 0.5 olmaz — şema kısıtının bu ayrımı nasıl tehdit ettiği
		ve nasıl korunduğu `_focal_ciftli` / `_safe_dortlu` içinde yazılı.
		"""
		focal_x, focal_y = self._focal_ciftli()
		safe_x, safe_y, safe_w, safe_h = self._safe_dortlu()
		zoom, center_x, center_y = self._zoom_uclu()
		return {
			"focal_x": focal_x,
			"focal_y": focal_y,
			"safe_x": safe_x,
			"safe_y": safe_y,
			"safe_w": safe_w,
			"safe_h": safe_h,
			"zoom": zoom,
			"center_x": center_x,
			"center_y": center_y,
			"method": self.method or "",
			"confidence": self.confidence,
			"approved_by_user": bool(self.approved_by_user),
			"overrides": [
				{
					"profile": o.profile,
					"x": o.x,
					"y": o.y,
					"w": o.w,
					"h": o.h,
					"method": o.method or "manual",
				}
				for o in (self.get("overrides") or [])
			],
		}

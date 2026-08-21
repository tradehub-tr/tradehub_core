"""T-082 — Kırpma uçları: `get_intent` / `save_intent` / `suggest_focal` / `preview`.

KIRPMA MATEMATİĞİ BURADA DEĞİL
------------------------------
Öncelik zinciri (override → güvenli alan+odak → odak → smartcrop → merkez),
0-1 normalize koordinat sözleşmesi (INV-10) ve simülatörle birebir aynı
pencere matematiği `tradehub_core/media/pipeline/core/crop.py`'de ZATEN var ve testli
(`tests/test_crop.py`). Bu modül tek satır kadraj matematiği yazmaz; onu
çağırır. Buradaki iş üç şeyle sınırlı:

    doğrulama    normalize koordinat gerçekten 0-1 mi, profil bu slotta var mı
    eşzamanlılık iki editör aynı niyeti aynı anda yazarsa ne olur (If-Match)
    ölçüm       odak noktası önerisi — kod tabanında KARŞILIĞI OLMAYAN tek parça

ODAK ÖNERİSİ: NE ÖLÇÜLÜYOR, NE ÖLÇÜLMÜYOR
-----------------------------------------
`core/crop.py::smartcrop_suggestion_of` bir öneriyi **okur**; öneriyi
**üreten** kod bugün yok. `suggest_focal` bu boşluğu doldurur ve bunu en ucuz
dürüst yöntemle yapar: küçültülmüş gri tonlamalı kare üzerinde kenar enerjisi
(gradyan büyüklüğü) hesaplanır, odak o enerjinin ağırlık merkezidir.

Bu bir nesne tanıma DEĞİLDİR ve öyleymiş gibi sunulmaz:

  * Yüz, ürün ya da metin aramaz. Kontrastın yoğunlaştığı yeri bulur.
  * Düz arka planlı stüdyo ürün fotoğrafında iyi çalışır (İstoç'ta baskın
    desen); kalabalık sahnede yanılır.
  * `confidence` enerjinin ne kadar TOPLANDIĞINI ölçer, önerinin doğru
    olduğunu değil.

**Eşik KALİBRE EDİLMEDİ.** `core/crop.py::SMARTCROP_CONFIDENCE_THRESHOLD`
değeri 0.5 ve kaynağında "ÖLÇÜLMEDİ" yazıyor; bu modül o değeri kullanır ve
aynı uyarıyı yanıtta `calibrated: false` alanıyla taşır. Kullanıcıya "sistem
bunu buldu" demek ile "sistem şuraya bakıyor" demek farklı iki cümledir.

PILLOW YOKSA NE OLUR
--------------------
`suggest_focal` ve görüntülü `preview` Pillow ister. Yoksa uç **hata
vermez**: merkez odak, `measured: false` ve `reason: "pillow_unavailable"` ile
200 döner. Sebebi `NFR-043` ile aynı yönde — ölçemediğin şeyi ölçülmüş gibi
göstermemek; ama kadraj çözümü (öncelik zinciri) Pillow'suz da çalıştığı için
uç noktayı tamamen kapatmak gereksiz bir kısıt olurdu.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from tradehub_core.media.pipeline.api import envelope as env
from tradehub_core.media.pipeline.contracts.errors import kod_uret
from tradehub_core.media.pipeline.core import crop as crop_core
from tradehub_core.media.pipeline.image import render as render_mod

#: Odak öneri ızgarası. 32×32: 1024 örnek, tek bir 72 MP dosyada bile
#: milisaniyeler mertebesinde. Daha büyük ızgara kenar enerjisini keskinleştirir
#: ama ağırlık merkezini anlamlı biçimde kaydırmaz (merkez zaten integraldir).
FOCAL_GRID: int = 32

#: `confidence` hesabında kullanılan yoğunlaşma kutusu — ızgaranın 1/3'ü.
#: Enerjinin bu kutu içinde kalan oranı güven sayısıdır.
FOCAL_CONCENTRATION_BOX: float = 1.0 / 3.0

#: Önizlemenin ölçüsü/biçimi/kalitesi BU MODÜLDE SABİT DEĞİLDİR: önizleme
#: `image/render.py::render_rendition` ile üretilir ve profilin kendi
#: `width`/`formats`/`encoder_quality` değerlerini kullanır. Ayrı bir önizleme
#: boyutu tanımlamak, kullanıcının gördüğü ile aldığının farklı olması demekti.
PREVIEW_USES_PROFILE: bool = True

REASON_PILLOW: str = "pillow_unavailable"
REASON_NO_SOURCE: str = "source_unavailable"
REASON_FLAT: str = "no_edge_energy"
REASON_OK: str = "measured"


# ── Portlar ─────────────────────────────────────────────────────────────


class AssetReader(Protocol):
	"""Varlık künyesi + kaynak baytları."""

	def get(self, asset: str) -> Optional[Mapping[str, Any]]:
		"""`width`, `height`, `slot_key` taşıyan sözlük ya da `None`."""
		...

	def read_source(self, asset: str) -> Optional[bytes]:
		"""Master baytları. Depoya gitmek pahalıysa `None` dönebilir —
		çağıran o zaman ölçülmemiş sonuç alır, uydurulmuş değil."""
		...


class CropIntentRepository(Protocol):
	"""`Media Crop Intent` kaydı (doctype_specs/media_crop_intent.json)."""

	def get(self, asset: str) -> Optional[Mapping[str, Any]]: ...

	def save(self, asset: str, intent: Mapping[str, Any]) -> Mapping[str, Any]: ...


# ── Odak önerisi ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FocalSuggestion:
	"""Odak önerisi ve onun ne kadar ciddiye alınacağı.

	`measured=False` ise `x`/`y` merkezdir ve `confidence=0.0`'dır; bu bir
	öneri değil, "öneri üretilemedi" bildirimidir.
	"""

	x: float = 0.5
	y: float = 0.5
	confidence: float = 0.0
	measured: bool = False
	reason: str = REASON_NO_SOURCE
	grid: int = FOCAL_GRID
	#: Eşiğin kalibre edilip edilmediği. `core/crop.py` kaynağında ÖLÇÜLMEDİ.
	threshold: float = crop_core.SMARTCROP_CONFIDENCE_THRESHOLD
	calibrated: bool = False

	@property
	def above_threshold(self) -> bool:
		return self.measured and self.confidence >= self.threshold

	def to_dict(self) -> Dict[str, Any]:
		return {
			"focal_x": round(self.x, 6),
			"focal_y": round(self.y, 6),
			"confidence": round(self.confidence, 6),
			"measured": self.measured,
			"reason": self.reason,
			"grid": self.grid,
			"threshold": self.threshold,
			"threshold_calibrated": self.calibrated,
			"above_threshold": self.above_threshold,
			"method": crop_core.METHOD_SMARTCROP if self.above_threshold else crop_core.METHOD_CENTER,
		}


def focal_from_bytes(content: bytes, *, grid: int = FOCAL_GRID) -> FocalSuggestion:
	"""Kenar enerjisinin ağırlık merkezi → odak önerisi. **Saf fonksiyon.**

	Adımlar:
	  1. EXIF rotasyonu uygulanır (kullanıcı ne görüyorsa o ölçülür).
	  2. Gri tonlamaya çevrilip `grid × grid` kareye indirilir.
	  3. Her hücrede yatay+dikey komşu farkının mutlak değeri toplanır
	     (ayrık gradyan büyüklüğü).
	  4. Odak = bu enerjinin ağırlık merkezi.
	  5. Güven = enerjinin, odağın çevresindeki 1/3'lük kutuda kalan oranı.

	Düz renk görselde toplam enerji 0'dır; bu durumda merkez döner ve
	`reason=no_edge_energy` yazılır — "merkez seçtim" ile "ölçemedim" ayrımı
	yanıtta korunur.
	"""
	try:
		from PIL import Image, ImageOps
	except Exception:
		return FocalSuggestion(reason=REASON_PILLOW)

	if not content:
		return FocalSuggestion(reason=REASON_NO_SOURCE)

	n = max(4, int(grid))
	try:
		import io

		with Image.open(io.BytesIO(content)) as im:
			im = ImageOps.exif_transpose(im)
			gri = im.convert("L").resize((n, n), Image.LANCZOS)
			px = list(gri.getdata())
	except Exception:
		return FocalSuggestion(reason=REASON_NO_SOURCE)

	# Gradyan büyüklüğü — kenar yoğunluğunun ucuz vekili.
	enerji: List[float] = [0.0] * (n * n)
	for y in range(n):
		for x in range(n):
			i = y * n + x
			deger = px[i]
			dx = abs(deger - px[i + 1]) if x + 1 < n else 0
			dy = abs(deger - px[i + n]) if y + 1 < n else 0
			enerji[i] = float(dx + dy)

	toplam = sum(enerji)
	if toplam <= 0.0:
		return FocalSuggestion(reason=REASON_FLAT)

	# Ağırlık merkezi — hücre MERKEZİ kullanılır ((x+0.5)/n), köşesi değil.
	# Köşe kullanmak odağı yarım hücre sola-yukarı kaydırırdı; 32'lik ızgarada
	# bu %1,5'lik sistematik bir sapmadır.
	cx = sum(((x + 0.5) / n) * enerji[y * n + x] for y in range(n) for x in range(n)) / toplam
	cy = sum(((y + 0.5) / n) * enerji[y * n + x] for y in range(n) for x in range(n)) / toplam

	yari = FOCAL_CONCENTRATION_BOX / 2.0
	icerde = 0.0
	for y in range(n):
		for x in range(n):
			gx, gy = (x + 0.5) / n, (y + 0.5) / n
			if abs(gx - cx) <= yari and abs(gy - cy) <= yari:
				icerde += enerji[y * n + x]
	guven = icerde / toplam

	return FocalSuggestion(
		x=min(1.0, max(0.0, cx)),
		y=min(1.0, max(0.0, cy)),
		confidence=min(1.0, max(0.0, guven)),
		measured=True,
		reason=REASON_OK,
		grid=n,
	)


# ── Uç noktalar ─────────────────────────────────────────────────────────


@dataclass
class CropApi:
	"""Kırpma uçları. Saf Python — `@frappe.whitelist()` YOK."""

	#: Sözleşmedeki uç noktalar — bkz. `UploadApi.ENDPOINTS` notu.
	ENDPOINTS: ClassVar[Tuple[str, ...]] = (
		"get_intent",
		"save_intent",
		"suggest_focal",
		"preview",
	)

	assets: AssetReader
	intents: CropIntentRepository
	clock: Callable[[], float] = time.time
	on_denied: Optional[env.DenialHook] = None
	#: Önizleme üretmek için Pillow gerekir; kapatmak isteyen dağıtım
	#: `preview_enabled=False` verir ve uç `measured=False` ile döner.
	preview_enabled: bool = True

	# ── ortak ──────────────────────────────────────────────────────────

	def _asset(self, principal: env.Principal, asset: str) -> Mapping[str, Any]:
		env.require_auth(principal)
		ad = env.require_str(asset, "asset", max_len=140)
		kayit = self.assets.get(ad)
		if kayit is None:
			raise env.NotFound(
				"Medya varlığı bulunamadı.",
				kod=kod_uret(env.API_PREFIX, "not_found"),
				detay={"asset": ad},
			)
		if not env.same_store(principal, str(kayit.get("owner_store") or "")):
			# 403 değil 404: başka mağazanın varlığının VARLIĞI sızmamalı.
			raise env.NotFound(
				"Medya varlığı bulunamadı.",
				kod=kod_uret(env.API_PREFIX, "not_found"),
				detay={"asset": ad},
			)
		return kayit

	@staticmethod
	def _slot_of(kayit: Mapping[str, Any]) -> str:
		return str(kayit.get("slot_key") or "")

	def _profiles(self, slot_key: str) -> Tuple[render_mod.RenditionProfile, ...]:
		if not slot_key:
			return ()
		try:
			return render_mod.load_profiles(slot_key)
		except (KeyError, render_mod.RenderError):
			return ()

	@staticmethod
	def _normalize_intent(raw: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
		"""Kayıt → API biçimi. Yazılmamış alan `None` KALIR, 0.5 OLMAZ.

		`core/crop.py::focal_of` dokümanında yazılı ayrım burada korunur:
		"kullanıcı merkezi seçti" ile "hiç seçmedi" farklı seviyelerdir.
		"""
		d = dict(raw or {})
		return {
			"focal_x": d.get("focal_x"),
			"focal_y": d.get("focal_y"),
			"safe_x": d.get("safe_x"),
			"safe_y": d.get("safe_y"),
			"safe_w": d.get("safe_w"),
			"safe_h": d.get("safe_h"),
			"zoom": d.get("zoom"),
			"center_x": d.get("center_x"),
			"center_y": d.get("center_y"),
			"method": d.get("method") or "",
			"confidence": d.get("confidence"),
			"approved_by_user": bool(d.get("approved_by_user")),
			"overrides": [dict(o) for o in (d.get("overrides") or [])],
			# TUR-124: yanıtta ISO 8601 + kayma; iç kayıt epoch kalır.
			"updated_at": env.iso_time(d.get("updated_at")),
		}

	def _windows(
		self, kayit: Mapping[str, Any], intent: Mapping[str, Any]
	) -> List[Dict[str, Any]]:
		"""Slotun her profili için çözülmüş pencere. Editör önizlemesi budur."""
		cikti: List[Dict[str, Any]] = []
		for profil in self._profiles(self._slot_of(kayit)):
			win = crop_core.resolve_crop(kayit, profil, intent=intent)
			satir = win.as_dict()
			satir["profile"] = profil.profile_key
			satir["width"] = profil.width
			satir["fit"] = profil.fit
			w = int(kayit.get("width") or 0)
			h = int(kayit.get("height") or 0)
			if w > 0 and h > 0:
				left, top, cw, ch = win.to_pixels(w, h)
				satir["pixels"] = {"left": left, "top": top, "width": cw, "height": ch}
			else:
				# Ölçü bilinmiyorsa piksel kutusu ÜRETİLMEZ. Canlı ölçümde
				# `th_media_width` dolu olan kayıt sayısı 2853'te 0; bu alanın
				# boş gelmesi bugün İSTİSNA DEĞİL, kural.
				satir["pixels"] = None
			cikti.append(satir)
		return cikti

	# ── T-082.1 get_intent ─────────────────────────────────────────────

	def get_intent(
		self, principal: env.Principal, asset: str, *, if_none_match: str = ""
	) -> env.ApiResponse:
		"""Kırpma niyetini ve çözülmüş pencereleri döndür.

		Niyet henüz yazılmamışsa **404 değil**, `exists: false` ile 200 döner:
		her varlığın örtük bir niyeti vardır (merkez kırpım) ve editör onu
		göstermek zorundadır. 404 döndürmek istemciyi "yoksa merkez varsay"
		mantığını kendi yazmaya iterdi — aynı kural iki yerde (NFR-046).
		"""
		kayit = self._asset(principal, asset)
		ham = self.intents.get(str(asset))
		intent = self._normalize_intent(ham)
		govde = {
			"asset": str(asset),
			"slot_key": self._slot_of(kayit),
			"exists": ham is not None,
			"intent": intent,
			"source": {
				"width": int(kayit.get("width") or 0),
				"height": int(kayit.get("height") or 0),
				"source_ratio": crop_core.source_ratio_of(kayit),
			},
			"windows": self._windows(kayit, intent),
		}
		return env.conditional_get(govde, if_none_match)

	# ── T-082.2 save_intent ────────────────────────────────────────────

	def save_intent(
		self,
		principal: env.Principal,
		asset: str,
		*,
		focal_x: Any = None,
		focal_y: Any = None,
		safe_area: Optional[Mapping[str, Any]] = None,
		zoom: Any = None,
		center_x: Any = None,
		center_y: Any = None,
		overrides: Optional[Sequence[Mapping[str, Any]]] = None,
		approved_by_user: bool = False,
		confidence: Any = None,
		method: str = "",
		if_match: str = "",
	) -> env.ApiResponse:
		"""Niyeti yaz. Tüm koordinatlar 0-1 normalize olmak ZORUNDA (INV-10).

		Piksel koordinatı kabul edilseydi, aynı görselin master'ı ile arşiv
		kopyası farklı boyutta olduğunda kadraj kayardı — `core/crop.py` modül
		başlığındaki gerekçe. Bu yüzden 1'den büyük bir değer düzeltilmez,
		**reddedilir** (400).

		`zoom`/`center_x`/`center_y` stüdyonun taban bölgesini taşır
		(`crop_geometry.zoom_base` girdileri) ve ÜÇÜ BİRLİKTE verilir; zoom
		`[ZOOM_MIN, ZOOM_MAX]` dışıysa 400. Verilmezse kayıtlı üçlü KORUNUR —
		tek istisna: `safe_area` verilip zoom verilmemişse üçlü silinir,
		çünkü taban bölge yeniden tanımlanmıştır ve eski zoom yeni tabanı
		gölgelerdi (aşağıda, satır içi gerekçe).

		`If-Match` verilirse iyimser kilit uygulanır: araya başka bir yazma
		girdiyse 412 döner. Verilmezse son yazan kazanır — bugünkü editörde
		tek kullanıcı olduğu için varsayılan bu, ama kapı açık bırakıldı.
		"""
		kayit = self._asset(principal, asset)

		mevcut_ham = self.intents.get(str(asset))
		if if_match:
			mevcut_govde = {
				"asset": str(asset),
				"intent": self._normalize_intent(mevcut_ham),
			}
			if not env.etag_matches(env.etag_for(mevcut_govde), if_match):
				raise env.PreconditionFailed(
					"Kırpma niyeti bu arada değişti; sayfayı yenileyip tekrar deneyin.",
					kod=kod_uret(env.API_PREFIX, "precondition_failed"),
					detay={"asset": str(asset)},
				)

		yeni: Dict[str, Any] = dict(self._normalize_intent(mevcut_ham))

		if focal_x is not None or focal_y is not None:
			if focal_x is None or focal_y is None:
				raise env.BadRequest(
					"`focal_x` ve `focal_y` birlikte verilmeli.",
					kod=kod_uret(env.API_PREFIX, "bad_field"),
					detay={"field": "focal_x/focal_y"},
				)
			yeni["focal_x"] = env.require_unit(focal_x, "focal_x")
			yeni["focal_y"] = env.require_unit(focal_y, "focal_y")

		if safe_area is not None:
			yeni.update(self._parse_safe_area(safe_area))

		if zoom is not None or center_x is not None or center_y is not None:
			# Üçlü BİRLİKTE gelir: yarım yazılmış zoom (merkezi belirsiz bir
			# taban bölge) okurken sessizce bir alt seviyeye düşer ve
			# kullanıcı kadraj kaydettiğini sanırken sistem başka pencere
			# keser — odak çiftiyle aynı gerekçe.
			if zoom is None or center_x is None or center_y is None:
				raise env.BadRequest(
					"`zoom`, `center_x` ve `center_y` birlikte verilmeli.",
					kod=kod_uret(env.API_PREFIX, "bad_field"),
					detay={"field": "zoom/center_x/center_y"},
				)
			yeni["zoom"] = self._parse_zoom(zoom)
			yeni["center_x"] = env.require_unit(center_x, "center_x")
			yeni["center_y"] = env.require_unit(center_y, "center_y")
		elif safe_area is not None:
			# Çağıran taban bölgeyi zoom vermeden yeniden tanımladı (eski
			# istemci). Kayıtta duran zoom o eski tabanın niyetiydi; onu
			# bırakmak, çözücü zoom'u tercih ettiği için kullanıcının az önce
			# gönderdiği güvenli alanı sessizce gölgelerdi. Taban yeniden
			# tanımlanınca zoom üçlüsü SİLİNİR.
			yeni["zoom"] = None
			yeni["center_x"] = None
			yeni["center_y"] = None

		if overrides is not None:
			yeni["overrides"] = self._parse_overrides(overrides, self._slot_of(kayit))

		if confidence is not None:
			yeni["confidence"] = env.require_unit(confidence, "confidence")
		if method:
			m = env.require_str(method, "method", max_len=32)
			if m not in crop_core.METHODS:
				raise env.BadRequest(
					f"Bilinmeyen kırpma yöntemi: {m}",
					kod=kod_uret(env.API_PREFIX, "bad_field"),
					detay={"field": "method", "allowed": list(crop_core.METHODS)},
				)
			yeni["method"] = m

		yeni["approved_by_user"] = bool(approved_by_user)
		yeni["updated_at"] = float(self.clock())

		kaydedilen = self._normalize_intent(self.intents.save(str(asset), yeni) or yeni)

		govde = {
			"asset": str(asset),
			"slot_key": self._slot_of(kayit),
			"exists": True,
			"intent": kaydedilen,
			"source": {
				"width": int(kayit.get("width") or 0),
				"height": int(kayit.get("height") or 0),
				"source_ratio": crop_core.source_ratio_of(kayit),
			},
			"windows": self._windows(kayit, kaydedilen),
		}
		# ETag `get_intent` ile AYNI gövde şeklinden hesaplanır ki istemci
		# yazdıktan sonra aldığı ETag'i doğrudan `If-Match`'e koyabilsin.
		return env.ok(govde, etag=env.etag_for(govde))

	@staticmethod
	def _parse_zoom(raw: Any) -> float:
		"""Zoom çarpanı — `[ZOOM_MIN, ZOOM_MAX]` dışı REDDEDİLİR, kelepçelenmez.

		`crop_geometry.zoom_base` aralık dışını sessizce sıkıştırır; o davranış
		ETKİLEŞİM içindir (fare tekerleği dönerken hata basılmaz). YAZMA
		tarafında aynı hoşgörü, kullanıcının göndermediği bir kadrajı
		"kaydedildi" diye göstermek olurdu — 0-1 sözleşmesiyle aynı kural
		(`require_unit` ve modül başlığındaki gerekçe).
		"""
		try:
			sayi = float(raw)
		except (TypeError, ValueError):
			raise env.BadRequest(
				"`zoom` bir sayı olmalı.",
				kod=kod_uret(env.API_PREFIX, "bad_field"),
				detay={"field": "zoom", "observed": repr(raw)},
			)
		if not (crop_core.ZOOM_MIN <= sayi <= crop_core.ZOOM_MAX):
			raise env.BadRequest(
				f"`zoom` {crop_core.ZOOM_MIN} ile {crop_core.ZOOM_MAX} arasında olmalı: {sayi}.",
				kod=kod_uret(env.API_PREFIX, "bad_field"),
				detay={
					"field": "zoom",
					"min": crop_core.ZOOM_MIN,
					"max": crop_core.ZOOM_MAX,
					"observed": sayi,
				},
			)
		return sayi

	@staticmethod
	def _parse_safe_area(raw: Mapping[str, Any]) -> Dict[str, Any]:
		"""Güvenli alan → dört alan. Boş sözlük alanı SİLER (None yazar)."""
		if not raw:
			return {"safe_x": None, "safe_y": None, "safe_w": None, "safe_h": None}
		x = env.require_unit(raw.get("x"), "safe_area.x")
		y = env.require_unit(raw.get("y"), "safe_area.y")
		w = env.require_unit(raw.get("w"), "safe_area.w")
		h = env.require_unit(raw.get("h"), "safe_area.h")
		if w <= 0 or h <= 0:
			raise env.BadRequest(
				"Güvenli alanın genişliği ve yüksekliği sıfırdan büyük olmalı.",
				kod=kod_uret(env.API_PREFIX, "bad_field"),
				detay={"field": "safe_area"},
			)
		if x + w > 1.0 + 1e-6 or y + h > 1.0 + 1e-6:
			raise env.BadRequest(
				"Güvenli alan kaynağın dışına taşıyor.",
				kod=kod_uret(env.API_PREFIX, "bad_field"),
				detay={"field": "safe_area", "observed": {"x": x, "y": y, "w": w, "h": h}},
			)
		return {"safe_x": x, "safe_y": y, "safe_w": w, "safe_h": h}

	def _parse_overrides(
		self, rows: Sequence[Mapping[str, Any]], slot_key: str
	) -> List[Dict[str, Any]]:
		"""Profil bazlı elle kırpımlar. **Bilinmeyen profil reddedilir.**

		`core/crop.py::override_for` yarım yazılmış bir override'ı sessizce
		atlıyor ve zincirde bir alt seviyeye düşüyor — o davranış OKUMA
		tarafında doğru (yanlış kadraj, kadrajsızlıktan kötüdür). YAZMA
		tarafında sessizlik yanlış olur: kullanıcı çizdiğini kaydettiğini
		sanır, sistem onu atar.
		"""
		bilinen = {p.profile_key for p in self._profiles(slot_key)}
		cikti: List[Dict[str, Any]] = []
		gorulen: set = set()
		for row in rows:
			anahtar = env.require_str(
				row.get("profile") or row.get("profile_key"), "overrides[].profile", max_len=64
			)
			if bilinen and anahtar not in bilinen:
				raise env.BadRequest(
					f"`{anahtar}` bu slotta tanımlı bir profil değil.",
					kod=kod_uret(env.API_PREFIX, "bad_field"),
					detay={"field": "overrides[].profile", "allowed": sorted(bilinen)},
				)
			if anahtar in gorulen:
				raise env.BadRequest(
					f"Aynı profil için iki kırpım verildi: {anahtar}",
					kod=kod_uret(env.API_PREFIX, "bad_field"),
					detay={"field": "overrides[].profile", "profile": anahtar},
				)
			gorulen.add(anahtar)
			x = env.require_unit(row.get("x"), "overrides[].x")
			y = env.require_unit(row.get("y"), "overrides[].y")
			w = env.require_unit(row.get("w"), "overrides[].w")
			h = env.require_unit(row.get("h"), "overrides[].h")
			if w <= 0 or h <= 0 or x + w > 1.0 + 1e-6 or y + h > 1.0 + 1e-6:
				raise env.BadRequest(
					f"`{anahtar}` kırpımı kaynağın dışına taşıyor ya da sıfır alanlı.",
					kod=kod_uret(env.API_PREFIX, "bad_field"),
					detay={"field": "overrides[]", "profile": anahtar},
				)
			cikti.append(
				{
					"profile": anahtar,
					"x": x,
					"y": y,
					"w": w,
					"h": h,
					"method": crop_core.METHOD_OVERRIDE,
				}
			)
		return cikti

	# ── T-082.3 suggest_focal ──────────────────────────────────────────

	def suggest_focal(
		self, principal: env.Principal, asset: str, *, content: Optional[bytes] = None
	) -> env.ApiResponse:
		"""Odak noktası öner. **Yazmaz** — öneri kullanıcı onayına sunulur.

		Yazmamak bilinçli: `core/crop.py`'de smartcrop önerisi zincirin 4.
		seviyesidir ve `approved_by_user=0` iken bile KULLANILIR, ama arayüzde
		"öneri" rozetiyle gösterilir (`CropWindow.is_suggestion`). Öneriyi
		niyet kaydına yazmak o ayrımı yok ederdi.

		Kaynak baytları okunamazsa uç **hata vermez**: merkez + `measured=false`.
		"""
		kayit = self._asset(principal, asset)
		ham = content if content is not None else self.assets.read_source(str(asset))
		oneri = focal_from_bytes(ham or b"")

		intent = self._normalize_intent(self.intents.get(str(asset)))
		# Önerinin nasıl bir kadraj üreteceğini de gösteriyoruz: kullanıcı
		# sayıya değil, sonuca bakarak onaylar.
		onizleme_niyeti = dict(intent)
		if oneri.measured:
			onizleme_niyeti["focal_x"] = oneri.x
			onizleme_niyeti["focal_y"] = oneri.y

		govde = {
			"asset": str(asset),
			"slot_key": self._slot_of(kayit),
			"suggestion": oneri.to_dict(),
			"applied": False,
			"windows": self._windows(kayit, onizleme_niyeti),
		}
		return env.ok(govde)

	# ── T-082.4 preview ────────────────────────────────────────────────

	def preview(
		self,
		principal: env.Principal,
		asset: str,
		*,
		profile: str,
		intent: Optional[Mapping[str, Any]] = None,
		include_image: bool = False,
		content: Optional[bytes] = None,
	) -> env.ApiResponse:
		"""Tek profil için kadrajı çöz; istenirse görüntüsünü de üret.

		`intent` verilirse **kaydedilmemiş** niyet üzerinden hesaplanır —
		editörün kaydetmeden önizleme yapabilmesi için. Verilmezse kayıtlı
		niyet kullanılır.

		`include_image=True` görüntüyü `data:` URI olarak döndürür. Görüntü
		üretimi `image/render.py::render_rendition`'a delege edilir; ikinci bir
		yeniden ölçekleme yolu yazmak, önizlemenin türevden farklı görünmesi
		demek olurdu — kullanıcı gördüğünden başkasını alırdı.
		"""
		kayit = self._asset(principal, asset)
		slot = self._slot_of(kayit)
		anahtar = env.require_str(profile, "profile", max_len=64)

		profiller = {p.profile_key: p for p in self._profiles(slot)}
		if anahtar not in profiller:
			raise env.NotFound(
				f"`{anahtar}` bu slotta tanımlı bir profil değil.",
				kod=kod_uret(env.API_PREFIX, "not_found"),
				detay={"profile": anahtar, "slot_key": slot, "allowed": sorted(profiller)},
			)
		profil = profiller[anahtar]

		kullanilan = (
			self._normalize_intent(intent) if intent is not None
			else self._normalize_intent(self.intents.get(str(asset)))
		)
		win = crop_core.resolve_crop(kayit, profil, intent=kullanilan)
		crop_core.verify_window(win)

		satir = win.as_dict()
		satir["profile"] = profil.profile_key
		satir["width"] = profil.width
		satir["fit"] = profil.fit
		w = int(kayit.get("width") or 0)
		h = int(kayit.get("height") or 0)
		if w > 0 and h > 0:
			left, top, cw, ch = win.to_pixels(w, h)
			satir["pixels"] = {"left": left, "top": top, "width": cw, "height": ch}
		else:
			satir["pixels"] = None

		govde: Dict[str, Any] = {
			"asset": str(asset),
			"slot_key": slot,
			"window": satir,
			"image": None,
			"image_reason": "",
		}

		if include_image:
			ham = content if content is not None else self.assets.read_source(str(asset))
			govde["image"], govde["image_reason"] = self._render_preview(
				ham, profil, kullanilan
			)

		return env.ok(govde)

	def _render_preview(
		self, content: Optional[bytes], profile: render_mod.RenditionProfile, intent: Mapping[str, Any]
	) -> Tuple[Optional[str], str]:
		"""`(data_uri, reason)`. Üretilemezse `(None, sebep)` — istisna ATMAZ."""
		if not self.preview_enabled:
			return (None, "preview_disabled")
		if not content:
			return (None, REASON_NO_SOURCE)
		try:
			sonuc = render_mod.render_rendition(content, profile, intent)
		except Exception as exc:
			# Önizleme üretilememesi kadraj cevabını geçersiz kılmaz; kadraj
			# saf aritmetiktir, görüntü ise kodlayıcıya bağlıdır.
			return (None, f"render_failed:{type(exc).__name__}")
		mime = {"webp": "image/webp", "avif": "image/avif", "jpeg": "image/jpeg", "png": "image/png"}
		tur = mime.get(sonuc.format, "application/octet-stream")
		veri = base64.b64encode(sonuc.content).decode("ascii")
		return (f"data:{tur};base64,{veri}", REASON_OK)


# ── Test/geliştirme için bellek-içi depolar ─────────────────────────────


class InMemoryCropIntents:
	"""Bellek-içi `Media Crop Intent` deposu."""

	def __init__(self) -> None:
		self.rows: Dict[str, Dict[str, Any]] = {}

	def get(self, asset: str) -> Optional[Mapping[str, Any]]:
		row = self.rows.get(asset)
		return dict(row) if row is not None else None

	def save(self, asset: str, intent: Mapping[str, Any]) -> Mapping[str, Any]:
		self.rows[asset] = dict(intent)
		return dict(self.rows[asset])


@dataclass
class InMemoryAssetReader:
	"""`AssetReader` portunun bellek-içi eşi."""

	rows: Dict[str, Dict[str, Any]] = field(default_factory=dict)
	blobs: Dict[str, bytes] = field(default_factory=dict)

	def get(self, asset: str) -> Optional[Mapping[str, Any]]:
		row = self.rows.get(asset)
		return dict(row) if row is not None else None

	def read_source(self, asset: str) -> Optional[bytes]:
		return self.blobs.get(asset)


__all__ = [
	"FOCAL_GRID",
	"FOCAL_CONCENTRATION_BOX",
	"PREVIEW_USES_PROFILE",
	"REASON_PILLOW",
	"REASON_NO_SOURCE",
	"REASON_FLAT",
	"REASON_OK",
	"AssetReader",
	"CropIntentRepository",
	"FocalSuggestion",
	"focal_from_bytes",
	"CropApi",
	"InMemoryCropIntents",
	"InMemoryAssetReader",
]

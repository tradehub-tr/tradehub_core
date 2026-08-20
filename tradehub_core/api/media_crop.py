# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""Kırpma niyeti uçları — T-082. `media/pipeline/api/crop.py` ile Frappe arasındaki ince katman.

NEDEN AYRI BİR MODÜL
--------------------
`media/pipeline/api/crop.py` **saf Python**tur ve modül başlığında açıkça
"Saf Python — `@frappe.whitelist()` YOK" yazar. O dosya bu görevde tek satır
değiştirilmedi. Dışarıya uç açmak için gereken her şey — whitelist, oturum,
kiracı sınırı, DocType okuma/yazma — burada durur. `api/media_manifest.py` ile
aynı desen; ikinci bir mimari icat edilmedi.

KADRAJ MATEMATİĞİ BURADA DA YOK
-------------------------------
Öncelik zinciri, 0-1 sözleşmesi ve pencere matematiği `pipeline/core/crop.py`de;
odak önerisi `pipeline/api/crop.py:focal_from_bytes`ta. Bu modül ikisini de
ÇAĞIRIR, hiçbirini yeniden yazmaz. `CropApi` üç porta ihtiyaç duyar
(`AssetReader`, `CropIntentRepository`); bu modülün asıl işi o portların Frappe
karşılığını vermektir.

ARALIK DIŞI GİRDİ: KELEPÇELENMEZ, **REDDEDİLİR**
------------------------------------------------
`envelope.require_unit` 0-1 dışını 400 ile geri çevirir ve bu modül o kararı
DEĞİŞTİRMEZ. Gerekçe `core/crop.py` modül başlığında yazılı: koordinat piksel
değil normalize olduğu için, 1.4 gibi bir değer "biraz taşmış bir kadraj"
değildir — çağıranın piksel gönderdiğinin kanıtıdır. Sessizce 1.0'a çekmek,
kullanıcının çizmediği bir kadrajı "kaydedildi" diye göstermek olurdu.
Kelepçeleme bu kod tabanında yalnız TERCİH alanlarında kullanılıyor
(`envelope.page_params`: `page_size` tavanı), koordinatlarda değil.

`method` VOKABÜLERİ — İKİ EKSEN, İKİ SÖZLÜK
-------------------------------------------
`Media Crop Intent.method` niyetin KAYNAĞINI söyler; spec'in Select'i
`manual/smartcrop/center`. `core/crop.py:METHODS` ise çözülen PENCERENİN
yöntemidir (`override/safe_focal/focal/smartcrop/center`) — spec'in kendi alan
açıklaması bu iki ekseni ayırıyor. `CropApi.save_intent` gelen `method`i pencere
vokabülerine göre doğruladığı için "manual" oradan geçemez. Bu yüzden `method`
kütüphaneye HİÇ verilmez: şema (spec) yetkili olduğundan doğrulama burada
Select seçeneklerine göre yapılır ve değer depo katmanına (`_FrappeCropIntents`)
doğrudan taşınır. Kütüphanenin pencere doğrulayıcısına yanlış eksenden bir
değer sokuşturmak, iki sözlüğü birbirine karıştırmak olurdu.

KİRACI SINIRI — ÜÇ KAT
----------------------
1. `_principal()` oturumun satıcı kapsamını (`Admin Seller Profile`) taşır;
   `CropApi._asset` başka mağazanın varlığını **404** ile geri çevirir (403
   değil: varlığın VARLIĞI sızmamalı).
2. `doc.check_permission()` → `permissions.media_crop_intent_has_permission`
   kancası, niyeti `asset.owner_seller`a zincirler.
3. Liste yüzeyi `permission_query_conditions` ile aynı zincirden süzülür.
Üçü de aynı yöne çalışır; biri kaldırılırsa test kırmızıya döner.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import frappe
from frappe import _

from tradehub_core.api.rate_limit import rate_limit
from tradehub_core.media.pipeline.api import crop as crop_lib
from tradehub_core.media.pipeline.api import envelope as env
from tradehub_core.media.pipeline.contracts.errors import MediaEngineError
from tradehub_core.media.pipeline.core.crop import CropError

#: Niyet DocType'ı — tek yerde yazılı, üç uç da buradan okur.
INTENT_DOCTYPE: str = "Media Crop Intent"
ASSET_DOCTYPE: str = "Media Asset"

#: `Media Crop Intent.method` Select seçenekleri (spec). Şema yetkilidir —
#: `core/crop.py:METHODS` BAŞKA bir eksendir, bkz. modül başlığı.
INTENT_METHODS: frozenset[str] = frozenset({"manual", "smartcrop", "center"})

#: Kaynak ölçüleri `File` üstündeki custom field'larda durur (v15_9_15).
#: `Media Asset` kendi width/height kolonu TAŞIMAZ; ölçüyü oradan okumak
#: uydurma bir alan icat etmek olurdu.
FILE_WIDTH_FIELD: str = "th_media_width"
FILE_HEIGHT_FIELD: str = "th_media_height"

#: `suggest_focal` her çağrıda master baytları okur ve 32×32 ızgara üzerinde
#: gradyan hesaplar — ucuz ama bedava değil. Satıcı başına dakikada 30 öneri,
#: stüdyoda insan hızının çok üstünde; kötüye kullanımı keser, kullanımı kesmez.
SUGGEST_RATE_LIMIT_CALLS: int = 30
SUGGEST_RATE_LIMIT_WINDOW: int = 60

#: Uçların çevirdiği kütüphane hataları. `CropError` bir `ValueError`dır ve
#: `MediaEngineError` ağacında DEĞİLDİR — ayrıca yakalanmazsa kadrajı çözülemeyen
#: tek bir varlık ucu HTTP 500'e düşürür (ölçüldü: ölçüsüz varlıkta
#: `source_ratio_of` fırlatıyor).
_KUTUPHANE_HATALARI: tuple[type[Exception], ...] = (MediaEngineError, CropError)


# ── Frappe portları ─────────────────────────────────────────────────────


class _FrappeAssetReader:
	"""`crop_lib.AssetReader` portunun Frappe karşılığı.

	Master baytlar istek kapsamında bir kez okunur (`_bayt_onbellek`): ölçü
	tespiti ve odak önerisi aynı dosyayı istiyor, iki kez okumak aynı diski
	iki kez dolaşmak olurdu.
	"""

	def __init__(self) -> None:
		self._bayt_onbellek: dict[str, bytes | None] = {}

	def get(self, asset: str) -> dict | None:
		"""Varlık künyesi: ölçü + slot + sahip mağaza.

		`get_value` (get_doc değil): birkaç kolon için tam doküman yüklemek
		gereksiz. İzin kapısı çağıranda (`_principal` + `same_store`) ve
		Frappe kancasında; bu okuma onların GİRDİSİ olduğu için izin
		kontrolünden önce gelir.
		"""
		kayit = frappe.db.get_value(
			ASSET_DOCTYPE,
			asset,
			["name", "slot_key", "owner_seller", "source_file", "state"],
			as_dict=True,
		)
		if not kayit:
			return None

		kunye = {
			"name": kayit["name"],
			"slot_key": kayit.get("slot_key") or "",
			# `CropApi._asset` mağaza karşılaştırmasını `owner_store` adıyla
			# yapıyor; kütüphane Frappe alan adlarını bilmez, çeviri burada.
			"owner_store": kayit.get("owner_seller") or "",
			"state": kayit.get("state") or "",
		}

		genislik, yukseklik = self._olculer(asset, kayit.get("source_file"))
		if genislik > 0 and yukseklik > 0:
			kunye["width"] = genislik
			kunye["height"] = yukseklik
		# ÖLÇÜ BİLİNMİYORSA ALANLAR HİÇ KONMAZ — 0 YAZILMAZ.
		# `core/crop.py:source_ratio_of` iki durumu AYIRIYOR: alan yoksa 1.0
		# (kare) varsayar ve bunu "varsayım" diye işaretler; alan VAR ama 0 ise
		# `CropError` fırlatır. 0 yazmak "bu görsel sıfır piksel geniş" demektir
		# ve ucu 500'e düşürür (ölçüldü). Bilinmeyeni bilinmeyen olarak
		# bırakmak, sıfır diye bildirmekten farklıdır.
		return kunye

	def _olculer(self, asset: str, source_file: str | None) -> tuple[int, int]:
		"""Kaynağın piksel ölçüsü. Bilinmiyorsa (0, 0).

		İki kaynak, bu sırayla:
		  1. `File.th_media_width/height` — hat yüklemede ölçtüyse bedava.
		  2. Görselin kendi başlığı — Pillow `Image.open` tembeldir, `.size`
		     için tüm kareyi çözmez.

		2. adım NEDEN VAR: canlı ölçümde `th_media_width` dolu olan kayıt
		sayısı 2853'te 0 (bkz. `api/media_manifest.py` notu). Yalnız 1. adıma
		güvenmek, bugünkü varlıkların TAMAMINDA kare varsayımına düşmek
		demekti — kare olmayan bir görselde bu, kullanıcıya yanlış kadraj
		göstermek olurdu. Ölçüm KALICILAŞTIRILMAZ: okuma yolunda yazmak
		(salt-okunur oturum, eşzamanlı istek) ayrı bir sorun sınıfı açar;
		alanı doldurmak yükleme hattının işi.
		"""
		if not source_file:
			return (0, 0)

		olcu = frappe.db.get_value(
			"File", source_file, [FILE_WIDTH_FIELD, FILE_HEIGHT_FIELD], as_dict=True
		)
		if olcu:
			w = int(olcu.get(FILE_WIDTH_FIELD) or 0)
			h = int(olcu.get(FILE_HEIGHT_FIELD) or 0)
			if w > 0 and h > 0:
				return (w, h)

		return self._baytlardan_olc(self.read_source(asset))

	@staticmethod
	def _baytlardan_olc(icerik: bytes | None) -> tuple[int, int]:
		"""Görsel başlığından ölçü. Pillow yoksa/çözülemezse (0, 0)."""
		if not icerik:
			return (0, 0)
		try:
			import io

			from PIL import Image

			with Image.open(io.BytesIO(icerik)) as im:
				w, h = im.size
			return (int(w), int(h))
		except Exception:
			# Pillow yok, biçim tanınmıyor ya da dosya bozuk. Ölçüsüzlük bu
			# uçta ölümcül değil: kare varsayımına düşülür ve piksel kutusu
			# üretilmez. `focal_from_bytes` de aynı savunmacı üslupla yazılmış.
			return (0, 0)

	def read_source(self, asset: str) -> bytes | None:
		"""Master baytları. Okunamazsa `None` — çağıran ölçülmemiş sonuç alır.

		`focal_from_bytes` boş girdide merkez + `measured=false` döndürüyor;
		yani burada istisna fırlatmak, ölçülemeyen bir görselin tüm ucu
		500'e düşürmesi demek olurdu.
		"""
		if asset in self._bayt_onbellek:
			return self._bayt_onbellek[asset]

		self._bayt_onbellek[asset] = None
		kaynak = frappe.db.get_value(ASSET_DOCTYPE, asset, "source_file")
		if not kaynak:
			return None
		try:
			self._bayt_onbellek[asset] = frappe.get_doc("File", kaynak).get_content()
		except (OSError, frappe.DoesNotExistError) as exc:
			# Dosya diskte yok ya da okunamıyor. Öneri üretilemez ama kadraj
			# çözümü (öncelik zinciri) baytsız da çalışır.
			frappe.log_error(
				title="media_crop kaynak okunamadı",
				message=f"asset={asset!r} file={kaynak!r}: {exc}",
			)
		return self._bayt_onbellek[asset]


class _FrappeCropIntents:
	"""`crop_lib.CropIntentRepository` portunun Frappe karşılığı.

	`intent_method` niyetin ŞEMA vokabülerindeki yöntemidir ve kütüphaneden
	DEĞİL, bu modülün doğrulayıcısından gelir (bkz. modül başlığı). İstek
	başına bir örnek kurulur; alan paylaşımlı durum değildir.
	"""

	def __init__(self, *, intent_method: str = "", algorithm: str = "", algorithm_version: str = "",
			previewed_placements: Any = None) -> None:
		self.intent_method = intent_method
		self.algorithm = algorithm
		self.algorithm_version = algorithm_version
		self.previewed_placements = previewed_placements

	def get(self, asset: str) -> Mapping[str, Any] | None:
		"""Kayıtlı niyet ya da `None`. `None` "niyet yazılmamış" demektir.

		`exists=False` ile 200 dönmenin gerekçesi `CropApi.get_intent`
		dokümanında: her varlığın örtük bir niyeti (merkez kırpım) vardır.
		"""
		if not frappe.db.exists(INTENT_DOCTYPE, asset):
			return None
		doc = frappe.get_doc(INTENT_DOCTYPE, asset)
		doc.check_permission("read")
		return doc.as_intent_mapping()

	def save(self, asset: str, intent: Mapping[str, Any]) -> Mapping[str, Any]:
		"""Niyeti yaz. **İdempotent**: ikinci çağrı yeni satır AÇMAZ.

		`autoname: field:asset` docname'i varlık adına eşitlediği için mevcut
		kaydın adı zaten biliniyor; "varsa güncelle, yoksa oluştur" tek
		`exists` sorgusuyla çözülür. Aynı varlık için ikinci bir kayıt
		açılamaz — `asset` alanı ayrıca `unique: 1`.
		"""
		var_mi = frappe.db.exists(INTENT_DOCTYPE, asset)
		doc = (
			frappe.get_doc(INTENT_DOCTYPE, asset)
			if var_mi
			else frappe.new_doc(INTENT_DOCTYPE)
		)
		if not var_mi:
			doc.asset = asset

		# Yazma izni: yeni kayıtta "create", mevcut kayıtta "write".
		# `media_crop_intent_has_permission` her ikisinde de `asset.owner_seller`
		# zincirini uygular.
		doc.check_permission("create" if not var_mi else "write")

		for alan in (
			"focal_x", "focal_y", "safe_x", "safe_y", "safe_w", "safe_h",
			"zoom", "center_x", "center_y", "confidence",
		):
			doc.set(alan, intent.get(alan))
		doc.approved_by_user = 1 if intent.get("approved_by_user") else 0

		if self.intent_method:
			doc.method = self.intent_method
		if self.algorithm:
			doc.algorithm = self.algorithm
		if self.algorithm_version:
			doc.algorithm_version = self.algorithm_version
		if self.previewed_placements is not None:
			doc.previewed_placements = json.dumps(self.previewed_placements, ensure_ascii=False)

		# T-114 — sunucu kapısı: onay, önizleme kanıtı olmadan geçemez.
		# Şartname (62-faz11-simulator.html → T-114): "Kayıt sunucu tarafında
		# da doğrulanıyor: eksik previewed_placements ile publish reddediliyor.
		# Frontend atlatılamaz." Kural bir ayara BAĞLI DEĞİLDİR.
		# Kanıt, bu istekte gönderilen ya da kayıtta zaten duran gövdedir:
		# daha önce kapıdan geçmiş bir kayıt, sonraki yazımlarda kanıtı
		# yeniden göndermek zorunda bırakılmaz. Aynı kural DocType
		# doğrulamasında da durur (`media_crop_intent._validate_approval_evidence`)
		# — burası 400 + MEDIA_PREVIEW_REQUIRED ile okunur olanı, orası ORM
		# yüzeyini kapatır.
		if doc.approved_by_user and not _onizleme_kaniti_var(doc.previewed_placements):
			frappe.local.response["http_status_code"] = env.HTTP_BAD_REQUEST
			frappe.throw(
				_(
					"Onay için önizleme kanıtı zorunlu: `previewed_placements` boş. "
					"Yerleşimleri simülatörde görüp onaylayın. (MEDIA_PREVIEW_REQUIRED)"
				),
				title=_("Kırpma"),
			)

		doc.set("overrides", [])
		for satir in intent.get("overrides") or []:
			doc.append(
				"overrides",
				{
					"profile": satir.get("profile"),
					"x": satir.get("x"),
					"y": satir.get("y"),
					"w": satir.get("w"),
					"h": satir.get("h"),
					# Child Select'i yalnız manual/smartcrop tanır; kütüphane
					# override satırlarını "override" pencere yöntemiyle
					# damgalıyor (o BAŞKA eksen) — şemanın sözlüğüne çevriliyor.
					"method": "manual",
				},
			)

		doc.save()
		return doc.as_intent_mapping()


# ── Ortak yardımcılar ───────────────────────────────────────────────────


def _principal() -> env.Principal:
	"""Oturum → `env.Principal`. Satıcı kapsamı `Admin Seller Profile` adıdır."""
	from tradehub_core.permissions import _get_seller_profile_name

	user = frappe.session.user
	roller = tuple(frappe.get_roles(user))
	# Guest'in satıcı profili aranmaz: `_get_seller_profile_name` boş döner ama
	# gereksiz üç sorgu atardı ve `require_auth` zaten 401 verecek.
	magaza = "" if user == env.GUEST_USER else (_get_seller_profile_name(user) or "")
	return env.Principal(user=user, roles=roller, store=magaza)


def _api(intents: _FrappeCropIntents) -> crop_lib.CropApi:
	"""Portları bağlanmış `CropApi`. Önizleme görüntüsü bu uçlarda üretilmez."""
	return crop_lib.CropApi(assets=_FrappeAssetReader(), intents=intents)


def _yanit(cevap: env.ApiResponse) -> dict:
	"""`ApiResponse` → whitelist dönüşü.

	ETag GÖVDEDE taşınır, başlıkta değil: bu kurulumdaki Frappe v15.116.1'de
	`dict` döndüren bir whitelist metodunun HTTP başlığı eklemesi için kanca
	yok (`frappe/utils/response.py:as_json()` yalnız `http_status_code` okur).
	Aynı gerekçe `api/media_manifest.py` başlığında da yazılı.
	"""
	govde = dict(cevap.body or {})
	for ad, deger in (cevap.headers or {}).items():
		govde[ad.lower().replace("-", "_")] = deger
	govde["status"] = cevap.status
	return govde


def _throw(exc: MediaEngineError) -> None:
	"""Kütüphane hatasını Frappe hatasına çevirir ve HTTP durumunu korur.

	Durum kodu düşürülürse istemci 404 ile 400'ü ayırt edemez; kırpma
	stüdyosu "varlık yok" ile "koordinat geçersiz" arasındaki farkı
	kullanıcıya göstermek zorunda.
	"""
	frappe.local.response["http_status_code"] = env.http_status_for(exc)
	frappe.throw(str(exc), title=_("Kırpma"), exc=frappe.ValidationError)


def _cozumle(ham: Any, alan: str) -> Any:
	"""HTTP üzerinden dizge olarak gelen JSON gövdeyi çözer.

	Frappe form-encoded istekte iç içe yapıları dizge yapar; `None` ile "boş
	sözlük" arasındaki farkı korumak zorundayız çünkü `save_intent` boş
	sözlüğü "güvenli alanı SİL" diye okuyor.
	"""
	if ham is None or isinstance(ham, (dict, list)):
		return ham
	metin = str(ham).strip()
	if not metin:
		return None
	try:
		return json.loads(metin)
	except (TypeError, ValueError):
		frappe.local.response["http_status_code"] = env.HTTP_BAD_REQUEST
		frappe.throw(_("`{0}` geçerli bir JSON değil.").format(alan))


def _onizleme_kaniti_var(ham: Any) -> bool:
	"""`previewed_placements` gerçekten kanıt taşıyor mu (boş değil mi).

	Alan JSON dizgesi (DB'den), liste/sözlük (istek gövdesi) ya da boş
	gelebilir. Ayrıştırılamayan gövde kanıt SAYILMAZ — "gördü ve onayladı"
	iddiasının kanıtı okunabilir olmak zorunda (DocType doğrulaması onu
	zaten reddediyor; burada da kanıt sayılmaması vacuity'ye karşı çift kilit).
	"""
	if ham is None or ham == "":
		return False
	if isinstance(ham, (list, dict)):
		return bool(ham)
	try:
		return bool(json.loads(ham))
	except (TypeError, ValueError):
		return False


def _method_dogrula(method: str) -> str:
	"""`method`i ŞEMA vokabülerine göre doğrular (bkz. modül başlığı)."""
	if not method:
		return ""
	temiz = str(method).strip()
	if temiz not in INTENT_METHODS:
		frappe.local.response["http_status_code"] = env.HTTP_BAD_REQUEST
		frappe.throw(
			_("Bilinmeyen kırpma yöntemi: {0}. İzin verilenler: {1}").format(
				temiz, ", ".join(sorted(INTENT_METHODS))
			)
		)
	return temiz


# ── Uç noktalar ─────────────────────────────────────────────────────────


@frappe.whitelist()
def get_intent(asset: str, if_none_match: str = "") -> dict:
	"""Kırpma niyetini ve her profil için çözülmüş pencereleri döndür.

	Args:
	    asset: `Media Asset` adı.
	    if_none_match: Önceki yanıtın `etag`i; eşleşirse gövdesiz yanıt döner.

	Returns:
	    `{"asset", "slot_key", "exists", "intent", "source", "windows", ...}`.
	    Niyet hiç yazılmamışsa **404 değil**, `exists: false` ile 200 döner —
	    her varlığın örtük bir niyeti (merkez kırpım) vardır.
	"""
	depo = _FrappeCropIntents()
	try:
		return _yanit(_api(depo).get_intent(_principal(), asset, if_none_match=if_none_match))
	except _KUTUPHANE_HATALARI as exc:
		_throw(exc)


@frappe.whitelist()
def save_intent(
	asset: str,
	focal_x: Any = None,
	focal_y: Any = None,
	safe_area: Any = None,
	zoom: Any = None,
	center_x: Any = None,
	center_y: Any = None,
	overrides: Any = None,
	approved_by_user: Any = 0,
	confidence: Any = None,
	method: str = "",
	algorithm: str = "",
	algorithm_version: str = "",
	previewed_placements: Any = None,
	if_match: str = "",
) -> dict:
	"""Kırpma niyetini kaydet. **İdempotent** — ikinci çağrı yeni satır açmaz.

	Args:
	    asset: `Media Asset` adı. Niyet kaydının adı da budur (`field:asset`).
	    focal_x, focal_y: Odak noktası, 0-1 normalize. İkisi BİRLİKTE verilir.
	    safe_area: `{"x","y","w","h"}` — 0-1 normalize. Boş sözlük alanı SİLER.
	    zoom: Stüdyonun zoom çarpanı, 1-16. `center_x`/`center_y` ile BİRLİKTE
	        verilir; verilmezse kayıtlı üçlü korunur (safe_area verilirse
	        silinir — gerekçe `pipeline/api/crop.py::save_intent`).
	    center_x, center_y: Pan merkezi, 0-1 normalize.
	    overrides: `[{"profile","x","y","w","h"}]` — profil bazlı istisnalar.
	    approved_by_user: Kullanıcı öneriyi onayladı mı.
	    confidence: Öneri güveni, 0-1.
	    method: Niyetin kaynağı — `manual` / `smartcrop` / `center`.
	    algorithm, algorithm_version: Öneriyi üreten kodun künyesi.
	    previewed_placements: Kullanıcının simülatörde gördüğü yerleşimler.
	    if_match: İyimser kilit; araya başka yazma girdiyse 412.

	Returns:
	    `get_intent` ile AYNI gövde şekli + `etag` (yazdıktan sonra doğrudan
	    `if_match`e konabilsin diye).

	Aralık dışı koordinat **reddedilir** (400), kelepçelenmez — gerekçe modül
	başlığında.
	"""
	depo = _FrappeCropIntents(
		intent_method=_method_dogrula(method),
		algorithm=str(algorithm or "").strip(),
		algorithm_version=str(algorithm_version or "").strip(),
		previewed_placements=_cozumle(previewed_placements, "previewed_placements"),
	)
	guvenli = _cozumle(safe_area, "safe_area")
	istisnalar = _cozumle(overrides, "overrides")

	try:
		yanit = _yanit(
			_api(depo).save_intent(
				_principal(),
				asset,
				focal_x=focal_x,
				focal_y=focal_y,
				safe_area=guvenli if isinstance(guvenli, Mapping) or guvenli == {} else None,
				zoom=zoom,
				center_x=center_x,
				center_y=center_y,
				overrides=istisnalar if isinstance(istisnalar, Sequence) and not isinstance(istisnalar, str) else None,
				approved_by_user=bool(int(approved_by_user or 0)),
				confidence=confidence,
				# `method` BİLEREK geçilmiyor — iki eksen, iki sözlük (modül başlığı).
				if_match=if_match,
			)
		)
	except _KUTUPHANE_HATALARI as exc:
		_throw(exc)

	# W9+ — kadraj değişti: türevler yeni pencereyle yeniden üretilsin.
	# Best-effort: kuyruk hatası kaydı geri almaz — niyet yazıldı, ekran
	# yanıtını alır; işin kendisi bayrak/slot kapılarını worker'da yine sorar.
	try:
		from tradehub_core.media import pipeline_bridge

		pipeline_bridge.maybe_reprocess_after_crop(asset)
	except Exception:
		frappe.log_error(
			title="media_crop reprocess enqueue failed",
			message=frappe.get_traceback(),
		)
	return yanit


@frappe.whitelist()
@rate_limit(
	max_calls=SUGGEST_RATE_LIMIT_CALLS,
	window_seconds=SUGGEST_RATE_LIMIT_WINDOW,
	scope="media_crop_suggest",
)
def suggest_focal(asset: str) -> dict:
	"""Odak noktası öner. **Yazmaz** — öneri kullanıcı onayına sunulur.

	Args:
	    asset: `Media Asset` adı.

	Returns:
	    `{"asset", "slot_key", "suggestion": {...}, "applied": false, "windows": [...]}`.
	    `suggestion.focal_x` / `focal_y` DAİMA 0-1 aralığındadır: ölçüm
	    yapılamazsa (Pillow yok, kaynak okunamıyor, düz renk görsel) merkez
	    (0.5, 0.5) + `measured: false` + `reason` döner, hata DEĞİL.

	Algoritma `pipeline/api/crop.py:focal_from_bytes` — kenar enerjisinin
	ağırlık merkezi. Burada yeniden yazılmadı; nesne tanıma değildir ve
	`threshold_calibrated: false` alanı bunu yanıtta açıkça taşır.
	"""
	depo = _FrappeCropIntents()
	try:
		return _yanit(_api(depo).suggest_focal(_principal(), asset))
	except _KUTUPHANE_HATALARI as exc:
		_throw(exc)

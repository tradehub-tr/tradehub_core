"""Görsel önizleme penceresi uçları — `ImagePlacementModal` (2026-10-01).

Pencere bir DOSYA adresiyle açılır; odak ise `Media Crop Intent`te VARLIK
başına durur. `get_preview_target` köprüdür: oturumdaki satıcının bu dosya
için en uygun varlığını seçer (önce odağın durduğu canlı varlık, sonra aynı
slotun `ready` varlığı, sonra arşivlenmemiş herhangi biri). Başka satıcının
varlığı ASLA seçilmez; seçilemezse `asset: ""` döner ve pencere Kaydet'i kapatır.

Kaynak künyesi (`source`, `square`) da aynı sınırdadır: yalnız seçilen varlığın
`source_file`ından ya da çağıranın KENDİ yüklediği `File` satırından okunur.
Aksi halde "varlık yok" ile birebir aynı boş şekil döner — başka satıcının
(özel ya da açık) dosyasının varlığı, boyutu, ölçüsü veya kare öncesi ilk
ölçüsü sızmaz (bulunurluk kâhini olmasın diye biçim de boş).
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.query_builder import DocType

from tradehub_core.api.media_crop import FILE_HEIGHT_FIELD, FILE_WIDTH_FIELD, _FrappeAssetReader, _principal
from tradehub_core.media import odak

PREF_KEY = "th_media_preview_autoopen"
SLOT_KEYS = frozenset({"company.cover_image", "seller.logo", "product.image"})
ADMIN_ROLES = frozenset({"System Manager", "Marketplace Admin"})
_HAZIR = "ready"
_EMEKLI = "archived"
# Ölçü için okunacak başlık üst sınırı: PNG/WebP/GIF ilk birkaç yüz baytta,
# JPEG SOF çoğunlukla ilk 64 KB'ta; 256 KB büyük EXIF/ICC bloklarına pay bırakır.
_BASLIK_BAYT = 256 * 1024
_BOS_KAYNAK: dict[str, Any] = {"width": 0, "height": 0, "bytes": 0, "format": ""}
# Ardışık dönüşümler (ör. PNG → WebP → kare) için yönlendirme zinciri üst sınırı.
_YONLENDIRME_ADIMI = 4


def _giris_zorunlu() -> None:
	if frappe.session.user in ("Guest", "", None):
		frappe.throw(_("Bu işlem için giriş yapmalısınız."), frappe.PermissionError)


def _adaylar(url: str, magaza: str, yonetici: bool) -> list[dict[str, Any]]:
	varlik, dosya = DocType("Media Asset"), DocType("File")
	sorgu = (
		frappe.qb.from_(varlik)
		.join(dosya)
		.on(dosya.name == varlik.source_file)
		.select(
			varlik.name,
			varlik.slot_key,
			varlik.state,
			varlik.owner_seller,
			varlik.source_file,
			varlik.modified,
		)
		.where(dosya.file_url == url)
	)
	if not yonetici:
		if not magaza:
			return []
		sorgu = sorgu.where(varlik.owner_seller == magaza)
	return sorgu.run(as_dict=True)


def _odak_varligi(adlar: list[str]) -> str:
	if not adlar:
		return ""
	niyet = DocType("Media Crop Intent")
	satir = (
		frappe.qb.from_(niyet)
		.select(niyet.asset)
		.where(niyet.asset.isin(adlar))
		.where(niyet.focal_x.isnotnull())
		.orderby(niyet.modified, order=frappe.qb.desc)
		.limit(1)
	).run(as_dict=True)
	return satir[0]["asset"] if satir else ""


def _varlik_sec(adaylar: list[dict[str, Any]], slot_key: str) -> dict[str, Any] | None:
	canli = [a for a in adaylar if a.get("state") != _EMEKLI]
	if not canli:
		return None
	odakli = _odak_varligi([a["name"] for a in canli])
	if odakli:
		return next(a for a in canli if a["name"] == odakli)
	return max(
		canli,
		key=lambda a: (a.get("slot_key") == slot_key, a.get("state") == _HAZIR, str(a.get("modified"))),
	)


def _kare_ozeti(url: str, w: int, h: int) -> dict[str, Any]:
	"""Ürün görseli kareye tamamlandıysa ilk ölçü `Media URL Redirect.file_names` künyesinde."""
	ozgun = None
	ham = frappe.db.get_value("Media URL Redirect", {"target_url": url}, "file_names")
	try:
		kayitlar = json.loads(ham or "[]")
	except (TypeError, ValueError):
		kayitlar = []
	for k in kayitlar if isinstance(kayitlar, list) else []:
		meta = (k or {}).get("old_meta") or {}
		ow, oh = int(meta.get("th_media_width") or 0), int(meta.get("th_media_height") or 0)
		if ow and oh:
			ozgun = {"width": ow, "height": oh}
			break
	return {"original": ozgun, "size": w if w and w == h else 0}


def _okunur_dosya(url: str, kullanici: str, yonetici: bool, secilen: dict[str, Any] | None) -> str:
	"""Künyesi okunabilecek `File` satırı; okuma hakkı yoksa "".

	Seçilen varlık varsa onun `source_file`ı (kiracı süzgecinden geçmiş ve
	belirlenimci). Yoksa hak, adresin EN ESKİ satırının (creation, name)
	sahibinde. "Çağıranın kendi satırı" YETMEZ: Frappe `upload_file(file_url=…)`
	var olan herhangi bir `/private/files/…` adresine çağıranın sahip olduğu yeni
	bir satır açtırır, yani sahiplik sahtelenebilir; ilk yükleyen ise
	sahtelenemez. `frappe.has_permission("File")` da YETMEZ: açık dosyayı
	herkese okunur sayar. Hak varsa yalnız asıl sahibin satırlarından, ölçüsü
	dolu olan, sonra en eski seçilir (sahte satırın kolonlarına güvenilmez).
	"""
	if secilen:
		return str(secilen.get("source_file") or "")
	dosya = DocType("File")
	satirlar = (
		frappe.qb.from_(dosya)
		.select(dosya.name, dosya.owner, dosya.creation, dosya[FILE_WIDTH_FIELD], dosya[FILE_HEIGHT_FIELD])
		.where(dosya.file_url == url)
		.orderby(dosya.creation)
		.orderby(dosya.name)
	).run(as_dict=True)
	if not satirlar:
		return ""
	asil_sahip = satirlar[0]["owner"]
	if not yonetici and asil_sahip != kullanici:
		return ""
	return min(
		(r for r in satirlar if r["owner"] == asil_sahip),
		key=lambda r: (
			not (int(r.get(FILE_WIDTH_FIELD) or 0) > 0 and int(r.get(FILE_HEIGHT_FIELD) or 0) > 0),
			str(r.get("creation")),
			r["name"],
		),
	)["name"]


def _olcu(asset: str, dosya_adi: str) -> tuple[int, int]:
	"""Piksel ölçüsü: kayıtlı kolonlar, boşsa görsel başlığı (`media_crop` ile aynı yol)."""
	if asset:
		return _FrappeAssetReader()._olculer(asset, dosya_adi)
	olcu = frappe.db.get_value("File", dosya_adi, [FILE_WIDTH_FIELD, FILE_HEIGHT_FIELD], as_dict=True) or {}
	w, h = int(olcu.get(FILE_WIDTH_FIELD) or 0), int(olcu.get(FILE_HEIGHT_FIELD) or 0)
	if w > 0 and h > 0:
		return (w, h)
	return _basliktan_olc(dosya_adi)


def _basliktan_olc(dosya_adi: str) -> tuple[int, int]:
	"""Yalnız dosyanın ilk `_BASLIK_BAYT` baytı okunur — tüm dosya belleğe alınmaz.

	Pillow `Image.open` tembeldir; `.size` başlıktan gelir. JPEG'de SOF işareti
	büyük bir EXIF/ICC bloğunun ardında kalırsa ölçü (0, 0) döner — bilinmeyen
	ölçü olarak kalır, pencere oranı `<img>` yüklenince kendisi ölçer.
	"""
	try:
		yol = frappe.get_doc("File", dosya_adi).get_full_path()
		with open(yol, "rb") as akis:
			bas = akis.read(_BASLIK_BAYT)
	except (OSError, frappe.DoesNotExistError, frappe.ValidationError) as exc:
		frappe.log_error(title="media_preview kaynak okunamadı", message=f"file={dosya_adi!r}: {exc}")
		return (0, 0)
	return _FrappeAssetReader._baytlardan_olc(bas)


def _kaynak_kunyesi(url: str, asset: str, dosya_adi: str) -> dict[str, Any]:
	if not dosya_adi:
		return dict(_BOS_KAYNAK)
	w, h = _olcu(asset, dosya_adi)
	boyut = int(frappe.db.get_value("File", dosya_adi, "file_size") or 0)
	bicim = url.rsplit(".", 1)[-1].lower() if "." in url.rsplit("/", 1)[-1] else ""
	return {"width": w, "height": h, "bytes": boyut, "format": bicim}


def _guncel_adres(url: str) -> str:
	"""Dönüşümle taşınmış adresin güncel hâli — `Media URL Redirect` zinciri.

	`kare.py`/`magaza_gorseli.py` dosyayı içerik adresli yeni URL'ye taşır ve
	AYNI `File` satırını günceller; düzenleyici ise eski adresi tutmaya devam
	eder. Adresin kendi `File` satırı varsa (ya da yönlendirme yoksa) adres
	aynen döner. Yalnız herkese açık `/files/`; kiracı süzgeci hedef adreste
	`_adaylar`da yine uygulanır.
	"""
	gorulen = {url}
	for _adim in range(_YONLENDIRME_ADIMI):
		if not url.startswith("/files/") or frappe.db.exists("File", {"file_url": url}):
			return url
		yon = DocType("Media URL Redirect")
		satir = (
			frappe.qb.from_(yon)
			.select(yon.target_url)
			.where(yon.source_url == url)
			.orderby(yon.creation, order=frappe.qb.desc)
			.limit(1)
		).run(as_dict=True)
		hedef = str(satir[0]["target_url"] or "").strip() if satir else ""
		if not hedef or hedef in gorulen:
			return url
		gorulen.add(hedef)
		url = hedef
	return url


@frappe.whitelist()
def get_preview_target(file_url: str, slot_key: str) -> dict:
	"""Dosya + slot → önizleme hedefi (varlık, ölçü, kayıtlı odak)."""
	_giris_zorunlu()
	if slot_key not in SLOT_KEYS:
		frappe.throw(_("Bilinmeyen görsel yeri: {0}").format(slot_key), frappe.ValidationError)
	url = _guncel_adres(str(file_url or "").strip())
	kim = _principal()
	yonetici = bool(ADMIN_ROLES & set(kim.roles))
	adaylar = _adaylar(url, kim.store, yonetici)
	secilen = _varlik_sec(adaylar, slot_key)
	sahip = kim.store or (str(secilen.get("owner_seller") or "") if secilen else "")

	dosya_adi = _okunur_dosya(url, kim.user, yonetici, secilen)
	kaynak = _kaynak_kunyesi(url, secilen["name"] if secilen else "", dosya_adi)
	if slot_key != "product.image":
		kare = None
	elif dosya_adi:
		kare = _kare_ozeti(url, kaynak["width"], kaynak["height"])
	else:
		kare = {"original": None, "size": 0}
	odak_degeri = odak.odaklar([(url, sahip)]).get((url, sahip)) if secilen else None

	return {
		"file_url": url,
		"slot_key": slot_key,
		"asset": secilen["name"] if secilen else "",
		"processing": not (secilen and secilen.get("state") == _HAZIR),
		"source": kaynak,
		"focal": odak_degeri,
		"square": kare,
	}


@frappe.whitelist()
def get_preview_prefs() -> dict:
	"""Pencere tek yüklemede kendiliğinden açılsın mı — kullanıcıya özel, varsayılan AÇIK."""
	_giris_zorunlu()
	deger = frappe.defaults.get_user_default(PREF_KEY)
	return {"autoopen": deger is None or str(deger).strip().lower() not in ("0", "false")}


@frappe.whitelist(methods=["POST"])
def set_preview_prefs(autoopen: str = "1") -> dict:
	"""Tercihi sunucuda sakla (cihazdan bağımsız)."""
	_giris_zorunlu()
	acik = str(autoopen).strip().lower() not in ("0", "false", "")
	frappe.defaults.set_user_default(PREF_KEY, "1" if acik else "0")
	return {"autoopen": acik}

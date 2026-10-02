"""Mağaza görselleri: WebP master, oran ve şeffaflık korunur (2026-09-30).

Kullanıcı kararı: mağaza görselleri ürün görselinin kare kuralına girmez.

- Kare/beyaz dolgu YOK; en-boy oranı ve şeffaflık (WebP alfa) korunur.
- Master WebP'ye çevrilir, uzun kenar en çok 2000 px, asla büyütülmez.
- Taşıma yolu kare ile AYNI: yeni içerik-adresli adres, `Media URL Redirect`
  301, orijinal 30 gün arşiv, referanslar yeni adrese, geri alma çalışır.
  Taşıma katmanı `kare.py`'dedir; bu modül yalnız kuralı (`KURAL`) ve aday
  listesini verir, mantık kopyalanmaz.

Kapsamdaki görseller (alan → türev slotu):

    Admin Seller Profile.logo            mağaza logosu        seller.logo
    Admin Seller Profile.banner_image    mağaza kapak görseli company.cover_image
    Storefront Layout.sections (JSON)    vitrin slayt/bant    company.cover_image
    Seller Gallery Image.image           şirket galerisi      company.cover_image
    Seller Gallery Image.poster_image    galeri video kapağı  company.cover_image
    Seller Category.image                satıcı kategori      (kendi slotu)

Bir adres yalnız mağaza kaynaklarında (`MAGAZA_KINDS`) kullanılıyorsa mağaza
görselidir. Aynı dosya bir üründe de kullanılıyorsa DOKUNULMAZ (`not_store_image`):
o dosya kare kuralına tabidir.
"""

from __future__ import annotations

import hashlib
import json

import frappe

from tradehub_core.media import kare, refs, retro_rename

MAX_KENAR = 2000
WEBP_QUALITY = 85
AUTO_JOB_KEY = "kare-magaza-auto"
#: Bu modülün kendi kill switch'i; ürün kareleme switch'i de bu yolu kapatır
#: (geri alma talimatı tek anahtarı anlatıyor — ikisini de açmak gerekmesin).
KILL_SWITCH = "magaza_gorseli_donusum_kapali"

MAGAZA_KINDS = frozenset(
	{
		"seller_logo",
		"seller_banner",
		"seller_gallery",
		"seller_gallery_poster",
		"storefront",
		"seller_category_image",
	}
)


def kapali_mi() -> bool:
	return bool(frappe.conf.get(KILL_SWITCH) or frappe.conf.get("urun_gorseli_kare_kapali"))


# ─── Kural ──────────────────────────────────────────────────────────────────


def hazir_mi(w: int, h: int, bicim: str) -> bool:
	"""Başlıktan: zaten WebP ve uzun kenar ≤ 2000 ise dokunulmaz."""
	return bicim == "WEBP" and 0 < max(w, h) <= MAX_KENAR


def webp_cevir(icerik: bytes) -> tuple[bytes, tuple[int, int]]:
	"""`(webp, (w, h))`. Oran ve alfa korunur; yalnız küçültülür, dolgu yok.

	Alfa kanalı tamamen opaksa (ör. RGBA kaydedilmiş düz JPEG) RGB'ye inilir:
	boş alfa düzlemi yalnız bayt harcar. Görünür şeffaflık varsa RGBA kalır.
	"""
	from PIL import Image

	im, bicim, dpi = kare.kaynagi_ac(icerik)
	if hazir_mi(im.width, im.height, bicim):
		raise kare.Atla("already_webp")
	if im.mode in ("LA", "PA") or (im.mode == "P" and "transparency" in im.info):
		im = im.convert("RGBA")
	if im.mode == "RGBA":
		if im.getchannel("A").getextrema() == (255, 255):
			im = im.convert("RGB")
	elif im.mode != "RGB":
		im = im.convert("RGB")
	im.thumbnail((MAX_KENAR, MAX_KENAR), Image.LANCZOS)  # yalnız küçültür
	return kare.webp_yaz(im, dpi, WEBP_QUALITY), (im.width, im.height)


def magaza_gorseli_mi(url: str) -> tuple[bool, bool]:
	"""`(magaza_mi, siparis_var_mi)`. Mağaza dışı canlı kaynak varsa mağaza sayılmaz."""
	bulunan = refs.find(url)
	canli = [r for r in bulunan if not r["readonly"]]
	magaza = bool(canli) and all(r["kind"] in MAGAZA_KINDS for r in canli)
	return magaza, any(r["readonly"] for r in bulunan)


KURAL = kare.DonusumKurali(
	ad="magaza",
	hazir=lambda w, h, bicim: hazir_mi(w, h, bicim),
	hazir_nedeni="already_webp",
	kapsam=lambda url: magaza_gorseli_mi(url),
	kapsam_disi_nedeni="not_store_image",
	cevir=lambda icerik: webp_cevir(icerik),
)


# ─── Adaylar ────────────────────────────────────────────────────────────────


def _json_adresleri(ham, hedef: set[str]) -> None:
	"""JSON içindeki (iç içe) `/files/` adreslerini topla — vitrin slaytları vb."""
	try:
		veri = json.loads(ham or "null")
	except (TypeError, ValueError):
		return
	yigin = [veri]
	while yigin:
		dugum = yigin.pop()
		if isinstance(dugum, dict):
			yigin.extend(dugum.values())
		elif isinstance(dugum, list):
			yigin.extend(dugum)
		elif isinstance(dugum, str) and dugum.startswith(retro_rename.PUBLIC_PREFIX):
			hedef.add(dugum)


def aday_urls(saticilar: list[str] | None = None) -> list[str]:
	"""Mağaza görsel alanlarındaki distinct adresler; `saticilar` verilirse yalnız onlar.

	Sistem işi (toplu iş / kuyruk): tüm mağazalar taranır, kullanıcı kapsamı yok.
	"""
	f_ana = {"name": ["in", saticilar]} if saticilar else {}
	f_cocuk = {"parent": ["in", saticilar]} if saticilar else {}
	urls: set[str] = set()
	for r in frappe.get_all("Admin Seller Profile", filters=f_ana, fields=["logo", "banner_image"]):
		urls |= {r.logo, r.banner_image}
	for r in frappe.get_all("Seller Gallery Image", filters=f_cocuk, fields=["image", "poster_image"]):
		urls |= {r.image, r.poster_image}
	f_kat = {"seller": ["in", saticilar]} if saticilar else {}
	urls |= set(frappe.get_all("Seller Category", filters=f_kat, pluck="image"))
	f_vitrin = {"seller_profile": ["in", saticilar]} if saticilar else {}
	for r in frappe.get_all("Storefront Layout", filters=f_vitrin, fields=["sections"]):
		_json_adresleri(r.sections, urls)
	return sorted(u for u in urls if isinstance(u, str) and kare._gorsel_url(u))


def toplu_donustur(
	job_key: str,
	*,
	dry_run: bool = False,
	batch_size: int = retro_rename.DEFAULT_BATCH,
	satir_anahtari: str | None = None,
) -> dict:
	"""Tüm mağaza görselleri — gövde `kare.toplu_donustur`, kural `KURAL`.

	Kilit YÖNETMEZ; çağıran ortak medya kilidini `job_key` adına tutar.
	`satir_anahtari`: 301 satırlarının etiketi (tek düğme: `<iş>-mg`).
	"""
	return kare.toplu_donustur(
		job_key,
		dry_run=dry_run,
		batch_size=batch_size,
		urls=aday_urls(),
		kural=KURAL,
		satir_anahtari=satir_anahtari,
	)


# ─── Otomatik tetik ─────────────────────────────────────────────────────────


def normalize_seller(seller: str) -> dict:
	"""Tek mağazanın görselleri (kayıt kancasından kuyrukla çağrılır).

	Ortak medya iş kilidi doluyken (toplu iş ya da geri alma sürüyor) hiç
	çalışmaz — `kare.normalize_listing` ile aynı gerekçe.
	"""
	ozet = {"converted": 0, "skipped": 0, "errors": 0}
	if kare._medya_isi_aktif():
		frappe.logger("kare").info(f"magaza: medya işi aktif, {seller} otomatik dönüşüm atlandı")
		ozet["skipped_active_job"] = 1
		return ozet
	for url in aday_urls([seller]):
		out = kare.normalize_one(url, AUTO_JOB_KEY, None, kural=KURAL)
		ozet[{"converted": "converted", "skipped": "skipped"}.get(out["status"], "errors")] += 1
	return ozet


def enqueue_seller(seller: str | None, job_id: str | None = None) -> bool:
	"""`normalize_seller`'i mağaza başına tek iş olarak kuyruğa al (commit sonrası)."""
	if not seller or kapali_mi() or frappe.flags.in_test or frappe.flags.in_migrate:
		return False
	frappe.enqueue(
		"tradehub_core.media.magaza_gorseli.normalize_seller",
		queue="default",
		timeout=600,
		enqueue_after_commit=True,
		job_id=job_id or f"magaza-gorsel-{seller}",
		deduplicate=True,
		seller=seller,
	)
	return True


def _galeri_adresleri(doc) -> set[str]:
	return {
		u
		for r in doc.get("gallery_images") or []
		for u in (r.get("image"), r.get("poster_image"))
		if isinstance(u, str) and u
	}


def on_seller_profile_update(doc, method=None) -> None:
	"""`Admin Seller Profile.on_update`: logo / kapak / galeri değiştiyse dönüşüm kuyruğa."""
	onceki = doc.get_doc_before_save()
	degisti = (
		onceki is None
		or doc.get("logo") != onceki.get("logo")
		or doc.get("banner_image") != onceki.get("banner_image")
		or _galeri_adresleri(doc) != _galeri_adresleri(onceki)
	)
	adresler = {doc.get("logo"), doc.get("banner_image"), *_galeri_adresleri(doc)}
	if degisti and any(isinstance(u, str) and kare._gorsel_url(u) for u in adresler):
		enqueue_seller(doc.name)


def on_storefront_layout_update(doc, method=None) -> None:
	"""`Storefront Layout.on_update`: vitrin bölümleri değiştiyse dönüşüm kuyruğa."""
	onceki = doc.get_doc_before_save()
	if onceki is not None and onceki.get("sections") == doc.get("sections"):
		return
	adresler: set[str] = set()
	_json_adresleri(doc.get("sections"), adresler)
	if any(kare._gorsel_url(u) for u in adresler):
		enqueue_seller(doc.get("seller_profile"))


def _saticilar_for_url(url: str) -> list[str]:
	if not kare._gorsel_url(url):
		return []
	saticilar = set(
		frappe.get_all(
			"Admin Seller Profile",
			or_filters={"logo": url, "banner_image": url},
			pluck="name",
		)
	)
	saticilar |= set(
		frappe.get_all(
			"Seller Gallery Image",
			or_filters={"image": url, "poster_image": url},
			pluck="parent",
		)
	)
	saticilar |= set(
		frappe.get_all(
			"Storefront Layout", filters={"sections": ["like", f"%{url}%"]}, pluck="seller_profile"
		)
	)
	return sorted(s for s in saticilar if s)


def enqueue_for_released_url(url: str) -> int:
	"""AV bekletmesinden çıkan dosya mağaza görseliyse dönüşümü kuyruğa al.

	`kare.enqueue_for_released_url` ile aynı boşluğu kapatır: kayıt anında
	dosya bekletmedeydi ve `quarantined` diye atlandı.
	"""
	if kapali_mi() or frappe.flags.in_test or frappe.flags.in_migrate:
		return 0
	saticilar = _saticilar_for_url(url)
	iz = hashlib.sha1(url.encode()).hexdigest()[:10]
	for satici in saticilar:
		enqueue_seller(satici, job_id=f"magaza-release-{satici}-{iz}")
	return len(saticilar)


# ─── Bayat form koruması (kare C1'in mağaza karşılığı) ──────────────────────


def _yonlendirme_haritasi(adaylar: set[str]) -> dict[str, str]:
	adaylar = {u for u in adaylar if isinstance(u, str) and u.startswith(retro_rename.PUBLIC_PREFIX)}
	if not adaylar:
		return {}
	from frappe.utils import now_datetime

	return {
		r.source_url: r.target_url
		for r in frappe.get_all(
			"Media URL Redirect",
			filters={"source_url": ["in", list(adaylar)], "expires_at": [">", now_datetime()]},
			fields=["source_url", "target_url"],
		)
		if r.target_url
	}


def yonlendirilmis_gorselleri_esle(doc, method=None) -> None:
	"""`Admin Seller Profile.validate`: 301'i olan eski logo/kapak/galeri adresini hedefe çevir.

	Dönüşümden önce açılmış bir form kaydedilirse eski adres geri yazılır; 301
	süresi dolunca mağaza kayıp dosyayı gösterirdi.
	"""
	harita = _yonlendirme_haritasi({doc.get("logo"), doc.get("banner_image"), *_galeri_adresleri(doc)})
	if not harita:
		return
	for alan in ("logo", "banner_image"):
		if doc.get(alan) in harita:
			doc.set(alan, harita[doc.get(alan)])
	for r in doc.get("gallery_images") or []:
		for alan in ("image", "poster_image"):
			if r.get(alan) in harita:
				r.set(alan, harita[r.get(alan)])


def vitrin_yonlendirmelerini_esle(doc, method=None) -> None:
	"""`Storefront Layout.validate`: bölümlerdeki 301'li eski görsel adreslerini hedefe çevir."""
	adresler: set[str] = set()
	_json_adresleri(doc.get("sections"), adresler)
	harita = _yonlendirme_haritasi(adresler)
	if not harita:
		return
	ham = doc.get("sections") or ""
	for eski, yeni in harita.items():
		ham = ham.replace(json.dumps(eski)[1:-1], json.dumps(yeni)[1:-1])
	doc.sections = ham

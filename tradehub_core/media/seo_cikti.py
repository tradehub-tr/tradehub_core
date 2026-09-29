"""API çıktısında okunur görsel adresi — satır listeleri için ortak yardımcılar.

Spec: docs/superpowers/specs/2026-09-28-seo-gorsel-adresi-design.md §5.3

Sepet, favori ve sipariş satırları görseli kendi alanında (`snapshot_image`,
`image`) taşır; okunur adresin slug'ı ise satırın ilanının ORİJİNAL `title`'ından
gelir (dil çevirisi değil — slug her dilde aynı kalsın). İlan silinmişse satırda
saklı ad kullanılır. Kural her uçta aynı: önce tüm adresler toplanır, kodlar TEK
sorguyla alınır, sonra her adres çevrilir (N+1 yok). Veritabanındaki değerlere
DOKUNULMAZ; yalnız çıktı değişir.

`frappe` modül düzeyinde içe aktarılıyor ama `retro_rename` gibi ağır modüller
BİLEREK alınmıyor: bazı sözleşme testleri `frappe`'yi saplayıp bu yolu çağırıyor.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, MutableMapping
from typing import Any

import frappe

#: İçerik-kodlu adres ön eki (`seo_url.HASHED_RE` ile aynı biçim). `seo_url`
#: TEMBEL içe aktarılıyor: modül düzeyinde `frappe.utils.get_files_path`
#: istiyor ve `frappe`'yi saplayan sözleşme testleri (sipariş/satıcı listesi)
#: bu yolu içerik-kodlu adres olmadan da çağırıyor.
_ICERIK_KODLU = re.compile(r"^/files/[0-9a-f]{2}/[0-9a-f]{32}(?:__[a-z0-9]+)?\.[a-z0-9]+$")


def _seo_url():
	from tradehub_core.media import seo_url

	return seo_url


def icerik_kodlu_mu(url: str | None) -> bool:
	return bool(_ICERIK_KODLU.match((url or "").split("?")[0]))


def ilan_ozetleri(adlar: Iterable[str | None]) -> dict[str, dict[str, Any]]:
	"""`{ilan_adı: {"title", "primary_image"}}` — tek sorgu; silinmiş ilan sözlükte yok.

	`get_all` bilinçli: satırlar zaten çağıranın yetki kapısından geçti (kendi
	sepeti/favorisi/siparişi); burada yalnız görsel adının slug'ı için başlık okunuyor.
	"""
	benzersiz = sorted({a for a in adlar if a})
	if not benzersiz:
		return {}
	satirlar = frappe.get_all(
		"Listing",
		filters={"name": ["in", benzersiz]},
		fields=["name", "title", "primary_image"],
		limit_page_length=0,
	)
	return {s.get("name"): s for s in satirlar}


def urun_gorseli_url(url: str | None, baslik: str | None, codes: dict[str, str]) -> str | None:
	"""Ürün GÖRSELİ ise okunur adres; video/boş ise aynen (spec §3: video kapsam dışı).

	Galeri alanları (`images`, künye, manifest) video dosyası da taşıyabiliyor;
	içerik-kodlu video adresi okunur biçime çevrilmez.
	"""
	if not url:
		return url
	from tradehub_core.media.video_poster import VIDEO_UZANTILAR

	if url.lower().split("?")[0].endswith(VIDEO_UZANTILAR):
		return url
	return _seo_url().seo_image_url(url, baslik, codes) if icerik_kodlu_mu(url) else url


def _ayni_site_yolu(url: str) -> str | None:
	"""Mutlak adres bu sitenin (backend ya da vitrin) adresiyse yolunu döndürür; değilse None."""
	from urllib.parse import urlsplit

	parca = urlsplit(url)
	if not parca.scheme:
		return url
	if parca.scheme not in ("http", "https"):
		return None
	siteler = {urlsplit(frappe.utils.get_url()).netloc}
	try:
		from tradehub_core.seo.site_url import storefront_url

		siteler.add(urlsplit(storefront_url()).netloc)
	except Exception:
		frappe.log_error(title="seo_cikti vitrin adresi okunamadı", message=frappe.get_traceback())
	return parca.path if parca.netloc in siteler else None


def to_storage_url(url: str | None) -> str:
	"""Okunur adres → DB'de saklanan içerik-kodlu adres (yazma yolları için).

	Vitrin API'den aldığı okunur adresi (`/files/<slug>-<kod>[__türev].<uzantı>`)
	favori/sipariş yazarken geri gönderiyor. DB'ye okunur adres yazılırsa kullanım
	takibi (`usage`, tam `file_url` eşleşmesi), retro-rename ve sipariş görseli
	kuralı bozulur (review I-1). Adres, okunur biçim nasıl KURULDUYSA öyle geri
	çözülür: kod → `File.seo_code` → türevsiz orijinal hash; türev son eki ve
	uzantı istekteki gibi eklenir. Çözülemezse (tanınmayan kod, belirsiz içerik,
	uzantısı tutmayan orijinal) girdi aynen döner. Aynı sitenin mutlak adresi
	önce yola indirilir; yabancı alan adı aynen kalır.
	"""
	if not url:
		return url or ""
	yol = _ayni_site_yolu(url.strip())
	if yol is None:
		return url
	if "/files/" not in yol:
		return url
	seo_url = _seo_url()
	m = seo_url.SEO_RE.match(yol.split("?")[0])
	if not m:
		return url
	_slug, kod, turev, uzanti = m.groups()
	adaylar = {
		a
		for u in frappe.get_all("File", filters={"seo_code": kod}, pluck="file_url")
		if (a := seo_url.HASHED_RE.match(u or "")) and not a.group(3)
	}
	hashler = {a.group(2) for a in adaylar}
	if len(hashler) != 1:
		return url
	h32 = hashler.pop()
	if not turev and not any(a.group(4) == uzanti for a in adaylar):
		return url
	return f"/files/{h32[:2]}/{h32}{turev}.{uzanti}"


def eski_ad_mi(url: str | None) -> bool:
	"""İçerik-kodlu OLMAYAN yerel `/files/` adresi (retro-rename öncesi ad).

	Okunur biçim (`SEO_RE`) BİLEREK ayrıştırılmıyor: `/files/urun-abcdef12.jpg` gibi
	gerçek bir eski ad da o desene uyar. İlan duruyorsa okunur adresi de güncel
	ana görselden yeniden üretmek zararsız; ayırt etmeye çalışmak eski adı kaçırır.
	"""
	temiz = (url or "").split("?")[0]
	if not temiz.startswith("/files/") or temiz.startswith("/files/media/"):
		return False
	return not icerik_kodlu_mu(temiz)


def satirlari_cevir(
	satirlar: list[MutableMapping[str, Any]],
	*,
	url_alani: str,
	ilan_alani: str = "listing",
	ad_alani: str | None = None,
	eskiyse_ilandan: bool = False,
	ilanlar: dict[str, dict[str, Any]] | None = None,
) -> None:
	"""Satırlardaki görsel adresini yerinde okunur adrese çevirir.

	`eskiyse_ilandan` (sipariş, spec §5.3): saklı adres eski adsa ve ilan hâlâ
	duruyorsa ilanın GÜNCEL `primary_image`'ı kullanılır; ilan yoksa saklı adres
	aynen kalır. Boş adres boş kalır — ilandan görsel uydurulmaz.

	`ilanlar` verilirse (çağıran `title`'ı zaten okuduysa) ek `Listing` sorgusu açılmaz.
	"""
	if not satirlar:
		return
	if ilanlar is None:
		ilanlar = ilan_ozetleri(s.get(ilan_alani) for s in satirlar)
	plan: list[tuple[MutableMapping[str, Any], str, str | None]] = []
	for satir in satirlar:
		url = satir.get(url_alani)
		if not url:
			continue
		ilan = ilanlar.get(satir.get(ilan_alani))
		if eskiyse_ilandan and ilan and ilan.get("primary_image") and eski_ad_mi(url):
			url = ilan["primary_image"]
		baslik = ilan.get("title") if ilan else (satir.get(ad_alani) if ad_alani else None)
		plan.append((satir, url, baslik))
	plan = [(satir, url, baslik) for satir, url, baslik in plan if icerik_kodlu_mu(url)]
	if not plan:
		return
	seo_url = _seo_url()
	kodlar = seo_url.codes_for([url for _, url, _ in plan])
	for satir, url, baslik in plan:
		satir[url_alani] = seo_url.seo_image_url(url, baslik, kodlar)


def okunur_adresler(ciftler: list[tuple[str | None, str | None]]) -> list[str | None]:
	"""`[(adres, başlık)]` → okunur adresler, TEK kod sorgusu. İçerik-kodlu olmayan aynen döner."""
	hedef = [u for u, _ in ciftler if icerik_kodlu_mu(u)]
	if not hedef:
		return [u for u, _ in ciftler]
	seo_url = _seo_url()
	codes = seo_url.codes_for(hedef)
	return [seo_url.seo_image_url(u, b, codes) if icerik_kodlu_mu(u) else u for u, b in ciftler]


#: Okunur adresin yazma yollarından DB'ye sızmış olabileceği sütunlar (review I-1).
_SAKLAMA_ALANLARI: tuple[tuple[str, str], ...] = (
	("Buyer Favorite Item", "snapshot_image"),
	("Cart Item", "snapshot_image"),
	("Order Item", "image"),
)


def normalize_stored_readable_urls(dry_run: int = 1) -> dict:
	"""Tek seferlik, idempotent: saklanmış okunur adresleri içerik-kodlu biçime çevirir.

	Yalnız yerel geliştirme içindir (değişiklik alpha/prod'a çıkmadan yazma
	yollarından sızmış satırlar). `bench --site <site> execute
	tradehub_core.media.seo_cikti.normalize_stored_readable_urls --kwargs "{'dry_run': 0}"`.
	Dönen sayaçlar: `{doctype.alan: {"bulunan", "cevrilen"}}`. Çözülemeyen adres aynen kalır.
	"""
	sonuc: dict[str, dict[str, int]] = {}
	for doctype, alan in _SAKLAMA_ALANLARI:
		satirlar = frappe.get_all(
			doctype,
			filters={alan: ["like", "/files/%-%"]},
			fields=["name", alan],
			limit_page_length=0,
		)
		adaylar = [r for r in satirlar if _seo_url().SEO_RE.match((r.get(alan) or "").split("?")[0])]
		cevrilen = 0
		for r in adaylar:
			yeni = to_storage_url(r.get(alan))
			if yeni and yeni != r.get(alan):
				cevrilen += 1
				if not int(dry_run):
					frappe.db.set_value(doctype, r["name"], alan, yeni, update_modified=False)
		sonuc[f"{doctype}.{alan}"] = {"bulunan": len(adaylar), "cevrilen": cevrilen}
	if not int(dry_run):
		frappe.db.commit()
	return sonuc

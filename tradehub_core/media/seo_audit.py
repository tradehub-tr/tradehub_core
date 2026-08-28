"""Medya SEO denetimi ve skoru — TUR-135 Dilim 3 (§6.3).

Karar belgesi: `docs/MEDYA-SEO-SOZLESMESI.md` §6.3.

NEDEN DENETİM
-------------
Alan göstermek yetmiyor: alanlar Mayıs'tan beri duruyordu ve 3.123 dosyanın
0'ında alt metni vardı (ölçüm 18 Ağu). Panelde "alt metni eksik" rozeti bile
vardı ama kimse toplu resmi göremiyordu. Denetim, "neyi düzeltmeliyim"
sorusunu tek listede cevaplar.

KURALLARIN İKİ SINIFI
---------------------
    ERROR   — arama motoruna yanlış bilgi gidiyor ya da güvenlik/hak sorunu
    WARN    — fırsat kaçıyor, ama yanlış bir şey yayınlanmıyor

Ayrım keyfi değil: bir mağazanın 400 görselinde "alt metni eksik" uyarısı
varsa ve aralarında BİR tane "hakkı dolmuş görsel yayında" varsa, ikisi aynı
renkte görünmemeli.

TEK SORGU İLKESİ
----------------
Kurallar dosya başına DB sorgusu yapmaz: girdi `media/seo.fields_for_many`
ile tek seferde çekilir (anti-patterns.md §6 N+1). Kullanım ve indexability
kararı yalnız istendiğinde hesaplanır — ikisi de pahalı.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import frappe
from frappe.utils import getdate, nowdate

from tradehub_core.media import seo
from tradehub_core.media.video_poster import VIDEO_UZANTILAR
from tradehub_core.seo.i18n import CONTENT_LANGS, DEFAULT_LANG

SEVERITY_ERROR: str = "error"
SEVERITY_WARN: str = "warn"

#: Alt metni bu uzunluğu aşarsa "şüpheli": ölçülen örnekte 100 karakterlik ham
#: ürün başlığı kopyalanmıştı, ekran okuyucu tamamını sesli okuyor.
_ALT_MAX: int = 125
#: Bu kadar kısa metin bilgi taşımıyor ("ürün", "foto").
_ALT_MIN: int = 5
#: Aynı kelimenin tekrarı — anahtar kelime yığını işareti.
_STUFF_REPEAT: int = 3
#: Kötü dosya adı kalıpları (ölçüm: 9 "Ekran", 271 boşluklu ad).
_BAD_NAME = re.compile(
	r"(img[_-]?\d+|ekran\s*g[oö]r[uü]nt[uü]s[uü]|whatsapp|dsc[_-]?\d+|untitled|adsız)", re.I
)


def _kural(kod: str, severity: str, mesaj: str, detay: str = "") -> dict:
	return {"code": kod, "severity": severity, "message": mesaj, "detail": detay}


def _video_mu(file_name: str) -> bool:
	"""Dosya adı video uzantılarından biriyle mi bitiyor — `video_poster` ile aynı küme."""
	return file_name.lower().endswith(VIDEO_UZANTILAR)


def audit_fields(alanlar: dict, *, file_name: str = "") -> list[dict]:
	"""Tek görselin ALAN tabanlı bulguları — DB'ye dokunmaz, saf fonksiyon.

	Kullanım/indexability gerektiren kurallar `audit_file`'da; buradakiler
	yalnız `fields_for` çıktısıyla karar verilebilenler.
	"""
	bulgular: list[dict] = []
	alt = (alanlar.get("alt") or "").strip()
	baslik = (alanlar.get("title") or "").strip()

	if not alt:
		bulgular.append(_kural("missing_alt", SEVERITY_ERROR, "Alt metni yok"))
	else:
		if len(alt) > _ALT_MAX:
			bulgular.append(
				_kural(
					"suspicious_alt",
					SEVERITY_WARN,
					"Alt metni çok uzun — ham ürün başlığı kopyalanmış olabilir",
					f"{len(alt)} karakter",
				)
			)
		if len(alt) < _ALT_MIN:
			bulgular.append(_kural("suspicious_alt", SEVERITY_WARN, "Alt metni bilgi taşımıyor", alt))
		if "(" in alt and ")" in alt and len(alt) > 60:
			bulgular.append(
				_kural("suspicious_alt", SEVERITY_WARN, "Alt metninde parantezli gürültü var", alt[:60])
			)
		kelimeler = [k for k in re.split(r"\W+", alt.lower()) if len(k) > 3]
		for kelime in set(kelimeler):
			if kelimeler.count(kelime) >= _STUFF_REPEAT:
				bulgular.append(
					_kural(
						"keyword_stuffed_alt",
						SEVERITY_WARN,
						"Alt metninde aynı kelime tekrarlanıyor",
						kelime,
					)
				)
				break

	if not baslik:
		bulgular.append(_kural("missing_title", SEVERITY_WARN, "Başlık yok"))
	if not (alanlar.get("caption") or "").strip():
		bulgular.append(_kural("missing_caption", SEVERITY_WARN, "Altyazı yok"))

	if file_name and _BAD_NAME.search(file_name):
		bulgular.append(
			_kural("poor_filename", SEVERITY_WARN, "Dosya adı içerik hakkında bilgi vermiyor", file_name)
		)

	if not (alanlar.get("width") and alanlar.get("height")):
		bulgular.append(
			_kural(
				"missing_dimensions",
				SEVERITY_ERROR,
				"Çözünürlük bilinmiyor — sayfada yanlış yer ayrılıyor (CLS)",
			)
		)

	if not (alanlar.get("license_url") or alanlar.get("copyright_notice")):
		bulgular.append(_kural("missing_license", SEVERITY_WARN, "Lisans/telif bilgisi yok"))

	bitis = alanlar.get("rights_expires_on")
	if bitis and getdate(bitis) < getdate(nowdate()):
		bulgular.append(
			_kural("expired_rights", SEVERITY_ERROR, "Kullanım hakkı dolmuş ama yayında", str(bitis))
		)

	if file_name and _video_mu(file_name):
		if not (alanlar.get("poster_url") or "").strip():
			bulgular.append(_kural("missing_poster", SEVERITY_WARN, "Video posteri yok"))
		if not (alanlar.get("transcript") or "").strip():
			bulgular.append(_kural("missing_transcript", SEVERITY_WARN, "Transcript yok"))
		if not alanlar.get("duration"):
			bulgular.append(_kural("missing_duration", SEVERITY_WARN, "Video süresi bilinmiyor"))

	return bulgular


def audit_file(file_url: str, *, deep: bool = True) -> dict:
	"""Tek görselin tam denetimi — alan + kullanım + indexability.

	`deep=False` kullanım taramasını atlar (pahalı): toplu denetimde
	kullanılır.
	"""
	url = (file_url or "").split("?")[0]
	if not url:
		return {"file_url": "", "findings": [], "score": {}}

	alanlar = seo.fields_for(url)
	ad = frappe.db.get_value("File", {"file_url": url}, "file_name")
	bulgular = audit_fields(alanlar, file_name=ad or "")
	if ad is None:
		bulgular = [
			_kural("missing_file", SEVERITY_ERROR, "Dosya kaydı yok — ürün kırık görsele işaret ediyor")
		]
	ad = ad or ""

	if deep:
		bulgular.extend(_baglamsal_bulgular(url))
		# Görev 6 kararı: `missing_watch_slug` BİLEREK `_baglamsal_bulgular`'a
		# EKLENMEDİ — o fonksiyon hem burada (tekil) hem `audit_batch`'in
		# `deep=True` dalında çağrılıyor. `watch_indexable` üç sorgu açıyor
		# (indexability + poster + vitrin bağı); toplu denetimde N dosya için
		# N kez tetiklemek pahalı olurdu (aynı gerekçe `media_public.
		# _storefront_listings` docstring'inde de var: guest-erişilebilir
		# yüzeyde ucuz tutulan sorgu, toplu tarafta ucuz OLMAYABİLİR). Bu
		# yüzden yalnız tekil dosya denetiminde (bu fonksiyon) çalışır.
		bulgular.extend(_watch_slug_bulgusu(url, ad, alanlar))
		# Görev 6 (Dosya Yöneticisi SEO) — `_doc_bulgulari` `_watch_slug_bulgusu`
		# ile AYNI gerekçeyle yalnız burada (tekil denetim) çağrılıyor:
		# `_document_listings` iki toplu sorgu açıyor (child satır + parent
		# Listing), N dosya için toplu tarafta tekrarlamak pahalı olurdu.
		bulgular.extend(_doc_bulgulari(url, alanlar))

	return {
		"file_url": url,
		"file_name": ad,
		"alt": alanlar.get("alt") or "",
		"alt_source": alanlar.get("alt_source") or "",
		"findings": bulgular,
		"score": score_from(bulgular, alanlar),
	}


def _watch_slug_bulgusu(url: str, file_name: str, alanlar: dict) -> list[dict]:
	"""İzleme sayfası (`/medya/v/<slug>`) slug'ı eksik mi — YALNIZ video.

	Üç koşul birden gerekli: dosya video, `watch_indexable` True (indexability
	+ poster + vitrin bağı — W3 üçlüsü) ve `th_media_slug` boş. Postersiz ya da
	vitrine bağlı olmayan bir videonun slug'ı zaten olmayabilir — o durumda
	uyarı YANLIŞ ALARM olurdu, W3 sağlanmadan bu kural hiç çalışmaz.

	`alanlar` çağıran (`audit_file`) tarafından zaten hesaplanmış `fields_for`
	çıktısı — burada YENİDEN sorgulanmaz, `watch_indexable`'a `fields=` olarak
	geçirilir (aynı "tekrar hesaplama yok" ilkesi `watch_indexable` docstring'inde).
	"""
	if not file_name or not _video_mu(file_name):
		return []
	try:
		from tradehub_core.api.media_public import watch_indexable

		if not watch_indexable(url, fields=alanlar):
			return []
	except Exception:
		frappe.log_error(title="media.seo_audit watch_slug", message=frappe.get_traceback())
		return []

	if (alanlar.get("slug") or "").strip():
		return []
	return [_kural("missing_watch_slug", SEVERITY_WARN, "İzleme sayfası slug'ı yok")]


def _doc_bulgulari(url: str, alanlar: dict) -> list[dict]:
	"""Doküman (PDF/Office) metadata + discoverability kuralları — Dosya
	Yöneticisi SEO görev seti Task 6, `_watch_slug_bulgusu`'nun (video) doküman
	KARDEŞİ: AYNI gerekçeyle yalnız `audit_file`'ın tekil deep dalında çalışır.

	Koşul (ikisi birden gerekli):
	  1. Uzantı `doc_meta.DOC_UZANTILAR` içinde — `doc_indexable`'ın ilk
	     uzantı kontrolüyle AYNI: `Listing Document.file` serbest bir
	     `Attach`, herhangi bir dosya ekli olabilir.
	  2. En az bir `Listing Document` ile VİTRİNDE GÖRÜNEN bir ilana bağlı —
	     `media_public._document_listings` KULLANILIYOR, yeniden yazılmıyor
	     (`doc_indexable`'ın ikinci koşuluyla aynı sorgu). Kimsenin görmediği
	     bir dokümanın başlığını/dilini/metnini denetlemek anlamsız — panel
	     gürültüsü olurdu.

	Üç kural:
	  - `missing_doc_title` (metadata) — `alanlar["title"]` boş. Bu, genel
	    `missing_title` kuralıyla (audit_fields) AYNI alanı okur; kasıtlı
	    ÇAKIŞMA — bir dokümanın vitrinde görünen bir ürüne bağlıyken başlıksız
	    kalması, bağsız/görsel bir dosyadan daha ağır bir SEO fırsatı kaybı,
	    bu yüzden ayrı kod ile AYRICA işaretleniyor (video tarafında
	    `missing_watch_slug`'ın da kendi başına bir kod olması aynı ilke).
	  - `missing_doc_text` (discoverability) — `extracted_text` boş.
	    `page_count` KASITLI OLARAK kontrol edilmiyor: `doc_meta.apply`
	    başarısız çıkarımda page_count'a -1 yazıyor ama `fields_for` bunu
	    dışa `max(0, ...)` ile 0'a kırpıyor (`test_negatif_page_count_
	    disari_sizmiyor`) — yani "çıkarım hiç denenmedi/başarısız" ile
	    "gerçekten 0 sayfa" dışarıdan AYIRT EDİLEMİYOR, ikisinde de metin
	    boştur ve ikisinde de WARN doğru karar (taranamış/taranamaz doküman
	    arama motoruna hiçbir şey söylemiyor). Mesaj bu iki olası kökü de
	    (OCR gerektiren taranmış görüntü ya da henüz çıkarılmamış) taşıyor.
	  - `missing_doc_language` (metadata) — `Listing Document.language`
	    satır alanı. BASİT KURAL: dosya birden çok ilana bağlıysa (aynı
	    dosya farklı ürünlerde farklı `Listing Document` satırlarına
	    girebilir) HERHANGİ birinde dil boşsa WARN — hangi ilanın satırının
	    boş olduğunu ayrıştırmıyor, `_document_listings`'in kendisi de
	    "bağlı mı" sorusunu tekil url için aynı şekilde yalın tutuyor.
	"""
	from tradehub_core.api.media_public import _document_listings
	from tradehub_core.media import doc_meta, upload_policy

	if upload_policy.extension_of(url) not in doc_meta.DOC_UZANTILAR:
		return []
	try:
		if not _document_listings(url):
			return []
	except Exception:
		frappe.log_error(title="media.seo_audit doc_bulgulari", message=frappe.get_traceback())
		return []

	bulgular: list[dict] = []
	if not (alanlar.get("title") or "").strip():
		bulgular.append(_kural("missing_doc_title", SEVERITY_WARN, "Doküman başlığı yok"))

	if not (alanlar.get("extracted_text") or "").strip():
		bulgular.append(
			_kural(
				"missing_doc_text",
				SEVERITY_WARN,
				"Doküman metni çıkarılamadı — taranamaz/boş içerik olabilir, OCR gerekebilir",
			)
		)

	try:
		satirlar = frappe.get_all("Listing Document", filters={"file": url}, fields=["language"])
	except Exception:
		frappe.log_error(title="media.seo_audit doc_bulgulari language", message=frappe.get_traceback())
		satirlar = []
	if any(not (satir.get("language") or "").strip() for satir in satirlar):
		bulgular.append(_kural("missing_doc_language", SEVERITY_WARN, "Doküman dili belirtilmemiş"))

	return bulgular


def _baglamsal_bulgular(url: str) -> list[dict]:
	"""Kullanım ve indexability gerektiren kurallar."""
	bulgular: list[dict] = []
	try:
		from tradehub_core.media import seo_index, usage

		karar = seo_index.decide(url, check_usage=False)
		kullanim = (usage.verdicts_for([url]) or {}).get(url) or {}
		verdict = kullanim.get("verdict")

		if verdict in ("unused", "not_in_use"):
			bulgular.append(_kural("orphan_asset", SEVERITY_WARN, "Hiçbir sayfada kullanılmıyor", verdict))
		elif verdict == "history_only":
			bulgular.append(
				_kural("orphan_asset", SEVERITY_WARN, "Yalnız geçmiş kayıtlarda geçiyor", verdict)
			)

		if verdict == "in_use" and not karar["indexable"]:
			# Sayfada görünen ama aranamayan görsel: ya kasıtlı ya kaza.
			bulgular.append(
				_kural(
					"used_but_noindex",
					SEVERITY_ERROR,
					"Sayfada kullanılıyor ama arama motoruna kapalı",
					karar["reason"],
				)
			)
	except Exception:
		frappe.log_error(title="media.seo_audit context", message=frappe.get_traceback())
	return bulgular


# ── Skor ─────────────────────────────────────────────────────────────────

#: Kural → hangi alt skoru düşürür. Tek sayı yerine kırılım gösteriliyor:
#: "82/100" hangi tarafın zayıf olduğunu söylemiyor (§6.3).
_KURAL_BOYUT: dict[str, str] = {
	"missing_file": "accessibility",
	"missing_alt": "accessibility",
	"suspicious_alt": "accessibility",
	"keyword_stuffed_alt": "accessibility",
	"missing_title": "metadata",
	"missing_caption": "metadata",
	"poor_filename": "metadata",
	"missing_dimensions": "performance",
	"missing_license": "rights",
	"expired_rights": "rights",
	"orphan_asset": "discoverability",
	"used_but_noindex": "discoverability",
	"missing_structured_data": "structured_data",
	"broken_structured_data": "structured_data",
	"oversized_image": "performance",
	"missing_responsive_variants": "performance",
	"missing_modern_format": "performance",
	"incomplete_rendition_ladder": "performance",
	"aspect_ratio_mismatch": "performance",
	"lcp_candidate_unoptimized": "performance",
	"unserved_renditions": "technical_health",
	"broken_url": "technical_health",
	"duplicate_asset": "technical_health",
	"visibility_conflict": "technical_health",
	"missing_association": "discoverability",
	"missing_poster": "performance",
	"missing_transcript": "accessibility",
	"missing_duration": "structured_data",
	"missing_watch_slug": "discoverability",
	"missing_doc_title": "metadata",
	"missing_doc_text": "discoverability",
	"missing_doc_language": "metadata",
	# Dilim 8 (Bulk Localization, L4) — boyutun İLK kodu. `localization` skoru
	# `_yerellestirme_puani`'nden gelir (bu harita SADECE panel `code`
	# süzgeci/gruplaması için); bu yüzden `score_from`'daki genel ceza
	# döngüsü burayı etkilese de bir sonraki satır her zaman ezer (L5: skor
	# formülü DEĞİŞMEZ).
	"missing_localized_alt": "localization",
}

DIMENSIONS: tuple[str, ...] = (
	"accessibility",
	"metadata",
	"performance",
	"rights",
	"discoverability",
	"structured_data",
	"localization",
	"technical_health",
)

#: Ceza puanları. `error` iki katı: yanlış yayın, eksik fırsattan ağır.
_CEZA = {SEVERITY_ERROR: 40, SEVERITY_WARN: 20}


def score_from(bulgular: list[dict], alanlar: dict | None = None) -> dict[str, int]:
	"""Alt kırılımlı skor — her boyut 0-100, artı ağırlıksız ortalama.

	Ağırlıklar bilinçli olarak EŞİT: hangi boyutun daha önemli olduğu ürün
	kararı ve henüz ölçüm yok (§11 soru 6). Eşit başlamak, uydurma bir
	ağırlıkla başlamaktan dürüst.
	"""
	puanlar = {boyut: 100 for boyut in DIMENSIONS}
	for bulgu in bulgular or []:
		boyut = _KURAL_BOYUT.get(bulgu["code"])
		if not boyut:
			continue
		puanlar[boyut] = max(0, puanlar[boyut] - _CEZA.get(bulgu["severity"], 20))

	# Yerelleştirme: kaç dilde alt metni var (varsayılan dil hariç kazanç).
	if alanlar is not None:
		puanlar["localization"] = _yerellestirme_puani(alanlar)

	# Yapısal veri: ImageObject üretilebiliyor mu — en az bir anlamlı alan.
	if alanlar is not None and not any(
		alanlar.get(k) for k in ("alt", "caption", "title", "width", "license_url")
	):
		puanlar["structured_data"] = 0

	puanlar["overall"] = round(sum(puanlar[b] for b in DIMENSIONS) / len(DIMENSIONS))
	return puanlar


def _yerellestirme_puani(alanlar: dict) -> int:
	"""Kaç dilde alt metni var. Tek dil = 100 DEĞİL: vitrin 4 dilli."""
	from tradehub_core.seo.i18n import CONTENT_LANGS

	localized = (alanlar.get("localized") or {}).get("alt") or {}
	if localized:
		dolu = sum(1 for lang in CONTENT_LANGS if str(localized.get(lang) or "").strip())
		return round(100 * dolu / max(1, len(CONTENT_LANGS)))
	return 100 if (alanlar.get("alt") or "").strip() else 0


# ── Toplu denetim ────────────────────────────────────────────────────────


#: Tam kapsam denetiminin önbellek süresi. Local katalogda soğuk tarama
#: 3,8 sn; satır aksiyonları artık tek dosyayı uzlaştırdığı için aynı bedeli
#: dakikada bir tekrar ödemeye gerek yok. Operatörün açık "Yenile" aksiyonu
#: `refresh=1` ile bu cache'i zaten atlar.
SCOPE_CACHE_TTL: int = 3600
#: `_v2` eki bilinçli (CWV tasarımı C7): kural seti değişince eski anahtarla
#: yazılmış 1 saatlik cache okunMAmalı — sürüm eki eski kayıtları görünmez kılar.
SCOPE_CACHE_KEY: str = "tradehub_media_seo_audit_v2"


def audit_scope(
	urls: list[str],
	*,
	deep: bool = False,
	cache_key: str = "",
	refresh: bool = False,
	primary_urls: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
	"""Kapsamın TAMAMINI denetle — özet ve skor bütünü yansıtsın diye.

	Sayfalama sonradan uygulanıyor (`paginate`): özeti yalnız görünen sayfadan
	hesaplamak "138 alt metni eksik" yerine "20 eksik" derdi ve operatör
	işin boyutunu göremezdi.

	`primary_urls` — CWV tasarımı C5: `lcp_candidate_unoptimized` yalnız bu
	kümedeki (ilan `primary_image`) dosyalarda değerlendirilir. `audit_batch`e
	olduğu gibi taşınır.
	"""
	if cache_key and not refresh:
		onbellek = frappe.cache().get_value(f"{SCOPE_CACHE_KEY}:{cache_key}")
		if onbellek:
			return onbellek

	sonuc = audit_batch(urls, deep=deep, primary_urls=primary_urls)
	if cache_key:
		frappe.cache().set_value(f"{SCOPE_CACHE_KEY}:{cache_key}", sonuc, expires_in_sec=SCOPE_CACHE_TTL)
	return sonuc


def paginate(
	sonuc: dict[str, Any],
	*,
	page: int = 1,
	page_size: int = 50,
	code: str = "",
	query: str = "",
) -> dict[str, Any]:
	"""Denetim sonucunu süz ve sayfala — özet/skor DEĞİŞMEZ.

	`code` bulgu süzgeci (sayaç şeridine tıklama), `query` dosya adı/adres
	araması. İkisi de sunucuda uygulanıyor: istemcide süzmek yalnız GÖRÜNEN
	sayfayı süzerdi ve "3 sonuç" derken aslında 300 sonuç olurdu.
	"""
	satirlar = sonuc.get("files") or []
	if code:
		satirlar = [r for r in satirlar if any(f["code"] == code for f in (r.get("findings") or []))]
	if query:
		arama = query.strip().lower()
		satirlar = [
			r
			for r in satirlar
			if arama in (r.get("file_name") or "").lower() or arama in (r.get("file_url") or "").lower()
		]

	toplam = len(satirlar)
	boyut = max(1, min(200, int(page_size or 50)))
	sayfa = max(1, int(page or 1))
	baslangic = (sayfa - 1) * boyut
	return {
		"files": satirlar[baslangic : baslangic + boyut],
		"summary": sonuc.get("summary") or {},
		"score": sonuc.get("score") or {},
		"total": sonuc.get("total") or 0,
		"filtered_total": toplam,
		"page": sayfa,
		"page_size": boyut,
		"page_count": max(1, -(-toplam // boyut)),
	}


def audit_batch(
	file_urls: list[str], *, deep: bool = False, primary_urls: frozenset[str] | set[str] | None = None
) -> dict[str, Any]:
	"""Çok sayıda görselin denetimi — tek sorgu, sonra saf kurallar.

	`deep=True` her dosya için kullanım sorgusu çalıştırır; 100+ dosyada
	pahalıdır ve panel bunu istek üzerine açar.

	`primary_urls` — CWV tasarımı C5: `Listing.primary_image` (LCP adayı)
	kümesi. Varsayılan `None` → boş küme: eski çağıranlar (parametreyi hiç
	bilmeyenler) `lcp_candidate_unoptimized`'ı asla üretmez, davranış kırılmaz.
	"""
	primary = frozenset(primary_urls or ())
	temiz = [u for u in {(u or "").split("?")[0] for u in file_urls or []} if u]
	if not temiz:
		return {"files": [], "summary": {}, "score": {}}

	toplu = seo.fields_for_many(temiz)
	file_fields = ["file_url", "file_name", "file_size", "is_private", "th_media_state"]
	for optional in ("th_media_visibility", "th_media_robots_override"):
		if frappe.db.has_column("File", optional):
			file_fields.append(optional)
	kayitlar = {
		r["file_url"]: r
		for r in frappe.get_all(
			"File", filters={"file_url": ["in", temiz]},
			fields=file_fields,
		)
	}
	url_counts = dict(
		frappe.db.sql(
			"select file_url, count(*) from `tabFile` where file_url in %(urls)s group by file_url",
			{"urls": temiz},
		)
	)
	asset_by_url: dict[str, dict] = {}
	if frappe.db.table_exists("Media Asset"):
		for satir in frappe.db.sql(
			"""select f.file_url, a.name, a.perceptual_hash
			from `tabMedia Asset` a join `tabFile` f on f.name=a.source_file
			where f.file_url in %(urls)s""", {"urls": temiz}, as_dict=True,
		):
			asset_by_url[satir["file_url"]] = satir
	rendition_assets: set[str] = set()
	renditions_by_asset: dict[str, list[dict]] = {}
	if asset_by_url and frappe.db.table_exists("Media Rendition"):
		# CWV tasarımı C2/C3: "türev var mı" kümesi ile format/profil/servis-
		# edilebilirlik kuralları AYNI sorgudan beslenir — alan listesi
		# genişledi, sorgu SAYISI artmadı (tek sorgu ilkesi, N+1 yasağı).
		for r in frappe.get_all(
			"Media Rendition",
			filters={
				"asset": ["in", [a["name"] for a in asset_by_url.values()]],
				"state": ["!=", "purged"],
			},
			fields=["asset", "profile", "format", "width", "height", "state", "benefit_gate_passed"],
			limit_page_length=0,
		):
			renditions_by_asset.setdefault(r["asset"], []).append(r)
		rendition_assets = set(renditions_by_asset)
	# Dilim 8 (Bulk Localization, L4) `missing_localized_alt` kaynağı: url →
	# {lang: kaynak dilde çeviri var mı}. Yalnız GÖRÜNÜR (`storefront_visible=1`)
	# Listing'lerden — kural görünmeyen bir ilan yüzünden yanlış alarm vermesin.
	# `associated_urls` sorgularıyla PAYLAŞILIR (alan listesi genişledi, sorgu
	# SAYISI artmadı — tek yeni sorgu yalnız galeri dalında, N+1 yasağı).
	listing_lang_map: dict[str, dict[str, bool]] = {}
	_yerel_diller = [lang for lang in CONTENT_LANGS if lang != DEFAULT_LANG]

	primary_listing_satirlari = frappe.get_all(
		"Listing",
		filters={"primary_image": ["in", temiz]},
		fields=["primary_image", "storefront_visible", *(f"title_{lang}" for lang in _yerel_diller)],
		limit_page_length=0,
	)
	associated_urls = {r["primary_image"] for r in primary_listing_satirlari if r.get("primary_image")}
	for r in primary_listing_satirlari:
		url = r.get("primary_image")
		if url and r.get("storefront_visible"):
			listing_lang_map[url] = {
				lang: bool(str(r.get(f"title_{lang}") or "").strip()) for lang in _yerel_diller
			}

	galeri_satirlari = frappe.get_all(
		"Listing Image", filters={"image": ["in", temiz]}, fields=["image", "parent"], limit_page_length=0,
	)
	associated_urls.update(r["image"] for r in galeri_satirlari if r.get("image"))
	galeri_parent_adlari = {r["parent"] for r in galeri_satirlari if r.get("parent")}
	if galeri_parent_adlari:
		galeri_listing_satirlari = {
			p["name"]: p
			for p in frappe.get_all(
				"Listing",
				filters={"name": ["in", list(galeri_parent_adlari)], "storefront_visible": 1},
				fields=["name", *(f"title_{lang}" for lang in _yerel_diller)],
				limit_page_length=0,
			)
		}
		for r in galeri_satirlari:
			url = r.get("image")
			ebeveyn = galeri_listing_satirlari.get(r.get("parent"))
			if url and ebeveyn and url not in listing_lang_map:
				listing_lang_map[url] = {
					lang: bool(str(ebeveyn.get(f"title_{lang}") or "").strip()) for lang in _yerel_diller
				}
	for doctype, field in (("Product Category", "image"), ("Seller Category", "image"), ("Brand", "logo")):
		if not frappe.db.table_exists(doctype) or not frappe.get_meta(doctype).has_field(field):
			continue
		associated_urls.update(
			r[field] for r in frappe.get_all(
				doctype, filters={field: ["in", temiz]}, fields=[field], limit_page_length=0,
			) if r.get(field)
		)
	adlar = {u: r.get("file_name") or "" for u, r in kayitlar.items()}

	sonuclar = []
	ozet: dict[str, int] = {}
	toplam_skor: dict[str, list[int]] = {b: [] for b in (*DIMENSIONS, "overall")}
	for url in temiz:
		alanlar = toplu.get(url) or {"file_url": url}
		bulgular = audit_fields(alanlar, file_name=adlar.get(url, ""))
		kayit = kayitlar.get(url) or {}
		asset = asset_by_url.get(url)
		bulgular.extend(
			_technical_findings(
				url,
				alanlar,
				kayit,
				url_count=int(url_counts.get(url) or 0),
				asset=asset,
				rendition_assets=rendition_assets,
				associated=url in associated_urls,
				renditions=renditions_by_asset.get(asset["name"]) if asset else None,
				primary_urls=primary,
				localized_source=listing_lang_map.get(url),
			)
		)
		if url not in kayitlar:
			# Katalog bu adresi gösteriyor ama dosya kaydı yok: alt/title bulguları
			# anlamsız, kök sorun kırık görsel. Tek bulgu, en ağır seviye.
			bulgular = [
				_kural("missing_file", SEVERITY_ERROR, "Dosya kaydı yok — ürün kırık görsele işaret ediyor")
			]
		if deep:
			bulgular.extend(_baglamsal_bulgular(url))
		skor = score_from(bulgular, alanlar)
		for bulgu in bulgular:
			ozet[bulgu["code"]] = ozet.get(bulgu["code"], 0) + 1
		for boyut, deger in skor.items():
			toplam_skor.setdefault(boyut, []).append(deger)
		# Alt metnin kendisi de listeye gidiyor: panel yalnız ✓/— gösterince
		# operatör "Metin üret" bir şey yaptı mı anlayamıyordu.
		sonuclar.append(
			{
				"file_url": url,
				"file_name": adlar.get(url, ""),
				"file_size": (kayitlar.get(url) or {}).get("file_size") or 0,
				"alt": alanlar.get("alt") or "",
				"alt_source": alanlar.get("alt_source") or "",
				"findings": bulgular,
				"score": skor,
			}
		)

	ortalama = {
		boyut: round(sum(degerler) / len(degerler)) if degerler else 0
		for boyut, degerler in toplam_skor.items()
	}
	return {"files": sonuclar, "summary": ozet, "score": ortalama, "total": len(sonuclar)}


#: Denetimin beklediği modern teslim formatları — policy'deki `formats`
#: birleşiminden KESİŞİMLE seçilir; policy hangilerini üretiyorsa onlar
#: beklenir, bu küme koda kopyalanmış bir beklenti listesi DEĞİLDİR (C3).
_MODERN_FORMATLAR: frozenset[str] = frozenset({"avif", "webp"})

#: `require.ratio_tolerance` policy'de okunamaz/geçersizse bu sabit fallback
#: olur (Görev 2 tasarımı, product-image.json `sources.require.ratio_tolerance`
#: T-020 kararı ±%2). Yalnız policy BAŞARIYLA yüklendiğinde ama alan eksikse
#: devreye girer — policy'nin kendisi okunamazsa `_slot_policy` zaten boş dict
#: döner ve tüm CWV kuralları (bu dahil) sessiz kalır.
_RATIO_TOLERANCE: float = 0.02

#: `_slot_policy` istek-içi memo anahtarı. `frappe.local` istek başına
#: sıfırlanır; bu memo'nun amacı TAZELİK değil — aynı istek içinde policy'yi
#: tekrar hesaplamayı önlemek (fan-out'ta 100+ dosya aynı slot'u sorar).
#: Tazelik sözleşmesi zaten altındaki yükleyicide: `ssim._slot_politikalari`
#: `@lru_cache` ile SÜREÇ ÖMRÜ boyunca önbellekli — policy dosyası değişse
#: bile worker yeniden başlayana dek bayat kalabilir (bilinen, kabul edilmiş
#: sözleşme; bu memo onu ne kötüleştirir ne düzeltir).
_POLICY_LOCAL_KEY: str = "th_seo_audit_slot_policy"


def _slot_policy(slot: str = "product.image") -> dict:
	"""Slot policy'sinden denetimin ihtiyacı olan özet — C3: koda kopya YOK.

	`{"modern_formats": set[str], "profiles": [{"name", "width", "fit"}],
	"ratio_tolerance": float}` döner. `fit` (`"pad"`/`"contain"`) review
	bulgusu #1 için taşınıyor: pad-fit profiller kareye (`target_ratio` 1:1)
	dolgulanmış olduğundan CLS oran kıyaslamasında kullanılamaz. Kaynak
	`policy/slots/*.json`; okuma pipeline'ın MEVCUT yükleyicisiyle yapılır
	(`quality.ssim._slot_politikalari`, süreç başına bir kez), çıkan özet
	istek içinde `frappe.local` üstünde memoize edilir. Policy okunamaz ya da
	profilsizse boş dict: denetim DÜŞMEZ, kurallar sessiz kalır ve sorun
	log'a düşer.
	"""
	cache = getattr(frappe.local, _POLICY_LOCAL_KEY, None)
	if cache is None:
		cache = {}
		setattr(frappe.local, _POLICY_LOCAL_KEY, cache)
	if slot in cache:
		return cache[slot]

	sonuc: dict = {}
	try:
		from tradehub_core.media.pipeline.quality.ssim import _slot_politikalari

		ham = _slot_politikalari().get(slot) or {}
		profiller = [
			{
				"name": str(p.get("name") or ""),
				"width": int(p.get("width") or 0),
				"fit": str(p.get("fit") or ""),
			}
			for p in (ham.get("profiles") or [])
			if p.get("name")
		]
		if profiller:
			formatlar: set[str] = set()
			for p in ham.get("profiles") or []:
				formatlar.update(str(f) for f in (p.get("formats") or []))
			try:
				tolerans = float((ham.get("require") or {}).get("ratio_tolerance"))
			except (TypeError, ValueError):
				tolerans = _RATIO_TOLERANCE
			sonuc = {
				"modern_formats": formatlar & _MODERN_FORMATLAR,
				"profiles": profiller,
				"ratio_tolerance": tolerans,
			}
		else:
			frappe.log_error(
				title="media.seo_audit slot_policy",
				message=f"Slot policy okunamadı ya da profilsiz: {slot}",
			)
	except Exception:
		frappe.log_error(title="media.seo_audit slot_policy", message=frappe.get_traceback())
	cache[slot] = sonuc
	return sonuc


def _servis_edilebilir(renditions: list[dict]) -> list[dict]:
	"""Servis edilebilirlik tanımı — Task 1 ile AYNI: `state=ready` +
	`benefit_gate_passed`. Tek yerde tutulur, `_rendition_bulgulari`'nin iki
	dalı da (unserved + oran) buradan besleniyor."""
	return [r for r in renditions if r.get("state") == "ready" and r.get("benefit_gate_passed")]


def _rendition_bulgulari(url: str, alanlar: dict, renditions: list[dict] | None) -> list[dict]:
	"""Format/merdiven/oran kuralları — CWV denetimi (tasarım §3, C2/C3).

	YALNIZ en az bir türevi olan görsel-sınıfı dosyalarda çalışır: hiç türevi
	olmayan asset `missing_responsive_variants`'ın işidir (ayrık küme — aynı
	dosyada ikisi birden tetiklenmez), video/doküman uzantıları kapsam dışı.

	Servis edilebilirlik hiçbir türevde sağlanmıyorsa kök neden
	`unserved_renditions`dır: format/merdiven/oran kuralları o dosya için
	ÜRETİLMEZ, üretilmiş ama boşa gitmiş türevlerden format/merdiven/oran
	çıkarımı yapmak yanlış alarm olurdu (Görev 2 tasarımı §3).
	"""
	from tradehub_core.media import upload_policy

	if not renditions or upload_policy.kind_of(url) != upload_policy.KIND_IMAGE:
		return []

	servis_turevler = _servis_edilebilir(renditions)
	if not servis_turevler:
		# `ready` ama gate düşmüş türev, hiç üretilememiş türevden farklı bir
		# operasyonel durum (review bulgusu #3) — ikisi de detayda ayrı görünür.
		detay = ", ".join(
			f"{r.get('profile') or '?'}:{r.get('state') or '?'}"
			f"/gate={int(bool(r.get('benefit_gate_passed')))}"
			for r in renditions
		)
		return [
			_kural(
				"unserved_renditions",
				SEVERITY_WARN,
				"Türev(ler) üretilmiş ama hiçbiri servis edilebilir değil",
				detay,
			)
		]

	policy = _slot_policy()
	if not policy:
		return []

	out: list[dict] = []
	servis = {str(r.get("format") or "") for r in servis_turevler}
	modern = policy.get("modern_formats") or set()
	if modern and not (servis & modern):
		out.append(
			_kural(
				"missing_modern_format",
				SEVERITY_WARN,
				"Servis edilebilir modern format (AVIF/WebP) türevi yok",
				f"servis edilebilir: {', '.join(sorted(f for f in servis if f)) or 'yok'}",
			)
		)

	# Upscale beklenmez: kaynak ölçüsünün (ya da üretilmiş en büyük türevin)
	# izin verdiği basamakların üstü "eksik" sayılmaz.
	max_kaynak = max(
		int(alanlar.get("width") or 0),
		max((int(r.get("width") or 0) for r in renditions), default=0),
	)
	uretilen = {str(r.get("profile") or "") for r in renditions}
	eksik = [
		p["name"]
		for p in policy.get("profiles") or []
		if p["width"] and p["width"] <= max_kaynak and p["name"] not in uretilen
	]
	if eksik:
		out.append(
			_kural(
				"incomplete_rendition_ladder",
				SEVERITY_WARN,
				"Rendition merdiveninde eksik basamaklar var",
				", ".join(eksik),
			)
		)

	# CLS riski: kaynağın oranı ile servis edilen EN BÜYÜK ORAN-KORUYAN
	# (`fit != "pad"`) türevin oranı toleransın dışına çıkarsa sayfada
	# ayrılan alan yanlış olur (§3 aspect_ratio_mismatch). `pad` profiller
	# (w96…w768) `target_ratio=1:1` ile KARE dolgulanır — bunları kıyaslamak
	# policy-izinli 4:5/3:4 kaynaklarda HER ZAMAN yanlış pozitif üretirdi
	# (review bulgusu #1, reviewer container repro'su). Hiç oran-koruyan
	# servis edilebilir türev yoksa (yalnız pad basamaklar üretilmiş) kural
	# sessiz kalır — kıyaslanacak güvenilir bir aday yok.
	# Ölçüsüz kaynakta (missing_dimensions zaten var) kıyaslanacak bir oran
	# yok — bilerek sessiz kalır.
	kaynak_w = int(alanlar.get("width") or 0)
	kaynak_h = int(alanlar.get("height") or 0)
	if kaynak_w > 0 and kaynak_h > 0:
		oran_koruyan_profiller = {p["name"] for p in policy.get("profiles") or [] if p.get("fit") != "pad"}
		oran_adaylari = [r for r in servis_turevler if str(r.get("profile") or "") in oran_koruyan_profiller]
		if oran_adaylari:
			en_buyuk = max(oran_adaylari, key=lambda r: int(r.get("width") or 0))
			turev_w = int(en_buyuk.get("width") or 0)
			turev_h = int(en_buyuk.get("height") or 0)
			if turev_w > 0 and turev_h > 0:
				tol = policy.get("ratio_tolerance")
				tolerans = float(tol) if tol is not None else _RATIO_TOLERANCE
				if abs((kaynak_w / kaynak_h) - (turev_w / turev_h)) > tolerans:
					out.append(
						_kural(
							"aspect_ratio_mismatch",
							SEVERITY_WARN,
							"Kaynak ve servis edilen türevin en-boy oranı uyuşmuyor — CLS riski",
							f"kaynak {kaynak_w}x{kaynak_h}, türev {turev_w}x{turev_h}",
						)
					)

	return out


def _lcp_bulgusu(
	url: str, alanlar: dict, renditions: list[dict] | None, *, unserved: bool
) -> list[dict]:
	"""LCP adayı (birincil görsel) ek kritiklik kuralı — tasarım §3/§4 (C5).

	Yalnız `_technical_findings` bu dosyanın `primary_urls` içinde olduğunu
	doğruladığında çağrılır. Tetik: modern format YOK veya boyut bilgisi eksik.
	Bayt/piksel bütçesi (`oversized_image`) burada YOK — spec bilinçli olarak
	onu ayrı bırakıyor (çifte ceza değil).

	`unserved=True` (yani `unserved_renditions` zaten tetiklendi — türev(ler)
	üretilmiş ama hiçbiri servis edilebilir değil) ise modern-format bacağı
	BİLEREK atlanır: aynı kök nedeni iki koddan raporlamak çifte gürültü
	olurdu, `unserved_renditions` zaten doğru sinyal. Bu durumda LCP kuralı
	yalnız boyut-eksik bacağıyla değerlendirilir.
	"""
	from tradehub_core.media import upload_policy

	nedenler: list[str] = []
	# Boyut bacağı KASITLI olarak `KIND_IMAGE` kontrolü yapmıyor — format bacağının
	# aksine. `primary_urls` (C5) sözleşmesi gereği LCP adayı zaten
	# `Listing.primary_image`; pratikte bu her zaman bir görsel dosyasıdır, video/
	# doküman asla bu kümeye girmez. Asimetri bilinçli: boyut eksikliği dosya
	# türünden bağımsız evrensel bir sinyal, modern-format ise yalnız görsel
	# formatları için anlamlı bir kavram (video/doküman'da "AVIF/WebP" kavramı yok).
	if not (alanlar.get("width") and alanlar.get("height")):
		nedenler.append("boyut bilgisi eksik")

	if not unserved and upload_policy.kind_of(url) == upload_policy.KIND_IMAGE:
		policy = _slot_policy()
		modern = policy.get("modern_formats") if policy else None
		if modern:
			servis_formatlari = {str(r.get("format") or "") for r in _servis_edilebilir(renditions or [])}
			if not (servis_formatlari & modern):
				nedenler.append("modern format yok")

	if not nedenler:
		return []
	return [
		_kural(
			"lcp_candidate_unoptimized",
			SEVERITY_WARN,
			"LCP adayı (ilanın birincil görseli) optimize değil",
			", ".join(nedenler),
		)
	]


def _missing_localized_alt_bulgusu(alanlar: dict, kaynak_diller: dict[str, bool] | None) -> list[dict]:
	"""Dilim 8 (Bulk Localization, L4) — "çevrilebilirdi ama çevrilmedi" sinyali.

	Üç koşul birden gerekli:
	  1. Dosyanın alt'ı (tr ya da taban) DOLU — boş alt zaten `missing_alt`'ın
	     işi, burada tekrar edilmez.
	  2. `kaynak_diller` (batch katmanında ön-yüklenmiş, url'nin bağlı olduğu
	     GÖRÜNÜR Listing'in `title_{lang}` doluluğu) en az bir dilde True.
	  3. O dilin `alt_{lang}` kolonu boş.

	`kaynak_diller` boş/None ise (dosya hiçbir görünür Listing'e bağlı değil,
	ya da hiçbir dilde kaynak çevirisi yok) kural SESSİZ kalır — kopyalama
	yasağıyla (L1) aynı tutarlılık: çeviri kaynağı yoksa "eksik" demek yanlış
	alarm olurdu.
	"""
	if not kaynak_diller:
		return []
	if not (alanlar.get("alt") or "").strip():
		return []
	localized_alt = (alanlar.get("localized") or {}).get("alt") or {}
	eksik = sorted(
		lang
		for lang, var in kaynak_diller.items()
		if var and not str(localized_alt.get(lang) or "").strip()
	)
	if not eksik:
		return []
	return [
		_kural(
			"missing_localized_alt",
			SEVERITY_WARN,
			"Kaynak çevirisi mevcut ama alt metni bu dillerde eksik",
			", ".join(eksik),
		)
	]


def _technical_findings(
	url: str,
	alanlar: dict,
	kayit: dict,
	*,
	url_count: int,
	asset: dict | None,
	rendition_assets: set[str],
	associated: bool,
	renditions: list[dict] | None = None,
	primary_urls: frozenset[str] = frozenset(),
	localized_source: dict[str, bool] | None = None,
) -> list[dict]:
	"""Dosya/teslim/structured-data temelli, toplu sorgularla beslenen kurallar."""
	out: list[dict] = []
	out.extend(_missing_localized_alt_bulgusu(alanlar, localized_source))
	parsed = urlsplit(url)
	if (
		not url.startswith(("/files/", "/private/files/", "http://", "https://"))
		or parsed.scheme == "javascript"
	):
		out.append(
			_kural("broken_url", SEVERITY_ERROR, "Dosya adresi teslim edilebilir bir medya URL'si değil", url)
		)
	w = int(alanlar.get("width") or 0)
	h = int(alanlar.get("height") or 0)
	bytes_ = int(kayit.get("file_size") or 0)
	if (w * h) > 12_000_000 or bytes_ > 2 * 1024 * 1024:
		out.append(_kural(
			"oversized_image", SEVERITY_WARN,
			"Görsel piksel/bayt bütçesini aşıyor",
			f"{w}x{h}, {bytes_} bytes",
		))
	if asset and asset.get("name") not in rendition_assets:
		out.append(_kural("missing_responsive_variants", SEVERITY_WARN, "Responsive türev bulunamadı"))
	out.extend(_rendition_bulgulari(url, alanlar, renditions))
	if url in primary_urls:
		# Kök-neden kapısı `_rendition_bulgulari` ile AYNI: türev(ler) üretilmiş
		# ama hiçbiri servis edilebilir değilse (unserved_renditions) modern-
		# format bacağı ona bırakılır (bkz. `_lcp_bulgusu` docstring).
		unserved = bool(renditions) and not _servis_edilebilir(renditions)
		out.extend(_lcp_bulgusu(url, alanlar, renditions, unserved=unserved))
	if url_count > 1:
		out.append(
			_kural(
				"duplicate_asset", SEVERITY_WARN,
				"Aynı delivery URL birden fazla File kaydında", str(url_count),
			)
		)
	if not associated:
		out.append(
			_kural("missing_association", SEVERITY_WARN, "Asset bir ürün veya kategori bağlamına bağlı değil")
		)
	if not any(alanlar.get(k) for k in ("alt", "caption", "title", "width", "license_url")):
		out.append(
			_kural("missing_structured_data", SEVERITY_WARN, "Anlamlı ImageObject üretmek için metadata yok")
		)
	for key in ("license_url", "acquire_license_url"):
		value = str(alanlar.get(key) or "")
		if value and not value.startswith(("/", "http://", "https://")):
			out.append(_kural("broken_structured_data", SEVERITY_ERROR, f"Geçersiz {key}", value))
	visibility = str(kayit.get("th_media_visibility") or "")
	robots = str(kayit.get("th_media_robots_override") or "").lower()
	if kayit.get("is_private") and url.startswith("/files/"):
		out.append(_kural("visibility_conflict", SEVERITY_ERROR, "Private asset public URL altında"))
	if visibility == "Public" and "noindex" in robots:
		out.append(_kural("visibility_conflict", SEVERITY_ERROR, "Public asset robots override ile noindex"))
	return out

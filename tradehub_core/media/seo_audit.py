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

	return {
		"file_url": url,
		"file_name": ad,
		"alt": alanlar.get("alt") or "",
		"alt_source": alanlar.get("alt_source") or "",
		"findings": bulgular,
		"score": score_from(bulgular, alanlar),
	}


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
	"broken_url": "technical_health",
	"duplicate_asset": "technical_health",
	"visibility_conflict": "technical_health",
	"missing_association": "discoverability",
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
SCOPE_CACHE_KEY: str = "tradehub_media_seo_audit"


def audit_scope(
	urls: list[str], *, deep: bool = False, cache_key: str = "", refresh: bool = False
) -> dict[str, Any]:
	"""Kapsamın TAMAMINI denetle — özet ve skor bütünü yansıtsın diye.

	Sayfalama sonradan uygulanıyor (`paginate`): özeti yalnız görünen sayfadan
	hesaplamak "138 alt metni eksik" yerine "20 eksik" derdi ve operatör
	işin boyutunu göremezdi.
	"""
	if cache_key and not refresh:
		onbellek = frappe.cache().get_value(f"{SCOPE_CACHE_KEY}:{cache_key}")
		if onbellek:
			return onbellek

	sonuc = audit_batch(urls, deep=deep)
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


def audit_batch(file_urls: list[str], *, deep: bool = False) -> dict[str, Any]:
	"""Çok sayıda görselin denetimi — tek sorgu, sonra saf kurallar.

	`deep=True` her dosya için kullanım sorgusu çalıştırır; 100+ dosyada
	pahalıdır ve panel bunu istek üzerine açar.
	"""
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
	if asset_by_url and frappe.db.table_exists("Media Rendition"):
		rendition_assets = {
			r["asset"] for r in frappe.get_all(
				"Media Rendition", filters={
					"asset": ["in", [a["name"] for a in asset_by_url.values()]],
					"state": ["!=", "purged"],
				},
				fields=["asset"], group_by="asset", limit_page_length=0,
			)
		}
	associated_urls = {
		r["primary_image"] for r in frappe.get_all(
			"Listing", filters={"primary_image": ["in", temiz]}, fields=["primary_image"], limit_page_length=0,
		) if r.get("primary_image")
	}
	associated_urls.update(
		r["image"] for r in frappe.get_all(
			"Listing Image", filters={"image": ["in", temiz]}, fields=["image"], limit_page_length=0,
		) if r.get("image")
	)
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
		bulgular.extend(_technical_findings(
			url, alanlar, kayit, url_count=int(url_counts.get(url) or 0),
			asset=asset_by_url.get(url), rendition_assets=rendition_assets,
			associated=url in associated_urls,
		))
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


def _technical_findings(
	url: str, alanlar: dict, kayit: dict, *, url_count: int,
	asset: dict | None, rendition_assets: set[str], associated: bool,
) -> list[dict]:
	"""Dosya/teslim/structured-data temelli, toplu sorgularla beslenen kurallar."""
	out: list[dict] = []
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

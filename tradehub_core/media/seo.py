"""Medya SEO alanları — TEK okuma kapısı ve yazma yolu (TUR-135 Dilim 1).

Karar belgesi: `docs/MEDYA-SEO-SOZLESMESI.md`. Mimari kaydı: ADR-0023.

NEDEN TEK KAPI
--------------
SEO alanlarının bugünkü evi `File.th_media_*` (yamalar `v15_9_15`, `v15_9_37`).
Medya motoru olgunlaştığında ev `Media Asset` olabilir (ADR-0023 "metadata evi
— bayrak öncesi karar"). Tüketiciler — ImageObject üreticisi, site haritası,
Listing API'si, vitrin, denetim kuralları — o gün DEĞİŞMESİN diye hepsi
buradan okur:

    fields_for(file_url, ref_doctype=..., ref_name=..., ref_field=..., lang=...)

Taşıma günü yalnız bu modülün içi değişir. Doğrudan `th_media_alt` okuyan
kod yazılmamalı; `tests/test_media_seo.py` bunu kural olarak sabitliyor.

ÜÇ KATMAN — SIRA ANLAMLIDIR
---------------------------
    1. Kullanım ezmesi   `Media SEO Override` (bu sayfada bu görsel)
    2. Varlık varsayılanı `File.th_media_*`   (bu dosya, her yerde)
    3. Boş                                    (üretim kuralı Dilim 2'de devreye girer)

Aynı görsel `/urun/bmw-x5` ve `/blog/bmw-x5-inceleme` sayfalarında farklı alt
metni ister; katman 1 bunun içindir. Ezme YOKSA varlık varsayılanı basılır —
her sayfa için ezme yazmak zorunlu değil, istisna yönetimidir.

ÇOK DİL
-------
`alt`, `title`, `caption` dört dilde (`_tr/_en/_ar/_ru`). Çözüm sırası
`seo/i18n.resolve_content_field` ile AYNI: istenen dil → varsayılan dil →
eski tek-dil kolonu. Aynı fonksiyon kullanılıyor, ikinci bir çözücü yazılmadı.

BOŞ, YANLIŞTAN İYİDİR
---------------------
Hiçbir katmanda değer yoksa boş dize döner. Ekran okuyucu boş `alt`'ı
"dekoratif görsel" diye geçer; uydurma metin ise yalan söyler. Bu ilke
üretim kuralında da (Dilim 2 §5.1) geçerlidir.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

import frappe
from frappe.utils import cint

from tradehub_core.seo.i18n import CONTENT_LANGS, DEFAULT_LANG, resolve_content_field

#: Çok dilli VE kullanım başına ezilebilir alanlar. `File` kolon öneki
#: `th_media_`, ezme tablosunda (`Media SEO Override`) çıplak ad.
#:
#: Bu üçlü BİLEREK büyümüyor: şartnamenin §2 "asset metadata ile kullanım
#: metadata'sı ayrılmalı" maddesi yalnız alt/title/caption override'ı sayıyor.
#: Yeni bir alanı buraya eklemek `Media SEO Override`'a dört kolon daha
#: açmak ve her kullanım satırını şişirmek demek.
TRANSLATABLE: tuple[str, ...] = ("alt", "title", "caption")

#: Çok dilli ama YALNIZ varlık düzeyinde tutulan alanlar (§11).
#:
#: `TRANSLATABLE`'dan farkı: aynı asset'in iki farklı kullanımı için ayrı
#: değer TUTULMAZ. Gerekçe alanların doğasında — bir görselin açıklaması ya
#: da bir videonun transkripti dosyanın kendisine ait; hangi sayfada
#: gösterildiğine göre değişmez. Alt metni değişir (bağlam anlatır),
#: transkript değişmez (ses aynı ses).
#:
#: 10 Eyl 2026'da `description` `SINGLE`'dan BURAYA taşındı: şartname §11
#: "alt, title, caption ve description alanları locale bazında tutulabilmeli"
#: diyor ve description tek dilliydi. `transcript`/`captions_url` de aynı
#: maddenin ikinci cümlesiyle ("transcript ve subtitle çok dilli") geldi.
ASSET_TRANSLATABLE: tuple[str, ...] = ("description", "transcript", "captions_url")

#: Tek dilli varlık alanları (dış yüzeyde render edilmiyor ya da dilden bağımsız).
SINGLE: tuple[str, ...] = (
	"tags",
	"creator",
	"creator_type",
	"credit_text",
	"copyright_notice",
	"license_url",
	"acquire_license_url",
	"usage_rights",
	"rights_expires_on",
	"seo_filename",
	"slug",
	"canonical",
	"alt_source",
	# ── §2 alan seti tamamlaması (v15_9_54) ──────────────────────────────
	"long_description",
	"keywords",
	"entities",
	"content_purpose",
	"source",
	"creator_role",
	"country",
	"region",
	"location",
	"geo",
	# ── §5 Video SEO alanları (v15_9_54) ─────────────────────────────────
	# `chapters` JSON metni olarak taşınıyor; ayrıştırma `seo_render`/
	# `schema_builder` tarafında, bu katman metni taşır ve doğrular.
	"chapters",
	"regions_allowed",
	"age_restriction",
	"content_rating",
	# ── §17 etiket kaynağı (v15_9_54) ────────────────────────────────────
	# Etiket → kaynak eşlemesi (JSON). `tags`'ın YANINDA duruyor, içinde
	# değil: `tags` virgüllü metin ve şeklini değiştirmek onu okuyan her
	# yeri (arama, filtre, panel, yedek) kırardı.
	"tag_sources",
)

OVERRIDE_DOCTYPE: str = "Media SEO Override"

#: `alt` üretim kaynağı. Kural motoru (Dilim 2) yalnız `rule`/`ai` olanı
#: yeniler; `human`/`edited` bir daha ASLA otomatik ezilmez.
SOURCE_RULE: str = "rule"
SOURCE_AI: str = "ai"
SOURCE_HUMAN: str = "human"
SOURCE_EDITED: str = "edited"
REFRESHABLE: frozenset[str] = frozenset({"", SOURCE_RULE, SOURCE_AI})


def _temiz_url(file_url: str) -> str:
	return (file_url or "").split("?")[0].strip()


def _asset_columns(*, include_text: bool = False) -> list[str]:
	"""Okunacak `File` kolonları — kolon yoksa sorguya girmez.

	Yama koşmamış bir site'ta (ör. test ortamı, eski kurulum) sorgu patlamasın:
	`th_media_caption` ve dil kolonları `v15_9_37` ile geliyor.

	`include_text=True` yalnız tekil okuma (`fields_for`) çağırır: `th_media_extracted_text`
	Long Text — toplu yolda (`fields_for_many`, `audit_batch`, sitemap ön-yükleme) 100+
	satırda N×64KB taşır. `page_count` (Int) küçük olduğu için ayrım gerekmiyor, her zaman gelir.
	"""
	adaylar = [f"th_media_{alan}" for alan in SINGLE]
	for alan in (*TRANSLATABLE, *ASSET_TRANSLATABLE):
		adaylar.append(f"th_media_{alan}")
		# `transcript` dil kolonları Long Text. Toplu yolda dört dilin dördü
		# birden 100+ satırda `extracted_text`'le AYNI sorunu üretirdi
		# (N×4×64KB) — bu yüzden onlar da `include_text` kapısının arkasında.
		# Taban `th_media_transcript` kolonu dışarıda kalıyor: v15_9_49'dan
		# beri toplu yolda geliyor ve onu çıkarmak mevcut çağıranları kırardı.
		if alan == "transcript" and not include_text:
			continue
		adaylar.extend(f"th_media_{alan}_{lang}" for lang in CONTENT_LANGS)
	# Çözünürlük `SINGLE` listesinde DEĞİL (SEO metni değil, dosyanın fiziksel
	# gerçeği) ama `_birlestir` onu döndürüyor: sorguya alınmazsa her zaman 0
	# döner ve vitrin sabit 800×800 basmaya devam eder. Ölçüldü: denetim
	# 4.776 dosyanın ölçüsü DOLDUKTAN sonra bile "eksik" diyordu.
	adaylar.extend(("th_media_width", "th_media_height"))
	# Video sistem alanları da width/height gibi: SEO metni değil, dosyanın
	# fiziksel gerçeği. SINGLE'a koymamak bilinçli — set_asset_fields'tan
	# yazılamazlar (poster'ı/süreyi yalnız üretim hattı yazar).
	adaylar.extend(("th_media_duration", "th_media_poster_url"))
	# Doküman (PDF vb.) sistem alanları — sayfa sayısı ve çıkarılan metin aynı
	# desen: SEO metni değil, üretim hattının çıkardığı fiziksel/otomatik
	# gerçek. SINGLE'a koymamak bilinçli — set_asset_fields'tan yazılamazlar
	# (yalnız üretim hattı/patch yazar). `page_count` küçük (Int) — toplu yolda kalır.
	adaylar.append("th_media_page_count")
	# Ses sistem alanı — süre/poster ile AYNI desen: SEO metni değil, üretim
	# hattının kapsayıcı etiketinden çıkardığı gerçek. SINGLE'a koymamak
	# bilinçli, `set_asset_fields`'tan yazılamaz.
	adaylar.append("th_media_artist")
	if include_text:
		adaylar.append("th_media_extracted_text")
	return [k for k in adaylar if frappe.db.has_column("File", k)]


def _override_row(file_url: str, ref_doctype: str, ref_name: str, ref_field: str) -> dict:
	if not (ref_doctype and ref_name and ref_field):
		return {}
	if not frappe.db.table_exists(OVERRIDE_DOCTYPE):
		return {}
	satir = frappe.db.get_value(
		OVERRIDE_DOCTYPE,
		{
			"file_url": file_url,
			"ref_doctype": ref_doctype,
			"ref_name": ref_name,
			"ref_field": ref_field,
		},
		"*",
		as_dict=True,
	)
	return satir or {}


def _asset_row(file_url: str, store: str | None = None, *, include_text: bool = False) -> dict:
	"""Varlık varsayılanı — aynı adrese ait `File` kayıtlarından biri.

	Aynı içerik birden çok mağazaya ait olabiliyor (içerik-adresli adlandırma;
	ölçüm: 30 adres). Her mağaza kendi alt metnini yazabildiği için hangi
	kaydın okunacağı önemli: `store` verilirse o mağazanın kaydı tercih edilir,
	yoksa DOLU alt metni olan ilk kayıt — boş bir ikiz yüzünden dolu metin
	kaybolmasın diye.

	`include_text` — bkz. `_asset_columns` docstring: tekil okuma (`fields_for`)
	`th_media_extracted_text`'i ister, toplu yol istemez.
	"""
	kolonlar = _asset_columns(include_text=include_text)
	if not kolonlar:
		return {}
	satirlar = frappe.get_all(
		"File",
		filters={"file_url": file_url},
		fields=["name", "owner", *kolonlar],
		limit_page_length=0,
	)
	if not satirlar:
		return {}
	if store:
		from tradehub_core.media import ownership

		for satir in satirlar:
			if ownership.store_of(satir.get("owner")) == store:
				return satir
	for satir in satirlar:
		if any(satir.get(f"th_media_alt_{lang}") for lang in CONTENT_LANGS) or satir.get("th_media_alt"):
			return satir
	return satirlar[0]


def _coz(kayit: dict, alan: str, lang: str, onek: str = "") -> str:
	"""Çok dilli alanı çöz — `resolve_content_field` ile aynı fallback zinciri."""
	if not kayit:
		return ""
	# `resolve_content_field` `{alan}_{lang}` bekliyor; File tarafında önek var.
	tam = f"{onek}{alan}"
	kucultulmus = {anahtar[len(onek) :]: deger for anahtar, deger in kayit.items() if anahtar.startswith(tam)}
	return resolve_content_field(kucultulmus, alan, lang, DEFAULT_LANG)


def _override_value(kayit: dict, alan: str, lang: str) -> tuple[bool, str]:
	"""Ezmede alan tanımlı mı ve değeri ne.

	Boş dize burada anlamlıdır: editör bu kullanımı dekoratif ilan edip
	``alt=""`` yazmış olabilir. Genel i18n resolver'ları boşu "eksik" sayar;
	usage override için bu davranış asset varsayılanını yanlışlıkla geri
	getirir. ``None`` alanın hiç belirlenmediğini, ``""`` bilinçli boşluğu
	ifade eder.
	"""
	if not kayit:
		return False, ""
	istenen = f"{alan}_{lang}"
	if kayit.get(istenen) is not None:
		return True, str(kayit.get(istenen) or "")
	varsayilan = f"{alan}_{DEFAULT_LANG}"
	if kayit.get(varsayilan) is not None:
		return True, str(kayit.get(varsayilan) or "")
	# Eski tek-dil kayıtlarına geriye uyum.
	if kayit.get(alan) is not None:
		return True, str(kayit.get(alan) or "")
	return False, ""


def fields_for(
	file_url: str,
	*,
	ref_doctype: str = "",
	ref_name: str = "",
	ref_field: str = "",
	lang: str = DEFAULT_LANG,
	store: str | None = None,
) -> dict[str, Any]:
	"""Bir görselin bir kullanımdaki SEO alanları — TÜM tüketicilerin kapısı.

	`ref_*` verilirse kullanım ezmesi katmanı devreye girer; verilmezse varlık
	varsayılanı döner (ör. medya kütüphanesi listesi, denetim).

	Dönen sözlük dış yüzeyin ihtiyacı olan her şeyi taşır: metinler, lisans
	beşlisi, hak süresi, boyutlar (CLS için `width`/`height`), üretim kaynağı.
	Boş alan `""` olarak döner — `None` değil: JSON'da tür değiştirmesin ve
	şablonlar `or` ile zincirleyebilsin.
	"""
	url = _temiz_url(file_url)
	if not url:
		return {}

	varlik = _asset_row(url, store=store, include_text=True)
	ezme = _override_row(url, ref_doctype, ref_name, ref_field)
	# Birleştirme `_birlestir`'de: toplu okuma da aynı yolu kullanıyor, iki
	# yerde iki farklı katman sırası doğmasın.
	return _birlestir(url, varlik, lang, ezme)


def fields_for_many(
	file_urls: list[str], *, lang: str = DEFAULT_LANG, store: str | None = None
) -> dict[str, dict[str, Any]]:
	"""Toplu okuma — liste ekranları ve site haritası için.

	Kullanım ezmesi UYGULANMAZ: toplu çağıranların kullanım bağlamı yok
	(sitemap bir dosyayı bir kez listeler). Bağlamı olan çağıran `fields_for`
	kullanır. Ayrım bilinçli — sessizce yanlış katman uygulamaktansa hiç
	uygulamamak yeğdir.
	"""
	temiz = list(dict.fromkeys(_temiz_url(u) for u in file_urls or []))
	temiz = [u for u in temiz if u]
	if not temiz:
		return {}

	# TEK sorgu — döngü içinde `fields_for` çağırmak N+1 üretiyordu (ölçüm:
	# 50 dosya 156 ms). Site haritası binlerce dosya listeleyecek; orada aynı
	# desen dakikalara çıkardı (anti-patterns.md §6).
	kolonlar = _asset_columns()
	if not kolonlar:
		return {u: {"file_url": u} for u in temiz}

	satirlar = frappe.get_all(
		"File",
		filters={"file_url": ["in", temiz]},
		fields=["name", "owner", "file_url", *kolonlar],
		limit_page_length=0,
	)
	gruplu: dict[str, list[dict]] = {}
	for satir in satirlar:
		gruplu.setdefault(satir["file_url"], []).append(satir)

	return {u: _birlestir(u, _sec(gruplu.get(u, []), store), lang) for u in temiz}


def _sec(satirlar: list[dict], store: str | None) -> dict:
	"""Aynı adrese ait kayıtlardan hangisi okunacak — `_asset_row` ile aynı kural."""
	if not satirlar:
		return {}
	if store:
		from tradehub_core.media import ownership

		for satir in satirlar:
			if ownership.store_of(satir.get("owner")) == store:
				return satir
	for satir in satirlar:
		if any(satir.get(f"th_media_alt_{lang}") for lang in CONTENT_LANGS) or satir.get("th_media_alt"):
			return satir
	return satirlar[0]


def _birlestir(url: str, varlik: dict, lang: str, ezme: dict | None = None) -> dict[str, Any]:
	"""Katmanları tek sözlüğe indir. `fields_for` ve `fields_for_many` ORTAK yolu —
	iki yerde iki farklı birleştirme mantığı olmasın."""
	ezme = ezme or {}
	sonuc: dict[str, Any] = {"file_url": url}
	for alan in TRANSLATABLE:
		ezilmis, deger = _override_value(ezme, alan, lang)
		if not ezilmis:
			deger = _coz(varlik, alan, lang, onek="th_media_")
		sonuc[alan] = deger or ""
	# Varlık düzeyinde çok dilli alanlar: ezme YOK, doğrudan dil çözümü.
	# `TRANSLATABLE` döngüsünün aynısı ama `_override_value` adımı olmadan —
	# bu alanların kullanım başına değeri yok (gerekçe `ASSET_TRANSLATABLE`).
	for alan in ASSET_TRANSLATABLE:
		sonuc[alan] = _coz(varlik, alan, lang, onek="th_media_") or ""
	for alan in SINGLE:
		sonuc[alan] = varlik.get(f"th_media_{alan}") or ""
	if ezme.get("source"):
		sonuc["alt_source"] = ezme["source"]
	sonuc["width"] = varlik.get("th_media_width") or 0
	sonuc["height"] = varlik.get("th_media_height") or 0
	# `audio_meta.apply` başarısız çıkarımda -1 yazıyor (anti-açlık damgası,
	# `backfill_pending` aynı okunamayan dosyayı yeniden seçmesin diye — İÇ
	# sözleşme). `page_count` ile AYNI nöbetçi: negatif süre dışarıya sızarsa
	# JSON-LD'ye "PT-1S" gibi geçersiz bir değer basılırdı.
	sonuc["duration"] = max(0, float(varlik.get("th_media_duration") or 0))
	sonuc["poster_url"] = varlik.get("th_media_poster_url") or ""
	sonuc["artist"] = varlik.get("th_media_artist") or ""
	# `cover_url` AYRI KOLON DEĞİL, `poster_url`in ses tarafındaki adı:
	# "medyayı temsil eden sabit görsel" videoda poster, seste kapak — aynı
	# kavram. İkinci bir kolon açmak aynı gerçeği iki yerde tutmak olurdu.
	sonuc["cover_url"] = sonuc["poster_url"]
	# `doc_meta.apply` başarısız çıkarımda -1 yazıyor (anti-açlık damgası,
	# `backfill_docs` aynı okunamayan dosyayı yeniden seçmesin diye — İÇ
	# sözleşme). Dışarıya (`fields_for`/`fields_for_many` tüketicileri: panel,
	# JSON-LD) negatif sayfa sayısı ASLA sızmamalı — `max(0, ...)` nöbetçiyi
	# burada, tek yerde durduruyor.
	sonuc["page_count"] = max(0, cint(varlik.get("th_media_page_count")))
	sonuc["extracted_text"] = varlik.get("th_media_extracted_text") or ""
	# `has_text` metnin KENDİSİ değil VARLIĞI. Ayrı anahtar olmasının sebebi
	# `extracted_text`'in toplu yolda hiç okunmaması (Long Text, 100+ satırda
	# N×64KB — `_asset_columns` docstring'i): toplu denetim metnin var olup
	# olmadığını bilmek zorunda ama metni taşımak zorunda değil. Toplu yolda
	# burada False kalır ve `seo_audit.audit_scope` tek bir varlık sorgusuyla
	# üzerine yazar; tekil yolda doğrudan doğru değer çıkar.
	sonuc["has_text"] = bool(sonuc["extracted_text"].strip())
	sonuc["overridden"] = bool(ezme)
	sonuc["localized"] = {
		alan: {
			l: (
				str(ezme.get(f"{alan}_{l}") or "")
				if ezme.get(f"{alan}_{l}") is not None
				else str(varlik.get(f"th_media_{alan}_{l}") or "")
			)
			for l in CONTENT_LANGS
		}
		for alan in TRANSLATABLE
	}
	# Varlık düzeyi çok dilli alanlar AYNI `localized` sözlüğüne giriyor ama
	# ezme katmanına hiç bakmadan. Panelin tek bir yerden okuması için ayrı
	# anahtar açılmadı: `localized["description"]["en"]` ile
	# `localized["alt"]["en"]` istemci için aynı şey — farkı YAZMA tarafı
	# biliyor (`set_override` `ASSET_TRANSLATABLE`'ı reddeder).
	sonuc["localized"].update(
		{
			alan: {l: str(varlik.get(f"th_media_{alan}_{l}") or "") for l in CONTENT_LANGS}
			for alan in ASSET_TRANSLATABLE
		}
	)
	return sonuc


def listing_usage_contexts(listing_name: str, file_urls: list[str] | None = None) -> list[dict[str, str]]:
	"""Listing görsellerinin kanonik usage kimlikleri.

	Ana görsel doğrudan ``Listing`` kaydına; galeri görseli ise parent adına
	değil gerçek ``Listing Image.name`` child-row kimliğine bağlanır. API,
	schema ve sitemap aynı resolver'ı kullanarak kimlik sapmasını önler.
	"""
	if not listing_name:
		return []
	hedef = {_temiz_url(u) for u in (file_urls or []) if _temiz_url(u)}
	ana = frappe.db.get_value("Listing", listing_name, "primary_image") or ""
	sonuc: list[dict[str, str]] = []
	if ana and (not hedef or ana in hedef):
		sonuc.append({
			"file_url": ana,
			"ref_doctype": "Listing",
			"ref_name": listing_name,
			"ref_field": "primary_image",
			"context_doctype": "Listing",
			"context_name": listing_name,
			# Ana görselin rolü kayıttan OKUNMAZ, kimliğinden gelir:
			# `Listing.primary_image` alanında duruyorsa o ürünün birincil
			# görselidir. `Listing Image` satırlarının aksine burada rol
			# alanı yok ve olması da anlamsız olurdu (§12).
			"media_role": "primary",
		})
	# `media_role` (v15_9_54) yaması koşmamış bir veritabanında kolon yok;
	# alan listesine koşulsuz eklemek sorguyu düşürürdü.
	alanlar = ["name", "image", "idx"]
	if frappe.db.has_column("Listing Image", "media_role"):
		alanlar.append("media_role")
	for satir in frappe.get_all(
		"Listing Image",
		filters={"parent": listing_name, "parenttype": "Listing"},
		fields=alanlar,
		order_by="idx asc",
		limit_page_length=0,
	):
		url = _temiz_url(satir.get("image") or "")
		if not url or (hedef and url not in hedef):
			continue
		sonuc.append({
			"file_url": url,
			"ref_doctype": "Listing Image",
			"ref_name": satir["name"],
			"ref_field": "image",
			"context_doctype": "Listing",
			"context_name": listing_name,
			# Rol boşsa "gallery": galeri tablosundaki bir satırın varsayılan
			# rolü galeri olmaktır. Boş bırakmak tüketiciyi (feed, panel)
			# "rol yok" ile "rol galeri" arasında karar vermeye zorlardı.
			"media_role": str(satir.get("media_role") or "").strip() or "gallery",
		})
	return sonuc


def usage_overrides_for(file_url: str, *, lang: str = DEFAULT_LANG) -> list[dict[str, Any]]:
	"""Bir asset'in katalog kullanımları ve her kullanımdaki etkili metadata."""
	url = _temiz_url(file_url)
	if not url:
		return []
	listing_names = {
		r["name"] for r in frappe.get_all("Listing", filters={"primary_image": url}, fields=["name"])
	}
	listing_names.update(
		r["parent"] for r in frappe.get_all(
			"Listing Image", filters={"image": url, "parenttype": "Listing"}, fields=["parent"]
		)
	)
	out: list[dict[str, Any]] = []
	for listing_name in sorted(listing_names):
		listing = frappe.db.get_value("Listing", listing_name, ["title", "slug"], as_dict=True) or {}
		for context in listing_usage_contexts(listing_name, [url]):
			row = _override_row(url, context["ref_doctype"], context["ref_name"], context["ref_field"])
			effective = fields_for(
				url, ref_doctype=context["ref_doctype"], ref_name=context["ref_name"],
				ref_field=context["ref_field"], lang=lang,
			)
			out.append({
				**context, "label": listing.get("title") or listing_name,
				"page_path": f"/urun/{listing.get('slug')}" if listing.get("slug") else "",
				"override_name": row.get("name") or "", "overridden": bool(row),
				"values": {k: row.get(k) for k in row if k in {f"{a}_{l}" for a in TRANSLATABLE for l in CONTENT_LANGS}},
				"effective": {k: effective.get(k, "") for k in TRANSLATABLE},
			})
	return out


# ── Yazma ────────────────────────────────────────────────────────────────


def set_asset_fields(file_url: str, values: dict[str, Any], *, store: str | None = None) -> int:
	"""Varlık varsayılanını yaz — etkilenen `File` kaydı sayısını döndürür.

	Yalnız bilinen alanlar yazılır (beyaz liste): istek gövdesine
	`th_media_state` koyup yaşam döngüsünü değiştirmeye çalışan bir çağrı
	buradan geçemez — `media/metadata.py`'deki aynı korumanın SEO tarafı.

	`store` verilirse yalnız o mağazanın kayıtlarına yazılır: aynı adrese ait
	başka mağazanın alt metni ezilmez (TUR-298 ortak sahiplik dersi).
	"""
	url = _temiz_url(file_url)
	if not url or not values:
		return 0

	values = _validate_asset_values(values)
	izinli: dict[str, Any] = {}
	for anahtar, deger in values.items():
		if anahtar in SINGLE:
			izinli[f"th_media_{anahtar}"] = deger
		elif anahtar in TRANSLATABLE or anahtar in ASSET_TRANSLATABLE:
			izinli[f"th_media_{anahtar}"] = deger
		elif "_" in anahtar:
			taban, _, lang = anahtar.rpartition("_")
			# `ASSET_TRANSLATABLE` de dil ekli yazmayı kabul eder
			# (`description_en`); farkı YALNIZ `set_override`'da — orası
			# kullanım katmanı ve bu alanların orada karşılığı yok.
			if taban in (*TRANSLATABLE, *ASSET_TRANSLATABLE) and lang in CONTENT_LANGS:
				izinli[f"th_media_{anahtar}"] = deger
	izinli = {k: v for k, v in izinli.items() if frappe.db.has_column("File", k)}
	if not izinli:
		return 0

	adlar = _hedef_kayitlar(url, store)
	if not adlar:
		return 0
	frappe.db.set_value("File", {"name": ["in", adlar]}, izinli, update_modified=False)
	return len(adlar)


def _validate_asset_values(values: dict[str, Any]) -> dict[str, Any]:
	"""Rights/URL alanlarını DB yazımından önce doğrula."""
	clean = dict(values or {})
	for key in ("license_url", "acquire_license_url", "canonical"):
		if key not in clean:
			# Anahtar girdide hiç yoksa BURADA EKLEME: `set_asset_fields` sonradan
			# bunu `SINGLE` alanı sanıp boş dizeyle DB'ye yazıyordu — çağıran
			# yalnız `transcript` gönderse bile `license_url`/`acquire_license_url`/
			# `canonical` her seferinde sıfırlanıyordu (final inceleme veri-silme
			# bug'ı). `rights_expires_on` dalı zaten aynı deseni uyguluyor.
			continue
		value = str(clean.get(key) or "").strip()
		if value:
			parsed = urlsplit(value)
			if value.startswith("//"):
				# F-20: protokolsüz (scheme-relative) URL de "/" ile başladığı
				# için "site içi yol" dalına düşüyor ve doğrulamadan geçiyordu.
				# Tarayıcı `//kotu.site/x` adresini sayfanın protokolüyle DIŞ
				# alan adına çözer; bu değer JSON-LD ile yayına çıkıyor.
				frappe.throw(
					frappe._("Geçersiz URL: {0} — protokolsüz adres kabul edilmiyor").format(key)
				)
			elif value.startswith("/"):
				pass
			elif parsed.scheme not in ("http", "https") or not parsed.netloc:
				frappe.throw(frappe._("Geçersiz URL: {0}").format(key))
		clean[key] = value
	creator_type = str(clean.get("creator_type") or "").strip()
	if creator_type and creator_type not in ("Person", "Organization"):
		frappe.throw(frappe._("Creator type Person veya Organization olmalıdır."))
	if "rights_expires_on" in clean:
		value = clean.get("rights_expires_on")
		if value:
			from frappe.utils import getdate

			try:
				clean["rights_expires_on"] = str(getdate(value))
			except Exception:
				frappe.throw(frappe._("Geçersiz hak bitiş tarihi."))
		else:
			clean["rights_expires_on"] = None
	_dogrula_yeni_alanlar(clean)
	return clean


#: `th_media_geo` biçimi: "enlem,boylam". Aralık kontrolü ayrıca yapılıyor —
#: desen "91,181"i de kabul eder, dünya etmez.
_GEO_DESEN = re.compile(r"^-?\d{1,3}(\.\d+)?\s*,\s*-?\d{1,3}(\.\d+)?$")

#: ISO 3166-1 alpha-2 — iki büyük harf. `regions_allowed` bunlardan virgüllü.
_ULKE_DESEN = re.compile(r"^[A-Z]{2}$")


def _dogrula_yeni_alanlar(clean: dict[str, Any]) -> None:
	"""v15_9_54 ile gelen alanların biçim doğrulaması.

	Hepsi yapısal veriye ya da HTTP başlığına giriyor; serbest metin olarak
	bırakmak geçersiz JSON-LD üretmenin en kısa yolu. Doğrulama YAZMA
	anında, okuma anında değil — bozuk değer DB'ye hiç girmesin ki
	`schema_builder` her okumada yeniden savunma yapmak zorunda kalmasın.
	"""
	geo = str(clean.get("geo") or "").strip()
	if geo:
		if not _GEO_DESEN.match(geo):
			frappe.throw(frappe._("Koordinat biçimi 'enlem,boylam' olmalıdır."))
		enlem, boylam = (float(p) for p in geo.split(","))
		if not (-90 <= enlem <= 90) or not (-180 <= boylam <= 180):
			frappe.throw(frappe._("Koordinat aralık dışında."))
		clean["geo"] = f"{enlem},{boylam}"

	for anahtar in ("country", "region"):
		deger = str(clean.get(anahtar) or "").strip().upper()
		if deger and not _ULKE_DESEN.match(deger):
			frappe.throw(frappe._("{0} iki harfli ISO 3166-1 kodu olmalıdır.").format(anahtar))
		if anahtar in clean:
			clean[anahtar] = deger

	izinli = str(clean.get("regions_allowed") or "").strip().upper()
	if izinli:
		kodlar = [p.strip() for p in izinli.split(",") if p.strip()]
		if not kodlar or any(not _ULKE_DESEN.match(k) for k in kodlar):
			frappe.throw(frappe._("İzinli bölgeler virgülle ayrılmış ISO 3166-1 kodları olmalıdır."))
		clean["regions_allowed"] = ",".join(dict.fromkeys(kodlar))

	yas = str(clean.get("age_restriction") or "").strip().lower()
	if yas and yas != "18+":
		# schema.org `isFamilyFriendly`/`contentRating` ikilisinde Google'ın
		# tanıdığı TEK yaş kısıtı değeri "18+". Serbest metin ("16 yaş",
		# "R18") yapısal veride hiçbir şey ifade etmez.
		frappe.throw(frappe._("Yaş sınırı yalnız '18+' olabilir."))
	if "age_restriction" in clean:
		clean["age_restriction"] = yas

	_dogrula_json_alan(clean, "chapters", liste=True)
	_dogrula_json_alan(clean, "tag_sources", liste=False)


def _dogrula_json_alan(clean: dict[str, Any], anahtar: str, *, liste: bool) -> None:
	"""JSON taşıyan kolonu ayrıştırılabilirlik ve şekil için doğrula.

	Değer METİN olarak saklanıyor (kolon Long Text/Small Text). Burada
	ayrıştırılıp yeniden basılmasının sebebi normalleştirme değil DOĞRULAMA:
	bozuk JSON bir kez girerse onu okuyan her yer (panel, JSON-LD, yedek)
	ayrı ayrı savunma yazmak zorunda kalır.
	"""
	if anahtar not in clean:
		return
	ham = clean.get(anahtar)
	if ham in (None, ""):
		clean[anahtar] = ""
		return
	if isinstance(ham, str):
		try:
			veri = json.loads(ham)
		except ValueError:
			frappe.throw(frappe._("{0} geçerli JSON değil.").format(anahtar))
	else:
		veri = ham
	if liste:
		if not isinstance(veri, list) or any(
			not isinstance(x, dict) or "start" not in x for x in veri
		):
			frappe.throw(frappe._("Bölümler [{{'start': saniye, 'title': metin}}] biçiminde olmalıdır."))
		# Sıralı tutulur: `SeekToAction`/`hasPart` çıktısı zaman sırasına
		# göre okunuyor ve sıralamayı tüketiciye bırakmak her tüketicide
		# tekrarlanan bir iş demek.
		veri = sorted(veri, key=lambda x: float(x.get("start") or 0))
	elif not isinstance(veri, dict):
		frappe.throw(frappe._("{0} bir nesne olmalıdır.").format(anahtar))
	clean[anahtar] = json.dumps(veri, ensure_ascii=False)


def _hedef_kayitlar(url: str, store: str | None) -> list[str]:
	satirlar = frappe.get_all("File", filters={"file_url": url}, fields=["name", "owner"])
	if not store:
		return [s["name"] for s in satirlar]
	from tradehub_core.media import ownership

	return [s["name"] for s in satirlar if ownership.store_of(s.get("owner")) == store]


def set_override(
	file_url: str,
	*,
	ref_doctype: str,
	ref_name: str,
	ref_field: str,
	values: dict[str, Any],
	source: str = SOURCE_HUMAN,
) -> str:
	"""Kullanım ezmesini yaz/güncelle — kaydın adını döndürür.

	Boş değerler ezmeyi SİLMEZ, boş olarak saklar: "bu sayfada alt metni
	bilerek boş" ile "ezme yok" farklı şeylerdir. Ezmeyi tamamen kaldırmak
	`clear_override` işidir.
	"""
	url = _temiz_url(file_url)
	if not (url and ref_doctype and ref_name and ref_field):
		frappe.throw(frappe._("Kullanım ezmesi için dosya ve kullanım bilgisi zorunlu."))

	anahtar = {
		"file_url": url,
		"ref_doctype": ref_doctype,
		"ref_name": ref_name,
		"ref_field": ref_field,
	}
	mevcut = frappe.db.get_value(OVERRIDE_DOCTYPE, anahtar, "name")
	doc = (
		frappe.get_doc(OVERRIDE_DOCTYPE, mevcut)
		if mevcut
		else frappe.get_doc({"doctype": OVERRIDE_DOCTYPE, **anahtar})
	)

	for alan, deger in (values or {}).items():
		if alan in TRANSLATABLE:
			doc.set(f"{alan}_{DEFAULT_LANG}", deger)
			continue
		taban, _, lang = alan.rpartition("_")
		if taban in TRANSLATABLE and lang in CONTENT_LANGS:
			doc.set(alan, deger)
			continue
		# Varlık düzeyi alanı ezme olarak yazılamaz — ve bunu SESSİZCE
		# düşürmek en kötüsü olurdu: çağıran `description_en` yazıp
		# kaydedildiğini sanır, panelde hiçbir şey değişmez ve hata da
		# görmez. `ASSET_TRANSLATABLE` gerekçesi tanımının yanında.
		if taban in ASSET_TRANSLATABLE or alan in ASSET_TRANSLATABLE:
			frappe.throw(
				frappe._("'{0}' varlık düzeyinde bir alan; kullanım ezmesi olarak yazılamaz.").format(alan)
			)
	doc.source = source
	doc.save(ignore_permissions=True)
	return doc.name


def clear_override(file_url: str, *, ref_doctype: str, ref_name: str, ref_field: str) -> bool:
	"""Ezmeyi kaldır — varlık varsayılanına geri dönülür."""
	url = _temiz_url(file_url)
	ad = frappe.db.get_value(
		OVERRIDE_DOCTYPE,
		{
			"file_url": url,
			"ref_doctype": ref_doctype,
			"ref_name": ref_name,
			"ref_field": ref_field,
		},
		"name",
	)
	if not ad:
		return False
	frappe.delete_doc(OVERRIDE_DOCTYPE, ad, ignore_permissions=True)
	return True


# ── Dile özel medya ezmesi (§11) ─────────────────────────────────────────

LOCALE_VARIANT_DOCTYPE: str = "Media Locale Variant"


def locale_variants_for(file_url: str, *, store: str | None = None) -> dict[str, dict[str, str]]:
	"""`{dil: {"variant_url": ..., "poster_url": ...}}` — tanımlı ezmeler.

	Mağazaya özel satır, platform geneli satırı EZER. Sıra anlamlıdır:
	platform bir varsayılan koyabilir, satıcı kendi mağazası için onu
	değiştirebilir — `Media SEO Override`'ın varlık/kullanım katmanlarıyla
	aynı mantık, bir katman aşağıda.
	"""
	url = _temiz_url(file_url)
	if not url or not frappe.db.table_exists(LOCALE_VARIANT_DOCTYPE):
		return {}

	satirlar = frappe.get_all(
		LOCALE_VARIANT_DOCTYPE,
		filters={"file_url": url},
		fields=["locale", "store", "variant_url", "poster_url"],
		limit_page_length=0,
	)
	out: dict[str, dict[str, str]] = {}
	# Önce platform geneli (store boş), sonra mağazaya özel — ikincisi
	# birincinin üzerine yazsın diye bu SIRAYLA işleniyor.
	for magazali in (False, True):
		for satir in satirlar:
			var_magaza = bool(satir.get("store"))
			if var_magaza is not magazali:
				continue
			if magazali and store and satir.get("store") != store:
				continue
			if magazali and not store:
				# Mağaza bağlamı verilmemişse mağazaya özel satır
				# uygulanamaz: hangisinin geçerli olduğu bilinmiyor.
				continue
			out[satir["locale"]] = {
				"variant_url": satir.get("variant_url") or "",
				"poster_url": satir.get("poster_url") or "",
			}
	return out


def resolve_media_for_locale(
	file_url: str, *, lang: str = DEFAULT_LANG, store: str | None = None
) -> dict[str, str]:
	"""Bu dilde GERÇEKTEN kullanılacak medya adresi ve posteri.

	Ezme yoksa kaynağın kendisi döner — çağıran "ezme var mı" diye ayrıca
	sormak zorunda kalmasın. `overridden` bayrağı hangi dalın çalıştığını
	söyler; panel bunu rozet olarak gösteriyor.
	"""
	url = _temiz_url(file_url)
	ezmeler = locale_variants_for(url, store=store)
	ezme = ezmeler.get(lang) or {}
	return {
		"file_url": ezme.get("variant_url") or url,
		"poster_url": ezme.get("poster_url") or "",
		"source_url": url,
		"locale": lang,
		"overridden": bool(ezme.get("variant_url") or ezme.get("poster_url")),
	}

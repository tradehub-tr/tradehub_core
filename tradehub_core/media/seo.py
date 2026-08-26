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

from typing import Any
from urllib.parse import urlsplit

import frappe

from tradehub_core.seo.i18n import CONTENT_LANGS, DEFAULT_LANG, resolve_content_field

#: Çok dilli alanlar — `File` kolon öneki `th_media_`, ezme tablosunda çıplak ad.
TRANSLATABLE: tuple[str, ...] = ("alt", "title", "caption")

#: Tek dilli varlık alanları (dış yüzeyde render edilmiyor ya da dilden bağımsız).
SINGLE: tuple[str, ...] = (
	"description",
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
	"transcript",
	"captions_url",
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


def _asset_columns() -> list[str]:
	"""Okunacak `File` kolonları — kolon yoksa sorguya girmez.

	Yama koşmamış bir site'ta (ör. test ortamı, eski kurulum) sorgu patlamasın:
	`th_media_caption` ve dil kolonları `v15_9_37` ile geliyor.
	"""
	adaylar = [f"th_media_{alan}" for alan in SINGLE]
	for alan in TRANSLATABLE:
		adaylar.append(f"th_media_{alan}")
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


def _asset_row(file_url: str, store: str | None = None) -> dict:
	"""Varlık varsayılanı — aynı adrese ait `File` kayıtlarından biri.

	Aynı içerik birden çok mağazaya ait olabiliyor (içerik-adresli adlandırma;
	ölçüm: 30 adres). Her mağaza kendi alt metnini yazabildiği için hangi
	kaydın okunacağı önemli: `store` verilirse o mağazanın kaydı tercih edilir,
	yoksa DOLU alt metni olan ilk kayıt — boş bir ikiz yüzünden dolu metin
	kaybolmasın diye.
	"""
	kolonlar = _asset_columns()
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

	varlik = _asset_row(url, store=store)
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
	for alan in SINGLE:
		sonuc[alan] = varlik.get(f"th_media_{alan}") or ""
	if ezme.get("source"):
		sonuc["alt_source"] = ezme["source"]
	sonuc["width"] = varlik.get("th_media_width") or 0
	sonuc["height"] = varlik.get("th_media_height") or 0
	sonuc["duration"] = varlik.get("th_media_duration") or 0
	sonuc["poster_url"] = varlik.get("th_media_poster_url") or ""
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
		})
	for satir in frappe.get_all(
		"Listing Image",
		filters={"parent": listing_name, "parenttype": "Listing"},
		fields=["name", "image", "idx"],
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
		elif anahtar in TRANSLATABLE:
			izinli[f"th_media_{anahtar}"] = deger
		elif "_" in anahtar:
			taban, _, lang = anahtar.rpartition("_")
			if taban in TRANSLATABLE and lang in CONTENT_LANGS:
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
			if value.startswith("/"):
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
	return clean


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

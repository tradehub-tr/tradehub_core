"""`alt` üretimi — kural zinciri, tetikleme ve geri doldurma (TUR-135 Dilim 2).

Karar belgesi: `docs/MEDYA-SEO-SOZLESMESI.md` §5.

NEDEN OTOMATİK
--------------
Ölçüm (18 Ağu): 3.123 public dosyanın **0'ında** alt metni var — alanlar
aylardır duruyor. Elle doldurmaya dayalı tasarım bu üründe çalışmıyor;
otomatik üretim bir kolaylık değil, VARSAYILAN olmalı (ar-ge sonucu 2).

ÖNCELİK ZİNCİRİ (§5.1) — ilk dolu olan kazanır
----------------------------------------------
    1. İnsan yazdıysa                  → dokunulmaz (alt_source ∈ human/edited)
    2. Listing'e bağlıysa              → "<başlık> — <marka>" (+ "(2. görsel)")
    3. Kategori görseliyse             → "<kategori> kategorisi"
    4. Mağaza/marka görseliyse         → "<mağaza> mağaza görseli"
    5. Hiçbiri                         → BOŞ BIRAKILIR

5. adım bilinçli: dosya adından metin türetmek (`IMG_4821` → "img 4821")
anlamsız gürültü üretir. Boş `alt` ekran okuyucuya "bu görsel dekoratif" der;
yanlış `alt` yalan söyler. **Boş, yanlıştan iyidir.**

SIRA NUMARASI NEDEN VAR
-----------------------
Aynı ürünün 5 görseli aynı metni taşırsa arama motoru bunu yinelenen içerik
sayar ve hepsini birden değersizleştirir. İlk görsel eksiz, sonrakiler
"(2. görsel)" — çıplak "- 2" değil, çünkü ekran okuyucu onu "eksi iki" diye
okuyor (bugünkü vitrin hatası, §7.1 madde 2).

NEREYE YAZILIR
--------------
Varlık varsayılanına (`media/seo.set_asset_fields`) — yani `File`. Kullanım
ezmesi bu modülün işi DEĞİL: ezme insan kararıdır (§4.3). Kural motoru yalnız
`alt_source ∈ {"", rule, ai}` olanı yeniler; `human`/`edited` bir daha asla
ezilmez (§5.2).
"""

from __future__ import annotations

import frappe

from tradehub_core.media import seo
from tradehub_core.seo.i18n import (
	CONTENT_LANGS,
	DEFAULT_LANG,
	format_image_ordinal,
	normalize_lang,
	translate_platform_term,
)

#: Kaç görselden sonra sıra numarası eklenir. İlk görsel eksiz kalır: tek
#: görselli üründe "(1. görsel)" demek hiçbir şey ifade etmiyor.
_SIRA_ESIGI: int = 1


def _listing_kolonlari(lang: str) -> list[str]:
	kolonlar = ["name", "title", "brand"]
	if lang != DEFAULT_LANG:
		kolonlar.append(f"title_{lang}")
	return kolonlar


def _listing_baglami(url: str, lang: str) -> tuple[str, int] | None:
	"""Bu adres bir ürüne bağlıysa (metin, kaçıncı görsel).

	Ana görsel her zaman 1. sıradır; galeri satırları `idx` sırasına göre
	numaralanır. İki kaynak ayrı sorgulanıyor çünkü galeri child table.

	Dönen `metin` boş olabilir (L1: hedef dilde gerçek çeviri yoksa) — bu
	"bağlam yok" ile karıştırılmaz. `None` yalnız dosya HİÇBİR Listing'e
	(ana görsel ya da galeri) bağlı değilse döner.

	AYNI DOSYA BİRDEN ÇOK LISTING'E BAĞLIYSA: GÖRÜNÜR (`storefront_visible=1`)
	olan ÖNCELİKLE ve deterministik sırayla (`modified desc`) seçilir —
	denetim (`seo_audit._missing_localized_alt_bulgusu`) da yalnız görünür
	Listing'i sayıyor; bu fonksiyon rastgele görünmez bir taslağı seçseydi
	panelden kapatılamayan bir bulgu doğardı (görünür ilanda çeviri var, ama
	`refresh_alt` görünmez taslağı okuyup `no_translation` dönerdi). Hiç
	görünür yoksa mevcut davranışa (herhangi biri, yine deterministik)
	düşülür — alt üretimi görünmez ilanlar için de çalışmaya DEVAM eder (tr
	backfill'i bugüne kadar hepsini kapsıyordu, kapsam DARALTILMADI).
	"""
	kolonlar = _listing_kolonlari(lang)
	ana = _oncelikli_listing({"primary_image": url}, kolonlar)
	if ana:
		return _listing_metni(ana, lang), 1

	satir = _oncelikli_listing_image(url)
	if not satir:
		return None
	listing = frappe.db.get_value("Listing", satir["parent"], kolonlar, as_dict=True)
	if not listing:
		return None
	# Ana görsel 1 sayıldığı için galeri 2'den başlar.
	return _listing_metni(listing, lang), int(satir.get("idx") or 1) + 1


def _oncelikli_listing(filtre: dict, kolonlar: list[str]) -> dict | None:
	"""`filtre`ye uyan Listing'lerden GÖRÜNÜR olanı, yoksa herhangi birini seç.

	`order_by="modified desc"` her iki sorguda da deterministik sıra sağlar —
	`frappe.db.get_value`'nin varsayılan sırası (`KEEP_DEFAULT_ORDERING`) iki
	koşum arasında hangi satırı döndüreceğini garanti etmez.
	"""
	gorunur_filtre = dict(filtre, storefront_visible=1)
	gorunur = frappe.db.get_value("Listing", gorunur_filtre, kolonlar, as_dict=True, order_by="modified desc")
	if gorunur:
		return gorunur
	return frappe.db.get_value("Listing", filtre, kolonlar, as_dict=True, order_by="modified desc")


def _oncelikli_listing_image(url: str) -> dict | None:
	"""Bu adrese sahip `Listing Image` satırı — ebeveyni GÖRÜNÜR olan
	öncelikli, yoksa herhangi biri (gerekçe: `_oncelikli_listing`).

	Galeri child table olduğu için `Listing`'e JOIN gerekiyor — `frappe.db.
	get_value` bunu tek çağrıda yapamıyor, parametreli `frappe.db.sql` ile
	(bu dosyanın geri kalanıyla aynı desen, ör. `_backfill_adaylari`).
	"""
	gorunur = frappe.db.sql(
		"""
		SELECT li.parent AS parent, li.idx AS idx
		FROM `tabListing Image` li
		INNER JOIN `tabListing` l ON l.name = li.parent
		WHERE li.image = %s AND l.storefront_visible = 1
		ORDER BY l.modified DESC
		LIMIT 1
		""",
		(url,),
		as_dict=True,
	)
	if gorunur:
		return gorunur[0]
	return frappe.db.get_value("Listing Image", {"image": url}, ["parent", "idx"], as_dict=True)


def _listing_metni(listing: dict, lang: str) -> str:
	"""Listing başlığı + marka.

	L1 TUZAĞI: fallback'li `resolve_content_field` KULLANILMAZ — "o dilde
	gerçek çeviri var mı" sorusu `title_{lang}` kolonunu DOĞRUDAN okuyarak
	sorulur (fallback TR'ye düşüp "çeviri var" yalanı söylerdi). tr çağrısı
	mevcut yolu (`title` base kolonu) birebir korur.
	"""
	lang = normalize_lang(lang)
	if lang == DEFAULT_LANG:
		baslik = (listing.get("title") or "").strip()
	else:
		baslik = (listing.get(f"title_{lang}") or "").strip()
	if not baslik:
		return ""
	marka = ""
	if listing.get("brand"):
		# Marka adı özel isim — çevrilmez, olduğu gibi kalır.
		marka = (frappe.db.get_value("Brand", listing["brand"], "brand_name") or "").strip()
	return f"{baslik} — {marka}" if marka else baslik


def _kategori_metni(url: str, lang: str) -> tuple[bool, str]:
	"""Kategori bağlamı: (bağlam bulundu mu, üretilen metin).

	Kategori adı SERBEST içerik (özel isim değil) — hedef dilde gerçek
	çevirisi yoksa (`category_name_{lang}` boş ya da doctype'ta hiç yok,
	örn. `Seller Category`) metin BOŞ döner; "bağlam bulundu" yine True
	kalır — `no_translation` ayrımı `refresh_alt`'ta buradan gelir.
	"""
	for doctype, alan, sonek in (
		("Product Category", "category_name", "kategorisi"),
		("Seller Category", "category_name", "kategorisi"),
	):
		if not frappe.db.table_exists(doctype):
			continue
		lang_alan = f"{alan}_{lang}"
		var_kolon = lang != DEFAULT_LANG and frappe.db.has_column(doctype, lang_alan)
		kolonlar = [alan, lang_alan] if var_kolon else [alan]
		kayit = frappe.db.get_value(doctype, {"image": url}, kolonlar, as_dict=True)
		if kayit is None:
			continue
		if lang == DEFAULT_LANG:
			ad = (kayit.get(alan) or "").strip()
		elif var_kolon:
			ad = (kayit.get(lang_alan) or "").strip()
		else:
			# Doctype'ta bu dil için sufix kolon HİÇ yok (örn. `Seller Category`
			# yalnız `category_name` taşır) — TR adını okuyup çevrili sabit ekle
			# birleştirmek L1 ihlali olurdu ("çeviri var" yalanı). no_translation.
			return True, ""
		if not ad:
			return True, ""
		return True, f"{ad} {translate_platform_term(sonek, lang)}"
	return False, ""


def _magaza_metni(url: str, lang: str) -> tuple[bool, str]:
	"""Mağaza/marka bağlamı: (bağlam bulundu mu, üretilen metin).

	Mağaza/marka adı ÖZEL İSİM — çevrilmez, olduğu gibi kalır; yalnız sabit
	ek (`translate_platform_term`) dile göre değişir. Bu yüzden bu dal
	`no_translation` ÜRETMEZ: ad zaten kaynağıyla aynı, tüm dillerde üretim
	mümkün (tasarım L1/L8 — kopyalama değil, özel isim + çevrili sabit ek).

	Kayıt eşleşse bile ad boşsa (veri eksikliği — çeviri sorunu değil)
	zincir orijinal davranışla AYNI şekilde bir sonraki adaya devam eder;
	yalnız gerçekten bir ad bulunca "bağlam bulundu" sayılır.
	"""
	# Mağaza adı `seller_name`; `company_name` yedek (bazı kayıtlarda ticari
	# unvan dolu, mağaza adı boş). Alan adı ölçülerek doğrulandı — "store_name"
	# diye bir kolon YOK.
	for alan, sonek in (("logo", "mağaza logosu"), ("banner_image", "mağaza kapak görseli")):
		kayit = frappe.db.get_value(
			"Admin Seller Profile", {alan: url}, ["seller_name", "company_name"], as_dict=True
		)
		ad = ((kayit or {}).get("seller_name") or (kayit or {}).get("company_name") or "").strip()
		if ad:
			return True, f"{ad} {translate_platform_term(sonek, lang)}"
	for alan, sonek in (("logo", "marka logosu"), ("hero_banner", "marka kapak görseli")):
		ad = (frappe.db.get_value("Brand", {alan: url}, "brand_name") or "").strip()
		if ad:
			return True, f"{ad} {translate_platform_term(sonek, lang)}"
	return False, ""


def _alt_detay(url: str, lang: str) -> tuple[str, bool]:
	"""Kural zincirini çalıştır — (üretilen metin, bağlam bulundu mu).

	Bağlam bulunduysa (Listing/kategori/mağaza eşleşti) ama metin boşsa
	(L1: o dilde gerçek çeviri yok) `refresh_alt` bunu `no_translation`
	sebebiyle ayırt eder; bağlam da yoksa `no_context`.
	"""
	baglam = _listing_baglami(url, lang)
	if baglam:
		metin, sira = baglam
		if metin:
			return (metin if sira <= _SIRA_ESIGI else f"{metin} {format_image_ordinal(sira, lang)}"), True
		return "", True

	bulundu, kategori = _kategori_metni(url, lang)
	if bulundu:
		return kategori, True

	bulundu, magaza = _magaza_metni(url, lang)
	if bulundu:
		return magaza, True

	return "", False


def generate_alt(file_url: str, lang: str = DEFAULT_LANG) -> str:
	"""Kural zincirini çalıştır — üretilen metin ya da boş dize.

	`lang` için kaynak alanın (Listing başlığı, kategori adı) o dilde
	GERÇEK çevirisi yoksa "" döner — kopyalama YASAK (L1); mağaza/marka
	dalı özel isim taşıdığı için istisna (bkz. `_magaza_metni`).

	Saf okuma: hiçbir şey yazmaz. Yazma `refresh_alt`'ın işi; ayrım
	test edilebilirlik içindir (zincir bench olmadan da denenebilsin).
	"""
	url = (file_url or "").split("?")[0]
	if not url:
		return ""
	lang = normalize_lang(lang)
	metin, _ = _alt_detay(url, lang)
	return metin


def refresh_alt(file_url: str, *, lang: str = DEFAULT_LANG, force: bool = False) -> dict:
	"""Üretilen metni varlık varsayılanına yaz — insan yazdıysa DOKUNMA.

	`lang` hedef kolonu seçer (`alt_{lang}`); `lang="tr"` (varsayılan)
	mevcut davranışı birebir korur. Kaynağın o dilde GERÇEK çevirisi yoksa
	`no_translation` sebebiyle atlanır (L1: kopyalama yasak).

	`force` yalnız yönetici aracı içindir (ör. "bu ürünün tüm alt metinlerini
	yeniden üret"); insan metnini ezmek bilinçli bir karar olmalı, kazara
	olmamalı.

	Dönüş: `{"written": bool, "alt": str, "reason": str}` — neden yazılmadığı
	çağırana açıkça söylenir, sessiz atlama yok.
	"""
	url = (file_url or "").split("?")[0]
	if not url:
		return {"written": False, "alt": "", "reason": "no_url"}
	lang = normalize_lang(lang)

	mevcut = seo.fields_for(url, lang=lang)
	# `alt_source` damgası dil-körü (L6): hangi dil hedeflenirse hedeflensin
	# aynı kapıdan geçer, insan/edited damgalı dosyanın hiçbir dil kolonuna
	# dokunulmaz.
	kaynak = mevcut.get("alt_source") or ""
	if not force and kaynak not in seo.REFRESHABLE:
		return {"written": False, "alt": mevcut.get("alt", ""), "reason": f"source:{kaynak}"}

	uretilen, baglam_bulundu = _alt_detay(url, lang)
	if not uretilen:
		# Bağlam bulunduysa (Listing/kategori/mağaza) ama o dilde gerçek
		# çeviri yoksa `no_translation`; bağlam da yoksa `no_context` — ikisi
		# de bir karardır, hata değil (§5.1 adım 5 + L1).
		sebep = "no_translation" if baglam_bulundu else "no_context"
		return {"written": False, "alt": "", "reason": sebep}
	if uretilen == mevcut.get("alt"):
		return {"written": False, "alt": uretilen, "reason": "unchanged"}

	# `alt_{lang}` yalnız o dilin GERÇEK kaynağından türetilir (Listing.title_{lang},
	# kategori adı vb.) — Türkçe metni başka dilin kolonuna kopyalamak "çeviri
	# var" yalanı söylerdi (L1). Kaynak o dilde boşsa yukarıdaki `if not uretilen`
	# dalı zaten `no_translation` ile atlar; buraya yalnız gerçek çeviri ulaşır.
	yazilan = seo.set_asset_fields(url, {f"alt_{lang}": uretilen, "alt_source": seo.SOURCE_RULE})
	if not yazilan:
		# Ürün bu adresi gösteriyor ama `File` kaydı yok (bozuk içe aktarma:
		# açıklama cümlesi dosya adı yapılmış, 4 üründe görüldü). Metin üretildi
		# ama yazılacak kayıt yok — "yazdım" demek panelde sonsuz "alt metni
		# yok" döngüsü yaratıyordu.
		return {"written": False, "alt": uretilen, "reason": "no_file"}
	return {"written": True, "alt": uretilen, "reason": "generated"}


def on_reference_change(doc, method: str | None = None) -> None:
	"""`Listing` kaydedilince bağlı görsellerin alt metnini tazele.

	Yalnız kural üretimi olanlar yenilenir (`refresh_alt` kapısı). Kanca
	hafif tutuluyor: ana görsel + galeri, en fazla `_KANCA_SINIRI` satır —
	100 görselli bir üründe kaydetme akışını uzatmamak için gerisi geri
	doldurma işine bırakılır.
	"""
	try:
		urls = [doc.get("primary_image")] if doc.get("primary_image") else []
		for satir in doc.get("images") or []:
			deger = satir.get("image") if isinstance(satir, dict) else getattr(satir, "image", None)
			if deger:
				urls.append(deger)
		for url in urls[:_KANCA_SINIRI]:
			refresh_alt(url)
	except Exception:
		# Alt metni üretimi bir yan etkidir; ürün kaydetmeyi ASLA düşürmemeli.
		frappe.log_error(title="media.seo_generate on_reference_change", message=frappe.get_traceback())


#: Kaydetme akışında en fazla kaç görsel tazelenir.
_KANCA_SINIRI: int = 12


def backfill(limit: int = 500, *, only_listing: bool = True) -> dict:
	"""Mevcut katalogu parça parça doldur — `av.backfill_pending` deseni.

	    Öncelik `Listing`'e bağlı görseller: SEO değeri orada. `only_listing=False`
	    kategori/mağaza görsellerini de kapsar.

	Tek turda `limit` dosya; kuyruğu ve DB'yi boğmamak için çağıran tekrar
	tekrar çağırır (panel düğmesi ya da zamanlanmış iş).
	"""
	limit = max(1, min(2000, int(limit or 500)))
	adaylar = _backfill_adaylari(limit, only_listing=only_listing)

	yazilan = atlanan = 0
	sebepler: dict[str, int] = {}
	for url in adaylar:
		sonuc = refresh_alt(url)
		if sonuc["written"]:
			yazilan += 1
		else:
			atlanan += 1
			sebepler[sonuc["reason"]] = sebepler.get(sonuc["reason"], 0) + 1
	frappe.db.commit()
	return {
		"scanned": len(adaylar),
		"written": yazilan,
		"skipped": atlanan,
		"reasons": sebepler,
	}


def _backfill_adaylari(limit: int, lang: str = DEFAULT_LANG, only_listing: bool = True) -> list[str]:
	"""`alt_{lang}` BOŞ olan Listing'e bağlı dosya adresleri.

	"Boş mu" sorusu `is not set` ile soruluyor: yamayla sonradan eklenen
	kolonlarda mevcut kayıtların TAMAMI NULL olur ve `in ("", None)` filtresi
	NULL satırları hiç yakalamaz — bu tuzak `av.backfill_pending`'de ölçülmüştü
	(5.120 NULL / 30 boş string).

	`lang=tr` (varsayılan) mevcut davranışı BİREBİR korur: hem `alt_tr` hem
	eski taban `alt` kolonu boş olmalı (taban kolon sufix'e taşınmamış eski
	kayıtları da yakalar). Diğer dillerde taban kolon TR'ye özgü olduğundan
	yalnız `alt_{lang}` boşluğuna bakılır.

	Kaynak çevirisi (`Listing.title_{lang}`) var mı ön-filtresi BİLİNÇLİ
	EKLENMEDİ: `refresh_alt` zaten bunu `no_translation` sebebiyle atlıyor
	(L1). Burada tekrar sorgulamak (JOIN ya da ikinci DB turu) aday listesini
	yalnız "denenecek" kümeye indirger, SONUCU değiştirmez — backfill zaten
	idempotent, çevirisiz adaylar her koşumda yine `no_translation` ile
	atlanır ve sayaç dürüstçe raporlar. Basitlik, ikinci sorgu maliyetine değmedi.
	"""
	lang = normalize_lang(lang)
	kolon = f"th_media_alt_{lang}"
	if not frappe.db.has_column("File", kolon):
		return []
	# Yalnız `tr` taban kolonu da kontrol eder — diğer diller `th_media_alt`
	# (tarihsel TR-only alan) ile hiç ilişkilendirilmez.
	taban_var = lang == DEFAULT_LANG

	if only_listing:
		taban_kosulu = "AND IFNULL(f.th_media_alt, '') = ''" if taban_var else ""
		satirlar = frappe.db.sql(
			f"""
			SELECT DISTINCT f.file_url
			FROM `tabFile` f
			WHERE f.is_folder = 0
			  AND IFNULL(f.`{kolon}`, '') = ''
			  {taban_kosulu}
			  AND (
			      EXISTS (SELECT 1 FROM `tabListing` l WHERE l.primary_image = f.file_url)
			   OR EXISTS (SELECT 1 FROM `tabListing Image` li WHERE li.image = f.file_url)
			  )
			LIMIT %s
			""",
			(limit,),
		)
	else:
		taban_kosulu = "AND IFNULL(th_media_alt, '') = ''" if taban_var else ""
		satirlar = frappe.db.sql(
			f"""
			SELECT DISTINCT file_url FROM `tabFile`
			WHERE is_folder = 0
			  AND IFNULL(`{kolon}`, '') = ''
			  {taban_kosulu}
			  AND file_url IS NOT NULL AND file_url != ''
			LIMIT %s
			""",
			(limit,),
		)
	return [r[0] for r in satirlar]


def backfill_localization(limit: int = 500, langs: tuple[str, ...] = ("en", "ar", "ru")) -> dict:
	"""Katalogu `langs` içindeki HER dil için parça parça doldur.

	Dil başına aday sorgusu (`_backfill_adaylari(lang=...)`) + `refresh_alt
	(lang=...)` döngüsü — `backfill` (tr-only) ile AYNI desen, dil ekseninde
	tekrarlanmış hâli. Senkron + limit'li (L3): kuyruk yok, metin işi.

	İdempotent: bir dil için üretilebilecek her şey yazılınca o dilin aday
	sorgusu bir daha boş döner — ikinci koşum o dilde 0 yazar.

	`by_lang` — dil başına doğruluk: "en 40 yazıldı, ar 3 yazıldı" tek toplam
	sayıdan daha dürüst bir sinyal (rapor 111, kabul kriteri 6).

	`limit` her dil için ayrı uygulanır, TOPLAM tavan değildir.

	BİLİNMEYEN DİL KORUMASI: `normalize_lang` tanımadığı bir kodu (`"de"` gibi)
	sessizce `DEFAULT_LANG`'a (tr) çevirir — bu döngüde korunmasız bırakılsaydı
	çağıran "de" istemiş sanırken koşum ikinci kez tr'yi tekrarlar, `by_lang`
	yalancı bir "de yazıldı" raporlardı. Bilinmeyenler burada AYRILIR: hiç
	sorgu/yazma yapılmaz, `unknown_lang` sebebiyle izlenir.
	"""
	limit = max(1, min(2000, int(limit or 500)))
	toplam_taranan = toplam_yazilan = toplam_atlanan = 0
	sebepler: dict[str, int] = {}
	by_lang: dict[str, dict] = {}

	for ham_lang in langs or ():
		if ham_lang not in CONTENT_LANGS:
			by_lang[ham_lang] = {
				"scanned": 0,
				"written": 0,
				"skipped": 0,
				"reasons": {"unknown_lang": 1},
			}
			sebepler["unknown_lang"] = sebepler.get("unknown_lang", 0) + 1
			continue
		lang = normalize_lang(ham_lang)
		adaylar = _backfill_adaylari(limit, lang=lang, only_listing=True)

		yazilan = atlanan = 0
		lang_sebepler: dict[str, int] = {}
		for url in adaylar:
			sonuc = refresh_alt(url, lang=lang)
			if sonuc["written"]:
				yazilan += 1
			else:
				atlanan += 1
				lang_sebepler[sonuc["reason"]] = lang_sebepler.get(sonuc["reason"], 0) + 1
				sebepler[sonuc["reason"]] = sebepler.get(sonuc["reason"], 0) + 1

		by_lang[lang] = {
			"scanned": len(adaylar),
			"written": yazilan,
			"skipped": atlanan,
			"reasons": lang_sebepler,
		}
		toplam_taranan += len(adaylar)
		toplam_yazilan += yazilan
		toplam_atlanan += atlanan

	frappe.db.commit()
	return {
		"scanned": toplam_taranan,
		"written": toplam_yazilan,
		"skipped": toplam_atlanan,
		"reasons": sebepler,
		"by_lang": by_lang,
	}


# ── Çözünürlük geri doldurma ─────────────────────────────────────────────


def backfill_dimensions(limit: int = 500) -> dict:
	"""`th_media_width/height` boş olan görsellerin gerçek ölçüsünü yaz.

	NEDEN GEREKLİ: ar-ge belgesi (§7.1 madde 4) "doğru değerler
	`th_media_width/height` alanlarında ZATEN duruyor" diyordu; ölçüm bunu
	yalanladı — 2.853 kaydın **hiçbirinde** dolu değil. Alanlar `v15_9_15`
	ile açılmış ama yalnız satıcı kütüphanesi yolundan geçen yüklemelerde
	doldurulmuş. Ölçü olmadan vitrin sabit 800×800 basmaya devam eder ve
	CLS düzeltmesi kâğıt üstünde kalır.

	Pillow yalnız BAŞLIĞI okur (`Image.open` lazy'dir, `load()` çağrılmıyor):
	54 MP'lik dosya için bile bellek maliyeti yok — bu, aynı dosyayı
	açıp işlemekle karıştırılmamalı ([[medya-cozunurluk-olcumu]]).

	Bozuk/okunamayan dosya sessizce atlanır ve sayılır: burada amaç ölçü
	toplamak, doğrulama yapmak değil (o `upload_policy`'nin işi).
	"""
	import os

	from PIL import Image

	limit = max(1, min(2000, int(limit or 500)))
	satirlar = frappe.db.sql(
		"""
		SELECT name, file_url, is_private FROM `tabFile`
		WHERE is_folder = 0
		  AND IFNULL(th_media_width, 0) = 0
		  AND file_url IS NOT NULL AND file_url != ''
		  AND LOWER(file_url) REGEXP '\\.(jpg|jpeg|png|webp|gif|bmp|tiff|tif)$'
		LIMIT %s
		""",
		(limit,),
		as_dict=True,
	)

	yazilan = okunamayan = kayip = 0
	for satir in satirlar:
		yol = (
			frappe.get_site_path(satir["file_url"].lstrip("/"))
			if satir.get("is_private")
			else frappe.get_site_path("public", satir["file_url"].lstrip("/"))
		)
		if not os.path.exists(yol):
			kayip += 1
			continue
		try:
			with Image.open(yol) as im:
				w, h = im.size
		except Exception:
			okunamayan += 1
			continue
		frappe.db.set_value(
			"File",
			satir["name"],
			{"th_media_width": w, "th_media_height": h},
			update_modified=False,
		)
		yazilan += 1
	frappe.db.commit()
	return {"scanned": len(satirlar), "written": yazilan, "unreadable": okunamayan, "missing": kayip}


def translated_alt(file_url: str, lang: str) -> str:
	"""İstenen dildeki alt metni — yoksa varsayılan dile düşer.

	`seo.fields_for` zaten bunu yapıyor; bu ince sarmalayıcı yalnız
	okunabilirlik için (`translated_alt(url, "en")`).
	"""
	if lang not in CONTENT_LANGS:
		lang = DEFAULT_LANG
	return seo.fields_for(file_url, lang=lang).get("alt", "")

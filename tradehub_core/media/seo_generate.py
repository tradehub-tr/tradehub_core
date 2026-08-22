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
from tradehub_core.seo.i18n import CONTENT_LANGS, DEFAULT_LANG

#: Kaç görselden sonra sıra numarası eklenir. İlk görsel eksiz kalır: tek
#: görselli üründe "(1. görsel)" demek hiçbir şey ifade etmiyor.
_SIRA_ESIGI: int = 1


def _listing_baglami(url: str) -> tuple[str, int] | None:
	"""Bu adres bir ürüne bağlıysa (başlık + marka, kaçıncı görsel).

	Ana görsel her zaman 1. sıradır; galeri satırları `idx` sırasına göre
	numaralanır. İki kaynak ayrı sorgulanıyor çünkü galeri child table.
	"""
	ana = frappe.db.get_value("Listing", {"primary_image": url}, ["name", "title", "brand"], as_dict=True)
	if ana:
		return _listing_metni(ana), 1

	satir = frappe.db.get_value("Listing Image", {"image": url}, ["parent", "idx"], as_dict=True)
	if not satir:
		return None
	listing = frappe.db.get_value("Listing", satir["parent"], ["name", "title", "brand"], as_dict=True)
	if not listing:
		return None
	# Ana görsel 1 sayıldığı için galeri 2'den başlar.
	return _listing_metni(listing), int(satir.get("idx") or 1) + 1


def _listing_metni(listing: dict) -> str:
	baslik = (listing.get("title") or "").strip()
	if not baslik:
		return ""
	marka = ""
	if listing.get("brand"):
		marka = (frappe.db.get_value("Brand", listing["brand"], "brand_name") or "").strip()
	return f"{baslik} — {marka}" if marka else baslik


def _kategori_metni(url: str) -> str:
	for doctype, alan, sonek in (
		("Product Category", "category_name", "kategorisi"),
		("Seller Category", "category_name", "kategorisi"),
	):
		if not frappe.db.table_exists(doctype):
			continue
		ad = frappe.db.get_value(doctype, {"image": url}, alan)
		if ad:
			return f"{ad} {sonek}"
	return ""


def _magaza_metni(url: str) -> str:
	# Mağaza adı `seller_name`; `company_name` yedek (bazı kayıtlarda ticari
	# unvan dolu, mağaza adı boş). Alan adı ölçülerek doğrulandı — "store_name"
	# diye bir kolon YOK.
	for alan, sonek in (("logo", "mağaza logosu"), ("banner_image", "mağaza kapak görseli")):
		kayit = frappe.db.get_value(
			"Admin Seller Profile", {alan: url}, ["seller_name", "company_name"], as_dict=True
		)
		ad = (kayit or {}).get("seller_name") or (kayit or {}).get("company_name")
		if ad:
			return f"{ad} {sonek}"
	for alan, sonek in (("logo", "marka logosu"), ("hero_banner", "marka kapak görseli")):
		ad = frappe.db.get_value("Brand", {alan: url}, "brand_name")
		if ad:
			return f"{ad} {sonek}"
	return ""


def generate_alt(file_url: str) -> str:
	"""Kural zincirini çalıştır — üretilen metin ya da boş dize.

	Saf okuma: hiçbir şey yazmaz. Yazma `refresh_alt`'ın işi; ayrım
	test edilebilirlik içindir (zincir bench olmadan da denenebilsin).
	"""
	url = (file_url or "").split("?")[0]
	if not url:
		return ""

	baglam = _listing_baglami(url)
	if baglam:
		metin, sira = baglam
		if metin:
			return metin if sira <= _SIRA_ESIGI else f"{metin} ({sira}. görsel)"

	kategori = _kategori_metni(url)
	if kategori:
		return kategori

	return _magaza_metni(url)


def refresh_alt(file_url: str, *, force: bool = False) -> dict:
	"""Üretilen metni varlık varsayılanına yaz — insan yazdıysa DOKUNMA.

	`force` yalnız yönetici aracı içindir (ör. "bu ürünün tüm alt metinlerini
	yeniden üret"); insan metnini ezmek bilinçli bir karar olmalı, kazara
	olmamalı.

	Dönüş: `{"written": bool, "alt": str, "reason": str}` — neden yazılmadığı
	çağırana açıkça söylenir, sessiz atlama yok.
	"""
	url = (file_url or "").split("?")[0]
	if not url:
		return {"written": False, "alt": "", "reason": "no_url"}

	mevcut = seo.fields_for(url)
	kaynak = mevcut.get("alt_source") or ""
	if not force and kaynak not in seo.REFRESHABLE:
		return {"written": False, "alt": mevcut.get("alt", ""), "reason": f"source:{kaynak}"}

	uretilen = generate_alt(url)
	if not uretilen:
		# Boş bırakmak bir karardır, hata değil (§5.1 adım 5).
		return {"written": False, "alt": "", "reason": "no_context"}
	if uretilen == mevcut.get("alt"):
		return {"written": False, "alt": uretilen, "reason": "unchanged"}

	# Yalnız varsayılan dile yazılır (§11 soru 2): çeviri `Listing.title`
	# çevirisi geldiğinde türetilir; Türkçe metni İngilizce kolona yazmak
	# "çeviri var" yalanı söylerdi.
	yazilan = seo.set_asset_fields(url, {f"alt_{DEFAULT_LANG}": uretilen, "alt_source": seo.SOURCE_RULE})
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
	adaylar = _backfill_adaylari(limit, only_listing)

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


def _backfill_adaylari(limit: int, only_listing: bool) -> list[str]:
	"""Alt metni BOŞ olan dosya adresleri.

	"Boş mu" sorusu `is not set` ile soruluyor: yamayla sonradan eklenen
	kolonlarda mevcut kayıtların TAMAMI NULL olur ve `in ("", None)` filtresi
	NULL satırları hiç yakalamaz — bu tuzak `av.backfill_pending`'de ölçülmüştü
	(5.120 NULL / 30 boş string).
	"""
	kolon = f"th_media_alt_{DEFAULT_LANG}"
	if not frappe.db.has_column("File", kolon):
		return []

	if only_listing:
		satirlar = frappe.db.sql(
			f"""
			SELECT DISTINCT f.file_url
			FROM `tabFile` f
			WHERE f.is_folder = 0
			  AND IFNULL(f.`{kolon}`, '') = ''
			  AND IFNULL(f.th_media_alt, '') = ''
			  AND (
			      EXISTS (SELECT 1 FROM `tabListing` l WHERE l.primary_image = f.file_url)
			   OR EXISTS (SELECT 1 FROM `tabListing Image` li WHERE li.image = f.file_url)
			  )
			LIMIT %s
			""",
			(limit,),
		)
	else:
		satirlar = frappe.db.sql(
			f"""
			SELECT DISTINCT file_url FROM `tabFile`
			WHERE is_folder = 0
			  AND IFNULL(`{kolon}`, '') = ''
			  AND IFNULL(th_media_alt, '') = ''
			  AND file_url IS NOT NULL AND file_url != ''
			LIMIT %s
			""",
			(limit,),
		)
	return [r[0] for r in satirlar]


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

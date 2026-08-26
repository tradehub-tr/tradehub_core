"""
JSON-LD structured data schema builder'ları (5 schema türü).

Pure fonksiyonlar Frappe runtime'a bağımlı değildir. Composer'lar
(`compose_for_*`) Frappe wrapper olarak DB'den ek veri çeker.
"""

import html
from urllib.parse import urljoin, urlsplit

SCHEMA_CONTEXT = "https://schema.org"

#: `ImageObject`'e girecek lisans alanları — Google görsel lisans rozetinin
#: okuduğu set (TUR-135 §4.4). Sözlük anahtarı `media/seo.fields_for` çıktısı,
#: değeri schema.org adı.
_IMAGE_LICENSE_MAP: dict[str, str] = {
	"creator": "creator",
	"credit_text": "creditText",
	"copyright_notice": "copyrightNotice",
	"license_url": "license",
	"acquire_license_url": "acquireLicensePage",
}


def build_image_object(seo_fields: dict, site_url: str) -> dict | str:
	"""Tek görsel için `ImageObject` — alan yoksa düz URL'ye düşer.

	NEDEN DÜZ URL'YE DÜŞÜYOR: `ImageObject` üretmek için en az bir anlamlı
	alan (alt/caption/boyut/lisans) gerekir; hiçbiri yoksa `{"@type":
	"ImageObject", "url": ...}` düz URL'den daha fazlasını söylemez ama
	çıktıyı şişirir. Ölçüm (18 Ağu): 3.123 dosyanın 0'ında alt metni var —
	yani geçiş döneminde çoğu görsel bu daldan geçecek ve JSON-LD bugünkü
	biçimini koruyacak. Alanlar doldukça çıktı kendiliğinden zenginleşir.

	Saf fonksiyon: `seo_fields` çağıran tarafından `media/seo.fields_for` ile
	getirilir (bu modül Frappe'ye bağlanmaz).
	"""
	content_url = _absolute_url(seo_fields.get("content_url") or seo_fields.get("file_url"), site_url)
	identity_url = _absolute_url(seo_fields.get("asset_url") or content_url, site_url)
	if not content_url:
		return ""

	nesne: dict = {"@type": "ImageObject", "url": identity_url, "contentUrl": content_url}
	if seo_fields.get("title"):
		nesne["name"] = seo_fields["title"]
	# `caption` sayfada görünen metin, `alt` erişilebilirlik metni. Google
	# ikisini de okuyor; caption yoksa alt caption olarak verilir — uydurma
	# değil, aynı görselin tarifi.
	altyazi = seo_fields.get("caption") or seo_fields.get("alt")
	if altyazi:
		nesne["caption"] = altyazi
	if seo_fields.get("description"):
		nesne["description"] = seo_fields["description"]
	if seo_fields.get("width"):
		nesne["width"] = seo_fields["width"]
	if seo_fields.get("height"):
		nesne["height"] = seo_fields["height"]
	if seo_fields.get("canonical_url"):
		nesne["mainEntityOfPage"] = _absolute_url(seo_fields["canonical_url"], site_url)
	for kaynak, hedef in (
		("encoding_format", "encodingFormat"),
		("date_created", "dateCreated"),
		("date_published", "datePublished"),
	):
		if seo_fields.get(kaynak):
			nesne[hedef] = seo_fields[kaynak]

	for kaynak, hedef in _IMAGE_LICENSE_MAP.items():
		deger = seo_fields.get(kaynak)
		if not deger:
			continue
		if hedef in ("license", "acquireLicensePage"):
			nesne[hedef] = _absolute_url(deger, site_url)
		elif hedef == "creator":
			tur = seo_fields.get("creator_type") or ""
			yaratici = {"name": deger}
			if tur in ("Person", "Organization"):
				yaratici["@type"] = tur
			nesne[hedef] = yaratici
		else:
			nesne[hedef] = deger

	# Yalnız url/contentUrl kaldıysa nesne bir şey söylemiyor demektir.
	if set(nesne) <= {"@type", "url", "contentUrl"}:
		return content_url
	return nesne


def _iso8601_sure(saniye: float) -> str:
	"""65.0 → "PT1M5S"; 0 → "" (basılmaz)."""
	toplam = int(saniye or 0)
	if toplam <= 0:
		return ""
	dk, sn = divmod(toplam, 60)
	sa, dk = divmod(dk, 60)
	parca = "PT"
	if sa:
		parca += f"{sa}H"
	if dk:
		parca += f"{dk}M"
	if sn or parca == "PT":
		parca += f"{sn}S"
	return parca


def build_video_object(
	seo_fields: dict,
	site_url: str,
	*,
	content_url: str = "",
	embed_url: str = "",
	upload_date: str = "",
) -> dict | None:
	"""Tek video için `VideoObject` — poster yoksa None.

	Google `thumbnailUrl` + `name` + `uploadDate`'i zorunlu sayar; geçersiz
	yapısal veri hiç üretmemekten kötüdür (spec netleştirmesi). Poster'ı
	olmayan video JSON-LD'ye ve video sitemap'e GİRMEZ, denetim uyarır.

	URL mutlaklaştırması dosyadaki `_absolute_url` ile paylaşılır — `embedUrl`
	istisna: gömülü oynatıcı linki (ör. YouTube embed) zaten mutlak gelir,
	site_url'e göre yeniden yazılmaz.
	"""
	poster = str(seo_fields.get("poster_url") or "").strip()
	if not poster or not (content_url or embed_url):
		return None

	ad = str(seo_fields.get("title") or seo_fields.get("alt") or "").strip()
	if not ad:
		return None
	obj: dict = {"@type": "VideoObject", "name": ad, "thumbnailUrl": _absolute_url(poster, site_url)}
	aciklama = str(seo_fields.get("caption") or seo_fields.get("description") or "").strip()
	if aciklama:
		obj["description"] = aciklama
	if content_url:
		obj["contentUrl"] = _absolute_url(content_url, site_url)
	if embed_url:
		obj["embedUrl"] = embed_url
	sure = _iso8601_sure(float(seo_fields.get("duration") or 0))
	if sure:
		obj["duration"] = sure
	if upload_date:
		obj["uploadDate"] = str(upload_date)[:10]
	transcript = str(seo_fields.get("transcript") or "").strip()
	if transcript:
		obj["transcript"] = transcript
	biter = str(seo_fields.get("rights_expires_on") or "").strip()
	if biter:
		obj["expires"] = biter
	return obj


def build_image_list(seo_fields_list: list[dict], site_url: str) -> list:
	"""Sıralı görsel listesi — her biri `ImageObject` ya da düz URL."""
	out = []
	for alanlar in seo_fields_list or []:
		deger = build_image_object(alanlar, site_url)
		if deger:
			out.append(deger)
	return out


def _absolute_url(value: str | None, site_url: str) -> str:
	"""Relative storefront asset/page URL'lerini mutlak URL'ye çevir."""
	if not value:
		return ""
	if str(value).startswith(("http://", "https://")):
		return str(value)
	parts = urlsplit(site_url)
	origin = f"{parts.scheme}://{parts.netloc}/"
	return urljoin(origin, str(value).lstrip("/"))


def _effective_listing_price(listing: dict) -> float | str:
	"""Kart/detay görünümündeki satış fiyatını şemaya yansıt."""
	price = listing.get("selling_price")
	if price in (None, ""):
		price = listing.get("base_price", 0)
	try:
		numeric_price = float(price or 0)
		discount = float(listing.get("discount_percentage") or 0)
		if discount > 0:
			numeric_price *= 1 - discount / 100
		return round(numeric_price, 2)
	except (TypeError, ValueError):
		return price or 0
	return price or 0


def _listing_availability(listing: dict) -> str:
	status = str(listing.get("status") or "")
	is_out_of_stock = status == "Out of Stock"
	if listing.get("track_inventory"):
		try:
			is_out_of_stock = is_out_of_stock or float(listing.get("available_qty") or 0) <= 0
		except (TypeError, ValueError):
			pass
	state = "OutOfStock" if is_out_of_stock else "InStock"
	return f"{SCHEMA_CONTEXT}/{state}"


def build_product_schema(
	*,
	listing: dict,
	site_url: str,
	brand: dict | None,
	category_name: str | None,
	aggregate_rating: dict | None,
	reviews: list[dict] | None,
	currency: str = "TRY",
	lang: str = "tr",
	media_videos: list | None = None,
) -> dict:
	"""Product schema üret. Pure: I/O yok."""
	slug = listing.get("slug", "")
	url = f"{site_url.rstrip('/')}/urun/{slug}"

	# Görseller: çağıran `media_images` (ImageObject listesi) verdiyse o
	# kullanılır — alt metni, altyazı, boyut ve lisans oradan gelir (TUR-135
	# §6). Vermediyse eski davranış: `primary_image`'ın düz URL'si. Geçiş
	# döneminde ikisi de geçerli; hiçbir çağıran kırılmıyor.
	images = listing.get("media_images")
	if not images:
		primary_image = listing.get("primary_image")
		images = [_absolute_url(primary_image, site_url)] if primary_image else []

	schema = {
		"@context": SCHEMA_CONTEXT,
		"@type": "Product",
		"@id": f"{url}#product",
		"name": listing.get("title", ""),
		"image": images,
		"description": listing.get("description", "") or "",
		"sku": listing.get("name", ""),
		"inLanguage": lang,
		"offers": {
			"@type": "Offer",
			"@id": f"{url}#offer",
			"url": url,
			"priceCurrency": listing.get("currency") or currency,
			"price": str(_effective_listing_price(listing)),
			"availability": _listing_availability(listing),
		},
	}

	if brand and brand.get("name"):
		brand_slug = brand.get("slug") or ""
		schema["brand"] = {
			"@type": "Brand",
			"name": brand["name"],
			"url": f"{site_url.rstrip('/')}/marka/{brand_slug}",
		}

	if category_name:
		schema["category"] = category_name

	if aggregate_rating and aggregate_rating.get("count"):
		schema["aggregateRating"] = {
			"@type": "AggregateRating",
			"ratingValue": str(aggregate_rating["value"]),
			"reviewCount": str(aggregate_rating["count"]),
		}

	if reviews:
		schema["review"] = reviews

	# Video (Görev 6): çağıran (compose_for_listing) `VideoObject` listesini
	# önceden üretip verir — burası pure kalır, DB/Frappe'ye dokunmaz.
	if media_videos:
		schema["video"] = media_videos

	return schema


def build_breadcrumb_schema(*, items: list[dict], schema_id: str | None = None) -> dict:
	"""BreadcrumbList schema üret. items: [{"name", "url"}, ...]"""
	schema = {
		"@context": SCHEMA_CONTEXT,
		"@type": "BreadcrumbList",
		"itemListElement": [
			{
				"@type": "ListItem",
				"position": idx + 1,
				"name": item.get("name", ""),
				"item": item.get("url", ""),
			}
			for idx, item in enumerate(items)
		],
	}
	if schema_id:
		schema["@id"] = schema_id
	return schema


def build_organization_schema(
	*,
	site_name: str,
	site_url: str,
	logo_url: str | None,
	same_as: list[str] | None,
) -> dict:
	"""Organization schema üret."""
	normalized_url = site_url.rstrip("/")
	path = urlsplit(normalized_url).path.rstrip("/")
	schema_id = f"{normalized_url}/#organization" if not path else f"{normalized_url}#organization"
	schema = {
		"@context": SCHEMA_CONTEXT,
		"@type": "Organization",
		"@id": schema_id,
		"name": site_name,
		"url": normalized_url,
	}
	if logo_url:
		schema["logo"] = _absolute_url(logo_url, site_url)
	if same_as:
		schema["sameAs"] = list(same_as)
	return schema


def build_website_schema(*, site_url: str, search_url_template: str | None = None) -> dict:
	"""WebSite schema üret (SearchAction içerir, sitelinks searchbox için)."""
	site_url = site_url.rstrip("/")
	template = search_url_template or f"{site_url}/?q={{search_term_string}}"
	return {
		"@context": SCHEMA_CONTEXT,
		"@type": "WebSite",
		"@id": f"{site_url}/#website",
		"url": site_url,
		"potentialAction": {
			"@type": "SearchAction",
			"target": template,
			"query-input": "required name=search_term_string",
		},
	}


def build_item_list_schema(*, items: list[dict], canonical_url: str, site_url: str) -> dict:
	"""Yalnızca API'nin döndürdüğü görünür sayfa ürünlerinden ItemList üret."""
	canonical_url = canonical_url.rstrip("/")
	elements = []
	for position, item in enumerate(items, start=1):
		href = item.get("href") or f"/urun/{item.get('slug', '')}"
		product_url = _absolute_url(href, site_url).rstrip("/")
		product = {
			"@type": "Product",
			"@id": f"{product_url}#product",
			"name": item.get("name") or item.get("title") or "",
			"url": product_url,
		}
		image = item.get("imageSrc") or item.get("primary_image")
		if image:
			product["image"] = _absolute_url(image, site_url)
		elements.append(
			{
				"@type": "ListItem",
				"position": position,
				"item": product,
			}
		)
	return {
		"@context": SCHEMA_CONTEXT,
		"@type": "ItemList",
		"@id": f"{canonical_url}#itemlist",
		"url": canonical_url,
		"numberOfItems": len(elements),
		"itemListElement": elements,
	}


def build_faq_schema(*, questions: list[dict]) -> dict | None:
	"""FAQ schema üret. questions: [{"question", "answer"}, ...]

	Empty list → None (atlanır)."""
	if not questions:
		return None

	return {
		"@context": SCHEMA_CONTEXT,
		"@type": "FAQPage",
		"mainEntity": [
			{
				"@type": "Question",
				"name": html.escape(q.get("question", "")),
				"acceptedAnswer": {
					"@type": "Answer",
					"text": html.escape(q.get("answer", "")),
				},
			}
			for q in questions
		],
	}


# ── Composer'lar (pure) ────────────────────────────────────────────────────


def _same_as_from_defaults(defaults: dict) -> list[str]:
	"""defaults dict'inden sosyal medya URL'leri toplar."""
	result = []
	for key in ("twitter", "facebook", "linkedin", "instagram", "youtube"):
		val = defaults.get(key)
		if val and val.startswith("http"):
			result.append(val)
	return result


def _pure_compose_for_listing(*, ctx: dict, defaults: dict, site_url: str) -> list[dict]:
	"""Listing için tüm schema setini üret. Pure: ctx tüm input verisi."""
	listing = ctx["listing"]
	schemas: list[dict] = []

	# 1. Product
	schemas.append(
		build_product_schema(
			listing=listing,
			site_url=site_url,
			brand=ctx.get("brand"),
			category_name=ctx.get("category_name"),
			aggregate_rating=ctx.get("aggregate_rating"),
			reviews=ctx.get("reviews"),
			media_videos=listing.get("media_videos"),
		)
	)

	# 2. BreadcrumbList: Home → Category → Listing
	items = [{"name": "Anasayfa", "url": f"{site_url.rstrip('/')}/"}]
	if ctx.get("category_name") and ctx.get("category_url"):
		items.append({"name": ctx["category_name"], "url": ctx["category_url"]})
	items.append(
		{
			"name": listing.get("title", ""),
			"url": f"{site_url.rstrip('/')}/urun/{listing.get('slug', '')}",
		}
	)
	listing_url = f"{site_url.rstrip('/')}/urun/{listing.get('slug', '')}"
	schemas.append(build_breadcrumb_schema(items=items, schema_id=f"{listing_url}#breadcrumb"))

	# 3. Organization
	schemas.append(
		build_organization_schema(
			site_name=defaults.get("site_name", ""),
			site_url=site_url,
			logo_url=defaults.get("logo"),
			same_as=defaults.get("same_as") or _same_as_from_defaults(defaults),
		)
	)

	# 4. FAQ (varsa)
	faq = build_faq_schema(questions=ctx.get("questions", []))
	if faq:
		schemas.append(faq)

	return schemas


def _pure_compose_for_category(*, category: dict, defaults: dict, site_url: str) -> list[dict]:
	"""Product Category için: Breadcrumb + Organization."""
	slug = category.get("url_slug", "")
	items = [
		{"name": "Anasayfa", "url": f"{site_url.rstrip('/')}/"},
		{"name": "Kategoriler", "url": f"{site_url.rstrip('/')}/kategoriler"},
		{"name": category.get("category_name", ""), "url": f"{site_url.rstrip('/')}/kategori/{slug}"},
	]
	return [
		build_breadcrumb_schema(
			items=items,
			schema_id=f"{site_url.rstrip('/')}/kategori/{slug}#breadcrumb",
		),
		build_organization_schema(
			site_name=defaults.get("site_name", ""),
			site_url=site_url,
			logo_url=defaults.get("logo"),
			same_as=_same_as_from_defaults(defaults),
		),
	]


def _pure_compose_for_brand(*, brand: dict, defaults: dict, site_url: str) -> list[dict]:
	"""Brand için: Organization (Brand-as-Org) + Breadcrumb."""
	slug = brand.get("slug", "")
	brand_url = f"{site_url.rstrip('/')}/marka/{slug}"

	org = build_organization_schema(
		site_name=brand.get("brand_name", ""),
		site_url=brand_url,
		logo_url=brand.get("logo"),
		same_as=None,
	)

	# Brand listesi sayfası yok — breadcrumb sadeleştirildi (eskiden /markalar'a
	# atıf vardı, ama o URL aslında Üreticiler sayfasına gidiyordu; kavramsal hata).
	items = [
		{"name": "Anasayfa", "url": f"{site_url.rstrip('/')}/"},
		{"name": brand.get("brand_name", ""), "url": brand_url},
	]
	breadcrumb = build_breadcrumb_schema(items=items, schema_id=f"{brand_url}#breadcrumb")

	return [org, breadcrumb]


def _pure_compose_for_seller(*, seller: dict, defaults: dict, site_url: str) -> list[dict]:
	"""Admin Seller Profile için: Organization + Breadcrumb."""
	slug = seller.get("slug", "")
	seller_url = f"{site_url.rstrip('/')}/magaza/{slug}"

	org = build_organization_schema(
		site_name=seller.get("seller_name", ""),
		site_url=seller_url,
		logo_url=seller.get("logo"),
		same_as=None,
	)

	items = [
		{"name": "Anasayfa", "url": f"{site_url.rstrip('/')}/"},
		{"name": "Üreticiler", "url": f"{site_url.rstrip('/')}/ureticiler"},
		{"name": seller.get("seller_name", ""), "url": seller_url},
	]
	breadcrumb = build_breadcrumb_schema(items=items, schema_id=f"{seller_url}#breadcrumb")

	return [org, breadcrumb]


# ── Frappe-aware composer wrapper'lar ─────────────────────────────────────


def _fetch_answered_questions_for(listing_name: str) -> list[dict]:
	"""status='Answered' Listing Question'lardan ilk 10'unu çek."""
	import frappe

	try:
		rows = frappe.get_all(
			"Listing Question",
			filters={"listing": listing_name, "status": "Answered"},
			fields=["question", "answer"],
			limit_page_length=10,
			order_by="creation asc",
		)
		return [
			{"question": r.get("question") or "", "answer": r.get("answer") or ""}
			for r in rows
			if r.get("answer")
		]
	except Exception:
		frappe.log_error("Listing Question fetch failed", "schema_builder")
		return []


def _listing_image_objects(listing: dict, site_url: str) -> list:
	"""Ürünün görselleri → `ImageObject` listesi (indexlenmeyenler ELENİR).

	Alt metni ve lisans `media/seo.fields_for` üzerinden okunuyor — kullanım
	bağlamıyla, yani ürün sayfasına yazılmış ezme varsa o (TUR-135 §4.3).
	Doğrudan `th_media_alt` okunmuyor: metadata evi taşındığı gün burası
	değişmesin (ADR-0023).

	Çöpteki/karantinadaki/hakkı dolmuş görsel yapısal veriye GİRMEZ
	(`seo_index.decide`): Google'a var olmayan ya da kaldırılmış bir kaynağı
	göstermek, kırık zengin sonuç üretir.
	"""
	import frappe

	try:
		from tradehub_core.media import seo as media_seo
		from tradehub_core.media import seo_index

		ad = listing.get("name") or ""
		lang = listing.get("content_default_lang") or "tr"
		kaynaklar = media_seo.listing_usage_contexts(ad) if ad else []

		out = []
		gorulen: set[str] = set()
		for baglam in kaynaklar:
			url = baglam["file_url"]
			if url in gorulen:
				continue
			gorulen.add(url)
			if not seo_index.decide(url, check_usage=False)["indexable"]:
				continue
			alanlar = media_seo.fields_for(
				url,
				ref_doctype=baglam["ref_doctype"],
				ref_name=baglam["ref_name"],
				ref_field=baglam["ref_field"],
				lang=lang,
			)
			from tradehub_core.media import seo_urls

			kimlik = seo_urls.resolve(
				url,
				ref_doctype=baglam["ref_doctype"],
				ref_name=baglam["ref_name"],
				context_doctype=baglam.get("context_doctype", ""),
				context_name=baglam.get("context_name", ""),
				site_url=site_url,
			)
			alanlar.update(
				{
					"asset_url": kimlik.get("stable_url", ""),
					"content_url": kimlik.get("delivery_url", ""),
					"encoding_format": kimlik.get("encoding_format", ""),
					"date_created": kimlik.get("date_created", ""),
					"date_published": kimlik.get("date_published", ""),
					"canonical_url": kimlik.get("canonical_url", ""),
				}
			)
			nesne = build_image_object(alanlar, site_url)
			if nesne:
				out.append(nesne)
		return out
	except Exception:
		# Yapısal veri üretimi bir sayfa isteğinin içinde koşuyor; medya
		# tarafındaki bir hata ürün sayfasını DÜŞÜRMEMELİ. Eski davranışa
		# (düz `primary_image`) düşülür.
		frappe.log_error("listing image objects failed", "schema_builder")
		return []


def _listing_video_objects(listing: dict, site_url: str) -> list:
	"""İlanın tanıtım videosu (`Listing.video_url`) → `VideoObject` listesi (0/1 eleman).

	Kapsam site haritası kardeşiyle (`sitemap_generator._video_entries_for_listing`)
	AYNI: yalnız tek video alanı işlenir, galerideki video dosyaları burada
	tekrar İŞLENMEZ — onlar `imageMeta` (Görev 6, `api.listing._gorsel_kunyeleri`)
	üzerinden zaten poster/süre/altyazı taşıyor. Poster'ı ya da adı olmayan video
	`build_video_object` sözleşmesiyle HİÇ girmez (Google geçersiz yapısal veri
	istemiyor). Yerel dosya (`/files/...`) `contentUrl`, harici oynatıcı (YouTube/
	Vimeo) `embedUrl` olarak basılır.
	"""
	import frappe

	video_url = str(listing.get("video_url") or "").split("?")[0].strip()
	if not video_url:
		return []
	try:
		from tradehub_core.media import seo as media_seo

		listing_name = listing.get("name") or ""
		lang = listing.get("content_default_lang") or "tr"
		alanlar = media_seo.fields_for(
			video_url,
			ref_doctype="Listing",
			ref_name=listing_name,
			ref_field="video_url",
			lang=lang,
		)
		if not alanlar.get("title"):
			alanlar = {**alanlar, "title": listing.get("title") or ""}
		yerel = video_url.startswith("/files/")
		nesne = build_video_object(
			alanlar,
			site_url,
			content_url=video_url if yerel else "",
			embed_url="" if yerel else video_url,
			upload_date=str(listing.get("creation") or ""),
		)
		return [nesne] if nesne else []
	except Exception:
		# Şema üretimi sayfa isteği içinde koşuyor: video tarafındaki bir hata
		# ürün sayfasını DÜŞÜRMEMELİ — image kardeşiyle aynı gerekçe.
		frappe.log_error("listing video objects failed", "schema_builder")
		return []


def _get_listing_extra_context(listing_name: str) -> dict:
	"""Listing için brand + category + rating + reviews + questions topla."""
	import frappe

	ctx = {
		"brand": None,
		"category_name": None,
		"category_url": None,
		"aggregate_rating": None,
		"reviews": None,
		"questions": [],
	}

	listing = frappe.db.get_value(
		"Listing",
		listing_name,
		[
			"brand",
			"brand_name",
			"product_category",
			"product_category_name",
			"average_rating",
			"review_count",
		],
		as_dict=True,
	)
	if not listing:
		return ctx

	# Brand
	if listing.get("brand"):
		brand_slug = frappe.db.get_value("Brand", listing["brand"], "slug")
		ctx["brand"] = {
			"name": listing.get("brand_name") or "",
			"slug": brand_slug or "",
		}

	# Category
	if listing.get("product_category"):
		from tradehub_core.seo.site_url import storefront_url

		category = frappe.db.get_value(
			"Product Category",
			listing["product_category"],
			["category_name", "url_slug"],
			as_dict=True,
		)
		category = category or {}
		ctx["category_name"] = listing.get("product_category_name") or category.get("category_name") or ""
		site_url = storefront_url()
		category_slug = category.get("url_slug")
		if category_slug:
			ctx["category_url"] = f"{site_url}/kategori/{category_slug}"

	# AggregateRating
	if listing.get("review_count"):
		ctx["aggregate_rating"] = {
			"value": listing.get("average_rating") or 0,
			"count": listing["review_count"],
		}

	# Reviews (mevcut endpoint'ten alınır)
	try:
		from tradehub_core.api.seo import get_review_schema_jsonld

		review_schema = get_review_schema_jsonld(listing=listing_name)
		if isinstance(review_schema, dict) and review_schema.get("review"):
			ctx["reviews"] = review_schema["review"]
	except Exception:
		frappe.log_error("Review schema fetch failed for listing context", "schema_builder")
		pass

	# FAQ (Listing Question)
	ctx["questions"] = _fetch_answered_questions_for(listing_name)

	return ctx


def _frappe_defaults() -> dict:
	"""Website Settings SEO defaults + sosyal medya URL'leri.

	Sosyal profiller (Organization `sameAs` — marka sinyali, bilgi paneli
	hedefi) panelden yönetilir: Website Settings'e `seo_social_*` custom
	field'ları eklendiğinde otomatik toplanır; alan yoksa/boşsa şemaya girmez.
	"""
	import frappe

	ws = frappe.get_single("Website Settings")
	twitter_handle = (ws.get("seo_twitter_handle") or "").lstrip("@")
	defaults = {
		"site_name": ws.get("seo_site_name") or "iStoc",
		"logo": ws.get("seo_og_image") or "",
		"twitter": (f"https://twitter.com/{twitter_handle}" if twitter_handle else None),
	}
	for social in ("facebook", "linkedin", "instagram", "youtube"):
		defaults[social] = ws.get(f"seo_social_{social}") or None
	return defaults


def compose_for_home(defaults: dict, site_url: str) -> list[dict]:
	"""Ana sayfa ('/') için Organization + WebSite şemaları.

	Organization: marka bilgi paneli sinyali (sameAs sosyal profiller).
	WebSite: sitelinks searchbox (SearchAction → /urunler?q=).
	"""
	# Caller (meta_builder) Website Settings defaults'ını tek kez yükleyip verir.
	# Böylece aynı üretici hem bot SSR'da hem public client payload'ında kullanılır
	# ve pure testlerde Frappe runtime gerektirmez.
	merged = {k: v for k, v in (defaults or {}).items() if v}
	site_url = site_url.rstrip("/")
	org = build_organization_schema(
		site_name=merged.get("site_name") or "istoc",
		site_url=site_url,
		logo_url=merged.get("logo") or merged.get("og_image") or None,
		same_as=_same_as_from_defaults(merged),
	)
	website = build_website_schema(
		site_url=site_url,
		search_url_template=f"{site_url}/urunler?q={{search_term_string}}",
	)
	return [org, website]


def compose_for_listing(listing: dict, defaults: dict, site_url: str) -> list[dict]:
	"""Frappe wrapper: Listing için tüm schema setini üret."""
	listing = {
		**listing,
		"media_images": _listing_image_objects(listing, site_url),
		"media_videos": _listing_video_objects(listing, site_url),
	}
	ctx = {"listing": listing}
	ctx.update(_get_listing_extra_context(listing.get("name", "")))
	merged_defaults = {**defaults, **_frappe_defaults()}
	return _pure_compose_for_listing(ctx=ctx, defaults=merged_defaults, site_url=site_url)


def compose_for_category(category: dict, defaults: dict, site_url: str) -> list[dict]:
	merged_defaults = {**defaults, **_frappe_defaults()}
	return _pure_compose_for_category(category=category, defaults=merged_defaults, site_url=site_url)


def compose_for_brand(brand: dict, defaults: dict, site_url: str) -> list[dict]:
	merged_defaults = {**defaults, **_frappe_defaults()}
	return _pure_compose_for_brand(brand=brand, defaults=merged_defaults, site_url=site_url)


def compose_for_seller(seller: dict, defaults: dict, site_url: str) -> list[dict]:
	merged_defaults = {**defaults, **_frappe_defaults()}
	return _pure_compose_for_seller(seller=seller, defaults=merged_defaults, site_url=site_url)

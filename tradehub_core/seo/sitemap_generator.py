"""
XML sitemap üretici (index + alt-sitemap'ler + pagination).

Pure builder fonksiyonları Frappe runtime'a bağımlı değildir; DB sorgu
yapan `build_for_type()` ve `build_index()` Frappe wrapper'lar.
"""

from collections.abc import Iterable
from xml.sax.saxutils import escape

from tradehub_core.seo.i18n import build_hreflang_links

MAX_URLS_PER_SITEMAP = 50_000
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
XHTML_NS = "http://www.w3.org/1999/xhtml"
#: Görsel site haritası (TUR-135 §6). Namespace yalnız görsel TAŞIYAN
#: çıktıya eklenir: her urlset'e eklemek, hiç `<image:image>` içermeyen
#: dosyalara ölü bildirim koymak olurdu.
IMAGE_NS = "http://www.google.com/schemas/sitemap-image/1.1"
#: Video site haritası (Task 5). Aynı gerekçe: namespace yalnız video
#: TAŞIYAN çıktıya eklenir.
VIDEO_NS = "http://www.google.com/schemas/sitemap-video/1.1"

DOCTYPE_CONFIG = {
	"Listing": {
		"url_prefix": "/urun",
		"priority": "0.9",
		"changefreq": "weekly",
		"slug_field": "slug",
		"sub_sitemap_name": "products",
	},
	"Product Category": {
		"url_prefix": "/kategori",
		"priority": "0.8",
		"changefreq": "monthly",
		"slug_field": "url_slug",
		"sub_sitemap_name": "categories",
	},
	"Brand": {
		"url_prefix": "/marka",
		"priority": "0.7",
		"changefreq": "monthly",
		"slug_field": "slug",
		"sub_sitemap_name": "brands",
	},
	"Admin Seller Profile": {
		"url_prefix": "/magaza",
		"priority": "0.6",
		"changefreq": "weekly",
		# BUG FIX (BE-MAP): mağaza URL'leri seller_code taşır (/magaza/<code>,
		# get_seller de seller_code ile arar) — "slug" alanı yok/boş kalıyordu.
		"slug_field": "seller_code",
		"sub_sitemap_name": "sellers",
	},
	"Static Page SEO": {
		"url_prefix": "",  # page_path zaten / ile başlar
		"priority": "0.5",
		"changefreq": "monthly",
		"slug_field": "page_path",
		"sub_sitemap_name": "static-pages",
	},
}


def urlentry(*, loc: str, lastmod: str, priority: str = "0.5", changefreq: str = "monthly") -> dict:
	"""URL entry dict üretir (sitemap_generator için canonical format)."""
	return {
		"loc": loc,
		"lastmod": lastmod,
		"priority": priority,
		"changefreq": changefreq,
	}


def build_urlset_xml(urls: Iterable[dict], include_hreflang: bool = True) -> str:
	"""URL listesinden <urlset> XML üret. Pure: I/O yok.

	`include_hreflang=True` ise her URL'ye xhtml:link hreflang annotation
	eklenir (Faz 7). URL entry'sinde `hreflang_links` varsa onu kullanır,
	yoksa otomatik üretilmez (entry zaten TR URL'i olduğu için)."""
	urls = list(urls)
	# Görsel namespace'i yalnız gerçekten görsel varsa bildirilir.
	gorselli = any(u.get("images") for u in urls)
	videolu = any(u.get("videos") for u in urls)

	xmlns = f'xmlns="{SITEMAP_NS}"'
	if include_hreflang:
		xmlns += f' xmlns:xhtml="{XHTML_NS}"'
	if gorselli:
		xmlns += f' xmlns:image="{IMAGE_NS}"'
	if videolu:
		xmlns += f' xmlns:video="{VIDEO_NS}"'

	lines = [
		'<?xml version="1.0" encoding="UTF-8"?>',
		f"<urlset {xmlns}>",
	]
	for u in urls:
		loc = escape(u.get("loc", ""))
		lastmod = escape(u.get("lastmod", ""))
		changefreq = escape(u.get("changefreq", "monthly"))
		priority = escape(u.get("priority", "0.5"))
		lines.append("  <url>")
		lines.append(f"    <loc>{loc}</loc>")
		# Hreflang annotations (xhtml:link)
		hreflang_links = u.get("hreflang_links") or []
		for alt in hreflang_links:
			hreflang_attr = escape(alt.get("hreflang", ""))
			href_attr = escape(alt.get("href", ""))
			lines.append(f'    <xhtml:link rel="alternate" hreflang="{hreflang_attr}" href="{href_attr}"/>')
		if lastmod:
			lines.append(f"    <lastmod>{lastmod}</lastmod>")
		lines.append(f"    <changefreq>{changefreq}</changefreq>")
		lines.append(f"    <priority>{priority}</priority>")
		# Görseller (TUR-135 §6): sayfa başına <image:image>. `loc` zorunlu,
		# `caption` ve `title` opsiyonel — boş etiket yazmak yerine atlanır.
		for gorsel in u.get("images") or []:
			img_loc = escape(gorsel.get("loc", ""))
			if not img_loc:
				continue
			lines.append("    <image:image>")
			lines.append(f"      <image:loc>{img_loc}</image:loc>")
			if gorsel.get("caption"):
				lines.append(f"      <image:caption>{escape(gorsel['caption'])}</image:caption>")
			if gorsel.get("title"):
				lines.append(f"      <image:title>{escape(gorsel['title'])}</image:title>")
			if gorsel.get("license"):
				lines.append(f"      <image:license>{escape(gorsel['license'])}</image:license>")
			lines.append("    </image:image>")
		# Videolar (Task 5): sayfa başına <video:video>. `thumbnail_loc` ve
		# `title` zorunlu — üretici (`_video_entries_for_listing`) posteri
		# olmayan videoyu zaten eleyip buraya göndermiyor.
		for video in u.get("videos") or []:
			lines.append("    <video:video>")
			lines.append(f"      <video:thumbnail_loc>{escape(video['thumbnail_loc'])}</video:thumbnail_loc>")
			lines.append(f"      <video:title>{escape(video['title'])}</video:title>")
			lines.append(
				f"      <video:description>{escape(video.get('description') or video['title'])}</video:description>"
			)
			if video.get("content_loc"):
				lines.append(f"      <video:content_loc>{escape(video['content_loc'])}</video:content_loc>")
			if video.get("player_loc"):
				lines.append(f"      <video:player_loc>{escape(video['player_loc'])}</video:player_loc>")
			if video.get("duration"):
				lines.append(f"      <video:duration>{int(video['duration'])}</video:duration>")
			if video.get("publication_date"):
				lines.append(
					f"      <video:publication_date>{escape(video['publication_date'])}</video:publication_date>"
				)
			if video.get("expiration_date"):
				lines.append(
					f"      <video:expiration_date>{escape(video['expiration_date'])}</video:expiration_date>"
				)
			lines.append("    </video:video>")
		lines.append("  </url>")
	lines.append("</urlset>")
	return "\n".join(lines)


def build_index_xml(sitemaps: Iterable[dict]) -> str:
	"""Sub-sitemap listesinden <sitemapindex> XML üret. Pure."""
	lines = [
		'<?xml version="1.0" encoding="UTF-8"?>',
		f'<sitemapindex xmlns="{SITEMAP_NS}">',
	]
	for sm in sitemaps:
		loc = escape(sm.get("loc", ""))
		lastmod = escape(sm.get("lastmod", ""))
		lines.append("  <sitemap>")
		lines.append(f"    <loc>{loc}</loc>")
		if lastmod:
			lines.append(f"    <lastmod>{lastmod}</lastmod>")
		lines.append("  </sitemap>")
	lines.append("</sitemapindex>")
	return "\n".join(lines)


def chunk_urls_for_pagination(urls: list[dict]) -> list[list[dict]]:
	"""URL listesini MAX_URLS_PER_SITEMAP boyutunda parçalara böl."""
	chunks = []
	for i in range(0, len(urls), MAX_URLS_PER_SITEMAP):
		chunks.append(urls[i : i + MAX_URLS_PER_SITEMAP])
	return chunks or [[]]


def sitemap_file_name(sub_name: str, part: int, total_parts: int) -> str:
	"""Parça dosya adı: tek parça → sitemap-products.xml; çok parça → -N ekli."""
	if total_parts <= 1:
		return f"sitemap-{sub_name}.xml"
	return f"sitemap-{sub_name}-{part}.xml"


_NAME_TO_DOCTYPE = {cfg["sub_sitemap_name"]: dt for dt, cfg in DOCTYPE_CONFIG.items()}


def parse_sitemap_name(name: str) -> tuple[str | None, int]:
	"""`/sitemap-<name>.xml` içindeki <name>'i (doctype, part) ikilisine çözer.

	Guard (BE-MAP): yalnız bilinen sub-sitemap adları + opsiyonel pozitif parça
	numarası kabul edilir — path traversal / keyfi dosya adı reddedilir (None).
	Örnek: "products" → ("Listing", 1); "products-3" → ("Listing", 3);
	"../etc" → (None, 0).
	"""
	base, _, suffix = name.rpartition("-")
	if suffix.isdigit() and base in _NAME_TO_DOCTYPE:
		part = int(suffix)
		if part < 1 or part > 50_000:
			return None, 0
		return _NAME_TO_DOCTYPE[base], part
	if name in _NAME_TO_DOCTYPE:
		return _NAME_TO_DOCTYPE[name], 1
	return None, 0


# Frappe wrappers ------------------------------------------------------------


def _site_url() -> str:
	from tradehub_core.seo.site_url import storefront_url

	return storefront_url()


FETCH_BATCH_SIZE = 5_000


def _iter_records_for(doctype: str):
	"""DB'den sitemap kayıtlarını KEYSET pagination ile akıt (BE-MAP ölçek).

	`limit_page_length=0` milyon-satırlık tabloyu tek seferde belleğe alırdı;
	keyset (`name > last`) + sabit batch ile bellek düz kalır, OFFSET taraması
	da yapılmaz. Sistem işi: get_all bilinçli (perm bypass — public sitemap).
	"""
	import frappe

	cfg = DOCTYPE_CONFIG[doctype]
	slug_field = cfg["slug_field"]

	base_filters: dict = {"noindex": 0}
	if doctype == "Listing":
		# BUG FIX (BE-MAP): status=Active yerine denormalize storefront_visible
		# bayrağı — is_visible=0 (satıcı gizledi) ürünler sitemap'e SIZMAZ,
		# Out of Stock ama görünür ürünler sitemap'ten DÜŞMEZ.
		base_filters["storefront_visible"] = 1
	elif doctype == "Brand":
		base_filters["status"] = "Approved"

	fields = ["name", slug_field, "modified"]
	if doctype in ("Product Category", "Static Page SEO"):
		fields.extend(["sitemap_priority", "sitemap_changefreq"])
	if doctype == "Listing":
		# Görsel site haritası ana görselden başlıyor (TUR-135 §6); alan
		# sorguya alınmazsa `_image_entries_for_listing` yalnız galeriyi
		# görür ve ürünün ASIL görseli haritaya girmez.
		fields.append("primary_image")
		# Task 5: video kaynağı + başlık fallback'i — batch sorguya alınmazsa
		# `_video_entries_for_listing` her ilan için ayrı bir DB call açardı
		# (anti-patterns.md §6, N+1).
		fields.extend(["video_url", "title"])

	last_name = ""
	while True:
		filters = dict(base_filters)
		if last_name:
			filters["name"] = [">", last_name]
		rows = frappe.get_all(
			doctype,
			filters=filters,
			fields=fields,
			order_by="name asc",
			limit_page_length=FETCH_BATCH_SIZE,
		)
		if not rows:
			return
		for r in rows:
			if r.get(slug_field):
				yield r
		last_name = rows[-1]["name"]
		if len(rows) < FETCH_BATCH_SIZE:
			return


def _entry_for_row(row: dict, cfg: dict, site: str) -> dict:
	slug = row.get(cfg["slug_field"])
	# Static Page SEO: page_path zaten / ile başlıyor (örn. "/kvkk")
	# Diğerleri: prefix + "/" + slug (örn. "/urun" + "/" + "iphone")
	if cfg["url_prefix"]:
		tr_path = f"{cfg['url_prefix']}/{slug}"
	else:
		tr_path = slug if slug.startswith("/") else f"/{slug}"

	entry = urlentry(
		loc=f"{site}{tr_path}",
		lastmod=str(row.get("modified", ""))[:10],
		priority=str(row.get("sitemap_priority") or cfg["priority"]),
		changefreq=str(row.get("sitemap_changefreq") or cfg["changefreq"]),
	)
	# Faz 7: hreflang annotations (xhtml:link) — her TR URL'sine tr+en+x-default
	entry["hreflang_links"] = build_hreflang_links(tr_path, site)
	# TUR-135 §6: ürün sayfalarına görsel girdileri. Yalnız Listing —
	# kategori/marka sayfasının tek görseli var ve zaten sayfa taranırken
	# bulunuyor; ürün sayfasında galeri var ve Google onları ayrıca
	# keşfedemiyor (ar-ge §6 tablosu).
	if cfg.get("url_prefix") == "/urun":
		entry["images"] = _image_entries_for_listing(row, site)
		# Task 5: ürün videosu — `_image_entries_for_listing` ile aynı yerde
		# bağlanır (yalnız Listing sayfaları video taşır).
		entry["videos"] = _video_entries_for_listing(row, site)
	return entry


def _image_entries_for_listing(row: dict, site: str) -> list[dict]:
	"""Ürünün indexlenebilir görselleri → `<image:image>` girdileri.

	Alt metni/altyazı `media/seo.fields_for`'dan, indexability kararı
	`media/seo_index`'ten. Çöpteki, karantinadaki, hakkı dolmuş ya da private
	görsel site haritasına GİRMEZ — Google'a kaldırılmış kaynak göstermek
	kırık sonuç üretir.

	Hata halinde boş liste: site haritası üretimi zamanlanmış bir iştir ve
	medya tarafındaki bir sorun yüzünden TÜM haritanın üretilememesi,
	görselsiz üretilmesinden çok daha kötüdür.
	"""
	import frappe

	ad = row.get("name")
	if not ad:
		return []
	try:
		from tradehub_core.media import seo as media_seo
		from tradehub_core.media import seo_index

		adresler = media_seo.listing_usage_contexts(ad)

		girdiler: list[dict] = []
		gorulen: set[str] = set()
		for baglam in adresler[:_SITEMAP_IMAGE_LIMIT]:
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
			)
			girdi = {"loc": _mutlak(url, site)}
			if alanlar.get("caption") or alanlar.get("alt"):
				girdi["caption"] = alanlar.get("caption") or alanlar.get("alt")
			if alanlar.get("title"):
				girdi["title"] = alanlar["title"]
			if alanlar.get("license_url"):
				girdi["license"] = _mutlak(alanlar["license_url"], site)
			girdiler.append(girdi)
		return girdiler
	except Exception:
		frappe.log_error("sitemap image entries failed", "sitemap_generator")
		return []


#: Sayfa başına en fazla kaç görsel. Google sınırı 1.000; bizde galeriler
#: küçük, ama bir ürüne 200 görsel eklenirse harita şişmesin.
_SITEMAP_IMAGE_LIMIT: int = 25


def _video_entries_for_listing(row: dict, site: str) -> list[dict]:
	"""Ürünün indexlenebilir videosu → `<video:video>` girdisi.

	`_image_entries_for_listing`'in birebir kardeşi: alanlar `media/seo.
	fields_for_many`'dan, indexability kararı `media/seo_index.decide`'dan.
	Kaynak `Listing.video_url` — Listing Image galerisi yalnız görsel taşır
	(`Attach Image`, `media/usage.py` LIVE_SOURCES'ta tek video kaynağı
	`tabListing.video_url`).

	Poster'ı OLMAYAN video sitemap'e GİRMEZ: Google video sitemap şartı
	`thumbnail_loc`'u zorunlu kılıyor (spec Global Constraints). Poster ayrı
	bir arka plan işiyle (`media/video_poster.generate`) üretiliyor; henüz
	üretilmemişse video boş/kırık thumbnail ile gönderilmek yerine geçici
	olarak sitemap dışında kalır.

	Hata halinde boş liste: image kardeşiyle aynı gerekçe — medya tarafındaki
	bir arıza TÜM site haritasının üretilememesine yol açmasın.
	"""
	import frappe

	ad = row.get("name")
	video_url = str(row.get("video_url") or "").split("?")[0].strip()
	if not ad or not video_url:
		return []
	try:
		from tradehub_core.media import seo as media_seo
		from tradehub_core.media import seo_index
		from tradehub_core.media.video_poster import VIDEO_UZANTILAR

		if not video_url.lower().endswith(VIDEO_UZANTILAR):
			return []
		if not seo_index.decide(video_url, check_usage=False)["indexable"]:
			return []

		alanlar = next(iter(media_seo.fields_for_many([video_url]).values()), {})
		poster_url = alanlar.get("poster_url")
		if not poster_url:
			return []

		baslik = alanlar.get("title") or row.get("title") or video_url.rsplit("/", 1)[-1]
		video: dict = {
			"thumbnail_loc": _mutlak(poster_url, site),
			"title": baslik,
			"content_loc": _mutlak(video_url, site),
			"duration": alanlar.get("duration") or 0,
		}
		if alanlar.get("description") or alanlar.get("caption"):
			video["description"] = alanlar.get("description") or alanlar.get("caption")
		if alanlar.get("rights_expires_on"):
			video["expiration_date"] = alanlar["rights_expires_on"]
		return [video]
	except Exception:
		frappe.log_error("sitemap video entries failed", "sitemap_generator")
		return []


def _mutlak(url: str, site: str) -> str:
	if not url:
		return ""
	if url.startswith(("http://", "https://")):
		return url
	return f"{site.rstrip('/')}/{url.lstrip('/')}"


def build_chunks_for_type(doctype: str):
	"""Tek doctype için <urlset> XML PARÇALARINI akıt (generator).

	BUG FIX (BE-MAP): eski build_for_type yalnız chunks[0]'ı döndürüyordu —
	50k üzeri her kayıt sessizce sitemap dışı kalıyordu. Artık her 50k'lık
	parça ayrı XML olarak üretilir; disk cache'e parça parça yazılır (bellekte
	tek parça tutulur).
	"""
	cfg = DOCTYPE_CONFIG[doctype]
	site = _site_url()

	batch: list[dict] = []
	yielded = False
	for row in _iter_records_for(doctype):
		batch.append(_entry_for_row(row, cfg, site))
		if len(batch) >= MAX_URLS_PER_SITEMAP:
			yield build_urlset_xml(batch)
			yielded = True
			batch = []
	# Son parça; hiç kayıt yoksa geçerli boş urlset (tam-50k katında fazladan
	# boş parça üretme)
	if batch or not yielded:
		yield build_urlset_xml(batch)


def build_for_type(doctype: str) -> str:
	"""Geriye uyumlu wrapper: İLK parçayı döndürür (küçük doctype'lar tek parça)."""
	return next(build_chunks_for_type(doctype))


def build_index(parts_by_sub_name: dict[str, int] | None = None) -> str:
	"""Sitemap index'i üret.

	parts_by_sub_name: {sub_sitemap_name: parça_sayısı}. Verilmezse her tip
	tek parça varsayılır (küçük site fallback'i)."""
	from datetime import date

	site = _site_url()
	today = date.today().isoformat()
	parts_by_sub_name = parts_by_sub_name or {}

	sitemaps = []
	for _doctype, cfg in DOCTYPE_CONFIG.items():
		sub = cfg["sub_sitemap_name"]
		total = max(1, parts_by_sub_name.get(sub, 1))
		for part in range(1, total + 1):
			sitemaps.append(
				{
					"loc": f"{site}/{sitemap_file_name(sub, part, total)}",
					"lastmod": today,
				}
			)

	return build_index_xml(sitemaps)

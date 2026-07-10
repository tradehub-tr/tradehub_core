"""Kategori Vitrini (Category Showcase) varsayılan içeriğini seed'le.

Storefront ana sayfadaki "Kategorileri keşfet" bento grid'i admin içerik girene
kadar boş kalıyordu. Bu patch, storefront'taki onaylı mock tasarımın (2026-07-08
/impeccable redesign, tradehubfront categoryShowcaseService MOCK_SHOWCASE) birebir
kopyasını varsayılan içerik olarak oluşturur: 7 kategori kutusu + 1 promo kutu,
4 sütun, TR/EN başlıklar. Görseller Unsplash CDN (hepsi HTTP 200 doğrulandı).

Mevcut tile'ları (eski görselsiz varsayılan set) siler ve yeni seti kurar — onaylı
tasarım tüm ortamlarda (beta/RC/prod/alpha) aynı gelsin diye. Frappe patch'leri
site başına yalnızca bir kez çalışır; sonrasında admin'in yaptığı düzenlemelere
bir daha dokunulmaz.
"""

from __future__ import annotations

import frappe

_UNSPLASH = "https://images.unsplash.com/photo-{pid}?auto=format&fit=crop&w={w}&q=70"

_CATEGORY_TILES = [
	{
		"col_span": 2,
		"row_span": 2,
		"sort_order": 1,
		"label_tr": "Tekstil ve Giyim",
		"label_en": "Textile & Apparel",
		"hover_text_tr": "Toptan giyim, kumaş ve konfeksiyon",
		"hover_text_en": "Wholesale apparel, fabric and garments",
		"image": _UNSPLASH.format(pid="1441984904996-e0b6ba687e04", w=1200),
		"link_href": "/pages/categories.html?cat=tekstil-giyim",
	},
	{
		"col_span": 2,
		"row_span": 1,
		"sort_order": 2,
		"label_tr": "Elektronik ve Aksesuar",
		"label_en": "Electronics & Accessories",
		"hover_text_tr": "Telefon aksesuarı, kulaklık ve küçük elektronik",
		"hover_text_en": "Phone accessories, headphones and gadgets",
		"image": _UNSPLASH.format(pid="1518770660439-4636190af475", w=1000),
		"link_href": "/pages/categories.html?cat=elektronik",
	},
	{
		"col_span": 1,
		"row_span": 1,
		"sort_order": 3,
		"label_tr": "Ayakkabı ve Deri",
		"label_en": "Footwear & Leather",
		"hover_text_tr": "Ayakkabı, çanta ve deri ürünleri",
		"hover_text_en": "Shoes, bags and leather goods",
		"image": _UNSPLASH.format(pid="1549298916-b41d501d3772", w=800),
		"link_href": "/pages/categories.html?cat=ayakkabi-deri",
	},
	{
		"col_span": 1,
		"row_span": 1,
		"sort_order": 4,
		"label_tr": "Kozmetik ve Kişisel Bakım",
		"label_en": "Cosmetics & Personal Care",
		"hover_text_tr": "Toptan kozmetik ve bakım ürünleri",
		"hover_text_en": "Wholesale cosmetics and care products",
		"image": _UNSPLASH.format(pid="1596462502278-27bfdc403348", w=800),
		"link_href": "/pages/categories.html?cat=kozmetik",
	},
	{
		"col_span": 1,
		"row_span": 1,
		"sort_order": 5,
		"label_tr": "Ev ve Mutfak",
		"label_en": "Home & Kitchen",
		"hover_text_tr": "Züccaciye, mutfak ve ev gereçleri",
		"hover_text_en": "Glassware, kitchen and homeware",
		"image": _UNSPLASH.format(pid="1556911220-bff31c812dba", w=800),
		"link_href": "/pages/categories.html?cat=ev-mutfak",
	},
	{
		"col_span": 1,
		"row_span": 1,
		"sort_order": 6,
		"label_tr": "Hırdavat ve Yapı Market",
		"label_en": "Hardware & Tools",
		"hover_text_tr": "El aletleri ve yapı malzemeleri",
		"hover_text_en": "Hand tools and building supplies",
		"image": _UNSPLASH.format(pid="1504148455328-c376907d081c", w=800),
		"link_href": "/pages/categories.html?cat=hirdavat",
	},
	{
		"col_span": 1,
		"row_span": 1,
		"sort_order": 7,
		"label_tr": "Kırtasiye ve Ofis",
		"label_en": "Stationery & Office",
		"hover_text_tr": "Okul, ofis ve kırtasiye ürünleri",
		"hover_text_en": "School, office and stationery supplies",
		"image": _UNSPLASH.format(pid="1456735190827-d1262f71b8a3", w=800),
		"link_href": "/pages/categories.html?cat=kirtasiye",
	},
]

_PROMO_TILE = {
	"col_span": 1,
	"row_span": 1,
	"sort_order": 8,
	"promo_badge_tr": "Ticaret Güvencesi",
	"promo_badge_en": "Trade Assurance",
	"promo_title_tr": "Güvenli ödeme, teslimat garantisi",
	"promo_title_en": "Secure payment, guaranteed delivery",
	"background_color": "#0a0a0a",
	"cta_text_tr": "Nasıl çalışır?",
	"cta_text_en": "How it works?",
	"cta_href": "/pages/info/trade-assurance-detail.html",
}


def execute() -> dict:
	# Eski varsayılan seti kaldır — patch site başına tek sefer çalışır, sonraki
	# admin düzenlemeleri güvende.
	removed = 0
	for name in frappe.get_all("Category Showcase Tile", pluck="name"):
		frappe.delete_doc("Category Showcase Tile", name, ignore_permissions=True, force=True)
		removed += 1

	created = 0
	for spec in _CATEGORY_TILES:
		doc = frappe.new_doc("Category Showcase Tile")
		doc.tile_type = "category"
		doc.is_active = 1
		doc.update(spec)
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)  # migration bağlamı, kullanıcı akışı değil
		created += 1

	promo = frappe.new_doc("Category Showcase Tile")
	promo.tile_type = "promo"
	promo.is_active = 1
	promo.update(_PROMO_TILE)
	promo.flags.ignore_permissions = True
	promo.insert(ignore_permissions=True)
	created += 1

	settings = frappe.get_single("Category Showcase Settings")
	settings.is_enabled = 1
	settings.columns = 4
	# Başlığı yalnızca boşsa yaz — admin'in verdiği başlığı ezme.
	if not (settings.section_title_tr or "").strip():
		settings.section_title_tr = "Kategorileri keşfet"
	if not (settings.section_title_en or "").strip():
		settings.section_title_en = "Explore categories"
	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)

	frappe.db.commit()

	from tradehub_core.api.category_showcase import invalidate_cache

	invalidate_cache(None)

	return {"removed": removed, "created": created}

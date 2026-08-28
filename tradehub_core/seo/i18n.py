"""
Multi-language helpers (Faz 7).

Pure fonksiyonlar:
  - parse_lang_from_path(path) → (lang, normalized_path)
  - get_field_with_fallback(record, field, lang) → str
  - localize_url(path, lang) → str (TR prefix'siz, EN /en/ prefix'li)
  - build_hreflang_links(canonical_tr_path, site_url) → list[dict]
  - slug_field_for(doctype, lang) → str (doctype + dil-bazlı slug field adı)

Frappe runtime'a bağımlı değil; standalone test edilebilir.
"""

# SEO URL/hreflang dilleri — storefront router'ı yalnızca tr (prefix'siz) + en (/en/) destekliyor.
# ar/ru URL prefix routing'i ayrı bir iş; buraya eklemek henüz route olmayan hreflang üretir.
SUPPORTED_LANGS = ("tr", "en")
# İçerik çevirisi dilleri — storefront UI 4 dilli; resolve_content_field/normalize_lang bunu kullanır.
CONTENT_LANGS = ("tr", "en", "ar", "ru")
DEFAULT_LANG = "tr"

# Çevrilebilir içerik alanları — TEK KAYNAK.
# Patch (kolon üretimi), DocType controller (base↔default senkron + mandatory) ve
# API okuma katmanı (resolve_content_field) bu haritadan okur.
# Her alan için {field}_tr/_en/_ar/_ru sufix kolonları + kayıt başına content_default_lang.
CONTENT_TRANSLATABLE_FIELDS: dict[str, dict[str, dict]] = {
	"Listing": {
		"title": {"fieldtype": "Data", "length": 500, "reqd": 1},
		"short_description": {"fieldtype": "Small Text", "length": 500},
		"description": {"fieldtype": "Text Editor"},
		"selling_point": {"fieldtype": "Data"},
	},
	"Product Category": {
		"category_name": {"fieldtype": "Data", "reqd": 1},
		"description": {"fieldtype": "Text Editor"},
	},
}

# Çevrilebilir CHILD-table alanları (Phase 2 — teknik özellikler + varyantlar).
# Kaynak/varsayılan dil PARENT kaydın content_default_lang'inden gelir.
CONTENT_CHILD_TRANSLATABLE_FIELDS: dict[str, dict[str, dict]] = {
	"Listing Attribute Value": {
		"attribute_label": {"fieldtype": "Data"},
		"attribute_value": {"fieldtype": "Data"},
	},
	"Listing Variant Item": {
		"attribute_type": {"fieldtype": "Data"},
		"attribute_value": {"fieldtype": "Data"},
		"attribute_type_2": {"fieldtype": "Data"},
		"attribute_value_2": {"fieldtype": "Data"},
	},
}

# Parent doctype → [(child_table_fieldname, child_doctype), ...]
# sync_content_translations parent save'inde child base kolonlarını senkronlar.
CONTENT_CHILD_TABLES: dict[str, list[tuple[str, str]]] = {
	"Listing": [
		("attribute_values", "Listing Attribute Value"),
		("variant_items", "Listing Variant Item"),
	],
}

_LANG_LABEL = {"tr": "TR", "en": "EN", "ar": "AR", "ru": "RU"}

# ── Platform terim sözlüğü (kontrollü kelime dağarcığı) ──────────────────────
# Listing başlığı/açıklaması gibi SERBEST içerik suffix-kolon modeliyle çevrilir.
# Ama bazı alanlar platform-tanımlı, her kayıtta tekrarlayan SABİT terimlerdir
# (özellik grup başlıkları + paketleme etiketleri). Bunları 1990 satıra denormalize
# yazmak yerine burada tek noktada çeviriyoruz. Kaynak dil = tr; eşleşme yoksa
# (örn. satıcının eklediği özel grup) kaynak terim aynen döner.
# Anahtarlar TR kaynak metnin tam hâli (case-sensitive); değer dil→çeviri.
PLATFORM_TERMS: dict[str, dict[str, str]] = {
	# Özellik grupları (Listing Attribute Value.attribute_group)
	"Genel": {"en": "General", "ar": "عام", "ru": "Общее"},
	"Teknik": {"en": "Technical", "ar": "تقني", "ru": "Технические"},
	"Satış": {"en": "Sales", "ar": "المبيعات", "ru": "Продажи"},
	"Kullanım": {"en": "Usage", "ar": "الاستخدام", "ru": "Применение"},
	"Lojistik": {"en": "Logistics", "ar": "الخدمات اللوجستية", "ru": "Логистика"},
	"Uyum": {"en": "Compliance", "ar": "التوافق", "ru": "Соответствие"},
	"Paketleme": {"en": "Packaging", "ar": "التغليف", "ru": "Упаковка"},
	# Paketleme & teslimat etiketleri (api/listing.py'da üretilen sabit label'lar)
	"Paket Tipi": {"en": "Package Type", "ar": "نوع العبوة", "ru": "Тип упаковки"},
	"Paket Boyutu": {"en": "Package Dimensions", "ar": "أبعاد العبوة", "ru": "Размеры упаковки"},
	"Paket Ağırlığı": {"en": "Package Weight", "ar": "وزن العبوة", "ru": "Вес упаковки"},
	"Koli Başına Adet": {"en": "Units per Carton", "ar": "الوحدات لكل صندوق", "ru": "Единиц в коробке"},
	"Koli Boyutu": {"en": "Carton Dimensions", "ar": "أبعاد الصندوق", "ru": "Размеры коробки"},
	"Koli Brüt Ağırlığı": {
		"en": "Carton Gross Weight",
		"ar": "الوزن الإجمالي للصندوق",
		"ru": "Вес коробки брутто",
	},
	# Zaman birimleri (leadTime / shipping estimatedDays metinleri)
	"iş günü": {"en": "business days", "ar": "يوم عمل", "ru": "рабочих дней"},
	"gün": {"en": "days", "ar": "يوم", "ru": "дней"},
	# Kart istatistik etiketi ("{n} adet satıldı")
	"adet satıldı": {"en": "sold", "ar": "تم بيعها", "ru": "продано"},
	# Paket tipi Select seçenekleri (Listing.package_type — değer çevirisi)
	"Karton Kutu": {"en": "Cardboard Box", "ar": "صندوق كرتوني", "ru": "Картонная коробка"},
	"Poşet": {"en": "Polybag", "ar": "كيس بلاستيكي", "ru": "Полиэтиленовый пакет"},
	"Ahşap Kasa": {"en": "Wooden Crate", "ar": "صندوق خشبي", "ru": "Деревянный ящик"},
	"Palet": {"en": "Pallet", "ar": "منصة نقالة", "ru": "Паллета"},
	"File": {"en": "Net Bag", "ar": "كيس شبكي", "ru": "Сетка"},
	"Torba": {"en": "Sack", "ar": "كيس", "ru": "Мешок"},
	"Diğer": {"en": "Other", "ar": "أخرى", "ru": "Другое"},
	# Ölçü birimleri (Listing.stock_uom — UOM)
	"Adet": {"en": "Piece", "ar": "قطعة", "ru": "Штука"},
	"Çift": {"en": "Pair", "ar": "زوج", "ru": "Пара"},
	"Koli": {"en": "Carton", "ar": "صندوق", "ru": "Коробка"},
	"Paket": {"en": "Pack", "ar": "عبوة", "ru": "Упаковка"},
	"Kutu": {"en": "Box", "ar": "علبة", "ru": "Коробка"},
	"Takım": {"en": "Set", "ar": "طقم", "ru": "Комплект"},
	"Düzine": {"en": "Dozen", "ar": "دزينة", "ru": "Дюжина"},
	"Metre": {"en": "Meter", "ar": "متر", "ru": "Метр"},
	"Litre": {"en": "Liter", "ar": "لتر", "ru": "Литр"},
	"Kilogram": {"en": "Kilogram", "ar": "كيلوغرام", "ru": "Килограмм"},
	"Gram": {"en": "Gram", "ar": "غرام", "ru": "Грамм"},
	"Ton": {"en": "Ton", "ar": "طن", "ru": "Тонна"},
	"Rulo": {"en": "Roll", "ar": "لفة", "ru": "Рулон"},
	"Top": {"en": "Bolt", "ar": "طاقة", "ru": "Рулон"},
	"Set": {"en": "Set", "ar": "طقم", "ru": "Комплект"},
	# Medya alt metni sabit ekleri (Dilim 8 — Bulk Localization, L8). Kategori
	# adı/mağaza-marka adı SERBEST/özel isim içeriktir (buradan çevrilmez);
	# yalnız bu sabit ek çevrilir — `media/seo_generate.py` kural zinciri.
	"kategorisi": {"en": "category", "ar": "فئة", "ru": "категория"},
	"mağaza logosu": {"en": "store logo", "ar": "شعار المتجر", "ru": "логотип магазина"},
	"mağaza kapak görseli": {
		"en": "store cover image",
		"ar": "صورة غلاف المتجر",
		"ru": "обложка магазина",
	},
	"marka logosu": {"en": "brand logo", "ar": "شعار العلامة التجارية", "ru": "логотип бренда"},
	"marka kapak görseli": {
		"en": "brand cover image",
		"ar": "صورة غلاف العلامة التجارية",
		"ru": "обложка бренда",
	},
}


def format_discount_badge(pct: int, lang: str) -> str:
	"""İndirim rozeti metnini dile göre biçimle (% konumu dile göre değişir).

	tr: "%20 indirim" · en: "20% off" · ar: "خصم 20%" · ru: "скидка 20%"
	"""
	lang = normalize_lang(lang)
	if lang == "en":
		return f"{pct}% off"
	if lang == "ar":
		return f"خصم {pct}%"
	if lang == "ru":
		return f"скидка {pct}%"
	return f"%{pct} indirim"


def translate_platform_term(term: str, lang: str) -> str:
	"""Platform-tanımlı sabit terimi (özellik grubu, paketleme etiketi) çevir.

	Kaynak dil tr; istenen dilde eşleşme yoksa terimi aynen döndürür (satıcının
	eklediği bilinmeyen grup adları kaynak hâliyle kalır). Saf fonksiyon — DB yok.
	"""
	if not term:
		return ""
	lang = normalize_lang(lang)
	if lang == DEFAULT_LANG:
		return term
	return PLATFORM_TERMS.get(term, {}).get(lang, term)


def format_image_ordinal(n: int, lang: str) -> str:
	"""Görsel sıra eki — dile göre kalıp değişir (ekran okuyucu okunuşu ayrı).

	tr: "(2. görsel)" · en: "(image 2)" · ar: "(الصورة 2)" · ru: "(изображение 2)".
	`PLATFORM_TERMS` düz sözlüğüne sığmıyor (rakam gövdeye giriyor) — bu yüzden
	ayrı küçük saf yardımcı. `media/seo_generate.py` sıra numarası eklerken kullanır.
	"""
	lang = normalize_lang(lang)
	if lang == "en":
		return f"(image {n})"
	if lang == "ar":
		return f"(الصورة {n})"
	if lang == "ru":
		return f"(изображение {n})"
	return f"({n}. görsel)"


def content_lang_field(field: str, lang: str) -> str:
	"""Bir içerik alanının dil-bazlı kolon adı: ('title','ar') → 'title_ar'."""
	return f"{field}_{lang}"


def normalize_lang(lang: str | None) -> str:
	"""Geçersiz/boş içerik dili kodunu DEFAULT_LANG'a normalize et."""
	if lang and lang in CONTENT_LANGS:
		return lang
	return DEFAULT_LANG


def resolve_content_field(record: dict, field: str, lang: str, default_lang: str = DEFAULT_LANG) -> str:
	"""Çok-dilli içerik alanını çöz (simetrik 4-dil sufix modeli).

	İstenen dilin `{field}_{lang}` kolonu doluysa onu; değilse kaydın kaynak/varsayılan
	dilinin `{field}_{default_lang}` kolonuna; o da yoksa eski base `{field}` kolonuna düşer.

	`record` örn. {"title_ar": "...", "title_tr": "...", "content_default_lang": "tr"}.
	Storefront hot-path'inde çağrılır — saf fonksiyon, DB'ye dokunmaz.
	"""
	if not record or not field:
		return ""
	lang = normalize_lang(lang)
	default_lang = normalize_lang(default_lang)
	value = record.get(f"{field}_{lang}")
	if value:
		return value
	fallback = record.get(f"{field}_{default_lang}")
	if fallback:
		return fallback
	# Legacy base kolon (sufix kolonları doldurulmadan önceki TR içerik)
	return record.get(field) or ""


def parse_lang_from_path(path: str) -> tuple[str, str]:
	"""Path'in başındaki dil prefix'ini ayır.

	`/en/urun/x` → ("en", "/urun/x")
	`/urun/x`    → ("tr", "/urun/x")
	`/tr/urun/x` → ("tr", "/urun/x")  # explicit tr prefix temizlenir
	`/en`        → ("en", "/")
	"""
	if not path:
		return DEFAULT_LANG, "/"
	if not path.startswith("/"):
		path = "/" + path

	for lang in SUPPORTED_LANGS:
		# `/en` veya `/en/...`
		if path == f"/{lang}":
			return lang, "/"
		prefix = f"/{lang}/"
		if path.startswith(prefix):
			remainder = "/" + path[len(prefix) :]
			return lang, remainder

	return DEFAULT_LANG, path


def get_field_with_fallback(record: dict, field: str, lang: str) -> str:
	"""lang=en → record[field+'_en'] varsa o, yoksa record[field] (TR fallback).

	`url_slug` özel durum: lang=en → record['url_slug_en'] denenir.
	"""
	if not record or not field:
		return ""
	if lang == DEFAULT_LANG:
		return record.get(field, "") or ""
	en_field = f"{field}_en"
	en_value = record.get(en_field) or ""
	if en_value:
		return en_value
	return record.get(field, "") or ""


def localize_url(path: str, lang: str) -> str:
	"""TR prefix'siz, EN için `/en/` prefix ekle.

	`/urun/x` + tr → `/urun/x`
	`/urun/x` + en → `/en/urun/x`
	`/` + en → `/en/`
	"""
	if not path:
		path = "/"
	if not path.startswith("/"):
		path = "/" + path
	if lang == DEFAULT_LANG:
		return path
	if lang not in SUPPORTED_LANGS:
		return path
	# Halihazırda dil prefix'liyse tekrar ekleme
	if path.startswith(f"/{lang}/") or path == f"/{lang}":
		return path
	if path == "/":
		return f"/{lang}/"
	return f"/{lang}{path}"


def build_hreflang_links(canonical_tr_path: str, site_url: str) -> list[dict]:
	"""Tüm dil alternate link'leri + x-default.

	`canonical_tr_path` her zaman TR (prefix'siz) path olarak verilir.
	Returns: [
	  {"hreflang": "tr", "href": "https://istoc.com/urun/x"},
	  {"hreflang": "en", "href": "https://istoc.com/en/urun/x"},
	  {"hreflang": "x-default", "href": "https://istoc.com/urun/x"},
	]
	"""
	site = site_url.rstrip("/")
	links = []
	for lang in SUPPORTED_LANGS:
		links.append(
			{
				"hreflang": lang,
				"href": f"{site}{localize_url(canonical_tr_path, lang)}",
			}
		)
	# x-default → TR (default dil)
	links.append(
		{
			"hreflang": "x-default",
			"href": f"{site}{canonical_tr_path}",
		}
	)
	return links


def slug_field_for(doctype: str, lang: str) -> str:
	"""Doctype + dil-bazlı slug field adı.

	Product Category: tr → 'url_slug', en → 'url_slug_en'
	Listing/Brand/Admin Seller Profile: tr → 'slug', en → 'slug_en'
	"""
	base = "url_slug" if doctype == "Product Category" else "slug"
	if lang == DEFAULT_LANG:
		return base
	return f"{base}_en"

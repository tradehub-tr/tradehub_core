"""MOGEM-620 alan seti tamamlama — §2, §5, §11, §12, §17.

10 Eylül 2026 denetimi şartnamenin alan listesini koda karşı satır satır
karşılaştırdı. Aşağıdaki kolonlar KARŞILIĞI OLMADIĞI için açılıyor. Karşılığı
olan hiçbir alan yeniden açılmadı — gerekçeler tek tek yazılı, çünkü bu
dosyanın en kolay hatası "adı benziyor, yenisini açayım" demek.

AÇILMAYANLAR VE NEDENİ
----------------------
    başlık/alt/altyazı çok dilli   → `th_media_{alan}_{lang}` (v15_9_37) VAR
    süre                           → `th_media_duration` (v15_9_49) VAR
    kapak/poster                   → `th_media_poster_url` (v15_9_49) VAR
    sanatçı                        → `th_media_artist` (v15_9_53) VAR
    telif/lisans beşlisi           → v15_9_4x VAR
    SKU                            → `Listing.name` (schema.org `sku`) VAR
    varyant SKU                    → `Listing Variant Item.variant_sku` VAR

NEDEN AYRI KOLON, NEDEN TEK JSON DEĞİL
--------------------------------------
Çok dilli alanlar (`description`, `transcript`, `captions_url`) mevcut
`alt`/`title`/`caption` deseniyle BİREBİR aynı: dil başına kolon. Tek bir
JSON kolonuna sıkıştırmak `seo._coz`'un dört satırlık çözümünü ikinci bir
ayrıştırıcıyla çoğaltmak ve `inventory` serbest aramasını o dillerde kör
bırakmak olurdu (`Locate` JSON içinde de eşleşir ama yanlış anahtarda da
eşleşir).

İki İSTİSNA bilinçli olarak JSON:
    `th_media_chapters`     — sıralı liste (başlangıç saniyesi + başlık),
                              sayısı önceden bilinmiyor; kolonla modellenemez.
    `th_media_tag_sources`  — etiket → kaynak eşlemesi; etiketlerin kendisi
                              zaten `th_media_tags` içinde virgüllü metin ve
                              o alanın şeklini değiştirmek 4.800 kaydı ve
                              her okuyanı kırardı (§17 gerekçesi
                              `media/tags_source.py` docstring'inde).

İdempotent: create_custom_fields(update=True).
"""

from __future__ import annotations

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

#: `seo.i18n.CONTENT_LANGS` ile AYNI küme. İçe aktarmak yerine sabit yazıldı:
#: yama geçmişe dönük çalışır ve bir gün dil eklenirse ESKİ yamanın davranışı
#: değişmemeli — yeni dil yeni yamayla gelir (aynı gerekçe v15_9_37'de).
_DILLER: tuple[str, ...] = ("tr", "en", "ar", "ru")


def _data(fieldname: str, label: str, fieldtype: str = "Data") -> dict:
	return {
		"fieldname": fieldname,
		"label": label,
		"fieldtype": fieldtype,
		"hidden": 1,
		"no_copy": 1,
		"module": "Tradehub Core",
	}


def _cok_dilli(taban: str, etiket: str, fieldtype: str) -> list[dict]:
	return [
		_data(f"th_media_{taban}_{lang}", f"TH Media {etiket} ({lang.upper()})", fieldtype)
		for lang in _DILLER
	]


FIELDS: dict[str, list[dict]] = {
	"File": [
		# ── §2 SEO Metadata Engine — karşılığı olmayan alanlar ───────────
		_data("th_media_long_description", "TH Media Long Description", "Text"),
		# `keywords` ile `tags` AYRI: `tags` satıcının kütüphane içi
		# düzenlemesi (filtrelenir, aranır), `keywords` yayına giden SEO
		# anahtar kelimeleri. Aynı kolonda tutmak, kütüphane etiketini
		# arama motoruna göndermek olurdu.
		_data("th_media_keywords", "TH Media Keywords", "Small Text"),
		# Varlık grafiğinin metin yüzü: "bu görsel hangi varlıkları
		# gösteriyor" (marka, kişi, yer). Grafiğin KENDİSİ `Media Usage` ve
		# `Media Asset Relation`; bu kolon yapısal veriye basılan serbest
		# metin listesi.
		_data("th_media_entities", "TH Media Entities", "Small Text"),
		_data("th_media_content_purpose", "TH Media Content Purpose"),
		# `source` provenans: varlığın NEREDEN geldiği (ajans, satıcı,
		# üretici kataloğu). `creator` kim ürettiği, `credit_text` nasıl
		# anılacağı — üçü farklı sorunun cevabı, schema.org da ayırıyor.
		_data("th_media_source", "TH Media Source"),
		# Şartname creator/author/photographer/videographer sayıyor.
		# Dördü için dört kolon açmak yerine TEK rol alanı: kişi zaten
		# `th_media_creator`'da, burada onun bu varlıktaki ROLÜ duruyor.
		# `creator_type` ile karışmaz — o schema.org `@type`
		# (Person/Organization), bu meslek rolü.
		_data("th_media_creator_role", "TH Media Creator Role"),
		_data("th_media_country", "TH Media Country"),
		_data("th_media_region", "TH Media Region"),
		_data("th_media_location", "TH Media Location"),
		# "enlem,boylam" tek Data alanı. İki ayrı Float yerine tek metin:
		# koordinat ya vardır ya yoktur, yarısı olmaz; iki kolonda birinin
		# dolup diğerinin boş kalması sessiz bir bozuk durum üretirdi.
		# EXIF GPS'ten OTOMATİK DOLMAZ — `exif_vault` GPS'i public türevden
		# çıkarıyor (§1 gizlilik kuralı); buraya operatör bilerek yazar.
		_data("th_media_geo", "TH Media Geo"),
		# ── §11 Multilingual — çok dilli asset alanları ──────────────────
		*_cok_dilli("description", "Description", "Text"),
		*_cok_dilli("transcript", "Transcript", "Long Text"),
		*_cok_dilli("captions_url", "Captions URL", "Data"),
		# ── §5 Video SEO — VideoObject'in eksik alanları ─────────────────
		# Sıralı bölüm listesi: [{"start": 0, "title": "Giriş"}, ...]
		_data("th_media_chapters", "TH Media Chapters", "Long Text"),
		_data("th_media_regions_allowed", "TH Media Regions Allowed", "Small Text"),
		_data("th_media_age_restriction", "TH Media Age Restriction"),
		_data("th_media_content_rating", "TH Media Content Rating"),
		# ── §17 Categorization — etiket kaynağı ──────────────────────────
		_data("th_media_tag_sources", "TH Media Tag Sources", "Small Text"),
	],
	# ── §12 E-commerce / Product SEO ────────────────────────────────────
	"Listing": [
		# GTIN (EAN/UPC/ISBN) — schema.org `gtin`. Marka ve kategori zaten
		# var, SKU `name`'den geliyor; eksik olan tek küresel tanımlayıcı
		# buydu ve Google Merchant tarafında ürün eşleştirmenin anahtarı.
		{
			"fieldname": "gtin",
			"label": "GTIN / Barkod",
			"fieldtype": "Data",
			"insert_after": "brand_name",
			"module": "Tradehub Core",
			"description": "EAN-13 / UPC-A / ISBN — yapısal veriye `gtin` olarak basılır.",
		},
	],
	"Listing Variant Item": [
		{
			"fieldname": "variant_gtin",
			"label": "Varyant GTIN",
			"fieldtype": "Data",
			"insert_after": "variant_sku",
			"module": "Tradehub Core",
		},
	],
	"Listing Image": [
		# Şartname 10 rol sayıyor. Select olarak modellendi (serbest metin
		# değil): rol yapısal veriye ve galeri sıralamasına giriyor, yazım
		# farkı ("Lifestyle"/"lifestyle") iki ayrı rol üretirdi.
		{
			"fieldname": "media_role",
			"label": "Medya Rolü",
			"fieldtype": "Select",
			"insert_after": "alt_text",
			"options": "\n".join(
				[
					"",
					"primary",
					"secondary",
					"gallery",
					"variant",
					"swatch",
					"lifestyle",
					"technical",
					"packaging",
					"360",
					"video",
				]
			),
			"module": "Tradehub Core",
		},
	],
}


def execute() -> None:
	create_custom_fields(FIELDS, update=True)

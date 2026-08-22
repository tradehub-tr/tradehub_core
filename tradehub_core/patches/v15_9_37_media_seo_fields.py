"""Medya SEO alanları — çok dil, üretim kaynağı, lisans/hak (TUR-135 Dilim 1).

Karar belgesi: `docs/MEDYA-SEO-SOZLESMESI.md` (§4.1 alan seti, §4.2 çok
dillilik, §4.4 lisans, §5.2 `alt_source`, §0 revizyon kaydı R1-R4).

NEDEN `File` ÜSTÜNDE
--------------------
Medya motorunun `Media Asset`'i (ADR-0023) varlık kimliğini taşıyor ama:
bugün 3 kayıt (şalter kapalı, `File` 5.873), yalnız SLOTA bağlı dosyalarda
açılıyor (sipariş dekontu, muhtelif ek kapsam dışı) ve `backup.py` onu
taşımıyor. SEO metni oraya yazılsaydı bugün yazacak yeri olmazdı, yarın
kapsamı eksik olurdu ve bir felakette yedeksiz kalırdı.

`File` her dosyada var, yedekte, ve kayıt düzeyinde: aynı görsel iki mağazaya
birden ait olduğunda her mağaza kendi alt metnini yazabiliyor
(`media/metadata.py` gerekçesi) — bu, motorun `(satıcı, slot, içerik)`
tanecikliğiyle de örtüşüyor.

Geçiş: okuma TEK kapıdan (`media/seo.py::fields_for`). Motor tabloları
dolduğunda o fonksiyonun içi değişir, tüketiciler değişmez.

ÇOK DİL — MEVCUT DESENE KATILIR
-------------------------------
`alt`, `title`, `caption` için `{alan}_{tr,en,ar,ru}` kolonları; desen
`seo/i18n.CONTENT_TRANSLATABLE_FIELDS` ile aynı (`resolve_content_field`
fallback zinciri burada da çalışır). AMA `File` o sözlüğe EKLENMEZ: oradaki
akış `content_default_lang` + controller senkronu + zorunluluk kontrolü
istiyor; `File` bir içerik doctype'ı değil ve `th_media_*` alanları hidden.
Medya tarafı kendi çözücüsünü kullanır (`media/seo.py`), aynı kolon
düzenini paylaşır. Bu bilinçli: iki sistem aynı BİÇİMİ paylaşır, aynı
KONTROLLERİ değil.

`description` ve `tags` tek dil kalır — dış yüzeyde render edilmiyorlar
(§4.1), yalnız panel içi arama/filtreleme besliyorlar.

İdempotent: `create_custom_fields(update=True)`; geri doldurma koşullu.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from tradehub_core.seo.i18n import CONTENT_LANGS

#: Çok dilli hale gelen medya alanları — base kolon KORUNUR (eski okuyucular
#: ve geri doldurma için), yanına dil kolonları açılır.
_TRANSLATABLE: dict[str, str] = {
	"th_media_alt": "Alt Text",
	"th_media_title": "Title",
	"th_media_caption": "Caption",
}

_LANG_LABEL = {"tr": "TR", "en": "EN", "ar": "AR", "ru": "RU"}


def _lang_fields() -> list[dict]:
	out: list[dict] = []
	for alan, etiket in _TRANSLATABLE.items():
		for lang in CONTENT_LANGS:
			out.append(
				{
					"fieldname": f"{alan}_{lang}",
					"label": f"TH Media {etiket} ({_LANG_LABEL[lang]})",
					"fieldtype": "Small Text" if alan == "th_media_caption" else "Data",
					"hidden": 1,
					"no_copy": 1,
					"module": "Tradehub Core",
				}
			)
	return out


FIELDS: dict[str, list[dict]] = {
	"File": [
		# ── Caption (R1) — description'dan AYRI: caption sayfada GÖRÜNÜR metin
		# (<figcaption>, ImageObject.caption, sitemap image:caption); description
		# panel içidir. 19 Ağu'da "aynı iş" diye eklenmemişti, üst belge ayrımı
		# netleştirdi.
		{
			"fieldname": "th_media_caption",
			"label": "TH Media Caption",
			"fieldtype": "Small Text",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		# ── Üretim kaynağı (R2) — dört durum, Check DEĞİL.
		# "AI önerdi, insan onayladı" ile "insan sıfırdan yazdı" denetimde ayrı
		# okunmalı; ayrıca "kural üretti" yenilenebilir, "insan yazdı" asla
		# ezilmez (§5.2 tablosu bu alan olmadan uygulanamaz).
		{
			"fieldname": "th_media_alt_source",
			"label": "TH Media Alt Source",
			"fieldtype": "Select",
			"options": "\nrule\nai\nhuman\nedited",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		# AI önerisi AYRI kolonda durur ve ASLA doğrudan yayınlanmaz (§5.2a):
		# erişilebilirlik alt'ı ile SEO açıklaması aynı şey değil; yanlış metin
		# ekran okuyucuya yalan söyler, boş alt "dekoratif" der.
		{
			"fieldname": "th_media_alt_ai",
			"label": "TH Media Alt (AI suggestion)",
			"fieldtype": "Small Text",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		# ── Lisans / telif (§4.4) — Google görsel lisans rozetinin okuduğu set.
		# ImageObject'e birebir bağlanır: creator, creditText, copyrightNotice,
		# license, acquireLicensePage.
		{
			"fieldname": "th_media_creator",
			"label": "TH Media Creator",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_credit_text",
			"label": "TH Media Credit Text",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_copyright_notice",
			"label": "TH Media Copyright Notice",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_license_url",
			"label": "TH Media License URL",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_acquire_license_url",
			"label": "TH Media Acquire License URL",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_usage_rights",
			"label": "TH Media Usage Rights",
			"fieldtype": "Small Text",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		# Süresi dolan varlık indexability'de noindex'e düşer ve denetimde
		# "expired asset still published" kuralına takılır (§6.1, §6.3).
		{
			"fieldname": "th_media_rights_expires_on",
			"label": "TH Media Rights Expire On",
			"fieldtype": "Date",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		# ── Adres metadata'sı (R3/R4) — DİSK ADI DEĞİŞMEZ.
		# Servis adresi içerik-hash'li kalır (TUR-141/130 güvenlik kararı);
		# bunlar indirme adı, "kötü dosya adı" denetimi ve ileride medya
		# landing/watch page adresi için saklanır.
		{
			"fieldname": "th_media_seo_filename",
			"label": "TH Media SEO Filename",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_slug",
			"label": "TH Media Slug",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_canonical",
			"label": "TH Media Canonical URL",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
	]
}


def execute() -> None:
	alanlar = {"File": FIELDS["File"] + _lang_fields()}
	create_custom_fields(alanlar, update=True)

	# Geri doldurma: mevcut tek dilli değerler varsayılan dile taşınır.
	# `th_media_alt` bugün 3.123 dosyada BOŞ (ölçüm 18 Ağu) — yani pratikte
	# taşınacak veri yok; yine de koşullu çalıştırılıyor ki bu yama daha sonra
	# veri girilmiş bir site'ta koşarsa metin kaybolmasın.
	for alan in _TRANSLATABLE:
		hedef = f"{alan}_tr"
		if not (frappe.db.has_column("File", alan) and frappe.db.has_column("File", hedef)):
			continue
		frappe.db.sql(
			f"""
			UPDATE `tabFile`
			SET `{hedef}` = `{alan}`
			WHERE `{alan}` IS NOT NULL AND `{alan}` != ''
			  AND (`{hedef}` IS NULL OR `{hedef}` = '')
			"""
		)

	# Elle yazılmış mevcut alt metinleri "human" işaretlenir — kural motoru
	# (§5.2) yalnız `rule`/`ai` olanları yeniler; kaynak boş kalsaydı ilk
	# çalıştırmada insan emeği ezilirdi.
	if frappe.db.has_column("File", "th_media_alt_source"):
		frappe.db.sql(
			"""
			UPDATE `tabFile`
			SET th_media_alt_source = 'human'
			WHERE th_media_alt IS NOT NULL AND th_media_alt != ''
			  AND (th_media_alt_source IS NULL OR th_media_alt_source = '')
			"""
		)

	frappe.db.commit()

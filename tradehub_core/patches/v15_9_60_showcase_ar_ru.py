"""Ana sayfa vitrinindeki metinlerin Arapça ve Rusça karşılıklarını doldur.

NEDEN: Ölçüldü (17 Eyl 2026, alpha'da GERÇEK Suudi Arabistan IP'siyle, temiz
oturum): otomatik dil seçimi sayfayı Arapça ve RTL açıyordu ama vitrin bölümü
çevrilmemiş görünüyordu — "Kategorileri keşfet" ve "Tüm kategoriler" Türkçe,
hero başlığı İngilizce. Kanıt: `docs/ulke-turu-kanit/alpha/01-SA-anasayfa.png`.

Kök neden çeviri hattında DEĞİL, şemadaydı: `Category Showcase Tile` DocType'ı
yalnızca `_tr` ve `_en` kolonları taşıyordu; `_ar`/`_ru` hiç yoktu. Karşı kanıt
aynı turda ölçülmüştü — elle Türkçe seçilince vitrin doğru geliyordu, yani
kusur VERİDEYDİ.

Bu patch, `v15_9_10_seed_category_showcase` ile kurulan onaylı tasarımın
metinlerini dört dile tamamlar. Eşleme TÜRKÇE METNE göre yapılır: admin bir
kutunun Türkçesini değiştirdiyse o kutu atlanır — bilmediğimiz bir metne
çeviri yazmayız.

İDEMPOTENT: dolu bir `_ar`/`_ru` alanının üzerine YAZMAZ. İkinci koşum 0 yazar
ve admin'in elle girdiği çeviri korunur.
"""

from __future__ import annotations

import frappe

#: Türkçe metin → {ar, ru}. Kaynak: v15_9_10 tohumundaki onaylı tasarım.
_SOZLUK: dict[str, dict[str, str]] = {
	# Etiketler
	"Tekstil ve Giyim": {"ar": "المنسوجات والملابس", "ru": "Текстиль и одежда"},
	"Elektronik ve Aksesuar": {"ar": "الإلكترونيات والإكسسوارات", "ru": "Электроника и аксессуары"},
	"Ayakkabı ve Deri": {"ar": "الأحذية والجلود", "ru": "Обувь и изделия из кожи"},
	"Kozmetik ve Kişisel Bakım": {
		"ar": "مستحضرات التجميل والعناية الشخصية",
		"ru": "Косметика и личная гигиена",
	},
	"Ev ve Mutfak": {"ar": "المنزل والمطبخ", "ru": "Дом и кухня"},
	"Hırdavat ve Yapı Market": {"ar": "الأدوات ومواد البناء", "ru": "Инструменты и стройматериалы"},
	"Kırtasiye ve Ofis": {"ar": "القرطاسية والمكتب", "ru": "Канцтовары и офис"},
	# Üzerine gelince çıkan açıklamalar
	"Toptan giyim, kumaş ve konfeksiyon": {
		"ar": "ملابس وأقمشة ومنسوجات بالجملة",
		"ru": "Оптом одежда, ткани и трикотаж",
	},
	"Telefon aksesuarı, kulaklık ve küçük elektronik": {
		"ar": "إكسسوارات الهاتف وسماعات وإلكترونيات صغيرة",
		"ru": "Аксессуары для телефонов, наушники и мелкая электроника",
	},
	"Ayakkabı, çanta ve deri ürünleri": {
		"ar": "أحذية وحقائب ومنتجات جلدية",
		"ru": "Обувь, сумки и изделия из кожи",
	},
	"Toptan kozmetik ve bakım ürünleri": {
		"ar": "مستحضرات تجميل وعناية بالجملة",
		"ru": "Оптом косметика и средства ухода",
	},
	"Züccaciye, mutfak ve ev gereçleri": {
		"ar": "أدوات زجاجية ومستلزمات المطبخ والمنزل",
		"ru": "Посуда, кухонные и хозяйственные товары",
	},
	"El aletleri ve yapı malzemeleri": {
		"ar": "عدد يدوية ومواد بناء",
		"ru": "Ручной инструмент и стройматериалы",
	},
	"Okul, ofis ve kırtasiye ürünleri": {
		"ar": "مستلزمات المدرسة والمكتب والقرطاسية",
		"ru": "Школьные, офисные и канцелярские товары",
	},
	# Promo kutusu
	"Ticaret Güvencesi": {"ar": "ضمان التجارة", "ru": "Торговая гарантия"},
	"Güvenli ödeme, teslimat garantisi": {
		"ar": "دفع آمن وضمان التسليم",
		"ru": "Безопасная оплата, гарантия доставки",
	},
	"Nasıl çalışır?": {"ar": "كيف يعمل؟", "ru": "Как это работает?"},
	# Bölüm başlığı (Settings)
	"Kategorileri keşfet": {"ar": "استكشف الفئات", "ru": "Изучите категории"},
}

#: `<kok>_tr` okunur, `<kok>_ar` / `<kok>_ru` yazılır.
_KOKLER = ("label", "hover_text", "promo_badge", "promo_title", "cta_text")
_DILLER = ("ar", "ru")


def execute() -> dict:
	rapor = {"scanned": 0, "written": 0, "skipped_filled": 0, "skipped_unknown": 0}

	for ad in frappe.get_all("Category Showcase Tile", pluck="name"):
		doc = frappe.get_doc("Category Showcase Tile", ad)
		degisti = False
		for kok in _KOKLER:
			kaynak = (doc.get(f"{kok}_tr") or "").strip()
			if not kaynak:
				continue
			rapor["scanned"] += 1
			karsilik = _SOZLUK.get(kaynak)
			if not karsilik:
				# Admin metni değiştirmiş olabilir — tahminle çeviri yazmayız.
				rapor["skipped_unknown"] += 1
				continue
			for dil in _DILLER:
				if (doc.get(f"{kok}_{dil}") or "").strip():
					rapor["skipped_filled"] += 1
					continue
				doc.set(f"{kok}_{dil}", karsilik[dil])
				rapor["written"] += 1
				degisti = True
		if degisti:
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)

	settings = frappe.get_single("Category Showcase Settings")
	baslik = (settings.section_title_tr or "").strip()
	karsilik = _SOZLUK.get(baslik)
	if karsilik:
		for dil in _DILLER:
			if not (settings.get(f"section_title_{dil}") or "").strip():
				settings.set(f"section_title_{dil}", karsilik[dil])
				rapor["written"] += 1
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)

	# Yük 60 sn önbellekli; yazdıktan sonra temizlenmezse ilk dakika eski veri döner.
	from tradehub_core.api.category_showcase import CACHE_KEY

	frappe.cache.delete_value(CACHE_KEY)
	frappe.logger().info(f"v15_9_60_showcase_ar_ru: {rapor}")
	return rapor

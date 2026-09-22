"""Kategori adlarının en/ar/ru karşılıklarını hazır sözlükten doldur.

NEDEN BİR PATCH: `catalog/category_i18n.py` 16 Eylül 2026'da eklendi —
modül, 801 kayıtlık sözlük tohumu ve 374 satır test birlikte commit edildi
(`e5bb810`). Ama hattı ÇAĞIRAN hiçbir şey yoktu: `patches.txt`'te satır,
`hooks.py`'de kanca, panelde ekran, başka bir modülde referans — dördü de
sıfırdı. Testler yeşildi çünkü fonksiyonun DOĞRU çalıştığını ölçüyorlardı;
hiçbiri "bunu çağıran var mı" diye sormuyordu.

Sonuç ölçüldü (21 Eyl 2026, canlı): `get_categories` dört dilde de Türkçe
dönüyordu — `lang=ar` istendiğinde bile "Ambalaj ve Paketleme". Yani arayüz
dört dilde çalışırken katalog tek dilliydi.

`apply_name_seed()` idempotenttir: dolu bir alanın üzerine YAZMAZ, ikinci
koşum 0 yazar. Bu yüzden patch her migrate'te güvenle çalışabilir ve elle
yapılmış düzeltmeleri ezmez.

Sözlükte karşılığı olmayan kategori ATLANIR (bugün 23.511 kategorinin ~868'i
doluyor — menünün üst iki seviyesi). Kalanı `backfill_names()` sağlayıcıyla
doldurur; sağlayıcı yapılandırılmadan o hat hiçbir şey yazmaz (stub koruması).
"""

import frappe

from tradehub_core.catalog.category_i18n import apply_name_seed


def execute() -> None:
	rapor = apply_name_seed()
	# Rapor log'a düşsün: "kaç kategori dolduruldu" sorusu deploy sonrası
	# sorulacak ve tek kanıt bu satır olacak.
	frappe.logger().info(f"v15_9_59_seed_category_names: {rapor}")

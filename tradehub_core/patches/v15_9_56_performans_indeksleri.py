"""MOGEM-638 §4.3 / §7-14: tam taramaya düşen üç sorgu için indeks.

Ölçüldü (2026-09-12, EXPLAIN, 7.694 kategori / 2.531 ilan):

* `tabProduct Category`'de `is_active`, `parent_product_category`, `lft/rgt` için
  HİÇ indeks yoktu — mega menü ve `get_categories` sorguları `type=ALL`,
  rows=7562, "Using filesort". Ağaç sorgularının tamamı tarama.
* `get_search_suggestions` (`storefront_visible=1 ORDER BY order_count DESC,
  view_count DESC`) mevcut `(storefront_visible, order_count)` indeksini
  seçiyor ama ikinci sıralama anahtarı indekste olmadığı için filesort kalıyor.

EXPLAIN ile doğrulanan sonuç (aynı gün):

* `(parent_product_category, is_active)` → `get_categories` kök sorgusu
  ALL/7562 satırdan ref/7 satıra indi.
* `(storefront_visible, order_count, view_count)` → `get_search_suggestions`
  filesort'suz, doğrudan indeks sırasından okuyor.
* `(lft, rgt)` → NSM alt ağaç süzgeci (`lft >= ? AND rgt <= ?`) için.

Denenip ÇIKARILAN: `(is_active, sort_order, lft)` — mega menü sorgusu için
düşünülmüştü ama kategorilerin %100'ü aktif olduğundan optimizer indeksi
possible_keys'e koyup seçmedi (type=ALL kaldı). Mega menünün çözümü indeks
değil sonuç önbelleği (api/category.get_mega_menu). Doğrulanmayan indeks
33 indeksli yazma maliyetine eklenmesin diye burada yok.

Idempotent: `frappe.db.add_index` var olan indekste no-op.
"""

import frappe

_INDEXES = (
	("Product Category", ["parent_product_category", "is_active"], "idx_pc_parent_active"),
	("Product Category", ["lft", "rgt"], "idx_pc_lft_rgt"),
	("Listing", ["storefront_visible", "order_count", "view_count"], "idx_listing_sfv_orders_views"),
)


def execute():
	for doctype, fields, name in _INDEXES:
		table = f"tab{doctype}"
		if not all(frappe.db.has_column(doctype, f) for f in fields):
			frappe.log_error(
				f"{table}: {fields} kolonlarından biri yok, indeks atlandı", "performans_indeksleri"
			)
			continue
		frappe.db.add_index(doctype, fields, index_name=name)
	frappe.db.commit()

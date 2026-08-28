"""Guest izleme sayfası (`/medya/v/<slug>`) sıcak yolu için index (final inceleme, Important bulgu).

`api/media_public.py` her `/medya/v/<slug>` isteğinde iki eşitlik filtresi
çalıştırıyor:

  - `frappe.get_all("File", filters={"th_media_slug": slug})` (satır ~252)
  - `frappe.get_all("Listing", filters={"video_url": file_url, ...})` (satır ~167)

Her ikisi de **index'siz** kolon üzerinde. `File.th_media_slug` `v15_9_37`
yamasıyla açıldı ama o yama (ve onu okuyan `media/watch_slug.py`) hiçbir
noktada `add_index` çağırmadı — `v15_9_20_media_scan_fields.py` ve
`v15_9_14_media_state_field.py`'nin aksine, oradaki kardeş kolonlar
(`th_media_scan_status`, `th_media_state`) aynı sıcak-yol gerekçesiyle
index'lenmişti, bu ikisi atlanmış.

`tabFile` 25k+ satır (ve büyüyor — her medya yüklemesi bir satır); index'siz
eşitlik filtresi her guest isteğinde tam tablo taraması demek. Bu endpoint
`allow_guest=True` (storefront SEO sayfası, login gerektirmiyor) — yani
tarama maliyeti kimliksiz herhangi bir istemci tarafından tetiklenebilir,
istek hacmi arttıkça büyüyen bir DoS yüzeyi. `Listing.video_url` de aynı
gerekçeyle index'siz: `tabListing` küçük değil ve bu filtre watch page'in
"bu dosya hangi listing'e ait" çözümlemesinde HER istekte çalışıyor.

Idempotent: `frappe.db.add_index` zaten var olan index'i sessizce atlar
(`ALTER TABLE ... ADD INDEX IF NOT EXISTS`); `try/except` + `frappe.log_error`
sarımı `v15_9_20`/`v15_9_14` deseniyle aynı — bir index oluşturma hatası
migration'ı düşürmemeli.

**Desenden BİLİNÇLİ sapma — search_index property setter'ı BİZ set ediyoruz:**
`v15_9_20`/`v15_9_14` sadece `add_index` çağırıp bırakıyor. Bu canlıda
doğrulanırken gerçek bir regresyon yakalandı: `frappe/database/mariadb/
database.py::add_index` search_index property setter'ını YALNIZ
`frappe.flags.in_migrate`/`in_install` **False** iken yazıyor — ama patch'ler
HER ZAMAN `bench migrate` içinde, yani bu bayrak **True** iken çalışıyor. Property
setter yazılmazsa meta `search_index=0` görmeye devam eder; bir SONRAKİ
`bench migrate`'in şema senkronu (`frappe/database/schema.py::DbColumn.
set_column`: "`current_def['index'] and not self.set_index` → DROP INDEX")
bu index'i "elle silinmiş" sanıp kaldırıyor. Doğrulamada BİREBİR bu oldu: ilk
migrate `video_url_index`'i oluşturdu, ikinci migrate (idempotens turu) onu
sildi çünkü property setter yoktu. `th_media_state_index` (v15_9_14, en eski
kardeş) canlıda ŞU AN tam olarak bu yüzden eksik — aynı sapmayı yeni bir kez
daha tekrarlamak yerine burada `make_property_setter` ile search_index=1
kalıcı hale getiriliyor (desen: `v15_9_7_hide_asp_fake_perf_fields.py` —
"idempotent: make_property_setter aynı (doctype, field, property) için var
olan setter'ı günceller", autoname `{doctype}-{field}-{property}` + `validate()`
içindeki `delete_property_setter` çağrısı çakışmayı önlüyor).

Desen: `v15_9_20_media_scan_fields.py`, `v15_9_14_media_state_field.py`
(add_index), `v15_9_7_hide_asp_fake_perf_fields.py` (make_property_setter idempotens).
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

#: (doctype, fieldname) — guest sıcak yolun (`/medya/v/<slug>`) index'lenecek
#: eşitlik filtreleri.
_HEDEFLER: list[tuple[str, str]] = [
	("File", "th_media_slug"),
	("Listing", "video_url"),
]


def execute() -> None:
	for doctype, fieldname in _HEDEFLER:
		# Guest sıcak yol (`/medya/v/<slug>`) — index'siz eşitlik filtresi
		# `tabFile`'da (25k+ satır, büyüyor) ve `tabListing`'de tam tablo
		# taraması demekti (final inceleme, Important bulgu): allow_guest=True
		# endpoint, tarama maliyeti kimliksiz istemciyle tetiklenebiliyordu.
		try:
			frappe.db.add_index(doctype, [fieldname])
		except Exception:
			frappe.log_error(
				title=f"watch page index failed: {doctype}.{fieldname}",
				message=frappe.get_traceback(),
			)
			continue

		# `add_index` migrate/install bayrağı altında search_index property
		# setter'ını atlıyor (yukarıdaki docstring) — burada elle tamamlıyoruz
		# ki index bir SONRAKİ migrate'in şema senkronunda silinmesin.
		try:
			make_property_setter(
				doctype=doctype,
				fieldname=fieldname,
				property="search_index",
				value="1",
				property_type="Check",
				validate_fields_for_doctype=False,
			)
		except Exception:
			frappe.log_error(
				title=f"watch page search_index property setter failed: {doctype}.{fieldname}",
				message=frappe.get_traceback(),
			)

	frappe.db.commit()

"""`File` üstündeki iki eski medya index'ini `in_migrate` tuzağına karşı sabitle.

Bağlam — `v15_9_50_watch_slug_indexes.py` docstring'i:
`frappe.db.add_index`, çağrıldığı an `frappe.flags.in_migrate`/`in_install`
**True** ise (patch'ler HER ZAMAN `bench migrate` içinde çalıştığı için bu
her zaman doğru) `search_index` property setter'ını YAZMAZ
(`frappe/database/mariadb/database.py::add_index` — sadece bayrak yokken
"assuming this is manually added via code or console" varsayımıyla yazıyor).
Property setter yoksa meta `search_index=0` görmeye devam eder ve BİR SONRAKİ
`bench migrate`'in şema senkronu (`frappe/database/schema.py::DbColumn.
set_column`: `current_def["index"] and not self.set_index` → `DROP INDEX`)
index'i "elle silinmiş" sanıp kaldırır.

`v15_9_50` bu tuzağı `add_index` + `make_property_setter` ikilisiyle çözdü —
ama iki ESKİ kardeş kolon bu düzeltmeden önce yazıldığı için aynı riski
taşıyor durumda kaldı:

- `File.th_media_state` (`v15_9_14_media_state_field.py`) — yalnız `add_index`
  çağırıyor, property setter yok.
- `File.th_media_scan_status` (`v15_9_20_media_scan_fields.py`) — aynı durum.

**Canlı kanıt (istoc-dev-backend-1 / istoc.localhost, bu patch yazılmadan
önce ölçüldü):**

```
SHOW INDEX FROM tabFile WHERE Column_name IN ('th_media_state','th_media_scan_status');
→ yalnız th_media_scan_status_index döndü — th_media_state'in index'i YOK.
```

`th_media_state_index`'in yokluğu tam olarak `v15_9_50` docstring'inin
öngördüğü senaryo: index bir ara migrate turunda oluşup, property setter
yokluğunda sonraki şema senkronunda sessizce düşmüş (en eski kardeş, en çok
migrate turuna maruz kalmış).

`th_media_scan_status_index` şu an DB'de duruyor, ama bunun nedeni kod
değil — `tabProperty Setter`'da `File-th_media_scan_status-search_index=1`
kaydı var (creation: 2026-08-24), oysa repo'da bunu yazan HİÇBİR patch/kod
yok (`grep -rl th_media_scan_status … | xargs grep -l make_property_setter`
yalnız bu dosyayı ve `v15_9_50`'yi buluyor). Yani bu index şu an sadece bu
container'ın DB'sinde elle/console'dan oluşmuş bir property setter'ın
şansına bağlı hayatta — `custom_field.search_index` meta değeri hâlâ `0`.
Fresh bir site kurulumunda ya da bu container dışındaki bir ortamda
`th_media_scan_status` index'i de `th_media_state` ile aynı kaderi paylaşır.
Bu patch her iki alan için de property setter'ı KOD İÇİNDE, idempotent ve
tekrar-üretilebilir şekilde sabitliyor.

Idempotent: `frappe.db.add_index` var olan index'i sessizce atlar;
`make_property_setter` aynı (doctype, field, property) için var olan
setter'ı günceller (desen: `v15_9_7_hide_asp_fake_perf_fields.py`,
`v15_9_50_watch_slug_indexes.py`).

Desen: `v15_9_50_watch_slug_indexes.py` (add_index + make_property_setter
ikilisi), `v15_9_20_media_scan_fields.py` / `v15_9_14_media_state_field.py`
(add_index — düzeltilen eksik kısım).
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

#: (doctype, fieldname) — `v15_9_14`/`v15_9_20`'de add_index çağrılmış ama
#: search_index property setter'ı hiç yazılmamış, `in_migrate` tuzağına açık
#: eski kardeş kolonlar.
_HEDEFLER: list[tuple[str, str]] = [
	("File", "th_media_state"),
	("File", "th_media_scan_status"),
]


def execute() -> None:
	for doctype, fieldname in _HEDEFLER:
		# `th_media_state`: envanter/durum filtresi (v15_9_14), index canlıda
		# şu an eksik — bir önceki migrate turunda property setter'sız düşmüş.
		# `th_media_scan_status`: süpürücünün 5 dakikada bir attığı
		# `pending` filtresi (v15_9_20), index şu an ayakta ama yalnız bu
		# container'daki izole/elle oluşmuş bir property setter sayesinde.
		try:
			frappe.db.add_index(doctype, [fieldname])
		except Exception:
			frappe.log_error(
				title=f"media index failed: {doctype}.{fieldname}",
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
				title=f"media search_index property setter failed: {doctype}.{fieldname}",
				message=frappe.get_traceback(),
			)

	frappe.db.commit()

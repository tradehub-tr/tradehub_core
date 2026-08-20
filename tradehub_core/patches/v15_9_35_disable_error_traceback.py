"""B-04 (rapor 92 §3) — `allow_error_traceback` her ortamda kapatılır.

Frappe v15 `System Settings.allow_error_traceback` varsayılanı **1** ve
`is_traceback_allowed()` `developer_mode`'a hiç bakmaz: kimse ayarı elle
kapatmadıysa PROD sitesi de misafire tam traceback + iç dosya yolları döndürür
(canlı ölçüldü — rapor 92'de önce/sonra çıktısı). Hatalar `Error Log`'a
yazılmaya devam eder; kapatmanın geliştirici maliyeti yok.

İdempotent: ayar zaten 0 ise dokunmaz. Bilinçli olarak KOŞULSUZ 0'lar —
"bir kere biri 1 yaptıysa saygı duy" davranışı burada yanlış olurdu; ayarı
bilerek açmak isteyen ortam patch'ten SONRA açar ve bunun bilinçli bir
güvenlik kararı olduğu görünür olur.
"""

import frappe


def execute():
	if frappe.db.get_single_value("System Settings", "allow_error_traceback"):
		frappe.db.set_single_value("System Settings", "allow_error_traceback", 0)
		frappe.db.commit()

"""14.6 Geri doldurma: kurulum öncesi var olan Builder Page'ler için SEO Page aynası + politika.

Idempotent: aynası olan sayfaya dokunmaz. Büyük sitelerde parti parti (BATCH) commit eder ki
migrate uzun bir tek işlem açmasın. Geri dönüş: `SEO Page` satırları silinebilir; Builder Page'e
yazılan tek alan `canonical_url` (politika çıktısı) — girdi `seo_canonical`'da korunur.
"""

import frappe

BATCH = 200


def execute():
	if not frappe.db.exists("DocType", "SEO Page") or not frappe.db.exists("DocType", "Builder Page"):
		return
	from tradehub_core.seo_helper.cms.bridge import mirror_builder_page
	from tradehub_core.seo_helper.core.policy import apply_for_page

	adlar = frappe.db.sql(
		"select b.name from `tabBuilder Page` b where coalesce(b.is_template, 0) = 0 "
		"and not exists (select 1 from `tabSEO Page` s where s.builder_page = b.name) order by b.creation",
		pluck="name",
	)
	yapilan = hata = 0
	for i, name in enumerate(adlar, 1):
		try:
			page = mirror_builder_page(frappe.get_doc("Builder Page", name))
			apply_for_page(page)
			yapilan += 1
		except Exception:  # noqa: BLE001 — tek sayfa geri doldurmayı düşürmez; Error Log'a
			hata += 1
			frappe.log_error(title=f"seo_helper backfill {name}", message=frappe.get_traceback())
		if i % BATCH == 0:
			frappe.db.commit()
	frappe.db.commit()
	print(f"seo_helper backfill: {yapilan} ayna, {hata} hata, {len(adlar)} aday")

"""SEO Audit Finding.active_key (UNIQUE) doldurma: aktif bulgular için parmak izi; aynı izde birden çok aktif
kayıt varsa (eşzamanlı koşum yarışı — 662 e2e-7 ile görüldü) en yenisi kalır, diğerleri occurrences'ları
toplanarak kapatılır. İdempotent."""

import frappe


def execute():
	if not frappe.db.has_column("SEO Audit Finding", "active_key"):
		return
	aktif = ("open", "reopened", "recrawl_pending", "fixed")
	rows = frappe.db.sql(
		"""select name, fingerprint, occurrences from `tabSEO Audit Finding`
		where status in %(s)s and coalesce(fingerprint,'') != '' and active_key is null
		order by fingerprint, creation desc""",
		{"s": aktif},
		as_dict=True,
	)
	gorulen: dict[str, str] = {}
	kapanan = 0
	for r in rows:
		if r.fingerprint in gorulen:
			frappe.db.sql(
				"update `tabSEO Audit Finding` set status='closed', active_key=NULL, resolved=1, closed_at=now(), "
				"resolved_at=now() where name=%s",
				(r.name,),
			)
			frappe.db.sql(
				"update `tabSEO Audit Finding` set occurrences = coalesce(occurrences,0) + %s where name=%s",
				(int(r.occurrences or 0), gorulen[r.fingerprint]),
			)
			kapanan += 1
			continue
		gorulen[r.fingerprint] = r.name
		frappe.db.sql("update `tabSEO Audit Finding` set active_key=fingerprint where name=%s", (r.name,))
	frappe.db.commit()
	print(f"active_key: {len(gorulen)} aktif iz, {kapanan} çift kayıt kapatıldı")

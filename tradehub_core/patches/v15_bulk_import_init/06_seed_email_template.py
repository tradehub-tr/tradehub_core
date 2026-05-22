# Copyright (c) 2026, TradeHub Team and contributors

"""Seed Frappe Email Template — bulk-import-job-failed (default text, edit OK)."""

import frappe

EMAIL_TEMPLATE_NAME = "bulk-import-job-failed"

SUBJECT = "Toplu yükleme başarısız: {{ job_name }}"

BODY = """
<p>Sayın satıcımız,</p>

<p><strong>{{ job_name }}</strong> numaralı toplu yükleme işleminiz tamamlanamadı.</p>

<p><strong>Hata:</strong> {{ error_summary }}</p>

<p><strong>Eklenen ürün sayısı:</strong> {{ inserted }} / {{ total }}</p>

<p>Detay için panele giriş yapın: <a href="{{ panel_url }}">{{ panel_url }}</a></p>

<hr>
<p style="font-size: 11px; color: #888;">
Bu otomatik bildirimdir. Email tercihlerinizi değiştirmek için admin'le iletişime geçin.
</p>
""".strip()


def execute():
	"""Seed bulk-import-job-failed Email Template (idempotent)."""
	# Email Template doctype kuruluda yoksa atla (graceful — özel kurulumlarda olabilir).
	if not frappe.db.exists("DocType", "Email Template"):
		return
	if frappe.db.exists("Email Template", EMAIL_TEMPLATE_NAME):
		return
	doc = frappe.new_doc("Email Template")
	doc.name = EMAIL_TEMPLATE_NAME
	doc.subject = SUBJECT
	doc.response = BODY
	doc.use_html = 1
	try:
		doc.insert(ignore_permissions=True)
	except Exception as e:
		frappe.log_error(f"Seed email template failed: {e}", "v15_bulk_import_init.06")
	frappe.db.commit()

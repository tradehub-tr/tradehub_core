"""Bulk import bildirimleri — in-app + (opsiyonel) email.

Email default OFF, master switch (`Analytics Settings.enable_failure_emails`) ile açılır.
Şu an sadece `job_failed` event'inde email gönderilir, body hardcoded Türkçe.
"""

import frappe

_FAILURE_SUBJECT = "Toplu yükleme başarısız: {job_name}"
_FAILURE_BODY = """
<p>Sayın satıcımız,</p>
<p><strong>{job_name}</strong> numaralı toplu yükleme işleminiz tamamlanamadı.</p>
<p><strong>Hata:</strong> {error_summary}</p>
<p><strong>Eklenen ürün sayısı:</strong> {inserted} / {total}</p>
<p>Detay için: <a href="{panel_url}">{panel_url}</a></p>
<hr>
<p style="font-size: 11px; color: #888;">
Bu otomatik bildirimdir. Email tercihlerinizi değiştirmek için admin'le iletişime geçin.
</p>
"""

EMAIL_ENABLED_EVENTS: set[str] = {"job_failed"}


def notify(event_type: str, context: dict) -> None:
	"""Bildirim merkezi giriş noktası."""
	_send_in_app(event_type, context)

	if event_type not in EMAIL_ENABLED_EVENTS:
		return
	if not _email_master_enabled():
		return
	_send_failure_email(context)


def _send_in_app(event_type: str, context: dict) -> None:
	"""Platform Notification doctype kullanarak in-app bildirim."""
	job = context.get("job")
	if not job:
		return

	titles = {
		"job_completed": "Toplu yükleme tamamlandı",
		"job_completed_with_errors": "Toplu yükleme kısmen tamamlandı",
		"job_failed": "Toplu yükleme başarısız",
	}
	msgs = {
		"job_completed": f"{job.inserted_count or 0} yeni ürün eklendi",
		"job_completed_with_errors": (
			f"{job.inserted_count or 0} eklendi, "
			f"{job.error_count or 0} hata, "
			f"{job.skipped_count or 0} atlandı"
		),
		"job_failed": f"İşlem tamamlanamadı: {(job.error_summary or '')[:100]}",
	}

	try:
		seller_user = frappe.db.get_value(
			"Admin Seller Profile",
			job.seller_profile,
			"owner",
		)
		if seller_user and frappe.db.exists("DocType", "Platform Notification"):
			notif = frappe.new_doc("Platform Notification")
			notif.recipient_user = seller_user
			notif.title = titles.get(event_type, "Toplu yükleme bildirimi")
			notif.message = msgs.get(event_type, "")
			notif.action_url = f"/panel/bulk-import/{job.name}"
			notif.insert(ignore_permissions=True)
	except Exception as e:
		frappe.log_error(
			f"in-app notify failed: {e}",
			"bulk_import.notifications",
		)


def _email_master_enabled() -> bool:
	"""Analytics Settings.enable_failure_emails flag kontrol."""
	try:
		return bool(
			frappe.db.get_single_value(
				"Analytics Settings",
				"enable_failure_emails",
			)
		)
	except Exception:
		return False


def _send_failure_email(context: dict) -> None:
	"""Hardcoded Türkçe failure mail."""
	job = context.get("job")
	if not job:
		return

	owner_user = frappe.db.get_value(
		"Admin Seller Profile",
		job.seller_profile,
		"owner",
	)
	seller_email = frappe.db.get_value(
		"Admin Seller Profile",
		job.seller_profile,
		"email",
	)
	if not seller_email and owner_user:
		seller_email = frappe.db.get_value("User", owner_user, "email")
	if not seller_email:
		return

	from tradehub_core.seo.site_url import admin_panel_url

	panel_url = f"{admin_panel_url()}/bulk-import/{job.name}"
	try:
		frappe.sendmail(
			recipients=[seller_email],
			subject=_FAILURE_SUBJECT.format(job_name=job.name),
			message=_FAILURE_BODY.format(
				job_name=job.name,
				error_summary=(job.error_summary or "Bilinmeyen hata"),
				inserted=job.inserted_count or 0,
				total=job.total_rows or 0,
				panel_url=panel_url,
			),
			now=False,
		)
	except Exception as e:
		frappe.log_error(
			f"failure email failed: {e}",
			"bulk_import.notifications",
		)

"""Background job: collect user's personal data into JSON+CSV ZIP archive."""

import csv
import hashlib
import io
import json
import os
import secrets
import zipfile

import frappe
from frappe.utils import add_to_date, get_files_path, now_datetime

_EXPORTABLE_DOCTYPES = {
	"User": {
		"filters_field": "name",
		"label": "Hesap Bilgileri",
		"fields": [
			"email",
			"first_name",
			"last_name",
			"full_name",
			"username",
			"time_zone",
			"enabled",
			"creation",
		],
	},
	"User Profile": {
		"filters_field": "user",
		"label": "Kullanıcı Profili",
		"fields": [
			"member_id",
			"status",
			"full_name",
			"phone",
			"country",
			"account_type",
			"company_name",
			"tax_id",
			"tax_id_type",
			"tax_office",
			"email_verified",
			"business_type",
			"year_established",
			"employee_count",
			"sourcing_frequency",
			"annual_spending",
			"joined_at",
			"created_via",
		],
	},
	"Seller Profile": {
		"filters_field": "user",
		"label": "Satıcı Profili",
		"fields": [
			"store_name",
			"store_slug",
			"description",
			"phone",
			"email",
			"city",
			"district",
			"address",
			"creation",
		],
	},
	"Seller Application": {
		"filters_field": "user",
		"label": "Satıcı Başvurusu",
		"fields": [
			"company_name",
			"company_type",
			"tax_id",
			"tax_office",
			"status",
			"creation",
		],
	},
	"Addresses": {
		"filters_field": "user",
		"label": "Adresler",
		"fields": [
			"address_title",
			"address_type",
			"address_line1",
			"address_line2",
			"city",
			"state",
			"country",
			"pincode",
			"phone",
			"purpose",
			"creation",
		],
	},
	"Order": {
		"filters_field": "buyer",
		"label": "Siparişler",
		"fields": [
			"name",
			"status",
			"grand_total",
			"currency",
			"creation",
		],
	},
	"Cart": {
		"filters_field": "user",
		"label": "Sepet",
		"fields": ["name", "creation"],
	},
	"RFQ": {
		"filters_field": "buyer",
		"label": "Teklif Talepleri",
		"fields": [
			"name",
			"status",
			"subject",
			"creation",
		],
	},
	"Listing Review": {
		"filters_field": "reviewer",
		"label": "Değerlendirmeler",
		"fields": [
			"listing",
			"rating",
			"title",
			"content",
			"status",
			"creation",
		],
	},
	"Listing Question": {
		"filters_field": "asked_by",
		"label": "Sorular",
		"fields": [
			"listing",
			"question",
			"status",
			"creation",
		],
	},
	"Search History": {
		"filters_field": "user",
		"label": "Arama Geçmişi",
		"fields": ["query", "creation"],
	},
	"User Product View": {
		"filters_field": "user",
		"label": "Ürün Görüntülemeleri",
		"fields": ["listing", "creation"],
	},
	"User Email Preference": {
		"filters_field": "user",
		"label": "E-posta Tercihleri",
		"fields": ["category", "enabled", "creation"],
	},
	"Buyer Favorite List": {
		"filters_field": "user",
		"label": "Favori Listesi",
		"fields": ["listing", "creation"],
	},
	"User Consent Log": {
		"filters_field": "user",
		"label": "Onay Kayıtları",
		"fields": [
			"consent_type",
			"action",
			"version",
			"source",
			"creation",
		],
	},
}


def generate_user_data_export(request_name: str) -> None:
	"""Enqueue target: collects all user data, creates ZIP, emails link."""
	frappe.flags.audit_write = True

	req = frappe.get_doc("Data Export Request", request_name)
	if req.status != "Pending":
		return

	req.db_set("status", "Processing", update_modified=False)
	frappe.db.commit()

	try:
		user = req.user
		zip_buffer = io.BytesIO()

		with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
			manifest = {}

			for dt, cfg in _EXPORTABLE_DOCTYPES.items():
				if not frappe.db.exists("DocType", dt):
					continue

				export_fields = cfg.get("fields")
				try:
					records = frappe.get_all(
						dt,
						filters={cfg["filters_field"]: user},
						fields=export_fields or ["name", "creation"],
						limit_page_length=0,
					)
				except Exception:
					continue

				if not records:
					continue

				clean = records
				slug = frappe.scrub(dt)

				zf.writestr(f"{slug}.json", json.dumps(clean, ensure_ascii=False, indent=2, default=str))

				if clean:
					csv_data = _records_to_csv(clean)
					zf.writestr(f"{slug}.csv", csv_data)

				manifest[dt] = {"label": cfg["label"], "count": len(clean)}

			zf.writestr(
				"manifest.json",
				json.dumps(
					{
						"user": user,
						"exported_at": str(now_datetime()),
						"format": "json_csv",
						"doctypes": manifest,
					},
					ensure_ascii=False,
					indent=2,
				),
			)

		zip_bytes = zip_buffer.getvalue()
		user_hash = hashlib.sha256(user.encode()).hexdigest()[:12]
		token = secrets.token_urlsafe(32)
		fname = f"data-export-{user_hash}-{token[:8]}.zip"

		private_path = get_files_path(is_private=True)
		os.makedirs(private_path, exist_ok=True)
		full_path = os.path.join(private_path, fname)

		with open(full_path, "wb") as f:
			f.write(zip_bytes)

		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": fname,
				"file_url": f"/private/files/{fname}",
				"is_private": 1,
				"attached_to_doctype": "Data Export Request",
				"attached_to_name": request_name,
			}
		)
		file_doc.insert(ignore_permissions=True)

		expires = add_to_date(None, hours=72)

		req.reload()
		req.db_set(
			{
				"status": "Ready",
				"completed_at": now_datetime(),
				"file_url": file_doc.file_url,
				"file_size": len(zip_bytes),
				"expires_at": expires,
				"download_token": token,
			},
			update_modified=False,
		)
		frappe.db.commit()

		_send_export_ready_email(user, request_name, token)

	except Exception as e:
		frappe.db.rollback()
		req.reload()
		req.db_set(
			{
				"status": "Failed",
				"error_message": str(e)[:2000],
			},
			update_modified=False,
		)
		frappe.db.commit()
		frappe.log_error(f"Data export failed for {request_name}")


def _clean_record(record: dict) -> dict:
	"""Remove None values from export record."""
	return {k: v for k, v in record.items() if v is not None}


def _records_to_csv(records: list[dict]) -> str:
	if not records:
		return ""
	output = io.StringIO()
	fieldnames = list(records[0].keys())
	writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
	writer.writeheader()
	for r in records:
		writer.writerow({k: str(v) if v is not None else "" for k, v in r.items()})
	return output.getvalue()


def _send_export_ready_email(user: str, request_name: str, token: str) -> None:
	# storefront_url() ortam-özel + restore-proof; get_url() backend host'u döner.
	from tradehub_core.seo.site_url import storefront_url

	download_url = (
		f"{storefront_url()}/api/method/tradehub_core.api.v1.compliance.download_data_export"
		f"?request_name={request_name}&token={token}"
	)
	frappe.sendmail(
		recipients=[user],
		subject="Veri Dışa Aktarma Talebiniz Hazır",
		message=f"""
        <p>Merhaba,</p>
        <p>Talep ettiğiniz kişisel veri dışa aktarma dosyanız hazırdır.</p>
        <p><a href="{download_url}">Verilerimi İndir</a></p>
        <p>Bu link 72 saat geçerlidir.</p>
        <p>Bu talebi siz yapmadıysanız lütfen bize ulaşın.</p>
        """,
	)


def cleanup_expired_exports() -> None:
	"""Daily scheduled: delete expired export ZIP files."""
	expired = frappe.get_all(
		"Data Export Request",
		filters={
			"status": "Ready",
			"expires_at": ("<", now_datetime()),
		},
		fields=["name", "file_url"],
	)

	for exp in expired:
		if exp.file_url:
			try:
				fpath = frappe.get_site_path("private", "files", os.path.basename(exp.file_url))
				if os.path.exists(fpath):
					os.remove(fpath)
				attached = frappe.get_all(
					"File",
					filters={"file_url": exp.file_url, "attached_to_name": exp.name},
					pluck="name",
				)
				for f in attached:
					frappe.delete_doc("File", f, ignore_permissions=True, force=True)
			except Exception:
				frappe.log_error(f"Failed to cleanup export file for {exp.name}")

		frappe.db.set_value("Data Export Request", exp.name, "status", "Expired", update_modified=False)

	if expired:
		frappe.db.commit()
		frappe.logger().info(f"Cleaned up {len(expired)} expired data exports")

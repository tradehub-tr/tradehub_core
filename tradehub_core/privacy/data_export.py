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

# T-134 / KVKK denetim izi — veri sahibi (m.11) akışının eylem sabitleri.
# Desen mevcut: `media/audit.py` ACTION_* sabitleri + `account_deletion.py`nin
# `log_decision(action="account.anonymize")` çağrısı. Yeni desen İCAT EDİLMEDİ.
# Kimlik MASKELEME kuralı: bu satırlara kullanıcı e-postası YAZILMAZ — satır
# `Data Export Request` kaydına işaret eder, kimlik orada (satır silinirse
# denetim satırı kimliksiz kalır; bu bilinçli: ADL saklama süresi talep
# kaydından uzun olabilir ve anonimleştirme sonrası ADL'de PII kalmamalı).
ACTION_EXPORT_GENERATED: str = "privacy.export_generated"
ACTION_EXPORT_PURGED: str = "privacy.export_purged"


def _collect_user_media(user: str) -> list[dict]:
	"""Ö-K2 — veri sahibinin KENDİ medyasını KVKK maskesiyle toplar.

	KVKK maskesi = medya envanterinin (`media/inventory.py`) HİJYEN KEMERLERİ,
	yeniden uygulanmadı, doğrudan `_base_query()` çağrılıyor:
	  * yalnız public (`is_private=0`) — KYB/KYC evrakı gibi private dosyalar dışarıda,
	  * klasör değil, KVKK/hassas doctype eki değil (EXCLUDED_DOCTYPES),
	  * HASSAS-İKİZ maskesi: hassas bir belgeyle AYNI içeriğe (content_hash) sahip
	    public kopya export'a GİRMEZ.
	Sahiplik envanter listesiyle BİREBİR aynı süzgeçten (`ownership.scope`): yalnız
	kullanıcının mağazasının yüklediği/kullandığı dosyalar. Böylece BAŞKASININ
	göremeyeceği dosya export'a sızmaz — süzgeci gevşetmek (scope'u atlamak ya da
	ham `File` sorgusu) doğrudan bir veri sızıntısıdır (vacuity testi bunu kanıtlar).

	Mağazası olmayan kullanıcı (alıcı) için boş liste: bu modelde public medyayı
	mağazalar yükler (`media/ownership.py` ölçümü: 2839/2839 dosya bir mağazaya
	çözülüyor).
	"""
	from frappe.query_builder.functions import Max, Min

	from tradehub_core.media import inventory, ownership

	store = ownership.store_of(user)
	if not store:
		return []

	f, query = inventory._base_query()
	query = ownership.scope(query, f, store)
	# `_base_query()` `file_url` ile grupluyor; gruplanmayan kolonlar agregatla
	# seçilir (envanterin `list_files` deseniyle aynı).
	rows = query.select(
		f.file_url,
		Min(f.file_name).as_("file_name"),
		Max(f.file_size).as_("file_size"),
		Min(f.creation).as_("uploaded_at"),
	).run(as_dict=True)
	return rows

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

		_PAGE_LIMIT = 5000

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
						limit_page_length=_PAGE_LIMIT,
					)
				except Exception:
					frappe.log_error(f"Failed to fetch records for doctype {dt} during user data export for user {user}", "data_export.generate_user_data_export")
					continue

				if not records:
					continue

				truncated = len(records) >= _PAGE_LIMIT
				clean = records
				slug = frappe.scrub(dt)

				zf.writestr(f"{slug}.json", json.dumps(clean, ensure_ascii=False, indent=2, default=str))

				if clean:
					csv_data = _records_to_csv(clean)
					zf.writestr(f"{slug}.csv", csv_data)

				entry = {"label": cfg["label"], "count": len(clean)}
				if truncated:
					entry["truncated"] = True
					entry["note"] = "Kayıt sayısı limiti aştığından veriler kısmi olabilir."
				manifest[dt] = entry

			# Ö-K2 — veri sahibinin yüklediği medya. Ayrı bölüm: kaynağı `tabFile`,
			# `_EXPORTABLE_DOCTYPES` deseni (doctype+filters_field) buna uymuyor.
			# KVKK maskesi `_collect_user_media` içinde (hassas-ikiz + sahiplik).
			try:
				media_rows = _collect_user_media(user)
			except Exception:
				frappe.log_error(
					f"Failed to collect user media during data export for user {user}",
					"data_export.generate_user_data_export",
				)
				media_rows = []

			if media_rows:
				zf.writestr(
					"media.json",
					json.dumps(media_rows, ensure_ascii=False, indent=2, default=str),
				)
				zf.writestr("media.csv", _records_to_csv(media_rows))
				manifest["File"] = {"label": "Yüklenen Medya", "count": len(media_rows)}

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

		# T-134: KVKK m.11 dışa aktarım izi — PII arşivi diskte OLUŞTU (veri
		# sunucu içinde de olsa tek dosyada toplandı; media.export ile aynı
		# gerekçeyle HIGH). Token/dosya yolu yazılmaz; boyut ve kapsam yazılır.
		try:
			from tradehub_core.audit.log import DECISION_ALLOW, LAYER_L3, SEVERITY_HIGH, log_decision

			log_decision(
				# ADL.actor Link→User doğrular; "System" diye bir User YOK — canlıda
				# ölçüldü: actor="System" satırı sessizce düşüyor (rapor 92 §4).
				# Sistem işleri Frappe'de Administrator oturumuyla koşar.
				actor="Administrator",
				action=ACTION_EXPORT_GENERATED,
				decision=DECISION_ALLOW,
				rule_id="kvkk.article11",
				layer=LAYER_L3,
				object_doctype="Data Export Request",
				object_name=request_name,
				severity=SEVERITY_HIGH,
				context={"doctypes": len(manifest), "zip_bytes": len(zip_bytes)},
			)
		except Exception:
			frappe.log_error(
				f"Failed to write audit log after export generation {request_name}",
				"data_export.generate_user_data_export",
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
		# T-134: silme izi — süresi dolan KVKK arşivlerinin imhası TEK satırda
		# (`log_media_batch` deseni: toplu iş = tek özet kaydı). Talep adları
		# PII değildir (DER-xxxx); dosya yolları yazılmaz.
		try:
			from tradehub_core.audit.log import DECISION_ALLOW, LAYER_L3, log_decision

			log_decision(
				# actor="System" değil — ADL.actor Link→User (rapor 92 §4).
				actor="Administrator",
				action=ACTION_EXPORT_PURGED,
				decision=DECISION_ALLOW,
				rule_id="kvkk.article7",
				layer=LAYER_L3,
				object_doctype="Data Export Request",
				context={"purged": len(expired), "requests": [e.name for e in expired]},
			)
		except Exception:
			frappe.log_error("Failed to write audit log for export purge", "data_export.cleanup_expired_exports")
		frappe.db.commit()
		frappe.logger().info(f"Cleaned up {len(expired)} expired data exports")

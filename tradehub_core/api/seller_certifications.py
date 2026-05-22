"""
Sertifikalarım — admin panel /panel/my-certifications endpoint'leri.

v4 mimarisi (Model A — belge havuzu):
  - Belge SADECE Seller Certification'da (mağaza havuzu)
  - Listing Certification yalnız atama referansı + tarih override
  - Mağaza modal kategori kısıtı YOK (hem Mgmt hem Prod kabul)
  - Listing'e atanan cert için: parent mağaza cert Verified olmalı
  - verification_status: Pending → admin doğrular → Verified/Rejected
  - Storefront sadece Verified gösterir
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate, today

# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _require_seller_profile(capability: str | None = None) -> str:
	"""Login satıcının Admin Seller Profile name'i; yoksa throw.

	capability: opsiyonel — verilirse önce seller capability kontrolü yapılır
	(rol profili bazlı). Read endpoint'leri None geçer; write endpoint'leri
	"cert.write" gibi capability key geçer.
	"""
	if capability:
		from tradehub_core.utils.seller_capabilities import require_seller_capability

		require_seller_capability(capability)

	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Bu işlem için giriş yapmalısınız."), frappe.PermissionError)
	name = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
	if not name:
		frappe.throw(_("Satıcı profili bulunamadı."), frappe.DoesNotExistError)
	return name


@frappe.whitelist(allow_guest=True, methods=["POST"])
def clear_invalid_session():
	"""Bozuk/invalid session cookie'lerini server tarafından temizle.

	Frappe /api/method/logout invalid sid alındığında sid cookie'sini expire
	etmiyor — bu yüzden frontend 417 alıp redirect yaptığında httpOnly sid
	cookie'si tarayıcıda kalıyor, bir sonraki request yine 417 alıyor.

	Bu endpoint allow_guest — bozuk session'la bile çağrılabilir. Tüm session
	cookie'lerini Set-Cookie expire ile temizler.

	Frontend `api.js` 417 ValidationError "is disabled" yakaladığında bu
	endpoint'i çağırıp sonra /login'e yönlendirir.
	"""
	if hasattr(frappe.local, "cookie_manager"):
		for cookie_name in ("sid", "user_id", "full_name", "user_image", "system_user"):
			try:
				frappe.local.cookie_manager.delete_cookie(cookie_name)
			except Exception:
				pass
	return {"success": True, "message": "Session cookies cleared."}


def _require_admin() -> None:
	"""System Manager olmayan kullanıcılar reddedilir."""
	if "System Manager" not in frappe.get_roles(frappe.session.user):
		frappe.throw(_("Bu işlem için yetkiniz yok."), frappe.PermissionError)


def _ensure_folder(folder_path: str, parent: str = "Home") -> str:
	"""Folder yoksa oluştur. Idempotent. folder_path örnek: 'Home/sertifikalar/SEL-00001'.

	Frappe'de Folder = File doctype satırı (is_folder=1). Klasör adı tam path olarak
	name field'a yazılır (örn. 'Home/sertifikalar'). file_name son segment.
	"""
	if not folder_path:
		return parent
	if frappe.db.exists("File", {"name": folder_path, "is_folder": 1}):
		return folder_path

	# Parent klasör de yoksa rekürsif oluştur
	last_slash = folder_path.rfind("/")
	if last_slash > 0:
		parent_path = folder_path[:last_slash]
		file_name = folder_path[last_slash + 1 :]
		_ensure_folder(parent_path, parent="Home")
	else:
		parent_path = parent
		file_name = folder_path

	doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"is_folder": 1,
			"folder": parent_path,
		}
	)
	doc.insert(ignore_permissions=True)
	return folder_path


MAX_CERT_DOC_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_CERT_DOC_EXT = (".pdf", ".jpg", ".jpeg", ".png")


@frappe.whitelist(methods=["POST"])
def upload_seller_cert_document(file_name: str = "", file_content: str = ""):
	"""Satıcı sertifika belgesi yükle — base64 JSON üzerinden.

	CRITICAL FIX (2026-05): File doc.insert Frappe internal session.sid'i
	regenerate edebiliyor. Yeni sid response Set-Cookie header'ı ile tarayıcıya
	yazılınca tarayıcıdaki mevcut sid bozulur (whitespace içerebilir veya
	server-side karşılığı olmayan değer) → sonraki API request 417 EXPECTATION
	FAILED ("User None is disabled") → frontend login redirect.

	Çözüm: `frappe.local.cookie_manager.to_set` temizlenir — response'a
	Set-Cookie header'ı YAZILMAZ. Bu endpoint sadece dosya yükler, session
	state'i değişmemeli. Cookie ResponseFilter pattern.

	Args:
	    file_name: orijinal dosya adı (uzantı kontrolü için).
	    file_content: base64-encoded dosya içeriği (data URL prefix opsiyonel).
	"""
	import base64
	import os
	import secrets

	profile_name = _require_seller_profile("cert.write")

	# CRITICAL: Response Set-Cookie yazımını engelle — session/sid değişimi
	# tarayıcıya yansımayacak. Cookie state stable kalır.
	# Frappe v15 CookieManager (auth.py:372): cookies dict + to_delete list.
	# Endpoint başında snapshot al, sonunda restore et.
	_original_cookies = {}
	_original_to_delete = []
	try:
		if hasattr(frappe.local, "cookie_manager"):
			cm = frappe.local.cookie_manager
			_original_cookies = dict(cm.cookies)
			_original_to_delete = list(cm.to_delete)
	except Exception:
		pass

	seller_code = frappe.db.get_value("Admin Seller Profile", profile_name, "seller_code")
	if not seller_code:
		frappe.throw(_("Mağaza kodu bulunamadı."))

	if not file_name or not file_content:
		frappe.throw(_("Dosya gönderilmedi."))

	# Data URL prefix'i at ("data:application/pdf;base64,...")
	if "," in file_content and file_content.startswith("data:"):
		file_content = file_content.split(",", 1)[1]

	try:
		content = base64.b64decode(file_content, validate=False)
	except Exception:
		frappe.throw(_("Dosya bozuk veya geçersiz formatta."))

	# Boyut + tip kontrolü
	if len(content) > MAX_CERT_DOC_SIZE:
		frappe.throw(_("Dosya 10 MB'tan büyük olamaz."))
	if len(content) == 0:
		frappe.throw(_("Boş dosya yüklenemez."))

	lower_name = file_name.lower()
	if not any(lower_name.endswith(ext) for ext in ALLOWED_CERT_DOC_EXT):
		frappe.throw(_("Sadece PDF, JPG veya PNG dosya yükleyebilirsiniz."))

	# Klasörleri garanti et (idempotent)
	folder_path = f"Home/sertifikalar/{seller_code}"
	_ensure_folder("Home/sertifikalar")
	_ensure_folder(folder_path)

	# Diske yaz — random suffix ile çakışma engelle
	ext = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
	random_id = secrets.token_hex(12)
	stored_name = f"cert_{random_id}{ext}"

	site_files_path = frappe.get_site_path("public", "files")
	try:
		os.makedirs(site_files_path, exist_ok=True)
	except Exception:
		pass

	disk_path = os.path.join(site_files_path, stored_name)
	with open(disk_path, "wb") as f:
		f.write(content)

	# File doc — minimal, no_session_update flag ile cookie yan etkisini engelle
	frappe.local.flags.no_session_update = True

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"file_url": f"/files/{stored_name}",
			"folder": folder_path,
			"is_private": 0,
			"file_size": len(content),
		}
	)
	file_doc.flags.ignore_permissions = True
	file_doc.flags.ignore_version = True
	file_doc.insert(ignore_permissions=True)
	frappe.db.commit()

	# CRITICAL: File doc.insert sırasında Frappe internal'da `set_cookie("sid", ...)`
	# çağrılabilir (auth.py:382 init_cookies veya session.update side-effect). Bu
	# yeni sid response Set-Cookie ile tarayıcıya yazılırsa cookie state desync olur
	# (whitespace içerebilir, browser tarafından farklı parse edilir → 417).
	# Snapshot'a geri restore et: endpoint girişindeki cookie state korunur.
	try:
		if hasattr(frappe.local, "cookie_manager"):
			cm = frappe.local.cookie_manager
			cm.cookies = _original_cookies
			cm.to_delete = _original_to_delete
	except Exception:
		pass

	return {
		"file_url": file_doc.file_url,
		"file_name": file_doc.file_name,
		"name": file_doc.name,
	}


def _format_cert_row(row: dict) -> dict:
	"""Sertifika satırı ortak formatlama — expiry status hesaplaması dahil."""
	expiry = row.get("expiry_date")
	days_left = None
	if expiry:
		days_left = (getdate(expiry) - getdate(today())).days
		if days_left < 0:
			status_text = "Expired"
		elif days_left <= 30:
			status_text = "Expiring"
		else:
			status_text = "Active"
	else:
		status_text = "Active"

	return {
		"name": row.get("name"),
		"certification_type": row.get("certification_type"),
		"certificate_number": row.get("certificate_number"),
		"issued_date": row.get("issued_date"),
		"expiry_date": row.get("expiry_date"),
		"document": row.get("document"),
		"verification_status": row.get("verification_status") or "Pending",
		"rejection_reason": row.get("rejection_reason"),
		"category": row.get("category"),
		"status_text": status_text,
		"days_left": days_left,
	}


# ──────────────────────────────────────────────────────────────────────────
# Tab 1 — Mağaza Sertifikaları (belge havuzu) + Tab 3 + Tab 4 birleşik
# ──────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def get_my_certifications() -> dict:
	"""4 tab için tek seferde veri döner.

	seller_certs:  Mağaza Sertifikalarım (belge havuzu)
	suggestions:   Önerdiklerim (Cert Type suggested_by)
	catalog:       Sistem Kataloğu (Approved Cert Type'lar)
	"""
	profile_name = _require_seller_profile()
	user = frappe.session.user

	# Mağaza sertifikaları
	seller_certs_raw = frappe.get_all(
		"Seller Certification",
		filters={"parent": profile_name, "parenttype": "Admin Seller Profile"},
		fields=[
			"name",
			"certification_type",
			"category",
			"certificate_number",
			"issued_date",
			"expiry_date",
			"document",
			"verification_status",
			"rejection_reason",
		],
		order_by="idx ASC",
	)
	seller_certs = [_format_cert_row(r) for r in seller_certs_raw]

	# Önerilerim (Cert Type suggested_by)
	suggestions = frappe.get_all(
		"Certification Type",
		filters={"suggested_by": user},
		fields=[
			"name",
			"certification_name",
			"category",
			"status",
			"rejection_reason",
			"creation",
		],
		order_by="creation DESC",
	)

	# Sistem Kataloğu (sadece Approved)
	catalog = frappe.get_all(
		"Certification Type",
		filters={"status": "Approved"},
		fields=["name", "certification_name", "category", "description"],
		order_by="certification_name ASC",
	)

	return {
		"seller_certs": seller_certs,
		"suggestions": suggestions,
		"catalog": catalog,
	}


@frappe.whitelist()
def get_listing_cert_matrix(
	search: str = "",
	cert_filter: str = "",
	status_filter: str = "",
	page: int = 1,
	page_size: int = 50,
) -> dict:
	"""Ürün Sertifikalarım matrix — P2 filtre + arama + pagination dahil.

	search:        ürün adı veya name içinde arama
	cert_filter:   yalnız bu cert tipi atanmış ürünleri göster
	status_filter: 'expiring' (≤30 gün), 'expired', 'unassigned'
	"""
	profile_name = _require_seller_profile()

	try:
		page = max(1, int(page or 1))
	except Exception:
		page = 1
	try:
		page_size = max(10, min(500, int(page_size or 50)))
	except Exception:
		page_size = 50

	listing_filters = {"seller_profile": profile_name}
	if search:
		listing_filters["title"] = ["like", f"%{search}%"]

	# Önce toplam
	total = frappe.db.count("Listing", filters=listing_filters)

	# Eğer cert_filter veya status_filter varsa, prefiltreli listing isimleri al
	listing_name_filter = None
	if cert_filter:
		listing_name_filter = set(
			frappe.get_all(
				"Listing Certification",
				filters={
					"parenttype": "Listing",
					"certification_type": cert_filter,
				},
				pluck="parent",
			)
		)
	if status_filter == "unassigned":
		# Hiç sertifika atanmamış ürünler
		assigned = set(
			frappe.get_all(
				"Listing Certification",
				filters={"parenttype": "Listing"},
				pluck="parent",
			)
		)
		all_owned = set(frappe.get_all("Listing", filters=listing_filters, pluck="name"))
		unassigned = list(all_owned - assigned)
		listing_name_filter = (
			set(unassigned) if listing_name_filter is None else (listing_name_filter & set(unassigned))
		)

	final_filters = dict(listing_filters)
	if listing_name_filter is not None:
		if not listing_name_filter:
			return {"listings": [], "total": 0, "page": page, "page_size": page_size}
		final_filters["name"] = ["in", list(listing_name_filter)]

	listings = frappe.get_all(
		"Listing",
		filters=final_filters,
		fields=["name", "title"],
		order_by="title ASC",
		limit_page_length=page_size,
		limit_start=(page - 1) * page_size,
	)
	listing_names = [l["name"] for l in listings]

	if not listing_names:
		return {"listings": [], "total": total, "page": page, "page_size": page_size}

	# Cert satırları
	cert_rows = frappe.get_all(
		"Listing Certification",
		filters={"parent": ["in", listing_names], "parenttype": "Listing"},
		fields=[
			"name",
			"parent",
			"certification_type",
			"certificate_number",
			"issued_date",
			"expiry_date",
		],
	)

	# Parent mağaza cert verification_status'larını batch çek
	cert_types_in_use = list({r["certification_type"] for r in cert_rows})
	seller_cert_status = {}
	if cert_types_in_use:
		for sc in frappe.get_all(
			"Seller Certification",
			filters={
				"parent": profile_name,
				"parenttype": "Admin Seller Profile",
				"certification_type": ["in", cert_types_in_use],
			},
			fields=["certification_type", "verification_status"],
		):
			seller_cert_status[sc["certification_type"]] = sc["verification_status"]

	by_listing: dict[str, list] = {}
	for r in cert_rows:
		formatted = _format_cert_row(r)
		formatted["verification_status"] = seller_cert_status.get(r["certification_type"], "Pending")
		by_listing.setdefault(r["parent"], []).append(formatted)

	# status_filter expiring/expired — listing-bazlı tarih varsa onu, yoksa parent tarih
	if status_filter in ("expiring", "expired"):

		def matches(cert: dict) -> bool:
			days = cert.get("days_left")
			if days is None:
				return False
			if status_filter == "expiring":
				return 0 <= days <= 30
			return days < 0

		filtered = []
		for l in listings:
			certs = by_listing.get(l["name"], [])
			if any(matches(c) for c in certs):
				filtered.append(l)
		listings = filtered

	return {
		"listings": [
			{
				"name": l["name"],
				"title": l["title"],
				"certs": by_listing.get(l["name"], []),
			}
			for l in listings
		],
		"total": total,
		"page": page,
		"page_size": page_size,
	}


# ──────────────────────────────────────────────────────────────────────────
# Mağaza sertifikaları — CRUD (belge havuzu)
# ──────────────────────────────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def add_seller_cert(
	certification_type: str,
	certificate_number: str = "",
	issued_date: str | None = None,
	expiry_date: str | None = None,
	document: str = "",
) -> dict:
	"""Mağaza sertifikası ekle — belge havuzuna.

	v4: Kategori kısıtı YOK (hem Management hem Product kabul).
	verification_status default "Pending" — admin doğrulayana kadar storefront'ta gözükmez.

	Cookie protection (upload_seller_cert_document ile aynı pattern):
	Admin Seller Profile.save() Frappe internal'da `set_cookie("sid", ...)` çağırabilir
	→ response Set-Cookie tarayıcıdaki sid'i bozar → sonraki GET 417 → login redirect.
	Snapshot+restore ile response Set-Cookie yazımını engelliyoruz.
	"""
	profile_name = _require_seller_profile("cert.write")

	_original_cookies = {}
	_original_to_delete = []
	try:
		if hasattr(frappe.local, "cookie_manager"):
			cm = frappe.local.cookie_manager
			_original_cookies = dict(cm.cookies)
			_original_to_delete = list(cm.to_delete)
	except Exception:
		pass

	if not certification_type:
		frappe.throw(_("Sertifika tipi zorunludur."))

	# Belge zorunlu — admin doğrulama için gereklidir
	if not document or not str(document).strip():
		frappe.throw(_("Sertifika belgesi (PDF / JPG / PNG) yüklemek zorunludur."))

	ct = frappe.db.get_value("Certification Type", certification_type, ["status", "category"], as_dict=True)
	if not ct or ct.status != "Approved":
		frappe.throw(_("Sadece onaylanmış sertifika tipleri eklenebilir."))

	# Aynı cert daha önce eklenmiş mi?
	exists = frappe.db.exists(
		"Seller Certification",
		{
			"parent": profile_name,
			"parenttype": "Admin Seller Profile",
			"certification_type": certification_type,
		},
	)
	if exists:
		frappe.throw(
			_("'{0}' sertifikası mağaza havuzunuzda zaten mevcut. Düzenlemek için satırı kullanın.").format(
				certification_type
			)
		)

	frappe.local.flags.no_session_update = True
	try:
		profile = frappe.get_doc("Admin Seller Profile", profile_name)
		row = profile.append(
			"certifications",
			{
				"certification_type": certification_type,
				"certificate_number": certificate_number,
				"issued_date": issued_date,
				"expiry_date": expiry_date,
				"document": document,
				"verification_status": "Pending",
			},
		)
		# ignore_version: gereksiz Version doc oluşmasın.
		# ignore_mandatory: parent doctype'ın eksik field validation'ı bloklamasın.
		profile.flags.ignore_version = True
		profile.flags.ignore_mandatory = True
		profile.save(ignore_permissions=True)
		frappe.db.commit()

		# Frappe v15 parent.save() child row'lara parent.creation timestamp'ini yazar
		# (DELETE+INSERT pipeline yan etkisi). Yeni eklenen cert için "Yüklenme tarihi"
		# yanlış (parent'in oluşturulma tarihini gösterir). Manuel olarak now() set et.
		frappe.db.set_value(
			"Seller Certification",
			row.name,
			"creation",
			frappe.utils.now(),
			update_modified=False,
		)
		frappe.db.commit()
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(title="add_seller_cert beklenmeyen hata")
		frappe.throw(_("Sertifika eklenemedi. Lütfen alanları kontrol edin veya destek ekibine başvurun."))

	# Admin'lere bildirim — yeni doğrulama bekleyen belge
	try:
		_notify_admins_pending_cert(
			cert_name=certification_type,
			seller_name=frappe.db.get_value("Admin Seller Profile", profile_name, "seller_name")
			or profile_name,
			row_name=row.name,
		)
	except Exception:
		frappe.log_error(title="add_seller_cert: admin notify")

	# Cookie restore — response Set-Cookie ile sid değişmesin
	try:
		if hasattr(frappe.local, "cookie_manager"):
			cm = frappe.local.cookie_manager
			cm.cookies = _original_cookies
			cm.to_delete = _original_to_delete
	except Exception:
		pass

	return {
		"success": True,
		"name": row.name,
		"message": _("Sertifika eklendi. Admin doğrulamasını bekliyor."),
	}


@frappe.whitelist(methods=["POST"])
def update_seller_cert(
	row_name: str,
	certificate_number: str = "",
	issued_date: str | None = None,
	expiry_date: str | None = None,
	document: str = "",
) -> dict:
	"""Mağaza sertifikası düzenle (certification_type değiştirilemez).

	Düzenleme sonrası verification_status tekrar 'Pending' — admin re-verify gerekir.
	Belge zorunlu — boş bırakılamaz.

	Cookie protection: add_seller_cert ile aynı sid-bozulma riski (notify_admins
	içinde Notification doc.insert tetiklenebilir).
	"""
	profile_name = _require_seller_profile("cert.write")

	_original_cookies = {}
	_original_to_delete = []
	try:
		if hasattr(frappe.local, "cookie_manager"):
			cm = frappe.local.cookie_manager
			_original_cookies = dict(cm.cookies)
			_original_to_delete = list(cm.to_delete)
	except Exception:
		pass

	if not document or not str(document).strip():
		frappe.throw(_("Sertifika belgesi (PDF / JPG / PNG) zorunludur."))

	parent = frappe.db.get_value("Seller Certification", row_name, "parent")
	if parent != profile_name:
		frappe.throw(_("Bu sertifika satırını düzenleme yetkiniz yok."), frappe.PermissionError)

	frappe.local.flags.no_session_update = True
	try:
		frappe.db.set_value(
			"Seller Certification",
			row_name,
			{
				"certificate_number": certificate_number or None,
				"issued_date": issued_date or None,
				"expiry_date": expiry_date or None,
				"document": document or None,
				"verification_status": "Pending",
			},
		)
		frappe.db.commit()
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(title="update_seller_cert beklenmeyen hata")
		frappe.throw(_("Sertifika güncellenemedi. Lütfen alanları kontrol edin."))

	# Admin'lere bildirim — re-verify
	try:
		cert_type = frappe.db.get_value("Seller Certification", row_name, "certification_type")
		_notify_admins_pending_cert(
			cert_name=cert_type or "?",
			seller_name=frappe.db.get_value("Admin Seller Profile", profile_name, "seller_name")
			or profile_name,
			row_name=row_name,
		)
	except Exception:
		pass

	# Cookie restore — response Set-Cookie ile sid değişmesin
	try:
		if hasattr(frappe.local, "cookie_manager"):
			cm = frappe.local.cookie_manager
			cm.cookies = _original_cookies
			cm.to_delete = _original_to_delete
	except Exception:
		pass

	return {"success": True, "message": _("Sertifika güncellendi. Admin yeniden doğrulayacak.")}


@frappe.whitelist(methods=["POST"])
def delete_seller_cert(row_name: str) -> dict:
	"""Mağaza sertifikası sil.

	Eğer cert herhangi bir Listing'e atanmışsa, ilişkili atamalar da silinir.

	Cookie protection: delete_doc on_trash hook'larını tetikler — add_seller_cert
	ile aynı sid-bozulma riski.
	"""
	profile_name = _require_seller_profile("cert.write")

	_original_cookies = {}
	_original_to_delete = []
	try:
		if hasattr(frappe.local, "cookie_manager"):
			cm = frappe.local.cookie_manager
			_original_cookies = dict(cm.cookies)
			_original_to_delete = list(cm.to_delete)
	except Exception:
		pass

	parent = frappe.db.get_value("Seller Certification", row_name, "parent")
	if parent != profile_name:
		frappe.throw(_("Bu sertifika satırını silme yetkiniz yok."), frappe.PermissionError)

	cert_type = frappe.db.get_value("Seller Certification", row_name, "certification_type")

	frappe.local.flags.no_session_update = True

	# Listing atamalarını da kaldır
	if cert_type:
		seller_listings = frappe.get_all("Listing", filters={"seller_profile": profile_name}, pluck="name")
		if seller_listings:
			listing_cert_rows = frappe.get_all(
				"Listing Certification",
				filters={
					"parent": ["in", seller_listings],
					"parenttype": "Listing",
					"certification_type": cert_type,
				},
				pluck="name",
			)
			for r in listing_cert_rows:
				try:
					frappe.delete_doc("Listing Certification", r, ignore_permissions=True)
				except Exception:
					frappe.log_error(title=f"delete_seller_cert: child {r}")

	frappe.delete_doc("Seller Certification", row_name, ignore_permissions=True)
	frappe.db.commit()

	# Cookie restore — response Set-Cookie ile sid değişmesin
	try:
		if hasattr(frappe.local, "cookie_manager"):
			cm = frappe.local.cookie_manager
			cm.cookies = _original_cookies
			cm.to_delete = _original_to_delete
	except Exception:
		pass

	return {"success": True, "message": _("Sertifika silindi. Bağlı ürün atamaları da kaldırıldı.")}


# ──────────────────────────────────────────────────────────────────────────
# Listing cert — Tek atama + düzenleme + toplu
# ──────────────────────────────────────────────────────────────────────────


def _validate_listing_assignment_prereq(profile_name: str, listing_name: str, cert_type: str) -> None:
	"""Listing'e cert atamak için ön kontroller."""
	# Listing satıcıya ait mi?
	owner = frappe.db.get_value("Listing", listing_name, "seller_profile")
	if owner != profile_name:
		frappe.throw(_("Bu ürünü yönetme yetkiniz yok: {0}").format(listing_name), frappe.PermissionError)

	# Cert Type Approved + Product
	ct = frappe.db.get_value("Certification Type", cert_type, ["status", "category"], as_dict=True)
	if not ct or ct.status != "Approved":
		frappe.throw(_("Sadece onaylanmış sertifika tipleri atanabilir."))
	if ct.category != "Product":
		frappe.throw(_("Mağaza sertifikası ürüne atanamaz. Kategori 'Product' olmalı."))

	# Parent mağaza cert Verified mi?
	parent_cert = frappe.db.get_value(
		"Seller Certification",
		{
			"parent": profile_name,
			"parenttype": "Admin Seller Profile",
			"certification_type": cert_type,
		},
		["name", "verification_status"],
		as_dict=True,
	)
	if not parent_cert:
		frappe.throw(
			_(
				"'{0}' sertifikası mağaza havuzunuzda yok. Önce 'Sertifikalarım > "
				"Mağaza Sertifikalarım'a ekleyin."
			).format(cert_type)
		)
	if parent_cert.verification_status != "Verified":
		frappe.throw(
			_(
				"'{0}' mağaza sertifikanız henüz doğrulanmamış (durum: {1}). "
				"Doğrulandıktan sonra ürünlere atayabilirsiniz."
			).format(cert_type, parent_cert.verification_status or "Pending")
		)


@frappe.whitelist(methods=["POST"])
def add_listing_cert(
	listing_name: str,
	certification_type: str,
	issued_date: str | None = None,
	expiry_date: str | None = None,
) -> dict:
	"""Listing'e tek bir sertifika ata — tek tek atama UI'sı."""
	profile_name = _require_seller_profile("cert.write")
	_validate_listing_assignment_prereq(profile_name, listing_name, certification_type)

	# Aynı cert daha önce atanmış mı?
	exists = frappe.db.exists(
		"Listing Certification",
		{
			"parent": listing_name,
			"parenttype": "Listing",
			"certification_type": certification_type,
		},
	)
	if exists:
		frappe.throw(
			_("'{0}' bu ürüne zaten atanmış. Düzenlemek için cert rozetine tıklayın.").format(
				certification_type
			)
		)

	try:
		listing = frappe.get_doc("Listing", listing_name)
		row = listing.append(
			"product_certifications",
			{
				"certification_type": certification_type,
				"issued_date": issued_date,
				"expiry_date": expiry_date,
			},
		)
		listing.save(ignore_permissions=True)
		frappe.db.commit()
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(title="add_listing_cert beklenmeyen hata")
		frappe.throw(_("Sertifika atanamadı. Lütfen tekrar deneyin."))

	return {"success": True, "name": row.name, "message": _("Sertifika atandı.")}


@frappe.whitelist(methods=["POST"])
def update_listing_cert(
	row_name: str,
	issued_date: str | None = None,
	expiry_date: str | None = None,
) -> dict:
	"""Listing cert atamasını düzenle (tarih override)."""
	profile_name = _require_seller_profile("cert.write")

	row = frappe.db.get_value(
		"Listing Certification",
		row_name,
		["parent", "parenttype"],
		as_dict=True,
	)
	if not row or row.parenttype != "Listing":
		frappe.throw(_("Sertifika satırı bulunamadı."))

	listing_seller = frappe.db.get_value("Listing", row.parent, "seller_profile")
	if listing_seller != profile_name:
		frappe.throw(_("Yetkiniz yok."), frappe.PermissionError)

	# Tarih kontrolü
	if issued_date and expiry_date:
		if getdate(expiry_date) < getdate(issued_date):
			frappe.throw(_("Bitiş tarihi verilme tarihinden önce olamaz."))

	try:
		frappe.db.set_value(
			"Listing Certification",
			row_name,
			{
				"issued_date": issued_date or None,
				"expiry_date": expiry_date or None,
			},
		)
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="update_listing_cert beklenmeyen hata")
		frappe.throw(_("Sertifika güncellenemedi."))

	return {"success": True, "message": _("Sertifika tarihleri güncellendi.")}


@frappe.whitelist(methods=["POST"])
def bulk_assign_listing_cert(
	listing_names: str,
	certification_type: str,
	issued_date: str | None = None,
	expiry_date: str | None = None,
) -> dict:
	"""Toplu atama — Verified parent mağaza cert şart."""
	profile_name = _require_seller_profile("cert.write")

	if isinstance(listing_names, str):
		listing_names = [n.strip() for n in listing_names.split(",") if n.strip()]
	if not listing_names:
		frappe.throw(_("En az bir ürün seçilmeli."))
	if not certification_type:
		frappe.throw(_("Sertifika tipi zorunludur."))

	# Cert + parent mağaza Verified kontrolleri (tek listing üzerinden yeterli)
	# Çünkü cert type ve parent mağaza tüm listing'ler için aynı
	_validate_listing_assignment_prereq(profile_name, listing_names[0], certification_type)

	# Yetki kontrolü
	owned = frappe.get_all(
		"Listing",
		filters={"name": ["in", listing_names], "seller_profile": profile_name},
		pluck="name",
	)
	owned_set = set(owned)
	rejected = [n for n in listing_names if n not in owned_set]
	if rejected:
		frappe.throw(
			_("Bu ürünleri yönetme yetkiniz yok: {0}").format(", ".join(rejected[:5])),
			frappe.PermissionError,
		)

	added = 0
	skipped = 0
	for listing_name in owned:
		exists = frappe.db.exists(
			"Listing Certification",
			{
				"parent": listing_name,
				"parenttype": "Listing",
				"certification_type": certification_type,
			},
		)
		if exists:
			skipped += 1
			continue

		listing = frappe.get_doc("Listing", listing_name)
		listing.append(
			"product_certifications",
			{
				"certification_type": certification_type,
				"issued_date": issued_date,
				"expiry_date": expiry_date,
			},
		)
		listing.save(ignore_permissions=True)
		added += 1

	frappe.db.commit()
	return {
		"success": True,
		"added": added,
		"skipped": skipped,
		"message": _("{0} ürüne atandı, {1} zaten atanmıştı.").format(added, skipped),
	}


@frappe.whitelist(methods=["POST"])
def bulk_remove_listing_cert(listing_names: str, certification_type: str) -> dict:
	"""Birden fazla listing'ten aynı sertifikayı kaldırır."""
	profile_name = _require_seller_profile("cert.write")

	if isinstance(listing_names, str):
		listing_names = [n.strip() for n in listing_names.split(",") if n.strip()]
	if not listing_names:
		frappe.throw(_("En az bir ürün seçilmeli."))
	if not certification_type:
		frappe.throw(_("Sertifika tipi zorunludur."))

	owned = frappe.get_all(
		"Listing",
		filters={"name": ["in", listing_names], "seller_profile": profile_name},
		pluck="name",
	)
	if not owned:
		frappe.throw(_("Yetkiniz yok."), frappe.PermissionError)

	rows = frappe.get_all(
		"Listing Certification",
		filters={
			"parent": ["in", owned],
			"parenttype": "Listing",
			"certification_type": certification_type,
		},
		pluck="name",
	)

	removed = 0
	for row_name in rows:
		try:
			frappe.delete_doc("Listing Certification", row_name, ignore_permissions=True)
			removed += 1
		except Exception:
			frappe.log_error(title=f"bulk_remove_listing_cert: {row_name}")

	frappe.db.commit()
	return {
		"success": True,
		"removed": removed,
		"message": _("{0} üründen sertifika kaldırıldı.").format(removed),
	}


@frappe.whitelist(methods=["POST"])
def remove_listing_cert(row_name: str) -> dict:
	"""Listing'den ürün sertifikası tek tek kaldır (× butonu)."""
	profile_name = _require_seller_profile("cert.write")

	row = frappe.db.get_value(
		"Listing Certification",
		row_name,
		["parent", "parenttype"],
		as_dict=True,
	)
	if not row or row.parenttype != "Listing":
		frappe.throw(_("Sertifika satırı bulunamadı."))

	listing_seller = frappe.db.get_value("Listing", row.parent, "seller_profile")
	if listing_seller != profile_name:
		frappe.throw(_("Yetkiniz yok."), frappe.PermissionError)

	frappe.delete_doc("Listing Certification", row_name, ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "message": _("Sertifika kaldırıldı.")}


# ──────────────────────────────────────────────────────────────────────────
# Admin verify endpoint'leri
# ──────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def list_pending_seller_certs() -> dict:
	"""Admin: doğrulama bekleyen mağaza cert'lerinin listesi."""
	_require_admin()

	rows = frappe.db.sql(
		"""
		SELECT
			sc.name AS row_name,
			sc.parent AS seller_profile,
			sc.certification_type,
			sc.category,
			sc.issued_date,
			sc.expiry_date,
			sc.document,
			sc.verification_status,
			sc.rejection_reason,
			sc.creation,
			sc.modified,
			asp.seller_name,
			asp.user AS seller_user
		FROM `tabSeller Certification` sc
		INNER JOIN `tabAdmin Seller Profile` asp ON asp.name = sc.parent
		WHERE sc.parenttype = 'Admin Seller Profile'
			AND IFNULL(sc.verification_status, 'Pending') = 'Pending'
		ORDER BY sc.creation ASC
		""",
		as_dict=True,
	)

	return {"data": rows, "total": len(rows)}


@frappe.whitelist(methods=["POST"])
def verify_seller_cert(row_name: str) -> dict:
	"""Admin: belgeyi doğrular."""
	_require_admin()

	row = frappe.db.get_value(
		"Seller Certification",
		row_name,
		["parent", "certification_type", "verification_status"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Sertifika satırı bulunamadı."))
	if row.verification_status == "Verified":
		frappe.throw(_("Bu sertifika zaten doğrulanmış."))

	frappe.db.set_value(
		"Seller Certification",
		row_name,
		{"verification_status": "Verified", "rejection_reason": None},
	)
	frappe.db.commit()

	# Satıcıya bildirim
	try:
		seller_user = frappe.db.get_value("Admin Seller Profile", row.parent, "user")
		if seller_user and seller_user not in ("Guest", "Administrator"):
			from tradehub_core.utils.notify import notify

			notify(
				recipient_user=seller_user,
				type="certification",
				title=_("Sertifikanız doğrulandı"),
				message=_(
					"'{0}' sertifikanız admin tarafından doğrulandı. Artık ürünlere atayabilir ve storefront'ta gösterebilirsiniz."
				).format(row.certification_type),
				recipient_role="seller",
				action_url="/panel/my-certifications#seller",
				reference_doctype="Admin Seller Profile",
				reference_name=row.parent,
			)
	except Exception:
		frappe.log_error(title="verify_seller_cert: seller notify")

	return {"success": True, "message": _("Sertifika doğrulandı.")}


@frappe.whitelist(methods=["POST"])
def reject_seller_cert(row_name: str, reason: str = "") -> dict:
	"""Admin: belgeyi reddet (sebep zorunlu)."""
	_require_admin()

	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Reddetme sebebi zorunludur."))

	row = frappe.db.get_value(
		"Seller Certification",
		row_name,
		["parent", "certification_type", "verification_status"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Sertifika satırı bulunamadı."))

	frappe.db.set_value(
		"Seller Certification",
		row_name,
		{"verification_status": "Rejected", "rejection_reason": reason},
	)
	frappe.db.commit()

	# Satıcıya bildirim
	try:
		seller_user = frappe.db.get_value("Admin Seller Profile", row.parent, "user")
		if seller_user and seller_user not in ("Guest", "Administrator"):
			from tradehub_core.utils.notify import notify

			notify(
				recipient_user=seller_user,
				type="certification",
				title=_("Sertifikanız reddedildi"),
				message=_("'{0}' sertifikanız reddedildi. Sebep: {1}").format(row.certification_type, reason),
				recipient_role="seller",
				action_url="/panel/my-certifications#seller",
				reference_doctype="Admin Seller Profile",
				reference_name=row.parent,
			)
	except Exception:
		frappe.log_error(title="reject_seller_cert: seller notify")

	return {"success": True, "message": _("Sertifika reddedildi.")}


# ──────────────────────────────────────────────────────────────────────────
# Excel export/import — P3
# ──────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def export_listing_cert_matrix() -> dict:
	"""Cert atama matrisini JSON olarak dön — frontend Excel olarak indirir."""
	profile_name = _require_seller_profile()

	listings = frappe.get_all(
		"Listing",
		filters={"seller_profile": profile_name},
		fields=["name", "title"],
		order_by="title ASC",
	)
	listing_names = [l["name"] for l in listings]

	cert_rows = frappe.get_all(
		"Listing Certification",
		filters={"parent": ["in", listing_names or [""]], "parenttype": "Listing"},
		fields=["parent", "certification_type", "issued_date", "expiry_date"],
	)

	cert_types_in_use = sorted({r["certification_type"] for r in cert_rows})

	# Matrix: rows = listings, columns = cert types
	matrix = []
	for l in listings:
		row = {"name": l["name"], "title": l["title"]}
		for ct in cert_types_in_use:
			match = next(
				(r for r in cert_rows if r["parent"] == l["name"] and r["certification_type"] == ct),
				None,
			)
			if match:
				row[ct] = f"✓ ({match.get('expiry_date') or '-'})"
			else:
				row[ct] = ""
		matrix.append(row)

	return {
		"columns": ["Ürün", "Ürün Adı"] + cert_types_in_use,
		"data": matrix,
	}


# ──────────────────────────────────────────────────────────────────────────
# Notify helpers
# ──────────────────────────────────────────────────────────────────────────


def _notify_admins_pending_cert(cert_name: str, seller_name: str, row_name: str) -> None:
	"""System Manager rolüne sahip aktif kullanıcılara bildirim — dedup'lu."""
	from tradehub_core.utils.notify import notify

	admins = frappe.db.sql(
		"""
		SELECT DISTINCT u.name
		FROM `tabUser` u
		INNER JOIN `tabHas Role` hr ON hr.parent = u.name AND hr.parenttype = 'User'
		WHERE u.enabled = 1
			AND hr.role = 'System Manager'
			AND u.name NOT IN ('Administrator', 'Guest')
		""",
		as_dict=True,
	)
	for a in admins:
		notify(
			recipient_user=a.name,
			type="certification",
			title=_("Doğrulama bekleyen sertifika"),
			message=_("'{0}' sertifikası ({1} mağazası) admin doğrulaması bekliyor.").format(
				cert_name, seller_name
			),
			recipient_role="admin",
			action_url="/panel/admin/cert-verification",
			reference_doctype="Seller Certification",
			reference_name=row_name,
		)

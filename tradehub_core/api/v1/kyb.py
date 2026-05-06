import base64
import io
import zipfile

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

SELLER_TYPE_MAP = {
	"Individual": "Şahıs",
	"Business": "Limited Şirket",
	"Enterprise": "Anonim Şirket",
}

# ── KYB Document Format Whitelist ────────────────────────────────
#
# Yalnızca aşağıdaki formatlar kabul edilir. Magic-byte doğrulaması
# extension spoofing'e karşı korumayı sağlar (örn. .pdf uzantılı .exe).
KYB_ALLOWED_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".docx")
KYB_MAX_BYTES = 10 * 1024 * 1024  # 10 MB hard cap


def _detect_format(content: bytes, filename_lower: str) -> str:
	"""Detect file format by magic bytes. Returns the canonical extension
	(e.g. ".pdf"), or raises ValidationError if format is not supported or
	content does not match its claimed extension."""
	if len(content) < 12:
		frappe.throw(_("Geçersiz dosya: içerik çok kısa."), frappe.ValidationError)

	# PDF: %PDF-
	if content[:5] == b"%PDF-":
		return ".pdf"

	# JPEG: FF D8 FF
	if content[:3] == b"\xff\xd8\xff":
		return ".jpg" if filename_lower.endswith(".jpg") else ".jpeg"

	# PNG: 89 50 4E 47 0D 0A 1A 0A
	if content[:8] == b"\x89PNG\r\n\x1a\n":
		return ".png"

	# WEBP: RIFF....WEBP (byte 0-3 = RIFF, byte 8-11 = WEBP)
	if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
		return ".webp"

	# DOCX: ZIP magic (PK\x03\x04) + içeride [Content_Types].xml + word/ klasörü
	# Sadece ZIP magic yetmez — kullanıcı .zip'i .docx uzantılı yükleyebilir.
	if content[:4] == b"PK\x03\x04":
		try:
			with zipfile.ZipFile(io.BytesIO(content)) as zf:
				names = zf.namelist()
				if "[Content_Types].xml" in names and any(
					n.startswith("word/") for n in names
				):
					return ".docx"
		except zipfile.BadZipFile:
			pass

	# Hangi format tespit edildi? Kullanıcıya net bilgi
	first_bytes = content[:4].hex().upper() if len(content) >= 4 else "??"
	frappe.throw(
		_(
			"Dosyanızın gerçek formatı, uzantısıyla eşleşmiyor. "
			"Yüklediğiniz {0} dosyasının ilk byte'ları: {1}. "
			"Yalnızca gerçek PDF, JPG, JPEG, PNG, WEBP, DOCX dosyaları kabul edilir. "
			"Lütfen orijinal dosyayı yükleyin (uzantısı sahte olmayan)."
		).format(filename_lower, first_bytes),
		frappe.ValidationError,
	)


def _get_seller_data(user: str) -> dict:
	"""Fetch existing seller data to pre-fill KYB form.

	Seller Application kayıt sırasındaki kullanıcı verisini taşır (en doğru
	kaynak). Seller Profile sonradan farklı amaçla güncellenebilir
	(business_name'i ad-soyad ile karışmış olabilir). Bu yüzden **SA önceliklidir**;
	SA boşsa SP fallback olur.
	"""
	sa = frappe.db.get_value(
		"Seller Application",
		{"applicant_user": user},
		["business_name", "seller_type", "tax_id", "tax_id_type", "tax_office"],
		as_dict=True,
	) or {}

	sp = frappe.db.get_value(
		"Seller Profile",
		{"user": user},
		["seller_name", "seller_type", "business_name", "tax_id", "tax_id_type", "tax_office"],
		as_dict=True,
	) or {}

	# SA öncelik, SP fallback
	business_name = sa.get("business_name") or sp.get("business_name") or ""
	seller_type = sa.get("seller_type") or sp.get("seller_type") or ""
	tax_id = sa.get("tax_id") or sp.get("tax_id") or ""
	tax_id_type = sa.get("tax_id_type") or sp.get("tax_id_type") or "TCKN"
	tax_office = sa.get("tax_office") or sp.get("tax_office") or ""
	authorized_person = sp.get("seller_name") or ""

	return {
		"company_title": business_name,
		"business_type": SELLER_TYPE_MAP.get(seller_type, "") or seller_type or "",
		"authorized_person": authorized_person,
		"tax_id_type": tax_id_type,
		"tax_id": tax_id,
		"tax_office": tax_office,
	}


@frappe.whitelist(methods=["GET"])
def get_kyb_status():
	"""Return KYB verification status and data for the current user.

	If no KYB record exists, auto-creates one pre-filled from Seller Profile.
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	# Check if seller
	if not frappe.db.exists("Seller Profile", {"user": user}):
		return {"exists": False, "status": None, "message": "Not a seller"}

	existing = frappe.db.get_value("KYB Verification", {"user": user}, "name")

	if not existing:
		# Auto-create KYB record pre-filled from Seller Application/Profile.
		# 6 belge reqd:1 — kullanıcı henüz yüklemedi; ignore_mandatory ile bypass.
		# Belgeler submit_kyb_documents endpoint'inde Türkçe validation ile kontrol edilir.
		seller_data = _get_seller_data(user)
		doc = frappe.new_doc("KYB Verification")
		doc.user = user
		doc.owner = user
		doc.status = "Pending"
		for field, value in seller_data.items():
			doc.set(field, value)
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		existing = doc.name
	else:
		# Eski kayıtlarda eksik alanları SA/SP'den idempotent doldur.
		# Sadece KYB.field BOŞ ise SP/SA'dan değer alır; mevcut değerleri ezmez.
		seller_data = _get_seller_data(user)
		doc = frappe.get_doc("KYB Verification", existing)
		changed = False
		for field, value in seller_data.items():
			current = doc.get(field) or ""
			if not current and value:
				doc.set(field, value)
				changed = True
		if changed:
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)
			frappe.db.commit()

	kyb = frappe.db.get_value(
		"KYB Verification",
		existing,
		[
			"name",
			"status",
			"company_title",
			"business_type",
			"authorized_person",
			"tax_id_type",
			"tax_id",
			"tax_office",
			"trade_registry_number",
			"rejection_reason",
			"verified_at",
			"identity_document",
			"imza_sirkuleri",
			"ticaret_sicil_gazetesi",
			"faaliyet_belgesi",
			"vergi_levhasi",
			"bank_account_document",
			"document_expiry_date",
		],
		as_dict=True,
	)

	return {
		"exists": True,
		"name": kyb.name,
		"status": kyb.status,
		"company_title": kyb.company_title or "",
		"business_type": kyb.business_type or "",
		"authorized_person": kyb.authorized_person or "",
		"identity_document": kyb.identity_document or "",
		"imza_sirkuleri": kyb.imza_sirkuleri or "",
		"ticaret_sicil_gazetesi": kyb.ticaret_sicil_gazetesi or "",
		"faaliyet_belgesi": kyb.faaliyet_belgesi or "",
		"vergi_levhasi": kyb.vergi_levhasi or "",
		"bank_account_document": kyb.bank_account_document or "",
		"document_expiry_date": (
			str(kyb.document_expiry_date) if kyb.document_expiry_date else ""
		),
		"tax_id_type": kyb.tax_id_type or "",
		"tax_id": kyb.tax_id or "",
		"tax_office": kyb.tax_office or "",
		"trade_registry_number": kyb.trade_registry_number or "",
		"rejection_reason": kyb.rejection_reason if kyb.status == "Rejected" else None,
		"verified_at": kyb.verified_at,
	}


@frappe.whitelist(methods=["POST"])
@rate_limit(key="user", limit=1, seconds=60)
def submit_kyb_documents(
	company_title: str,
	business_type: str = "",
	authorized_person: str = "",
	tax_id_type: str = "",
	tax_id: str = "",
	tax_office: str = "",
	trade_registry_number: str = "",
	identity_document: str = "",
	imza_sirkuleri: str = "",
	ticaret_sicil_gazetesi: str = "",
	faaliyet_belgesi: str = "",
	vergi_levhasi: str = "",
	bank_account_document: str = "",
	document_expiry_date: str = "",
):
	"""KYB belgelerini gönder veya yeniden gönder.

	İlk başvuru: Yeni KYB Verification oluşturulur, status="Pending".

	Resubmit (mevcut kayıt var):
	- Sadece status="Rejected" iken status "Pending"e döner. Verified veya
	  Under Review durumda dokunulmaz (sahte status flicker önlenir).
	- Sadece **belge field'larından en az biri değişmişse** Pending'e dönüş
	  tetiklenir; data alanlarının tek başına güncellenmesi status değiştirmez.
	- Throttle: Aynı kullanıcı 5 dakikada en fazla 1 kez resubmit edebilir
	  (decorator). Spam'a karşı.
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	if not company_title:
		frappe.throw(_("Company title is required."), frappe.ValidationError)

	# ── Zorunlu belge kontrolü ───────────────────────────────────────
	# Frontend bypass'ına karşı son söz; admin paneldeki reqd:1 ile
	# çift kontrol. Eksik dosyalar Türkçe label'larıyla raporlanır.
	required_documents = [
		("identity_document", identity_document, "Kimlik Belgesi"),
		("imza_sirkuleri", imza_sirkuleri, "İmza Sirküleri"),
		("ticaret_sicil_gazetesi", ticaret_sicil_gazetesi, "Ticaret Sicil Gazetesi"),
		("faaliyet_belgesi", faaliyet_belgesi, "Faaliyet Belgesi"),
		("vergi_levhasi", vergi_levhasi, "Vergi Levhası"),
		("bank_account_document", bank_account_document, "Banka Hesap Belgesi"),
	]
	missing = [label for _fname, value, label in required_documents if not (value or "").strip()]
	if missing:
		frappe.throw(
			_("Eksik belge: {0}").format(", ".join(missing)),
			frappe.ValidationError,
		)

	existing = frappe.db.get_value("KYB Verification", {"user": user}, "name")

	# permlevel 1 fields (tax_id_type, tax_id, tax_office, business_type)
	# are NOT accepted from seller — they come from Seller Profile at creation.
	# Only admin can change them via Frappe Desk.
	field_data = {
		"company_title": company_title,
		"authorized_person": authorized_person,
		"trade_registry_number": trade_registry_number,
		"identity_document": identity_document,
		"imza_sirkuleri": imza_sirkuleri,
		"ticaret_sicil_gazetesi": ticaret_sicil_gazetesi,
		"faaliyet_belgesi": faaliyet_belgesi,
		"vergi_levhasi": vergi_levhasi,
		"bank_account_document": bank_account_document,
		"document_expiry_date": document_expiry_date or None,
	}

	if existing:
		doc = frappe.get_doc("KYB Verification", existing)

		# Belge field'larından herhangi biri değişti mi?
		document_fields = (
			"identity_document",
			"imza_sirkuleri",
			"ticaret_sicil_gazetesi",
			"faaliyet_belgesi",
			"vergi_levhasi",
			"bank_account_document",
		)
		documents_changed = any(
			(doc.get(f) or "") != (field_data.get(f) or "") for f in document_fields
		)

		# Field'ları yaz
		for field, value in field_data.items():
			doc.set(field, value)

		# Resubmit kuralları:
		# - Sadece Rejected → Pending (Verified/Under Review/Pending dokunulmaz)
		# - Sadece belge değişikliği status flicker'ını tetikler
		previous_status = doc.status
		status_changed_to_pending = False
		if previous_status == "Rejected" and documents_changed:
			doc.status = "Pending"
			status_changed_to_pending = True

		doc.save(ignore_permissions=True)
		frappe.db.commit()
		return {
			"success": True,
			"name": existing,
			"status": doc.status,
			"updated": True,
			"resubmitted": status_changed_to_pending,
			"previous_status": previous_status,
		}
	else:
		doc = frappe.new_doc("KYB Verification")
		doc.user = user
		doc.owner = user
		doc.status = "Pending"
		for field, value in field_data.items():
			doc.set(field, value)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return {
			"success": True,
			"name": doc.name,
			"status": "Pending",
			"updated": False,
			"resubmitted": False,
		}


@frappe.whitelist(methods=["POST"])
def review_kyb(
	kyb_name: str,
	action: str,
	rejection_reason: str = "",
	notes: str = "",
):
	"""Admin aksiyonu: KYB durumunu güncelle.

	Kabul edilen action'lar: Pending, Under Review, Verified, Rejected, Expired.
	Pending'e çekme = "yeniden incele" (önceki inceleme metadata'sı sıfırlanır).
	Expired'a çekme = "belge süresi doldu, tekrar yüklensin".
	Rejected aksiyonu rejection_reason'ı yazar (min 20 karakter zorunlu).

	``notes`` opsiyonel: admin-only internal not (permlevel:2). Verilirse
	mevcut notes alanına tarih+admin damgalı APPEND edilir (eski notlar korunur).
	"""
	user = frappe.session.user
	roles = frappe.get_roles(user)

	if "System Manager" not in roles and "Marketplace Admin" not in roles:
		frappe.throw(_("Not authorized."), frappe.PermissionError)

	if action not in ("Pending", "Under Review", "Verified", "Rejected", "Expired"):
		frappe.throw(_("Invalid action."), frappe.ValidationError)

	# Reject için rejection_reason zorunlu ve min 20 karakter
	if action == "Rejected":
		reason_clean = (rejection_reason or "").strip()
		if len(reason_clean) < 20:
			frappe.throw(
				_(
					"Reddetme gerekçesi en az 20 karakter olmalı; satıcıya net "
					"bir eylem önerisi verin."
				),
				frappe.ValidationError,
			)

	doc = frappe.get_doc("KYB Verification", kyb_name)
	doc.status = action
	if action == "Rejected":
		doc.rejection_reason = rejection_reason

	# Notes append (opsiyonel, internal admin not'u)
	notes_clean = (notes or "").strip()
	if notes_clean:
		from frappe.utils import now_datetime

		stamp = now_datetime().strftime("%Y-%m-%d %H:%M")
		entry = f"[{stamp}] {user} · {action}: {notes_clean}"
		existing = (doc.notes or "").strip()
		doc.notes = f"{existing}\n\n{entry}" if existing else entry

	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True, "status": doc.status}


@frappe.whitelist(methods=["POST"])
@rate_limit(key="user", limit=20, seconds=300)
def upload_kyb_document(filename: str = "", filedata: str = ""):
	"""KYB belge yükleme endpoint'i — extension whitelist + magic-byte
	doğrulaması + 10 MB cap + private storage.

	Standart Frappe ``upload_file`` endpoint'i format kontrolü yapmadığı için
	KYB belgeleri için bu endpoint kullanılır. Yüklenen dosya:
	  1. ``filedata`` base64 olarak gelir (data URI prefix opsiyonel).
	  2. Uzantı whitelist (KYB_ALLOWED_EXTENSIONS) kontrolü.
	  3. Magic-byte ile içerik doğrulaması (extension spoof'una karşı).
	  4. 10 MB hard cap.
	  5. ``is_private=1`` File doc oluşturulur.

	Returns: ``{"success": True, "file_url": "/private/files/..."}``.
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Oturum açılmamış."), frappe.AuthenticationError)

	if not filename or not filedata:
		frappe.throw(_("Dosya bilgisi eksik."), frappe.ValidationError)

	filename_lower = filename.lower()
	if not filename_lower.endswith(KYB_ALLOWED_EXTENSIONS):
		frappe.throw(
			_(
				"Geçersiz dosya türü. Yalnızca PDF, JPG, JPEG, PNG, WEBP, DOCX "
				"kabul edilir."
			),
			frappe.ValidationError,
		)

	if "," in filedata and filedata.startswith("data:"):
		filedata = filedata.split(",", 1)[1]

	try:
		content = base64.b64decode(filedata)
	except Exception:
		frappe.throw(_("Geçersiz dosya içeriği (base64 decode hatası)."), frappe.ValidationError)

	if len(content) > KYB_MAX_BYTES:
		frappe.throw(_("Dosya 10 MB'dan küçük olmalı."), frappe.ValidationError)

	# Magic-byte doğrulaması — uzantı spoof'unu engeller, ayrıca uzantı/içerik
	# tutarlılığını da kontrol eder.
	detected_ext = _detect_format(content, filename_lower)

	# Extension <-> magic-byte tutarlılığı kontrolü
	# (örn. .pdf yüklenip içerik PNG ise reddet)
	expected_match = {
		".pdf": (".pdf",),
		".jpg": (".jpg", ".jpeg"),
		".jpeg": (".jpg", ".jpeg"),
		".png": (".png",),
		".webp": (".webp",),
		".docx": (".docx",),
	}
	claimed_ext = "." + filename_lower.rsplit(".", 1)[-1]
	if detected_ext not in expected_match.get(claimed_ext, ()):
		frappe.throw(
			_("Dosya içeriği uzantıyla eşleşmiyor."),
			frappe.ValidationError,
		)

	# File doc'unu KYB Verification kaydına attach et — eğer kayıt yoksa
	# auto-create. File'ın User'a attach olması Frappe private file permission
	# kontrolünde Seller'ın 403 yemesine sebep oluyor; KYB Verification'a
	# attach olunca if_owner=1 sayesinde Seller kendi belgesine erişir.
	kyb_name = frappe.db.get_value("KYB Verification", {"user": user}, "name")
	if not kyb_name:
		# Auto-create boş KYB kaydı (SP/SA verisiyle önceden doldur).
		# Bu nokta tipik olarak satıcının ilk belge upload'ı — KYB doc henüz yok.
		# reqd:1 belge field'ları boş olduğu için ignore_mandatory ile bypass edilir.
		seller_data = _get_seller_data(user)
		kyb_doc = frappe.new_doc("KYB Verification")
		kyb_doc.user = user
		kyb_doc.owner = user
		kyb_doc.status = "Pending"
		for f, v in seller_data.items():
			kyb_doc.set(f, v)
		kyb_doc.flags.ignore_permissions = True
		kyb_doc.flags.ignore_mandatory = True
		kyb_doc.insert(ignore_permissions=True)
		frappe.db.commit()
		kyb_name = kyb_doc.name

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"content": content,
			"is_private": 1,
			"attached_to_doctype": "KYB Verification",
			"attached_to_name": kyb_name,
		}
	)
	file_doc.insert(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True, "file_url": file_doc.file_url, "file_name": file_doc.file_name}

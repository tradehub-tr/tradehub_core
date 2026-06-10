import json
import re
import secrets
import socket

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import now_datetime
from frappe.utils.password import check_password, update_password

from tradehub_core.api.v1.auth import _generate_member_id
from tradehub_core.utils.auth_guards import require_verified_email
from tradehub_core.utils.phone import canonicalize_phone

PASSWORD_MIN_LENGTH = 8
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

# Total wrong-OTP entries we accept before invalidating the code. Shared by all
# three OTP verify endpoints (registration, email change, email reverify) so the
# UX (kademeli aşama göstergesi) tells the same story everywhere.
OTP_MAX_ATTEMPTS = 5

# Tek seferlik / atılabilir e-posta sağlayıcı domainleri.
# Kayıt akışı bu domainlerden gelen adresleri reddeder.
DISPOSABLE_EMAIL_DOMAINS = frozenset(
	{
		"mailinator.com",
		"tempmail.com",
		"temp-mail.org",
		"10minutemail.com",
		"guerrillamail.com",
		"guerrillamail.info",
		"trashmail.com",
		"sharklasers.com",
		"yopmail.com",
		"throwawaymail.com",
		"getnada.com",
		"maildrop.cc",
		"mintemail.com",
		"dispostable.com",
		"fakeinbox.com",
		"mohmal.com",
		"emailondeck.com",
	}
)


def _is_disposable_email(email: str) -> bool:
	"""Return True if the domain matches the disposable blocklist."""
	if "@" not in email:
		return False
	domain = email.rsplit("@", 1)[1].lower().strip()
	return domain in DISPOSABLE_EMAIL_DOMAINS


# ── Helpers ────────────────────────────────────────────


def _domain_resolves(domain: str) -> bool:
	"""Quick check if a domain has DNS resolution (A record).

	Bu MX kontrolü değildir ama yaygın yazım hatalarını ("turksab.coms",
	"gmial.com" vb.) yakalar. Network çağrısı 50ms-2s sürebilir; fail-open
	(DNS hatası olursa True dön) — DNS kesintisinde kullanıcıyı bloklamayalım.
	"""
	try:
		# 2 saniye timeout — DNS yavaşsa kullanıcıyı uzun bekletme
		old_timeout = socket.getdefaulttimeout()
		socket.setdefaulttimeout(2)
		try:
			socket.gethostbyname(domain)
			return True
		finally:
			socket.setdefaulttimeout(old_timeout)
	except socket.gaierror:
		return False
	except Exception:
		# Diğer beklenmeyen network hataları — fail-open
		return True


def _validate_email_format(email: str) -> str:
	"""Return lowered-trimmed email or throw 400.

	Doğrulamalar:
	  1. Regex format
	  2. Disposable blocklist
	  3. Domain DNS resolve kontrolü (A record) — yazım hatalarını yakalar
	"""
	email = (email or "").strip().lower()
	if not _EMAIL_RE.match(email):
		frappe.local.response["http_status_code"] = 400
		frappe.throw(_("Please enter a valid email address."), frappe.ValidationError)
	if _is_disposable_email(email):
		frappe.local.response["http_status_code"] = 400
		frappe.throw(
			_("Disposable email addresses are not allowed. Please use a permanent email."),
			frappe.ValidationError,
		)
	# Domain DNS kontrolü (yazım hatalarını yakala)
	domain = email.rsplit("@", 1)[1]
	if not _domain_resolves(domain):
		frappe.local.response["http_status_code"] = 400
		frappe.throw(
			_("The email domain could not be reached. Please check your email address."),
			frappe.ValidationError,
		)
	return email


def _validate_password(password: str):
	"""Enforce password policy: 8+ chars, uppercase, lowercase, digit."""
	if len(password) < PASSWORD_MIN_LENGTH:
		frappe.throw(_("Password must be at least {0} characters.").format(PASSWORD_MIN_LENGTH))
	if not re.search(r"[A-Z]", password):
		frappe.throw(_("Password must contain at least one uppercase letter."))
	if not re.search(r"[a-z]", password):
		frappe.throw(_("Password must contain at least one lowercase letter."))
	if not re.search(r"[0-9]", password):
		frappe.throw(_("Password must contain at least one digit."))


def _generate_otp() -> str:
	"""Generate a cryptographically secure 6-digit OTP."""
	return "".join([str(secrets.randbelow(10)) for _ in range(6)])


def _reassign_file_owner(file_url: str, new_owner: str):
	"""Reassign file owner from Guest to actual user after registration."""
	if not file_url:
		return
	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if file_name:
		frappe.db.set_value("File", file_name, "owner", new_owner)


def _log_email_verification_event(
	user: str,
	event: str,
	method: str = None,
	actor: str = None,
	reason: str = None,
):
	"""Append an entry to the Email Verification Log audit trail.

	Silently no-ops when the DocType has not yet been migrated, so older
	deployments keep working until the post-model-sync patch runs.
	"""
	try:
		if not frappe.db.exists("DocType", "Email Verification Log"):
			return
		log = frappe.new_doc("Email Verification Log")
		log.user = user
		log.event = event
		if method:
			log.method = method
		log.actor = actor or frappe.session.user
		if reason:
			log.reason = reason
		try:
			log.ip_address = frappe.local.request_ip
		except Exception:
			pass
		try:
			ua = frappe.get_request_header("User-Agent") if frappe.local.request else None
			if ua:
				log.user_agent = ua[:500]
		except Exception:
			pass
		log.flags.ignore_permissions = True
		log.insert(ignore_permissions=True)
	except Exception:
		# Audit log failure should never break the main flow.
		frappe.log_error(
			title="Email Verification Log write failed",
			message=frappe.get_traceback(),
		)


def _create_email_verification(email: str, first_name: str):
	"""DEPRECATED — eski post-registration link akışı.

	Pattern A (OTP-only) sonrası kayıt sırasında çağrılmaz. Yalnızca eski
	maillerden gelen `verify_email?key=...` linklerinin TTL süresince çalışmasını
	sağlamak için Redis key seti hâlâ duruyor. ``resend_verification_email``
	çağrılırsa OTP-temelli yeni akışa düşer.
	"""
	key = frappe.generate_hash(length=32)
	frappe.cache.set_value(f"email_verification:{key}", email, expires_in_sec=86400)
	storefront = frappe.conf.get("storefront_url", "https://rc.istoc.com")
	link = f"{storefront}/api/method/tradehub_core.api.v1.identity.verify_email?key={key}"

	frappe.sendmail(
		recipients=email,
		subject="iSTOC — Email Adresinizi Doğrulayın",
		template="tradehub_email_verification",
		args={"link": link, "first_name": first_name},
		now=True,
		communication=False,
	)


# ── Endpoints ──────────────────────────────────────────


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="email", limit=5, seconds=300)
def send_registration_otp(email: str):
	"""Send a 6-digit OTP to the given email for registration verification.

	Errors:
	  400 — invalid email format
	  409 — email already registered
	  429 — rate limit exceeded
	"""
	email = _validate_email_format(email)

	if frappe.db.exists("User", email):
		frappe.local.response["http_status_code"] = 409
		frappe.throw(
			_("An account with this email already exists."),
			frappe.DuplicateEntryError,
		)

	otp_code = _generate_otp()

	# Store OTP in Redis — overwrites any previous OTP for this email
	frappe.cache.set_value(
		f"registration_otp:{email}",
		json.dumps({"code": otp_code, "attempts": 0}),
		expires_in_sec=600,
	)

	frappe.sendmail(
		recipients=email,
		subject="iSTOC — Kayıt Doğrulama Kodu",
		template="registration_otp",
		args={"code": otp_code},
		now=True,
		communication=False,
	)

	return {"success": True, "expires_in_minutes": 10}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="email", limit=5, seconds=300)
def verify_registration_otp(email: str, code: str):
	"""Verify the 6-digit OTP and return a registration_token on success.

	Errors:
	  404 — OTP not found or expired
	  401 — wrong code
	  429 — too many wrong attempts (5+)
	"""
	email = (email or "").strip().lower()
	code = (code or "").strip()

	cache_key = f"registration_otp:{email}"
	cached = frappe.cache.get_value(cache_key)

	if not cached:
		frappe.local.response["http_status_code"] = 404
		frappe.throw(
			_("Verification code not found or expired."),
			frappe.DoesNotExistError,
		)

	otp_data = json.loads(cached) if isinstance(cached, str) else cached

	# Too many wrong attempts — invalidate the OTP
	if otp_data.get("attempts", 0) >= OTP_MAX_ATTEMPTS:
		frappe.cache.delete_value(cache_key)
		frappe.local.response["http_status_code"] = 429
		frappe.local.response["attempts_remaining"] = 0
		frappe.throw(
			_("Too many wrong attempts. Please request a new code."),
			frappe.TooManyRequestsError,
		)

	# Wrong code — increment attempts
	if code != otp_data["code"]:
		otp_data["attempts"] = otp_data.get("attempts", 0) + 1
		frappe.cache.set_value(
			cache_key,
			json.dumps(otp_data),
			expires_in_sec=600,
		)
		# Frontend uses this to render the staged "Kalan deneme" UX; capped at 0
		# so the lockout case stays consistent with the 429 branch above.
		frappe.local.response["http_status_code"] = 422
		frappe.local.response["attempts_remaining"] = max(0, OTP_MAX_ATTEMPTS - otp_data["attempts"])
		frappe.throw(
			_("Wrong verification code."),
			frappe.ValidationError,
		)

	# Code matches — generate registration_token
	# 60 min TTL to allow time for supplier setup form
	registration_token = frappe.generate_hash(length=32)
	frappe.cache.set_value(
		f"registration_token:{registration_token}",
		email,
		expires_in_sec=3600,
	)

	# Delete OTP (single-use)
	frappe.cache.delete_value(cache_key)

	return {"success": True, "registration_token": registration_token}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="email", limit=5, seconds=3600)
def register_user(
	email: str,
	password: str,
	first_name: str,
	last_name: str,
	registration_type: str = "Alici",
	account_type: str = "Individual",
	phone: str = "",
	country: str = "Turkey",
	company_name: str = "",
	tax_id: str = "",
	tax_id_type: str = "",
	tax_office: str = "",
	accept_terms: bool = False,
	accept_kvkk: bool = False,
	registration_token: str = "",
):
	"""Sprint 2.6 — Hesap Oluştur ekranı: Alıcı kayıt akışı.

	registration_type:
	  - "Alici" (default) — Bu endpoint Alıcı kayıt akışı için. Satıcı kayıt için
	    register_supplier kullanılmalı. Bu parametre ileri uyumluluk için.

	account_type:
	  - "Individual" / "Business" — Sprint 2.6'da KYC formunda toggle ile set
	    ediliyor. Bu parametre backward compat için kabul edilir ama KYC submit
	    sırasında User Profile.account_type tekrar yazılır.

	Sprint 2.6 davranışı:
	  - Tüm Alıcılar için kyc_status="Pending" set edilir (Soru 1 cevabı).
	  - kyb_status="Locked" — Satıcı başvurusu yapılana kadar kilitli (Soru 6).

	The registration_token must have been obtained from verify_registration_otp().
	"""
	email = _validate_email_format(email)

	# Sprint 2.6 — Alıcı endpoint'i; Satıcı için register_supplier
	if registration_type not in ("Alici", "Satici"):
		registration_type = "Alici"
	if registration_type == "Satici":
		frappe.throw(
			_("Satıcı kaydı için /api/method/...register_supplier endpoint'i kullanılmalı."),
			frappe.ValidationError,
		)

	# Sprint 2 — account_type normalize (backward compat for legacy "buyer"/"supplier")
	legacy_map = {"buyer": "Individual", "supplier": "Business", "seller": "Business"}
	account_type = legacy_map.get(account_type.lower(), account_type) if account_type else "Individual"
	if account_type not in ("Individual", "Business"):
		account_type = "Individual"

	# Sprint 2.6: company_name/tax_id zorunluluğu KYC formuna taşındı.
	# Bu validation kaldırıldı — KYC submit anında doğrulanır.

	# ── Token validation ──
	token_cache_key = f"registration_token:{registration_token}"
	cached_email = frappe.cache.get_value(token_cache_key)

	if not cached_email:
		frappe.throw(_("Invalid or expired verification token. Please restart the registration."))

	# Handle bytes from Redis
	if isinstance(cached_email, bytes):
		cached_email = cached_email.decode()

	if cached_email != email:
		frappe.throw(_("Verification token does not match this email."))

	# ── Terms validation ──
	if not accept_terms:
		frappe.throw(_("You must accept the Terms of Service."))
	if not accept_kvkk:
		frappe.throw(_("You must accept the KVKK policy."))

	# ── Password validation ──
	_validate_password(password)

	# ── Duplicate check ──
	if frappe.db.exists("User", email):
		frappe.throw(
			_("An account with this email already exists."),
			frappe.DuplicateEntryError,
		)

	# ── Create User ──
	user = frappe.new_doc("User")
	user.email = email
	user.first_name = first_name
	user.last_name = last_name
	user.send_welcome_email = 0
	user.user_type = "Website User"
	user.flags.ignore_permissions = True
	user.flags.ignore_password_policy = True
	user.insert()

	update_password(email, password)
	user.add_roles("Buyer")

	# 🔒 KRITIK GÜVENLİK: Frappe v15 ``add_roles("Buyer")`` user_type'ı
	# **System User**'a yükseltiyor (Buyer rolü Frappe'de desk_access=1 flag'i
	# ile tanımlı). Bu Buyer'ı Frappe Desk'e erişebilir hale getirir → büyük
	# güvenlik açığı. Defansif raw SQL ile Website User'a geri çek + Desk User
	# rolünü kaldır.
	frappe.db.sql(
		"UPDATE `tabUser` SET `user_type`='Website User' WHERE `name`=%s",
		(email,),
	)
	frappe.db.sql(
		"DELETE FROM `tabHas Role` WHERE `parent`=%s AND `role`='Desk User' AND `parenttype`='User'",
		(email,),
	)

	# ── Generate unique member ID ──
	member_id = _generate_member_id(email, user.creation)

	# Canonicalize phone (optional field — empty stays empty).
	phone_canonical = canonicalize_phone(phone) or ""
	if phone and not phone_canonical:
		frappe.throw(_("Please enter a valid Turkish phone number."), frappe.ValidationError)

	# ── Create User Profile (Sprint 2 — Buyer Profile birleşik) ──
	# OTP doğrulaması zaten kullanıcının e-posta sahipliğini kanıtladı,
	# bu nedenle email_verified=1 olarak başlatıyoruz.
	up = frappe.new_doc("User Profile")
	up.user = email
	up.full_name = f"{first_name} {last_name}".strip() or email
	up.member_id = member_id
	up.country = country
	up.phone = phone_canonical
	up.status = "Active"
	# Sprint 2.6 (revised): KYC Verified olunca 1 set edilir; kayıt anında 0
	up.can_buy = 0
	up.can_sell = 0
	up.account_type = account_type
	up.email_verified = 1
	up.email_verified_at = now_datetime()
	up.email_verified_method = "otp"
	up.created_via = "storefront"
	up.owner = email
	# Backward compat — eski frontend Business kayıt göndermişse koru
	if account_type == "Business":
		if company_name:
			up.company_name = company_name
		if tax_id:
			up.tax_id = tax_id
		if tax_id_type:
			up.tax_id_type = tax_id_type
		if tax_office:
			up.tax_office = tax_office
	# Sprint 2.6: Tüm Alıcılar için KYC zorunlu (Soru 1). KYB Locked
	# (Satıcı başvurusu yapılana kadar). Sidebar/banner buna göre render olur.
	up.kyc_status = "Pending"
	up.kyb_status = "Locked"
	up.flags.ignore_permissions = True
	up.flags.ignore_validate = True
	up.insert(ignore_permissions=True)

	# Defansif raw SQL — Frappe v15'te Datetime field'ı insert sırasında bazen atlıyor
	frappe.db.sql(
		"UPDATE `tabUser Profile` SET `email_verified`=1, "
		"`email_verified_at`=%s, `email_verified_method`='otp', `owner`=%s "
		"WHERE `name`=%s",
		(now_datetime(), email, up.name),
	)

	# ── Audit log ──
	_log_email_verification_event(
		user=email,
		event="verified",
		method="otp",
		actor=email,
	)

	# ── Delete registration token (single-use) ──
	frappe.cache.delete_value(token_cache_key)

	frappe.db.commit()
	return {
		"success": True,
		"user": email,
		"registration_type": registration_type,
		"account_type": account_type,
		"kyc_required": True,  # Sprint 2.6 — Alıcı'ya hep KYC zorunlu
		"kyb_locked": True,  # Satıcı başvurusu yapana kadar
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="email", limit=5, seconds=3600)
def register_supplier(
	email: str,
	password: str,
	first_name: str,
	last_name: str,
	phone: str = "",
	country: str = "Turkey",
	accept_terms: int = 0,
	accept_kvkk: int = 0,
	registration_token: str = "",
	# Supplier form fields
	seller_type: str = "Business",
	business_name: str = "",
	contact_phone: str = "",
	tax_id_type: str = "TCKN",
	tax_id: str = "",
	tax_office: str = "",
	address_line_1: str = "",
	city: str = "",
	bank_name: str = "",
	iban: str = "",
	account_holder_name: str = "",
	identity_document_type: str = "",
	identity_document_number: str = "",
	identity_document_expiry: str = "",
	identity_document: str = "",
	terms_accepted: int = 0,
	privacy_accepted: int = 0,
	kvkk_accepted: int = 0,
	commission_accepted: int = 0,
	return_policy_accepted: int = 0,
):
	"""Register a new supplier in one atomic operation.

	Creates User + Buyer Profile + Seller Application (Submitted) all at once.
	Nothing is written to the database until the full form is submitted.
	"""
	email = _validate_email_format(email)

	# ── Token validation ──
	token_cache_key = f"registration_token:{registration_token}"
	cached_email = frappe.cache.get_value(token_cache_key)

	if not cached_email:
		frappe.throw(_("Invalid or expired verification token. Please restart the registration."))

	if isinstance(cached_email, bytes):
		cached_email = cached_email.decode()

	if cached_email != email:
		frappe.throw(_("Verification token does not match this email."))

	# ── Validations ──
	if not accept_terms:
		frappe.throw(_("You must accept the Terms of Service."))
	if not accept_kvkk:
		frappe.throw(_("You must accept the KVKK policy."))
	# TEMP-DISABLED: Frontend SupplierSetupForm Step 4'te "Kimlik Belgesi" yükleme
	# alanı yorum satırına alındı (geri getirildiğinde bu blok da açılır).
	# if not (identity_document or "").strip():
	# 	frappe.throw(
	# 		_("Identity document upload is required."),
	# 		frappe.ValidationError,
	# 	)
	_validate_password(password)

	if frappe.db.exists("User", email):
		frappe.throw(
			_("An account with this email already exists."),
			frappe.DuplicateEntryError,
		)

	# ── Create User ──
	user = frappe.new_doc("User")
	user.email = email
	user.first_name = first_name
	user.last_name = last_name
	user.send_welcome_email = 0
	user.user_type = "Website User"
	user.flags.ignore_permissions = True
	user.flags.ignore_password_policy = True
	user.insert()

	update_password(email, password)
	user.add_roles("Buyer")

	# 🔒 KRITIK GÜVENLİK: Frappe v15 ``add_roles("Buyer")`` user_type'ı
	# System User'a yükseltir. Defansif olarak Website User'a geri çek.
	frappe.db.sql(
		"UPDATE `tabUser` SET `user_type`='Website User' WHERE `name`=%s",
		(email,),
	)
	frappe.db.sql(
		"DELETE FROM `tabHas Role` WHERE `parent`=%s AND `role`='Desk User' AND `parenttype`='User'",
		(email,),
	)

	member_id = _generate_member_id(email, user.creation)

	# Canonicalize both phone fields once. Each is optional; if a value was
	# provided but cannot canonicalize, reject the whole registration.
	phone_canonical = canonicalize_phone(phone) or ""
	if phone and not phone_canonical:
		frappe.throw(_("Please enter a valid Turkish phone number."), frappe.ValidationError)
	contact_phone_canonical = canonicalize_phone(contact_phone) or ""
	if contact_phone and not contact_phone_canonical:
		frappe.throw(_("Please enter a valid Turkish phone number."), frappe.ValidationError)

	# ── Create User Profile (Sprint 2.6 — Satıcı kayıt akışı) ──
	# Satıcı kayıt → can_sell=0 (henüz Seller Application onayı yok),
	# can_buy=0 (KYC doldurulup onaylanana kadar satın alım yok).
	# Soru 1 cevabı: KYC opsiyonel Satıcı için → kyc_status="Locked",
	# kyb_status="Locked" (Seller Application onayında Pending'e döner).
	buyer = frappe.new_doc("User Profile")
	buyer.user = email
	buyer.full_name = f"{first_name} {last_name}".strip() or email
	buyer.member_id = member_id
	buyer.country = country
	buyer.phone = phone_canonical or contact_phone_canonical
	buyer.status = "Active"
	buyer.can_buy = 0
	buyer.can_sell = 0  # Seller Application onayında 1'e döner
	buyer.account_type = "Business"  # Satıcı = zorunlu kurumsal
	if business_name:
		buyer.company_name = business_name
	if tax_id:
		buyer.tax_id = tax_id
	if tax_id_type:
		buyer.tax_id_type = tax_id_type
	if tax_office:
		buyer.tax_office = tax_office
	buyer.kyc_status = "Locked"
	buyer.kyb_status = "Locked"
	buyer.email_verified = 1
	buyer.email_verified_at = now_datetime()
	buyer.email_verified_method = "otp"
	buyer.created_via = "seller_application"
	buyer.owner = email
	buyer.flags.ignore_permissions = True
	buyer.flags.ignore_validate = True
	buyer.insert(ignore_permissions=True)

	# Defansif — Frappe Datetime field'ı insert sırasında bazen atlıyor
	frappe.db.sql(
		"UPDATE `tabUser Profile` SET `email_verified`=1, "
		"`email_verified_at`=%s, `email_verified_method`='otp', `owner`=%s "
		"WHERE `name`=%s",
		(now_datetime(), email, buyer.name),
	)

	# ── Audit log ──
	_log_email_verification_event(
		user=email,
		event="verified",
		method="otp",
		actor=email,
	)

	# ── Create Seller Application (Submitted) ──
	app = frappe.new_doc("Seller Application")
	app.applicant_user = email
	app.owner = email
	app.member_id = member_id
	app.contact_email = email
	app.status = "Submitted"
	app.seller_type = seller_type
	app.business_name = business_name
	app.contact_phone = contact_phone_canonical or phone_canonical
	app.tax_id_type = tax_id_type
	app.tax_id = tax_id
	app.tax_office = tax_office
	app.address_line_1 = address_line_1
	app.city = city
	app.country = country or "Turkey"
	app.bank_name = bank_name
	app.iban = iban
	app.account_holder_name = account_holder_name
	app.identity_document_type = identity_document_type
	app.identity_document_number = identity_document_number
	app.identity_document_expiry = identity_document_expiry or None
	app.identity_document = identity_document
	app.terms_accepted = int(terms_accepted)
	app.privacy_accepted = int(privacy_accepted)
	app.kvkk_accepted = int(kvkk_accepted)
	app.commission_accepted = int(commission_accepted)
	app.return_policy_accepted = int(return_policy_accepted)
	app.insert(ignore_permissions=True)

	# ── Assign uploaded files to new user ──
	if identity_document:
		_reassign_file_owner(identity_document, email)

	# ── Delete registration token (single-use) ──
	frappe.cache.delete_value(token_cache_key)

	frappe.db.commit()
	return {
		"success": True,
		"user": email,
		"registration_type": "Satici",
		"account_type": "Business",
		"seller_application": app.name,
		"seller_application_status": app.status,
		"kyb_locked": True,  # Seller Application onayında Pending'e döner
		"kyc_locked": True,  # Alıcı olmak isterse KYC doldurulur
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="email", limit=10, seconds=3600)
def forgot_password(email: str):
	"""Send a password reset link via email.

	Always returns success to prevent email enumeration. Ancak format ve
	domain DNS kontrolü öncesinde yapılır — geçersiz domain ("turksab.coms"
	gibi yazım hataları) 400 ile reddedilir, böylece kullanıcı yanlış
	adrese mail gönderildi sanmaz.
	"""
	# Format + DNS check (geçersiz adres → 400; bu enumeration leak değil
	# çünkü domain'in varlığı kullanıcı varlığına bağlı değil)
	email = _validate_email_format(email)

	# Always return success — email enumeration protection
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)

		# Generate reset key
		reset_key = frappe.generate_hash(length=32)
		user.db_set("reset_password_key", reset_key)
		user.db_set("last_reset_password_key_generated_on", now_datetime())

		# Build reset link pointing to the storefront page
		storefront = frappe.conf.get("storefront_url", "https://rc.istoc.com")
		link = f"{storefront}/pages/auth/reset-password?key={reset_key}"

		frappe.sendmail(
			recipients=email,
			subject="iSTOC — Şifre Sıfırlama",
			template="tradehub_password_reset",
			args={"link": link, "full_name": user.full_name},
			now=True,
			communication=False,
		)

	return {
		"success": True,
		"message": _("If this email is registered, a password reset link has been sent."),
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="key", limit=5, seconds=3600)
def reset_password(key: str, new_password: str):
	"""Reset password using the key from the email link.

	The key must match User.reset_password_key and be within 24 hours.
	"""
	key = (key or "").strip()

	if not key:
		frappe.throw(
			_("Invalid or expired password reset link."),
			frappe.AuthenticationError,
		)

	# Find user with this reset key
	user_data = frappe.db.get_value(
		"User",
		{"reset_password_key": key},
		["name", "last_reset_password_key_generated_on"],
		as_dict=True,
	)

	if not user_data:
		frappe.throw(
			_("Invalid or expired password reset link."),
			frappe.AuthenticationError,
		)

	# Check 24-hour expiry
	if not user_data.last_reset_password_key_generated_on:
		frappe.throw(
			_("Invalid or expired password reset link."),
			frappe.AuthenticationError,
		)
	age = (now_datetime() - user_data.last_reset_password_key_generated_on).total_seconds()
	if age > 86400:
		frappe.throw(
			_("This reset link has expired. Please request a new one."),
			frappe.AuthenticationError,
		)

	# Validate new password
	_validate_password(new_password)

	# Reject if the new password is identical to the current one
	try:
		check_password(user_data.name, new_password)
	except frappe.AuthenticationError:
		# Different password — proceed
		pass
	else:
		frappe.throw(
			_("This password is already in use. Please choose a different one."),
			frappe.ValidationError,
		)

	# Update password and clear reset key
	update_password(user_data.name, new_password, logout_all_sessions=True)
	frappe.db.set_value("User", user_data.name, "reset_password_key", None)

	# Audit (Faz C — K12) — şifre değişimi kritik güvenlik olayı
	from tradehub_core.audit import log_decision

	log_decision(
		actor=user_data.name,
		action="identity.reset_password",
		decision="ALLOW",
		rule_id="auth.password_reset_completed",
		layer="L2",
		object_doctype="User",
		object_name=user_data.name,
		severity="HIGH",
		context={"all_sessions_logged_out": True},
	)

	return {
		"success": True,
		"message": _("Your password has been reset successfully."),
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def verify_email(key: str):
	"""Verify user email via the link sent after registration.

	On success, redirects to the storefront login page with ?verified=1.
	On failure, redirects with ?verified=0.
	"""
	key = (key or "").strip()
	storefront = frappe.conf.get("storefront_url", "https://rc.istoc.com")
	login_url = f"{storefront}/pages/auth/login"

	cache_key = f"email_verification:{key}"
	email = frappe.cache.get_value(cache_key)

	if not email:
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = f"{login_url}?verified=0"
		return

	# Handle bytes from Redis
	if isinstance(email, bytes):
		email = email.decode()

	# Mark email as verified on User Profile — doğrudan SQL UPDATE (Frappe v15
	# set_value `email_verified_at` Datetime field'ını bazı durumlarda yazmıyor;
	# tek raw UPDATE ile garanti çalışır + atomik).
	# Sprint 2 (revised, 2026-05-15): tabBuyer Profile → tabUser Profile rename.
	bp_name = frappe.db.get_value("User Profile", {"user": email}, "name")
	if bp_name:
		frappe.db.sql(
			"UPDATE `tabUser Profile` SET `email_verified`=1, "
			"`email_verified_at`=%s, `email_verified_method`='otp' "
			"WHERE `name`=%s",
			(now_datetime(), bp_name),
		)

	# Audit log
	_log_email_verification_event(
		user=email,
		event="verified",
		method="otp",
		actor=email,
	)

	# Delete verification key (single-use)
	frappe.cache.delete_value(cache_key)

	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = f"{login_url}?verified=1"


def _verify_password(user: str, password: str):
	"""Verify user password. Raises ValidationError (400) instead of
	AuthenticationError (401) so the frontend api() wrapper does not
	redirect to the login page."""
	try:
		check_password(user, password)
	except frappe.AuthenticationError:
		frappe.local.response["http_status_code"] = 400
		frappe.throw(
			_("Incorrect password."),
			frappe.ValidationError,
		)


@frappe.whitelist(methods=["POST"])
@rate_limit(key="user", limit=10, seconds=300)
def update_profile_image(filename: str = "", filedata: str = ""):
	"""Upload a profile image for the currently logged-in user.

	Accepts base64-encoded image content via JSON body. Stores the file as
	a public attachment (so it can be rendered in avatars) and updates the
	``User.user_image`` field. Returns the final file URL so the frontend
	can update the UI immediately without a full reload.
	"""
	import base64

	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	if not filename or not filedata:
		frappe.throw(_("No file uploaded."))

	allowed_ext = (".jpg", ".jpeg", ".png", ".webp", ".gif")
	if not filename.lower().endswith(allowed_ext):
		frappe.throw(_("Only JPG, PNG, WEBP and GIF images are allowed."))

	# Strip data URI prefix if present (e.g. "data:image/png;base64,...")
	if "," in filedata:
		filedata = filedata.split(",", 1)[1]

	try:
		content = base64.b64decode(filedata)
	except Exception:
		frappe.throw(_("Invalid file data."))

	# Hard size cap — 5 MB
	if len(content) > 5 * 1024 * 1024:
		frappe.throw(_("Image must be smaller than 5 MB."))

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"content": content,
			"is_private": 0,
			"attached_to_doctype": "User",
			"attached_to_name": user,
		}
	)
	file_doc.insert(ignore_permissions=True)

	frappe.db.set_value("User", user, "user_image", file_doc.file_url)
	frappe.db.commit()

	return {"success": True, "user_image": file_doc.file_url}


@frappe.whitelist(methods=["POST"])
def change_password(current_password: str, new_password: str):
	"""Change password for the currently logged-in user."""
	user = frappe.session.user

	if user == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	# Verify current password — returns 400 on failure (not 401)
	_verify_password(user, current_password)

	# Reject if new password is identical to current password
	if current_password == new_password:
		frappe.throw(_("Your new password cannot be the same as your current password."))

	# Validate new password rules
	_validate_password(new_password)

	# Update password and invalidate all other sessions
	update_password(user, new_password, logout_all_sessions=True)
	frappe.db.commit()

	# Audit (Faz C — K12) — şifre değişimi kritik güvenlik olayı
	from tradehub_core.audit import log_decision

	log_decision(
		actor=user,
		action="identity.change_password",
		decision="ALLOW",
		rule_id="auth.password_change_completed",
		layer="L2",
		object_doctype="User",
		object_name=user,
		severity="HIGH",
		context={"all_sessions_logged_out": True},
	)

	return {"success": True, "message": _("Password changed successfully.")}


@frappe.whitelist(methods=["POST"])
@rate_limit(key="user", limit=10, seconds=3600)
def change_email(new_email: str, password: str):
	"""DEPRECATED — eski tek-adımlı email değişimi.

	Pattern A (OTP-only) ile birlikte ``request_email_change`` +
	``confirm_email_change`` ikilisine taşındı. Bu endpoint artık
	hiçbir DB yazımı yapmaz; eski frontend istemcilerinin görünür bir
	hata almasını ve yeni akışa geçmesini sağlar.
	"""
	frappe.local.response["http_status_code"] = 410
	frappe.throw(
		_("This endpoint has been replaced. Use request_email_change followed by confirm_email_change."),
		frappe.ValidationError,
	)


@frappe.whitelist(methods=["POST"])
@rate_limit(key="user", limit=20, seconds=3600)
def request_email_change(new_email: str, password: str):
	"""Email değişimi için yeni adrese OTP gönderir; DB yazımı YAPMAZ.

	Akış:
	  1. Kullanıcı parolasını doğrular.
	  2. Yeni adresin format/duplicate kontrollerini yapar.
	  3. 6 haneli OTP üretir, Redis'e ``email_change:{user}`` ile yazar (TTL 30dk).
	  4. Yeni adrese ``email_change_otp`` template'iyle kod gönderir.

	HTTP hataları:
	  400 — geçersiz format / aynı adres
	  401 — parola yanlış
	  409 — yeni adres başka kullanıcıda
	  429 — rate limit
	"""
	old_email = frappe.session.user
	if old_email == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	if old_email == "Administrator":
		frappe.local.response["http_status_code"] = 403
		frappe.throw(
			_("Administrator account email cannot be changed."),
			frappe.PermissionError,
		)

	new_email = _validate_email_format(new_email)

	if new_email == old_email:
		frappe.local.response["http_status_code"] = 400
		frappe.throw(
			_("New email cannot be the same as your current email."),
			frappe.ValidationError,
		)

	if frappe.db.exists("User", new_email):
		frappe.local.response["http_status_code"] = 409
		frappe.throw(
			_("An account with this email already exists."),
			frappe.DuplicateEntryError,
		)

	# Parolayı doğrula — başarısızsa 400 (frontend api() wrapper logout'a düşmesin)
	_verify_password(old_email, password)

	# OTP oluştur ve Redis'e yaz (30 dk TTL)
	otp_code = _generate_otp()
	frappe.cache.set_value(
		f"email_change:{old_email}",
		json.dumps({"new_email": new_email, "code": otp_code, "attempts": 0}),
		expires_in_sec=1800,
	)

	# Audit
	_log_email_verification_event(
		user=old_email,
		event="change_requested",
		method="otp",
	)

	# Yeni adrese OTP gönder — now=False ile mail kuyruğuna alınır (async)
	# communication=False: Frappe Desk inbox'ında sistem mailleri görünmesin
	# (başka kullanıcılar pinar.kaya'nın inbox'ından görmesin)
	frappe.sendmail(
		recipients=new_email,
		subject="iSTOC — Yeni E-posta Adresi Doğrulama",
		template="email_change_otp",
		args={"code": otp_code, "old_email": old_email},
		now=False,
		communication=False,
	)

	return {"success": True, "expires_in_minutes": 30}


@frappe.whitelist(methods=["POST"])
@rate_limit(key="user", limit=10, seconds=600)
def confirm_email_change(code: str):
	"""``request_email_change``'den gelen OTP'yi doğrular ve adresi değiştirir.

	Tüm DB yazımları (User rename, Buyer/Seller Profile, Seller Application,
	__Auth) tek bir akışta atomik olarak çalışır; bir adım başarısız olursa
	Frappe transaction otomatik rollback eder. Önceki ``change_email``'deki
	``try/except: pass`` kalıbı tamamen kaldırıldı.
	"""
	old_email = frappe.session.user
	if old_email == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	code = (code or "").strip()
	cache_key = f"email_change:{old_email}"
	cached = frappe.cache.get_value(cache_key)

	if not cached:
		frappe.local.response["http_status_code"] = 404
		frappe.throw(
			_("No pending email change. Please start over."),
			frappe.DoesNotExistError,
		)

	data = json.loads(cached) if isinstance(cached, str) else cached
	new_email = (data.get("new_email") or "").strip().lower()
	expected = data.get("code")

	# 5 başarısız denemeden sonra OTP'yi geçersiz kıl
	if data.get("attempts", 0) >= OTP_MAX_ATTEMPTS:
		frappe.cache.delete_value(cache_key)
		frappe.local.response["http_status_code"] = 429
		frappe.local.response["attempts_remaining"] = 0
		frappe.throw(
			_("Too many wrong attempts. Please request a new code."),
			frappe.TooManyRequestsError,
		)

	if code != expected:
		data["attempts"] = data.get("attempts", 0) + 1
		frappe.cache.set_value(cache_key, json.dumps(data), expires_in_sec=1800)
		frappe.local.response["http_status_code"] = 422
		frappe.local.response["attempts_remaining"] = max(0, OTP_MAX_ATTEMPTS - data["attempts"])
		frappe.throw(
			_("Wrong verification code."),
			frappe.ValidationError,
		)

	# Race koruması: OTP oluşturulduktan sonra başkası adresi almış olabilir
	if frappe.db.exists("User", new_email):
		frappe.cache.delete_value(cache_key)
		frappe.local.response["http_status_code"] = 409
		frappe.throw(
			_("An account with this email already exists."),
			frappe.DuplicateEntryError,
		)

	# ── Senkron rename (low-level SQL — Frappe rename_doc bug bypass) ──
	# Frappe v15 + Python 3.14 + redis-on-mariadb sessions kombinasyonunda
	# ``frappe.rename_doc("User", ...)`` -> ``after_rename`` -> ``clear_sessions``
	# DB connection'ını koparıyor, rename'in kalan adımları (add_comment vb.)
	# fail ediyor ve transaction rollback oluyor. Eski kod ``try/except: pass``
	# ile yutarak yarı yazılmış state üretiyordu (kullanıcının raporladığı bug).
	#
	# Çözüm: rename_doc'u tamamen by-pass et. Yapılması gereken kritik DB
	# UPDATE'leri kendimiz tek transaction içinde manuel yapıyoruz; Frappe'nin
	# Comment/Version history kayıtlarından feragat ediyoruz (zaten Email
	# Verification Log'umuz var).
	_do_rename_user_email(old_email=old_email, new_email=new_email)

	# OTP cache'ini sil (single-use)
	frappe.cache.delete_value(cache_key)
	frappe.db.commit()

	return {
		"success": True,
		"new_email": new_email,
		"message": _("Email address updated successfully. Please log in again with your new email."),
	}


def _do_rename_user_email(old_email: str, new_email: str):
	"""Hibrit User rename — Frappe ``rename_doc`` dene, fail ederse SQL fallback.

	**Sıra**:
	  1. Frappe ``rename_doc("User", old, new)`` çağrılır. ``clear_sessions``
	     geçici no-op'lanır (Python 3.14 + redis-on-mariadb dev ortamındaki
	     ``InterfaceError`` zincirini önlemek için).
	  2. ``frappe.db.exists("User", new_email)`` ile rename'in DB'ye yansıyıp
	     yansımadığı doğrulanır. **Başarılı ise**: Frappe ``Comment`` "renamed
	     from X to Y" + ``Version`` history kayıtları otomatik düşer.
	  3. **Fail ise** (örn. Python 3.14 InterfaceError): connection tazelenir,
	     low-level SQL UPDATE'ler ile manuel rename yapılır.

	**Trade-off**:
	  + Prod (Python 3.11): Frappe native rename audit (Comment, Version) düşer
	  + Dev (Python 3.14): SQL fallback ile aynı sonuç (mevcut davranış korunur)
	  + Future-proof: Frappe v16'da rename_doc davranışı değişse bile fallback
	    devreye girer
	  - Hibrit kod biraz daha karmaşık (try/except + fallback dalı)

	İşlem sırası (rename başarısı sonrası ortak):
	  • User Profile email_verified=1, at=now, method=otp (SQL UPDATE)
	  • Eski adrese bilgilendirme maili (mail kuyruğu — async)
	  • Email Verification Log change_completed event'i
	  • Sessions clear (artık komut commit'lendi, fail olsa zarar yok)

	**SQL fallback** sadece rename_doc başarısız olduğunda çalışır:
	  1. ``__Auth`` tablosu — parola/secret mapping'i taşı
	  2. ``tabUser`` primary key + email + username
	  3. ``tabUser Profile`` — autoname=field:user → name == user, ikisi de UPDATE
	  4. ``tabSeller Profile`` — user field
	  5. ``tabSeller Application`` — applicant_user + contact_email
	  6. Tüm User Link field'ları — ``frappe.model.rename_doc.get_link_fields``
	     ile dinamik liste, parent doctype'larda UPDATE
	  9. Audit log
	 10. Cache invalidation
	 11. clear_sessions(new_email, force=True) — try/except yutarak (artık
	     rollback edilemez, commit'ten önce ama transaction sonu yakın)
	"""
	from frappe.model.rename_doc import get_link_fields

	# 🔒 KRITIK GÜVENLİK: rename öncesi target user_type'ı belirle.
	# Frappe v15 ``rename_doc`` (ve ``add_roles``) User'ın user_type'ını
	# ``System User``'a otomatik yükseltiyor (Buyer rolü desk_access=1).
	#
	# Bu KRITIK BIR SIZINTI: Buyer email değiştirir → user_type=System User
	# olur → Frappe Desk'e (`/app`) erişebilir.
	#
	# Mantık: Buyer Profile veya Seller Profile'a bağlıysa storefront kullanıcı
	# kabul edilir; user_type SQL UPDATE ile **zorla `Website User`** yapılır.
	# Aksi halde (admin gibi) eski user_type korunur.
	is_storefront_user = bool(
		frappe.db.exists("User Profile", {"user": old_email})
		or frappe.db.exists("User Profile", {"user": old_email})
		or frappe.db.exists("Seller Application", {"applicant_user": old_email})
	)
	if is_storefront_user:
		target_user_type = "Website User"
	else:
		# Admin kullanıcı — pre-state'i koru (genelde System User)
		target_user_type = frappe.db.get_value("User", old_email, "user_type") or "System User"

	# ─── HİBRİT YOL: ÖNCE Frappe rename_doc dene ───────────────────────────
	# rename_doc başarılı olursa Frappe'nin ``Comment`` ve ``Version`` audit
	# kayıtları otomatik düşer (admin Frappe Desk → User → Activity sekmesinde
	# "renamed from X to Y" satırını görür).
	#
	# ``clear_sessions``'ı geçici olarak no-op'la — Python 3.14 + redis-on-mariadb
	# kombinasyonunda InterfaceError'u önler. Prod'da (Python 3.11) bu zaten
	# sorunsuz çalışır; no-op zarar vermez (rename sonrası manuel
	# clear_sessions yine çalıştırılır).
	rename_doc_succeeded = False
	try:
		import frappe.core.doctype.user.user as _user_module

		_orig_clear_sessions = _user_module.clear_sessions
		_user_module.clear_sessions = lambda *a, **kw: None
		try:
			frappe.rename_doc("User", old_email, new_email, merge=False)
		finally:
			_user_module.clear_sessions = _orig_clear_sessions

		# Connection tazele (Python 3.14'te clear_sessions InterfaceError
		# fırlatmış olabilir; rename muhtemelen yine de uygulanmış olabilir)
		try:
			frappe.db.sql("SELECT 1")
		except Exception:
			frappe.db.connect()

		# rename gerçekten DB'ye yansıdı mı?
		if frappe.db.exists("User", new_email) and not frappe.db.exists("User", old_email):
			rename_doc_succeeded = True
			frappe.logger().info(f"_do_rename_user_email: rename_doc succeeded ({old_email} -> {new_email})")
	except Exception as exc:
		# rename_doc patladı (Python 3.14 InterfaceError, vs.) — connection tazele
		try:
			frappe.db.sql("SELECT 1")
		except Exception:
			frappe.db.connect()
		frappe.logger().warning(
			f"_do_rename_user_email: rename_doc raised {type(exc).__name__}; will use SQL fallback"
		)

	# rename_doc başarılı olduğunda — Buyer Profile.user'ı NEW'a günceller ama
	# ``autoname=field:user`` kuralı için ``BP.name``'i de senkronize etmek
	# gerek. Frappe rename_doc bunu yapmıyor (link field cascade rename değil).
	# Tek satır SQL UPDATE: BP.name = NEW.
	if rename_doc_succeeded and frappe.db.exists("User Profile", old_email):
		frappe.db.sql(
			"UPDATE `tabUser Profile` SET `name`=%s WHERE `name`=%s",
			(new_email, old_email),
		)

	# 🔒 KRITIK GÜVENLİK GUARD: rename_doc/add_roles User.user_type'ı System
	# User'a otomatik çekiyor. target_user_type'a zorla geri yaz — storefront
	# kullanıcılar için Website User, adminler için pre-state.
	if frappe.db.exists("User", new_email):
		current_user_type = frappe.db.get_value("User", new_email, "user_type")
		if current_user_type != target_user_type:
			frappe.db.sql(
				"UPDATE `tabUser` SET `user_type`=%s WHERE `name`=%s",
				(target_user_type, new_email),
			)
			frappe.logger().info(
				f"_do_rename_user_email: user_type guard restored "
				f"{target_user_type} (was {current_user_type})"
			)

	# ─── SQL FALLBACK: rename_doc başarısızsa veya kısmen kaldıysa ─────────
	# Bu kod Python 3.14 dev ortamında devreye girer. Prod'da (Python 3.11)
	# rename_doc başarılı olur ve bu blok atlanır.
	if not rename_doc_succeeded:
		frappe.logger().info(f"_do_rename_user_email: SQL fallback for {old_email} -> {new_email}")

		# 1. __Auth — parola/secret mapping'i (rename'den ÖNCE yapılmalı: User.name
		#    primary key'i değişeceği için __Auth.name FK constraint'i bağlı kalmasın)
		frappe.db.sql(
			"UPDATE `__Auth` SET `name`=%s WHERE `name`=%s AND `doctype`='User'",
			(new_email, old_email),
		)

		# 2. tabUser — primary key + email + username
		# DİKKAT: Frappe User DocType'ında autoname=email; rename_doc bu field'ları
		# otomatik senkronlar ama fallback'ta manuel güncelliyoruz. Aksi halde
		# ``User.name`` yeni email olur ama ``User.email`` eski email kalır.
		frappe.db.sql(
			"UPDATE `tabUser` SET `name`=%s, `email`=%s, `username`=%s WHERE `name`=%s",
			(new_email, new_email, new_email.split("@", 1)[0], old_email),
		)

		# 3. tabUser Profile — autoname=field:user, hem name hem user UPDATE
		# Sprint 2 (revised, 2026-05-15): tabBuyer Profile → tabUser Profile rename.
		frappe.db.sql(
			"UPDATE `tabUser Profile` SET `name`=%s, `user`=%s WHERE `name`=%s OR `user`=%s",
			(new_email, new_email, old_email, old_email),
		)

		# 4. tabSeller Profile — user field
		frappe.db.sql(
			"UPDATE `tabSeller Profile` SET `user`=%s WHERE `user`=%s",
			(new_email, old_email),
		)

		# 5. tabSeller Application — applicant_user + contact_email
		frappe.db.sql(
			"UPDATE `tabSeller Application` SET `applicant_user`=%s, `contact_email`=%s "
			"WHERE `applicant_user`=%s",
			(new_email, new_email, old_email),
		)

		# 6. Diğer User Link field'ları (dinamik) — owner, modified_by gibi sistem
		#    alanlarını ATLA; sadece custom Link field'ları güncelle.
		for lf in get_link_fields("User"):
			parent = lf.get("parent")
			fieldname = lf.get("fieldname")
			issingle = lf.get("issingle")
			if not parent or not fieldname:
				continue
			# Yukarıda zaten elle güncellediklerimizi atla
			if (parent, fieldname) in {
				("User", "name"),
				("User Profile", "user"),
				("User Profile", "user"),
				("Seller Application", "applicant_user"),
			}:
				continue
			try:
				if issingle:
					frappe.db.sql(
						"UPDATE `tabSingles` SET `value`=%s WHERE `doctype`=%s AND `field`=%s AND `value`=%s",
						(new_email, parent, fieldname, old_email),
					)
				else:
					frappe.db.sql(
						f"UPDATE `tab{parent}` SET `{fieldname}`=%s WHERE `{fieldname}`=%s",
						(new_email, old_email),
					)
			except Exception:
				# Tek bir link field UPDATE'inin başarısız olması rename'i bozmasın
				frappe.log_error(
					title=f"User rename: link field update failed ({parent}.{fieldname})",
					message=frappe.get_traceback(),
				)

		# Fallback rename'in DB'ye yansıdığını doğrula
		if not frappe.db.exists("User", new_email):
			frappe.local.response["http_status_code"] = 500
			frappe.throw(
				_(
					"Email change could not be completed. Please try again. "
					"If the problem persists, contact support."
				),
				frappe.ValidationError,
			)

	# ─── ORTAK ADIMLAR — rename_doc başarılı olsun veya SQL fallback olsun ───

	# 7. Yeni adres OTP ile kanıtlandı → email_verified=1
	# Doğrudan SQL UPDATE (Frappe v15 set_value `update_modified=False` ile
	# Datetime field'ını bazen yazmıyor — bu Sorun 4'ün kök nedeniydi).
	# Tek raw UPDATE garanti çalışır.
	bp_name = frappe.db.get_value("User Profile", {"user": new_email}, "name")
	if bp_name:
		frappe.db.sql(
			"UPDATE `tabUser Profile` SET `email_verified`=1, "
			"`email_verified_at`=%s, `email_verified_method`='otp' "
			"WHERE `name`=%s",
			(now_datetime(), bp_name),
		)

	# 8. Eski adrese bilgilendirme maili (now=False → mail kuyruğu)
	# communication=False: Frappe Desk inbox'ı sistem mailini göstermesin
	try:
		frappe.sendmail(
			recipients=old_email,
			subject="iSTOC — Hesap E-posta Adresi Değiştirildi",
			template="email_change_notice",
			args={"old_email": old_email, "new_email": new_email},
			now=False,
			communication=False,
		)
	except Exception:
		frappe.log_error(
			title="email_change_notice send failed",
			message=frappe.get_traceback(),
		)

	# 9. Audit log
	_log_email_verification_event(
		user=new_email,
		event="change_completed",
		method="otp",
		actor=new_email,
	)

	# 10. Cache invalidation (eski email referansları)
	try:
		frappe.clear_cache(user=old_email)
		frappe.clear_cache(user=new_email)
	except Exception:
		pass

	# 11. Sessions temizle (try/except — connection ölürse de transaction etkilenmez,
	#     çünkü ana commit'i caller yapıyor; burada warning kalır)
	try:
		from frappe.sessions import clear_sessions

		clear_sessions(user=old_email, force=True)
	except Exception:
		frappe.logger().warning("clear_sessions(old_email) after rename failed; ignoring")
		try:
			frappe.db.sql("SELECT 1")
		except Exception:
			frappe.db.connect()


@frappe.whitelist(methods=["POST"])
@rate_limit(key="user", limit=3, seconds=3600)
def resend_verification_email():
	"""Doğrulanmamış kullanıcı için yeni bir OTP gönderir.

	Pattern A'da kayıt sırasında zaten verified=1 set edildiği için bu endpoint
	yalnızca migrate edilmiş eski kullanıcılar veya admin tarafından unverify
	edilmiş hesaplar için anlamlı.
	"""
	user = frappe.session.user

	if user == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	# Zaten doğrulanmışsa boşa OTP gönderme
	already_verified = bool(frappe.db.get_value("User Profile", {"user": user}, "email_verified"))
	if already_verified:
		return {"success": True, "already_verified": True}

	otp_code = _generate_otp()
	frappe.cache.set_value(
		f"reverify_otp:{user}",
		json.dumps({"code": otp_code, "attempts": 0}),
		expires_in_sec=600,
	)

	frappe.sendmail(
		recipients=user,
		subject="iSTOC — E-posta Doğrulama Kodu",
		template="registration_otp",
		args={"code": otp_code},
		now=False,
		communication=False,
	)

	return {"success": True, "expires_in_minutes": 10}


@frappe.whitelist(methods=["POST"])
def admin_set_email_verified(user: str, verified: int = 1, reason: str = ""):
	"""System Manager / Marketplace Admin: bir kullanıcının email_verified flag'ini
	manuel olarak değiştirir. Form üstündeki sessiz toggle yerine bu endpoint
	üzerinden gerçekleşir; her çağrı denetim kaydına geçer.

	HTTP hataları:
	  403 — yetkisiz çağrı
	  400 — gerekçe boş veya kullanıcı bulunamadı
	"""
	caller = frappe.session.user
	roles = frappe.get_roles(caller)
	if not ({"System Manager", "Administrator", "Marketplace Admin"} & set(roles)):
		frappe.local.response["http_status_code"] = 403
		frappe.throw(_("Insufficient privileges."), frappe.PermissionError)

	user = (user or "").strip().lower()
	if not user or not frappe.db.exists("User", user):
		frappe.local.response["http_status_code"] = 400
		frappe.throw(_("User not found."), frappe.DoesNotExistError)

	verified = int(verified or 0)
	reason = (reason or "").strip()
	if not reason:
		frappe.local.response["http_status_code"] = 400
		frappe.throw(
			_("A reason is required for manual verification overrides."),
			frappe.ValidationError,
		)

	if not frappe.db.exists("User Profile", {"user": user}):
		frappe.local.response["http_status_code"] = 400
		frappe.throw(_("Target user has no Buyer Profile."), frappe.DoesNotExistError)

	# Doğrudan SQL UPDATE (Frappe v15 set_value Datetime field'ını
	# bazen yazmıyor — Sorun 4 kök neden)
	bp_name = frappe.db.get_value("User Profile", {"user": user}, "name")
	if bp_name:
		if verified:
			frappe.db.sql(
				"UPDATE `tabUser Profile` SET `email_verified`=1, "
				"`email_verified_at`=%s, `email_verified_method`='admin_override' "
				"WHERE `name`=%s",
				(now_datetime(), bp_name),
			)
		else:
			frappe.db.sql(
				"UPDATE `tabUser Profile` SET `email_verified`=0, "
				"`email_verified_at`=NULL, `email_verified_method`=NULL "
				"WHERE `name`=%s",
				(bp_name,),
			)

	_log_email_verification_event(
		user=user,
		event="admin_override" if verified else "unverified",
		method="admin_override",
		actor=caller,
		reason=reason,
	)

	frappe.db.commit()
	return {"success": True, "user": user, "email_verified": bool(verified)}


@frappe.whitelist(methods=["POST"])
@rate_limit(key="user", limit=10, seconds=600)
def verify_email_otp(code: str):
	"""``resend_verification_email`` ile gönderilen OTP'yi doğrular."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	cache_key = f"reverify_otp:{user}"
	cached = frappe.cache.get_value(cache_key)
	if not cached:
		frappe.local.response["http_status_code"] = 404
		frappe.throw(
			_("Verification code not found or expired."),
			frappe.DoesNotExistError,
		)

	data = json.loads(cached) if isinstance(cached, str) else cached
	if data.get("attempts", 0) >= OTP_MAX_ATTEMPTS:
		frappe.cache.delete_value(cache_key)
		frappe.local.response["http_status_code"] = 429
		frappe.local.response["attempts_remaining"] = 0
		frappe.throw(
			_("Too many wrong attempts. Please request a new code."),
			frappe.TooManyRequestsError,
		)

	if (code or "").strip() != data.get("code"):
		data["attempts"] = data.get("attempts", 0) + 1
		frappe.cache.set_value(cache_key, json.dumps(data), expires_in_sec=600)
		frappe.local.response["http_status_code"] = 422
		frappe.local.response["attempts_remaining"] = max(0, OTP_MAX_ATTEMPTS - data["attempts"])
		frappe.throw(_("Wrong verification code."), frappe.ValidationError)

	# Doğrudan SQL UPDATE (Sorun 4 kök neden — set_value Datetime yazımı)
	bp_name = frappe.db.get_value("User Profile", {"user": user}, "name")
	if bp_name:
		frappe.db.sql(
			"UPDATE `tabUser Profile` SET `email_verified`=1, "
			"`email_verified_at`=%s, `email_verified_method`='otp' "
			"WHERE `name`=%s",
			(now_datetime(), bp_name),
		)

	_log_email_verification_event(
		user=user,
		event="verified",
		method="otp",
		actor=user,
	)

	frappe.cache.delete_value(cache_key)
	frappe.db.commit()
	return {"success": True}


@frappe.whitelist(methods=["POST"])
def change_phone(phone: str, password: str):
	"""Change the phone number for the currently logged-in user.

	Requires the current password for security verification.
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	phone = (phone or "").strip()
	if not phone:
		frappe.local.response["http_status_code"] = 400
		frappe.throw(_("Phone number is required."), frappe.ValidationError)

	# Canonicalize to E.164 (+90...). Accepts mobile (5XX) and landline (2XX-4XX).
	canonical = canonicalize_phone(phone)
	if not canonical or not canonical.startswith("+90"):
		frappe.local.response["http_status_code"] = 400
		frappe.throw(
			_("Please enter a valid Turkish phone number."),
			frappe.ValidationError,
		)

	# Reject if the new phone equals the current one. Both sides go through the
	# same canonicalizer so format-only differences (spaces, "+90" vs "0") don't
	# fool the comparison.
	old_phone_canonical = canonicalize_phone(frappe.db.get_value("User", user, "phone") or "")
	if old_phone_canonical and canonical == old_phone_canonical:
		frappe.local.response["http_status_code"] = 400
		frappe.throw(
			_("New phone number cannot be the same as your current phone number."),
			frappe.ValidationError,
		)

	# Verify password — returns 400 on failure (not 401)
	_verify_password(user, password)

	# Persist the canonical form everywhere — never the raw input.
	frappe.db.set_value("User", user, "phone", canonical)

	# Sprint 2.6: User Profile birleşik — tek phone field'ı. Eski Seller Profile.contact_phone
	# User Profile.phone'a birleşti; ayrı set ÇIKARILDI.
	user_profile = frappe.db.get_value("User Profile", {"user": user}, "name")
	if user_profile:
		frappe.db.set_value("User Profile", user_profile, "phone", canonical)

	seller_app = frappe.db.get_value("Seller Application", {"applicant_user": user}, "name")
	if seller_app:
		frappe.db.set_value("Seller Application", seller_app, "contact_phone", canonical)

	frappe.db.commit()

	return {"success": True, "message": _("Phone number updated successfully.")}


@frappe.whitelist(methods=["POST"])
def delete_account(password: str, reason: str = ""):
	"""Soft-delete the currently logged-in user's account.

	Requires the current password for security verification.
	The user is disabled (not physically deleted) so data can be recovered
	within a grace period.

	Session cleanup is handled by the frontend (calls /api/method/logout
	after receiving the success response).
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	# Verify password — returns 400 on failure (not 401)
	_verify_password(user, password)

	# Disable the user (soft-delete)
	frappe.db.set_value("User", user, "enabled", 0)

	# Deactivate Buyer Profile if exists
	buyer_profile = frappe.db.get_value("User Profile", {"user": user}, "name")
	if buyer_profile:
		frappe.db.set_value("User Profile", buyer_profile, "status", "Deactivated")

	# Deactivate Seller Profile if exists
	seller_profile = frappe.db.get_value("User Profile", {"user": user}, "name")
	if seller_profile:
		frappe.db.set_value("User Profile", seller_profile, "status", "Deactivated")

	# Log the deletion reason
	frappe.log_error(
		title=f"Account deletion: {user}",
		message=f"User {user} requested account deletion.\nReason: {reason or 'Not specified'}",
	)

	# Clear all active sessions for this user
	frappe.sessions.clear_sessions(user)

	frappe.db.commit()

	# Audit (Faz C — K12) — hesap silme kritik HIGH severity güvenlik olayı
	from tradehub_core.audit import log_decision

	log_decision(
		actor=user,
		action="identity.delete_account",
		decision="ALLOW",
		rule_id="auth.account_soft_deleted",
		layer="L2",
		object_doctype="User",
		object_name=user,
		severity="HIGH",
		context={
			"reason": (reason or "")[:200],
			"buyer_profile_deactivated": bool(buyer_profile),
			"seller_profile_deactivated": bool(seller_profile),
		},
	)

	return {"success": True, "message": _("Your account has been deleted.")}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=300)
def upload_private_file(filename: str = "", filedata: str = ""):
	"""Upload a file as private (e.g. identity documents).

	Accepts base64-encoded file content via JSON body.
	Files are stored in the private directory.
	Allowed during registration (guest) and for logged-in users.
	"""
	import base64

	if not filename or not filedata:
		frappe.throw(_("No file uploaded."))

	# Validate file type
	allowed_ext = (".pdf", ".jpg", ".jpeg", ".png")
	if not filename.lower().endswith(allowed_ext):
		frappe.throw(_("Only PDF, JPG, and PNG files are allowed."))

	# Strip data URI prefix if present (e.g. "data:image/png;base64,...")
	if "," in filedata:
		filedata = filedata.split(",", 1)[1]

	content = base64.b64decode(filedata)

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"content": content,
			"is_private": 1,
		}
	)
	file_doc.insert(ignore_permissions=True)
	frappe.db.commit()

	return {"file_url": file_doc.file_url}


@frappe.whitelist(methods=["POST"])
@require_verified_email
def become_seller():
	"""Create a Seller Application for an existing buyer account.

	Returns the application name so the frontend can redirect to the
	supplier setup form.
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	# Sprint 2.6: Mevcut Seller Application varsa, frontend form prefill için
	# tüm field'ları döndür. Kullanıcı yarım kalan Draft'ı "kaldığı yerden devam
	# eder" — Step 1'den boş başlamaz.
	existing = frappe.db.get_value(
		"Seller Application",
		{"applicant_user": user},
		[
			"name",
			"status",
			"seller_type",
			"business_name",
			"contact_phone",
			"tax_id_type",
			"tax_id",
			"tax_office",
			"address_line_1",
			"city",
			"country",
			"bank_name",
			"iban",
			"account_holder_name",
			"identity_document_type",
			"identity_document_number",
			"identity_document_expiry",
			"identity_document",
			"terms_accepted",
			"privacy_accepted",
			"kvkk_accepted",
			"commission_accepted",
			"return_policy_accepted",
		],
		as_dict=True,
	)
	if existing:
		return {
			"success": True,
			"seller_application": existing.name,
			"seller_application_status": existing.status,
			"already_exists": True,
			# Prefill için Draft field değerleri
			"data": {
				"seller_type": existing.seller_type or "",
				"business_name": existing.business_name or "",
				"contact_phone": existing.contact_phone or "",
				"tax_id_type": existing.tax_id_type or "",
				"tax_id": existing.tax_id or "",
				"tax_office": existing.tax_office or "",
				"address_line_1": existing.address_line_1 or "",
				"city": existing.city or "",
				"country": existing.country or "Turkey",
				"bank_name": existing.bank_name or "",
				"iban": existing.iban or "",
				"account_holder_name": existing.account_holder_name or "",
				"identity_document_type": existing.identity_document_type or "",
				"identity_document_number": existing.identity_document_number or "",
				"identity_document_expiry": str(existing.identity_document_expiry or ""),
				"identity_document": existing.identity_document or "",
				"terms_accepted": int(existing.terms_accepted or 0),
				"privacy_accepted": int(existing.privacy_accepted or 0),
				"kvkk_accepted": int(existing.kvkk_accepted or 0),
				"commission_accepted": int(existing.commission_accepted or 0),
				"return_policy_accepted": int(existing.return_policy_accepted or 0),
			},
		}

	# Generate member_id
	user_data = frappe.db.get_value("User", user, ["email", "creation", "phone"], as_dict=True)
	member_id = frappe.db.get_value("User Profile", {"user": user}, "member_id") or _generate_member_id(
		user_data.email, user_data.creation
	)

	app = frappe.new_doc("Seller Application")
	app.applicant_user = user
	app.member_id = member_id
	app.contact_email = user
	# user_data.phone may be a legacy non-canonical value; canonicalize before
	# copying it forward so the new application starts clean.
	app.contact_phone = canonicalize_phone(user_data.phone) or ""
	app.country = frappe.db.get_value("User Profile", {"user": user}, "country") or "Turkey"
	app.status = "Draft"
	# identity_document doctype-level reqd:1 — Draft skeleton burada boş insert
	# edilir; gerçek zorunluluk complete_registration_application'da set ile
	# birlikte Submitted save'de Frappe core tarafından + register_supplier'daki
	# explicit Türkçe validation tarafından enforced.
	app.flags.ignore_mandatory = True
	app.insert(ignore_permissions=True)
	frappe.db.commit()

	return {
		"success": True,
		"seller_application": app.name,
		"seller_application_status": app.status,
		"already_exists": False,
	}


@frappe.whitelist(methods=["POST"])
@require_verified_email
def complete_registration_application(
	seller_application,
	seller_type=None,
	business_name=None,
	contact_phone=None,
	tax_id_type=None,
	tax_id=None,
	tax_office=None,
	address_line_1=None,
	city=None,
	country=None,
	bank_name=None,
	iban=None,
	account_holder_name=None,
	identity_document_type=None,
	identity_document_number=None,
	identity_document_expiry=None,
	identity_document=None,
	terms_accepted=0,
	privacy_accepted=0,
	kvkk_accepted=0,
	commission_accepted=0,
	return_policy_accepted=0,
	requested_trial_plan=None,
):
	"""Complete a supplier registration application with business details.

	The caller must be the owner of the Seller Application.

	requested_trial_plan: Storefront'ta "X gün ücretsiz dene"ye tıklandıysa o paket
	(genelde PRO). Onayda bu paketin denemesi otomatik başlatılır
	(bkz. SellerApplication._start_trial_if_requested).
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	# Security: verify ownership
	app_data = frappe.db.get_value(
		"Seller Application",
		seller_application,
		["applicant_user", "status"],
		as_dict=True,
	)
	if not app_data or app_data.applicant_user != user:
		frappe.throw(
			_("You do not have permission to update this application."),
			frappe.PermissionError,
		)

	# Prevent modifying already reviewed applications
	if app_data.status in ("Approved", "Rejected", "Revoked"):
		frappe.throw(
			_("Cannot modify an already reviewed application."),
			frappe.ValidationError,
		)

	doc = frappe.get_doc("Seller Application", seller_application)

	# Trial niyeti — yalnızca geçerli bir Subscription Plan ise sakla (Link
	# field bütünlüğü + sahte değer enjeksiyonu önlemi).
	if requested_trial_plan and not frappe.db.exists("Subscription Plan", requested_trial_plan):
		requested_trial_plan = None

	# Canonicalize phone before assigning. Empty/None stays untouched; an
	# unparseable value is rejected.
	if contact_phone is not None and contact_phone != "":
		contact_phone_canonical = canonicalize_phone(contact_phone)
		if not contact_phone_canonical:
			frappe.throw(_("Please enter a valid Turkish phone number."), frappe.ValidationError)
		contact_phone = contact_phone_canonical

	# Assign all fields
	field_map = {
		"seller_type": seller_type,
		"business_name": business_name,
		"contact_phone": contact_phone,
		"tax_id_type": tax_id_type,
		"tax_id": tax_id,
		"tax_office": tax_office,
		"address_line_1": address_line_1,
		"city": city,
		"country": country,
		"bank_name": bank_name,
		"iban": iban,
		"account_holder_name": account_holder_name,
		"identity_document_type": identity_document_type,
		"identity_document_number": identity_document_number,
		"identity_document_expiry": identity_document_expiry,
		"identity_document": identity_document,
		"terms_accepted": int(terms_accepted),
		"privacy_accepted": int(privacy_accepted),
		"kvkk_accepted": int(kvkk_accepted),
		"commission_accepted": int(commission_accepted),
		"return_policy_accepted": int(return_policy_accepted),
		"requested_trial_plan": requested_trial_plan,
	}

	for field, value in field_map.items():
		if value is not None:
			doc.set(field, value)

	doc.status = "Submitted"
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True, "application": doc.name}

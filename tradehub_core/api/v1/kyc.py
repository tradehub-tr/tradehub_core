"""KYC Verification API — Sprint 2.6.

Endpoint'ler:
  - get_kyc_status: Kullanıcının mevcut KYC durumunu döner
  - submit_kyc_documents: KYC formu gönderimi (Kurumsal/Bireysel toggle)
  - review_kyc: Admin onay/red (Re-submit veya Suspended kategorisi)
  - get_prefill_data: Cross-form prefill (KYC + KYB ortak için)
"""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit


@frappe.whitelist(methods=["GET"])
def get_kyc_status() -> dict:
	"""Mevcut KYC kaydını ve durumunu döner. Kayıt yoksa null döner."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Giriş yapmalısınız."), frappe.AuthenticationError)

	kyc = frappe.db.get_value(
		"KYC Verification",
		{"user": user},
		[
			"name",
			"status",
			"account_type",
			"company_name",
			"tax_id",
			"phone",
			"email_field",
			"address",
			"billing_address",
			"identity_document",
			"rejection_reason",
			"rejection_category",
			"submitted_at",
			"reviewed_at",
		],
		as_dict=True,
	)
	if not kyc:
		return {"exists": False, "status": None}
	return {"exists": True, **kyc}


@frappe.whitelist(methods=["POST"])
@rate_limit(key="user", limit=1, seconds=60)
def submit_kyc_documents(
	account_type: str = "Business",
	identity_document: str = "",
	company_name: str = "",
	tax_id: str = "",
	phone: str = "",
	address: str = "",
	billing_address: str = "",
) -> dict:
	"""KYC belgesini ve bilgilerini gönder.

	Kurumsal (default): company_name, tax_id, phone, address, billing_address +
	identity_document zorunlu.
	Bireysel: sadece identity_document zorunlu.

	Resubmit (mevcut Rejected kayıt varsa):
	- Sadece status='Rejected' iken aynı kayıt Pending'e döner.
	- Throttle: dakikada 1 kez.
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Giriş yapmalısınız."), frappe.AuthenticationError)

	if account_type not in ("Business", "Individual"):
		account_type = "Business"

	if not (identity_document or "").strip():
		frappe.throw(_("Kimlik Belgesi zorunludur."), frappe.ValidationError)

	# Sprint 2.6: Hem Bireysel hem Kurumsal için ortak zorunlu alanlar.
	required = [
		("tax_id", tax_id, _("Vergi Numarası")),
		("phone", phone, _("Telefon")),
		("address", address, _("Adres")),
		("billing_address", billing_address, _("Fatura Adresi")),
	]
	if account_type == "Business":
		required.insert(0, ("company_name", company_name, _("Şirket Ünvanı")))

	missing = [label for _fname, value, label in required if not (value or "").strip()]
	if missing:
		frappe.throw(_("Eksik alan: {0}").format(", ".join(missing)), frappe.ValidationError)

	# Mevcut kayıt var mı?
	existing_name = frappe.db.get_value("KYC Verification", {"user": user}, "name")
	field_data = {
		"account_type": account_type,
		"identity_document": identity_document,
		"company_name": company_name if account_type == "Business" else "",
		"tax_id": tax_id,
		"phone": phone,
		"address": address,
		"billing_address": billing_address,
	}

	if existing_name:
		doc = frappe.get_doc("KYC Verification", existing_name)
		# Resubmit: sadece Rejected → Pending
		if doc.status == "Rejected":
			for k, v in field_data.items():
				doc.set(k, v)
			doc.status = "Pending"
			doc.rejection_reason = ""
			doc.rejection_category = ""
			doc.flags.ignore_permissions = True
			doc.save()
			frappe.db.commit()
			return {"success": True, "name": doc.name, "status": "Pending", "resubmit": True}
		if doc.status in ("Verified", "Suspended"):
			frappe.throw(
				_("KYC durumunuz '{0}' — yeni gönderim yapılamaz.").format(doc.status),
				frappe.ValidationError,
			)
		# Pending: aynı kayıt update
		for k, v in field_data.items():
			doc.set(k, v)
		doc.flags.ignore_permissions = True
		doc.save()
		frappe.db.commit()
		return {"success": True, "name": doc.name, "status": doc.status, "updated": True}

	# İlk başvuru
	doc = frappe.get_doc({"doctype": "KYC Verification", "user": user, **field_data})
	doc.flags.ignore_permissions = True
	doc.insert()
	frappe.db.commit()
	return {"success": True, "name": doc.name, "status": "Pending"}


@frappe.whitelist(methods=["POST"])
def review_kyc(
	name: str,
	decision: str,
	rejection_reason: str = "",
	rejection_category: str = "",
) -> dict:
	"""Admin onay/red. decision: 'Verified' | 'Rejected' | 'Suspended'.
	Rejected/Suspended için rejection_category (Re-submit | Suspended) zorunlu."""
	if not frappe.has_permission("KYC Verification", "write"):
		frappe.throw(_("Yetkiniz yok."), frappe.PermissionError)

	if decision not in ("Verified", "Rejected", "Suspended"):
		frappe.throw(_("Geçersiz karar."), frappe.ValidationError)

	doc = frappe.get_doc("KYC Verification", name)
	doc.status = decision
	if decision in ("Rejected", "Suspended"):
		doc.rejection_reason = rejection_reason
		doc.rejection_category = rejection_category or (
			"Suspended" if decision == "Suspended" else "Re-submit"
		)
	doc.save()
	frappe.db.commit()
	return {"success": True, "name": doc.name, "status": decision}


@frappe.whitelist(methods=["POST"])
def unlock_for_self() -> dict:
	"""Sprint 2.6: Satıcı kullanıcı 'KYC doldurmaya başla' deyince kyc_status
	Locked → Pending'e geçer. Form sayfası açılır, kullanıcı KYC bilgilerini
	doldurabilir. Admin onayı sonrası Verified olur.

	Bireysel/Şirket toggle KYC formunda. Bu endpoint sadece state geçişi için.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Giriş yapmalısınız."), frappe.AuthenticationError)

	up_name = frappe.db.get_value("User Profile", {"user": user}, "name")
	if not up_name:
		frappe.throw(_("Kullanıcı profili bulunamadı."), frappe.ValidationError)

	current = frappe.db.get_value("User Profile", up_name, "kyc_status")
	if current == "Locked":
		frappe.db.set_value("User Profile", up_name, "kyc_status", "Pending", update_modified=False)
		frappe.db.commit()
	return {"success": True, "kyc_status": "Pending"}


@frappe.whitelist(methods=["POST"])
def unlock_kyb_for_self() -> dict:
	"""Sprint 2.6: Alıcı kullanıcı 'Satıcı başvurusu' yaptıktan ve admin onayı
	sonrasında otomatik kyb_status Pending'e döner — bu endpoint sadece edge
	case'ler için (manuel KYB başlatma). Şu an çağrılmıyor."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Giriş yapmalısınız."), frappe.AuthenticationError)
	up_name = frappe.db.get_value("User Profile", {"user": user}, "name")
	if not up_name:
		frappe.throw(_("Kullanıcı profili bulunamadı."), frappe.ValidationError)
	current = frappe.db.get_value("User Profile", up_name, "kyb_status")
	if current == "Locked":
		frappe.db.set_value("User Profile", up_name, "kyb_status", "Pending", update_modified=False)
		frappe.db.commit()
	return {"success": True, "kyb_status": "Pending"}


@frappe.whitelist(methods=["GET"])
def get_prefill_data() -> dict:
	"""KYC/KYB formları için kullanıcının mevcut bilgilerini döner.

	Sprint 2.6: Kullanıcı tekrar yazmak zorunda kalmasın — User Profile +
	en son KYC/KYB Verification'dan değerleri birleştir.
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Giriş yapmalısınız."), frappe.AuthenticationError)

	up = (
		frappe.db.get_value(
			"User Profile",
			{"user": user},
			["company_name", "tax_id", "phone", "account_type", "full_name"],
			as_dict=True,
		)
		or {}
	)
	user_data = frappe.db.get_value("User", user, ["email", "first_name", "last_name"], as_dict=True) or {}
	last_kyc = (
		frappe.db.get_value(
			"KYC Verification",
			{"user": user},
			[
				"account_type",
				"company_name",
				"tax_id",
				"phone",
				"address",
				"billing_address",
				"identity_document",
			],
			as_dict=True,
			order_by="creation desc",
		)
		or {}
	)
	last_kyb = (
		frappe.db.get_value(
			"KYB Verification",
			{"user": user},
			[
				"company_title",
				"authorized_person",
				"trade_registry_number",
				"mersis_no",
				"kep_address",
				"identity_document",
				"imza_sirkuleri",
				"ticaret_sicil_gazetesi",
				"faaliyet_belgesi",
				"vergi_levhasi",
				"bank_account_document",
			],
			as_dict=True,
			order_by="creation desc",
		)
		or {}
	)

	return {
		"email": user_data.get("email") or user,
		"first_name": user_data.get("first_name") or "",
		"last_name": user_data.get("last_name") or "",
		# User Profile (cross-form sync hedefi)
		"account_type": up.get("account_type") or last_kyc.get("account_type") or "Business",
		"company_name": up.get("company_name")
		or last_kyc.get("company_name")
		or last_kyb.get("company_title")
		or "",
		"tax_id": up.get("tax_id") or last_kyc.get("tax_id") or "",
		"phone": up.get("phone") or last_kyc.get("phone") or "",
		"full_name": up.get("full_name") or "",
		# KYC'ye özel
		"address": last_kyc.get("address") or "",
		"billing_address": last_kyc.get("billing_address") or "",
		"identity_document": last_kyc.get("identity_document") or last_kyb.get("identity_document") or "",
		# KYB'ye özel
		"company_title": last_kyb.get("company_title") or up.get("company_name") or "",
		"authorized_person": last_kyb.get("authorized_person") or "",
		"trade_registry_number": last_kyb.get("trade_registry_number") or "",
		"mersis_no": last_kyb.get("mersis_no") or "",
		"kep_address": last_kyb.get("kep_address") or "",
		"imza_sirkuleri": last_kyb.get("imza_sirkuleri") or "",
		"ticaret_sicil_gazetesi": last_kyb.get("ticaret_sicil_gazetesi") or "",
		"faaliyet_belgesi": last_kyb.get("faaliyet_belgesi") or "",
		"vergi_levhasi": last_kyb.get("vergi_levhasi") or "",
		"bank_account_document": last_kyb.get("bank_account_document") or "",
	}

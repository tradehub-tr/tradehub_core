"""Patch 19 — Sprint 2.6: KYC Verification DocType split + KYB refactor.

1. KYC Verification DocType yarat (yeni)
2. Mevcut KYB Verification(verification_kind=KYC) kayıtlarını yeni KYC Verification'a taşı
3. KYB Verification.verification_kind + document_expiry_date field'larını sil
4. User Profile.kyc_status / kyb_status Select option'ları güncelle (Locked + Suspended ekle, Expired temizle)
5. Mevcut 4 hibrit kullanıcıya kyc_status=Pending, kyb_status=Pending set (Soru 2-B cevabı)

Idempotent — defalarca koşulabilir.
"""

import frappe


def execute():
	_create_kyc_verification_doctype()
	_migrate_kyc_kind_records()
	_drop_kyb_legacy_fields()
	_update_user_profile_status_options()
	_set_hybrid_users_pending()
	frappe.db.commit()
	frappe.clear_cache()


def _create_kyc_verification_doctype():
	"""KYC Verification DocType reload-doc ile yaratılır.

	Frappe migrate flow'unda DocType JSON otomatik DB'ye yansır;
	bu patch sadece güvence için reload tetikler."""
	if not frappe.db.exists("DocType", "KYC Verification"):
		# DocType JSON'dan otomatik create için reload-doc
		frappe.reload_doc("tradehub_core", "doctype", "kyc_verification")


def _migrate_kyc_kind_records():
	"""Eski KYB Verification(verification_kind='KYC') kayıtları → yeni KYC Verification."""
	if not frappe.db.has_column("KYB Verification", "verification_kind"):
		return

	kyc_records = frappe.db.sql(
		"""SELECT name, user, status, identity_document, creation, modified
		   FROM `tabKYB Verification`
		   WHERE verification_kind = 'KYC'""",
		as_dict=True,
	)
	for r in kyc_records:
		# Yeni KYC Verification kaydı yarat (sadece taşıma — Bireysel default)
		if frappe.db.exists("KYC Verification", {"user": r["user"]}):
			continue
		new_kyc = frappe.get_doc(
			{
				"doctype": "KYC Verification",
				"user": r["user"],
				"account_type": "Individual",  # Eski KYC = bireysel kimlik
				"status": r["status"],
				"identity_document": r["identity_document"],
			}
		)
		new_kyc.flags.ignore_validate = True
		new_kyc.flags.ignore_permissions = True
		new_kyc.insert(ignore_permissions=True)

	# Taşınan kayıtları eski tabloda işaretle (silmek riskli, audit için tut)
	frappe.db.sql(
		"""UPDATE `tabKYB Verification`
		   SET status = 'Rejected'
		   WHERE verification_kind = 'KYC' AND status != 'Rejected'"""
	)


def _drop_kyb_legacy_fields():
	"""KYB Verification.verification_kind ve document_expiry_date kolonlarını sil.
	DDL (ALTER TABLE) implicit commit yapar — Frappe ImplicitCommitError'u
	önlemek için explicit commit çağırıyoruz."""
	for col in ("verification_kind", "document_expiry_date"):
		if frappe.db.has_column("KYB Verification", col):
			frappe.db.commit()  # noqa: SLF001 — DDL öncesi pending tx temizle
			frappe.db.sql_ddl(f"ALTER TABLE `tabKYB Verification` DROP COLUMN `{col}`")


def _update_user_profile_status_options():
	"""kyc_status / kyb_status Select option'larını güncelle.
	Mevcut Expired/Locked/Suspended değerlerini normalize et."""
	# Expired olan kyb_status'ları temizle (Soru 8 — expiry yok)
	frappe.db.sql(
		"""UPDATE `tabUser Profile`
		   SET kyb_status = 'Pending'
		   WHERE kyb_status = 'Expired'"""
	)


def _set_hybrid_users_pending():
	"""Soru 2-B cevabı: Mevcut hibrit kullanıcılara (can_buy=1+can_sell=1)
	kyc_status=Pending, kyb_status=Pending set — dev'de gerçek akış test edilebilsin.

	Idempotent: NULL veya boş olanlara set, mevcut değerleri korur."""
	frappe.db.sql(
		"""UPDATE `tabUser Profile`
		   SET kyc_status = 'Pending'
		   WHERE can_buy = 1 AND (kyc_status IS NULL OR kyc_status = '')"""
	)
	frappe.db.sql(
		"""UPDATE `tabUser Profile`
		   SET kyb_status = 'Pending'
		   WHERE can_sell = 1 AND (kyb_status IS NULL OR kyb_status = '')"""
	)
	# Pure Buyer'lara (can_sell=0) kyb_status = Locked
	frappe.db.sql(
		"""UPDATE `tabUser Profile`
		   SET kyb_status = 'Locked'
		   WHERE can_sell = 0 AND (kyb_status IS NULL OR kyb_status = '')"""
	)
	# Pure Seller'lara (can_buy=0) kyc_status = Locked
	frappe.db.sql(
		"""UPDATE `tabUser Profile`
		   SET kyc_status = 'Locked'
		   WHERE can_buy = 0 AND (kyc_status IS NULL OR kyc_status = '')"""
	)

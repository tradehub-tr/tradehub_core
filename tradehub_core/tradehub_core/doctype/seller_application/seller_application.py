import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, now_datetime

from tradehub_core.utils.notify import notify


class SellerApplication(Document):
	def on_update(self):
		if self.has_value_changed("status"):
			if self.status == "Approved":
				self._approve_application()
				self._notify_applicant_approved()
			elif self.status == "Rejected":
				self._revoke_approval()
				self._notify_applicant_rejected()
			elif self.status in ("Submitted", "Under Review", "Draft"):
				self._revoke_approval()
			if self.status == "Submitted":
				self._notify_admin_new_application()
				self._notify_applicant_received()

	def _approve_application(self):
		"""Sprint 2 — User Profile birleşmesi sonrası yeni onay akışı:
		1. User Profile.can_sell=1 set (mevcut User Profile var, kayıtta yaratıldı)
		2. account_type=Business zorla (Seller olmak için zorunlu - S6/S28)
		3. Admin Seller Profile yarat (mağaza entity)
		4. KYB Verification yarat (verification_kind=KYB - S26)
		5. User'a Seller + Seller Owner rolleri ekle, tradehub_is_owner=1,
		   tradehub_tenant=ASP.name, role_profile_name="Seller Full Access" set
		   (Sprint 3 RBAC: Owner çift kapı kontrolü → auth.is_owner için zorunlu)."""
		user = self.applicant_user
		seller_name = self.business_name or frappe.db.get_value("User", user, "full_name") or user

		# ───── 1+2. User Profile güncellemesi (can_sell=1 + account_type=Business) ─────
		# Sprint 2: User Profile mevcut (register sırasında yaratıldı). Buradaki başvuru
		# kullanıcının "satıcı olmak istiyorum" talebi — UP.can_sell=1 + Business yapılır.
		up_name = frappe.db.get_value("User Profile", {"user": user}, "name")
		if up_name:
			# Sprint 2.6 (revised): can_sell KYB Verified anında set edilir, başvuru onayında değil
			up_updates = {
				"account_type": "Business",  # Bloker 1: Seller zorunlu Business
				"migrated_from_seller_profile": self.name,
			}
			# Seller-özel field'ları User Profile'a kopyala (eksikse)
			current = (
				frappe.db.get_value(
					"User Profile",
					up_name,
					[
						"company_name",
						"tax_id",
						"tax_id_type",
						"tax_office",
						"bank_name",
						"iban",
						"account_holder_name",
						"phone",
					],
					as_dict=True,
				)
				or {}
			)
			if not current.get("company_name") and self.business_name:
				up_updates["company_name"] = self.business_name[:140]
			if not current.get("tax_id") and self.tax_id:
				up_updates["tax_id"] = self.tax_id
			if not current.get("tax_id_type") and self.tax_id_type:
				up_updates["tax_id_type"] = self.tax_id_type
			if not current.get("tax_office") and self.tax_office:
				up_updates["tax_office"] = self.tax_office
			if not current.get("bank_name") and self.bank_name:
				up_updates["bank_name"] = self.bank_name
			if not current.get("iban") and self.iban:
				up_updates["iban"] = self.iban
			if not current.get("account_holder_name") and self.account_holder_name:
				up_updates["account_holder_name"] = self.account_holder_name
			if not current.get("phone") and self.contact_phone:
				up_updates["phone"] = (self.contact_phone or "")[:20]

			# frappe.db.set_value — controller hook bypass (set_value tek call multi-field)
			frappe.db.set_value("User Profile", up_name, up_updates, update_modified=False)
		else:
			# User Profile yoksa (edge case — register akışı atlanmış) yarat
			frappe.log_error(
				title="Seller Application: User Profile bulunamadı",
				message=f"User {user} için User Profile yok; minimum User Profile yaratılıyor.",
			)
			frappe.db.sql(
				"""
				INSERT INTO `tabUser Profile` (
					name, user, can_buy, can_sell, status, account_type,
					full_name, phone, country, company_name, tax_id, tax_id_type, tax_office,
					bank_name, iban, account_holder_name,
					created_via, migrated_at, migrated_from_seller_profile,
					creation, modified, owner, modified_by, docstatus
				) VALUES (
					%(user)s, %(user)s, 1, 1, 'Active', 'Business',
					%(full_name)s, %(phone)s, %(country)s, %(company_name)s,
					%(tax_id)s, %(tax_id_type)s, %(tax_office)s,
					%(bank_name)s, %(iban)s, %(account_holder_name)s,
					'seller_application', NOW(), %(sa_name)s,
					NOW(), NOW(), %(user)s, %(user)s, 0
				)
			""",
				{
					"user": user,
					"full_name": seller_name[:140],
					"phone": (self.contact_phone or "")[:20],
					"country": self.country,
					"company_name": (self.business_name or seller_name)[:140],
					"tax_id": self.tax_id,
					"tax_id_type": self.tax_id_type,
					"tax_office": self.tax_office,
					"bank_name": self.bank_name,
					"iban": self.iban,
					"account_holder_name": self.account_holder_name,
					"sa_name": self.name,
				},
			)

		# ───── 3. Admin Seller Profile yarat (mağaza entity — değişmedi) ─────
		asp_name = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
		if not asp_name:
			count = (frappe.db.count("Admin Seller Profile") or 0) + 1
			seller_code = f"SEL-{count:05d}"

			admin_profile = frappe.new_doc("Admin Seller Profile")
			admin_profile.seller_code = seller_code
			admin_profile.user = user
			admin_profile.seller_name = seller_name
			admin_profile.company_name = self.business_name or seller_name
			admin_profile.email = frappe.db.get_value("User", user, "email") or self.contact_email or ""
			admin_profile.tax_id = self.tax_id or ""
			admin_profile.phone = self.contact_phone or ""
			admin_profile.country = self.country or "Turkey"
			admin_profile.bank_name = self.bank_name or ""
			admin_profile.iban = self.iban or ""
			admin_profile.account_holder = self.account_holder_name or ""
			admin_profile.status = "Active"
			admin_profile.flags.ignore_permissions = True
			admin_profile.owner = user
			admin_profile.insert(ignore_permissions=True)
			frappe.db.set_value("Admin Seller Profile", admin_profile.name, "owner", user)
			asp_name = admin_profile.name

		# ───── 3b. User'ı kendi tenant'ına bağla + Owner flag + role_profile ─────
		# Sprint 3 RBAC: auth.is_owner = bool(tradehub_is_owner) AND "Seller Owner" in roles.
		# Owner mağazasına bağlı olmalı (tenant_link) ki sub-user davetleri ve
		# capability resolver çalışsın. role_profile_name = "Seller Full Access"
		# Owner'a tüm capability'leri (Admin + Finance + Staff + Viewer) verir.
		user_updates: dict[str, object] = {"tradehub_is_owner": 1, "tradehub_tenant": asp_name}
		if not frappe.db.get_value("User", user, "role_profile_name"):
			user_updates["role_profile_name"] = "Seller Full Access"
		frappe.db.set_value("User", user, user_updates, update_modified=False)

		# ───── 4. KYB Verification yarat (Sprint 2.6: verification_kind kaldırıldı) ─────
		seller_type_map = {
			"Individual": "Şahıs",
			"Business": "Limited Şirket",
			"Enterprise": "Anonim Şirket",
		}
		kyb_data = {
			"company_title": self.business_name or seller_name,
			"business_type": seller_type_map.get(self.seller_type, "") or self.seller_type or "",
			"authorized_person": seller_name,
			"tax_id_type": self.tax_id_type or "TCKN",
			"tax_id": self.tax_id or "",
			"tax_office": self.tax_office or "",
		}

		existing_kyb = frappe.db.get_value("KYB Verification", {"user": user}, "name")
		if existing_kyb:
			for field, value in kyb_data.items():
				frappe.db.set_value("KYB Verification", existing_kyb, field, value)
			frappe.db.set_value("KYB Verification", existing_kyb, "status", "Draft")
			frappe.db.set_value("KYB Verification", existing_kyb, "owner", user)
		else:
			kyb = frappe.new_doc("KYB Verification")
			kyb.user = user
			kyb.owner = user
			kyb.status = "Draft"
			for field, value in kyb_data.items():
				kyb.set(field, value)
			kyb.flags.ignore_permissions = True
			kyb.flags.ignore_mandatory = True
			kyb.insert(ignore_permissions=True)
			frappe.db.set_value("KYB Verification", kyb.name, "owner", user)

		# ───── 5. Seller + Seller Owner rolleri (Sprint 3 RBAC) ─────
		# auth.is_owner çift kapı: tradehub_is_owner=1 AND "Seller Owner" in roles.
		# İkisi de bu fonksiyonda set ediliyor (yukarıda flag, burada rol).
		current_roles = set(frappe.get_roles(user))
		missing_roles = [r for r in ("Seller", "Seller Owner") if r not in current_roles]
		if missing_roles:
			user_doc = frappe.get_doc("User", user)
			user_doc.add_roles(*missing_roles)

		# ───── 6. User Profile.kyb_status sync ─────
		if up_name:
			frappe.db.set_value("User Profile", up_name, "kyb_status", "Pending", update_modified=False)

		# ───── 7. Trial talep edildiyse 14 günlük deneme aboneliğini başlat ─────
		self._start_trial_if_requested(asp_name)

		# Record review metadata
		self.db_set("reviewed_by", frappe.session.user)
		self.db_set("reviewed_on", now_datetime())

	def _start_trial_if_requested(self, tenant: str) -> None:
		"""Başvuruda `requested_trial_plan` doluysa onayda deneme aboneliğini başlat.

		Doğrudan Store Subscription oluşturur (upgrade_subscription_plan'ı çağırmaz —
		o fonksiyon doc-event içinde sakıncalı `frappe.db.commit()` yapar ve gereksiz
		role-sync tetikler; yeni satıcının henüz sub-user'ı yok).

		Idempotent: mağazanın zaten bir Store Subscription'ı varsa atla (re-approve
		guard). trial_days > 0 ve plan aktif değilse deneme başlatılmaz.
		"""
		plan_code = (self.get("requested_trial_plan") or "").strip()
		if not plan_code or not tenant:
			return
		if frappe.db.exists("Store Subscription", {"store": tenant}):
			return  # idempotent: zaten abonelik var
		if not frappe.db.exists("Subscription Plan", plan_code):
			return
		plan = frappe.get_cached_doc("Subscription Plan", plan_code)
		if not plan.is_active:
			return
		trial_days = int(plan.get("trial_days") or 0)
		if trial_days <= 0:
			return  # plan'da trial tanımı yoksa deneme verme

		now = now_datetime()
		sub = frappe.new_doc("Store Subscription")
		sub.store = tenant
		sub.plan = plan_code
		sub.status = "trial"
		sub.started_at = now
		sub.current_period_start = now
		sub.trial_start = now
		sub.trial_end = add_days(now, trial_days)
		sub.trial_plan = plan_code
		sub.trial_used = 1
		sub.flags.ignore_permissions = True
		sub.insert(ignore_permissions=True)

	def _revoke_approval(self):
		"""Sprint 2 — Onay geri çekme: User Profile.can_sell=0 + Admin Seller Profile suspend.
		Sprint 3 RBAC: Seller Owner rolü + tradehub_is_owner flag de geri alınır."""
		user = self.applicant_user

		# Seller + Seller Owner rollerini kaldır
		current_roles = set(frappe.get_roles(user))
		to_remove = [r for r in ("Seller", "Seller Owner") if r in current_roles]
		if to_remove:
			user_doc = frappe.get_doc("User", user)
			user_doc.remove_roles(*to_remove)

		# Owner flag'ini sıfırla (tradehub_tenant link'ini koruyoruz —
		# Suspended ASP hâlâ aynı user'a ait, link sub-user davetleri için referans)
		frappe.db.set_value("User", user, "tradehub_is_owner", 0, update_modified=False)

		# User Profile.can_sell=0 set et (account_type Business kalır — TEK YÖNLÜ upgrade kuralı)
		up_name = frappe.db.get_value("User Profile", {"user": user}, "name")
		if up_name:
			frappe.db.set_value(
				"User Profile",
				up_name,
				{"can_sell": 0, "kyb_status": ""},
				update_modified=False,
			)

		# Admin Seller Profile suspend
		existing_asp = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
		if existing_asp:
			frappe.db.set_value("Admin Seller Profile", existing_asp, "status", "Suspended")

		# Update review metadata
		self.db_set("reviewed_by", frappe.session.user)
		self.db_set("reviewed_on", now_datetime())

	def _notify_applicant_received(self):
		"""Başvuru oluşturulduğunda (Submitted) applicant'a in-app bildirim.

		Mail için: send_email=True + email_subject + email_body parametreleri
		ileride eklenecek (memory: project_seller_application_email_followup).
		Mevcut çağrı sadece Platform Notification kaydı oluşturur.
		"""
		# action_url: admin-panel /dashboard. Başvuran henüz seller değil ama
		# onay sonrası seller olunca eski bildirime tıklayabilir; admin-panel'in
		# anasayfası tüm rollar için güvenli landing.
		notify(
			recipient_user=self.applicant_user,
			recipient_role="seller",
			type="system",
			title=_("Başvurunuz Alındı"),
			message=_("Satıcı başvurunuz başarıyla alındı. İncelendikten sonra size haber vereceğiz."),
			action_url="/dashboard",
			reference_doctype="Seller Application",
			reference_name=self.name,
		)

	def _notify_applicant_approved(self):
		notify(
			recipient_user=self.applicant_user,
			recipient_role="seller",
			type="system",
			title=_("Başvurunuz Onaylandı"),
			message=_("Satıcı başvurunuz onaylandı. Artık ürün listelemeye başlayabilirsiniz."),
			action_url="/dashboard",
			reference_doctype="Seller Application",
			reference_name=self.name,
		)

	def _notify_applicant_rejected(self):
		notify(
			recipient_user=self.applicant_user,
			recipient_role="seller",
			type="system",
			title=_("Başvurunuz Reddedildi"),
			message=_("Satıcı başvurunuz reddedildi. Detaylar için destek ile iletişime geçin."),
			action_url="/dashboard",
			reference_doctype="Seller Application",
			reference_name=self.name,
		)

	def _notify_admin_new_application(self):
		admins = frappe.get_all(
			"Has Role",
			filters={"role": "System Manager", "parenttype": "User"},
			fields=["parent"],
		)
		seller_name = self.business_name or self.applicant_user
		for admin in admins:
			# Aynı başvuru için admin'e zaten bildirim gittiyse tekrar gönderme
			existing = frappe.db.exists(
				"Platform Notification",
				{
					"recipient_user": admin.parent,
					"reference_doctype": "Seller Application",
					"reference_name": self.name,
					"type": "system",
				},
			)
			if existing:
				continue
			notify(
				recipient_user=admin.parent,
				recipient_role="admin",
				type="system",
				title=_("Yeni Satıcı Başvurusu"),
				message=_("{0} yeni satıcı başvurusu yaptı.").format(seller_name),
				action_url=f"/app/seller-application/{self.name}",
				reference_doctype="Seller Application",
				reference_name=self.name,
			)

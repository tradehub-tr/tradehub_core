# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 2.4 — B2B alıcı sub-user yönetim API.

Seller paralel'i (`seller_users.py`); fakat tenant Admin Seller Profile yerine
CRM Organization (buyer_org). Buyer Admin/Procurement/Finance vs roller için
plan kelepçesi: `feature.role.profile.buyer_*`.

Endpoints:
  - invite_buyer_sub_user(email, full_name, role_profile, organization)
  - list_buyer_sub_users(organization=None)
  - update_buyer_sub_user_role(user, role_profile)
  - deactivate_buyer_sub_user(user, reason)
  - reactivate_buyer_sub_user(user)
  - revoke_buyer_invite(invite_name, reason)
  - accept_buyer_invite(token, full_name, password)  → allow_guest=True

Detay: docs/yetki/faz-2/03-faz-2-detayli-plan.md §2.4
"""

from __future__ import annotations

import hashlib
import secrets

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime

from tradehub_core.audit import log_role_change
from tradehub_core.entitlement import (
	check_feature_or_throw,
	check_quota_or_throw,
)

_TOKEN_BYTES = 32
_INVITE_TTL_DAYS = 7


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_user_organization(user: str | None = None) -> str | None:
	"""Caller user'ın bağlı olduğu buyer organization."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return None
	return frappe.db.get_value("User", user, "tradehub_parent_organization")


def _require_buyer_admin(action: str = "") -> str:
	"""Caller Buyer Admin mi? Yoksa PermissionError.

	Buyer Admin = Buyer Full Access rol profile veya Buyer Admin rolü olan
	+ tradehub_parent_organization tanımlı kullanıcı.

	Returns:
	    organization name
	"""
	organization = _get_user_organization()
	if not organization:
		frappe.throw(
			_("B2B ekip yönetimi için bir Organization'a bağlı olmanız gerekir."),
			frappe.PermissionError,
		)

	user = frappe.session.user
	roles = set(frappe.get_roles(user))

	# System Manager / Marketplace Admin bypass
	if "System Manager" in roles or "Marketplace Admin" in roles:
		return organization

	# Buyer Admin rolü VE Buyer Full Access profili
	is_buyer_admin = "Buyer Admin" in roles
	profile = frappe.db.get_value("User", user, "role_profile_name")
	is_full_access = profile == "Buyer Full Access"

	if not (is_buyer_admin or is_full_access):
		frappe.throw(
			_("Bu işlem için Buyer Admin (Buyer Full Access) yetkisi gerekir."),
			frappe.PermissionError,
		)

	return organization


def _hash_token(raw_token: str) -> str:
	return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _generate_invite_token() -> tuple[str, str]:
	raw = secrets.token_urlsafe(_TOKEN_BYTES)
	return raw, _hash_token(raw)


def _validate_role_profile_for_plan(organization: str, role_profile: str) -> None:
	"""Plan kelepçesi — bu organization'ın aktif plan'ında bu role profile var mı?

	Buyer ile satıcı planı farklı olabilir. Faz 2.4'te aynı subscription
	üzerinden gidiyoruz (bir tenant = bir plan); buyer_org kendi planına
	sahip değil, mevcut yapıda sub-user'lar Admin Seller Profile (= tenant)'a
	bağlı.

	Pragmatik: caller (Buyer Admin) hangi tenant'a bağlı? Onun planı kullanılır.
	"""
	# Profile name → feature key
	code = role_profile.lower().replace(" ", "_").replace("-", "_")
	feature_key = f"feature.role.profile.{code}"

	# Caller'ın tenant'ı (B2B alıcı için Organization'ın bağlı olduğu Admin Seller Profile;
	# Faz 2.4'te ayrı subscription yok — Faz 3'te buyer-side subscription gelir).
	# Şimdilik global plan kontrolü için: bu organization'ın "host" satıcısı varsayılıyor
	# (büyük holding/buyer'lar genelde Pro+ plan'a sahip).
	#
	# Pratik: Faz 2.4'te tenant Buyer-side için Admin Seller Profile olmayabilir.
	# Bu durumda has_feature(None, ...) → False döner; kontrol geçilir.
	# Faz 3'te buyer-side subscription doctype eklenince burada güzelce kontrol edilir.

	# Pragmatik: caller'ın tenant'ı yoksa "Pro plan varsayılır" (B2B alıcı için).
	# Bu Faz 2.4'ün ölçeklendirme limiti — Faz 3'te düzeltilir.
	from tradehub_core.entitlement import has_feature
	from tradehub_core.utils.tenant import get_current_seller_profile

	tenant = get_current_seller_profile()
	if not tenant:
		# Buyer-only kullanıcı için: organization'ın bir "host plan"ı var mı?
		# Şu an Plan kontrolü skip (Faz 3'te detaylanır).
		return

	# feature key veya custom creation
	if not has_feature(tenant, feature_key) and not has_feature(tenant, "feature.role.custom_creation"):
		check_feature_or_throw(
			tenant,
			feature_key,
			action_description=_("'{0}' Buyer rol profili atama").format(role_profile),
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@frappe.whitelist()
def invite_buyer_sub_user(
	email: str, full_name: str, role_profile: str, organization: str | None = None
) -> dict:
	"""Yeni buyer sub-user davet et.

	Args:
	    email: Davet edilecek e-posta
	    full_name: Ad soyad
	    role_profile: 'Buyer Full Access', 'Buyer Operations', vb.
	    organization: Hedef Organization (None ise caller'ın org'u)

	Returns:
	    {"invite_name", "expires_at", "message"}
	"""
	caller_org = _require_buyer_admin()
	target_org = organization or caller_org

	# Caller başka org'a davet edemez (Marketplace Admin bypass)
	if target_org != caller_org:
		roles = set(frappe.get_roles(frappe.session.user))
		if "System Manager" not in roles and "Marketplace Admin" not in roles:
			frappe.throw(
				_("Başka organization'a davet gönderme yetkiniz yok."),
				frappe.PermissionError,
			)

	email = (email or "").strip().lower()
	if not email or "@" not in email:
		frappe.throw(_("Geçerli bir e-posta girin."))

	# Duplicate kontrol
	if frappe.db.exists("User", email):
		existing_org = frappe.db.get_value("User", email, "tradehub_parent_organization")
		if existing_org == target_org:
			frappe.throw(_("Bu e-posta zaten ekibinizde mevcut."))
		else:
			frappe.throw(_("Bu e-posta başka bir organizasyona bağlı."))

	if frappe.db.exists(
		"Buyer Sub User Invite",
		{"email": email, "organization": target_org, "status": "Pending"},
	):
		frappe.throw(_("Bu e-postaya zaten aktif bir davet gönderilmiş."))

	# Kota: max_sub_users (Faz 2.4'te buyer-side için aynı limit kullanılıyor)
	current_count = frappe.db.count("User", {"tradehub_parent_organization": target_org, "enabled": 1})
	from tradehub_core.utils.tenant import get_current_seller_profile

	tenant_for_quota = get_current_seller_profile()
	if tenant_for_quota:
		check_quota_or_throw(
			tenant_for_quota,
			"quota.max_sub_users",
			current_count,
			action_description=_("Yeni B2B çalışan daveti"),
		)

	# Plan kelepçesi
	_validate_role_profile_for_plan(target_org, role_profile)

	# Token üret
	raw_token, token_hash = _generate_invite_token()
	expires_at = add_days(now_datetime(), _INVITE_TTL_DAYS)

	invite = frappe.get_doc(
		{
			"doctype": "Buyer Sub User Invite",
			"email": email,
			"full_name": full_name,
			"organization": target_org,
			"role_profile": role_profile,
			"status": "Pending",
			"invited_by": frappe.session.user,
			"expires_at": expires_at,
			"token_hash": token_hash,
		}
	)
	invite.insert(ignore_permissions=True)

	# E-posta
	invite_url = _build_invite_url(raw_token)
	try:
		_send_invite_email(invite, invite_url)
	except Exception as exc:
		frappe.log_error(f"Buyer davet e-postası gönderilemedi: {exc}", "invite_buyer_sub_user")

	frappe.db.commit()
	return {
		"invite_name": invite.name,
		"invite_url": invite_url if "System Manager" in frappe.get_roles() else None,
		"expires_at": str(expires_at),
		"message": _("B2B davet e-postası gönderildi: {0}").format(email),
	}


@frappe.whitelist()
def list_buyer_sub_users(organization: str | None = None) -> dict:
	"""Bir organization'ın tüm buyer sub-user'larını + pending invite'ları döner."""
	caller_org = _require_buyer_admin()
	target_org = organization or caller_org

	if target_org != caller_org:
		roles = set(frappe.get_roles(frappe.session.user))
		if "System Manager" not in roles and "Marketplace Admin" not in roles:
			frappe.throw(_("Başka organization'ın ekibini göremezsiniz."), frappe.PermissionError)

	users = frappe.get_all(
		"User",
		filters={"tradehub_parent_organization": target_org},
		fields=[
			"name",
			"email",
			"full_name",
			"enabled",
			"role_profile_name",
			"last_login",
		],
		order_by="creation desc",
	)

	invites = frappe.get_all(
		"Buyer Sub User Invite",
		filters={"organization": target_org, "status": "Pending"},
		fields=["name", "email", "full_name", "role_profile", "expires_at", "invited_by"],
		order_by="creation desc",
	)

	return {"organization": target_org, "users": users, "pending_invites": invites}


@frappe.whitelist()
def update_buyer_sub_user_role(user: str, role_profile: str) -> dict:
	"""Buyer sub-user rol profile güncelle."""
	caller_org = _require_buyer_admin()

	user_org = frappe.db.get_value("User", user, "tradehub_parent_organization")
	if user_org != caller_org:
		frappe.throw(_("Bu kullanıcı ekibinizde değil."), frappe.PermissionError)

	_validate_role_profile_for_plan(caller_org, role_profile)

	old_profile = frappe.db.get_value("User", user, "role_profile_name")

	user_doc = frappe.get_doc("User", user)
	user_doc.role_profile_name = role_profile
	user_doc.save(ignore_permissions=True)

	log_role_change(
		target_user=user,
		change_type="profile_change",
		tenant=caller_org,
		before_role_profiles=[old_profile] if old_profile else [],
		after_role_profiles=[role_profile],
		reason=f"Buyer team — Updated by {frappe.session.user}",
	)

	frappe.db.commit()
	return {"message": _("Buyer rol profili güncellendi: {0} → {1}").format(old_profile, role_profile)}


@frappe.whitelist()
def deactivate_buyer_sub_user(user: str, reason: str = "") -> dict:
	"""Buyer sub-user pasifleştir + oturum kes."""
	caller_org = _require_buyer_admin()

	user_org = frappe.db.get_value("User", user, "tradehub_parent_organization")
	if user_org != caller_org:
		frappe.throw(_("Bu kullanıcı ekibinizde değil."), frappe.PermissionError)

	user_doc = frappe.get_doc("User", user)
	user_doc.enabled = 0
	user_doc.save(ignore_permissions=True)

	frappe.db.delete("Sessions", {"user": user})
	frappe.cache().delete_value(f"user:{user}")

	log_role_change(
		target_user=user,
		change_type="deactivate",
		tenant=caller_org,
		reason=reason or f"Buyer team — Deactivated by {frappe.session.user}",
	)

	frappe.db.commit()
	return {"message": _("Buyer kullanıcı pasifleştirildi ve oturumları sonlandırıldı.")}


@frappe.whitelist()
def reactivate_buyer_sub_user(user: str) -> dict:
	"""Pasifleştirilmiş buyer sub-user'ı yeniden aktive et."""
	caller_org = _require_buyer_admin()

	user_org = frappe.db.get_value("User", user, "tradehub_parent_organization")
	if user_org != caller_org:
		frappe.throw(_("Bu kullanıcı ekibinizde değil."), frappe.PermissionError)

	current_count = frappe.db.count("User", {"tradehub_parent_organization": caller_org, "enabled": 1})
	from tradehub_core.utils.tenant import get_current_seller_profile

	tenant_for_quota = get_current_seller_profile()
	if tenant_for_quota:
		check_quota_or_throw(
			tenant_for_quota,
			"quota.max_sub_users",
			current_count,
			action_description=_("Buyer kullanıcı yeniden aktive"),
		)

	user_doc = frappe.get_doc("User", user)
	user_doc.enabled = 1
	user_doc.save(ignore_permissions=True)

	log_role_change(
		target_user=user,
		change_type="activate",
		tenant=caller_org,
		reason=f"Buyer team — Reactivated by {frappe.session.user}",
	)

	frappe.db.commit()
	return {"message": _("Buyer kullanıcı yeniden aktive edildi.")}


@frappe.whitelist()
def revoke_buyer_invite(invite_name: str, reason: str = "") -> dict:
	"""Bekleyen buyer davetini iptal et."""
	caller_org = _require_buyer_admin()

	invite = frappe.get_doc("Buyer Sub User Invite", invite_name)
	if invite.organization != caller_org:
		frappe.throw(_("Bu davet ekibinize ait değil."), frappe.PermissionError)
	if invite.status != "Pending":
		frappe.throw(_("Sadece 'Pending' durumundaki davet iptal edilebilir."))

	invite.status = "Revoked"
	invite.revoke_reason = reason or f"Revoked by {frappe.session.user}"
	invite.save(ignore_permissions=True)

	frappe.db.commit()
	return {"message": _("Buyer davet iptal edildi.")}


@frappe.whitelist(allow_guest=True)
def accept_buyer_invite(token: str, full_name: str, password: str) -> dict:
	"""Davet kabul (public endpoint).

	Args:
	    token: Raw token (e-postadan)
	    full_name: Ad
	    password: Yeni şifre

	Side effects:
	  - User oluşturulur (enabled=1, role_profile_name, tradehub_parent_organization)
	  - Davet status=Accepted
	"""
	if not token or not password:
		frappe.throw(_("Geçersiz davet."))

	if len(password) < 8:
		frappe.throw(_("Şifre en az 8 karakter olmalı."))

	token_hash = _hash_token(token)
	invite_name = frappe.db.get_value(
		"Buyer Sub User Invite",
		{"token_hash": token_hash, "status": "Pending"},
		"name",
	)
	if not invite_name:
		frappe.throw(_("Davet geçersiz veya zaten kullanılmış."), frappe.PermissionError)

	invite = frappe.get_doc("Buyer Sub User Invite", invite_name)

	if invite.expires_at and now_datetime() > invite.expires_at:
		invite.status = "Expired"
		invite.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.throw(_("Davet süresi dolmuş."), frappe.PermissionError)

	if frappe.db.exists("User", invite.email):
		frappe.throw(_("Bu e-posta zaten kayıtlı."), frappe.PermissionError)

	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": invite.email,
			"first_name": (full_name or invite.full_name).split()[0],
			"last_name": " ".join((full_name or invite.full_name).split()[1:]) or "-",
			"full_name": full_name or invite.full_name,
			"enabled": 1,
			"send_welcome_email": 0,
			"user_type": "System User",
			"new_password": password,
			"role_profile_name": invite.role_profile,
			"tradehub_parent_organization": invite.organization,
		}
	)
	user.flags.ignore_permissions = True
	user.flags.from_insert = True
	user.insert(ignore_permissions=True)

	# v15_5_4 — Defansif Role Profile → User.roles sync
	_ensure_user_roles_from_profile(user, invite.role_profile)

	invite.status = "Accepted"
	invite.accepted_at = now_datetime()
	invite.created_user = user.name
	invite.save(ignore_permissions=True)

	frappe.db.commit()
	return {
		"message": _("Hoşgeldiniz! B2B alıcı hesabınız oluşturuldu."),
		"user": user.name,
		"organization": invite.organization,
	}


def _ensure_user_roles_from_profile(user_doc, role_profile_name: str) -> None:
	"""v15_5_4 — User'a Role Profile'daki rolleri explicit olarak ekle.

	Aynı pattern api/v1/seller_users.py içinde. Frappe Role Profile auto-sync
	fixture eksikliklerinde silently fail edebiliyor → defansif manuel sync.
	"""
	if not role_profile_name:
		return
	if not frappe.db.exists("Role Profile", role_profile_name):
		return
	try:
		rp = frappe.get_doc("Role Profile", role_profile_name)
		current_roles = {r.role for r in (user_doc.roles or [])}
		profile_roles = {r.role for r in (rp.roles or []) if r.role}
		missing = profile_roles - current_roles
		if missing:
			for role in missing:
				if frappe.db.exists("Role", role):
					user_doc.append("roles", {"role": role})
			user_doc.save(ignore_permissions=True)
	except Exception as exc:
		frappe.log_error(
			f"_ensure_user_roles_from_profile {user_doc.name}/{role_profile_name}: {exc}",
			"buyer_team.invite_accept",
		)


# ---------------------------------------------------------------------------
# Email helper
# ---------------------------------------------------------------------------


def _build_invite_url(raw_token: str) -> str:
	site_url = frappe.utils.get_url()
	return f"{site_url}/accept-buyer-invite?token={raw_token}"


def _send_invite_email(invite, invite_url: str) -> None:
	"""Davet e-postası gönder (basit template)."""
	subject = _("[TradeHub] '{0}' organizasyonuna davet").format(invite.organization)
	message = _(
		"""Merhaba {full_name},

{invited_by} sizi TradeHub üzerinde '{org}' organizasyonunun ekibine '{role_profile}'
rolünde davet etti.

Daveti kabul etmek için aşağıdaki linke tıklayın (7 gün geçerli):

  {invite_url}

İyi çalışmalar,
TradeHub Ekibi"""
	).format(
		full_name=invite.full_name,
		invited_by=invite.invited_by,
		org=invite.organization,
		role_profile=invite.role_profile,
		invite_url=invite_url,
	)

	frappe.sendmail(
		recipients=[invite.email],
		subject=subject,
		message=message,
		now=True,
	)

# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 1.5 — Satıcı sub-user yönetim API'ı.

Endpoints:
  - invite_sub_user(email, full_name, role_profile)
  - list_sub_users()
  - update_sub_user_role(user, role_profile)
  - deactivate_sub_user(user, reason)
  - reactivate_sub_user(user)
  - accept_invite(token, new_password)  → allow_guest=True
  - revoke_invite(invite_name, reason)

Davet akışı:
  Owner → invite_sub_user → SSUI kaydı + raw token + e-posta
  Davet linki → /accept-invite?token=<raw> → accept_invite endpoint
  accept_invite → User oluştur, role_profile ata, tenant set, davet Accepted

Detay: docs/yetki/01-karar-dosyasi.md §5
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
	has_feature,
)

# Token boyutu (urlsafe karakter sayısı)
_TOKEN_BYTES = 32

# Davet geçerlilik süresi (gün)
_INVITE_TTL_DAYS = 7

# Owner-only operasyonlar (Co-Owner bile yapamaz)
_OWNER_ONLY_ACTIONS = frozenset(
	{
		"transfer_owner",
		"change_bank_info",
		"change_tax_info",
		"delete_account",
	}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_current_tenant() -> str | None:
	"""Mevcut user'ın seller_profile (tenant) name'i."""
	from tradehub_core.utils.tenant import get_current_seller_profile

	return get_current_seller_profile()


def _require_owner_or_co_owner(action: str = "") -> str:
	"""Caller Owner veya Co-Owner mi? Değilse PermissionError.

	Returns:
	    tenant name (Admin Seller Profile.name)
	"""
	tenant = _get_current_tenant()
	if not tenant:
		frappe.throw(_("Sub-user yönetimi için bir mağazaya bağlı olmanız gerekir."), frappe.PermissionError)

	user = frappe.session.user
	roles = set(frappe.get_roles(user))

	# Owner: Seller Owner rolü + is_owner flag
	is_owner = "Seller Owner" in roles and frappe.db.get_value("User", user, "tradehub_is_owner")

	# Co-Owner: Seller Co-Owner role profile
	co_owner_profile = frappe.db.get_value("User", user, "role_profile_name")
	is_co_owner = co_owner_profile == "Seller Co-Owner"

	if not (is_owner or is_co_owner) and "System Manager" not in roles:
		frappe.throw(
			_("Bu işlem için Mağaza Sahibi (Owner) veya Co-Owner olmalısınız."),
			frappe.PermissionError,
		)

	# Owner-only check (banka değiştirme, owner devri vb.)
	if action in _OWNER_ONLY_ACTIONS and not is_owner and "System Manager" not in roles:
		frappe.throw(
			_("Bu işlem yalnızca Mağaza Sahibi (Owner) tarafından yapılabilir."),
			frappe.PermissionError,
		)

	return tenant


def _hash_token(raw_token: str) -> str:
	"""Raw token → SHA-256 hex."""
	return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _generate_invite_token() -> tuple[str, str]:
	"""(raw_token, token_hash) üret."""
	raw = secrets.token_urlsafe(_TOKEN_BYTES)
	return raw, _hash_token(raw)


def _validate_role_profile_for_plan(tenant: str, role_profile: str) -> None:
	"""Plan kelepçesi — role_profile, plan'ın SubUserFeatures'ında mı?

	Profile code feature key'e çevrilir: 'Seller Manager' → 'seller_manager' →
	'feature.role.profile.seller_manager'.
	"""
	# A1 fix: Role Profile existence check — typo koruması
	if not frappe.db.exists("Role Profile", role_profile):
		frappe.throw(
			_("'{0}' geçerli bir rol profili değil.").format(role_profile),
			frappe.ValidationError,
		)

	# Profile name → feature key
	code = role_profile.lower().replace(" ", "_").replace("-", "_")
	feature_key = f"feature.role.profile.{code}"

	# Custom rol oluşturma capability'si Enterprise only
	if not has_feature(tenant, feature_key) and not has_feature(tenant, "feature.role.custom_creation"):
		check_feature_or_throw(
			tenant,
			feature_key,
			action_description=_("'{0}' rol profili atama").format(role_profile),
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@frappe.whitelist()
def invite_sub_user(email: str, full_name: str, role_profile: str) -> dict:
	"""Yeni sub-user davet et.

	Args:
	    email: Davet edilecek e-posta
	    full_name: Ad soyad
	    role_profile: Role Profile.name (örn. 'Seller Manager')

	Returns:
	    {"invite_name": str, "invite_url": str, "expires_at": str}

	Raises:
	    PermissionError: Caller Owner/Co-Owner değil
	    EntitlementError: Plan kelepçesi (feature.role.profile.X yok) veya
	                       sub-user kotası dolu
	"""
	tenant = _require_owner_or_co_owner()
	email = (email or "").strip().lower()

	if not email or "@" not in email:
		frappe.throw(_("Geçerli bir e-posta girin."))

	# Aynı tenant için aynı email'e açık davet veya kullanıcı var mı?
	if frappe.db.exists("User", email):
		existing_tenant = frappe.db.get_value("User", email, "tradehub_tenant")
		if existing_tenant == tenant:
			frappe.throw(_("Bu e-posta zaten ekibinizde mevcut."))
		else:
			frappe.throw(_("Bu e-posta başka bir mağazaya bağlı."))

	existing_invite = frappe.db.exists(
		"Seller Sub User Invite",
		{"email": email, "tenant": tenant, "status": "Pending"},
	)
	if existing_invite:
		frappe.throw(_("Bu e-postaya zaten aktif bir davet gönderilmiş: {0}").format(existing_invite))

	# Kota kontrolü — mevcut aktif sub-user sayısı
	# Owner (mağaza sahibi) sub-user kotasına DAHİL DEĞİL — limit yalnız ek kullanıcıları sayar.
	current_count = frappe.db.count("User", {"tradehub_tenant": tenant, "enabled": 1, "tradehub_is_owner": 0})
	check_quota_or_throw(
		tenant,
		"quota.max_sub_users",
		current_count,
		action_description=_("Yeni çalışan daveti"),
	)

	# Plan kelepçesi (role_profile bu planda atanabilir mi?)
	_validate_role_profile_for_plan(tenant, role_profile)

	# Token üret
	raw_token, token_hash = _generate_invite_token()
	expires_at = add_days(now_datetime(), _INVITE_TTL_DAYS)

	# Invite kaydı oluştur
	invite = frappe.get_doc(
		{
			"doctype": "Seller Sub User Invite",
			"email": email,
			"full_name": full_name,
			"tenant": tenant,
			"role_profile": role_profile,
			"status": "Pending",
			"invited_by": frappe.session.user,
			"expires_at": expires_at,
			"token_hash": token_hash,
		}
	)
	invite.insert(ignore_permissions=True)

	# E-posta gönder (Faz 1.5'te basit template; Faz 3'te Mailing entegrasyonu)
	invite_url = _build_invite_url(raw_token)
	try:
		_send_invite_email(invite, invite_url)
	except Exception as exc:
		frappe.log_error(f"Davet e-postası gönderilemedi: {exc}", "invite_sub_user")

	frappe.db.commit()

	return {
		"invite_name": invite.name,
		"invite_url": invite_url if "System Manager" in frappe.get_roles() else None,
		"expires_at": str(expires_at),
		"message": _("Davet e-postası gönderildi: {0}").format(email),
	}


@frappe.whitelist()
def list_sub_users() -> list[dict]:
	"""Caller'ın tenant'ındaki tüm sub-user'lar + bekleyen davetler."""
	tenant = _require_owner_or_co_owner()

	users = frappe.get_all(
		"User",
		filters={"tradehub_tenant": tenant},
		fields=[
			"name",
			"email",
			"full_name",
			"enabled",
			"role_profile_name",
			"tradehub_is_owner",
			"last_login",
		],
		order_by="creation desc",
	)

	invites = frappe.get_all(
		"Seller Sub User Invite",
		filters={"tenant": tenant, "status": "Pending"},
		fields=["name", "email", "full_name", "role_profile", "expires_at", "invited_by"],
		order_by="creation desc",
	)

	return {"users": users, "pending_invites": invites}


@frappe.whitelist()
def update_sub_user_role(user: str, role_profile: str) -> dict:
	"""Bir sub-user'ın role_profile'ını değiştir.

	Plan kelepçesi + Owner-only kontrolleri:
	  - role_profile yeni planın SubUserFeatures'ında olmalı
	  - Owner profili (Seller Full Access) değişikliği sadece Owner yapabilir
	"""
	tenant = _require_owner_or_co_owner()

	# Target user gerçekten bu tenant'ta mı?
	user_tenant = frappe.db.get_value("User", user, "tradehub_tenant")
	if user_tenant != tenant:
		frappe.throw(_("Bu kullanıcı ekibinizde değil."), frappe.PermissionError)

	# Target Owner mu? Owner değişikliği yalnızca Owner tarafından
	target_is_owner = frappe.db.get_value("User", user, "tradehub_is_owner")
	if target_is_owner:
		_require_owner_or_co_owner(action="transfer_owner")

	# Plan kelepçesi
	_validate_role_profile_for_plan(tenant, role_profile)

	# Mevcut profil snapshot
	old_profile = frappe.db.get_value("User", user, "role_profile_name")

	# Set
	user_doc = frappe.get_doc("User", user)
	user_doc.role_profile_name = role_profile
	user_doc.save(ignore_permissions=True)

	# Audit
	log_role_change(
		target_user=user,
		change_type="profile_change",
		tenant=tenant,
		before_role_profiles=[old_profile] if old_profile else [],
		after_role_profiles=[role_profile],
		reason=f"Updated by {frappe.session.user}",
	)

	frappe.db.commit()
	return {"message": _("Rol profili güncellendi: {0} → {1}").format(old_profile, role_profile)}


@frappe.whitelist()
def deactivate_sub_user(user: str, reason: str = "") -> dict:
	"""Sub-user'ı pasifleştir + tüm açık oturumları sonlandır.

	Owner pasifleştirilemez (Owner devri için ayrı endpoint Faz 3).
	"""
	tenant = _require_owner_or_co_owner()

	user_tenant = frappe.db.get_value("User", user, "tradehub_tenant")
	if user_tenant != tenant:
		frappe.throw(_("Bu kullanıcı ekibinizde değil."), frappe.PermissionError)

	if frappe.db.get_value("User", user, "tradehub_is_owner"):
		frappe.throw(
			_("Owner pasifleştirilemez — önce Owner devri yapın (Faz 3)."),
			frappe.PermissionError,
		)

	# Pasifleştir
	user_doc = frappe.get_doc("User", user)
	user_doc.enabled = 0
	user_doc.save(ignore_permissions=True)

	# K8 fix: tam session + cache + API token temizliği (race window kapat)
	from tradehub_core.utils.user_lifecycle import purge_user_sessions_and_caches

	purge_user_sessions_and_caches(user)

	# Ek özel cache (legacy)
	frappe.cache().delete_value(f"user:{user}")
	frappe.cache().delete_value(f"tradehub:seller_for_user:{user}")

	# Audit
	log_role_change(
		target_user=user,
		change_type="deactivate",
		tenant=tenant,
		reason=reason or f"Deactivated by {frappe.session.user}",
	)

	frappe.db.commit()
	return {"message": _("Kullanıcı pasifleştirildi ve oturumları sonlandırıldı.")}


@frappe.whitelist()
def reactivate_sub_user(user: str) -> dict:
	"""Pasifleştirilmiş sub-user'ı tekrar aktif et (kota kontrolü ile)."""
	tenant = _require_owner_or_co_owner()

	user_tenant = frappe.db.get_value("User", user, "tradehub_tenant")
	if user_tenant != tenant:
		frappe.throw(_("Bu kullanıcı ekibinizde değil."), frappe.PermissionError)

	# Kota kontrolü
	# Owner (mağaza sahibi) sub-user kotasına DAHİL DEĞİL — limit yalnız ek kullanıcıları sayar.
	current_count = frappe.db.count("User", {"tradehub_tenant": tenant, "enabled": 1, "tradehub_is_owner": 0})
	check_quota_or_throw(
		tenant,
		"quota.max_sub_users",
		current_count,
		action_description=_("Çalışan yeniden aktive etme"),
	)

	user_doc = frappe.get_doc("User", user)
	user_doc.enabled = 1
	user_doc.save(ignore_permissions=True)

	log_role_change(
		target_user=user,
		change_type="activate",
		tenant=tenant,
		reason=f"Reactivated by {frappe.session.user}",
	)

	frappe.db.commit()
	return {"message": _("Kullanıcı yeniden aktive edildi.")}


@frappe.whitelist()
def revoke_invite(invite_name: str, reason: str = "") -> dict:
	"""Bekleyen daveti iptal et."""
	tenant = _require_owner_or_co_owner()

	invite = frappe.get_doc("Seller Sub User Invite", invite_name)
	if invite.tenant != tenant:
		frappe.throw(_("Bu davet ekibinize ait değil."), frappe.PermissionError)
	if invite.status != "Pending":
		frappe.throw(_("Sadece 'Pending' durumundaki davet iptal edilebilir."))

	invite.status = "Revoked"
	invite.revoke_reason = reason or f"Revoked by {frappe.session.user}"
	invite.save(ignore_permissions=True)

	frappe.db.commit()
	return {"message": _("Davet iptal edildi.")}


@frappe.whitelist(allow_guest=True)
def verify_invite(token: str) -> dict:
	"""Davet linki doğrulama — accept-invite sayfası açıldığında çağrılır.

	Süre/status kontrolü yapar, geçerliyse meta bilgileri döner.
	Token kendisi response'da ASLA döndürülmez (replay önleme).
	"""
	if not token:
		frappe.throw(_("Geçersiz davet."), exc=frappe.ValidationError)

	token_hash = _hash_token(token)
	invite_name = frappe.db.get_value(
		"Seller Sub User Invite",
		{"token_hash": token_hash, "status": "Pending"},
		"name",
	)
	if not invite_name:
		frappe.throw(_("Davet geçersiz veya zaten kullanılmış."), exc=frappe.ValidationError)

	invite = frappe.get_doc("Seller Sub User Invite", invite_name)
	if invite.expires_at and now_datetime() > invite.expires_at:
		invite.status = "Expired"
		invite.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.throw(_("Davet süresi dolmuş."), exc=frappe.ValidationError)

	return {
		"email": invite.email,
		"full_name": invite.full_name,
		"tenant": invite.tenant,
		"role_profile": invite.role_profile,
		"expires_at": str(invite.expires_at) if invite.expires_at else None,
	}


@frappe.whitelist(allow_guest=True)
def accept_invite(token: str, full_name: str, password: str) -> dict:
	"""Davet linkinden gelen kullanıcı bu endpoint'i çağırır.

	Args:
	    token: E-postadaki raw token
	    full_name: Davet edilen kişinin adı (form doldururken doğrulama)
	    password: Yeni şifre

	Side effects:
	  - Frappe User oluşturulur (enabled=1, role_profile_name set)
	  - tradehub_tenant set edilir
	  - Davet status=Accepted
	"""
	if not token or not password:
		frappe.throw(_("Geçersiz davet."))

	if len(password) < 8:
		frappe.throw(_("Şifre en az 8 karakter olmalı."))

	token_hash = _hash_token(token)

	# A3 fix: Pessimistic lock — concurrent accept race condition önlemi.
	# SELECT ... FOR UPDATE ile satır kilitlenir, ikinci request ilkini bekler.
	locked = frappe.db.sql(
		"SELECT name FROM `tabSeller Sub User Invite` "
		"WHERE token_hash = %s AND status = 'Pending' "
		"LIMIT 1 FOR UPDATE",
		(token_hash,),
		as_dict=True,
	)
	if not locked:
		frappe.throw(_("Davet geçersiz veya zaten kullanılmış."), frappe.PermissionError)

	invite_name = locked[0].name
	invite = frappe.get_doc("Seller Sub User Invite", invite_name)

	# Süre kontrolü
	if invite.expires_at and now_datetime() > invite.expires_at:
		invite.status = "Expired"
		invite.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.throw(_("Davet süresi dolmuş."), frappe.PermissionError)

	# Aynı email zaten User olarak var mı?
	if frappe.db.exists("User", invite.email):
		frappe.throw(_("Bu e-posta zaten kayıtlı."), frappe.PermissionError)

	# User oluştur
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
			"tradehub_tenant": invite.tenant,
			"tradehub_is_owner": 0,  # Co-Owner / Owner promote ayrı endpoint
		}
	)
	user.flags.ignore_permissions = True
	user.flags.from_insert = True  # audit/user_hooks için
	user.insert(ignore_permissions=True)

	# v15_5_4 fix: Frappe'nin Role Profile → User.roles auto-sync mekanizması
	# fixture'lar tam yüklenmediğinde sessizce başarısız olabiliyordu (sub-user
	# tablosunda role profile boş gözüküyordu). Defansif sync — Role Profile'da
	# tanımlı her rolü explicit olarak User.roles'a ekle.
	_ensure_user_roles_from_profile(user, invite.role_profile)

	# Davet'i kapat
	invite.status = "Accepted"
	invite.accepted_at = now_datetime()
	invite.created_user = user.name
	invite.save(ignore_permissions=True)

	frappe.db.commit()

	return {
		"message": _("Hoşgeldiniz! Hesabınız oluşturuldu, giriş yapabilirsiniz."),
		"user": user.name,
		"tenant": invite.tenant,
	}


def _ensure_user_roles_from_profile(user_doc, role_profile_name: str) -> None:
	"""v15_5_4 — User'a Role Profile'daki rolleri explicit olarak ekle.

	Frappe normalde `role_profile_name` set edildiğinde otomatik sync yapar,
	ama Role Profile fixture'ları tam yüklenmemişse veya child table boşsa
	bu sync no-op olur ve User rolsüz kalır → ACL inconsistency.
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
			"seller_users.invite_accept",
		)


# ---------------------------------------------------------------------------
# Email helper
# ---------------------------------------------------------------------------


def _build_invite_url(raw_token: str) -> str:
	"""Davet kabul URL'i — environment-aware.

	Öncelik sırası:
	  1. site_config.json → `tradehub_admin_panel_url` (örn: https://beta.istoc.com)
	  2. site_config.json → `admin_panel_url`
	  3. Frappe `get_url()` fallback (backend domain)

	Production deploy: site_config.json'da `tradehub_admin_panel_url`'i set et.
	Local dev: fallback `http://localhost:8082` veya manuel config.
	"""
	panel_url = (
		frappe.conf.get("tradehub_admin_panel_url")
		or frappe.conf.get("admin_panel_url")
		or _default_panel_url()
	)
	panel_url = panel_url.rstrip("/")

	# A5 fix: URL domain whitelist — phishing koruması.
	# Config'ten gelen URL beklenmeyen bir domain'e işaret ediyorsa reject et.
	from urllib.parse import urlparse

	parsed = urlparse(panel_url)
	_ALLOWED_DOMAINS = frozenset(
		{
			"localhost",
			"istoc.com",
			"beta.istoc.com",
			"rc.istoc.com",
			"admin.istoc.com",
			"admin-preview.istoc.com",
		}
	)
	hostname = parsed.hostname or ""
	if hostname and hostname not in _ALLOWED_DOMAINS and not hostname.endswith(".istoc.com"):
		frappe.log_error(
			f"Invite URL domain not whitelisted: {panel_url}",
			"seller_users.invite_url_security",
		)
		# Fallback güvenli URL'e
		panel_url = _default_panel_url()

	return f"{panel_url}/accept-invite?token={raw_token}"


def _default_panel_url() -> str:
	"""Frappe backend URL'inden admin panel URL'i tahmin et (dev fallback).

	dev.localhost → http://localhost:8082 (Vite dev server portu)
	Production'da bu fallback'e güvenme — `tradehub_admin_panel_url` config'i set et.
	"""
	site_url = frappe.utils.get_url() or ""
	if "dev.localhost" in site_url or "localhost" in site_url:
		return "http://localhost:8082"
	return site_url


def _send_invite_email(invite, invite_url: str) -> None:
	"""Davet e-postası gönder (HTML template)."""
	store_name = frappe.db.get_value("Admin Seller Profile", invite.tenant, "seller_name") or invite.tenant
	subject = _("[TradeHub] '{0}' mağazasına davet").format(store_name)
	message = _(
		"""<p>Merhaba {full_name},</p>

<p><strong>{invited_by}</strong> sizi TradeHub üzerinde <strong>{store_name}</strong> mağazasının
ekibine <strong>{role_profile}</strong> rolünde davet etti.</p>

<p>Daveti kabul etmek için aşağıdaki butona tıklayın (7 gün geçerli):</p>

<p style="margin: 24px 0;">
  <a href="{invite_url}"
     style="background-color: #7c3aed; color: #ffffff; padding: 12px 32px;
            text-decoration: none; border-radius: 8px; font-weight: 600;
            display: inline-block;">
    Daveti Kabul Et
  </a>
</p>

<p style="font-size: 12px; color: #888;">
  Buton çalışmıyorsa bu linki tarayıcınıza yapıştırın:<br>
  <a href="{invite_url}">{invite_url}</a>
</p>

<p>İyi çalışmalar,<br>TradeHub Ekibi</p>"""
	).format(
		full_name=invite.full_name,
		invited_by=invite.invited_by,
		store_name=store_name,
		role_profile=invite.role_profile,
		invite_url=invite_url,
	)

	frappe.sendmail(
		recipients=[invite.email],
		subject=subject,
		message=message,
		now=True,
	)

"""Faz E.3 — Self-service Subscription Plan upgrade/downgrade.

Owner (`tradehub_is_owner=1`) veya platform admin tenant'ın aktif Store
Subscription'ının `plan` field'ını değiştirebilir. Plan değişimi sonrası:
  1. Subscription Plan capability/quota'ları yeni planın değerlerine geçer
  2. Eski plan'da desteklenen sub-user role profile'lar yeni plan'da
     desteklenmiyorsa `apply_role_downgrade_for_plan_change` ile sub-user
     downgrade chain'i uygulanır
  3. Entitlement + permission cache flush edilir
  4. ADL'ye HIGH severity audit log yazılır (rule: auth.subscription_change)

Şu an placeholder — gerçek billing/payment akışı entegrasyonu yapılmadı; sadece
plan değişimi + role sync + audit. Trial üretiyorsa caller `start_trial=True`
ile çağırır (`status=trial`, `trial_end` plan.trial_days üzerinden).
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, add_months, add_years, cint, getdate, now_datetime

from tradehub_core.audit import log_decision

# Panele erişim veren abonelik durumları (abonelik kapısı / paywall kuralı).
# Bu set dışındaki her durum (expired/canceled/past_due/suspended/yok) → panel kilitli.
_ACCESS_GRANTING_STATUS = frozenset({"active", "trial"})


def _resolve_tenant_for_caller() -> str:
	"""Caller'ın yönetebileceği tenant'ı çöz.

	Platform admin (System Manager / Marketplace Admin) → tenant parametresi
	zorunlu (aksi durumda hangi store'u yöneteceğini bilmez).
	Seller Owner → User.tradehub_tenant'tan otomatik resolve.
	Diğer → PermissionError.
	"""
	user = frappe.session.user
	if user in ("Guest", ""):
		frappe.throw(_("Yetki gerekli."), frappe.PermissionError)

	roles = set(frappe.get_roles(user))
	if {"System Manager", "Marketplace Admin"} & roles:
		return ""  # Caller tenant parametresini geçirmeli

	user_data = frappe.db.get_value("User", user, ["tradehub_tenant", "tradehub_is_owner"], as_dict=True)
	if not user_data or not user_data.tradehub_is_owner:
		frappe.throw(
			_("Sadece mağaza sahibi veya platform admin plan değiştirebilir."),
			frappe.PermissionError,
		)
	tenant = user_data.tradehub_tenant
	if not tenant:
		frappe.throw(_("Mağaza bulunamadı."), frappe.PermissionError)
	return tenant


@frappe.whitelist(methods=["POST"])
def upgrade_subscription_plan(
	new_plan: str,
	tenant: str | None = None,
	start_trial: bool | int | str = False,
	reason: str = "",
	billing_cycle: str | None = None,
) -> dict[str, Any]:
	"""Self-service plan değişimi (upgrade/downgrade/trial başlatma).

	Args:
	    new_plan: Subscription Plan.name (örn. "PRO", "ENTERPRISE")
	    tenant: Platform admin için zorunlu (Admin Seller Profile.name). Owner
	        çağırıyorsa otomatik resolve.
	    start_trial: True ise `status=trial`, `trial_end = now + plan.trial_days`.
	        False (default) → `status=active`, immediate billing period start.
	    reason: Audit context'e yazılır (max 200 char).
	    billing_cycle: 'monthly' | 'yearly'. Geriye-uyumlu: None (default) →
	        mevcut subscription'ın billing_cycle'ı, o da yoksa 'monthly'.
	        Yalnız `status=active` geçişinde dönem hesabına girer (BE-3 / AC-7).

	Returns:
	    {old_plan, new_plan, role_sync, audit_id}
	"""
	caller_tenant = _resolve_tenant_for_caller()
	tenant = (tenant or caller_tenant or "").strip()
	if not tenant:
		frappe.throw(_("tenant parametresi gerekli."), frappe.ValidationError)
	if caller_tenant and caller_tenant != tenant:
		# Owner sadece kendi tenant'ı için işlem yapabilir
		frappe.throw(_("Başka mağaza için plan değiştiremezsiniz."), frappe.PermissionError)

	if not frappe.db.exists("Admin Seller Profile", tenant):
		frappe.throw(_("Mağaza bulunamadı: {0}").format(tenant))
	if not frappe.db.exists("Subscription Plan", new_plan):
		frappe.throw(_("Plan bulunamadı: {0}").format(new_plan))

	plan_doc = frappe.get_doc("Subscription Plan", new_plan)
	if not plan_doc.is_active:
		frappe.throw(
			_("'{0}' planı aktif değil; seçilemez.").format(new_plan),
			frappe.ValidationError,
		)

	if billing_cycle is not None:
		billing_cycle = (billing_cycle or "").strip().lower()
		if billing_cycle not in ("monthly", "yearly"):
			frappe.throw(
				_("Geçersiz billing_cycle: {0}. İzin verilen: monthly, yearly.").format(billing_cycle),
				frappe.ValidationError,
			)

	start_trial_bool = str(start_trial).strip().lower() in ("1", "true", "yes")

	# C8 fix — ödemesiz plan aktivasyonu engeli.
	# Platform admin (caller_tenant == "" → System Manager/Marketplace Admin) ücretli
	# aktivasyon yapabilir (ödeme onayı süreci dışından). Mağaza sahibi self-service
	# olarak YALNIZCA trial başlatabilir; ücretli `active` plana geçiş onaylı ödeme
	# gerektirir (confirm_subscription_payment akışı, admin-only). Bu kontrol olmadan
	# her owner ücret ödemeden ENTERPRISE'a geçebiliyordu.
	is_platform_admin = caller_tenant == ""
	if not is_platform_admin and not start_trial_bool:
		frappe.throw(
			_("Ücretli plana geçiş için ödeme onayı gerekir; lütfen ödeme akışını kullanın."),
			frappe.PermissionError,
		)

	# Mağazanın mevcut Store Subscription'ı (store unique → en fazla 1 satır).
	# Status'tan bağımsız ara: `expired`/`past_due` bir mağaza tekrar abone/öde
	# olduğunda AYNI satır reaktive edilmeli — yeni insert `store` unique
	# kısıtını ihlal eder (bkz. store_subscription state machine: expired→active).
	existing = frappe.db.get_value(
		"Store Subscription",
		{"store": tenant},
		["name", "plan", "status", "trial_used", "billing_cycle"],
		as_dict=True,
	)

	# 1 mağaza = 1 trial: deneme hakkı kullanılmışsa yeniden trial verme → active.
	if start_trial_bool and existing and existing.get("trial_used"):
		start_trial_bool = False

	old_plan = existing.plan if existing else None
	target_status = "trial" if start_trial_bool else "active"

	# R2 — 'canceled' bir mağaza self-servis reaktive edilemez, önce admin
	# reaktivasyonu gerekir: hesap silme akışı (account_deleted) profili
	# Suspended + owner User'ı disabled bırakır; admin un-suspend + enable
	# yapmadan canceled→active geçişi 417 ile durdurulur (AC-14 negatif vakası).
	if existing and existing.status == "canceled" and target_status == "active":
		profile = frappe.db.get_value("Admin Seller Profile", tenant, ["status", "user"], as_dict=True)
		owner_enabled = 1
		if profile and profile.user:
			owner_enabled = cint(frappe.db.get_value("User", profile.user, "enabled"))
		if (profile and profile.status == "Suspended") or not owner_enabled:
			frappe.throw(
				_("Önce mağaza reaktivasyonu gerekli — admin işlemi."),
				frappe.ValidationError,
			)

	def _apply_trial_fields(doc) -> None:
		"""Trial başlatılıyorsa trial_start/end/plan/used alanlarını set et.

		Dönem alanları (current_period_*, next_invoice_date) trial'da YAZILMAZ —
		trial ömrünü trial_end yönetir (BE-3).
		"""
		trial_days = int(plan_doc.get("trial_days") or 0)
		now = now_datetime()
		doc.trial_start = now
		doc.trial_plan = new_plan
		doc.trial_used = 1
		doc.trial_end = add_days(now, trial_days) if trial_days > 0 else None

	def _apply_active_period_fields(doc, cycle: str) -> None:
		"""'active' geçişinde dönem alanlarını yaz (BE-3 / AC-7).

		current_period_end = start + 1 ay/1 yıl, next_invoice_date = dönem sonu.
		cancel_at_period_end burada sıfırlanır: yeniden abonelikte eski iptal
		planı taşınmaz. renewal_reminder_* bayraklarını BE-1'in validate'i
		current_period_start değişiminde zaten sıfırlıyor — burada tekrarlanmaz.
		"""
		start = now_datetime()
		end = add_months(start, 1) if cycle == "monthly" else add_years(start, 1)
		doc.current_period_start = start
		doc.current_period_end = end
		doc.next_invoice_date = getdate(end)
		doc.billing_cycle = cycle
		doc.cancel_at_period_end = 0

	# Geriye-uyumlu cycle çözümü: parametre > mevcut kayıt > JSON default.
	effective_cycle = billing_cycle or (existing.billing_cycle if existing else None) or "monthly"

	if existing:
		sub_doc = frappe.get_doc("Store Subscription", existing.name)
		sub_doc.plan = new_plan
		sub_doc.status = target_status
	else:
		sub_doc = frappe.new_doc("Store Subscription")
		sub_doc.store = tenant
		sub_doc.plan = new_plan
		sub_doc.status = target_status
		sub_doc.started_at = now_datetime()

	if start_trial_bool:
		_apply_trial_fields(sub_doc)
	else:
		_apply_active_period_fields(sub_doc, effective_cycle)

	sub_doc.flags.ignore_permissions = True
	if existing:
		sub_doc.save(ignore_permissions=True)
	else:
		sub_doc.insert(ignore_permissions=True)

	# Plan değiştiyse sub-user role profile downgrade chain'ini çalıştır
	role_sync: dict[str, Any] = {"downgraded": [], "deactivated": [], "unchanged": []}
	if old_plan and old_plan != new_plan:
		try:
			from tradehub_core.services.subscription_downgrade import (
				apply_role_downgrade_for_plan_change,
			)

			role_sync = apply_role_downgrade_for_plan_change(tenant, new_plan)
		except Exception as exc:
			frappe.log_error(
				f"plan upgrade role sync failed: tenant={tenant} plan={new_plan}: {exc}",
				"subscription.upgrade",
			)

	# Cache flush — entitlement layer
	try:
		frappe.cache().delete_keys("tradehub:entitlement:")
		frappe.cache().delete_keys("tradehub:pricing:public")
	except Exception:
		frappe.log_error("cache flush failed in upgrade", "subscription.upgrade")

	frappe.db.commit()

	# Audit — HIGH severity (subscription change is owner-only capability)
	log_decision(
		action="subscription.upgrade",
		decision="ALLOW",
		rule_id="auth.subscription_change",
		layer="L0",
		object_doctype="Store Subscription",
		object_name=sub_doc.name,
		tenant=tenant,
		plan_code=new_plan,
		severity="HIGH",
		context={
			"old_plan": old_plan,
			"new_plan": new_plan,
			"status": target_status,
			"billing_cycle": None if start_trial_bool else effective_cycle,
			"started_trial": start_trial_bool,
			"reason": (reason or "")[:200],
			"role_sync_summary": {
				"downgraded": len(role_sync.get("downgraded", [])),
				"deactivated": len(role_sync.get("deactivated", [])),
				"unchanged": len(role_sync.get("unchanged", [])),
			},
		},
	)

	return {
		"old_plan": old_plan,
		"new_plan": new_plan,
		"status": target_status,
		"subscription": sub_doc.name,
		"role_sync": role_sync,
	}


# Locked durum → frontend bu reason'a göre paywall mesajı gösterir.
_LOCK_REASON_BY_STATUS = {
	"expired": "trial_expired",
	"canceled": "canceled",
	"past_due": "past_due",
	"suspended": "suspended",
}


def _ok_access_payload(sub: Any) -> dict[str, Any]:
	"""OK-şekilli erişim yanıtının ortak gövdesi.

	trial/active (mevcut davranış, bit değiştirmeden) ile past_due dunning
	hoşgörü dalı (BE-4 / AC-1) aynı alan setini bu helper'dan üretir.
	"""
	return {
		"access": "ok",
		"status": sub.status,
		"plan": sub.plan,
		"is_trial": sub.status == "trial",
		"trial_start": sub.trial_start,
		"trial_end": sub.trial_end,
		"started_at": sub.started_at,
		"current_period_end": sub.current_period_end,
		# BE-3 additive alanlar — panel iptal-planlı banner + dönem bilgisi.
		"cancel_at_period_end": cint(sub.cancel_at_period_end),
		"billing_cycle": sub.billing_cycle,
	}


@frappe.whitelist()
def get_seller_access_state() -> dict[str, Any]:
	"""Abonelik kapısı kararı — satıcı panele girebilir mi?

	Frontend her açılışta/rotada çağırır. `access`:
	  - "ok"      → panel açık (status trial veya active). is_trial/trial_end döner.
	                past_due da OK döner (dunning hoşgörü penceresi, BE-4/AC-1) —
	                additive in_dunning=1 + dunning_grace_end alanlarıyla.
	  - "locked"  → panele girilemez; paket-seçme/abonelik sayfasına yönlendir.
	  - "no_store"→ kullanıcı satıcı değil (mağaza yok); kapı kapsamı dışı.
	  - "guest"   → giriş yok.

	Güvenlik notu: Bu sadece yönlendirme/UX kararıdır. Asıl enforcement, hassas
	satıcı endpoint'lerinde ayrıca yapılır (Faz 4).
	"""
	user = frappe.session.user
	if user in ("Guest", ""):
		return {"access": "guest", "reason": "not_logged_in"}

	tenant = frappe.db.get_value("User", user, "tradehub_tenant")
	if not tenant:
		# Mağazası olmayan kullanıcı (alıcı vb.) — kapı bu kullanıcıyı kapsamaz.
		return {"access": "no_store", "reason": "no_seller_profile"}

	sub = frappe.db.get_value(
		"Store Subscription",
		{"store": tenant},
		[
			"status",
			"plan",
			"trial_start",
			"trial_end",
			"trial_plan",
			"trial_used",
			"started_at",
			"current_period_end",
			"cancel_at_period_end",
			"billing_cycle",
			"canceled_at",
			"suspended_at",
			"cancellation_reason",
		],
		as_dict=True,
	)

	if sub and sub.status in _ACCESS_GRANTING_STATUS:
		return _ok_access_payload(sub)

	if sub and sub.status == "past_due":
		# BE-4 / AC-1 — dunning hoşgörü penceresi: past_due artık kilitlemez,
		# OK-şekilli yanıt + additive in_dunning/dunning_grace_end döner
		# (_ACCESS_GRANTING_STATUS setine kasıtlı DOKUNULMADI — ayrı dal).
		# Tek otorite: süre sabiti BE-3'ün lifecycle modülünde (yedek tanım YOK).
		from tradehub_core.services.subscription_lifecycle import _DUNNING_SUSPEND_DAYS

		ok = _ok_access_payload(sub)
		ok["in_dunning"] = 1
		ok["dunning_grace_end"] = (
			add_days(sub.current_period_end, _DUNNING_SUSPEND_DAYS) if sub.current_period_end else None
		)
		return ok

	# Kilitli: hiç abonelik yok ya da erişim vermeyen durum (expired/canceled/...).
	lock_reason = _LOCK_REASON_BY_STATUS.get(sub.status, sub.status) if sub else "no_subscription"
	locked: dict[str, Any] = {
		"access": "locked",
		"status": sub.status if sub else None,
		"reason": lock_reason,
		"redirect": "/abonelik",
		# Deneme hakkı hiç kullanılmadıysa paywall "14 gün ücretsiz dene" sunabilir.
		"can_start_trial": not (sub and sub.trial_used),
	}
	if lock_reason == "canceled":
		# BE-3 additive alan — paywall "X tarihinde iptal edildi" gösterebilir.
		locked["canceled_at"] = sub.canceled_at
	if lock_reason == "suspended":
		# BE-4 / AC-5 additive — paywall 'vitrin geçici pasif, ödemenizle geri
		# açılır' + fesih tarihini gösterebilir. Süre sabiti lifecycle'dan (tek otorite).
		from tradehub_core.services.subscription_lifecycle import _DUNNING_EXPIRE_DAYS

		locked["suspended_at"] = sub.suspended_at
		locked["dunning_expire_at"] = (
			add_days(sub.current_period_end, _DUNNING_EXPIRE_DAYS) if sub.current_period_end else None
		)
	if lock_reason == "trial_expired":
		# BE-4 / AC-8 additive — reason geriye uyumluluk için 'trial_expired'
		# KALIR; dunning feshi ile trial bitişi ayrımı yeni expired_cause alanında.
		locked["expired_cause"] = "dunning" if sub.cancellation_reason == "dunning_expired" else "trial"
	return locked


@frappe.whitelist()
def get_seller_subscription(user: str) -> dict[str, Any]:
	"""Bir satıcının abonelik planını döndür — admin panel Satıcı Profili kartı için.

	Yetki: System Manager / Marketplace Admin herhangi satıcıyı görebilir + değiştirebilir
	(can_edit=True). Diğer kullanıcılar yalnızca kendi profilini (read-only) görebilir.
	Satıcı değilse (tradehub_tenant yok) {"is_seller": False} döner → kart gizlenir.
	"""
	from tradehub_core.entitlement.core import get_active_subscription

	user = (user or "").strip()
	if not user:
		frappe.throw(_("user gerekli"))

	caller = frappe.session.user
	roles = set(frappe.get_roles(caller))
	is_admin = bool({"System Manager", "Marketplace Admin", "Administrator"} & roles)

	if not is_admin and user != caller:
		frappe.throw(_("Bu profili görüntüleme yetkiniz yok."), frappe.PermissionError)

	tenant = frappe.db.get_value("User", user, "tradehub_tenant")
	if not tenant:
		return {"is_seller": False}

	sub = get_active_subscription(tenant)
	plan_code = sub.get("plan") if sub else None
	plan_name = frappe.db.get_value("Subscription Plan", plan_code, "plan_name") if plan_code else None

	return {
		"is_seller": True,
		"store": tenant,
		"plan_code": plan_code,
		"plan_name": plan_name,
		"status": sub.get("status") if sub else None,
		"trial_end": sub.get("trial_end") if sub else None,
		"can_edit": is_admin,
	}

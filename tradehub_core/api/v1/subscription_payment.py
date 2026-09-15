"""Havale/EFT tabanlı abonelik ödemesi (ödeme gateway'i yok).

Akış:
  1. Satıcı paywall'da paket seçer → `create_bank_transfer_request` → `pending`
     Subscription Payment + banka bilgisi + referans kodu döner. Abonelik HENÜZ
     aktive edilmez (panel kilitli kalır).
  2. Satıcı havale yapar (açıklamaya referans kodu).
  3. Admin panelden `confirm_subscription_payment` → abonelik `active`
     (upgrade_subscription_plan) → panel açılır. Veya `reject_subscription_payment`.

Owner/tenant çözümü ve aktivasyon subscription.py ile paylaşılır.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

# Rate limit: proje-içi decorator — kova kimliği frappe.session.user'dan türer
# (frappe.rate_limiter key="user" form_dict bypass'ına karşı; detay rate_limit.py).
from tradehub_core.api.rate_limit import rate_limit
from tradehub_core.api.v1.subscription import (
	_resolve_tenant_for_caller,
	upgrade_subscription_plan,
)

# Owner-only çözüm ortak helper'dan (PO/BE-2: import edilebilir — aynı çift
# katman deseni): platform-admin boş-tenant yolu + alt kullanıcı/guest 403,
# yetkisiz deneme DENY audit'i helper içinde yazılır.
from tradehub_core.api.v1.subscription_cancellation import _resolve_owner_tenant
from tradehub_core.utils.notify import notify

_ADMIN_ROLES = ("System Manager", "Marketplace Admin")


def _platform_bank_details() -> dict[str, str]:
	"""Marketplace Settings'ten platform banka bilgisi (havale ekranı için)."""
	s = frappe.get_cached_doc("Marketplace Settings")
	return {
		"bank_name": s.get("subscription_bank_name") or "",
		"account_holder": s.get("subscription_account_holder") or "",
		"iban": s.get("subscription_iban") or "",
		"instructions": s.get("subscription_payment_instructions") or "",
	}


def _plan_amount(plan_doc, billing_cycle: str) -> tuple[float, str]:
	"""Plan + döneme göre tutar ve para birimi."""
	if billing_cycle == "monthly":
		amount = float(plan_doc.get("monthly_price") or 0)
	else:
		amount = float(plan_doc.get("yearly_price") or 0)
	return amount, (plan_doc.get("currency") or "EUR")


def _payment_public_view(payment) -> dict[str, Any]:
	"""Satıcıya gösterilecek havale talebi özeti + banka bilgisi."""
	return {
		"payment": payment.name,
		"status": payment.status,
		"plan": payment.plan,
		"billing_cycle": payment.billing_cycle,
		"amount": payment.amount,
		"currency": payment.currency,
		"reference_code": payment.reference_code,
		"bank": _platform_bank_details(),
	}


@frappe.whitelist(methods=["POST"])
def create_bank_transfer_request(plan: str, billing_cycle: str = "yearly") -> dict[str, Any]:
	"""Satıcı: seçilen paket için havale/EFT ödeme talebi oluştur (pending)."""
	tenant = (_resolve_tenant_for_caller() or "").strip()
	if not tenant:
		frappe.throw(_("Mağaza bulunamadı."), frappe.PermissionError)
	# R5 — askıdaki (Suspended) mağaza yeni havale talebi açamaz (AC-13):
	# hesap silme akışı profili Suspended bırakır; önce admin reaktivasyonu gerekir.
	if frappe.db.get_value("Admin Seller Profile", tenant, "status") == "Suspended":
		frappe.throw(
			_("Mağaza askıya alınmış; yeni ödeme talebi açılamaz — admin işlemi gerekli."),
			frappe.ValidationError,
		)
	if billing_cycle not in ("monthly", "yearly"):
		billing_cycle = "yearly"
	if not frappe.db.exists("Subscription Plan", plan):
		frappe.throw(_("Plan bulunamadı: {0}").format(plan))

	plan_doc = frappe.get_doc("Subscription Plan", plan)
	if not plan_doc.is_active:
		frappe.throw(_("'{0}' planı seçilemez.").format(plan), frappe.ValidationError)

	amount, currency = _plan_amount(plan_doc, billing_cycle)
	if amount <= 0:
		# Enterprise gibi özel fiyatlı paketler havale akışına girmez.
		frappe.throw(_("Bu paket için lütfen satış ekibiyle iletişime geçin."), frappe.ValidationError)

	# Aynı mağaza için zaten bekleyen talep varsa onu döndür (çift kayıt önle).
	existing = frappe.db.get_value("Subscription Payment", {"store": tenant, "status": "pending"}, "name")
	if existing:
		payment = frappe.get_doc("Subscription Payment", existing)
		# AC-5 — bayat fiyat: plan/cycle AYNI kalsa bile güncel plan fiyatı
		# (amount/currency) bekleyen talebin tutarından farklıysa tazelenir
		# (bayat 5.990€ bulgusu; currency değişimi de kapsanır — risk kaydı).
		amount_stale = float(payment.amount or 0) != amount or (payment.currency or "") != currency
		# Plan/dönem değiştiyse güncelle (kullanıcı farklı paket seçmiş olabilir).
		if payment.plan != plan or payment.billing_cycle != billing_cycle or amount_stale:
			payment.plan = plan
			payment.billing_cycle = billing_cycle
			payment.amount = amount
			payment.currency = currency
			payment.flags.ignore_permissions = True
			payment.save(ignore_permissions=True)
			frappe.db.commit()
		view = _payment_public_view(payment)
		if amount_stale:
			# E4 — additive sinyal: tutar BU çağrıda güncellendi (AD-1 pending
			# bloğu bilgilendirme notu gösterir). Mevcut yanıt alanları değişmez;
			# tutar aynıysa alan hiç eklenmez.
			view["amount_updated"] = True
		return view

	payment = frappe.new_doc("Subscription Payment")
	payment.store = tenant
	payment.plan = plan
	payment.billing_cycle = billing_cycle
	payment.amount = amount
	payment.currency = currency
	payment.status = "pending"
	payment.flags.ignore_permissions = True
	payment.insert(ignore_permissions=True)
	frappe.db.commit()

	_notify_admins_new_payment(payment)
	return _payment_public_view(payment)


@frappe.whitelist()
def get_my_pending_payment() -> dict[str, Any] | None:
	"""Satıcı: bekleyen havale talebim var mı? (paywall 'onay bekleniyor' durumu)."""
	tenant = (_resolve_tenant_for_caller() or "").strip()
	if not tenant:
		return None
	name = frappe.db.get_value("Subscription Payment", {"store": tenant, "status": "pending"}, "name")
	if not name:
		return None
	return _payment_public_view(frappe.get_doc("Subscription Payment", name))


# Yanıt sözleşmesi alan seti (shared_contracts — list_my_subscription_payments).
_MY_PAYMENT_FIELDS = (
	"name",
	"plan",
	"billing_cycle",
	"amount",
	"currency",
	"reference_code",
	"status",
	"requested_at",
	"confirmed_at",
	"rejection_reason",
)


@frappe.whitelist(methods=["GET"])
@rate_limit(max_calls=30, window_seconds=300, scope="list_my_subscription_payments")
def list_my_subscription_payments() -> list[dict[str, Any]]:
	"""Satıcı: kendi mağazamın ödeme geçmişi (makbuz listesi — AC-6).

	Owner-only çift katman:
	  1. `_resolve_owner_tenant` — alt kullanıcı (tradehub_is_owner=0), guest ve
	     platform-admin boş-tenant yolu 403 (admin geçmişi Desk'ten
	     `list_subscription_payments` ile görür); DENY audit helper içinde.
	  2. Sorgu `store=tenant` filtresiyle gider + dönen satırların store'u
	     tekrar doğrulanır (defense-in-depth).

	Returns:
	    Sözleşme alanlarıyla en fazla 100 satır, requested_at desc.
	"""
	tenant = _resolve_owner_tenant(_("Sadece mağaza sahibi ödeme geçmişini görüntüleyebilir."))

	# get_all gerekçesi: Subscription Payment seller rolüne DocType-level read
	# vermez (admin onay kaydı) — get_list her satıcı için boş dönerdi. Owner
	# yukarıda çözüldü ve tenant filtresi elle uygulanıyor; store alanı yalnız
	# aşağıdaki ikinci katman doğrulaması için çekilir, yanıtta yer almaz.
	rows = frappe.get_all(
		"Subscription Payment",
		filters={"store": tenant},
		fields=["store", *_MY_PAYMENT_FIELDS],
		order_by="requested_at desc",
		limit_page_length=100,
	)

	# Defense-in-depth (2. katman): sorgu zaten store filtresiyle gitti — bu dal
	# yalnız filtre katmanı ileride değişir/gevşerse cross-tenant satır sızmasın
	# diye bilinçli tutuluyor (subscription_cancellation ile aynı desen).
	out: list[dict[str, Any]] = []
	for r in rows:
		if (r.pop("store", None) or "") != tenant:
			continue
		out.append(r)
	return out


@frappe.whitelist(methods=["POST"])
def confirm_subscription_payment(payment: str) -> dict[str, Any]:
	"""Admin: havalenin geldiğini doğrula → aboneliği aktive et."""
	frappe.only_for(_ADMIN_ROLES)
	doc = frappe.get_doc("Subscription Payment", payment)
	if doc.status != "pending":
		frappe.throw(_("Bu ödeme zaten işlenmiş (durum: {0}).").format(doc.status))

	doc.status = "confirmed"
	doc.confirmed_at = now_datetime()
	doc.confirmed_by = frappe.session.user
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)

	# Aboneliği aktive et (admin → tenant parametresi ile). billing_cycle
	# geçirilir ki dönem hesabı ödemenin dönemine göre yapılsın (BE-3 / AC-7);
	# geçirilmezse mevcut kayıt/monthly default'una düşüp yanlış dönem yazılırdı.
	upgrade_subscription_plan(
		new_plan=doc.plan,
		tenant=doc.store,
		start_trial=0,
		reason=f"Bank transfer confirmed: {doc.name} ({doc.reference_code})",
		billing_cycle=doc.billing_cycle,
	)

	_notify_seller_payment_result(doc, confirmed=True)
	return {"ok": True, "payment": doc.name, "plan": doc.plan, "store": doc.store}


@frappe.whitelist(methods=["POST"])
def reject_subscription_payment(payment: str, reason: str = "") -> dict[str, Any]:
	"""Admin: havale gelmedi/yanlış → talebi reddet."""
	frappe.only_for(_ADMIN_ROLES)
	doc = frappe.get_doc("Subscription Payment", payment)
	if doc.status != "pending":
		frappe.throw(_("Bu ödeme zaten işlenmiş (durum: {0}).").format(doc.status))

	doc.status = "rejected"
	doc.rejection_reason = (reason or "")[:500]
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)

	_notify_seller_payment_result(doc, confirmed=False)
	return {"ok": True, "payment": doc.name}


@frappe.whitelist()
def list_subscription_payments(status: str = "pending") -> list[dict[str, Any]]:
	"""Admin: havale talepleri listesi (onay ekranı)."""
	frappe.only_for(_ADMIN_ROLES)
	filters: dict[str, Any] = {}
	if status and status != "all":
		filters["status"] = status
	rows = frappe.get_all(
		"Subscription Payment",
		filters=filters,
		fields=[
			"name",
			"store",
			"plan",
			"billing_cycle",
			"amount",
			"currency",
			"reference_code",
			"status",
			"requested_at",
			"confirmed_at",
		],
		order_by="requested_at desc",
		limit_page_length=200,
	)
	# Mağaza adını ekle (admin listesinde okunur olsun).
	store_ids = list({r["store"] for r in rows if r["store"]})
	name_map = (
		{
			r.name: r.seller_name
			for r in frappe.get_all(
				"Admin Seller Profile",
				filters={"name": ["in", store_ids]},
				fields=["name", "seller_name"],
			)
		}
		if store_ids
		else {}
	)
	for r in rows:
		r["store_name"] = name_map.get(r["store"], r["store"])
	return rows


def _notify_admins_new_payment(payment) -> None:
	"""Yeni havale talebinde Marketplace Admin'lere bildirim (panel-içi)."""
	try:
		admins = frappe.get_all(
			"Has Role",
			filters={"role": "Marketplace Admin", "parenttype": "User"},
			fields=["parent"],
			limit_page_length=50,
		)
		for a in admins:
			notify(
				recipient_user=a.parent,
				type="system",
				title="Yeni abonelik ödeme talebi",
				message=f"{payment.store} — {payment.plan} ({payment.amount} {payment.currency}). Ref: {payment.reference_code}",
				action_url="/abonelik-odemeleri",
				reference_doctype="Subscription Payment",
				reference_name=payment.name,
			)
	except Exception as exc:  # noqa: BLE001
		frappe.log_error(f"admin notify fail: {payment.name}: {exc}", "subscription_payment.notify_admin")


def _notify_seller_payment_result(payment, confirmed: bool) -> None:
	"""Onay/ret sonrası satıcıya bildirim (panel + e-posta)."""
	try:
		owner = frappe.db.get_value("Admin Seller Profile", payment.store, "user")
		if not owner:
			return
		if confirmed:
			title = "Aboneliğiniz aktif edildi 🎉"
			message = f"{payment.plan} paketi ödemeniz onaylandı; satıcı paneliniz açıldı."
		else:
			title = "Ödeme talebiniz reddedildi"
			reason = (payment.rejection_reason or "").strip()
			message = "Havale ödemeniz onaylanamadı." + (f" Sebep: {reason}" if reason else "")
		notify(
			recipient_user=owner,
			type="system",
			title=title,
			message=message,
			action_url="/abonelik",
			reference_doctype="Subscription Payment",
			reference_name=payment.name,
			send_email=True,
			email_subject=title,
			email_body=message,
		)
	except Exception as exc:  # noqa: BLE001
		frappe.log_error(f"seller notify fail: {payment.name}: {exc}", "subscription_payment.notify_seller")

"""BE-2 — Abonelik iptali uçları (Amazon Seller modeli, dönem sonu iptal).

`request_cancellation`: `active` abonelikte `cancel_at_period_end=1` bayrağını
işaretler — status DEĞİŞMEZ, dönem sonunda lifecycle job (BE-4) `canceled`a
çevirir. Zorunlu sebep anketi (allowlist) + opsiyonel not (max 500).
`revoke_cancellation`: planlı iptali tek adımda geri alır.

Yetki (çift katman — AC-4):
  1. Owner çözümü: `_resolve_tenant_for_caller` yeniden kullanılır ama
     platform-admin boş-tenant yolu REDDEDİLİR (admin iptali Desk'ten yapar);
     alt kullanıcı (tradehub_is_owner=0) → 403.
  2. Store eşleşmesi: Store Subscription.store == caller tenant doğrulaması.

Guard'lar: status != 'active' → 417 (trial dahil — R3: trial'da ödeme yok,
iptal gereksiz), current_period_end boş → 417 (BE-1 backfill önkoşul).
Her iki uç idempotent; audit (HIGH, rule_id='auth.subscription_cancellation')
+ Platform Notification (AC-11) + rate limit içerir.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

# GÜVENLİK — frappe.rate_limiter.rate_limit(key="user") KULLANMA: Frappe v15'te
# `key` form_dict'ten okunur (`user_key = frappe.form_dict.get(key, "")`), yani
# istemci `user=<rastgele>` göndererek her çağrıda yeni bucket açar ve limiti
# atlar. Proje-içi decorator kimliği frappe.session.user'dan türetir
# (frappe.cache + TTL sayaç, atomik INCR) — form input'undan etkilenmez.
from tradehub_core.api.rate_limit import rate_limit
from tradehub_core.api.v1.subscription import _resolve_tenant_for_caller
from tradehub_core.audit import log_decision
from tradehub_core.utils.notify import notify

# Zorunlu iptal anketi sebep kodları (AC-10) — aksi 417.
CANCELLATION_REASONS = frozenset(
	{"fiyat", "kullanmiyorum", "ozellik_eksik", "gecici_durgunluk", "kapaniyor", "diger"}
)

# cancellation_note üst sınırı (shared_contracts: max 500 karakter).
_NOTE_MAX_LEN = 500

_RULE_ID = "auth.subscription_cancellation"

# Kayıt okuma/yazma için ortak field seti.
_SUB_FIELDS = [
	"name",
	"store",
	"status",
	"plan",
	"current_period_end",
	"cancel_at_period_end",
	# BE-3: idempotent tekrar çağrının erken dönüş yolunda MEVCUT talep tarihi
	# DB'den okunur — yanıt her zaman ilk talep anını taşır.
	"cancel_requested_at",
]


def _resolve_owner_tenant(denial_message: str) -> str:
	"""Owner-only tenant çözümü — platform-admin boş-tenant yolu reddedilir.

	`_resolve_tenant_for_caller` platform admin için "" döner (tenant paramlı
	Desk akışı); bu uçlar YALNIZ mağaza sahibine açık olduğundan boş tenant da
	403'tür. Alt kullanıcı / guest zaten PermissionError fırlatır — sözleşme
	mesajıyla yeniden fırlatılır (uçlara özgü 403 metni).
	"""
	try:
		tenant = _resolve_tenant_for_caller()
	except frappe.PermissionError:
		tenant = None  # mesajı sözleşmeye çevirip aşağıda fırlat
	if not tenant:
		# Güvenlik denetimi: yetkisiz deneme throw'dan ÖNCE audit'e yazılır —
		# "" = platform-admin boş-tenant yolu (Desk'e yönlendirilir),
		# None = alt kullanıcı / guest (owner çözümü PermissionError verdi).
		log_decision(
			action="subscription.cancellation",
			decision="DENY",
			rule_id=_RULE_ID,
			layer="L2",
			object_doctype="Store Subscription",
			severity="HIGH",
			context={"denied": "platform_admin_path" if tenant == "" else "not_owner"},
		)
		frappe.throw(denial_message, frappe.PermissionError)
	return tenant


def _get_owned_subscription(tenant: str, denial_message: str) -> Any:
	"""Tenant'ın Store Subscription satırını getir + store eşleşmesini doğrula.

	Çift katmanın 2. katmanı (AC-4): sorgu store filtresiyle gitse bile dönen
	satırın store'u caller tenant'ıyla açıkça karşılaştırılır — cross-tenant
	erişim denemesi DENY audit'iyle 403 alır.
	"""
	sub = frappe.db.get_value(
		"Store Subscription",
		{"store": tenant},
		_SUB_FIELDS,
		as_dict=True,
	)
	if not sub:
		frappe.throw(_("Mağazanız için abonelik kaydı bulunamadı."), frappe.ValidationError)
	# Defense-in-depth: sorgu zaten {"store": tenant} filtresiyle gittiği için bu
	# dala normalde ERİŞİLMEZ — yalnız sorgu katmanı ileride değişir/gevşerse
	# cross-tenant sızıntıyı yakalayan ikinci kilit olarak bilinçli tutuluyor.
	if (sub.store or "") != tenant:
		log_decision(
			action="subscription.cancellation",
			decision="DENY",
			rule_id=_RULE_ID,
			layer="L1",
			object_doctype="Store Subscription",
			object_name=sub.name,
			tenant=tenant,
			severity="HIGH",
			context={"denied": "store_mismatch", "subscription_store": sub.store},
		)
		frappe.throw(denial_message, frappe.PermissionError)
	return sub


@frappe.whitelist(methods=["POST"])
@rate_limit(max_calls=5, window_seconds=300, scope="request_cancellation")
def request_cancellation(reason: str, note: str = "") -> dict[str, Any]:
	"""Dönem sonu iptal talebi (AC-5): bayrak işaretlenir, status 'active' KALIR.

	Args:
	    reason: Zorunlu sebep kodu — CANCELLATION_REASONS allowlist'i.
	    note: Opsiyonel serbest metin, max 500 karakter.

	Returns:
	    {ok, subscription, status, cancel_at_period_end, effective_end, plan,
	     already_scheduled, cancel_requested_at} — idempotent tekrar çağrıda
	     already_scheduled=True ve cancel_requested_at İLK talep tarihi kalır (BE-3).
	"""
	denial = _("Sadece mağaza sahibi aboneliği iptal edebilir.")
	tenant = _resolve_owner_tenant(denial)
	sub = _get_owned_subscription(tenant, denial)

	reason = (reason or "").strip()
	if reason not in CANCELLATION_REASONS:
		frappe.throw(
			_("Geçersiz iptal sebebi: {0}. İzin verilen: {1}").format(
				reason or "(boş)", ", ".join(sorted(CANCELLATION_REASONS))
			),
			frappe.ValidationError,
		)
	note = (note or "").strip()
	if len(note) > _NOTE_MAX_LEN:
		frappe.throw(
			_("İptal notu en fazla {0} karakter olabilir.").format(_NOTE_MAX_LEN),
			frappe.ValidationError,
		)

	# R3 — trial dahil: yalnız 'active' abonelik dönem sonu iptali planlayabilir
	# (trial'da ödeme yok, trial_end zaten otomatik sonlandırır).
	if sub.status != "active":
		frappe.throw(
			_("Dönem sonu iptali yalnız aktif abonelikte planlanabilir (mevcut durum: {0}).").format(
				sub.status
			),
			frappe.ValidationError,
		)
	if not sub.current_period_end:
		frappe.throw(
			_("Dönem bilgisi eksik; iptal planlanamıyor. Lütfen destek ile iletişime geçin."),
			frappe.ValidationError,
		)

	# İdempotent: iptal zaten planlıysa yan etkisiz aynı yanıt (AC-6).
	if cint(sub.cancel_at_period_end):
		return _cancellation_response(sub, already_scheduled=True)

	requested_at = now_datetime()
	doc = frappe.get_doc("Store Subscription", sub.name)
	doc.cancel_at_period_end = 1
	doc.cancellation_reason = reason
	doc.cancellation_note = note
	doc.cancel_requested_by = frappe.session.user
	# BE-3 / AC-8: talep anı damgası — revoke temizler; dönem sonu finalize'da
	# KORUNUR (tarihsel iz, controller yalnız bayrağı sıfırlar).
	doc.cancel_requested_at = requested_at
	# Status DEĞİŞMİYOR → state machine devreye girmez; validate bayrağı yalnız
	# 'active'te kabul eder (BE-1). Yetki yukarıda çift katman doğrulandı;
	# owner'ın DocType-level write perm'i yok → bilinçli ignore_permissions.
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	log_decision(
		action="subscription.cancel_request",
		decision="ALLOW",
		rule_id=_RULE_ID,
		layer="L0",
		object_doctype="Store Subscription",
		object_name=sub.name,
		tenant=tenant,
		plan_code=sub.plan,
		severity="HIGH",
		context={
			"reason": reason,
			"has_note": bool(note),
			"effective_end": str(sub.current_period_end),
			"requested_at": str(requested_at),
		},
	)
	# AC-11 — iptal onayı bildirimi: bitiş tarihi + geri alma yolu.
	notify(
		recipient_user=frappe.session.user,
		recipient_role="seller",
		type="system",
		title=_("Abonelik iptaliniz planlandı"),
		message=_(
			"Aboneliğiniz {0} tarihine kadar tüm haklarıyla devam edecek, sonrasında sona erecek. "
			"Fikriniz değişirse abonelik sayfasından tek tıkla 'İptali Geri Al' diyebilirsiniz."
		).format(sub.current_period_end),
		action_url="/abonelik",
		reference_doctype="Store Subscription",
		reference_name=sub.name,
	)

	return _cancellation_response(sub, already_scheduled=False, cancel_requested_at=requested_at)


@frappe.whitelist(methods=["POST"])
@rate_limit(max_calls=5, window_seconds=300, scope="revoke_cancellation")
def revoke_cancellation() -> dict[str, Any]:
	"""Planlı iptali geri al (AC-6): bayrak 0'lanır, cancellation alanları temizlenir.

	İptal planlı değilse (bayrak 0 — hiç istenmemiş, zaten geri alınmış veya
	dönem bitip 'canceled' olmuş) → 417.
	"""
	denial = _("Sadece mağaza sahibi bu işlemi yapabilir.")
	tenant = _resolve_owner_tenant(denial)
	sub = _get_owned_subscription(tenant, denial)

	if not cint(sub.cancel_at_period_end):
		frappe.throw(_("Geri alınacak bir iptal talebi yok."), frappe.ValidationError)

	doc = frappe.get_doc("Store Subscription", sub.name)
	doc.cancel_at_period_end = 0
	doc.cancellation_reason = None
	doc.cancellation_note = None
	doc.cancel_requested_by = None
	# BE-3: geri almada talep tarihi de diğer cancellation alanlarıyla temizlenir.
	doc.cancel_requested_at = None
	# Yetki yukarıda çift katman doğrulandı (owner + store eşleşmesi);
	# owner'ın DocType-level write perm'i yok → bilinçli ignore_permissions.
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	log_decision(
		action="subscription.cancel_revoke",
		decision="ALLOW",
		rule_id=_RULE_ID,
		layer="L0",
		object_doctype="Store Subscription",
		object_name=sub.name,
		tenant=tenant,
		plan_code=sub.plan,
		severity="HIGH",
		context={"current_period_end": str(sub.current_period_end)},
	)
	# AC-11 — geri alma onayı bildirimi.
	notify(
		recipient_user=frappe.session.user,
		recipient_role="seller",
		type="system",
		title=_("Abonelik iptaliniz geri alındı"),
		message=_("İptal talebiniz kaldırıldı; aboneliğiniz kesintisiz devam edecek."),
		action_url="/abonelik",
		reference_doctype="Store Subscription",
		reference_name=sub.name,
	)

	return {
		"ok": True,
		"subscription": sub.name,
		"status": sub.status,
		"cancel_at_period_end": 0,
		"current_period_end": sub.current_period_end,
		"plan": sub.plan,
		# BE-3 additive (AC-8): geri almada talep tarihi temizlendi.
		"cancel_requested_at": None,
	}


def _cancellation_response(
	sub: Any, *, already_scheduled: bool, cancel_requested_at: Any = None
) -> dict[str, Any]:
	"""request_cancellation sözleşme yanıtı (shared_contracts ile birebir).

	`cancel_requested_at` (BE-3 additive, AC-8): yeni talepte az önce yazılan damga
	parametreyle gelir; idempotent tekrar çağrının erken dönüşünde parametre boş
	kalır ve DB'den okunmuş MEVCUT değer (`_SUB_FIELDS` üzerinden `sub`'da) döner —
	ilk talep tarihi tekrar çağrıda DEĞİŞMEZ.
	"""
	return {
		"ok": True,
		"subscription": sub.name,
		"status": sub.status,
		"cancel_at_period_end": 1,
		"effective_end": sub.current_period_end,
		"plan": sub.plan,
		"already_scheduled": already_scheduled,
		"cancel_requested_at": cancel_requested_at or sub.get("cancel_requested_at"),
	}

# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik modülü permission fonksiyonları.

Platform yöneticileri tam erişime sahipken, seller ve buyer kullanıcıları
yalnızca kendi sevkiyatlarına erişebilir (tenant izolasyonu).

Bu fonksiyonlar hooks.py içinde permission_query_conditions ve
has_permission olarak kayıt edilir. Carrier Account kaydı LOG-028 ile,
Shipment / Shipment Leg / Shipment Event kayıtları LOG-055 (+ Faz 4 F1)
ile yapıldı.

Rol matrisi:
  - Platform full access: System Manager, Marketplace Admin, Logistics Manager,
    Support Agent, Platform Admin
  - Platform Finance: read-only (has_permission'da kontrol)
  - Seller-scoped: Logistics Operator / Seller rolleri (seller_profile match)
  - Buyer-scoped: kendi siparişine ait sevkiyatlar (buyer match)

P1-1 platform-genişlik erişim invariant'ı: platform-full dallar (boş filtre /
koşulsuz True) yalnız seller_profile'ı OLMAYAN kullanıcıya uygulanır —
seller_profile'ı olan kullanıcı platform rolü taşısa bile tenant-scoped
değerlendirilir (System Manager/Administrator muaf). Nihai Logistics Manager
rol kapsamı P3 kararına bağlı; bu guard karar ne olursa olsun geçerli invariant.
"""

from __future__ import annotations

import frappe

from tradehub_core.logistics.constants import CACHE_PREFIX

# ---------------------------------------------------------------------------
# Platform rol kümeleri — permissions.py ana modülündeki ile tutarlı
# ---------------------------------------------------------------------------
_PLATFORM_FULL_ACCESS_ROLES: frozenset[str] = frozenset({
	"System Manager",
	"Marketplace Admin",
	"Logistics Manager",
	"Support Agent",
	"Platform Admin",
})

_SHIPMENT_WRITE_ROLES: frozenset[str] = frozenset({
	"System Manager",
	"Marketplace Admin",
	"Logistics Manager",
	"Platform Admin",
})

_SHIPMENT_CANCEL_ROLES: frozenset[str] = frozenset({
	"Logistics Manager",
})

_WRITE_PTYPES: frozenset[str] = frozenset({
	"write", "create", "delete", "submit", "cancel", "amend",
})

# P1-4: tenant (seller_profile'lı) kullanıcıda yazma-türü ptype'lara izinli
# roller — Seller Logistics salt-okumadır. NOT (P3): nihai seller-tarafı rol
# matrisi P3 kararına bağlı; bu küme karar netleşene dek geçerli invariant.
_TENANT_WRITE_ROLES: frozenset[str] = frozenset({
	"Logistics Operator",
	"Logistics Manager",
})

# doc=None (doctype-seviyesi) kontrolde yazma-turu ptype'lara izinli roller:
# platform yazma rolleri + tenant-scoped Logistics Operator (J.2 matrisi)
_DOCTYPE_LEVEL_WRITE_ROLES: frozenset[str] = _SHIPMENT_WRITE_ROLES | frozenset({
	"Logistics Operator",
})


# ---------------------------------------------------------------------------
# Helper: seller_profile resolver (mevcut permissions.py pattern)
# ---------------------------------------------------------------------------
def _get_user_seller_profile(user: str) -> str | None:
	"""User'ın bağlı olduğu Admin Seller Profile name'ini döndürür.

	Kanonik tenant resolver'ı kullanır (User.tradehub_tenant).
	Test fallback'i: Admin Seller Profile.user ile arama.
	"""
	try:
		from tradehub_core.utils.tenant import _get_seller_profile_for_user

		return _get_seller_profile_for_user(user)
	except (ImportError, AttributeError):
		# Test fallback — production'da tenant_utils her zaman yüklü
		return frappe.db.get_value(
			"Admin Seller Profile", {"user": user}, "name"
		)


def _doc_field(doc: object, field: str) -> str | None:
	"""Doc veya dict'ten field değeri oku (defensive)."""
	if isinstance(doc, dict):
		return doc.get(field)
	return getattr(doc, field, None)


# Tenant/kapsam sınırını aşma denemesi sayılan reddetme gerekçeleri — bunlar
# saldırı sinyali olabilir, HIGH severity ile kaydedilir (utils/tenant.py ile aynı
# konvansiyon).
_CROSS_BOUNDARY_REASONS: frozenset[str] = frozenset({
	"seller_profile_mismatch",
	"platform_global_account_tenant_denied",
	# Tenant'lı LM'in BAŞKA tenant'ın sevkiyatını iptal denemesi de sınır
	# aşımıdır (denetim 2026-08-20): NORMAL yazılıyordu, HIGH olmalı.
	"cancel_tenant_mismatch",
})

# Aynı (kullanıcı, eylem, nesne) reddi bu süre içinde tekrar yazılmaz.
_DENY_DEDUP_TTL_SECONDS: int = 60


def _log_deny(
	user: str,
	action: str,
	doc: object | None = None,
	reason: str = "",
	object_doctype: str = "Shipment",
) -> None:
	"""Permission DENY kararını audit log'a yaz (best-effort).

	İki filtre uygulanır — `log_decision` senkron bir DB insert'i olduğu için
	her reddi yazmak istek gecikmesine ve ADL tablosunun şişmesine yol açıyordu:

	1. **doc=None atlanır.** Doctype seviyesindeki kontrolleri Frappe her liste
	   ve form açılışında çağırır ("Yeni" butonu gösterilsin mi?). Kullanıcı
	   henüz bir şey denememişken satır yazmak sinyal değil gürültüdür; üstelik
	   ADL şeması nesne bazlıdır, `object_name` boş kalırdı.
	2. **Kısa süreli tekrar bastırma.** Aynı kullanıcının aynı nesneye aynı
	   eylemi tekrar denemesi (sayfa yenileme, retry) 60 sn içinde tek satır
	   üretir.

	Tenant sınırını aşma denemeleri HIGH severity ile kaydedilir.

	P1-6e: object_doctype explicit parametredir — action string'inden substring
	heuristiği ile doctype türetme kaldırıldı; her çağıran doğru doctype'ı geçer.
	"""
	if doc is None:
		return

	object_name = _doc_field(doc, "name")
	dedup_key = f"{CACHE_PREFIX}deny:{user}:{action}:{object_name}"

	try:
		from tradehub_core.audit import log as audit

		# expires=True ZORUNLU: Frappe'de `set_value(..., expires_in_sec=...)`
		# değeri yalnız Redis'e yazar, `frappe.local.cache`'e yazmaz. `get_value`
		# ise varsayılan `expires=False` ile ilk miss'i local cache'e None olarak
		# yazar ve sonraki okumalar Redis'e hiç gitmez — dedup sessizce çalışmaz.
		if frappe.cache.get_value(dedup_key, expires=True):
			return
		frappe.cache.set_value(dedup_key, 1, expires_in_sec=_DENY_DEDUP_TTL_SECONDS)

		audit.log_decision(
			actor=user,
			action=action,
			decision=audit.DECISION_DENY,
			layer=audit.LAYER_L2,
			object_doctype=object_doctype,
			object_name=object_name,
			tenant=_doc_field(doc, "seller_profile"),
			rule_id=f"logistics.{action}",
			severity=(
				audit.SEVERITY_HIGH
				if reason in _CROSS_BOUNDARY_REASONS
				else audit.SEVERITY_NORMAL
			),
			context={"reason": reason} if reason else None,
		)
	except Exception:  # noqa: BLE001 — audit hatası business flow'u bozmaz
		frappe.log_error(
			f"Audit log yazılamadı: {action} deny for {user}",
			"logistics.permissions",
		)


# ---------------------------------------------------------------------------
# Shipment permission fonksiyonları
# ---------------------------------------------------------------------------


def shipment_query_conditions(user: str | None = None) -> str:
	"""Shipment listesi için SQL koşulu döndürür.

	Platform rolleri (System Manager, Logistics Manager, Support Agent,
	Platform Admin, Marketplace Admin) tam erişim alır.
	Platform Finance read-only erişim alır (has_permission'da kontrol).
	Seller rolü yalnızca kendi mağazasına ait sevkiyatları görür.
	Buyer rolü yalnızca kendi siparişlerine ait sevkiyatları görür.

	Args:
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		SQL WHERE koşul string'i.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return "1=0"

	if user == "Administrator":
		return ""

	roles = set(frappe.get_roles(user))

	# System Manager muafiyeti aynen korunur (P1-1).
	if "System Manager" in roles:
		return ""

	# P1-1 platform-genişlik erişim invariant'ı: boş filtre (platform-full) dalı
	# yalnız seller_profile'ı OLMAYAN kullanıcıya uygulanır. seller_profile'lı
	# kullanıcı platform rolü taşısa bile tenant-scoped değerlendirilir.
	# Nihai LM rol kapsamı P3 kararına bağlı; bu guard karar ne olursa olsun
	# geçerli invariant.
	seller_profile = _get_user_seller_profile(user)

	# Platform full access + Platform Finance (read-only): tüm sevkiyatlar
	if not seller_profile and (roles & _PLATFORM_FULL_ACCESS_ROLES or "Platform Finance" in roles):
		return ""

	# Seller-scoped: kendi mağazasının sevkiyatları. P1-6f: tenant kullanıcısı
	# aynı zamanda buyer olduğu sevkiyatları da görür (satıcı başka mağazadan
	# alım yapabilir — buyer görünürlüğü tenant filtresiyle kaybolmasın).
	if seller_profile:
		return (
			f"(`tabShipment`.`seller_profile` = {frappe.db.escape(seller_profile)}"
			f" OR `tabShipment`.`buyer` = {frappe.db.escape(user)})"
		)

	# Buyer-scoped: kendi siparişlerine ait sevkiyatlar
	# NOT (2026-08-20 denetim): buyer read DocPerm'i bilinçli olarak henüz yok —
	# bu dal storefront takip fazında (12-BE) DocPerm satırıyla birlikte
	# canlanacak; fail-closed.
	return f"`tabShipment`.`buyer` = {frappe.db.escape(user)}"


def shipment_has_permission(
	doc: object,
	ptype: str | None = None,
	user: str | None = None,
) -> bool:
	"""Tek bir Shipment dokümanı için yetki kontrolü.

	Rol + ptype matrisi:
	  - Administrator: tam erişim
	  - cancel: sadece Logistics Manager
	  - Platform Finance: yalnız read/report/export (tüm yazma-türü ptype'lar False)
	  - read: tenant izolasyonu (seller_profile match veya buyer match)
	  - Support Agent: sadece read
	  - Buyer: sadece read, kendi siparişi
	  - Her DENY'da audit.log_decision() çağrılır

	Args:
		doc: Shipment dokümanı.
		ptype: İzin tipi (read, write, create, delete, submit, cancel).
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		Erişim izni varsa True.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		_log_deny(user or "Guest", "shipment.access", doc, "guest_denied", object_doctype="Shipment")
		return False

	if user == "Administrator":
		return True

	roles = set(frappe.get_roles(user))

	# P1-1 platform-genişlik erişim invariant'ı: koşulsuz-True (platform-full)
	# dallar yalnız seller_profile'ı OLMAYAN kullanıcıya uygulanır;
	# seller_profile'lı kullanıcı platform rolü taşısa bile tenant-scoped
	# değerlendirilir. System Manager/Administrator muafiyeti korunur.
	# Nihai LM rol kapsamı P3 kararına bağlı; bu guard karar ne olursa olsun
	# geçerli invariant.
	seller_profile = _get_user_seller_profile(user)

	# ptype='cancel' → sadece Logistics Manager. P1-1: seller_profile'lı LM
	# yalnız KENDİ tenant'ının sevkiyatını iptal edebilir.
	if ptype == "cancel":
		if "System Manager" in roles:
			return True
		if not (roles & _SHIPMENT_CANCEL_ROLES):
			_log_deny(user, "shipment.cancel", doc, "cancel_requires_logistics_manager", object_doctype="Shipment")
			return False
		if not seller_profile:
			return True  # platform LM — tenant kısıtı yok
		if doc is None:
			return True  # doctype-seviyesi kontrol; per-doc tenant kontrolü doc'lu çağrıda
		if _doc_field(doc, "seller_profile") == seller_profile:
			return True
		_log_deny(user, "shipment.cancel", doc, "cancel_tenant_mismatch", object_doctype="Shipment")
		return False

	if not seller_profile:
		# Support Agent → sadece read
		if "Support Agent" in roles and not (roles & (_PLATFORM_FULL_ACCESS_ROLES - {"Support Agent"})):
			if ptype and ptype != "read":
				_log_deny(user, f"shipment.{ptype}", doc, "support_agent_read_only", object_doctype="Shipment")
				return False
			# read izni için tenant kontrolüne gerek yok — tüm sevkiyatları okuyabilir
			return True

		# Platform Finance → yalnız READ (J.2 yetki matrisi: read/report/export);
		# write dahil tüm yazma-türü ptype'lar reddedilir
		if "Platform Finance" in roles and not (roles & _SHIPMENT_WRITE_ROLES):
			if ptype and ptype in _WRITE_PTYPES:
				_log_deny(user, f"shipment.{ptype}", doc, "platform_finance_read_only", object_doctype="Shipment")
				return False
			return True  # read/report/export türü izinler

		# Platform full access rolleri — write dahil tam erişim
		if roles & _SHIPMENT_WRITE_ROLES:
			return True

	# doc yoksa (doctype-seviyesi kontrol) → tenant kontrolü yapılamaz.
	# Okuma-türü ptype'lar liste görünümlerini kırmamak için serbest;
	# yazma-türü ptype'larda rol matrisi uygulanır (fail-open kapatıldı).
	if doc is None:
		if ptype and ptype in _WRITE_PTYPES:
			if roles & _DOCTYPE_LEVEL_WRITE_ROLES:
				return True
			_log_deny(user, f"shipment.{ptype}", doc, "doctype_level_write_denied", object_doctype="Shipment")
			return False
		return True

	# Seller-scoped: kendi mağazasının sevkiyatı
	doc_seller = _doc_field(doc, "seller_profile")

	if seller_profile and doc_seller and doc_seller == seller_profile:
		# P1-4: read-türü ptype'lar (read/report/export/print/email) serbest;
		# yazma-türü yalnız Logistics Operator/Manager rollü tenant kullanıcısı
		# (Seller Logistics salt-okuma). NOT (P3): nihai seller-tarafı rol
		# matrisi P3 kararına bağlı.
		if ptype and ptype in _WRITE_PTYPES:
			if roles & _TENANT_WRITE_ROLES:
				return True
			_log_deny(
				user, f"shipment.{ptype}", doc,
				"tenant_write_requires_logistics_role", object_doctype="Shipment",
			)
			return False
		return True

	# Buyer-scoped: kendi siparişi → yalnız okuma-türü. P1-6f: seller_profile
	# uyuşmazlığında da bu dala düşülür (satıcı, buyer olduğu sevkiyatı okur).
	# NOT (2026-08-20 denetim): buyer read DocPerm'i bilinçli olarak henüz yok —
	# bu dal storefront takip fazında (12-BE) DocPerm satırıyla birlikte
	# canlanacak; fail-closed.
	doc_buyer = _doc_field(doc, "buyer")
	if doc_buyer == user:
		if ptype and ptype in _WRITE_PTYPES:
			_log_deny(user, f"shipment.{ptype}", doc, "buyer_read_only", object_doctype="Shipment")
			return False
		return True

	# Çapraz-tenant sınıflandırma (denetim 2026-08-20): seller_profile'lı
	# kullanıcının BAŞKA tenant'ın sevkiyatına erişim denemesi sınır aşımıdır ve
	# HIGH severity ile loglanır; tenant'sız olağan reddetmeler NORMAL kalır.
	if seller_profile and doc_seller and doc_seller != seller_profile:
		_log_deny(
			user, f"shipment.{ptype or 'read'}", doc,
			"seller_profile_mismatch", object_doctype="Shipment",
		)
		return False

	_log_deny(user, f"shipment.{ptype or 'read'}", doc, "no_access", object_doctype="Shipment")
	return False


# ---------------------------------------------------------------------------
# Shipment Leg permission fonksiyonları (Dalga B — LOG-055)
#
# Leg'ler operasyonel kayıtlardır; izolasyon Shipment üzerinden JOIN ile
# değil, Carrier Account emsalindeki gibi denormalize seller_profile alanı
# üzerinden sağlanır (Shipment Leg.seller_profile — tenant çift hook set eder).
# ---------------------------------------------------------------------------


def shipment_leg_query_conditions(user: str | None = None) -> str:
	"""Shipment Leg listesi için SQL koşulu döndürür.

	Platform full access rolleri (+ read-only Platform Finance) tüm
	bacakları görür; seller-scoped kullanıcı yalnız kendi tenant'ının
	bacaklarını görür. Buyer'a leg listesi açılmaz (operasyonel veri —
	buyer takibi Shipment/Event üzerinden yapılır).

	Args:
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		SQL WHERE koşul string'i.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return "1=0"

	if user == "Administrator":
		return ""

	roles = set(frappe.get_roles(user))

	# System Manager muafiyeti aynen korunur (P1-1).
	if "System Manager" in roles:
		return ""

	# P1-1 invariant: boş filtre (platform-full) dalı yalnız seller_profile'ı
	# OLMAYAN kullanıcıya; seller_profile'lı kullanıcı platform rolü taşısa
	# bile tenant-scoped. Nihai LM rol kapsamı P3 kararına bağlı; bu guard
	# karar ne olursa olsun geçerli invariant.
	seller_profile = _get_user_seller_profile(user)

	if not seller_profile and (roles & _PLATFORM_FULL_ACCESS_ROLES or "Platform Finance" in roles):
		return ""

	if seller_profile:
		return (
			f"`tabShipment Leg`.`seller_profile` = {frappe.db.escape(seller_profile)}"
		)

	return "1=0"


def shipment_leg_has_permission(
	doc: object,
	ptype: str | None = None,
	user: str | None = None,
) -> bool:
	"""Tek bir Shipment Leg dokümanı için yetki kontrolü.

	Platform yazma rolleri tam erişim; Support Agent + Platform Finance
	yalnız read; seller-scoped kullanıcı kendi tenant'ının leg'ine erişir.
	Buyer erişemez.

	Args:
		doc: Shipment Leg dokümanı.
		ptype: İzin tipi (read, write, create, delete).
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		Erişim izni varsa True.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		_log_deny(user or "Guest", "shipment_leg.access", doc, "guest_denied", object_doctype="Shipment Leg")
		return False

	if user == "Administrator":
		return True

	roles = set(frappe.get_roles(user))

	# P1-1 invariant: koşulsuz-True (platform-full) dallar yalnız
	# seller_profile'ı OLMAYAN kullanıcıya; seller_profile'lı kullanıcı platform
	# rolü taşısa bile tenant-scoped değerlendirilir. System Manager muafiyeti
	# korunur. Nihai LM rol kapsamı P3 kararına bağlı; bu guard karar ne olursa
	# olsun geçerli invariant.
	if "System Manager" in roles:
		return True

	seller_profile = _get_user_seller_profile(user)

	if not seller_profile:
		# Platform yazma rolleri → tam erişim
		if roles & _SHIPMENT_WRITE_ROLES:
			return True

		# Support Agent / Platform Finance → yalnız okuma-türü ptype'lar
		if roles & {"Support Agent", "Platform Finance"}:
			if ptype and ptype in _WRITE_PTYPES:
				_log_deny(user, f"shipment_leg.{ptype}", doc, "read_only_role", object_doctype="Shipment Leg")
				return False
			return True

		_log_deny(user, f"shipment_leg.{ptype or 'read'}", doc, "no_tenant", object_doctype="Shipment Leg")
		return False

	# doc yoksa (doctype-seviyesi kontrol): seller-scoped roller liste/create
	# görebilsin; per-doc tenant kontrolü doc'lu çağrıda uygulanır.
	if doc is None:
		return True

	# Tenant izolasyonu: denormalize seller_profile eşleşmesi
	doc_seller = _doc_field(doc, "seller_profile")
	if doc_seller == seller_profile:
		# P1-4: yazma-türü ptype'lar yalnız Logistics Operator/Manager rollü
		# tenant kullanıcısına (Seller Logistics salt-okuma). P3 notu: nihai
		# seller-tarafı rol matrisi P3 kararına bağlı.
		if ptype and ptype in _WRITE_PTYPES:
			if roles & _TENANT_WRITE_ROLES:
				return True
			_log_deny(
				user, f"shipment_leg.{ptype}", doc,
				"tenant_write_requires_logistics_role", object_doctype="Shipment Leg",
			)
			return False
		return True

	# Tur-2 re-audit: mismatch (HIGH) yalnız İKİ taraf da doluyken — Shipment
	# deseniyle hizalı. Bu noktada seller_profile dolu ve doc_seller !=
	# seller_profile garanti; doc_seller doluysa sınır aşımıdır.
	if doc_seller:
		_log_deny(
			user, f"shipment_leg.{ptype or 'read'}", doc,
			"seller_profile_mismatch", object_doctype="Shipment Leg",
		)
		return False

	# doc_seller boş: denormalize tenant alanı set edilmemiş (hook atlanmış /
	# eski kayıt) — saldırı sinyali değil veri bütünlüğü sinyali; NORMAL severity.
	_log_deny(
		user, f"shipment_leg.{ptype or 'read'}", doc,
		"missing_tenant_denorm", object_doctype="Shipment Leg",
	)
	return False


# ---------------------------------------------------------------------------
# Shipment Event permission fonksiyonları (Faz 4 — F1 tenant okuma izolasyonu)
#
# Event'ler append-only operasyonel kayıtlardır; izolasyon Shipment Leg
# emsalindeki gibi denormalize seller_profile alanı üzerinden sağlanır
# (Shipment Event.seller_profile — tenant çift hook set eder).
# ---------------------------------------------------------------------------


def shipment_event_query_conditions(user: str | None = None) -> str:
	"""Shipment Event listesi için SQL koşulu döndürür.

	Platform full access rolleri (+ read-only Platform Finance) tüm
	olayları görür; seller-scoped kullanıcı yalnız kendi tenant'ının
	olaylarını görür. Buyer'a event listesi açılmaz (operasyonel veri —
	buyer takibi Shipment üzerinden yapılır; Shipment Leg emsali).

	Args:
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		SQL WHERE koşul string'i.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return "1=0"

	if user == "Administrator":
		return ""

	roles = set(frappe.get_roles(user))

	# System Manager muafiyeti aynen korunur (P1-1).
	if "System Manager" in roles:
		return ""

	# P1-1 invariant: boş filtre (platform-full) dalı yalnız seller_profile'ı
	# OLMAYAN kullanıcıya; seller_profile'lı kullanıcı platform rolü taşısa
	# bile tenant-scoped. Nihai LM rol kapsamı P3 kararına bağlı; bu guard
	# karar ne olursa olsun geçerli invariant.
	seller_profile = _get_user_seller_profile(user)

	if not seller_profile and (roles & _PLATFORM_FULL_ACCESS_ROLES or "Platform Finance" in roles):
		return ""

	if seller_profile:
		return (
			f"`tabShipment Event`.`seller_profile` = {frappe.db.escape(seller_profile)}"
		)

	return "1=0"


def shipment_event_has_permission(
	doc: object,
	ptype: str | None = None,
	user: str | None = None,
) -> bool:
	"""Tek bir Shipment Event dokümanı için yetki kontrolü.

	Platform yazma rolleri tam erişim; Support Agent + Platform Finance
	yalnız read; seller-scoped kullanıcı kendi tenant'ının event'ine erişir.
	Buyer erişemez. (Append-only update/delete kilidi ayrıca controller'da —
	shipment_event.py validate/on_trash.)

	Args:
		doc: Shipment Event dokümanı.
		ptype: İzin tipi (read, write, create, delete).
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		Erişim izni varsa True.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		_log_deny(
			user or "Guest", "shipment_event.access", doc, "guest_denied", object_doctype="Shipment Event"
		)
		return False

	if user == "Administrator":
		return True

	roles = set(frappe.get_roles(user))

	# P1-1 invariant: koşulsuz-True (platform-full) dallar yalnız
	# seller_profile'ı OLMAYAN kullanıcıya; seller_profile'lı kullanıcı platform
	# rolü taşısa bile tenant-scoped değerlendirilir. System Manager muafiyeti
	# korunur. Nihai LM rol kapsamı P3 kararına bağlı; bu guard karar ne olursa
	# olsun geçerli invariant.
	if "System Manager" in roles:
		return True

	seller_profile = _get_user_seller_profile(user)

	if not seller_profile:
		# Platform yazma rolleri → tam erişim
		if roles & _SHIPMENT_WRITE_ROLES:
			return True

		# Support Agent / Platform Finance → yalnız okuma-türü ptype'lar
		if roles & {"Support Agent", "Platform Finance"}:
			if ptype and ptype in _WRITE_PTYPES:
				_log_deny(
					user, f"shipment_event.{ptype}", doc, "read_only_role", object_doctype="Shipment Event"
				)
				return False
			return True

		_log_deny(user, f"shipment_event.{ptype or 'read'}", doc, "no_tenant", object_doctype="Shipment Event")
		return False

	# doc yoksa (doctype-seviyesi kontrol): seller-scoped roller liste/create
	# görebilsin; per-doc tenant kontrolü doc'lu çağrıda uygulanır.
	if doc is None:
		return True

	# Tenant izolasyonu: denormalize seller_profile eşleşmesi
	doc_seller = _doc_field(doc, "seller_profile")
	if doc_seller == seller_profile:
		# P1-4: yazma-türü ptype'lar yalnız Logistics Operator/Manager rollü
		# tenant kullanıcısına (append-only kilidi ayrıca controller'da). P3
		# notu: nihai seller-tarafı rol matrisi P3 kararına bağlı.
		if ptype and ptype in _WRITE_PTYPES:
			if roles & _TENANT_WRITE_ROLES:
				return True
			_log_deny(
				user, f"shipment_event.{ptype}", doc,
				"tenant_write_requires_logistics_role", object_doctype="Shipment Event",
			)
			return False
		return True

	# Tur-2 re-audit: mismatch (HIGH) yalnız İKİ taraf da doluyken — Shipment
	# deseniyle hizalı. Bu noktada seller_profile dolu ve doc_seller !=
	# seller_profile garanti; doc_seller doluysa sınır aşımıdır.
	if doc_seller:
		_log_deny(
			user, f"shipment_event.{ptype or 'read'}", doc,
			"seller_profile_mismatch", object_doctype="Shipment Event",
		)
		return False

	# doc_seller boş: denormalize tenant alanı set edilmemiş (hook atlanmış /
	# eski kayıt) — saldırı sinyali değil veri bütünlüğü sinyali; NORMAL severity.
	_log_deny(
		user, f"shipment_event.{ptype or 'read'}", doc,
		"missing_tenant_denorm", object_doctype="Shipment Event",
	)
	return False


# ---------------------------------------------------------------------------
# Carrier Account permission fonksiyonları
# ---------------------------------------------------------------------------


def carrier_account_query_conditions(user: str | None = None) -> str:
	"""Carrier Account listesi için SQL koşulu döndürür.

	Carrier Integration Manager tam erişim (kendi tenant).
	Logistics Manager read-only (kendi tenant).
	Diğer roller erişemez.

	Args:
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		SQL WHERE koşul string'i.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return "1=0"

	if user == "Administrator":
		return ""

	roles = set(frappe.get_roles(user))

	# System Manager: tam liste erişimi.
	# Marketplace Admin / Platform Admin kaldırıldı — DocPerm satırları yok,
	# has_permission'daki ölü grant temizliğinin simetriği (BE-4d).
	if "System Manager" in roles:
		return ""

	# Carrier Integration Manager veya Logistics Manager: kendi tenant'ı
	if roles & {"Carrier Integration Manager", "Logistics Manager"}:
		seller_profile = _get_user_seller_profile(user)
		if seller_profile:
			return (
				f"`tabCarrier Account`.`seller_profile`"
				f" = {frappe.db.escape(seller_profile)}"
			)

	# Diğer roller → erişim yok
	return "1=0"


def carrier_account_has_permission(
	doc: object,
	ptype: str | None = None,
	user: str | None = None,
) -> bool:
	"""Tek bir Carrier Account dokümanı için yetki kontrolü.

	Carrier Integration Manager → tam CRUD (kendi tenant).
	Logistics Manager → sadece read (kendi tenant).
	Platform admin rolleri → tam erişim.
	Diğer → False.

	Args:
		doc: Carrier Account dokümanı.
		ptype: İzin tipi (read, write, create, delete).
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		Erişim izni varsa True.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		_log_deny(user or "Guest", "carrier_account.access", doc, "guest_denied", object_doctype="Carrier Account")
		return False

	if user == "Administrator":
		return True

	roles = set(frappe.get_roles(user))

	# System Manager: tenant kısıtı uygulanmaz.
	# NOT: Frappe'de has_permission hook'u izin VEREMEZ, yalnız kısıtlar —
	# DocPerm satırı olmayan Marketplace Admin / Platform Admin grant'ları
	# bu yüzden kaldırıldı (yanıltıcı ölü kod idi).
	if "System Manager" in roles:
		return True

	# doc yoksa (doctype-seviyesi kontrol)
	if doc is None:
		if roles & {"Carrier Integration Manager", "Logistics Manager"}:
			return True
		_log_deny(user, "carrier_account.access", doc, "no_role", object_doctype="Carrier Account")
		return False

	# Tenant izolasyonu: seller_profile eşleşmesi
	seller_profile = _get_user_seller_profile(user)
	doc_seller = _doc_field(doc, "seller_profile")

	if not doc_seller:
		# Platform-global hesap (seller_profile boş): yalnız seller_profile'ı
		# OLMAYAN platform kullanıcıları (ör. platform Carrier Integration
		# Manager) erişebilir; tenant kullanıcısına kapalı.
		if seller_profile:
			_log_deny(
				user, f"carrier_account.{ptype or 'read'}", doc,
				"platform_global_account_tenant_denied", object_doctype="Carrier Account",
			)
			return False
	elif not seller_profile or doc_seller != seller_profile:
		_log_deny(
			user, f"carrier_account.{ptype or 'read'}", doc,
			"seller_profile_mismatch", object_doctype="Carrier Account",
		)
		return False

	# Carrier Integration Manager → tam CRUD
	if "Carrier Integration Manager" in roles:
		return True

	# Logistics Manager → sadece read
	if "Logistics Manager" in roles:
		if ptype and ptype != "read":
			_log_deny(
				user, f"carrier_account.{ptype}", doc,
				"logistics_manager_read_only", object_doctype="Carrier Account",
			)
			return False
		return True

	_log_deny(user, f"carrier_account.{ptype or 'read'}", doc, "no_role", object_doctype="Carrier Account")
	return False


# ---------------------------------------------------------------------------
# Cost field maskeleme guard'ları (BE-8)
# ---------------------------------------------------------------------------


def mask_shipment_cost_fields(doc: object, user: str | None = None) -> None:
	"""view.logistics_cost capability yoksa maliyet alanlarını maskele.

	Shipment dokümanında shipping_cost, insurance_cost, total_cost gibi
	hassas maliyet alanlarını capability kontrolü ile maskeler.

	Args:
		doc: Shipment dokümanı.
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.
	"""
	user = user or frappe.session.user
	# Yalnız Administrator muaf; user falsy ise maskeleme UYGULANIR (fail-closed)
	if user == "Administrator":
		return

	if user:
		try:
			from tradehub_core.utils.permission_resolver import has_capability

			if has_capability(user, "view.logistics_cost"):
				return
		except (ImportError, AttributeError):
			# permission_resolver mevcut değilse maskeleme UYGULA (fail-closed — güvenli taraf)
			pass

	# Maliyet alanlarını maskele — None yazılır, 0 DEĞİL: write yetkili ama
	# capability'siz bir kullanıcı doc'u kaydederse 0 DB'deki gerçek maliyeti ezerdi
	cost_fields = (
		"shipping_cost", "insurance_cost", "total_cost",
		"carrier_cost", "fuel_surcharge", "packaging_cost",
	)
	for field in cost_fields:
		if hasattr(doc, field) and getattr(doc, field, None) is not None:
			setattr(doc, field, None)


def mask_carrier_account_fields(doc: object, user: str | None = None) -> None:
	"""view.carrier_secret capability yoksa api_key/api_secret maskele.

	Carrier Account dokümanında hassas API anahtarlarını capability
	kontrolü ile maskeler.

	Args:
		doc: Carrier Account dokümanı.
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.
	"""
	user = user or frappe.session.user
	# Yalnız Administrator muaf; user falsy ise maskeleme UYGULANIR (fail-closed)
	if user == "Administrator":
		return

	if user:
		try:
			from tradehub_core.utils.permission_resolver import has_capability

			if has_capability(user, "view.carrier_secret"):
				return
		except (ImportError, AttributeError):
			# permission_resolver mevcut değilse maskeleme UYGULA (fail-closed — güvenli taraf)
			pass

	# Hassas alanları maskele.
	# CONSTRAINT: Frappe BaseDocument._save_passwords yalnız TÜM-asterisk
	# değerleri dummy sayıp kaydetmede atlar; bullet (•) içeren bir mask,
	# doc kaydedilirse __Auth'taki gerçek secret'ın üzerine yazılırdı.
	secret_fields = ("api_key", "api_secret", "webhook_secret", "access_token")
	mask_value = "*" * 8
	for field in secret_fields:
		if hasattr(doc, field) and getattr(doc, field, None):
			setattr(doc, field, mask_value)


# -------------------------------------------------------------------------
# Logistics Settings — Singleton permission fonksiyonlari (TUR-102)
#
# NOT (P2-4): logistics_settings_query_conditions kaldirildi — Logistics
# Settings issingle oldugu icin permission_query_conditions tekil DocType'ta
# hic uygulanmaz, olu kod idi (Faz 3.5 olu-grant temizligi emsali).
# has_permission kaydi calisiyor ve KORUNUR.
# -------------------------------------------------------------------------


def logistics_settings_has_permission(
	doc: frappe.Document | None = None,
	ptype: str = "read",
	user: str | None = None,
) -> bool:
	"""Logistics Settings icin per-doc permission kontrolu.

	Singleton DocType oldugu icin basit rol kontrolu yeterli.
	System Manager tam CRUD, Marketplace Admin read + write.

	Args:
		doc: Logistics Settings dokumani.
		ptype: Permission tipi (read, write, create, delete).
		user: Kullanici e-posta adresi (None ise session user).

	Returns:
		Erisim izni verilip verilmedigi.
	"""
	if not user:
		user = frappe.session.user

	roles = frappe.get_roles(user)

	# System Manager tam erisim
	if "System Manager" in roles:
		return True

	# Marketplace Admin read + write
	if "Marketplace Admin" in roles:
		if ptype in ("read", "write"):
			return True

	return False

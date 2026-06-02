# Copyright (c) 2024-2026, TradeHub Team and contributors
# For license information, please see license.txt

"""
Tenant isolation utilities for multi-tenant TradeHub platform.

MİMARİ KARAR (2026-05-20):
TradeHub'da "tenant" kavramı `Admin Seller Profile` ile özdeştir; ayrı bir
"Tenant" DocType'ı yoktur. Bu modül her satıcının kendi verisinde izole
kalmasını sağlayan helper'ları sunar.

Detay: docs/yetki/TradeHub-Yetkilendirme-Mimarisi-v2.md §1, §4, §13

Sorumluluk:
  - get_current_seller_profile(user): User → seller_profile name resolver
  - enforce_seller_isolation_on_insert(doc): before_insert hook, seller_profile
    field'ı boşsa current user'ın seller'ını set eder; başka satıcı yazılmaya
    çalışılırsa reddeder (System Manager hariç).
  - validate_seller_isolation_on_save(doc): validate hook, mevcut bir kaydın
    seller_profile field'ı değiştirilmeye çalışılırsa reddeder.

`is_tenant_admin()` ve `get_tenant_users()` legacy helper'ları geriye-dönük
uyumluluk için korunmuştur ama yeni kod `_get_seller_profile_name` ve role
kontrolünü `permissions.py` üzerinden yapmalıdır.
"""

import frappe
from frappe import _

# ---------------------------------------------------------------------------
# Yeni API (FAZ 1.1) — seller_profile bazlı
# ---------------------------------------------------------------------------

# Tenant izolasyonundan muaf DocType'lar. Bu listedeki doctype'lar için
# enforce_seller_isolation_on_insert ve validate_seller_isolation_on_save
# hook'ları skip eder. Sistem DocType'ları + tenant kavramı dışında kalan
# DocType'lar (Buyer Profile, User vb.) burada listelenir.
TENANT_EXEMPT_DOCTYPES: frozenset[str] = frozenset(
	{
		# Frappe system
		"User",
		"Role",
		"Role Profile",
		"Module Profile",
		"DocType",
		"DocField",
		"DocPerm",
		"Custom Field",
		"Property Setter",
		"Print Format",
		"Report",
		"Page",
		"Module Def",
		"Workflow",
		"Workflow State",
		"Workflow Action Master",
		"Workflow Transition",
		"File",
		"Comment",
		"Communication",
		"Tag",
		"Tag Link",
		# Tenant/global master data
		"Tenant",
		"Organization",
		"Buyer Profile",
		"User Profile",
		"Address",
		# Public catalog (tenant ile filtrelenmemeli)
		"Brand",
		"Product Family",
		"Product Attribute",
		"Attribute Set",
		"Product Category",
		# Singleton/site settings
		"Marketplace Settings",
		"System Settings",
		"Website Settings",
		# Audit (write-protected by other means)
		"Activity Log",
		"Error Log",
	}
)


def _get_seller_profile_for_user(user: str | None = None) -> str | None:
	"""User'a bağlı aktif Admin Seller Profile name'i — yoksa None.

	Resolver sırası:
	  1. User.tradehub_tenant → sub-user davet sonrası set edilen mağaza
	     (Co-Owner, Finance Staff, Operations vs. hepsi Owner'ın mağazasını görür)
	  2. Admin Seller Profile.user = session.user (Owner direkt linki)
	  3. Admin Seller Profile.email = session.user (legacy)

	Cache stratejisi (POSITIVE-ONLY, 2026-05-22):
	  Sadece profile bulunan kullanıcılar için cache yazılır. Negative caching
	  (None değerini cache'lemek) intermittent bug yaratıyordu: sub-user invite
	  henüz commit olmadan ilk lookup None döner, cache'e boş string yazılır,
	  sonraki 5 dakika boyunca yenileme None döner → "Satıcı profili bulunamadı"
	  ekranı flicker eder. Pozitif-only cache: miss durumunda her zaman fresh DB
	  lookup yapılır (~1ms maliyet vs UX bozukluğu).
	"""
	user = user or frappe.session.user
	if not user or user in ("Guest", "Administrator"):
		return None

	cache_key = f"tradehub:seller_for_user:{user}"
	cached = frappe.cache().get_value(cache_key)
	# Boş string artık geçerli "cached miss" sayılmaz — eski negative cache
	# kayıtları yeni semantik altında stale; bir kez bypass edilirse cache'den
	# silinecek (aşağıdaki delete_value).
	if cached:
		return cached
	if cached == "":
		# Eski negative cache temizliği — bu bir kez tetiklenir, sonra fresh
		frappe.cache().delete_value(cache_key)

	profile = (
		# FAZ 1.5: sub-user → tradehub_tenant linki üzerinden Owner'ın mağazası
		frappe.db.get_value("User", user, "tradehub_tenant")
		or frappe.db.get_value("Admin Seller Profile", {"user": user, "status": "Active"}, "name")
		or frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
		or frappe.db.get_value("Admin Seller Profile", {"email": user}, "name")
	)

	# Positive-only cache: sadece gerçek bir değer varsa yaz
	if profile:
		frappe.cache().set_value(cache_key, profile, expires_in_sec=300)
	return profile


def get_current_seller_profile() -> str | None:
	"""Mevcut session user'ın seller_profile name'i — public API."""
	return _get_seller_profile_for_user(frappe.session.user)


def _doctype_has_seller_field(doctype: str) -> bool:
	"""DocType'ın `seller_profile` veya `seller` field'ı var mı (cache'li)."""
	cache_key = f"tradehub:doctype_seller_field:{doctype}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached == "yes"

	try:
		meta = frappe.get_meta(doctype)
		has_field = meta.has_field("seller_profile") or meta.has_field("seller")
	except Exception:
		has_field = False

	frappe.cache().set_value(cache_key, "yes" if has_field else "no", expires_in_sec=86400)
	return has_field


def _resolve_seller_field_name(doctype: str) -> str | None:
	"""DocType'da seller field adı — 'seller_profile' veya 'seller', yoksa None."""
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return None

	if meta.has_field("seller_profile"):
		return "seller_profile"
	if meta.has_field("seller"):
		return "seller"
	return None


def enforce_seller_isolation_on_insert(doc, method=None):
	"""before_insert hook — seller_profile field'ını set + cross-seller koru.

	Davranış:
	  - DocType TENANT_EXEMPT_DOCTYPES içindeyse → skip
	  - DocType'ın seller_profile/seller field'ı yoksa → skip
	  - User System Manager ise → field doluysa olduğu gibi bırak, boşsa
	    autoset YAPMA (Sistem manager farklı satıcı için doc oluşturuyor olabilir)
	  - User'ın seller profile'ı yoksa (örn. Marketplace Admin, Buyer):
	    - Field boşsa boş bırak (admin yazıyor)
	    - Field doluysa olduğu gibi bırak
	  - User'ın seller profile'ı varsa:
	    - Field boşsa → kendi profile'ını set et
	    - Field başka satıcı ise → frappe.PermissionError fırlat

	Args:
	    doc: Frappe document (insert sırasında)
	    method: Frappe doc_event method adı (kullanılmıyor, signature uyumu)
	"""
	if doc.doctype in TENANT_EXEMPT_DOCTYPES:
		return

	field_name = _resolve_seller_field_name(doc.doctype)
	if not field_name:
		return

	user = frappe.session.user
	# System Manager / Administrator için autoset yok — explicit veri girer.
	if "System Manager" in frappe.get_roles(user) or user == "Administrator":
		return

	current_value = doc.get(field_name)
	user_seller = _get_seller_profile_for_user(user)

	# User'ın seller'ı yoksa (admin, buyer, guest) — field'a dokunma.
	if not user_seller:
		return

	# Field boşsa autoset.
	if not current_value:
		doc.set(field_name, user_seller)
		return

	# Field başka satıcıya işaret ediyorsa reddet (cross-tenant attempt).
	if current_value != user_seller:
		# FAZ 1.4 — HIGH severity audit log (saldırı potansiyeli)
		try:
			from tradehub_core.audit import (
				DECISION_DENY,
				LAYER_L1,
				SEVERITY_HIGH,
				log_decision,
			)

			log_decision(
				action=f"{doc.doctype.lower().replace(' ', '_')}.cross_tenant_attempt",
				decision=DECISION_DENY,
				rule_id="tenant.isolation.cross_tenant_attempt",
				layer=LAYER_L1,
				object_doctype=doc.doctype,
				tenant=user_seller,
				severity=SEVERITY_HIGH,
				context={
					"attempted_tenant": current_value,
					"actor_tenant": user_seller,
				},
			)
		except Exception:
			pass

		frappe.throw(
			_("{0} kaydı başka bir satıcıya ({1}) aitmiş gibi oluşturulamaz.").format(
				doc.doctype, current_value
			),
			frappe.PermissionError,
		)


def validate_seller_isolation_on_save(doc, method=None):
	"""validate hook — mevcut kaydın seller_profile değişikliğini engelle.

	Davranış:
	  - DocType TENANT_EXEMPT_DOCTYPES içindeyse → skip
	  - DocType'ın seller_profile/seller field'ı yoksa → skip
	  - User System Manager ise → skip (admin değiştirebilir)
	  - Doc yeni ise → enforce_seller_isolation_on_insert ilgileniyor, skip
	  - Doc mevcut ise ve seller_profile değişmişse → frappe.PermissionError

	Args:
	    doc: Frappe document
	    method: Frappe doc_event method adı
	"""
	if doc.doctype in TENANT_EXEMPT_DOCTYPES:
		return

	field_name = _resolve_seller_field_name(doc.doctype)
	if not field_name:
		return

	user = frappe.session.user
	if "System Manager" in frappe.get_roles(user) or user == "Administrator":
		return

	# Yeni doc — insert hook ilgileniyor.
	if doc.is_new():
		return

	# Mevcut değer DB'den (önce-save snapshot) — değişmiş mi?
	try:
		db_value = frappe.db.get_value(doc.doctype, doc.name, field_name)
	except Exception:
		return

	if not db_value:
		return

	current_value = doc.get(field_name)
	if current_value != db_value:
		frappe.throw(
			_("{0}.{1} alanı kaydedildikten sonra değiştirilemez (tenant izolasyonu).").format(
				doc.doctype, field_name
			),
			frappe.PermissionError,
		)


def clear_seller_cache_for_user(user: str) -> None:
	"""User için seller_profile cache'ini invalidate et.

	Çağrı zamanı: Admin Seller Profile.after_insert/on_update, rol değişimi.
	"""
	if not user:
		return
	frappe.cache().delete_value(f"tradehub:seller_for_user:{user}")


# ---------------------------------------------------------------------------
# Legacy API — geriye dönük uyumluluk
# ---------------------------------------------------------------------------
# Aşağıdaki fonksiyonlar eskiden `Tenant` DocType'ına referans veriyordu;
# o DocType bu repo'da hiç oluşturulmamıştı. Yeni kod bunları kullanmamalı,
# `get_current_seller_profile()` ve `_get_seller_profile_for_user()` tercih
# edilmeli. Geriye dönük import'lar kırılmasın diye thin alias'lar bırakıldı.


def get_current_tenant() -> str | None:
	"""DEPRECATED: get_current_seller_profile() kullan.

	Eski API ile uyumluluk için seller_profile döner.
	"""
	return get_current_seller_profile()


def set_tenant(tenant_name: str | None) -> None:
	"""DEPRECATED: Tenant DocType yok; bu fonksiyon no-op'tur.

	Önceki sürümlerde "Tenant" DocType'ı için context set ediyordu; o doctype
	hiç oluşturulmadı. Tenant kavramı artık Admin Seller Profile ile özdeş ve
	kullanıcıya bağlı olarak `get_current_seller_profile()` üzerinden çözülür.
	"""
	# No-op. Çağıranlara hata vermek yerine sessizce skip — eski kod kırılmasın.
	pass


def clear_tenant_cache() -> None:
	"""DEPRECATED: User-spesifik cache invalidation için clear_seller_cache_for_user kullan."""
	# Eski API: tüm session cache'i temizliyordu. Yeni davranış: current user
	# için seller cache'ini temizle.
	user = frappe.session.user if hasattr(frappe, "session") else None
	if user:
		clear_seller_cache_for_user(user)


def get_tenant_users(tenant_name: str | None) -> list[str]:
	"""Verilen seller_profile'a bağlı User listesi (legacy)."""
	if not tenant_name:
		return []

	cache_key = f"tradehub:seller_users:{tenant_name}"
	users = frappe.cache().get_value(cache_key)
	if users is not None:
		return users

	# Admin Seller Profile'ın owner user'ı
	owner = frappe.db.get_value("Admin Seller Profile", tenant_name, "user")
	users = [owner] if owner else []

	frappe.cache().set_value(cache_key, users, expires_in_sec=3600)
	return users


def is_tenant_admin(user: str | None = None, tenant: str | None = None) -> bool:
	"""User, verilen tenant (= seller_profile) için admin mi?

	Kurallar:
	  - System Manager / Marketplace Admin → tüm seller'lara admin
	  - User'ın seller profile'ı verilen tenant'a eşitse → admin
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False

	roles = set(frappe.get_roles(user))
	if "System Manager" in roles or "Marketplace Admin" in roles:
		return True

	tenant = tenant or get_current_seller_profile()
	if not tenant:
		return False

	user_seller = _get_seller_profile_for_user(user)
	return user_seller == tenant


# ---------------------------------------------------------------------------
# Internal — permissions.py ile uyum
# ---------------------------------------------------------------------------
# permissions.py modülü `_has_tenant_field` import etmeye çalışabilir.
# Geriye dönük uyumluluk için alias bırakıyoruz.


def _has_tenant_field(doctype: str) -> bool:
	"""DEPRECATED: _doctype_has_seller_field kullan."""
	return _doctype_has_seller_field(doctype)


def validate_tenant(doc, method=None):
	"""DEPRECATED: validate_seller_isolation_on_save kullan.

	Eski hook adı için thin wrapper.
	"""
	return validate_seller_isolation_on_save(doc, method)

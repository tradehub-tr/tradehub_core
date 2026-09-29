"""İzin sözleşmeleri (14.3) — mağaza (store) izolasyonu, MOGEM-648 §1.4 ile aynı kural.

Dört yüzey, tek karar:
- **Liste:** `permission_query_conditions` → satıcı yalnız kendi `store`'unu görür; `store` boş
  (platform geneli) kayıtlar yalnız SEO Manager/System Manager'a.
- **Doğrudan kayıt:** `has_permission` aynı kuralı tekil kayda uygular.
- **API:** whitelisted uçlar `require_store_access(store)` çağırır.
- **Dosya / arka plan işi:** işler `store` alanını açıkça taşır; sistem kullanıcısı olarak koşan
  iş bile `store` dışına yazamaz (`SEO Sync Job.store` zorunlu; bkz. core/queue).
"""

from __future__ import annotations

import frappe
from frappe import _

ADMIN_ROLES = {"System Manager", "SEO Manager"}


def _is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(ADMIN_ROLES & set(frappe.get_roles(user)))


def store_of(user: str | None = None) -> str | None:
	"""Kullanıcının mağazası — tradehub tenant çözücüsüyle aynı kaynak (owner + sub-user)."""
	from tradehub_core.utils.tenant import _get_seller_profile_for_user

	return _get_seller_profile_for_user(user or frappe.session.user)


def store_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if _is_admin(user):
		return ""
	store = store_of(user)
	if not store:
		return "1=0"
	# Hangi DocType için çağrıldığı hooks'ta belli; Frappe koşulu tablo adıyla bekler.
	dt = frappe.local.flags.get("seo_helper_perm_doctype") or ""
	col = f"`tab{dt}`.store" if dt else "store"
	return f"{col} = {frappe.db.escape(store)}"


def store_has_permission(doc, ptype: str, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if _is_admin(user):
		return True
	store = store_of(user)
	doc_store = doc.get("store") if isinstance(doc, dict) else getattr(doc, "store", None)
	if not store or doc_store != store:
		return False
	# MCP kayıtlarını satıcı yalnız okur; yazma sistem/ajan yolundan
	if getattr(doc, "doctype", "") in ("MCP Tool Call", "MCP Client") and ptype != "read":
		return False
	return True


def require_store_access(store: str | None, ptype: str = "read") -> str:
	"""API kapısı: verilen mağazaya oturumun hakkı var mı; yoksa PermissionError. Döner: etkin store."""
	if _is_admin():
		return store or ""
	own = store_of()
	if not own:
		frappe.throw(_("Bu işlem için bir mağazaya bağlı olmalısınız"), frappe.PermissionError)
	if not store and ptype != "read":
		frappe.throw(_("Platform (mağazasız) kaydına yalnız SEO Manager yazabilir"), frappe.PermissionError)
	if store and store != own:
		frappe.throw(_("Başka mağazanın kaydına erişilemez"), frappe.PermissionError)
	return own


def get_doc_or_deny(doctype: str, name):
	"""Kayıt yoksa yönetici 404 alır, diğer herkes 403 — var/yok bilgisi mağaza dışına sızmasın
	(rol matrisi 25 Eyl 2026: satıcı `rotate_key(client="yok")` ile 404 alıyordu)."""
	if not name or not frappe.db.exists(doctype, name):
		if _is_admin():
			frappe.throw(_("{0} {1} bulunamadı").format(_(doctype), name), frappe.DoesNotExistError)
		frappe.throw(_("Bu kayda erişilemez"), frappe.PermissionError)
	return frappe.get_doc(doctype, name)

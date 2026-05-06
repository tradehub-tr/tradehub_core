"""CRM frontend yardımcı API override'ları.

Frappe CRM app'inin `crm.api.session.get_users` endpoint'i, default davranışta
sitedeki tüm aktif User kayıtlarını döner. Multi-tenant marketplace'de bu,
satıcıların admin/diğer satıcı personelini görmesine yol açar (sızıntı).

Faz 1 ("şimdilik atama yok — satıcı kendi kaydını yönetir") için override:
  - Administrator + System Manager + Marketplace Admin + Sales* → tüm aktif
    System User listesi (admin panel kullanım senaryosu).
  - Marketplace Seller / Seller / diğer roller → sadece kendisi.

Ek olarak Contact CRUD'u: Frappe `/api/resource/Contact` PUT'u child table'ları
(email_ids, phone_nos) güvenilir şekilde güncellemiyor. Aşağıdaki whitelisted
method'lar üst düzey alanları + child table'ları doğru şekilde senkronlar.
"""

import frappe

from tradehub_core.permissions import (
	_CRM_FULL_ACCESS_ROLES,
	_get_seller_profile_name,
)


_USER_FIELDS = ("name", "email", "full_name", "user_image")
_ORG_FIELDS = ("name", "organization_name", "industry", "territory", "no_of_employees")

# Contact üzerinde frontend'in yazmasına izin verilen üst düzey alanlar.
# system fields (owner, name, creation, modified...) ve child table'lar hariç.
_CONTACT_ALLOWED_FIELDS = {
	"first_name",
	"last_name",
	"middle_name",
	"full_name",
	"company_name",
	"designation",
	"department",
	"gender",
	"image",
	"is_primary_contact",
	"is_billing_contact",
	"address",
	"sync_with_google_contacts",
	"google_contacts",
}


@frappe.whitelist()
def get_users():
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(frappe._("Yetki gerekli"))

	roles = set(frappe.get_roles(user))
	if user == "Administrator" or (roles & _CRM_FULL_ACCESS_ROLES):
		return frappe.get_all(
			"User",
			filters={"enabled": 1, "user_type": "System User"},
			fields=list(_USER_FIELDS),
			limit_page_length=500,
			order_by="full_name asc",
		)

	# Marketplace Seller (ve atanmamış roller) — yalnızca kendisini gör
	me = frappe.db.get_value("User", user, list(_USER_FIELDS), as_dict=True)
	return [me] if me else []


_CRM_COUNTABLE_DOCTYPES = frozenset(
	{
		"CRM Lead",
		"CRM Deal",
		"CRM Organization",
		"CRM Task",
		"CRM Call Log",
		"FCRM Note",
		"Contact",
	}
)


@frappe.whitelist()
def crm_get_count(doctype: str, filters=None):
	"""Permission-aware count — Frappe `frappe.client.get_count` fonksiyonu
	`permission_query_conditions` hook'unu uygulamadığı için multi-tenant'ta
	yanıltıcı sayılar verir (tüm tenant kayıtlarını sayar). Bu endpoint
	`frappe.get_list` üzerinden permission filtresi uygulayarak sayar.
	"""
	if doctype not in _CRM_COUNTABLE_DOCTYPES:
		frappe.throw(frappe._("Bu doctype için count desteklenmez"))

	if isinstance(filters, str):
		import json

		filters = json.loads(filters)

	rows = frappe.get_list(
		doctype,
		filters=filters or [],
		pluck="name",
		limit_page_length=0,  # 0 = no limit; permission_query yine devrede
	)
	return len(rows)


@frappe.whitelist()
def get_organizations():
	"""Override of crm.api.session.get_organizations — kişisel scope.

	Dropdown UX'i: Her kullanıcı yalnızca **kendi oluşturduğu** CRM Organization
	kayıtlarını seçenek olarak görür (rolden bağımsız). Admin tüm tenant'lara
	yine `permission_query_conditions` üzerinden Desk/getList ile erişebilir;
	bu endpoint sadece Yeni Anlaşma drawer'ı gibi UI'lara servis eder.

	Administrator özel durumu — Frappe'de `owner=Administrator` kayıtların
	çoğu seed/import sırasında oluşturulduğu için Administrator session'da
	tüm kayıtlar dönülür (yönetici tam görüş).
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(frappe._("Yetki gerekli"))

	if user == "Administrator":
		return frappe.get_all(
			"CRM Organization",
			fields=list(_ORG_FIELDS),
			order_by="organization_name asc",
			limit_page_length=1000,
		)

	return frappe.get_all(
		"CRM Organization",
		filters={"owner": user},
		fields=list(_ORG_FIELDS),
		order_by="organization_name asc",
		limit_page_length=1000,
	)


def _apply_contact_fields(doc, data: dict):
	"""Frontend payload'ını Contact dokümanına uygula (yalnız izinli alanlar)."""
	for key, value in (data or {}).items():
		if key in _CONTACT_ALLOWED_FIELDS:
			doc.set(key, value)

	# email_ids — child table; tamamen değiştir
	if "email_ids" in data:
		doc.set("email_ids", [])
		for row in data.get("email_ids") or []:
			doc.append(
				"email_ids",
				{
					"email_id": row.get("email_id"),
					"is_primary": 1 if row.get("is_primary") else 0,
				},
			)

	# phone_nos — child table; tamamen değiştir
	if "phone_nos" in data:
		doc.set("phone_nos", [])
		for row in data.get("phone_nos") or []:
			doc.append(
				"phone_nos",
				{
					"phone": row.get("phone"),
					"is_primary_phone": 1 if row.get("is_primary_phone") else 0,
					"is_primary_mobile_no": 1 if row.get("is_primary_mobile_no") else 0,
				},
			)


@frappe.whitelist()
def save_contact(name=None, data=None):
	"""Contact create/update — flat email/telefon yerine child table'ları senkronlar.

	name boşsa yeni kayıt oluşturulur, doluysa mevcut kayıt güncellenir.
	`data` JSON string ya da dict olabilir (frappe whitelist transport quirk'i).
	Permission_query_conditions ve has_permission hook'ları yine geçerli.
	"""
	if isinstance(data, str):
		import json

		data = json.loads(data)
	data = data or {}

	if name:
		doc = frappe.get_doc("Contact", name)
		_apply_contact_fields(doc, data)
		doc.save()
	else:
		doc = frappe.new_doc("Contact")
		_apply_contact_fields(doc, data)
		doc.insert()
	return doc.as_dict()

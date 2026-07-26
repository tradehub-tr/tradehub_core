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

from tradehub_core.api._pagination import normalize_offset
from tradehub_core.permissions import (
	_CRM_FULL_ACCESS_ROLES,
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

# Kanban kartları için bilinçli dar alan setleri. Özellikle Lead e-posta/telefonu
# burada taşınmaz; kartın detay görünümü mevcut izinli detail endpoint'inden alınır.
_CRM_KANBAN_CONFIG = {
	"CRM Lead": {
		"fields": (
			"name",
			"lead_name",
			"first_name",
			"last_name",
			"organization",
			"status",
			"lead_owner",
			"modified",
			"creation",
		),
		"status_field": "status",
	},
	"CRM Deal": {
		"fields": (
			"name",
			"organization",
			"deal_owner",
			"status",
			"currency",
			"deal_value",
			"expected_deal_value",
			"modified",
			"creation",
		),
		"status_field": "status",
	},
	"CRM Task": {
		"fields": (
			"name",
			"title",
			"status",
			"priority",
			"due_date",
			"assigned_to",
			"reference_doctype",
			"reference_docname",
			"modified",
			"creation",
		),
		"status_field": "status",
	},
}

_CRM_KANBAN_ORDER_BY = {
	"modified desc": ("modified desc, name desc", "modified"),
	"modified asc": ("modified asc, name asc", "modified"),
	"creation desc": ("creation desc, name desc", "creation"),
	"creation asc": ("creation asc, name asc", "creation"),
}


def _parse_kanban_filters(filters):
	"""Whitelisted transport'tan gelen filtreleri güvenli bir listeye çevir."""
	if isinstance(filters, str):
		import json

		try:
			filters = json.loads(filters)
		except (TypeError, ValueError):
			filters = []
	return list(filters) if isinstance(filters, (list, tuple)) else []


@frappe.whitelist()
def crm_get_kanban_page(
	doctype: str,
	status=None,
	filters=None,
	limit_page_length=50,
	limit_start=0,
	order_by: str = "modified desc",
) -> dict:
	"""CRM Kanban için izinli, status-bazlı ve sayfalı kart okuması.

	`frappe.get_list` kasıtlı olarak kullanılır: tenant permission query
	conditions burada uygulanır. İstemci sıralama SQL'i gönderemez; izinli dört
	stabil sıralamadan biri seçilir ve `name` deterministik tie-breaker olur.

	Bu endpoint kart yüklemek içindir. `order_token`, aktif okuma sırasının
	anchor'ıdır; kalıcı drag-reorder değildir. Bunun için önce ayrı bir kanonik
	rank alanı ve transaction'lı yazma endpoint'i gerekir.
	"""
	config = _CRM_KANBAN_CONFIG.get(doctype)
	if not config:
		frappe.throw(frappe._("Bu doctype için Kanban desteklenmez"))

	start, length = normalize_offset(
		limit_start, limit_page_length, default_length=50, max_length=100
	)
	stable_order_by, token_field = _CRM_KANBAN_ORDER_BY.get(
		str(order_by or "").strip().lower(), _CRM_KANBAN_ORDER_BY["modified desc"]
	)
	query_filters = _parse_kanban_filters(filters)
	status_field = config["status_field"]
	if status not in (None, ""):
		# Status filtresi endpoint sahipliğindedir; istemci filtreleri ile
		# çelişse bile kolona ait sonuç seti değişmez.
		query_filters = [
			item
			for item in query_filters
			if not (isinstance(item, (list, tuple)) and item and item[0] == status_field)
		]
		query_filters.append([status_field, "=", status])

	# db.count permission_query_conditions'i garanti etmez. get_list hem count
	# hem kart sorgusunda aynı hook'u çalıştırır.
	total = len(
		frappe.get_list(
			doctype,
			filters=query_filters,
			pluck="name",
			limit_page_length=0,
		)
	)
	items = frappe.get_list(
		doctype,
		filters=query_filters,
		fields=list(config["fields"]),
		order_by=stable_order_by,
		start=start,
		page_length=length,
	)
	for item in items:
		item["order_token"] = f"{item.get(token_field) or ''}|{item['name']}"

	next_offset = start + length if total > start + length else None
	return {
		"items": items,
		"total": total,
		"has_more": next_offset is not None,
		"next_offset": next_offset,
		"status_field": status_field,
		"order_by": stable_order_by,
		"drag_contract": {
			"id_field": "name",
			"status_field": status_field,
			"order_token_field": "order_token",
			"reorder_supported": False,
		},
	}


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


# ───────────────────────────────────────────────────────────────────────────
# Sprint 5 Faz 2 — Maskeleme uygulayan CRM list endpoint'leri
# ───────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def crm_list_contacts(
	filters=None,
	fields=None,
	order_by: str = "modified desc",
	limit_page_length=20,
	limit_start=0,
) -> list[dict]:
	"""Maskeli Contact listesi — frappe.get_list + apply_list_masking.

	on_load hook list endpoint'lerinde tetiklenmediği için bu wrapper
	view.customer_pii capability'si olmayan kullanıcıya phone/email'ı
	maskelenmiş halde döner.

	Frontend `api.callMethodGET("...crm_list_contacts", { ... })` ile çağırır.
	"""
	import json as _json

	# Args parse — frappe whitelist transport quirk
	if isinstance(filters, str):
		try:
			filters = _json.loads(filters)
		except (ValueError, TypeError):
			filters = []
	if isinstance(fields, str):
		try:
			fields = _json.loads(fields)
		except (ValueError, TypeError):
			fields = None

	if not fields:
		fields = [
			"name",
			"full_name",
			"first_name",
			"last_name",
			"email_id",
			"phone",
			"mobile_no",
			"company_name",
			"designation",
			"modified",
			"image",
			"owner",  # apply_list_masking owner kontrolü için
		]
	# owner field'ı mutlaka dahil olsun (mask helper buna bakar)
	if "owner" not in fields:
		fields = list(fields) + ["owner"]

	rows = frappe.get_list(
		"Contact",
		filters=filters or [],
		fields=fields,
		order_by=order_by,
		start=int(limit_start or 0),
		page_length=int(limit_page_length or 20),
	)

	from tradehub_core.api.v1.crm_masking import apply_list_masking

	return apply_list_masking(rows, "Contact")

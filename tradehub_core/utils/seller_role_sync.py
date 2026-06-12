"""
Admin Seller Profile ↔ User rol senkronizasyonu.

Amaç: bir user'ın aktif Admin Seller Profile'ı olduğu sürece `Marketplace Seller`
rolüne sahip olması — onboarding adımı, manual oluşturma, import patch'i,
hangisi olursa olsun. Profil askıya alınınca rol kaldırılır.

Bu rol Frappe role-level DocPerm tarafında CRM Deal/Lead/Contact/Org/Task/Note/
Call Log doctype'ları için create/read/write izni veriyor (bkz.
`patches/grant_seller_crm_permissions.py`). Permission query layer
(`permissions._is_marketplace_seller`) ayrıca `seller` field'ı ile satır-bazlı
izolasyon uyguluyor — yani rol verilen user yalnızca kendi mağazasının
kayıtlarını görür.

Hook bağlama (hooks.py):
    doc_events["Admin Seller Profile"] = {
        "after_insert": "tradehub_core.utils.seller_role_sync.sync_marketplace_seller_role",
        "on_update": "tradehub_core.utils.seller_role_sync.sync_marketplace_seller_role",
    }
"""

import frappe

ROLE = "Marketplace Seller"
ACTIVE_STATUSES = {"Active"}


def sync_marketplace_seller_role(doc, method=None):
	"""Admin Seller Profile.user için Marketplace Seller rolünü aktif/pasif et.

	- status ∈ ACTIVE_STATUSES ve user mevcut → rol ekle (yoksa)
	- aksi halde → rol kaldır (varsa)

	Idempotent. Rol kayıtlı değilse veya user kaydı yoksa sessizce skip.
	"""
	user = getattr(doc, "user", None) if not isinstance(doc, dict) else doc.get("user")
	if not user or user in ("Guest", "Administrator"):
		return

	# Satıcı KENDİ profilini kaydediyorsa rol senkronunu çalıştırma. _add_role,
	# desk_access=1 olan "Marketplace Seller"ı eklerken user_type'ı geçici olarak
	# System→Website User'a çalkalıyor; bu canlı oturumun (panel = desk route)
	# auth state'ini bozuyor → sonraki istekte init_request 417 → satıcı logout
	# olur. Sahip zaten kendi profilini düzenleyebildiği için bu request'te rol
	# senkronuna ihtiyaç yok; admin'in başka satıcıyı güncellediği yol (session
	# user != doc.user) sağlam kalır.
	if user == frappe.session.user:
		return

	# User henüz commit'lenmemiş olabilir — exists kontrolü
	if not frappe.db.exists("User", user):
		return

	# Rol sistemde tanımlı mı
	if not frappe.db.exists("Role", ROLE):
		return

	status = getattr(doc, "status", None) if not isinstance(doc, dict) else doc.get("status")
	should_have = status in ACTIVE_STATUSES

	current_roles = set(frappe.get_roles(user))
	has_role = ROLE in current_roles

	if should_have and not has_role:
		_add_role(user, ROLE)
	elif not should_have and has_role:
		# Sadece bu kullanıcının BAŞKA aktif profile'ı yoksa kaldır.
		# Aksi halde aynı user birden fazla profile sahibi (nadir ama mümkün)
		# kayıtlarına erişimi kaybeder.
		other_active = frappe.db.exists(
			"Admin Seller Profile",
			{
				"user": user,
				"status": ("in", list(ACTIVE_STATUSES)),
				"name": ("!=", doc.name if hasattr(doc, "name") else doc.get("name")),
			},
		)
		if not other_active:
			_remove_role(user, ROLE)


def _add_role(user: str, role: str) -> None:
	user_doc = frappe.get_doc("User", user)
	user_doc.add_roles(role)

	# 2026-05-11 REVERT: System User mimarisinin Frappe v15'te init_request
	# 417 edge case'leri çözülemedi. Eski stabil Website User mimarisine dönüldü.
	# add_roles bazı rolleri (desk_access=1) eklerken user_type'ı System User'a
	# yükseltir; defansif geri çek.
	frappe.db.sql(
		"UPDATE `tabUser` SET `user_type`='Website User' WHERE `name`=%s AND `user_type`='System User'",
		(user,),
	)
	frappe.db.sql(
		"DELETE FROM `tabHas Role` WHERE `parent`=%s AND `role`='Desk User' AND `parenttype`='User'",
		(user,),
	)


def _remove_role(user: str, role: str) -> None:
	user_doc = frappe.get_doc("User", user)
	user_doc.remove_roles(role)

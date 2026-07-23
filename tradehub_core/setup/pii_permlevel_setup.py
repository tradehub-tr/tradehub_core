"""Sprint 5 Faz 3 — Frappe Desk PII koruması.

`on_load` hook ve `apply_list_masking` Vue panel için çalışıyor, ama
Frappe Desk (UI veya `/api/resource` raw) generic REST kullanır → bizim
hook'lar tetiklenmez.

Bu modül Frappe'nin built-in **permlevel** mekanizmasını kullanarak DocType
JSON'una dokunmadan:
  1. Hassas field'ları `permlevel: 1` yapar (Property Setter)
  2. Sadece privileged role'lere Custom DocPerm ile `permlevel: 1, read: 1`
     verir; diğer roller bu field'ları okuyamaz, görmez.

Privileged role tanımı:
  - Frappe Desk üst yönetim erişimi olan roller
  - Capability sistemimizden bağımsız (Frappe rol bazlı)

İdempotent — patch tekrar tekrar çalıştırılabilir.
"""

from __future__ import annotations

import frappe

# DocType → field listesi (permlevel 1'e çekilecekler)
_PII_FIELDS_BY_DOCTYPE: dict[str, list[str]] = {
	"Admin Seller Profile": ["iban", "bank_name", "account_holder", "tax_id"],
	"User Profile": ["iban", "bank_name", "account_holder_name", "tax_id"],
	"Contact": ["email_id", "phone", "mobile_no"],
}

# Privileged role'ler — permlevel 1 read=1, sadece bunlar Desk'te PII görür
_PRIVILEGED_ROLES_READ: list[str] = [
	"Seller Owner",
	"Seller Co-Owner",
	"Compliance Officer",
	"System Manager",
	"Marketplace Admin",
]

# Write izni daha kısıtlı — sadece Owner ve System Manager
_PRIVILEGED_ROLES_WRITE: list[str] = [
	"Seller Owner",
	"System Manager",
]


def _create_property_setter(doctype: str, fieldname: str, permlevel: int) -> bool:
	"""DocField için permlevel Property Setter ekle veya güncelle (idempotent upsert).

	Returns:
	    True: yeni Property Setter oluşturuldu veya value güncellendi
	    False: değişiklik yok (zaten doğru değer) veya field bulunamadı
	"""
	# Field gerçekten var mı (DocField table'ında)
	if not frappe.db.exists("DocField", {"parent": doctype, "fieldname": fieldname}):
		return False

	ps_name = f"{doctype}-{fieldname}-permlevel"
	target_value = str(permlevel)

	if frappe.db.exists("Property Setter", ps_name):
		current = frappe.db.get_value("Property Setter", ps_name, "value")
		if current == target_value:
			return False
		frappe.db.set_value("Property Setter", ps_name, "value", target_value)
		return True

	ps = frappe.new_doc("Property Setter")
	ps.doctype_or_field = "DocField"
	ps.doc_type = doctype
	ps.field_name = fieldname
	ps.property = "permlevel"
	ps.value = target_value
	ps.property_type = "Int"
	ps.flags.ignore_permissions = True
	ps.flags.ignore_mandatory = True
	ps.insert(ignore_permissions=True)
	return True


def _ensure_custom_docperm(
	doctype: str,
	role: str,
	permlevel: int,
	read: int = 1,
	write: int = 0,
) -> bool:
	"""Custom DocPerm kaydı yarat veya güncelle (idempotent).

	Returns:
	    True: kayıt oluşturuldu veya güncellendi
	    False: zaten var ve değişiklik yok
	"""
	if not frappe.db.exists("Role", role):
		return False

	existing = frappe.db.get_value(
		"Custom DocPerm",
		{"parent": doctype, "role": role, "permlevel": permlevel},
		["name", "read", "write"],
		as_dict=True,
	)
	if existing:
		# Güncelleme gerekli mi?
		if existing.get("read") == read and existing.get("write") == write:
			return False
		frappe.db.set_value(
			"Custom DocPerm",
			existing["name"],
			{"read": read, "write": write},
		)
		return True

	# Yeni kayıt
	# Custom DocPerm parent kaydı DocType. Aşağıdaki insert pattern Frappe
	# permissions modülünde de kullanılıyor.
	doc = frappe.new_doc("Custom DocPerm")
	doc.parent = doctype
	doc.parenttype = "DocType"
	doc.parentfield = "permissions"
	doc.role = role
	doc.permlevel = permlevel
	doc.read = read
	doc.write = write
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return True


def revoke_non_privileged_permlevel_reads(target_permlevel: int = 2) -> dict:
	"""PII permlevel'inde non-privileged role'lerin read/write izinlerini sıfırla.

	Frappe DocType migrate / DocType save side-effect olarak DocType
	permissions tablosundaki "Seller", "Marketplace Seller" gibi non-privileged
	role'lere otomatik permlevel 1+ izinleri ekleyebilir. Bu yardımcı, bizim
	privileged listemizde olmayan role'lerin permlevel target_permlevel
	üzerindeki read/write izinlerini 0'a çeker.

	Custom DocPerm tek doğruluk kaynağı; aynı (parent, role, permlevel) için
	read=0/write=0 set edilirse Frappe Desk'te o field'lar görünmez.
	"""
	all_privileged = set(_PRIVILEGED_ROLES_READ) | set(_PRIVILEGED_ROLES_WRITE)
	revoked = 0
	for doctype in _PII_FIELDS_BY_DOCTYPE.keys():
		rows = frappe.get_all(
			"Custom DocPerm",
			filters={"parent": doctype, "permlevel": target_permlevel},
			fields=["name", "role", "read", "write"],
		)
		for r in rows:
			if r["role"] in all_privileged:
				continue
			if r["read"] == 0 and r["write"] == 0:
				continue
			frappe.db.set_value("Custom DocPerm", r["name"], {"read": 0, "write": 0})
			revoked += 1
	frappe.db.commit()
	try:
		frappe.clear_cache()
	except Exception:
		frappe.log_error("Cache clear failed after revoking non-privileged permlevel reads", "pii_permlevel_setup")
		pass
	return {"non_privileged_revoked": revoked, "target_permlevel": target_permlevel}


def apply_pii_permlevels(dry_run: bool = False, target_permlevel: int = 2) -> dict:
	"""Tüm PII field'larını belirtilen permlevel'e çek + privileged role'lere
	read ver.

	target_permlevel=2 önerilen değer — DocType default permission'larında
	"Seller" ve "Marketplace Seller" için permlevel 1 read=1 zaten tanımlı
	olduğundan permlevel 1 sub-user'ı engellemez. permlevel 2 ile temiz
	isolation sağlanır.

	Args:
	    dry_run: True ise yalnızca raporlar, değişiklik yapmaz.
	    target_permlevel: PII field'ları için hedef permlevel (default 2).

	Returns:
	    {
	      "property_setters_created": int,  # yarat veya update
	      "docperms_created": int,           # yarat veya update
	      "target_permlevel": int,
	      "skipped_fields": [...],
	      "skipped_roles": [...],
	    }
	"""
	property_setters_created = 0
	docperms_created = 0
	skipped_fields: list[str] = []
	skipped_roles: list[str] = []

	for doctype, fields in _PII_FIELDS_BY_DOCTYPE.items():
		if not frappe.db.exists("DocType", doctype):
			skipped_fields.append(f"{doctype}(DocType yok)")
			continue

		# Custom DocPerm standart DocPerm'i TAMAMEN ezer. permlevel 1+ Custom
		# DocPerm eklemeden önce permlevel-0 taban izinlerini JSON'dan kopyala,
		# yoksa taban `read` düşer (KYB/KYC'de yaşanan 403 hatası). Idempotent.
		if not dry_run:
			from frappe.permissions import setup_custom_perms

			setup_custom_perms(doctype)

		# 1) Field'ları hedef permlevel'e yükselt
		for fieldname in fields:
			if dry_run:
				exists_field = frappe.db.exists("DocField", {"parent": doctype, "fieldname": fieldname})
				if not exists_field:
					skipped_fields.append(f"{doctype}.{fieldname}(field yok)")
				else:
					property_setters_created += 1
			else:
				if _create_property_setter(doctype, fieldname, permlevel=target_permlevel):
					property_setters_created += 1
				elif not frappe.db.exists("DocField", {"parent": doctype, "fieldname": fieldname}):
					skipped_fields.append(f"{doctype}.{fieldname}(field yok)")

		# 2) Privileged role'lere hedef permlevel read=1
		for role in _PRIVILEGED_ROLES_READ:
			if not frappe.db.exists("Role", role):
				skipped_roles.append(f"{role}(Role yok)")
				continue
			write_flag = 1 if role in _PRIVILEGED_ROLES_WRITE else 0
			if dry_run:
				existing = frappe.db.exists(
					"Custom DocPerm",
					{"parent": doctype, "role": role, "permlevel": target_permlevel},
				)
				if not existing:
					docperms_created += 1
			else:
				if _ensure_custom_docperm(doctype, role, target_permlevel, read=1, write=write_flag):
					docperms_created += 1

	if not dry_run:
		frappe.db.commit()
		# Permission cache invalidate
		try:
			frappe.clear_cache()
		except Exception:
			frappe.log_error("Cache clear failed after applying PII permlevels", "pii_permlevel_setup")
			pass

	return {
		"property_setters_created": property_setters_created,
		"docperms_created": docperms_created,
		"target_permlevel": target_permlevel,
		"skipped_fields": list(set(skipped_fields)),
		"skipped_roles": list(set(skipped_roles)),
		"dry_run": dry_run,
	}

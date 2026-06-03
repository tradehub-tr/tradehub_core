"""Sprint 5 Faz 3 düzeltme — PII permlevel'i 1'den 2'ye yükselt.

Sorun:
  v15_6_6 patch'i PII field'larını permlevel 1'e çekti. Ancak Admin Seller
  Profile, User Profile ve Contact DocType'larında default permissions
  içinde "Seller" ve "Marketplace Seller" rolleri için permlevel 1 read=1
  zaten tanımlıdır. Bu yüzden sub-user (Seller rolü taşıyor) hâlâ permlevel
  1 field'larını Frappe Desk'te görüyordu.

Çözüm:
  permlevel 2'ye geç — DocType default permissions'da permlevel 2 read tanımlı
  hiçbir rol yok. Sadece bizim eklediğimiz privileged role'ler (Seller Owner,
  Seller Co-Owner, Compliance Officer, System Manager, Marketplace Admin)
  permlevel 2 read=1 alır.

İdempotent:
  - Mevcut Property Setter'lar value=1'den value=2'ye güncellenir
  - Mevcut Custom DocPerm permlevel=1 kayıtları silinir
  - Yeni Custom DocPerm permlevel=2 kayıtları yaratılır
"""

from __future__ import annotations

import frappe


def execute() -> dict:
	# 1) v15_6_6'da yaratılan permlevel=1 Custom DocPerm kayıtlarını sil
	#    (bizim eklediklerimiz) — DocType default permissions'a dokunmayalım.
	#    Custom DocPerm tablosundan sadece bizim setup'ımızın yaratacağı
	#    permlevel 1 kayıtları temizleyelim.
	from tradehub_core.setup.pii_permlevel_setup import (
		_PII_FIELDS_BY_DOCTYPE,
		_PRIVILEGED_ROLES_READ,
		apply_pii_permlevels,
	)

	cleaned = 0
	for doctype in _PII_FIELDS_BY_DOCTYPE.keys():
		for role in _PRIVILEGED_ROLES_READ:
			existing = frappe.db.get_value(
				"Custom DocPerm",
				{"parent": doctype, "role": role, "permlevel": 1},
				"name",
			)
			if existing:
				frappe.delete_doc("Custom DocPerm", existing, ignore_permissions=True, force=1)
				cleaned += 1

	frappe.db.commit()

	# 2) Property Setter'ları permlevel 2'ye yükselt + yeni Custom DocPerm yarat
	result = apply_pii_permlevels(dry_run=False, target_permlevel=2)
	result["custom_docperms_v1_removed"] = cleaned

	return result

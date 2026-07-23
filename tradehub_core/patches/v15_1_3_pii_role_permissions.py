"""FAZ 1.3 — Role × permlevel × doctype permission matrisi.

Bu patch her permlevel için hangi rol'ün read/write yapacağını
Custom DocPerm üzerinden tanımlar (idempotent).

Mimari karar (docs/yetki/01-karar-dosyasi.md §3):
  - permlevel 0: Default (mevcut role permission'lar)
  - permlevel 1: Restricted (phone, email, adres)
  - permlevel 2: Sensitive (vergi no, IBAN)
  - permlevel 3: Critical PII (kimlik, KYC dosyaları)

Rol matrisi:
  permlevel 1 (Restricted):
    - System Manager: r/w
    - Marketplace Admin: r/w
    - Customer Service / Support Agent: r
    - Compliance Officer: r/w
    - Seller (kendi profili): r/w
    - Marketplace Seller: r/w
  permlevel 2 (Sensitive — Finance düzeyi):
    - System Manager: r/w
    - Marketplace Admin: r
    - Compliance Officer: r
    - Seller / Marketplace Seller (sadece Owner, if_owner=1): r/w
  permlevel 3 (Critical PII — Compliance Officer + Owner):
    - System Manager: r/w
    - Compliance Officer: r/w
    - Seller / Marketplace Seller (sadece Owner, if_owner=1): r

Detay: docs/yetki/01-karar-dosyasi.md §3.1, §6.1
"""

import frappe
from frappe.permissions import setup_custom_perms

# DocType'lar — PII permlevel'ı olan, role permission'larına ek satır eklenecek
_TARGET_DOCTYPES: list[str] = [
	"Admin Seller Profile",
	"User Profile",
	"KYC Verification",
	"KYB Verification",
]

# (role, permlevel, read, write, if_owner)
_PERM_MATRIX: list[tuple[str, int, int, int, int]] = [
	# === permlevel 1 — Restricted ===
	("System Manager", 1, 1, 1, 0),
	("Marketplace Admin", 1, 1, 1, 0),
	("Support Agent", 1, 1, 0, 0),
	("Compliance Officer", 1, 1, 1, 0),
	("Seller", 1, 1, 1, 1),
	("Marketplace Seller", 1, 1, 1, 1),
	# === permlevel 2 — Sensitive (vergi/banka) ===
	("System Manager", 2, 1, 1, 0),
	("Marketplace Admin", 2, 1, 0, 0),
	("Compliance Officer", 2, 1, 0, 0),
	("Seller", 2, 1, 1, 1),
	("Marketplace Seller", 2, 1, 1, 1),
	# === permlevel 3 — Critical PII (kimlik dosyaları) ===
	("System Manager", 3, 1, 1, 0),
	("Compliance Officer", 3, 1, 1, 0),
	("Seller", 3, 1, 0, 1),
	("Marketplace Seller", 3, 1, 0, 1),
]


def execute() -> None:
	"""Custom DocPerm satırlarını idempotent şekilde ekle."""
	added = 0
	updated = 0
	skipped = 0
	errors = []

	for doctype in _TARGET_DOCTYPES:
		# DocType var mı?
		if not frappe.db.exists("DocType", doctype):
			skipped += 1
			continue

		# Custom DocPerm standart DocPerm'i (DocType JSON) TAMAMEN ezer. İlk
		# Custom DocPerm satırını eklemeden önce permlevel-0 taban izinlerini
		# JSON'dan Custom DocPerm'e kopyala; yoksa permlevel 1/2/3 satırları
		# eklenince taban `read` düşer ve generic formda "does not have doctype
		# access via role permission" 403'üne yol açar. setup_custom_perms
		# idempotent — Custom DocPerm zaten varsa no-op.
		setup_custom_perms(doctype)

		for role, permlevel, read, write, if_owner in _PERM_MATRIX:
			# Role var mı?
			if not frappe.db.exists("Role", role):
				continue

			try:
				# Bu kombinasyon için mevcut DocPerm var mı?
				existing = frappe.db.exists(
					"Custom DocPerm",
					{
						"parent": doctype,
						"role": role,
						"permlevel": permlevel,
					},
				)

				if existing:
					# Güncelle (idempotent)
					perm = frappe.get_doc("Custom DocPerm", existing)
					changed = False
					if perm.read != read:
						perm.read = read
						changed = True
					if perm.write != write:
						perm.write = write
						changed = True
					if perm.if_owner != if_owner:
						perm.if_owner = if_owner
						changed = True
					if changed:
						perm.save(ignore_permissions=True)
						updated += 1
				else:
					# Yeni Custom DocPerm oluştur
					perm = frappe.get_doc(
						{
							"doctype": "Custom DocPerm",
							"parent": doctype,
							"parenttype": "DocType",
							"parentfield": "permissions",
							"role": role,
							"permlevel": permlevel,
							"read": read,
							"write": write,
							"if_owner": if_owner,
						}
					)
					perm.insert(ignore_permissions=True)
					added += 1
			except Exception as e:
				errors.append(f"{doctype}/{role}/lvl{permlevel}: {e}")
				frappe.log_error(
					f"Role permission ataması başarısız: {doctype}/{role}/lvl{permlevel}: {e}",
					"v15_1_3_pii_role_perms",
				)

	# Rapor
	frappe.logger("patches").info(
		f"FAZ 1.3 Role permission matrisi: {added} yeni, {updated} güncellendi, {skipped} doctype skip."
	)
	if errors:
		frappe.logger("patches").warning(f"FAZ 1.3 Role permission matrisi: {len(errors)} hata:")
		for err in errors[:10]:
			frappe.logger("patches").error(f"   {err}")

	frappe.db.commit()

	# Clear cache — yeni permission'lar yansısın
	frappe.clear_cache()

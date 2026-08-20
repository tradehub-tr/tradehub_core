"""T2/T3 — KYC/KYB `status` alanını başvuru sahibinin permlevel'inden ayır.

Kök neden (ölçüldü, canlı DB 2026-08-19 · docs/reports/28-faz13-pentest.md §2):
  `KYC Verification.status` ve `KYB Verification.status` permlevel-1'deydi.
  Aynı permlevel'de `Seller` ve `Marketplace Seller` rollerinin
  `write=1, if_owner=1` Custom DocPerm satırı var. Frappe'de permlevel kapısı
  (`Document.get_permlevel_access`, frappe/model/document.py:808) `if_owner`
  bayrağına HİÇ bakmaz — yalnız rol + permlevel + write üçlüsüne bakar. Yani
  satıcı rolü taşıyan bir kullanıcı, doc-seviyesi write'ı olan HER kayıtta
  (kendi kaydı) `status` yazabiliyordu. Ölçülen sonuç:
    - KYC `status=Verified` → `on_update._sync_kyc_status` → `can_buy = 1`
    - KYB `status=Verified` → `on_update._sync_verified_seller_role` →
      kullanıcı kendine **`Verified Seller`** rolünü verdi, `can_sell = 1`
  Hem `doc.save()` hem `frappe.client.set_value` yolu çalıştı.

Neden YENİ bir permlevel (4), mevcut 2 veya 3 DEĞİL:
  permlevel 1/2/3 bu depoda bir **PII hassaslık merdiveni** (Faz 1.3 karar
  dosyası: 1=Restricted, 2=Sensitive, 3=Critical PII). Ölçülen canlı satırlar:
    - permlevel 2: `Seller`/`Marketplace Seller` write=1  → hiçbir şey düzelmez.
    - permlevel 3: `Marketplace Admin` satırı HİÇ YOK (ne read ne write) →
      `status`'ü 3'e taşımak bugünkü tek gerçek inceleme rolünü kilitlerdi;
      3'e Marketplace Admin write eklemek ise ona kimlik belgelerinde
      (identity_document, imza sirküleri, ...) da write açardı — istenmeyen
      genişleme.
  `status` zaten PII değil, bir **karar alanı**. Bu yüzden ayrı bir seviye:
      permlevel 4 (Karar) — inceleme rolleri r/w, başvuru sahibi read-only.

Satır matrisi (bu patch'in yazdığı):
    System Manager      r/w   — mevcut tüm permlevel'lerde zaten r/w
    Marketplace Admin   r/w   — `review_kyb` / `review_kyc` bu rolü şart koşar
    Compliance Officer  r/w   — permlevel 1 ve 3'te bugün de write=1
    Seller              r     — kendi başvurusunun durumunu GÖRÜR, yazamaz
    Marketplace Seller  r     —  "
    Seller Owner        r     — panel generic formu (v15_8_3 meşru akışı)
    Buyer               r     — yalnız KYC'de (KYB'de permlevel-0 satırı yok)

Neden Custom DocPerm:
  Her iki doctype'ta Custom DocPerm satırı VAR (ölçüm: KYC 20, KYB 19 satır).
  Frappe'de bir doctype için Custom DocPerm bulunduğunda standart DocPerm
  (DocType JSON `permissions` listesi) TAMAMEN yok sayılır
  (frappe/model/meta.py:542). Yani JSON'a satır eklemek hiçbir şey yapmaz —
  satırlar buradan yazılmalı. `status` alanının permlevel'i ise DocField'dan
  gelir; onu DocType JSON'u taşır ve model-sync bu patch'ten ÖNCE koşar
  (patches.txt `[post_model_sync]`).

Bu patch TEK savunma DEĞİL: permlevel kapısı `flags.ignore_permissions` ile
tamamen atlanır (frappe/model/document.py:785) ve bu depoda KYC/KYB'yi
`ignore_permissions=True` ile kaydeden 5 fonksiyon / 12 çağrı noktası var
(ölçüldü: `api/v1/kyc.py`, `api/v1/kyb.py`). Asıl kapı controller
`validate()` içindeki `permissions.guard_verification_status_change`.

İdempotent: var olan satırda yalnız farklı bayrağı yazar; yoksa oluşturur.
"""

from __future__ import annotations

import frappe

_DOCTYPES = ("KYC Verification", "KYB Verification")
_PERMLEVEL = 4

# role -> (read, write). Buyer yalnız KYC'de anlamlı; KYB'de permlevel-0
# satırı olmadığı için orada da yazılması zararsız ama gereksiz — aşağıda
# permlevel-0 satırı olan roller + Compliance Officer ile sınırlanıyor.
_MATRIX: dict[str, tuple[int, int]] = {
	"System Manager": (1, 1),
	"Marketplace Admin": (1, 1),
	"Compliance Officer": (1, 1),
	"Seller": (1, 0),
	"Marketplace Seller": (1, 0),
	"Seller Owner": (1, 0),
	"Buyer": (1, 0),
}

# permlevel-4 satırında AÇIK BIRAKILMAYACAK bayraklar. `status` bir karar
# alanı; buradan rapor/dışa aktarım/paylaşım hakkı doğmamalı.
_ZERO_FLAGS = (
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"report",
	"export",
	"import",
	"share",
	"print",
	"email",
	"if_owner",
)


def _roles_with_base_access(doctype: str) -> set[str]:
	"""Bu doctype'ta permlevel-0 Custom DocPerm satırı olan roller."""
	return set(
		frappe.get_all(
			"Custom DocPerm",
			filters={"parent": doctype, "permlevel": 0},
			pluck="role",
		)
	)


def execute() -> dict:
	result: dict = {}

	for doctype in _DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			result[doctype] = {"skipped": "no_doctype"}
			continue

		# Custom DocPerm yoksa standart DocPerm geçerlidir ve bu patch'in
		# yazdığı satırlar hiç okunmaz — sessiz geçmek v15_8_3'ün hatasını
		# tekrarlamak olurdu, o yüzden görünür bir kayıt bırakıyoruz.
		if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
			frappe.log_error(
				title="KYC/KYB status permlevel-4 satırı yazılamadı",
				message=(
					f"{doctype} için Custom DocPerm YOK; standart DocPerm geçerli. "
					"permlevel-4 satırları DocType JSON'una eklenmeli."
				),
			)
			result[doctype] = {"skipped": "no_custom_docperm"}
			continue

		base_roles = _roles_with_base_access(doctype)
		changed: dict = {}

		for role, (read, write) in _MATRIX.items():
			if not frappe.db.exists("Role", role):
				continue
			# Compliance Officer'ın permlevel-0 satırı yok (T4 — ayrı bulgu);
			# yine de üst permlevel satırları var, o yüzden matriste tutuluyor.
			if role not in base_roles and role != "Compliance Officer":
				continue

			name = frappe.db.exists(
				"Custom DocPerm",
				{"parent": doctype, "role": role, "permlevel": _PERMLEVEL},
			)
			wanted = {"read": read, "write": write, **{f: 0 for f in _ZERO_FLAGS}}

			if name:
				row = frappe.get_doc("Custom DocPerm", name)
				delta = {f: v for f, v in wanted.items() if int(row.get(f) or 0) != v}
				if delta:
					for f, v in delta.items():
						row.set(f, v)
					row.save(ignore_permissions=True)
					changed[role] = {"updated": delta}
			else:
				row = frappe.new_doc("Custom DocPerm")
				row.parent = doctype
				row.parenttype = "DocType"
				row.parentfield = "permissions"
				row.role = role
				row.permlevel = _PERMLEVEL
				for f, v in wanted.items():
					row.set(f, v)
				row.insert(ignore_permissions=True)
				changed[role] = {"created": wanted}

		frappe.clear_cache(doctype=doctype)
		result[doctype] = {
			"changed": changed,
			"status_permlevel": frappe.get_meta(doctype).get_field("status").permlevel,
		}

	frappe.db.commit()
	return result

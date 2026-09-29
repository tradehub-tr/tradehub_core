"""MOGEM-685 bulgu 1 — KYB AML/yaptırım işaretini satıcıdan gizle (permlevel 5).

`aml_check_status` / `sanctions_status` bu turda KYB Verification'a eklendi; admin KYB
incelemesinde işaretler, işaretli satıcı ödeme onayı / iade / bakiye çekme yetkisini kaybeder
(`utils/aml_gate.py`).

Neden YENİ permlevel (5), mevcut 0–4 DEĞİL (ölçüldü, yerel Custom DocPerm 29 Eyl 2026):
  0–3: `Seller`/`Marketplace Seller` en az read (0–2'de write) — satıcı kendi işaretini görür
       ya da kaldırır; 2'ye koyulan ilk denemede birim testi satıcının alanı gördüğünü yakaladı.
  4:   `status` karar seviyesi (v15_9_26) — satıcı read; işaret gizli kalmalı.
KYB'de Custom DocPerm VAR → DocType JSON'undaki `permissions` hiç okunmuyor
(frappe/model/meta.py), satırlar buradan yazılmalı. Alanların permlevel'ini JSON taşır;
model-sync bu patch'ten önce koşar (`[post_model_sync]`).

Satır matrisi: System Manager / Marketplace Admin / Compliance Officer r/w. Satıcı rolleri
satır ALMAZ; varsa (elle eklenmişse) read/write sıfırlanır. İkinci savunma
`permissions.guard_aml_fields_change` (validate — ignore_permissions yolları için).

İdempotent: var olan satırda yalnız farklı bayrağı yazar; yoksa oluşturur.
"""

from __future__ import annotations

import frappe

_DOCTYPE = "KYB Verification"
_PERMLEVEL = 5

_INCELEYICILER = ("System Manager", "Marketplace Admin", "Compliance Officer")
_SATICI_ROLLERI = ("Seller", "Marketplace Seller", "Seller Owner", "Buyer")

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


def _yaz(role: str, read: int, write: int, olustur: bool) -> dict | None:
	wanted = {"read": read, "write": write, **{f: 0 for f in _ZERO_FLAGS}}
	name = frappe.db.exists("Custom DocPerm", {"parent": _DOCTYPE, "role": role, "permlevel": _PERMLEVEL})
	if name:
		row = frappe.get_doc("Custom DocPerm", name)
		delta = {f: v for f, v in wanted.items() if int(row.get(f) or 0) != v}
		if not delta:
			return None
		for f, v in delta.items():
			row.set(f, v)
		row.save(ignore_permissions=True)
		return {"updated": delta}
	if not olustur:
		return None
	row = frappe.new_doc("Custom DocPerm")
	row.parent = _DOCTYPE
	row.parenttype = "DocType"
	row.parentfield = "permissions"
	row.role = role
	row.permlevel = _PERMLEVEL
	for f, v in wanted.items():
		row.set(f, v)
	row.insert(ignore_permissions=True)
	return {"created": wanted}


def execute() -> dict:
	if not frappe.db.exists("DocType", _DOCTYPE):
		return {"skipped": "no_doctype"}
	# Custom DocPerm yoksa standart DocPerm geçerli ve buraya yazılan satırlar okunmaz —
	# sessiz geçmek yerine görünür kayıt (v15_9_26 ile aynı ders).
	if not frappe.db.exists("Custom DocPerm", {"parent": _DOCTYPE}):
		frappe.log_error(
			title="KYB AML permlevel-5 satırı yazılamadı",
			message=f"{_DOCTYPE} için Custom DocPerm YOK; permlevel-5 satırları DocType JSON'una eklenmeli.",
		)
		return {"skipped": "no_custom_docperm"}

	changed: dict = {}
	for role in _INCELEYICILER:
		if frappe.db.exists("Role", role) and (sonuc := _yaz(role, 1, 1, olustur=True)):
			changed[role] = sonuc
	for role in _SATICI_ROLLERI:
		if sonuc := _yaz(role, 0, 0, olustur=False):
			changed[role] = sonuc

	frappe.clear_cache(doctype=_DOCTYPE)
	frappe.db.commit()
	return {
		"changed": changed,
		"permlevel": frappe.get_meta(_DOCTYPE).get_field("aml_check_status").permlevel,
	}

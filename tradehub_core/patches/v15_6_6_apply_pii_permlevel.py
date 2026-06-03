"""Sprint 5 Faz 3 — Frappe Desk PII koruması.

Vue panel için on_load + apply_list_masking hook'ları çalışıyor, ama Frappe
Desk generic REST kullandığı için bizim hook'ları tetiklemez. Bu patch
**Property Setter + Custom DocPerm** mekanizmasıyla DocType JSON'una
dokunmadan Frappe Desk tarafında da PII field'larını korur:

  1. Hassas field'ları permlevel 1'e çeker (Property Setter)
  2. Sadece privileged role'lere permlevel 1 read=1 verir (Custom DocPerm)
  3. Diğer roller bu field'ları Desk'te göremez

Etki:
  - Admin Seller Profile: iban, tax_id, bank_name, account_holder
  - User Profile: iban, tax_id, bank_name, account_holder_name
  - Contact: email_id, phone, mobile_no

Privileged roller (Desk'te PII görür):
  - Seller Owner, Seller Co-Owner
  - Compliance Officer
  - System Manager, Marketplace Admin

İdempotent.
"""

from __future__ import annotations


def execute() -> dict:
	from tradehub_core.setup.pii_permlevel_setup import apply_pii_permlevels

	return apply_pii_permlevels(dry_run=False)

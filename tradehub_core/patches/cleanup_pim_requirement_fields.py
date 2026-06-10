"""PIM zorunluluk/taxonomy temizliği — artık enforcement yok.

Product Type'tan `is_group` ve `required_core_fields`, Product Type Required
Attribute'tan `requirement_level` alanları DocType JSON'dan kaldırıldı. Frappe
migrate orphan kolonu otomatik düşürmediği için bu patch idempotent ALTER TABLE
DROP COLUMN ile DB kolonlarını temizler.

İdempotent: kolon yoksa no-op (unknown column hatasını yutar).
"""

import frappe

_DROP_TARGETS = (
	("tabProduct Type", "is_group"),
	("tabProduct Type", "required_core_fields"),
	("tabProduct Type Required Attribute", "requirement_level"),
)


def execute():
	for table, col in _DROP_TARGETS:
		try:
			frappe.db.sql(f"ALTER TABLE `{table}` DROP COLUMN `{col}`")
		except Exception as e:
			msg = str(e).lower()
			# 'unknown column' / "doesn't exist" / 'check that' → zaten yok, sorun değil
			if "unknown" in msg or "doesn't exist" in msg or "check that" in msg:
				continue
			frappe.log_error(
				title=f"cleanup_pim_requirement_fields: ALTER TABLE {table}.{col}",
				message=str(e),
			)

	frappe.db.commit()

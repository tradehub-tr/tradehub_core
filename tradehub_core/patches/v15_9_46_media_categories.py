"""MOGEM-579 kategori ilişkileri için DB düzeyi benzersizlik kısıtları.

Controller doğrulaması kullanıcıya anlaşılır hata verir; bu benzersiz
indeksler ise iki eşzamanlı isteğin doğrulamayı birlikte geçip aynı bağı iki
kez yazmasını engeller. 500 karakterlik URL doğrudan birleşik indekse
konulmaz; tam SHA-256 özeti kullanılır.
"""

from __future__ import annotations

import hashlib

import frappe


def _has_index(table: str, index_name: str) -> bool:
	return bool(
		frappe.db.sql(
			f"SHOW INDEX FROM `{table}` WHERE Key_name = %s",  # nosec B608 — table sabit çağrılır
			(index_name,),
		)
	)


def execute() -> None:
	# Patch sırası farklı bir kurulumda schema sync'ten önce çalışırsa da alanlar
	# ve tablolar hazır olsun.
	frappe.reload_doc("tradehub_core", "doctype", "media_category")
	frappe.reload_doc("tradehub_core", "doctype", "media_category_assignment")

	for row in frappe.get_all(
		"Media Category Assignment", fields=["name", "file_url", "file_url_hash"], limit_page_length=0
	):
		digest = hashlib.sha256((row.file_url or "").encode()).hexdigest()
		if row.file_url_hash != digest:
			frappe.db.set_value(
				"Media Category Assignment", row.name, "file_url_hash", digest, update_modified=False
			)

	if not _has_index("tabMedia Category", "uniq_media_category_scope"):
		frappe.db.sql(
			"""ALTER TABLE `tabMedia Category`
			ADD UNIQUE INDEX `uniq_media_category_scope`
			(`store`, `parent_category`, `category_name`)"""
		)
	if not _has_index("tabMedia Category Assignment", "uniq_media_category_assignment"):
		frappe.db.sql(
			"""ALTER TABLE `tabMedia Category Assignment`
			ADD UNIQUE INDEX `uniq_media_category_assignment`
			(`store`, `category`, `file_url_hash`)"""
		)

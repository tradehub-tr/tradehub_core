"""Atomic shadow-table swap utilities for Related Listing Cache.

The full rebuild writes new rows into a shadow table, then atomically
swaps it with the production table via MariaDB's RENAME TABLE statement.
This keeps the storefront API serving stale-but-consistent results
during the entire rebuild window — there is never a moment when the
production table is empty or partial.

The RENAME itself is metadata-only (~ms) on MariaDB ≥ 10.5, so the swap
is invisible to clients holding open SELECTs.
"""

from __future__ import annotations

import frappe

PROD_TABLE = "tabRelated Listing Cache"
SHADOW_TABLE = "tabRelated Listing Cache_shadow"
ARCHIVE_TABLE = "tabRelated Listing Cache_archive"


def ensure_shadow_table() -> None:
	"""Drop any stale shadow/archive, create a fresh empty shadow.

	Called at the start of every full rebuild. The DROP IF EXISTS makes
	this safe to run after a previously aborted rebuild left tables behind.
	"""
	frappe.db.sql(f"DROP TABLE IF EXISTS `{ARCHIVE_TABLE}`")
	frappe.db.sql(f"DROP TABLE IF EXISTS `{SHADOW_TABLE}`")
	frappe.db.sql(f"CREATE TABLE `{SHADOW_TABLE}` LIKE `{PROD_TABLE}`")


def shadow_exists() -> bool:
	rows = frappe.db.sql("SHOW TABLES LIKE %s", (SHADOW_TABLE,))
	return bool(rows)


def shadow_row_count() -> int:
	if not shadow_exists():
		return 0
	rows = frappe.db.sql(f"SELECT COUNT(*) FROM `{SHADOW_TABLE}`")
	return int(rows[0][0]) if rows else 0


def swap_tables() -> None:
	"""Atomic swap PROD ↔ SHADOW via three-way RENAME, then drop old.

	MariaDB executes the RENAME under a single metadata lock (~ms), so a
	concurrent SELECT against PROD either sees the old data fully or the
	new data fully — never an empty/partial state.
	"""
	frappe.db.sql(
		f"""
        RENAME TABLE
          `{PROD_TABLE}` TO `{ARCHIVE_TABLE}`,
          `{SHADOW_TABLE}` TO `{PROD_TABLE}`
        """
	)
	frappe.db.sql(f"DROP TABLE IF EXISTS `{ARCHIVE_TABLE}`")


def cleanup_shadow() -> None:
	"""Drop the shadow table without swapping. Used on rebuild abort."""
	frappe.db.sql(f"DROP TABLE IF EXISTS `{SHADOW_TABLE}`")

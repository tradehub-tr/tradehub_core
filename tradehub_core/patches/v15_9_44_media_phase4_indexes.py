"""T-044 — install the composite indexes used by critical Media queries."""

from __future__ import annotations

from dataclasses import dataclass

import frappe


@dataclass(frozen=True)
class IndexSpec:
	table: str
	name: str
	columns: tuple[str, ...]
	unique: bool = False


INDEXES: tuple[IndexSpec, ...] = (
	IndexSpec("tabMedia Asset", "ix_seller_state_modified", ("owner_seller", "state", "modified")),
	IndexSpec("tabMedia Asset", "ix_state_lastaccess", ("state", "last_access_at")),
	IndexSpec("tabMedia Asset", "ix_state_hold_creation", ("state", "legal_hold", "creation")),
	IndexSpec(
		"tabMedia Rendition",
		"uk_rendition_quad",
		("version_hash", "profile", "width", "format"),
		unique=True,
	),
	IndexSpec(
		"tabMedia Rendition",
		"ix_rendition_asset_version",
		("asset", "version_hash", "profile"),
	),
	IndexSpec(
		"tabMedia Processing Job",
		"ix_queue_status_modified",
		("queue", "status", "modified"),
	),
	IndexSpec(
		"tabMedia Processing Job",
		"ix_job_asset_status",
		("asset", "status"),
	),
)


def execute() -> dict[str, list[str]]:
	added: list[str] = []
	for spec in INDEXES:
		if _exists(spec):
			continue
		columns = ", ".join(f"`{column}`" for column in spec.columns)
		frappe.db.sql(
			f"ALTER TABLE `{spec.table}` ADD {'UNIQUE ' if spec.unique else ''}"
			f"KEY `{spec.name}` ({columns})"
		)
		added.append(spec.name)
	frappe.db.commit()
	return {"added": added, "present": [spec.name for spec in INDEXES]}


def _exists(spec: IndexSpec) -> bool:
	return bool(
		frappe.db.sql(
			"""select 1 from information_schema.statistics
			where table_schema = database() and table_name = %s and index_name = %s
			limit 1""",
			(spec.table, spec.name),
		)
	)

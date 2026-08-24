"""Faz 5 canonical storage settings, retention report and soft-delete schema."""

from __future__ import annotations

from typing import Any

import frappe

DOCTYPES: tuple[tuple[str, str], ...] = (
	("media_storage_profile", "Media Storage Profile"),
	("media_storage_settings", "Media Storage Settings"),
	("media_rendition", "Media Rendition"),
	("media_maintenance_report", "Media Maintenance Report"),
)


def execute() -> dict[str, Any]:
	loaded: list[str] = []
	for folder, doctype in DOCTYPES:
		frappe.reload_doc("tradehub_core", "doctype", folder, force=True)
		installed = (
			bool(frappe.db.exists("DocType", doctype))
			if doctype == "Media Storage Settings"
			else frappe.db.table_exists(doctype)
		)
		if not installed:
			frappe.throw(f"Faz 5 DocType tablosu oluşmadı: {doctype}")
		loaded.append(doctype)

	# Yeni required state alanından önceki satırlar servis edilebilir hazır
	# rendition'lardır. NULL bırakmak manifestin fail-closed filtresinde onları
	# görünmez yapardı.
	frappe.db.sql(
		"update `tabMedia Rendition` set state='ready' where ifnull(state, '')=''"
	)
	_migrate_storage_settings()
	# MariaDB index DDL'i implicit commit yapar; Frappe yazılı transaction
	# içinde bunu bilinçli olarak reddeder. Veri migrasyonunu önce kapat, sonra
	# idempotent DDL'i ayrı transaction sınırında uygula.
	frappe.db.commit()
	_install_indexes()
	frappe.db.commit()
	return {"loaded": loaded, "settings_seeded": True}


def seed_defaults() -> None:
	"""Fresh install ve upgrade için aynı güvenli retention başlangıcını kur."""
	if not frappe.db.exists("DocType", "Media Storage Settings"):
		return
	settings = frappe.get_single("Media Storage Settings")
	if not settings.derivative_always_keep_profiles:
		for profile in ("product-main", "product-card"):
			settings.append("derivative_always_keep_profiles", {"profile": profile})
	settings.legal_hold_overrides_all = 1
	settings.original_delete_requires_approval = 1
	settings.save(ignore_permissions=True)


def _migrate_storage_settings() -> None:
	settings = frappe.get_single("Media Storage Settings")
	# Single DocType'a sonradan eklenen alanlar `tabSingles`'ta satır olmadığı
	# için meta default'u yerine 0/None okunabilir. Validation'dan önce güvenli
	# canonical varsayılanları açıkça kur.
	_defaults = {
		"storage_mode": "local",
		"local_free_space_alarm_gb": 50,
		"s3_provider": "hetzner",
		"s3_prefix": "media",
		"s3_storage_class": "STANDARD",
		"s3_server_side_encryption": "none",
		"s3_multipart_threshold_mb": 64,
		"s3_max_concurrency": 4,
		"cdn_provider": "custom",
		"cdn_signed_ttl_seconds": 900,
		"cdn_cache_control_public": "public, max-age=31536000, immutable",
		"cdn_cache_control_private": "private, no-store",
		"imgproxy_max_source_mp": 30,
		"soft_delete_grace_days": 30,
	}
	for fieldname, value in _defaults.items():
		if settings.get(fieldname) in (None, "", 0, 0.0):
			settings.set(fieldname, value)
	for check_field in (
		"keep_originals",
		"derivative_regenerate_on_demand",
		"original_delete_requires_approval",
		"legal_hold_overrides_all",
	):
		if not frappe.db.sql(
			"select 1 from tabSingles where doctype=%s and field=%s limit 1",
			("Media Storage Settings", check_field),
		):
			settings.set(check_field, 1)
	if str(settings.get("original_then_action") or "") not in {
		"keep_local", "move_s3", "move_s3_cold", "delete"
	}:
		settings.original_then_action = "keep_local"
	legacy_mode = str(settings.get("backend") or "local")
	if not settings.get("storage_mode") or (
		str(settings.get("storage_mode")) == "local" and legacy_mode != "local"
	):
		settings.storage_mode = "s3_primary" if legacy_mode == "s3" else legacy_mode
	_copy_if_empty(settings, "s3_endpoint_url", "s3_endpoint")
	_copy_if_empty(settings, "s3_access_key_id", "s3_access_key")
	if not settings.get("cdn_signed_ttl_seconds") and settings.get("signed_url_ttl_seconds"):
		settings.cdn_signed_ttl_seconds = settings.signed_url_ttl_seconds
	if settings.storage_mode in {"s3_primary", "mirror", "tiered"} and settings.s3_bucket:
		settings.s3_enabled = 1
	elif settings.storage_mode in {"s3_primary", "mirror", "tiered"}:
		# Eksik bucket ile migrate'i ya da çalışan yerel yüklemeyi kırma. Legacy
		# niyet alanları korunur; operatör canonical ayarı tamamlayınca yeniden açar.
		settings.storage_mode = "local"
		settings.s3_enabled = 0
	if settings.storage_mode == "tiered" and int(settings.original_local_days or 0) < 1:
		settings.original_local_days = 90
	try:
		legacy_secret = settings.get_password("s3_secret_key", raise_exception=False) or ""
		canonical_secret = settings.get_password(
			"s3_secret_access_key", raise_exception=False
		) or ""
	except Exception:
		legacy_secret = canonical_secret = ""
	if legacy_secret and not canonical_secret:
		settings.s3_secret_access_key = legacy_secret
	seed_profiles = not settings.derivative_always_keep_profiles
	if seed_profiles:
		for profile in ("product-main", "product-card"):
			settings.append("derivative_always_keep_profiles", {"profile": profile})
	settings.legal_hold_overrides_all = 1
	settings.original_delete_requires_approval = 1
	settings.save(ignore_permissions=True)


def _copy_if_empty(doc: Any, target: str, source: str) -> None:
	if not doc.get(target) and doc.get(source):
		doc.set(target, doc.get(source))


def _install_indexes() -> None:
	_indexes = (
		("tabMedia Rendition", "ix_rendition_state_purge", ("state", "purge_after")),
		(
			"tabMedia Maintenance Report",
			"ix_media_maintenance_approval",
			("job_type", "policy_hash", "approval_status", "expires_at"),
		),
	)
	for table, name, columns in _indexes:
		present = frappe.db.sql(
			"""select 1 from information_schema.statistics
			where table_schema=database() and table_name=%s and index_name=%s limit 1""",
			(table, name),
		)
		if present:
			continue
		frappe.db.sql(
			f"alter table `{table}` add key `{name}` ({', '.join(f'`{c}`' for c in columns)})"
		)

"""Mevcut sitelerde medya işleme ve eski görsellerin otomatik geçişini aç."""

import frappe

from tradehub_core.media import pipeline_flags
from tradehub_core.patches.v15_9_22_media_engine_settings import execute as seed_settings


def execute() -> None:
	seed_settings()
	settings = frappe.get_doc("Media Engine Settings")
	settings.media_pipeline_enabled = 1
	settings.rendition_on_upload = 1
	settings.manifest_api_enabled = 1
	settings.active_slots = "*"
	settings.rollout_percent = 100
	settings.save(ignore_permissions=True)
	pipeline_flags.clear_cache()
	# Profil/scheduler sync tamamlanınca after_install/after_migrate kancası
	# başlatır. Bu tek seferlik patch, sonraki manuel kapatmaları ezmez.
	frappe.db.commit()

"""Medya motorunun açık varsayılanlarını yükle; kayıtlı tercihleri koru."""

from tradehub_core.patches.v15_9_22_media_engine_settings import execute as seed_settings


def execute() -> dict:
	return seed_settings()

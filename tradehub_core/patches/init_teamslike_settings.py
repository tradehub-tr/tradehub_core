"""
Teamslike Settings singleton'ını ilk kurulumda doldur.

İçeride iki kaynaktan bilgi okur:

1. Container içinde mount edilmiş `/teamslike-tenant.json` (varsa)
2. Aksi halde sadece base_url ve enabled=0 ile boş singleton yazar; UI'dan
   manuel doldurulabilir.

JSON şeması (provision sırasında oluşturulan dosya):
{
  "base_url": "http://host.docker.internal:8800",
  "tenant_slug": "istoc",
  "tenant_id": "...",
  "tenant_name": "...",
  "admin_email": "admin@istoc.io",
  "admin_full_name": "iSTOC Admin",
  "admin_user_id": "...",
  "admin_password": "...",
  "admin_access_token": "...",
  "signing_secret": "..."
}
"""

import json
import os

import frappe

CREDENTIALS_PATHS = [
	"/teamslike-tenant.json",  # backend container içinde bind-mount
	"/home/frappe/frappe-bench/sites/teamslike-tenant.json",
]


def execute():
	settings = frappe.get_single("Teamslike Settings")
	# Zaten doldurulmuşsa dokunma
	if settings.get("tenant_id"):
		return

	creds = _read_credentials()
	if not creds:
		# UI'dan manuel doldurulmak üzere boş başla
		settings.base_url = "http://host.docker.internal:8800"
		settings.enabled = 0
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		return

	settings.enabled = 1
	settings.base_url = creds.get("base_url") or "http://host.docker.internal:8800"
	settings.tenant_slug = creds.get("tenant_slug") or ""
	settings.tenant_id = creds.get("tenant_id") or ""
	settings.tenant_name = creds.get("tenant_name") or ""
	settings.admin_email = creds.get("admin_email") or ""
	settings.admin_full_name = creds.get("admin_full_name") or ""
	settings.admin_user_id = creds.get("admin_user_id") or ""
	settings.admin_password = creds.get("admin_password") or ""
	settings.admin_access_token = creds.get("admin_access_token") or ""
	settings.signing_secret = creds.get("signing_secret") or ""
	settings.save(ignore_permissions=True)
	frappe.db.commit()


def _read_credentials():
	for path in CREDENTIALS_PATHS:
		if os.path.isfile(path):
			try:
				with open(path) as f:
					return json.load(f)
			except (OSError, json.JSONDecodeError):
				continue
	return None

"""One-shot debug helper — DELETE after use."""

import traceback

import frappe
import requests

from tradehub_core.api import chat
from tradehub_core.api.chat import _admin_headers, _api_url, _settings


def fix_base_url():
	s = frappe.get_single("Teamslike Settings")
	old = s.base_url
	new = "http://host.docker.internal:8090/api"
	s.base_url = new
	s.admin_access_token = ""
	s.admin_token_expires_at = None
	s.save(ignore_permissions=True)
	frappe.db.commit()
	print(f"base_url: {old!r} -> {new!r}; token cache cleared")


def reset_seller_provisioning():
	"""TeamsLike'taki demo-seller-* user'larını sil, Frappe'deki field'ları temizle.
	Sonraki chat çağrısında auto-provision tekrar çalışacak.
	"""
	s = _settings()
	headers = _admin_headers()
	r = requests.get(_api_url(s, "/v1/users/"), headers=headers, timeout=10)
	if r.status_code >= 400:
		print(f"List users failed: {r.status_code} {r.text}")
		return
	users = r.json()
	print(f"TeamsLike user count: {len(users)}")
	deleted = 0
	for u in users:
		email = (u.get("email") or "").lower()
		if email.startswith("demo-seller-") or email.startswith("demo-buyer-"):
			uid = u.get("id")
			print(f"  deleting {email} (id={uid})")
			dr = requests.delete(_api_url(s, f"/v1/users/{uid}"), headers=headers, timeout=10)
			if dr.status_code >= 400:
				print(f"    failed: {dr.status_code} {dr.text[:200]}")
			else:
				deleted += 1
	print(f"TeamsLike deleted: {deleted}")

	# Frappe tarafında custom field'ları temizle
	seller_users = frappe.get_all(
		"User",
		filters={"email": ["like", "demo-%@istoc.demo"]},
		fields=["name", "email"],
	)
	cleared = 0
	for u in seller_users:
		frappe.db.set_value(
			"User",
			u.name,
			{"teamslike_user_id": "", "teamslike_password": "", "teamslike_provisioned_at": None},
		)
		cleared += 1
	frappe.db.commit()
	print(f"Frappe User fields cleared: {cleared}")


def run():
	for email in ("demo-seller-01@istoc.demo", "demo-buyer-01@istoc.demo"):
		frappe.set_user(email)
		print(f"\n=== {email} (roles={frappe.get_roles()[:3]}) ===")
		try:
			res = chat.list_my_threads(perspective=None)
			print(f"OK  type={type(res).__name__} len={len(res) if hasattr(res, '__len__') else 'n/a'}")
			if isinstance(res, list) and res:
				print(f"first thread keys: {list(res[0].keys()) if isinstance(res[0], dict) else type(res[0])}")
		except Exception:
			print("FAILED:")
			traceback.print_exc()

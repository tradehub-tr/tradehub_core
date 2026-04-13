import json

import frappe
from frappe import _


@frappe.whitelist(methods=["GET"])
def get_email_preferences():
	"""Aktif e-posta tercih kategorilerini ve kullanıcının tercihlerini döner."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Oturum açmanız gerekiyor."), frappe.AuthenticationError)

	categories = frappe.get_list(
		"Email Preference Category",
		filters={"is_active": 1},
		fields=["name", "category_key", "title", "description", "default_enabled"],
		order_by="sort_order asc",
	)

	if not categories:
		return {"categories": []}

	# Tüm kalemleri tek sorguda çek, parent'a göre grupla
	parent_names = [c.name for c in categories]
	all_items = frappe.get_all(
		"Email Preference Item",
		filters={"parent": ["in", parent_names], "parenttype": "Email Preference Category"},
		fields=["parent", "item_key", "title", "description", "default_enabled", "sort_order"],
		order_by="sort_order asc",
	)

	items_by_parent: dict[str, list] = {}
	for item in all_items:
		items_by_parent.setdefault(item.parent, []).append(item)

	# Kullanıcı tercihlerini çek
	toggles, checks = _get_user_prefs(user)

	result = []
	for cat in categories:
		cat_items = items_by_parent.get(cat.name, [])
		cat_checks = [
			checks.get(item.item_key, bool(item.default_enabled))
			for item in cat_items
		]
		# Toggle durumu: kullanıcı kaydı varsa onu kullan, yoksa checkbox'lardan türet
		cat_enabled = toggles.get(cat.category_key) if cat.category_key in toggles else any(cat_checks)

		result.append({
			"id": cat.category_key,
			"title": _(cat.title),
			"description": _(cat.description or ""),
			"enabled": cat_enabled,
			"items": [
				{
					"id": item.item_key,
					"title": _(item.title),
					"description": _(item.description or ""),
					"checked": checks.get(item.item_key, bool(item.default_enabled)),
				}
				for item in cat_items
			],
		})

	return {"categories": result}


@frappe.whitelist(methods=["POST"])
def save_email_preferences(preferences=None):
	"""Kullanıcının e-posta tercihlerini kaydeder."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Oturum açmanız gerekiyor."), frappe.AuthenticationError)

	if not preferences:
		frappe.throw(_("Tercih verisi gerekli."), frappe.ValidationError)

	# Frappe hem string hem dict gönderebilir
	if isinstance(preferences, str):
		try:
			preferences = json.loads(preferences)
		except (json.JSONDecodeError, TypeError):
			frappe.throw(_("Geçersiz tercih verisi."), frappe.ValidationError)

	if not isinstance(preferences, dict):
		frappe.throw(_("Geçersiz tercih formatı."), frappe.ValidationError)

	toggles = preferences.get("toggles", {})
	checks = preferences.get("checks", {})

	if not isinstance(toggles, dict) or not isinstance(checks, dict):
		frappe.throw(_("Geçersiz tercih formatı."), frappe.ValidationError)

	prefs_json = json.dumps({"toggles": toggles, "checks": checks})

	if frappe.db.exists("User Email Preference", user):
		frappe.db.set_value("User Email Preference", user, "preferences_json", prefs_json)
	else:
		doc = frappe.new_doc("User Email Preference")
		doc.user = user
		doc.preferences_json = prefs_json
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
	return {"success": True}


def _get_user_prefs(user: str) -> tuple[dict, dict]:
	"""Kullanıcının tercih JSON'ını parse eder. (toggles, checks) tuple döner."""
	raw = frappe.db.get_value("User Email Preference", user, "preferences_json")
	if not raw:
		return {}, {}
	try:
		prefs = json.loads(raw)
		return prefs.get("toggles", {}), prefs.get("checks", {})
	except (json.JSONDecodeError, TypeError):
		return {}, {}

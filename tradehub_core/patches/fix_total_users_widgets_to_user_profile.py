"""Sprint 2 sonrası `User` → `User Profile` geçişi (Dashboard Widget'ları).

Tarihçe:
Sprint 2'de Buyer Profile + Seller Profile birleşip `User Profile` canonical
DocType'ına dönüştü. Tüm marketplace kullanıcıları (alıcı + satıcı + hybrid)
artık bir `User Profile` kaydına sahip; aktiflik tek doğru kaynak olarak
`User Profile.status = 'Active'` üzerinden okunur.

Ancak Sprint 2'den ÖNCE seed edilen 3 dashboard widget'ı Frappe core'un
`User` doctype'ını `user_type='System User' AND enabled=1` filtresiyle
sorguluyor. Bu filtre güvenlik nedeniyle alıcıları (hep `Website User`
tutulanlar) ve onaylanmamış satıcıları (henüz System User'a yükseltilmemiş)
sayım dışı bırakıyor → "Toplam Kullanıcı" %70-90 eksik gösteriyor.

Etkilenen widget'lar (platform_overview):
- "Toplam Kullanıcı" (kpi_single): source_doctype + filters_json
- "Hızlı Erişim" (quick_links): config_json.links[] içindeki "Kullanıcılar" entry
                                + "Alıcı Profilleri" entry (Buyer Profile deprecated)
- "Satıcı Onboarding Funnel" (funnel_chart): config_json.stages[] içindeki "users" stage

Idempotent: zaten User Profile'a yazılmış olanları atlar; widget yoksa sessizce
çıkar (yeni install'da seed zaten doğru değerleri yazdığı için patch no-op olur).
"""

import json

import frappe

DASHBOARD_KEY = "platform_overview"


def execute():
	_fix_total_users_kpi()
	_fix_quick_links_user_entry()
	_fix_onboarding_funnel_first_stage()
	frappe.db.commit()


def _fix_total_users_kpi():
	"""KPI widget'in top-level source_doctype + filters_json'unu güncelle."""
	name = frappe.db.get_value(
		"Dashboard Widget",
		{"dashboard_key": DASHBOARD_KEY, "title": "Toplam Kullanıcı"},
		"name",
	)
	if not name:
		return
	if frappe.db.get_value("Dashboard Widget", name, "source_doctype") == "User Profile":
		return  # zaten düzeltildi
	frappe.db.set_value(
		"Dashboard Widget",
		name,
		{
			"source_doctype": "User Profile",
			"filters_json": json.dumps([["status", "=", "Active"]]),
		},
	)
	print(f"  [updated] {name}: 'Toplam Kullanıcı' → User Profile + status=Active")


def _fix_quick_links_user_entry():
	"""Hızlı Erişim widget'ı içindeki config_json.links[] dizisinden:
	- label='Kullanıcılar' + source_doctype='User' → User Profile
	- label='Alıcı Profilleri' + source_doctype='Buyer Profile' → User Profile + can_buy=1
	"""
	name = frappe.db.get_value(
		"Dashboard Widget",
		{"dashboard_key": DASHBOARD_KEY, "title": "Hızlı Erişim"},
		"name",
	)
	if not name:
		return
	raw = frappe.db.get_value("Dashboard Widget", name, "config_json")
	if not raw:
		return
	try:
		config = json.loads(raw)
	except (TypeError, ValueError):
		# Bozuk JSON — manuel müdahale gerek, patch sessizce atlasın
		return
	changed = False
	for link in config.get("links") or []:
		# Kullanıcılar: User (Frappe core) → User Profile (canonical)
		if link.get("label") == "Kullanıcılar" and link.get("source_doctype") == "User":
			link["source_doctype"] = "User Profile"
			link["to"] = "/app/User Profile"
			changed = True
		# Alıcı Profilleri: Buyer Profile (deprecated) → User Profile + can_buy filter
		elif link.get("label") == "Alıcı Profilleri" and link.get("source_doctype") == "Buyer Profile":
			link["source_doctype"] = "User Profile"
			link["to"] = "/app/User Profile?can_buy=1"
			link["filters"] = [["can_buy", "=", 1]]
			changed = True
	if changed:
		frappe.db.set_value("Dashboard Widget", name, "config_json", json.dumps(config))
		print(f"  [updated] {name}: 'Hızlı Erişim' linkler güncellendi (Kullanıcılar, Alıcı Profilleri)")


def _fix_onboarding_funnel_first_stage():
	"""Funnel widget'ı içindeki config_json.stages[] dizisinden key='users'
	olan stage'i güncelle."""
	name = frappe.db.get_value(
		"Dashboard Widget",
		{"dashboard_key": DASHBOARD_KEY, "title": "Satıcı Onboarding Funnel"},
		"name",
	)
	if not name:
		return
	raw = frappe.db.get_value("Dashboard Widget", name, "config_json")
	if not raw:
		return
	try:
		config = json.loads(raw)
	except (TypeError, ValueError):
		return
	changed = False
	for stage in config.get("stages") or []:
		if stage.get("key") == "users" and stage.get("doctype") == "User":
			stage["doctype"] = "User Profile"
			stage["filters"] = [["status", "=", "Active"]]
			changed = True
	if changed:
		frappe.db.set_value("Dashboard Widget", name, "config_json", json.dumps(config))
		print(f"  [updated] {name}: 'Satıcı Onboarding Funnel' users stage → User Profile")

"""Media SEO visibility/indexability policy alanları."""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute() -> None:
	create_custom_fields({
		"File": [
			{
				"fieldname": "th_media_visibility", "label": "TH Media Visibility",
				"fieldtype": "Select",
				"options": "Public\nPrivate\nUnlisted\nProtected\nTemporary\nExpired\nArchived\nDeleted",
				"default": "Public", "hidden": 1, "no_copy": 1, "module": "Tradehub Core",
			},
			{
				"fieldname": "th_media_expires_at", "label": "TH Media Expires At",
				"fieldtype": "Datetime", "hidden": 1, "no_copy": 1, "module": "Tradehub Core",
			},
			{
				"fieldname": "th_media_robots_override", "label": "TH Media Robots Override",
				"fieldtype": "Data", "hidden": 1, "no_copy": 1, "module": "Tradehub Core",
			},
			{
				"fieldname": "th_media_creator_type", "label": "TH Media Creator Type",
				"fieldtype": "Select", "options": "\nPerson\nOrganization",
				"hidden": 1, "no_copy": 1, "module": "Tradehub Core",
			},
		]
	}, update=True)
	_migrate_listing_image_override_identity()


def _migrate_listing_image_override_identity() -> None:
	"""Eski parent Listing adıyla yazılan galeri override'larını child row'a taşı."""
	if not frappe.db.table_exists("Media SEO Override"):
		return
	rows = frappe.db.sql(
		"""select o.name, o.file_url, o.ref_name
		from `tabMedia SEO Override` o
		where o.ref_doctype='Listing Image' and o.ref_field='image'""",
		as_dict=True,
	)
	for row in rows:
		# Zaten gerçek child-row kimliğiyse dokunma.
		if frappe.db.exists("Listing Image", row["ref_name"]):
			continue
		children = frappe.get_all(
			"Listing Image",
			filters={"parent": row["ref_name"], "parenttype": "Listing", "image": row["file_url"]},
			fields=["name"], limit_page_length=2,
		)
		# Aynı URL aynı galeride iki kez kullanılmışsa otomatik seçim yapma.
		if len(children) != 1:
			continue
		if frappe.db.exists(
			"Media SEO Override",
			{
				"file_url": row["file_url"],
				"ref_doctype": "Listing Image",
				"ref_name": children[0]["name"],
				"ref_field": "image",
			},
		):
			continue
		frappe.db.set_value(
			"Media SEO Override", row["name"], "ref_name", children[0]["name"], update_modified=False
		)

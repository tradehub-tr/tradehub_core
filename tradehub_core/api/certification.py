import frappe
from frappe import _


@frappe.whitelist(allow_guest=True)
def get_certification_types(category=None, status="Approved"):
	"""Get certification types, optionally filtered by category and status."""
	filters = {}
	if status:
		filters["status"] = status
	if category:
		filters["category"] = category

	certs = frappe.get_all(
		"Certification Type",
		filters=filters,
		fields=["name", "certification_name", "category", "status", "description"],
		order_by="certification_name ASC",
	)
	return {"data": certs}


@frappe.whitelist(methods=["POST"])
def suggest_certification(certification_name: str, category: str, description: str = ""):
	"""Seller suggests a new certification type. Created as Pending for admin approval."""
	certification_name = (certification_name or "").strip()
	category = (category or "").strip()

	if not certification_name:
		frappe.throw(_("Sertifika adı zorunludur."))
	if category not in ("Management", "Product"):
		frappe.throw(_("Kategori 'Management' veya 'Product' olmalıdır."))

	# Check duplicate
	if frappe.db.exists("Certification Type", {"certification_name": certification_name}):
		frappe.throw(_("Bu isimde bir sertifika zaten mevcut."))

	doc = frappe.new_doc("Certification Type")
	doc.certification_name = certification_name
	doc.category = category
	doc.description = description
	doc.status = "Pending"
	doc.suggested_by = frappe.session.user
	doc.insert(ignore_permissions=True)

	return {
		"success": True,
		"message": _("Sertifika öneriniz admin onayına gönderildi."),
		"name": doc.name,
	}


@frappe.whitelist(methods=["POST"])
def approve_certification(name: str):
	"""Admin approves a pending certification type."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Bu işlem için yetkiniz yok."), frappe.PermissionError)

	doc = frappe.get_doc("Certification Type", name)
	if doc.status != "Pending":
		frappe.throw(_("Sadece bekleyen sertifikalar onaylanabilir."))

	doc.status = "Approved"
	doc.save(ignore_permissions=True)

	return {"success": True, "message": _("Sertifika onaylandı.")}


@frappe.whitelist(methods=["POST"])
def reject_certification(name: str, reason: str = ""):
	"""Admin rejects a pending certification type."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Bu işlem için yetkiniz yok."), frappe.PermissionError)

	doc = frappe.get_doc("Certification Type", name)
	if doc.status != "Pending":
		frappe.throw(_("Sadece bekleyen sertifikalar reddedilebilir."))

	doc.status = "Rejected"
	doc.rejection_reason = reason
	doc.save(ignore_permissions=True)

	return {"success": True, "message": _("Sertifika reddedildi.")}

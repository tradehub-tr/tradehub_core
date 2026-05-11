"""Certification Type endpoint'leri — sistem kataloğu + öneri akışı.

v4 mimari:
- Admin onaylarken kategoriyi düzeltebilir
- Reddedilen aynı isim önerisi → "Sebebi göster + bloklu" mesaj
"""

import frappe
from frappe import _

from tradehub_core.utils.notify import notify


def _notify_admins(title: str, message: str, action_url: str, ref_name: str) -> int:
	"""System Manager rolüne sahip aktif kullanıcılara bildirim — dedup'lu."""
	admins = frappe.db.sql(
		"""
		SELECT DISTINCT u.name
		FROM `tabUser` u
		INNER JOIN `tabHas Role` hr ON hr.parent = u.name AND hr.parenttype = 'User'
		WHERE u.enabled = 1
			AND hr.role = 'System Manager'
			AND u.name NOT IN ('Administrator', 'Guest')
		""",
		as_dict=True,
	)
	count = 0
	for a in admins:
		notify(
			recipient_user=a.name,
			type="certification",
			title=title,
			message=message,
			recipient_role="admin",
			action_url=action_url,
			reference_doctype="Certification Type",
			reference_name=ref_name,
		)
		count += 1
	return count


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
	"""Satıcı yeni cert türü önerir.

	v4: Aynı isimle rejected kayıt varsa kullanıcı dostu mesaj ver.
	"""
	certification_name = (certification_name or "").strip()
	category = (category or "").strip()

	if not certification_name:
		frappe.throw(_("Sertifika adı zorunludur."))
	if category not in ("Management", "Product"):
		frappe.throw(_("Kategori 'Management' veya 'Product' olmalıdır."))

	# Duplicate check — sebebi göster
	existing = frappe.db.get_value(
		"Certification Type",
		{"certification_name": certification_name},
		["name", "status", "rejection_reason"],
		as_dict=True,
	)
	if existing:
		if existing.status == "Rejected":
			reason = existing.rejection_reason or _("(sebep belirtilmemiş)")
			frappe.throw(
				_(
					"'{0}' sertifikası daha önce reddedildi.\n\nSebep: {1}\n\nBu isimle yeniden öneremezsiniz."
				).format(certification_name, reason)
			)
		elif existing.status == "Pending":
			frappe.throw(_("'{0}' sertifikası zaten admin onayı bekliyor.").format(certification_name))
		else:  # Approved
			frappe.throw(
				_(
					"'{0}' sertifikası zaten sistemde mevcut. Sertifikalarım > Mağaza Sertifikalarım'dan ekleyebilirsiniz."
				).format(certification_name)
			)

	doc = frappe.new_doc("Certification Type")
	doc.certification_name = certification_name
	doc.category = category
	doc.description = description
	doc.status = "Pending"
	doc.suggested_by = frappe.session.user
	doc.insert(ignore_permissions=True)

	# Süper admin'e bildirim
	try:
		_notify_admins(
			title=_("Yeni sertifika önerisi"),
			message=_("'{0}' adlı sertifika önerildi (kategori: {1}, öneren: {2}).").format(
				certification_name,
				_("Yönetim") if category == "Management" else _("Ürün"),
				frappe.session.user,
			),
			action_url=f"/panel/app/Certification Type/{doc.name}",
			ref_name=doc.name,
		)
	except Exception:
		frappe.log_error(title="suggest_certification: admin notify")

	return {
		"success": True,
		"message": _("Sertifika öneriniz admin onayına gönderildi."),
		"name": doc.name,
	}


@frappe.whitelist(methods=["POST"])
def approve_certification(name: str, category: str = None):
	"""Admin onaylar.

	v4: Admin onay sırasında kategoriyi düzeltebilir.
	"""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Bu işlem için yetkiniz yok."), frappe.PermissionError)

	doc = frappe.get_doc("Certification Type", name)
	if doc.status != "Pending":
		frappe.throw(_("Sadece bekleyen sertifikalar onaylanabilir."))

	category_changed = False
	if category and category in ("Management", "Product") and category != doc.category:
		old_category = doc.category
		doc.category = category
		category_changed = True
	else:
		old_category = doc.category

	doc.status = "Approved"
	doc.save(ignore_permissions=True)

	# Önerene bildirim
	if doc.suggested_by and doc.suggested_by not in ("Administrator", "Guest"):
		try:
			cat_msg = ""
			if category_changed:
				cat_msg = _(" (Kategori '{0}' olarak düzeltildi.)").format(
					_("Yönetim") if doc.category == "Management" else _("Ürün")
				)
			notify(
				recipient_user=doc.suggested_by,
				type="certification",
				title=_("Sertifika öneriniz onaylandı"),
				message=_("Önerdiğiniz '{0}' sertifikası onaylandı ve sistem kataloğuna eklendi.{1}").format(
					doc.certification_name, cat_msg
				),
				recipient_role="seller",
				action_url="/panel/my-certifications#suggestions",
				reference_doctype="Certification Type",
				reference_name=doc.name,
			)
		except Exception:
			frappe.log_error(title="approve_certification: seller notify")

	return {
		"success": True,
		"message": _("Sertifika onaylandı."),
		"category_changed": category_changed,
		"old_category": old_category,
		"new_category": doc.category,
	}


@frappe.whitelist(methods=["POST"])
def reject_certification(name: str, reason: str = ""):
	"""Admin reddeder — sebep zorunlu."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Bu işlem için yetkiniz yok."), frappe.PermissionError)

	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Reddetme sebebi zorunludur."))

	doc = frappe.get_doc("Certification Type", name)
	if doc.status != "Pending":
		frappe.throw(_("Sadece bekleyen sertifikalar reddedilebilir."))

	doc.status = "Rejected"
	doc.rejection_reason = reason
	doc.save(ignore_permissions=True)

	# Önerene bildirim
	if doc.suggested_by and doc.suggested_by not in ("Administrator", "Guest"):
		try:
			notify(
				recipient_user=doc.suggested_by,
				type="certification",
				title=_("Sertifika öneriniz reddedildi"),
				message=_("Önerdiğiniz '{0}' sertifikası reddedildi. Sebep: {1}").format(
					doc.certification_name, reason
				),
				recipient_role="seller",
				action_url="/panel/my-certifications#suggestions",
				reference_doctype="Certification Type",
				reference_name=doc.name,
			)
		except Exception:
			frappe.log_error(title="reject_certification: seller notify")

	return {"success": True, "message": _("Sertifika reddedildi.")}

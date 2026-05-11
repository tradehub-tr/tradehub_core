"""
Sertifika süre dolma kontrolü — daily scheduler.

Listing Certification ve Seller Certification child table'larında expiry_date
alanına göre 30 gün, 7 gün ve süresi dolan kayıtlar için Platform Notification
oluşturur. Süresi dolan kayıtlar verification_status = 'Rejected' olarak
işaretlenir (storefront filter'larında otomatik düşer).

hooks.py'a daily scheduler olarak kayıtlı.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate, today

from tradehub_core.utils.notify import notify

NOTIFY_THRESHOLDS = (30, 7, 0)  # gün
NOTIFICATION_TYPE = "certification"


def check_certificate_expiry() -> dict:
	"""Tüm Listing/Seller Certification kayıtları için expiry kontrol.

	Daily scheduler'dan çağrılır. Returns sayılar dict — log/test için.
	"""
	stats = {
		"listing_30": 0,
		"listing_7": 0,
		"listing_expired": 0,
		"seller_30": 0,
		"seller_7": 0,
		"seller_expired": 0,
	}

	# ── Listing Certification ────────────────────────────────────────────
	listing_certs = frappe.db.sql(
		"""
		SELECT
			lc.name AS row_name,
			lc.parent AS listing_name,
			lc.certification_type AS cert_type,
			lc.expiry_date,
			lc.verification_status,
			l.seller_profile AS seller_profile,
			l.title AS listing_title
		FROM `tabListing Certification` lc
		INNER JOIN `tabListing` l ON l.name = lc.parent
		WHERE lc.expiry_date IS NOT NULL
			AND IFNULL(lc.verification_status, 'Pending') != 'Rejected'
		""",
		as_dict=True,
	)

	for row in listing_certs:
		days = (getdate(row.expiry_date) - getdate(today())).days
		seller_user = _seller_profile_user(row.seller_profile)
		if days == 30:
			_notify_expiry(
				seller_user=seller_user,
				cert_name=row.cert_type,
				days=30,
				ref_doctype="Listing",
				ref_name=row.listing_name,
				context=_("ürün ({0})").format(row.listing_title or row.listing_name),
				action_url=f"/panel/app/Listing/{row.listing_name}",
			)
			stats["listing_30"] += 1
		elif days == 7:
			_notify_expiry(
				seller_user=seller_user,
				cert_name=row.cert_type,
				days=7,
				ref_doctype="Listing",
				ref_name=row.listing_name,
				context=_("ürün ({0})").format(row.listing_title or row.listing_name),
				action_url=f"/panel/app/Listing/{row.listing_name}",
			)
			stats["listing_7"] += 1
		elif days <= 0:
			_notify_expiry(
				seller_user=seller_user,
				cert_name=row.cert_type,
				days=0,
				ref_doctype="Listing",
				ref_name=row.listing_name,
				context=_("ürün ({0})").format(row.listing_title or row.listing_name),
				action_url=f"/panel/app/Listing/{row.listing_name}",
			)
			# Süresi dolan kayıt verification_status = Rejected → storefront düşer
			frappe.db.set_value(
				"Listing Certification",
				row.row_name,
				"verification_status",
				"Rejected",
				update_modified=False,
			)
			stats["listing_expired"] += 1

	# ── Seller Certification ─────────────────────────────────────────────
	seller_certs = frappe.db.sql(
		"""
		SELECT
			sc.name AS row_name,
			sc.parent AS seller_profile,
			sc.certification_type AS cert_type,
			sc.expiry_date,
			sc.verification_status
		FROM `tabSeller Certification` sc
		WHERE sc.expiry_date IS NOT NULL
			AND IFNULL(sc.verification_status, 'Pending') != 'Rejected'
		""",
		as_dict=True,
	)

	for row in seller_certs:
		days = (getdate(row.expiry_date) - getdate(today())).days
		seller_user = _seller_profile_user(row.seller_profile)
		if days == 30:
			_notify_expiry(
				seller_user=seller_user,
				cert_name=row.cert_type,
				days=30,
				ref_doctype="Admin Seller Profile",
				ref_name=row.seller_profile,
				context=_("mağaza"),
				action_url="/panel/my-certifications",
			)
			stats["seller_30"] += 1
		elif days == 7:
			_notify_expiry(
				seller_user=seller_user,
				cert_name=row.cert_type,
				days=7,
				ref_doctype="Admin Seller Profile",
				ref_name=row.seller_profile,
				context=_("mağaza"),
				action_url="/panel/my-certifications",
			)
			stats["seller_7"] += 1
		elif days <= 0:
			_notify_expiry(
				seller_user=seller_user,
				cert_name=row.cert_type,
				days=0,
				ref_doctype="Admin Seller Profile",
				ref_name=row.seller_profile,
				context=_("mağaza"),
				action_url="/panel/my-certifications",
			)
			frappe.db.set_value(
				"Seller Certification",
				row.row_name,
				"verification_status",
				"Rejected",
				update_modified=False,
			)
			stats["seller_expired"] += 1

	frappe.db.commit()
	return stats


def _seller_profile_user(seller_profile: str | None) -> str:
	"""Admin Seller Profile.user → bildirim alıcısı."""
	if not seller_profile:
		return ""
	return frappe.db.get_value("Admin Seller Profile", seller_profile, "user") or ""


def _notify_expiry(
	seller_user: str,
	cert_name: str,
	days: int,
	ref_doctype: str,
	ref_name: str,
	context: str,
	action_url: str,
) -> None:
	"""30/7/0 gün için bildirim — `notify` helper kullanır."""
	if not seller_user or seller_user in ("Guest", "Administrator"):
		return
	if days == 30:
		title = _("Sertifika süresi yaklaşıyor")
		msg = _("'{0}' sertifikası 30 gün sonra dolacak ({1}). Yenileme için belgeleri hazırlayın.").format(
			cert_name, context
		)
	elif days == 7:
		title = _("Sertifika 7 gün içinde dolacak")
		msg = _("'{0}' sertifikası 7 gün sonra dolacak ({1}). Acil yenileme gerekli.").format(
			cert_name, context
		)
	else:
		title = _("Sertifika süresi doldu")
		msg = _("'{0}' sertifikasının süresi doldu ({1}). Storefront filtrelerinden kaldırıldı.").format(
			cert_name, context
		)

	notify(
		recipient_user=seller_user,
		type=NOTIFICATION_TYPE,
		title=title,
		message=msg,
		recipient_role="seller",
		action_url=action_url,
		reference_doctype=ref_doctype,
		reference_name=ref_name,
	)

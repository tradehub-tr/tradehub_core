"""Faz 4 — Order Dispute (Review-as-Evidence).

1-2★ yorumlar bir Order Dispute açabilir. Dispute resolved olunca yoruma
rozet eklenir: "Anlaşmazlık X lehine çözüldü".

Akış: manuel onaylı CTA — buyer tıklamadan otomatik dispute oluşmaz.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime

VALID_DISPUTE_TYPES = {
	"Product Quality",
	"Wrong Item",
	"Damaged",
	"Not Delivered",
	"Other",
}
VALID_RESOLUTIONS = {"buyer", "seller"}


def _ensure_logged_in():
	if frappe.session.user == "Guest":
		frappe.throw(_("Giriş yapın"), frappe.AuthenticationError)


def _is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	return bool(roles & {"System Manager", "Marketplace Admin"})


@frappe.whitelist()
def open_dispute_from_review(review: str, dispute_type: str, description: str):
	"""Buyer 1-2★ yorum üzerinden anlaşmazlık başlatır."""
	_ensure_logged_in()
	if dispute_type not in VALID_DISPUTE_TYPES:
		frappe.throw(_("Geçersiz anlaşmazlık tipi"))
	desc = (description or "").strip()
	if len(desc) < 10:
		frappe.throw(_("Açıklama en az 10 karakter olmalı"))

	rev = frappe.db.get_value(
		"Listing Review",
		review,
		["reviewer_user", "order", "order_item", "seller", "rating", "related_dispute"],
		as_dict=True,
	)
	if not rev:
		frappe.throw(_("Yorum bulunamadı"), frappe.DoesNotExistError)
	if rev.related_dispute:
		frappe.throw(_("Bu yorum için zaten anlaşmazlık açıldı: {0}").format(rev.related_dispute))
	if rev.reviewer_user != frappe.session.user and not _is_admin():
		frappe.throw(_("Yalnızca yorumun sahibi açabilir"), frappe.PermissionError)
	if rev.rating and int(rev.rating) > 2:
		# B2B'de 3★+ için dispute genellikle açılmaz — guard
		frappe.throw(_("Anlaşmazlık yalnızca 1-2★ yorumlar üzerinden açılabilir"))

	doc = frappe.new_doc("Order Dispute")
	doc.order = rev.order
	doc.order_item = rev.order_item
	doc.related_review = review
	doc.buyer = rev.reviewer_user
	doc.seller = rev.seller
	doc.dispute_type = dispute_type
	doc.description = desc
	doc.status = "Open"
	doc.opened_at = now_datetime()
	doc.insert(ignore_permissions=True)

	# Listing Review.related_dispute cache
	frappe.db.set_value("Listing Review", review, "related_dispute", doc.name, update_modified=False)
	frappe.db.commit()
	return {"success": True, "name": doc.name, "status": doc.status}


@frappe.whitelist()
def resolve_dispute(dispute: str, in_favor_of: str, note: str | None = None):
	"""Admin anlaşmazlığı çözer (buyer veya seller lehine)."""
	_ensure_logged_in()
	if not _is_admin():
		frappe.throw(_("Yetkisiz"), frappe.PermissionError)
	if in_favor_of not in VALID_RESOLUTIONS:
		frappe.throw(_("Geçersiz çözüm tarafı"))
	doc = frappe.get_doc("Order Dispute", dispute)
	if doc.status in ("Resolved-Buyer", "Resolved-Seller", "Closed"):
		frappe.throw(_("Bu anlaşmazlık zaten çözüldü"))

	doc.in_favor_of = in_favor_of
	doc.status = "Resolved-Buyer" if in_favor_of == "buyer" else "Resolved-Seller"
	doc.resolution_note = (note or "").strip() or None
	doc.resolved_at = now_datetime()
	doc.save(ignore_permissions=True)

	# Listing Review'da rozet bilgisi cache'le
	if doc.related_review:
		frappe.db.set_value(
			"Listing Review",
			doc.related_review,
			"dispute_resolved_in_favor_of",
			in_favor_of,
			update_modified=False,
		)
	frappe.db.commit()
	return {"success": True, "status": doc.status, "in_favor_of": in_favor_of}


@frappe.whitelist(allow_guest=True)
def get_dispute_summary(dispute: str):
	"""Public özet (yorumun altında rozet gösterimi için)."""
	if not dispute or not frappe.db.exists("Order Dispute", dispute):
		return {"exists": False}
	row = frappe.db.get_value(
		"Order Dispute",
		dispute,
		["status", "in_favor_of", "dispute_type", "opened_at", "resolved_at"],
		as_dict=True,
	)
	return {"exists": True, **row}

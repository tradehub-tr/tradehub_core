"""
CRM kayıtlarında `seller` field'ını before_insert hook ile otomatik doldur.

Akış:
  - Eğer doc.seller zaten dolu → bırak
  - Eğer creator user'ı bir Admin Seller Profile'a sahip → kendi profile'ını set
  - Aksi (admin/sales user) → boş bırak (Marketplace Admin havuzu)

Bu modül 7 CRM doctype için ortak `before_insert` hook olarak kullanılır.
"""

import frappe


def _resolve_user_seller(user: str) -> str | None:
	"""User'ın bağlı olduğu aktif Admin Seller Profile name'i — yoksa None."""
	if not user or user in ("Guest", "Administrator"):
		return None
	return frappe.db.get_value(
		"Admin Seller Profile",
		{"user": user, "status": "Active"},
		"name",
	)


def autoset_seller(doc, method=None):
	"""before_insert hook — doc.seller boşsa creator'ın profile'ını set."""
	# DocType'ın `seller` field'ı yoksa skip (custom field henüz install
	# olmamış olabilir).
	try:
		meta = frappe.get_meta(doc.doctype)
		if not meta.has_field("seller"):
			return
	except Exception:
		return

	current = getattr(doc, "seller", None)
	if current:
		return

	user = frappe.session.user
	profile = _resolve_user_seller(user)
	if profile:
		doc.seller = profile


_OWNER_FIELDS = ("lead_owner", "deal_owner")


def autoset_owner(doc, method=None):
	"""before_insert hook — boş kalan lead_owner/deal_owner alanını creator'a set.

	Faz 1'de kullanıcı atama UI'ı yok; kayıt sahipliği otomatik olarak
	oluşturanın e-postasına bağlanır. İleride çok kullanıcılı modele geçilirse
	UserPicker tekrar açılır ve bu hook elle set edilenleri override etmez.
	"""
	user = frappe.session.user
	if not user or user in ("Guest", "Administrator"):
		return
	try:
		meta = frappe.get_meta(doc.doctype)
	except Exception:
		return
	for field in _OWNER_FIELDS:
		if meta.has_field(field) and not getattr(doc, field, None):
			setattr(doc, field, user)

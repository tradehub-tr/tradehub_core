import frappe
from frappe.model.document import Document


class PlatformNotification(Document):
	def before_save(self):
		if self.is_read and not self.read_at:
			self.read_at = frappe.utils.now()


def get_permission_query_conditions(user=None):
	"""
	Frappe DatabaseQuery permission filter — Marketplace Buyer/Seller rolleri
	Desk listing'de SADECE kendi bildirimlerini gorur.

	System Manager: tum kayitlar.
	Diger roller: recipient_user = current_user.

	Bu hook hooks.py'da `permission_query_conditions` map'ine kayitli — Desk
	veya frappe.get_list tarafindan otomatik uygulanir. API endpoint'leri zaten
	manual `recipient_user` filtresi yaptigindan etkilenmez.
	"""
	if not user:
		user = frappe.session.user
	if not user or user == "Guest":
		# Guest kayit goremez; bos string yerine 1=0 dondurelim
		return "1=0"
	if "System Manager" in frappe.get_roles(user):
		return ""
	user_escaped = frappe.db.escape(user)
	return f"`tabPlatform Notification`.`recipient_user` = {user_escaped}"


def has_permission(doc, user=None, permission_type=""):
	"""
	Tek-kayit permission check — Desk form acma/edit.
	System Manager her zaman, digerleri sadece kendi recipient_user kayitlari.
	"""
	if not user:
		user = frappe.session.user
	if not user or user == "Guest":
		return False
	if "System Manager" in frappe.get_roles(user):
		return True
	return getattr(doc, "recipient_user", None) == user

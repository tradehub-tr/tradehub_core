import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

APPROVER_ROLES = {"System Manager", "Marketplace Admin"}


class Brand(Document):
	def validate(self):
		self._normalize_slug()
		self._validate_parent_cycle()
		self._validate_founded_year()
		self._enforce_status_transition()
		self._enforce_brand_owner_policy()
		self._validate_featured_listings()

	def before_insert(self):
		if not _user_is_approver():
			self.status = "Pending Approval"
			self.suggested_by = frappe.session.user
			self.reviewed_by = None
			self.reviewed_at = None
			self.rejection_reason = None
		else:
			if self.status != "Rejected":
				self.status = "Approved"
			if self.status == "Approved" and not self.reviewed_by:
				self.reviewed_by = frappe.session.user
				self.reviewed_at = now_datetime()

	def _normalize_slug(self):
		if not self.slug and self.brand_name:
			self.slug = frappe.scrub(self.brand_name).replace("_", "-")

	def _validate_parent_cycle(self):
		if not self.parent_brand:
			return
		if self.parent_brand == self.name:
			frappe.throw(_("Marka kendisinin üst markası olamaz."))
		visited = {self.name}
		current = self.parent_brand
		while current:
			if current in visited:
				frappe.throw(_("Marka hiyerarşisinde döngü tespit edildi: {0}").format(current))
			visited.add(current)
			current = frappe.db.get_value("Brand", current, "parent_brand")

	def _validate_founded_year(self):
		if self.founded_year:
			from datetime import datetime

			current_year = datetime.now().year
			if self.founded_year < 1800 or self.founded_year > current_year:
				frappe.throw(_("Kuruluş yılı 1800 ile {0} arasında olmalıdır.").format(current_year))

	def _enforce_status_transition(self):
		if self.is_new():
			return

		previous_status = self.get_db_value("status") or "Pending Approval"
		if previous_status == self.status:
			return

		if not _user_is_approver():
			frappe.throw(_("Onay durumunu yalnızca yöneticiler değiştirebilir."))

		allowed = {
			"Pending Approval": {"Approved", "Rejected"},
			"Rejected": {"Pending Approval", "Approved"},
			"Approved": {"Pending Approval", "Rejected"},
		}
		if self.status not in allowed.get(previous_status, set()):
			frappe.throw(_("Geçersiz durum geçişi: {0} → {1}").format(previous_status, self.status))

		if self.status == "Rejected" and not (self.rejection_reason or "").strip():
			frappe.throw(_("Ret için gerekçe zorunludur."))

		self.reviewed_by = frappe.session.user
		self.reviewed_at = now_datetime()
		if self.status != "Rejected":
			self.rejection_reason = None

	def get_db_value(self, fieldname):
		if not self.name:
			return None
		return frappe.db.get_value(self.doctype, self.name, fieldname)

	def _validate_featured_listings(self):
		rows = self.featured_listings or []
		if len(rows) > 8:
			frappe.throw(_("En fazla 8 öne çıkan ürün eklenebilir."))
		seen = set()
		for r in rows:
			if not r.listing:
				continue
			if r.listing in seen:
				frappe.throw(_("Öne çıkan ürünlerde tekrar var: {0}").format(r.listing))
			seen.add(r.listing)

	def _enforce_brand_owner_policy(self):
		"""
		brand_owner ve official_status alanlarını yalnızca admin atayabilir.
		brand_owner satıcısının edit erişimi ise hooks.py'deki has_permission
		handler'ı ile verilir.
		"""
		if self.is_new():
			return

		if _user_is_approver():
			return

		previous_owner = self.get_db_value("brand_owner")
		previous_official = self.get_db_value("official_status")

		# Non-admin users cannot change brand_owner or official_status
		if self.brand_owner != previous_owner:
			frappe.throw(_("Marka sahibini yalnızca yöneticiler atayabilir."))
		if self.official_status != previous_official:
			frappe.throw(_("Resmi durumu yalnızca yöneticiler değiştirebilir."))


def _user_is_approver(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	return bool(roles & APPROVER_ROLES)

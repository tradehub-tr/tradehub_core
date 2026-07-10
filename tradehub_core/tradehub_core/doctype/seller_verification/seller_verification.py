import frappe
from frappe import _
from frappe.model.document import Document


class SellerVerification(Document):
	def validate(self):
		super().validate() if hasattr(super(), "validate") else None
		self._check_duplicate()
		self._enforce_status_rule()

	def _check_duplicate(self):
		"""Aynı (seller, source) çifti için yalnız bir AKTİF kayıt olabilir.

		Engelleyici: Requested/Scheduled/Pending veya süresi geçmemiş Verified.
		Rejected ve süresi dolmuş Verified yeni kaydı ENGELLEMEZ — red sonrası
		yeniden başvuru ve süre dolunca yenileme bu sayede mümkün.
		"""
		if not self.seller or not self.source:
			return
		filters = {"seller": self.seller, "source": self.source}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		# Koşul (status + expiry birleşimi) dict-filter ile ifade edilemiyor;
		# satıcı+kaynak başına birkaç kayıt olduğundan Python'da değerlendirilir.
		rows = frappe.get_all(
			"Seller Verification", filters=filters, fields=["status", "expiry_date"]
		)
		bugun = frappe.utils.getdate()
		for row in rows:
			if row.status in ("Requested", "Scheduled", "Pending"):
				engelleyici = True
			elif row.status == "Verified":
				engelleyici = not row.expiry_date or frappe.utils.getdate(row.expiry_date) >= bugun
			else:  # Rejected
				engelleyici = False
			if engelleyici:
				frappe.throw(
					_("Bu kaynak için zaten aktif bir başvurunuz veya geçerli bir doğrulamanız var."),
					frappe.DuplicateEntryError,
				)

	def _enforce_status_rule(self):
		"""Durum geçiş kuralları.

		- Yeni kayıt: status API tarafından set edilir (Requested veya Pending);
		  burada zorlanmaz, yalnız Pending için belge şartı kontrol edilir.
		- Requested → Scheduled: yalnız Administrator / System Manager.
		- (Requested|Scheduled) → Pending: belge zorunlu (satıcı veya admin).
		- → Verified / Rejected: yalnız Administrator.
		"""
		if self.is_new():
			# API katmanı doğru status'ü set eder; yalnız Pending için belge şartı.
			if self.status == "Pending" and not self.document:
				frappe.throw(_("Onaya göndermek için denetim belgesi gereklidir."))
			return

		old_status = frappe.db.get_value("Seller Verification", self.name, "status")
		if old_status == self.status:
			return

		roles = set(frappe.get_roles(frappe.session.user))
		is_admin = frappe.session.user == "Administrator" or "System Manager" in roles

		if self.status == "Pending" and not self.document:
			frappe.throw(_("Onaya göndermek için denetim belgesi gereklidir."))

		if self.status == "Scheduled" and not is_admin:
			frappe.throw(
				_("Denetim yalnızca yönetici tarafından planlanabilir."),
				frappe.PermissionError,
			)

		if self.status in ("Verified", "Rejected") and frappe.session.user != "Administrator":
			frappe.throw(
				_("Doğrulama durumu yalnızca Administrator tarafından değiştirilebilir."),
				frappe.PermissionError,
			)

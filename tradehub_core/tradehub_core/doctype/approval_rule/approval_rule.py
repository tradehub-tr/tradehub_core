# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Approval Rule — B2B alıcı onay zinciri kuralı.

Bir CRM Organization için amount aralığına göre onay zinciri tanımlar.
Sub-rule (category_filter, supplier_filter) ile daha specifik kurallar
yapılabilir.

Workflow:
  1. Order create edildiğinde `services.approval_workflow.find_matching_rule`
     çağrılır (org + amount + filters match)
  2. Eşleşen rule varsa Order Approval instance create edilir
  3. Approver chain'in L1'i bildirim alır

Detay: docs/yetki/faz-2/03-faz-2-detayli-plan.md §2.5
"""

import frappe
from frappe import _
from frappe.model.document import Document


class ApprovalRule(Document):
	def validate(self) -> None:
		self._validate_organization_scope()
		self._validate_amount_range()
		self._validate_approver_chain()

	def _validate_organization_scope(self) -> None:
		"""D9: Cross-org rule create yasak. Non-admin user'lar sadece kendi
		organizasyonu (+ ataları) için rule yazabilmeli.

		- organization field reqd=1 zaten (JSON'da); ek olarak burada session
		  user'ın bu org'a yetkisi olduğunu doğruluyoruz.
		- System Manager / Marketplace Admin / Compliance Officer / Platform
		  Admin → bypass (her org için rule oluşturabilir).
		"""
		if not self.organization:
			frappe.throw(_("Organization alanı zorunlu."))

		user = frappe.session.user
		if not user or user in ("Guest", "Administrator"):
			return

		roles = set(frappe.get_roles(user))
		# Platform-full bypass (permissions._PLATFORM_FULL_ACCESS_ROLES ile uyumlu)
		platform_full = {
			"System Manager",
			"Marketplace Admin",
			"Platform Super Admin",
			"Platform Admin",
			"Compliance Officer",
		}
		if roles & platform_full:
			return

		# Buyer-side: kendi organization'ı + ataları içinde olmalı
		from tradehub_core.utils.organization_hierarchy import get_ancestors

		user_org = frappe.db.get_value("User", user, "tradehub_parent_organization")
		if not user_org:
			frappe.throw(
				_("Bu organization için Approval Rule oluşturma yetkiniz yok."),
				exc=frappe.PermissionError,
			)
		allowed_orgs = {user_org, *get_ancestors(user_org)}
		if self.organization not in allowed_orgs:
			frappe.throw(
				_("Approval Rule'u sadece kendi organizasyonunuz veya alt birimleri için tanımlayabilirsiniz."),
				exc=frappe.PermissionError,
			)

	def _validate_amount_range(self) -> None:
		"""max_amount > min_amount (eğer set edilmişse)."""
		if self.max_amount and self.max_amount <= (self.min_amount or 0):
			frappe.throw(_("Max Amount, Min Amount'tan büyük olmalı."))

	def _validate_approver_chain(self) -> None:
		"""En az 1 approver olmalı; level değerleri 1 veya 2."""
		if not self.approvers:
			frappe.throw(_("En az bir Approver tanımlanmalı."))

		for row in self.approvers:
			if row.approver_level not in (1, 2):
				frappe.throw(
					_("Approver level 1 veya 2 olmalı; satır {0}: {1}").format(
						row.idx, row.approver_level
					)
				)
			if not row.approver:
				frappe.throw(_("Satır {0}: Approver user boş olamaz.").format(row.idx))

	def get_approvers_at_level(self, level: int) -> list[str]:
		"""Belirli level'daki tüm user listesi (sequence'a göre sıralı)."""
		rows = sorted(
			(r for r in (self.approvers or []) if r.approver_level == level),
			key=lambda r: (r.sequence or 0),
		)
		return [r.approver for r in rows]

	def max_level(self) -> int:
		"""Bu kuralın en yüksek approval level'ı (1 veya 2)."""
		levels = [r.approver_level for r in (self.approvers or [])]
		return max(levels) if levels else 0

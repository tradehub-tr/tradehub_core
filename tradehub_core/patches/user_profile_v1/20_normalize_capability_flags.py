"""Sprint 2.6 (revised) — capability flag invariant.

Yeni kural: can_buy = (kyc_status == 'Verified'),
           can_sell = (kyb_status == 'Verified').
Mevcut User Profile'larda invariant'ı uygular.
"""

import frappe


def execute():
	frappe.db.sql(
		"""
		UPDATE `tabUser Profile`
		SET can_buy = CASE WHEN kyc_status = 'Verified' THEN 1 ELSE 0 END,
		    can_sell = CASE WHEN kyb_status = 'Verified' THEN 1 ELSE 0 END
		"""
	)
	frappe.db.commit()

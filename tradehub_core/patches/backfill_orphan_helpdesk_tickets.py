# Copyright (c) 2024, TR TradeHub and contributors

"""
Eski test/sandbox verisinde agent_group atanmamış HD Ticket'ları
Platform Support team'ine yönlendirir. Permission query her ticket'ın
bir team'e bağlı olmasını gerektirir; aksi halde hiçbir ajan göremez.

Idempotent: yalnızca agent_group NULL olanları günceller.
"""

import frappe

from tradehub_core.utils.helpdesk_routing import ensure_platform_support_team


def execute():
	team = ensure_platform_support_team()
	# Bulk update — direkt SQL, ORM tek tek save'den çok daha hızlı
	frappe.db.sql(
		"""
		UPDATE `tabHD Ticket`
		SET agent_group = %s
		WHERE agent_group IS NULL OR agent_group = ''
		""",
		(team,),
	)
	frappe.db.commit()

# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-037: Lojistik Role Profile'larını DB'ye yaz (idempotent).

Neden gerekli:
	TUR-103'te `fixtures/role_profile.json` dosyasına 3 lojistik Role Profile
	eklendi, ama bu dosyayı DB'ye taşıyan tek mekanizma
	`v15_5_4_sync_role_profiles` patch'iydi ve o patch Patch Log'da kayıtlı
	olduğu için tekrar çalışmadı. `hooks.py` `fixtures` listesinde de
	`Role Profile` yok. Sonuç: 3 profil hiç oluşmadı.

	Profiller olmadığı için `v15_tur103_seed_logistics_capabilities` de
	grant'ları sessizce atladı — `shipment.cancel`, `shipment.split`,
	`carrier_credential.manage` ve `view.carrier_secret` capability'leri
	hiçbir role bağlanmadı. Grant backfill'i LOG-038'de.
"""

from __future__ import annotations

import frappe

from tradehub_core.setup.seed_role_profiles import seed_role_profiles_by_name

LOGISTICS_ROLE_PROFILES: tuple[str, ...] = (
	"Logistics Manager",
	"Logistics Operator",
	"Carrier Integration Manager",
)


def execute() -> dict:
	"""3 lojistik Role Profile'ını fixture'tan okuyup oluşturur."""
	result = seed_role_profiles_by_name(LOGISTICS_ROLE_PROFILES)

	# Sessiz atlama yasak — eksik kalan her şey görünür olmalı (bkz.
	# docs/LOGISTICS-ARCHITECTURE.md §6.1)
	if result["missing_in_fixture"]:
		frappe.log_error(
			f"role_profile.json'da bulunamayan profiller: {result['missing_in_fixture']}",
			"v15_log037_seed_logistics_role_profiles",
		)
	if result["missing_roles"]:
		frappe.log_error(
			f"DB'de olmayan roller nedeniyle eksik atanan profiller: {result['missing_roles']}",
			"v15_log037_seed_logistics_role_profiles",
		)

	frappe.db.commit()
	return result

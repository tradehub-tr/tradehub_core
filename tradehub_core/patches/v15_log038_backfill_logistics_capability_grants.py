# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-038: Lojistik capability grant'larını backfill et (idempotent).

Neden gerekli:
	`v15_tur103_seed_logistics_capabilities` çalıştığında lojistik Role
	Profile'ları DB'de yoktu (bkz. LOG-037), bu yüzden 3 rol profilinin
	grant'larını atladı ve yalnız `Seller Full Access` satırları oluştu.
	Patch Log kaydı nedeniyle TUR-103 tekrar çalışmayacağı için eksik
	grant'lar bu patch ile tamamlanır.

	Grant matrisi tek kaynaktan okunur (`v15_tur103...GRANTS`) — kopyalanmaz.
"""

from __future__ import annotations

import frappe

from tradehub_core.patches.v15_tur103_seed_logistics_capabilities import (
	GRANTS,
	seed_capability_grants,
)


def execute() -> dict:
	"""TUR-103 grant matrisindeki eksik kayıtları tamamlar."""
	result = seed_capability_grants(GRANTS)

	# Bu noktada LOG-037 çalışmış olmalı; hâlâ eksik profil varsa gerçek bir
	# sorun vardır — sessiz geçme.
	if result["missing_profiles"]:
		frappe.log_error(
			f"Backfill sonrası hâlâ eksik Role Profile: {result['missing_profiles']}",
			"v15_log038_backfill_logistics_capability_grants",
		)
	if result["missing_capabilities"]:
		frappe.log_error(
			f"TH Capability Registry'de bulunamayan capability: {result['missing_capabilities']}",
			"v15_log038_backfill_logistics_capability_grants",
		)

	frappe.db.commit()
	return result

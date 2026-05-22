# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 1.4 — Audit Log public API.

Üç tür log:
  - Authorization Decision Log: her L0/L1/L2/L3 karar
  - Role Change Log: rol atama, davet, pasifleştirme
  - Permission Override Log: ignore_permissions=True veya admin bypass

Kullanım:

    from tradehub_core.audit import log_decision, log_role_change, log_override

    log_decision(
        actor="seller-a@x.com",
        action="listing.create",
        decision="DENY",
        rule_id="entitlement.quota.max_products",
        layer="L0",
    )

Retention: 90 gün sıcak (Frappe DB), 10 yıl arşiv (S3/MinIO — Faz 3'te encryption).

Detay: docs/yetki/01-karar-dosyasi.md §4
"""

from tradehub_core.audit.log import (
	DECISION_ALLOW,
	DECISION_ALLOW_PENDING,
	DECISION_DENY,
	DECISION_ERROR,
	DECISION_FIELD_MASKED,
	LAYER_L0,
	LAYER_L1,
	LAYER_L2,
	LAYER_L3,
	SEVERITY_HIGH,
	SEVERITY_LOW,
	SEVERITY_NORMAL,
	log_decision,
	log_override,
	log_role_change,
)

__all__ = [
	"DECISION_ALLOW",
	"DECISION_ALLOW_PENDING",
	"DECISION_DENY",
	"DECISION_ERROR",
	"DECISION_FIELD_MASKED",
	"LAYER_L0",
	"LAYER_L1",
	"LAYER_L2",
	"LAYER_L3",
	"SEVERITY_HIGH",
	"SEVERITY_LOW",
	"SEVERITY_NORMAL",
	"log_decision",
	"log_override",
	"log_role_change",
]

"""Birleşik yetkilendirme (PDP) paketi — Faz 1.

Tek karar noktası: `authorize(principal, action, resource, context)`.
Karar sırası (Cedar/IAM ilhamı, fail-closed):
    L1 HARD DENY → L2 GUARDRAIL → L3 RELATIONSHIP(ReBAC) ∪ ROLE(RBAC) → L4 DEFAULT DENY

Bkz. ReBAC-ABAC-Gelistirme-Faz-Plani.md · Faz 1.
"""

from tradehub_core.authz.pdp import Decision, authorize

__all__ = ["Decision", "authorize"]

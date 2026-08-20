#!/usr/bin/env bash
#
# Faz 0 — Yetkilendirme (RBAC/ReBAC/ABAC) test kapısı.
#
# Bu modüller frappe'yi kendi içinde stub'lar → gerçek bir Frappe/DB kurulumu
# GEREKTİRMEZ. Sadece `python3` yeterli; CI'da altyapısız koşar ve authz
# regresyonlarında build'i KIRMASI amaçlanır (CI-blocking gate).
#
# Kullanım:
#   bash scripts/run_authz_tests.sh
# Çıkış kodu: herhangi bir modül fail/error → 1 (CI kırmızı).
set -uo pipefail

cd "$(dirname "$0")/.." || exit 2

# Pure-stub (frappe'siz koşan) authz-ilgili test modülleri.
# Not: test_store_subscription_isolation gerçek frappe gerektirir → bench ile
# ayrıca koşulmalı (CI stub kapsamı dışında).
MODULES=(
	test_pdp
	test_guardrail
	test_enforcement
	test_break_glass
	test_entitlement
	test_entitlement_snapshot
	test_plan_feature_sync
	test_phase1_integration
	test_phase2_integration
	test_rebac_doctype_permissions
	test_abac_context
	test_abac_gate_enforcement
	test_shadow_observe
	test_rebac_enforce
	test_authorization_simulator
	test_authz_simulator_security
	test_tenant_isolation
	test_delegation
	test_delegation_security
	test_seller_capabilities
	test_procurement_tenant_security
	test_buyer_team_role_security
	test_rebac_client
	test_tuple_sync
	test_enforce_readiness
	test_approval_workflow
	test_rebac_approval_gating
	test_anomaly_detector
	test_audit
	test_audit_signatures
	test_audit_hashchain
	test_pii
	test_pii_compliance
	test_rebac_abac_e2e
	test_owner_transfer_security
	test_cross_app_link_resolution
	test_sub_users
	test_store_subscription_perms
	test_subscription_upgrade_security
	test_review_abtest_bola
	test_cart_price_tampering
	test_get_customer_detail_pii
	test_payment_pii_security
	test_mobile_jwt_secret
	test_organization_hierarchy
	test_authz_regression
	test_faz13_guest_surface
	test_payment_iban_permlevel
	test_privacy_audit
)

fail=0
for m in "${MODULES[@]}"; do
	if python3 -m unittest "tradehub_core.tests.$m" >/tmp/authz_$m.log 2>&1; then
		printf '  \033[32mPASS\033[0m %s\n' "$m"
	else
		printf '  \033[31mFAIL\033[0m %s\n' "$m"
		tail -20 "/tmp/authz_$m.log"
		fail=1
	fi
done

if [ "$fail" -ne 0 ]; then
	echo "AUTHZ TEST GATE: FAIL"
	exit 1
fi
echo "AUTHZ TEST GATE: OK (${#MODULES[@]} modül)"

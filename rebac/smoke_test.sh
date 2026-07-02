#!/usr/bin/env bash
# FAZ 2.2 — OpenFGA smoke test
#
# Model deploy edildikten sonra basit bir tuple yaz + check işlemleri yap.
# Beklenen: tüm assertion'lar geçer.
#
# Kullanım: make rebac-smoke

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# rebac/ artık tradehub_core altında → proje kökü iki seviye yukarı.
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/docker/.env"

# .env'i yükle
if [ ! -f "$ENV_FILE" ]; then
	echo "✗ HATA: $ENV_FILE yok." >&2
	exit 1
fi
set -a; source "$ENV_FILE"; set +a

BASE_URL="${REBAC_PUBLIC_URL:-http://localhost:8090}"
API_KEY="${REBAC_API_KEY:-dev-only-key-change-in-production}"
STORE_ID="${REBAC_STORE_ID:-}"

if [ -z "$STORE_ID" ]; then
	echo "✗ HATA: REBAC_STORE_ID yok. Önce 'make rebac-model-deploy' çalıştır." >&2
	exit 1
fi

# Yardımcı: HTTP çağrısı + JSON döndür
_curl() {
	curl -fsS -H "Authorization: Bearer $API_KEY" "$@"
}

# ----------------------------------------------------------------------------
# 1) Tuple yaz: (buyer_org:smoke-acme, member, user:smoke-ayse@x.com)
# ----------------------------------------------------------------------------
echo "→ TEST 1: Tuple yaz (member ilişkisi)..."
_curl -H "Content-Type: application/json" \
	-d '{
		"writes": {
			"tuple_keys": [
				{
					"user": "user:smoke-ayse@x.com",
					"relation": "member",
					"object": "buyer_org:smoke-acme"
				}
			]
		}
	}' \
	"$BASE_URL/stores/$STORE_ID/write" > /dev/null
echo "✓ Tuple yazıldı"

# ----------------------------------------------------------------------------
# 2) Check: Ayşe ACME'nin üyesi mi? → ALLOW
# ----------------------------------------------------------------------------
echo "→ TEST 2: Check (Ayşe member mı?)..."
RESULT=$(_curl -H "Content-Type: application/json" \
	-d '{
		"tuple_key": {
			"user": "user:smoke-ayse@x.com",
			"relation": "member",
			"object": "buyer_org:smoke-acme"
		}
	}' \
	"$BASE_URL/stores/$STORE_ID/check" | jq -r '.allowed')

if [ "$RESULT" = "true" ]; then
	echo "✓ ALLOWED (beklenen)"
else
	echo "✗ FAIL: Beklenen 'true', alınan '$RESULT'" >&2
	exit 1
fi

# ----------------------------------------------------------------------------
# 3) Negative check: Mehmet ACME'nin üyesi mi? → DENY
# ----------------------------------------------------------------------------
echo "→ TEST 3: Negative check (Mehmet member değil)..."
RESULT=$(_curl -H "Content-Type: application/json" \
	-d '{
		"tuple_key": {
			"user": "user:smoke-mehmet@x.com",
			"relation": "member",
			"object": "buyer_org:smoke-acme"
		}
	}' \
	"$BASE_URL/stores/$STORE_ID/check" | jq -r '.allowed')

if [ "$RESULT" = "false" ]; then
	echo "✓ DENIED (beklenen)"
else
	echo "✗ FAIL: Beklenen 'false', alınan '$RESULT'" >&2
	exit 1
fi

# ----------------------------------------------------------------------------
# 4) Türetilmiş ilişki: can_view (member üzerinden)
# ----------------------------------------------------------------------------
echo "→ TEST 4: Türetilmiş can_view (Ayşe ACME'yi görür)..."
RESULT=$(_curl -H "Content-Type: application/json" \
	-d '{
		"tuple_key": {
			"user": "user:smoke-ayse@x.com",
			"relation": "can_view",
			"object": "buyer_org:smoke-acme"
		}
	}' \
	"$BASE_URL/stores/$STORE_ID/check" | jq -r '.allowed')

if [ "$RESULT" = "true" ]; then
	echo "✓ can_view: ALLOWED (member ⟹ can_view)"
else
	echo "✗ FAIL: can_view türetilmesi çalışmadı" >&2
	exit 1
fi

# ----------------------------------------------------------------------------
# 5) Cleanup: smoke tuple'ı sil
# ----------------------------------------------------------------------------
echo "→ TEST 5: Cleanup..."
_curl -H "Content-Type: application/json" \
	-d '{
		"deletes": {
			"tuple_keys": [
				{
					"user": "user:smoke-ayse@x.com",
					"relation": "member",
					"object": "buyer_org:smoke-acme"
				}
			]
		}
	}' \
	"$BASE_URL/stores/$STORE_ID/write" > /dev/null
echo "✓ Cleanup tamam"

echo ""
echo "========================================"
echo "✓ TÜM SMOKE TESTLER GEÇTİ (5/5)"
echo "========================================"

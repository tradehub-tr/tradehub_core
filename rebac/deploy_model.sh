#!/usr/bin/env bash
# FAZ 2.2 — OpenFGA model deploy script
#
# 1. Store oluştur (yoksa)
# 2. tradehub_core/rebac/model.fga'i upload et
# 3. STORE_ID + MODEL_ID'yi docker/.env'e yaz
#
# Kullanım: make rebac-model-deploy
# Bağımlılık: curl, jq (apt install jq)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# rebac/ artık tradehub_core altında (istoc.com/tradehub_core/rebac) → proje kökü iki seviye yukarı.
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/docker/.env"
MODEL_FILE="$SCRIPT_DIR/model.fga"

# .env'i yükle
if [ ! -f "$ENV_FILE" ]; then
	echo "✗ HATA: $ENV_FILE yok." >&2
	exit 1
fi
# shellcheck source=/dev/null
set -a; source "$ENV_FILE"; set +a

# Default'lar
BASE_URL="${REBAC_PUBLIC_URL:-http://localhost:8090}"
API_KEY="${REBAC_API_KEY:-dev-only-key-change-in-production}"
STORE_NAME="${REBAC_STORE_NAME:-tradehub}"

# Bağımlılık kontrolü
if ! command -v jq > /dev/null 2>&1; then
	echo "✗ HATA: 'jq' gerekli. Yükle: sudo apt install jq" >&2
	exit 1
fi
if [ ! -f "$MODEL_FILE" ]; then
	echo "✗ HATA: $MODEL_FILE yok." >&2
	exit 1
fi

# Health check
echo "→ OpenFGA health check..."
if ! curl -fs "$BASE_URL/healthz" > /dev/null; then
	echo "✗ HATA: OpenFGA $BASE_URL adresinde erişilemez. 'make rebac-up' çalıştır." >&2
	exit 1
fi

# ----------------------------------------------------------------------------
# 1) STORE bul veya oluştur
# ----------------------------------------------------------------------------
echo "→ Store '$STORE_NAME' aranıyor..."
STORE_LIST=$(curl -fsS -H "Authorization: Bearer $API_KEY" "$BASE_URL/stores")
STORE_ID=$(echo "$STORE_LIST" | jq -r --arg name "$STORE_NAME" '.stores[] | select(.name == $name) | .id' | head -1)

if [ -z "$STORE_ID" ] || [ "$STORE_ID" = "null" ]; then
	echo "→ Store yok, oluşturuluyor..."
	STORE_ID=$(curl -fsS -H "Authorization: Bearer $API_KEY" \
		-H "Content-Type: application/json" \
		-d "{\"name\": \"$STORE_NAME\"}" \
		"$BASE_URL/stores" | jq -r '.id')
	echo "✓ Store oluşturuldu: $STORE_ID"
else
	echo "✓ Store zaten var: $STORE_ID"
fi

# ----------------------------------------------------------------------------
# 2) MODEL upload
# ----------------------------------------------------------------------------
# OpenFGA REST API doğrudan .fga DSL'i kabul etmez — JSON formatı gerekir.
# 'fga' CLI ile dönüştürme yapacağız. Eğer yoksa basit JSON template kullan.

echo "→ Model upload ediliyor..."

# fga CLI ile JSON'a çevir (varsa)
if command -v fga > /dev/null 2>&1; then
	MODEL_JSON=$(fga model transform --file "$MODEL_FILE")
else
	# fga CLI yoksa, container içindekini kullan
	echo "→ fga CLI yok, container içinden transform yapılıyor..."
	MODEL_DSL=$(cat "$MODEL_FILE")
	# Container içinde 'fga' yok (run image'ı), bu yüzden REST API yerine
	# manuel JSON template'i kullanacağız. Daha temizi: 'fga' CLI install et.
	echo "✗ HATA: 'fga' CLI gerekli. Yükle:" >&2
	echo "    curl -L https://github.com/openfga/cli/releases/latest/download/fga_linux_amd64.tar.gz | tar xz" >&2
	echo "    sudo mv fga /usr/local/bin/" >&2
	echo "" >&2
	echo "Veya manuel JSON model.json üret ve script'i güncelle." >&2
	exit 1
fi

# Upload — POST /stores/<store_id>/authorization-models
MODEL_RESPONSE=$(curl -fsS -H "Authorization: Bearer $API_KEY" \
	-H "Content-Type: application/json" \
	-d "$MODEL_JSON" \
	"$BASE_URL/stores/$STORE_ID/authorization-models")
MODEL_ID=$(echo "$MODEL_RESPONSE" | jq -r '.authorization_model_id')

if [ -z "$MODEL_ID" ] || [ "$MODEL_ID" = "null" ]; then
	echo "✗ Model upload başarısız: $MODEL_RESPONSE" >&2
	exit 1
fi
echo "✓ Model upload edildi: $MODEL_ID"

# ----------------------------------------------------------------------------
# 3) .env'e yaz
# ----------------------------------------------------------------------------
echo "→ docker/.env güncelleniyor..."

# REBAC_STORE_ID ve REBAC_MODEL_ID satırlarını güncelle veya ekle
update_env_var() {
	local key="$1"
	local value="$2"
	if grep -q "^${key}=" "$ENV_FILE"; then
		# Var, güncelle (sed in-place — mac/linux uyumlu)
		if [[ "$OSTYPE" == "darwin"* ]]; then
			sed -i '' "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
		else
			sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
		fi
	else
		# Yok, ekle
		echo "${key}=${value}" >> "$ENV_FILE"
	fi
	# Yorum satırı (# REBAC_STORE_ID=) varsa kaldır
	if [[ "$OSTYPE" == "darwin"* ]]; then
		sed -i '' "/^# ${key}=$/d" "$ENV_FILE"
	else
		sed -i "/^# ${key}=$/d" "$ENV_FILE"
	fi
}

update_env_var "REBAC_STORE_ID" "$STORE_ID"
update_env_var "REBAC_MODEL_ID" "$MODEL_ID"

echo ""
echo "========================================"
echo "✓ Deploy tamamlandı"
echo "========================================"
echo "STORE_ID:  $STORE_ID"
echo "MODEL_ID:  $MODEL_ID"
echo "Playground: http://localhost:3001/playground"
echo ""
echo "Smoke test: make rebac-smoke"

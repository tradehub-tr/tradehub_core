# tradehub_core/rebac — OpenFGA ReBAC Sidecar

> **Faz 2.2 çıktısı.** TradeHub'ın B2B alıcı hiyerarşisi ve çok katmanlı onay zinciri için OpenFGA tabanlı sidecar.

---

## İçindekiler

- `model.fga` — OpenFGA authorization model (DSL)
- `deploy_model.sh` — Model upload + .env güncelleme
- `smoke_test.sh` — 5 adımlı smoke test
- `README.md` — bu dosya

---

## Hızlı Başlangıç

### 1. Önkoşullar

```bash
# fga CLI (OpenFGA komut satırı)
curl -L https://github.com/openfga/cli/releases/latest/download/fga_linux_amd64.tar.gz | tar xz
sudo mv fga /usr/local/bin/

# jq (JSON parsing)
sudo apt install jq
```

### 2. Sidecar'ı başlat

```bash
cd /home/bora/Masaüstü/istoc.com
make rebac-up
```

Beklenen çıktı:
```
✓ OpenFGA HEALTHY — http://localhost:8090
✓ Playground UI — http://localhost:3001/playground
```

### 3. Model'i deploy et

```bash
make rebac-model-deploy
```

Bu:
- Store oluşturur (yoksa)
- `model.fga` dosyasını upload eder
- `docker/.env`'e `REBAC_STORE_ID` + `REBAC_MODEL_ID` yazar

### 4. Smoke test

```bash
make rebac-smoke
```

Beklenen: `✓ TÜM SMOKE TESTLER GEÇTİ (5/5)`

---

## Operasyon

### Container yönetimi

```bash
make rebac-up          # başlat
make rebac-down        # durdur
make rebac-restart     # restart
make rebac-logs        # logs takip
```

### Backup

```bash
make rebac-backup
# Çıktı: backups/rebac-pg-YYYYMMDD-HHMMSS.sql.gz
```

**Production cron (önerilen):**

```cron
# /etc/cron.d/tradehub-rebac-backup
0 3 * * * bora cd /home/bora/Masaüstü/istoc.com && make rebac-backup >> /var/log/tradehub-rebac-backup.log 2>&1

# Eski yedekleri sil (30 günden eski)
0 4 * * * bora find /home/bora/Masaüstü/istoc.com/backups -name 'rebac-pg-*.sql.gz' -mtime +30 -delete
```

### Restore (acil durum)

```bash
# Container durdur
make rebac-down
docker volume rm docker_rebac-pgdata  # ⚠ DİKKAT: tüm tuple silinir

# Container baştan başlat
make rebac-up

# Yedek geri yükle
gunzip < backups/rebac-pg-20260521-030001.sql.gz | \
  docker exec -i docker-rebac-db-1 psql -U openfga openfga

# Model'i tekrar deploy et (gerekirse)
make rebac-model-deploy
```

---

## Mimari

```
┌──────────────────────────┐                ┌──────────────────────┐
│  Frappe Backend          │                │  OpenFGA Sidecar     │
│  (tradehub_core)         │  HTTP / 8090   │  (rebac-sidecar)     │
│                          ├───────────────►│                      │
│  services/rebac_client.py│                │  - /healthz          │
│                          │                │  - /stores/.../check │
└──────────────────────────┘                │  - /stores/.../write │
                                            │  - /stores/.../list  │
                                            └──────────┬───────────┘
                                                       │
                                                       │ Postgres 15
                                                       ▼
                                            ┌──────────────────────┐
                                            │  rebac-db            │
                                            │  (tuple store)       │
                                            └──────────────────────┘
```

---

## Network Erişimi

| Endpoint | Host (dev) | Container Internal | Production |
|---|---|---|---|
| HTTP API | localhost:8090 | rebac-sidecar:8080 | Internal-only |
| Playground UI | localhost:3001/playground | rebac-sidecar:3000 | Kapalı |
| Postgres | — (sadece internal) | rebac-db:5432 | Sadece sidecar |

**Production güvenlik:**
- `docker-compose.yml`'da rebac-sidecar `ports:` bloğunu kaldır → sadece internal
- `OPENFGA_PLAYGROUND_ENABLED: "false"`
- `OPENFGA_AUTHN_METHOD: oidc` (preshared yerine — OIDC ile)

---

## Model Geliştirme

### Model dosyasını edit ettikten sonra

1. `tradehub_core/rebac/model.fga` düzenle
2. `fga model validate --file tradehub_core/rebac/model.fga` (lokalde)
3. `make rebac-model-deploy` — yeni version upload (eski version'lar saklanır)
4. `make rebac-smoke` — regression
5. `.env`'deki `REBAC_MODEL_ID` otomatik güncellenir

### Authorization Model Versioning

OpenFGA her model upload'unu **yeni versiyon** olarak saklar — eski tuple'lar eski model ile uyumlu kalır. Geriye dönük uyumluluk için:
- Yeni relation ekleme: **güvenli**
- Type ekleme: **güvenli**
- Relation silme: **kırılgan** (eski tuple'lar invalid olur)

---

## Monitoring

OpenFGA Prometheus metrics endpoint'i exposed: `http://localhost:8090/metrics`

Önemli metrikler:
- `openfga_check_request_duration_seconds` — check latency p99
- `openfga_check_request_total{result="allow|deny"}` — karar sayıları
- `openfga_datastore_query_duration_seconds` — Postgres query süresi

---

## Sorun Giderme

### "Health check failed"
```bash
make rebac-logs
# Postgres ulaşılamıyor mu? → rebac-db ayakta mı?
docker ps | grep rebac
```

### "Model upload failed: invalid DSL"
```bash
# Lokalde validate
fga model validate --file tradehub_core/rebac/model.fga
```

### Tuple store dolu / Postgres disk dolu
```bash
# Disk kullanımı
docker exec docker-rebac-db-1 du -sh /var/lib/postgresql/data

# Tuple sayısı (Postgres'e direkt query)
docker exec docker-rebac-db-1 psql -U openfga -d openfga \
  -c "SELECT count(*) FROM tuple;"
```

---

## Sonraki Adımlar (Faz 2.3+)

- Faz 2.3 — `tradehub_core/services/rebac_client.py` (Frappe ↔ sidecar HTTP)
- Faz 2.4 — Buyer team management + Organization hiyerarşisi
- Faz 2.5 — Çok katmanlı onay zinciri (Approval Rule + Order Approval)
- Faz 2.6 — ABAC conditions runtime entegrasyonu

Detay: `docs/yetki/faz-2/03-faz-2-detayli-plan.md`

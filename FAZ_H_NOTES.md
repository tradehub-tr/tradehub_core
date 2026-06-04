# Faz H — Polish Notları

Bu belge Faz H kapsamında **otomasyon dışı bırakılan** maddeleri ve gelecek
sprint'lere ertelenmiş işleri kayıt eder.

## ✅ Faz H kapsamında uygulananlar

| ID | Maden | Durum |
|---|---|---|
| H.1 | ENTERPRISE `is_public=0` DB reset | Patch `v15_6_17_reset_enterprise_public_flag` |
| H.2 | Subscription Plan rich text alanları XSS sanitize | `subscription_plan.py:_sanitize_rich_text_fields` (description, short_tagline, badge_label, cta_label) |
| H.3 | rule_id naming tutarlılığı | `auth.admin_module_policy` → `auth.admin_module_policy_toggle` |
| H.4 | `order.total=None` defansif yorum | `abac_context.py:build_order_context` 5-satır açıklama |
| H.5 | Protected module e2e test | `test_sprint6_rbac.test_protected_module_cannot_be_hidden_via_policy` |

## ⚠ Kullanıcı tarafında **manuel** yapılması gerekenler

### D16 — `bench export-fixtures` plan fixture güncelleme
Fixture `subscription_plan.json` aylık/yıllık fiyatları eskimiş (örn. fixture
`monthly_price: 399` vs DB `39`). Yeni site kurulumlarında yanlış fiyat
seed edilecek. Çözüm:

```bash
docker exec docker-backend-1 bench --site dev.localhost export-fixtures
```

Bu komut DB'deki güncel `Subscription Plan` kayıtlarını fixture dosyasına
yazar. Sonra commit (kullanıcı kararı).

### G.4 — ReBAC sidecar production deploy
ReBAC sidecar `docker-rebac-sidecar` container'ı dev env'de yok. Production
deploy adımı:
1. `docker-compose.yml`'a sidecar servisi
2. Environment: `REBAC_BASE_URL`, `REBAC_STORE_ID`, `REBAC_API_KEY`
3. Sidecar healthz endpoint scheduler bağlama

Bu DevOps işi — kod tarafında ek değişiklik gerekmiyor (fail-closed mevcut).

## 📋 Gelecek sprint'lere ertelenen (deferred)

### D18 — Pricing UI gelişmiş özellikler
- Multi-currency pricing (her plan birden fazla currency'de fiyat)
- Discount/promo kupon alanı
- Billing cycle: weekly / quarterly / lifetime
- Custom trial period

**Tahmini efor:** 2-3 sprint (backend + UI + storefront)

### D22 — Dokümantasyon güncellemesi
- `docs/yetki/*.md` içinde "Audit Decision Log" referansları → `Authorization Decision Log` (gerçek doctype adı)
- Workflow orchestrator (`tradehub_core.workflow`) kullanım kılavuzu — Faz G.3 scaffold
- Faz A-H için CHANGELOG

## 🔍 Faz D bulguları — Kapatılma durumu

| Bulgu | Faz | Durum |
|---|---|---|
| 🔴 D1 update_pricing_plan REPLACE bug | E.1 | ✅ MERGE semantiği |
| 🔴 D2 update_plan_capabilities REPLACE bug | E.1 | ✅ Aynı helper |
| 🔴 D3 Self-service plan upgrade yok | E.3 | ✅ `subscription.upgrade_subscription_plan` |
| 🔴 D4 max_orders_per_month=0 | E.4 | ✅ -1 (sınırsız) |
| 🔴 D5 _record() SKIP→ALLOW fail-open | G.1 | ✅ positive-affirm invariant |
| 🔴 D6 list_assignable_roles SM şeffaf | F.1 | ✅ filter |
| 🔴 D7 protected module seed eksik | F.2 | ✅ 6 modül seed |
| 🔴 D8 currency-blind tier | G.2 | ✅ EUR normalize |
| 🟠 D9 deprecated key kabul | E.2 | ✅ reject |
| 🟠 D10 capability registry sığ | — | Tasarım kararı (entitlement layer ayrı) |
| 🟠 D11 MA pricing tampering | F.4 | ✅ field separation |
| 🟠 D12 plan değişikliği audit yok | E.3 | ✅ subscription.upgrade HIGH ADL |
| 🟠 D13 sidecar dev'de yok | G.4 | Deploy (deferred) |
| 🟠 D14 admin_role_crud object alanları | F.3 | ✅ Role Profile + name |
| 🟠 D15 ADL ismi drift | H.6 | Dokümantasyon (deferred) |
| 🟡 D16 fixture vs DB drift | H.6 | Manuel `bench export-fixtures` |
| 🟡 D17 ENTERPRISE is_public sızıntı | H.1 | ✅ patch reset |
| 🟡 D18 multi-currency vs. | H.6 | Sprint backlog |
| 🟡 D19 description XSS | H.2 | ✅ sanitize_html |
| 🟡 D20 rule_id naming | H.3 | ✅ _toggle suffix |
| 🟡 D21 order.total=None implicit | H.4 | ✅ açıklayıcı yorum |
| 🟡 D22 doctype isim dokümantasyon | H.6 | Deferred |
| 🟡 D23 protected module runtime test | H.5 | ✅ e2e test |

**Toplam:** 19/23 kapatıldı (4 deferred/manual: D10, D13, D16, D18, D22 — bunların 2'si manuel komut, 2'si gelecek sprint, 1'i tasarım kararı).

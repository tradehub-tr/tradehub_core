---
paths:
  - "**/*.py"
  - "**/*.json"
---

# Bench komutları + Frappe v15 referansları

## 1. Bench günlük komutları

```bash
# Temel
bench --site dev.localhost migrate
bench --site dev.localhost console
bench --site dev.localhost clear-cache

# Tek doctype'ı yeniden yükle (custom field uyumu)
bench --site dev.localhost reload-doc tradehub_core doctype listing

# Test
bench --site dev.localhost run-tests --app tradehub_core
bench --site dev.localhost run-tests --doctype "Listing"

# Build (asset bundling)
bench build --app tradehub_core

# Lint
ruff check tradehub_core/
ruff format --check tradehub_core/
```

## 2. Docker container'da bench çalıştırma (LOCAL dev)

> Bu repo `docker-compose.yml` ile çalışıyor. Bench komutları **container içinde** çalışır.

```bash
# Bench komutu için docker exec deseni
docker exec istocc-dev-backend-1 bench --site tradehub.localhost migrate
docker exec istocc-dev-backend-1 bench --site tradehub.localhost reload-doc tradehub_core doctype listing
docker exec istocc-dev-backend-1 bench --site tradehub.localhost clear-cache

# DocType JSON değişiklikleri için:
docker exec istocc-dev-backend-1 bench --site tradehub.localhost migrate
```

> ⚠ **Local dev'de `/app/console` veya Frappe Desk UI önerme** — bu projede yok. Bench komutları doğrudan `docker exec` ile.

## 3. Press API (production deploy)

Production'da Frappe Cloud Press API üzerinden:

- `press.cronbi.com/api/method/run_doc_method` (schedule_update, migrate)
- Beta → RC → PROD geçişi kök `.claude/CLAUDE.md` §2'de.

## 4. Frappe v15 dokümantasyon referansları

| Konu | URL |
|---|---|
| Frappe Hooks reference | https://docs.frappe.io/framework/user/en/python-api/hooks |
| Frappe Database API | https://docs.frappe.io/framework/user/en/api/database |
| Frappe Query Builder (qb) | https://docs.frappe.io/framework/v15/user/en/api/query-builder |
| Frappe v15 release notes | https://frappeframework.com/version-15 |
| ERPNext Coding Standards | https://github.com/frappe/erpnext/wiki/Coding-Standards |
| ERPNext Code Security Guidelines | https://github.com/frappe/erpnext/wiki/Code-Security-Guidelines |
| ERPNext Performance Tuning | https://github.com/frappe/erpnext/wiki/ERPNext-Performance-Tuning |
| Migrating to v15 | https://github.com/frappe/frappe/wiki/Migrating-to-version-15 |

## 5. Sık karşılaşılan komutlar

```bash
# Yeni doctype eklediğin sonra
docker exec istocc-dev-backend-1 bench --site tradehub.localhost migrate

# Permission değişikliklerini yansıt
docker exec istocc-dev-backend-1 bench --site tradehub.localhost clear-cache

# Patch ekledikten sonra tek seferlik
docker exec istocc-dev-backend-1 bench --site tradehub.localhost migrate

# Custom app'i yeniden install (development reset)
docker exec istocc-dev-backend-1 bench --site tradehub.localhost reinstall

# Production worker restart (canlıda)
bench restart  # Sunucu B'de
```

# TradeHub Core — Proje Rehberi

Bu dosya kısa orkestrasyon kurallarını içerir. Detaylı kurallar `tradehub_core/.claude/rules/` altında path-scoped olarak duruyor — Claude bir `.py` dosyasına dokunduğunda otomatik yüklenir.

> Bu belge gerçek dizin ağacını, bağımlılıkları ve ölçülmüş kod borçlarını yansıtır — **kod ile çelişirse bu belge değil, kod doğrudur**: gördüğünü kayıt et, çelişkiyi flag et, gerekirse bu belgeyi güncelle.

---

## 1. Proje kimliği

| Alan | Değer |
|---|---|
| Domain | B2B Marketplace (İstoç Ticaret Merkezi tabanlı) |
| Tip | Frappe custom app — backend + DocType + REST API + DocType formları |
| Framework | Frappe v15 (`>=15.0.0,<16.0.0`) + ERPNext v15 |
| Python | `requires-python = ">=3.10"` (production runtime: 3.12.3) |
| ORM/DB | MariaDB 10.6+ (Frappe ORM + frappe.qb / frappe.db) |
| Cache/Queue | Redis (cache + queue + socketio) |
| Lint | Ruff (line-length 110, target-version py310, **tab indent**) |
| Build | flit_core (pyproject.toml dinamik versiyon) |
| Default branch | `version-15` (`main` değil!) |
| Tek runtime bağımlılığı | `frappe` (requirements.txt) |
| Mimari yaklaşım | **Tek monolitik app** — tüm modüller `tradehub_core/` altında |

> ⚠️ **Geçmiş tasarımla farkı:** Eski belgelerde 7 ayrı app (catalog, commerce, seller, logistics, marketing, compliance) bahsi geçiyordu. **Bugün** kod tek `tradehub_core` app'i içinde monolitik. Yeni feature'lar mevcut yapıya eklenir.

## 2. Dizin ve modül haritası (özet)

```
tradehub_core/                          (repo kökü)
├── pyproject.toml                      (flit_core, ruff config)
├── requirements.txt                    (sadece "frappe")
├── CHANGELOG.md
└── tradehub_core/                      (Python paketi — Frappe app modülü)
    ├── hooks.py                        (doc_events, scheduler_events, perms)
    ├── modules.txt                     ("Tradehub Core")
    ├── patches.txt                     (migration patch sırası)
    ├── permissions.py                  (1176 satır — query_conditions + has_permission)
    ├── seed_demo_data.py               (3972 satır — DEV seed)
    ├── tasks.py                        (1224 satır — scheduler entry point'leri)
    ├── api/                            (REST/whitelist endpoints)
    │   ├── listing.py    (3407)        ← kritik refactor adayı
    │   ├── cart.py       (1387)
    │   ├── seller.py     (1314)
    │   ├── order.py      (1072)
    │   ├── payment.py    (830)
    │   ├── public.py     (805)
    │   └── v1/identity.py (1786), crm_overrides.py
    ├── eca/                            (Event–Condition–Action rule engine)
    ├── recommendations/                (Related products, kategori embeddings)
    ├── services/                       (TCMB döviz, dış servis adaptörleri)
    ├── setup/                          (after_install / after_migrate)
    ├── tradehub_core/                  ← Frappe konvansiyonu: modül namespace
    │   ├── api/                        (kpi_dashboard, dashboard_engine)
    │   ├── doctype/                    (75+ doctype dizini)
    │   ├── utils/                      (auth_guards, tenant, security, ...)
    │   ├── scoring/                    (engine.py)
    │   └── workspace/, fixtures/, config/
    ├── utils/                          (kök seviye yardımcılar)
    └── webhooks/                       (ERPNext + dış sistem köprüleri)
```

**DocType sayısı:** 75+ aktif (`tradehub_core/doctype/`).
**Whitelist endpoint sayısı:** ~269 (`@frappe.whitelist()`).
**Toplam Python:** ~322 dosya, en büyük 10 dosya ~16k satır.

## 3. Stack ve sürüm notları

- **Python:** 3.10+ özellikleri (`X | Y` union types, `tomllib`) serbest. 3.11+ özelliği (Self type, exception groups) ortak runtime'ı doğrula.
- **Frappe v15:** `frappe.qb`, `frappe.get_docs`, `frappe.get_list`, `frappe.client_cache`. v14 doc'una **bakma**.
- **Lint:** Ruff `E, F, W, I, B, UP`, tab indent, line-length 110.

## 4. Mutlak kurallar (özet)

> Detay her birinin path-scoped rule'unda. Burası özet uyarı listesi.

1. **Type annotation zorunlu** — yeni endpoint'lerde (`def fn(name: str, qty: int)`).
2. **`get_list` kullan**, `get_all` system-only (user verisi için yasak).
3. **`@frappe.whitelist()` + auth check** — her endpoint'te `doc.check_permission` / `frappe.only_for` / `validate_tenant`.
4. **`frappe.qb` tercih et**, `frappe.db.sql(f"...")` SQL injection.
5. **`super().validate()` çağır** — override'da super atlama yasak.
6. **`hooks.py`'yi silme/üzerine yazma** — append et.
7. **`ignore_permissions=True`** kullanırsan gerekçe yorumla (user input flow'unda yasak).
8. **`except Exception:` gerekçesiz yasak** — en az `frappe.log_error` + spesifik exception.
9. **i18n:** `frappe.throw(_("..."))` zorunlu, çıplak string yasak.
10. **Tab indent + line-length 110** (Ruff format).
11. **Lojistik sözleşme artefaktları ÜRETİLİR — elle düzenleme.**
    `logistics/contract.py`, `logistics/constants.py`, `logistics/exceptions.py`,
    `api/v1/logistics_*.py` ve seed patch'leri **tek otorite**. Bunlardan
    44 dosya üretiliyor: `docs/logistics-api.schema.json`,
    `docs/generated/LOGISTICS-ENDPOINTS.md` (backend başlangıç belgesi),
    `docs/generated/logistics.d.ts`, `docs/generated/fixtures/*.json` ve
    kardeş repolardaki kopyalar (`admin-panel/frontend/src/mocks/logistics`,
    `tradehubfront/src/{mocks/logistics,types/logistics.d.ts}`).

    Kaynağa dokunduysan **üretimi de çalıştır ve üç repoda da commit'le**:
    ```bash
    python3 scripts/gen_logistics_types.py --check   # bayat mı?
    python3 scripts/gen_logistics_types.py --sync    # kardeş repolara da yaz
    ```
    **OTOMATİK KAPI YOK** — ne CI ne pre-commit bunu zorluyor (gerekçe:
    `docs/lojistik/KALAN-ISLER.md` → "Çözülmüş"). Yakalayan tek şey senin
    `--check` çalıştırman. Üretilmiş dosyalar formatter'ın dışında tutuluyor
    (`.prettierignore`); biçimi üreteç belirliyor, Prettier dokunursa iki
    araç birbirini sonsuza kadar geri alır (ölçüldü 2026-08-24: tek
    `npm run format` koşusu 19 dosyada 1958+/2058− sahte diff üretti).

## 5. Path-scoped rules

`.claude/rules/` altında 8 dosya — `.py` dosyası açıldığında otomatik yüklenir:

| Dosya | İçerik |
|---|---|
| `frappe-doctype.md` | DocType oluşturma, child table, isimlendirme, index, schema migration |
| `frappe-api.md` | Modern v15 API (qb, get_list, whitelist), tercih sırası, JS form scripts |
| `hooks-events.md` | hooks.py kayıtları, doc_events, scheduler, multi-tenant `permission_query_conditions` |
| `anti-patterns.md` | 28 anti-pattern (DB/sorgu/güvenlik/hooks/kod kalitesi) |
| `python-style.md` | Tab indent, type hints, fonksiyon boyutu, hata yönetimi, test, Auto-Claude task kuralları |
| `checklists.md` | Her PR için güvenlik + performans + tenant izolasyonu + i18n + cache invalidation |
| `bench-docs.md` | Bench komutları (docker exec deseni), Frappe v15 doküman linkleri |
| `refactor-targets.md` | 10 büyük dosya, 0 qb / 218 raw SQL, 269 whitelist audit, 182 except Exception |

## 6. Auto memory ile ilişki

Kök auto memory her oturumda yüklenir. Bu CLAUDE.md ile **tamamlayıcı**: yazılı kural vs. biriken öğrenme.

Clean code kuralları kök `.claude/rules/clean-code.md`'de — 3 alt-projeyi kapsar; Python-spesifik kısımlar `python-style.md`'de.

### 6.1 Aktif mimari memory'ler (Sprint 2 sonrası, 2026-05-18)

User DocType + Adres + Capability invariant ile ilgili memory'ler tek noktada:

- [[user-profile-architecture-v1]] — Sprint 2 birleşmesi (Buyer/Seller Profile → User Profile + Admin Seller Profile mağaza entity)
- [[sprint-2-6-capability-invariant]] — Patch 20: can_buy=(kyc=Verified), can_sell=(kyb=Verified); auth.py flag formülü status-bazlı
- [[address-architecture-applied]] — Sprint 1 Faz D: Marketplace Settings + Addresses purpose/address_type/tax_no/tax_office + VKN/TCKN checksum
- [[kyb-business-type-status]] — KYB business_type default "Limited Şirket" (kullanıcı form input'u yok)
- [[vergi-tab-hidden]] — Settings/Vergi tab 4 noktada yorum satırı (S3=C); SettingsTaxInfo + i18n korundu

<!-- Bakım notu: bu dosyayı <200 satırda tut. Yaşayan kısım: §2 dizin haritası, §5 rules listesi, §6.1 memory referansları, refactor-targets.md (kod değiştikçe güncellenmeli). Sabit kısım: anti-patterns.md, checklists.md (tek sefer disipliniyle yazıldı). -->


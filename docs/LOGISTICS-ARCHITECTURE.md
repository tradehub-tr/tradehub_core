# Lojistik Modülü — Mimari Sözleşme (TUR-102)

> **Kapsam:** İstoç.com B2B marketplace lojistik modülünün teknik sınırları, geliştirme
> sözleşmeleri ve genişleme noktaları.
> **Otorite kuralı:** Bu belge ile kod çelişirse **kod doğrudur** — belgeyi güncelle.
> **Son güncelleme:** 2026-08-12 (Faz A.2)

---

## 1. Repo sınırları — kim neyden sorumlu

Lojistik tek bir üründür ama **üç repo'ya yayılır**. Sınırı bulanıklaştırmak en sık
yapılan hatadır; aşağıdaki tablo bağlayıcıdır.

| Repo | Sorumluluk | Sorumlu OLMADIĞI |
|---|---|---|
| **tradehub_core** | Domain modeli (DocType), iş kuralları, durum makinesi, permission/tenant izolasyonu, taşıyıcı adapter'ları, arka plan işleri, API sözleşmesinin **sunucu tarafı** | Görsel sunum, ekran akışı, istemci state yönetimi |
| **admin-panel** | Operasyon paneli: katalog yönetimi, sevkiyat operasyonu, taşıyıcı entegrasyon konsolu, rol bazlı **aksiyon görünürlüğü** | İş kuralı, yetki **kararı** (yalnız yetki **sonucunu** gösterir), fiyat/maliyet hesabı |
| **tradehubfront** | Satıcı ve alıcı yüzeyleri: kargo seçimi, sevkiyat takibi, teslimat seçenekleri | Maliyet kırılımı, taşıyıcı credential'ı, operasyon aksiyonları |

### Değişmez sınır kuralları

1. **Yetki kararı yalnız backend'de verilir.** Frontend `capability` listesini okur ve
   aksiyonu gizler/pasifleştirir; bu bir **UX kolaylığı**, güvenlik sınırı değildir.
   Backend her istekte kararı yeniden verir.
2. **Maliyet ve credential alanları frontend'e sızdırılmaz.** `shipping_cost`,
   `carrier_cost`, `api_key`, `api_secret`, `webhook_secret`, `access_token` alanları
   capability kontrolünden geçmeden serialize edilmez (`logistics/permissions.py`
   `mask_*_fields`).
3. **Enum'ların tek kaynağı `logistics/constants.py`'dir.** Frontend'deki durum listeleri
   buradan türetilir; elle kopyalanmaz.
4. **Storefront asla operasyon endpoint'i çağırmaz.** `api/v1/shipment.*` satıcı/operasyon
   yüzeyidir; alıcı yüzeyi ayrı ve dar kapsamlıdır.

---

## 2. Modül yapısı

```
tradehub_core/logistics/
├── constants.py     Durum makinesi, enum'lar, feature flag varsayılanları  ← TEK KAYNAK
├── exceptions.py    LogisticsError hiyerarşisi (HTTP kodlu)
├── permissions.py   Rol matrisi, tenant izolasyonu, alan maskeleme
├── __init__.py      is_enabled() — feature flag okuyucu
├── cache.py         tc:logistics: prefix'li cache anahtarları + invalidation
├── hooks.py         doc_event handler'ları
├── seed.py          Katalog seed veri sözlükleri
├── adapters/        Taşıyıcı entegrasyon katmanı (ABC + registry + carriers/)
├── services/        İş mantığı (desi, fiyatlandırma, bölme, takip, bildirim)
├── jobs/            Arka plan işleri (tracking poll, SLA izleme)
├── reports/         Lojistik raporları
└── tests/           Birim + entegrasyon testleri
```

Hangi bileşenin gerçekten çalıştığı: **`logistics/README.md` → "Mevcut olgunluk"** tablosu.

### Katman kuralları

- `api/` → `services/` → `adapters/` yönünde çağrı yapılır. **Ters yön yasak**:
  `adapters/` içinden `services/` veya `api/` import edilmez.
- `constants.py` ve `exceptions.py` **yaprak modüldür** — hiçbir lojistik modülünü
  import etmez (döngüsel bağımlılık koruması).
- DocType controller'ları iş mantığı **barındırmaz**, `services/`'e delege eder.
  Controller'da yalnız doğrulama ve alan normalizasyonu bulunur.

---

## 3. İsimlendirme sözleşmesi

| Öğe | Desen | Örnek |
|---|---|---|
| DocType | Title Case | `Carrier Account`, `Shipment Exception Code` |
| DocType klasörü | snake_case | `carrier_account/carrier_account.py` |
| Controller sınıfı | PascalCase | `class CarrierAccount(Document)` |
| Sevkiyat adı | `SHP-.YYYY.-.#####` | `SHP-2026-00001` |
| Katalog autoname | `field:<kod alanı>` | `field:provider_code` → `YK` |
| Çok alanlı autoname | `format:{a}-{b}` | `format:{carrier}-{branch_code}` |
| Migration patch | `v15_log<NNN>_<konu>.py` | `v15_log037_seed_logistics_role_profiles.py` |
| Cache anahtarı | `tc:logistics:<alan>:<id>` | `tc:logistics:dashboard:seller:ABC` |
| Capability | `<nesne>.<eylem>` / `view.<alan>` | `shipment.cancel`, `view.carrier_secret` |
| Feature flag | `<konu>_enabled` | `carrier_api_enabled` |
| Git branch | kişi bazlı (ekip kuralı) | `ali`, `bora`, `metin` |

> **Kod alanları büyük harfe normalize edilir** ve normalizasyon `before_insert`'te
> yapılır — Frappe v15'te `set_new_name()` `validate`'ten **önce** çalıştığı için
> yalnız `validate`'te normalize etmek `name` ile alan arasında drift yaratır.

---

## 4. API sözleşmesi

### 4.1 Sürümleme

| Namespace | Kullanım |
|---|---|
| `tradehub_core.api.v1.*` | **Tek geçerli namespace.** Yeni tüm lojistik endpoint'leri buraya |
| `tradehub_core.api.logistics` | ⚠️ Sürümsüz, tarihsel. **B bloğunda `api/v1/logistics.py`'ye taşınacak** |

Kırıcı değişiklik `v2` açar; `v1` bozulmaz.

### 4.2 Yetki sözleşmesi

Her endpoint'te üç kontrolden **en az biri** zorunludur:

```python
doc.check_permission("read"|"write")   # tekil doküman
frappe.only_for([...])                 # rol kapısı
validate_tenant(doc)                   # satıcı izolasyonu
```

- Liste sorgularında **`frappe.get_list`** kullanılır (`get_all` değil) —
  `permission_query_conditions` ancak böyle devreye girer.
- `allow_guest=True` yalnız gerçekten public veriye açılır ve **kaynağın yayın
  durumu ayrıca doğrulanır** (taslak/pasif kayıt guest'e sızmamalı).

### 4.3 Ortak hata modeli

`logistics/exceptions.py` hiyerarşisi HTTP kodlarını taşır:

| Sınıf | HTTP | Ne zaman |
|---|---:|---|
| `LogisticsError` | 417 | Tüm lojistik hatalarının atası |
| `CarrierAPIError` | 502 | Taşıyıcı API'si hata döndü |
| `CarrierTimeoutError` | 504 | Taşıyıcı API'si zaman aşımı |
| `ShipmentStateError` | 409 | İzin verilmeyen durum geçişi |
| `IdempotencyConflictError` | 409 | Aynı anahtar, farklı istek |
| `SplitInvariantError` | 422 | INV-1..5 ihlali |
| `TrackingNotFoundError` | 404 | Takip/sevkiyat bulunamadı |
| `CarrierNotFoundError` | 404 | Registry'de olmayan carrier_code |
| `CarrierCapabilityError` | 400 | Taşıyıcı bu yeteneği desteklemiyor |

> 🔸 **Mevcut durum:** Sınıflar tanımlı ama **hiçbir endpoint kullanmıyor**; hepsi düz
> `frappe.ValidationError` fırlatıyor. İstemcinin hata türünü ayırt edebilmesi için
> gereken HTTP zarfı (`error_code`, `message`, `http_status`, `details`) ve onu uygulayan
> dekoratör **B bloğunda** yazılacak ve sözleşme orada dondurulacak.

### 4.4 Idempotency

Kargo API'leri **gerçek gönderi ve ücret üretir**; ağ hatasında yapılan retry çift
gönderi yaratır. Bu yüzden gönderi oluşturan / iptal eden her endpoint idempotent olmalıdır.

- İstemci `Idempotency-Key` header'ı gönderir (istek başına benzersiz).
- Aynı anahtar + aynı istek gövdesi → **ilk yanıt** tekrar döner, yeni işlem yapılmaz.
- Aynı anahtar + **farklı** gövde → `IdempotencyConflictError` (409).

> 🔸 **Mevcut durum:** Yalnız exception sınıfı var. Anahtar üretimi, saklama ve TTL
> **B bloğunda sözleşme olarak**, **F bloğunda implementasyon olarak** gelecek.

---

## 5. Feature flag ve kademeli açılış

`is_enabled(flag)` üç katmanı sırayla okur:

1. `Logistics Settings.feature_flags` (JSON alan)
2. `site_config` → `tradehub_logistics_<flag>`
3. `constants.LOGISTICS_FEATURE_FLAGS` varsayılanı (**hepsi `False`**)

12 bayrak: `carrier_api_enabled`, `multi_carrier_enabled`, `shipping_zone_pricing_enabled`,
`auto_tracking_enabled`, `split_shipment_enabled`, `multi_leg_enabled`,
`cost_estimation_enabled`, `webhook_notifications_enabled`, `return_flow_enabled`,
`seller_delivery_enabled`, `buyer_pickup_enabled`, `warehouse_transfer_enabled`.

**Kural:** Her lojistik giriş noktası ilgili bayrağı kontrol eder. Bayrak kapalıysa
endpoint iş yapmaz.

> 🔸 **Mevcut durum:** `is_enabled()` production kodunda **hiçbir yerden çağrılmıyor**;
> `Logistics Settings.logistics_enabled` ana bayrağı yazılıyor ama **hiç okunmuyor**.
> Bayrak kapısı B bloğunda eklenecek — `logistics_enabled` kapalıyken tüm bayraklar
> `False` sayılacak.

Yayın sırası: **Beta → RC → PROD**, sonra bayraklar tek tek açılır
(`logistics_enabled` → `cost_estimation_enabled` → `carrier_api_enabled` → …).

---

## 6. Migration, fixture ve patch standardı

### 6.1 Patch kuralları

- **Her şema değişikliği patch ister.** DocType JSON'unu değiştirmek tek başına yetmez;
  mevcut satırların veri uyumu için idempotent bir backfill patch'i gerekir.
- **Patch idempotenttir** — iki kez çalışırsa aynı sonucu üretir, duplicate yaratmaz.
- Kayıt: `patches.txt` → **`[post_model_sync]`** bölümüne, **sona** eklenir. Sıra bozulmaz.
- Sistem kurulumu olduğu için `ignore_permissions=True` serbesttir; **gerekçe yorumla**.
- **Sessiz atlama yasak.** Ön koşul sağlanmıyorsa `frappe.log_error` ile görünür kıl —
  `continue` ile geçip başarılı görünme.

```python
def execute() -> None:
    if frappe.db.exists("Shipping Channel", code):
        return                      # idempotent — zaten var
    doc = frappe.new_doc("Shipping Channel")
    ...
    doc.insert(ignore_permissions=True)  # Sistem migration'ı, kullanıcı akışı değil
    frappe.db.commit()
```

### 6.2 Fixture tuzağı ⚠️

`tradehub_core/tradehub_core/fixtures/role_profile.json` dosyası **Frappe'nin fixture
mekanizmasıyla yüklenmez** — `hooks.py` içindeki `fixtures` listesinde `Role Profile`
yoktur. Bu dosyayı DB'ye taşıyan tek şey **patch**'lerdir.

Sonuç: JSON'a yeni bir Role Profile eklemek **hiçbir şey yapmaz**; eskiden çalışmış patch
Patch Log'da kayıtlı olduğu için tekrar çalışmaz. **Yeni profil eklerken yeni patch yaz.**

> Bu tuzak gerçekten ısırdı: TUR-103'te eklenen 3 lojistik Role Profile'ı DB'ye hiç
> yazılmadı, dolayısıyla capability grant'ları da oluşmadı (bkz. Faz A.3).

### 6.3 Seed verisi

- Seed veri sözlükleri `logistics/seed.py`'de, onları yazan patch'ler
  `patches/v15_log0NN_*.py`'de durur. Sözlükte `name` anahtarı **kullanma** —
  `doc.name` ile çakışır.
- Seed **katalog** verisi üretir, **işlem** verisi değil.
- Seed geri alınırken **referans kontrol edilir**: kayıt başka bir dokümandan link
  ediliyorsa silinmez, `is_active=0` yapılır.

---

## 7. Ülke ve bölge genişlemesi

Modül Türkiye ile başlar ama tek ülkeye çakılmaz.

| Alan | Kural |
|---|---|
| Ülke | `Link: Country` (Frappe standart DocType, 250 kayıt). ⚠️ Kayıt adları **İngilizce**dir (`Turkey`, `Germany`) — Türkçe string yazma |
| İl / ilçe | Kanonik biçim **diakritikli Türkçe** ("İstanbul", "Şanlıurfa"). Yeni bir il/ilçe DocType'ı **açılmaz**; `patches/normalize_address_provinces_diacritics.ASCII_TO_DIACRITIC` eşlemesi tek kaynaktır ve `before_insert`'te uygulanır |
| Servis bölgesi | `Service Coverage Area` — taşıyıcı × servis × il/ilçe × posta kodu aralığı |
| Para birimi | `Logistics Settings.default_currency` (`Link: Currency`), varsayılan `TRY` |
| Desi böleni | Yurt içi `3000`, uluslararası `5000` — çağıran belirtir, sabit gömülmez |

> ⚠️ **Collation tuzağı — benzersizlik testi yazarken.** MariaDB `utf8mb4_unicode_ci`
> bazı Türkçe çiftleri kendisi eşit sayar, bazılarını saymaz:
>
> ```
> 'Istanbul'  = 'İstanbul'   COLLATE utf8mb4_unicode_ci  -> 1   (DB engeller)
> 'Sanliurfa' = 'Şanlıurfa'  COLLATE utf8mb4_unicode_ci  -> 0   (DB ENGELLEMEZ)
> ```
>
> Yani İstanbul çiftiyle yazılan bir "duplicate reddedilir" testi, normalizasyon
> tamamen kaldırılsa bile yeşil kalır — koruduğu şeyi kanıtlamaz. Normalizasyonun
> yükünü taşıdığı durumu test etmek için collation'ın yakalayamadığı bir çift
> (Şanlıurfa/Sanliurfa gibi) kullan.

---

## 8. Taşıyıcı entegrasyon sözleşmesi

Yeni taşıyıcı eklemek **çekirdek kodu değiştirmeden** mümkündür.

1. `adapters/carriers/<carrier>.py` içinde `BaseCarrierAdapter` türet.
2. Zorunlu metotlar: `authenticate()`, `get_quote()`, `create_shipment()`, `track()`.
3. Opsiyonel metotlar (`cancel_shipment`, `get_label`, `schedule_pickup`) desteklenmiyorsa
   **override etme** — taban sınıf `CarrierCapabilityError` (400) fırlatır.
4. `capabilities` kümesini bildir (`CarrierCapability` enum'ı).
5. `register_carrier("<kod>", <Sınıf>)` ile kaydet — idempotenttir, aynı kodla **farklı**
   sınıf gelirse hata verir.
6. Kimlik bilgileri `Carrier Account` DocType'ında (`Password` fieldtype) tutulur.

**Veri kontratları** `adapters/base.py` içinde `@dataclass` olarak tanımlıdır:
`QuoteRequest/Response`, `ShipmentRequest/Response`, `TrackingResponse/Event`, `CancelResponse`.
Taşıyıcıya özgü ham yanıt `raw_response` alanında saklanır — normalize edilmiş alanlar
sözleşmedir, `raw_response` teşhis içindir.

**Dış çağrı kuralları:** timeout zorunlu, retry exponential backoff, tekrarlayan hatada
circuit breaker, log'a **credential yazılmaz**. (`adapters/http_client.py` — 🔸 F bloğunda.)

---

## 9. Yetki modeli

### Roller

| Rol | Kapsam |
|---|---|
| `Logistics Manager` | Platform lojistik yöneticisi — tam operasyon + iptal/bölme |
| `Logistics Operator` | Sevkiyat oluşturma/düzenleme, takip görüntüleme |
| `Carrier Integration Manager` | Taşıyıcı hesapları ve credential yönetimi |

Platform rolleri (`System Manager`, `Marketplace Admin`, `Platform Admin`) tam erişim;
`Support Agent` yalnız okuma; `Platform Finance` yalnız okuma/rapor.

### Capability'ler (8)

`shipment.create` · `shipment.write` · `shipment.cancel` · `shipment.split` ·
`view.logistics_cost` · `view.tracking` · `carrier_credential.manage` · `view.carrier_secret`

### Tenant izolasyonu

- Satıcı kapsamlı DocType'larda tenant alanı **`seller_profile`** (`Admin Seller Profile`
  link'i). Başka isim kullanma — `seller` alanı farklı anlam taşır.
- İki katman zorunlu: `permission_query_conditions` (liste) **+** `has_permission` (tekil).
- Yazma yolunda çift hook: `before_insert` (autoset + cross-tenant reddi) **+**
  `validate` (tenant değişim kilidi) — `utils/tenant.py`.
- `has_permission` hook'u Frappe'de izin **veremez, yalnız kısıtlar**. DocPerm satırı
  olmayan bir role burada `True` döndürmek ölü koddur.

### Alan maskeleme

`mask_shipment_cost_fields` ve `mask_carrier_account_fields` **fail-closed** çalışır:
capability çözülemezse maskeleme **uygulanır**.

⚠️ Secret maskesi **yalnız `"*"` karakterinden** oluşmalıdır. Frappe'nin
`BaseDocument._save_passwords` metodu sadece tamamı asterisk olan değeri "dummy" sayıp
kaydetmede atlar; bullet (`•`) içeren bir maske doküman kaydedilirse `__Auth`'taki
gerçek secret'ın **üzerine yazar**.

Maliyet maskesi `None` yazar, `0` **değil** — `0` gerçek maliyeti ezerdi.

---

## 10. Yeni geliştirici — sıfırdan ayağa kaldırma

```bash
# 1. Stack'i başlat (kök orkestrasyon klasöründen)
cd <istoc.com kökü>
docker compose up -d

# 2. Migrate — lojistik DocType'ları ve seed patch'leri uygulanır
docker exec istoccom-backend-1 bash -c \
  "cd /home/frappe/workspace/frappe-bench && bench --site dev.localhost migrate"

# 3. Doğrula — katalog satır sayıları
docker exec istoccom-backend-1 bash -c \
  "cd /home/frappe/workspace/frappe-bench && bench --site dev.localhost mariadb -e \
   \"SELECT COUNT(*) FROM \\\`tabShipping Channel\\\`;\""    # → 5

# 4. Testleri çalıştır
docker exec istoccom-backend-1 bash -c \
  "cd /home/frappe/workspace/frappe-bench && bench --site dev.localhost run-tests \
   --module tradehub_core.logistics.tests.test_constants"

# 5. Lint
ruff check tradehub_core/
```

**Beklenen ilk kurulum çıktısı:** Shipping Channel 5 · Shipping Method 5 ·
Logistics Provider 8 · Vehicle Type 5 · Package Type 5 · Shipment Exception Code 8 ·
Logistics Settings 1 (singleton).

Yeni DocType / hook / whitelist endpoint eklendiyse worker'lar route cache'lediği için:
`docker restart istoccom-backend-1`.

---

## 11. Branch ve PR kuralları

- Ekip **kişi bazlı branch** kullanır (`ali`, `bora`, `metin`); iş bitince PR ile
  default branch'e merge edilir. `tradehub_core` default branch'i **`version-15`**
  (`main` değil), `admin-panel` **`master`**, `tradehubfront` **`main`**.
- Commit mesajı Türkçe, Conventional Commits, yalnız 3 prefix: `feat:` / `fix:` / `refactor:`
  (bkz. kök `.claude/rules/commit.md`). Merge commit'inde `feat`/`fix` **kullanma** —
  auto-bump'ı tetikler.
- **Refactor commit'i ayrı ve önce**, `feat`/`fix` sonra.
- CI: `lint.yml` → `ruff check .` (`continue-on-error` **yok**, kırmızıysa merge etme).
  ⚠️ CI `ruff==0.8.0` pinliyor; lokalde daha yeni sürüm kullanıyorsan uyuşmazlık olabilir.
- Sürüm etiketleri: `alpha` → `beta` → `rc` → prod. Lojistik işi 2026-08-12 itibarıyla
  **yalnız alpha** etiketlerinde.

---

## 12. Bilinen açıklar

Bu belge yazıldığı anda kapalı **olmayan** maddeler. Kapandıkça buradan silinir.

| # | Açık | Nereye |
|---|---|---|
| 1 | Ortak hata zarfı endpoint'lere bağlı değil | B bloğu |
| 2 | Idempotency implementasyonu yok | B (sözleşme) / F (kod) |
| 3 | `is_enabled()` hiçbir kapıda kullanılmıyor | B bloğu |
| 4 | `api/logistics.py` sürümsüz namespace'te | B bloğu |
| 5 | Boot'ta hiçbir carrier register edilmiyor | F bloğu |
| 6 | `adapters/http_client.py` boş (retry/timeout/circuit breaker yok) | F bloğu |
| 7 | Shipment DocType yok → durum makinesi uygulanmıyor | F bloğu |
| 8 | ReBAC `model.fga`'da `shipment` tipi yok, `tuple_sync` buna rağmen tuple üretiyor | F bloğu |
| 9 | `logistics/hooks.py`'deki 7 handler `pass` ve ana `hooks.py`'a bağlı değil | F bloğu |
| 10 | Katalog yönetim ekranları yok (admin-panel) | C–E blokları |

Ayrıntılı bulgu listesi ve plan: kök `docs/PLAN-lojistik-eksik-giderme.md`,
`docs/YOL-HARITASI-lojistik.md`.

# Ö-3 — KYC Verification kiracı izolasyonu

**Tarih:** 2026-08-19 · **Depo:** `tradehub_core` (`ahmet`) · **Ortam:** `istoc.localhost` (Docker, `istoc-dev-backend-1`)

---

## 1. Bulgu

`Seller Owner` rolü, `KYC Verification` üzerinde **sahiplik kısıtı olmadan** okuma **ve yazma** iznine sahipti:

```
[Custom DocPerm] KYC Verification / Seller Owner
  permlevel=0  read=1  write=1  create=0  if_owner=0  report=0  export=1
```

ve bu izni sınırlayacak hiçbir kiracı kancası yoktu:

```
KYC Verification   permission_query_conditions=YOK    has_permission=YOK
KYB Verification   permission_query_conditions=VAR    has_permission=VAR
```

Canlıda `Seller Owner` rolü taşıyan **37 kullanıcı**, sistemdeki **24 KYC kaydının tamamını** okuyabiliyor ve permlevel-0 alanlarını değiştirebiliyordu.

### 1.1 Kök neden — patch'in yazılı varsayımı hiç gerçekleşmemiş

Satır `tradehub_core/patches/v15_8_3_seller_owner_kyb_kyc_docperm.py` tarafından eklenmiş (2026-06-16). O patch'in kendi docstring'i şunu söylüyor:

> "Tenant izolasyonu KORUNUR: her iki doctype'ta `permission_query_conditions` + `has_permission` hook'u var (hooks.py → `kyb_verification_*`; `doc.user==user`) → satıcı YALNIZCA kendi kaydını görür/düzenler."

Cümle KYB için doğruydu, **KYC için değildi**: `hooks.py`'de yalnız KYB kayıtlıydı. Yani patch, KYC tarafında hiç var olmayan bir güvenlik önlemine dayanarak `if_owner=0 + write=1` verdi. Patch'in `_GRANTS` sözlüğünde KYB ve KYC yan yana duruyor, ama koruma yalnız birinde vardı — bu, **iki doctype'ı aynı patch'te ele alıp izolasyonu yalnız birinde doğrulamanın** tipik sonucudur.

İki DocPerm satırı bugün de baytı baytına aynıdır (`ou5k5jhpf8` / `ou5us3r7du`, aynı saniyede yaratılmış) — tek fark, KYB'nin arkasında kancanın olması.

Aynı denetimde `Payment Transaction`'da (`Marketplace Seller`, `read=1, if_owner=0`, kanca yok) ve Ö-2'de (`File` çok-satırlı sızıntı) **aynı desen** görüldü. Ö-2 ajanı kapattığı 437 erişimin 318'inin kök nedeninin bu izin satırı olduğunu ölçtü; o düzeltme **dosya indirmesini** kapattı, **kaydın alanlarını** değil. Bu rapor kaydın alanlarını kapatır.

---

## 2. Sızıntı kanıtı — DÜZELTMEDEN ÖNCE

Koşum: `tradehub_core._kycsec_evidence.main` (geçici modül, koşum sonrası silindi), canlı `istoc.localhost` DB.
Personalar: `kycsec_attacker@test.local` (`Marketplace Seller` + `Seller` + `Seller Owner`), `kycsec_victim@test.local` (`Buyer`).

| # | Deneme | Sonuç (ÖNCE) |
|---|---|---|
| 1 | `frappe.client.get("KYC Verification", <kurbanın kaydı>)` saldırgan bağlamında | **GEÇTİ** — `phone`, `address`, `billing_address`, `tax_id`, `identity_document`, `email_field` tam döndü |
| 1b | `frappe.has_permission(..., "read", doc=<kurban>, user=saldırgan)` | **`True`** |
| 2 | `frappe.client.set_value(..., "phone", "+909999999999")` kurbanın kaydına | **GEÇTİ** — DB'de `phone = +909999999999` doğrulandı |
| 2b | `frappe.has_permission(..., "write", doc=<kurban>, user=saldırgan)` | **`True`** |
| 3 | **Canlı kayıt**: gerçek satıcı `demo-seller-01@istoc.demo` → gerçek alıcının KYC kaydı (`KYC-00024`) | **GEÇTİ** — gerçek `phone` + `address` okundu (rapor için maskelendi) |
| 4 | `frappe.get_list("KYC Verification")` saldırgan bağlamında | **26/26 kayıt** döndü (kurbanınki dahil) |

3 numaralı vaka kritik: sızıntı benim ürettiğim fixture'ın artefaktı **değil** — canlıdaki gerçek bir mağaza sahibi, canlıdaki gerçek bir alıcının kimlik/adres/telefon verisine ulaşıyordu.

---

## 3. Düzeltme

### 3.1 `permissions.py` (yalnız ekleme, +30 satır)

`kyb_verification_query_conditions` / `kyb_verification_has_permission`'ın **birebir aynası**. Desen icat edilmedi:

```python
def kyc_verification_query_conditions(user):
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	return f"`tabKYC Verification`.`user` = {frappe.db.escape(user)}"


def kyc_verification_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user, ptype):
		return True
	user_val = getattr(doc, "user", None) if not isinstance(doc, dict) else doc.get("user")
	return user_val == user
```

### 3.2 `hooks.py` (yalnız ekleme, +5 satır — diff'te 0 silme)

`permission_query_conditions` ve `has_permission` sözlüklerine `"KYC Verification"` kaydı, KYB satırının hemen altına.

### 3.3 `Seller Owner` DocPerm satırı — SİLİNMEDİ, DARALTILDI

**Karar ve gerekçe:**

- **Satır silinmedi.** Meşru kullanımı var ve doğrulandı: admin-panel KYC formunu generic desk REST üzerinden açıp kaydediyor (`admin-panel/frontend/src/views/doctype/DocTypeFormView.vue` → `api.updateDoc("KYC Verification", …)`). v15_8_3 tam olarak bu yoldaki 403'ü kapatmak için eklenmişti; satır silinirse mağaza sahibi **kendi** KYC kaydını panelde açamaz.
- **`if_owner` 1 yapılmadı.** Bu doctype'ta `owner` doğru eksen değil: canlıda 24 kaydın **15'inde** `owner = "Administrator"` (seed/onay akışı), `user` ise gerçek kişi. `if_owner=1` bu 15 kullanıcının kendi kaydına erişimini kırardı. Doğru eksen `user` link alanıdır ve `if_owner`'dan güçlüdür — `owner` yeniden atanabilir, `user` şemadır. Bunu 3.1'deki kanca uygular.
- **Daraltılan:** `export` `1 → 0`. `report=0` olduğu için zaten ölü bir grant'tı, ama bir PII doctype'ında satıcı rolüne duran bir dışa-aktarma yetkisi bırakıyordu.
- **Sabitlenen:** `create/delete/submit/cancel/amend/report/import/share/print/email/if_owner = 0` invariant olarak yazıldı — ileride bir "union" patch'i (v15_8_3 gibi) bunları sessizce açamasın diye.
- **Korunan:** `read=1, write=1` — artık kancayla kendi kaydına sınırlı.

### 3.4 Patch — `v15_9_24_kyc_docperm_tenant_isolation`

`tradehub_core/patches/v15_9_24_kyc_docperm_tenant_isolation.py` + `patches.txt` kaydı.

- İdempotent — birinci koşum `{"changed": {"export": {"from": 1, "to": 0}}}`, ikinci koşum `{"changed": {}}` (ikisi de koşuldu).
- **Erişim genişletmez:** satır yoksa yeni satır AÇMAZ (`skipped: no_docperm_row`). Bu bir sertleştirme patch'i.
- **Kanca invaryantını denetler:** `permission_query_conditions` + `has_permission` kayıtlı değilse `frappe.log_error` ile görünür bir kayıt bırakır — v15_8_3'ün hatası (var olmayan bir korumaya güvenmek) tekrarlanamasın diye.

Patch `bench execute` ile iki kez doğrudan koşuldu (Patch Log'a **yazılmadı** — konteynerde başka ajanlar çalıştığı için `bench migrate` kilidine girilmedi). Sıradaki `bench migrate` patch'i normal akışında bir kez daha koşacak; idempotent olduğu için `{"changed": {}}` dönecek.

Koşum çıktısı:
```
{"hooks": {"permission_query_conditions": true, "has_permission": true},
 "changed": {"export": {"from": 1, "to": 0}},
 "row": {"read": 1, "write": 1, "create": 0, "delete": 0, "submit": 0, "cancel": 0,
         "amend": 0, "report": 0, "export": 0, "import": 0, "share": 0, "print": 0,
         "email": 0, "if_owner": 0}}
```

---

## 4. Kapanış kanıtı — DÜZELTMEDEN SONRA

Aynı script, aynı personalar, `docker restart` sonrası (gunicorn `hooks.py`'yi boot'ta import ettiği için `bench clear-cache` yetmez):

| # | Deneme | ÖNCE | SONRA |
|---|---|---|---|
| 1 | saldırgan → kurbanın kaydını `frappe.client.get` | tam veri döndü | **`PermissionError`** |
| 1b | `has_permission(read)` | `True` | **`False`** |
| 2 | saldırgan → kurbanın `phone` alanına `set_value` | DB değişti | **`PermissionError`**, DB'de değer değişmedi |
| 2b | `has_permission(write)` | `True` | **`False`** |
| 3 | canlı: `demo-seller-01` → `KYC-00024` | gerçek PII döndü | **`PermissionError`** |
| 4 | saldırgan `frappe.get_list` | 26 kayıt | **1 kayıt** (yalnız kendisininki) |

### 4.1 Meşru erişim kırılmadı

| Kim | Deneme | SONRA |
|---|---|---|
| Mağaza sahibi (kendi kaydı) | read + `set_value("phone")` | **çalışıyor** (`owner="Administrator"` olan kayıtta da — yani `user` ekseni üzerinden) |
| Marketplace Admin | read + list + başkasına write | **çalışıyor** (list 26/26) |
| Administrator / System Manager | read + list | **çalışıyor** (list 26/26) |
| Compliance Officer | `kyc_verification_has_permission(doc, "read")` | **`True`** · `query_conditions` → `""` (kısıtsız) |
| Compliance Officer | `kyc_verification_has_permission(doc, "write")` | **`False`** — `_PLATFORM_WRITE_ACCESS_ROLES` gereği salt-okunur, doğru davranış |

---

## 5. Testler

`tradehub_core/tests/test_kyc_tenant_isolation.py` — 13 test.

```
docker exec istoc-dev-backend-1 bench --site istoc.localhost \
    run-tests --module tradehub_core.tests.test_kyc_tenant_isolation
```

```
Ran 13 tests in 166.820s

OK
```

| Test | Ne sınıyor |
|---|---|
| `test_cross_tenant_read_denied` | başkasının kaydı: `has_permission(read)` False + `frappe.client.get` → `PermissionError` |
| `test_cross_tenant_write_denied` | başkasının kaydı: `has_permission(write)` False + `set_value` → `PermissionError` + DB'de değer değişmemiş |
| `test_cross_tenant_delete_denied` | başkasının kaydı: `has_permission(delete)` False |
| `test_list_excludes_other_tenants` | `frappe.get_list` başkasınınkini döndürmez, kendisininkini döndürür |
| `test_query_conditions_sql_scopes_to_user` | üretilen SQL `user` alanına bağlanıyor (`owner`'a değil) |
| `test_own_record_read_and_write_allowed` | kendi kaydı: read + `set_value("phone")` çalışıyor |
| `test_marketplace_admin_keeps_full_access` | read + list + başkasına write çalışıyor |
| `test_system_manager_keeps_full_access` | read + list çalışıyor |
| `test_administrator_keeps_full_access` | `query_conditions` boş + list tam |
| `test_compliance_officer_not_blocked_by_this_layer` | kanca `read` için True, `query_conditions` boş |
| `test_compliance_officer_is_read_only_at_this_layer` | kanca `write` için False |
| `test_hooks_registered` | `hooks.py` kaydı gerçekten var |
| `test_docperm_row_is_narrowed` | v15_9_24 sonrası satırda ölü grant yok |

Fixture, `owner`-ekseni yanılgısına karşı korumalı: saldırganın kendi KYC kaydının `owner`'ı bilerek `"Administrator"` yapılıyor, böylece "kendi kaydını okuyabiliyor" yeşili `if_owner` üzerinden **gelemez**.

### 5.1 Vacuity (boşluk) kanıtı

Testlerin gerçekten düzeltmeyi ölçtüğünü göstermek için düzeltme **geçici olarak geri alındı** (konteynerde `hooks.py`'den iki KYC kaydı `sed` ile silindi, `permissions.py` ve DocPerm dokunulmadan bırakıldı), testler tekrar koşuldu, sonra geri konuldu.

```
FAIL: test_cross_tenant_read_denied
      AssertionError: True is not false : Seller Owner başkasının KYC kaydını okuyabiliyor
FAIL: test_cross_tenant_write_denied
      AssertionError: True is not false : Seller Owner başkasının KYC kaydına yazabiliyor
FAIL: test_hooks_registered
      AssertionError: 'tradehub_core.permissions.kyc_verification_query_conditions' not found in []
FAIL: test_list_excludes_other_tenants
      AssertionError: 'KYC-00045' unexpectedly found in [... 28 kayıt ...] : liste sorgusunda çapraz kiracı sızıntısı

Ran 13 tests in 151.011s
FAILED (failures=4)
```

Yani izolasyon testleri **boş değil** — kanca kaldırılınca kırmızıya dönüyorlar. Geri koyduktan sonra tekrar `Ran 13 tests ... OK`.

Kırmızıya dönmeyen iki test bilinçli:
- `test_cross_tenant_delete_denied` kancasız da geçer (`delete` bayrağı zaten hiçbir satıcı rolünde açık değil) — kanca-ölçer değil, regresyon bekçisi.
- `test_docperm_row_is_narrowed` `hooks.py`'yi değil DocPerm satırını ölçer; vacuity koşumunda satır geri alınmadığı için yeşil kaldı.

---

## 6. Kapatılamayan / kapsam dışı bırakılan vektörler

Bunlar **kapatılmadı**. Ölçüldüler, kaydediliyorlar.

### 6.1 `Compliance Officer` KYC'yi hiç okuyamıyor (önceden var olan, düzeltilmedi)

Ölçüm (`frappe.permissions.get_role_permissions`, KYC Verification, Compliance Officer):

```
{"read": 0, "write": 0, "export": 0, ... }   # permlevel-0 satırı YOK
```

Compliance Officer'ın KYC'de yalnız **permlevel 1, 2, 3** Custom DocPerm satırları var; permlevel-0 satırı yok. Frappe permlevel-0'da okuma vermezse dokümanı hiç açtırmaz → `frappe.client.get` **düzeltmeden önce de sonra da** `PermissionError` veriyor. Aynı boşluk KYB Verification'da da var.

Bu, benim kattığım katmandan bağımsız (kanca `True` dönüyor, `query_conditions` boş). Bilinçli olarak **düzeltmedim**: bir sertleştirme patch'inde erişim genişletmek yanlış yön, ve "Compliance Officer KYC'yi görmeli mi" bir ürün kararı. Ayrı bir görev olarak açılmalı.

### 6.2 Kendi KYC kaydında `status` alanına yazma — ayrıcalık yükseltme adayı

`Seller` ve `Marketplace Seller` rolleri KYC'de **permlevel 1'de `write=1, if_owner=1`** taşıyor. `status` alanı permlevel 1. Kendi kaydının `owner`'ı olan bir kullanıcı, kendi KYC durumunu `Verified`'a çekip `User Profile.can_buy=1` tetikleyebilir (`kyc_verification.py::_sync_kyc_status`).

Bu **kiracı izolasyonu değil, ayrıcalık yükseltmesidir** — bu görevin kapsamı dışı ve `KYB Verification`'da da birebir aynı şekilde var. Düzeltmedim; ölçtüm ve buraya yazıyorum. Ayrı görev olmalı.

### 6.3 `Payment Transaction`

Aynı desenin kardeşi (`Marketplace Seller`, `read=1, if_owner=0`, kanca yok). Bu görevin kapsamı dışı, hâlâ **açık**.

### 6.4 Storefront API yolu — zaten etkilenmiyor

`tradehub_core/api/v1/kyc.py` (`get_kyc_status`, `submit_kyc_documents`) oturum kullanıcısına göre filtreliyor ve yazarken `ignore_permissions=True` kullanıyor. Yani bu düzeltme storefront akışını **ne kırıyor ne de koruyor** — koruma zaten endpoint'in kendi filtresinden geliyordu. Sızıntı yüzeyi generic desk/ORM yüzeyiydi ve kapandı.

---

## 7. Dokunulan dosyalar

| Dosya | Değişiklik |
|---|---|
| `tradehub_core/permissions.py` | +30 satır (yalnız ekleme) |
| `tradehub_core/hooks.py` | +5 satır (yalnız ekleme; diff'te 0 silme) |
| `tradehub_core/patches/v15_9_24_kyc_docperm_tenant_isolation.py` | yeni |
| `tradehub_core/patches.txt` | +1 satır |
| `tradehub_core/tests/test_kyc_tenant_isolation.py` | yeni, 13 test |
| `docs/reports/24-kyc-izolasyon.md` | bu dosya |

`kyc_verification.json`'a dokunulmadı — DocType'ta Custom DocPerm bulunduğu için JSON `permissions` bloğu Frappe tarafından **tamamen yok sayılıyor**; oraya yazmak ölü kod olurdu.

Dokunulmayan (yasak) alanlar: `media/file_isolation.py`, `api/media_manifest.py`, `api/seller_media.py`, `media/browse.py`, `media/pipeline/storage/`, `docs/standards/`, `admin-panel`, `tradehubfront`. `Media Engine Settings` bayrakları 0'da bırakıldı. Üretilen test kayıtları ve geçici koşum modülleri silindi.

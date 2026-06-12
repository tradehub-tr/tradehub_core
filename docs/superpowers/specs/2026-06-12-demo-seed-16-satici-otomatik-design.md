# Demo Seed: 16 Satıcı + Otomatik İdempotent Çalışma — Tasarım

**Tarih:** 2026-06-12
**Kapsam:** `tradehub_core/tradehub_core/seed_demo_data.py` + `tradehub_core/tradehub_core/hooks.py`
**Branch:** `ahmet`

## 1. Amaç

Demo seed verisini, beta / RC / istoc.com (prod) ortamlarının **hepsinde aynı** görünecek
şekilde, deploy sırasında **otomatik** ve **veri silmeden (idempotent)** çalışacak hâle getirmek.
Ayrıca satıcı sayısını **16**'ya çıkarmak ve 3 isimli gerçek e-postayı onaylı satıcı olarak eklemek.

## 2. Gereksinimler (kullanıcı kararları)

| # | Karar | Değer |
|---|---|---|
| R1 | Satıcı sayısı | **16** (mevcut 10 + 6 yeni). Alıcılar **5** kalır. |
| R2 | İsimli satıcılar | `ahmet.seker@turksab.com`, `ali.bal@turksab.com`, `bora.aydeger@turksab.com` — onaylı KYB/KYC. |
| R3 | Otomatik çalışma | `after_migrate` hook → her deploy/migrate'te. |
| R4 | Veri davranışı | **Saf idempotent**: asla silme, eksikleri ekle (create-if-missing). |
| R5 | İsimli e-postalar | Demo kapsamında, tazelemeye dahil — ama gerçek User hesabı korunur. |
| R6 | Kategoriler | Sabit kalır; 3 ortamda birebir aynı. Yeni satıcılar mevcut kategorilere bağlanır. |
| R7 | Demo şifreleri | Tüm demo satıcı + alıcı şifresi **`Turksab2026!`** (mevcut `Demo1234!` yerine). |

## 3. Mevcut durum (kod incelemesi)

- `execute()` **başında `cleanup(silent=True)` çağırır** → tüm demo veriyi silip sıfırdan kurar.
  Bu "sıfırlayan" davranış otomatik/prod için uygun değil.
- Seed **hiçbir yerde otomatik tetiklenmiyor** (ne `hooks.py`, ne `patches.txt`, ne `setup/`).
- `_ensure_user / _ensure_seller / _ensure_buyer / _ensure_category / _ensure_seller_category /
  _ensure_cert_type / _ensure_brand / _ensure_shipping_method / _ensure_product_attribute /
  _ensure_buyer_user_profile` → **idempotent** (create-if-missing; bazıları boş alan upsert eder).
- `_create_listing` → **idempotent DEĞİL**: existence guard yok, her çağrıda `new_doc("Listing")`
  + `insert`. Tekrar çalışınca **ürünleri çiftler**. (Şu an `execute()` öncesi cleanup ile maskeleniyor.)
  Benzersiz kimlik: `seller_profile` + `route = "urun/{slug}"` (slug = `_slug(base_title)`).
- `cleanup()` demo veriyi `DEMO-*` kodu ve `demo-seller-%@istoc.demo` / `demo-buyer-%@istoc.demo`
  e-posta deseniyle filtreler ve **User'ı hard-delete eder** (adım 9).
- Mevcut sayı: **10 satıcı (DEMO-001..010) + 5 alıcı**.

## 4. Tasarım

### 4.1 Yeni satıcılar (DEMO-011..016)

6 yeni satıcı, mevcut sektör/kategorilere bağlanır (yeni kategori YOK → R6 korunur):

| Kod | E-posta | Şirket (varsayılan, spec'te değişebilir) | variant_type/sektör |
|---|---|---|---|
| DEMO-011 | ahmet.seker@turksab.com | Şeker Tekstil | giyim |
| DEMO-012 | ali.bal@turksab.com | Bal Gıda | gida |
| DEMO-013 | bora.aydeger@turksab.com | Aydeğer Elektronik | elektronik |
| DEMO-014 | demo-seller-14@istoc.demo | (jenerik — ayakkabı/deri) | ayakkabi |
| DEMO-015 | demo-seller-15@istoc.demo | (jenerik — kozmetik) | kozmetik |
| DEMO-016 | demo-seller-16@istoc.demo | (jenerik — ev tekstili) | ev_tekstili |

Her yeni satıcı için doldurulacak veri yapıları:
- `SELLERS` — tam profil (company_name, tax_id, iban, certifications, address, commission_rate, vb.).
  tax_id `12345670XX`, iban `...00XX XX` desenini sürdürür.
- `SELLER_LOGO_ICONS` — (icon, renk) çifti.
- `SELLER_FACTORY_IMAGES` — sektöre uygun Pexels foto id listesi (mevcut sektör listelerinden yeniden kullanılabilir).
- `SELLER_CONTACTS` — (ad, soyad) gerçek kişi. İsimli satıcılarda: Ahmet Şeker / Ali Bal / Bora Aydeğer.
- `SELLER_SECTORS` — hangi grup/dj_cat'leri sattığı (mevcut dj_cat'ler; yeni kategori üretmez).
- `DEMO_KYB_STATUSES` — index 10..15 → `"Verified"`.
- Marka: `_ensure_brand` otomatik üretir.

KYB + KYC `execute()`/seed akışındaki mevcut çağrılarla Verified olur (`can_sell=1`).

### 4.2 Idempotency düzeltmesi (`_create_listing`)

`_create_listing` başına guard:

```python
route = f"urun/{slug}"
existing = frappe.db.exists("Listing", {"seller_profile": seller, "route": route})
if existing:
    return existing
```

Böylece tekrar çalıştırmada mevcut listing atlanır, çift kayıt oluşmaz.
(Not: `route` global benzersiz olabilir; `seller_profile + route` çifti satıcı-içi benzersizliği garanti eder
ve yanlış-atlama yapmaz.)

### 4.3 Otomatik tetikleme (`after_migrate` + korumalı entry)

`hooks.py`'ye **ekle** (silme/üzerine yazma yok):

```python
after_migrate = ["tradehub_core.seed_demo_data.run_idempotent_seed"]
```

Yeni entry fonksiyon:

```python
def run_idempotent_seed():
    """after_migrate: site_config.demo_seed_enabled ise demo seed'i
    cleanup ÇAĞIRMADAN idempotent çalıştırır. Hata migrate'i bozmaz."""
    if not frappe.conf.get("demo_seed_enabled"):
        return
    try:
        _seed(cleanup_first=False)   # cleanup'sız idempotent kurulum
    except Exception:
        frappe.log_error(frappe.get_traceback(), "run_idempotent_seed")
```

### 4.4 `execute()` / `cleanup()` ayrıştırması

- Mevcut seed gövdesi `_seed(cleanup_first: bool)` özel fonksiyonuna taşınır.
- `execute()` → `_seed(cleanup_first=True)` (manuel "sıfırla ve yeniden kur" davranışı KORUNUR).
- `run_idempotent_seed()` → `_seed(cleanup_first=False)`.
- `_seed` içindeki `random.seed(42)` korunur; idempotent path'te mevcut kayıtlar atlanacağı için
  yalnızca yeni kayıtlar üretilir.

### 4.5 Gerçek e-posta güvenliği (`cleanup()`)

- Auto path zaten `cleanup()` çağırmaz → 3 isimli hesap otomatikte asla silinmez.
- Manuel `cleanup()` için: 3 isimli e-postanın demo artefaktları (Admin Seller Profile DEMO-011..013,
  Listing, Seller Category, Seller Profile, KYB/KYC) temizlenir; ancak **User hesabı silinmez**
  (cleanup adım 9'daki `demo-seller-%@istoc.demo` deseni bu gerçek e-postaları kapsamaz; ek olarak
  isimli e-postalar User-silme listesinden açıkça hariç tutulur).

### 4.6 Demo şifreleri (R7)

- `DEMO_SELLER_PASSWORD` ve `DEMO_BUYER_PASSWORD` sabitleri `"Turksab2026!"` olur.
- `_ensure_user` her çalıştırmada `update_password(email, password)` çağırdığı için yeni şifre
  **mevcut demo hesaplara da** otomatik yansır (idempotent path dahil).

### 4.7 Site config bayrağı

- beta / RC / prod site_config'lerine `"demo_seed_enabled": 1` eklenir (Press API ile).
- Bayrak yoksa (örn. lokal dev veya başka site) `after_migrate` no-op → güvenli.
- Bu, deploy runbook'una not olarak eklenir (kod değişikliği değil, operasyon adımı).

## 5. Etki / değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `seed_demo_data.py` | 6 satıcı verisi (8 yapı); `_create_listing` guard; `_seed(cleanup_first)` ayrıştırma; `run_idempotent_seed()`; `cleanup()` gerçek-e-posta koruması. |
| `hooks.py` | `after_migrate` ekleme (append). |
| site_config (beta/RC/prod) | `demo_seed_enabled: 1` — operasyon adımı, kod değil. |

## 6. Doğrulama (DoD)

- `python -m py_compile seed_demo_data.py hooks.py` temiz.
- `ruff check` temiz (tab indent, line-length 110).
- Lokal: `docker exec istocc-cd-backend-1 bench --site tradehub.localhost execute
  tradehub_core.seed_demo_data.execute` → 16 satıcı, çift listing yok.
- Lokal idempotency: bayrak set edilip `bench migrate` **iki kez** çalıştırılır → ikinci çalıştırma
  yeni kayıt üretmez, listing sayısı sabit kalır (çiftlenme yok).
- İsimli 3 satıcı: KYB+KYC Verified, can_sell=1, storefront'ta görünür.
- `cleanup()` sonrası `ahmet.seker@turksab.com` User hesabı hâlâ mevcut.

## 7. Kapsam dışı (YAGNI)

- Alıcı sayısı değişmez (5 kalır).
- Mevcut kayıtların alan-düzeyi sürekli upsert'ü yapılmaz (create-if-missing; prod admin
  düzenlemeleri ezilmesin diye). Belirli bir alan/kategori değişimini yaymak gerekirse ayrı
  hedefli patch açılır.
- Yeni kategori/ürün taksonomisi eklenmez.

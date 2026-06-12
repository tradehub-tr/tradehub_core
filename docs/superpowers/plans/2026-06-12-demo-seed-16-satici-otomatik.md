# Demo Seed: 16 Satıcı + Otomatik İdempotent Çalışma — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Demo seed'i 16 satıcıya çıkar ve beta/RC/prod'da deploy'da otomatik + veri silmeden (idempotent) çalışacak hâle getir.

**Architecture:** `seed_demo_data.py` içinde seed gövdesi `_seed(cleanup_first)` fonksiyonuna ayrılır; `execute()` manuel (cleanup'lı) çağırır, yeni `run_idempotent_seed()` cleanup'sız çağırır ve `hooks.py`'deki `after_migrate` ile tetiklenir. `_create_listing`'e idempotency guard eklenir. 6 yeni satıcı (3 isimli gerçek e-posta + 3 jenerik) veri yapılarına eklenir.

**Tech Stack:** Frappe v15 (Python 3.12, tab indent, ruff line-length 110), MariaDB, Docker (`istocc-cd-backend-1`).

---

## Proje kuralları (TÜM task'lar için geçerli)

- **Auto-commit YOK.** Her task sonunda dosya doğrulanır (`py_compile` + `ruff`); commit'i kullanıcı kendi toplu mesajıyla yapar. Önerilen commit mesajı her task'ın sonunda verilir.
- **Tab indent zorunlu** (boşluk değil) — ruff format'tan geçmesi için.
- Bench komutları: `docker exec istocc-cd-backend-1 bench --site tradehub.localhost <cmd>`.
- Dokunulan dosyalar: `tradehub_core/tradehub_core/seed_demo_data.py`, `tradehub_core/tradehub_core/hooks.py`.

## File Structure

| Dosya | Sorumluluk | Değişiklik |
|---|---|---|
| `tradehub_core/tradehub_core/seed_demo_data.py` | Demo veri tanımı + kurulum | Şifre sabitleri; 6 satıcı verisi; `_create_listing` guard; `_seed`/`execute` ayrıştırma; `run_idempotent_seed`; `cleanup` gerçek-e-posta koruması |
| `tradehub_core/tradehub_core/hooks.py` | Frappe hook kayıtları | `after_migrate` append |

---

## Task 1: Demo şifrelerini `Turksab2026!` yap (R7)

**Files:**
- Modify: `tradehub_core/tradehub_core/seed_demo_data.py:30-31`

- [ ] **Step 1: Şifre sabitlerini değiştir**

`seed_demo_data.py` satır 30-31:

```python
DEMO_SELLER_PASSWORD = "Demo1234!"
DEMO_BUYER_PASSWORD = "Demo1234!"
```

→ yeni:

```python
DEMO_SELLER_PASSWORD = "Turksab2026!"
DEMO_BUYER_PASSWORD = "Turksab2026!"
```

- [ ] **Step 2: Doğrula**

```bash
cd "/home/metin/Desktop/istoc cı-cd/tradehub_core"
grep -n 'DEMO_SELLER_PASSWORD\|DEMO_BUYER_PASSWORD' tradehub_core/seed_demo_data.py | head -3
python -m py_compile tradehub_core/seed_demo_data.py && echo "py_compile OK"
```

Beklenen: ilk 2 satır `"Turksab2026!"` gösterir, `py_compile OK`.

- [ ] **Step 3: Commit (kullanıcı yapar)**

Önerilen mesaj: `refactor(seed): demo hesap şifreleri Turksab2026! olarak güncellendi`

---

## Task 2: `_create_listing` idempotency guard (4.2)

**Files:**
- Modify: `tradehub_core/tradehub_core/seed_demo_data.py:3518-3519` (slug/currency satırının hemen ardı)

- [ ] **Step 1: Guard ekle**

`_create_listing` içinde mevcut satırlar (~3517-3519):

```python
	# Slug orijinal başlıktan türetilir — suffix eklemeden, URL kısa kalsın
	slug = _slug(base_title)
	currency = "TRY" if frappe.db.exists("Currency", "TRY") else "USD"
```

Bu bloğun **hemen ardına** ekle:

```python

	# İdempotent guard: aynı satıcı + route için listing zaten varsa yeniden oluşturma
	# (after_migrate her deploy'da çalıştığında çift kayıt oluşmasını engeller).
	# route satıcı-içi benzersiz; aynı ürünü satan iki satıcı route'u paylaşabilir,
	# bu yüzden seller_profile ile birlikte filtrelenir.
	_existing_listing = frappe.db.exists("Listing", {"seller_profile": seller, "route": f"urun/{slug}"})
	if _existing_listing:
		return _existing_listing
```

- [ ] **Step 2: Doğrula**

```bash
cd "/home/metin/Desktop/istoc cı-cd/tradehub_core"
grep -n '_existing_listing = frappe.db.exists' tradehub_core/seed_demo_data.py
python -m py_compile tradehub_core/seed_demo_data.py && echo "py_compile OK"
ruff check tradehub_core/seed_demo_data.py
```

Beklenen: guard satırı bulunur, `py_compile OK`, ruff temiz.

- [ ] **Step 3: Commit (kullanıcı yapar)**

Önerilen mesaj: `fix(seed): _create_listing idempotent — mevcut route'ta çift listing engellendi`

---

## Task 3: 6 yeni satıcı verisi (4.1)

**Files:**
- Modify: `tradehub_core/tradehub_core/seed_demo_data.py` — 6 sözlük/liste: `SELLER_LOGO_ICONS` (67), `SELLER_FACTORY_IMAGES` (109), `SELLERS` (615-926 sonu), `DEMO_KYB_STATUSES` (938-949), `SELLER_SECTORS` (2791-2871 sonu), `SELLER_CONTACTS` (3854)

- [ ] **Step 1: `SELLER_LOGO_ICONS`'a 6 satır ekle**

`SELLER_LOGO_ICONS` sözlüğünde `"DEMO-010": ("boxSeam", "1d4ed8"),` satırının ardına:

```python
	"DEMO-011": ("scissors", "7c3aed"),  # Şeker Tekstil (giyim)
	"DEMO-012": ("basket", "16a34a"),  # Bal Gıda (gıda)
	"DEMO-013": ("laptop", "0284c7"),  # Aydeğer Elektronik (elektronik)
	"DEMO-014": ("handbag", "92400e"),  # Jenerik ayakkabı/deri
	"DEMO-015": ("palette", "db2777"),  # Jenerik kozmetik
	"DEMO-016": ("house", "0d9488"),  # Jenerik ev tekstili
```

- [ ] **Step 2: `SELLER_FACTORY_IMAGES`'a 6 satır ekle**

`SELLER_FACTORY_IMAGES` içinde `"DEMO-010": [36376366, 9550363, 19837529],` satırının ardına (mevcut sektör foto havuzlarını yeniden kullan):

```python
	"DEMO-011": [31091544, 6525848, 31212954, 31112181],  # Tekstil (giyim)
	"DEMO-012": [5953663, 5532664, 18631424, 5953831],  # Gıda üretim hattı
	"DEMO-013": [5554948, 5554949, 36522029, 4211136],  # Elektronik/PCB
	"DEMO-014": [13524733, 30433081, 11463568, 5894231],  # Ayakkabı/deri atölyesi
	"DEMO-015": [15831825, 37650270, 37466061, 20684151],  # Kozmetik laboratuvarı
	"DEMO-016": [31112181, 6525848, 31212954, 31091544],  # Ev tekstili (dokuma)
```

- [ ] **Step 3: `SELLERS` listesine 6 sözlük ekle**

`SELLERS` listesinde son eleman (`DEMO-010` Yıldız Ambalaj) sözlüğünün kapanış `},`'ından sonra, listeyi kapatan `]`'dan **önce** ekle:

```python
	{
		"code": "DEMO-011",
		"seller_name": "Şeker Tekstil",
		"company_name": "Şeker Tekstil Sanayi ve Ticaret A.Ş.",
		"email": "ahmet.seker@turksab.com",
		"sector": "Tekstil ve Giyim",
		"variant_type": "giyim",
		"price_range": (30, 500),
		"description": "Şeker Tekstil, pamuklu örme ve dokuma kumaşta uzmanlaşmış, toptan tekstil üretimi yapan köklü bir firmadır. Geniş renk ve gramaj seçenekleriyle kurumsal alıcılara özel üretim sunar.",
		"slogan": "Pamuğun En Saf Hâli",
		"business_type": "Manufacturer",
		"founded_year": "1997",
		"staff_count": "95",
		"annual_revenue": "38M+ TL",
		"factory_size": "2200 m²",
		"certifications": "ISO 9001, OEKO-TEX Standard 100, GOTS",
		"phone": "+90 212 438 00 11",
		"website": "https://sekertekstil.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 11. Ada No:9",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "Garanti BBVA",
		"iban": "TR00 0001 0000 0000 0000 0011 11",
		"account_holder": "Şeker Tekstil San. Tic. A.Ş.",
		"tax_id": "1234567011",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Pro",
		"commission_rate": 6.5,
		"main_markets": "Türkiye, Almanya, Hollanda",
	},
	{
		"code": "DEMO-012",
		"seller_name": "Bal Gıda",
		"company_name": "Bal Gıda Tarım Ürünleri Tic. A.Ş.",
		"email": "ali.bal@turksab.com",
		"sector": "Gıda ve İçecek",
		"variant_type": "gida",
		"price_range": (10, 250),
		"description": "Bal Gıda, doğal bal, kuruyemiş ve organik bakliyat tedarikinde uzmanlaşmış bir toptancıdır. Üretici köylerden doğrudan tedarik ile rekabetçi fiyat ve izlenebilir kalite sunar.",
		"slogan": "Doğanın Bereketi, Toptan Fiyatla",
		"business_type": "Wholesaler",
		"founded_year": "2004",
		"staff_count": "48",
		"annual_revenue": "22M+ TL",
		"factory_size": "1600 m²",
		"certifications": "ISO 22000, HACCP, Organik Sertifika, Helal",
		"phone": "+90 212 438 00 12",
		"website": "https://balgida.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 12. Ada No:4",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "Ziraat Bankası",
		"iban": "TR00 0001 0000 0000 0000 0012 12",
		"account_holder": "Bal Gıda Tic. A.Ş.",
		"tax_id": "1234567012",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Pro",
		"commission_rate": 5.5,
		"main_markets": "Türkiye, Almanya, BAE",
	},
	{
		"code": "DEMO-013",
		"seller_name": "Aydeğer Elektronik",
		"company_name": "Aydeğer Elektronik Tic. Ltd. Şti.",
		"email": "bora.aydeger@turksab.com",
		"sector": "Elektronik ve Aksesuar",
		"variant_type": "elektronik",
		"price_range": (15, 500),
		"description": "Aydeğer Elektronik, telefon ve bilgisayar aksesuarlarında geniş stok ve hızlı sevkiyat sunan toptancı firmadır. Orijinal ürün garantisi ve kurumsal fatura ile çalışır.",
		"slogan": "Teknolojiye Hızlı Erişim",
		"business_type": "Wholesaler",
		"founded_year": "2009",
		"staff_count": "38",
		"annual_revenue": "27M+ TL",
		"factory_size": "700 m²",
		"certifications": "CE, RoHS, FCC",
		"phone": "+90 212 438 00 13",
		"website": "https://aydegerelektronik.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 13. Ada No:21",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "Yapı Kredi",
		"iban": "TR00 0001 0000 0000 0000 0013 13",
		"account_holder": "Aydeğer Elektronik Tic. Ltd. Şti.",
		"tax_id": "1234567013",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Pro",
		"commission_rate": 8.0,
		"main_markets": "Türkiye, Orta Doğu",
	},
	{
		"code": "DEMO-014",
		"seller_name": "Anadolu Ayakkabı",
		"company_name": "Anadolu Ayakkabı ve Deri San. Tic. A.Ş.",
		"email": "demo-seller-14@istoc.demo",
		"sector": "Ayakkabı ve Deri",
		"variant_type": "ayakkabi",
		"price_range": (80, 1500),
		"description": "Anadolu Ayakkabı, klasik ve günlük deri ayakkabı üretiminde el işçiliğiyle öne çıkan bir üretici firmadır. Toptan alımlarda özel kalıp ve renk seçenekleri sunar.",
		"slogan": "Adımlarınıza Değer Katan Kalite",
		"business_type": "Manufacturer",
		"founded_year": "1994",
		"staff_count": "72",
		"annual_revenue": "30M+ TL",
		"factory_size": "1500 m²",
		"certifications": "ISO 9001, CE, Deri Sertifikası",
		"phone": "+90 212 438 00 14",
		"website": "https://anadoluayakkabi.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 14. Ada No:7",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "İş Bankası",
		"iban": "TR00 0001 0000 0000 0000 0014 14",
		"account_holder": "Anadolu Ayakkabı San. Tic. A.Ş.",
		"tax_id": "1234567014",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Pro",
		"commission_rate": 7.0,
		"main_markets": "Türkiye, Rusya, Irak",
	},
	{
		"code": "DEMO-015",
		"seller_name": "Lale Kozmetik",
		"company_name": "Lale Kozmetik ve Kişisel Bakım San. A.Ş.",
		"email": "demo-seller-15@istoc.demo",
		"sector": "Kozmetik ve Kişisel Bakım",
		"variant_type": "kozmetik",
		"price_range": (15, 400),
		"description": "Lale Kozmetik, cilt bakımı ve makyaj ürünlerinde yerli üretim yapan, dermatolojik test standartlarına uygun bir üretici firmadır. Özel marka (private label) üretimine açıktır.",
		"slogan": "Bakımın İnce Dokunuşu",
		"business_type": "Manufacturer",
		"founded_year": "2006",
		"staff_count": "64",
		"annual_revenue": "24M+ TL",
		"factory_size": "1400 m²",
		"certifications": "ISO 22716 (GMP), ISO 9001, Cruelty-Free",
		"phone": "+90 212 438 00 15",
		"website": "https://lalekozmetik.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 15. Ada No:13",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "Akbank",
		"iban": "TR00 0001 0000 0000 0000 0015 15",
		"account_holder": "Lale Kozmetik San. A.Ş.",
		"tax_id": "1234567015",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Pro",
		"commission_rate": 8.0,
		"main_markets": "Türkiye, Rusya, Kazakistan",
	},
	{
		"code": "DEMO-016",
		"seller_name": "Marmara Ev Tekstili",
		"company_name": "Marmara Ev Tekstili San. Tic. A.Ş.",
		"email": "demo-seller-16@istoc.demo",
		"sector": "Ev Tekstili ve Dekorasyon",
		"variant_type": "ev_tekstili",
		"price_range": (25, 800),
		"description": "Marmara Ev Tekstili, nevresim, havlu ve dekoratif ev ürünlerinde modern koleksiyonlar sunan bir üretici firmadır. Yüksek iplik kalitesi ve dayanıklı boya teknolojisiyle öne çıkar.",
		"slogan": "Evinizin Sıcak Dokusu",
		"business_type": "Manufacturer",
		"founded_year": "1999",
		"staff_count": "88",
		"annual_revenue": "33M+ TL",
		"factory_size": "2600 m²",
		"certifications": "ISO 9001, OEKO-TEX Standard 100, GOTS",
		"phone": "+90 212 438 00 16",
		"website": "https://marmaraev.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 16. Ada No:6",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "Garanti BBVA",
		"iban": "TR00 0001 0000 0000 0000 0016 16",
		"account_holder": "Marmara Ev Tekstili San. Tic. A.Ş.",
		"tax_id": "1234567016",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Pro",
		"commission_rate": 6.5,
		"main_markets": "Türkiye, Almanya, Fransa",
	},
```

- [ ] **Step 4: `DEMO_KYB_STATUSES`'a 6 index ekle**

`DEMO_KYB_STATUSES` sözlüğünde `9: "Verified",  # Yıldız Ambalaj ve Kırtasiye` satırının ardına:

```python
	10: "Verified",  # Şeker Tekstil
	11: "Verified",  # Bal Gıda
	12: "Verified",  # Aydeğer Elektronik
	13: "Verified",  # Anadolu Ayakkabı
	14: "Verified",  # Lale Kozmetik
	15: "Verified",  # Marmara Ev Tekstili
```

- [ ] **Step 5: `SELLER_SECTORS`'a 6 satır ekle (mevcut dj_cat'leri yeniden kullan — yeni kategori YOK)**

`SELLER_SECTORS` sözlüğünde `DEMO-010` bloğunun kapanış `},`'ından sonra, sözlüğü kapatan `}`'dan önce:

```python
	"DEMO-011": {
		"sector_name": "Tekstil ve Giyim",
		"sector_code": "TG",
		"groups": [
			("Erkek Giyim", ["mens-shirts"]),
			("Kadın Giyim", ["tops", "womens-dresses"]),
		],
	},
	"DEMO-012": {
		"sector_name": "Gıda ve İçecek",
		"sector_code": "GD",
		"groups": [
			("Market", ["groceries"]),
		],
	},
	"DEMO-013": {
		"sector_name": "Elektronik ve Aksesuar",
		"sector_code": "EL",
		"groups": [
			("Telefon", ["smartphones", "mobile-accessories"]),
			("Bilgisayar", ["laptops", "tablets"]),
		],
	},
	"DEMO-014": {
		"sector_name": "Ayakkabı ve Deri",
		"sector_code": "AD",
		"groups": [
			("Erkek Ayakkabı", ["mens-shoes"]),
			("Kadın Ayakkabı", ["womens-shoes"]),
			("Çantalar", ["womens-bags"]),
		],
	},
	"DEMO-015": {
		"sector_name": "Kozmetik ve Kişisel Bakım",
		"sector_code": "KZ",
		"groups": [
			("Makyaj ve Bakım", ["beauty", "skin-care"]),
			("Parfüm", ["fragrances"]),
		],
	},
	"DEMO-016": {
		"sector_name": "Ev Tekstili ve Dekorasyon",
		"sector_code": "EV",
		"groups": [
			("Dekorasyon", ["home-decoration"]),
			("Mobilya", ["furniture"]),
		],
	},
```

- [ ] **Step 6: `SELLER_CONTACTS`'a 6 satır ekle**

Önce mevcut yapıyı oku (gerçek anahtar/format için):

```bash
cd "/home/metin/Desktop/istoc cı-cd/tradehub_core"
sed -n '3854,3880p' tradehub_core/seed_demo_data.py
```

`SELLER_CONTACTS` sözlüğünün son `DEMO-010` satırının ardına (mevcut `(first, last)` tuple formatını izle):

```python
	"DEMO-011": ("Ahmet", "Şeker"),
	"DEMO-012": ("Ali", "Bal"),
	"DEMO-013": ("Bora", "Aydeğer"),
	"DEMO-014": ("Murat", "Kaya"),
	"DEMO-015": ("Elif", "Demir"),
	"DEMO-016": ("Selin", "Yıldız"),
```

> Not: Step 6'daki tam tuple formatını Step 6 başındaki `sed` çıktısıyla doğrula; format farklıysa ona uydur.

- [ ] **Step 7: Doğrula**

```bash
cd "/home/metin/Desktop/istoc cı-cd/tradehub_core"
grep -c '"code": "DEMO-0' tradehub_core/seed_demo_data.py   # 16 beklenir
grep -n 'DEMO-011\|DEMO-016' tradehub_core/seed_demo_data.py | head
python -m py_compile tradehub_core/seed_demo_data.py && echo "py_compile OK"
ruff check tradehub_core/seed_demo_data.py
```

Beklenen: `16`, DEMO-011/016 her yapıda görünür, `py_compile OK`, ruff temiz.

- [ ] **Step 8: Commit (kullanıcı yapar)**

Önerilen mesaj: `feat(seed): 6 yeni demo satıcı eklendi (16 satıcı) — 3 isimli onaylı KYB/KYC`

---

## Task 4: `_seed(cleanup_first)` ayrıştırma + `execute()` wrapper (4.4)

**Files:**
- Modify: `tradehub_core/tradehub_core/seed_demo_data.py` — `execute()` (4540), oto-temizlik bloğu (4567-4570)

- [ ] **Step 1: `execute()` permission check sonrasını `_seed`'e böl**

Mevcut kod (~4553-4559):

```python
	if not frappe.session.user == "Administrator" and not frappe.has_permission(
		"Admin Seller Profile", "create"
	):
		frappe.throw(_("Bu işlem için Administrator yetkisi gereklidir."))
	frappe.flags.ignore_permissions = True
	frappe.flags.in_import = True
	random.seed(42)  # Tekrarlanabilir sonuçlar
```

→ yeni (permission check execute'ta kalır, gerisi `_seed`'e taşınır):

```python
	if not frappe.session.user == "Administrator" and not frappe.has_permission(
		"Admin Seller Profile", "create"
	):
		frappe.throw(_("Bu işlem için Administrator yetkisi gereklidir."))
	return _seed(cleanup_first=True)


def _seed(cleanup_first=True):
	"""Demo veriyi kur.

	cleanup_first=True  → önce mevcut demo veriyi siler, sonra sıfırdan kurar
	                      (manuel `execute()` davranışı — deterministik reset).
	cleanup_first=False → hiçbir şey silmez; yalnız eksik kayıtları ekler
	                      (after_migrate idempotent path). Tüm `_ensure_*` fonksiyonları
	                      ve `_create_listing` create-if-missing olduğundan güvenlidir.
	"""
	frappe.flags.ignore_permissions = True
	frappe.flags.in_import = True
	random.seed(42)  # Tekrarlanabilir sonuçlar
```

- [ ] **Step 2: Oto-temizlik bloğunu `cleanup_first`'e bağla**

Mevcut kod (~4567-4570):

```python
	# ── −1. Oto-temizlik: eski demo verileri kaldır ───────────
	print("\n[Oto-temizlik] Önceki demo veriler kaldırılıyor...")
	cleanup(silent=True)
	frappe.db.commit()
```

→ yeni:

```python
	# ── −1. Oto-temizlik: yalnız cleanup_first=True iken eski demo verileri kaldır ──
	if cleanup_first:
		print("\n[Oto-temizlik] Önceki demo veriler kaldırılıyor...")
		cleanup(silent=True)
		frappe.db.commit()
```

- [ ] **Step 3: Doğrula (girinti + derleme)**

```bash
cd "/home/metin/Desktop/istoc cı-cd/tradehub_core"
grep -n 'def _seed(cleanup_first' tradehub_core/seed_demo_data.py
grep -n 'return _seed(cleanup_first=True)' tradehub_core/seed_demo_data.py
grep -n 'if cleanup_first:' tradehub_core/seed_demo_data.py
python -m py_compile tradehub_core/seed_demo_data.py && echo "py_compile OK"
ruff check tradehub_core/seed_demo_data.py
```

Beklenen: `_seed` tanımı + wrapper + conditional bulunur, `py_compile OK`, ruff temiz. (İç gövdenin girintisi zaten 1-tab; `_seed` de modül seviyesinde olduğu için gövde girintisi değişmez — sadece üstüne yeni `def` eklenir.)

- [ ] **Step 4: Commit (kullanıcı yapar)**

Önerilen mesaj: `refactor(seed): seed gövdesi _seed(cleanup_first) fonksiyonuna ayrıldı`

---

## Task 5: `run_idempotent_seed()` entry + `after_migrate` hook (4.3)

**Files:**
- Modify: `tradehub_core/tradehub_core/seed_demo_data.py` — `_seed` gövdesinin bittiği yerin ardına (yeni fonksiyon)
- Modify: `tradehub_core/tradehub_core/hooks.py` — `after_migrate` append

- [ ] **Step 1: `_seed` gövdesinin nerede bittiğini bul**

`_seed`'in son satırları, mevcut `execute()`'ın "DEMO GİRİŞ BİLGİLERİ" tablosunun bittiği yer (`print("═" * 76)` + `print()`). Hemen ardından `def verify_email(...)` gelir. Konumu doğrula:

```bash
cd "/home/metin/Desktop/istoc cı-cd/tradehub_core"
grep -n 'def verify_email(user_email)' tradehub_core/seed_demo_data.py
```

- [ ] **Step 2: `run_idempotent_seed()` fonksiyonunu ekle**

`@frappe.whitelist()` + `def verify_email(...)` satırlarının **hemen üstüne** (yani `_seed` bittikten sonra, `verify_email`'den önce) ekle:

```python
def run_idempotent_seed():
	"""after_migrate hook: site_config.demo_seed_enabled=1 olan sitelerde demo
	seed'i cleanup ÇAĞIRMADAN idempotent çalıştırır.

	- Bayrak yoksa no-op (lokal dev / ilgisiz siteler güvende).
	- Hata migrate'i bozmasın diye geniş try/except + frappe.log_error.
	  (Anti-pattern istisnası: after_migrate'de hata yutmak deploy'u korur; log var.)
	"""
	if not frappe.conf.get("demo_seed_enabled"):
		return
	try:
		_seed(cleanup_first=False)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "run_idempotent_seed başarısız")


```

- [ ] **Step 3: `hooks.py`'de mevcut `after_migrate` var mı kontrol et**

```bash
cd "/home/metin/Desktop/istoc cı-cd/tradehub_core"
grep -n 'after_migrate' tradehub_core/hooks.py
```

- [ ] **Step 4: `after_migrate` ekle**

Eğer Step 3 **boş** döndüyse (mevcut yok), `hooks.py`'ye yeni satır ekle (dosyada `scheduler_events` veya `doc_events` bloğunun yakınına, mantıklı bir yere):

```python
after_migrate = ["tradehub_core.seed_demo_data.run_idempotent_seed"]
```

Eğer Step 3 **mevcut bir `after_migrate`** gösterdiyse (silme/üzerine yazma YASAK — append et): mevcut listeye string'i ekle. Örn. mevcut `after_migrate = ["x.y.z"]` ise → `after_migrate = ["x.y.z", "tradehub_core.seed_demo_data.run_idempotent_seed"]`.

- [ ] **Step 5: Doğrula**

```bash
cd "/home/metin/Desktop/istoc cı-cd/tradehub_core"
grep -n 'def run_idempotent_seed' tradehub_core/seed_demo_data.py
grep -n 'after_migrate' tradehub_core/hooks.py
python -m py_compile tradehub_core/seed_demo_data.py tradehub_core/hooks.py && echo "py_compile OK"
ruff check tradehub_core/seed_demo_data.py tradehub_core/hooks.py
```

Beklenen: fonksiyon + hook bulunur, `py_compile OK`, ruff temiz.

- [ ] **Step 6: Commit (kullanıcı yapar)**

Önerilen mesaj: `feat(seed): after_migrate ile otomatik idempotent demo seed (demo_seed_enabled bayrağı)`

---

## Task 6: `cleanup()` gerçek e-posta koruması (4.5)

**Files:**
- Modify: `tradehub_core/tradehub_core/seed_demo_data.py` — `cleanup()` (4914) içindeki e-posta filtreli sorgular

**Amaç:** Manuel `cleanup()` 3 isimli satıcının demo artefaktlarını (Seller Application, KYB, Seller Profile, KYC, User Profile) da temizlesin; ama gerçek **User hesabı silinmesin** (cleanup adım 9, `demo-seller-%@istoc.demo` deseni zaten bu gerçek e-postaları kapsamaz — değiştirme).

- [ ] **Step 1: İsimli e-posta sabitini ekle**

`seed_demo_data.py`'de `DEMO_KYB_DOC_FIELDS` tanımının (~966-973) ardına, modül seviyesinde:

```python
# Demo satıcı olarak kullanılan GERÇEK ekip e-postaları (demo-seller-%@istoc.demo
# desenine uymaz). cleanup() bunların demo artefaktlarını temizler AMA User hesabını
# ASLA silmez (gerçek login korunur).
NAMED_DEMO_SELLER_EMAILS = [
	"ahmet.seker@turksab.com",
	"ali.bal@turksab.com",
	"bora.aydeger@turksab.com",
]
```

- [ ] **Step 2: Seller Application sorgusuna isimli e-postaları ekle**

`cleanup()` adım 5a (~5013-5021):

```python
	demo_apps = frappe.get_all(
		"Seller Application",
		filters={"applicant_user": ["like", "demo-seller-%@istoc.demo"]},
		pluck="name",
	)
```

→ yeni (pattern + isimli e-postaları birleştir):

```python
	demo_apps = frappe.get_all(
		"Seller Application",
		filters={"applicant_user": ["like", "demo-seller-%@istoc.demo"]},
		pluck="name",
	)
	demo_apps += frappe.get_all(
		"Seller Application",
		filters={"applicant_user": ["in", NAMED_DEMO_SELLER_EMAILS]},
		pluck="name",
	)
	demo_apps = list(set(demo_apps))
```

- [ ] **Step 3: KYB Verification sorgusuna ekle**

Adım 5b (~5024-5031) `demo_kyb` sorgusunu aynı kalıpla genişlet:

```python
	demo_kyb = frappe.get_all(
		"KYB Verification",
		filters={"user": ["like", "demo-seller-%@istoc.demo"]},
		pluck="name",
	)
	demo_kyb += frappe.get_all(
		"KYB Verification",
		filters={"user": ["in", NAMED_DEMO_SELLER_EMAILS]},
		pluck="name",
	)
	demo_kyb = list(set(demo_kyb))
```

- [ ] **Step 4: Seller Profile sorgusuna ekle**

Adım 5c (~5034-5041) `demo_seller_profiles`:

```python
	demo_seller_profiles = frappe.get_all(
		"Seller Profile",
		filters={"user": ["like", "demo-seller-%@istoc.demo"]},
		pluck="name",
	)
	demo_seller_profiles += frappe.get_all(
		"Seller Profile",
		filters={"user": ["in", NAMED_DEMO_SELLER_EMAILS]},
		pluck="name",
	)
	demo_seller_profiles = list(set(demo_seller_profiles))
```

- [ ] **Step 5: KYC Verification sorgusuna ekle**

Adım 6a (~5054-5064) `kyc_sellers` listesine union ekle (mevcut `demo_kyc = list(set(kyc_sellers + kyc_buyers))` satırından önce):

```python
	kyc_sellers += frappe.get_all(
		"KYC Verification",
		filters={"user": ["in", NAMED_DEMO_SELLER_EMAILS]},
		pluck="name",
	)
```

- [ ] **Step 6: User Profile sorgusuna ekle**

Adım 6b (~5070-5080) `up_sellers` listesine union ekle (mevcut `demo_user_profiles = list(set(up_sellers + up_buyers))` satırından önce):

```python
	up_sellers += frappe.get_all(
		"User Profile",
		filters={"user": ["in", NAMED_DEMO_SELLER_EMAILS]},
		pluck="name",
	)
```

- [ ] **Step 7: User silme adımını DEĞİŞTİRME (gerçek hesap korunur)**

Adım 9 (~5106-5111) `demo-seller-%@istoc.demo` desenini KORU — isimli e-postaları **ekleme**. Bu, `ahmet.seker@turksab.com` gibi gerçek User'ların silinmemesini garanti eder. (Değişiklik yapılmıyor; doğrulama için kontrol et.)

```bash
cd "/home/metin/Desktop/istoc cı-cd/tradehub_core"
sed -n '5105,5112p' tradehub_core/seed_demo_data.py
```

Beklenen: User sorgusu yalnız `demo-seller-%@istoc.demo` / `demo-buyer-%@istoc.demo` desenlerini içerir; `NAMED_DEMO_SELLER_EMAILS` burada GEÇMEZ.

- [ ] **Step 8: Doğrula**

```bash
cd "/home/metin/Desktop/istoc cı-cd/tradehub_core"
grep -n 'NAMED_DEMO_SELLER_EMAILS' tradehub_core/seed_demo_data.py
# User silme adımında geçmediğini doğrula: aşağıdaki çıktı, adım 9 satır no'sundan KÜÇÜK olmalı
python -m py_compile tradehub_core/seed_demo_data.py && echo "py_compile OK"
ruff check tradehub_core/seed_demo_data.py
```

Beklenen: sabit tanımı + 5 sorgu union'ı bulunur; `py_compile OK`; ruff temiz. `NAMED_DEMO_SELLER_EMAILS` referansları yalnız tanım + 5 union (Seller Application, KYB, Seller Profile, KYC, User Profile) = toplam 6 kullanım; User silme adımında yok.

- [ ] **Step 9: Commit (kullanıcı yapar)**

Önerilen mesaj: `fix(seed): cleanup isimli satıcı artefaktlarını temizler, gerçek User hesabını korur`

---

## Task 7: Uçtan uca doğrulama (DoD)

**Files:** (yok — sadece çalıştırma/doğrulama)

> Bu task lokal Docker stack çalışıyorken yapılır. Çalışmıyorsa `docker compose up -d` ile başlat.

- [ ] **Step 1: Tam manuel seed (cleanup'lı) çalıştır**

```bash
docker exec istocc-cd-backend-1 bench --site tradehub.localhost execute tradehub_core.seed_demo_data.execute
```

Beklenen çıktı: "Satıcılar: 16", "Alıcılar: 5", giriş bilgileri tablosunda 16 satıcı + `Turksab2026!` şifresi, hata yok.

- [ ] **Step 2: Satıcı sayısını + isimli hesapları DB'den doğrula**

```bash
docker exec istocc-cd-backend-1 bench --site tradehub.localhost execute frappe.client.get_count --kwargs "{'doctype': 'Admin Seller Profile', 'filters': {'seller_code': ['like', 'DEMO-%']}}"
```

Beklenen: `16`.

İsimli satıcıların KYC/can_sell durumu (User Profile üzerinden):

```bash
docker exec istocc-cd-backend-1 bench --site tradehub.localhost execute frappe.client.get_value --kwargs "{'doctype': 'User Profile', 'filters': {'user': 'ahmet.seker@turksab.com'}, 'fieldname': ['can_sell', 'kyc_status', 'kyb_status']}"
```

Beklenen: `can_sell=1`, `kyc_status='Verified'`, `kyb_status='Verified'` (seed akışına göre).

- [ ] **Step 3: İdempotency — bayrağı set et ve `run_idempotent_seed`'i İKİ kez çalıştır**

```bash
# Listing sayısını al
docker exec istocc-cd-backend-1 bench --site tradehub.localhost execute frappe.client.get_count --kwargs "{'doctype': 'Listing', 'filters': {'seller_profile': ['like', 'DEMO-%']}}"
# Bayrağı set et
docker exec istocc-cd-backend-1 bench --site tradehub.localhost set-config demo_seed_enabled 1
# İdempotent seed'i 2 kez çalıştır
docker exec istocc-cd-backend-1 bench --site tradehub.localhost execute tradehub_core.seed_demo_data.run_idempotent_seed
docker exec istocc-cd-backend-1 bench --site tradehub.localhost execute tradehub_core.seed_demo_data.run_idempotent_seed
# Listing sayısını tekrar al — DEĞİŞMEMELİ
docker exec istocc-cd-backend-1 bench --site tradehub.localhost execute frappe.client.get_count --kwargs "{'doctype': 'Listing', 'filters': {'seller_profile': ['like', 'DEMO-%']}}"
```

Beklenen: ilk ve son Listing sayısı **eşit** (çift kayıt yok). İdempotency kanıtlandı.

- [ ] **Step 4: `migrate` ile uçtan uca otomatik tetikleme**

```bash
docker exec istocc-cd-backend-1 bench --site tradehub.localhost migrate 2>&1 | tail -20
docker exec istocc-cd-backend-1 bench --site tradehub.localhost execute frappe.client.get_count --kwargs "{'doctype': 'Listing', 'filters': {'seller_profile': ['like', 'DEMO-%']}}"
```

Beklenen: migrate hatasız biter (after_migrate `run_idempotent_seed` çalışır); Listing sayısı Step 3'tekiyle aynı.

- [ ] **Step 5: `cleanup()` gerçek-hesap korumasını doğrula**

```bash
docker exec istocc-cd-backend-1 bench --site tradehub.localhost execute tradehub_core.seed_demo_data.cleanup
# Gerçek User hâlâ var mı?
docker exec istocc-cd-backend-1 bench --site tradehub.localhost execute frappe.client.get_value --kwargs "{'doctype': 'User', 'filters': {'email': 'ahmet.seker@turksab.com'}, 'fieldname': 'email'}"
```

Beklenen: cleanup sonrası `ahmet.seker@turksab.com` User'ı **hâlâ mevcut** (email döner, None değil). Sonra Step 1'i tekrar çalıştırıp veriyi geri yükle.

- [ ] **Step 6: Operasyon notu (prod/RC/beta)**

`demo_seed_enabled` bayrağı beta/RC/prod site_config'lerine eklenmeli (Press API / `bench set-config`). Bu kod değil operasyon adımı — deploy runbook'una not düş ve kullanıcıyı bilgilendir. Bayrak set edilmezse `after_migrate` no-op olur.

---

## Self-Review (plan yazarı tarafından dolduruldu)

**Spec kapsama:** R1 (16 satıcı) → Task 3; R2 (isimli satıcılar) → Task 3; R3 (after_migrate) → Task 5; R4 (idempotent) → Task 2+4; R5 (gerçek e-posta) → Task 6; R6 (kategoriler sabit) → Task 3 Step 5 (mevcut dj_cat reuse); R7 (şifre) → Task 1. Tüm gereksinimler karşılandı.

**Placeholder taraması:** Tüm kod blokları somut; "TBD/TODO" yok. SELLER_CONTACTS formatı Step 6'da `sed` ile doğrulanıyor (mevcut format farklıysa uyarlanır).

**Tip tutarlılığı:** `_seed(cleanup_first=...)` imzası Task 4'te tanımlı, Task 5'te aynı imzayla çağrılıyor. `NAMED_DEMO_SELLER_EMAILS` Task 6 Step 1'de tanımlı, Step 2-6'da kullanılıyor. `run_idempotent_seed` Task 5'te tanımlı, hooks + Task 7'de aynı isimle çağrılıyor.

---

## Uygulama sapmaları (canlı doğrulamada keşfedildi — 2026-06-12)

Plan yazıldıktan sonra lokal `bench execute` ile gerçek-veri çakışmaları ortaya çıktı; iki ek değişiklik gerekti:

1. **`_ensure_seller` convert-via-rename** — `ahmet.seker@turksab.com` LOKALDE zaten aktif satıcıydı ("Turksab", `SEL-00011`, System User). `Admin Seller Profile.user` UNIQUE olduğu için DEMO-011 insert'i `IntegrityError` verdi. Kullanıcı kararı: mevcut profili **dönüştür**. Eklenen mantık: aynı user farklı kodla varsa `frappe.rename_doc(eski → s["code"], force=True)` + child table'ları temizleyip demo alanlarıyla `save()` (yeni ise `insert()`). İlk çalıştırmada dönüşür, sonra DEMO-011 var → erken çık (idempotent). `rename_doc` `ignore_permissions` kwarg'ı KABUL ETMEZ — `frappe.flags.ignore_permissions` (zaten set) yeterli.

2. **`cleanup()` `tradehub_tenant` dangling-link temizliği** — dönüşüm `User.tradehub_tenant` (custom Link → Admin Seller Profile) = DEMO-011 yapıyor. cleanup DEMO-011 profilini siler ama User'ı korur → dangling link → sonraki `_ensure_user` save'i `LinkValidationError`. Fix: cleanup, Admin Seller Profile silindikten sonra `NAMED_DEMO_SELLER_EMAILS` User'larının `tradehub_tenant`'ını `None` yapar (`update_modified=False`).

**Doğrulama sonuçları:** execute→16 satıcı; run_idempotent_seed ×2 → listing 316 sabit (çift yok); `bench migrate` → after_migrate seed'i çalıştırdı, 16/316 sabit; cleanup→ahmet User korundu; cleanup→execute ardışık döngü temiz. ahmet = DEMO-011 "Şeker Tekstil", can_sell=1, KYB/KYC Verified.

> Not: `migrate` sonrası geçici `QueryDeadlockError (tabDocShare 1020)` kodla ilgisiz — eşzamanlı worker/scheduler erişimi; retry'da geçer.

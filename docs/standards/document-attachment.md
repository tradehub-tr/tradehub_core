# Standart — `document.attachment` (Belge / sertifika eki)

> **Güncel karar — 2026-08-23.** Makine kaynağı
> `tradehub_core/media/pipeline/policy/slots/document-attachment.json` şemaya
> uyumludur; `standard_status=fixed`, açık soru sayısı 0 ve gerçek uyum ölçümü
> kayıtlıdır. `status=draft` yalnız Faz 3 rollout durumudur; aşağıdaki durum
> satırı 2026-08-17 anlık görüntüsüdür.

**Görev:** T-023 · **Tarih:** 2026-08-17 · **Branch:** `medya-motoru-faz0-faz2`
**Politika dosyası:** `tradehub_core/media/pipeline/policy/slots/document-attachment.json`
**Tarihsel durum:** `draft` — ama **gövdesi zaten üretimde çalışıyordu.**

> **Bu belge yeni bir kural tasarlamıyor.** `tradehub_core/api/v1/kyb.py:411-501`
> kod tabanının **en sıkı yükleme kuralını** zaten uyguluyor: uzantı allowlist +
> magic-byte tespiti + uzantı/içerik eşleşmesi + 10 MB tavanı + private
> depolama + doğru attach hedefi + yetki kapısı + rate limit.
> Bu belgenin işi (1) o kuralı standarda taşımak, (2) aynı kuralı **almayan** 7
> kardeş slotu işaretlemek, (3) belge slotunun **gösterim değil okunabilirlik**
> slotu olduğunu piksel hesabıyla göstermek.

---

## 1. Referans uygulama — `kyb.upload_kyb_document`

`tradehub_core/api/v1/kyb.py:411-501`, çalışma sırası:

| # | Kural | Satır |
|---|---|---|
| 1 | Yetki kapısı `require_seller_capability("kyb.submit")` | `:427-429` |
| 2 | Guest reddi (`frappe.AuthenticationError`) | `:431-433` |
| 3 | Rate limit 20 istek / 300 sn, `key="user"` | `:412` |
| 4 | Dosya bilgisi eksikse ret | `:435-436` |
| 5 | Uzantı allowlist — `KYB_ALLOWED_EXTENSIONS` | `:19`, kontrol `:438-443` |
| 6 | data-URI öneki soyma + base64 çözme | `:445-451` |
| 7 | 10 MB tavanı — `KYB_MAX_BYTES` | `:20`, kontrol `:453-454` |
| 8 | İçerik < 12 bayt → ret | `:27-28` |
| 9 | Magic-byte tespiti (`_detect_format`) | `:23-58`, çağrı `:458` |
| 10 | Uzantı ↔ içerik eşleşmesi (`expected_match`) | `:460-478` |
| 11 | `is_private=1` File doc | `:423` (docstring), `:479+` |
| 12 | File'ı **KYB Verification'a** attach (User'a değil) | `:479-501` |
| 13 | Kayıt yoksa Draft KYB otomatik oluştur (`ignore_mandatory`) | `:483-501` |

### Magic-byte imzaları (`kyb.py:23-58`)

| Biçim | İmza |
|---|---|
| PDF | `%PDF-` (bayt 0-4) |
| JPEG | `FF D8 FF` (bayt 0-2) |
| PNG | `89 50 4E 47 0D 0A 1A 0A` (bayt 0-7) |
| WEBP | `RIFF` (0-3) **ve** `WEBP` (8-11) |
| DOCX | `PK\x03\x04` **ve** ZIP içinde `[Content_Types].xml` **ve** `word/` klasörü |

> DOCX kontrolü tek başına ZIP magic'e güvenmiyor (`:46-53` yorumu): kullanıcı
> `.zip`'i `.docx` uzantılı yükleyebilir. Bu, tekrar keşfedilmemesi gereken bir
> ayrıntı.

### Attach hedefi kararı — kaydedilmesi gereken bulgu

`kyb.py:479-495` yorumu: File `User`'a attach edilirse Frappe'nin private-file
izin kontrolünde **satıcı kendi belgesine 403 alıyor**. `KYB Verification`'a
attach edilince `if_owner=1` sayesinde erişiyor. Bu, gelecekte "neden User'a
attach etmiyoruz?" sorusunun cevabıdır.

---

## 2. Kapsanan alanlar ve koruma seviyesi

| doctype.field | L1 var mı | `EXCLUDED_DOCTYPES` | `EXCLUDED_MEDIA_FIELDS` |
|---|---|---|---|
| `KYB Verification.identity_document` | ✅ | ✅ `presets.py:45` | ✅ `presets.py:73` |
| `KYB Verification.imza_sirkuleri` | ✅ | ✅ | ❌ |
| `KYB Verification.ticaret_sicil_gazetesi` | ✅ | ✅ | ❌ |
| `KYB Verification.faaliyet_belgesi` | ✅ | ✅ | ❌ |
| `KYB Verification.vergi_levhasi` | ✅ | ✅ | ❌ |
| `KYB Verification.bank_account_document` | ✅ | ✅ | ✅ `presets.py:73` |
| `KYC Verification.identity_document` | ❌ | ✅ `presets.py:46` | ✅ `presets.py:71` |
| `Seller Application.identity_document` | ❌ | ✅ `presets.py:49` | ✅ `presets.py:72` |
| `Seller Certification.document` | ❌ | ✅ `presets.py:47` | ✅ `presets.py:74` |
| `Seller Verification.document` | ❌ | ✅ `presets.py:48` | ✅ `presets.py:75` |
| `Shipment Document.file` | ❌ | **❌** | ❌ |
| `Data Processing Agreement.document` | ❌ | **❌** | ❌ |
| `Order.receipt_url` | ❌ | ✅ `presets.py:50` | ❌ |
| `Payment Transaction.receipt_url` | ❌ | ✅ `presets.py:51` | ❌ |

**İki koyu ❌ satırı en somut boşluk:** `Shipment Document.file` (sevk
irsaliyesi / POD) ve `Data Processing Agreement.document` (imzalı KVKK
sözleşmesi) hem L1 almıyor hem optimizasyon muafiyet listesinde **yok** →
görsel olarak taranmışlarsa **küçültülüyorlar** (§3.3).

### L1 almayan 7 slot yalnız L0'a güveniyor

`tradehub_core/hooks.py:227-252` → `utils/security.py:68,90,96` →
`media/upload_policy.py:307`:
yasak uzantı listesi (`utils/security.py:90`), dosya adı temizliği
(`upload_policy.py:272-291`), belge tavanı 50 MB (`:73`), ilk 512 baytta
tehlikeli içerik (`:187-224`). Uzantı/içerik uyuşmazlığı L0'da **yalnız uyarı**
(`:366-369`).

### KYC ucu neden farklı

`tradehubfront/src/components/kyc/KycLayout.ts:376` doğrudan
`/api/method/upload_file`'a gidiyor → magic-byte kontrolü **yok**. İstemci
tarafı: 10 MB (`:370`), `accept=".pdf,.jpg,.jpeg,.png,.webp,.docx"` (`:369`),
**`compress: false`** (`:381`).

---

## 3. Piksel hesabı — bu bir gösterim slotu DEĞİL

### 3.1 Render kutusu belgeyi değil küçük resmini gösteriyor

| Render noktası | Dosya:satır | CSS kutu |
|---|---|---|
| SlotDropzone belge kartı | `lib/upload-ui/facades/SlotDropzone.ts:95`, grid `:76` | yükseklik **160 px** (`h-40`), mobil **128 px** (`max-sm:h-32`); genişlik `grid-cols-1 sm:2 lg:3 gap-6` içinde container-boxed'dan |
| Panel önizleme kartı | `admin-panel/.../DocTypeFormView.vue:512` | **240×160** (`w-60 h-40`) |
| Panel alt tablo satırı | `admin-panel/.../DocTypeFormView.vue:862` | **40×40** (`w-10 h-10`) |
| Sertifika rozeti (belge **değil**) | `components/product/ProductCertificates.ts:30` | satır 52 px, ikon 32×32 |

SlotDropzone kart genişliği (container-boxed formülü,
`docs/reports/03-render-envanteri.md` §1.2; `gap-6` = 24 px; `lg` = 768px →
3 sütun):

| Viewport | Sütun | Kart genişliği |
|---|---|---|
| 360 | 1 | 328 |
| 430 | 1 | 398 |
| 640 | 2 | ≈292 |
| 768 | 3 | ≈229 |
| 1024 | 3 | ≈315 |
| 1280 | 3 | ≈405 |
| 1920 | 3 | ≈581 |

**Belgenin kendisi hiçbir yüksek trafikli yüzeye inmiyor.** Ürün sayfasında
sertifika **belgesi** değil yalnız rozet basılıyor
(`ProductCertificates.ts:30`).

### 3.2 Minimum piksel — render kutusundan değil, okunabilirlikten

A4 = **210 × 297 mm**. İnç çevrimi (`25,4 mm = 1 inç`):

```
kısa kenar: 210 / 25,4 = 8,268 inç
uzun kenar: 297 / 25,4 = 11,693 inç

150 dpi →  1240 × 1754 px
200 dpi →  1654 × 2339 px      ← STANDART
300 dpi →  2480 × 3508 px
```

| Alan | Değer | Türetme |
|---|---|---|
| `require.min_short_edge` | **1654** | 8,268 inç × 200 dpi = 1.653,5 → 1.654 |
| `require.min_area` | **3.868.706** | 1.654 × 2.339 |
| `master.min_long_edge` | **2339** | 11,693 inç × 200 dpi = 2.338,6 → 2.339 |
| `master.dpi_out` | **200** | Aynı seçim; diğer slotlarda 72 (ekran medyası) — burada bilinçli farklı |

> **200 dpi bir SEÇİMDİR, ölçüm değil.** Yazılı belge OCR'ı için yaygın alt
> eşik olduğu için alındı. §5.4'te doğrulama yöntemi (tesseract ile karakter
> doğruluğu karşılaştırması) yazılı. Eşik değişirse yukarıdaki üç sayı da
> değişir.

`require.allowed_ratios` = `["210:297"]` + **`ratio_tolerance: 1`** →
oran **serbest**. Şemanın kendi talimatı bu: *"oran serbest istenirse
`allowed_ratios: ["0:0"]` DEĞİL, `ratio_tolerance: 1` kullanılır"*
(`tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json`). Gerekçe: belge oranı
belgeye göre değişiyor — A4 dikey/yatay, kimlik kartı (ISO/IEC 7810 ID-1 =
85,6 × 54 mm), vergi levhası.

### 3.3 OPTİMİZASYON TUZAĞI — türetilmiş, ölçülmedi

```
presets.py:15    "balanced": {"max_dim": 2000, "quality": 88}   ← varsayılan
engine.py:117    im.thumbnail((max_dim, max_dim))               ← uzun kenarı 2000'e indirir

2000 px / 11,693 inç = 171 dpi
```

**Yani 300 dpi'lik bir A4 taraması optimizasyon hattına girerse 171 dpi'ye
düşer.** Bu tuzak `presets.py:44-53` `EXCLUDED_DOCTYPES` (8 doctype) sayesinde
kapalı — ama `Shipment Document` ve `Data Processing Agreement` o listede
**yok** (§2 tablosu).

**PDF muafiyeti:** `engine.py:98-100`
`if fmt not in SUPPORTED_FORMATS: return unsupported_format` → PDF hiç işlenmez.
Tuzak yalnız **görsel olarak** (jpg/png/webp) taranmış belgeler için geçerlidir.

`master.max_long_edge = 5000` bu yüzden **küçültmeyi pratikte devre dışı bırakan**
bir değer olarak yazıldı: 5000 px = 300 dpi'de 42 cm'lik bir kenar, A3 tarama
dahil her belgeyi kapsar. Gerçek üst sınırı `accept.max_bytes` (10 MB) koyuyor.

### 3.4 KVKK muafiyet haritası eksikliği

`presets.py:70-76` `EXCLUDED_MEDIA_FIELDS` KYB'nin yalnız **2** alanını sayıyor
(`identity_document`, `bank_account_document`); `imza_sirkuleri`,
`ticaret_sicil_gazetesi`, `faaliyet_belgesi`, `vergi_levhasi` **yok**.
Kodun kendi bakım notu (`presets.py:66-69`) bu riski **zaten yazmış**:

> *"`EXCLUDED_DOCTYPES` + `attached_to_doctype` kontrolü TEK BAŞINA bu 146
> kimlik/PII belgesini (TC kimlik taraması dahil) yakalayamıyor;
> `media/access_level.py` `set_level()` public'e geçişten önce bu haritayla
> TERS REFERANS taraması da yapmalı."*

Canlı DB'de doğrulanmış (`presets.py:56-64`):
`Seller Application.identity_document` **144 dosya**,
`Seller Certification.document` **2 dosya** — ikisinde de `attached_to_doctype`
**BOŞ**.

---

## 4. Profil — tek profil, private

| Profil | Genişlik | Biçim | Oran | Erişim | Türetme |
|---|---|---|---|---|---|
| `doc_thumb_512` | 512 | webp (q85) | 3:2 (`cover`) | **private** | max(160·3 = 480; 240·2 = 480; 40·3 = 120) = 480 → 512 |

Hedef oran **3:2**, panel önizleme kutusunun oranı (240/160).
`encoder_quality.webp: 85` — küçük resim de metin içeriyor (belge başlığı
okunabilmeli); `presets.py:14-16` aralığının (82-90) ortası. **ÖLÇÜLMEDİ.**

**Türev de private olmalı:** küçük resim de kimlik bilgisi taşır. Bir kimlik
kartının 512 px'lik küçük resminde TC kimlik numarası okunabilir.

Orijinal için ayrı profil yok — `doc-original` **değişmeden** saklanır
(`presets.py:44-53` bunu 8 doctype için zaten sağlıyor).

---

## 5. İhlal aksiyonu

`on_violation`: `default: reject`, `accept: reject`, **`require: warn`**,
`master: warn`, **`content_rules: reject`**,
`error_code_prefix: upload`, `retryable: false`.

| Kural | Aksiyon | Bugün (KYB) | Bugün (diğer 7) |
|---|---|---|---|
| Yetki yok (`kyb.submit`) | `reject` | ✅ `:427-429` | — |
| Guest | `reject` | ✅ `:431-433` | Frappe kendi kontrolü |
| Uzantı listede değil | `reject` | ✅ `:438-443` | ❌ |
| İçerik < 12 bayt | `reject` | ✅ `:27-28` | ❌ |
| Magic-byte tanınmıyor | `reject` | ✅ `:23-58` | ❌ |
| Uzantı ↔ içerik uyuşmuyor | `reject` | ✅ `:460-478` | ❌ (L0'da **yalnız uyarı**, `:366-369`) |
| `.docx` aslında `.zip` | `reject` | ✅ `:48-53` | ❌ |
| Boyut > 10 MB | `reject` | ✅ `:453-454` | ❌ (L0 50 MB) |
| `is_private=0` | `reject` | ✅ (`is_private=1` zorlanıyor) | ❌ çağırana bağlı (§7-B B8) |
| `attached_to_doctype` boş | `reject` | ✅ `:479-501` | ❌ **146 dosyada boş** |
| İstemci sıkıştırması açık | `reject` | ✅ `kyb.ts:303-306` | ✅ KYC'de de (`KycLayout.ts:381`) |
| Uzun kenar < 2339 | **`warn`** | ❌ | ❌ |
| Optimizasyon muafiyetinde değil | `review` | — | ❌ 2 doctype |
| KVKK alan haritası eksik | `review` | ❌ 4 KYB alanı | ❌ |

### Neden `require: warn` (ret değil)

Telefonla çekilmiş düşük çözünürlüklü bir vergi levhası **bugün kabul ediliyor**
ve KYB süreci onun üzerinden yürüyor. Sert ret çalışan bir akışı kırar.
Doğru davranış: uyarı + "yeniden çekin" çağrısı.

Buna karşılık `content_rules: reject` — çünkü `kyb.py` bugün de bu kuralların
çoğunda `frappe.throw` ile **sert ret** veriyor (`:440-443`, `:453-454`,
`:472-476`). Mevcut davranışın kaydı.

### Kod sözleşmesi uyumsuzluğu

`kyb.py` `upload_policy.py:104-139`'daki kodlu ret sözleşmesini
**kullanmıyor**; düz `frappe.ValidationError` metni fırlatıyor. İstemci koda
değil metne bakmak zorunda.

---

## 6. Zaten çözülmüş — üstüne yazılmayacak

1. **`kyb.py:411-501`'in tüm kural zinciri** (§1). Bu standardın gövdesi budur.
2. **Attach hedefi kararı ve gerekçesi** (`kyb.py:479-495` yorumu).
3. **`presets.py:44-53` `EXCLUDED_DOCTYPES`** — 8 doctype optimizasyondan muaf.
4. **`presets.py:70-76` `EXCLUDED_MEDIA_FIELDS`** + `:56-69` bakım notu — ters
   referans taraması haritası ve **kodun kendi yazdığı risk uyarısı**.
5. **İSTEMCİ SIKIŞTIRMASININ BİLİNÇLİ KAPATILMASI.** `KycLayout.ts:381`
   (`compress: false`) ve `alpine/kyb.ts:303-306` (`autoCustomUploader` ile
   sıkıştırmayı atlıyor). Gerekçe: OCR okunabilirliği.
   **Hiçbir "optimizasyon" önerisi bunu geri açmamalı.**
6. **RFQ ekinde doğru bağlama deseni.** `components/rfq/uploader.ts:30-41` —
   `is_private=1` + `doctype=RFQ`. Kod tabanındaki tek tam doğru bağlama örneği
   (`docs/reports/00-upload-slot-envanteri.md` Tablo B).
7. **SlotDropzone'un ortak yükleme UI'ı.** `lib/upload-ui/facades/SlotDropzone.ts`
   — sabit etiketli tek-dosya slotları için tek bileşen; KYB ve KYC aynı
   bileşeni kullanıyor (`alpine/kyb.ts:290-336`, `KycLayout.ts:362-382`).
8. **Rate limit** 20/300 sn (`kyb.py:412`).

---

## 7. ÜRETİMDE DOĞRULANMALI

Bu ortamda **hiçbir ölçüm yapılmadı** (Docker kapalı, üretim DB ve canlı site
erişimi yok). §3'teki dpi hesapları **aritmetiktir**; hangi dpi'nin gerçekten
gerektiği ölçülmedi.

### 7.1 EN KRİTİK: hassas belgeler küçültülmüş mü

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
# EXCLUDED_DOCTYPES'ta OLMAYAN belge doctype'larında optimize edilmiş dosya:
print(frappe.db.sql("""
  select attached_to_doctype, attached_to_field, file_url, th_optimized_at
  from tabFile
  where attached_to_doctype in ('Shipment Document','Data Processing Agreement')
    and th_optimized_at is not null
""", as_dict=True))
PY
```

**Dönen her satır küçültülmüş bir hassas belgedir.** Boş dönerse tuzak
teorik kalmış demektir (o dosyalar PDF olduğu için, `engine.py:98-100`).

Gerçek dpi kaybını ölçmek için:

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe, os
from PIL import Image
for dt in ("Shipment Document", "Data Processing Agreement"):
    for f in frappe.get_all("File", filters={"attached_to_doctype": dt},
                            fields=["file_url","file_name"], limit_page_length=0):
        p = frappe.get_site_path("private" if "/private/" in f.file_url else "public",
                                 f.file_url.replace("/private/","").lstrip("/"))
        if not os.path.exists(p) or f.file_name.lower().endswith(".pdf"): continue
        try:
            with Image.open(p) as im:
                w, h = im.size
                # A4 dikey varsayımıyla efektif dpi:
                print(dt, f.file_name, f"{w}x{h}", f"~{round(max(w,h)/11.693)} dpi")
        except Exception as e: print(dt, f.file_name, "HATA", e)
PY
```

`~171 dpi` civarında değerler görülürse `engine.py:117`'nin belgeye dokunduğu
kanıtlanmış olur.

### 7.2 `attached_to_doctype` boş hassas belge sayısı hâlâ 146 mı

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print("attach hedefi boş toplam:", frappe.db.sql("""
  select count(*) from tabFile
  where (attached_to_doctype is null or attached_to_doctype = '') and is_folder = 0
""")[0][0])
# Ters referans taraması — presets.py:70-76 haritası:
from tradehub_core.media.presets import EXCLUDED_MEDIA_FIELDS
for dt, alanlar in EXCLUDED_MEDIA_FIELDS.items():
    for alan in alanlar:
        n = frappe.db.count(dt, {alan: ["is","set"]})
        print(f"{dt}.{alan}: {n} referans")
# Haritada OLMAYAN 4 KYB alanı:
for alan in ("imza_sirkuleri","ticaret_sicil_gazetesi","faaliyet_belgesi","vergi_levhasi"):
    print(f"KYB Verification.{alan} (haritada YOK):",
          frappe.db.count("KYB Verification", {alan: ["is","set"]}))
PY
```

Son blok, `presets.py:70-76`'ya eklenmesi gereken dosya sayısını verir.

### 7.3 Gerçek piksel ve dpi dağılımı

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe, os
from collections import Counter
from PIL import Image
dpi_dagilim, dusuk, pdf, toplam = Counter(), 0, 0, 0
DTS = ("KYB Verification","KYC Verification","Seller Certification",
       "Seller Verification","Seller Application","Shipment Document",
       "Data Processing Agreement","Order")
for dt in DTS:
    for f in frappe.get_all("File", filters={"attached_to_doctype": dt},
                            fields=["file_url","file_name","file_size"], limit_page_length=0):
        toplam += 1
        if f.file_name.lower().endswith((".pdf",".docx")):
            pdf += 1; continue
        rel = f.file_url.replace("/private/","").lstrip("/")
        p = frappe.get_site_path("private" if "/private/" in f.file_url else "public", rel)
        if not os.path.exists(p): continue
        try:
            with Image.open(p) as im:
                w, h = im.size
                efektif = round(max(w, h) / 11.693)   # A4 dikey varsayımı
                dpi_dagilim[min(efektif // 50 * 50, 600)] += 1
                if max(w, h) < 2339: dusuk += 1
                gomulu = im.info.get("dpi")
                if gomulu: dpi_dagilim[("gomulu", tuple(round(x) for x in gomulu))] += 1
        except Exception: pass
print("toplam belge:", toplam, "| PDF/DOCX:", pdf)
print("2339 px altı (200 dpi A4 altı):", dusuk)
print("efektif dpi histogramı (50'lik kova):", dpi_dagilim.most_common(30))
PY
```

Ölçülmesi gereken üç sayı:
1. **2339 px altındaki belge oranı** — `warn` eşiğinin kaç kaydı işaretleyeceği.
2. **Efektif dpi medyanı** — 200 dpi seçiminin gerçekçi olup olmadığı.
3. **PDF / görsel oranı** — optimizasyon tuzağının kaç dosyayı ilgilendirdiği.

### 7.4 KYC ucu L1'e taşınabilir mi

```bash
# KYC yüklemelerinin gerçekten upload_file'dan geçtiğini doğrula:
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print(frappe.db.sql("""
  select is_private, count(*) c from tabFile
  where attached_to_doctype = 'KYC Verification' group by is_private
""", as_dict=True))
# Magic-byte uyuşmazlığı olan KYC dosyası var mı (spoof denemesi):
PY
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe, os
from tradehub_core.api.v1.kyb import _detect_format
for f in frappe.get_all("File", filters={"attached_to_doctype":"KYC Verification"},
                        fields=["file_url","file_name"], limit_page_length=0):
    rel = f.file_url.replace("/private/","").lstrip("/")
    p = frappe.get_site_path("private" if "/private/" in f.file_url else "public", rel)
    if not os.path.exists(p): continue
    with open(p, "rb") as fh: icerik = fh.read(4096)
    try:
        tespit = _detect_format(icerik, f.file_name.lower())
        beyan = "." + f.file_name.lower().rsplit(".",1)[-1]
        if tespit not in (beyan, ".jpg" if beyan==".jpeg" else beyan):
            print("UYUŞMAZLIK:", f.file_name, "beyan", beyan, "tespit", tespit)
    except Exception as e:
        print("TESPİT EDİLEMEDİ:", f.file_name, e)
PY
```

`UYUŞMAZLIK` satırları KYC ucunda magic-byte kontrolünün eksik olmasının
somut bedelini gösterir.

### 7.5 200 dpi eşiği doğru mu — OCR ölçümü

Bu, §3.2'nin tek doğrulanmamış varsayımıdır.

```bash
# 30 örnek belge yolu al:
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
for f in frappe.get_all("File", filters={"attached_to_doctype":"KYB Verification"},
                        fields=["file_url","file_name"], limit_page_length=30):
    print(f.file_url, f.file_name)
PY
# Ardından her belge için 150/200/300 dpi'de OCR karakter doğruluğunu karşılaştır:
#   for dpi in 150 200 300; do
#     magick "$f" -resize $(python3 -c "print(int(8.268*$dpi))")x tmp_$dpi.png
#     tesseract tmp_$dpi.png - -l tur --psm 6 > ocr_$dpi.txt
#   done
#   # 300 dpi çıktısını referans alıp 150/200'ün karakter hata oranını hesapla
```

Hedef: hangi dpi'de OCR hata oranının kabul edilemez hâle geldiği.
`require.min_short_edge` bu ölçüme göre 1240 (150 dpi) veya 2480 (300 dpi)
olarak revize edilebilir.

### 7.6 PDF içi aktif içerik taranıyor mu

`engine.py` PDF'e dokunmuyor; `upload_policy.py:187-224` ilk 512 baytta
`<html`/`<svg`/`<script` arıyor. **PDF içindeki JavaScript
(`/JS`, `/JavaScript`, `/OpenAction`, `/Launch`) taranMIYOR.**

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe, os, re
KALIP = re.compile(rb"/JavaScript|/JS\b|/OpenAction|/Launch|/EmbeddedFile")
for f in frappe.get_all("File", filters={"file_name": ["like", "%.pdf"]},
                        fields=["file_url","file_name","attached_to_doctype"],
                        limit_page_length=0):
    rel = f.file_url.replace("/private/","").lstrip("/")
    p = frappe.get_site_path("private" if "/private/" in f.file_url else "public", rel)
    if not os.path.exists(p): continue
    with open(p, "rb") as fh: veri = fh.read()
    if KALIP.search(veri):
        print("AKTİF İÇERİK:", f.attached_to_doctype, f.file_name)
PY
```

Bu, bu standardın kapsamı dışında ayrı bir güvenlik konusudur ama belge
slotunda ortaya çıktığı için kaydedildi.

### 7.7 Ölçülemeyen ve kasıtlı boş bırakılanlar

| Konu | Neden |
|---|---|
| OCR başarı oranı | tesseract koşumu + üretim belgeleri gerektirir (§7.5) |
| `doc_thumb_512` `encoder_quality: 85` doğruluğu | Kalibrasyon koşumu gerektirir |
| `quality.target_ssim_per_class.text = 0.995` | Hangi SSIM'de OCR'ın düştüğü ölçülmedi |
| KYC'nin L1'e taşınıp taşınmayacağı | Ürün/güvenlik kararı |
| Belgelerin gerçek saklama maliyeti | `docs/reports/06-depolama-maliyet.md` kapsamı |
| `master.max_long_edge = 5000` gerçek A3 taramalarını kapsıyor mu | Üretimde en büyük belge boyutu ölçülmedi |

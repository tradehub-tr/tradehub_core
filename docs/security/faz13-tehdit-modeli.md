# T-132 — Medya hattı tehdit modeli

**Tarih:** 2026-08-18 · **Faz:** 13 (Güvenlik ve observability) · **Görev:** T-132
**Kod karşılığı:** `tradehub_core/media/pipeline/security/isolation.py` (T-130), `tradehub_core/media/pipeline/security/svg.py` (T-131),
`tradehub_core/media/pipeline/observability/{metrics,logging}.py` (T-133)
**Test karşılığı:** `tests/test_isolation.py` (36), `tests/test_svg_sanitize.py` (52), `tests/test_observability.py` (72)
**Kardeş belge:** `docs/security/faz13-gdpr.md` (T-134 — KVKK/GDPR ve EXIF)

> **Bu belge `tradehub_core/` altındaki üretim kodunu DEĞİŞTİRMEZ.** Bulunan
> açıklar ölçülür, kanıtlanır ve **düzeltme önerisi** olarak yazılır. Uygulama
> kararı ayrı bir görevdir; §6'daki her öneri, dokunulacak dosya ve satırla
> birlikte verilmiştir.

---

## 0. Yöntem — bu belgedeki her sayı nereden geldi

| Etiket | Anlamı |
|---|---|
| **[K]** | Kod okundu — `dosya:satır` verildi |
| **[Ö]** | **Canlı sistemde ölçüldü** — 2026-08-18, `istoc-dev-backend-1`, site `istoc.localhost`, Python 3.11.6. Ölçüm betikleri §8'de |
| **[D]** | Bu makinede deneyle doğrulandı (HTTP isteği, sha256 karşılaştırması) |
| **[T]** | Tasarım kararı — gerekçesi yanında |
| **[?]** | ÖLÇÜLEMEDİ → §7'de neden ve nasıl ölçüleceği yazılı |

**Ölçümün sınırı, açıkça.** Bütün [Ö]/[D] sayıları **geliştirme sitesinden**
(`istoc.localhost`) alındı. Üretim veritabanına erişim bu görevde YOKTU. Bu
sitede hem seed verisi hem gerçek görünümlü satıcı yüklemeleri bir arada.
§3'teki bulguların **mekanizması** üretimde de aynıdır (aynı kod, aynı nginx
kuralları); **sayıları** üretimde farklı olacaktır. §7 hangi komutun üretimde
koşturulması gerektiğini yazıyor.

---

## 1. Varlıklar ve güven sınırları

### 1.1 Korunan varlıklar

| # | Varlık | Nerede | Neden hassas |
|---|---|---|---|
| A1 | KYB/KYC belgeleri | `private/files/` | TC kimlik, imza sirküleri, vergi levhası, banka belgesi — KVKK m.6 özel nitelikli veri |
| A2 | Ödeme/sipariş dekontları | `Order.receipt_url`, `Payment Transaction.receipt_url` | Banka hesabı, tutar, taraf bilgisi |
| A3 | Satıcı ticari görselleri | `public/files/` | Gizli değil; bütünlük ve erişilebilirlik korunur |
| A4 | Worker süreçleri | RQ `queue-short` / `queue-long` | Düşerse KUYRUKTAKİ TÜM işler gider |
| A5 | Denetim izi | Access Decision Log + log satırları | Olay sonrası tek kanıt; PII taşımamalı |

### 1.2 Güven sınırları

```
  [ tarayıcı / mobil ]           GÜVENİLMEZ
          │  multipart upload
          ▼
  ┌───────────────────────────────────────────────┐
  │ nginx  (public/files/ DOĞRUDAN servis eder)   │ ← Python HİÇ devreye girmez
  │        (private/files/ → 403, X-Accel ile)    │
  └───────────────────────────────────────────────┘
          │
          ▼
  ┌───────────────────────────────────────────────┐
  │ gunicorn / Frappe  (upload_policy → File)     │  SINIR 1: içerik doğrulama
  └───────────────────────────────────────────────┘
          │  frappe.enqueue
          ▼
  ┌───────────────────────────────────────────────┐
  │ RQ worker  (av → engine/Pillow → transcode)   │  SINIR 2: çözme/işleme
  │            └─ ffmpeg / clamdscan alt süreç    │  SINIR 3: harici ikili
  └───────────────────────────────────────────────┘
```

**Kritik gözlem [K].** `public/files/` altındaki bir dosyayı nginx doğrudan
servis eder. Yani **bir veritabanı bayrağı (`File.is_private`) o dosyayı
erişime kapatmaz**; kapatmanın tek yolu dosyayı o kökün DIŞINA almaktır. Bu
gerçek `tradehub_core/media/av.py` modül başlığında ("Karantina neden FİZİKSEL
taşıma") ve `media/trash.py`'de zaten yazılı. §3'teki F-02 ve F-03 bulgularının
tamamı bu tek gerçeğin sonucudur.

---

## 2. Hat aşamaları ve tehditler

| # | Aşama | Tehdit | Bugünkü savunma [K] | Faz 13 cevabı |
|---|---|---|---|---|
| S1 | Ad + uzantı | Yasaklı tür (`.svg`, `.html`) | `utils/security.py:27-44` deny-list, `File.before_insert` | — (yerinde) |
| S2 | Boyut | Disk doldurma | `upload_policy.py` `MAX_BYTES` + Frappe tavanı | — (yerinde) |
| S3 | İçerik imzası | `.jpg` adlı HTML/SVG → saklı XSS | `upload_policy.is_dangerous()` magic-byte + BOM atlama | — (yerinde) |
| S4 | **Çözme** | **Dekompresyon bombası → worker OOM kill** | **YOK** | **T-130 `isolation.py`** |
| S5 | **Aktif içerik** | SVG script/handler/harici referans | Bugün SVG tamamen reddediliyor (iki kapı) | **T-131 `svg.py`** — kapı açılırsa ön koşul |
| S6 | Zararlı içerik | Bilinen malware imzası | `av.py` clamdscan + karantina + bekletme | — (yerinde) |
| S7 | Alt süreç | ffmpeg zaman aşımı / bellek | `subprocess(timeout=1700)`; **bellek sınırı YOK, torun süreç öldürülmüyor** | **T-130** |
| S8 | Erişim seviyesi | PII belgesinin public'e çevrilmesi | `access_level._is_protected_pii` çift yol | **F-01/F-04 — açık** |
| S9 | **Depolama** | **Hassas içeriğin public ağaçta İKİZİ** | **YOK** | **F-03 — açık** |
| S10 | Metadata | EXIF GPS / kamera seri no | `engine.py` dolaylı düşürüyor | `faz13-gdpr.md` |
| S11 | Gözlem | Olay görülemiyor, korelasyon yok | `frappe.log_error` serbest metin | **T-133** |

---

## 3. Bulgular

Her bulgu: **ne**, **ölçüm**, **neden bugünkü savunma yetmiyor**, **etki**.

### F-01 — `EXCLUDED_MEDIA_FIELDS` haritası 13 alanın 6'sını kapsıyor · **GİZLİ RİSK**

**[K]** `tradehub_core/media/presets.py:44-53` sekiz doctype'ı kapsam dışı
sayıyor. Aynı dosyadaki `EXCLUDED_MEDIA_FIELDS` (`:70-76`) ise beş doctype ve
altı alan taşıyor.

**[Ö]** Sekiz doctype'ın `Attach`/`Attach Image` alanları sayıldı — **13 alan**,
bunun **6'sı haritada, 7'si haritasız**:

| Doctype | Alan | Haritada | Dolu satır | Benzersiz dosya |
|---|---|:--:|--:|--:|
| KYB Verification | `identity_document` | ✅ | 33 | 18 |
| KYB Verification | `bank_account_document` | ✅ | 33 | 20 |
| KYB Verification | **`imza_sirkuleri`** | ❌ | 33 | 16 |
| KYB Verification | **`ticaret_sicil_gazetesi`** | ❌ | 33 | 18 |
| KYB Verification | **`faaliyet_belgesi`** | ❌ | 33 | 18 |
| KYB Verification | **`vergi_levhasi`** | ❌ | 33 | 19 |
| KYC Verification | `identity_document` | ✅ | 24 | 7 |
| Seller Application | `identity_document` | ✅ | 13 | 3 |
| Seller Certification | `document` | ✅ | 30 | 1 |
| Seller Verification | `document` | ✅ | — | 1 |
| **Order** | **`receipt_url`** | ❌ | 3 | 3 |
| **Payment Transaction** | **`receipt_url`** | ❌ | 3 | 3 |
| **Data Export Request** | **`file_url`** | ❌ | 0 | 0 |

Ayrıca **üç doctype haritada HİÇ YOK**: `Order`, `Payment Transaction`,
`Data Export Request`.

**Bugün sömürülebilir mi — HAYIR, ve nedeni önemli. [Ö]**
`_is_protected_pii` iki yoldan koruyor (`access_level.py:72-92`). 127 benzersiz
hassas dosyanın **126'sı yol 1** (`File.attached_to_doctype` ∈
`EXCLUDED_DOCTYPES`) ile yakalanıyor; **korumasız dosya sayısı bugün 0**.

Yani harita boşluğu bugün **etkisiz**, çünkü yol 1 onu örtüyor. Ama:

**[Ö]** 127 dosyanın **1'inde** `attached_to_doctype` BOŞ (Seller
Certification.document). O dosyayı ayakta tutan tek şey yol 2 — yani harita.
Aynı durumdaki bir dosya **haritasız bir alanda** olsaydı hiçbir yol onu
yakalamazdı ve `set_level(make_private=False)` bir imza sirkülerini herkese
açık yapardı.

**Etki:** Gizli risk. `attached_to_doctype`'ı boş bırakan tek bir yeni yükleme
yolu (bugün en az bir tanesi zaten var) yedi haritasız alanı bir anda
sömürülebilir hâle getirir. TUR-126 §4 review round 1 aynı hatayı 146 dosyada
ölçmüştü; harita o zaman genişletildi ama **alan bazında değil doctype bazında**
genişletildi ve KYB'nin 6 alanından 2'si alındı.

---

### F-02 — Üç dekont dosyası ŞU AN kimliksiz HTTP ile okunabiliyor · **CANLI**

**[Ö]** `Order.receipt_url` ve `Payment Transaction.receipt_url` alanlarındaki
**3 benzersiz dosyanın 3'ü de** `/files/` (public) ağacında ve `File.is_private = 0`.

**[D]** Kimlik doğrulaması olmadan, düz `curl` ile:

```
/files/H5068c4646bb8478c9c9f0c9000a4b989f.jpg   → HTTP 200   88 096 B  image/jpeg
/files/323-9.png                                → HTTP 200 7 554 143 B  image/png
/files/Gemini_Generated_Image_...png            → HTTP 200 6 376 748 B  image/png
```

**Neden `_is_protected_pii` işe yaramıyor:** o fonksiyon bir **geçiş
muhafızıdır** (`private → public` dönüşümünü reddeder), bir **durum muhafızı**
değil. Dosya en baştan public yüklenmişse hiç devreye girmez. `Order` ve
`Payment Transaction`'ın `EXCLUDED_DOCTYPES` içinde olması, o doctype'ların
"hassas" sayıldığını söylüyor — ama bu etiket yalnız **listeleme/optimizasyon
kapsamını** ve **toggle'ı** etkiliyor; **yükleme anındaki erişim seviyesini
HİÇ belirlemiyor**.

**Etki:** Dekontlar banka hesabı, tutar ve taraf bilgisi taşır. Üç dosya az
görünüyor ama sayı, hattaki dekont yükleme hacmiyle doğru orantılı büyür ve
bugün büyümesini durduran hiçbir kontrol yok.

---

### F-03 — 39 KYB/KYC belgesinin BAYT-ÖZDEŞ kopyası public ağaçta · **CANLI · EN AĞIR**

Bu bulgu F-02'den ayrı ve daha ağır: dosyalar doğru şekilde `private/files/`
altında ve 403 veriyor — **ama aynı baytlar `public/files/` altında da duruyor.**

**[Ö]** `content_hash` üzerinden eşleştirme:

| Ölçüm | Değer |
|---|--:|
| private + hassas ↔ public dosya çifti | **384** |
| benzersiz `content_hash` | **39** |
| benzersiz public dosya | **39** |
| benzersiz private hassas dosya | **39** |
| **dosya ADI da aynı olan çift** | **379 / 384** |
| public tarafta sızan toplam bayt | **12 806 763** (≈12,2 MB) |

Hassas taraf (çift bazında): KYB Verification **46**, KYC Verification **4**,
Seller Application **1**, Seller Verification **1**.
Public taraf: `attached_to_doctype` boş **38**, Admin Seller Profile **9**
(satıcı logosu), Listing **3** (ürün görseli), Seller Category **1**,
Static Page SEO **1**.

**[D] Uçtan uca doğrulama** — tek bir dosyada, dört adımda:

```
private disk   sha256 = 4c7c576a620f0e850d78f2b71fa7eda4c09af3e6a7f9082414ac11de41334ac3
public  HTTP   sha256 = 4c7c576a620f0e850d78f2b71fa7eda4c09af3e6a7f9082414ac11de41334ac3   ← AYNI

GET /private/files/469119194_...nm.jpg   → HTTP 403     (koruma ÇALIŞIYOR)
GET /files/469119194_...nm.jpg           → HTTP 200 · 67 776 B   (aynı baytlar)
```

**İki yol yalnız `/private` önekiyle ayrılıyor; dosya adı aynı.** Yani private
adresi bilen (ya da tahmin eden) biri, `/private`'ı silerek aynı belgeyi
kimliksiz indirir. 384 çiftin 379'unda ad aynı.

**Kök neden — üç parça birleşiyor:**

1. **[K]** `media/naming.py:_hashed_name` içerik-adresli adlandırma yapıyor:
   `sha256(içerik)[:32] + uzantı`. **Aynı içerik → aynı ad.** Bu tasarım
   doğrudur (dedup + adres tahmin edilemezliği) ama **erişim seviyesini
   adın parçası saymaz**.
2. **Kullanıcı davranışı, kusur değil:** satıcı aynı JPEG'i hem mağaza logosu
   (public) hem KYB eki (private) olarak yüklüyor. Public taraftaki 9 dosya
   `Admin Seller Profile`'a, 3'ü `Listing`'e bağlı — bu tam olarak o senaryo.
3. **Kimse iki ağacı karşılaştırmıyor:** yükleme sırasında "bu içeriğin public
   bir ikizi var mı" sorusu HİÇ sorulmuyor.

**Etki:** `is_private` bayrağının ve `_is_protected_pii`'nin **koruduğu şey
tamamen delinmiş** — 39 KYB/KYC belgesi bugün kimliksiz indirilebilir durumda.
Bu, F-01'deki gizli riskin aksine **bugün gerçekleşmiş** bir sızıntıdır.

---

### F-04 — `_is_protected_pii` geçiş muhafızı, durum muhafızı değil · **YAPISAL**

F-02 ve F-03'ün ortak nedeni. **[K]** `access_level.py:95-209` (`set_level`) yalnız açıkça
çağrıldığında çalışır. Bir dosyanın:

* public olarak **yüklenmesi**,
* public ağaçta **ikizinin bulunması**,
* bir hassas alana **sonradan bağlanması** (dosya zaten publicken)

durumlarının hiçbirinde devreye girmez. Sistemde "bu dosya hassas bir alanda
duruyor ve public" sorusunu **periyodik soran** bir iş yok.

---

### F-05 — Ters referans taraması O(doctype × alan × sorgu) · **PERFORMANS/DOĞRULUK**

**[K]** `access_level.py:88-92`:

```python
for doctype, fields in presets.EXCLUDED_MEDIA_FIELDS.items():
    for field in fields:
        if frappe.db.exists(doctype, {field: url}):
            return True
```

Bugün 6 alan → 6 sorgu. F-01'in önerisi uygulanıp harita 13 alana çıkarsa 13
sorgu; her biri **indekssiz** bir `Attach` kolonunda `=` araması. Ölçülmedi
**[?]** ama yön belli: harita büyüdükçe toggle yavaşlar ve bu, haritayı
genişletmeye karşı sessiz bir baskı yaratır — yani güvenlik kararını performans
kaygısı belirler. §6'daki öneri bu baskıyı kaldırıyor.

---

### F-06 — Dekompresyon bombası worker'ı öldürüyor · **T-130 ile kapatıldı**

**[K]** `media/runner.py` → `media/engine.py` `Image.open(...).load()` worker
sürecinin İÇİNDE çalışıyor. Bellek sınırı yok.

**[Ö]** `tests/fixtures/malicious/bomb_100mp.png`: **97 221 B** dosya,
**10 000 × 10 000 = 100 MP** (mod `L`) piksele açılıyor. Linux'ta ölçüldü:

| Adres alanı sınırı | Sonuç |
|---|---|
| 64 MB | `isolation_memory` (MemoryError, çıkış 121) |
| 96 MB | `isolation_memory` |
| 128 MB | `isolation_memory` |
| 1,5 GB (`IMAGE_LIMITS`) | başarılı — gerçek dosyalar kesilmiyor |

**Cevap:** `tradehub_core/media/pipeline/security/isolation.py` işi `fork()`'lu bir çocukta,
`RLIMIT_AS` + `RLIMIT_CPU` + duvar saati altında koşturur. Çocuk ölür, worker
yaşar (`tests/test_isolation.py::WorkerHayatta`).

**[Ö] Platform uyarısı:** `RLIMIT_AS` **macOS/Darwin'de uygulanmıyor** — 100 MB
sınır altında 400 MB `bytearray` sorunsuz ayrıldı, `getrlimit` `RLIM_INFINITY`
döndürdü. Üretim Linux olduğu için koruma üretimde geçerli; **yerel geliştirme
makinesinde YOK**. Test bunu `skipTest` ile açıkça işaretliyor.

---

### F-07 — Alt süreç zaman aşımında torunlar arkada kalıyor · **T-130 ile kapatıldı**

**[K]** `media/transcode.py:365` ve `media/av.py:484`
`subprocess.run(..., timeout=…)` kullanıyor. Python zaman aşımında yalnız
DOĞRUDAN çocuğu öldürür; ffmpeg'in doğurduğu alt süreçler çalışmaya devam eder
ve geçici dosya kilitli kalır.

**Cevap:** `isolation.run_command()` çocuğu `os.setsid()` ile yeni oturuma
alır ve zaman aşımında `killpg` ile **süreç grubunun tamamını** öldürür
(`tests/test_isolation.py::test_komut_zaman_asiminda_surec_grubu_olur`).

---

### F-08 — Yukarıdakilerin hiçbiri ölçülemiyor · **T-133 ile kapatıldı**

**[K]** Bugün üç ayrı log kanalı var (`frappe.log_error` serbest metin,
`frappe.logger()`, Access Decision Log) ve **ortak korelasyon anahtarı yok**.
Yükleme → AV → optimize → türev zinciri dört sürece dağılıyor; hiçbir sorgu
"şu yükleme neden reddedildi" sorusunu tek adımda cevaplayamıyor.

**Cevap:** `observability/logging.py` (korelasyon ID + JSON Lines + iki yollu
PII maskeleme) ve `observability/metrics.py` (Prometheus 0.0.4).
F-01/F-02 için özel iki gösterge tanımlı:

```
media_pii_field_coverage{status="mapped"|"unmapped"}   # F-01: unmapped > 0 → açık
media_pii_unprotected_files                            # F-02/F-03: > 0 → sızıntı
```

---

## 4. Kapatılan tehditler — özet

| Tehdit | Cevap | Ölçülen kanıt |
|---|---|---|
| Dekompresyon bombası → worker OOM | `isolation.run_callable` + `RLIMIT_AS` | 64/96/128 MB'ın üçünde de durduruldu |
| Sonsuz döngü | `RLIMIT_CPU` → SIGXCPU | 1 sn CPU sınırı, ~2 sn'de sonlandı |
| Takılı alt süreç | duvar saati + `killpg` | 30 sn'lik iki `sleep`, 2 sn'de bitti |
| `abort()` / segfault | sinyal sınıflandırma | SIGABRT → `isolation_killed`, ebeveyn yaşadı |
| Core dump ile PII sızıntısı | `RLIMIT_CORE = 0` varsayılan | `IMAGE_LIMITS.core_bytes == 0` |
| SVG script/handler | `svg.sanitize` izin listesi | fixture'ın 5 saldırısının 5'i silindi |
| XXE / billion laughs | ham bayt ön taraması | ayrıştırıcı HİÇ çağrılmadı (`parser == "none"`) |
| Gömülü font | üç yol birden kapalı | `font`/`@font-face`/`style` silindi |
| SVG harici referans | `#` dışındaki her href silinir | `https:`, `//`, göreli yol, `url(https://…)` |
| Log'da ham dosya yolu | iki yollu maskeleme | `masked:<sha256[:12]>` — `audit.fingerprint` ile aynı |
| Log injection (korelasyon ID) | karakter süzme | `\n` ve `"` düşüyor |

---

## 5. Açık kalan tehditler

| # | Tehdit | Durum | Neden bu görevde kapatılmadı |
|---|---|---|---|
| F-01 | Harita 7 alanı kapsamıyor | **AÇIK (gizli)** | Düzeltme `tradehub_core/media/presets.py` içinde — bu görev orayı DEĞİŞTİRMİYOR |
| F-02 | 3 dekont public | **AÇIK (canlı)** | Veri düzeltmesi + yükleme yolu değişikliği gerekiyor |
| F-03 | 39 KYB/KYC belgesinin public ikizi | **AÇIK (canlı, en ağır)** | Yeni bir kontrol (yükleme anı çakışma taraması) + geriye dönük temizlik |
| F-04 | Geçiş muhafızı ≠ durum muhafızı | **AÇIK (yapısal)** | Periyodik denetim işi gerekiyor |
| F-05 | Ters tarama indekssiz | **AÇIK** | F-01 düzeltmesiyle birlikte çözülmeli |

---

## 6. Düzeltme önerileri

> **Hiçbiri bu görevde uygulanmadı.** Her öneri dokunulacak dosyayı, gerekçeyi
> ve **neden daha basit bir çözümün yetmediğini** yazar.

### Ö-1 — Haritayı alandan değil ŞEMADAN türet (F-01 + F-05)

**Sorun:** `EXCLUDED_MEDIA_FIELDS` elle bakımlı bir liste. `presets.py:66-68`
zaten bir "KVKK BAKIM NOTU" taşıyor — yani bakımın unutulacağı biliniyor ve
çözüm olarak *hatırlatma* seçilmiş. Ölçüm hatırlatmanın işe yaramadığını
gösteriyor: KYB'ye dört alan eklenmiş, harita güncellenmemiş.

**Öneri:** listeyi elle tutmak yerine `frappe.get_meta()` ile TÜRET.

```python
# tradehub_core/media/presets.py — ÖNERİ, uygulanmadı
def excluded_media_fields() -> dict[str, tuple[str, ...]]:
	"""EXCLUDED_DOCTYPES'in dosya tutan TÜM alanları — şemadan türetilir.

	Elle liste tutmak, doctype'a alan eklenince sessizce eskiyordu:
	ÖLÇÜM 2026-08-18 — 13 alanın 6'sı listedeydi, KYB'nin dört belgesi
	(imza_sirkuleri, ticaret_sicil_gazetesi, faaliyet_belgesi, vergi_levhasi)
	ve üç doctype (Order, Payment Transaction, Data Export Request) dışarıda
	kalmıştı.
	"""
	harita: dict[str, tuple[str, ...]] = {}
	for dt in EXCLUDED_DOCTYPES:
		if not frappe.db.exists("DocType", dt):
			continue
		meta = frappe.get_meta(dt)   # meta zaten cache'li
		alanlar = tuple(
			df.fieldname for df in meta.fields if df.fieldtype in ("Attach", "Attach Image")
		)
		if alanlar:
			harita[dt] = alanlar
	return harita
```

**Neden daha basiti yetmez:** "listeye dört alan ekle" düzeltmesi bugünü
kapatır, yarını kapatmaz — bir sonraki KYB alanı yine unutulur. Kaynağı şema
yapmak, unutmayı **imkânsız** kılar.

**Ö-1b (F-05).** Türetilmiş harita 13 sorguya çıkacağı için ters tarama tek
sorguya indirilmeli:

```python
# ÖNERİ — access_level._is_protected_pii yerine
# 13 ayrı frappe.db.exists yerine doctype başına TEK sorgu (OR'lu),
# ve önce File.attached_to_doctype kontrolü (ucuz olan önce).
```

Ayrıca ilgili `Attach` kolonlarına indeks: `frappe.db.add_index("KYB Verification",
["identity_document"])` vb. — **[?] ölçülmedi**, kolon uzunluğu prefix indeks
gerektirebilir.

### Ö-2 — Hassas alanlar için erişim seviyesini YÜKLEMEDE zorla (F-02 + F-04)

**Sorun:** `EXCLUDED_DOCTYPES` etiketi bugün yalnız *listeleme kapsamını* ve
*toggle'ı* etkiliyor; yükleme anında hiçbir şey yapmıyor. Bu yüzden dekont
public yüklenebiliyor.

**Öneri:** `File.before_insert`/`after_insert` kancasında — bugünkü
`reject_unsafe_files` kancasının yanına — bir **zorlayıcı** ekle:

```
File kaydı açılıyor
  └─ attached_to_doctype ∈ EXCLUDED_DOCTYPES  ya da
     file_url türetilmiş haritadaki bir alanda duruyor
        → is_private = 1 ZORLA (public yüklendiyse private'a TAŞI)
        → audit.log_media_event(action=FORCED_PRIVATE, sensitive=True)
```

**Neden `set_level` yetmez:** o bir geçiş muhafızı (F-04). Yükleme yolunu
kapatmadan, aynı açık her yeni dekontta tekrar açılır.

**Geriye dönük temizlik:** ölçülen 3 dosya için tek seferlik bir patch —
`set_level(make_private=True)` çağrısı referansları da düzeltir
(`refs.retarget`), yani kırık görsel bırakmaz.

### Ö-3 — Yükleme anında public-ikiz taraması (F-03)

**Sorun:** `content_hash` zaten hesaplanıyor ve `File` üzerinde duruyor
(**[Ö]** 4 964 kaydın 4 958'inde dolu — %99,9). Yani veri VAR, kimse SORMUYOR.

**Öneri:** hassas bir alana dosya bağlanırken tek sorgu:

```python
# ÖNERİ — hassas dosya kaydedilirken
ikiz = frappe.db.get_value("File", {"content_hash": doc.content_hash, "is_private": 0}, "name")
if ikiz:
    # 1) operatöre uyarı + moderasyon kuyruğu (sessizce silmek satıcının
    #    mağaza logosunu kırardı — bu bir KARAR, otomatik düzeltme değil)
    # 2) media_pii_unprotected_files göstergesi +1
```

**Ve geriye dönük:** ölçülen 39 dosya için tek seferlik rapor + insan kararı.
Otomatik silmek YANLIŞ olur: public taraftaki 9 dosya satıcının mağaza
logosu, 3'ü ürün görseli — silmek vitrini bozar. Doğru karar "hangisi kalacak"
sorusunun insan tarafından cevaplanmasıdır.

**Neden `naming.py` değiştirilmemeli:** "erişim seviyesini hash'e kat" önerisi
(`sha256(içerik + tuz_private)`) dedup'u bozar ve **mevcut 4 958 dosyanın
adını değiştiremez** — yani bugünkü 39 sızıntıyı kapatmaz. Sorun adlandırmada
değil, iki ağacın hiç karşılaştırılmamasında.

### Ö-4 — Periyodik PII denetim işi (F-04)

Günlük bir `scheduler_events` işi §8'deki ölçüm betiğini koştursun ve
sonucu `metrics.PII_FIELD_COVERAGE` / `PII_UNPROTECTED_FILES` göstergelerine
yazsın. Uyarı kuralı basit: **her ikisi de 0 olmalı.** Bugün ikisi de 0 değil.

### Ö-5 — İzolasyonu üretim hattına bağla (F-06 + F-07)

`isolation.py` yazıldı ama **hiçbir yerden çağrılmıyor** — bilinçli: bu görev
`tradehub_core/` altına yazmıyor. Bağlama noktaları:

| Dosya | Bugün | Öneri |
|---|---|---|
| `media/runner.py` | `engine.optimize(...)` doğrudan | `isolation.run_callable(engine.optimize, …, limits=IMAGE_LIMITS)` |
| `media/transcode.py:365` | `subprocess.run(timeout=1700)` | `isolation.run_command(cmd, limits=VIDEO_LIMITS)` |
| `media/transcode.py:133` | `subprocess.run(timeout=20)` | `isolation.run_command(cmd, limits=PROBE_LIMITS)` |
| `media/av.py:484` | `subprocess.run(timeout=120)` | `isolation.run_command(cmd, limits=SCAN_LIMITS)` |

Üçü de `IsolationResult.retryable` ile `media/jobs.py` retry politikasına
doğrudan bağlanabilir (`SEBEP_MEMORY` tekrar denenmez, `SEBEP_TIMEOUT` denenir).

---

## 7. Ölçülemeyenler

| # | Ne | Neden | Nasıl ölçülür |
|---|---|---|---|
| ? -1 | **Üretim** sayıları | Üretim DB erişimi yok | §8 betikleri üretim sitesinde koşturulmalı; F-02/F-03 sayıları orada farklı olacak |
| ? -2 | `Attach` kolonu indeksi ve ters tarama süresi | Profil alınmadı | `EXPLAIN` + 13 alanlı harita ile `set_level` süresi |
| ? -3 | nginx `private/files/` sertleştirmesinin ÜRETİMDEKİ hâli | Yalnız dev nginx ölçüldü (403 doğru) | MEMORY.md "prod'a ulaşmamış nginx sertleştirmesi" bulgusu; üretimde aynı `curl` testi |
| ? -4 | `X-Content-Type-Options` / CSP başlıkları | SVG kapalı olduğu için sırası gelmedi | `logo.md` §12-D6 — SVG-8 doğrulaması |
| ? -5 | ClamAV gerçekten kurulu mu | Bu görevde tarama koşturulmadı | `docker exec … which clamdscan` |
| ? -6 | `RLIMIT_AS`'ın üretim konteynerindeki cgroup limitiyle etkileşimi | Ölçülmedi | cgroup `memory.max` < `RLIMIT_AS` ise OOM killer önce devreye girer → `SEBEP_KILLED` |

---

## 8. Ölçüm betikleri

Hepsi **salt okunur**. Konteynerde çalıştırma deseni:

```bash
docker exec -w /home/frappe/frappe-bench/sites istoc-dev-backend-1 \
    ../env/bin/python /home/frappe/olcum/<betik>.py
```

| Betik | Ne ölçer | §'ye kaynak |
|---|---|---|
| `faz13_olcum.py` | Alan envanteri + haritasız alanlar + `content_hash` özeti | F-01 |
| `faz13_olcum2.py` | Korumasız dosya birleşimi + çakışma dağılımı | F-01, F-03 |
| `faz13_olcum3.py` | Çakışmanın doğası (aynı ad? aynı URL? diskte var mı?) | F-03 |
| `faz13_olcum4.py` | **Dosya başına koruma yolu** (yol1 / yol2 / korumasız) | F-01, F-02 |
| `faz13_gps_canli.py` | public + private ağaçta EXIF/GPS taraması | `faz13-gdpr.md` |

F-03'ün özet sorgusu (tek satırda tekrar üretilebilir):

```sql
SELECT COUNT(*) FROM tabFile p
  JOIN tabFile s ON p.content_hash = s.content_hash
 WHERE p.is_private = 0 AND s.is_private = 1
   AND s.attached_to_doctype IN ('KYB Verification','KYC Verification',
       'Seller Certification','Seller Verification','Seller Application',
       'Order','Payment Transaction','Data Export Request');
-- 2026-08-18 · istoc.localhost → 384
```

---

## 9. Sonuç

Faz 13'ün yazdığı kod **üç tehdidi kapattı** (kaynak tüketimi, SVG aktif
içerik, gözlemlenemezlik) ve **üç açığı ölçtü**:

* **F-03 en ağırı** — 39 KYB/KYC belgesi bugün kimliksiz indirilebiliyor,
  bayt-özdeşliği sha256 ile ve erişilebilirliği HTTP 200/403 farkıyla
  doğrulandı. `is_private` bayrağı bu dosyalar için hiçbir şey korumuyor.
* **F-02** üç dekontu aynı biçimde açıkta bırakıyor.
* **F-01** bugün etkisiz ama tek bir yeni yükleme yolu onu etkinleştirir.

Üçünün ortak kökü **F-04**'tür: sistem "bu dosya hassas mı" sorusunu yalnız
erişim seviyesi DEĞİŞTİRİLİRKEN soruyor; yüklenirken, kopyalanırken ve
sonradan bağlanırken sormuyor. §6'daki öneriler bu soruyu üç noktaya daha
taşır.

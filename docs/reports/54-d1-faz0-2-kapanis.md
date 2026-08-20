# 54 — D-1: Faz 0 · Faz 1 · Faz 2 kapanış dosyası (imzaya hazırlık)

**Tarih:** 2026-08-19 · **Dal:** `ahmet` · **Kapsam:** T-009, T-019, T-020, T-023, T-029

> **Bu belge hiçbir şeyi imzalamaz ve hiçbir onay bloğunu doldurmaz.**
> Amacı tek: üç fazın kapanış kapılarını **bugünkü ölçümle** tek yere toplamak,
> her kapı için "kapandı mı / kapanmadıysa **tek adımda ne gerekiyor**" sorusunu
> sayıyla cevaplamak ve imzalayanın önüne konacak listeyi hazırlamak.
> İmza bir insanın eylemidir; bu belge onu **veremez**, yalnız hazırlar.

**Bu görevde dokunulan dosyalar:** bu belge (yeni) + üç kapanış belgesine eklenen
birer "kanıt ve kapı durumu" bölümü (`07-faz0-kapanis.md`, `30-faz1-adr-kapanis.md`,
`16-t029-politika-aktivasyonu.md`). **Hiçbir onay bloğu, kutucuk, imza alanı
değiştirilmedi.** Hiçbir `.py`, DocType JSON, politika JSON, `docs/standards/`,
`docs/adr/` ya da `docs/srs/` dosyası değiştirilmedi.

---

## 0. Yöntem

| İşaret | Anlamı |
|---|---|
| **[Ö]** | **Bu oturumda ölçüldü** — komut ve çıktı §0.1'de ya da ilgili bölümde. |
| **[T]** | Bu oturumda kod yolu koşturuldu (canlı site, salt okuma). |
| **[K]** | Dosya/kod okundu, varlığı ve içeriği doğrulandı. |
| **[R]** | Yalnız mevcut rapora dayanıyor — **bu oturumda tekrarlanmadı**. |
| **ÖLÇÜLMEDİ** | Ölçülemedi. İddia **yok**. |

**Süre ya da performans iddiası YOK.** Makine paylaşımlı; paralel beş ajan
çalışıyordu. Yalnız geçti/kaldı ve sayım ölçüldü.

### 0.1 Bu oturumda koşulan ölçümler

Tamamı **salt okuma**. Konteynere kopyalanan 3 geçici betik koşum sonrası
silindi (`rm` doğrulandı, `ls /tmp | grep d2` → boş). Hiçbir doctype'ta kayıt
oluşturulmadı, silinmedi; hiçbir bayrak değiştirilmedi.

| # | Ne ölçüldü | Ortam |
|---|---|---|
| Ö-A | **D-2** — hassas `content_hash` paylaşan public dosya sayımı, üç yolun birleşimiyle | `istoc-dev-backend-1`, site `istoc.localhost` |
| Ö-B | `_is_protected_pii(file_doc, url)` — 40 dosyanın her biri için tek tek | aynı |
| Ö-C | **T-017** — 10 kötücül fixture'a `upload_policy.check()`, iki yolda, ret kodlarıyla | aynı |
| Ö-D | 9 slot politikasının `status` / `open_questions` / `encoder_quality null` / `max_megapixels_hard` sayımı | host |
| Ö-E | 9 politikanın `slot-policy.schema.json` ile jsonschema doğrulaması | host (jsonschema 4.25.1) |
| Ö-F | `jsonschema`'nın konteynerdeki ve `requirements.txt`'teki varlığı | ikisi de |
| Ö-G | 17 ADR'nin `## ` bölüm başlıkları + 8 zorunlu konu taraması | host |
| Ö-H | SRS §6.2 kutucuk sayımı + §6.2'nin 6 maddesinin kod tarafı | host |
| Ö-I | `git status` / `git ls-files` — versiyonlama (G-2) | host |
| Ö-J | K-2 kalıntı ölçümü (`istocc`, `istoc.localhost`) + `git log` | host |

### 0.2 Ölçüm anı damgası — bu belge donmuş bir fotoğraf değil

`git status` bu oturumda **105 untracked** girdi ve **40+ değiştirilmiş** dosya
gösterdi; bunların arasında `content_rules.json`, `upload_policy.py`,
`SRS-v1.0.md`, `logo.md` ve üç slot politikası var. **Bu dosyalar bu belge
yazılırken başka ajanlar tarafından değiştiriliyordu.** Aşağıdaki her sayı
2026-08-19 tarihli tek bir ölçüm anına aittir; §11'deki komutlarla tekrar
üretilebilir. **İmza öncesi §11 yeniden koşulmalıdır.**

---

## 1. Tek sayfalık cevap

| Faz | Görev | Kapı sayısı | Kapandı | Kısmen | Açık | **Bugün imzalanabilir mi** |
|---|---|---:|---:|---:|---:|---|
| **Faz 0** | T-009 | 5 (K-1…K-4, G-2) | **2** (K-2, K-4/ölçüm tarafı kısmi) | 1 | **2** | **HAYIR** — ama kalan iş 2 kaleme indi |
| **Faz 1** | T-019 | 4 (ADR seti, geri dönüş yolu, 8 konu, imza) | **1** (ADR seti) | 1 | **2** | **HAYIR** — 2'si tek oturumda kapatılabilir |
| **Faz 2** | T-029, T-020, T-023 | 7 (G1…G7) | **2** (G2, G4) | 1 (G1) | **4** | **HAYIR** — 2 kapı onay yetkisiyle bile kapanmaz |

**Kısa cevap: üç fazın hiçbiri bugün imzalanamaz.** Gerekçe faza göre farklı ve
§8'de tek tek yazılı. **Ama üç fazın da kalan işi dünkü hâlinden küçüldü** — bu
oturumda üç kalemin (K-2, K-25'in çekirdeği, T-017) kapandığı **ölçümle**
doğrulandı ve bu üçü hiçbir mevcut kapanış belgesinde güncel değil (§7).

---

## 2. T-009 — Faz 0 kapanışı

**Kapanış belgesi:** `docs/reports/07-faz0-kapanis.md` (Rev. 2, 2026-08-18)
**Kaynağın kabul kriteri:** *7 rapor tutarlı; fixture manifest programatik
doğrulanmış; açık sorular atanmış; **platform yöneticisi imzası alınmış***

### 2.1 Beş kapının bugünkü durumu

| Kapı | Rev. 2'nin (08-18) yazdığı | **Bugünkü ölçüm (08-19)** | Kapandı mı | **Tek adımda ne gerekiyor** |
|---|---|---|---|---|
| **K-1** KVKK (AS-01 + AS-02) | D-1 = 0 temiz · **D-2 = 44 BULGU** | **[Ö]** D-2 = **40** public dosya; `_is_protected_pii=True` olan **0/40**; tüm public küme (4.426 satır) içinde de **0** | ❌ **DARALTILDI, KAPANMADI** | 40 dosyanın içerik sınıflandırması — **insan kararı**, ölçümle kapanmaz. Rapor 19 §5.4'ün "gerçek sızıntı" saydığı 4 dosya kapatıldı; kalan 40 için "satıcı aynı görseli iki yere yükledi mi, yoksa PII mi" sorusu **cevaplanmadı** |
| **K-2** `media_stats.py` + `02-medya` komutları | ❌ **YAPILMADI** — `istocc` 2+7, betik koşulmadı | **[Ö]** `istocc` → **0 + 0**. `10-media-stats-kosum-ciktisi.txt` (2.853 dosya taranmış, 88 satır) **tracked**. **[Ö]** `git log`: commit `31f115b` (2026-08-18) — *"fix(medya): K-2 kapatıldı — bozuk bench komutları düzeltildi, media_stats koşuldu"* | ✅ **KAPANDI** | — **Rev. 2 bu noktada eskimiş** (§7-B1) |
| **K-3** Üretim imajında ffmpeg (AS-03) | ❌ ÖLÇÜLMEDİ — üretim erişimi yok | **ÖLÇÜLMEDİ** — üretim erişimi bu oturumda da yoktu | ❌ **AÇIK** | Üretim konteynerinde tek komut: `ffmpeg -version`. **Erişim açılmadan kapanmaz** — bu bir ölçüm değil, **erişim** işidir. Alternatif: yönetici "yok" varsayımıyla riski kabul eder (kutucuk zaten var) |
| **K-4** 39 kalem + 6 raporun metni | ⚠ Ölçüm: 10 tam + 8 kısmi / 39. Metin: **0 rapor düzeltildi** | Ölçüm tarafı bu oturumda tekrarlanmadı **[R]**. Metin tarafı **[Ö]**: 6 raporun hiçbirinde "Docker kapalı" gerekçesi düzeltilmemiş | 🟡 **KISMİ** | Kutucuk zaten "☐ Kısmen (18/39)" seçeneğini taşıyor → **imzalayan bu kutuyu işaretleyerek kapatabilir**. Metin düzeltmesi ayrı, bloklayıcı değil |
| **G-2** Çıktılar versiyonlandı mı | ❌ 14 girdi `untracked` | **[Ö]** `docs/reports/`: **19 tracked / 34 untracked**. `docs/adr/`: **0 / 18 tracked**. Toplam **105 untracked** girdi | ❌ **AÇIK — GERİLEDİ** | `git add docs/reports docs/adr scripts && git commit`. **Mekanik iş, karar gerektirmez.** Ama 105 girdinin içinde başka ajanların üretimi de var → commit kapsamı kararlaştırılmalı |

### 2.2 D-2'nin bağımsız yeniden ölçümü — ham çıktı **[Ö]**

`19-d2-hash-ortusme.md` §1.2'nin kendi tanımı (üç yolun birleşimi:
`attached_to_doctype ∈ presets.EXCLUDED_DOCTYPES` **veya**
`presets.EXCLUDED_MEDIA_FIELDS` ters referansı **veya** `is_private=1`) sıfırdan
yazılmış bağımsız bir betikle uygulandı:

```
hassas file_url                                      = 184
hassas content_hash                                  = 165
hassas hash paylasan DISTINCT public file_url        = 40
kirilim (hash-esi uzerinden):
    KYB Verification 133 · KYC Verification 3 · Seller Application 1
    · Seller Verification 1 · (eslesmeyen) 1
_is_protected_pii=True olan public (40'lik kume)     = 0 / 40
tabFile is_private=0 = 4.426    is_private=1 = 616
```

| İddia | Kaynağı | Bu oturumun ölçümü | Karar |
|---|---|---:|---|
| Düzeltme sonrası **40** public dosya kalıyor | rapor 19 §5.4, rapor 33 §2.1 | **40** | ✅ **DOĞRULANDI (üçüncü kez)** |
| `Order` ve `Payment Transaction` kırılımdan düştü | rapor 19 §5.4 | Kırılımda **ikisi de yok** | ✅ **DOĞRULANDI** |
| `_is_protected_pii=True` olan public dosya **0** | rapor 19, rapor 33 | **0 / 40** | ✅ **DOĞRULANDI** |

> **Bu üç ✅ "D-2 kapandı" demek DEĞİLDİR.** Üçü de raporun **kendi** iddiasının
> doğru olduğunu gösteriyor; iddianın kendisi zaten *"40 dosya hâlâ hassas hash
> paylaşıyor"* diyor. **Bloklayıcı daraltıldı: 44 → 40, ve politikanın koruduğunu
> iddia ettiği 4 dosya gerçekten kapatıldı. Kapanan şey budur; kalan 40 dosya
> duruyor.**
>
> Ayrıca rapor 33'ün yapısal notu bu oturumda tekrar doğrulandı **[Ö]**:
> `_is_protected_pii` bir **DB kolonu değil**, `media/access_level.py:72`'deki bir
> **fonksiyon** — imzası `_is_protected_pii(file_doc, url)`. Yani "hangi dosyalar
> korumalı" sorusunun **sorgulanabilir** bir cevabı yok; 40 dosya için 40 ayrı
> çağrı gerekti. Retroaktif de değil (rapor 19 Ö-1): yalnız `set_level` anında
> çalışır. **Ölçümün tamamı yerel dev verisidir; üretimde tekrarlanmadı** (Ö-6).

### 2.3 `07-faz0-kapanis.md` §10 onay bloğunun envanteri — **doldurulmadı**

**[Ö]** Ölçüm: belgenin tamamında **29 `☐` kutucuk**, **0 işaretli**; §10 içinde
ayrıca **31 boş alan** (`______`). Hepsi §10'da toplanmış.

| Alt bölüm | Kutucuk | Boş alan | İmzalayanın önüne konacak kanıt (bu belgede nerede) |
|---|---:|---:|---|
| §10.1 K-1 (KVKK / D-2) | 3 | 2 | §2.2 — 40 dosya, 0/40 korumalı bayrak, kırılım |
| §10.1 K-2 (bozuk komutlar) | 2 | 2 | §2.1 K-2 satırı — **artık kanıtlı: commit `31f115b`** |
| §10.1 K-3 (üretim ffmpeg) | 3 | 2 | ÖLÇÜLMEDİ — erişim yok. Yalnız "risk kabul edildi" kutusu seçilebilir |
| §10.1 K-4 (39 kalem) | 3 | 2 | §2.1 K-4 satırı — "Kısmen (18/39)" kutusu kanıtlı |
| §10.2 K-23 (kanonik politika seti) | 4 | 2 | §5.1 G1 satırı — iki set hâlâ yan yana, karar yok |
| §10.2 K-24 (SRS FR-019) | 3 | 2 | ÖLÇÜLMEDİ bu oturumda **[R]** — `09 §4.6` |
| §10.2 K-25 (megapiksel kapısı) | 3 | 2 | §3.3 + §7-B2 — **kapının çekirdeği bugün kapandı**; eşik tarafı hâlâ açık (§5.1 G7) |
| §10.3 K-10 / K-11 (T-006 / T-007 devri) | 5 | 0 | rapor 33 §2: 34 görsel + **7 video** (kaynak ≥8 istiyor), `pyvips` konteynerde **yok** → K-11 "tekrar çalıştırılabilir" şartı sağlanmıyor **[R]** |
| §10.4 Faz 1'e geçiş | 3 | 2 | §8 — bu belgenin net kararı |
| §10.5 Platform yöneticisi imzası | 0 | 4 | — |
| §10.6 Bilgilendirilenler | 0 | 10 | 5 rol × (ad, tarih) |
| **TOPLAM** | **29** | **31** | |

> **Bu tablo bir doldurma talimatı değildir.** Hangi kutucuğun işaretleneceği
> kararı imzalayanındır; buradaki tek katkı, her kutucuğun karşısına
> **hangi sayının** konacağını göstermektir.

### 2.4 Faz 0 kararı

> **Faz 0 bugün imzalanamaz.** Beş kapının **ikisi açık** (K-1, K-3), biri
> kısmi (K-4), biri gerilemiş (G-2). **Ama Rev. 2'nin dört bloklayıcısından
> biri (K-2) bu oturumda ölçümle kapandı** ve belge bunu bilmiyor.
>
> **Kalan gerçek engel iki tane:**
> 1. **K-1** — 40 dosyanın sınıflandırılması. *İnsan kararı; ajan kapatamaz.*
> 2. **K-3** — üretim erişimi. *Erişim işi; ajan kapatamaz.*
>
> **G-2 mekaniktir** (tek commit), **K-4 zaten kutucukla kapatılabilir**.
> Yani Faz 0 imzaya iki kalem uzaklıkta ve ikisi de bu oturumun yetki
> alanının dışında.

---

## 3. T-019 — Faz 1 kapanışı (ADR seti)

**Kapanış belgesi:** `docs/reports/30-faz1-adr-kapanis.md`
**Kaynağın kabul kriteri:** *Her ADR: bağlam · seçenekler · ölçüm verisi · karar ·
sonuçlar · **geri dönüş yolu**; **en az 8 konuda ADR**; her ADR bir Faz 0/1
raporundaki sayısal veriye atıf; reddedilen seçeneklerin geri dönüş koşulu yazılı*

### 3.1 ADR setinin yapısal ölçümü **[Ö]**

`docs/adr/` — **17 ADR + README**. 17'sinin `## ` başlıkları tek tek okundu:

```
0001…0017  →  ## Bağlam | ## Seçenekler | ## Karar | ## Gerekçe | ## Sonuçlar
             (0008, 0010, 0012, 0014, 0017'de "Gerekçe" başlığı uzatılmış:
              "Gerekçe — ölçülen sayılar" / "— K3'ün ölçümle dönüşü" /
              "ve doğrulama — ölçüldü" / "— ölçülen dağılım (n=400 canlı)")
```

| Kaynağın istediği bölüm | Ölçülen | Karar |
|---|---|---|
| Bağlam | **17/17** | ✅ |
| Seçenekler | **17/17** | ✅ |
| Ölçüm verisi | 5 ADR'de başlığa taşınmış, kalanında gövdede | ✅ (biçimsel şart yok) |
| Karar | **17/17** | ✅ |
| Sonuçlar | **17/17** | ✅ |
| **Geri dönüş yolu** | **0/17 — ayrı bölüm olarak HİÇBİRİNDE YOK** | ❌ |

**Geri dönüş koşulunun metin içinde geçtiği ADR'ler [Ö]:** `grep -liE 'geri
dönüş\|geri alınır\|geri alma koşulu\|rollback'` → **2 dosya** (`0002`, `0003`).
Rapor 33 aynı kalemi 4 dosya (`0002, 0003, 0008, 0010`) olarak saymıştı; fark
grep deseninden geliyor. **İki ölçümün ortak sonucu aynı: şablon 5 bölümlüdür ve
altıncı bölüm hiçbir ADR'de kurulmamıştır.**

### 3.2 Kaynağın istediği 8 konunun karşılığı **[Ö]**

| # | Kaynağın istediği konu | ADR var mı | Kanıt |
|---|---|---|---|
| 1 | image engine | ✅ | ADR-0008 (Pillow, pyvips yerine) |
| 2 | video engine | ✅ | ADR-0011 (H.264 birincil), ADR-0010 (AV1 ertelendi) |
| 3 | **istemci kütüphane seti** | ❌ **YOK** | `grep -liE 'mediabunny\|uppy\|istemci kütüphane\|client-side\|tarayıcı tarafı' docs/adr/0*.md` → **0 dosya** |
| 4 | depolama | ✅ | ADR-0001, ADR-0015 |
| 5 | **CDN** | ❌ **YOK** | `grep -lw CDN docs/adr/0*.md` → **1 dosya** (`0001`), o dosyada da **1 kez**. CDN bir ADR konusu değil, bir yan cümle |
| 6 | smartcrop | ✅ | ADR-0017 (saliency) |
| 7 | kalite stratejisi | ✅ | ADR-0006 (adaptif kalite döngüsü), ADR-0012 |
| 8 | karar tablosu | ✅ | ADR-0016 (politika veridir), `video_decision.json` |
| | **TOPLAM** | **6 / 8** | |

`30-faz1-adr-kapanis.md` §2'nin "istenen 8 ADR" tablosu kaynak sayfadaki listeyle
**aynı 8'liyi eşlemiyor** — bu, rapor 33'ün tespitidir ve bu oturumda
**doğrulandı**: yukarıdaki 3 ve 5 numaralı satırların ADR karşılığı yok.

### 3.3 T-017 bugün kapandı — Faz 1'in karnesi bundan etkilenir **[Ö]**

Rapor 33 T-017'yi **YOK** (RED=2 / GEÇTİ=8) diye ölçmüştü. Rapor 38 kapıyı
onardığını söylüyor. **Bu oturumda bağımsız olarak tekrar ölçüldü** — 10 kötücül
fixture, `upload_policy.check()`, iki yolda, ret kodlarıyla:

```
bomb_100mp.png          kanca=[upload_image_bomb]         medya=[upload_image_bomb]
data_uri_svg.txt        kanca=[upload_content_dangerous]  medya=[upload_ext_not_allowed]
empty_zero_byte.jpg     kanca=[upload_content_empty]      medya=[upload_content_empty]
executable_as.png       kanca=[upload_content_dangerous]  medya=[upload_content_dangerous]
fake_docx.docx          kanca=[upload_container_invalid]  medya=[upload_ext_not_allowed]
jpeg_with_html_tail.jpg kanca=[upload_appended_payload]   medya=[upload_appended_payload]
polyglot_pdf_as.jpg     kanca=[upload_type_mismatch]      medya=[upload_type_mismatch]
polyglot_png_as.jpg     kanca=[upload_type_mismatch]      medya=[upload_type_mismatch]
script_payload.svg      kanca=[upload_ext_denied]         medya=[upload_ext_denied]
truncated.jpg           kanca=[upload_content_truncated]  medya=[upload_content_truncated]

kanca yolu: RED=10 GECTI=0        medya ucu: RED=10 GECTI=0
```

✅ **Rapor 38'in "10/10 REDDEDİLİYOR" iddiası bağımsız olarak DOĞRULANDI.**
Kaynağın kabul kriteri (*"`fixtures/malicious/` içindeki HER dosya reddediliyor"*)
**karşılanıyor**. 100 MP decompression bomb `upload_image_bomb` koduyla,
**iki yolda da** kesiliyor.

**Faz 1 karnesine etkisi:**

| Karne | Rapor 33 (bu sabah) | **Bugünkü ölçümle** |
|---|---|---|
| Faz 1 (T-010…T-019) TAM | 5 | **6** |
| KISMİ | 4 | 4 |
| **YOK** | **1** (T-017) | **0** |

> **Rapor 33'ün Faz 1 tablosu bu satırda eskimiştir.** Rapor 33 yalnız oku
> kuralı gereği düzeltilmedi; düzeltme burada kayda geçirildi.
> `docs/reports/38-t017-guvenlik-kapisi.md` §7 de aynı sonucu yazıyor.

### 3.4 Faz 1 kapılarının durumu

| Kapı | Durum | **Tek adımda ne gerekiyor** |
|---|---|---|
| **ADR seti var mı** (`14-nihai-denetim.md:221`'in 1. gerekçesi) | ✅ **KAPANDI** — 17 ADR + README | — |
| **Geri dönüş yolu bölümü** | ❌ **AÇIK — 0/17** | 17 ADR'ye birer `## Geri dönüş yolu` bölümü. **Ajan yapabilir ama `docs/adr/` bu turda yalnız-oku alandır** — ADR sahibinin işi. Reddedilen seçeneğin geri dönüş koşulu zaten 2 ADR'de gövdede var; kalan 15'i **karar** ister, kopyalanamaz |
| **8 zorunlu konu** | ❌ **6/8** | 2 yeni ADR: (a) *istemci kütüphane seti* — `44-t081-yukleyici.md` ve `11-faz1-arge.md` §T-015 girdiyi taşıyor; (b) *CDN* — `27-t052-cdn-teslim.md` (19.638 B) girdiyi taşıyor. **İkisinin de ölçüm verisi hazır, yalnız ADR'ye dökülmemiş.** Bu, tek oturumda kapatılabilecek en somut kalem |
| **İmza** (2. gerekçe) | ❌ **AÇIK** | `11-faz1-arge.md`'ye (ve `docs/adr/README.md`'ye) onay bloğu kurulmalı. **Bugün böyle bir blok hiç yok** — `30-…md` §4 bunu açıkça *"AÇIK"* bırakıyor. Faz 0'ın `07-…md` §10'u gibi bir şablon **kurulmamış**; imzalayanın önüne konacak fiziksel alan yok |

### 3.5 İmzalayanın önüne konacak ek liste — Faz 1'in kendi 8 ölçülmemiş kalemi

`30-faz1-adr-kapanis.md` §4'ün son tablosu, `11-faz1-arge.md` §11'in 8
ölçülmemiş kalemini denetim gerekçesine **girmediği** için kapıyı etkilemiyor
diye kaydetmiş. Bu doğru; ama imza anında imzalayan bunu görmelidir:

| # | Ölçülmeyen | Durum [R] |
|---|---|---|
| Ö-1 | Gerçek ürün fotoğrafında hedefi tutan kalite | ❌ açık — ADR-0006'nın en büyük boşluğu |
| Ö-2 | SSIM'in `scikit-image` ile çapraz doğrulaması | ❌ açık |
| Ö-3 | AV1 vs VP9 kalite-eşitli kıyas | ✅ kapandı (`22-t072-vmaf-av1.md`) |
| Ö-4 | Disk taraması ↔ DB sayımı farkı (4.341 vs 4.958) | ❌ açıklanmadı |
| Ö-5 | 220 dpi'lik 102 dosyanın slot dağılımı | ❌ açık |
| Ö-6 | Saliency merkezinin insan seçimiyle uyumu | ❌ açık (ADR-0017'de "doğrulanmadı" işaretli) |
| Ö-7 | `company.cover_video` alt sınırının canlıdaki ihlali | 🟡 kısmen (`08-canli-olcum.md` §7) |
| Ö-8 | `ruff` | ❌ kurulu değil |

**Karne: 8 kalemin 1'i tam, 1'i kısmen kapandı, 6'sı açık.** Bu oturumda hiçbiri
yeniden ölçülmedi.

### 3.6 Faz 1 kararı

> **Faz 1 bugün imzalanamaz.** Dört kapının biri kapandı (ADR seti), üçü açık.
>
> **Ama Faz 1 üç fazın imzaya en yakın olanıdır:** açık üç kalemin **ikisi
> ajan işiyle kapatılabilir** (2 eksik ADR konusu + 17 ADR'ye geri dönüş yolu
> bölümü), üçüncüsü (imza) yalnız **bir onay bloğunun kurulmasını** ister —
> bugün böyle bir blok fiziksel olarak **yok**.
>
> Ayrıca Faz 1'in en ağır tekil bulgusu (T-017: 100 MP bomba kapıdan geçiyor)
> **bugün kapandı ve bağımsız olarak doğrulandı** (§3.3).

---

## 4. T-020 ve T-023 — standart belgeleri

Bu iki görev faz kapanışı değil, **standart belgesidir**; ama ikisinin de kabul
kriteri Faz 2'nin kapılarına bağlıdır ve bağımsız kapanamazlar.

### 4.1 T-020 — Ürün görseli standardı + politika şeması

**Kabul kriteri:** *Şema tüm alanları içeriyor; **ihlal yüzdesi raporlanmış**;
**jsonschema ile doğrulanıyor**; 2000×2000 master ile çelişki yok*

| Kriter | Ölçüm | Karar |
|---|---|---|
| Şema tüm alanları içeriyor | **[Ö]** `product-image.json` → `slot-policy.schema.json` ile **0 hata** | ✅ |
| jsonschema ile doğrulanıyor | **[Ö]** host'ta 0 hata (jsonschema 4.25.1). ❌ **konteynerde `jsonschema` YOK** (`ModuleNotFoundError`), `requirements.txt`'te de **yok** | 🟡 **doğrulanıyor ama üretim yolunda koşamaz** |
| İhlal yüzdesi raporlanmış | ❌ **ÖLÇÜLMEDİ.** Politikanın kendi `open_questions`'ı (**[Ö]** 7 madde) bunu söylüyor | ❌ |
| 2000×2000 master ile çelişki yok | Bu oturumda ölçülmedi **[R]** — `07-…md` Ç-9 kalemi (master tavanı 1920–2000 ↔ profil matrisi 2400) **hâlâ açık** | ❌ **çelişki kayıtlı** |

**Tek adımda ne gerekiyor:** ihlal yüzdesi ölçümü — canlı ürün görsellerine
politikanın `require.*` kurallarını uygulayan bir sayım. **`scripts/` altında böyle
bir betik yok** (`09-slot-bazinda-istatistik.md` slot bazlı uyum sayıyor ama
politika sürümüyle bağlı değil). Ç-9 ise **karar** ister.

### 4.2 T-023 — Kalan slotların standartları

**Kabul kriteri:** *Slot kataloğundaki **tüm satırlar "SABİT"**; her slot şema
doğrulamasından geçiyor; TR mesaj metinleri; slot→profil eşlemesi tam*

**[Ö]** 9 politikanın canlı sayımı (2026-08-19):

| Politika | `status` | `open_questions` | `encoder_quality` null | `accept.max_megapixels_hard` |
|---|---|---:|---:|---|
| `brand-logo.json` | `draft` | 1 | 0 | ❌ **YOK** |
| `category-banner.json` | `draft` | 6 | **3** | 80 |
| `company-cover-image.json` | `draft` | 6 | **5** | 80 |
| `company-cover-video.json` | `draft` | 8 | 0 | 8.3 |
| `document-attachment.json` | `draft` | 6 | 0 | 80 |
| `product-image.json` | `draft` | 7 | **5** | 80 |
| `product-video.json` | `draft` | 6 | **1** | 8.3 |
| `seller-logo.json` | `draft` | 3 | 0 | ❌ **YOK** |
| `user-avatar.json` | `draft` | 6 | 0 | 80 |
| **TOPLAM** | **`active` = 0 / 9** | **49** | **14** | **7 / 9** |

**[Ö]** Şema doğrulaması: **9/9, TOPLAM HATA = 0**.

| Kriter | Karar |
|---|---|
| Tüm satırlar "SABİT" | ❌ — **9/9 `draft`**, 49 açık soru |
| Her slot şema doğrulamasından geçiyor | ✅ — 0 hata |
| `docs/standards/` altında slot belgesi | ✅ — 8 slot belgesi + `logo.md` (iki slotu birlikte) + README |
| TR mesaj metinleri / slot→profil eşlemesi | Bu oturumda ölçülmedi **[R]** |

**Tek adımda ne gerekiyor:** 49 açık sorunun kapatılması ya da her birine bir
CR-ID bağlanması. **Bu tek bir adım değil** — rapor 16 §7 ölçtü: 49 maddenin
kapanması üretim ölçümü ve/veya onay yetkisi ister. En yakın slot `brand-logo`
(1 açık soru, 0 null) ama `max_megapixels_hard` alanı **yok** → FR-144 gereği
`active` olamaz.

### 4.3 T-020 / T-023 kararı

> **İkisi de kapanamaz ve ayrı kapanamaz.** İkisinin de kalan kalemi Faz 2'nin
> G3 (49 açık soru), G6 (0/9 `active`) ve G7 (`max_megapixels_hard`)
> kapılarıyla **aynı kalemdir**. Bu görevler için ayrı bir imza tanımlı değildir;
> kapanışları T-029'a bağlıdır.

---

## 5. T-029 — Faz 2 kapanışı (SRS onayı)

**Kapanış belgesi:** `docs/reports/16-t029-politika-aktivasyonu.md` +
`docs/srs/SRS-v1.0.md` §6.7 / §9.2
**Kaynağın kabul kriteri:** *FR-xxx/NFR-xxx test edilebilir; izlenebilirlik
matrisi; **hiçbir slot "TBD" değil**; **platform yöneticisi onayı alınmış***

### 5.1 Yedi kapının bugünkü bağımsız durumu

| Kapı | SRS §6.7'nin doğrulama kuralı | Rapor 16 (08-19) | **Bu oturumun ölçümü** | **Tek adımda ne gerekiyor** |
|---|---|---|---|---|
| **G1** | Şema 0 hatayla doğrulanıyor **ve** kanonik set kararı verilmiş | 🟡 KISMEN | 🟡 **KISMEN [Ö]** — jsonschema **9/9, 0 hata** ✅; ama `policy/slots/` (**9 dosya**) ile `docs/standards/policies/` (**13 dosya**) yan yana duruyor, **kanonik set kararı yazılı değil**; `README.md` §6 betiği hâlâ çıkış kodu 1 **[R]** | Kanonik seti ilan et — **`07-…md` §10.2 K-23 kutucuğu bunun için var**. Tek imza kalemi |
| **G2** | Şema v1.1, video/belge biçimini ifade ediyor | ✅ GEÇTİ | ✅ **GEÇTİ [R]** — bu oturumda tekrarlanmadı | — |
| **G3** | `open_questions` toplamı 0 **ya da** her madde bir CR-ID taşıyor | ❌ 49 | ❌ **AÇIK — 49 [Ö]** (kırılım §4.2). Hiçbirine CR-ID verilmemiş | 49 madde. **Tek adım değil**; üretim ölçümü + onay yetkisi ister |
| **G4** | 14 yönetici kararı onaylanmış ve belgeye işlenmiş | ✅ 14/14 | ✅ **GEÇTİ [R]** — rapor 33 §4.3 bağımsız doğruladı | ⚠ **kanıt belgenin kendi beyanıdır** — aşağıda |
| **G5** | `calibration_status != "UNCALIBRATED"` | ❌ AÇIK | ⚠ **DİZE OLARAK GEÇER, ÖZÜNDE AÇIK [Ö]** — bkz. §5.3 | Etiketli korpus (≥300 görsel) + `calibrate_content_rules.py` koşumu. **İnsan etiketlemesi** |
| **G6** | En az bir politika `status: "active"` | ❌ 0/9 | ❌ **AÇIK — 0/9 [Ö]** | Üç sistem eksiği: FR-001 (`slot_key`), FR-144 (`max_megapixels_hard`), FR-149 (`compliance_measured`). **[Ö]** Üçü de bugün hâlâ eksik (§5.2) |
| **G7** | `max_megapixels_hard` 9/9'da var ve kütüphaneyi kesiyor | ❌ AÇIK | ❌ **AÇIK — 7/9 [Ö]**; var olan 7'nin **5'inde eşik 80 MP** ve bu değer canlıdaki **0 dosyayı** kesiyor (en büyük 72,71 MP) | Eşiği bellek bütçesinden türet (FR-143) + 2 logo politikasına ekle (FR-144). **Politika JSON değişikliği** — bu turda yasak alan |

**SONUÇ: 7 kapının 2'si geçti (G2, G4), 1'i kısmen (G1), 4'ü açık (G3, G5, G6,
G7).** SRS §9.3'ün sürüm kuralı "G1–G7'nin **tamamı**" diyor → **`v1.0 ONAYLI`
olamaz.** Rapor 16 ve rapor 33'ün sonucu bu oturumda **doğrulandı**.

> **G4'ün kanıt kalitesi hakkında bir uyarı.** 14 kararın 14'ü kapandı, bu
> doğrulandı. Ama rapor 33 §4.3'ün notu geçerlidir ve bu oturumda **tekrar
> doğrulandı**: onayı taşıyan şey `logo.md` ve `company-cover-video.md`
> içindeki *"platform yöneticisi tarafından onaylanmıştır"* **cümlesidir**.
> Bu iki belgede **imzalı bir onay bloğu, ad/tarih alanı ya da ayrı bir onay
> artefaktı yok.** `07-faz0-kapanis.md` §10.5'teki gibi doldurulacak bir tablo
> orada hiç kurulmamış. **G4 geçti sayılıyor; kanıtı ise beyandır.**

### 5.2 SRS §6.2 — 20 kutucuk, sıfır işaret

**[Ö]** SRS'in tamamında **53 `- [ ]` kutucuk, 0 işaretli**. §6.2 (*"Aşağıdakiler
tamamlanmadan hiçbir slot politikası `active` yapılamaz"*) içinde **20 kutucuk**,
**20'si de işaretsiz**. Rapor 33'ün sayısı doğrulandı.

Bu 20 maddenin **6'sı** bu oturumda programatik olarak ölçüldü:

| # | Madde | FR | **Ölçüm [Ö]** | Karşılanıyor mu |
|---|---|---|---|---|
| 1 | `upload_policy.check()` `slot_key` parametresi alıyor | FR-001 | `grep -c 'slot_key' media/upload_policy.py` → **0**. İmza: `check(file_name, *, content, size, media_endpoint)` | ❌ |
| 2 | 9 dosyanın 9'u tek şemaya uyuyor | FR-002, FR-003 | jsonschema **9/9, 0 hata** | ✅ **tek karşılanan madde** |
| 7 | `max_megapixels_hard` **9/9** politikada | FR-144 | **7 / 9** | ❌ |
| 10 | Her `active` politika `compliance_measured` karnesi taşıyor | FR-149 | **0 / 9** politikada dolu | ❌ |
| 15 | `ffprobe` tabanlı ölçü/süre + `th_media_duration_ms` alanı | FR-133 | `grep -rn 'th_media_duration_ms' tradehub_core/` → **0** | ❌ |
| 19 | `optimization` yanıt bloğu döndürülüyor | FR-064 | `grep -rn '"optimization"' tradehub_core/api/` → **0** | ❌ |
| — | **Kalan 14 madde** | — | **Bu oturumda ölçülmedi** | **doğrulanmadı** |

> **Yani §6.2'nin 20 maddesinden ölçülebilen 6'sının 1'i karşılanıyor.**
> Kalan 14 hakkında bu belge **hiçbir iddiada bulunmaz.**

**Ayrıca kayda geçirilmiş bir iç çelişki duruyor** (rapor 16 §2.3, SRS §6.7-C):
§6.2 *"hiçbir politika `active` yapılamaz"* der, G6 *"en az biri `active`
olmalı"* der. **Bu çelişki çözülmedi.** Bugünkü hâliyle G6 ile §6.2 aynı anda
sağlanamaz — bu, imzadan önce **belge düzeyinde** çözülmesi gereken bir kalemdir
ve tek adımda kapanabilir: G6'nın metni "aktivasyona hazır" olarak yeniden
yazılır ya da §6.2'nin listesi G6'nın önkoşulu ilan edilir.

### 5.3 G5 uyarısı — kapı bugün dize düzeyinde geçti, özünde geçmedi **[Ö]**

SRS §6.7 G5'in **doğrulama kuralı harfiyen şudur:**
`calibration_status != "UNCALIBRATED"`.

Bugünkü ölçüm:

```
content_rules.json  calibration_status = "TRIGGER_RATE_MEASURED_UNLABELED"
git diff:  - "calibration_status": "UNCALIBRATED",
           + "calibration_status": "TRIGGER_RATE_MEASURED_UNLABELED",
```

Ama 9 kuralın **9'unun** `threshold_status`'ı hâlâ *"KALİBRE EDİLMEDİ"* (ya da
*"KALİBRE EDİLMEZ — ürün kararı"*) ile başlıyor; 2026-08-19 eki yalnız
*"tetiklenme oranı ÖLÇÜLDÜ, eşik DEĞİŞMEDİ"* diyor, 2 kuralda ise
*"ÇALIŞTIRILAMADI (ölçüm aracı yok)"*. **Yanlış pozitif oranı ölçülmedi;
etiketli korpus yok.**

> **Bu, G5'in metnindeki bir kusurdur, bir başarı değil.** Kapı bir **dize
> karşılaştırmasına** dayandığı için, kalibrasyon yapılmadan yalnız alanın
> değeri değiştirilerek harfiyen geçilebilir hâle geldi. Bu belge G5'i
> **AÇIK** sayar ve gerekçesini yukarıya yazar.
>
> **İmzalayana öneri:** G5'in doğrulama kuralı, T-025'in kendi kabul kriterine
> (*"eşikler kalibre edilmiş, yanlış pozitif < %5 **ölçülmüş**"*) bağlanmalıdır.
> Bu bir SRS metin düzeltmesidir; **bu turda `docs/srs/` yalnız-oku olduğu için
> yapılmadı.**
>
> ⚠ Ek olarak `38-t017-guvenlik-kapisi.md` §6.3'ün açık bulgusu duruyor:
> `extreme_blur` **RED üretebilen** bir kuraldır ve canlı ürün görsellerinin
> **%1,70'ini (22 dosya)** gizlerdi; kuralın kendi `rollout` sözleşmesi reject
> kuralları için FP < %1 istiyor. **Kalibre edilmemiş bir RED kuralı üretime
> açılırsa satıcı kaybettirir** — bu, G5'in neden gerçekten kapanması gerektiğinin
> ölçülmüş gerekçesidir.

### 5.4 FR-003'ün "CI'da koşar" kriteri bugünkü imajla sağlanamaz **[Ö]**

```
konteyner:  env/bin/python -c "import jsonschema"  →  ModuleNotFoundError
host:       jsonschema 4.25.1  →  9/9 politika, 0 hata
requirements.txt / pyproject.toml / setup.py:  "jsonschema" geçmiyor (0 isabet)
```

> Şema doğrulaması **çalışıyor** — ama yalnız geliştiricinin makinesinde.
> **Üretim/CI imajında bağımlılık yok ve bağımlılık listesinde de yok.**
> G1'in ve §6.2'nin 2. maddesinin (FR-002/FR-003) *"doğrulanıyor"* iddiası
> bugün **taşınabilir değildir**.
>
> **Tek adımda ne gerekiyor:** `requirements.txt`'e `jsonschema` satırı + imaj
> yeniden inşası. **Mekanik iş, karar gerektirmez** — ama `requirements.txt` bu
> oturumda başka bir ajan tarafından değiştirilmiş durumda (`git status: M`),
> o yüzden bu belge dosyaya dokunmadı.

### 5.5 Faz 2'nin onay bloğu — var, ama eksik **[Ö]**

Görev tanımı *"imza bloğu hiçbir yerde yok"* diyordu. **Ölçüm bunu kısmen
düzeltiyor:**

| Belge | Onay bloğu | Ölçüm |
|---|---|---|
| `docs/srs/SRS-v1.0.md` **§9.2 "Onay blokları"** | ✅ **VAR** | 5 rol satırı. **[Ö]** SRS'te toplam **5 `☐`, 1 `☑`**. `☑` yalnız *"T7'nin 14 kararı 2026-08-19'da VERİLDİ"* içindir; aynı satır *"Belgenin geri kalanı (§2, §5, §6.7, FR-019) hâlâ onaysız ☐"* diyor. Diğer 4 rol (backend, frontend, güvenlik/KVKK, ürün) **tamamen işaretsiz** |
| | ❌ **EKSİK** | Tabloda **ad/tarih/imza için doldurulacak alan yok** — yalnız bir "İmza / tarih" sütun başlığı var, içi metin. `07-…md` §10.5'teki gibi `______` alanları **kurulmamış** |
| `docs/reports/16-t029-politika-aktivasyonu.md` | ❌ **YOK** | **[Ö]** `grep -c '☐\|İmza'` → **0**. Faz 2'nin kapanış raporunun kendisinde onay bloğu yok |
| `docs/standards/logo.md`, `company-cover-video.md` | ❌ **YOK** | G4'ün 14 kararını taşıyan iki belge; onay **cümle** olarak yazılı, blok olarak değil (§5.1 notu) |

**Tek adımda ne gerekiyor:** SRS §9.2'ye ad/tarih/imza alanları eklenmesi ve
`16-…md`'ye bir onay bölümü. **İkisi de belge işidir, karar değil** — ama
`docs/srs/` bu turda yalnız-oku alan olduğu için yapılmadı.

### 5.6 Faz 2 kararı

> **Faz 2 bugün imzalanamaz ve üç fazın imzaya en uzağıdır.**
>
> 7 kapının 4'ü açık. Bunlardan **ikisi (G3, G5) onay yetkisiyle bile
> kapanmaz** — G3 üretim ölçümü, G5 insan etiketlemesi ister. G6 üç sistem
> düzeyi eksik ister (FR-001, FR-144, FR-149 — üçü de bugün ölçüldü, üçü de
> eksik). G7 politika JSON değişikliğidir.
>
> **Sadece G1'in ikinci yarısı (kanonik set kararı) bir imza kalemidir** ve
> `07-…md` §10.2 K-23 kutucuğu zaten bunun için kurulmuştur.
>
> Ayrıca §6.2'nin **20 kutucuğunun 20'si işaretsiz**, ölçülebilen 6'sının
> **1'i** karşılanıyor; ve G5 bugün **dize düzeyinde** geçer hâle geldi (§5.3) —
> bu, kapının gevşemesi değil, metninin kusurudur ve imza öncesi düzeltilmelidir.

---

## 6. Kanıt haritası — bugünkü raporlar hangi kapıya bakıyor

Bugün `docs/reports/` altında **15-** … **49-** aralığında 34 rapor üretildi
(**20-** numarası boş; bkz. `31-gorev-numara-hizalama.md`). Üç fazın kapılarına
**doğrudan** dokunanlar:

| Rapor | Görev | Hangi kapı | Ne kanıtlıyor | Ne kanıtlamıyor |
|---|---|---|---|---|
| `16-t029-politika-aktivasyonu.md` | T-029 | **G1…G7** | 7 kapının tek yerde ölçümü; 0/9 `active`; 14/14 karar | Onay bloğu içermiyor (§5.5) |
| `19-d2-hash-ortusme.md` | T-018/D-2 | **Faz 0 K-1** | 44 dosyanın sınıflandırılması; 4 gerçek sızıntının kapatılması | Kalan 40 dosyanın PII olup olmadığını; üretimi (Ö-6) |
| `30-faz1-adr-kapanis.md` | T-019 | **Faz 1 kapı 1** | ADR setinin varlığı (17 + README) | Geri dönüş yolu; 2 eksik konu; imza |
| `33-dogrulama-faz0-3.md` | T-000…T-035 | **hepsi** | 40 görevin bağımsız ölçümü; dört fazın ortak imza engeli | T-017 satırı **eskimiş** (§3.3); T-008/T-013/T-014/T-028 `[R]` |
| `38-t017-guvenlik-kapisi.md` | T-017, T-131, T-025 | **Faz 1 T-017**, **Faz 2 G5** | 10/10 RED (bu oturumda doğrulandı); `probe.py` PNG decode açığı | G5'i kapatmıyor — `calibration_status` yeniden adlandırıldı, kalibrasyon yapılmadı (§5.3) |
| `07-faz0-kapanis.md` | T-009 | **Faz 0 K-1…K-4, G-2** | Faz 0'ın tek onay bloğu (29 kutucuk, 31 alan) | K-2 satırı **eskimiş** (§7-B1); K-25 satırı **eskimiş** (§7-B2) |
| `22-t072-vmaf-av1.md` | T-016/T-072 | Faz 1 Ö-3 | AV1 vs H.264; ADR-0010'un dayanağı | — |
| `27-t052-cdn-teslim.md` | T-052 | **Faz 1 kapı 3 (CDN)** | CDN teslim katmanı ölçümü — **eksik CDN ADR'sinin hazır girdisi** | ADR değil |
| `44-t081-yukleyici.md` | T-081/T-091 | **Faz 1 kapı 3 (istemci)** | Yükleyici ölçümü — **eksik istemci-kütüphane ADR'sinin hazır girdisi** | ADR değil |
| `17-t028-backfill-plani.md` | T-028 | Faz 2 G1 (dolaylı) | Backfill planı | Kanonik set kararı olmadan hangi eşiği uygulayacağını (Ç-15) |
| `21-t030-mimari-inceleme.md` | T-030 | Faz 3 (kapsam dışı) | SAD'ın 8 bloklayıcısı | — |
| `34-` `35-` `36-` | Faz 4…14 | kapsam dışı | — | — |

---

## 7. Bu oturumda ortaya çıkan, mevcut kapanış belgelerinde OLMAYAN beş bulgu

### B1 — K-2 kapandı; `07-faz0-kapanis.md` Rev. 2 bu noktada eskimiş **[Ö]**

```
grep -c "istocc" scripts/media_stats.py                → 0   (Rev.2: 2)
grep -c "istocc" docs/reports/02-medya-istatistigi.md  → 0   (Rev.2: 7)
git log -1 -- scripts/media_stats.py
  → 31f115b 2026-08-18  fix(medya): K-2 kapatıldı — bozuk bench komutları
                        düzeltildi, media_stats koşuldu
docs/reports/10-media-stats-kosum-ciktisi.txt  → tracked, 88 satır, 2.853 dosya
```

Rev. 2 (2026-08-18) K-2'yi *"YAPILMADI"* diye kaydetti; düzeltme **aynı gün,
raporun yazımından sonra** commit'lendi. **Faz 0'ın dört bloklayıcısı üçe indi.**
`07-…md` §5.1, §9.2, §9.3 ve §10.1'in K-2 satırları güncel değildir.

> Not: `istoc.localhost` dizesi hâlâ 1 + 4 kez geçiyor — **bu bir kusur değil,
> sitenin doğru adıdır**; Rev. 2'nin Ç-12 tablosunda ölçülen asıl kusur çift
> `c`'li `istocc` yazımıydı ve o **sıfırlandı**.

### B2 — K-25'in çekirdeği kapandı **[Ö]**

`07-…md` K-25: *"95 KB'lık bir dosya bugün 100 MP açtırıyor ve `optimize()`
`ok=True` dönüyor"* → **kod çözmeden önce megapiksel kapısı** isteniyordu.

Bugünkü ölçüm (§3.3): `bomb_100mp.png` **iki yolda da** `upload_image_bomb`
koduyla reddediliyor. `38-…md` §3.3 ayrıca `probe.py`'nin PNG'de `getexif()`
üzerinden tam decode yaptığını bulup kapattığını yazıyor **[R]**.

**K-25 tam kapanmadı:** kutucuğun ikinci yarısı (*"`max_megapixels_hard` eşiğini
gözden geçir"*) hâlâ açık — **[Ö]** 7 politikanın 5'inde eşik 80 MP ve canlıdaki
**0 dosyayı** kesiyor (G7 ile aynı kalem). **Yani K-25: kapı VAR, eşik ÖLÜ.**

### B3 — T-017 kapandı; rapor 33'ün Faz 1 karnesi eskimiş **[Ö]**

Faz 1: **5 TAM / 4 KISMİ / 1 YOK** → **6 TAM / 4 KISMİ / 0 YOK** (§3.3).
Rapor 33 yalnız-oku alandır; düzeltme burada kayda geçirildi.

### B4 — G5 bugün dize düzeyinde geçilebilir hâle geldi **[Ö]**

`calibration_status`: `UNCALIBRATED` → `TRIGGER_RATE_MEASURED_UNLABELED`.
SRS §6.7 G5'in doğrulama kuralı `!= "UNCALIBRATED"` olduğu için **harfiyen
geçer**; kalibrasyon yapılmadı, FP ölçülmedi, 9 kuralın 9'u hâlâ
*"KALİBRE EDİLMEDİ"*. Bu belge G5'i **AÇIK** sayar (§5.3).

### B5 — FR-001'in "yapılamaz" gerekçesi çürüdü **[Ö]**

`16-t029-politika-aktivasyonu.md` §7, FR-001'i (`upload_policy.check()`'e
`slot_key`) *"`media/*.py` **dokunulmayacaklar** listesinde"* diye kapsam dışı
bıraktı. **Ama `tradehub_core/media/upload_policy.py` bugün değişti**
(`git status: M`; T-017 düzeltmesi). Yani o gerekçe artık geçerli değil.

> **G6'nın üç engelinden birinin kilidi bu yüzden açıldı.** FR-001 bugün
> teknik olarak yapılabilir bir iştir; kalan iki engel (FR-144 politika JSON'u,
> FR-149 şema değişikliği) hâlâ duruyor. **Bu belge hiçbir kod değişikliği
> önermez, yalnız gerekçenin çürüdüğünü kayda geçirir.**

---

## 8. NET KARAR

> ## Bu üç faz bugün imzalanamaz.

**Faz 0 — HAYIR.** Kalan iki gerçek engel: **K-1** (40 dosyanın PII
sınıflandırması — insan kararı) ve **K-3** (üretim erişimi). K-2 kapandı (B1),
K-4 kutucukla kapatılabilir, G-2 tek commit'lik mekanik iştir. **Onay bloğu
hazır ve tam** (29 kutucuk + 31 alan, §2.3) — imzalayanın önüne konacak sayılar
bu belgede.

**Faz 1 — HAYIR, ama en yakın olan bu.** Açık üç kalem: (a) 17 ADR'de **geri
dönüş yolu bölümü yok**, (b) 8 zorunlu konudan **2'si karşılıksız** (istemci
kütüphane seti, CDN — **ikisinin de ölçüm girdisi hazır**: `44-`, `27-`),
(c) imza. **Faz 1'in en ağır tekil bulgusu (T-017) bugün kapandı ve bağımsız
doğrulandı.** Kritik eksik: `11-faz1-arge.md`'de **onay bloğu fiziksel olarak
yok** — imzalayanın imzalayacağı bir alan bulunmuyor.

**Faz 2 — HAYIR, ve en uzak olan bu.** 7 kapının 4'ü açık; **G3 ve G5 onay
yetkisiyle bile kapanmaz** (üretim ölçümü / insan etiketlemesi). §6.2'nin **20
kutucuğunun 20'si işaretsiz**; ölçülebilen 6'sının **1'i** karşılanıyor. Ek
olarak iki **belge düzeyi** kusur imzadan önce düzeltilmelidir: **G5'in dize
temelli doğrulama kuralı** (§5.3) ve **G6 ↔ §6.2 çelişkisi** (§5.2). Ayrıca
`jsonschema` konteynerde ve `requirements.txt`'te yok → FR-003'ün *"CI'da
koşar"* kriteri bugünkü imajla **sağlanamaz** (§5.4).

**T-020 / T-023 — bağımsız kapanamaz.** Kalan kalemleri G3/G6/G7 ile aynıdır.

---

## 9. İmzalayanın önüne konacak liste

> Aşağıdaki üç liste **doldurulmamıştır**. Her satır, karşısındaki kutucuğun
> hangi ölçülmüş sayıya dayanarak işaretleneceğini gösterir.

### 9.1 Faz 0 (`07-faz0-kapanis.md` §10)

| Karar kalemi | Bugünkü ölçülmüş durum | Karar kimin |
|---|---|---|
| **K-1** — 44 → **40** public dosya hassas hash paylaşıyor; `_is_protected_pii=True` **0/40**; kırılım KYB 133 · KYC 3 · S.App 1 · S.Ver 1 | **daraltıldı, kapanmadı** | KVKK / veri sorumlusu |
| **K-2** — `istocc` 0+0; betik koşuldu; çıktı tracked (commit `31f115b`) | ✅ **kapandı** — "☐ Düzeltildi ve koşuldu" kutusu artık kanıtlı | Platform yöneticisi (tespit) |
| **K-3** — üretimde `ffmpeg` **ölçülmedi** | erişim yok | Altyapı / DevOps |
| **K-4** — 39 kalemin **18'i** (10 tam + 8 kısmi); 6 raporun metni **düzeltilmedi** | "☐ Kısmen (18/39)" kanıtlı | Platform yöneticisi |
| **K-23** — iki politika seti yan yana (9 vs 13 dosya), kanonik karar **yok** | açık — **G1'in de yarısı** | Ürün / veri sahibi |
| **K-24** — SRS FR-019 (logo alfa) | bu oturumda ölçülmedi **[R]** | Platform yöneticisi |
| **K-25** — megapiksel kapısı **VAR** (`upload_image_bomb`, iki yolda); eşik **ÖLÜ** (80 MP, 0 dosya keser) | **yarısı kapandı** | Backend + Platform yöneticisi |
| **K-10** — 34 görsel + **7 video** (kaynak ≥8 istiyor), 10 kötücül; manifest 51/51 | eksik: 1 video | Platform yöneticisi |
| **K-11** — `pyvips` konteynerde **YOK** → benchmark tekrar çalıştırılamaz | açık | Altyapı / DevOps |
| **G-2** — `docs/reports/` 19 tracked / **34 untracked**; `docs/adr/` **0/18**; toplam 105 untracked | açık, mekanik | Altyapı / DevOps |

### 9.2 Faz 1 (`30-faz1-adr-kapanis.md` — onay bloğu henüz KURULMAMIŞ)

| Karar kalemi | Bugünkü ölçülmüş durum |
|---|---|
| ADR seti var mı | ✅ **17 ADR + README**; 17/17'sinde 5 bölüm tam |
| Geri dönüş yolu bölümü | ❌ **0/17** ayrı bölüm; metin içinde 2 ADR'de (`0002`, `0003`) |
| 8 zorunlu konu | ❌ **6/8** — eksik: *istemci kütüphane seti* (0 ADR), *CDN* (1 yan cümle) |
| Rapor atıfı | ✅ **15/17**; `0011` ve `0012` yalnız `dosya:satır` |
| T-017 (Faz 1'in en ağır bulgusu) | ✅ **10/10 RED**, iki yolda — bu oturumda doğrulandı |
| Faz 1 karnesi | **6 TAM / 4 KISMİ / 0 YOK** (rapor 33'ün 5/4/1'i eskimiş) |
| `11-faz1-arge.md` §11'in 8 ölçülmemiş kalemi | **1 tam · 1 kısmen · 6 açık** |
| **Onay bloğu** | ❌ **fiziksel olarak yok** — kurulması gerekiyor |

### 9.3 Faz 2 (`SRS-v1.0.md` §9.2 — blok var, ad/tarih/imza alanı yok)

| Kapı | Durum | Kapatan kim |
|---|---|---|
| **G1** | 🟡 şema ✅ (9/9, 0 hata) · kanonik set kararı ❌ | Ürün / veri sahibi (= K-23) |
| **G2** | ✅ geçti | — |
| **G3** | ❌ 49 açık soru, 0 CR-ID | üretim ölçümü + onay |
| **G4** | ✅ 14/14 — ⚠ kanıt **beyandır**, imzalı blok yok | Platform yöneticisi |
| **G5** | ❌ **açık** — dize değişti, kalibrasyon yapılmadı; `extreme_blur` RED'i canlının %1,70'ini gizlerdi | insan etiketlemesi (≥300 görsel) |
| **G6** | ❌ 0/9 `active`; üç engel: FR-001 (0 isabet), FR-144 (7/9), FR-149 (0/9) | backend + ürün |
| **G7** | ❌ 7/9 alan var; 5'inde eşik 80 MP → **0 dosya keser** | backend (FR-143 türetme) |
| **§6.2** | ❌ **20/20 kutucuk işaretsiz**; ölçülen 6'nın 1'i karşılanıyor | — |
| **Belge kusuru 1** | G5'in kuralı dize karşılaştırması | SRS metin düzeltmesi |
| **Belge kusuru 2** | G6 ↔ §6.2 çelişkisi | SRS metin düzeltmesi |
| **Altyapı** | `jsonschema` konteynerde ve `requirements.txt`'te **yok** | Altyapı / DevOps |

---

## 10. Ne YAPILMADI

- **Hiçbir onay bloğu doldurulmadı, hiçbir kutucuk işaretlenmedi, hiçbir imza
  alanına yazılmadı.** `07-faz0-kapanis.md` §10'un 29 kutucuğu ve 31 boş alanı
  bu belgeden önce nasılsa öyle duruyor.
- Hiçbir `.py`, DocType JSON, politika JSON dosyasına dokunulmadı.
- `docs/standards/`, `docs/adr/`, `docs/srs/` **yalnız okundu**.
- `docs/reports/33-` … `49-` **yalnız okundu**.
- `admin-panel/`, `docker/` açılmadı.
- `Media Engine Settings` bayrakları **okunmadı ve değiştirilmedi**; hiçbir
  doctype'ta kayıt oluşturulmadı ya da silinmedi. Tüm DB erişimi `SELECT`.
- **Süre ya da performans iddiası yapılmadı.**
- Aşağıdakiler **ölçülmedi** ve bu belge onlar hakkında iddia taşımaz:
  SRS §6.2'nin 14 maddesi · T-008 · T-011 · T-013 · T-014 · T-024 · T-026 ·
  T-027 · T-028 · K-4'ün 39 kalemlik listesi · K-24 (FR-019) · G2 ·
  `docs/standards/` metinlerinin içerik doğruluğu.

---

## Ek A — Yeniden üretme komutları

Tamamı salt okuma. Konteyner betikleri koşum sonrası silinmelidir.

```bash
# --- Faz 0 / K-2 ---
grep -c "istocc" scripts/media_stats.py docs/reports/02-medya-istatistigi.md
git log -1 --format='%h %ad %s' --date=short -- scripts/media_stats.py

# --- Faz 0 / G-2 ---
git ls-files docs/reports | wc -l ; git status --short docs/reports | grep -c '^??'
git ls-files docs/adr | wc -l ; ls docs/adr/*.md | wc -l
git status --short | grep -c '^??'

# --- Faz 1 / ADR yapısı ---
for f in docs/adr/0*.md; do printf "%-45s " "$(basename $f)"; \
  grep '^## ' "$f" | tr '\n' '|'; echo; done
grep -l '^## .*[Gg]eri dönüş' docs/adr/*.md | wc -l          # → 0
grep -liE -e 'mediabunny|uppy|istemci kütüphane|client-side|tarayıcı tarafı' \
  docs/adr/0*.md                                              # → 0 dosya
grep -lw -e 'CDN' docs/adr/0*.md                              # → yalnız 0001

# --- Faz 2 / politika sayımı + şema ---
python3 - <<'PY'
import json,glob,os
tot_oq=tot_null=0
for p in sorted(glob.glob("tradehub_core/media/pipeline/policy/slots/*.json")):
    d=json.load(open(p)); n=0
    def walk(o):
        global n
        if isinstance(o,dict):
            for k,v in o.items():
                if k=="encoder_quality":
                    if v is None: n+=1
                    elif isinstance(v,dict): n+=sum(1 for x in v.values() if x is None)
                else: walk(v)
        elif isinstance(o,list):
            for v in o: walk(v)
    walk(d)
    oq=d.get("open_questions") or []
    print(f"{os.path.basename(p):28} {d.get('status'):6} oq={len(oq):>2} "
          f"encq_null={n:>2} mmp_hard={d.get('accept',{}).get('max_megapixels_hard')}")
    tot_oq+=len(oq); tot_null+=n
print("TOPLAM oq =",tot_oq," encoder_quality null =",tot_null)
PY

python3 - <<'PY'
import json,glob,os
from jsonschema import Draft202012Validator
sch=json.load(open("tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json"))
v=Draft202012Validator(sch); tot=0
for p in sorted(glob.glob("tradehub_core/media/pipeline/policy/slots/*.json")):
    e=list(v.iter_errors(json.load(open(p)))); tot+=len(e)
    print(f"{os.path.basename(p):28} hata={len(e)}")
print("TOPLAM HATA =",tot)
PY

# --- Faz 2 / SRS kutucukları ve kapı kalemleri ---
grep -c '^\s*- \[ \]' docs/srs/SRS-v1.0.md      # 53 (§6.2'de 20)
grep -c '^\s*- \[x\]' docs/srs/SRS-v1.0.md      # 0
grep -o '☐' docs/srs/SRS-v1.0.md | wc -l        # 5   (§9.2 onay bloğu)
grep -c 'slot_key' tradehub_core/media/upload_policy.py            # FR-001 → 0
grep -rn 'th_media_duration_ms' tradehub_core/ | wc -l             # FR-133 → 0
grep -rn '"optimization"' tradehub_core/api/ | wc -l               # FR-064 → 0
python3 -c "import json;print(json.load(open('tradehub_core/media/pipeline/policy/content_rules.json'))['calibration_status'])"

# --- Faz 2 / jsonschema taşınabilirliği ---
docker exec istoc-dev-backend-1 /home/frappe/frappe-bench/env/bin/python \
  -c "import jsonschema" ; grep -rn "jsonschema" requirements.txt pyproject.toml setup.py

# --- Faz 0 / D-2 ve Faz 1 / T-017 ---
# İkisi de konteynere kopyalanan geçici betiklerle koşuldu; gövdeleri §2.2 ve
# §3.3'teki çıktılarla birlikte yukarıda tarif edildi. Koşum sonrası:
#   docker exec -u root istoc-dev-backend-1 rm -f /tmp/<betik>.py
```

---

## Ek B — Bu oturumda DEĞİŞTİRİLMEYENLER

`tradehub_core/**/*.py` · `tradehub_core/**/doctype/**/*.json` ·
`tradehub_core/media/pipeline/policy/**` · `docs/standards/**` · `docs/adr/**` ·
`docs/srs/**` · `docs/reports/33-` … `49-` · `requirements.txt` ·
`admin-panel/` · `docker/` · **her üç kapanış belgesinin onay/imza blokları.**

# 36 — Faz 12 · 13 · 14 doğrulama (ölçümle)

**Tarih:** 2026-08-19 · **Depo:** `tradehub_core` (`ahmet`) · **Ortam:** `istoc.localhost`
(Docker, `istoc-dev-backend-1`) · **Kaynak:** `karacaismail.github.io/imageoptimization/docs/`
→ `70-faz12-headless-teslim.html`, `71-faz13-guvenlik-observability.html`,
`72-faz14-test-kabul.html`

> **Bu belge salt okuma + ölçümdür.** Hiçbir üretim dosyası değiştirilmedi;
> yazılan tek dosya bu rapordur. Üretilen her test kaydı geri alındı (§5).
>
> **Mevcut raporlara güvenilmedi.** `28-faz13-pentest.md`, `29-pentest-duzeltmeleri.md`,
> `31-gorev-numara-hizalama.md` ve `DALGA-A-DEVIR.md` yalnız **çapraz kontrol**
> için okundu; her iddia bu koşumda yeniden ölçüldü ya da **ÖLÇÜLMEDİ** yazıldı.
>
> **Süre/performans iddiası YOKTUR** — bu koşum sırasında makinede paralel üç
> ajan daha çalışıyordu. Hiçbir duvar-saati sayısı raporlanmadı.

---

## 0. Yöntem etiketleri

| Etiket | Anlamı |
|---|---|
| **[T]** | `bench run-tests` koşuldu, çıktısı bu belgede |
| **[Ö]** | Canlı sistemde ölçüldü (`bench console`, gerçek kullanıcı bağlamı) |
| **[H]** | Gerçek HTTP — `curl` ile gateway üzerinden |
| **[D]** | Diskte/DB'de doğrudan sayıldı |
| **[K]** | Kod okundu — `dosya:satır` |
| **ÖLÇÜLMEDİ** | Bu koşumda ölçülemedi; sebebi yazılı |

**Durum işaretleri:** **TAM** = kaynağın kabul kriterlerinin tamamı kanıtlı ·
**KISMİ** = bir kısmı kanıtlı, kalanı değil · **YOK** = karşılığı yok ·
**ÖLÇÜLMEDİ** = bu koşumun kapsamı dışı.

---

## 1. Koşulan testler — ham çıktı

Hepsi `docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module …`

| Modül | Sonuç | Not |
|---|---|---|
| `tests.test_delivery_picture` | **Ran 24 — OK** | T-120 çekirdeği |
| `tests.test_delivery_sizes` | **Ran 22 — OK** | T-121 çekirdeği |
| `tests.test_delivery_rum` | **Ran 26 — OK** | T-123 çekirdeği |
| **Faz 12 toplam** | **72/72 OK** | brifingdeki 72 sayısı doğrulandı |
| `tests.test_e2e_scenarios` | **Ran 39 — OK (skipped=8)** | 31 koştu, **8 atlandı** — §4.2 |
| `tests.test_migration_backfill` | **Ran 50 — OK** | T-143 çekirdeği |
| `tests.test_payment_transaction_isolation` | **Ran 12 — OK** | T1 düzeltmesi |
| `tests.test_verification_status_guard` | **Ran 14 — FAILED (failures=1)** | 🔴 §3.3 |
| `tests.test_rate_limit_guest_bucket` | **Ran 15 — OK** | T9 düzeltmesi |

> 🔴 **`29-pentest-duzeltmeleri.md` "41 yeni test, hepsi yeşil" diyor. Bugün 41
> testin 40'ı yeşil, 1'i KIRMIZI.** Ayrıntı §3.3 — ve kırmızı olan test
> bağımsız ölçümümle birebir aynı boşluğu gösteriyor.

---

## 2. FAZ 12 — Headless teslim ve performans

### 2.1 T-124 çapraz kontrolü — brifingdeki ölçüm tutarlı mı?

**T-124 ölçümü TEKRARLANMADI.** Bayrak açmak yasaktı ve gerek de yoktu; yapılan
şey `DALGA-A-DEVIR.md`'deki iddiaların **bugünkü sistem durumuyla tutarlılığını**
denetlemektir.

| İddia (`DALGA-A-DEVIR.md`) | Bugün ölçülen | Tutarlı? |
|---|---|:--:|
| En ağır ürün sayfası `LST-00560`, **7 görsel** | `Listing.primary_image` 1 + `Listing Image` 6 = **7** [Ö] | ✅ |
| Ham toplam **9,99 MB** | **10 476 759 B = 9,9914 MB** [D] | ✅ |
| Bayraklar sonra kapatıldı | `media_pipeline_enabled=0`, `rendition_on_upload=0`, `manifest_api_enabled=0` [Ö] | ✅ |
| 84 türev silindi | `Media Rendition` = **0** [Ö]; diskte `.avif` = **0** (public+private) [D] | ✅ |
| `Media Asset/Rendition/Job` = 0 | Asset **0**, Rendition **0**, `Media Processing Job` **0** [Ö] | ✅ |
| `File` 5014 (değişmedi) | **5014** [Ö] | ✅ |
| `Media Profile` = 36 (tohum) | **36** [Ö] | ✅ |

**Ham toplamın dökümü** [D] — `sites/istoc.localhost/public/files`:

```
 875 839  191-ff0258.jpg
1 883 369  191 GRİ.jpg
2 186 056  192 GRİ.jpg
 830 715  192-37e2f8.jpg
3 179 140  193 GRİ.jpg
 827 953  193-823272.jpg
 693 687  593-.jpg
──────────
10 476 759 B  =  9,9914 MB
```

**Karar: T-124'ün bayt ölçümü tutarlı.** `LST-00560` gerçekten sitenin o
ölçüdeki ağır sayfası, 7 görsel ve 9,99 MB birebir tutuyor, geri alma da
eksiksiz (türev 0, `.avif` 0, `File` sayısı sabit). Senaryo A/C/D sonuçları
(0,617 / 0,186 / 0,145 MB) **bu koşumda yeniden üretilmedi** — bayrak açmak
gerektiği için bilinçli olarak ölçülmedi; yalnız girdi tarafı (9,99 MB) ve
geri alma tarafı doğrulandı.

**Küçük tutarsızlık (kozmetik):** `DALGA-A-DEVIR.md` üst tabloda `Media Profile`
için **34**, T-124 bölümünde **36** yazıyor; canlı değer **36**. Ayrıca
"`Asset/Rendition/Job` = 0" ifadesindeki `Media Asset Version` ve `Media Job`
tabloları **hiç yok** (`tabMedia Asset Version`, `tabMedia Job` → 1146); iş
kaydı `Media Processing Job` adında ve o da 0.

### 2.2 Faz 12 görev tablosu

| ID | Başlık | Kaynağın kabul kriteri | Durum | Kanıt |
|---|---|---|:--:|---|
| **T-120** | MediaImage / MediaVideo teslim bileşenleri | `<picture>` AVIF→WebP→JPEG · `priority`→`fetchpriority=high` · `width/height` hep · LQIP geçişi · rendition yoksa düzgün yedek · **video: poster, muted-autoplay-loop, playsinline, HLS lazy, reduced-motion** | **KISMİ** | Backend çekirdek `media/pipeline/delivery/picture.py` (525 satır) + **24/24 test OK** [T]. Frontend'de bileşen **`MediaImage` adıyla yok**; karşılığı `tradehubfront/src/components/media/ResponsiveImage.ts` — `width`/`height` her zaman, `fetchpriority`/`loading`/`decoding` üçlüsü, avif/webp kaynakları var [K]. **`MediaVideo` karşılığı YOK**: `ProductVideoSection.ts` ve `compress.video.ts` var, ama poster/muted-autoplay/playsinline/HLS-lazy/reduced-motion sözleşmesini karşılayan bileşen bulunamadı [K]. **CLS = 0 ölçümü ÖLÇÜLMEDİ** (tarayıcı yok) |
| **T-121** | `sizes` değerlerinin gerçek düzenden türetilmesi | Her yerleşim için `sizes` gerçek CSS'ten türetilmiş · **seçilen rendition ile gerçek kutu farkı ≤ %25** · yanlış `sizes` için otomatik test · rapor `docs/reports/120-sizes-dogrulama.md` | **KISMİ** | `media/pipeline/delivery/sizes.py` (621 satır) + **22/22 test OK** [T]. **≤ %25 sapma ÖLÇÜLMEDİ** — kriter Playwright ile `currentSrc` genişliği vs `getBoundingClientRect().width × DPR` karşılaştırması istiyor, tarayıcı yok. **`docs/reports/120-sizes-dogrulama.md` YOK** [D] |
| **T-122** | LCP optimizasyonu ve preload stratejisi | Her sayfa tipinde LCP elementi `priority` · `<link rel=preload imagesrcset>` üretiliyor · carousel'de yalnız ilk slayt eager · **mobil LCP ≤ 2,5 sn** · taban çizgisiyle karşılaştırma | **KISMİ** | `ResponsiveImage.ts` eager/lazy ve `fetchpriority` ayrımını yapıyor; "ilk görsel eager, kalanı lazy" davranışı kodda [K]. `tradehubfront/lighthouserc.cjs` LCP ≤ 2500 ms / CLS ≤ 0,1 / TBT ≤ 300 ms bütçeleriyle var. **Mobil LCP ≤ 2,5 sn ÖLÇÜLMEDİ** (tarayıcı yok). `docs/reports/12-performans-kabul.md` kendi içinde "Faz 12 'sonra' ölçümü henüz **yapılmadı**" diyor |
| **T-123** | Gerçek kullanıcı telemetrisi (RUM) | LCP/CLS/INP **saha** verisi toplanıyor · LCP elementinin asset'i kaydediliyor · p75 panoda · regresyon alarmı · KVKK uyumlu örnekleme | **KISMİ** | `media/pipeline/delivery/rum.py` (543 satır) + **26/26 test OK** [T]; PII reddi, rota şablonu, örneklem, p75 toplama kanıtlı. **Ama modül kendi docstring'inde yazıyor:** *"YAPMAZ: HTTP ucu açmaz, veritabanına yazmaz, `frappe` içe aktarmaz"* [K]. Ölçüldü: **`Media RUM Sample` DocType YOK** [D] · storefront'ta **`web-vitals` bağımlılığı YOK**, `onLCP/onCLS/onINP` çağrısı YOK [D] · **pano YOK, alarm YOK**. Yani **saha verisi bugün toplanmıyor**; var olan şey veri sözleşmesi |
| **T-124** | Faz 12 kapanış: performans kabulü | 4 sayfa tipi × 2 cihaz profili hedefte · taban çizgisine göre sayısal iyileşme ("9 saniye" vakası) · **performans bütçeleri CI'da (Lighthouse CI) eşik; regresyon PR'ı kırıyor** | **KISMİ** | Bayt kriteri: §2.1'de girdi (9,99 MB) ve geri alma **tutarlı** doğrulandı; senaryo çıktıları bu koşumda **yeniden üretilmedi** (bayrak yasağı). **4 sayfa tipi × 2 cihaz profili ÖLÇÜLMEDİ.** 🔴 **CI kriteri KARŞILANMIYOR:** `lighthouserc.cjs` hiçbir workflow'dan çağrılmıyor (`tradehubfront/.github/workflows/` = alpha/beta/deploy/prod/rc, hiçbirinde lighthouse yok) [D] ve config varsayılanı `assertionLevel = "warn"` — yani **regresyon PR'ı kırmıyor** [K] |

**Faz 12 sayım: TAM 0 · KISMİ 5 · YOK 0**

---

## 3. FAZ 13 — Güvenlik ve observability

### 3.1 T1 — `Payment Transaction` çapraz-kiracı IDOR → **KAPANDI (ölçüldü)**

**Kancalar kayıtlı ve YÜKLÜ** [Ö] — dosyada olması yetmez, çalışan sitede yüklü mü diye soruldu:

```
frappe.get_hooks("permission_query_conditions")["Payment Transaction"]
  → ["tradehub_core.permissions.payment_transaction_query_conditions"]
frappe.get_hooks("has_permission")["Payment Transaction"]
  → ["tradehub_core.permissions.payment_transaction_has_permission"]
```

**Gerçek satıcılarla canlı ölçüm** [Ö] — toplam `Payment Transaction` = **3**
(`PAY-00001…3`). Canlıdaki **39** `Marketplace Seller`'dan 4'ü örneklendi:

| Kullanıcı | `frappe.get_list` görünen | `has_permission` (PAY-1/2/3) |
|---|---:|---|
| `avcilarplastik@istoc.com` | **0** / 3 | False · False · False |
| `solingenbicak@istoc.com` | **0** / 3 | False · False · False |
| `cetinplastik@istoc.com` | **0** / 3 | False · False · False |
| `moiplastik@istoc.com` | **0** / 3 | False · False · False |

> **Yöntem uyarısı — kendi hatam, kayda geçiyor.** İlk koşumda `frappe.get_all`
> kullandım ve dört satıcının da **3/3** kaydı gördüğünü ölçtüm. Bu **yanlış
> pozitifti**: `frappe.get_all` izin motorunu bilinçli olarak atlar
> (`ignore_permissions=True`), `frappe.get_list` uygular. Doğru çağrıyla sonuç
> **0/3**. Aynı tuzağa düşen bir "sızıntı var" iddiası görülürse önce çağrının
> `get_all` mı `get_list` mi olduğuna bakılmalı.

**Karar: T1 kapalı.** `test_payment_transaction_isolation` **12/12 OK** [T].

### 3.2 T2 / T3 — KYC / KYB kendini-doğrulama → **KAPANDI (ölçüldü)**

Canlı sömürü denemesi, **gerçek** satıcı rolleri taşıyan gerçek kullanıcılarla,
işlem hiç `commit` edilmeden (`frappe.db.rollback()`):

**T2 — KYC.** `KYC-00023` işlem içinde `Pending`e çekildi, sahibi
`aliturgut.turksab.com` (`Marketplace Seller` + `Seller Owner` + `Verified Seller`,
9 rol) kendi kaydında `status="Verified"` yazmayı denedi:

```
PermissionError: Doğrulama durumunu yalnızca inceleme yetkilisi değiştirebilir.
db_status_after = "Pending"
```

**T3 — KYB.** `KYB-00037`, sahibi `solingenbicak@istoc.com`, aynı senaryo:

```
PermissionError: Doğrulama durumunu yalnızca inceleme yetkilisi değiştirebilir.
db_status_after = "Pending"
```

**Karar: T2 ve T3 kapalı** — ama **tek katmanla**, aşağıdaki nedenle.

### 3.3 🔴 YENİ BULGU — permlevel-4 ikinci katmanı canlıda ETKİN DEĞİL

Brifing "KYC/KYB'de `status` alanı hangi permlevel'da (4 olmalı)" diye sordu.
**Kaynak dosyada 4, canlı veritabanında 1.**

| Nerede | `status` permlevel |
|---|:--:|
| `doctype/kyc_verification/kyc_verification.json` (depo) | **4** |
| `doctype/kyb_verification/kyb_verification.json` (depo) | **4** |
| Konteynerdeki aynı iki JSON | **4** |
| **Canlı `tabDocField`** (KYC) | 🔴 **1** |
| **Canlı `tabDocField`** (KYB) | 🔴 **1** |
| **Çalışma anı `frappe.get_meta(...).get_field("status").permlevel`** | 🔴 **1** (ikisi de) |

**Bağımsız ikinci kanıt — düzeltmenin kendi testi kırmızı** [T]:

```
FAIL: test_permlevel_layer_denies_write_to_seller_roles
      (…test_verification_status_guard…)
      İkinci katman: permlevel-4'te satıcı rollerinde write YOK.
  File ".../tests/test_verification_status_guard.py", line 230
    self.assertEqual(status_permlevel, 4, "status permlevel-4'te değil")
AssertionError: 1 != 4 : status permlevel-4'te değil
Ran 14 tests — FAILED (failures=1)
```

**Kök neden [Ö].** Patch **koştu** — `Patch Log`'da
`tradehub_core.patches.v15_9_26_kyc_kyb_status_permlevel`, `2026-08-19 18:11:41`.
Patch'in yaptığı iş **permlevel-4 `Custom DocPerm` matrisini kurmak**; canlıda o
satırlar gerçekten var (KYC ve KYB için L4: `System Manager`/`Marketplace Admin`/
`Compliance Officer` read+write, `Seller`/`Marketplace Seller`/`Seller Owner`
read-only). **Ama alanı 1'den 4'e taşıyan şey patch değil, DocType senkronu**
(`bench migrate` / `reload_doc`) ve o **çalışmamış**. Sonuç: matris L4 için
hazır, alan hâlâ L1'de duruyor.

**Etki — ölçüldü.** `status` L1'de ve `Marketplace Seller`'ın KYC/KYB'de
**L1 write=1** satırı var. Yani izin katmanı satıcının `status` yazmasını
**engellemiyor**; §3.2'de sömürüyü durduran tek şey `validate()` içindeki
`guard_verification_status_change()` (`permissions.py:2898`). Düzeltmenin
tasarımı iki katmanlıydı (`kyc_verification.py:88-99` docstring'i bunu açıkça
yazıyor: *"İzin katmanı … TEK savunma değil"*); **bugün canlıda tek katman
çalışıyor.** Guard'da bir regresyon olursa arkasında ağ yok.

> **Yan gözlem (aynı ölçümden).** `Buyer` rolündeki bir kullanıcı kendi
> KYC'sinde `status="Verified"` yazıp `save()` çağırdığında **istisna almıyor,
> `save()` başarılı dönüyor** — ama alan sessizce eski değerine dönüyor
> (`doc.status` save sonrası `"Pending"`, DB `"Pending"`). Sebep: `Buyer`'ın
> L1 satırı yok, Frappe `validate_higher_perm_levels()` alanı geri yazıyor,
> dolayısıyla `has_value_changed("status")` False oluyor ve guard hiç
> çalışmıyor. Sızıntı yok, ama **sessiz başarı** yanıltıcı: istemci
> "kaydedildi" görüyor. Guard yolundan geçen satıcı rolleri açık `PermissionError`
> alıyor; `Buyer` almıyor. Tutarsız geri bildirim.

**Önerilen doğrulama komutu** (bu koşumda çalıştırılmadı — kod/DB değiştirir):
`bench --site istoc.localhost migrate` sonrası
`frappe.get_meta("KYC Verification").get_field("status").permlevel` → 4 olmalı
ve `test_verification_status_guard` 14/14 yeşile dönmeli.

### 3.4 T9 — Misafir hız-sınırı kovası → **KAPANDI, rapordan İYİ durumda**

`29-pentest-duzeltmeleri.md` bunu **"🟡 KOD KAPATILDI, UÇTAN UCA AÇIK"**
işaretlemiş ve gerekçe olarak "bugünkü nginx zinciri istemci IP'sini yok
ediyor" demiş. **Bugün uçtan uca da kapalı.**

**Kod tarafı** [K]: `api/rate_limit.py:163` → `f"Guest:{_client_ip() or _UNRESOLVED_IP}"`;
`_client_ip()` XFF zincirini **sağdan sola** yürüyüp güvenilir vekil olmayan ilk
adresi alıyor (`:127-141`), güvenilir ağlar RFC1918 + CGNAT + loopback (`:70-82`).

**Topoloji tarafı** — rapor 29'un kapsam dışı bıraktığı kısım **çözülmüş**:
`docker/docker-compose.yml:210-213` `frappe-frontend`'e `UPSTREAM_REAL_IP_ADDRESS=192.168.97.0/24`,
`UPSTREAM_REAL_IP_HEADER=X-Forwarded-For`, `UPSTREAM_REAL_IP_RECURSIVE=on`
veriyor **ve çalışan konteynerde etkin** [Ö]:

```
$ docker exec istoc-dev-frappe-frontend-1 env | grep REAL_IP
UPSTREAM_REAL_IP_ADDRESS=192.168.97.0/24
UPSTREAM_REAL_IP_RECURSIVE=on
UPSTREAM_REAL_IP_HEADER=X-Forwarded-For
$ … grep real_ip /etc/nginx/conf.d/frappe.conf
set_real_ip_from 192.168.97.0/24;  real_ip_header X-Forwarded-For;  real_ip_recursive on;
```

**Uçtan uca kanıt** [H] — gateway üzerinden, `allow_guest` + `@rate_limit`
taşıyan gerçek uç (`media_manifest.get_manifest_batch`), iki farklı istemci IP'si:

```
curl -H "X-Forwarded-For: 203.0.113.11"  … → 200
curl -H "X-Forwarded-For: 198.51.100.22" … → 200

redis-cache db0:
  _429e9b47c486be76|rl:media_manifest_batch:Guest:203.0.113.11
  _429e9b47c486be76|rl:media_manifest_batch:Guest:198.51.100.22
```

**İki ayrı kova.** Rapor 28'deki DoS (bir saldırgan pencereyi doldurunca tüm
anonim trafik kilitleniyor) **artık üretilemiyor**. `test_rate_limit_guest_bucket`
**15/15 OK** [T].

**Kalan risk — aynı ölçümden düştü, kayda geçiyor.** Bu kovaları ayıran şey
**istemcinin gönderdiği** `X-Forwarded-For` başlığı; zinciri temizleyen güvenilir
bir dış kenar (CDN/WAF) yok. Yukarıdaki iki kovayı **ben uydurma başlıklarla
açtım**. Yani bir saldırgan `X-Forwarded-For`u döndürerek **kendi limitinden
kaçabilir** (her istekte taze kova). Kapanan şey "tek kova → herkesi kilitleme"
(DoS); kapanmayan şey "başlık uydurarak kendi limitini atlama" (limit kaçırma).
Üretimde XFF'i ezen bir kenar konmadıkça bu açık kalır.

### 3.5 T4 — `Compliance Officer` KYC'yi okuyamıyor → **HÂLÂ AÇIK (ters yön)**

Pentest'in kapatılmayan 4'üncü bulgusu. Doğrulandı, **ters yönde boşluk
duruyor**.

**DocPerm kanıtı** [Ö] — KYC ve KYB'de `Compliance Officer` **yalnız permlevel
1, 2, 3, 4** satırlarında var; **permlevel-0 satırı YOK**. (KYC L0 sahipleri:
`System Manager`, `Marketplace Admin`, `Buyer`, `Seller`, `Marketplace Seller`,
`Seller Owner`. KYB L0: `System Manager`, `Marketplace Admin`, `Seller`,
`Seller Owner`, `Marketplace Seller`.) Frappe'de L0 read olmadan belge hiç
açılmaz.

**Davranış kanıtı** [Ö] — geçici `Compliance Officer` kullanıcısı açıldı, ölçüldü,
geri alındı:

```
roles = ["All","Compliance Officer","Desk User","Guest"]
frappe.has_permission("KYC Verification","read") → False
frappe.has_permission("KYB Verification","read") → False
frappe.get_list("KYC Verification")            → PermissionError
get_doc("KYC-00023").check_permission("read")  → PermissionError
```

**Ek olarak** [Ö]: canlıda `Compliance Officer` rolünü taşıyan **0 kullanıcı**
var. Yani rol tanımlı, kimseye atanmamış, atansa da KYC/KYB'yi açamıyor —
KVKK/AML denetim rolü görevini yapamaz durumda. `29-pentest-duzeltmeleri.md`
bunu kapsamına almamış; **doğru**, kapatılmamış olarak duruyor.

### 3.6 Pentest raporunun kapsamadıkları

| Kaynak T-135 kriteri | Durum |
|---|---|
| Sızma testi, kritik/yüksek bulgu kalmamış | **KISMİ** — 10 vektör test edildi, 3'ü kapatıldı ve **bu koşumda kapalı doğrulandı**; T4 açık, T6 (imzalı belirsiz-blob) kod açığı olarak duruyor |
| **Yük testi** — hedef eşzamanlıda p95 finalize, kuyruk derinliği, hata oranı | **YOK** — `28-faz13-pentest.md` §5 "Yük testi — neden yapılmadı" başlığıyla **bilinçli** atladığını yazıyor. Kabul kriteri karşılanmıyor |
| **Kaos testi** — worker öldürme / Redis kesintisi / S3 kesintisi, veri kaybı yok | **YOK** — pentest raporunda kaos bölümü **hiç yok** (§0-§9 arasında yer almıyor). `test_e2e_scenarios.py`'deki S3 senaryosu sahte ayna üzerinde koşuyor, gerçek kesinti değil; `test_gercek_S3_ile_OLCULMEDI` zaten atlanmış. **Brifingde "yük testi bilinçli atlandı" denmişti; kaos testi ondan ayrı ve o hiç anılmamış.** |

### 3.7 Faz 13 görev tablosu

| ID | Başlık | Kaynağın kabul kriteri | Durum | Kanıt |
|---|---|---|:--:|---|
| **T-130** | Worker izolasyonu ve kaynak limitleri | Ayrı süreç · RLIMIT/cgroup + süre limiti · limit aşımı `failed` yapıp worker'ı öldürmüyor · FS/ağ kısıtlı · libvips/FFmpeg pinli + CI'da CVE taraması | **ÖLÇÜLMEDİ** | Varlık taraması yapıldı: `media/pipeline/security/isolation.py` + `tests/test_isolation.py` var (`RLIMIT_AS`/`RLIMIT_CPU` geçiyor) [D]. **Testi koşulmadı** (brifing kapsamı dışı). **CI'da `pip-audit`/`trivy` adımı YOK** — `.github/workflows/` taramasında hiç geçmiyor [D] → bu alt kriter **karşılanmıyor** |
| **T-131** | SVG sanitizasyonu, CSP, dosya servis güvenliği | Script/handler/dış ref/entity kalmıyor · ayrı origin ya da CSP sandbox · `nosniff` + doğru `Content-Type` · HTML/JS asla inline | **ÖLÇÜLMEDİ** (kısmen pentest kapsadı) | `media/pipeline/security/svg.py` + `tests/test_svg_sanitize.py` var [D], **bu koşumda koşulmadı**. `28-faz13-pentest.md` T8: 5/5 yük nötrlendi. `nosniff` storefront ve admin nginx şablonlarında var [D]; **`deploy/nginx/media.conf` YOK** — kaynak dokümanın istediği ayrı medya origin'i bulunamadı |
| **T-132** | Yetki sertleştirme ve sızıntı testleri | Satıcı başka satıcının asset'ine hiçbir uçtan erişemiyor (404) · sır hiçbir yanıt/log/traceback'te yok · **tüm whitelisted metotlar taranmış** · IDOR + path traversal geçiyor | **KISMİ** | IDOR tarafı bu koşumda **kapalı doğrulandı** (§3.1, 0/3 + `has_permission` False). Path traversal ve SVG: pentest 4/4 ve 5/5 engelledi (bu koşumda tekrarlanmadı). **"Tüm whitelisted metotlar taranmış" — otomatik tarayıcı YOK** [D]; kriter karşılanmıyor. `docs/reports/130-guvenlik-test.md` **YOK** |
| **T-133** | Gözlemlenebilirlik: metrik, log, iz, alarm | Prometheus metrikleri · JSON log + correlation_id · **panolar** · **alarmlar** · her alarm için runbook bağlantısı | **KISMİ** | `media/pipeline/observability/metrics.py` ve `logging.py` + `tests/test_observability.py` var [D], koşulmadı. 🔴 **`deploy/grafana/` YOK · `docs/ops/runbooks/` YOK** [D] — pano ve alarm-runbook kriterleri karşılanmıyor (runbook metinleri `docs/plans/faz14-golive.md` §5 içinde duruyor, ayrı dosya olarak değil) |
| **T-134** | Denetim izi ve KVKK uyumu | Silme/ayar/onay/retention/sır erişimi audit'e yazılıyor · append-only · **KVKK envanteri + veri sahibi talebi akışı** · aydınlatma metni | **KISMİ** | 🔴 **`Media Audit Log` DocType YOK** [D] (genel `tradehub_core/audit/` modülü var, medya denetimi değil). 🔴 **`docs/compliance/kvkk.md` YOK**, `docs/` altında hiç KVKK/compliance dosyası yok [D]. EXIF GPS strip tarafı var (`media/pipeline/image/normalize.py`) |
| **T-135** | Faz 13 kapanış: sızma + yük + kaos | Kritik/yüksek bulgu kalmamış · yük testi hedefte · kaos senaryolarında veri kaybı yok | **KISMİ** | Sızma testi yapıldı ve 3 bulgusunun kapandığı **bu koşumda bağımsız doğrulandı** (§3.1-3.4). **T4 açık** (§3.5). **Yük testi YOK · kaos testi YOK** (§3.6). `docs/reports/135-guvenlik-yuk-kabul.md` **YOK** |

**Faz 13 sayım: TAM 0 · KISMİ 4 · YOK 0 · ÖLÇÜLMEDİ 2**

**Pentest bulguları ayrı sayım (brifingin sorduğu):**
**T1 KAPALI ✅ · T2 KAPALI ✅ (tek katman) · T3 KAPALI ✅ (tek katman) ·
T9 KAPALI ✅ (rapordakinden iyi) · T4 AÇIK ❌ · permlevel-4 katmanı ETKİN DEĞİL 🔴**

---

## 4. FAZ 14 — Test, doğrulama, kabul

### 4.1 T-142 ve T-144 gerçekten koşulmamış mı? → **Evet, koşulmamış**

Brifing "plan var, oturum yok" dedi; doğrulandı — hem belgelerin kendi beyanıyla
hem bağımsız dosya taramasıyla.

| Kanıt | Sonuç |
|---|---|
| `docs/plans/faz14-uat.md` §0 (345 satır) | *"**BU BİR PLANDIR. PİLOT KOŞULMADI.** … satıcıdan gelmiş tek bir ölçüm, tamamlanmış tek bir görev, hesaplanmış tek bir tamamlama oranı **yoktur**"* |
| `docs/plans/faz14-golive.md` §0 (559 satır) | *"**DEVREYE ALMA YAPILMADI. GERİ DÖNÜŞ PROVASI KOŞULMADI.** … o süre **ÖLÇÜLMEDİ**"* |
| **`docs/qa/` dizini** | **YOK** [D] — `uat-plan.md`, `evidence/`, `final-acceptance.md`, `traceability.md` hiçbiri orada değil |
| **`docs/ops/` dizini** | **YOK** [D] — `go-live.md` ve `runbooks/` ayrı dosya olarak üretilmemiş |
| UAT bulgu kaydı | **YOK** — pilot koşulmadığı için bulgu da yok |
| Özellik bayrağı (aşamalı açılış için) | `faz14-golive.md` §1: *"Kod tabanında medya için böyle bir bayrak **bulunamadı**"* |
| Canlı sistem | `Media Asset` 0 · `Media Rendition` 0 · bayraklar 0 [Ö] — hiçbir devreye alma izi yok |

**Karar: T-142 ve T-144'ün "koşulmadı" beyanı doğru.** İkisi de dürüst yazılmış;
plan belgelerinin kendisi kabul kriterlerini "GEÇTİ" işaretlemiyor.

### 4.2 E2E paketinin 8 atlanan testi

`test_e2e_scenarios.py` **39 test — OK (skipped=8)**. Atlananlar "yeşil" değildir;
gerekçeleriyle birlikte:

| Atlanan test | Gerekçe (dosyadan) | Ne anlama geliyor |
|---|---|---|
| `test_arayuzde_gosterim_OLCULMEDI` | Tarayıcı yok; anlama oranı T-142'nin işi | UAT'a bağlı |
| `test_urun_sayfasi_LCP_OLCULMEDI` | LCP yalnız gerçek tarayıcıda; NFR-008 bütçesi ÖLÇÜLMEDİ | Faz 12 ile aynı boşluk |
| `test_arayuzde_onizleme_OLCULMEDI` | **Crop Studio ve önizleme simülatörü EKRANI yazılmadı** | Faz 10/11 belge seviyesinde |
| `test_onizleme_onay_kapisi_YOK` | **"Önizlemeden geçmeden onaylayamaz" kuralının kodda KARŞILIĞI YOK** | Kaynak dokümanın **5. kritik senaryosu** uygulanmamış |
| `test_yalniz_etkilenen_rendition_YENIDEN_URETILIR_OLCULMEDI` | **İş planlayıcı YOK** | Kaynak dokümanın **6. senaryosu** kısmen yok |
| `test_VMAF_OLCULEMEDI` | Konteynerdeki ffmpeg 5.1.9 **libvmaf içermiyor** | **8. senaryo** (VMAF ≥ 93) KANIT YOK |
| `test_gercek_S3_ile_OLCULMEDI` | boto3 yok, dış ağa çıkılmıyor | **11. senaryo** yalnız sözleşme düzeyinde |
| `test_tembel_yeniden_uretim_ucu_YOK` | **ON-DEMAND teslim ucu uygulanmadı** | **12. senaryo** uygulanmamış |

> Kaynak doküman 12 kritik senaryonun **tümünün otomatik ve GREEN** olmasını,
> her senaryonun **ekran görüntüsü/video kaydı** üretmesini istiyor. Bugün:
> Playwright yok, kayıt yok, `docs/qa/evidence/` yok ve **12 senaryonun en az
> 4'ünün (5, 6, 8, 12) kodda karşılığı yok**.

### 4.3 Faz 14 görev tablosu

| ID | Başlık | Kaynağın kabul kriteri | Durum | Kanıt |
|---|---|---|:--:|---|
| **T-140** | İzlenebilirlik matrisi (SRS → test) | **Her FR/NFR en az bir teste bağlı; bağsız gereksinim YOK** · her INV ≥1 property/golden test · matris otomatik ve **CI'da güncel** | **KISMİ** | Üretici var: `scripts/gen_traceability.py`; çıktı `docs/test/traceability.md` [D]. **Matris kendi içinde kriteri karşılamadığını yazıyor:** 202 gereksinimin **74'ü (%36,6)** bağlı, **128'i (%63,4) KAPSANMIYOR** → *"bugün **SAĞLANMIYOR**"*. 🔴 **CI zorlaması YOK** — `.github/workflows/` içinde `traceability` geçmiyor [D]. `@pytest.mark.req` / `@pytest.mark.inv` etiketleri **hiçbir teste konmamış** [D] |
| **T-141** | E2E senaryo paketi | **12 senaryonun tümü otomatik ve GREEN** · her senaryo ekran görüntüsü/video üretiyor · temiz kurulumda sıfırdan | **KISMİ** | `tests/test_e2e_scenarios.py` **39 test, 31 koştu, 8 atlandı** [T]. Playwright değil, unittest. **Ekran görüntüsü/video YOK**, `docs/qa/evidence/` **YOK** [D]. 12 senaryodan **5, 6, 8, 12** kodda karşılıksız (§4.2) |
| **T-142** | UAT ve satıcı pilotu | ≥10 gerçek satıcı, her biri ≥5 ürün · tamamlanma oranı/süre ölçülmüş · anlama oranı ≥%90 · bulgular önceliklendirilmiş | **YOK** | `docs/plans/faz14-uat.md` **plan olarak var (345 satır)**, koşum **yok** — belge kendisi *"PİLOT KOŞULMADI"* diyor. Bağımsız doğrulama: `docs/qa/` dizini yok, bulgu kaydı yok [D]. Plan ayrıca pilotun **bugün koşulamayacağını** kanıtlıyor: görev (b) ve (c) için **arayüz yazılmamış** |
| **T-143** | Geçiş (backfill) uygulaması ve izleme | Parti parti düşük öncelikli kuyruk, **canlı trafiği etkilemediği ölçümle kanıtlı** · ilerleme/hata/tahmini bitiş **panoda** · eşik aşılırsa **otomatik duruyor** · **geri alma prova edilmiş** · **satıcılar bilgilendirilmiş** | **KISMİ** | Kod tam: `media/pipeline/migration/backfill.py` (862 satır) — `StopPolicy.error_rate_max`, `evaluate_stop`, `LiveTrafficGuard`, `AtomicSwitch`, `SellerNotice`/`build_notices`, `dashboard()` [K]; **50/50 test OK** [T]. 🔴 Ama: **backfill canlıda koşmadı** (`Media Asset` 0, `Media Rendition` 0) [Ö] · **canlı trafik koruması yük testiyle kanıtlanmadı** (kriter bunu açıkça istiyor) · **pano bir arayüz değil, `dict` döndüren bir fonksiyon** · **geri alma provası koşulmadı** · **satıcılara bildirim gitmedi** |
| **T-144** | Devreye alma (go-live) ve runbook'lar | Aşamalı açılış planı · **geri dönüş prova edilmiş ve süresi ölçülmüş** · runbook'lar · nöbet/eskalasyon | **KISMİ** | `docs/plans/faz14-golive.md` (559 satır): aşama tablosu §2.1, geri dönüş prosedürü §3, **8 runbook** §5 (R1-R8), nöbet/eskalasyon §4 — **yazılı kısım tam**. 🔴 **Prova YOK, süre ÖLÇÜLMEDİ** (§3.4 başlığı zaten "Prova — ÖLÇÜLMEDİ"). **Aşamalı açılışın dayandığı özellik bayrağı mekanizması yok** (§1). `docs/ops/runbooks/` **YOK** [D] |
| **T-145** | Nihai kabul dosyası ve devir | Tüm faz çıkış kriterleri işaretli ve kanıtlı · **izlenebilirlik matrisi %100** · açık bulgu listesi · devir · **platform yöneticisi imzası** | **KISMİ** | `docs/reports/13-faz14-kabul.md` var ve dürüst bir işaret sistemi kullanıyor (KANITLI/KISMEN/KANIT YOK/KAPSAM DIŞI). 🔴 **İzlenebilirlik %36,6** — %100 kriteri karşılanmıyor (T-140). **İmza yok** (kapsam dışı: imza yetkisi yok). `docs/qa/final-acceptance.md` **YOK** [D] |

**Faz 14 sayım: TAM 0 · KISMİ 5 · YOK 1**

---

## 5. Koşum hijyeni — üretilen her şey geri alındı

Bu koşum **canlı veriye üç yerde dokundu** ve üçü de geri alındı. Doğrulama
sayıları koşum sonrası yeniden okundu [Ö]:

| Ne üretildi/değiştirildi | Nasıl geri alındı | Koşum sonrası doğrulama |
|---|---|---|
| `KYC-00023` işlem içinde `Pending`e çekildi, satıcı `Verified` denedi | `frappe.db.rollback()` (hiç `commit` yok) | `KYC-00023` = **`Verified`** ✅ |
| `KYB-00037` aynı senaryo | `frappe.db.rollback()` | `KYB-00037` = **`Verified`** ✅ |
| `KYC-00024` üzerinde `Buyer` denemesi | `frappe.db.rollback()` | `KYC-00024` = **`Pending`** ✅ |
| Geçici kullanıcı `verify36_co@example.local` (`Compliance Officer`) | `frappe.db.rollback()` | `User` sayısı **63 → 63**, `exists()` = **null** ✅ |
| 2 Redis hız-sınırı kovası (uydurma IP'ler) | `redis-cli DEL` (2 anahtar silindi) | `rl:*` taraması **boş** ✅ |
| Konteynere kopyalanan `/tmp/chk12.py` | ölçümde kullanılmadı (komut hatası), zararsız | — |

**Toplam sayılar koşum öncesi/sonrası aynı:** `KYC Verification` **24**,
`KYB Verification` **37**, `User` **63**, `Payment Transaction` **3**,
`Media Rendition` **0**, `Media Asset` **0**, `Media Processing Job` **0**,
`Media Profile` **36**.

🔒 **`Media Engine Settings` bayraklarına DOKUNULMADI** — koşum boyunca ve
sonunda `media_pipeline_enabled=0`, `rendition_on_upload=0`,
`manifest_api_enabled=0`. **T-124 ölçümü TEKRARLANMADI.**

📄 **Değiştirilen üretim dosyası: 0.** Yazılan tek dosya bu rapordur.
(`git status`'taki `M` işaretli dosyalar paralel koşan diğer ajanların işidir,
bu koşumun değil.)

---

## 6. Sayım

### 6.1 Faz bazında

| Faz | TAM | KISMİ | YOK | ÖLÇÜLMEDİ | Toplam |
|---|:--:|:--:|:--:|:--:|:--:|
| **Faz 12** (T-120…T-124) | **0** | **5** | 0 | 0 | 5 |
| **Faz 13** (T-130…T-135) | **0** | **4** | 0 | **2** | 6 |
| **Faz 14** (T-140…T-145) | **0** | **5** | **1** | 0 | 6 |
| **TOPLAM** | **0** | **14** | **1** | **2** | **17** |

### 6.2 Neden hiç TAM yok

Üç fazın da görevleri aynı desende kırılıyor: **çekirdek Python katmanı yazılmış
ve testleri geçiyor, ama kabul kriterinin "üretimde/ölçümde kanıtla" diyen yarısı
karşılanmamış.** Somut olarak:

- **Tarayıcı yok** → T-120 (CLS 0), T-121 (≤%25 sapma), T-122 (LCP ≤2,5 sn),
  T-124 (4×2 profil), T-141 (Playwright + kayıt) ölçülemiyor. Bu bir eksiklik
  değil, **kapsam sınırı** — ama kriter yine de karşılanmamış durumda.
- **Uç/DocType bağlanmamış** → T-123 (RUM saha verisi toplanmıyor), T-134
  (`Media Audit Log` yok). Sözleşme var, boru yok.
- **CI'ya bağlanmamış** → T-124 (Lighthouse bütçesi), T-130 (pip-audit/trivy),
  T-140 (traceability kapısı). Üçü de "regresyon CI'ı kırsın" diyor, üçü de
  workflow'larda yok.
- **Koşulmamış oturumlar** → T-142 (pilot), T-144 (geri dönüş provası),
  T-135 (yük + kaos), T-143 (canlı backfill).

### 6.3 Bu koşumun üç somut çıktısı

1. 🔴 **`status` permlevel-4 ikinci katmanı canlıda etkin değil** (§3.3) —
   kaynak dosyada 4, `tabDocField`'da ve çalışma anı meta'sında **1**. Patch
   koştu ama DocType senkronu koşmadı. Düzeltmenin **kendi testi kırmızı**
   (`test_verification_status_guard` 13/14). `29-pentest-duzeltmeleri.md`'nin
   "41 test, hepsi yeşil" beyanı bugün geçerli değil. KYC/KYB kendini-doğrulama
   şu an **tek katmanla** (controller guard) tutuluyor.

2. ✅ **T9 rapordan daha iyi durumda** (§3.4) — rapor 29 "uçtan uca AÇIK"
   demiş; `docker-compose.yml`'deki `real_ip` düzeltmesi çalışan konteynerde
   etkin ve gerçek HTTP ile **iki ayrı misafir kovası** ölçüldü. Kalan risk:
   XFF uydurarak kendi limitinden kaçma (kanıtlandı — kovaları uydurma
   başlıklarla ben açtım).

3. ✅ **T-124'ün bayt ölçümü tutarlı** (§2.1) — `LST-00560` bağımsız olarak
   sayıldı: **7 görsel, 10 476 759 B = 9,9914 MB**, iddia edilen "9,99 MB" ile
   birebir. Geri alma da eksiksiz: `Media Rendition` 0, diskte `.avif` 0,
   `File` 5014 sabit, bayraklar 0. **Ölçüm tekrarlanmadı.**

### 6.4 Ölçülmedi olarak kalanlar (dürüstlük kaydı)

- **T-130, T-131** — modülleri ve testleri var, bu koşumda **koşulmadı**
  (brifing kapsamı Faz 12 delivery + Faz 14 e2e/backfill + Faz 13 pentest
  doğrulamasıydı). Yalnız varlık taraması ve CI/nginx alt kriterleri ölçüldü.
- **T-133, T-134** — testleri koşulmadı; yalnız eksik çıktılar (`deploy/grafana/`,
  `docs/ops/runbooks/`, `Media Audit Log`, `docs/compliance/kvkk.md`) **yokluk
  olarak** ölçüldü.
- **T-124 senaryo A/C/D çıktıları** — bayrak açmak gerektiği için bilinçli
  ölçülmedi.
- **Tarayıcı gerektiren her kriter** — LCP, CLS, `sizes` sapması, E2E kayıtları.
- **Yük testi ve kaos testi** — bu koşumda da yapılmadı; paralel ajan yükü
  altında anlamlı bir yük ölçümü zaten üretilemezdi.

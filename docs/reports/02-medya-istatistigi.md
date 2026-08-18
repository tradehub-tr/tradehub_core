# Üretim Medya İstatistiği — elde olan veriyle

**T-003** · Medya Motoru Fazı 0 · Rapor tarihi: **2026-08-17**
Branch: `medya-motoru-faz0-faz2` · Çalışma alanı: `/Users/ahmet/Desktop/istoc-medya-wt`

---

## 0. Bu rapor ne yapar, ne yapmaz

**Yapar:** Kod tabanında ve tasarım belgelerinde **daha önce ölçülmüş** medya
sayılarını tek yerde toplar, her sayının kaynağını `dosya:satır` olarak verir,
kaynaklar arasındaki **çelişkileri aritmetikle gösterir** ve eksik metrikleri
üretecek sorguları yazar.

**Yapmaz — ve yapamaz:** Hiçbir sayıyı bu oturumda ölçmedim.

| Kısıt | Durum |
|---|---|
| Docker | Kapalı |
| Üretim veritabanı | Erişim yok |
| Canlı site | Erişim yok |
| `bench` | Çalıştırılmadı |

**Bu raporda geçen hiçbir sayı benim ölçümüm değildir.** Hepsi başka birinin
belirli bir tarihte yaptığı ve koda/belgeye yazdığı ölçümün alıntısıdır. Tek
kendi katkım: alıntıların **aritmetik tutarlılığının** kontrolü (§3) — o da
saf hesap, veri değil.

Ölçülmesi gereken ama ölçülemeyen her şey §6 (çalıştırılacak sorgular) ve §7
(**ÜRETİMDE DOĞRULANMALI**) bölümlerindedir. Çalıştırılabilir hâli:
`scripts/media_stats.py`.

---

## 1. Kaynaklar ve tarihleri

Ölçüm tarihleri git ile bulundu — `git log -S"<sayı>" --format=%ad --date=short`
çıktısının **en eski** satırı, yani o sayının koda ilk girdiği commit.

| # | Kaynak | Ölçümün koda giriş tarihi |
|---|---|---|
| K1 | `docs/MEDYA-DEPOLAMA-STANDARDI.md` (TUR-130) | 2026-08-14 |
| K2 | `docs/MEDYA-ERISIM-MODELI.md` (TUR-126) | 2026-08-14 |
| K3 | `tradehub_core/media/inventory.py` | 2026-08-06 |
| K4 | `tradehub_core/media/upload_policy.py` | 2026-08-14 |
| K5 | `tradehub_core/media/ownership.py` | 2026-08-13 |
| K6 | `tradehub_core/media/gates.py` | 2026-08-06 |
| K7 | `tradehub_core/media/backup.py` | 2026-08-13 |
| K8 | `tradehub_core/media/presets.py` + `media/access_level.py` | 2026-08-14 |
| K9 | `docs/superpowers/specs/2026-08-13-medya-sikistirma-kota-url-design.md` | 2026-08-13 |
| K10 | `tradehub_core/media/usage.py`, `audit.py`, `backup_export.py`, `files.py`, `engine.py`, `metadata.py` | 2026-08-06 … 08-14 |

> **Kayıp kaynak.** Kodda **8 yerde** `GORSEL-OPTIMIZASYON.md` §2.1/§3/§4.1-4.3/§6/§7.3/§8/§10.1/§11'e atıf var
> (`media/gates.py:5`, `media/presets.py:3`, `media/inventory.py:15,440`,
> `media/engine.py:11`, `media/archive.py:3`, `media/runner.py:62`,
> `tradehub_core/hooks.py:130`, `api/media_admin.py:8`).
> **Bu dosya çalışma alanında YOK** (`find /Users/ahmet/Desktop/istoc*
> -iname "GORSEL-OPTIMIZASYON*"` → boş). Preset seçimlerinin (2000px/q88),
> kapı gerekçelerinin ve %3 kalite ölçümünün asıl kanıtı **kayıp**. Kodda
> yalnız özetleri var. Bkz. §3, T-9.

---

## 2. Bugün BİLİNEN dağılım

### 2.1 Depolama düzlemi — dosya sayıları

| Metrik | Değer | Kaynak | Tarih |
|---|---:|---|---|
| `public/files/` dosya sayısı | **2.858** | K1 `MEDYA-DEPOLAMA-STANDARDI.md:31` | 2026-08-14 |
| `private/files/` dosya sayısı | **192** | K1 `MEDYA-DEPOLAMA-STANDARDI.md:32` | 2026-08-14 |
| Dizin yapısı | **DÜZ** (alt dizin yok) | K1 `:31-32` | 2026-08-14 |
| Tahmin-edilebilir eski ad (`0505.jpg`) | **2.166** | K1 `MEDYA-DEPOLAMA-STANDARDI.md:150` | 2026-08-14 |
| Public görsellerin tahmin-edilebilir oranı | **~%50** | K9 `…design.md:22` | 2026-08-13 |
| Enumeration kanıtı | **12 kör denemede 4 isabet** | K9 `…design.md:22` | 2026-08-13 |
| Kırılmaması gereken mevcut URL | **4.324** | K9 `…design.md:104` | 2026-08-13 |

### 2.2 Aynı düzlemin FARKLI sayıları — kod içinden

Aşağıdaki sayılar da "public dosya" diyor ama **hiçbiri 2.858 değil**. Çelişki
analizi §3.2'de.

| Değer | Ne dediği | Kaynak | Tarih |
|---:|---|---|---|
| **938** | tekil `file_url` (public) | K3 `media/inventory.py:10` | 2026-08-06 |
| **2.860** | o 938 adrese düşen `tabFile` **kaydı** | K3 `media/inventory.py:10` | 2026-08-06 |
| **2.826** | "tümünü optimize et" işinin dosya sayısı | K3 `media/inventory.py:444` | 2026-08-06 |
| **209** | aynı anda ekranda görünen satır | K3 `media/inventory.py:444` | 2026-08-06 |
| **2.839** | public dosya (sahiplik ölçümü) | K5 `media/ownership.py:4,6` | 2026-08-13 |
| **2.800** | tipik optimizasyon işinin dosya sayısı | K10 `media/audit.py:15` | 2026-08-06 |
| **4.003** | public dosya (boyut tavanı ölçümü) | K4 `media/upload_policy.py:45` | 2026-08-14 |
| **4.007** | dosya (kapı ölçümü) | K6 `media/gates.py:8` | 2026-08-06 |
| **4.195** | dosya (yedek ölçümü) | K7 `media/backup.py:7` | 2026-08-13 |
| **4.324** | URL (isimlendirme ölçümü) | K9 `…design.md:104` | 2026-08-13 |
| **4.800** | `tabFile` kaydı (backfill gerekçesi) | K3 `media/inventory.py:5` | 2026-08-06 |
| **4.900** | yedek dışa aktarımında satır | K10 `media/backup_export.py:339` | 2026-08-14 |
| **1.500** | uzantı-içerik denetimi yapılan dosya | K4 `media/upload_policy.py:25` | 2026-08-14 |
| **3.000** | istemci/sunucu ayrışma testi girdisi | K4 `media/upload_policy.py:414-415` | 2026-08-14 |
| **356 / 333** | "hiç kullanılmamış" sayacı / filtre satırı | K10 `media/usage.py:414-415` | 2026-08-06 |

### 2.3 Private dağılımı

| `attached_to_doctype` | Adet | Kaynak |
|---|---:|---|
| KYB Verification | 489 | K2 `MEDYA-ERISIM-MODELI.md:47-48` |
| *(owner-only — bağlı belge yok)* | 71 | K2 aynı |
| Bulk Import | 29 | K2 aynı |
| KYC Verification | 9 | K2 aynı |
| Brand | 4 | K2 aynı |
| Seller Application | 3 | K2 aynı |
| **Toplam (benim topladığım)** | **605** | — |

> `489 + 71 + 29 + 9 + 4 + 3 = 605`. Bu toplam **belgede yazmıyor**, ben
> topladım. K1 aynı düzlem için **192** diyor. Bkz. §3.1.

**Taksonomi notu (belgede karışık):** Bu listede üç farklı şey yan yana duruyor —
gerçek doctype'lar (KYB Verification, KYC Verification, Brand, Seller Application),
bir **durum** ("owner-only" = `attached_to_doctype` boş, doctype değil) ve bir
**kanal** ("Bulk Import" — `Bulk Import Job` mu `Bulk Import Job Error` mü belirsiz;
`media/usage.py:53-58`'de ikisi de ayrı kaynak olarak tanımlı). Sorgu yazarken bu
ayrım kritik: `group by attached_to_doctype` bu listeyi **birebir üretmez**.

### 2.4 Kayıt / adres şişmesi (dedup)

| Metrik | Değer | Kaynak |
|---|---:|---|
| Tekil `file_url` | 938 | K3 `media/inventory.py:10` |
| `tabFile` kaydı | 2.860 | K3 aynı |
| Şişme çarpanı (benim hesabım) | **3,05×** | `2.860 / 938` |
| En kötü tek adres | `/files/515804-5.jpg` → **39 kayıt** | K3 `media/inventory.py:10` |
| Aynı görselin iki mağazaya ait olması | **30 adres** | K5 `media/ownership.py:13` / K10 `media/metadata.py:8` |
| Dedup'lu toplam boyut | **1,06 GB** | K3 `media/inventory.py:12`, K10 `media/files.py:230` |
| Dedup'suz (yanlış) toplam | **1,49 GB** | aynı |
| Şişme (benim hesabım) | **1,41×** | `1,49 / 1,06` |

> Birim belirsizliği: hiçbir kaynakta GB'nin ondalık mı (10⁹) ikilik mi (2³⁰)
> olduğu yazmıyor. §3.4.

### 2.5 Sahiplik ve kullanım

| Metrik | Değer | Kaynak |
|---|---:|---|
| Ölçüm kümesi | 2.839 public dosya | K5 `media/ownership.py:4` |
| Yükleyen → mağaza çözülebiliyor | **2.839 / 2.839 (%100)** | K5 `media/ownership.py:6` |
| `attached_to` üzerinden çözülen | 1.162 ürün + 37 mağaza | K5 `media/ownership.py:7` |
| `attached_to` **boş** | **1.914** | K5 aynı |
| Görsel URL'i geçen alan sayısı (`information_schema` taraması) | **23 alan** | K10 `media/usage.py:8` |
| Bunlardan CANLI kaynak | 8 tablo/sütun | K10 `media/usage.py:32-42` (`LIVE_SOURCES`) |
| SİPARİŞ kaynağı | 2 | K10 `media/usage.py:46-49` (`ORDER_SOURCES`) |
| GEÇMİŞ kaynağı | 6 | K10 `media/usage.py:53-60` (`HISTORY_SOURCES`) |
| `tabListing.primary_image` referansı | **1.241** | K1 `MEDYA-DEPOLAMA-STANDARDI.md:152` |
| `tabListing Image.image` referansı | **1.137** | K1 `:153` |
| Retro-rename'in dokunacağı referans | **~2.400** | K1 `:152` / K9 `…design.md:114` |

### 2.6 Optimizasyon kapıları — kaç dosya gerçekten işleniyor

| Metrik | Değer | Kaynak |
|---|---:|---|
| Ölçüm kümesi | 4.007 dosya | K6 `media/gates.py:8` |
| Kapı 4'ü (`already_small`) geçen | **~300** | K6 aynı |
| Hiç dokunulmayan | **3.700** | K6 `media/gates.py:9` |
| İşlenme oranı (benim hesabım) | **~%7,5** | `300 / 4.007` |
| Kapı 1 alt sınırı | 200 KB | `media/presets.py:22` (`MIN_FILE_SIZE`) |
| Kapı 4 eşiği (balanced) | 2000 px en uzun kenar | `media/presets.py:15` |
| Kapı 6 kazanç eşiği | %10 | `media/presets.py:25` (`MIN_SAVING_RATIO`) |
| q75 yerine q88 seçimi | q75 yalnız **%3** ek kazanç, görünür bozulma | `media/presets.py:4-5` (kanıt `GORSEL-OPTIMIZASYON.md` §4.1-4.3 — **kayıp**) |

**TIFF ölçümü** (`media/engine.py:45-49`) — 8 gerçek dosya, toplam 101,7 MB:

| Yöntem | Sonuç | Kazanç |
|---|---:|---:|
| 2000px + LZW | 19,2 MB | %81 |
| **2000px + Deflate** ← seçilen | **13,3 MB** | **%87** |
| 2000px + JPEG-in-TIFF | 4,0 MB | %96 (kayıplı, reddedildi) |

### 2.7 Yedek düzlemi

| Metrik | Değer | Kaynak |
|---|---:|---|
| Ölçüm kümesi | 4.195 dosya | K7 `media/backup.py:7` |
| Toplam | **994 MB** | K7 `media/backup.py:9` |
| Günlük değişim | ~12 MB | K7 `media/backup.py:10` |
| Son 30 gün | 945 dosya / 372 MB | K7 aynı |
| Diskte boş alan | **382 GB** | K7 `media/backup.py:11` |
| Seçilen saklama | 14 gün ≈ 1 GB havuz + ~170 MB değişim | K7 `media/backup.py:361,382-383` |
| Ortalama dosya (benim hesabım) | **236,9 KB** | `994 MB / 4.195` |
| Kalıcı medya kaybı (bu oturumda) | 3 olay, **2'si kalıcı** | K7 `media/backup.py:5` |

### 2.8 Güvenlik-ilintili sayılar

Bunlar istatistik değil, **açık**. Rapor kapsamında ama ayrı işaretlenmeli.

| Bulgu | Adet | Kaynak |
|---|---:|---|
| `attached_to_doctype` BOŞ yüklenen `Seller Application.identity_document` | **144** | K8 `media/presets.py:59` ve `media/access_level.py:81` |
| Aynı durumdaki `Seller Certification.document` | **2** | K8 aynı |
| **Toplam korumasız PII belgesi** | **146** (TC kimlik taraması dahil) | K8 `media/presets.py:62` |
| Bir private/hassas belgeyle aynı `content_hash`'e sahip **public** dosya | **44** | K3 `media/inventory.py:71-75` |
| Bunlardan panelde **listelenen** | **6** (biri KYC kimlik belgesi) | K3 aynı |
| `LIKE` hatası yüzünden envanterden sessizce düşen dosya | **23** | K3 `media/inventory.py:24-26` |
| Panel sayacı ile filtre satırının ayrışması | 356 vs 333 (**23 fark**) | K10 `media/usage.py:414-415` |
| İstemci/sunucu ret sebebi ayrışması | 3.000 girdide **43** | K4 `media/upload_policy.py:414-415` |

---

## 3. TUTARSIZLIKLAR

Aşağıdakiler benim ölçümüm değil, **kaynaklar arası aritmetik çelişki**. Her
biri için hipotez veriyorum; hiçbirini doğrulayamadım.

### T-1 · Private dosya sayısı: 192 mi 605 mi? — **KRİTİK**

| Kaynak | Değer |
|---|---:|
| `MEDYA-DEPOLAMA-STANDARDI.md:32` | 192 |
| `MEDYA-ERISIM-MODELI.md:47-48` toplamı | 605 |

Oran: `605 / 192 = 3,15×`. İki belge **aynı gün** (2026-08-14) yazıldı ve
`MEDYA-ERISIM-MODELI.md:8` doğrudan diğerine atıf yapıyor — yani yazarlar
birbirinin farkındaydı, çelişki fark edilmemiş.

**Hipotez (doğrulanmadı):** 192 = **diskteki fiziksel dosya**, 605 = **`tabFile`
kaydı**. Dayanak: public tarafta aynı şişme belgeli — `2.860 kayıt / 938 adres =
3,05×` (`media/inventory.py:10`). `3,15` ile `3,05` aynı mertebede. Doğruysa
private tarafta da tekilleştirme yapılmalı ama **hiçbir private sorgusu
`group by file_url` kullanmıyor** — bkz. `media/files.py:238-243` yalnız
`is_private=0` sayıyor, private'ın dedup'lu sayacı **hiç yok**.

**Karşı-kanıt:** Hipotez doğruysa private'ta 605-192=413 fazla kayıt olmalı. Ama
`entitlement/checks.py:227-229` "private dosyalar kotadan muaf, çünkü
`media/files.py:storage_usage` yalnız `is_private=0` sayıyor" diyor — yani private
düzlemin ölçülmediği zaten kabul edilmiş. 605 bu durumda **nereden** ölçüldü,
belge söylemiyor.

**Sonuç: İKİSİ DE GÜVENİLMEZ.** Faz planlamasında private hacmi için hiçbir sayı
kullanılmamalı. §6 Sorgu 2 bunu çözer.

### T-2 · Public dosya sayısı: iki ayrı küme, on ayrı sayı — **KRİTİK**

Değerler iki kümede toplanıyor:

```
KÜME A (~2,8k):  938 (adres) · 2.826 · 2.839 · 2.858 · 2.860 (kayıt)
KÜME B (~4,0k+): 4.003 · 4.007 · 4.195 · 4.324 · 4.800 · 4.900
```

Fark: `4.003 − 2.858 = 1.145`.

**Hipotez A (kapsam farkı):** Küme A = `media/inventory.py:58-89`'daki
`_base_query()` süzgecinden geçmiş küme (`is_private=0` **VE** `EXCLUDED_DOCTYPES`
dışı **VE** hassas `content_hash` dışı). Küme B = süzgeçsiz `tabFile`.
`2.858 + 192 = 3.050` ≠ 4.003, yani basit public+private toplamı da **açığı
kapatmıyor** — 953 dosya hâlâ açıkta.

**Hipoteze karşı en güçlü kanıt:** `media/upload_policy.py:45` sayının yanına
açıkça "**public** dosya" yazıyor ve 4.003 diyor; `MEDYA-DEPOLAMA-STANDARDI.md:31`
de "**public**/files/" diyor ve 2.858. Aynı etiket, iki değer. Kapsam
hipotezinin kendisi de belgesiz.

**Hipotez B (zaman farkı) ÇÜRÜK:** 4.007 (08-06) → 4.195 (08-13) büyüme
gösteriyor (`+188 / 7 gün ≈ 27 dosya/gün`). Ama **4.003 (08-14)**, bir gün
öncesinin 4.195'inden **küçük**. Büyüyen bir sistemde bu mümkün değil; farkın
kaynağı zaman **değil**, kapsam ya da ölçüm hatası.

**Sonuç: Faz planlaması hiçbirine dayanamaz.** §6 Sorgu 1 on tanımı da aynı
anda çıkarır.

### T-3 · 938 adres mi 2.858 dosya mı? — **YÜKSEK**

`media/inventory.py:10` public tarafta **938 tekil adres** olduğunu söylüyor.
`MEDYA-DEPOLAMA-STANDARDI.md:31` aynı dizinde **2.858 dosya** olduğunu söylüyor.
Diskte bir dosya = bir adres olduğuna göre `2.858 − 938 = 1.920` dosyanın
**`File` kaydı yok**, ya da 938 sayısı bir alt kümenin sayısı.

Üç olası açıklama, hiçbiri doğrulanmadı:
1. 938 = `_base_query()` süzgecinden geçen adres; 2.858 = ham disk.
2. 2.858, türev dosyaları da sayıyor (`<hash>_thumb.webp` —
   `MEDYA-DEPOLAMA-STANDARDI.md:118-125`). Ama türev üretimi TUR-297/TUR-128'e
   **ertelenmiş** (`:133-134`), yani bugün türev **olmamalı**.
3. 2.858 dosyanın bir kısmı gerçekten yetim (silinen `File` kaydından kalan).

**Bu, veri kaybı riskidir:** Yetim dosya varsa yedek kapsamı dışında olabilir
(`media/backup.py` `File` kaydı üzerinden çalışıyor). §6 Sorgu 7.

### T-4 · Tahmin-edilebilir ad: 2.166 hangi kümenin %50'si? — **YÜKSEK**

`MEDYA-DEPOLAMA-STANDARDI.md:150` → **2.166** tahmin-edilebilir ad.
`…design.md:22` → public görsellerin "**~%50**"si tahmin edilebilir.

```
2.166 / 4.324 = %50,09   ← "~%50" ancak 4.324 tabanıyla tutar
2.166 / 2.858 = %75,79   ← 2.858 tabanıyla tutmuyor
2.166 /   938 = %230,9   ← imkânsız (adresten fazla ad olamaz)
```

Yani **"%50" iddiası 4.324'ü, "2.858 public dosya" iddiası başka bir kümeyi
ölçüyor** ve ikisi aynı belgede yan yana kullanılamaz. `2.166 / 938 > 1`
olduğu için T-3'teki 938 değeri bu tabloyla **kesinlikle uyumsuz**.

### T-5 · Toplam boyut: 1,06 GB mı 994 MB mı, ve hangi birimle? — **ORTA**

| Kaynak | Küme | Boyut |
|---|---:|---:|
| `media/inventory.py:12` + `media/files.py:230` | 938 adres | 1,06 GB |
| `media/backup.py:7,9` | 4.195 dosya | 994 MB |

`994 MB = 0,97 GiB` — yani 4,5 kat büyük bir kümede **daha az** bayt. Bu, ancak
1,06 GB'ın dedup'suz/farklı kapsamlı olmasıyla açıklanabilir; ama `files.py:230`
tam tersini söylüyor (1,06 = dedup'lu, 1,49 = dedup'suz).

Ortalama dosya boyutları da ayrışıyor:
```
994 MB / 4.195 dosya = 236,9 KB
1,06 GB /   938 adres = ~1,13 MB   (ondalık GB varsayımıyla)
```
**4,8 kat fark.** Aynı diskteki aynı dosyalar için mümkün değil.

**Birim belirsizliği ayrıca var:** Hiçbir kaynakta GB'ın 10⁹ mu 2³⁰ mu olduğu
yazmıyor. `media/upload_policy.py:348` `bayt/1024/1024` kullanıyor (ikilik),
`media/backup.py:9` yorumunda tanım yok. Kota hesabı (`quota.max_storage_mb`,
`entitlement/checks.py:255`) MB cinsinden — hangi MB olduğu satıcıya gösterilen
sayının doğruluğunu doğrudan etkiler.

### T-6 · Retro-rename referans sayısı iç tutarsız — **DÜŞÜK**

`MEDYA-DEPOLAMA-STANDARDI.md:152-153`: "~2.400 referans (`tabListing.primary_image`
1241, `tabListing Image.image` 1137, **+ uzun kuyruk**)".

```
1.241 + 1.137 = 2.378
~2.400 − 2.378 = 22   ← "uzun kuyruk" için kalan pay
```

Ama `media/usage.py:32-60` **16 tablo/sütun** çifti tanımlıyor (8 canlı + 2
sipariş + 6 geçmiş) ve `media/usage.py:8` toplam **23 alan** bulunduğunu
söylüyor. 14–21 ek alanın toplam **22 referans** taşıması mümkün ama şüpheli;
`tabVersion` ve `tabDeleted Document` gibi geçmiş tabloları tipik olarak
binlerce satır taşır. Ya "~2.400" yalnız CANLI kaynakları sayıyor (o zaman
migration geçmişi kıracak), ya da tahmin düşük.

### T-7 · Private "Seller Application 3" ile public'teki 144 çelişiyor — **KRİTİK (güvenlik)**

`MEDYA-ERISIM-MODELI.md:47` private tarafta `Seller Application` için **3** dosya
sayıyor. `media/presets.py:59` ve `media/access_level.py:81` ise
`Seller Application.identity_document` alanında **144 dosya** olduğunu ve
bunların `attached_to_doctype`'ının **BOŞ** olduğunu söylüyor.

Boş `attached_to_doctype`, `MEDYA-ERISIM-MODELI.md`'deki dağılımda "owner-only"
(71) kovasına düşer — ama 144 > 71. Yani **144 kimlik belgesi private
dağılımının hiçbir satırında görünmüyor.** En olası açıklama: bunlar
`is_private=0`, yani **public tarafta**.

**Sonuç:** `MEDYA-DEPOLAMA-STANDARDI.md:31`'in "2.858 dosya (ürün görselleri,
public medya)" etiketi yanlış olabilir — o kümede TC kimlik taraması bulunuyor
olabilir. §6 Sorgu 6 bunu doğrudan cevaplar ve **en yüksek öncelikli sorgudur**.

### T-8 · "Kullanılmayan dosya" sayacı ile filtresi ayrışıyor — **ORTA (bilinen)**

`media/usage.py:414-415` bu ayrışmayı zaten belgeliyor: sayaç **356**,
filtre **333** satır getiriyor, fark hassas doctype'lara bağlı eklerden.
Yorumda çözüm de yazılı (kapsam listesi aynı olmalı) ve kod düzeltilmiş
görünüyor — ama **rakamlar güncellenmemiş**. Bugünkü ayrışmanın 0 olup
olmadığı bilinmiyor.

### T-9 · Ölçümlerin asıl kanıt belgesi kayıp — **YÜKSEK (yönetişim)**

`GORSEL-OPTIMIZASYON.md` **8 dosyadan** referans veriliyor (§1 sonundaki liste)
ama çalışma alanında yok. Preset seçimi (2000px/q88), Kapı 4 eşiği, %3 kalite
ölçümü, arşiv retention (30 gün), satıcı self-service kapsam kararı — hepsinin
gerekçesi orada. Kod yalnız **sonucu** taşıyor, **veriyi** değil.

Bu, T-1…T-8'i çözmeyi de zorlaştırıyor: bir sayı yanlış çıkarsa hangi ölçüm
koşulunda üretildiğini bilmenin yolu yok.

### Tutarsızlık özeti

| # | Konu | Şiddet | Çözen sorgu |
|---|---|---|---|
| T-7 | 144 PII belgesi public'te olabilir | **KRİTİK (güvenlik)** | §6 Sorgu 6 |
| T-1 | Private: 192 vs 605 | **KRİTİK** | §6 Sorgu 2 |
| T-2 | Public: ~2,8k vs ~4,0k | **KRİTİK** | §6 Sorgu 1 |
| T-3 | 938 adres vs 2.858 dosya | YÜKSEK | §6 Sorgu 7 |
| T-4 | 2.166'nın tabanı belirsiz | YÜKSEK | §6 Sorgu 1 (F satırı) |
| T-9 | Kanıt belgesi kayıp | YÜKSEK | — (arşiv/git arama) |
| T-5 | 1,06 GB vs 994 MB + birim | ORTA | §6 Sorgu 1 (G satırı) |
| T-8 | 356 vs 333 | ORTA | §6 Sorgu 8 |
| T-6 | ~2.400 referans iç tutarsız | DÜŞÜK | §6 Sorgu 9 |

---

## 4. `media/inventory.py` hangi metrikleri üretebiliyor

Modülü baştan sona okudum (452 satır). Aşağıdaki tablo, **yeni kod yazmadan**
bugün üretilebilen metrikleri listeler — bunlar için ayrı sorgu yazmaya gerek yok.

### 4.1 Üretebildikleri

| Metrik | Fonksiyon | Satır | Not |
|---|---|---|---|
| Tekil dosya adedi | `summary()["count"]` | 367-408 | `file_url` bazında `group by` |
| Toplam bayt (dedup'lu) | `summary()["total_bytes"]` | 380-388 | `Sum(Max(file_size))` |
| Optimize edilmiş adet | `summary()["optimized_count"]` | 391-397 | `th_optimized_at` dolu |
| Kazanılan bayt | `summary()["saved_bytes"]` | 399-401 | `original − current`, negatife kapalı |
| Sayfalı liste + toplam | `list_files()` | 184-280 | max 200/sayfa (`MAX_PAGE_SIZE:49`) |
| Filtreli sayım | `_count()` | 348-364 | `group by` sonucu sarmalanıp sayılıyor |
| Durum kırılımı (optimized/pending/trashed) | `_apply_filters` | 121-134 | `th_media_state` + damga yedeği |
| "Optimize edilebilir" alt kümesi | `only_optimizable` | 136-145 | motor uzantıları + ≥200 KB |
| Kullanım tipi (single/multi_use/repeat) | `_usage_kind` | 339-345 | `record_count` vs `usage_count` |
| Kullanım kararı | `_decorate` → `usage.verdict_map_all` | 298-312 | önbellekli |
| Mağaza kapsamı | `ownership.scope` | 208-209 | süzgeç sorgunun **başına** giriyor |
| Boyut/ad/tarih/kazanç/durum sıralaması | `_order_term` | 324-336 | `usage` hariç |

### 4.2 ÜRETEMEDİKLERİ — bu raporun boşlukları

| İstenen metrik | Neden üretilemiyor | Kanıt |
|---|---|---|
| **p50 / p90 / p99 boyut** | Hiçbir persentil/histogram sorgusu yok; yalnız `Sum`, `Count`, `Min`, `Max` import edilmiş | `media/inventory.py:22` |
| **>20 MP dosya** | Çözünürlük `tabFile`'da var (`th_media_width/height`) ama **tembel** doldurulur — yalnız `ensure_dimensions()` çağrılınca | `media/metadata.py:159-196` |
| **CMYK / renk uzayı** | `engine.Probe` dataclass'ında `mode` alanı **YOK** | `media/engine.py:53-66` |
| **0 bayt dosya** | `file_size` süzgeci var ama **alt** sınır olarak (`>=`), 0 için özel sorgu yok | `media/inventory.py:147-148` |
| **Uzantı-MIME uyuşmazlığı** | Mantık var ama yalnız **yükleme anında**, envanterde geriye dönük tarama yok | `media/upload_policy.py:365-369` |
| **Private envanteri** | Modül docstring'i açıkça kapsam dışı bırakıyor; `_base_query` `is_private=0` sabit | `media/inventory.py:14-15`, `:84` |
| **Diskte olmayan dosya** | `runner` koşu sırasında `file_missing` üretiyor ama envanter sorgusu diske bakmıyor | `media/gates.py:36-38` |
| **Diskteki yetim dosya** | Sorgu `tabFile`'dan başlıyor; kayıtsız dosya hiç görünmüyor | `media/inventory.py:1-5` |

> **Kritik tasarım notu:** Çözünürlük alanı dolu olan satır oranı **bilinmiyor**.
> `where th_media_width * th_media_height > 20000000` sorgusu **alt sınır** verir,
> gerçek sayıyı değil. `scripts/media_stats.py:dimension_coverage()` önce kapsamı
> ölçer; kapsam düşükse (beklenen) MP ölçümü **zorunlu olarak diske iner**.

---

## 5. `media/upload_policy.py` — mevcut boyut tavanları

Değerler doğrudan koddan; **hiçbiri benim önerim değil**.

### 5.1 Politika tavanları

| Tür | Uzantılar | Tavan | Satır |
|---|---|---:|---|
| `image` | `.jpg .jpeg .png .webp .gif .bmp .tif .tiff .avif .heic` | **25 MB** | `:59-61`, `:68` |
| `video` | `.mp4 .webm .mov .m4v` | **200 MB** | `:62`, `:69` |
| `document` | `.pdf .doc .docx .xls .xlsx` | **50 MB** | `:63`, `:70` |
| `other` | `.txt .csv .zip` | **50 MB** | `:64`, `:71` |
| *bilinmeyen* | — | **50 MB** | `:76` (`MAX_BYTES_UNKNOWN`) |

### 5.2 GERÇEKTEN uygulanan tavan

`effective_max()` = `min(politika, platform)` — `media/upload_policy.py:262-265`.

| Sabit | Değer | Satır |
|---|---:|---|
| Frappe platform tavanı (fallback) | 25 MB | `:259` |
| Tek istekte gövde sınırı | **8 MB** (base64 %33 şişme payı) | `:89` |
| Parça boyutu | 2 MB | `media/chunked.py:15` |
| En çok parça | 256 | `media/chunked.py:19` |
| Yarım oturum TTL | 6 saat | `media/chunked.py:23` |
| Dosya adı sınırı | 140 karakter | `:84` |

> **Ölçümle kayıtlı çelişki** (`media/upload_policy.py:243-252`): Video için
> ilan edilen 200 MB **gerçekleşemez** — Frappe `File` kaydı açılırken 25 MB'da
> reddediyor ("File size exceeded the maximum allowed size of 25.0 MB",
> 26 MB'lık dosyayla doğrulanmış). `platform_limit()` bu yüzden var. Gerçek
> 200 MB isteniyorsa site ayarındaki `max_file_size` yükseltilmeli
> (`MEDYA-YUKLEME-SOZLESMESI.md:140`).

### 5.3 Anomali eşiklerinin politikayla ilişkisi

| Anomali eşiği | Politikaya göre durumu |
|---|---|
| **> 20 MB** | Bugün **geçerli** — tavan 25 MB. `media/upload_policy.py:45-46` "en büyük 21 MB'lık bir TIFF" diyor → **en az 1 dosyanın bu eşiği aşması bekleniyor** |
| **> 20 MP** | Bugün **denetlenmiyor** — hiçbir yerde piksel sınırı yok. Kıyas: balanced preset `max_dim=2000` → optimize edilmiş görsel en fazla 4 MP. 20 MP'lik bir dosya Kapı 4'ü geçmiş ama henüz işlenmemiş demek |
| **CMYK** | Bugün **kısmen düzeltiliyor**: `engine.py:121` JPEG'i `convert("RGB")` ile RGB'ye çeviriyor — **ama yalnız tüm kapıları geçen dosyada**. `engine.py:127-131` TIFF'i **bilerek çevirmiyor** (alpha/renk yönetimi korunsun diye). Kapı 4'e takılan CMYK dosya tarayıcıya **CMYK olarak gider** |
| **0 bayt** | `CONTENT_EMPTY` ile **reddediliyor** (`:355`) — ama yalnız `content` verildiğinde (`:353`). Diskten geri yükleme yolunda içerik yok, boyut da 0 ise geçer |
| **Uzantı-MIME uyuşmazlığı** | **Bilinçli olarak reddedilmiyor** (`:24-28`): zararsız uyuşmazlık uyarıya yazılıyor (`:365-369`), yalnız **tehlikeli** olan (`<svg`, `<script`, `<html`…) reddediliyor (`:187-195`, `:357-363`). Ölçüm: "mevcut 1500 dosyada 0 uyuşmazlık" (`:25-26`) |

---

## 6. ÜRETİMDE ÇALIŞTIRILACAK SORGULAR

Hepsi **salt okunur**. Çalıştırılabilir hâli: **`scripts/media_stats.py`**
(yazıldı, **çalıştırılmadı**).

### 6.0 Scripti çalıştırma

```bash
# LOCAL DEV (docker açıkken)
docker cp scripts/media_stats.py istocc-dev-backend-1:/tmp/media_stats.py
docker exec -i istocc-dev-backend-1 bench --site tradehub.localhost console <<'EOF'
exec(open('/tmp/media_stats.py').read())
main()
EOF

# PROD (bench kurulu makine)
bench --site <site> console <<'EOF'
exec(open('/path/to/media_stats.py').read())
main()
EOF

# Kademeli — disk probe pahalıysa (3k dosyada dakikalar sürer)
main(probe_disk=False)          # yalnız SQL
main(sql=False, probe_limit=500) # yalnız en büyük 500 dosya

# JSON çıktısı
MEDIA_STATS_OUT=/tmp/media_stats.json
```

> **`LIKE` KULLANMAYIN.** `media/inventory.py:24-26`: MariaDB
> `utf8mb4_unicode_ci`'de `file_url like '/files/%'` 4 baytlık karakter (emoji,
> matematiksel alfabe) içeren satırlarda **eşleşmiyor** — ölçüldü, **23 dosyayı
> sessizce düşürüyordu**. Aşağıdaki sorguların hepsi `LEFT()` kullanır.

### Sorgu 1 — Mutabakat: on farklı sayı hangi tanıma karşılık geliyor (T-2, T-3, T-4, T-5)

```sql
-- A) Ham satır sayıları (hiç filtre yok)
select 'rows_all'         k, count(*) v from tabFile
union all select 'rows_not_folder', count(*) from tabFile where is_folder=0
union all select 'rows_public',     count(*) from tabFile where is_folder=0 and is_private=0
union all select 'rows_private',    count(*) from tabFile where is_folder=0 and is_private=1

-- B) TEKİL adres (dedup) — inventory.py:10'daki 938'in bugünkü karşılığı
union all select 'urls_public', count(*) from (
  select file_url from tabFile
  where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
  group by file_url) a
union all select 'urls_private', count(*) from (
  select file_url from tabFile
  where is_folder=0 and is_private=1 and left(file_url,15)='/private/files/'
  group by file_url) b

-- E) Shard geçişi: kaç adres hâlâ DÜZ (/files/<ad>), kaç tanesi /files/<ab>/<ad>
union all select 'urls_public_flat', count(*) from (
  select file_url from tabFile
  where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
    and file_url not regexp '^/files/[0-9a-f]{2}/'
  group by file_url) c

-- F) T-4: tahmin-edilebilir ad = gövdesi 32 hex OLMAYAN (hash ismi 32 hex,
--    MEDYA-DEPOLAMA-STANDARDI.md:77-80). "2.166"nın tabanı buradan çıkar.
union all select 'urls_public_non_hashed', count(*) from (
  select file_url from tabFile
  where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
    and substring_index(substring_index(file_url,'/',-1),'.',1)
        not regexp '^[0-9a-f]{32}$'
  group by file_url) d

-- G) T-5: dedup'lu vs ham toplam bayt. files.py:238-243 ile aynı desen.
union all select 'bytes_public_dedup', (
  select coalesce(sum(boyut),0) from (
    select max(file_size) boyut from tabFile
    where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
    group by file_url) e)
union all select 'bytes_public_raw', (
  select coalesce(sum(file_size),0) from tabFile
  where is_folder=0 and is_private=0 and left(file_url,7)='/files/');
```

**C) Panelin GERÇEKTEN gördüğü küme** — `media/inventory.py:58-89` `_base_query()`
ile birebir aynı üç filtre. `EXCLUDED_DOCTYPES` listesi **elle yazılmamalı**;
`scripts/media_stats.py:_excluded_placeholders()` onu `media/presets.py:44-53`'ten
alır. Bench console'da:

```python
from tradehub_core.media import inventory
print(inventory.summary())   # count / total_bytes / optimized_count / saved_bytes
print(inventory._count(search="", state=""))
```

**D) DİSKTEKİ fiziksel dosya** — `MEDYA-DEPOLAMA-STANDARDI.md:31-32`'nin
(2.858/192) kaynağı büyük olasılıkla budur:

```bash
docker exec istocc-dev-backend-1 sh -c '
  S=$(ls -d /home/frappe/frappe-bench/sites/tradehub.localhost)
  echo -n "public/files : "; find $S/public/files  -type f | wc -l
  echo -n "private/files: "; find $S/private/files -type f | wc -l
  echo -n "image_originals: "; find $S/private/image_originals -type f 2>/dev/null | wc -l
  echo -n "media_trash    : "; find $S/private/media_trash     -type f 2>/dev/null | wc -l
  echo -n "media-backups  : "; find $S/private/media-backups   -type f 2>/dev/null | wc -l
  echo -n "public bayt  : "; du -sb $S/public/files
  echo -n "private bayt : "; du -sb $S/private/files
'
```

> Üç medya-özel kök (`image_originals`, `media_trash`, `media-backups` —
> `MEDYA-DEPOLAMA-STANDARDI.md:57-66`) **bilerek `File` kaydı üretmez**, kotaya
> girmez. Disk toplamı alırken ayrı sayılmalı, yoksa "public medya" rakamı
> arşiv ve çöple şişer.

### Sorgu 2 — Private dağılımı: 192 mi 605 mi (T-1)

```sql
select
  coalesce(nullif(attached_to_doctype,''),'__owner_only__') doctype,
  count(*)                    kayit_sayisi,
  count(distinct file_url)    adres_sayisi,
  coalesce(sum(file_size),0)  ham_bayt
from tabFile
where is_folder=0 and is_private=1
group by doctype
order by kayit_sayisi desc;

-- Toplam iki türlü
select count(*) kayit, count(distinct file_url) adres
from tabFile where is_folder=0 and is_private=1;
```

**Yorumlama:** `kayit` toplamı ~605'e, `adres` toplamı ~192'ye yakın çıkarsa
T-1'in hipotezi (kayıt vs disk) **doğrulanır**. İkisi de tutmazsa iki belge de
başka bir şeyi ölçmüş demektir ve **her ikisi de rapordan çıkarılmalıdır**.

`MEDYA-ERISIM-MODELI.md:47`'deki "Bulk Import"un hangi doctype olduğu bu
sorgunun çıktısından okunur (`Bulk Import Job` mu `Bulk Import Job Error` mü).

### Sorgu 3 — Boyut dağılımı p50 / p90 / p99

**Yöntem uyarısı:** `PERCENTILE_CONT` MariaDB 10.3.3+ window fonksiyonudur;
üretimdeki sürüm doğrulanmadı. Sürüm farkında sorgu **sessizce sözdizimi hatası**
verir. Bu yüzden **birincil yöntem Python tarafı** (`scripts/media_stats.py:
_percentile()`, doğrusal enterpolasyon, NumPy `linear` ile aynı):

```python
from tradehub_core.media import inventory  # noqa: kapsam referansı
exec(open('/tmp/media_stats.py').read())
print(size_distribution())
# üç kapsam ayrı ayrı döner: "inventory" (panelin gördüğü), "public", "private"
```

Saf SQL isteniyorsa (sürüm doğrulandıktan sonra):

```sql
select
  count(*)                                                        n,
  min(boyut)                                                      min_b,
  max(boyut)                                                      max_b,
  round(sum(boyut)/1024/1024,2)                                   toplam_mb,
  percentile_cont(0.50) within group (order by boyut) over ()     p50,
  percentile_cont(0.90) within group (order by boyut) over ()     p90,
  percentile_cont(0.99) within group (order by boyut) over ()     p99
from (
  select max(file_size) boyut from tabFile
  where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
  group by file_url
) x limit 1;
```

Sürüm bilinmiyorsa **taşınabilir** persentil (window fonksiyonu gerekmez):

```sql
set @n := (select count(*) from (
  select file_url from tabFile
  where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
  group by file_url) t);
-- p90 örneği; p50 için 0.50, p99 için 0.99
select max(file_size) boyut from tabFile
where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
group by file_url order by boyut
limit 1 offset (select floor(@n*0.90));
```

**Politika kıyas sayaçları** — `media/upload_policy.py:68` (25 MB) ve
`media/presets.py:22` (200 KB, Kapı 1) ile:

```sql
select
  sum(boyut = 0)                       sifir_bayt,
  sum(boyut < 200*1024)                kapi1_alti_200kb,
  sum(boyut > 20*1024*1024)            ustu_20mb,
  sum(boyut > 25*1024*1024)            ustu_25mb_POLITIKA_IHLALI
from (
  select max(file_size) boyut from tabFile
  where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
  group by file_url) x;
```

> `ustu_25mb_POLITIKA_IHLALI > 0` çıkarsa: bu dosyalar **bugünkü kuraldan önce**
> yüklenmiş demektir (`media/upload_policy.py:243-252`, Frappe 25 MB'da
> reddediyor). Her biri elle incelenmeli.

### Sorgu 4 — Çözünürlük kapsamı: MP'yi SQL'de ölçmek MÜMKÜN MÜ

**Bu sorgu diğerlerinden önce çalıştırılmalı** — sonucu MP ölçüm yöntemini belirler.

```sql
select
  count(distinct file_url)                                                  adres,
  count(distinct case when ifnull(th_media_width,0)>0 then file_url end)    olculmus,
  round(100.0*count(distinct case when ifnull(th_media_width,0)>0 then file_url end)
        / nullif(count(distinct file_url),0), 1)                            kapsam_yuzde
from tabFile
where is_folder=0 and is_private=0 and left(file_url,7)='/files/';
```

- **Kapsam ≈ %100** ise MP doğrudan SQL'de ölçülebilir:
  ```sql
  select count(distinct file_url) from tabFile
  where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
    and ifnull(th_media_width,0)*ifnull(th_media_height,0) > 20000000;
  ```
- **Kapsam düşük** (beklenen — `media/metadata.py:159-196` alanı yalnız
  `ensure_dimensions()` çağrılınca doldurur) ise yukarıdaki sayı **ALT SINIRDIR,
  gerçek sayı değildir**. Sorgu 5 zorunlu hâle gelir.

### Sorgu 5 — Disk probe: >20 MP, CMYK, 0 bayt, uzantı-içerik uyuşmazlığı

SQL'de üretilemez. `scripts/media_stats.py:probe_images()`:

```python
exec(open('/tmp/media_stats.py').read())
r = probe_images()          # tümü
r = probe_images(limit=500) # yalnız en büyük 500
print(r["anomaly_counts"])
print(r["megapixels"])      # p50/p90/p99/max, megapiksel cinsinden
print(r["modes"])           # {'RGB': n, 'CMYK': n, 'P': n, ...}
```

Ölçtükleri ve **hangi mevcut kodu yeniden kullandığı**:

| Anomali | Yöntem | Yeniden kullanılan kod |
|---|---|---|
| `over_megapixels` | PIL `im.size` (tembel — piksel decode edilmez) | — (`engine.Probe` MP taşımıyor) |
| `cmyk` | PIL `im.mode ∈ {CMYK, YCbCr, LAB}` | — (`engine.py:53-66` `mode` alanı yok) |
| `zero_byte_disk` | `os.path.getsize() == 0` | — |
| `missing_on_disk` | `os.path.isfile()` False | `gates.py:36-38` `file_missing` sebebiyle aynı |
| `over_bytes` | diskteki gerçek boyut > 20 MB | `upload_policy.py:68` eşiğiyle kıyas |
| `ext_content_mismatch` | **`upload_policy.sniff()` + `_uyumlu()`** | `upload_policy.py:198-211`, `:374-395` — **yeniden yazılmadı** |
| `dangerous_content` | **`upload_policy.is_dangerous()`** | `upload_policy.py:214-224` — **yeniden yazılmadı** |
| `db_disk_size_mismatch` | `tabFile.file_size` ≠ `os.path.getsize()` | — |

> **`db_disk_size_mismatch` neden önemli:** Kota (`media/files.py:238-243`) ve
> depolama raporu **DB'deki `file_size`'a** güveniyor. Diskteki gerçek boyutla
> ayrışırsa satıcıya gösterilen kota yanlıştır.

Yalnız 0 bayt / eksik boyut için hızlı SQL ön kontrolü:

```sql
select 'db_sifir' k, count(*) v from tabFile
  where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
    and ifnull(file_size,0)=0
union all
select 'db_null', count(*) from tabFile
  where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
    and file_size is null;
```

### Sorgu 6 — PII maruziyeti (T-7) — **EN YÜKSEK ÖNCELİK**

Kodda ölçülmüş 146 belge (`media/presets.py:59-62`) bugün hâlâ public mi:

```sql
-- Seller Application.identity_document — presets.py:59'da 144 ölçülmüş
select count(*) from `tabSeller Application` d
join tabFile f on f.file_url = d.identity_document
where ifnull(d.identity_document,'')<>''
  and f.is_private = 0
  and ifnull(f.attached_to_doctype,'') = '';

-- Seller Certification.document — presets.py:59-60'ta 2 ölçülmüş
select count(*) from `tabSeller Certification` d
join tabFile f on f.file_url = d.document
where ifnull(d.document,'')<>''
  and f.is_private = 0
  and ifnull(f.attached_to_doctype,'') = '';
```

Tüm `EXCLUDED_MEDIA_FIELDS` haritası (`media/presets.py:70-76`) üzerinde
tek geçişte:

```python
exec(open('/tmp/media_stats.py').read())
print(pii_exposure())
```

`content_hash` sızıntısı (`media/inventory.py:68-79` — 44 dosya, 6'sı panelde):

```sql
select count(distinct f.file_url)
from tabFile f
where f.is_folder=0 and f.is_private=0 and ifnull(f.content_hash,'')<>''
  and f.content_hash in (
    select content_hash from tabFile
    where ifnull(content_hash,'')<>''
      and (is_private=1 or attached_to_doctype in (
        'KYB Verification','KYC Verification','Seller Certification',
        'Seller Verification','Seller Application','Order',
        'Payment Transaction','Data Export Request')));
```

> Listeyi elle yazmak yerine `media/presets.py:44-53`'ten okuyun —
> `scripts/media_stats.py:_excluded_placeholders()` bunu yapar. Elle kopya,
> yeni bir hassas doctype eklendiğinde sessizce eskir.

### Sorgu 7 — Yetim dosya / kayıp dosya (T-3)

```python
exec(open('/tmp/media_stats.py').read())
print(orphan_files())
# disk_count, db_url_count, orphan_count (diskte var DB'de yok),
# orphan_looks_like_derivative, db_url_without_disk_file (DB'de var diskte yok)
```

Kabuk karşılığı (çapraz doğrulama için):

```bash
docker exec istocc-dev-backend-1 sh -c '
  S=/home/frappe/frappe-bench/sites/tradehub.localhost
  find $S/public/files -type f -printf "/files/%P\n" | sort -u > /tmp/disk.txt
  wc -l /tmp/disk.txt
'
docker exec istocc-dev-backend-1 bench --site tradehub.localhost console <<'EOF'
import frappe
u = {r[0] for r in frappe.db.sql("""select distinct file_url from tabFile
  where is_folder=0 and is_private=0 and left(file_url,7)='/files/'""")}
open('/tmp/db.txt','w').write("\n".join(sorted(u)))
print(len(u))
EOF
docker exec istocc-dev-backend-1 sh -c 'comm -23 /tmp/disk.txt <(sort /tmp/db.txt) | wc -l'
```

> **Yetim dosya = yedeksiz dosya.** `media/backup.py` `File` kaydı üzerinden
> çalışıyor (`media/backup.py:22-27`). Kayıtsız bir dosya yedeğe **girmez** ve
> `media/backup.py:5`'te belgelenen "3 kayıp olayı, 2'si kalıcı" tam olarak
> bu sınıftan olabilir.

### Sorgu 8 — Kullanım kararı ayrışması (T-8)

```python
from tradehub_core.media import usage
sayac = usage.verdict_map_all(deep=True, refresh=True)
from collections import Counter
print(Counter(sayac.values()))     # {"unused": n, ...} — "356" buradaydı

from tradehub_core.media import inventory
print(inventory._count(search="", state="", usage_state="unused"))  # "333" buradaydı
# İki sayı EŞİT olmalı. Değilse media/usage.py:411-413'teki kapsam hatası sürüyor.
```

### Sorgu 9 — Referans yükü (T-6)

```python
from tradehub_core.media import usage
for etiket, kaynak in (("LIVE", usage.LIVE_SOURCES),
                       ("ORDER", usage.ORDER_SOURCES),
                       ("HISTORY", usage.HISTORY_SOURCES)):
    for tablo, kolon, _tur, _ad in kaynak:
        try:
            n = frappe.db.sql(f"select count(*) from `{tablo}` "
                              f"where ifnull(`{kolon}`,'')<>''")[0][0]
        except Exception as e:
            n = f"HATA {type(e).__name__}"
        print(f"{etiket:8} {tablo}.{kolon:22} {n}")
```

`tabListing.primary_image` 1.241 ve `tabListing Image.image` 1.137 doğrulanır;
"uzun kuyruk"un gerçekten ~22 mi yoksa binlerce mi olduğu görülür.

### Sorgu 10 — Uzantı karması ve motor kapsamı

```python
exec(open('/tmp/media_stats.py').read())
print(extension_mix())
# her uzantı için adet + MB + engine_supported (engine.supported_extensions()'tan)
```

```sql
select lower(substring_index(file_url,'.',-1)) uzanti,
       count(*) adet, round(sum(boyut)/1024/1024,1) mb
from (select file_url, max(file_size) boyut from tabFile
      where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
      group by file_url) x
group by uzanti order by adet desc;
```

> `engine_supported=false` olan bir uzantıda büyük hacim varsa optimizasyon
> tavanı oradadır — `media/engine.py:21` `SUPPORTED_FORMATS` yalnız
> JPEG/PNG/WEBP/TIFF. `.avif` ve `.heic` yükleme politikasında **kabul ediliyor**
> (`upload_policy.py:60`) ama motor **işleyemiyor** — sessiz boşluk.

---

## 7. ÜRETİMDE DOĞRULANMALI

Aşağıdaki maddelerin **hiçbiri bu oturumda ölçülmedi**. Docker kapalı, üretim
veritabanına ve canlı siteye erişim yok. Her satır, çalıştırılacak tam komutu
içerir.

| # | Doğrulanacak | Komut | Neden gerekli |
|---|---|---|---|
| D-1 | 144 `Seller Application.identity_document` bugün hâlâ public mi | §6 Sorgu 6 (ilk SQL) | **KVKK.** TC kimlik taraması public URL'den erişilebilir olabilir (T-7) |
| D-2 | 44 public dosyanın hassas `content_hash` paylaşımı sürüyor mu | §6 Sorgu 6 (son SQL) | 6'sı panelde listeleniyordu, biri KYC kimlik belgesi |
| D-3 | Private: 192 mi 605 mi | §6 Sorgu 2 | T-1 — private hacmi için kullanılabilir tek sayı yok |
| D-4 | Public: 2.858 mi 4.003 mü, aradaki 1.145 nedir | §6 Sorgu 1 (A+B+C) + D (disk) | T-2 — kapasite planlaması buna dayanacak |
| D-5 | 938 adres ile 2.858 dosya arasındaki 1.920 fark | §6 Sorgu 7 | T-3 — yetimse **yedeksiz** demektir |
| D-6 | `th_media_width` kapsam yüzdesi | §6 Sorgu 4 | MP ölçüm yöntemini belirler; düşükse disk probe zorunlu |
| D-7 | p50 / p90 / p99 boyut (üç kapsam ayrı) | §6 Sorgu 3 | **Hiç ölçülmemiş.** Bugün elde tek bir persentil bile yok |
| D-8 | >20 MP dosya sayısı ve MP p99'u | §6 Sorgu 5 (`probe_images`) | Bugün **hiçbir piksel sınırı yok** — decode bombası riski |
| D-9 | CMYK / YCbCr / LAB dosya sayısı | §6 Sorgu 5 (`modes`) | `engine.py:127-131` TIFF'i bilerek çevirmiyor; Kapı 4'e takılan CMYK tarayıcıya öyle gidiyor |
| D-10 | 0 bayt dosya (DB'de ve diskte ayrı) | §6 Sorgu 5 + hızlı SQL | Kota ve yedek bütünlüğü |
| D-11 | Uzantı-MIME uyuşmazlığı bugün gerçekten 0 mı | §6 Sorgu 5 (`ext_content_mismatch`) | `upload_policy.py:25-26` "1500 dosyada 0" diyor; küme 1.500'den büyük |
| D-12 | DB `file_size` ↔ disk boyut sapması | §6 Sorgu 5 (`db_disk_size_mismatch`) | Sapma varsa satıcıya gösterilen kota **yanlış** |
| D-13 | Diskteki `public/files` ve `private/files` gerçek bayt toplamı | §6 Sorgu 1 (D, `du -sb`) | T-5 — 1,06 GB / 994 MB çelişkisi |
| D-14 | `image_originals` + `media_trash` + `media-backups` disk yükü | §6 Sorgu 1 (D) | Bu üç kök **kotaya girmiyor** (`MEDYA-DEPOLAMA-STANDARDI.md:64-66`); 382 GB boş alan iddiası bunları içeriyor mu bilinmiyor |
| D-15 | Shard geçişi: kaç adres hâlâ düz `/files/<ad>` | §6 Sorgu 1 (E) | Hash+shard yalnız yeni yüklemelere uygulanıyor (`MEDYA-DEPOLAMA-STANDARDI.md:140`) — ilerleme hiç ölçülmemiş |
| D-16 | 2.166'nın gerçek tabanı (%50 mi %76 mı) | §6 Sorgu 1 (F) | T-4 — retro-rename iş büyüklüğü buna bağlı |
| D-17 | `usage` sayacı ile filtresi hâlâ ayrışıyor mu (356 vs 333) | §6 Sorgu 8 | T-8 |
| D-18 | 16 kaynak tablodaki gerçek referans sayısı | §6 Sorgu 9 | T-6 — "~2.400" tahmini doğru mu |
| D-19 | `.avif` / `.heic` hacmi (motor işleyemiyor) | §6 Sorgu 10 | Politika kabul ediyor, motor desteklemiyor — sessiz boşluk |
| D-20 | Frappe `max_file_size` üretimdeki gerçek değeri | `bench --site <site> console` → `from frappe.core.api.file import get_max_file_size; print(get_max_file_size())` | 200 MB video tavanı gerçekleşemiyor (`upload_policy.py:243-252`) |
| D-21 | MariaDB sürümü (`PERCENTILE_CONT` var mı) | `docker exec istocc-dev-db-1 mysql -e "select version()"` | §6 Sorgu 3'ün hangi varyantının çalışacağı |
| D-22 | `GORSEL-OPTIMIZASYON.md` nerede | `git log --all --diff-filter=D --name-only \| grep -i gorsel` | T-9 — 8 dosyanın atıf yaptığı kanıt belgesi kayıp |

### Doğrulama sırası

```
1. D-1, D-2      → güvenlik. Diğer her şeyden önce. (§6 Sorgu 6)
2. D-21          → sorgu varyantı seçimi (§6 Sorgu 3 hangi yolu izleyecek)
3. D-3, D-4, D-5 → mutabakat. Bunlar çözülmeden hiçbir kapasite sayısı geçerli değil.
4. D-6           → MP yöntemini belirler
5. D-7 … D-12    → asıl istatistik (p50/p90/p99 + anomaliler)
6. D-13 … D-19   → depolama ve borç ölçümleri
7. D-20, D-22    → yönetişim
```

---

## 8. Üretilen dosyalar

| Dosya | Durum |
|---|---|
| `docs/reports/02-medya-istatistigi.md` | Bu rapor — **yeni dosya** |
| `scripts/media_stats.py` | Ölçüm scripti — **yeni dosya, YAZILDI ama ÇALIŞTIRILMADI** |

Mevcut hiçbir dosya değiştirilmedi.

`scripts/media_stats.py` salt okunurdur: `frappe.db.set_value`, `frappe.db.commit`,
`doc.save`, `doc.insert`, `os.remove`, `shutil.*` **çağrısı içermez**. Tek yazma
işlemi, `MEDIA_STATS_OUT` ortam değişkeni doluysa JSON raporunu **dosyaya** yazmaktır
— veritabanına değil.

# 110 — CWV / Render Performans Denetimi: panel etiketleri + canlı ölçüm (Görev 4)

**Tarih:** 2026-08-27
**Ortam:** `istoc-dev-backend-1`, site `istoc.localhost` (yerel dev).
**Kapsam:** Dilim 7'nin (CWV/render performans denetimi, MOGEM-620 §9 A-9)
SON görevi — Task 1-3'te eklenen 5 yeni kuralın (`missing_modern_format`,
`incomplete_rendition_ladder`, `unserved_renditions`, `aspect_ratio_mismatch`,
`lcp_candidate_unoptimized`) panel yüzeyi keşfi + gerçek katalogda canlı
ölçümü + T3'ten devreden 2 mini iş (core).

Yöntem (rapor 106-109 ile aynı kısıt): `docker cp` ile konteynere taşınan
tek seferlik script, `bench --site istoc.localhost console` içine
`exec(open('/tmp/measure_110.py').read(), {})` ile beslendi (çok satırlı
döngüler console stdin pipe'ında bozulduğu için). Script yalnız `SELECT`/
`get_all`/`audit_batch` çağırdı — **`frappe.db.commit()` hiç çağrılmadı**,
hiçbir DocType'a yazma yapılmadı.

**Düzeltme notu (2026-08-27, aynı gün ikinci tur):** İlk sürümdeki §3.2
yorumu ("katalogda neredeyse hiç rendition yok") koordinatörün bağımsız
canlı sondajıyla YANLIŞ bulundu ve `/tmp/verify_110.py` (aynı desen,
salt-okur, `frappe.db.count`/`frappe.db.sql`) ile ikinci kez doğrulanarak
düzeltildi. Kod DEĞİŞMEDİ — yalnız bu rapor ve `task-4-report.md`. Detay
§3.2/§3.2b/§3.2c'de.

---

## 1. Panel etiket keşfi

```
$ grep -rn "missing_responsive_variants\|oversized_image" admin-panel/frontend/src
```

**Bulgu: harita VAR.** Panelin denetim ekranı (`views/system/MediaSeoView.vue`)
bulgu kodlarını çıplak göstermiyor — `t(`mediaSeo.finding.${code}`)` ile
i18n'den etiket çekiyor (satır 106, 118, 390, 552). Anahtar-değer haritası
`admin-panel/frontend/src/i18n/locales/{tr,en,ar,ru}.js` içinde `mediaSeo.finding`
namespace'inde duruyor; `tr.js`/`en.js` 21 mevcut koddan 21'ini de eksiksiz
taşıyordu (`ar.js`/`ru.js` 20/21 — küçük bir tutarsızlık var ama bu görevin
kapsamı dışında, dokunulmadı).

**Yapılan değişiklik:** `tr.js` ve `en.js`'e 5 yeni kod için etiket eklendi
(brief yalnız tr/en istiyor):

| Kod | TR | EN |
|---|---|---|
| `missing_modern_format` | Modern format (AVIF/WebP) üretilmemiş | No modern format (AVIF/WebP) generated |
| `incomplete_rendition_ladder` | Türev merdiveni eksik | Rendition ladder is incomplete |
| `unserved_renditions` | Türevler üretildi ama servis edilmiyor | Renditions exist but none are servable |
| `aspect_ratio_mismatch` | En-boy oranı türevle uyuşmuyor | Aspect ratio does not match rendition |
| `lcp_candidate_unoptimized` | LCP adayı optimize edilmemiş | LCP candidate is unoptimized |

Değişen dosyalar: `admin-panel/frontend/src/i18n/locales/tr.js`,
`admin-panel/frontend/src/i18n/locales/en.js`. Yeni bileşen/route eklenmedi
(spec §6: "yeni panel bileşeni YOK").

**Test koşumu:** Bu 5 kod için ayrı bir birim test yok (harita doğrudan i18n
dosyasında, `MediaSeoScorecard`/`MediaSeoDrawer` testleri kod→etiket eşlemesini
hedeflemiyor) — güvenlik için tüm panel paketi koşuldu:

```
$ npm test   # admin-panel/frontend
ℹ pass 1385
ℹ fail 3
ℹ skipped 5
```

3 başarısızlık **bu değişiklikten ÖNCE de var olan, ilgisiz** testler:
`contract.live.test.js` içindeki 2 canlı-API zaman aşımı (backend'e bağımlı,
locale dosyasıyla ilgisi yok) ve `policyEngineParity.test.js`'in
`tradehub_core/tradehub_core/media/pipeline/policy/engine.py` hash-eşleşme
kontrolü (bu görevde o dosyaya dokunulmadı — kaynak başka bir nedenle
kaymış, önceden var olan bir borç). Locale dosyalarına dokunan hiçbir test
etkilenmedi.

---

## 2. T3'ten devreden 2 mini iş (core)

### 2a. `lcp_candidate_unoptimized` × `missing_responsive_variants` çift-sinyal testi

`tradehub_core/tests/test_media_seo_pipeline.py::TestTopluDenetim::
test_hic_turev_yoksa_primary_gorselde_lcp_de_tetiklenir` eklendi.

Sabitlenen davranış: `renditions=None` olan (hiç türevi olmayan) bir
**primary** görselde `missing_responsive_variants` ("hiç türev yok") VE
`lcp_candidate_unoptimized`'ın modern-format bacağı ("modern format yok")
**BİRLİKTE** tetikleniyor. Bu bir bug değil — `_rendition_bulgulari`
(format/merdiven/oran kuralları) kendi ayrık-küme kapısına sahip
(`not renditions` → `[]`, `missing_responsive_variants` ile hiç çakışmaz),
ama `_lcp_bulgusu` aynı kapıyı TAŞIMIYOR: `renditions or []` boş listede
`_servis_edilebilir` de boş döner, modern-format kümesiyle kesişim boş
kalır ve "modern format yok" nedeni eklenir. LCP adayında iki sinyal ayrı
anlam taşıyor — biri "hiç türev üretilmedi", diğeri "servis edilebilir
modern format yok" — ve §3 canlı ölçümünde görüleceği gibi bu asıl katalog
davranışının kendisi (aşağıya bakınız).

### 2b. `_lcp_bulgusu` KIND_IMAGE asimetrisi — yorum eklendi

`tradehub_core/media/seo_audit.py::_lcp_bulgusu` içinde boyut bacağı
(`if not (alanlar.get("width") and alanlar.get("height"))`) format bacağının
aksine `upload_policy.kind_of(url) == KIND_IMAGE` kontrolü yapmıyor. Davranış
DEĞİŞTİRİLMEDİ — yalnız kısa bir "neden" yorumu eklendi: `primary_urls`
(C5) sözleşmesi gereği LCP adayı zaten `Listing.primary_image`, pratikte her
zaman görsel; asimetri bilinçli çünkü boyut eksikliği dosya türünden
bağımsız evrensel bir sinyal, "modern format" kavramı ise yalnız görsel
formatlar için anlamlı (video/dokümanda AVIF/WebP kavramı yok).

Değişen dosyalar: `tradehub_core/media/seo_audit.py` (yorum +
`_lcp_bulgusu` docstring çevresi), `tradehub_core/tests/test_media_seo_pipeline.py`
(+1 test).

---

## 3. Canlı ölçüm — katalog kapsamı

```
$ docker cp measure_110.py istoc-dev-backend-1:/tmp/measure_110.py
$ docker exec istoc-dev-backend-1 bash -lc \
    "cd /home/frappe/frappe-bench && \
     echo \"exec(open('/tmp/measure_110.py').read(), {})\" | \
     bench --site istoc.localhost console"
```

Script `_seo_audit_adaylari("catalog", 20000)` + `seo_audit.audit_batch(urls,
primary_urls=primary)` çağırdı — `audit_media_seo`'nun kendisi değil, onun
çağırdığı iki fonksiyon doğrudan (console'da whitelist guard'ı atlamak için,
salt-okur amaçla).

### 3.1 Aday kümeleri

| Ölçü | Değer |
|---|---:|
| `urls` (katalog, primary+galeri birleşik) | **1986** |
| `primary_urls` (`Listing.primary_image`, storefront_visible=1) | **1113** |

Görev talimatındaki "1986 url / 1113 primary" reviewer repro'suyla birebir
eşleşiyor.

### 3.2 Yeni 5 kuralın tetiklenme sayısı

| Kod | Sayı |
|---|---:|
| `missing_modern_format` | **0** |
| `incomplete_rendition_ladder` | **0** |
| `unserved_renditions` | **0** |
| `aspect_ratio_mismatch` | **0** |
| `lcp_candidate_unoptimized` | **1112** |

**Düzeltme (koordinatör canlı sondajı, 2026-08-27):** Bu bölümün ilk sürümü
"katalogda neredeyse hiç `Media Rendition` yok" diyordu — bu **yanlıştı**.
Bağımsız doğrulama (`frappe.db.count`/`frappe.db.sql`, salt-okur) aşağıdaki
gerçek envanteri gösteriyor:

| Ölçü | Değer |
|---|---:|
| DB geneli toplam `Media Rendition` | **20.896** — hepsi `state=ready` |
| Format dağılımı (DB geneli) | avif **4.130** / webp **10.364** / jpeg **6.398** (+ 1 m3u8, 3 mp4) |
| `benefit_gate_passed` dağılımı | **20.866** geçmiş / yalnız **30** gate-fail |
| Katalog (1986 url) → `Media Asset` eşleşmesi | **1980 / 1986** |
| Bu 1980 asset'in toplam rendition'ı | **20.814** (ortalama **~10,5 türev/asset**) |

Yani rendition üretim boru hattı **canlı ve sağlıklı çalışıyor** — türevler
bol, modern formatlar (avif+webp=14.494) baskın, gate geçişi ezici çoğunlukla
var. **Gerçek nedenler (4 kural için ayrı ayrı):**

- `missing_modern_format=0` → **doğru sessizlik.** Modern format zaten
  neredeyse her asset'te servis ediliyor.
- `incomplete_rendition_ladder=0` → **doğru sessizlik.** Kural türev SAYISI
  değil, policy'nin beklediği PROFİL ADLARININ tamamının üretilip
  üretilmediğini kıyaslar; "ortalama ~10,5 türev/asset" bu kuralla ilgisiz
  bir istatistik (bir profil onlarca kez üretilse de tek adı sayılır).
  Ölçülen 0 zaten kendi başına kanıt: katalog asset'lerinin beklenen profil
  adlarının tamamına sahip olduğunu gösteriyor.
- `unserved_renditions=0` → **doğru sessizlik.** Gate geçişi ezici
  çoğunlukla var (20.866/20.896); "üretildi ama servis edilemiyor" durumu
  bu katalogda pratikte yok.
- `aspect_ratio_mismatch=0` → **BAŞKA bir nedenden, rendition eksikliğiyle
  İLGİSİZ:** kural `_rendition_bulgulari` içinde yalnız `kaynak_w > 0 and
  kaynak_h > 0` iken değerlendirilir (satır ~803). Katalog `File`
  kayıtlarının `th_media_width`/`th_media_height` alanı DOLU DEĞİL — bu
  kapıya takılıp kural tasarım gereği sessiz kalıyor (aşağıya bakınız,
  §3.2b). Rendition'larla hiçbir ilgisi yok; tam tersi, rendition verisi
  zengin olduğu için bu kural şu an "kör" kalıyor.

**`lcp_candidate_unoptimized` neden 1112/1113 (neredeyse tüm primary
görseller) — gerçek sürücü boyut bacağı, modern-format bacağı DEĞİL:**
bkz. §3.2b.

### 3.2b LCP bulgusunun gerçek sürücüsü — boyut bacağı baskın

`lcp_candidate_unoptimized`'ın `detail` alanını (`_lcp_bulgusu`'nun iki
bacağından hangisi/hangileri tetiklendi) primary örneklem üzerinde kırdım.
**Örnekleme notu:** `sorted(primary_urls)[:300]` kullanıldı — alfabetik
sıranın BAŞI, hafif bir önyargı taşıyabilir (rastgele örnek değil); yine de
300/1113 (%27) yeterince büyük bir dilim ve sonuç tekil kaçış değil.

| Detay | Sayı (300 örnekte) |
|---|---:|
| yalnız "boyut bilgisi eksik" | **297** |
| "boyut bilgisi eksik, modern format yok" | **2** |
| yalnız "modern format yok" | 0 |
| Toplam `lcp_candidate_unoptimized` (300 örnekte) | 299 |

**Gerçek kök neden: `th_media_width`/`th_media_height` katalog genelinde
neredeyse hiç dolu değil**, rendition/format eksikliği değil:

| Ölçü | Değer |
|---|---:|
| Katalog url'lerine karşılık gelen `File` satırı (duplicate'ler dahil) | 3.130 |
| Bunlardan boyutu DOLU olan | **3** |
| 300'lük primary örneklemde boyutu dolu olan | **1 / 300** |
| Aynı örneklemde `missing_dimensions` (mevcut, ÖNCEDEN VAR OLAN kural) | **299 / 300** |

`missing_dimensions` katalogda zaten bu ölçekte (299/300) ateşleniyordu —
bu **dilim öncesinden beri var olan bir veri boşluğu**. Yeni
`lcp_candidate_unoptimized` kuralı bu boşluğu icat etmedi; onu **LCP
merceğinden yeniden görünür kıldı** ("bu eksik boyut bilgisi, sıradan bir
görsel için değil, sayfanın LCP adayı için eksik" — daha kritik bir çerçeve).
2/300 satırda "modern format yok" da görünüyor: bunlar gerçekten nadir,
modern rendition'ı olmayan asset'ler (katalogdaki 6 istisnadan biri, §3.2'nin
"neredeyse her asset'te modern format var" gözlemiyle tutarlı — İSTİSNA,
kural DEĞİL).

### 3.2c Önerilen takip işi (ÇALIŞTIRILMADI — insan kararına bırakılıyor)

Yukarıdaki bulgu tek bir somut takip aksiyonuna işaret ediyor: **katalog
genelinde `th_media_width`/`th_media_height` backfill'i**, mevcut
metadata/probe altyapısıyla (dosya zaten diskte/depoda var, yalnız ölçü
probe'u hiç çalışmamış ya da sonucu `File`'a yazılmamış görünüyor — kesin
kök neden bu görevin kapsamı dışında, ayrı bir keşif gerektirir). Bu
backfill koşulursa beklenen etki:

- `lcp_candidate_unoptimized` (1112 → ~2'ye, yalnız gerçek modern-format
  eksikliği kalır) ve `missing_dimensions` büyük oranda kapanır.
- `aspect_ratio_mismatch` ancak O ZAMAN gerçek bir sinyal üretebilir hale
  gelir — bugün `kaynak_w/h` guard'ına takılıp hiç çalışmıyor; kaynak
  ölçüleri dolunca CLS riski kontrolü fiilen devreye girer.

**Bu backfill bu görevde ÇALIŞTIRILMADI** — talimat gereği yalnız ölçüm/rapor
kapsamı, yazma işlemi insan kararına bırakılıyor.

### 3.3 Skor önce/sonra

```
SCORE_SONRA (modülün audit_batch çıktısı, 8 boyut + overall):
accessibility=60  discoverability=100  localization=0  metadata=60
overall=55  performance=49  rights=80  structured_data=0
technical_health=94
```

**Yöntem (ayrı koşum YOK — aynı çıktıdan türetildi):** `sonuc["files"]`
her dosya için tam `findings` listesini taşıyor. Modülün kendi
`_KURAL_BOYUT`/`_CEZA` sabitleriyle, her dosya için `performance` ve
`technical_health` boyutunun cezasını **5 yeni kodu hariç tutarak** yeniden
topladım (`max(0, 100 - ceza)`), sonra dosyalar üstünden aynı ortalamayı
aldım (`round(sum/len)`) — modülün `score_from`/`audit_batch` yaptığı
işlemin birebir aynısı, yalnız filtre kümesi farklı. Doğrulama: 5 yeni kod
DAHİL edilerek aynı yöntemle hesaplanan "sonra" değeri, modülün kendi
`sonuc["score"]` çıktısıyla **tam eşleşti** (script çıktısında
`eslesiyor_mu=True`), yani türetim yöntemi doğru.

| Boyut | Önce (5 yeni kural yokmuş gibi) | Sonra (gerçek, bugünkü kod) |
|---|---:|---:|
| `performance` | **60** | **49** |
| `technical_health` | **94** | **94** |

`technical_health` değişmedi çünkü tek yeni kuralı (`unserved_renditions`)
bu ölçümde hiç tetiklenmedi (§3.2 — DOĞRU sessizlik, gate geçişi zaten
sağlıklı). `performance` 60→49 düştü — tamamı `lcp_candidate_unoptimized`'ın
1112 tetiklenmesinden geliyor (diğer 3 performance-boyutlu yeni kural da 0).

**Düzeltilmiş yorum (§3.2/§3.2b'ye bağlı):** Bu düşüş "rendition üretim
boru hattı eksik" ANLAMINA GELMİYOR — o boru hattı sağlıklı (§3.2).
Gerçek anlamı: **`th_media_width`/`th_media_height` katalog genelinde
neredeyse hiç dolu değil** (299/300 örnekte boyut eksik, dilim öncesinden
beri var olan bir veri boşluğu — `missing_dimensions` zaten aynı ölçekte
ateşleniyordu). Yeni LCP kuralı bu ÖNCEDEN VAR OLAN boşluğu icat etmedi,
onu daha kritik bir çerçeveden (LCP adayı özelinde) yeniden görünür kıldı.
`performance` skorundaki 11 puanlık düşüş, "yeni kurallar katalogda yeni
bir sorun buldu" değil, "yeni kurallar mevcut bir veri kalitesi sorununu
performans merceğinden bir kez daha, daha ağır bir şekilde saydı" olarak
okunmalı. §3.2c'deki boyut backfill'i koşulursa bu düşüşün büyük kısmının
geri kazanılması beklenir.

### 3.4 RUM özeti (`Media RUM Sample`)

```
RUM_TOPLAM_SATIR 113
RUM CLS  good              35
RUM CLS  poor                1
RUM INP  good                1
RUM LCP  good               40
RUM LCP  poor                1
RUM TTFB good              35
```

| Metrik | Toplam örnek | good | needs-improvement | poor |
|---|---:|---:|---:|---:|
| LCP | 41 | 40 | 0 | 1 |
| CLS | 36 | 35 | 0 | 1 |
| INP | 1 | 1 | 0 | 0 |
| TTFB | 35 | 35 | 0 | 0 |
| FCP | 0 | 0 | 0 | 0 |

**LCP satırlarında `lcp_format` kırılımı (41 satır):**

| Format | good | poor |
|---|---:|---:|
| (boş) | 26 | 1 |
| avif | 3 | 0 |
| webp | 4 | 0 |
| jpg | 2 | 0 |
| jpeg | 1 | 0 |
| png | 4 | 0 |

**Dürüst yorum — örneklem YETERSİZ, yön göstermez.** Toplam 113 satır, en
büyük metrik grubu (LCP) 41, en küçüğü (INP) **1** örnek. Bu ölçek üzerinden
"modern format kullanan LCP'ler daha iyi rating alıyor" gibi bir sonuç
çıkarmak istatistiksel olarak anlamsız — `poor` etiketli tek LCP satırının
`lcp_format` boş (yani format bilgisi hiç toplanamamış bir örnek), `good`
etiketli 26/40 satır da aynı şekilde format bilgisiz. Format kırılımı ile
rating arasında bu örneklemde **hiçbir yön iddia edilmiyor**; RUM burada
yalnız "toplama pipeline'ı çalışıyor ve veri akıyor" doğrulaması olarak
okunmalı, kural değişikliği için karar verici değil (spec C1: "RUM verisi
kural DEĞİL, rapor 110'da ölçüm özeti").

---

## 4. Testler — gerçek koşum

```
$ docker cp seo_audit.py istoc-dev-backend-1:.../media/seo_audit.py
$ docker cp test_media_seo_pipeline.py istoc-dev-backend-1:.../tests/test_media_seo_pipeline.py
$ docker exec istoc-dev-backend-1 bash -lc \
    "cd /home/frappe/frappe-bench && bench --site istoc.localhost \
     run-tests --module tradehub_core.tests.test_media_seo_pipeline"
Ran 66 tests in 1.725s
OK
```

66/66 (65 önceki + 1 yeni, §2a). `ruff check` (container içinde, aynı iki
dosya üstünde): **All checks passed!** — tab indent + ≤110 satır kuralları
korundu, `log_error` çağrıları dokunulmadı.

**Not (`docker cp` gerekliliği):** Konteynerdeki `apps/tradehub_core`
dizini host reposunun bind-mount'u DEĞİL — imaj build'inde gömülü, ayrı bir
kopya (bkz. `docker/docker-compose.yml` `image: istoc/tradehub-backend:v15`).
Bu görevde değiştirilen 2 dosya (`seo_audit.py`, `test_media_seo_pipeline.py`)
`docker cp` ile konteynere geçici olarak taşındı — **imaj rebuild edilmedi,
recreate/migrate ÇALIŞTIRILMADI** (bilinen tuzak: recreate+migrate bayat
JSON'u DB'ye geri yazabilir). Diğer dosyalar (`media_admin.py`,
`upload_policy.py` vb.) T1-T3'ten zaten senkron durumdaydı (diff ile
doğrulandı).

---

## 5. Öz-denetim

- **Tüm sayılar gerçek sorgu çıktısı** — `/tmp/measure_110.py`
  `_seo_audit_adaylari`, `seo_audit.audit_batch`, `frappe.get_all` gibi
  gerçek API'leri çağırdı; tahmini/yuvarlanmış değer yok. Script hiçbir
  yazma işlemi yapmadı, `frappe.db.commit()` hiç çağrılmadı.
- **"0" ve "yetersiz örneklem" dürüstçe raporlandı, ve bir kez DÜZELTİLDİ**
  — bu bölümün ilk sürümü 4 yeni kuralın 0 çıkmasını "ortamda henüz
  rendition verisi yok" diye açıklamıştı; koordinatörün canlı sondajıyla
  bu YANLIŞ çıktı (rendition verisi bol ve sağlıklı — §3.2) ve rapor
  düzeltildi: gerçek nedenler kural bazında ayrı ayrı (3'ü doğru sessizlik,
  1'i `th_media_width/height` eksikliğine bağlı kör nokta). RUM'un 113
  satırı ayrıca yön göstermeyecek kadar küçük — bu değerlendirme değişmedi.
- **`aspect_ratio_mismatch`'in 0 çıkma nedeni rendition değil, kaynak
  ölçüsü eksikliği:** kural `kaynak_w > 0 and kaynak_h > 0` guard'ına bağlı;
  katalogda bu neredeyse hiç sağlanmıyor (§3.2b). T2'de düzeltilen pad-fit
  ayrımı (`fit != "pad"` filtresi, review bulgusu #1) olmasaydı, kaynak
  ölçüleri dolduğunda (backfill sonrası, §3.2c) bu kural policy-izinli
  4:5/3:4 kaynaklarda HER ZAMAN yanlış pozitif üretecekti (pad profilleri
  kareye dolguluyor). Bugünün 0'ı "kural doğru çalışıyor" göstergesi değil
  — "kaynak ölçüsü yok, kural hiç çalışamıyor" göstergesi; doğruluk kanıtı
  `TestTopluDenetim`'in `test_pad_fit_turevde_oran_kontrolu_atlanir` /
  `test_contain_turevle_gercek_oran_bozulmasi_tespit_edilir` testlerinden
  geliyor — backfill sonrası bu kuralın GERÇEK sinyal üretip üretmediği
  yeniden ölçülmeli.
- **Skor türetimi ikinci bir koşum gerektirmedi** — aynı `audit_batch`
  çağrısının döndürdüğü `findings` listesi üzerinden, modülün kendi
  `_KURAL_BOYUT`/`_CEZA` sabitleriyle yeniden hesaplandı; "sonra" değerinin
  modülün gerçek `score` çıktısıyla birebir eşleştiği doğrulanarak yöntem
  kendi kendini sınadı.
- **Panel işi minimal ve gerekliydi** — harita gerçekten var (`i18n`
  dosyaları), 5 etiket eklendi, yeni bileşen/route açılmadı (spec §6).
- **Yazma disiplini:** commit YOK, `git add` YOK, yeni branch YOK, subagent
  YOK. `docker cp` geçici (imaj rebuild edilmedi).

---

## EK — Boyut backfill koşumu (2026-08-28, kullanıcı onayıyla)

§3.2c'de "insan kararına bırakıldı" denen katalog boyut backfill'i kullanıcı
talimatıyla ("boyut backfill'ini çalıştır") koşuldu.

**Komut:** `seo_generate.backfill_dimensions(limit=2000)` × 4 tur (console
script, tur başına `frappe.db.commit()`), ardından tam katalog denetimi
(`_seo_audit_adaylari("catalog")` → `audit_batch(primary_urls=...)`).

**Sonuçlar:**

| Ölçü | Önce | Sonra |
|---|---|---|
| `th_media_width/height` doluluğu (yerel dosyalar) | 27 / 4.611 (%0,6) | **4.363 / 4.611 (%94,6)** |
| `missing_dimensions` (katalog) | ~1.100+ | **0** |
| `lcp_candidate_unoptimized` | 1.112 | **4** |
| `performance` skoru | 49 | **98** |
| `overall` skor | 55 | **74** |
| `aspect_ratio_mismatch` | 0 (kör) | 0 (**gerçek sinyal** — pad-fit ayrımı sayesinde yanlış pozitif seli yok; §5'teki öngörü doğrulandı) |
| `oversized_image` | 2 (örneklemde) | **108** (büyük pikselli kaynaklar artık görünür) |
| `incomplete_rendition_ladder` | 0 (kör) | **68** (merdiven boşlukları artık görünür) |

Toplam 4.836 yazım; kalıcı artık: 3 okunamaz dosya + 50 kayıp dosya
(diskte yok), ~195 görsel-dışı/kapsam-dışı satır. Koşum idempotent —
son tur `written=0` ile durdu.

**Yorum:** CWV kurallarının değeri veri dolunca ortaya çıktı: LCP bulguları
1.112'den 4'e düşerken, daha önce kör olan iki kural (oversized 108, ladder
68) ilk kez gerçek iş listesi üretti. `aspect_ratio_mismatch`'in 0 kalması,
T2 review'ünde eklenen pad-fit ayrımının sahada doğrulanması — o düzeltme
olmasaydı bugün ~yüzlerce yanlış pozitif basılacaktı. Kalan 4 LCP bulgusu
ve 108+68 yeni bulgu panelden süzülerek çalışılabilir.

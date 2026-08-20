# 38 — T-017 zararlı dosya kapısı · T-131 SVG · T-025 içerik eşikleri

**Tarih:** 2026-08-19 · **Dal:** `ahmet` · **Kapsam:** T-017 (öncelik), T-131, T-025
**Koşum ortamı:** `istoc-dev-backend-1` (Docker), site `istoc.localhost`, Pillow **12.2.0**,
numpy 2.4.6, defusedxml 0.7.1. Uygulama imaja gömülü → ölçüm betikleri `docker cp` ile taşındı.

> **Süre/performans iddiası YOK.** Makinede paralel ajanlar çalışıyordu; yalnız
> geçti/kaldı ve sayım ölçüldü.
> **`Media Engine Settings` bayrakları** ölçüm öncesi ve sonrası okundu:
> `media_pipeline_enabled=0 · rendition_on_upload=0 · manifest_api_enabled=0` — **değişmedi**.
> Hiçbir doctype'ta kayıt oluşturulmadı, silinmedi.

| İşaret | Anlamı |
|---|---|
| **[Ö]** | Bu oturumda ölçüldü — komut ve çıktı aşağıda. |
| **[T]** | Test koşuldu — modül ve sonuç aşağıda. |
| **[K]** | Kod okundu, varlığı doğrulandı. |
| **ÖLÇÜLMEDİ** | Ölçülemedi; iddia YOK. |

---

## 0. Özet

| Görev | Önce | Sonra |
|---|---|---|
| **T-017** kötücül fixture kapısı | **8/10 GEÇİYORDU** | **10/10 REDDEDİLİYOR** (kanca yolu + medya ucu) |
| Meşru yol (4.584 public + 1.010 private + 41 fixture gerçek dosya) | — | **hiçbiri kesilmedi** (0 regresyon) |
| **T-131** SVG saldırı vektörü | testi yoktu | **26 vektör + 3 RET vektörü** sınandı, hepsi temiz; **130 gerçek SVG** ölçüldü |
| **T-025** içerik eşikleri | `UNCALIBRATED`, hiç çalıştırılmamış | **1.291 canlı ürün görselinde ÇALIŞTIRILDI**, 6 kuralın tetiklenme oranı ölçüldü — *kalibre EDİLEMEDİ (etiket yok)*, eşikler değişmedi |

**Yol boyunca bulunan ikinci açık:** `image/probe.py`'nin "pikselleri AÇMAZ"
garantisi **PNG'de tutmuyordu** — `getexif()` Pillow 12.2.0'da `load()` çağırıyor,
yani 100 MP'lik bomba kapının kendisinde tam decode ediliyordu (§3.3).

**En riskli açık bulgu:** `content_rules.json` `extreme_blur` RED üretebiliyor ve
canlı ürün görsellerinin **%1,70'ini (22 dosya)** gizlerdi; kuralın kendi
`rollout` sözleşmesi reject kuralları için FP < %1 istiyor (§6.3).

---

## 1. T-017 — kapının taban durumu bağımsız olarak tekrarlandı **[Ö]**

Rapor 33 §T-017'nin bulgusu, kaynak koda dokunulmadan önce aynı yöntemle
tekrarlandı: `upload_policy.check(ad, content=..., media_endpoint=...)` 10
kötücül fixture'a uygulandı.

```
=== KOTUCUL FIXTURE (kanca yolu, media_endpoint=False) ===
GECTI  bomb_100mp.png                                     97221 B
GECTI  data_uri_svg.txt                                     179 B
RED    empty_zero_byte.jpg      upload_content_empty          0 B
GECTI  executable_as.png                                    359 B
GECTI  fake_docx.docx                                       369 B
GECTI  jpeg_with_html_tail.jpg                            14760 B
GECTI  polyglot_pdf_as.jpg      (uyari: uzanti=.jpg icerik=pdf)
GECTI  polyglot_png_as.jpg      (uyari: uzanti=.jpg icerik=png)
RED    script_payload.svg       upload_ext_denied           555 B
GECTI  truncated.jpg                                     247095 B
kanca yolu:  RED=2 GECTI=8          medya ucu: RED=4 GECTI=6
```

**Rapor 33 doğrulandı: 8/10 geçiyordu.** Medya ucunda 2 fixture fazladan
düşüyor ama sebebi güvenlik değil, izin listesi (`.txt`/`.docx` medya ucunda
kabul edilmiyor) — aynı dosyalar kanca yolundan geçiyordu.

### 1.1 Her fixture NEDEN geçiyordu — tek tek teşhis **[K]**

| Fixture | Kapıdaki boşluk | Kanıt |
|---|---|---|
| `bomb_100mp.png` | **Piksel tavanı hiç yoktu.** 10000×10000 = 100 MP, 97 KB. Boyut sınırı (25 MB) ve imza kontrolü geçti. | `upload_policy.check()` içinde `megapixel` geçen tek satır yoktu |
| `executable_as.png` | `upload_policy.sniff()` tablosunda **MZ/ELF yok**; tür "bilinmiyor" çıkıp uzantıya güvenildi. | `_SIGNATURES` 11 girdi, hiçbiri `MZ`/`\x7fELF` değil |
| `data_uri_svg.txt` | `data:` şeması **tanınmıyordu**; `.txt` = `KIND_OTHER`, yasak listesinde değil. | `_SIGNATURES` + `_DANGEROUS_MARKERS` ikisinde de yok |
| `jpeg_with_html_tail.jpg` | `is_dangerous()` yalnız **ilk 512 bayta** bakıyor (`bas.startswith(...)`). Yük EOI'den (`FF D9`) sonra: `<html><script>alert(1)</script></html>`. | `upload_policy.is_dangerous`, dosya kuyruğu hex dökümü |
| `polyglot_pdf_as.jpg` | Uzantı/içerik uyuşmazlığı **ret değil UYARI** idi. `%PDF-1.4` başlığı `.jpg` adıyla geçti. | `check()` içinde `uyarilar.append(...)` |
| `polyglot_png_as.jpg` | Aynı sebep — PNG gövdesi `.jpg` adıyla. | aynı satır |
| `truncated.jpg` | **Kesiklik hiç ölçülmüyordu.** Başlık geçerli (1600×1200), EOI yok. | `check()` içinde kuyruk okuması yok |
| `fake_docx.docx` | ZIP imzası (`PK\x03\x04`) doğru diye geçti; kap **hiç açılmadı**. İçi: `merhaba.txt`, `dizin/veri.bin`. | `_UYUM` sözlüğünde `.docx` girdisi yok → `_uyumlu()` `True` döner |
| `empty_zero_byte.jpg` | — reddediliyordu (`upload_content_empty`) | — |
| `script_payload.svg` | — reddediliyordu (`upload_ext_denied`) | — |

### 1.2 Kök sebep: kapı ile denetim iki ayrı yerde duruyordu **[K]**

`tradehub_core/media/pipeline/image/probe.py` (`probe_header`) bu kontrollerin
**çoğunu zaten doğru yapıyordu** — piksel tavanı, kesiklik, eklenmiş yük,
çalıştırılabilir imza. Ama:

```
$ grep -rn "probe_header\|assert_accepted" tradehub_core --include=*.py | grep -v tests/
(çıktı yok)
```

**Hiçbir üretim yolu onu çağırmıyordu.** Yükleme yollarının tamamı
`upload_policy.check()`'ten geçiyor (`utils/security.py:_apply_upload_policy`
→ `File.before_insert` kancası; `api/seller_media.py:_kaydet`;
`media/files.py:replace`), o da yalnız ilk 512 baytı denetliyordu. Yani
denetim yazılmış ama kapıya **bağlanmamıştı**.

---

## 2. Eşikler GERÇEK korpusta ölçüldü — kapıyı sıkmadan önce **[Ö]**

Kapıyı sıkmanın bedeli, meşru dosyaları kesmektir. Bu yüzden her yeni kural
önce gerçek dosyalarda ölçüldü, sonra yazıldı.

**Korpus:** `sites/istoc.localhost/public/files` (**4.584** dosya, 3.897'si
Pillow ile açılabilir görsel) + `private/files` (**1.010** dosya) + fixture
korpusu (34 görsel + 7 video).

| Ölçüm | public | private | Kararı nasıl etkiledi |
|---|---:|---:|---|
| Megapiksel p50 / p90 / p99 | 1,05 / 4,0 / 29,2 | 1,16 / 3,14 / 17,3 | — |
| **En büyük gerçek görsel** | **72,71 MP** (10315×7049 JPEG) | 18,28 MP | Piksel tavanı **80 MP** seçildi: bombayı (100 MP) keser, gerçek dosyayı kesmez |
| >20 MP dosya | 120 | 0 | Tavanı 25 MP'ye çekmek 120 gerçek dosyayı keserdi |
| **Kesik dosya (EOI/IEND yok)** | **0** | **0** | Kesikliği RET yapmak güvenli |
| **Eklenmiş yük (EOI sonrası markup)** | **0** | **0** | Eklenmiş yükü RET yapmak güvenli |
| **Çalıştırılabilir sihirli bayt (MZ/ELF)** | **0** | **0** | RET yapmak güvenli |
| `data:` URI içerikli dosya | **0** | **0** | RET yapmak güvenli |
| Uzantı≠içerik (ham) | 640 | 852 | **Reddedilemez** — çoğu "sihirli bayt tanınmıyor" (`.txt`/`.csv`/`.avif`/`.heic`) |
| **SERT uyuşmazlık** (iki taraf da bilinen, farklı) | **1** | **0** | Tek örnek `.mp4` içinde webm → görsel dışı, RET edilmedi |
| **Görsel uzantıda sert uyuşmazlık** | **0** | **0** | Görsel tarafta RET yapmak güvenli |
| Bozuk zip | 0 | 0 | — |
| OOXML (`.docx`/`.xlsx`) | 0 | 31 | **31/31**'inde `[Content_Types].xml` + doğru kök (`word/`, `xl/`) → doğrulama güvenli |
| Düz `.zip` (ürün görseli arşivi) | 0 | 11 | Doğrulanmıyor: zip'in iddia ettiği iç yapı yok |
| Animasyonlu görsel | **0** | **0** | Animasyon kapıda RET EDİLMİYOR — slot politikasının işi |
| Pillow açamayan `.png` | 1 | 0 | 28 baytlık `\x89PNG entegrasyon test verisi` — gerçek görsel değil, test artığı |

### 2.1 Sıkıştırma oranı EŞİK OLARAK KULLANILAMADI — ölçüldü, ayrık değil **[Ö]**

Bomba savunmasında ikinci bir sinyal denendi: piksel/bayt oranı.

```
gorsel n=4037  piksel/bayt orani
  p50=16,03  p90=38,85  p99=85,9  p99,9=210,65  max=678,25
  en yuksek: 678,3 (enc_webp_lossless.webp, 1,05 MP / 1546 B)
             251,0 (2,76 MP / 11016 B webp) …
  bomb_100mp.png = 1028,6
```

Gerçek korpusun tepesi ile bombanın arası **yalnız 1,5 kat**. Bu ayrımla eşik
koymak, düz zeminli logo ve lossless WebP'lerde yanlış pozitif üretirdi.
**Eşik konmadı**; karar `content_gate.py` modül başlığında yazılı. Bombanın
ikinci savunma katmanı eşik değil, `security/isolation.py` (rlimit'li alt
süreç).

---

## 3. Düzeltme — ne yapıldı

### 3.1 Yeni modül: `media/pipeline/security/content_gate.py` (frappe'siz)

Denetim `upload_policy` içine yazılmadı; ayrı ve frappe'siz bir modüle kondu ki
bench olmadan test edilebilsin. Yedi kontrol, sırayla:

| # | Kontrol | Kod | Kapattığı fixture |
|---|---|---|---|
| 1 | Dosyanın başı çalıştırılabilir işaret | `upload_content_dangerous` | `script_payload.svg` |
| 2 | Sihirli bayt: `executable` / `data_uri` / `svg` / `xml` | `upload_content_dangerous` | `executable_as.png`, `data_uri_svg.txt` |
| 3 | Görsel uzantıda tehlikeli tür uyuşmazlığı | `upload_type_mismatch` | `polyglot_pdf_as.jpg`, `polyglot_png_as.jpg` |
| 4 | Görselin EOI/IEND'inden sonra eklenmiş yük | `upload_appended_payload` | `jpeg_with_html_tail.jpg` |
| 5 | OOXML kabı iddia ettiği belge değil | `upload_container_invalid` | `fake_docx.docx` |
| 6 | Kesiklik (bitiş işareti yok) | `upload_content_truncated` | `truncated.jpg` |
| 7 | Piksel tavanı — **başlıktan**, 80 MP | `upload_image_bomb` | `bomb_100mp.png` |

Sezgiler tekrar yazılmadı: `sniff`, `_has_leading_marker`,
`_has_appended_payload`, `EXTENSION_KINDS` `core/probe.py`'dan; başlık okuma
`image/probe._open_header`'dan çağrılıyor.

### 3.2 `upload_policy.check()` denetimi çağırıyor

Tek satırlık bağlantı (`_derin_denetim`) her yükleme yolunu birden kapsıyor:
`File.before_insert` kancası (22 ekran), `api/seller_media` medya uçları,
`media/files.replace`. Beş yeni hata kodu `ALL_CODES`'a eklendi; hepsi
`retryable=False` (aynı dosya aynı cevabı verir).

### 3.3 `image/probe.py` — ikinci, önceden bilinmeyen açık **[Ö]**

Testi yazarken ölçüldü: `probe_header` "pikselleri AÇMAZ" diyor ama **PNG'de
açıyordu**.

```
Pillow 12.2.0, `Image.load` sayaci, 64×64 ornek:
  JPEG geometri=0 getexif_sonrasi=0
  PNG  geometri=0 getexif_sonrasi=2      ← PngImagePlugin.py:1096 `self.load()`
  WEBP 0/0 · TIFF 0/0 · GIF 0/0 · BMP 0/0
```

Yani `bomb_100mp.png` kapıda **tam olarak decode ediliyordu** — modülün
varlık sebebi olan garanti PNG'de tutmuyordu. `_open_header` artık
`EXIF_DECODES_PIXELS` (ölçülmüş liste) ve `EXIF_MAX_MEGAPIXELS` (biçimden
bağımsız emniyet) ile EXIF okumasını atlıyor; atlandığı künyeye
`exif_skipped` olarak yazılıyor — "1" değil, "ölçülmedi".

---

## 4. Sonuç ölçümü — kapı kapandı, meşru yol kırılmadı **[Ö]**

Aynı betik, aynı korpus, düzeltmeden sonra:

```
=== KOTUCUL FIXTURE (kanca yolu) ===          === KOTUCUL FIXTURE (medya ucu) ===
RED bomb_100mp.png          upload_image_bomb        RED  upload_image_bomb
RED data_uri_svg.txt        upload_content_dangerous RED  upload_ext_not_allowed
RED empty_zero_byte.jpg     upload_content_empty     RED  upload_content_empty
RED executable_as.png       upload_content_dangerous RED  upload_content_dangerous
RED fake_docx.docx          upload_container_invalid RED  upload_ext_not_allowed
RED jpeg_with_html_tail.jpg upload_appended_payload  RED  upload_appended_payload
RED polyglot_pdf_as.jpg     upload_type_mismatch     RED  upload_type_mismatch
RED polyglot_png_as.jpg     upload_type_mismatch     RED  upload_type_mismatch
RED script_payload.svg      upload_ext_denied        RED  upload_ext_denied
RED truncated.jpg           upload_content_truncated RED  upload_content_truncated
kanca yolu: RED=10 GECTI=0                    medya ucu: RED=10 GECTI=0
```

**Kaynağın kabul kriteri karşılandı: `fixtures/malicious/` içindeki HER dosya
reddediliyor** — ve hiçbiri tam decode edilmiyor (§3.3 + test
`test_bomba_pikselleri_acilmadan_reddedilir`).

### 4.1 Meşru yol — ÖNCE/SONRA aynı korpusta

| Korpus | ÖNCE (GEÇTİ/RED) | SONRA (GEÇTİ/RED) | Fark |
|---|---|---|---|
| Gerçek `public/files` (4.584) | 4.573 / 11 | 4.573 / 11 | **0** |
| Gerçek `private/files` (1.010) | 1.010 / 0 | 1.010 / 0 | **0** |
| Temiz fixture korpusu (41) | 41 / 0 | 41 / 0 | **0** |

11 red **düzeltmeden ÖNCE de vardı** ve hepsi `sitemaps/*.xml`
(`upload_ext_denied` — `.xml` zaten yasak uzantı listesindeydi). Bunlar
sistemin kendi ürettiği dosyalar, yükleme değil.

**Meşru yolda tek bir gerçek dosya bile kesilmedi.**

> Not: `public/files` oturum boyunca **4.584 → 4.620** büyüdü (makinede paralel
> ajanlar çalışıyordu). ÖNCE/SONRA karşılaştırması ikisi de **aynı anda,
> 4.584** üzerinde yapıldı. Son ölçüm 4.620'de tekrarlandı: **4.609 GEÇTİ /
> 11 RED**, red kırılımı yine yalnız `sitemaps/*.xml`.

### 4.2 Vacuity kontrolü — test gerçekten bu düzeltmeyi ölçüyor **[Ö]**

Rule: düzeltmeyi geçici geri al, KIRMIZI olduğunu göster, geri koy.

```
1) content_gate.inspect() etkisiz hale getirildi (erken return)
   → test_media_security_gate: FAILED (failures=10, errors=1)
   → kapı ölçümü: kanca yolu RED=2 GECTI=8   (taban durumla BİREBİR aynı)
   → geri konuldu: Ran 18 tests OK, "VACUITY" izi dosyada 0

2) image/probe._open_header EXIF koruması kapatıldı (`if False:`)
   → test_bomba_pikselleri_acilmadan_reddedilir: FAILED
     AssertionError: ['load','load'] != []  "piksel decode edildi — kapı bombayı açtı"
   → geri konuldu: Ran 18 tests OK
```

### 4.3 Koşulan testler **[T]**

```
tradehub_core.tests.test_media_security_gate   Ran 18 tests  OK   (YENİ)
tradehub_core.tests.test_media_security_svg    Ran 10 tests  OK   (YENİ)
─── regresyon: mevcut paketler ───
test_image_probe        16 OK      test_policy_engine    38 OK
test_contracts          69 OK      test_image_normalize  25 OK
test_image_classify     32 OK      test_crop_geometry    37 · 1 BAŞARISIZ (bkz. not)
test_dedup              57 OK      test_policy_dpi       19 OK (expected failures=1)
test_enforcement         6 OK      test_svg_sanitize     52 OK (skipped=3)
test_isolation          36 OK      test_storage_adapters 137 OK
```

`test_policy_engine`'in ayna testleri (`_SIGNATURES` / `_DANGEROUS_MARKERS`
`core/probe.py` ile aynı mı) **yeşil kaldı**: iki tablo bilinçli olarak
DEĞİŞTİRİLMEDİ, yeni tanımalar `content_gate` içinde ayrı sabitlerde.

> ⚠ **`test_crop_geometry` içinde 1 başarısızlık var ve BU DEĞİŞİKLİKLE İLGİSİ YOK** [Ö]:
> `TypeScriptPariteTesti::test_ts_ikizi_ayni_sayiyi_veriyor` —
> `node: bad option: --experimental-strip-types` (konteynerdeki Node **v20.19.2**
> bu bayrağı desteklemiyor). Ortam sorunu; medya güvenliğiyle ilgisi yok, bu
> ajanın alanında da değil. Rapor 33'ün "37 OK" ölçümü o gün geçerliydi;
> bugün **37 koştu, 1 başarısız** — kayıt altına alınıyor, "geçti" DENMİYOR.

---

## 5. T-131 — SVG sanitizasyonu, gerçek dosyalarla sınandı

### 5.1 Saldırı vektörleri — 26 vektör, hepsi tam SVG dosyası **[Ö][T]**

`tests/test_media_security_svg.py` her vektörü `svg.sanitize()`'dan geçirip
**çıktıyı bayt düzeyinde** tarıyor. Test "şu element silindi mi" demiyor;
saldırının izi (`<script`, `onload`, `javascript:`, `foreignobject`,
`@import`, `kotu.example`, `data:text/html`, `etc/passwd`, `http(s)://`)
çıktıda var mı diye soruyor. Namespace URI'leri taramadan düşülüyor.

| Sınıf | Vektörler | Sonuç |
|---|---|---|
| Script | düz, CDATA, **namespace önekli** (`<svg:script>`) | 3/3 temiz |
| Olay işleyici | `onload` (kök), `ONLOAD` (büyük harf), `onmouseover` | 3/3 temiz |
| foreignObject | XHTML `<div><img onerror>` alt ağacı | temiz — alt ağaç bütünüyle gidiyor |
| `javascript:` şeması | `xlink:href`, düz `href`, **`&#106;` entity kodlu**, **`java\tscript:`** | 4/4 temiz |
| Harici referans | `use` (https), `use` (`../../etc/passwd`), `use` (data URI), `image` (https), `image` (`data:text/html`) | 5/5 temiz |
| CSS | `<style>@import`, `<style>@font-face`, `style="expression()"`, `fill="url(https…)"` | 4/4 temiz |
| SMIL | `<set attributeName="onload">`, `<animate attributeName="xlink:href">` | 2/2 temiz |
| Diğer gömme | `<handler ev:event>`, `<iframe>`, `<meta http-equiv=refresh>` | 3/3 temiz |
| **RET edilenler** (ayrıştırıcıya hiç verilmez) | `<!DOCTYPE …ENTITY>`, XXE `SYSTEM file:///etc/passwd`, gerçek gzip akışı (`.svgz`) | 3/3 `logo_svg_dtd_forbidden` / `svg_compressed_forbidden` |

Ayrıca doğrulandı: temizlenmiş çıktı **hâlâ geçerli XML** (bozuk çıktı üretip
sorunu aşağı akışa ötelemek de bir hatadır) ve **aşırı temizlik yok** —
`<desc>&lt;script&gt;</desc>` gibi KAÇIŞLI metin korunuyor ve kaçışlı kalıyor.

### 5.2 Gerçek SVG korpusu — 130 dosya **[Ö]**

Uygulamayla birlikte dağıtılan `tradehub_core/public/` altında **130 SVG** var
(sertifika rozetleri + demo ürün görselleri).

```
gercek SVG dosyasi: 130   (defusedxml=True)
sonuc kodlari: {'ok': 130}          REDDEDILEN 0
en buyuk: 1.125 B / 14 dugum        tavanlar: max_bytes=32768  max_nodes=256
tedarik zinciri: hicbirinde <script / onload= / <foreignObject YOK
```

**⚠ BULGU — sanitize açılırsa 130 dosyanın metni gider.** Aynı ölçümde:

```
kaldirilan: element 'text' × 347   ·   attribute 'font-family' × 130
```

`logo.md` §6.2 allowlist'inde `text`/`tspan` **yok**. Bugün zararı yok
(sanitize hiçbir servis yolunda değil), ama `svg_policy.enabled` açılırsa 130
rozet sessizce metinsiz kalır. Sayı `test_metin_kaybi_olculur_ve_bilinir`
ile sabitlendi ki allowlist değişirse fark görülsün.
**Karar bende değil** — allowlist `docs/standards/logo.md` ve `slots/*.json`
sahibinde; **raporlanıyor, değiştirilmedi.**

### 5.3 CSP ve dosya servisi — ÖLÇÜLMEDİ, sınır dışı

T-131'in CSP ayağı bu ajanın yasak alanında: CSP başlıkları `docker/` (nginx)
ve `api/**` içinde. **Değiştirilmedi ve ölçülmedi.** Bilinen bağlam:
`docs/reports/29-pentest-duzeltmeleri.md` nginx sertleştirmesinin üretime
ulaşmadığını söylüyor; `.svg` iki bağımsız kapıda hâlâ yasak
(`utils/security._DENIED_EXTENSIONS`, `upload_policy._DANGEROUS_MARKERS`) ve
bu görevde **açılmadı** — `test_svg_sanitize.test_svg_bugun_hala_iki_kapida_yasak`
yeşil.

---

## 6. T-025 — içerik eşikleri gerçek korpusta ÇALIŞTIRILDI

`policy/content_rules.json` `calibration_status = UNCALIBRATED` idi ve kendi
`not_measured` bloğu *"Hiçbir eşik gerçek görselle sınanmadı — görsel korpusu
yok, Docker kapalı, üretim veritabanına erişim yok"* diyordu. Üçü de artık
geçerli değil.

**Korpus [Ö]:** `tabFile` üzerinden `attached_to_doctype='Listing'` olan
görseller — **1.291 dosya**, `primary_image` için **1.165 ayrık URL**, 1.241
ilan. Metrikler `scripts/calibrate_content_rules.py`'nin **kendi fonksiyonları**
ile hesaplandı (`flat_bg_ratio`, `frame_fill_ratio`, `border_frame`,
`laplacian_var`, `phash`) — ayrı bir uygulama yazılmadı.

**Ölçüm araçları [Ö]:** numpy **2.4.6** VAR · Pillow **12.2.0** VAR ·
pytesseract **YOK** · tesseract binary **YOK** · vision API **çağrılmadı (ağa
çıkılmadı)**.

### 6.1 Ölçülen dağılımlar ve tetiklenme oranları

| Kural | Aksiyon | Metrik p50 | Mevcut eşik | **Tetiklenme oranı** | Bütçe %5 |
|---|---|---|---|---:|---|
| `flat_background` | warn | flat_bg_ratio 1,00 | < 0,90 | **%19,7** (229/1165) | ✗ 4× aşıyor |
| `frame_fill` | warn | fill_ratio 0,487 | < 0,70 | **%72,7** (838/1153) | ✗ 14× aşıyor |
| `overlay_text` | warn | — | OCR | **ÖLÇÜLEMEDİ** | — |
| `border_frame` | warn | thickness 0 px | ≥ 2 px | **%0,2** (2/1291) | ✓ |
| `blur` | warn | lap_var 315,1 | < 100 | **%19,9** (232/1165) | ✗ 4× aşıyor |
| **`extreme_blur`** | **reject** | ten_mean 2,63 | lap<20 ∧ ten<4 ∧ uzun≥800 | **%1,70** (22/1291) | ✗ reject bütçesi %1 |
| `nsfw_content` | reject | — | ≥ 0,85 | **ÖLÇÜLEMEDİ** | — |
| `duplicate_image` | warn | hamming 18 | ≤ 8 | **%28,1** (16/57 çift) | — |
| `min_image_count` | warn | — | < 3 görsel | **≥ %96,5** (alt sınır) | ✗ |

Ham dağılımlar (yüzdelikler) `content_rules.json` içindeki her kuralın
`measured_2026_08_19` bloğuna yazıldı.

### 6.2 Ne kalibre EDİLDİ, ne EDİLMEDİ — dürüstlük beyanı

**Hiçbir eşik değiştirilmedi.** Sebebi teknik: `scripts/calibrate_content_rules.py`
FP/FN süpürmesi için **insan etiketi** ister (`label_flat_background` vb.).
Etiket üretilmedi ve üretilemezdi. Etiketsiz bir dağılımdan eşik türetmek —
"p95'i al" demek — kalibrasyon değil, kılık değiştirmiş tahmindir; dosyanın
kendi `false_positive_budget` sözleşmesini de karşılamaz, çünkü **tetiklenme
oranı ile yanlış pozitif oranı ayrı şeylerdir**: %19,7 tetiklenmenin tamamı
gerçekten karışık zeminli olabilir de, tamamı yanlış pozitif de olabilir.

`calibration_status` bu yüzden `UNCALIBRATED` → **`TRIGGER_RATE_MEASURED_UNLABELED`**
yapıldı. `rollout.stage_0_shadow`'un istediği ölçümün **yarısı** tamamlandı:
tetiklenme oranı biliniyor, FP oranı bilinmiyor (200 tetiklenmenin el ile
örneklenmesi gerekiyor).

### 6.3 T-025'ten çıkan üç somut bulgu

1. **`frame_fill` bu korpusa ait değil.** Gerçek ürün görsellerinin medyan
   doluluğu **0,487** — yani ürünün kadranın yarısını kaplaması bu pazaryerinde
   normal. %70 eşiği %72,7'sini uyarır. Bugünkü eşikle `stage_1`'e çıkarılmamalı.
2. **`extreme_blur` — RED üretebilen kural, canlı ürün görsellerinin %1,70'ini
   (22 dosya) gizlerdi.** İkinci sinyal kapısı (tenengrad) tetiklenmeyi yalnız
   %1,8'den %1,70'e düşürüyor: kapı neredeyse hiç iş yapmıyor. `rollout`
   reject kuralları için FP < %1 istiyor. **Bu 22 dosya el ile incelenmeden
   `stage_2` açılmamalı.**
3. **İki dosya duplicate eşiğinde AYRIŞIK:** `content_rules.json` `hamming ≤ 8`,
   `slots/product-image.json` `duplicate_phash hamming ≤ 6`. Aynı sorunun iki
   farklı cevabı; `slots/` bu ajanın dosyası değil — **raporlanıyor, düzeltilmedi.**

### 6.4 Ölçülmedi — iddia yok

- **Yanlış pozitif oranı** hiçbir kural için. İnsan etiketi yok.
- **`overlay_text`**: pytesseract/tesseract kurulu değil; yerel OCR yolu koşturulamadı.
- **`nsfw_content`**: skor üretmek dış vision API + ağ ister; **ağa çıkılmadı**.
- Ölçüm **dev konteynerindeki** veriyle yapıldı; üretim korpusunda tekrarlanmadı.

---

## 7. Açık bulgular — başka ajanların/insanın alanı

Bu ajanın **yasak** alanına giren ya da ürün kararı gerektiren, düzeltilmemiş
tespitler:

| # | Bulgu | Nerede | Neden burada düzeltilmedi |
|---|---|---|---|
| A-1 | **SVG allowlist metni siliyor** — `logo.md` §6.2'de `text`/`tspan` yok; depodaki 130 SVG'den 347 `<text>` düğümü ve 130 `font-family` kaldırılıyor | `docs/standards/logo.md`, `slots/*.json` `svg_policy` | Standart ve slot politikası başka sahipte |
| A-2 | **`slots/product-image.json` `blur_laplacian_variance` eşiği = 100** ve motorda ETKİN; ölçüldü: gerçek ürün görsellerinin **%19,9**'unu uyarır | `slots/product-image.json` | Slot politikası bu ajanın dosyası değil |
| A-3 | **duplicate eşiği ayrışık** — `content_rules.json` 8 vs `slots/product-image.json` 6 | ikisi arası | `slots/` dokunulmadı |
| A-4 | **CSP / dosya servisi ölçülmedi** — nginx `docker/`, servis yolu `api/**` | yasak alan | Kapsam dışı |
| A-5 | `test_contracts.py::test_uzanti_icerik_uyusmazligi_uyaridir` docstring'i *"Bugünkü `upload_policy` davranışı korunuyor: ret değil uyarı"* diyor. Test hâlâ **yeşil** (motoru sınıyor, `upload_policy`'yi değil) ama **açıklaması artık eskidi**: görsel uzantıda uyuşmazlık artık RET | `tests/test_contracts.py` | Başkasının test dosyası — yalnız raporlanıyor |
| A-6 | Gerçek public korpusta **28 baytlık sahte PNG** var (`061d562a…png`, içerik `\x89PNG entegrasyon test verisi`) — test artığı, üretim dizininde duruyor | site `public/files` | Veri temizliği, kod değil |
| A-7 | `sitemaps/*.xml` (11 dosya) `upload_ext_denied` alıyor. Yükleme değil, sistemin kendi ürettiği dosyalar; `File` kaydı açılırsa kanca onları reddeder | sitemap üretim yolu | Davranış düzeltmeden ÖNCE de aynıydı |
| A-8 | **`test_crop_geometry::test_ts_ikizi_ayni_sayiyi_veriyor` başarısız** — konteynerdeki Node **v20.19.2** `--experimental-strip-types` bayrağını desteklemiyor. Bu değişiklikle ilgisi YOK | `tests/test_crop_geometry.py` + konteyner Node sürümü | Ortam/altyapı; medya güvenliği alanı değil |

---

## 8. Değiştirilen dosyalar

| Dosya | Değişiklik |
|---|---|
| `tradehub_core/media/pipeline/security/content_gate.py` | **YENİ** — 7 içerik kontrolü, frappe'siz, eşikler ölçümle gerekçeli |
| `tradehub_core/media/upload_policy.py` | 5 yeni hata kodu + `_derin_denetim()` bağlantısı + modül başlığı güncellendi |
| `tradehub_core/media/pipeline/image/probe.py` | `EXIF_DECODES_PIXELS` / `EXIF_MAX_MEGAPIXELS` — PNG'de EXIF okumasının pikselleri açması kapatıldı |
| `tradehub_core/tests/test_media_security_gate.py` | **YENİ** — 18 test |
| `tradehub_core/tests/test_media_security_svg.py` | **YENİ** — 10 test / 26 saldırı vektörü / 130 gerçek SVG |
| `tradehub_core/media/pipeline/policy/content_rules.json` | Ölçüm blokları, `calibration_status`, `not_measured` güncellemesi. **Hiçbir eşik değişmedi.** |
| `docs/reports/38-t017-guvenlik-kapisi.md` | bu rapor |

**Dokunulmayanlar (yasak alan):** `hooks.py`, `permissions.py`, `patches.txt`,
`patches/**`, `media/file_isolation.py`, `api/**`, `admin-panel`, `docker/`.
`bench migrate` **çalıştırılmadı**. Şema değişikliği **yok**.

---

## 9. Kabul kriteri karşılığı

| Görev | Kaynağın kabul kriteri | Durum |
|---|---|---|
| **T-017** | *"`fixtures/malicious/` içindeki HER dosya reddediliyor, hiçbiri tam decode edilmiyor"* | ✅ **KARŞILANDI** — 10/10 RED (iki yolda da) [Ö]; bomba `Image.load` çağrılmadan reddediliyor [T] |
| **T-131** | SVG script/foreignObject/harici referans vektörleri gerçek dosyalarla sınanır | ✅ 26 vektör + 3 RET vektörü + 130 gerçek SVG [T]. **CSP ayağı: ÖLÇÜLMEDİ (yasak alan)** |
| **T-025** | Eşikler gerçek korpusta ölçülür ve kalibre edilir | ⚠ **KISMİ** — 6 kuralın tetiklenme oranı 1.291 canlı görselde ÖLÇÜLDÜ; **kalibrasyon yapılamadı** (insan etiketi yok), 2 kural hiç ölçülemedi (OCR/vision aracı yok). Eşikler DEĞİŞMEDİ. |

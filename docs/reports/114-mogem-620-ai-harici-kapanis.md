# MOGEM-620 · AI arama katmanı hariç kalan tüm maddelerin kapanışı

**Tarih:** 10 Eylül 2026
**Kapsam:** MOGEM-620'nin AI/semantik arama katmanı DIŞINDA kalan 14 açık kalemi
**Durum:** kodlandı, test edildi, tarayıcıda doğrulandı — **commit EDİLMEDİ**

---

## 1. Başlangıç durumu

10 Eylül denetimi şartnamenin 18 işlevsel bölümünü ve 20 kabul kriterini koda
karşı satır satır karşılaştırdı. AI katmanı hariç tutulduğunda 14 kalem açıktı.

En kritik bulgu bir mantık hatası **değildi**:

> `media/audio_meta.py` yazılmıştı, 81 testi vardı, hepsi yeşildi — ama
> `apply` ve `backfill_pending` fonksiyonlarının **hiçbir çağıranı yoktu**.
> Kod doğruydu, kablo yoktu. Canlıda bir `.mp3` yüklendiğinde başlık,
> sanatçı, süre ve kapak hiç çıkarılmıyordu; `AudioObject` boş kalıyordu.

Testlerin hiçbiri bunu göremiyordu çünkü hepsi fonksiyonu doğrudan çağırıyordu.
Bu, teslimatın en pahalı hata sınıfı: "yazıldı, test edildi, çalışmıyor."

---

## 2. Yapılanlar

### 2.1 Kablolar (§15)

| Ne | Nerede |
|---|---|
| `audio_meta.maybe_extract_on_insert` | `hooks.py` → `File.after_insert` |
| `audio_meta.backfill_pending` | `hooks.py` → `scheduler_events.daily` |
| `doc_meta.backfill_docs` | `hooks.py` → `scheduler_events.daily` |

`backfill_docs` zamanlanmamıştı: `after_insert` yalnız BUNDAN SONRAKİ
yüklemeleri kapsıyor, kanca yazılmadan önce yüklenmiş 14 PDF'in tamamında
`extracted_text` boştu.

**Bu değişiklik testleri kırdı ve doğrusu buydu.** Kanca takılınca canlı worker
test ile aynı `File` satırına dokunup `Lock wait timeout` üretti. Çözüm kancayı
geri almak değil, testi kuyruk durumundan bağımsız kılmak oldu:
`tests/zenginlestirme_notr.py` (`av_notr.py` deseninin birebir kardeşi).

### 2.2 Arama (§16)

`inventory` serbest araması yalnız **başlık + etiket + kategori adı + dosya
adı**na bakıyordu. Şartname "filename, full-text, metadata, OCR, transcript"
istiyor ve o metinler zaten `th_media_extracted_text` / `th_media_transcript`
sütunlarında duruyordu — veri vardı, kapı yoktu.

Arama artık şu sütunları kapsıyor (dil ekli olanlar dört dile açılıyor):
`title`, `alt`, `caption`, `description`, `transcript` (+`_tr/_en/_ar/_ru`),
`tags`, `artist`, `creator`, `credit_text`, `keywords`, `entities`,
`extracted_text`.

`th_media_alt_ai` **bilerek dışarıda**: onaylanmamış AI çıktısı yayımlanmadığı
gibi aranabilir de olmamalı.

> **E2E testi bir kusur daha yakaladı:** `description` bu turda `SINGLE`'dan
> `ASSET_TRANSLATABLE`'a taşındı, yani gerçek değer artık
> `th_media_description_tr`'de. Yalnız taban kolonu aramak, açıklama aramasını
> sessizce çalışmaz hâle getiriyordu.

### 2.3 Görsel benzerlik (§16)

`pipeline/core/dedup.dhash` + `find_similar` **yazılmıştı ve doğruydu**,
`Media Asset.perceptual_hash` **doluyordu**, ama hiçbir uç ikisini
bağlamıyordu. `api/advanced_search.visual_search` adında bir uç vardı ama
gövdesi baştan sona yorum satırıydı (Elasticsearch k-NN taslağı).

Yeni: `media/similar.py` + iki uç (satıcı kapsamlı / yönetici kapsamsız).
Kiracı sınırı opsiyonel değil — sınırsız çalışan bir benzerlik araması
satıcı A'ya satıcı B'nin ürün fotoğrafını gösterir.

### 2.4 Toplu işlemler (§14)

`bulk_ops.py`: görünürlük/index, telif/lisans/künye, desene göre yeniden
adlandırma + kategori bağı kaldırma. Panelde `MediaBulkFieldsModal.vue`.

**Yeniden adlandırma `file_url`'i DEĞİŞTİRMEZ** — kabul kriteri "metadata ve
filename değişiklikleri Stable Asset ID'yi bozmaz". Adresi de değiştiren iş
`retro_rename` ve 301 köprüsü kuruyor.

`canonical`/`slug`/`seo_filename` toplu yazılamaz ve bu **kasıtlı asimetri**:
üçü de her dosyada benzersiz olmak zorunda, 200 dosyaya aynı kanonik adresi
yazmak çakışma demek. Beyaz liste dışı alan **sessizce düşmüyor**, hata veriyor.

### 2.5 Denetim: on alt skor (§13)

`DIMENSIONS` sekizden ona çıktı: `visual_search` ve `ai_readiness`.

İkisi de **mevcut alanlardan türetiliyor**, yeni kolon ya da model çağrısı yok —
§10'un son maddesi "GEO/LLMO keyword veya AEO score gibi YAPAY alanlar yerine
mevcut asset'in makinece anlaşılmasını sağlayan ortak veri modeli" diyor.

İki boyuta **yeni uyarı kuralı eklenmedi**: §13'ün saydığı bulgu listesinin
tamamı zaten karşılanıyordu; her varlıkta patlayan iki yeni kural denetim
listesini şartnamede istenmeyen gürültüyle doldururdu.

### 2.6 Çözme maliyeti (§9)

`decode_cost.py` — şartnamenin dört bileşeninden eksik olanı. `decode` kelimesi
kod tabanının tamamında geçmiyordu.

Neden bayt yetmiyor: AVIF aynı görseli JPEG'in yarısı baytta taşır ama çözmesi
~2,6 kat pahalı. Yalnız bayta bakan denetim "AVIF'e geç" der, düşük uçlu
telefonda LCP'nin kötüleştiğini göremez.

### 2.7 Alan seti (§2/§5/§11/§12/§17)

`patches/v15_9_54` — 27 yeni `File` kolonu + `Listing.gtin` +
`Listing Variant Item.variant_gtin` + `Listing Image.media_role`.

- **§11:** `description`/`transcript`/`captions_url` dört dile açıldı
  (`ASSET_TRANSLATABLE`). Kullanım başına ezilebilir üçlü (`alt`/`title`/
  `caption`) bilerek büyümedi. Dile özel medya ezmesi: `Media Locale Variant`.
- **§12:** varyantlı ürün artık `Product` değil **`ProductGroup`**; her varyant
  bir `Product`. Kimliksiz (SKU/GTIN'siz) varyant şemaya girmiyor.
- **§5:** `chapters` → `Clip` listesi (Key Moments), `regionsAllowed`,
  `contentRating`, `isFamilyFriendly`.
- **§17:** `tags_source.py` — etiket → kaynak eşlemesi. `th_media_tags`'ın
  şekli DEĞİŞMEDİ: altı ayrı yerden okunuyor ve şeklini değiştirmek altısını
  birden kırardı.

### 2.8 Akış kotaları (§18)

Yalnız depolama kotası vardı. `media/meter.py` + `Media Usage Meter` +
`patches/v15_9_55`: bant genişliği, dönüşüm, AI çağrısı.

Depolama bir **durum** (`SUM(file_size)` her seferinde yeniden hesaplanabilir),
bunlar **akış** — olay anında sayılmazsa kaybolur.

Bağlandığı yerler: dönüşüm → `pipeline_bridge` (kuyruk kapısı + sayaç),
bant genişliği → `media_access` (imza kapısı + teslim sayacı), AI →
`moderation` (OpenAI Vision çağrısı).

---

## 3. Bulunan ve düzeltilen kusurlar

Testler yazılırken **8 gerçek kusur** çıktı — hiçbiri planlanmış iş değildi.

| # | Kusur | Nasıl bulundu |
|---|---|---|
| 1 | Ses çıkarımının hiçbir çağıranı yok | Denetim |
| 2 | `doc_meta.backfill_docs` zamanlanmamış | Denetim |
| 3 | Arama `description`ın dil kolonlarını görmüyor | E2E testi |
| 4 | `Media Locale Variant` tekillik kontrolü NULL mağazada delik | Fonksiyonel test |
| 5 | `_iso8601_sure` sonsuz sürede `OverflowError` — VideoObject'in TAMAMI düşüyor | Fuzz |
| 6 | `_chapters` `int(float("inf"))` aynı sınıf | Fuzz |
| 7 | `meter.limit_for` sayısal olmayan plan değerinde çöküyor | Fuzz |
| 8 | `_yerellestirme_puani` sözlük olmayan `localized`da `AttributeError` (F-18a'nın kardeşi) | Fuzz |

Ayrıca panelde, MOGEM-620 kapsamı dışında ama konsola düşen bir kusur:
`AppHeader` breadcrumb'ı düz Türkçe metni `t()`ye veriyordu ve intlify her
sayfada uyarı basıyordu (ölçüldü: medya kütüphanesi açılışında 240 uyarı).
`media.filters.dateFrom`/`dateTo` anahtarları da hiçbir dilde yoktu.

---

## 4. Test paketi

Altı yeni backend modülü, **206 test**:

| Modül | Test | Ne ölçüyor |
|---|---|---|
| `test_mogem620_fonksiyonel` | 98 | Her yeni modülün sözleşmesi |
| `test_mogem620_permutasyon` | 21 | Çarpım uzayı (skor alt kümeleri, dil kombinasyonları, 8×3 görünürlük, 5×5 kaynak geçişi, 10×2×2 format) |
| `test_mogem620_yetki` | 18 | Rol kapısı, kiracı izolasyonu, yetki yükseltmesi yok |
| `test_mogem620_duman` | 23 | **Kablolar takılı mı** — 1 numaralı kusurun sınıfı |
| `test_mogem620_maymun` | 23 | Fuzz — 4 kusuru bu buldu |
| `test_mogem620_e2e` | 23 | Kabul kriterlerinin uçtan uca karşılığı |

Panel tarafı: `mediaBulkFields.test.js` (26 test) + `mediaAxe.test.js`e iki yeni
WCAG yüzeyi.

**Yetki testlerinde kritik not:** `frappe.only_for` testte devre dışı
(`frappe/__init__.py:954`). Bu tuzak 6 Eylül'de neredeyse sahte bir güvenlik
açığı raporuna yol açmıştı. Her rol reddi `gercek_yetki()` sarmalayıcısı içinde
ve `TestNobetci` sınıfı sarmalayıcının kendisini sınıyor.

---

## 5. Tarayıcı doğrulaması

Playwright + sunucu tarafı sid (memory `panel-rwd-denetim-yontemi` deseni),
gerçek satıcı oturumu (`bursevplastik@istoc.com`, 1.189 dosya):

```
✓ kütüphane render oldu (appLen=153477)     ✓ modal açıldı
✓ 12 medya kartı                            ✓ odak modalın içinde (WCAG 2.4.3)
✓ toplu işlem çubuğu göründü                ✓ 25 Tab sonrası odak hâlâ modalda (2.1.2)
✓ toplu düzenle düğmesi                     ✓ tüm hedefler ≥44px (2.5.5)
✓ desen önizlemesi: test-01.png             ✓ Esc modalı kapattı
✓ bildirim: "2 dosya güncellendi"           ✓ 320/375/768/1024/1440 taşma yok
✓ yazılan değer SUNUCUDA aranabiliyor (2 dosya)
--- konsol HATA: 0
```

Son satır asıl kanıt: ekrandaki "başarılı" bildirimi istemcide üretiliyor ve
sunucu hiçbir şey yazmamış olabilir. Yazma sonrası değer sunucudan geri
okundu — ve bu aynı anda genişletilmiş aramanın da canlıda çalıştığını
gösteriyor (`creator` yeni aranan sütunlardan biri).

---

## 6. Bilerek yapılmayanlar

1. **AI/semantik arama katmanı** — istenen kapsam dışı. Vektör gömme, doğal
   dil sorgusu, otomatik ALT üretimi bu turda yok. `visual_search` boyutu
   AI'sız (algısal hash) çalışıyor.
2. **Medya motoru bayrağı açılmadı.** `media_pipeline_enabled` varsayılan `0`.
   §1 EXIF kasası, §4'ün tamamı (AVIF/WebP türevleri, LQIP, akıllı kırpma) ve
   §5 HLS bu bayrağın arkasında — **kodları var, canlıda çalışmıyor**.
   Bayrağı açmak bir ürün/kapasite kararı ve bu turun işi değil.
3. **Arka planda kaldırma (§4)** — hiçbir kütüphane yok, yeni bağımlılık
   kararı gerektiriyor.
4. **Doküman önizleme/thumbnail (§15)** — `pdftoppm` konteynerde kurulu değil
   (rapor 113 envanteri).
5. **Bant genişliği kotası imzalı indirme ucunda UYGULANMIYOR**, yalnız
   ölçülüyor. Kapı bağlantının VERİLDİĞİ yerde (`get_signed_url`); verilmiş bir
   imzayı sonradan 403'e çevirmek kullanıcının önündeki sayfayı kırar.

---

## 7. Sıradaki iş

- **Commit ve PR** — bu turda hiçbir şey commit edilmedi.
- Medya motoru bayrağı için kapasite ölçümü (§4/§5'in kalanı ona bağlı).
- `alt_ai` onay akışı — kolon var, akış yok (rapor 113 bulgusu). AI katmanı
  açılırsa Faz 0'ın parçası.

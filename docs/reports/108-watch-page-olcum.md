# 108 — Watch page slug backfill + ölçüm (Task 6)

**Tarih:** 2026-08-27
**Ortam:** `istoc-dev-backend-1`, site `istoc.localhost` (yerel dev).
**Kapsam:** 2026-08-26 medya-watch-page görev setinin Task 6'sı — panel slug
alanı + `missing_watch_slug` denetim kuralı + `watch_slug.backfill_slugs`
koşusu + gerçek envanter ölçümü. Sayfa bazlı SEO skoru/karnesi bu dilimin
kapsamı dışında — yalnız slug/watch-indexability envanteri.

Yöntem (rapor 106/107/98 ile aynı kısıt): `docker cp` ile konteynere taşınan
tek seferlik script, `bench --site istoc.localhost console` içine
`exec(open('/tmp/measure_108.py').read())` ile beslendi (çok satırlı döngüler
console stdin pipe'ında bozulduğu için). Backfill koşusu ayrıca
`bench --site istoc.localhost execute tradehub_core.media.watch_slug.
backfill_slugs --kwargs "{'limit': 500}"` ile ayrı çalıştırıldı.

---

## 1. Backfill koşusu

```
$ bench --site istoc.localhost execute tradehub_core.media.watch_slug.backfill_slugs --kwargs "{'limit': 500}"
5

$ bench --site istoc.localhost execute tradehub_core.media.watch_slug.backfill_slugs --kwargs "{'limit': 500}"
(çıktı yok — 0 aday kaldı)
```

İlk koşu **5** posterli-ama-slug'sız videoyu işledi. İkinci koşu **0**
döndürdü (çıktı boş) — aday havuzu tükendi, fonksiyon idempotent
(`backfill_slugs` docstring'i: "işlenen aday sayısı" döner, tekrar
çağrıldığında iş kalmayınca sessizce 0'a düşer).

---

## 2. Envanter — gerçek sorgu çıktıları (backfill sonrası)

| Ölçü | Değer |
|---|---:|
| Toplam public video `File` satırı (`is_private=0`, video uzantılı) | **140** |
| **— bunlardan gerçek katalog videosu (test artığı hariç, bkz. §2.1)** | **6** |
| Poster'lı (backfill'in aday havuzu — `th_media_poster_url` dolu) | **6** |
| Şu an slug'lı `File` satırı (`th_media_slug` dolu) | **9** |
| Posterli ama hâlâ slug'sız kalan (`backfill`'in artığı) | **0** |
| Distinct slug sayısı | **6** |
| Slug'lı distinct adres sayısı | **6** |

`slugli_video_satiri` (9) ile `distinct_slug_sayisi` (6) arasındaki fark
**kardeş kayıtlar** — `watch_slug` deseni (`_kardes_kayitlar`) aynı
`file_url`'e işaret eden birden çok `File` satırına AYNI slug'ı yazıyor;
3 satır kardeş paylaşımından geliyor, çakışma değil.

`posterli_slugsuz_kalan = 0`, ilk backfill koşusunun (`islenen=5`) o anki
aday havuzunun (6) 5'ini işleyip 1'inin zaten önceden slug'lı olduğunu
(muhtemelen daha önceki test/görev koşularından kalan) doğruluyor — ikinci
koşunun 0 dönmesiyle tutarlı.

### 2.1 Dipnot — 106 baseline'ından (114) sapmanın nedeni

**Düzeltme turu 1 (görev denetimi, 1 Important).** "140" ile rapor 106'nın
"114"ü arasındaki **+26** fark **tamamen `Administrator` sahipli test
artığından geliyor — gerçek katalog videosu her iki ölçümde de AYNI 6 dosya,
sıfır büyüme.**

Ölçüm (`docker cp` + `bench console` ile, salt-okunur `SELECT`):

| Ölçü | Değer |
|---|---:|
| Toplam public video satırı (şimdi) | 141 (bu dipnotun yazıldığı an — §2 tablosundaki 140'tan 1 fazla; aradaki tek satır rapor gövdesindeki ölçümden SONRA çalıştırılan `test_media_video_seo` regresyon koşusunun bıraktığı artık, aşağıda açıklanıyor) |
| `owner = 'Administrator'` olan satır | **135** |
| `owner != 'Administrator'` olan satır (gerçek satıcı hesapları) | **6** |
| Bu 6 satırın poster'lı olanı | **6/6** — yani `poster_var` havuzunun (§2) TAMAMI bu 6 satır |
| `2026-08-26 12:00`'dan SONRA oluşan public video satırı | **49** (hepsi `Administrator` sahipli) |

Sahiplik kırılımı **iddiayı doğrudan doğruluyor**: sistemdeki 6 poster'lı
video ile 6 `Administrator`-dışı (gerçek satıcı hesabı) video **birebir aynı
küme** — dosya adı/sahip/`creation` eşleşmesiyle doğrulandı
(`AQPp_3LT54pJF...mp4` → `timexplastik@istoc.com`, 2026-07-21;
`10 (1).mp4` → `cetinplastik@istoc.com`, 2026-07-23; `Evde taze sıkılmış...
Avcılar Plastik...mp4` ve `AQOOb74v4bIRU...mp4` → `avcilarplastik@istoc.com`,
2026-07-28; iki adet `9mb.mp4` → `ali.bal@turksab.com` (2026-08-13) ve
`bora.aydeger@turksab.com` (2026-08-20)). Bu 6 dosyanın TAMAMI 106'nın
yazıldığı günden (2026-08-26) ÖNCE yüklenmiş — 106'nın "114"ü ve 108'in
"140"ı **aynı 6 gerçek videoyu** taşıyor, aralarında tek bir yeni katalog
videosu yok.

Kalan **135** satırın (140 - 6 - 1 tutarsızlık ≈ 134 106 zamanında, 135 şu
an) tamamı tanınabilir test/fixture adları taşıyor ve `Administrator`
sahipli: `kisa-video-2.mp4`, `api-yonetici-video.mp4`,
`inv-video-status-<hex>.mp4`, `paylasilan-adres(-2).mp4`,
`api-satici-video.mp4`, `supur-video.mp4`, `toplama-a/b.mp4`,
`retry-sayac-1.mp4`, `e2e-video.mp4`, `watch-url-tam.webm` (bu SONUNCUSU bu
görev setinin kendi Task 4 testinden — `TestListingDetailVideoWatchUrl`,
`test_media_watch.py` — **4 kez tekrarlanmış artık kalıntısı**, aynı
`file_name`+`th_media_slug` ile 2026-08-27 00:55/01:33/01:34/01:44'te ayrı
ayrı oluşmuş; `addCleanup(doc.delete, ...)` kayıtlıydı ama satırlar hâlâ
DB'de — bu proje/konteynerin test rejiminde (`bench run-tests`) döngü içi
`File` kayıtlarının transaction rollback ile değil elle `delete()` ile
temizlenmesine dayanan, bilinen ve bu görevden ÖNCE de var olan bir kalıntı
deseni; kök nedeni bu düzeltme turunun kapsamı DIŞINDA, dokunulmadı).

**106'nın kendisi de zaten test artığı içeriyordu** — 106'nın "114" satırının
114-6=108'i o günkü (2026-08-26'dan önceki, `feature/media-video-seo`
dalının kendi Task 1-9 test döngülerinden kalma) `Administrator` artığıydı.
Aradaki net büyüme **108 → 135 = +27** (bu dipnotun ölçtüğü an) / **108 → 134
= +26** (§2 tablosunun "140" ölçüldüğü an, bu görevin kendi
`test_media_watch`/`test_media_seo_pipeline`/`test_media_video_seo`
regresyon koşularının EKLEDİĞİ satırlar dahil) — yani **+26/+27'nin
tamamı, bu görev setinin (Task 1-6) ve önceki `media-video-seo` dalının
test paketlerinin GÜN İÇİNDE tekrar tekrar çalıştırılmasından** birikti,
tek bir satırı bile gerçek/yeni katalog içeriği değil.

**Sonuç:** §2-§5'teki TÜM downstream ölçümler (poster, slug, `watch_indexable`,
`missing_watch_slug`) zaten yalnız bu **6 gerçek** video üzerinden hesaplanıyor
— test artığının hiçbirinde poster/slug yok, hiçbiri `backfill_slugs`'ın
aday havuzuna girmedi. Yani +26/+27'lik sapma **raporun asıl bulgularını
DEĞİŞTİRMİYOR**, yalnız "toplam public video satırı" metriğinin kendisi bu
ortamda katalog boyutunu değil, dev veritabanının test-kirliliğini ölçüyor
— bu iki rapor arasında (ve muhtemelen bundan sonraki her ölçümde) böyle
kalacak, konteyner sıfırlanmadıkça.

---

## 3. `watch_indexable` — W3 üçlüsü (indexability + poster + vitrin bağı)

| Ölçü | Değer |
|---|---:|
| Slug'lı distinct video adresi | 6 |
| `watch_indexable(url) == True` | **4** |

4/6 slug'lı video, W3 üçlüsünün tamamını (arama motoruna açık + poster var +
vitrinde görünen bir ilana bağlı) sağlıyor — yani **/medya/v/&lt;slug&gt;**
sayfası bu 4 adres için indexlenebilir durumda. Kalan 2'si ya postersiz ya da
hiçbir vitrin ilanına bağlı değil (W3'ün eksik kaldığı taraf bu ölçümde ayrıca
kırılmadı — kapsam dışı, `watch_indexable` zaten üçünü TEK karar noktasında
birleştiriyor).

Örnek indexlenebilir slug'lar (ilk 4):

```
aqoob74v4biruoaq3zdxz8iod-vxxpuf8s5zqg0ch1roth5lezh01smta1uljldiaeigep2uqqkyikuwbhcdmksgr-vropys
evde-taze-sikilmis-meyve-sularinin-keyfini-cikarin-avcilar-plastik-estetik-tasarimli-limon
9mb
aqpp-3lt54pjfuimtjmpvcibnnrtsv5sx18x1mprogktfdyrpoijrqtjs3sy1hfgshtcskcsjus5tki7v-mrwrad
```

---

## 4. `missing_watch_slug` denetim kuralı — gerçek koşum

`posterli_slugsuz_kalan = 0` olduğu için, denetlenecek aday havuzu da **0**:

| Ölçü | Değer |
|---|---:|
| Posterli + slug'sız (denetim adayı) | 0 |
| `missing_watch_slug` WARN üreten | 0 |

Bu **beklenen** sonuç — backfill koşusu az önce tam da bu havuzu boşalttı.
Kuralın gerçekten çalıştığı `tradehub_core/tests/test_media_watch.py::
TestMissingWatchSlugAudit` içinde senkron olarak doğrulandı (posterli +
vitrine bağlı + slug'sız fixture videosu → WARN; slug'lı, postersiz ya da
görsel dosyada → bulgu YOK; `audit_batch(deep=True)`'te de bilerek YOK —
§6'da gerekçesi).

---

## 5. Örnek sayfa — HTTP + JSON-LD kanıtı

Seçilen slug: `aqoob74v4biruoaq3zdxz8iod-vxxpuf8s5zqg0ch1roth5lezh01smta1uljldiaeigep2uqqkyikuwbhcdmksgr-vropys`
(watch_indexable=True örneklerinden ilki).

### 5.1 `get_watch_page` (JSON sözleşmesi)

```json
{
  "indexable": true,
  "canonical": "http://istoc.localhost/medya/v/aqoob74v4biruoaq3zdxz8iod-...-vropys",
  "robots": "index, follow, max-image-preview:large, max-video-preview:-1",
  "sources_count": 1,
  "listings_count": 1
}
```

### 5.2 `page_resolver.render_media_watch(slug)` — doğrudan test istemcisi

> Konteynerde nginx/gateway `/medya/v/<slug>` yolunu wire etmiyor (`curl` bu
> yoldan **000/417** dönüyor — dinamik izleme sayfası rota eşlemesi
> vitrin/storefront tarafında, `tradehub_core` repo'sunun kapsamı dışında ve
> `page_resolver.py` KORUNAN dosya listesinde, bu görevde dokunulmadı).
> Görev talimatının kendi fallback'i izlendi: **resolver doğrudan test
> istemcisiyle** çağrıldı (`TestRenderMediaWatch` testlerinin de yaptığı
> aynı yöntem).

```
status_code:        200
has_canonical_tag:  true
has_videoobject:    true   ("@type": "VideoObject")
has_seektoaction:   true   ("@type": "SeekToAction")
content_length:     2753 bayt
```

Üç kanıt (JSON sözleşmesi, resolver HTML'i, `TestRenderMediaWatch`'ın önceden
geçen testleri) aynı sonucu veriyor: seçilen video sayfası indexlenebilir,
canonical doğru, VideoObject + SeekToAction JSON-LD üretiliyor.

---

## 6. Bilinen artıklar (düzeltme turu 1)

Rapor 107'nin §4 deseniyle aynı: bu ölçümün "temiz olmayan" tarafı gizlenmiyor,
adı konup burada listeleniyor.

- **135 `Administrator`-sahipli test-fixture `File` satırı** — §2.1'de tam
  döküm ve kanıt zinciri var. Hiçbiri poster/slug taşımıyor, hiçbiri §2-§5'in
  ölçtüğü hiçbir sayıyı ETKİLEMİYOR (backfill/watch_indexable/missing_watch_slug
  hepsi zaten yalnız 6 gerçek video üzerinden hesaplanıyor).
- Bunlardan **4 tanesi** (`watch-url-tam.webm`, `th_media_slug=watch-url-tam-slug`)
  bu görev setinin KENDİ `test_media_watch.py::TestListingDetailVideoWatchUrl`
  testinden — `addCleanup` kayıtlı olmasına rağmen satırlar DB'de kalmış;
  bu görevin (Task 6) test dosyasına eklediğim `TestMissingWatchSlugAudit`/
  `TestChangeWatchSlugEndpoint` testleri KENDİ fixture'larını (`mws-*`,
  `cws-*` önekli) düzgün temizliyor — 36/36 koşu sonrası bu önekli TEK satır
  bile DB'de kalmadı (ayrıca doğrulandı, aşağıda). Sorun Task 4'ün ÖNCEDEN
  yazılmış testinde, bu düzeltme turunun kapsamı dışında bırakıldı.
- Kök neden araştırılmadı (kapsam dışı) ama gözlem: bu konteynerde
  `bench run-tests` çalıştırıldığında bazı `File` kayıtları test sonunda
  ROLLBACK edilmiyor gibi görünüyor (`FrappeTestCase`'in normal davranışı
  transaction'ı geri almaktır) — muhtemelen bu test dosyalarının bazı
  yollarının `enqueue_after_commit=True`/gerçek commit gerektiren bir
  bağlama girmesi. Doğrulanmadı, yalnız gözlem olarak not düşülüyor.

---

## 7. Öz-denetim

- **Tüm sayılar gerçek sorgu çıktısı** — `docker cp` ile taşınan
  `/tmp/measure_108.py` script'i `mariadb`/`frappe` API'lerini (`frappe.db.sql`,
  `watch_indexable`, `seo_audit.audit_file`, `page_resolver.render_media_watch`)
  çağırdı; tahmini/yuvarlanmış değer yok.
- **`missing_watch_slug` kuralının `audit_batch`'e EKLENMEME kararı** —
  gerekçe: `_baglamsal_bulgular` hem `audit_file` hem `audit_batch`'in
  `deep=True` dalında paylaşılan tek fonksiyon; `watch_indexable` üç ayrı
  sorgu açıyor (`seo_index.decide` + `seo.fields_for` + `_storefront_listings`
  join'i). Toplu denetim yüzlerce/binlerce dosyayı tek istekte tarıyor
  (`audit_scope`/`audit_batch` docstring'i: "3.200 dosya 2,2 s" gibi bütçeler
  taşıyor); bu üçlüyü N dosya için N kez tetiklemek o bütçeyi bozardı. Kural
  bu yüzden `seo_audit.py::_watch_slug_bulgusu` adında AYRI bir fonksiyona
  yazıldı ve yalnız `audit_file`'ın (tekil, panelin "Düzenle" çekmecesi
  açıldığında çağrılan) gövdesine eklendi — `audit_fields`'ın saf/DB'siz
  imzası hiç değişmedi. `TestMissingWatchSlugAudit.test_toplu_denetimde_
  calismaz` bu sınırı doğrudan test ediyor.
- **HTTP kanıtı sınırı açıkça işaretlendi** — konteyner nginx'i `/medya/v/`
  yolunu bu ortamda routelamıyor (§5.2); görev talimatının kendi fallback'i
  (resolver'ı doğrudan test istemcisiyle çağırmak) izlendi, gizlenmedi.
- **"Önce" durumu** kısmen yeniden üretildi: ilk `backfill_slugs` koşusunun
  dönüş değeri (`5`) o anki aday sayısını, ikinci koşunun `0` dönmesi
  havuzun tükendiğini kanıtlıyor — bağımsız bir "önce" tablosu snapshot'ı
  alınmadı (backfill ölçümden ÖNCE çalıştırıldığı için), bu açıkça
  belirtiliyor, gizli varsayım yok.
- **Yazma disiplini:** Ölçüm script'i yalnız `SELECT`/`get_value`/salt-okunur
  API çağırdı; tek yazma işlemi görevin kendisi olan `backfill_slugs`
  koşusuydu (görev tanımının istediği adım). `git add`/commit YAPILMADI.
- Testler: `bench run-tests --module tradehub_core.tests.test_media_watch`
  → **36/36** (27 mevcut Task 1-4 testi + 9 yeni: `TestMissingWatchSlugAudit`
  6 + `TestChangeWatchSlugEndpoint` 3 — detay `task-6-report.md`);
  `test_media_seo_pipeline` regresyon → **39/39**.

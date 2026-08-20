# 71 · W3D — Öksüz dosya raporu (T-043'ün ikinci yarısı)

**Tarih:** 2026-08-20 · **Kapsam:** `list_orphans` satıcı ucu + `MediaFilterRail` öksüz bölümü · **Şartname:** `~/Desktop/imageoptimization/docs/41-faz4-veri-modeli.html` (T-043: "Hiçbir Usage kaydı olmayan ve N gün eski asset'ler 'öksüz' raporunda listeleniyor. Öksüz asset otomatik silinmiyor.")

Başlangıç ölçümü (denetim 61c ile uyumlu): whitelist yüzeyinde öksüz ucu yok
(`grep -rn "orphan" tradehub_core/api/` → 0 uç), panelde öksüz ekranı yok.
Kullanım paneli (`MediaUsagePanel` → `get_my_usage`) var ve tarama sınırını
ekranda ilan ediyor (`media.usage.scanNote`).

Bu iş bilinçli olarak **GÖRÜNÜRLÜK** işi, silme işi değil: rapor 57'de
kullanım koruması GC yolunun yarısına bağlı çıktı ve 3.821 dosya silinme
sınırına geldi. `list_orphans` hiçbir şey silmez; silme mevcut çöp akışında
(`preview_release` → `archive_media` → `purge_media`) ve oradaki korumalar
aynen geçerli.

---

## 1. Uç — `tradehub_core.api.seller_media.list_orphans`

```python
@frappe.whitelist()
def list_orphans(days_unused: int = 30, start: int = 0, page_length: int = 50) -> dict
```

- Mağaza **parametre değil**, oturumdan (`_store()`) çözülür — modüldeki tüm
  uçlarla aynı kural (Payment Transaction dersinin devamı).
- `days_unused` 0–3650 aralığında zorlanır (`frappe.throw`), `page_length`
  1–200'e kırpılır (`inventory.MAX_PAGE_SIZE`).
- Dönen gövde:

```json
{
  "items": [{"file_url", "file_name", "file_size", "uploaded_at", "last_checked"}],
  "total": 4, "start": 0, "page_length": 50, "days_unused": 30,
  "scanned_at": "...",
  "scan": {"live_fields": 17, "order_fields": 5, "history_scanned": false, "failed_sources": []}
}
```

`scan` bloğu taramanın **neyi görmediğinin** makine okunur beyanı — ekran
notu (aşağıda) buna dayanır. `last_checked` = istek anındaki tarama damgası;
kalıcı bir kullanım dizini olmadığı için satır başına ayrı damga yoktur.

### Karar mantığı — kaynak listesi TEK, kopya yok

İş mantığı `media/usage.py`'de (`store_orphans`, `store_referenced_urls`).
Kaynak alanlar **`LIVE_SOURCES` + `ORDER_SOURCES` sabitlerinden okunur** —
`get_my_usage`/`verdicts_for` ile aynı liste; ikinci bir liste yazılmadı,
liste değişince öksüz kararı kendiliğinden değişir. Aday küme de satıcı
listesiyle aynı sorgudan (`inventory._base_query` + `ownership.scope`):
hassas doctype dışlaması ve content-hash emniyet kemeri ikinci kez yazılmadı.

İki katmanlı referans taraması:

| Katman | Alanlar | Tarama kapsamı | Gerekçe |
|---|---|---|---|
| Mağaza süzgeçli | `STORE_FILTERS`'ı olan 16 alan (ürün, varyant, vitrin, galeri, logo, sipariş…) | yalnız BU mağazanın kayıtları | kiracı izolasyonu — başka satıcının verisi ne okunur ne sayılır |
| Global | süzgeçsiz 6 alan (`Brand.logo`, `Brand.hero_banner`, `Product Category.image`, `Static Page SEO.og_image`, `Verification Source.icon`, `Buyer Favorite Item.snapshot_image`) | tüm kayıtlar | atlansaydı satıcının yüklediği ama platformun kullandığı görsel (T-029 tuzağı) "öksüz" görünürdü; satıcı bırakınca platformun sahiplik payı olmadığından dosya diskten gider, logo kırılırdı. Kiracı verisi sızmaz: sonuç yalnız "listede görünmeme"ye dönüşür |

`HISTORY_SOURCES` bilerek taranmıyor (geçmiş izi kullanım değil + 3,5 sn
maliyet ölçümü); `scan.history_scanned=false` ile beyan ediliyor. Çöpteki
dosyalar aday kümeye girmez (onlar zaten ayrı akışta). Tarama sorgusu hata
veren alan loglanır ve `scan.failed_sources`'a adıyla düşer — o alandaki
kullanım görünmediği için hatanın yönü "öksüz sanma"ya doğrudur, ekran
bunu göstermek zorundadır.

## 2. Tarama maliyeti — ölçüldü, toplu SQL seçildi

Ölçüm 2026-08-20, istoc.localhost (2.897 public URL; en büyük mağaza
SEL-00027, 750 URL):

| Yol | Maliyet | Ölçekleme |
|---|---|---|
| Dosya-başı (`verdicts_for`, deep=False, store) — N dosya × M alan LIKE | 750 URL: **99 ms** · 2.897 URL: **373 ms** | dosya sayısıyla BÜYÜR (400'lük chunk × 22 alan) |
| **Toplu ters tarama** (`store_referenced_urls`) — alan başına TEK `locate('/files/', kolon)` sorgusu | **9 ms** | alan sayısıyla sabit, dosya sayısından bağımsız |

Toplu yol seçildi (~40× fark, 3.000+ dosyalık mağazada makas daha da
açılır). Uçtan uca smoke: gerçek satıcı oturumuyla (`SEL-00027`,
`bursevplastik@istoc.com`) `list_orphans(days_unused=30)` → **68 ms**,
`total=4`, `failed_sources=[]`.

Sayfalama bellek içinde dilimlenir: öksüz kararı SQL'de üretilemiyor
(kaynaklar 10+ tabloya yayılı metin alanları) ve `total`'ın doğru olması
için tüm adayların kararı gerekir — `verdict_map_all` ile aynı gerekçe.
Mağaza başına aday küme küçük (ölçülen en büyük: 750 satır).

## 3. Ekran — `MediaFilterRail.vue`, gerekçesi

İki serbest seçenekten **`MediaFilterRail`** seçildi; `MediaAuditView`
elenmesinin sebebi teknik: o ekran `requiresSuperAdmin` rotasında ve uç
satıcı oturumu ister (`_store()`); mağazası olmayan süper-admin'e uç
`PermissionError` döner — rapor orada ya boş ya kırık olurdu. Öksüz raporu
satıcının kendi kütüphanesinin sorusudur ve ray zaten "yerim neye gidiyor"
bölgesini (depolama/kota) taşıyor; bölüm onun hemen altına kondu.

Sınır: rayın ebeveyni `MediaLibraryView.vue` bu işte YASAK dosya. Bu yüzden
"tıklayınca listeyi filtrele" davranışı (ebeveynde emit kablolaması
gerektirir) kurulamadı; onun yerine bölüm **kendi içinde açılır sayfalı
liste** taşır: sayaç + katlanır gövde (rayın mevcut akordiyon durumu,
`localStorage`'daki `media-rail-open` ile kalıcı). Bölüm kendi verisini
kendisi çeker (`useMediaOrphans` composable, açılışta tek istek — 9 ms uç);
ebeveyne yeni prop/emit eklenmedi. Kütüphane filtresine bağlamak istenirse
tek gereken, `MediaLibraryView`'da bir `quickView` tanımlayıp `usage_state`
filtresine bağlamak — ayrı bir iş.

Ekran davranışı (hepsi `useMediaUsage` sözleşmesiyle):

- **Sayaç dürüst:** cevap gelmeden `…`/`—` gösterir; `0` yalnız arka taraf
  yanıtlayınca basılır ("hata = temiz kütüphane" okunamaz).
- **Boş durum dürüst:** "Taranan kaynaklara göre {days} gündür kullanılmayan
  dosya yok." — "öksüz yok" DEMEZ.
- **Tarama sınırı notu ZORUNLU ve her durumda görünür** (`scanNote` deseni):
  kararın sabit listeden geldiği, listede olmayan alanın görünmediği, geçmiş
  izlerinin dahil olmadığı ve bunun bir silme listesi olmadığı yazar;
  `scan.failed_sources` doluysa okunamayan alan adları nota eklenir.
- Yaş eşiği seçilebilir (7/30/90/180 gün), "daha fazla göster" ile birikimli
  sayfalama, yetki reddi/arıza ayrı metinler, satırlarda işlem düğmesi YOK.

## 4. i18n anahtarları

Hepsi `t(anahtar, {...}, "TR varsayılan")` ile — **locale dosyalarına
dokunulmadı**, anahtar listesi çeviri ekibi için:

| Anahtar | TR varsayılan |
|---|---|
| `media.orphans.title` | Öksüz dosyalar |
| `media.orphans.threshold` | Yaş eşiği |
| `media.orphans.days` | {n} gün |
| `media.orphans.loading` | Taranıyor… |
| `media.orphans.denied` | Bu raporu görme yetkiniz yok. |
| `media.orphans.failed` | Öksüz taraması alınamadı. |
| `media.orphans.retry` | Yeniden dene |
| `media.orphans.notScanned` | Henüz taranmadı. |
| `media.orphans.empty` | Taranan kaynaklara göre {days} gündür kullanılmayan dosya yok. |
| `media.orphans.uploadedAt` | {date} yüklendi |
| `media.orphans.more` | Daha fazla göster ({shown}/{total}) |
| `media.orphans.scanNote` | Öksüz kararı kalıcı bir kullanım dizininden değil, istek anında taranan sabit bir kaynak listesinden geliyor. Kullanım taramasının görmediği bir alanda geçen dosya burada yanlışlıkla öksüz görünebilir; geçmiş izleri (sürüm, silinmiş kayıt) karara dahil değildir. Bu bir silme listesi değildir — silme, çöp akışındaki korumalardan geçer. |
| `media.orphans.scanFailed` | Bu taramada okunamayan alanlar: {fields}. |

## 5. Testler

**Backend** — `tradehub_core/tests/test_media_orphans.py` (yeni, konteynerde
`bench run-tests` ile): **11/11 yeşil** (6,8 sn).

- Öksüz doğru bulunuyor + satır sözleşmesi (`file_url/file_name/file_size/
  uploaded_at/last_checked`) + `scan` beyanı.
- Kullanılan dosya listede DEĞİL — kullanılan dosyanın yaşı da geri
  çekilerek (dışlanma sebebi yaş filtresi olmasın diye).
- Yeni yüklenen eşik dolmadan görünmez; eşik 0 olunca görünür (kabul
  kriteri: "yeni yüklenenlerin raporda çıkmaması").
- Çöpteki dosya listede değil.
- Platform alanında (Product Category.image) kullanılan dosya öksüz değil
  (global katman testi).
- Negatif eşik reddi.
- **Cross-tenant + vacuity:** B'nin öksüzü A'ya görünmüyor; aynı çağrıda
  `_store` B'ye çevrilince (kontrol gevşetilince) GÖRÜNÜYOR — yokluğun
  gerçekten mağaza bağından geldiği kanıtlı. Toplam sayı da sızdırmıyor
  (A'nın `total`'ı B'nin öksüzleriyle şişmiyor).
- Sayfalama: toplam korunur, sayfalar ayrışık, sıra deterministik (en eski
  önce), küme dışı sayfa boş ama `total` doğru.
- `store_referenced_urls` iki katmanı birden görüyor (süzgeçli + global).

**Frontend** — `src/composables/__tests__/mediaOrphans.test.js` (yeni,
`node --test`): **7/7 yeşil**. `useMediaUsage` sözleşmesi: cevapsızken
`total=null` ("öksüz yok" denemez), boş sonuç ancak cevapla, 403 ayrı bayrak,
arıza `total`'ı 0 yapmaz, sayfalama birikimli ve tükenince istek atmaz, eşik
değişimi sayfayı sıfırlar, `scan` beyanı yorumsuz taşınır.

**Regresyon:** `test_seller_media_browse` 12/12 · `test_media_trash_path`
4/4 · rayı mount eden `mediaProgressbarName.test.js` 5/5 ve
`mediaAxe.test.js` 4/4 (yeni bölüm dahil 0 engelleyici bulgu) ·
`npm run build` temiz.

## 6. Bilinen durum — bu işten bağımsız kırmızı

`test_media_usage_sources.test_kapsanmayan_alan_kalmadi` DEV sitesinde
kırmızı: kör-nokta süpürmesi `tabMedia Rendition.file_url`'i buldu. Sebep bu
iş değil — eşzamanlı çalışan boru hattı ajanı bugün 07:31'de 88 `Media
Rendition` satırı üretti ve kolon artık `/files/` taşıyor. Çözüm o ajanın
alanında: alan ya bir kaynak listesine ya `BILINCLI_DISARIDA`'ya (türev
tablosu — kullanım kaynağı değil, gerekçeyle) yazılmalı. Bu işte o dosyaya
dokunulmadı; öksüz raporu `tabFile` üzerinde çalışır ve rendition
tablolarına bakmaz, kararları etkilenmez.

## 7. Dokunulan dosyalar

| Dosya | İş |
|---|---|
| `tradehub_core/tradehub_core/media/usage.py` | `store_referenced_urls` + `store_orphans` (kaynak listeleri mevcut sabitlerden) |
| `tradehub_core/tradehub_core/api/seller_media.py` | `list_orphans` ucu (+ `cint` importu) |
| `tradehub_core/tradehub_core/tests/test_media_orphans.py` | yeni — 11 test |
| `admin-panel/frontend/src/composables/useMediaOrphans.js` | yeni composable |
| `admin-panel/frontend/src/components/media/MediaFilterRail.vue` | öksüz bölümü (depolamanın altı) |
| `admin-panel/frontend/src/composables/__tests__/mediaOrphans.test.js` | yeni — 7 test |

`hooks.py` / `patches.txt` / router / locale dosyalarına dokunulmadı;
şema değişikliği ve migrate gereği yok.

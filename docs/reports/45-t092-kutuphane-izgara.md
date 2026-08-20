# 45 — T-092 / T-094: Kütüphane ızgarası, filtre kalıcılığı ve toplu işlem dökümü

**Tarih:** 2026-08-19
**Depo / dal:** `admin-panel` · `ahmet`
**Görevler:** T-092 (ızgara, arama, filtre, sanal kaydırma) · T-094 (klasör/etiket organizasyonu + toplu işlemler)
**Kaynak kriter:** `imageoptimization/docs/60-faz9-media-library.html` — Faz 9

---

## 1. Özet

Bu tur **iki gerçek boşluğu** kapattı, bir iddiayı **ölçtü**, üçünü de kapsam dışı
bırakıp gerekçesini yazdı.

| # | İş | Durum |
|---|---|---|
| 1 | Filtre durumu adres çubuğunda (paylaşılabilir bağlantı, yenilemeye dayanıklı) | **Yapıldı** |
| 2 | Toplu işlemde kısmi sonuç bildirimi ("48 oldu, 2 olmadı, 3 atlandı") | **Yapıldı** |
| 3 | Kalıcı silme onayı artık `preview_release` ucundan doğrulanıyor | **Yapıldı** |
| 4 | Izgaranın DOM'a bastığı kalem sayısı | **Ölçüldü ve testle çakıldı** |
| 5 | Klasör ağacı + sürükle-bırak taşıma | **Yapılmadı** — arka tarafta karşılığı yok (§5.1) |
| 6 | `MediaFilters.vue` yeni bileşeni | **Yazılmadı** — gerekçe §5.2 |
| 7 | Ürüne göre arama (`search: product`) | **Yapılamaz** — istemcide veri yok (§5.3) |

**Doğrulama:** `npm run lint` → **EXIT 0** (yeni uyarı yok; kalan 2 uyarı
`views/permission/PlansTab.vue`'da, bu turdan önce vardı).
`npm run build` → **EXIT 0**.
`npm test` → **569 test, 569 geçti, 0 başarısız** (bu turun 28 yeni testi dâhil).

> Bu turun başında ölçülen taban 396/396 idi. Sayının 569'a çıkması bu turun
> işi değil: aynı anda çalışan kırpma stüdyosu ve simülatör ajanları kendi
> testlerini ekledi. Ara ölçümlerde onların dosyalarından gelen geçici
> başarısızlıklar görüldü, son koşuda hepsi kapandı.

---

## 2. Ölçülen gerçek: ızgara zaten şişmiyor, kanıtı da artık var

### 2.1 Ne ölçüldü

Faz 9 T-092 "10.000 varlıkta akıcı kaydırma" istiyor. Bu ekranda **sanal
kaydırma eklenmedi ve eklenmemeli** — ızgaranın kaynağı `stores/media.js`
içindeki `paged`, yani sayfa başına en çok **48 kayıt**. Toplam kaç kayıt
olursa olsun DOM'a basılan kart sayısı bu sınırın üstüne çıkamıyor.

Bu bir varsayım değil, artık **testle çakılı**:
`src/stores/__tests__/mediaLibraryGrid.test.js`

```
✔ 10.000 kayıtta bile ızgaranın kaynağı sayfa boyutunu aşmaz
✔ ızgara ŞABLONU gerçekten `paged` döner — sınır kaynakta da duruyor
```

Birinci test 10.000 kayıt yükleyip `filtered.length === 10000` iken
`paged.length`'in 12/24/48 sayfa boyutlarının her birinde tam o sayı
kaldığını doğruluyor. İkinci test bunu şablona bağlıyor: `MediaLibraryView`
kaynağındaki ızgara ve satır listesi bloklarının `v-for="… in paged"` yazdığını
düzenli ifadeyle kontrol ediyor. İki iddiayı birbirine bağlamak şart —
bağlanmasaydı bir sonraki düzenlemede `paged` yerine `filtered` yazılır ve
sınır sessizce kalkardı.

### 2.2 Ne ÖLÇÜLMEDİ

- **Süre, kare hızı, akıcılık.** Makine paylaşımlı, tarayıcı yok, düzen motoru
  yok. "Akıcı kaydırıyor" **demiyoruz**; "ızgaranın kaynağı sayfa boyutuyla
  sınırlı" diyoruz.
- **Gerçek DOM düğüm sayısı.** SSR bile kurulmadı; ölçülen, şablonun döndüğü
  liste. `MediaCard` başına kaç düğüm çıktığı bu turda ölçülmedi.

### 2.3 Sanal kaydırma nerede gerekli — ve orası benim dosyam değil

Şişme dosya listesinde değil **klasör seviyesinde**:
`tradehub_core/media/browse.py:744 seller_listings()` bir kategorideki bütün
ürün klasörlerini tek yanıtta döndürüyor, `folders` listesinde sayfalama yok.
Bunun çözümü bu turdan önce yazılmış (`useVirtualGrid.js` +
`MediaFolderGrid.vue`) ve kendi testleri var
(`composables/__tests__/virtualGrid.test.js`). O dosyalara **dokunulmadı**.

> Kalıcı çözüm istemcide değil: `seller_listings()` klasör listesine de
> `page`/`page_size` almalı. Pencereleme onun yerine geçmiyor, sadece
> tarayıcıyı ayakta tutuyor — yanıt yine bütün klasörleri taşıyor.

---

## 3. T-092 — Filtre durumu artık adres çubuğunda

### 3.1 Sorun

Faz 9 kabul kriteri: *"Filter state persists in URL; shareable and
back-button compatible."* Bu ekranda **hiç yoktu**. Filtre durumu yalnız
bellekteydi:

- Satıcı "kullanılmayan videolar" süzgecini kurup bağlantıyı ekibine
  gönderdiğinde karşı taraf **filtresiz** kütüphaneyi açıyordu.
- Sekme yenilenince kurulan beş tıklık süzgeç kayboluyordu.

### 3.2 Çözüm

Yeni saf modül: **`src/utils/mediaFilterUrl.js`** (Vue yok, router yok, DOM
yok). Yalnız çeviri yapıyor:

| Filtre tipi | Adres karşılığı | Örnek |
|---|---|---|
| `text` | düz metin | `fileName=kapak` |
| `select` | virgülle | `kind=video,image` |
| `range` | `min~max` | `bytes=0.5~5` |
| `date` | `from~to` | `uploadedAt=2026-01-01~2026-02-01` |
| sıralama | `alan:yön` | `sort=bytes:asc` |
| sayfa | `page`, `size` | `page=3&size=48` |

Bağlama `MediaLibraryView.vue` içinde, çift yönlü: ekran adresi, adres ekranı
besliyor.

**Döngü nasıl kırıldı:** bayrak/kilit kullanılmadı — bayrak async bir
gezinmede kilitli kalabiliyor, senkron olanı da sessizce ölüyor. Bunun yerine
her iki taraf da **yazmadan önce eşitliğe bakıyor** (`sameQuery`). Adres ile
ekran aynıysa hiçbir şey yazılmıyor.

**Karar defteri:**

- **`replace`, `push` değil.** Arama 300 ms gecikmeli de olsa her tuş
  vuruşunda yazıyor; `push` olsaydı tek kelimelik bir arama geçmişe on kayıt
  eklerdi ve geri tuşu sayfadan çıkamaz hâle gelirdi. **Sonucu açıkça
  yazıyorum:** paylaşılan bağlantı ve yenileme kayıpsız çalışıyor, ama geri
  tuşu filtre adımlarını **tek tek geri sarmıyor** — sayfadan çıkıyor. Faz 9'un
  "back-button compatible" ifadesi bu kadarıyla karşılandı.
- **Varsayılan yazılmıyor.** Filtresiz sayfa temiz adreste kalıyor; aksi hâlde
  her açılış uzun bir sorgu kuyruğuyla gelirdi.
- **Sayfa boyutu beyaz listeden.** `?size=100000` bütün kütüphaneyi tek sayfaya
  basardı — yani §2'deki tek koruma adres çubuğundan aşılabilir olurdu.
  Yalnız `[12, 24, 48]` kabul ediliyor.
- **Sıralama alanı beyaz listeden.** Bugün sonucu yalnız "sıralama olmaz", ama
  sıralama sunucuya taşındığında aynı değer sorguya girerdi.
- **Bozuk adres filtreyi hiç kurmuyor.** `bytes=abc~def` yok sayılıyor; elle
  düzenlenmiş bir bağlantı yüzünden kullanıcı boş kütüphane görmemeli.
- **Bize ait olmayan parametreler korunuyor** (`utm`, `ref` vb.).
- **Sayfadan çıkarken yazılmıyor.** Gezinme onaylandığında `route` yeni sayfayı
  gösterirken bileşen henüz sökülmemiş oluyor; o aralıkta medya filtreleri
  **başka bir sayfanın adresine** yazılabilirdi. `OWN_PATH` kontrolü bunu
  kapatıyor.

### 3.3 Yan düzeltme — `watch(dt.sorting, …)` artık `flush: "sync"`

`?sort=bytes:asc&page=3` bağlantısı hep 1. sayfayı açıyordu: adresten durum
kurulurken sıralama sayfadan önce yazılıyor, gecikmeli akışta sıralama→sayfa
sıfırlaması **sayfa yazıldıktan sonra** çalışıyordu. Kullanıcı etkileşimi
açısından fark yok — sıfırlama zaten aynı etkileşim içinde oluyordu.

---

## 4. T-094 — Toplu işlemler

### 4.1 Kısmi sonuç artık gizlenmiyor

**Bulgu:** `tradehub_core/api/seller_media.py` içindeki `_toplu()` iskeleti üç
şeyi ayrı ayrı döndürüyor:

```python
return {
    sayac_adi: len(basarili),   # archived / unarchived / purged
    "failed": hatali,           # [{file_url, error}]
    "skipped": atlanan,         # sahiplik kontrolünden düşenler
    "details": basarili,
}
```

Ekran bunlardan **yalnız ilkini** okuyordu; `failed` ve `skipped` atılıyordu.
Sonuç: 50 dosya seçilip arşivlendiğinde 2'si hata verse bile ekran
**"48 medya arşivlendi"** diyor, eksik kalan 2 dosyadan hiç söz etmiyordu.
Kullanıcı işlemin tamamlandığını sanıyordu. Faz 9 T-094 bunu açıkça istiyor:
*"bulk operations … with progress and partial-error reporting ('48 succeeded,
2 failed')"*.

**Çözüm:**

- `stores/media.js` → yeni **saf** fonksiyon `summarizeBulk(action, sonuc, counterKey)`
  yanıtı `{ ok, failed[], skipped, partial }` dökümüne çeviriyor. Saf olması
  kasıtlı: gerçek uç çağrılmadan test edilebilsin.
- `archiveMany` / `removeMany` / `purgeMany` artık çıplak sayı değil bu dökümü
  döndürüyor ve `store.bulkReport`'a yazıyor (yalnız eksik kalan varsa).
- `MediaBulkBar.vue` dökümü `role="alert"` ile gösteriyor: hangi dosyanın hangi
  hatayı verdiği (ilk 4'ü adıyla, gerisi sayıyla), atlanan sayısı ve elle
  kapatma. Döküm **seçim boşaldıktan sonra da** ekranda kalıyor — toplu işlem
  seçimi temizlediği için `selectedIds` koşuluna bağlansaydı liste tam
  yazıldığı anda kalkardı.
- `MediaLibraryView.reportBulk()` kısmi sonuçta **başarı bildirimi çıkarmıyor**;
  hata tonunda özet veriyor (`useToast`'ta uyarı tonu yok — "işlem bitti"
  izlenimi vermemesi başarı tonundan daha önemli).

Testler (`mediaLibraryGrid.test.js`), gerçek uç çağırmadan:

```
✔ kısmi sonuç: kaç oldu, kaç olmadı, kaç atlandı — üçü de taşınır
✔ her şey olduysa kısmi değildir — ekran sade başarı gösterir
✔ hiçbiri olmadıysa da kısmi sayılır — 'işlem tamam' denmez
✔ eksik ya da bozuk yanıtta sayı uydurulmaz
✔ boş seçimde toplu işlem uca GİTMEZ
```

> **Veri silme yapılmadı.** Kısmi sonuç mantığı saf `summarizeBulk` ile
> sınandı; store testleri kayıtları doğrudan `store.items`'a koyuyor, hiçbir
> uç çağrılmıyor. "Boş seçimde uca gitmez" testi bunu tersinden doğruluyor:
> çağrı olsaydı Node'da `fetch` patlardı.

### 4.2 "İlerleme" — çubuk YOK, ve bu bilinçli

`store.bulkBusy` süren işlemde çubuğun düğmelerini kilitliyor, `aria-busy`
basıyor ve "işlem sürüyor" satırı gösteriyor. **Yüzde çubuğu çizilmedi:**
uçlar listenin tamamını tek istekte işleyip tek yanıt döndürüyor, aradan
ilerleme bildirimi gelmiyor. Uydurma bir çubuk, olmayan bir bilgiyi varmış
gibi gösterirdi.

> Gerçek yüzdeli ilerleme için arka tarafın işi kuyruğa alıp durum ucu açması
> gerekir (Faz 9'un "background jobs for bulk operations with progress
> tracking" maddesi). Bu turda arka tarafa dokunulmadı.

### 4.3 Kalıcı silme onayı artık sunucudan doğrulanıyor

**Bulgu:** `preview_release` ucu vardı ve **hiçbir yerden çağrılmıyordu** —
`useSellerMedia.js`'te tanımlı, sıfır kullanım.

Onay penceresi uyarısını listeyle birlikte gelen `liveUsage` sayısından
kuruyordu. O sayı listenin **yüklendiği andan kalma**: aradan geçen sürede
aynı görsel bir ürüne bağlanmış olabilir (başka sekme, başka kullanıcı, içeri
aktarma işi). Ekran "hiçbir yerde kullanılmıyor" der, kullanıcı **kalıcı**
silmeyi onaylar.

`askPurge()` artık onay penceresini açmadan önce `preview_release`'i çağırıyor
(salt okuma, hiçbir şey silmez) ve sunucu "bunlardan n tanesi şu an
kullanılıyor" derse en sert uyarıyı gösteriyor. Çağrı başarısız olursa onay
yine açılıyor: silmeyi engellemek doğru cevap değil — asıl kapı arka tarafta
ve orası kullanımdaki dosyayı zaten reddediyor.

### 4.4 Yol boyunca çıkan üç sessiz hata

1. **Arşiv görünümünde toplu işlem ekranı boşaltıyordu.** `archiveMany`,
   `removeMany` ve `addTagToMany` işlem sonrası hep **aktif** listeyi
   yüklüyordu (`loadReal()`). Arşiv görünümündeyken gelen kayıtlar
   `archived: false` olurken süzgeç `archived: true` aradığı için liste
   bomboş kalıyordu. Üçü de artık `loadReal({ trashed: showArchived })`
   çağırıyor — `purgeMany` zaten böyleydi.
2. **Toplu çubuktaki "Arşivle" düğmesi arşivde de "Arşivle" diyordu.** Oysa
   oradan yapılacak tek şey geri almak; `media.bulk.unarchive` çevirisi vardı
   ama kullanılmıyordu. Düğme artık `archived` prop'una göre etiket ve ikon
   değiştiriyor.
3. **Tek dosyalık arşivlemede sessiz başarı.** Sahiplik kontrolünden düşen ya
   da hata veren dosya için de "arşivlendi" yazılıyordu; artık kısmi sonuçta
   uyarı çıkıyor.

---

## 5. Yapılmayanlar ve gerekçeleri

### 5.1 Klasör ağacı + sürükle-bırak taşıma (T-094)

Faz 9 "vendor-scoped folder tree with drag-drop move and rename" ve arkasında
"Media Folder DocType with nested-set structure" istiyor. **Böyle bir DocType
yok** ve `seller_media.py`'de klasör/taşıma ucu yok — sanal klasör ağacı
`media/browse.py` üzerinden ürün/kategori hiyerarşisinden türetiliyor, yani
taşınabilir bir şey değil. Ekran tarafında bir ağaç çizmek, arkasında
karşılığı olmayan bir işlem vaat etmek olurdu.

Ayrıca gezgin ekranları (`MediaExplorerView.vue`, `MediaFolderGrid.vue`,
`useMediaBrowser.js`) bu turda **yasak listesinde**ydi; okundu, değiştirilmedi.

**Etiket tarafı zaten var:** çoklu etiket süzgeci (AND), etiket bulutu,
toplu etiketleme ve serbest etiket girişi çalışıyor; bu turda etiket
süzgecinin AND davranışı testle çakıldı.

### 5.2 `MediaFilters.vue` yazılmadı

İki sebep:

1. **REFACTOR-BEFORE-WRITE.** Ekranda zaten iki filtre bileşeni var —
   `MediaFilterRail.vue` (gruplar, etiket bulutu, hızlı görünümler) ve
   `MediaFilterChips.vue` (aktif filtre şeridi). Üçüncüsü aynı işi bölerdi.
2. **Doğrulanamazdı.** Geriye kalan iş masaüstü araç çubuğunu görünümden
   çıkarmaktı — saf düzen taşıma, sıfır işlevsel kazanç. Bu turda tarayıcıda
   doğrulama yapılmıyor; `sticky` konumlanma ve scoped stil taşınmasının
   doğru olduğunu **testle gösteremezdim**. Doğrulanamayan bir düzen
   değişikliğini işlevsel iş yerine koymak yanlış takas.

Ayrılan dosya bütçesi bunun yerine `src/utils/mediaFilterUrl.js`'e gitti —
saf, testli ve düzen riski yok.

> **Not:** `mediaFilterUrl.js` görev tarifindeki "senin dosyaların" listesinde
> adı geçmeyen tek yeni dosya. Adı benzersiz, başka hiçbir dosyadan
> içe aktarılmıyor (yalnız `MediaLibraryView.vue` ve kendi testi), çakışma
> riski yok.

### 5.3 Ürüne göre arama yapılamıyor

Faz 9 T-092 arama alanları arasında "product" sayıyor. İstemcide bu veri
**yok**: bir dosyanın hangi ürünlerde kullanıldığı (`usageDetail`) pahalı
olduğu için yalnız detay paneli açılınca, dosya başına ayrı çağrıyla
isteniyor. Listedeki her satır için istemek 200 ek istek demek.

Arama kutusu bugün **dosya adı, başlık ve etiketlerde** çalışıyor
(`utils/mediaFormat.js → matchesQuery`). Durum (kullanılıyor/kullanılmıyor,
arşiv), tarih aralığı ve boyut aralığı ayrı süzgeç olarak zaten var ve artık
adres çubuğunda taşınıyor.

`matchesQuery` **bilinçli olarak genişletilmedi**: `MediaPickerModal` ile
paylaşılan bir yardımcı ve bu turda aynı anda 14 ajan çalışıyor; marjinal
kazanç için paylaşılan dosyada çakışma riski almak doğru takas değil.

**Öneri:** ürüne göre arama sunucuda çözülmeli — `get_my_media`'nın `search`
parametresi kullanım tablosuna da bakmalı.

---

## 6. Değişen dosyalar

| Dosya | Ne oldu |
|---|---|
| `frontend/src/utils/mediaFilterUrl.js` | **YENİ** — filtre↔adres saf çevirisi |
| `frontend/src/stores/media.js` | `summarizeBulk` (dışa aktarılan saf fn), `bulkBusy`, `bulkReport`, `previewRelease`, `clearBulkReport`; üç toplu işlemin dönüş şekli; arşiv görünümü yeniden yükleme düzeltmesi |
| `frontend/src/views/seller/MediaLibraryView.vue` | Adres çubuğu senkronu, `reportBulk`, `askPurge` → `preview_release`, sıralama izleyicisi `flush: "sync"` |
| `frontend/src/components/media/MediaBulkBar.vue` | `busy` + `report` prop'ları, kısmi sonuç paneli, arşiv/geri-al etiketi |
| `frontend/src/utils/__tests__/mediaFilterUrl.test.js` | **YENİ** — 13 test |
| `frontend/src/stores/__tests__/mediaLibraryGrid.test.js` | **YENİ** — 15 test |

Yasak listesindeki hiçbir dosyaya dokunulmadı: `router/index.js`,
`data/navigation.js`, `i18n/locales/*`, `components/media/upload|crop|simulator/**`,
`MediaDetailPanel.vue`, `MediaExplorerView.vue`, `useVirtualGrid.js`,
`useMediaBrowser.js`, `tradehub_core`, `docker/`.

---

## 7. Gereken i18n anahtarları (rota/menü/i18n bağlantısı bende değil)

Sekiz yeni anahtar; hepsi `t()` ile çağrılıyor, dört dile de eklenmeli.
`media.bulk.unarchive` zaten vardı (kullanılmıyordu, artık kullanılıyor).

| Anahtar | Yerine geçen değişkenler | Önerilen TR metni |
|---|---|---|
| `media.bulk.running` | — | `İşlem sürüyor…` |
| `media.bulk.partial` | `{ok}` `{failed}` `{skipped}` | `{ok} dosya işlendi · {failed} başarısız · {skipped} atlandı` |
| `media.bulk.failedUnknown` | — | `Sebep bildirilmedi` |
| `media.bulk.failedMore` | `{count}` | `ve {count} dosya daha` |
| `media.bulk.skippedNote` | `{count}` | `{count} dosya bu mağazaya ait olmadığı için atlandı.` |
| `media.bulk.dismissReport` | — | `Dökümü kapat` |
| `media.toast.bulkPartial` | `{ok}` `{failed}` `{skipped}` | `{ok} tamamlandı, {failed} başarısız, {skipped} atlandı.` |
| `media.confirm.purgeNowInUse` | `{count}` | `DİKKAT: bu dosyalardan {count} tanesi ŞU AN ürünlerinizde kullanılıyor. Bu işlem GERİ ALINAMAZ; silerseniz o ürünlerde görsel kaybolur.` |

> Anahtar eklenene kadar ekran anahtarın kendisini yazar (vue-i18n davranışı);
> derleme ve test bundan etkilenmiyor.

---

## 8. Arka tarafa devredilen bulgular

1. **`seller_listings()` klasör listesi sayfalanmıyor** (`media/browse.py:744`).
   İstemci penceresi tarayıcıyı ayakta tutuyor ama yanıt hâlâ bütün klasörleri
   taşıyor. `page`/`page_size` alması gerekiyor.
2. **`add_tag` `_toplu()` iskeletini kullanmıyor** (`api/seller_media.py:519`).
   Yalnız `{tagged: n}` döndürüyor; sahibi olunmayan dosya ile "etiket zaten
   var" durumu aynı sessiz atlama. Bu yüzden etiketlemede kısmi döküm
   üretilemiyor — diğer üç toplu işlemde üretiliyor. `_toplu()`'ya taşınmalı.
3. **Toplu işlemlerde gerçek ilerleme yok.** Uçlar senkron ve tek yanıtlı;
   Faz 9'un "background jobs … with progress tracking" maddesi için kuyruk +
   durum ucu gerekiyor.
4. **Ürüne göre arama sunucuda çözülmeli** (§5.3).

---

## 9. Doğrulama çıktısı

```
$ npm run lint   → EXIT 0   (2 uyarı, ikisi de PlansTab.vue — bu turdan önce vardı)
$ npm run build  → EXIT 0
$ npm test       → tests 569 · pass 569 · fail 0
$ node --test src/utils/__tests__/mediaFilterUrl.test.js \
               src/stores/__tests__/mediaLibraryGrid.test.js
                 → tests 28 · pass 28 · fail 0
```

**Yapılmayan doğrulama:** tarayıcıda açılıp bakılmadı, imaj kurulmadı, süre /
kare hızı / bellek ölçülmedi. Bu turda hiçbir performans iddiası yok — §2'deki
tek nicel iddia "DOM'a basılan kalem sayısının üst sınırı", o da testle
gösterildi.

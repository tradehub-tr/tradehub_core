# 44 — T-081 · T-091: Yükleme oturumu, devam ve ön kontrol paneli

**Tarih:** 2026-08-19 · **Depo:** `admin-panel`, dal `ahmet` · **Kapsam:** T-081 (upload
session + resumable), T-091 (Uppy + tus yükleyici ve preflight paneli)

Her iki görev de sıfırdan yazıldı; öncesinde bu iki başlığa ait hiçbir dosya yoktu.

---

## 1. Özet — ne yapıldı, ne yapılmadı

| İstenen | Durum | Not |
|---|---|---|
| Parçalı yükleme oturumu | ✅ | `upload_begin/chunk/finish/abort` üstünde |
| Kesintiden devam | ✅ | `upload_status` + `localStorage` parmak izi |
| tus protokolü | ❌ **YAPILAMADI** | Sunucuda tus YOK — §3 |
| `create_session` (policy snapshot, quota, expires_at) | ❌ | Sunucuda yok — §3 |
| Idempotency-Key | ❌ | Sunucuda yok; istemci tarafı kilit var — §3 |
| Uppy | ❌ **KURULMADI** | Gerekçe §4 |
| Ön kontrol: boyut, MP, biçim, alfa, süre, codec | ✅ | §5 |
| Ön kontrol: DPI | ⚠️ **kural yok** | Ölçülüyor, ekranda bilgi; politikada eşik yok — §5.3 |
| Ön kontrol Web Worker'da | ⚠️ **kısmen** | Görsel işçide, **video ana iş parçacığında** — §5.4 |
| İhlalde yükleme başlamıyor + düzeltme yolu | ✅ | Testle ölçüldü — §7 |
| Sürükle-bırak · çoklu · klasör · yapıştırma | ✅ | §6 |
| Cihazda küçültme, başarısızlıkta sunucuya devir | ✅ | Mevcut `prepareMedia` yeniden kullanıldı |
| "50 dosyada ana thread <50 ms" | ❌ **ÖLÇÜLMEDİ** | §9 |
| Rota / menü bağlantısı | — | Bilerek yapılmadı; bileşen kullanıma hazır |

---

## 2. Yazılan dosyalar

```
src/lib/media/upload/
  sync.mjs                    slot politikasını tradehub_core'dan üreten script
  vendor/slotPolicy.js        ÜRETİLMİŞ — 9 slotun ön kontrol alanları + kaynak özetleri
  bytes.js                    imza, tehlikeli içerik, animasyon, DPI, BAŞLIKTAN boyut
  probe.js                    ölçüm (işçide de ana iş parçacığında da koşar)
  videoProbe.js               mediabunny ile video ölçümü (yalnız ana iş parçacığı)
  preflight.js                SAF kural motoru — slot politikasına vurur
  preflight.worker.js         işçi kapısı
  preflightClient.js          işçi/yedek yol seçimi + kuyruk ölçümü
  session.js                  T-081: oturum, devam, yeniden deneme, iptal
  dropFiles.js                klasör ağacı + yapıştırma toplayıcısı
  __tests__/preflight.test.js (37 test)
  __tests__/session.test.js   (17 test)
  __tests__/queue.test.js     (9 test)
  __tests__/fixtures/apiStub.js

src/composables/useMediaUpload.js    kuyruk orkestrasyonu

src/components/media/upload/
  MediaUploader.vue           kullanıma hazır bileşen
  UploadDropzone.vue          bırakma alanı
  UploadQueueRow.vue          kuyruk satırı
  PreflightPanel.vue          ölçüm + ihlal + düzeltme yolu
```

`package.json` **DEĞİŞTİRİLMEDİ** — yeni bağımlılık eklenmedi (§4).

---

## 3. T-081: tus yok, `create_session` yok — sözleşme sunucudan çıkarıldı

Görev metni (`docs/52-faz8-api.html`) şunu istiyor:

> `create_session` → `{ session_id, upload_url, policy_snapshot, quota_remaining, expires_at }`
> · Kesilen yüklemeler **tus protokolüyle son bayttan** devam eder
> · Aynı `Idempotency-Key` ile ikinci `finalize` yeni varlık açmaz

**Sunucuda bunların hiçbiri yok.** `docs/api/openapi-http.yaml` (87 uç) tarandı: tek bir
tus başlığı, `PATCH .../uploads/...` ucu ya da `Idempotency-Key` parametresi geçmiyor.
`tradehub_core/media/chunked.py` + `api/seller_media.py` kendi sözleşmesini tanımlıyor:

```
upload_begin(file_name, total_bytes) → {upload_id, chunk_bytes(2 MB), chunk_count, file_name}
upload_chunk(upload_id, index, content:base64) → {received, chunk_count, complete}
upload_finish(upload_id) → {file_url, file_name, bytes, video_status}
upload_abort(upload_id)  → {aborted}
upload_status(upload_id) → {upload_id, file_name, chunk_count, chunk_bytes, received[], created}
```

`tus-js-client` (kayıt erişilebilir, güncel sürüm 4.3.1) **kurulmadı**: konuşacağı bir uç
olmadan ölü bağımlılık olurdu.

**Devam edebilirlik tus'un tekelinde değil.** `upload_status` sunucuda DURAN parça
sıralarını döndürüyor; "son bayttan devam" ile aynı kullanıcı sonucunu veren "eksik
parçalardan devam" bu uçla mümkün ve kurulan şey bu:

1. Oturum kimliği `localStorage`'a dosyanın parmak iziyle (`ad|boyut|değişim zamanı`)
   yazılır. `lastModified` parmak izinde: aynı adla aynı boyutta ama değiştirilmiş bir
   dosya eski oturuma parça eklerse iki dosyanın baytları karışırdı.
2. Kaydın yaşı sunucu TTL'sini (6 sa, `chunked.SESSION_TTL_HOURS`) geçtiyse sorulmadan
   atılır.
3. `upload_status` sorulur; sunucu oturumu unutmuşsa kayıt atılır ve **kullanıcı hata
   görmeden** sıfırdan başlanır.
4. Sunucunun parça planı (`chunk_bytes`) istemcininkiyle uyuşmuyorsa devam EDİLMEZ.
5. Yalnız eksik parçalar gönderilir; sayaç sunucunun döndüğü `received`'dan okunur.

### Sunucuda kapanması gereken boşluklar (istemci gizleyemez)

| Boşluk | Bugünkü etki | İstemcideki geçici karşılık |
|---|---|---|
| `Idempotency-Key` yok | `upload_finish` ağ koptuktan sonra tekrarlanırsa **ikinci bir `File` kaydı açılabilir**; istemci bunu göremez | `start()` istemci tarafında tek sefere kilitli; ikinci çağrı aynı sözü döner |
| `expires_at` dönmüyor | TTL istemcide **sabit yazılı** (6 sa) — sunucudaki sabit değişirse sessizce ayrışır | TTL aşımında kayıt atılıp sıfırdan başlanıyor |
| `policy_snapshot` / `quota_remaining` yok | Kota reddi ancak `upload_finish`'te öğreniliyor; 200 MB gönderildikten sonra | Yok — kullanıcı bekliyor |
| sha256 ile "zaten var" yok | Aynı dosya ikinci kez tam olarak yükleniyor | Kuyruk içi tekrar engelleniyor, sunucu tarafında engellenmiyor |

---

## 4. T-091: Uppy kurulmadı — gerekçe

1. **tus tarafı ölü** (§3). Uppy'nin bu bağlamdaki asıl değeri `@uppy/tus`; o
   kullanılamıyor.
2. Uppy kendi kuyruk/durum modelini getiriyor. Bu ekranda kuyruk zaten
   `useMediaUpload` içinde ve **gerçek uçlara** bağlı. İki kuyruk modeli arasında köprü
   kurmak, tek bir kuyruk yazmaktan hem büyük hem kırılgan olurdu.
3. `CLAUDE.md` §2/11: yeni bağımlılık **sorulmadan** eklenmez. Üstelik 14 ajan aynı
   depoda paralel çalışıyor; `npm install` `package-lock.json` ve `node_modules`'ı
   paylaşımlı olarak değiştirip başka ajanların yapısını kırabilirdi.

Uppy'nin sağladığı özellikler ayrıca yazıldı: sürükle-bırak, çoklu dosya, **klasör
bırakma** (`webkitGetAsEntry` ağaç gezme, `readEntries` sayfalaması tükenene kadar),
**yapıştırma** (adsız ekran görüntüsüne zaman damgalı ad — adsız dosya sunucuda
`upload_name_required` ile reddedilirdi), ilerleme, kalan süre, yeniden deneme, iptal.

**Yeni bağımlılık eklenmedi.** Video ölçümü için zaten bağımlılıkta olan `mediabunny`
(`compress.video.js` kullanıyor), küçültme için zaten var olan `prepareMedia` kullanıldı.

---

## 5. Ön kontrol paneli

### 5.1 Kural kaynağı — kopyalandı, çünkü ucu yok

Slot kuralları (`max_megapixels_hard`, `min_short_edge`, `allowed_ratios`,
`duration_max_s` …) `tradehub_core/.../policy/slots/*.json` içinde. **Bunları panele
veren hiçbir HTTP ucu yok** — `upload_limits` yalnız uzantı ve bayt sınırı veriyor.

Bu yüzden `sync.mjs` 9 slotun ön kontrole bakan alanlarını `vendor/slotPolicy.js`'e
üretiyor ve kaynak dosyaların **sha256**'sını dosyaya yazıyor. `npm test` içindeki bir
test bu özetleri yeniden hesaplıyor: kaynak değişip script koşturulmazsa **test kırılıyor**.
Ayrışma sessiz kalmasın diye. (Aynı 9 hash, crop ajanının `crop/vendor/vendor.manifest.json`
dosyasındakilerle birebir aynı çıktı — bağımsız çapraz doğrulama.)

> **Kalıcı çözüm sunucuda:** slot politikasını dönen bir uç (`get_slot_policies`) açılırsa
> bu kopya silinmeli. Bugün açık bir borç.

### 5.2 Eşikler uydurulmadı

Karşılaştırmalar referans uygulamayla (`media/pipeline/fakes/policy.py`
`check_image`/`check_video`) birebir; sebep kodları da sunucunun `SEBEP_*` sabitlerinin
aynısı (`megapixel_bomb`, `short_edge_too_small`, `ratio_not_allowed` …) — ekranda
gösterilen sebeple sunucunun döndüğü sebep aynı kelime.

| Kural | Karşılaştırma | Sonuç |
|---|---|---|
| `max_megapixels_hard` | `>` | **RET** |
| `min_short_edge` | `<` (eşitlik geçerli, FR-015) | **RET** |
| `min_area`, `max_edge`, `max_short_edge` | `<` / `>` | **RET** |
| `allowed_ratios` | `min(\|ar−hedef\|/hedef) > tolerans` | **RET** |
| `aspect_band` (logolar) | bant dışı | **RET** |
| `allow_animated:false` + animasyon **ölçüldü** | — | **RET** |
| `max_count` | `>` | **RET** |
| `duration_min_s` / `duration_max_s` | aralık dışı | **RET** |
| `resolution_min` / `resolution_max` | — | **RET** |
| `bitrate_cap_kbps` | `>` | **UYARI** (transcode zaten düşürüyor) |
| `low_resolution_warn_below` | `<` | **UYARI** |
| uzantı/imza uyuşmazlığı | — | **UYARI** (sunucu da reddetmiyor) |
| `alpha_channel: optional` + alfa yok | — | **BİLGİ** |

### 5.3 DPI — ölçülüyor ama kural yok

T-091 "DPI" diyor. Slot politikalarında **girdi DPI'ı için hiçbir eşik yok**; yalnız ÇIKTI
için `master.dpi_out: 72` var. JPEG JFIF yoğunluğu ve PNG `pHYs` okunuyor ve panelde
bilgi olarak gösteriliyor, ama **hiçbir dosyayı reddetmiyor** — olmayan bir kuralı
uydurmaktansa boşluğu ilan etmek doğru.

### 5.4 Megapiksel bombası ÇÖZÜLMEDEN yakalanıyor

Boyut önce **başlıktan** okunuyor (PNG IHDR, JPEG SOF, GIF, WebP VP8/VP8L/VP8X, BMP).
Tavanı aşan görsel `createImageBitmap`'e HİÇ verilmiyor: 100 MP'lik bir PNG birkaç yüz
KB olabilir ama açıldığında yüzlerce MB RAM ister — boyutu öğrenmek için çözmek,
korunmaya çalışılan saldırıyı tarayıcıda yapmak olurdu. Başlığı okunamayan biçimler
(AVIF/HEIC/TIFF) `createImageBitmap`'e düşüyor.

### 5.5 Ölçülemeyen ≠ geçti

Her ölçüm alanı ya bir sayı ya `null`. Çözülemeyen dosya `manual_review` + görünür
uyarı üretiyor; panelde o satır "ölçülmedi" yazıyor, boş bırakılmıyor — boşluk "sorun
yok" diye okunurdu. Animasyon bilinmeyen biçimlerde `false` değil `null` dönüyor.

---

## 6. Web Worker — kısmen

T-091 ölçümün Web Worker'da koşmasını istiyor. **Görsel ölçümü işçide; video ana iş
parçacığında.** Sebep yapısal ve ölçüldü: `mediabunny` devingen içe aktarılıyor (~540 KB;
statik bağlamak yalnız görsel yükleyen kullanıcıya da bu bedeli ödetirdi) ve devingen
içe aktarma işçi paketinde kod bölmesi üretiyor. Vite'ın varsayılan işçi biçimi bunu
reddediyor:

```
[vite:worker-import-meta-url] Invalid value "iife" for option "output.format" —
UMD and IIFE output formats are not supported for code-splitting builds
```

Bu, önce **üretim yapısını kırdı**; ölçüm ikiye ayrılarak çözüldü. Kalıcı çözüm
`vite.config.js`'te `worker: { format: "es" }` — yapı yapılandırması bu görevin kapsamı
dışında bırakıldı (başka ajanların da kullandığı ortak dosya).

**Sonuç:** video ölçülürken ana iş parçacığı bloklanabilir. **Bu ÖLÇÜLMEDİ.**

İşçi hiç kurulamazsa (Storybook, eski WebView) ön kontrol atlanmıyor: aynı `probe.js`
ana iş parçacığında koşuyor ve ekranda `media.uploader.workerFallback` uyarısı çıkıyor.

---

## 7. Doğrulama — ne koşturuldu, ne koşturulmadı

### Koşturulanlar

| Komut | Sonuç |
|---|---|
| `npm run lint` | **EXIT 0** · 0 hata, **2 uyarı** (ikisi de `PlansTab.vue`, önceden vardı — yeni uyarı eklenmedi) |
| `npm test` | **571 test · 571 geçti · 0 kaldı** |
| `npm run build` | **EXIT 0** |

**Test taban çizgisi düzeltmesi:** görev metni "bugün 396/396 geçiyor" diyor. İşe
başlarken ölçülen gerçek durum **396 test / 395 geçti / 1 KALDI** idi —
`src/lib/media/simulator/__tests__/srcsetParity.test.js` bir sha256 beklentisinde
düşüyordu (simülatör ajanının alanı, dokunulmadı). Kapanışta o test de geçiyor; başka
bir ajan aradan düzeltmiş. Toplam 571'in **63'ü** bu görevin testleri (37 + 17 + 9).

**Yeni bileşenler için `npm run build` tek başına hiçbir şey kanıtlamıyor** — hiçbir rota
onları içe aktarmadığı için ağaç sarsmayla dışarıda kalıyorlar. Bu yüzden ayrıca dört
`.vue` dosyasını giriş alan geçici bir Vite yapısı koşturuldu: dördü de derlendi, işçi
parçası (`preflight.worker-*.js`) ayrı varlık olarak üretildi. Geçici dosyalar silindi.
İlk denemede §6'daki `iife` hatası **tam burada yakalandı**.

### Koşturulmayanlar — ÖLÇÜLMEDİ

- **Gerçek sunucuya karşı hiçbir yükleme yapılmadı.** Testlerdeki `api` sahte. Uçların
  gerçekten bu gövdeleri kabul ettiği, `upload_status`'ın `received[]`'ı beklenen
  şekilde döndürdüğü ve devam akışının gerçek bir kesintide çalıştığı **HTTP ile
  doğrulanmadı**. Sözleşme yalnız `chunked.py` + `seller_media.py` + `openapi-http.yaml`
  okunarak çıkarıldı.
- **Tarayıcıda hiçbir şey açılmadı** (görev kuralı). `createImageBitmap`, `OffscreenCanvas`
  alfa örneklemesi, `mediabunny` video ölçümü, Web Worker yolu, sürükle-bırak ve
  yapıştırma olayları **gerçek tarayıcıda çalıştırılmadı**. Node testleri bunların
  saf/bayt kısımlarını kapsıyor.
- **Hiçbir süre/hız ölçümü yapılmadı.** "50 dosyada ana thread <50 ms" kabul ölçütü
  **doğrulanmadı**. Kalan süre kestirimi (`etaSeconds`) yazıldı ama gerçek bir ağda
  sınanmadı.
- `docker/` ve `tradehub_core` altında **hiçbir dosya değiştirilmedi**; imaj kurulmadı.

### Node testleriyle gerçekten ölçülenler

- Kopyalanan slot politikasının kaynağıyla hâlâ özdeş olduğu (9 sha256).
- 9 slotun eksiksiz taşındığı, rol süzgeci, video/görsel ayrımı.
- Eşik karşılaştırmalarının yönü: MP tavanında eşitlik geçiyor `+1` piksel kalıyor;
  kısa kenarda 1000 geçiyor 999 kalıyor; oran sapması bağıl; bit hızı uyarı, ret değil.
- Başlıktan boyut okuma (PNG/JPEG-SOF/GIF/WebP/BMP), imza tanıma, tehlikeli içeriğin
  baştaki boşlukla atlatılamadığı, APNG/GIF animasyon tespiti, JFIF DPI birimleri.
- Oturum: çağrı sırası ve gövdeleri; devamda `upload_begin`'in **hiç çağrılmadığı** ve
  yalnız eksik parçaların gittiği; sunucu oturumu unuttuğunda sessizce sıfırlandığı;
  parça planı uyuşmazsa devam edilmediği; ağ kopmasının yeniden denendiği ama politika
  reddinin **denenmediği**; iptalin `upload_abort` çağırdığı; ikinci `start()`in yeni
  istek üretmediği.
- Kuyruk: klasör ağacının gezildiği, `readEntries` sayfalamasının tükenene kadar
  okunduğu, ihlalli dosyada **yükleme uçlarına hiç gidilmediği** ve satırın kuyrukta
  kaldığı, uyan dosyanın gerçekten gittiği.

---

## 8. Gereken i18n anahtarları

Kodda sabit Türkçe metin yok; hepsi `t()` üzerinden. **Dört dile eklenmesi gerekenler:**

### `media.uploader.*`

| Anahtar | Parametre | Anlam |
|---|---|---|
| `title` | — | "Medya yükle" |
| `dropTitle` | — | "Dosyaları buraya sürükleyin" |
| `dropActive` | — | Sürükleme sırasında: "Bırakın" |
| `dropHint` | — | Slot seçilmemişken genel ipucu |
| `dropAria` | — | Bırakma alanının erişilebilir adı |
| `pasteHint` | — | "Ekran görüntüsünü Ctrl+V ile yapıştırabilirsiniz" |
| `slotHint` | `{formats}`, `{limit}` | "JPG · PNG · WEBP · en fazla {limit} MB" |
| `slotLine` | `{slot}` | "Kurallar: {slot}" |
| `noSlot` | — | "Slot seçilmedi — yalnız genel yükleme kuralları geçerli" |
| `summary` | `{done}`, `{blocked}`, `{failed}`, `{total}` | Kuyruk özeti |
| `overallAria` | — | Genel ilerleme çubuğunun adı |
| `progressAria` | `{name}` | Satır ilerleme çubuğunun adı |
| `details` | `{n}` | "Ayrıntı ({n})" |
| `retry` / `cancel` / `cancelAll` / `clearFinished` | — | Düğmeler |
| `removeAria` | `{name}` | "{name} dosyasını kuyruktan çıkar" |
| `compressed` | `{from}` | "{from} → küçültüldü" |
| `resumed` | — | "Kaldığı yerden devam etti" |
| `resumable` | — | "Yarım kalmış yükleme var" |
| `etaSeconds` | `{n}` | "~{n} sn kaldı" |
| `etaMinutes` | `{n}` | "~{n} dk kaldı" |
| `workerFallback` | — | "Ölçüm ana iş parçacığında koşuyor; büyük dosyalarda arayüz takılabilir" |
| `errorGeneric` | — | "Yüklenemedi." |
| `status.queued` · `status.checking` · `status.blocked` · `status.ready` · `status.preparing` · `status.uploading` · `status.done` · `status.failed` · `status.aborted` | — | 9 durum etiketi |

### `media.preflight.*`

| Anahtar | Parametre | Anlam |
|---|---|---|
| `allClear` | — | "Tüm kontrollerden geçti" |
| `unmeasured` | — | "ölçülmedi" |
| `yes` / `no` | — | Alfa satırı için |
| `seconds` | `{n}` | "{n} sn" |
| `slotLine` | `{slot}` | "Kurallar: {slot}" |
| `fact.size` · `fact.dimensions` · `fact.megapixels` · `fact.alpha` · `fact.dpi` · `fact.duration` · `fact.codec` · `fact.format` | — | Ölçüm etiketleri (8) |

### `media.preflight.reason.*` ve `media.preflight.fix.*`

Her sebep için **iki** anahtar: `reason.<kod>` ihlali anlatır, `fix.<kod>` düzeltme
yolunu söyler. `fix.*` isteğe bağlı — yoksa satır yalnız sebebi gösterir, ama T-091
"düzeltme yolu gösteriliyor" dediği için hepsinin yazılması gerekiyor.

| Kod | `reason` parametreleri | `fix` ne demeli (öneri) |
|---|---|---|
| `ext_not_allowed` | `{ext}`, `{allowed}`, `{conditional}` | Kabul edilen biçimlerden birine dönüştürün |
| `mime_not_allowed` | `{mime}`, `{allowed}` | Aynı |
| `too_large` | `{sizeMb}`, `{limitMb}` | Küçültün ya da daha düşük çözünürlükte kaydedin |
| `empty` | — | Dosya boş; yeniden dışa aktarın |
| `dangerous_content` | — | Uzantı içerikle uyuşmuyor; gerçek bir görsel yükleyin |
| `ext_content_mismatch` | `{ext}`, `{sniffed}` | Reddedilmedi; doğru uzantıyla kaydetmeniz önerilir |
| `megapixel_bomb` | `{measured}`, `{limit}` | Piksel sayısını düşürün |
| `animated_not_allowed` | — | Tek kare olarak dışa aktarın |
| `short_edge_too_small` | `{measured}`, `{limit}` | Daha yüksek çözünürlükte kaydedin (video: `{measured}`/`{limit}` "1280×720" biçiminde) |
| `area_too_small` | `{measured}`, `{limit}` | Aynı |
| `ratio_not_allowed` | `{measured}`, `{allowed}` | Kırpma aracıyla izinli orana getirin |
| `count_exceeded` | `{count}`, `{limit}` | Fazla dosyaları çıkarın |
| `alpha_lost` | — | Saydamlık gerekiyorsa PNG/WebP olarak kaydedin |
| `under_spec` | `{measured}`, `{limit}` / `{recommended}` / `{allowed}` | Çok amaçlı: üst sınır aşımı, düşük çözünürlük uyarısı, kare hızı uyarısı |
| `duration_out_of_range` | `{measured}`, `{min}`, `{max}` | Süreyi kısaltın/uzatın |
| `bitrate_exceeded` | `{measured}`, `{limit}` | Reddedilmedi; sunucuda yeniden sıkıştırılacak |
| `decode_failed` | `{kind}` | Dosya açılamadı, bozuk olabilir |
| `probe_unavailable` | `{kind}` / `{field}` / `{detail}` | Ölçülemedi; sunucu denetleyecek |
| `policy_not_found` | `{slotKey}` | Bilinmeyen slot — geliştirici hatası |

> Sunucudan gelen kodlar (`upload_too_large`, `upload_ext_denied` …) için panel ZATEN var
> olan `media.upload.err.*` anahtarlarını kullanıyor; onlar için yeni anahtar gerekmiyor.
>
> Politika dosyaları slot başına hazır Türkçe ihlal metinleri de taşıyor
> (`slots/*.json` → `messages.tr`, örn. `oran_16_9_degil`, `cozunurluk_dusuk`). Bunlar
> **kasıtlı kopyalanmadı** — kopyalansaydı dört dile çevrilemeyen sabit Türkçe metin
> koda girerdi. `fix.*` metinlerini yazarken kaynak olarak kullanılabilirler.

---

## 9. Kullanım

```vue
<MediaUploader slot-key="product.image" @uploaded="onUploaded" @blocked="onBlocked" />
```

`slot-key` boş bırakılırsa yalnız sunucunun genel politikası (uzantı + bayt + tehlikeli
içerik) uygulanır — medya kütüphanesine serbest yükleme yolu budur. Geçerli anahtarlar:
`brand.logo`, `category.banner`, `company.cover_image`, `company.cover_video`,
`document.attachment`, `product.image`, `product.video`, `seller.logo`, `user.avatar`.

Rota ve menü bağı **bilerek yapılmadı**; ekranın menüde görünmemesi beklenen durum.

Slot politikası değişince:

```bash
cd admin-panel/frontend && node src/lib/media/upload/sync.mjs
```

(`--check` ile yalnız ayrışma denetlenir. `package.json`'a npm script eklenmedi — o dosya
bu görevde yalnız bağımlılık için açıktı ve bağımlılık da eklenmedi.)

---

## 10. Açık borçlar

1. **Sunucuda `Idempotency-Key`** — `upload_finish` tekrarı yeni kayıt açabiliyor (§3).
2. **Slot politikasını dönen bir uç** — kopya silinebilsin (§5.1).
3. **`vite.config.js` `worker: { format: "es" }`** — video ölçümü de işçiye taşınabilsin (§6).
4. **`expires_at`, `quota_remaining`, sha256 dedup** — `create_session` sözleşmesinin
   kalanı (§3).
5. **Gerçek uca karşı devam senaryosu sınanmalı** — bu görevde ölçülmedi (§7).
6. **"50 dosyada <50 ms" ölçülmeli** — kabul ölçütü doğrulanmadı (§7).

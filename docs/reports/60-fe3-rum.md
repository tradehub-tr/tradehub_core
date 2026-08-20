# 60 — T-123 Gerçek kullanıcı telemetrisi (RUM), istemci halkası

**Tarih:** 2026-08-19/20 · **Kapsam:** `admin-panel/frontend`, branch `ahmet`
**Görev:** T-123 — Faz 12 (Headless teslim), kaynak kabul kriteri
`docs/70-faz12-headless-teslim.html`

---

## 0. Tek cümlelik sonuç

İstemci toplayıcı **kuruldu ve testle kanıtlandı**; ama zincirin sunucu
tarafındaki iki halkası (HTTP ucu + `Media RUM Sample` DocType) **hâlâ yok**,
bu yüzden **bugün gerçek saha verisi toplanamaz** ve dört RUM alarmı
besleyicisiz kalmaya devam eder. T-123'ün kabul kriterlerinin hiçbiri bu
görevle **kapanmadı** — kapanmaları için gereken şey aşağıda §5'te alan alan
tarif edildi.

---

## 1. Ne yapıldı

`admin-panel/frontend` altında, çerçeveden bağımsız bir RUM istemcisi:

| Dosya | İşi |
|---|---|
| `src/lib/media/rum/contract.js` | `rum.py` sabitlerinin kopyası (metrikler, rota şablonları, eşikler, yasak alanlar, şema sınırları) |
| `src/lib/media/rum/vendor/rum_vectors.json` | `rum.py`'den **üretilmiş** parite vektörleri + kaynak dosyanın SHA-256'sı |
| `src/lib/media/rum/sha256.js` | Senkron SHA-256 — örneklem kararının sunucuyla birebir aynı olması için |
| `src/lib/media/rum/sampling.js` | Oturum tokeni + deterministik `decide()` (`rum.decide()` paritesi) |
| `src/lib/media/rum/context.js` | Rota şablonu, cihaz sınıfı, viewport kovası, ağ sınıfı, DPR |
| `src/lib/media/rum/lcpAsset.js` | LCP asset etiketleri (`lcp_region` / `lcp_profile` / `lcp_format`) — **URL göndermeden** |
| `src/lib/media/rum/payload.js` | Gövde kurma + istemci tarafı doğrulama + PII kilidi (beyaz liste **ve** kara liste) |
| `src/lib/media/rum/transport.js` | `sendBeacon` → `fetch` yedeği, devre kesici, **ASLA FIRLATMAZ** |
| `src/lib/media/rum/collector.js` | `web-vitals` bağlama, kuyruk, sayfa gizlenince boşaltma |
| `src/lib/media/rum/index.js` | Genel giriş noktası |
| `src/composables/useRum.js` | Vue köprüsü (`startRum` / `stopRum` / `useRum`) |

Testler: `src/lib/media/rum/__tests__/` (6 dosya) + `src/composables/__tests__/rum.test.js`.

Bağımlılık: **`web-vitals@6.1.1`** (`package.json` + `package-lock.json`).

---

## 2. Sözleşme nereden çıkarıldı

Gövde şekli **uydurulmadı**; `media/pipeline/delivery/rum.py` içindeki
`SCHEMA` ve `validate()` okunarak çıkarıldı:

- Zorunlu: `metric`, `value`, `route`, `device_class`, `viewport_width`, `sample_rate`
- İsteğe bağlı: `dpr`, `connection`, `navigation_type`, `session_token`,
  `lcp_region`, `lcp_profile`, `lcp_format`, `engine_version`
- `additionalProperties: false` — bu 14 alanın dışındaki her şey kaydı reddettirir
- Birim: `CLS` birimsiz (4 hane), diğer dördü milisaniye (1 hane) —
  `to_metrics()` bunları **ayrı** metriklere yazdığı için birim karışması
  panelde iki farklı eksen demek

Bu sözleşmenin kopya olduğu ve ayrışmadığı **her koşuda** doğrulanıyor:
`rum_vectors.json` içindeki `source_sha256`, gerçek `rum.py`'nin özetiyle
karşılaştırılıyor. `rum.py` değişip vektörler yenilenmezse test **kırılır**.

Parite vektörleriyle doğrulanan fonksiyonlar:

| Fonksiyon | Vektör sayısı |
|---|---|
| `decide()` (örneklem kararı) | 49 |
| `route_template()` | 18 |
| `viewport_bucket()` | 18 |
| `rating()` | 30 |
| `token_hash()` | 12 |

---

## 3. ⚠ Ölçülmüş boşluk: rota beyaz listesi paneli kapsamıyor

`rum.ROUTE_TEMPLATES` **storefront** rotalarıdır:

```
/  /urunler  /urun/:slug  /magaza/:code  /kategori/:slug  /marka/:slug  /sepet  other
```

Admin panelin rotaları (`src/router/index.js`) bunların **hiçbiri değil**:
`/dashboard`, `/media-library`, `/seller-orders`, `/seo/redirects`,
`/category-management`, … Hepsi `route_template()` tarafından **`other`**
kovasına düşer. Bu, Python'un kendisiyle üretilmiş vektörlerle doğrulandı ve
`rumContract.test.js` içinde açık bir test olarak duruyor.

**Sonucu:** toplayıcı admin panele monte edilirse, toplanan her kayıt
`route="other"` olur ve **sayfa tipi kırılımı oluşmaz.** Kabul kriteri #1'in
"sayfa tipi … göre kırılım var" yarısı bu hâliyle **karşılanamaz**.

İki çıkış yolu var, ikisi de bu görevin kapsamı dışında:

1. **Toplayıcıyı storefront'a monte etmek** (`tradehubfront`). Faz 12'nin asıl
   hedefi zaten storefront LCP'si; `rum.py`'nin lab taban çizgisi
   (`LAB_BASELINE_MS`) da o dört storefront sayfasından alınmış. Teknik olarak
   doğru yer burası.
2. **`rum.ROUTE_TEMPLATES`'i panel rotalarıyla genişletmek** (backend değişikliği).
   Panelin kendi performansı da ölçülmek isteniyorsa gerekli.

Toplayıcı çerçeveden bağımsız yazıldı; (1) için Vue'ya bağımlı tek dosya
`useRum.js`, geri kalanı olduğu gibi taşınabilir.

---

## 4. Kabul kriterleri — durum

Kaynak: `docs/70-faz12-headless-teslim.html`, T-123.

| # | Kriter | Durum | Gerekçe |
|---|---|---|---|
| 1 | "LCP, CLS, INP saha verisi toplanıyor; sayfa tipi ve cihaz sınıfına göre kırılım var" | **KAPANMADI** | Toplayıcı dördünü de (+TTFB) üretiyor ve cihaz sınıfı kırılımı çalışıyor (testli). Ama **saha verisi akmıyor** (uç yok) ve **sayfa tipi kırılımı panelde oluşmuyor** (§3) |
| 2 | "LCP elementinin hangi asset olduğu kaydediliyor" | **İstemci hazır, akış yok** | `lcp_profile=w1280`, `lcp_format=webp`, `lcp_region=product_detail/main_image` üretildiği testle kanıtlandı. Uç olmadığı için hiçbir yere yazılmıyor |
| 3 | "p75 metrikleri panoda; regresyon alarmı var" | **KAPANMADI** | Alarmlar `observability/alerts.py`'de tanımlı ama **besleyicisiz**. p75'i hesaplayan `rum.aggregate()`/`to_metrics()` var, ama girdisi olan örneklem hiç gelmiyor |
| 4 | "Veri toplama KVKK uyumlu; kişisel veri yok, örnekleme uygulanıyor" | **İstemci tarafı KAPANDI** | Örnekleme %10 varsayılan ve deterministik; gövdede PII taşıyan tek bir alan üretilemiyor (testli). Saklama tarafı (30 gün, `Link` alanı yok) `rum.DOCTYPE_DESIGN`'da tasarlı ama **kurulmadı** |

---

## 5. Gereken backend ucu — tarif

Uydurma bir uç yazılmadı. Toplayıcı, aşağıdaki uç var olana kadar 404 alır,
devresini açar ve **susar** (§7). Ucun karşılaması gerekenler:

### 5.1 Yol ve metot

| Alan | Değer |
|---|---|
| Yol | `POST /api/method/tradehub_core.api.v1.media_rum.collect` |
| Frappe | `@frappe.whitelist(allow_guest=True, methods=["POST"])` |
| İstemcideki karşılığı | `transport.js` → `DEFAULT_ENDPOINT` |

> Yol istemcide bir **varsayılandır**, dayatma değil. Backend başka bir yol
> seçerse `startRum({ endpoint: "..." })` ile geçilir; tek satır.

### 5.2 Gövde

`Content-Type: text/plain;charset=UTF-8` — **bilinçli**. `application/json`
"basit istek" olmadığı için CORS ön-kontrolü tetikler; sayfa kapanırken
ön-kontrol tamamlanamaz ve `sendBeacon` ölçümü kaybeder. Sunucu gövdeyi yine
JSON olarak ayrıştırmalı (`json.loads(frappe.request.get_data())`).

```jsonc
{
  "samples": [
    {
      "metric": "LCP",              // LCP|CLS|INP|FCP|TTFB
      "value": 2431.8,              // CLS birimsiz, diğerleri ms
      "route": "/urun/:slug",       // ROUTE_TEMPLATES üyesi
      "device_class": "phone",      // phone|tablet|desktop
      "viewport_width": 390,        // 1..10000  (sunucu kovaya indirger)
      "sample_rate": 0.1,           // (0,1]
      "dpr": 2.63,                  // 0.5..6
      "connection": "4g",           // slow-2g|2g|3g|4g|unknown
      "navigation_type": "navigate",
      "session_token": "…32 hex…",  // sunucu ÖZETİNİ saklar, hamını değil
      "lcp_region": "product_detail/main_image",  // yalnız LCP
      "lcp_profile": "w1280",                      // yalnız LCP
      "lcp_format": "webp",                        // yalnız LCP
      "engine_version": "media-engine-1.2.3"
    }
  ]
}
```

Bir gövdede en fazla **20** örnek (istemci sınırı, `MAX_BATCH`).

### 5.3 Ucun yapması gerekenler

1. `samples` dizisini gez; her eleman için `rum.validate(payload, salt=<gizli>)`.
   `salt` **yapılandırmadan** gelmeli ve sızmamalı — `token_hash`'in tek yönlü
   olmasının anlamı buna bağlı.
2. `RumError` yakala → `rum.record_rejection(hata)` çağır. **Tüm gövdeyi
   düşürme**; geçerli örnekleri yaz, geçersizleri sayaca yaz. Aksi hâlde tek
   bozuk kayıt 19 geçerli ölçümü çöpe atar.
3. Geçerli `RumSample`'ı `Media RUM Sample` olarak `ignore_permissions=True`
   ile ekle (`owner` GUEST olacak ve bilgi taşımayacak — `DOCTYPE_DESIGN`
   böyle tasarlandı).
4. **Yanıt gövdesi önemsiz.** `sendBeacon` yanıtı okuyamaz; 200 dönmek yeterli.
5. **Örneklem kararını yeniden verme.** Karar istemcide verildi ve `sample_rate`
   kayda yazıldı; sunucuda ikinci bir kapı, `estimated_population` hesabını
   (`1/sample_rate` toplamı) bozar.

### 5.4 Yetki ve güvenlik — dikkat edilmesi gerekenler

| Konu | Karar | Gerekçe / risk |
|---|---|---|
| Kimlik | `allow_guest=True` | Storefront'ta ziyaretçi oturumsuz; ölçüm yalnız giriş yapmışlardan toplanırsa saha verisi temsili olmaz |
| CSRF | **Muaf olmalı** | `sendBeacon` başlık gönderemez. Risk kabul edilebilir: uç yalnız **yazar**, hiçbir şey okumaz/değiştirmez ve gövdesi 14 alanlık kapalı bir şemadır |
| Hız sınırı | **GEREKLİ** | Kimliksiz + CSRF'siz bir yazma ucu, sınırsız bırakılırsa tabloyu şişirmeye açıktır. IP başına dakikalık sınır önerilir (IP **saklanmadan**, yalnız sayaçta) |
| Gövde boyutu | Sınırla (≤ 16 KB) | 20 örnek × ~250 bayt tavanın çok altında |
| `Link` alanı | **YOK** | `DOCTYPE_DESIGN` kararı: kayıt hiçbir kullanıcıya bağlanamamalı |
| Saklama | 30 gün | `DOCTYPE_DESIGN.retention_days`; sonrası yalnız `Aggregate` özeti |

### 5.5 Ayrıca kurulması gereken

- **`Media RUM Sample` DocType** — alanları `rum.DOCTYPE_FIELDS`'te,
  tasarımı `rum.DOCTYPE_DESIGN`'da hazır. `rum.doctype_matches_sample()`
  boş dönüyorsa şema ile saklama aynı şeyi söylüyor demektir.
- **Toplama işi (scheduler)** — `rum.aggregate()` → `rum.to_metrics()`.
  ⚠ `to_metrics()` içindeki `samples` bir **sayaçtır**: her toplama penceresi
  **bir kez** geçirilmeli, yoksa örnek sayısı katlanır.

---

## 6. Montaj — nasıl bağlanır (bu görevde YAPILMADI)

`main.js` bu görevin dokunma yetkisi dışında (orkestratörde). Bağlanışı:

```js
// main.js — app.mount() çağrısından SONRA
import { startRum } from "@/composables/useRum";

startRum({ sampleRate: 0.1 });
```

`mount()`'tan sonra olması ölçümü kaybettirmez: `web-vitals`
`PerformanceObserver`'ı `buffered: true` ile kurar, yani toplayıcı geç
bağlansa da geçmiş girdileri teslim alır.

**LCP bölgesi için ek sözleşme:** `lcp_region` etiketinin dolması için LCP
adayı görselleri saran element `data-rum-region="sayfa/bolge"` taşımalı
(sözlük `simulator/vendor/placements.json`). Nitelik yoksa ölçüm yine
toplanır, yalnız bölge boş kalır. Bu nitelik **otomatik türetilmedi**: CSS
seçicisinden çıkarmak DOM yeniden düzenlendiğinde sessizce yanlış bölgeyi
etiketlerdi.

---

## 7. "Telemetri sayfayı asla kırmaz" — nasıl sağlandı

Depodaki mevcut desen (`composables/useMediaBrowser.js` → *"Asla fırlatmaz.
Uç henüz yayına girmemiş … olabilir; o durumda ekran çökmemeli"*) aynen
uygulandı. T-123 için bu varsayımsal değil, **bugünkü durum**.

- `transport.send()` ne fırlatır ne de reddedilen söz döndürür.
- 404/405/410/501 → **devre açılır**, bir daha ağa gidilmez (olmayan uca her
  sayfa yüklemesinde istek yağdırmamak için).
- 500 → başarısız sayılır ama devre **açılmaz** (geçici hata).
- Ağ hiç yoksa / `fetch` reddederse / `sendBeacon` patlarsa → yutulur.
- `web-vitals` yüklenemezse, tek bir metrik gözlemcisi kurulamazsa, metrik
  nesnesi bozuksa, tanılama geri çağrısı fırlatırsa → toplayıcı yaşar.
- Tanılama **konsola basılmaz**; telemetrinin gürültüsü ölçtüğü sayfanın
  konsolunu kirletmemeli.

### `utils/api.js` neden kullanılmadı

`CLAUDE.md` yeni HTTP isteklerinin `utils/api.js`'ten geçmesini söylüyor.
Telemetri bunun **bilinçli istisnası**, iki ölçülmüş nedenle:

1. `api.js` 401/417'de `window.location.href = "/panel/reset"` ile **sert
   yönlendirme** yapıyor (`src/utils/api.js:145,176`). Sayfa kapanırken atılan
   bir telemetri isteği bayat oturum yüzünden 401 alsaydı, kullanıcı **ölçüm
   uğruna oturumundan atılırdı**.
2. `sendBeacon` `api.js`'ten geçemez — `fetch` sarmalayıcısı değil, ayrı bir
   tarayıcı API'si. Sayfa kapanırken ölçümün kaybolmaması tam olarak buna bağlı.

Takas: CSRF başlığı gönderilmiyor → uç CSRF muaf olmalı (§5.4).

---

## 8. Örneklem oranı — %10 neden

Varsayılan **%10**, `docs/70-faz12-headless-teslim.html` T-123 bölümünden
alındı ("örnekleme (%10)"); burada kararlaştırılmadı.

- **%100 değil:** her sayfa yüklemesi 4 metrik üretir; ham örneklem 30 gün
  saklanıyor. Oran kayda yazıldığı ve sunucuda `1/oran` ile genellendiği için
  (`estimated_population`) %10'luk p75, %100'lük p75'ten **farklı bir sayı
  değil**, sadece daha geniş güven aralığına sahip aynı tahmin.
- **%1 değil:** kovalama `(metric, route, device_class)` üzerinden yapılıyor —
  trafik 5 × 8 × 3 kovaya bölünüyor. %1, seyrek kovaları tek haneli örneğe
  düşürür ve p75 gürültüye döner.

**ÖLÇÜLMEDİ:** bu proje için "doğru" oranın ne olduğu. Trafik hacmi bilinmiyor
ve uç yayında olmadığı için ölçülemez. %10 dokümandan gelen bir başlangıç
değeridir, ölçüme dayanan bir optimum değil. İlk gerçek veriden sonra kova
başına örnek sayısına bakılıp güncellenmeli. Oran `startRum({ sampleRate })`
ile yapılandırılabilir.

Karar **deterministik**: aynı token + aynı oran hep aynı sonucu verir, yani
bir oturumun LCP'si alınıp INP'si düşmez. `rum.py` bunu açıkça şart koşuyor.

---

## 9. Test kanıtı

### 9.1 Sayılar

| Ölçüm | Değer |
|---|---|
| Başlangıç (bu görevden önce) | **640 / 640 geçti** |
| Bu görevin eklediği testler | **84**, hepsi geçiyor |
| Bitişte tüm paket | **736 test · 729 geçti · 7 kırık** |

**7 kırığın hiçbiri bu görevin değil.** Hepsi
`src/lib/media/simulator/__tests__/drift.test.js` içinde — bu görevin
**yasak alanında** olan, başka bir ajanın çalışma sırasında eklediği dosya.
Kırılma sebebi ölçüldü: test `fixtures/drift-measurements.json` okuyor,
`fixtures/` dizini **boş**. Dosya benim değiştirdiğim hiçbir modülü import
etmiyor (`../index.js` + `./driftBaseline.js`), yani nedensel bağ yok.
Bu görev kapsamında **dokunulmadı**.

Yalnız bu görevin dosyaları:

```
node --test "src/lib/media/rum/__tests__/*.test.js" "src/composables/__tests__/rum.test.js"
ℹ tests 84 · pass 84 · fail 0
```

`npm run lint` → **EXIT 0**. Kalan 2 uyarı `views/permission/PlansTab.vue`
içinde ve **önceden vardı**; bu görevin dosyalarından tek satır lint çıktısı
yok. `npm run build` **koşturulmadı** (talimat gereği; paralel ajanlarla çakışır).

### 9.2 Toplayıcı gerçekten metrik üretiyor mu

`rumCollectorVitals.test.js` — jsdom + **sahte `PerformanceObserver`** +
**gerçek `web-vitals`** (kütüphane sahte değil; LCP/CLS/INP'yi o hesaplıyor).
Sahte gözlemciye tarayıcı girdileri besleniyor, üretilen gövdeler doğrulanıyor:

| Doğrulanan | Değer |
|---|---|
| TTFB | `120` (navigation `responseStart`'tan) |
| CLS | `0.12` (0,05 + 0,07 toplandı) |
| INP | `250` (etkileşim süresinden) |
| LCP | `1200` (renderTime'dan) |
| LCP asset | `lcp_profile=w1280`, `lcp_format=webp`, `lcp_region=product_detail/main_image` |
| Bağlam | `route=/urun/:slug`, `device_class=phone`, `viewport_width=390`, `dpr=2` |
| PII | Hiçbir gövdede yasak/şema dışı alan yok; `cdn.test`, `panel.test`, `#hero` gövdelere **sızmıyor** |

### 9.3 Uç yokken sayfa kırılmıyor — üç arıza ayrı ayrı

`rumTransport.test.js` + `rumCollector.test.js`:

- **404** → fırlatmaz, devre açılır, sonraki gönderimlerde ağa **hiç gidilmez**
- **500** → fırlatmaz, devre açılmaz (geçici sayılır)
- **Ağ yok** (`fetch` reject) → fırlatmaz; ardışık gönderimlerde de sessiz

### 9.4 Vacuity (boş test) denetimi — iki kez yapıldı

**(a) "ASLA FIRLATMAZ" koruması kaldırıldı** — `transport.js` içindeki iki
`catch` bloğu `throw e` ile değiştirildi:

```
✖ ARIZA 3/3 — ağ hiç yok: fetch reject ediyor, yine fırlatmaz
    actual: TypeError: Failed to fetch
✖ ağ yokken ARDIŞIK gönderimler de sessiz (unhandled rejection yok)
    Error: ECONNREFUSED
✖ ne sendBeacon ne fetch var — yine fırlatmaz
ℹ pass 12 · fail 3
```

Koruma geri konuldu → **15/15 geçti**.

**(b) LCP asset etiketlemesi kaldırıldı** — `collector.js` içindeki
`lcpAssetTags` çağrısı yorumlandı:

```
✖ GERÇEK web-vitals + sahte PerformanceObserver → sözleşmeye uygun gövdeler
    AssertionError: LCP türevi URL'den çıkarılmalı
    actual: undefined · expected: 'w1280'
ℹ pass 0 · fail 1
```

Geri konuldu → **1/1 geçti**.

---

## 10. ÖLÇÜLMEDİ / doğrulanmadı

Dürüstlük listesi — bunlar "geçti" **değil**:

1. **Gerçek saha verisi.** Uç yok, DocType yok. Bu görev hiçbir gerçek
   kullanıcıdan tek bir ölçüm toplamadı ve **toplayamaz**.
2. **Uçtan uca doğrulama.** Sunucunun `validate()`'inin ürettiğimiz gövdeyi
   kabul ettiği test edilmedi — kabul edecek bir uç yok. Yalnız gövdenin
   `SCHEMA`'ya **uyduğu** doğrulandı.
3. **Gerçek tarayıcı.** Hiçbir şey Chrome/Safari/Firefox'ta koşturulmadı.
   jsdom bir tarayıcı değil. `sendBeacon`'ın sayfa kapanırken gerçekten
   yolladığı **doğrulanmadı**.
4. **`web-vitals`'ın ölçüm doğruluğu.** Kütüphanenin LCP'yi Chrome'un
   raporladığı gibi ölçtüğü bu depoda doğrulanmadı; dış bağımlılık olarak
   kabul edildi.
5. **LCP'nin nihai-değer yolu.** `web-vitals` LCP'yi yalnız *güvenilir*
   (`isTrusted`) bir click/keydown/visibilitychange olayında kesinleştirir;
   jsdom'da `Event.isTrusted` yeniden tanımlanamıyor. Test bu yüzden
   `reportAllChanges` ile sürüyor. Nihai-değer yolu **tarayıcıda test edilmeli**.
6. **Türev URL adlandırma düzeni.** `lcp_profile` çıkarımı iki yaygın deseni
   (`-w1280.webp`, `?w=1280`) tanıyor; gerçek storefront URL'lerine
   **bakılmadı**. Tanımadığında `unknown` döner (şemada geçerli bir değer) —
   yanlış tahmin etmektense bilmediğini söyler.
7. **Örneklem oranının bu proje için doğruluğu** (§8).
8. **Süre/performans iddiası yok.** Toplayıcının sayfaya maliyeti
   ölçülmedi; makine paylaşımlı, ölçüm anlamsız olurdu.

---

## 11. Bağımlılık denetimi — `web-vitals@6.1.1`

| Ölçüt | Değer |
|---|---|
| Lisans | Apache-2.0 |
| Geçişli bağımlılık | **yok** (0 dependency) |
| `web-vitals.attribution.js` | 15.6 KB ham / **5.6 KB gzip** |
| `web-vitals.js` (attribution'sız) | 9.0 KB ham / 3.3 KB gzip |
| Ana pakete etkisi | **yok** — `collector.js` içinde `await import(...)` ile **dinamik** yükleniyor, ayrı chunk olur |

`attribution` yapısı seçildi çünkü kabul kriteri #2 ("LCP elementinin hangi
asset olduğu") yalnız o yapıdaki `attribution.url` / `attribution.lcpEntry`
ile cevaplanabiliyor. Fark: +2,3 KB gzip.

> `CLAUDE.md` kural 11 "yeni dependency: **sor** + bundle audit" diyor.
> Audit yukarıda; **sorulamadı** (etkileşimsiz ajan koşusu). Bağımlılık
> istenmezse geri alınması tek yerde: `collector.js` → `loadVitals()`.

---

## 12. Sıradaki iş (bu görevin dışında)

1. **HTTP ucunu yaz** — §5.1–5.4.
2. **`Media RUM Sample` DocType'ı kur** — `rum.DOCTYPE_FIELDS` / `DOCTYPE_DESIGN`.
3. **Toplama işini zamanla** — `aggregate()` → `to_metrics()`, pencere başına **bir kez**.
4. **Montaj kararı** — panel mi storefront mu (§3). Faz 12'nin hedefi göz
   önüne alınırsa **storefront**.
5. **`data-rum-region` niteliklerini** LCP adayı bölgelere ekle (§6).
6. Uç yayına girdikten sonra **oranı gerçek veriye göre yeniden değerlendir**.

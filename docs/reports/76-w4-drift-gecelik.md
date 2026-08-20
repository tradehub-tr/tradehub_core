# 76 — W4: T-115 gecelik drift işi + bildirim kanalı

**Tarih:** 2026-08-20 · **Yazılan repo:** `admin-panel` (workflow) + `tradehub_core` (bu rapor)
**Kaynak:** T-115 kabul ölçütü §4 — *"Test her PR'da değil, günlük (nightly) çalışıyor ve ekip bilgilendiriliyor."*
**Önceki durum:** `docs/reports/59-fe2-drift-testi.md` §5 — ölçüm zinciri TAM, zamanlanmış iş ve bildirim YOK (⚠ KISMİ).

---

## 0. Tek sayfada sonuç

| | Durum |
|---|---|
| Gecelik workflow | ✅ YAZILDI — `admin-panel/.github/workflows/drift-nightly.yml` (yeni dosya; mevcut workflow'lara dokunulmadı) |
| Tetikleyiciler | `schedule: cron "47 1 * * *"` (04:47 TRT) + `workflow_dispatch` |
| Bildirim kanalı | **CI kırmızısı + artifact** — harici webhook/Slack BAĞLANMADI (bilinen kanal yok, uydurulmadı; boşluk §4'te) |
| Yerel prova (CI komut zinciri) | ✅ BAŞTAN SONA KOŞTU — 88 kutu ölçüldü, **drift 0**, en büyük \|fark\| 0,42 px |
| CI ortamında koşum | ❌ **ÖLÇÜLMEDİ** — push/tetikleme bu oturuma ait değil; ilk gece / ilk elle tetiklemede doğrulanacak |
| YAML sözdizimi | ✅ `js-yaml` ile ayrıştırıldı (actionlint kurulmadı) |

> Rapor 59'daki 4 sapan bölge (25 drift satırı, en büyük 80,68 px) **bu provada
> SIFIR çıktı** — `placements.json` düzeltmeleri (rapor 59 §6, iş 1-4) bu ölçümle
> ilk kez gerçek tarayıcıda doğrulanmış oldu. Gecelik iş tam da bu geri kaymayı
> yakalamak için var.

---

## 1. Workflow nerede, neden orada

Ölçerek karar verildi:

| Ölçüm | Sonuç |
|---|---|
| Drift zinciri hangi repoda? | `admin-panel/frontend/scripts/drift-{cdp,serve,targets,measure}.mjs` + `src/lib/media/simulator/` — tamamı admin-panel |
| `tradehubfront`'un rolü | yalnız derlenen GİRDİ (`dist/`) — script'i yok |
| İki repo aynı hesapta mı? | `git remote -v`: ikisi de `github.com/tradehub-tr/…` |
| Görünürlük | `gh repo view` → ikisi de **PUBLIC** → ikinci checkout için ek token/PAT GEREKMEZ |
| admin-panel'de workflow var mı? | var: `alpha/beta/rc/prod-release.yml`, `deploy.yml` — hepsi release/deploy amaçlı, hiçbiri drift koşmuyor; hiçbirine dokunulmadı |

Karar: **workflow `admin-panel`'e yazıldı**, `tradehubfront` ikinci
`actions/checkout` ile yan dizine alınıyor (`repository: tradehub-tr/tradehubfront`).
Kalıp `tradehub_core/.github/workflows/ci.yml`'den alındı (gerekçeli yorum
blokları, sahte-yeşil tabanı, Türkçe adımlar).

### Adımlar (dosyadaki sırayla)

1. `actions/checkout` × 2 → `workspace/{admin-panel, tradehubfront}`
2. `actions/setup-node` Node **24** (drift-cdp.mjs Node'un yerleşik `WebSocket`'ini kullanır; prova v24.18.1 ile yapıldı) + iki lockfile'lı npm cache
3. Chrome doğrula — ubuntu-latest imajında `/usr/bin/google-chrome` kurulu gelir; `findChrome()`'un zaten baktığı üç yol denenir, yoksa iş açık bir hatayla kırmızı (sessiz taklit yok)
4. `tradehubfront: npm ci` + `npm run build` (= icons:generate + tsc + vite build) — ölçüm hedefi GÜNCEL kaynaktan derlenen dist, yayındaki imaj değil (rapor 59 §1.1 gerekçesi)
5. `admin-panel/frontend: npm ci`
6. `node scripts/drift-measure.mjs --dist $GITHUB_WORKSPACE/tradehubfront/dist --base $DRIFT_BASE --out $RUNNER_TEMP/drift-nightly.json` — **herhangi bir bölgede 2 px üzeri sapma → exit 1 → iş KIRMIZI**
7. `MIN_OLCUM` tabanı — sahte-yeşil kapanı (§3)
8. `actions/upload-artifact` — ölçüm JSON'u **her koşumda** (`if: always()`) 30 gün saklanır

---

## 2. Yerel prova — CI komut zinciri baştan sona

CI'da koşacak zincir yerel makinede aynen koşturuldu (macOS, Node v24.18.1,
`/Applications/Google Chrome.app`, headless):

| Adım | Sonuç |
|---|---|
| `tradehubfront: npm ci` | ✅ (onarılmış lockfile ile — daha önce kırıktı) |
| `tradehubfront: npm run build` | ✅ dist üretildi (PWA precache 219 dosya / 7,2 MB) |
| `admin-panel/frontend: npm ci` | ✅ |
| `node scripts/drift-measure.mjs --dist ../../tradehubfront/dist` | ✅ **exit 0** |

### Ölçüm çıktısı (betiğin ÖZET bloğu, elle yazılmadı)

```json
{
  "devices": 13,
  "regionsAttempted": 12,
  "regionsUnmeasured": 3,
  "measured": 88,
  "notFound": 53,
  "driftCount": 0,
  "maxAbsDeltaPx": 0.421875,
  "maxAbsDeltaAt": "desktop-1440p home/top_deals",
  "squareMismatch": 0
}
```

- **88 kutu ölçüldü, sapan 0** — eşik hâlâ 2 px, gevşetilmedi.
- Rapor 59'da sapan 4 bölge bugün: `home/top_deals` −0,42…+0,22 px,
  `seller_shop/product_grid` 0,00, `cart_checkout/summary_strip` 0,00,
  `home/hero_showcase_grid` 0,00. Katalog düzeltmeleri gerçek tarayıcıda tutuyor.
- `notFound: 53` satırın büyük kısmı `optional` işaretli seçiciler
  (`related_slider`, `sku_row`, `product_item`, `tailored_grid`) × 13 cihaz —
  rapor 59 §3'teki bilinen ölçülemeyenler, gizlenmiyor.
- 3 bölge gerekçeli `OLCULMEDI` (marka slug'ı boş, tek görselli ürün, çekmece akışı).

### Backend'siz prova — CI ortamının simülasyonu

GitHub runner'da `http://istoc.localhost` YOK; veri proxy'si 502 döner ve
API'den beslenen ızgaralar boş kalır. Bu durum yerelde `--base http://127.0.0.1:9`
(ölü port) ile ölçüldü:

```json
{
  "devices": 13,
  "regionsAttempted": 12,
  "regionsUnmeasured": 3,
  "measured": 13,
  "notFound": 128,
  "driftCount": 0,
  "maxAbsDeltaPx": 0,
  "maxAbsDeltaAt": "iphone-se-3 cart_checkout/summary_strip",
  "squareMismatch": 0
}
```

Backend'siz ölçülebilen TEK bölge `cart_checkout/summary_strip` (13 cihazın
hepsinde, sapma 0,00) — çünkü sepet API'den değil, `localStorage` tohumundan
besleniyor. Diğer 7 ölçülebilir bölge (ana sayfa ızgaraları, ürün detayı,
listeleme, mağaza) API verisi olmadan boş kalıp `BULUNAMADI` düşüyor. Yani
**bugünkü CI'nın gerçekten koruduğu küme: summary_strip kutusu + zincirin
kendisi** (derleme, seçiciler, Chrome, katalog hesabı). Bu bir boşluktur ve
§6/2'de açıkça yazılıdır; `vars.DRIFT_BASE`'e erişilebilir bir ortam verilince
kapsam 88 kutuya çıkar.

---

## 3. Sahte-yeşil kapanı — `MIN_OLCUM`

`BULUNAMADI` satırları drift SAYILMAZ (`driftCount` yalnız ölçülen kutulardan
gelir). Ölçüm zinciri tamamen çökerse — Chrome yok, seçiciler kaydı, tüm
ızgaralar boş — `measured: 0, driftCount: 0` ile iş **sahte-yeşil** biterdi.
Bu yüzden workflow, ölçümden sonra JSON'daki `summary.measured` değerini
`MIN_OLCUM` tabanıyla karşılaştırır ve altındaysa işi kırmızıya çeker
(`ci.yml`'deki `MIN_MODUL` deseninin aynısı). Taban backend'siz provadan
ölçülerek kondu: **backend'siz ölçüm 13 kutu verdi → `MIN_OLCUM: 10`**
(biraz altta; 10'un altı "zincir çöktü" demek). `DRIFT_BASE`'e gerçek bir
ortam bağlanırsa taban ~80'e çekilmeli (backend'li prova 88 ölçtü) —
workflow'daki yorumda yazılı.

---

## 4. Bildirim kanalı — ne var, ne YOK

**Kanal = CI kırmızısı + artifact.**

- Sapma → `drift-measure.mjs` exit 1 → workflow KIRMIZI → GitHub'ın kendi
  bildirim mekanizması (workflow'u yazan/tetikleyen kişiye e-posta + UI).
- Her koşumda (kırmızı dahil) ölçüm JSON'u `drift-nightly-<run>` artifact'i
  olarak 30 gün saklanır — sapmanın hangi cihaz/bölgede, hangi hesaplanmış
  CSS'ten geldiği içinde.

**Boşluk (gizlenmiyor):** Harici bir webhook/Slack/e-posta listesi
**BAĞLANMADI** — bu projede bilinen, yapılandırılmış bir bildirim kanalı yok ve
uydurulmadı. Şartnamedeki "ekip bilgilendiriliyor" ifadesi, ekip GitHub
bildirimlerini izlemiyorsa TAM karşılanmış sayılmaz. Kapatmak için: ekip bir
webhook URL'i verdiğinde workflow'un sonuna `if: failure()` korumalı tek bir
`curl` adımı eklemek yeterli (workflow'daki yorumda da yazılı). Ayrıca
`schedule` tetikli işlerde GitHub bildirimi yalnız workflow dosyasının son
değiştiricisine gider — bu da ekip-geneli bildirim sayılmaz.

---

## 5. CI'da DOĞRULANAMAYANLAR

| # | Ne | Neden |
|---|---|---|
| 1 | Workflow'un GitHub Actions üzerinde koşumu | Push/tetikleme bu oturuma ait değil; dosya commit'lenmedi. **İlk gece ya da ilk `workflow_dispatch`'te doğrulanacak.** |
| 2 | ubuntu-latest'ta Chrome'un gerçekten `/usr/bin/google-chrome`'da olduğu | İmaj dokümantasyonundan biliniyor ama bu oturumda runner'da ölçülmedi; değilse "Chrome dogrula" adımı açık hatayla kırmızı verir (sessiz sahte-yeşil değil) |
| 3 | Runner'da `istoc.localhost`'un davranışı (DNS reddi mi, bağlantı reddi mi) | Yerelde ölü portla simüle edildi; runner'daki tam hata biçimi farklı olabilir, sonuç aynı: proxy 502 → BULUNAMADI |
| 4 | `schedule` tetikleyicisinin fiilen çalışması | GitHub, 60 gün aktivitesiz repolarda schedule'ı durdurur; ayrıca default branch dışındaki dosyalarda schedule KOŞMAZ — workflow **default branch'e** (master) merge edilmeden gecelik koşum başlamaz |
| 5 | npm cache/`setup-node`'un iki-lockfile davranışı | Dokümante özellik; runner'da ölçülmedi |

## 6. Şartname boşlukları

1. **"Ekip bilgilendiriliyor" kısmı KISMİ** — §4: kanal CI kırmızısı + artifact;
   harici kanal yok. Ekip webhook verirse tek adımla kapanır.
2. **CI'da veri katmanı yok** — gecelik iş API'den beslenen bölgeleri
   ÖLÇEMEZ (BULUNAMADI düşer); bugün CI'nın gerçekten koruduğu kümenin sınırı
   §3'teki backend'siz ölçümdür. Tam kapsam için repo değişkeni `DRIFT_BASE`'e
   erişilebilir bir storefront ortamı verilmeli (workflow buna hazır:
   `vars.DRIFT_BASE`). Alternatif — CI içinde backend ayağa kaldırmak — 14
   servislik compose demek, bu görevde denenmedi.
3. **Görsel (piksel) diff hâlâ yok** — T-115 §1 kabulünün "görsel diff" kısmı
   rapor 59'dan beri açık; bu görev kutu ölçüsü zincirini gecelik koşuma
   bağladı, ekran görüntüsü karşılaştırması ayrı görev.

## 7. Dosyalar

| Dosya | İş |
|---|---|
| `admin-panel/.github/workflows/drift-nightly.yml` | YENİ — gecelik drift işi (mevcut 5 workflow'a dokunulmadı) |
| `tradehub_core/docs/reports/76-w4-drift-gecelik.md` | bu rapor |

**Commit/push YAPILMADI** — dosyalar çalışma ağacında, commit kullanıcıya ait.
**Süre/FPS iddiası yok.**

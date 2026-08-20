# 63 — T-123 RUM zinciri: üç kopuk halka bağlandı (BE1)

**Tarih:** 2026-08-20 · **Kapsam:** `tradehub_core` + `tradehubfront`
**Görev:** Pano T-123 (T-133/T-124'ü besler) — rapor 60'ın (`60-fe3-rum.md`) bıraktığı yerden:
HTTP ucu + `Media RUM Sample` DocType + storefront montajı.

---

## 0. Tek cümlelik sonuç

Zincirin sunucu halkaları **kuruldu ve canlıda ölçüldü** (uç 200 dönüyor, kayıt yazıyor,
hız sınırı HTTP'de 429 atıyor, DocType tabDocField'da 15 alanla duruyor); storefront
montajı **hazır ama kapalı** — `web-vitals` tradehubfront'ta kurulu değil ve göreve göre
package.json'a eklenemezdi (§5, ENGEL).

---

## 1. Ne kuruldu

| Halka | Dosya | Durum |
|---|---|---|
| DocType | `tradehub_core/tradehub_core/doctype/media_rum_sample/` (json + py + `__init__`) | Migrate edildi, **tabDocField'dan ölçüldü** |
| HTTP ucu | `tradehub_core/api/rum.py` → `POST /api/method/tradehub_core.api.rum.collect` | Canlıda ölçüldü (§3) |
| Saklama/kota | Aynı dosyada `purge_expired_samples()` (30 gün) + günlük kayıt tavanı (50k, `site_config.rum_daily_sample_cap`) | Testli; scheduler kaydı SENDE (§7) |
| İstemci çekirdeği | `tradehubfront/src/lib/rum/` (9 dosya + `vendor/rum_vectors.json`) | Vendor'landı, köken notlu |
| Montaj | `tradehubfront/src/main.ts` sonunda tek blok | **HAZIR-AMA-KAPALI** (§5) |
| Testler | `tradehub_core/tests/test_rum_endpoint.py` | **17/17 geçti**, konteynerde (§4) |

Uç yolu istemci varsayılanından (`tradehub_core.api.v1.media_rum.collect`, rapor 60 §5.1)
farklı: görev tarifi `tradehub_core/api/rum.py` dedi. Vendor'lanan `transport.js` içindeki
`DEFAULT_ENDPOINT` gerçek yola güncellendi (vendor-değişikliği yorumla işaretli); admin-panel
kopyası DOKUNULMADI (yasak alan).

`media/pipeline/delivery/rum.py`'ye **tek satır dokunulmadı** (panelin 127 parite vektörü
ona bağlı) — plan bir ekleme öngörmüyordu, gerek de çıkmadı: uç yalnız çağırıyor
(`validate`, `record_rejection`, `DOCTYPE_DESIGN`, `SEBEP_GOVDE`).

## 2. DocType — ölçümler

- `SELECT COUNT(*) FROM tabDocField WHERE parent='Media RUM Sample'` → **15**
  (`rum.DOCTYPE_FIELDS` ile aynı küme; SCHEMA'nın 14 giriş alanından fark tasarım gereği:
  `viewport_width`→`viewport_bucket`, `session_token`→`session_bucket`, + sunucu hesabı `rating`).
- `rum.doctype_matches_sample()` → `()` (testte assert).
- İndeksler (SHOW INDEX ile ölçüldü): `metric`, `route`, `device_class`, `creation_index`
  — `DOCTYPE_DESIGN["indexes"]` şartının tamamı. `creation` indeksi `on_doctype_update()` ile.
- `Link`/`Dynamic Link` alanı YOK (testte assert) — kayıt kimseye bağlanamaz.
- İzinler DOCTYPE_DESIGN'a birebir: yalnız System Manager `read` + `delete`.

## 3. Uç — canlı HTTP ölçümleri (konteyner içinden, misafir, CSRF başlıksız, text/plain)

| Ölçüm | Sonuç |
|---|---|
| Geçerli gövde POST | **200** `{"message":{"ok":true}}` + tabloda 1 kayıt |
| Geçersiz gövde POST (`bozuk govde {{{`) | **200** aynı yanıt, kayıt YOK (hata ayrıntısı sızmaz) |
| Yazılan kayıt | `route=/urun/:slug`, `device_class=phone`, `viewport_bucket=390`, `rating=good` (sunucu hesabı), `owner=Guest`, `session_bucket=5bdb33d1d98d` (12 hex — ham token DEĞİL) |
| Hız sınırı | Aynı dakikada ardışık POST serisi: ilk 30 → `200`, sonrası → **429 429 429 429** |

Hız sınırı **mevcut depodaki desenle**: `tradehub_core.api.rate_limit.rate_limit`
(T9 düzeltmeli misafir IP kovası), `max_calls=30 / 60 sn / per_user=True`. Frappe'nin
`frappe.rate_limiter.rate_limit`'i değil — projede guest kovası düzeltmesi bu modülde.

**CSRF:** misafir POST'u CSRF başlıksız 200 aldı (yukarıda ölçüldü) — frappe/auth.py
`validate_csrf_token` oturumda kayıtlı token yoksa atlar; global `ignore_csrf` AÇILMADI.
Gerekçe uçta yorum bloğunda (rapor 60 §2/§5.4). ÖLÇÜLMEDİ: oturum AÇMIŞ kullanıcının
beacon'ının 400 alacağı çıkarımı kaynak koddan; canlı oturumla denenmedi.

## 4. Test kanıtı

```
bench --site istoc.localhost run-tests --module tradehub_core.tests.test_rum_endpoint
Ran 17 tests ... OK
```

Kapsam: DocType alan paritesi (tabDocField'dan) · geçerli→200+kayıt · geçersiz (PII alanı,
bilinmeyen metrik, bozuk JSON, boş gövde, 16KB üstü) → 200+kayıt YOK · karışık gövde →
yalnız geçerliler · 20 üstü batch kırpılır · günlük kota dolunca düşürme · hız sınırı 429 ·
kova kimlik-başına · misafir whitelist kaydı (`frappe.guest_methods`, yalnız POST) ·
owner=Guest · `purge_expired_samples` yalnız 30 günden eskiyi siler.

**Vacuity (kırmızı kanıtı):** konteynerdeki uçtan `@rate_limit` dekoratörü çıkarıldı →
`FAILED (failures=2)` (`test_rate_limit_exceeded_raises_429`,
`test_rate_limit_bucket_is_per_identity`); dosya geri kondu → 17/17 OK.
Bu denemenin yan bulgusu: ilk vacuity girişimi (sabiti 30→1.000.000 yapmak) testi
KIRMIZI YAPMADI çünkü test pencere boyutunu aynı modül sabitinden okuyor — test limitin
*değerini* değil *mekanizmasını* sınar. Bilinçli bırakıldı (değer yapılandırmadır) ama
kayda geçsin.

Ruff: `ruff check` üç yeni dosyada temiz; `ruff format --check` temiz (repo pyproject
ayarlarıyla, uvx üzerinden — bench imajında ruff yok).

## 5. Storefront montajı — HAZIR-AMA-KAPALI (ENGEL)

- Çekirdek `tradehubfront/src/lib/rum/` altına vendor'landı; her dosyanın başında köken
  notu (`admin-panel/frontend/src/lib/media/rum/<dosya>`) + değişiklik işaretleri.
  Değişen yalnız iki şey: `transport.js DEFAULT_ENDPOINT` (gerçek uca) ve `index.js`'e
  çerçevesiz `startRum()/stopRum()` tekil sarmalayıcı (Vue köprüsü `useRum.js` taşınmadı).
- **ENGEL (ölçüldü):** `web-vitals` tradehubfront'ta YOK (`package.json` dependencies +
  `node_modules` bakıldı). Görev kuralı gereği package.json'a EKLENMEDİ. `collector.js`
  `import("web-vitals/attribution")` içerdiği için modül bir girişten import edilirse Vite
  build kırılır — montaj bloğu bu yüzden `src/main.ts` sonunda YORUMDA, açma adımları
  (npm install web-vitals@^6 + iki satırın yorumunu kaldır) blokta yazılı.
- Ölçümler: `npx eslint src/lib/rum/**/*.js src/main.ts` → temiz · `npx tsc` → temiz ·
  `npm run build` → **EXIT 0** (vendor dosyaları import edilmediği için pakete girmiyor).
- Montaj kanıtı (grep `src/main.ts`):

```
298:// import { startRum } from "./lib/rum/index.js";
299:// startRum({ sampleRate: 0.1 });
```

- NOT: storefront ÇOK girişli (her `*.html` ayrı entry). `main.ts` yalnız ana sayfanın
  girişi; blok açıldığında diğer sayfa tipleri (`/urun`, `/sepet`…) için aynı çağrının
  ortak bir bootstrap'e alınması gerekir — tek montaj bloğu şartı nedeniyle şimdilik tek
  giriş. `data-rum-region` nitelikleri de hiçbir şablona eklenmedi (rapor 60 §6 sözleşmesi).

## 6. ÖLÇÜLMEDİ / yapılmadı

1. Gerçek tarayıcıdan uçtan uca akış (web-vitals kurulamadığı için toplayıcı hiç çalışmadı).
2. Oturumlu kullanıcının beacon'ının CSRF'e takılması — kaynak koddan çıkarım (§3).
3. Toplama/scheduler halkası: `rum.aggregate()→to_metrics()` koşucusu YAZILMADI (görev
   kapsamı 1-5 dışında) — T-133/T-124 alarm beslemesi için sıradaki iş; pencere başına
   BİR çağrı kuralına dikkat (`to_metrics` sayaç katlar).
4. 50k/gün tavanı ve 30/dk hız sınırının "doğru" değerleri — trafik yok, ölçülemez.
5. Süre/performans iddiası yok.

## 7. Orkestratörden istenenler (hooks.py bende YASAKTI)

1. **Scheduler (saklama):** `scheduler_events["daily"]` listesine
   `"tradehub_core.api.rum.purge_expired_samples"` — 30 günden eski ham örneklemi siler.
   Eklenene kadar büyüme günlük tavanla sınırlı ama silme İŞLEMEZ.
2. (Sıradaki iş, fonksiyonu yazılınca) toplama işi için `hourly` kaydı — bugün eklenecek
   fonksiyon YOK, kayıt da eklenmesin.
3. `patches.txt` gerekmiyor: DocType migrate ile kuruldu, veri dönüşümü yok.
4. İsteğe bağlı site_config anahtarları: `rum_token_salt` (yoksa `encryption_key` kullanılır),
   `rum_daily_sample_cap` (varsayılan 50000).
5. Montajı AÇMAK için: tradehubfront'a `web-vitals@^6` bağımlılık onayı + `main.ts`'teki
   iki satırın yorumunu kaldırmak (§5) + storefront imaj rebuild (dist bind-mount değil).

# Faz 8 Kapanış Dosyası — API

> **Bu belge ölçümlerden derlenmiştir; çelişki hâlinde rapor kazanır.**
> Derleme tarihi: 2026-08-20 · Hazırlık: W6 kapanış dalgası (T-085 kapanış hazırlığı — imza atılmaz.)

## 1. Çıkış kapısı (91-gorev-panosu.html)

| Kapı çıktısı | Onaylayan |
|---|---|
| OpenAPI v1 dondurma + contract testleri | Teknik sorumlu |

## 2. Kapıyı karşılayan ölçümler

| Kalem | Durum | Kanıt |
|---|---|---|
| OpenAPI üretimi + bayt kilidi | **KARŞILANDI** | `docs/api/openapi-http.yaml` üretilmiş dosya; `gen_http_openapi.py --check` temiz (41 §7, 56 #6); kardeş `openapi.yaml` bayt-eşitlik testi `test_api_contracts` **126/126 OK** (32 §6, 57c #1). |
| Uç yüzeyi | **KARŞILANDI** | paths/operations/x-endpoint-count = **90/90/90**, gerçek YAML parser ile (57c §0.1; 41 §0). 32/35'teki "87" bayat. |
| Ölçüm zorunluluğu | **KARŞILANDI** | x-measured: http **69** · http-partial **20** · unmeasured **1** (`create_media_backup`, gerekçeli: 5.020 dosya) — testle kilitli (41 §2). |
| Contract testleri | **KARŞILANDI** | `test_http_api_contracts` **41/41, 0 atlama** (tam ortam değişkenleriyle); ortamsız OK (skipped=16) (41 §7, 57c #3/#4). |
| Negatif yetki kapsamı | **KARŞILANDI (örnekleme değil, tamamı)** | Misafir → oturumlu **87/87 uçta 403 İSTİSNASIZ**; seller→admin **49/49 → 403**; seller kendi kütüphanesi 33/33 uçtan uca (41 §6). |
| Sapma beyanı | **KARŞILANDI** | `x-contract-deviations` 10 madde (D1–D10: 417 kullanımı, eksik parametre→500, GET→403 vb.), `test_sapma_listesi_bos_degil` ile kilitli (41 §5). |
| manifest_batch (T-083) | **KARŞILANDI (08-20)** | 66: `manifest_batch(file_urls)` FILE_BATCH_MAX=100, **16 test OK**; FE `useMediaRenditions.load()` 2N→**1 istek**; vacuity: ignore_permissions eklenince FAILED (failures=4). |

## 3. Karşılanmayanlar / ölçülmeyenler (AÇIK)

1. **"v1 donduruldu" çağrılabilir yüzey için değil** — README §2.5'in "donmuş yüzeyi" `/api/media/v1/…` katmanı **çağrılamıyor** (0 route kuralı); `openapi-http.yaml`'da dondurma/deprecation politikası yok. 32 §10.4: "donmuş olan, istemcinin çağıramadığı katmandır."
2. **Yüzey 08-20'de değişti, bayt kilidi yeniden koşulmadı** — 65 `save_intent`'e 3 parametre, 66 yeni `manifest_batch` ucu ekledi; hiçbir rapor `gen_http_openapi.py --check` tekrarını kaydetmiyor → **90 sayısı ve kilit bayat olabilir; kapanıştan önce yeniden üret/ölç.**
3. **spectral lint YOK · schemathesis/dredd YOK · Postman/Bruno koleksiyonu YOK** (56 §5.2, 57c §1). → ARAÇ.
4. **TS SDK üretilmedi ve FE tüketmiyor** — openapi-typescript 0 isabet; `ui/src/api/client.ts` yok; `api.js` elle yazılmış (56 §5.2, 61e). → **KARAR** ("OpenAPI'den tipli TS SDK üretilsin mi?" — plan Kova D).
5. **tus/resumable KARARI açık; sunucu tarafı eksikleri**: `Idempotency-Key` repo genelinde 0 isabet; `expires_at`, `quota_remaining`, sha256 dedup yok; **`chunked.cleanup()` yazılmış ama hiçbir scheduler'a bağlı değil** — "fonksiyon var, zamanlayıcı yok" (44 §10, 57c §0.7). Protokol gerekçesi kayıtlı: "tus-js-client kurmak, konuşacağı bir sunucu olmadan ölü bir bağımlılık olurdu."
6. **`save_intent` overrides yolu HER ZAMAN 417** — Link kısıtı DB'de kaldırıldı ama "uçtan uca ölçülmedi" (57c §0.4); 3 artefakt eski gerçeği taşıyor. → KARAR + ölçüm.
7. **Zenginleştirme uçlara akmıyor** — `get_manifest` LQIP/dominant boş; `manifest_batch` version_meta taşımıyor (73 §3.2–3.3; düzeltme 1+2 satır).
8. **Contract testleri CI'da koşmuyor** — CI ortam değişkeni vermediği için gerçek HTTP yüzeyi hiçbir otomasyonda ölçülmüyor (57c §0.1, 41 §8-7).

## 4. Kapı durumu özeti

**Kapı: BÜYÜK ÖLÇÜDE KARŞILANDI, İKİ ŞERHLE.** Contract test tabanı güçlü (126 + 41 + 87/87 negatif kapsam) ve ölçüm zorunluluğu şemaya gömülü. Şerhler: (a) "dondurma" beyanı çağrılabilir yüzeye taşınmalı ve 08-20 değişikliklerinden sonra `--check` yeniden koşulmalı; (b) T-085'in SDK/lint/koleksiyon kalemleri yapılmamış iş (56 §5.4: "Faz 8 bugün KAPANMAZ").

## 5. Kaynak raporlar
`docs/reports/`: 41-t080-api-sozlesme.md · 56-d3-faz6-10-kapanis.md §5 · 57c-durum-faz8-11.md §0–1 · 32-faz8-api-kapanis.md §10 · 66-be4-manifest-batch.md · 44-t081-yukleyici.md · 73-w4-manifest-zenginlestirme.md · 61e-fe-denetim-faz8-9.md

## 6. Onay

```
Onaylayan (Teknik sorumlu): ______________________   Tarih: ______________   İmza: ______________
```

# 68 — W3A · T-140 İzlenebilirlik matrisinin FRONTEND ayağı

**Tarih:** 2026-08-20 · **Görev:** T-140 (FE ayağı) · **Kapsam:** `gen_traceability.py` FE tarayıcısı + FE test adlarına `[FR-xxx]` etiketi

---

## 1. Ne yapıldı

1. **Üretici genişletildi** (`scripts/gen_traceability.py`): yeni **F kanıt sınıfı** — üç FE koşucusu taranıyor ve her matris satırında koşucu adı görünüyor (`node:` / `vitest:` / `e2e:` öneki):
   - `node` — `admin-panel/frontend/src/**/__tests__/*.test.js` (node --test)
   - `vitest` — `tradehubfront/src/**/*.test.ts`
   - `e2e` — `tradehubfront/tests/e2e/*.spec.ts` (playwright)

   Kanıt yalnız test adının **başındaki** `[FR-xxx]`/`[NFR-xxx]` etiketi; ad ortasındaki serbest metin sayılmaz. `test.skip`/`it.skip`/`fixme`/`todo` **koşmayan** testtir, kapsama girmez (`media-seller-upload.spec.ts`'nin 6 skip senaryosu bu yüzden bilinçli olarak etiketlenMEdi).

2. **31 FE testi etiketlendi** (34 etiket; bazı testler iki gereksinim taşıyor). Yalnız test ADI dizgeleri değişti; assertion/mantık/fixture'a dokunulmadı.

3. Matris yeniden üretildi; vacuity kanıtı alındı (§5).

## 2. Kapsama — önce / sonra

| Ölçüm | Önce | Sonra |
|---|---:|---:|
| FE testi olan gereksinim (F kanıtı) | **0** | **15** |
| En az bir teste bağlı (A ∪ C ∪ F) | 76 (%37.6) | **82 (%40.6)** |
| YALNIZ FE ile kapsanan (A/C yok) | 0 | **6** (FR-012, FR-126, FR-127, NFR-024, NFR-028, NFR-033) |
| FE test adındaki etiket | 0 | 34 |
| Taranan FE testi (koşan) | — | 1152 (node 822 · vitest 233 · e2e 97) + 8 skip |

FE kanıtı kazanan 15 gereksinim: FR-011, FR-012, FR-015, FR-016, FR-018, FR-028, FR-060, FR-121, FR-123, FR-124, FR-126, FR-127, NFR-024, NFR-028, NFR-033.

## 3. Etiketlenen testler (repo bazında)

**admin-panel (node --test) — 23 test:**

| Dosya | Test → etiket |
|---|---|
| `lib/media/upload/__tests__/preflight.test.js` | megapiksel tavanı `>` reddi → [FR-011] · PNG boyutu başlıktan → [FR-011] · kısa kenar `>=` → [FR-015] (adın sonundaki serbest "— FR-015" öneke taşındı) · bağıl sapma formülü → [FR-016] · izinsiz oran → [FR-016] · max_count → [FR-018] · animasyon yasağı → [FR-012] |
| `utils/__tests__/uploadPolicy.test.js` | politika reddi retry edilmez (koda bakar) → [FR-060] |
| `lib/media/upload/__tests__/session.test.js` | politika reddi YENİDEN DENENMİYOR → [FR-060] |
| `lib/media/simulator/__tests__/srcsetParity.test.js` | profil merdiveni + upscale kelepçesi → [FR-028] (ad içindeki "FR-028" öneke taşındı) · 15 bölge `sizes` → [FR-121] · `srcset` dizgesi → [FR-121] |
| `components/media/delivery/__tests__/mediaDelivery.test.js` | AVIF→WebP sırası → [FR-121] · srcset artan/tekil → [FR-121] · sizes+srcset birlikte → [FR-121] · video kutusu önceden → [FR-124] · ölçüsüz videoda kutu → [FR-124] · sessiz-döngü (muted+playsinline+loop) → [FR-127] · prefers-reduced-motion JS kararı → [FR-126] |
| `components/media/__tests__/mediaCls.test.js` | intrinsic öznitelik → [FR-124][NFR-033] · ölçüsüz görselde kutu → [FR-124] · kaynak yokken kutu → [FR-124][NFR-028] · medya ekranları önceden ayrılmış → [FR-124] |

**tradehubfront (vitest) — 6 test:**

| Dosya | Test → etiket |
|---|---|
| `src/components/media/ResponsiveImage.test.ts` | çok biçimli `<picture>` sarmalı → [FR-121] · bölge sizes ezer → [FR-121] · width/height her zaman → [FR-124] · içsel ölçü yoksa yedek yol (CLS) → [FR-124] · loading=lazy/decoding=async → [NFR-033] |
| `src/lib/upload-ui/uploader.test.ts` | compress:false'ta sıkıştırma yok → [NFR-024] |

**tradehubfront (playwright e2e) — 2 test:**

| Dosya | Test → etiket |
|---|---|
| `tests/e2e/media-delivery-manifest.spec.ts` | S3 — ham dosya istenmez → [FR-123] · S2 — içsel ölçü + tavana kadar srcset → [FR-121][FR-124] |

Her etiket, testin gövdesi OKUNARAK verildi (ör. FR-016 için `min(|ar−hedef|/hedef)` bağıl formülünün assert edildiği, FR-127 için `muted`+`playsinline` assert'lerinin varlığı doğrulandı).

## 4. Etiketlenemeyenler — eşleşme bulunamadı / emin değilim

| Gereksinim | Aday test | Neden etiketlenmedi |
|---|---|---|
| FR-022 (avatar dairesel güvenli alan) | `cropSafeArea.test.js` | Test tam tersini ölçüyor: `user.avatar`'da güvenli alan bandı YOK (`safeBandFor === null`). FR uygulanmamış; sahte kapsama olurdu. |
| FR-023 / FR-024 (cover/banner güvenli alan) | `cropSafeArea.test.js` "eşikler canlı politikayla birebir" | Test eşik SABİTLERİNİN politikayla eşitliğini doğruluyor; taşan içerikte uyarı ÜRETİMİNİ sınayan pozitif test yok. Konfig paritesi ≠ davranış kanıtı. |
| FR-009 (magic-byte uyuşmazlığı RED) | `preflight.test.js` "uzantı/imza uyuşmazlığı UYARI" | Test FR'nin tersini (bugünkü warn davranışını) kilitliyor. |
| FR-112 (imzalı süreli URL) | `mediaAccessControl.test.js` | Test yalnız composable'ın `get_signed_url` ucunu çağırdığını grep'liyor; yetki/imza davranışı sınanmıyor. |
| FR-080 (kota kullanımı + %80 uyarı) | — | Panelde kota gösterim/uyarı testi bulunamadı (`mediaUsage.test.js` dosya-kullanım taraması, kota değil). |
| NFR-028 için e2e S11/S12 | `media-delivery-manifest.spec.ts` | Manifest ucu arızası ≠ "görsel yok"; bağ dolaylı, emin olunamadı. |
| T-141 S1/S4/S5/S9/S10/S11b | `media-seller-upload.spec.ts` | Hepsi `test.skip` — koşmayan test kapsam sayılmaz; tarayıcı da bunları bilinçli dışlıyor. |
| Crop parite testleri (`cropPixelParity`, `cropGeometryParity`, `cropHandles`) | — | Panel↔sunucu matematik paritesini sınıyor; SRS'te birebir karşılığı olan tek bir FR yok. |
| LcpPreload / rum / approvalGate / videoDecision testleri | — | NFR-008 (CWV bütçesi) ölçümü değil, mekanizma doğruluğu; ilişki dolaylı. |

## 5. Vacuity kanıtı — tarayıcı gerçekten etikete bakıyor

1. `preflight.test.js`'ten `[FR-018]` öneki geçici silindi → yeniden üretimde FR-018 satırından `node: …preflight.test.js :: max_count aşımı reddediliyor` girdisi DÜŞTÜ; özet sayaçlar F 15→14, etiket 34→33 oldu.
2. Etiket geri kondu → yeniden üretim, etiketli sürümle **bayt bayt aynı** (`diff` boş).

## 6. Doğrulama — test koşumları (önce → sonra)

| Paket | Önce | Sonra | Durum |
|---|---|---|---|
| Panel `npm test` (node --test) | 833 pass / 0 fail | **833 pass / 0 fail** | ✅ korundu |
| Storefront `npx vitest run` | 250 pass / **6 fail** | 249 pass / **7 fail** | ⚠ aynı 6 kırık AYNEN duruyor; +1 YENİ kırık **benim değişikliğimden DEĞİL** (aşağıda) |
| Storefront `npx playwright test tests/e2e/media-*` | 6 pass / 8 skip | **6 pass / 8 skip** | ✅ korundu |

**Yeni vitest kırığı ölçüldü:** `src/security/nginxCspContract.test.ts > requires the storefront anti-framing header`. Sebep: iki koşum ARASINDA paralel bir görev (T-131 medya servis sertleştirmesi) çalışma ağacındaki `nginx.conf.template`'e ikinci bir `add_header X-Frame-Options "DENY"` satırı ekledi (satır 387); test ilk DENY'ı SAMEORIGIN'e mutasyonlayıp doğrulayıcının şikayet etmesini bekliyor, ikinci DENY şikâyeti susturuyor. Bu depodaki tek izlenen değişikliğim `uploader.test.ts`'te 1 satırlık ad değişikliği; kırık test dokunduğum hiçbir dosyayı okumuyor. T-131 sahibinin nginx değişikliğiyle birlikte bu testi güncellemesi gerekir.

## 7. Yol açılan iki bakım bulgusu (üreticide düzeltildi)

- **Eşleme dosyası bayattı:** medya testleri `tests/` → `tradehub_core/tests/` taşınmış (commit `1ec9b5e`), `req-test-map.json` eski yolları taşıyor ve HEAD'deki betik de exit 2 ile düşüyordu (matris yeniden üretilemiyordu). Üreticiye göç uyumu eklendi: eski yol yoksa `tradehub_core/` önekiyle çözülüyor; fixture `manifest.json` yolu için de aynı düzeltme yapıldı (B izleri 23 gereksinimde geri geldi).
- Matristeki Python sayıları da tazelendi: 111 dosya / 2811 fonksiyon → 143 / 3380 (taşınma + o sırada paralel görevlerin eklediği testler).

## 8. Yeniden üretme

```bash
cd tradehub_core && python3 scripts/gen_traceability.py          # matrisi üret
python3 scripts/gen_traceability.py --check                       # CI bayatlık kontrolü (bugün: güncel)
```

# 93 — W8 · Panel FE süpürmesi

**Tarih:** 2026-08-20 · **Kapsam:** UploadDropzone a11y (rapor 89 bulguları) + T-140 kalan etiketler + eksik i18n anahtarları (rapor 78/89) + panel tam doğrulama

Kural gereği her kalem önce ÖLÇÜLDÜ, sonra yapıldı. Durum sözlüğü:
**ZATEN YAPILMIŞ** / **YAPILDI** / **YAPILAMADI**.

---

## 1. UploadDropzone a11y — YAPILDI (ölçüm: yapılmamıştı)

**Önce ölçüldü:** `UploadDropzone.vue`'da rapor 89'un iki bulgusu aynen duruyordu
(`label` critical: adsız gizli `<input type="file">`; `nested-interactive` serious:
`role="button"` içinde odaklanabilir input) ve `mediaAxe.test.js`
`UPLOADER_BASELINE = 2` ile kilitliydi.

**Düzeltme (görsel değişiklik yok):**

- `<input type="file">` bırakma alanının (`role="button"` div) **dışına** taşındı —
  bileşen çok köklü (Vue 3 fragment); tek kullanıcı `MediaUploader.vue` yalnız
  bildirilmiş prop/emit geçirdiği için attribute-fallthrough riski yok. Input zaten
  `display: none` (SSR/axe taramasında CSS uygulanmadığı için görünüyordu) ve
  tetikleyicisi yine bırakma alanı → ekranda hiçbir şey değişmedi.
- Input'a `aria-label` bağlandı (`media.uploader.dropAria` metniyle).

**Kilit:** `UPLOADER_BASELINE` 2 → **0** (`mediaAxe.test.js`), yorum bloğu güncellendi.

**Vacuity kanıtı:** düzeltme geçici geri alındı → test KIRMIZI
(`Taban çizgi 0, ölçülen 2: label [critical] ×1 … nested-interactive [serious] ×1`);
düzeltme geri kondu → 7/7 yeşil.

---

## 2. T-140 kalan etiketler — YAPILDI (ölçüm: hiçbiri etiketli değildi)

**Önce ölçüldü:** `[FR-`/`[NFR-` etiketi taşıyan FE dosyaları yalnız W3-A'nın 9
dosyasıydı (34 etiket). W4-W7'nin yeni test dosyalarının HİÇBİRİ etiket taşımıyordu.
Ayrıca `gen_traceability.py` panel e2e paketini (`admin-panel/frontend/tests/e2e/`)
HİÇ taramıyordu — oraya yazılacak etiket kapsama giremezdi.

**Yapılan (W3-A kuralları: yalnız EMİN eşleşme, etiket adın BAŞINA, assertion'a
dokunulmadı):**

| Dosya | Test → etiket | Gerekçe (gövde okundu) |
|---|---|---|
| `policyEngine.test.js` | kısa kenar tam eşikte ihlal üretmez → **[FR-015]** (ad sonundaki "(FR-015)" öneke taşındı) | `>=` eşitlik semantiği: 100 geçer, 99 ret |
| `policyEngine.test.js` | oran toleransı BAĞIL → **[FR-016]** | bant içi 101/100 geçer, 103/100 ret — bağıl tolerans |
| `policyEngine.test.js` | EN YÜKSEK aksiyon kazanır, uyarılar düşmez → **[FR-049]** | `action=reject` + warn ihlali listede — FR-049 metniyle birebir |
| `media-upload-security.spec.ts` | S1 → **[FR-015][FR-062]** | <1000 kısa kenar UI'da bloklanır; sebep ölçüyü (900) VE gerekeni (1000) basar, fix satırı var (NEDEN+NASIL) |
| `media-upload-security.spec.ts` | S1b → **[FR-015]** | sunucu kapısı: 900×900 → 417 `product_image_short_edge_too_small` |
| `media-upload-security.spec.ts` | S10 → **[FR-011][FR-014]** | bomb → 417 `upload_image_bomb` (piksel tavanı); SVG-XSS → 417 (SVG reddi sürüyor) |
| `media-dedup.spec.ts` | S9 → **[NFR-050]** | "aynı dosya 2× → tek asset" = "aynı içerik tek fiziksel dosya" |

**Betik genişletmesi:** `gen_traceability.py`'ye 4. FE koşucusu eklendi:
`panel-e2e` → `admin-panel/frontend/tests/e2e/*.spec.ts` (T-141 senaryoları rapor
86/87 ile panele taşınmıştı; taranmadan etiketleri sayılamazdı).

**Matris — önce / sonra (yeniden üretildi, `--check` yeşil):**

| Ölçüm | Önce | Sonra |
|---|---:|---:|
| En az bir teste bağlı (A ∪ C ∪ F) | 82 (%40.6) | **83 (%41.1)** |
| F kanıtı olan gereksinim | 15 | **19** |
| FE test adındaki etiket | 34 | **43** |
| Taranan FE test dosyası / testi | 162 / 1245 | **166 / 1255** (panel-e2e 4 dosya · 10 test) |

Yeni F kanıtı kazananlar: FR-014, FR-049, FR-062, NFR-050 (FR-049 **ilk kez**
kapsandı — A/C kanıtı da yoktu). FR-011/015/016'nın F kanıtı derinleşti.

**Vacuity kanıtı:** `[NFR-050]` etiketi geçici silindi → yeniden üretimde F 19→18,
`media-dedup` satırı matristen düştü; etiket geri kondu → matris **bayt bayt aynı**.

**Etiketlenmeyenler (emin olunamadı — sahte kapsama yazılmadı):**

| Aday | Neden etiketlenmedi |
|---|---|
| `dedupCheck.test.js` (birim) | İstemci uyarı mekanizması; NFR-050'nin kendisi (depo tekliği) S9'da ölçülüyor — bağ dolaylı |
| `hlsPlayback.test.js` / `hlsVideo.test.ts` / `ProductVideoSection.test.ts` | HLS teslimi SRS'te FR olarak yok; autoplay testi `muted`'ı assert ediyor ama `playsinline`'ı ETMİYOR → FR-127 verilmedi |
| `videoDecision.test.js` | NFR-011'e (gereksiz re-encode yok) bağ dolaylı: testler yorumlayıcı PARİTESİNİ ölçüyor, kapı politikasını değil |
| `policyEngineParity.test.js` | NFR-045/046 adayı ama ikiz motor tam da "aynı kural iki yerde" — parite testinin NFR'yi kanıtladığı savunulamaz |
| `lcpImagePreload.test.js`, `cardGridWindow.test.js` | NFR-008 (CWV) ölçümü değil mekanizma doğruluğu — W3-A'nın aynı gerekçesi |
| `mediaOrphans.test.js`, `sellerMediaFolders.test.js` | FR-107 arka uç uzlaştırması; composable dürüstlük sözleşmesi dolaylı / klasör UI'ının SRS karşılığı yok |
| `mediaVideoStatus.test.js` | FR-118 SRS satırı ÖZELLİKLE private-transcode-atlandı mesajını istiyor (`private_transcode_atlandi`); rozet testleri bunu ölçmüyor |
| `media-crop-approval.spec.ts`, `media-console-access.spec.ts` | S4/S5 onay kapısı ve S11b ekran kapısının SRS'te birebir FR'si yok (FR-115/NFR-017 metinleri farklı şeyi istiyor) |
| `media-video-pipeline.spec.ts` (S7/S8) | `test.skip` — koşmayan test kapsam sayılmaz |

---

## 3. Eksik i18n anahtarları — YAPILDI (ölçüm: dört dilde de eksikti)

**Önce ölçüldü (import-temelli — dört locale modülü `import` edilip düz anahtar
kümesi çıkarıldı; regex değil):** görevin saydığı setlerin TAMAMI dört dilde de
eksikti:

- `media.detail.tabsLabel` + `tab.{summary,renditions,usage,quality,versions}` → 0/6
- `media.versions.*` (rapor 89) → 0/28 (attr.7 + jobState.4 dâhil)
- `media.uploader.*` (rapor 78) → 2/11 (yalnız `dropActive`, `pasteHint` vardı) → 9 eksik
- `media.preflight.*` (rapor 78) → `allClear/yes/no/unmeasured` + `fact.{8}` → 0/12;
  `reason.*` 19 kod ve `fix.*` 6 kod (yalnız `duplicate_in_library` vardı)

Ölçüm ayrıca görev listesinde olmayan İKİ şeyi buldu (aynı detay çekmecesinin
Kalite sekmesi — locale dosyaları bu turda bende olduğu için düzeltildi):

- `media.quality.*`: `title/caption/loading/denied/failed/notInPipeline` +
  `col.{source,result}` (+ en'de `col.attribute`) + `attr.{7}` → dört dilde eksik
- **Yer tutucu uyuşmazlığı:** `MediaQualityPanel` `savings`'e `{percent,from,to}`
  geçiyor, dört sözlük de `{pct}` bekliyordu → `{pct}` → `{percent}` düzeltildi

**Yapılan:** 95 anahtar/locale eklendi (en'de 96 — `quality.col.attribute` da
eksikti); rapor 89'un KULLANILMIYOR dediği `media.versions.notInstalled/scopeNote`
silindi (kodda 0 kullanım — grep ile ölçüldü). Çeviri kuralları uygulandı: TR
metinler bileşenlerdeki `t(k, {}, "TR")` varsayılanlarından **birebir**; yer
tutucular dört dilde birebir; teknik jetonlar (MB, MP, kbps, DPI, Codec, Enter,
Ctrl+V, sn) çevrilmedi; en/ru/ar mevcut terminolojiyle hizalı (ör. renditions =
Производные / النسخ المشتقة).

**Doğrulama:** dört dosya `prettier --write` + `--check` temiz; `node --check`
dördü de ayrıştırıyor; import-temelli sayım: `media.*` alt ağacı dört dilde de
**413 anahtar ve küme olarak ÖZDEŞ**. Toplam anahtar: tr 8017→**8110**,
en 8036→**8130**, ru 7226→**7319**, ar 7226→**7319**. Yan kanıt: `mediaAxe`
koşumundaki `[intlify] Not found 'media.uploader.…'` uyarıları kayboldu.

---

## 4. Panel tam doğrulama — YAPILDI

| Kapı | Sonuç |
|---|---|
| `npm test` | **906 test · 901 pass · 0 fail · 5 skip** (taban 906/901 korundu) |
| `npm run lint` | **0 hata** (2 uyarı `PlansTab.vue` no-unused-vars — önceden vardı, bu turun dosyası değil) |
| `npm run build` | **temiz**, 9.03 s |
| `npm run test:e2e` | **11 test · 10 passed · 1 skipped · 0 failed** (skip: S11b superadmin-S3 — bilinçli, oturum satıcı) |
| `gen_traceability.py --check` | **güncel** (matris yeniden üretildi) |

---

## 5. Dokunulan dosyalar

| Dosya | İş |
|---|---|
| `admin-panel/frontend/src/components/media/upload/UploadDropzone.vue` | input dışarı + aria-label (Kalem 1) |
| `admin-panel/frontend/src/components/media/a11y/__tests__/mediaAxe.test.js` | `UPLOADER_BASELINE` 2→0 |
| `admin-panel/frontend/src/lib/media/policy/__tests__/policyEngine.test.js` | 3 test adına etiket |
| `admin-panel/frontend/tests/e2e/media-upload-security.spec.ts` | 3 test adına 5 etiket |
| `admin-panel/frontend/tests/e2e/media-dedup.spec.ts` | 1 etiket |
| `tradehub_core/scripts/gen_traceability.py` | `panel-e2e` FE kaynağı |
| `tradehub_core/docs/test/traceability.md` | yeniden üretildi |
| `admin-panel/frontend/src/i18n/locales/{tr,en,ru,ar}.js` | +95/96 anahtar, −2 ölü anahtar, `{pct}`→`{percent}` |

Yasaklara uyuldu: commit yok, router/navigation yok, backend'e (matris betiği
hariç) dokunulmadı, başka bileşen değiştirilmedi.

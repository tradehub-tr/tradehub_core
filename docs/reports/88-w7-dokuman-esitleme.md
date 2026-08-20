# 88 — W7: Doküman eşitlemesi (SAD · ADR · SRS → 2026-08-20 ölçülmüş gerçek)

**Tarih:** 2026-08-20 · **Kapsam:** `docs/sad/**`, `docs/adr/**`, `docs/srs/**`,
`docs/test/traceability.md` (yalnız yeniden üretim), `docs/closure/faz{1,2,3}-kapanis.md`
(tek satır ek). **Kaynak koda dokunulmadı; commit atılmadı.**
**Görev:** T-030/T-031/T-035 ve T-019/T-029'un doküman yarıları — belgelerin
koddan geride olduğu iki kez ölçülmüştü (rapor 61: "45 dosya / 3.355 satır fark").

---

## 0. Özet

| Ölçüm | Değer |
|---|---:|
| Güncellenen/oluşturulan dosya | **14** (7 düzenleme + 1 yeniden üretim + 5 yeni ADR + bu rapor) |
| Düzeltilen çelişki/bayatlık | **17** (aşağıda; her biri gövdede `(2026-08-20 ölçümü: rapor NN)` etiketli) |
| Açılan ADR | **5** (2 KABUL + 3 ÖNERİLDİ/BEKLİYOR) |
| Çözülemeyen / bilerek dokunulmayan | **5** (§4) |

Her düzeltme ya bu oturumda ölçüldü (grep/dosya/JSON okuması) ya numaralı bir
ölçüm raporuna bağlandı. Ölçülemeyen hiçbir iddia belgeye yazılmadı.

---

## 1. SAD (`docs/sad/SAD-v1.0.md` + `interfaces.md`)

Rapor 21'in 8 bloklayıcısından **belge işi olan 5'inin belge yarısı kapandı**;
kayıt SAD §14.6'da (yeni bölüm). En önemli düzeltmeler:

| # | Çelişki (öncesi) | Düzeltme (kanıt) |
|---|---|---|
| 1 | **M-04 / S-03:** SAD "Yeni DocType açılmaz" diyordu; repoda **13 medya DocType'ı** sayıldı (`tradehub_core/tradehub_core/doctype/` — bu oturumda `ls` ile) | §2.2 S-03 "KARAR ÇÜRÜDÜ" olarak yeniden yazıldı, 13 DocType adlı listelendi; terk gerekçesinin hiçbir belgede olmadığı notu korundu (rapor 30 §3) |
| 2 | **M-09 + dedup:** §5.1 üretim akışını hiç anlatmıyordu; rapor 57 "üretim tek girdili version_hash kullanıyor" demişti — bugün üretim **4 girdili** `dedup.version_hash` + INV-09 hash'li adres kullanıyor (rapor 64; kanca `hooks.py:350`) | §5.1'e "Üretimdeki gerçek akış" bloğu eklendi |
| 3 | **M-10 + sözleşme:** gerçek teslim yolu (`api/media_manifest`, misafire açık `:181`/`:223`) ve OpenAPI yüzeyi belgede yoktu | §5.4'e eklendi: `manifest_batch` `version` anahtarı (rapor 66/73), **OpenAPI-HTTP 100 uç** (90→100; bu oturumda `grep -c operationId` = 100 doğrulandı; rapor 80) |
| 4 | **M-07:** §7.2 "türev merdiveninin durum alanı yok — bilinçli" diyordu; üretim `Media Processing Job`'da tam durum makinesi + `Media Version` tutuyor | §7.2'ye çelişki notu eklendi — satır tarihsel niyeti anlatır, bugünü değil |
| 5 | **Video motoru:** §5.2 yalnız eski VP9/Opus hattını anlatıyordu; yeni H.264 motoru DEV'de **ilk gerçek koşumunu** yaptı — VMAF ilk kez ölçüldü: **89,34**; INV-05 ilk kez gerçek çıktıyla tuttu (%11,44) (rapor 81) | §5.2'ye motor gerçeği + "video için boru hattı YOK" boşluğu (rapor 81 §8) eklendi |

Diğer SAD düzeltmeleri: **M-01** — gövdedeki 6 `media_engine` kalıntısı gerçek
yola (`tradehub_core/media/pipeline/`) çevrildi, §2.1 ağacındaki `tests/` kökü
`tradehub_core/tests/` yapıldı · **S-05** — MinIO/S3 adaptörünün yazılıp
varsayılan kapalı olduğu (ADR-0015, 91 gerçek MinIO testi — rapor 23) ve MinIO
kabulünün **bugün W7-4'te yeniden koştuğu** not edildi (sonuç W7-4 raporunda) ·
**§4.1 PolicyEngine** satırına 13/13 protokol uyumu (rapor 43) + **TS ikizi
393/393 parite** (rapor 77) işlendi · **§14.6** — kapı karnesi: M-01/M-04/M-07/
M-09/M-10 belge yarıları kapandı; M-14 ve M-18 AÇIK (§4) · izin modeli notu:
`owner_seller` zincirli kiracı izolasyonu (`permissions.py:2627-2789`) +
`if_owner` tuzağının kaldırılması (`permissions.py:2066`, `v15_3_6` yaması).

**`interfaces.md` (T-031 "dondurulmuş arayüzler"):** test sayısı **69 → 75**
(POLICY_IMPLS'e üretim motoru girdi — rapor 43; başlık + §6 + koşum komutu),
bayat modül yolu düzeltildi (`media_engine.contracts.signatures` →
`tradehub_core.media.pipeline.contracts.signatures`, gerçek yol
`test_contracts.py:210`'dan doğrulandı), §2.4'e üretim uygulaması durumu +
dondurulmamış `evaluate` yüzeyi notu, **yeni §8**: sözleşmenin bugünkü üç
tüketici katmanı (OpenAPI-HTTP 100 uç + `types.gen.ts`/`client.ts` — rapor 80;
TS policy ikizi 393 vektör — rapor 77; `RenderManifest.extra["version"]`
zenginleştirmesi — rapor 66/73; imzalar DEĞİŞMEDİ).

## 2. ADR (17 → 22)

| ADR | Başlık | Durum |
|---|---|---|
| **0018** | HLS oynatma için `hls.js` eklenir (MSE fallback) | **KABUL** — kullanıcı onayı; uygulama W7'de (rapor 85). Bu rapor yazılırken ilk iz ölçüldü: `admin-panel/frontend/package.json:42` → `hls.js ^1.7.1` |
| **0019** | HLS basamaklarına fayda/bütçe kapısı | **KABUL** — W7-1 uyguluyor; dayanak: 720p basamağı kaynaktan 1,26×, paket 2,84× (rapor 81 §4; rapor 39/56'da ikinci ölçüm) |
| **0020** | Devam edebilir yükleme: tus mu, mevcut `chunked.py` mi | **ÖNERİLDİ · BEKLİYOR** — sunucuda tus yok (rapor 44 §3), çalışan chunked sözleşmesi var; `Idempotency-Key` iki tarafta da eksik |
| **0021** | VMAF eşiği (93 ↔ INV-05, gerçek ölçüm 89,34) | **ÖNERİLDİ · BEKLİYOR** — A/B/C seçenekleri ölçülmüş bedelleriyle rapor 56 §4.3'ten taşındı; rapor 81'in yeni verisi eklendi (libvmaf artık imajda → "uygulanamaz" engeli düştü, karar kaldı) |
| **0022** | K7 kota: türev sayımı ↔ ADR-0009 | **ÖNERİLDİ · BEKLİYOR** — kapak videosu başına ~6 nesne/~19 MB (rapor 56 §7.4); HLS ile 411 dosya/koşum (rapor 81 §9) |
| README | Dizin + "gerilimler" güncellendi | 0007'nin "video hattı hiç çıktı vermiyor" cümlesi eskidi işareti (rapor 81); 0009↔K7 → ADR-0022'ye bağlandı; ÖNERİLDİ istisnası açıklandı |

**Hiçbir BEKLİYOR kalemi karara bağlanmadı** — üç TASLAK ADR'nin "Karar"
bölümü açıkça BEKLİYOR der.

## 3. SRS + izlenebilirlik

- **G5 "yanlış şeyi ölçen kapı" bulgusu (rapor 57) SRS'te işaretlendi ve
  bugün YENİDEN ölçülerek doğrulandı:** `content_rules.json`
  `calibration_status` artık `"TRIGGER_RATE_MEASURED_UNLABELED"` (bu oturumda
  JSON'dan okundu) → §6.7 G5'in harfî koşulu (`!= "UNCALIBRATED"`) **kalibrasyon
  yapılmadan sağlanır hâle geldi** (9 kuralın 8'i hâlâ "KALİBRE EDİLMEDİ").
  Üç yerde işaretlendi: §6.7 kapı tanımı (bağlayıcı koşul `threshold_status`
  sütununa çevrildi), §6.7-C G5 satırı, §0.3-C rev3 T4 satırı. Kapı ❌ AÇIK kalır.
- Rapor 57'nin diğer iki "yanlış ölçen kapı" bulgusu (`cropPixelParity`
  düzeneği, `test_hooks_kaydi_henuz_yok`) SRS metninde **geçmiyor** (grep 0) —
  SRS'te işaretlenecek yerleri yok, test tarafının işi.
- **`docs/test/traceability.md` yeniden üretildi (iki kez):** `--check`
  KIRMIZI (bayat) ölçüldü → betik koşuldu; SRS düzenlemelerim + paralel W7
  ajanlarının test eklemeleri dosyayı yeniden bayatlattı → ikinci koşum →
  `--check` **yeşil**. Son matris: 202 gereksinim, 82 kapsanan (%40,6),
  120 KAPSANMIYOR; taranan 148 Py + 161 FE test dosyası (paralel ajanlar
  çalışırken sayılar canlı kayıyor — W6'daki 147/159'dan fark bu).
  Not: betiğin stdout'u "110 gereksinim KAPSANMIYOR" derken ürettiği dosya
  "120" yazıyor — betik kusuru adayı, dosyaya dokunulmadı (elle düzenleme yasak).

## 4. ÇELİŞKİ / bilerek dokunulmayan

1. **SAD M-14** — taslak (`draft`) politikanın üretim kararına etkisi için
   mimari kural hâlâ yok. Kural koymak KARAR işidir; bu tur ölçüm/belge işiydi.
2. **SAD M-18 belge yarısı** — içerik-adresli adlandırmanın çok-kiracılı bedeli
   §10.1'e hâlâ yazılmadı (kod azaltımı yerinde). Bedel anlatımı güvenlik
   ölçümlerinin sahibince yazılmalı; uydurmadım.
3. **SAD §9.3 türev sayıları + §11 A-4/A-7/A-8** — bu tur yeniden ölçülmedi
   (canlı DB/parti koşumu ister); SAD-G8'in bu yarısı AÇIK bırakıldı.
4. **A-1 kanonik politika seti (SPOF-8 / SRS T6/G1)** — hangi kök kanonik,
   karar hâlâ yok; iki belge de mevcut ifadeleriyle bırakıldı.
5. **`gen_traceability.py` 110↔120 tutarsızlığı** (§3) — betik kusuru adayı,
   kaynak koda dokunma yasağı gereği düzeltilmedi, kayda geçirildi.

## 5. Doğrulama

- `python3 scripts/gen_traceability.py --check` → **yeşil** (dosya güncel).
- Rapor atıfları: 84–87 numaraları bu rapor yazılırken henüz doğmamıştı
  (W7 ajanları koşuyor); onlara atıflar "W7-1/W7-4 raporu" ve "rapor 85
  (hls.js)" biçiminde, görev tanımındaki numaralandırmayla verildi.
- Closure dosyalarına yalnız tek satır eklendi; **imza satırlarına dokunulmadı.**

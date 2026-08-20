# 77 · W4 — Politika motorunun TypeScript ikizi + çapraz parite (T-033'ün eksik yarısı)

**Tarih:** 2026-08-20 · **Kapsam:** T-033 kabul kriteri 4 — "Aynı politika motoru client
tarafında da çalışıyor (paylaşılan JSON, TS uygulaması) ve iki taraf aynı sonucu veriyor
(çapraz test)."

## 1. Ölçülen mevcut durum

- **Python motoru zaten saf.** `tradehub_core/media/pipeline/policy/engine.py` (1817
  satır) `frappe` içermiyor; tek IO noktası `PolicyRegistry.load()`'un slot JSON'larını
  diskten okuması. Karar yolu (`evaluate(slot, probe_dict, role)`) sözlük girdiyle saf
  fonksiyon — **Python tarafında saf-çekirdek yeniden düzenlemesi GEREKMEDİ, Python'a
  dokunulmadı.** Kanıt: konteyner dışında (macOS python3 3.9.6) `PolicyEngine()` kuruldu
  ve `evaluate` koştu.
- **Protokol uyumu (57 raporundaki bulgunun bugünü):** ölçüldü —
  `isinstance(PolicyEngine(), contracts.policy.PolicyEngine)` → `True`, 13/13 metot
  mevcut. Eski "somut sınıf 13/13'ü karşılamıyor" bulgusu kapanmış durumda.
- **Paneldeki en yakın şey** `upload/vendor/slotPolicy.js` — ön kontrolün DAMITILMIŞ alt
  kümesi (`on_violation`/`messages`/`master`/`profiles`/`content_rules` yok). İkiz motor
  ham politikayı ister; o vendor'a dokunulmadı (yalnız okundu), ikiz kendi vendor
  zincirini kurdu.

## 2. Karar yüzeyi (neyin ikizi yapıldı)

**Girdi** — `evaluate(slot_key, probe, role)`:

- `probe`: `MediaProbe`'un snake_case sözlüğü (dosya AÇILMADAN bilinenler + ölçülenler):
  kimlik (`filename, extension, byte_size`), tür (`kind, detected, mime, fmt`), geometri
  (`width, height, exif_orientation`), görsel özellikleri (`has_alpha, animated`),
  okunabilirlik (`readable, loadable`), güvenlik bayrakları
  (`extension_matches_content, leading_marker, appended_payload, container_valid,
  is_data_uri, scan_clean`), video (`duration_s, bitrate_bps, frame_rate, …`), bağlam
  (`existing_count, is_private`). `None`/eksik alan = "ölçülmedi" → ilgili kural
  değerlendirilmez ve `skipped`'a yazılır.
- `role`: boşsa rol kuralı uygulanmaz.

**Çıktı** — `Decision.to_dict()` ile birebir aynı nesne:
`{allow, slot, role, action, violations[], normalized_targets, skipped[],
policy_version, policy_status}`. Her ihlal: `{code, rule, block, action,
message{tr,en}, hint{tr,en}, observed, expected, retryable, source}`.

**Kural blokları** (Python'la aynı sıra): rol → güvenlik → accept (uzantı/koşullu
SVG/MIME/bayt/megapiksel/animasyon/data-URI/okunabilirlik) → require (kısa-uzun kenar,
alan, oran toleransı, aspect bandı, adet) → video (süre/bitrate/fps) → master
(under-spec uyarısı) → content_rules (ölçülebilir 8 metrik; piksel analizi isteyenler
`skipped`). Birden çok ihlalde EN YÜKSEK aksiyon; `warn`/`auto_fix` engellemez;
`ignore` listeden düşer; `review`/`manual_review`/`reject` engeller.

**Kapsam dışı (bilinçli):** 13 metotluk sözleşme yüzeyi (`master_spec`,
`rendition_specs`, `validate`…) — sunucu üretim parametreleri; istemcide kopyalamak
ikinci doğruluk kaynağı üretirdi. T-033'ün istediği API `evaluate` yüzeyidir.

## 3. Kurulan zincir (depodaki kanıtlanmış desen — icat yok)

`crop_geometry` (esbuild ikiz + sha256 manifest) + `sync-simulator` (gömülü Python ile
vektör üretimi) desenlerinin birleşimi:

| Dosya | Ne |
|---|---|
| `admin-panel/frontend/src/lib/media/policy/engine.ts` | İkiz motor (yazılan kaynak; tipli) |
| `…/policy/vendor/engine.js` | Tipleri silinmiş koşan kopya (`transformWithEsbuild`; Node 20'de tip soyma yok — crop zincirindeki aynı gerekçe) |
| `…/policy/vendor/slot_policies.js` | 9 slot politikasının HAM kopyası + `FLOAT_REPRS` |
| `…/policy/vendor/policy_vectors.json` | 393 parite vektörü — **kararları Python motoru koşturularak üretildi** |
| `…/policy/vendor/vendor.manifest.json` | Kaynak sha256 zinciri (engine.py, errors.py, probe.py, manifest.json, live-probe.json, 9 slot JSON + engine.ts→engine.js türetme halkası) |
| `…/policy/index.js` | Tek meşru kapı (`defaultPolicyEngine()`, `evaluate()`) |
| `admin-panel/frontend/scripts/sync-policy-engine.mjs` | Senkron betiği (`npm run sync:policy` / `sync:policy:check` / `parity:policy`) |
| `…/policy/__tests__/policyEngineParity.test.js` | 393/393 parite + hash zinciri + sahiplik korumaları (9 test) |
| `…/policy/__tests__/policyEngine.test.js` | Motor birim testleri (13 test) |

`FLOAT_REPRS` neden var: JSON `2.0` taşıyor, `JSON.parse` bunu 2'ye indiriyor ama
Python mesajda `str(2.0)="2.0"` yazıyor (ölçülen tek nokta:
`require.aspect_band.max_w_over_h` — brand/seller logo bandı "0.5–2.0"). Senkron
betiğindeki gömülü Python, politikadaki tam-sayı-değerli float yollarını repr'larıyla
çıkarır; ikiz mesaj üretirken oradan okur. Parite testi bu zinciri ayrıca kanıtlıyor.

## 4. Vektör örneklemi ve sonuç

**393 vektör**, dağılım: `manifest:38` (51 ölçülmüş fixture'dan görsel olanlar —
`tests/fixtures/media/manifest.json` `olculen` blokları), `ffprobe:14` (canlı
konteynerde ölçülmüş 7 video künyesi × 2 video slotu — `live-probe.json`),
`sinir:175` (her slotun politikadaki HER sayısal eşiği: bayt/megapiksel/kenar/alan/
oran-toleransı/bant/adet/süre/bitrate/fps için ±1 ve eşit değerler; tamamı veri
güdümlü, slot başına özel `if` yok), `rol:18`, `bicim:40` (reddedilen/koşullu/
bilinmeyen uzantı, MIME uyuşmazlığı, içerik-uzantı uyuşmazlığı, animasyon),
`guvenlik:63` (baş işaretçisi, kuyruk yükü, kap geçersiz, AV kirli/ölçülmedi,
çalıştırılabilir, data-URI), `kunye:45` (okunamaz, kesik, geometri ölçülmedi, EXIF 6,
gizli).

- **Parite: 393/393 birebir** (`assert.deepStrictEqual` — mesaj metinleri, ihlal
  sırası, `normalized_targets` sayıları ve `skipped` kayıtları dahil). İlk tam koşuda
  geçti.
- **Vacuity ölçümü:** `engine.ts`'te `short < min_short_edge` → `<=` yapıldı, senkron
  yeniden koşturuldu → parite süiti KIRMIZI (393'lük tarama düştü); geri alındı →
  22/22 yeşil. Kapı boş değil.
- **Doğrulama:** `npm test` → **862/862** (taban 840 + 22 yeni; başka ajanların o anki
  ağaç durumuyla birlikte) · `npm run lint` → **0 hata** (2 uyarı önceden var olan
  `PlansTab.vue`'da, bu işin dışında) · `npm run sync:policy:check` → yeşil ("vendor
  zinciri güncel") · Python'a dokunulmadığı için konteyner koşusu gerekmedi.

Parite çevirisinin ölçüm gerektiren noktaları (hepsi teste bağlandı): CPython
`round()`'un yarı-çift davranışı (`pyRound`, tam ondalık açılım üzerinden;
`normalized_targets` ölçekleri ve `observed` oranları buna bağlı), `{:.3f}` biçimi
(`pyFixed`), Python truthiness (`0/""/boş liste/boş sözlük` falsy — `aspect_band: {}`
tuzağı), `str(float)`in ".0" kuralı, `_SafeDict` (bilinmeyen yer tutucu olduğu gibi
kalır), `_compare`'in TypeError→False semantiği (`outside`/`pad_to` gibi bilinmeyen
karşılaştırıcılar tetiklenmez).

**Bilinen temsil sınırı (belgelendi):** JSON'daki künye alanında tam-sayı-değerli float
(`duration_s: 90.0`) `JSON.parse` sonrası 90'a iner; Python mesajı "90.0 saniye" der,
JS "90" derdi. Politika tarafı `FLOAT_REPRS` ile çözüldü; künye tarafında vektör
üreticisi bu değerleri int'e indirger (karar birebir aynı kalır) — gerçek akışta künye
JS'te üretilip JSON'la sunucuya gittiği için bu sınır pratikte ortaya çıkmaz.

## 5. Bayatlama koruması

- `vendor.manifest.json` kaynakların sha256'sını taşır; parite testi depo ortamdaysa
  CANLI kaynakla karşılaştırır (engine.py/slot JSON değişir de senkron koşulmazsa test
  düşer), depo yoksa **atlar ve "ÖLÇÜLMEDİ" der** — "geçti" demez.
- `engine.ts` → `engine.js` türetme halkası da manifestte; elle düzenlenmiş ya da
  eskimiş `.js` testte yakalanır. `.ts` içe aktarımı yasağı ve "vendor'ı yalnız
  index.js okur" sahiplik korumaları testte.

## 6. `engine.ts` preflight'tan NASIL çağrılır (bu görevde YAPILMADI — tarif)

`preflight.js`'in felsefesi korunuyor: karar VERMEZ, hızlandırır. Bağlama ayrı iş
(upload dizininde başka sahiplikler var). Önerilen dikiş:

1. `preflight.js` bugün `upload/vendor/slotPolicy.js`'ten damıtılmış kurallarla kendi
   bulgularını üretiyor. Geçiş adımında probe sözlüğü zaten elde:
   `probe.js`/`videoProbe.js` çıktısı + dosya meta'sı → `MediaProbe` alan adlarına
   (snake_case) eşlenir: `{filename, extension, byte_size, kind, detected, mime,
   width, height, animated, duration_s, bitrate_bps, frame_rate, existing_count, …}`.
   Ölçülemeyen alan GÖNDERİLMEZ (eksik alan = "ölçülmedi" sözleşmesi).
2. Çağrı: `import { evaluate } from "@/lib/media/policy";` →
   `const karar = evaluate(slotKey, probeDict, role)`. `karar.allow === false` ise
   yükleme başlatılmaz ve `karar.violations[*].message.tr` + `hint.tr` doğrudan
   `PreflightPanel`'e basılır (makine kodu `code`, telemetri için hazır).
   `karar.action === "warn"/"auto_fix"` yüklemeyi durdurmaz — bugünkü davranışla aynı.
3. `karar.normalized_targets` ön izleme simülatörüne "sunucu bunu üretecek" verisi
   sağlar (master ölçüsü + türev merdiveni) — simülatörün kendi vendor'ına dokunmadan.
4. Sunucu kararı DAİMA kazanır: finalize yanıtındaki sunucu ihlali istemci ön
   izlenimiyle çelişirse çelişki telemetriye yazılmalı (parite kapısının sahadaki
   devamı). `slotPolicy.js`'e dayalı mevcut hızlı yol istenirse bir süre paralel
   kalabilir; ikisi çelişirse motor kazanır.

## 7. Dosya sahipliği özeti

Yazılan/değişen: `admin-panel/frontend/src/lib/media/policy/**` (yeni),
`admin-panel/frontend/scripts/sync-policy-engine.mjs` (yeni), `package.json`
(3 script eklendi), `.prettierignore` (+1 vendor satırı, mevcut desen), bu rapor.
Dokunulmayan (yasak listesi): `preflight.js` ve upload akışı, `upload/vendor/slotPolicy.js`,
crop/simulator dizinleri, `i18n/locales`, `hooks.py`, `pipeline_bridge.py`, `docker/`,
Python motoru ve testleri.

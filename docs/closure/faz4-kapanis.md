# Faz 4 Kapanış Dosyası — Veri Modeli

> **Bu belge ölçümlerden derlenmiştir; çelişki hâlinde rapor kazanır.**
> Derleme tarihi: 2026-08-20 · Hazırlık: W6 kapanış dalgası (T-044 hazırlığı — imza atılmaz.)

## 1. Çıkış kapısı (91-gorev-panosu.html)

| Kapı çıktısı | Onaylayan |
|---|---|
| Veri modeli + indeks planı + migration provası | Teknik sorumlu |

## 2. Kapıyı karşılayan ölçümler

| Kalem | Durum | Kanıt |
|---|---|---|
| ER diyagramı + indeks planı | **KARŞILANDI** | 55-d2-faz3-5-kapanis.md §6.4: `docs/data/data-model-review.md:30-45` mermaid erDiagram; `:169-219` indeks planı (**68→57 indeks**), sorgu yolları Y1–Y7. |
| İndeks envanteri (kurulu tablolar) | **KARŞILANDI (kapsamlı)** | 55 §6.3 ölçümü: `tabMedia Asset` UNIQUE `asset_key` + 9 ikincil; `tabMedia Rendition` UNIQUE `rendition_key` + 4; `Media Processing Job` UNIQUE `idempotency_key`; `Media Profile` UNIQUE `profile_key`. |
| Satıcı izolasyonu | **KARŞILANDI** | hooks.py:880-891'de 7 DocType `permission_query_conditions`; `media_asset.json:210-225` if_owner:1; Storage Settings yalnız Media Superadmin + System Manager (57b T-040(3)). |
| Varsayılan profiller | **KARŞILANDI (notlu)** | `tabMedia Profile` **36 satır** (9 slotun hepsi), patch `v15_9_23_media_profile_seed` — kriter "fixture" diyordu, patch ile geldi (57b). |
| Patch temizliği | **DOLAYLI** | `tabPatch Log` v15_9_27…32 **skipped=0**; tek gerçek `bench migrate` koşumu 37-media-crop-intent.md §5.1 (19:27:50–19:28:07, hata 0). |
| T-042 üretim kablolaması | **KARŞILANDI (08-20)** | 64-be2-dedup.md: köprü `dedup.version_hash(source_hash, policy_snapshot, crop_intent, engine_version)` kullanıyor (pillow-11.3.0); `Media Version` autoname `field:version_hash` UNIQUE. |

## 3. Karşılanmayanlar / ölçülmeyenler (AÇIK)

1. **Migration provası + geri alma provası YOK** — 55 §6.4 ❌: "geri alma provası yok, `docs/plans/rollback-doctypes.md` yok (ölçüldü)"; `data-model-review.md:526-527` kendisi "YAZILMADI" diyor. **Kapının üçüncü cümlesi karşılanmıyor.**
2. **1M ölçekli EXPLAIN tekrarlanamaz** — 524.288 asset (%52) / 2.097.152 rendition (%7'si hedefin) geçici DB'de denendi, DB **düşürüldü**; `scripts/seed_synthetic.py` yazılmadı (55 §6.4, 57b T-044(2)).
3. **DocType kurulumu 10/15** — eksik 5: Media Source, Media Policy, Media Policy Profile, Media Content Rule, Media Quality Report (57b §1.1, 22:50:01).
4. **Beyan edilmiş şema sapması** — `content_sha256` UNIQUE değil (teklik `asset_key` üçlüsünde); `Media Rendition`'da `version` alanı ve `(version, profile, width, format)` bileşik UNIQUE yok (57b T-040(2); 64 §6 hâlâ açık diyor).
5. **Dedup görüş alanı dar** — `tabFile.content_hash` 5.047/5.047 satırda **MD5**; içerik-adresli ad yalnız 86 satırda → 4.961 dosya dedup aramasına görünmez; `Media Asset.content_sha256` dev'de 0 satır (64 §2).
6. **Backfill PLANLANDI, KOŞULMADI** — 17-t028-backfill-plani.md §0: "Bu rapor hiçbir backfill çalıştırmadı." Aday küme 2.833 URL / 835,4 MB; türev tohumlama ~7,1 saat tek worker (bant 7–47 sa), 29.136 nesne / 0,6–0,9 GB.
7. **Atomik versiyon geçişi yazılmıyor** — `active_version` kolonu var, "hiçbir kod bu alana yazmıyor"; SQL yalnız docstring (57b §1.2, media_version.py:10-23).
8. **Y-4 hakikat kaynağı** — `doctype_specs/media_asset.json` hâlâ `source` diyor, `asset_key`'i tanımıyor (55 §8).
9. Migration süresi hiçbir raporda ölçülmedi.

## 4. Kapı durumu özeti

**Kapı: KARŞILANMADI.** 55 §9 hükmü geçerli: "**Faz 4 (T-044) KAPANAMAZ** — kapanışın önündeki iki engel artık teknik değil, yapılmamış iş": (a) 1M sentetik EXPLAIN + `seed_synthetic.py`, (b) migration/rollback provası + `rollback-doctypes.md`. Karne (57b): 0 TAM · 5 KISMİ · 0 YOK.

## 5. Kaynak raporlar
`docs/reports/`: 57b-durum-faz4-7.md · 55-d2-faz3-5-kapanis.md §6 · 37-media-crop-intent.md · 17-t028-backfill-plani.md · 64-be2-dedup.md · 34-dogrulama-faz4-7.md (kısmen eskidi) · 40-t043-kullanim-gc.md · `docs/data/data-model-review.md`

## Ek ölçüm — 2026-08-20 (W8, rapor 94 §7–8)

- **DocType envanteri 10 → 13** (canlı DB'de sayıldı): +`Media Folder`, +`Media Folder Item`, +`Media RUM Sample`. Kaynağın 15'inden hâlâ 5 yok — dördü ADR-0016 gereği bilinçli olarak JSON'da (KARAR işi).
- **§3.7 zayıfladı / T-042 kırmızıları KAPANDI:** üretim `version_hash`'i artık **4 girdili** (`pipeline_bridge` → `dedup.version_hash`); rendition URL'lerinin **92/92'si** `/files/media/{asset}/{64-hex version_hash}/…` (INV-09 canlı, DB'de sayıldı); `Media Version.version_hash` **UNIQUE** (SHOW INDEX ile doğrulandı). `active_version`'a yazan kod hâlâ yok (0/13 dolu) — o kalem açık.
- **§3.4 sürüyor:** `content_sha256` hâlâ non-unique (bilinçli sapma, teklik `asset_key`'de).
- **T-043 uzlaştırması yazıldı (KARAR KULLANICIYA):** kalıcı `Media Usage` indeksi (kapının lafzı) ↔ bugünkü istek-anı tarama (tabMedia Usage **0 satır**; `LIVE_SOURCES` 17 + `ORDER_SOURCES` 5; `list_orphans` ucu canlı; kapının ölçülmüş koruması 3.821 dosya / 1,06 GB). İki seçeneğin bedelleri ADR-taslak formatında rapor 94 §8'de.
- **§3.1/§3.2 DEĞİŞMEDİ:** `rollback-doctypes.md` ve `seed_synthetic.py` bugün de yok; 1M EXPLAIN hâlâ tekrarlanamaz. Kapının "prova" cümlesi açık.

## 6. Onay

```
Onaylayan (Teknik sorumlu): ______________________   Tarih: ______________   İmza: ______________
```

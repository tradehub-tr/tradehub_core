# Faz 9 Kapanış Dosyası — Media Library — **TASLAK**

> ⚠️ **TASLAK — Faz 9 hâlâ hareketli.** i18n kapısı ~5 saat içinde iki kez kırıldı (57c §0.2: 571→609; 58 §1.1: 642+3 kırık) ve RU/AR çeviri işi devam ediyor. Bu dosya imzaya SUNULMAZ; sayılar dondurulunca güncellenip taslak damgası kaldırılır.
> **Bu belge ölçümlerden derlenmiştir; çelişki hâlinde rapor kazanır.**
> Derleme tarihi: 2026-08-20 · Hazırlık: W6 kapanış dalgası (T-095 hazırlığı).

## 1. Çıkış kapısı (91-gorev-panosu.html)

| Kapı çıktısı | Onaylayan |
|---|---|
| Erişilebilirlik + i18n raporu | QA |

## 2. Kapıyı karşılayan ölçümler

| Kalem | Durum | Kanıt |
|---|---|---|
| axe-core taraması kurulu ve KOŞUYOR | **KARŞILANDI** | axe-core ^4.13.0 + jsdom harness (52 §1.2–1.3); 08-20 koşumu: `mediaAxe.test.js` **4/4 pass** (61e). (57c'nin "axe.run 0 isabet" satırı bayat — 61e çürüttü.) |
| Taranan yüzeylerde ciddi bulgu | **0'a indirildi** | 52 §1.4: 2 serious (`aria-progressbar-name` ×2) → 58: **2→0**, suite 640→**645/645**; 6 komşu yüzey temiz (passes 7–17). |
| Tarama boş değil (vacuity) | **KARŞILANDI** | 58 §4: düzeltme geri alınınca yeniden 2 serious + 4 test kırmızı; geri konunca 0 bulgu / 5-5. |
| TR/EN kapsamı | **1 anahtar eksik** | TR **917**, EN **916** — tek boşluk `media.quality.col.attribute` (61e). |
| i18n anahtar kapısı (simülatör kapsamı) | **VAR ve ÇALIŞTI** | `simulatorA11y.test.js` 4 dil küme eşitliği; kapı 22:28'de kırmızı → 22:45 yeşil (57c §0.2); 23:44'te yine yakaladı (58 §1.1). |

## 3. Karşılanmayanlar / ölçülmeyenler (AÇIK)

1. **RU/AR: 766/917 anahtar eksik (≈%83)** — RU 151, AR 151; `media.*` (285), `mediaAudit` (192), `mediaOptimize` (131) vd. sıfır; yalnız `mediaStorage` (54/54) ve `mediaSimulator` (97/97) tam (61e bulgu #1). → **KARAR**: makine çevirisi mi, insan çevirmen mi (plan Kova D).
2. **axe kapsamı 5 ana ekranı DIŞARIDA bırakıyor** — MediaLibraryView, MediaOptimizeView, MediaAuditView, MediaExplorerView, MediaBackupView taranmadı; Teleport diyalogları SSR'da render olmuyor → hiç taranmadı (52 §1.5, 61e).
3. **AA kontrast ÖLÇÜLMEDİ** — `color-contrast` bilinçli UNMEASURABLE (jsdom boyamaz) (52 §1.5, 58 §6).
4. **Klavye-yalnız uçtan uca akış ÖLÇÜLMEDİ**; roving tabindex / diyalog odak tuzağı / ConfirmDialog dialog rolü grep'te hâlâ 0 (61e).
5. **aria-live eski 5 ana ekranda yok** (61e, 51 §4.1).
6. **`NEIGHBOUR_BASELINE = 2` gevşek** — `<=` karşılaştırması 0'la da geçiyor; 0'a çekilmeli (58 §9).
7. **Tek birleşik "Erişilebilirlik + i18n raporu" belgesi yok** — kanıt 52 + 58 + 61e'ye dağılmış.
8. Yan bulgular: `MediaUploadQueue.vue:125` SSR timer sızıntısı (58 §7-1); sanal grid ana varlık ızgarasına bağlanmadı (`useVirtualGrid` 0 isabet MediaLibraryView'da, 61e T-092).

## 4. Kapı durumu özeti (taslak)

**Kapı: KISMEN KARŞILANDI.** Tarama altyapısı gerçek ve vacuity-kanıtlı; taranan kümede ciddi bulgu 0; TR/EN 1 anahtar dışında tam. Kapanışı bloklayan iki büyük iş: RU/AR 766 anahtar (KARAR + çeviri) ve axe kapsamının 5 ana ekrana + diyaloglara genişletilmesi (gerçek tarayıcı gerektirir).

## 5. Kaynak raporlar
`docs/reports/`: 61e-fe-denetim-faz8-9.md · 58-fe1-a11y.md · 52-t090-tasarim-sistemi.md §1 · 57c-durum-faz8-11.md §0.2 · 45-t092-kutuphane-izgara.md · 46-t093-detay-cekmecesi.md

## 6. Onay — **TASLAK, imzaya sunulmaz**

```
Onaylayan (QA): ______________________   Tarih: ______________   İmza: ______________
```

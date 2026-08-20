# Faz 11 Kapanış Dosyası — Simülatör

> **Bu belge ölçümlerden derlenmiştir; çelişki hâlinde rapor kazanır.**
> Derleme tarihi: 2026-08-20 · Hazırlık: W6 kapanış dalgası (T-115 hazırlığı — imza atılmaz.)

## 1. Çıkış kapısı (91-gorev-panosu.html)

| Kapı çıktısı | Onaylayan |
|---|---|
| Simülatör drift testi + onay kapısı çalışır | QA |

## 2. Kapıyı karşılayan ölçümler

### Drift testi
| Kalem | Durum | Kanıt |
|---|---|---|
| Gerçek sayfa ↔ simülatör otomatik karşılaştırma | **KARŞILANDI (kutu boyutu)** | 59: ham CDP + kurulu Chrome; **13 cihaz × 5 sayfa, 85 kutu**; yayınlanmış imaja çapraz kontrol: 14/14 birebir. İlk ölçümde **25/85 satır >2 px, en büyük 80,68 px** (seller_shop/product_grid @ ipad-pro-11; ~240 px sidebar modellenmemişti). |
| Katalog düzeltmesi sonrası | **KARŞILANDI** | 76: `placements.json` düzeltmeleri sonrası tam zincir yeniden koştu — **measured 88 · driftCount 0 · maxAbsDeltaPx 0,42** (desktop-1440p home/top_deals) · squareMismatch 0. |
| >2 px = kırmızı | **KARŞILANDI** | `drift-measure.mjs` her sapmada exit 1; `drift.test.js` 7 test bugünkü sapma listesini sabitliyor (59 §5). |
| Sapma raporu CSS kökeni | **KARŞILANDI** | Her sapan satırda tag/class/computed CSS + 4 kuşak ata zinciri; 4 kök neden buradan okundu (59 §5 #3). |
| Gecelik CI | **KISMEN** | 76: `drift-nightly.yml` yazıldı (cron 47 1 * * * = 04:47 TRT, Node 24, çift checkout, 30 gün artifact, `MIN_OLCUM: 10` sahte-yeşil korkuluğu). **Commit/push YAPILMADI; schedule default branch'e merge edilmeden HİÇ KOŞMAZ** (76 §5/§7). → İNSAN: commit + merge + webhook. |

### Onay kapısı
| Kalem | Durum | Kanıt |
|---|---|---|
| İstemci kapısı | **KARŞILANDI** | 51 §4.1: 5 lcp_candidate bölge × 4 cihaz sınıfı = 20 gereklilik; görünürlük ≥%50 + ≥1 sn; IntersectionObserver yoksa hiçbir şey işaretlenmez; boş gereklilik seti de bloklar; `approvalGate.test.js` 20 test. |
| **Sunucu kapısı** | **KARŞILANDI (08-20)** | 65 §3: kanıtsız `approved_by_user=1` → **HTTP 417 MEDIA_PREVIEW_REQUIRED**; kanıtla → 200; zoom=17 → 417. İki katman (uç + DocType validate — "ORM ile yazılsa da geçilemez"). Vacuity: kapı satırları kapatılınca FAILED (failures=3) → geri 18/18. Playwright bağımsız doğrulama: 75 S5 KOŞUYOR. |
| Uyarı onayı (acknowledgement) | **KARŞILANDI (istemci)** | BLOCK_UNACKNOWLEDGED_WARNING + aria-describedby bağlı disabled yayın düğmesi (51 §4.1). |
| srcset göstergesi | **KARŞILANDI** | `test_simulator_srcset` 34/34; 65 kombinasyonda kaynak_yetersiz=0 · asiri_servis=1 · zoom_yetersiz=6; 1120 px kaynakla kaynak_yetersiz=4 (57c #6). Bayt yalnız gerçek `Media Rendition.bytes`'tan — "Bayt TAHMİN EDİLMEDİ" (51 §2.4). |

## 3. Karşılanmayanlar / ölçülmeyenler (AÇIK)

1. **Görsel (piksel) diff YOK** — ekran görüntüsü karşılaştırması ayrı iş (59 §6-6, 76 §6-3).
2. **Gecelik iş CI'da hiç koşmadı** — dosya untracked; ekip bildirimi = yalnız CI kırmızısı + artifact, webhook bağlanmadı ("uydurulmadı"); schedule bildirimi yalnız dosyanın son değiştiricisine gider (76 §6-1).
3. **CI'da veri katmanı yok** — `DRIFT_BASE` verilene kadar korunan küme 88 kutunun ~13'ü; `MIN_OLCUM` o zaman ~80'e çekilmeli (76 §6-2).
4. **3 bölge gerekçeli ölçülemedi** (brand_grid boş brandSlug · lightbox_thumb tek görselli ürün · drawer_thumb akışı tetiklenmedi) + 4 selector BULUNAMADI (59 §3).
5. **Kapı içerik denetimi eksik** — sunucu BOŞ kanıtı reddediyor, EKSİK kanıtı (phone/tablet/desktop kapsaması) değil (65 §9). `preview_gate_passed` alanı yok; sunucu tarafı denetim (audit) satırı yazılmıyor (51 §4.3).
6. **Kapı ürün akışında kısmen ölü** — `CropStudioModal` `:asset` almadığından kütüphane ekranından `approve()` no-op (75 Bulgu 3).
7. Bayat başlıklar: `SimApprovalGate.vue` "Sunucu tarafı kapı YOK — ölçüldü" yazıyor; artık VAR (65 §9).
8. Video simülasyonu boşlukları: HLS merdiven bitrate'leri vendor'lanmadı; cover_video/gallery_video bölgeleri placements.json'da yok (poster kutusu main_image vekili ile); vitrinde satıcı kapak videosunda autoplay yok, ProductVideoSection poster attribute yazmıyor (51 §6.2, §3.1).
9. İlk boyama <1,5 sn ÖLÇÜLMEDİ (49 §6).

## 4. Kapı durumu özeti

**Kapı: BÜYÜK ÖLÇÜDE KARŞILANDI.** Drift zinciri gerçek tarayıcıyla ölçüldü, katalog düzeltildi (25 sapma → 0; maks 80,68 px → 0,42 px) ve onay kapısı artık iki katmanlı sunucu zorlamasıyla çalışıyor (417/200 canlı ölçüldü). Kalanlar: gecelik workflow'un commit+merge'i (İNSAN), görsel diff, kanıt içerik denetimi, `:asset` düzeltmesi.

## 5. Kaynak raporlar
`docs/reports/`: 76-w4-drift-gecelik.md · 59-fe2-drift-testi.md · 65-be3-zoom-kapi.md §3 · 75-w4-panel-e2e.md · 51-t112-simulator-kartlari.md · 49-t111-render-motoru.md · 61f-fe-denetim-faz10-11.md · 57c-durum-faz8-11.md (T-114/T-115 satırları 65/75/76 ile aşıldı)

## 6. Onay

```
Onaylayan (QA): ______________________   Tarih: ______________   İmza: ______________
```

# Faz 14 Kapanış Dosyası — Test ve Kabul — **TASLAK**

> ⚠️ **TASLAK — Faz 14 hâlâ hareketli.** Bu fazın çıktısı (nihai kabul + go-live) tanımı gereği diğer tüm fazların kapanmasına bağlıdır ve bugün 9 faz imzasız, UAT/pilot koşulmadı, go-live yapılmadı. Bu dosya imzaya SUNULMAZ.
> **Bu belge ölçümlerden derlenmiştir; çelişki hâlinde rapor kazanır.**
> Derleme tarihi: 2026-08-20 · Hazırlık: W6 kapanış dalgası (T-140…T-145 durumu). Nihai kabul TASLAĞI ayrı dosyada: `docs/closure/nihai-kabul-taslak.md`.

## 1. Çıkış kapısı (91-gorev-panosu.html)

| Kapı çıktısı | Onaylayan |
|---|---|
| Nihai kabul dosyası + go-live onayı | Platform yöneticisi |

## 2. Kapıyı karşılayan ölçümler

| Kalem | Durum | Kanıt |
|---|---|---|
| Nihai kabul dosyası (dürüst envanter) | **VAR (2026-08-18, bayat)** | 13-faz14-kabul.md — kendi karnesi: 15 fazın **2'si kanıtlı** (6, 8), 7 kısmen, 6 kanıt yok; §7: "BU BELGE İMZALANMAMIŞTIR VE BUGÜN İMZALANAMAZ". 14-nihai-denetim.md 13'ün 3 sayı hatasını düzeltti (74→137 test; 16→15 DocType; security/ boş değil). |
| İzlenebilirlik matrisi (T-140) | **GÜNCELLENDİ** | `docs/test/traceability.md` (2026-08-20 07:31) + 68: **202 gereksinim (150 FR + 52 NFR)**, bağlı **82 (%40,6)**, kapsanmayan **120 (%59,4)**; Python 144 dosya/3.391 fonksiyon; FE 1.152 koşan test, 34 FE etiketi; vacuity kanıtlı (etiket silinince F 15→14). Eski %36,6 değeri geçersiz. |
| E2E paketi (T-141) | **KISMEN** | `test_e2e_scenarios.py` **39 test OK (skipped=8)**; panel E2E: 75 — Playwright **6 koşuyor / 2 gerekçeli skip**, 4 yeni kusur buldu; unit 862/862. |
| Go-live/UAT planları | **VAR (plan)** | faz14-golive.md (aşama tablosu, geri dönüş prosedürü, R1–R8 runbook metinleri, nöbet); faz14-uat.md (pilot tasarımı). İkisi de kendini "KOŞULMADI" olarak işaretliyor. |
| Backfill kodu | **HAZIR, KOŞULMADI** | `migration/backfill.py` 862 satır + **50/50 test OK**; docstring: "Bu sınıf ÇALIŞTIRILMADI" (57d). Plan: 17-t028 (2.833 URL / 835,4 MB; koşum yok). |

## 3. Karşılanmayanlar / ölçülmeyenler (AÇIK)

1. **UAT/satıcı pilotu KOŞULMADI** — faz14-uat.md: "BU BİR PLANDIR. PİLOT KOŞULMADI… satıcıdan gelmiş tek bir ölçüm yoktur"; pilotun (b) Crop Studio ve (c) simülatör ekran bağları o tarihte yazılmamıştı. → **İNSAN**.
2. **Go-live + geri dönüş provası YAPILMADI** — faz14-golive.md: "DEVREYE ALMA YAPILMADI. GERİ DÖNÜŞ PROVASI KOŞULMADI… o süre ÖLÇÜLMEDİ". Runbook bu dalgada yazıldı (`docs/runbooks/media-go-live.md`) — **tatbikat yapılmadı notuyla**. → **İNSAN**.
3. **9 faz kapanış imzası eksik** (57 karar #9) — imza dosyaları artık hazır: `docs/closure/faz{0..13}-kapanis.md`.
4. **İzlenebilirlik %40,6** — %100 şartına 120 gereksinim uzakta (68).
5. **E2E senaryo 5/6/8/12 kodda karşılıksız** (önizleme-onay kapısı kısmen 65 ile kapandı; iş planlayıcı, VMAF, on-demand ucu açık); `docs/qa/evidence/` yok (36, 57d, 61g).
6. **VMAF kapısı ölçülemez** — Dockerfile ffmpeg n8.1.2 pinli ama çalışan konteyner 5.1.9, libvmaf YOK → imaj rebuild şart (57d §4.2).
7. **A-1 kritik**: Faz 3–14 çıktılarının önemli kısmı git'te untracked (105 dosya, 54 G-2); drift-nightly.yml ve ci.yml dahil.
8. **A-2 kritik**: KVKK D-2 — 40 public PII dosyası sınıflandırılmadı (54 §2.1).
9. **A-13 kritik**: 2400 px hedefi ↔ 2000 px tavanı ↔ 30 gün arşiv = geri dönülemez piksel kaybı riski (13 §4). Tüm A-1…A-13'te "SAHİP ATANMADI".
10. **Suite kararsızlığı** — 18 koşumda 17 OK / 1 FAILED (≈%5,6); "kararsız bir suite üzerine hiçbir kabul kriteri kurulamaz" (14 B1).
11. **Bayat go-live belgeleri** — golive.md "medya bayrağı bulunamadı" diyor (pipeline_flags.py var, 16 test); 13 "hiç ADR yok" diyor (17 ADR var) (57d §4.1). Güncellenmeli.
12. **RUM scheduler kayıtları** — 63 §7/72 §6'nın istediği `hourly aggregate_samples` + `daily purge_expired_samples` hooks.py'de **artık kayıtlı** (hooks.py:157/188, W6 doğrulaması) — bu madde kapandı; gerçek scheduler koşumu henüz gözlenmedi.

## 4. Kapı durumu özeti (taslak)

**Kapı: KARŞILANMADI.** Kapının iki bileşeni de (nihai kabul dosyası imzası + go-live onayı) İNSAN eylemine bağlı ve ikisinin de ön koşulları (UAT, tatbikat, 9 faz imzası, kritik A-1/A-2/A-13) açık. Bu dalga insan kalemlerini "oku ve imzala"ya indirdi: kapanış dosyaları + runbook + kabul taslağı hazır.

## 5. Kaynak raporlar
`docs/reports/`: 13-faz14-kabul.md · 14-nihai-denetim.md · 57d-durum-faz12-14.md §4 · 68-w3a-izlenebilirlik.md · 75-w4-panel-e2e.md · 36-dogrulama-faz12-14.md · 61g-fe-denetim-faz12-14.md · `docs/test/traceability.md` · `docs/plans/faz14-golive.md` · `docs/plans/faz14-uat.md`

## 6. Onay — **TASLAK, imzaya sunulmaz**

```
Onaylayan (Platform yöneticisi): ______________________   Tarih: ______________   İmza: ______________
```

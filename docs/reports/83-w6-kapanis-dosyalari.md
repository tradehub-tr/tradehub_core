# 83 — W6: Faz kapanış ve kabul dosyaları (imza hariç her şey)

> **Bu belge ölçümlerden derlenmiştir; çelişki hâlinde rapor kazanır.**
> Tarih: 2026-08-20 · Kapsam: T-009, T-019, T-029, T-035, T-044, T-055 (hazırlık + koşum), T-067, T-075, T-105, T-115, T-124, T-135 kapanış dosyaları; T-144 runbook; T-145 kabul taslağı.
> Amaç: insan kalemlerini "oku ve imzala" adımına indirmek. **Hiçbir dosyaya imza atılmadı, onay uydurulmadı.**

## 1. Üretilen dosyalar

| Dosya | İçerik |
|---|---|
| `docs/closure/faz0-kapanis.md` … `faz14-kapanis.md` (15 dosya) | Her faz için: pano kapısı → karşılayan ölçümler (rapor+sayı) → karşılanmayanlar AÇIKÇA → kaynak listesi → **boş imza satırı**. Faz 9 ve Faz 14 **TASLAK damgalı** (ikisi de hareketli: i18n kapısı ~5 saatte 2 kez kırıldı; Faz 14 tanımı gereği diğerlerine bağlı). |
| `docs/closure/nihai-kabul-taslak.md` | T-145 taslağı: ölçülmüş karne, 12 açık karar, 13 insan kalemi, kusur/borç listesi, boş imza bloğu. |
| `docs/runbooks/media-go-live.md` | T-144: 4 bayrak sırası (69 §1), worker/imaj tuzağı (69 §3, komutuyla), migrate kilidi, backfill adımları + durdurma kriterleri (17), geri alma (bayrak neyi geri alır / neler KALICI — 69 §9), izleme (24 metrik serisi, 16 alarm, drift CI, scheduler kayıtları). **"TATBİKAT YAPILMADI" notu ve boş tatbikat kaydı ile.** |
| `tradehub_core/tests/acceptance/__init__.py` + `test_storage_acceptance.py` | T-055 kabul paketi (Faz 5'in tek "YOK artefaktı"ydı — 55 §7.1'de `ls` kanıtıyla). |

Mevcut hiçbir rapor değiştirilmedi; kaynak kod, hooks.py, frontend'e dokunulmadı.

## 2. T-055 kabul testi — koşum çıktısı

Şartname senaryoları (42-faz5 · T-055) çalıştırılabilir iskelet olarak yazıldı: **Local kipi GERÇEKTEN koşuyor** (bugünkü içerik-adresli yerel depo canlı kod); S3 / Mirror / Tiered / canlı-yanlış-kimlik senaryoları `skipUnless(MEDIA_ENGINE_S3_*)` — gerekçe test çıktısına gömülü: kabul koşumu hedef S3'ü varsaymaz, dev MinIO'ya örtük bağlanmak kabul kanıtı sayılmaz (sözleşme düzeyi kanıt zaten `test_storage_adapters` 137 + `_minio` 91'de). **Sahte yeşil yok** — koşulmayan senaryo `skipped` görünür.

Gerçek koşan 10 test: uçtan uca yükleme→teslim URL (içerik-adresli ad `sha256[:32]`, shard, `/files/..` sözleşmesi, tam hash künyesi) · dedup idempotensi (`created=False`, tek nesne) · atomik yazım kalıntısızlığı (`.tmp-*.part` = 0) · public↔private taşıma (anahtar korunur) · private imzalı URL (doğrulama + kurcalama reddi) · imzalayıcısız private URL reddi · **boto3 saflığı** (taze alt süreçte local döngü sonrası `sys.modules`'ta boto3 yok) · `build_storage` local planı · **graceful degradation** (mode=s3 istenmiş + S3 kapalı → local'e sebep raporuyla düşüş, tam işlevsel) · **retention kuru koşumu** (RetentionSweeper varsayılan dry-run: 0 silme, rapor `dry_run=True`).

**Konteyner koşumu (istoc-dev-backend-1, 2026-08-20):**

```
$ docker cp tradehub_core/tests/acceptance istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/tests/
$ docker exec istoc-dev-backend-1 bash -c "cd /home/frappe/frappe-bench/apps/tradehub_core && \
    python3 -m unittest tradehub_core.tests.acceptance.test_storage_acceptance -v"
...
Ran 14 tests in 0.125s
OK (skipped=4)
```

- **Geçen: 10 · Skip: 4** (s3_primary, mirror, tiered, yanlış-kimlik — hepsi `MEDIA_ENGINE_S3_*` gerekçesiyle). Host koşumu da aynı: `Ran 14 — OK (skipped=4)`.
- ⚠ Kod imaja gömülü olduğundan test dosyası konteynere `docker cp` ile taşındı — **imaj rebuild'inde kaybolur** (W3-B/69 §3 bulgusuyla aynı sınıf). Kalıcılık için dosyalar repo'da; sonraki imaj build'i içerecek.

## 3. Faz başına kapı durumu özeti

| Faz | Kapı | Durum | Kısa gerekçe (ayrıntı kapanış dosyasında) |
|---|---|---|---|
| 0 | 7 rapor + korpus + açık sorular | **KISMEN** | 12 rapor + 51/51 manifest ✅; video fixture 7/8; K-1 (40 PII dosyası) + K-3 İNSAN'da |
| 1 | Algoritma raporu + ADR seti | **KISMEN** | 592 vektör 0,0 px ✅; **ADR seti kısmi**: geri dönüş yolu 0/17, 2 zorunlu ADR (istemci kütüphane, CDN) yok, P-kod tablosu yok |
| 2 | Slot standartları sabit + SRS v1.0 | **KARŞILANMADI** | 0/9 slot `active`, 49 open_question; SRS "HÂLÂ TASLAK"; **content_rules eşikleri insan etiketleme bekliyor** (~200 tetiklenme) |
| 3 | SAD v1.0 + dondurulmuş arayüzler | **KISMEN** | Arayüzler ✅ (5 protokol, 75 contract testi, TS 393/393); SAD "ONAYLANAMAZ" (7/8 kapı açık, 0 ADR referansı) |
| 4 | Veri modeli + indeks + migration provası | **KARŞILANMADI** | ER+indeks ✅; **migration/rollback provası yok**, 1M EXPLAIN tekrarlanamaz, DocType 10/15 |
| 5 | Depolama kabul raporu (4 mod) | **KISMEN (bu dalga ile)** | Sözleşme 137+91 test ✅; **kabul paketi bugün yazıldı, Local konteynerde GEÇTİ**; S3'lü 3 kip kabul ortamı bekliyor; DR 0 yedek seti; dry-run onayı İNSAN'da |
| 6 | Golden regresyon GREEN + değişmez kapsamı | **YARISI** | GREEN ✅ (32 OK ×2 bağımsız); değişmez kapsamı ❌ (7/12 INV adsız, harita dosyası yok) |
| 7 | Video regresyonu GREEN + kaynak bütçesi | **YARISI** | GREEN ✅ (208 test); bütçe kısmi (bellek/CPU/eşzamanlılık yok, 4K60 fixture yok); kapanış **VMAF↔INV-05 KARARINA** bağlı |
| 8 | OpenAPI v1 dondurma + contract testleri | **BÜYÜK ÖLÇÜDE** | 126+41 test, 87/87 negatif kapsam ✅; şerh: dondurma çağrılamayan katmanda; 08-20 yüzey değişiminden sonra `--check` yeniden koşulmalı; SDK/lint/koleksiyon yok |
| 9 (TASLAK) | Erişilebilirlik + i18n raporu | **KISMEN** | axe 2→0 + vacuity ✅, TR/EN 1 anahtar eksik; **RU/AR 766/917 eksik (%83)**, 5 ana ekran axe dışı, kontrast ölçülemedi |
| 10 | Crop doğruluk raporu | **KISMEN** | 600 vaka ölçüldü; zoom düzeltmesiyle B: 7391 px→1 px ✅; **C/E ürün kararı**, 20 görsel elle karşılaştırma İNSAN'da |
| 11 | Drift testi + onay kapısı | **BÜYÜK ÖLÇÜDE** | Drift 25 sapma→0 (88 kutu, maks 0,42 px) ✅; sunucu onay kapısı canlı 417/200 ✅; gecelik workflow commit+merge İNSAN'da; görsel diff yok |
| 12 | Performans kabulü (LCP/CLS) | **KARŞILANMADI** | Gerçek lab ölçümü var (12 koşum) ve RUM canlı; ama products LCP 6352 ms ❌, categories CLS 0,5396 ❌, mobil profil ve "sonra" ölçümü yok |
| 13 | Sızma + yük + kaos raporu | **KARŞILANMADI (1/3)** | Sızma ✅ (10 vektör, düzeltmeler doğrulandı); **yük testi YOK, kaos testi YOK**; T4 karar, T6 kod açığı açık |
| 14 (TASLAK) | Nihai kabul + go-live onayı | **KARŞILANMADI** | Tanımı gereği İNSAN'da: UAT koşulmadı, tatbikat yapılmadı, 9 faz imzasız; taslak + runbook bu dalgada hazırlandı |

Sayım: **karşılandı/büyük ölçüde 2** (Faz 8, 11) · **yarısı 2** (6, 7) · **kısmen 6** (0, 1, 3, 5, 9, 10) · **karşılanmadı 5** (2, 4, 12, 13, 14).

## 4. Dürüstlük notları

1. Görev metnindeki **"48/52/2" karnesi hiçbir raporda yok**; ölçülmüş karne 57'nin **21/78/3**'ü + 08-20 hareketleri. Kabul taslağı ölçümü esas aldı.
2. Görev metnindeki **"59-82 arası bugünün dalgaları"**: dizin **77'de bitiyor** — 78-82 raporları mevcut değil (ls ile doğrulandı); bu rapor 83 numarasını görev tanımına sadık kalarak kullandı.
3. **"logistics çevirisi"** diye bir açık karar plan dosyasında bulunamadı; çeviri kararı **RU/AR 766 anahtar**; "logistics" yalnız `logistics.provider_logo` medya slotu olarak geçiyor (LIVE_SOURCES'ta yok). İkisi de kabul taslağına dürüstçe yazıldı.
4. Faz kapanış dosyalarındaki her "KARŞILANDI" bir rapor+sayıya bağlı; ölçümü olmayan hiçbir kaleme "karşılandı" yazılmadı — durum "KARŞILANMADI" ya da "ÖLÇÜLMEDİ".
5. Süre/performans iddiası yok; T-055 koşum süreleri (0,125 s) yalnız çıktı aktarımıdır, bütçe iddiası değildir.

## 5. Sonraki insan adımları (öncelik sırasıyla)

1. Kapanış dosyalarını oku → hazır olanları imzala (Faz 8 ve 11 en yakın; Faz 6/7'nin GREEN yarıları imzalanabilir kapsam daraltmasıyla).
2. `nihai-kabul-taslak.md` §2'deki 12 kararı sahiplendir (en ucuz üçü: C/E önizleme, K7, overrides).
3. Runbook ile tatbikat koş; süreyi runbook'un boş tatbikat kaydına işle.
4. İmaj rebuild (libvmaf+boto3+Node 22) → 3 ARAÇ engeli ve T-055 S3 senaryoları açılır; `MEDIA_ENGINE_S3_*` kabul ortamıyla `test_storage_acceptance` yeniden koşulur.

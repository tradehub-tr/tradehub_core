# ADR-0008 — Görsel motoru Pillow'da kalır; pyvips reddedildi, `draft()` eklenmesi önerildi

**Durum:** Kabul edildi · **`draft()` önerisi henüz uygulanmadı**
**Tarih:** 2026-08-18 (T-007 / K-11)
**İlgili:** ADR-0006

---

## Bağlam

Faz 0 kapanış raporunun K-11 maddesi bir kütüphane kıyaslaması istiyordu; Faz
0'da yapılamamıştı çünkü `libvips`/`pyvips` kurulu değildi. Bu oturumda kuruldu
ve ölçüm koşuldu: `scripts/bench_engine.py`, ham veri `fixtures/bench.csv` —
**360 satır, 0 hata**, canlı veriden 10 gerçek dosya, 6 motor kolu.

Soru: Pillow'da mı kalınmalı, pyvips'e mi geçilmeli (ya da ffmpeg görsel yoluna)?

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| **A (SEÇİLEN)** — Pillow'da kal, `engine.optimize`'a `draft()` ekle | İki satır, yeni bağımlılık yok, üretim imajı değişmiyor. |
| B — pyvips'e geç | Elle ayarlanmış zincirle **1,37×** hızlı. Bedeli: `libvips42`'nin **üretim imajına** girmesi (imajı Frappe Cloud/Press build ediyor), iki tuzağın bilinmesi, ve CMYK renk kayması. |
| C — ffmpeg görsel yolu | Belleği en düşük. Bedeli: renk yönetimi zayıf, süreç başlatma maliyeti var. |

## Karar

> **Pillow'da kalın.** Ama `engine.optimize`'a **`draft()` ekleyin**: iki satır,
> yeni bağımlılık yok, en kötü dosyada tepe bellek **588 MB → 172 MB (3,4×)**.
> (`docs/reports/05-kutuphane-benchmark.md` §0)

K-11 "libvips ekle" olarak değil, **"ölçüldü, ertelendi"** olarak kapatıldı.

## Gerekçe — ölçülen sayılar

| Gerekçe | Ölçüm |
|---|---|
| Canlı görsellerin %90'ı 5,01 MP altında | pyvips'in kazancı bu bölgede **1,02×–0,97× (yok)** |
| pyvips'in kazandığı bölge (>20 MP) | 4.812 görselin **179'u = %3,7** |
| Kutudan çıktığı hâliyle pyvips | **0,94× — Pillow'dan YAVAŞ** |
| Elle ayarlanmış pyvips | 1,37× — ama iki tuzağı bilmeyi gerektiriyor (§5 CMYK, §6 `export_profile`) |
| CMYK (38 dosya) | pyvips **0,37×–0,56× yavaş** ve **rengi gözle görülür biçimde değiştiriyor** (§9) |
| Çıktı boyutu farkı | **%4** — kararı taşıyacak kadar büyük değil |
| Kalite (SSIM) | Kodlama kaybı **eşit** (0,985–0,998, iki motorda da) |
| `draft()`'ın getirisi | 72,7 MP JPEG: tepe RSS **588 → 172 MB**, süre **624 → 474 ms**; 36,2 MP CMYK JPEG: **309 → 105 MB**, **553 → 217 ms** |
| pyvips'in gerçek maliyeti | Press'in ürettiği **üretim imajına** `libvips42` sokmak |

## Sonuçlar

### Olumlu

- Bağımlılık eklenmedi, üretim imajı değişmedi, CMYK renk riski alınmadı.
- Kararın **tersine dönme koşulu sayısal olarak yazıldı** (§12.2-4): pyvips ancak
  şu üç eşikten biri aşılırsa yeniden değerlendirilir —
  (a) toplu koşumda darboğaz **ve** iş yükünün >%20'si 15 MP üstü dosyalardan
  geliyorsa, (b) sunucuda AVIF/HEIC **girdi** desteği gerekirse (Pillow'da HEIF
  yok; libvips 8.14.1'de `.heic`/`.avif`/`.jxl` var — pyvips'in bu benchmark'taki
  **tek net üstünlüğü**), (c) tek istekte 30+ türev üretilecekse.

### Olumsuz / açık

- **`draft()` uygulanmadı.** Rapor kod değiştirmedi (`tradehub_core/` salt okunur
  ele alındı). Yani kararın "getiri" tarafı bugün **tahsil edilmemiş** durumda:
  72,7 MP dosyada hâlâ 588 MB tepe bellek riski var.
- `draft()`'ın yan etkisi var: pikseller değişiyor (SSIM 0,9721–1,0000). Golden
  fixture korpusu (K-10) bunu yakalamak için ideal ilk müşteri — ama bu koşum
  yapılmadı.
- Asıl bellek riski `draft()` ile kapanmıyor: `max_megapixels_hard = 80` canlıdaki
  **72,71 MP**'lik dosyayı geçiriyor ve `draft()` PNG/WebP'yi kurtarmıyor (§10).
  Megapiksel kapısı gözden geçirilmedi.
- Kurulum **geçici**: `libvips`/`pyvips` ölçüm için elle kuruldu, `docker/backend.Dockerfile`
  değiştirilmedi (§1). Ölçüm tekrarlanmak istenirse kurulum yeniden yapılmalı.

## Geri dönüş yolu

Peak RSS 500 MB'yi veya normalize p95 süre bütçesini gerçek korpusta aşarsa
pyvips yeniden ölçülür. Aynı fixture, codec, kalite ve ICC çıktısında renk/SSIM
paritesi sağlanmadan motor değişmez; başarısız pilotta Pillow yoluna bayrakla
dönülür.

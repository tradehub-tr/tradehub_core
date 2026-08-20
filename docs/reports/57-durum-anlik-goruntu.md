# 57 — Durum anlık görüntüsü (102 görev)

**Ölçüm penceresi:** 2026-08-19 · 22:27 → 23:00
**Yöntem:** dört bağımsız ajan, kaynak panonun kendi kabul kriterlerine karşı **ölçerek**
(mevcut raporlara güvenmeden, çapraz kontrol için kullanarak).
**Ayrıntı:** `57a-durum-faz0-3.md` · `57b-durum-faz4-7.md` · `57c-durum-faz8-11.md` · `57d-durum-faz12-14.md`

⚠️ **Bu bir anlık görüntüdür.** Ölçüm sırasında **7 ajan aktif olarak kod yazıyordu.**
Ölçüm penceresinin içinde gerçekleşenler (ajanlar saatiyle kaydetti):
- 22:23–22:32 Şerit A `v15_9_28…33` yamalarını uyguladı → DocType 8 → **10**
- 22:36 dört yeni rapor doğdu (`51`, `54`, `55`, `56`)
- 22:42–22:43 C7 eksik i18n anahtarlarını kapattı → panel testi 571 (1 kırmızı) → **609 (0)**
- 22:43 `/metrics` `auth_hooks` kablolaması yetişti → 401 → **HTTP 200**
- 22:56 `.github/workflows/ci.yml` **doğdu** (22:31'de yoktu)

---

## Karne

| Fazlar | Görev | TAM | KISMİ | YOK |
|---|---:|---:|---:|---:|
| 0–3 | 36 | **18** | 18 | 0 |
| 4–7 | 25 | **2** | 22 | 1 |
| 8–11 | 24 | **1** | 22 | 1 |
| 12–14 | 17 | **0** | 16 | 1 |
| **Toplam** | **102** | **21** | **78** | **3** |

### Sabahki ölçümle karşılaştırma

| | Sabah (33–36) | Şimdi (57a–d) |
|---|---:|---:|
| TAM | 30 | **21** |
| KISMİ | 61 | **78** |
| YOK | 10 | **3** |

**TAM'ın düşmesi gerileme DEĞİL.** Ajanların ortak tespiti: kriter bu turda
**kütüphanede** değil **teslim edilen üründe** arandı.

En keskin örnek — **T-042**: kütüphane `core/dedup.py` doğru 4 girdili
`version_hash`'i ve hash'li URL şemasını tanımlıyor; üretim `pipeline_bridge.py`
ise kendi **tek girdili** sürümünü kullanıyor ve URL'e hash koymuyor.
Canlı doğrulama: o adres kalıbına uyan `tabFile` kaydı **sıfır**.

**Asıl kazanım YOK'ta: 10 → 3.** Gün içinde YOK'tan çıkanlar: T-017, T-032,
T-081, T-091, T-105, T-111, T-114, T-130, T-131.

Kalan üç YOK: **T-055** (Faz 5 kabul — `tests/acceptance/` hiç yok) ve iki faz kapanışı.

---

## Engelleyen dağılımı

Ajanların kendi sayımları (toplam 102):

| Engelleyen | Görev | Anlamı |
|---|---:|---|
| **AJAN** | 47 | Kod işi, engel yok — ajanla bitirilebilir |
| **—** | 21 | Zaten TAM |
| **ARAÇ** | 16 | Eksik araç: libvmaf · boto3 · spectral · axe-core · tesseract · jsonschema · TS SDK · Postman |
| **KARAR** | 9 | İş kararı — ajan veremez |
| **İNSAN** | 9 | İmza · UAT pilotu · go-live tatbikatı · PII sınıflandırması |

---

## Bugün ölçülen tekrar eden desen

Aynı yapısal kusur **sekiz ayrı yerde** çıktı: mekanizma yazılmış, üretime bağlanmamış.

| # | Mekanizma | Ölçülen durum |
|---|---|---|
| 1 | `probe.py` güvenlik denetimleri | Yazılmış, **hiçbir üretim yolu çağırmıyordu** → T-017 açığı |
| 2 | Metrikler (24 tanım) | Tanımlı, **hiçbir satır yazmıyordu** |
| 3 | `PolicyEngine` Protokolü | Tanımlı, somut sınıf **13/13 metodu karşılamıyordu** |
| 4 | `ImageEngine` · `VideoEngine` · `DeliveryManifest` | **0 üretim uygulaması**, yalnız sahte |
| 5 | Kullanım koruması (GC) | Yolun **yarısına** bağlıydı → 3.821 dosya silinecekti |
| 6 | `core/dedup.py` `version_hash` | Kütüphanede doğru, **üretim kendi sürümünü kullanıyor** |
| 7 | Poster üretimi | 7/7 üretiliyor, `ProductVideoSection.ts` **`poster` özniteliği hiç yazmıyor** |
| 8 | Yeni panel bileşenleri | Yazılmış, **hiçbir rota import etmiyor** (bölüşüm kararımın sonucu) |

Sekizinde de testler yeşildi ve kod tabanı "var" görünüyordu.

### İkinci desen: kapı yanlış şeyi ölçüyor

- **G5 (SRS):** kural harfiyen `!= "UNCALIBRATED"` — dize değişince kalibrasyon
  yapılmadan geçiyor. 9 kuralın 9'u hâlâ kalibre edilmemiş.
- **T-105 (`cropPixelParity`):** düzenek `savePayload`'ı doğrudan `resolve_crop`'a
  veriyor, gerçek yoldaki `_parse_safe_area` katmanını atlıyor. Kapı 7391 px sapma
  gösteriyor; gerçek zincirde ölçüm **3 sapan / 1 px**. Düzeltme çalışıyor, kapı yanlış.
- **`test_hooks_kaydi_henuz_yok`:** kaydın *olmadığını* iddia ediyor, `hooks.py:210-211`
  artık kayıtlı — bayat bekçi, Faz 5 paketini kırmızıya düşürüyor.

---

## Karar bekleyen 9 madde (özet)

1. **VMAF eşiği ↔ INV-05 fayda kapısı** — gerçek 1080p'de aynı anda sağlanamaz.
   Üç seçenek ölçülmüş bedelleriyle `56-d3-faz6-10-kapanis.md` §4.3'te. **Bugün ölçülemez** — imajda `libvmaf` yok.
2. **K7 kota çelişkisi** — "rendition'lar kotadan sayılsın" kararı, "türevler `File` açmaz" mimari kararıyla çelişiyor.
3. **`content_rules` eşikleri** — kalibrasyon insan etiketi istiyor (~200 görsel).
4. **T-105 C/E ayrışmaları** — override oran zorlaması ve taban bölge; ikisi de ürün kararı.
5. **Compliance Officer KYC erişimi** — permlevel-0 satırı yok, erişim genişletmek karar.
6. **Poster kalite kapısı** — 122 KB tavanı ancak WebP q40'ta tutuyor.
7. **AV1** — %31,7 verimli ama kapıyı geçmiyor.
8. **40 dosyanın PII sınıflandırması** (Faz 0 kapanışı).
9. **9 faz kapanış imzası.**

---

## Doğrulanamayan / ölçülemeyen

- **Sessiz başarısızlık iddiası** (`57d`): permlevel-4 devreye girince satıcı
  `PermissionError` almıyor, değer sessizce değişmiyor. **Doğrulayamadım** —
  `Verified` olmayan ve satıcı rolü taşıyan kayıt canlıda yok.
- İmaj yeniden kurulmadı: `libvmaf` 0, `boto3` sistem python'da yok, Node v20.
  `backend.Dockerfile` tarifi var ama imaja girmemiş. **Tek rebuild üç görevi açar.**
- 8 adet `@test.local` kullanıcı ajanlardan artakalmış.

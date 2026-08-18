# Canlı Ölçüm Raporu — T-003 / T-004 boşluklarının kapatılması

**Tarih:** 2026-08-18 · **Ortam:** yerel stack (`istoc-dev-*`, site `istoc.localhost`)
**Yöntem:** konteyner içinde `../env/bin/python` ile doğrudan ölçüm; her sayı bu oturumda üretildi.

Bu rapor, Faz 0 dalgasında **veritabanı erişimi olmadığı için** ertelenen ölçümleri
kapatır. Kapanış raporundaki (`07-faz0-kapanis.md` §Ç-1) tespit doğruydu: bu kalemler
"üretimde doğrulanmalı" değil, **yerelde koşulabilirdi**.

---

## 1. Genel medya envanteri (T-003)

| Metrik | Değer |
|---|---:|
| `tabFile` kaydı (klasör hariç) | **4.958** |
| — public | 4.350 |
| — private | 608 |
| Görsel | 4.812 |
| Video | 23 |
| Belge (pdf/doc/xls/zip) | 57 |
| Diskte bulunamayan | 7 |
| Açılamayan (bozuk/desteklenmeyen) | 59 |
| Toplam disk | **1.559,5 MB** |

> ⚠ **Belge kayması.** `MEDYA-DEPOLAMA-STANDARDI.md` "public 2.858 / private 192" diyor.
> Ölçülen: **4.350 / 608**. Belge yazıldığından bu yana public %52, private %217 büyümüş.
> Faz 2'de bu belgeye dayanan her sayı yeniden değerlendirilmeli.

### 1.1 Format ve renk modu

| Format | Adet | Pay |
|---|---:|---:|
| JPEG | 3.631 | %75,5 |
| PNG | 786 | %16,3 |
| WEBP | 384 | %8,0 |
| TIFF | 11 | %0,2 |

| Mod | Adet | Not |
|---|---:|---|
| RGB | 4.096 | — |
| RGBA | 597 | alfa kanallı |
| P | 74 | paletli |
| CMYK | **38** | tarayıcıda yanlış renk riski |
| L | 7 | gri tonlama |

### 1.2 Dağılım (yüzdelikler)

| Ölçü | p50 | p90 | p99 | uç |
|---|---:|---:|---:|---:|
| Megapiksel | 1,56 | 5,01 | **29,21** | **72,71** |
| Kısa kenar (px) | 1.120 | 2.160 | 4.480 | min 32 |
| Bayt | 81 KB | 869 KB | 3,6 MB | 22,1 MB |

### 1.3 Anomaliler

| Anomali | Adet | Anlamı |
|---|---:|---|
| **> 20 MP** | **179** | Dokümanın P-01 tuzağının ("18 MP / 1 MB → 9 sn") ölçülmüş hâli |
| **En büyük: 72,71 MP** | 1 | Dokümandaki `max_megapixels_hard = 80` bunu **geçirir**. Eşik gözden geçirilmeli |
| > 20 MB | 1 | — |
| CMYK | 38 | sRGB'ye çevrilmeli (`engine.optimize` çeviriyor, ama yalnız optimize edilende) |
| Alfa kanallı | 597 | Format zincirinde alfa korunmalı (JPEG'e düşürülemez) |
| 0 bayt | 0 | temiz |

**Sonuç:** projenin gerekçesi ölçümle doğrulandı. Bugün piksel tavanı politikası
**yok** (`media/` içinde tek satır DPI/piksel tavanı kodu geçmiyor) ve 179 dosya
20 MP üstünde duruyor.

---

## 2. Logo ölçümü — bekleyen kararları çözer (T-021)

**Kapsam:** `Admin Seller Profile.logo` (27) + `Brand.logo` (11) = 38 referans.

| Depolama biçimi | Adet | Not |
|---|---:|---|
| Diskte gerçek dosya | 18 | ölçülebilen küme |
| `data:image/svg+xml;base64,…` (DB'ye gömülü) | 18 | **hepsi DEMO seed kaydı**; gerçek satıcıda **0** |
| Diskte bulunamayan | 2 | ikisi de `DEMO-001`, `DEMO-002` |

> `data:` URI'lar yalnız seed verisinde. **Canlı bir yükleme yolu değil** — ama alan
> tipi buna izin verdiği için `seller-logo.json`'daki `accept.allow_data_uri` alanı
> yerinde bir önlem.

### 2.1 Ölçülen 18 gerçek logo

| Ölçüt | Sonuç |
|---|---|
| **JPEG payı** | **9/18 = %50** |
| Alfa kanallı (RGBA) | 4/18 = %22 |
| Oran bandı **1:2 … 2:1** içinde | **16/18 = %89** |
| Band dışı | 2 (ikisi de 2,876 = geniş kelime markası) |
| Kısa kenar < 512 (önerilen master) | 6/18 = %33 |
| Kısa kenar < 256 (sert ret eşiği) | 1/18 = %5,5 |
| Kısa kenar aralığı | 200 – 2.471 px |

### 2.2 Kararların ölçümle çözülmesi

`docs/standards/logo.md` §13'teki kararlar sayısal tetik taşıyordu. Ölçüm geldi:

| Karar | Tetik | Ölçüm | **Sonuç** |
|---|---|---:|---|
| **K1** JPEG logo: ret mi, uyarı mı? | "%10'u geçerse B'ye çevir" | **%50** | → **B**: kabul + uyarı + geçiş penceresi. Öneri A (ret) ölçümle **düştü**; mevcut logoların yarısını reddetmek kabul edilemez |
| **K2** Oran bandı 1:2…2:1 mi, 1:4…4:1 mi? | "%20'den fazlası 2:1 dışındaysa B'ye geç" | **%11** | → **A onaylandı**: band 1:2…2:1 kalır. 2 kelime markası (`egemen-plastik`, `timex-logo`, ikisi de 2,876) istisna olarak ele alınmalı |
| **K3** Merdiven 4 rung mu 5 mi? | "512 rung'u 40 KiB'e yaklaşırsa 5'e çık" | ölçülmedi | → **açık.** Rung baytı ancak türev üretimi (T-063) yazıldıktan sonra ölçülebilir |

**K1 ve K2 artık karar bekliyor değil, onay bekliyor.** Dokümanın kendi kuralı sonucu belirledi.

---

## 3. Ortam doğrulaması (T-000 açık kalemleri)

| Kalem | Sonuç |
|---|---|
| `ffmpeg` / `ffprobe` — backend | **VAR** (`/usr/bin/ffmpeg`, `/usr/bin/ffprobe`) |
| `ffmpeg` — queue-long (transcode worker) | **VAR** |
| `pyvips` | **YOK** — `ModuleNotFoundError`. T-007 benchmark'ı için kurulmalı (kapanış K-11) |
| Ayakta servis | 12 (db `healthy`) |

> **Üretim paritesi hâlâ açık:** yerelde ffmpeg var, ama üretim imajını Frappe Cloud
> kendi build ediyor ve `docker/backend.Dockerfile`'ı kullanmıyor. Bu ölçüm yerel
> ortamı doğrular, üretimi **doğrulamaz**.

---

## 4. Bu raporun kapatmadıkları

| Kalem | Neden |
|---|---|
| LCP / CLS ölçümü (T-004) | Tarayıcı otomasyonu gerekiyor; Lighthouse koşulmadı |
| T-006 golden fixture korpusu | Ayrı görev; bu ölçüm korpus üretmedi |
| T-007 kütüphane benchmark'ı | `pyvips` kurulu değil |
| Slot bazında dağılım | Bu ölçüm dosya düzeyinde; slot eşlemesi `bound_to` üzerinden ayrıca yapılmalı |
| Video dağılımı (23 dosya) | ffprobe ile süre/codec/bitrate dökümü yapılmadı |

---

## 5. Yeniden üretim

```bash
docker cp <betik> istoc-dev-backend-1:/tmp/x.py
docker exec -w /home/frappe/frappe-bench/sites istoc-dev-backend-1 ../env/bin/python /tmp/x.py
```
Ölçüm betikleri `scripts/media_stats.py` deseniyle uyumludur; bu rapordaki sayılar
o betiğin canlı koşumundan değil, aynı mantığın doğrudan çalıştırılmasından gelmiştir.

---

## 6. PII koruma açığının gerçek veride ölçümü (GÜVENLİK)

`media/access_level.py` PII korumasını iki yoldan yapıyor:
1. `attached_to_doctype in EXCLUDED_DOCTYPES`
2. `EXCLUDED_MEDIA_FIELDS` üzerinden **ters-referans taraması**

İkinci yol, birinci yol çalışmadığında (yani `attached_to_doctype` **boş** olduğunda)
devreye giren emniyet ağıdır — commit `19a2e61`'in çözdüğü CRITICAL tam buydu
(146 kimlik belgesi birinci yoldan kaçmıştı).

**Ölçülen boşluk:**

| Kontrol | Sonuç |
|---|---|
| `EXCLUDED_DOCTYPES` | 8 doctype |
| `EXCLUDED_MEDIA_FIELDS` | yalnız **5** doctype |
| Haritada olmayan | **`Order`, `Payment Transaction`, `Data Export Request`** |
| KYB ek alanı (gerçek) | 6: `identity_document`, `imza_sirkuleri`, `ticaret_sicil_gazetesi`, `faaliyet_belgesi`, `vergi_levhasi`, `bank_account_document` |
| KYB haritalanan | **2** (`identity_document`, `bank_account_document`) |
| KYB **haritasız** | **4**: `imza_sirkuleri`, `ticaret_sicil_gazetesi`, `faaliyet_belgesi`, `vergi_levhasi` |

**Bugünkü gerçek maruziyet (yerel veri):**

| Kaynak | Dosya | Durum |
|---|---:|---|
| `Order.receipt_url` | 1 | ⚠ `attached_to_doctype` boş **ve** haritada yok → **korumasız** |
| `Payment Transaction.receipt_url` | 1 | ⚠ aynı → **korumasız** (ödeme dekontu) |
| `Seller Certification.document` | 2 | ✓ `attached_to_doctype` boş ama haritada var → 2. yol yakalıyor |
| **Korumasız toplam** | **2** | — |

4 haritasız KYB alanında bu veri setinde açık dosya **yok** — boşluk **gizil** (latent).
KYB, PII'nin yoğunlaştığı yer olduğu için asıl risk orada.

> **Not:** bu ölçüm yerel veri setinde yapıldı. Üretimde dosya sayıları farklıdır;
> aynı betik üretimde koşulmalı.

**Düzeltme:** `media/presets.py` içindeki `EXCLUDED_MEDIA_FIELDS` haritasına 3 doctype
ve 4 KYB alanı eklenmeli. Ekleme yalnız **daha fazla** dosyayı korur, hiçbir şeyi açmaz.
(Bu turda kapsam "analiz + spesifikasyon" olduğu için kod değiştirilmedi.)

---

## 7. Video dağılımı (T-022 girdisi)

23 video dosyası; **5'i ffprobe ile okunabildi** (kalanı diskte yok ya da bozuk).

| Ölçüt | Sonuç |
|---|---|
| Codec | h264 (5/5) |
| Ses içeren | 4/23 |
| Süre | p50 **33 sn** · p90 = max **540 sn (9 dk)** |
| Bitrate | p50 **746 kbps** · max 1.169 kbps |
| Çözünürlük örnekleri | 720×1280 (9:16), 720×720 (1:1), 1280×720 (16:9), 352×352, 1920×1080 (16:9) |

**T-022 için çıkarımlar:**
- **Oran tek değil.** 9:16, 1:1 ve 16:9 birlikte var → tek oran dayatmak mevcut içeriği kırar.
- **540 sn'lik video** dokümanın ürün videosu için önerdiği 180 sn tavanını **3× aşıyor**;
  HLS eşiği kararı (K-?) bu gerçek üzerinden verilmeli.
- **352×352** çözünürlük, önerilen 720p tabanının çok altında — mevcut içerik için
  geçiş penceresi gerekecek.
- Bitrate'ler düşük (p50 746 kbps) → `transcode.py`'deki 2.5 Mbps eşiği bu içerikte
  **hiç tetiklenmiyor**; yani bugün bu videoların çoğu passthrough oluyor.

> **Veri kalitesi uyarısı:** `tabFile.file_size` videoların çoğunda dolu değil
> (p50 = 19 bayt). Bayt tabanlı hiçbir kural bu alana güvenmemeli; gerçek boyut
> diskten okunmalı.

# T-144 — Devreye alma (go-live) planı ve runbook'lar

**Görev:** T-144 · **Faz:** 14 · **Bağımlılık:** T-135, T-143 · **Tarih:** 2026-08-18
**Kaynak kabul kriterleri:** `docs/72-faz14-test-kabul.html` → T-144

---

## 0. Durum beyanı

> **DEVREYE ALMA YAPILMADI. GERİ DÖNÜŞ PROVASI KOŞULMADI.**
> Bu belge planı ve runbook'ları yazar. Kaynak doküman "geri dönüş prova
> edilmiş ve **süresi ölçülmüş**" istiyor; **o süre ÖLÇÜLMEDİ** (§5.4). Ölçüm
> yapılmadan bu kriter **KANIT YOK** durumundadır ve §7 kontrol listesinde
> işaretlenmemiştir.

**Bu belgedeki sayıların kaynağı üç türdür ve her birinin yanında yazılıdır:**
`dosya:satır` (kodda ölçülmüş sabit) · `hesap:` (aritmetik, formülü yanında) ·
`ÖLÇÜLMEDİ` (yapılması gereken ölçüm + komutu).

### 0.1 Bu planın kapsadığı "devreye alma" nedir

Devreye alınan şey **`media_engine` katmanının yükleme ve teslim yolunda
etkinleşmesidir**. Bugün bu katman `tradehub_core/media/`'nin YANINDA duruyor
ve üretim yolunda **çağrılmıyor** (`tradehub_core/media/pipeline/` altındaki hiçbir modül
`tradehub_core/hooks.py`'den referanslanmıyor — §8-D1 ile doğrulanacak).
Dolayısıyla go-live tek bir anahtar değil, **üç bağımsız anahtardır**:

| Anahtar | Ne değişir | Geri dönüşü |
|---|---|---|
| **A · Kabul kapısı** | Yükleme kararı slot politikasından verilir (FR-001/FR-015) | Bayrağı kapat; eski `upload_policy.check()` yolu zaten duruyor |
| **B · Türev üretimi** | Master + merdiven üretilir, `srcset` basılır | Bayrağı kapat; eski tek çıktı yolu duruyor. Üretilmiş türevler **kalır**, zarar vermez |
| **C · Backfill** | Geriye dönük standartlaştırma koşar | `runner.restore_batch` (30 gün penceresi) |

**Sıra zorunludur: A → B → C.** Gerekçe: B'nin ürettiği türevlerin doğru
geometride olması A'nın (slot kimliği) çalışmasına bağlıdır; C ise B'nin
kararı verilmeden başlatılamaz (`docs/plans/migration.md` §2.5 — 2000 px tavanı
ile 2400 px hedefi arasındaki **geri dönülemez** çelişki).

---

## 1. Özellik bayrağı — bugün YOK, yazılması gerekiyor

Aşamalı açılış bir bayrak mekanizması gerektirir. Kod tabanında medya için
böyle bir bayrak **bulunamadı**; doğrulama komutu §8-D2'de.

**Önerilen taşıyıcı:** `Marketplace Settings` doctype'ı (tekil ayar kaydı;
`tradehub_core/tests/test_marketplace_settings.py` ile test edilen mevcut
desen). Yeni alanlar:

| Alan | Tip | Anlamı |
|---|---|---|
| `media_engine_gate_enabled` | Check | Anahtar A |
| `media_engine_renditions_enabled` | Check | Anahtar B |
| `media_engine_rollout_percent` | Int (0–100) | Aşama yüzdesi |
| `media_engine_rollout_stores` | Small Text | Canary mağaza listesi (virgülle) |

**Yüzdenin belirlenimci olması şart:** rastgele seçim, aynı satıcının bir
istekte yeni bir istekte eski yola düşmesine yol açar ve hata ayıklanamaz hâle
gelir. Kural:

```
dahil = (crc32(store_id) % 100) < rollout_percent   ya da   store_id ∈ rollout_stores
```

Aynı mağaza her zaman aynı tarafta kalır; yüzde artınca **yalnız yeni mağaza
eklenir**, hiçbir mağaza geri çıkmaz.

---

## 2. Aşamalı açılış

Her aşama için: kim, ne kadar süre, hangi metrik izlenir, ilerleme koşulu ve
**geri dönüş eşiği**. Eşikler aşağıdaki tabloda; hiçbiri ölçüm sonrası
gevşetilmez.

### 2.1 Aşama tablosu

| Aşama | Kapsam | En az süre | İlerleme koşulu | GERİ DÖNÜŞ EŞİĞİ (herhangi biri) |
|---|---|---|---|---|
| **0 · Canary** | İç kullanıcılar + 1 gönüllü satıcı (`rollout_stores`) | **48 saat** | Sıfır kritik bulgu; en az 20 gerçek yükleme | Tek bir veri kaybı **veya** yanlış görsel servisi |
| **1 · %10** | `rollout_percent = 10` | **72 saat** | Aşağıdaki metriklerin hepsi eşik içinde | Ret oranı taban çizgisinin **2 katı**; hata oranı > **%2**; p95 yükleme süresi taban çizgisinin **1,5 katı** |
| **2 · %50** | `rollout_percent = 50` | **7 gün** | Aynı metrikler + satıcı şikâyeti artışı yok | Aynı eşikler + şikâyet sayısı önceki haftanın **2 katı** |
| **3 · %100** | `rollout_percent = 100` | — | — | Aynı eşikler; geri dönüş yolu **30 gün** açık kalır |

> **48 saat / 72 saat / 7 gün süreleri ÖLÇÜLMEDİ, seçildi.** Gerekçe: yükleme
> davranışı haftanın gününe göre değişir (hafta sonu satıcı aktivitesi düşer);
> 72 saatin altındaki bir pencere hafta içi–hafta sonu farkını göremez. Bu bir
> tasarım tercihidir, ölçüm değildir.

### 2.2 İzlenecek metrikler — ve her birinin taban çizgisi

| Metrik | Nereden okunur | Taban çizgisi |
|---|---|---|
| Yükleme hata oranı | `runner.read_progress` + API 5xx oranı | **ÖLÇÜLMEDİ** — §8-D3 |
| Ret oranı (politika reddi) | Ret kodlarının sayımı (`tradehub_core/media/pipeline/core/errors.py` kodları) | **ÖLÇÜLMEDİ** — bugün slot bazlı ret yok |
| p50/p95 yükleme süresi | Telemetri (`media_upload_succeeded.seconds`) | **ÖLÇÜLMEDİ** — olay yazılmadı (`faz14-uat.md` §5) |
| Kuyruk derinliği (`long`) | `frappe.utils.background_jobs.get_queue("long").count` | **ÖLÇÜLMEDİ** — §8-D4 |
| LCP (ürün detay) | Lighthouse CI (`lighthouserc.cjs:30-36` bütçeleri) | LCP < 2500 ms bütçesi tanımlı; saha ölçümü **ÖLÇÜLMEDİ** |
| Disk boş alan | `df` | **382 GB** (`media/backup.py:11`, ölçüm **2026-08-13**, tazelenmeli) |
| Satıcı şikâyeti | Helpdesk (HD Ticket) medya etiketi | **ÖLÇÜLMEDİ** |

> **Uyarı — bu tablo planın en zayıf yeridir.** Yedi metriğin altısının taban
> çizgisi yok. Taban çizgisi olmadan "2 katı" eşiği **uygulanamaz**. Bu yüzden
> §7 kontrol listesinde "taban çizgileri ölçüldü" ayrı bir kapıdır ve canary
> **öncesinde** kapanmalıdır.

---

## 3. Geri dönüş (rollback) prosedürü

### 3.1 Anahtar A ve B — bayrak kapatma

```
1. Marketplace Settings → media_engine_gate_enabled = 0
                        → media_engine_renditions_enabled = 0
2. bench --site <site> clear-cache
3. Doğrula: yeni bir yükleme eski yoldan geçiyor mu (log satırı / ret kodu biçimi)
```

**Beklenen süre: 2–5 dakika** — `hesap:` ayar kaydını değiştirme (≈30 sn) +
`clear-cache` (≈30 sn, `bench-docs.md` deseni) + doğrulama yüklemesi (≈2 dk).
**ÖLÇÜLMEDİ** (§5.4 provası koşulmadı).

Geri dönüşün **kalıcı etkisi yoktur**: A ve B yeni dosya adresi üretmez,
`file_url` değiştirmez (`archive.py:5-6`, `engine.py:8-9` garantisi). Üretilmiş
türevler diskte kalır ve `srcset` basılmadığı için servis edilmez.

### 3.2 Anahtar C — backfill geri alma

```python
# Batch bazında (önerilen)
start_restore(scope="selected", file_names=[...])     # api/media_admin.py:230-267
# Tüm optimize edilenler
start_restore(scope="optimized")
# Tek dosya, senkron
restore_image(file_name)                              # api/media_admin.py:221-228
```

**Sert takvim kısıtı:** geri alma penceresi **30 gün**
(`presets.py:38` `ARCHIVE_RETENTION_DAYS`). `archive.purge_expired` orijinali
sildikten sonra geri dönüş **yoktur**. Bu yüzden §7 kontrol listesinde
"backfill sırasında purge durduruldu mu" kapısı vardır.

**Geri alınamayan durum — kayda geçirilir:** `runner.restore_original`
`th_optimized_at` boşsa istisna atar (`runner.py:336-337`). Timeout kesilmesi
yaşanmış dosyalar (diskte optimize, DB'de damgasız) bu yüzden **otomatik geri
alınamaz**; elle kurtarılır. Tespit sorgusu `docs/plans/migration.md` §10-D2.

### 3.3 Geri dönüş kararı kimde

| Durum | Karar mercii | Beklenen süre |
|---|---|---|
| Veri kaybı / yanlış görsel servisi | Nöbetçi **tek başına** geri döner, sonra bildirir | anında |
| Eşik aşımı (metrik) | Nöbetçi + geliştirme sorumlusu | 15 dk içinde |
| Belirsiz / tartışmalı | Platform yöneticisi | 1 saat içinde |

**Kural:** şüphede kalındığında **geri dönülür**. Geri dönüşün maliyeti
5 dakikadır; yanlış görsel servis etmenin maliyeti satıcı güvenidir.

### 3.4 Prova — ÖLÇÜLMEDİ

Kaynak doküman geri dönüşün **prova edilmesini ve süresinin ölçülmesini**
istiyor. Prova koşulmadı. Koşulması gereken prova:

```
1. Yerel stack'te bayrakları aç, 5 dosya yükle (A + B aktif).
2. Kronometre başlat → bayrakları kapat → cache temizle → yeni yükleme yap.
3. Kronometre durdur. Ölçülen süreyi bu belgeye §3.1'e YAZ.
4. Backfill provası: 10 dosyalık batch koş (dry_run=0), sonra
   start_restore(scope="selected", file_names=[o 10 dosya]).
5. Doğrula: 10/10 dosya orijinal boyutuna döndü, th_optimized_at temizlendi.
   Süreyi yaz.
```

Bu prova yapılmadan **§7 kontrol listesindeki ilgili kutu işaretlenemez**.

---

## 4. Nöbet ve eskalasyon

| Seviye | Kim | Kapsam | Yanıt süresi hedefi |
|---|---|---|---|
| L1 | Nöbetçi geliştirici | Runbook uygulama, geri dönüş | 15 dk |
| L2 | Medya motoru sorumlusu | Runbook çözmezse kök neden | 1 saat |
| L3 | Platform yöneticisi | Kapsam/karar değişikliği, iletişim | 4 saat |

**Nöbet penceresi:** aşama 0–2 boyunca **09:00–21:00** (satıcı aktivitesinin
yoğun olduğu aralık — **ÖLÇÜLMEDİ**, panel giriş dağılımıyla doğrulanmalı).
Aşama 3'ten sonra normal nöbet.

**Alarm eşikleri (kurulacak):** hata oranı > %2 (5 dk pencere), `long` kuyruk
derinliği > 50, disk boş alan < %15, backfill `HALTED`. Bugün bu alarmların
**hiçbiri kurulu değil** — Faz 13'ün (T-130…T-139) işi.

---

## 5. RUNBOOK'LAR — 8 arıza senaryosu

Her runbook aynı dört başlığı taşır: **belirti · doğrulama komutu · çözüm ·
eskalasyon**. Komutlar `docker exec` desenindedir (`bench-docs.md` §2).

---

### R1 · Kuyruk birikmesi

**Belirti:** Yüklenen videolar `processing`'de kalıyor; satıcı "videom
hazırlanmıyor" diyor; backfill batch'leri ilerlemiyor.

**Doğrulama:**

```bash
docker exec -i istoc-dev-backend-1 bench --site istoc.localhost console <<'EOF'
from frappe.utils.background_jobs import get_queue
for q in ("short", "default", "long", "media_backfill"):
    try:
        k = get_queue(q)
        print(f"{q:16s} bekleyen={k.count} basarisiz={k.failed_job_registry.count}")
    except Exception as e:
        print(f"{q:16s} OKUNAMADI: {e!r}")
EOF
docker compose -f /Users/ahmet/Desktop/istoc/docker/docker-compose.yml ps queue-short queue-long
```

**Çözüm (sırayla):**

1. Backfill koşuyorsa **DURDUR** — orkestratör zaten canlı kuyruk derinliği
   > 0 iken enqueue etmiyor (`tradehub_core/media/pipeline/migration/backfill.py`
   `LiveTrafficGuard`), ama kuyruğa **girmiş** batch'i durdurmaz. Kalan
   batch'lerin enqueue'unu iptal et.
2. `long` kuyruğundaki uzun işi tanı: transcode mu backfill mi? Transcode
   tek iş en çok ~28 dk tutar (`transcode.py:52` timeout 1700 s + RQ 1800 s).
3. Kuyruk temizlenmiyorsa worker'ı yeniden başlat:
   `docker compose restart queue-long`.
4. Tekrarlıyorsa: backfill için **ayrı worker** aç (`migration.md` §5.2'deki
   `queue-media-backfill` servisi).

**Eskalasyon:** 30 dakikada düşmüyorsa L2.

---

### R2 · Disk dolması

**Belirti:** Yükleme 500 dönüyor; `No space left on device`; arşiv yazımı
başarısız (bu durumda dosyaya **dokunulmaz** — `runner.py:248` sırası
sayesinde veri kaybı yok).

**Doğrulama:**

```bash
docker exec istoc-dev-backend-1 sh -c '
  S=/home/frappe/frappe-bench/sites/istoc.localhost
  df -h $S
  du -sh $S/public/files $S/private/files 2>/dev/null
  du -sh $S/private/image_originals $S/private/media_trash $S/private/media-backups 2>/dev/null
'
```

**Çözüm:**

1. **ÖNCE arşivi bak, çöpü değil.** Backfill koştuysa disk geçici olarak
   şişer (`archive.py:11`: "Purge sonrası nihai kazanç gelir"). 30 günü
   dolmuş arşiv varsa `archive.purge_expired()`.
   ⚠ **Backfill doğrulama penceresi açıksa purge ÇALIŞTIRILMAZ** — geri dönüş
   kapanır (§3.2).
2. Çöp kutusunda süresi dolmuş dosyalar: `trash` süpürücüsü.
3. Yetim disk dosyaları: **1.166 adet ölçüldü** (canlı ölçüm). Silmeden önce
   `tradehub_core/media/pipeline/core/usage.py` yetim raporunu koştur; **otomatik silme yok**,
   bilinçli.
4. Hiçbiri yetmezse birim genişletme → L3.

**Eskalasyon:** boş alan < %10 → anında L2; < %5 → L3 + yüklemeleri geçici
kapat.

---

### R3 · S3 / nesne depolama kesintisi

**Belirti:** Aynalama hataları; S3 kipindeyse okuma 404.

**Doğrulama:**

```bash
docker exec -i istoc-dev-backend-1 bench --site istoc.localhost console <<'EOF'
import frappe
print(frappe.get_single("Media Storage Settings").as_dict() if
      frappe.db.exists("DocType", "Media Storage Settings") else "AYAR DOCTYPE'I YOK")
EOF
```

**Çözüm:**

1. **Ayna kipindeyse (`mirror`) yapılacak bir şey yok** — birincil yereldir,
   ikincil çökse bile yazma ve okuma sürer. Bu davranış testle sabitlendi
   (`tests/test_e2e_scenarios.py::Senaryo11S3AynalamaVeKesinti::
   test_s3_duserse_yerel_ayakta_kalir`).
2. **S3 birincil kipindeyse (`s3`)** derhal `local` kipine dön; `mirror`
   kipinde birikmiş yazımlar `reconcile` ile sonra eşitlenir.
3. Kesinti bitince: `MirrorStorage.reconcile` eksikleri kuyruğa alır.

**Eskalasyon:** S3 birincil kipte ve 15 dk içinde dönmüyorsa L2 → kip değişimi
kararı L3.

**Bilinen sınır:** S3 adaptörü **gerçek AWS/MinIO'ya karşı ÖLÇÜLMEDİ**;
sözleşme testleri sahte istemciyle koşuyor (`tests/test_storage_adapters.py`
docstring'i bunu yazıyor). İlk gerçek kesintide adaptör davranışı sürpriz
yapabilir.

---

### R4 · CDN / tarayıcı cache sorunu (bayat görsel)

**Belirti:** Satıcı görseli değiştirdi, eski görsel görünüyor.

**Doğrulama:**

```bash
curl -sI https://<site>/files/media/<asset>/<version_hash>/<profile>-<w>.webp \
  | grep -iE 'cache-control|etag|age|x-cache'
```

**Çözüm:**

1. **URL'de `version_hash` var mı?** Varsa bayat cache **yapısal olarak
   imkânsızdır**: içerik değişince adres değişir (INV-09;
   `tradehub_core/media/pipeline/core/dedup.py::version_hash`). Bayat görsel görünüyorsa sorun
   cache değil, **yayın**dır: yeni türevler üretilmemiş ya da manifest eski
   sürümü gösteriyor.
2. `Cache-Control: public, max-age=31536000, immutable` yalnız `version_hash`
   taşıyan adreslerde verilir. Hash'siz bir adreste bu başlık görülürse
   **BUG**'dır, purge ile örtülmez, düzeltilir.
3. Purge son çare; purge yapıldıysa **neden gerektiği bulgu olarak açılır**.

**Eskalasyon:** hash'siz adreste `immutable` görülürse anında L2 (kritik).

---

### R5 · Hatalı / bozuk türev

**Belirti:** Görsel bozuk açılıyor, yanlış kırpılmış, ya da kaynaktan büyük.

**Doğrulama:**

```bash
# Türev gerçekten açılabiliyor mu + kaynaktan büyük mü (INV-05)
python3 - <<'EOF'
from PIL import Image; import os, io
yol = "<turev-dosyasi>"
print(os.path.getsize(yol), Image.open(yol).size)
EOF
```

**Çözüm:**

1. **Anahtar B'yi kapat.** `srcset` basımı durur, storefront tek çıktıya döner.
2. Bozuk türevi sil — orijinal **dokunulmamıştır** (INV-11: orijinal daima
   korunur). Türev yeniden üretilebilir.
3. Kök neden: `tests/test_render_regression.py` koştur. Bayt temel çizgisi
   sapmışsa hangi profilde saptığı testin çıktısında görünür.
4. Kırpma yanlışsa: `Media Crop Intent` kaydını oku; `version_hash` niyeti
   içeriyor, yani yanlış niyet **yanlış adres** demektir — adres doğruysa
   niyet doğrudur, sorun render'dadır.

**Eskalasyon:** birden çok satıcıda görülüyorsa anında L2 + anahtar B kapalı
kalır.

---

### R6 · Toplu yeniden işleme (backfill) sorunu

**Belirti:** Backfill `HALTED`; ya da ilerlemiyor; ya da hata oranı yükseliyor.

**Doğrulama:**

```python
# Orkestratör raporu
rapor.to_dict()["stop"]        # → {"halt": true, "code": "...", "reason": "..."}
# Ham ilerleme
from tradehub_core.media import runner
runner.read_progress("backfill-0007")
```

**Çözüm — durdurma koduna göre:**

| Kod | Anlamı | Yapılacak |
|---|---|---|
| `error_rate_exceeded` | Hata oranı > %2 | **Devam ETME.** Hata örneklerini incele; kök neden bulunmadan yeniden başlatma |
| `skip_reason_anomaly` | `file_missing` / `decode_failed` > %1 | Disk–DB ayrışması ya da bozulma. `media_stats` yetim taraması koş |
| `progress_not_found` | İlerleme kaydı TTL'i doldu (3600 s) | Hata oranı **bilinmiyor**. Batch'i yeniden koşma; önce `runner.read_progress` penceresini kısalt |
| `job_not_terminal` | İş takılı | R1 (kuyruk) runbook'u |

**Yeniden başlatma kuralı:** `HALTED` bir koşum **otomatik devam etmez**.
Operatör kök nedeni yazılı olarak kaydeder, sonra `max_batches` ile **tek
batch** koşar ve sonucu doğrular.

**Eskalasyon:** `error_rate_exceeded` her zaman L2.

---

### R7 · Worker çökmeleri

**Belirti:** İşler `processing`'de kalıyor, kuyruk boş görünüyor; worker
konteyneri yeniden başlıyor.

**Doğrulama:**

```bash
docker compose -f /Users/ahmet/Desktop/istoc/docker/docker-compose.yml \
  logs --tail 200 queue-long queue-short
docker stats --no-stream istoc-dev-backend-1
```

**Çözüm:**

1. **Bellek mi?** Büyük görsel açan bir iş worker'ı OOM ile düşürebilir.
   Ölçülen en büyük dosya **72,71 MP**'dir (canlı ölçüm) ve kabul kapısı
   megapikseli **başlıktan** okuyup reddeder (`tradehub_core/media/pipeline/image/probe.py`).
   Kapı devrede değilse (Anahtar A kapalı) bu koruma **yoktur**.
2. Takılı işler süpürücü tarafından yeniden planlanır
   (`tradehub_core/media/jobs.py` `STALE_AFTER_SECONDS = 2700`). Süpürücünün
   koştuğunu doğrula.
3. Aynı iş tekrar tekrar düşürüyorsa: o dosyayı karantinaya al, backfill
   listesinden çıkar, bulgu aç.

**Eskalasyon:** 3 çökme / saat → L2.

---

### R8 · Saklama (retention) işinin takılması

**Belirti:** Süpürücü koşmuyor; ya da beklenenden çok siliyor.

**Doğrulama:**

```bash
docker exec -i istoc-dev-backend-1 bench --site istoc.localhost console <<'EOF'
import frappe
print(frappe.get_hooks("scheduler_events"))
EOF
```

**Çözüm:**

1. **Süpürücünün varsayılanı KURU KOŞUMDUR** (`RetentionSweeper.sweep()`
   `dry_run=True`) ve varsayılan politika **hiçbir şeyi silmez**
   (`tests/test_retention.py::TestKuruKosum::
   test_varsayilan_politika_hicbir_seyi_silmez`). "Çok siliyor" belirtisi
   varsa politika **elle değiştirilmiştir**; önce politikayı oku.
2. Legal hold açık ama kapı verilmemişse süpürücü **kurulmaz** (istisna atar)
   — bu bilinçli: "açık ama kapısız" legal hold, olmayandan tehlikelidir.
3. Koşmuyorsa: scheduler'ın genel olarak çalıştığını doğrula (medya işine özel
   değil, tüm zamanlanmış görevler durmuş olabilir).
4. **Backfill doğrulama penceresi açıkken arşiv purge'u DURDURULUR** (§3.2).

**Eskalasyon:** beklenmedik silme → anında L3 (veri kaybı sınıfı).

---

## 6. İletişim

| Kime | Ne zaman | Kanal | İçerik |
|---|---|---|---|
| Satıcılar (B sınıfı medyası olanlar) | Aşama 1 başlamadan **7 gün önce** | Panel bildirimi + e-posta | Hangi görsel, neden, son tarih (30 gün) — metin `migration.md` §6.2'de yazılı |
| Tüm satıcılar | Aşama 2 başlarken | Panel duyurusu | "Görsel kalitesi iyileştirmesi", eylem gerekmiyor |
| İç ekip | Her aşama geçişinde | Ekip kanalı | Metrik özeti + karar |
| Nöbet | Alarm anında | Alarm kanalı | Runbook bağlantısı |

**A sınıfı dosyalar için satıcıya bildirim YAPILMAZ** (`migration.md` §6.1):
dosya sunucuda düzelir, `file_url` değişmez, satıcının yapacağı bir şey yoktur.

---

## 7. Devreye alma kontrol listesi

Hepsi işaretlenmeden **canary başlamaz**. Bugün işaretlenebilen: **yok**.

**Ön koşullar**

- [ ] Özellik bayrağı mekanizması yazıldı ve belirlenimci yüzde kuralı test edildi (§1)
- [ ] §2.2'deki **yedi metriğin taban çizgisi ölçüldü** (bugün 6'sı yok)
- [ ] Alarm eşikleri kuruldu (§4) — Faz 13 çıktısı
- [ ] Medya telemetri olayları yazıldı (`faz14-uat.md` §5)

**Faz çıkış kriterleri**

- [ ] Faz 0…13 çıkış kriterleri işaretli ve kanıtlı → `docs/reports/13-faz14-kabul.md`
- [ ] Kritik bulgular kapalı (UAT + güvenlik)
- [ ] İzlenebilirlik matrisi %100 → bugün **%36,6** (`docs/test/traceability.md`)

**Operasyon**

- [ ] Geri dönüş provası **koşuldu ve süresi ölçüldü** (§3.4) — bugün ÖLÇÜLMEDİ
- [ ] Yedek/DR provası yapıldı (`docs/plans/backup-dr.md`)
- [ ] 8 runbook'un tamamı en az bir kez **okundu ve komutları doğrulandı**
- [ ] Nöbet planı yayında, eskalasyon iletişim bilgileri güncel
- [ ] Backfill sırasında arşiv purge'ünün durdurulacağı doğrulandı (§3.2)

**Eğitim / devir**

- [ ] Operasyon ekibi runbook eğitimi aldı
- [ ] Erişimler verildi (panel, kuyruk, log, depolama)

---

## 8. ÜRETİMDE DOĞRULANMALI

### D1 — `media_engine` üretim yolunda çağrılıyor mu

```bash
grep -rn "media_engine" /Users/ahmet/Desktop/istoc/tradehub_core/tradehub_core/ | wc -l
# Bu plan yazılırken beklenen: 0 (katman üretim yoluna BAĞLI DEĞİL)
```

### D2 — Medya için özellik bayrağı var mı

```bash
grep -rniE "media.*(flag|enabled|rollout)" \
  /Users/ahmet/Desktop/istoc/tradehub_core/tradehub_core/ | head -20
# Beklenen: yükleme/teslim yolunu kapatıp açan bir bayrak YOK
```

### D3 — Yükleme hata oranı taban çizgisi

```bash
docker exec -i istoc-dev-backend-1 bench --site istoc.localhost console <<'EOF'
import frappe
rows = frappe.db.sql("""
  select method, count(*) n from `tabError Log`
  where creation > date_sub(now(), interval 30 day)
    and (method like '%media%' or method like '%upload%')
  group by method order by n desc limit 20
""", as_dict=True)
for r in rows: print(r["n"], r["method"])
EOF
```

### D4 — Kuyruk derinliği taban çizgisi

R1'deki doğrulama komutu, **normal koşullarda** günde 3 kez (sabah/öğle/akşam)
bir hafta boyunca koşulur; medyan ve p95 kaydedilir. Eşik (`> 50`) bu ölçümden
sonra **güncellenebilir**; bugünkü değer bir tahmindir.

### D5 — Disk boş alanı (tazeleme)

```bash
docker exec istoc-dev-backend-1 df -h /home/frappe/frappe-bench/sites
# backup.py:11'deki 382 GB (2026-08-13) bu çıktıyla DEĞİŞTİRİLİR
```

---

## 9. Kaynaklar

- Kaynak tasarım dokümanı: `docs/72-faz14-test-kabul.html` → T-144
- `docs/plans/migration.md` — §2.5 (geri dönülemez çelişki), §5 (kuyruk),
  §6 (bildirim), §7 (durdurma), §10 (doğrulama komutları)
- `docs/plans/backup-dr.md` — yedek/DR provası
- `tradehub_core/media/pipeline/migration/backfill.py` — orkestratör, durdurma, atomik geçiş
- `tests/test_e2e_scenarios.py` — S3 kesintisi ve türev senaryolarının testleri
- `docs/reports/13-faz14-kabul.md` — faz çıkış kriterleri karnesi

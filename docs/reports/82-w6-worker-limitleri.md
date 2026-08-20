# 82 — W6: Worker izolasyonu ve kaynak limitleri (T-130, konteyner katmanı)

**Tarih:** 2026-08-20 · **Kapsam:** `docker/docker-compose.yml` — yalnız
`queue-long`, `queue-short`, `scheduler` blokları. Backend web servisi bilinçli
olarak DOKUNULMADI. **Rol:** T-130'un konteyner (cgroup) ayağı — uygulama içi
RLIMIT/megapiksel katmanının (W5-C, paralel ajan) İKİNCİ savunma hattı.

## 1. Ölçülmüş mevcut durum (değişiklik ÖNCESİ)

`grep mem_limit|cpus|pids_limit|ulimits|deploy` compose'ta **0 sonuç** —
dosyada hiçbir kaynak limiti yoktu. Canlı doğrulama (`docker inspect`):

| Konteyner | Memory | MemorySwap | NanoCpus | PidsLimit |
|---|---|---|---|---|
| queue-long | 0 (sınırsız) | 0 | 0 | yok |
| queue-short | 0 (sınırsız) | 0 | 0 | yok |
| scheduler | 0 (sınırsız) | 0 | 0 | yok |
| backend | 0 (sınırsız) | 0 | 0 | yok |

Yani her worker, 8.79 GiB'lık Docker VM'inin tamamını tüketebilirdi; tek bir
decompression-bomb işi db/redis/backend dahil bütün stack'i OOM'a sürükleyebilirdi.
57 raporunun bulgusuyla tutarlı: `security/isolation.py` (RLIMIT'ler) olgun ama
üretim yoluna bağlı değil; konteyner katmanında da hiçbir fren yoktu.

Rölanti kullanım (`docker stats`, işlem yokken): queue-long 50.4 MiB ·
queue-short 50.1 MiB · scheduler 58.4 MiB · PID 1-2.

## 2. Tavanı belirleyen ölçümler

Yöntem: gerçek üretim render yolu (`pipeline_bridge._profiles_for_slot` +
`render.render_rendition`, `product.image` slotunun 7 profil × biçim matrisi —
bugünkü 88 türevlik koşumun birebir kod yolu) worker konteynerinde koşuldu;
süreç zirvesi `resource.getrusage(ru_maxrss)`, konteyner zirvesi `docker stats`
örneklemesiyle alındı. DB'ye yazılmadı (yan etki yok).

| Girdi | Türev | Süreç zirve RSS | Konteyner örneklem zirvesi |
|---|---|---|---|
| Bugünkü koşumun tipik dosyası (`51N9LYNfAVL…jpg`, 38 667 B) | 12 | **181.5 MiB** | 57 MiB* |
| Kütüphanedeki en büyük gerçek kaynak (`Toplu resim-…-3.png`, 11 414 055 B) | 12 | **572.8 MiB** | 483.4 MiB |

\* tipik dosyada örnekleme (~2 sn/örnek) zirveyi ıskaladı; güvenilir değer
süreç RSS'i. Bugünkü gerçek koşum (07:31, `Media Processing Job` kayıtları
`success`) 22-41 KB'lık JPG'lerle çalıştı — tipik satır o sınıfı temsil ediyor.

## 3. Uygulanan limitler (`docker/docker-compose.yml`)

| Servis | mem_limit | memswap_limit | cpus | pids_limit | Gerekçe |
|---|---|---|---|---|---|
| queue-long | 2g | 2g | 2 | 256 | Ölçülen en kötü görsel zirvesinin (573 MiB) ~3.5 katı; video transcode (VP9, aynı kuyruk) bu koşumda **ÖLÇÜLMEDİ**, pay onun için. ffmpeg/AVIF thread'leri pids'e sayılır → 256 |
| queue-short | 1g | 1g | 1 | 128 | short/default işleri hafif; görsel işi bu kuyruğa girmiyor (`enqueue(queue="long")`) |
| scheduler | 512m | 512m | 0.5 | 64 | Yalnız enqueue eder; rölanti 58 MiB'in ~9 katı |
| backend | — | — | — | — | Bilinçli limitsiz (görev şartı: web'i boğma) |

`memswap_limit = mem_limit` → swap'a taşma yok; aşım deterministik OOM olur ve
`sweep_stuck_transcodes` süpürücüsü işi geri planlar (transcode.py'nin sert-kill
tasarımı tam bu senaryo için). `ulimits` EKLENMEDİ: konteyner içi süreç-başı
RLIMIT'ler T-130'un uygulama ayağının işi (`security/isolation.py`, W5-C hattı);
`nproc` gibi kullanıcı-bazlı ulimit'ler aynı UID'yi paylaşan konteynerler arası
yan etki yapar, fork frenini `pids_limit` veriyor.

Host kapasitesi: 11 CPU / 8.79 GiB (`docker info`). Üç servisin toplam tavanı
3.5 GiB + 3.5 CPU — db/redis/backend/ES'e alan kalıyor.

## 4. Uygulama ve canlı doğrulama

`docker compose up -d --no-deps queue-long queue-short scheduler` — yalnız üç
konteyner yeniden yaratıldı; backend/db/redis/frontend'e DOKUNULMADI
(`backend` inspect'i hâlâ Memory=0, "Up" süresi kesintisiz).

`docker inspect` (SONRA):

| Konteyner | Memory | MemorySwap | NanoCpus | PidsLimit | Durum |
|---|---|---|---|---|---|
| queue-long | 2147483648 | 2147483648 | 2000000000 | 256 | running |
| queue-short | 1073741824 | 1073741824 | 1000000000 | 128 | running |
| scheduler | 536870912 | 536870912 | 500000000 | 64 | running |

Konteyner içinden cgroup v2 çapraz doğrulama (scheduler):
`memory.max=536870912`, `pids.max=64`, `cpu.max=50000 100000` (=0.5 CPU).

- `GET /api/method/ping` → **200** (limitleme sonrası, iki kez).
- Kuyruk canlı: `frappe.enqueue(frappe.ping, queue="long")` →
  RQ `status: finished`; aynı test `queue="short"` → `finished`
  (worker `99a07283…` işledi). İki worker da limit altında iş tüketiyor.

## 5. Regresyon — bugünkü işlerin benzeri limit altında

En kötü gerçek girdiyle (11.4 MB PNG → 12 türev, tam profil matrisi) render
**limitli** queue-long içinde tekrar koşuldu:

- çıkış kodu 0, `uretilen=12`, süreç zirve RSS **570.0 MiB**
- `docker stats` örneklem zirvesi **502 MiB / 2 GiB**, PID zirvesi 13/256
- `docker inspect` → `OOMKilled=false`, `Status=running`

Yani bugünkü 88 türevlik koşumun en ağır tek-dosya senaryosu 2 GiB tavanının
%28'inde bitiyor; limit hiçbir gerçek işi öldürmüyor.

Kararlı durum (iş yokken): queue-long 50.4 MiB/2 GiB · queue-short 49.5 MiB/1 GiB ·
scheduler 56.8 MiB/512 MiB · ping 200.

## 6. ÖLÇÜLMEDİ / notlar

- **Video transcode zirvesi ÖLÇÜLMEDİ** (kuyrukta bekleyen video işi yoktu;
  sentetik video üretimi kapsam dışı bırakıldı). 2g tavanı görsel ölçümünün
  3.5 katı pay bırakıyor; ilk gerçek VP9 işinde `docker stats` ile doğrulanmalı.
  OOM olursa `sweep_stuck_transcodes` işi geri planlar (tasarım gereği) ama
  tavan ölçüme göre yükseltilmeli.
- **Scheduler tick'i ölçülemedi**: site scheduler'ı zaten kapalı
  (`is_scheduler_disabled=true`, son `last_execution` 2026-08-03 — değişiklikten
  17 gün önce, bu işin yan etkisi değil). Süreç ayakta (PID 1 `bench schedule`),
  limitler cgroup'ta doğrulandı; scheduler açıldığında 512m yeterliliği izlenmeli.
- Ölçüm betiği konteyner `/tmp/measure_render.py`'de kaldı (root'a ait, frappe
  silemiyor); konteyner efemerál, ilk yeniden yaratmada kaybolur. Uygulama
  koduna hiçbir dosya eklenmedi.
- T-130'un kabul kriterlerinden "her medya işi ayrı süreçte + RLIMIT" ve
  "ağ erişimi kapalı" ayakları bu işin kapsamı DIŞINDA (uygulama katmanı /
  W5-C; ağ kapatma, worker'ın db/redis/S3'e muhtaçlığı yüzünden ayrı tasarım
  ister). Bu iş, şartnamenin "izole worker + bellek limiti" konteyner katmanını
  kapatır.

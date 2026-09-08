# 113 — MOGEM-620 AI katmanı: sunucuya ne kurulacak

**Tarih:** 7 Eylül 2026
**Soru:** MOGEM-620'nin açık kalan AI/semantik katmanı için sunucuya ne kurulmalı?
**Durum:** karar belgesi — kurulum YAPILMADI, yalnız ölçüldü ve fiyatlandırıldı
**Karar sahibi:** PM/ops (§11.7 · `MOGEM-620-DURUM.md` D bölümü, 28 Ağu'da ertelendi)

---

## 1. Neyi kuruyoruz — açık kalan AI işleri

MOGEM-620'nin 18 bölümünden **kodla kapatılabilecek olanların tamamı bitti**.
Geriye kalan her şey tek bir kararın arkasında duruyor: AI servisi. Bugün açık
olan maddeler ve her birinin gerçekte istediği yetenek:

| # | Bölüm | Açık kalan | Gereken yetenek |
|---|---|---|---|
| 3 | AI Metadata Generation | `th_media_alt_ai` kolonunu dolduracak servis yok | **görsel→metin** (captioning), 4 dil |
| 5 / 15 | Video + File Manager | transcript/VTT "AI gelene kadar elle" | **konuşma→metin** (ASR) |
| 10 | Visual Search + Semantic | object/OCR/logo tanıma, embeddings, entity graph | **görsel embedding + OCR + tespit** |
| 16 | Media Library Search | OCR/semantic/vector arama | **metin + görsel embedding** |
| 17 | Categorization | etiket önerisi bugün kural-tabanlı | **sınıflandırma** (embedding ile de olur) |

Buna repoda hazır bekleyen bir kalem daha ekleniyor: **T-014 smartcrop** ONNX
prototipi ölçüldü (rapor 14) ama üretimde çalıştıracak runtime kurulu değil.

Şema tarafında yapılacak bir şey yok: `th_media_alt_ai`, `th_media_alt_source`
(`rule/ai/human/edited`), `th_media_transcript`, `th_media_captions_url`,
`th_media_extracted_text` kolonlarının hepsi **açık ve okuma kapısına bağlı**.
Servis takıldığında yapılacak tek iş bu kolonları doldurmak.

---

## 2. Bugün sunucuda ne var, ne yok (ölçüm — 7 Eyl 2026)

`istoc-backend` konteynerinde ölçüldü. **Sistem python'u değil, bench sanal
ortamı** (`~/frappe-bench/env/bin/python`) esas alındı.

**Taban:** Debian 12 bookworm · bench venv **Python 3.12.12** · 12 vCPU ·
27 GB RAM · 365 GB boş disk · **ayrık GPU yok** (AMD Cezanne tümleşik).

| Var | Sürüm | Yok |
|---|---|---|
| `ffmpeg` / `ffprobe` | 5.1.9 | `onnxruntime` |
| `tesseract` ikilisi | 5.3.0 (`eng`, `osd`, `tur`) | **`pytesseract`** (python paketi) |
| `clamscan` | 1.4.3 | `torch`, `transformers` |
| `numpy` | 2.5.1 | `sentence-transformers`, `faiss` |
| `Pillow` | 12.2.0 | `openai`, `anthropic` SDK |
| `pyvips` | 3.2.0 | `httpx` |
| `scikit-learn` | 1.9.0 | herhangi bir model dosyası |
| `pypdf` | 6.13.3 | |

**İki bulgu ölçümden çıktı:**

1. **OCR bugün çalışmıyor.** `tesseract` ikilisi kurulu ama `pytesseract`
   paketi bench ortamında **yok** — `requirements.txt` onu beyan ediyor,
   `pyproject.toml`'un kurduğu şey o dosya değil. Yani
   `scripts/calibrate_content_rules.py` OCR sinyalini "unavailable" yazıyor
   (dürüst davranıyor, 0 saymıyor) ve `th_media_extracted_text` yalnız PDF
   **metin katmanından** doluyor (`doc_meta._extract_pdf`, pypdf). Taranmış
   PDF ve görsel üstü metin bugün tamamen görünmez.
2. **`pyvips` 3.2.0 kurulu, `pyproject.toml` `<3` diyor.** AI işiyle ilgisiz,
   ama imaj tarifi yeniden pişerken patlayacak bir tutarsızlık — kurulum
   kararıyla aynı turda bakılmalı.

---

## 3. Ne kadar iş var — envanter (yerel prod-restore verisi)

| Varlık | Adet | Boyut |
|---|---:|---:|
| Görsel (jpg/jpeg/png/webp/tif) | **4.804** | 899 MB |
| Video (mp4/webm) | 576 | 9 MB — **bunlar test fixture'ı, gerçek video değil** |
| PDF | 14 | — |
| Ses | 0 | — (katman 6 Eyl'de kodlandı, envanter boş) |

**Video sürelerinin tamamı boş** (`th_media_duration` 576/576 sıfır) ve toplam
9 MB. ASR maliyeti **bu veriden hesaplanamaz**; gerçek video envanteri prod'dan
ölçülmeden transcript kalemine bütçe verilmemeli.

---

## 4. İki yol

### Yol A — Bulut API (sunucuya model kurulmaz)

Sunucuya kurulacak tek şey birkaç MB'lık istemci kütüphanesi:

```
pip: httpx>=0.27          # ya da mevcut requests ile idare edilir
pip: openai / anthropic   # hangi sağlayıcı seçilirse (~5-10 MB)
```

Gereken diğer şeyler kod değil, altyapı: **giden 443 çıkışı** ve anahtar kasası
(şema hazır — `test_secret_access_audit` zaten `openai`/`openai_api_key`
alanının denetimini sınıyor).

- **Artı:** donanım yatırımı sıfır, kalite bugün yerel modellerin üstünde,
  Türkçe alt metni kalitesi belirgin şekilde daha iyi.
- **Eksi:** **ürün görselleri sunucudan çıkar.** KVKK/veri gizliliği kararı
  burada verilir, teknik masada değil. Ayrıca 4.804 görsellik geri doldurma
  tek seferlik bir fatura üretir ve her yeni yüklemede tekrar eder.

### Yol B — Yerel (self-hosted)

Veri sunucudan çıkmaz, tekrar eden maliyet yok; karşılığında disk, RAM ve
kurulum bakımı. Aşağıdaki tablo yetenek yetenek ne kurulacağını veriyor.

| Yetenek | Sistem paketi (apt) | Python paketi | Model | Disk |
|---|---|---|---|---:|
| **OCR** (taranmış PDF, görsel üstü metin) | `tesseract-ocr` ✅ var · **+`tesseract-ocr-ara`, `-rus`** · `poppler-utils` (PDF→görsel) | **`pytesseract`** | tessdata (dil başına ~5-15 MB) | ~100 MB |
| **Smartcrop / odak** (T-014, prototip hazır) | — | `onnxruntime` (CPU) | U²-Net-P **4.574.861 bayt**, SHA repoda | ~60 MB |
| **Görsel embedding** (benzer/semantik arama) | — | `onnxruntime`, `tokenizers` | CLIP ViT-B/32 ONNX (görsel+metin kulesi) | ~400 MB |
| **Metin embedding** (çok dilli arama) | — | aynı runtime | multilingual-e5-small (int8 ONNX daha küçük) | ~150-500 MB |
| **Nesne/logo tespiti** | — | `onnxruntime` | YOLO sınıfı ONNX | ~50 MB |
| **Transcript / VTT** | `ffmpeg` ✅ var | `faster-whisper` + `ctranslate2` | whisper small / medium / large-v3 | ~0,5 / 1,5 / 3 GB |
| **Alt/caption önerisi** | — | `torch` (CPU wheel) + `transformers` | küçük VLM (Florence-2-base sınıfı) ~1 GB; **kabul edilebilir Türkçe için 2-7B sınıfı** | 1 GB → 15 GB |

> Model boyutları **yaklaşıktır** ve kurulum anında teyit edilmelidir. Repoda
> ölçülmüş tek gerçek rakam U²-Net-P'nin 4.574.861 baytı ve SHA-256'sıdır
> (rapor 14). Diğerleri sipariş verilecek rakam değil, mertebe göstergesidir.

**Yol B'nin toplamı:** OCR + smartcrop + embedding + ASR(small) ≈ **1,5-2 GB**
disk, `torch` istemez, CPU'da koşar. Alt/caption üretimi eklenirse `torch`
(~200 MB wheel) + model ile **3-18 GB** arasına çıkar; asıl sıçrama buradadır.

---

## 5. Donanım: mevcut sunucu yeter mi?

Elimizde **tek gerçek CPU ölçümü** var: aynı makinede ONNX U²-Net-P
**168,83 ms/görsel ortalama, p90 217,87 ms** (rapor 14, 50 gerçek katalog
görseli). Bundan türetilen:

| İş | Hesap | Süre (tek iş parçacığı) |
|---|---|---|
| 4.804 görselin smartcrop'u | 4.804 × 169 ms | **~13,5 dakika** |
| 4.804 görselin CLIP embedding'i | benzer mertebe, **ölçülmedi** | ~15-30 dk (tahmin) |
| 4.804 görselin OCR'ı | tesseract görsel başına ~0,3-1 s | ~25-80 dk (tahmin) |

12 vCPU'ya bölününce hepsi **gece koşusuna sığar**. Embedding ve OCR için GPU
gerekmez.

**Ayrık GPU yok** ve alınması da gerekmiyor — tek istisna alt/caption üretimini
yerel büyük bir VLM ile yapma kararı. O senaryoda CPU üzerinde görsel başına
saniyeler mertebesinde süre çıkar; 4.804 görsel için gece koşusu yetmez.
**Yerel captioning istiyorsak GPU konuşulur, diğer her şey için konuşulmaz.**

⚠️ **Bu ölçümlerin tamamı geliştirme makinesindendir** (12 vCPU / 27 GB / GPU
yok). Prod sunucusunun özellikleri bu belgeye girmedi çünkü elimde yok. Karar
öncesi prod'un vCPU/RAM/disk değerleri alınmalı; 4 vCPU'luk bir sunucuda
yukarıdaki süreler üçe katlanır.

---

## 6. Kurulmayacaklar — ve nedeni

- **Vektör veritabanı (Qdrant/Milvus/pgvector) GEREKMİYOR.** 4.804 görsel ×
  512 boyut × float32 = **~10 MB**. Tek `numpy` matris çarpımı milisaniyeler
  sürer; `numpy` zaten kurulu. Vektör DB'si yüz binlerce varlıkta anlamlı olur.
  Bugün kurmak bakımı olan, kazancı olmayan bir servis eklemektir.
- **Elasticsearch'e dokunulmuyor.** İmajda kurulu değil; kurmak `HAS_ES`'i
  `True` yapar ve `sync_document_to_es` her doküman güncellemesinde yazmaya
  başlar — davranış değişikliği, ayrı görev (`requirements.txt` notu).
- **`torch`, Yol B'nin captioning kalemi seçilmedikçe kurulmaz.** OCR,
  embedding, ASR ve smartcrop'un hiçbiri `torch` istemiyor; `onnxruntime` +
  `ctranslate2` yeterli. Gereksiz `torch` imaja ~2 GB ekler.

---

## 7. Kurulum nereye yazılır — kalıcılık tuzağı

Bu, kurulum listesinden daha kritik. **Elle `pip install` yapılırsa kaybolur.**
29 Ağustos'ta medya kuyruğu (worker + ffmpeg/pyvips/tesseract) elle kurulmuştu
ve kalıcı değildi. Aynı hataya düşmemek için:

1. **Python paketleri → `pyproject.toml` `[project].dependencies`.**
   `requirements.txt`'e yazmak YETMEZ; imaj tarifi yalnız
   `pip install -e apps/tradehub_core` koşuyor, yani gerçekte kurulan şey
   `pyproject.toml`. `elasticsearch` yıllardır bu yüzden kurulu değil —
   `pytesseract` de aynı tuzağa düşmüş durumda (bkz. §2).
2. **Sistem ikilileri → imaj tarifindeki `apt-get`.** Not: bu checkout'ta
   `docker/backend.Dockerfile` **yok**; `docker-compose.yml` doğrudan
   `frappe/bench:latest` kullanıyor ve `docker/` dizininde yalnız `.env` var.
   Tarifin nerede olduğu (ayrı deploy reposu mu?) kurulumdan önce netleşmeli —
   yoksa "kur" kararı yine elle kuruluma düşer.
3. **Model dosyaları imaja GİRMEZ.** İmajı şişirir ve sürümlemeyi zorlaştırır.
   Repoda doğru emsal zaten var: `scripts/fetch_smartcrop_model.py` —
   sabit URL + **SHA-256 doğrulaması** + boyut tavanı + atomik yazım. Her yeni
   model aynı desenle, kalıcı bir hacme (`/home/frappe/models` gibi) indirilir.
4. **Kurulumdan sonra imaj yeniden pişirilir.** `MOGEM-620-DURUM.md` C
   bölümündeki bekleyen "imaj rebuild" işiyle aynı turda yapılmalı.

---

## 8. Öneri — üç faz

Yol A/B kararı verilmeden de başlanabilecek işler var. Ucuzdan pahalıya:

**Faz 0 — bugün yapılabilir, karar beklemez (~100 MB, sıfır maliyet)**
`pytesseract` + `tesseract-ocr-ara`/`-rus` + `poppler-utils` + `onnxruntime`.
Kazanç: OCR gerçekten çalışır (taranmış PDF ve görsel üstü metin aranabilir
olur), smartcrop prototipi üretime alınabilir. Hiçbir veri sunucudan çıkmaz,
hiçbir sağlayıcı seçimi gerekmez. **Zaten beyan edilmiş ama kurulmamış bir
paketi kurmak** — yeni bir karar değil, bir eksiğin kapatılması.

**Faz 1 — semantik arama, yerel (~0,5-1 GB)**
CLIP ONNX + metin embedding modeli, vektörler `numpy` ile bellekte. Bölüm 10
ve 16'nın "kalan"ını kapatır. Veri dışarı çıkmaz.

**Faz 2 — alt/caption + transcript: asıl karar burada**
- Kalite ve hız isteniyorsa **Yol A (bulut API)**; kurulacak tek şey SDK.
  Bedeli: ürün görselleri dışarı çıkar → KVKK kararı.
- Veri çıkmasın deniyorsa **Yol B**; transcript için `faster-whisper` CPU'da
  makul, **captioning için GPU konuşulur**.
- Hangisi seçilirse seçilsin **onay akışı değişmiyor**: öneri `th_media_alt_ai`
  kolonuna yazılır, `alt`'a asla doğrudan yazılmaz (§5.2a).

---

## 9. Karar için gereken, bende olmayan üç girdi

1. **Prod sunucusunun vCPU/RAM/disk değerleri** — §5'teki süreler geliştirme
   makinesinden; prod daha küçükse fazlar yeniden sıralanır.
2. **Ürün görselleri ve satıcı dokümanları üçüncü tarafa gönderilebilir mi?**
   Yol A/B'yi teknik değil bu soru belirliyor (§11.7'nin "veri gizliliği" şıkkı).
3. **Gerçek video envanteri** (adet + toplam süre) — dev'deki 576 kayıt 9 MB'lık
   fixture; transcript bütçesi bu veriyle hesaplanamaz.

---

## 10. Özet tablo — "sunucuya ne kurulacak"

| Karar | Kurulacaklar | Disk | GPU |
|---|---|---:|---|
| **Hiçbir şey seçilmese bile** (eksik kapatma) | `pytesseract`, `tesseract-ocr-ara/-rus`, `poppler-utils` | ~100 MB | hayır |
| **+ smartcrop üretime** | `onnxruntime`, U²-Net-P modeli | +60 MB | hayır |
| **+ semantik/görsel arama** | CLIP ONNX + metin embedding modeli | +0,5-1 GB | hayır |
| **+ transcript, yerel** | `faster-whisper`, `ctranslate2`, whisper modeli | +0,5-3 GB | hayır (yavaş) |
| **+ alt/caption, yerel** | `torch`, `transformers`, VLM | +3-18 GB | **evet** |
| **+ alt/caption, bulut** | sağlayıcı SDK + `httpx` | ~10 MB | hayır |

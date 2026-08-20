# 53 · F1 Altyapı — araç kurulumu, imaj devri, T-032 CI kapısı

**Tarih:** 2026-08-19
**Şerit:** F1 (altyapı ve dağıtım) — `docker/**`, `.github/workflows/**`,
`tradehub_core/requirements.txt`, `tradehub_core/pyproject.toml`
**Ortam:** macOS arm64, Docker Desktop, `istoc-dev` compose projesi (14 servis)

---

## 0. Özet — ne ölçüldü, ne değişti

| Kalem | Önce (ölçüldü) | Sonra (ölçüldü) | Tıkadığı görev |
|---|---|---|---|
| `libvmaf` | `ffmpeg -filters \| grep -c libvmaf` → **0** | → **1**; `vmaf_available()` → `True`; gerçek ölçüm `{'measured': True, 'metric': 'vmaf', 'vmaf': 80.831408}` | T-072 · T-075 |
| `tesseract` | `tesseract: command not found` | **5.3.0**, diller `eng osd tur`; `pytesseract.get_tesseract_version()` → `5.3.0` | T-025 |
| `boto3` | **1.34.162 kurulu** ama beyansız (aşağıda düzeltme) | aynı sürüm, artık `pyproject.toml` + `requirements.txt`'te beyanlı; **91/91 MinIO testi yeşil** | T-050 · T-051 · T-055 |
| CI kapısı | 5 workflow, hiçbirinde test/lint yok; `[tool.mypy]` yok; `.pre-commit-config.yaml` yok | `ci.yml` (4 job) + `[tool.mypy]` + `.pre-commit-config.yaml`; **GitHub Actions'ta henüz koşmadı** | T-032 |

**Değişen dosyalar:**

- `docker/backend.Dockerfile` — yeni araç katmanı
- `docker/README.md` — "Medya araçları" bölümü
- `tradehub_core/pyproject.toml` — `boto3`, `pytesseract`, `[tool.mypy]`
- `tradehub_core/requirements.txt` — aynı bağımlılıklar + dosyanın kullanılmadığı uyarısı
- `tradehub_core/.github/workflows/ci.yml` — **yeni**
- `tradehub_core/.pre-commit-config.yaml` — **yeni**
- bu rapor

⚠️ **`docker/` bir git reposu DEĞİL.** `backend.Dockerfile`, `docker-compose.yml`
ve `nginx/gateway.conf` üzerindeki hiçbir değişiklik versiyonlanmıyor; geri
alınamaz, kim ne zaman değiştirdi görünmez. Bu raporun §7'si o yüzden var:
kalıcı olması gereken kararları versiyonlanan tarafa (bu dosyaya) yazıyor.

---

## 1. Brifingin bir maddesi YANLIŞTI — `boto3` düzeltmesi

Görev tanımı `boto3` için şöyle diyordu: *"requirements.txt'te ve imaj
tarifinde yok; çalışan konteynere elle kurulmuş, rebuild'de kaybolur → 91
MinIO testi düşer."*

**İlk iki iddia doğru, üçüncüsü değil.** Ölçüm:

```bash
# Çalışan konteyner ile imajın pip listeleri BİREBİR AYNI (elle kurulum yok)
docker exec istoc-dev-backend-1 env/bin/pip list --format=freeze | sort > A
docker run --rm --entrypoint .../pip istoc/tradehub-backend:v15 list --format=freeze | sort > B
diff A B      # → çıktı YOK (184 paket, 0 fark)

# dpkg tarafı da aynı
diff dpkg_image dpkg_running   # → çıktı YOK

# boto3 nereden geliyor: base imajdan, frappe'nin transitif bağımlılığı olarak
docker run --rm --entrypoint .../python frappe/erpnext:v15 -c "import boto3; print(boto3.__version__)"
# → base boto3 1.34.162
```

Yani `boto3` **rebuild'de kaybolmazdı**; `frappe/erpnext:v15` base imajı zaten
getiriyor. Gerçek risk daha sessiz: **beyansız transitif bağımlılık.** Frappe
bir gün `boto3`u bırakırsa 91 MinIO testi ve `media/pipeline/storage/s3.py`
sessizce düşer ve kimse sebebini bağlayamaz. Bu yüzden yine de eklendi —
"kurulsun diye" değil, **beyan edilsin diye**.

---

## 2. İmaj kurulmadan ÖNCE: host ↔ konteyner farkı

Kural gereği (bugün bir ajan `docker cp` ile taşınmış işini tam bu yüzden
kaybetmiş) imaj derlenmeden önce ölçüldü: **konteynerde olup host'ta olmayan
hiçbir şey var mı?**

```bash
docker cp istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/. /tmp/ctr_app/
diff -rq --exclude=__pycache__ --exclude='*.pyc' --exclude=.ruff_cache \
     tradehub_core/ /tmp/ctr_app/ | grep -c 'Only in /tmp/ctr_app'
# → 0
```

**Üç eksende de konteyner-özel değişiklik YOK:**

| Eksen | Ölçüm | Sonuç |
|---|---|---|
| App kodu (`apps/tradehub_core`) | `diff -rq` → **0** "Only in container" | Kaybedilecek bir şey yok |
| Python paketleri | `pip list` farkı → **0** satır | Elle `pip install` yapılmamış |
| Sistem paketleri | `dpkg -l` farkı → **0** satır | Elle `apt install` yapılmamış |

Ters yön ise doluydu — **host konteynerin katı üst kümesiydi**. İmaja giren,
o güne kadar çalışan konteynerde OLMAYAN başlıca içerik:

- `tradehub_core/api/observability.py` (yeni dosya)
- `tradehub_core/tradehub_core/doctype/media_usage/` ve `media_version/` (2 yeni DocType)
- `patches/v15_9_28…v15_9_32` (**5 yeni patch**) + değişmiş `patches.txt`
- değişmiş `hooks.py` (T-133 metrik kablolaması), `permissions.py` (T-043/T-064)
- 30+ yeni `docs/reports/*.md`, `docs/adr/`, `docs/security/kvkk.md`

> ⚠️ **Şerit A ajanına doğrudan sonuç:** Bu içerik artık imajda ve çalışan
> konteynerlerde. `patches.txt`'e eklenen **5 patch bir sonraki `bench migrate`
> koşumunda çalışacak**. Sıra `patches.txt`'te zaten yazılı (Media Version →
> Media Asset.active_version). Ben `bench migrate` **koşmadım** (yasak listede).

---

## 3. `docker/backend.Dockerfile` — ne eklendi ve niye orada

Yeni katman **ağır `bench get-app`/`bench build` katmanından SONRA, app
`COPY`'sinden ÖNCE**. Sebep: yukarısı (crm + helpdesk Vue SPA derlemesi)
cache'ten gelsin, aşağısı (app kodu) her değiştiğinde bu araçlar yeniden
kurulmasın. Ölçüldü: yeniden derlemede yalnız 3 katman koştu, `bench build`
cache'ten geldi.

### 3.1 ffmpeg — niye statik derleme, niye apt değil

`media/pipeline/video/transcode.py::vmaf_available()` PATH'teki `ffmpeg`i
çağırıp filtre listesinde `" libvmaf "` arıyor. Debian bookworm'ün paketi
(5.1.9) libvmaf **olmadan** derlenmiş — `--enable-*` listesinde yok, kontrol
edildi. Yani apt'tan çözüm yok; libvmaf ffmpeg'in derleme zamanı kararı.

Seçilen yol: **BtbN FFmpeg-Builds statik GPL derlemesi**, `/usr/local/bin`e.
Konteyner PATH'i `/usr/local/bin:/usr/bin:...` olduğu için apt sürümünü
gölgeler; apt sürümü `/usr/bin/ffmpeg` olarak **yerinde bırakıldı** (geri
dönüş yolu).

Kararlar:

- **Sürüm pinli, `latest` DEĞİL.** `latest` hareketli hedef; aynı Dockerfile
  yarın başka bir ikili üretir. Üç ARG birlikte güncellenir
  (`FFMPEG_RELEASE_TAG` / `FFMPEG_ASSET_STEM` / `FFMPEG_ASSET_SUFFIX`) çünkü
  BtbN'in dosya adı git hash'i taşıyor.
- **`n8.1` sürüm hattı**, master değil. Master gecelik; 8.1 yayınlanmış hat.
- **`TARGETARCH` ile iki mimari.** arm64 → `linuxarm64`, amd64 → `linux64`.
  Bilinmeyen mimaride build **düşer** (sessizce yanlış ikili kurmaz).
- **VMAF modeli ayrıca gerekmiyor** — libvmaf 2.x `vmaf_v0.6.1`i kütüphaneye
  gömüyor. Doğrulandı: gerçek ölçüm skor döndürdü, "model not found" yok.
- **Build içinde kanıt kapısı:** `ffmpeg -filters | grep -q " libvmaf "`.
  Filtre yoksa build orada düşer; "kuruldu" diyen ama ölçmeyen bir imaj çıkmaz.
- **Bedel:** `ffmpeg` + `ffprobe` statik ikilileri ~204 MB. `ffplay`
  kopyalanmadı.

### 3.2 tesseract

`apt-get install tesseract-ocr tesseract-ocr-eng tesseract-ocr-tur`
(+ `xz-utils`, statik arşivi açmak için — base imajda `xz` yoktu).
Python köprüsü `pytesseract` `pyproject.toml`'a eklendi, `pip install -e`
ile geliyor.

Türkçe dil paketi bilinçli: `content_rules.json` `overlay_text` kuralı
Türkçe bindirme metinlerini (İNDİRİM / KAMPANYA / STOK) hedefliyor.

### 3.3 `requirements.txt` gerçekte KURULMUYOR — ölçülmüş bir sapma

`backend.Dockerfile` yalnız `pip install -e apps/tradehub_core` koşuyor; yani
kurulan şey `pyproject.toml [project].dependencies`. `requirements.txt` imaj
tarifinde **hiç okunmuyor**.

Doğrudan sonucu ölçüldü: **`elasticsearch` imajda KURULU DEĞİL** —
`requirements.txt`'te var (`elasticsearch>=8.0.0`) ama `pyproject.toml`'da yok.
`api/elasticsearch_integration.py` `ImportError`ı yutup `HAS_ES = False`a
düşüyor, yani **ES arama yolu sessizce kapalı**.

**Bilinçli olarak DÜZELTİLMEDİ.** Kurmak `HAS_ES`i `True` yapar ve
`sync_document_to_es` her doc update'inde ES'e yazmaya başlar — bu bir davranış
değişikliğidir, altyapı görevinin kapsamı değil. Bulgu olarak §8'de duruyor;
`requirements.txt`'in başına da uyarı yazıldı.

---

## 4. T-032 — CI kapısı

Kaynak kriteri (`33-dogrulama-faz0-3.md` §5.2): *"CI: ruff + mypy + pytest +
pre-commit çalışıyor"*. Doğrulandı, hiçbiri yoktu: 5 workflow'un tamamı
release/deploy, `[tool.mypy]` bloğu yok, `.pre-commit-config.yaml` yok.

### 4.1 Ölçülmüş taban — niye "tüm depoda ruff" kurulamadı

```
ruff check .                     → 1401 hata
ruff format --check .            → 326 dosya yeniden biçimlenirdi
ruff check tradehub_core/media/pipeline --statistics:
    715 UP006  (typing.Dict → dict)
    282 UP045  (Optional[X] → X | None)
    153 UP035  (deprecated-import)
     42 UP037  (quoted-annotation)
    → 1192 / 1210'u kozmetik tip modernizasyonu
```

Tüm depoyu bloklayıcı yapmak CI'ı ilk gün kırmızı bırakırdı ve kırmızı kapı
kapı değildir. Ayrıca 1192 düzeltmenin tamamı `media/**` altında — bu oturumda
başka bir ajanın alanı.

**Seçilen tasarım:** kapı **değişen dosyalara** kurulu. PR'da dokunulan `.py`
temiz olmak zorunda; dokunulmamış eski kod kimseyi durdurmaz. Tüm depo tabanı
her koşumda job özetine basılır (bloklamaz) ki sayı görünür kalsın.

### 4.2 mypy

`[tool.mypy]` `pyproject.toml`'a eklendi. Ölçülmüş taban
(mypy 1.18.2, `--ignore-missing-imports`):

| Kapsam | Hata |
|---|---|
| `media/pipeline/contracts` | **0** |
| `media/pipeline/policy` | 2 |
| `media/pipeline/core` | 38 |
| `media/pipeline` (tümü) | 107 |

Bloklayıcı kapı yalnız `contracts/` — T-031'in donmuş 5 Protocol'ü. Orada
`disallow_untyped_defs` + `disallow_incomplete_defs` + `no_implicit_optional`
açık ve **0 hata** (doğrulandı: `Success: no issues found in 8 source files`).
Böylece T-031'in *"arayüz değişikliği CI'da kırmızı verir"* kriterinin mypy
ayağı da kuruldu.

`warn_return_any` bilinçli KAPALI: açıkken tek bir hata veriyor
(`contracts/signatures.py:76`), düzeltmesi `media/**` dosyasına dokunmayı
gerektiriyor. Gerekçe pyproject'te yorum olarak yazılı.

### 4.3 Testler — ve kesif sırasında bulunan bir tuzak

CI'daki test job'ı modül listesini **sabit tutmaz, keşfeder**. Ama keşfin
**her modül için ayrı süreçte** yapılması şart:

> Bu depodaki birçok test modülü import anında `sys.modules`'e **sahte bir
> `frappe`** enjekte ediyor. Hepsini tek bir Python sürecinde import edersen
> ilk modülün sahtesi sonrakileri de "frappe varmış" gibi gösterir. İlk
> denememde keşif **95 modül** buldu; `unittest` her modülü kendi sürecinde
> yüklediği için bunların **13'ü** `No module named 'frappe'` ile düştü.
> Ayrı süreçte ölçünce gerçek sayı çıktı: **97 modül tek başına import
> edilebiliyor, 40 modül çalışan bir Frappe sitesi istiyor.**

CI script'i bu yüzden her modülü `python -c "import <modul>"` ile temiz bir alt
süreçte dener. Ayrıca `MIN_MODUL` tabanı var (bugün 90): keşfedilen sayı
tabanın altına inerse job kırmızı olur — toplu import kırılması sessizce
"0 test koştu"ya dönüşmesin diye.

**97 modülün 5'i frappe'siz ortamda gerçekten düşüyor** ve hiçbiri ortam
eksiğinden değil; hepsi test dosyalarının **kendi** sorunu. CI'da adlarıyla ve
gerekçeleriyle hariç tutuldular (`BILINEN` sözlüğü); listeye giren her satır
ölçülmüş bir gözlemdir, biri düzelince silinmeli:

| Modül | Ölçülen sebep |
|---|---|
| `test_address_validators` | 2 failure — test, `api/buyer.py` ve `seller.py` içinde **birebir kaynak metni** arıyor (`'phone_to_save = intl_digits[len(prefix_digits):]'`); o satır kodda değişmiş. **Bayat assertion** |
| `test_kyc_verification` | 15 error — dosyanın kendi frappe sahtesi eskimiş: `frappe.log_error(defer_insert=…)` argümanını kabul etmiyor |
| `test_store_subscription_isolation` | 4 error — `setUp` içindeki lambda yanlış arite: *"takes 1 positional argument but 2 were given"* |
| `test_tenant_isolation` | 1 error — kısmi frappe sahtesi: `frappe.utils.now_datetime` ve `frappe.get_traceback` yok |
| `test_tuple_sync` | ⚠️ **ASILI KALIYOR** — 1800 sn zaman aşımına uğradı (2 test yazıp durdu). Frappe'siz ortamda zaman aşımsız bir bekleme var. Hariç tutulmasaydı CI bütçesinin tamamını yakardı |

Geriye kalan **92 modül** frappe'siz ortamda yeşil (ölçüldü).

MinIO GitHub Actions `services:` bloğu olarak ayağa kaldırılıyor, böylece
T-050/051/055'in 91 testi CI'da da gerçek bir S3 uçnoktasına karşı koşuyor.
MinIO ulaşılamazsa testler **skip** olur, düşmez (dosyanın kendi tasarımı).

### 4.4 pre-commit

`.pre-commit-config.yaml`: `pre-commit-hooks` (merge conflict, large files,
yaml/toml/json, EOF, trailing whitespace) + `ruff-check --fix` + `ruff-format`
+ `mypy` (yalnız `contracts/`).

Yerel doğrulama (depo kopyası üzerinde, `python:3.12-slim` konteynerinde):

```
pre-commit validate-config .pre-commit-config.yaml    → çıktı yok (geçerli)
pre-commit run --files pyproject.toml requirements.txt \
                      tradehub_core/media/pipeline/contracts/storage.py
    check for merge conflicts ....... Passed
    check toml ...................... Passed
    fix end of files ................ Passed
    trim trailing whitespace ........ Passed
    ruff check ...................... Failed (10 hata, 10'u otomatik düzeltildi)
    ruff format ..................... Passed
    mypy ............................ Passed
```

`ruff check`in `storage.py`de 10 hata bulması **beklenen** — §4.1'deki
UP006/UP045 tabanı. Kapının anlamı bu: o dosyaya dokunan kişi onu temizler.

### 4.5 ⚠️ ÖLÇÜLMEDİ

**`ci.yml` GitHub Actions üzerinde koşmadı.** Bu oturumda hiçbir şey
push/commit edilmedi. Doğrulananlar:

- YAML sözdizimi (`yaml.safe_load` → 4 job) ✔
- Gömülü Python'un derlenmesi ve heredoc girintisinin doğruluğu ✔
- `pre-commit` konfigürasyonu ve hook id'leri (gerçek koşumla) ✔
- **Test job'ının gömülü script'i, `ci.yml`den çıkarılıp birebir koşturuldu**
  — `python:3.12-slim` + apt ffmpeg/tesseract + aynı pip listesi + compose
  ağındaki gerçek MinIO'ya bağlı, aynı `MEDIA_ENGINE_S3_*` değişkenleriyle ✔

```
kesfedilen: 97  frappe-gerektiren: 40  diger-import-hatasi: 0
SKIP  test_address_validators           (bilinen dusen)
SKIP  test_kyc_verification             (bilinen dusen)
SKIP  test_store_subscription_isolation (bilinen dusen)
SKIP  test_tenant_isolation             (bilinen dusen)
SKIP  test_tuple_sync                   (bilinen dusen — asili kaliyor)
...
OK    test_storage_adapters_minio       OK          ← skip YOK, 91 test gerçek MinIO'ya karşı
OK    test_video_transcode              OK
HEPSI YESIL — kosan 92 modul, bilinen dusen 5, frappe-gerektiren 40
CIKIS_KODU=0
```

Doğrulanmayan: gerçek runner davranışı — `actions/setup-python`, MinIO service
container'ının sağlık kontrolü, `pre-commit/action@v3.0.1`'in `--from-ref`
argümanları, `github.event.before` fallback'i. **İlk PR'da görülecek.**

Ayrıca: runner'ın apt ffmpeg'i **libvmaf'sız**dır. Video testleri CI'da
SSIM/PSNR yoluna düşer; VMAF yalnız üretim imajında ölçülür.

---

## 5. Kurulum sonrası ölçümler (rule 5 — "gerçekten çalıştıklarını ölç")

Hepsi **yeniden derlenmiş imajdan** ve `docker compose up -d` sonrası
**çalışan `istoc-dev-backend-1`** içinden:

```
libvmaf filtre sayisi: 1
ffmpeg: ffmpeg version n8.1.2-44-g7c533d0f86-20260818
/usr/bin/ffmpeg (apt, geri dönüş): ffmpeg version 5.1.9-0+deb12u1
tesseract: tesseract 5.3.0        diller: eng osd tur
boto3: 1.34.162
pytesseract -> tesseract: 5.3.0
vmaf_available(): True
```

**Uçtan uca VMAF, üretim kodunun kendi fonksiyonuyla:**

```python
from tradehub_core.media.pipeline.video import transcode as t
t.vmaf_available()                                  # True
t.vmaf_min()                                        # 93.0
t.measure_quality("/tmp/ref.mp4", "/tmp/dist.webm")
# {'measured': True, 'metric': 'vmaf', 'vmaf': 80.831408}
```

Bu, T-072/T-075'i tıkayan asıl maddeyi kapatıyor: ölçüm artık dış imajla
(`linuxserver/ffmpeg`) değil, **üretim hattının kendisiyle** yapılabiliyor.

**OCR, `calibrate_content_rules.py`nin kendi bayrağıyla:**

```
HAS_TESSERACT: True
tesseract sürümü: 5.3.0
OCR metni: 'INDIRIM 0% KAMPANYA'   (kaynak: "INDIRIM 50% KAMPANYA")
```

("50" → "0" farkı PIL'in varsayılan bitmap fontundan; araç kusuru değil.
T-025'in gerçek kalibrasyonu `fixtures/` görselleriyle yapılmalı — o
`media/**` alanı, bu oturumda bana kapalı.)

**Testler — yeniden derlenmiş imajda:**

| Modül | Sonuç |
|---|---|
| `test_storage_adapters_minio` | **91 test OK** (gerçek MinIO; skip YOK) |
| `test_video_transcode` | **109 test OK** (299 s) |
| `test_render_regression` | 32 test OK (1 skip) |
| `test_contracts` | 75 OK |
| `test_policy_engine` | 38 OK |
| `test_state_machine` | 47 OK |
| `test_storage_adapters` | 137 OK |
| `test_policy_dpi` | 19 OK (1 expected failure) |
| `test_dedup` | 57 OK |
| `test_image_probe` / `test_image_normalize` / `test_image_classify` | 16 / 25 / 32 OK |
| `test_enforcement` | 6 OK |
| `test_crop_geometry` | 3652 örnek, en büyük sapma 2.07e-16; 584 vektör, 0.0 px |

**ffmpeg 5.1.9 → 8.1.2 yükseltmesi hiçbir testi düşürmedi** — bu yükseltmenin
tek gerekçesi libvmaf'tı ve bedeli ölçüldü: sıfır.

---

## 6. Dağıtım — bugünkü ortam tuzağı bir kez daha yaşandı ve doğrulandı

```bash
docker compose up -d --no-build backend frappe-frontend queue-short queue-long scheduler websocket
curl -o /dev/null -w '%{http_code}' http://istoc.localhost/files/Bere-1.png   # → 502
docker compose restart storefront gateway admin-panel
curl ... /files/Bere-1.png    # → 200
curl ... /                    # → 200
curl ... :8001/api/method/ping # → 200
```

Yenilenen backend servisleri yeni IP aldı; gateway/storefront eski IP'yi
tutuyordu → **502**, üstelik `docker compose ps` hepsini "Up" gösteriyordu.
`restart storefront gateway` ile düzeldi. Bu tuzak `gateway.conf` içinde
`resolver` + değişken `proxy_pass` ile zaten hafifletilmiş ama **storefront ve
admin-panel nginx'lerinde aynı önlem yok** — §8'de bulgu olarak duruyor.

**Rule 4 kontrolü — `Media Engine Settings` bayrakları:**

```json
{"media_pipeline_enabled": 0, "rendition_on_upload": 0, "manifest_api_enabled": 0,
 "max_renditions_per_asset": 40}
```

Ölçüm öncesi/sonrası **0'da kaldı**. Hiçbir bayrak açılmadı.

---

## 7. T-052 — bu şeritte NE YAPILMADI ve niye

Kalan iki eksik, ikisi de bu şeridin dışında kaldı:

1. **`cdn_purge_api_url` okuyucusu yazılmadı.** Alanı okuyacak kod
   `media/pipeline/delivery/` ya da `Media Storage Settings` doctype'ının
   `.py`si olurdu; ikisi de bu oturumda **yasak listede** (`media/**`,
   DocType'lar). Beş ajan paralel çalışırken oraya dokunmak çakışma üretirdi.
   → T-052'nin 3. kriteri **hâlâ açık**, kapanmadı.

2. **Prod eşdeğeri uygulanmadı.** `docker/nginx/gateway.conf` prod
   host-nginx'inin *local taklidi*; prod sunucusuna erişimim yok ve prod'a
   uygulamak bir deploy eylemi. Ölçebildiğim tek şey local gateway'di.

**Yapılabilen kısım:** `docker/`nin versiyonlanmadığı gerçeği (§0) T-052 için
somut bir risk — 91 satırlık cache politikası tek kopya, git dışında,
kaybolabilir. `docker/README.md`ye kalıcı bir uyarı ve araç tablosu yazıldı;
bu rapor da versiyonlanan tarafta duruyor.

---

## 8. Açık bulgular (bu şeritte kapatılmadı)

| # | Bulgu | Kanıt | Kime |
|---|---|---|---|
| F-1 | `requirements.txt` imaj tarifinde **hiç okunmuyor**; gerçek kaynak `pyproject.toml`'dur | `backend.Dockerfile` yalnız `pip install -e` koşuyor | Altyapı |
| F-2 | **`elasticsearch` kurulu değil** → `HAS_ES=False`, ES arama yolu sessizce kapalı | `pip list \| grep elasticsearch` → boş | Backend/arama sahibi |
| F-3 | `cdn_purge_api_url` / `cdn_purge_token` okuyucusuz | repo geneli grep → yalnız rapor metni + DocType JSON | T-052 sahibi |
| F-4 | **`docker/` versiyonlanmıyor** — Dockerfile, compose, gateway.conf git dışında | `git status` → repo değil | Proje sahibi |
| F-5 | storefront/admin-panel nginx'lerinde `resolver` + değişken `proxy_pass` yok → recreate sonrası 502 elle `restart` istiyor | §6'daki ölçüm | Altyapı (sonraki tur) |
| F-6 | İmaj **7.32 GB → 7.69 GB** (+370 MB): statik ffmpeg+ffprobe ~204 MB, tesseract+dil paketleri ~90 MB, kalanı apt/katman yükü | `docker images` | Kabul edilebilir; not |
| F-7 | `contracts/signatures.py:76` `Any` döndürüyor; `warn_return_any` bu yüzden kapalı | mypy çıktısı | `media/**` sahibi |
| F-8 | 5 yeni patch imaja girdi, **bir sonraki `bench migrate`de koşacak** | §2 | Şerit A |
| F-9 | **`test_tuple_sync` asılı kalıyor** (>1800 sn) — frappe'siz ortamda zaman aşımsız bekleme | §4.3 | Test sahibi |
| F-10 | `test_address_validators` **bayat**: kodda artık olmayan bir kaynak satırını arıyor | §4.3 | Backend |
| F-11 | 3 modülün kendi frappe sahtesi eskimiş (`log_error(defer_insert)`, `now_datetime`, lambda aritesi) — yalnız `bench run-tests` altında geçerler | §4.3 | Test sahibi |

---

## Ek A — yeniden üretme komutları

```bash
# Araçlar
docker exec istoc-dev-backend-1 ffmpeg -hide_banner -filters | grep -c libvmaf   # 1
docker exec istoc-dev-backend-1 tesseract --version | head -1                    # 5.3.0
docker exec istoc-dev-backend-1 tesseract --list-langs                           # eng osd tur
docker exec istoc-dev-backend-1 /home/frappe/frappe-bench/env/bin/python \
    -c "import boto3, pytesseract; print(boto3.__version__, pytesseract.get_tesseract_version())"

# VMAF, üretim kodunun kendi fonksiyonuyla
docker exec istoc-dev-backend-1 bash -lc 'cd /home/frappe/frappe-bench/apps/tradehub_core && \
  ../../env/bin/python -c "
from tradehub_core.media.pipeline.video import transcode as t
print(t.vmaf_available(), t.vmaf_min())"'

# 91 MinIO testi (gerçek MinIO'ya karşı — skip görürsen minio servisi kapalıdır)
docker exec istoc-dev-backend-1 bash -lc 'cd /home/frappe/frappe-bench/apps/tradehub_core && \
  ../../env/bin/python -m unittest tradehub_core.tests.test_storage_adapters_minio'

# Lint/tip tabanı (host)
python3 -m ruff check --statistics .
python3 -m ruff format --check . | tail -1
docker run --rm -v "$PWD":/src -w /src python:3.12-slim \
  bash -c 'pip install -q mypy==1.18.2 && mypy tradehub_core/media/pipeline/contracts'

# İmajı yeniden derle (araç katmanı ~1 dk; bench build cache'ten gelir)
cd docker && docker compose build backend

# Dağıt — ARDINDAN gateway/storefront restart ŞART (yoksa 502)
docker compose up -d --no-build backend frappe-frontend queue-short queue-long scheduler websocket
docker compose restart storefront gateway admin-panel
curl -s -o /dev/null -w '%{http_code}\n' http://istoc.localhost/files/Bere-1.png   # 200 bekleniyor
```

## Ek B — bu oturumda DEĞİŞTİRİLMEYENLER

- `hooks.py`, `permissions.py`, `patches.txt`, `patches/**` — açılmadı
- `media/**`, `api/**`, `admin-panel/**`, hiçbir DocType JSON'u — açılmadı
- `bench migrate` **koşulmadı**
- `Media Engine Settings` bayrakları okundu, **0'da bırakıldı**
- Hiçbir git commit / push yapılmadı

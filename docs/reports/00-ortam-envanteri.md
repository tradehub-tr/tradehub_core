# T-000 — Depo ve Ortam Envanteri

**Medya motoru çalışması · Faz 0 · 2026-08-17**
Branch: `medya-motoru-faz0-faz2` · Worktree: `/Users/ahmet/Desktop/istoc-medya-wt`

Bu belge medya motorunun üzerinde çalışacağı ortamı **ölçerek** kayda geçirir.
Tasarım yapmaz, öneri vermez — yalnız "bugün ne var" sorusunu cevaplar.

---

## 0. Ölçüm yöntemi ve güven seviyesi

Her satırın yanında kaynağı var. Üç güven seviyesi kullanılıyor:

| İşaret | Anlamı |
|---|---|
| **[Ö]** | **Ölçüldü** — komut çalıştırıldı, çıktısı bu belgeye alındı. Komut aşağıda. |
| **[K]** | **Kaynakta yazılı** — dosya:satır olarak okundu, çalıştırılmadı. |
| **[?]** | **Bilinemedi** — nedeni ve nasıl öğrenileceği §10'da. |

### Ölçüm ortamı — ÖNEMLİ UYARI

Görev tanımında "Docker kapalı" varsayılmıştı; **kapalı değildi**. `docker ps`
çıktısında `istoc-dev-*` yığınının 12 konteyneri `Up` durumdaydı (db, redis-cache,
redis-queue, backend, websocket, scheduler, queue-short, queue-long,
frappe-frontend, storefront, admin-panel, gateway). Bu yüzden aşağıdaki [Ö]
işaretli değerler **yerel geliştirme yığınından** (`istoc-dev-backend-1`,
`istoc-dev-frappe-frontend-1`) alınmıştır.

**Yerel yığın üretim DEĞİLDİR.** Farklar bilinen ve önemli:

| Boyut | Yerel dev [Ö] | Üretim |
|---|---|---|
| İmaj kaynağı | `docker/backend.Dockerfile` (bizim yazdığımız) | Frappe Cloud / Press'in kendi build'i |
| Mimari | `arm64` (`docker image inspect istoc/tradehub-backend:v15 --format '{{.Architecture}}'`) | [?] büyük olasılıkla `amd64` |
| ffmpeg | Kurulu (bkz. §3) | [?] Press imajında ffmpeg kurulu olduğuna dair **hiçbir kanıt yok** — §10-A |
| Veri | `istoc.cronbi.com` yedeğinden türetilmiş, tarihi bilinmiyor | Canlı |

Üretim veritabanına ve canlı siteye erişim yok. Üretime ait her satır ya
`.github/workflows/deploy.yml`'den okunmuştur ([K]) ya da §10'a düşmüştür.

### Kullanılan komutlar (yeniden üretilebilirlik için)

```bash
docker exec istoc-dev-backend-1 bash -lc 'python3 --version; cat sites/apps.txt'
docker exec istoc-dev-backend-1 bash -lc 'for a in $(cat sites/apps.txt); do \
  printf "%s\t" "$a"; env/bin/python -c "import $a; print($a.__version__)"; done'
docker exec istoc-dev-backend-1 bash -lc 'env/bin/pip show Pillow'
docker exec istoc-dev-backend-1 bash -lc 'env/bin/python -c "from PIL import features; features.pilinfo()"'
docker exec istoc-dev-backend-1 bash -lc 'ffmpeg -version; ffprobe -version'
docker exec istoc-dev-backend-1 bash -lc 'vips --version; ldconfig -p | grep -i vips'
docker exec istoc-dev-backend-1 bash -lc 'env/bin/python -c "import pyvips"'
docker exec istoc-dev-backend-1 bash -lc 'cat sites/common_site_config.json; cat sites/istoc.localhost/site_config.json'
docker exec istoc-dev-backend-1 bash -lc 'bench --site istoc.localhost execute frappe.client.get_value \
  --kwargs "{\"doctype\":\"System Settings\",\"filters\":{},\"fieldname\":\"max_file_size\"}"'
docker exec istoc-dev-frappe-frontend-1 bash -lc 'grep -n client_max_body_size /etc/nginx/conf.d/frappe.conf'
docker exec istoc-dev-backend-1 bash -lc 'du -sh sites/istoc.localhost/public/files; \
  find sites/istoc.localhost/public/files -type f | wc -l'
```

---

## 1. Çalışma zamanı — Frappe / ERPNext / Python

| Bileşen | Değer | Kaynak |
|---|---|---|
| Python (bench venv) | **3.11.6** (`main, Nov 29 2023`, GCC 12.2.0) | [Ö] `env/bin/python --version` |
| Python (asgari, bildirilen) | `>=3.10` | [K] `pyproject.toml:5` |
| Frappe | **15.116.1** | [Ö] `import frappe; frappe.__version__` |
| Frappe (bildirilen aralık) | `>=15.0.0,<16.0.0` | [K] `pyproject.toml:19` |
| ERPNext | **15.118.3** | [Ö] `import erpnext; erpnext.__version__` |
| ERPNext (bildirilen aralık) | `>=15.0.0,<16.0.0` | [K] `pyproject.toml:20` |
| tradehub_core | **1.13.1a18** | [Ö] `import tradehub_core; __version__` |
| Base imaj | `frappe/erpnext:v15` (Debian 12 "bookworm" tabanlı) | [K] `docker/backend.Dockerfile:4` · Debian sürümü [Ö] ffmpeg paket etiketi `0+deb12u1` |
| Build backend | `flit_core >=3.4,<4` | [K] `pyproject.toml:12` |
| Ruff hedefi | `py310`, line-length 110, tab indent | [K] `pyproject.toml:23-24,56` |

**Not:** Frappe 15.116.1 ile ERPNext 15.118.3 arasındaki minor fark normaldir;
ikisi bağımsız yayınlanır. `pyproject.toml` yalnız majör aralığı sabitliyor —
**yama sürümü pinli değil**. Yerel imaj ile Frappe Cloud bench'inin aynı yama
sürümünde olduğunun garantisi yok (§10-B).

### Python bağımlılıkları (tradehub_core'un kendi beyanı)

| Paket | Kısıt | Kaynak |
|---|---|---|
| `defusedxml` | `>=0.7` | [K] `pyproject.toml:7`, `requirements.txt:2` |
| `scikit-learn` | `>=1.3` | [K] `pyproject.toml:8`, `requirements.txt:3` |

`requirements.txt:4` notu: *"openpyxl Frappe ile gelir; explicit dependency yok"*.
**Pillow da aynı durumda — `tradehub_core` Pillow'u kendi bağımlılığı olarak
BEYAN ETMİYOR**, Frappe'nin bağımlılığı olarak geliyor (bkz. §3, risk notu).

---

## 2. Kurulu app'ler

`sites/apps.txt` içeriği [Ö] — kurulum sırasıyla:

| # | App | Sürüm [Ö] | Nasıl geliyor | Pin kaynağı |
|---|---|---|---|---|
| 1 | `frappe` | 15.116.1 | base imaj | [K] `backend.Dockerfile:4` (`frappe/erpnext:v15` etiketi — **yama pinli değil**) |
| 2 | `erpnext` | 15.118.3 | base imaj | [K] aynı |
| 3 | `tradehub_core` | 1.13.1a18 | `COPY` + editable pip | [K] `backend.Dockerfile:69,78` |
| 4 | `crm` | 1.56.4 | `bench get-app --branch v1.56.4` | [K] `backend.Dockerfile:54,62` |
| 5 | `helpdesk` | 1.22.1 | `bench get-app --branch v1.22.1` | [K] `backend.Dockerfile:55,63` |
| 6 | `telephony` | 0.0.1 | `bench get-app --branch develop` | [K] `backend.Dockerfile:53,61` |

**telephony neden pinsiz:** Dockerfile:26-27 yorumu — *"telephony'nin yayınlanmış
tag'i yok, tek branch develop"*. Yani bu app **her yeniden build'de değişebilir**;
tekrarlanabilir build zinciri burada kırık.

**crm/helpdesk neden var:** Dockerfile:20-23 — üretim yedeği (`istoc.cronbi.com`)
`tabInstalled Application`'da bu üçünü listeliyor; kod olmadan restore edilen site
`ModuleNotFoundError` ile boot edemiyor. Yani **üretimde de kurulular**.

Medya açısından anlamı: `File` DocType'ına dokunan üç ek app var. `hooks.py`'deki
global `File` kancaları (`before_insert`, `after_insert`) bu app'lerin yüklediği
dosyalarda da çalışır — chat ekleri, ticket ekleri dahil.

---

## 3. Sistem kütüphaneleri — görsel/video işleme

| Kütüphane | Yerel dev | Kaynak / kanıt |
|---|---|---|
| **ffmpeg** | **VAR** — `5.1.9-0+deb12u1`, arm64, `--enable-libvpx --enable-libopus --enable-libwebp --enable-libaom --enable-libsvtav1 --enable-libx264 --enable-libx265 --enable-libdav1d` | [Ö] `ffmpeg -version` · kurulum [K] `backend.Dockerfile:15` |
| **ffprobe** | **VAR** — `5.1.9-0+deb12u1` (ffmpeg paketiyle birlikte) | [Ö] `ffprobe -version` |
| **libvips (C kütüphanesi)** | **YOK** — `vips: command not found`, `ldconfig -p \| grep -i vips` → boş | [Ö] |
| **pyvips (Python binding)** | **YOK** — `ModuleNotFoundError: No module named 'pyvips'` | [Ö] |
| **Pillow** | **VAR** — `12.2.0` | [Ö] `env/bin/pip show Pillow` |
| **libimagequant** | **YOK** — `*** LIBIMAGEQUANT support not installed` | [Ö] `features.pilinfo()` |
| **HEIF/HEIC dekoder** | **YOK** — `pillow-heif` kurulu değil, `features.check("heif")` → `Unknown feature` | [Ö] |
| **Tkinter** | YOK (`libtk8.6.so` bulunamıyor) — medya için önemsiz | [Ö] |

### Pillow 12.2.0 içindeki kodek matrisi [Ö]

`features.pilinfo()` çıktısı, tam liste:

| Yetenek | Durum | Yüklü sürüm |
|---|---|---|
| PIL CORE | ✅ | 12.2.0 için derlenmiş |
| **WEBP** | ✅ | libwebp **1.6.0** |
| **AVIF** | ✅ | **1.4.1** |
| **JPEG** | ✅ | libjpeg-turbo **3.1.4.1** |
| **TIFF** | ✅ | libtiff **4.7.1** |
| **ZLIB (PNG)** | ✅ | 1.2.13, zlib-ng 2.3.3 için derlenmiş |
| JPEG2000 | ✅ | OpenJPEG 2.5.4 |
| LITTLECMS2 (ICC) | ✅ | 2.18 |
| FREETYPE2 | ✅ | 2.14.3 |
| RAQM (bidi metin) | ✅ | 0.10.3 / fribidi 1.0.8 / harfbuzz 13.2.1 |
| LIBIMAGEQUANT | ❌ | — (PNG palet kuantizasyonu yok) |
| HEIF | ❌ | — |
| TKINTER | ❌ | — |

### Bu ölçümlerden çıkan üç somut boşluk

**(a) AVIF Pillow'da VAR ama motorda YOK.**
`media/engine.py:21` → `SUPPORTED_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "TIFF"})`.
AVIF `FORMAT_EXTENSIONS`'ta tanımlı (`engine.py:33`) ama `SUPPORTED_FORMATS`'ta
olmadığı için `optimize()` onu `unsupported_format` ile reddediyor
(`engine.py:109-110`). Yani ortamda hazır duran bir kodek kullanılmıyor.

**(b) `.heic` kabul ediliyor ama açılamıyor.**
`media/upload_policy.py:60` `.heic`'i `KIND_IMAGE` olarak izin listesine alıyor.
Pillow'da HEIF desteği yok [Ö]. Sonuç: iPhone'dan gelen bir `.heic` politika
kapısını GEÇER, sonra `engine.probe()` `readable=False` döner (`engine.py:92-93`)
ve `engine.to_webp()` (`engine.py:163`, `Image.open`) **istisna fırlatır** —
`to_webp` `optimize()` gibi hata yutmuyor, ham `PIL` çağrısı yapıyor.
Sahada ne olduğu ölçülmedi → §10-C.

**(c) libvips yok, ama kod bunu bekliyor olabilir.**
`engine.py:5` docstring'i: *"Pillow yavaş kalırsa yalnız bu dosya pyvips'e
çevrilir"*. Bu bilinçli bir kaçış kapısı, bugün kullanılmıyor. Depoda `pyvips`
geçen tek satır bu yorum [Ö] (`grep -rn "pyvips\|libvips" --include='*.py'`).
libvips'e geçilecekse **imaja hem `libvips` hem `pyvips` eklenmesi gerekir** —
şu an ikisi de yok.

---

## 4. Görsel/video işleme için kullanılan Python kütüphanesi

### 4.1 Görsel — `media/engine.py`

Modülün tüm import'ları [K] (`engine.py:16-19` + gövde içi lazy import'lar):

```python
from __future__ import annotations
import io
from dataclasses import dataclass
# gövde içinde, fonksiyon başına:
from PIL import Image                 # engine.py:82  (probe)
from PIL import Image, ImageOps       # engine.py:102 (optimize)
from PIL import Image, ImageOps       # engine.py:161 (to_webp)
from PIL import Image                 # engine.py:187 (_verify)
```

**Tek görsel kütüphanesi: Pillow.** Başka hiçbir görsel bağımlılığı yok.

Kayda değer üç mimari karar (hepsi `engine.py` docstring'inde gerekçeli):

| Karar | Yer | Gerekçe (dosyadan) |
|---|---|---|
| `import frappe` YOK | `engine.py:3` | Site kurmadan test edilebilsin; pyvips'e geçiş üst katmanı etkilemesin |
| Import'lar fonksiyon içinde (lazy) | `engine.py:82,102,161,187` | Pillow yoksa `optimize()` `pillow_unavailable` döner, çökmez (`engine.py:103-104`) |
| Format KORUNUR (`optimize`) / koşulsuz WebP (`to_webp`) | `engine.py:8`, `engine.py:148-160` | `file_url` sabit kalsın; Safari/iOS'ta `canvas.toBlob('image/webp')` yok |

**TIFF sıkıştırma seçimi ölçümle yapılmış** — `engine.py:44-50` yorumu, 8 gerçek
dosya / 101,7 MB üzerinde: LZW → 19,2 MB (%81), **Deflate → 13,3 MB (%87, seçilen)**,
JPEG-in-TIFF → 4,0 MB (%96, kayıplı olduğu için elenmiş). Bu sayılar bizim
ölçümümüz değil, kodun kendi kayıtlı ölçümü.

### 4.2 Video — `media/transcode.py`

| Şey | Değer | Kaynak |
|---|---|---|
| Kütüphane | Python kütüphanesi YOK — `subprocess` ile harici `ffmpeg`/`ffprobe` | [K] `transcode.py:38` (`import subprocess`) |
| Hedef kodek | VP9 video / Opus ses, WebM konteyner | [K] `transcode.py:1` başlık |
| Hedef çözünürlük | `scale=min(1280,iw)` | [K] `transcode.py:239` yorumu |
| ffmpeg zaman aşımı | **1700 sn** | [K] `transcode.py:50` `_FFMPEG_TIMEOUT_SECONDS` |
| ffprobe zaman aşımı | **20 sn** | [K] `transcode.py:53` `_FFPROBE_TIMEOUT_SECONDS` |
| Transcode eşiği — genişlik | **1280 px** üstü | [K] `transcode.py:62` `NEEDS_TRANSCODE_MAX_WIDTH` |
| Transcode eşiği — bitrate | **2.500.000 bps (2,5 Mbps)** üstü | [K] `transcode.py:63` `NEEDS_TRANSCODE_MAX_BITRATE` |
| Kabul edilen video uzantıları | `.mp4 .webm .mov .m4v` | [K] `transcode.py:70` `VIDEO_EXTENSIONS` |
| ffmpeg yoksa davranış | `FileNotFoundError` yakalanıyor, worker çökmüyor, dosya `failed` damgalanıyor | [K] `transcode.py:30-32` |

**Yerel dev'deki ffmpeg 5.1.9 bu işi yapabiliyor:** `--enable-libvpx` (VP9) ve
`--enable-libopus` derleme bayrakları çıktıda var [Ö].

### 4.3 Pillow kullanan diğer modüller [Ö]

`grep -rln "from PIL\|import PIL" --include='*.py'` → 9 dosya:

| Dosya | Rol |
|---|---|
| `media/engine.py` | Ana motor |
| `bulk_import/image_matcher.py` | Toplu içe aktarmada görsel eşleştirme |
| `seo/og_image.py` | OG görseli üretimi |
| `tests/test_engine_webp.py`, `tests/test_media_pipeline_integration.py`, `tests/test_media_transcode.py`, `bulk_import/tests/test_bulk_import.py`, `bulk_import/tests/test_image_matcher.py`, `seo/tests/test_og_image.py` | Testler |

**Risk:** Pillow üç ayrı üretim modülünün sert bağımlılığı ama `pyproject.toml`'da
beyan edilmiyor (§1). Frappe bir gün Pillow'u bırakırsa üç modül birden düşer.

### 4.4 Medya kodunun büyüklüğü [Ö]

| Kapsam | Satır | Komut |
|---|---:|---|
| `tradehub_core/media/*.py` (27 dosya) | **8.200** | `wc -l media/*.py` |
| `tradehub_core/api/seller_media.py` | **494** | `wc -l` |
| Medya testleri (`tests/test_media*.py`, `test_engine*.py` — 8 dosya) | **2.581** | `wc -l` |
| `seo/og_image.py` + `bulk_import/image_matcher.py` | **512** | `wc -l` |
| **Toplam (backend, ölçülen)** | **11.787** | — |

Görev tanımındaki "21.430 satır medya kodu" rakamı **bu ölçümle uyuşmuyor**.
Aradaki fark büyük olasılıkla frontend medya kodunu (admin-panel
`src/lib/upload-ui/`, `stores/media.js`) içeriyor; o taraf bu görevin kapsamında
ölçülmedi. **Bu belgede kullanılan sayı 11.787'dir.**

---

## 5. Yükleme boyut limitleri — tam zincir

Bir dosya yüklenirken **beş ayrı tavan** var. Efektif limit her zaman en küçüğü.

| # | Katman | Değer | Bayt | Kaynak |
|---|---|---|---:|---|
| 1 | İstemci — admin panel genel yükleme | 5 MB | 5.242.880 | [K] `admin-panel/frontend/src/composables/useFileUpload.js:4` |
| 1b | İstemci — ImagePicker varsayılanı | 2 MB | 2.097.152 | [K] `admin-panel/frontend/src/lib/upload-ui/facades/ImagePicker.ts:147`, `components/upload/ImagePickerUpload.vue:18` |
| 1c | İstemci — SlotDropzone varsayılanı | 5 MB | 5.242.880 | [K] `admin-panel/frontend/src/lib/upload-ui/facades/SlotDropzone.ts:82,177` |
| 1d | İstemci — toplu içe aktarma (zip / diğer) | 200 MB / 25 MB | 209.715.200 / 26.214.400 | [K] `admin-panel/frontend/src/composables/useBulkImport.js:81` |
| 1e | İstemci — zengin metin editörü | 10 MB | 10.485.760 | [K] `admin-panel/frontend/src/components/common/RichTextEditor.vue:145` |
| 2 | nginx — gateway (dış kapı) | **50m** | 52.428.800 | [K] `docker/nginx/gateway.conf:24` ve `:44` |
| 3 | nginx — storefront | **50m** | 52.428.800 | [K] `docker/nginx/storefront.local.template:374` |
| 4 | nginx — frappe-frontend | **50m** | 52.428.800 | [K] `docker/docker-compose.yml:195` `CLIENT_MAX_BODY_SIZE: 50m` → [Ö] render edilmiş hali `/etc/nginx/conf.d/frappe.conf:83` |
| 5 | Frappe — `request.max_content_length` | `get_max_file_size()` | bkz. 5b | [Ö] `apps/frappe/frappe/app.py:198-200` |
| 5b | Frappe — `get_max_file_size()` | **25 MB** | **26.214.400** | [Ö] hesap aşağıda |
| 6 | tradehub_core — `MAX_BYTES[image]` | 25 MB | 26.214.400 | [K] `media/upload_policy.py:68` |
| 6b | tradehub_core — `MAX_BYTES[video]` | 200 MB | 209.715.200 | [K] `media/upload_policy.py:69` |
| 6c | tradehub_core — `MAX_BYTES[document]` | 50 MB | 52.428.800 | [K] `media/upload_policy.py:70` |
| 6d | tradehub_core — `MAX_BYTES[other]` | 50 MB | 52.428.800 | [K] `media/upload_policy.py:71` |
| 6e | tradehub_core — `MAX_BYTES_UNKNOWN` | 50 MB | 52.428.800 | [K] `media/upload_policy.py:76` |

### 5b — Frappe tavanının nasıl 25 MB olduğu [Ö]

Frappe v15 kaynağı (`apps/frappe/frappe/core/api/file.py:86-91`, konteynerden okundu):

```python
def get_max_file_size() -> int:
    return (
        cint(frappe.get_system_settings("max_file_size")) * 1024 * 1024
        or cint(frappe.conf.get("max_file_size"))
        or 25 * 1024 * 1024
    )
```

Ölçülen girdiler:

| Girdi | Değer | Ölçüm |
|---|---|---|
| System Settings → `max_file_size` | **`"0"`** | [Ö] `bench execute frappe.client.get_value ...` |
| `common_site_config.json` → `max_file_size` | **anahtar yok** | [Ö] tam içerik: `db_host, db_port, default_site, developer_mode, redis_cache, redis_queue, redis_socketio, server_script_enabled, socketio_port` |
| `sites/istoc.localhost/site_config.json` → `max_file_size` | **anahtar yok** | [Ö] tam içerik: `allow_tests, db_name, db_password, db_type, encryption_key, mute_emails` |

Üçü de boş → varsayılan devreye giriyor: **25 × 1024 × 1024 = 26.214.400 bayt.**

### 5c — Efektif limit: video için 200 MB İLAN EDİLİYOR, 25 MB UYGULANIYOR

`upload_policy.effective_max()` (`upload_policy.py:262-265`) iki tavanın küçüğünü alır:

```python
def effective_max(tur: str) -> int:
    bizim = MAX_BYTES.get(tur, MAX_BYTES_UNKNOWN)
    return min(bizim, platform_limit())
```

`platform_limit()` = `get_max_file_size()` = 26.214.400 [Ö]. Sonuç tablosu:

| Tür | `MAX_BYTES` | `platform_limit()` [Ö] | **Efektif** | Kayıp |
|---|---:|---:|---:|---|
| image | 26.214.400 | 26.214.400 | **26.214.400** | — |
| video | 209.715.200 | 26.214.400 | **26.214.400** | **-183.500.800 (%87,5)** |
| document | 52.428.800 | 26.214.400 | **26.214.400** | -26.214.400 (%50) |
| other | 52.428.800 | 26.214.400 | **26.214.400** | -26.214.400 (%50) |
| unknown | 52.428.800 | 26.214.400 | **26.214.400** | -26.214.400 (%50) |

**Bu bir sürpriz değil — kod bunu biliyor ve yazıyor.** `upload_policy.py:239-252`
docstring'i aynen: *"Video için gerçekten 200 MB isteniyorsa site ayarındaki
`max_file_size` yükseltilmeli"*. `docs/MEDYA-YUKLEME-SOZLESMESI.md §4` de aynı
yere işaret ediyor.

Yani **yerel dev'de video tavanı fiilen 25 MB'dır** [Ö]. Üretimde System Settings →
`max_file_size` farklı olabilir → §10-D.

### 5d — Parçalı yükleme (chunked) parametreleri

| Parametre | Değer | Bayt | Kaynak |
|---|---|---:|---|
| Tek atış eşiği (`SINGLE_SHOT_LIMIT`) | 8 MB | 8.388.608 | [K] `media/upload_policy.py:89` |
| Parça boyutu (`CHUNK_BYTES`) | 2 MB | 2.097.152 | [K] `media/chunked.py:43` |
| Azami parça sayısı (`MAX_CHUNKS`) | 256 | — | [K] `media/chunked.py:47` |
| **Teorik parçalı tavan** | 2 MB × 256 = **512 MB** | 536.870.912 | hesap: `CHUNK_BYTES * MAX_CHUNKS` |
| Oturum ömrü | 6 saat | — | [K] `docs/MEDYA-YUKLEME-SOZLESMESI.md §4` tablosu |

**Çelişki:** parçalı yol teorik olarak 512 MB'a kadar taşıyabiliyor, ama
`upload_finish` birleştirme sonrası politikayı uyguluyor
(`MEDYA-YUKLEME-SOZLESMESI.md §4`: *"Politika birleşimden SONRA uygulanır"*) ve
orada efektif tavan 25 MB [Ö]. 512 MB'lık bir dosya 256 parça yüklendikten
**sonra** reddedilir. Bu ölçülmedi, kod okunarak çıkarıldı → §10-E.

### 5e — Diğer ad/boyut sınırları

| Sınır | Değer | Kaynak |
|---|---|---|
| `File.file_name` azami uzunluk | 140 karakter (aşılırsa **kırpılır**, reddedilmez) | [K] `media/upload_policy.py:84`, `:288-291` |
| İzin verilen uzantılar — görsel | `.jpg .jpeg .png .webp .gif .bmp .tif .tiff .avif .heic` | [K] `media/upload_policy.py:60` |
| İzin verilen uzantılar — video | `.mp4 .webm .mov .m4v` | [K] `media/upload_policy.py:62` |
| İzin verilen uzantılar — belge | `.pdf .doc .docx .xls .xlsx` | [K] `media/upload_policy.py:63` |
| İzin verilen uzantılar — diğer | `.txt .csv .zip` | [K] `media/upload_policy.py:64` |
| Medya uçlarının dar kapısı | yalnız `image` + `video` + `.pdf` | [K] `media/upload_policy.py:79-80` |
| İçerik imzası (magic bytes) kontrolü | 11 imza + RIFF/WEBP + ftyp özel durumları | [K] `media/upload_policy.py:171-211` |
| Tehlikeli içerik markörleri | `<!doctype html`, `<html`, `<svg`, `<?xml`, `<script`, `<%`, `#!/` — ilk 512 baytta, baştaki boşluk/BOM atlanarak | [K] `media/upload_policy.py:187-195`, `:223` |

---

## 6. Worker / kuyruk yapılandırması

### 6.1 Konteyner düzeyi (yerel dev)

| Servis | Komut | Kuyruklar | Adet [Ö] |
|---|---|---|---:|
| `queue-short` | `bench worker --queue short,default` | short, default | 1 |
| `queue-long` | `bench worker --queue long,default,short` | long, default, short | 1 |
| `scheduler` | `bench schedule` | — | 1 |
| `websocket` | `node apps/frappe/socketio.js` | — | 1 |
| `backend` | (base imaj entrypoint — gunicorn) | — | 1 |

Kaynak: [K] `docker/docker-compose.yml:161,168,175,154` · adetler [Ö] `docker ps`
(`istoc-dev-queue-short-1`, `istoc-dev-queue-long-1`, `istoc-dev-scheduler-1` —
her birinden **birer tane**).

Redis: `redis-cache` ve `redis-queue` ayrı konteynerler, ikisi de `redis:7-alpine`
[K] `docker-compose.yml:50,56`. Kuyruk Redis'i `redis://redis-queue:6379`,
socketio da aynı örneği kullanıyor [Ö] `common_site_config.json`.

### 6.2 Kuyruk zaman aşımları (Frappe varsayılanları) [Ö]

`apps/frappe/frappe/utils/background_jobs.py:45-54` (konteynerden okundu):

| Kuyruk | Varsayılan timeout |
|---|---:|
| `short` | 300 sn |
| `default` | 300 sn |
| `long` | **1500 sn** |

### 6.3 Medyanın kuyruk kullanımı

| İş | Kuyruk | Timeout | Kaynak |
|---|---|---:|---|
| `media.transcode._run_transcode` | `long` | **1800 sn** (açıkça geçiliyor, varsayılan 1500'ü ezer) | [K] `media/transcode.py:156-161` |
| ffmpeg alt süreci | — | 1700 sn | [K] `media/transcode.py:50` |

**Tutarlı:** 1700 (ffmpeg) < 1800 (RQ job) — ffmpeg kendi durup `failed` yazsın,
RQ'nun sert kill'i devreye girmesin (`transcode.py:48-49` yorumu). `long`
kuyruğunun 1500'lük varsayılanı burada geçerli değil çünkü `timeout=1800`
açıkça veriliyor.

`enqueue_after_commit=True` [K] `transcode.py:161` — `File.insert()` henüz commit
olmadan worker'ın dosyayı aramasını engelliyor.

### 6.4 `hooks.py` — medyaya ait zamanlanmış işler

| Sıklık | İş | Satır | Ne yapıyor |
|---|---|---:|---|
| `daily` | `media.archive.purge_expired` | `hooks.py:131` | Optimizasyonda saklanan orijinallerin geri-alma penceresi dolunca silinmesi |
| `daily` | `media.trash.purge_expired` | `hooks.py:133` | Çöpteki görsellerin 30 günlük pencere dolunca kalıcı silinmesi |
| `daily` | `media.backup.run_scheduled` | `hooks.py:138` | Medya yedeği (dosyalar + `File` kayıtları), içerik-adresli |

`hooks.py:134-138` yorumu kendi ölçümünü taşıyor: *"günde ~12 MB değişim"*.
Bu bizim ölçümümüz değil.

**Medyanın `cron`, `hourly` veya `weekly_long` işi YOK** [Ö]
(`grep -n "media\." hooks.py` → yalnız 131, 133, 138 satırları scheduler bloğunda;
248-250 doc_events, 878 write_file).

### 6.5 `hooks.py` — `File` DocType kancaları

| Olay | Kanca | Satır |
|---|---|---:|
| `before_insert` | `utils.security.reject_unsafe_files` | `hooks.py:235` |
| `before_insert` | `entitlement.checks.check_media_storage_quota` | `hooks.py:236` |
| `after_insert` | `media.states.on_file_insert` | `hooks.py:248` |
| `after_insert` | `media.audit.on_file_insert` | `hooks.py:249` |
| `after_insert` | `media.transcode.maybe_transcode_on_insert` | `hooks.py:250` |
| — | `write_file = media.naming.write_file_hashed` | `hooks.py:878` |

`write_file` kancası içerik-adresli adlandırma yapıyor: disk adı
`sha256(içerik)[:32].<ext>` [K] `media/naming.py:1-5`. Bu **global** bir hook —
`File` üzerinden geçen her yükleme etkilenir.

### 6.6 Ölçülemeyen worker parametreleri

| Parametre | Durum |
|---|---|
| gunicorn worker sayısı | [?] `ps` konteynerde kurulu değil (`ps: command not found` [Ö]) → §10-F |
| RQ worker concurrency (`--burst`, fork sayısı) | [?] `bench worker` varsayılanı = tek süreç; konteyner başına 1 → §10-F |
| Frappe Cloud'daki worker sayısı/tipi | [?] → §10-F |

---

## 7. Depolama

| Şey | Değer | Kaynak |
|---|---|---|
| Depolama tipi | **Site diski** (yerel dosya sistemi) — obje depolama/S3 YOK | [Ö] `grep -rn "boto3\|s3\|S3\|cdn\|CDN" media/` → **0 eşleşme** |
| Public dizin | `sites/<site>/public/files` | Frappe standardı |
| Private dizin | `sites/<site>/private/files` | Frappe standardı |
| Dosya adlandırma | İçerik-adresli: `sha256(içerik)[:32].<ext>` | [K] `media/naming.py:3-4` |
| Docker'da kalıcılık | `sites` adlı named volume, **tüm** backend servislerinde paylaşımlı | [K] `docker-compose.yml:26,265` |

`docs/MEDYA-YUKLEME-SOZLESMESI.md §4` bunu açıkça yazıyor: *"Doğrudan obje
depolama (S3 imzalı URL) bugün uygulanamıyor — dosyalar site diskinde duruyor ve
depolama yapısı kararı TUR-130'un konusu."*

### Yerel dev disk kullanımı [Ö]

| Dizin | Boyut | Dosya sayısı |
|---|---:|---:|
| `sites/istoc.localhost/public/files` | **944 MB** | **4.016** |
| `sites/istoc.localhost/private/files` | **165 MB** | **325** |
| **Toplam** | **1,109 GB** | **4.341** |

**Bu sayı üretim değildir.** Yerel site `istoc.cronbi.com` yedeğinden türetilmiş
([K] `backend.Dockerfile:20-21`) ama yedeğin tarihi bilinmiyor ve o tarihten
sonra yerel geliştirme sırasında dosya eklenmiş olabilir. Karşılaştırma noktası:
`media/upload_policy.py:45` yorumu **"4003 public dosya"** ölçümünü kaydetmiş;
bugün 4.016 [Ö] — yani +13 dosya yerel olarak eklenmiş. Üretimin gerçek rakamı
için §10-G.

---

## 8. Üretim ortamı — Frappe Cloud (Press)

Tümü `.github/workflows/deploy.yml`'den okundu [K]; **hiçbiri doğrulanamadı**
(Press API'sine erişim yok).

| Alan | Değer | Satır |
|---|---|---:|
| Platform | Frappe Cloud / **Press** — self-hosted Press örneği | `deploy.yml:34` |
| Press API tabanı | `https://press.cronbi.com/api/method` | `deploy.yml:34` |
| Bench grubu | `bench-0001` | `deploy.yml:35` |
| App source kaydı | `SRC-tradehub_core-004` | `deploy.yml:36` |
| Uygulama sunucusu | `apphtznr.cronbi.com` (ad Hetzner'e işaret ediyor) | `deploy.yml:38` |
| Kimlik doğrulama | `token $FRAPPE_API_KEY:$FRAPPE_API_SECRET` (GitHub secrets) | `deploy.yml:25-26,39` |
| Deploy bekleme tavanı | 600 sn (bench), 300 sn (site update), 15 sn poll | `deploy.yml:41-43` |
| Workflow timeout | 15 dakika | `deploy.yml:11` |

### Site kademeleri [Ö `grep -o "[a-z0-9]*\.cronbi\.com" .github/workflows/`]

| Site | Kademe | Nasıl güncelleniyor |
|---|---|---|
| `alphaistoc.cronbi.com` | alpha | **GitHub Actions `deploy.yml`** — core build BURADA yapılır [K] `deploy.yml:31-32` |
| `betaistoc.cronbi.com` | beta | **Jenkins** pipeline (`schedule_update`, build yok) [K] `deploy.yml:32-33`, `beta-release.yml:3` |
| `rcistoc.cronbi.com` | rc | **Jenkins** [K] `rc-release.yml:3-5` |
| `istoc.cronbi.com` | **prod** | **Jenkins** (RC→PROD) [K] `prod-release.yml:3-5` |

Sürümleme zinciri [K] `alpha-release.yml:26-39`: `version-15` branch'ine her
push'ta `vX.Y.Z-alpha.N` tag'i üretilir → `deploy.yml` `workflow_run` ile tetiklenir
→ 60 sn bekler (`deploy.yml:19`) → Press API'sine `deploy_and_update` atar.

### Üretim imajı hakkında ne BİLMİYORUZ — kritik

`tradehub_core` deposunda **hiçbir Dockerfile veya `apps.json` yok** [Ö]
(`find . -maxdepth 3 \( -name "Dockerfile*" -o -name "apps.json" \)` → 0 sonuç).

Yani üretim imajını **Press kendi kalıbıyla** üretiyor ve içeriğini bu depodan
göremiyoruz. Sonuçları:

1. **ffmpeg üretimde kurulu mu bilinmiyor.** `docker/backend.Dockerfile:15`
   yalnız YEREL imajı besliyor; Press onu okumuyor. Press imajlarında ffmpeg
   standart olarak **yoktur**; eklemek için bench grubunun "Dependencies" /
   build-time apt paketleri ayarı gerekir.
   → ffmpeg yoksa `transcode.py` sessizce `failed` yazar (`transcode.py:30-32`
   FileNotFoundError'u yutuyor) — **video yükleme kırık görünmez, sessizce
   bozulur.** Bu, bu envanterin en yüksek riskli boşluğu. §10-A.
2. Python / Frappe yama sürümü [?] — §10-B.
3. Mimari (amd64 vs yereldeki arm64) [?] — §10-H.
4. Pillow sürümü ve kodek matrisi [?] — Press'in kendi wheel'i farklı derlenmiş
   olabilir (özellikle AVIF/WEBP). §10-I.

---

## 9. Özet — ortamın medya motoru açısından hâli

| Yetenek | Yerel dev [Ö] | Kod bunu kullanıyor mu? |
|---|---|---|
| JPEG oku/yaz | ✅ libjpeg-turbo 3.1.4.1 | ✅ `engine.py:120-123` |
| PNG oku/yaz | ✅ zlib-ng 2.3.3 | ✅ `engine.py:124-126` |
| WEBP oku/yaz | ✅ libwebp 1.6.0 | ✅ `engine.py:133`, `to_webp` |
| TIFF oku/yaz | ✅ libtiff 4.7.1 | ✅ `engine.py:127-131` (Deflate) |
| **AVIF oku/yaz** | ✅ **1.4.1** | ❌ **`SUPPORTED_FORMATS`'ta yok** (`engine.py:21`) |
| **HEIC oku** | ❌ | ⚠️ **izin listesinde var** (`upload_policy.py:60`) |
| PNG palet kuantizasyonu | ❌ libimagequant yok | — |
| ICC profil yönetimi | ✅ lcms2 2.18 | ✅ `engine.py:115,122,126,131,133` |
| VP9/Opus transcode | ✅ ffmpeg 5.1.9 (libvpx, libopus) | ✅ `transcode.py` |
| AV1 encode | ✅ ffmpeg'de var (`--enable-libsvtav1`, `--enable-librav1e`) | ❌ kullanılmıyor |
| libvips hızlandırma | ❌ yok | ❌ (yalnız yorumda kaçış kapısı olarak anılıyor) |
| Obje depolama / CDN | ❌ yok | ❌ (TUR-130'a ertelenmiş) |
| Video için >25 MB yükleme | ❌ efektif 25 MB | ⚠️ kod 200 MB ilan ediyor |

---

## 10. ÜRETİMDE DOĞRULANMALI

Aşağıdakiler ölçülemedi. Her madde için **çalıştırılacak tam komut** verildi.
Komutlar Frappe Cloud bench konsolundan (Press → Site → Console / SSH) ya da
Press API'sinden çalıştırılacak.

### 10-A. ffmpeg/ffprobe üretim imajında kurulu mu? **(en yüksek öncelik)**

Neden kritik: kurulu değilse video transcode sessizce başarısız oluyor
(`transcode.py:30-32` istisnayı yutuyor, kullanıcı hata görmüyor).

```bash
# Frappe Cloud → Sites → istoc.cronbi.com → SSH / bench console
which ffmpeg ffprobe; ffmpeg -version | head -3
ffmpeg -codecs 2>/dev/null | grep -E "libvpx-vp9|libopus"
```

Alternatif — SSH yoksa, Press bench konsolundan Python ile:

```python
import subprocess
print(subprocess.run(["ffmpeg","-version"], capture_output=True, text=True).stdout[:200])
```

Beklenen: `ffmpeg version 5.x` + `libvpx-vp9` ve `libopus` satırları.
**Çıkmazsa:** Press bench grubu → Dependencies → apt paketi olarak `ffmpeg`
eklenmeli, sonra yeni deploy.

Ek doğrulama — transcode gerçekten çalışmış mı (DB'den, ffmpeg'e dokunmadan):

```bash
bench --site istoc.cronbi.com execute frappe.db.sql \
  --kwargs "{'query':'select th_media_video_status, count(*) from tabFile where th_media_video_status is not null group by 1'}"
```

`failed` sayısı `ready`'den büyükse ffmpeg yok demektir.

### 10-B. Üretimdeki Frappe/ERPNext/Python yama sürümleri

```bash
bench --site istoc.cronbi.com version
python3 --version
bench --site istoc.cronbi.com execute frappe.utils.change_log.get_versions
```

Karşılaştırılacak yerel değerler [Ö]: frappe 15.116.1 · erpnext 15.118.3 ·
tradehub_core 1.13.1a18 · Python 3.11.6.

### 10-C. `.heic` yüklemeleri sahada ne oldu?

```bash
bench --site istoc.cronbi.com execute frappe.db.sql \
  --kwargs "{'query':\"select count(*) from tabFile where lower(file_name) like '%.heic'\"}"
bench --site istoc.cronbi.com execute frappe.db.sql \
  --kwargs "{'query':\"select count(*) from tabFile where lower(file_name) like '%.avif'\"}"
```

0 çıkarsa boşluk teoriktir. >0 çıkarsa `engine.to_webp` bu dosyalarda istisna
fırlatmış demektir — Error Log'a bakılmalı:

```bash
bench --site istoc.cronbi.com execute frappe.db.sql \
  --kwargs "{'query':\"select title, count(*) from tabError Log where title like '%upload%' or title like '%to_webp%' group by 1 order by 2 desc limit 20\"}"
```

### 10-D. Üretimdeki gerçek dosya boyutu tavanı

```bash
bench --site istoc.cronbi.com execute frappe.client.get_value \
  --kwargs "{'doctype':'System Settings','filters':{},'fieldname':'max_file_size'}"
bench --site istoc.cronbi.com execute frappe.core.api.file.get_max_file_size
bench --site istoc.cronbi.com execute tradehub_core.media.upload_policy.effective_max \
  --kwargs "{'tur':'video'}"
```

Yerel [Ö]: System Settings `"0"` → efektif 26.214.400 (25 MB) — video için de.
Üretimde `max_file_size` MB cinsinden bir sayı girilmişse tavan farklıdır.

Ayrıca nginx tarafı (Press'in kendi nginx'i, `docker/nginx/*` üretimde geçerli DEĞİL):

```bash
# Press sunucusunda
grep -rn client_max_body_size /home/frappe/frappe-bench/config/nginx.conf /etc/nginx/
```

Yerel [Ö/K]: her katmanda 50m.

### 10-E. Parçalı yüklemede 25 MB üstü dosya gerçekten 256. parçadan sonra mı reddediliyor?

Kod okunarak çıkarıldı, çalıştırılmadı. Doğrulama (staging'de, `alphaistoc`):

```bash
# 30 MB'lık bir test videosu ile
curl -X POST "https://alphaistoc.cronbi.com/api/method/tradehub_core.media.chunked.upload_begin" \
  -H "Authorization: token KEY:SECRET" \
  -d 'ad=test.mp4&toplam=31457280'
# dönen oturum kimliğiyle parçaları gönder, upload_finish'in hangi kodla
# reddettiğine bak: upload_too_large mı, daha erken bir kod mu
```

Ölçülecek: reddin **hangi adımda** geldiği (begin mi finish mi) ve
kaç MB'lık boşuna trafik harcandığı.

### 10-F. Üretimdeki worker/gunicorn sayısı ve kuyruk derinliği

```bash
bench doctor                      # kuyruk derinliği + worker durumu
bench --site istoc.cronbi.com execute frappe.utils.background_jobs.get_queue_list
# Press sunucusunda:
supervisorctl status | grep -E "worker|gunicorn"
cat /home/frappe/frappe-bench/config/supervisor.conf | grep -E "numprocs|--queue|workers"
```

Yerel [Ö]: `queue-short` ×1, `queue-long` ×1, `scheduler` ×1.
Video transcode `long` kuyruğunda 1800 sn tutuyor — üretimde `long` worker sayısı
1 ise **tek büyük video 30 dakika boyunca tüm long kuyruğunu bloklar**. Bu senaryo
ölçülmedi; worker sayısı öğrenildikten sonra değerlendirilmeli.

### 10-G. Üretimdeki gerçek medya hacmi

```bash
# Press sunucusunda
du -sh /home/frappe/frappe-bench/sites/istoc.cronbi.com/public/files
find /home/frappe/frappe-bench/sites/istoc.cronbi.com/public/files -type f | wc -l
du -sh /home/frappe/frappe-bench/sites/istoc.cronbi.com/private/files

# DB tarafından, dosya sistemine dokunmadan:
bench --site istoc.cronbi.com execute frappe.db.sql \
  --kwargs "{'query':'select is_private, count(*), sum(file_size), max(file_size) from tabFile group by 1'}"
# uzantı dağılımı:
bench --site istoc.cronbi.com execute frappe.db.sql \
  --kwargs "{'query':\"select lower(substring_index(file_name,'.',-1)) ext, count(*) c, sum(file_size) b from tabFile where file_name like '%.%' group by 1 order by c desc limit 25\"}"
```

Yerel [Ö] karşılaştırma noktası: public 944 MB / 4.016 dosya, private 165 MB / 325 dosya.

### 10-H. Üretim mimarisi (amd64 vs arm64)

```bash
uname -m
python3 -c "import platform; print(platform.machine(), platform.libc_ver())"
```

Yerel [Ö]: `arm64` / Debian 12 (glibc). Mimari farkı ffmpeg kodek setini ve
Pillow wheel'inin SIMD hızlandırmasını değiştirir — performans ölçümleri
yerelden üretime taşınamaz.

### 10-I. Üretimdeki Pillow sürümü ve kodek matrisi

```bash
bench --site istoc.cronbi.com execute frappe.utils.execute_in_shell \
  --kwargs "{'cmd':'env/bin/pip show Pillow'}"
# ya da bench console'da:
from PIL import features; features.pilinfo()
```

Yerel [Ö]: Pillow 12.2.0, WEBP 1.6.0, AVIF 1.4.1, JPEG-turbo 3.1.4.1, TIFF 4.7.1,
LCMS2 2.18; HEIF ve libimagequant YOK.
Üretimde AVIF/WEBP eksikse `engine.to_webp` **her yüklemede** düşer — bu, ffmpeg
kadar kritik ikinci nokta.

### 10-J. `telephony` app'inin üretimdeki commit'i

`develop` branch'inden pinsiz geliyor [K] `backend.Dockerfile:53,61`. Üretimdeki
gerçek commit:

```bash
cd /home/frappe/frappe-bench/apps/telephony && git rev-parse HEAD && git log -1 --date=short --format=%cd
```

Yerelde `0.0.1` [Ö] — ama bu `__version__` sabiti, commit'i temsil etmiyor.

---

## 11. Bu envanterden çıkan, kayda geçirilmesi gereken 6 boşluk

Öneri değil, **tespit**. Çözüm sonraki fazların işi.

| # | Boşluk | Kanıt | Risk |
|---|---|---|---|
| 1 | Üretimde ffmpeg olduğuna dair kanıt yok; yokluğunda video transcode **sessizce** başarısız | `find` → depoda prod Dockerfile yok [Ö]; `transcode.py:30-32` istisnayı yutuyor [K] | **Yüksek** |
| 2 | Video için ilan edilen 200 MB tavanı efektif 25 MB | `upload_policy.py:69` vs `platform_limit()`=26.214.400 [Ö] | Orta — kod bunu biliyor ve belgelemiş |
| 3 | `.heic` izin listesinde ama Pillow'da HEIF desteği yok | `upload_policy.py:60` [K] vs `features.check("heif")`→False [Ö] | Orta |
| 4 | AVIF ortamda hazır (Pillow 1.4.1) ama motorda kapalı | `engine.py:21` [K] vs pilinfo AVIF ok [Ö] | Düşük — kaçırılan fırsat |
| 5 | Pillow üç üretim modülünün sert bağımlılığı, `pyproject.toml`'da beyan edilmiyor | `pyproject.toml:6-9` [K] vs 3 üretim dosyası [Ö] | Düşük–orta |
| 6 | `telephony` pinsiz (`develop`), build tekrarlanabilir değil | `backend.Dockerfile:53` [K] | Düşük (medya dışı ama imajı etkiler) |

---

## 12. Kaynak dosya listesi

Bu belgenin dayandığı dosyalar, tam yolla:

**Okunanlar (yazılmadı, değiştirilmedi):**
- `/Users/ahmet/Desktop/istoc-medya-wt/pyproject.toml`
- `/Users/ahmet/Desktop/istoc-medya-wt/requirements.txt`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/hooks.py`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/engine.py`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/upload_policy.py`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/transcode.py`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/chunked.py`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/naming.py`
- `/Users/ahmet/Desktop/istoc-medya-wt/.github/workflows/deploy.yml`
- `/Users/ahmet/Desktop/istoc-medya-wt/.github/workflows/{alpha,beta,rc,prod}-release.yml`
- `/Users/ahmet/Desktop/istoc-medya-wt/docs/MEDYA-YUKLEME-SOZLESMESI.md`
- `/Users/ahmet/Desktop/istoc/docker/backend.Dockerfile`
- `/Users/ahmet/Desktop/istoc/docker/docker-compose.yml`
- `/Users/ahmet/Desktop/istoc/docker/nginx/gateway.conf`
- `/Users/ahmet/Desktop/istoc/docker/nginx/storefront.local.template`
- `/Users/ahmet/Desktop/istoc/admin-panel/frontend/src/composables/useFileUpload.js`
- `/Users/ahmet/Desktop/istoc/admin-panel/frontend/src/composables/useBulkImport.js`
- `/Users/ahmet/Desktop/istoc/admin-panel/frontend/src/lib/upload-ui/facades/{ImagePicker.ts,SlotDropzone.ts}`

**Konteynerden okunanlar (yerel dev, salt-oku):**
- `istoc-dev-backend-1:/home/frappe/frappe-bench/sites/apps.txt`
- `istoc-dev-backend-1:.../sites/common_site_config.json`
- `istoc-dev-backend-1:.../sites/istoc.localhost/site_config.json`
- `istoc-dev-backend-1:.../apps/frappe/frappe/core/api/file.py`
- `istoc-dev-backend-1:.../apps/frappe/frappe/app.py`
- `istoc-dev-backend-1:.../apps/frappe/frappe/utils/background_jobs.py`
- `istoc-dev-frappe-frontend-1:/etc/nginx/conf.d/frappe.conf`

**Yazılan tek dosya:** bu belge.

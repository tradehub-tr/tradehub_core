# 23 — T-051: S3 depolama adaptörleri, GERÇEK bir S3 uyumlu servise karşı

**Görev:** T-051 (Faz 5 · Depolama) · **Tarih:** 2026-08-19 · **Dal:** `ahmet`
**Ölçülen kod:** `tradehub_core/media/pipeline/storage/{__init__,local,s3,mirror,tiered}.py`
**Sözleşme:** `tradehub_core/media/pipeline/contracts/storage.py` — `StorageAdapter` Protocol
**Tetikleyen kayıt:** `docs/reports/14-nihai-denetim.md` — *T-051 KISMİ: kod yazılmış, gerçek ölçüm yok*
**Ölçüm ortamı:** MinIO (RELEASE, `minio/minio:latest`), `istoc-dev` compose ağı, boto3 1.34.162

> **Bu belge `storage/` altındaki hiçbir `.py` dosyasına, `api/`'ye, `media/`
> altındaki diğer modüllere, DocType/politika JSON'larına ya da
> `docs/standards/`'a DOKUNMADI.** Adaptörler değiştirilmeden ölçüldü.
> Bulunan 6 kusurun hiçbiri koşumu ENGELLEMEDİ, bu yüzden hiçbiri
> düzeltilmedi — hepsi §6'da kanıtıyla yazılı.
>
> Eklenen: `docker/docker-compose.yml`'a bir `minio` servisi (yalnız EKLEME),
> `tradehub_core/tests/test_storage_adapters_minio.py` (yeni dosya).

---

## 0. Karar (önce sonuç)

> ### Dört kip de gerçek S3 uyumlu bir servise karşı ÇALIŞIYOR. Üretime **bugünkü hâliyle alınamaz**; 2 yüksek öncelikli kusur var ve ikisi de tek satırlık düzeltmeler değil.

**Çalışan:** `local`, `s3`, `mirror`, `tiered` — dördü de aynı sözleşme
gövdesinden geçti. Sahte istemcili paketten (`test_storage_adapters.py`,
137 test) tek satır test metni kopyalanmadan, o dosyanın
`StorageContractMixin`'i **ithal edilerek** gerçek MinIO'ya karşı koşuldu:
**91 test, hepsi geçti.** İçerik-adresleme, dedup (`created=False`),
kapsam ayrımı, `move` sırasında anahtar korunması, `ObjectNotFound`,
idempotent `delete`, tembel `iter_keys`, TTL kelepçesi — hepsi gerçek
serviste de tutuyor. `sha256` metadata'sı MinIO'da yaşıyor ve `stat()`
onu geri veriyor; `demote()` `verify_mode=hash` ile doğruluyor.

**Alınamaz kılan:**

| # | Bulgu | Etki |
|---|---|---|
| **B-01** | Presigned URL **SigV2** üretiliyor, SigV4 değil | AWS S3'ün 2014 sonrası bölgelerinde private dosya indirme **hiç çalışmaz** |
| **B-02** | `S3Storage.exists()` ağ hatasında **istisna atıyor** — sözleşme "hata atmaz" diyor, kendi dokümanı "`False` döner" diyor | `tiered` kipinde `url_for()` soğuk katman düşünce render'ı kırar; 8,9 sn asılı kalır |
| **B-04** | `TieredStorage.delete()` sıcaktan siler, soğuk düşükken **istisna atar** | KVKK silme talebi "başarısız" görünürken sıcak kopya gitmiş olur |
| **B-05** | `media_mirror_queue=inline` üretimde açılabilir durumda | Yükleme gecikmesi 2 ms → 317 ms; S3 kesintisinde 3,5 sn |

**Açılabilme koşulu** §7'de; özet: B-01 ve B-02 düzeltilmeden hiçbir kip,
B-04 düzeltilmeden `tiered`, B-05 kelepçelenmeden `mirror` açılamaz.
`local` bugünkü davranıştır ve etkilenmez.

---

## 1. Sözleşme ve dört kip — kodda ne yazıyor

Tahmin edilmedi, okundu.

**Sözleşme** (`contracts/storage.py`): `runtime_checkable` bir `Protocol` —
`put`, `get`, `exists`, `stat`, `delete`, `move`, `iter_keys`, `url_for`.
Adres birimi `ObjectRef` (= `ObjectKey(shard, name)` + `scope`); anahtar
`sha256(içerik)[:32] + uzantı`, shard adın ilk 2 hex'i. `key_for()` saf ve
deterministik — "bir depo uygulaması kendi ad şemasını uyduramaz".
Kapsamlar `public` (`/files`) ve `private` (`/private/files`).

**Dört kip** (`storage/__init__.py`, `MODES`):

| kip | sınıf | ne yapar |
|---|---|---|
| `local` | `LocalDiskStorage` | bugünkü üretim davranışı, yerel disk |
| `s3` | `S3Storage` | yalnız nesne deposu |
| `mirror` | `MirrorStorage` | yerel BİRİNCİL + S3 asenkron ikincil |
| `tiered` | `TieredStorage` | sıcak yerel + N gün sonra soğuk S3 |

Fabrika (`build_storage`) S3 kullanılamazsa `local`'e düşer ve düşüşü
`StoragePlan.reasons` ile raporlar. Ölçüldü — sessiz düşüş yok:

| istenen kip | s3_enabled | kurulan adaptör | düşüş var mı | sebepler |
|---|---|---|---|---|
| local | 0 | local (LocalDiskStorage) | False | - |
| local | 1 | local (LocalDiskStorage) | False | - |
| s3 | 0 | local (LocalDiskStorage) | **True** | `s3_enabled=0` |
| s3 | 1 | s3 (S3Storage) | False | - |
| mirror | 0 | local (LocalDiskStorage) | **True** | `s3_enabled=0` |
| mirror | 1 | mirror (MirrorStorage) | False | - |
| tiered | 0 | local (LocalDiskStorage) | **True** | `s3_enabled=0` |
| tiered | 1 | tiered (TieredStorage) | False | - |

---

## 2. Ölçüm ortamı — ne kuruldu, ne kadar kalıcı

### 2.1 MinIO

`docker/docker-compose.yml`'a **yalnız eklenerek** bir `minio` servisi
girdi (mevcut hiçbir servis satırı değiştirilmedi):

- `minio/minio:latest`, `server /data --console-address :9001`
- host portları **9100** (S3 API) ve **9101** (konsol) — konteyner içi 9000
  frappe websocket'inde kullanıldığı için host tarafı 91xx'e alındı
- `minio-data` adlı yeni volume
- healthcheck: `mc ready local`
- **hiçbir servis buna `depends_on` ile bağlı değil**

> ### ⚠️ `docker/` bir git reposu DEĞİL
> `git rev-parse --show-toplevel` → *fatal: not a git repository*.
> Yani bu compose değişikliği **versiyonlanmıyor**: kimse `git log`'da
> göremez, `git checkout` ile geri alınamaz, başka bir makineye kendiliğinden
> gitmez. Kalıcı olması isteniyorsa `docker/` ya versiyonlanmalı ya da bu
> blok bir yere kopyalanmalı. Yedek: `/tmp/docker-compose.yml.t051.bak`
> (değişiklikten önceki hâli) — `/tmp` de kalıcı değil.

### 2.2 boto3

Görevin istediği sıra izlendi: önce **daha az müdahaleli yol**.

```
docker exec istoc-dev-backend-1 \
  /home/frappe/frappe-bench/env/bin/pip install boto3   →  boto3 1.34.162
```

`docker/backend.Dockerfile` **değiştirilmedi** ve `requirements.txt`'ye
boto3 **eklenmedi**. İkisi de bilinçli:

- **KALICI DEĞİL.** Bu kurulum konteynerin yazılabilir katmanında duruyor.
  `docker compose up -d --build backend` ya da konteyner yeniden
  oluşturulduğu an **kaybolur** ve bu raporun ölçümleri tekrar edilemez
  hâle gelir. Tekrar için yukarıdaki tek satır yeniden koşulmalı.
- İmaja eklemek, S3 kararı verilmeden üretim imajına bir bağımlılık
  sokardı; ayrıca tüm backend servislerinin (`backend`, `websocket`,
  `scheduler`, `queue-short`, `queue-long`, `frappe-frontend`) yeniden
  oluşturulmasını gerektirirdi. Ölçüm için gerekmiyordu.

`s3transfer` ve `jmespath` **zaten kuruluydu** (başka bir bağımlılıktan);
boto3 sürümü de bu yüzden botocore<1.35 kelepçesine düşüp 1.34.162'de
sabitlendi. Üretimde S3 açılacaksa sürüm bilinçli seçilmeli.

### 2.3 Medya hattı bu servisten habersiz

```
grep -iE "s3|minio|media_storage" sites/istoc.localhost/site_config.json \
                                  sites/common_site_config.json
→ HİÇBİR ANAHTAR YOK
```

`s3_enabled` tanımsız → `S3Config.enabled=False` → §1'deki tabloya göre her
kip `local`'e düşer. Bayraklar **0 kaldı**.

---

## 3. Sözleşme koşumu — dört kip, aynı test gövdesi

Yeni dosya: `tradehub_core/tests/test_storage_adapters_minio.py`.
Sözleşme testlerini **yeniden yazmıyor**; mevcut dosyadan
`StorageContractMixin` ve `Harness`/`LocalHarness` ithal ediyor ve tek bir
noktayı — `Harness._s3()` — sahte istemciden gerçek MinIO istemcisine
çeviriyor. "Aynı sözleşme, farklı arka uç" iddiası böylece koddan okunur.

```
env/bin/python -m unittest tradehub_core.tests.test_storage_adapters_minio
→ Ran 91 tests in 16.740s — OK
```

Kapsanan: dört kip × 22 sözleşme testi + yalnız gerçek serviste anlamlı
olan 7 test (presigned URL'in HTTP ile gerçekten indirilmesi, imzasız
erişimin 403 alması, süresi dolmuş imzanın 403 alması, `x-amz-meta-sha256`
metadata'sının gerçekten dönmesi, gerçek `list_objects_v2` sayfalaması,
SigV2 bulgusunun sabitlenmesi, s3v4 düzeltmesinin doğrulanması).

MinIO ulaşılamazsa dosya **skip** eder, düşmez: üretimde S3 yok ve yokluğu
bir hata değil.

---

## 4. Ölçüm tabloları

Tek geçişli senaryo tabloları aşağıda. **İlk `put` satırı yanıltıcıdır**:
`S3Storage` istemciyi tembel kuruyor (`import boto3` + bağlantı), o maliyet
ilk çağrıya biniyor ve koşumdan koşuma 100 ms'den fazla oynuyor. Karşılaştırma
için §4.6'daki ısınmış/tekrarlı tabloya bakılmalı. Ortam bir dizüstü Docker
VM'i; sayılar mutlak kapasite değil, **kipler arası oran** için anlamlıdır.

### 4.1 kip: local

| işlem | boyut | bayt | süre (ms) | sonuç |
|---|---|---:|---:|---|
| put (ilk yazma) | 1 KiB | 1024 | 2.31 | created=True |
| put (aynı içerik, dedup) | 1 KiB | 1024 | 0.43 | created=False |
| exists | 1 KiB | 0 | 0.07 | True |
| stat | 1 KiB | 0 | 0.11 | boyut=1024 hash=tam |
| get | 1 KiB | 1024 | 0.06 | 1024 bayt, içerik aynı |
| url_for (public) | 1 KiB | 0 | 0.01 | imzasız düz URL |
| put (private) | 1 KiB | 1024 | 0.96 | created=True |
| url_for (private, imzalı) | 1 KiB | 0 | 0.15 | imzalı (218 krkt) |
| delete (private) | 1 KiB | 0 | 0.10 | True |
| move (public→private) | 1 KiB | 1024 | 0.30 | anahtar korundu=True |
| delete | 1 KiB | 0 | 0.13 | silindi=True |
| delete (tekrar, idempotens) | 1 KiB | 0 | 0.06 | silindi=False |
| exists (silinmiş) | 1 KiB | 0 | 0.04 | False |
| put (ilk yazma) | 256 KiB | 262144 | 1.63 | created=True |
| put (aynı içerik, dedup) | 256 KiB | 262144 | 1.88 | created=False |
| exists | 256 KiB | 0 | 0.18 | True |
| stat | 256 KiB | 0 | 0.46 | boyut=262144 hash=tam |
| get | 256 KiB | 262144 | 0.26 | 262144 bayt, içerik aynı |
| url_for (public) | 256 KiB | 0 | 0.01 | imzasız düz URL |
| put (private) | 256 KiB | 262144 | 1.55 | created=True |
| url_for (private, imzalı) | 256 KiB | 0 | 0.14 | imzalı (218 krkt) |
| delete (private) | 256 KiB | 0 | 0.13 | True |
| move (public→private) | 256 KiB | 262144 | 0.13 | anahtar korundu=True |
| delete | 256 KiB | 0 | 0.10 | silindi=True |
| delete (tekrar, idempotens) | 256 KiB | 0 | 0.04 | silindi=False |
| exists (silinmiş) | 256 KiB | 0 | 0.04 | False |
| put (ilk yazma) | 4 MiB | 4194304 | 15.93 | created=True |
| put (aynı içerik, dedup) | 4 MiB | 4194304 | 20.30 | created=False |
| exists | 4 MiB | 0 | 0.75 | True |
| stat | 4 MiB | 0 | 7.80 | boyut=4194304 hash=tam |
| get | 4 MiB | 4194304 | 4.08 | 4194304 bayt, içerik aynı |
| url_for (public) | 4 MiB | 0 | 0.03 | imzasız düz URL |
| put (private) | 4 MiB | 4194304 | 21.99 | created=True |
| url_for (private, imzalı) | 4 MiB | 0 | 0.24 | imzalı (218 krkt) |
| delete (private) | 4 MiB | 0 | 0.80 | True |
| move (public→private) | 4 MiB | 4194304 | 0.25 | anahtar korundu=True |
| delete | 4 MiB | 0 | 1.17 | silindi=True |
| delete (tekrar, idempotens) | 4 MiB | 0 | 0.17 | silindi=False |
| exists (silinmiş) | 4 MiB | 0 | 0.05 | False |


### 4.2 kip: s3

| işlem | boyut | bayt | süre (ms) | sonuç |
|---|---|---:|---:|---|
| put (ilk yazma) | 1 KiB | 1024 | 68.87 | created=True |
| put (aynı içerik, dedup) | 1 KiB | 1024 | 7.16 | created=False |
| exists | 1 KiB | 0 | 5.29 | True |
| stat | 1 KiB | 0 | 4.46 | boyut=1024 hash=tam |
| get | 1 KiB | 1024 | 7.60 | 1024 bayt, içerik aynı |
| url_for (public) | 1 KiB | 0 | 0.02 | imzasız düz URL |
| put (private) | 1 KiB | 1024 | 22.85 | created=True |
| url_for (private, imzalı) | 1 KiB | 0 | 0.69 | imzalı (191 krkt) |
| delete (private) | 1 KiB | 0 | 9.70 | True |
| move (public→private) | 1 KiB | 1024 | 32.00 | anahtar korundu=True |
| delete | 1 KiB | 0 | 8.28 | silindi=True |
| delete (tekrar, idempotens) | 1 KiB | 0 | 3.67 | silindi=False |
| exists (silinmiş) | 1 KiB | 0 | 2.72 | False |
| put (ilk yazma) | 256 KiB | 262144 | 36.83 | created=True |
| put (aynı içerik, dedup) | 256 KiB | 262144 | 6.04 | created=False |
| exists | 256 KiB | 0 | 6.61 | True |
| stat | 256 KiB | 0 | 5.10 | boyut=262144 hash=tam |
| get | 256 KiB | 262144 | 6.35 | 262144 bayt, içerik aynı |
| url_for (public) | 256 KiB | 0 | 0.03 | imzasız düz URL |
| put (private) | 256 KiB | 262144 | 32.42 | created=True |
| url_for (private, imzalı) | 256 KiB | 0 | 0.77 | imzalı (185 krkt) |
| delete (private) | 256 KiB | 0 | 7.02 | True |
| move (public→private) | 256 KiB | 262144 | 33.74 | anahtar korundu=True |
| delete | 256 KiB | 0 | 11.43 | silindi=True |
| delete (tekrar, idempotens) | 256 KiB | 0 | 3.10 | silindi=False |
| exists (silinmiş) | 256 KiB | 0 | 3.78 | False |
| put (ilk yazma) | 4 MiB | 4194304 | 108.51 | created=True |
| put (aynı içerik, dedup) | 4 MiB | 4194304 | 10.47 | created=False |
| exists | 4 MiB | 0 | 4.95 | True |
| stat | 4 MiB | 0 | 5.52 | boyut=4194304 hash=tam |
| get | 4 MiB | 4194304 | 23.16 | 4194304 bayt, içerik aynı |
| url_for (public) | 4 MiB | 0 | 0.04 | imzasız düz URL |
| put (private) | 4 MiB | 4194304 | 106.49 | created=True |
| url_for (private, imzalı) | 4 MiB | 0 | 1.22 | imzalı (187 krkt) |
| delete (private) | 4 MiB | 0 | 13.79 | True |
| move (public→private) | 4 MiB | 4194304 | 78.55 | anahtar korundu=True |
| delete | 4 MiB | 0 | 16.11 | silindi=True |
| delete (tekrar, idempotens) | 4 MiB | 0 | 4.57 | silindi=False |
| exists (silinmiş) | 4 MiB | 0 | 3.94 | False |


### 4.3 kip: mirror (`inline_mirror` — sözleşme testiyle aynı kurulum)

| işlem | boyut | bayt | süre (ms) | sonuç |
|---|---|---:|---:|---|
| put (ilk yazma) | 1 KiB | 1024 | 39.09 | created=True |
| put (aynı içerik, dedup) | 1 KiB | 1024 | 6.09 | created=False |
| exists | 1 KiB | 0 | 2.75 | True |
| stat | 1 KiB | 0 | 0.66 | boyut=1024 hash=tam |
| get | 1 KiB | 1024 | 0.16 | 1024 bayt, içerik aynı |
| url_for (public) | 1 KiB | 0 | 0.02 | imzasız düz URL |
| put (private) | 1 KiB | 1024 | 35.15 | created=True |
| url_for (private, imzalı) | 1 KiB | 0 | 0.17 | imzalı (218 krkt) |
| delete (private) | 1 KiB | 0 | 10.44 | True |
| move (public→private) | 1 KiB | 1024 | 48.39 | anahtar korundu=True |
| delete | 1 KiB | 0 | 12.23 | silindi=True |
| delete (tekrar, idempotens) | 1 KiB | 0 | 6.61 | silindi=False |
| exists (silinmiş) | 1 KiB | 0 | 5.38 | False |
| put (ilk yazma) | 256 KiB | 262144 | 33.00 | created=True |
| put (aynı içerik, dedup) | 256 KiB | 262144 | 8.14 | created=False |
| exists | 256 KiB | 0 | 0.11 | True |
| stat | 256 KiB | 0 | 0.46 | boyut=262144 hash=tam |
| get | 256 KiB | 262144 | 0.28 | 262144 bayt, içerik aynı |
| url_for (public) | 256 KiB | 0 | 0.01 | imzasız düz URL |
| put (private) | 256 KiB | 262144 | 32.44 | created=True |
| url_for (private, imzalı) | 256 KiB | 0 | 0.37 | imzalı (218 krkt) |
| delete (private) | 256 KiB | 0 | 11.10 | True |
| move (public→private) | 256 KiB | 262144 | 38.36 | anahtar korundu=True |
| delete | 256 KiB | 0 | 14.04 | silindi=True |
| delete (tekrar, idempotens) | 256 KiB | 0 | 3.45 | silindi=False |
| exists (silinmiş) | 256 KiB | 0 | 5.65 | False |
| put (ilk yazma) | 4 MiB | 4194304 | 163.53 | created=True |
| put (aynı içerik, dedup) | 4 MiB | 4194304 | 31.77 | created=False |
| exists | 4 MiB | 0 | 0.15 | True |
| stat | 4 MiB | 0 | 10.66 | boyut=4194304 hash=tam |
| get | 4 MiB | 4194304 | 3.57 | 4194304 bayt, içerik aynı |
| url_for (public) | 4 MiB | 0 | 0.03 | imzasız düz URL |
| put (private) | 4 MiB | 4194304 | 169.51 | created=True |
| url_for (private, imzalı) | 4 MiB | 0 | 0.34 | imzalı (218 krkt) |
| delete (private) | 4 MiB | 0 | 23.80 | True |
| move (public→private) | 4 MiB | 4194304 | 82.08 | anahtar korundu=True |
| delete | 4 MiB | 0 | 15.81 | silindi=True |
| delete (tekrar, idempotens) | 4 MiB | 0 | 4.37 | silindi=False |
| exists (silinmiş) | 4 MiB | 0 | 4.83 | False |
| ayna: ikincilde var mı | 256 KiB | 0 | 5.75 | True (sayaçlar={'ok': 22, 'failed': 0, 'dropped': 0}) |
| ayna: reconcile | - | 0 | 6.21 | tarandı=1 eksik=0 kuyruğa=0 |


### 4.4 kip: tiered

| işlem | boyut | bayt | süre (ms) | sonuç |
|---|---|---:|---:|---|
| put (ilk yazma) | 1 KiB | 1024 | 3.33 | created=True |
| put (aynı içerik, dedup) | 1 KiB | 1024 | 0.19 | created=False |
| exists | 1 KiB | 0 | 0.04 | True |
| stat | 1 KiB | 0 | 0.06 | boyut=1024 hash=tam |
| get | 1 KiB | 1024 | 0.05 | 1024 bayt, içerik aynı |
| url_for (public) | 1 KiB | 0 | 0.05 | imzasız düz URL |
| put (private) | 1 KiB | 1024 | 1.08 | created=True |
| url_for (private, imzalı) | 1 KiB | 0 | 0.18 | imzalı (218 krkt) |
| delete (private) | 1 KiB | 0 | 21.59 | True |
| move (public→private) | 1 KiB | 1024 | 4.90 | anahtar korundu=True |
| delete | 1 KiB | 0 | 3.38 | silindi=True |
| delete (tekrar, idempotens) | 1 KiB | 0 | 4.47 | silindi=False |
| exists (silinmiş) | 1 KiB | 0 | 4.18 | False |
| put (ilk yazma) | 256 KiB | 262144 | 2.12 | created=True |
| put (aynı içerik, dedup) | 256 KiB | 262144 | 2.48 | created=False |
| exists | 256 KiB | 0 | 0.21 | True |
| stat | 256 KiB | 0 | 0.46 | boyut=262144 hash=tam |
| get | 256 KiB | 262144 | 0.29 | 262144 bayt, içerik aynı |
| url_for (public) | 256 KiB | 0 | 0.08 | imzasız düz URL |
| put (private) | 256 KiB | 262144 | 1.95 | created=True |
| url_for (private, imzalı) | 256 KiB | 0 | 1.13 | imzalı (218 krkt) |
| delete (private) | 256 KiB | 0 | 7.66 | True |
| move (public→private) | 256 KiB | 262144 | 5.00 | anahtar korundu=True |
| delete | 256 KiB | 0 | 2.88 | silindi=True |
| delete (tekrar, idempotens) | 256 KiB | 0 | 3.54 | silindi=False |
| exists (silinmiş) | 256 KiB | 0 | 4.15 | False |
| put (ilk yazma) | 4 MiB | 4194304 | 17.74 | created=True |
| put (aynı içerik, dedup) | 4 MiB | 4194304 | 31.97 | created=False |
| exists | 4 MiB | 0 | 0.14 | True |
| stat | 4 MiB | 0 | 7.86 | boyut=4194304 hash=tam |
| get | 4 MiB | 4194304 | 3.62 | 4194304 bayt, içerik aynı |
| url_for (public) | 4 MiB | 0 | 0.39 | imzasız düz URL |
| put (private) | 4 MiB | 4194304 | 21.76 | created=True |
| url_for (private, imzalı) | 4 MiB | 0 | 0.39 | imzalı (218 krkt) |
| delete (private) | 4 MiB | 0 | 6.31 | True |
| move (public→private) | 4 MiB | 4194304 | 4.74 | anahtar korundu=True |
| delete | 4 MiB | 0 | 5.13 | silindi=True |
| delete (tekrar, idempotens) | 4 MiB | 0 | 5.12 | silindi=False |
| exists (silinmiş) | 4 MiB | 0 | 5.22 | False |
| katman: demote (yaz→doğrula→sil) | 256 KiB | 262144 | 51.06 | taşındı=True doğrulama=hash serbest=262144B |
| katman: konum | - | 0 | 4.66 | cold |
| katman: soğuktan get | 256 KiB | 262144 | 11.82 | 262144 bayt, içerik aynı |
| katman: promote | 256 KiB | 0 | 13.19 | True |
| katman: konum (promote sonrası) | - | 0 | 6.02 | both |


`demote` gerçek yolu koştu: soğuğa yaz → **hash ile doğrula** → sıcaktan sil.
`verify_mode=hash` çıktı, yani `x-amz-meta-sha256` MinIO'dan geri okunabildi
ve zayıf `size` doğrulamasına düşülmedi. `promote` sonrası konum `both` —
modül dokümanının söylediği gibi soğuk kopya silinmiyor.

### 4.5 kip: mirror, ÜRETİM kuyruğuyla (`ThreadMirrorQueue`)

| işlem | boyut | bayt | süre (ms) | sonuç |
|---|---|---:|---:|---|
| put (çağıranın gördüğü süre) | 1 KiB | 1024 | 1.87 | created=True |
| drain (ayna kuyruğu boşalana kadar) | 1 KiB | 1024 | 50.44 | kuyruk boş |
| ikincilde var mı (drain sonrası) | 1 KiB | 0 | 8.23 | True |
| put (çağıranın gördüğü süre) | 256 KiB | 262144 | 2.22 | created=True |
| drain (ayna kuyruğu boşalana kadar) | 256 KiB | 262144 | 46.95 | kuyruk boş |
| ikincilde var mı (drain sonrası) | 256 KiB | 0 | 4.93 | True |
| put (çağıranın gördüğü süre) | 4 MiB | 4194304 | 82.23 | created=True |
| drain (ayna kuyruğu boşalana kadar) | 4 MiB | 4194304 | 121.78 | kuyruk boş |
| ikincilde var mı (drain sonrası) | 4 MiB | 0 | 6.12 | True |
| ayna sayaçları | - | 0 | 0.01 | {'ok': 3, 'failed': 0, 'dropped': 0} |


**Modül dokümanının asıl iddiası burada sınandı ve TUTTU:** çağıranın
gördüğü `put` süresi 1,87 / 2,22 / 82,23 ms — yerel diskin kendisiyle aynı
mertebede. S3'e yazma `drain` süresine (47–122 ms) kaydı, yükleme yoluna
binmedi. `ok: 3, failed: 0, dropped: 0`, üç dosya da ikincilde doğrulandı.

### 4.6 Isınmış ölçüm — 5 tekrar, medyan

| kip | işlem | medyan | en düşük | en yüksek | n |
|---|---|---:|---:|---:|---:|
| local | put 256 KiB | 2.07 | 1.46 | 3.24 | 5 |
| local | get 256 KiB | 0.31 | 0.21 | 0.33 | 5 |
| local | exists | 0.05 | 0.04 | 0.05 | 5 |
| local | stat | 0.43 | 0.41 | 0.49 | 5 |
| local | delete | 0.14 | 0.13 | 0.18 | 5 |
| s3 | put 256 KiB | 45.49 | 28.99 | 84.43 | 5 |
| s3 | get 256 KiB | 9.30 | 6.80 | 33.62 | 5 |
| s3 | exists | 5.75 | 4.17 | 12.02 | 5 |
| s3 | stat | 5.58 | 3.60 | 9.95 | 5 |
| s3 | delete | 9.57 | 7.33 | 17.17 | 5 |
| mirror | put 256 KiB | 317.42 | 125.48 | 444.86 | 5 |
| mirror | get 256 KiB | 0.38 | 0.33 | 0.64 | 5 |
| mirror | exists | 0.07 | 0.06 | 1.21 | 5 |
| mirror | stat | 0.63 | 0.49 | 2.81 | 5 |
| mirror | delete | 13.59 | 9.24 | 17.61 | 5 |
| tiered | put 256 KiB | 1.94 | 1.72 | 4.14 | 5 |
| tiered | get 256 KiB | 0.31 | 0.20 | 0.34 | 5 |
| tiered | exists | 0.06 | 0.04 | 0.13 | 5 |
| tiered | stat | 0.45 | 0.32 | 0.52 | 5 |
| tiered | delete | 5.36 | 3.74 | 6.00 | 5 |


Okunuşu:

- **`s3` kipi yerel diske göre `put`'ta ~22×, `get`'te ~30× yavaş** (45,49 ms
  vs 2,07 ms; 9,30 ms vs 0,31 ms). Bu aynı makinedeki bir konteyner; gerçek
  bir bulut bölgesinde ağ gecikmesi bunun üstüne biner.
- **`exists`/`stat` yerelde ~0,05–0,43 ms, S3'te ~5,6 ms — yüz kat.** Kodun
  `exists()`'i ucuz sayan her yeri (ör. `TieredStorage.url_for` her URL
  üretiminde `hot.exists()` + gerekirse `cold.exists()` çağırıyor) S3
  katmanında ağ çağrısına dönüşüyor.
- **`mirror` inline kurulumda `put` medyanı 317 ms** — yerelin 150 katı.
  Aynı kip `ThreadMirrorQueue` ile 2,22 ms. Fark tamamen kuyruk seçiminden
  geliyor (B-05).
- `tiered` yeni yazmada yerelle aynı (1,94 ms) — beklenen, çünkü `put`
  her zaman sıcak katmana gidiyor. `delete` 5,36 ms, çünkü iki katmandan
  da siliyor.

---

## 5. Hata yolu — servis kapalıyken ne oluyor

`docker compose stop minio` ile MinIO durduruldu ve aynı işlemler tekrar
koşuldu (`--failure`). Ölçülen: birincil yazma hâlâ çalışıyor mu, istisna
sözleşme hiyerarşisinden mi geliyor yoksa ham `botocore` istisnası mı
sızıyor, ve düşüş kaç saniye sürüyor.

| kip | işlem | süre (ms) | sonuç |
|---|---|---:|---|
| s3 | put | 3497.6 | HATA StorageError: S3 işlemi başarısız ← sözleşme istisnası |
| mirror | put | 3570.3 | created=True (BİRİNCİL YAZMA GEÇTİ) |
| mirror | get (birincilden) | 0.2 | 65536 bayt |
| mirror | ayna sayaçları | 0.0 | {'ok': 0, 'failed': 1, 'dropped': 0} |
| mirror | düşen görevler | 0.0 | StorageError:media_conflict |
| mirror | exists | 0.0 | True |
| mirror | stat | 0.2 | boyut=65536 |
| mirror | delete | 7957.0 | True |
| tiered | put | 2.8 | created=True (BİRİNCİL YAZMA GEÇTİ) |
| tiered | exists | 1.1 | True |
| tiered | stat | 0.3 | boyut=65536 |
| tiered | delete | 4462.5 | HATA StorageError: S3 işlemi başarısız ← sözleşme istisnası |
| tiered | demote (soğuk kapalı) | 11601.0 | taşındı=False sebep=cold_put_failed:media_conflict (sıcak kopya duruyor) |
| tiered | sıcak kopya hâlâ var mı | 0.2 | True |


**Fail-safe olan:**

- **`mirror` — birincil yazma GEÇTİ.** S3 tamamen kapalıyken bile `put()`
  başarılı döndü, `get()` birincilden 0,2 ms'de okudu, düşen görev
  `failed_tasks()` ile görünür oldu. Modül dokümanının "ikincil hiçbir
  koşulda birinciyi düşürmez" kuralı **tuttu**.
- **`tiered` — `demote()` sıcağa DOKUNMADI.** `cold_put_failed` sebebiyle
  `moved=False` döndü ve sıcak kopya yerinde kaldı (`sıcak kopya hâlâ var
  mı → True`). "Yaz → doğrula → sil" sırası veri kaybını önledi.
- **`s3` — sessiz başarı YOK.** `put()` `StorageError` attı; ham botocore
  istisnası sızmadı.

**Fail-safe OLMAYAN:**

- **`tiered.delete()` yarım sildi ve sonra patladı** (B-04).
- **Bekleme süreleri sözleşmesiz.** `s3.put` 3,5 sn, `mirror.delete` 8,0 sn,
  `tiered.demote` 11,6 sn asılı kaldı. `s3.py:_client()` hiçbir
  `connect_timeout`/`read_timeout`/`retries` vermiyor; botocore varsayılanı
  (legacy retry, 5 deneme) geçerli. Bir web isteği içinde bu süreler
  kullanıcıya kesinti olarak yansır.
- **`mirror` inline kuyrukla `put` 3,5 sn sürdü** — asenkron kuyrukta
  sürmezdi (B-05).

---

## 6. Bulgular

### B-01 · YÜKSEK · Presigned URL SigV2 üretiliyor, SigV4 değil

`storage/s3.py` `_client()` içinde `BotoConfig` yalnız `addressing_style`
ile kuruluyor; `signature_version` **verilmiyor**. Tanınmayan bir endpoint
için botocore eski `s3` imzalayıcısına (SigV2) düşüyor. Ölçülen URL:

```
…/private/77/778c….pdf?AWSAccessKeyId=minioadmin&Signature=f1rt…%3D&Expires=1787230994
```

`X-Amz-Signature` yok, `X-Amz-Expires` yok. MinIO bunu kabul ediyor
(indirme 200 döndü) — **AWS S3'ün 2014 sonrasında açılmış bölgeleri
etmiyor** (eu-central-1, eu-west-2, ap-*, …); AWS SigV2'yi ayrıca
kullanımdan kaldırıyor. Yani bugünkü kod MinIO/Ceph ile çalışır, AWS ile
private dosya servisi **hiç çalışmaz**.

TTL kelepçesi yine de uygulanıyor — ölçüldü: 10 günlük istek → `Expires -
now = 86400`. Yani güvenlik açığı değil, **taşınabilirlik kırığı**.

**Düzeltme ölçüldü ve çalışıyor:** `BotoConfig(signature_version="s3v4", …)`.
Adaptörün kendi `client_factory` kancasından enjekte edilerek `s3.py`
değiştirilmeden doğrulandı — `X-Amz-Signature` üretti, `X-Amz-Expires=86400`
çıktı, indirme 200 döndü
(`test_s3v4_enjekte_edilince_calisiyor`).

**Yan bulgu — sahte test bunu yakalayamazdı.** `test_storage_adapters.py`
içindeki `FakeS3Client.generate_presigned_url` URL'i elle kuruyor ve
`?X-Amz-Expires=` parametresini **uyduruyor**. Ortak gövdedeki
`test_url_for_private_ttl_kelepcelenir` tam da o parametreyi okuduğu için
sahte koşumda yeşil, gerçek MinIO'da **düştü**. Ortak dosya
değiştirilmedi; yeni dosyada `PresignTtlUyarlamasi` ile üç imza biçimini de
okuyan bir override kondu ve bugünkü SigV2 davranışı ayrıca
`test_presign_imza_surumu_SigV2_BULGU` ile **sabitlendi** — `s3.py`
düzeltildiğinde o test düşecek ve düşüşü düzeltmenin kanıtı olacak.

### B-02 · YÜKSEK · `S3Storage.exists()` ağ hatasında istisna atıyor

Sözleşme (`contracts/storage.py`): *"Nesne var mı. Yan etkisiz, **hata
atmaz**."*
`s3.py`'nin kendi `exists()` dokümanı: *"Ağ hatası da `False` döner —
sözleşme 'hata atmaz' diyor."*
Ölçülen (MinIO kapalı):

```
exists ISTISNA ATTI: StorageError kod=media_conflict   süre 8949,7 ms
```

Sebep: `exists()` → `_head()` → `_is_missing()` değilse `raise
self._wrap(...)`. Doküman ile kod çelişiyor ve **kod kaybediyor**.

Etkisi kipler arası yayılıyor:

- `MirrorStorage.exists()` = `primary.exists() or secondary.exists()` —
  birincilde yoksa ikincile sorar, ikincil düşükse **istisna**.
- `TieredStorage.url_for()` her çağrıda `hot.exists()`, gerekirse
  `cold.exists()` çağırıyor. Soğuk katman düşükken **URL üretimi patlar**.
  Aynı fonksiyonun kendi dokümanı bunun tam tersini gerekçelendiriyor:
  *"istisna atıp render'ı kırmaktan daha az zararlı"*. Bugünkü kodda render
  kırılıyor — üstelik 8,9 sn bekledikten sonra.

### B-03 · ORTA · Her depolama hatası `media_conflict` kodunu taşıyor

`contracts/errors.py`:

```
class StorageError(MediaEngineError):
	varsayilan_sebep = SEBEP_CONFLICT      # → kod: media_conflict
```

Ölçülen: ağ hatasından doğan `StorageError.kod == "media_conflict"` —
`StorageConflict` ile **aynı kod**. Ayna kuyruğunun düşen görev kaydı da
`StorageError:media_conflict` diye yazıldı; oysa çakışma değil, servis
erişilemezliği.

FR-060 istemcinin hata **koduna** bakmasını şart koşuyor. Bugün istemci
"aynı anahtar farklı içerik" ile "S3 kapalı"yı koddan ayıramıyor; yalnız
`retryable` alanı (False vs True) ayırıyor. `SEBEP_UNAVAILABLE` gibi ayrı
bir kod gerekiyor. *(`contracts/errors.py` dokunma listesinde — yalnız
raporlandı.)*

### B-04 · ORTA · `TieredStorage.delete()` yarım silip istisna atıyor

```
def delete(self, ref):
	sicak = self._hot.delete(ref)     # ← başarıyla siler
	soguk = self._cold.delete(ref)    # ← soğuk düşükse StorageError
	return sicak or soguk
```

Ölçülen (MinIO kapalı): `delete → HATA StorageError` (4462 ms) — **sıcak
kopya o sırada silinmiş durumda**. Çağıran "silme başarısız" görüyor;
yeniden denediğinde sıcak `False` dönüyor ve soğuk yine patlıyor, yani
işlem **kalıcı olarak başarısız** görünüyor. Modülün kendi gerekçesi
("KVKK silme talebi açısından gerçek bir risk") tam da bu senaryoyu
işaret ediyor ama sıra bunu karşılamıyor: ya soğuk önce silinmeli, ya
kısmi sonuç istisna yerine raporlanmalı.

### B-05 · ORTA · `inline` ayna kuyruğu üretimde seçilebilir durumda

`storage/__init__.py` `_mirror_queue_factory` `media_mirror_queue=inline`
değerini kabul ediyor; tek koruma `InlineMirrorQueue`'nun docstring'i
("Üretimde kullanmak `put()`'u S3'e bağlar"). Ölçülen bedel:

| kurulum | `put` 256 KiB medyan | S3 kapalıyken `put` | S3 kapalıyken `delete` |
|---|---:|---:|---:|
| `local` | 2,07 ms | — | — |
| `mirror` + `ThreadMirrorQueue` | **2,22 ms** | (kuyruğa düşer) | (kuyruğa düşer) |
| `mirror` + `InlineMirrorQueue` | **317,42 ms** | **3570 ms** | **7957 ms** |

Yanlış tek bir ayar satırı, yükleme yolunu 150 kat yavaşlatıp S3'ü
birincil tek hata noktası hâline getiriyor — modülün önlemek için var
olduğu şey. Ayar katmanında reddedilmeli.

### B-06 · BELGE · `s3.py` "boto3 konteynerde VAR" diyor; yok

`storage/s3.py` modül dokümanı:

> *"Ölçüldü (2026-08-18): `boto3` yerelde YOK, `istoc-dev-backend-1`
> konteynerinde VAR."*

2026-08-19'da ölçüldü: konteynerin **ne sistem python'unda ne bench
sanal ortamında** boto3 vardı (`ModuleNotFoundError`), `requirements.txt`
dört satır ve içinde yok. Bu cümle T-051'in "kod yazıldı" durumunu
destekleyen tek ampirik iddiaydı ve **yanlıştı**. Bu rapordaki ölçüm de
ancak elle `pip install` sonrası mümkün oldu.

### Bulgu OLMAYAN — kayda geçsin

- **Adresleme stili.** `S3Config.addressing_style` varsayılanı `auto`;
  MinIO ile **çalışıyor** (ölçüldü: `auto` → OK 272 ms, `path` → OK 69 ms).
  Yalnız açıkça `virtual` seçilirse kırılıyor (`StorageError`, 7068 ms) —
  `bucket.minio:9000` DNS'te yok. Varsayılan güvenli.
- **İmza dayatması.** MinIO süresi dolmuş presigned URL'i **403** ile
  reddetti (ölçüldü). İmzasız düz erişim de **403** aldı; bucket public
  değil.
- **TTL kelepçesi.** 10 günlük istek her iki imza sürümünde de 86400 sn'ye
  indi (`MAX_TTL_SECONDS`). `url_for(ttl=1)` ise 60 sn'ye **yükseldi**
  (`MIN_TTL_SECONDS`) — beklenen davranış.
- **Fabrikanın düşüş raporu.** §1'deki tablo: `s3_enabled=0` iken üç S3
  kipi de `local`'e düşüyor ve sebebi taşıyor. Sessiz düşüş yok.

---

## 7. Üretime alınabilir mi

**Hayır — bugünkü hâliyle hiçbir S3 kipi açılmamalı.** Adaptörler
çalışıyor; eksik olan kod değil, üç kapının kapalı olması.

### Kip kip

| kip | gerçek serviste çalışıyor mu | açılabilir mi | engel |
|---|---|---|---|
| `local` | evet (bugünkü üretim) | **zaten açık** | — |
| `s3` | evet, 91 testin tamamı | **hayır** | B-01, B-02; ayrıca tek kopya = yedeklilik kaybı |
| `mirror` | evet | **hayır** | B-01, B-02, B-05; `reconcile` zamanlanmamış |
| `tiered` | evet, `demote`/`promote` dâhil | **hayır** | B-01, B-02, **B-04**; `age_days=90` ölçülmemiş bir varsayılan |

### Açılma koşulları (sırayla)

1. **B-01 düzelt** — `signature_version="s3v4"`. Düzeltme ölçüldü, çalışıyor.
   Aynı yamada `connect_timeout`/`read_timeout`/`retries` de verilmeli
   (bugün 3,5–11,6 sn asılı kalıyor, §5).
2. **B-02 düzelt** — `exists()` ağ hatasında `False` dönmeli (kendi
   dokümanının söylediği gibi). Aksi hâlde `tiered` kipinde soğuk katman
   kesintisi doğrudan render kırar.
3. **B-04 düzelt** — `tiered.delete()` kısmi sonucu istisna yerine
   raporlamalı; KVKK silme talebi buna bağlı.
4. **B-05 kelepçele** — `media_mirror_queue=inline` üretim ayarında
   reddedilmeli.
5. **boto3'ü imaja al** — `docker/backend.Dockerfile` + `requirements.txt`,
   sürüm bilinçli seçilerek. Bugünkü kurulum konteyner ömürlüdür (§2.2).
6. **`mirror.reconcile()` zamanla** — kuyruk dolması, süreç yeniden başlaması
   ve S3 kesintisi hâlinde düşen görevlerin TEK telafi yolu bu ve bugün
   hiçbir zamanlayıcıya bağlı değil.
7. **`tiered` için `age_days` ölç** — `DEFAULT_AGE_DAYS=90` kodun kendi
   ifadesiyle "bir ölçüm değil, bir varsayılan seçimi". Erişim log'undan
   "yüklendikten N gün sonra hâlâ istenen dosya oranı" çıkarılmalı.
8. **`tiered` + private kapsam kararı** — bugün `keep_scopes=(public,)`,
   yani KYB/KYC belgeleri yaslanmıyor. Bu bilinçli KVKK kararı; açılırken
   ayrıca ele alınmalı.

### Bugün ne söylenebilir

- "Adaptörler yazıldı ama gerçek S3'e karşı ölçülmedi" durumu **kapandı**:
  ölçüldü, dört kip de gerçek bir S3 uyumlu servise karşı sözleşmeyi
  koruyor.
- "Üretime hazır" durumu **açılmadı** ve bu raporun ürettiği asıl değer,
  hazır olmadığını sahte istemcinin gösteremediği dört noktada (B-01, B-02,
  B-04, B-05) göstermesi.

---

## 8. Mevcut stack bozulmadı — doğrulama

MinIO eklendikten ve ölçüm bittikten sonra:

```
docker compose ps        → 14 servisin hepsi Up (minio dâhil, healthy)
curl http://istoc.localhost/files/Bere-1.png   → 200
curl http://istoc.localhost/                   → 200
curl http://istoc.localhost/panel/             → 200
curl http://istoc.localhost:8001/api/method/ping → 200
```

Test koşumları:

| paket | koşum | sonuç |
|---|---|---|
| `tradehub_core.tests.test_storage_adapters` (sahte istemci) | `python -m unittest` | **137 test, OK** |
| `tradehub_core.tests.test_dedup` | `python -m unittest` | **57 test, OK** |
| `tradehub_core.tests.test_media_access` | `bench --site istoc.localhost run-tests --module …` | **17 test, OK** (85,8 sn) |
| `tradehub_core.tests.test_storage_adapters_minio` (yeni) | `python -m unittest` | **91 test, OK** |

Not: `test_media_access`, `test_media_access_level`, `test_media_naming`,
`test_media_pipeline_integration` düz `python -m unittest` ile
**koşmuyor** — `frappe.tests.utils` `test_site` adlı bir site arıyor
(`IncorrectSitePath`). Bu, bu görevden önce de böyleydi ve MinIO ile
ilgisi yok; doğru koşum yolu `bench … run-tests` ve o yolla `test_media_access`
geçiyor (yukarıda).

---

## 9. Bırakılan durum

- **MinIO çalışıyor ve KAPALI yapılandırılmış.** Servis Up ve healthy;
  hiçbir servis ona bağlı değil; `site_config.json`/`common_site_config.json`
  içinde tek bir `s3_*` anahtarı yok; dolayısıyla fabrika her kipte `local`
  döndürüyor. Medya hattı MinIO'dan habersiz çalışıyor.
- **Test bucket'ı boş.** `istoc-medya-test` içinde 0 nesne — her koşum kendi
  `t051/<kip>/<uuid>` önekini kullanıp sonunda siliyor.
- **boto3 konteyner ömürlü** (§2.2). Ölçümü tekrarlamak için tek satır
  yeniden koşulmalı.
- **`docker/` versiyonlanmıyor** (§2.1). Compose değişikliği git'te yok.
- **Değişen/eklenen dosyalar:**
  - `docker/docker-compose.yml` — `minio` servisi + `minio-data` volume (EKLEME)
  - `tradehub_core/tests/test_storage_adapters_minio.py` — YENİ
  - `docs/reports/23-t051-s3-adaptor.md` — bu belge
- **MinIO'yu tamamen kaldırmak için:** `docker compose stop minio && docker
  compose rm -f minio && docker volume rm istoc-dev_minio-data`, ardından
  compose'daki bloğun silinmesi. Stack bu servisten hiçbir şekilde
  beslenmediği için kaldırma başka hiçbir servisi etkilemez.

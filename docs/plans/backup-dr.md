# Medya Yedekleme ve Felaket Kurtarma Planı (T-054)

> **Kapanış güncellemesi · 2026-08-23:** Aşağıdaki 2026-08-18 envanteri
> tarihsel başlangıç ölçümüdür. Geliştirme sitesinde yedekleme artık gerçekten
> çalıştırıldı: `20260823_104322_t054_phase5` seti 8.893 orijinal dosya /
> 1.041.292.081 bayt ve 5.126 `File` kaydı taşıyor; 1.197 yeniden üretilebilir
> rendition `/files/media/` politikasıyla dışlandı. Tam `verify(deep=True)`
> 8.893/8.893, deterministik 100 dosyalık örneklem 100/100 geçti. Kontrollü tek
> dosya restore tatbikatı 280,7 ms sürdü ve SHA-256 birebir korundu. Ayrıntı:
> `docs/reports/100-t054-phase5-dr-rehearsal.md`. Üretim altyapısında uzak kopya
> ve periyodik tatbikatı açmak operasyonel rollout kapısı olarak devam eder.

**Kapsam:** İstoç medya varlıkları — orijinal dosyalar, `File` kayıtları, türevler,
çöp/arşiv/yedek alanları.
**Kapsam dışı:** Veritabanının tamamı (Frappe'nin kendi yedeği), uygulama kodu,
konteyner imajları. Bunlara değinilir ama sahibi bu belge değildir.

**Ölçüm tarihi:** 2026-08-18 · **Ortam:** `istoc-dev-backend-1` / `istoc.localhost`
(geliştirme). Üretim sunucusunda ÖLÇÜLMEDİ — bu belgedeki her sayının hangi
ortamdan geldiği satır satır yazılıdır ve üretime taşınmadan önce §7'deki
komutlarla yeniden ölçülmelidir.

---

## 0. Tarihsel başlangıç ölçümü (2026-08-18)

| Soru | Ölçülen cevap |
|---|---|
| Medya dosyalarının yedeği var mı? | **HAYIR.** `private/media-backups/` dizini YOK. |
| Yedek görevi hiç koştu mu? | **HAYIR.** `Scheduled Job Type` → `tradehub_core.media.backup.run_scheduled`, `last_execution = None`. |
| Zamanlayıcı çalışıyor mu? | **HAYIR.** `frappe.utils.scheduler.is_scheduler_inactive() == True`; son `Scheduled Job Log` kaydı **2026-08-03 08:15** (15 gün önce). |
| Veritabanı yedeği var mı? | Tek dosya: `20260804_083345-istoc_localhost-database.sql.gz`, **10.432.574 bayt**, **2026-08-04** (14 gün önce). |
| Bugünkü fiilî RPO | **Sınırsız** — kurtarılacak bir medya yedeği yok. |
| Bugünkü fiilî RTO | **Ölçülemez** — geri yüklenecek set yok. |

`tradehub_core/media/backup.py` modül dokümanındaki cümle (“Bu oturumda üç kez
yaşandı, ikisi kalıcı kayıpla sonuçlandı”) bu tablonun anlamını özetliyor:
kod yazıldı, **çalıştırılmadı**. Bu planın birinci maddesi yeni bir sistem
kurmak değil, **var olanı açmaktır** (§6.1).

---

## 1. Neyi koruyoruz — varlık envanteri (ölçülen)

| Varlık | Yer | Ölçülen boyut | Dosya sayısı | Yedekleniyor mu |
|---|---|---:|---:|---|
| Public medya | `<site>/public/files` | **981.242.219 B** (935,8 MiB) | **4.016** | Hayır |
| Private medya | `<site>/private/files` | ~165 MB (`du -sh`) | **325** | Hayır |
| `File` kayıtları | MariaDB `tabFile` | — | **4.964** (608 private) | DB yedeğiyle (14 gün eski) |
| Çöp (`media_trash`) | `<site>/private/media_trash` | **dizin yok** | 0 | — |
| Optimizasyon arşivi (`image_originals`) | `<site>/private/image_originals` | **dizin yok** | 0 | — |
| Medya yedek havuzu | `<site>/private/media-backups` | **dizin yok** | 0 | — |
| DB yedeği | `<site>/private/backups` | 10.432.574 B | 1 set | — |
| Boş disk | `/dev/vdb1` | **301 GB boş / 348 GB** (%14 dolu) | — | — |

> **Tutarsızlık, açıkça:** görev tanımındaki canlı ölçüm 4.958 dosya / 1.559 MB
> diyor; bu konteynerde 4.341 dosya / ~1.109 MB ölçüldü. `File` kayıt sayısı
> (4.964) görev tanımıyla uyuşuyor, **disk** uyuşmuyor — yani DB'de kaydı olup
> diskte olmayan (ya da başka bir kökte duran) dosyalar var. Bu, `retention.md`
> §9.6'daki “kayıt ↔ disk örtüşüyor mu” sorusunun cevabının **hayır** olduğunu
> gösteriyor ve DR açısından önemli: **kurtarma planı DB kaydına göre yapılırsa
> eksik dosya sessizce “geri yüklendi” sayılır.** `restore.plan()` bu farkı
> `missing_file` olarak raporluyor (§4.2).

---

## 2. Ölçülen kurtarma hızları

Ölçüm betikleri konteyner içinde, `/home/frappe/olcum/` altında koşturuldu.

| Ölçüm | Yöntem | Sonuç |
|---|---|---|
| Soğuk okuma | `posix_fadvise(DONTNEED)` ile sayfa önbelleği düşürüldü, 981 MB sha256'lanarak okundu | **706,8 MB/s** |
| Kopyalama (geri yükleme vekili) | `shutil.copytree` + `sync`, 981 MB | **407,5 MB/s** (2,30 sn) |
| Derin doğrulama (sha256) | 4.016 dosya, sıcak önbellek | **1.285,2 MB/s** (0,73 sn) |

**Bu sayıların sınırı:** kopyalama ölçümü kaynağı sıcak önbellekten okumuş
olabilir; gerçek geri yükleme daha yavaş olur. Soğuk okuma ölçümü (706,8 MB/s)
bu yüzden daha güvenilir taban. Üretim diski ÖLÇÜLMEDİ; ağ üzerinden
(S3/uzak yedek) geri yükleme hızı ÖLÇÜLMEDİ.

---

## 3. RPO / RTO — sayısal hedefler

### 3.1 Hedefler

| Senaryo | RPO (kabul edilen veri kaybı) | RTO (hizmete dönüş) | Dayanak |
|---|---|---|---|
| S1 — Tek dosya silindi/bozuldu | **24 saat** | **≤ 5 dk** | Günlük snapshot + `restore.apply(only=[...])` |
| S2 — Toplu silme (yanlış purge, hatalı script) | **24 saat** | **≤ 30 dk** | Tek set geri yükleme, 981 MB @ 706,8 MB/s = **1,4 sn** ham kopya; kalan süre insan kararı + doğrulama |
| S3 — Medya diski tamamen kayıp | **24 saat** | **≤ 4 saat** | Disk sağlama + tam set geri yükleme + `verify(deep=True)` |
| S4 — Site tamamen kayıp (DB + disk) | **24 saat** (DB yedeği günlük varsayımıyla) | **≤ 8 saat** | DB restore (**ÖLÇÜLMEDİ**) + medya restore + tutarlılık onarımı |
| S5 — KVKK silme talebinin geri gelmesi | — | — | Yedekten geri gelme **istenmeyen** sonuçtur; §5.3 |

### 3.2 RPO neden 24 saat

`hooks.py` günlük bloğunda `media.backup.run_scheduled` var; `backup.py`
ölçümüne göre günlük değişim ~12 MB. Daha sık snapshot almanın kazancı,
içerik-adresli havuzda zaten sıfıra yakın (değişmeyen dosya yeniden
yazılmıyor); daha seyrek almak bir günden fazla veriyi riske atar. RPO'yu
düşürmek isteniyorsa yol **daha sık snapshot değil**, `storage/mirror.py`
kipine geçmektir (yazma anında ikinci kopya). Ayna kipinde RPO ≈ ayna
kuyruğunun boşalma süresi olur — **ÖLÇÜLMEDİ, çünkü S3 yok** (`s3_enabled=0`).

### 3.3 RTO'nun bileşenleri (S3 senaryosu, ölçülen + tahmin)

| Adım | Süre | Kaynak |
|---|---|---|
| Karar + erişim (insan) | 15–60 dk | ÖLÇÜLMEDİ (organizasyonel) |
| `backup.list_sets()` + `verify(deep=True)` | 981 MB / 1.285 MB/s ≈ **0,8 sn** + I/O | ölçüldü |
| `restore.plan(set_id)` | dosya sayısıyla doğrusal; 4.016 dosyada saniyeler | ÖLÇÜLMEDİ (frappe gerekir) |
| Dosya geri yazma | 981 MB / 706,8 MB/s ≈ **1,4 sn** | ölçüldü (yerel disk) |
| `File` kayıtlarının kurulması | 4.964 satır, satır başına 1 insert/update | ÖLÇÜLMEDİ |
| Doğrulama + smoke test | 15–30 dk | ÖLÇÜLMEDİ |

**Sonuç:** dosya kopyalama RTO'nun **belirleyici bileşeni değil** (saniyeler).
Belirleyici olan insan kararı ve kayıt onarımıdır. Bu yüzden §4'teki runbook
otomasyona değil, **sıraya ve doğrulamaya** yatırım yapar.

---

## 4. Restore runbook

> Tüm komutlar konteyner içinde koşar. Site adı `istoc.localhost`, konteyner
> `istoc-dev-backend-1`. Üretimde site adı ve konteyner değişir.

### 4.0 Ön koşul — “yedeğim var” değil, “yedeğim çalışıyor”

```bash
docker exec istoc-dev-backend-1 bench --site istoc.localhost console
```
```python
from tradehub_core.media import backup
backup.list_sets()          # en yeniden eskiye set listesi
backup.usage()              # {"bytes": ..., "files": ..., "sets": ...}
backup.verify("<set_id>", deep=True)   # ok=True DEĞİLSE bu set kullanılamaz
```

`verify(deep=True)` havuzdaki her içeriğin sha256'sını yeniden hesaplar; sessiz
disk bozulmasını yakalayan tek adım budur. **`ok: False` olan bir setle geri
yükleme başlatma** — bir önceki sete geç.

### 4.1 S1 — Tek dosya kurtarma

```python
from tradehub_core.media import restore
p = restore.plan("<set_id>")
[s for s in p["missing_file"] if s["path"].endswith("abc123.jpg")]   # durumu gör
restore.apply("<set_id>", only=["ab/abc123.jpg"])                    # yalnız o yol
```

`only` listesi manifestteki **`path`** değerleriyle eşleşir; bu yol kapsam
kökünden GÖRELİDİR (`ab/abc123.jpg`), başında `public/` yoktur. Aynı göreli yol
hem public hem private kökte bulunabiliyorsa `only` ikisini de kapsar — nadir
ama mümkün; içerik-adresli adlarda aynı ad = aynı içerik olduğu için zararsız.

`only` verilmezse tüm set uygulanır — tek dosya için bunu yapma.

### 4.2 S2/S3 — Toplu geri yükleme

```python
from tradehub_core.media import restore
p = restore.plan("<set_id>")
{k: p[k] for k in ("ok", "missing_file_count", "conflict_count",
                   "missing_record_count", "extra_count")}
p["schema"]     # yedeğin alındığı andaki sütunlar ile bugünkü şemanın farkı
```

Karar tablosu (`restore.py` modül dokümanı):

| Durum | Anlamı | Varsayılan davranış |
|---|---|---|
| `ok` | Dosya var, içerik yedekle aynı | dokunulmaz |
| `missing_file` | Kayıt/yedek var, disk yok | **geri yazılır** |
| `conflict` | Yol var, içerik farklı | **DOKUNULMAZ** (`overwrite=True` gerekir) |
| `missing_record` | Dosya var, `File` kaydı yok | kayıt yeniden kurulur |
| `extra` | Bugün var, yedekte yok | **DOKUNULMAZ** (yedekten sonra yüklenen dosyalar) |

```python
restore.apply("<set_id>", files=True, records=True, overwrite=False)
```

`overwrite=False` bilinçli varsayılandır: `conflict` çoğu zaman **optimize
edilmiş** dosyadır; eski hâlini geri yazmak sessiz bir gerileme olur. Çatışmalar
tek tek incelenmeden `overwrite=True` verilmemeli.

**Geri yükleme hiçbir koşulda dosya SİLMEZ.** “Yedeğe birebir eşitle” diye bir
mod yoktur ve olmamalıdır.

### 4.3 S3 — Disk tamamen kayıp

1. Yeni diski bağla, `<site>/public/files` ve `<site>/private/files` dizinlerini
   **doğru sahiplik ve izinle** oluştur (`frappe:frappe`, `0755`).
2. Yedek havuzunun (`private/media-backups`) sağlam olduğunu doğrula — havuz
   aynı diskteyse **zaten kaybolmuştur**; bu senaryonun ön koşulu havuzun
   BAŞKA bir cihazda/uzakta olmasıdır (§6.2, bugün karşılanmıyor).
3. §4.0 → §4.2 sırasını uygula.
4. `restore.repair_missing_files()` ile artakalan `missing_file` satırlarını
   süpür.
5. `media_engine` tarafında yetim taraması: `MirrorStorage.reconcile()` (ayna
   kipindeyse) ya da `LocalDiskStorage.iter_keys()` ile DB↔disk karşılaştırması.

### 4.4 S4 — Site tamamen kayıp

```bash
docker exec istoc-dev-backend-1 bench --site istoc.localhost --force restore \
    /home/frappe/frappe-bench/sites/istoc.localhost/private/backups/<dump>.sql.gz
```

Sonra §4.2. **Sıra önemli:** önce DB, sonra medya. Tersi olursa `File`
kayıtları eski şemayla gelir ve `restore.apply(records=True)` bugünkü sütunlara
yazmaya çalışır. Yedekteki `schema.json` künyesi (bkz. `backup.snapshot`) hangi
alanların karşılığı olmadığını söyler; künye okunmadan farklı bir veritabanına
geri yükleme yapılmamalı.

### 4.5 Geri yüklemenin **yapmadığı** iki şey

- **Karantinayı geçersiz kılmaz.** `restore._servis_edilebilir()` AV politikası
  “infected” dediği dosyayı geri yazmaz. Geri yükleme bir güvenlik kararını
  ezemez.
- **Silme talebini geri getirmez** — bkz. §5.3.

---

## 5. Politika kararları

### 5.1 Türevler YEDEKLENMEZ (karar)

**Karar:** yedek yalnız **orijinali** ve `File` kayıtlarını kapsar. Türevler
(`<hash>__<profil>.<ext>`) yedeğe girmez; kayıptan sonra orijinalden yeniden
üretilir.

**Gerekçe, ölçümle:**

| Girdi | Ölçülen | Kaynak |
|---|---|---|
| Bir masterın türev merdiveni | **7 türev / 410,5 KB**, masterın **0,39 katı** | `tests/test_render_regression.py` koşumu, 2026-08-18, 2400×2400 JPEG (1.045,3 KB) |
| Yeniden üretim maliyeti | **17.495 ms / master** (28 encode) | aynı koşum, yerel makine (Pillow, numpy yok) |
| Depolamada kazanç | Türevler yedeklenseydi havuz ~**%39** büyürdü | yukarıdaki orandan |
| Bugünkü türev sayısı | **0** — türev boru hattı üretimde YOK | `docs/standards/retention.md` §5.4 |

Karar ucuz görünüyor çünkü bugün türev yok; **kalıcı** olmasının nedeni oran:
türev, orijinalden **saf fonksiyonla** üretilebilen bir önbellektir
(`retention.schema.json` → `derivative_retention.regenerate_on_demand: true`).
Önbelleği yedeklemek, yeniden üretilebilir veriyi iki kez saklamaktır.

**Bu kararın bedeli, açıkça:** felaket sonrası ilk saatlerde site orijinalleri
servis eder (13,14 MB'lık ürün detay sayfası geri gelir) ve türevler arka planda
yeniden üretilirken **hız gerilemesi yaşanır**. Master başına 17,5 sn ölçüldü;
4.016 master için tek çekirdekte ~19,5 saat, 8 paralel işçide ~2,4 saat
(hesaplandı, ÖLÇÜLMEDİ — paralel koşum denenmedi). Bu süre RTO'ya **dâhil
değildir**: site türevsiz de çalışır.

**Karar ne zaman gözden geçirilir:** `regenerate_on_demand` `false` olursa ya da
bir türev profili el emeğiyle (manuel kırpma/`MediaCropOverride`) üretilirse.
Elle üretilen türev **yeniden üretilemez** ve yedeklenmelidir.

### 5.2 Çöp ve arşiv YEDEKLENİR mi

`backup._media_dirs()` bugün yalnız `public/files` + `private/files` tarıyor;
`media_trash` ve `image_originals` yedeğe **girmiyor**. Bu doğru:

- **Çöp** zaten “silinmek üzere” işaretlenmiş veridir; yedeklemek 30 günlük
  geri alma penceresini yedek ömrü kadar uzatır ve KVKK silme talebini
  sulandırır.
- **Arşiv** (optimizasyon öncesi orijinal) canlı dosyanın eski sürümüdür ve
  kendisi 30 günlük bir geri alma penceresidir; yedeğin yedeği olur.

### 5.3 KVKK: silinen veri yedekten geri GELMEMELİ

Yedek, silme talebinin karşı tarafıdır. Bugünkü mekanizma:

1. Kullanıcı silme talebi → dosya çöpe, `File` kaydında damga.
2. 30 gün sonra `trash.purge_expired` kalıcı siler.
3. **Ama yedek setlerinde blob durmaya devam eder** — `prune(keep=14)`
   çalıştıkça en fazla 14 gün sonra havuzdan da düşer (`_collect_orphan_blobs`).

Yani silinen bir içeriğin yedekten tamamen çıkması **en fazla 14 gün** sürer
(ölçülen sabit: `backup.KEEP_SETS = 14`). Bu pencere KVKK açısından savunulabilir
ama **belgelenmek zorundadır**; silme talebi kaydında “yedeklerden düşme tarihi”
alanı bulunmalıdır. **BUGÜN YOK** — `retention.schema.json`
`legal_hold`/`soft_delete` blokları bu boşluğu işaretliyor.

Ters yön de geçerli: `legal_hold` açıkken hiçbir purge çalışmaz
(`tradehub_core/media/pipeline/storage/retention.py` → `UpstreamPurge._gate`), çünkü
`trash.purge_expired` diskte mtime'a bakar, `File` alanlarını okumaz —
tutulan bir dosyayı silebilir. Ölçüldü: `tabFile` üzerinde **`th_legal_hold`
sütunu YOK**; mevcut 12 `th_*` alanı legal hold içermiyor.

### 5.4 3-2-1 kuralına göre neredeyiz

| Kural | Hedef | Bugün | Boşluk |
|---|---|---|---|
| **3** kopya | orijinal + 2 yedek | **1** (yalnız canlı disk) | 2 kopya eksik |
| **2** farklı ortam | disk + nesne deposu | 1 (yalnız yerel disk) | `s3_enabled=0` |
| **1** kopya dışarıda | başka lokasyon | **0** | uzak hedef yok |

---

## 6. Uygulama sırası (bugünden hedefe)

### 6.1 Adım 1 — Var olanı aç (maliyet: sıfır kod)

1. Zamanlayıcıyı etkinleştir; `is_scheduler_inactive()` **False** olmalı.
2. `backup.run_scheduled` ilk koşumunu **elle** tetikle ve süresini ölç.
3. `backup.verify(<set>, deep=True)` → `ok: True` görülene kadar üretim
   “yedeklidir” denmesin.
4. `Scheduled Job Type.last_execution` üç medya görevi için de dolmalı.

**Kabul ölçütü:** `private/media-backups/sets/` altında en az 2 set, ikisi de
`verify(deep=True).ok == True`.

### 6.2 Adım 2 — Havuzu aynı diskten çıkar

Bugün yedek havuzu korunan veriyle **aynı fiziksel diskte**
(`/dev/vdb1`). Disk kaybı senaryosunda (S3) yedek de kaybolur; yani bugünkü
yapı yalnız “yanlış silme” senaryolarına karşı işe yarar.

Seçenekler ve kararı belirleyen ölçüler:

| Seçenek | Ek maliyet | RPO etkisi | Not |
|---|---|---|---|
| Aynı sunucuda ikinci disk | disk | değişmez | S3 senaryosunu kısmen çözer |
| `storage/mirror.py` + S3 | S3 + trafik | **24 saat → dakikalar** | `s3_enabled=1` gerekir; asenkron kuyruk boşalana kadar RPO yerel disktir |
| `storage/tiered.py` + S3 | S3 (daha ucuz sınıf) | değişmez | Bu bir **maliyet** kipidir, yedeklilik DEĞİL |

> `tiered` kipi DR çözümü **değildir**: tek kopya tutar, yerini değiştirir.
> Soğuk katman versiyonlu bir bucket olmadıkça yedek sayılmaz.

### 6.3 Adım 3 — Geri yüklemeyi tatbik et

Yedek doğrulanmış olsa bile **geri yükleme tatbik edilmeden** RTO bir tahmindir.
Üç ayda bir: rastgele bir set seç, boş bir siteye `restore.apply` uygula, süreyi
ölç, bu belgedeki §3.3 tablosunu **ölçülen** değerlerle güncelle.

---

## 7. Doğrulama komutları (kopyala-çalıştır)

```bash
# 7.1 Zamanlayıcı ve son koşumlar
docker exec -w /home/frappe/frappe-bench/sites istoc-dev-backend-1 ../env/bin/python - <<'PY'
import frappe
frappe.init(site="istoc.localhost"); frappe.connect()
from frappe.utils.scheduler import is_scheduler_inactive
print("scheduler_inactive:", is_scheduler_inactive())
for r in frappe.db.sql("""select method, frequency, stopped, last_execution
    from `tabScheduled Job Type` where method like '%%tradehub_core.media%%'""", as_dict=True):
    print(r)
frappe.destroy()
PY

# 7.2 Disk gerçeği
docker exec istoc-dev-backend-1 sh -c '
S=/home/frappe/frappe-bench/sites/istoc.localhost
du -sh $S/public/files $S/private/files $S/private/backups 2>/dev/null
ls -d $S/private/media-backups $S/private/media_trash $S/private/image_originals 2>&1
df -h $S | tail -1'

# 7.3 Yedek sağlığı (yedek varsa) — `bench console` etkileşimlidir, betikte
# doğrudan frappe.init kullan.
docker exec -w /home/frappe/frappe-bench/sites istoc-dev-backend-1 ../env/bin/python - <<'PY'
import frappe
frappe.init(site="istoc.localhost"); frappe.connect()
from tradehub_core.media import backup
print(backup.usage())
for s in backup.list_sets()[:5]:
    print(s["set_id"], backup.verify(s["set_id"])["ok"])
frappe.destroy()
PY

# 7.4 Geri yükleme hız ölçümü (yalnız ölçüm, veri taşımaz)
docker exec -w /home/frappe/frappe-bench/sites istoc-dev-backend-1 ../env/bin/python /home/frappe/olcum/olcum_dr2.py
```

---

## 8. Bu planın bilinen boşlukları

1. **Üretimde hiçbir şey ölçülmedi.** Tüm sayılar geliştirme konteynerinden.
2. **DB restore süresi ÖLÇÜLMEDİ** — S4 RTO'sunun en büyük bilinmeyeni.
3. **Ayna kuyruğu boşalma süresi ÖLÇÜLMEDİ** — S3 olmadığı için ölçülemez;
   `s3_enabled=1` olduğu gün ilk ölçülmesi gereken sayı budur.
4. **Türev yeniden üretiminin paralel süresi hesaplandı, ölçülmedi** (§5.1).
5. **DB kaydı ile disk arasındaki fark** (§1) ölçüldü ama **nedeni bulunmadı**;
   DR planı bu farkı `restore.plan()` raporuna havale ediyor, çözmüyor.
6. **`th_legal_hold` alanı yok** — yasal saklama kapısı bugün uygulanamaz
   durumda; `FrappeLegalHold.enforceable` konteynerde `False` ölçüldü.
7. **Yedeğin şifrelenmesi ele alınmadı.** Havuzda private medya (KYB/KYC
   belgeleri, 325 dosya / ~165 MB) düz duruyor; havuz sunucu dışına çıkarılacaksa
   şifreleme ayrı bir karar olarak alınmalı.

---

## 9. Bu belgeyi yazarken okunan kod

- `tradehub_core/media/backup.py` — snapshot / verify / prune / run_scheduled, `KEEP_SETS=14`
- `tradehub_core/media/restore.py` — plan / apply / repair_missing_files, beş durum sınıfı
- `tradehub_core/media/backup_export.py` — `KEEP_HOURS=48` dışa aktarma penceresi
- `tradehub_core/media/trash.py` — `TRASH_RETENTION_DAYS=30`, `purge_expired`
- `tradehub_core/media/archive.py` — `ARCHIVE_RETENTION_DAYS=30`
- `tradehub_core/hooks.py` — günlük blok sırası (arşiv → çöp → yedek)
- `tradehub_core/media/pipeline/policy/retention.schema.json` — saklama şeması, varsayılanlar
- `tradehub_core/media/pipeline/storage/retention.py` — bu fazda yazılan politika uygulaması
- `tradehub_core/media/pipeline/storage/{mirror,tiered,s3,local}.py` — depolama kipleri
- `docs/standards/retention.md` — §4.4, §5.2, §5.3, §5.4, §6.3, §9

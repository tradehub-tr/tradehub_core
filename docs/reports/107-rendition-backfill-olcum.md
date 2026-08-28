# 107 — Rendition backfill + A-sınıfı migration ölçümü (gece koşusu)

**Tarih:** 2026-08-27
**Ortam:** `istoc-dev-backend-1`, site `istoc.localhost` (yerel dev, prod'dan restore edilmiş veri).
**Kapsam:** Dün gece koşulan (1) katalog türev tohumlaması (`pipeline_bridge.enqueue_catalog_backfill`
→ `product.image` merdiveni) ve (2) A-sınıfı eski-motor `Media Migration Run`
(`mig-f82808559d584a01c171`) koşumunun **gerçek, sorgu-tabanlı** envanteri. Sayfa
bazlı yeniden ölçüm (T-124 tarzı) bu dilimin kapsamı dışında — yalnız envanter.

İki kök neden düzeltmesi bu koşudan önce yapılmıştı (`pipeline_bridge.py`
`_catalog_backfill_candidates` docstring'i, satır 980-1023):

1. **Aday sorgusu içerik-hash eşleşmesi** — yalnız `source_file` ile eşlemek yerine
   `content_sha256` (dosya adının gövdesi) üzerinden de eşleşme; aynı içeriğin
   başka bir `File` satırından açılmış asset'ini görmeyen sorgu backfill'i
   2.748 adayda platoya oturtuyordu.
2. **JPEG-şartının kaldırılması (sınıf-farkında)** — grafik/şeffaf sınıfı
   lossless WEBP+PNG zinciri alıyor, JPEG hiç plana girmiyor; jpeg-şartlı eski
   sorgu 232 ready-ama-JPEG'siz asset'i sonsuza dek aday sayıyordu.

---

## 1. Koşu özeti — gerçek sorgu çıktıları

### 1.1 `pipeline_bridge.rendition_backfill_status()`

```
{'total': 3130, 'ready': 3116, 'missing': 14, 'queue_depth': 0,
 'success': 2005, 'failed': 0, 'running': 0, 'queued_jobs': 0}
```

`missing=14`, **`tabFile` satırı** bazında sayılıyor (bkz. §5) — aynı görsel
içeriğin birden çok `File` kaydına yüklenmiş olması nedeniyle 14 satır, **5
farklı adrese** düşüyor (`_catalog_backfill_candidates` distinct URL döner).

### 1.2 Media Asset — state dağılımı

| state | adet |
|---|---:|
| ready | 2.020 |
| draft | 9 |
| **toplam** | **2.029** |

`product.image` slotunda `ready` asset: **2.010**.

### 1.3 Media Rendition — format dağılımı + bayt

Tüm slotlar:

| format | adet | toplam bayt | MiB |
|---|---:|---:|---:|
| webp | 10.364 | 295.235.038 | 281,55 |
| jpeg | 6.398 | 177.964.774 | 169,72 |
| avif | 4.130 | 138.437.857 | 132,03 |
| mp4 (video) | 3 | 9.781.097 | 9,33 |
| m3u8 (HLS manifest) | 1 | 15.205.198 | 14,50 |
| **toplam** | **20.896** | **636.623.964** | **607,14** |

Yalnız `product.image` slotu (katalog vitrin merdiveni):

| format | adet | toplam bayt | MiB |
|---|---:|---:|---:|
| webp | 10.350 | 295.154.936 | 281,47 |
| jpeg | 6.398 | 177.964.774 | 169,72 |
| avif | 4.130 | 138.437.857 | 132,03 |
| **toplam** | **20.878** | **611.557.567** | **583,24** |

Ölçülmüş: tüm `jpeg` ve `avif` türevleri `product.image` slotuna ait (sıfır
sapma); `webp`'te 80.102 bayt (14 satır) diğer slotlara (video poster / test
slotları) düşüyor.

### 1.4 Migration koşumu — `mig-f82808559d584a01c171`

`migration_runtime.status("mig-f82808559d584a01c171")` özeti:

| Alan | Değer |
|---|---:|
| status | **validated** |
| dry_run | `false` (gerçek koşum) |
| approved_dry_run | `mig-e3c804e4c9bca40876e4` |
| preset | balanced |
| total_files / processed | 48 / 48 |
| optimized / skipped / errors | 44 / 4 / **0** |
| original_bytes | 31.367.453 (29,92 MiB) |
| new_bytes | 14.755.896 (14,07 MiB) |
| tasarruf | 16.611.557 bayt — **%52,96** |
| preflight_ok / validation_ok | `true` / `true` |
| başlangıç | 2026-08-27 01:05:24.056 |
| bitiş | 2026-08-27 01:05:31.059 (≈ 7 sn, tek batch) |
| doğrulama | 2026-08-27 01:05:31.134 |
| rollback_deadline | 2026-09-26 01:05:24 (30 gün) |

`Media Migration Run` doc'undan doğrudan okunan alanlar (`status`, `total_files`,
`processed`, `optimized`, `skipped`, `errors`, `original_bytes`, `new_bytes`,
`started_at`, `finished_at`, `validated_at`) yukarıdaki tabloyla birebir aynı —
`status()` fonksiyonu ile doc alanları arasında sapma yok. 4 `skipped` dosya
`already_optimized` gibi bir gate nedeniyle (bkz. rapor 98) atlanmış, hata değil.

---

## 2. Önce/sonra tablo

"Önce" durumu **yeniden üretildi** (zaman makinesi yok): `Media Rendition.creation
< 2026-08-26 00:00:00` kesimiyle aynı `NOT EXISTS` mantığı tekrar koşuldu — yani
"bir katalog dosyası, o kesimden ÖNCE üretilmiş bir `ready` rendition'a sahip
miydi" sorusu.

| Ölçü | Önce (kesim: 26 Ağu 00:00) | Sonra (27 Ağu, şimdi) |
|---|---:|---:|
| Toplam vitrin görseli (`product.image` katalog, `File` satırı) | 3.130 | 3.130 (değişmez) |
| **Ready** | **66** | **3.116** |
| **Missing** | **3.064** | **14** (5 farklı adres) |
| Toplam `Media Rendition` (tüm slotlar) | 531 | 20.896 |
| Bunlardan `product.image` | 513 | 20.878 |
| Başarılı rendition job'ı (`job_type=rendition`, tüm slotlar) | 69 | 2.005 |
| A-sınıfı migration koşumu | koşulmamış | **validated**, 48/48, 0 hata |

**Not — kaynak metnindeki "ready 0" ile fark:** görev bağlamı gece başı için
"ready 0" varsayıyordu; gerçek sorgu **66** buluyor (531 önceki rendition'ın
513'ü zaten `product.image` slotunda ve bunların bir kısmı zaten "ready"
File'lara karşılık geliyordu — muhtemelen T-124/W9 döneminden kalma kısmi
üretim). "531 toplam rendition, çoğu diğer slotlarda" iddiası ise **doğrulandı**:
531'in 513'ü zaten `product.image`, kalan 18'i `product.video` (6) + test
slotları (12).

**Kazanç:** missing 3.064 → 14, yani **%99,54 azalma** (File satırı bazında).
Farklı-adres (distinct URL) bazında bakarsak 3.130 aday adresten yalnız
**5'i** hâlâ merdivensiz — **%99,84** çözüm oranı. T-124 kabul kriteri (ürün
sayfası başına ≥%98 bayt kazancı, "< 2 MB") bu dilimde **yeniden ölçülmedi**;
burada yalnızca envanter/kapsam tamamlanma oranı raporlanıyor.

---

## 3. HTTP kanıtı

Görünür ilan: **`LST-00206`** (`storefront_visible=1`, `primary_image` `/files/`
ile başlıyor). `media_manifest.get_manifest(listing="LST-00206",
slot="product.image")` (misafir, `allow_guest=True`) döndürdü: `enabled: true`,
2 görsel, her ikisi de `avif`+`webp` merdiveni + `sources[]` bloğu dolu.

Seçilen `srcset` adresi:

```
/files/media/s2oubr540l/a2e4d0ccb33855cf8c5d776409a37855480b06608b1f65b1064e4c2017cfff94/w384-384.avif
```

Diskte doğrulama (konteyner içi): `30.514` bayt, dosya mevcut.

`curl -sI` (nginx gateway, `Host: istoc.localhost`, port 8080 **ve** backend
port 8001 — ikisi de aynı sonucu verdi):

```
HTTP/1.1 200 OK
Content-Type: image/avif
Content-Length: 30514
Cache-Control: public, max-age=31536000, immutable
```

`Content-Length` diskteki bayt sayısıyla **birebir** eşleşiyor — manifest,
disk ve HTTP üçü aynı kanıtı veriyor.

---

## 4. Bilinen artıklar

### 4.1 Kalan 5 inatçı aday (14 `File` satırı → 5 farklı adres)

| Adres | Kaç `File` satırı | Durum |
|---|---:|---|
| `/files/10/10ca6ca5fdfadcdfe2572d8f0c7a7829.webp` | 2 | Asset yok (ne `source_file` ne `content_sha256` eşleşiyor) — iş hiç açılmadan sessizce kapsam dışı |
| `/files/2c/2c810daeaea66b3f7b283b461df7d511.jpg` | 2 | **Asset VAR** (`anh41gmn1h`, state=`ready`, slot=`product.image`) ama bağlı **0 Media Rendition** satırı — yetim "ready" kaydı; backfill sorgusu doğru şekilde eksik sayıyor |
| `/files/e1/e12f1d94fbf9ed051e8df3081a17fd3e.png` | 4 | Asset yok |
| `/files/ae/aef2cb71316c5a92a5f8677cd4ec231b.jpg` | 3 | Asset yok |
| `/files/af/af21488c308e6ed40d31595094016705.png` | 3 | Asset yok |

4/5 adreste hiç `Media Asset` açılmamış — `_resolve_scope` kapısından hiç
geçmemiş (muhtemelen slot çözülemeyen eski/import edilmiş `File` kayıtları,
rapor kapsamında kök neden araştırılmadı). 1/5 adreste (`2c810d...`) asset var
ama rendition'sız — muhtemelen eski bir üretim denemesinin `state` alanı
`ready`'e set edilip rendition satırları hiç yazılmamış ya da sonradan
silinmiş; bu, `enqueue_catalog_backfill(force=True)` çağrıldığında worker'ın
`_renditions_exist()` kontrolünü geçip yeniden üretime girmesi gereken bir
durum — bir sonraki backfill turunda otomatik düzelmesi beklenir (görev
kapsamında elle müdahale edilmedi).

### 4.2 9 draft Media Asset

| slot_key | adet | not |
|---|---:|---|
| `library.upload` | 7 | 2026-08-20/22 tarihli, katalog backfill'inden ÖNCE oluşmuş test/fixture kayıtları |
| `product.image` | 1 | `content_sha256="aaaa…aaaa"` — açıkça sahte/test fixture'ı, gerçek dosya değil |
| `boyle.bir.slot.yok` | 1 | Var olmayan bir slot adıyla oluşturulmuş test kaydı |

Hepsi dün geceki koşudan önce (2026-08-20/22) oluşmuş; katalog backfill'inin
kapsamına hiç girmiyorlar (gerçek `product.image` katalog sorgusu `File` +
`Listing`/`Listing Image` join'inden geçiyor, bu draft'lar o join'e düşmüyor).
Aksiyon önerilmiyor — bilinen, zararsız test artığı olarak not düşülüyor.

---

## 5. Öz-denetim

- Bu raporun **tüm sayıları** yukarıdaki `mariadb`/`frappe` sorgularının
  gerçek çıktısıdır; tahmini/yuvarlanmış değer yok. Ölçüm, `docker exec
  istoc-dev-backend-1 bash -c "... bench --site istoc.localhost console"`
  üzerinden `docker cp` ile taşınan tek seferlik script'lerle yapıldı
  (çok satırlı döngüler console stdin pipe'ında bozulduğu için `exec(open(...).
  read(), {})` deseni kullanıldı — rapor 106/98'deki aynı kısıt).
- "Önce" satırı **gerçek geçmiş bir ölçüm değil**, `creation` zaman damgası
  kesimiyle **yeniden üretilmiş** bir sorgu sonucudur — bu açıkça işaretlendi
  (§2), tahmin/varsayım olarak sunulmadı.
- Görev bağlamındaki "ready 0" varsayımı ile gerçek ölçüm (**66**) arasındaki
  fark saklanmadı, §2'de açıkça raporlandı.
- `missing=14` (backfill_status) ile "5 inatçı aday" (candidate URL sayısı)
  arasındaki fark araştırıldı ve kök nedeni (aynı içeriğin birden çok `File`
  satırına yüklenmesi) doğrulandı (§4.1) — sessizce göz ardı edilmedi.
- HTTP kanıtı üç bağımsız kaynaktan (manifest JSON, disk `stat`, `curl -I`)
  çapraz doğrulandı; üçü de aynı bayt sayısını (`30.514`) veriyor.
- Sayfa bazlı önce/sonra bayt kazancı (T-124 tarzı, `< 2 MB` kabul kriteri)
  bu dilimde **kasıtlı olarak yeniden ölçülmedi** — görev tanımı yalnızca
  envanter istiyordu; bu sınır §2 sonunda açıkça belirtildi.
- **Yazma yapılmadı:** ölçüm boyunca yalnız `SELECT` / `get_all` / `get_doc`
  / `status()` (salt okunur) çağrıldı; DB'ye tek bir `INSERT`/`UPDATE`
  gönderilmedi, `git add`/commit atılmadı.

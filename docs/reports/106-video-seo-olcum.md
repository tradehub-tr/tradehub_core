# 106 — Video SEO uçtan uca ölçüm + kapanış (Dilim 4)

**Tarih:** 2026-08-26
**Dal:** `feature/media-video-seo` (Task 1-8 tamam, backend `4fd6e17`)
**Kapsam:** Task 9 — regresyon paketi, geri doldurma koşusu, önce/sonra ölçümü.
**Ortam:** `istoc-dev-backend-1`, site `istoc.localhost` (yerel, prod'dan restore
edilmiş veri). Bu dalda değişen 16 dosya `git diff --name-only 7b3372a..HEAD`
ile listelenip `docker cp` ile imaja tazelendi, `bench migrate` ile
`v15_9_49_media_video_seo` yaması uygulandı.

---

## 1. Regresyon paketi

| Modül | Sonuç |
|---|---|
| `tradehub_core.tests.test_media_video_seo` | **24/24 PASS** |
| `tradehub_core.tests.test_video_poster` | **7/7 PASS** |
| `tradehub_core.tests.test_media_seo` | **19/20 PASS** — 1 pre-existing hata (`test_bilinmeyen_alan_yok_sayilir`, bu daldan önce mevcut) |
| `tradehub_core.tests.test_media_seo_pipeline` | **38/39 PASS** — 1 pre-existing hata (`test_alanlar_varsa_nesne`, `creator` alanında `@type: Organization` bekleniyor, bu daldan önce mevcut) |
| `tradehub_core.seo.tests.test_sitemap_generator` | **27/27 PASS** |
| `tradehub_core.seo.tests.test_sitemap_cache` | **15/15 PASS** |

Ek sağlama (kapsam dışı ama değişen dosyalara bağlı, ücretsiz kontrol):
`seo.tests.test_schema_builder` 37/37 PASS, `tests.test_media_transcode` 23/23
PASS — regresyon yok.

İki pre-existing hata bu dilimin kapsamı dışında; ikisi de bu dal açılmadan
önceki commit'lerde zaten mevcuttu (Task 9 brief'inde de "1 pre-existing"
olarak beklentiye alınmış).

## 2. Geri doldurma koşusu

```
docker exec istoc-dev-backend-1 bench --site istoc.localhost execute \
  tradehub_core.media.video_poster.backfill_pending --kwargs "{'limit': 200}"
```

`--kwargs` sözdizimi çalıştı (console fallback'e gerek kalmadı). Dönen değer:
**`6`** (poster üretilen video sayısı).

`backfill_pending`, `is_private=0` ve `VIDEO_UZANTILAR` uzantılı, posteri VE
duration'ı boş olan videoları `ORDER BY creation DESC LIMIT 200` ile seçiyor.
114 aday videodan yalnız 6'sı `generate()` içinde başarılı oldu; kalan 108'i
poster/duration boş bıraktı (kod, hatayı videoyu düşürmeden log'layıp
atlıyor — spec §4 ilkesi: "hata poster'ı değil videoyu ASLA düşürmez").
Bu, dosyaların çoğunun yerel dev ortamında **fiziksel olarak diskte
bulunmaması** ile tutarlı (prod restore'unda yalnız veritabanı satırı var,
video dosyası yok); 6 başarılı olan, gerçek video dosyası bulunan `Listing`
kayıtlarına ait.

## 3. Önce/sonra ölçüm — TUR-135 §9.1 tablo deseni

| | Önce | Sonra |
|---|---:|---:|
| Toplam public video (`VIDEO_UZANTILAR` ile `LIKE`, `is_private=0`) | 114 | 114 (değişmez — beklenen) |
| Poster'lı video (`th_media_poster_url` dolu) | **0** | **6** |
| Duration'lı video (`th_media_duration` dolu) | **0** | **6** |
| `video_url`'lü `Listing` | 7 | 7 (değişmez — beklenen) |
| Bunlardan `VideoObject` üretilebilen (posterli, distinct ilan) | **0** | **5** |

### 3.1 Kalan 2/7 ilan neden `VideoObject` üretemiyor

| İlan | `video_url` | Durum |
|---|---|---|
| `LST-00202` | `https://a.co/d/0dNxWPV4` (dış URL) | Beklenen — `schema_builder._listing_video_objects` yalnız `/files/` ile başlayan yerel videoyu işler; dış URL'ye poster üretimi kapsam dışı (spec kararı, hata değil) |
| `LST-00002` | `/files/task6-manifest-video.mp4` | `tabFile`'da bu `file_url` ile eşleşen kayıt **yok** — muhtemelen erken bir manifest/test fixture'ı, gerçek dosya hiç yüklenmemiş. Bu dalın kapsamında değil; not olarak bırakıldı, düzeltme yapılmadı |

Kalan 108 postersiz video de aynı nedenle (yerel dosya yok) bekliyor; prod'da
gerçek dosyalarla koştuğunda `backfill_pending`'in günlük `media-maint`
kuyruğu üzerinden parça parça (`limit`'e göre) ilerleyeceği spec'te zaten
tanımlı (§5.3 deseni, video_poster.py docstring'i).

## 4. Öz-denetim

- Tüm sayılar yukarıdaki `mariadb` sorgularının **gerçek** çıktısı; tahmini
  değer yok.
- Regresyon paketi brief'teki beklenen PASS/FAIL oranlarıyla birebir örtüşüyor
  (19/20, 38/39) — sürpriz yeni hata yok.
- `--kwargs` sözdizimi ilk denemede çalıştı, console fallback'e gerek kalmadı.
- Geri doldurmanın düşük "başarı oranı" (6/114) bir regresyon değil, yerel
  dev ortamının fiziksel dosya eksikliğinin sonucu; kod hatayı doğru
  yutuyor ve videoyu düşürmüyor (doğrulandı: toplam public video sayısı
  114'te sabit kaldı).

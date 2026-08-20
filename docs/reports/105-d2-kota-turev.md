# 105-D2 — Kota hesabına türev baytlarını ekle (ADR-0022)

**Tarih:** 2026-08-20
**Karar:** ADR-0022 — satıcının depolama kotası artık türev (`Media Rendition`)
baytlarını da sayar; gerçek disk kullanımını yansıtsın diye.
**Kapsam (sahiplik):** backend kota fonksiyonu (`media/files.py`) + kendi testleri.
**Dokunulmadı:** hooks/patches, frontend (gereken satır raporlandı — değişiklik
GEREKMEDİ), `docker/`, `pipeline_bridge.py` / `media_manifest.py` mantığı.

---

## 1. ÖNCE ölçüm — kota bugün nasıl hesaplanıyor?

**Kota hesabının tek kaynağı:** `tradehub_core/media/files.py::storage_usage(store)`.

İki tüketici bu fonksiyonun `bytes` alanını okuyor:

| Tüketici | Yol | Amaç |
|---|---|---|
| Enforcement | `entitlement/checks.py::check_media_storage_quota` (`File.before_insert`) → `files.storage_usage(store)["bytes"]` | yükleme reddi |
| FE göstergesi | `api/seller_media.py::get_my_summary` → `depolama["bytes"]` → `stores/media.js` `loadSummary` → `MediaFilterRail.vue` kullanım çubuğu | %'lik doluluk |

**Ölçülen sorun:** `storage_usage` yalnızca satıcının yüklediği **orijinalleri**
sayıyordu:

```sql
select max(file_size) ... from tabFile
where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
  and owner in (mağazanın kullanıcıları)   -- File.owner zinciri
group by file_url                            -- url bazında tekilleştirme
```

Türevler (`Media Rendition`) sistemin ürettiği küçültülmüş kopyalar; **ayrı bir
`File` kaydı AÇMIYORLAR** (içerik-adresli, `dedup.rendition_path`). Bu yüzden
yukarıdaki `tabFile` sorgusunda hiç görünmüyor, kotaya hiç girmiyorlardı.

**Türev zinciri (mağazaya bağlanış):**
`Media Rendition.asset` → `Media Asset.name`, `Media Asset.owner_seller = store`.
Türev baytı `Media Rendition.bytes` alanında.

Canlı DB'de (istoc.localhost) ölçülen türev dağılımı — 490 rendition, 54 asset:

| owner_seller | türev adedi | türev bayt |
|---|---:|---:|
| SEL-00003 | 14 | 25.025.870 |
| SEL-00036 | 356 | 5.155.267 |
| DEMO-001 | 36 | 590.131 |
| SEL-00020 | 12 | 545.062 |
| … | | |

---

## 2. Değişiklik

`media/files.py`:

1. **Yeni `rendition_usage(store) -> int`** — satıcının türev baytlarını **TEK
   toplu `frappe.qb` agregatıyla** toplar (N+1 YOK):

   ```python
   SUM(Media Rendition.bytes)
   FROM Media Rendition
   INNER JOIN Media Asset ON Rendition.asset = Asset.name
   WHERE Asset.owner_seller = store     # ← kiracı kemeri
   ```

2. **`storage_usage` güncellendi** — `bytes` artık **orijinal + türev
   TOPLAMI**. Dökümü de dönülüyor:
   - `bytes` (geriye dönük): toplam — enforcement ve FE aynı alanı okuyor.
   - `original_bytes`: yalnız orijinaller (eski `bytes`).
   - `rendition_bytes`: yalnız türevler.
   - `files`: orijinal dosya sayacı — türevler bu sayacı ŞİŞİRMEZ.

   `users_of(store)` boş olsa bile (mağazanın hiç kullanıcısı çözülemese)
   türevler ayrıca sayılıyor — türevler `File.owner`'a değil
   `Media Asset.owner_seller`'a bağlı.

Diğer dosyaya dokunulmadı: enforcement (`checks.py`) ve FE otomatik yeni toplamı
okur.

---

## 3. FE kota göstergesi — değişiklik GEREKMEDİ

`admin-panel/frontend/src/stores/media.js:163`:

```js
storage.value = { bytes: o.bytes || 0, quotaBytes: o.quota_bytes ?? null };
```

`MediaFilterRail.vue:376` `storagePercent = usedBytes / quotaBytes`
(`usedBytes` ← `storage.bytes`). Backend `bytes` alanı artık toplamı taşıdığı
için **kullanım çubuğu ve yüzde otomatik olarak yeni toplamı gösterir.** FE
sahiplik dışında; tek satır bile değişmedi.

---

## 4. ÖNCE / SONRA — gerçek sayılar (istoc.localhost)

`files.storage_usage(store)` gerçek fonksiyon, konteynerde çalıştırıldı:

| Mağaza | ÖNCE `bytes` (yalnız orijinal) | türev bayt | SONRA `bytes` (orijinal+türev) | fark |
|---|---:|---:|---:|---:|
| SEL-00003 | 11.484.783 | 25.025.870 | **36.510.653** | +25.025.870 (+217,9%) |
| SEL-00036 | 59.562.800 | 5.155.267 | **64.718.067** | +5.155.267 |
| DEMO-001 | 3.812.812 | 590.131 | **4.402.943** | +590.131 |
| SEL-00099 (türevsiz) | 0 | 0 | **0** | 0 — değişmez |

Türevi olan satıcıda fark görünüyor; türevi olmayanda tıpatıp aynı.

---

## 5. Testler — `tradehub_core/tests/test_media_quota_renditions.py`

Yeni bench testi (gerçek DB, `FrappeTestCase`, otomatik rollback). Mevcut
saf-Python `test_media_quota.py` (10 test) korundu ve hâlâ yeşil.

```
docker exec istoc-dev-backend-1 bench --site istoc.localhost \
    run-tests --module tradehub_core.tests.test_media_quota_renditions
→ Ran 3 tests ... OK
```

1. `test_kota_turev_baytlarini_icerir` — `bytes == original_bytes + türev`;
   türev satırları `files` sayacını şişirmez.
2. `test_turevi_olmayan_satici_degismez` — türevsiz mağazada
   `bytes == original_bytes`.
3. `test_tenant_a_kotasi_b_turevleriyle_sismez` — A'nın kotası B'nin
   türevleriyle şişmez.

**Tenant VACUITY (zorunlu kanıt):** `rendition_usage` içindeki
`.where(Asset.owner_seller == store)` filtresi gevşetilince (konteyner
kopyasında geçici olarak `Asset.name == Asset.name`'e çevrildi) 3 test de
KIRMIZIYA döndü — A'nın `rendition_usage`'ı DB'deki TÜM türevleri (32.306.127
bayt) saydı:

```
FAIL: test_tenant_a_kotasi_b_turevleriyle_sismez
  AssertionError: 32306127 != 0
```

Filtre geri alındıktan sonra tekrar 3/3 yeşil. Filtrenin gerçekten iş yaptığı
kanıtlandı (vacuity guard).

---

## 6. Mimari çelişki + GC senkronu

**Çelişki:** Türevler `File` açmadığı için "kota = gerçek disk" ilişkisi, kota
kodunun `Media Rendition.bytes`'ı ayrı bir zincirden (asset → owner_seller)
toplamasına bağlı. Orijinaller `File.owner`'dan, türevler
`Media Asset.owner_seller`'dan geliyor — iki ayrı sahiplik yolu tek toplamda
birleşiyor.

**GC senkronu — ÖLÇÜLDÜ, senkron:** Kota **saklanan sayaç değil, okuma anında
canlı `SUM`**. GC (`retention.py::_apply_derivative`) türevi silerken
`frappe.delete_doc("Media Rendition", ...)` ile **DB kaydını da** siliyor
(yalnız diski değil). Dolayısıyla türev silinince sonraki okumada kotadan
kendiliğinden düşer — drift eden bir sayaç yok.

Konteynerde doğrulandı (silme rollback'lendi):

```
store=SEL-00003 before=25.025.870 deleted_bytes=9.622.536
                after=15.403.334  drop=9.622.536  → SYNC_OK
```

Türev silinince kota tam da o türevin baytı kadar düştü.

**Kalan nüans (bilgi, açık değil):** Enforcement kapısında `check_media_storage_
quota` "mevcut (orijinal+türev) + gelen ORİJİNAL" hesaplıyor; yeni yüklenen
dosyanın türevleri o an henüz üretilmediği için (async, transcode/pipeline
sonrası) yükleme anında sayılmıyor. Bu türevler üretildikten sonra ilk okumada
kotaya girer — canlı `SUM` olduğu için kendiliğinden düzelir. Kabul edilebilir;
yükleme anında türev baytını tahmin etmek gerekmiyor.

---

## 7. Doğrulama komutları

```bash
# Testler
docker exec istoc-dev-backend-1 bench --site istoc.localhost \
    run-tests --module tradehub_core.tests.test_media_quota_renditions   # 3/3 OK
docker exec istoc-dev-backend-1 bench --site istoc.localhost \
    run-tests --module tradehub_core.tests.test_media_quota               # 10/10 OK (regresyon yok)

# py_compile — PY_COMPILE_OK
```

**Not:** `ruff` bu konteynerde/ortamda kurulu değil; `py_compile` ile derleme
doğrulandı. Ruff lint/format ayrı ortamda koşturulmalı (tab indent + line-length
110 kuralına uygun yazıldı).

# 100 · K-2 — `Media Asset.active_version` atomik yazarı + rollback

**Tarih:** 2026-08-20
**Kapsam:** T-042 / INV-08 · Rapor 40 §7.3 · Rapor 50 (Faz 6) T-064 madde 3
**Sahiplik:** `doctype/media_version/**`, `version_enrichment_for_assets` (okuma yolu), `pipeline_bridge.py` tek çağrı EK'i, yeni test modülü.

---

## 1. Sorun (ölçülmüş durum)

Şema göçmüştü ama **yazan üretim kodu yoktu**:

- `Media Version` DocType + `is_active` kolonu ve `Media Asset.active_version`
  kolonu kuruldu (patch `v15_9_29_media_version`, `v15_9_30_media_asset_active_version`).
- Docstring'deki 3-cümlelik atomik geçiş (`media_version.py:16-20`) yalnız
  **tasarımdı**; çalıştıran Python yoktu. `_validate_active_consistency` (~:98)
  sadece OKUR/doğrular.
- `migration/backfill.py::rollback` (~:465) yalnız in-memory rafı boşaltır,
  `active_version`'a dokunmaz (kapsam dışı, BE dalgası orada — dokunulmadı).
- **Doğrulama (grep, değişiklikten önce):** `active_version`'ı YAZAN tek kod
  şema patch'iydi (`v15_9_30`); `_validate_active_consistency` dahil geri kalan
  her nokta yalnız OKUYORDU. Yani boru hattı ürettiği HİÇBİR varlığa
  `active_version` yazmıyordu → alan tüm gerçek veride NULL.
- Sonuç: okuma yolu (`version_enrichment_for_assets`) `is_active desc, creation
  desc` ile en yeniye düşerek eksikliği **maskeliyordu** (is_active hep 0 →
  pratikte `creation desc` = en yeni).

## 2. Yapılan

### 2.1 Atomik yazar — `promote_version(asset, version, *, commit=True)`
`doctype/media_version/media_version.py` (okuma yolu + tutarlılık kapısı ile
aynı dosya; çekirdek `pipeline/core/` bilinçli frappe'siz, transaction gerektiren
yazar oraya konamaz).

Protokol (docstring'in kodu, INV-08):
1. **Doğrula:** sürüm var → `asset`e ait → varlık `ready` (servis edilebilir).
2. **Atomik geçiş** (`_write_active_version_atomic`), TEK transaction, arada
   commit YOK:
   `eski is_active=0` → `Media Asset.active_version = version` → `yeni is_active=1`.
3. **Tutarlılık** (`_assert_active_consistent`): TAM bir aktif + o da
   `active_version`, ve controller'ın kendi `_validate_active_consistency`'si de
   çağrılır (sözleşmenin tek kaynağı atlanmıyor, doğrulanıyor).
4. **Denetim izi** aynı transaction'da yazılır → yayınlanmış her geçişin izi de
   yayınlanır.

"Geçiş sırasında eski sürüm erişilebilir kalır": üç yazma tek transaction'da,
tek commit ile kalıcı olur → başka bağlantıdaki okuma yolu ya öncekini ya
sonrakini görür, yarı-durumu (sıfır/çift aktif) asla. Türev baytları
`version_hash` taşıyan ayrı adreslerde (INV-09) durduğu için geçiş boyunca
yerinde kalır.

### 2.2 `rollback_version(asset, *, commit=True)`
Önceki yayına döner. Hedef DB'den tek başına çıkarılamaz (sürümler silinmez,
"hangi is_active=0 bir önceki aktifti" bilgisini yalnız yayın geçmişi taşır);
bu yüzden en son promote/rollback **denetim** kaydının `from` alanından okunur.
Promote/rollback izi geçişle aynı transaction'da commit'lendiği için
yayınlanmış geçişlerin izi güvenilir. Geçmiş yoksa/hedef artık bu varlığa ait
değilse `frappe.throw`.

### 2.3 Denetim eylemleri
`media/audit.py`'nin `media.<eylem>` desenini izleyen iki sabit **kendi
modülümde** tanımlandı (audit.py sahiplik dışı):
`ACTION_VERSION_PROMOTE = "media.version_promote"`,
`ACTION_VERSION_ROLLBACK = "media.version_rollback"`. Kayıt `log_decision` ile
ADL'ye, `object_doctype="Media Asset"`, `context={"from":…, "to":…}`,
`tenant=owner_seller`.
> **Not (panel görünürlüğü):** Bu iki eylem `audit.MEDIA_ACTIONS` listesinde
> DEĞİL (o liste audit.py'de, sahiplik dışı). Panelin medya-denetim ekranı
> `MEDIA_ACTIONS` ile süzdüğü için promote/rollback kayıtları ADL'ye YAZILIR
> ama o ekranda görünmez — `media.storage_settings_changed` ile aynı bilinen
> durum (audit.py:86-95). İstenirse audit sahibinin bu iki sabiti
> `MEDIA_ACTIONS`'a eklemesi yeterli; işlevsel bir engel değil.

### 2.4 Okuma yolu — `version_enrichment_for_assets`
Artık `active_version` DOLUYSA **yalnız** o sürüm kabul edilir (daha yeni bir
sürüm bile maskeleyemez); BOŞSA bugünkü `is_active desc, creation desc` fallback
korunur (geriye uyum — `active_version` yazmayan eski varlıklar). İki sorgu:
önce asset→active_version haritası, sonra tek sürüm sorgusu. Bu, "en yeni
maskeleme"yi gerçek aktif-sürüm seçimine çevirir.

### 2.5 Boru hattı köprüsü — item 5 ölçümü + tek-satır EK
**Ölçüm:** Değişiklikten önce NE görsel (`_ensure_version`) NE video
(`_ensure_video_version`) `active_version` yazıyordu; ikisi de sürümü
`is_active=0` açıp bırakıyordu. Yani gap yalnız videoda değil, **her iki**
zincirdeydi ve `active_version` özelliği tüm boru-hattı verisinde atıldı.

**EK (mevcut mantığı bozmadan):** İlk `ready` geçişinde `_promote_initial_version`
çağrısı eklendi (görsel + video, simetrik). YALNIZ `active_version` boşken
promote eder → **ilk yayın** otomatik, **yeniden işleme** (reprocess,
`active_version` zaten dolu) moderasyona bırakılır, ona dokunulmaz. Böylece
"hangi sürüm yayında bir moderasyon kararıdır" ilkesi korunur; yalnız "hiç
yazılmıyordu" boşluğu kapanır. `commit=False` — köprü job sonunda kendi
commit'ini atar, geçiş aynı transaction'da kalıcı olur.
`_produce_video_outputs` artık `surum_hash` döndürüyor (None→str, geriye uyumlu).

## 3. Testler — `tradehub_core/tests/test_media_version_promote.py` (14, hepsi yeşil)

- **promote:** yayına alır + tutarlı; ikinci sürüme geçiş TAM bir aktif bırakır
  ve eski sürümü SİLMEZ; idempotent (zaten yayındaki → no-op).
- **red yolları:** yanlış asset'in sürümü, `ready` olmayan varlık, var olmayan
  sürüm reddedilir.
- **`_validate_active_consistency` dişi var:** elle çelişki kurulunca kapı
  `throw` eder (promote'un ona güvenmesi vacuous değil).
- **VACUITY (atomiklik):** `test_promote_atomik_hata_da_tam_geri_alinir` —
  tutarlılık kapısı hata fırlatınca geçiş bir savepoint içinde TAM geri alınır,
  eski sürüm hâlâ yayında. **Kanıt:** `_write_active_version_atomic`'e araya
  `frappe.db.commit()` (atomiklik-kırma) eklenince bu test KIRMIZI oldu
  (`SAVEPOINT sp_promote_atomik does not exist` — interior commit savepoint'i
  serbest bırakıyor); commit geri alınınca yeşil. Yani atomiklik iddiası bu
  teste bağlı, boşa değil.
- **rollback:** önceki sürüme döner; denetim izi
  `[promote, promote, rollback]`; geçmiş yoksa `throw`.
- **okuma yolu:** `active_version` VARSA onu tercih eder (en yeni maskelemez);
  YOKSA fallback korunur; boş giriş `{}`.

### Konteynerde koşum (docker cp + bench)
| Süit | Sonuç |
|---|---|
| `test_media_version_promote` (yeni) | **14 OK** |
| `test_pipeline_bridge` | **25 OK** (okuma yolu/köprü bozulmadı) |
| `test_media_manifest_api` | **11 OK** |
| `test_manifest_batch` | **16 OK** |
| `test_media_version_enrichment` | **13 OK** |
| `test_video_{live_run,servis,preview_ve_listing,transcode,decision}` | **17/28/23/109/58 OK** |

## 4. Kapsam dışı bırakılanlar (raporla, dokunma)
- **hooks/patches:** dokunulmadı. Yeni `media.version_*` ADL eylemlerinin panel
  denetim ekranında görünmesi istenirse `audit.MEDIA_ACTIONS`'a (audit.py,
  sahiplik dışı) eklenmeli — §2.3 notu.
- **`migration/backfill.py`:** BE dalgası orada; `active_version`'a hâlâ
  dokunmuyor (in-memory raf rollback'i ayrı eksen). Toplu backfill'in
  `active_version` yazması gerekiyorsa o dalganın işi.
- **frontend / docker / commit:** dokunulmadı.

## 5. Değişen dosyalar
- `tradehub_core/tradehub_core/doctype/media_version/media_version.py`
  — `promote_version` / `rollback_version` + yardımcılar; okuma yolu
  `active_version` tercihi.
- `tradehub_core/media/pipeline_bridge.py`
  — `_promote_initial_version` + görsel/video ilk-`ready` çağrısı;
  `_produce_video_outputs` `surum_hash` döndürür.
- `tradehub_core/tests/test_media_version_promote.py` — yeni (14 test).

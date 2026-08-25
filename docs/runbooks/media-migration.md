# MOGEM-570 — medya migration runbook'u

Durum: uygulanmış · plan şeması `v1` · son güncelleme 2026-08-24

Bu runbook yalnız mevcut public görsellerin içerik standardizasyonunu kapsar.
`file_url` değiştiren retro-rename MOGEM-582'dir; rendition seed/rollout ise
MOGEM-617'dir. Üç akış aynı koşumda birleştirilmez.

## Güvenlik sözleşmesi

- Mutasyon uçları yalnız `System Manager` rolüne açıktır.
- Varsayılan koşum `dry_run=1`'dir.
- Wet-run, `validated` durumundaki bir dry-run'ın adını ister. Dry ve wet plan
  SHA-256 özetleri birebir aynı değilse koşum başlamaz.
- Plan `plan_schema_version=1`, `plan_digest` ve `plan_id` taşır. İçerik
  değiştiğinde özet doğrulaması başarısız olur.
- `BILINMIYOR` kayıt, eksik `File`, DB/disk ayrışması, private/hassas kapsam,
  `file_url` drift'i, yetersiz disk veya görünmeyen bulk worker preflight'ı
  kapatır.
- Her batch ayrı `media-image-bulk` işidir. Bir önceki checkpoint kalıcı DB
  kaydına yazılmadan sonraki iş kuyruğa girmez.
- `media-image-live` derinliği sıfır değilse koşum `paused` olur. Böylece canlı
  yükleme için downtime gerekmez.
- Batch hata oranı `%2`yi veya `file_missing`/`decode_failed` oranı `%1`i aşarsa
  koşum `halted` olur.

## 1. Sürümlü planı üret

Planlayıcı salt okunurdur; varsayılan olarak bütün adayları diskten probe eder.
Eksik/hızlı keşif için verilen `probe_limit` veya `probe_min_bytes > 0` çıktısı
wet-run'a kabul edilmez; bilinmeyen kayıtlar kapanmalıdır.

```bash
BACKFILL_PLAN_OUT=/tmp/media-plan-v1.json \
bench --site <site> console
```

Console içinde:

```python
exec(open("apps/tradehub_core/scripts/plan_backfill.py").read())
main()
```

Çıktıda en az şu alanlar bulunur:

```json
{
  "plan_schema_version": 1,
  "plan_id": "media-v1-...",
  "plan_digest": "<64 hex>",
  "records": []
}
```

## 2. Preflight ve dry-run

Bench yolu:

```python
import json

from tradehub_core.media import migration_runtime

with open("/tmp/media-plan-v1.json", encoding="utf-8") as handle:
    plan = json.load(handle)
check = migration_runtime.preflight(plan)
assert check["ok"], check["errors"]
dry = migration_runtime.start(plan, dry_run=True, batch_size=200)
```

HTTP yolu (`POST`, System Manager):

- `tradehub_core.api.media_admin.preflight_media_migration`
- `tradehub_core.api.media_admin.start_media_migration`

Durum:

```python
migration_runtime.status(dry["run_key"])
```

Son batch'ten sonra doğrulama otomatik çalışır. Wet-run'a geçmek için dry-run
durumu `validated`, `validation.ok` değeri `true` ve `errors` değeri `0`
olmalıdır.

## 3. Wet-run

Dry-run'da kullanılan JSON dosyasını değiştirmeden kullan:

```python
wet = migration_runtime.start(
    plan,
    dry_run=False,
    batch_size=200,
    approved_dry_run=dry["run_key"],
)
```

Wet-run sırasında her batch şu kimlikleri ayrı ayrı saklar:

- planlanan `file_names_json`,
- gerçekten değişen `changed_files_json`,
- runner sayaçları ve skip nedenleri,
- otomatik durdurma kararı.

Normal worker veya uygulama yeniden başlatması checkpoint'i kaybettirmez.

## 4. Durdur, devam et, doğrula

```python
migration_runtime.request_stop(wet["run_key"])
# Çalışan batch tamamlanır; sonraki batch başlamadan durum `stopped` olur.

migration_runtime.resume(wet["run_key"])
# `halted`/`failed` için sebebi gördüğünü açıkça belirt:
migration_runtime.resume(wet["run_key"], acknowledge_stop=True)

migration_runtime.validate_run(wet["run_key"])
```

HTTP karşılıkları:

- `get_media_migration_status` (`GET`)
- `stop_media_migration` (`POST`)
- `resume_media_migration` (`POST`)
- `validate_media_migration` (`POST`)

Wet doğrulaması şunları birlikte kontrol eder:

- tüm batch muhasebesi ve plan SHA-256 özeti,
- DB `file_size` ile gerçek disk boyutu,
- `th_optimized_at` / `th_original_size`,
- exact orijinal arşiv kopyası,
- `file_url`'in planla aynı kalması,
- private, excluded doctype ve hassas içerik ikizi kapsamı.

## 5. Rollback

Rollback yalnız wet-run'ın `changed_files_json` listelerini ters batch sırasıyla
işler; aynı URL'deki başka dosyaları veya dry-run tahminlerini geri almaz.

```python
migration_runtime.start_rollback(wet["run_key"])
```

HTTP karşılığı: `rollback_media_migration` (`POST`).

Her ters batch'ten sonra DB/disk metadata kontrol edilir. Son batch'te ayrıca
arşiv kopyasının silindiği ve optimizasyon damgasının temizlendiği doğrulanır.
Başarılı son durum `rolled_back`, doğrulama hatası `rollback_failed` olur.

Wet-run başladığında `archive_hold_until` rollback penceresinin sonuna yazılır.
Bu süre boyunca günlük veya manuel `archive.purge_expired()` hiçbir orijinali
silmez. Aktif `running`/`rolling_back` koşumda süre alanı yanlış olsa bile hold
fail-closed uygulanır.

## Kalıcı kayıtlar ve kod haritası

| Parça | Konum |
|---|---|
| Plan üretimi ve v1 imzası | `scripts/plan_backfill.py`, `media/pipeline/migration/backfill.py` |
| Run/batch executor | `media/migration_runtime.py` |
| Yönetici API'leri | `api/media_admin.py` |
| Dosya işleme / exact kimlik toplama | `media/runner.py` |
| Purge hold | `media/archive.py` |
| Kalıcı şema | `Media Migration Run`, `Media Migration Batch` |
| Schema/index patch'i | `patches/v15_9_47_media_migration_runtime.py` |

Tam üretim wet-run'ı deploy işlemi değildir ve otomatik tetiklenmez. Operatör
önce gerçek planı üretir, dry-run sonucunu inceler ve aynı özeti açıkça onaylar.

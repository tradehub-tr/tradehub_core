# Faz 3 Kapanış Dosyası — Sistem Mimarisi

> Son teknik doğrulama: 2026-08-23. Bu dosya teknik kanıt ile insan onayını
> ayırır; boş imza otomatik olarak doldurulmaz.

## Görev durumu

| ID | Görev | Durum | Kanıt / kalan kapı |
|---|---|:--:|---|
| T-030 | SAD v1.0 | ✅ Teknik tamam | C4, veri/akış/durum diyagramları; bileşen sorumluluk/bağımlılık/hata/ölçek tablosu; ADR izlenebilirliği; SPOF azaltımları (`docs/sad/SAD-v1.0.md`) |
| T-031 | Beş arayüzü dondur | ✅ | 5 `typing.Protocol`, değer tipleri ve hata hiyerarşisi; `signatures.golden.json`; fake + production contract matrisi; `--check` ve mypy kapısı |
| T-032 | Paket/CI/Docker iskeleti | ✅ | App içi saf alt paket kararı ADR-0003; ADR-0004 import sınırı; `.github/workflows/faz3-architecture.yml`; beş worker'lı Compose projeksiyonu |
| T-033 | PolicyEngine | ✅ | 9 kanonik JSON politika; schema/atomik reload; Python fake/production karar paritesi; TypeScript ikizi 393/393 |
| T-034 | Durum, işler ve kuyruklar | ✅ | Geçersiz geçiş testleri; idempotency/retry/backoff/dead-letter; `Media Processing Job`; beş ayrık kuyruk ve `media_queue_depth/jobs` metrikleri |
| T-035 | Bağımsız mimari inceleme | ◐ İnsan kapısı | Teknik bulgular kapatıldı ve paket hazır. Bağımsız gözden geçiren adı/tarih/imzası hâlâ boş |

## Ölçülen teknik kapılar

| Kapı | Sonuç |
|---|---|
| Phase 3 tam kapanış suite | **184 test: OK; 1 skip** (hostta ffmpeg/ffprobe yok; bunun 8'i kapanış koruması) |
| Gerçek ffmpeg smoke | Güncel kaynak read-only mount + backend imajındaki ffmpeg/ffprobe: **1/1 OK, 0,108 sn** |
| Donmuş imza | `python -m ...contracts.signatures --check` → **OK** |
| Tip denetimi | mypy `media/pipeline/contracts` → **0 hata / 8 dosya** |
| Lint | Değişen Faz 3 Python dosyaları → **ruff 0 hata** |
| PolicyEngine | 75 contract + 38 policy testi; kabul edilmiş karar sapması **0** |
| Durum/idempotency | 47 test → **OK** |
| Kuyruk topolojisi | 5/5 kuyruk; DocType/köprü/deploy/workspace projeksiyonları → **OK** |
| Compose | base ve base+`deploy/media-workers.compose.yml` → `docker compose config --quiet` **OK** |
| CI süre bütçesi | Workflow `timeout-minutes: 10` + suite duvar saati `<600 sn` kapısı; gerçek GitHub koşumu ilk push/PR'da ölçülecek |

Tam kapanış suite komutu:

```bash
python -m unittest -v \
  tradehub_core.tests.test_faz3_closure \
  tradehub_core.tests.test_phase3_queue_topology \
  tradehub_core.tests.test_phase3_production_engines \
  tradehub_core.tests.test_contracts \
  tradehub_core.tests.test_policy_engine \
  tradehub_core.tests.test_state_machine
```

## Mimari karar özeti

- Ayrı `media_engine` Frappe app'i yerine
  `tradehub_core.media.pipeline` app içi saf alt paket seçildi (ADR-0003).
- `api/`/köprü dışında modül düzeyinde Frappe bağımlılığı yoktur (ADR-0004).
- Çalışma-zamanı politikasının tek kaynağı `policy/slots/*.json`; standart
  klasöründeki dosyalar belge/ölçüm izdüşümüdür.
- Genel `long` kuyruğuna fallback yoktur: `media-image-live`,
  `media-image-bulk`, `media-video`, `media-ai`, `media-maint` ayrıdır.
- Teknik CI dosyası depodadır; GitHub'da fiilî yeşil koşum yapılmış gibi iddia
  edilmez.

## Kapanış hükmü

T-030…T-034 teknik olarak tamamdır. Faz 3'ün otomasyonla kapatılamayan tek
maddesi T-035 bağımsız insan onayıdır. Dolayısıyla görev panosunda T-030…T-034
**Done**, T-035 ise **In Review / human gate** olmalıdır.

## Onay

```text
Onaylayan (Bağımsız gözden geçiren): ______________________   Tarih: ______________   İmza: ______________
```

# Faz 2 kapanış — Medya standartları

**Doğrulama tarihi:** 2026-08-23
**Kapsam:** T-020…T-029
**Sonuç:** Kod/ajan işi tamamlandı; T-025 insan etiketi ve T-029 gerçek imza
bekliyor. Bu iki madde tamamlanmadan Faz 2 Plane üzerinde bütünüyle Done
çekilmemelidir.

## Görev tablosu

| ID | Görev | Durum | Done çekilir mi? | Kanıt / kalan iş |
|---|---|---:|---:|---|
| T-020 | Ürün görseli standardı + politika şeması | ✅ | Evet | Draft 2020-12 şema; `product-image.json`; 3.061 referansta uyum ölçümü; 2400/2000 master kuralı |
| T-021 | Seller/brand logo standardı | ✅ | Evet | İki logo politikası `standard_status=fixed`; ölçülmüş logo dağılımı; açık soru/null kalite yok |
| T-022 | Company cover video standardı | ✅ | Evet | Süre/çözünürlük/bitrate/poster/HLS/erişilebilirlik kararları sabit; ffmpeg/ffprobe imajda doğrulandı |
| T-023 | Diğer slot standartları | ✅ | Evet | Dokuz slotun tamamı sabit, gerçek alanlara bağlı ve şemaya uyumlu |
| T-024 | DPI ve piksel normalizasyonu | ✅ | Evet | `to_webp` varsayılan tavanı 2400; ürün master tabanı ≥2000; bağımsız testler |
| T-025 | İçerik kuralları ve eşik kalibrasyonu | ◐ | Hayır | Araç, ölçüm yöntemi, eşik, aksiyon ve 1.291 görsellik tetik ölçümü hazır. İnsan etiketleri olmadığı için FP <%5 kanıtı yok |
| T-026 | Retention standardı | ✅ | Evet | Orijinal/türev bağımsız politika, legal hold, soft-delete, audit ve GC testleri |
| T-027 | Kota/rate-limit standardı | ✅ | Evet | Plan bazlı limitler, orijinal+türev sayımı, 429/Retry-After sözleşmesi ve şema |
| T-028 | Migration/backfill planı | ✅ | Evet | Slot bazlı sayılar, A/B/C sınıfları, düşük öncelikli batch, durdurma/rollback, bildirim ve testler |
| T-029 | SRS v1.0 onayı | ◐ | Hayır | SRS/izlenebilirlik ve TBD kontrolü hazır; platform/teknik/güvenlik/ürün imzaları boş ve T-025 bağımlılığı açık |

## Otomatik kapılar

| Kontrol | Beklenen | Sonuç |
|---|---:|---:|
| Slot politikası | 9 | 9 |
| Draft 2020-12 şema hatası | 0 | 0 |
| `standard_status=fixed` | 9 | 9 |
| `compliance_measured` | 9 | 9 |
| `open_questions` toplamı | 0 | 0 |
| Null `encoder_quality` | 0 | 0 |
| Kanonik runtime seti | 1 | 1 (`pipeline/policy/slots`) |
| `docs/standards/` bağlayıcı TBD | 0 | 0 |

Runtime `status=draft` olması hata değildir: Faz 2 şartname durumunu
`standard_status`, Faz 3 üretim rollout durumunu `status` taşır.

## İnsan kapıları

T-025 için etiket şablonu ve yeniden üretilebilir araç hazırdır:
`scripts/calibrate_content_rules.py`. Etiketler, gerçek kişilerce kurala göre
doğru/yanlış olarak doldurulmalıdır; tetik oranı yanlış-pozitif oranı yerine
kullanılamaz.

T-029 için [SRS v1.0](../srs/SRS-v1.0.md) §9.2’deki onay alanları gerçek
onaylayanlar tarafından doldurulmalıdır. Ajan imza veya onay uydurmaz.

## Doğrulama komutları

```bash
PYTHONPATH=. python3 -m unittest \
  tradehub_core.tests.test_faz2_closure \
  tradehub_core.tests.test_policy_dpi \
  tradehub_core.tests.test_policy_engine \
  tradehub_core.tests.test_retention \
  tradehub_core.tests.test_media_quota \
  tradehub_core.tests.test_migration_backfill -v

python3 scripts/gen_traceability.py --check
```

Docker konteyneri kaynak klasörünü bind-mount etmediğinden, güncel çalışma
ağacının saf Python testleri yerelde çalıştırılır. Konteyner yalnız DB/ffmpeg
gibi ortam ölçümlerinde kullanılır; içindeki eski paket kodu test kanıtı
sayılmaz.

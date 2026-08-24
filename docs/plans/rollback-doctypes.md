# Faz 4 DocType rollback planı

Bu plan `Media Source`, `Media Policy`, `Media Policy Profile`, `Media Content Rule`, `Media Asset.source` ve Faz 4 bileşik indeksleri için geçerlidir. Varsayılan yol roll-forward’dur; üretim verisi olan bir DocType tablo düşürülerek geri alınmaz.

## Güvenlik sınırı

- Önce `Media Engine Settings.media_pipeline_enabled=0` yapılır ve beş medya kuyruğu boşaltılır.
- Site, veritabanı ve public/private dosyalar aynı geri dönüş noktasında yedeklenir.
- Yedek açılabilirliği ve dosya boyutu doğrulanmadan hiçbir DDL çalıştırılmaz.
- Geri dönüş hedefi açıkça bir site/veritabanı adı olmalıdır; glob, `$HOME`, `~` veya genel workspace hedeflenmez.
- `Media Source` satırı oluşmuş bir üretim sisteminde yalnız snapshot restore veya ileri düzeltme kullanılır. Tablo düşürmek veri kaybıdır.

## Tercih edilen geri dönüş

1. Trafiği bakım moduna al, upload uçlarını ve worker’ları durdur.
2. `bench --site <site> backup --with-files` çalıştır; oluşturulan SQL ve iki dosya arşivini doğrula.
3. Önceki uygulama imajını/kod sürümünü seç.
4. Aynı bakım penceresinde doğrulanmış SQL snapshot’ını `bench --site <site> restore <sql.gz> --force` ile geri yükle.
5. Önceki kod sürümünde `bench --site <site> migrate --skip-search-index` çalıştır.
6. Şu kontrolleri yap: policy/profile sayıları, `Media Asset.active_version`, açık `Media Usage`, rendition dosya varlığı, seller query isolation ve Settings rol kapısı.
7. Worker’ları önce tek örnekle aç; hata oranı ve kuyruk derinliği normal kalırsa ölçekle.

`source_file` alanı bilinçli olarak korunmuştur. Böylece `Media Source` bağlantısını okumayan önceki uygulama sürümü aynı File kaydıyla çalışmaya devam eder.

## Yalnız boş/tek kullanımlık ortam için şema sökümü

Aşağıdaki öğeler yalnız yedeği alınmış, adı açıkça doğrulanmış disposable/boş ortamda sökülebilir:

- `tabMedia Source`
- `tabMedia Policy`, `tabMedia Policy Profile`, `tabMedia Content Rule`
- `tabMedia Asset.source`
- `ix_seller_state_modified`, `ix_state_lastaccess`, `ix_state_hold_creation`
- `uk_rendition_quad`, `ix_rendition_asset_version`
- `ix_queue_status_modified`, `ix_job_asset_status`

Policy ve child kayıtları kanonik `media/pipeline/policy/slots/*.json` dosyalarından yeniden üretilebilir. `Media Source` kullanıcı verisidir ve yeniden üretilebilir kabul edilmez.

## 2026-08-23 prova kaydı

Prova hedefi yalnız bu iş için oluşturulan `phase4-rollback-20260823.localhost` / `media_phase4_rollback_20260823` idi.

| Adım | Ölçüm / sonuç |
|---|---:|
| Temiz site + app kurulumu | 24,897 sn |
| Temiz `bench migrate` | 6,167 sn |
| Kurulum sonrası katalog | 9 policy · 36 profile · 72 content rule |
| Kurulum sonrası şema | 4 yeni tablo · 1 source kolonu · 7 bileşik indeks |
| SQL backup | 0,704 sn · 531.067 bayt |
| Kontrollü şema kaybı | doğrulama sonucu `0 tablo / 0 kolon / 0 indeks` |
| Snapshot restore | 6,255 sn |
| Restore doğrulaması | `4 tablo / 1 kolon / 7 indeks`, katalog `9 / 36 / 72` |

Bu prova gerçek kullanıcı verisine dokunmadı. Disposable site, benchmark/rollback veritabanları, arşivlenmiş site config’i ve geçici backup doğrulama sonrasında kaldırıldı; aynı prova yukarıdaki adımlarla yeniden üretilebilir.

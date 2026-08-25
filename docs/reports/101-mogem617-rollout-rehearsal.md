# MOGEM-617 / T-144 yerel rollout ve hard-kill provası

Tarih: 2026-08-24  
Ortam: `istoc.localhost`, yerel Docker/Frappe kabul sitesi  
Kapsam: yalnız mağaza seçim kontrol düzlemi; üretim alarm/karar/iletişim süreci değil

## Sonuç

Yerel `Media Engine Settings` değerleri önce belleğe alındı. Prova
`try/finally` içinde `%0 + SELLER-CANARY → %10 → %50 → %100 → master=0`
sırasını koştu ve özgün değerleri geri yükledi.

| Kontrol | Ölçüm | Sonuç |
|---|---:|---|
| `%0` canary mağaza | `true` | Geçti |
| `%0` kapsam dışı mağaza | `false` | Geçti |
| 500 sentetik mağazada `%10` | 48 | Geçti |
| 500 sentetik mağazada `%50` | 246 | Geçti |
| 500 sentetik mağazada `%100` | 500 | Geçti |
| Kümeler monoton (`10 ⊂ 50 ⊂ 100`) | `true` | Geçti |
| Master hard-kill canary'yi de kapattı | `true` | Geçti |
| Yerel DB commit + cache-clear + karar süresi | **1,947 ms** | Ölçüldü |
| Başlangıç ayarları geri yüklendi | `true` | Geçti |

Başlangıç/geri yüklenen değerler:
`media_pipeline_enabled=1`, `rollout_percent=100`, `rollout_stores=""`.

## Kanıt sınırı

`1,947 ms` yalnız aynı yerel sitedeki ayar yazımı, DB commit'i, request-cache
temizliği ve `is_store_enabled` doğrulamasıdır. Alarmın görülmesi, insan kararı,
ayrı web/worker süreçlerine yayılım, gerçek yükleme ve dış gözlemci doğrulaması
bu ölçümde yoktur. Bu nedenle T-144'ün istediği **üretim geri dönüş süresi**
olarak kullanılamaz; üretim canary ve nöbetçi tatbikatı açık kalır.

Tekrarlanabilir davranış testleri:

- `test_pipeline_flags.py`: canary, SHA-256 kovası, monoton yüzde, master-kill.
- `test_pipeline_bridge.py`: kapsam dışı mağazada enqueue yok, canary'de var.
- `test_media_manifest_api.py`: kapsam dışında ham fallback, canary'de rendition.

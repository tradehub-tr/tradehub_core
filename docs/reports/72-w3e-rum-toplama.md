# 72 — T-133/T-124 beslemesi: RUM toplama koşucusu (W3E)

**Tarih:** 2026-08-20 · **Kapsam:** `tradehub_core` (yalnız `api/rum.py` EK + yeni test)
**Görev:** Rapor 63 §6.3'ün devrettiği kalem — `rum.aggregate()→to_metrics()`
zinciri yazılmıştı ama **hiçbir şey çağırmıyordu**. Bu rapor o çağıranı kurar
ve canlıda ölçer.

---

## 0. Tek cümlelik sonuç

`tradehub_core.api.rum.aggregate_samples()` son penceredeki `Media RUM Sample`
satırlarını `rum.aggregate()→to_metrics()` zincirinden geçirip `/metrics`e
taşıyor — **canlıda ölçüldü** (§3): RUM serileri bearer token'lı `/metrics`
çıktısında görünüyor ve **iki koşu aynı değerleri veriyor** (sayaç şişmiyor,
§4). `delivery/rum.py`'ye ve `api/observability.py`'nin mevcut satırlarına
dokunulmadı; `hooks.py` kaydı orkestratörde (§6).

## 1. Ne eklendi

| Parça | Yer | Ne |
|---|---|---|
| Koşucu | `tradehub_core/api/rum.py` (EK — BE-1'in fonksiyonları değişmedi; tek satır dokunuşu import'a `add_to_date` eklemek) | `aggregate_samples(pencere_sonu=None, parcayi_yaz=True)` + `_high_water()` + `_row_to_sample()` |
| Testler | `tradehub_core/tests/test_rum_aggregate.py` (YENİ) | 5 test (§5) |

### Koşucu imzası

```python
def aggregate_samples(pencere_sonu: str | None = None, parcayi_yaz: bool = True) -> dict[str, Any]:
```

Dönen özet: `{"pencere_baslangic", "pencere_sonu", "okunan", "atlanan", "seri", "parca"}`.
Argümansız çağrılabilir (scheduler + `bench execute` uyumlu); `pencere_sonu`
yalnız test/elle koşum için, `parcayi_yaz=False` yalnız test için (test süreci
paylaşılan parça dizinini kirletmesin).

## 2. Pencere/kova tasarımı — `rum.py` fonksiyonlarının KENDİ sözleşmesinden

- `to_metrics()` docstring'i: *"Çağıran, her toplama penceresini BİR kez
  geçirmelidir"* — `rum_samples` bir SAYAÇTIR, aynı pencere ikinci kez
  geçirilirse katlanır. Dolayısıyla pencereler **ayrık** olmak zorunda.
- Pencere: `(işlenen son damga, pencere_sonu]`; varsayılan pencere sonu
  `şimdi − 5 sn` (commit gecikmesi emniyet payı). Kovalanma
  `rum.METRIC_GROUP_BY = ("route", "device_class")` — `to_metrics`'in etiket
  sözleşmesiyle birebir, değiştirilmedi.
- **Damga saklama:** `frappe.db.set_global("rum_aggregate_high_water", ...)`
  → `tabDefaultValue` satırı. Settings alanı YASAKTI; Redis REDDEDİLDİ çünkü
  `clear-cache`/restart'ta uçar ve uçtuğu anda aynı pencere ikinci kez işlenip
  sayaçları şişirirdi. `tabDefaultValue` şemasız + kalıcı + migrate istemez.
- Damga yalnız satır işlendiğinde ve `to_metrics` BAŞARDIKTAN sonra ilerler.
  Bilinen dar takas (kodda yorumla): "to_metrics yazdı, damga yazılamadı"
  (DB çökmesi) durumunda tekrar koşum bir kerelik fazlalık bırakabilir —
  yumuşak tavanlı telemetri için kabul edildi.
- Boş pencerede damga İLERLEMEZ ve parça yazılmaz (iş yok → iz yok).
- `frappe.get_all` gerekçeli (docstring'de): sistem/telemetri işi, DocType'ta
  hiçbir role create/write izni yok, scheduler bağlamında oturum kullanıcısı
  da yok. Okunan alanlar 15 alanın 6'sı (`fields=["*"]` yok).
- Metrikler süreç-yerel `REGISTRY`'ye yazıldıktan sonra
  `observability.write_shard(force=True)` ile parça dosyasına iner — scheduler
  ve `bench execute` süreçleri `after_request` kancasından geçmez, parça
  yazılmasa `/metrics` birleşimine hiç girmezlerdi. Çok-süreç güvenliği:
  sayaçlar parçalar arasında TOPLANIR ama damga her satırı en fazla bir sürece
  verdiği için toplam yine doğrudur.

## 3. Canlı ölçüm (konteyner, istoc.localhost)

1. `collect` ucuna misafir POST (text/plain, 5 sahte örnek: 4×LCP
   100/200/300/400 ms + 1×CLS 0.3, `route=/magaza/:code`,
   `device_class=tablet`, `sample_rate=0.5`) → **200**.
2. `bench execute tradehub_core.api.rum.aggregate_samples --kwargs
   '{"pencere_sonu": "<frappe.utils.now>"}'` →
   `{"okunan": 6, "atlanan": 0, "seri": 3, "parca": ".../media-446.metrics.json"}`
   (6 = 5 sahte + BE-1'in rapor 63 §3'te canlıda bıraktığı 1 kayıt).
3. `/metrics` (bearer token `site_config.media_metrics_token` ile, konteyner
   içinden) — RUM serileri GÖRÜNÜYOR:

```
media_rum_p75_milliseconds{metric="LCP",route="/magaza/:code",device_class="tablet"} 300
media_rum_samples_total{metric="LCP",route="/magaza/:code",device_class="tablet",rating="good"} 4
media_rum_estimated_population{metric="LCP",route="/magaza/:code",device_class="tablet"} 8
media_rum_cls_p75{route="/magaza/:code",device_class="tablet"} 0.3
media_rum_samples_total{metric="CLS",route="/magaza/:code",device_class="tablet",rating="poor"} 1
```

Sayılar satırlardan doğrulanabilir: p75(100,200,300,400)=300; popülasyon
4×(1/0,5)=8; CLS 0,3 → poor.

## 4. İdempotens ölçümü

İkinci koşu (argümansız): `{"pencere_baslangic": "2026-08-20 07:26:57.596469",
"okunan": 0, "seri": 0, "parca": null}` — damga DB'den okundu, pencere boş.
`/metrics` iki scrape arasında **bayt bayt aynı** (10 RUM satırının 10'u;
`media_rum_samples_total ... tablet ... good` iki koşuda da **4**). Şişme yok.

## 5. Test kanıtı

```
run-tests --module tradehub_core.tests.test_rum_aggregate  → Ran 5 tests OK
```

Kapsam: boş pencere sıfır iş + damga ilerlemez · örnekli pencere doğru sayım
(p75/sayaç/popülasyon/damga) · örnekleme oranı popülasyona yansır · çift koşu
şişirmiyor (aynı pencere + satırsız yeni pencere) · sonraki pencere yalnız
yenileri işler.

Regresyon (hepsi konteynerde): `test_rum_endpoint` **17/17** ·
`test_rum_metrics` **20/20** · `test_delivery_rum` **26/26**.

**Vacuity (kırmızı kanıtı):** konteyner kopyasında
`frappe.db.set_global(AGGREGATE_HIGH_WATER_KEY, son)` satırı `pass` yapıldı →
`FAILED (failures=3)` — `test_cift_kosu_sisirmiyor` dahil (sayaç 2 yerine 4'e
katlandı); dosya geri kondu → 5/5 OK. Yani idempotens testleri korumanın
kendisini sınıyor, dekorunu değil.

Ruff: `ruff check` + `ruff format --check` iki dosyada temiz (uvx, repo
pyproject ayarlarıyla). Host ↔ konteyner kopyaları md5 ile birebir.

## 6. Orkestratörden istenen (hooks.py bende YASAKTI)

```python
scheduler_events["hourly"].append("tradehub_core.api.rum.aggregate_samples")
```

(Rapor 63 §7.1'deki `daily` → `purge_expired_samples` kaydı hâlâ ayrıca
bekliyor.) Kayıt eklenene kadar elle:
`bench --site <site> execute tradehub_core.api.rum.aggregate_samples`.

## 7. ÖLÇÜLMEDİ / notlar

1. Scheduler'dan gerçek `hourly` koşusu — kayıt yok, koşamaz (§6).
2. `bench restart` YAPILMADI (görev şartı; diğer ajanın kuyruğu). Koşucu zaten
   `bench execute`/scheduler süreçlerinde yaşıyor — web worker'ların eski kodu
   koşucuyu etkilemez; `collect` ucu değişmedi.
3. Canlı ölçümün DEV sitesinde bıraktığı iz: 5 sahte `Media RUM Sample` satırı
   (30 günde `purge` ile gider), `rum_aggregate_high_water` damgası ve
   `media-446` parça dosyası. Bilinçli bırakıldı — gerçek zincirin kanıtı.
4. Gauge'lar (p75/popülasyon) pencere boşken ESKİ değerini korur (Prometheus
   gauge semantiği + parça birleşiminde `latest` politikası). Bayatlık alarmı
   T-124 kural setinin işi, bu görevin değil.

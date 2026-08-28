# Tenant medya kota sözleşmesi

**Plane:** MOGEM-573 · **Sürüm:** 1.0 · **Yürürlük:** 2026-08-24

Bu belge çalışma zamanı sözleşmesidir. Geniş T-027 incelemesi ve rate-limit
araştırması `kota.md` içinde tarihsel kayıt olarak durur; çelişkide bu belge,
`media/quota_model.py` ve `media/files.py` geçerlidir.

## 1. Kota ve gözlem boyutları

| Boyut | Kaynak | Davranış |
|---|---|---|
| Depolama baytı | Public orijinal + tenant rendition baytı | Plan bazlı sert kota |
| Orijinal dosya adedi | Tekilleştirilmiş public `File.file_url` | Gözlem/rapor |
| Rendition adedi | `Media Rendition` satırı | Gözlem/rapor |
| Aylık iş adedi | Bu ay açılan `Media Processing Job` | Gözlem/rapor |
| Aylık işlem süresi | Bu ayın `duration_ms` toplamı | Gözlem/rapor |
| Tek dosya boyutu | `upload_policy` + slot politikası | Tenant kotasından ayrı yükleme kapısı |

Dosya, rendition veya aylık işlem adetleri için ticari plan değerleri
onaylanmadı. Bu nedenle sayı uydurulmaz ve bu boyutlar yüklemeyi engellemez.
Yeni bir limit önce gözlem verisiyle kalibre edilip ayrı plan anahtarıyla
etkinleştirilmelidir.

## 2. Depolama formülü ve tenant izolasyonu

```text
used_bytes = original_bytes + rendition_bytes
```

- `original_bytes`: mağazanın kullanıcılarına ait, `is_private=0`, `/files/`
  yolundaki kayıtların `file_url` bazında `max(file_size)` toplamı.
- `rendition_bytes`: `Media Rendition.asset → Media Asset.owner_seller`
  zincirinde yalnız hedef tenant'a ait `SUM(bytes)`.
- Türevler `File` kaydı açmaz; ADR-0009 korunur. ADR-0022 seçenek D uyarınca
  ledger baytları ikinci sayaç olarak kotaya katılır.
- HLS segment adedi tahmin edilmez. HLS rendition satırındaki toplam bayt
  kullanılır.

Tenant kimliği istek gövdesinden alınmaz. Satıcı uçları oturumdan mağazayı
çözer; raporlama ve SQL join'leri `owner_seller=store` filtresini kendi içinde
uygular.

## 3. Plan yönetimi

Tek sert limit `Subscription Plan.quota_limits` içindeki
`quota.max_storage_mb` anahtarıdır. Yönetici plan JSON'unu veya abonelik
override'ını değiştirdiğinde entitlement cache'i üzerinden yeni değer
uygulanır.

| Plan adı eşleşmesi | Varsayılan |
|---|---:|
| free / bilinmeyen custom plan | 500 MB |
| starter | 2.000 MB |
| pro / premium | 5.000 MB |
| enterprise | `-1` — sınırsız |

Semantik: anahtar yoksa `unconfigured` ve fail-open; `-1` sınırsız; `0` yeni
medya yüklemesini kapatır; pozitif sayı MiB cinsinden sert sınırdır. `-2` ve
daha küçük değerler yapılandırma hatasıdır.

## 4. Durum ve kullanıcı davranışı

| Durum | Koşul | Kullanıcı davranışı |
|---|---|---|
| `unconfigured` | Plan anahtarı yok | Sınır gösterilmez, yükleme engellenmez |
| `unlimited` | Limit `-1` | “Sınırsız” gösterilir |
| `ok` | Kullanım <%80 | Normal gösterge |
| `warning` | %80 ≤ kullanım <%100 | Kalan alanla uyarı |
| `exhausted` | Kullanım = %100 | Yeni pozitif yükleme engellenir |
| `exceeded` | Kullanım > %100 | Aşım raporlanır, yeni yükleme engellenir |

Yüzde raporda kırpılmaz; örneğin yarış veya sonradan yazılan rendition kotayı
aşırırsa `%120` görünür. Görsel ilerleme çubuğu yalnız 0–100 aralığında çizilir.
Ret kodu `upload_quota_exceeded` ve retryable=false'dur. Kullanıcı yer açmalı
veya plan yükseltmelidir; otomatik retry aynı sonucu vereceği için yapılmaz.

## 5. Uygulama noktaları

1. Parçalı yükleme oturumu açılırken ilan edilen bayt kota ile karşılaştırılır
   ve `quota_remaining` döner.
2. Tek/parçalı satıcı medya kaydında, dönüşebilen görselin gerçekten saklanacak
   baytı `File.insert` öncesinde yeniden kontrol edilir. Yetersizse diske yazılmaz.
3. Genel Frappe yükleme yolları için `File.before_insert` kontrolü ikinci
   savunma hattıdır.
4. Rendition üretildikten sonra ledger baytı canlı toplama girdiği için bir
   sonraki özet/kota kontrolü ek maliyeti otomatik görür.

Kontrol kilitsiz canlı toplam kullanır; eşzamanlı istekler için kalıcı bayt
rezervasyonu bu sözleşmenin dışında ayrı bir ölçeklendirme işidir. Aşım
saklanmaz veya gizlenmez: `quota_state=exceeded` ve `overage_bytes` ile görünür.

## 6. Public/private ve saklama kapsamı

- Public satıcı medyası ve onun rendition'ları sayılır.
- Private dosyalar sayılmaz ve hook'ta muaftır. Bunlar KYB/KYC, sipariş,
  ödeme ve veri dışa aktarma gibi medya kütüphanesinde görünmeyen güvenlik/
  yasal ekler için ayrı kapsamdır.
- Bu geniş private muafiyeti genel `upload_file` yolunda kötüye kullanılabilir;
  private hacim ayrı güvenlik metriğiyle izlenmelidir. Medya kotasına sessizce
  eklemek, satıcının göremediği belgeler yüzünden yüklemeyi engelleyeceğinden
  yapılmaz.
- Çöp ve yasal saklama davranışı retention sözleşmesinin sahibidir; kota
  verisi bir silme yetkisi vermez.

## 7. Raporlama API'si

`seller_media.get_my_summary` geriye dönük `bytes` ve `quota_bytes` alanlarını
korur; ayrıca şu alanları döndürür:

- `original_bytes`, `rendition_bytes`, `original_files`, `renditions`,
- `remaining_bytes`, `usage_percent`, `quota_mode`, `quota_state`,
- `warning_threshold_percent`, `is_warning`, `is_exhausted`, `is_exceeded`,
  `overage_bytes`,
- `processing_period_start`, `processing_jobs_month`,
  `processing_duration_ms_month`,
- `scope.public_originals`, `scope.private_originals`, `scope.renditions`.

Panel toplamın yanında orijinal/türev dökümünü gösterir; uyarı ve engel rengini
backend durumundan alır. Böylece istemci kendi kota eşiğini icat etmez.

## 8. Otomatik kanıt

- `test_media_quota_model.py`: limit semantiği, %80 uyarı, tükenme ve aşım,
- `test_media_quota.py`: `File.before_insert` kararları ve muafiyetler,
- `test_media_quota_renditions.py`: tenant-süzgeçli bayt/adet/aylık iş raporu,
- `test_media_pipeline_integration.py`: kota reddinde File ve disk artığı yok,
- admin `mediaLibraryGrid.test.js`: API → store alan eşlemesi,
- admin `mediaProgressbarName.test.js`: uyarı/engel ve erişilebilir gösterge.

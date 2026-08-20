# Arayüz Sözleşmeleri — DONDURULMUŞ

**Durum:** DONDURULMUŞ (v1.0) · **Faz:** 3 · **Görev:** T-031
**Kod:** `tradehub_core/media/pipeline/contracts/` · **Sahte uygulamalar:** `tradehub_core/media/pipeline/fakes/`
**Testler:** `tradehub_core/tests/test_contracts.py` (**75 test** — 69→75, `POLICY_IMPLS`'e üretim
uygulaması eklendi; 2026-08-20 ölçümü: rapor 88, kaynak rapor 43) · **Altın dosya:**
`tradehub_core/media/pipeline/contracts/signatures.golden.json`
**Mimari bağlam:** `docs/sad/SAD-v1.0.md` §3.3, §4.1 · **Bugünkü tüketiciler:** §8

---

## 0. "Dondurulmuş" ne demek

Bu sayfadaki imzalar `signatures.golden.json` dosyasına yazılmıştır ve
`tests/test_contracts.py::SignatureGoldenTest` her koşumda karşılaştırır. Bir
metot imzası ya da bir değer nesnesinin alan listesi **sessizce** değişemez;
değişirse test kırılır.

Bilinçli değişiklik üç adımdır:

```bash
# 1. sözleşmeyi değiştir (contracts/*.py)
# 2. altın dosyayı yenile
python3 -m tradehub_core.media.pipeline.contracts.signatures --write
# 3. bu belgenin sürüm notunu güncelle ve gerekçeyi commit mesajına yaz
```

Gerekçesiz imza değişikliği kabul edilmez: sözleşme, iki tarafın (üretici
motor ve tüketici uç) aynı anda değişmesini gerektirir.

---

## 1. Tasarım ilkeleri

| # | İlke | Sonucu |
|---|---|---|
| 1 | **`typing.Protocol` — yapısal tipleme** | Uygulamanın bu paketten türemesi gerekmez. `tradehub_core/media/` altındaki çalışan modüller **değiştirilmeden**, ince bir sarmalayıcıyla sözleşmeye uydurulabilir |
| 2 | **`frappe` yok, DB yok, ağ yok** | Sözleşme testleri site/bench olmadan koşar. Bugünkü `media/engine.py` ve `media/gates.py`'nin bilinçli kısıtı pakete genişletilmiştir |
| 3 | **Girdi bayt, çıktı bayt** | Motorlar depoya yazmaz, `File` kaydı açmaz. Yan etki tek yerde (`StorageAdapter`) toplanır |
| 4 | **Hata tipi sözleşmenin parçası** | `FileNotFoundError`/`CalledProcessError` sızdırmak ihlaldir; her hata `contracts.errors` hiyerarşisinden gelir |
| 5 | **İdempotensi docstring'de yazılı** | Her metot "ikinci çağrı ne yapar" sorusunu yanıtlar; §5'te toplu tablo |
| 6 | **Ölçülemeyen değer uydurulmaz** | `measured=False` taşıyan rapor tipleri (`QualityReport`, `VideoProbe`) — FR-066 |

---

## 2. Beş çekirdek arayüz

### 2.1 `StorageAdapter` — İçerik-adresli nesne deposu

`media/naming.py` (sha256[:32] + 2 hex shard) ve `media/access_level.py` (atomik public↔private taşıma) davranışının sözleşme hâli. `file_url` sabit kalır (NFR-044).

| Metot | İmza |
|---|---|
| `delete` | `(self, ref: 'ObjectRef') -> 'bool'` |
| `exists` | `(self, ref: 'ObjectRef') -> 'bool'` |
| `get` | `(self, ref: 'ObjectRef') -> 'bytes'` |
| `iter_keys` | `(self, *, scope: 'str' = 'public', prefix: 'str' = '') -> 'Iterator[ObjectKey]'` |
| `move` | `(self, source: 'ObjectRef', target_scope: 'str') -> 'ObjectRef'` |
| `put` | `(self, content: 'bytes', extension: 'str', *, scope: 'str' = 'public') -> 'PutResult'` |
| `stat` | `(self, ref: 'ObjectRef') -> 'ObjectStat'` |
| `url_for` | `(self, ref: 'ObjectRef', *, ttl_seconds: 'Optional[int]' = None) -> 'str'` |

### 2.2 `ImageEngine` — Görsel işleme

`media/engine.py`'yi sarar ve genişletir: `probe`/`optimize`/`to_webp` karşılıkları + **yeni** türev merdiveni ve SSIM kapısı. Pillow'da kalındı (SAD §2.2 S-02).

| Metot | İmza |
|---|---|
| `make_ladder` | `(self, master: 'bytes', specs: 'Sequence[RenditionSpec]') -> 'Dict[str, EncodedImage]'` |
| `make_master` | `(self, content: 'bytes', spec: 'MasterSpec') -> 'EncodedImage'` |
| `make_rendition` | `(self, master: 'bytes', spec: 'RenditionSpec') -> 'EncodedImage'` |
| `probe` | `(self, content: 'bytes', *, max_megapixels: 'float' = 0.0) -> 'ImageProbe'` |
| `quality_score` | `(self, reference: 'bytes', candidate: 'bytes', *, metric: 'str' = 'ssim') -> 'QualityReport'` |
| `supported_formats` | `(self) -> 'Tuple[str, ...]'` |

### 2.3 `VideoEngine` — Video işleme — kuyruk HARİÇ

`media/transcode.py`'nin saf dönüşüm kısmı. Retry/dead-letter/süpürücü sözleşmeye GİRMEZ: o katman `media/jobs.py` + `media/states.py` ile zaten çalışıyor.

| Metot | İmza |
|---|---|
| `make_poster` | `(self, source: 'VideoSource', spec: 'PosterSpec') -> 'EncodedImage'` |
| `make_preview_clip` | `(self, source: 'VideoSource', spec: 'PreviewClipSpec', *, target_path: 'str' = '') -> 'VideoArtifact'` |
| `needs_transcode` | `(self, probe: 'VideoProbe', *, max_width: 'int' = 1280, max_bitrate_bps: 'int' = 2500000) -> 'bool'` |
| `probe` | `(self, source: 'VideoSource') -> 'VideoProbe'` |
| `transcode` | `(self, source: 'VideoSource', spec: 'VideoRenditionSpec', *, target_path: 'str' = '') -> 'VideoArtifact'` |
| `transcode_all` | `(self, source: 'VideoSource', specs: 'Sequence[VideoRenditionSpec]') -> 'Dict[str, VideoArtifact]'` |

### 2.4 `PolicyEngine` — Slot politikası kayıt defteri ve karar kapıları

Faz 2 çıktısını (`policy/schema` + 9 slot) karara çevirir. L1 `accept`, L2 `require`, L3 `master`, L4 `quality` katmanları.

> **Uygulama durumu (2026-08-20 ölçümü: rapor 77):** üretim sınıfı
> `policy/engine.py` protokolün **13/13** metodunu karşılıyor (`isinstance` True).
> Üretim sınıfı ayrıca dondurulmuş yüzeyin DIŞINDA bir `evaluate(slot, probe,
> role) -> Decision` metodu taşır (`engine.py:572`); bu metot protokole
> **eklenmedi** — panel tarafındaki TypeScript ikizinin (393/393 parite vektörü)
> ikizlediği yüzey budur. `evaluate`'i dondurmak ayrı bir sözleşme kararıdır.

| Metot | İmza |
|---|---|
| `check_accept` | `(self, slot_key: 'str', *, file_name: 'str', size_bytes: 'int', sniffed_type: 'str' = '', declared_mime: 'str' = '') -> 'Decision'` |
| `check_geometry` | `(self, slot_key: 'str', probe: 'ImageProbe', *, count: 'int' = 1) -> 'Decision'` |
| `check_video` | `(self, slot_key: 'str', probe: 'VideoProbe') -> 'Decision'` |
| `effective_limits` | `(self, slot_key: 'str', *, plan_max_bytes: 'int' = 0) -> 'EffectiveLimits'` |
| `load` | `(self, slot_key: 'str') -> 'SlotPolicy'` |
| `master_spec` | `(self, slot_key: 'str') -> 'MasterSpec'` |
| `quality_threshold` | `(self, slot_key: 'str', content_class: 'str') -> 'float'` |
| `reload` | `(self) -> 'int'` |
| `rendition_specs` | `(self, slot_key: 'str') -> 'Tuple[RenditionSpec, ...]'` |
| `slots` | `(self) -> 'Tuple[str, ...]'` |
| `source_root` | `(self) -> 'str'` |
| `validate` | `(self, slot_key: 'str' = '') -> 'Decision'` |
| `video_rendition_specs` | `(self, slot_key: 'str') -> 'Tuple[VideoRenditionSpec, ...]'` |

### 2.5 `DeliveryManifest` — `srcset`/`sizes`/`<picture>` manifestosu

**Mevcut motorda karşılığı YOK.** Ölçülen boşluk: `srcset` 31 görselin 0'ında; ürün sayfası 13,14 MB (hedefin 15 katı). HTML değil **veri** döndürür — iki frontend (Alpine + Vue) aynı sözlüğü okur.

| Metot | İmza |
|---|---|
| `build_image` | `(self, slot_key: 'str', base: 'ObjectRef', *, intrinsic: 'Tuple[int, int]' = (0, 0), alt: 'str' = '', sizes: 'str' = '', available_profiles: 'Optional[Sequence[str]]' = None, is_lcp_candidate: 'bool' = False) -> 'RenderManifest'` |
| `build_video` | `(self, slot_key: 'str', base: 'ObjectRef', *, poster: 'Optional[ObjectRef]' = None, captions_url: 'str' = '', intrinsic: 'Tuple[int, int]' = (0, 0), available_renditions: 'Optional[Sequence[str]]' = None) -> 'RenderManifest'` |
| `overshoot` | `(self, slot_key: 'str', css_width_px: 'float', *, dpr: 'float' = 1.0) -> 'float'` |
| `pick` | `(self, slot_key: 'str', css_width_px: 'float', *, dpr: 'float' = 1.0) -> 'Variant'` |
| `sizes_attribute` | `(self, slot_key: 'str', *, context: 'str' = '') -> 'str'` |

---

## 3. Değer nesneleri (donmuş dataclass)

Protokol imzaları bunlara atıf yaptığı için **alan listeleri de dondurulmuştur**:
`ImageProbe`'a zorunlu bir alan eklemek, imzası değişmemiş bir metodu bile kırar.

| Tip | Yapıcı imzası |
|---|---|
| `ObjectKey` | `(shard: 'str', name: 'str') -> None` |
| `ObjectRef` | `(key: 'ObjectKey', scope: 'str' = 'public') -> None` |
| `ObjectStat` | `(size_bytes: 'int', content_hash: 'str', modified_at: 'float' = 0.0, extra: 'Dict[str, Any]' = <factory>) -> None` |
| `PutResult` | `(ref: 'ObjectRef', created: 'bool', stat: 'ObjectStat') -> None` |
| `ImageProbe` | `(fmt: 'str', width: 'int', height: 'int', mode: 'str' = '', animated: 'bool' = False, readable: 'bool' = True, has_alpha: 'bool' = False, icc_profile: 'bool' = False, dpi: 'Optional[Tuple[float, float]]' = None, exif_orientation: 'int' = 1, frame_count: 'int' = 1) -> None` |
| `MasterSpec` | `(max_long_edge: 'int', format: 'str', min_long_edge: 'int' = 0, max_megapixels: 'float' = 0.0, dpi_out: 'int' = 72, colorspace: 'str' = 'srgb', orientation: 'str' = 'apply_exif', fit: 'str' = 'contain', target_ratio: 'str' = '', pad_color: 'str' = '', allow_crop: 'bool' = False, allow_upscale: 'bool' = False, quality: 'int' = 0, lossless: 'bool' = False, strip_metadata: 'Dict[str, bool]' = <factory>) -> None` |
| `RenditionSpec` | `(name: 'str', width: 'int', format: 'str', quality: 'int' = 0, fit: 'str' = 'contain', target_ratio: 'str' = '', pad_color: 'str' = '', lossless: 'bool' = False, derived_from: 'str' = '') -> None` |
| `EncodedImage` | `(content: 'bytes', fmt: 'str', width: 'int', height: 'int', quality: 'int' = 0, dpi: 'int' = 72, notes: 'Tuple[str, ...]' = ()) -> None` |
| `QualityReport` | `(metric: 'str', score: 'float', threshold: 'float', measured: 'bool' = True) -> None` |
| `VideoSource` | `(content: 'Optional[bytes]' = None, path: 'str' = '') -> None` |
| `VideoProbe` | `(width: 'int' = 0, height: 'int' = 0, duration_s: 'float' = 0.0, bitrate_bps: 'int' = 0, frame_rate: 'float' = 0.0, container: 'str' = '', video_codec: 'str' = '', audio_codec: 'str' = '', has_audio: 'bool' = False, measured: 'bool' = True) -> None` |
| `VideoRenditionSpec` | `(id: 'str', width: 'int', height: 'int', container: 'str', video_codec: 'str', crf: 'int' = 32, maxrate_kbps: 'int' = 0, bufsize_kbps: 'int' = 0, frame_rate_cap: 'int' = 30, audio: 'str' = 'allowed', audio_codec: 'str' = 'libopus', audio_bitrate_kbps: 'int' = 96, audio_channels: 'int' = 2, loudness_filter: 'str' = '', max_bytes: 'int' = 0, role: 'str' = 'primary', keyframe_interval_s: 'float' = 0.0) -> None` |
| `PosterSpec` | `(width: 'int', height: 'int' = 0, format: 'str' = 'webp', quality: 'int' = 80, window_start_s: 'float' = 0.5, window_end_s: 'float' = 5.0, retry_window_start_s: 'float' = 0.0, retry_window_end_s: 'float' = 0.0, frames: 'int' = 120, min_brightness: 'float' = 0.0) -> None` |
| `PreviewClipSpec` | `(duration_s: 'float' = 6.0, width: 'int' = 854, height: 'int' = 480, max_bytes: 'int' = 409600, video_codec: 'str' = 'libvpx-vp9', container: 'str' = 'webm', start_offset_s: 'float' = 0.0, silent: 'bool' = True, loop: 'bool' = True) -> None` |
| `VideoArtifact` | `(rendition_id: 'str', width: 'int', height: 'int', duration_s: 'float', size_bytes: 'int', container: 'str', content: 'Optional[bytes]' = None, path: 'str' = '', bitrate_bps: 'int' = 0, has_audio: 'bool' = False, notes: 'Tuple[str, ...]' = (), extra: 'Dict[str, str]' = <factory>) -> None` |
| `Violation` | `(code: 'str', layer: 'str', sebep: 'str', action: 'str' = 'reject', retryable: 'bool' = False, message_key: 'str' = '', measured: 'Optional[Any]' = None, expected: 'Optional[Any]' = None, detay: 'Dict[str, Any]' = <factory>) -> None` |
| `Decision` | `(slot_key: 'str', action: 'str' = 'pass', violations: 'Tuple[Violation, ...]' = (), warnings: 'Tuple[Violation, ...]' = (), notes: 'Tuple[str, ...]' = ()) -> None` |
| `EffectiveLimits` | `(max_bytes: 'int', max_megapixels_hard: 'float' = 0.0, max_count: 'int' = 0, source: 'Dict[str, str]' = <factory>) -> None` |
| `SlotPolicy` | `(slot_key: 'str', schema_version: 'str', status: 'str' = 'draft', roles: 'Tuple[str, ...]' = (), accept: 'Mapping[str, Any]' = <factory>, require: 'Mapping[str, Any]' = <factory>, master: 'Mapping[str, Any]' = <factory>, quality: 'Mapping[str, Any]' = <factory>, profiles: 'Tuple[Mapping[str, Any], ...]' = (), video: 'Mapping[str, Any]' = <factory>, on_violation: 'Mapping[str, Any]' = <factory>, messages: 'Mapping[str, Any]' = <factory>, bound_to: 'Tuple[Mapping[str, Any], ...]' = (), raw: 'Mapping[str, Any]' = <factory>) -> None` |
| `Variant` | `(profile: 'str', url: 'str', width: 'int', fmt: 'str', height: 'int' = 0, size_bytes: 'int' = 0, available: 'bool' = True) -> None` |
| `SourceSet` | `(fmt: 'str', srcset: 'str', sizes: 'str' = '') -> None` |
| `RenderManifest` | `(slot_key: 'str', fallback_url: 'str', variants: 'Tuple[Variant, ...]' = (), sources: 'Tuple[SourceSet, ...]' = (), sizes: 'str' = '', intrinsic_width: 'int' = 0, intrinsic_height: 'int' = 0, alt: 'str' = '', loading: 'str' = 'lazy', decoding: 'str' = 'async', fetchpriority: 'str' = '', poster_url: 'str' = '', captions_url: 'str' = '', extra: 'Dict[str, Any]' = <factory>) -> None` |

---

## 4. Hata hiyerarşisi

```
MediaEngineError(mesaj, *, kod, retryable, detay)   .to_response() → {error_code, retryable, message, details}
├── PolicyError                    politika kayıt defteri bozuk
│   └── PolicyNotFound             bilinmeyen slot_key
├── PolicyViolation                dosya politikayı ihlal etti (kullanıcı hatası)
├── StorageError                   (retryable=True)
│   ├── ObjectNotFound             (retryable=False)
│   └── StorageConflict            aynı anahtar, farklı içerik (retryable=False)
├── ImageError
│   ├── DecodeError                baytlar görsel değil
│   ├── EncodeError                (retryable=True) — hiçbir bayt yazılmamış olmalı
│   ├── UnsupportedFormat          biçim desteklenmiyor / alfa düşürülemez
│   └── OversizedImage             megapiksel tavanı (FR-011, FR-143)
├── VideoError                     (retryable=True)
│   ├── ProbeUnavailable           ffprobe yok/okunamadı → güvenli taraf (NFR-043)
│   └── TranscodeFailed            detay["attempts"] taşır
└── DeliveryError
    └── NoProfileAvailable         hiçbir türev üretilebilir değil
```

### 4.1 `retryable` kuralı

`tradehub_core/media/upload_policy.py:90-96`'daki kural **korunur**: kullanıcının
dosyasıyla ilgili hatalar tekrar denenmez (aynı dosya aynı sonucu verir);
geçici sistem hataları denenir. İstemci karar verirken hata **metnine değil**
`(kod, retryable)` çiftine bakar (FR-060).

### 4.2 Kod üretimi

```python
kod_uret(prefix, sebep) -> "<prefix>_<sebep>"
# prefix  ← slot politikasının on_violation.error_code_prefix (ör. "product_image")
# sebep   ← errors.SEBEP_* sabitlerinden biri
# örnek   → "product_image_short_edge_too_small"
```

Serbest metin yerine sabit kullanılır: aynı sebebin iki slotta iki farklı
yazımla görünmesi böylece imkânsızdır (NFR-046).

---

## 5. İdempotensi tablosu

| Metot | Davranış | Not |
|---|---|---|
| `StorageAdapter.put` | **İdempotent** | İçerik-adresli; ikinci yazma `created=False`. Aynı anahtar + farklı içerik → `StorageConflict` |
| `StorageAdapter.delete` | **İdempotent** | Yoktu ise `False`, sildi ise `True` |
| `StorageAdapter.move` | **DEĞİL** | Kaynak bir kez tüketilir. Hedefte aynı içerik varsa birleşme (no-op) |
| `StorageAdapter.get/exists/stat/url_for/iter_keys` | Yan etkisiz | — |
| `ImageEngine.probe` | Yan etkisiz | Açılamayan içerikte hata atmaz, `readable=False` döner |
| `ImageEngine.make_master` | **Deterministik + sabit noktalı** | `make_master(make_master(x,s).content, s) == make_master(x,s)` — bayt düzeyinde |
| `ImageEngine.make_rendition` / `make_ladder` | **Deterministik** | Merdivende kısmi başarı YOK |
| `ImageEngine.quality_score` | Yan etkisiz | Ölçülemezse `measured=False` |
| `VideoEngine.probe` / `needs_transcode` | Yan etkisiz | Ölçülemeyen video → `needs_transcode = True` (güvenli taraf) |
| `VideoEngine.transcode` | **Etki-idempotent** | Bayt-determinizmi VAAT EDİLMEZ (ffmpeg sürümü). İkinci koşum sistemi aynı durumda bırakır (NFR-040) |
| `VideoEngine.make_poster` | Deterministik | `thumbnail` filtresi girdiye göre çalışır |
| `PolicyEngine.*` (`reload` hariç) | **Saf** | Aynı politika + aynı girdi → aynı `Decision` |
| `PolicyEngine.reload` | **Tek yan etkili metot** | Ya hep ya hiç: bozuk dosyada hiçbir politika değişmez |
| `DeliveryManifest.*` | **Saf** | Depoya bakmaz; hangi türevin var olduğunu çağıran `available_profiles` ile bildirir |

---

## 6. Sahte uygulamalar

| Sahte | Gerçekliği |
|---|---|
| `InMemoryStorage` | Tamamen sahte — sözlük tabanlı, disk yok. İçerik-adresli davranışın tamamını taşır |
| `FakeImageEngine` | Sentetik biçim (`FIMG1\|fmt=…\|w=…`). Pillow **gerekmez**. Piksel doğruluğunu değil sözleşme davranışını doğrular |
| `FakeVideoEngine` | Sentetik biçim (`FVID1\|…`). ffmpeg **gerekmez** |
| `InMemoryPolicyEngine` | **Sahte değil, referans uygulama.** `tradehub_core/media/pipeline/policy/slots/*.json`'u gerçekten okur. Politika mantığını sahtelemek testi anlamsız kılardı |
| `SimpleDeliveryManifest` | Referans uygulama — politikadan `srcset` üretir |

**Sözleşme testleri parametrizedir:** her test bir uygulama listesi üzerinde
döner (`STORAGE_IMPLS`, `IMAGE_IMPLS`, `VIDEO_IMPLS`, `POLICY_IMPLS`). Gerçek
uygulama yazıldığında listeye **tek satır** eklenir ve aynı testler onu da
denetler — `PolicyEngine` için bu yapıldı: üretim motoru listeye girdi ve suite
**69 → 75** teste çıktı (2026-08-20 ölçümü: rapor 88, kaynak rapor 43).
`ImageEngine` ve `VideoEngine` için üretim uygulaması hâlâ **yalnız sahte** —
SAD §14.6 / SAD-G2.

```bash
python3 -m unittest tradehub_core.tests.test_contracts -v   # 75 test, bağımlılık yok
```

---

## 7. Bilinen açık madde

`tradehub_core/media/pipeline/core/errors.py` (Faz 3 ikinci yarısı) kullanıcıya dönük iki dilli
mesaj + düzeltme ipucu taşıyan **ayrı** bir ihlal nesnesi tanımlıyor. Bu
sözleşmedeki `contracts/errors.py` ile **çelişmiyor** ama iki modül birleşmeli:
`contracts/errors` taşıma katmanı (kod + retryable), `core/errors` sunum
katmanı (tr/en mesaj + ipucu). Karar Faz 3 kapanışında (T-035) verilmeli.
Bkz. `docs/sad/SAD-v1.0.md` §11 A-2.

---

## 8. Sözleşmenin bugünkü tüketicileri — 2026-08-20 durumu (rapor 88)

Dondurulan Python yüzeyinin üstünde, T-031'den sonra üç gerçek sözleşme
katmanı daha doğdu. Hiçbiri §2'deki imzaları değiştirmedi; buraya envanter
olarak kaydedildi:

| Katman | Kaynak doğruluk | Kanıt |
|---|---|---|
| **HTTP sözleşmesi** | `docs/api/openapi-http.yaml` — gerçek `@frappe.whitelist()` yüzeyi, **100 uç** (90 → 100; 10 ayrık uç kapatıldı, 79'u canlı HTTP ile ölçülü). Panelde `openapi-typescript` üretimi `types.gen.ts` (5.232 satır, 100 path) + `client.ts` sarmalayıcı + canlıya karşı contract testleri; sha256 vendor zinciri `--check` ile bayatlamaya kapalı | rapor 80 |
| **PolicyEngine TS ikizi** | `admin-panel/frontend/src/lib/media/policy/` — `evaluate` yüzeyinin tipli ikizi; **393/393 parite vektörü** Python motoru koşturularak üretildi ve birebir tutuyor (mesaj metinleri, ihlal sırası, `skipped` dahil); `vendor.manifest.json` sha256 zinciri kaynak sürüklenmesini testte yakalar | rapor 77 |
| **Manifest zenginleştirmesi** | `RenderManifest.extra["version"]` — `Media Version` meta bloğu (lqip, dominant_color, colorspace, `policy_snapshot` özeti) `build_image(..., version_meta=...)` kw-only parametresiyle taşınır; `manifest_batch` yanıtı dosya başına `version` anahtarı döndürür. **İmza değişmedi**: `extra: Dict[str, Any]` alanı sözleşmede zaten vardı | rapor 66, 73 |

Bu katmanların bayatlama korumaları (üç ayrı `--check` betiği + parite
testleri) bu belgenin altın-dosya desenini izler: sözleşme sessizce değişemez.

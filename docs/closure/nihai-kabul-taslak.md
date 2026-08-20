# Nihai Kabul Dosyası — **TASLAK** (T-145 hazırlığı)

> ⚠️ **TASLAK.** Bu belge imzaya sunulmaz; 13-faz14-kabul.md'nin (2026-08-18) güncel ölçümlerle yeniden derlenmiş hâlidir ve nihai kabulün insan kalemlerini tek listede toplar.
> **Bu belge ölçümlerden derlenmiştir; çelişki hâlinde rapor kazanır.**
> Derleme tarihi: 2026-08-20 · W6 kapanış dalgası.

---

## 1. Güncel karne

**Ölçülmüş karne (57-durum-anlik-goruntu.md, pencere 2026-08-19 22:27→23:00, 102 görev):**

| Fazlar | Görev | TAM | KISMİ | YOK |
|---|---:|---:|---:|---:|
| 0–3 | 36 | 18 | 18 | 0 |
| 4–7 | 25 | 2 | 22 | 1 |
| 8–11 | 24 | 1 | 22 | 1 |
| 12–14 | 17 | 0 | 16 | 1 |
| **Toplam** | **102** | **21** | **78** | **3** |

> Not: Görev tanımındaki "48/52/2" sayısı hiçbir raporda bulunamadı; ölçülmüş karne yukarıdaki **21/78/3**'tür (sabah 33–36 raporları 30/61/10 idi; düşüş gerileme değil, "kriter üründe arandı" — 57). Bu belge ölçümü esas alır.

**57 sonrası (08-20 dalgaları) ölçümle kapanan/ilerleyen kalemler** (frontend-kalan-45-plani.md §8–9 + raporlar):
- **T-083 → TAM** (66: manifest_batch, 16 test; FE 2N→1 istek)
- **T-123 → TAM** (74: RUM 72 girişte canlı; gerçek vitals DB'de)
- **T-033 → TAM** (77: TS PolicyEngine 393/393 parite)
- **T-141 çekirdek** (75: panel E2E 6 koşuyor/2 gerekçeli skip, 4 yeni kusur buldu; unit 862/862)
- **T-115 → TAM'a yakın** (76: 88 kutu drift 0, gecelik workflow — commit İNSAN'da)
- **T-114 sunucu kapısı KAPANDI** (65: 417/200 canlı, iki katman, vacuity 3 kırmızı)
- **T-061/065 üretim yolu** (73: LQIP/dominant üretiliyor; uçlara akış 1+2 satır açık)
- **T-042 güvenlik yarısı** (64: hassas-ikiz tek-kapı; sızıntı envanteri silme kararında)
- **T-055 kabul paketi BUGÜN oluşturuldu** (83-w6: `tests/acceptance/` — konteynerde Local **10 test GEÇTİ**, S3'lü 3 kip gerekçeli skip) — 3 YOK'tan biri kapandı.

**Engelleyen dağılımı (57):** AJAN 47 · zaten TAM 21 · **ARAÇ 16** (libvmaf · boto3 · spectral · axe-core[tarayıcı] · tesseract · jsonschema · TS SDK · Postman — "tek imaj rebuild üç görevi açar") · **KARAR 9** · **İNSAN 9**.

**İzlenebilirlik (docs/test/traceability.md, 2026-08-20 07:31 + 68):** 202 gereksinim; en az bir teste bağlı **82 (%40,6)**; kapsanmayan **120 (%59,4)**; Python 144 dosya/3.391 fonksiyon; FE 1.152 koşan test, 34 etiket; vacuity kanıtlı.

---

## 2. Açık karar listesi (KARAR sahibine)

| # | Karar | Ölçülmüş durum |
|---|---|---|
| 1 | **VMAF eşiği ↔ INV-05 fayda kapısı** | Gerçek 1080p'de aynı anda sağlanamaz: fayda bütçesinde en iyi VMAF ≈86–89; 92,11 için +%20,5 şişme (39 §4.2). Üç seçenek bedelleriyle 56 §4.3/57b §5'te. Bugün ölçülemez: imajda libvmaf yok. |
| 2 | **K7 kota çelişkisi** | "Rendition'lar kotadan sayılsın" ↔ ADR-0009 "türevler File açmaz". Kapak videosu başına ~6 nesne → kota ~6× hızlı dolar (16 §4.1). |
| 3 | **content_rules eşikleri** | `TRIGGER_RATE_MEASURED_UNLABELED`; FP oranı hiçbir kural için bilinmiyor; **~200 tetiklenmenin insan etiketi** gerekiyor (57a T-025). `extreme_blur` canlı görsellerin %1,70'ini gizlerdi (bütçe FP<%1). |
| 4 | **T-105 C/E crop ayrışması** | C: 104/120 sapan (3704 px) — sunucu oran zorluyor; E: 86/120 (3481 px) — panel taban bölge. Bilinçli politika farkı; öneri: önizleme sunucunun kutusunu çizsin (56 §6.7). |
| 5 | **tus / Faz 8 TS SDK** | Sunucuda tus YOK, `Idempotency-Key` YOK (0 isabet); Uppy gerekçeli tercih kayıtlı. Kararlar: tus sunucusu kurulacak mı · OpenAPI'den tipli TS SDK üretilecek mi (44 §10, 56 §5.2, plan Kova C/D). |
| 6 | **Hassas-ikiz türev SİLME** | Sızıntı envanteri üretildi ve **temizlenMEDİ** (64 EK): 1 Asset + 1 Version + 10 Rendition, 315.836 B, public yol kapatıldı; "silme/maskeleme kararı ve manifest etkisi ayrı iş — veri kaybı riski". |
| 7 | **RU/AR çeviri yöntemi** | Medya ekranlarında **766/917 anahtar eksik (%83)** (61e). Makine çevirisi mi, insan çevirmen mi? (plan Kova D). Not: görev metnindeki "logistics çevirisi" diye bir kalem plan dosyasında YOK; "logistics" yalnız medya slotu olarak geçiyor (`logistics.provider_logo` — LIVE_SOURCES'ta kayıtlı değil, 3 kolonu ÖLÇÜLEMEDİ; 00-upload-slot-envanteri:139). |
| 8 | **Compliance Officer KYC erişimi** | permlevel-0 read satırı yok; genişletmek üründe karar (28 T4; 57 karar #5). |
| 9 | **Poster kalite kapısı** | 122 KB tavanı ancak WebP q40'ta tutuyor (merdiven ölçümü 39 §8.1); merdiven uzatılsın mı? |
| 10 | **AV1** | %31,7 verimli ama fayda kapısını geçmiyor (ADR-0010: şimdi eklenmiyor — teyit ya da revizyon). |
| 11 | **hls.js** | Yeni bağımlılık; bugün yalnız yerli HLS (Safari/iOS) çalışır (plan Kova D). |
| 12 | **overrides / `save_intent`** | Her zaman 417; Link kısıtı kaldırıldı ama uçtan uca ölçülmedi; "karar verilmeden panelin overrides göndermesi anlamsız" (41 §8-1, 57c §0.4). |

## 3. İnsan kalemleri (imza öncesi)

| # | Kalem | Dayanak |
|---|---|---|
| 1 | **9+ faz kapanış imzası** — dosyalar hazır: `docs/closure/faz{0..13}-kapanis.md` (faz9/faz14 TASLAK) | 57 karar #9; bu dalga |
| 2 | **40 public PII dosyasının sınıflandırılması** (K-1 / A-2 KRİTİK) | 54 §2.1, 13 §4 |
| 3 | **UAT / satıcı pilotu** — plan hazır, koşulmadı | faz14-uat.md |
| 4 | **Go-live tatbikatı + geri dönüş provası** — runbook hazır (`docs/runbooks/media-go-live.md`), tatbikat yapılmadı, süre ölçülmedi | faz14-golive.md; bu dalga |
| 5 | **~200 içerik-kuralı tetiklenmesinin elle etiketlenmesi** | 57a T-025 |
| 6 | **20 gerçek görselde elle crop karşılaştırması** | 56 §6.4 |
| 7 | **Retention dry-run raporunun incelenip onaylanması** | 57b T-055(4) |
| 8 | **DR provası**: yedek seti 0; geri yükleme süresi ölçülmedi | 57b T-054, backup-dr.md |
| 9 | **Git hijyeni (A-1 KRİTİK)**: ~105 untracked çıktı; `ci.yml` ve `drift-nightly.yml` commit+merge (schedule merge'siz koşmaz) | 54 G-2, 57b §1.8, 76 §5 |
| 10 | **İmaj rebuild kararı ve uygulaması** (libvmaf + boto3 + Node 22) + worker yeniden yaratma | 57; runbook §2 |
| 11 | **Prometheus/Grafana kurulumu + promtool + 16 runbook dosyası** | 42 §6.3/§10 |
| 12 | **Drift bildirimi için webhook/Slack kanalı** | 76 §4 |
| 13 | **Üretim erişimi** (K-3: prod ffmpeg; prod nginx sertleştirme doğrulaması) | 54 §2.1; 70; memory: nginx prod'a ulaşmadı |

## 4. Bilinen kusur / borç listesi

**Kritik (13 §4 + güncel):**
- **A-1**: Faz 3–14 çıktıları git'te untracked (105 dosya) — kaybolma riski.
- **A-2**: KVKK D-2, 40 dosya sınıflandırılmamış; `_is_protected_pii` 0/4.426.
- **A-13**: 2400 px hedef ↔ 2000 px tavan ↔ 30 gün arşiv = geri dönülemez piksel kaybı riski.
- Tüm A-1…A-13'te "SAHİP ATANMADI, hedef tarih yok".

**Teslim/performans borçları:**
- **LQIP eski dosyalarda yok ve uçlara akmıyor**: 6 eski Media Version boş kaldı (73 backfill "hala bos: 0" — yeniden işleme ister); `get_manifest` `"lqip": ""` döndürüyor, `manifest_batch` version_meta taşımıyor (73 §3.2, düzeltme 1+2 satır); FE'de lqip/blurhash 0 sonuç (57d T-120).
- **products.html LCP 6352 ms** (bütçe 2500; ~5 MB ham görsel — boru hattı açılmadan tutturulamaz) · **categories.html CLS 0,5396** (0,5394'ü tek footer) (62).
- Preload üretim yoluna bağlı değil (`preload_link()` yazılı, çağıran 0); `/` ve categories'te LCP öğesi çerez bandı (62, 61g).
- **RUM montaj kapsamı**: canlı ama düşük hacim; `sampleRate: 0.1` ölçüme dayanmıyor; bundle etkisi ölçülmedi (74 §8); INP saha verisi henüz birikmedi.
- sizes ≤%25 sapma kriteri (currentSrc↔gerçek genişlik) ölçülemedi (12 §4).

**Boru hattı/panel kusurları (W5 kuyruğu, 75):**
- `MediaUploader` hiçbir route'a bağlı değil → min-boyut kapısı canlıda ölü; **64×64 PNG 200 ile kabul edildi**.
- **Megapiksel-bomba kaçış aralığı (GÜVENLİK)**: Pillow tavanı (~89 MP) üstünü iddia eden PNG başlığı boyut 0 okunup **200 ile kabul**; yalnız 80–89 MP penceresi yakalanıyor.
- İstemci dedup uyarısı görsellerde yapısal ölü (orijinal sha ↔ sunucu WebP sha).
- `CropStudioModal` `:asset`'siz mount → kütüphaneden `save_intent` çağrılamaz.
- `media/trash.py` `..` alt-dize hatası: 8 dosya çöpe atılamaz/geri alınamaz/optimize edilemez (17).
- Tek seferlik: ilerleme kaydı kayboldu (job_key e70763f284aa, tekrarlanamadı) (69 §5.3).

**Test/altyapı borçları:**
- `test_retention_gc` 1 bayat fail (hooks kaydı artık var — testin beklentisi güncellenmeli) (55 Y-5).
- Suite kararsızlığı ≈%5,6 (18 koşumda 1 FAILED, adı kaybedildi) (14 B1).
- TS parite kapıları konteynerde sessiz/kırmızı (Node 20) (57b T-041, 65 §6).
- 12 değişmezin 7'si adsız, INV kapsam haritası yok (57b T-067).
- İşçi kaynak limiti: yalnız `nice`; RLIMIT/eşzamanlılık tavanı yok; `isolation.py` üretim ffmpeg yollarına bağlı değil (57b, 57d T-130).
- B-8 kodek çelişkisi: sözleşme VP9/WebM ↔ kod H.264/MP4 ↔ manifest WebM birincil (18 §8, 14 B3).
- HLS merdiveninde fayda kapısı yok (+%25,7 basamak) (39 §6.3).
- 8 metrik toplayıcısız (en kritik 3 KVKK alarmı sessiz kalır) (42 §6.4).
- boto3/jsonschema/pyvips imajda kalıcı değil; `docker/` versiyonsuz (23 §2.1–2.2, 54 §5.4).
- `chunked.cleanup()` zamanlayıcısız (44 §3).
- T6 kod açığı: `media_access.download` blob-satır bağını doğrulamıyor (29).
- Sızıntı envanteri artıkları + panel E2E 11 File kaydı + 8 `@test.local` kullanıcı temizlik bekliyor (64, 75, 57).

## 5. Kapanış koşulu

Bu taslak, şu üçü tamamlandığında "nihai kabul dosyası" olur:
1. §2'deki kararların verilmesi (her karar bir ADR ya da CR kaydıyla),
2. §3'teki insan kalemlerinin kapatılması (özellikle 1, 2, 3, 4),
3. Faz kapanış dosyalarındaki "KARŞILANMADI" kalemlerinin ya kapatılması ya da bilinen-kusur olarak açıkça kabulü.

## 6. İmza — **TASLAK, imzaya sunulmaz**

```
Geliştirme sorumlusu: ______________________   Tarih: ______________   İmza: ______________
QA sorumlusu:         ______________________   Tarih: ______________   İmza: ______________
Platform yöneticisi:  ______________________   Tarih: ______________   İmza: ______________
```

## Kaynak raporlar
57-durum-anlik-goruntu.md · 57a–57d · 13-faz14-kabul.md · 14-nihai-denetim.md · 68-w3a-izlenebilirlik.md · 62 · 63–66 · 69–77 · 54–56 · 16 · 17 · 18 · 23 · 28 · 29 · 38 · 39 · 41 · 42 · 44 · 61a–61g · docs/plans/frontend-kalan-45-plani.md · docs/test/traceability.md · docs/closure/faz{0..14}-kapanis.md

## Karar günlüğü — 2026-08-20 (kullanıcı kararları)

| Karar | Sonuç | Not |
|---|---|---|
| RU/AR `logistics` çevirisi (~567 anahtar ×2) | **ERTELENDİ** | Kullanıcılar İngilizce fallback görüyor (kırık değil); ayrı çeviri projesi |
| Yükleme protokolü tus (T-081/082) | **Mevcut resumable KALIYOR** | Kendi resumable'ımız çalışıyor; tus'un kullanıcı getirisi düşük, maliyeti yüksek. ADR-0020: REDDEDİLDİ |
| VMAF eşiği (T-072, ADR-0021) | **93'te KALIYOR** | Gerçek ölçüm: 89,31 red / 96,655 kabul. Yüksek kalite garantisi tercih edildi; 89-92 arası video ham (PASSTHROUGH) geçer |
| Golden fixture git saklama (T-006) | **GİT'E KOYULMUYOR** | Deploy/checkout hızı korunur (kullanıcı kararı: 26,5 MB'ı her clone'a bindirme). Kanıt manifest.json'da (sha256+köken, git'te); ilgili testler taze checkout'ta @skipUnless ile atlanır — .gitignore'a belgelendi |

## Karar günlüğü — ek (2026-08-20, ikinci tur)

| Karar | Sonuç | Not |
|---|---|---|
| Hassas-ikiz 10 türev (BE-2 bulgusu) | **DOKUNULMUYOR** | Kullanıcı beyanı: bunlar DEV test/seed görselleri — gerçek hassas-ikiz değil. Üretim koruması zaten eklendi (BE-2, `_resolve_scope`), prod'da gerçek hassas-ikiz oluşamaz. Dev artığı, temizlik gerekmez |
| Önizleme klip mount (ProductVideoSection ölü kod) | **BAĞLANACAK** | Kod işi — kanca yazıldı (K3), sayfaya mount edilecek |
| K7 kota: türevler kotaya sayılsın mı (ADR-0022) | **TÜREVLER DE SAYILIR** | Kod işi — kota hesabına türev baytları eklenecek. ADR-0022: türev-dahil kota |
| TS-strict + Vitest göçü (T-090) | **REDDEDİLDİ** | JS + node:test kalıyor; 910 test yeşil, göç yüksek riskli/getirisiz. ADR: JS korunur |

## Karar günlüğü — ek (2026-08-20, üçüncü tur)

| Karar | Sonuç | Not |
|---|---|---|
| content_rules eşikleri (T-025, NSFW/blur/filigran) | **KABUL — insan onayı ile karşılanıyor** | KULLANICI NOTU (aynen): "content_rules ayarlarında zaten muhtemelen bunu AI ileride bağlanıp onun kontrol etmesi sağlanacak. Şimdi admin zaten ürünleri onayladığı için (görüp insan onaylıyor) yapıldı say." → T-025 bugün İNSAN-ONAYLI içerik denetimiyle karşılanıyor (admin her ürünü görüp onaylıyor); otomatik eşik/AI ileriki iş. Bu kalem KAPALI sayılır |
| Crop C/E oran davranışı (T-105) | **GELİŞTİRİLECEK — before/after + auto/manuel** | Kırpma oranı kare KALIYOR (doğru). Panel kullanıcıya before/after karşılaştırma göstersin (C/E sapması sürpriz olmasın) + auto (smart crop/focal) ve manuel ayar modu; gerçek ürün görselleriyle. Kod işi |

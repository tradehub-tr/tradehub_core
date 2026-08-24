# Yükleme doğrulama sözleşmesi

**Plane:** MOGEM-569 · **Kapsam:** `[G-16]-04 upload validation` ·
**Son doğrulama:** 2026-08-24

Bu belge bir ikinci kural seti değildir. Çalışma zamanı doğruluk kaynakları:

- genel dosya kapısı: `tradehub_core/media/upload_policy.py`,
- bozuk/tehlikeli içerik: `tradehub_core/media/pipeline/security/content_gate.py`,
- slot kuralları: `tradehub_core/media/pipeline/policy/slots/*.json`,
- video motor kararı: `tradehub_core/media/pipeline/policy/video_decision.json`.

## Kabul kuralları

| Alan | Kuralın sahibi | Uygulama zamanı |
|---|---|---|
| İzinli uzantı ve genel tür | `upload_policy.EXTENSIONS` | Dosya kaydı açılmadan |
| Slot MIME/uzantı/bayt sınırı | `slots/<slot>.json → accept` | Dosya kaydı açılmadan |
| Platform + tür boyut tavanı | `upload_policy.effective_max()` | İstek/parçalı oturum başında ve birleşim sonunda |
| Magic-byte uyuşması, çalıştırılabilir/polyglot içerik | `content_gate.inspect()` | Tam orijinal bayt geldikten sonra, kayıt öncesi |
| Kesik/bozuk görsel ve sahte OOXML kabı | `content_gate.inspect()` | Tam orijinal bayt geldikten sonra, kayıt öncesi |
| Görsel çözünürlük/oran/adet | `PolicyEngine.evaluate()` | Kayıt ve dönüşüm öncesi |
| Video gerçek çözünürlük, süre ve bitrate | `video.validation.validate()` + `PolicyEngine` | Kayıttan sonra, worker'da ffprobe sonrası |
| Video akışı, mutlak 4K/15 dk sınırı | `video_decision.json` | Kayıttan sonra, worker'da ffprobe sonrası |
| Video/ses codec uyumluluğu | `video_decision.json` | Kayıttan sonra; uyumsuz codec ret değil `TRANSCODE` |

Efektif boyut tavanı her zaman en dar sınırdır: platform, genel medya türü ve
slot tavanlarından hiçbiri diğerini gevşetemez. Parçalı yükleme, ilan edilen
boyutu oturum açılırken; gerçek boyut ve içeriği bütün parçalar birleştikten
sonra tekrar denetler.

## Ön yükleme / son yükleme sınırı

Dosya adına, ilan edilen boyuta veya ilk baytlara bakarak güvenilir biçimde
ölçülebilen her şey **kayıt öncesinde** reddedilir. Böyle bir ret HTTP 417,
`upload_error` ve mesaj sonundaki `[code]` işaretiyle senkron döner; geçersiz
dosya için `File` kaydı açılmaz.

Video süresi ve codec adı uzantıdan tahmin edilmez. Bunlar izole ffprobe
koşumundan sonra **kayıt sonrası** değerlendirilir. Worker iki kararı birlikte
uygular:

1. motor kararı: `PASSTHROUGH`, `REMUX`, `TRANSCODE` veya `REJECT`,
2. slot kararı: süre, çözünürlük, oran, bitrate ve slotun aksiyon seviyesi.

Herhangi biri reddederse çıktı üretilmez; `Media Asset.state=rejected`,
`rejection_code`, `rejection_note`, başarısız `Media Processing Job.error_code`
ve `File.th_media_video_status=failed` aynı kapanışta yazılır. Satıcıya ait
geçmiş API'si `rejection_code` ile `rejection_note` alanlarını döndürür.

## Slot örnekleri

- `company.cover_video`: 6–60 saniye ve en az 1280×720; ihlal sert rettir.
  Kodlar politikadaki `video.validation_codes` listesinden gelir
  (`cover_video_too_short`, `cover_video_too_long`,
  `cover_video_resolution_too_low`).
- `product.video`: 33 saniye kuralı uyarıdır; dosya kabul edilir. Genel motorun
  15 dakika sınırı yine sert rettir.
- H.264 dışındaki kaynak video veya AAC/MP3 dışındaki ses codec'i kullanıcı
  hatası sayılmaz; teslim biçimine yeniden kodlanır.
- ffprobe dosyayı okuyamazsa motor `video_probe_failed` ile reddeder. Ölçüm
  yokken videoyu kurallara uygun varsaymak yasaktır.

## Hata sözleşmesi

Senkron yükleme retleri `docs/api/error-catalog.json` içindeki
`upload_*` kodlarını kullanır. Video worker retleri motor tablosundaki
`video_*` veya slot politikasının `validation_codes` alanındaki kodları
kullanır. Kullanıcı davranışı metne göre değil koda göre belirlenir; metin
yalnız açıklama ve düzeltme yönlendirmesidir.

## Otomatik kanıt

- `test_media_security_gate.py`: kötücül/bozuk fixture korpusu ve yanlış
  pozitif koruması,
- `test_media_upload_slot_gate.py`: kayıt öncesi slot reddi ve HTTP hata
  sözleşmesi,
- `test_media_video_validation.py`: süre, çözünürlük, boyut, codec ve ffprobe
  kararlarının birleşmesi,
- `test_video_servis.py`: slot reddinin gerçek worker'da Asset/Job/File
  durumlarına yazılması,
- `test_seller_media_history.py`: kodlu ret açıklamasının kiracı-süzgeçli API
  yanıtında bulunması.

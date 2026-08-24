# MIME ve EXIF işleme standardı

**Plane:** MOGEM-580 · **Durum:** uygulanmış · **Doğrulama:** 2026-08-24

Bu belge dosya uzantısı, gerçek içerik türü, boyut/çözünürlük sınırları ve
EXIF metadata davranışı için tek insan-okunur kapanış sözleşmesidir. Çalışma
zamanındaki kararın sahipleri `media/upload_policy.py`,
`media/pipeline/security/content_gate.py`, `media/pipeline/image/probe.py`,
`media/pipeline/image/normalize.py` ve `media/exif_vault.py` dosyalarıdır.

## Yükleme ve normalize sırası

1. `upload_policy.check()` dosya adını, uzantı sınıfını, efektif bayt tavanını
   ve tehlikeli içeriği denetler.
2. `content_gate.inspect()` magic byte üzerinden gerçek türü ölçer; uzantı ile
   bilinen içerik türü uyuşmazsa varsayılan davranış reddir.
3. Slot varsa `check_slot()` MIME, uzantı, geometri ve slot sınırlarını aynı
   politika kaydından uygular.
4. Kaynak EXIF/IPTC benzeri bilgi, DocType mevcutsa `Media Metadata Vault`
   içinde Password alanına yazılır; özet SHA-256 ile bütünlük izi taşır.
5. `normalize()` yön etiketini önce piksellere uygular, sonra yayın metadata
   politikasını yürütür ve ürettiği dosyayı yeniden açarak doğrular.

İstemcinin gönderdiği `Content-Type` karar kaynağı değildir. Uzantı ve
magic-byte MIME ayrı ölçülür; böylece örneğin PNG baytı taşıyan `.jpg` bir
JPEG olarak servis edilemez.

## Boyut ve çözünürlük

| Sınıf | Politika tavanı |
|---|---:|
| Görsel | 25 MiB |
| Video | 200 MiB |
| Belge | 50 MiB |
| Diğer/bilinmeyen | 50 MiB |

Gerçek yükleme tavanı `min(politika tavanı, Frappe max_file_size)` değeridir.
Görseller decode edilmeden önce başlıktan ölçülür; varsayılan sert güvenlik
tavanı 80 MP'dir. Slotların kısa kenar, alan, oran ve daha dar bayt sınırları
`pipeline/policy/slots/*.json` içinde ayrıca uygulanır.

## EXIF ve hatalı metadata politikası

| Senaryo | Davranış |
|---|---|
| EXIF orientation 2–8 | Normalize öncesi piksellere uygulanır; çıktı etiketi kaldırılır |
| GPS | Yayınlanan her çıktıda koşulsuz silinir |
| EXIF/XMP | Varsayılan yayın politikasında silinir |
| ICC | Renk doğruluğu için varsayılan korunur; slot açıkça isterse silinir |
| Kaynak metadata | Yetki-sınırlı, şifreli kasada tutulur; public API'ye verilmez |
| Geçersiz orientation | `1` kabul edilir |
| Geçersiz `DateTimeOriginal` | Boş kabul edilir; Datetime alanına taşınmaz |
| Okunamayan GPS IFD | GPS yok sayılır; public çıktı yine metadata temizlenerek üretilir |
| Kasa/metadata okuma hatası | Hata loglanır, kasa yazımı `False` döner; yayın hattı EXIF/GPS temizliğini sürdürür |

Bu hata davranışı bilinçlidir: özel kasaya kaydetme sorunu bir dosyada kişisel
metadata'nın public çıktıya sızmasına yol açmaz. Public taraf her durumda
normalize politikasından geçer.

## Otomatik kanıt

`tradehub_core.tests.test_media_mime_exif` aşağıdaki kapanış koşullarını tek
modülde sabitler:

- magic byte MIME'ın uzantı beyanından ayrı ölçülmesi,
- bilinen uzantı–içerik uyuşmazlığının reddedilmesi,
- sınıf bazlı bayt tavanları,
- kaynak GPS'in kasada görülüp yayın çıktısından kaldırılması,
- bozuk orientation/tarih/GPS alanlarının güvenli davranışı,
- kasa kaydının politika sürümü ve SHA-256 bütünlük izi,
- kasa hatasının medya işini düşürmeden loglanması.

Tam regresyon kapısı ayrıca `test_media_security_gate`, `test_image_probe`,
`test_image_normalize`, `test_media_upload_slot_gate` ve
`test_pipeline_bridge` modülleridir.

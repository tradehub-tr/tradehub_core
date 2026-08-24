# ADR — Mimari Karar Kayıtları

Bu dizin, medya motoru çalışmasında **verilmiş** kararları kaydeder. ADR bir
öneri ya da plan belgesi değildir: her dosya, alınmış bir kararın bağlamını,
elenen seçeneklerini, gerekçesini ve **hem olumlu hem olumsuz** sonuçlarını
yazar.

## Bu dizinin kuralları

1. **Arkeoloji, icat değil.** Buradaki hiçbir karar bu dizin için üretilmedi.
   Her ADR bir rapora, bir standart belgesine, bir politika JSON'una ya da bir
   kod yorumuna dayanır ve en az bir **dosya:satır** veya rapor atıfı taşır.
2. **Sayı varsa sayı yazılır**, kaynağıyla birlikte. "Daha hızlı" değil,
   "10,45 sn → 3,50 sn (`docs/reports/17-t028-backfill-plani.md` §4.3)".
3. **Doğrulanamayan iddia "doğrulanmadı" diye işaretlenir.** Ölçülmemiş bir şey
   ölçülmüş gibi yazılmaz.
4. **Karar ölçümle değiştiyse dönüş gösterilir.** Bu depodaki en güçlü desen
   budur: karar önce sayısal bir **tetikle** yazılır, sonra ölçüm tetiği
   çalıştırır ve gerekiyorsa öneriyi devirir. Elenen seçenek tabloları silinmez.
5. **Sonuçlar bölümü olumsuzu da yazar.** Bedelini yazmayan bir ADR eksiktir.
6. **Geri dönüş yolu zorunludur.** Tetik, uygulanacak rollback ve reddedilen
   seçeneğin hangi ölçümle yeniden açılacağı açıkça yazılır.

## Biçim

`Bağlam · Seçenekler · Ölçüm verisi/Gerekçe · Karar · Sonuçlar (olumlu VE
olumsuz) · Geri dönüş yolu · Durum · Tarih`

Dosya adı: `NNNN-kebab-baslik.md`. Numara bir kez verilir, değişmez. Bir karar
geçersizleşirse ADR **silinmez**; durumu güncellenir ve yerine geçen ADR'ye atıf
verilir.

---

## Dizin

| # | Karar | Durum | Ana dayanak |
|---|---|---|---|
| [0001](0001-icerik-adresli-depolama.md) | İçerik-adresli dosya adlandırma (`sha256[:32]` + shard) | Kabul · **bedeli açık** | `media/naming.py:55,66,102,124` · `docs/reports/19-d2-hash-ortusme.md` · `21-t030-mimari-inceleme.md` M-18 |
| [0002](0002-bayrak-arkasinda-paralel-hat.md) | Yeni hat bayrak arkasında, eski hattın yanında | Kabul · bayraklar 0 | `media/pipeline_flags.py` · `docs/reports/15-dalga-a-dogrulama.md` §4c, §5 |
| [0003](0003-ayri-app-degil-tek-monolit.md) | Medya motoru ayrı app değil, kütüphane | Kabul · **uygulama saptı** | `media/pipeline/__init__.py` · `21-t030-mimari-inceleme.md` M-01 |
| [0004](0004-saf-cekirdek-frappe-kabugu.md) | Saf çekirdek / Frappe kabuğu: `api/` dışı `import frappe` yok | Kabul · testle kilitli | `media/pipeline/__init__.py` · `tests/test_state_machine.py` |
| [0005](0005-media-rendition-profile-link-degil-data.md) | `Media Rendition.profile` `Link` → `Data` | Kabul · A/B ile kanıtlı | `media/pipeline_bridge.py:610-622` · `media_rendition.json:43-44` |
| [0006](0006-adaptif-kalite-dongusu.md) | Hedef SSIM'e ikili arama, encode bütçesi 4, aralık (70,95) | Kabul · **maliyeti yeniden açılmalı** | `quality/ssim.py:62,78` · `11-faz1-arge.md` §T-013 · `17-t028-backfill-plani.md` §4.3 |
| [0007](0007-fayda-kapisi-inv-05.md) | Fayda kapısı (INV-05): kaynaktan büyük türev yazılmaz | Kabul · **video hattını kilitliyor** | `image/render.py:42,885-907` · `video_decision.json:30` |
| [0008](0008-pillow-pyvips-yerine.md) | Pillow'da kal, pyvips reddedildi (+ `draft()`) | Kabul · **`draft()` uygulanmadı** | `docs/reports/05-kutuphane-benchmark.md` (360 koşum) |
| [0009](0009-turevler-file-kaydi-acmaz.md) | Türevler için `File` kaydı açılmaz | Kabul · K7 bağlantısı ADR-0022 ile çözüldü | `media/pipeline_bridge.py` · `media/files.py` |
| [0010](0010-av1-simdi-eklenmiyor.md) | AV1 şimdi eklenmiyor | Kabul · **sayısal tetikle yeniden açılır** | `docs/reports/22-t072-vmaf-av1.md` §5.4–5.6 |
| [0011](0011-h264-birincil-vp9-degil.md) | Video birincili H.264/MP4, VP9 değil | Kabul · **üretim hattı henüz uymuyor** | `policy/video_decision.json:250-256` |
| [0012](0012-logo-kayipsiz-webp-merdiveni.md) | Logo: kayıpsız WebP, 40 KiB tavanı, merdiven 4 → 5 basamak | Kabul · **`max_bytes` yaptırımsız** | `docs/standards/logo.md` §13 K3/K4 · `image/render.py:934` |
| [0013](0013-logo-bicim-ve-oran-kabulu.md) | Opak JPEG logo uyarıyla kabul; oran bandı 1:2…2:1 kalır | Kabul · **ikisi de ölçümle** | `docs/standards/logo.md` §13 K1/K2 · `08-canli-olcum.md` §2.1 |
| [0014](0014-yikici-isler-cift-kapi-kuru-kosum.md) | Yıkıcı işler varsayılan kuru koşum + iki bağımsız kapı | Kabul · ölçüldü | `hooks.py:154,160` · `docs/reports/26-t053-saklama-gc.md` §0 |
| [0015](0015-s3-yazildi-varsayilan-kapali.md) | S3/mirror/tiered yazıldı, varsayılan kapalı, düşüş raporlanır | Kabul · üretimde kapalı | `storage/s3.py:11-18` · `23-t051-s3-adaptor.md` · `25-t051-depolama-ayarlari.md` |
| [0016](0016-politika-veridir-kod-degil.md) | Slot politikası VERİdir, kod değil | Kabul · testle doğrulanıyor | `policy/engine.py` başlığı · `image/render.py` başlığı · `21-t030-mimari-inceleme.md` M-11/M-12/M-14 |
| [0017](0017-saliency-esik-ustunde-ve-oneri.md) | Saliency eşik üstünde ve yalnız öneri | Kabul · üç yöntem çalışıyor, insan kalibrasyonu açık | `14-smartcrop-karsilastirma.md` (50/50, insan etiketi 0) |
| [0018](0018-hls-js-istemci-oynatici.md) | HLS oynatma için `hls.js` eklenir (MSE fallback) | **Kabul (2026-08-20)** · uygulama W7'de (rapor 85) | `81-w6-video-kosum.md` §7 · `MediaVideo.vue:27-31` |
| [0019](0019-hls-basamaginda-fayda-kapisi.md) | HLS basamaklarına fayda/bütçe kapısı | **Kabul (2026-08-20)** · uygulama W7-1'de | `81-w6-video-kosum.md` §4 · `56-d3-faz6-10-kapanis.md` §4.5 |
| [0020](0020-tus-yerine-mevcut-chunked.md) | Devam edebilir yükleme: tus mu, mevcut `chunked.py` mi | **ÖNERİLDİ · karar BEKLİYOR** | `44-t081-yukleyici.md` §3 · `61e-fe-denetim-faz8-9.md` |
| [0021](0021-vmaf-esigi.md) | VMAF eşiği (93 ↔ INV-05 çelişkisi; gerçek ölçüm 89,34) | **ÖNERİLDİ · karar BEKLİYOR** | `56-d3-faz6-10-kapanis.md` §4.2–4.4 · `81-w6-video-kosum.md` |
| [0022](0022-k7-kota-turev-sayimi.md) | K7 kota: türevler File açmadan tenant kotasına sayılır | Kabul · seçenek D, MOGEM-573 | `media/files.py` · `105-d2-kota-turev.md` · ADR-0009 |
| [0023](0023-kavram-basina-tek-sahip.md) | Kavram başına tek sahip: çekirdek ↔ motor; sözleşme md aynı PR'da; sözleşmeler test olarak; bayrak öncesi 3 ön koşul | **ÖNERİLDİ · imza bekliyor (Metin + Ahmet)** | 21 Ağu ortak çatı denetimi · `tests/test_media_contracts.py` · `scripts/check_media_contract_docs.py` |
| [0024](0024-istemci-medya-kutuphane-seti.md) | Native probe + browser-image-compression + MediaBunny; bütçe aşımında server fallback | Kabul · gerçek cihaz kalibrasyonu açık | `15-client-butce.md` · 7/7 + 10/10 test |
| [0025](0025-cdn-icerik-adresli-teslim.md) | Hash URL immutable; purge yalnız aynı-URL overwrite'ta | Kabul | `18-depolama-arge.md` · `27-t052-cdn-teslim.md` |
| [0026](0026-video-karar-tablosu-json.md) | Video codec kararları sürümlü JSON verisidir | Kabul | `16-video-karar.md` · Faz 7 467/467 |
| [0027](0027-dpi-piksel-politikasi.md) | DPI metadata; pixel cap bağımsız; upscale yok | Kabul | `12-dpi-prototip.md` · 5/5 format |
| [0028](0028-medya-islem-izolasyonu.md) | İş başına child process + RLIMIT_AS + timeout | Kabul | `17-guvenlik-arge.md` · 10/10 malicious, 36/36 izolasyon |

> **ÖNERİLDİ durumundaki ADR'ler (0020, 0021 ve 0023) bu dizinin "verilmiş kararlar"
> kuralının bilinçli istisnasıdır** (2026-08-20, rapor 88): üçü de iki kez
> ölçülmüş, karar bekleyen açık kalemlerdir. Karar TASLAK gövdede
> **uydurulmamıştır** — seçenekler ölçülmüş bedelleriyle taşındı, "Karar"
> bölümleri BEKLİYOR der. Karar verildiğinde durum satırı güncellenir.

## T-019 zorunlu konu kapsaması

| Zorunlu tema | ADR | Durum |
|---|---|---|
| Image engine | 0008 | Kabul |
| Video engine | 0011 | Kabul |
| İstemci kütüphane seti | 0024 | Kabul; cihaz kalibrasyonu açık |
| Birincil depolama / opsiyonel S3 | 0001, 0015 | Kabul; local varsayılan |
| CDN | 0025 | Kabul |
| Smartcrop | 0017 | Öneri-only kabul; insan etiketi açık |
| Uyarlanabilir kalite | 0006 | Kabul |
| Video karar tablosu biçimi | 0026 | Kabul |
| DPI/piksel politikası | 0027 | Kabul |
| Güvenlik izolasyonu | 0028 | Kabul |

28/28 ADR'de ayrı `Geri dönüş yolu` bölümü vardır. Teknik ADR setinin açık
kalemleri belge eksikliği değildir: T-014 için 50 insan etiketi, T-015 için
fiziksel cihaz laboratuvarı ve 0020, 0021 ile 0023 için insan kararı/imzasıdır.

---

## Kararlar arası gerilimler (bilinçli, kayıtlı)

Bu ADR'ler birbiriyle çelişmiyor ama üçü **kabul edilmiş bedel** taşıyor ve
birbirine bağlı:

- **0001 ↔ güvenlik.** İçerik-adresleme dedup'u bedava getirdi; aynı mekanizma
  çok kiracılı bir okuma sızıntısı doğurdu (33 çok sahipli özel URL, 29'u
  hassas). Karar geri alınmıyor, düzeltmesi ayrı görev.
- **0009 ↔ K7 kota kararı (çözüldü).** Türevler `File` kaydı açmıyor;
  `Media Rendition.bytes → Media Asset.owner_seller` ikinci sayacıyla tenant
  kotasına katılıyor. **ADR-0022 seçenek D kabul edildi** (2026-08-24).
- **0007 ↔ 0010/0011.** Fayda kapısı doğru çalışıyor ve bu yüzden video hattı
  bugün **hiç çıktı vermiyor**. Kapı gevşetilmedi; kök neden (hız denetimi)
  düzeltilmedi. **Güncelleme (2026-08-20, rapor 81):** kapı ilk kez gerçek
  çıktıyla sınandı ve **tuttu** (%11,44 ≥ %10) — "hiç çıktı vermiyor" ifadesi
  eskidi; VMAF eşiği tarafı ADR-0021'de karar bekliyor.

## Yazılamayan kararlar

Ölçüm ya da gerekçe bulunamadığı için ADR yazılmayan kararlar
`docs/reports/30-faz1-adr-kapanis.md` §3'te listelidir. En önemlisi **S-03
("Yeni DocType açılmaz")**: karar çürüdü (5 DocType kurulu) ama terk edilme
gerekçesi hiçbir belgede bulunamadı.

#!/usr/bin/env python3
"""T-006 — fixture korpusunu ÖLÇER ve manifest.json'u yazar.

Manifest'teki hiçbir sayı elle yazılmaz: `expect` bloğu BEYAN, `olculen`
bloğu ÖLÇÜM'dür ve betik ikisini karşılaştırır. Uyuşmazlık `dogrulama:
"KALDI"` olarak işaretlenir ve çıkış kodu 1 olur.

Girdi (konteynerde ölçülüp buraya kopyalanan kanıt dosyaları):
    tests/fixtures/media/live-probe.json   — engine.probe / engine.optimize /
                                             ffprobe / needs_transcode çıktıları

Kullanım:
    python3 scripts/build_fixture_manifest.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parents[1]
# 1ec9b5e göçü: testler `tests/` kökünden `tradehub_core/tests/` altına taşındı.
# Eski `ROOT/tests` yolu ölü kalmıştı (W9 T-032 ölçümü, 2026-08-20) — düzeltildi.
MEDIA = ROOT / "tradehub_core" / "tests" / "fixtures" / "media"
IMG = MEDIA / "images"
VID = MEDIA / "video"
MAL = ROOT / "tradehub_core" / "tests" / "fixtures" / "malicious"
CANLI = MEDIA / "live-probe.json"
MANIFEST = MEDIA / "manifest.json"

# --------------------------------------------------------------------------
# BEYAN TABLOSU
#
# expected_action, ilgili `slot` politikasının bugünkü hâline göredir:
#   process     — kabul edilir, motor türev/master üretir (uyarı olabilir)
#   passthrough — kabul edilir, motor DOKUNMAZ (bugünkü davranış)
#   reject      — kabul kapısında reddedilir
#
# `kural` alanı docs/srs/SRS-v1.0.md FR kodlarına ve slot politikasındaki
# alan adlarına atıf yapar.
# --------------------------------------------------------------------------

SPEC: dict[str, dict] = {
    # ---------------- görseller ----------------
    "p01_18mp_1mb.jpg": dict(
        cls="photo", slot="product.image", action="reject",
        expect=dict(format="JPEG", mode="RGB", width=5184, height=3456,
                    megapixels=17.92, bytes_max=1_400_000),
        kural=["FR-011", "FR-015", "require.allowed_ratios"],
        neden="Dokümanın P-01 tuzağı: küçük dosya (1 MB) ama 17,92 MP. Kabul "
              "kapısı megapikseli DOSYA BOYUTUNDAN değil başlıktan okumak "
              "zorunda; bayta bakan bir kapı bunu 'küçük dosya' sanıp geçirir. "
              "Oranı 3:2 olduğu için product.image bandında (1:1/4:5/3:4) "
              "değil → ret. RET GEREKÇESİ ORANDIR ve karar 18 MP'yi hiç "
              "decode etmeden verilmelidir.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08-canli-olcum.md §1.3 — canlıda >20 MP 179 dosya",
    ),
    "dpi_3000x3000_300dpi.tif": dict(
        cls="photo", slot="product.image", action="process",
        expect=dict(format="TIFF", mode="RGB", width=3000, height=3000,
                    dpi=(300, 300)),
        kural=["FR-029", "FR-030", "master.dpi_out"],
        neden="dpi-ve-cozunurluk.md'nin DOĞRU/YASAK vakası. 3000×3000@300dpi "
              "→ 2400×2400@72dpi olmalı (piksel korunur). YASAK olan "
              "720×720@72dpi: DPI oranını piksele uygulamak. Çıktı kenarı "
              "2400'ün altına inerse test KALIR.",
        kaynak="sentetik",
        canli="08 §1.1 — canlıda 11 TIFF var",
    ),
    "mode_cmyk.jpg": dict(
        cls="photo", slot="product.image", action="process",
        expect=dict(format="JPEG", mode="CMYK", width=1600, height=1600),
        kural=["master.colorspace=srgb"],
        neden="CMYK JPEG tarayıcıda yanlış renk verir. Master sRGB'ye "
              "çevrilmeli. engine.optimize bunu bugün yapıyor, to_webp "
              "yolu ayrı — ikisi de bu fixture ile denenmeli.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §1.1 — canlıda 38 CMYK dosya",
    ),
    "mode_rgba_alpha.png": dict(
        cls="transparent", slot="product.image", action="process",
        expect=dict(format="PNG", mode="RGBA", width=1200, height=1200,
                    has_alpha=True),
        kural=["accept.mime", "master.format=webp"],
        neden="Alfa kanalı zincir boyunca korunmalı; JPEG'e düşürülürse "
              "saydamlık düz siyah/beyaza döner. Türev WebP olduğu için "
              "alfa taşınabilir — bu fixture bunu kanıtlar.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §1.3 — canlıda 597 alfa kanallı dosya",
    ),
    "mode_palette_p.png": dict(
        cls="graphic", slot="product.image", action="process",
        expect=dict(format="PNG", mode="P", width=1200, height=1200),
        kural=["master.colorspace=srgb"],
        neden="Paletli (P) mod, RGB'ye çevrilmeden yeniden boyutlandırılırsa "
              "en yakın komşu kuantizasyonu yüzünden bantlanır. P → RGB "
              "dönüşümünün ölçek ÖNCESİ yapıldığını doğrular.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §1.1 — canlıda 74 paletli dosya",
    ),
    "mode_grayscale_l.png": dict(
        cls="graphic", slot="product.image", action="process",
        expect=dict(format="PNG", mode="L", width=1400, height=1400),
        kural=["master.colorspace=srgb"],
        neden="Tek kanallı görsel. 3 kanal varsayan bir dönüşüm zinciri "
              "burada patlar ya da sessizce renk katar.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §1.1 — canlıda 7 gri tonlama dosya",
    ),
    "geom_strip_400x4000.png": dict(
        cls="graphic", slot="product.image", action="reject",
        expect=dict(format="PNG", mode="RGB", width=400, height=4000),
        kural=["FR-015", "FR-016", "require.min_short_edge"],
        neden="Oran 1:10, kısa kenar 400. İki bağımsız kural birden ihlal "
              "ediliyor (kısa kenar < 1000 VE oran bandı dışı). Ret "
              "mesajının HANGİ kuralı söylediği de test edilir: kullanıcıya "
              "tek bir uygulanabilir düzeltme verilmeli (FR-062).",
        kaynak="sentetik",
    ),
    "geom_1x1.png": dict(
        cls="graphic", slot="product.image", action="reject",
        expect=dict(format="PNG", mode="RGB", width=1, height=1,
                    bytes_max=500),
        kural=["FR-015", "require.min_area"],
        neden="Dejenere alt sınır. Alan hesabı, oran bölmesi ve "
              "küçültme mantığının 1 pikselde sıfıra bölme / negatif boyut "
              "üretmediğini doğrular.",
        kaynak="sentetik",
    ),
    "exif_orientation6.jpg": dict(
        cls="graphic", slot="product.image", action="reject",
        expect=dict(format="JPEG", mode="RGB", width=1200, height=1600,
                    exif_orientation=6),
        kural=["FR-016", "master.orientation=apply_exif"],
        neden="SIRALAMA testi. Saklanan 1200×1600 → oran 0,75 = 3:4, "
              "product.image bandında KABUL. EXIF orientation=6 uygulandıktan "
              "sonra 1600×1200 → oran 1,333, bantta YOK → RET. Oranı "
              "transpose ÖNCESİ ölçen bir uygulama bu dosyayı YANLIŞLIKLA "
              "kabul eder. Bu fixture'ın tek ayırt edici özelliği budur.",
        kaynak="sentetik",
    ),
    "exif_gps.jpg": dict(
        cls="photo", slot="product.image", action="process",
        expect=dict(format="JPEG", mode="RGB", width=1600, height=1600,
                    has_gps=True),
        kural=["FR-039", "master.strip_metadata.gps"],
        neden="KVKK. Satıcının fabrika/ev konumu EXIF GPS bloğuyla sızar. "
              "Kabul edilir ama çıktıda GPS IFD'si BULUNMAMALIDIR. Bugün "
              "kod tabanında EXIF temizliği YOK (engine.py:116 yalnız yön "
              "uyguluyor) — bu fixture o boşluğun regresyon testidir.",
        kaynak="sentetik",
    ),
    "enc_progressive.jpg": dict(
        cls="photo", slot="product.image", action="process",
        expect=dict(format="JPEG", mode="RGB", width=1800, height=1800,
                    progressive=True),
        kural=["accept.mime"],
        neden="Progressive JPEG bazı decoder'larda baseline'dan farklı bellek "
              "profili çıkarır ve bazı eski kütüphanelerde hiç açılmaz. "
              "Kabul yolunun biçim varyantına duyarsız olduğunu doğrular.",
        kaynak="sentetik",
    ),
    "anim_6frames.gif": dict(
        cls="animation", slot="product.image", action="reject",
        expect=dict(format="GIF", n_frames=6, animated=True,
                    width=600, height=600),
        kural=["FR-012", "accept.mime", "accept.allow_animated=false"],
        neden="İKİ bağımsız sebeple reddedilmeli: (1) GIF, product.image "
              "accept.mime listesinde yok, (2) animasyonlu. Ret mesajı "
              "'format_not_supported' mı 'animated' mı diyor — kullanıcıya "
              "hangisinin söylendiği ölçülür.",
        kaynak="sentetik",
    ),
    "anim_webp.webp": dict(
        cls="animation", slot="product.image", action="reject",
        expect=dict(format="WEBP", n_frames=6, animated=True,
                    width=600, height=600),
        kural=["FR-012", "accept.allow_animated=false"],
        neden="KESKİN vaka: WebP accept.mime listesinde VAR, tek ihlal "
              "animasyon. Uzantı/MIME'a bakıp animasyon bayrağına bakmayan "
              "bir kapı bunu geçirir ve motor türev üretemez "
              "(engine.py:111 reason='animated').",
        kaynak="sentetik",
    ),
    "enc_webp_lossy.webp": dict(
        cls="photo", slot="product.image", action="process",
        expect=dict(format="WEBP", mode="RGB", width=1600, height=1600),
        kural=["quality.reencode_floor_saving_ratio"],
        neden="Zaten WebP olan bir kaynağın yeniden kodlanması. Kapı 6 "
              "(MIN_SAVING_RATIO=0.10, presets.py:25) tetiklenmeli: "
              "%10'dan az kazanç varsa orijinal korunmalı.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §1.1 — canlıda 384 WEBP dosya",
    ),
    "enc_webp_lossless.webp": dict(
        cls="transparent", slot="seller.logo", action="process",
        expect=dict(format="WEBP", mode="RGBA", width=1024, height=1024,
                    has_alpha=True),
        kural=["FR-038", "master.encoding=lossless"],
        neden="Logo merdiveni kayıpsız üretilmeli. WebP'de quality=100 "
              "HÂLÂ kayıplıdır; kip sayıyla ifade edilemez "
              "(seller-logo.json quality.metric='bit_exact'). Bu fixture "
              "kayıpsız kipin gerçekten kullanıldığını piksel-eşitliğiyle "
              "doğrulamayı mümkün kılar.",
        kaynak="sentetik",
    ),
    "edge_short32.jpg": dict(
        cls="photo", slot="product.image", action="reject",
        expect=dict(format="JPEG", mode="RGB", width=32, height=48),
        kural=["FR-015", "FR-028", "require.min_short_edge"],
        neden="Canlıdaki EN KÜÇÜK kısa kenar. Reddedilmeli; kabul edilirse "
              "sistem asla upscale yapmayacağı için (FR-028) w96 dışındaki "
              "hiçbir profil üretilemez.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §1.2 — kısa kenar min = 32",
    ),
    "edge_short4480.jpg": dict(
        cls="photo", slot="product.image", action="process",
        expect=dict(format="JPEG", mode="RGB", width=4480, height=5600,
                    megapixels=25.09),
        kural=["FR-028", "master.max_long_edge"],
        neden="Canlıdaki p99 kısa kenar. Oran 4:5 (kabul bandında) ve "
              "25,09 MP < 80 MP tavanı → KABUL. Master 2400'e inmeli; "
              "girdinin 5600 uzun kenarı çıktıda görülürse küçültme "
              "çalışmıyor demektir.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §1.2 — kısa kenar p99 = 4.480",
    ),
    "edge_72mp.jpg": dict(
        cls="photo", slot="product.image", action="process",
        expect=dict(format="JPEG", mode="RGB", width=8527, height=8527,
                    megapixels=72.71),
        kural=["FR-011", "accept.max_megapixels_hard=80"],
        neden="Canlıdaki MAKSİMUM megapiksel. Bugünkü politika tavanı 80 MP "
              "olduğu için bu dosya KABUL EDİLİR — raporun 'eşik gözden "
              "geçirilmeli' tespitinin ölçülebilir hâli. Tavan 80'den 30'a "
              "indirilirse bu fixture'ın expected_action'ı reject'e döner; "
              "yani fixture aynı zamanda politika değişikliğinin alarmıdır.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §1.2/§1.3 — MP maksimum = 72,71",
    ),
    "bound_short999.jpg": dict(
        cls="photo", slot="product.image", action="reject",
        expect=dict(format="JPEG", mode="RGB", width=999, height=999),
        kural=["FR-015", "require.min_short_edge=1000", "require.min_area"],
        neden="SINIR — alt yaka. Kısa kenar 999 < 1000 ve alan 998.001 < "
              "1.000.000. `>` yerine `>=` yazan bir uygulama bunu geçirmez "
              "ama `>=` ile `>` karışıklığı ancak eşleniğiyle "
              "(bound_short1000) birlikte yakalanır.",
        kaynak="sentetik",
    ),
    "bound_short1000.jpg": dict(
        cls="photo", slot="product.image", action="process",
        expect=dict(format="JPEG", mode="RGB", width=1000, height=1000),
        kural=["FR-015", "require.min_short_edge=1000", "require.min_area"],
        neden="SINIR — üst yaka. Kısa kenar TAM 1000, alan TAM 1.000.000. "
              "FR-015 'eşitlik geçerli' diyor; `>` kullanan bir uygulama bu "
              "dosyayı yanlışlıkla reddeder. min_short_edge ile min_area "
              "burada tam olarak buluşur (1000² = 1.000.000).",
        kaynak="sentetik",
    ),
    "ok_product_1x1_2400.jpg": dict(
        cls="photo", slot="product.image", action="process",
        expect=dict(format="JPEG", mode="RGB", width=2400, height=2400),
        kural=["master.max_long_edge=2400", "FR-035"],
        neden="POZİTİF KONTROL / altın çıktı. Tam master hedefinde "
              "(2400×2400 = 5,76 MP). Küçültme YAPILMAMALI, 7 türev "
              "profilinin (w96…w1920) hepsi üretilebilmeli. Korpusun "
              "'hiçbir uyarı çıkmamalı' referansı budur.",
        kaynak="sentetik",
    ),
    "ok_product_4x5.jpg": dict(
        cls="photo", slot="product.image", action="process",
        expect=dict(format="JPEG", mode="RGB", width=2000, height=2500),
        kural=["FR-016", "FR-037", "profiles[].fit=pad"],
        neden="4:5 kabul bandının pozitif kontrolü. w96–w768 profilleri "
              "1:1'e beyaz dolgu ile normalize edilmeli (kırpma değil); "
              "kırpan bir uygulama ürünün %20'sini keser.",
        kaynak="sentetik",
    ),
    "logo_alpha_512.png": dict(
        cls="transparent", slot="seller.logo", action="process",
        expect=dict(format="PNG", mode="RGBA", width=512, height=512,
                    has_alpha=True),
        kural=["FR-019", "FR-020", "require.recommended_edge=512"],
        neden="POZİTİF KONTROL logo: alfa var, 1:1, kısa kenar tam önerilen "
              "512. Hiçbir uyarı çıkmamalı (low_resolution_warn_below=512 "
              "sınırına TAM oturur — `<` mi `<=` mi sorusunu da test eder).",
        kaynak="sentetik",
    ),
    "logo_jpeg_noalpha.jpg": dict(
        cls="graphic", slot="seller.logo", action="process",
        expect=dict(format="JPEG", mode="RGB", width=600, height=600,
                    has_alpha=False),
        kural=["FR-019", "require.alpha_channel=optional",
               "accept.format_priority"],
        neden="ÇELİŞKİ FIXTURE'I. SRS FR-019 'logo slotlarında alfa ZORUNLU, "
              "alfası olmayan REDDEDİLİR' diyor; seller-logo.json ise "
              "alpha_channel='optional' yazıyor. Canlı ölçüm ikincisini "
              "haklı çıkardı: logoların %50'si JPEG (08 §2.1) ve K1 kararı "
              "ölçümle 'kabul + uyarı'ya döndü (08 §2.2). Beklenen: KABUL + "
              "uyarı. FR-019 metni bu ölçüme göre düzeltilmeli.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §2.1 — 18 gerçek logonun 9'u (%50) JPEG",
    ),
    "logo_wordmark_2876.png": dict(
        cls="transparent", slot="seller.logo", action="reject",
        expect=dict(format="PNG", mode="RGBA", width=1438, height=500,
                    has_alpha=True),
        kural=["FR-020", "require.aspect_band"],
        neden="Oran 2,876 — kabul bandı 1:2…2:1'in DIŞINDA. Canlıda tam bu "
              "orana sahip iki gerçek kelime markası var (egemen-plastik, "
              "timex-logo). K2 kararı bandı 1:2…2:1'de tuttu (%11 < %20 "
              "tetiği) ama bu iki dosyayı 'istisna olarak ele alınmalı' "
              "diye açık bıraktı. Fixture o açık ucun taşıyıcısıdır: "
              "istisna mekanizması yazıldığında expected_action değişir.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §2.1/§2.2 — band dışı 2 dosya, ikisi de oran 2,876",
    ),
    "logo_short200.png": dict(
        cls="transparent", slot="seller.logo", action="reject",
        expect=dict(format="PNG", mode="RGBA", width=200, height=200,
                    has_alpha=True),
        kural=["require.min_short_edge=256", "on_violation.require=reject"],
        neden="Canlıdaki EN KÜÇÜK gerçek logo kenarı (200 px). Sert ret "
              "eşiği 256 olduğu için reddedilmeli. Canlıda bu eşiğin altında "
              "1 dosya var (%5,5) — geriye dönük uygulama o tek satıcıyı "
              "etkiler; fixture geçiş penceresi kararının test tabanıdır.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §2.1 — kısa kenar aralığı 200–2.471; <256 olan 1/18",
    ),
    "ok_cover_24x5.jpg": dict(
        cls="photo", slot="company.cover_image", action="process",
        expect=dict(format="JPEG", mode="RGB", width=2400, height=500),
        kural=["FR-016", "FR-023", "require.allowed_ratios=24:5"],
        neden="SINIR + pozitif kontrol: 2400/500 = 4,80, kabul listesinin EN "
              "GENİŞ oranı (24:5) ile TAM eşit. Kısa kenar 500 ≥ 400. "
              "Güvenli alan kuralı (merkez %41,7 dikey şerit) bu geometride "
              "ölçülür.",
        kaynak="sentetik",
    ),
    "ok_banner_2x1.jpg": dict(
        cls="photo", slot="category.banner", action="process",
        expect=dict(format="JPEG", mode="RGB", width=2000, height=1000),
        kural=["FR-016", "FR-024", "master.max_long_edge=2000"],
        neden="Pozitif kontrol: oran 2:1 (öneri), kısa kenar 1000 ≥ 480, "
              "uzun kenar TAM master tavanında (2000). Küçültme "
              "yapılmamalı.",
        kaynak="sentetik",
    ),
    "ok_avatar_96.png": dict(
        cls="graphic", slot="user.avatar", action="process",
        expect=dict(format="PNG", mode="RGB", width=96, height=96),
        kural=["FR-021", "require.min_short_edge=96", "master.min_long_edge"],
        neden="SINIR: avatar kabul tabanı TAM 96 px ve master.min_long_edge "
              "de 96. Kabul edilmeli ama upscale EDİLMEMELİ (FR-028): "
              "çıktı 256 px olursa test kalır.",
        kaynak="sentetik",
    ),
    "content_blank_white.png": dict(
        cls="graphic", slot="product.image", action="process",
        expect=dict(format="PNG", mode="RGB", width=1200, height=1200),
        kural=["content_rules.entropy_bits", "FR-048", "FR-057"],
        neden="Tek renk, entropi ≈ 0. product-image.json bu kurala "
              "action='reject' yazıyor AMA content_rules.json decision_model "
              "yalnız nsfw_content ve extreme_blur'ün RED üretmesine izin "
              "veriyor ve eşik UNCALIBRATED. Bugünkü doğru davranış: KABUL + "
              "uyarı. Bu fixture kalibrasyon betiğinin (scripts/"
              "calibrate_content_rules.py) alt referans noktasıdır.",
        kaynak="sentetik",
    ),
    "content_border_40pct.png": dict(
        cls="graphic", slot="product.image", action="process",
        expect=dict(format="PNG", mode="RGB", width=1400, height=1400),
        kural=["content_rules.border_ratio", "auto_fix"],
        neden="Her kenarda %40 düz beyaz çerçeve → border_ratio > 0,25 "
              "eşiğini net aşar. Beklenen aksiyon auto_fix (sistem kırpar ve "
              "söyler). Kırpma sonrası ürünün kadrajın ≥%75'ini kaplaması "
              "ölçülür.",
        kaynak="sentetik",
    ),
    "content_border_08pct.png": dict(
        cls="graphic", slot="product.image", action="process",
        expect=dict(format="PNG", mode="RGB", width=1400, height=1400),
        kural=["content_rules.border_ratio"],
        neden="NEGATİF KONTROL: aynı üretici, %8 çerçeve → eşiğin altında. "
              "Hiçbir kırpma yapılmamalı. Yanlış-pozitif bütçesi (%5) "
              "ancak negatif kontrolle ölçülebilir.",
        kaynak="sentetik",
    ),
    "icc_srgb_embedded.jpg": dict(
        cls="photo", slot="product.image", action="process",
        expect=dict(format="JPEG", mode="RGB", width=1600, height=1600,
                    has_icc=True),
        kural=["master.strip_metadata.icc=false"],
        neden="Gömülü ICC profili. EXIF/GPS/XMP silinirken ICC "
              "SİLİNMEMELİ — engine.py:11-13 notu gereği profil bilinçli "
              "olarak çıktıya taşınıyor; silinirse renk yönetimi bozulur. "
              "Metadata temizliğinin seçici olduğunu doğrular.",
        kaynak="sentetik",
    ),
    "fmt_tiff_lzw.tif": dict(
        cls="photo", slot="product.image", action="process",
        expect=dict(format="TIFF", mode="RGB", width=1500, height=1500),
        kural=["accept.mime", "engine.SUPPORTED_FORMATS"],
        neden="TIFF, engine.SUPPORTED_FORMATS içindeki dört biçimden en az "
              "kullanılanı ve tek 'ofis/baskı' biçimi. LZW sıkıştırmalı "
              "varyantın açıldığını ve WebP'ye çevrildiğini doğrular.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §1.1 — canlıda 11 TIFF",
    ),

    # ---------------- kötücül ----------------
    "bomb_100mp.png": dict(
        cls="malicious", slot="product.image", action="reject", dizin="malicious",
        expect=dict(format="PNG", mode="L", width=10000, height=10000,
                    megapixels=100.0, bytes_max=200_000),
        kural=["FR-011", "accept.max_megapixels_hard=80"],
        neden="DECOMPRESSION BOMB. 97 KB'lık dosya 100 MP açıyor (≈100 MB "
              "ham). Karar dosya BOYUTUNDAN değil BAŞLIKTAN verilmeli. "
              "ÖLÇÜLDÜ: bugünkü engine.probe() bu dosyayı readable=True, "
              "supported=True döndürüyor ve engine.optimize() 314,8 ms'de "
              "BAŞARIYLA işliyor (ok=True) — yani koruma bugün YOK. "
              "Pillow'un kendi MAX_IMAGE_PIXELS'i (89.478.485) yalnız "
              "DecompressionBombWarning basıyor, hata fırlatmıyor.",
        kaynak="sentetik",
    ),
    "script_payload.svg": dict(
        cls="malicious", slot="seller.logo", action="reject", dizin="malicious",
        expect=dict(pil_readable=False, bytes_max=2000),
        kural=["FR-014", "FR-119", "accept.conditional_extensions"],
        neden="XSS taşıyıcısı: <script>, onload=, javascript: href, "
              "foreignObject/iframe ve dış kaynak <image> — beşi bir arada. "
              "seller-logo.json .svg'yi conditional_extensions'a koyuyor; "
              "FR-014 SVG-1…SVG-10 ön koşulları karşılanana kadar REDDET "
              "diyor. Bu dosya 'sanitizer yazıldı' iddiasının kabul testidir.",
        kaynak="sentetik",
    ),
    "polyglot_pdf_as.jpg": dict(
        cls="malicious", slot="product.image", action="reject", dizin="malicious",
        expect=dict(pil_readable=False, magic=b"%PDF"),
        kural=["FR-009", "magic_byte_matches_extension"],
        neden="Uzantı .jpg, içerik %PDF-. Kararı uzantıdan veren kapı bunu "
              "'görsel' sayar. upload_policy.py L0 bugün uyuşmazlıkta yalnız "
              "UYARI veriyor; magic-byte reddi yalnız kyb.upload_kyb_document "
              "içinde var (SRS FR-009 'KISMEN').",
        kaynak="sentetik",
    ),
    "polyglot_png_as.jpg": dict(
        cls="malicious", slot="product.image", action="reject", dizin="malicious",
        expect=dict(format="PNG", mode="RGBA", width=256, height=256),
        kural=["FR-009", "FR-008"],
        neden="ZOR vaka: içerik GEÇERLİ bir PNG ama uzantı .jpg. Zararsız "
              "görünür, bu yüzden 'nasılsa açılıyor' diye geçirilir. "
              "ÖLÇÜLDÜ: engine.optimize() bunu sorunsuz işliyor (ok=True). "
              "Sonuç dosya .jpg adıyla PNG/WebP içerik taşır → Content-Type "
              "uzantıdan türetiliyorsa tarayıcı yanlış tip görür.",
        kaynak="sentetik",
    ),
    "empty_zero_byte.jpg": dict(
        cls="malicious", slot="product.image", action="reject", dizin="malicious",
        expect=dict(pil_readable=False, bytes=0),
        kural=["FR-009", "unreadable"],
        neden="0 bayt. Canlıda bugün 0 adet (08 §1.3) ama kesilmiş yükleme / "
              "ağ hatası bunu her an üretir. Bölme, `content[:8]` dilimleme "
              "ve MIME sezgisi burada IndexError vermemeli.",
        kaynak="sentetik",
    ),
    "truncated.jpg": dict(
        cls="malicious", slot="product.image", action="reject", dizin="malicious",
        expect=dict(format="JPEG", width=1600, height=1200,
                    pil_readable=False),
        kural=["FR-009", "content_rules.unreadable"],
        neden="Geçerli JPEG BAŞLIĞI, veri %40'ta kesik. ÖLÇÜLDÜ: "
              "engine.probe() readable=True diyor (başlık sağlam), ama "
              "engine.optimize() reason='error:OSError' ile düşüyor. Yani "
              "probe TEK BAŞINA yeterli bir kabul kapısı değildir — kapı "
              "sırasını doğrulayan fixture budur.",
        kaynak="sentetik",
    ),
    "fake_docx.docx": dict(
        cls="malicious", slot="document.attachment", action="reject", dizin="malicious",
        expect=dict(pil_readable=False, magic=b"PK\x03\x04"),
        kural=["FR-010", "content_rules.magic_byte"],
        neden="ZIP magic'i (PK) doğru ama içinde [Content_Types].xml ve "
              "word/ yok. Yalnız ZIP imzasına bakan bir kontrol geçirir; "
              "kyb.py:46-53 bu yüzden ZIP içeriğini de açıyor. Referans "
              "uygulamanın kopyalandığını doğrular.",
        kaynak="sentetik",
    ),
    "executable_as.png": dict(
        cls="malicious", slot="user.avatar", action="reject", dizin="malicious",
        expect=dict(pil_readable=False, magic=b"MZ"),
        kural=["FR-009", "magic_byte_matches_extension"],
        neden="Windows PE (MZ) imzası, .png uzantısı. Avatar slotunda "
              "magic-byte kontrolü BUGÜN YOK (user-avatar.md §5.3) — "
              "identity.py:955 File'ı doğrudan açıyor. Bu dosya o boşluğun "
              "regresyon testidir.",
        kaynak="sentetik",
    ),
    "data_uri_svg.txt": dict(
        cls="malicious", slot="seller.logo", action="reject", dizin="malicious",
        expect=dict(pil_readable=False),
        kural=["FR-013", "accept.allow_data_uri=false"],
        neden="data:image/svg+xml;base64,… — medya ALANINA dosya yerine "
              "gömülü içerik yazma. Canlıda 18 logo kaydı tam olarak böyle "
              "duruyor (hepsi demo seed, gerçek satıcıda 0). Alan tipi buna "
              "izin verdiği için seller-logo.json'daki allow_data_uri=false "
              "yerinde bir önlem; bu dosya onun kabul testidir.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §2 — DB'ye gömülü 18 data: URI logosu",
    ),
    "jpeg_with_html_tail.jpg": dict(
        cls="malicious", slot="user.avatar", action="reject", dizin="malicious",
        expect=dict(format="JPEG", mode="RGB", width=320, height=320),
        kural=["FR-009", "content_rules"],
        neden="Geçerli JPEG + gövde sonunda <script>. product.image'da kısa "
              "kenar 320 < 1000 zaten reddeder; ama user.avatar tabanı 96 "
              "olduğu için ORADA geometri kapısı bunu DURDURMAZ — savunma "
              "yeniden kodlamadan gelmeli. ÖLÇÜLDÜ: engine.optimize() "
              "yeniden kodluyor ve kuyruk düşüyor (14.760 B giriş → "
              "15.561 B çıkış). Yani optimize hattından GEÇEN dosya "
              "temizleniyor, GEÇMEYEN (muaf doctype) dosya temizlenmiyor.",
        kaynak="sentetik",
    ),

    # ---------------- video ----------------
    "video_efficient_720p_750k.mp4": dict(
        cls="video", slot="product.video", action="passthrough", dizin="video",
        expect=dict(width=1280, height=720, has_audio=True,
                    needs_transcode=False),
        kural=["needs_transcode", "NEEDS_TRANSCODE_MAX_BITRATE"],
        neden="Verimli taban: 1280×720, ölçülen 797 kbps (canlı p50 746 "
              "kbps'e yakın), 16:9 tam. ÖLÇÜLDÜ: gerçek "
              "transcode.needs_transcode() False döndü → sunucu DOKUNMAZ. "
              "Şişirilmiş eşleniğiyle (aynı kaynak içerik, aynı süre) "
              "yalnız bitrate'te ayrışır.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §7 — bitrate p50 746 kbps",
    ),
    "video_bloated_720p_8m.mp4": dict(
        cls="video", slot="product.video", action="process", dizin="video",
        expect=dict(width=1280, height=720, has_audio=True,
                    needs_transcode=True, bytes_max=10_485_760),
        kural=["needs_transcode", "NEEDS_TRANSCODE_MAX_BITRATE=2500000",
               "accept.max_bytes"],
        neden="AYNI içerik, aynı süre, aynı çözünürlük — tek fark 8 Mbps. "
              "ÖLÇÜLDÜ: needs_transcode() True. Genişlik eşiği (1280) "
              "tetiklenmiyor, yalnız bitrate kolu çalışıyor: iki kolun "
              "birbirinden bağımsız olduğunu kanıtlayan tek fixture. "
              "Dosya 10 MB slot tavanının ALTINDA tutuldu ki ret bayt "
              "kuralından değil bitrate kuralından gelsin.",
        kaynak="sentetik",
    ),
    "video_silent_noaudio_720p.mp4": dict(
        cls="video", slot="product.video", action="passthrough", dizin="video",
        expect=dict(width=1280, height=720, has_audio=False,
                    needs_transcode=False),
        kural=["needs_transcode", "video.renditions"],
        neden="Ses AKIŞI HİÇ YOK (sessiz ses akışı değil). Canlıda 23 "
              "videonun 19'u böyle. libopus'a ses akışı olmadan komut "
              "kuran bir transcode zinciri burada patlar; poster üretimi "
              "(FR-042) ses akışına bakmamalı.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §7 — ses içeren 4/23",
    ),
    "video_vertical_9x16.mp4": dict(
        cls="video", slot="product.video", action="passthrough", dizin="video",
        expect=dict(width=720, height=1280, has_audio=True,
                    needs_transcode=False),
        kural=["FR-016", "require.allowed_ratios=16:9",
               "on_violation.require=warn"],
        neden="9:16 dikey — canlıda ölçülen gerçek çözünürlük (720×1280). "
              "product.video 16:9 ±%6 istiyor; oran 0,5625, sapma %68 → "
              "ihlal. AMA on_violation.require='warn' olduğu için RET DEĞİL "
              "uyarı. 08 §7'nin 'oran tek değil, tek oran dayatmak mevcut "
              "içeriği kırar' tespitinin test hâli.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §7 — çözünürlük örneği 720×1280",
    ),
    "video_long_540s_320x240.mp4": dict(
        cls="video", slot="product.video", action="passthrough", dizin="video",
        expect=dict(width=320, height=240, duration_s=540.0,
                    has_audio=False, needs_transcode=False),
        kural=["needs_transcode", "require.min_area", "SÜRE KURALI YOK"],
        neden="Canlıdaki MAKSİMUM süre (540 sn = 9 dk), doküman önerisinin "
              "(180 sn) 3 katı. Korpusu küçük tutmak için çözünürlük "
              "düşürüldü, SÜRE korundu. ÖLÇÜLDÜ: needs_transcode() False → "
              "9 dakikalık video bugün sunucuya hiç uğramadan geçiyor. "
              "AÇIK: product-video.json'da SÜRE için hiçbir kural yok; "
              "bu fixture o boşluğun taşıyıcısıdır.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §7 — süre p90 = max = 540 sn",
    ),
    "video_square_352.mp4": dict(
        cls="video", slot="product.video", action="passthrough", dizin="video",
        expect=dict(width=352, height=352, has_audio=False,
                    needs_transcode=False),
        kural=["require.min_short_edge=360", "on_violation.require=warn"],
        neden="SINIR: 352 < 360, kısa kenar tabanının 8 px altında — "
              "canlıda ölçülen gerçek en düşük çözünürlük. require ihlali "
              "'warn' olduğu için kabul edilir. Eşik 352'ye çekilirse uyarı "
              "kaybolur; bu fixture o kararın alarmıdır.",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §7 — çözünürlük örneği 352×352",
    ),
    "video_16x9_1080p.mp4": dict(
        cls="video", slot="product.video", action="process", dizin="video",
        expect=dict(width=1920, height=1080, has_audio=False,
                    needs_transcode=True),
        kural=["needs_transcode", "NEEDS_TRANSCODE_MAX_WIDTH=1280",
               "master.max_long_edge=1280"],
        neden="Genişlik kolu: 1920 > 1280 → transcode. Bitrate (1505 kbps) "
              "eşiğin ALTINDA, yani tetikleyen tek şey genişlik — şişirilmiş "
              "fixture'ın simetriği. Çıktı 1280 genişliğe inmeli "
              "(scale='min(1280,iw)':-2).",
        kaynak="canlı-veriden-türetilmiş",
        canli="08 §7 — çözünürlük örneği 1920×1080",
    ),

    # ------------- W9 (2026-08-20) — GERÇEK kaynaklar (T-006 eksik türler) ---
    # Sentetik ÜRETİLMEDİ; tamamı DEV'den bayt-birebir alındı (docker cp).
    # Köken sha256'ları alım anında konteynerde ölçüldü ve `koken` blokunda.
    "real_satici_720x720_28s.mp4": dict(
        cls="video", slot="product.video", action="passthrough", dizin="video",
        expect=dict(width=720, height=720, has_audio=True, duration_s=28.0,
                    needs_transcode=False),
        kural=["needs_transcode", "video_decision default→PASSTHROUGH"],
        neden="8. video eksiği GERÇEK kaynakla kapandı: LST-04043'ün gerçek "
              "satıcı videosu (Instagram türü, önceden sıkıştırılmış — 707 "
              "kbps video). Karar tablosu default→PASSTHROUGH (rapor 81 §2); "
              "fayda kapısı sondası bu dosyada %11,44 ölçmüştü (rapor 81 "
              "§3.3). Türkçe+emoji'li orijinal ad köken blokunda.",
        kaynak="gerçek — DEV canlı satıcı videosu",
        koken=dict(
            kaynak_dosya="sites/istoc.localhost/public/files/Evde taze "
                         "sıkılmış meyve sularının keyfini çıkarın! 🍹 "
                         "Avcılar Plastik, estetik tasarımlı limon.mp4",
            baglam="Listing LST-04043 video_url",
            sha256="eb52e15d596dadca991e39dd4968454aa02a6c4c2a827cf3360084"
                   "bab3c7c71a",
            alim="2026-08-20 W9 koşumu, docker cp (bayt-birebir)",
        ),
    ),
    "real_uretim_h264_1280.mp4": dict(
        cls="video", slot="product.video", action="passthrough", dizin="video",
        expect=dict(width=1280, height=720, has_audio=False, duration_s=540.0,
                    needs_transcode=False),
        kural=["needs_transcode", "INV-09", "idempotency"],
        neden="İLK gerçek ÜRETİM-ÇIKTISI fixture'ı: boru hattının kanonik "
              "adresli (INV-09, version_hash'li) h264 türevi — 9mb.mp4'ün "
              "REMUX (faststart) zincirinden gelen teslim dosyası, moov "
              "BAŞTA. 'Üretim çıktısı tekrar girdi olursa hat DOKUNMAMALI' "
              "vakasını taşır (needs_transcode=False ölçüldü).",
        kaynak="gerçek — boru hattı üretim çıktısı (W6-W8 koşumları)",
        koken=dict(
            kaynak_dosya="sites/istoc.localhost/public/files/media/"
                         "3pjpbple42/f8de21dd87c9c08749bb165c5000064e749e5"
                         "2f6ea2d7ce4bbe2642e1eb163c7/h264-1280.mp4",
            baglam="Media Rendition (profile=h264) — kaynak 9mb.mp4 "
                   "(LST-04419); rapor 81 §3 + rapor 90",
            sha256="64fa75a46c204baff1e022518e89539287152189b0c14f1bfe8193"
                   "72b9a0c6a1",
            alim="2026-08-20 W9 koşumu, docker cp (bayt-birebir)",
        ),
    ),
    "real_uretim_preview_480.mp4": dict(
        cls="video", slot="product.video", action="passthrough", dizin="video",
        expect=dict(width=480, height=480, has_audio=False, duration_s=6.0,
                    needs_transcode=False),
        kural=["needs_transcode", "preview ≤ 400 KB politika hedefi"],
        neden="Önizleme klibi türünün İLK gerçek örneği: W8'in ürettiği "
              "kanonik preview türevi (rapor 90 §1c — 116.775 B ≤ 400 KB "
              "politika hedefi, CRF merdiveni). Sessiz, 6 sn, poster "
              "damgasından başlar.",
        kaynak="gerçek — boru hattı üretim çıktısı (W8 koşumu)",
        koken=dict(
            kaynak_dosya="sites/istoc.localhost/public/files/media/"
                         "59jmq0pkp0/3ebd7218f85347b57ef83ae8e66d860c1da43"
                         "010f510fdd6b170db682529b12b/preview-480.mp4",
            baglam="Media Rendition (profile=preview) — kaynak LST-04043 "
                   "limon videosu; rapor 90 §1",
            sha256="7d4cf07fee7d3a8dff01b9699105ee2b9aa69237454f2755bbadb0"
                   "4c164821c8",
            alim="2026-08-20 W9 koşumu, docker cp (bayt-birebir)",
        ),
    ),
    "video_real_seller_1080p_2997fps.mp4": dict(
        cls="video", slot="product.video", action="process", dizin="video",
        expect=dict(width=1920, height=1080, has_audio=True,
                    needs_transcode=True),
        kural=["needs_transcode", "NEEDS_TRANSCODE_MAX_WIDTH=1280"],
        neden="Gerçek satıcı 1080p videosu; korpusun tek KESİRLİ fps'li "
              "(30000/1001 = NTSC 29,97) dosyası — sentetik korpusta hiç "
              "yoktu; fps'i tam sayı varsayan süre/kare hesabı burada "
              "sapar. Genişlik 1920 > 1280 → needs_transcode=True ölçüldü.",
        kaynak="gerçek — DEV canlı satıcı videosu",
        koken=dict(
            kaynak_dosya="sites/istoc.localhost/public/files/10 (1).mp4",
            baglam="tabFile gerçek video (rapor 81 §2'nin 'bağlı olmayan "
                   "5.' gerçek videosu)",
            sha256="1a61c34c1c299eb6cb2ea6b712f529ded6d028dce74ed1f9802d93"
                   "871425677a",
            alim="2026-08-20 (dosya fixture dizinine bu koşum sırasında "
                 "paralel bir elden geldi; köken sha256 ile doğrulandı, "
                 "künyesi bu koşumda ölçüldü)",
        ),
    ),
    "real_foto_canon_2240x2905.tif": dict(
        cls="photo", slot="product.image", action="reject",
        expect=dict(format="TIFF", mode="RGBA", width=2240, height=2905,
                    has_alpha=True, dpi=(200, 200)),
        kural=["FR-016", "require.allowed_ratios", "AS-27"],
        neden="AS-27 eksiği: korpusun İLK gerçek kamera fotoğrafı (Canon "
              "EOS 5D Mark IV EXIF'i dosyada; korpus bugüne dek tümüyle "
              "sentetikti). Oran 0,771 → bugünkü product.image bandı "
              "dışında; konteynerde gerçek motorla ölçüldü: evaluate → "
              "reject/ratio_not_allowed. Gerçek satıcı fotoğrafının bile "
              "bantta takılması FR-147/09-slot uyumsuzluk geriliminin "
              "fixture hâli. content_rules kalibrasyonu (AS-27) için "
              "gerçek-fotoğraf tohumu — tek dosya kalibrasyon DEĞİLDİR.",
        kaynak="gerçek — DEV canlı satıcı fotoğrafı",
        koken=dict(
            kaynak_dosya="sites/istoc.localhost/public/files/örn.tif",
            baglam="Canon EOS 5D Mark IV, 200 dpi ürün çekimi (kamera "
                   "EXIF'li 8 DEV dosyasından public olanı)",
            sha256="79ed518cd8541166a335f9d21617c291d0aeb3b1c1972840c545ee"
                   "416f35a46a",
            alim="2026-08-20 W9 koşumu, docker cp (bayt-birebir)",
        ),
    ),
    "real_adobergb_3780x2717.png": dict(
        cls="photo", slot="product.image", action="reject",
        expect=dict(format="PNG", mode="RGBA", width=3780, height=2717,
                    has_alpha=True, has_icc=True, dpi=(300, 300)),
        kural=["FR-016", "require.allowed_ratios", "master.colorspace=srgb",
               "T-061/3"],
        neden="T-061/3 eksiği: gerçek 'Adobe RGB (1998)' ICC profilli "
              "üretici görseli (profil tanımı konteynerde ImageCms ile "
              "okundu; DEV'de 11 AdobeRGB dosya bulundu). ΔE/renk dönüşümü "
              "ölçümü artık fixture'lı: ICC sRGB'ye dönüştürülmeden "
              "kırpılırsa renk kayması sessizce üretilir. Oran 1,391 → "
              "bant dışı; evaluate → reject/ratio_not_allowed (ölçüldü).",
        kaynak="gerçek — DEV canlı satıcı görseli",
        koken=dict(
            kaynak_dosya="sites/istoc.localhost/public/files/IMG_1663-"
                         "Küçük Boy Düz ve Kapaklı-3.png",
            baglam="Adobe RGB (1998) ICC'li Photoshop çıktısı ürün görseli",
            sha256="2f0433954494fefe974e0d142662576c6548af148d3107f8598e4c"
                   "42c99c1e4a",
            alim="2026-08-20 W9 koşumu, docker cp (bayt-birebir)",
        ),
    ),
}

# --------------------------------------------------------------------------
# T-006 eksik tür karnesi (W9, 2026-08-20) — rapor 94 §3'ün 5 eksiği.
# Ölçüm: DEV'de 4.213 görsel PIL/ICC/EXIF ile, 6 gerçek video (>100 KB)
# ffprobe ile tarandı (istoc-dev-backend-1). Sentetik üretim YASAKTI.
# --------------------------------------------------------------------------
EKSIK_TURLER: dict[str, str] = {
    "8_video": "TEMİN EDİLDİ: real_satici_720x720_28s.mp4 (+3 gerçek video "
               "daha; video korpusu 7 → 11)",
    "4k_60fps_uzun_video": "TEMİN EDİLEMEDİ: DEV'deki 6 gerçek videonun "
               "tamamı ≤1920×1080 ve ≤30 fps (ffprobe, 2026-08-20); 4K/60fps "
               "gerçek kaynak yok, sentetik üretim görev kuralı gereği yasak",
    "hdr_bt2020_video": "TEMİN EDİLEMEDİ: 6/6 gerçek videoda color_primaries "
               "∈ {bt709, smpte170m/bt470bg, unknown} — BT.2020/HDR kaynak "
               "DEV'de yok (ffprobe, 2026-08-20)",
    "adobergb_gorsel": "TEMİN EDİLDİ: real_adobergb_3780x2717.png (DEV "
               "taramasında 11 AdobeRGB-ICC'li gerçek dosya bulundu)",
    "gercek_fotograf": "TEMİN EDİLDİ (kısmen): real_foto_canon_2240x2905.tif "
               "(DEV'de kamera-EXIF'li 8 dosya; 1'i alındı). AS-27'nin "
               "kalibrasyon şartı için korpus hâlâ ağırlıkla sentetik — "
               "tek gerçek fotoğraf kalibrasyon değildir",
}


# --------------------------------------------------------------------------
# ölçüm
# --------------------------------------------------------------------------

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for blok in iter(lambda: f.read(1 << 20), b""):
            h.update(blok)
    return h.hexdigest()


def olc_gorsel(p: Path) -> dict:
    m: dict = {"bytes": p.stat().st_size, "sha256": sha256(p)}
    try:
        with Image.open(p) as im:
            # Başlık (open) ile piksel (load) AYRI ölçülür: bozuk dosyada
            # başlık sağlam olabilir. engine.probe()/engine.optimize()
            # ayrımının yerel karşılığı budur.
            try:
                im.load()
                m["pil_readable"] = True
            except Exception as e:
                m["pil_readable"] = False
                m["pil_load_hata"] = f"{type(e).__name__}: {e}"
            m.update(
                format=im.format,
                mode=im.mode,
                width=im.width,
                height=im.height,
                megapixels=round(im.width * im.height / 1e6, 4),
                animated=bool(getattr(im, "is_animated", False)),
                n_frames=int(getattr(im, "n_frames", 1)),
                has_alpha=(im.mode in ("RGBA", "LA", "PA")
                           or "transparency" in im.info),
                has_icc="icc_profile" in im.info,
                progressive=bool(im.info.get("progressive")
                                 or im.info.get("progression")),
            )
            dpi = im.info.get("dpi")
            if dpi:
                m["dpi"] = [round(float(dpi[0])), round(float(dpi[1]))]
            try:
                ex = im.getexif()
                if ex:
                    if 0x0112 in ex:
                        m["exif_orientation"] = int(ex[0x0112])
                    gps = ex.get_ifd(0x8825)
                    m["has_gps"] = bool(gps)
            except Exception:
                pass
    except Exception as e:
        m.update(pil_readable=False, pil_hata=f"{type(e).__name__}: {e}")
    with p.open("rb") as f:
        m["magic_hex"] = f.read(8).hex()
    return m


def karsilastir(beyan: dict, olculen: dict, dosya: str) -> list[str]:
    """`expect` beyanını ölçümle karşılaştırır. Dönen liste boşsa GEÇTİ."""
    hatalar = []
    for k, bek in beyan.items():
        if k == "bytes_max":
            if olculen["bytes"] > bek:
                hatalar.append(f"bytes {olculen['bytes']} > bytes_max {bek}")
            continue
        if k == "magic":
            if not olculen["magic_hex"].startswith(bek.hex()):
                hatalar.append(f"magic {olculen['magic_hex'][:8]} != {bek.hex()}")
            continue
        if k == "dpi":
            bek = [bek[0], bek[1]]
        if k not in olculen:
            hatalar.append(f"{k}: ÖLÇÜLEMEDİ")
            continue
        gor = olculen[k]
        if k == "megapixels":
            if abs(gor - bek) > 0.02:
                hatalar.append(f"megapixels ölçülen {gor} != beyan {bek}")
        elif gor != bek:
            hatalar.append(f"{k}: ölçülen {gor!r} != beyan {bek!r}")
    return hatalar


def main() -> int:
    canli = json.loads(CANLI.read_text()) if CANLI.exists() else {}
    eprobe = canli.get("engine_probe", {})
    eopt = canli.get("engine_optimize", {})
    vprobe = canli.get("ffprobe", {})
    vnt = canli.get("needs_transcode", {})

    kayitlar = []
    gecti = kaldi = 0

    for ad, spec in SPEC.items():
        dizin = spec.get("dizin", "images")
        kok = {"images": IMG, "video": VID, "malicious": MAL}[dizin]
        p = kok / ad
        goreli = str(p.relative_to(ROOT))

        if not p.exists():
            kayitlar.append({"file": goreli, "dogrulama": "KALDI",
                             "hata": ["dosya YOK"]})
            kaldi += 1
            continue

        if dizin == "video":
            olculen = {"bytes": p.stat().st_size, "sha256": sha256(p)}
            olculen.update(vprobe.get(ad, {}))
            if ad in vnt:
                olculen["needs_transcode"] = vnt[ad]
        else:
            olculen = olc_gorsel(p)
            if ad in eprobe:
                olculen["engine_probe"] = eprobe[ad]
            if ad in eopt:
                olculen["engine_optimize"] = eopt[ad]

        hatalar = karsilastir(spec["expect"], olculen, ad)
        if hatalar:
            kaldi += 1
        else:
            gecti += 1

        kayit = {
            "file": goreli,
            "class": spec["cls"],
            "expected_action": spec["action"],
            "expect": {k: (v.hex() if isinstance(v, bytes) else v)
                       for k, v in spec["expect"].items()},
            "neden": " ".join(spec["neden"].split()),
            "kaynak": spec["kaynak"],
            "slot": spec["slot"],
            "kural": spec["kural"],
            "olculen": olculen,
            "dogrulama": "KALDI" if hatalar else "GEÇTİ",
        }
        if "canli" in spec:
            kayit["canli_karsilik"] = spec["canli"]
        if "koken" in spec:
            kayit["koken"] = spec["koken"]
        if hatalar:
            kayit["hata"] = hatalar
        kayitlar.append(kayit)

    toplam_bayt = sum(k.get("olculen", {}).get("bytes", 0) for k in kayitlar)
    manifest = {
        "gorev": "T-006",
        "tarih": "2026-08-18",
        "guncelleme": (
            "2026-08-20 W9: rapor 94 §3'ün 5 eksik türü ölçüldü; 6 GERÇEK "
            "kaynak eklendi (köken+sha256 kayıtlı), 2 tür DEV'de temin "
            "edilemedi — bkz. eksik_turler"
        ),
        "eksik_turler": EKSIK_TURLER,
        "branch": "medya-motoru-faz0-faz2",
        "aciklama": (
            "Golden fixture korpusu. `expect` BEYAN, `olculen` ÖLÇÜM'dür; "
            "`dogrulama` ikisinin karşılaştırmasıdır. `expected_action` "
            "ilgili `slot` politikasının BUGÜNKÜ hâline göredir — politika "
            "değişirse bu alan da değişmelidir."
        ),
        "olcum_ortami": canli.get("_ortam", {}),
        "ozet": {
            "fixture_sayisi": len(kayitlar),
            "gecti": gecti,
            "kaldi": kaldi,
            "toplam_bayt": toplam_bayt,
            "toplam_mb": round(toplam_bayt / 1024 / 1024, 2),
            "sinif_dagilimi": {
                c: sum(1 for k in kayitlar if k.get("class") == c)
                for c in ("photo", "transparent", "graphic", "animation",
                          "video", "malicious")
            },
            "expected_action_dagilimi": {
                a: sum(1 for k in kayitlar if k.get("expected_action") == a)
                for a in ("process", "passthrough", "reject")
            },
        },
        "fixtures": kayitlar,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                        encoding="utf-8")

    print(f"{len(kayitlar)} fixture · GEÇTİ {gecti} · KALDI {kaldi} · "
          f"{manifest['ozet']['toplam_mb']} MB")
    for k in kayitlar:
        if k["dogrulama"] == "KALDI":
            print("  KALDI", k["file"], k.get("hata"))
    return 1 if kaldi else 0


if __name__ == "__main__":
    sys.exit(main())

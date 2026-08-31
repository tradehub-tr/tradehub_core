"""KD suite ortak fixture üreteçleri — diskten dosya okumaz, hepsini üretir.

Neden üretiyoruz: `tests/fixtures/malicious/` altındaki korpus mevcut testlerin
beklentisiyle birlikte evrildi. Bağımsız denetimin girdisi de bağımsız olmalı;
burada her bayt açıkça kurulur ve neyin neden öyle olduğu okunabilir.

`import frappe` YOKTUR — bu modül kapı/normalize gibi frappe'siz katmanlarda da
kullanılabilsin diye saf tutuldu.
"""

from __future__ import annotations

import io
import struct
import zipfile

# ── Pillow tabanlı gerçek görseller ─────────────────────────────────────


def _pil():
	from PIL import Image

	return Image


def jpeg(
	width: int = 64,
	height: int = 64,
	*,
	quality: int = 85,
	dpi: tuple[int, int] | None = None,
	orientation: int | None = None,
	renk: tuple[int, int, int] = (200, 120, 40),
	gurultu: bool = True,
) -> bytes:
	"""Gerçek bir JPEG. `gurultu=True` ile düz renk olmayan içerik üretir —
	düz renk JPEG'i sıkıştırma/SSIM ölçümlerinde dejenere davranır."""
	Image = _pil()
	im = Image.new("RGB", (width, height), renk)
	if gurultu:
		px = im.load()
		for y in range(0, height, 3):
			for x in range(0, width, 3):
				px[x, y] = ((x * 7 + y * 13) % 256, (x * 3) % 256, (y * 5) % 256)
	kw: dict = {"quality": quality}
	if dpi:
		kw["dpi"] = dpi
	if orientation is not None:
		exif = im.getexif()
		exif[0x0112] = orientation
		kw["exif"] = exif.tobytes()
	buf = io.BytesIO()
	im.save(buf, "JPEG", **kw)
	return buf.getvalue()


def jpeg_gps(width: int = 64, height: int = 64) -> bytes:
	"""GPS IFD'si DOLU bir JPEG — INV-04 (GPS her koşulda silinir) girdisi."""
	Image = _pil()
	im = Image.new("RGB", (width, height), (10, 200, 90))
	exif = im.getexif()
	gps = exif.get_ifd(0x8825)
	gps[1] = "N"
	gps[2] = (41.0, 1.0, 15.0)
	gps[3] = "E"
	gps[4] = (28.0, 58.0, 30.0)
	exif[0x010E] = "kd-test"
	buf = io.BytesIO()
	im.save(buf, "JPEG", exif=exif.tobytes())
	return buf.getvalue()


def png(width: int = 64, height: int = 64, *, alpha: bool = False, palette: bool = False) -> bytes:
	Image = _pil()
	if palette:
		im = Image.new("P", (width, height))
		im.putpalette([(i * 3) % 256 for i in range(768)])
	elif alpha:
		im = Image.new("RGBA", (width, height), (10, 20, 30, 128))
	else:
		im = Image.new("RGB", (width, height), (30, 60, 90))
	buf = io.BytesIO()
	im.save(buf, "PNG")
	return buf.getvalue()


def webp(width: int = 64, height: int = 64, *, lossless: bool = False) -> bytes:
	Image = _pil()
	im = Image.new("RGB", (width, height), (90, 30, 120))
	buf = io.BytesIO()
	im.save(buf, "WEBP", lossless=lossless, quality=80)
	return buf.getvalue()


def gif_animated(width: int = 32, height: int = 32, kare: int = 3) -> bytes:
	"""Gerçekten çok kareli GIF.

	Dikkat: boş palet + yalnız indeks farkı yeterli DEĞİL — Pillow palet
	renkleri aynı çıkınca kareleri tek kareye indiriyor (ilk kurguda ölçüldü:
	`is_animated=False`). Kareler bu yüzden hem paletli hem farklı piksel
	desenli üretiliyor.
	"""
	Image = _pil()
	palet = []
	for i in range(256):
		palet += [(i * 5) % 256, (i * 11) % 256, (i * 23) % 256]
	kareler = []
	for k in range(kare):
		im = Image.new("P", (width, height), 0)
		im.putpalette(palet)
		px = im.load()
		for yy in range(height):
			for xx in range(width):
				px[xx, yy] = (xx + yy + k * 37) % 256
		kareler.append(im)
	buf = io.BytesIO()
	kareler[0].save(buf, "GIF", save_all=True, append_images=kareler[1:], duration=80, loop=0)
	return buf.getvalue()


def tiff(width: int = 64, height: int = 64) -> bytes:
	Image = _pil()
	im = Image.new("RGB", (width, height), (5, 5, 5))
	buf = io.BytesIO()
	im.save(buf, "TIFF")
	return buf.getvalue()


# ── Ham başlık kurguları (piksel ayırmadan "büyük" dosya) ───────────────


def _png_chunk(tur: bytes, govde: bytes) -> bytes:
	import zlib

	return (
		struct.pack(">I", len(govde))
		+ tur
		+ govde
		+ struct.pack(">I", zlib.crc32(tur + govde) & 0xFFFFFFFF)
	)


def png_beyan_edilen_olcu(width: int, height: int, *, govde: int = 512, crc: bool = True) -> bytes:
	"""IHDR'da `width×height` BEYAN eden ama gövdesi sahte olan PNG.

	Bomba kapısını gerçekten 900 MP bellek ayırmadan ölçmenin tek yolu:
	beyan gerçek, gövde değil. Kapının sözleşmesi zaten "beyan üzerinden,
	decode etmeden karar" olduğu için bu meşru bir girdi.

	`crc=True` → CRC'ler doğru; Pillow başlığı AÇAR (ölçü tavanının altındaysa)
	ya da `DecompressionBombError` atar. `crc=False` → Pillow hiç tanıyamaz
	(`UnidentifiedImageError`); kapı ham başlıktan ölçü okumak zorunda kalır.
	İki yol farklı kod dallarını sınar, ikisi de gerekli.
	"""
	imza = b"\x89PNG\r\n\x1a\n"
	ihdr_govde = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
	idat_govde = b"\x00" * govde
	if crc:
		return imza + _png_chunk(b"IHDR", ihdr_govde) + _png_chunk(b"IDAT", idat_govde) + _png_chunk(b"IEND", b"")
	sifir = struct.pack(">I", 0)
	return (
		imza
		+ struct.pack(">I", len(ihdr_govde)) + b"IHDR" + ihdr_govde + sifir
		+ struct.pack(">I", len(idat_govde)) + b"IDAT" + idat_govde + sifir
		+ sifir + b"IEND" + sifir
	)


def jpeg_kesik(oran: float = 0.5) -> bytes:
	"""EOI'si olmayan JPEG — `truncated` kuralının girdisi."""
	tam = jpeg(320, 240)
	return tam[: int(len(tam) * oran)]


# ── Kötücül / polyglot kurgular ─────────────────────────────────────────

SCRIPT = b"<script>alert(1)</script>"


def jpeg_kuyrukta_script(dolgu: int = 0) -> bytes:
	"""EOI'den SONRA script taşıyan JPEG. `dolgu` kadar ara bayt konur.

	`dolgu` büyüdükçe EOI, dosyanın son 64 KB'lık tarama penceresinden çıkar.
	"""
	return jpeg(64, 64) + (b"A" * dolgu) + SCRIPT


def jpeg_script_sonra_eoi() -> bytes:
	"""Script EOI'den sonra ama dosyanın SONUNA ikinci bir EOI eklenmiş."""
	return jpeg(64, 64) + SCRIPT + b"\xff\xd9"


def png_govdesinde_script() -> bytes:
	"""IEND'den sonra script taşıyan PNG."""
	return png(48, 48) + SCRIPT


def polyglot_png_uzantisi_jpg() -> bytes:
	"""İçerik PNG, ad `.jpg` — uzantı/içerik uyuşmazlığı girdisi."""
	return png(48, 48)


def calistirilabilir() -> bytes:
	"""MZ (PE) başlıklı ikili — `detected == "executable"` girdisi."""
	return b"MZ\x90\x00" + b"\x00" * 256


def elf() -> bytes:
	return b"\x7fELF\x02\x01\x01" + b"\x00" * 256


def data_uri_metni() -> bytes:
	return b"data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4="


def svg(zararli: bool = False, *, bom: bool = False) -> bytes:
	govde = (
		b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
		+ (b'<script>alert(1)</script>' if zararli else b"<rect width='4' height='4'/>")
		+ b"</svg>"
	)
	return (b"\xef\xbb\xbf" + govde) if bom else govde


def sahte_docx() -> bytes:
	"""ZIP imzası doğru ama içi docx değil."""
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w") as zf:
		zf.writestr("merhaba.txt", "docx degil")
	return buf.getvalue()


def gercek_docx() -> bytes:
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w") as zf:
		zf.writestr("[Content_Types].xml", "<Types/>")
		zf.writestr("word/document.xml", "<document/>")
	return buf.getvalue()


def pdf_ftyp_polyglot() -> bytes:
	"""İlk 4 bayt `%PDF`, 4-8 arası `ftyp` — sniff sıralaması sınavı."""
	return b"%PDFftypisom" + b"\x00" * 64


def zip_bombasi_kucuk() -> bytes:
	"""Yüksek sıkıştırma oranlı ZIP — namelist() decompress etmemeli."""
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
		zf.writestr("buyuk.bin", b"\x00" * (8 * 1024 * 1024))
	return buf.getvalue()


# ── Video künye sözlükleri (ffprobe çıktısı taklidi) ────────────────────


def ffprobe_ciktisi(**ustune) -> dict:
	"""`probe_video_from_ffprobe` ve karar tablosu için tipik künye."""
	temel = {
		"width": 1920,
		"height": 1080,
		"duration_s": 30.0,
		"bitrate_kbps": 4000,
		"fps": "30000/1001",
		"has_audio": True,
		"audio_codec": "aac",
		"video_codec": "h264",
		"bytes": 15_000_000,
		"sha256": "0" * 64,
	}
	temel.update(ustune)
	return temel

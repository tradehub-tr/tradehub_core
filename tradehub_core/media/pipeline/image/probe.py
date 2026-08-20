"""T-060 — Başlık okuma ve kabul kapısı: **piksel açmadan** karar.

Neden ayrı bir modül
--------------------
`tradehub_core/media/pipeline/core/probe.py` zaten tam bir künye çıkarıyor, ama `_image_details()`
içinde `im.load()` çağırıyor — yani **tüm pikselleri açıyor**. Bu, karar için
gereken bilgiyi verir ama bomba dosyasında (fixture `bomb_100mp.png`, 100 MP)
tam da kaçınmak istediğimiz şeyi yapar: reddedeceğimiz dosyanın belleğini
ayırır. Kabul kapısı, açmadan karar vermek zorundadır.

Bu modül `core.probe`'un yerine geçmez; **kapı** rolünü üstlenir:

    core.probe.probe_bytes()   tam künye — PolicyEngine girdisi, pikselleri açar
    image.probe.probe_header() başlık künyesi — kabul kapısı, pikselleri AÇMAZ

Güvenlik sezgileri TEKRAR YAZILMADI: `sniff`, tehlikeli işaretçi ve eklenmiş yük
tespitleri `core.probe`'tan çağrılır (o da `tradehub_core/media/upload_policy.py`
tablolarının aynası). Bu modülün eklediği üç şey:

1. **Piksel tavanı başlıktan** — `max_megapixels` aşılırsa hiçbir piksel açılmaz.
2. **Kesiklik (truncation) başlıktan/kuyruktan** — JPEG'in EOI'si, PNG'nin IEND'i,
   GIF'in trailer'ı dosyanın sonunda var mı. `core.probe` bunu `im.load()` ile
   ölçüyor; burada aynı soru **decode etmeden** cevaplanıyor.
   ÖLÇÜLDÜ: `tradehub_core/tests/fixtures/malicious/truncated.jpg` başlığı geçerli
   (1600×1200 okunuyor) ama EOI yok.
3. **Yol (path) girdisi** — 30 MB'lık bir dosyayı karar vermek için belleğe
   almak gerekmez: başlık + son 64 KB okunur.

ÖLÇÜM (yerel, Pillow 11.3.0, 34 görsel fixture, 5 tekrar ortalaması):
`Image.open` ile başlık okuma en yavaş dosyada (20,98 MB TIFF) 0,20 ms.
Yol girdisiyle uçtan uca `probe_header` bütçesi `tests/test_image_probe.py`
içinde 30 MB'lık üretilmiş dosyada ölçülür; hedef <50 ms.

`import frappe` YOKTUR.
"""

from __future__ import annotations

import io
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from tradehub_core.media.pipeline.contracts.errors import (
	SEBEP_ANIMATED_NOT_ALLOWED,
	SEBEP_DANGEROUS_CONTENT,
	SEBEP_DECODE_FAILED,
	SEBEP_EMPTY,
	SEBEP_EXT_CONTENT_MISMATCH,
	SEBEP_MEGAPIXEL_BOMB,
	SEBEP_TOO_LARGE,
	SEBEP_UNSUPPORTED_FORMAT,
)
from tradehub_core.media.pipeline.core import probe as core_probe

#: `core.probe` ile aynı kaynağı kullanan tür sezgisi — burada TEKRARLANMAZ.
sniff = core_probe.sniff

#: Kesiklik/ek-yük kontrolü için okunacak kuyruk. 64 KB, JPEG'in en uzun
#: EOI-öncesi segmentinden (64 KB APPn sınırı) büyük ya da eşit seçildi.
TAIL_BYTES: int = 64 * 1024

#: Yol girdisinde başlık için okunacak ön parça. TIFF IFD'si dosyanın sonunda
#: olabildiği için Pillow'a dosyanın kendisi verilir; bu tampon yalnız magic
#: ve tehlikeli işaretçi taraması içindir (`is_dangerous` ilk 512 bayta bakar).
HEAD_BYTES: int = 64 * 1024

#: `getexif()` çağrısı PİKSEL AÇAN biçimler — T-017'de ÖLÇÜLDÜ.
#: Pillow 12.2.0'da `PngImagePlugin.getexif()` ilk satırında `self.load()`
#: çağırıyor (`PngImagePlugin.py:1096`). Yani bu modülün "pikselleri AÇMAZ"
#: sözü PNG'de tutmuyordu: `bomb_100mp.png` kapıda tam olarak decode ediliyor,
#: 100 MP bellek ayrılıyordu. Ölçüm (aynı Pillow, 64×64 örnek, `Image.load`
#: sayacı): JPEG 0 · **PNG 2** · WEBP 0 · TIFF 0 · GIF 0 · BMP 0.
#: PNG'de EXIF kaybı pratikte bedelsiz: PNG'nin oryantasyon konvansiyonu yok,
#: `eXIf` chunk'ı nadir ve boru hattının EXIF rotasyonu kamera JPEG'i içindir.
EXIF_DECODES_PIXELS: frozenset[str] = frozenset({"PNG"})

#: Biçimden bağımsız emniyet: bu ölçünün üstünde EXIF hiç okunmaz. Yukarıdaki
#: liste Pillow sürümüne bağlı; sürüm değişip başka bir biçim de `load()`
#: çağırmaya başlarsa bomba yine açılmasın.
EXIF_MAX_MEGAPIXELS: float = 80.0

#: Bu motorun **okuyabildiği** biçimler. `engine.SUPPORTED_FORMATS` (JPEG/PNG/
#: WEBP/TIFF) motorun YAZABİLDİKLERİ; kapı daha geniştir çünkü GIF/BMP/AVIF
#: okunup başka biçime çevrilebilir. Kapıdan geçen her dosyanın master'ı
#: `normalize.py` tarafından üretilir.
READABLE_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "WEBP", "TIFF", "GIF", "BMP", "AVIF"})

#: Ek ret kodları — `contracts/errors.py` listesinde karşılığı olmayan iki durum.
SEBEP_TRUNCATED: str = "truncated"
SEBEP_APPENDED_PAYLOAD: str = "appended_payload"
SEBEP_UNREADABLE_HEADER: str = SEBEP_DECODE_FAILED


@dataclass(frozen=True)
class GuardConfig:
	"""Kapı eşikleri.

	Varsayılanlar `tradehub_core/media/pipeline/policy/slots/product-image.json` `accept`
	bloğundan alındı: `max_megapixels_hard = 80`, `max_bytes = 26214400`,
	`allow_animated = false`. Slot politikası varsa `from_accept()` ile
	kurulur; sabitler burada YALNIZ varsayılan olarak durur.
	"""

	max_megapixels: float = 80.0
	max_bytes: int = 25 * 1024 * 1024
	allow_animated: bool = False
	allowed_formats: frozenset[str] = READABLE_FORMATS
	#: Uzantı ile içerik uyuşmazlığında reddet. `False` yapılırsa yalnız
	#: uyarı üretilir — `upload_policy.check()`'in bugünkü davranışı
	#: (zararsız uyuşmazlık sahada var, bkz. upload_policy.py modül başlığı).
	reject_extension_mismatch: bool = True
	#: Kesik dosyayı reddet. Pillow `LOAD_TRUNCATED_IMAGES` ile kesik dosyayı
	#: sessizce tamamlayabiliyor; kapı bunu bilerek yapmaz.
	reject_truncated: bool = True

	@classmethod
	def from_accept(cls, accept: dict, **kwargs) -> GuardConfig:
		"""Slot politikasının `accept` bloğundan kapı kurar."""
		return cls(
			max_megapixels=float(accept.get("max_megapixels_hard") or cls.max_megapixels),
			max_bytes=int(accept.get("max_bytes") or cls.max_bytes),
			allow_animated=bool(accept.get("allow_animated", False)),
			**kwargs,
		)


DEFAULT_GUARD: GuardConfig = GuardConfig()


@dataclass(frozen=True)
class Rejection:
	"""Tek bir kapı reddi — kod + insan okunur gerekçe + ölçülen/beklenen."""

	code: str
	message: str
	observed: object = None
	expected: object = None

	def to_dict(self) -> dict:
		return {
			"code": self.code,
			"message": self.message,
			"observed": self.observed,
			"expected": self.expected,
		}


@dataclass(frozen=True)
class HeaderProbe:
	"""Başlıktan okunan künye. **Hiçbir alanı piksel decode'u gerektirmez.**

	`None` "ölçülmedi" demektir (`core.probe.MediaProbe` ile aynı sözleşme):
	`truncated=None` "bu biçimde kuyruk sınırı ucuzca bilinemez" anlamına
	gelir, "kesik değil" anlamına GELMEZ.
	"""

	filename: str = ""
	extension: str = ""
	byte_size: int = 0
	detected: str = ""
	fmt: str = ""
	width: int = 0
	height: int = 0
	mode: str = ""
	animated: bool = False
	frame_count: int = 1
	has_alpha: bool = False
	has_icc: bool = False
	dpi: tuple[float, float] | None = None
	exif_orientation: int = 1
	progressive: bool = False
	readable: bool = False
	truncated: bool | None = None
	leading_marker: bool = False
	appended_payload: bool = False
	extension_matches_content: bool | None = None
	rejections: tuple[Rejection, ...] = ()
	warnings: tuple[str, ...] = ()
	source_kind: str = "bytes"  # "bytes" | "path"
	extra: dict = field(default_factory=dict)

	# — türetilmiş ölçüler —

	@property
	def ok(self) -> bool:
		"""Kapıdan geçti mi."""
		return not self.rejections

	@property
	def megapixels(self) -> float:
		return (self.width * self.height) / 1_000_000.0

	@property
	def short_edge(self) -> int:
		return min(self.width, self.height) if self.width and self.height else 0

	@property
	def long_edge(self) -> int:
		return max(self.width, self.height) if self.width and self.height else 0

	@property
	def display_size(self) -> tuple[int, int]:
		"""EXIF rotasyonu UYGULANMIŞ ölçü — `core.probe.MediaProbe` ile aynı kural."""
		if self.exif_orientation in (5, 6, 7, 8):
			return (self.height, self.width)
		return (self.width, self.height)

	@property
	def aspect(self) -> float:
		w, h = self.display_size
		return (w / h) if h else 0.0

	@property
	def codes(self) -> tuple[str, ...]:
		return tuple(r.code for r in self.rejections)

	def to_dict(self) -> dict:
		return {
			"filename": self.filename,
			"extension": self.extension,
			"byte_size": self.byte_size,
			"detected": self.detected,
			"fmt": self.fmt,
			"width": self.width,
			"height": self.height,
			"megapixels": round(self.megapixels, 4),
			"mode": self.mode,
			"animated": self.animated,
			"frame_count": self.frame_count,
			"has_alpha": self.has_alpha,
			"has_icc": self.has_icc,
			"dpi": list(self.dpi) if self.dpi else None,
			"exif_orientation": self.exif_orientation,
			"progressive": self.progressive,
			"readable": self.readable,
			"truncated": self.truncated,
			"leading_marker": self.leading_marker,
			"appended_payload": self.appended_payload,
			"extension_matches_content": self.extension_matches_content,
			"ok": self.ok,
			"rejections": [r.to_dict() for r in self.rejections],
			"warnings": list(self.warnings),
			"source_kind": self.source_kind,
		}


# ── Kaynak okuma ────────────────────────────────────────────────────────
#
# Kapının iki girdi biçimi var ve ikisi FARKLI maliyet taşır:
#   bytes → içerik zaten bellekte; kuyruk taraması dilimleme.
#   path  → dosya açılır, YALNIZ baş ve kuyruk okunur; 30 MB belleğe alınmaz.


def _read_edges(path: Path) -> tuple[bytes, bytes, int]:
	"""Dosyanın başını ve kuyruğunu oku — ortasına dokunma."""
	size = path.stat().st_size
	with path.open("rb") as fh:
		head = fh.read(min(HEAD_BYTES, size))
		if size > TAIL_BYTES:
			fh.seek(-TAIL_BYTES, os.SEEK_END)
			tail = fh.read(TAIL_BYTES)
		else:
			tail = head if size <= HEAD_BYTES else b""
			if not tail:
				fh.seek(0)
				tail = fh.read(size)
	return head, tail, size


# ── Kesiklik ────────────────────────────────────────────────────────────


def tail_is_complete(tail: bytes, detected: str) -> bool | None:
	"""Dosyanın kuyruğunda biçimin bitiş işareti var mı — decode YOK.

	`None` "bu biçimde ucuzca ölçülemez" demektir; kapı o durumda kesiklik
	kuralını DEĞERLENDİRMEZ (sessizce "tamam" saymaz, kuralı atlar).

	Sınırlar biçim tanımlarından:
	  JPEG  EOI = FF D9            (ITU-T T.81 B.1.1.3)
	  PNG   son chunk = IEND + CRC (RFC 2083 §3.4)
	  GIF   trailer = 0x3B         (GIF89a §23)
	  WEBP  RIFF gövde uzunluğu dosya boyutuyla tutarlı olmalı — bu kontrol
	        baş tarafta yapılır, burada değil; `None` döner.
	"""
	if not tail:
		return None
	if detected == "jpeg":
		return tail.rfind(b"\xff\xd9") >= 0
	if detected == "png":
		return tail.rfind(b"IEND") >= 0
	if detected == "gif":
		return tail.rstrip(b"\x00").endswith(b"\x3b")
	return None


def _riff_length_ok(head: bytes, size: int) -> bool | None:
	"""WEBP/RIFF: başlıktaki gövde uzunluğu dosya boyutuyla tutarlı mı."""
	if len(head) < 12 or not head.startswith(b"RIFF"):
		return None
	beyan = int.from_bytes(head[4:8], "little")
	# RIFF uzunluğu ilk 8 baytı saymaz.
	return (beyan + 8) <= size


# ── Beyan edilen ölçü — Pillow'SUZ ──────────────────────────────────────
#
# Rapor 75 bulgu 4 (W4 panel E2E, ÖLÇÜLDÜ): Pillow, kendi `MAX_IMAGE_PIXELS`
# tavanının 2 katının (≈179 MP) üstünde boyut BEYAN eden başlığı hiç açmıyor
# (`DecompressionBombError`), ölçü 0 okunuyor ve 80 MP tavanı hiç
# değerlendirilmiyordu — 30000×30000'lik PNG kapıdan 200 ile geçti. En agresif
# bomba, denetimden "hata yüzünden" muaftı. Bu yüzden beyan edilen ölçü,
# Pillow'a hiç sorulmadan ilk baytlardan da okunabilmelidir.

#: `declared_dimensions`'ın ham baytlardan ölçebildiği biçimler. Bu kümedeki
#: bir biçimin ölçüsü OKUNAMIYORSA dosya bozuktur — kapı fail-closed reddeder.
DIMENSIONS_PARSEABLE: frozenset[str] = frozenset({"png", "jpeg", "gif", "webp", "bmp"})

#: JPEG SOFn işaretçileri — kare ölçüsünü taşıyan segmentler (ITU-T T.81 B.2.2).
#: C4 (DHT), C8 (JPG) ve CC (DAC) SOF DEĞİLDİR, bilinçli olarak dışarıda.
_JPEG_SOF_MARKERS: frozenset[int] = frozenset(
	{0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


def _jpeg_dimensions(head: bytes) -> tuple[int, int] | None:
	"""JPEG segmentlerini SOFn'a kadar yürü — decode YOK (ITU-T T.81 B).

	SOFn her zaman SOS'tan (FFDA) önce gelir; SOS'a ya da tampon sonuna
	SOF görmeden ulaşılırsa ölçü OKUNAMAMIŞTIR (`None`).
	"""
	i, n = 2, len(head)
	while i + 4 <= n:
		if head[i] != 0xFF:
			return None
		marker = head[i + 1]
		if marker == 0xFF:  # doldurma baytı (padding)
			i += 1
			continue
		if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # bağımsız işaretçiler
			i += 2
			continue
		if marker in (0xD9, 0xDA):  # EOI / SOS — SOF artık gelmez
			return None
		seg_len = int.from_bytes(head[i + 2 : i + 4], "big")
		if seg_len < 2:
			return None
		if marker in _JPEG_SOF_MARKERS:
			if i + 9 > n:
				return None
			h = int.from_bytes(head[i + 5 : i + 7], "big")
			w = int.from_bytes(head[i + 7 : i + 9], "big")
			return (w, h)
		i += 2 + seg_len
	return None


def _webp_dimensions(head: bytes) -> tuple[int, int] | None:
	"""WebP kanvas ölçüsü — RIFF içindeki VP8/VP8L/VP8X başlığından."""
	if len(head) < 30 or not head.startswith(b"RIFF") or head[8:12] != b"WEBP":
		return None
	dortlu = head[12:16]
	if dortlu == b"VP8 ":  # lossy: 3B kare etiketi + 9D 01 2A + 2×14 bit ölçü
		if head[23:26] != b"\x9d\x01\x2a":
			return None
		w = int.from_bytes(head[26:28], "little") & 0x3FFF
		h = int.from_bytes(head[28:30], "little") & 0x3FFF
		return (w, h)
	if dortlu == b"VP8L":  # lossless: imza 0x2F + 2×14 bit (ölçü-1)
		if head[20] != 0x2F:
			return None
		bits = int.from_bytes(head[21:25], "little")
		return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
	if dortlu == b"VP8X":  # extended: 4B bayrak + 2×24 bit (kanvas-1)
		w = int.from_bytes(head[24:27], "little") + 1
		h = int.from_bytes(head[27:30], "little") + 1
		return (w, h)
	return None


def declared_dimensions(head: bytes, detected: str) -> tuple[int, int] | None:
	"""Başlığın BEYAN ettiği piksel ölçüsü — Pillow'a hiç sorulmadan.

	`None` = bu biçimde okunamadı / başlık bozuk. Dönen değer bir beyan,
	doğrulanmış içerik değildir: bomba kararı için tam da beyan gerekir
	(gövde zaten decode edilmeyecek). 0/negatif değerler OLDUĞU GİBİ döner;
	fail-closed ret kararı çağırana aittir.
	"""
	if detected == "png":
		# imza(8) + uzunluk(4) + "IHDR"(4) + genişlik(4 BE) + yükseklik(4 BE)
		if len(head) >= 24 and head[12:16] == b"IHDR":
			return (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"))
		return None
	if detected == "jpeg":
		return _jpeg_dimensions(head)
	if detected == "gif":
		# "GIF87a/89a"(6) + mantıksal ekran genişlik/yükseklik (2×LE uint16)
		if len(head) >= 10:
			return (int.from_bytes(head[6:8], "little"), int.from_bytes(head[8:10], "little"))
		return None
	if detected == "webp":
		return _webp_dimensions(head)
	if detected == "bmp":
		if len(head) < 22:
			return None
		hdr = int.from_bytes(head[14:18], "little")
		if hdr == 12:  # BITMAPCOREHEADER: 2×LE uint16
			return (int.from_bytes(head[18:20], "little"), int.from_bytes(head[20:22], "little"))
		if hdr >= 40 and len(head) >= 26:  # BITMAPINFOHEADER+: 2×LE int32
			w = int.from_bytes(head[18:22], "little", signed=True)
			h = int.from_bytes(head[22:26], "little", signed=True)
			return (w, abs(h))  # negatif yükseklik = top-down BMP, meşru
		return None
	return None


# ── Başlık açma ─────────────────────────────────────────────────────────


def _open_header(src) -> dict:
	"""Pillow ile YALNIZ başlığı oku. `im.load()` ÇAĞRILMAZ.

	`Image.open` tembeldir: başlığı ayrıştırır, piksel verisine dokunmaz.
	Bu fonksiyonun tek işi o tembelliği bozmadan alanları toplamaktır —
	`im.getexif()` de EXIF bloğunu okur, pikselleri değil.
	"""
	out: dict = {"readable": False}
	try:
		from PIL import Image
	except Exception:
		out["pillow_missing"] = True
		return out

	try:
		with warnings.catch_warnings():
			# DecompressionBombWarning burada BASTIRILIR ama karar
			# bastırılmaz: piksel tavanını bizim `GuardConfig` uygular ve
			# reddi kendi kodumuzla döneriz. Pillow'un uyarısı test
			# çıktısını kirletmenin ötesinde bir bilgi taşımıyor.
			warnings.simplefilter("ignore")
			with Image.open(src) as im:
				out["readable"] = True
				out["fmt"] = (im.format or "").upper()
				out["width"] = int(im.width)
				out["height"] = int(im.height)
				out["mode"] = im.mode
				out["animated"] = bool(getattr(im, "is_animated", False))
				out["frame_count"] = int(getattr(im, "n_frames", 1) or 1)
				out["has_icc"] = bool(im.info.get("icc_profile"))
				out["progressive"] = bool(im.info.get("progressive") or im.info.get("progression"))
				out["has_alpha"] = bool(
					im.mode in ("RGBA", "LA", "PA")
					or (im.mode == "P" and "transparency" in im.info)
				)
				dpi = im.info.get("dpi")
				if dpi:
					try:
						out["dpi"] = (float(dpi[0]), float(dpi[1]))
					except Exception:
						pass
				# EXIF okuması bazı biçimlerde pikselleri AÇIYOR (bkz.
				# `EXIF_DECODES_PIXELS`). Kapının tek işi açmadan karar
				# vermek olduğu için burada okumak yerine ATLANIYOR ve
				# atlandığı künyeye yazılıyor — "ölçülmedi", "1" değil.
				megapiksel = (out["width"] * out["height"]) / 1_000_000.0
				if out["fmt"] in EXIF_DECODES_PIXELS or megapiksel > EXIF_MAX_MEGAPIXELS:
					out["exif_skipped"] = True
				else:
					try:
						exif = im.getexif()
						deger = exif.get(0x0112) if exif else None
						if deger:
							out["exif_orientation"] = int(deger)
					except Exception:
						pass
	except Image.DecompressionBombError as exc:
		# Pillow, beyan edilen ölçü kendi tavanının (MAX_IMAGE_PIXELS×2)
		# üstündeyse başlığı HİÇ açmaz. Bu bir "okunamadı" değil, "bomba
		# beyanı" sinyalidir — kapı bunu görmezse en agresif bomba denetimden
		# kaçar (rapor 75 bulgu 4). Ayrı işaretlenir ki `_guard` fail-closed
		# reddedebilsin.
		out["decompression_bomb"] = True
		out["error"] = f"{type(exc).__name__}: {exc}"
	except Exception as exc:  # noqa: BLE001 — kapı hiçbir girdide patlamamalı
		out["error"] = f"{type(exc).__name__}: {exc}"
	return out


# ── Kapı ────────────────────────────────────────────────────────────────


def probe_header(
	src: bytes | bytearray | str | Path,
	*,
	filename: str = "",
	config: GuardConfig = DEFAULT_GUARD,
) -> HeaderProbe:
	"""Başlık künyesi + kapı kararı. **Piksel açılmaz, istisna atılmaz.**

	`src` bayt dizisi ya da dosya yolu olabilir. Yol verildiğinde dosyanın
	tamamı belleğe ALINMAZ: başlık Pillow tarafından, güvenlik taraması ilk
	64 KB + son 64 KB üzerinden yapılır.

	Ret üretmez, ret LİSTESİ döner (`probe.rejections`). İstisna isteyen
	çağıran `assert_accepted()` kullanır.
	"""
	yol: Path | None = None
	if isinstance(src, (bytes, bytearray)):
		content = bytes(src)
		head = content[:HEAD_BYTES]
		tail = content[-TAIL_BYTES:] if len(content) > TAIL_BYTES else content
		size = len(content)
		kaynak = "bytes"
		acilacak: object = io.BytesIO(content)
		ad = filename
	else:
		yol = Path(src)
		if not yol.exists():
			return HeaderProbe(
				filename=filename or str(src),
				rejections=(Rejection(SEBEP_EMPTY, "Dosya bulunamadı.", observed=str(src)),),
				source_kind="path",
			)
		head, tail, size = _read_edges(yol)
		kaynak = "path"
		acilacak = str(yol)
		ad = filename or yol.name

	uzanti = os.path.splitext(ad)[1].lower() if ad else ""
	detected = sniff(head)

	# Boş dosya: hiçbir ölçüm anlamlı değil, tek retle çık.
	if size == 0:
		return HeaderProbe(
			filename=ad,
			extension=uzanti,
			byte_size=0,
			source_kind=kaynak,
			rejections=(Rejection(SEBEP_EMPTY, "Dosya içeriği boş.", observed=0),),
		)

	# Güvenlik sezgileri — `core.probe` ile AYNI uygulama, tekrar yazılmadı.
	leading = core_probe._has_leading_marker(head)
	appended = core_probe._has_appended_payload(tail, detected)
	eslesme = core_probe._extension_matches(uzanti, detected)

	baslik = _open_header(acilacak)
	fmt = baslik.get("fmt", "")

	# Pillow başlığı açamadıysa (ör. kendi ~179 MP tavanı) BEYAN edilen ölçü
	# ham baytlardan okunur — piksel tavanı ölçüsüz kalıp atlanmasın
	# (rapor 75 bulgu 4: 30000×30000 PNG "boyut 0" diye kuraldan kaçıyordu).
	if not (baslik.get("width") and baslik.get("height")):
		beyan = declared_dimensions(head, detected)
		if beyan is not None:
			baslik["width"], baslik["height"] = beyan
			baslik["size_from_raw_header"] = True

	kesik = tail_is_complete(tail, detected)
	if kesik is None and detected == "webp":
		riff = _riff_length_ok(head, size)
		kesik = riff
	truncated = (not kesik) if kesik is not None else None

	p = HeaderProbe(
		filename=ad,
		extension=uzanti,
		byte_size=size,
		detected=detected,
		fmt=fmt,
		width=int(baslik.get("width", 0)),
		height=int(baslik.get("height", 0)),
		mode=baslik.get("mode", ""),
		animated=bool(baslik.get("animated", False)),
		frame_count=int(baslik.get("frame_count", 1)),
		has_alpha=bool(baslik.get("has_alpha", False)),
		has_icc=bool(baslik.get("has_icc", False)),
		dpi=baslik.get("dpi"),
		exif_orientation=int(baslik.get("exif_orientation", 1)),
		progressive=bool(baslik.get("progressive", False)),
		readable=bool(baslik.get("readable", False)),
		truncated=truncated,
		leading_marker=leading,
		appended_payload=appended,
		extension_matches_content=eslesme,
		source_kind=kaynak,
		extra={
			k: v
			for k, v in baslik.items()
			if k in ("error", "pillow_missing", "exif_skipped", "decompression_bomb", "size_from_raw_header")
		},
	)
	return _guard(p, config)


def _guard(p: HeaderProbe, config: GuardConfig) -> HeaderProbe:
	"""Künyeye kapı kurallarını uygula — sıralama ANLAMLIDIR.

	Önce **hiç açmadan** verilebilecek retler (tehlikeli içerik, boyut, tür
	uyuşmazlığı), sonra başlıktan okunanlar (piksel tavanı, animasyon).
	Sıralamanın gerekçesi: kullanıcıya gösterilecek TEK gerekçe en erken ve
	en anlaşılır olanı olmalı (FR-062).
	"""
	retler: list[Rejection] = []
	uyarilar: list[str] = []

	if p.leading_marker:
		retler.append(
			Rejection(
				SEBEP_DANGEROUS_CONTENT,
				"Dosyanın içeriği tarayıcıda çalıştırılabilir (HTML/SVG/script).",
				observed=p.detected or "markup",
			)
		)

	if p.detected in ("executable", "data_uri"):
		retler.append(
			Rejection(
				SEBEP_DANGEROUS_CONTENT,
				"Dosya bir görsel değil; çalıştırılabilir içerik ya da gömülü URI.",
				observed=p.detected,
			)
		)

	if p.byte_size > config.max_bytes:
		retler.append(
			Rejection(
				SEBEP_TOO_LARGE,
				"Dosya boyutu sınırı aşıyor.",
				observed=p.byte_size,
				expected=config.max_bytes,
			)
		)

	if config.reject_extension_mismatch and p.extension_matches_content is False:
		retler.append(
			Rejection(
				SEBEP_EXT_CONTENT_MISMATCH,
				"Dosya uzantısı içerikle uyuşmuyor.",
				observed=p.detected or "?",
				expected=p.extension or "?",
			)
		)
	elif p.extension_matches_content is False:
		uyarilar.append(f"uzanti={p.extension} icerik={p.detected}")

	if p.appended_payload:
		retler.append(
			Rejection(
				SEBEP_APPENDED_PAYLOAD,
				"Görselin sonuna çalıştırılabilir içerik eklenmiş.",
				observed="tail_markup",
			)
		)

	# PİKSEL TAVANI — bomba koruması. Başlıktaki (gerekirse ham baytlardan
	# okunan) BEYAN ölçüsünden hesaplanır; `im.load()` bu noktaya kadar HİÇ
	# çağrılmadı. Kural `readable`'dan BAĞIMSIZ ve FAIL-CLOSED: Pillow'un
	# kendi tavanının üstünde boyut beyan eden dosyayı Pillow hiç açmaz;
	# ölçü ham baytlardan da okunamadıysa `decompression_bomb` işareti tek
	# başına RET'tir. Aksi hâlde en agresif bomba, "başlık açılamadı"nın
	# gölgesinde piksel tavanından muaf kalırdı (rapor 75 bulgu 4, ÖLÇÜLDÜ:
	# 30000×30000 PNG kapıdan 200 ile geçti).
	if config.max_megapixels:
		if p.megapixels > config.max_megapixels:
			retler.append(
				Rejection(
					SEBEP_MEGAPIXEL_BOMB,
					"Görsel çözünürlüğü sınırı aşıyor; açılmadan reddedildi.",
					observed=round(p.megapixels, 3),
					expected=config.max_megapixels,
				)
			)
		elif p.extra.get("decompression_bomb") and (p.width <= 0 or p.height <= 0):
			retler.append(
				Rejection(
					SEBEP_MEGAPIXEL_BOMB,
					"Görsel çözünürlüğü sınırı aşıyor; açılmadan reddedildi.",
					observed="declared_over_decoder_limit",
					expected=config.max_megapixels,
				)
			)

	if not p.readable:
		retler.append(
			Rejection(
				SEBEP_UNREADABLE_HEADER,
				"Dosyanın başlığı okunamadı; geçerli bir görsel değil.",
				observed=p.extra.get("error", ""),
			)
		)
	else:
		if config.allowed_formats and p.fmt not in config.allowed_formats:
			retler.append(
				Rejection(
					SEBEP_UNSUPPORTED_FORMAT,
					"Bu görsel biçimi işlenemiyor.",
					observed=p.fmt,
					expected=sorted(config.allowed_formats),
				)
			)

		if p.animated and not config.allow_animated:
			retler.append(
				Rejection(
					SEBEP_ANIMATED_NOT_ALLOWED,
					"Hareketli görsel kabul edilmiyor.",
					observed=p.frame_count,
				)
			)

		if config.reject_truncated and p.truncated is True:
			retler.append(
				Rejection(
					SEBEP_TRUNCATED,
					"Dosya eksik; veri akışı yarıda kesilmiş.",
					observed=p.detected,
				)
			)
		elif p.truncated is None:
			uyarilar.append(f"kesiklik_olculmedi:{p.detected or 'bilinmiyor'}")

	return replace_probe(p, rejections=tuple(retler), warnings=tuple(uyarilar))


def replace_probe(p: HeaderProbe, **degisiklikler) -> HeaderProbe:
	"""`dataclasses.replace` sarmalayıcısı — `extra` sözlüğü kopyalanır."""
	from dataclasses import replace

	return replace(p, **degisiklikler)


class ImageRejected(Exception):
	"""Kapı reddi — `assert_accepted()` bunu atar.

	`media_engine.contracts.errors.MediaEngineError` yerine düz `Exception`
	seçilmedi: bu sınıf `ImageError` altında durur ki çağıran tek `except`
	ile tüm görsel hatalarını yakalayabilsin.
	"""

	def __init__(self, probe: HeaderProbe):
		self.probe = probe
		self.rejections = probe.rejections
		kodlar = ", ".join(r.code for r in probe.rejections) or "unknown"
		mesaj = probe.rejections[0].message if probe.rejections else "Reddedildi."
		super().__init__(f"{mesaj} [{kodlar}]")


def assert_accepted(
	src: bytes | bytearray | str | Path,
	*,
	filename: str = "",
	config: GuardConfig = DEFAULT_GUARD,
) -> HeaderProbe:
	"""`probe_header` + ret varsa `ImageRejected`. Kabul edilirse künyeyi döner."""
	p = probe_header(src, filename=filename, config=config)
	if not p.ok:
		raise ImageRejected(p)
	return p


def guard_only(p: HeaderProbe, config: GuardConfig) -> HeaderProbe:
	"""Var olan bir künyeyi FARKLI bir kapı ayarıyla yeniden değerlendir.

	Aynı dosya iki slota (ör. `product.image` ve `document.attachment`) aday
	olabiliyor ve slotların `accept` blokları farklı. Dosyayı ikinci kez
	okumak gereksiz: künye zaten elde.
	"""
	return _guard(replace_probe(p, rejections=(), warnings=()), config)


__all__ = [
	"DEFAULT_GUARD",
	"DIMENSIONS_PARSEABLE",
	"EXIF_DECODES_PIXELS",
	"EXIF_MAX_MEGAPIXELS",
	"HEAD_BYTES",
	"READABLE_FORMATS",
	"SEBEP_APPENDED_PAYLOAD",
	"SEBEP_TRUNCATED",
	"TAIL_BYTES",
	"GuardConfig",
	"HeaderProbe",
	"ImageRejected",
	"Rejection",
	"assert_accepted",
	"declared_dimensions",
	"guard_only",
	"probe_header",
	"sniff",
	"tail_is_complete",
]

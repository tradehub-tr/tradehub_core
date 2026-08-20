"""Künye çıkarımı — PolicyEngine'in TEK girdisi. `import frappe` YOKTUR.

PolicyEngine'e dosya değil KÜNYE verilir. Sebep: karar saf bir fonksiyon
olsun; testte 4 MB'lık dosya açmadan da, üretimde ffprobe çıktısından da aynı
karar üretilebilsin.

Bu modül üretimde çözülmüş olanı TEKRARLAMAZ:
  - görsel açma/ölçme      → `tradehub_core.media.pipeline.probe()` çağrılır
    (o modül de frappe'siz olduğu için doğrudan import edilebiliyor)
  - magic-byte imzaları    → `upload_policy._SIGNATURES` ile AYNI tablo
  - tehlikeli işaretçiler  → `upload_policy._DANGEROUS_MARKERS` ile AYNI liste

Aynalanan iki tablo `tests/test_policy_engine.py` içinde kaynak dosyadan
`ast` ile okunup karşılaştırılır; ayrışma testi düşürür.

ÜRETİMDE OLMAYAN, BURADA EKLENEN ÜÇ ÖLÇÜM
------------------------------------------
1. `appended_payload` — `upload_policy.is_dangerous()` yalnız dosyanın BAŞINA
   bakıyor (`bas.startswith(...)`, upload_policy.py:224). Geçerli bir JPEG'in
   SONUNA eklenmiş `<script>` bu kontrolden geçiyor; fixture
   `tradehub_core/tests/fixtures/malicious/jpeg_with_html_tail.jpg` tam olarak budur ve
   `user.avatar` slotunda geometri kapıları da onu durdurmuyor (320×320 > 96).
2. `container_valid` — ZIP imzası doğru ama içi docx değil
   (`tradehub_core/tests/fixtures/malicious/fake_docx.docx`). Yalnız imzaya bakan kontrol
   geçirir; `tradehub_core/kyb.py:46-53` bunu KYB yolunda zaten açıyor, burada
   slot yoluna taşındı.
3. `loadable` — `engine.probe()` başlığı okuyup `readable=True` diyor ama
   veri kesikse `optimize()` sonradan düşüyor (fixture `truncated.jpg`,
   manifest'te ÖLÇÜLDÜ). Başlık okunabilirliği ile piksel okunabilirliği ayrı
   iki sorudur; ikisi ayrı alanda tutulur.

`data:` URI ve SVG için Pillow yolu yoktur; bunlar magic/metin sezgisiyle
işaretlenir ve kararı slot politikası verir.
"""

from __future__ import annotations

import io
import os
import zipfile
from dataclasses import asdict, dataclass, field

# upload_policy.py:171-185 ile AYNI tablo (ayna; test doğruluyor).
SIGNATURES: tuple[tuple[bytes, str], ...] = (
	(b"\xff\xd8\xff", "jpeg"),
	(b"\x89PNG\r\n\x1a\n", "png"),
	(b"GIF87a", "gif"),
	(b"GIF89a", "gif"),
	(b"BM", "bmp"),
	(b"II*\x00", "tiff"),
	(b"MM\x00*", "tiff"),
	(b"%PDF-", "pdf"),
	(b"PK\x03\x04", "zip"),
	(b"\x00\x00\x00\x18ftyp", "mp4"),
	(b"\x1a\x45\xdf\xa3", "webm"),
)

# upload_policy.py:187-195 ile AYNI liste (ayna; test doğruluyor).
DANGEROUS_MARKERS: tuple[bytes, ...] = (
	b"<!doctype html",
	b"<html",
	b"<svg",
	b"<?xml",
	b"<script",
	b"<%",
	b"#!/",
)

# Tabloda olmayan, magic'i sabit ofsette olmayan biçimler.
_MZ = b"MZ"
_ELF = b"\x7fELF"
_RIFF = b"RIFF"
_WEBP = b"WEBP"
_DATA_URI = b"data:"

#: Tespit edilen türün MIME karşılığı. Politikadaki `accept.mime` ile
#: karşılaştırılır. Bilinmeyen tür için boş dizge döner ve MIME kuralı
#: DEĞERLENDİRİLMEZ (uydurma MIME ile yanlış ret üretmemek için).
MIME_BY_KIND: dict[str, str] = {
	"jpeg": "image/jpeg",
	"png": "image/png",
	"gif": "image/gif",
	"webp": "image/webp",
	"tiff": "image/tiff",
	"bmp": "image/bmp",
	"pdf": "application/pdf",
	"mp4": "video/mp4",
	"webm": "video/webm",
	"mov": "video/quicktime",
	"svg": "image/svg+xml",
	"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

#: Uzantı ile gerçek içeriğin uyumu. upload_policy.py:374-390 `_UYUM`
#: sözlüğünün aynı amaçlı, slot yoluna taşınmış hâli. `.jpg` içinden PNG
#: çıkması UYUMSUZDUR: dosya adı .jpg kalırsa Content-Type uzantıdan türeyen
#: her yol yanlış tip döndürür (fixture: polyglot_png_as.jpg).
EXTENSION_KINDS: dict[str, frozenset[str]] = {
	".jpg": frozenset({"jpeg"}),
	".jpeg": frozenset({"jpeg"}),
	".png": frozenset({"png"}),
	".gif": frozenset({"gif"}),
	".webp": frozenset({"webp"}),
	".tif": frozenset({"tiff"}),
	".tiff": frozenset({"tiff"}),
	".bmp": frozenset({"bmp"}),
	".pdf": frozenset({"pdf"}),
	".svg": frozenset({"svg"}),
	".docx": frozenset({"docx", "zip"}),
	".mp4": frozenset({"mp4"}),
	".m4v": frozenset({"mp4"}),
	".mov": frozenset({"mp4", "mov"}),
	".webm": frozenset({"webm"}),
}

KIND_IMAGE: str = "image"
KIND_VIDEO: str = "video"
KIND_DOCUMENT: str = "document"
KIND_UNKNOWN: str = "unknown"

_VIDEO_KINDS = frozenset({"mp4", "webm", "mov"})
_DOCUMENT_KINDS = frozenset({"pdf", "docx", "zip"})


@dataclass(frozen=True)
class MediaProbe:
	"""Bir yüklemenin karar için gereken tüm ölçülebilir künyesi.

	Alanların çoğu `None` olabilir. `None` "ölçülmedi" demektir ve ilgili kural
	DEĞERLENDİRİLMEZ (`SkippedRule` olarak raporlanır). `False` ile `None`
	arasındaki fark burada anlamlıdır: `has_audio=False` "ses yok" ölçümüdür,
	`has_audio=None` "bakılmadı"dır.
	"""

	# kimlik
	filename: str = ""
	extension: str = ""
	byte_size: int = 0
	sha256: str = ""

	# tür
	kind: str = KIND_UNKNOWN
	detected: str = ""          # magic'ten çıkan tür ("jpeg", "zip", …)
	mime: str = ""
	fmt: str = ""               # Pillow biçimi ("JPEG", "PNG", …)

	# geometri
	width: int = 0
	height: int = 0
	exif_orientation: int | None = None

	# görsel özellikleri
	mode: str = ""
	has_alpha: bool | None = None
	animated: bool | None = None
	dpi: tuple[int, int] | None = None
	has_icc: bool | None = None

	# okunabilirlik
	readable: bool = False      # başlık okundu mu (engine.probe)
	loadable: bool | None = None  # pikseller tam mı (im.load)

	# güvenlik
	extension_matches_content: bool | None = None
	leading_marker: bool | None = None    # dosyanın BAŞI çalıştırılabilir mi
	appended_payload: bool | None = None  # dosyanın SONUNA eklenmiş yük var mı
	container_valid: bool | None = None   # zip/docx içi tutarlı mı
	is_data_uri: bool | None = None

	# video
	duration_s: float | None = None
	bitrate_bps: int | None = None
	frame_rate: float | None = None
	has_audio: bool | None = None
	audio_codec: str = ""
	video_codec: str = ""

	# bağlam (dosyadan değil, çağrandan gelir)
	existing_count: int | None = None
	is_private: bool | None = None
	scan_clean: bool | None = None

	extra: dict = field(default_factory=dict)

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
		"""EXIF rotasyonu UYGULANMIŞ ölçü.

		Ölçüt: 5,6,7,8 numaralı EXIF orientation değerleri kareyi 90° çevirir.
		`tradehub_core/media/pipeline.py:102` çıktıda `exif_transpose` uyguluyor;
		oran kuralı da bu yüzden döndürülmüş ölçüye bakmalıdır. Fixture
		`exif_orientation6.jpg` (1200×1600 depolanmış, 1600×1200 görünen)
		bunun regresyon testidir: dosyadaki ölçü 3:4 (izinli), görünen ölçü
		4:3 (izinsiz).
		"""
		if self.exif_orientation in (5, 6, 7, 8):
			return (self.height, self.width)
		return (self.width, self.height)

	@property
	def aspect(self) -> float:
		w, h = self.display_size
		return (w / h) if h else 0.0

	def to_dict(self) -> dict:
		return asdict(self)


def sniff(content: bytes) -> str:
	"""İçeriğin gerçek türü — bilinmiyorsa boş dizge.

	`upload_policy.sniff()` ile aynı tabloyu kullanır, üç ek tanıma ile:
	RIFF/WEBP, MZ/ELF (çalıştırılabilir) ve `data:` URI. Bu üçünün ikisi
	fixture korpusunda RET beklenen dosyalardır (executable_as.png,
	data_uri_svg.txt); tabloya girmezlerse "bilinmeyen" olup sessizce
	uzantısına güvenilir.
	"""
	if not content:
		return ""
	head = content[:16]
	if head.startswith(_RIFF) and content[8:12] == _WEBP:
		return "webp"
	if head.startswith(_MZ) or head.startswith(_ELF):
		return "executable"
	if head[:5].lower() == _DATA_URI:
		return "data_uri"
	# mp4/mov: `ftyp` 4. bayttan başlar, boyut alanı sabit değildir.
	if content[4:8] == b"ftyp":
		brand = content[8:12]
		return "mov" if brand in (b"qt  ",) else "mp4"
	lowered = content[:64].lstrip().lower()
	if lowered.startswith(b"<?xml") or lowered.startswith(b"<svg"):
		return "svg" if b"<svg" in content[:2048].lower() else "xml"
	for sig, kind in SIGNATURES:
		if content.startswith(sig):
			return kind
	return ""


def kind_of(detected: str, extension: str) -> str:
	"""Geniş tür sınıfı — kural bloklarının hangisinin çalışacağını belirler."""
	if detected in _VIDEO_KINDS:
		return KIND_VIDEO
	if detected in _DOCUMENT_KINDS:
		return KIND_DOCUMENT
	if detected in ("jpeg", "png", "gif", "webp", "tiff", "bmp", "svg"):
		return KIND_IMAGE
	# Magic tanınmadıysa uzantıya DÜŞÜLÜR ama bu bir güven beyanı değildir;
	# `extension_matches_content` alanı zaten False işaretlenmiş olur.
	ext = (extension or "").lower()
	if ext in (".mp4", ".m4v", ".mov", ".webm"):
		return KIND_VIDEO
	if ext in (".pdf", ".docx"):
		return KIND_DOCUMENT
	if ext in EXTENSION_KINDS:
		return KIND_IMAGE
	return KIND_UNKNOWN


def _extension_matches(extension: str, detected: str) -> bool | None:
	ext = (extension or "").lower()
	if not detected:
		return None if not ext else False
	allowed = EXTENSION_KINDS.get(ext)
	if allowed is None:
		return None
	return detected in allowed


def _has_leading_marker(content: bytes) -> bool:
	"""upload_policy.is_dangerous() ile aynı: BOM ve baştaki boşluk atlanır."""
	head = content[:512].lstrip()
	if head.startswith(b"\xef\xbb\xbf"):
		head = head[3:].lstrip()
	head = head.lower()
	return any(head.startswith(m) for m in DANGEROUS_MARKERS)


def _has_appended_payload(content: bytes, detected: str) -> bool:
	"""Görselin yapısal sonundan SONRA çalıştırılabilir içerik var mı.

	JPEG için EOI (FFD9), PNG için IEND üzerinden kuyruk bulunur. Diğer
	biçimlerde kuyruk sınırı ucuzca bilinemez; o durumda tüm gövdede
	`<script` aranır — yanlış pozitif riski, gerçek bir XSS taşıyıcısını
	kaçırmaktan ucuzdur ve bu bayrak tek başına RET üretmez, slot politikası
	karar verir.
	"""
	if not content:
		return False
	tail = b""
	if detected == "jpeg":
		idx = content.rfind(b"\xff\xd9")
		if idx >= 0:
			tail = content[idx + 2 :]
	elif detected == "png":
		idx = content.rfind(b"IEND")
		if idx >= 0:
			tail = content[idx + 8 :]
	else:
		tail = content
	lowered = tail.lower()
	return any(m in lowered for m in (b"<script", b"<?php", b"<html", b"<!doctype html"))


def _container_valid(content: bytes, extension: str, detected: str) -> bool | None:
	"""ZIP tabanlı belgelerin içi gerçekten o belge mi.

	`tradehub_core/kyb.py:46-53` referans uygulamadır; burada uzantıya göre
	beklenen girdiler aranır. ZIP olmayan dosyalar için `None` (soru geçersiz).
	"""
	if detected != "zip" and extension.lower() != ".docx":
		return None
	if detected != "zip":
		return False
	try:
		with zipfile.ZipFile(io.BytesIO(content)) as zf:
			names = set(zf.namelist())
	except Exception:
		return False
	if extension.lower() == ".docx":
		return "[Content_Types].xml" in names and any(n.startswith("word/") for n in names)
	return True


def _image_details(content: bytes) -> dict:
	"""Pillow ile ayrıntı — `engine.probe()` üstüne mod/alfa/DPI/EXIF ekler."""
	out: dict = {}
	try:
		from PIL import Image, ImageFile
	except Exception:
		return out

	# Kesik dosyanın SESSİZCE tamamlanmasını istemiyoruz: `loadable` ölçümünün
	# anlamı buna bağlı. Global ayarı geçici olarak kapatıp geri koyuyoruz.
	onceki = ImageFile.LOAD_TRUNCATED_IMAGES
	ImageFile.LOAD_TRUNCATED_IMAGES = False
	try:
		with Image.open(io.BytesIO(content)) as im:
			out["mode"] = im.mode
			out["has_icc"] = bool(im.info.get("icc_profile"))
			dpi = im.info.get("dpi")
			if dpi:
				try:
					out["dpi"] = (int(round(dpi[0])), int(round(dpi[1])))
				except Exception:
					pass
			out["has_alpha"] = bool(
				im.mode in ("RGBA", "LA", "PA")
				or (im.mode == "P" and "transparency" in im.info)
			)
			try:
				exif = im.getexif()
				if exif:
					val = exif.get(0x0112)
					if val:
						out["exif_orientation"] = int(val)
			except Exception:
				pass
			try:
				im.load()
				out["loadable"] = True
			except Exception:
				out["loadable"] = False
	except Exception:
		out["loadable"] = False
	finally:
		ImageFile.LOAD_TRUNCATED_IMAGES = onceki
	return out


def probe_bytes(content: bytes, filename: str = "", **context) -> MediaProbe:
	"""Bayt dizisinden künye. `context` ile bağlam alanları geçilir.

	Bağlam alanları (dosyadan ölçülemeyenler): `existing_count`, `is_private`,
	`scan_clean`, ayrıca ffprobe'dan gelen video alanları.
	"""
	import hashlib

	extension = os.path.splitext(filename)[1].lower() if filename else ""
	detected = sniff(content)
	kind = kind_of(detected, extension)

	base: dict = {
		"filename": filename,
		"extension": extension,
		"byte_size": len(content),
		"sha256": hashlib.sha256(content).hexdigest(),
		"kind": kind,
		"detected": detected,
		"mime": MIME_BY_KIND.get(detected, "") or MIME_BY_KIND.get(
			(extension or "").lstrip("."), ""
		),
		"extension_matches_content": _extension_matches(extension, detected),
		"leading_marker": _has_leading_marker(content),
		"appended_payload": _has_appended_payload(content, detected),
		"container_valid": _container_valid(content, extension, detected),
		"is_data_uri": detected == "data_uri",
	}

	if kind == KIND_IMAGE and detected != "svg":
		# Üretim motorunun kendi probe'u — TEKRARLANMADI, çağrıldı.
		from tradehub_core.media.engine import probe as engine_probe

		p = engine_probe(content)
		base.update(
			{
				"fmt": p.fmt,
				"width": p.width,
				"height": p.height,
				"animated": p.animated,
				"readable": p.readable,
			}
		)
		base.update(_image_details(content))
	elif kind == KIND_IMAGE:
		base["readable"] = False  # SVG: Pillow yolu yok, karar politikanın

	base.update({k: v for k, v in context.items() if k in MediaProbe.__dataclass_fields__})
	return MediaProbe(**base)


def probe_file(path, **context) -> MediaProbe:
	"""Diskteki dosyadan künye."""
	with open(path, "rb") as fh:
		content = fh.read()
	return probe_bytes(content, filename=os.path.basename(str(path)), **context)


def probe_video_from_ffprobe(data: dict, filename: str = "", **context) -> MediaProbe:
	"""ffprobe/manifest çıktısından video künyesi.

	Video için Pillow yolu yoktur; `tradehub_core/media/transcode.py` zaten
	ffprobe çağırıyor. Bu fonksiyon o çıktının (ya da manifest'teki ölçülmüş
	kopyasının) künyeye çevrilmesidir — ffprobe İKİNCİ KEZ çağrılmaz.
	"""
	fps = data.get("fps")
	if isinstance(fps, str) and "/" in fps:
		pay, payda = fps.split("/", 1)
		try:
			fps = float(pay) / float(payda) if float(payda) else None
		except Exception:
			fps = None
	elif fps is not None:
		fps = float(fps)

	bitrate_kbps = data.get("bitrate_kbps")
	base = {
		"filename": filename,
		"extension": os.path.splitext(filename)[1].lower() if filename else "",
		"byte_size": int(data.get("bytes") or 0),
		"sha256": data.get("sha256", ""),
		"kind": KIND_VIDEO,
		"detected": "mp4",
		"mime": "video/mp4",
		"width": int(data.get("width") or 0),
		"height": int(data.get("height") or 0),
		"readable": bool(data.get("width")),
		"loadable": bool(data.get("width")),
		"duration_s": float(data["duration_s"]) if data.get("duration_s") is not None else None,
		"bitrate_bps": int(bitrate_kbps) * 1000 if bitrate_kbps is not None else None,
		"frame_rate": fps,
		"has_audio": data.get("has_audio"),
		"audio_codec": data.get("audio_codec") or "",
		"video_codec": data.get("video_codec") or "",
		"animated": True,
		"extension_matches_content": True,
		"leading_marker": False,
		"appended_payload": False,
	}
	base.update({k: v for k, v in context.items() if k in MediaProbe.__dataclass_fields__})
	return MediaProbe(**base)

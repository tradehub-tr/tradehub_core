"""T-017 — Yükleme kapısının İÇERİK denetimi. `import frappe` YOKTUR.

Neden bu modül var
------------------
`tradehub_core/media/upload_policy.py` bütün yükleme yollarının tek kapısı, ama
kapının içerik tarafı yalnız **dosyanın ilk 512 baytına** bakıyordu
(`is_dangerous`). Ölçüldü — `tradehub_core/tests/fixtures/malicious/` içindeki
10 dosyanın **8'i kapıdan geçti** (`docs/reports/33-dogrulama-faz0-3.md` §T-017,
bu oturumda bağımsız olarak tekrarlandı). Geçenler ve **neden** geçtikleri:

    bomb_100mp.png          piksel tavanı YOKTU (100 MP, 97 KB)
    executable_as.png       MZ/ELF sihirli baytı tanınmıyordu
    data_uri_svg.txt        `data:` URI tanınmıyordu, `.txt` serbest uzantı
    jpeg_with_html_tail.jpg kontrol yalnız BAŞA bakıyordu, EOI sonrası gövde serbest
    polyglot_pdf_as.jpg     uzantı/içerik uyuşmazlığı yalnız UYARI üretiyordu
    polyglot_png_as.jpg     aynı sebep
    truncated.jpg           kesiklik hiç ölçülmüyordu
    fake_docx.docx          zip imzası doğru diye geçiyordu, içi hiç açılmıyordu

`media/pipeline/image/probe.py` bu kontrollerin çoğunu zaten **doğru** yapıyordu
ama onu hiçbir yükleme yolu ÇAĞIRMIYORDU: kapı ile denetim iki ayrı yerde
duruyordu. Bu modül aradaki köprüdür — `upload_policy.check()` içinden çağrılır,
böylece medya uçları da, 22 ekranın geçtiği `File.before_insert` kancası da aynı
denetimden geçer.

Neden ayrı dosya (upload_policy'nin içine yazılmadı)
----------------------------------------------------
`upload_policy` frappe'ye bağlı; bench/site olmadan import edilemiyor. Denetim
mantığı burada durursa `tests/test_media_security_gate.py` bench'siz koşar ve
kural, i18n/istisna kabuğundan bağımsız olarak test edilebilir.

Sezgiler TEKRAR YAZILMADI
--------------------------
`sniff`, `_has_leading_marker`, `_has_appended_payload`, `_extension_matches`
`media/pipeline/core/probe.py`'dan; başlık okuma `media/pipeline/image/probe.py`
`_open_header`'dan çağrılır. Aynı sorunun ikinci bir uygulaması, ikisinin
ayrışacağı gün demektir (bu depoda ölçüldü: kapı ile denetim tam olarak böyle
ayrışmıştı).

EŞİKLER — hepsi bu depodaki GERÇEK korpusta ölçüldü
----------------------------------------------------
Korpus: `sites/istoc.localhost/public/files` (4.584 dosya, 3.897'si Pillow ile
açılabilir görsel) + `private/files` (1.010 dosya) + fixture korpusu (34 görsel,
7 video). Ölçüm çıktısı `docs/reports/38-t017-guvenlik-kapisi.md` §2'de.

    MAX_MEGAPIXELS = 80.0
        Gerçek public korpusun en büyüğü **72,71 MP** (10315×7049 JPEG);
        >20 MP olan 120 dosya var. 80 MP bugünkü hiçbir gerçek dosyayı kesmez
        ve 100 MP'lik bombayı durdurur. Pay yalnız %10 — bu bilinçli:
        `slots/*.json` `accept.max_megapixels_hard` slot bazında DAHA DAR
        (product-image = 80, user-avatar = 0,0655). Buradaki değer platform
        çapındaki son emniyet, slot kapısı değil.

    Sıkıştırma oranı (piksel/bayt) EŞİK OLARAK KULLANILMADI — ölçüldü, ayrık
    değil: gerçek korpusta p99,9 = 210, **max = 678** (1 MP lossless WebP),
    bombada 1.029. 1,5 katlık ayrım güvenilir bir eşik vermez; yanlış pozitifi
    gerçek logo/düz zemin görsellerinde üretirdi. Bomba savunmasının ikinci
    katmanı bu yüzden eşik değil, `security/isolation.py` (rlimit'li alt süreç).

    OOXML doğrulaması: gerçek korpusta 30 `.xlsx` + 1 `.docx` var, **31/31'inde**
    `[Content_Types].xml` ve doğru kök dizin (`xl/`, `word/`) mevcut.
    `fake_docx.docx`'te ikisi de yok. Düz `.zip` (11 adet, içi ürün görseli)
    DOĞRULANMAZ — zip bir kap, iddia edilen bir iç yapısı yok.
"""

from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass

from tradehub_core.media.pipeline.core import probe as core_probe

#: Piksel tavanı — gerekçe ve ölçüm modül başlığında.
MAX_MEGAPIXELS: float = 80.0

#: Başlık taraması için okunacak ön parça. `_has_leading_marker` ilk 512 bayta
#: bakar; 64 KB, kuyruk/başlık taramalarının ikisine de yeter.
HEAD_BYTES: int = 64 * 1024

#: Kuyruk taraması. JPEG'in en uzun EOI-öncesi segmenti (APPn, 64 KB) kadar.
TAIL_BYTES: int = 64 * 1024

#: Tarayıcının ya da işletim sisteminin ÇALIŞTIRABİLECEĞİ, hiçbir yükleme
#: slotunda karşılığı olmayan içerik türleri. Gerçek korpusta 0 dosya.
FORBIDDEN_KINDS: frozenset[str] = frozenset({"executable", "data_uri", "svg", "xml"})

#: Uzantısı görsel olan bir dosyanın içeriği bu sınıflardan biriyse RET.
IMAGE_KINDS: frozenset[str] = frozenset({"jpeg", "png", "gif", "webp", "tiff", "bmp"})

#: Uzantısı bunlardan biri olan dosya "görsel" iddiasındadır.
IMAGE_EXTENSIONS: frozenset[str] = frozenset(
	{".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif", ".heic"}
)

#: OOXML: zip kabının içinde İDDİA EDİLEN yapı aranır.
OOXML_ROOTS: dict[str, str] = {".docx": "word/", ".xlsx": "xl/", ".pptx": "ppt/"}

#: Kesiklik ölçülebilen biçimler — diğerlerinde kural DEĞERLENDİRİLMEZ.
TRUNCATION_MEASURABLE: frozenset[str] = frozenset({"jpeg", "png", "gif"})


# ── Bulgu ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Bulgu:
	"""Tek bir ret gerekçesi.

	`kod` istemcinin okuduğu sözleşmedir (`upload_policy.Kod.kod` ile aynı
	biçim); `mesaj` kullanıcıya gösterilecek metnin ÇEKİRDEĞİdir — i18n
	`upload_policy` tarafında yapılır, bu modül frappe'ye bağlı değildir.
	"""

	kod: str
	mesaj: str
	olculen: object = None
	beklenen: object = None


# Ret kodları — `upload_policy` bunları `Kod` nesnelerine eşler.
KOD_DANGEROUS: str = "upload_content_dangerous"
KOD_APPENDED: str = "upload_appended_payload"
KOD_MISMATCH: str = "upload_type_mismatch"
KOD_BOMB: str = "upload_image_bomb"
KOD_TRUNCATED: str = "upload_content_truncated"
KOD_CONTAINER: str = "upload_container_invalid"


# ── Yardımcılar ─────────────────────────────────────────────────────────


def _kuyruk_tam(tail: bytes, detected: str) -> bool | None:
	"""Biçimin bitiş işareti kuyrukta var mı — decode YOK.

	`None` = "bu biçimde ucuzca ölçülemez"; o durumda kural atlanır, sessizce
	"tamam" SAYILMAZ. `image/probe.tail_is_complete` ile aynı sınırlar:
	JPEG EOI = FF D9 (ITU-T T.81 B.1.1.3), PNG IEND (RFC 2083 §3.4),
	GIF trailer = 0x3B (GIF89a §23).
	"""
	if not tail or detected not in TRUNCATION_MEASURABLE:
		return None
	if detected == "jpeg":
		return tail.rfind(b"\xff\xd9") >= 0
	if detected == "png":
		return tail.rfind(b"IEND") >= 0
	return tail.rstrip(b"\x00").endswith(b"\x3b")


def _ooxml_gecerli(content: bytes, uzanti: str) -> bool | None:
	"""OOXML kabı iddia ettiği belge mi.

	`None` = soru bu dosya için geçersiz (OOXML uzantısı değil). Düz `.zip`
	DOĞRULANMAZ: zip'in iddia ettiği bir iç yapı yoktur ve gerçek korpusta
	11 tanesi ürün görseli arşivi.
	"""
	kok = OOXML_ROOTS.get(uzanti)
	if kok is None:
		return None
	try:
		with zipfile.ZipFile(io.BytesIO(content)) as zf:
			adlar = zf.namelist()
	except Exception:
		return False
	return "[Content_Types].xml" in adlar and any(a.startswith(kok) for a in adlar)


def _tehlikeli_uyusmazlik(uzanti: str, detected: str) -> bool:
	"""Bu uyuşmazlık saldırı mı, gürültü mü.

	RET edilen: uzantı GÖRSEL diyor ama içerik başka bir bilinen tür.
	  - başka bir görsel biçimi  → `polyglot_png_as.jpg`
	  - belge/arşiv/aktif içerik → `polyglot_pdf_as.jpg`
	Sebep: `Content-Type` bu sistemde uzantıdan türetiliyor; bayt akışı ile
	ilan edilen tür ayrışırsa tarayıcının sniff davranışı kararı devralır.
	Gerçek korpusta bu sınıftan **0** dosya var (4.584 public + 1.010 private).

	RET EDİLMEYEN: video kabı uyuşmazlığı (`.mp4` içinde webm). Gerçek
	korpusta **1** dosya var ve tarayıcı MediaRecorder çıktısında yaygın;
	iki taraf da hareketsiz kap, çalıştırılabilir değil. Uyarı olarak kalır.
	Bilinmeyen sihirli bayt (`detected == ""`) da uyuşmazlık SAYILMAZ:
	`.txt`/`.csv`/`.avif`/`.heic` gerçek korpusta 640 + 852 dosya.
	"""
	if not detected or uzanti not in IMAGE_EXTENSIONS:
		return False
	beklenen = core_probe.EXTENSION_KINDS.get(uzanti)
	if beklenen is None:
		# `.avif` / `.heic`: tabloda yok, sihirli baytı da tanınmıyor.
		return False
	return detected not in beklenen


def _boyut_basliktan(content: bytes, detected: str) -> tuple[int, int] | None:
	"""Piksel ölçüsü — `im.load()` ÇAĞRILMAZ, gerekiyorsa Pillow'suz.

	Önce BEYAN edilen ölçü ham baytlardan okunur
	(`image/probe.declared_dimensions`). Sebep ölçülmüş bir kaçış (rapor 75
	bulgu 4): Pillow, kendi `MAX_IMAGE_PIXELS` tavanının üstünde boyut beyan
	eden başlığı hiç açmıyor (`DecompressionBombError`), ölçü 0 kalıyor ve
	80 MP tavanı hiç değerlendirilmiyordu — 30000×30000 PNG kapıdan 200 ile
	geçti; yalnız 80–89 MP penceresi yakalanıyordu. Ham baytlardan
	okunamayan biçimlerde (TIFF) Pillow'un tembel `Image.open` başlığı
	kullanılır: başlığı ayrıştırır, piksel verisine dokunmaz.

	`None` = başlık HİÇBİR yolla okunamadı. Çağıran bunu "geçer" değil,
	görsel biçimlerde FAIL-CLOSED ret olarak yorumlar. 0/negatif ölçü
	OLDUĞU GİBİ döner — o karar da çağıranın fail-closed kuralına aittir.
	"""
	from tradehub_core.media.pipeline.image.probe import _open_header, declared_dimensions

	beyan = declared_dimensions(content[:HEAD_BYTES], detected)
	if beyan is not None and beyan[0] > 0 and beyan[1] > 0:
		return beyan
	baslik = _open_header(io.BytesIO(content))
	w, h = int(baslik.get("width", 0) or 0), int(baslik.get("height", 0) or 0)
	if w > 0 and h > 0:
		return (w, h)
	# İki yol da pozitif ölçü veremedi. Ham başlık 0/negatif BEYAN etmişse o
	# beyan döner (fail-closed retin `olculen` alanına girer); hiçbiri yoksa None.
	return beyan


# ── Kapı ────────────────────────────────────────────────────────────────


def inspect(
	file_name: str,
	content: bytes,
	*,
	max_megapixels: float = MAX_MEGAPIXELS,
) -> tuple[Bulgu, ...]:
	"""İçeriği denetle — bulgu LİSTESİ döner, istisna ATMAZ.

	Sıra anlamlıdır: kullanıcıya gösterilecek tek gerekçe, en erken ve en
	anlaşılır olanıdır (FR-062). Önce hiç açmadan verilebilecek retler, en
	sonda başlıktan okunan piksel tavanı.
	"""
	if not content:
		return ()

	uzanti = os.path.splitext((file_name or "").strip().split("?", 1)[0])[1].lower()
	bas = content[:HEAD_BYTES]
	kuyruk = content[-TAIL_BYTES:] if len(content) > TAIL_BYTES else content
	detected = core_probe.sniff(bas)

	bulgular: list[Bulgu] = []

	# 1 — Dosyanın BAŞI çalıştırılabilir işaretle başlıyor mu.
	#     (`upload_policy.is_dangerous` bunu zaten yapıyordu; burada aynı
	#      sezgiden geçirilip tek yerde toplanıyor.)
	if core_probe._has_leading_marker(bas):
		bulgular.append(
			Bulgu(
				KOD_DANGEROUS,
				"Dosyanın içeriği tarayıcıda çalıştırılabilir (HTML/SVG/script).",
				olculen=detected or "markup",
			)
		)

	# 2 — Sihirli bayt hiçbir slotta karşılığı olmayan bir türü gösteriyor mu.
	elif detected in FORBIDDEN_KINDS:
		bulgular.append(
			Bulgu(
				KOD_DANGEROUS,
				"Dosya bir medya dosyası değil; çalıştırılabilir içerik ya da gömülü URI.",
				olculen=detected,
			)
		)

	# 3 — Uzantı görsel diyor, içerik başka bir bilinen tür.
	if _tehlikeli_uyusmazlik(uzanti, detected):
		bulgular.append(
			Bulgu(
				KOD_MISMATCH,
				"Dosyanın uzantısı içeriğiyle uyuşmuyor.",
				olculen=detected,
				beklenen=uzanti,
			)
		)

	# 4 — Görselin yapısal sonundan SONRA eklenmiş çalıştırılabilir gövde.
	if detected in IMAGE_KINDS and core_probe._has_appended_payload(content, detected):
		bulgular.append(
			Bulgu(
				KOD_APPENDED,
				"Görselin sonuna çalıştırılabilir içerik eklenmiş.",
				olculen="tail_markup",
			)
		)

	# 5 — OOXML kabı iddia ettiği belge mi.
	if _ooxml_gecerli(content, uzanti) is False:
		bulgular.append(
			Bulgu(
				KOD_CONTAINER,
				"Belge dosyası bozuk ya da iddia ettiği biçimde değil.",
				olculen=detected or "?",
				beklenen=uzanti,
			)
		)

	# 6 — Kesiklik. `None` (ölçülemez) sessizce "tamam" SAYILMAZ, kural atlanır.
	if _kuyruk_tam(kuyruk, detected) is False:
		bulgular.append(
			Bulgu(
				KOD_TRUNCATED,
				"Dosya eksik; veri akışı yarıda kesilmiş.",
				olculen=detected,
			)
		)

	# 7 — Piksel tavanı. Başlıktan okunur, hiçbir piksel açılmaz. Kural
	#     FAIL-CLOSED (rapor 75 bulgu 4): içerik bilinen bir görsel biçimiyse
	#     ölçüsü OKUNAMAYAN ya da 0/negatif okunan dosya da REDDEDİLİR —
	#     Pillow'un kendi tavanının üstünde boyut beyan eden bomba artık
	#     "boyut 0" gölgesinde kuraldan kaçamaz (30000×30000 PNG böyle geçmişti;
	#     ölçü artık `declared_dimensions` ile ham baytlardan okunuyor).
	#     Koşulda uzantı da var: HEIC/AVIF ISOBMFF kabıdır ve `sniff` onları
	#     `mp4`/"" diye tanır (4. bayttan `ftyp`), yani `IMAGE_KINDS` testinden
	#     kaçarlardı. Fail-closed dalı yalnız `IMAGE_KINDS` içindir: ölçüsü
	#     hiçbir yolla okunamayan AVIF/HEIC'te kural ESKİSİ GİBİ atlanır —
	#     meşru AVIF/HEIC korpusu (852 dosya) kesilmez.
	if (detected in IMAGE_KINDS or uzanti in IMAGE_EXTENSIONS) and max_megapixels:
		olcu = _boyut_basliktan(content, detected)
		if olcu is None:
			if detected in IMAGE_KINDS:
				bulgular.append(
					Bulgu(
						KOD_BOMB,
						"Görselin boyutu başlıktan okunamadı; güvenlik gereği reddedildi.",
						olculen="unreadable_header",
						beklenen=max_megapixels,
					)
				)
		else:
			w, h = olcu
			mp = (w * h) / 1_000_000.0
			if w <= 0 or h <= 0:
				bulgular.append(
					Bulgu(
						KOD_BOMB,
						"Görselin boyutu başlıktan okunamadı; güvenlik gereği reddedildi.",
						olculen=(w, h),
						beklenen=max_megapixels,
					)
				)
			elif mp > max_megapixels:
				bulgular.append(
					Bulgu(
						KOD_BOMB,
						"Görsel çözünürlüğü sınırı aşıyor; açılmadan reddedildi.",
						olculen=round(mp, 3),
						beklenen=max_megapixels,
					)
				)

	return tuple(bulgular)


__all__ = [
	"HEAD_BYTES",
	"IMAGE_EXTENSIONS",
	"IMAGE_KINDS",
	"KOD_APPENDED",
	"KOD_BOMB",
	"KOD_CONTAINER",
	"KOD_DANGEROUS",
	"KOD_MISMATCH",
	"KOD_TRUNCATED",
	"MAX_MEGAPIXELS",
	"OOXML_ROOTS",
	"TAIL_BYTES",
	"Bulgu",
	"inspect",
]

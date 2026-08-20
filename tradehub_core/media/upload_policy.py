"""Yükleme politikası — kuralın tek sahibi (TUR-123).

**Sorun, ölçümle.** Panelde iki ayrı yükleme yolu vardı:

    seller_media.upload_media   1 ekran   uzantı listesi + 25 MB + kapsam + denetim
    Frappe upload_file         22 ekran   yalnız yasaklı uzantı kancası

Yani medya kütüphanesine koyduğumuz kurallar tek ekranda geçerliydi. Satıcı
ürün formundan, toplu yüklemeden, vitrin düzenleyiciden geçen dosyalarda ne
boyut sınırı ne içerik denetimi vardı. "Kurallar sunucuda" demek, kuralın
GİRİLEN HER KAPIDA olması demek; tek kapıda olması yetmez.

**Çözüm.** Kural bu modülde tanımlanır, iki yerden birden uygulanır: medya
uçları doğrudan çağırır, geri kalan 22 ekran ise `File` kaydı açılırken çalışan
kanca üzerinden aynı kuraldan geçer. Kimsenin ekranına dokunmadan hepsi
korunur.

**Neden yasaklı liste hâlâ duruyor.** Mevcut kanca bir YASAK listesiydi (svg,
html, js, xml…). Bunu izin listesine çevirmek, bugün çalışan ve listede olmayan
her akışı sessizce kırardı. Yasak listesi olduğu gibi korunuyor; üstüne boyut
sınırı ve tehlikeli içerik kontrolü ekleniyor. İzin listesi yalnız MEDYA
uçlarında geçerli — orası bizim kapımız, dar tutulabilir.

**Neden her tür uyuşmazlığı reddedilmiyor.** Reddedilen şey yalnız TEHLİKELİ
uyuşmazlık: uzantısı GÖRSEL diyen bir dosyanın içinden başka bir bilinen tür
çıkması (`polyglot_pdf_as.jpg`, `polyglot_png_as.jpg`). Ölçüm: 4.584 public +
1.010 private gerçek dosyada bu sınıftan **0** dosya var, yani kural bugünkü
hiçbir akışı kesmiyor. Reddedilmeyen iki gürültü sınıfı: sihirli baytı hiç
tanınmayan dosyalar (`.txt`/`.csv`/`.avif`/`.heic` — 1.492 gerçek dosya) ve
video kabı uyuşmazlığı (`.mp4` içinde webm — 1 gerçek dosya, tarayıcı
MediaRecorder çıktısında yaygın).

**T-017 — kapının içerik tarafı (2026-08-19).** Bu modül eskiden içeriğin
yalnız ilk 512 baytına bakıyordu; ölçüldü, `tests/fixtures/malicious/`
içindeki 10 dosyanın 8'i geçiyordu. Derin denetim
`media/pipeline/security/content_gate.py` içinde toplandı ve `check()`
buradan çağırıyor — piksel bombası, eklenmiş yük, kesiklik, sahte OOXML kabı,
çalıştırılabilir sihirli bayt ve `data:` URI artık kapıda duruyor.
Gerekçe ve ölçüm: `docs/reports/38-t017-guvenlik-kapisi.md`.

**Hata kodları.** Her ret bir kodla döner. İstemci koda bakıp karar verir:
yeniden denenecek mi, kullanıcıya ne denecek. Metne bakarak karar vermek,
çeviri değişince kırılan bir sözleşme olurdu.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

import frappe
from frappe import _

# ── Türler ve sınırlar ──────────────────────────────────────────────────
#
# Sınırlar ölçümle seçildi (4003 public dosya): 25 MB üstü dosya YOK, en büyük
# 21 MB'lık bir TIFF. Yani görsel için 25 MB bugünkü kullanımı kesmiyor.
#
# Video sınırı ayrı ve yüksek: izin listesinde mp4/mov varken 25 MB tavan
# koymak kendi içinde çelişkiydi — gerçek video nadiren o kadar küçük olur.
# Ürünün video alanı var; yüklenemeyen bir alan tanımlamak anlamsız.

KIND_IMAGE = "image"
KIND_VIDEO = "video"
KIND_DOCUMENT = "document"
KIND_OTHER = "other"

EXTENSIONS: dict[str, str] = {
	**{
		e: KIND_IMAGE
		for e in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif", ".heic")
	},
	**{e: KIND_VIDEO for e in (".mp4", ".webm", ".mov", ".m4v")},
	**{e: KIND_DOCUMENT for e in (".pdf", ".doc", ".docx", ".xls", ".xlsx")},
	**{e: KIND_OTHER for e in (".txt", ".csv", ".zip")},
}

MAX_BYTES: dict[str, int] = {
	KIND_IMAGE: 25 * 1024 * 1024,
	KIND_VIDEO: 200 * 1024 * 1024,
	KIND_DOCUMENT: 50 * 1024 * 1024,
	KIND_OTHER: 50 * 1024 * 1024,
}

# Türü bilinmeyen dosyalar için tavan. Kanca yolunda izin listesi
# uygulanmıyor (bkz. modül başlığı), ama sınırsız da bırakılamaz.
MAX_BYTES_UNKNOWN: int = 50 * 1024 * 1024

# Medya uçlarının kabul ettiği türler — dar kapı.
MEDIA_KINDS: frozenset[str] = frozenset({KIND_IMAGE, KIND_VIDEO})
MEDIA_EXTRA_EXTENSIONS: frozenset[str] = frozenset({".pdf"})

# `File.file_name` sütun sınırı. `files.MAX_NAME` ile aynı değer; oradan
# içe aktarmak döngüsel bağımlılık kuracağı için burada tekrar tanımlı.
MAX_NAME: int = 140

# Tek istekte gönderilebilecek en büyük gövde. Bunun üstü parçalı yüklemeye
# gider (bkz. `chunked.py`). base64 içeriği ~%33 şişirdiği için ham sınırın
# altında tutuluyor.
SINGLE_SHOT_LIMIT: int = 8 * 1024 * 1024


# ── Hata kodları ────────────────────────────────────────────────────────
#
# `retryable` istemcinin otomatik yeniden deneyip denemeyeceğini söyler.
# Kural basit: kullanıcının dosyasıyla ilgili hatalar tekrar denenmez (aynı
# dosya aynı sonucu verir), geçici sistem hataları denenir.

@dataclass(frozen=True)
class Kod:
	kod: str
	retryable: bool


NAME_REQUIRED = Kod("upload_name_required", False)
NAME_INVALID = Kod("upload_name_invalid", False)
EXT_DENIED = Kod("upload_ext_denied", False)
EXT_NOT_ALLOWED = Kod("upload_ext_not_allowed", False)
TOO_LARGE = Kod("upload_too_large", False)
CONTENT_EMPTY = Kod("upload_content_empty", False)
CONTENT_UNREADABLE = Kod("upload_content_unreadable", False)
CONTENT_DANGEROUS = Kod("upload_content_dangerous", False)
# T-017 — içerik denetiminin ürettiği beş yeni ret. Hepsi kullanıcının
# dosyasıyla ilgili: aynı dosya aynı cevabı verir, tekrar denenmez.
CONTENT_APPENDED = Kod("upload_appended_payload", False)
CONTENT_MISMATCH = Kod("upload_type_mismatch", False)
CONTENT_BOMB = Kod("upload_image_bomb", False)
CONTENT_TRUNCATED = Kod("upload_content_truncated", False)
CONTENT_CONTAINER = Kod("upload_container_invalid", False)
STORE_REQUIRED = Kod("upload_store_required", False)
SESSION_UNKNOWN = Kod("upload_session_unknown", False)
CHUNK_ORDER = Kod("upload_chunk_order", True)
CHUNK_MISSING = Kod("upload_chunk_missing", True)
TOO_MANY_CHUNKS = Kod("upload_too_many_chunks", False)
# Kota reddi bu modülün KENDİ kontrolü değil — `entitlement.checks.
# check_media_storage_quota` veriyor. Kod yine burada tanımlı: istemci tek bir
# ret sözleşmesi görsün diye. Tekrar denenmez; satıcı yer açmadan aynı cevap.
QUOTA_EXCEEDED = Kod("upload_quota_exceeded", False)
# W7 (rapor 78 W5-2) — istemci slot BEYAN ETTİ ama beyan hiçbir politikaya
# denk gelmiyor. Sessizce yok saymak, bozuk (ya da kasıtlı bozulmuş) bir slot
# adıyla kapının tamamını atlamak demekti; açık ret verilir. Slot HİÇ
# verilmemişse (genel yükleme) kapı zaten koşmaz — bkz. `check_slot`.
SLOT_UNKNOWN = Kod("upload_slot_unknown", False)

ALL_CODES: tuple[Kod, ...] = (
	NAME_REQUIRED,
	NAME_INVALID,
	EXT_DENIED,
	EXT_NOT_ALLOWED,
	TOO_LARGE,
	CONTENT_EMPTY,
	CONTENT_UNREADABLE,
	CONTENT_DANGEROUS,
	CONTENT_APPENDED,
	CONTENT_MISMATCH,
	CONTENT_BOMB,
	CONTENT_TRUNCATED,
	CONTENT_CONTAINER,
	STORE_REQUIRED,
	SESSION_UNKNOWN,
	CHUNK_ORDER,
	CHUNK_MISSING,
	TOO_MANY_CHUNKS,
	QUOTA_EXCEEDED,
	SLOT_UNKNOWN,
)

RETRYABLE: frozenset[str] = frozenset(k.kod for k in ALL_CODES if k.retryable)


class UploadRejected(frappe.ValidationError):
	"""Politika reddi.

	Ayrı bir sınıf: Frappe yanıtta sınıf adını `exc_type` olarak döndürüyor ve
	istemci hata kodunu oradan okuyor. Düz `ValidationError` fırlatmak, istemciyi
	hata METNİNE bakmaya zorlardı — çeviri değişince kırılan bir sözleşme.
	"""


def reddet(kod: Kod, mesaj: str) -> None:
	"""Kodlu ret — mesaj kullanıcıya, kod istemciye.

	`frappe.local.response` istek dışı bağlamlarda (scheduler, konsol, stub'lı
	test) bulunmayabiliyor; markör mesajın sonunda zaten taşındığı için yanıt
	sözlüğüne yazamamak reddi düşürmemeli.
	"""
	try:
		frappe.local.response["upload_error"] = kod.kod
	except Exception:
		pass
	frappe.throw(f"{mesaj} [{kod.kod}]", exc=UploadRejected)


# ── İçerik imzaları ─────────────────────────────────────────────────────
#
# Uzantıya güvenilmez: adı `.jpg` olan bir dosyanın içi HTML olabilir ve
# tarayıcı onu HTML olarak açarsa saklı XSS olur. Bu yüzden içeriğin ilk
# baytlarına bakılıyor.

_SIGNATURES: tuple[tuple[bytes, str], ...] = (
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

# Tarayıcının ÇALIŞTIRABİLECEĞİ içerikler. Görsel/belge diye gelen bir dosyanın
# içi bunlardan biriyse reddedilir.
_DANGEROUS_MARKERS: tuple[bytes, ...] = (
	b"<!doctype html",
	b"<html",
	b"<svg",
	b"<?xml",
	b"<script",
	b"<%",
	b"#!/",
)


def sniff(icerik: bytes) -> str:
	"""İçeriğin gerçek türü — bilinmiyorsa boş."""
	if not icerik:
		return ""
	bas = icerik[:32]
	for imza, ad in _SIGNATURES:
		if bas.startswith(imza):
			return ad
	# RIFF konteyneri: WEBP ve WAV aynı başlıkla başlar, ayrımı 8. bayttan.
	if bas.startswith(b"RIFF") and icerik[8:12] == b"WEBP":
		return "webp"
	if icerik[4:12] in (b"ftypisom", b"ftypmp42", b"ftypqt  ") or icerik[4:8] == b"ftyp":
		return "mp4"
	return ""


def is_dangerous(icerik: bytes) -> bool:
	"""İçerik tarayıcıda çalışabilir mi.

	Baştaki boşluklar atlanıyor: `   <svg…` ile `<svg…` aynı şekilde çalışır,
	yalnız ilk baytı kontrol etmek boşluk eklemekle atlatılabilirdi.
	"""
	if not icerik:
		return False
	# Baştaki boşluklar ve BOM atlanıyor (`\xef\xbb\xbf` = UTF-8 BOM).
	bas = icerik[:512].lstrip(b" \t\r\n\xef\xbb\xbf").lower()
	return any(bas.startswith(m) for m in _DANGEROUS_MARKERS)


# ── Ad ve uzantı ────────────────────────────────────────────────────────


def extension_of(ad: str) -> str:
	kaynak = (ad or "").strip().split("?", 1)[0].split("#", 1)[0]
	return os.path.splitext(kaynak)[1].lower()


def kind_of(ad: str) -> str:
	return EXTENSIONS.get(extension_of(ad), "")


def platform_limit() -> int:
	"""Frappe'nin kendi dosya boyutu tavanı.

	ÖNEMLİ: bu tavan bizimkinden bağımsız ve `File` kaydı açılırken uygulanıyor.
	Yani buradaki sınırı ne kadar yükseltirsek yükseltelim, üstünü Frappe
	reddediyor — ölçümle görüldü: 26 MB'lık bir dosya bizim kurala hiç gelmeden
	"File size exceeded the maximum allowed size of 25.0 MB" ile düşüyor.

	Bu yüzden ilan edilen sınır GERÇEKLEŞEBİLİR olanla kısıtlanıyor. İstemciye
	200 MB deyip 25 MB'da reddetmek, kullanıcıyı dosyayı yükledikten sonra
	hayal kırıklığına uğratırdı.

	Video için gerçekten 200 MB isteniyorsa site ayarındaki `max_file_size`
	yükseltilmeli (bkz. MEDYA-YUKLEME-SOZLESMESI.md §4).
	"""
	try:
		from frappe.core.api.file import get_max_file_size

		return int(get_max_file_size())
	except Exception:
		return 25 * 1024 * 1024


def effective_max(tur: str) -> int:
	"""Bu tür için gerçekten geçerli sınır — ikisinden küçük olanı."""
	bizim = MAX_BYTES.get(tur, MAX_BYTES_UNKNOWN)
	return min(bizim, platform_limit())


def max_bytes_for(ad: str) -> int:
	return effective_max(kind_of(ad))


def clean_name(ad: str) -> str:
	"""Adı güvenli hâle getir — reddetme, düzelt.

	Yol karakteri ve null bayt REDDEDİLİR (kasıt gerektirir). Uzunluk ise
	kırpılır: kullanıcıyı uzun ad yüzünden geri çevirmek gereksiz sürtünme,
	sütun sınırını aşmaksa veritabanı hatası.
	"""
	temiz = (ad or "").strip()
	if not temiz:
		reddet(NAME_REQUIRED, _("Dosya adı zorunlu."))
	if any(k in temiz for k in ("/", "\\", "\0")):
		reddet(NAME_INVALID, _("Dosya adında yol karakteri kullanılamaz."))
	if temiz in (".", ".."):
		reddet(NAME_INVALID, _("Geçersiz dosya adı."))

	uzanti = extension_of(temiz)
	if len(temiz) <= MAX_NAME:
		return temiz
	govde = temiz[: MAX_NAME - len(uzanti)]
	return f"{govde}{uzanti}"


# ── Karar ───────────────────────────────────────────────────────────────


@dataclass
class Karar:
	"""Politika sonucu — reddedilmediyse temizlenmiş ad ve tür."""

	file_name: str
	kind: str
	bytes: int = 0
	warnings: list[str] = field(default_factory=list)


def check(
	file_name: str,
	*,
	content: bytes | None = None,
	size: int = 0,
	media_endpoint: bool = False,
) -> Karar:
	"""Tek doğrulama noktası — her yükleme yolu buradan geçer.

	`media_endpoint=True` medya uçları içindir: dar izin listesi uygulanır.
	`False` kanca yolu içindir: yasak listesi + boyut + tehlikeli içerik.

	`content` verilmezse içerik kontrolleri atlanır (dosya diskte hazır olabilir,
	geri yüklemede olduğu gibi). Boyut yine `size` üzerinden denetlenir.
	"""
	from tradehub_core.utils.security import is_denied_extension

	ad = clean_name(file_name)
	uzanti = extension_of(ad)
	tur = EXTENSIONS.get(uzanti, "")

	if is_denied_extension(uzanti):
		reddet(
			EXT_DENIED,
			_("Bu dosya türü güvenlik nedeniyle kabul edilmiyor: {0}").format(uzanti),
		)

	if media_endpoint and not (tur in MEDIA_KINDS or uzanti in MEDIA_EXTRA_EXTENSIONS):
		reddet(
			EXT_NOT_ALLOWED,
			_("Bu dosya türü kabul edilmiyor: {0}. Görsel, video veya PDF yükleyin.").format(
				uzanti or "?"
			),
		)

	boyut = len(content) if content is not None else int(size or 0)
	sinir = effective_max(tur)
	if boyut > sinir:
		reddet(
			TOO_LARGE,
			_("Dosya çok büyük: {0} MB. Bu tür için sınır {1} MB.").format(
				round(boyut / 1024 / 1024, 1), sinir // (1024 * 1024)
			),
		)

	uyarilar: list[str] = []
	if content is not None:
		if not content:
			reddet(CONTENT_EMPTY, _("Dosya içeriği boş."))

		if is_dangerous(content):
			# Asıl saldırı bu: adı `.jpg`, içi `<svg onload=…>`. Tarayıcı içeriğe
			# göre davranırsa saklı XSS olur.
			reddet(
				CONTENT_DANGEROUS,
				_("Dosyanın içeriği türüyle uyuşmuyor ve güvenli değil."),
			)

		# T-017 — DERİN içerik denetimi. `is_dangerous` yalnız dosyanın BAŞINA
		# bakıyor; ölçüldü: kötücül fixture'ların 8/10'u bu kapıdan geçiyordu
		# (`docs/reports/38-t017-guvenlik-kapisi.md`). Denetimin kendisi
		# frappe'siz bir modülde durur; burası yalnız kodu ve i18n metnini bağlar.
		_derin_denetim(ad, content)

		gercek = sniff(content)
		if gercek and tur and not _uyumlu(uzanti, gercek):
			# Buraya artık yalnız TEHLİKESİZ uyuşmazlık düşüyor — görsel
			# uzantılı tehlikeli uyuşmazlığı `_derin_denetim` yukarıda
			# reddetti. Kalan tek gerçek örnek `.mp4` içinde webm (ölçüm:
			# 4.584 public dosyada 1 adet); tarayıcı MediaRecorder çıktısında
			# yaygın ve iki taraf da hareketsiz kap.
			uyarilar.append(f"uzanti={uzanti} icerik={gercek}")

	return Karar(file_name=ad, kind=tur, bytes=boyut, warnings=uyarilar)


# İçerik denetiminin ürettiği kodun `Kod` karşılığı. Denetim modülü frappe'ye
# bağlı olmadığı için kodu düz dizge döndürür; eşleme burada.
_DERIN_KODLAR: dict[str, Kod] = {
	CONTENT_DANGEROUS.kod: CONTENT_DANGEROUS,
	CONTENT_APPENDED.kod: CONTENT_APPENDED,
	CONTENT_MISMATCH.kod: CONTENT_MISMATCH,
	CONTENT_BOMB.kod: CONTENT_BOMB,
	CONTENT_TRUNCATED.kod: CONTENT_TRUNCATED,
	CONTENT_CONTAINER.kod: CONTENT_CONTAINER,
}

def _derin_mesaj(kod: str) -> str:
	"""Kullanıcıya gösterilecek metin — denetim modülü `_()` çağıramaz (frappe'siz).

	Sözlük fonksiyonun İÇİNDE kuruluyor ki `_()` çıplak dizgeleri sarsın:
	modül düzeyinde bir sözlükte `_()` çağrılamaz (çeviri henüz yüklenmemiş
	olur) ve `_(degisken)` yazmak çeviri çıkarıcısının metni bulamaması
	demektir. Sözlük yalnız RET anında kuruluyor; mutlu yolda hiç çalışmaz.
	"""
	return {
		CONTENT_DANGEROUS.kod: _("Dosyanın içeriği türüyle uyuşmuyor ve güvenli değil."),
		CONTENT_APPENDED.kod: _("Görselin sonuna görsel olmayan içerik eklenmiş."),
		CONTENT_MISMATCH.kod: _("Dosyanın uzantısı içeriğiyle uyuşmuyor."),
		CONTENT_BOMB.kod: _("Görselin çözünürlüğü çok yüksek; işlenemez."),
		CONTENT_TRUNCATED.kod: _("Dosya eksik yüklenmiş; lütfen tekrar deneyin."),
		CONTENT_CONTAINER.kod: _("Belge dosyası bozuk ya da iddia ettiği biçimde değil."),
	}.get(kod, "")


def _derin_denetim(ad: str, content: bytes) -> None:
	"""İçerik denetimi — ilk bulguda reddet.

	Denetim `media/pipeline/security/content_gate.py` içinde; oraya
	taşınmasının sebebi bench'siz test edilebilirlik (bkz. o modülün başlığı).
	İçe aktarma fonksiyon içinde: `upload_policy` `File.before_insert`
	kancasından her kayıtta çağrılıyor ve Pillow'u modül düzeyinde çekmek
	kanca yolunu gereksiz ağırlaştırırdı.
	"""
	from tradehub_core.media.pipeline.security import content_gate

	bulgular = content_gate.inspect(ad, content)
	if not bulgular:
		return
	ilk = bulgular[0]
	kod = _DERIN_KODLAR.get(ilk.kod, CONTENT_DANGEROUS)
	reddet(kod, _derin_mesaj(ilk.kod) or ilk.mesaj)


_UYUM: dict[str, frozenset[str]] = {
	".jpg": frozenset({"jpeg"}),
	".jpeg": frozenset({"jpeg"}),
	".png": frozenset({"png"}),
	".gif": frozenset({"gif"}),
	".bmp": frozenset({"bmp"}),
	".webp": frozenset({"webp"}),
	".tif": frozenset({"tiff"}),
	".tiff": frozenset({"tiff"}),
	".pdf": frozenset({"pdf"}),
	".zip": frozenset({"zip"}),
	".mp4": frozenset({"mp4"}),
	".m4v": frozenset({"mp4"}),
	".mov": frozenset({"mp4"}),
	".webm": frozenset({"webm"}),
}


def _uyumlu(uzanti: str, gercek: str) -> bool:
	beklenen = _UYUM.get(uzanti)
	# AVIF/HEIC imzası tabloda yok; bilinmeyen tür uyuşmazlık sayılmaz.
	return beklenen is None or gercek in beklenen


# ── Slot politikası kapısı (W7 — rapor 78 W5-2) ─────────────────────────
#
# `check()` yukarıda GENEL kuralı uygular: tür, boyut tavanı, tehlikeli içerik.
# Slot politikası (min kısa kenar, min alan, oran, slot-özel biçim listesi) ise
# bugüne kadar yalnız İSTEMCİDE koşuyordu ve istemci kapısı atlatılabilir —
# ölçüldü: 900×900 PNG `upload_media`dan 200 alıyor (panel E2E S1b, rapor 75
# Bulgu 1). Buradaki kapı o boşluğu kapatır.
#
# KURAL KOPYASI YOKTUR: karar `pipeline/policy/engine.py::evaluate`'ten gelir
# (393 vektörle TS paritesi kanıtlı — rapor 77). Bu fonksiyon yalnız künyeyi
# kurar ve engelleyici (`block`) ihlali mevcut ret sözleşmesine (417 +
# `upload_error` kodu) çevirir; `warn`/`auto_fix` REDDETMEZ.


@lru_cache(maxsize=1)
def _policy_engine():
	"""Tek PolicyEngine — kayıt defteri (slots/*.json) süreç başına bir kez okunur.

	Politika dosyaları deploy-zamanı sabittir; `pipeline_bridge._slot_bindings`
	ile aynı önbellek deseni. İçe aktarma fonksiyon içinde: motor yalnız SLOT
	BEYAN EDEN yüklemelerde gerekiyor, kanca yolunu ağırlaştırmamalı
	(`_derin_denetim` ile aynı gerekçe).
	"""
	from tradehub_core.media.pipeline.policy.engine import PolicyEngine

	return PolicyEngine()


def _slot_probe(ad: str, icerik: bytes) -> dict:
	"""Motorun `evaluate()` girdisi — Pillow'a HİÇ dokunmadan, başlıktan.

	Ölçü W5-C'nin `declared_dimensions()`ından gelir (decode yok; bomba benzeri
	girdiyi `check()` içindeki içerik kapısı bu satıra gelmeden zaten reddetti).
	Ölçülemeyen alanlar sözleşme gereği `None`/0 bırakılır ve motor o kuralları
	`SkippedRule` olarak raporlar — kapı ölçemediği şey üzerinden ne reddeder
	ne de sessizce "geçti" sayar.

	`readable=True` bilinçli: motorun `unreadable` kuralı tam-probe girdisi için
	yazıldı; başlık-okuma kapısında okunabilirlik/kesiklik kararı zaten
	`content_gate`'in (T-017) işi ve orada kendi koduyla reddediliyor. Burada
	`False` bırakmak, başlığı ayrıştırılamayan ama içerik kapısından geçmiş her
	biçimi (ör. AVIF/HEIC) slot verildiği anda otomatik reddetmek olurdu.

	BİLİNEN SINIR: EXIF orientation başlıktan OKUNMUYOR (`declared_dimensions`
	ham ölçüyü verir). Kısa kenar ve alan kuralları rotasyondan bağımsızdır;
	yalnız ORAN kuralı 90° döndürülmüş JPEG'lerde depolanan ölçüyle değerlendirilir.
	"""
	from tradehub_core.media.pipeline.core import probe as karar_probe
	from tradehub_core.media.pipeline.image.probe import declared_dimensions
	from tradehub_core.media.pipeline.security.content_gate import HEAD_BYTES

	detected = karar_probe.sniff(icerik)
	w, h = declared_dimensions(icerik[:HEAD_BYTES], detected) or (0, 0)
	if w < 0 or h < 0:
		# Bozuk beyan — "ölçülemedi" say; geometri kuralları SkippedRule olur.
		w = h = 0
	uzanti = extension_of(ad)
	return {
		"filename": ad,
		"extension": uzanti,
		"byte_size": len(icerik),
		"kind": karar_probe.kind_of(detected, uzanti),
		"detected": detected,
		"mime": karar_probe.MIME_BY_KIND.get(detected, ""),
		"width": int(w),
		"height": int(h),
		"readable": True,
	}


def check_slot(slot: str, file_name: str, content: bytes, *, role: str = "") -> None:
	"""Slot politikasını uygula — slot verilmemişse HİÇBİR ŞEY yapmaz.

	`check()`ten SONRA ve dönüşümden (`engine.to_webp`) ÖNCE, ORİJİNAL içerik
	üstünde çağrılır. Engelleyici ihlalde ilk ihlalin kodu (`product_image_
	short_edge_too_small` gibi) mevcut sözleşmeyle döner: `upload_error` +
	mesaj sonunda `[kod]` + HTTP 417 (`UploadRejected`).
	"""
	anahtar = (slot or "").strip().lower()
	if not anahtar:
		return

	motor = _policy_engine()
	if anahtar not in motor.registry:
		reddet(SLOT_UNKNOWN, _("Bilinmeyen yükleme slotu: {0}").format(anahtar))

	karar = motor.evaluate(anahtar, _slot_probe(file_name, content or b""), role=role)
	engeller = karar.blocking()
	if not engeller:
		return

	ilk = engeller[0]
	mesaj = (ilk.message or {}).get("tr") or (ilk.message or {}).get("en") or ilk.rule
	# Motorun kodu politika önekini zaten taşıyor (`error_code_prefix`);
	# `Kod` sarmalayıcı yalnız mevcut ret biçimini (upload_error + [kod]) kurar.
	reddet(Kod(ilk.code, False), mesaj)


def limits() -> dict:
	"""İstemcinin aynı kuralları uygulayabilmesi için sınırlar.

	İstemci bu değerleri sunucudan alır, kendi içine YAZMAZ. İki tarafa ayrı
	sabit koymak, biri değişince sessizce ayrışan iki kural demekti: kullanıcı
	ekranda kabul edilen dosyanın sunucuda reddedildiğini görürdü.
	"""
	from tradehub_core.utils.security import _DENIED_EXTENSIONS

	return {
		"extensions": sorted(EXTENSIONS),
		"media_extensions": sorted(
			e for e, t in EXTENSIONS.items() if t in MEDIA_KINDS or e in MEDIA_EXTRA_EXTENSIONS
		),
		# Yasak liste de gönderiliyor. Gönderilmeseydi istemci `.svg` için
		# "kabul edilmiyor" derken sunucu "güvenlik nedeniyle kabul edilmiyor"
		# diyordu: aynı dosya, iki farklı sebep. Ayrışma ölçümle yakalandı
		# (3000 girdide 43 ayrışma) ve kaynağı buydu.
		"denied_extensions": sorted(_DENIED_EXTENSIONS),
		"kinds": {e: t for e, t in EXTENSIONS.items()},
		# GERÇEKLEŞEBİLİR sınırlar: Frappe'nin kendi tavanı bizimkinden düşük
		# olabiliyor ve bizden önce reddediyor. İstemciye ulaşılamayan bir sayı
		# vermek, dosya yüklendikten sonra hayal kırıklığı demekti.
		"max_bytes": {t: effective_max(t) for t in MAX_BYTES},
		"max_bytes_unknown": min(MAX_BYTES_UNKNOWN, platform_limit()),
		"policy_max_bytes": dict(MAX_BYTES),
		"platform_limit": platform_limit(),
		"single_shot_limit": SINGLE_SHOT_LIMIT,
		"max_name": MAX_NAME,
		"retryable_codes": sorted(RETRYABLE),
	}

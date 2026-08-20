"""T-133 — korelasyon ID'li yapılandırılmış JSON log + PII maskeleme.

SORUN — bugünkü log'lar bir isteği takip ETMİYOR
================================================
Üretimdeki medya hattı üç ayrı yere yazıyor ve üçü de birbirini tanımıyor:

    frappe.log_error(title=..., message=traceback)   media/access_level.py, transcode.py, av.py
    frappe.logger("...").info("serbest metin")        çeşitli
    Access Decision Log (ADL)                         media/audit.py `log_media_event`

Sonuç: bir yükleme reddedildiğinde "hangi istek", "hangi iş", "kaçıncı deneme"
sorularının cevabı üç ayrı yerde ve BAĞLANAMIYOR. Yükleme → AV taraması →
optimize → türev zinciri dört ayrı sürece dağılıyor; ortak bir anahtar yok.

ÇÖZÜM — tek anahtar, tek biçim
==============================
`correlation_id` istek/iş başına bir kez üretilir, `contextvars` ile taşınır ve
HER log satırına düşer. Kuyruğa iş verilirken anahtar iş yüküne konur
(`correlation_scope(cid)` ile worker'da geri kurulur), böylece zincir süreç
sınırını geçer.

Biçim: satır başına bir JSON nesnesi (JSON Lines). Anahtar sırası
DETERMİNİSTİKTİR — grep/jq ile okunabilirlik ve altın-dosya testi için.

MASKELEME — `media/audit.py` ile AYNI sözleşme
==============================================
`audit.fingerprint()` sha256'nın ilk 12 hane'sini kullanıyor ve maskeli değeri
`masked:<fp>` biçiminde yazıyor (`audit.py:132-138`, `:183`). Bu modül AYNI
biçimi üretir; farklı bir maskeleme, aynı dosyanın ADL'de ve log'da farklı
kimlikle görünmesi demekti — ikisini eşleştirmek imkânsız olurdu.

Maskeleme İKİ yoldan tetiklenir, çünkü tek yol yetmiyor:
  1. **Anahtar adı** (`file_url`, `email`, `path`, …) — yazan kişi ne yazdığını
     biliyorsa doğru anahtarı kullanır.
  2. **Değer deseni** (e-posta, `/private/files/…`, 11 haneli TCKN, IBAN) —
     yazan kişi `detail="hata: /private/files/ab/kimlik.jpg"` diye serbest
     metin yazdığında (1) devreye girmez. Bu ikinci tarama olmadan maskeleme
     iyi niyete bağlı kalırdı.

`import frappe` YOKTUR. Frappe'nin logger'ı kullanılabilir: `configure()` bu
modülün `JsonFormatter`'ını herhangi bir `logging.Handler`'a takar.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import os
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional, Tuple

#: Korelasyon anahtarı — istek/iş başına bir kez üretilir, süreç sınırını
#: iş yükünde taşınarak geçer.
_KORELASYON: contextvars.ContextVar = contextvars.ContextVar("media_correlation_id", default="")
#: Her satıra eklenecek yapışkan alanlar (`slot`, `job`, `attempt`, …).
#: Varsayılan `None` — `{}` DEĞİL: değiştirilebilir bir varsayılan tüm
#: bağlamlarca PAYLAŞILIR ve bir işin alanları diğerine sızabilir.
_BAGLAM: contextvars.ContextVar = contextvars.ContextVar("media_log_context", default=None)

LOGGER_ADI: str = "media_engine"

#: `masked:` öneki `media/audit.py:183` ile BİREBİR aynı — iki kayıt aynı
#: dosyayı aynı kimlikle göstersin.
MASK_ONEKI: str = "masked:"
FINGERPRINT_UZUNLUK: int = 12


def fingerprint(deger: Any) -> str:
	"""Kararlı, geri döndürülemez kimlik — `media/audit.py:132-138`'in aynısı.

	Aynı dosya her seferinde aynı parmak izini verir (operatör "bu dosyaya 5
	kez denendi" diyebilir) ama parmak izinden dosyaya dönülemez.
	"""
	return hashlib.sha256(str(deger or "").encode("utf-8")).hexdigest()[:FINGERPRINT_UZUNLUK]


def mask(deger: Any) -> str:
	"""`masked:<fp>` — boş değer maskelenmez (maskelenmiş boşluk bilgi taşımaz)."""
	metin = str(deger or "")
	return f"{MASK_ONEKI}{fingerprint(metin)}" if metin else ""


# ── Hassas alan tanımı ──────────────────────────────────────────────────
#
# Anahtar adı listesi DAR tutuldu: her alanı maskelemek log'u okunamaz yapar.
# Buraya giren alanlar ya doğrudan PII taşır ya da bir PII kaydına götürür.

HASSAS_ANAHTARLAR: frozenset = frozenset(
	{
		"file_url",
		"file_name",
		"file_path",
		"path",
		"src",
		"dst",
		"old_url",
		"new_url",
		"url",
		"email",
		"user",
		"owner",
		"modified_by",
		"phone",
		"tckn",
		"identity_document",
		"iban",
		"attached_to_name",
		"docname",
		"ip",
		"remote_addr",
	}
)

#: Maskelenmesi GEREKMEYEN, kasıtlı olarak açık bırakılanlar. `doctype` PII
#: değildir ve olmadan hiçbir olay yorumlanamaz; `slot` politika anahtarıdır.
ACIK_ANAHTARLAR: frozenset = frozenset(
	{"doctype", "attached_to_doctype", "slot", "kind", "reason", "code", "action", "job", "state"}
)

_EPOSTA = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_DOSYA_YOLU = re.compile(r"/(?:private/)?files/[^\s\"',;)]+")
#: 11 hane TCKN — kelime sınırıyla; sipariş numarası gibi 11 haneli olmayan
#: kimlikler etkilenmesin diye tam uzunluk şartı var.
_TCKN = re.compile(r"(?<!\d)\d{11}(?!\d)")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
#: Mutlak disk yolu (sunucu topolojisini sızdırır, PII değil ama bilgi ifşası).
_MUTLAK_YOL = re.compile(r"(?:/home|/var|/opt|/Users)/[^\s\"',;)]+")

_DESENLER: Tuple[Tuple[re.Pattern, str], ...] = (
	(_EPOSTA, "email"),
	(_DOSYA_YOLU, "file"),
	(_IBAN, "iban"),
	(_TCKN, "tckn"),
	(_MUTLAK_YOL, "path"),
)

#: Serbest metinde bir değeri kırpma tavanı. Log satırının kendisi bir DoS
#: yüzeyi olabilir: 40 MB'lık bir traceback disk doldurur.
MAX_DEGER_UZUNLUK: int = 2000
MAX_ALAN_SAYISI: int = 64


def maskele_metin(metin: str) -> str:
	"""Serbest metindeki PII desenlerini `masked:<fp>` ile değiştirir.

	Desenin YAKALADIĞI parça maskelenir, cümlenin geri kalanı okunur kalır:
	`"kopyalama hatasi: /private/files/ab/x.jpg"` →
	`"kopyalama hatasi: masked:9f2c…"`. Satırı tümden atmak, hatayı
	anlaşılmaz yapardı.
	"""
	if not metin:
		return metin
	sonuc = metin
	for desen, _ad in _DESENLER:
		sonuc = desen.sub(lambda m: mask(m.group(0)), sonuc)
	return sonuc


def maskele_deger(anahtar: str, deger: Any) -> Any:
	"""Tek alanı maskele — anahtar adına VE değer desenine göre."""
	ad = (anahtar or "").lower()
	if ad in ACIK_ANAHTARLAR:
		return _kirp(deger)
	if ad in HASSAS_ANAHTARLAR:
		return mask(deger) if deger not in (None, "", 0) else deger
	if isinstance(deger, str):
		return _kirp(maskele_metin(deger))
	if isinstance(deger, dict):
		return {k: maskele_deger(k, v) for k, v in list(deger.items())[:MAX_ALAN_SAYISI]}
	if isinstance(deger, (list, tuple)):
		return [maskele_deger(anahtar, v) for v in list(deger)[:MAX_ALAN_SAYISI]]
	return _kirp(deger)


def _kirp(deger: Any) -> Any:
	if isinstance(deger, str) and len(deger) > MAX_DEGER_UZUNLUK:
		return deger[:MAX_DEGER_UZUNLUK] + f"…(+{len(deger) - MAX_DEGER_UZUNLUK})"
	return deger


# ── Korelasyon ──────────────────────────────────────────────────────────


def new_correlation_id() -> str:
	"""Yeni korelasyon anahtarı üretir ve BAĞLAMA yazar.

	`uuid4().hex[:16]`: 64 bit. Çarpışma olasılığı günlük 1 milyon istekte
	ihmal edilebilir, tam UUID ise her satıra 36 karakter ekliyordu.
	"""
	cid = uuid.uuid4().hex[:16]
	_KORELASYON.set(cid)
	return cid


def get_correlation_id() -> str:
	"""Geçerli anahtar; yoksa boş (otomatik ÜRETMEZ — bkz. `ensure_...`)."""
	return _KORELASYON.get() or ""


def ensure_correlation_id() -> str:
	"""Anahtar varsa onu, yoksa yenisini döndürür."""
	return get_correlation_id() or new_correlation_id()


def set_correlation_id(cid: str) -> str:
	"""Dışarıdan gelen anahtarı kurar — kuyruk worker'ı bunu kullanır.

	Değer TEMİZLENİR: iş yükünden gelen bir string doğrudan log'a yazılacak;
	içine yeni satır koyan biri sahte log satırı üretebilirdi (log injection).
	"""
	temiz = re.sub(r"[^A-Za-z0-9_.:-]", "", str(cid or ""))[:64]
	_KORELASYON.set(temiz)
	return temiz


def bind(**alanlar: Any) -> Dict[str, Any]:
	"""Bağlama yapışkan alan ekler; ÖNCEKİ bağlamı döndürür (geri almak için)."""
	onceki = dict(_BAGLAM.get() or {})
	yeni = dict(onceki)
	yeni.update(alanlar)
	_BAGLAM.set(yeni)
	return onceki


def get_context() -> Dict[str, Any]:
	return dict(_BAGLAM.get() or {})


def clear_context() -> None:
	_BAGLAM.set({})


@contextmanager
def correlation_scope(cid: Optional[str] = None, **alanlar: Any) -> Iterator[str]:
	"""Bir işin ömrü boyunca anahtarı ve bağlamı tutar, çıkışta GERİ ALIR.

	    with correlation_scope(is_yuku.get("correlation_id"), job="transcode"):
	        ...

	Çıkışta eski değerlere dönülür — worker aynı süreçte sıradaki işi alırken
	önceki işin anahtarını taşımamalı (kirli bağlam en sinsi log hatasıdır).
	"""
	onceki_cid = _KORELASYON.get()
	onceki_baglam = dict(_BAGLAM.get() or {})
	yeni_cid = set_correlation_id(cid) if cid else new_correlation_id()
	if alanlar:
		bind(**alanlar)
	try:
		yield yeni_cid
	finally:
		_KORELASYON.set(onceki_cid)
		_BAGLAM.set(onceki_baglam)


# ── JSON biçimlendirici ─────────────────────────────────────────────────

#: Alan sırası. Sabit sıra bir süs değil: `head -1 log | jq -c` çıktısının
#: kararlı olması ve altın-dosya testi bunu gerektiriyor.
SABIT_SIRA: Tuple[str, ...] = ("ts", "level", "logger", "event", "correlation_id", "message")

#: `logging.LogRecord`'un kendi alanları — `extra` ile gelen kullanıcı
#: alanlarından ayırmak için.
_RECORD_ALANLARI: frozenset = frozenset(
	{
		"args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
		"levelname", "levelno", "lineno", "module", "msecs", "msg", "name", "pathname",
		"process", "processName", "relativeCreated", "stack_info", "thread", "threadName",
		"taskName", "getMessage", "event",
	}
)


class JsonFormatter(logging.Formatter):
	"""`logging.LogRecord` → tek satır JSON.

	`record.__dict__` içindeki standart olmayan her anahtar (yani `extra=` ile
	gelen her şey) alan olarak yazılır ve maskelemeden geçer. `exc_info` varsa
	`error.type` / `error.message` / `error.stack` alanları eklenir; stack de
	maskelenir çünkü traceback satırları mutlak dosya yolu taşır.
	"""

	def __init__(self, *, service: str = "media_engine", maskele: bool = True) -> None:
		super().__init__()
		self.service = service
		self.maskele = maskele

	def format(self, record: logging.LogRecord) -> str:  # noqa: A003 - logging API
		veri: Dict[str, Any] = {
			"ts": _iso(record.created),
			"level": record.levelname,
			"logger": record.name,
			"event": str(getattr(record, "event", "") or record.getMessage())[:200],
			"correlation_id": get_correlation_id(),
		}
		ham_mesaj = record.getMessage()
		if ham_mesaj and ham_mesaj != veri["event"]:
			# `event` sabit anahtar, `message` serbest cümle. İkisi AYNIYSA
			# `message` yazılmaz — her satırda aynı metni iki kez taşımak
			# log hacmini gereksiz büyütür.
			veri["message"] = ham_mesaj

		alanlar: Dict[str, Any] = dict(get_context())
		for anahtar, deger in record.__dict__.items():
			if anahtar in _RECORD_ALANLARI or anahtar.startswith("_"):
				continue
			alanlar[anahtar] = deger

		if record.exc_info:
			tur, deger_, _iz = record.exc_info
			alanlar["error_type"] = getattr(tur, "__name__", str(tur))
			alanlar["error_message"] = str(deger_)
			alanlar["error_stack"] = self.formatException(record.exc_info)

		for anahtar in sorted(alanlar)[:MAX_ALAN_SAYISI]:
			if anahtar in veri:
				# Sabit alanlar ezilemez: `extra={"level": "DEBUG"}` yazan biri
				# log seviyesini yalanlayabilirdi.
				anahtar_yaz = f"field_{anahtar}"
			else:
				anahtar_yaz = anahtar
			deger = alanlar[anahtar]
			veri[anahtar_yaz] = maskele_deger(anahtar, deger) if self.maskele else _kirp(deger)

		veri["service"] = self.service
		veri["pid"] = os.getpid()

		sirali = {a: veri[a] for a in SABIT_SIRA if a in veri}
		for a in sorted(veri):
			if a not in sirali:
				sirali[a] = veri[a]
		return json.dumps(sirali, ensure_ascii=False, default=_json_yedek)


def _json_yedek(o: Any) -> str:
	"""JSON'a çevrilemeyen değer — repr'i kırpılarak yazılır, satır DÜŞMEZ.

	`default=` olmadan tek bir `datetime` bütün log satırını `TypeError` ile
	düşürürdü; log yazamamak, log'un koruduğu şeyden daha pahalıdır.
	"""
	try:
		return _kirp(repr(o))
	except Exception:
		return "<unrepr>"


def _iso(zaman: float) -> str:
	"""UTC ISO-8601, milisaniye çözünürlüklü. `Z` soneki açık."""
	yapı = time.gmtime(zaman)
	ms = int((zaman - int(zaman)) * 1000)
	return f"{time.strftime('%Y-%m-%dT%H:%M:%S', yapı)}.{ms:03d}Z"


# ── Kurulum ve kullanım ─────────────────────────────────────────────────


@dataclass
class LoggerAyari:
	"""`configure()` sonucunun künyesi — testte ve sağlık ucunda okunur."""

	name: str
	level: int
	handlers: int
	masking: bool


def configure(
	*,
	name: str = LOGGER_ADI,
	level: int = logging.INFO,
	stream: Any = None,
	maskele: bool = True,
	service: str = "media_engine",
	replace: bool = False,
) -> LoggerAyari:
	"""Logger'ı JSON biçimlendiriciyle kurar. Tekrar çağırmak GÜVENLİDİR.

	`replace=False` (varsayılan) mevcut handler'ları KORUR ve yalnız bu
	modülün handler'ı yoksa ekler: Frappe kendi handler'larını takıyor,
	onları silmek uygulamanın log'unu kesmek olurdu.

	`propagate=False`: kök logger'a çıkmaz, yoksa aynı satır iki kez yazılır.
	"""
	logger = logging.getLogger(name)
	logger.setLevel(level)
	if replace:
		for h in list(logger.handlers):
			logger.removeHandler(h)
	if not any(getattr(h, "_media_engine", False) for h in logger.handlers):
		handler = logging.StreamHandler(stream) if stream is not None else logging.StreamHandler()
		handler.setFormatter(JsonFormatter(service=service, maskele=maskele))
		handler._media_engine = True  # type: ignore[attr-defined]
		logger.addHandler(handler)
	logger.propagate = False
	return LoggerAyari(name=name, level=level, handlers=len(logger.handlers), masking=maskele)


def get_logger(name: str = LOGGER_ADI) -> logging.Logger:
	"""Adlandırılmış logger. `configure()` çağrılmadıysa handler EKLEMEZ.

	Sessiz kurulum bilinçli olarak yapılmıyor: bir kütüphanenin import
	edilir edilmez stderr'e yazmaya başlaması, gömüldüğü uygulamanın log
	yapılandırmasını ele geçirmesidir.
	"""
	return logging.getLogger(name)


def log_event(
	event: str,
	*,
	level: int = logging.INFO,
	logger: Optional[logging.Logger] = None,
	exc_info: Any = None,
	**alanlar: Any,
) -> None:
	"""Tek yapılandırılmış olay yaz.

	    log_event("upload.rejected", slot="product.image",
	              reason="upload_too_large", bytes=31_457_280)

	`event` NOKTA AYRIMLI ve SABİT olmalı (`<alan>.<eylem>`): metrik adı gibi,
	uyarı kuralı ve gösterge paneli buna bağlanır. Serbest cümle `message`
	alanına yazılır.

	**İstisna fırlatmaz** — log yazamamak çağıranı düşürmemeli
	(`media/audit.py` `log_media_event`'in best-effort davranışıyla aynı).
	"""
	lg = logger or get_logger()
	try:
		lg.log(level, event, extra={"event": event, **alanlar}, exc_info=exc_info)
	except Exception:
		pass


def is_event(event: str, **alanlar: Any) -> None:
	"""Kısayol: kuyruk işi olayları için `job` bağlamıyla `log_event`."""
	log_event(event, **alanlar)


def job_payload(**ek: Any) -> Dict[str, Any]:
	"""Kuyruğa verilecek iş yüküne konacak korelasyon parçası.

	    frappe.enqueue(..., **logging.job_payload(job="transcode"))

	Worker tarafında `correlation_scope(payload["correlation_id"])` ile zincir
	geri kurulur. Anahtar İŞ YÜKÜNDE taşınır çünkü `contextvars` süreç
	sınırını geçmez — bu, zincirin kopabileceği tek yerdir ve bilinçli olarak
	tek bir fonksiyonda toplandı.
	"""
	return {"correlation_id": ensure_correlation_id(), **ek}


__all__ = [
	"ACIK_ANAHTARLAR",
	"FINGERPRINT_UZUNLUK",
	"HASSAS_ANAHTARLAR",
	"LOGGER_ADI",
	"MASK_ONEKI",
	"MAX_DEGER_UZUNLUK",
	"SABIT_SIRA",
	"JsonFormatter",
	"LoggerAyari",
	"bind",
	"clear_context",
	"configure",
	"correlation_scope",
	"ensure_correlation_id",
	"fingerprint",
	"get_context",
	"get_correlation_id",
	"get_logger",
	"job_payload",
	"log_event",
	"mask",
	"maskele_deger",
	"maskele_metin",
	"new_correlation_id",
	"set_correlation_id",
]

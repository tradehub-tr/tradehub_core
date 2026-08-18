"""Faz 8 — API zarfı: yanıt biçimi, HTTP eşlemesi, ETag ve yetki kapısı.

NEDEN AYRI BİR ZARF
-------------------
`media_engine` bir **kütüphanedir**, Frappe app'i değil. Bu paketteki hiçbir
fonksiyon `@frappe.whitelist()` taşımaz ve hiçbiri `frappe.local.response`'a
yazmaz; hepsi bir `ApiResponse` **döndürür**. Frappe'ye bağlama noktası tek bir
ince katmandır ve `docs/api/README.md` §3'te anlatılır.

Bunun bedeli bir zarf tanımlamaktır; karşılığı, uç noktaların site/bench/DB
olmadan test edilebilmesidir. `tests/test_api_contracts.py` bu sayede
konteyner dışında da koşar.

HATA SÖZLEŞMESİ TEK KAYNAKTAN GELİR
-----------------------------------
Kodlu ret sözleşmesi bu dosyada YENİDEN TANIMLANMAZ. Kaynak
`tradehub_core/media/pipeline/contracts/errors.py` (o da `tradehub_core/media/upload_policy.py`
ile uyumlu). Bu modülün eklediği tek şey, o hiyerarşinin **HTTP durum kodu**
karşılığıdır — kütüphane katmanı HTTP'yi bilmez, bilmemelidir de.

    PolicyViolation   → 422   (dosya geçerli ama kurala uymuyor)
    PolicyNotFound    → 404   (bilinmeyen slot)
    ObjectNotFound    → 404
    StorageConflict   → 409
    OversizedImage    → 413
    UnsupportedFormat → 415
    DecodeError       → 400
    ProbeUnavailable  → 503   (retryable)

`retryable` bayrağı `to_response()` içinde zaten var ve HTTP durumundan BAĞIMSIZ
taşınır: 503 alan istemci yeniden dener, 422 alan denemez — ama karar metne
değil bayrağa bakılarak verilir (FR-060).

ETag NEDEN BURADA
-----------------
Teslim manifestosu (T-083) ve politika okumaları saf fonksiyonlardır: aynı girdi
her zaman aynı çıktıyı verir. Bu, içerik-adresli bir ETag'i mümkün kılar —
gövdenin kanonik JSON'unun sha256'sı. Kanonikleştirme `core/dedup.py`'deki
`canonical_json` ile yapılır; ikinci bir kanonikleştirme yazmak, iki yerin
sessizce ayrışması demek olurdu (NFR-046).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from tradehub_core.media.pipeline.contracts.errors import (
	DecodeError,
	DeliveryError,
	EncodeError,
	ImageError,
	MediaEngineError,
	NoProfileAvailable,
	ObjectNotFound,
	OversizedImage,
	PolicyError,
	PolicyNotFound,
	PolicyViolation,
	ProbeUnavailable,
	StorageConflict,
	StorageError,
	TranscodeFailed,
	UnsupportedFormat,
	VideoError,
	kod_uret,
)
from tradehub_core.media.pipeline.core.dedup import canonical_json

# ── HTTP durum sabitleri ────────────────────────────────────────────────

HTTP_OK: int = 200
HTTP_CREATED: int = 201
HTTP_ACCEPTED: int = 202
HTTP_NO_CONTENT: int = 204
HTTP_NOT_MODIFIED: int = 304
HTTP_BAD_REQUEST: int = 400
HTTP_UNAUTHORIZED: int = 401
HTTP_FORBIDDEN: int = 403
HTTP_NOT_FOUND: int = 404
HTTP_CONFLICT: int = 409
HTTP_PRECONDITION_FAILED: int = 412
HTTP_PAYLOAD_TOO_LARGE: int = 413
HTTP_UNSUPPORTED_MEDIA_TYPE: int = 415
HTTP_UNPROCESSABLE: int = 422
HTTP_TOO_MANY_REQUESTS: int = 429
HTTP_INTERNAL_ERROR: int = 500
HTTP_UNAVAILABLE: int = 503

#: `media_engine` dışına çıkan tüm hata gövdelerinin kod öneki (slot bağlamı
#: olmayan hatalar için). `contracts/errors.VARSAYILAN_PREFIX` ile aynı.
API_PREFIX: str = "media"


# ── API'ye özgü hatalar ─────────────────────────────────────────────────
#
# Bunlar `MediaEngineError` türevidir; yani `to_response()` biçimi ve
# `retryable` sözleşmesi aynı kalır. Ayrı bir hiyerarşi kurmak, istemcinin iki
# farklı hata biçimi ayrıştırması demek olurdu.


class ApiError(MediaEngineError):
	"""Uç katmanının kendi ürettiği hata. `http_status` sınıfta sabittir."""

	http_status: int = HTTP_INTERNAL_ERROR
	varsayilan_sebep = "api_error"


class BadRequest(ApiError):
	"""İstek gövdesi/parametresi geçersiz — dosyayla ilgisi yok."""

	http_status = HTTP_BAD_REQUEST
	varsayilan_sebep = "bad_request"


class Unauthorized(ApiError):
	"""Kimlik yok. Oturum açmak sonucu değiştirir → bu bir 401'dir, 403 değil."""

	http_status = HTTP_UNAUTHORIZED
	varsayilan_sebep = "unauthorized"


class Forbidden(ApiError):
	"""Kimlik var, yetki yok."""

	http_status = HTTP_FORBIDDEN
	varsayilan_sebep = "forbidden"


class NotFound(ApiError):
	"""Kaynak yok — ya da **görünmemesi gerekiyor**.

	Yayınlanmamış varlık için bilinçli olarak 403 değil 404 döndürülür
	(T-083). 403, kaynağın var olduğunu doğrular; yayınlanmamış bir görselin
	varlığını sızdırmak, yayın takvimini sızdırmaktır.
	"""

	http_status = HTTP_NOT_FOUND
	varsayilan_sebep = "not_found"


class Conflict(ApiError):
	"""Kaynağın bugünkü hâliyle çelişen istek."""

	http_status = HTTP_CONFLICT
	varsayilan_sebep = "conflict"


class PreconditionFailed(ApiError):
	"""`If-Match` tutmadı — araya başka bir yazma girdi (iyimser kilit)."""

	http_status = HTTP_PRECONDITION_FAILED
	varsayilan_sebep = "precondition_failed"


class PayloadTooLarge(ApiError):
	"""İlan edilen boyut slot tavanını aşıyor. Bayt beklenmeden reddedilir."""

	http_status = HTTP_PAYLOAD_TOO_LARGE
	varsayilan_sebep = "too_large"


class TooManyRequests(ApiError):
	"""Hız sınırı. Geçicidir → `retryable=True`."""

	http_status = HTTP_TOO_MANY_REQUESTS
	varsayilan_sebep = "rate_limited"
	varsayilan_retryable = True


class ServiceUnavailable(ApiError):
	"""Bağımlılık yok (ffprobe, depo, Pillow). Geçicidir."""

	http_status = HTTP_UNAVAILABLE
	varsayilan_sebep = "unavailable"
	varsayilan_retryable = True


#: `contracts.errors` sınıfları → HTTP durumu. Sıra ÖNEMSİZ; arama MRO ile
#: yapılır, yani en özgül sınıf kazanır (`ObjectNotFound` → 404, ata sınıfı
#: `StorageError` → 503).
STATUS_BY_ERROR: Dict[type, int] = {
	PolicyViolation: HTTP_UNPROCESSABLE,
	PolicyNotFound: HTTP_NOT_FOUND,
	PolicyError: HTTP_INTERNAL_ERROR,
	ObjectNotFound: HTTP_NOT_FOUND,
	StorageConflict: HTTP_CONFLICT,
	StorageError: HTTP_UNAVAILABLE,
	OversizedImage: HTTP_PAYLOAD_TOO_LARGE,
	UnsupportedFormat: HTTP_UNSUPPORTED_MEDIA_TYPE,
	DecodeError: HTTP_BAD_REQUEST,
	EncodeError: HTTP_INTERNAL_ERROR,
	ImageError: HTTP_BAD_REQUEST,
	ProbeUnavailable: HTTP_UNAVAILABLE,
	TranscodeFailed: HTTP_INTERNAL_ERROR,
	VideoError: HTTP_INTERNAL_ERROR,
	NoProfileAvailable: HTTP_NOT_FOUND,
	DeliveryError: HTTP_INTERNAL_ERROR,
	MediaEngineError: HTTP_INTERNAL_ERROR,
}


def http_status_for(exc: BaseException) -> int:
	"""Hata → HTTP durumu. Bilinmeyen istisna 500'dür, sessizce 200 DEĞİL."""
	if isinstance(exc, ApiError):
		return exc.http_status
	for tip in type(exc).__mro__:
		if tip in STATUS_BY_ERROR:
			return STATUS_BY_ERROR[tip]
	return HTTP_INTERNAL_ERROR


# ── Yanıt ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ApiResponse:
	"""Bir uç noktanın dönüşü. HTTP'ye çeviren katman `api/` DIŞINDADIR.

	`body=None` gövdesiz yanıttır (204/304). `headers` anahtarları HTTP
	yazımıyla aynıdır (`ETag`, `Cache-Control`) — çeviri katmanı olmasın diye.
	"""

	status: int = HTTP_OK
	body: Optional[Dict[str, Any]] = None
	headers: Dict[str, str] = field(default_factory=dict)

	@property
	def ok(self) -> bool:
		return 200 <= self.status < 300

	@property
	def error_code(self) -> str:
		return str((self.body or {}).get("error_code", "")) if not self.ok else ""

	def with_header(self, name: str, value: str) -> ApiResponse:
		yeni = dict(self.headers)
		yeni[name] = value
		return ApiResponse(status=self.status, body=self.body, headers=yeni)

	def to_dict(self) -> Dict[str, Any]:
		return {"status": self.status, "headers": dict(self.headers), "body": self.body}


def ok(data: Optional[Mapping[str, Any]] = None, *, status: int = HTTP_OK, **headers: str) -> ApiResponse:
	"""Başarılı yanıt. `headers` anahtarları alt tire ile yazılır ve çevrilir
	(`cache_control` → `Cache-Control`)."""
	return ApiResponse(status=status, body=dict(data or {}), headers=_headers(headers))


def created(data: Mapping[str, Any], *, location: str = "", **headers: str) -> ApiResponse:
	h = _headers(headers)
	if location:
		h["Location"] = location
	return ApiResponse(status=HTTP_CREATED, body=dict(data), headers=h)


def accepted(data: Mapping[str, Any], **headers: str) -> ApiResponse:
	return ApiResponse(status=HTTP_ACCEPTED, body=dict(data), headers=_headers(headers))


def no_content(**headers: str) -> ApiResponse:
	"""204 — gövde YOK. `abort` ve silme uçları bunu döndürür."""
	return ApiResponse(status=HTTP_NO_CONTENT, body=None, headers=_headers(headers))


def not_modified(etag: str, **headers: str) -> ApiResponse:
	"""304 — gövde YOK ama ETag TAŞINIR (RFC 9110 §15.4.5)."""
	h = _headers(headers)
	h["ETag"] = etag
	return ApiResponse(status=HTTP_NOT_MODIFIED, body=None, headers=h)


def error_response(exc: BaseException) -> ApiResponse:
	"""Hata → yanıt. `MediaEngineError` değilse kod uydurulmaz, `media_internal`
	kullanılır ve mesaj DIŞARI SIZDIRILMAZ (NFR-035: yol/e-posta maskeleme)."""
	if isinstance(exc, MediaEngineError):
		return ApiResponse(status=http_status_for(exc), body=exc.to_response())
	return ApiResponse(
		status=HTTP_INTERNAL_ERROR,
		body={
			"error_code": kod_uret(API_PREFIX, "internal"),
			"retryable": True,
			"message": "İşlem tamamlanamadı.",
			"details": {"type": type(exc).__name__},
		},
	)


def call(fn: Callable[..., ApiResponse], *args: Any, **kwargs: Any) -> ApiResponse:
	"""Uç noktayı çağır, `MediaEngineError`'ı yanıta çevir.

	Bağlama katmanının tek kullanması gereken kapı budur: istisna HTTP'ye
	buradan çıkar, her uç noktada ayrı `try/except` yazılmaz.
	"""
	try:
		return fn(*args, **kwargs)
	except MediaEngineError as exc:
		return error_response(exc)


#: `capitalize()` ile doğru yazılamayan başlıklar. `ETag` bunların başında
#: geliyor: HTTP başlık adları büyük/küçük harfe duyarsızdır ama istemci kodu
#: (ve testler) sözlükten ADIYLA okur; `Etag` yazmak sessiz bir uyumsuzluk
#: üretirdi.
_HEADER_CASE: Dict[str, str] = {
	"etag": "ETag",
	"content_type": "Content-Type",
	"content_length": "Content-Length",
	"www_authenticate": "WWW-Authenticate",
	"retry_after": "Retry-After",
}


def _headers(raw: Mapping[str, str]) -> Dict[str, str]:
	"""`cache_control` → `Cache-Control`. Zaten doğru yazılmışsa dokunulmaz."""
	cikti: Dict[str, str] = {}
	for k, v in raw.items():
		if v is None:
			continue
		if "-" in k:
			ad = k
		elif k.lower() in _HEADER_CASE:
			ad = _HEADER_CASE[k.lower()]
		else:
			ad = "-".join(p.capitalize() for p in k.split("_"))
		cikti[ad] = str(v)
	return cikti


# ── ETag ────────────────────────────────────────────────────────────────

#: Manifest yanıtları için önbellek başlığı. Manifest içerik-adresli
#: türevlere işaret eder; gövdenin kendisi kısa ömürlüdür (varlık
#: yayından kaldırılabilir), bu yüzden `must-revalidate`.
CACHE_MANIFEST: str = "public, max-age=60, must-revalidate"

#: İmzalı URL yanıtı ASLA önbelleğe alınmaz — paylaşılan bir önbellek onu
#: başka kullanıcıya servis ederdi.
CACHE_NEVER: str = "private, no-store"


def etag_for(payload: Any) -> str:
	"""Gövdenin içerik-adresli, güçlü ETag'i.

	Kanonik JSON kullanılır: anahtar sırası ya da boşluk değişince ETag
	DEĞİŞMEZ. Aksi hâlde aynı manifest iki farklı ETag alır ve 304 hiç
	çalışmaz — önbellek sessizce ölü olurdu.
	"""
	ham = canonical_json(payload).encode("utf-8")
	return '"' + hashlib.sha256(ham).hexdigest()[:32] + '"'


def etag_matches(etag: str, header_value: str) -> bool:
	"""`If-None-Match` / `If-Match` karşılaştırması.

	`*` her şeye uyar. `W/` öneki kırpılır: zayıf karşılaştırma
	(`If-None-Match` için RFC 9110 §13.1.2'nin istediği) tam olarak budur.
	"""
	if not header_value:
		return False
	beklenen = _strip_weak(etag)
	for parca in header_value.split(","):
		aday = parca.strip()
		if aday == "*":
			return True
		if _strip_weak(aday) == beklenen:
			return True
	return False


def _strip_weak(value: str) -> str:
	v = (value or "").strip()
	if v.startswith("W/"):
		v = v[2:]
	return v


def conditional_get(body: Mapping[str, Any], if_none_match: str, **headers: str) -> ApiResponse:
	"""ETag hesapla; `If-None-Match` tutuyorsa 304, tutmuyorsa 200 döndür.

	Tek yerde durmasının sebebi: ETag'i üretip karşılaştırmayı unutmak sessiz
	bir performans regresyonudur — hata vermez, yalnız her istek gövdeyi
	yeniden indirir.
	"""
	etag = etag_for(body)
	if etag_matches(etag, if_none_match):
		return not_modified(etag, **headers)
	return ok(body, etag=etag, **headers)


# ── Kimlik ve yetki ─────────────────────────────────────────────────────

#: `tradehub_core/api/media_admin.py:33` ALLOWED_ROLES aynası.
ADMIN_ROLES: Tuple[str, ...] = ("System Manager", "Marketplace Admin")

#: `media_admin.py:39` DESTRUCTIVE_ROLES aynası — geri alınamaz işlemler.
DESTRUCTIVE_ROLES: Tuple[str, ...] = ("System Manager",)

#: `tradehub_core/api/chat.py:319` ve `reservation.py:33` ile aynı küme.
SELLER_ROLES: Tuple[str, ...] = ("Seller", "Marketplace Seller", "Verified Seller")

#: Frappe'de oturumsuz kullanıcının adı.
GUEST_USER: str = "Guest"


@dataclass(frozen=True)
class Principal:
	"""İsteği yapan. `frappe.session` + `frappe.get_roles()` karşılığı.

	`store` satıcı kapsamıdır (`Admin Seller Profile` adı). Kapsam
	`tradehub_core/media/chunked.py`'de her adımda yeniden doğrulanıyor; bu
	katman aynı disiplini sürdürür — kimliği ele geçiren biri başka mağazanın
	oturumuna dokunamamalı.
	"""

	user: str = GUEST_USER
	roles: Tuple[str, ...] = ()
	store: str = ""

	@property
	def authenticated(self) -> bool:
		return bool(self.user) and self.user != GUEST_USER

	def has_any(self, roles: Iterable[str]) -> bool:
		kume = set(self.roles)
		return any(r in kume for r in roles)

	@property
	def is_admin(self) -> bool:
		return self.has_any(ADMIN_ROLES)


ANONYMOUS: Principal = Principal()

#: Yetki reddi kancası. `media_admin._only_for` reddi denetim kaydına yazıyor;
#: bu kütüphane `audit`'e bağlanamaz (frappe gerekir), bu yüzden kanca
#: dışarıdan verilir. Verilmezse red yine olur, yalnız kayda geçmez.
DenialHook = Callable[[Principal, Sequence[str], str], None]


def require_auth(principal: Principal) -> Principal:
	"""Oturum şart. Guest → 401."""
	if principal is None or not principal.authenticated:
		raise Unauthorized(
			"Bu işlem için oturum açmanız gerekiyor.",
			kod=kod_uret(API_PREFIX, "unauthorized"),
		)
	return principal


def require_roles(
	principal: Principal,
	roles: Sequence[str],
	*,
	scope: str = "",
	on_denied: Optional[DenialHook] = None,
) -> Principal:
	"""Rol kapısı. `media_admin._only_for` ile aynı sözleşme + denetim kancası."""
	require_auth(principal)
	if not principal.has_any(roles):
		if on_denied is not None:
			on_denied(principal, tuple(roles), scope or "media_engine")
		raise Forbidden(
			"Bu işlem için yetkiniz yok.",
			kod=kod_uret(API_PREFIX, "forbidden"),
			detay={"required_roles": list(roles), "scope": scope or "media_engine"},
		)
	return principal


def require_store(principal: Principal) -> str:
	"""Satıcı kapsamı şart — `chunked.begin()` ile aynı kural (STORE_REQUIRED)."""
	require_auth(principal)
	if not principal.store:
		raise Forbidden(
			"Bu işlem için bir mağaza hesabı gerekiyor.",
			kod=kod_uret(API_PREFIX, "store_required"),
		)
	return principal.store


def same_store(principal: Principal, store: str) -> bool:
	"""Admin her mağazayı görür; satıcı yalnız kendi mağazasını."""
	if principal.is_admin:
		return True
	return bool(store) and principal.store == store


# ── Küçük doğrulayıcılar ────────────────────────────────────────────────
#
# Uç noktalarda tekrar eden üç kontrol. Her uçta elle yazmak, birinin
# gevşemesi demektir.

MAX_PAGE_SIZE: int = 200
DEFAULT_PAGE_SIZE: int = 50


def require_str(value: Any, field_name: str, *, max_len: int = 512) -> str:
	"""Boş olmayan dizge. Sessizce `str(None)` = `"None"` üretmez."""
	if value is None:
		raise BadRequest(
			f"`{field_name}` alanı zorunlu.",
			kod=kod_uret(API_PREFIX, "missing_field"),
			detay={"field": field_name},
		)
	metin = str(value).strip()
	if not metin:
		raise BadRequest(
			f"`{field_name}` alanı boş olamaz.",
			kod=kod_uret(API_PREFIX, "missing_field"),
			detay={"field": field_name},
		)
	if len(metin) > max_len:
		raise BadRequest(
			f"`{field_name}` çok uzun ({len(metin)} > {max_len}).",
			kod=kod_uret(API_PREFIX, "field_too_long"),
			detay={"field": field_name, "max_len": max_len},
		)
	return metin


def require_int(value: Any, field_name: str, *, minimum: int = 0, maximum: Optional[int] = None) -> int:
	try:
		sayi = int(value)
	except (TypeError, ValueError):
		raise BadRequest(
			f"`{field_name}` bir tam sayı olmalı.",
			kod=kod_uret(API_PREFIX, "bad_field"),
			detay={"field": field_name, "observed": repr(value)},
		)
	if sayi < minimum or (maximum is not None and sayi > maximum):
		raise BadRequest(
			f"`{field_name}` aralık dışında: {sayi}.",
			kod=kod_uret(API_PREFIX, "bad_field"),
			detay={"field": field_name, "min": minimum, "max": maximum, "observed": sayi},
		)
	return sayi


def require_unit(value: Any, field_name: str) -> float:
	"""0-1 normalize koordinat (INV-10). Piksel kabul EDİLMEZ."""
	try:
		sayi = float(value)
	except (TypeError, ValueError):
		raise BadRequest(
			f"`{field_name}` bir sayı olmalı.",
			kod=kod_uret(API_PREFIX, "bad_field"),
			detay={"field": field_name, "observed": repr(value)},
		)
	if not (0.0 <= sayi <= 1.0):
		raise BadRequest(
			f"`{field_name}` 0 ile 1 arasında olmalı (normalize koordinat, INV-10): {sayi}.",
			kod=kod_uret(API_PREFIX, "bad_field"),
			detay={"field": field_name, "observed": sayi},
		)
	return sayi


def page_params(page: Any = 1, page_size: Any = DEFAULT_PAGE_SIZE) -> Tuple[int, int]:
	"""`(page, page_size)` — sayfa boyutu tavanı KELEPÇELENİR, hata verilmez.

	`page_size=100000` isteyen istemciyi reddetmek yerine tavana çekmek,
	`media_admin.get_private_files` ile aynı davranıştır.
	"""
	p = max(1, require_int(page or 1, "page", minimum=1))
	ps = require_int(page_size or DEFAULT_PAGE_SIZE, "page_size", minimum=1)
	return p, min(ps, MAX_PAGE_SIZE)


__all__ = [
	"API_PREFIX",
	"HTTP_OK",
	"HTTP_CREATED",
	"HTTP_ACCEPTED",
	"HTTP_NO_CONTENT",
	"HTTP_NOT_MODIFIED",
	"HTTP_BAD_REQUEST",
	"HTTP_UNAUTHORIZED",
	"HTTP_FORBIDDEN",
	"HTTP_NOT_FOUND",
	"HTTP_CONFLICT",
	"HTTP_PRECONDITION_FAILED",
	"HTTP_PAYLOAD_TOO_LARGE",
	"HTTP_UNSUPPORTED_MEDIA_TYPE",
	"HTTP_UNPROCESSABLE",
	"HTTP_TOO_MANY_REQUESTS",
	"HTTP_INTERNAL_ERROR",
	"HTTP_UNAVAILABLE",
	"ApiError",
	"BadRequest",
	"Unauthorized",
	"Forbidden",
	"NotFound",
	"Conflict",
	"PreconditionFailed",
	"PayloadTooLarge",
	"TooManyRequests",
	"ServiceUnavailable",
	"STATUS_BY_ERROR",
	"http_status_for",
	"ApiResponse",
	"ok",
	"created",
	"accepted",
	"no_content",
	"not_modified",
	"error_response",
	"call",
	"CACHE_MANIFEST",
	"CACHE_NEVER",
	"etag_for",
	"etag_matches",
	"conditional_get",
	"ADMIN_ROLES",
	"DESTRUCTIVE_ROLES",
	"SELLER_ROLES",
	"GUEST_USER",
	"Principal",
	"ANONYMOUS",
	"DenialHook",
	"require_auth",
	"require_roles",
	"require_store",
	"same_store",
	"MAX_PAGE_SIZE",
	"DEFAULT_PAGE_SIZE",
	"require_str",
	"require_int",
	"require_unit",
	"page_params",
]

"""T-052 — HMAC imzalı, süreli medya URL'i. TTL kelepçesi + sabit-zamanlı karşılaştırma.

MEVCUT UYGULAMA OKUNDU, YENİDEN YAZILMADI
-----------------------------------------
`tradehub_core/api/media_access.py` imzalı private erişimi ZATEN üretimde
uyguluyor ve doğru uyguluyor:

    get_signed_url()   yetki kontrolü → `frappe.utils.verified_command.
                       get_signed_params` (site secret + HMAC-SHA512)
    download()         `verify_request()` → `exp` → `check_path_safety` →
                       `send_private_file`, her red dalı denetime yazılır
    _clamp_ttl()       [60, 86400] aralığı, varsayılan 900

Bu modül o kodun yerine geçmez; onu **sarar** ve iki eksiğini kapatır:

  1. **Frappe'siz imzalanabilirlik.** `verified_command` `frappe.local.conf`
     ister; motorun saf katmanı (depolama adaptörleri) site olmadan
     `url_for()` üretebilmek zorunda — `StorageAdapter.url_for` sözleşmesi
     private kapsamda imzalı URL şart koşuyor (FR-112/FR-113).
  2. **İkinci TTL kelepçesi.** Bugün clamp YALNIZ imzalama anında var
     (`media_access._clamp_ttl`). İmzalayan tarafta bir hata/regresyon
     `exp`'i on yıl sonraya koyarsa doğrulayan taraf bunu FARK ETMEZ: `exp`
     imzanın içinde olduğu için geçerli görünür ve süresiz bir kapı açılır.
     Buradaki imza `iat`'ı da kapsar, doğrulayıcı `exp - iat <= max_ttl`
     kontrolünü YENİDEN yapar. Kelepçe böylece iki bağımsız yerde durur.

SABİT-ZAMANLI KARŞILAŞTIRMA
---------------------------
İmza karşılaştırması `hmac.compare_digest` ile yapılır ve **her koşulda**
hesaplanır: yol bozuk olsa, `exp` eksik olsa bile önce beklenen imza üretilir,
sonra karşılaştırılır. Erken `return` ile kısa devre yapmak, saldırgana
"ilk n bayt doğruydu" bilgisini zamanlama üzerinden sızdırır.

Sıra da bilinçli ve `media_access.download()` ile AYNI: önce imza, sonra süre.
Tersi olsaydı süresi geçmiş ama imzasız bir istek "expired" cevabı alır ve
saldırgan `exp` alanının kabul edildiğini öğrenirdi.

BU MODÜL YETKİ KONTROLÜ YAPMAZ
------------------------------
`media_access.get_signed_url` imzalamadan ÖNCE `File.has_permission("read")`
çağırıyor ve bu modülün onu taklit etmesi imkânsız (DB gerekir). Kural
değişmiyor: **imzalamadan önce yetkiyi çağıran doğrular.** `HmacUrlSigner.sign`
bir yetki kapısı DEĞİLDİR; yetkisiz çağrıya imza üretir. Uç katmanı
(`api/`) `FrappeSignedUrl` üzerinden gitmelidir.
"""

from __future__ import annotations

import hmac
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit

from tradehub_core.media.pipeline.contracts.errors import DeliveryError

# ── TTL politikası: KAYNAK tradehub_core/api/media_access.py ────────────
#
# `core/jobs.py` ile aynı desen: frappe varsa üretim sabitleri oradan alınır,
# yoksa aşağıdaki ayna kullanılır ve `tests/test_storage_adapters.py`
# ayrışmayı düşürür. Ayna değerleri `media_access.py:57-59`'dan.
_MIRROR: Dict[str, Any] = {
	"DEFAULT_TTL_SECONDS": 900,
	"MIN_TTL_SECONDS": 60,
	"MAX_TTL_SECONDS": 86400,
	"PRIVATE_PREFIX": "/private/files/",
}

try:  # pragma: no cover - bench içinde bu dal çalışır
	from tradehub_core.api import media_access as _upstream

	DEFAULT_TTL_SECONDS: int = _upstream.DEFAULT_TTL_SECONDS
	MIN_TTL_SECONDS: int = _upstream.MIN_TTL_SECONDS
	MAX_TTL_SECONDS: int = _upstream.MAX_TTL_SECONDS
	PRIVATE_PREFIX: str = _upstream.PRIVATE_PREFIX
	UPSTREAM_AVAILABLE: bool = True
except Exception:  # frappe yok — test/CI yolu
	_upstream = None
	DEFAULT_TTL_SECONDS = _MIRROR["DEFAULT_TTL_SECONDS"]
	MIN_TTL_SECONDS = _MIRROR["MIN_TTL_SECONDS"]
	MAX_TTL_SECONDS = _MIRROR["MAX_TTL_SECONDS"]
	PRIVATE_PREFIX = _MIRROR["PRIVATE_PREFIX"]
	UPSTREAM_AVAILABLE = False

#: Üretim uçnoktası — `media_access.get_signed_url` bu yolu döndürüyor.
DOWNLOAD_ENDPOINT: str = "/api/method/tradehub_core.api.media_access.download"

#: Sorgu parametre adları. `exp` üretimdeki adla AYNI (`media_access.py:158`);
#: `iat` ve `sig` bu modülün eklediği alanlar.
PARAM_FILE: str = "file"
PARAM_EXPIRES: str = "exp"
PARAM_ISSUED: str = "iat"
PARAM_SIGNATURE: str = "sig"

#: Varsayılan özet. SHA-256 yeterli: imza gizli anahtarla üretiliyor ve
#: yalnız kısa ömürlü bir URL'i kapsıyor. `verified_command` SHA-512
#: kullanıyor; iki uygulama farklı özet kullanabilir çünkü aynı imzayı
#: doğrulamıyorlar — hangi imzalayıcının ürettiği URL'in hangi doğrulayıcıya
#: gittiği `api/` katmanında tek yönlüdür.
DEFAULT_DIGEST: str = "sha256"

# ── Red sebepleri ───────────────────────────────────────────────────────
REASON_OK: str = "ok"
REASON_BAD_PATH: str = "bad_path"
REASON_MISSING_SIGNATURE: str = "missing_signature"
REASON_INVALID_SIGNATURE: str = "invalid_signature"
REASON_MALFORMED_EXP: str = "malformed_exp"
REASON_EXPIRED: str = "expired"
REASON_TTL_EXCEEDED: str = "ttl_exceeded"
REASON_DELEGATED: str = "delegated_to_frappe"


class SignedUrlError(DeliveryError):
	"""İmzalı URL üretilemedi (yol reddedildi, anahtar yok)."""


def clamp_ttl(ttl_seconds: Any, *, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
	"""TTL'i `[minimum, maximum]` aralığına sıkıştır — `media_access._clamp_ttl` ile AYNI.

	Sayıya çevrilemeyen ya da boş değer varsayılana düşer; negatif değer alt
	sınıra çıkar. Üst sınır olmadan link isteyen taraf pratikte sınırsız
	süreli bir kapı açabilirdi (TUR-126 §3.2).
	"""
	low = MIN_TTL_SECONDS if minimum is None else minimum
	high = MAX_TTL_SECONDS if maximum is None else maximum
	try:
		ttl = int(ttl_seconds) if ttl_seconds not in (None, "") else DEFAULT_TTL_SECONDS
	except (TypeError, ValueError):
		ttl = DEFAULT_TTL_SECONDS
	return max(low, min(ttl, high))


def require_private_path(path: str) -> str:
	"""Yolun güvenli ve `/private/files/` altında olduğunu doğrula.

	`media_access._require_private_path` ile AYNI iki red sebebi: yol geçişi
	(`..`) ve public yol. Public zaten girişsiz açık; onu imzalamak imzayı
	anlamsız kılar ve "imzalı olduğuna göre korunuyordur" yanılgısı üretir.
	"""
	clean = (path or "").strip()
	if not clean or ".." in clean or not clean.startswith(PRIVATE_PREFIX):
		raise SignedUrlError(
			"Yalnız private dosyalar için imzalı bağlantı üretilebilir.",
			detay={"reason": REASON_BAD_PATH},
		)
	return clean


@dataclass(frozen=True)
class SignedUrl:
	"""Üretilmiş imzalı URL ve künyesi."""

	url: str
	path: str
	issued_at: int
	expires_at: int
	ttl_seconds: int
	signature: str

	def remaining(self, now: Optional[float] = None) -> int:
		"""Kalan saniye; süresi geçmişse 0."""
		simdi = int(time.time() if now is None else now)
		return max(0, self.expires_at - simdi)

	def to_dict(self) -> Dict[str, Any]:
		"""`media_access.get_signed_url` yanıt biçimiyle uyumlu sözlük."""
		return {
			"url": self.url,
			"exp": self.expires_at,
			"ttl_seconds": self.ttl_seconds,
		}


@dataclass(frozen=True)
class Verdict:
	"""Doğrulama sonucu. `bool(verdict)` geçerlilik demektir."""

	valid: bool
	reason: str
	path: str = ""
	expires_at: int = 0
	issued_at: int = 0
	detay: Dict[str, Any] = field(default_factory=dict)

	def __bool__(self) -> bool:
		return self.valid


class UrlSigner(Protocol):
	"""İmzalı URL üreten/doğrulayan taraf."""

	def sign(self, path: str, *, ttl_seconds: Optional[int] = None) -> SignedUrl:
		"""Yolu imzala. Yetki kontrolü YAPMAZ — çağıranın işi."""
		...

	def verify(self, url: str, *, now: Optional[float] = None) -> Verdict:
		"""İmzayı ve süreyi doğrula. Asla istisna atmaz, `Verdict` döner."""
		...


class HmacUrlSigner:
	"""Saf HMAC imzalayıcı — frappe GEREKTİRMEZ.

	İmzalanan yük (payload) üç alanı kapsar ve sırası SABİTTİR:

	    <path>\\n<iat>\\n<exp>

	`iat`'ın imzaya girmesi doğrulayıcının TTL'i yeniden kelepçelemesini
	mümkün kılar (modül dokümanı §2). Sırayı değiştirmek eski imzaları
	geçersiz kılar — sürüm etiketi yok, çünkü URL'ler zaten kısa ömürlü
	(tavan `MAX_TTL_SECONDS`); tüm eski imzalar bir gün içinde doğal olarak
	dolar.
	"""

	def __init__(
		self,
		secret: bytes,
		*,
		digest: str = DEFAULT_DIGEST,
		endpoint: str = DOWNLOAD_ENDPOINT,
		default_ttl: Optional[int] = None,
		min_ttl: Optional[int] = None,
		max_ttl: Optional[int] = None,
		signature_length: int = 0,
	) -> None:
		if not secret:
			raise SignedUrlError("İmzalama anahtarı boş olamaz.", detay={"reason": "no_secret"})
		self._secret = secret if isinstance(secret, bytes) else str(secret).encode("utf-8")
		self._digest = digest
		self._endpoint = endpoint or ""
		self._default_ttl = DEFAULT_TTL_SECONDS if default_ttl is None else int(default_ttl)
		self._min_ttl = MIN_TTL_SECONDS if min_ttl is None else int(min_ttl)
		self._max_ttl = MAX_TTL_SECONDS if max_ttl is None else int(max_ttl)
		# 0 = kırpma yok. Kırpmak URL'i kısaltır ama güvenlik payını düşürür;
		# varsayılan olarak kırpılmaz.
		self._signature_length = int(signature_length)
		if self._min_ttl > self._max_ttl:
			raise SignedUrlError(
				"min_ttl max_ttl'den büyük olamaz.",
				detay={"min_ttl": self._min_ttl, "max_ttl": self._max_ttl},
			)

	# ── imzalama ───────────────────────────────────────────────────────

	@property
	def max_ttl(self) -> int:
		return self._max_ttl

	def _payload(self, path: str, issued_at: int, expires_at: int) -> bytes:
		return f"{path}\n{issued_at}\n{expires_at}".encode("utf-8")

	def _digest_of(self, path: str, issued_at: int, expires_at: int) -> str:
		mac = hmac.new(self._secret, self._payload(path, issued_at, expires_at), self._digest)
		imza = mac.hexdigest()
		return imza[: self._signature_length] if self._signature_length else imza

	def sign(self, path: str, *, ttl_seconds: Optional[int] = None) -> SignedUrl:
		"""Private yolu imzala.

		TTL `[min_ttl, max_ttl]` aralığına sıkıştırılır; çağıranın istediği
		değer değil, sıkıştırılmış değer geçerlidir (FR-113).
		"""
		temiz = require_private_path(path)
		ttl = clamp_ttl(
			self._default_ttl if ttl_seconds is None else ttl_seconds,
			minimum=self._min_ttl,
			maximum=self._max_ttl,
		)
		iat = int(time.time())
		exp = iat + ttl
		imza = self._digest_of(temiz, iat, exp)
		sorgu = urlencode(
			[
				(PARAM_FILE, temiz),
				(PARAM_ISSUED, iat),
				(PARAM_EXPIRES, exp),
				(PARAM_SIGNATURE, imza),
			]
		)
		url = f"{self._endpoint}?{sorgu}" if self._endpoint else f"{temiz}?{sorgu}"
		return SignedUrl(
			url=url, path=temiz, issued_at=iat, expires_at=exp, ttl_seconds=ttl, signature=imza
		)

	# ── doğrulama ──────────────────────────────────────────────────────

	def verify(self, url: str, *, now: Optional[float] = None) -> Verdict:
		"""İmzayı ve süreyi doğrula — istisna atmaz.

		Sıra (`media_access.download()` ile aynı): imza → TTL kelepçesi →
		süre. Beklenen imza HER durumda hesaplanır ve
		`hmac.compare_digest` ile karşılaştırılır; bozuk yol/eksik alan
		erken `return` üretmez.
		"""
		params = parse_signed_params(url)
		yol = params.get(PARAM_FILE, "")
		ham_imza = params.get(PARAM_SIGNATURE, "")

		# Bozuk yol da imza hesaplamasına girer — kısa devre yapmamak için.
		# Geçerli sayılması yine de imkânsız: `yol_gecerli` aşağıda ayrı
		# kapı olarak duruyor.
		yol_gecerli = bool(yol) and ".." not in yol and yol.startswith(PRIVATE_PREFIX)

		iat, iat_ok = _to_int(params.get(PARAM_ISSUED))
		exp, exp_ok = _to_int(params.get(PARAM_EXPIRES))

		beklenen = self._digest_of(yol, iat, exp)
		imza_dogru = hmac.compare_digest(beklenen, ham_imza or "")

		if not ham_imza:
			return Verdict(False, REASON_MISSING_SIGNATURE, path=yol)
		if not yol_gecerli:
			return Verdict(False, REASON_BAD_PATH, path=yol)
		if not imza_dogru:
			return Verdict(False, REASON_INVALID_SIGNATURE, path=yol)
		if not (iat_ok and exp_ok):
			return Verdict(False, REASON_MALFORMED_EXP, path=yol)

		# İKİNCİ TTL kelepçesi — imzalayıcı hatalı/ele geçmiş olsa bile
		# `max_ttl`'den uzun bir kapı açılamaz.
		if exp - iat > self._max_ttl:
			return Verdict(
				False,
				REASON_TTL_EXCEEDED,
				path=yol,
				expires_at=exp,
				issued_at=iat,
				detay={"ttl": exp - iat, "max_ttl": self._max_ttl},
			)

		simdi = int(time.time() if now is None else now)
		if exp <= simdi:
			return Verdict(False, REASON_EXPIRED, path=yol, expires_at=exp, issued_at=iat)

		return Verdict(True, REASON_OK, path=yol, expires_at=exp, issued_at=iat)


class FrappeSignedUrl:
	"""Üretim imzalayıcısı — `tradehub_core.api.media_access` sarmalayıcısı.

	`sign()` yetki kontrolünü DE yapar (`media_access.get_signed_url` içinde
	`File.has_permission("read")`), dolayısıyla uç katmanının kullanması
	gereken sınıf budur. `frappe` import'u fonksiyon içinde ve tembeldir.

	`verify()` bilinçli olarak uygulanmaz: `frappe.utils.verified_command.
	verify_request` istek bağlamı (`frappe.form_dict`) ister ve doğrulama
	zaten `media_access.download()` içinde yapılır. Burada sahte bir
	"geçerli" döndürmek, ikinci bir doğrulama yolu varmış izlenimi yaratırdı.
	"""

	def sign(self, path: str, *, ttl_seconds: Optional[int] = None) -> SignedUrl:
		from tradehub_core.api import media_access  # tembel: frappe gerektirir

		temiz = require_private_path(path)
		ttl = clamp_ttl(ttl_seconds)
		sonuc = media_access.get_signed_url(temiz, ttl)
		exp = int(sonuc["exp"])
		gercek_ttl = int(sonuc.get("ttl_seconds") or ttl)
		return SignedUrl(
			url=sonuc["url"],
			path=temiz,
			issued_at=exp - gercek_ttl,
			expires_at=exp,
			ttl_seconds=gercek_ttl,
			signature="",  # imza `verified_command` biçiminde, URL'in içinde
		)

	def verify(self, url: str, *, now: Optional[float] = None) -> Verdict:
		"""Doğrulama `media_access.download()`'a aittir — burada yapılmaz."""
		return Verdict(False, REASON_DELEGATED, path=parse_signed_params(url).get(PARAM_FILE, ""))


# ── yardımcılar ─────────────────────────────────────────────────────────


def parse_signed_params(url: str) -> Dict[str, str]:
	"""URL / sorgu dizgesi / `?`'siz yol → parametre sözlüğü.

	Hatalı girdi istisna ATMAZ, boş sözlük döner: doğrulayıcı her girdi için
	aynı kod yolunu yürümeli (zamanlama kanalı).
	"""
	if not url:
		return {}
	parca = urlsplit(url)
	sorgu = parca.query or (url if "=" in url and "?" not in url else "")
	return dict(parse_qsl(sorgu, keep_blank_values=True))


def _to_int(value: Any) -> Tuple[int, bool]:
	"""`(deger, gecerli_mi)` — geçersizde `(0, False)`. İstisna atmaz."""
	try:
		return int(value), True
	except (TypeError, ValueError):
		return 0, False


def signer_from_secret(secret: Any, **kwargs: Any) -> HmacUrlSigner:
	"""Dizge/bayt anahtardan imzalayıcı üret."""
	ham = secret if isinstance(secret, bytes) else str(secret or "").encode("utf-8")
	return HmacUrlSigner(ham, **kwargs)


def default_signer(*, secret: Any = None, **kwargs: Any) -> UrlSigner:
	"""Ortama göre imzalayıcı seç.

	Sıra:
	  1. Açıkça verilen `secret` → `HmacUrlSigner` (test ve saf katman).
	  2. `MEDIA_ENGINE_SIGNING_KEY` ortam değişkeni → `HmacUrlSigner`.
	  3. Frappe mevcutsa → `FrappeSignedUrl` (üretim; yetki kontrolü dâhil).

	Hiçbiri yoksa `SignedUrlError`. **Rastgele bir anahtar ÜRETİLMEZ**:
	süreç yeniden başladığında tüm imzalı linkler sessizce geçersiz olurdu ve
	bunun teşhisi (çalışan bir link, yeniden başlatmadan sonra 403) çok pahalı.
	"""
	if secret:
		return signer_from_secret(secret, **kwargs)
	ortam = os.environ.get("MEDIA_ENGINE_SIGNING_KEY")
	if ortam:
		return signer_from_secret(ortam, **kwargs)
	if UPSTREAM_AVAILABLE:
		return FrappeSignedUrl()
	raise SignedUrlError(
		"İmzalama anahtarı yok: `secret` verin ya da MEDIA_ENGINE_SIGNING_KEY "
		"ortam değişkenini tanımlayın.",
		detay={"reason": "no_secret"},
	)


def verify_ttl_contract() -> Dict[str, Any]:
	"""Üretim TTL sabitleriyle bu modülün aynada tuttuğu değerleri karşılaştır.

	Sessiz ayrışma bu modülün tek gerçek riski: `media_access._clamp_ttl`
	sınırları değişir ve burası eski değerlerle imzalamaya devam ederse
	kelepçe iki farklı yerde iki farklı sayı olur. Frappe yoksa
	`available=False` döner ve test ATLANIR — sahte "geçti" verilmez.
	"""
	if not UPSTREAM_AVAILABLE:  # pragma: no cover - bench dışı
		return {"available": False, "matches": None, "mirror": dict(_MIRROR)}
	gercek = {
		"DEFAULT_TTL_SECONDS": _upstream.DEFAULT_TTL_SECONDS,
		"MIN_TTL_SECONDS": _upstream.MIN_TTL_SECONDS,
		"MAX_TTL_SECONDS": _upstream.MAX_TTL_SECONDS,
		"PRIVATE_PREFIX": _upstream.PRIVATE_PREFIX,
	}
	return {
		"available": True,
		"matches": gercek == _MIRROR,
		"mirror": dict(_MIRROR),
		"upstream": gercek,
	}


__all__ = [
	"DEFAULT_TTL_SECONDS",
	"MIN_TTL_SECONDS",
	"MAX_TTL_SECONDS",
	"PRIVATE_PREFIX",
	"DOWNLOAD_ENDPOINT",
	"UPSTREAM_AVAILABLE",
	"PARAM_FILE",
	"PARAM_EXPIRES",
	"PARAM_ISSUED",
	"PARAM_SIGNATURE",
	"REASON_OK",
	"REASON_BAD_PATH",
	"REASON_MISSING_SIGNATURE",
	"REASON_INVALID_SIGNATURE",
	"REASON_MALFORMED_EXP",
	"REASON_EXPIRED",
	"REASON_TTL_EXCEEDED",
	"REASON_DELEGATED",
	"SignedUrl",
	"SignedUrlError",
	"Verdict",
	"UrlSigner",
	"HmacUrlSigner",
	"FrappeSignedUrl",
	"clamp_ttl",
	"require_private_path",
	"parse_signed_params",
	"signer_from_secret",
	"default_signer",
	"verify_ttl_contract",
]

# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Kargo firması HTTP istemcisi — taşıma-bağımsız transport primitifi (TUR-110).

Bu modül **tek bir iş** yapar: bir kargo firmasının HTTP uç noktasına istek
gönderir ve ham yanıtı geri verir. Serileştirme (JSON/SOAP/form) ve yanıt
ayrıştırma ADAPTER'ın işidir — istemci gövdeyi olduğu gibi taşır.

## İKİ AYRI KİMLİK UZAYI (karıştırmak logu tamamen kaybettirir)

	carrier_code : ADAPTER REGISTRY kodu — `registry.py` bunu `.strip().lower()`
	               eder, örnekleri `aras` / `yurtici`. Devre kesici anahtarının
	               ve hata telemetrisinin kapsamı budur. Serbest bir dize.
	provider     : `Logistics Provider` DOCNAME'i — sitedeki değerler `AK`, `YK`,
	               `MNG`, `PTT`, `SK`, `UPS`, `DHL`, `FEDEX`. `Carrier Integration
	               Log.carrier` alanı bu DocType'a **Link** ve `reqd:1`.

Bu ikisi AYNI DİZE OLMAK ZORUNDA DEĞİLDİR ve pratikte değildir. Ölçülmüş arıza:
`carrier='aras'` ile yazılan log satırı LinkValidationError'da düşüyor,
`write_integration_log` istisnayı yutuyor, `_log`'un kendi except'i de yutuyor —
gözlemlenebilirlik katmanı SESSİZCE tamamen kayboluyordu. Bu yüzden log
yalnızca `provider` verildiğinde yazılır; verilmezse loglama kapalıdır
(fail-safe) ve yapıcıda bir kez uyarılır. Gerekçe: transport primitifi bir DB
kaydının varlığına bağımlı olmamalı — mock adapter, sözleşme testleri ve
"bağlantıyı test et" akışı provider olmadan da çalışabilmeli; ama gerçek
entegrasyonda eksik provider gürültülü olmalı, sessiz değil.

## Burada merkezileşen davranışlar

1. **İşlem türüne duyarlı yeniden deneme.** Gönderi oluşturmayı körlemesine
   tekrar denemek kargo firmasında ÇİFT GÖNDERİ (ve çift fatura) yaratır. Bu
   yüzden yeniden deneme varsayılan olarak KAPALI; yalnızca çağıran
   `idempotent=True` derse açılır. Politikanın kendisi enjekte edilebilir:
   `logistics/resilience/retry_policy.py::RetryPolicy`.
2. **Taşıyıcı bazında devre kesici.** `logistics/resilience/circuit_breaker.py`.
   Sonuç sınıflandırması `Outcome` üzerinden yapılır (HEALTHY / UNAVAILABLE /
   NEUTRAL) ve `classify=` ile taşıyıcıya göre değiştirilebilir — TR SOAP
   taşıyıcıları rutin olarak HTTP 200 + gövdede `<ResultCode>-1</ResultCode>`
   döndürür ve bunu "sağlıklı" saymak devreyi asla açtırmaz.
3. **SSRF kapısı.** `adapters/url_guard.py` — her denemede ve HER YÖNLENDİRME
   ADIMINDA uygulanır. `Carrier Account.base_url` serbest bir `Data` alanı ve
   platform içi bir rol tarafından yazılabiliyor; kapı olmadan iç ağa erişim
   ve metadata sızdırma zinciri açık kalıyordu. Kapının kararı `GuardedHTTPAdapter`
   ile TAŞINIR: bağlantı doğrulanan IP'ye kurulur (bkz. sınıf docstring'i).
4. **Yanıt boyutu tavanı VE süre bütçesi.** Gövde `stream=True` + `iter_content`
   ile sabit tavana kadar okunur; Content-Type saldırgan kontrolündedir ve
   "application/json" deyip 500 MB göndermek işçiyi OOM'a sürüklerdi. Bayt
   tavanı TEK BAŞINA yetmiyor: okuma timeout'u SOKET OKUMASI BAŞINA uygulanır,
   saniyede 1 bayt gönderen bir sunucu onu her seferinde sıfırlar (ölçüldü:
   `timeout=(3,5)` ile 6 baytlık gövde 12,04 sn sürdü ve timeout hiç tetiklenmedi).
   Bu yüzden `MAX_BODY_READ_SEC` mutlak son tarihi var.
5. **Enjekte edilen log yazıcısı.** İstemci `logistics/integration/log.py`
   modülüne BAĞIMLI DEĞİLDİR; yapıcıya verilen callable ile konuşur. Maskeleme
   log katmanının sorumluluğu — buradan (boyutu kırpılmış) ham gövde geçer.
6. **Log, iç ağ keşif oracle'ı OLMAMALI.** `Carrier Integration Manager` hem
   `base_url`'e yazabiliyor hem logu okuyabiliyor. Bu yüzden kapı reddi log'a
   TEK kodla (`URL_BLOCKED`) ve çözümlenen IP OLMADAN düşer; `requests` istisna
   metni (`str(exc)`) — URL, host, port ve query string'deki credential'ı taşır —
   DocType'a HİÇ yazılmaz, yalnız `type(exc).__name__` yazılır. Tam metin iç
   telemetriye (`logistics` logger'ı) gider.

   AYRIM KAYNAKTA BİRLEŞTİRİLDİ (5. tur). "Ad DNS'te yok" (`URL_UNRESOLVABLE`)
   ile "ad çözümlendi ama iç adrese düştü" (`URL_HOST_BLOCKED`) arasındaki fark
   üç turda üç ayrı sütuna kaçtı (`error_code` → `is_retriable`/`duration_ms` →
   devre kesici durumu + `carrier_error_code`). Tek tek kanal kapatmak yerine
   kaynak birleştirildi: `_COLLAPSED_GUARD_CODES` kapsamındaki her kapı reddi
   TEK bir `Outcome` (NEUTRAL) üretir, tek denemede biter, tek log satırı yazar
   ve devre kesiciye HİÇ işlenmez. Kapı reddi zaten taşıyıcı arızası değil
   YAPILANDIRMA hatasıdır; çözümlenemeyen bir `base_url` için devreyi açmanın
   operasyonel değeri yoktur. Yeni bir alan eklerken kural: iki dal
   gözlemlenebilir HİÇBİR şeyde ayrışmamalı.
7. **Ortamdan gelen yapılandırma yok.** Kendi session'ında `trust_env=False`:
   `HTTPS_PROXY` kapının IP kararını tamamen geçersiz kılıyordu (ölçüldü: kapı
   8.8.8.8'i doğruladı, trafik `127.0.0.1:8123`'e gitti) ve `REQUESTS_CA_BUNDLE`
   TLS güven deposunu değiştirebiliyordu.

`carrier_api_enabled` feature flag'i BURADA kontrol EDİLMEZ: bu sınıf bir
transport primitifi; flag kontrolü servis/adapter katmanının işi (aksi halde
mock adapter ve testler flag kapalıyken çalışamazdı).

`frappe.integrations.utils.make_request` neden kullanılmıyor (REFACTOR-BEFORE-WRITE):
yanıtı content-type'a göre JSON'a çevirip ham gövdeyi kaybediyor (SOAP kırılır),
timeout parametresi yok, her hatada `frappe.log_error()` yazıyor ve deneme
başına log/attempt sayacı tutulamıyor. Altındaki `frappe.utils.get_request_session`
ise `Retry(total=5, status_forcelist=[500])` mount ediyor: transport katmanında
GÖRÜNMEZ yeniden denemeler yapar, bizim işlem-türüne göre karar veren mantığımızı
ve deneme başına loglamayı imkânsız kılar. Bu yüzden düz `requests.Session`
kullanıyoruz — yeniden denemeyi tamamen bu modül yönetir.
"""

from __future__ import annotations

import codecs
import email.utils
import json
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from functools import cached_property
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit

import frappe
import requests
from frappe import _

from tradehub_core.logistics.adapters.registry import normalize_carrier_code
from tradehub_core.logistics.adapters.url_guard import UrlGuard, UrlNotAllowedError
from tradehub_core.logistics.constants import CREDENTIAL_SECRET_FIELDS, INTEGRATION_LOG_OPERATIONS
from tradehub_core.logistics.exceptions import CarrierAPIError, CarrierTimeoutError, LogisticsError
from tradehub_core.logistics.integration.secrets import (
	collect_extra_secret_values,
	collect_secret_values,
)
from tradehub_core.logistics.resilience import (
	CarrierCircuitBreaker,
	CircuitState,
	Outcome,
	RetryPolicy,
)
from tradehub_core.logistics.resilience.fault_report import report_throttled, should_report

if TYPE_CHECKING:
	# YALNIZ TİP İÇİN. Modül docstring'inin 5. maddesi ("istemci
	# `logistics/integration/log.py` modülüne BAĞIMLI DEĞİLDİR") KORUNUR:
	# `TYPE_CHECKING` runtime'da False'tur, bu import hiç çalışmaz ve
	# `from __future__ import annotations` sayesinde ek açıklamalar da
	# değerlendirilmez. Soyutlama 2. turda yazılmıştı ama bağımlılık ona
	# ÇEVRİLMEMİŞTİ: enjeksiyon noktası hâlâ `Callable[..., Any]`'ydi, yani
	# Protocol'ün tek referansı bir smoke testiydi.
	from tradehub_core.logistics.integration.log import IntegrationLogWriter

__all__ = [
	"CREDENTIAL_SECRET_FIELDS",
	"CarrierHttpClient",
	"CarrierResponse",
	"DEFAULT_TIMEOUT",
	"GuardedHTTPAdapter",
	"MAX_BODY_READ_SEC",
	"MAX_RESPONSE_BYTES",
	"URL_BLOCKED_LOG_CODE",
	"VALID_OPERATIONS",
]


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

#: (bağlantı, okuma) saniye. TR kargo firmalarının SOAP uçları yavaş; okuma
#: payı geniş ama SINIRLI tutuldu — timeout'suz istek bir işçiyi süresiz kilitler.
DEFAULT_TIMEOUT: tuple[float, float] = (5.0, 30.0)

CIRCUIT_FAILURE_THRESHOLD: int = 5
CIRCUIT_COOLDOWN_SEC: int = 60
#: Hata sayacının yaşam süresi. Saatler arayla gelen 5 münferit hata devreyi
#: açmamalı — sayaç bu pencerede sıfırlanır.
CIRCUIT_FAILURE_WINDOW_SEC: int = 300

#: Belleğe alınacak azami yanıt gövdesi. Etiket PDF'i ve toplu takip yanıtı
#: megabaytlara çıkabiliyor; ama tavan olmadan tek bir arızalı (ya da düşman)
#: taşıyıcı, yeniden denenebilir bir çağrıda işçiyi 3 kez OOM'a sürükler.
MAX_RESPONSE_BYTES: int = 8 * 1024 * 1024
_READ_CHUNK_BYTES: int = 64 * 1024

#: Gövde okumasının MUTLAK süre bütçesi. Bayt tavanı tek başına yetmez:
#: requests/urllib3'te okuma timeout'u SOKET OKUMASI BAŞINA uygulanır, toplam
#: süreye değil — 2 saniyede bir 1 bayt gönderen sunucu onu her seferinde
#: sıfırlar ve 8 MiB tavanına kadar bir RQ işçisini pratikte süresiz tutar
#: (`idempotent=True` ile 3 kat). Varsayılan okuma timeout'unun ~2 katı.
MAX_BODY_READ_SEC: float = 60.0

#: Kapı reddinin entegrasyon loguna yazılan TEK kodu. `URL_HOST_BLOCKED` ile
#: `URL_UNRESOLVABLE` ayrımı "bu iç ad var mı" sorusunu cevaplıyordu ve loga
#: okuma yetkisi olan rol `base_url`'i tarayarak iç DNS haritası çıkarabiliyordu.
#: Ayrım iç telemetride (logistics logger'ı + `Outcome`) KORUNUR.
URL_BLOCKED_LOG_CODE: str = "URL_BLOCKED"
_COLLAPSED_GUARD_CODES: frozenset[str] = frozenset({"URL_HOST_BLOCKED", "URL_UNRESOLVABLE"})

#: Elle takip edilen azami yönlendirme adımı (her adım URL kapısından geçer).
DEFAULT_MAX_REDIRECTS: int = 3
_REDIRECT_STATUSES: frozenset[int] = frozenset({301, 302, 303, 307, 308})

#: Bağlantı havuzu boyutu — tek işçi tek taşıyıcıya paralel çağrı yapabilir.
DEFAULT_POOL_SIZE: int = 10

#: Devre-açık bildirimi yazılamadığında anahtarın aynı kısma penceresinde kaç
#: kez geri verileceği. Sınırsızken kalıcı bir log arızası "claim → düş →
#: release → yeniden claim" çevrimine giriyor ve istek başına rapor üretiyordu.
_OPEN_NOTICE_RETRY_LIMIT: int = 3

#: `read1` boş dönüşünün EOF SAYILMADAN önce kaç tur tolere edileceği.
#:
#: `decode_content=True` ile decoder bir turda çıktı üretmeyebilir (girdi
#: parçası tam bir deflate bloğu tamamlamıyorsa). O boş dönüşü EOF saymak
#: gövdeyi SESSİZCE kırpıyordu — sır sızdırmaz ama teşhis kaybettirir.
#: Sonsuz döngü riski yok: hem bu sayaç hem `_read_capped`'in MUTLAK süre
#: bütçesi sınırlıyor (boş parçalar bilerek `yield` ediliyor ki bütçe dönsün).
_MAX_EMPTY_READS: int = 64

#: `credential_doc` içinde DEĞERİ sır olan alanlar — TEK OTORİTE
#: `logistics/constants.py::CREDENTIAL_SECRET_FIELDS`. Buradaki ad yalnız
#: geriye dönük bir takma addır; toplama mantığı da bu modülde DEĞİL,
#: `integration/secrets.py::collect_secret_values` içindedir (webhook alıcısı ve
#: credential fabrikası da aynı fonksiyonu çağırsın diye).
#:
#: Eskiden küme burada YEDİ adla, `api/v1/logistics_admin.py::SECRET_FIELDS`'te
#: DÖRT adla yazılıydı ve buradaki yorum "aynı küme ... ikisi birlikte
#: değişmeli" diyerek yanlış bilgi veriyordu. `Carrier Account` DocType'ında
#: yalnız dört `Password` alanı var; fazladan üç ad hiç dolmuyordu.
#: (Katman gerekçesi de geçersizdi: `logistics_admin` zaten
#: `tradehub_core.logistics.api_utils`'ten import ediyor.)

#: `Carrier Integration Log.operation` Select sözleşmesi. TEK OTORİTE
#: `logistics/constants.py::INTEGRATION_LOG_OPERATIONS` — bu küme eskiden dört
#: yerde ayrı ayrı yazılıydı ve sapması sessiz veri kaybı üretiyordu. Buradaki
#: ad yalnız geriye dönük bir takma addır.
VALID_OPERATIONS: frozenset[str] = INTEGRATION_LOG_OPERATIONS

#: Log'a metin olarak yazılabilecek content-type parçaları. Etiket PDF'i gibi
#: ikili gövdeler log alanına (Code) yazılmaz — yerine özet konur.
_TEXTUAL_CONTENT_HINTS: tuple[str, ...] = ("text/", "json", "xml", "urlencoded", "javascript")

#: RFC 7230 token'ının dar bir alt kümesi. Transport kütüphanesinin sürümüne
#: bağlı kalmıyoruz: başlık adına/değerine CRLF sokabilen bir çağıran istek
#: bölme (request splitting) yapabilirdi.
#: `\A...\Z` KULLANILIYOR, `^...$` DEĞİL: Python'da `$` sondaki satır sonundan
#: ÖNCE de eşleşir, yani `"X-Api-Key\n"` kapıdan geçerdi (ölçüldü).
_HEADER_NAME_RE = re.compile(r"\A[A-Za-z0-9-]{1,128}\Z")

#: Başlık DEĞERİ için ALLOWLIST (denylist değil). Eski `ord(char) < 32 or == 127`
#: denylist'i U+0085 (NEL — latin-1'de 0x85 olarak tele çıkar), U+2028 ve U+2029'u
#: geçiriyordu (ölçüldü). Yazılabilir ASCII + yatay sekme dışında hiçbir şey
#: başlık değerine giremez.
_HEADER_VALUE_RE = re.compile(r"\A[\x20-\x7E\t]*\Z")

#: Değerini TRANSPORT üretir — çağıran veremez. `Host` pinlenmiş bağlantıda
#: adapter tarafından kurulur; `Content-Length`/`Transfer-Encoding` çifti bir
#: forward proxy arkasında istek kaçırma (request smuggling) yüzeyidir.
_TRANSPORT_OWNED_HEADERS: frozenset[str] = frozenset(
	{"host", "content-length", "transfer-encoding", "connection", "expect", "upgrade"}
)

#: Çapraz-host yönlendirmede TAŞINAN tek başlıklar (küçük harf).
#: requests yalnız `Authorization`'ı düşürür; adapter'ın koyduğu `X-Api-Key`
#: gibi başlıklar saldırganın hostuna AYNEN giderdi.
_SAFE_REDIRECT_HEADERS: frozenset[str] = frozenset(
	{"user-agent", "accept", "accept-encoding", "accept-language", "content-type"}
)


# ---------------------------------------------------------------------------
# Transport: doğrulanan IP'ye pinleme
# ---------------------------------------------------------------------------


class _BodyReadDeadline(requests.exceptions.ReadTimeout):
	"""Gövde okuması `MAX_BODY_READ_SEC` bütçesini aştı (slow-loris savunması).

	`requests.Timeout` soyundan: mevcut sınıflandırma zinciri bunu zaten
	`CarrierTimeoutError` (HTTP 504) olarak eşliyor; ayrı bir sınıf olmasının
	tek sebebi log kodunu (`BODY_READ_TIMEOUT`) soket timeout'undan ayırmak.
	"""


class GuardedHTTPAdapter(requests.adapters.HTTPAdapter):
	"""Bağlantıyı SSRF kapısının DOĞRULADIĞI IP'ye pinler.

	KÖK NEDEN: kapı bir ADI doğruluyor, transport ise o adı KENDİSİ yeniden
	çözümleyip bağlanıyordu. "Doğrulanan ad ≠ bağlanılan ad" iki ayrı bulgunun
	tek kaynağıydı:

		(a) DNS rebinding — doğrulama ile bağlantı arasındaki milisaniyelik
			pencerede kayıt iç bir adrese döndürülür;
		(b) IDNA kodlama farkı — `getaddrinfo` (stdlib `idna` CODEC'i, IDNA2003)
			ile `requests` (`idna` PAKETİ, UTS46) aynı host'tan FARKLI A-label
			üretir, yani iki taraf başka adları çözümler (bkz. `url_guard`).

	Bağlantı doğrulanan IP'ye kurulunca ikisi de biter: `Host` başlığı ve TLS
	SNI (`server_hostname`) + sertifika eşleşmesi (`assert_hostname`) orijinal
	ADLA taşınır, yani sertifika doğrulaması ZAYIFLAMAZ — IP'ye değil, adına
	doğrulanır.

	Pin, İSTEMCİ tarafından her istekten hemen önce kurulur; ikinci bir DNS
	çözümlemesi yapılmaz. Depolama `threading.local`: bir session'ı paylaşan
	işçi thread'leri birbirinin pinini görmemeli.
	"""

	def __init__(self, **kwargs: Any) -> None:
		super().__init__(**kwargs)
		self._local = threading.local()

	# -- pin yönetimi ---------------------------------------------------

	def _pins(self) -> dict[str, str]:
		pins: dict[str, str] | None = getattr(self._local, "pins", None)
		if pins is None:
			pins = {}
			self._local.pins = pins
		return pins

	def pin(self, host: str, address: str | None) -> None:
		"""`host` için bağlanılacak IP'yi belirler. `address=None` pini kaldırır."""
		pins = self._pins()
		key = (host or "").lower()
		if address:
			pins[key] = address
		else:
			pins.pop(key, None)

	def clear_pins(self) -> None:
		"""Bu thread'in tüm pinlerini siler — istek bitince BAYAT pin kalmasın."""
		self._local.pins = {}

	# -- requests bağlantı kurulumu --------------------------------------

	def build_connection_pool_key_attributes(
		self, request: Any, verify: Any, cert: Any = None
	) -> tuple[dict[str, Any], dict[str, Any]]:
		"""Havuz anahtarındaki HOST'u pinlenmiş IP ile değiştirir.

		`requests` 2.32+ bu metodu tam da bu amaçla ayırdı; `send()`'i baştan
		yazmak requests iç akışını kopyalamak olurdu (sürüm kırılganlığı).
		Metot yoksa (eski requests) override hiç çağrılmaz ve adapter düz
		`HTTPAdapter` gibi davranır — pinleme sessizce devre dışı kalır, ASCII
		reddi + kapı yerinde durur.
		"""
		host_params, pool_kwargs = super().build_connection_pool_key_attributes(request, verify, cert)
		hostname = str(host_params.get("host") or "").lower()
		pins = self._pins()
		address = pins.get(hostname)
		if not address:
			if pins:
				# FAIL-CLOSED. Kapı bu istek için bir pin kurdu ama transport
				# BAŞKA bir host'a bağlanmak üzere: tam olarak IDNA farkının
				# imzası (kapı `ss.attacker.com`, requests `xn--zca.attacker.com`).
				# ASCII reddi bunu zaten kesiyor; bu ikinci savunma hattı,
				# `requests`/`idna` sürümleri host'u başka bir biçimde yeniden
				# yazarsa sessizce pinsiz bağlanmamak içindir.
				raise UrlNotAllowedError(
					_("Taşıyıcı adresi doğrulanan adla eşleşmiyor."),
					guard_code="URL_HOST_BLOCKED",
				)
			return host_params, pool_kwargs
		if address == hostname:
			return host_params, pool_kwargs

		host_params["host"] = address
		if str(host_params.get("scheme") or "").lower() == "https":
			# SNI ve sertifika eşleşmesi ADLA yapılır; IP'ye sertifika arayan
			# bir doğrulama tüm taşıyıcı uçlarını kırardı.
			# İkisi de urllib3 `PoolKey` alanı (`key_assert_hostname`,
			# `key_server_hostname`), yani havuz anahtarına GİRERLER: pinlenmiş
			# bağlantı başka bir isteğin havuzuna karışmaz. `server_hostname`
			# `HTTPSConnectionPool.__init__`'in `**conn_kw`'sinden geçip
			# `HTTPSConnection(server_hostname=...)`'a ulaşır. `conn_kw`'yi ELLE
			# vermek PoolKey'de karşılığı olmadığı için `TypeError` üretiyordu.
			pool_kwargs["assert_hostname"] = hostname
			pool_kwargs["server_hostname"] = hostname
		return host_params, pool_kwargs

	def send(self, request: Any, **kwargs: Any) -> Any:
		"""`Host` başlığını orijinal adla taşır.

		urllib3 `Host`'u havuzun host'undan türetir; pinlendiğimiz için o değer
		IP olurdu ve isim-tabanlı sanal barındırma yapan her taşıyıcı uç noktası
		404/400 dönerdi.
		"""
		host = (urlsplit(request.url or "").hostname or "").lower()
		if host and self._pins().get(host):
			request.headers["Host"] = _netloc_for_host_header(request.url)
		return super().send(request, **kwargs)


def _netloc_for_host_header(url: str) -> str:
	"""`Host` başlığı değeri: ad + (varsayılan değilse) port."""
	parts = urlsplit(url or "")
	host = parts.hostname or ""
	try:
		port = parts.port
	except ValueError:
		port = None
	default = {"http": 80, "https": 443}.get((parts.scheme or "").lower())
	if port and port != default:
		return f"{host}:{port}"
	return host


# ---------------------------------------------------------------------------
# Yanıt sözleşmesi
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CarrierResponse:
	"""Ham taşıyıcı yanıtı. Ayrıştırma adapter'ın işi — burada parse YOK.

	`frozen`: `attempts` eskiden nesne kurulduktan SONRA mutasyona uğratılıyordu;
	deneme sayısı nihai değerini `request()` dönüşünde alır ve
	`dataclasses.replace` ile yeni bir nesne üretilir.
	"""

	status_code: int
	headers: Mapping[str, str]
	content: bytes
	elapsed_ms: int
	attempts: int
	encoding: str | None = None

	@cached_property
	def text(self) -> str:
		"""Gövdeyi metne çevirir (tembel + tek seferlik).

		`encoding` doğrudan saldırgan kontrolündeki `Content-Type; charset=`
		değerinden geliyor. Doğrulanmadan `decode()`'a verilince tanınmayan bir
		charset `LookupError` fırlatıyordu; bu sınıf `LogisticsError`
		hiyerarşisinde OLMADIĞI için API zarfına takılmıyor ve 500'e dönüşüyordu
		(ölçüldü: `charset=totally-not-a-codec`). RCE yolu YOK — bayt→bayt
		codec'lerini `bytes.decode()` zaten reddediyor — risk kullanılabilirlik.
		"""
		return self.content.decode(_usable_encoding(self.encoding) or "utf-8", errors="replace")

	@property
	def ok(self) -> bool:
		return 200 <= self.status_code < 400

	def json(self) -> Any:
		"""Kolaylık ayrıştırıcısı. İstemci bunu KENDİ çağırmaz — çağıran seçer."""
		return json.loads(self.text)


@dataclass
class _Attempt:
	"""Tek denemenin sonucu — başarı ya da sınıflandırılmış hata."""

	outcome: Outcome = Outcome.HEALTHY
	response: CarrierResponse | None = None
	failed: bool = False
	timed_out: bool = False
	status: int | None = None
	error_code: str | None = None
	error_message: str | None = None
	retry_after: float | None = None
	body_text: str | None = None
	#: URL kapısının DARALTILAN reddi mi (bkz. `_COLLAPSED_GUARD_CODES`).
	#: True ise gözlemlenebilir HER ŞEY sabitlenir: `Outcome` (NEUTRAL), deneme
	#: sayısı (1), DocType satırı ve devre kesici etkisi (yok). Gerçek
	#: `guard_code` ayrımı yalnız iç telemetride (`_warn`) kalır.
	collapsed_guard: bool = False


@dataclass
class _Call:
	"""Tek `request()` çağrısının değişmeyen bağlamı.

	Deneme yapan iç metotlar 10+ parametre yerine bunu alır; `shipment` ve
	`carrier_account` gibi KORELASYON alanları transport'u hiç ilgilendirmez,
	yalnızca logger'a iletilir (DocType bunları `in_standard_filter` yapmış ve
	patch `ix_cil_shipment_creation` index'ini kurmuş — dolmazsa ikisi de ölü).
	"""

	method: str
	url: str
	operation: str
	headers: dict[str, str]
	payload: bytes | None
	params: dict[str, Any] | None
	timeout: float | tuple[float, float]
	policy: RetryPolicy
	classify: Callable[[CarrierResponse], Outcome] | None
	request_body: str | None
	shipment: str | None = None
	carrier_account: str | None = None
	#: Daraltılan kapı reddi bu ÇAĞRI için DocType'a yazıldı mı (6. tur).
	#:
	#: Satır ÇAĞRI BAŞINA bir kez yazılır — koşul eskiden `attempt_no == 1` idi
	#: ve kapı reddi 1. denemeden SONRA geldiğinde (1. deneme gerçek
	#: `ConnectionError`, 2. deneme `URL_HOST_BLOCKED`) satır HİÇ yazılmıyordu:
	#: engellenen SSRF denemesi denetim izinde görünmüyordu (ölçüldü). Bayrak
	#: `_Call` üzerinde çünkü `_Call` tek çağrının bağlamıdır ve denemeler
	#: arasında yaşayan tek nesnedir.
	guard_logged: bool = False


# ---------------------------------------------------------------------------
# İstemci
# ---------------------------------------------------------------------------


class CarrierHttpClient:
	"""Taşıma-bağımsız kargo HTTP istemcisi.

	Args:
		carrier_code: REGISTRY kodu — devre kesici anahtarı ve hata telemetrisi.
			`Logistics Provider` docname'i DEĞİL (bkz. modül docstring'i).
		provider: `Logistics Provider` docname'i — entegrasyon logunun `carrier`
			Link alanı. Verilmezse LOGLAMA KAPALIDIR (fail-safe).
		credential_doc: `Carrier Account` dokümanı ya da alan eşlemesi (adapter'a
			ait; kimlik başlıklarını adapter kurar). İstemci içine YALNIZCA
			`integration/secrets.py::collect_secret_values` üzerinden bakar —
			`Password` alanları `get_password()` ile okunur, sütundaki
			`'****'` yer tutucusu redaksiyon varyantı olarak KULLANILMAZ.
		environment: "production" | "test".
		timeout: saniye ya da (bağlantı, okuma) çifti. None → DEFAULT_TIMEOUT.
		retry_policy: yeniden deneme politikası; None → `RetryPolicy()`.
		max_attempts: `retry_policy.max_attempts` için kısayol (ergonomi).
		logger: `integration/log.py::IntegrationLogWriter` Protocol'üne uyan
			yazıcı (`write_integration_log`); None ise loglama no-op.
		circuit_breaker: devre kesiciyi kapatmak için False (testler/tek seferlik işler).
		failure_threshold: devreyi açan ardışık hata sayısı.
		cooldown_sec: devre açık kalma süresi.
		failure_window_sec: hata sayacının yaşam süresi.
		session: hazır `requests.Session` (bağlantı havuzunu paylaşmak için).
			ENJEKTE EDİLEN session `close()` ile KAPATILMAZ — sahibi çağırandır.
		extra_secret_values: Adapter'ın kendi ürettiği kısa ömürlü sırlar (oturum
			jetonu, imza). AYRI KANALDAN loglanır: `credential_doc` çözülemese
			bile uygulanır ve yazıcının "unutuldu" nöbetçisini susturmaz.
		allow_private_hosts: SSRF kapısının IP kontrolünü kapatır. Yalnız sandbox,
			birim testi ve kurum içi uçlar. VARSAYILAN False.
		allow_http: düz `http` şemasına izin verir (test/sandbox uçları).
		allowed_ports: kapının geçireceği portlar; None → `UrlGuard` varsayılanı
			({80, 443}; sandbox modunda kısıt yok).
		max_response_bytes: belleğe alınacak azami gövde.
		max_body_read_sec: gövde okumasının MUTLAK süre bütçesi (slow-loris).
		max_redirects: elle takip edilen azami yönlendirme adımı.
		pool_size: kendi oluşturduğu session için bağlantı havuzu boyutu.
	"""

	def __init__(
		self,
		carrier_code: str,
		*,
		provider: str | None = None,
		credential_doc: dict[str, Any] | None = None,
		environment: str = "production",
		timeout: float | tuple[float, float] | None = None,
		retry_policy: RetryPolicy | None = None,
		max_attempts: int | None = None,
		logger: IntegrationLogWriter | None = None,
		circuit_breaker: bool = True,
		failure_threshold: int = CIRCUIT_FAILURE_THRESHOLD,
		cooldown_sec: int = CIRCUIT_COOLDOWN_SEC,
		failure_window_sec: int = CIRCUIT_FAILURE_WINDOW_SEC,
		session: requests.Session | None = None,
		extra_secret_values: Iterable[Any] | None = None,
		allow_private_hosts: bool = False,
		allow_http: bool = False,
		allowed_ports: Iterable[int] | None = None,
		max_response_bytes: int = MAX_RESPONSE_BYTES,
		max_body_read_sec: float = MAX_BODY_READ_SEC,
		max_redirects: int = DEFAULT_MAX_REDIRECTS,
		pool_size: int = DEFAULT_POOL_SIZE,
	) -> None:
		# NORMALİZASYON TEK OTORİTEDEN (`registry.normalize_carrier_code`). Ölçüldü:
		# istemci ham dizeyi taşıdığı için `ARAS` ile `aras` AYRI devre sayacı
		# tutuyor, arıza sayacı bölünüyor ve devre HİÇ açılmıyordu — oysa iki
		# yazım `get_adapter` tarafından AYNI adapter'a çözülüyor.
		self.carrier_code: str = normalize_carrier_code(carrier_code) or str(carrier_code or "")
		self.provider: str | None = provider
		self.credential_doc: dict[str, Any] | None = credential_doc
		# `None` = "sır VAR ama plaintext'i okunamadı" (bkz. `integration/secrets.py`).
		# O durumda `_log` `secret_values` argümanını HİÇ GEÇMEZ ki yazıcının
		# "unutuldu" uyarısı devreye girsin — yarım küme geçmek guardrail'i
		# susturur ve sistem kendini korunuyor sanır.
		self._secret_values: frozenset[str] | None = collect_secret_values(credential_doc)
		# AYRI KAYNAK, AYRI KANAL: `extra_secret_values` adapter'ın ürettiği kısa
		# ömürlü materyaldir (oturum jetonu, imza) ve taşıyıcının YANITINDA geri
		# döner — denylist'in en kolay atladığı sınıf. Tek argümanda toplandığında
		# credential çözülemeyince O DA DÜŞÜYORDU (ölçüldü:
		# `collect_secret_values(placeholder_doc, extra=['OTURUM_JETONU_777'])`
		# → `None`). Guardrail yalnız `credential_doc` için geçerli olmalı.
		self._extra_secret_values: frozenset[str] = collect_extra_secret_values(extra_secret_values)
		self.environment: str = environment
		self.timeout = timeout  # property setter None'ı DEFAULT_TIMEOUT'a çevirir

		policy = retry_policy or RetryPolicy()
		if max_attempts is not None:
			policy = replace(policy, max_attempts=max_attempts)
		self.retry_policy: RetryPolicy = policy

		# DEVRE KAPSAMI = (kod, ORTAM). Ölçüldü: ortam anahtarda yokken sandbox
		# istemcisinde 2 hata production istemcisini `CIRCUIT_OPEN` ile
		# kesiyordu — sandbox arızası canlı gönderiyi durduruyordu.
		self.breaker: CarrierCircuitBreaker = CarrierCircuitBreaker(
			self.carrier_code,
			environment=self.environment,
			failure_threshold=failure_threshold,
			cooldown_sec=cooldown_sec,
			failure_window_sec=failure_window_sec,
			enabled=circuit_breaker,
		)
		self.max_response_bytes: int = max(1024, int(max_response_bytes))
		self.max_body_read_sec: float = max(0.001, float(max_body_read_sec))
		self.max_redirects: int = max(0, int(max_redirects))
		self.pool_size: int = max(1, int(pool_size))
		self._guard: UrlGuard = UrlGuard(
			allow_private_hosts=allow_private_hosts,
			allow_http=allow_http,
			allowed_ports=allowed_ports,
		)
		self._logger: IntegrationLogWriter | None = logger
		self._session: requests.Session | None = session
		self._owns_session: bool = session is None
		self._pin_adapter: GuardedHTTPAdapter | None = None

		if session is not None:
			_audit_injected_session(carrier_code, session)

		if logger is not None and not provider:
			# Sessiz kalmak, tam da bu dilimde kapatılan arızanın ta kendisiydi.
			_warn(f"CarrierHttpClient({carrier_code!r}): provider verilmedi — entegrasyon logu YAZILMAYACAK.")

		if self._secret_values is None:
			# GÜRÜLTÜLÜ OLMAK ZORUNDA: birincil savunma (değer-tabanlı redaksiyon)
			# bu çağrı için kapalı. `_warn` tek başına yetmez — logger dosyası
			# rotasyona uğrar, Error Log satırı kalır ve sorgulanabilir.
			message = (
				f"CarrierHttpClient({carrier_code!r}): credential_doc'ta DOLU sır alanları var ama "
				"PLAINTEXT'leri okunamadı (Frappe `Password` alanı sütunda `****` tutar; "
				"`get_password()` ile okunabilen bir doküman geçilmeli). Değer-tabanlı "
				"redaksiyon bu istemci için DEVRE DIŞI."
			)
			_warn(message, level="error")
			_safe_log_error(message, "logistics.http_client.secret_values_unresolved")

	@property
	def timeout(self) -> float | tuple[float, float]:
		"""Etkin timeout. `None` atanamaz: transporta None gitmesi işçiyi SÜRESİZ kilitler."""
		return self._timeout

	@timeout.setter
	def timeout(self, value: float | tuple[float, float] | None) -> None:
		"""Yalnız `None` ele alınıyordu; geçersiz değerler 500 üretiyordu.

		ÖLÇÜLDÜ: `0` `_send`'deki `call.timeout or DEFAULT_TIMEOUT` tarafından
		SESSİZCE varsayılana çevriliyordu (çağıranın niyeti değişiyor); `-1`,
		`(0, 0)` ve `'abc'` ise urllib3'te `ValueError` fırlatıp `_perform_attempt`
		tarafından yakalanmıyordu — 500, devre kesiciye kayıt YOK, log YOK.
		"""
		self._timeout = DEFAULT_TIMEOUT if value is None else _validated_timeout(value)

	# -------------------------------------------------------------------
	# Ana giriş noktası
	# -------------------------------------------------------------------

	def request(
		self,
		method: str,
		url: str,
		*,
		operation: str,
		idempotent: bool = False,
		headers: Mapping[str, str] | None = None,
		body: bytes | str | dict[str, Any] | list[Any] | None = None,
		content_type: str | None = None,
		params: Mapping[str, Any] | None = None,
		timeout: float | tuple[float, float] | None = None,
		retry_policy: RetryPolicy | None = None,
		classify: Callable[[CarrierResponse], Outcome] | None = None,
		shipment: str | None = None,
		carrier_account: str | None = None,
	) -> CarrierResponse:
		"""Taşıyıcıya istek gönderir ve HAM yanıtı döndürür.

		`idempotent` bir **yeniden deneme izni**dir: çağıran, isteğin tekrarının
		taşıyıcı tarafında çift kayıt yaratmayacağını taahhüt eder.

		`classify` verilirse sonuç sınıflandırması TAMAMEN devralınır — HTTP 200
		döndürüp gövdede hata bildiren SOAP taşıyıcıları için tek doğru seam
		budur. Fonksiyon `CarrierResponse` alır, `Outcome` döner ve içinden
		fırlayan istisna YUTULMAZ (adapter hatası görünür olmalı).

		Args:
			shipment: korelasyon alanı — yalnız log satırına yazılır.
			carrier_account: korelasyon alanı — yalnız log satırına yazılır.

		Raises:
			LogisticsError: sözleşme dışı `operation`, gövde tipi ya da başlık.
			CarrierTimeoutError: bağlantı/okuma zaman aşımı (denemeler tükendikten sonra).
			CarrierAPIError: ağ hatası, engellenen URL, hatalı yanıt ya da devre açık.
		"""
		self._validate_operation(operation)
		payload, effective_ct = self._prepare_body(body, content_type)
		policy = retry_policy or self.retry_policy
		call = _Call(
			method=method,
			url=url,
			operation=operation,
			headers=self._build_headers(headers, effective_ct),
			payload=payload,
			params=dict(params) if params else None,
			timeout=_validated_timeout(timeout) if timeout is not None else self.timeout,
			policy=policy,
			classify=classify,
			request_body=self._loggable(payload, effective_ct),
			shipment=shipment,
			carrier_account=carrier_account,
		)

		is_probe = self._enter_circuit(call)
		started_all = time.monotonic()
		budget = policy.attempt_budget(idempotent=idempotent)
		try:
			last, last_real, made = self._run_attempts(call, budget, is_probe)
		except LogisticsError:
			# ÇAĞIRAN/YAPILANDIRMA KAYNAKLI HATA (bugün tek örneği: `classify=`
			# callback'inin çöküşü). Taşıyıcı hakkında hiçbir şey KANITLAMAZ:
			# devre sayacına işlenmez — ama yarı-açık deneme hakkını da YAKMAMALI.
			# Yakarsa devre, bizim kendi kodumuzdaki bir hata yüzünden cooldown
			# boyunca HALF_OPEN'da kilitlenir (aynı sınıf arıza, bkz.
			# `record_neutral` docstring'i).
			if is_probe:
				self.breaker.release_probe()
			raise
		if isinstance(last, CarrierResponse):
			return last

		if last_real is not None:
			self.breaker.record(last_real.outcome, is_probe=is_probe)
		elif last is None:
			self.breaker.record(Outcome.UNAVAILABLE, is_probe=is_probe)
		elif is_probe:
			# ÜÇÜNCÜ KATMAN'IN EKSİK YARISI. Daraltılan kapı reddi devre kesiciye
			# HİÇ işlenmez (aşağıdaki gerekçe) — ama probe anahtarı `_enter_circuit`
			# tarafından kapıdan ÖNCE alınmıştı ve geri verilmiyordu: bir kez
			# `base_url` hatalı yazıldığında devre cooldown boyunca HALF_OPEN'da
			# kilitleniyor, sağlıklı taşıyıcıya giden çağrılar `CIRCUIT_OPEN`
			# yiyordu (ölçüldü). İki kapı dalı da aynı davranır — oracle eşitliği
			# bozulmaz.
			self.breaker.release_probe()
		# ÜÇÜNCÜ KATMAN: daraltılan kapı reddi devre kesiciye HİÇ işlenmez. NEUTRAL
		# zaten no-op; bu satır niyeti çağrı yerinde görünür kılar, böylece kapı
		# reddinin devre DURUMUNU değiştirmesi bir daha kazara mümkün olmaz.
		# `last_real` kapı reddinin KENDİSİNİ asla içermez (`collapsed_guard`
		# denemeler ona atanmaz), ama ondan ÖNCEKİ gerçek arızayı içerir ve o
		# arıza her iki kapı dalında da AYNI olduğu için oracle eşitliği bozulmaz.
		elapsed_ms = int((time.monotonic() - started_all) * 1000)
		# `attempts` GERÇEKTEN yapılan deneme sayısı — bütçe değil; 400 tek denemede
		# biter ve telemetri bunu 3 gibi göstermemeli.
		raise self._build_error(last, operation=operation, attempts=made, elapsed_ms=elapsed_ms)

	def _run_attempts(
		self, call: _Call, budget: int, is_probe: bool
	) -> tuple[_Attempt | CarrierResponse | None, _Attempt | None, int]:
		"""Deneme döngüsü. Başarıda `CarrierResponse`, aksi halde son denemeler.

		AYRI METOT ÇÜNKÜ `request()` bu döngüden SIZAN `LogisticsError`'ı yakalayıp
		probe anahtarını iade etmek zorunda; aynı `try` bloğu döngüden SONRAKİ
		`_build_error` çağrısını da kapsasaydı normal hata yolu (CarrierAPIError
		bir `LogisticsError` alt sınıfıdır) yanlışlıkla o dala düşerdi.

		Döner: (son deneme ya da başarı yanıtı, kapı reddi OLMAYAN son deneme,
		gerçekten yapılan deneme sayısı).
		"""
		policy = call.policy
		last: _Attempt | None = None
		#: Kapı reddi OLMAYAN son deneme — devre kesiciye İŞLENECEK olan kanıt.
		#:
		#: `last` daraltılmış bir kapı reddiyse devre kesici hiçbir şey görmüyordu
		#: (`not last.collapsed_guard` koşulu), ama ondan ÖNCEKİ deneme GERÇEK bir
		#: arıza olabilir (1. deneme `ConnectionError` → retriable → 2. denemede
		#: ad iç adrese çözümlenir). Eski kodda o gerçek arıza sayaca hiç
		#: işlenmiyordu: DNS yanıtını değiştirebilen biri gerçek arızaların
		#: sayılmasını bastırabiliyordu (ölçüldü). Kapı reddinin KENDİSİ hâlâ
		#: hiçbir dalda kaydedilmez — iki dal da NEUTRAL ve gözlemlenebilirleri
		#: aynı — yalnız ondan önceki GERÇEK deneme kaydedilir.
		last_real: _Attempt | None = None
		made = 0

		for attempt_no in range(1, budget + 1):
			made = attempt_no
			last = self._perform_attempt(call, attempt_no)
			if not last.collapsed_guard:
				last_real = last
			if not last.failed:
				# Devre sayacı DENEME başına değil, İSTEK başına işlenir: tek bir
				# çağrının 3 denemesi tek bir kanıttır, üç ayrı kanıt değil.
				self.breaker.record(Outcome.HEALTHY, is_probe=is_probe)
				return replace(last.response, attempts=attempt_no), last_real, made  # type: ignore[arg-type]

			if last.collapsed_guard:
				# İKİNCİ KATMAN. Kapı reddinde `Outcome` zaten NEUTRAL (retriable
				# değil), ama deneme SAYISI çağırana `error.attempts` ve
				# `error.elapsed_ms` olarak dönüyor: ileride biri `Outcome`'a ya da
				# `is_retriable`'a dokunursa oracle sessizce geri gelirdi. Daraltılan
				# kapı reddi bu yüzden POLİTİKADAN BAĞIMSIZ olarak tek denemede biter.
				break
			if not policy.is_retriable(last.outcome) or attempt_no >= budget:
				break
			delay = policy.delay_before_retry(attempt_no, last.retry_after)
			if delay is None:
				break  # Firma "çok sonra gel" diyor — işçiyi burada tutmuyoruz.
			_sleep(delay)

		return last, last_real, made

	# -------------------------------------------------------------------
	# Tek deneme
	# -------------------------------------------------------------------

	def _perform_attempt(self, call: _Call, attempt_no: int) -> _Attempt:
		"""Tek HTTP denemesi yapar, sonucu sınıflandırır ve loglar."""
		started = time.monotonic()
		raw: Any = None
		captured: tuple[Any, bytes, bool] | None = None
		result: _Attempt

		try:
			raw, content, truncated = self._send(call)
			captured = (raw, content, truncated)
		except UrlNotAllowedError as exc:
			# KAPI REDDİ TEK SINIFTIR — `Outcome` AYRIMI YOK (bkz. modül docstring'i (6)).
			#
			# Eskiden `URL_UNRESOLVABLE` → `UNAVAILABLE`, `URL_HOST_BLOCKED` → `NEUTRAL`
			# idi ve bu TEK satır ayrımı sistemin her yerine yayıyordu: devre kesici
			# sayacı yalnız çözümlenemeyen adda artıyor, eşikte devre açılıyor ve
			# sonraki çağrı `carrier_error_code="CIRCUIT_OPEN"` ile dönüyordu. Log
			# okuma yetkisi bile gerekmiyordu — çağıran iki kodu doğrudan görüyordu.
			# `base_url`'e yazabilen `Carrier Integration Manager` böylece ad başına
			# temiz 1-bit "bu iç ad DNS'te var mı" haritası çıkarabiliyordu.
			#
			# Kapı reddi zaten "taşıyıcı arızası değil YAPILANDIRMA hatası" sınıfı:
			# çözümlenemeyen bir `base_url` için devreyi açmanın operasyonel değeri
			# yok. İki dal da `NEUTRAL` üretir → devre kesici `record_neutral()`
			# (mutlak no-op) görür, sayaç HİÇBİR dalda ilerlemez, devre kapı reddi
			# yüzünden AÇILMAZ. Ayrım yalnız `_warn` iç telemetrisinde kalır.
			collapsed = exc.guard_code in _COLLAPSED_GUARD_CODES
			# Ayrım (hangi kod, hangi host) İÇ TELEMETRİDE kalır; DocType'a giden
			# satır "bu iç ad var mı / hangi IP'ye çözümlendi" sorularını
			# cevaplamamalı — bkz. modül docstring'i (6).
			_warn(
				f"url_guard_block carrier={self.carrier_code} operation={call.operation} "
				f"code={exc.guard_code}: {exc}",
				level="info",
			)
			result = _Attempt(
				failed=True,
				outcome=Outcome.NEUTRAL,
				error_code=URL_BLOCKED_LOG_CODE if collapsed else exc.guard_code,
				error_message=(
					_("Taşıyıcı adresi giden istek kapısından geçemedi.") if collapsed else str(exc)
				),
				collapsed_guard=collapsed,
			)
		except _BodyReadDeadline:
			result = _Attempt(
				failed=True,
				outcome=Outcome.UNAVAILABLE,
				timed_out=True,
				error_code="BODY_READ_TIMEOUT",
				error_message=_("Taşıyıcı yanıt gövdesi {0} sn süre bütçesini aştı.").format(
					f"{self.max_body_read_sec:g}"
				),
			)
		except requests.Timeout as exc:
			result = _Attempt(
				failed=True,
				outcome=Outcome.UNAVAILABLE,
				timed_out=True,
				error_code="TIMEOUT",
				error_message=_sanitized_transport_error(self.carrier_code, call.operation, exc),
			)
		except requests.RequestException as exc:
			# Ağ katmanı hatası (DNS, bağlantı reddi, TLS) — istek karşıya ULAŞMAMIŞ
			# sayılamaz ama yeniden denenebilir sınıfa girer; çift gönderi riskini
			# çağıranın `idempotent` kararı zaten sınırlıyor.
			result = _Attempt(
				failed=True,
				outcome=Outcome.UNAVAILABLE,
				error_code="NETWORK_ERROR",
				error_message=_sanitized_transport_error(self.carrier_code, call.operation, exc),
			)
		except ValueError as exc:
			# SON ÇARE. urllib3 geçersiz timeout/URL için çıplak `ValueError`
			# fırlatıyor; yakalanmazsa 500'e dönüşüyor, devre kesiciye kayıt
			# düşmüyor ve entegrasyon logu HİÇ yazılmıyordu (ölçüldü).
			result = _Attempt(
				failed=True,
				outcome=Outcome.NEUTRAL,
				error_code="CONFIG_ERROR",
				error_message=_sanitized_transport_error(self.carrier_code, call.operation, exc),
			)
		finally:
			if raw is not None:
				_close_quietly(raw)

		elapsed_ms = int((time.monotonic() - started) * 1000)
		if captured is not None:
			try:
				result = self._classify(call, *captured, elapsed_ms=elapsed_ms)
			except LogisticsError:
				# Zaten sözleşmeye uygun; ikinci kez sarmalamak nedeni gizler.
				self._log_classify_failure(call, captured[0], attempt_no, elapsed_ms)
				raise
			except Exception as exc:
				# ÇAĞIRANIN `classify=` CALLBACK'İ FIRLATTI. Eskiden istisna
				# olduğu gibi dışarı çıkıyordu ve DÖRT şey birden kayboluyordu
				# (ölçüldü): log satırı YAZILMIYOR, devre kesiciye kayıt
				# düşmüyor, yarı-açık probe tükeniyor ve `LogisticsError`
				# hiyerarşisi dışında kaldığı için API zarfı 500 dönüyordu.
				#
				# Modülün her yerde uyguladığı politika (`_prepare_body`,
				# `_validate_operation`, `_validated_timeout` emsali):
				# hiyerarşiye çevir. `classify` ADAPTER kodudur, taşıyıcı arızası
				# değil — bu yüzden 502 değil `LogisticsError` (417) ve devre
				# kesiciye kanıt olarak İŞLENMEZ.
				self._log_classify_failure(call, captured[0], attempt_no, elapsed_ms)
				raise LogisticsError(
					_("Taşıyıcı yanıt sınıflandırıcısı hata verdi ({0}): {1}").format(
						call.operation, type(exc).__name__
					)
				) from exc

		if result.collapsed_guard:
			# İÇ AĞ ORACLE'I — DARALTMA KOMŞU SÜTUNA KAÇMIŞTI (2. turdan beri açık).
			# `error_code` ve `error_message` daraltılmıştı ama ayrım aynı satırın
			# BAŞKA alanlarından okunabiliyordu:
			#   * `is_retriable` = 1 ⟺ ad ÇÖZÜMLENEMEDİ (UNAVAILABLE), 0 ⟺ ad
			#     çözümlendi ama IP iç ağa düştü (NEUTRAL);
			#   * `attempt` — UNAVAILABLE retriable olduğu için `idempotent=True`
			#     çağrılarda max_attempts'e çıkıyor, NEUTRAL'da 1 kalıyordu;
			#   * `duration_ms` — DNS çözümlemesi ile literal IP reddi farklı süre;
			#   * SATIR SAYISI — retriable kod N satır, diğeri 1 satır üretiyordu.
			#   * DEVRE KESİCİ DURUMU (5. tur) — UNAVAILABLE sayacı artırdığı için
			#     eşikten sonra `carrier_error_code="CIRCUIT_OPEN"` dönüyordu; bu
			#     kanal log OKUMA yetkisi bile gerektirmiyordu.
			# `Carrier Integration Manager` hem `base_url`'e yazıyor hem logu
			# okuyor; tehdit modeli kurulu. Ayrım artık KAYNAKTA birleşti: iki dal
			# da `Outcome.NEUTRAL` üretir, tek denemede biter ve devre kesiciye
			# işlenmez (bkz. `_perform_attempt`'in `UrlNotAllowedError` dalı). Bu
			# blok da DocType'a DENEME BAŞINA DEĞİL, ÇAĞRI BAŞINA tek satır yazar.
			# Ayrım iç telemetride (`_warn`, `logistics` logger'ı) gerçek
			# `guard_code` ile durmaya devam eder.
			#
			# KOŞUL `attempt_no == 1` DEĞİL, ÇAĞRI BAŞINA BAYRAK (6. tur): kapı
			# reddi 1. denemeden SONRA gelebiliyor (1. deneme gerçek ağ hatası →
			# retriable → yeniden denenir, 2. denemede ad artık iç adrese
			# çözümlenir). Eski koşulda o satır HİÇ yazılmıyor, yani ENGELLENEN
			# SSRF DENEMESİ denetim izinde görünmüyordu (ölçüldü). Yazılan alanlar
			# `attempt_no`'dan BAĞIMSIZ sabittir (`attempt=1`, `duration_ms=0`,
			# `is_retriable=False`), böylece iki kapı dalının gözlemlenebilirleri
			# BİT BİT aynı kalır.
			if not call.guard_logged:
				call.guard_logged = True
				self._log(
					call,
					succeeded=False,
					http_status=None,
					duration_ms=0,
					attempt=1,
					error_code=result.error_code,
					error_message=result.error_message,
					request_body=call.request_body,
					response_body=None,
					request_headers=call.headers,
					is_retriable=False,
				)
			return result

		self._log(
			call,
			succeeded=not result.failed,
			http_status=result.status,
			duration_ms=elapsed_ms,
			attempt=attempt_no,
			error_code=result.error_code,
			error_message=result.error_message,
			request_body=call.request_body,
			response_body=result.body_text,
			request_headers=call.headers,
			is_retriable=call.policy.is_retriable(result.outcome),
		)
		return result

	def _log_classify_failure(self, call: _Call, raw: Any, attempt_no: int, elapsed_ms: int) -> None:
		"""`classify=` çöküşünü entegrasyon loguna yazar.

		SATIR YAZILMAK ZORUNDA: taşıyıcı yanıt VERDİ (durum kodu elimizde), çöken
		bizim sınıflandırıcımız. Satır olmadan operatörün elinde yalnız bir 500
		kalıyor ve taşıyıcının ne döndüğü hiçbir yerde görünmüyordu. Gövde
		yazılmaz — sınıflandırma yapılamadığı için güvenilir bir `body_text`
		yoktur ve ham gövdeyi bu yoldan geçirmek maskeleme sözleşmesini atlatırdı.
		"""
		self._log(
			call,
			succeeded=False,
			http_status=_status_or_none(raw),
			duration_ms=elapsed_ms,
			attempt=attempt_no,
			error_code="CLASSIFY_ERROR",
			error_message=_("Taşıyıcı yanıt sınıflandırıcısı hata verdi."),
			request_body=call.request_body,
			response_body=None,
			request_headers=call.headers,
			is_retriable=False,
		)

	def _send(self, call: _Call) -> tuple[Any, bytes, bool]:
		"""İsteği gönderir, yönlendirmeleri ELLE takip eder, gövdeyi tavanla okur.

		`allow_redirects=False`: requests'in kendi takibi URL kapısını atlar ve
		çapraz-host yönlendirmede yalnız `Authorization`'ı düşürür — adapter'ın
		koyduğu `X-Api-Key` saldırganın hostuna aynen giderdi.

		Her hop'ta kapının DOĞRULADIĞI IP `GuardedHTTPAdapter`'a pinlenir:
		doğrulanan ad ile bağlanılan ad aynı olur (bkz. adapter docstring'i).
		"""
		method = call.method.upper()
		url = call.url
		headers = dict(call.headers)
		payload = call.payload
		params = call.params
		origin, pin = self._guard.validate_pinned(url)

		try:
			for hop in range(self.max_redirects + 1):
				session = self._get_session()
				self._apply_pin(origin[1], pin)
				raw = session.request(
					method=method,
					url=url,
					headers=headers,
					data=payload,
					params=params,
					timeout=call.timeout,
					allow_redirects=False,
					stream=True,
				)
				redirecting = raw.status_code in _REDIRECT_STATUSES
				location = (raw.headers or {}).get("Location") if redirecting else None
				if not location:
					try:
						content, truncated = _read_capped(
							raw, self.max_response_bytes, self.max_body_read_sec
						)
					except BaseException:
						_close_quietly(raw)
						raise
					return raw, content, truncated

				_close_quietly(raw)
				if hop >= self.max_redirects:
					raise UrlNotAllowedError(
						_("Taşıyıcı yönlendirme sınırını aştı ({0}).").format(self.max_redirects),
						guard_code="URL_INVALID",
					)

				url = urljoin(url, location)
				new_origin, pin = self._guard.validate_pinned(url)
				if new_origin != origin:
					headers = _strip_cross_origin_headers(headers)
					origin = new_origin
				method, payload, headers = _redirect_semantics(raw.status_code, method, payload, headers)
				# Sorgu parametreleri Location'ın kendi query'sinde taşınır; yeniden
				# eklemek hedefi bozar.
				params = None
		finally:
			# Bayat pin bir sonraki isteği YANLIŞ adrese götürürdü.
			if self._pin_adapter is not None:
				self._pin_adapter.clear_pins()

		# Döngü `hop >= max_redirects` dalıyla biter; buraya düşülmez.
		raise UrlNotAllowedError(_("Taşıyıcı yönlendirmesi çözülemedi."), guard_code="URL_INVALID")

	def _apply_pin(self, host: str, address: str | None) -> None:
		"""Kapının doğruladığı adresi transport'a bildirir.

		Enjekte edilmiş session'da adapter bizim değil; pinleme sessizce devre
		dışı kalır (yapıcıda bir kez uyarıldı). Kapı + ASCII reddi yerinde durur.
		"""
		if self._pin_adapter is not None:
			self._pin_adapter.pin(host, address)

	def _classify(
		self,
		call: _Call,
		raw: Any,
		content: bytes,
		truncated: bool,
		*,
		elapsed_ms: int,
	) -> _Attempt:
		"""Yanıtı `Outcome`'a çevirir (varsayılan: HTTP durumu; override: `classify=`)."""
		status = int(raw.status_code)
		headers = dict(raw.headers or {})

		if truncated:
			summary = f"<truncated, >{self.max_response_bytes} bytes>"
			return _Attempt(
				failed=True,
				outcome=Outcome.NEUTRAL,
				status=status,
				error_code="RESPONSE_TOO_LARGE",
				error_message=_("Taşıyıcı yanıtı {0} bayt tavanını aştı.").format(self.max_response_bytes),
				body_text=summary,
			)

		response = CarrierResponse(
			status_code=status,
			headers=headers,
			content=content,
			elapsed_ms=elapsed_ms,
			attempts=1,
			encoding=getattr(raw, "encoding", None),
		)
		body_text = self._loggable(content, headers.get("Content-Type"))
		outcome = call.classify(response) if call.classify else call.policy.classify_status(status)

		if outcome is Outcome.HEALTHY:
			return _Attempt(outcome=outcome, response=response, status=status, body_text=body_text)

		if outcome is Outcome.UNAVAILABLE:
			message = _("Taşıyıcı geçici hata döndürdü: HTTP {0}").format(status)
		else:
			message = _("Taşıyıcı isteği reddetti: HTTP {0}").format(status)

		return _Attempt(
			outcome=outcome,
			response=response,
			failed=True,
			status=status,
			# 2xx/3xx + hata gövdesi senaryosunda `HTTP_200` yanıltıcı olurdu.
			error_code=f"HTTP_{status}" if status >= 400 else "CARRIER_REJECTED",
			error_message=message,
			retry_after=_parse_retry_after(headers.get("Retry-After")),
			body_text=body_text,
		)

	# -------------------------------------------------------------------
	# Devre kesici köprüsü (durum yönetimi resilience/circuit_breaker.py'de)
	# -------------------------------------------------------------------

	def _enter_circuit(self, call: _Call) -> bool:
		"""Devre kapısı. Açıksa hemen reddeder; yarı-açık probe ise True döner."""
		state = self.breaker.state()
		if state is CircuitState.CLOSED:
			return False
		if state is CircuitState.HALF_OPEN and self.breaker.acquire_probe():
			return True

		reason = _("{0} taşıyıcısı için devre kesici açık — çağrı denenmeden reddedildi.").format(
			self.carrier_code
		)
		# Cooldown boyunca DocType'a TEK satır: devre kesicinin amacı yükü kesmek,
		# HTTP'den tasarruf edilen yükü log tablosuna aktarmak değil. Kalan retler
		# ucuz logger'a düşer.
		#
		# Anahtar YALNIZCA gerçekten yazabilecekken talep edilir: logger ya da
		# provider yoksa `_log` hiçbir şey yazmıyor ama notice anahtarı harcanmış
		# oluyordu. Kazanan YAZAMAZSA anahtar geri verilir — aksi halde cooldown
		# boyunca hiç satır kalmıyor ve kimse yeniden deneyemiyordu.
		can_log = self._logger is not None and bool(self.provider)
		if can_log and self.breaker.claim_open_notice():
			written = self._log(
				call,
				succeeded=False,
				http_status=None,
				duration_ms=0,
				attempt=0,
				error_code="CIRCUIT_OPEN",
				error_message=reason,
				request_body=call.request_body,
				response_body=None,
				request_headers=call.headers,
				is_retriable=True,
			)
			# ANAHTARI GERİ VERME DE KISILIR: arıza KALICI ise her istek yeniden
			# claim edip yeniden düşüyor ve her tur bir rapor üretiyordu. Aynı
			# cooldown penceresinde birkaç denemeden sonra anahtar bırakılmaz;
			# devre kesicinin "cooldown başına tek satır" sözü korunur ve log
			# katmanı kendi kendini boğmaz.
			if not written and should_report(f"open_notice:{self.carrier_code}", _OPEN_NOTICE_RETRY_LIMIT):
				self.breaker.release_open_notice()
		else:
			_warn(f"circuit_open carrier={self.carrier_code} operation={call.operation}", level="info")

		error = CarrierAPIError(reason)
		error.carrier = self.carrier_code
		error.provider = self.provider
		error.operation = call.operation
		error.carrier_status = None
		error.carrier_error_code = "CIRCUIT_OPEN"
		error.attempts = 0
		error.elapsed_ms = 0
		raise error

	def reset_circuit(self) -> None:
		"""Devre durumunu sıfırlar (admin "bağlantıyı test et" akışı ve testler)."""
		self.breaker.reset()

	# -------------------------------------------------------------------
	# Gövde / başlık hazırlığı
	# -------------------------------------------------------------------

	@staticmethod
	def _prepare_body(
		body: bytes | str | dict[str, Any] | list[Any] | None,
		content_type: str | None,
	) -> tuple[bytes | None, str | None]:
		"""Gövdeyi tel formatına çevirir.

		`bytes`/`str` DOKUNULMADAN geçer — SOAP zarfı, imzalı XML veya firma-özel
		encoding bozulmamalı. `dict`/`list` yalnızca KOLAYLIK olsun diye JSON'a
		çevrilir; bu istemcinin varsayılan taşıması JSON DEĞİLDİR.

		Raises:
			LogisticsError: desteklenmeyen gövde tipi. Çıplak `TypeError` DEĞİL —
				`LogisticsError` hiyerarşisi dışındaki istisnalar
				`logistics_endpoint` zarfına takılmaz ve 500 olarak yansırdı.
		"""
		if body is None:
			return None, content_type
		if isinstance(body, bytes):
			return body, content_type
		if isinstance(body, str):
			return body.encode("utf-8"), content_type
		if isinstance(body, (dict, list)):
			return (
				json.dumps(body, ensure_ascii=False).encode("utf-8"),
				content_type or "application/json; charset=utf-8",
			)
		raise LogisticsError(_("Desteklenmeyen gövde tipi: {0}").format(type(body).__name__))

	def _build_headers(self, headers: Mapping[str, str] | None, content_type: str | None) -> dict[str, str]:
		"""Başlıkları birleştirir ve doğrular (ad + değer + sahiplik).

		Değer kontrolü ALLOWLIST: eski denylist (`ord < 32 or == 127`) U+0085'i
		(NEL — latin-1'de 0x85 olarak tele çıkar), U+2028 ve U+2029'u geçiriyordu.
		Transport'un kendi ürettiği başlıklar (`Host`, `Content-Length`,
		`Transfer-Encoding`, …) çağırandan hiç kabul edilmez.
		"""
		merged: dict[str, str] = {"User-Agent": f"TradeHub-Logistics/1.0 ({self.environment})"}
		for key, value in (headers or {}).items():
			name = str(key)
			text = str(value)
			if not _HEADER_NAME_RE.match(name):
				raise LogisticsError(_("Geçersiz HTTP başlık adı: {0}").format(name[:64]))
			if name.lower() in _TRANSPORT_OWNED_HEADERS:
				raise LogisticsError(_("Bu HTTP başlığını transport belirler: {0}").format(name))
			if not _HEADER_VALUE_RE.match(text):
				raise LogisticsError(_("HTTP başlık değeri kontrol karakteri içeremez: {0}").format(name))
			merged[name] = text
		if content_type and not any(k.lower() == "content-type" for k in merged):
			merged["Content-Type"] = content_type
		return merged

	@staticmethod
	def _loggable(payload: bytes | None, content_type: str | None) -> str | None:
		"""Gövdeyi log alanına (Code) yazılabilir metne çevirir.

		Maskeleme BURADA YAPILMAZ — log katmanı merkezî olarak maskeler. Yalnızca
		ikili içerik elenir: etiket PDF'ini metne çevirmek log tablosunu çöple
		doldurur ve hiçbir şey ifade etmez. Özet biçimi `masking._mask_bytes` ile
		HİZALI (`<binary N bytes>`); content-type biliniyorsa eklenir.
		"""
		if not payload:
			return None
		hint = (content_type or "").split(";")[0].strip().lower()
		if hint and not any(token in hint for token in _TEXTUAL_CONTENT_HINTS):
			return f"<binary {len(payload)} bytes, {hint}>"
		try:
			return payload.decode("utf-8")
		except UnicodeDecodeError:
			return f"<binary {len(payload)} bytes>"

	@staticmethod
	def _validate_operation(operation: str) -> None:
		"""Sözleşme dışı `operation`'ı reddeder.

		`LogisticsError` fırlatılır (çıplak `ValueError` değil): lojistik
		hiyerarşisi dışındaki istisnalar API zarfında 500'e dönüşür.
		"""
		if operation not in VALID_OPERATIONS:
			raise LogisticsError(
				_("Geçersiz operation {0}; sözleşme değerleri: {1}").format(
					operation, ", ".join(sorted(VALID_OPERATIONS))
				)
			)

	# -------------------------------------------------------------------
	# Hata üretimi
	# -------------------------------------------------------------------

	def _build_error(
		self,
		attempt: _Attempt | None,
		*,
		operation: str,
		attempts: int,
		elapsed_ms: int,
	) -> CarrierAPIError:
		"""Son denemeyi lojistik exception'ına çevirir.

		İSTİSNAYA HAM YANIT İLİŞTİRİLMEZ. Eskiden `error.response` tüm gövde
		baytlarını ve tüm yanıt başlıklarını (`Set-Cookie`, oturum jetonu)
		taşıyordu; `frappe.log_error(frappe.get_traceback())` çağıran herhangi
		bir üst katman maskelenmemiş taşıyıcı gövdesini Error Log'a düşürürdü.
		Gövdeye ihtiyaç duyan adapter onu NORMAL dönüş yolundan almalı — bunun
		için `classify=` ile "bu durum başarıdır" demek yeterli.

		Kullanıcıya dönen mesaj da taşıyıcı detayı TAŞIMAZ: requests'in hata
		metni query string'deki credential'ı içerebiliyor ve bu metin 502 yanıt
		gövdesine çıkıyordu. Operatör detayı yalnız log satırında kalır.

		`http_status_code` SINIF niteliği (502/504) EZİLMEZ — o, bizim API'mizin
		istemciye döneceği durum. Taşıyıcının durumu ayrı bir örnek niteliğinde
		(`carrier_status`) taşınır.
		"""
		timed_out = bool(attempt and attempt.timed_out)
		exc_cls = CarrierTimeoutError if timed_out else CarrierAPIError
		message = _("{0} taşıyıcı çağrısı başarısız ({1}).").format(self.carrier_code, operation)

		error = exc_cls(message)
		error.carrier = self.carrier_code
		error.provider = self.provider
		error.operation = operation
		error.carrier_status = attempt.status if attempt else None
		error.carrier_error_code = attempt.error_code if attempt else None
		error.attempts = attempts
		error.elapsed_ms = elapsed_ms
		return error

	# -------------------------------------------------------------------
	# Log köprüsü
	# -------------------------------------------------------------------

	def _log(self, call: _Call, **kwargs: Any) -> bool:
		"""Enjekte edilen log yazıcısını çağırır. Döner: satır GERÇEKTEN YAZILDI mı.

		`carrier` alanına `provider` (Logistics Provider docname) gider,
		`carrier_code` DEĞİL — bkz. modül docstring'i "iki ayrı kimlik uzayı".

		Log yazımı ana akışı ASLA kırmamalı: entegrasyon logu bir gözlemlenebilirlik
		aracı, gönderi oluşturmanın önkoşulu değil. Ama SESSİZ de olmamalı:
		`claim_open_notice` kazananının logu düşerse cooldown boyunca hiçbir
		satır kalmıyordu, bu yüzden başarı bilgisi çağırana DÖNER.

		İKİ BAŞARISIZLIK KANALI VAR ve ikisi de okunur: (a) istisna — SÖZLEŞME
		DIŞI ama savunma olarak duruyor, (b) `None` dönüşü — `IntegrationLogWriter`
		sözleşmesinin TEK meşru başarısızlık bildirimi. (b) okunmadığı sürece bu
		metot koşulsuz True dönüyordu (ölçüldü).
		"""
		if self._logger is None or not self.provider:
			return False
		if self._secret_values is not None:
			# Küme çözülemediyse argüman HİÇ GEÇİLMEZ: `write_integration_log`'un
			# "`secret_values` unutuldu" nöbetçisi ancak böyle tetiklenir. Yarım
			# (ya da yer tutucu dolu) bir küme geçmek o uyarıyı susturur ve
			# birincil savunmanın kapalı olduğu görünmez olurdu — ölçülmüş arıza.
			kwargs["secret_values"] = self._secret_values
		if self._extra_secret_values:
			# Adapter jetonu AYRI kanaldan gider: `secret_values` hiç geçilmese
			# bile redakte edilir ve nöbetçiyi SUSTURMAZ.
			kwargs["extra_secret_values"] = self._extra_secret_values
		try:
			written = self._logger(
				carrier=self.provider,
				direction="outbound",
				operation=call.operation,
				shipment=call.shipment,
				carrier_account=call.carrier_account,
				**kwargs,
			)
		except Exception as exc:  # noqa: BLE001 — gerekçe yukarıda
			# Gözlemlenebilirlik katmanının kendisi çökmüşse `_warn` yeterli
			# değil: kalıcı bir kayıt (traceback'li) olmadan bu arıza fark
			# edilmiyordu.
			_report_log_failure(self.carrier_code, call.operation, exc)
			return False
		# YAZICININ ASIL BAŞARISIZLIK KANALI DÖNÜŞ DEĞERİDİR. `write_integration_log`
		# sözleşme gereği ASLA FIRLATMAZ (bkz. `IntegrationLogWriter` docstring'i:
		# "Dönüş: oluşan log kaydının adı; yazılamadıysa `None`. **Asla
		# fırlatmaz.**") — yani yukarıdaki `except` gerçek yazıcıda HİÇ tetiklenmez
		# ve dönüş atıldığı sürece bu metot koşulsuz True dönüyordu (ölçüldü:
		# sözleşmeye uyan, `None` dönen bir yazıcıyla `_log` → True). Sonuç:
		# `_enter_circuit`'in "kazanan yazamadıysa anahtarı geri ver" dalı
		# ERİŞİLEMEZDİ; devre-açık bildirimi düşen bir cooldown boyunca DocType'ta
		# HİÇ satır kalmıyor ve kimse yeniden deneyemiyordu.
		#
		# BURADA AYRICA RAPOR YAZILMAZ: `write_integration_log` kendi arızasını
		# zaten `safe_log_error` ile kalıcı olarak kaydediyor; ikinci bir kayıt
		# aynı olayı çift sayardı. Kısılmış raporlama yalnız SÖZLEŞME İHLALİ olan
		# (fırlatan) yazıcılar için yukarıdaki dalda kalır.
		return written is not None

	# -------------------------------------------------------------------
	# Oturum yönetimi
	# -------------------------------------------------------------------

	def _get_session(self) -> requests.Session:
		"""Bağlantı havuzu için örnek başına tek Session.

		Transport katmanına retry MOUNT EDİLMEZ — yeniden denemeyi bu sınıf
		yönetir (bkz. modül docstring'i). Yalnız havuz boyutu ayarlanır:
		varsayılan `pool_maxsize=10` aşıldığında requests bağlantıyı atıp
		yenisini açar ve TLS el sıkışması her çağrıda tekrarlanır.

		`trust_env=False` GÜVENLİK KARARIDIR, ergonomi değil: ortamdaki
		`HTTPS_PROXY` SSRF kapısının IP kararını tamamen geçersiz kılıyordu
		(ölçüldü — kapı 8.8.8.8'i doğruladı, trafik `127.0.0.1:8123` proxy'sine
		gitti) ve `REQUESTS_CA_BUNDLE` TLS güven deposunu değiştirebiliyordu.
		"""
		if self._session is None:
			session = requests.Session()
			session.trust_env = False
			session.proxies = {}
			session.verify = True  # Açıkça: sertifika doğrulaması kapatılamaz.
			adapter = GuardedHTTPAdapter(pool_connections=self.pool_size, pool_maxsize=self.pool_size)
			session.mount("https://", adapter)
			session.mount("http://", adapter)
			self._session = session
			self._owns_session = True
			self._pin_adapter = adapter
		return self._session

	def close(self) -> None:
		"""Kendi oluşturduğu session'ı kapatır. ENJEKTE EDİLENE DOKUNMAZ.

		Havuzu paylaşmak için session veren çağıran onu başka istemcilerle de
		kullanıyor olabilir; `with` bloğundan çıkmak onun havuzunu kapatmamalı.
		"""
		if self._owns_session and self._session is not None:
			self._session.close()
			self._session = None

	def __enter__(self) -> CarrierHttpClient:
		return self

	def __exit__(self, *exc_info: Any) -> None:
		self.close()

	def __repr__(self) -> str:
		return (
			f"<CarrierHttpClient carrier={self.carrier_code!r} "
			f"provider={self.provider!r} env={self.environment!r}>"
		)


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _sleep(seconds: float) -> None:
	"""Yeniden denemeler arası bekleme.

	Ayrı fonksiyon: testler `time.sleep`'i GLOBAL olarak patch'lemek zorunda
	kalmasın (aynı modül nesnesi tüm süreçte paylaşılıyor); bu isim modüle özel.
	"""
	time.sleep(seconds)


def _warn(message: str, *, level: str = "warning") -> None:
	"""`logistics` logger'ına yazar; logger'ın kendisi yoksa sessiz geçer."""
	try:
		getattr(frappe.logger("logistics"), level)(message)
	except Exception:  # noqa: BLE001 — uyarı yolu ana akışı düşüremez
		pass


def _status_or_none(raw: Any) -> int | None:
	"""Ham yanıtın durum kodu; okunamıyorsa None (log yolu düşmemeli)."""
	try:
		return int(raw.status_code)
	except (AttributeError, TypeError, ValueError):
		return None


def _close_quietly(raw: Any) -> None:
	"""Akış hâlindeki yanıtı kapatır; kapatma hatası çağrıyı düşürmez."""
	try:
		raw.close()
	except Exception:  # noqa: BLE001 — bağlantı zaten kopmuş olabilir
		pass


def _read_capped(raw: Any, cap: int, max_seconds: float = MAX_BODY_READ_SEC) -> tuple[bytes, bool]:
	"""Gövdeyi BAYT ve SÜRE tavanıyla okur. Döner: (içerik, kırpıldı_mı).

	Üç katmanlı savunma: (1) beyan edilen `Content-Length` tavanı aşıyorsa tek
	bayt bile okunmaz, (2) beyan yalan olabilir (chunked encoding'de zaten yok),
	bu yüzden akış sayılarak okunur ve tavanı aşan ilk parçada bırakılır,
	(3) MUTLAK SON TARİH — bayt saymak slow-loris'i durdurmuyor: requests/urllib3
	okuma timeout'unu SOKET OKUMASI BAŞINA uygular, saniyede 1 bayt gönderen
	sunucu onu her seferinde sıfırlar (ölçüldü: `timeout=(3,5)` ile 6 baytlık
	gövde 12,04 sn, timeout hiç tetiklenmedi). `base_url` saldırgan kontrolünde
	olduğu için birkaç eşzamanlı çağrı tüm RQ işçilerini tüketebilirdi.

	Kırpılmışsa içerik BOŞ döner — yarım gövdeyi adapter'a vermek onu sessizce
	yanlış ayrıştırmaya iterdi; `RESPONSE_TOO_LARGE` hatası dürüst olan.

	Raises:
		_BodyReadDeadline: toplam okuma süresi `max_seconds`'ı aştı.
	"""
	declared = _content_length(raw.headers)
	if declared is not None and declared > cap:
		return b"", True

	deadline = time.monotonic() + max_seconds
	chunks: list[bytes] = []
	total = 0
	for chunk in _iter_body(raw, _READ_CHUNK_BYTES):
		# SON TARİH ÖNCE, `continue`'dan ÖNCE — ölçülmüş delik: kontrol boş parça
		# atlamasının ALTINDAYDI, yani yalnız `b''` üreten bir akışta bütçe HİÇ
		# ateşlenmiyordu (ölçüldü: 1,0 sn boyunca boş parça üreten sahte yanıtta
		# `max_seconds=0.05` ile istisna ancak ilk DOLU parçada, 1,0 sn sonra
		# atıldı). `read1` geçişinin kapatmak istediği slow-loris yüzeyi tam da
		# `iter_content` düşüş yolunda açık kalmıştı.
		if time.monotonic() > deadline:
			# Bağlantıyı çağıran kapatır (`_send` → `_close_quietly`).
			raise _BodyReadDeadline(f"carrier body read exceeded {max_seconds:g}s")
		if not chunk:
			continue
		total += len(chunk)
		if total > cap:
			return b"", True
		chunks.append(chunk)
	return b"".join(chunks), False


def _iter_body(raw: Any, chunk_size: int) -> Iterator[bytes]:
	"""Gövdeyi soketten VERİ GELDİKÇE parça parça verir.

	`iter_content(chunk_size=N)` N BAYT DOLANA ya da EOF'a KADAR BLOKE OLUR —
	altındaki `BufferedReader.read(N)` böyle çalışır. Yani saniyede 1 bayt
	gönderen bir sunucuda TEK bir `iter_content` adımı 64 KiB için saatler
	sürer ve parçalar ARASINA konan süre kontrolü hiç çalışmaz (ölçüldü: süre
	bütçesi eklendikten sonra bile istek kesilmedi). urllib3 2.x'in `read1()`'i
	veri gelir gelmez döner; bütçe ancak böyle uygulanabilir.

	`decode_content=True`: yanıt boyutu tavanı ÇÖZÜLMÜŞ bayt üzerinden sayılmaya
	devam eder — gzip bombası savunması buna dayanıyor.

	`read1` yoksa (sahte yanıt nesneleri, eski urllib3) `iter_content`'a düşülür;
	o yolda bütçe parça granülaritesinde uygulanır. DÜŞÜŞ SESSİZ DEĞİL: slow-loris
	savunmasının granülaritesi düştüğü için bir kez kalıcı olarak raporlanır —
	`requests`/`urllib3` sürüm yükseltmesi bu iç yüzeyi uyarısız kaldırabilir ve
	savunma görünmez şekilde devre dışı kalırdı (bkz. `pyproject.toml` taban
	sürümleri ve `test_carrier_http_client` smoke testi).

	BOŞ `read1` DÖNÜŞÜ EOF DEĞİLDİR: `decode_content=True` ile decoder bir turda
	çıktı üretmeyebilir. Eskiden ilk boş dönüşte `return` ediliyor ve gövde
	SESSİZCE kırpılıyordu. Artık gerçek EOF sorulur; emin olunamıyorsa sınırlı
	sayıda boş tur tolere edilir (süre bütçesi zaten koruyor).
	"""
	stream = getattr(raw, "raw", None)
	read1 = getattr(stream, "read1", None)
	if not callable(read1):
		report_throttled(
			"iter_body_read1_missing",
			"CarrierHttpClient `raw.read1` bulamadı; gövde okuması `iter_content`'a düştü. "
			"Slow-loris süre bütçesi artık parça granülaritesinde uygulanıyor "
			f"(yanıt tipi={type(raw).__name__}, akış tipi={type(stream).__name__}). "
			"`requests>=2.32` + `urllib3>=2` tabanını doğrulayın.",
			"logistics.http_client.read1_unavailable",
		)
		yield from raw.iter_content(chunk_size=chunk_size)
		return

	empty_rounds = 0
	while True:
		chunk = read1(chunk_size, decode_content=True)
		if chunk:
			empty_rounds = 0
			yield chunk
			continue
		if _stream_at_eof(stream) or empty_rounds >= _MAX_EMPTY_READS:
			return
		empty_rounds += 1
		# Boş parça BİLEREK yukarı verilir: `_read_capped` süre bütçesini parça
		# başında kontrol ediyor, döngüde sessizce beklemek onu atlatırdı.
		yield b""


def _stream_at_eof(stream: Any) -> bool:
	"""Akış GERÇEKTEN bitti mi? Bilinemiyorsa False (çağıran tur sayar).

	`urllib3.HTTPResponse` hem `isclosed()` (http.client mirası) hem `closed`
	taşır. Sahte test nesnelerinde ikisi de olmayabilir; o durumda "bitmedi"
	demek güvenlidir çünkü `_MAX_EMPTY_READS` ve süre bütçesi sınırlıyor.
	"""
	probe = getattr(stream, "isclosed", None)
	if callable(probe):
		try:
			return bool(probe())
		except Exception:  # noqa: BLE001 — bağlantı zaten kopmuş olabilir
			return True
	closed = getattr(stream, "closed", None)
	return closed if isinstance(closed, bool) else False


def _usable_encoding(encoding: str | None) -> str | None:
	"""Saldırgan kontrollü charset'i doğrular; kullanılamazsa None.

	`Content-Type; charset=` doğrudan taşıyıcıdan geliyor. `codecs.lookup`
	tanımayan bir adı `LookupError` ile reddeder; ayrıca `base64`/`zlib` gibi
	BAYT→BAYT codec'leri de eleniyor — `bytes.decode()` onları zaten reddediyor
	ve aynı `LookupError`'a düşerdi.
	"""
	if not encoding:
		return None
	try:
		info = codecs.lookup(str(encoding))
	except (LookupError, TypeError, ValueError):
		return None
	if not getattr(info, "_is_text_encoding", True):
		return None
	return str(encoding)


def _validated_timeout(value: Any) -> float | tuple[float, float]:
	"""Transporta gitmeden önce timeout'u doğrular.

	Raises:
		LogisticsError: çıplak `ValueError` DEĞİL — lojistik hiyerarşisi
			dışındaki istisnalar `logistics_endpoint` zarfına takılmaz ve
			500 olarak yansırdı.
	"""
	if isinstance(value, tuple):
		if len(value) != 2:
			raise LogisticsError(_("timeout çifti (bağlantı, okuma) biçiminde olmalı."))
		return (_positive_seconds(value[0]), _positive_seconds(value[1]))
	return _positive_seconds(value)


def _positive_seconds(value: Any) -> float:
	"""Pozitif, sonlu bir saniye değeri döndürür."""
	if isinstance(value, bool) or not isinstance(value, (int, float)):
		raise LogisticsError(_("timeout sayı olmalı: {0}").format(type(value).__name__))
	number = float(value)
	# `number != number` → NaN. `0` da reddedilir: eskiden `or DEFAULT_TIMEOUT`
	# tarafından sessizce varsayılana çevriliyor, çağıranın niyeti değişiyordu.
	if number != number or number in (float("inf"), float("-inf")) or number <= 0:
		raise LogisticsError(_("timeout sıfırdan büyük olmalı: {0}").format(value))
	return number


def _sanitized_transport_error(carrier_code: str, operation: str, exc: BaseException) -> str:
	"""Transport istisnasını LOGA YAZILABİLİR özete indirger.

	`str(exc)` URL'i (query string'deki credential dahil), host'u ve PORTU
	taşıyor. Ölçüldü: açık iç port → `SSLError: ...`, kapalı port →
	`ConnectionError: ... NewConnec...` — `Carrier Integration Log`'u okuyabilen
	rol için tam bir iç port tarayıcısıydı. Ham metin yalnız iç telemetriye
	(logistics logger'ı) gider.
	"""
	_warn(f"carrier_transport_error carrier={carrier_code} operation={operation}: {exc}")
	return _("Taşıyıcıya erişilemedi ({0}).").format(type(exc).__name__)


def _audit_injected_session(carrier_code: str, session: Any) -> None:
	"""Enjekte edilen session'da beklenmedik transport ayarlarını raporlar.

	Kendi session'ımızı sertleştirmek yetmiyor: havuz paylaşmak için dışarıdan
	verilen bir session `trust_env=True` ya da elle konmuş `proxies` taşıyorsa
	SSRF kapısının IP kararı yine geçersiz kalır. Session'a DOKUNMUYORUZ (sahibi
	çağıran) ama sessiz de kalmıyoruz. IP pinlemesi de bu yolda devre dışıdır.
	"""
	if not isinstance(session, requests.Session):
		return  # Testlerin sahte session'ı — uyarı gürültü olurdu.
	problems: list[str] = []
	if getattr(session, "trust_env", False):
		problems.append("trust_env=True")
	if getattr(session, "proxies", None):
		problems.append("proxies")
	if getattr(session, "verify", True) is not True:
		problems.append("verify!=True")
	detail = ", ".join(problems) if problems else "-"
	_warn(
		f"CarrierHttpClient({carrier_code!r}) enjekte session: ip_pinning=off, beklenmedik={detail}",
		level="warning" if problems else "info",
	)


def _safe_log_error(message: str, title: str) -> None:
	"""`frappe.log_error`'ı yutar — `log.py::safe_log_error` ile AYNI desen.

	NEDEN ORADAN IMPORT EDİLMİYOR (tek meşru kopya): modül docstring'inin 5.
	maddesi bu istemcinin `logistics/integration/log.py`'ye BAĞIMLI OLMAMASINI
	şart koşuyor — log yazıcısı enjekte edilen bir callable'dır, transport onun
	varlığını varsayamaz. Yardımcıyı oradan almak o invaryantı runtime'da
	delerdi (`IntegrationLogWriter` yalnız `TYPE_CHECKING` altında alınıyor,
	tam da bu yüzden).

	`log_error` bir `Error Log` SATIRI yazar; DB yazma katmanı çöktüğünde o da
	patlar ve istisna dışarı sızar. Son çare `_warn`.
	"""
	try:
		frappe.log_error(message, title)
	except Exception:  # noqa: BLE001 — son savunma hattı; buradan çıkış yok
		_warn(message)


def _report_log_failure(carrier_code: str, operation: str, exc: BaseException) -> None:
	"""Entegrasyon logu yazılamadığını KISILMIŞ ve KALICI olarak raporlar.

	Kısma deseni kardeş yoldan (`circuit_breaker._report_fault`) devralınmıştır
	ve artık `resilience/fault_report.py`'de PAYLAŞILIYOR. Burada eksikti ve
	etkisi devre AÇIKKEN katlanıyordu: `_enter_circuit` → `claim_open_notice()`
	True → `_log` düşer → bu fonksiyon → `release_open_notice()` anahtarı SİLER
	→ sonraki istek yeniden claim eder → yine yazar. Kalıcı bir log arızasında
	cooldown başına tek satır yerine İSTEK BAŞINA satır oluşuyordu.
	"""
	report_throttled(
		f"log_failure:{carrier_code}:{operation}",
		f"Entegrasyon logu yazılamadı carrier={carrier_code} operation={operation}: {exc}",
		"logistics.http_client",
	)


def _content_length(headers: Mapping[str, str] | None) -> int | None:
	try:
		raw = (headers or {}).get("Content-Length")
		return int(raw) if raw is not None else None
	except (TypeError, ValueError):
		return None


def _strip_cross_origin_headers(headers: Mapping[str, str]) -> dict[str, str]:
	"""Çapraz-host yönlendirmede kimlik taşıyan başlıkları düşürür."""
	return {key: value for key, value in headers.items() if key.lower() in _SAFE_REDIRECT_HEADERS}


def _redirect_semantics(
	status: int,
	method: str,
	payload: bytes | None,
	headers: dict[str, str],
) -> tuple[str, bytes | None, dict[str, str]]:
	"""301/302/303 → GET'e düşer ve gövdeyi bırakır; 307/308 metodu korur."""
	if status in (307, 308):
		return method, payload, headers
	if method in ("GET", "HEAD"):
		return method, None, headers
	stripped = {key: value for key, value in headers.items() if key.lower() != "content-type"}
	return "GET", None, stripped


def _parse_retry_after(value: str | None) -> float | None:
	"""`Retry-After` başlığını saniyeye çevirir (delta-seconds veya HTTP-date)."""
	if not value:
		return None
	raw = value.strip()
	try:
		return max(0.0, float(raw))
	except ValueError:
		pass
	try:
		parsed: datetime | None = email.utils.parsedate_to_datetime(raw)
	except (TypeError, ValueError):
		return None
	if parsed is None:
		return None
	if parsed.tzinfo is None:
		parsed = parsed.replace(tzinfo=timezone.utc)
	return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())

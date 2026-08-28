# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Giden istek URL kapısı — SSRF savunması (TUR-110).

TEHDİT MODELİ (varsayımsal değil, DocPerm'den okundu):
`Carrier Account.base_url` serbest bir `Data` alanı ve **Carrier Integration
Manager** rolü onu YAZABİLİYOR. AYNI rol `Carrier Integration Log`'u
OKUYABİLİYOR. Kapı olmadan zincir tamdır:

	base_url'i bulut metadata servisine (169.254.169.254) çevir
	→ herhangi bir taşıyıcı çağrısını tetikle
	→ yanıt gövdesini entegrasyon logundan oku

Yani platform içi bir rol, sunucunun iç ağına ve makine kimliğine erişir. Kapı
bu yüzden transport katmanında ve VARSAYILAN AÇIK.

KONTROLLER
	1. Şema: yalnız `https` (sandbox için açık izinle `http`).
	2. Kullanıcı bilgisi (`user:pass@host`) reddedilir — kimlik URL'de taşınmaz.
	3. **Host ASCII olmak ZORUNDA** (bkz. "IDNA" başlığı).
	3a. **Host karakter allowlist'i** — ad için yalnız `[A-Za-z0-9.-]`, IPv6
	   literali için `[0-9A-Fa-f:.]` (bkz. "AYRIŞTIRICI FARKI").
	3b. **Port allowlist'i** — varsayılan {80, 443}. Port `0` sessizce 443'e
	   dönüşüyordu: kapı 443 için karar veriyor, `requests`'e giden URL hâlâ
	   `:0` taşıyordu. Artık `URL_INVALID` ile reddedilir (bkz.
	   `DEFAULT_ALLOWED_PORTS`).
	3c. **Ayrıştırıcı mutabakatı** — kapının çıkardığı (şema, host, port),
	   transport'un (`requests` + `urllib3`) çıkardığıyla KARŞILAŞTIRILIR;
	   eşit değilse ya da transport ayrıştırıcısı istisna atarsa reddedilir
	   (bkz. "AYRIŞTIRICI FARKI").
	4. Host çözümlenir ve DÖNEN TÜM adresler kontrol edilir. Tek bir adres
	   `is_private/is_loopback/is_link_local/is_reserved/is_multicast/
	   is_unspecified` ise ya da `BLOCKED_NETWORKS` listesindeki bir bloğa
	   düşüyorsa istek hiç yapılmaz. "Tümü" şart: bir DNS kaydı hem genel hem
	   127.0.0.1 döndürebilir ve `getaddrinfo` sırası garanti değil.
	5. Yönlendirme kapısı istemcide: `allow_redirects=False` ve her hop bu
	   fonksiyondan yeniden geçer (bkz.
	   `http_client.CarrierHttpClient._send` — yönlendirme takibi orada, ayrı
	   bir `_follow_redirects` metodu YOK).

IDNA — ASCII OLMAYAN HOST NEDEN TAMAMEN REDDEDİLİYOR (ölçülmüş atlatma):
	Kapı `socket.getaddrinfo(host, ...)` çağırıyor; CPython bir `str` host'u
	stdlib **`idna` CODEC**'iyle (IDNA2003 + nameprep) A-label'a çevirir.
	`requests.PreparedRequest.prepare_url` ise **`idna` PAKETİ** ile
	`idna.encode(host, uts46=True)` (IDNA2008/UTS46) yapar. İKİSİ FARKLI
	A-label üretir (konteynerde ölçüldü, Python 3.11.6 / requests 2.33.1 /
	idna 3.18):

		ß.example.com      KAPI=ss.example.com          REQUESTS=xn--zca.example.com
		faß.example.com    KAPI=fass.example.com        REQUESTS=xn--fa-hia.example.com
		ςigma.example.com  KAPI=xn--igma-kod.example... REQUESTS=xn--igma-fod.example...

	Saldırgan kendi alanına iki A kaydı koyar (`ss.attacker.com` → genel bir IP,
	`xn--zca.attacker.com` → 169.254.169.254) ve `base_url`'e `https://ß.attacker.com`
	yazar: kapı GENEL adresi doğrular, istemci İÇ adrese bağlanır. Yarış yok,
	deterministik — bu bir DNS rebinding DEĞİL, kodlama farkıdır.

	İki kütüphaneyi hizalamak (kapıda da `idna.encode(uts46=True)` çağırmak)
	teoride mümkün ama kırılgan: hizalama `requests`/`urllib3`/`idna` sürüm
	üçlüsünün davranışına bağlı kalır ve bir sürüm yükseltmesi sessizce yeniden
	ayırabilir. Taşıyıcı uçları pratikte ASCII (`api.araskargo.com.tr` vb.)
	olduğundan REDDETMEK hem en ucuz hem en dayanıklı seçenek: kapının kararı
	tek bir kütüphanenin yorumuna bağlı kalmaz. IDN'li bir taşıyıcı çıkarsa
	operatör punycode (`xn--…`) biçimini yazar — o zaten ASCII'dir.

AYRIŞTIRICI FARKI — TERS BÖLÜ (`\\`) İLE HOST KAÇIRMA (ölçülmüş atlatma):
	Kapı host'u `urllib.parse.urlsplit` ile çıkarıyordu; `requests`/`urllib3`
	kendi (WHATWG'ye yakın) ayrıştırıcısını kullanır. Ters bölüde ikisi ayrışır:
	`urlsplit` ters bölüyü host adının PARÇASI sayar, `requests` onu yol
	ayracına çevirip ÖNCEKİ kısmı host yapar. Konteynerde ölçüldü
	(Python 3.11.6 / requests 2.33.1 / urllib3 2.7.0):

		'https://169.254.169.254\\.attacker.com/x'  KAPI='169.254.169.254\\.attacker.com'
		                                            REQUESTS='169.254.169.254'
		'https://169.254.169.254\\attacker.com/x'   KAPI='169.254.169.254\\attacker.com'
		                                            REQUESTS='169.254.169.254'

	Uçtan uca kanıt (gerçek joker DNS, `sslip.io`): glibc ters bölülü etiketi
	ÇÖZÜYOR, yani kapının DNS kontrolü de saldırganın seçtiği GENEL adresi görür:

		URL: https://localhost\\x.1.2.3.4.sslip.io/api/ship
		getaddrinfo(...) -> ['1.2.3.4']      → kapı hedefi GENEL sanıp GEÇİRİYOR
		enjekte session'lı istemci -> 127.0.0.1:443 bağlantısı ALINDI

	37 ayraç karakteri × 3 şablon tarandı: kapı/transport 61 kez ayrıştı, 51'i
	kapıdan GEÇİYORDU. Yalnız `\\` uçtan uca sömürülebilirdi (diğerleri
	percent-encode edilip DNS'te düşüyor ya da userinfo/port kontrolüne takılıyor)
	— ama AYRIŞMANIN KENDİSİ hatadır: bir sonraki `urllib3` sürümü başka bir
	karakteri sömürülebilir hâle getirebilir.

	İKİ KATMANLI DÜZELTME (ikisi birlikte):
		(a) Host karakter allowlist'i — `isascii()` çok geniştir, ters bölü
		    ASCII'dir. Ad için yalnız `[A-Za-z0-9.-]`, IPv6 literali için
		    `[0-9A-Fa-f:.]` geçer; bugünkü vektörü kapatır.
		(b) Ayrıştırıcı mutabakatı — kapı, `requests.PreparedRequest.prepare_url`
		    + `urllib3.util.parse_url` ile transport'un GÖRECEĞİ (şema, host, port)
		    üçlüsünü hesaplar ve kendi çıkardığıyla karşılaştırır; fark ya da
		    istisna REDDİR (fail-closed). Bu, GELECEKTEKİ ayrışmaları yakalar.
		(c) Aynı taramada çıktı: `[`/`]` ayraçlarında `urlsplit` KENDİSİ
		    `ValueError("Invalid IPv6 URL")` atıyor ve bu çıplak istisna kapıdan
		    sızıp istemcide `URL_BLOCKED` yerine 500'e dönüşüyordu. Artık
		    `URL_INVALID` reddine çevriliyor.
	Tarama düzeltmeden sonra yeniden koşuldu: kapıdan geçen ayrışmış vektör 0.

DNS REBINDING — KAPATILDI:
	Doğrulama ile bağlantı arasındaki pencere `validate_pinned()` + istemcideki
	`GuardedHTTPAdapter` ile kapatıldı: bağlantı DOĞRULANAN IP'ye kurulur,
	`Host` başlığı ve TLS SNI/sertifika doğrulaması orijinal ADLA yapılır.

	Aynı kök neden — DOĞRULANAN AD ≠ BAĞLANILAN AD — modülde ÜÇ kez çıktı:
	(1) DNS rebinding, (2) IDNA kodlama farkı, (3) ayrıştırıcı farkı (ters bölü).
	Pinleme üçünü de bağlantı anında keser; ama pinleme HER YOLDA AÇIK DEĞİLDİR:
	`session=` enjekte edilmiş istemcide `_apply_pin` no-op olur ve
	`allow_private_hosts=True` sandbox'ta pin zaten üretilmez.

	ÖNCEKİ SÜRÜMDEKİ YANLIŞ İDDİA DÜZELTİLDİ: burada "ASCII reddi pinlemenin
	devre dışı olduğu yollarda da korur" yazıyordu. **Yanlıştı** — ters bölü
	ASCII'dir, `isascii()` kontrolünden geçiyordu ve pinsiz yolda hiçbir savunma
	kalmıyordu (yukarıdaki PoC bunu ölçtü). Pinsiz yolu koruyan şey artık ASCII
	reddi değil, (a) host karakter allowlist'i + (b) ayrıştırıcı mutabakatıdır;
	ikisi de bağlantıdan ÖNCE, kapının kendi içinde çalışır.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable, Iterable, Iterator
from urllib.parse import urlsplit

import requests
import urllib3
from frappe import _

from tradehub_core.logistics.exceptions import CarrierAPIError

__all__ = [
	"BLOCKED_NETWORKS",
	"DEFAULT_ALLOWED_PORTS",
	"URL_GUARD_CODES",
	"UrlGuard",
	"UrlNotAllowedError",
]

#: Kapının ürettiği kararlı hata kodları — log ve telemetri bunlara dallanır.
URL_GUARD_CODES: frozenset[str] = frozenset(
	{"URL_INVALID", "URL_SCHEME_BLOCKED", "URL_HOST_BLOCKED", "URL_UNRESOLVABLE"}
)

_HTTPS_SCHEMES: frozenset[str] = frozenset({"https"})
_HTTP_SCHEMES: frozenset[str] = frozenset({"http", "https"})

#: Şema başına varsayılan port — origin karşılaştırması için.
_DEFAULT_PORTS: dict[str, int] = {"http": 80, "https": 443}

#: Alan adı host'unda İZİN VERİLEN karakterler (LDH + nokta). `isascii()` çok
#: geniştir: ters bölü, boşluk, kontrol karakterleri, `|^{}<>"'`, `_`, `@` hepsi
#: ASCII'dir ve kapıdan geçiyordu — gerekçe modül docstring'inde
#: ("AYRIŞTIRICI FARKI"). Sondaki nokta (kök etiketi) bilinçli olarak serbest.
_HOST_NAME_CHARS: re.Pattern[str] = re.compile(r"\A[A-Za-z0-9.-]+\Z")

#: IPv6 literali için izin verilen karakterler. `urlsplit.hostname` köşeli
#: parantezleri zaten soyar; gövde ayrıca `ipaddress` ile doğrulanır.
_HOST_IPV6_CHARS: re.Pattern[str] = re.compile(r"\A[0-9A-Fa-f:.]+\Z")

#: Kapının geçirdiği portlar. TR kargo uçlarının TAMAMI standart portlarda.
#:
#: ÖLÇÜLMÜŞ AÇIK: kapı port KISITLAMIYORDU. Genel bir IP'nin 22 (SSH),
#: 6379 (Redis), 9200 (Elasticsearch), 11211 (memcached) portlarına istek
#: serbestti — `Carrier Account.base_url`'e yazabilen rol için ucuz bir dış
#: port tarayıcısı ve "yanıtı entegrasyon logundan oku" zincirinin ikinci
#: yarısı. Allowlist, IP kontrolünün kapsamadığı bu ekseni kapatır: adres
#: GENEL olsa bile hedef servis HTTP(S) olmak zorunda.
DEFAULT_ALLOWED_PORTS: frozenset[int] = frozenset({80, 443})

#: `ipaddress` stdlib yüklemlerinin KAPSAMADIĞI ya da Python sürümüne göre
#: DEĞİŞEN bloklar. Güvenlik kararı stdlib yorumuna bırakılamaz: konteyner
#: 3.11.6, production 3.12.3 ve `is_private`/`is_reserved` tanımları sürümler
#: arasında oynuyor. Aşağıdaki liste MODÜLDE SABİT ve sürümden bağımsızdır.
#:
#: Hepsi ölçülerek eklendi — düzeltmeden önce her biri kapıdan GEÇİYORDU.
_BLOCKED_NETWORK_SPECS: tuple[str, ...] = (
	# RFC 6598 CGNAT. Gerçek bir İÇ AĞ aralığı: AWS EKS pod CIDR'ları, GCP,
	# telekom NAT havuzları ve Alibaba Cloud metadata servisi (100.100.100.200).
	"100.64.0.0/10",
	"192.0.0.0/24",  # RFC 6890 IETF protokol atamaları
	"192.31.196.0/24",  # AS112-v4
	"192.52.193.0/24",  # AMT
	"192.88.99.0/24",  # 6to4 relay anycast
	"192.175.48.0/24",  # AS112 doğrudan delegasyon
	"198.18.0.0/15",  # RFC 2544 kıyaslama ağı
	# 6to4: gövdesinde KEYFİ bir IPv4 taşır — `2002:7f00:1::` = 127.0.0.1,
	# `2002:a9fe:a9fe::` = 169.254.169.254. Blok komple kapalı; ayrıca gömülü
	# IPv4 `sixtofour` niteliğiyle açılıp aynı kontrolden geçiriliyor.
	"2002::/16",
	"2001::/32",  # Teredo (gömülü IPv4 `teredo` niteliğiyle ayrıca açılıyor)
	"64:ff9b::/96",  # NAT64 well-known
	"64:ff9b:1::/48",  # NAT64 local-use
	"::/96",  # IPv4-compatible IPv6 (kullanımdan kalktı ama hâlâ çözümlenir)
)

#: Yüklenmiş hâli — modül import'unda bir kez kurulur.
BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = tuple(
	ipaddress.ip_network(spec) for spec in _BLOCKED_NETWORK_SPECS
)

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class UrlNotAllowedError(CarrierAPIError):
	"""URL kapısı isteği reddetti. `guard_code` reddin sebebini taşır."""

	code = "CARRIER_URL_BLOCKED"

	def __init__(self, message: str, *, guard_code: str) -> None:
		super().__init__(message)
		self.guard_code: str = guard_code


class UrlGuard:
	"""Bir URL'in dışarıya çıkmaya uygun olup olmadığına karar verir.

	Args:
		allow_private_hosts: True ise HOST/IP kontrolü tamamen atlanır (yalnız
			sandbox, birim testi ve kurum içi taşıyıcı uçları). Şema, kullanıcı
			bilgisi ve ASCII kontrolleri yine uygulanır. VARSAYILAN False.
		allow_http: True ise düz `http` de kabul edilir (test/sandbox uçları).
		allowed_ports: Kabul edilen port kümesi. Verilmezse `DEFAULT_ALLOWED_PORTS`
			({80, 443}); `allow_private_hosts=True` (sandbox) modunda kısıt
			UYGULANMAZ. Açıkça verilen küme her iki modda da geçerlidir.
		resolver: `socket.getaddrinfo` uyumlu çözümleyici. Testler kendi
			sahtesini enjekte edebilsin diye parametre.
	"""

	def __init__(
		self,
		*,
		allow_private_hosts: bool = False,
		allow_http: bool = False,
		allowed_ports: Iterable[int] | None = None,
		resolver: Callable[..., list] | None = None,
	) -> None:
		self.allow_private_hosts: bool = allow_private_hosts
		self.allow_http: bool = allow_http
		# Sandbox modunda (`allow_private_hosts=True`) port kısıtı UYGULANMAZ:
		# kurum içi/test uçları 8080, 8443, 5000 gibi portlarda durur ve o modda
		# zaten hiçbir IP doğrulanmıyor — port allowlist'i orada güvenlik değil
		# yalnız sürtünme üretirdi. Açık yapılandırma her iki modda da geçerlidir.
		self.allowed_ports: frozenset[int] | None = (
			frozenset(int(port) for port in allowed_ports)
			if allowed_ports is not None
			else (None if allow_private_hosts else DEFAULT_ALLOWED_PORTS)
		)
		self._resolver: Callable[..., list] = resolver or socket.getaddrinfo

	@property
	def allowed_schemes(self) -> frozenset[str]:
		return _HTTP_SCHEMES if self.allow_http else _HTTPS_SCHEMES

	def validate(self, url: str) -> tuple[str, str, int]:
		"""URL'i doğrular ve origin üçlüsünü (şema, host, port) döndürür.

		Raises:
			UrlNotAllowedError: şema, kullanıcı bilgisi, host ya da çözümlenen
				IP kabul edilmiyorsa.
		"""
		return self.validate_pinned(url)[0]

	def validate_pinned(self, url: str) -> tuple[tuple[str, str, int], str | None]:
		"""`validate()` + bağlantının kurulacağı DOĞRULANMIŞ IP.

		Returns:
			((şema, host, port), pin). `pin` None ise pinleme uygulanmaz —
			yalnızca `allow_private_hosts=True` (sandbox/test) modunda olur;
			o modda hiçbir IP doğrulanmadığı için pinlemenin güvenlik değeri
			yoktur ve `localhost` gibi adlarda aile seçimini bozardı.

		Raises:
			UrlNotAllowedError: `validate()` ile aynı.
		"""
		try:
			# `urlsplit` KENDİSİ patlayabiliyor ("Invalid IPv6 URL", ör.
			# `https://169.254.169.254[.attacker.com/x`). Çıplak `ValueError`
			# kapıdan sızıp istemcide URL_BLOCKED yerine 500'e dönüşüyordu:
			# ayrıştırılamayan URL de bir REDDİR, istisna değil.
			parts = urlsplit(url or "")
			scheme = (parts.scheme or "").lower()
		except ValueError:
			raise UrlNotAllowedError(
				_("Taşıyıcı URL'i güvenli biçimde ayrıştırılamadı."),
				guard_code="URL_INVALID",
			)

		if scheme not in self.allowed_schemes:
			raise UrlNotAllowedError(
				_("Taşıyıcı uç noktası için izin verilmeyen şema: {0}").format(scheme or "(yok)"),
				guard_code="URL_SCHEME_BLOCKED",
			)

		if parts.username or parts.password:
			raise UrlNotAllowedError(
				_("Taşıyıcı URL'inde kullanıcı bilgisi taşınamaz."),
				guard_code="URL_INVALID",
			)

		host = (parts.hostname or "").strip()
		if not host:
			raise UrlNotAllowedError(_("Taşıyıcı URL'inde host yok."), guard_code="URL_INVALID")

		# ASCII OLMAYAN HOST TAMAMEN REDDEDİLİR — gerekçe modül docstring'inde
		# ("IDNA"): kapı ile `requests` iki FARKLI A-label üretiyor ve kapı
		# deterministik olarak atlatılabiliyordu.
		if not host.isascii():
			raise UrlNotAllowedError(
				_("Taşıyıcı URL'inde ASCII olmayan host kullanılamaz; punycode (xn--) yazın."),
				guard_code="URL_INVALID",
			)

		# ASCII YETMEZ: ters bölü de ASCII'dir ve kapı ile `requests` onu FARKLI
		# ayrıştırıyordu (docstring → "AYRIŞTIRICI FARKI"). Dar allowlist bugünkü
		# vektörü kapatır; aşağıdaki mutabakat kontrolü gelecektekileri yakalar.
		_assert_host_charset(host)

		try:
			# `parts.port or ...` YAZILMAZ: port 0 falsy'dir ve SESSİZCE 443'e
			# dönüşüyordu — kapı 443 için karar veriyor, `requests`'e giden URL
			# ise hâlâ `:0` taşıyordu (kapının doğruladığı hedef ile bağlanılan
			# hedef ayrışıyordu; modülün tüm tehdit modeli bu ayrışmaya dayanıyor).
			explicit = parts.port
		except ValueError:
			raise UrlNotAllowedError(_("Taşıyıcı URL'inde geçersiz port."), guard_code="URL_INVALID")

		if explicit is not None and not 1 <= explicit <= 65535:
			raise UrlNotAllowedError(_("Taşıyıcı URL'inde geçersiz port."), guard_code="URL_INVALID")

		port = explicit if explicit is not None else _DEFAULT_PORTS[scheme]
		if self.allowed_ports is not None and port not in self.allowed_ports:
			raise UrlNotAllowedError(
				_("Taşıyıcı uç noktası için izin verilmeyen port: {0}").format(port),
				guard_code="URL_INVALID",
			)

		origin = (scheme, host.lower(), port)

		# AYRIŞTIRICI MUTABAKATI — kapının doğruladığı hedef ile transport'un
		# BAĞLANACAĞI hedef aynı olmak ZORUNDA. Sandbox (`allow_private_hosts`)
		# ve yönlendirme hop'ları da buradan geçer: `origin` üretilmeden önce.
		_assert_transport_agrees(url or "", origin)

		if self.allow_private_hosts:
			return origin, None
		return origin, self._assert_public_host(host, port)

	# -------------------------------------------------------------------
	# İç yardımcılar
	# -------------------------------------------------------------------

	def _assert_public_host(self, host: str, port: int) -> str:
		"""Host'un TÜM adreslerini doğrular ve bağlanılacak IP'yi döndürür."""
		literal = _as_ip(host)
		if literal is not None:
			self._assert_public_ip(literal, host)
			return str(literal)

		try:
			infos = self._resolver(host, port, proto=socket.IPPROTO_TCP)
		except OSError as exc:
			raise UrlNotAllowedError(
				_("Taşıyıcı adresi çözümlenemedi: {0}").format(type(exc).__name__),
				guard_code="URL_UNRESOLVABLE",
			)

		addresses = [_as_ip(_addr_of(info)) for info in infos or []]
		resolved = [address for address in addresses if address is not None]
		if not resolved:
			raise UrlNotAllowedError(_("Taşıyıcı adresi çözümlenemedi."), guard_code="URL_UNRESOLVABLE")
		for address in resolved:
			self._assert_public_ip(address, host)
		# Sıra `getaddrinfo`'nun sistem tercihidir (IPv6/IPv4 seçimi dahil);
		# hepsi doğrulandığı için ilkini almak güvenli.
		return str(resolved[0])

	@staticmethod
	def _assert_public_ip(address: _IPAddress, host: str) -> None:
		"""Adresi ve İÇİNE GÖMÜLÜ IPv4'leri aynı yasak listesinden geçirir."""
		for candidate in _unwrap(address):
			if not _is_blocked(candidate):
				continue
			# ÇÖZÜMLENEN IP MESAJA YAZILMAZ. Bu metin `_log(error_message=...)`
			# yoluyla `Carrier Integration Log`'a düşüyor ve loga okuma yetkisi
			# olan AYNI rol `base_url`'e yazabiliyor: `internal-db.corp.local`
			# yazıp logdan `→ 10.2.3.4` okumak iç ağ keşif oracle'ıydı. Host bir
			# IP literaliyse zaten saldırganın yazdığı değerdir; ad ise
			# çözümlenen adres onun BİLMEDİĞİ yeni bilgidir.
			raise UrlNotAllowedError(
				_("Taşıyıcı adresi iç ağa işaret ediyor: {0}").format(host),
				guard_code="URL_HOST_BLOCKED",
			)


def _assert_host_charset(host: str) -> None:
	"""Host'u dar bir karakter allowlist'inden geçirir (docstring → "AYRIŞTIRICI FARKI").

	Ad host'u LDH + nokta, IPv6 literali ise onaltılık + `:`/`.` ile sınırlıdır.
	`urlsplit.hostname` köşeli parantezleri soyduğu için IPv6 dalını `:` varlığı
	ayırır; gövde ayrıca `ipaddress` ile doğrulanır ki `a:b` gibi bir metin
	"IPv6" diye kaçmasın.

	Raises:
		UrlNotAllowedError: host allowlist dışı bir karakter taşıyorsa.
	"""
	if ":" in host:
		if _HOST_IPV6_CHARS.match(host) and _as_ip(host) is not None:
			return
	elif _HOST_NAME_CHARS.match(host):
		return
	raise UrlNotAllowedError(
		_("Taşıyıcı URL'inde geçersiz host karakteri var."),
		guard_code="URL_INVALID",
	)


def _assert_transport_agrees(url: str, origin: tuple[str, str, int]) -> None:
	"""Kapının çıkardığı origin ile transport'un çıkardığını karşılaştırır.

	Transport tarafı `requests.PreparedRequest.prepare_url` + `urllib3.util.parse_url`
	ile — yani istemcinin GERÇEKTEN kullanacağı ayrıştırıcılarla — hesaplanır.
	Fark da istisna da REDDİR: kapının kararı, bağlantının kurulacağı hedefle
	ilgisiz kalırsa kapı diye bir şey yoktur.

	Raises:
		UrlNotAllowedError: transport farklı bir (şema, host, port) görüyorsa ya
			da URL'i hiç ayrıştıramıyorsa.
	"""
	scheme, host, port = origin
	try:
		prepared = requests.models.PreparedRequest()
		prepared.prepare_url(url, None)
		parsed = urllib3.util.parse_url(prepared.url or "")
		transport_scheme = (parsed.scheme or "").lower()
		transport_host = (parsed.host or "").strip("[]").lower()
		transport_port = parsed.port
		if transport_port is None:
			transport_port = _DEFAULT_PORTS.get(transport_scheme, -1)
	except Exception:  # noqa: BLE001 — fail-closed: ayrıştıramadığımız URL geçmez.
		raise UrlNotAllowedError(
			_("Taşıyıcı URL'i güvenli biçimde ayrıştırılamadı."),
			guard_code="URL_INVALID",
		)

	if (transport_scheme, transport_host, transport_port) != (scheme, host, port):
		# ÇÖZÜMLENEN/BEKLENEN HOST MESAJA YAZILMAZ — `_assert_public_ip`'deki
		# aynı gerekçe: bu metin entegrasyon loguna düşüyor.
		raise UrlNotAllowedError(
			_("Taşıyıcı URL'i tutarsız ayrıştırılıyor; reddedildi."),
			guard_code="URL_INVALID",
		)


def _is_blocked(address: _IPAddress) -> bool:
	"""Adres yasaklı mı? stdlib yüklemleri + modüldeki SABİT ağ listesi."""
	if (
		address.is_private
		or address.is_loopback
		or address.is_link_local
		or address.is_reserved
		or address.is_multicast
		or address.is_unspecified
	):
		return True
	return any(address in network for network in BLOCKED_NETWORKS if network.version == address.version)


def _unwrap(address: _IPAddress) -> Iterator[_IPAddress]:
	"""Adresin kendisini ve gömülü IPv4'lerini sırayla verir.

	`::ffff:127.0.0.1` (IPv4-mapped) kontrolü atlatmanın klasik yolu; `2002::/16`
	(6to4) ve `2001::/32` (Teredo) ise gövdelerinde KEYFİ IPv4 taşır. Sarmalı
	açmadan yalnız dış adrese bakmak üçünü de kaçırırdı.
	"""
	yield address
	mapped = getattr(address, "ipv4_mapped", None)
	if mapped is not None:
		yield mapped
	sixtofour = getattr(address, "sixtofour", None)
	if sixtofour is not None:
		yield sixtofour
	teredo = getattr(address, "teredo", None)
	if teredo is not None:
		# (sunucu, istemci) çifti — ikisi de iç ağa işaret edebilir.
		yield from teredo


def _as_ip(value: str) -> _IPAddress | None:
	"""Metni IP adresine çevirir; IP değilse None (yani bir alan adı)."""
	try:
		return ipaddress.ip_address(value.strip("[]"))
	except ValueError:
		return None


def _addr_of(info: object) -> str:
	"""`getaddrinfo` girdisinden adres metnini çıkarır."""
	try:
		sockaddr = info[4]  # type: ignore[index]
		return str(sockaddr[0])
	except (IndexError, KeyError, TypeError):
		return ""

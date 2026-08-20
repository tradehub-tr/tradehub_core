"""Faz 5 — Redis-based Rate Limiter.

Endpoint'leri brute-force/spam'a karşı korur. Frappe'in built-in
`frappe.cache` (redis-cache) altyapısını kullanır — ayrı Redis bağlantısı
gerekmez.

Kullanım:
    @rate_limit(max_calls=10, window_seconds=60)
    @frappe.whitelist()
    def my_endpoint(...):
        ...

429-benzeri davranış: limit aşılırsa frappe.throw(TooManyRequestsError).
"""

from __future__ import annotations

import functools
import ipaddress

import frappe
from frappe import _


class TooManyRequestsError(frappe.ValidationError):
	"""HTTP 429 karşılığı Frappe exception."""

	http_status_code = 429


# ---------------------------------------------------------------------------
# T9 — misafir kovası (docs/reports/28-faz13-pentest.md §2)
# ---------------------------------------------------------------------------
# Bulgu: kova `frappe.session.user`a bağlıydı ve misafirde bu değer HER ZAMAN
# "Guest" — IP'den, çerezden, oturumdan bağımsız. Ölçüldü: bir saldırgan
# `sf_submit_review`'in 5 çağrılık penceresini doldurunca TÜM anonim
# ziyaretçiler o pencerede kilitleniyordu (DoS). Etkilenen uçnoktalar
# `allow_guest=True` + `per_user=True` olanlar (storefront_api, social_proof,
# cart, qa, review).
#
# Doğru istemci IP'si NASIL bulunur — ölçülmüş gerekçe:
#   Frappe `frappe.local.request_ip`i `X-Forwarded-For`un EN SOLDAKİ değerinden
#   üretir (frappe/auth.py:64). En sol değer, zincire ilk giren taraf yazdığı
#   için ISTEMCI TARAFINDAN uydurulabilir: saldırgan onu rastgele değiştirip
#   limiti atlar ya da bir kurbanın IP'sini yazıp kurbanı kilitler.
#   Doğrusu, zinciri SAĞDAN SOLA yürüyüp GÜVENİLİR PROXY olmayan ilk adresi
#   almaktır: sağdaki adresleri bizim kendi ters-vekillerimiz yazar, yani
#   uydurulamaz. Güvenilir proxy kümesi varsayılan olarak özel/loopback
#   aralıklarıdır; `site_config.rate_limit_trusted_proxies` ile CIDR listesi
#   verilerek genişletilebilir.
#
# Bu kurulumda ölçülen durum (2026-08-19, `istoc.localhost`):
#   gateway → storefront → frappe-frontend → gunicorn zincirinde
#   `frappe-frontend` nginx'i `proxy_set_header X-Forwarded-For $remote_addr`
#   ile zinciri EZİYOR (frappe.conf `@webserver` bloğu). Gunicorn'a ulaşan
#   X-Forwarded-For tek elemanlı ve içeriği STOREFRONT KONTEYNERİNİN IP'si.
#   Yani istemci IP'si uygulama katmanına HİÇ ulaşmıyor. Bu, sahteciliği
#   engelliyor ama gerçek IP'yi de yok ediyor.
#   Aşağıdaki çözümleyici o durumda `None` döner ve kova
#   "Guest:_unresolved" olur — yani bugünkü topolojide misafir DoS'u
#   uygulama katmanından TAM kapanmaz. Kapanması için altyapıda tek satırlık
#   değişiklik gerekir (frappe-frontend konteynerine
#   `UPSTREAM_REAL_IP_ADDRESS=<docker subnet CIDR>` +
#   `UPSTREAM_REAL_IP_RECURSIVE=on` env'leri; nginx-entrypoint.sh bunları
#   `set_real_ip_from` / `real_ip_recursive` olarak şablona basıyor).
#   Detay ve kanıt: docs/reports/29-pentest-duzeltmeleri.md §T9.

#: Ters-vekil olduğu varsayılan ağlar. Bu aralıklardan gelen bir adres
#: "istemci kimliği" sayılmaz — zincirde onun SOLUNA bakılır.
_DEFAULT_TRUSTED_PROXY_NETS: tuple[str, ...] = (
	"127.0.0.0/8",  # loopback
	"::1/128",
	"10.0.0.0/8",  # RFC1918
	"172.16.0.0/12",
	"192.168.0.0/16",
	"100.64.0.0/10",  # RFC6598 CGNAT — konteyner/bulut iç ağı
	"169.254.0.0/16",  # link-local
	"fc00::/7",  # IPv6 ULA
	"fe80::/10",  # IPv6 link-local
)

_UNRESOLVED_IP = "_unresolved"


def _trusted_proxy_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
	"""Güvenilir ters-vekil ağları — istek kapsamında önbellekli.

	`site_config.rate_limit_trusted_proxies` bir CIDR listesi ile varsayılanı
	GENİŞLETİR (değiştirmez): konteyner ağları zaten özel aralıkta, ek olarak
	yalnız public bir CDN/edge aralığı eklenmesi beklenir.
	"""

	def _build():
		raw = list(_DEFAULT_TRUSTED_PROXY_NETS)
		extra = frappe.conf.get("rate_limit_trusted_proxies") or []
		if isinstance(extra, str):
			extra = [extra]
		nets = []
		for cidr in [*raw, *extra]:
			try:
				nets.append(ipaddress.ip_network(str(cidr).strip(), strict=False))
			except ValueError:
				# Hatalı CIDR sessizce atlanır ama görünür kalsın — bu liste
				# yanlışsa hız sınırı yanlış kimliğe bağlanır.
				frappe.log_error(
					title="rate_limit: geçersiz trusted proxy CIDR",
					message=f"cidr={cidr!r}",
				)
		return tuple(nets)

	return frappe.local_cache("tradehub_rate_limit", "trusted_proxy_nets", _build)


def _is_trusted_proxy(addr: str) -> bool:
	"""Adres bizim ters-vekil kümemizde mi? Ayrıştırılamayan değer de True.

	Ayrıştırılamayan bir değeri "istemci" saymak, uydurulmuş bir dizeyi kova
	anahtarı yapmak demektir — o yüzden atlanır.
	"""
	try:
		ip = ipaddress.ip_address(addr)
	except ValueError:
		return True
	return any(ip in net for net in _trusted_proxy_networks())


def _client_ip() -> str | None:
	"""İstemcinin gerçek IP'si — bulunamazsa None.

	Sıra: X-Forwarded-For zinciri (SAĞDAN SOLA, güvenilir vekilleri atlayarak)
	→ X-Real-IP → `frappe.local.request_ip`. Her adayda "güvenilir vekil mi"
	kontrolü var; hiçbiri geçmezse None.
	"""
	if not getattr(frappe.local, "request", None):
		return None

	xff = frappe.get_request_header("X-Forwarded-For") or ""
	for addr in reversed([p.strip() for p in xff.split(",") if p.strip()]):
		if not _is_trusted_proxy(addr):
			return addr

	real_ip = (frappe.get_request_header("X-Real-IP") or "").strip()
	if real_ip and not _is_trusted_proxy(real_ip):
		return real_ip

	request_ip = (getattr(frappe.local, "request_ip", None) or "").strip()
	if request_ip and not _is_trusted_proxy(request_ip):
		return request_ip

	return None


def _bucket_identity() -> str:
	"""Kova kimliği: oturum açmışta kullanıcı, misafirde istemci IP'si.

	Misafirde IP çözülemezse `Guest:_unresolved` döner — TÜM misafirlerin tek
	kovada toplandığı eski davranışın aynısı. Bu bilinçli: yanlış/uydurma bir
	kimliğe bağlanmaktansa görünür şekilde çözülemedi demek daha güvenli.
	"""
	user = frappe.session.user if frappe.session else None
	if user and user != "Guest":
		return user
	return f"Guest:{_client_ip() or _UNRESOLVED_IP}"


def _bucket_key(name: str, user: str) -> str:
	return f"rl:{name}:{user}"


def rate_limit(
	max_calls: int = 60, window_seconds: int = 60, per_user: bool = True, scope: str | None = None
):
	"""Decorator: bir whitelisted endpoint'i rate-limit'ler.

	Args:
		max_calls: pencere içinde izin verilen maks çağrı
		window_seconds: pencere uzunluğu
		per_user: True → user başına ayrı limit; False → global
		scope: cache key prefix (default fonksiyon adı)

	Sliding window algoritması (basit fixed-window — Redis INCR + EXPIRE).
	"""

	def decorator(func):
		key_scope = scope or func.__name__

		@functools.wraps(func)
		def wrapper(*args, **kwargs):
			# T9: misafirde `frappe.session.user` her ziyaretçi için "Guest" —
			# tek kova = tek saldırganın tüm anonim trafiği kilitlemesi.
			identity = _bucket_identity() if per_user else "_global"
			key = _bucket_key(key_scope, identity)
			cache = frappe.cache()

			# F-004: Redis hatası → graceful degradation (rate limit devre dışı,
			# sistem çalışmaya devam eder). Fail-closed tüm kullanıcıları kilitler;
			# Redis downtime sırasında kısa süreli rate-limit kaybı kabul edilebilir.
			# W7-4 bulgusu (rapor 87, YÜKSEK): eski get→delete→set deseni atomik
			# değildi — 4 paralel istemci kayıp-güncelleme yarışıyla 30 sn'de
			# 6195 isteği 0×429 ile geçirdi (sınır 600/60s). Sayaç artık Redis
			# INCR ile atomik: önce say, sonra karşılaştır. Reddedilen istek de
			# sayılır — pencere dolunca saldırgan 429 almaya devam eder, sayaç
			# TTL ile sıfırlanır. `RedisWrapper` gerçek `redis.Redis` alt sınıfı;
			# `make_key` site önekini ekler (set_value ile aynı ad alanı).
			try:
				raw_key = cache.make_key(key)
				current = cache.incr(raw_key)
				if current == 1:
					cache.expire(raw_key, window_seconds)
				elif cache.ttl(raw_key) < 0:
					# incr=1 anındaki expire bir kesintiyle kaybolduysa anahtar
					# kalıcılaşır ve pencere hiç sıfırlanmaz — ucuz emniyet.
					cache.expire(raw_key, window_seconds)
			except Exception:
				frappe.log_error(
					title="Rate limiter Redis incr failed",
					message=f"key={key}, endpoint={key_scope}",
				)
				# F-004: Redis down → rate limit olmadan devam et, sistemi kilitleme.
				return func(*args, **kwargs)

			if current > max_calls:
				raise TooManyRequestsError(
					_("Çok fazla istek — {0} saniye sonra tekrar deneyin").format(window_seconds)
				)

			return func(*args, **kwargs)

		return wrapper

	return decorator


def get_remaining(name: str, user: str | None = None, max_calls: int = 60) -> int:
	"""Kalan çağrı sayısını döner (info amaçlı).

	`user` verilmezse dekoratörün kullandığı kimliğin AYNISI hesaplanır
	(misafirde `Guest:<ip>`) — aksi halde bu fonksiyon var olmayan bir kovayı
	okur ve her zaman "limit dolu değil" der.
	"""
	user = user or _bucket_identity()
	key = _bucket_key(name, user)
	try:
		current = frappe.cache().get_value(key)
		current = int(current) if current else 0
	except Exception:
		current = 0
	return max(0, max_calls - current)


def reset_bucket(name: str, user: str | None = None):
	"""Test/admin için bir bucket'i sıfırla.

	`user` verilmezse dekoratörün kimliğiyle aynı kova hedeflenir.
	"""
	user = user or _bucket_identity()
	key = _bucket_key(name, user)
	try:
		frappe.cache().delete_value(key)
	except Exception:
		frappe.log_error(f"Failed to reset rate limit bucket: name={name} user={user}", "rate_limit.reset_bucket")
		pass


def cleanup_old_records():
	"""Scheduled placeholder. Redis cache TTL ile expire ettiği için no-op."""
	pass

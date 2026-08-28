# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Anahtar bazında devre kesici — genel dayanıklılık primitifi (TUR-110).

Bir dış servis çöktüğünde her iş kuyruğu görevinin timeout'a kadar beklemesi
kuyruğu tıkar. Ardışık N hatadan sonra devre AÇILIR ve o servise giden çağrılar
cooldown boyunca hiç denenmeden reddedilir. Cooldown sonunda YARI-AÇIK: tek bir
deneme geçer; başarılıysa devre kapanır, başarısızsa cooldown yeniden başlar.

NEDEN `adapters/` ALTINDA DEĞİL: bu sınıfın kargo firmasıyla hiçbir ilgisi yok —
bir anahtar, bir sayaç ve bir cooldown. Kargo HTTP istemcisi ilk kullanıcısı,
tek kullanıcısı değil (webhook alım yolu ve dış servis istemcileri de aynı
primitifi kullanacak, ve inbound webhook bir "adapter" DEĞİLDİR). Geriye dönük
uyum için `logistics/adapters/__init__.py` bu sınıfı yeniden dışa veriyor.

DURUM REDIS'TE — süreç-içi (module-level) sayaç işe YARAMAZ: Frappe çok işçili
çalışır (gunicorn + N adet RQ worker). Her süreç kendi sayacını tutarsa devre
zamanında açılmaz; N kat fazla istek çöken servise gider.

`frappe.cache.set_value/get_value` yerine HAM redis API'si kullanılıyor:
(a) sayaç için atomik `INCR` gerekiyor, (b) `get_value` sonucu
`frappe.local.cache`'e yazıp aynı istek boyunca BAYAT değer döndürüyor,
(c) pickle gereksiz.

Her yol FAIL-OPEN: cache arızası gönderi akışını durdurmamalı — koruma katmanı
devre dışı kalır, iş devam eder. Ancak SESSİZ DEĞİL: her yutulan arıza kısılmış
biçimde raporlanır (ilki `frappe.log_error`, sonrakiler `logistics` logger'ına).
Sessiz fail-open ölçülmüş bir tuzaktı — yakalanan hata kümesi `AttributeError`
içerdiği sürece try bloğundaki bir YAZIM HATASI devre kesiciyi kalıcı ve
görünmez şekilde devre dışı bırakıyordu; bu yüzden programlama hataları
(`AttributeError`, `TypeError`) artık YUTULMUYOR.

## ANAHTAR KAPSAMI = (normalize edilmiş kod, ortam)

İki ölçülmüş arıza anahtarı buradan geçiyordu:

1. **Yazım farkı devreyi bölüyordu.** `registry.py` `carrier_code`'u
   `.strip().lower()` ile normalize ediyor, bu modül ise HAM dizeyi
   kullanıyordu. Ölçüldü: `ARAS` → `...circuit:ARAS-5d6f8c3b533da979:failures`,
   `aras` → `...circuit:aras-91c067132b137529:failures`. İki yazım AYNI
   adapter'a çözülüyor ama AYRI sayaç tutuyor; eşik hiç dolmuyor ve çöken
   taşıyıcıya karşı devre AÇILMIYORDU. Normalizasyon artık TEK OTORİTEDEN
   (`registry.normalize_carrier_code`) geliyor ve digest de NORMALİZE edilmiş
   dizeden alınıyor.
2. **Sandbox arızası production'ı kesiyordu.** Ölçüldü: sandbox istemcisinde 2
   hata → production istemcisi `CIRCUIT_OPEN`. Anahtar artık `carrier_code` +
   `environment` çiftinden türüyor; iki segment de KENDİ sha256 kuyruğunu taşır,
   böylece ayırıcı karışması (`a` + `b:c` vs `a:b` + `c`) mümkün değildir.

Kayıplı önek + digest çakışma koruması KORUNUR: `a:b` ile `a_b` hâlâ AYRI
anahtar alır (bkz. `_key_segment`).
"""

from __future__ import annotations

import enum
import hashlib
import re

import frappe
from redis.exceptions import RedisError

# TEK YÖNLÜ BAĞIMLILIK — `registry` bu modülü İMPORT ETMEZ (döngü yok; ölçüldü:
# `registry` yalnız `adapters.base` + `exceptions` çeker, `adapters/__init__.py`
# boştur). Kodu burada yeniden normalize etmek yerine oradan almanın gerekçesi
# ölçülmüş: iki katman ayrı normalizasyon uyguladığında `ARAS` ile `aras` AYRI
# devre sayacı tutuyor, arıza sayacı bölünüyor ve devre HİÇ açılmıyordu.
from tradehub_core.logistics.adapters.registry import normalize_carrier_code
from tradehub_core.logistics.constants import CACHE_PREFIX
from tradehub_core.logistics.resilience.fault_report import report_throttled
from tradehub_core.logistics.resilience.outcome import Outcome

__all__ = ["CarrierCircuitBreaker", "CircuitState"]

#: Redis anahtar kökü — proje kuralı gereği `tc:` ön ekli (CACHE_PREFIX = "tc:logistics:").
CIRCUIT_KEY_PREFIX: str = f"{CACHE_PREFIX}circuit:"

#: Cache erişilemediğinde yutulan hatalar. `RedisError` bağlantı/protokol,
#: `RuntimeError` frappe bağlamı (`frappe.local`) kurulmadan çağrıldığında,
#: `OSError` (soket/`ConnectionResetError`) ise redis-py'nin sarmalamadığı
#: altyapı arızalarında gelir — `OSError` eksikken `_enter_circuit` →
#: `breaker.state()` üzerinden `request()`'ten sızıyor, `LogisticsError`
#: olmadığı için 500 dönüyor ve gönderi akışı DURUYORDU (belgelenmiş fail-open
#: değişmezinin ihlali).
#: `AttributeError`/`TypeError` BİLEREK dışarıda: onlar cache arızası değil,
#: bizim kodumuzdaki hatadır ve görünür olmalıdır.
_CACHE_FAULTS = (RedisError, RuntimeError, OSError)

#: Anahtar bileşeni olarak kabul edilen karakterler. Doğrulanmamış bir kod
#: (boşluk, `:`, `*`) anahtar uzayını kirletir ve komşu devrelerle çakışabilir.
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9_-]")
_MAX_KEY_CODE_LEN: int = 32

#: Anahtarın çakışmayı önleyen parçası — okunabilir önek KAYIPLI olduğu için.
_KEY_DIGEST_LEN: int = 16


def _report_fault(scope: str, exc: BaseException, *, circuit: str = "-") -> None:
	"""Yutulan cache arızasını KISILMIŞ biçimde raporlar.

	İlk görülüşte `frappe.log_error` (traceback'li kalıcı kayıt), sonraki
	tekrarlarda 60 sn'de bir `logistics` logger'ına uyarı. Redis çöktüğünde
	saniyede yüzlerce çağrı gelir; her birine Error Log satırı yazmak arızayı
	teşhis edilemez hale getirirdi.

	Kısma mantığı `resilience/fault_report.py`'de PAYLAŞILIYOR — kardeş yol
	(`http_client._report_log_failure`) aynı deseni devralmamıştı ve kalıcı bir
	log arızasında istek başına `Error Log` satırı üretiyordu.

	KISMA KAPSAMI DEVRE BAŞINADIR (`circuit`). Eskiden kapsam yalnız sabit metot
	adıydı (`'state'`, `'record_failure'`); TÜM taşıyıcılar ve TÜM ortamlar tek
	kısma kovasını paylaşıyordu, yani bir taşıyıcının arızası diğerlerinin
	raporunu 60 sn boyunca SUSTURUYORDU. `fault_report.report_throttled`
	docstring'i kapsamı zaten `carrier_code + ":" + operation` olarak
	örnekliyordu; kardeş yol (`http_client._report_log_failure`) buna uyuyordu,
	bu yol uymuyordu.
	"""
	report_throttled(
		f"circuit:{circuit}:{scope}",
		f"Devre kesici cache arızası (circuit={circuit} {scope}): {type(exc).__name__}: {exc}",
		"logistics.circuit_breaker",
	)


class CircuitState(enum.Enum):
	CLOSED = "closed"
	OPEN = "open"
	HALF_OPEN = "half_open"


class CarrierCircuitBreaker:
	"""Tek bir anahtarın devre durumunu Redis üzerinden yönetir.

	Args:
		carrier_code: Devrenin kapsamı — her taşıyıcı/servis bağımsız. Bu değer
			bir REGISTRY kodudur (`aras`, `yurtici`), `Logistics Provider`
			docname'i DEĞİL; anahtar uzayı log'unkiyle aynı olmak zorunda değil.
			`registry.normalize_carrier_code` ile normalize edilir: `ARAS`,
			`aras` ve `' aras '` AYNI devredir.
		environment: Devrenin İKİNCİ kapsam ekseni (`production` | `sandbox` |
			`test`). Ölçüldü: eksikken sandbox'ta 2 hata production çağrılarını
			`CIRCUIT_OPEN` ile kesiyordu. Kod ile aynı kurala göre normalize edilir.
		failure_threshold: Devreyi açan ardışık hata sayısı.
		cooldown_sec: Devrenin açık kalma süresi.
		failure_window_sec: Hata sayacının yaşam süresi. Saatler arayla gelen
			münferit hatalar devreyi açmamalı — sayaç bu pencerede sıfırlanır.
		enabled: False ise TÜM metotlar no-op (testler, tek seferlik işler):
			`state()` daima CLOSED, `acquire_probe()` False, `reset()` ve
			kayıt metotları hiçbir şey yapmaz.
	"""

	def __init__(
		self,
		carrier_code: str,
		*,
		environment: str = "production",
		failure_threshold: int = 5,
		cooldown_sec: int = 60,
		failure_window_sec: int = 300,
		enabled: bool = True,
	) -> None:
		self.carrier_code: str = normalize_carrier_code(carrier_code)
		self.environment: str = normalize_carrier_code(environment) or "production"
		self._key_code: str = _sanitize_key_code(carrier_code)
		self._key_env: str = _key_segment(self.environment)
		#: Kısma kapsamının okunabilir kimliği — bkz. `_report_fault`.
		self._fault_scope: str = f"{self.carrier_code}@{self.environment}"
		self.failure_threshold: int = max(1, int(failure_threshold))
		self.cooldown_sec: int = max(1, int(cooldown_sec))
		self.failure_window_sec: int = max(self.cooldown_sec, int(failure_window_sec))
		self.enabled: bool = enabled

	# -------------------------------------------------------------------
	# Sorgu
	# -------------------------------------------------------------------

	def state(self) -> CircuitState:
		"""Devrenin güncel durumu. Cache erişilemezse CLOSED (fail-open)."""
		if not self.enabled:
			return CircuitState.CLOSED
		try:
			client = frappe.cache
			# `exists()` KULLANILMIYOR: RedisWrapper onu override edip `make_key`'i
			# BİR KEZ DAHA uyguluyor; önceden ön-ekli anahtarımız çifte ön-ek alıp
			# hep 0 dönüyordu (ölçüldü — devre hiç açılmıyordu). get/set/incr/expire/
			# delete override edilmemiş, ön eki bu yüzden biz veriyoruz.
			if client.get(self._key("open")) is not None:
				return CircuitState.OPEN
			failures = self._read_failures(client)
		except _CACHE_FAULTS as exc:
			_report_fault("state", exc, circuit=self._fault_scope)
			return CircuitState.CLOSED
		return CircuitState.HALF_OPEN if failures >= self.failure_threshold else CircuitState.CLOSED

	def acquire_probe(self) -> bool:
		"""Yarı-açık durumda TEK bir denemeye izin verir (`SET NX` — atomik).

		Atomik olmak zorunda: aksi halde cooldown biter bitmez tüm işçiler aynı
		anda "probe" sanıp çöken firmayı yeniden yere serer.
		"""
		if not self.enabled:
			return False
		try:
			return bool(frappe.cache.set(self._key("probe"), b"1", ex=self.cooldown_sec, nx=True))
		except _CACHE_FAULTS as exc:
			_report_fault("acquire_probe", exc, circuit=self._fault_scope)
			return True

	def claim_open_notice(self) -> bool:
		"""Bu cooldown içinde devre-açık reddini KALICI loglama hakkını talep eder.

		Devre kesicinin amacı yükü kesmek; her reddi DocType'a yazmak HTTP'den
		tasarruf edilen yükü log tablosuna aktarır (60 sn cooldown'da kuyruktaki
		N görev N adet aynı satırı yazar). `SET NX` ile cooldown başına yalnız
		bir çağıran True alır; kalanlar ucuz logger'a düşmeli.

		Cache arızasında True döner: gözlemlenebilirliği kaybetmektense fazladan
		satır yazmak yeğdir.
		"""
		if not self.enabled:
			return True
		try:
			return bool(frappe.cache.set(self._key("notice"), b"1", ex=self.cooldown_sec, nx=True))
		except _CACHE_FAULTS as exc:
			_report_fault("claim_open_notice", exc, circuit=self._fault_scope)
			return True

	def release_open_notice(self) -> None:
		"""Alınan loglama hakkını geri verir — kazanan satırı YAZAMADIYSA.

		`SET NX` tekilliği doğru çalışıyor ama kazananın log yazımı düşerse
		cooldown boyunca DocType'ta HİÇ satır kalmıyordu: anahtar alınmış,
		kimse yeniden deneyemiyor. Hak geri verilince sıradaki çağrı yazmayı
		dener.
		"""
		if not self.enabled:
			return
		try:
			frappe.cache.delete(self._key("notice"))
		except _CACHE_FAULTS as exc:
			# TTL ile zaten düşer; en kötü ihtimalle bu cooldown'da satır yok.
			_report_fault("release_open_notice", exc, circuit=self._fault_scope)

	# -------------------------------------------------------------------
	# Kayıt
	# -------------------------------------------------------------------

	def record(self, outcome: Outcome, *, is_probe: bool = False) -> None:
		"""Sonucu devre durumuna işler. Tek giriş noktası — bkz. `Outcome`."""
		if outcome is Outcome.HEALTHY:
			self.record_success()
		elif outcome is Outcome.UNAVAILABLE:
			self.record_failure(is_probe=is_probe)
		else:
			self.record_neutral(is_probe=is_probe)

	def record_success(self) -> None:
		"""Servis ayakta — sayaç ve devre sıfırlanır."""
		if not self.enabled:
			return
		self.reset()

	def record_neutral(self, *, is_probe: bool = False) -> None:
		"""Sonuç devre açısından ANLAMSIZ — sayaç ne artar ne sıfırlanır.

		Kalıcı 4xx, kapı reddi ve yapılandırma hatası buraya düşer.

		SAYAÇ AÇISINDAN hâlâ mutlak no-op — ama PROBE ANAHTARI açısından DEĞİL.
		Ölçüldü: yarı-açık probe HTTP 400 alınca anahtar geri verilmiyor, devre
		HALF_OPEN'da kilitleniyor ve sonraki SAĞLIKLI çağrı `CIRCUIT_OPEN`
		yiyordu (`acquire_probe()` → False). Kilit `probe` anahtarının TTL'i
		(= cooldown) dolana kadar sürüyordu.

		NEDEN "ANAHTARI İADE", "DEVREYİ KAPAT" DEĞİL (ölçülmüş gerekçe): NEUTRAL
		kümesi yalnız 4xx değil; `CONFIG_ERROR` (geçersiz timeout/URL) ve
		`URL_BLOCKED` (SSRF kapısı reddi) de NEUTRAL üretir ve bu iki dalda istek
		TAŞIYICIYA HİÇ ULAŞMAZ. Devreyi kapatmak, taşıyıcıya dair SIFIR kanıtla
		`failures` sayacını sıfırlar; çöken bir taşıyıcının önündeki devre, kendi
		`base_url`'ümüzdeki bir yazım hatasıyla açılabilir hâle gelirdi. Anahtarı
		iade etmek durumu probe ÖNCESİNE geri döndürür: devre HALF_OPEN kalır,
		sayaç eşikte durur, sıradaki çağrı YENİ bir probe alır ve taşıyıcı
		hakkındaki kararı gerçek bir kanıt verir.
		"""
		if not self.enabled or not is_probe:
			return
		self.release_probe()

	def release_probe(self) -> None:
		"""Alınan yarı-açık deneme hakkını geri verir — kanıt üretilemediyse.

		Çağrıldığı yerler: NEUTRAL sonuç (bkz. `record_neutral`) ve transport'a
		hiç ulaşmadan biten çağrılar (kapı reddi, `classify=` çöküşü). Devre
		DURUMU değişmez; yalnız `probe` anahtarı silinir.

		Cache arızasında sessiz kalmıyoruz ama akış da durmuyor: anahtar TTL ile
		zaten cooldown sonunda düşer, en kötü ihtimalle bu cooldown'da başka
		probe verilmez (fail-open değil, fail-safe — mevcut davranışın aynısı).
		"""
		if not self.enabled:
			return
		try:
			frappe.cache.delete(self._key("probe"))
		except _CACHE_FAULTS as exc:
			_report_fault("release_probe", exc, circuit=self._fault_scope)

	def record_failure(self, *, is_probe: bool = False) -> None:
		"""Servis erişilemedi — sayacı artırır, eşikte devreyi açar.

		Yalnızca "karşı taraf ayakta değil" sinyalleri buraya gelmeli
		(`Outcome.UNAVAILABLE`). Kalıcı 4xx `record_neutral()`'a gider.
		"""
		if not self.enabled:
			return
		try:
			client = frappe.cache
			if is_probe:
				# Yarı-açık deneme başarısız — cooldown baştan başlar.
				client.set(self._key("open"), b"1", ex=self.cooldown_sec)
				client.set(self._key("failures"), str(self.failure_threshold), ex=self.failure_window_sec)
				client.delete(self._key("probe"), self._key("notice"))
				return
			failures = self._incr_failures(client)
			if failures >= self.failure_threshold:
				client.set(self._key("open"), b"1", ex=self.cooldown_sec)
		except _CACHE_FAULTS as exc:
			_report_fault(
				"record_failure", exc, circuit=self._fault_scope
			)  # Fail-open: koruma yok ama akış sürüyor.

	def reset(self) -> None:
		"""Devre durumunu tamamen siler (admin "bağlantıyı test et" akışı, testler)."""
		if not self.enabled:
			return
		try:
			frappe.cache.delete(
				self._key("failures"), self._key("open"), self._key("probe"), self._key("notice")
			)
		except _CACHE_FAULTS as exc:
			# Silinemeyen anahtar TTL ile zaten düşer — ama sessiz kalmıyoruz.
			_report_fault("reset", exc, circuit=self._fault_scope)

	# -------------------------------------------------------------------
	# İç yardımcılar
	# -------------------------------------------------------------------

	def _key(self, suffix: str) -> bytes | str:
		"""Anahtar = ön ek + NORMALİZE kod segmenti + ORTAM segmenti + son ek.

		İki segment de kendi sha256 kuyruğunu taşır (bkz. `_key_segment`), yani
		ayırıcı karışması (`a` + `b:c` ile `a:b` + `c`) aynı anahtarı üretemez.
		"""
		return frappe.cache.make_key(f"{CIRCUIT_KEY_PREFIX}{self._key_code}:{self._key_env}:{suffix}")

	def _incr_failures(self, client: object) -> int:
		"""Sayacı ATOMİK olarak artırır; TTL yalnız anahtar YENİYKEN kurulur.

		`incr` + ayrı `expire` iki ayrı gidiş-dönüş: arada süreç ölürse ya da
		ikinci komut düşerse anahtar TTL'SİZ kalır ve o taşıyıcı için sayaç bir
		daha asla sıfırlanmaz. Pipeline (MULTI/EXEC) ikisini tek turda gönderir.

		`SET NX` + `INCR`, düz `INCR` + `EXPIRE`'ın yerine geçti: ikincisi TTL'i
		HER artışta tazeliyordu, yani pencere SABİT değil KAYAN bir boşta-kalma
		penceresi oluyordu (ölçüldü: `window=17`, 1. hata ttl=17, 1 sn sonra 2.
		hata ttl=16 olmalıyken yine 17). Sınıf docstring'i açıkça tersini vaat
		ediyor: "saatler arayla gelen 5 münferit hata devreyi açmamalı" —
		kayan pencerede 4 dakikada bir gelen hatalar devreyi sonunda AÇARDI.
		"""
		key = self._key("failures")
		pipe = client.pipeline()  # type: ignore[attr-defined]
		pipe.set(key, 0, ex=self.failure_window_sec, nx=True)
		pipe.incr(key)
		return _coerce_counter(pipe.execute()[1])

	def _read_failures(self, client: object) -> int:
		# redis-py ham bayt döndürür (frappe `decode_responses` kullanmıyor);
		# `int(b"3")` TypeError verir — önce çöz.
		return _coerce_counter(client.get(self._key("failures")))  # type: ignore[attr-defined]

	def __repr__(self) -> str:
		return (
			f"<CarrierCircuitBreaker carrier={self.carrier_code!r} "
			f"threshold={self.failure_threshold} cooldown={self.cooldown_sec}s>"
		)


def _key_segment(value: str) -> str:
	"""Bir anahtar segmentini güvenli karakter kümesine indirger — KAYIPSIZ.

	Eski hâli yalnız `sub()` + kırpma yapıyordu ve KAYIPLIYDI: `a:b`, `a_b`,
	`a b`, `a.b`, `a/b`, `a*b` HEPSİ `a_b` oluyordu. Kanıtlandı — `a:b`'ye 2
	hata yazınca `a_b`'nin devresi de açılıyor, yani BİR taşıyıcının çökmesi
	BAŞKA bir taşıyıcının gönderilerini durduruyordu. 64 karakteri aşan iki
	farklı kod da aynı anahtara düşüyordu.

	Çözüm: okunabilir (ama kayıplı) öneke, segmentin sha256 özetinden bir kuyruk
	eklenir. Önek operatör içindir; ayrıştırıcı olan kuyruktur.
	"""
	raw = str(value or "")
	cleaned = _UNSAFE_KEY_CHARS.sub("_", raw)[:_MAX_KEY_CODE_LEN] or "_"
	digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:_KEY_DIGEST_LEN]
	return f"{cleaned}-{digest}"


def _sanitize_key_code(carrier_code: str) -> str:
	"""Taşıyıcı kodunu anahtar segmentine çevirir — ÖNCE NORMALİZE EDER.

	DIGEST HAM DİZEDEN DEĞİL, NORMALİZE EDİLMİŞ DİZEDEN alınır. Ölçüldü: eskiden
	`strip()` yalnızca okunabilir öneke uygulanıyor, sha256 ise HAM dizeyi
	özetliyordu; `'ARAS'`, `'aras'` ve `' aras '` üç AYRI devre anahtarı
	üretiyordu (`ARAS-5d6f8c3b533da979`, `aras-91c067132b137529`,
	`aras-904d2d4d1225168e`). Üçü de `registry.get_adapter` tarafından AYNI
	adapter'a çözülüyordu, yani arıza sayacı üçe bölünüyor ve eşik hiç
	dolmuyordu.

	Çakışma koruması KORUNUR: normalizasyon yalnız `strip().lower()` yapar,
	`a:b` ile `a_b` normalize edildikten sonra da FARKLI dizelerdir ve farklı
	digest üretirler.
	"""
	return _key_segment(normalize_carrier_code(carrier_code))


def _coerce_counter(raw: object) -> int:
	"""Redis'ten gelen sayaç değerini int'e çevirir; bozuksa 0 sayar.

	DAR kapsam: bu dönüşümün `ValueError`'ı bir CACHE arızası değil, bozuk bir
	değerdir ve devre kesicinin tamamını fail-open'a düşürmemeli.
	"""
	if raw is None:
		return 0
	if isinstance(raw, (bytes, bytearray)):
		raw = bytes(raw).decode("utf-8", errors="replace")
	try:
		return int(raw)
	except (TypeError, ValueError):
		return 0

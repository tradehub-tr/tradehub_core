# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Kimlik dokümanından SIR DEĞERLERİNİ toplar — değer-tabanlı redaksiyonun girdisi.

NEDEN AYRI MODÜL (eskiden `http_client._collect_secret_values` static metoduydu):

1. **Üç ayrı tüketici var.** Giden istemci, webhook alıcısı (`direction="inbound"`)
   ve credential fabrikası aynı kümeye ihtiyaç duyar. Private bir static metot
   olarak kaldığı sürece üç kopya doğardı; `log.py`'nin `safe_log_error`
   hikâyesi bunun tam olarak nasıl bittiğini gösteriyor.
2. **`Password` fieldtype'ı ancak burada tek yerde ele alınabilir.** Aşağıdaki
   ölçülmüş arıza tam olarak bu yüzden oluştu.

ÖLÇÜLMÜŞ ARIZA — "küme boş" DEĞİL, "küme DOLU ama SAHTE":

	Frappe `base_document.py::_save_passwords` `Password` alanının GERÇEK
	değerini `__Auth` tablosuna yazar ve SÜTUNA `'*' * len(değer)` koyar.
	`Carrier Account`'taki dört gizli alanın DÖRDÜ DE `Password` fieldtype.
	Düz `Mapping.get(field)` ile okuyan eski toplayıcı şunu üretiyordu
	(gerçek kayıtla ölçüldü):

		as_dict()['api_key']            == '*******************'
		toplanan küme                   == {'*******************', '******************'}
		'REALSECRETKEY123456' in küme   == False
		mask_payload('<Xyz42>REALSECRETKEY123456</Xyz42>', secret_values=küme)
		                                == GİRDİYLE AYNI

	Üç etkisi vardı ve üçü de sessizdi:

	(a) BİRİNCİL SAVUNMA kanonik yolda tamamen no-op — `masking.py`'nin kendi
	    docstring'indeki `<Xyz42>SECRET</Xyz42>` örneği ham loglanıyordu.
	(b) Küme BOŞ OLMADIĞI için `log.py`'nin "`secret_values` unutuldu" uyarısı
	    HİÇ tetiklenmiyordu — arızayı yakalayacak TEK guardrail susturulmuştu,
	    sistem kendini korunuyor sanıyordu.
	(c) `'*' * 19` geçerli bir redaksiyon varyantı olarak kullanılıyordu; gövdede
	    geçen her 19 yıldızlık dizi `***` ile değiştiriliyordu (sessiz veri
	    bozulması).

SÖZLEŞME — ÜÇ DURUM, ÜÇÜ DE AYRI:

	frozenset(...)  Sırların PLAINTEXT'i toplandı (boş olabilir: doküman hiç sır
	                taşımıyordur). Çağıran bunu `secret_values=` ile geçer.
	frozenset()     "Sır YOK" — doğrulanmış bilgi.
	None            "Sır VAR ama PLAINTEXT'İ OKUYAMADIM." Çağıran
	                `write_integration_log`'a `secret_values` argümanını HİÇ
	                GEÇMEMELİDİR; o zaman yazıcının kendi "unutuldu" uyarısı
	                devreye girer. Yarım bir küme geçmek, guardrail'i susturup
	                korunuyor izlenimi verir — (b) maddesindeki hatanın ta kendisi.

FRAPPE BAĞIMLILIĞI YOK: `masking.py` ile aynı gerekçe — bu mantık düz
`python -m unittest` ile de doğrulanabilmeli. Doküman TÜR KONTROLÜYLE değil
DAVRANIŞLA tanınır (`get_password` çağrılabiliyor mu), uyarılar stdlib
`logging` ile yazılır. Çağıran (Frappe'yi zaten import eden `http_client`)
`None` dönüşünü kalıcı bir `Error Log` satırına çevirir.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from tradehub_core.logistics.constants import CREDENTIAL_SECRET_FIELDS
from tradehub_core.logistics.integration.masking import secret_texts

#: Modül uyarıları — Frappe'siz kalabilmek için stdlib logging.
_LOGGER = logging.getLogger("tradehub_core.logistics.secrets")

__all__ = [
	"CREDENTIAL_SECRET_FIELDS",
	"collect_extra_secret_values",
	"collect_secret_values",
	"is_password_placeholder",
]

#: `str` olmayan ama SIR OLABİLECEK türler — `masking.secret_texts` bunların
#: hepsini aranabilir metin gösterimlerine çevirir (utf-8/latin-1/hex/base64).
#:
#: ÖLÇÜLMÜŞ ARIZA: `_read_secret_field` `str` olmayan değeri "alan HİÇ DOLU
#: DEĞİL" sayıyordu; `{'api_key': b'REALKEY123456'}` ve `{'api_key': 123456789}`
#: için `collect_secret_values` UYARISIZ `frozenset()` döndürüyordu. Sözleşmede
#: `frozenset()` "sır YOK — DOĞRULANMIŞ" demek, dolayısıyla `http_client._log`
#: `secret_values=frozenset()` argümanını AÇIKÇA geçiyor ve `log.py`'nin
#: "unutuldu" nöbetçisi de tetiklenmiyordu — İKİ guardrail birden susuyordu.
#: `credential_doc` sözleşmesi `dict[str, Any]`; HMAC anahtarı `bytes`, hesap no
#: `int` taşıyan kimlik sözlüğü tam bu sınıftır ve `masking` bu türleri ZATEN
#: destekliyordu. `bool` BİLEREK dışarıda: `int` alt sınıfı olsa da bir sır
#: değeri değildir, "alan dolu" saymak yanıltıcı olurdu.
#:
#: `Decimal` 5. turda eklendi: Frappe `Currency`/`Float` alanları ve DB
#: sürücüsü rutin olarak `Decimal` döndürür ve bu tür buraya girmediği için
#: `_read_secret_field` onu "desteklenmeyen" sayıp `unresolved`'a yazıyordu —
#: o kimlik dokümanı için değer-tabanlı savunma TAMAMEN kapanıyordu.
#: `masking.secret_texts` onu `format(raw, 'f')` ile bilimsel gösterim tuzağına
#: düşmeden metne çevirir.
_CONVERTIBLE_SECRET_TYPES = (bytes, bytearray, memoryview, int, float, Decimal)


def is_password_placeholder(value: str) -> bool:
	"""Frappe'nin `Password` sütununa yazdığı yer tutucu mu?

	Frappe gerçek değeri `__Auth`'a taşır ve sütuna `'*' * len(değer)` koyar.
	Yer tutucunun UZUNLUĞU değişkendir, o yüzden sabit bir metinle
	karşılaştırılamaz; ayırt edici özellik "TAMAMI yıldız" olmasıdır.

	⚠️ TEK BAŞINA YETERLİ DEĞİL — bkz. `_read_secret_field`. Tamamı yıldız olan
	MEŞRU bir sır (`'******'`) da bu testi geçer; o yüzden yer tutucu kararı
	"tamamı yıldız VE `get_password()` okuyabilen bir doküman var" bileşimiyle
	verilir. Düz bir `dict`'te `__Auth` dolaylaması YOKTUR, dolayısıyla oradaki
	`'******'` yer tutucu değil DEĞERİN KENDİSİDİR (ölçüldü: eskiden
	`collect_secret_values` o vakada `None` dönüyor ve o istemci için
	değer-tabanlı redaksiyon TAMAMEN kapanıyordu).

	Args:
		value: Alan değeri.

	Returns:
		Değer boş değilse ve yalnız `*` karakterlerinden oluşuyorsa True.
	"""
	return bool(value) and set(value) == {"*"}


def collect_secret_values(
	source: Any,
	extra: Iterable[Any] | None = None,
) -> frozenset[str] | None:
	"""Kimlik dokümanındaki sır DEĞERLERİNİ toplar.

	Neden değer (anahtar adı değil): anahtar denylist'i taşıyıcının alan ADINI
	tanımak zorunda, bu yüzden bilinmeyen bir şema (`<Xyz42>SECRET</Xyz42>`) onu
	atlatır. İsteği kuran BİZ olduğumuz için sır DEĞERİ zaten elimizde — birebir
	dizgi eşleşmesi biçimden bağımsız çalışır: SOAP, base64, querystring,
	istisna metni, hepsinde.

	OKUMA SIRASI (tür kontrolü TEK yerde, burada):

	1. `get_password(field, raise_exception=False)` — `Document` benzeri girdide
	   `Password` alanının GERÇEK değerini `__Auth` tablosundan getiren tek yol.
	2. Düz alan okuması (`.get()` ya da `getattr`) — düz `dict` girdisi,
	   ve HENÜZ KAYDEDİLMEMİŞ bir doküman (o anda alanda plaintext durur).

	Yer tutucu (`'****'`) hiçbir koşulda kümeye GİRMEZ: redaksiyon varyantı
	olarak kullanılsaydı gövdedeki her yıldız dizisini bozardı.

	⚠️ `extra` BU DÖNÜŞE BAĞLIDIR — AYRI KANAL VAR: `credential_doc`
	çözülemediğinde bu fonksiyon `None` döner ve `extra` ile verilen sırlar da
	onunla birlikte düşer (ölçüldü:
	`collect_secret_values(placeholder_doc, extra=['OTURUM_JETONU_777'])` →
	`None`). Guardrail argümanı `credential_doc` için geçerlidir — yarım küme
	geçmek "korunuyorum" yanılgısı üretir — ama `extra` FARKLI BİR KAYNAKTIR:
	adapter'ın kendi ürettiği kısa ömürlü jeton/imza, taşıyıcının YANITINDA geri
	döner ve denylist'in en kolay atladığı materyaldir. İki kaynağı ayırmak için
	`collect_extra_secret_values` kullanın ve onu `write_integration_log`'un
	`extra_secret_values=` kanalıyla geçin; o kanal "unutuldu" nöbetçisini
	SUSTURMAZ. `http_client` tam olarak böyle yapar.

	Args:
		source: `Carrier Account` dokümanı ya da alan adı → değer eşlemesi.
			`None` verilebilir (yalnız `extra` toplanır).
		extra: Adapter'ın kendi ürettiği kısa ömürlü sırlar (oturum jetonu,
			imza); credential dokümanında görünmezler. Yukarıdaki uyarıya bakın.

	Returns:
		Toplanan plaintext kümesi; bir alan DOLU olduğu hâlde plaintext'i
		okunamadıysa `None` (bkz. modül docstring'i "ÜÇ DURUM").
	"""
	values: set[str] = set()
	unresolved: list[str] = []

	for field in CREDENTIAL_SECRET_FIELDS:
		plaintexts, present = _read_secret_field(source, field)
		if not present:
			continue
		if plaintexts is None:
			unresolved.append(field)
			continue
		values.update(plaintexts)

	values |= collect_extra_secret_values(extra)

	if unresolved:
		# SESSİZ KALMAK YASAK: bu "sır yok" değil, "sırrı YANLIŞ YERDEN okudum".
		# Çağıran `None`'ı görüp `secret_values`'ı hiç geçmeyecek, böylece
		# yazıcının kendi uyarısı da tetiklenecek — iki katman birden konuşur.
		_LOGGER.error(
			"Kimlik dokümanında DOLU olan sır alanlarının plaintext'i okunamadı: %s. "
			"Değer-tabanlı redaksiyon BİRİNCİL savunmadır; yarım küme geçmek yerine "
			"hiç geçilmeyecek. `Password` alanları için `get_password()` gerekir.",
			", ".join(unresolved),
		)
		return None

	return frozenset(values)


def collect_extra_secret_values(extra: Iterable[Any] | None) -> frozenset[str]:
	"""Adapter'ın ürettiği kısa ömürlü sırları AYRI kanal olarak toplar.

	`credential_doc`'tan bağımsızdır ve ASLA `None` dönmez: bu kaynakta
	"okuyamadım" durumu yoktur — değerler çağıranın elinde plaintext durur.
	Bu yüzden credential çözülemediğinde bile uygulanabilir.

	Args:
		extra: Oturum jetonu, imza gibi kısa ömürlü sır değerleri.

	Returns:
		Aranabilir plaintext kümesi (boş olabilir).
	"""
	values: set[str] = set()
	for raw in extra or ():
		if isinstance(raw, str):
			if raw.strip():
				values.add(raw)
		elif isinstance(raw, _CONVERTIBLE_SECRET_TYPES) and not isinstance(raw, bool):
			values.update(text for text in secret_texts(raw) if text.strip())
		elif raw is not None:
			_LOGGER.error(
				"Desteklenmeyen `extra` sır türü redakte EDİLEMEDİ: %s. Sır değeri metin, "
				"bayt ya da sayı olmalı.",
				type(raw).__name__,
			)
	return frozenset(values)


def _read_secret_field(source: Any, field: str) -> tuple[tuple[str, ...] | None, bool]:
	"""Tek bir sır alanını okur. Döner: `(plaintext gösterimleri, alan DOLU mu)`.

	`plaintexts is None and present` → alan dolu ama gerçek değere ulaşılamadı
	(yer tutucu okundu ve `get_password` da vermedi, ya da tür desteklenmiyor).

	SESSİZ ÜÇÜNCÜ YOL YOK: `str` olmayan bir değer ya dönüştürülüp kümeye
	girer (bayt/sayı — `masking.secret_texts` ile, sistemin geri kalanının
	beklediği dönüşümün AYNISI) ya da `unresolved`'a yazılıp `None` döner.
	"Alan hiç dolu değil" saymak İKİ guardrail'i birden susturuyordu (bkz.
	`_CONVERTIBLE_SECRET_TYPES` gerekçesi).
	"""
	stored = _read_plain(source, field)

	if not isinstance(stored, str):
		if stored is None or isinstance(stored, bool) or not stored:
			return None, False
		if isinstance(stored, _CONVERTIBLE_SECRET_TYPES):
			texts = tuple(text for text in secret_texts(stored) if text.strip())
			return (texts, True) if texts else (None, True)
		# Liste/sözlük/nesne: `str()` gösterimi meşru veriyle çakışıp gövdeyi
		# bozabilir. Sessizce ATMAK yerine GÜRÜLTÜLÜ fail-closed.
		return None, True

	if not stored.strip():
		return None, False

	decrypted = _read_password(source, field)
	if isinstance(decrypted, str) and decrypted.strip() and not is_password_placeholder(decrypted):
		return (decrypted,), True

	# Kaydedilmemiş doküman / düz dict: alanın kendisi plaintext taşır.
	# YER TUTUCU KARARI BİLEŞİKTİR: `'******'` ancak `get_password()` OKUYABİLEN
	# bir dokümanda yer tutucudur. Düz `dict`'te `__Auth` dolaylaması yok, değer
	# kendisidir — tersini varsaymak meşru bir sırrı düşürüp o istemci için
	# birincil savunmayı tamamen kapatıyordu (ölçüldü).
	if not (_has_password_reader(source) and is_password_placeholder(stored)):
		return (stored,), True

	return None, True


def _has_password_reader(source: Any) -> bool:
	"""Kaynak `Password` alanını `__Auth`'tan okuyabilen bir doküman mı?"""
	return callable(getattr(source, "get_password", None))


def _read_plain(source: Any, field: str) -> Any:
	"""Alanı ham okur — `Mapping`, Frappe `Document` ve düz nesne için tek yol."""
	if source is None:
		return None
	getter = getattr(source, "get", None)
	if callable(getter):
		try:
			return getter(field)
		except Exception:  # noqa: BLE001 — okuma yolu sır toplamayı düşüremez
			return None
	return getattr(source, field, None)


def _read_password(source: Any, field: str) -> Any:
	"""`Document.get_password` varsa çağırır; yoksa/patlarsa `None`.

	`raise_exception=False`: değeri hiç kaydedilmemiş bir alanda Frappe aksi
	hâlde fırlatır ve tek bir eksik alan tüm toplamayı düşürürdü.
	"""
	get_password = getattr(source, "get_password", None)
	if not callable(get_password):
		return None
	try:
		return get_password(field, raise_exception=False)
	except Exception:  # noqa: BLE001 — kayıt DB'de yoksa/şifre çözülemezse yer tutucuya düşülür
		return None

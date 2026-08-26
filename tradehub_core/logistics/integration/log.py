# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Entegrasyon logu yazıcısı — `Carrier Integration Log` DocType'ına yazar.

TASARIM SÖZLEŞMESİ (dördü de bağlayıcı):

1. **ASLA istisna fırlatmaz.** Log yazımı bir yan etkidir; taşıyıcıya gönderi
   açma isteği, log satırı yazılamadı diye başarısız olmamalıdır. Her hata
   `frappe.log_error` ile raporlanır ve `None` döner. `log_error`'ın KENDİSİ de
   bir Error Log satırı yazar — yani DB yazma katmanı çöktüğünde (log yazımının
   başarısız olmasının en olası nedeni) o da patlar. Bu yüzden her `log_error`
   çağrısı iç içe try/except ile sarılıdır (`safe_log_error`).

   AMA "fırlatmamak" `None` DÖNMEK DEĞİLDİR: `None` denetim izinin kaybıdır ve
   madde 3 ile çelişir. Serileştirme hataları (`str` olmayan sözlük anahtarı,
   döngüsel referans, `RecursionError`) dış `except`'e ÇIKMADAN kapatılır —
   bkz. `_json_text`. Ölçüldü: `{b'sifre': b'x'}` gövdesi `json.dumps`'ta
   `TypeError` fırlatıp KAYDIN TAMAMINI düşürüyordu; `parse_qs(body_bytes)`
   tam bu biçimi üretir, yani `direction='inbound'` webhook'u ile erişilebilir.
2. **Maskeleme merkezi.** Gövdeler, başlıklar, SÖZLEŞME İHLALİ ZARFI ve HATA
   METİNLERİ yazılmadan ÖNCE maskelenir. Çağıranın maskelemeyi atlaması MÜMKÜN
   DEĞİL — imzada "zaten maskelendi" gibi bir kaçış yolu yok.

   Bu invaryant İKİ yerde deliniyordu (ölçüldü, ikisi de kapatıldı):
   `_serialize_request` `violations` sözlüğünü zarfa HAM koyuyordu
   (`operation='sifre=SUPERSECRET123'` → `request_body` içinde ham), ve
   `_split_choice` ham değeri f-string ile **Error Log**'a yazıyordu. Error Log
   `Carrier Integration Log`'dan DAHA GENİŞ okuma yetkisine sahiptir ve
   `MASKED_LOG_FIELDS` oraya hiç uygulanmaz — yani ikinci sızıntı birincisinden
   daha ağırdı.

   ÜÇÜNCÜ DELİK (10. tur, ölçüldü): redaksiyon yalnız DEĞER yapraklarına
   uygulanıyordu, sözlük ANAHTARI konumundaki sır HAM yazılıyordu — aynı içerik
   JSON METNİ olarak geldiğinde maskeleniyordu, yani `masking.py`'nin TEK KÜME
   KURALI ihlal ediliyordu. Anahtar redaksiyonu artık `_redact_deep`'te; sıra
   bağlayıcıdır (önce anahtar denylist'i, SONRA değer-tabanlı redaksiyon).

   MASKELEME KAYDI DÜŞÜREMEZ (10. tur, ölçüldü): `_mask_short_text` `…` için
   bütçe ayırmadığından `limit + 1` üretiyor, `error_code` (`Data`, 140)
   `CharacterLengthExceededError` ile reddediliyor ve SATIR HİÇ YAZILMIYORDU.
   Kırpma sınırları artık ellipsis payını içerir.

   `secret_values` ARGÜMANININ ATLANMASI da bu invaryantı deler: değer-tabanlı
   redaksiyon birincil savunmadır ve `{'X-Trace': <jeton>}` gibi beklenmedik bir
   taşımada TEK savunmadır. Argüman hiç verilmediğinde uyarı yazılır (bkz.
   `_SECRET_VALUES_OMITTED`); "unuttum" ile "sır yok" ayrışsın diye sır
   içermeyen çağrılar `secret_values=()` YAZMALIDIR.
3. **Veri kaybetmez.** Sözleşme dışı `operation`/`direction` değeri gelirse
   uyarı loglanır ama kayıt yine de yazılır (bkz. `_split_choice`) ve
   `error_code` boşsa `CONTRACT_VIOLATION` yazılır — ihlal SORGULANABİLİR olur.
4. **Kırpma maskelemeden ÖNCE.** 50 MB'lık bir gövde tam boy ayrıştırılıp
   regex'ten geçirilip sonra 64 KB'a inmez; giriş noktasında kırpılır ve
   maskeleme yalnız kırpılmış metni görür.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

import frappe

from tradehub_core.logistics.constants import (
	INTEGRATION_LOG_DIRECTIONS,
	INTEGRATION_LOG_OPERATIONS,
)
from tradehub_core.logistics.integration.masking import (
	MASK,
	MAX_MASK_DEPTH,
	build_secret_variants,
	mask_headers,
	mask_payload,
	redact_with_variants,
	strip_partial_secret_tail,
)

#: `Carrier Integration Log` DocType adı.
INTEGRATION_LOG_DOCTYPE: str = "Carrier Integration Log"

#: Sözleşmedeki Select seçenekleri — TEK KAYNAK `logistics/constants.py`.
#: Geriye dönük adlar korunur (`http_client` ve testler bu adları kullanıyor).
VALID_OPERATIONS: frozenset[str] = INTEGRATION_LOG_OPERATIONS
VALID_DIRECTIONS: frozenset[str] = INTEGRATION_LOG_DIRECTIONS

#: Gövde başına saklanan azami bayt. Taşıyıcı yanıtları (etiket base64'ü, toplu
#: takip yanıtı) megabaytlara çıkabiliyor; log tablosu arşiv değil teşhis aracı.
MAX_BODY_BYTES: int = 64 * 1024

#: MASKELENEN ALANLARIN TEK KAYNAĞI.
#:
#: Eskiden liste DocType controller'ında elle kopyalanıyordu ve iki katman aynı
#: kör noktayı paylaşıyordu: `error_message` ikisinde de yoktu, oysa oraya
#: `requests`'in bağlantı hatası metni geliyor ve o metin TAM URL'i query
#: string'iyle (`?musteri_kodu=42&sifre=SECRET`) taşıyor.
#:
#: KAPSAM: bu demet YAZICININ gövde/metin alanlarını sayar. Sözleşmeye
#: (`contract.py::PROVISIONAL_ENTITIES["integration_log"]["masked_fields"]`)
#: bildirilen küme ise `CONTROLLER_MASKED_FIELDS`'tir — panele FİİLEN maskelenen
#: alanların TAMAMI bildirilmelidir (aşağıdaki gerekçeye bkz.). İki demet arası
#: fark testle sabitlenmiştir.
MASKED_LOG_FIELDS: tuple[str, ...] = ("request_body", "response_body", "error_message")

#: DocType controller'ının (`carrier_integration_log.py::before_insert`) maskelediği
#: alanlar — sözleşme demetinden TÜRETİLİR, elle kopyalanmaz.
#:
#: NEDEN `error_code` FAZLADAN:
#: 	`write_integration_log` `error_code`'u `_mask_short_text`'ten geçiriyor ama
#: 	`MASKED_LOG_FIELDS` onu içermiyordu; sonuç, yazıcıyı ATLAYAN yolun (veri
#: 	taşıma script'i, fixture) `error_code`'u hiç maskelememesiydi — iki katman
#: 	arasında ÖLÇÜLMÜŞ bir asimetri. Kontrol edilen alan listesinin doğru
#: 	referansı sözleşme değil YAZICININ DAVRANIŞIDIR: controller yazıcıyla aynı
#: 	alanları kapatmalı. `error_code` `Data` alanıdır ve `E-<jeton>` gibi bir
#: 	değeri taşıyabilir (`AUTH_FAILED sifre=...` biçimi adapter'lardan geliyor).
#:
#: SÖZLEŞME SAPMASI KAPATILDI (üç tur devredilmişti): `contract.py` üç alan
#: bildiriyor, gerçek maskeleme dördünü kapsıyordu — panele EKSİK bildirim.
#: Sözleşme artık BU demetten türetilir; sapma testle kilitli.
CONTROLLER_MASKED_FIELDS: tuple[str, ...] = (*MASKED_LOG_FIELDS, "error_code")

#: Sözleşme ihlali olan kaydın `error_code`'u — Select boş kaldığı için
#: satırın kendisi filtrelenebilir olmalı (Data alanı, standart filtrede).
CONTRACT_VIOLATION_CODE: str = "CONTRACT_VIOLATION"

#: `error_code` / `error_message` karakter sınırları (DocType: Data / Small Text).
_ERROR_CODE_LIMIT: int = 140
_ERROR_MESSAGE_LIMIT: int = 1000

#: Sözleşme ihlali ham değerinin zarfa yazılırken kırpıldığı sınır.
_VIOLATION_LIMIT: int = 200

#: Zarf iskeletinin gövdeye BIRAKMAK ZORUNDA olduğu asgari bütçe.
#:
#: İskelet bu payı bırakamıyorsa (`headers` sınırsız büyüyebilir) parçaları
#: düşürülür; aksi hâlde `budget` sıfırlanıyor ve döngü tavanı AŞAN metni
#: döndürüyordu (ölçüldü: 15,74x). Gövdesiz bir zarf teşhis değeri taşımaz.
_MIN_BODY_BUDGET: int = 512

#: `secret_values` HİÇ VERİLMEDİ nöbetçisi.
#:
#: `None` ile ayrımı bilinçli: `secret_values=None` "sır yok" DEMEK İSTEYEN bir
#: çağrı olabilir, argümanın hiç yazılmaması ise büyük olasılıkla UNUTULMASIDIR.
#: Değer-tabanlı redaksiyon birincil savunma olduğu için bu ikisini ayırmak
#: gerekir; imzayı zorunlu kılmak mevcut çağıranları (adapters/http_client.py)
#: kırardı, o yüzden ÇALIŞIR ama UYARIR.
_SECRET_VALUES_OMITTED: object = object()

#: Uyarı bir kez yazılır — her taşıyıcı çağrısında Error Log şişirmesin.
_omission_warned: bool = False


class IntegrationLogWriter(Protocol):
	"""`write_integration_log` imzasının tip sözleşmesi.

	Adapter katmanı (`logistics/adapters/http_client.py`) logger'ı enjekte
	edilebilir bir bağımlılık olarak alır; bu Protocol o parametreyi tipe
	bağlar ve testte no-op bir sahte yazıcının imza-uyumlu olmasını zorunlu
	kılar.

	DEĞER SEMANTİĞİ — hepsi bağlayıcı:

	* ``carrier``: **`Logistics Provider` DOCNAME'i.** Adapter registry kodu
	  DEĞİL. Bu turda bulunan kritik hatanın kök nedeni buydu: registry
	  anahtarı (`aras`, `yurtici`) ile DocType adı karıştırıldığında Link
	  doğrulaması kaydı tamamen düşürüyordu. Sitedeki adlar: `AK`, `YK`,
	  `MNG`, `PTT`, `SK`, `UPS`, `DHL`, `FEDEX`.
	* ``carrier_account``: `Carrier Account` docname'i veya None.
	* ``shipment``: `Shipment` docname'i veya None.
	* ``operation``: `logistics.constants.INTEGRATION_LOG_OPERATIONS` üyesi.
	  Küme dışı bir değer kaydı DÜŞÜRMEZ; Select boş bırakılır, ham değer
	  `request_body._contract_violation`'a yazılır ve `error_code`
	  `CONTRACT_VIOLATION` olur.
	* ``direction``: `INTEGRATION_LOG_DIRECTIONS` üyesi (`outbound` = biz
	  taşıyıcıyı çağırdık, `inbound` = taşıyıcı bizi çağırdı/webhook).
	* ``request_body`` / ``response_body`` / ``request_headers`` /
	  ``error_message``: HAM verilir; maskeleme yazıcının içindedir. Çağıran
	  önceden maskelememelidir — çift maskeleme veri kaybettirir.
	* ``secret_values``: Bu çağrıda kullanılan sır materyalinin DEĞERLERİ
	  (API anahtarı, parola, imza). Değer-tabanlı redaksiyonun girdisidir ve
	  biçimden bağımsız çalışan tek savunmadır.
	* ``extra_secret_values``: AYRI KAYNAK — adapter'ın kendi ürettiği kısa
	  ömürlü sırlar (oturum jetonu, imza). `secret_values` ile BİRLEŞTİRİLİR
	  ama "argüman unutuldu" nöbetçisini SUSTURMAZ. Kimlik dokümanının
	  plaintext'i okunamadığında (`collect_secret_values` → `None`) çağıran
	  `secret_values`'ı hiç geçmez; bu kanal sayesinde adapter jetonu yine de
	  redakte edilir. İki kaynağı tek argümanda toplamak, birinin çözülememesi
	  hâlinde diğerini de düşürüyordu (ölçüldü).
	* Dönüş: oluşan log kaydının adı; yazılamadıysa `None`. **Asla fırlatmaz.**
	"""

	def __call__(
		self,
		*,
		carrier: str,
		operation: str,
		direction: str,
		succeeded: bool,
		carrier_account: str | None = ...,
		shipment: str | None = ...,
		http_status: int | None = ...,
		duration_ms: int | None = ...,
		attempt: int | None = ...,
		error_code: str | None = ...,
		error_message: str | None = ...,
		request_body: Any = ...,
		response_body: Any = ...,
		request_headers: Mapping | None = ...,
		is_retriable: bool | None = ...,
		secret_values: Iterable[str] | None = ...,
		extra_secret_values: Iterable[Any] | None = ...,
	) -> str | None: ...


def write_integration_log(
	*,
	carrier: str,
	operation: str,
	direction: str,
	succeeded: bool,
	carrier_account: str | None = None,
	shipment: str | None = None,
	http_status: int | None = None,
	duration_ms: int | None = None,
	attempt: int | None = None,
	error_code: str | None = None,
	error_message: str | None = None,
	request_body: Any = None,
	response_body: Any = None,
	request_headers: Mapping | None = None,
	is_retriable: bool | None = None,
	secret_values: Iterable[str] | None | object = _SECRET_VALUES_OMITTED,
	extra_secret_values: Iterable[Any] | None = None,
) -> str | None:
	"""Bir taşıyıcı API çağrısını entegrasyon loguna yazar.

	Değer semantiği için `IntegrationLogWriter` Protocol docstring'ine bakın —
	özellikle `carrier`'ın `Logistics Provider` DOCNAME'i olduğu kuralına.

	Args:
		carrier: `Logistics Provider` DOCNAME'i (zorunlu).
		operation: `create_shipment | cancel | label | quote | track | webhook`.
		direction: `outbound | inbound`.
		succeeded: Çağrı başarılı mı.
		carrier_account: İlgili `Carrier Account` (varsa).
		shipment: İlgili `Shipment` (varsa).
		http_status: Yanıtın HTTP durumu.
		duration_ms: Çağrı süresi (ms).
		attempt: Kaçıncı deneme (yeniden çalıştırma sayacı).
		error_code: Kararlı hata kodu — MASKELENİR.
		error_message: Operatöre gösterilecek hata metni — MASKELENİR.
		request_body: İstek gövdesi — kırpılır, MASKELENİR.
		response_body: Yanıt gövdesi — kırpılır, MASKELENİR.
		request_headers: İstek başlıkları — MASKELENİR ve istek gövdesine katlanır.
		is_retriable: Yeniden deneme anlamlı mı.
		secret_values: Bu çağrıda kullanılan sır DEĞERLERİ — birebir redakte edilir.
			**Sır yoksa açıkça `()` geçin.** Argümanın hiç yazılmaması birincil
			savunmayı sessizce kapatır ve uyarı loglanır.
		extra_secret_values: Adapter'ın ürettiği kısa ömürlü sırlar — AYRI kanal,
			nöbetçiyi susturmaz (bkz. `IntegrationLogWriter`).

	Returns:
		Oluşan log kaydının adı; yazılamadıysa `None`.
	"""
	try:
		secrets = build_secret_variants(
			_merge_secret_sources(_resolve_secret_values(secret_values), extra_secret_values)
		)
		operation_value, operation_raw = _split_choice("operation", operation, VALID_OPERATIONS, secrets)
		direction_value, direction_raw = _split_choice("direction", direction, VALID_DIRECTIONS, secrets)
		violations = {
			key: value
			for key, value in (("operation", operation_raw), ("direction", direction_raw))
			if value is not None
		}

		doc_payload: dict[str, Any] = {
			"doctype": INTEGRATION_LOG_DOCTYPE,
			"carrier": carrier,
			"carrier_account": carrier_account,
			"shipment": shipment,
			"operation": operation_value,
			"direction": direction_value,
			"succeeded": 1 if succeeded else 0,
			"http_status": _coerce_int(http_status),
			"duration_ms": _coerce_int(duration_ms),
			"attempt": _coerce_int(attempt),
			"error_code": _mask_short_text(error_code, _ERROR_CODE_LIMIT, secrets)
			or (CONTRACT_VIOLATION_CODE if violations else None),
			"error_message": _mask_short_text(error_message, _ERROR_MESSAGE_LIMIT, secrets),
			"request_body": _serialize_request(request_body, request_headers, violations, secrets),
			"response_body": _serialize_body(response_body, secrets),
			"is_retriable": None if is_retriable is None else (1 if is_retriable else 0),
		}

		doc = frappe.get_doc(doc_payload)
		# ignore_permissions GEREKÇESİ: bu kayıt bir SİSTEM gözlemidir, kullanıcı
		# girdisi değil. Yazan taraf (adapter/webhook) çağrıyı yapan kullanıcının
		# oturumunda koşuyor olabilir ve o kullanıcının bu DocType'ta `create`
		# hakkı BİLEREK yok — log platform operasyon verisidir, satıcıya hiç
		# açılmaz (bkz. logistics/permissions.py). İzin kontrolü açık bırakılsaydı
		# gözlem, gözlenenin yetkisine bağlı olurdu: yetkisiz kullanıcının hatalı
		# çağrısı hiç loglanmaz, yani en çok ihtiyaç duyulan satır kaybolurdu.
		# Tenant alanları (carrier / carrier_account / shipment) yine doğru
		# doldurulur; atlanan tek şey ÇAĞIRANIN yazma yetkisi.
		# ignore_mandatory GEREKÇESİ: yalnız sözleşme ihlali olan kayıtta açılır.
		# İhlalde Select alanı BOŞ bırakılıyor (aşağıya bkz.) ve alan `reqd`
		# olduğu için zorunluluk kontrolü kaydı düşürürdü. Kural 3 gereği kayıt
		# yaşamalı; boşluk zaten ihlalin görünür işareti.
		doc.insert(ignore_permissions=True, ignore_mandatory=bool(violations))
		return doc.name

	except Exception:  # noqa: BLE001 — sözleşme: log yazımı iş akışını KIRMAZ
		# Buradan istisna sızarsa taşıyıcı çağrısı başarılı olduğu halde işlem
		# başarısız görünürdü. Sessizce yutmuyoruz: traceback Error Log'a yazılır
		# — ama o yazma da DB'ye gider ve DB çöktüyse o da patlar, bu yüzden
		# `safe_log_error` ile sarılı.
		safe_log_error(traceback_text(), "logistics.integration.write_integration_log")
		return None


def _merge_secret_sources(
	primary: Iterable[Any] | None,
	extra: Iterable[Any] | None,
) -> Iterable[Any] | None:
	"""İki AYRI sır kaynağını tek arama listesinde birleştirir.

	Kaynakların ayrı tutulmasının gerekçesi `IntegrationLogWriter`
	docstring'inde: kimlik dokümanı çözülemediğinde çağıran `secret_values`'ı
	hiç geçmez (nöbetçi tetiklensin diye), ama adapter'ın ürettiği jeton yine
	de redakte edilmelidir. Birleştirme BURADA, nöbetçi çözüldükten SONRA
	yapılır ki `extra` nöbetçiyi susturmasın.
	"""
	if not extra:
		return primary
	if primary is None:
		return list(extra)
	return [*primary, *extra]


def _resolve_secret_values(secret_values: Iterable[str] | None | object) -> Iterable[str] | None:
	"""Nöbetçiyi çözer ve argümanın UNUTULDUĞUNU bir kez raporlar."""
	global _omission_warned

	if secret_values is not _SECRET_VALUES_OMITTED:
		return secret_values  # type: ignore[return-value]

	if not _omission_warned:
		_omission_warned = True
		safe_log_error(
			"write_integration_log `secret_values` ARGÜMANI OLMADAN çağrıldı. Değer-tabanlı "
			"redaksiyon birincil savunmadır ve anahtar denylist'inin tanıyamadığı taşımalarda "
			"(ör. `X-Trace-Id: <jeton>`) TEK savunmadır. Sır yoksa açıkça `secret_values=()` geçin.",
			"logistics.integration.secret_values_omitted",
		)
	return None


def safe_log_error(message: str, title: str) -> None:
	"""`frappe.log_error`'ı HER KOŞULDA yutar. **PAYLAŞILAN — kopyalanmaz.**

	`log_error` bir `Error Log` satırı YAZAR. Log yazımının başarısız olmasının
	en olası nedeni DB yazma katmanının çökmesidir — yani tam da o anda
	`log_error` de patlar ve istisna, "asla fırlatmaz" sözleşmesini delerek
	dışarı sızar (konteynerde doğrulandı).

	TÜKETİCİLER: `carrier_integration_log.py` (DocType controller'ı) ve
	`jobs/integration_log_retention.py` (saklama işi) bu deseni AYNEN buradan
	alır. Kopyalanırsa biri düzeltilip diğeri unutulur; iki tur üst üste tam
	olarak bu oldu — önce saklama işi korumalı traceback desenini devralmadı,
	sonra düzeltmenin KENDİSİ `_safe_log_error`'ı yeniden yazdı.

	NEDEN TAKMA AD YOK: fonksiyon eskiden `_safe_log_error` adıyla tanımlanıp
	`safe_log_error = _safe_log_error` ile yayınlanıyordu. Aynı davranışın iki
	adı olması grep sonuçlarını ikiye katlıyor ve "modül içi private, dışarısı
	public" yanılsaması üretiyordu; kopya tam da bu karışıklıkta doğdu.
	`adapters/http_client.py`'deki eş desen TEK MEŞRU KOPYADIR (o modül log.py'ye
	bağımlı olamaz — kendi docstring'inde gerekçelendirilmiştir).
	"""
	try:
		frappe.log_error(message, title)
	except Exception:  # noqa: BLE001 — son savunma hattı; buradan çıkış yok
		pass


def traceback_text() -> str:
	"""Traceback'i güvenle alır; alınamıyorsa sabit bir metne düşer.

	`frappe.get_traceback()` SARMALAYICININ ARGÜMANI olarak çağrılırsa koruma
	işlemez — `safe_log_error(frappe.get_traceback(), ...)` deseninde istisna
	`safe_log_error`'a hiç girmeden dışarı sızar. Bu yüzden çağrı noktalarında
	her zaman `traceback_text()` kullanılır.
	"""
	try:
		return frappe.get_traceback()
	except Exception:  # noqa: BLE001 — traceback bile alınamıyorsa metin yeter
		return "traceback alınamadı"


def _split_choice(
	field: str, value: str, allowed: frozenset[str], secrets: tuple[str, ...] = ()
) -> tuple[str, str | None]:
	"""Select değerini sözleşmeye göre ayırır: (yazılacak değer, ihlal eden ham değer).

	NEDEN HAM DEĞER SÜTUNA YAZILMIYOR:
		Frappe `_validate_selects` seçenek listesi dışındaki her değeri
		`ValidationError` ile reddeder (`base_document.py`). Ham değeri sütuna
		yazmayı denemek kaydın TAMAMINI düşürürdü — oysa sözleşme dışı bir
		`operation`, tam da kaydedilmesi gereken adapter hatasının kanıtıdır.

	NEDEN BOŞ BIRAKILIYOR (uydurma bir seçenek yerine):
		Listeden rastgele geçerli bir değer seçmek (ör. `track`) log'u YANLIŞ
		yapardı; okuyan operatör var olmayan bir işlemi gerçekmiş gibi görürdü.
		Boş Select "bu satır sözleşmeye uymayan bir çağrıdan geldi" der. İhlal
		ayrıca `error_code = CONTRACT_VIOLATION` ile SORGULANABİLİR hale gelir,
		ham değer `request_body._contract_violation` zarfında saklanır.

	NEDEN ERROR LOG'A HAM DEĞER YAZILMIYOR:
		`Error Log` `Carrier Integration Log`'dan DAHA GENİŞ okuma yetkisine
		sahiptir ve `MASKED_LOG_FIELDS` oraya HİÇ uygulanmaz. Ham `operation`
		değeri (çağıran kontrolünde bir dizgi) f-string ile buraya yazıldığında
		`operation='sifre=SUPERSECRET123'` sızıyordu — modül docstring'inin
		"çağıranın maskelemeyi atlaması MÜMKÜN DEĞİL" invaryantını delen ikinci
		nokta buydu. Artık mesaja maskelenmiş hâl ve ham UZUNLUK yazılır;
		uzunluk teşhis için yeterli, sır için değersizdir.

	Args:
		field: Alan adı (yalnız mesajda).
		value: Çağıranın verdiği ham değer.
		allowed: Sözleşmedeki izinli küme.
		secrets: Önceden hesaplanmış sır varyantları (redaksiyon için).

	Returns:
		(yazılacak Select değeri, ihlal varsa ham değer aksi halde None)
	"""
	normalized = (value or "").strip()
	if normalized in allowed:
		return normalized, None

	safe = _mask_short_text(normalized, _VIOLATION_LIMIT, secrets) or ""
	safe_log_error(
		f"Sözleşme dışı {field} değeri: {safe!r} (ham uzunluk={len(normalized)}, izinli: {sorted(allowed)})",
		"logistics.integration.invalid_choice",
	)
	return "", normalized


def _coerce_int(value: Any) -> int | None:
	"""Int alanları için güvenli dönüşüm; çevrilemeyen değer None olur."""
	if value is None:
		return None
	try:
		return int(value)
	except (TypeError, ValueError):
		return None


def _mask_short_text(text: str | None, limit: int, secrets: tuple[str, ...]) -> str | None:
	"""`error_code` / `error_message` için: ÖNCE kırp, sonra maskele + redakte et.

	Bu alanlar eskiden yalnız kırpılıyordu. Oysa `error_message`'a
	`f"{type(exc).__name__}: {exc}"` geliyor ve `requests`'in bağlantı hatası
	metni TAM URL'i query string'iyle taşıyor — kimlik bilgisi ham düşüyordu
	(konteynerde doğrulandı).

	KIRPMA SINIRINDA YARIM SIR — `_mask_with_truncation`'ın KARDEŞ BULGUSU:
		Gövde yolu bu sınıfı `strip_partial_secret_tail` ile kapatmıştı; bu
		fonksiyon AYNI sözleşmeyi (KIRP → MASKELE) uyguladığı halde düzeltmeyi
		DEVRALMAMIŞTI. Ölçüldü (9. tur): `'SESSIONKEY_' + 'Z'*300` (311 karakter)
		1000. karakter sınırına denk getirildiğinde sırrın ilk **100** karakteri,
		`error_code`'un 140 sınırında ilk **105** karakteri sütuna HAM yazıldı —
		birebir eşleşen redaksiyon yarım kalmış ön eki göremiyor. PEM özel
		anahtar, SAML assertion ve uzun bearer jetonu tam bu sınıfta.

	ELLİPSİS EN SONDA — SIRA BAĞLAYICI:
		Eski sürüm `…` (U+2026) karakterini kırpma anında ekliyordu. O karakter
		metnin kuyruğuna yapıştığı için `strip_partial_secret_tail`'in ÖN EK
		eşleşmesini bozar (`'...ZZZ…'` hiçbir varyantın öneki değildir) — yani
		düzeltme sonradan eklense bile ETKİSİZ kalırdı (ölçüldü). Bu yüzden
		sıra: kırp → maskele → redakte et → yarım sır kuyruğunu kes → (maskeleme
		metni uzattıysa) TEKRAR kırp ve TEKRAR kes → EN SON `…` ekle.

	İkinci kesme sonrası tavan korunur: `strip_partial_secret_tail` en fazla
	`_MIN_TAIL_PREFIX` (4) karakteri `MASK` (3 karakter) ile değiştirir, yani
	metni UZATAMAZ.

	ELLİPSİS'E BÜTÇE AYRILIR — 10. TURDA ÖLÇÜLEN KAYIT DÜŞMESİ:
		9. tur `…`'i EN SONA taşıyarak sızıntıyı gerçekten kapattı ama hiçbir
		kırpma adımı ona YER AYIRMIYORDU; çıktı `limit + 1` uzunluğunda çıkıyordu
		(ölçüldü: girdi 141 → çıktı 141, girdi 200 → çıktı 141, tavan 140).
		`error_code` bir `Data` alanıdır ve Frappe `_validate_length` 141 karakteri
		`CharacterLengthExceededError` ile reddeder → `write_integration_log`'un
		dış `except`'i yakalar → `None` döner ve **SATIR HİÇ YAZILMAZ** (ölçüldü:
		`error_code` 140 karakter → KAYIT YAZILDI, 200 karakter → KAYIT DÜŞTÜ).
		Yani 9. turda `RecursionError` ve anahtar-TÜRÜ yolları kapatılırken
		UZUNLUK yolu açılmış, "saldırgan denetim izini bastırabilir" sınıfı geri
		gelmişti — 130.000 örneklik fuzz'da 2.717 tavan aşımı sayıldı.

		Bugün her kırpma `limit - 1`e yapılır ve `…` sonradan eklenir; nihai
		uzunluk HER KOŞULDA `limit`i aşmaz (fuzz sonrası: 0 aşım, ham sır ön eki
		yine 0). Ellipsis EN SONDA kaldığı için 9. turun sıra kuralı bozulmaz.
	"""
	if text is None or text == "":
		return None

	# `…` (U+2026) TEK karakter yer kaplar; kırpma sınırı ona bütçe AYIRIR.
	budget = limit - 1
	value = str(text)
	truncated = len(value) > limit
	if truncated:
		value = value[:budget]

	masked = mask_payload(value)
	if not isinstance(masked, str):  # pragma: no cover — str girdide str döner
		masked = str(masked)
	masked = redact_with_variants(masked, secrets)
	if truncated and secrets:
		masked = strip_partial_secret_tail(masked, secrets)

	# Maskeleme metni uzatabilir (`***` eklenmesi); sütun sınırını koru. Kırpma
	# olacaksa tavan `budget`tir (ellipsis payı), olmayacaksa `limit`. Bu İKİNCİ
	# kırpma yeni bir yarım sır üretebileceği için kuyruk yeniden denetlenir.
	if len(masked) > (budget if truncated else limit):
		masked = masked[:budget]
		if secrets:
			masked = strip_partial_secret_tail(masked, secrets)
		truncated = True

	return f"{masked}…" if truncated else masked


# ---------------------------------------------------------------------------
# Gövde serileştirme — KIRP, sonra MASKELE
# ---------------------------------------------------------------------------


def _serialize_request(
	body: Any,
	headers: Mapping | None,
	violations: dict[str, str] | None,
	secrets: tuple[str, ...],
) -> str | None:
	"""İstek gövdesini (varsa başlık ve sözleşme ihlaliyle) maskeleyip metne çevirir.

	KARAR — başlıklar için ayrı sütun AÇILMADI: sözleşme
	(`contract.py::INTEGRATION_LOG_FIELDS`) 16 alanla bağlayıcı ve içinde
	`request_headers` yok. Başlıkları düşürmek teşhis değeri olan veriyi
	(hangi içerik tipi, hangi idempotency anahtarı) kaybettirirdi; bu yüzden
	maskelenmiş başlıklar `request_body`'ye zarfla katlanır.

	KARAR — ZARF ANAHTAR SIRASI: `_truncated` → `_contract_violation` →
	`headers` → `body`. Eskiden `body` ilk sıradaydı ve kırpma önce METAVERİYİ
	yiyordu: 64 KB'ı aşan bir istekte sözleşme ihlali kaydı ve başlıklar
	kayboluyor, kalan gövdenin kuyruğu duruyordu. Artık gövde SONDA — kırpma
	yalnız en ucuz veriyi budar.
	"""
	masked_headers = mask_headers(headers) if headers else {}
	if masked_headers and secrets:
		masked_headers = _redact_deep(masked_headers, secrets)

	masked_body, truncated_bytes = _mask_with_truncation(body, secrets)

	if not masked_headers and not violations and truncated_bytes is None:
		return _to_text(masked_body)

	envelope: dict[str, Any] = {}
	if truncated_bytes is not None:
		envelope["_truncated"] = {"field": "body", "original_bytes": truncated_bytes}
	if violations:
		# HAM DEĞER ZARFA GİRMEZ: `violations` çağıranın verdiği dizgidir ve
		# doğrudan `json.dumps` ile sütuna yazılıyordu — ne `mask_payload` ne
		# redaksiyon dokunuyordu (ölçüldü: `operation='sifre=SUPERSECRET123'` +
		# `secret_values=['SUPERSECRET123']` → `request_body` içinde HAM).
		envelope["_contract_violation"] = {
			key: _mask_short_text(value, _VIOLATION_LIMIT, secrets) or "" for key, value in violations.items()
		}
	if masked_headers:
		envelope["headers"] = masked_headers
	envelope["body"] = masked_body

	return _serialize_envelope(envelope, secrets)


def _serialize_body(body: Any, secrets: tuple[str, ...]) -> str | None:
	"""Yanıt gövdesini kırpar, maskeler ve metne çevirir.

	Kırpma olduğunda `{"_truncated": {...}, "body": "..."}` zarfına geçilir.

	KARAR — kırpma bilgisi YAPISAL alana taşındı: eski sürüm `…[kırpıldı,
	toplam N bayt]` sonekini JSON'un DIŞINA ekliyordu, sonuç ayrıştırılamaz
	bir metindi ve F3 ekranı gövdeyi hiç gösteremiyordu. Zarf yaklaşımında
	dış JSON HER ZAMAN geçerlidir; `body` bir JSON STRING değeridir, içeriği
	yarım kalmış olsa bile ayrıştırmayı bozmaz.
	"""
	if body is None:
		return None

	masked, truncated_bytes = _mask_with_truncation(body, secrets)
	if truncated_bytes is None:
		return _to_text(masked)

	return _serialize_envelope(
		{
			"_truncated": {"field": "body", "original_bytes": truncated_bytes},
			"body": masked,
		},
		secrets,
	)


def _mask_with_truncation(body: Any, secrets: tuple[str, ...]) -> tuple[Any, int | None]:
	"""Gövdeyi ÖNCE kırpar, SONRA maskeler.

	Sıra kritik: eski sürümde 50 MB'lık bir gövde tam boy decode ediliyor,
	JSON'a ayrıştırılıyor, megabaytlarca metin regex'ten geçiyor ve ancak
	sonunda 64 KB'a iniyordu — maskelemenin maliyeti gövde boyutuyla
	sınırsız büyüyordu.

	KIRPMA SINIRINDA YARIM SIR — ölçülmüş sızıntı:
		Redaksiyon BİREBİR eşleşme yapar; kırpma bir sırrın ortasına denk
		geldiğinde geriye kalan ÖN EK hiçbir varyantla eşleşmez ve HAM kalır
		(ölçüldü: 308 karakterlik sır 64 KB sınırına denk getirildiğinde ilk 202
		karakteri ham çıktı). PEM özel anahtar, SAML assertion ve uzun bearer
		jetonu tam bu sınıfta. `strip_partial_secret_tail` kırpılmış metnin
		kuyruğunu varyantların GERÇEK ön eklerine karşı denetler ve keser.

	Returns:
		(maskelenmiş gövde, kırpıldıysa orijinal bayt sayısı aksi halde None)
	"""
	if body is None:
		return None, None

	prepared, original_bytes = _truncate_input(body)
	masked = mask_payload(prepared, secret_values=None)
	if secrets:
		masked = _redact_deep(masked, secrets)
		if original_bytes is not None and isinstance(masked, str):
			masked = strip_partial_secret_tail(masked, secrets)
	return masked, original_bytes


def _truncate_input(body: Any) -> tuple[Any, int | None]:
	"""Maskelemeden ÖNCE giriş noktasında kırpar.

	* bytes / str: doğrudan bayt dilimlenir.
	* Mapping / list: `iterencode` ile ARTIMLI serileştirilir ve sınır aşılınca
	  DURULUR — 50 MB'lık bir sözlüğün tamamı hiç belleğe yazılmaz. Sınır
	  aşılmadıysa ORİJİNAL nesne döner (yapısal maskeleme metin regex'inden
	  daha güvenilir; küçük gövdede onu kaybetmenin anlamı yok). Serileştirme
	  BAŞARISIZ olursa tavan kararı BİLİNEMEZ — `_truncate_structure` o durumda
	  güvenli yöne gider; ayrıntı orada.
	* Diğer türler: dokunulmaz (maskeleme `<TypeName>`e indirger).
	"""
	if isinstance(body, (bytes, bytearray, memoryview)):
		raw = bytes(body)
		if len(raw) <= MAX_BODY_BYTES:
			return raw, None
		return raw[:MAX_BODY_BYTES], len(raw)

	if isinstance(body, str):
		encoded = body.encode("utf-8")
		if len(encoded) <= MAX_BODY_BYTES:
			return body, None
		return encoded[:MAX_BODY_BYTES].decode("utf-8", errors="ignore"), len(encoded)

	if isinstance(body, (Mapping, list, tuple, set, frozenset)):
		return _truncate_structure(body)

	return body, None


def _truncate_structure(body: Any) -> tuple[Any, int | None]:
	"""Yapısal gövdeyi sınıra göre kırpar; serileştirilemiyorsa ÖNCE onarır.

	`_iterencode_bounded` "BİLMİYORUM" (`None`) dediğinde tavan kararı
	verilemez — ve eski sürüm bunu "taşma YOK" sayıp ORİJİNALİ kırpmadan geri
	veriyordu, yani `MAX_BODY_BYTES` SESSİZCE devre dışı kalıyordu (ölçüldü:
	`{('tuple','key'): 1, 'pad': 'A'*300000}` → `overflow=None`, 300 KB
	kırpılmadı). Güvenli yön KIRPMAK olduğu için burada önce anahtarlar
	onarılır (`_coerce_json_keys`) ve ölçüm TEKRARLANIR; onarım da yetmezse
	(döngüsel referans, `RecursionError`) gövde teşhis işaretine indirgenir —
	kayıt YİNE de yazılır.

	Anahtar onarımının YAN FAYDASI: `b'sifre'` anahtarı `'sifre'` olur ve
	`mask_payload`'ın anahtar denylist'i onu ARTIK GÖREBİLİR (`bytes` anahtar
	denylist'i atlıyordu — bkz. `masking.py::_normalize_key`, ayrı bulgu).
	"""
	text, overflow = _iterencode_bounded(body, MAX_BODY_BYTES)
	if overflow is None:
		try:
			repaired = _coerce_json_keys(body)
		except Exception:  # noqa: BLE001 — onarım DENEMESİ kaydı düşüremez (madde 1/3)
			# `Mapping.items()` / `__iter__` çağıranın kontrolünde ve KORUMASIZDI:
			# `items()` `TypeError` atan bir gövde buradan dış `except`'e çıkıp
			# satırın tamamını düşürüyordu (ölçüldü, 10. tur).
			return {"_serialization_failed": _safe_type_name(body)}, None
		text, overflow = _iterencode_bounded(repaired, MAX_BODY_BYTES)
		if overflow is None:
			return {"_serialization_failed": _safe_type_name(body)}, None
		body = repaired

	if not overflow:
		return body, None

	encoded = text.encode("utf-8")
	return encoded[:MAX_BODY_BYTES].decode("utf-8", errors="ignore"), len(encoded)


def _iterencode_bounded(obj: Any, limit: int) -> tuple[str, bool | None]:
	"""JSON'u artımlı üretir ve `limit` aşılınca DURUR.

	`json.dumps` tamamını üretirdi; 50 MB'lık bir gövdede bu tek başına
	saniyeler ve yüzlerce megabayt demek. `iterencode` parça parça verdiği
	için sınır aşıldığı anda çıkabiliyoruz.

	SÖZLEŞME — ÜÇ DEĞERLİ İKİNCİ DÖNÜŞ:
		* `True`  — sınır AŞILDI (metin kırpılmış hâliyle döner).
		* `False` — sınır aşılmadı, metin TAM.
		* `None`  — **BİLMİYORUM**: gövde serileştirilemedi, boyut ölçülemedi.

		`None` eskiden `False` idi ve çağıran onu "taşma yok" diye okuyordu;
		sonuç, `MAX_BODY_BYTES` tavanının serileştirilemeyen HER gövdede sessizce
		kapanmasıydı. `None`'ı gören çağıran GÜVENLİ yöne gitmek ZORUNDADIR
		(bkz. `_truncate_structure`).

	Returns:
		(üretilen metin, sınır aşıldı mı / bilinmiyorsa None)
	"""
	chunks: list[str] = []
	size = 0
	try:
		encoder = json.JSONEncoder(ensure_ascii=False, default=str)
		for chunk in encoder.iterencode(obj):
			chunks.append(chunk)
			size += len(chunk.encode("utf-8"))
			if size > limit:
				return "".join(chunks), True
	except Exception:  # noqa: BLE001 — HER hata "BİLMİYORUM"dur; sözleşme korunur
		# GEREKÇE (10. tur): demet `(TypeError, ValueError, RecursionError)` idi ve
		# `default=str` içinden gelen BAŞKA bir istisna sınıfı (ör. `__str__`'ü
		# `KeyError` atan bir nesne) dışarı sızıp `write_integration_log`'un dış
		# `except`'ine düşerek SATIRIN TAMAMINI düşürüyordu (ölçüldü).
		# ÜÇ DEĞERLİ SÖZLEŞME BOZULMAZ: her yakalanan hata yine `None`
		# ("BİLMİYORUM") döner — `False` ("taşma yok") ASLA üretilmez, yani
		# çağıranın GÜVENLİ yöne gitme zorunluluğu aynen sürer.
		# Yarım kalan parçalar GEÇERSİZ JSON'dur; metin değil KARARSIZLIK döner.
		return "", None
	return "".join(chunks), False


def _safe_type_name(value: Any) -> str:
	"""Tür adını KORUMALI alır — teşhis işareti üretmek kaydı düşüremez.

	`type(value).__name__` pratikte patlamaz ama patolojik bir metaclass
	(`__getattr__` ile üretilen `__name__`) istisna fırlatabilir ve bu ifade
	`_json_text` ile `_truncate_structure`'ın SON ÇARE dallarında duruyor: tam da
	"artık hiçbir şey fırlatmamalı" denen noktada. Sabite düşmek bir teşhis
	kaybıdır, satırı kaybetmek denetim izinin kaybıdır (madde 3).
	"""
	try:
		return type(value).__name__
	except Exception:  # noqa: BLE001 — son savunma hattı; buradan çıkış yok
		return "unknown"


def _json_safe_key(key: Any) -> Any:
	"""`json.dumps`'ın kabul ETMEDİĞİ sözlük anahtarını metne indirger.

	`json` yalnız `str | int | float | bool | None` anahtarı kabul eder; başka
	her tür `TypeError` fırlatır. `bytes` anahtar egzotik DEĞİL:
	`urllib.parse.parse_qs(body_bytes)` doğrudan `bytes` anahtarlı sözlük üretir
	ve form-encoded taşıyıcı webhook'u (`direction='inbound'`) tam bu biçimdedir.
	`tuple` / `frozenset` anahtarlar da aynı sınıfta (ölçüldü).

	`json`'un kendi kabul ettiği türler DEĞİŞTİRİLMEZ — aksi hâlde `True`
	anahtarı `"true"` yerine `"True"` olurdu; onarım yolu davranışı gereksiz
	kaydırmamalı.
	"""
	if isinstance(key, (bytes, bytearray, memoryview)):
		return bytes(key).decode("utf-8", errors="replace")
	if key is None or isinstance(key, (str, int, float, bool)):
		return key
	return str(key)


def _coerce_json_keys(value: Any, depth: int = 0) -> Any:
	"""Yapıdaki TÜM sözlük anahtarlarını `json`'un kabul ettiği türe indirger.

	Değerlere DOKUNMAZ: yapısal maskeleme (`mask_payload`) metin regex'inden
	daha güvenilir ve bu onarım maskelemeden ÖNCE çalışır — yapıyı düzleştirmek
	savunmayı zayıflatırdı. Derinlik `_redact_deep` ile aynı gerekçeyle AÇIKÇA
	sayılır: onarımın kendisi `RecursionError` ile log satırını düşüremez.
	"""
	if depth > MAX_MASK_DEPTH:
		return MASK

	if isinstance(value, Mapping):
		return {_json_safe_key(key): _coerce_json_keys(item, depth + 1) for key, item in value.items()}
	if isinstance(value, (list, tuple)):
		# `json` demeti zaten diziye çevirir; liste dönmek çıktıyı değiştirmez.
		return [_coerce_json_keys(item, depth + 1) for item in value]
	return value


def _json_text(value: Any) -> str:
	"""`json.dumps`'ın KORUMALI hâli — metin döner, **ASLA fırlatmaz**.

	`_iterencode_bounded` `TypeError`'ı yakalıyordu ama `_to_text`,
	`_encoded_size` ve `_serialize_envelope` içindeki `json.dumps` çağrıları
	KORUMASIZDI: aynı `str` olmayan anahtar bu kez `write_integration_log`'un
	dış `except`'ine çıkıyor ve KAYIT TAMAMEN DÜŞÜYORDU (`None` döner, ölçüldü:
	`_serialize_body({b'sifre': b'x'})` → `TypeError`). Bu, modülün
	`RecursionError` için AÇIKÇA kapattığı "saldırgan denetim izini bastırabilir"
	sınıfının aynısıdır — `MAX_MASK_DEPTH` o yolu kapatmıştı, anahtar TÜRÜ yolu
	açık kalmıştı.

	KARAR — TEŞHİS KAYBI YERİNE KAYIT: sözleşme (madde 1) "asla fırlatmaz"
	diyor, ama `None` dönmek de bir kayıptır (madde 3: veri kaybetmez). Bu yüzden
	sırayla (1) doğrudan, (2) anahtarları onarılmış, (3) hiçbiri olmazsa
	`{"_serialization_failed": "<TypeName>"}` denenir; satır HER KOŞULDA yazılır.

	DEMET DEĞİL `Exception` — 10. TURDA ÖLÇÜLEN SÖZLEŞME DELİĞİ:
		İki `except` de `(TypeError, ValueError, RecursionError)` demetiydi;
		`default=str` KEYFİ bir `__str__` çağırır ve oradan gelen BAŞKA bir
		istisna sınıfı "ASLA fırlatmaz" sözleşmesini deliyordu. Ölçüldü
		(erişilemez ama sözleşme ihlali): `__str__`'ü `KeyError` atan bir nesne →
		`_json_text`, `_to_text`, `_encoded_size`, `_serialize_envelope` HEPSİ
		fırlatıyor, `write_integration_log` `None` dönüyordu. Proje kuralı
		gerekçesiz `except Exception`'ı yasaklar; gerekçe budur ve dar demet
		BURADA yanlış araçtır — yakalanan hata sınıfı DEĞİL, "serileştirilemedi"
		OLGUSU önemlidir. `BaseException` yakalanmaz: `KeyboardInterrupt` /
		`SystemExit` geçmeye devam eder.
	"""
	try:
		return json.dumps(value, ensure_ascii=False, default=str)
	except Exception:  # noqa: BLE001 — sözleşme: metin döner, ASLA fırlatmaz
		pass

	try:
		return json.dumps(_coerce_json_keys(value), ensure_ascii=False, default=str)
	except Exception:  # noqa: BLE001 — sözleşme: metin döner, ASLA fırlatmaz
		# `type(value).__name__` de KORUMALI: son çare dalı fırlatan tek ifadeyi
		# barındıramaz (bkz. `_safe_type_name`).
		return json.dumps({"_serialization_failed": _safe_type_name(value)}, ensure_ascii=False)


def _redact_deep(value: Any, secrets: tuple[str, ...], depth: int = 0) -> Any:
	"""Maskelenmiş yapıdaki tüm metin yapraklarında birebir redaksiyon.

	Derinlik AÇIKÇA sayılır: `mask_payload` gibi bu özyineleme de derin bir
	girdide `RecursionError` fırlatıp log satırını düşürebilirdi.

	YAPRAK REDAKSİYONU BURADA DEĞİL: metin yaprağı `masking.py`'nin
	`redact_with_variants`'ına devredilir. Bu modülde satır satır aynı bir
	`_redact` kopyası duruyordu; YAPI gezintisi (`_redact_deep`) log'a özgü
	olduğu için KALIR, dizgi değiştirme maskeleme modülünündür.

	ANAHTAR DA REDAKTE EDİLİR — 10. TURDA ÖLÇÜLEN SIZINTI:
		Eski sürüm yalnız DEĞER yapraklarını redakte ediyordu, `key` hiç
		dokunulmadan geçiyordu. Ölçüldü:

			mask_payload({'SUPERSECRET123': 'v'}, secret_values=['SUPERSECRET123'])
				-> {'SUPERSECRET123': 'v'}          ANAHTAR HAM
			mask_payload('{"SUPERSECRET123":"v"}', ...)
				-> {"***": "v"}                     JSON METNİ yolunda MASKELİ

		Yani `masking.py`'nin ilan ettiği **TEK KÜME KURALI** (aynı içerik dict /
		JSON metni / querystring olarak gelse de AYNI sonuç) ölçülerek ihlal
		ediliyordu. 9. turun `_coerce_json_keys` onarımı bunu AĞIRLAŞTIRDI:
		`bytes`/`tuple` anahtarlı gövdeler eskiden `TypeError` ile kaydı düşürüyor
		(kazara fail-closed), onarımdan sonra geçerli `str`'e çevrilip YAZILIYORDU
		— sır, redaksiyonun dokunmadığı TEK konuma taşınmıştı (uçtan uca ölçüldü:
		`request_body: {"SUPERSECRET123": ["1"]}`).

	SIRA BAĞLAYICI — ANAHTAR REDAKSİYONU BURADA, `_coerce_json_keys`'TE DEĞİL:
		`_mask_with_truncation` önce `mask_payload` (anahtar DENYLIST'i), sonra bu
		fonksiyonu çağırır. Redaksiyon onarım adımına taşınsaydı denylist `***`
		görürdü ve `sifre` anahtarını KAÇIRIRDI — onarımın yan faydası
		(`{b'sifre': 'X'}` → `{"sifre": "***"}`) kaybolurdu.

	AŞIRI MASKELEME YOK: yalnız `secret_values` ile eşleşen anahtarlar değişir.
	Teşhis anahtarları (`tracking_number`, `barcode`, `order_no`, `status_code`,
	`idempotency_key`, `request_id`, `hata_kodu`) ANAHTAR konumunda GÖRÜNÜR kalır
	— anahtar DENYLIST'i buraya hiç karışmaz.

	BİLİNEN VE SINIRLI KAYIP — ANAHTAR ÇAKIŞMASI: iki AYRI anahtar aynı sırra
	indirgenirse (`{'TOKEN1': 'a', 'TOKEN2': 'b'}`, ikisi de `secret_values`'ta)
	sonuç tek `'***'` anahtarı olur ve bir değer düşer. Ayırt edici bir son ek
	(`***#2`) eklemek TEK KÜME KURALINI delerdi: aynı içerik JSON METNİ olarak
	geldiğinde `redact_with_variants` düz dizgi değiştirmesi yapar ve son ek
	üretemez. İki yol arasındaki simetri, çakışan-anahtar vakasındaki tek değerin
	kaybından daha değerli sayıldı.
	"""
	if depth > MAX_MASK_DEPTH:
		return MASK

	if isinstance(value, str):
		return redact_with_variants(value, secrets)
	if isinstance(value, Mapping):
		return {
			(redact_with_variants(key, secrets) if isinstance(key, str) else key): _redact_deep(
				item, secrets, depth + 1
			)
			for key, item in value.items()
		}
	if isinstance(value, list):
		return [_redact_deep(item, secrets, depth + 1) for item in value]
	return value


def _serialize_envelope(envelope: dict[str, Any], secrets: tuple[str, ...] = ()) -> str:
	"""Zarfı JSON'a yazar ve sınırı AŞMAYACAK şekilde gövdeyi daraltır.

	Zarf metaverisi (`_truncated`, `_contract_violation`, `headers`) gövdeyi
	sınırın üstüne itebilir. O durumda gövdeye kalan bütçe hesaplanır ve gövde
	bir JSON STRING olarak kısaltılır — dış JSON GEÇERLİ kalır, yalnız `body`
	içeriği yarımdır. Böylece F3 ekranı zarfı her koşulda ayrıştırabilir.

	NEDEN "ÖLÇ VE YİNELE" — bütçe hesabı 2.0x aşıyordu:
		Eski sürüm bütçeyi HAM bayt üzerinden hesaplıyor, JSON KAÇIŞINI hiç
		saymıyordu. `"` → `\\"` ve `\\` → `\\\\` bir baytı iki bayta çıkarır;
		ölçüldü (limit 65.536): düz metin 65.548, tırnak-yoğun **130.963
		(2.00x)**, ters-bölü yoğun 130.963, satır-sonu yoğun 98.256. Alan
		`Code`/longtext olduğu için insert patlamıyordu — hata SESSİZDİ ve log
		tablosu iki katı hızla şişiyordu (gövde kısmen saldırgan kontrolünde).
		Artık serileştirilmiş GERÇEK boyut ölçülür ve sığana kadar yarılanır.

	İKİ EK DÜZELTME (QA turu):
		* `envelope_shrunk` bayrağı iskelet ölçüldükten SONRA ekleniyordu, yani
		  +22 baytı bütçeye hiç girmiyordu; artık ölçümden ÖNCE eklenir.
		* `truncated['envelope_shrunk'] = True` ÇAĞIRANIN iç sözlüğünü mutasyona
		  uğratıyordu; artık kopya üzerinde çalışılır.

	İSKELET DE BÜTÇELENİR (2.00x bulgusunun kardeşi, ölçüldü):
		Yalnız `body` daraltılıyordu; iskelet (`headers` + `_contract_violation`
		+ `_truncated`) SINIRSIZDI. `overhead > MAX_BODY_BYTES` olduğunda
		`budget` sıfıra düşüyor ve döngü ilk turda `budget == 0` dalından
		TAVANI AŞAN metni döndürüyordu — 2000 adet 500 baytlık başlıkla
		`_serialize_request` **1.031.244 bayt = tavanın 15,74 KATI** üretti
		(aynı çağrı düz gövdeyle 0,9998x, yani gövde tarafı doğruydu).
		Bugün ulaşılabilir değil (başlıkları `_build_headers` kuruyor) ama
		`Carrier Account.additional_config` serbest bir JSON alanı ve
		`Carrier Integration Manager` oraya yazabiliyor; gerçek adapter'lar o
		alanı başlığa taşıdığında yüzey açılır. Artık `_shrink_skeleton`
		sırasıyla `headers`'ı, sonra `_contract_violation`'ı düşürür; her
		düşürme çıktıda AÇIKÇA işaretlenir ve dış JSON geçerli kalır.
	"""
	text = _json_text(envelope)
	if len(text.encode("utf-8")) <= MAX_BODY_BYTES:
		return text

	skeleton = {key: value for key, value in envelope.items() if key != "body"}
	truncated = skeleton.get("_truncated")
	if isinstance(truncated, dict):
		# Çağıranın sözlüğünü DEĞİŞTİRME — kopya üzerinde işaretle.
		marked = dict(truncated)
		marked["envelope_shrunk"] = True
		skeleton["_truncated"] = marked
	else:
		skeleton["envelope_shrunk"] = True
	# Bayrak ÖLÇÜMDEN ÖNCE yerinde: iskelet artık nihai hâliyle tartılıyor.
	skeleton["body"] = ""
	overhead = _encoded_size(skeleton)

	if overhead > MAX_BODY_BYTES - _MIN_BODY_BUDGET:
		skeleton = _shrink_skeleton(skeleton)
		overhead = _encoded_size(skeleton)

	body_bytes = _to_text(envelope.get("body")) or ""
	budget = max(0, MAX_BODY_BYTES - overhead - 16)
	shrunk = dict(skeleton)

	# En kötü kaçış oranı 2x olduğu için döngü en fazla ~17 turda biter; yine de
	# GERÇEK boyut ölçülür, orana GÜVENİLMEZ. `budget == 0` dalı artık güvenli:
	# iskelet yukarıda tavanın altına indirildi.
	while True:
		candidate = body_bytes.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
		shrunk["body"] = strip_partial_secret_tail(candidate, secrets) if secrets else candidate
		text = _json_text(shrunk)
		if len(text.encode("utf-8")) <= MAX_BODY_BYTES or budget == 0:
			return text
		budget //= 2


def _encoded_size(value: Any) -> int:
	"""Serileştirilmiş GERÇEK bayt boyutu — JSON kaçışı dahil.

	`_json_text` üzerinden ölçülür: bu fonksiyon `_serialize_envelope`'un bütçe
	hesabını besler ve buradan fırlayan bir `TypeError` (bkz. `_json_text`)
	TÜM log satırını düşürürdü.
	"""
	return len(_json_text(value).encode("utf-8"))


def _shrink_skeleton(skeleton: dict[str, Any]) -> dict[str, Any]:
	"""Zarf iskeletini tavanın altına indirir; düşürülen her parça İŞARETLENİR.

	DÜŞÜRME SIRASI — en pahalıdan en değerliye:

	1. `headers`: tek sınırsız parça (adapter'ın koyduğu başlık sayısı/boyu
	   sözleşmeyle sınırlı değil). `_headers_dropped` bayrağı kalır.
	2. `_contract_violation`: alan başına 200 karakterle sınırlı, yani normalde
	   ~450 bayt; yine de tavanı dolduran patolojik bir durumda düşer ve
	   `_contract_violation_dropped` ile işaretlenir. İhlalin KENDİSİ
	   `error_code = CONTRACT_VIOLATION` ile sütunda sorgulanabilir kalır.
	3. Hiçbiri yetmezse iskelet minimuma indirilir: teşhis değeri olan tek şey
	   "zarf taştı" bilgisidir ve o da AÇIKÇA yazılır.

	`_truncated` HİÇ düşürülmez: kaç baytın kaybolduğunu söyleyen tek alan odur
	ve boyutu sabittir.
	"""
	shrunk = dict(skeleton)

	if "headers" in shrunk:
		shrunk.pop("headers")
		shrunk["_headers_dropped"] = True
		if _encoded_size(shrunk) <= MAX_BODY_BYTES - _MIN_BODY_BUDGET:
			return shrunk

	if "_contract_violation" in shrunk:
		shrunk.pop("_contract_violation")
		shrunk["_contract_violation_dropped"] = True
		if _encoded_size(shrunk) <= MAX_BODY_BYTES - _MIN_BODY_BUDGET:
			return shrunk

	return {
		"_truncated": shrunk.get("_truncated") or {"field": "body", "envelope_shrunk": True},
		"_envelope_overflow": True,
		"body": "",
	}


def _to_text(value: Any) -> str | None:
	"""Maskelenmiş gövdeyi sütuna yazılacak metne çevirir. **Fırlatmaz.**

	Koruma gerekçesi `_json_text` docstring'inde: `str` olmayan bir sözlük
	anahtarı burada `TypeError` fırlatıp `write_integration_log`'un dış
	`except`'ine düşüyor ve kaydı TAMAMEN düşürüyordu.
	"""
	if value is None:
		return None
	if isinstance(value, str):
		return value
	return _json_text(value)


__all__ = [
	"CONTRACT_VIOLATION_CODE",
	"CONTROLLER_MASKED_FIELDS",
	"INTEGRATION_LOG_DOCTYPE",
	"MASKED_LOG_FIELDS",
	"MAX_BODY_BYTES",
	"VALID_DIRECTIONS",
	"VALID_OPERATIONS",
	"IntegrationLogWriter",
	"safe_log_error",
	"traceback_text",
	"write_integration_log",
]

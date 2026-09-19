# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Takip event isleme servisi (TUR-112'nin webhook alt-kumesi — 09-BE BE-4).

`process_webhook_event`, guest webhook ucunun (`api/v1/logistics_webhook.py`)
`frappe.enqueue` ile cagirdigi asenkron isleyicidir. HMAC imza dogrulamasi
ENDPOINT'te bitmistir (W1) — buraya ulasan govdenin kimligi KANITLANMIS kabul
edilir; bu modul yalniz ayristirir, katalogla esler ve durum gecisini yapar.
Adapter cozumu ve `parse_webhook` YALNIZ burada (job'da) denenir (W1).

Hata siniflandirmasi — her yol `write_integration_log` ile izlenebilir ve
HICBIR yol job'i patlatmaz (endpoint coktan 200 dondu; job'un patlamasi
RQ retry'inda ayni sonucu tekrar tekrar uretirdi):

	CAPABILITY_UNSUPPORTED   adapter kayitli degil / WEBHOOK yetenegi yok (AC-11)
	PARSE_FAILED             adapter govdeyi ayristiramadi (CarrierAPIError)
	SHIPMENT_NOT_FOUND       tracking_number cozulmedi VEYA tenant guard (AC-10)
	STATUS_UNMAPPED          katalog eslemesi yok — durum DEGISMEZ, succeeded=1 (AC-9)
	SHIPMENT_STATE_INVALID   gecis matrisi reddetti (gec/sirasiz tasiyici event'i)
	EVENT_PROCESSING_FAILED  beklenmeyen istisna — DIGER event'leri dusurmez

`normalize_carrier_status` webhook'a ozgu hicbir sey bilmez: poll dilimi
(11-BE) ayni fonksiyonu kullanacak (bu dilimde poll entegrasyonu YOK).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import frappe
from frappe import _

from tradehub_core.logistics.adapters.registry import get_adapter
from tradehub_core.logistics.exceptions import (
	CarrierAPIError,
	CarrierCapabilityError,
	CarrierNotFoundError,
	ShipmentStateError,
)
from tradehub_core.logistics.integration.log import safe_log_error, write_integration_log
from tradehub_core.logistics.integration.secrets import collect_secret_values
from tradehub_core.logistics.services.shipment_service import transition_status

if TYPE_CHECKING:
	from collections.abc import Mapping

	from frappe.model.document import Document

	from tradehub_core.logistics.adapters.base import BaseCarrierAdapter, TrackingEvent

__all__ = ["normalize_carrier_status", "process_webhook_event"]

#: `normalize_carrier_status` request-scope cache namespace'i (prefix kurali: `tc:`).
_STATUS_MAP_CACHE_NS: str = "tc:logistics:status_map"

#: `safe_log_error` baslik alani — Error Log'da filtrelenebilir sabit kimlik.
_LOG_TITLE: str = "logistics.tracking_service.process_webhook_event"


# ---------------------------------------------------------------------------
# Enqueue hedefi (BE-3 → frappe.enqueue)
# ---------------------------------------------------------------------------


def process_webhook_event(account: str, raw_body: bytes | str, headers: dict) -> None:
	"""Kimligi endpoint'te kanitlanmis inbound webhook govdesini isler.

	Cagiran: `api/v1/logistics_webhook.py::receive_carrier_webhook` — imza,
	boyut ve dedupe kontrolleri ORADA bitti. Bu fonksiyon job baglaminda
	kosar ve ASLA firlatmaz: her sonuc ya inbound integration log'a ya da
	(hesap silinmisse) Error Log'a duser.

	Args:
		account: `Carrier Account` docname'i (endpoint dogrulamayi bu hesapla yapti).
		raw_body: Ham webhook govdesi. Enqueue serializasyonunda `str`'e donusmus
			olabilir; adapter sozlesmesi `bytes` istedigi icin UTF-8 ile geri cevrilir.
		headers: Istek basliklari (adapter ayristirmada kullanabilir).
	"""
	account_doc = _load_account(account)
	if account_doc is None:
		return

	body: bytes = raw_body.encode("utf-8") if isinstance(raw_body, str) else bytes(raw_body)
	# Sir toplama sozlesmesi (integration/secrets.py): `None` donerse
	# `secret_values` argumani HIC GECILMEZ — yarim kume, log yazicisinin
	# "unutuldu" nobetcisini susturur (olculmus ariza, modul docstring'i).
	secrets: frozenset[str] | None = collect_secret_values(account_doc)

	adapter = _resolve_adapter(account_doc, body, secrets)
	if adapter is None:
		return

	events = _parse_events(adapter, account_doc, body, headers, secrets)
	if events is None:
		return

	for event in events:
		try:
			_process_single_event(account_doc, event, secrets)
		except Exception:
			# Gerekce: her event BAGIMSIZ islenir (spec madde 5) — birinin
			# beklenmedik hatasi (DB kopmasi haric her sey) digerlerini
			# dusurmemeli. Istisna YUTULMAZ: traceback Error Log'a, kayit
			# failed inbound log'a yazilir; siniflandirilmis yollar
			# (_process_single_event) zaten kendi kodlariyla loglandi.
			safe_log_error(frappe.get_traceback(), _LOG_TITLE)
			_write_webhook_log(
				account_doc,
				secrets,
				succeeded=False,
				error_code="EVENT_PROCESSING_FAILED",
				error_message=_("Webhook event'i islenirken beklenmeyen hata olustu."),
				request_body=event.raw,
			)


# ---------------------------------------------------------------------------
# Katalog eslemesi — poll (11-BE) ile paylasilan saf lookup
# ---------------------------------------------------------------------------


def normalize_carrier_status(carrier: str, code: str) -> str | None:
	"""Tasiyici durum kodunu `Carrier Status Mapping` katalogundan cozer.

	Webhook'a ozgu hicbir sey bilmez — poll dilimi (11-BE) ayni fonksiyonu
	kullanacak. Eslesme yoksa `None` doner; "eslesmedi"nin nasil ele
	alinacagi (STATUS_UNMAPPED vb.) cagiranin karari.

	Onbellek: katalog istek/job basina BIR kez okunur. NOT — surum sapmasi:
	bu kurulumdaki Frappe v15.116.1'de `frappe.client_cache` YOK (olculdu,
	bkz. media/pipeline_flags.py); v15 request-scope karsiligi
	`frappe.local_cache` kullanilir. Cross-request onbellek BILEREK yok:
	katalog guncellemesi bir sonraki webhook'ta aninda etki etmeli.

	Args:
		carrier: `Logistics Provider` docname'i (autoname `field:provider_code`).
		code: Tasiyicinin ham durum kodu (orn. "OUT_FOR_DELIVERY").

	Returns:
		Eslesen internal_status (ShipmentStatus degeri) ya da `None`.
	"""
	code_key: str = str(code or "").strip()
	if not carrier or not code_key:
		return None
	mapping: dict[str, str] = frappe.local_cache(
		_STATUS_MAP_CACHE_NS, carrier, lambda: _load_status_map(carrier)
	)
	return mapping.get(code_key)


def _load_status_map(carrier: str) -> dict[str, str]:
	"""Bir tasiyicinin tum durum eslemelerini tek sorguda okur.

	`frappe.get_all` GEREKCESI: `Carrier Status Mapping` tenant'siz bir
	sistem KATALOGUDUR (yalniz System/Logistics Manager yazar) ve okuma
	sistem isidir — job baglaminda oturum Guest olabilir; `get_list`'in
	permission katmani mesru sistem okumasini bosaltirdi.
	"""
	rows = frappe.get_all(
		"Carrier Status Mapping",
		filters={"carrier": carrier},
		fields=["carrier_status_code", "internal_status"],
	)
	return {str(row.carrier_status_code).strip(): row.internal_status for row in rows}


# ---------------------------------------------------------------------------
# Ic adimlar
# ---------------------------------------------------------------------------


def _load_account(account: str) -> Document | None:
	"""Carrier Account'u yukler; silinmisse Error Log'a dusup `None` doner."""
	try:
		return frappe.get_doc("Carrier Account", account)
	except frappe.DoesNotExistError:
		# Hesap, enqueue ile job kosumu arasinda silinmis olabilir. Inbound
		# integration log YAZILAMAZ (zorunlu `carrier` Link'i hesapla birlikte
		# gitti) — iz Error Log'a duser; sessiz kaybolma yok, job patlatilmaz.
		safe_log_error(f"Webhook job'i icin Carrier Account bulunamadi: {account}", _LOG_TITLE)
		return None


def _resolve_adapter(
	account_doc: Document, body: bytes, secrets: frozenset[str] | None
) -> BaseCarrierAdapter | None:
	"""Hesabin tasiyicisina kayitli adapter'i dondurur; yoksa AC-11 yolu.

	`Logistics Provider` autoname'i `field:provider_code` oldugu icin hesabin
	`carrier` Link'i registry'nin bekledigi provider koduyla AYNIDIR.
	"""
	try:
		return get_adapter(
			account_doc.carrier,
			# parse_webhook kimlik bilgisi GEREKTIRMEZ: imza endpoint'te (W1)
			# dogrulandi ve disari HTTP cagrisi yok. `as_dict()` gecmek Password
			# yer tutucularini ('****') sir sanan olculmus arizanin kapisini
			# acar (integration/secrets.py); kimlik isteyen ilk gercek akis
			# (11-BE poll) kendi credential fabrikasini kuracak.
			credential_doc=None,
			environment=(account_doc.environment or "production").lower(),
		)
	except CarrierNotFoundError as exc:
		_handle_capability_unsupported(account_doc, secrets, exc, body)
		return None


def _parse_events(
	adapter: BaseCarrierAdapter,
	account_doc: Document,
	body: bytes,
	headers: Mapping[str, str] | None,
	secrets: frozenset[str] | None,
) -> list[TrackingEvent] | None:
	"""Adapter ayristirmasini kosar; hatayi PARSE_FAILED/CAPABILITY yoluna cevirir."""
	try:
		return adapter.parse_webhook(body, headers or {})
	except CarrierCapabilityError as exc:
		# Adapter kayitli ama WEBHOOK yetenegi yok ya da metot override
		# edilmemis — AC-11'in ikinci kolu, adapter-yok ile AYNI kod.
		_handle_capability_unsupported(account_doc, secrets, exc, body)
		return None
	except CarrierAPIError as exc:
		# Tasiyici bize gecersiz payload gonderdi (bozuk JSON/eksik alan).
		# Kimlik kanitliydi, endpoint 200 dondu (retry firtinasi onleme) —
		# iz failed inbound log'da; log katmani govdeyi maskeler/kirpar.
		_write_webhook_log(
			account_doc,
			secrets,
			succeeded=False,
			error_code="PARSE_FAILED",
			error_message=str(exc),
			request_body=body,
		)
		return None


def _handle_capability_unsupported(
	account_doc: Document, secrets: frozenset[str] | None, exc: Exception, request_body: Any
) -> None:
	"""AC-11: adapter yok / WEBHOOK yetenegi yok — failed log + Error Log.

	Istisna YUTULMAZ (iki ayri kalici iz) ama job da PATLATILMAZ: istek
	kimlik kanitli oldugu icin endpoint coktan 200 dondu; burada firlatmak
	RQ retry'inda ayni CAPABILITY hatasini sonsuza dek tekrarlatirdi.
	"""
	safe_log_error(frappe.get_traceback() or str(exc), _LOG_TITLE)
	_write_webhook_log(
		account_doc,
		secrets,
		succeeded=False,
		error_code="CAPABILITY_UNSUPPORTED",
		error_message=str(exc),
		request_body=request_body,
	)


def _process_single_event(
	account_doc: Document, event: TrackingEvent, secrets: frozenset[str] | None
) -> None:
	"""Tek TrackingEvent'i cozer, esler ve durum gecisini uygular."""
	shipment_name = _resolve_shipment(account_doc, event)
	if shipment_name is None:
		_write_webhook_log(
			account_doc,
			secrets,
			succeeded=False,
			error_code="SHIPMENT_NOT_FOUND",
			error_message=_("Takip numarasi bu hesap kapsaminda bir sevkiyata cozulemedi."),
			request_body=event.raw,
		)
		return

	carrier_code_raw: str = str(event.status or "").strip()
	internal_status: str | None = normalize_carrier_status(account_doc.carrier, carrier_code_raw)
	if internal_status is None:
		# AC-9: eslesmeyen kod durumu DEGISTIRMEZ; alim yine BASARILIDIR
		# (succeeded=1) — tasiyiciya hata donulmez, operator error_code'dan gorur.
		_write_webhook_log(
			account_doc,
			secrets,
			succeeded=True,
			error_code="STATUS_UNMAPPED",
			shipment=shipment_name,
			request_body=event.raw,
		)
		return

	try:
		_apply_transition(account_doc, shipment_name, internal_status, carrier_code_raw, event, secrets)
	except ShipmentStateError as exc:
		# Gec/sirasiz tasiyici event'i (orn. Delivered'dan SONRA gelen
		# In Transit) — tasiyici tarafinda normaldir; durum korunur,
		# iz failed inbound log'da. Exception kararli kodla siniflandi,
		# ayrica Error Log kirletilmez (beklenen operasyonel durum).
		_write_webhook_log(
			account_doc,
			secrets,
			succeeded=False,
			error_code="SHIPMENT_STATE_INVALID",
			error_message=str(exc),
			shipment=shipment_name,
			request_body=event.raw,
		)


def _resolve_shipment(account_doc: Document, event: TrackingEvent) -> str | None:
	"""tracking_number → Shipment cozumu + tenant guard (AC-10).

	`TrackingEvent` veri sinifinda tracking_number alani YOK; webhook
	semasinda numara event `raw` payload'inda tasinir (mock sozlesmesi:
	`{tracking_number, status_code, ...}` — adapter `raw`'a oldugu gibi koyar).
	"""
	tracking_number: str = str((event.raw or {}).get("tracking_number") or "").strip()
	if not tracking_number:
		return None

	# `frappe.get_all` GEREKCESI: sistem isi — job baglaminda oturum Guest
	# olabilir ve `get_list`'in permission katmani sonucu bosaltirdi. Tenant
	# izolasyonu asagida ACIKCA uygulanir (AC-10).
	rows = frappe.get_all(
		"Shipment",
		filters={"tracking_number": tracking_number},
		fields=["name", "seller_profile"],
	)

	# Tenant guard (AC-10): satici hesabi yalniz KENDI saticisinin sevkiyatini
	# guncelleyebilir — A'nin imzasiyla B'nin sevkiyati islenemez. PLATFORM
	# hesabinda guard ATLANIR: `Carrier Account.seller_profile` bos birakilirsa
	# hesap platform seviyesidir (Istoc sozlesmeli, tum tenant'lara hizmet
	# verir — alan aciklamasi carrier_account.json'da) ve tek bir tenant'a
	# baglanamaz.
	if account_doc.get("seller_profile"):
		rows = [row for row in rows if row.seller_profile == account_doc.seller_profile]

	if len(rows) != 1:
		# 0 → bulunamadi; >1 → belirsiz eslesme. Ikisi de AYNI yola duser:
		# cross-tenant deneme ile "gercekten yok" disaridan ayirt edilemez
		# olmali (anti-enumeration — 2026-09-04 denetim deseni) ve coklu
		# eslesme belirsizliginde guvenli taraf "isleme"dir.
		return None
	return rows[0].name


def _apply_transition(
	account_doc: Document,
	shipment_name: str,
	internal_status: str,
	carrier_code_raw: str,
	event: TrackingEvent,
	secrets: frozenset[str] | None,
) -> None:
	"""transition_status'u kosar, event'e ham kodu damgalar, basari logunu yazar.

	Ayni-durum idempotency katmani transition_status'un ICINDE (sessiz no-op,
	event uretmez); no-op da succeeded=1 loglanir — uc katmanli idempotency'nin
	orta katmani gorunur kalir. `doc.save()` mevcut fulfillment hook zincirini
	(on_shipment_status_change → update_order_fulfillment) otomatik tetikler.
	"""
	doc: Document = frappe.get_doc("Shipment", shipment_name)
	from_status: str = doc.status
	# ignore_permissions GEREKCESI: job Guest baglaminda kosabilir (enqueue
	# eden uc guest webhook) ve DocPerm katmani Guest'e Shipment yazdirmaz.
	# Yetki kaniti burada HMAC imzasi (endpoint, W1) + yukaridaki tenant
	# guard'dir (AC-10); bu bir kullanici girdisi akisi degil, dogrulanmis
	# tasiyici push'udur.
	doc.flags.ignore_permissions = True
	doc = transition_status(
		doc,
		internal_status,
		source="Webhook",
		note=f"{account_doc.carrier} (webhook)",
	)

	changed: bool = from_status != internal_status
	if changed:
		_stamp_carrier_status_code(shipment_name, internal_status, carrier_code_raw)

	_write_webhook_log(
		account_doc,
		secrets,
		succeeded=True,
		shipment=shipment_name,
		request_body=event.raw,
		response_body={"from_status": from_status, "to_status": doc.status, "no_op": not changed},
	)


def _stamp_carrier_status_code(shipment_name: str, internal_status: str, carrier_code_raw: str) -> None:
	"""Yeni yazilan Shipment Event'e ham tasiyici kodunu denormalize eder (AC-8).

	`transition_status` carrier_status_code parametresi ALMAZ ve event'i
	kendisi yazar; imzayi genisletmek `shipment_service.py`'nin isi ve BE-4
	sinirinin DISINDA (nota dusuldu). Bu yuzden gecis SONRASI ayni gecisin
	en yeni Webhook-kaynakli event'i bulunur ve alan doldurulur.

	`frappe.db.set_value` GEREKCESI (validate bypass): Shipment Event
	append-only bir audit kaydidir, controller is kurali yoktur ve alan salt
	denormalize ham koddur; `update_modified=False` audit zaman damgasini
	korur. `frappe.get_all` GEREKCESI: sistem isi (Guest oturumunda kosabilir),
	filtre shipment+source+status ile zaten dar.
	"""
	rows = frappe.get_all(
		"Shipment Event",
		filters={"shipment": shipment_name, "source": "Webhook", "internal_status": internal_status},
		fields=["name"],
		order_by="creation desc",
		limit=1,
	)
	if rows:
		frappe.db.set_value(
			"Shipment Event", rows[0].name, "carrier_status_code", carrier_code_raw, update_modified=False
		)


def _write_webhook_log(
	account_doc: Document,
	secrets: frozenset[str] | None,
	*,
	succeeded: bool,
	error_code: str | None = None,
	error_message: str | None = None,
	shipment: str | None = None,
	request_body: Any = None,
	response_body: Any = None,
) -> None:
	"""Webhook isleme yollari icin ortak inbound integration log kaydi.

	`secrets is None` ⇒ `secret_values` HIC gecilmez (secrets.py sozlesmesi:
	yarim kume yazicinin "unutuldu" nobetcisini susturur); aksi halde kume
	oldugu gibi gecilir — bos frozenset "sir yok, DOGRULANDI" demektir.
	`write_integration_log` asla firlatmaz — job'u dusuremez.
	"""
	kwargs: dict[str, Any] = {}
	if secrets is not None:
		kwargs["secret_values"] = secrets
	write_integration_log(
		carrier=account_doc.carrier,
		carrier_account=account_doc.name,
		shipment=shipment,
		operation="webhook",
		direction="inbound",
		succeeded=succeeded,
		error_code=error_code,
		error_message=error_message,
		request_body=request_body,
		response_body=response_body,
		**kwargs,
	)

# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Guest carrier webhook alicisi (09-BE webhook dilimi, BE-3).

Tasiyicilarin kargo durum push'u icin TEK guest POST ucu:

	POST /api/method/tradehub_core.api.v1.logistics_webhook.receive_carrier_webhook?account=<docname>
	X-Webhook-Signature: sha256=<hex(HMAC-SHA256(webhook_secret, raw_body))>

Yanit sozlesmesi (shared_contracts):
	200 {ok: true}  — kabul / duplicate (job'suz) / kimlikli-ama-islenemez
	401 {ok: false} — TUM ret yollari BAYT-BAYT AYNI govde (asagiya bkz.)
	413 {ok: false} — govde > MAX_WEBHOOK_BODY_BYTES (imza HESAPLANMADAN, AC-5)
	429             — IP rate limit (Frappe standart yaniti)

NEDEN `logistics_endpoint` ZARFI KULLANILMIYOR (BILINCLI KARAR):
	`logistics/api_utils.py`'deki zarf, hata sinifini ayirt edilebilir kod ve
	mesajla istemciye ACIKLAR — dogru davranis, ama YALNIZ kimligi dogrulanmis
	istemciler icin. Bu uc guest'tir ve URL'deki `account` docname'i tahmin
	edilebilir; ret nedenini ("hesap yok" / "hesap pasif" / "imza yanlis")
	ayristiran her yanit, saldirgana hesap enumeration'i ve imza oraklamasi
	icin birer soru cevaplar. Bu yuzden AC-2/AC-4 geregi TUM ret yollari
	`_reject()` uzerinden tek tip, jenerik ve bayt-bayt ayni 401 dondurur —
	`api/v1/auth.py` / `identity.py`'deki yerlesik "dict return +
	frappe.local.response['http_status_code']" deseni kullanilir.

W1 — IMZA DOGRULAMASI ENDPOINT'TE, SAF FALLBACK-HMAC ILE:
	Hesap -> adapter COZULEBILIYORSA `adapter.verify_webhook_signature`
	(ozel imza semali gercek tasiyicilar icin override noktasi) kullanilir;
	cozulemiyorsa `adapters/signature.verify_hmac_signature` saf fonksiyonuna
	(BaseCarrierAdapter default'unun cagirdigi AYNI fonksiyon) BE-1
	sabitleriyle dusulur. `parse_webhook` ve capability kontrolu YALNIZ job'da
	denenir (AC-11: adapter'siz carrier'in default-HMAC-gecerli istegi 200 alir).

W2 — CATCH-ALL TEKDUZELIK:
	Govde bastan sona try/except ile sarilidir. BEKLENMEDIK exception
	(get_password/Redis/enqueue vb.) `frappe.log_error`'a maskeli yazilir ve
	istemciye AYNI jenerik 401 doner — Frappe'nin default 500 zarfi `exc_type`
	sizdirir ve 401-tekduzeligini kirardi.

W3 — RATE LIMIT KEY PARAMETRESIZ (IP KOVASI):
	`frappe.rate_limiter.rate_limit(limit=600, seconds=60)` KEY VERILMEDEN
	kullanilir. v15 kaynagindan dogrulandi (frappe/rate_limiter.py::rate_limit):
	`key=None` + `ip_based=True` (default) -> `identity = frappe.local.request_ip`,
	yani kova ISTEK IP'SIDIR. `api/rate_limit.py`'deki session-bazli decorator
	bu GUEST ucta BILEREK kullanilmaz: tasiyicilar cookie'siz istemcidir, hepsi
	tek guest-session kovasina duser ve bir tasiyici digerini bogardi.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import frappe
from frappe.rate_limiter import rate_limit

from tradehub_core.logistics import is_enabled
from tradehub_core.logistics.adapters.registry import get_adapter
from tradehub_core.logistics.adapters.signature import verify_hmac_signature
from tradehub_core.logistics.constants import (
	CACHE_PREFIX,
	MAX_WEBHOOK_BODY_BYTES,
	WEBHOOK_DEDUPE_TTL_SECONDS,
	WEBHOOK_SIGNATURE_HEADER,
	WEBHOOK_SIGNATURE_PREFIX,
)
from tradehub_core.logistics.integration.log import safe_log_error, traceback_text, write_integration_log

if TYPE_CHECKING:
	from frappe.model.document import Document

	from tradehub_core.logistics.adapters.base import BaseCarrierAdapter

#: Asenkron isleme job'unun yolu (BE-4, `frappe.enqueue` hedefi). Modul yolu
#: repo yapisindan dogrulandi: python paketi `tradehub_core/tradehub_core/` ->
#: `tradehub_core.logistics...` (log.py ve servislerin import'lariyla ayni kok).
_WEBHOOK_JOB_METHOD: str = "tradehub_core.logistics.services.tracking_service.process_webhook_event"

#: Imzasiz/yanlis imzali inbound kaydin kararli hata kodu (AC-2).
_SIGNATURE_INVALID: str = "SIGNATURE_INVALID"


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=600, seconds=60)
def receive_carrier_webhook(account: str | None = None) -> dict[str, bool]:
	"""Tasiyici webhook push'unu kabul eder ve islemeyi job'a devreder.

	Sira: flag -> raw body -> boyut(413) -> hesap coz (is_active, get_password)
	-> imza (W1: adapter ya da saf fallback) -> dedupe -> maskeli inbound log
	-> enqueue(queue='short'). Ret yollarinin TAMAMI ayni jenerik 401'dir.

	Args:
		account: `Carrier Account` docname'i (URL query parametresi).

	Returns:
		{"ok": True} kabul/duplicate; {"ok": False} ret (401/413 status ile).
	"""
	# W2: beklenmedik HICBIR exception istemciye sizmaz — Frappe'nin 500 zarfi
	# exc_type/mesaj tasir ve 401-tekduzeligini kirardi. Traceback maskeli
	# (govde/sir icermez) olarak Error Log'a yazilir, istemci ayni 401'i gorur.
	try:
		return _receive(account)
	except Exception:  # noqa: BLE001 — W2 sozlesmesi: tek tip 401, sizinti yok (gerekce ustte)
		safe_log_error(traceback_text(), "logistics.webhook.unexpected")
		return _reject()


def _receive(account: str | None) -> dict[str, bool]:
	"""Webhook akisinin govdesi — tum ret dallari `_reject()`e cikar."""
	# Flag kapaliyken de yanit 401'dir (AC-4): "uc var ama kapali" bilgisi bile
	# enumeration yuzeyidir; 404/503 ayristirilabilir sinyal olurdu.
	if not is_enabled("carrier_webhook_enabled"):
		return _reject()
	if not account or not isinstance(account, str) or frappe.request is None:
		return _reject()

	# Raw body: frappe.app.make_form_dict de ayni API'yi kullaniyor
	# (request.get_data) — werkzeug govdeyi cache'ler, ikinci okuma guvenli.
	raw_body: bytes = frappe.request.get_data() or b""
	if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
		# AC-5: imza HESAPLANMADAN 413 — saldirgana bedava HMAC yaptirilmaz.
		frappe.local.response["http_status_code"] = 413
		return {"ok": False}

	resolved = _resolve_account(account)
	if resolved is None:
		return _reject()
	account_doc, secret = resolved

	if not _verify_signature(account_doc, raw_body, secret):
		_write_inbound_log(account_doc, raw_body, secret, succeeded=False, error_code=_SIGNATURE_INVALID)
		return _reject()

	if _is_duplicate(account_doc.name, raw_body):
		# AC-7: kimligi dogrulanmis duplicate 200 alir ama IKINCI job YOK —
		# 401 donseydi tasiyici retry firtinasi baslatirdi.
		return {"ok": True}

	_write_inbound_log(account_doc, raw_body, secret, succeeded=True, error_code=None)
	# environment kwarg'i BILEREK gecilmiyor: process_webhook_event imzasinda yok
	# ve gercek worker (execute_job) kwarg'lari imzaya gore FILTRELEMEZ — fazladan
	# kwarg her job'u TypeError ile oldururdu (BE-5 bulgusu). Job, environment'i
	# zaten hesabi yukleyip kendisinden okuyor (Sandbox/Production ayrimi orada).
	frappe.enqueue(
		_WEBHOOK_JOB_METHOD,
		queue="short",
		account=account_doc.name,
		raw_body=raw_body,
		headers=dict(frappe.request.headers),
	)
	# Dedupe isareti enqueue BASARILI olduktan SONRA atilir: once atilsaydi ve
	# enqueue patlasaydi (W2 -> 401) tasiyicinin retry'i "duplicate" sayilir,
	# event SESSIZCE kaybolurdu. Ters sirada kalan dar yaris penceresini
	# 2. ve 3. idempotency katmani (transition no-op + event_hash unique) kapatir.
	_mark_seen(account_doc.name, raw_body)
	return {"ok": True}


def _reject() -> dict[str, bool]:
	"""TUM ret yollarinin TEK cikisi — bayt-bayt ayni jenerik 401 (AC-2/AC-4).

	`frappe.throw` BILEREK kullanilmaz: exc sinifina gore degisen mesaj/zarf
	uretir ve ret nedenlerini ayristirilabilir kilardi. Yerlesik desen:
	dict return + `frappe.local.response["http_status_code"]` (auth.py/identity.py).
	"""
	frappe.local.response["http_status_code"] = 401
	return {"ok": False}


def _resolve_account(account: str) -> tuple[Document, str] | None:
	"""`Carrier Account`'u cozer; hesap yok / pasif / secret bos -> None.

	`frappe.get_doc` okumasi guest oturumda izin kontrolsuz calisir — BILINCLI:
	bu uc kimligini HMAC ile kanitlar, Frappe rol modeliyle degil; dokumandan
	istemciye HICBIR alan sizmaz (yanit her kosulda {ok} govdesidir). Guest'e
	`Carrier Account` okuma rolu ACILMAZ.
	"""
	if not frappe.db.exists("Carrier Account", account):
		return None

	account_doc = frappe.get_doc("Carrier Account", account)
	if not account_doc.is_active:
		return None

	# get_password GEREKCESI: `webhook_secret` bir Password alanidir; HMAC
	# hesabi icin plaintext ZORUNLU. `raise_exception=False` — cozulemeyen/bos
	# secret exception degil, jenerik 401'e giden sessiz bir ret nedenidir.
	secret = account_doc.get_password("webhook_secret", raise_exception=False)
	if not secret:
		return None
	return account_doc, secret


def _verify_signature(account_doc: Document, raw_body: bytes, secret: str) -> bool:
	"""W1: adapter cozulebiliyorsa onun imza dogrulamasi, degilse saf fallback."""
	adapter = _try_resolve_adapter(account_doc)
	if adapter is not None:
		# Ozel imza semali tasiyici override'i (header adi/prefix'i/algoritmasi
		# farkli olabilir). Default implementasyon zaten ayni saf fonksiyona iner.
		return bool(adapter.verify_webhook_signature(raw_body, frappe.request.headers, secret))

	# Fallback: BE-1 sabitleriyle saf HMAC — adapter'siz carrier'in gecerli
	# imzali istegi de 200 alir (AC-11); isleyememe karari job'a aittir.
	signature_header: str | None = frappe.request.headers.get(WEBHOOK_SIGNATURE_HEADER)
	return verify_hmac_signature(raw_body, signature_header, secret, prefix=WEBHOOK_SIGNATURE_PREFIX)


def _try_resolve_adapter(account_doc: Document) -> BaseCarrierAdapter | None:
	"""Hesap -> `Logistics Provider.provider_code` -> registry adapter'i.

	W1 kurali: cozulememe bir HATA DEGIL, saf fallback'e gecis sinyalidir —
	bu dilimde gercek adapter kayitli olmadigi icin normal yol budur. Bu yuzden
	`CarrierNotFoundError` dahil HER istisna None'a katlanir; imza dogrulamasi
	fallback ile yine yapilir, 401-tekduzeligi bozulmaz. (Gercek bir adapter
	verify icinde patlarsa o istisna BURADAN degil `verify_webhook_signature`
	cagrisindan cikar ve W2 catch-all'una duser.)
	"""
	try:
		provider_code = frappe.db.get_value("Logistics Provider", account_doc.carrier, "provider_code")
		if not provider_code:
			return None
		return get_adapter(
			provider_code, credential_doc=None, environment=account_doc.environment or "Production"
		)
	except Exception:  # noqa: BLE001 — W1: cozulemeyen adapter = fallback sinyali (gerekce ustte)
		return None


def _write_inbound_log(
	account_doc: Document,
	raw_body: bytes,
	secret: str,
	*,
	succeeded: bool,
	error_code: str | None,
) -> None:
	"""Maskeli inbound entegrasyon logu (AC-1/AC-2). Asla firlatmaz (log.py sozlesmesi)."""
	write_integration_log(
		carrier=account_doc.carrier,  # `Logistics Provider` DOCNAME'i (log.py sozlesmesi)
		carrier_account=account_doc.name,
		operation="webhook",
		direction="inbound",
		succeeded=succeeded,
		http_status=200 if succeeded else 401,
		error_code=error_code,
		request_body=raw_body,
		request_headers=dict(frappe.request.headers),
		# Deger-tabanli redaksiyonun girdisi: govdeye/basliga sizmis secret
		# birebir maskelensin (imza hex'i secret DEGIL, maskelenmesi gerekmez).
		secret_values=[secret],
	)


def _dedupe_key(account: str, raw_body: bytes) -> str:
	"""Redis dedupe anahtari: tc:logistics:webhook:seen:{account}:{sha256}."""
	digest: str = hashlib.sha256(raw_body).hexdigest()
	return f"{CACHE_PREFIX}webhook:seen:{account}:{digest}"


def _is_duplicate(account: str, raw_body: bytes) -> bool:
	"""Ayni ham govde TTL penceresinde daha once gorulmus mu? (AC-7, 1. katman)

	Redis erisilemezse `get_value` None doner — dedupe FAIL-OPEN calisir
	(kacan duplicate'i transition no-op + event_hash unique katmanlari yutar);
	fail-closed olsaydi Redis kesintisi tum webhook alimini durdururdu.
	"""
	return bool(frappe.cache.get_value(_dedupe_key(account, raw_body), expires=True))


def _mark_seen(account: str, raw_body: bytes) -> None:
	"""Govdeyi TTL'li olarak gorulmus isaretle (48 saat — W4)."""
	frappe.cache.set_value(_dedupe_key(account, raw_body), 1, expires_in_sec=WEBHOOK_DEDUPE_TTL_SECONDS)

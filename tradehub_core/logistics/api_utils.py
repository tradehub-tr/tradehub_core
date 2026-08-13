# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik API sözleşme katmanı — yanıt zarfı, hata modeli, kapılar.

Her lojistik endpoint'i `@logistics_endpoint(...)` ile sarılır. Dekoratör üç
işi tek yerde yapar:

	1. **Feature flag kapısı** — bayrak kapalıysa iş mantığı hiç çalışmaz
	2. **Capability kapısı** — ince taneli yetki kontrolü
	3. **Yanıt zarfı** — başarı ve hata için TEK ve sabit şekil

Zarf:

	başarı → {"ok": true,  "data": <...>}
	hata   → {"ok": false, "error": {"code": "...", "message": "...", "details": {...}}}

`error.code` istemcinin dallanacağı kararlı anahtardır (bkz. `exceptions.py`);
`error.message` kullanıcıya gösterilmek üzere i18n'lidir ve dallanma için
KULLANILMAZ.

NEDEN AYRI BİR ZARF:
	Repo'da üç rakip konvansiyon var (`{"success": ...}` 120 yer, `{"ok": ...}`
	49 yer, `{"data": ...}` 23 yer) ve hiçbiri hata kodu taşımıyor. Frontend'in
	hata türüne göre dallanabilmesi (ör. FEATURE_DISABLED ile PERMISSION_DENIED
	farklı ekran gösterir) için kararlı bir kod alanı şart. Mevcut endpoint'ler
	DEĞİŞTİRİLMİYOR — bu zarf yalnız lojistik yüzeyi için geçerli.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

import frappe
from frappe import _

from tradehub_core.logistics.exceptions import (
	CapabilityRequiredError,
	FeatureDisabledError,
	LogisticsError,
)

# ---------------------------------------------------------------------------
# Lojistik dışı exception'lar için kod eşlemesi
# ---------------------------------------------------------------------------
# LogisticsError alt sınıfları kendi `code` ve `http_status_code`'unu taşır.
# Aşağıdakiler Frappe'nin kendi hata sınıfları — sözleşmeye onları da bağlıyoruz
# ki istemci tek bir hata şekliyle çalışsın.
_FRAPPE_ERROR_MAP: tuple[tuple[type[Exception], str, int], ...] = (
	(frappe.PermissionError, "PERMISSION_DENIED", 403),
	(frappe.DoesNotExistError, "NOT_FOUND", 404),
	(frappe.DuplicateEntryError, "DUPLICATE_ENTRY", 409),
	# ValidationError EN SONDA: LogisticsError ondan türüyor, önce gelirse
	# lojistik kodlarını gölgeler.
	(frappe.ValidationError, "VALIDATION_ERROR", 417),
)

_INTERNAL_ERROR_CODE = "INTERNAL_ERROR"


def ok(data: Any = None) -> dict:
	"""Başarı zarfı."""
	return {"ok": True, "data": data}


def error(code: str, message: str, details: dict | None = None) -> dict:
	"""Hata zarfı."""
	payload: dict[str, Any] = {"code": code, "message": message}
	if details:
		payload["details"] = details
	return {"ok": False, "error": payload}


def _resolve_frappe_error(exc: Exception) -> tuple[str, int] | None:
	"""Frappe hata sınıfını (kod, http) ikilisine çevirir; eşleşme yoksa None."""
	for exc_type, code, status in _FRAPPE_ERROR_MAP:
		if isinstance(exc, exc_type):
			return code, status
	return None


def _fail(code: str, message: str, status: int, details: dict | None = None) -> dict:
	"""Hata yanıtını üretir ve HTTP durumunu ayarlar.

	`frappe.db.rollback()` ZORUNLU: exception'ı yutup normal dönüş yaptığımız
	için Frappe'nin otomatik rollback'i devreye girmez ve yarım kalmış bir yazma
	commit edilirdi.
	"""
	frappe.db.rollback()
	frappe.local.response["http_status_code"] = status
	return error(code, message, details)


def logistics_endpoint(
	*,
	flag: str | None = None,
	capability: str | None = None,
	roles: list[str] | None = None,
) -> Callable:
	"""Lojistik endpoint'lerini sözleşme zarfına bağlar.

	Args:
		flag: Zorunlu feature flag adı. Kapalıysa FEATURE_DISABLED (403).
		capability: Zorunlu capability anahtarı. Yoksa CAPABILITY_REQUIRED (403).
		roles: Verilirse `frappe.only_for` ile rol kapısı uygulanır.

	Sıra önemli: **flag → rol → capability → iş mantığı**. Kapalı bir özelliğin
	yetki hatası döndürmesi yanıltıcı olurdu; önce "bu özellik açık mı" sorulur.

	Kullanım:
		@frappe.whitelist()
		@logistics_endpoint(flag="logistics_enabled", capability="view.tracking")
		def list_carrier_services(page: int = 1) -> dict:
			return ok({"items": [...]})

	Not: `@frappe.whitelist()` EN ÜSTTE olmalı — Frappe sarmalanmış fonksiyonu
	değil, dış fonksiyonu kaydetmeli.
	"""

	def decorator(fn: Callable) -> Callable:
		@functools.wraps(fn)
		def wrapper(*args, **kwargs) -> dict:
			try:
				if flag:
					_assert_feature_enabled(flag)
				if roles:
					frappe.only_for(roles)
				if capability:
					_assert_capability(capability)

				result = fn(*args, **kwargs)
				# İş fonksiyonu zaten zarflamışsa iki kez sarma
				if isinstance(result, dict) and "ok" in result:
					return result
				return ok(result)

			except LogisticsError as exc:
				return _fail(
					code=getattr(exc, "code", "LOGISTICS_ERROR"),
					message=_extract_message(exc),
					status=getattr(exc, "http_status_code", 417),
				)

			except Exception as exc:  # noqa: BLE001 — sözleşme sınırı: her hata zarfa girer
				mapped = _resolve_frappe_error(exc)
				if mapped:
					code, status = mapped
					return _fail(code=code, message=_extract_message(exc), status=status)

				# Beklenmeyen hata: ayrıntıyı istemciye SIZDIRMA, log'a yaz
				frappe.log_error(
					frappe.get_traceback(), f"logistics_endpoint.{fn.__name__}"
				)
				return _fail(
					code=_INTERNAL_ERROR_CODE,
					message=_("Beklenmeyen bir hata oluştu. Kayıt altına alındı."),
					status=500,
				)

		return wrapper

	return decorator


def _assert_feature_enabled(flag: str) -> None:
	"""Ana bayrak ve istenen bayrak açık değilse FeatureDisabledError fırlatır."""
	from tradehub_core.logistics import is_enabled

	if not is_enabled(flag):
		raise FeatureDisabledError(
			_("Bu lojistik özelliği henüz aktif değil: {0}").format(flag)
		)


def _assert_capability(capability: str) -> None:
	"""Capability yoksa CapabilityRequiredError fırlatır."""
	from tradehub_core.utils.permission_resolver import has_capability

	if not has_capability(frappe.session.user, capability):
		raise CapabilityRequiredError(
			_("Bu işlem için gerekli yetkiniz yok: {0}").format(capability)
		)


def _extract_message(exc: Exception) -> str:
	"""Exception'dan kullanıcıya gösterilebilir mesajı çıkarır.

	`frappe.throw` mesajı bazen exception'ın kendisinde değil
	`frappe.message_log`'da durur; ikisini de kontrol ediyoruz.
	"""
	text = str(exc).strip()
	if text:
		return text

	for entry in reversed(frappe.message_log or []):
		message = entry.get("message") if isinstance(entry, dict) else entry
		if message:
			return str(message)

	return _("İşlem tamamlanamadı.")

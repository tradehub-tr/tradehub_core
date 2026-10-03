"""API hata zarfı: makine kodu + kullanıcıya uygun metin; sır/trace yok.

Beklenen hatalar (404/409/422/429/503) exception yerine durum kodlu `message` gövdesiyle döner;
önce transaction geri alınır ki yarım yazma kalmasın.
"""

from __future__ import annotations

import frappe
from frappe import _


class ApiError(Exception):
	def __init__(self, status: int, payload: dict):
		super().__init__(payload.get("error_code"))
		self.status = status
		self.payload = payload


def not_found(what: str = "") -> ApiError:
	return ApiError(
		404, {"error_code": "NOT_FOUND", "message": _("Kayıt bulunamadı.") + (f" ({what})" if what else "")}
	)


def validation(field_errors: dict | None = None, blocking=None, warnings=None, message=None) -> ApiError:
	payload = {
		"error_code": "VALIDATION_FAILED",
		"message": message or _("Gönderilen bilgiler geçersiz."),
		"blocking": blocking or [],
		"warnings": warnings or [],
	}
	if field_errors:
		payload["field_errors"] = field_errors
	return ApiError(422, payload)


def conflict(revision: int, theirs=None, saved_by=None, saved_at=None) -> ApiError:
	return ApiError(
		409,
		{
			"error_code": "REVISION_CONFLICT",
			"message": _("Kayıt başka bir oturumda değişti."),
			"revision": revision,
			"theirs": theirs,
			"saved_by": saved_by,
			"saved_at": str(saved_at) if saved_at else None,
		},
	)


def provider_unavailable(channel: str) -> ApiError:
	return ApiError(
		503,
		{
			"error_code": "PROVIDER_UNAVAILABLE",
			"message": _("Bu kanal için gönderim sağlayıcısı yapılandırılmamış."),
			"channel": channel,
		},
	)


def rate_limited() -> ApiError:
	return ApiError(
		429, {"error_code": "RATE_LIMITED", "message": _("Çok sık deneme. Biraz sonra tekrar deneyin.")}
	)


def respond(err: ApiError) -> dict:
	frappe.db.rollback()
	frappe.local.response.http_status_code = err.status
	return err.payload


def guarded(fn):
	"""Whitelist ucunu ApiError → durum kodlu yanıt çevirisiyle sarar."""
	import functools

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		try:
			return fn(*args, **kwargs)
		except ApiError as e:
			return respond(e)

	return wrapper

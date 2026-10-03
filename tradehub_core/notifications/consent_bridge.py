"""Ticari ileti izni köprüsü.

İzin KARARININ tek kayıt kaynağı mevcut `User Consent Log` (marketing_email / marketing_sms).
Dış aktarım (İYS) ayrı bir kayıttır: `Commercial Consent Sync`. Bu kurulumda İYS entegrasyonu
YOK (B0 envanteri); aktarım satırı açık hata koduyla (`PROVIDER_UNAVAILABLE`) "basarisiz" kalır,
başarı taklit edilmez. Geri çekme dış servisten bağımsız olarak yerelde hemen etkilidir.

Sıra: yeni bir karar kaydedildiğinde aynı kullanıcı/kanalın bekleyen ya da başarısız eski aktarım
satırları "gecersiz" olur; eski bir işin daha yeni bir geri çekmeyi ezmesi böylece engellenir.
"""

from __future__ import annotations

import hashlib

import frappe
from frappe.utils import now_datetime

SYNC = "Commercial Consent Sync"
TYPES = {"email": "marketing_email", "sms": "marketing_sms"}
CHANNEL_OF = {v: k for k, v in TYPES.items()}
SOURCES = ("registration", "settings", "banner", "modal", "admin_override")


def provider_available() -> bool:
	"""İYS sağlayıcısı yapılandırılmış mı. Kodda entegrasyon olmadığı için daima False."""
	return False


def _mask_email(email: str) -> str:
	if not email or "@" not in email:
		return ""
	local, domain = email.split("@", 1)
	return f"{local[:2]}•••@{domain}"


def _mask_phone(phone: str) -> str:
	digits = "".join(c for c in phone or "" if c.isdigit())
	if len(digits) < 4:
		return ""
	return f"+•• ••• ••• {digits[-4:-2]} {digits[-2:]}"


def target(user: str, channel: str) -> dict:
	"""Kayıtlı hedef ve doğrulama durumu. Doğrulama kaydı olmayan hedef 'doğrulanmadı' sayılır."""
	if channel == "email":
		email = frappe.db.get_value("User", user, "email") or ""
		verified = bool(frappe.db.get_value("User Profile", {"user": user}, "email_verified"))
		return {"raw": email, "masked": _mask_email(email) or None, "verified": bool(email) and verified}
	phone = frappe.db.get_value("User Profile", {"user": user}, "phone") or frappe.db.get_value(
		"User", user, "mobile_no"
	)
	# Telefon doğrulama alanı veri modelinde yok (B0): SMS hedefi doğrulanmış sayılmaz.
	return {"raw": phone or "", "masked": _mask_phone(phone or "") or None, "verified": False}


def assert_grantable(user: str, channel: str) -> None:
	"""Ticari izin verilecekse hedef var ve doğrulanmış olmalı (tüm izin yolları için tek kapı)."""
	from frappe import _

	from tradehub_core.notifications import errors

	tgt = target(user, channel)
	if not tgt["raw"]:
		raise errors.validation(
			field_errors={"channel": "İletişim bilgisi eksik."}, message=_("Önce iletişim bilgisini ekleyin.")
		)
	if not tgt["verified"]:
		raise errors.validation(
			field_errors={"channel": "İletişim bilgisi doğrulanmamış."},
			message=_("Önce iletişim bilgisini doğrulayın."),
		)


def _latest_logs(user: str, limit: int = 50) -> list[dict]:
	return frappe.get_all(
		"User Consent Log",
		filters={"user": user, "consent_type": ["in", list(TYPES.values())]},
		fields=["name", "consent_type", "action", "source", "creation"],
		order_by="creation desc",
		limit=limit,
	)


def _syncs_by_log(log_names: list[str]) -> dict:
	if not log_names:
		return {}
	rows = frappe.get_all(
		SYNC,
		filters={"consent_log": ["in", log_names]},
		fields=["consent_log", "status", "error_code", "modified"],
		order_by="modified desc",
	)
	out = {}
	for r in rows:
		out.setdefault(r.consent_log, r)
	return out


def _entry(user: str, channel: str, last: dict | None, sync: dict | None) -> dict:
	tgt = target(user, channel)
	granted = bool(last and last.action in ("granted", "renewed"))
	if granted and not tgt["raw"]:
		state = "hedef-eksik"
	elif granted and not tgt["verified"]:
		state = "hedef-dogrulanmadi"
	elif granted:
		state = {"islendi": "onayli", "bekliyor": "bekliyor"}.get(
			(sync or {}).get("status") or "", "basarisiz"
		)
	elif last:
		state = "geri-cekildi"
	elif not tgt["raw"]:
		state = "hedef-eksik"
	elif not tgt["verified"]:
		# İzin verilemez durumda: arayüz "İzin yok" deyip 422'ye düşen bir düğme göstermesin.
		state = "hedef-dogrulanmadi"
	else:
		state = "yok"
	return {
		"state": state,
		"granted": granted,
		"target": tgt["masked"],
		"target_verified": tgt["verified"],
		"updated_at": str(last.creation) if last else None,
		"source": last.source if last and last.source in SOURCES else None,
		"sync_available": provider_available(),
		"error_code": (sync or {}).get("error_code") or None,
	}


def status(user: str) -> dict:
	logs = _latest_logs(user)
	syncs = _syncs_by_log([r.name for r in logs])
	consent = {}
	for channel, ctype in TYPES.items():
		last = next((r for r in logs if r.consent_type == ctype), None)
		consent[channel] = _entry(user, channel, last, syncs.get(last.name) if last else None)
	history = []
	for r in logs[:20]:
		sync = syncs.get(r.name) or {}
		history.append(
			{
				"at": str(r.creation),
				"channel": CHANNEL_OF[r.consent_type],
				"action": "revoke" if r.action == "withdrawn" else "grant",
				"source": r.source if r.source in SOURCES else "settings",
				"sync_state": {"islendi": "islendi", "bekliyor": "bekliyor"}.get(
					sync.get("status"), "basarisiz"
				),
			}
		)
	return {"consent": consent, "consent_history": history}


def after_decision(log_name: str) -> None:
	"""Yeni izin kararı sonrası aktarım satırı; eski bekleyenleri geçersiz kılar.

	`privacy.consent.record_consent` her marketing kararında çağırır; böylece eski compliance
	uçları da aynı köprüden geçer (tek kayıt kaynağı).
	"""
	log = frappe.db.get_value("User Consent Log", log_name, ["user", "consent_type", "action"], as_dict=True)
	if not log or log.consent_type not in CHANNEL_OF:
		return
	from tradehub_core.notifications.store import _Write

	with _Write():
		_record_sync(log_name, log)


def _record_sync(log_name: str, log) -> None:
	channel = CHANNEL_OF[log.consent_type]
	S = frappe.qb.DocType(SYNC)
	(
		frappe.qb.update(S)
		.set(S.status, "gecersiz")
		.where(S.user == log.user)
		.where(S.channel == channel)
		.where(S.status.isin(["bekliyor", "basarisiz"]))
	).run()
	tgt = target(log.user, channel)
	available = provider_available()
	frappe.get_doc(
		{
			"doctype": SYNC,
			"consent_log": log_name,
			"user": log.user,
			"channel": channel,
			"action": "revoke" if log.action == "withdrawn" else "grant",
			"target_ref": tgt["masked"],
			"target_hash": hashlib.sha256(tgt["raw"].encode()).hexdigest() if tgt["raw"] else "",
			"status": "bekliyor" if available else "basarisiz",
			"error_code": None if available else "PROVIDER_UNAVAILABLE",
			"attempts": 0,
			"next_retry_at": now_datetime() if available else None,
		}
	).insert(ignore_permissions=True)  # sistem kaydı; karar kullanıcının kendi oturumunda alındı

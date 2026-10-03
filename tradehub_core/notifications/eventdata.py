"""Tetikleyici noktalarında olay verisi kurma yardımcıları.

Değerler gerçek kayıttan gelir; eksik değer örnekle doldurulmaz (gönderim kaydı
`MISSING_EVENT_DATA` ile atlanır ya da zorunlu kanalda güvenilir eski yola düşer).

Bu modül domain akışlarının (sipariş, KYB, abonelik…) modül düzeyinde içe aktarılır; bu yüzden
ağır bağımlılıkları fonksiyon içinde yükler ve bir değer kurulamazsa domain işlemini düşürmek
yerine o alanı boş bırakır.
"""

from __future__ import annotations

import frappe


def absolute(path: str) -> str:
	if not path:
		return ""
	if path.startswith("https://"):
		return path
	if not path.startswith("/"):
		return ""
	try:
		from tradehub_core.notifications.dispatch import base_url

		return f"{base_url()}{path}"
	except Exception:  # noqa: BLE001 — adres kurulamazsa bağlantı boş kalır, gönderim kaydı eksik veriyi işaretler
		return ""


def _now_text() -> str:
	try:
		from frappe.utils import now_datetime

		from tradehub_core.notifications.dispatch import fmt_dt

		return fmt_dt(now_datetime())
	except Exception:  # noqa: BLE001 — tarih metni kurulamazsa boş kalır
		return ""


def _full_name(user: str) -> str:
	try:
		return frappe.db.get_value("User", user, "full_name") or ""
	except Exception:  # noqa: BLE001 — ad bulunamazsa selamlama koşullu bloğu düşer
		return ""


def generic_event_data(user: str, reference_no: str, path: str = "") -> dict:
	return {
		"recipient_name": _full_name(user),
		"reference_no": reference_no or "",
		"event_date": _now_text(),
		"action_url": absolute(path),
	}


def safe(builder, *args, **kwargs) -> dict:
	"""Olay verisi kurucusunu çağırır; hata domain bildirimini düşürmez, olay yolu atlanır."""
	try:
		return builder(*args, **kwargs)
	except Exception:  # noqa: BLE001 — log'a yazılır; legacy bildirim yine gider
		try:
			frappe.log_error(title="notification event data")
		except Exception:  # noqa: BLE001
			pass
		return {}

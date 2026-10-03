"""Platform e-postalarının gönderen kimliği.

Gönderen adı varsayılan olarak "iStoc"tur. Frappe, giden posta site ayarından (site_config) geliyorsa
ve `email_sender_name` tanımlı değilse adı "Frappe" yazar; bu yüzden ad burada açıkça verilir. Adres
her zaman sitenin varsayılan giden posta hesabından alınır (SMTP'nin kabul ettiği adres değişmez).
Ad, site_config'te `istoc_email_sender_name` ile değiştirilebilir.
"""

from __future__ import annotations

import email.utils

import frappe

DEFAULT_SENDER_NAME = "iStoc"


def brand_sender() -> str | None:
	"""`"iStoc" <varsayılan giden adres>`; giden hesap yoksa None (Frappe kendi varsayılanını kullanır)."""
	try:
		from frappe.email.doctype.email_account.email_account import EmailAccount

		account = EmailAccount.find_default_outgoing()
		address = account.get("email_id") if account else None
	except Exception:  # noqa: BLE001 — gönderen adı kurulamazsa e-posta yine Frappe varsayılanıyla gider
		return None
	if not address:
		return None
	name = frappe.conf.get("istoc_email_sender_name") or DEFAULT_SENDER_NAME
	return email.utils.formataddr((name, address))

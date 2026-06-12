"""Mailgun (outgoing) Email Account kurulumu — secret'ı process argümanından alma.

Güvenlik (C1): SMTP parolası daha önce docker-compose'da `bench execute ... --kwargs
"{...password...}"` ile **process argümanı** olarak geçiriliyordu; `ps`, `docker inspect`
ve shell history üzerinden okunabiliyordu. Bu fonksiyon parolayı yalnızca container'ın
`os.environ`'ından okur — komut satırında hiçbir secret görünmez.

Çağrı (docker-compose create-site):
    bench --site $SITE_NAME execute tradehub_core.setup.email_account.setup_mailgun_from_env
"""
from __future__ import annotations

import os

import frappe


def setup_mailgun_from_env() -> None:
    """MAIL_* ortam değişkenlerinden default outgoing Email Account oluşturur/günceller.

    Idempotent: aynı email_account_name varsa yeniden oluşturmaz, alanları günceller.
    Gerekli env değişkeni eksikse sessizce çıkar (site kurulumu bozulmaz).
    """
    sender = os.environ.get("MAIL_DEFAULT_SENDER")
    server = os.environ.get("MAIL_SERVER")
    login = os.environ.get("MAIL_LOGIN")
    password = os.environ.get("MAIL_PASSWORD")

    if not (sender and server and login and password):
        # Mail yapılandırılmadıysa kurulumu atla — hata fırlatma.
        return

    port = int(os.environ.get("MAIL_PORT", "587") or "587")
    use_tls = (os.environ.get("MAIL_USE_TLS", "1") or "1") not in ("0", "false", "False")
    account_name = "Mailgun"

    fields = {
        "email_id": sender,
        "enable_outgoing": 1,
        "default_outgoing": 1,
        "smtp_server": server,
        "smtp_port": port,
        "use_tls": 1 if use_tls else 0,
        "no_smtp_authentication": 0,
        "login_id": login,
        "password": password,
        "always_use_account_email_id_as_sender": 1,
    }

    existing = frappe.db.exists("Email Account", {"email_account_name": account_name})
    if existing:
        doc = frappe.get_doc("Email Account", existing)
        for key, value in fields.items():
            doc.set(key, value)
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc({"doctype": "Email Account", "email_account_name": account_name, **fields})
        doc.insert(ignore_permissions=True)

    frappe.db.commit()

"""
Headless CRM & Helpdesk icin guest wrapper'lari.

CRM Lead ve HD Ticket doctype'larini Guest'e DOGRUDAN acmiyoruz (field whitelist
ve veri sizintisi riski). Bunun yerine minimum validasyonlu, ignore_permissions
uzerinden olusturan wrapper'lar kullaniyoruz.

Cagirma pattern'i:
    POST /api/method/tradehub_core.api.public.create_lead
    POST /api/method/tradehub_core.api.public.create_ticket
"""

import re

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from tradehub_core.utils.helpdesk_routing import (
    ensure_platform_support_team,
    resolve_team_for_order,
)

EMAIL_RE = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")


def _validate_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not email or not EMAIL_RE.match(email):
        frappe.throw(_("Gecerli bir e-posta adresi girin."), frappe.ValidationError)
    return email


def _clip(value: str | None, max_len: int = 500) -> str:
    if not value:
        return ""
    return str(value).strip()[:max_len]


def _resolve_user_email(user: str) -> str:
    """User name'i email'e çözümle (Administrator gibi özel name'ler için)."""
    if not user:
        return ""
    if "@" in user:
        return user
    return frappe.db.get_value("User", user, "email") or user


@frappe.whitelist(allow_guest=True)
@rate_limit(key="email", limit=5, seconds=300)
def create_lead(
    email: str,
    first_name: str = "",
    last_name: str = "",
    mobile_no: str = "",
    organization: str = "",
    message: str = "",
    source: str = "Website",
):
    """Storefront iletisim formu → CRM Lead.

    Rate-limit: email basina 5 dakikada 5 kez.
    """
    email = _validate_email(email)
    first_name = _clip(first_name, 140) or email.split("@")[0]
    last_name = _clip(last_name, 140)
    mobile_no = _clip(mobile_no, 40)
    organization = _clip(organization, 200)
    message = _clip(message, 4000)
    source = _clip(source, 140) or "Website"

    lead = frappe.new_doc("CRM Lead")
    lead.first_name = first_name
    if last_name:
        lead.last_name = last_name
    lead.email = email
    if mobile_no:
        lead.mobile_no = mobile_no
    if organization:
        lead.organization = organization
    lead.source = source
    if message:
        lead.lead_note = message
    lead.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"name": lead.name, "ok": True}


@frappe.whitelist()
def list_my_tickets(status: str = "all", page: int = 1, page_size: int = 20):
    """Müşteri perspektifinde kendi ticket'larını liste + count döndürür.

    Frappe'nin get_count'u permission_query_conditions ile kombine olunca
    bazı durumlarda 0 dönebiliyor; burada filter'ı manuel uygulayıp
    ignore_permissions=True ile tutarlı count + list veriyoruz.
    """
    caller = frappe.session.user
    if not caller or caller == "Guest":
        frappe.throw(_("Giriş yapmalısınız."), frappe.PermissionError)

    try:
        page = int(page) or 1
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(page_size) or 20
    except (TypeError, ValueError):
        page_size = 20
    page_size = min(max(page_size, 1), 100)

    # Login user'in olasi tum email/name kimliklerine karsi raised_by eslesimi
    user_email = _resolve_user_email(caller)
    raised_by_options = list({caller, user_email})  # dedup

    base_filters = {"raised_by": ["in", raised_by_options]}
    if status and status != "all":
        base_filters["status"] = status

    fields = [
        "name", "subject", "status", "priority", "ticket_type",
        "raised_by", "creation", "modified",
    ]
    data = frappe.get_all(
        "HD Ticket",
        filters=base_filters,
        fields=fields,
        order_by="modified desc",
        start=(page - 1) * page_size,
        page_length=page_size,
        ignore_permissions=True,
    )
    total = frappe.db.count("HD Ticket", filters=base_filters)
    return {"data": data, "total": total}


@frappe.whitelist()
def my_ticket_status_counts():
    """Tab sayıları için tek seferde tüm status'lerin count'unu döndürür."""
    caller = frappe.session.user
    if not caller or caller == "Guest":
        frappe.throw(_("Giriş yapmalısınız."), frappe.PermissionError)

    user_email = _resolve_user_email(caller)
    raised_by_options = list({caller, user_email})
    rows = frappe.get_all(
        "HD Ticket",
        filters={"raised_by": ["in", raised_by_options]},
        fields=["status"],
        ignore_permissions=True,
        limit_page_length=10000,
    )
    counts = {"all": 0, "Open": 0, "Replied": 0, "Resolved": 0, "Closed": 0}
    for r in rows:
        counts["all"] += 1
        if r.get("status") in counts:
            counts[r["status"]] += 1
    return counts


@frappe.whitelist()
def get_ticket_communications(ticket: str):
    """HD Ticket'a bağlı Communication'ları döndürür.

    Müşteri Communication doctype'ında read yetkisine sahip değil; ama
    kendi HD Ticket'ına permission query üzerinden erişebiliyor. Ticket
    görünüyorsa, bağlı communications'ı ignore_permissions ile çekeriz.
    """
    if not ticket:
        frappe.throw(_("Talep kimliği gerekli."), frappe.ValidationError)
    if not frappe.has_permission("HD Ticket", doc=ticket, ptype="read"):
        frappe.throw(_("Bu talebe erişim yetkiniz yok."), frappe.PermissionError)

    return frappe.get_all(
        "Communication",
        filters={
            "reference_doctype": "HD Ticket",
            "reference_name": ticket,
        },
        fields=[
            "name", "subject", "content", "sender", "sender_full_name",
            "recipients", "communication_date", "sent_or_received",
            "communication_medium",
        ],
        order_by="communication_date asc",
        limit_page_length=200,
        ignore_permissions=True,
    )


@frappe.whitelist()
def reply_ticket(ticket: str, content: str):
    """Müşteri HD Ticket'a yanıt ekler. Ticket'a erişim varsa Communication
    oluşturulur (sent_or_received='Received' — sisteme gelen)."""
    if not ticket or not (content or "").strip():
        frappe.throw(_("Talep ve içerik zorunlu."), frappe.ValidationError)
    if not frappe.has_permission("HD Ticket", doc=ticket, ptype="read"):
        frappe.throw(_("Bu talebe erişim yetkiniz yok."), frappe.PermissionError)

    caller = frappe.session.user
    comm = frappe.get_doc({
        "doctype": "Communication",
        "communication_type": "Communication",
        "communication_medium": "Email",
        "sent_or_received": "Received",
        "content": content,
        "reference_doctype": "HD Ticket",
        "reference_name": ticket,
        "sender": caller,
        "status": "Linked",
        "subject": f"Re: {ticket}",
    })
    comm.insert(ignore_permissions=True)
    # HD Ticket status'u müşteri yanıtında tekrar "Open"a dönsün (Frappe std)
    try:
        frappe.db.set_value("HD Ticket", ticket, "status", "Open")
    except Exception:
        frappe.log_error(title="reply_ticket status update")
    frappe.db.commit()
    return {"name": comm.name, "ok": True}


@frappe.whitelist(allow_guest=True)
@rate_limit(key="email", limit=10, seconds=300)
def create_ticket(
    subject: str,
    description: str,
    email: str = "",
    name: str = "",
    phone: str = "",
    priority: str = "",
    ticket_type: str = "",
    order_ref: str = "",
):
    """Storefront destek formu → HD Ticket.

    Guest (login olmayan) musteri de cagirabilir. raised_by = email.
    Login'li musteri varsa Frappe session.user kullanilir (email zorunlu degil).
    Rate-limit: email basina 5 dakikada 10 kez.
    """
    caller = frappe.session.user
    if caller and caller != "Guest":
        # Administrator gibi ozel user'lar icin name @ icermeyebilir — User.email'den al.
        user_email = frappe.db.get_value("User", caller, "email") or ""
        if "@" in caller:
            email = caller
        elif user_email:
            email = user_email
        # Hicbiri yoksa param'daki email kullanilir (zorunlu olur)
    email = _validate_email(email)
    subject = _clip(subject, 200)
    description = _clip(description, 10000)
    phone = _clip(phone, 40)
    customer_name = _clip(name, 200)
    order_ref = _clip(order_ref, 140)

    if not subject or not description:
        frappe.throw(_("Konu ve aciklama zorunludur."), frappe.ValidationError)

    # Team routing: sipariş varsa o siparişin satıcı team'ine, yoksa Platform Support
    if order_ref:
        team = resolve_team_for_order(order_ref) or ensure_platform_support_team()
    else:
        team = ensure_platform_support_team()

    # Helpdesk'in kendi validate/before_insert hook'lari "Agent" rolu istiyor
    # ve Link permission kontrolu yapıyor — hem Guest hem normal müşteri
    # user'da patlar. Her durumda Administrator'a gecici impersonate.
    original_user = caller
    try:
        if caller != "Administrator":
            frappe.set_user("Administrator")

        ticket = frappe.new_doc("HD Ticket")
        ticket.subject = subject
        ticket.description = description
        ticket.raised_by = email
        if priority:
            ticket.priority = priority
        # ticket_type Link(HD Ticket Type) — gecersiz deger gelirse sessizce atla
        if ticket_type and frappe.db.exists("HD Ticket Type", ticket_type):
            ticket.ticket_type = ticket_type
        if customer_name:
            ticket.customer_name = customer_name
        if phone:
            ticket.contact_phone = phone
        if team:
            ticket.agent_group = team
        ticket.insert(ignore_permissions=True)
        frappe.db.commit()
    finally:
        if caller != "Administrator":
            frappe.set_user(original_user)

    return {"name": ticket.name, "ok": True}

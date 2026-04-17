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
		"name",
		"subject",
		"status",
		"priority",
		"ticket_type",
		"raised_by",
		"creation",
		"modified",
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
			"name",
			"subject",
			"content",
			"sender",
			"sender_full_name",
			"recipients",
			"communication_date",
			"sent_or_received",
			"communication_medium",
		],
		order_by="communication_date asc",
		limit_page_length=200,
		ignore_permissions=True,
	)


@frappe.whitelist()
def agent_reply_ticket(ticket: str, content: str):
	"""Ajan HD Ticket'a müşteri yanıtı ekler (headless).

	Frappe Helpdesk'in standart `reply_via_agent` metodu e-posta göndermeyi
	zorunlu kılıyor (default outgoing Email Account gerekli). Biz headless
	akışta çalıştığımız için sadece Communication oluşturup ticket status'unu
	"Replied"e çeviriyoruz — müşteri RC üzerinden mesajı kendi sayfasında görür.
	"""
	if not ticket or not (content or "").strip():
		frappe.throw(_("Talep ve içerik zorunlu."), frappe.ValidationError)

	from helpdesk.utils import is_agent

	if not is_agent():
		frappe.throw(_("Bu işlem için ajan yetkisi gerekli."), frappe.PermissionError)

	caller = frappe.session.user
	sender_full_name = frappe.db.get_value("User", caller, "full_name") or caller
	ticket_doc = frappe.get_doc("HD Ticket", ticket)

	# Self-reply yasak: ayni user hem alici (raised_by) hem ajan olamaz —
	# kendi acitigi talebe alici baglaminda (storefront) yanit vermeli.
	if ticket_doc.raised_by == caller:
		frappe.throw(
			_("Kendi açtığınız talebe ajan olarak yanıt veremezsiniz. Alıcı sayfasından yanıtlayın."),
			frappe.PermissionError,
		)

	comm = frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Sent",
			"content": content,
			"reference_doctype": "HD Ticket",
			"reference_name": ticket,
			"sender": caller,
			"sender_full_name": sender_full_name,
			"recipients": ticket_doc.raised_by or "",
			"status": "Linked",
			"subject": f"Re: {ticket_doc.subject or ticket}",
		}
	)
	comm.insert(ignore_permissions=True)

	updates = {"status": "Replied"}
	if not ticket_doc.first_responded_on:
		updates["first_responded_on"] = frappe.utils.now()
	for k, v in updates.items():
		frappe.db.set_value("HD Ticket", ticket, k, v)

	frappe.db.commit()
	return {"name": comm.name, "ok": True}


@frappe.whitelist()
def reply_ticket(ticket: str, content: str):
	"""Müşteri HD Ticket'a yanıt ekler. Ticket'a erişim varsa Communication
	oluşturulur (sent_or_received='Received' — sisteme gelen)."""
	if not ticket or not (content or "").strip():
		frappe.throw(_("Talep ve içerik zorunlu."), frappe.ValidationError)
	if not frappe.has_permission("HD Ticket", doc=ticket, ptype="read"):
		frappe.throw(_("Bu talebe erişim yetkiniz yok."), frappe.PermissionError)

	caller = frappe.session.user
	comm = frappe.get_doc(
		{
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
		}
	)
	comm.insert(ignore_permissions=True)
	# HD Ticket status'u müşteri yanıtında tekrar "Open"a dönsün (Frappe std)
	try:
		frappe.db.set_value("HD Ticket", ticket, "status", "Open")
	except Exception:
		frappe.log_error(title="reply_ticket status update")
	frappe.db.commit()
	return {"name": comm.name, "ok": True}


# Satici tarafina yonlendirilecek kategoriler — order_ref zorunlu.
# Gerisi (odeme/hesap/diger) Platform Support'a duser.
_SELLER_CATEGORIES = frozenset({"siparis", "kargo", "urun"})


@frappe.whitelist()
@rate_limit(key="user", limit=10, seconds=300)
def create_ticket(
	subject: str,
	description: str,
	name: str = "",
	phone: str = "",
	priority: str = "",
	ticket_type: str = "",
	order_ref: str = "",
	category: str = "",
):
	"""Storefront destek formu → HD Ticket.

	Login zorunlu — alıcı/satıcı kayıt + giriş yapmadan talep oluşturamaz.
	raised_by = session.user.email. Rate-limit: user başına 5 dakikada 10 kez.

	Kategori routing:
	  - siparis/kargo/urun → satici team (order_ref zorunlu)
	  - odeme/hesap/diger/bos → Platform Support (order_ref yoksayilir)
	"""
	caller = frappe.session.user
	if not caller or caller == "Guest":
		frappe.throw(_("Talep oluşturmak için giriş yapmalısınız."), frappe.PermissionError)

	# Administrator gibi ozel user'lar icin name @ icermeyebilir — User.email'den al.
	user_email = frappe.db.get_value("User", caller, "email") or ""
	email = caller if "@" in caller else user_email
	email = _validate_email(email)
	subject = _clip(subject, 200)
	description = _clip(description, 10000)
	phone = _clip(phone, 40)
	customer_name = _clip(name, 200)
	order_ref = _clip(order_ref, 140)
	category = _clip(category, 40).strip().lower()

	if not subject or not description:
		frappe.throw(_("Konu ve aciklama zorunludur."), frappe.ValidationError)

	# Kategori-bazli routing
	if category in _SELLER_CATEGORIES:
		if not order_ref:
			frappe.throw(
				_("Bu kategori için sipariş referansı zorunludur."),
				frappe.ValidationError,
			)
		# Cikar catismasi: satici kendi siparisine ajan-tarafli destek acamaz.
		# Platform kategorileri (odeme/hesap/diger) ile hala talep olusturabilir —
		# o yol Platform Support'a duser, satici team'ine degil.
		seller = frappe.db.get_value("Order", order_ref, "seller")
		if seller:
			seller_user = frappe.db.get_value("Admin Seller Profile", seller, "user")
			if seller_user and seller_user == caller:
				frappe.throw(
					_("Kendi sattığınız sipariş için destek talebi açamazsınız."),
					frappe.ValidationError,
				)
		team = resolve_team_for_order(order_ref) or ensure_platform_support_team()
	else:
		# Platform-seviyesi kategoriler (odeme/hesap/diger) veya kategorisiz
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


# ── Attachment API ─────────────────────────────────────────────────────────
# MVP: HD Ticket'a bagli File doctype kayitlarini musteri/ajan upload'u icin
# whitelisted wrapper. Max 5 dosya, her biri 10MB. is_private=1 — sadece yetkili
# kullanici download edebilir.

_MAX_TICKET_FILES = 5
_MAX_TICKET_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@frappe.whitelist()
@rate_limit(key="user", limit=20, seconds=300)
def upload_ticket_attachment(ticket: str):
	"""Ticket'a dosya ekle. Multipart form data — 'file' field.

	Musteri kendi ticket'ina, agent ise yetkili oldugu ticket'a yukleyebilir.
	Permission check HD Ticket uzerinden (ayni query condition ile tutarli).
	"""
	if not ticket:
		frappe.throw(_("Talep kimliği gerekli."), frappe.ValidationError)
	if not frappe.has_permission("HD Ticket", doc=ticket, ptype="read"):
		frappe.throw(_("Bu talebe erişim yetkiniz yok."), frappe.PermissionError)

	existing = frappe.db.count(
		"File",
		{"attached_to_doctype": "HD Ticket", "attached_to_name": ticket},
	)
	if existing >= _MAX_TICKET_FILES:
		frappe.throw(
			_("Bu talep için maksimum {0} dosya eklenebilir.").format(_MAX_TICKET_FILES),
			frappe.ValidationError,
		)

	content = getattr(frappe.local, "uploaded_file", None)
	filename = getattr(frappe.local, "uploaded_filename", None) or "attachment"

	if not content:
		frappe.throw(_("Dosya gönderilmedi."), frappe.ValidationError)
	if len(content) > _MAX_TICKET_FILE_SIZE:
		frappe.throw(
			_("Dosya 10MB'dan büyük olamaz."),
			frappe.ValidationError,
		)

	from frappe.utils.file_manager import save_file

	file_doc = save_file(
		fname=filename,
		content=content,
		dt="HD Ticket",
		dn=ticket,
		is_private=1,
	)
	frappe.db.commit()
	return {
		"name": file_doc.name,
		"file_name": file_doc.file_name,
		"file_url": file_doc.file_url,
		"file_size": file_doc.file_size,
	}


@frappe.whitelist()
def list_ticket_attachments(ticket: str):
	"""Ticket'a bagli tum File kayitlarini dondur.

	Musteri File doctype'ina direkt read yetkisine sahip degil; HD Ticket
	ownership varsa ignore_permissions ile okuyoruz.
	"""
	if not ticket:
		return []
	if not frappe.has_permission("HD Ticket", doc=ticket, ptype="read"):
		frappe.throw(_("Bu talebe erişim yetkiniz yok."), frappe.PermissionError)

	return frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "HD Ticket",
			"attached_to_name": ticket,
		},
		fields=["name", "file_name", "file_url", "file_size", "creation", "owner", "is_private"],
		order_by="creation asc",
		ignore_permissions=True,
		limit_page_length=50,
	)

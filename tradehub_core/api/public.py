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
from urllib.parse import quote

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from tradehub_core.seo.site_url import admin_panel_url, storefront_url
from tradehub_core.utils.helpdesk_routing import (
	ensure_platform_support_team,
	resolve_team_for_order,
)
from tradehub_core.utils.notify import notify, notify_assigned_users, notify_team_members

EMAIL_RE = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")


# ── Ticket URL helpers ─────────────────────────────────────────────────
# Storefront ve admin panel URL'leri ortam-özel; merkezî site_url helper'ından
# (backend site adına göre, restore-proof) türetilir. Bildirim e-postalarındaki
# tıklanabilir link bu fonksiyonlardan üretilir.


def _storefront_ticket_url(name: str) -> str:
	return f"{storefront_url()}/pages/help/help-ticket.html?id={quote(name, safe='')}"


def _admin_ticket_url(name: str) -> str:
	return f"{admin_panel_url()}/helpdesk/tickets/{quote(name, safe='')}"


def _ticket_email_html(heading: str, ticket_subject: str, body_text: str, link: str, link_label: str) -> str:
	"""Tutarlı bir HTML şablonu. CSS inline — Frappe Email Queue'da güvenli."""
	safe_subject = frappe.utils.escape_html(ticket_subject or "")
	safe_body = frappe.utils.escape_html(body_text or "").replace("\n", "<br>")
	return f"""
<div style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; color: #222; max-width: 560px;">
  <h2 style="margin: 0 0 16px; font-size: 18px; color: #111;">{frappe.utils.escape_html(heading)}</h2>
  <p style="margin: 0 0 8px; font-size: 14px;"><strong>Konu:</strong> {safe_subject}</p>
  <div style="margin: 16px 0; padding: 12px 14px; background: #f6f7fb; border-left: 3px solid #7c3aed; border-radius: 4px; font-size: 14px; line-height: 1.5;">
    {safe_body}
  </div>
  <p style="margin: 24px 0 0;">
    <a href="{frappe.utils.escape_html(link)}"
       style="display: inline-block; padding: 10px 18px; background: #7c3aed; color: #fff; text-decoration: none; border-radius: 6px; font-size: 14px;">
      {frappe.utils.escape_html(link_label)}
    </a>
  </p>
  <p style="margin: 28px 0 0; font-size: 11px; color: #888;">
    Bu e-posta TradeHub Marketplace üzerinden otomatik gönderildi.
  </p>
</div>
""".strip()


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

	# Müşteri bildirimi (in-app + e-posta)
	try:
		_notify_customer_reply(ticket_doc, content, agent_name=sender_full_name)
	except Exception:
		frappe.log_error(title="agent_reply_ticket: notify_customer")

	return {"name": comm.name, "ok": True}


def _notify_customer_reply(ticket_doc, content: str, agent_name: str = ""):
	"""Ajan yanıt verdiğinde müşteriye (raised_by) in-app + e-posta bildir."""
	customer = ticket_doc.raised_by or ""
	if not customer:
		return
	preview = (content or "")[:300]
	link = _storefront_ticket_url(ticket_doc.name)
	body_html = _ticket_email_html(
		heading=(f"{agent_name} talebinize yanıt verdi" if agent_name else "Talebinize yanıt geldi"),
		ticket_subject=ticket_doc.subject or "",
		body_text=preview,
		link=link,
		link_label="Yanıtı Görüntüle",
	)
	notify(
		recipient_user=customer,
		type="dispute",
		title=f"Talebinize yanıt: {ticket_doc.subject or ticket_doc.name}",
		message=preview or "Destek ekibi talebinize yanıt verdi.",
		recipient_role="buyer",
		action_url=f"/pages/help/help-ticket.html?id={ticket_doc.name}",
		reference_doctype="HD Ticket",
		reference_name=ticket_doc.name,
		send_email=True,
		email_subject=f"[TradeHub] Talebinize yanıt geldi: {ticket_doc.subject or ticket_doc.name}",
		email_body=body_html,
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

	# Ajan bildirimi (atanmışlar varsa onlara, yoksa team'e — e-posta dahil)
	try:
		_notify_customer_replied(ticket, content, customer_user=caller)
	except Exception:
		frappe.log_error(title="reply_ticket: notify_agents")

	return {"name": comm.name, "ok": True}


def _notify_customer_replied(ticket_name: str, content: str, customer_user: str = ""):
	"""Müşteri yanıt verdiğinde ajanlara (atanan veya team) in-app + e-posta bildir."""
	ticket_doc = frappe.db.get_value(
		"HD Ticket",
		ticket_name,
		["subject", "agent_group", "raised_by"],
		as_dict=True,
	)
	if not ticket_doc:
		return

	preview = (content or "")[:300]
	link = _admin_ticket_url(ticket_name)
	customer_label = ticket_doc.raised_by or "Müşteri"
	body_html = _ticket_email_html(
		heading=f"{customer_label} talebine yanıt verdi",
		ticket_subject=ticket_doc.subject or "",
		body_text=preview,
		link=link,
		link_label="Talebi Aç",
	)
	title = f"Müşteri yanıtı: {ticket_doc.subject or ticket_name}"
	message = preview or "Müşteri talebine yeni bir yanıt ekledi."
	subject = f"[TradeHub] Müşteri yanıtladı: {ticket_doc.subject or ticket_name}"

	# 1) Atanmış ajan(lar) — birincil hedef
	assigned_count = notify_assigned_users(
		doctype="HD Ticket",
		docname=ticket_name,
		type="dispute",
		title=title,
		message=message,
		action_url=f"/helpdesk/tickets/{ticket_name}",
		send_email=True,
		email_subject=subject,
		email_body=body_html,
		exclude_user=customer_user,
		recipient_role="admin",
	)

	# 2) Atanmış yoksa team'e fallback
	if assigned_count == 0 and ticket_doc.agent_group:
		notify_team_members(
			team_name=ticket_doc.agent_group,
			type="dispute",
			title=title,
			message=message,
			action_url=f"/helpdesk/tickets/{ticket_name}",
			reference_doctype="HD Ticket",
			reference_name=ticket_name,
			send_email=True,
			email_subject=subject,
			email_body=body_html,
			exclude_user=customer_user,
		)


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
	related_order: str = "",
	related_rfq: str = "",
	related_listing: str = "",
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
		# Yeni: marketplace Link alanları (custom fields). Geçersiz Link
		# değerleri sessizce atlanır — frontend yanlış ID gönderse de
		# ticket oluşur.
		if related_order and frappe.db.exists("Order", related_order):
			ticket.related_order = related_order
		if related_rfq and frappe.db.exists("RFQ", related_rfq):
			ticket.related_rfq = related_rfq
		if related_listing and frappe.db.exists("Listing", related_listing):
			ticket.related_listing = related_listing
		# order_ref string'i hâlâ destekliyor (geriye uyum); related_order
		# verilmediyse onu kullan
		if order_ref and not getattr(ticket, "related_order", None):
			if frappe.db.exists("Order", order_ref):
				ticket.related_order = order_ref
		ticket.insert(ignore_permissions=True)
		frappe.db.commit()
	finally:
		if caller != "Administrator":
			frappe.set_user(original_user)

	# Yeni ticket → routed team üyelerine bildir (müşteri hariç)
	try:
		_notify_new_ticket(ticket, exclude_user=caller)
	except Exception:
		frappe.log_error(title="create_ticket: notify_new_ticket")

	return {"name": ticket.name, "ok": True}


def _notify_new_ticket(ticket, exclude_user: str = ""):
	"""Yeni HD Ticket oluştuğunda atandığı team üyelerine in-app + e-posta bildirim."""
	team = ticket.agent_group or ""
	if not team:
		return
	link = _admin_ticket_url(ticket.name)
	preview = (ticket.description or "")[:300]
	body_html = _ticket_email_html(
		heading="Yeni destek talebi geldi",
		ticket_subject=ticket.subject or "",
		body_text=preview,
		link=link,
		link_label="Talebi Aç",
	)
	notify_team_members(
		team_name=team,
		type="dispute",
		title=f"Yeni talep: {ticket.subject or ticket.name}",
		message=preview or "Yeni bir destek talebi açıldı.",
		action_url=f"/helpdesk/tickets/{ticket.name}",
		reference_doctype="HD Ticket",
		reference_name=ticket.name,
		send_email=True,
		email_subject=f"[TradeHub] Yeni destek talebi: {ticket.subject or ticket.name}",
		email_body=body_html,
		exclude_user=exclude_user,
	)


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
def helpdesk_dashboard_kpis():
	"""Ajan/admin paneli için permission-aware ticket KPI sayıları.

	`frappe.client.get_count` permission_query_conditions'ı honor etmediğinden
	(direkt frappe.db.count'a yönelir), satıcı agent kendi team'inde olmayan
	ticket sayısını da görüyordu. Burada `frappe.get_list` kullanarak
	permission query'sini honor ediyoruz; satıcı yalnız kendi team'inin,
	platform support yöneticisi ise hepsini sayar.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Giriş yapmalısınız."), frappe.PermissionError)

	# get_list permission_query_conditions ile ortak çalışır (helpdesk_ticket_query_conditions).
	# Sadece name alanı yeterli — sayım için.
	open_rows = frappe.get_list(
		"HD Ticket",
		filters={"status": "Open"},
		fields=["name"],
		limit_page_length=10000,
	)
	replied_rows = frappe.get_list(
		"HD Ticket",
		filters={"status": "Replied"},
		fields=["name"],
		limit_page_length=10000,
	)

	mine_open_rows = frappe.get_list(
		"HD Ticket",
		filters={
			"status": ["in", ["Open", "Replied"]],
			"_assign": ["like", f"%{user}%"],
		},
		fields=["name"],
		limit_page_length=10000,
	)

	since = frappe.utils.add_to_date(frappe.utils.now(), days=-7)
	resolved_rows = frappe.get_list(
		"HD Ticket",
		filters={
			"status": ["in", ["Resolved", "Closed"]],
			"resolution_date": [">=", since],
		},
		fields=["name"],
		limit_page_length=10000,
	)

	return {
		"open": len(open_rows),
		"replied": len(replied_rows),
		"mine_open": len(mine_open_rows),
		"resolved_week": len(resolved_rows),
	}


@frappe.whitelist()
def bulk_update_tickets(tickets: str, action: str, value: str = ""):
	"""Toplu HD Ticket güncelleme — ajan-side bulk action.

	tickets: JSON-encoded list of ticket names
	action: "status" | "priority" | "assign" | "agent_group"
	value: action'a bağlı değer

	Permission query her ticket için ayrı kontrol edilir; yetkisiz olanlar
	sessizce skip edilir, sonuçta {ok, skipped} sayıları döner.
	"""
	import json

	if not tickets or not action:
		frappe.throw(_("tickets ve action zorunlu."), frappe.ValidationError)

	try:
		ticket_list = json.loads(tickets) if isinstance(tickets, str) else tickets
	except (TypeError, ValueError):
		frappe.throw(_("Geçersiz tickets formatı."), frappe.ValidationError)

	if not isinstance(ticket_list, list) or not ticket_list:
		frappe.throw(_("En az bir ticket seçilmeli."), frappe.ValidationError)
	if len(ticket_list) > 200:
		frappe.throw(_("Tek seferde maksimum 200 ticket güncellenebilir."), frappe.ValidationError)

	allowed_status = {"Open", "Replied", "Resolved", "Closed"}
	allowed_priority = {"Low", "Medium", "High", "Urgent"}

	if action == "status":
		if value not in allowed_status:
			frappe.throw(_("Geçersiz status."), frappe.ValidationError)
	elif action == "priority":
		if value not in allowed_priority:
			frappe.throw(_("Geçersiz öncelik."), frappe.ValidationError)
	elif action == "assign":
		if not value:
			frappe.throw(_("Atanacak kullanıcı gerekli."), frappe.ValidationError)
		# value bir user (e-posta) — varlık kontrolü
		if not frappe.db.exists("User", value):
			frappe.throw(_("Kullanıcı bulunamadı."), frappe.ValidationError)
	elif action == "agent_group":
		if not value or not frappe.db.exists("HD Team", value):
			frappe.throw(_("Geçersiz HD Team."), frappe.ValidationError)
	else:
		frappe.throw(_("Bilinmeyen action."), frappe.ValidationError)

	ok = 0
	skipped = 0
	for t in ticket_list:
		if not frappe.has_permission("HD Ticket", doc=t, ptype="write"):
			skipped += 1
			continue
		try:
			if action == "status":
				frappe.db.set_value("HD Ticket", t, "status", value)
			elif action == "priority":
				frappe.db.set_value("HD Ticket", t, "priority", value)
			elif action == "agent_group":
				frappe.db.set_value("HD Ticket", t, "agent_group", value)
			elif action == "assign":
				from frappe.desk.form.assign_to import add as assign_add

				assign_add({"assign_to": [value], "doctype": "HD Ticket", "name": t})
			ok += 1
		except Exception:
			frappe.log_error(title=f"bulk_update_tickets {t}")
			skipped += 1

	frappe.db.commit()
	return {"ok": ok, "skipped": skipped, "total": len(ticket_list)}


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

"""
Satıcıya özel CRM agregasyonları + Marketplace köprüleri.

Endpoints:
  - dashboard_kpis(): satıcı CRM dashboard widget'ları için tek istek
  - inquiry_to_lead(inquiry): Mağaza Sorusu → CRM Lead dönüşümü
  - rfq_to_lead(rfq): RFQ → CRM Lead dönüşümü
  - lead_to_deal(lead, deal_data): Lead → Deal (Frappe convert_to_deal wrapper)

Tüm fonksiyonlar `permission_query_conditions` kuralları üzerinden çalışır;
satıcı yalnız kendi verisine erişir.
"""

import json

import frappe
from frappe import _


def _get_my_seller_profile():
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Giriş yapmalısınız."), frappe.PermissionError)
	profile = frappe.db.get_value(
		"Admin Seller Profile",
		{"user": user, "status": "Active"},
		"name",
	)
	return profile, user


# ── Dashboard KPI ──────────────────────────────────────────────────────


@frappe.whitelist()
def dashboard_kpis():
	"""Satıcı CRM dashboard'u için tek istekte tüm KPI'lar.

	frappe.get_list permission query'sini honor eder; yani System Manager
	tüm sistem genelini, satıcı kendi seller'ını sayar. Sales User da admin
	tarafında full görür.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Giriş yapmalısınız."), frappe.PermissionError)

	# Açık Lead'ler (status open/contacted/qualified vs — Won/Lost değil)
	open_leads = frappe.get_list(
		"CRM Lead",
		filters={"status": ["not in", ["Junk", "Lost", "Converted"]]},
		fields=["name"],
		limit_page_length=10000,
	)

	# Açık Deal'ler (status Lost/Won olmayan)
	open_deals = frappe.get_list(
		"CRM Deal",
		filters={"status": ["not in", ["Won", "Lost"]]},
		fields=["name", "deal_value", "expected_deal_value", "probability"],
		limit_page_length=10000,
	)

	pipeline_value = sum(float(d.get("deal_value") or d.get("expected_deal_value") or 0) for d in open_deals)
	weighted_pipeline = sum(
		float(d.get("deal_value") or d.get("expected_deal_value") or 0)
		* (float(d.get("probability") or 0) / 100.0)
		for d in open_deals
	)

	# Bu ay kazanılan Deal sayısı + tutarı
	from frappe.utils import get_first_day, getdate, nowdate

	month_start = get_first_day(getdate(nowdate())).strftime("%Y-%m-%d")
	won_this_month = frappe.get_list(
		"CRM Deal",
		filters={
			"status": "Won",
			"closed_date": [">=", month_start],
		},
		fields=["name", "deal_value"],
		limit_page_length=10000,
	)
	won_amount = sum(float(d.get("deal_value") or 0) for d in won_this_month)

	# Conversion rate (son 30 gün lead'lerden Deal'e dönen oranı)
	thirty_ago = frappe.utils.add_to_date(frappe.utils.now(), days=-30)
	recent_leads = frappe.get_list(
		"CRM Lead",
		filters={"creation": [">=", thirty_ago]},
		fields=["name", "converted"],
		limit_page_length=10000,
	)
	total_recent = len(recent_leads)
	converted_recent = sum(1 for l in recent_leads if l.get("converted"))
	conversion_rate = (converted_recent / total_recent * 100.0) if total_recent else 0.0

	# Bana atanmış açık Task sayısı
	my_open_tasks = frappe.get_list(
		"CRM Task",
		filters={
			"status": ["not in", ["Done", "Cancelled"]],
			"assigned_to": user,
		},
		fields=["name"],
		limit_page_length=10000,
	)

	return {
		"open_leads": len(open_leads),
		"open_deals": len(open_deals),
		"pipeline_value": round(pipeline_value, 2),
		"weighted_pipeline": round(weighted_pipeline, 2),
		"won_this_month_count": len(won_this_month),
		"won_this_month_amount": round(won_amount, 2),
		"conversion_rate": round(conversion_rate, 1),
		"my_open_tasks": len(my_open_tasks),
	}


# ── Köprüler: Inquiry / RFQ → Lead ───────────────────────────────────


@frappe.whitelist()
def inquiry_to_lead(inquiry: str, lead_owner: str = ""):
	"""Mağaza Sorusu → CRM Lead. Satıcı kendi inquiry'sini lead'e yükseltir.

	Mapping:
	  Seller Inquiry.sender_name  → CRM Lead.first_name
	  Seller Inquiry.sender_email → CRM Lead.email
	  Seller Inquiry.message      → CRM Lead.first_name + (notes)
	  CRM Lead.seller             → satıcının kendi profile'ı (autoset hook)
	  CRM Lead.source             → 'Mağaza Sorusu'
	"""
	from tradehub_core.utils.seller_capabilities import require_seller_capability

	require_seller_capability("crm.lead_capture")

	if not inquiry:
		frappe.throw(_("Inquiry kimliği gerekli."), frappe.ValidationError)
	if not frappe.has_permission("Seller Inquiry", doc=inquiry, ptype="read"):
		frappe.throw(_("Bu soruya erişim yok."), frappe.PermissionError)

	inq = frappe.get_doc("Seller Inquiry", inquiry)

	# Aynı email zaten lead olarak kayıtlıysa onu döndür
	existing = None
	if inq.sender_email:
		existing = frappe.db.get_value(
			"CRM Lead",
			{"email": inq.sender_email, "seller": inq.seller},
			"name",
		)
	if existing:
		return {"name": existing, "ok": True, "existed": True}

	_ensure_lead_source("Mağaza Sorusu")

	lead = frappe.new_doc("CRM Lead")
	# sender_name "Ad Soyad" şeklinde gelebilir; ilk kelimeyi first_name'e
	# kalanını last_name'e koyalım.
	full_name = (inq.sender_name or "").strip()
	parts = full_name.split(" ", 1)
	lead.first_name = parts[0] if parts and parts[0] else (inq.sender_email or "Müşteri")
	if len(parts) == 2:
		lead.last_name = parts[1]
	if inq.sender_email:
		lead.email = inq.sender_email
	if inq.buyer:
		# Buyer User Link → mobile_no zenginleştir
		mobile = frappe.db.get_value("User", inq.buyer, "mobile_no")
		if mobile:
			lead.mobile_no = mobile
	lead.source = "Mağaza Sorusu"
	lead.seller = inq.seller  # autoset hook devreye girmeden direkt set
	if lead_owner:
		lead.lead_owner = lead_owner
	# Notes — Frappe CRM'de explicit notes field'ı yok; details'e koyalım
	if inq.message:
		lead.details = f"[Mağaza Sorusu #{inq.name}]\n\n{inq.message}"

	lead.insert(ignore_permissions=True)
	frappe.db.commit()

	return {"name": lead.name, "ok": True, "existed": False}


@frappe.whitelist()
def rfq_to_lead(rfq: str, lead_owner: str = ""):
	"""RFQ → CRM Lead. Satıcı RFQ'ya bakıp ilgilendiyse lead açar.

	RFQ doctype field'ı projeye göre değişebilir; aşağıda yaygın kabul
	edilen field'ları kullanıyoruz; yoksa fallback davranış.
	"""
	from tradehub_core.utils.seller_capabilities import require_seller_capability

	require_seller_capability("crm.lead_capture")

	if not rfq:
		frappe.throw(_("RFQ kimliği gerekli."), frappe.ValidationError)
	if not frappe.has_permission("RFQ", doc=rfq, ptype="read"):
		frappe.throw(_("Bu RFQ'ya erişim yok."), frappe.PermissionError)

	rfq_doc = frappe.get_doc("RFQ", rfq)

	# Genel field'lar — yoksa boş kalsın
	rfq_buyer = getattr(rfq_doc, "buyer", None) or getattr(rfq_doc, "user", None) or ""
	rfq_subject = getattr(rfq_doc, "title", None) or getattr(rfq_doc, "subject", None) or ""
	rfq_description = getattr(rfq_doc, "description", None) or getattr(rfq_doc, "message", None) or ""

	# Email ve isim — buyer User'dan
	email, name_full, mobile = "", "", ""
	if rfq_buyer:
		user_doc = frappe.db.get_value("User", rfq_buyer, ["email", "full_name", "mobile_no"], as_dict=True)
		if user_doc:
			email = user_doc.email or rfq_buyer
			name_full = user_doc.full_name or ""
			mobile = user_doc.mobile_no or ""

	# Çağıranın seller'ı
	profile, _user = _get_my_seller_profile()

	# Mevcut lead var mı (aynı email + seller)
	if email:
		existing = frappe.db.get_value(
			"CRM Lead",
			{"email": email, "seller": profile},
			"name",
		)
		if existing:
			return {"name": existing, "ok": True, "existed": True}

	_ensure_lead_source("RFQ")

	lead = frappe.new_doc("CRM Lead")
	parts = (name_full or email or "Müşteri").split(" ", 1)
	lead.first_name = parts[0]
	if len(parts) == 2:
		lead.last_name = parts[1]
	if email:
		lead.email = email
	if mobile:
		lead.mobile_no = mobile
	lead.source = "RFQ"
	lead.seller = profile
	if lead_owner:
		lead.lead_owner = lead_owner
	if rfq_subject or rfq_description:
		lead.details = f"[RFQ #{rfq}]\n\n{rfq_subject}\n\n{rfq_description}"

	lead.insert(ignore_permissions=True)
	frappe.db.commit()

	return {"name": lead.name, "ok": True, "existed": False}


@frappe.whitelist()
def lead_to_deal(lead: str, deal_data: str = ""):
	"""Lead → Deal dönüşümü için ince wrapper.

	Frappe CRM'in `convert_to_deal` method'unu kullanır; öncesinde permission
	kontrolü yapılır. Yeni Deal'in seller alanı hook ile otomatik set edilir.
	"""
	if not lead:
		frappe.throw(_("Lead kimliği gerekli."), frappe.ValidationError)
	if not frappe.has_permission("CRM Lead", doc=lead, ptype="write"):
		frappe.throw(_("Lead'i dönüştürme yetkiniz yok."), frappe.PermissionError)

	deal_dict = {}
	if deal_data:
		try:
			deal_dict = json.loads(deal_data) if isinstance(deal_data, str) else deal_data
		except (TypeError, ValueError):
			deal_dict = {}

	lead_doc = frappe.get_doc("CRM Lead", lead)
	deal_name = lead_doc.convert_to_deal(deal=deal_dict)
	frappe.db.commit()
	return {"name": deal_name, "ok": True}


# ── Helpers ───────────────────────────────────────────────────────────


def _ensure_lead_source(name: str):
	"""CRM Lead Source kaydı yoksa oluştur."""
	if not name:
		return
	if frappe.db.exists("CRM Lead Source", name):
		return
	try:
		doc = frappe.new_doc("CRM Lead Source")
		doc.lead_source = name
		doc.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title=f"_ensure_lead_source: {name}")

# Copyright (c) 2026, TR TradeHub and contributors
"""Saha pazarlama hakediş üretimi — CRM Deal 'Won' olunca otomatik Field Commission.

Faz 1: Deal kazanıldığında tek seferlik (period_index=1) Beklemede kayıt üretir.
Tekrarlayan/süreli modlar Faz 2'de store_subscription yenilemelerine bağlanır.
"""

import frappe
from frappe.utils import flt


def _deal_is_won(doc) -> bool:
	"""CRM Deal status'ü 'Won' tipinde mi? Status, CRM Deal Status'e Link."""
	status = doc.get("status")
	if not status:
		return False
	status_type = frappe.db.get_value("CRM Deal Status", status, "type")
	if status_type:
		return status_type == "Won"
	# Fallback: type alanı yoksa isim eşleşmesi
	return str(status).strip().lower() == "won"


def _base_amount(deal, plan_doc) -> float:
	"""Esas tutar: deal override > paket aylık fiyat > paket yıllık fiyat."""
	override = flt(deal.get("custom_sale_amount"))
	if override > 0:
		return override
	monthly = flt(plan_doc.get("monthly_price"))
	if monthly > 0:
		return monthly
	return flt(plan_doc.get("yearly_price"))


def _global_per_sale_amount() -> float:
	"""Saha Hakediş Ayarları'ndaki global satış-başı sabit tutar (0 = tanımsız)."""
	return flt(frappe.db.get_single_value("Field Commission Settings", "global_per_sale_amount"))


def _resolve_commission(deal, plan_doc) -> dict | None:
	"""Komisyonu çöz. Precedence: plan ayarı (Yüzde/Sabit) > global sabit tutar.

	Plan'da anlamlı ayar yoksa (oran/sabit 0/boş) global satış-başı sabit tutara düşer.
	Hiçbiri tanımlı değilse None (hakediş üretilmez).
	commission_amount Yüzde'de 0 bırakılır; doctype validate base×rate/100 hesaplar.
	"""
	ctype = plan_doc.get("field_commission_type")
	if ctype == "Sabit Ücret":
		fixed = flt(plan_doc.get("field_commission_fixed_amount"))
		if fixed > 0:
			return {
				"commission_type": "Sabit Ücret",
				"base_amount": 0,
				"commission_rate": 0,
				"commission_amount": fixed,
			}
	elif ctype == "Yüzde":
		rate = flt(plan_doc.get("field_commission_rate"))
		base = _base_amount(deal, plan_doc)
		if rate > 0 and base > 0:
			return {
				"commission_type": "Yüzde",
				"base_amount": base,
				"commission_rate": rate,
				"commission_amount": 0,
			}

	glob = _global_per_sale_amount()
	if glob > 0:
		return {
			"commission_type": "Sabit Ücret",
			"base_amount": 0,
			"commission_rate": 0,
			"commission_amount": glob,
		}
	return None


def generate_on_deal_won(doc, method=None):
	"""CRM Deal on_update hook. Won + paket dolu ise Beklemede hakediş üretir.

	Komisyon türü pakette tanımlı: 'Yüzde' (paket fiyatının %'si) veya
	'Sabit Ücret' (satış başına sabit tutar). İlgili tutar 0/boşsa üretilmez.
	"""
	if not _deal_is_won(doc):
		return

	plan_code = doc.get("custom_subscription_plan")
	agent = doc.get("deal_owner")
	if not plan_code or not agent:
		return

	# Idempotency: deal + dönem başına tek kayıt.
	if frappe.db.exists("Field Commission", {"deal": doc.name, "period_index": 1}):
		return

	plan_doc = frappe.get_cached_doc("Subscription Plan", plan_code)
	resolved = _resolve_commission(doc, plan_doc)
	if not resolved:
		return

	fc = frappe.new_doc("Field Commission")
	fc.agent = agent
	fc.deal = doc.name
	fc.plan = plan_code
	fc.currency = plan_doc.get("currency") or doc.get("currency")
	fc.commission_mode = plan_doc.get("field_commission_mode") or "Tek seferlik"
	fc.period_index = 1
	fc.status = "Beklemede"
	fc.commission_type = resolved["commission_type"]
	fc.base_amount = resolved["base_amount"]
	fc.commission_rate = resolved["commission_rate"]
	fc.commission_amount = resolved["commission_amount"]
	fc.insert(ignore_permissions=True)

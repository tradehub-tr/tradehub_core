"""Buyer dashboard analitik özeti.

4 KPI (toplam harcama, aktif sipariş, bekleyen teklif, pazarlık tasarrufu),
son 6 aylık harcama trendi ve kategori dağılımı tek endpoint'te döner.
Ham sayılar döner; formatlama/renk/etiket frontend'de yapılır.

Sorgu kuralı: kullanıcı verisi (Order, RFQ) `get_list` ile okunur
(permission_query_conditions devreye girsin). Child tablo (Order Item),
satıcıya ait RFQ Quote ve referans/listing okumaları `get_all` ile yapılır —
her biri buyer'ın kendi kayıtlarıyla zaten scoped (gerekçe satır içinde).
"""

import frappe
from frappe.utils import add_months, flt, get_first_day, getdate, nowdate

from tradehub_core.api.order import _require_buyer

# Order.status haritası — "harcama" ödeme bekleyen + iptal hariç.
SPEND_STATUSES = ["Onaylanıyor", "Kargoda", "Tamamlandı"]
PREPARING_STATUS = "Onaylanıyor"  # "hazırlanıyor"
SHIPPING_STATUS = "Kargoda"  # "yolda"
TREND_MONTHS = 6
TOP_CATEGORIES = 5  # + "Diğer"
DEFAULT_CURRENCY = "TRY"

_TR_MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


@frappe.whitelist()
def get_buyer_analytics():
	"""Giriş yapan buyer için dashboard analitik özeti."""
	user = _require_buyer()
	return {
		"kpis": {
			"total_spend": _total_spend(user),
			"active_orders": _active_orders(user),
			"pending_quotes": _pending_quotes(user),
			"negotiation_savings": _negotiation_savings(user),
		},
		"spending_trend": _spending_trend(user),
		"category_breakdown": _category_breakdown(user),
	}


def _sum_spend(user, start, end):
	"""[start, end) aralığında buyer'ın SPEND_STATUSES siparişlerinin toplam tutarı."""
	rows = frappe.get_list(
		"Order",
		filters=[
			["buyer", "=", user],
			["status", "in", SPEND_STATUSES],
			["order_date", ">=", start],
			["order_date", "<", end],
		],
		fields=["total"],
		page_length=5000,  # harcama toplaması — pratik üst sınır; daha fazlası chunk'a alınmalı
	)
	return sum(flt(r.total) for r in rows)


def _total_spend(user):
	today = getdate(nowdate())
	this_start = get_first_day(today)
	next_start = get_first_day(add_months(today, 1))
	last_start = get_first_day(add_months(today, -1))

	this_amount = _sum_spend(user, this_start, next_start)
	last_amount = _sum_spend(user, last_start, this_start)

	if last_amount:
		change_pct = round((this_amount - last_amount) / last_amount * 100, 1)
		trend = "up" if change_pct > 0 else "down" if change_pct < 0 else "neutral"
	else:
		# Geçen ay harcama yok → yüzde değişim anlamsız (0'a bölme / sonsuz artış).
		# Yanıltıcı "%0 yükseliş" yerine nötr işaret.
		change_pct = 0.0
		trend = "neutral"

	return {
		"amount": round(this_amount),
		"currency": DEFAULT_CURRENCY,
		"change_pct": change_pct,
		"trend": trend,
	}


def _active_orders(user):
	# db.count buyer ile scoped — permission sızıntısı yok, sayım için get_list'ten ucuz.
	preparing = frappe.db.count("Order", {"buyer": user, "status": PREPARING_STATUS})
	shipping = frappe.db.count("Order", {"buyer": user, "status": SHIPPING_STATUS})
	return {"count": preparing + shipping, "shipping": shipping, "preparing": preparing}


def _pending_quotes(user):
	open_rfqs = frappe.get_list(
		"RFQ", filters={"buyer": user, "status": "Pending"}, pluck="name", page_length=1000  # buyer'a ait sınırlı dataset
	)
	quote_count = 0
	if open_rfqs:
		# RFQ Quote satıcıya ait; buyer'ın açık RFQ'larıyla scoped. db.count → permission-bypass kasıtlı.
		quote_count = frappe.db.count("RFQ Quote", {"rfq": ["in", open_rfqs], "status": "Submitted"})
	return {"quote_count": quote_count, "rfq_count": len(open_rfqs)}


def _zero_savings():
	return {"amount": 0, "avg_discount_pct": 0.0, "currency": DEFAULT_CURRENCY}


def _negotiation_savings(user):
	rfqs = frappe.get_list("RFQ", filters={"buyer": user}, fields=["name", "quantity"], page_length=5000)  # tasarruf toplaması — pratik üst sınır
	qty_by_rfq = {r.name: flt(r.quantity) for r in rfqs}
	if not qty_by_rfq:
		return _zero_savings()

	# RFQ Quote satıcıya ait; buyer'ın RFQ'larıyla scoped → get_all (gerekçe: buyer'da quote list perm olmayabilir).
	quotes = frappe.get_all(
		"RFQ Quote",
		filters={"rfq": ["in", list(qty_by_rfq)], "status": "Accepted"},
		fields=["rfq", "listing", "total_price"],
	)
	if not quotes:
		return _zero_savings()

	# Referans birim fiyatları tek sorguda (N+1 yerine batch). get_all: kategori/fiyat toplaması için
	# listing görünürlük perm'i uygulanmamalı (silinmiş/pasif listing de referans sağlayabilir).
	listing_ids = list({q.listing for q in quotes if q.listing})
	price_by_listing = (
		{
			r.name: flt(r.selling_price)
			for r in frappe.get_all(
				"Listing", filters={"name": ["in", listing_ids]}, fields=["name", "selling_price"]
			)
		}
		if listing_ids
		else {}
	)

	savings = 0.0
	reference = 0.0
	for q in quotes:
		unit = price_by_listing.get(q.listing, 0.0)
		ref = unit * qty_by_rfq.get(q.rfq, 0)
		if ref <= 0:
			continue
		reference += ref
		savings += max(0.0, ref - flt(q.total_price))

	avg_pct = round(savings / reference * 100, 1) if reference else 0.0
	return {"amount": round(savings), "avg_discount_pct": avg_pct, "currency": DEFAULT_CURRENCY}


def _spending_trend(user):
	today = getdate(nowdate())
	window_start = get_first_day(add_months(today, -(TREND_MONTHS - 1)))
	next_start = get_first_day(add_months(today, 1))

	rows = frappe.get_list(
		"Order",
		filters=[
			["buyer", "=", user],
			["status", "in", SPEND_STATUSES],
			["order_date", ">=", window_start],
			["order_date", "<", next_start],
		],
		fields=["order_date", "total"],
		page_length=5000,  # 6 aylık trend toplaması — pratik üst sınır
	)

	# (yıl, ay) → [harcama, sipariş adedi]
	buckets = {}
	for r in rows:
		d = getdate(r.order_date)
		b = buckets.setdefault((d.year, d.month), [0.0, 0])
		b[0] += flt(r.total)
		b[1] += 1

	labels, spend, orders = [], [], []
	for i in range(TREND_MONTHS - 1, -1, -1):
		m = get_first_day(add_months(today, -i))
		b = buckets.get((m.year, m.month), [0.0, 0])
		labels.append(_TR_MONTHS[m.month - 1])
		spend.append(round(b[0]))
		orders.append(b[1])
	return {"labels": labels, "spend": spend, "orders": orders}


def _to_percentages(buckets, grand):
	"""(name, amount) listesini largest-remainder ile tam 100'e toplanan yüzdelere çevirir."""
	if not buckets or grand <= 0:
		return []
	raw = [(name, amt / grand * 100) for name, amt in buckets]
	values = [int(p) for _, p in raw]
	remainder = round(sum(p for _, p in raw)) - sum(values)  # ≈ 100 - floor toplamı
	# Kesirli kısmı en büyük dilimlere +1 dağıt (toplam tam 100 olsun).
	order = sorted(range(len(raw)), key=lambda i: raw[i][1] - int(raw[i][1]), reverse=True)
	for k in range(max(0, remainder)):
		values[order[k % len(order)]] += 1
	return [{"name": raw[i][0], "value": values[i]} for i in range(len(raw))]


def _category_breakdown(user):
	today = getdate(nowdate())
	window_start = get_first_day(add_months(today, -(TREND_MONTHS - 1)))

	order_names = frappe.get_list(
		"Order",
		filters=[
			["buyer", "=", user],
			["status", "in", SPEND_STATUSES],
			["order_date", ">=", window_start],
		],
		pluck="name",
		page_length=1000,  # buyer'a ait sınırlı dataset — güvenlik tavanı
	)
	if not order_names:
		return []

	# Order Item child tablosu; parent buyer'ın siparişleri → get_all (child, parent ile scoped).
	items = frappe.get_all(
		"Order Item",
		filters={"parent": ["in", order_names]},
		fields=["listing", "total_price"],
	)
	listing_ids = list({it.listing for it in items if it.listing})
	if not listing_ids:
		return []

	# Listing → kategori, tek sorguda (N+1 yerine batch). get_all: kategori toplaması için görünürlük perm'siz.
	cat_by_listing = {
		r.name: r.category
		for r in frappe.get_all("Listing", filters={"name": ["in", listing_ids]}, fields=["name", "category"])
	}

	# Tüm kategori ağacını tek sorguda belleğe al (referans verisi); kökü bellekte yürü.
	cat_rows = frappe.get_all("Product Category", fields=["name", "parent_product_category", "category_name"])
	parent_of = {c.name: c.parent_product_category for c in cat_rows}
	label_of = {c.name: (c.category_name or c.name) for c in cat_rows}

	def root_label(cat):
		seen = set()
		current = cat
		while parent_of.get(current) and current not in seen:
			seen.add(current)
			current = parent_of[current]
		return label_of.get(current, current)

	totals = {}
	for it in items:
		cat = cat_by_listing.get(it.listing)
		if not cat:
			continue
		label = root_label(cat)
		totals[label] = totals.get(label, 0.0) + flt(it.total_price)

	grand = sum(totals.values())
	if grand <= 0:
		return []

	ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
	buckets = ranked[:TOP_CATEGORIES]
	other = sum(amt for _, amt in ranked[TOP_CATEGORIES:])
	if other > 0:
		buckets.append(("Diğer", other))

	return _to_percentages(buckets, grand)

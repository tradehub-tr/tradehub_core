# Copyright (c) 2026, TR TradeHub and contributors
"""Saha pazarlama hakediş üretimi — CRM Deal 'Won' olunca otomatik Field Commission.

Faz 1: Deal kazanıldığında tek seferlik (period_index=1) Beklemede kayıt üretir.
Tekrarlayan/süreli modlar Faz 2'de store_subscription yenilemelerine bağlanır.
"""

import frappe
from frappe.utils import flt, now_datetime


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


def _period_key(dt=None) -> str:
	"""Kota dönem anahtarı. quota_period ayarına göre: Aylık 'YYYY-MM',
	Çeyrek 'YYYY-Qn', Yıllık 'YYYY'."""
	dt = dt or now_datetime()
	period = frappe.db.get_single_value("Field Commission Settings", "quota_period") or "Aylık"
	if period == "Yıllık":
		return f"{dt.year}"
	if period == "Çeyrek":
		return f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"
	return f"{dt.year}-{dt.month:02d}"


def _quota_bonus_for_count(count: int, plan: str) -> float:
	"""Paketin quota_tiers'ında min_sales <= count olan EN YÜKSEK eşiğin bonus_amount'ı (yoksa 0)."""
	if not plan:
		return 0.0
	tiers = frappe.get_all(
		"Field Commission Quota Tier",
		filters={"parenttype": "Subscription Plan", "parent": plan},
		fields=["min_sales", "bonus_amount"],
	)
	best_amount = 0.0
	best_min = -1
	for t in tiers:
		ms = int(t.min_sales or 0)
		if ms <= count and ms > best_min:
			best_min = ms
			best_amount = flt(t.bonus_amount)
	return best_amount


def _active_team_for_agent(agent: str) -> dict | None:
	"""Saha elemanının üyesi olduğu AKTİF Satış Ekibi (name+leader) ya da None.

	Üye birden çok ekipte görünebilir (pasif arşiv); yalnız is_active olan döner.
	Batch fetch — N+1 yok (anti-pattern #6).
	"""
	member_rows = frappe.get_all("Sales Team Member", filters={"agent": agent}, fields=["parent"])
	if not member_rows:
		return None
	teams = frappe.get_all(
		"Sales Team",
		filters={"name": ["in", [r.parent for r in member_rows]], "is_active": 1},
		fields=["name", "leader"],
		limit=1,
	)
	return teams[0] if teams else None


def _initial_routing(agent: str) -> dict:
	"""Üretim anında başlangıç onay rotası.

	Aktif ekip + lider var ve eleman lider DEĞİL → 'Lider Onayı Bekliyor'.
	Aksi halde (ekipsiz veya liderin kendi kaydı) → 'Süperadmin Onayı Bekliyor'.
	team/team_leader her durumda snapshot'lanır (varsa).
	"""
	team = _active_team_for_agent(agent)
	if team and team.get("leader") and team.get("leader") != agent:
		return {"team": team["name"], "team_leader": team["leader"], "status": "Lider Onayı Bekliyor"}
	return {
		"team": team["name"] if team else None,
		"team_leader": team["leader"] if team else None,
		"status": "Süperadmin Onayı Bekliyor",
	}


def _resolve_commission(deal, plan_doc) -> dict | None:
	"""Komisyonu çöz. Komisyon yalnızca paket ayarından gelir (Yüzde/Sabit Ücret).

	Plan'da anlamlı ayar yoksa (oran/sabit 0/boş) None döner (hakediş üretilmez).
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
	fc.kind = "Satış"
	fc.period_key = _period_key()
	fc.period_index = 1
	routing = _initial_routing(agent)
	fc.team = routing["team"]
	fc.team_leader = routing["team_leader"]
	fc.status = routing["status"]
	fc.commission_type = resolved["commission_type"]
	fc.base_amount = resolved["base_amount"]
	fc.commission_rate = resolved["commission_rate"]
	fc.commission_amount = resolved["commission_amount"]
	fc.insert(ignore_permissions=True)


def recompute_quota_bonus(agent: str, period_key: str, plan: str) -> None:
	"""Ajanın dönemde O PAKETTEKİ onaylanmış Satış/Pay sayısına göre Bonus üret/güncelle.

	Kota paket-bazı: sayım ve eşik tablosu plan'a özgüdür.
	Sayıma giren: status ∈ {Onaylandı, Ödendi}, kind ∈ {Satış, Pay}, plan == plan.
	Idempotent: (agent, period_key, plan, kind=Bonus) tek kayıt. Bonus pending ise tutar
	güncellenir; Onaylandı/Ödendi ise dokunulmaz (ödenmiş paraya müdahale yok).
	"""
	if not agent or not period_key or not plan:
		return
	count = frappe.db.count(
		"Field Commission",
		{
			"agent": agent,
			"period_key": period_key,
			"plan": plan,
			"kind": ["in", ["Satış", "Pay"]],
			"status": ["in", ["Onaylandı", "Ödendi"]],
		},
	)
	bonus_amount = _quota_bonus_for_count(count, plan)
	if bonus_amount <= 0:
		return
	existing = frappe.db.get_value(
		"Field Commission",
		{"agent": agent, "period_key": period_key, "plan": plan, "kind": "Bonus"},
		["name", "status", "commission_amount"],
		as_dict=True,
	)
	if existing:
		if existing.status in ("Onaylandı", "Ödendi"):
			return
		if flt(existing.commission_amount) != bonus_amount:
			frappe.db.set_value("Field Commission", existing.name, "commission_amount", bonus_amount)
		return

	routing = _initial_routing(agent)
	fc = frappe.new_doc("Field Commission")
	fc.agent = agent
	fc.plan = plan
	fc.kind = "Bonus"
	fc.period_key = period_key
	fc.commission_type = "Sabit Ücret"
	fc.base_amount = 0
	fc.commission_rate = 0
	fc.commission_amount = bonus_amount
	fc.period_index = 1
	fc.team = routing["team"]
	fc.team_leader = routing["team_leader"]
	fc.status = routing["status"]
	fc.insert(ignore_permissions=True)


def process_quota_bonuses():
	"""Günlük scheduler: cari dönemde onaylanmış Satış/Pay'i olan (agent, plan) çiftleri
	için bonus yeniden hesapla (on-approval tetiklemesinin güvenlik ağı)."""
	period_key = _period_key()
	rows = frappe.get_all(
		"Field Commission",
		filters={
			"period_key": period_key,
			"kind": ["in", ["Satış", "Pay"]],
			"status": ["in", ["Onaylandı", "Ödendi"]],
		},
		fields=["agent", "plan"],
		distinct=True,
	)
	for r in rows:
		recompute_quota_bonus(r.agent, period_key, r.plan)

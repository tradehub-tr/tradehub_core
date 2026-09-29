"""13.6 Deney yönetimi — kontrol kümeleri ve mevsimsellik.

`SEO Experiment`: deney (treatment) ve kontrol route kümeleri, metrik, tarih aralığı.
`evaluate()`: iki kümenin günlük metrik serilerini (SEO Metric Snapshot, `dimension=route`) toplar,
deney öncesi aynı uzunluktaki dönemi "prior" alır → fark-farkı (DiD); mevsimsellik `weekday`
(haftanın günü eşleme) ya da `yoy` ile normalize edilir; veri yoksa `insufficient`/`missing` döner.
Route bazlı seriyi 13.6 atıf toplulaştırması (`rollup_routes`) üretir: organik dönüşümler route'a göre.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import frappe
from frappe.utils import add_days, getdate, now_datetime, nowdate

from tradehub_core.seo_helper import board_math
from tradehub_core.seo_helper.board import series, write_snapshot
from tradehub_core.seo_helper.experiments.attribution import CONVERSION_DOCTYPES


def _routes(v) -> list[str]:
	if not v:
		return []
	try:
		lst = json.loads(v) if isinstance(v, str) else list(v)
	except ValueError:
		lst = [x.strip() for x in str(v).split(",")]
	return ["/" + str(r).strip().strip("/") for r in lst if str(r).strip()]


def create(
	experiment_key: str,
	*,
	title: str,
	treatment_routes: list[str],
	control_routes: list[str],
	start_date: str | date,
	end_date: str | date,
	metric: str = "organic_conversions",
	hypothesis: str = "",
	seasonality: str = "weekday",
) -> str:
	if not treatment_routes or not control_routes:
		frappe.throw("Deney ve kontrol kümeleri boş olamaz", frappe.ValidationError)
	if set(_routes(treatment_routes)) & set(_routes(control_routes)):
		frappe.throw("Aynı route hem deney hem kontrol olamaz", frappe.ValidationError)
	if getdate(end_date) < getdate(start_date):
		frappe.throw("Bitiş başlangıçtan önce olamaz", frappe.ValidationError)
	d = frappe.get_doc(
		{
			"doctype": "SEO Experiment",
			"experiment_key": experiment_key,
			"title": title,
			"hypothesis": hypothesis,
			"metric": metric,
			"treatment_routes": json.dumps(_routes(treatment_routes)),
			"control_routes": json.dumps(_routes(control_routes)),
			"start_date": getdate(start_date),
			"end_date": getdate(end_date),
			"status": "running",
			"seasonality": seasonality,
		}
	).insert(ignore_permissions=True)
	from tradehub_core.seo_helper.experiments.changelog import log_change

	log_change(
		change_type="experiment",
		scope_type="site",
		scope_key=d.name,
		description=f"Deney başladı: {title}",
		source="auto",
		experiment=d.name,
	)
	return d.name


def rollup_routes(day: date | None = None) -> dict:
	"""Günün organik dönüşümlerini route bazında yaz (deney/kontrol serileri için)."""
	gun = getdate(day or add_days(nowdate(), -1))
	toplam: dict[str, float] = {}
	for dt in CONVERSION_DOCTYPES:
		if not frappe.db.exists("DocType", dt) or not frappe.get_meta(dt).has_field("seo_is_organic"):
			continue
		for r in frappe.get_all(
			dt,
			filters={"creation": ["between", [f"{gun} 00:00:00", f"{gun} 23:59:59"]], "seo_is_organic": 1},
			fields=["seo_landing_path"],
			limit_page_length=100000,
		):
			p = r.seo_landing_path or "/"
			toplam[p] = toplam.get(p, 0.0) + 1
	for p, v in toplam.items():
		write_snapshot(gun, "analytics", "route", p, "organic_conversions", v)
	return {"day": gun.isoformat(), "routes": len(toplam)}


def _group_series(routes: list[str], metric: str, start: date, end: date) -> dict[date, float]:
	out: dict[date, float] = {}
	for r in routes:
		s = series(
			metric,
			source="analytics",
			dimension="route",
			dimension_key=r,
			days=(getdate(nowdate()) - start).days + 1,
		)
		for g, v in s.items():
			if start <= g <= end:
				out[g] = out.get(g, 0.0) + v
	return out


def evaluate(experiment: str) -> dict:
	d = frappe.get_doc("SEO Experiment", experiment)
	t_r, c_r = _routes(d.treatment_routes), _routes(d.control_routes)
	start, end = getdate(d.start_date), min(getdate(d.end_date), getdate(nowdate()))
	uzunluk = (end - start).days + 1
	if uzunluk <= 0:
		frappe.throw("Deney henüz başlamadı", frappe.ValidationError)
	onceki_bas, onceki_bit = start - timedelta(days=uzunluk), start - timedelta(days=1)
	t = _group_series(t_r, d.metric, start, end)
	c = _group_series(c_r, d.metric, start, end)
	pt = _group_series(t_r, d.metric, onceki_bas, onceki_bit)
	pc = _group_series(c_r, d.metric, onceki_bas, onceki_bit)
	gunler = [start + timedelta(days=i) for i in range(uzunluk)]
	onceki_gunler = [onceki_bas + timedelta(days=i) for i in range(uzunluk)]

	def seri(m: dict[date, float], gs: list[date]) -> list[float]:
		return [m.get(g, 0.0) for g in gs]

	karsilastirma = board_math.compare_groups(
		seri(t, gunler),
		seri(c, gunler),
		prior_treatment=seri(pt, onceki_gunler) if pt else None,
		prior_control=seri(pc, onceki_gunler) if pc else None,
	)
	mevsim = {}
	if d.seasonality and d.seasonality != "none":
		tum_t = {**pt, **t}
		tum_c = {**pc, **c}
		for ad, m in (("treatment", tum_t), ("control", tum_c)):
			oranlar = []
			eksik = 0
			for g in gunler:
				sa = board_math.seasonal_adjust(m, g, d.seasonality)
				if sa["missing"] or sa["ratio"] is None:
					eksik += 1
				else:
					oranlar.append(sa["ratio"])
			mevsim[ad] = {
				"ratio_mean": round(sum(oranlar) / len(oranlar), 3) if oranlar else None,
				"days_missing": eksik,
			}
	eksik_gunler = board_math.missing_days(start, end, set(t) | set(c))
	sonuc = {
		"experiment": d.name,
		"metric": d.metric,
		"period": {"start": start.isoformat(), "end": end.isoformat(), "days": uzunluk},
		"prior_period": {"start": onceki_bas.isoformat(), "end": onceki_bit.isoformat()},
		"treatment_routes": t_r,
		"control_routes": c_r,
		**karsilastirma,
		"seasonality": {"method": d.seasonality, **mevsim},
		"missing_days": [g.isoformat() for g in eksik_gunler],
		"data_quality": "insufficient"
		if karsilastirma["insufficient"] or len(eksik_gunler) > uzunluk / 2
		else "ok",
	}
	d.db_set(
		{
			"result": json.dumps(sonuc, ensure_ascii=False, default=str),
			"evaluated_at": now_datetime(),
			"status": "evaluated" if end >= getdate(d.end_date) else d.status,
		},
		update_modified=True,
	)
	return sonuc


def list_experiments(limit: int = 100) -> list[dict]:
	rows = frappe.get_all(
		"SEO Experiment",
		fields=[
			"name",
			"title",
			"metric",
			"start_date",
			"end_date",
			"status",
			"seasonality",
			"result",
			"evaluated_at",
			"treatment_routes",
			"control_routes",
			"hypothesis",
		],
		order_by="creation desc",
		limit_page_length=limit,
	)
	for r in rows:
		for k in ("result", "treatment_routes", "control_routes"):
			try:
				r[k] = json.loads(r[k]) if isinstance(r[k], str) and r[k] else (r[k] or None)
			except ValueError:
				pass
	return rows

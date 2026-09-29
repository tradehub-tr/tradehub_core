"""13.3 / 13.6 — saf sayısal yardımcılar: anomali, taban çizgisi, mevsimsellik, deney karşılaştırması."""

from __future__ import annotations

import statistics
from datetime import date, timedelta


def baseline(series: list[float]) -> dict:
	"""Ortalama/standart sapma (n<2 ise sd=0)."""
	if not series:
		return {"mean": 0.0, "sd": 0.0, "n": 0}
	m = statistics.fmean(series)
	sd = statistics.pstdev(series) if len(series) > 1 else 0.0
	return {"mean": m, "sd": sd, "n": len(series)}


def detect_anomaly(
	current: float,
	history: list[float],
	*,
	pct_threshold: float = 30.0,
	z_threshold: float = 3.0,
	min_history: int = 3,
) -> dict:
	"""Bugünkü değeri geçmişle karşılaştır: yüzde sapma VE z-skoru; ikisinden biri eşiği aşarsa anomali.
	Tarih yetersizse `insufficient_history` — sessiz 'normal' DEĞİL."""
	b = baseline(history)
	if b["n"] < min_history:
		return {
			"anomaly": False,
			"reason": "insufficient_history",
			"mean": b["mean"],
			"current": current,
			"pct": None,
			"z": None,
		}
	pct = ((current - b["mean"]) / b["mean"] * 100.0) if b["mean"] else (100.0 if current else 0.0)
	z = ((current - b["mean"]) / b["sd"]) if b["sd"] else (0.0 if current == b["mean"] else float("inf"))
	anomali = abs(pct) >= pct_threshold and (b["sd"] == 0 or abs(z) >= z_threshold or b["n"] < 7)
	yon = "up" if current > b["mean"] else "down" if current < b["mean"] else "flat"
	return {
		"anomaly": bool(anomali),
		"reason": yon if anomali else "normal",
		"mean": round(b["mean"], 3),
		"sd": round(b["sd"], 3),
		"current": current,
		"pct": round(pct, 1),
		"z": (round(z, 2) if z != float("inf") else None),
		"direction": yon,
	}


def weekday_baseline(values_by_day: dict[date, float], day: date, weeks: int = 4) -> float | None:
	"""Aynı haftanın gününün önceki N haftadaki ortalaması (mevsimsellik: haftalık döngü)."""
	xs = [
		values_by_day[d] for w in range(1, weeks + 1) if (d := day - timedelta(days=7 * w)) in values_by_day
	]
	return statistics.fmean(xs) if xs else None


def yoy_baseline(values_by_day: dict[date, float], day: date) -> float | None:
	"""Bir yıl önceki aynı gün (±3 gün ortalaması) — yıllık mevsimsellik."""
	try:
		gecen = day.replace(year=day.year - 1)
	except ValueError:  # 29 Şubat
		gecen = day - timedelta(days=365)
	xs = [values_by_day[d] for k in range(-3, 4) if (d := gecen + timedelta(days=k)) in values_by_day]
	return statistics.fmean(xs) if xs else None


def seasonal_adjust(values_by_day: dict[date, float], day: date, method: str = "weekday") -> dict:
	"""Değeri mevsimsel taban çizgisine göre normalize et (oran); taban yoksa `missing`."""
	v = values_by_day.get(day)
	taban = (
		weekday_baseline(values_by_day, day)
		if method == "weekday"
		else yoy_baseline(values_by_day, day)
		if method == "yoy"
		else None
	)
	if v is None or taban is None or method == "none":
		return {
			"value": v,
			"baseline": taban,
			"ratio": None,
			"missing": v is None or (method != "none" and taban is None),
		}
	return {"value": v, "baseline": taban, "ratio": (v / taban) if taban else None, "missing": False}


def compare_groups(
	treatment: list[float],
	control: list[float],
	*,
	prior_treatment: list[float] | None = None,
	prior_control: list[float] | None = None,
) -> dict:
	"""Deney vs kontrol: fark-farkı (difference-in-differences) varsa, yoksa düz fark. Yüzde 'lift'."""
	t, c = (
		(statistics.fmean(treatment) if treatment else 0.0),
		(statistics.fmean(control) if control else 0.0),
	)
	out = {"treatment_mean": t, "control_mean": c, "n_treatment": len(treatment), "n_control": len(control)}
	if prior_treatment and prior_control:
		pt, pc = statistics.fmean(prior_treatment), statistics.fmean(prior_control)
		out.update(
			{
				"prior_treatment_mean": pt,
				"prior_control_mean": pc,
				"did": (t - pt) - (c - pc),
				"method": "did",
			}
		)
		out["lift_pct"] = round(((t - pt) - (c - pc)) / pt * 100.0, 1) if pt else None
	else:
		out.update({"method": "diff", "lift_pct": round((t - c) / c * 100.0, 1) if c else None})
	out["insufficient"] = len(treatment) < 3 or len(control) < 3
	return out


def missing_days(start: date, end: date, present: set[date]) -> list[date]:
	"""[start, end] aralığında verisi olmayan günler."""
	out, d = [], start
	while d <= end:
		if d not in present:
			out.append(d)
		d += timedelta(days=1)
	return out

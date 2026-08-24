"""T-066 — gerçek RUM örneklerinden aylık görsel LCP etkisini ölç.

Ham URL ya da tekil kullanıcı kimliği bu katmana gelmez. ``Media RUM Sample``
satırlarının yalnız kaba rota/cihaz/ağ kovaları ve ``lcp_profile`` etiketi
kullanılır. Aynı kovadaki ``original`` ile ``w*`` örnekleri karşılaştırılır;
pozitif sonuç optimize türevin LCP'yi hızlandırdığı milisaniye miktarıdır.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

_OPTIMIZED_PROFILE = re.compile(r"^w\d{2,4}$")
_BASELINE_PROFILE = "original"

# Rota ve bölge birlikte hangi görsel yerleşiminin ölçüldüğünü; kalan alanlar
# ise ağ/ekran koşullarını sabitler. Farklı koşulları tek ortalamada
# karşılaştırmak Simpson paradoksuna açık olurdu.
_COHORT_FIELDS: tuple[str, ...] = (
	"route",
	"lcp_region",
	"device_class",
	"viewport_bucket",
	"dpr",
	"connection",
	"navigation_type",
	"engine_version",
)


class LcpImpactError(ValueError):
	"""Kalıcı RUM satırı güvenilir bir ölçüme dönüştürülemedi."""


@dataclass(frozen=True)
class LcpImpactMeasurement:
	"""Aylık karşılaştırmanın denetlenebilir özeti."""

	average_impact_ms: float | None
	comparable_cohorts: int
	baseline_samples: int
	optimized_samples: int
	comparable_samples: int
	estimated_comparable_population: float
	direction: str = "positive_is_faster"

	def as_dict(self) -> dict[str, Any]:
		return asdict(self)


@dataclass(frozen=True)
class _WeightedValue:
	value: float
	weight: float


def monthly_lcp_filters(period_start: date, period_end: date) -> list[list[Any]]:
	"""Önceki ay RUM sorgusunun yarı-açık zaman aralığını üret."""
	next_day = period_end + timedelta(days=1)
	return [
		["metric", "=", "LCP"],
		["creation", ">=", f"{period_start.isoformat()} 00:00:00"],
		["creation", "<", f"{next_day.isoformat()} 00:00:00"],
	]


def _number(row: Mapping[str, Any], field: str, *, positive: bool = False) -> float:
	try:
		value = float(row.get(field))
	except (TypeError, ValueError) as exc:
		raise LcpImpactError(f"gecersiz {field}: {row.get(field)!r}") from exc
	if not math.isfinite(value) or (positive and value <= 0):
		raise LcpImpactError(f"gecersiz {field}: {row.get(field)!r}")
	return value


def _profile_kind(profile: Any) -> str | None:
	text = str(profile or "").strip().lower()
	if text == _BASELINE_PROFILE:
		return "baseline"
	if _OPTIMIZED_PROFILE.fullmatch(text):
		return "optimized"
	# ``unknown`` şemada bilerek geçerli: ölçümü kaybetmez ama karşılaştırmaya
	# kanıtsız biçimde original/optimized diye sokulmaz.
	return None


def _cohort(row: Mapping[str, Any]) -> tuple[str, ...]:
	return tuple(str(row.get(field) if row.get(field) is not None else "") for field in _COHORT_FIELDS)


def _weighted_mean(values: Sequence[_WeightedValue]) -> tuple[float, float]:
	population = sum(item.weight for item in values)
	if population <= 0:
		raise LcpImpactError("LCP örneklem ağırlığı sıfır olamaz")
	return sum(item.value * item.weight for item in values) / population, population


def measure_lcp_impact(rows: Sequence[Mapping[str, Any]]) -> LcpImpactMeasurement:
	"""Eşleşen RUM kohortlarında original − optimized LCP farkını hesapla.

	Her satır ``1 / sample_rate`` ile popülasyona genellenir. Kohort farkları,
	iki kolun tahmini popülasyonundan küçük olanla ağırlıklandırılır; böylece
	tek tarafta çok trafik bulunan bir kova sonucu tek başına sürükleyemez.
	"""
	groups: dict[tuple[str, ...], dict[str, list[_WeightedValue]]] = defaultdict(
		lambda: {"baseline": [], "optimized": []}
	)
	baseline_samples = 0
	optimized_samples = 0

	for row in rows:
		if str(row.get("metric") or "LCP").upper() != "LCP":
			continue
		kind = _profile_kind(row.get("lcp_profile"))
		if kind is None:
			continue
		value = _number(row, "value")
		if value < 0:
			raise LcpImpactError(f"gecersiz value: {value!r}")
		rate = _number(row, "sample_rate", positive=True)
		if rate > 1:
			raise LcpImpactError(f"gecersiz sample_rate: {rate!r}")
		groups[_cohort(row)][kind].append(_WeightedValue(value=value, weight=1.0 / rate))
		if kind == "baseline":
			baseline_samples += 1
		else:
			optimized_samples += 1

	weighted_deltas: list[tuple[float, float]] = []
	comparable_samples = 0
	for group in groups.values():
		baseline = group["baseline"]
		optimized = group["optimized"]
		if not baseline or not optimized:
			continue
		baseline_mean, baseline_population = _weighted_mean(baseline)
		optimized_mean, optimized_population = _weighted_mean(optimized)
		comparison_population = min(baseline_population, optimized_population)
		weighted_deltas.append((baseline_mean - optimized_mean, comparison_population))
		comparable_samples += len(baseline) + len(optimized)

	population = sum(weight for _delta, weight in weighted_deltas)
	average = None
	if population:
		average = round(
			sum(delta * weight for delta, weight in weighted_deltas) / population,
			3,
		)

	return LcpImpactMeasurement(
		average_impact_ms=average,
		comparable_cohorts=len(weighted_deltas),
		baseline_samples=baseline_samples,
		optimized_samples=optimized_samples,
		comparable_samples=comparable_samples,
		estimated_comparable_population=round(population, 3),
	)


__all__ = [
	"LcpImpactError",
	"LcpImpactMeasurement",
	"measure_lcp_impact",
	"monthly_lcp_filters",
]

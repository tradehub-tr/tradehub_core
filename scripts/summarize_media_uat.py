#!/usr/bin/env python3
"""MOGEM-617 / T-142 satıcı pilotu CSV'sini doğrula ve özetle.

Bu araç ürün telemetrisi toplamaz. Açık rızalı, moderatörlü UAT oturumlarında
yalnız takma katılımcı kodlarıyla doldurulan iki CSV'yi çevrimdışı işler.

Kullanım:

    python3 scripts/summarize_media_uat.py sessions.csv findings.csv
    python3 scripts/summarize_media_uat.py sessions.csv findings.csv --json
    python3 scripts/summarize_media_uat.py sessions.csv findings.csv --check-gate

``--check-gate`` T-142 saha kapılarının tümü geçmediyse 1, veri sözleşmesi
bozuksa 2 ile çıkar. Araç bir üretim rollout'u veya nihai kabul imzası vermez.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

TASKS = ("G1", "G2", "G3", "G4", "G5", "G6")
SESSION_COLUMNS = (
	"participant_code",
	"real_seller",
	"consent_recorded",
	"product_count",
	"task_id",
	"started_at",
	"finished_at",
	"completed",
	"help_count",
	"rejection_score",
	"evidence_ref",
	"confusion_note",
)
FINDING_COLUMNS = (
	"finding_id",
	"severity",
	"status",
	"owner_code",
	"due_date",
	"evidence_ref",
	"summary",
)
SEVERITIES = frozenset({"critical", "high", "medium", "low"})
FINDING_STATUSES = frozenset({"open", "closed"})
PARTICIPANT_RE = re.compile(r"S\d{2,3}\Z")


class ContractError(ValueError):
	"""CSV sözleşmesi bozuk; rapor üretmek güvenli değil."""


@dataclass(frozen=True)
class SessionRow:
	participant_code: str
	real_seller: bool
	consent_recorded: bool
	product_count: int
	task_id: str
	started_at: datetime
	finished_at: datetime
	completed: bool
	help_count: int
	rejection_score: float | None
	evidence_ref: str
	confusion_note: str

	@property
	def duration_seconds(self) -> float:
		return (self.finished_at - self.started_at).total_seconds()


@dataclass(frozen=True)
class Finding:
	finding_id: str
	severity: str
	status: str
	owner_code: str
	due_date: str
	evidence_ref: str
	summary: str


@dataclass(frozen=True)
class TaskMetric:
	task_id: str
	attempts: int
	completed: int
	completion_rate: float
	median_seconds: float
	help_count: int
	confusion_count: int


def _read_dicts(path: Path, expected: tuple[str, ...]) -> list[dict[str, str]]:
	try:
		with path.open(encoding="utf-8-sig", newline="") as handle:
			reader = csv.DictReader(handle)
			actual = tuple(reader.fieldnames or ())
			if actual != expected:
				raise ContractError(
					f"{path}: kolonlar birebir şu sırada olmalı: {', '.join(expected)}; "
					f"gelen: {', '.join(actual) or '<boş>'}"
				)
			return [{key: str(value or "").strip() for key, value in row.items()} for row in reader]
	except OSError as exc:
		raise ContractError(f"{path}: okunamadı: {exc}") from exc


def _bool(value: str, *, where: str) -> bool:
	if value not in {"0", "1"}:
		raise ContractError(f"{where}: 0 veya 1 olmalı")
	return value == "1"


def _nonnegative_int(value: str, *, where: str) -> int:
	try:
		parsed = int(value)
	except ValueError as exc:
		raise ContractError(f"{where}: tam sayı olmalı") from exc
	if parsed < 0:
		raise ContractError(f"{where}: negatif olamaz")
	return parsed


def _timestamp(value: str, *, where: str) -> datetime:
	try:
		parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
	except ValueError as exc:
		raise ContractError(f"{where}: ISO-8601 zaman damgası olmalı") from exc
	if parsed.tzinfo is None or parsed.utcoffset() is None:
		raise ContractError(f"{where}: saat dilimi zorunlu (+03:00 veya Z)")
	return parsed


def read_sessions(path: Path) -> list[SessionRow]:
	rows: list[SessionRow] = []
	seen: set[tuple[str, str]] = set()
	participant_facts: dict[str, tuple[bool, bool, int]] = {}
	for index, raw in enumerate(_read_dicts(path, SESSION_COLUMNS), start=2):
		where = f"{path}:{index}"
		code = raw["participant_code"].upper()
		if not PARTICIPANT_RE.fullmatch(code):
			raise ContractError(f"{where}: participant_code S01…S999 biçiminde olmalı; ad/e-posta yazmayın")
		task_id = raw["task_id"].upper()
		if task_id not in TASKS:
			raise ContractError(f"{where}: task_id {', '.join(TASKS)} değerlerinden biri olmalı")
		key = (code, task_id)
		if key in seen:
			raise ContractError(f"{where}: yinelenen katılımcı/görev: {code}/{task_id}")
		seen.add(key)

		real_seller = _bool(raw["real_seller"], where=f"{where} real_seller")
		consent = _bool(raw["consent_recorded"], where=f"{where} consent_recorded")
		product_count = _nonnegative_int(raw["product_count"], where=f"{where} product_count")
		facts = (real_seller, consent, product_count)
		if code in participant_facts and participant_facts[code] != facts:
			raise ContractError(f"{where}: {code} için seller/onam/ürün sayısı satırlar arasında değişiyor")
		participant_facts[code] = facts

		started = _timestamp(raw["started_at"], where=f"{where} started_at")
		finished = _timestamp(raw["finished_at"], where=f"{where} finished_at")
		if finished < started:
			raise ContractError(f"{where}: finished_at started_at'tan önce olamaz")
		completed = _bool(raw["completed"], where=f"{where} completed")
		help_count = _nonnegative_int(raw["help_count"], where=f"{where} help_count")
		if completed and not raw["evidence_ref"]:
			raise ContractError(f"{where}: tamamlanan görevde evidence_ref zorunlu")

		score: float | None = None
		if task_id == "G6":
			try:
				score = float(raw["rejection_score"])
			except ValueError as exc:
				raise ContractError(f"{where}: G6 rejection_score 0, 0.5 veya 1 olmalı") from exc
			if score not in {0.0, 0.5, 1.0}:
				raise ContractError(f"{where}: G6 rejection_score 0, 0.5 veya 1 olmalı")
		elif raw["rejection_score"]:
			raise ContractError(f"{where}: rejection_score yalnız G6 satırında yazılır")

		rows.append(
			SessionRow(
				participant_code=code,
				real_seller=real_seller,
				consent_recorded=consent,
				product_count=product_count,
				task_id=task_id,
				started_at=started,
				finished_at=finished,
				completed=completed,
				help_count=help_count,
				rejection_score=score,
				evidence_ref=raw["evidence_ref"],
				confusion_note=raw["confusion_note"],
			)
		)
	return rows


def read_findings(path: Path) -> list[Finding]:
	findings: list[Finding] = []
	seen: set[str] = set()
	for index, raw in enumerate(_read_dicts(path, FINDING_COLUMNS), start=2):
		where = f"{path}:{index}"
		finding_id = raw["finding_id"].upper()
		if not finding_id or finding_id in seen:
			raise ContractError(f"{where}: finding_id boş veya yinelenen")
		seen.add(finding_id)
		severity = raw["severity"].lower()
		status = raw["status"].lower()
		if severity not in SEVERITIES:
			raise ContractError(
				f"{where}: severity {', '.join(sorted(SEVERITIES))} değerlerinden biri olmalı"
			)
		if status not in FINDING_STATUSES:
			raise ContractError(f"{where}: status open veya closed olmalı")
		if not raw["owner_code"] or not raw["due_date"]:
			raise ContractError(f"{where}: owner_code ve due_date zorunlu")
		try:
			datetime.strptime(raw["due_date"], "%Y-%m-%d")
		except ValueError as exc:
			raise ContractError(f"{where}: due_date YYYY-MM-DD olmalı") from exc
		if status == "closed" and not raw["evidence_ref"]:
			raise ContractError(f"{where}: kapalı bulguda evidence_ref zorunlu")
		if not raw["summary"]:
			raise ContractError(f"{where}: summary zorunlu")
		findings.append(
			Finding(
				finding_id=finding_id,
				severity=severity,
				status=status,
				owner_code=raw["owner_code"],
				due_date=raw["due_date"],
				evidence_ref=raw["evidence_ref"],
				summary=raw["summary"],
			)
		)
	return findings


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
	"""İkili tam-anlama oranı için %95 Wilson aralığı."""
	if total <= 0:
		return (0.0, 0.0)
	p = successes / total
	denominator = 1 + (z * z / total)
	centre = p + (z * z / (2 * total))
	margin = z * math.sqrt((p * (1 - p) / total) + (z * z / (4 * total * total)))
	return ((centre - margin) / denominator, (centre + margin) / denominator)


def summarize(rows: Sequence[SessionRow], findings: Sequence[Finding]) -> dict[str, Any]:
	by_participant: dict[str, list[SessionRow]] = defaultdict(list)
	for row in rows:
		by_participant[row.participant_code].append(row)

	eligible_codes = sorted(
		code
		for code, participant_rows in by_participant.items()
		if participant_rows[0].real_seller
		and participant_rows[0].consent_recorded
		and {row.task_id for row in participant_rows} == set(TASKS)
	)
	eligible = [row for row in rows if row.participant_code in eligible_codes]
	by_task: dict[str, list[SessionRow]] = defaultdict(list)
	for row in eligible:
		by_task[row.task_id].append(row)

	task_metrics: list[TaskMetric] = []
	for task_id in TASKS:
		task_rows = by_task[task_id]
		completed = sum(row.completed for row in task_rows)
		task_metrics.append(
			TaskMetric(
				task_id=task_id,
				attempts=len(task_rows),
				completed=completed,
				completion_rate=(completed / len(task_rows)) if task_rows else 0.0,
				median_seconds=statistics.median(row.duration_seconds for row in task_rows)
				if task_rows
				else 0.0,
				help_count=sum(row.help_count for row in task_rows),
				confusion_count=sum(bool(row.confusion_note) for row in task_rows),
			)
		)

	g6 = by_task["G6"]
	full_understanding = sum(row.rejection_score == 1.0 for row in g6)
	zero_understanding = sum(row.rejection_score == 0.0 for row in g6)
	mean_score = sum(float(row.rejection_score or 0.0) for row in g6) / len(g6) if g6 else 0.0
	understanding_rate = full_understanding / len(g6) if g6 else 0.0
	wilson_low, wilson_high = wilson_interval(full_understanding, len(g6))
	all_g1_products = bool(eligible_codes) and all(
		participant_rows[0].product_count >= 5
		and any(row.task_id == "G1" and row.completed for row in participant_rows)
		for code, participant_rows in by_participant.items()
		if code in eligible_codes
	)
	critical_open = [
		finding.finding_id
		for finding in findings
		if finding.severity == "critical" and finding.status != "closed"
	]

	gates = {
		"at_least_10_real_consented_sellers": len(eligible_codes) >= 10,
		"each_seller_at_least_5_products": all_g1_products,
		"understanding_rate_at_least_90_percent": understanding_rate >= 0.9,
		"no_zero_understanding_score": bool(g6) and zero_understanding == 0,
		"critical_findings_closed": not critical_open,
	}
	return {
		"participant_count": len(eligible_codes),
		"participant_codes": eligible_codes,
		"task_metrics": [asdict(metric) for metric in task_metrics],
		"understanding": {
			"full_count": full_understanding,
			"total": len(g6),
			"rate": understanding_rate,
			"mean_score": mean_score,
			"zero_count": zero_understanding,
			"wilson_95_low": wilson_low,
			"wilson_95_high": wilson_high,
		},
		"findings": {
			"total": len(findings),
			"critical_open": critical_open,
			"open_total": sum(finding.status == "open" for finding in findings),
		},
		"gates": gates,
		"passed": all(gates.values()),
	}


def render_markdown(summary: dict[str, Any]) -> str:
	lines = [
		"# MOGEM-617 / T-142 UAT özeti",
		"",
		f"Gerçek + açık rızalı + G1…G6 kaydı tam satıcı: **{summary['participant_count']}**",
		"",
		"| Görev | Deneme | Tamamlandı | Oran | Medyan süre | Yardım | Karışıklık notu |",
		"|---|---:|---:|---:|---:|---:|---:|",
	]
	for metric in summary["task_metrics"]:
		lines.append(
			f"| {metric['task_id']} | {metric['attempts']} | {metric['completed']} | "
			f"{metric['completion_rate']:.1%} | {metric['median_seconds']:.1f} sn | "
			f"{metric['help_count']} | {metric['confusion_count']} |"
		)
	understanding = summary["understanding"]
	lines.extend(
		[
			"",
			"## Reddedilen yüklemeyi anlama",
			"",
			f"Tam doğru: **{understanding['full_count']}/{understanding['total']} "
			f"({understanding['rate']:.1%})** · Ortalama puan: **{understanding['mean_score']:.1%}** · "
			f"Wilson %95: **{understanding['wilson_95_low']:.1%}–{understanding['wilson_95_high']:.1%}** · "
			f"0 puan: **{understanding['zero_count']}**",
			"",
			"## Çıkış kapıları",
			"",
			"| Kapı | Sonuç |",
			"|---|---|",
		]
	)
	labels = {
		"at_least_10_real_consented_sellers": "≥10 gerçek ve açık rızalı satıcı",
		"each_seller_at_least_5_products": "Her satıcı ≥5 ürün + G1 tamam",
		"understanding_rate_at_least_90_percent": "Tam anlama oranı ≥%90",
		"no_zero_understanding_score": "0 puanlı katılımcı yok",
		"critical_findings_closed": "Kritik bulgular kapalı",
	}
	for key, passed in summary["gates"].items():
		lines.append(f"| {labels[key]} | {'GEÇTİ' if passed else 'KALDI'} |")
	lines.extend(["", f"**T-142 sonucu: {'GEÇTİ' if summary['passed'] else 'KALDI'}**", ""])
	return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("sessions", type=Path, help="media-uat-results.csv")
	parser.add_argument("findings", type=Path, help="media-uat-findings.csv")
	parser.add_argument("--json", action="store_true", help="Markdown yerine JSON bas")
	parser.add_argument("--check-gate", action="store_true", help="T-142 kapısı açıkken exit 1")
	return parser


def main(argv: Sequence[str] | None = None) -> int:
	args = _parser().parse_args(argv)
	try:
		summary = summarize(read_sessions(args.sessions), read_findings(args.findings))
	except ContractError as exc:
		print(f"UAT veri sözleşmesi hatası: {exc}", file=sys.stderr)
		return 2
	if args.json:
		print(json.dumps(summary, ensure_ascii=False, indent=2))
	else:
		print(render_markdown(summary))
	return 1 if args.check_gate and not summary["passed"] else 0


if __name__ == "__main__":
	raise SystemExit(main())

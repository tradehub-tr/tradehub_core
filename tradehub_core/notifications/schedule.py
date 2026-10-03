"""Zaman hesapları: özet saatleri ve sessiz saat. Saat dilimi / DST / gece yarısı güvenli.

Saf modül (frappe gerekmez); tüm `datetime` değerleri saat dilimi bilgilidir (aware).
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HHMM = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def valid_tz(name: str) -> bool:
	try:
		ZoneInfo(str(name))
		return bool(name)
	except (ZoneInfoNotFoundError, ValueError):
		return False


def parse_hhmm(value: str) -> time:
	h, m = value.split(":")
	return time(int(h), int(m))


def _local(now: datetime, tz: str) -> datetime:
	return now.astimezone(ZoneInfo(tz))


def _at(day: datetime, t: time, tz: str) -> datetime:
	"""Yerel günün t saatine denk gelen an. DST boşluğunda (yok olan saat) ileri kayar."""
	naive = datetime(day.year, day.month, day.day, t.hour, t.minute)
	aware = naive.replace(tzinfo=ZoneInfo(tz))
	# Var olmayan yerel saat → UTC'ye gidip dönünce değişir; o durumda dönüşü kullan.
	return aware.astimezone(ZoneInfo("UTC")).astimezone(ZoneInfo(tz))


def next_daily(now: datetime, at: str, tz: str) -> datetime:
	local = _local(now, tz)
	cand = _at(local, parse_hhmm(at), tz)
	if cand <= local:
		cand = _at(local + timedelta(days=1), parse_hhmm(at), tz)
	return cand


def next_weekly(now: datetime, at: str, weekday: str, tz: str) -> datetime:
	local = _local(now, tz)
	target = WEEKDAYS.index(weekday)
	for add in range(0, 8):
		day = local + timedelta(days=add)
		if day.weekday() != target:
			continue
		cand = _at(day, parse_hhmm(at), tz)
		if cand > local:
			return cand
	raise AssertionError("unreachable")


def in_quiet(now: datetime, start: str, end: str, tz: str) -> bool:
	"""Gece yarısını geçen aralık desteklenir (22:00–08:00)."""
	t = _local(now, tz).time()
	s, e = parse_hhmm(start), parse_hhmm(end)
	if s < e:
		return s <= t < e
	return t >= s or t < e


def quiet_end(now: datetime, start: str, end: str, tz: str) -> datetime:
	"""Sessiz aralık içindeyken aralığın biteceği an."""
	local = _local(now, tz)
	e = parse_hhmm(end)
	cand = _at(local, e, tz)
	if cand <= local:
		cand = _at(local + timedelta(days=1), e, tz)
	return cand


def period_key(kind: str, due: datetime, tz: str) -> str:
	local = _local(due, tz)
	if kind == "daily":
		return local.strftime("%Y-%m-%d")
	iso = local.isocalendar()
	return f"{iso[0]}-W{iso[1]:02d}"

"""Date normalizer — TR locale default DD.MM.YYYY."""

import re
from datetime import datetime

from tradehub_core.bulk_import.ingestion.normalizers import register_normalizer

DATE_PATTERNS = [
	("%d.%m.%Y", re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$")),
	("%d/%m/%Y", re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")),
	("%Y-%m-%d", re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")),
	("%Y/%m/%d", re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$")),
	("%d-%m-%Y", re.compile(r"^\d{1,2}-\d{1,2}-\d{4}$")),
]


def parse_date(value):
	"""Tarih string'i → datetime. TR locale öncelikli (DD.MM.YYYY)."""
	if value is None or value == "":
		return None
	if isinstance(value, datetime):
		return value
	s = str(value).strip()
	for fmt, pattern in DATE_PATTERNS:
		if pattern.match(s):
			try:
				return datetime.strptime(s, fmt)
			except ValueError:
				continue
	return None


register_normalizer("date", parse_date)

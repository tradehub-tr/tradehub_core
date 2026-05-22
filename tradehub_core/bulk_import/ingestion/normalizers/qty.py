"""Quantity normalizer — adet, k, milyon, vs."""

import re

from tradehub_core.bulk_import.ingestion.normalizers import register_normalizer

QTY_RE = re.compile(
	r"^(?P<num>[\d.,]+)\s*(?P<unit>k|m|adet|piece|pcs|tane)?",
	re.IGNORECASE,
)


def parse_qty(value):
	"""Adet/quantity değeri → int."""
	if value is None or value == "":
		return None
	if isinstance(value, int):
		return value
	if isinstance(value, float):
		return int(value)
	s = str(value).strip().lower()
	m = QTY_RE.match(s)
	if not m:
		return None
	num_str = m.group("num").replace(",", "").replace(".", "")
	try:
		num = int(num_str)
	except ValueError:
		# Decimal parse fallback (örn. "1.5k")
		try:
			num = int(float(m.group("num").replace(",", ".")))
		except ValueError:
			return None
	unit = (m.group("unit") or "").lower()
	if unit == "k":
		num *= 1000
	elif unit == "m":
		num *= 1_000_000
	return num


register_normalizer("qty", parse_qty)

"""Price normalizer — Türkçe + İngilizce format."""

import re

from tradehub_core.bulk_import.ingestion.normalizers import register_normalizer

# Patterns: "1.234,56 TL", "$1,234.56", "1234", "1234.56", "₺1.250,50"
PRICE_RE = re.compile(
	r"^\s*[^\d\-]*?(?P<sign>-?)(?P<digits>[\d.,\s]+?)\s*(?:TL|₺|\$|€|EUR|USD|TRY)?\s*$",
	re.IGNORECASE,
)


def parse_price(value):
	"""Türk/İngiliz fiyat formatı → float."""
	if value is None or value == "":
		return None
	if isinstance(value, (int, float)):
		return float(value)
	s = str(value).strip()
	m = PRICE_RE.match(s)
	if not m:
		# Last-resort: extract digits + last decimal sep
		return _fallback_parse(s)

	digits = m.group("digits").replace(" ", "")
	sign = m.group("sign")

	# Determine TR vs EN format:
	# TR: "1.234,56" (. binlik, , ondalık)
	# EN: "1,234.56" (, binlik, . ondalık)
	if "," in digits and "." in digits:
		# Last separator is the decimal one
		if digits.rfind(",") > digits.rfind("."):
			# TR format
			digits = digits.replace(".", "").replace(",", ".")
		else:
			# EN format
			digits = digits.replace(",", "")
	elif "," in digits:
		# Only comma → probably decimal (TR)
		parts = digits.split(",")
		if len(parts) == 2 and len(parts[1]) <= 2:
			# "1234,56" → 1234.56
			digits = digits.replace(",", ".")
		else:
			# "1,234" → likely thousands
			digits = digits.replace(",", "")
	elif "." in digits:
		# Only dot → ambiguous; assume decimal if last group <= 2 digits
		parts = digits.split(".")
		if len(parts) == 2 and len(parts[1]) <= 2:
			pass  # Keep as decimal
		else:
			# "1.234" → thousands
			digits = digits.replace(".", "")

	try:
		return float(f"{sign}{digits}")
	except (ValueError, TypeError):
		return None


def _fallback_parse(s: str):
	"""Hiç pattern eşleşmezse — sadece rakam ve tek ondalık ayırıcı çıkar."""
	digits_only = re.sub(r"[^\d.,\-]", "", s)
	if not digits_only:
		return None
	try:
		# Last sep = decimal
		last_dot = digits_only.rfind(".")
		last_comma = digits_only.rfind(",")
		if last_dot == -1 and last_comma == -1:
			return float(digits_only)
		if last_comma > last_dot:
			return float(digits_only.replace(".", "").replace(",", "."))
		return float(digits_only.replace(",", ""))
	except (ValueError, TypeError):
		return None


register_normalizer("price", parse_price)

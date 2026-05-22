"""SKU normalizer — trim, case preserve, separator normalize."""

import re

from tradehub_core.bulk_import.ingestion.normalizers import register_normalizer


def normalize_sku(value):
	"""SKU değeri için trim + whitespace collapse (case korunur)."""
	if value is None or value == "":
		return None
	s = str(value).strip()
	# Birden fazla boşluk → tek boşluk
	s = re.sub(r"\s+", " ", s)
	return s


register_normalizer("sku", normalize_sku)

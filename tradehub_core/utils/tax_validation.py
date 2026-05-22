"""TR VKN/TCKN format + checksum doğrulama — Sprint 1 (2026-05-15).

Maliye VKN algoritması: https://www.gib.gov.tr (10 hane)
TCKN algoritması: NVI (11 hane, Bakanlık doğrulamasız format)
"""

import re


def is_valid_vkn(value: str | None) -> bool:
	"""TR Vergi Kimlik No (10 hane) format + Maliye checksum doğrulaması."""
	if not value:
		return False
	v = re.sub(r"\D", "", value.strip())
	if len(v) != 10:
		return False
	# Maliye VKN checksum algoritması
	digits = [int(c) for c in v]
	last = digits[9]
	total = 0
	for i in range(9):
		tmp = (digits[i] + (9 - i)) % 10
		tmp = (tmp * (2 ** (9 - i))) % 9
		if tmp == 0 and (digits[i] + (9 - i)) % 10 != 0:
			tmp = 9
		total += tmp
	check = (10 - (total % 10)) % 10
	return check == last


def is_valid_tckn(value: str | None) -> bool:
	"""TR TC Kimlik No (11 hane) format + checksum doğrulaması."""
	if not value:
		return False
	v = re.sub(r"\D", "", value.strip())
	if len(v) != 11 or v[0] == "0":
		return False
	digits = [int(c) for c in v]
	odd_sum = digits[0] + digits[2] + digits[4] + digits[6] + digits[8]
	even_sum = digits[1] + digits[3] + digits[5] + digits[7]
	d10 = ((odd_sum * 7) - even_sum) % 10
	d11 = (sum(digits[:10])) % 10
	return d10 == digits[9] and d11 == digits[10]


def is_valid_tax_id(value: str | None) -> bool:
	"""VKN (10) veya TCKN (11) — format ve checksum'a göre kabul."""
	if not value:
		return False
	v = re.sub(r"\D", "", value.strip())
	if len(v) == 10:
		return is_valid_vkn(v)
	if len(v) == 11:
		return is_valid_tckn(v)
	return False

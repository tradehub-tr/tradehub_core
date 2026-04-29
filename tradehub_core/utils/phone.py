"""
Phone number canonicalization helpers.

Single source of truth for converting any user-entered Turkish phone string into
the E.164 canonical form (`+90XXXXXXXXXX`). Kept in `utils/` so every API
endpoint (identity, addresses, seller flows) shares the exact same rules.

Accepted Turkish input shapes — all collapse to `+905326542137`:
    +90 532 654 21 37        +905326542137         5326542137
    0532 654 21 37           905326542137          (532) 654-2137
    +90-(532)-654 2137       0 532 654 21 37

Subscriber rules:
    Mobile  → starts with 5 (10 digits)
    Landline → starts with 2, 3, or 4 (10 digits, geographic area codes)

Non-TR international (must arrive with explicit `+` and a country code other
than 90) is preserved as `+<digits>` if it parses to 8–15 digits — this lets us
handle foreign supplier contacts without forcing them into a Turkish format.
"""

import re

_TR_LOCAL_RE = re.compile(r"^[2-5]\d{9}$")


def canonicalize_phone(raw):
	"""Return the E.164 canonical form of *raw*, or ``None`` if it is not a
	parseable phone number.

	The result is one of:
	  - ``"+90XXXXXXXXXX"`` for any Turkish input
	  - ``"+<country><digits>"`` for an explicitly-international input
	  - ``None`` for empty / unparseable input
	"""
	if raw is None:
		return None
	s = str(raw).strip()
	if not s:
		return None

	# A leading "+" that is *not* "+90" signals an explicit non-TR international
	# number. We preserve it as E.164 if the digit count is sane.
	is_explicit_intl = s.startswith("+") and not s.lstrip().startswith("+90")
	digits = re.sub(r"\D", "", s)
	if not digits:
		return None

	if is_explicit_intl and 8 <= len(digits) <= 15:
		return "+" + digits

	# Strip TR country/trunk prefixes so we can validate the 10-digit subscriber.
	if digits.startswith("90") and len(digits) == 12:
		digits = digits[2:]
	elif digits.startswith("0") and len(digits) == 11:
		digits = digits[1:]

	if _TR_LOCAL_RE.match(digits):
		return "+90" + digits

	return None


def is_valid_tr_phone(raw):
	"""``True`` if *raw* canonicalizes to a Turkish E.164 number (`+90...`)."""
	canonical = canonicalize_phone(raw)
	return canonical is not None and canonical.startswith("+90")


def split_e164(canonical):
	"""Split a canonicalized E.164 string into ``(prefix, local)``.

	Used by the Addresses DocType which keeps ``phone_prefix`` and ``phone`` as
	separate fields. For ``"+905326542137"`` returns ``("+90", "5326542137")``;
	for ``"+14155551234"`` returns ``("+1", "4155551234")``. Returns
	``(None, None)`` if *canonical* is falsy.
	"""
	if not canonical or not canonical.startswith("+"):
		return None, None
	# TR is the dominant case — keep it cheap.
	if canonical.startswith("+90") and len(canonical) == 13:
		return "+90", canonical[3:]
	# Fallback: best-effort split. Most country codes are 1–3 digits; we treat
	# everything except the last 10 digits as the prefix when the total length
	# permits, otherwise fall back to "+" + first digit.
	digits = canonical[1:]
	if len(digits) >= 11:
		return "+" + digits[: len(digits) - 10], digits[-10:]
	return "+" + digits[:1], digits[1:]

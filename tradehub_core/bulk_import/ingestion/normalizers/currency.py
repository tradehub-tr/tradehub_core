"""Currency normalizer — TL/₺/TRY → 'TRY' (ISO-4217)."""

from tradehub_core.bulk_import.ingestion.normalizers import register_normalizer

CURRENCY_MAP = {
	"tl": "TRY",
	"₺": "TRY",
	"try": "TRY",
	"tr": "TRY",
	"$": "USD",
	"usd": "USD",
	"us": "USD",
	"dolar": "USD",
	"€": "EUR",
	"eur": "EUR",
	"euro": "EUR",
	"£": "GBP",
	"gbp": "GBP",
	"pound": "GBP",
}


def parse_currency(value):
	"""Para birimi sembolü → ISO-4217 kod (örn. ₺ → TRY)."""
	if value is None or value == "":
		return None
	s = str(value).strip().lower()
	return CURRENCY_MAP.get(s)


register_normalizer("currency", parse_currency)

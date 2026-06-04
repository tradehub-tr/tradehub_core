"""Boolean normalizer — evet/E/var/1/hayır/H/yok/0."""

from tradehub_core.bulk_import.ingestion.normalizers import register_normalizer

TRUTHY = {
	"evet",
	"e",
	"var",
	"1",
	"true",
	"t",
	"yes",
	"y",
	"doğru",
	"dogru",
	"açık",
	"acik",
	"aktif",
}
FALSY = {
	"hayır",
	"hayir",
	"h",
	"yok",
	"0",
	"false",
	"f",
	"no",
	"n",
	"yanlış",
	"yanlis",
	"kapalı",
	"kapali",
	"pasif",
}


def parse_bool(value):
	"""TR/EN bool kelimeleri → True/False/None."""
	if value is None or value == "":
		return None
	if isinstance(value, bool):
		return value
	if isinstance(value, int | float):
		return bool(value)
	s = str(value).strip().lower()
	if s in TRUTHY:
		return True
	if s in FALSY:
		return False
	return None


register_normalizer("bool", parse_bool)

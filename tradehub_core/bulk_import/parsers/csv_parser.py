"""CSV/TSV parser — UTF-8 BOM aware, delimiter auto-detect."""

import csv
import io


def parse_csv(
	file_path: str,
	header_row: int = 1,
	delimiter: str | None = None,
) -> tuple[list[str], list[dict]]:
	"""Returns (headers, rows_as_dicts).

	Args:
	    file_path: Absolute path to .csv / .tsv file
	    header_row: 1-indexed row containing column headers
	    delimiter: Force delimiter. If None, auto-sniff (',', ';', '\\t', '|').
	"""
	with open(file_path, "rb") as f:
		raw = f.read()

	if raw.startswith(b"\xef\xbb\xbf"):
		raw = raw[3:]
	text = raw.decode("utf-8", errors="replace")

	if delimiter is None:
		sniffer = csv.Sniffer()
		try:
			dialect = sniffer.sniff(text[:8192], delimiters=",;\t|")
			delimiter = dialect.delimiter
		except csv.Error:
			delimiter = ","

	reader = csv.reader(io.StringIO(text), delimiter=delimiter)
	rows = list(reader)
	if not rows or len(rows) < header_row:
		return [], []

	headers = [h.strip() if h is not None else "" for h in rows[header_row - 1]]

	data_rows: list[dict] = []
	for row in rows[header_row:]:
		if not any((c or "").strip() for c in row):
			continue
		row_dict: dict = {}
		for i, val in enumerate(row):
			if i < len(headers) and headers[i]:
				row_dict[headers[i]] = val
		if row_dict:
			data_rows.append(row_dict)

	return headers, data_rows

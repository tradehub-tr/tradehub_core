"""Excel parser — openpyxl tabanlı, header detection + multi-sheet support."""

from openpyxl import load_workbook


def parse_xlsx(
	file_path: str,
	sheet_name: str | None = None,
	header_row: int = 1,
) -> tuple[list[str], list[dict]]:
	"""Returns (headers, rows_as_dicts).

	Args:
	    file_path: Absolute path to .xlsx file
	    sheet_name: If None, picks first sheet (or heuristic — see ingestion/sniffer)
	    header_row: 1-indexed row containing column headers (default 1)
	"""
	wb = load_workbook(file_path, read_only=True, data_only=True)
	try:
		sheet = wb[sheet_name] if sheet_name else wb.worksheets[0]

		rows = list(sheet.iter_rows(values_only=True))
		if not rows or len(rows) < header_row:
			return [], []

		raw_headers = rows[header_row - 1]
		headers = [str(c).strip() if c is not None else "" for c in raw_headers]

		data_rows: list[dict] = []
		for row in rows[header_row:]:
			if all(c is None for c in row):
				continue
			row_dict: dict = {}
			for i, val in enumerate(row):
				if i < len(headers) and headers[i]:
					row_dict[headers[i]] = val
			if row_dict:
				data_rows.append(row_dict)

		return headers, data_rows
	finally:
		wb.close()


def list_sheets(file_path: str) -> list[str]:
	"""Return list of sheet names."""
	wb = load_workbook(file_path, read_only=True)
	try:
		return list(wb.sheetnames)
	finally:
		wb.close()

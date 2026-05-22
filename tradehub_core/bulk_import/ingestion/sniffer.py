"""Format sniffer — magic-byte detection + header row finder."""

import math

XLSX_MAGIC = b"PK\x03\x04"  # ZIP-based; xlsx is a zip
XML_MAGIC = b"<?xml"


def detect_format(file_path: str) -> str:
	"""Magic-byte tabanlı format tespiti (extension'a güvenme)."""
	with open(file_path, "rb") as f:
		head = f.read(16)
	if head.startswith(XLSX_MAGIC):
		# Could be xlsx or generic zip; check extension as tie-breaker
		if file_path.lower().endswith((".xlsx", ".xls", ".xlsm")):
			return "xlsx"
		return "zip"
	if head.startswith(XML_MAGIC) or head.lstrip().startswith(b"<"):
		return "xml"
	# CSV/TSV — fallback: check if utf-8 decodable + has delimiter
	try:
		text = head.decode("utf-8", errors="ignore")
		if any(d in text for d in (",", ";", "\t", "|")):
			return "csv"
	except Exception:
		# Decode hatası — format bilinmiyor, fallback unknown
		pass
	return "unknown"


def find_header_row(rows: list[list], max_check: int = 10) -> int | None:
	"""İlk N satıra bak, en olası başlık satırını döndür (1-indexed).

	Heuristic:
	- Düşük boşluk oranı
	- Yüksek string oranı (sayı oranı düşük)
	- Alt satırlarla heterojenlik (başlık tek tip değil, altı tek tip)

	Returns: 1-indexed row number, or None if cannot determine.
	"""
	if not rows:
		return None

	scored: list[tuple[int, float]] = []
	for i in range(min(max_check, len(rows))):
		row = rows[i]
		if not row:
			continue
		# Empty cell ratio
		nonempty = [c for c in row if c is not None and str(c).strip() != ""]
		if not nonempty:
			continue
		empty_ratio = 1.0 - (len(nonempty) / len(row))
		# String ratio (vs numeric)
		str_count = sum(1 for c in nonempty if not _is_numeric(c))
		str_ratio = str_count / len(nonempty) if nonempty else 0
		# Heterogeneity vs next 3 rows
		het_score = 0.0
		if i + 3 < len(rows):
			for j in range(i + 1, min(i + 4, len(rows))):
				next_row = rows[j]
				next_strs = [c for c in next_row if c and not _is_numeric(c)]
				next_str_ratio = (len(next_strs) / len(next_row)) if next_row else 0
				# Header has higher string ratio than data
				het_score += max(0, str_ratio - next_str_ratio)
			het_score /= 3
		# Composite
		score = (1.0 - empty_ratio) * 0.3 + str_ratio * 0.4 + het_score * 0.3
		scored.append((i + 1, score))

	if not scored:
		return None

	scored.sort(key=lambda x: -x[1])
	best_row, best_score = scored[0]
	# Confidence threshold
	if best_score < 0.5:
		return None  # Çok düşük güven — UI'a sor
	return best_row


def _is_numeric(value) -> bool:
	"""TR/EN sayı formatını kabul eden type checker."""
	if value is None:
		return False
	try:
		float(str(value).replace(",", ".").replace(" ", ""))
		return True
	except (ValueError, TypeError):
		return False


def pick_main_sheet(sheet_data: dict[str, list[list]]) -> str:
	"""Multi-sheet xlsx için ana sheet'i seç.

	Heuristic: en uzun + dengeli (string+numeric karışım) sheet.
	"""
	if not sheet_data:
		return ""
	if len(sheet_data) == 1:
		return list(sheet_data.keys())[0]

	scored: list[tuple[str, float]] = []
	for name, rows in sheet_data.items():
		if not rows:
			continue
		n_rows = len(rows)
		# Sample first 20 rows for type analysis
		sample = rows[:20]
		non_empty_cells = 0
		numeric_cells = 0
		for row in sample:
			for c in row:
				if c is not None and str(c).strip() != "":
					non_empty_cells += 1
					if _is_numeric(c):
						numeric_cells += 1
		if non_empty_cells == 0:
			continue
		# Mix ratio: closer to 0.5 = better product sheet (mixed types)
		numeric_ratio = numeric_cells / non_empty_cells
		mix_score = 1.0 - abs(0.5 - numeric_ratio) * 2  # 1 at 0.5, 0 at 0/1
		# Size bonus (log scale)
		size_score = math.log(max(n_rows, 1)) / math.log(1000)  # ~1.0 for 1000 rows
		score = mix_score * 0.6 + size_score * 0.4
		scored.append((name, score))

	if not scored:
		return list(sheet_data.keys())[0]
	scored.sort(key=lambda x: -x[1])
	return scored[0][0]

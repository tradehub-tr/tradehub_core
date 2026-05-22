"""XML parser — defusedxml ile XXE koruması, en uzun homojen child array'ini bul ve flatten et."""

from defusedxml import ElementTree as ET


def parse_xml(file_path: str) -> tuple[list[str], list[dict]]:
	"""Returns (field_names, rows).

	Strategy: recursive traversal, find longest homogeneous array of dict-like
	elements. Flatten via dot-paths (children as `parent.child`, attributes as `parent@attr`).
	"""
	tree = ET.parse(file_path)
	root = tree.getroot()

	items_list, _items_path = _find_items_array(root)
	if not items_list:
		return [], []

	all_keys: set[str] = set()
	flat_rows: list[dict] = []
	for item in items_list:
		flat = _flatten_element(item)
		flat_rows.append(flat)
		all_keys.update(flat.keys())

	headers = sorted(all_keys)
	return headers, flat_rows


def _find_items_array(element, current_path: str = "") -> tuple[list, str]:
	"""En uzun homojen child array'ini bul (recursively)."""
	children_by_tag: dict[str, list] = {}
	for child in element:
		children_by_tag.setdefault(child.tag, []).append(child)

	best: list = []
	best_path = current_path
	for tag, items in children_by_tag.items():
		if len(items) > len(best):
			best = items
			best_path = f"{current_path}/{tag}" if current_path else tag

	if len(best) == 1:
		return _find_items_array(best[0], best_path)

	return best, best_path


def _flatten_element(element, prefix: str = "") -> dict:
	"""Flatten XML element with dot-paths."""
	result: dict = {}

	if element.text and element.text.strip():
		key = prefix if prefix else element.tag
		result[key] = element.text.strip()

	for attr_name, attr_val in element.attrib.items():
		key = f"{prefix}@{attr_name}" if prefix else f"{element.tag}@{attr_name}"
		result[key] = attr_val

	for child in element:
		child_prefix = f"{prefix}.{child.tag}" if prefix else child.tag
		result.update(_flatten_element(child, child_prefix))

	return result

"""Resim eşleştirme — folder + filename hibrit auto-detect.

ZIP içinden resimleri File DocType'a yükler ve `SKU → [file_url, ...]` haritası döndürür.
"""

import os
import re
import zipfile

import frappe
from frappe import _

ALLOWED_EXT: set[str] = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

SKU_FILENAME_RE = re.compile(
	# SKU: harf/rakam/tire/nokta (greedy). "_" sınırlayıcı olarak idx için ayrıldı.
	r"^(?P<sku>[A-Z0-9][A-Z0-9\-.]*)"
	# Opsiyonel idx: _<sayı> veya _<tag> (main/detay/on/arka/front/back).
	r"(?:_(?P<idx>\d+|main|detay|on|arka|front|back))?"
	r"\.(?P<ext>jpe?g|png|webp|gif|bmp)$",
	re.IGNORECASE,
)

MAX_FILES_IN_ZIP = 50_000
MAX_UNCOMPRESSED_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB


def build_image_index(zip_path: str, seller_profile: str) -> dict[str, list[str]]:
	"""ZIP'i aç ve SKU → [File URLs] haritası kur.

	Strategy:
	- Top-level dosyalar: SKU.jpg → SKU = filename başlangıcı (regex SKU_FILENAME_RE)
	- Klasörler: SKU/main.jpg → SKU = klasör adı, alfabetik sıralama; ilk = primary
	"""
	index: dict[str, list[str]] = {}

	with zipfile.ZipFile(zip_path, "r") as zf:
		names = zf.namelist()
		if len(names) > MAX_FILES_IN_ZIP:
			frappe.throw(_("ZIP'te {0}'den fazla dosya var").format(MAX_FILES_IN_ZIP))

		total_size = sum(z.file_size for z in zf.infolist())
		if total_size > MAX_UNCOMPRESSED_SIZE:
			frappe.throw(_("ZIP açıldığında 2 GB'ı aşıyor — zip bomb riski"))

		folder_groups: dict[str, list[str]] = {}
		top_level_files: list[str] = []

		for name in names:
			if name.startswith("__MACOSX/") or name.startswith("._") or "/._" in name:
				continue
			if name.endswith("/"):
				continue

			ext = os.path.splitext(name)[1].lower()
			if ext not in ALLOWED_EXT:
				continue

			norm = os.path.normpath(name).replace("\\", "/")
			if norm.startswith("..") or norm.startswith("/") or os.path.isabs(norm):
				continue

			parts = norm.split("/")
			if len(parts) == 1:
				top_level_files.append(name)
			else:
				sku = parts[0]
				folder_groups.setdefault(sku, []).append(name)

		for sku, files in folder_groups.items():
			files.sort()
			uploaded: list[str] = []
			for f in files:
				url = _extract_and_save(zf, f, seller_profile)
				if url:
					uploaded.append(url)
			if uploaded:
				index.setdefault(sku, []).extend(uploaded)

		for name in top_level_files:
			filename = os.path.basename(name)
			m = SKU_FILENAME_RE.match(filename)
			if not m:
				continue
			sku = m.group("sku")
			url = _extract_and_save(zf, name, seller_profile)
			if url:
				index.setdefault(sku, []).append(url)

	return index


def _extract_and_save(
	zf: zipfile.ZipFile,
	zip_entry: str,
	seller_profile: str,
) -> str | None:
	"""ZIP içindeki bir dosyayı File DocType'a kaydet, URL döndür."""
	try:
		content = zf.read(zip_entry)
		filename = os.path.basename(zip_entry)
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"content": content,
				"is_private": 0,
				"decode": False,
			}
		)
		file_doc.insert(ignore_permissions=True)
		return file_doc.file_url
	except Exception as e:
		frappe.log_error(
			f"Image extract failed {zip_entry}: {e}",
			"bulk_import.image_matcher",
		)
		return None

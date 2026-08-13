"""Yükleme sırasında içerik-adresli dosya adlandırma (TUR-141/130).

Amaç: yeni yüklenen dosyaların adı URL'den tahmin edilemesin
(<sha256(içerik)[:32]>.<ext>). Mevcut file_url'ler korunur; yalnız yeni
yüklemelere uygulanır.

Frappe `write_file` hook sözleşmesi (frappe/utils/file_manager.py `save_file`,
frappe v15 kaynağından teyit edildi):

    write_file_method = get_hook_method("write_file", fallback=save_file_on_filesystem)
    file_data = write_file_method(fname, content, content_type=content_type, is_private=is_private)

- `fname`: `get_file_name()` ile önceden çakışma-önlemeli hale getirilmiş orijinal
  ad (yalnız aynı isimde dosya zaten varsa suffix eklenir) — burada diske yazılacak
  gerçek ada karar verilir, `File.file_name` (görünen ad) etkilenmez.
- `content`: bytes ya da str.
- Dönüş: `frappe.get_hooks()["write_file_keys"]` = `["file_url", "file_name"]`
  anahtarlarını içeren dict (bkz. `frappe/hooks.py`).
"""

import hashlib
import os

import frappe
from frappe.utils import get_files_path


def _hashed_name(original: str, content: bytes) -> str:
	"""İçerik-adresli dosya adı üretir: `<sha256(content)[:32]>.<uzantı>`.

	Aynı içerik → aynı ad (dedup + enumeration önleme); orijinal ad sızmaz.
	"""
	ext = os.path.splitext(original)[1].lower()
	h = hashlib.sha256(content).hexdigest()[:32]
	return f"{h}{ext}"


def write_file_hashed(fname: str, content, content_type: str | None = None, is_private: int = 0) -> dict:
	"""Frappe `write_file` hook implementasyonu — diske hash-adıyla yazar.

	`frappe.utils.file_manager.save_file_on_filesystem` fallback'inin yerini alır;
	aynı imza + aynı dönüş sözleşmesiyle çalışır, tek fark diskteki ad + `file_url`
	içerik-hash'li olması (`/files/` veya `/private/files/` prefix + uzantı korunur).
	"""
	if isinstance(content, str):
		content = content.encode()

	hashed_name = _hashed_name(fname, content)

	folder_path = get_files_path(is_private=is_private)
	frappe.create_folder(folder_path)
	disk_path = os.path.join(folder_path.encode("utf-8"), hashed_name.encode("utf-8"))
	with open(disk_path, "wb+") as f:
		f.write(content)

	file_url = f"/private/files/{hashed_name}" if is_private else f"/files/{hashed_name}"
	return {"file_name": hashed_name, "file_url": file_url}

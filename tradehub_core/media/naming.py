"""Yükleme sırasında içerik-adresli dosya adlandırma (TUR-141/130).

Amaç: yeni yüklenen dosyaların adı URL'den tahmin edilemesin
(<sha256(içerik)[:32]>.<ext>). Mevcut file_url'ler korunur; yalnız yeni
yüklemelere uygulanır.

Frappe `write_file` hook'u konteynerdeki gerçek kaynaktan (frappe v15) teyit
edildiği üzere İKİ farklı çağrı yolundan, İKİ farklı imzayla tetiklenebilir —
fix round 1'de (Critical bulgu) ilk yol eksikti, HER içerikli upload kırılıyordu:

1) Asıl upload yolu — `frappe/core/doctype/file/file.py` `File.save_file()`
   (yani `/api/method/upload_file` da dahil DocType üzerinden her yükleme):

       write_file_method = get_hook_method("write_file")
       if write_file_method:
           return write_file_method(self)     # TEK argüman: File doc (Document)

   Bu yolda dönüş değeri `before_insert()` içinde KULLANILMAZ (`self.save_file(...)`
   çağrısı sonucu discard edilir) — asıl etki `self.file_url`'in mutate edilmesi ve
   `self.write_file()` ile `self.get_full_path()` (→ `self.file_url`'e göre çözülür)
   konumuna gerçekten yazılmasıdır. Frappe'nin kendi `File.save_file_on_filesystem()`
   implementasyonu da aynı deseni izler (`file.py` satır ~746-755): önce
   `self.file_url`'i (sanitize edilmiş `self.file_name`'den) ayarlar, sonra
   `self.write_file()` çağırır, sonra `{"file_name":.., "file_url":..}` döner.

2) Legacy yol — `frappe/utils/file_manager.py` `save_file()`:

       write_file_method = get_hook_method("write_file", fallback=save_file_on_filesystem)
       file_data = write_file_method(fname, content, content_type=content_type, is_private=is_private)

   `fname`: `get_file_name()` ile önceden çakışma-önlemeli hale getirilmiş orijinal ad.
   `content`: bytes ya da str.

Her iki yolda da dönüş `frappe.get_hooks()["write_file_keys"]` = `["file_url", "file_name"]`
anahtarlarını içeren dict olmalı (bkz. `frappe/hooks.py`).

`File.file_name` (görünen ad) her iki yolda da BU MODÜL tarafından değiştirilmez —
yalnız disk adı + `file_url` içerik-hash'lidir.
"""

import hashlib
import os

import frappe
from frappe.model.document import Document
from frappe.utils import get_files_path


def _hashed_name(original: str, content: bytes) -> str:
	"""İçerik-adresli dosya adı üretir: `<sha256(content)[:32]>.<uzantı>`.

	Aynı içerik → aynı ad (dedup + enumeration önleme); orijinal ad sızmaz.
	"""
	ext = os.path.splitext(original)[1].lower()
	h = hashlib.sha256(content).hexdigest()[:32]
	return f"{h}{ext}"


def _shard(hashed_name: str) -> str:
	"""Hash-prefix shard alt dizini: adın ilk 2 hex karakteri (00–ff).

	Tek dizinde milyonlarca dosya yerine ~256 dengeli alt dizin (TUR-130).
	İçerik-adresli adla doğal uyumlu; yedek blob'ları (media-backups/blobs/<xx>)
	zaten aynı deseni kullanıyor.
	"""
	return hashed_name[:2]


def _ensure_shard_dir(is_private: int, shard: str) -> None:
	"""Shard alt dizinini diskte oluştur — Frappe `write_file()` mkdir YAPMAZ
	(doğrudan `open(get_full_path(), "wb+")` çağırır), yoksa yükleme kırılır.
	"""
	base = get_files_path(is_private=is_private)
	frappe.create_folder(os.path.join(base, shard))


def write_file_hashed(*args, **kwargs) -> dict:
	"""Frappe `write_file` hook implementasyonu — iki çağrı yolunu da destekler.

	İlk argümanın tipine göre ayrılır: `Document` (File doc) → asıl upload yolu;
	aksi halde (str `fname`) → legacy `file_manager.save_file()` yolu.
	"""
	first = args[0] if args else None
	if isinstance(first, Document):
		return _write_file_from_doc(first)
	return _write_file_legacy(*args, **kwargs)


def _write_file_from_doc(doc: Document) -> dict:
	"""Asıl upload yolu — `File.save_file_on_filesystem()`'in yerini alır.

	`doc.file_url`'i hash'li adla ayarlar, `doc.write_file()` ile (get_full_path()
	→ doc.file_url'e göre çözülür) diske yazar. `doc.file_name` DEĞİŞTİRİLMEZ.
	"""
	content = doc.get_content()
	content_bytes = content.encode() if isinstance(content, str) else content

	hashed_name = _hashed_name(doc.file_name, content_bytes)
	shard = _shard(hashed_name)
	_ensure_shard_dir(doc.is_private, shard)
	prefix = "/private/files" if doc.is_private else "/files"
	doc.file_url = f"{prefix}/{shard}/{hashed_name}"

	fpath = doc.write_file()
	return {"file_name": os.path.basename(fpath), "file_url": doc.file_url}


def _write_file_legacy(fname: str, content, content_type: str | None = None, is_private: int = 0) -> dict:
	"""Legacy yol — `frappe.utils.file_manager.save_file_on_filesystem()`'in yerini alır."""
	if isinstance(content, str):
		content = content.encode()

	hashed_name = _hashed_name(fname, content)
	shard = _shard(hashed_name)

	folder_path = get_files_path(is_private=is_private)
	shard_path = os.path.join(folder_path, shard)
	frappe.create_folder(shard_path)
	disk_path = os.path.join(shard_path.encode("utf-8"), hashed_name.encode("utf-8"))
	with open(disk_path, "wb+") as f:
		f.write(content)

	prefix = "/private/files" if is_private else "/files"
	file_url = f"{prefix}/{shard}/{hashed_name}"
	return {"file_name": hashed_name, "file_url": file_url}

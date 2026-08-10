"""Orijinal görsel arşivi — optimizasyon geri alınabilsin diye.

Karar (GORSEL-OPTIMIZASYON.md §6, 2026-08-05'te güncellendi): dosyanın üstüne
yazıyoruz ama orijinali **süreli** saklıyoruz. `file_url` değişmediği için 22 alandaki
referanslar (JSON blob'lar dahil) kırılmaz; yanlış ayarla çalıştırılırsa
`ARCHIVE_RETENTION_DAYS` gün içinde geri alınabilir.

Arşiv `<site>/private/image_originals/` altındadır ve **`File` kaydı yaratılmaz** —
yoksa aynı dosya envanterde iki kez görünür ve depolama raporu bozulur.

Purge sonrası nihai kazanç gelir; o güne kadar disk geçici olarak şişer.
"""

from __future__ import annotations

import os
import shutil
import time

import frappe

from tradehub_core.media import audit
from tradehub_core.media.presets import ARCHIVE_DIRNAME, ARCHIVE_RETENTION_DAYS


def _archive_root() -> str:
	return frappe.get_site_path("private", ARCHIVE_DIRNAME)


def relative_path_for(file_url: str) -> str:
	"""`file_url` → arşiv içindeki göreli yol.

	`/files/a/b.jpg`         → `public/a/b.jpg`
	`/private/files/a/b.jpg` → `private/a/b.jpg`

	Path traversal koruması: `..` içeren veya beklenen önekle başlamayan URL reddedilir.
	"""
	url = (file_url or "").split("?")[0]
	if not url or ".." in url:
		frappe.throw(frappe._("Geçersiz dosya yolu: {0}").format(file_url))

	if url.startswith("/private/files/"):
		return os.path.join("private", url[len("/private/files/") :])
	if url.startswith("/files/"):
		return os.path.join("public", url[len("/files/") :])

	frappe.throw(frappe._("Desteklenmeyen dosya yolu: {0}").format(file_url))
	return ""  # ulaşılmaz — throw yukarıda


def absolute_path_for(file_url: str) -> str:
	"""Arşivdeki mutlak yol. Sonuç arşiv kökünün dışına çıkamaz."""
	root = os.path.realpath(_archive_root())
	target = os.path.realpath(os.path.join(root, relative_path_for(file_url)))
	if not target.startswith(root + os.sep):
		frappe.throw(frappe._("Arşiv yolu kök dizinin dışında: {0}").format(file_url))
	return target


def exists(file_url: str) -> bool:
	return os.path.isfile(absolute_path_for(file_url))


def store(file_url: str, content: bytes) -> str:
	"""Orijinali arşive yaz, göreli yolu dön. Zaten varsa üzerine YAZMAZ.

	Üzerine yazmama kuralı bilinçli: ikinci bir koşu (bug ya da elle tetikleme)
	zaten optimize edilmiş içeriği "orijinal" diye arşive yazarsa geri alma
	imkânı sessizce kaybolur.
	"""
	rel = relative_path_for(file_url)
	abs_path = absolute_path_for(file_url)
	if os.path.isfile(abs_path):
		return rel

	os.makedirs(os.path.dirname(abs_path), exist_ok=True)
	with open(abs_path, "wb") as f:
		f.write(content)
	return rel


def read(file_url: str) -> bytes:
	"""Arşivdeki orijinali oku. Yoksa hata fırlatır — çağıran geri alma yapmamalı."""
	abs_path = absolute_path_for(file_url)
	if not os.path.isfile(abs_path):
		frappe.throw(frappe._("Orijinal arşivde bulunamadı: {0}").format(file_url))
	with open(abs_path, "rb") as f:
		return f.read()


def drop(file_url: str) -> None:
	"""Arşiv kopyasını sil (geri alma sonrası — artık orijinal yerinde)."""
	abs_path = absolute_path_for(file_url)
	if os.path.isfile(abs_path):
		os.remove(abs_path)


def usage_bytes() -> int:
	"""Arşivin kapladığı toplam alan — UI'da 'geri alma penceresi' göstergesi."""
	root = _archive_root()
	if not os.path.isdir(root):
		return 0
	total = 0
	for dirpath, _dirnames, filenames in os.walk(root):
		for name in filenames:
			try:
				total += os.path.getsize(os.path.join(dirpath, name))
			except OSError:
				continue
	return total


def purge_expired(retention_days: int = ARCHIVE_RETENTION_DAYS) -> dict:
	"""Süresi dolan arşiv dosyalarını sil. Günlük scheduler job'ı çağırır.

	Geri alma penceresi kapandıktan sonra nihai depolama kazancı burada gerçekleşir.
	"""
	root = _archive_root()
	if not os.path.isdir(root):
		return {"deleted": 0, "freed_bytes": 0}

	cutoff = time.time() - retention_days * 86400
	deleted = 0
	freed = 0
	for dirpath, _dirnames, filenames in os.walk(root):
		for name in filenames:
			path = os.path.join(dirpath, name)
			try:
				if os.path.getmtime(path) >= cutoff:
					continue
				size = os.path.getsize(path)
				os.remove(path)
				deleted += 1
				freed += size
			except OSError:
				continue

	_prune_empty_dirs(root)

	# Arşiv silindikten sonra o dosyalar bir daha orijinaline döndürülemez —
	# geri alma penceresinin kapandığı an denetimde görünmeli.
	audit.log_media_batch(
		action=audit.ACTION_PURGE_ARCHIVE,
		summary={"retention_days": retention_days, "deleted": deleted, "freed_bytes": freed},
	)
	return {"deleted": deleted, "freed_bytes": freed}


def _prune_empty_dirs(root: str) -> None:
	"""Boşalan arşiv klasörlerini temizle (kök korunur)."""
	for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
		if dirpath == root:
			continue
		try:
			if not os.listdir(dirpath):
				shutil.rmtree(dirpath, ignore_errors=True)
		except OSError:
			continue

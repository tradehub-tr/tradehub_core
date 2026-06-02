"""
Güvenlik yardımcıları — file upload XSS koruması (HATA 23).

SVG dosyaları içlerinde `<script>` veya `onload="..."` event handler'ı
barındırabildiği için tarayıcı tarafından parse edildiklerinde JS çalıştırırlar.
HTML / SVG / JS dosyaları aktif olarak XSS vektörüdür.

Bu modül `File` doctype'ın `before_insert` event'ine bağlanır; bütün upload
yollarını (Frappe'nin `/api/method/upload_file`, custom listing image upload,
seller logo/banner, KYB belgeler) tek noktadan kapatır.

Dosya türü beyaz listesinde (allow-list yaklaşımı) sadece güvenli formatlar:
raster image (png/jpg/jpeg/webp/gif/bmp), belge (pdf/doc/docx/xls/xlsx),
arşiv (zip), video (mp4) ve düz metin (txt, csv).
"""

import os

import frappe
from frappe import _

# ── Reddedilen uzantılar (XSS / RCE riski) ──────────────────────────────────
# `.svg` browser tarafından `<script>` ile parse edilir → stored XSS.
# `.html`/`.htm`/`.xhtml` aynı şekilde, ayrıca clickjacking surface.
# `.js`/`.mjs`/`.ts` script execute edebilir.
# `.swf`/`.xml`/`.xsl` legacy XSS vektörleri.
_DENIED_EXTENSIONS = frozenset(
	{
		".svg",
		".svgz",
		".html",
		".htm",
		".xhtml",
		".js",
		".mjs",
		".ts",
		".jsx",
		".tsx",
		".swf",
		".xsl",
		".xslt",
		".xml",
	}
)


def _extract_extension(file_name: str | None, file_url: str | None) -> str:
	"""Dosya uzantısını küçük harfe normalize ederek döner. Yoksa boş string."""
	source = (file_name or "").strip() or (file_url or "").strip()
	if not source:
		return ""
	# Query string ve fragment'ı sıyır: "logo.svg?v=1" → "logo.svg"
	source = source.split("?", 1)[0].split("#", 1)[0]
	_, ext = os.path.splitext(source)
	return ext.lower()


def reject_unsafe_files(doc, method=None):
	"""
	`File` doctype `before_insert` hook'u. Yasaklı uzantıları yüklemeyi engeller.

	`tradehub_core/hooks.py` içinde:
	    doc_events = {
	        "File": {"before_insert": "tradehub_core.utils.security.reject_unsafe_files"},
	    }
	"""
	# Folder kayıtlarını atla — sadece gerçek dosyalar kontrol edilir.
	if getattr(doc, "is_folder", 0):
		return
	# Bulk import context'i: `tradehub_core.bulk_import.api.upload_bulk_file`
	# kontrollü kanal (uzantı + boyut allowlist'i kendi içinde). XML/CSV gibi
	# normalde yasaklı uzantıları bulk import için bypass eder.
	# İki flag kanalı: doc.flags (eski) + frappe.flags.in_bulk_import_upload
	# (save_file utility'sinde flag persistasyonu için).
	if getattr(getattr(doc, "flags", None), "bulk_import_safe", False):
		return
	if getattr(frappe.flags, "in_bulk_import_upload", False):
		return
	ext = _extract_extension(getattr(doc, "file_name", None), getattr(doc, "file_url", None))
	if ext and ext in _DENIED_EXTENSIONS:
		frappe.throw(
			_("Bu dosya türü güvenlik nedeniyle kabul edilmiyor: {0}").format(ext),
			frappe.PermissionError,
		)

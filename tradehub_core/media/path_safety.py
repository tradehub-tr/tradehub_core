"""`check_path_safety` uyumluluk katmanı — Frappe sürüm farkına karşı.

`frappe.core.doctype.file.utils.check_path_safety` Frappe v15'e yakın tarihli
bir güvenlik yamasıyla eklendi; her v15 kurulumunda YOK (alpha.istoc.com'daki
Frappe'de bulunmuyor, lokal dev imajındakinde var). Doğrudan import eden her
modül, eski Frappe'li ortamda ImportError ile import zincirini (media_admin
dahil TÜM media endpoint'leri) çökertiyordu — 2026-08-20 alpha 417 arızası.

Bu modül tek noktadan çözer: Frappe'ninki varsa o kullanılır (upstream'e
gelecek iyileştirmeler otomatik alınır), yoksa birebir aynı davranışın yerel
kopyası devreye girer. tradehub_core içinde `check_path_safety` HER ZAMAN
buradan import edilmeli, frappe'den asla doğrudan değil.
"""

from __future__ import annotations

import os

import frappe

try:
	from frappe.core.doctype.file.utils import check_path_safety as _upstream_check
except ImportError:
	_upstream_check = None


def _yerel_check(base_path: str, requested_path: str) -> bool:
	"""Upstream Frappe'deki fonksiyonun birebir kopyası (sandbox + log)."""
	base_path = os.path.realpath(base_path)
	requested_path = os.path.realpath(requested_path)
	if os.path.commonpath([base_path, requested_path]) != base_path:
		frappe.log_error(
			title="Attempted Unauthorized File Access",
			message=f"Blocked access to: {requested_path}",
		)
		return False
	return True


def check_path_safety(base_path: str, requested_path: str) -> bool:
	"""Yol kökün altında mı — **istisna atmaz**, karar döner.

	F-08: `os.path.commonpath` mutlak ile göreceyi (ve farklı sürücüleri)
	birlikte kabul etmez, `ValueError` atar. Ne upstream Frappe'nin sürümü ne
	de yerel kopya bunu yakalıyordu; sonuç "güvenli değil" yerine yükselen bir
	istisnaydı ve çağıran `except` koymamışsa istek 500 dönüyordu. Kullanıcı
	girdisiyle beslenen bir kapıda bu bir DoS/gürültü yüzeyidir.

	Sarmalayıcı upstream'i KORUR (oradaki iyileştirmeler otomatik alınır) ama
	karşılaştırma yapılamadığında **fail-closed** davranır: cevap `False`.
	"""
	fn = _upstream_check or _yerel_check
	try:
		return bool(fn(base_path, requested_path))
	except ValueError:
		frappe.log_error(
			title="Attempted Unauthorized File Access",
			message=f"Path comparison failed (base={base_path!r}): {requested_path!r}",
		)
		return False


__all__ = ["check_path_safety"]

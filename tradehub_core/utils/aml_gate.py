"""Satıcı AML / yaptırım kapısı — iki katmanın (yetki listesi + DocType izni) ortak sorgusu.

Admin, KYB incelemesinde `aml_check_status` ("Hit Found") ya da `sanctions_status`
("Match Found") işaretlerse satıcı ödeme onayı / iade / bakiye çekme yetkisini ve
Payment Intent / Escrow Account / Seller Balance erişimini kaybeder. Otomatik tarama
sağlayıcısı yok; alanları admin elle doldurur.

Kararlar (MOGEM-685 bulgu 1, 29 Eyl 2026):
* Tarama yapılmamış ("Not Checked", boş, KYB kaydı yok) satıcı engellenmez.
* Sorgu düşerse KAPALI: hassas iş güvenli tarafta durur, hata kayda geçer. Eskiden alanlar
  şemada olmadığı için sorgu HER çağrıda düşüyor ve "geçti" sayılıyordu (1.775 Error Log).
"""

from __future__ import annotations

import frappe

AML_ISARETLI = "Hit Found"
YAPTIRIM_ISARETLI = "Match Found"
HATA_BASLIGI = "AML/yaptırım kontrolü yapılamadı — işlem durduruldu"


def aml_engelli_mi(user: str) -> bool:
	"""Satıcı işaretliyse ya da kontrol yapılamıyorsa True."""
	try:
		# KYB Verification submittable değil (docstatus hep 0) — eski `docstatus: 1` filtresi hiçbir
		# kaydı bulmuyordu. Kullanıcı başına tek kayıt; yine de en yenisi okunur.
		kyb = frappe.db.get_value(
			"KYB Verification",
			{"user": user},
			["aml_check_status", "sanctions_status"],
			as_dict=True,
			order_by="creation desc",
		)
	except Exception:
		frappe.log_error(title=HATA_BASLIGI, message=f"user={user}\n{frappe.get_traceback()}")
		return True
	if not kyb:
		return False
	return kyb.aml_check_status == AML_ISARETLI or kyb.sanctions_status == YAPTIRIM_ISARETLI

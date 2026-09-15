"""Çakışan 'Tradehub Seller' workspace kaydını kaldır (BE kalıntı temizliği).

Desk'te AYNI "Satıcı Paneli" etiketiyle iki workspace listeleniyordu:
  - "Satıcı Paneli"  (workspace/satıcı_paneli) — TUTULAN: en güncel
    (modified 2026-03-30), content ↔ shortcuts birebir tutarlı (17/17) ve
    bakımı isimle hedefleyen iki patch var (add_seller_role_to_workspace,
    add_certification_to_workspace — sc20 eklemesi dosyada mevcut).
  - "Tradehub Seller" (workspace/tradehub_seller) — KALDIRILAN: daha eski
    kopya; content'i var olmayan 5 shortcut'a referans veriyordu ("Satıcı
    Profili", "Alıcı Profili", "Tedarikçi Profili", "Döviz Kurları",
    "Admin Satıcı Profili" → Desk'te kırık kartlar) ve sidebar'da aynı
    etiketle mükerrer satır üretiyordu.

JSON dosyası repodan silindi; bu patch sitedeki yetim Workspace kaydını da
temizler ki migrate sonrası Desk'te bayat kayıt kalmasın.
"""

import frappe


def execute() -> None:
	# İdempotent: kayıt yoksa (taze kurulum / tekrar koşum) sessizce çık.
	if not frappe.db.exists("Workspace", "Tradehub Seller"):
		return

	# Sistem migration yolu, user input yok — standart (is_standard=1) workspace
	# kaydını silebilmek için force + ignore_permissions gerekli.
	frappe.delete_doc(
		"Workspace",
		"Tradehub Seller",
		force=True,
		ignore_permissions=True,
		ignore_missing=True,
	)
	frappe.db.commit()

"""FAZ 9.5 — Onayda düşen ASP iletişim/vergi alanlarını Seller Application'dan backfill.

Sorun:
  Satıcı başvurusunda toplanan tax_office / address_line_1 / city alanları,
  onay anında (seller_application._approve_application) Admin Seller Profile'a
  KOPYALANMIYORDU — yalnızca User Profile'a yazılıyor ya da hiç yazılmıyordu.
  Sonuç: panelin "Mağaza Profilleri" formunda İletişim adresi ve Vergi Dairesi
  IBAN'ı dolu satıcılarda bile her zaman boş görünüyordu.

  Onay kodu artık bu üç alanı ASP'ye de yazıyor. Bu patch mevcut (eski onaylı)
  kayıtları, başvurularındaki değerlerle geriye dönük doldurur.

Çözüm:
  Her Admin Seller Profile için user üzerinden bağlı en güncel Seller Application'ı
  bul; ASP'de BOŞ olan tax_office/address_line1/city alanlarını başvurudaki dolu
  değerle doldur. Dolu olan ASP alanlarına DOKUNMA (sonradan elle düzeltilmiş
  olabilir). set_value + update_modified=False ile sessiz; on_update/rol senkronu
  tetiklenmez. İdempotent: ikinci koşuda boş alan kalmadığı için no-op.
"""

from __future__ import annotations

import frappe

# ASP alanı → Seller Application kaynak alanı
_FIELD_MAP = {
	"tax_office": "tax_office",
	"address_line1": "address_line_1",
	"city": "city",
}


def execute() -> dict:
	if not frappe.db.exists("DocType", "Admin Seller Profile") or not frappe.db.exists(
		"DocType", "Seller Application"
	):
		return {"skipped": "no_doctype"}

	# Sistem migration'ı — perm bypass kasıtlı (tüm tenant'lardaki eski kayıtlar).
	profiles = frappe.get_all(
		"Admin Seller Profile",
		fields=["name", "user", *_FIELD_MAP.keys()],
	)

	filled = 0
	for asp in profiles:
		if not asp.get("user"):
			continue
		# Üç hedef alan da doluysa bu kayıt için yapılacak iş yok.
		if all((asp.get(f) or "").strip() for f in _FIELD_MAP):
			continue

		app = frappe.get_all(
			"Seller Application",
			filters={"applicant_user": asp["user"]},
			fields=["name", *_FIELD_MAP.values()],
			order_by="modified desc",
			limit=1,
		)
		if not app:
			continue
		src = app[0]

		updates = {
			asp_field: src[src_field]
			for asp_field, src_field in _FIELD_MAP.items()
			if not (asp.get(asp_field) or "").strip() and (src.get(src_field) or "").strip()
		}
		if updates:
			frappe.db.set_value(
				"Admin Seller Profile", asp["name"], updates, update_modified=False
			)
			filled += 1

	frappe.db.commit()
	frappe.logger().info(f"v15_9_5 ASP iletişim/vergi backfill: {filled} kayıt güncellendi")
	return {"filled": filled}

"""FAZ 8.4 — Belgesiz "Pending" KYB kayıtlarını "Draft"a çek (status semantiği).

Sorun:
  KYB Verification "Draft" başlangıç durumu yokken kayıtlar 3 auto-create
  noktasında (seller_application onayı, get_kyb_status, upload_kyb_document)
  doğrudan "Pending" ile, boş belgelerle yaratılıyordu. Satıcı tek belge
  yüklemeden "Başvurunuz Beklemede" görüyordu — "Pending" hem "henüz
  gönderilmedi" hem "gönderildi, inceleniyor" anlamına geliyordu.

  Kod artık auto-create'lerde "Draft", gerçek submit'te (submit_kyb_documents)
  "Pending" atıyor. Bu patch mevcut (eski) kayıtları yeni semantiğe taşır.

Çözüm:
  status="Pending" ama 5 ZORUNLU belgenin (faaliyet_belgesi opsiyonel, hariç)
  HEPSİ boş olan kayıtları "Draft"a çek — bunlar gerçekte hiç başvurulmamış
  taslaklar. En az bir zorunlu belgesi olan "Pending" kayıtlara DOKUNMA
  (gerçek, inceleme bekleyen başvurular). can_sell zaten 0 (Pending de Draft
  de satışı kapatır) → User Profile senkronu gerekmez.

  set_value ile DB seviyesinde değiştirir (on_update/bildirim/rol senkronu
  tetiklenmez — backfill sessiz olmalı). İdempotent: ikinci koşuda belgesiz
  Pending kalmadığı için no-op.
"""

from __future__ import annotations

import frappe

# faaliyet_belgesi opsiyonel — zorunlu 5 belge (kyb_verification._validate_file_attachments).
_REQUIRED_DOC_FIELDS = (
	"identity_document",
	"imza_sirkuleri",
	"ticaret_sicil_gazetesi",
	"vergi_levhasi",
	"bank_account_document",
)


def execute() -> dict:
	if not frappe.db.exists("DocType", "KYB Verification"):
		return {"skipped": "no_doctype"}

	# Sistem migration'ı — perm bypass kasıtlı (tüm tenant'lardaki eski kayıtlar).
	pending = frappe.get_all(
		"KYB Verification",
		filters={"status": "Pending"},
		fields=["name", *_REQUIRED_DOC_FIELDS],
	)

	converted = []
	for row in pending:
		# En az bir zorunlu belge varsa gerçek başvuru → dokunma.
		if any((row.get(f) or "").strip() for f in _REQUIRED_DOC_FIELDS):
			continue
		frappe.db.set_value(
			"KYB Verification", row["name"], "status", "Draft", update_modified=False
		)
		converted.append(row["name"])

	frappe.db.commit()
	frappe.logger().info(f"v15_8_4 KYB Pending→Draft (belgesiz): {len(converted)}")
	return {"converted": len(converted)}

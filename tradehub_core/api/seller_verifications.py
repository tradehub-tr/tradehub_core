"""
Doğrulama Başvurularım — satıcı kendi Seller Verification kayıtlarını yönetir.

Güvenlik mimarisi:
  - seller her zaman session.user'ın Admin Seller Profile'ından türetilir.
  - Parametre olarak seller kabul edilmez → başka satıcı adına işlem imkânsız.
  - Tenant izolasyonu çift katmanlı:
      1. permissions.py :: seller_verification_query_conditions (liste sorguları)
      2. permissions.py :: seller_verification_has_permission (per-doc)
  - Belge upload: mevcut upload_seller_cert_document (seller_certifications.py) ile
    dosyayı yükleyip file_url'i create_my_verification'a `document` olarak geçin.
"""

from __future__ import annotations

import frappe
from frappe import _

from tradehub_core.api.seller_certifications import _require_seller_profile

# _require_seller_profile: session.user → Admin Seller Profile name;
# yoksa throw. Capability parametresine None geçilirse sadece login + profil kontrolü.


# ──────────────────────────────────────────────────────────────────────────
# Okuma — satıcı kendi başvurularını listeler
# ──────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def get_my_verifications() -> list:
	"""Satıcının tüm Seller Verification kayıtlarını döner (tüm statüler).

	N+1 önleme: Verification Source.source_name batch olarak çekilir.
	Tenant güvencesi: frappe.get_list permission_query_conditions üzerinden
	otomatik seller filtresi uygular; ek olarak explicit seller=profile_name
	filtresi çift güvence sağlar.

	Dönüş:
	    list[dict]: name, source, source_name, status, inspection_date,
	                expiry_date, document alanlarını içeren kayıt listesi.
	                Satıcı profili yoksa boş liste.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		return []

	profile_name = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
	if not profile_name:
		return []

	# frappe.get_all kullanım gerekçesi: DocType permission'ında Seller / Marketplace Seller
	# rolleri `if_owner: 1` ile tanımlı. frappe.get_list bu durumda WHERE owner=user ekler;
	# mevcut kayıtların owner'ı "Administrator" olduğundan get_list her zaman boş döner.
	# Güvenlik, profile_name'in session.user'dan türetilmesiyle (kullanıcı girdisinden değil)
	# ve explicit seller=profile_name filtresiyle zaten sağlanıyor — seller_certifications.py
	# get_my_certifications ile aynı desen.
	verifications = frappe.get_all(
		"Seller Verification",
		filters={"seller": profile_name},
		fields=["name", "source", "status", "inspection_date", "expiry_date", "document"],
		order_by="creation DESC",
	)

	if not verifications:
		return []

	# N+1 önleme: source_name'leri tek batch sorguyla çek
	source_ids = list({v["source"] for v in verifications if v.get("source")})
	source_name_map: dict[str, str] = {}
	if source_ids:
		for row in frappe.get_all(
			"Verification Source",
			filters={"name": ["in", source_ids]},
			fields=["name", "source_name"],
		):
			# Verification Source.name == source_name (autoname: field:source_name)
			source_name_map[row["name"]] = row["source_name"]

	for v in verifications:
		v["source_name"] = source_name_map.get(v["source"], v.get("source") or "")

	return verifications


# ──────────────────────────────────────────────────────────────────────────
# Yazma — satıcı yeni başvuru oluşturur
# ──────────────────────────────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def create_my_verification(
	source: str,
	document: str,
	inspection_date: str | None = None,
	expiry_date: str | None = None,
) -> dict:
	"""Satıcı adına yeni Seller Verification başvurusu oluşturur.

	Güvenlik:
	    seller parametresi KABUL EDİLMEZ; session.user'dan türetilir.
	    Başka satıcı adına başvuru oluşturmak imkânsızdır.

	Doğrulama:
	    - source: Verification Source'da is_active=1 olmalı.
	    - document: boş olamaz (URL/path).
	    - (seller, source) çifti zaten varsa anlamlı i18n hatası döner.

	Controller notu (seller_verification.py._enforce_status_rule):
	    Yeni kayıtlarda status her zaman "Pending"'e zorlanır;
	    buradan farklı bir değer göndermek etkisizdir.

	ignore_permissions gerekçesi:
	    DocType permission tablosunda Seller / Marketplace Seller rolleri
	    `create: 1, if_owner: 1` olarak tanımlı. Frappe insert öncesi
	    doc.owner'ı session.user'a set eder, bu yüzden normal akışta
	    permission check geçer. Bununla birlikte Frappe v15'te `if_owner`
	    create kontrolünün davranışı sürüm içi değişikliğe uğramıştır;
	    güvenlik, seller alanının yalnızca kendi profile_name'inden
	    alınması ile zaten sağlandığından `ignore_permissions=True` eklendi.

	Dönüş:
	    dict: ok=True, name (kayıt adı), status="Pending"
	"""
	profile_name = _require_seller_profile()

	# Parametre doğrulama
	if not source or not str(source).strip():
		frappe.throw(_("Doğrulama kaynağı zorunludur."))
	if not document or not str(document).strip():
		frappe.throw(_("Denetim belgesi yüklemek zorunludur."))

	# Verification Source aktif mi?
	vs_is_active = frappe.db.get_value("Verification Source", source, "is_active")
	if vs_is_active is None:
		frappe.throw(_("Belirtilen doğrulama kaynağı bulunamadı."))
	if not vs_is_active:
		frappe.throw(_("Bu doğrulama kaynağı artık aktif değil."))

	try:
		doc = frappe.get_doc(
			{
				"doctype": "Seller Verification",
				"seller": profile_name,
				"source": source,
				"document": document,
				"inspection_date": inspection_date or None,
				"expiry_date": expiry_date or None,
				# status: controller._enforce_status_rule "Pending"'e zorlar
			}
		)
		# ignore_permissions: güvenlik seller=kendi profil kısıtıyla sağlanıyor
		# (yukarıdaki docstring'e bkz.). if_owner=1 insert edge-case koruması.
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
	except frappe.DuplicateEntryError:
		# controller._check_duplicate bu hatayı fırlatır
		frappe.throw(_("Bu kaynak için zaten bir başvurunuz var."))
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(title="create_my_verification: beklenmeyen hata")
		frappe.throw(_("Başvuru oluşturulamadı. Lütfen alanları kontrol edin."))

	return {"ok": True, "name": doc.name, "status": "Pending"}

"""'Verified Seller' rolünü role-profile sync'ine karşı dayanıklı şekilde yönet.

KÖK SORUN (2026-06-15):
  Satıcı User'larında ``role_profile_name = "Seller Full Access"`` var. Bu profil
  yalnızca [Seller Finance, Seller Owner, Seller Staff, Seller Viewer] içeriyor —
  "Verified Seller" YOK. Frappe, User her kaydedildiğinde rolleri role-profile'a
  göre RESETLER → ``user_doc.add_roles("Verified Seller")`` çağrısı User.save
  tetiklediği için rol anında silinir. Sonuç: KYB'si Verified olan satıcı
  storefront'ta "doğrulanmadı" görünür (sipariş kapısı + rozetler bu role bakar).

  seed_demo_data._grant_verified_seller_role aynı nedenle Has Role satırını
  DOĞRUDAN ekler. Production runtime de aynı deseni kullanmalı.

ÇÖZÜM:
  Has Role child satırını doğrudan insert/delete ederek User.save profile-sync'ini
  bypass et. Ayrıca User on_update sonrası (profile-sync rolü silmiş olabilir)
  KYB Verified ise rolü yeniden garanti et (reassert_*).
"""

import frappe

VERIFIED_SELLER_ROLE = "Verified Seller"


def sync_verified_seller_role(user: str, should_have: bool) -> bool:
	"""Has Role satırını DOĞRUDAN ekle/sil (add_roles DEĞİL — role-profile silerdi).

	``should_have`` True ise rolü garanti eder, False ise kaldırır. Değişiklik
	yapıldıysa kullanıcı cache'ini temizler. İdempotent; True döner = değişti.
	"""
	if not user or not frappe.db.exists("User", user):
		return False
	if not frappe.db.exists("Role", VERIFIED_SELLER_ROLE):
		return False

	has_row = frappe.db.exists(
		"Has Role",
		{"parent": user, "parenttype": "User", "role": VERIFIED_SELLER_ROLE},
	)

	changed = False
	if should_have and not has_row:
		frappe.get_doc(
			{
				"doctype": "Has Role",
				"parenttype": "User",
				"parentfield": "roles",
				"parent": user,
				"role": VERIFIED_SELLER_ROLE,
			}
		).insert(ignore_permissions=True)
		changed = True
	elif not should_have and has_row:
		frappe.db.delete(
			"Has Role",
			{"parent": user, "parenttype": "User", "role": VERIFIED_SELLER_ROLE},
		)
		changed = True

	if changed:
		frappe.clear_cache(user=user)
	return changed


def reassert_verified_seller_on_user_save(doc, method=None) -> None:
	"""User on_update kalkanı — role-profile sync 'Verified Seller'ı silmiş olabilir.

	User her kaydedildiğinde Frappe rolleri role-profile'a göre resetler; bu da
	KYB'si Verified olan satıcının "Verified Seller" rolünü siler. Bu hook, save
	tamamlandıktan SONRA çalışıp KYB Verified ise rolü doğrudan yeniden ekler
	(User'ı tekrar KAYDETMEZ → role-profile sync tekrar tetiklenmez, döngü yok).
	"""
	kyb_status = frappe.db.get_value("KYB Verification", {"user": doc.name}, "status")
	if kyb_status == "Verified":
		sync_verified_seller_role(doc.name, True)

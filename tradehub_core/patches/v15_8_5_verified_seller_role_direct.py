"""FAZ 8.5 — KYB Verified satıcılara 'Verified Seller' rolünü DOĞRUDAN ekle.

Sorun:
  KYB'si "Verified" olan satıcılar storefront'ta "doğrulanmadı" görünüyordu.
  Kök neden: _sync_verified_seller_role ve eski assign_verified_seller_role
  patch'i `user_doc.add_roles("Verified Seller")` kullanıyordu; satıcı
  User'larındaki role_profile_name="Seller Full Access" User.save'de rolleri
  profile'a göre resetleyip "Verified Seller"ı siliyordu → rol hiç kalıcı olmadı.
  (assign_verified_seller_role patch'i de bu yüzden ETKİSİZDİ.)

Çözüm:
  status="Verified" olan tüm KYB Verification kayıtlarının user'larına
  "Verified Seller" rolünü Has Role satırı olarak DOĞRUDAN ekle
  (utils.verified_seller.sync_verified_seller_role — profile-sync bypass).
  Runtime artık aynı yöntemi kullanıyor; bu patch mevcut bozuk veriyi iyileştirir.
  İdempotent: rol zaten varsa atlar.
"""

from __future__ import annotations

import frappe

from tradehub_core.utils.verified_seller import sync_verified_seller_role


def execute() -> dict:
	if not frappe.db.exists("DocType", "KYB Verification"):
		return {"skipped": "no_doctype"}

	verified_users = frappe.get_all(
		"KYB Verification",
		filters={"status": "Verified"},
		pluck="user",
	)

	fixed = 0
	for user in verified_users:
		if user and sync_verified_seller_role(user, True):
			fixed += 1

	frappe.db.commit()
	frappe.logger().info(
		f"v15_8_5 Verified Seller rolü eklendi: {fixed}/{len(verified_users)}"
	)
	return {"fixed": fixed, "total_verified": len(verified_users)}

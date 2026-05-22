# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 2.5 — Order ↔ Approval Rule entegrasyonu (doc_event hook'u).

Order.after_insert hook'unda:
  1. Buyer'ın bağlı olduğu Organization belirlenir
  2. approval_workflow.find_matching_rule çağrılır
  3. Eşleşen rule varsa Order Approval instance oluşturulur
  4. Order.status "Onaylanıyor" yapılır

Hata davranışı: rule bulunamazsa veya rule match etmezse Order normal akışına
devam eder (best-effort). Hata olursa log_error yazılır, Order save bozulmaz.

Detay: docs/yetki/faz-2/03-faz-2-detayli-plan.md §2.5
"""

from __future__ import annotations

import frappe

from tradehub_core.services import approval_workflow


def on_order_after_insert(doc, method=None) -> None:
	"""Order create edildikten sonra approval workflow'unu başlat (best-effort).

	System Manager veya Administrator tarafından oluşturulan order'lar için
	approval skip edilir (admin operasyon). HOTFIX-6: skip durumu artık
	Permission Override Log'a HIGH severity ile yazılır — admin'in alıcı yerine
	order açma senaryosu forensics'te görünür.
	"""
	try:
		user = frappe.session.user
		roles = set(frappe.get_roles(user))
		buyer = doc.buyer

		if "System Manager" in roles or user == "Administrator":
			# Admin oluşturuyor — approval skip, ama audit'lensin
			_log_admin_bypass(doc, user, buyer)
			return

		if not buyer:
			return

		organization = frappe.db.get_value("User", buyer, "tradehub_parent_organization")
		if not organization:
			# Bireysel buyer — onay zinciri yok
			return

		# Kategori bilgisi (Faz 2.5'te basit — order'da kategori yoksa None)
		category = None  # Faz 3'te order line item'larından çıkarılabilir

		supplier = doc.seller_profile

		# Eşleşen rule var mı?
		rule_name = approval_workflow.find_matching_rule(
			organization=organization,
			amount=float(doc.total or 0),
			category=category,
			supplier=supplier,
		)

		if not rule_name:
			# Eşleşme yok — onay gerekmiyor (limit altı veya rule tanımlı değil)
			return

		# Order Approval başlat
		approval_name = approval_workflow.start_approval(doc.name, rule_name)

		# Order status'u "Onaylanıyor" yap
		doc.db_set("status", "Onaylanıyor")

		frappe.logger().info(
			f"Order {doc.name}: approval workflow başlatıldı (rule={rule_name}, "
			f"approval={approval_name})"
		)
	except Exception as exc:
		frappe.log_error(
			f"Order approval workflow başlatılamadı: order={doc.name}: {exc}",
			"order_approval_hooks",
		)


def _log_admin_bypass(order_doc, admin_user: str, buyer: str | None) -> None:
	"""System Manager order create ettiğinde approval workflow bypass'ı audit'le.

	Eğer admin **kendi** order'ını açıyorsa (test/own purchase) bypass beklenir.
	Eğer admin **başka bir buyer adına** order açıyorsa (impersonation) bu
	HIGH severity override — DPO/Compliance Officer incelemesi gerekir.
	"""
	try:
		from tradehub_core.audit import log_override

		is_impersonation = buyer and buyer != admin_user
		severity = "HIGH" if is_impersonation else "LOW"
		justification = (
			f"Order {order_doc.name} created by admin {admin_user} on behalf of buyer {buyer}"
			if is_impersonation
			else f"Order {order_doc.name} created by admin {admin_user} (own purchase)"
		)

		log_override(
			target_object=f"Order/{order_doc.name}",
			override_action="order.create.approval_bypass",
			justification=justification,
			admin_user=admin_user,
			original_decision="ALLOW",
			final_decision="ALLOW",
			severity=severity,
		)
	except Exception as exc:
		frappe.log_error(f"_log_admin_bypass failed: {exc}", "order_approval_hooks")

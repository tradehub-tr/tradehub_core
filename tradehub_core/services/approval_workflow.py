# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 2.5 — Çok katmanlı onay zinciri workflow servisi.

Public API:
  - find_matching_rule(organization, amount, category=None, supplier=None) → ApprovalRule | None
  - start_approval(order_doc, rule) → OrderApproval
  - approve(approval, user, comment=None) → OrderApproval (next state)
  - reject(approval, user, reason) → OrderApproval (Rejected)
  - get_pending_approvers(approval) → list[str]

State machine geçişleri:
  L1 onayladı + max_level=1 → Approved (terminal)
  L1 onayladı + max_level=2 → Pending L2
  L2 onayladı → Approved (terminal)
  L1 veya L2 reject → Rejected (terminal)

Bildirim: Frappe sendmail + Platform Notification (mevcut doctype).
ReBAC tuple: approve/reject sırasında Order Approval üzerine
`(order_approval, can_approve_l1/l2, user)` tuple'ları yazılır → ReBAC
list-objects ile "Demet kaç order onaylayabilir?" tek sorguda dönebilir.

Detay: docs/yetki/faz-2/01-tasarim-kararlari.md §6, model.fga
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime

# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------


def find_matching_rule(
	organization: str,
	amount: float,
	category: str | None = None,
	supplier: str | None = None,
) -> str | None:
	"""Verilen organization + amount + opsiyonel filtreler için en uygun rule.

	Algoritma:
	  1. Org match (organization veya parent_org zinciri)
	  2. Amount aralığı match (min_amount <= amount < max_amount)
	  3. Category filter match (rule.category_filter boş veya category eşit)
	  4. Supplier filter match (aynı)
	  5. is_active=1
	  6. Birden fazla rule eşleşirse priority küçük olan kazanır

	Returns:
	    Approval Rule name, eşleşme yoksa None.
	"""
	if not organization or amount is None:
		return None

	# Organization + ancestors (parent_org zincirinde tanımlı kural varsa kalıtır)
	from tradehub_core.utils.organization_hierarchy import get_ancestors

	org_set = [organization, *get_ancestors(organization)]

	# Önce direkt match
	rules = frappe.get_all(
		"Approval Rule",
		filters={
			"organization": ["in", org_set],
			"is_active": 1,
		},
		fields=[
			"name",
			"organization",
			"min_amount",
			"max_amount",
			"category_filter",
			"supplier_filter",
			"priority",
		],
		order_by="priority asc, min_amount desc",
	)

	for rule in rules:
		# Amount aralığı
		if amount < (rule.get("min_amount") or 0):
			continue
		if rule.get("max_amount") and amount >= rule.get("max_amount"):
			continue

		# Category filter
		if rule.get("category_filter") and rule["category_filter"] != category:
			continue

		# Supplier filter
		if rule.get("supplier_filter") and rule["supplier_filter"] != supplier:
			continue

		return rule["name"]

	return None


# ---------------------------------------------------------------------------
# Workflow actions
# ---------------------------------------------------------------------------


def start_approval(order_name: str, rule_name: str) -> str:
	"""Order + Rule için yeni Order Approval instance oluştur.

	Args:
	    order_name: Order doctype name
	    rule_name: Approval Rule name

	Returns:
	    Order Approval name

	Race protection: aynı order için iki paralel hook → row-level lock ile
	tek bir Order Approval oluşturulur. İkinci çağrı mevcut record'u döner.
	"""
	order = frappe.get_doc("Order", order_name)
	rule = frappe.get_doc("Approval Rule", rule_name)

	# FOR UPDATE lock — aynı order için paralel çağrılar serileşir
	existing_rows = frappe.db.sql(
		"""
		SELECT name FROM `tabOrder Approval`
		WHERE `order` = %s AND status IN ('Pending L1', 'Approved L1', 'Pending L2')
		FOR UPDATE
		""",
		(order_name,),
		as_dict=True,
	)
	if existing_rows:
		return existing_rows[0]["name"]

	# Requisitioner = order.owner
	requisitioner = order.owner

	# Organization = buyer'ın tradehub_parent_organization
	organization = (
		frappe.db.get_value("User", order.buyer or "", "tradehub_parent_organization") or rule.organization
	)

	# expires_at = +N gün
	timeout_days = rule.get("approval_timeout_days") or 7
	expires_at = add_days(now_datetime(), timeout_days)

	approval = frappe.get_doc(
		{
			"doctype": "Order Approval",
			"order": order_name,
			"approval_rule": rule_name,
			"organization": organization,
			"status": "Pending L1",
			"current_level": 1,
			"max_level": rule.max_level(),
			"amount": order.total,
			"currency": order.currency or rule.currency,
			"requisitioner": requisitioner,
			"started_at": now_datetime(),
			"expires_at": expires_at,
		}
	)
	approval.insert(ignore_permissions=True)

	# ReBAC tuple: approver_l1 chain → can_approve_l1 ilişkisi
	_sync_approval_tuples(approval, rule)

	# Bildirim: L1 approver'lara mail
	approvers = rule.get_approvers_at_level(1)
	_notify_approvers(approval, approvers, level=1)

	return approval.name


def approve(approval_name: str, user: str | None = None, comment: str = "") -> str:
	"""Bir approval'ı onayla — state machine ilerlet.

	Returns:
	    new status (Approved L1 / Pending L2 / Approved)

	Race protection: row-level lock ile iki paralel approve çağrısı serileşir.
	"""
	user = user or frappe.session.user

	# FOR UPDATE — paralel approve/reject çağrıları için lock
	locked = frappe.db.sql(
		"SELECT name, status, current_level, max_level FROM `tabOrder Approval` WHERE name = %s FOR UPDATE",
		(approval_name,),
		as_dict=True,
	)
	if not locked:
		frappe.throw(_("Order Approval bulunamadı: {0}").format(approval_name))

	approval = frappe.get_doc("Order Approval", approval_name)

	if approval.is_terminal():
		frappe.throw(_("Bu onay zaten tamamlanmış."))

	# Caller yetkili mi?
	rule = frappe.get_doc("Approval Rule", approval.approval_rule)
	current_level = approval.current_level
	allowed_approvers = rule.get_approvers_at_level(current_level)

	roles = set(frappe.get_roles(user))
	is_admin_override = user not in allowed_approvers and "System Manager" in roles
	if user not in allowed_approvers and not is_admin_override:
		frappe.throw(
			_("Bu siparişi onaylama yetkiniz yok. Level {0} approver'ları: {1}").format(
				current_level, ", ".join(allowed_approvers)
			),
			frappe.PermissionError,
		)

	# Log ekle
	approval.append(
		"approval_log",
		{
			"timestamp": now_datetime(),
			"approver": user,
			"action": "approved",
			"level": current_level,
			"comment": comment,
		},
	)

	# State ilerlet (single save — ara state save kaldırıldı, race window önlendi)
	max_level = approval.max_level
	if current_level == 1 and max_level == 1:
		approval.status = "Approved"
		approval.finalized_at = now_datetime()
	elif current_level == 1 and max_level == 2:
		approval.status = "Pending L2"
		approval.current_level = 2
	elif current_level == 2:
		approval.status = "Approved"
		approval.finalized_at = now_datetime()

	approval.save(ignore_permissions=True)

	# Admin bypass'ı log_override ile audit'le
	if is_admin_override:
		_log_admin_override(approval, user, "approve", current_level)

	# L1'den L2'ye geçişte L2 approver'lara bildirim
	if approval.status == "Pending L2":
		l2_approvers = rule.get_approvers_at_level(2)
		_notify_approvers(approval, l2_approvers, level=2)

	# Approve sonrası order status update
	if approval.status == "Approved":
		_sync_order_after_approval(approval, approved=True)

	# ReBAC audit log
	_log_approval_decision(approval, user, "approved", current_level)

	frappe.db.commit()
	return approval.status


def reject(approval_name: str, user: str | None = None, reason: str = "") -> str:
	"""Bir approval'ı reddet — terminal state. Race-protected (FOR UPDATE)."""
	user = user or frappe.session.user

	locked = frappe.db.sql(
		"SELECT name FROM `tabOrder Approval` WHERE name = %s FOR UPDATE",
		(approval_name,),
		as_dict=True,
	)
	if not locked:
		frappe.throw(_("Order Approval bulunamadı: {0}").format(approval_name))

	approval = frappe.get_doc("Order Approval", approval_name)

	if approval.is_terminal():
		frappe.throw(_("Bu onay zaten tamamlanmış."))

	# Caller yetkili mi?
	rule = frappe.get_doc("Approval Rule", approval.approval_rule)
	allowed_approvers = rule.get_approvers_at_level(approval.current_level)
	roles = set(frappe.get_roles(user))
	is_admin_override = user not in allowed_approvers and "System Manager" in roles
	if user not in allowed_approvers and not is_admin_override:
		frappe.throw(_("Bu siparişi reddetme yetkiniz yok."), frappe.PermissionError)

	if not reason or not reason.strip():
		frappe.throw(_("Reddetme nedeni zorunludur."))

	approval.append(
		"approval_log",
		{
			"timestamp": now_datetime(),
			"approver": user,
			"action": "rejected",
			"level": approval.current_level,
			"comment": reason,
		},
	)
	approval.status = "Rejected"
	approval.finalized_at = now_datetime()
	approval.rejection_reason = reason
	approval.save(ignore_permissions=True)

	if is_admin_override:
		_log_admin_override(approval, user, "reject", approval.current_level, reason=reason)

	_sync_order_after_approval(approval, approved=False)
	_log_approval_decision(approval, user, "rejected", approval.current_level, reason=reason)

	frappe.db.commit()
	return approval.status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sync_approval_tuples(approval, rule) -> None:
	"""Order Approval için ReBAC tuple'ları yaz.

	FAZ 2.6 — L1 ve L2 approver tuple'ları ABAC condition ile yazılır:
	  - L1 → condition `needs_approval_l1` (amount > 500 && <= 5000)
	  - L2 → condition `needs_approval_l2` (amount > 5000)

	HOTFIX-5 (Faz 3.6 post-audit):
	  Approval tuple'ları **senkron** yazılır. Eski async davranış ~5sn
	  eventual consistency penceresi bırakıyordu — bu pencerede approver
	  hemen tıklarsa `can_approve_l1` ReBAC check fail-closed semantiği
	  yüzünden DENY veriyordu.

	  Sync write fail olursa: en az 1 ADL kaydı + caller tarafa exception
	  fırlatılmaz (best-effort), ama approval workflow başlamış sayılır.
	  Drift detection job daily olarak eksik tuple'ları yakalar.
	"""
	from tradehub_core.services import rebac_client

	oa_obj = f"order_approval:{approval.name}"
	order_obj = f"order:{approval.order}"
	tuples: list = [(oa_obj, "target_order", order_obj)]

	try:
		# L1 — condition'lı tuple (4-tuple: user, relation, object, condition_name)
		for user in rule.get_approvers_at_level(1):
			tuples.append((f"user:{user}", "can_approve_l1", oa_obj, "needs_approval_l1"))
		for user in rule.get_approvers_at_level(2):
			tuples.append((f"user:{user}", "can_approve_l2", oa_obj, "needs_approval_l2"))
	except Exception as exc:
		frappe.log_error(f"approval tuple list build hatası: {exc}", "approval_workflow")
		return

	# Sync write — fail durumunda audit log üret, akışı kırma
	try:
		rebac_client.write_tuples(tuples)
	except Exception as exc:
		frappe.log_error(f"approval tuple sync write hatası: {exc}", "approval_workflow")
		_log_tuple_sync_failure(approval.name, tuples, str(exc))


def _log_tuple_sync_failure(approval_name: str, tuples: list, error: str) -> None:
	"""Tuple sync fail olduğunda HIGH severity audit — drift detection yakalar."""
	try:
		from tradehub_core.audit import log_decision

		log_decision(
			actor=frappe.session.user or "System",
			action="approval.tuple_sync",
			decision="ERROR",
			rule_id="approval.tuple_sync_failure",
			layer="L2",
			object_doctype="Order Approval",
			object_name=approval_name,
			severity="HIGH",
			context={
				"error": error,
				"tuple_count": len(tuples),
			},
		)
	except Exception:
		pass


def _notify_approvers(approval, approvers: list[str], level: int) -> None:
	"""Approver'lara mail + Platform Notification."""
	if not approvers:
		return

	subject = _("[TradeHub] Onay bekleyen sipariş: {0} ({1} {2})").format(
		approval.order, approval.amount, approval.currency
	)
	message = _(
		"""Onay bekleyen yeni bir sipariş var:

  Order:    {order}
  Tutar:    {amount} {currency}
  Açan:     {requisitioner}
  Seviye:   {level}
  Son onay: {expires_at}

Onaylamak veya reddetmek için admin paneline gidin:
  /panel/approval-queue
"""
	).format(
		order=approval.order,
		amount=approval.amount,
		currency=approval.currency,
		requisitioner=approval.requisitioner,
		level=level,
		expires_at=approval.expires_at,
	)

	try:
		frappe.sendmail(recipients=approvers, subject=subject, message=message, now=False)
	except Exception as exc:
		frappe.log_error(f"approval notify mail hatası: {exc}", "approval_workflow")

	# Platform Notification (her approver için)
	for user in approvers:
		try:
			frappe.get_doc(
				{
					"doctype": "Platform Notification",
					"user": user,
					"title": subject,
					"message": _("Onay bekleyen sipariş: {0}").format(approval.order),
					"link": f"/panel/approval-queue?id={approval.name}",
				}
			).insert(ignore_permissions=True)
		except Exception:
			# Platform Notification yoksa veya field mismatch → skip
			pass


def _sync_order_after_approval(approval, approved: bool) -> None:
	"""Approval terminal olduktan sonra Order.status güncelle."""
	try:
		order = frappe.get_doc("Order", approval.order)
		if approved:
			# Mevcut Order.status değerleri: "Ödeme Bekleniyor / Onaylanıyor / Kargoda / ..."
			# Approval geçince order "Ödeme Bekleniyor"a düşer (sipariş hazır)
			order.status = "Ödeme Bekleniyor"
		else:
			order.status = "İptal Edildi"
		order.save(ignore_permissions=True)
	except Exception as exc:
		frappe.log_error(f"order status sync hatası: {exc}", "approval_workflow")


def _log_approval_decision(approval, user: str, action: str, level: int, reason: str = "") -> None:
	"""Audit log."""
	try:
		from tradehub_core.audit import log_decision

		log_decision(
			actor=user,
			action=f"order_approval.{action}.l{level}",
			decision="ALLOW" if action == "approved" else "DENY",
			rule_id=f"approval.workflow.l{level}",
			layer="L2",
			object_doctype="Order Approval",
			object_name=approval.name,
			severity="NORMAL",
			context={
				"order": approval.order,
				"amount": float(approval.amount or 0),
				"currency": approval.currency,
				"reason": reason if reason else None,
			},
		)
	except Exception:
		pass


def _log_admin_override(approval, admin_user: str, action: str, level: int, reason: str = "") -> None:
	"""System Manager bypass — Permission Override Log'a HIGH severity kayıt.

	`approve()`/`reject()` içindeki "user not in allowed_approvers but is System Manager"
	durumunda çağrılır. Approval'ı atlayan admin override audit trail'i.
	"""
	try:
		from tradehub_core.audit import log_override

		justification = (
			reason.strip()
			if reason
			else _("Admin override — level {0} {1} action (otomatik audit)").format(level, action)
		)

		log_override(
			target_object=f"Order Approval/{approval.name}",
			override_action=f"approval.{action}.admin_bypass",
			justification=justification,
			admin_user=admin_user,
			original_decision="DENY",
			final_decision="ALLOW" if action == "approve" else "DENY",
			severity="HIGH",
		)
	except Exception as exc:
		frappe.log_error(f"_log_admin_override failed: {exc}", "approval_workflow")

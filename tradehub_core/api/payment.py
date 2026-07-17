import frappe
from frappe import _
from frappe.utils import now_datetime

from tradehub_core.api._pagination import normalize_pagination

# Türkçe (DB) → İngilizce (Frontend) transaction status mapping
TX_STATUS_TR_TO_EN = {
	"Gönderildi": "Sent",
	"Beklemede": "Pending",
	"Tedarikçi Eşleşmesi Bekleniyor": "Pending Supplier Match",
	"Eşleşti": "Matched",
	"Tamamlandı": "Completed",
	"Reddedildi": "Rejected",
}

TX_STATUS_COLORS = {
	"Sent": "text-blue-600",
	"Pending": "text-amber-600",
	"Pending Supplier Match": "text-orange-600",
	"Matched": "text-green-600",
	"Completed": "text-gray-500",
	"Rejected": "text-red-600",
}

# Frontend filter key → Türkçe DB values
TX_FILTER_STATUS_MAP = {
	"not_arrived": ["Gönderildi", "Beklemede"],
	"pending_match": ["Tedarikçi Eşleşmesi Bekleniyor"],
	"completed": ["Eşleşti", "Tamamlandı"],
}

MATCH_STATUS_TR_TO_EN = {
	"Beklemede": "Pending",
	"Kısmi Eşleşme": "Partial Match",
	"Tam Eşleşme": "Full Match",
}

MATCH_FILTER_MAP = {
	"pending": ["Beklemede"],
	"matched": ["Kısmi Eşleşme", "Tam Eşleşme"],
}


def _require_buyer():
	"""Ensure user is logged in and return user email."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("You must be logged in"), frappe.AuthenticationError)
	return user


def _backfill_missing_transactions_for_buyer(buyer):
	"""Alıcının havale yaptığı ama Payment Transaction kaydı oluşmamış
	siparişler için eksik kayıtları oluşturur. Idempotent."""
	# ignore_permissions: backfill sistem işlemi — buyer zaten _require_buyer() ile doğrulanmış,
	# Order doctype'ın permission_query_conditions'ı buyer filtresi uyguluyor ama
	# burada ek status filtreleri nedeniyle get_list perm check'i gereksiz yük olur.
	orders = frappe.get_list(
		"Order",
		filters={"buyer": buyer, "remittance_amount": [">", 0]},
		fields=[
			"name",
			"seller",
			"currency",
			"remittance_date",
			"remittance_amount",
			"remittance_sender",
			"receipt_url",
			"status",
		],
		ignore_permissions=True,
	)

	created = 0
	for order in orders:
		# Idempotency: aynı order+type kombinasyonu için zaten transaction varsa atla.
		# Race condition notu: concurrent çağrılarda duplicate mümkün ama
		# create_payment_transaction içindeki DuplicateEntryError catch ile korunur.
		if frappe.db.exists(
			"Payment Transaction",
			{"order": order.name, "transaction_type": "Ödeme"},
		):
			continue

		tx_status = "Gönderildi"
		if order.status in ("Onaylanıyor", "Kargoda", "Tamamlandı"):
			tx_status = "Tamamlandı"

		try:
			create_payment_transaction(
				order_name=order.name,
				buyer=buyer,
				transaction_type="Ödeme",
				amount=float(order.remittance_amount or 0),
				currency=order.currency or "TRY",
				payment_method="Banka Havalesi",
				remittance_sender=order.remittance_sender or "",
				receipt_url=order.receipt_url or "",
				status=tx_status,
			)
			if order.seller:
				upsert_bank_interaction(
					buyer,
					order.seller,
					float(order.remittance_amount or 0),
					order.currency or "TRY",
				)
			created += 1
		except Exception:
			frappe.log_error(
				f"Backfill Payment Transaction failed for order {order.name}",
				"payment_backfill",
			)

	if created:
		frappe.db.commit()


def _translate_transaction(tx):
	"""Transaction dict'indeki Türkçe alanları İngilizce'ye çevir."""
	tr_status = tx.get("status", "")
	en_status = TX_STATUS_TR_TO_EN.get(tr_status, tr_status)
	tx["status_en"] = en_status
	tx["status_color"] = TX_STATUS_COLORS.get(en_status, "text-gray-500")
	tx["amount"] = float(tx.get("amount") or 0)
	tx["transaction_fee"] = float(tx.get("transaction_fee") or 0)
	tx["transaction_type_en"] = "Payment" if tx.get("transaction_type") == "Ödeme" else "Refund"
	return tx


# ---------------------------------------------------------------------------
# Section 1: Ödeme Yönetimi (#payment-management)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_recent_payments(page=1, page_size=10):
	"""Returns recent payment transactions for the logged-in buyer."""
	buyer = _require_buyer()
	_backfill_missing_transactions_for_buyer(buyer)
	page, page_size, _ = normalize_pagination(page, page_size, default_page_size=10, max_page_size=50)

	filters = {"buyer": buyer, "transaction_type": "Ödeme"}

	total = frappe.db.count("Payment Transaction", filters=filters)

	# ignore_permissions: buyer filtresi zaten uygulanmış — kendi transaction'larını görür.
	# Payment Transaction doctype'ın perm check'i ek maliyet; buyer=session.user ile izole.
	transactions = frappe.get_list(
		"Payment Transaction",
		filters=filters,
		fields=[
			"name",
			"transaction_type",
			"order",
			"seller_name",
			"payment_method",
			"amount",
			"currency",
			"transaction_fee",
			"transaction_date",
			"status",
			"reference_number",
			"receipt_url",
		],
		order_by="transaction_date desc",
		start=(page - 1) * page_size,
		page_length=page_size,
		ignore_permissions=True,
	)

	for tx in transactions:
		_translate_transaction(tx)

	return {
		"success": True,
		"payments": transactions,
		"total": total,
		"page": page,
		"page_size": page_size,
	}


@frappe.whitelist()
def get_recent_refunds(page=1, page_size=10):
	"""Returns recent refund transactions for the logged-in buyer."""
	buyer = _require_buyer()
	page, page_size, _ = normalize_pagination(page, page_size, default_page_size=10, max_page_size=50)

	filters = {"buyer": buyer, "transaction_type": "İade"}

	total = frappe.db.count("Payment Transaction", filters=filters)

	transactions = frappe.get_list(
		"Payment Transaction",
		filters=filters,
		fields=[
			"name",
			"transaction_type",
			"order",
			"seller_name",
			"payment_method",
			"amount",
			"currency",
			"transaction_fee",
			"transaction_date",
			"status",
			"reference_number",
			"refund_reason",
		],
		order_by="transaction_date desc",
		start=(page - 1) * page_size,
		page_length=page_size,
		ignore_permissions=True,
	)

	for tx in transactions:
		_translate_transaction(tx)

	return {
		"success": True,
		"refunds": transactions,
		"total": total,
		"page": page,
		"page_size": page_size,
	}


# ---------------------------------------------------------------------------
# Section 2: İşlemler (#transactions)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_all_transactions(
	transaction_type=None,
	status=None,
	date_from=None,
	date_to=None,
	amount_min=None,
	amount_max=None,
	currency=None,
	page=1,
	page_size=20,
):
	"""Full transaction history with filtering."""
	buyer = _require_buyer()
	_backfill_missing_transactions_for_buyer(buyer)
	page, page_size, _ = normalize_pagination(page, page_size)

	filters = {"buyer": buyer}

	if transaction_type == "payment":
		filters["transaction_type"] = "Ödeme"
	elif transaction_type == "refund":
		filters["transaction_type"] = "İade"

	if status and status != "all":
		tr_statuses = TX_FILTER_STATUS_MAP.get(status)
		if tr_statuses:
			filters["status"] = ["in", tr_statuses]

	if currency:
		filters["currency"] = currency

	if date_from and date_to:
		filters["transaction_date"] = ["between", [date_from, date_to]]
	elif date_from:
		filters["transaction_date"] = [">=", date_from]
	elif date_to:
		filters["transaction_date"] = ["<=", date_to]

	if amount_min:
		filters["amount"] = [">=", float(amount_min)]
	if amount_max:
		if "amount" in filters:
			filters["amount"] = ["between", [float(amount_min or 0), float(amount_max)]]
		else:
			filters["amount"] = ["<=", float(amount_max)]

	total = frappe.db.count("Payment Transaction", filters=filters)

	transactions = frappe.get_list(
		"Payment Transaction",
		filters=filters,
		fields=[
			"name",
			"transaction_type",
			"order",
			"seller_name",
			"payment_method",
			"amount",
			"currency",
			"transaction_fee",
			"transaction_date",
			"status",
			"reference_number",
			"receipt_url",
			"refund_reason",
		],
		order_by="transaction_date desc",
		start=(page - 1) * page_size,
		page_length=page_size,
		ignore_permissions=True,
	)

	for tx in transactions:
		_translate_transaction(tx)

	return {
		"success": True,
		"transactions": transactions,
		"total": total,
		"page": page,
		"page_size": page_size,
	}


@frappe.whitelist()
def export_transactions(transaction_type=None, status=None, date_from=None, date_to=None, currency=None):
	"""Export transaction data as CSV. Returns file URL for download."""
	import csv
	import io

	buyer = _require_buyer()

	filters = {"buyer": buyer}
	if transaction_type == "payment":
		filters["transaction_type"] = "Ödeme"
	elif transaction_type == "refund":
		filters["transaction_type"] = "İade"
	if status and status != "all":
		tr_statuses = TX_FILTER_STATUS_MAP.get(status)
		if tr_statuses:
			filters["status"] = ["in", tr_statuses]
	if currency:
		filters["currency"] = currency
	if date_from and date_to:
		filters["transaction_date"] = ["between", [date_from, date_to]]
	elif date_from:
		filters["transaction_date"] = [">=", date_from]
	elif date_to:
		filters["transaction_date"] = ["<=", date_to]

	transactions = frappe.get_list(
		"Payment Transaction",
		filters=filters,
		fields=[
			"name",
			"transaction_type",
			"order",
			"seller_name",
			"payment_method",
			"amount",
			"currency",
			"transaction_fee",
			"transaction_date",
			"status",
			"reference_number",
		],
		order_by="transaction_date desc",
		# M21 fix — sınırsız (page_length=0) döküm yerine makul cap; `buyer` filtresi
		# cross-tenant'ı zaten engelliyor, bu ek olarak filtre-regresyonunda toplu
		# sızıntı/DoS riskini sınırlar.
		page_length=10000,
		ignore_permissions=True,
	)

	output = io.StringIO()
	writer = csv.writer(output)
	writer.writerow(
		[
			"İşlem No",
			"Tip",
			"Sipariş",
			"Tedarikçi",
			"Ödeme Yöntemi",
			"Tutar",
			"Para Birimi",
			"İşlem Ücreti",
			"Tarih",
			"Durum",
			"Referans No",
		]
	)

	for tx in transactions:
		_translate_transaction(tx)
		writer.writerow(
			[
				tx["name"],
				tx["transaction_type_en"],
				tx["order"],
				tx["seller_name"],
				tx.get("payment_method", ""),
				tx["amount"],
				tx.get("currency", "TRY"),
				tx["transaction_fee"],
				str(tx.get("transaction_date", ""))[:19],
				tx["status_en"],
				tx.get("reference_number", ""),
			]
		)

	csv_content = output.getvalue()
	output.close()

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"transactions-{buyer}-{frappe.utils.today()}.csv",
			"content": csv_content.encode("utf-8"),
			"is_private": 1,
		}
	)
	file_doc.flags.ignore_permissions = True
	file_doc.insert(ignore_permissions=True)

	return {"success": True, "file_url": file_doc.file_url}


# ---------------------------------------------------------------------------
# Section 3: Havale Hesapları (#tt-accounts)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_bank_interactions(match_status=None, search=None, date_from=None, date_to=None, page=1, page_size=20):
	"""Returns seller bank accounts the buyer has transacted with."""
	buyer = _require_buyer()
	_backfill_missing_transactions_for_buyer(buyer)
	page, page_size, _ = normalize_pagination(page, page_size)

	filters = {"buyer": buyer}

	if match_status and match_status != "all":
		tr_statuses = MATCH_FILTER_MAP.get(match_status)
		if tr_statuses:
			filters["match_status"] = ["in", tr_statuses]

	if date_from and date_to:
		filters["last_transaction_date"] = ["between", [date_from, date_to]]
	elif date_from:
		filters["last_transaction_date"] = [">=", date_from]
	elif date_to:
		filters["last_transaction_date"] = ["<=", date_to]

	total = frappe.db.count("Buyer Bank Interaction", filters=filters)

	interactions = frappe.get_list(
		"Buyer Bank Interaction",
		filters=filters,
		fields=[
			"name",
			"seller",
			"seller_name",
			"seller_iban",
			"seller_bank_name",
			"seller_account_holder",
			"total_wire_amount",
			"pending_match_amount",
			"currency",
			"last_transaction_date",
			"match_status",
			"is_verified",
		],
		order_by="last_transaction_date desc",
		start=(page - 1) * page_size,
		page_length=page_size,
		ignore_permissions=True,
	)

	if search:
		q = search.lower()
		interactions = [
			i
			for i in interactions
			if q in (i.get("seller_name") or "").lower() or q in (i.get("seller_iban") or "").lower()
		]

	for interaction in interactions:
		tr_match = interaction.get("match_status", "")
		interaction["match_status_en"] = MATCH_STATUS_TR_TO_EN.get(tr_match, tr_match)
		interaction["total_wire_amount"] = float(interaction.get("total_wire_amount") or 0)
		interaction["pending_match_amount"] = float(interaction.get("pending_match_amount") or 0)

	return {
		"success": True,
		"interactions": interactions,
		"total": total,
		"page": page,
		"page_size": page_size,
	}


@frappe.whitelist()
def get_bank_interaction_summary():
	"""Returns aggregate totals: total_wire_amount, pending_match_amount."""
	buyer = _require_buyer()

	result = frappe.db.sql(
		"""
        SELECT
            COALESCE(SUM(total_wire_amount), 0) as total_wire_amount,
            COALESCE(SUM(pending_match_amount), 0) as pending_match_amount
        FROM `tabBuyer Bank Interaction`
        WHERE buyer = %(buyer)s
    """,
		{"buyer": buyer},
		as_dict=True,
	)

	row = result[0] if result else {}

	return {
		"success": True,
		"total_wire_amount": float(row.get("total_wire_amount") or 0),
		"pending_match_amount": float(row.get("pending_match_amount") or 0),
	}


@frappe.whitelist()
def verify_supplier_account(iban):
	"""Verify if a supplier's bank account exists. Looks up by IBAN."""
	_require_buyer()

	if not iban:
		frappe.throw(_("IBAN alanı boş olamaz"))

	clean_iban = iban.replace(" ", "").upper()

	# H10 fix — banka PII enumerasyonu engeli. Eskiden herhangi bir alıcı IBAN deneyerek
	# tüm satıcıların seller_name/bank_name/account_holder bilgisini hasat edebiliyordu.
	# Artık yalnızca boolean `verified` dönülür; hiçbir PII döndürülmez.
	exists = frappe.db.exists("Admin Seller Profile", {"iban": clean_iban})
	if not exists:
		return {
			"success": True,
			"verified": False,
			"message": _("Bu IBAN ile kayıtlı bir tedarikçi bulunamadı."),
		}

	return {
		"success": True,
		"verified": True,
	}


# ---------------------------------------------------------------------------
# Section 4: Havale Takibi (#tt-tracking)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_wire_transfers(search=None, date_from=None, date_to=None, page=1, page_size=20):
	"""Returns wire transfers sent by the buyer."""
	buyer = _require_buyer()
	_backfill_missing_transactions_for_buyer(buyer)
	page, page_size, _ = normalize_pagination(page, page_size)

	filters = {
		"buyer": buyer,
		"transaction_type": "Ödeme",
		"payment_method": ["in", ["Banka Havalesi", "EFT/Havale"]],
	}

	if date_from and date_to:
		filters["transaction_date"] = ["between", [date_from, date_to]]
	elif date_from:
		filters["transaction_date"] = [">=", date_from]
	elif date_to:
		filters["transaction_date"] = ["<=", date_to]

	total = frappe.db.count("Payment Transaction", filters=filters)

	transfers = frappe.get_list(
		"Payment Transaction",
		filters=filters,
		fields=[
			"name",
			"order",
			"seller_name",
			"amount",
			"currency",
			"transaction_date",
			"status",
			"reference_number",
			"remittance_sender",
			"seller_bank_name",
			"seller_iban",
			"receipt_url",
		],
		order_by="transaction_date desc",
		start=(page - 1) * page_size,
		page_length=page_size,
		ignore_permissions=True,
	)

	if search:
		q = search.lower()
		transfers = [
			t
			for t in transfers
			if q in (t.get("reference_number") or "").lower() or q in (t.get("name") or "").lower()
		]

	for t in transfers:
		tr_status = t.get("status", "")
		t["status_en"] = TX_STATUS_TR_TO_EN.get(tr_status, tr_status)
		t["status_color"] = TX_STATUS_COLORS.get(t["status_en"], "text-gray-500")
		t["amount"] = float(t.get("amount") or 0)

	return {
		"success": True,
		"transfers": transfers,
		"total": total,
		"page": page,
		"page_size": page_size,
	}


@frappe.whitelist()
def get_wire_transfer_detail(transaction_name):
	"""Returns detailed info for a single wire transfer."""
	buyer = _require_buyer()

	tx = frappe.db.get_value(
		"Payment Transaction",
		{"name": transaction_name, "buyer": buyer},
		[
			"name",
			"transaction_type",
			"order",
			"buyer",
			"seller",
			"seller_name",
			"payment_method",
			"amount",
			"currency",
			"transaction_fee",
			"transaction_date",
			"status",
			"reference_number",
			"remittance_sender",
			"seller_bank_name",
			"seller_iban",
			"receipt_url",
			"confirmation_date",
			"confirmed_by",
			"refund_reason",
			"notes",
		],
		as_dict=True,
	)

	if not tx:
		frappe.throw(_("Transaction not found"), frappe.DoesNotExistError)

	_translate_transaction(tx)

	return {"success": True, "transaction": tx}


# ---------------------------------------------------------------------------
# Helper: Transaction + Bank Interaction oluşturma
# ---------------------------------------------------------------------------


def create_payment_transaction(
	order_name,
	buyer,
	transaction_type,
	amount,
	currency="TRY",
	payment_method="Banka Havalesi",
	reference_number="",
	remittance_sender="",
	receipt_url="",
	refund_reason="",
	status=None,
):
	"""Helper to create a Payment Transaction record.
	Called from order.py when remittance is submitted or refund requested.
	"""
	order = frappe.db.get_value(
		"Order",
		order_name,
		["seller", "currency"],
		as_dict=True,
	)

	seller_code = order.seller if order else ""
	seller_name = ""
	seller_bank_name = ""
	seller_iban = ""

	if seller_code:
		seller_info = frappe.db.get_value(
			"Admin Seller Profile",
			seller_code,
			["seller_name", "bank_name", "iban"],
			as_dict=True,
		)
		if seller_info:
			seller_name = seller_info.seller_name or ""
			seller_bank_name = seller_info.bank_name or ""
			seller_iban = seller_info.iban or ""

	if not status:
		status = "Beklemede" if transaction_type == "İade" else "Gönderildi"

	# Idempotency: aynı order + transaction_type + buyer için zaten kayıt varsa tekrar oluşturma
	existing_tx = frappe.db.get_value(
		"Payment Transaction",
		{"order": order_name, "transaction_type": transaction_type, "buyer": buyer},
		"name",
	)
	if existing_tx:
		return existing_tx

	tx = frappe.new_doc("Payment Transaction")
	tx.transaction_type = transaction_type
	tx.order = order_name
	tx.buyer = buyer
	tx.seller = seller_code
	tx.seller_name = seller_name
	tx.payment_method = payment_method
	tx.amount = float(amount)
	tx.currency = currency or (order.currency if order else "TRY")
	tx.transaction_date = now_datetime()
	tx.status = status
	tx.reference_number = reference_number
	tx.remittance_sender = remittance_sender
	tx.seller_bank_name = seller_bank_name
	tx.seller_iban = seller_iban
	tx.receipt_url = receipt_url
	tx.refund_reason = refund_reason
	tx.flags.ignore_permissions = True
	try:
		tx.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		# Race condition: başka bir request arada oluşturmuş
		frappe.db.rollback()
		return frappe.db.get_value(
			"Payment Transaction",
			{"order": order_name, "transaction_type": transaction_type, "buyer": buyer},
			"name",
		)

	return tx.name


def update_transaction_status(order_name, buyer, new_status, transaction_type="Ödeme", confirmed_by=None):
	"""Helper to update the most recent transaction status for an order."""
	tx_name = frappe.db.get_value(
		"Payment Transaction",
		{"order": order_name, "buyer": buyer, "transaction_type": transaction_type},
		"name",
		order_by="transaction_date desc",
	)

	if tx_name:
		update_fields = {"status": new_status}
		if confirmed_by:
			update_fields["confirmed_by"] = confirmed_by
			update_fields["confirmation_date"] = now_datetime()
		frappe.db.set_value("Payment Transaction", tx_name, update_fields)


def upsert_bank_interaction(buyer, seller_code, amount, currency="TRY"):
	"""Create or update a Buyer Bank Interaction record when payment is made."""
	seller_info = frappe.db.get_value(
		"Admin Seller Profile",
		seller_code,
		["seller_name", "bank_name", "iban", "account_holder"],
		as_dict=True,
	)
	if not seller_info:
		return

	existing = frappe.db.get_value(
		"Buyer Bank Interaction",
		{"buyer": buyer, "seller": seller_code},
		"name",
	)

	if existing:
		# Atomik UPDATE — race condition'da concurrent worker'lar doğru toplam hesaplar
		frappe.db.sql(
			"""UPDATE `tabBuyer Bank Interaction`
			   SET total_wire_amount = COALESCE(total_wire_amount, 0) + %s,
			       pending_match_amount = COALESCE(pending_match_amount, 0) + %s,
			       last_transaction_date = %s,
			       seller_iban = %s,
			       seller_bank_name = %s,
			       seller_account_holder = %s
			   WHERE name = %s""",
			(
				float(amount),
				float(amount),
				now_datetime(),
				seller_info.iban or "",
				seller_info.bank_name or "",
				seller_info.account_holder or "",
				existing,
			),
		)
	else:
		bi = frappe.new_doc("Buyer Bank Interaction")
		bi.buyer = buyer
		bi.seller = seller_code
		bi.seller_name = seller_info.seller_name or ""
		bi.seller_iban = seller_info.iban or ""
		bi.seller_bank_name = seller_info.bank_name or ""
		bi.seller_account_holder = seller_info.account_holder or ""
		bi.total_wire_amount = float(amount)
		bi.pending_match_amount = float(amount)
		bi.currency = currency
		bi.last_transaction_date = now_datetime()
		bi.match_status = "Beklemede"
		bi.flags.ignore_permissions = True
		try:
			bi.insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			# Race condition: başka request aynı buyer+seller için oluşturmuş, UPDATE yap
			frappe.db.rollback()
			existing = frappe.db.get_value("Buyer Bank Interaction", {"buyer": buyer, "seller": seller_code}, "name")
			if existing:
				frappe.db.sql(
					"""UPDATE `tabBuyer Bank Interaction`
					   SET total_wire_amount = COALESCE(total_wire_amount, 0) + %s,
					       pending_match_amount = COALESCE(pending_match_amount, 0) + %s,
					       last_transaction_date = %s
					   WHERE name = %s""",
					(float(amount), float(amount), now_datetime(), existing),
				)


def update_bank_interaction_on_confirm(buyer, seller_code, amount):
	"""When seller confirms payment, reduce pending_match_amount and update match_status."""
	existing = frappe.db.get_value(
		"Buyer Bank Interaction",
		{"buyer": buyer, "seller": seller_code},
		"name",
	)
	if not existing:
		return

	# F-039: Atomik SQL — read-modify-write race condition'ı önler
	from frappe.utils import now_datetime

	frappe.db.sql(
		"""UPDATE `tabBuyer Bank Interaction`
		   SET pending_match_amount = GREATEST(0, COALESCE(pending_match_amount, 0) - %s),
		       match_status = IF(
		           GREATEST(0, COALESCE(pending_match_amount, 0) - %s) = 0,
		           'Tam Eşleşme', 'Kısmi Eşleşme'
		       ),
		       modified = %s
		   WHERE name = %s""",
		(float(amount), float(amount), now_datetime(), existing),
	)

"""
Backfill Payment Transaction and Buyer Bank Interaction records
from existing Order data.

Idempotent: safe to run multiple times — skips orders that already have
corresponding transaction records.
"""
import frappe
from frappe.utils import now_datetime


def execute():
    # Ensure DocTypes are loaded
    frappe.reload_doc("tradehub_core", "doctype", "payment_transaction")
    frappe.reload_doc("tradehub_core", "doctype", "buyer_bank_interaction")

    _backfill_payment_transactions()
    _backfill_refund_transactions()
    _backfill_bank_interactions()

    frappe.db.commit()


def _backfill_payment_transactions():
    """Create Payment Transaction records from Orders with remittance data."""
    orders = frappe.get_list(
        "Order",
        filters={"remittance_amount": [">", 0]},
        fields=[
            "name", "buyer", "seller", "currency",
            "remittance_date", "remittance_amount", "remittance_sender",
            "receipt_url", "status",
        ],
        page_length=0,
        ignore_permissions=True,
    )

    for order in orders:
        # Skip if transaction already exists for this order
        if frappe.db.exists("Payment Transaction", {"order": order.name, "transaction_type": "Ödeme"}):
            continue

        seller_name = ""
        seller_bank_name = ""
        seller_iban = ""
        if order.seller:
            seller_info = frappe.db.get_value(
                "Admin Seller Profile", order.seller,
                ["seller_name", "bank_name", "iban"],
                as_dict=True,
            )
            if seller_info:
                seller_name = seller_info.seller_name or ""
                seller_bank_name = seller_info.bank_name or ""
                seller_iban = seller_info.iban or ""

        # Determine status based on order status
        status = "Gönderildi"
        if order.status in ("Onaylanıyor", "Kargoda", "Tamamlandı"):
            status = "Tamamlandı"

        tx = frappe.new_doc("Payment Transaction")
        tx.transaction_type = "Ödeme"
        tx.order = order.name
        tx.buyer = order.buyer
        tx.seller = order.seller or ""
        tx.seller_name = seller_name
        tx.payment_method = "Banka Havalesi"
        tx.amount = float(order.remittance_amount or 0)
        tx.currency = order.currency or "TRY"
        tx.transaction_date = order.remittance_date or now_datetime()
        tx.status = status
        tx.remittance_sender = order.remittance_sender or ""
        tx.seller_bank_name = seller_bank_name
        tx.seller_iban = seller_iban
        tx.receipt_url = order.receipt_url or ""
        tx.flags.ignore_permissions = True
        tx.insert(ignore_permissions=True)


def _backfill_refund_transactions():
    """Create refund-type Payment Transaction records from Orders with refund data."""
    orders = frappe.get_list(
        "Order",
        filters={"refund_status": ["!=", ""]},
        fields=[
            "name", "buyer", "seller", "currency",
            "refund_status", "refund_reason", "refund_amount", "refund_requested_at",
        ],
        page_length=0,
        ignore_permissions=True,
    )

    for order in orders:
        if frappe.db.exists("Payment Transaction", {"order": order.name, "transaction_type": "İade"}):
            continue

        seller_name = ""
        if order.seller:
            seller_name = frappe.db.get_value(
                "Admin Seller Profile", order.seller, "seller_name"
            ) or ""

        status_map = {
            "Pending": "Beklemede",
            "Approved": "Tamamlandı",
            "Rejected": "Reddedildi",
        }
        status = status_map.get(order.refund_status, "Beklemede")

        tx = frappe.new_doc("Payment Transaction")
        tx.transaction_type = "İade"
        tx.order = order.name
        tx.buyer = order.buyer
        tx.seller = order.seller or ""
        tx.seller_name = seller_name
        tx.amount = float(order.refund_amount or 0)
        tx.currency = order.currency or "TRY"
        tx.transaction_date = order.refund_requested_at or now_datetime()
        tx.status = status
        tx.refund_reason = order.refund_reason or ""
        tx.flags.ignore_permissions = True
        tx.insert(ignore_permissions=True)


def _backfill_bank_interactions():
    """Create Buyer Bank Interaction records from buyer-seller order relationships."""
    # Get unique buyer-seller pairs with payment data
    pairs = frappe.db.sql("""
        SELECT buyer, seller, currency,
               SUM(remittance_amount) as total_amount,
               MAX(remittance_date) as last_date
        FROM `tabOrder`
        WHERE seller IS NOT NULL AND seller != ''
          AND remittance_amount > 0
        GROUP BY buyer, seller, currency
    """, as_dict=True)

    for pair in pairs:
        if frappe.db.exists("Buyer Bank Interaction",
                            {"buyer": pair.buyer, "seller": pair.seller}):
            continue

        seller_info = frappe.db.get_value(
            "Admin Seller Profile", pair.seller,
            ["seller_name", "bank_name", "iban", "account_holder"],
            as_dict=True,
        )
        if not seller_info:
            continue

        # Count confirmed vs total to determine match status
        confirmed_count = frappe.db.count("Order", {
            "buyer": pair.buyer,
            "seller": pair.seller,
            "status": ["in", ["Onaylanıyor", "Kargoda", "Tamamlandı"]],
            "remittance_amount": [">", 0],
        })
        total_count = frappe.db.count("Order", {
            "buyer": pair.buyer,
            "seller": pair.seller,
            "remittance_amount": [">", 0],
        })

        if confirmed_count == total_count and total_count > 0:
            match_status = "Tam Eşleşme"
            pending_amount = 0
        elif confirmed_count > 0:
            match_status = "Kısmi Eşleşme"
            pending_amount = float(pair.total_amount or 0) * (1 - confirmed_count / total_count)
        else:
            match_status = "Beklemede"
            pending_amount = float(pair.total_amount or 0)

        bi = frappe.new_doc("Buyer Bank Interaction")
        bi.buyer = pair.buyer
        bi.seller = pair.seller
        bi.seller_name = seller_info.seller_name or ""
        bi.seller_iban = seller_info.iban or ""
        bi.seller_bank_name = seller_info.bank_name or ""
        bi.seller_account_holder = seller_info.account_holder or ""
        bi.total_wire_amount = float(pair.total_amount or 0)
        bi.pending_match_amount = pending_amount
        bi.currency = pair.currency or "TRY"
        bi.last_transaction_date = pair.last_date or now_datetime()
        bi.match_status = match_status
        bi.flags.ignore_permissions = True
        bi.insert(ignore_permissions=True)

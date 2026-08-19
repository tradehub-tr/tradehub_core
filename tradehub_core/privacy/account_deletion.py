"""Hesap silme sonrası PII anonimleştirme.

15 günlük bekleme süresinin ardından (veya hemen, admin tarafından tetiklenirse)
kullanıcıya ait tüm kişisel verileri anonimleştirir.

KVKK Madde 7 uyarınca: kişisel verilerin işlenmesini gerektiren sebeplerin
ortadan kalkması halinde, kişisel veriler resen veya ilgili kişinin talebi
üzerine silinir, yok edilir veya anonim hale getirilir.

Scheduler entegrasyonu: `anonymize_pending_deletions` günlük çalışır ve
`User.deletion_requested_on` alanı 15+ gün öncesine ait, hâlâ deaktif
kullanıcıları bulup anonimleştirir.
"""

import frappe
from frappe.utils import add_days, now_datetime

_DELETED_USER_LABEL = "[Silinmiş Kullanıcı]"
_ANONYMOUS_LABEL = "[Anonim]"
_GRACE_PERIOD_DAYS = 15  # KVKK Madde 7 — 15 gün içinde anonimleştirme zorunlu


def anonymize_pending_deletions() -> None:
	"""Günlük scheduler tarafından çağrılır.

	deletion_requested_on alanı 15+ gün öncesine ait, hâlâ deaktif
	kullanıcıları bulup anonimleştirir.
	"""
	cutoff = add_days(now_datetime(), -_GRACE_PERIOD_DAYS)

	users = frappe.get_all(
		"User",
		filters=[
			["enabled", "=", 0],
			["deletion_requested_on", "is", "set"],
			["deletion_requested_on", "<=", cutoff],
		],
		pluck="name",
		limit_page_length=50,
	)

	for user in users:
		try:
			anonymize_deleted_account(user)
		except Exception:
			frappe.log_error(
				f"Account anonymization failed for {user}",
				"account_deletion.anonymize_pending_deletions",
			)


def anonymize_deleted_account(user: str) -> None:
	"""Silinen hesaba ait PII verilerini anonimleştirir.

	Çalışmadan önce kullanıcının hala deaktif olduğunu doğrular (geri alma durumu).
	"""
	user_enabled = frappe.db.get_value("User", user, "enabled")
	if user_enabled:
		frappe.logger("account_deletion").info(f"User {user} re-enabled, skipping anonymization")
		return

	_anonymize_user_doc(user)
	_anonymize_user_profile(user)
	_anonymize_seller_profile(user)
	_anonymize_seller_application(user)
	_anonymize_addresses(user)
	_anonymize_orders(user)
	_anonymize_reviews(user)
	_anonymize_questions(user)
	_anonymize_search_history(user)
	_anonymize_favorites(user)
	_cleanup_sessions_and_tokens(user)

	# Clear the deletion_requested_on to prevent re-processing
	frappe.db.set_value("User", user, "deletion_requested_on", None, update_modified=False)

	try:
		from tradehub_core.audit.log import DECISION_ALLOW, LAYER_L3, log_decision

		log_decision(
			actor="System",
			action="account.anonymize",
			decision=DECISION_ALLOW,
			rule_id="kvkk.article7",
			layer=LAYER_L3,
			severity="HIGH",
			context={"user": user, "reason": "15-day grace period expired after account deletion (KVKK Madde 7)"},
		)
	except Exception:
		frappe.log_error(
			f"Failed to write audit log after anonymizing account {user}",
			"account_deletion.anonymize_deleted_account",
		)

	frappe.db.commit()
	frappe.logger("account_deletion").info(f"Account anonymized: {user}")


def _anonymize_user_doc(user: str) -> None:
	"""User DocType'ındaki PII alanlarını anonimleştirir.

	Frappe User tablosunda email, phone, full_name doğrudan PII içerir.
	Email login key olduğu için tamamen silinemez — anonim format kullanılır.
	"""
	frappe.db.set_value(
		"User",
		user,
		{
			"full_name": _DELETED_USER_LABEL,
			"first_name": _DELETED_USER_LABEL,
			"last_name": "",
			"phone": None,
			"mobile_no": None,
			"bio": None,
			"location": None,
			"user_image": None,
		},
		update_modified=False,
	)


def _anonymize_seller_application(user: str) -> None:
	"""Seller Application iletişim bilgilerini anonimleştirir."""
	if not frappe.db.exists("DocType", "Seller Application"):
		return
	apps = frappe.get_all(
		"Seller Application",
		filters={"applicant_user": user},
		pluck="name",
	)
	for app_name in apps:
		frappe.db.set_value(
			"Seller Application",
			app_name,
			{
				"contact_email": None,
				"contact_phone": None,
				"business_name": _DELETED_USER_LABEL,
			},
			update_modified=False,
		)


def _anonymize_user_profile(user: str) -> None:
	"""User Profile DocType'ındaki PII alanlarını anonimleştirir."""
	profile_name = frappe.db.get_value("User Profile", {"user": user}, "name")
	if not profile_name:
		return

	frappe.db.set_value(
		"User Profile",
		profile_name,
		{
			"full_name": _DELETED_USER_LABEL,
			"phone": None,
			"tax_id": None,
			"company_name": None,
		},
		update_modified=False,
	)


def _anonymize_seller_profile(user: str) -> None:
	"""Admin Seller Profile DocType'ındaki PII alanlarını anonimleştirir."""
	seller_name = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
	if not seller_name:
		return

	frappe.db.set_value(
		"Admin Seller Profile",
		seller_name,
		{
			"seller_name": _DELETED_USER_LABEL,
			"company_name": _DELETED_USER_LABEL,
			"email": None,
			"phone": None,
			"address_line1": None,
			"address_line2": None,
		},
		update_modified=False,
	)


def _anonymize_addresses(user: str) -> None:
	"""Kullanıcıya ait adres kayıtlarını siler."""
	addresses = frappe.get_all(
		"Addresses",
		filters={"user": user},
		pluck="name",
	)
	for addr_name in addresses:
		frappe.delete_doc("Addresses", addr_name, ignore_permissions=True, force=True)


def _anonymize_orders(user: str) -> None:
	"""Sipariş kayıtlarında alıcı notunu anonimleştirir.

	Siparişler mali kayıt niteliğindedir, tamamen silinemez.
	buyer Link alanı korunur (mali iz), sadece serbest metin PII temizlenir.
	"""
	orders = frappe.get_all(
		"Order",
		filters={"buyer": user},
		pluck="name",
	)
	for order_name in orders:
		frappe.db.set_value(
			"Order",
			order_name,
			{"buyer_note": None},
			update_modified=False,
		)


def _anonymize_reviews(user: str) -> None:
	"""Değerlendirmelerde yazar adını anonimleştirir, içerik korunur."""
	reviews = frappe.get_all(
		"Listing Review",
		filters={"reviewer_user": user},
		pluck="name",
	)
	for review_name in reviews:
		frappe.db.set_value(
			"Listing Review",
			review_name,
			{"reviewer_display_name": _ANONYMOUS_LABEL},
			update_modified=False,
		)


def _anonymize_questions(user: str) -> None:
	"""Ürün sorularında soran kişi adını anonimleştirir."""
	questions = frappe.get_all(
		"Listing Question",
		filters={"asker": user},
		pluck="name",
	)
	for q_name in questions:
		frappe.db.set_value(
			"Listing Question",
			q_name,
			{"asker_display_name": _ANONYMOUS_LABEL},
			update_modified=False,
		)


def _anonymize_search_history(user: str) -> None:
	"""Arama geçmişi ve ürün görüntüleme kayıtlarını siler."""
	for doctype in ("Search History", "User Product View"):
		if not frappe.db.exists("DocType", doctype):
			continue
		records = frappe.get_all(doctype, filters={"user": user}, pluck="name")
		for rec_name in records:
			frappe.delete_doc(doctype, rec_name, ignore_permissions=True, force=True)


def _anonymize_favorites(user: str) -> None:
	"""Favori listesi kayıtlarını siler."""
	if not frappe.db.exists("DocType", "Buyer Favorite List"):
		return
	favorites = frappe.get_all("Buyer Favorite List", filters={"user": user}, pluck="name")
	for fav_name in favorites:
		frappe.delete_doc("Buyer Favorite List", fav_name, ignore_permissions=True, force=True)


def _cleanup_sessions_and_tokens(user: str) -> None:
	"""Mobil API token ve push subscription kayıtlarını siler."""
	for doctype in ("Mobile API Token", "Push Subscription"):
		if not frappe.db.exists("DocType", doctype):
			continue
		records = frappe.get_all(doctype, filters={"user": user}, pluck="name")
		for rec_name in records:
			frappe.delete_doc(doctype, rec_name, ignore_permissions=True, force=True)

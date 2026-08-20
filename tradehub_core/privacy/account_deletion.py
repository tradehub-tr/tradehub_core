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

# Ö-K3 — silinen hesabın medya anonimleştirme adımının eylem sabiti. Mevcut
# nokta-deseni (`account.anonymize`, `privacy.export_*`) izlenir; `media.*`
# değil çünkü o küme `media/audit.py::MEDIA_ACTIONS`'a bağlı ve o dosya bu
# görevin kapsamı dışında. Bu satır privacy katmanının KVKK m.7 izi.
ACTION_MEDIA_ANONYMIZED: str = "privacy.media_anonymized"


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
	_anonymize_user_media(user)

	# Clear the deletion_requested_on to prevent re-processing
	frappe.db.set_value("User", user, "deletion_requested_on", None, update_modified=False)

	try:
		from tradehub_core.audit.log import DECISION_ALLOW, LAYER_L3, log_decision

		log_decision(
			# Rapor 92 §4 düzeltmesi: ADL.actor Link→User doğrular; "System" diye
			# bir User YOK — bu satır eklendiğinden beri SESSİZCE düşüyordu
			# (canlıda ölçüldü: ADL'de 0 `account.anonymize` kaydı, Error Log'da
			# "Actor: System bulunamadı"). Sistem işleri Administrator koşar.
			actor="Administrator",
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


def _own_uploaded_media_urls(user: str) -> list[str]:
	"""Kullanıcının KENDİ yüklediği public medyanın adresleri — hijyen kemeriyle.

	Envanterin `_base_query()` HİJYEN KEMERİ yeniden kullanılıyor (public,
	klasörsüz, KVKK/hassas doctype eki değil, HASSAS-İKİZ maskesi). Sahiplik
	burada mağaza değil BİREYSEL: `File.owner == user`. Silinen bir alt kullanıcı
	yüzünden mağazanın (ya da başka bir alt kullanıcının) dosyaları işaretlenmez.
	"""
	from tradehub_core.media import inventory

	f, query = inventory._base_query()
	rows = query.where(f.owner == user).select(f.file_url).run(as_dict=True)
	# `_base_query()` file_url ile gruplu — tekilleştirme zaten yapılmış.
	return [r["file_url"] for r in rows if r.get("file_url")]


def _anonymize_user_media(user: str) -> dict:
	"""Ö-K3 — silinen hesabın KENDİ medyasını işaretle (SİLME DEĞİL).

	KVKK m.7 anonimleştirmeyi ister ama iki sınır var (T-134 §4 "legal_hold ile
	çatışma kuralı"):

	  * KALICI SİLME YOK. Mevcut çöp akışı (`media/trash.py`) kullanılıyor —
	    geri alınabilir 30 günlük ara durak. Dosya `private/media_trash/`e taşınır,
	    public URL 404 döner (siteden erişilemez) ama kayıt durur. Retention'a
	    saygı bu: yanlış bir toplu anonimleştirme geri alınabilir olmalı.
	  * KULLANIMDAKİ dosya taşınmaz. Canlı ürün görseli / siparişe (mali kayıt)
	    bağlı görsel `TRASHABLE_VERDICTS` dışındadır ve RETAINED kalır — legal-hold
	    benzeri koruma. `move_to_trash` bunları `_assert_trashable` ile zaten
	    reddederdi; verdict'e ÖNCEDEN bakıp denetim gürültüsü (scope_denied)
	    üretmeden retained sayıyoruz.

	Private/hassas/KVKK-eki dosyalar `_own_uploaded_media_urls` hijyen kemerinde
	kapsam dışı — bu adıma hiç girmezler.

	Her taşıma zaten `media.trash` denetim satırı üretir (dosya başına iz);
	buradaki tek `privacy.media_anonymized` satırı KVKK m.7 adımının BÜTÜN olarak
	çalıştığının özet kanıtıdır.
	"""
	try:
		urls = _own_uploaded_media_urls(user)
	except Exception:
		frappe.log_error(
			f"Media collection failed during anonymization for {user}",
			"account_deletion._anonymize_user_media",
		)
		return {"trashed": 0, "retained": 0}

	if not urls:
		return {"trashed": 0, "retained": 0}

	from tradehub_core.media import trash, usage

	verdicts = usage.verdict_map_all(deep=True)
	trashed: list[str] = []
	retained: list[str] = []
	for url in urls:
		# Kullanımda ya da zaten çöpte → retention/legal-hold gereği DOKUNMA.
		if verdicts.get(url) not in trash.TRASHABLE_VERDICTS or trash.in_trash(url):
			retained.append(url)
			continue
		try:
			trash.move_to_trash(url)
			trashed.append(url)
		except Exception:
			# Taşınamadıysa (yarışan durum, disk) korunur — silme değil işaretleme.
			frappe.log_error(
				f"Media trash failed during anonymization for {user}: {url}",
				"account_deletion._anonymize_user_media",
			)
			retained.append(url)

	try:
		from tradehub_core.audit.log import DECISION_ALLOW, LAYER_L3, log_decision

		log_decision(
			actor="Administrator",  # ADL.actor Link→User; sistem işi Administrator koşar (rapor 92 §4)
			action=ACTION_MEDIA_ANONYMIZED,
			decision=DECISION_ALLOW,
			rule_id="kvkk.article7",
			layer=LAYER_L3,
			object_doctype="User",
			object_name=user,
			severity="HIGH",
			context={
				"trashed": len(trashed),
				"retained": len(retained),
				# İlk 20 adres; tamamı 5 KB bağlam sınırını şişirir. Adres kullanıcının
				# KENDİ medyası — başkasının dosyası bu listeye yapısal olarak giremez.
				"trashed_urls": trashed[:20],
				"reason": "account deletion media anonymization (KVKK Madde 7); in-use/legal-hold retained",
			},
		)
	except Exception:
		frappe.log_error(
			f"Failed to write media anonymization audit for {user}",
			"account_deletion._anonymize_user_media",
		)

	frappe.db.commit()
	return {"trashed": len(trashed), "retained": len(retained)}

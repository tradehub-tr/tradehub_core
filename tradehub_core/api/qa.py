"""Faz 4 — Q&A Hub API.

Pre-purchase soru-cevap sistemi.
- Buyer/Seller/Admin soru sorabilir
- Seller/Buyer/Admin yanıtlayabilir, responder_type otomatik atanır
- Helpful oyu sayaçları cache'lenir
- Anonim soru DESTEKLENMEZ (B2B güven gereği).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from tradehub_core.api.rate_limit import rate_limit

ADMIN_ROLES = {"System Manager", "Marketplace Admin"}
KYB_VERIFIED_STATUS = "Verified"
VALID_SORTS = {
	"recent": "submitted_at DESC",
	"helpful": "helpful_count DESC, submitted_at DESC",
	"answered": "answer_count DESC, submitted_at DESC",
}


def _ensure_logged_in():
	if frappe.session.user == "Guest":
		frappe.throw(_("Bu işlem için giriş yapmalısınız"), frappe.AuthenticationError)


def _is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(frappe.get_roles(user)) & ADMIN_ROLES)


def _resolve_display_name(user: str) -> str:
	bp = frappe.db.get_value(
		"Buyer Profile", {"user": user}, ["company_name", "buyer_name", "city"], as_dict=True
	)
	if bp:
		base = (bp.company_name or "").strip() or (bp.buyer_name or "").strip()
		if base and bp.city:
			return f"{base} ({bp.city})"
		if base:
			return base
	return frappe.db.get_value("User", user, "full_name") or user


def _kyb_verified(user: str) -> bool:
	status = frappe.db.get_value("KYB Verification", {"user": user}, "status")
	return status == KYB_VERIFIED_STATUS


# ---------------------------------------------------------------------------
# Question CRUD
# ---------------------------------------------------------------------------
@frappe.whitelist()
def submit_listing_question(listing: str, question: str):
	"""Buyer/Seller/Admin bir ürün için soru oluşturur."""
	_ensure_logged_in()
	if not listing or not frappe.db.exists("Listing", listing):
		frappe.throw(_("Ürün bulunamadı"), frappe.DoesNotExistError)
	q = (question or "").strip()
	if len(q) < 10:
		frappe.throw(_("Soru en az 10 karakter olmalı"))
	if len(q) > 1000:
		frappe.throw(_("Soru en fazla 1000 karakter olabilir"))

	user = frappe.session.user
	doc = frappe.new_doc("Listing Question")
	doc.listing = listing
	doc.asker = user
	doc.asker_display_name = _resolve_display_name(user)
	doc.is_kyb_verified = 1 if _kyb_verified(user) else 0
	doc.question = q
	doc.status = "Pending"
	doc.submitted_at = now_datetime()
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "name": doc.name, "status": doc.status}


@frappe.whitelist(allow_guest=True)
def list_listing_questions(
	listing: str, page: int = 1, page_size: int = 10, sort_by: str = "recent", status: str = "Answered"
):
	"""Public — bir ürün için soru listesi (cevaplarla birlikte).

	Varsayılan: yalnız `Answered` durumdaki sorular gösterilir.

	Ek davranış: Login'li kullanıcının **kendi Pending sorusu** da listede
	görünür (`is_own_pending=true` flag ile). Böylece soran kişi sorduğu
	an "kayboldu mu?" hissetmez.
	"""
	if not listing:
		frappe.throw(_("Ürün zorunlu"))
	page = max(1, cint(page))
	page_size = min(50, max(1, cint(page_size)))
	order_by = VALID_SORTS.get(sort_by, VALID_SORTS["recent"])

	user = frappe.session.user
	is_guest = user == "Guest"

	if is_guest or not status:
		# Public default akış — sadece Answered (veya istenen status)
		filters: dict = {"listing": listing}
		if status:
			filters["status"] = status
		total = frappe.db.count("Listing Question", filters=filters)
		questions = frappe.get_all(
			"Listing Question",
			filters=filters,
			fields=[
				"name",
				"asker",
				"asker_display_name",
				"is_kyb_verified",
				"question",
				"answer_count",
				"helpful_count",
				"submitted_at",
				"status",
			],
			order_by=order_by,
			limit_start=(page - 1) * page_size,
			limit_page_length=page_size,
		)
	else:
		# Login kullanıcı için: requested status + kendi Pending'leri
		# Tek SQL ile temiz çözüm.
		where = (
			"listing = %(listing)s AND (  status = %(status)s  OR (status = 'Pending' AND asker = %(user)s))"
		)
		params = {"listing": listing, "status": status, "user": user}
		total_row = frappe.db.sql(
			f"SELECT COUNT(*) FROM `tabListing Question` WHERE {where}",
			params,
		)
		total = int(total_row[0][0]) if total_row else 0
		offset = (page - 1) * page_size
		questions = frappe.db.sql(
			f"""
			SELECT
				name, asker, asker_display_name, is_kyb_verified,
				question, answer_count, helpful_count,
				submitted_at, status
			FROM `tabListing Question`
			WHERE {where}
			ORDER BY
				CASE WHEN status='Pending' AND asker=%(user)s THEN 0 ELSE 1 END,
				{order_by}
			LIMIT %(_limit)s OFFSET %(_offset)s
			""",
			{**params, "_limit": page_size, "_offset": offset},
			as_dict=True,
		)

	# Cevapları batch çek
	q_names = [str(q["name"]) for q in questions]
	answers_by_q = {}
	if q_names:
		rows = frappe.get_all(
			"Listing Question Answer",
			filters={"question": ["in", q_names]},
			fields=[
				"name",
				"question",
				"responder",
				"responder_type",
				"is_seller_answer",
				"helpful_count",
				"submitted_at",
				"answer",
			],
			order_by="is_seller_answer DESC, helpful_count DESC, submitted_at ASC",
		)
		for a in rows:
			answers_by_q.setdefault(str(a["question"]), []).append(
				{
					"name": a["name"],
					"responder_type": a["responder_type"],
					"is_seller_answer": bool(a["is_seller_answer"]),
					"helpful_count": int(a["helpful_count"] or 0),
					"submitted_at": a["submitted_at"],
					"answer": a["answer"],
				}
			)

	for q in questions:
		q["answers"] = answers_by_q.get(str(q["name"]), [])
		# Soran kişi kendi Pending sorusunu "Onay bekliyor" rozetiyle görsün
		q["is_own_pending"] = not is_guest and q.get("status") == "Pending" and q.get("asker") == user
		# asker e-posta kişisel bilgi — sadece kendi sorum için tut
		if q.get("asker") != user:
			q.pop("asker", None)
	return {"questions": questions, "total": total, "page": page, "page_size": page_size}


# ---------------------------------------------------------------------------
# Answer CRUD
# ---------------------------------------------------------------------------
def _recompute_question_answer_count(question_name: str):
	if not question_name or not frappe.db.exists("Listing Question", question_name):
		return
	cnt = frappe.db.count("Listing Question Answer", filters={"question": question_name})
	new_status = "Answered" if cnt > 0 else "Pending"
	frappe.db.set_value(
		"Listing Question",
		question_name,
		{"answer_count": cnt, "status": new_status},
		update_modified=False,
	)


@frappe.whitelist()
def submit_question_answer(question: str, answer: str):
	"""Seller/Buyer/Admin yorumlanır. Otomatik responder_type belirlenir."""
	_ensure_logged_in()
	if not question or not frappe.db.exists("Listing Question", question):
		frappe.throw(_("Soru bulunamadı"), frappe.DoesNotExistError)
	a = (answer or "").strip()
	if len(a) < 5:
		frappe.throw(_("Cevap en az 5 karakter olmalı"))
	if len(a) > 2000:
		frappe.throw(_("Cevap en fazla 2000 karakter olabilir"))

	q_doc = frappe.db.get_value("Listing Question", question, ["listing", "asker"], as_dict=True)
	if not q_doc:
		frappe.throw(_("Soru bulunamadı"))

	user = frappe.session.user

	# Guard #1: Soran kişi kendi sorusuna cevap veremez.
	# Asker == satıcının kendisi olabilir (test ortamı), o vakada
	# satıcı yetkisi öne çıksın (seller yine de cevap atabilsin).
	listing_seller = frappe.db.get_value("Listing", q_doc.listing, "seller_profile")
	seller_user = (
		frappe.db.get_value("Admin Seller Profile", listing_seller, "user") if listing_seller else None
	)
	is_seller_of_listing = bool(seller_user and seller_user == user)
	if q_doc.asker == user and not is_seller_of_listing and not _is_admin(user):
		frappe.throw(_("Kendi sorunuza cevap veremezsiniz"))

	# Guard #2: Aynı kullanıcı aynı soruya tekrar cevap atamaz (spam koruması).
	if frappe.db.exists(
		"Listing Question Answer",
		{"question": question, "responder": user},
	):
		frappe.throw(_("Bu soruya zaten cevap verdiniz"))

	# Responder type
	if _is_admin(user):
		responder_type = "admin"
		is_seller = 0
	elif is_seller_of_listing:
		responder_type = "seller"
		is_seller = 1
	else:
		responder_type = "buyer"
		is_seller = 0

	doc = frappe.new_doc("Listing Question Answer")
	doc.question = question
	doc.responder = user
	doc.responder_type = responder_type
	doc.is_seller_answer = is_seller
	doc.answer = a
	doc.submitted_at = now_datetime()
	doc.insert(ignore_permissions=True)

	# Question.answer_count + status
	_recompute_question_answer_count(question)
	frappe.db.commit()
	return {
		"success": True,
		"name": doc.name,
		"responder_type": responder_type,
		"is_seller_answer": bool(is_seller),
	}


# ---------------------------------------------------------------------------
# Helpful Vote
# ---------------------------------------------------------------------------
def _recompute_helpful_count(target_type: str, target_id: str):
	if target_type == "question":
		dt = "Listing Question"
	elif target_type == "answer":
		dt = "Listing Question Answer"
	else:
		return
	if not frappe.db.exists(dt, target_id):
		return
	cnt = frappe.db.count(
		"Question Helpful Vote",
		filters={"target_type": target_type, "target_id": target_id},
	)
	frappe.db.set_value(dt, target_id, "helpful_count", cnt, update_modified=False)


@frappe.whitelist()
def vote_question_helpful(target_type: str, target_id: str):
	"""Login'li user soru veya cevaba helpful oy verir.

	`target_type`: 'question' veya 'answer'
	"""
	_ensure_logged_in()
	if target_type not in ("question", "answer"):
		frappe.throw(_("Geçersiz hedef tipi"))
	if not target_id:
		frappe.throw(_("Hedef ID zorunlu"))

	user = frappe.session.user

	# Self-vote guard — kendi soru/cevabına oy vermek reputation exploit'i.
	# Review tarafındaki vote_review_helpful ile aynı koruma.
	if target_type == "question":
		asker = frappe.db.get_value("Listing Question", str(target_id), "asker")
		if asker and asker == user:
			frappe.throw(_("Kendi sorunuza oy veremezsiniz"), frappe.PermissionError)
	else:  # answer
		responder = frappe.db.get_value("Listing Question Answer", str(target_id), "responder")
		if responder and responder == user:
			frappe.throw(_("Kendi cevabınıza oy veremezsiniz"), frappe.PermissionError)

	existing = frappe.db.get_value(
		"Question Helpful Vote",
		{"target_type": target_type, "target_id": str(target_id), "voter": user},
		"name",
	)
	if existing:
		return {"success": True, "changed": False, "name": existing}

	doc = frappe.new_doc("Question Helpful Vote")
	doc.target_type = target_type
	doc.target_id = str(target_id)
	doc.voter = user
	doc.voted_at = now_datetime()
	doc.insert(ignore_permissions=True)

	_recompute_helpful_count(target_type, str(target_id))
	frappe.db.commit()
	return {"success": True, "changed": True, "name": doc.name}


# ---------------------------------------------------------------------------
# Satıcı panel — soruyu kendi panelinden gizle (storefront'ta kalmaya devam eder)
# ---------------------------------------------------------------------------
@frappe.whitelist()
@rate_limit(max_calls=30, window_seconds=60, scope="qa_dismiss_question")
def dismiss_question_from_seller_panel(name: str):
	"""Satıcı kendi yönetim panelinden soruyu gizler.

	**Soft-hide**: Veritabanında kayıt kalır, storefront `get_qa_page` ve
	`list_listing_questions` bu field'a bakmaz — yani alıcılar soruyu görmeye
	devam eder. Sadece bu satıcının kendi panel listesinden çıkar.

	Sadece listing'in satıcısı (veya admin) çağırabilir.
	"""
	_ensure_logged_in()
	if not name or not frappe.db.exists("Listing Question", name):
		frappe.throw(_("Soru bulunamadı"), frappe.DoesNotExistError)

	q_listing = frappe.db.get_value("Listing Question", name, "listing")
	listing_seller = frappe.db.get_value("Listing", q_listing, "seller_profile")
	seller_user = (
		frappe.db.get_value("Admin Seller Profile", listing_seller, "user") if listing_seller else None
	)

	user = frappe.session.user
	if not _is_admin(user) and seller_user != user:
		frappe.throw(
			_("Bu işlem için satıcı yetkisi gerekli"),
			frappe.PermissionError,
		)

	frappe.db.set_value(
		"Listing Question",
		name,
		"dismissed_by_seller",
		1,
		update_modified=False,
	)
	frappe.db.commit()
	return {"success": True, "name": name}


@frappe.whitelist()
@rate_limit(max_calls=30, window_seconds=60, scope="qa_restore_question")
def restore_question_to_seller_panel(name: str):
	"""dismiss_question_from_seller_panel'in tersi — soruyu panele geri getir."""
	_ensure_logged_in()
	if not name or not frappe.db.exists("Listing Question", name):
		frappe.throw(_("Soru bulunamadı"), frappe.DoesNotExistError)

	q_listing = frappe.db.get_value("Listing Question", name, "listing")
	listing_seller = frappe.db.get_value("Listing", q_listing, "seller_profile")
	seller_user = (
		frappe.db.get_value("Admin Seller Profile", listing_seller, "user") if listing_seller else None
	)

	user = frappe.session.user
	if not _is_admin(user) and seller_user != user:
		frappe.throw(
			_("Bu işlem için satıcı yetkisi gerekli"),
			frappe.PermissionError,
		)

	frappe.db.set_value(
		"Listing Question",
		name,
		"dismissed_by_seller",
		0,
		update_modified=False,
	)
	frappe.db.commit()
	return {"success": True, "name": name}


# ---------------------------------------------------------------------------
# Cevap silme — satıcı kendi cevabını silebilir (admin tüm cevapları)
# ---------------------------------------------------------------------------
@frappe.whitelist()
@rate_limit(max_calls=10, window_seconds=60, scope="qa_delete_answer")
def delete_question_answer(name: str):
	"""Cevap silme. Kurallar:

	- Cevabı yazan kullanıcı kendi cevabını silebilir.
	- Admin her cevabı silebilir.
	- Diğer kullanıcılar reddedilir.

	Silme sonrası soru'nun answer_count + status alanları yeniden hesaplanır.
	"""
	_ensure_logged_in()
	if not name or not frappe.db.exists("Listing Question Answer", name):
		frappe.throw(_("Cevap bulunamadı"), frappe.DoesNotExistError)

	row = frappe.db.get_value(
		"Listing Question Answer",
		name,
		["responder", "question"],
		as_dict=True,
	)
	user = frappe.session.user
	if not _is_admin(user) and row.responder != user:
		frappe.throw(
			_("Yalnızca kendi cevabınızı silebilirsiniz"),
			frappe.PermissionError,
		)

	frappe.delete_doc(
		"Listing Question Answer",
		name,
		ignore_permissions=True,
		force=True,
	)
	# Soru'nun answer_count + status alanlarını yeniden hesapla
	_recompute_question_answer_count(row.question)
	frappe.db.commit()
	return {"success": True, "question": row.question}


# ---------------------------------------------------------------------------
# Seller — kendi ürünlerindeki sorular (admin panel için)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def get_seller_questions(
	status: str | None = None,
	filter: str | None = None,
	page: int = 1,
	page_size: int = 20,
):
	"""Login'li satıcı için kendi listing'lerinin sorularını döner.

	Args:
		status: legacy — status'a göre filter ("Pending", "Answered", "Hidden")
		filter: "needs_my_answer" | "answered_by_me" | None. Satıcının kendi
			cevabı olup olmamasına göre filter. Status'tan bağımsız çalışır;
			yani satıcı bir Pending soruya cevap atsa o soru "answered_by_me"
			tab'ında görünür ama status hâlâ Pending olabilir (örn. soran
			tarafından kabul edilmedi).
		page, page_size: sayfalama.

	Returns:
		{ questions: [{... + listing_title, has_my_answer}], total, page,
		  page_size }
	"""
	_ensure_logged_in()
	user = frappe.session.user

	# Satıcı profilini bul
	seller_profile = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
	if not seller_profile:
		# Admin değilse ve seller değilse — boş döndür
		if not _is_admin(user):
			return {"questions": [], "total": 0, "page": 1, "page_size": page_size}
		seller_profile = None

	# Satıcının listing'lerini al
	listing_filter = {}
	if seller_profile:
		listings = frappe.get_all("Listing", filters={"seller_profile": seller_profile}, pluck="name")
		if not listings:
			return {"questions": [], "total": 0, "page": 1, "page_size": page_size}
		listing_filter = {"listing": ["in", listings]}

	page = max(1, cint(page))
	page_size = min(100, max(1, cint(page_size)))
	filters = dict(listing_filter)
	# Satıcının panel'inden gizlediği sorular default listede gözükmez.
	# Yine de tüm soruları görmek isteyen "include_dismissed=1" parametresi
	# eklenirse (future) çekilebilir; şu an her zaman gizliyoruz.
	filters["dismissed_by_seller"] = 0
	if status:
		filters["status"] = status

	# Satıcının kendi cevabı olan question'ları çek (filter için)
	# Listing scope'a göre kısıtla — sadece kendi listing'lerimin soruları için
	# verdiğim cevaplar sayılır.
	my_answered_qs: list[str] = []
	if listing_filter:
		my_answered_qs = frappe.db.sql_list(
			"""
			SELECT DISTINCT lqa.question
			FROM `tabListing Question Answer` lqa
			INNER JOIN `tabListing Question` lq ON lq.name = lqa.question
			WHERE lqa.responder = %(user)s AND lq.listing IN %(listings)s
			""",
			{"user": user, "listings": tuple(listings) or ("__none__",)},
		)

	# filter parametresine göre name filter ekle
	if filter == "needs_my_answer":
		if my_answered_qs:
			filters["name"] = ["not in", my_answered_qs]
	elif filter == "answered_by_me":
		if not my_answered_qs:
			# Hiç cevap atmamışsa boş döndür
			return {"questions": [], "total": 0, "page": page, "page_size": page_size}
		filters["name"] = ["in", my_answered_qs]

	total = frappe.db.count("Listing Question", filters=filters)
	# Pending önce — alfabetik sort yerine FIELD() ile öncelik
	questions = frappe.get_all(
		"Listing Question",
		filters=filters,
		fields=[
			"name",
			"listing",
			"asker_display_name",
			"asker",
			"is_kyb_verified",
			"question",
			"answer_count",
			"helpful_count",
			"submitted_at",
			"status",
		],
		order_by=("FIELD(status, 'Pending', 'Answered', 'Hidden') ASC, submitted_at DESC"),
		limit_start=(page - 1) * page_size,
		limit_page_length=page_size,
	)
	# Her soruda satıcı cevap atmış mı bilgisini ekle
	my_answered_set = set(str(x) for x in my_answered_qs)
	for q in questions:
		q["has_my_answer"] = str(q["name"]) in my_answered_set

	# Listing başlıklarını batch çek
	if questions:
		listing_names = list({q["listing"] for q in questions if q.get("listing")})
		titles = {}
		if listing_names:
			rows = frappe.get_all(
				"Listing", filters={"name": ["in", listing_names]}, fields=["name", "title"]
			)
			titles = {r["name"]: r["title"] for r in rows}
		for q in questions:
			q["listing_title"] = titles.get(q.get("listing"), q.get("listing"))

	# Cevapları batch çek
	q_names = [str(q["name"]) for q in questions]
	answers_by_q = {}
	if q_names:
		rows = frappe.get_all(
			"Listing Question Answer",
			filters={"question": ["in", q_names]},
			fields=[
				"name",
				"question",
				"responder",
				"responder_type",
				"is_seller_answer",
				"helpful_count",
				"submitted_at",
				"answer",
			],
			order_by="is_seller_answer DESC, helpful_count DESC, submitted_at ASC",
		)
		for a in rows:
			answers_by_q.setdefault(str(a["question"]), []).append(
				{
					"name": a["name"],
					"responder": a["responder"],
					"responder_type": a["responder_type"],
					"is_seller_answer": bool(a["is_seller_answer"]),
					"helpful_count": int(a["helpful_count"] or 0),
					"submitted_at": a["submitted_at"],
					"answer": a["answer"],
				}
			)
	for q in questions:
		q["answers"] = answers_by_q.get(str(q["name"]), [])

	return {"questions": questions, "total": total, "page": page, "page_size": page_size}


@frappe.whitelist()
def get_seller_question_counts():
	"""Satıcı paneli için rozetler.

	Yeni semantik (satıcı bakış açısı):
	  - needs_my_answer: satıcının cevap atmadığı sorular (status farkı yok)
	  - answered_by_me: satıcının cevap attığı sorular
	  - total: tüm sorular

	Geriye uyumluluk: pending/answered/hidden status-based sayılar da döner.
	"""
	_ensure_logged_in()
	user = frappe.session.user
	empty = {
		"pending": 0,
		"answered": 0,
		"hidden": 0,
		"total": 0,
		"needs_my_answer": 0,
		"answered_by_me": 0,
	}

	seller_profile = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
	if not seller_profile and not _is_admin(user):
		return empty

	listings = []
	if seller_profile:
		listings = frappe.get_all("Listing", filters={"seller_profile": seller_profile}, pluck="name")
		if not listings:
			return empty

	# Panel'den gizlenmiş sorular sayılmaz
	base_filter = (
		{"listing": ["in", listings], "dismissed_by_seller": 0} if listings else {"dismissed_by_seller": 0}
	)

	# Legacy status counts
	pending = frappe.db.count("Listing Question", filters={**base_filter, "status": "Pending"})
	answered = frappe.db.count("Listing Question", filters={**base_filter, "status": "Answered"})
	hidden = frappe.db.count("Listing Question", filters={**base_filter, "status": "Hidden"})
	total = pending + answered + hidden

	# Satıcı bakış açısı counts (sadece dismiss'siz sorular için)
	if listings:
		my_answered_qs = frappe.db.sql_list(
			"""
			SELECT DISTINCT lqa.question
			FROM `tabListing Question Answer` lqa
			INNER JOIN `tabListing Question` lq ON lq.name = lqa.question
			WHERE lqa.responder = %(user)s
			  AND lq.listing IN %(listings)s
			  AND lq.dismissed_by_seller = 0
			""",
			{"user": user, "listings": tuple(listings) or ("__none__",)},
		)
	else:
		my_answered_qs = []
	answered_by_me = len(my_answered_qs)
	needs_my_answer = total - answered_by_me

	return {
		"pending": pending,
		"answered": answered,
		"hidden": hidden,
		"total": total,
		"needs_my_answer": max(0, needs_my_answer),
		"answered_by_me": answered_by_me,
	}


# ---------------------------------------------------------------------------
# Admin moderation
# ---------------------------------------------------------------------------
@frappe.whitelist()
def admin_moderate_question(name: str, action: str):
	_ensure_logged_in()
	if not _is_admin():
		frappe.throw(_("Yetkisiz"), frappe.PermissionError)
	if action not in {"approve", "hide", "unhide"}:
		frappe.throw(_("Geçersiz aksiyon"))
	if not frappe.db.exists("Listing Question", name):
		frappe.throw(_("Soru bulunamadı"), frappe.DoesNotExistError)
	if action == "approve":
		# answer varsa Answered, yoksa Pending bırak
		_recompute_question_answer_count(name)
	elif action == "hide":
		frappe.db.set_value("Listing Question", name, "status", "Hidden", update_modified=False)
	elif action == "unhide":
		_recompute_question_answer_count(name)
	frappe.db.commit()
	return {"success": True}

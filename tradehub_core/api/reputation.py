"""Faz 3 — Reviewer Reputation Engine.

Kullanıcı yorumlarının kalitesine göre 0-100 reputation skoru hesaplar.
Tier'a göre ML-weighted rating'de daha yüksek katsayı kazandırır.

Tier weight'leri:
  Newcomer       (0-49)   → 1.0x
  Trusted        (50-74)  → 1.2x
  Top Contributor(75-89)  → 1.5x
  Verified Pro   (90-100) → 2.0x (B2B Vine — yeni ürünlere davet eligible)
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime

# Tier sınırları
TIER_THRESHOLDS = (
	(90, "Verified Pro", 2.0),
	(75, "Top Contributor", 1.5),
	(50, "Trusted", 1.2),
	(0, "Newcomer", 1.0),
)

KYB_VERIFIED_STATUS = "Verified"

# Skor katsayıları — yeni kullanıcı Newcomer (0-49) içinde başlasın
BASE_SCORE = 45
HELPFUL_VOTE_BONUS = 2  # max +30
HELPFUL_VOTE_MAX = 30
ABUSE_PENALTY = 5  # max -25
ABUSE_PENALTY_MAX = 25
KYB_BONUS = 10
REVIEW_COUNT_BONUS = 5  # 10+ review için sabit
REVIEW_COUNT_THRESHOLD = 10
REJECTION_PENALTY = 3  # max -15
REJECTION_PENALTY_MAX = 15


def _tier_for(score: int) -> tuple[str, float]:
	for threshold, name, weight in TIER_THRESHOLDS:
		if score >= threshold:
			return name, weight
	return "Newcomer", 1.0


def get_tier_weight(user: str) -> float:
	"""ML rating engine bunu çağırıyor — user'ın tier weight'ini döner."""
	if not user or user == "Guest":
		return 1.0
	tier = frappe.db.get_value("Reviewer Reputation", user, "tier")
	if not tier:
		return 1.0
	for _, name, weight in TIER_THRESHOLDS:
		if name == tier:
			return weight
	return 1.0


def _is_kyb_verified(user: str) -> bool:
	if not user:
		return False
	status = frappe.db.get_value("KYB Verification", {"user": user}, "status")
	return status == KYB_VERIFIED_STATUS


def recompute_user(user: str) -> dict:
	"""Bir user için reputation hesaplar ve kaydeder.

	Returns:
	  dict: {score, tier, total_reviews, helpful_received, abuse_received}
	"""
	if not user or user == "Guest":
		return {}

	# Toplam yorum sayısı (status = Approved)
	total_reviews = frappe.db.count("Listing Review", filters={"reviewer_user": user, "status": "Approved"})
	# Aldığı helpful oy sayısı (kendi review'larında)
	helpful_received = (
		frappe.db.sql(
			"""
			SELECT COALESCE(SUM(helpful_count), 0)
			FROM `tabListing Review`
			WHERE reviewer_user = %s
			""",
			(user,),
		)[0][0]
		or 0
	)
	# Aldığı ihbar sayısı
	abuse_received = (
		frappe.db.sql(
			"""
			SELECT COALESCE(SUM(abuse_report_count), 0)
			FROM `tabListing Review`
			WHERE reviewer_user = %s
			""",
			(user,),
		)[0][0]
		or 0
	)
	# Reddedilen yorum sayısı (status = Rejected)
	rejected = frappe.db.count("Listing Review", filters={"reviewer_user": user, "status": "Rejected"})
	kyb = _is_kyb_verified(user)

	# Skor hesabı
	score = BASE_SCORE
	score += min(HELPFUL_VOTE_MAX, int(helpful_received) * HELPFUL_VOTE_BONUS)
	score -= min(ABUSE_PENALTY_MAX, int(abuse_received) * ABUSE_PENALTY)
	if kyb:
		score += KYB_BONUS
	if total_reviews >= REVIEW_COUNT_THRESHOLD:
		score += REVIEW_COUNT_BONUS
	score -= min(REJECTION_PENALTY_MAX, int(rejected) * REJECTION_PENALTY)
	score = max(0, min(100, score))

	tier_name, _ = _tier_for(score)

	# Upsert
	if frappe.db.exists("Reviewer Reputation", user):
		doc = frappe.get_doc("Reviewer Reputation", user)
	else:
		doc = frappe.new_doc("Reviewer Reputation")
		doc.user = user
	doc.score = score
	doc.tier = tier_name
	doc.total_reviews = int(total_reviews)
	doc.helpful_received = int(helpful_received)
	doc.abuse_received = int(abuse_received)
	doc.rejected_reviews = int(rejected)
	doc.kyb_verified = 1 if kyb else 0
	doc.last_computed_at = now_datetime()
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {
		"score": score,
		"tier": tier_name,
		"total_reviews": int(total_reviews),
		"helpful_received": int(helpful_received),
		"abuse_received": int(abuse_received),
	}


# ── Hook handler'lar ────────────────────────────────────────────────────────
def recompute_on_review_update(doc, method=None):
	"""Listing Review on_update — sahibi için reputation güncelle."""
	if doc and doc.reviewer_user:
		try:
			recompute_user(doc.reviewer_user)
		except Exception:
			frappe.log_error(title="reputation_recompute_failed", message=f"review={doc.name}")


def recompute_on_helpful_vote(doc, method=None):
	"""Review Helpful Vote after_insert/on_trash — review sahibinin reputation'ı güncelle."""
	if not doc or not doc.review:
		return
	rev_user = frappe.db.get_value("Listing Review", doc.review, "reviewer_user")
	if rev_user:
		try:
			recompute_user(rev_user)
		except Exception:
			frappe.log_error(title="reputation_helpful_failed")


def recompute_on_abuse_report(doc, method=None):
	"""Review Abuse Report after_insert — review sahibinin reputation'ı güncelle."""
	if not doc or not doc.review:
		return
	rev_user = frappe.db.get_value("Listing Review", doc.review, "reviewer_user")
	if rev_user:
		try:
			recompute_user(rev_user)
		except Exception:
			frappe.log_error(title="reputation_abuse_failed")


# ── Scheduled job ───────────────────────────────────────────────────────────
def daily_recompute_all():
	"""Günlük cron — tüm reviewer'lar için reputation yeniden hesaplanır.

	Tier değişiklikleri (örn. helpful vote eskiyse vs.) için tampon.
	"""
	users = frappe.db.sql_list(
		"SELECT DISTINCT reviewer_user FROM `tabListing Review` WHERE reviewer_user IS NOT NULL"
	)
	updated = 0
	for u in users:
		try:
			recompute_user(u)
			updated += 1
		except Exception:
			frappe.log_error(title="reputation_daily_failed", message=f"user={u}")
	frappe.logger("tradehub").info(f"daily_reputation_recompute: {updated} kullanıcı")


# ── Public API ──────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# Faz 4 — Trusted Reviewer Invitation (B2B Vine programı)
# ─────────────────────────────────────────────────────────────────────────────
ELIGIBLE_TIERS_FOR_INVITATION = {"Top Contributor", "Verified Pro"}


@frappe.whitelist()
def invite_trusted_reviewer(user: str, listing: str, compensation: str = "Free Sample"):
	"""Admin/sistem bir Top Contributor / Verified Pro user'ı yeni bir
	ürünü değerlendirmeye davet eder."""
	from tradehub_core.api.review import _is_admin

	if not _is_admin():
		frappe.throw("Yetkisiz", frappe.PermissionError)

	if not user or not frappe.db.exists("User", user):
		frappe.throw("Kullanıcı bulunamadı", frappe.DoesNotExistError)
	if not listing or not frappe.db.exists("Listing", listing):
		frappe.throw("Ürün bulunamadı", frappe.DoesNotExistError)

	tier = frappe.db.get_value("Reviewer Reputation", user, "tier") or "Newcomer"
	if tier not in ELIGIBLE_TIERS_FOR_INVITATION:
		frappe.throw(f"{user} davete uygun tier değil (mevcut: {tier})")

	# Aynı (user, listing) için tekrar davet engelle
	if frappe.db.exists(
		"Trusted Reviewer Invitation",
		{"user": user, "listing": listing, "status": ["in", ["Invited", "Accepted"]]},
	):
		frappe.throw("Bu user için bu ürüne aktif davet zaten var")

	from frappe.utils import add_to_date

	doc = frappe.new_doc("Trusted Reviewer Invitation")
	doc.user = user
	doc.listing = listing
	doc.status = "Invited"
	doc.compensation = compensation
	doc.invited_at = now_datetime()
	doc.expires_at = add_to_date(now_datetime(), days=30)
	doc.insert(ignore_permissions=True)

	# Bildirim
	try:
		from tradehub_core.utils.notify import notify

		listing_title = frappe.db.get_value("Listing", listing, "title") or listing
		notify(
			recipient_user=user,
			recipient_role="buyer",
			type="review",
			title="Güvenilir Reviewer Daveti",
			message=f"{listing_title} ürününü değerlendirmeye davet edildiniz. Karşılık: {compensation}",
			action_url=f"/app/trusted-reviewer-invitation/{doc.name}",
			reference_doctype="Trusted Reviewer Invitation",
			reference_name=doc.name,
		)
	except Exception:
		pass

	frappe.db.commit()
	return {"success": True, "name": doc.name, "tier": tier}


@frappe.whitelist()
def accept_reviewer_invitation(name: str):
	"""User daveti kabul eder."""
	if frappe.session.user == "Guest":
		frappe.throw("Giriş yapın", frappe.AuthenticationError)
	doc = frappe.get_doc("Trusted Reviewer Invitation", name)
	from tradehub_core.api.review import _is_admin

	if doc.user != frappe.session.user and not _is_admin():
		frappe.throw("Sadece davetli kabul edebilir", frappe.PermissionError)
	if doc.status != "Invited":
		frappe.throw(f"Davet zaten {doc.status} durumda")
	doc.status = "Accepted"
	doc.accepted_at = now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "status": doc.status}


@frappe.whitelist()
def decline_reviewer_invitation(name: str):
	"""User daveti reddeder."""
	if frappe.session.user == "Guest":
		frappe.throw("Giriş yapın", frappe.AuthenticationError)
	doc = frappe.get_doc("Trusted Reviewer Invitation", name)
	from tradehub_core.api.review import _is_admin

	if doc.user != frappe.session.user and not _is_admin():
		frappe.throw("Yetkisiz", frappe.PermissionError)
	if doc.status != "Invited":
		frappe.throw(f"Davet zaten {doc.status} durumda")
	doc.status = "Declined"
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "status": doc.status}


@frappe.whitelist()
def get_invitation_list(user: str | None = None, status: str | None = None):
	"""User'a göre davet listesi."""
	if frappe.session.user == "Guest":
		frappe.throw("Giriş yapın", frappe.AuthenticationError)
	user = user or frappe.session.user
	filters = {"user": user}
	if status:
		filters["status"] = status
	rows = frappe.get_all(
		"Trusted Reviewer Invitation",
		filters=filters,
		fields=[
			"name",
			"listing",
			"status",
			"compensation",
			"invited_at",
			"accepted_at",
			"expires_at",
			"review",
		],
		order_by="invited_at DESC",
	)
	return {"invitations": rows, "total": len(rows)}


def send_trusted_reviewer_invitations():
	"""Haftalık scheduler — eligible user'lara yeni ürünler için davet gönder.

	Strateji:
	  - Son 14 günde Active'e geçen Listing'ler
	  - Eligible tier'daki user'lardan henüz davet edilmemiş olanlar
	  - User başına max 3 aktif davet
	"""
	from frappe.utils import add_to_date

	# Son 14 günde Active olmuş listing'ler
	cutoff = add_to_date(now_datetime(), days=-14)
	listings = frappe.get_all(
		"Listing",
		filters={"status": "Active", "modified": [">", cutoff]},
		fields=["name"],
		limit=20,
	)
	if not listings:
		return

	# Eligible reviewer'lar
	eligible = frappe.get_all(
		"Reviewer Reputation",
		filters={"tier": ["in", list(ELIGIBLE_TIERS_FOR_INVITATION)]},
		fields=["user"],
	)
	if not eligible:
		return

	sent = 0
	for rep in eligible:
		# User başına aktif davet sayısı
		active = frappe.db.count(
			"Trusted Reviewer Invitation",
			filters={"user": rep.user, "status": ["in", ["Invited", "Accepted"]]},
		)
		if active >= 3:
			continue
		# İlk eligible listing
		for ln in listings:
			# Bu user için bu listing'e davet var mı?
			if frappe.db.exists(
				"Trusted Reviewer Invitation",
				{"user": rep.user, "listing": ln.name},
			):
				continue
			try:
				invite_trusted_reviewer(user=rep.user, listing=ln.name)
				sent += 1
				break
			except Exception:
				continue
		if sent >= 10:  # haftalık cap
			break
	frappe.logger("tradehub").info(f"trusted_reviewer_invitations: {sent} davet")


@frappe.whitelist(allow_guest=True)
def get_reviewer_profile(user: str):
	"""Belirli kullanıcının reputation profilini döner (public)."""
	if not user:
		frappe.throw("user parametresi zorunlu")
	row = frappe.db.get_value(
		"Reviewer Reputation",
		user,
		["score", "tier", "total_reviews", "helpful_received", "abuse_received", "kyb_verified"],
		as_dict=True,
	)
	if not row:
		return {
			"user": user,
			"score": BASE_SCORE,
			"tier": "Newcomer",
			"total_reviews": 0,
			"helpful_received": 0,
			"abuse_received": 0,
			"kyb_verified": False,
			"exists": False,
		}
	return {
		"user": user,
		"score": int(row.score),
		"tier": row.tier,
		"total_reviews": int(row.total_reviews or 0),
		"helpful_received": int(row.helpful_received or 0),
		"abuse_received": int(row.abuse_received or 0),
		"kyb_verified": bool(row.kyb_verified),
		"exists": True,
	}

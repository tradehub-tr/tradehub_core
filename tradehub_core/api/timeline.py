"""Faz 4 — Multi-stage Timeline (T+0 / T+30 / T+90 / T+180).

Yorumun yaşam döngüsü içinde kullanıcı aynı yoruma update'ler ekler.
Stage'ler: Initial, 30-day, 90-day, Long-term.

Scheduled reminders:
- T+30 ve T+90 noktalarında reviewer'a bildirim
- T+180 (Long-term) için ekstra
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import (
	add_to_date,
	get_datetime,
	now_datetime,
)

from tradehub_core.utils.notify import notify

VALID_STAGES = ("Initial", "30-day", "90-day", "Long-term")


def _ensure_logged_in():
	if frappe.session.user == "Guest":
		frappe.throw(_("Giriş yapın"), frappe.AuthenticationError)


def _determine_stage(submitted_at, now=None) -> str:
	now = now or get_datetime(now_datetime())
	try:
		sub = get_datetime(submitted_at)
	except Exception:
		frappe.log_error("Review submitted_at parse failed in _determine_stage", "timeline")
		return "Initial"
	days = max(0, (now - sub).days)
	if days >= 180:
		return "Long-term"
	if days >= 90:
		return "90-day"
	if days >= 30:
		return "30-day"
	return "Initial"


@frappe.whitelist()
def submit_review_update(
	review: str, body: str, stage: str | None = None, rating=None, aspect_overrides=None
):
	"""Reviewer kendi yorumuna bir update ekler. Stage otomatik tespit edilir
	(submitted_at'a göre), manuel override edilebilir.
	"""
	_ensure_logged_in()
	if not review or not frappe.db.exists("Listing Review", review):
		frappe.throw(_("Yorum bulunamadı"), frappe.DoesNotExistError)
	doc = frappe.get_doc("Listing Review", review)
	if doc.reviewer_user != frappe.session.user and frappe.session.user != "Administrator":
		# Admin de güncelleyebilir test/moderasyon için
		from tradehub_core.api.review import _is_admin

		if not _is_admin():
			frappe.throw(_("Sadece yorumun sahibi güncelleme ekleyebilir"), frappe.PermissionError)

	body = (body or "").strip()
	if len(body) < 10:
		frappe.throw(_("Güncelleme en az 10 karakter olmalı"))

	# Stage belirleme
	if stage and stage in VALID_STAGES:
		final_stage = stage
	else:
		final_stage = _determine_stage(doc.submitted_at)

	# Aspect overrides JSON
	aspects_json = None
	if aspect_overrides:
		if isinstance(aspect_overrides, str):
			aspects_json = aspect_overrides
		elif isinstance(aspect_overrides, dict):
			aspects_json = json.dumps(aspect_overrides, ensure_ascii=False)

	# Rating opsiyonel
	rating_int = None
	if rating not in (None, "", 0):
		try:
			r = int(rating)
			if 1 <= r <= 5:
				rating_int = r
		except (ValueError, TypeError):
			pass

	# Aynı stage için tek update (en yenisi kazanır)
	for u in doc.updates or []:
		if u.stage == final_stage:
			doc.updates.remove(u)
			break

	doc.append(
		"updates",
		{
			"stage": final_stage,
			"rating": rating_int,
			"body": body,
			"aspect_overrides_json": aspects_json,
			"submitted_at": now_datetime(),
		},
	)
	doc.current_stage = final_stage
	doc.latest_update_at = now_datetime()
	doc.flags.system_save = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	# Long-term skoru güncelle
	_recompute_long_term_score(review)

	return {
		"success": True,
		"stage": final_stage,
		"total_updates": len(doc.updates or []),
	}


def _recompute_long_term_score(review_name: str):
	"""90-day ve Long-term update'lerin rating ortalaması = long_term_score."""
	if not review_name or not frappe.db.exists("Listing Review", review_name):
		return
	doc = frappe.get_doc("Listing Review", review_name)
	long_ratings = []
	for u in doc.updates or []:
		if u.stage in ("90-day", "Long-term") and u.rating:
			long_ratings.append(int(u.rating))
	if long_ratings:
		avg = round(sum(long_ratings) / len(long_ratings), 2)
	else:
		avg = 0.0
	frappe.db.set_value("Listing Review", review_name, "long_term_score", avg, update_modified=False)


@frappe.whitelist(allow_guest=True)
def get_review_timeline(review: str):
	"""Public — bir yorumun tüm update'lerini kronolojik olarak döner."""
	if not review or not frappe.db.exists("Listing Review", review):
		frappe.throw(_("Yorum bulunamadı"), frappe.DoesNotExistError)
	doc = frappe.get_doc("Listing Review", review)
	updates = []
	for u in doc.updates or []:
		aspect_data = None
		if u.aspect_overrides_json:
			try:
				aspect_data = json.loads(u.aspect_overrides_json)
			except (ValueError, TypeError):
				pass
		updates.append(
			{
				"stage": u.stage,
				"rating": int(u.rating) if u.rating else None,
				"body": u.body,
				"submitted_at": u.submitted_at,
				"aspect_overrides": aspect_data,
			}
		)
	# Initial olarak ana review de timeline'a eklensin (gösterim için)
	updates.insert(
		0,
		{
			"stage": "Initial",
			"rating": doc.rating,
			"body": doc.body,
			"submitted_at": doc.submitted_at,
			"aspect_overrides": None,
		},
	)
	# Stage sırasıyla sırala
	stage_order = {"Initial": 0, "30-day": 1, "90-day": 2, "Long-term": 3}
	updates.sort(key=lambda x: stage_order.get(x["stage"], 99))
	return {
		"review": doc.name,
		"current_stage": doc.current_stage or "Initial",
		"long_term_score": float(doc.long_term_score or 0),
		"timeline": updates,
	}


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler: T+30 / T+90 / T+180 reminders
# ─────────────────────────────────────────────────────────────────────────────
def _send_reminder(review_doc, stage: str):
	if not review_doc.reviewer_user:
		return
	# Aynı stage için zaten bildirim göndermişse atla — basit yöntem: update var mı?
	for u in review_doc.updates or []:
		if u.stage == stage:
			return
	listing_title = frappe.db.get_value("Listing", review_doc.listing, "title") or review_doc.listing
	try:
		notify(
			recipient_user=review_doc.reviewer_user,
			recipient_role="buyer",
			type="review",
			title=_("Yorumunuzu Güncelleyin ({0})").format(stage),
			message=_("{0} ürünü için yorumunuzu güncellemek ister misiniz?").format(listing_title),
			action_url=f"/app/listing-review/{review_doc.name}",
			reference_doctype="Listing Review",
			reference_name=review_doc.name,
		)
	except Exception:
		frappe.log_error("Timeline stage reminder notification failed", "timeline")
		pass


def _check_and_send(stage: str, min_days: int, max_days: int):
	"""Belirli stage için reminder gönder."""
	now = now_datetime()
	min_date = add_to_date(now, days=-max_days)
	max_date = add_to_date(now, days=-min_days)
	reviews = frappe.get_all(
		"Listing Review",
		filters={
			"status": "Approved",
			"submitted_at": ["between", [min_date, max_date]],
		},
		fields=["name"],
	)
	for r in reviews:
		try:
			doc = frappe.get_doc("Listing Review", r["name"])
			_send_reminder(doc, stage)
		except Exception:
			frappe.log_error(f"Timeline stage reminder failed: review={r['name']} stage={stage}", "timeline")


def send_t30_reminders():
	"""Daily cron: T+30 hatırlatması (30-37 gün arası yorumlara)."""
	_check_and_send("30-day", 30, 37)


def send_t90_reminders():
	"""Daily cron: T+90 hatırlatması."""
	_check_and_send("90-day", 90, 97)


def send_t180_reminders():
	"""Daily cron: T+180 hatırlatması (Long-term)."""
	_check_and_send("Long-term", 180, 187)

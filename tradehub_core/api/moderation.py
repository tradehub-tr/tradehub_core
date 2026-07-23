"""Faz 6 — Auto-Moderation Rules Engine + Image Content Moderation.

Aktif Moderation Rule kayıtları yorum oluşturulduğunda kontrol edilir.
Eşik aşılırsa otomatik action (auto_reject / auto_hide / flag).

Image moderation: yorumdaki görsel'ler için OpenAI Vision API
(api_key set ise) veya stub kontrol (her şey allow).
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime


def _evaluate_rules(review_doc) -> dict:
	"""Aktif Moderation Rule'ları kontrol et."""
	matched_rules = []
	rules = frappe.get_all(
		"Moderation Rule",
		filters={"is_active": 1},
		fields=["name", "trigger_type", "threshold_value", "action", "reason_template", "banned_phrases"],
	)
	for rule in rules:
		hit = False
		if rule["trigger_type"] == "risk_score_high":
			if int(review_doc.risk_score or 0) >= int(rule["threshold_value"] or 80):
				hit = True
		elif rule["trigger_type"] == "abuse_threshold":
			if int(review_doc.abuse_report_count or 0) >= int(rule["threshold_value"] or 5):
				hit = True
		elif rule["trigger_type"] == "banned_phrase":
			body = (review_doc.body or "").lower()
			phrases = (rule["banned_phrases"] or "").lower().split(",")
			if any(p.strip() and p.strip() in body for p in phrases):
				hit = True
		elif rule["trigger_type"] == "reviewer_repeat_rejected":
			if review_doc.reviewer_user:
				cnt = frappe.db.count(
					"Listing Review",
					filters={
						"reviewer_user": review_doc.reviewer_user,
						"status": "Rejected",
					},
				)
				if cnt >= int(rule["threshold_value"] or 5):
					hit = True
		if hit:
			matched_rules.append(rule)
	return {"matched": matched_rules}


def check_auto_rules(doc, method=None):
	"""hooks.py — Listing Review after_insert handler.

	Eşleşen kural varsa belirtilen aksiyonu uygula.
	"""
	if not doc or not doc.name:
		return
	try:
		out = _evaluate_rules(doc)
	except Exception:
		frappe.log_error(title="auto_rules_eval_failed", message=f"review={doc.name}")
		return
	for rule in out["matched"]:
		action = rule["action"]
		reason = rule["reason_template"] or f"Auto: {rule['name']}"
		try:
			if action == "auto_reject":
				frappe.db.set_value(
					"Listing Review",
					doc.name,
					{"status": "Rejected", "rejected_reason": reason},
					update_modified=False,
				)
			elif action == "auto_hide":
				frappe.db.set_value("Listing Review", doc.name, {"status": "Hidden"}, update_modified=False)
			elif action == "flag_for_review":
				# Status'u Pending'de tutar — admin manuel inceler
				pass
			elif action == "suspend_user":
				if doc.reviewer_user:
					frappe.db.set_value("User", doc.reviewer_user, "enabled", 0)
		except Exception:
			frappe.log_error(
				title="auto_rule_action_failed", message=f"review={doc.name} rule={rule['name']}"
			)


# ─────────────────────────────────────────────────────────────────────────────
# Image moderation (OpenAI Vision)
# ─────────────────────────────────────────────────────────────────────────────
def _stub_check_image(image_url: str) -> dict:
	"""Stub: her şey allow."""
	return {"decision": "allow", "nsfw_score": 0.0, "violence_score": 0.0, "text_detected": ""}


def _openai_vision_check(image_url: str, api_key: str) -> dict:
	"""OpenAI Vision ile NSFW/violence/text tespit."""
	import urllib.request

	prompt = (
		"Analyze this image. Return JSON: "
		'{"decision":"allow|reject|manual_review",'
		'"nsfw_score":0-1,"violence_score":0-1,'
		'"text_detected":"text in image"}. '
		"Reject if explicit nudity or graphic violence."
	)
	payload = {
		"model": "gpt-4o-mini",
		"messages": [
			{
				"role": "user",
				"content": [
					{"type": "text", "text": prompt},
					{"type": "image_url", "image_url": {"url": image_url}},
				],
			}
		],
		"response_format": {"type": "json_object"},
		"max_tokens": 200,
	}
	req = urllib.request.Request(
		"https://api.openai.com/v1/chat/completions",
		data=json.dumps(payload).encode("utf-8"),
		headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
	)
	with urllib.request.urlopen(req, timeout=30) as resp:
		data = json.loads(resp.read().decode("utf-8"))
	return json.loads(data["choices"][0]["message"]["content"])


def check_image_content(doc, method=None):
	"""hooks.py — Listing Review Image after_insert handler."""
	if not doc or not doc.image:
		return

	# Translation Settings'ten api_key oku
	api_key = None
	try:
		if frappe.db.table_exists("tabSingles"):
			settings = frappe.get_single("Translation Settings")
			api_key = settings.get_password("openai_api_key", raise_exception=False)
	except Exception:
		frappe.log_error("OpenAI API key fetch failed in check_image_content", "moderation")
		pass

	if api_key:
		try:
			result = _openai_vision_check(doc.image, api_key)
		except Exception as e:
			frappe.log_error(title="vision_check_failed", message=str(e))
			result = _stub_check_image(doc.image)
	else:
		result = _stub_check_image(doc.image)

	# Log kaydı
	try:
		log = frappe.new_doc("Image Moderation Log")
		log.review = doc.parent if doc.parenttype == "Listing Review" else None
		log.image_url = doc.image
		log.decision = result.get("decision", "allow")
		log.nsfw_score = float(result.get("nsfw_score", 0))
		log.violence_score = float(result.get("violence_score", 0))
		log.text_detected = result.get("text_detected", "")
		log.checked_at = now_datetime()
		log.insert(ignore_permissions=True)

		# Reject ise review'u Hidden yap
		if result.get("decision") == "reject" and log.review:
			frappe.db.set_value("Listing Review", log.review, {"status": "Hidden"}, update_modified=False)
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="image_moderation_log_failed", message=f"image={doc.image}")


@frappe.whitelist()
def admin_check_image(image_url: str):
	"""Admin manuel görsel kontrol."""
	from tradehub_core.api.review import _is_admin

	if not _is_admin():
		frappe.throw("Yetkisiz", frappe.PermissionError)
	api_key = None
	try:
		settings = frappe.get_single("Translation Settings")
		api_key = settings.get_password("openai_api_key", raise_exception=False)
	except Exception:
		frappe.log_error("OpenAI API key fetch failed in admin_check_image", "moderation")
		pass
	if api_key:
		return _openai_vision_check(image_url, api_key)
	return _stub_check_image(image_url)


@frappe.whitelist()
def list_active_rules():
	"""Aktif Moderation Rule'ları döner (admin)."""
	from tradehub_core.api.review import _is_admin

	if not _is_admin():
		frappe.throw("Yetkisiz", frappe.PermissionError)
	return frappe.get_all(
		"Moderation Rule",
		filters={"is_active": 1},
		fields=["name", "trigger_type", "threshold_value", "action"],
	)

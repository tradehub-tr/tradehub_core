"""Faz 5 — Slack/Discord/Email webhooks.

site_config'te aşağıdaki anahtarları set ederek aktive edin:
  - slack_review_webhook_url
  - discord_review_webhook_url
  - admin_email (email bildirimleri için)

Webhook URL'leri yoksa fonksiyonlar no-op olur (silent).
"""

from __future__ import annotations

import json

import frappe


def _post_json(url: str, payload: dict, timeout: int = 5):
	import urllib.error
	import urllib.request

	req = urllib.request.Request(
		url,
		data=json.dumps(payload).encode("utf-8"),
		headers={"Content-Type": "application/json"},
		method="POST",
	)
	try:
		with urllib.request.urlopen(req, timeout=timeout) as resp:
			return resp.status, resp.read().decode("utf-8", errors="ignore")
	except (urllib.error.URLError, urllib.error.HTTPError) as e:
		raise RuntimeError(str(e))


def send_slack(message: str, channel: str | None = None) -> bool:
	url = frappe.conf.get("slack_review_webhook_url")
	if not url:
		return False
	payload = {"text": message}
	if channel:
		payload["channel"] = channel
	try:
		_post_json(url, payload)
		return True
	except Exception as e:
		frappe.log_error(title="slack_webhook_failed", message=str(e))
		return False


def send_discord(message: str) -> bool:
	url = frappe.conf.get("discord_review_webhook_url")
	if not url:
		return False
	payload = {"content": message}
	try:
		_post_json(url, payload)
		return True
	except Exception as e:
		frappe.log_error(title="discord_webhook_failed", message=str(e))
		return False


def notify_admin_new_review(doc, method=None):
	"""hooks.py'den çağrılır — yeni Listing Review oluştuğunda admin'e bildirim.

	Sadece risk_score >= 31 (orta+) olanlar için tetiklenir spam'i önler.
	"""
	if not doc or not doc.name:
		return
	try:
		risk = int(doc.risk_score or 0)
	except Exception:
		risk = 0
	if risk < 31:
		return  # düşük riskli yorumlar için bildirim yok

	listing_title = (
		frappe.db.get_value("Listing", doc.listing, "title") or doc.listing if doc.listing else "?"
	)
	risk_label = "Yüksek" if risk >= 61 else "Orta"
	msg = (
		f"🟠 Yeni yorum ({risk_label} risk={risk}) — "
		f"{listing_title} — Puan: {doc.rating}\n"
		f"Reviewer: {doc.reviewer_display_name or doc.reviewer_user}\n"
		f"Body: {(doc.body or '')[:200]}"
	)
	send_slack(msg)
	send_discord(msg)


def flush_pending_notifications():
	"""Cron placeholder — batch flush (şu an her olay anlık gönderiyor).

	Future: queue'lanan bildirimleri toplu gönder.
	"""
	pass


@frappe.whitelist()
def webhook_test(channel: str = "slack"):
	"""Admin için webhook test endpoint'i."""
	from tradehub_core.api.review import _is_admin

	if not _is_admin():
		frappe.throw("Yetkisiz", frappe.PermissionError)
	msg = "✅ Webhook test — TradeHub Review System"
	if channel == "slack":
		ok = send_slack(msg)
	elif channel == "discord":
		ok = send_discord(msg)
	else:
		frappe.throw("Geçersiz kanal")
	return {
		"success": ok,
		"channel": channel,
		"configured": bool(frappe.conf.get(f"{channel}_review_webhook_url")),
	}

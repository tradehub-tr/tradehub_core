"""Bildirim backend'i — Frappe/MariaDB entegrasyon testleri (ayrı test sitesinde koşar).

    bench --site <test-sitesi> run-tests --module tradehub_core.tests.test_notification_backend

Uç fonksiyonları doğrudan çağrılır (yetki `frappe.set_user` ile). Gerçek iki-bağlantılı
eşzamanlılık kanıtı HTTP üzerinden `desing/.../backend-kanit/betikler/api_kanit.py` içindedir.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api.v1 import notification_preferences as prefs_api
from tradehub_core.api.v1 import notification_templates as tpl_api
from tradehub_core.notifications import dispatch, seed, store

BUYER = "nt.buyer@example.com"
EDITOR = "nt.editor@example.com"
VIEWER = "nt.viewer@example.com"
KEY = "rfq.quoted"  # inapp zorunlu + push seçmeli, alıcı olayı


def _user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	u = frappe.get_doc("User", email)
	for r in roles:
		if r not in [x.role for x in u.roles]:
			u.append("roles", {"role": r})
	u.save(ignore_permissions=True)


def _status():
	return frappe.local.response.get("http_status_code") or 200


def _call(fn, *args, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	out = fn(*args, **kwargs)
	status = _status()
	if status < 300:
		# Her HTTP isteği kendi transaction'ıdır; beklenen hata yanıtı (409/422) geri alma yapar.
		# Testte ardışık istekleri taklit etmek için başarılı yazma commit edilir (ayrı test sitesi).
		frappe.db.commit()
	return status, out


class TestNotificationBackend(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		seed.run()
		_user(BUYER, ["Buyer"])
		_user(EDITOR, ["Notification Content Manager"])
		_user(VIEWER, ["Notification Viewer"])
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")

	# ── Tercihler ──
	def test_get_preferences_is_read_only_and_saves_atomically(self):
		frappe.set_user(BUYER)
		frappe.db.delete("Platform Notification Preference", {"user": BUYER})
		s, p = _call(prefs_api.get_preferences)
		self.assertEqual((s, p["revision"]), (200, 0))
		self.assertFalse(frappe.db.exists("Platform Notification Preference", BUYER))
		self.assertNotIn("order.received", {e["key"] for e in p["events"]})  # satıcı olayı
		quiet = {"enabled": True, "start": "22:00", "end": "08:00", "timezone": "Europe/Istanbul"}
		s, p = _call(
			prefs_api.save_preferences,
			events={KEY: {"push": False}},
			frequency="daily",
			quiet=quiet,
			revision=0,
		)
		self.assertEqual((s, p["revision"]), (200, 1))
		self.assertEqual(next(e for e in p["events"] if e["key"] == KEY)["user"], {"push": False})
		s, err = _call(prefs_api.save_preferences, events={}, frequency="daily", quiet=quiet, revision=0)
		self.assertEqual((s, err["error_code"]), (409, "REVISION_CONFLICT"))
		s, err = _call(
			prefs_api.save_preferences,
			events={},
			frequency="daily",
			quiet=dict(quiet, end="22:00"),
			revision=1,
		)
		self.assertEqual((s, err["error_code"]), (422, "VALIDATION_FAILED"))
		self.assertIn("quiet.end", err["field_errors"])

	def test_consent_revoke_is_local_and_sync_is_honest(self):
		frappe.set_user(BUYER)
		s, out = _call(prefs_api.set_commercial_consent, channel="email", granted=False)
		self.assertEqual(s, 200)
		self.assertEqual(out["consent"]["email"]["state"], "geri-cekildi")
		self.assertFalse(out["consent"]["email"]["sync_available"])
		self.assertEqual(out["consent_history"][0]["sync_state"], "basarisiz")
		s, err = _call(prefs_api.retry_consent_sync, channel="email")
		self.assertEqual((s, err["error_code"]), (503, "PROVIDER_UNAVAILABLE"))

	# ── Şablon yönetimi ──
	def test_role_matrix(self):
		frappe.set_user(BUYER)
		with self.assertRaises(frappe.PermissionError):
			tpl_api.list_events()
		frappe.set_user(VIEWER)
		s, out = _call(tpl_api.list_events)
		self.assertEqual((s, out["template_role"]), (200, "salt-okunur"))
		with self.assertRaises(frappe.PermissionError):
			tpl_api.save_draft(KEY, "inapp", "tr", {"title": "x"}, 0)
		frappe.set_user(EDITOR)
		rev = store.load_event(KEY).revision
		with self.assertRaises(frappe.PermissionError):
			tpl_api.publish(KEY, rev)
		with self.assertRaises(frappe.PermissionError):
			tpl_api.restore_version(KEY, 1, rev)

	def test_lifecycle_draft_publish_restore_review(self):
		frappe.set_user(EDITOR)
		t = tpl_api.get_template(KEY)
		fields = dict(t["draft"]["inapp"]["tr"], message="{{reference_no}} için yeni teklif.")
		s, r = _call(tpl_api.save_draft, KEY, "inapp", "tr", fields, t["revision"])
		self.assertEqual(s, 200)
		s, rq = _call(tpl_api.request_publish, KEY, r["revision"])
		self.assertEqual(rq["state"], "onay-bekliyor")
		frappe.set_user("Administrator")
		s, pub = _call(tpl_api.publish, KEY, r["revision"])
		self.assertEqual(s, 200)
		v = pub["version"]
		s, again = _call(tpl_api.publish, KEY, r["revision"])
		self.assertEqual((s, again["error_code"]), (409, "REVISION_CONFLICT"))
		s, d = _call(
			tpl_api.save_draft,
			KEY,
			"inapp",
			"tr",
			dict(fields, message="DEĞİŞTİ {{reference_no}}"),
			pub["revision"],
		)
		live = tpl_api.get_template(KEY)["published"]["inapp"]["tr"]["message"]
		self.assertEqual(live, fields["message"])  # taslak canlıyı değiştirmez
		s, rest = _call(tpl_api.restore_version, KEY, v, d["revision"])
		self.assertEqual(rest["draft"]["inapp"]["tr"]["message"], fields["message"])
		self.assertEqual(tpl_api.get_event(KEY)["publish"]["version"], v)  # canlı aynı

	def test_publish_blocked_by_unknown_variable_and_unsafe_html_cleaned(self):
		frappe.set_user("Administrator")
		key = "store.moderation_result"
		t = tpl_api.get_template(key)
		email = dict(t["draft"]["email"]["tr"], html=t["draft"]["email"]["tr"]["html"] + "<script>x</script>")
		s, r = _call(tpl_api.save_draft, key, "email", "tr", email, t["revision"])
		self.assertNotIn("<script", r["draft"]["email"]["tr"]["html"])
		bad = dict(t["draft"]["inapp"]["tr"], message="{{yok_degisken}}")
		s, r = _call(tpl_api.save_draft, key, "inapp", "tr", bad, r["revision"])
		s, err = _call(tpl_api.publish, key, r["revision"])
		self.assertEqual(s, 422)
		self.assertTrue(any(i["kind"] == "unknown_variable" for i in err["blocking"]))

	# ── Gönderim ──
	def test_dispatch_respects_preference_and_dedupes(self):
		frappe.set_user("Administrator")
		key = "rfq.quoted"
		if not tpl_api.get_event(key)["publish"]["version"]:
			tpl_api.publish(key, store.load_event(key).revision)
		frappe.db.delete("Platform Notification Preference", {"user": BUYER})
		data = {
			"recipient_name": "B",
			"reference_no": "RFQ-T1",
			"event_date": "1",
			"action_url": "https://istoc.localhost/x",
		}
		out = dispatch.emit(key, BUYER, data, "RFQ-T1:quoted", meta={"type": "rfq"})
		self.assertEqual(out["handled"], {"inapp", "email", "push", "sms"})  # email/sms kapalı da "handled"
		rows = frappe.get_all(
			"Platform Notification Delivery",
			filters={"occurrence_id": "RFQ-T1:quoted"},
			fields=["channel", "status", "name"],
		)
		self.assertEqual(sorted(r.channel for r in rows), ["inapp", "push"])
		again = dispatch.emit(key, BUYER, data, "RFQ-T1:quoted")
		self.assertEqual(again["deliveries"], [])
		inapp = next(r for r in rows if r.channel == "inapp")
		self.assertEqual(dispatch.process(inapp.name), "sent")
		self.assertEqual(dispatch.process(inapp.name), "sent")  # ikinci işleme yeni bildirim üretmez
		self.assertEqual(
			frappe.db.count(
				"Platform Notification", {"recipient_user": BUYER, "message": ["like", "%RFQ-T1%"]}
			),
			1,
		)
		push = next(r for r in rows if r.channel == "push")
		self.assertEqual(dispatch.process(push.name), "failed")
		self.assertEqual(
			frappe.db.get_value("Platform Notification Delivery", push.name, "error_code"),
			"PROVIDER_UNAVAILABLE",
		)

	def test_management_records_not_writable_outside_service(self):
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Platform Notification Event", KEY)
		doc.channels = json.dumps({"inapp": "kapali", "email": "kapali", "push": "kapali", "sms": "kapali"})
		with self.assertRaises(frappe.PermissionError):
			doc.save()

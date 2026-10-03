"""Bildirim şablon dili, doğrulama, sanitizer ve zamanlama — saf birim testleri.

Ortak fixture `tests/fixtures/notification_template_cases.json` panel testleriyle (admin-panel
`notificationTemplateParity.test.js`) aynı dosyadır: iki taraf aynı girdide aynı sonucu vermeli.
"""

import json
import os
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from tradehub_core.notifications import catalog, schedule, template_lang, validation
from tradehub_core.notifications.sanitize import clean_html

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "notification_template_cases.json")


def _cases():
	with open(FIXTURE, encoding="utf-8") as fh:
		return json.load(fh)


class TestTemplateLanguage(unittest.TestCase):
	def test_fixture_render_cases(self):
		for case in _cases()["render"]:
			with self.subTest(case["name"]):
				self.assertEqual(
					template_lang.render(case["template"], case["scope"], case.get("mode", "text")),
					case["expected"],
				)

	def test_fixture_structure_cases(self):
		for case in _cases()["structure"]:
			with self.subTest(case["name"]):
				self.assertEqual(template_lang.structure_issue(case["template"]), case["issue"])

	def test_fixture_url_cases(self):
		variables = [{"name": "order_url", "type": "url"}, {"name": "order_no", "type": "text"}]
		for case in _cases()["url"]:
			with self.subTest(case["value"]):
				self.assertEqual(template_lang.url_template_ok(case["value"], variables), case["ok"])

	def test_nested_each_and_if(self):
		tpl = "{{#each groups}}[{{group.title}}{{#each group.items}}<{{item.title}}>{{/each}}{{#if group.more}}+{{group.more_n}}{{/if}}]{{/each}}"
		scope = {
			"groups": [
				{"title": "A", "items": [{"title": "a1"}, {"title": "a2"}], "more": True, "more_n": 3},
				{"title": "B", "items": [], "more": False},
			]
		}
		self.assertEqual(template_lang.render(tpl, scope), "[A<a1><a2>+3][B]")

	def test_no_attribute_walk_or_code(self):
		class Evil:
			secret = "x"

		self.assertEqual(template_lang.render("{{obj.secret}}{{obj.__class__}}", {"obj": Evil()}), "")
		self.assertEqual(template_lang.render("{{a._private}}", {"a": {"_private": "x"}}), "")
		# Jinja/fonksiyon sözdizimi belirteç değildir, metin olarak kalır.
		self.assertEqual(template_lang.render("{{ 7*7 }}{% if x %}", {}), "{{ 7*7 }}{% if x %}")

	def test_html_mode_escapes_values(self):
		out = template_lang.render("<p>{{name}}</p>", {"name": '<script>alert(1)</script>"'}, "html")
		self.assertEqual(out, "<p>&lt;script&gt;alert(1)&lt;/script&gt;&quot;</p>")

	def test_depth_and_loop_limits(self):
		deep = "{{#if a}}" * 5 + "x" + "{{/if}}" * 5
		self.assertEqual(template_lang.structure_issue(deep), "too_deep")
		with self.assertRaises(template_lang.RenderLimitError):
			template_lang.render(
				"{{#each xs}}.{{/each}}", {"xs": list(range(template_lang.MAX_LOOP_ITEMS + 1))}
			)

	def test_safe_url_after_render(self):
		self.assertEqual(template_lang.safe_url("javascript:alert(1)"), "")
		self.assertEqual(template_lang.safe_url("//evil.example"), "")
		self.assertEqual(template_lang.safe_url("data:text/html,1"), "")
		self.assertEqual(template_lang.safe_url("https://istoc.com/a"), "https://istoc.com/a")
		self.assertEqual(template_lang.safe_url("/pages/x"), "/pages/x")


class TestSanitizer(unittest.TestCase):
	def test_strips_dangerous(self):
		self.assertNotIn("script", clean_html("<script>alert(1)</script><p onclick='x'>a</p>"))
		self.assertEqual(clean_html('<a href="javascript:alert(1)">x</a>'), "<a>x</a>")
		self.assertEqual(clean_html('<a href="//evil.example">x</a>'), "<a>x</a>")
		self.assertEqual(clean_html('<a href="data:text/html,1">x</a>'), "<a>x</a>")

	def test_keeps_email_layout(self):
		html = '<table role="presentation" cellpadding="0" bgcolor="#fff"><tr><td class="kv" style="color:#000;position:fixed">{{x}}</td></tr></table>'
		out = clean_html(html)
		self.assertIn('role="presentation"', out)
		self.assertIn('class="kv"', out)
		self.assertIn("color:#000;", out)
		self.assertNotIn("position", out)
		self.assertIn("{{x}}", out)
		self.assertIn('<a href="{{order_url}}">a</a>', clean_html('<a href="{{order_url}}">a</a>'))


class TestValidation(unittest.TestCase):
	def test_unknown_and_missing_required(self):
		vars_ = catalog.variables_for("order.confirm_reminder")
		data = {"title": "x", "message": "{{ordr_no}}", "action_label": "", "action_url": ""}
		kinds = [i["kind"] for i in validation.validate_scope(data, "inapp", "tr", vars_, ["order_no"])]
		self.assertIn("unknown_variable", kinds)
		self.assertIn("missing_required_variable", kinds)

	def test_action_label_url_pair(self):
		vars_ = catalog.GENERIC_VARIABLES
		data = {"title": "t", "message": "{{reference_no}}", "action_label": "Aç", "action_url": ""}
		kinds = [i["kind"] for i in validation.validate_scope(data, "inapp", "tr", vars_, [])]
		self.assertIn("missing_action_url", kinds)

	def test_sms_unicode_and_segments(self):
		vars_ = catalog.GENERIC_VARIABLES
		data = {"text": "Şifreniz " + "ç" * 80 + " {{reference_no}}"}
		kinds = [i["kind"] for i in validation.validate_scope(data, "sms", "tr", vars_, [])]
		self.assertIn("sms_unicode", kinds)
		self.assertIn("sms_segments", kinds)
		info = validation.sms_info("Tutar ₺10", currency_as_text=True)
		self.assertFalse(info["unicode"])

	def test_normalize_rejects_unknown_field_and_cleans_html(self):
		with self.assertRaises(validation.FieldError):
			validation.normalize_fields("push", {"title": "a", "html": "<p>x</p>"})
		out = validation.normalize_fields(
			"email", {"subject": "s", "html": "<p onclick=1>x</p><script>1</script>"}
		)
		self.assertEqual(out["html"], "<p>x</p>1")
		self.assertEqual(out["preheader"], "")

	def test_conditional_branches_application_result(self):
		key = "store.application_result"
		approved = {
			"application_approved": True,
			"documents_required": False,
			"panel_url": "https://x",
			"approved_at": "1",
		}
		self.assertEqual(
			validation.missing_event_data(
				key, "email", {**approved, "company_name": "A", "application_no": "1"}
			),
			[],
		)
		docs = {
			"application_approved": False,
			"documents_required": True,
			"company_name": "A",
			"application_no": "1",
		}
		self.assertEqual(
			validation.missing_event_data(key, "email", docs), ["documents_url", "rejection_reason"]
		)

	def test_seed_drafts_have_no_blocking_issues(self):
		from tradehub_core.notifications import content_seed

		for ev in catalog.EVENTS:
			with self.subTest(ev["key"]):
				tree, states, _rep = content_seed.seed_for(ev)
				res = validation.validate_all(ev["key"], ev["channels"], states, tree)
				self.assertEqual(res["blocking"], [], res["blocking"])
				self.assertNotIn("hazir", states.values())


class TestSchedule(unittest.TestCase):
	TZ = "Europe/Istanbul"

	def test_quiet_over_midnight(self):
		at = lambda h, m=0: datetime(2026, 10, 3, h, m, tzinfo=ZoneInfo(self.TZ))  # noqa: E731
		self.assertTrue(schedule.in_quiet(at(23), "22:00", "08:00", self.TZ))
		self.assertTrue(schedule.in_quiet(at(7, 59), "22:00", "08:00", self.TZ))
		self.assertFalse(schedule.in_quiet(at(8), "22:00", "08:00", self.TZ))
		self.assertFalse(schedule.in_quiet(at(12), "22:00", "08:00", self.TZ))
		self.assertEqual(schedule.quiet_end(at(23), "22:00", "08:00", self.TZ).hour, 8)

	def test_daily_weekly_next(self):
		now = datetime(2026, 10, 3, 9, 0, tzinfo=ZoneInfo(self.TZ))  # cumartesi
		self.assertEqual(schedule.next_daily(now, "08:00", self.TZ).day, 4)
		weekly = schedule.next_weekly(now, "08:00", "monday", self.TZ)
		self.assertEqual((weekly.day, weekly.weekday()), (5, 0))

	def test_dst_gap_and_overlap(self):
		tz = "Europe/Berlin"
		# 29 Mart 2026 02:30 yerel saat yok (DST ileri) → geçerli bir ana kayar, hata yok.
		before = datetime(2026, 3, 29, 1, 0, tzinfo=ZoneInfo(tz))
		nxt = schedule.next_daily(before, "02:30", tz)
		self.assertEqual(nxt.date().day, 29)
		self.assertGreater(nxt, before)
		# 25 Ekim 2026 geri dönüş: 08:00 tek kez üretilir.
		day = datetime(2026, 10, 25, 0, 30, tzinfo=ZoneInfo(tz))
		self.assertEqual(schedule.next_daily(day, "08:00", tz).hour, 8)

	def test_period_keys(self):
		due = datetime(2026, 10, 5, 8, 0, tzinfo=ZoneInfo(self.TZ))
		self.assertEqual(schedule.period_key("daily", due, self.TZ), "2026-10-05")
		self.assertEqual(schedule.period_key("weekly", due, self.TZ), "2026-W41")

"""T-123 — RUM toplama ucu testleri (`tradehub_core.api.rum.collect`).

Zincirin bu görevle bağlanan üç halkasını sınar:

1. `Media RUM Sample` DocType gerçekten kurulu ve alan kümesi
   `rum.DOCTYPE_FIELDS` sözleşmesiyle birebir (tabDocField'dan ÖLÇÜLÜR).
2. Uç: geçerli gövde 200 + kayıt; geçersiz gövde 200 + kayıt YOK (hata
   ayrıntısı sızdırılmaz); karışık gövdede geçerliler yazılır.
3. Hız sınırı: pencere dolunca `TooManyRequestsError` (HTTP 429).
4. Misafir erişimi: fonksiyon `frappe.guest_methods`'ta kayıtlı ve misafir
   oturumuyla çağrıldığında kayıt yazabiliyor.

Koşturma:
	docker exec istoc-dev-backend-1 bench --site istoc.localhost \\
		run-tests --module tradehub_core.tests.test_rum_endpoint
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import rate_limit as rl
from tradehub_core.api import rum as rum_api
from tradehub_core.media.pipeline.delivery import rum

DOCTYPE = "Media RUM Sample"

#: Geçerli bir örnek — `rum.SCHEMA`'ya uygun (rapor 60 §5.2'deki örnek gövde).
VALID_SAMPLE = {
	"metric": "LCP",
	"value": 2431.8,
	"route": "/urun/:slug",
	"device_class": "phone",
	"viewport_width": 390,
	"sample_rate": 0.1,
	"dpr": 2.63,
	"connection": "4g",
	"navigation_type": "navigate",
	"session_token": "ab12cd34ef56ab12cd34ef56ab12cd34",
	"lcp_region": "product_detail/main_image",
	"lcp_profile": "w1280",
	"lcp_format": "webp",
	"engine_version": "media-engine-1.2.3",
}


class _FakeRequest:
	"""`collect()` gövdeyi `frappe.local.request.get_data()` ile okur;
	`rate_limit._bucket_identity` ise `frappe.local.request.headers`e bakar.
	İkisini de karşılayan asgari istek nesnesi."""

	method = "POST"

	def __init__(self, body: str, headers: dict[str, str] | None = None):
		self._body = body
		self.headers = headers or {}

	def get_data(self, as_text: bool = False):
		return self._body if as_text else self._body.encode("utf-8")


def _body(*samples: dict) -> str:
	return json.dumps({"samples": list(samples)})


class RumEndpointTests(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._orig_user = frappe.session.user
		self._orig_request = getattr(frappe.local, "request", None)
		# Sistem işi gerekçesi: test bakımı — tenant izolasyonu değil,
		# test öncesi/sonrası kayıt kümesi farkını ölçmek için tüm adlar gerekir.
		self._before = set(frappe.get_all(DOCTYPE, pluck="name"))
		self._reset_buckets()
		self.addCleanup(self._restore)

	def _restore(self):
		frappe.set_user(self._orig_user)
		frappe.local.request = self._orig_request
		self._reset_buckets()
		yeni = set(frappe.get_all(DOCTYPE, pluck="name")) - self._before
		if yeni:
			frappe.db.delete(DOCTYPE, {"name": ("in", list(yeni))})

	def _reset_buckets(self):
		# Hem admin hem misafir kovası — testler her iki kimlikle de çağırıyor.
		for identity in ("Administrator", "Guest:_unresolved"):
			rl.reset_bucket("media_rum_collect", identity)

	def _call(self, body: str, user: str = "Guest") -> dict:
		frappe.set_user(user)
		frappe.local.request = _FakeRequest(body)
		return rum_api.collect()

	def _new_records(self) -> list[str]:
		return sorted(set(frappe.get_all(DOCTYPE, pluck="name")) - self._before)

	# ── 1. DocType kuruldu ve sözleşmeyle birebir ─────────────────────

	def test_doctype_installed_with_contract_fields(self):
		"""tabDocField'dan ÖLÇ: alan kümesi rum.DOCTYPE_FIELDS ile aynı."""
		self.assertTrue(frappe.db.exists("DocType", DOCTYPE), "Media RUM Sample kurulmamış")
		db_fields = set(
			frappe.get_all(
				"DocField",
				filters={
					"parent": DOCTYPE,
					"fieldtype": ("not in", ("Section Break", "Column Break", "Tab Break")),
				},
				pluck="fieldname",
			)
		)
		self.assertEqual(db_fields, set(rum.doctype_field_names()))
		self.assertEqual(len(db_fields), len(rum.DOCTYPE_FIELDS))
		# Şema ile saklama aynı şeyi söylüyor mu (rum.py'nin kendi denetimi)
		self.assertEqual(rum.doctype_matches_sample(), ())

	def test_doctype_has_no_link_fields(self):
		"""DOCTYPE_DESIGN kararı: kayıt hiçbir kullanıcıya/belgeye bağlanamaz."""
		links = frappe.get_all(
			"DocField",
			filters={"parent": DOCTYPE, "fieldtype": ("in", ("Link", "Dynamic Link"))},
			pluck="fieldname",
		)
		self.assertEqual(links, [])

	# ── 2. Geçerli gövde → 200 + kayıt ────────────────────────────────

	def test_valid_body_creates_record(self):
		out = self._call(_body(VALID_SAMPLE))
		self.assertEqual(out, {"ok": True})
		yeni = self._new_records()
		self.assertEqual(len(yeni), 1)
		doc = frappe.get_doc(DOCTYPE, yeni[0])
		self.assertEqual(doc.metric, "LCP")
		self.assertEqual(doc.route, "/urun/:slug")
		self.assertEqual(doc.device_class, "phone")
		self.assertEqual(doc.viewport_bucket, 390)  # 390 → kova alt sınırı 390
		self.assertEqual(doc.rating, "good")  # LCP 2431.8 <= 2500 (web.dev iyi eşiği)
		self.assertEqual(doc.lcp_profile, "w1280")
		self.assertEqual(doc.sample_rate, 0.1)

	def test_session_token_stored_only_as_hash(self):
		"""Ham token SAKLANMAZ: kayda tuzlanmış özetin ilk 12 hex'i yazılır."""
		self._call(_body(VALID_SAMPLE))
		doc = frappe.get_doc(DOCTYPE, self._new_records()[0])
		self.assertEqual(len(doc.session_bucket), 12)
		self.assertNotIn(doc.session_bucket, VALID_SAMPLE["session_token"])
		beklenen = rum.token_hash(VALID_SAMPLE["session_token"], salt=rum_api._salt())
		self.assertEqual(doc.session_bucket, beklenen)

	# ── 3. Geçersiz gövde → 200 + kayıt YOK ───────────────────────────

	def test_pii_field_rejected_silently(self):
		kirli = dict(VALID_SAMPLE, url="https://istoc.localhost/urun/x?q=gizli")
		out = self._call(_body(kirli))
		self.assertEqual(out, {"ok": True})  # hata ayrıntısı sızmaz
		self.assertEqual(self._new_records(), [])

	def test_unknown_metric_rejected_silently(self):
		out = self._call(_body(dict(VALID_SAMPLE, metric="FID")))
		self.assertEqual(out, {"ok": True})
		self.assertEqual(self._new_records(), [])

	def test_malformed_json_returns_ok_without_record(self):
		out = self._call("bu json değil {{{")
		self.assertEqual(out, {"ok": True})
		self.assertEqual(self._new_records(), [])

	def test_empty_body_returns_ok_without_record(self):
		out = self._call("")
		self.assertEqual(out, {"ok": True})
		self.assertEqual(self._new_records(), [])

	def test_oversize_body_dropped(self):
		sisik = _body(dict(VALID_SAMPLE, engine_version="x" * 20)) + " " * (17 * 1024)
		out = self._call(sisik)
		self.assertEqual(out, {"ok": True})
		self.assertEqual(self._new_records(), [])

	def test_mixed_batch_keeps_valid_drops_invalid(self):
		"""Tek bozuk örnek 19 geçerli ölçümü çöpe atmasın (rapor 60 §5.3/2)."""
		gecerli2 = dict(VALID_SAMPLE, metric="CLS", value=0.12)
		bozuk = dict(VALID_SAMPLE, device_class="smart-tv")
		out = self._call(_body(VALID_SAMPLE, bozuk, gecerli2))
		self.assertEqual(out, {"ok": True})
		self.assertEqual(len(self._new_records()), 2)

	def test_batch_truncated_at_20(self):
		"""İstemci sınırı MAX_BATCH=20 — fazlası elle kurcalanmış gövdedir."""
		out = self._call(_body(*([VALID_SAMPLE] * 25)))
		self.assertEqual(out, {"ok": True})
		self.assertEqual(len(self._new_records()), 20)

	# ── 4. Günlük kota ────────────────────────────────────────────────

	def test_daily_cap_drops_new_samples(self):
		key = rum_api._quota_key()
		cache = frappe.cache()
		onceki = cache.get_value(key)
		try:
			cache.delete_value(key)
			cache.set_value(key, rum_api._daily_cap(), expires_in_sec=120)
			out = self._call(_body(VALID_SAMPLE))
			self.assertEqual(out, {"ok": True})
			self.assertEqual(self._new_records(), [])
		finally:
			cache.delete_value(key)
			if onceki is not None:
				cache.set_value(key, onceki, expires_in_sec=rum_api._QUOTA_TTL_SECONDS)

	# ── 5. Hız sınırı ─────────────────────────────────────────────────

	def test_rate_limit_exceeded_raises_429(self):
		"""Pencere içinde RATE_LIMIT_MAX_CALLS çağrı geçer, sonraki 429 atar."""
		for _ in range(rum_api.RATE_LIMIT_MAX_CALLS):
			self._call("")  # geçersiz gövde: sayaç işler ama kayıt yazılmaz
		with self.assertRaises(rl.TooManyRequestsError):
			self._call("")
		self.assertEqual(self._new_records(), [])

	def test_rate_limit_bucket_is_per_identity(self):
		"""Misafir kovası dolunca Administrator kovası etkilenmez."""
		for _ in range(rum_api.RATE_LIMIT_MAX_CALLS):
			self._call("")
		with self.assertRaises(rl.TooManyRequestsError):
			self._call("")
		# Aynı pencerede farklı kimlik hâlâ geçer
		out = self._call(_body(VALID_SAMPLE), user="Administrator")
		self.assertEqual(out, {"ok": True})
		self.assertEqual(len(self._new_records()), 1)

	# ── 6. Misafir erişimi ────────────────────────────────────────────

	def test_collect_is_guest_whitelisted_post_only(self):
		self.assertIn(rum_api.collect, frappe.guest_methods)
		self.assertIn(rum_api.collect, frappe.whitelisted)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func.get(rum_api.collect), ["POST"])

	def test_guest_written_record_has_no_identity(self):
		"""Misafir yazar; owner=Guest olur ve kayıt kimlik alanı taşımaz."""
		self._call(_body(VALID_SAMPLE), user="Guest")
		doc = frappe.get_doc(DOCTYPE, self._new_records()[0])
		self.assertEqual(doc.owner, "Guest")

	# ── 7. Saklama ────────────────────────────────────────────────────

	def test_purge_expired_samples_deletes_only_old_rows(self):
		self._call(_body(VALID_SAMPLE))
		yeni = self._new_records()
		self.assertEqual(len(yeni), 1)
		# Taze kayıt silinmez
		self.assertEqual(rum_api.purge_expired_samples(), 0)
		self.assertTrue(frappe.db.exists(DOCTYPE, yeni[0]))
		# Kaydı 31 gün geriye tarihle → silinir (creation'ı elle ez)
		frappe.db.set_value(
			DOCTYPE,
			yeni[0],
			"creation",
			frappe.utils.add_days(frappe.utils.now_datetime(), -31),
			update_modified=False,
		)
		self.assertEqual(rum_api.purge_expired_samples(), 1)
		self.assertFalse(frappe.db.exists(DOCTYPE, yeni[0]))

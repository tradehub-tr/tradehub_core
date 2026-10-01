"""MOGEM-981 — toplu yükleme job temizliği ilanları yetim bırakmamalı.

Eski temizlik 90 günlük job'ları `force=True` ile siliyordu; `Listing.created_by_bulk_job` var olmayan
job'ı gösterince ilanın her kaydı `LinkValidationError` (417) ile düşüyordu. Bu testler:
temizliğin bağlı başlığı koruduğunu, bağsız job'ı sildiğini, onarımın kilitli ilanı açtığını ve
bekçinin yetimi yakaladığını doğrular.

Görev ve onarım her job'dan sonra commit'ler; testin izolasyonu bozulmasın diye commit/rollback
susturulur, FrappeTestCase'in kendi geri alması her şeyi temizler.
"""

from __future__ import annotations

import itertools
import unittest
from unittest.mock import patch

try:
	from frappe.tests.utils import FrappeTestCase

	HAS_FRAPPE = True
except ImportError:
	HAS_FRAPPE = False

if HAS_FRAPPE:
	import frappe
	from frappe.utils import add_days, now_datetime

	from tradehub_core.bulk_import import api as bulk_api
	from tradehub_core.bulk_import import persister, repair, tasks
	from tradehub_core.utils import orphan_links

SELLERS = (
	("test_m981_a@example.com", "TST-M981-A"),
	("test_m981_b@example.com", "TST-M981-B"),
)


def _ensure_seller(user: str, code: str) -> str:
	if not frappe.db.exists("User", user):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": user,
				"first_name": "M981",
				"send_welcome_email": 0,
				"enabled": 1,
				"roles": [{"role": "Marketplace Seller"}],
			}
		).insert(ignore_permissions=True)
	if name := frappe.db.get_value("Admin Seller Profile", {"user": user}, "name"):
		return name
	return (
		frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"user": user,
				"email": user,
				"seller_name": code,
				"seller_code": code,
				"status": "Active",
				"company_name": f"{code} Co",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


@unittest.skipUnless(HAS_FRAPPE, "Frappe context required")
class TestMogem981OrphanJobs(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.seller_a, cls.seller_b = (_ensure_seller(u, c) for u, c in SELLERS)
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		self._sku = 0
		# FrappeTestCase yalnız sınıf sonunda geri alır; her test kendi kayıt noktasına döner.
		# Önce kaydedilen temizlik en son çalışır — susturma yamaları kalktıktan sonra.
		frappe.db.savepoint("m981")
		self.addCleanup(frappe.db.rollback, save_point="m981")
		for target in ("commit", "rollback"):
			p = patch.object(frappe.db, target, lambda *a, **k: None)
			p.start()
			self.addCleanup(p.stop)

	# ── yardımcılar ──────────────────────────────────────────────

	def _job(self, seller: str, *, days_old: int = 91, status: str = "Completed") -> str:
		data = frappe.get_doc(
			{"doctype": "File", "file_name": "m981.xlsx", "content": b"x", "is_private": 1}
		).insert(ignore_permissions=True)
		job = frappe.get_doc(
			{
				"doctype": "Bulk Import Job",
				"seller_profile": seller,
				"data_file": data.file_url,
				"file_format": "xlsx",
				"status": status,
				"completed_at": add_days(now_datetime(), -days_old),
				"error_details": [
					{"row_number": 2, "sku": "X", "error_type": "validation", "error_message": "e"}
				],
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "m981-hatalar.xlsx",
				"content": b"y",
				"is_private": 1,
				"attached_to_doctype": "Bulk Import Job",
				"attached_to_name": job.name,
			}
		).insert(ignore_permissions=True)
		return job.name

	def _listing(self, seller: str, job: str) -> str:
		self._sku += 1
		row = {
			"sku": f"M981-{frappe.generate_hash(length=6)}-{self._sku}",
			"title": "M981 Ürün",
			"base_price": "10",
		}
		return persister.create_listing(row, seller, job)

	def _orphan(self, seller: str, n: int = 2) -> tuple[str, list[str]]:
		"""Eski hatayı birebir kur: job'ı zorla sil, ilanlar yetim kalsın."""
		job = self._job(seller)
		listings = [self._listing(seller, job) for _ in range(n)]
		frappe.delete_doc("Bulk Import Job", job, force=True, delete_permanently=True)
		# Link kontrolü istek içi değer önbelleğini kullanır; gerçekte silme gece görevinde,
		# kayıt satıcının ayrı isteğinde olur — testte o ayrımı önbelleği boşaltarak kurarız.
		frappe.db.value_cache.clear()
		return job, listings

	def _save(self, listing: str) -> None:
		doc = frappe.get_doc("Listing", listing)
		doc.title = f"{doc.title} ."
		doc.save(ignore_permissions=True)

	# ── kök neden ────────────────────────────────────────────────

	def test_force_deleted_job_locks_listing_with_417(self):
		_job, (listing, _) = self._orphan(self.seller_a)
		with self.assertRaises(frappe.LinkValidationError) as ctx:
			self._save(listing)
		self.assertEqual(ctx.exception.http_status_code, 417)

	def test_frappe_blocks_unforced_delete_of_linked_job(self):
		"""İkinci emniyet kemeri: Custom Field bağlantısını da Frappe'nin kendi kontrolü görüyor."""
		job = self._job(self.seller_a)
		self._listing(self.seller_a, job)
		with self.assertRaises(frappe.LinkExistsError):
			frappe.delete_doc("Bulk Import Job", job, delete_permanently=True)

	# ── temizlik ─────────────────────────────────────────────────

	def test_cleanup_keeps_linked_header_and_listing_stays_editable(self):
		job = self._job(self.seller_a)
		listing = self._listing(self.seller_a, job)
		tasks.cleanup_old_bulk_import_jobs()
		self.assertTrue(frappe.db.exists("Bulk Import Job", job))
		self._save(listing)

	def test_cleanup_purges_artifacts_of_kept_job(self):
		job = self._job(self.seller_a)
		self._listing(self.seller_a, job)
		data_file = frappe.db.get_value("Bulk Import Job", job, "data_file")
		tasks.cleanup_old_bulk_import_jobs()
		row = frappe.db.get_value("Bulk Import Job", job, ["data_file", "artifacts_purged_at"], as_dict=True)
		self.assertIsNone(row.data_file)
		self.assertIsNotNone(row.artifacts_purged_at)
		self.assertFalse(frappe.db.exists("Bulk Import Job Error", {"parent": job}))
		self.assertFalse(frappe.db.exists("File", {"attached_to_name": job}))
		self.assertFalse(frappe.db.exists("File", {"file_url": data_file}))

	def test_cleanup_deletes_unlinked_job_with_its_upload(self):
		job = self._job(self.seller_a)
		data_file = frappe.db.get_value("Bulk Import Job", job, "data_file")
		result = tasks.cleanup_old_bulk_import_jobs()
		self.assertFalse(frappe.db.exists("Bulk Import Job", job))
		self.assertFalse(frappe.db.exists("File", {"file_url": data_file}))
		self.assertGreaterEqual(result["silindi"], 1)

	def test_cleanup_ignores_recent_and_unfinished_jobs(self):
		recent = self._job(self.seller_a, days_old=10)
		running = self._job(self.seller_a, status="Running")
		tasks.cleanup_old_bulk_import_jobs()
		for job in (recent, running):
			self.assertIsNone(frappe.db.get_value("Bulk Import Job", job, "artifacts_purged_at"))
			self.assertTrue(frappe.db.exists("Bulk Import Job Error", {"parent": job}))

	def test_cleanup_stops_at_time_budget_and_resumes_next_night(self):
		jobs = [self._job(self.seller_a, days_old=200 + i) for i in range(3)]
		for job in jobs:
			self._listing(self.seller_a, job)
		# İlk partiden sonra bütçe dolmuş gibi: saat bir kez okunur (bitiş), bir kez kontrol, sonra "geç".
		clock = itertools.chain([0, 0], itertools.repeat(10_000))
		with patch.object(tasks.time, "monotonic", lambda: next(clock)):
			first = tasks.cleanup_old_bulk_import_jobs(batch_size=2, time_budget=60)
		second = tasks.cleanup_old_bulk_import_jobs(batch_size=2)
		self.assertEqual(first["korundu"], 2)
		self.assertGreaterEqual(second["korundu"], 1)
		stamped = frappe.get_all(
			"Bulk Import Job", filters={"name": ["in", jobs]}, pluck="artifacts_purged_at"
		)
		self.assertTrue(all(stamped))

	def test_cleanup_does_not_spin_on_a_failing_job(self):
		job = self._job(self.seller_a)
		with patch.object(tasks, "_cleanup_job", side_effect=RuntimeError("bozuk")):
			result = tasks.cleanup_old_bulk_import_jobs(batch_size=1, time_budget=5)
		self.assertEqual(
			result["hata"],
			frappe.db.count(
				"Bulk Import Job",
				{
					"artifacts_purged_at": ["is", "not set"],
					"completed_at": ["<", add_days(now_datetime(), -90)],
					"status": ["in", ["Completed", "Failed", "Partial"]],
				},
			),
		)
		self.assertTrue(frappe.db.exists("Bulk Import Job", job))

	# ── onarım ───────────────────────────────────────────────────

	def test_repair_restores_header_and_unlocks_listing(self):
		job, (listing, _) = self._orphan(self.seller_a)
		repair.restore_orphan_jobs()
		row = frappe.db.get_value(
			"Bulk Import Job",
			job,
			["seller_profile", "status", "inserted_count", "error_summary"],
			as_dict=True,
		)
		self.assertEqual(row.seller_profile, self.seller_a)
		self.assertEqual(row.status, "Completed")
		self.assertEqual(row.inserted_count, 2)
		self.assertIn("MOGEM-981", row.error_summary)
		self._save(listing)

	def test_repair_is_idempotent(self):
		self._orphan(self.seller_a)
		repair.restore_orphan_jobs()
		self.assertEqual(repair.restore_orphan_jobs(), {"onarildi": 0, "atlandi": 0, "ilan": 0})

	def test_repair_skips_job_linked_by_two_sellers(self):
		# B'nin job'ı silmeden ÖNCE açılır: sonra açılsa geri alınan sayaçla silinen adı alırdı.
		other = self._listing(self.seller_b, self._job(self.seller_b))
		job, _ = self._orphan(self.seller_a)
		frappe.db.set_value("Listing", other, "created_by_bulk_job", job)
		result = repair.restore_orphan_jobs()
		self.assertFalse(frappe.db.exists("Bulk Import Job", job))
		self.assertGreaterEqual(result["atlandi"], 1)

	def test_new_import_after_repair_does_not_reuse_restored_name(self):
		"""Silinen job serinin sonuncusuysa Frappe sayacı geri alır; onarım sayacı ileri itmeli."""
		job, _ = self._orphan(self.seller_a)
		repair.restore_orphan_jobs()
		fresh = self._job(self.seller_a, days_old=0)
		self.assertNotEqual(fresh, job)

	def test_repaired_job_visible_only_to_its_seller(self):
		job, _ = self._orphan(self.seller_a)
		repair.restore_orphan_jobs()
		doc = frappe.get_doc("Bulk Import Job", job)
		self.assertTrue(frappe.has_permission("Bulk Import Job", "read", doc=doc, user=SELLERS[0][0]))
		self.assertFalse(frappe.has_permission("Bulk Import Job", "read", doc=doc, user=SELLERS[1][0]))

	def test_upsert_works_after_repair(self):
		"""Kabul senaryosu 3: eski ilanlar Excel ile toplu güncellenebilmeli."""
		job, (listing, _) = self._orphan(self.seller_a)
		repair.restore_orphan_jobs()
		sku = frappe.db.get_value("Listing", listing, "seller_sku")
		new_job = self._job(self.seller_a, days_old=0)
		name, changed = persister.update_listing(sku, {"title": "M981 Güncel"}, self.seller_a, new_job)
		self.assertEqual(name, listing)
		self.assertIn("title", changed)

	# ── düğme koruması ───────────────────────────────────────────

	def test_purged_job_buttons_explain_instead_of_failing(self):
		job, _ = self._orphan(self.seller_a)
		repair.restore_orphan_jobs()
		for endpoint in (bulk_api.download_error_excel, bulk_api.retry_failed_rows):
			with self.assertRaisesRegex(frappe.ValidationError, "saklama süresi|retention period"):
				endpoint(job)

	# ── bekçi ────────────────────────────────────────────────────

	def test_orphan_watch_reports_then_clears(self):
		job, _ = self._orphan(self.seller_a)
		target = ("Listing", "created_by_bulk_job", "Bulk Import Job")
		before = {(f["doctype"], f["alan"], f["hedef"]) for f in orphan_links.find_orphan_links()}
		self.assertIn(target, before)
		repair.restore_orphan_jobs()
		after = {(f["doctype"], f["alan"], f["hedef"]) for f in orphan_links.find_orphan_links()}
		self.assertNotIn(target, after)

	def test_orphan_watch_writes_baseline_once_then_only_increases(self):
		frappe.db.delete("DefaultValue", {"parent": "__default", "defkey": orphan_links.BASELINE_KEY})
		orphan_links.report_orphan_links()
		self.assertEqual(orphan_links.report_orphan_links(), [], "değişiklik yokken yine yazdı")
		self._orphan(self.seller_a)
		increased = orphan_links.report_orphan_links()
		self.assertEqual([(f["doctype"], f["alan"]) for f in increased], [("Listing", "created_by_bulk_job")])
		self.assertEqual(increased[0]["satir"] - increased[0]["onceki"], 2)
		self.assertEqual(orphan_links.report_orphan_links(), [], "artış bir kez raporlanmalı")

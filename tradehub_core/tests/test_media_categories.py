"""MOGEM-579 — medya kategorizasyonu model ve API sözleşmesi.

Kapsam: tenant kategori kataloğu, çoktan-çoğa manuel atama, atama kaynağı,
açıklanabilir otomatik öneri, SQL öncesi kategori arama/filtreleme ve çapraz
tenant izolasyonu.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import seller_media as api
from tradehub_core.media import categories
from tradehub_core.tradehub_core.doctype.media_category import media_category as category_doctype
from tradehub_core.utils.tenant import clear_seller_cache_for_user


class MediaCategoryTests(FrappeTestCase):
	def _drop(self, doctype: str, name: str) -> None:
		previous = frappe.session.user
		frappe.set_user("Administrator")
		try:
			if doctype == "Media Category":
				for assignment in frappe.get_all(
					"Media Category Assignment", filters={"category": name}, pluck="name"
				):
					frappe.delete_doc(
						"Media Category Assignment", assignment, ignore_permissions=True, force=True
					)
			if frappe.db.exists(doctype, name):
				frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			frappe.db.commit()
		finally:
			frappe.set_user(previous)

	def _user(self, tag: str) -> str:
		email = f"mogem579-{tag}-{self.suffix}@test.local"
		doc = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": tag,
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("User", doc.name))
		self.addCleanup(lambda: clear_seller_cache_for_user(doc.name))
		return doc.name

	def _seller(self, tag: str, user: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_code": f"M579{tag}{self.suffix}",
				"seller_name": f"MOGEM 579 {tag} {self.suffix}",
				"user": user,
				"email": user,
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Admin Seller Profile", doc.name))
		return doc.name

	def _file(self, tag: str, user: str) -> str:
		previous = frappe.session.user
		frappe.set_user(user)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"mogem579-{tag}-{self.suffix}.txt",
					"is_private": 0,
					"content": f"MOGEM 579 {tag} {self.suffix}".encode(),
				}
			).insert(ignore_permissions=True)
			frappe.db.commit()
		finally:
			frappe.set_user(previous)
		self.addCleanup(lambda: self._drop("File", doc.name))
		return doc.file_url

	def _category(self, name: str, category_type: str = "custom", user: str | None = None) -> str:
		if user:
			frappe.set_user(user)
		row = api.create_media_category(category_name=name, category_type=category_type)["category"]
		self.addCleanup(lambda: self._drop("Media Category", row["name"]))
		return row["name"]

	def setUp(self):
		super().setUp()
		self.previous_user = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self.previous_user))
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)
		self.owner_a = self._user("a")
		self.store_a = self._seller("A", self.owner_a)
		self.owner_b = self._user("b")
		self.store_b = self._seller("B", self.owner_b)
		self.file_a = self._file("kampanya", self.owner_a)
		self.file_a2 = self._file("diger", self.owner_a)
		frappe.set_user(self.owner_a)

	def test_catalog_crud_and_assignment_counts(self):
		first = self._category(f"Kampanya {self.suffix}", "campaign")
		second = self._category(f"Ürün {self.suffix}", "product")

		result = api.set_media_categories(self.file_a, [first, second])
		self.assertEqual({row["name"] for row in result["categories"]}, {first, second})
		self.assertTrue(
			all(row["assignment_source"] == "manual" for row in result["categories"])
		)
		self.assertTrue(all(row["confidence"] == 1 for row in result["categories"]))

		catalog = {row["name"]: row for row in api.list_media_categories()["categories"]}
		self.assertEqual(catalog[first]["assignment_count"], 1)
		self.assertEqual(catalog[second]["assignment_count"], 1)

		updated = api.update_media_category(
			first, {"category_name": f"Yaz Kampanyası {self.suffix}", "color": "#336699"}
		)["category"]
		self.assertEqual(updated["category_name"], f"Yaz Kampanyası {self.suffix}")
		self.assertEqual(updated["color"], "#336699")

		with self.assertRaises(frappe.ValidationError):
			api.delete_media_category(first)
		api.set_media_categories(self.file_a, [])
		api.delete_media_category(first)
		self.assertFalse(frappe.db.exists("Media Category", first))

	def test_multi_category_filter_and_category_name_search_run_before_paging(self):
		common = self._category(f"Ortak {self.suffix}")
		specific = self._category(f"Nadir {self.suffix}")
		api.set_media_categories(self.file_a, [common, specific])
		api.set_media_categories(self.file_a2, [common])

		filtered = api.get_my_media(page=1, page_size=1, categories=[common, specific])
		self.assertEqual(filtered["total"], 1)
		self.assertEqual(filtered["items"][0]["file_url"], self.file_a)
		self.assertEqual(
			{row["name"] for row in filtered["items"][0]["categories"]},
			{common, specific},
		)

		searched = api.get_my_media(page=1, page_size=1, search=f"Nadir {self.suffix}")
		self.assertEqual(searched["total"], 1)
		self.assertEqual(searched["items"][0]["file_url"], self.file_a)

	def test_suggestions_use_filename_metadata_source_and_content_type(self):
		campaign = self._category("kampanya", "campaign")
		metadata_category = self._category("teknik", "custom")
		source_category = self._category("dropbox", "workflow")
		content_category = self._category("belge", "content_type")
		api.update_media(self.file_a, {"title": "Teknik çizim"})

		result = api.suggest_media_categories(self.file_a, source="Dropbox import")
		by_name = {row["name"]: row for row in result["suggestions"]}
		self.assertIn(campaign, by_name)
		self.assertIn(metadata_category, by_name)
		self.assertIn(source_category, by_name)
		self.assertIn(content_category, by_name)
		self.assertIn("file_name", by_name[campaign]["evidence"])
		self.assertIn("title", by_name[metadata_category]["evidence"])
		self.assertIn("source", by_name[source_category]["evidence"])
		self.assertIn("content_type", by_name[content_category]["evidence"])

		applied = api.apply_media_category_suggestions(
			self.file_a, source="Dropbox import", threshold=0.8
		)
		self.assertGreaterEqual(applied["applied"], 3)
		self.assertTrue(
			all(
				row["assignment_source"] == "suggestion"
				for row in applied["categories"]
				if row["name"] in {campaign, metadata_category, source_category, content_category}
			)
		)

		# Kullanıcının açık seçimi aynı bağı manuel karara yükseltir ve sonraki
		# otomatik koşu bunu geriye çeviremez.
		manual = api.set_media_categories(self.file_a, [campaign])
		self.assertEqual(manual["categories"][0]["assignment_source"], "manual")
		api.apply_media_category_suggestions(self.file_a, source="Dropbox import", threshold=0.8)
		after = categories.assignments_for_urls([self.file_a], self.store_a)[self.file_a]
		campaign_row = next(row for row in after if row["name"] == campaign)
		self.assertEqual(campaign_row["assignment_source"], "manual")

	def test_cross_tenant_catalog_and_assignments_are_isolated(self):
		secret = self._category(f"A Gizli {self.suffix}")
		api.set_media_categories(self.file_a, [secret])
		doc = frappe.get_doc("Media Category", secret)

		frappe.set_user(self.owner_b)
		self.assertNotIn(
			secret, {row["name"] for row in api.list_media_categories()["categories"]}
		)
		with self.assertRaises(frappe.DoesNotExistError):
			api.update_media_category(secret, {"category_name": "ele geçirildi"})
		with self.assertRaises(frappe.DoesNotExistError):
			api.delete_media_category(secret)
		with self.assertRaises((frappe.PermissionError, frappe.DoesNotExistError)):
			api.set_media_categories(self.file_a, [secret])

		# Aynı görünen ad başka tenant için bağımsız bir katalog satırıdır.
		other = self._category(f"A Gizli {self.suffix}", user=self.owner_b)
		self.assertNotEqual(secret, other)
		self.assertFalse(category_doctype.has_permission(doc, user=self.owner_b))
		condition = category_doctype.get_permission_query_conditions(self.owner_b)
		self.assertIn("`tabMedia Category`.`store`", condition)
		names = {
			row[0]
			for row in frappe.db.sql(f"select name from `tabMedia Category` where {condition}")
		}
		self.assertNotIn(secret, names)
		self.assertIn(other, names)

	def test_inactive_category_is_listable_for_management_but_not_new_assignment(self):
		category = self._category(f"Pasif {self.suffix}")
		api.update_media_category(category, {"is_active": 0})
		self.assertNotIn(
			category, {row["name"] for row in api.list_media_categories()["categories"]}
		)
		self.assertIn(
			category,
			{
				row["name"]
				for row in api.list_media_categories(include_inactive=1)["categories"]
			},
		)
		with self.assertRaises(frappe.DoesNotExistError):
			api.set_media_categories(self.file_a, [category])

	def test_database_unique_constraints_and_url_digest_are_present(self):
		category = self._category(f"DB {self.suffix}")
		api.set_media_categories(self.file_a, [category])
		assignment = frappe.db.get_value(
			"Media Category Assignment",
			{"store": self.store_a, "file_url": self.file_a, "category": category},
			["name", "file_url_hash"],
			as_dict=True,
		)
		self.assertEqual(len(assignment.file_url_hash), 64)
		category_indexes = {
			row[2] for row in frappe.db.sql("SHOW INDEX FROM `tabMedia Category`")
		}
		assignment_indexes = {
			row[2] for row in frappe.db.sql("SHOW INDEX FROM `tabMedia Category Assignment`")
		}
		self.assertIn("uniq_media_category_scope", category_indexes)
		self.assertIn("uniq_media_category_assignment", assignment_indexes)

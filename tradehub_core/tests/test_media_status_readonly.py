"""Isolated status contract tests. No Frappe site, DB write or scan worker.

Run: python3 -m unittest tradehub_core.tests.test_media_status_readonly
"""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class MediaStatusTest(unittest.TestCase):
	def setUp(self):
		self.calls = []
		self.rows = [{"name": "own-file", "file_url": "/files/own.png", "file_size": 100, "th_media_scan_status": "pending"}]
		self.assets = [{"source_file": "own-file", "state": "ready"}]
		self.twins = None
		self.frappe = types.SimpleNamespace(
			session=types.SimpleNamespace(user="seller"),
			whitelist=lambda: lambda fn: fn,
			_=lambda msg: msg,
			PermissionError=PermissionError,
			throw=lambda msg, exc=ValueError: (_ for _ in ()).throw(exc(msg)),
			get_list=self.get_list,
		)
		spec = importlib.util.spec_from_file_location("media_status_unit", Path(__file__).parents[1] / "api/media_status.py")
		self.module = importlib.util.module_from_spec(spec)
		with patch.dict(sys.modules, {"frappe": self.frappe}):
			spec.loader.exec_module(self.module)

	def get_list(self, doctype, **kwargs):
		self.calls.append((doctype, kwargs))
		self.assertNotIn("ignore_permissions", kwargs)
		if doctype == "File" and "filters" in kwargs:
			urls = kwargs["filters"]["file_url"][1]
			pool = self.rows if self.twins is None else self.twins
			return [{"name": r["name"], "file_url": r["file_url"]} for r in pool if r["file_url"] in urls]
		if doctype == "Media Asset":
			wanted = set(kwargs["filters"]["source_file"][1])
			return [a for a in self.assets if a["source_file"] in wanted]
		return self.rows

	def test_missing_and_other_seller_are_indistinguishable(self):
		result = self.module.get_status(["own-file", "foreign-file", "absent-file"])["files"]
		self.assertEqual(result["foreign-file"], result["absent-file"])
		self.assertEqual(result["own-file"]["scan_status"], "pending")
		self.assertEqual(result["own-file"]["asset_states"], ["ready"])
		self.assertEqual(self.calls[2][1]["filters"]["source_file"], ["in", ["own-file"]])

	def test_reupload_of_same_content_sees_first_rows_asset(self):
		# Aynı içerik yeniden yüklendi: yeni File satırının Media Asset'i yok,
		# varlık ilk satıra bağlı. Kullanıcının okuyabildiği ikiz sayılır.
		self.rows = [{"name": "new-row", "file_url": "/files/own.png", "th_media_scan_status": "clean"}]
		self.twins = [
			{"name": "new-row", "file_url": "/files/own.png"},
			{"name": "own-file", "file_url": "/files/own.png"},
		]
		res = self.module.get_status(["new-row"])["files"]["new-row"]
		self.assertEqual(res["asset_states"], ["ready"])

	def test_unreadable_twin_is_not_used(self):
		# Başka satıcının ikizi get_list'te görünmez → varlığı da sayılmaz.
		self.rows = [{"name": "new-row", "file_url": "/files/own.png", "th_media_scan_status": "clean"}]
		self.twins = [{"name": "new-row", "file_url": "/files/own.png"}]
		res = self.module.get_status(["new-row"])["files"]["new-row"]
		self.assertEqual(res["asset_states"], [])

	def test_duplicate_url_uses_worst_scan_result(self):
		self.rows.append({"name": "duplicate", "file_url": "/files/own.png", "th_media_scan_status": "infected"})
		self.assertEqual(self.module.get_status(["/files/own.png"])["files"]["/files/own.png"]["scan_status"], "infected")

	def test_guest_and_invalid_batches_never_query(self):
		for invalid in (["x"] * 51, [None], "not-json", "{}"):
			with self.assertRaises(ValueError):
				self.module.get_status(invalid)
		self.frappe.session.user = "Guest"
		with self.assertRaises(PermissionError):
			self.module.get_status(["own-file"])
		self.assertEqual(self.calls, [])

	def test_no_visible_files_means_no_asset_query(self):
		self.rows = []
		self.assertEqual(self.module.get_status(["hidden"]), {"files": {"hidden": None}})
		self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
	unittest.main()

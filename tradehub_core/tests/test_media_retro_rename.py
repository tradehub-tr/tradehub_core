"""Medya retro-rename (MOGEM-582 alt görevi) — eski tahmin edilebilir adların
içerik-adresli ada taşınması, 301 köprüsü ve geri alma.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_retro_rename
"""

from __future__ import annotations

import os  # noqa: F401

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, get_files_path, now_datetime  # noqa: F401


class TestMediaUrlRedirectDoctype(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(lambda: frappe.db.delete("Media URL Redirect", {"job_key": "TEST-DT"}))

	def test_source_url_tekil(self):
		frappe.get_doc(
			{
				"doctype": "Media URL Redirect",
				"source_url": "/files/test-dt-eski.jpg",
				"target_url": "/files/ab/abcdef.jpg",
				"job_key": "TEST-DT",
				"expires_at": add_days(now_datetime(), 90),
			}
		).insert(ignore_permissions=True)
		with self.assertRaises(frappe.UniqueValidationError):
			frappe.get_doc(
				{
					"doctype": "Media URL Redirect",
					"source_url": "/files/test-dt-eski.jpg",
					"target_url": "/files/ab/ffffff.jpg",
					"job_key": "TEST-DT",
					"expires_at": add_days(now_datetime(), 90),
				}
			).insert(ignore_permissions=True)

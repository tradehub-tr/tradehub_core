"""MOGEM-981 — açıklaması hiç girilmemiş ilan, açıklamaya dokunulmadan kaydedilebilmeli.

Panel boş açıklamayı "" gönderiyor, DB'de NULL duruyor; `has_value_changed` bunu değişiklik
sayınca SEO açıklama kuralı (min 150 karakter) fiyat/stok düzenlemesini bile 417 ile reddediyordu.
Kural test bağlamında kendini kapattığı için `frappe.flags.in_test` burada bilerek indirilir.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

try:
	from frappe.tests.utils import FrappeTestCase

	HAS_FRAPPE = True
except ImportError:
	HAS_FRAPPE = False

if HAS_FRAPPE:
	import frappe

_TITLE = "Piknik Seti 4 Parça Plastik Servis ve Saklama Kabı Açık Hava İçin"


@unittest.skipUnless(HAS_FRAPPE, "Frappe context required")
class TestSeoBosAciklama(FrappeTestCase):
	def _saved_listing(self, before: str | None, now: str | None):
		"""Kayıtlı bir ilanın düzenlenmesini taklit eder: DB hâli `before`, formdan gelen `now`."""
		old = frappe.get_doc({"doctype": "Listing", "title": _TITLE, "description": before})
		doc = frappe.get_doc({"doctype": "Listing", "title": _TITLE, "description": now})
		for d in (old, doc):
			d.name = "LST-M981-SEO"
			d.set("__islocal", 0)
		doc._doc_before_save = old
		return doc

	def _validate(self, doc) -> None:
		with patch.dict(frappe.flags, {"in_test": False}):
			doc._validate_seo_content()

	def test_null_description_sent_as_empty_string_is_not_a_change(self):
		self._validate(self._saved_listing(None, ""))

	def test_empty_string_sent_as_null_is_not_a_change(self):
		self._validate(self._saved_listing("", None))

	def test_rule_still_applies_when_description_really_written(self):
		with self.assertRaises(frappe.ValidationError):
			self._validate(self._saved_listing(None, "kısa açıklama"))

	def test_rule_still_applies_to_new_listing(self):
		doc = frappe.get_doc({"doctype": "Listing", "title": _TITLE, "description": ""})
		with self.assertRaises(frappe.ValidationError):
			self._validate(doc)

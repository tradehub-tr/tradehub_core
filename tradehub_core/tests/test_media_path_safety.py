"""`media/path_safety.py` — check_path_safety uyumluluk katmanı testleri.

İki şeyi doğrular:

  1. **Fallback davranışı** — Frappe'de `check_path_safety` olmayan (eski v15)
     ortamlarda devreye giren yerel kopya, upstream ile birebir aynı kararı
     veriyor mu: kök içindeki yol kabul, path traversal red + log.
  2. **Import zinciri** — `access_level` ve `media_access` artık frappe'den
     değil buradan import ediyor; eski Frappe'de media_admin'in tamamını
     çökerten ImportError (2026-08-20 alpha 417 arızası) tekrarlanamaz.

Fallback, Frappe'de fonksiyonun VAR olduğu ortamda da test edilebilmeli —
bu yüzden modül `importlib` ile, frappe utils'teki isim geçici silinmişken
yeniden yüklenir.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_path_safety
"""

from __future__ import annotations

import importlib
import os
import tempfile
from unittest import mock

import frappe.core.doctype.file.utils as frappe_file_utils
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import path_safety


def _reload_without_frappe_impl():
	"""Modülü, Frappe'de `check_path_safety` yokmuş gibi yeniden yükle."""
	if not hasattr(frappe_file_utils, "check_path_safety"):
		# Zaten eski Frappe — fallback doğal yoldan devrede.
		return importlib.reload(path_safety)
	with mock.patch.object(frappe_file_utils, "check_path_safety", None):
		del frappe_file_utils.check_path_safety
		return importlib.reload(path_safety)
		# mock.patch çıkışta orijinal fonksiyonu geri koyar


class TestPathSafetyCompat(FrappeTestCase):
	def setUp(self):
		# Önceki test fallback'li reload bırakmış olabilir — temiz başla.
		importlib.reload(path_safety)
		super().setUp()

	@classmethod
	def tearDownClass(cls):
		# Diğer testler modülü normal hâliyle görsün.
		importlib.reload(path_safety)
		super().tearDownClass()

	def test_uses_frappe_impl_when_available(self):
		"""Upstream varsa KARAR ondan gelmeli.

		Eskiden kimlik karşılaştırılıyordu (`assertIs`). Artık modül
		upstream'i bir sarmalayıcının içinden çağırıyor (F-08: `commonpath`
		mutlak ile göreceyi karşılaştıramayıp `ValueError` atıyor ve ne
		upstream ne yerel kopya bunu yakalıyordu; sarmalayıcı fail-closed
		davranıyor). Sözleşme "aynı nesne" değil, "kararı upstream veriyor".
		"""
		if not hasattr(frappe_file_utils, "check_path_safety"):
			self.skipTest("upstream check_path_safety yok")
		self.assertIs(path_safety._upstream_check, frappe_file_utils.check_path_safety)
		with mock.patch.object(path_safety, "_upstream_check", return_value=False) as sahte:
			self.assertFalse(path_safety.check_path_safety(base_path="/a", requested_path="/a/b"))
		sahte.assert_called_once()

	def test_karsilastirilamayan_yol_ISTISNA_ATMAZ(self):
		"""F-08 — `commonpath` mutlak ile göreceyi kabul etmez, `ValueError` atar.

		Kullanıcı girdisiyle beslenen bir kapıda yükselen istisna "güvenli
		değil" cevabı yerine 500 üretiyordu. Cevap artık fail-closed: False.
		"""
		with mock.patch("frappe.log_error") as log_error:
			self.assertFalse(path_safety.check_path_safety(base_path="/mutlak", requested_path="goreceli"))
		log_error.assert_called()

	def test_fallback_accepts_path_inside_base(self):
		mod = _reload_without_frappe_impl()
		with tempfile.TemporaryDirectory() as base:
			inside = os.path.join(base, "ab", "hash.webp")
			self.assertTrue(mod.check_path_safety(base_path=base, requested_path=inside))

	def test_fallback_rejects_traversal_and_logs(self):
		mod = _reload_without_frappe_impl()
		with tempfile.TemporaryDirectory() as base:
			outside = os.path.join(base, "..", "etc", "passwd")
			with mock.patch("frappe.log_error") as log_error:
				self.assertFalse(mod.check_path_safety(base_path=base, requested_path=outside))
			log_error.assert_called_once()

	def test_importers_survive_old_frappe(self):
		"""access_level + media_access, Frappe'de fonksiyon yokken de import edilebilmeli."""
		_reload_without_frappe_impl()
		from tradehub_core.api import media_access
		from tradehub_core.media import access_level

		for module in (access_level, media_access):
			src = open(module.__file__).read()
			self.assertNotIn("from frappe.core.doctype.file.utils import check_path_safety", src)

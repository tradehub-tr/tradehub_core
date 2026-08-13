"""İçerik-hash'li dosya adlandırma testleri (TUR-141/130).

Yeni yüklenen dosyaların adı URL'den tahmin edilemesin diye
<sha256(içerik)[:32]>.<ext> ile adlandırılır (enumeration önleme).
Mevcut file_url'ler etkilenmez — yalnız yeni yüklemelere uygulanır.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_naming
"""

import os

from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import naming


class TestHashedName(FrappeTestCase):
	def test_ayni_icerik_ayni_hash_farkli_ad_gizli(self):
		data = b"\x89PNG test icerik"
		ad1 = naming._hashed_name("urun.png", data)
		self.assertTrue(ad1.endswith(".png"))
		self.assertNotIn("urun", ad1)  # orijinal ad sızmıyor
		self.assertEqual(len(ad1.split(".")[0]), 32)  # sha256[:32]
		self.assertEqual(ad1, naming._hashed_name("baska.png", data))  # içerik-adresli

	def test_farkli_icerik_farkli_hash(self):
		ad1 = naming._hashed_name("a.jpg", b"birinci icerik")
		ad2 = naming._hashed_name("a.jpg", b"ikinci icerik")
		self.assertNotEqual(ad1, ad2)

	def test_uzanti_kucuk_harfe_cevrilir(self):
		ad = naming._hashed_name("FOTO.JPG", b"veri")
		self.assertTrue(ad.endswith(".jpg"))


class TestWriteFileHashed(FrappeTestCase):
	def test_public_dosya_hash_isimli_yazilir_ve_url_doner(self):
		from frappe.utils import get_files_path

		content = b"public test icerigi"
		result = naming.write_file_hashed(
			"urun-foto.png", content, content_type="image/png", is_private=0
		)

		expected_name = naming._hashed_name("urun-foto.png", content)
		self.assertEqual(result["file_name"], expected_name)
		self.assertEqual(result["file_url"], f"/files/{expected_name}")

		disk_path = os.path.join(get_files_path(is_private=0), expected_name)
		self.addCleanup(lambda: os.path.exists(disk_path) and os.remove(disk_path))
		self.assertTrue(os.path.exists(disk_path))
		with open(disk_path, "rb") as f:
			self.assertEqual(f.read(), content)

	def test_private_dosya_private_prefix_ile_doner(self):
		from frappe.utils import get_files_path

		content = b"private test icerigi"
		result = naming.write_file_hashed(
			"gizli.pdf", content, content_type="application/pdf", is_private=1
		)

		expected_name = naming._hashed_name("gizli.pdf", content)
		self.assertEqual(result["file_name"], expected_name)
		self.assertEqual(result["file_url"], f"/private/files/{expected_name}")

		disk_path = os.path.join(get_files_path(is_private=1), expected_name)
		self.addCleanup(lambda: os.path.exists(disk_path) and os.remove(disk_path))
		self.assertTrue(os.path.exists(disk_path))

	def test_ayni_icerik_iki_kez_yazilinca_ayni_dosya_adini_uretir(self):
		"""İçerik-adresli isimlendirme idempotent olmalı — ikinci yazım üzerine yazar, çakışmaz."""
		content = b"tekrarlanan icerik"
		r1 = naming.write_file_hashed("once.png", content, content_type="image/png", is_private=0)
		r2 = naming.write_file_hashed("sonra.png", content, content_type="image/png", is_private=0)

		self.assertEqual(r1["file_name"], r2["file_name"])

		from frappe.utils import get_files_path

		disk_path = os.path.join(get_files_path(is_private=0), r1["file_name"])
		self.addCleanup(lambda: os.path.exists(disk_path) and os.remove(disk_path))

"""TUR-126 — private medya için imzalı süreli URL testleri.

`tradehub_core/api/media_access.py` iki güvenlik-kritik uçnokta sunar:

  - `get_signed_url` — çağıranın dosyaya READ yetkisi olduğunu doğrular,
    ardından `frappe.utils.verified_command.get_signed_params` ile
    `file=<url>&exp=<ts>` imzalar. Yetkisiz kullanıcı için imza ÜRETİLMEZ.
  - `download` (`allow_guest=True`) — imzayı (`verify_request`) ve süreyi
    (`exp`) doğrular, yalnız `/private/files/` altındaki dosyayı serve eder.

Gerçek DB (`FrappeTestCase`) kullanılır: `File.has_permission` gibi çekirdek
Frappe davranışı stub'lanamayacak kadar iç içe (owner/DocShare/bağlı-doc
delegasyonu). Yalnız HTTP-bağımlı iki parça mock'lanır:

  - `verify_request()` — gerçek bir HTTP isteği (`frappe.request.query_string`)
    gerektirir, test ortamında yok.
  - `frappe.form_dict` — `download()`'ın okuduğu `file`/`exp` parametreleri
    doğrudan set edilir (gerçek query string parse'ı test kapsamı dışı,
    `verified_command.verify_request` zaten Frappe çekirdeğinde test edilmiş).

Dosya oluşturma/silme gerçek commit yapıyor (`File.insert()` → disk yazımı +
`on_file_insert` audit kancası); bu yüzden `test_media_pipeline_integration.py`
ile AYNI desen kullanılıyor: fixture'lar `ignore_permissions=True` ile insert
edilip hemen commit edilir, `addCleanup` ile LIFO silinir.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_access
"""

from __future__ import annotations

import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

import frappe
from frappe.tests.utils import FrappeTestCase
from werkzeug.wrappers import Response

from tradehub_core.api import media_access


def _now() -> int:
	return int(time.time())


class MediaAccessTestBase(FrappeTestCase):
	"""Ortak fixture kurulumu: iki gerçek kullanıcı + iki gerçek File kaydı."""

	def _delete_and_commit(self, doctype: str, name: str) -> None:
		"""`File.insert()`/`User.insert()` gerçek commit yapıyor — teardown
		rollback'i bunu geri alamaz, silme de kendi commit'ini taşımalı
		(bkz. `test_media_pipeline_integration.py` aynı yorum)."""
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			frappe.db.commit()

	def setUp(self):
		super().setUp()
		self._orig_user = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self._orig_user))
		# Her testten önce temiz form_dict — bir test download() parametresi
		# bıraktıysa sonrakini kirletmesin.
		frappe.local.form_dict = frappe._dict()

		suffix = frappe.generate_hash(length=8)
		self.owner_email = f"medya-erisim-owner-{suffix}@test.local"
		self.outsider_email = f"medya-erisim-outsider-{suffix}@test.local"

		frappe.set_user("Administrator")
		self.owner = frappe.get_doc(
			{
				"doctype": "User",
				"email": self.owner_email,
				"first_name": "Owner",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("User", self.owner_email))

		self.outsider = frappe.get_doc(
			{
				"doctype": "User",
				"email": self.outsider_email,
				"first_name": "Outsider",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("User", self.outsider_email))

		# Owner'a ait, kimseyle paylaşılmamış PRIVATE dosya — outsider'ın
		# `has_permission("read")` sınavını GEÇEMEMESİ gereken senaryo.
		frappe.set_user(self.owner_email)
		self.private_file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "gizli-belge.txt",
				"is_private": 1,
				"content": b"gizli icerik",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("File", self.private_file.name))

		self.public_file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "acik-gorsel.txt",
				"is_private": 0,
				"content": b"herkese acik icerik",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("File", self.public_file.name))

		frappe.set_user("Administrator")

	def _signed_params(self, url: str) -> dict:
		query = urlparse(url).query
		return {k: v[0] for k, v in parse_qs(query).items()}


class GetSignedUrlTests(MediaAccessTestBase):
	def test_yetkili_kullanici_icin_imzali_url_doner(self):
		"""Dosya sahibi kendi private dosyası için imzalı link alabilir."""
		frappe.set_user(self.owner_email)

		result = media_access.get_signed_url(self.private_file.file_url)

		self.assertIn("url", result)
		self.assertIn("_signature=", result["url"])
		params = self._signed_params(result["url"])
		self.assertIn("exp", params)
		self.assertEqual(params["file"], self.private_file.file_url)
		# exp gelecekte, varsayılan TTL'e (900s) yakın olmalı.
		self.assertGreater(int(params["exp"]), _now())
		self.assertLessEqual(int(params["exp"]), _now() + 900 + 5)

	def test_yetkisiz_kullanici_permission_error_ve_imza_uretmez(self):
		"""KRİTİK güvenlik testi: outsider bu dosyaya read yetkisine sahip
		değil (owner değil, paylaşım yok, bağlı doküman yok) — imza asla
		üretilmemeli, `frappe.PermissionError` fırlatılmalı."""
		frappe.set_user(self.outsider_email)

		with self.assertRaises(frappe.PermissionError):
			media_access.get_signed_url(self.private_file.file_url)

	def test_public_dosya_icin_reddedilir(self):
		"""`/files/` altındaki public dosya zaten girişsiz açık — imza
		gereksiz, endpoint bunu bilerek reddetmeli."""
		frappe.set_user(self.owner_email)
		self.assertTrue(self.public_file.file_url.startswith("/files/"))

		with self.assertRaises(frappe.ValidationError):
			media_access.get_signed_url(self.public_file.file_url)

	def test_path_traversal_reddedilir(self):
		frappe.set_user(self.owner_email)
		with self.assertRaises(frappe.ValidationError):
			media_access.get_signed_url("/private/files/../../etc/passwd")

	def test_ttl_ust_sinira_clamp_edilir(self):
		"""86400'ü aşan TTL istekleri sessizce 86400'e clamp edilmeli — sınırsız
		süreli link üretilememeli (güvenlik: geniş TTL = uzun süre açık kapı)."""
		frappe.set_user(self.owner_email)

		result = media_access.get_signed_url(self.private_file.file_url, ttl_seconds=999999)

		params = self._signed_params(result["url"])
		exp = int(params["exp"])
		self.assertLessEqual(exp, _now() + media_access.MAX_TTL_SECONDS + 5)
		self.assertGreater(exp, _now() + media_access.MAX_TTL_SECONDS - 5)


class DownloadTests(MediaAccessTestBase):
	def _set_params(self, file_url: str, exp: int) -> None:
		frappe.local.form_dict = frappe._dict(file=file_url, exp=str(exp))

	def test_gecerli_imza_ve_sure_ici_dosya_serve_edilir(self):
		"""`send_private_file` gerçek bir werkzeug HTTP isteği (`frappe.local.
		request`) bekliyor — `bench run-tests`'te yok (`test_media_pipeline_
		integration.py`'nin de karşılaşmadığı bir katman, o dosya asla
		`response.py`'a inmiyor). Path çözümü + çağrı sözleşmesi burada test
		ediliyor; dosyanın X-Accel-Redirect/`send_file` ile gerçek akışı
		Frappe çekirdeğinin kendi test kapsamında zaten doğrulanmış.
		"""
		expected_relative = self.private_file.file_url[len("/private/") :]
		self._set_params(self.private_file.file_url, _now() + 900)
		stub_response = Response(b"gizli icerik", status=200)

		with mock.patch.object(media_access, "verify_request", return_value=True):
			with mock.patch.object(media_access, "send_private_file", return_value=stub_response) as m:
				response = media_access.download()

		m.assert_called_once_with(expected_relative)
		self.assertIs(response, stub_response)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.get_data(), b"gizli icerik")

	def test_gecerli_indirme_audit_kaydi_yazar(self):
		self._set_params(self.private_file.file_url, _now() + 900)

		with mock.patch.object(media_access, "verify_request", return_value=True):
			with mock.patch.object(media_access, "send_private_file", return_value=Response(b"x")):
				with mock.patch.object(media_access.audit, "log_media_event") as m:
					media_access.download()

		m.assert_called_once()
		_, kwargs = m.call_args
		self.assertEqual(kwargs["action"], media_access.audit.ACTION_SIGNED_ACCESS)
		self.assertEqual(kwargs["file_url"], self.private_file.file_url)
		self.assertTrue(kwargs["allowed"])

	def test_gecersiz_imza_reddedilir(self):
		"""KRİTİK güvenlik testi: HMAC doğrulaması başarısızsa dosya asla
		serve edilmemeli — `verify_request` False dönünce reddedilir."""
		self._set_params(self.private_file.file_url, _now() + 900)

		with mock.patch.object(media_access, "verify_request", return_value=False):
			with self.assertRaises(frappe.PermissionError):
				media_access.download()

	def test_suresi_dolmus_link_reddedilir(self):
		"""KRİTİK güvenlik testi: imza geçerli olsa bile `exp` geçmişse
		reddedilmeli — `exp` imzanın kapsamında olduğu için değiştirilemez,
		ama süresi geçmiş bir imza hâlâ doğrulanabilir kalır."""
		self._set_params(self.private_file.file_url, _now() - 10)

		with mock.patch.object(media_access, "verify_request", return_value=True):
			with self.assertRaises(frappe.PermissionError):
				media_access.download()

	def test_public_dosya_yolu_download_da_da_reddedilir(self):
		"""Savunma amaçlı ikinci kontrol: imza `/files/`'i kapsasa bile
		`download()` yalnız `/private/files/` servis eder."""
		self._set_params(self.public_file.file_url, _now() + 900)

		with mock.patch.object(media_access, "verify_request", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				media_access.download()

	def test_path_traversal_download_da_reddedilir(self):
		self._set_params("/private/files/../../../etc/passwd", _now() + 900)

		with mock.patch.object(media_access, "verify_request", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				media_access.download()

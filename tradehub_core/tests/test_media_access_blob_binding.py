"""T-052 — imzalı URL'in blob'a bağlanması (`media_access` × `file_isolation`).

NEDEN AYRI DOSYA
----------------
`test_media_access.py` imza + süre + path sözleşmesini kapsıyor ve tek
kullanıcılı, tek satırlı fixture'la çalışıyor. Buradaki senaryonun kurulumu
farklı: **aynı `file_url`'de iki `File` satırı, farklı `content_hash`** —
yani satır↔blob bağının koptuğu durum. O kurulumu mevcut base sınıfa eklemek
17 testin hepsini gereksiz yere yavaşlatırdı.

ÖLÇÜLEN AÇIK (2026-08-19, `istoc.localhost`)
--------------------------------------------
`download()` guest'e açık ve **hiçbir `File` satırı yüklemiyor**: imzayı
doğrulayıp `send_private_file` çağırıyor. Bu yüzden `media/file_isolation.py`
içindeki V2 daraltması (`blob_matches_row`, yalnız
`TenantIsolatedFile.is_downloadable()` içinde çağrılıyor) bu yolda HİÇ
çalışmıyordu. İmzalama tarafındaki `File.has_permission("read")` de
`file_has_permission` kancasından geçiyor ama `blob_matches_row`'u çağırmıyor.

Sonuç: oturumla indirmesi reddedilen bir satırın sahibi, aynı URL için imzalı
link alıp diskteki (BAŞKA kiracıya ait) blob'u indirebiliyordu. Sitede o gün
2 ayrı `content_hash` taşıyan **5 özel URL** vardı, arkalarında 4–18 satır.

KAPATMA İKİ YERDE
-----------------
  1. `get_signed_url` → `blob_matches_row` ile imza ÜRETMEYİ reddeder.
  2. `download` → `_blob_binding_ok` ile imzanın kapsadığı `blob`'u diskteki
     içerikle karşılaştırır (yalnız belirsiz URL'de; masraf orada).

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \\
        run-tests --module tradehub_core.tests.test_media_access_blob_binding
"""

from __future__ import annotations

import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

import frappe
from frappe.tests.utils import FrappeTestCase
from werkzeug.wrappers import Response

from tradehub_core.api import media_access
from tradehub_core.media import file_isolation

# Tarama kancası bu modülde nötrleniyor: `hold_until_clean` açıkken dosya
# insert anında public ağaçtan çıkarılıyor ve diskten okuyan testler
# `FileNotFoundError` alıyor. Gerekçe `tests/av_notr.py` başlığında.
from tradehub_core.tests.av_notr import setUpModule, tearDownModule  # noqa: F401


def _now() -> int:
	return int(time.time())


class BlobBindingTestBase(FrappeTestCase):
	"""Sahibi A olan gerçek bir private dosya + iki kullanıcı."""

	def _drop(self, doctype: str, name: str) -> None:
		"""`File.insert()` gerçek commit yapıyor — silme de kendi commit'ini
		taşımalı (bkz. `test_file_multirow_isolation.py` aynı yorum)."""
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			frappe.db.commit()

	def _user(self, tag: str) -> str:
		email = f"t052-{tag}-{self.suffix}@test.local"
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
		return doc.name

	def setUp(self):
		super().setUp()
		self._orig_user = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self._orig_user))
		frappe.local.form_dict = frappe._dict()
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)

		self.a_user = self._user("a")
		self.b_user = self._user("b")

		# Diskteki gerçek içerik. Her koşuda benzersiz → içerik-adresli ad da
		# benzersiz, önceki koşumdan kalan blob/cache karışmaz.
		frappe.set_user(self.a_user)
		self.file_a = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"t052-gizli-{self.suffix}.txt",
				"is_private": 1,
				"content": f"A kiracisinin belgesi {self.suffix}".encode(),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("File", self.file_a.name))
		frappe.set_user("Administrator")

		self.file_url = self.file_a.file_url
		self.disk_hash = self.file_a.content_hash
		self.addCleanup(lambda: self._clear_ambiguity_cache())

	def _clear_ambiguity_cache(self) -> None:
		"""`_url_is_ambiguous` 5 dk cache'liyor; testler arası sızmasın."""
		frappe.cache().delete_value(f"tradehub:file_url_ambiguous:{self.file_url}")

	def _params(self, **extra) -> None:
		frappe.local.form_dict = frappe._dict(file=self.file_url, exp=str(_now() + 900), **extra)


class TekSatirliUrlTests(BlobBindingTestBase):
	"""Belirsiz OLMAYAN URL — vakaların ~%99'u. Davranış değişmemeli."""

	def test_imzali_url_blob_parametresini_tasir(self):
		"""İmza artık `blob`'u da kapsıyor: `download()` satırı yüklemeden
		hangi içeriğe yetki verildiğini bilebilsin."""
		frappe.set_user(self.a_user)
		result = media_access.get_signed_url(self.file_url)

		params = {k: v[0] for k, v in parse_qs(urlparse(result["url"]).query).items()}
		self.assertEqual(params["blob"], self.disk_hash)
		self.assertIn("_signature", params)
		self.assertEqual(params["file"], self.file_url)

	def test_blob_parametresi_olmadan_da_indirilir(self):
		"""Geriye dönük uyum: bu değişiklikten önce üretilmiş linkte `blob`
		yok. URL belirsiz DEĞİLSE hangi bloba yetki verildiği zaten tek —
		reddetmek meşru erişimi kırardı."""
		self._params()
		with mock.patch.object(media_access, "verify_request", return_value=True):
			with mock.patch.object(media_access, "send_private_file", return_value=Response(b"ok")):
				response = media_access.download()
		self.assertEqual(response.status_code, 200)

	def test_belirsiz_olmayan_url_de_md5_hesaplanmaz(self):
		"""Masraf kontrolü: `_blob_hash` diskten okuyup md5 hesaplıyor.
		Belirsiz olmayan URL'de bu HİÇ çağrılmamalı, yoksa her imzalı
		indirme dosya boyutuyla orantılı CPU yakar."""
		self._params(blob=self.disk_hash)
		with mock.patch.object(media_access, "verify_request", return_value=True):
			with mock.patch.object(media_access, "send_private_file", return_value=Response(b"ok")):
				with mock.patch.object(file_isolation, "_blob_hash") as m:
					media_access.download()
		m.assert_not_called()


class BelirsizUrlTests(BlobBindingTestBase):
	"""Aynı `file_url`, iki satır, iki farklı `content_hash`."""

	def setUp(self):
		super().setUp()
		# B kendi satırını A'nın URL'ine kuruyor. `File.before_insert` blob'u
		# okuyup `content_hash`'i yeniden hesapladığı için ayrışma insert'te
		# kurulamıyor; canlıda da ayrışma SONRADAN oluşuyor (blob üzerine
		# yazılıyor, satırlar eski hash'le kalıyor). Aynı son durumu doğrudan
		# yazıyoruz — `update_modified=False`, bu bir kullanıcı düzenlemesi
		# değil, veri bozulmasının simülasyonu.
		frappe.set_user(self.b_user)
		self.file_b = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"t052-gizli-{self.suffix}.txt",
				"is_private": 1,
				"file_url": self.file_url,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("File", self.file_b.name))

		frappe.db.set_value("File", self.file_b.name, "content_hash", "0" * 32, update_modified=False)
		frappe.db.commit()
		self.file_b.reload()
		self._clear_ambiguity_cache()
		frappe.set_user("Administrator")

	def test_kurulum_gercekten_belirsiz(self):
		"""Fixture doğrulaması — bu olmadan aşağıdaki testler sessizce
		'belirsiz olmayan' dala düşüp hiçbir şey ölçmez."""
		self.assertTrue(file_isolation._url_is_ambiguous(self.file_url))
		self.assertEqual(file_isolation._blob_hash(self.file_url), self.disk_hash)

	def test_eslesmeyen_satirin_sahibi_imza_alamaz(self):
		"""KRİTİK: B'nin satırı diskteki blob'u temsil etmiyor. Hangi satır
		çözülürse çözülsün B reddedilir — kendi satırı gelirse blob eşleşmez,
		A'nın satırı gelirse yetki yok."""
		frappe.set_user(self.b_user)
		with self.assertRaises(frappe.PermissionError):
			media_access.get_signed_url(self.file_url)

	def test_imza_reddi_audit_a_yazar(self):
		frappe.set_user(self.b_user)
		with mock.patch.object(media_access.audit, "log_media_event") as m:
			with self.assertRaises(frappe.PermissionError):
				media_access.get_signed_url(self.file_url)

		m.assert_called_once()
		_, kwargs = m.call_args
		self.assertEqual(kwargs["action"], media_access.audit.ACTION_ACCESS_DENIED)
		self.assertFalse(kwargs["allowed"])
		self.assertIn(kwargs["reason"], ("blob_mismatch", "signed_url_denied"))

	def test_blob_parametresiz_indirme_reddedilir(self):
		"""Bu değişiklikten önce üretilmiş link belirsiz bir URL'i gösteriyorsa
		hangi bloba yetki verildiği bilinemez → reddet. Etki penceresi
		`MAX_TTL_SECONDS` (24 saat) ile sınırlı."""
		self._params()
		with mock.patch.object(media_access, "verify_request", return_value=True):
			with mock.patch.object(media_access, "send_private_file") as sent:
				with self.assertRaises(frappe.PermissionError):
					media_access.download()
		sent.assert_not_called()

	def test_yanlis_blob_reddedilir(self):
		"""KRİTİK: imza B'nin (bayat) hash'ini kapsıyorsa diskteki içerik
		B'nin yüklediği değildir — servis edilmemeli."""
		self._params(blob="0" * 32)
		with mock.patch.object(media_access, "verify_request", return_value=True):
			with mock.patch.object(media_access, "send_private_file") as sent:
				with self.assertRaises(frappe.PermissionError):
					media_access.download()
		sent.assert_not_called()

	def test_dogru_blob_serve_edilir(self):
		"""Meşru erişim kırılmıyor: imza diskteki içeriği kapsıyorsa geçer."""
		self._params(blob=self.disk_hash)
		with mock.patch.object(media_access, "verify_request", return_value=True):
			with mock.patch.object(media_access, "send_private_file", return_value=Response(b"ok")):
				response = media_access.download()
		self.assertEqual(response.status_code, 200)

	def test_blob_mismatch_reddi_audit_a_yazar(self):
		self._params(blob="0" * 32)
		with mock.patch.object(media_access, "verify_request", return_value=True):
			with mock.patch.object(media_access.audit, "log_media_event") as m:
				with self.assertRaises(frappe.PermissionError):
					media_access.download()

		m.assert_called_once()
		_, kwargs = m.call_args
		self.assertEqual(kwargs["action"], media_access.audit.ACTION_ACCESS_DENIED)
		self.assertFalse(kwargs["allowed"])
		self.assertEqual(kwargs["reason"], "blob_mismatch")

	def test_blob_okunamiyorsa_reddedilir(self):
		"""Asimetri testi: `blob_matches_row` karar veremediğinde fail-OPEN
		(altında kiracı kuralı var). `download()` guest yolu — altında hiçbir
		şey yok, o yüzden fail-CLOSED."""
		self._params(blob=self.disk_hash)
		with mock.patch.object(media_access, "verify_request", return_value=True):
			with mock.patch.object(file_isolation, "_blob_hash", return_value=None):
				with mock.patch.object(media_access, "send_private_file") as sent:
					with self.assertRaises(frappe.PermissionError):
						media_access.download()
		sent.assert_not_called()

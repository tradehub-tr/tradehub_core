"""WP3 (TUR-139) — satıcı medya depolama kotası enforcement testleri.

`entitlement.checks.check_media_storage_quota` (File.before_insert hook) için
saf-Python testler. Diğer entitlement test dosyalarıyla (test_entitlement.py,
test_phase1_integration.py) AYNI desen: frappe stub'lanır, `checks` modülünün
içine import edilen `get_quota_limits` / `files.storage_usage` /
`get_current_seller_profile` adları doğrudan monkeypatch edilir — gerçek DB'ye
veya `File.insert()`'in tüm yan etkilerine (naming hash, optimize kuyruğu,
audit log) ihtiyaç yok; test edilen tek şey kota kararının kendisi.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_media_quota

    # Frappe test runner (bench) ile:
    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_quota
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


# ---------------------------------------------------------------------------
# Frappe stub
# ---------------------------------------------------------------------------

_DB: dict = {}


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	frappe.session = SimpleNamespace(user="seller@x.com")
	frappe.flags = SimpleNamespace()
	frappe.get_roles = lambda u: _DB.get(("roles", u), [])

	def db_get_value(doctype, filters=None, fieldname=None, **kwargs):
		key = (doctype, str(filters), str(fieldname))
		return _DB.get(key)

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		exists=lambda *a, **kw: False,
		escape=lambda s: f"'{s}'",
	)

	class _CacheStub:
		def get_value(self, key):
			return None

		def set_value(self, key, value, expires_in_sec=None):
			pass

		def delete_value(self, key):
			pass

	frappe.cache = lambda: _CacheStub()

	if not hasattr(frappe, "_"):
		frappe._ = lambda s: s

	if not hasattr(frappe, "ValidationError"):

		class ValidationError(Exception):
			pass

		frappe.ValidationError = ValidationError

	if not hasattr(frappe, "PermissionError"):

		class PermissionError(Exception):
			pass

		frappe.PermissionError = PermissionError

	# frappe.throw varsayılan exc'i ValidationError (gerçek Frappe davranışı) —
	# brief'teki test snippet'i `assertRaises(frappe.ValidationError)` bekliyor.
	def _throw(msg, exc=None):
		exc = exc or frappe.ValidationError
		raise exc(msg) if isinstance(exc, type) else Exception(msg)

	frappe.throw = _throw

	if not hasattr(frappe, "log_error"):
		frappe.log_error = lambda *a, **kw: None

	if not hasattr(frappe, "logger"):
		frappe.logger = lambda: SimpleNamespace(info=lambda *a, **kw: None, error=lambda *a, **kw: None)

	if not hasattr(frappe, "get_all"):
		frappe.get_all = lambda *a, **kw: []

	if not hasattr(frappe, "get_cached_doc"):

		def get_cached_doc(doctype, name):
			raise Exception(f"{doctype} '{name}' not found")

		frappe.get_cached_doc = get_cached_doc
		frappe.get_doc = get_cached_doc


_install_frappe_stub()


def _reset_state() -> None:
	_DB.clear()
	_install_frappe_stub()


def _install_fake_media_files() -> types.ModuleType:
	"""`tradehub_core.media.files`'ın YERİNE sahte bir modül enjekte et.

	`checks.py`'nin `from tradehub_core.media import files` satırı gerçek
	modülü yüklerse `media.audit` üzerinden `frappe.query_builder`'a (gerçek
	Frappe paketi gerektirir) kadar iniyor — bu dosyanın diğer entitlement
	test'leriyle (test_entitlement.py, test_phase1_integration.py) aynı
	saf-Python stub deseninde çalışabilmesi için `files` modülünü `sys.modules`
	üzerinden sahteyle değiştiriyoruz. Testler zaten her senaryoda
	`checks.files.storage_usage`'ı override ediyor — gerçek implementasyona
	ihtiyaç yok, sadece import zincirinin kırılmaması gerekiyor.
	"""
	import tradehub_core  # noqa: F401 — boş __init__, sorunsuz
	import tradehub_core.media  # noqa: F401 — boş __init__, sorunsuz

	fake = types.ModuleType("tradehub_core.media.files")
	fake.storage_usage = lambda store: {"bytes": 0, "files": 0, "quota_bytes": None}
	sys.modules["tradehub_core.media.files"] = fake
	sys.modules["tradehub_core.media"].files = fake
	return fake


_install_fake_media_files()

# Modülleri stub kurulduktan sonra import et.
from tradehub_core.entitlement import checks  # noqa: E402


def _make_file_doc(**overrides) -> SimpleNamespace:
	"""File doc'unun `before_insert` sırasındaki minimal görünümü.

	Gerçek Frappe akışında core `File.before_insert()` (hooks.py listesindeki
	custom hook'lardan ÖNCE çalışır, bkz. `Document.hook`'un compose sırası)
	`file_size`'ı diskteki içerikten zaten hesaplamış olur — bu yüzden asıl
	kontrol `file_size` üzerinden yapılıyor, `content` sadece fallback.
	"""
	defaults = dict(
		doctype="File",
		file_name="urun.webp",
		is_private=0,
		is_folder=0,
		attached_to_doctype=None,
		file_size=0,
		content=b"",
	)
	defaults.update(overrides)
	doc = SimpleNamespace(**defaults)
	doc.get = lambda field, default=None: getattr(doc, field, default)
	doc.flags = overrides.get("flags", SimpleNamespace())
	return doc


class CheckMediaStorageQuotaTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		self._orig_get_current_seller_profile = checks.get_current_seller_profile
		self._orig_get_quota_limits = checks.get_quota_limits
		self._orig_storage_usage = checks.files.storage_usage

	def tearDown(self):
		checks.get_current_seller_profile = self._orig_get_current_seller_profile
		checks.get_quota_limits = self._orig_get_quota_limits
		checks.files.storage_usage = self._orig_storage_usage

	def _wire_store(self, store: str, quota_mb, used_bytes: int) -> None:
		"""Mağaza + plan kotası + mevcut kullanım mock'la."""
		checks.get_current_seller_profile = lambda: store
		checks.get_quota_limits = lambda s: {"quota.max_storage_mb": quota_mb} if s == store else {}
		checks.files.storage_usage = lambda s: {"bytes": used_bytes, "files": 1, "quota_bytes": None}

	# --- Step 3 senaryoları (brief) --------------------------------------

	def test_kota_asiminda_upload_reddedilir(self):
		"""1 MB'lık kota + 2MB'lık mevcut kullanım → yeni 1 byte'lık dosya bile reddedilir."""
		self._wire_store("STORE-A", quota_mb=1, used_bytes=2 * 1024 * 1024)
		doc = _make_file_doc(file_size=1)

		with self.assertRaises(sys.modules["frappe"].ValidationError):
			checks.check_media_storage_quota(doc)

	def test_kyb_dosyasi_kotadan_muaf(self):
		"""KYB Verification'a bağlı dosya EXCLUDED_DOCTYPES'ta — kota aşımında bile geçer."""
		self._wire_store("STORE-A", quota_mb=1, used_bytes=2 * 1024 * 1024)
		doc = _make_file_doc(file_size=5 * 1024 * 1024, attached_to_doctype="KYB Verification")

		checks.check_media_storage_quota(doc)  # frappe.throw ATMAMALI

	# --- Ek kenar durumlar -------------------------------------------------

	def test_kota_altinda_upload_kabul_edilir(self):
		self._wire_store("STORE-B", quota_mb=10, used_bytes=1024)
		doc = _make_file_doc(file_size=1024)
		checks.check_media_storage_quota(doc)  # throw yok

	def test_sinirsiz_kota_her_zaman_kabul(self):
		self._wire_store("STORE-C", quota_mb=-1, used_bytes=999 * 1024 * 1024 * 1024)
		doc = _make_file_doc(file_size=10 * 1024 * 1024)
		checks.check_media_storage_quota(doc)  # -1 → sınırsız, throw yok

	def test_tanimsiz_kota_reddetmez(self):
		"""Seed patch atlanmışsa (`quota.max_storage_mb` planda yok) fail-open: reddetme."""
		checks.get_current_seller_profile = lambda: "STORE-D"
		checks.get_quota_limits = lambda s: {}  # key hiç yok → None
		checks.files.storage_usage = lambda s: {"bytes": 0, "files": 0, "quota_bytes": None}
		doc = _make_file_doc(file_size=10 * 1024 * 1024 * 1024)
		checks.check_media_storage_quota(doc)  # throw yok — kritik güvenlik ağı

	def test_magazasiz_oturum_muaf(self):
		"""Guest/admin/tenant'sız kullanıcı — mağaza çözülemez, kontrol atlanır."""
		checks.get_current_seller_profile = lambda: None
		doc = _make_file_doc(file_size=999 * 1024 * 1024)
		checks.check_media_storage_quota(doc)  # throw yok

	def test_system_manager_muaf(self):
		_DB[("roles", "admin@x.com")] = ["System Manager"]
		sys.modules["frappe"].session.user = "admin@x.com"
		self._wire_store("STORE-E", quota_mb=1, used_bytes=999 * 1024 * 1024)
		doc = _make_file_doc(file_size=999 * 1024 * 1024)
		checks.check_media_storage_quota(doc)  # rol bypass — throw yok

	def test_private_dosya_muaf(self):
		"""`storage_usage` yalnız is_private=0 sayıyor — private dosyaya kota uygulanmaz."""
		self._wire_store("STORE-F", quota_mb=1, used_bytes=2 * 1024 * 1024)
		doc = _make_file_doc(file_size=999 * 1024 * 1024, is_private=1)
		checks.check_media_storage_quota(doc)  # throw yok

	def test_klasor_muaf(self):
		self._wire_store("STORE-G", quota_mb=1, used_bytes=2 * 1024 * 1024)
		doc = _make_file_doc(is_folder=1, file_size=999 * 1024 * 1024)
		checks.check_media_storage_quota(doc)  # throw yok

	def test_tam_kota_sinirinda_reddedilir(self):
		"""Toplam == limit → aşım sayılmaz (`>` kullanılıyor); toplam limiti aşınca reddedilir."""
		self._wire_store("STORE-H", quota_mb=1, used_bytes=0)
		tam_limit = 1 * 1024 * 1024
		doc_tam = _make_file_doc(file_size=tam_limit)
		checks.check_media_storage_quota(doc_tam)  # == limit, throw yok

		self._wire_store("STORE-H", quota_mb=1, used_bytes=0)
		doc_asan = _make_file_doc(file_size=tam_limit + 1)
		with self.assertRaises(sys.modules["frappe"].ValidationError):
			checks.check_media_storage_quota(doc_asan)


if __name__ == "__main__":
	unittest.main()

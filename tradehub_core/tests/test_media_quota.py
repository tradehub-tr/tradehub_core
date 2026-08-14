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


try:  # Gerçek frappe (bench env). Bulunamazsa asgari bir modül kurulur.
	import frappe
except ModuleNotFoundError:  # pragma: no cover — bench dışı ortam
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	# Import ANINDA gereken adlar: `entitlement.core` ve `checks` modül
	# seviyesinde `from frappe import _` yapıyor, dekoratörler `whitelist`
	# istiyor. Bunlar test başlamadan hazır olmalı; davranışsal yamalar
	# (session/db/roles) `FrappeStubCase.setUp` içinde kuruluyor.
	frappe._ = lambda s, *a, **kw: s
	frappe.whitelist = lambda *a, **kw: (lambda fn: fn)
	frappe.ValidationError = type("ValidationError", (Exception,), {})
	frappe.PermissionError = type("PermissionError", (Exception,), {})
	frappe.DoesNotExistError = type("DoesNotExistError", (Exception,), {})


# Eskiden bu dosya `frappe` üzerindeki adları KALICI olarak eziyordu. bench ile
# koşulduğunda `frappe.db` test bittikten sonra da `SimpleNamespace` kalıyor ve
# aynı süreçteki sonraki testler `'SimpleNamespace' object has no attribute
# 'commit'` diye çöküyordu. Artık her test kendi yamasını kurup `addCleanup` ile
# geri alıyor; gerçek bağlantı varsa `frappe.db`'ye hiç dokunulmuyor.
_YOK = object()


class _CacheStub:
	def get_value(self, key):
		return None

	def set_value(self, key, value, expires_in_sec=None):
		pass

	def delete_value(self, key):
		pass


class FrappeStubCase(unittest.TestCase):
	"""Kota kararını izole eden asgari `frappe` yaması; test sonunda geri alınır."""

	def setUp(self):
		_DB.clear()
		self._orijinaller: dict[str, object] = {}

		self._yamala("session", SimpleNamespace(user="seller@x.com"))
		self._yamala("flags", SimpleNamespace())
		self._yamala("get_roles", lambda u: _DB.get(("roles", u), []))
		# `cache` yalnız gerçeği yokken yamanıyor: Frappe v15'te `frappe.cache`
		# bir NESNE (çağrılabilir değil) ve çeviri katmanı `frappe.cache.hget`
		# çağırıyor — burada fonksiyona çevirmek `_("...")` çağrısını kırıyordu.
		if getattr(frappe, "cache", None) is None:
			self._yamala("cache", lambda: _CacheStub())

		if getattr(frappe, "db", None) is None:

			def db_get_value(doctype, filters=None, fieldname=None, **kwargs):
				return _DB.get((doctype, str(filters), str(fieldname)))

			self._yamala(
				"db",
				SimpleNamespace(
					get_value=db_get_value,
					exists=lambda *a, **kw: False,
					escape=lambda s: f"'{s}'",
				),
			)

		if not hasattr(frappe, "_"):
			self._yamala("_", lambda s: s)
		if not hasattr(frappe, "ValidationError"):
			self._yamala("ValidationError", type("ValidationError", (Exception,), {}))
		if not hasattr(frappe, "PermissionError"):
			self._yamala("PermissionError", type("PermissionError", (Exception,), {}))
		# `throw` HER ZAMAN yamanıyor: gerçek `frappe.throw` msgprint üzerinden
		# çeviri katmanına giriyor ve bu testin ölçtüğü şeyle (kota kararı)
		# ilgisi olmayan ortam sorunlarında (bozuk bir çeviri dosyası) patlıyor.
		# Davranış aynı: verilen exc sınıfıyla, yoksa ValidationError ile fırlat.
		def _throw(msg, exc=None, **kwargs):
			exc = exc or frappe.ValidationError
			raise exc(msg) if isinstance(exc, type) else Exception(msg)

		self._yamala("throw", _throw)
		if not hasattr(frappe, "log_error"):
			self._yamala("log_error", lambda *a, **kw: None)
		if not hasattr(frappe, "logger"):
			self._yamala(
				"logger",
				lambda: SimpleNamespace(info=lambda *a, **kw: None, error=lambda *a, **kw: None),
			)
		if not hasattr(frappe, "get_all"):
			self._yamala("get_all", lambda *a, **kw: [])
		if not hasattr(frappe, "get_cached_doc"):

			def get_cached_doc(doctype, name):
				raise Exception(f"{doctype} '{name}' not found")

			self._yamala("get_cached_doc", get_cached_doc)
			self._yamala("get_doc", get_cached_doc)

		self.addCleanup(self._geri_al)

	def _yamala(self, ad: str, deger) -> None:
		self._orijinaller.setdefault(ad, getattr(frappe, ad, _YOK))
		setattr(frappe, ad, deger)

	def _geri_al(self) -> None:
		for ad, eski in self._orijinaller.items():
			if eski is _YOK:
				delattr(frappe, ad)
			else:
				setattr(frappe, ad, eski)
		self._orijinaller.clear()


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


try:
	# bench ortamında gerçek modül sorunsuz yükleniyor; sahtesini enjekte etmek
	# `sys.modules`'ü kalıcı olarak kirletir ve aynı süreçteki diğer testler
	# gerçek `media.files` yerine bu boş modülü görürdü.
	from tradehub_core.media import files as _gercek_files  # noqa: F401
except Exception:  # pragma: no cover — saf-Python koşumu (site/Frappe yok)
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


class CheckMediaStorageQuotaTests(FrappeStubCase):
	def setUp(self):
		super().setUp()
		self._orig_get_current_seller_profile = checks.get_current_seller_profile
		self._orig_get_quota_limits = checks.get_quota_limits
		self._orig_storage_usage = checks.files.storage_usage
		# `checks` modülü `from frappe import _` ile çeviriciyi kendi ad alanına
		# almış; `frappe._`'yi yamalamak onu etkilemez. Ret mesajının çevirisi bu
		# testin konusu değil, kimliğe indiriyoruz.
		self._orig_ceviri = checks._
		checks._ = lambda s, *a, **kw: s

	def tearDown(self):
		checks.get_current_seller_profile = self._orig_get_current_seller_profile
		checks.get_quota_limits = self._orig_get_quota_limits
		checks.files.storage_usage = self._orig_storage_usage
		checks._ = self._orig_ceviri

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

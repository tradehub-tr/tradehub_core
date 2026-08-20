"""T-132 — yetki sertleştirme regresyon ağı (bench/site GEREKMEZ).

docs/reports/29-pentest-duzeltmeleri.md bugün dört sızma bulgusunu (T1, T2, T3,
T9) ve raporda ayrıca sayılan iki yeni vektörü kapattı. O raporun kanıtı
**canlı sistemde** üretildi ve yanındaki üç test modülü
(`test_payment_transaction_isolation`, `test_verification_status_guard`,
`test_rate_limit_guest_bucket`) `import frappe` ile başlıyor: bench + site
olmadan KOŞMAZLAR. Yani düzeltmeler bugün yeşil, ama sitesiz bir ortamda
(CI, yerel `python3 -m unittest`) sessizce geri alınabilirler.

Bu modül o boşluğu kapatır. İki tür test var ve ikisi de frappe'siz koşar:

1. **Davranış** — `api/rate_limit.py` ve `permissions.py`'nin GERÇEK
   fonksiyonları, en küçük bir `frappe` taklidiyle çağrılır. Taklit edilen şey
   yalnız ÇERÇEVE (oturum, istek başlığı, rol listesi); karar kodu gerçektir.
2. **Kablolama** — hook kaydı, permlevel, patch kaydı ve `validate()` çağrı
   sırası kaynaktan (`ast`/JSON) okunur. Bunlar 29 nolu raporun vacuity
   koşumunun kalıcı hâlidir: kayıt silinirse bu testler kırmızıya döner.

ÖLÇÜLMEYEN: T9'un uçtan uca yarısı bu depoda DEĞİL (`docker/` nginx zinciri,
29 §5.4). Buradaki testler kod tarafını korur, topolojiyi ölçmez.
"""

from __future__ import annotations

import ast
import contextlib
import importlib
import json
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

APP = ROOT / "tradehub_core"
HOOKS = APP / "hooks.py"
PERMISSIONS = APP / "permissions.py"
PATCHES = APP / "patches.txt"
RATE_LIMIT = APP / "api" / "rate_limit.py"
KYC_DIR = APP / "tradehub_core" / "doctype" / "kyc_verification"
KYB_DIR = APP / "tradehub_core" / "doctype" / "kyb_verification"
TESTS = APP / "tests"


# ═══════════════════════════════════════════════════════════════════════
# frappe taklidi — YALNIZ çerçeve, karar kodu değil
# ═══════════════════════════════════════════════════════════════════════


class SahtePermissionError(Exception):
	pass


class _Bayraklar:
	in_install = False
	in_migrate = False
	in_patch = False


class _Yerel:
	def __init__(self) -> None:
		self.request = None
		self.request_ip = ""


def _sahte_frappe(*, roller=(), kullanici="Guest", basliklar=None, request=True, request_ip=""):
	"""En küçük `frappe` modülü.

	Taklit YALNIZ şunları sağlar: oturum, rol listesi, istek başlıkları, konf,
	bayraklar, `throw`. Kova kimliği, güvenilir-vekil kararı ve durum geçişi
	kapısı GERÇEK koddan gelir — taklit edilirse test hiçbir şey ölçmez.
	"""
	basliklar = {k.lower(): v for k, v in (basliklar or {}).items()}
	f = types.ModuleType("frappe")
	f.local = _Yerel()
	f.local.request = object() if request else None
	f.local.request_ip = request_ip
	f.session = types.SimpleNamespace(user=kullanici)
	f.conf = {}
	f.flags = _Bayraklar()
	f.PermissionError = SahtePermissionError
	f.ValidationError = ValueError
	f.DoesNotExistError = KeyError
	f._ = lambda metin, *a, **k: metin
	f.get_request_header = lambda ad, default=None: basliklar.get(ad.lower(), default)
	f.get_roles = lambda user=None: list(roller)
	f.log_error = lambda *a, **k: None
	f.logger = lambda *a, **k: types.SimpleNamespace(
		info=lambda *x, **y: None, warning=lambda *x, **y: None, error=lambda *x, **y: None
	)

	onbellek: dict = {}

	def local_cache(ns, key, builder=None):
		if builder is None:
			return onbellek.get((ns, key))
		if (ns, key) not in onbellek:
			onbellek[(ns, key)] = builder()
		return onbellek[(ns, key)]

	f.local_cache = local_cache

	def throw(mesaj, exc=None, **kw):
		raise (exc or SahtePermissionError)(mesaj)

	f.throw = throw
	f.db = types.SimpleNamespace(
		get_value=lambda *a, **k: None, exists=lambda *a, **k: None, sql=lambda *a, **k: []
	)
	f.get_all = lambda *a, **k: []
	f.get_list = lambda *a, **k: []
	f.get_doc = lambda *a, **k: None
	f.get_cached_doc = lambda *a, **k: None
	f.cache = lambda *a, **k: types.SimpleNamespace(
		get_value=lambda *x, **y: None, set_value=lambda *x, **y: None
	)

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda v, precision=None: float(v or 0)
	utils.cint = lambda v: int(v or 0)
	utils.now_datetime = lambda: None
	utils.get_datetime = lambda *a, **k: None
	utils.cstr = lambda v: "" if v is None else str(v)
	f.utils = utils
	return f, utils


@contextlib.contextmanager
def sahte_frappe_ile(modul_adi: str, **kw):
	"""`modul_adi`'nı taklit `frappe` ile taze içe aktar, sonra HER ŞEYİ geri al.

	`sys.modules` bu süreçte başka test modülleriyle paylaşılıyor; taklidi
	bırakmak sonraki testleri sessizce zehirlerdi.
	"""
	korunacak = [
		"frappe",
		"frappe.utils",
		modul_adi,
		"tradehub_core.utils.tenant",
		"tradehub_core.permissions",
	]
	yedek = {ad: sys.modules.get(ad) for ad in korunacak}
	f, utils = _sahte_frappe(**kw)
	try:
		sys.modules["frappe"] = f
		sys.modules["frappe.utils"] = utils
		for ad in korunacak[2:]:
			sys.modules.pop(ad, None)
		yield importlib.import_module(modul_adi), f
	finally:
		for ad, deger in yedek.items():
			if deger is None:
				sys.modules.pop(ad, None)
			else:
				sys.modules[ad] = deger


# ═══════════════════════════════════════════════════════════════════════
# T9 — misafir hız-sınırı kovası (DAVRANIŞ)
# ═══════════════════════════════════════════════════════════════════════


class T9GuestBucketRegressionTest(unittest.TestCase):
	"""29 §5 — tüm misafirler tek `Guest` kovasındaydı; DoS vektörü."""

	def _kimlik(self, **kw) -> str:
		with sahte_frappe_ile("tradehub_core.api.rate_limit", **kw) as (mod, _f):
			return mod._bucket_identity()

	def test_iki_misafir_farkli_ip_farkli_kova(self):
		a = self._kimlik(basliklar={"X-Forwarded-For": "203.0.113.10"})
		b = self._kimlik(basliklar={"X-Forwarded-For": "203.0.113.11"})
		self.assertNotEqual(a, b)
		self.assertEqual(a, "Guest:203.0.113.10")

	def test_istemcinin_uydurdugu_soldaki_xff_kullanilmaz(self):
		"""Zincir SAĞDAN SOLA okunur: istemci başa istediğini yazabilir."""
		kimlik = self._kimlik(
			basliklar={"X-Forwarded-For": "203.0.113.99, 198.51.100.7, 10.0.0.5"}
		)
		self.assertEqual(kimlik, "Guest:198.51.100.7")

	def test_tamamen_ozel_zincir_cozulemedi_der(self):
		"""Yanlış kimliğe bağlanmaktansa görünür şekilde çözülemedi demek."""
		kimlik = self._kimlik(basliklar={"X-Forwarded-For": "10.0.0.5, 172.17.0.2"})
		self.assertEqual(kimlik, "Guest:_unresolved")

	def test_ayristirilamayan_deger_kimlik_olamaz(self):
		kimlik = self._kimlik(basliklar={"X-Forwarded-For": "not-an-ip"})
		self.assertEqual(kimlik, "Guest:_unresolved")

	def test_oturum_acmis_kullanici_ipye_bagli_degil(self):
		kimlik = self._kimlik(
			kullanici="ali@example.com", basliklar={"X-Forwarded-For": "203.0.113.10"}
		)
		self.assertEqual(kimlik, "ali@example.com")

	def test_x_real_ip_yedek_yol(self):
		self.assertEqual(
			self._kimlik(basliklar={"X-Real-IP": "203.0.113.20"}), "Guest:203.0.113.20"
		)

	def test_ozel_aralikli_request_ip_kimlik_olmaz(self):
		self.assertEqual(self._kimlik(request_ip="192.168.1.4"), "Guest:_unresolved")
		self.assertEqual(self._kimlik(request_ip="203.0.113.30"), "Guest:203.0.113.30")

	def test_kova_anahtari_kimligi_tasir(self):
		with sahte_frappe_ile(
			"tradehub_core.api.rate_limit", basliklar={"X-Forwarded-For": "203.0.113.10"}
		) as (mod, _f):
			self.assertEqual(
				mod._bucket_key("x", mod._bucket_identity()), "rl:x:Guest:203.0.113.10"
			)


# ═══════════════════════════════════════════════════════════════════════
# T2/T3 — KYC/KYB kendini-doğrulama kapısı (DAVRANIŞ)
# ═══════════════════════════════════════════════════════════════════════


class _SahteDoc:
	"""`has_value_changed` + `get_doc_before_save` sözleşmesini taşıyan künye."""

	def __init__(self, onceki: str | None, yeni: str) -> None:
		self.status = yeni
		self._onceki = onceki

	def has_value_changed(self, alan: str) -> bool:
		return getattr(self, alan) != self._onceki

	def get_doc_before_save(self):
		if self._onceki is None:
			return None
		return types.SimpleNamespace(status=self._onceki)


#: `permissions.py` → `utils/tenant.py` zinciri `str | None` yazıyor ve
#: `from __future__ import annotations` taşımıyor: 3.10 altında İMPORT anında
#: TypeError. Depo zaten `requires-python = ">=3.10"` (üretim 3.12) — eski bir
#: yorumlayıcıda testi KIRMIZI göstermek yanlış sinyal olurdu, ama sessizce
#: geçmek de yalancı yeşil olur: atlanır ve sebebi yazılır.
PY310 = sys.version_info >= (3, 10)


@unittest.skipUnless(PY310, "permissions.py 3.10+ sözdizimi istiyor (ÖLÇÜLMEDİ)")
class T2T3VerificationGuardRegressionTest(unittest.TestCase):
	"""29 §4 — satıcı kendi KYC/KYB'sinde `status=Verified` yazabiliyordu."""

	def _kapi(self, doc, roller=()):
		with sahte_frappe_ile("tradehub_core.permissions", roller=roller) as (mod, f):
			return mod.guard_verification_status_change, f, doc

	def _calistir(self, onceki, yeni, roller=(), kullanici="satici@example.com"):
		with sahte_frappe_ile(
			"tradehub_core.permissions", roller=roller, kullanici=kullanici
		) as (mod, _f):
			mod.guard_verification_status_change(_SahteDoc(onceki, yeni))

	def test_rolsuz_kullanici_kendini_verified_yapamaz(self):
		with self.assertRaises(SahtePermissionError):
			self._calistir("Pending", "Verified", roller=("Marketplace Seller",))

	def test_rolsuz_kullanici_under_review_yazamaz(self):
		for hedef in ("Under Review", "Rejected", "Suspended"):
			with self.subTest(hedef=hedef):
				with self.assertRaises(SahtePermissionError):
					self._calistir("Pending", hedef, roller=("Marketplace Seller",))

	def test_inceleme_yetkilisi_verified_yazabilir(self):
		self._calistir("Pending", "Verified", roller=("Marketplace Admin",))

	def test_administrator_gecer(self):
		self._calistir("Pending", "Verified", kullanici="Administrator")

	def test_status_degismediyse_kapi_calismaz(self):
		self._calistir("Verified", "Verified", roller=("Marketplace Seller",))

	def test_yeni_kayitta_verified_reddedilir(self):
		"""29 §4.2'deki yeni vektör: kayıt SIFIRDAN `Verified` açılıyordu."""
		with self.assertRaises(SahtePermissionError):
			self._calistir(None, "Verified", roller=("Marketplace Seller",))

	def test_inceleme_rolleri_bos_degil(self):
		with sahte_frappe_ile("tradehub_core.permissions") as (mod, _f):
			self.assertTrue(mod.VERIFICATION_REVIEWER_ROLES)
			self.assertNotIn("Marketplace Seller", mod.VERIFICATION_REVIEWER_ROLES)
			self.assertNotIn("Marketplace Buyer", mod.VERIFICATION_REVIEWER_ROLES)

	def test_self_servis_gecisleri_verified_icermez(self):
		"""Beyaz liste `Verified`'a giden hiçbir geçiş taşımamalı."""
		with sahte_frappe_ile("tradehub_core.permissions") as (mod, _f):
			hedefler = {yeni for _onceki, yeni in mod.SELF_SERVICE_VERIFICATION_TRANSITIONS}
			self.assertEqual(hedefler & {"Verified", "Under Review", "Rejected", "Suspended"}, set())


# ═══════════════════════════════════════════════════════════════════════
# Kablolama — kayıt silinirse KIRMIZI (29 nolu raporun vacuity'sinin kalıcı hâli)
# ═══════════════════════════════════════════════════════════════════════


def _modul_sozlugu(yol: Path, ad: str) -> dict:
	"""`ast` ile modül düzeyindeki bir sözlük ataması oku — import ETMEDEN.

	`hooks.py` `import frappe` içerir ve bu ağaçta frappe yok; kaydın varlığını
	ölçmenin frappe'siz tek yolu kaynağı ayrıştırmaktır.
	"""
	agac = ast.parse(yol.read_text(encoding="utf-8"))
	for node in agac.body:
		hedefler = (
			node.targets
			if isinstance(node, ast.Assign)
			else ([node.target] if isinstance(node, ast.AnnAssign) and node.value else [])
		)
		if not any(isinstance(t, ast.Name) and t.id == ad for t in hedefler):
			continue
		if isinstance(node.value, ast.Dict):
			return {
				k.value: (v.value if isinstance(v, ast.Constant) else v)
				for k, v in zip(node.value.keys, node.value.values)
				if isinstance(k, ast.Constant)
			}
	raise AssertionError(f"{yol.name} içinde `{ad}` sözlüğü yok")


def _fonksiyon_adlari(yol: Path) -> set:
	agac = ast.parse(yol.read_text(encoding="utf-8"))
	return {n.name for n in ast.walk(agac) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


class WiringRegressionTest(unittest.TestCase):
	def test_t1_payment_transaction_hooklari_kayitli(self):
		"""29 §3.5 vacuity'si bu iki kaydı silip KIRMIZI göstermişti."""
		pqc = _modul_sozlugu(HOOKS, "permission_query_conditions")
		hp = _modul_sozlugu(HOOKS, "has_permission")
		self.assertEqual(
			pqc.get("Payment Transaction"),
			"tradehub_core.permissions.payment_transaction_query_conditions",
		)
		self.assertEqual(
			hp.get("Payment Transaction"),
			"tradehub_core.permissions.payment_transaction_has_permission",
		)

	def test_t1_handler_fonksiyonlari_var(self):
		adlar = _fonksiyon_adlari(PERMISSIONS)
		for ad in (
			"payment_transaction_query_conditions",
			"payment_transaction_has_permission",
			"guard_verification_status_change",
			"is_verification_reviewer",
		):
			with self.subTest(fonksiyon=ad):
				self.assertIn(ad, adlar)

	def test_t1_order_kaydi_kaybolmadi(self):
		"""`Payment Transaction` kaydı `Order`'ın aynası; ikisi birlikte durur."""
		pqc = _modul_sozlugu(HOOKS, "permission_query_conditions")
		self.assertIn("Order", pqc)
		self.assertIn("Order", _modul_sozlugu(HOOKS, "has_permission"))

	def test_t2_t3_status_permlevel_dort(self):
		for ad, dizin in (("KYC", KYC_DIR), ("KYB", KYB_DIR)):
			with self.subTest(doctype=ad):
				veri = json.loads((dizin / f"{dizin.name}.json").read_text(encoding="utf-8"))
				alan = next(f for f in veri["fields"] if f["fieldname"] == "status")
				self.assertEqual(
					alan.get("permlevel"),
					4,
					"status permlevel 4 değil — kendini-doğrulama yeniden açılır.",
				)

	def test_t2_t3_kapi_validate_icinde_ve_ILK(self):
		"""Kapı `validate()`'in İLK ifadesi olmalı.

		Sonraya alınırsa, önceki bir doğrulama `throw` ettiğinde kapı hiç
		çalışmaz; daha kötüsü, araya giren bir `db_set` yan etkisi kapıdan
		önce işlemiş olur.
		"""
		for ad, dizin in (("KYC", KYC_DIR), ("KYB", KYB_DIR)):
			with self.subTest(doctype=ad):
				agac = ast.parse((dizin / f"{dizin.name}.py").read_text(encoding="utf-8"))
				validate = next(
					n
					for n in ast.walk(agac)
					if isinstance(n, ast.FunctionDef) and n.name == "validate"
				)
				ilk = validate.body[0]
				cagri = getattr(ilk, "value", None)
				self.assertTrue(
					isinstance(cagri, ast.Call)
					and isinstance(cagri.func, ast.Attribute)
					and cagri.func.attr == "_guard_status_change",
					f"{ad}.validate() ilk satırında `_guard_status_change()` yok.",
				)
				self.assertIn("guard_verification_status_change", ast.dump(agac))

	def test_t2_t3_permlevel_patchi_kayitli(self):
		satirlar = [s.strip() for s in PATCHES.read_text(encoding="utf-8").splitlines()]
		self.assertIn("tradehub_core.patches.v15_9_26_kyc_kyb_status_permlevel", satirlar)
		self.assertTrue(
			(APP / "patches" / "v15_9_26_kyc_kyb_status_permlevel.py").exists(),
			"patches.txt kaydı var ama dosya yok.",
		)

	def test_t9_guvenilir_vekil_araliklari_ozel_aglari_kapsiyor(self):
		with sahte_frappe_ile("tradehub_core.api.rate_limit") as (mod, _f):
			for adres in ("127.0.0.1", "10.1.2.3", "172.20.0.4", "192.168.5.6", "100.64.0.1"):
				with self.subTest(adres=adres):
					self.assertTrue(mod._is_trusted_proxy(adres))
			self.assertFalse(mod._is_trusted_proxy("203.0.113.5"))

	def test_pentest_test_modulleri_duruyor(self):
		"""29 §6'daki üç modül silinmesin — sitesi olan ortamda ASIL kanıt onlar."""
		for ad in (
			"test_payment_transaction_isolation.py",
			"test_verification_status_guard.py",
			"test_rate_limit_guest_bucket.py",
		):
			with self.subTest(modul=ad):
				self.assertTrue((TESTS / ad).exists(), f"{ad} silinmiş.")


if __name__ == "__main__":  # pragma: no cover
	unittest.main(verbosity=2)

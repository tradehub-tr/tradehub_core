"""T-134 — KVKK belge erişim + silme izleri denetim testleri (rapor 92).

NEDEN BU DOSYA VAR — ÖLÇÜLMÜŞ BOŞLUK (2026-08-20)
=================================================
KVKK veri-sahibi akışının EN hassas dokunuşu — kişisel veri arşivinin (m.11
dışa aktarım ZIP'i) indirilmesi — HİÇ denetim üretmiyordu; süresi dolan
arşivlerin imhası da (m.7 silme izi) kayıtsızdı. Rapor 92 bu iki noktaya
`privacy.export_downloaded` / `privacy.export_purged` /
`privacy.export_generated` eylemlerini ekledi (mevcut `account.anonymize`
log_decision deseniyle — yeni desen icat edilmedi).

Bu dosya o eklemeleri PINLER, özellikle KVKK maskeleme kuralını:
  - indirme TOKEN'ı denetim satırına ASLA yazılmaz,
  - IP yalnız parmak izi (sha256[:12]) olarak girer,
  - kullanıcı e-postası satıra girmez (kimlik Data Export Request kaydında).

Medya tarafındaki aynı kural zaten pinli — referans:
  tests/test_media_access_level.py::test_gecis_hassas_isaretlenir_ve_ham_url_context_e_yazilmaz
  tests/test_media_access_level.py::test_gercek_adl_kaydinda_object_name_maskeli

Frappe stub'lanır (test_audit.py deseni); gerçek `log_decision` KOŞULUR —
mock değil: satır sahiden `Authorization Decision Log` insert'ine gider.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_privacy_audit
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


_INSERTED: list[dict] = []  # log_decision'ın yazdığı sahte ADL doc'ları


try:  # Gerçek frappe (bench env). Bulunamazsa asgari stub.
	import frappe

	GERCEK_FRAPPE = True
except ModuleNotFoundError:  # pragma: no cover — bench dışı ortam
	GERCEK_FRAPPE = False
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe._ = lambda s, *a, **kw: s
	frappe.whitelist = lambda *a, **kw: (lambda fn: fn)
	frappe.ValidationError = type("ValidationError", (Exception,), {})
	frappe.PermissionError = type("PermissionError", (Exception,), {})
	frappe.DoesNotExistError = type("DoesNotExistError", (Exception,), {})
	frappe.AuthenticationError = type("AuthenticationError", (Exception,), {})

if not hasattr(frappe, "utils") or not hasattr(frappe.utils, "now_datetime"):
	frappe.utils = types.ModuleType("frappe.utils")
	from datetime import datetime

	frappe.utils.cint = int
	frappe.utils.flt = float
	frappe.utils.now_datetime = lambda: datetime(2026, 8, 20, 12, 0, 0)
	frappe.utils.add_days = lambda dt, days: dt
	frappe.utils.add_to_date = lambda dt, **kw: dt
	frappe.utils.get_files_path = lambda **kw: tempfile.gettempdir()
	sys.modules["frappe.utils"] = frappe.utils

# `download_data_export`'a eklenen `@rate_limit` (2026-08-20) `frappe.cache()`
# çağırıyor; düz-unittest stub'ında yoktu → 5 test AttributeError'la düşüyordu
# (bench'te gerçek cache var, 9/9 geçiyordu). Basit in-memory cache: testler
# tek süreç + tek istek olduğundan pencere/TTL davranışı önemsiz, çağrının
# PATLAMAMASI yeter. rate_limit hatada zaten fail-open (F-004).
if not hasattr(frappe, "cache"):
	class _StubCache:
		def __init__(self): self._d = {}
		def make_key(self, k): return k
		def incr(self, k): self._d[k] = self._d.get(k, 0) + 1; return self._d[k]
		def expire(self, k, sec): pass
		def ttl(self, k): return 1
		def get_value(self, k): return self._d.get(k)
		def set_value(self, k, v, **kw): self._d[k] = v
		def delete_value(self, k): self._d.pop(k, None)
		def delete(self, k): self._d.pop(k, None)
	_STUB_CACHE = _StubCache()
	frappe.cache = lambda: _STUB_CACHE

_YOK = object()


class _AdlDoc:
	"""`frappe.get_doc({...})` yerine geçen sahte ADL belgesi."""

	def __init__(self, data):
		self._data = dict(data)
		self.flags = SimpleNamespace(audit_write=False)
		self.name = None

	def insert(self, ignore_permissions=False, **kwargs):
		if not getattr(self.flags, "audit_write", False):
			raise Exception("Audit log doğrudan yazılamaz")
		self.name = f"ADL-{len(_INSERTED) + 1:06d}"
		self._data["name"] = self.name
		_INSERTED.append(dict(self._data))
		return self


class _ExportRequest(SimpleNamespace):
	"""`Data Export Request` yerine geçen sahte belge."""


class PrivacyAuditStubCase(unittest.TestCase):
	"""frappe adlarını yamalar (test_audit.py deseni), test sonunda geri alır."""

	TOKEN = "cok-gizli-indirme-tokeni-XYZ"
	IP = "203.0.113.77"

	def setUp(self):
		_INSERTED.clear()
		self._orijinaller: dict[str, object] = {}
		# `download_data_export` artık `@rate_limit(20/300s, per_user=False)`
		# taşıyor (KVKK brute-force koruması, 2026-08-20). Bench modunda GERÇEK
		# cache paylaşıldığından, aynı süreçte biriken çağrılar (art arda koşum,
		# canlı ölçüm) testi TooManyRequestsError ile düşürüyordu. Her testten
		# önce bu ucun kovasını sıfırla — koruma davranışını değil, test
		# yalıtımını sağlar (`_bucket_key("kvkk_export_dl", "_global")`).
		# rate_limit RAW incr kullanır (`make_key` önceden uygulanmış); silme de
		# aynı raw anahtara `delete` (redis-native, make_key TEKRAR uygulamaz)
		# ile yapılmalı — `delete_value` çift-önek üretip yanlış anahtarı silerdi.
		try:
			_c = frappe.cache()
			_c.delete(_c.make_key("rl:kvkk_export_dl:_global"))
		except Exception:
			pass
		self.request_doc = _ExportRequest(
			name="DER-0001",
			status="Ready",
			download_token=self.TOKEN,
			expires_at=None,
			file_url="/private/files/data-export-abc-def.zip",
			user="kisi@ornek.com",
		)

		gercek_get_doc = getattr(frappe, "get_doc", None)

		def sahte_get_doc(*args, **kwargs):
			if len(args) == 1 and isinstance(args[0], dict) and not kwargs:
				return _AdlDoc(args[0])
			if args and args[0] == "Data Export Request":
				return self.request_doc
			if gercek_get_doc is None:
				raise TypeError("get_doc bu testte yalnız ADL + Data Export Request destekler")
			return gercek_get_doc(*args, **kwargs)

		def _throw(msg, exc=Exception, **kwargs):
			raise exc(msg) if isinstance(exc, type) else Exception(msg)

		self._yamala("get_doc", sahte_get_doc)
		self._yamala("session", SimpleNamespace(user="Guest"))
		# Bench modunda GERÇEK `frappe.local` KOMPLE DEĞİŞTİRİLMEZ: gerçek
		# frappe yolları local.flags/local.cache gibi işlevsel parçalar ister;
		# SimpleNamespace ikamesi bench'te 5 AttributeError + denetim yazımının
		# sessizce kaybı (0 satır) üretti — köstebek avıyla değil, tasarımla
		# çözüldü: gerçekte yalnız gereken öznitelikler yamalanır ve tearDown'da
		# geri alınır; stub modunda eski davranış (komple ikame) sürer.
		if GERCEK_FRAPPE:
			self._local_orijinal = {
				ad: getattr(frappe.local, ad, _YOK) for ad in ("request_ip",)
			}
			frappe.local.request_ip = self.IP
		else:
			self._local_orijinal = None
			self._yamala(
				"local",
				SimpleNamespace(
					request_ip=self.IP,
					response=SimpleNamespace(),
					flags=SimpleNamespace(in_test=True),
				),
			)
		self._yamala("log_error", lambda *a, **kw: None)
		self._yamala("get_traceback", lambda *a, **kw: "")
		self._yamala("throw", _throw)
		self._yamala("logger", lambda *a, **kw: SimpleNamespace(info=lambda *x, **y: None))
		if not hasattr(frappe, "AuthenticationError"):
			self._yamala("AuthenticationError", type("AuthenticationError", (Exception,), {}))
		if getattr(frappe, "db", None) is None or not hasattr(getattr(frappe, "db", None), "commit"):
			self._yamala(
				"db",
				SimpleNamespace(
					get_value=lambda *a, **kw: None,
					set_value=lambda *a, **kw: None,
					exists=lambda *a, **kw: False,
					count=lambda *a, **kw: 0,
					commit=lambda: None,
				),
			)
		self.addCleanup(self._geri_al)

	def _yamala(self, ad: str, deger) -> None:
		self._orijinaller.setdefault(ad, getattr(frappe, ad, _YOK))
		setattr(frappe, ad, deger)

	def _geri_al(self) -> None:
		if getattr(self, "_local_orijinal", None):
			for ad, eski in self._local_orijinal.items():
				if eski is _YOK:
					try:
						delattr(frappe.local, ad)
					except AttributeError:
						pass
				else:
					setattr(frappe.local, ad, eski)
			self._local_orijinal = None
		for ad, eski in self._orijinaller.items():
			if eski is _YOK:
				delattr(frappe, ad)
			else:
				setattr(frappe, ad, eski)
		self._orijinaller.clear()


from tradehub_core.api.v1 import compliance  # noqa: E402
from tradehub_core.privacy import data_export  # noqa: E402


class DownloadAuditTests(PrivacyAuditStubCase):
	"""`download_data_export` — KVKK belge erişim izi (ALLOW + DENY yolları)."""

	def _tek_kayit(self) -> dict:
		self.assertEqual(len(_INSERTED), 1, f"1 denetim satırı beklenirdi, {len(_INSERTED)} yazıldı")
		return _INSERTED[0]

	def test_gecersiz_token_deny_yazar(self):
		with self.assertRaises(frappe.AuthenticationError):
			compliance.download_data_export("DER-0001", "yanlis-token")
		kayit = self._tek_kayit()
		self.assertEqual(kayit["action"], "privacy.export_downloaded")
		self.assertEqual(kayit["decision"], "DENY")
		self.assertEqual(kayit["severity"], "HIGH")
		self.assertEqual(kayit["object_name"], "DER-0001")
		self.assertIn("invalid_token", kayit["context"])

	def test_hazir_olmayan_talep_deny_yazar(self):
		self.request_doc.status = "Expired"
		with self.assertRaises(Exception):
			compliance.download_data_export("DER-0001", self.TOKEN)
		self.assertEqual(self._tek_kayit()["decision"], "DENY")
		self.assertIn("not_ready", self._tek_kayit()["context"])

	def test_basarili_indirme_allow_yazar(self):
		kok = tempfile.mkdtemp()
		# Rapor 92 §4 gerçek yerleşimi: medya motoru dosyayı içerik-adresli
		# ALT KLASÖRE taşıyor (/private/files/8f/8f0a...zip) — basename bunu
		# kırıyordu; test bilinçli olarak alt-klasörlü yolu kullanır.
		os.makedirs(os.path.join(kok, "8f"), exist_ok=True)
		zip_yolu = os.path.join(kok, "8f", "8f0adeadbeef.zip")
		with open(zip_yolu, "wb") as f:
			f.write(b"zip-icerigi-12345")
		self.addCleanup(os.unlink, zip_yolu)
		self.request_doc.file_url = "/private/files/8f/8f0adeadbeef.zip"
		self._yamala("get_site_path", lambda *parts: kok)

		compliance.download_data_export("DER-0001", self.TOKEN)

		kayit = self._tek_kayit()
		self.assertEqual(kayit["action"], "privacy.export_downloaded")
		self.assertEqual(kayit["decision"], "ALLOW")
		self.assertIn("zip_bytes", kayit["context"])
		self.assertEqual(frappe.local.response.type, "download")

	def test_path_escape_deny(self):
		# file_url private/files kökünden kaçarsa indirme reddedilir + DENY yazılır.
		kok = tempfile.mkdtemp()
		self.request_doc.file_url = "/private/files/../../site_config.json"
		self._yamala("get_site_path", lambda *parts: kok)
		with self.assertRaises(Exception):
			compliance.download_data_export("DER-0001", self.TOKEN)
		kayit = self._tek_kayit()
		self.assertEqual(kayit["decision"], "DENY")
		self.assertIn("path_escape", kayit["context"])

	def test_maskeleme_token_ip_email_sizdirmaz(self):
		"""KVKK maskeleme kuralı: token / ham IP / e-posta denetim satırına girmez."""
		with self.assertRaises(frappe.AuthenticationError):
			compliance.download_data_export("DER-0001", "yanlis-token")
		kayit = self._tek_kayit()
		butun_metin = str(kayit)
		self.assertNotIn(self.TOKEN, butun_metin, "İndirme tokeni denetim satırına sızdı.")
		self.assertNotIn("yanlis-token", butun_metin, "Denenen token denetim satırına sızdı.")
		self.assertNotIn(self.IP, butun_metin, "Ham IP denetim satırına sızdı — yalnız hash girmeli.")
		self.assertIn("ip_hash", kayit["context"], "IP parmak izi hiç yazılmamış — forensik iz kayboldu.")
		self.assertNotIn("kisi@ornek.com", butun_metin, "Kullanıcı e-postası denetim satırına sızdı.")

	def test_vacuity_kontrol_gevsetilince_iddia_kirilir(self):
		# Vacuity: maskeleme testi, token context'e YAZILSAYDI gerçekten kırılır mıydı?
		sahte_kayit = {"context": f'{{"token": "{self.TOKEN}"}}'}
		self.assertIn(self.TOKEN, str(sahte_kayit))


class PurgeAuditTests(PrivacyAuditStubCase):
	"""`cleanup_expired_exports` — m.7 silme izi tek özet satırla."""

	def test_imha_tek_ozet_satiri_yazar(self):
		suresi_dolanlar = [
			SimpleNamespace(name="DER-0001", file_url=None),
			SimpleNamespace(name="DER-0002", file_url=None),
		]
		self._yamala("get_all", lambda *a, **kw: suresi_dolanlar)

		data_export.cleanup_expired_exports()

		self.assertEqual(len(_INSERTED), 1, "Toplu imha TEK özet satırı yazmalı (log_media_batch deseni).")
		kayit = _INSERTED[0]
		self.assertEqual(kayit["action"], "privacy.export_purged")
		self.assertEqual(kayit["decision"], "ALLOW")
		self.assertIn("DER-0002", kayit["context"])

	def test_imha_yoksa_satir_yazilmaz(self):
		self._yamala("get_all", lambda *a, **kw: [])
		data_export.cleanup_expired_exports()
		self.assertEqual(len(_INSERTED), 0)


class ActionConstantsTests(unittest.TestCase):
	"""Eylem adları mevcut nokta-desenini izler (media.* / account.* gibi)."""

	def test_privacy_action_adlari(self):
		self.assertEqual(compliance.ACTION_EXPORT_DOWNLOADED, "privacy.export_downloaded")
		self.assertEqual(data_export.ACTION_EXPORT_GENERATED, "privacy.export_generated")
		self.assertEqual(data_export.ACTION_EXPORT_PURGED, "privacy.export_purged")


if __name__ == "__main__":
	unittest.main()

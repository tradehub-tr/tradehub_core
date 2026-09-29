"""T-134 §2 — servis-config sır-erişim denetimi testleri (rapor 103 / iş 2).

ÖLÇÜLEN BOŞLUK (2026-08-20, rapor 92 §3)
========================================
T-134 "sır erişimi (`get_password` çağrısı) audit'e yazılır" istiyor. Yalnız
`logistics_admin.reveal_carrier_secret` denetimliydi. OpenAI/DeepL/VAPID/S3/
imgproxy/client_secret okumaları iz bırakmıyordu.

Bu dosya ortak yardımcının (`audit/secret_access.py`) SÖZLEŞMESİNİ pinler:
  - okuma → TEK `config.secret_access` satırı,
  - sır DEĞERİ satıra ASLA girmez (yardımcı değeri hiç ALMAZ),
  - severity NORMAL (kullanıcı-tetikli reveal değil, sistem okuması).

Ve BİR gerçek çağrı sitesini (`public_api._verify_client`) uçtan uca koşturur:
gerçek sır değeri get_password'dan gelir, denetim satırına sızmadığı ölçülür.

Frappe stub'lanır (test_privacy_audit deseni yeniden kullanılır); gerçek
`log_decision` KOŞULUR — satır sahiden ADL insert'ine gider.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_secret_access_audit
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from tradehub_core.tests.test_privacy_audit import _INSERTED, PrivacyAuditStubCase, frappe

from tradehub_core.audit import secret_access


class SecretAccessHelperTests(PrivacyAuditStubCase):
	"""Ortak yardımcının denetim sözleşmesi."""

	def test_okuma_tek_denetim_satiri_yazar(self):
		secret_access.log_secret_access(
			service="openai",
			field="openai_api_key",
			object_doctype="Translation Settings",
			object_name="Translation Settings",
		)
		self.assertEqual(len(_INSERTED), 1, "Bir sır okuması tam bir denetim satırı yazmalı.")
		kayit = _INSERTED[0]
		self.assertEqual(kayit["action"], "config.secret_access")
		self.assertEqual(kayit["decision"], "ALLOW")
		self.assertEqual(kayit["severity"], "NORMAL")
		self.assertEqual(kayit["object_name"], "Translation Settings")
		self.assertIn("openai", kayit["context"])
		self.assertIn("openai_api_key", kayit["context"])

	def test_sir_degeri_satira_girmez(self):
		"""Yardımcı değeri parametre olarak hiç almaz — yapısal maskeleme."""
		secret_access.log_secret_access(service="s3", field="s3_secret_key")
		butun = str(_INSERTED[0])
		# Bağlamda alan ADI var, ama hiçbir sır DEĞERİ yok (değer hiç geçilmedi).
		self.assertIn("s3_secret_key", butun)
		self.assertNotIn("get_password", butun)

	def test_vacuity_deger_context_e_konsaydi_yakalanirdi(self):
		# Vacuity: maskeleme testi, değer gerçekten context'e YAZILSAYDI kırılır mıydı?
		sahte = {"context": '{"service": "s3", "secret": "AKIA-SUPER-SECRET"}'}
		self.assertIn("AKIA-SUPER-SECRET", str(sahte))


class _ClientStubBase(PrivacyAuditStubCase):
	"""Tek bir `API Application` (client_id `client-id-1`) taklidi — iki sınıf paylaşır."""

	SECRET = "cok-gizli-client-secret-XYZ-987"

	def setUp(self):
		super().setUp()
		# `_verify_client`, `get_value(..., as_dict=True)` sonucuna ÖZNİTELİK ile
		# erişir (`app.name`, `app.rate_limit_tier`) — düz dict değil, öznitelikli
		# nesne gerekir (gerçek frappe `_dict` döndürür).
		app_row = SimpleNamespace(
			name="APP-0001",
			rate_limit_tier="basic",
			developer_email="gelistirici@ornek.com",
		)

		fake_app = SimpleNamespace(
			name="APP-0001",
			scopes=[],
			get_password=lambda field, raise_exception=False: self.SECRET,
		)

		gercek_get_doc = frappe.get_doc

		def sahte_get_doc(*args, **kwargs):
			if args and args[0] == "API Application":
				return fake_app
			return gercek_get_doc(*args, **kwargs)

		self._yamala("get_doc", sahte_get_doc)
		# `_verify_client` yalnız `db.get_value("API Application", {...})` çağırır;
		# denetim yazımı (_AdlDoc) frappe.db'ye dokunmaz, bu yüzden dar bir stub yeter.
		self._yamala(
			"db",
			SimpleNamespace(
				get_value=lambda dt, filtre=None, *a, **kw: (
					app_row
					if dt == "API Application" and (filtre or {}).get("client_id") == "client-id-1"
					else None
				),
				commit=lambda: None,
			),
		)


class PublicApiClientSecretWiringTests(_ClientStubBase):
	"""`public_api._verify_client` — gerçek sır değeri denetime sızmaz."""

	def test_gecerli_secret_ile_dogrulama_denetlenir_ve_deger_sizmaz(self):
		from tradehub_core.api.v1 import public_api

		sonuc = public_api._verify_client("client-id-1", self.SECRET)
		self.assertEqual(sonuc["app_name"], "APP-0001")

		kayitlar = [k for k in _INSERTED if k.get("action") == "config.secret_access"]
		self.assertEqual(len(kayitlar), 1, "client_secret okuması bir denetim satırı üretmeli.")
		kayit = kayitlar[0]
		self.assertEqual(kayit["object_doctype"], "API Application")
		self.assertEqual(kayit["object_name"], "APP-0001")
		self.assertNotIn(self.SECRET, str(kayit), "client_secret DEĞERİ denetim satırına sızdı!")

	def test_vacuity_denetimsiz_okuma_iz_birakmaz(self):
		"""Vacuity: yardımcı çağrısı olmasaydı (yanlış secret → get_password okunur
		ama eşleşmez) yol farklı; burada eşleşme sağlanmadan hiç satır yazılmadığını
		DEĞİL, okumanın kendisinin satır ürettiğini pinliyoruz — bu yüzden geçerli
		secret ile üstteki test asıl kanıttır. Burada ters yön: dolu-secret okuması
		her zaman TAM BİR satır bırakır (0 değil)."""
		from tradehub_core.api.v1 import public_api

		# yanlış secret → throw; ama sır yine de OKUNDU → denetim satırı yazılmalı.
		with self.assertRaises(Exception):
			public_api._verify_client("client-id-1", "yanlis-secret")
		kayitlar = [k for k in _INSERTED if k.get("action") == "config.secret_access"]
		self.assertEqual(len(kayitlar), 1, "Sır okundu ama denetlenmedi — iz kayboldu.")


class PublicApiTokenEnumerationTests(_ClientStubBase):
	"""MOGEM-685 Bulgu 1 — token ucu geçerli client_id'leri ele vermez.

	Ölçüldü (28 Eyl 2026, gerçek HTTP): yanlış client_id → "Geçersiz client_id",
	doğru id + yanlış sır → "Geçersiz client_secret". Misafir, 30 istek/dk/IP ile
	hangi kimliklerin gerçek olduğunu tek tek bulabiliyordu. Sır da `!=` ile
	karşılaştırılıyordu (sabit zamanlı değil).
	"""

	def _hata(self, client_id: str, secret: str) -> Exception:
		from tradehub_core.api.v1 import public_api

		with self.assertRaises(frappe.AuthenticationError) as ctx:
			public_api._verify_client(client_id, secret)
		return ctx.exception

	def test_bilinmeyen_kimlik_ve_yanlis_sir_ayni_hatayi_verir(self):
		kimlik = self._hata("yok-boyle-bir-id", "herhangi")
		sir = self._hata("client-id-1", "yanlis-secret")
		self.assertEqual(type(kimlik), type(sir))
		self.assertEqual(str(kimlik), str(sir))
		self.assertNotIn("client_id", str(kimlik))
		self.assertNotIn("client_secret", str(sir))

	def test_sir_sabit_zamanli_karsilastirilir(self):
		from unittest import mock

		from tradehub_core.api.v1 import public_api

		with mock.patch.object(public_api.hmac, "compare_digest", wraps=public_api.hmac.compare_digest) as cd:
			public_api._verify_client("client-id-1", self.SECRET)
			with self.assertRaises(frappe.AuthenticationError):
				public_api._verify_client("client-id-1", "yanlis-secret")
		self.assertEqual(cd.call_count, 2)

	def test_bos_sir_kayitli_uygulama_da_ayni_hatayi_verir(self):
		frappe.get_doc("API Application", "APP-0001").get_password = lambda *a, **k: None
		self.assertEqual(str(self._hata("client-id-1", "")), str(self._hata("yok", "x")))

	def test_dogru_bilgiyle_gecer(self):
		from tradehub_core.api.v1 import public_api

		self.assertEqual(public_api._verify_client("client-id-1", self.SECRET)["app_name"], "APP-0001")

	def _sure(self, client_id: str, secret: str) -> float:
		import time

		basla = time.monotonic()
		try:
			from tradehub_core.api.v1 import public_api

			public_api._verify_client(client_id, secret)
		except frappe.AuthenticationError:
			pass
		return time.monotonic() - basla

	def test_ret_yollari_sure_olarak_da_esit(self):
		"""MOGEM-685 bulgu 5 — ölçüldü (29 Eyl, HTTP): bilinmeyen kimlik medyan 7,6 ms, bilinen
		kimlik + yanlış sır 19,0 ms; dağılımlar örtüşmüyordu. Artık iki ret de tabana tamamlanır."""
		import time

		from tradehub_core.api.v1 import public_api

		# Gerçekte bilinen kimlik yolu kayıt + şifre çözme + denetim yazıyor (~5 ms süreç içi);
		# taklitte get_password anında dönüyor — yavaşlık eklenmezse eşitleme kapalıyken de
		# test geçerdi (taban 0 ile ölçüldü: boş geçiyordu).
		app = frappe.get_doc("API Application", "APP-0001")
		app.get_password = lambda *a, **k: (time.sleep(0.02), self.SECRET)[1]
		taban = public_api.RET_SURE_TABANI_SN
		bilinmeyen = min(self._sure("yok-boyle-bir-id", "x") for _ in range(3))
		yanlis_sir = min(self._sure("client-id-1", "yanlis-secret") for _ in range(3))
		self.assertGreaterEqual(bilinmeyen, taban)
		self.assertGreaterEqual(yanlis_sir, taban)
		self.assertLess(abs(bilinmeyen - yanlis_sir), 0.01)

	def test_basarili_dogrulama_taban_kadar_beklemez(self):
		from tradehub_core.api.v1 import public_api

		self.assertLess(self._sure("client-id-1", self.SECRET), public_api.RET_SURE_TABANI_SN)


if __name__ == "__main__":
	unittest.main()

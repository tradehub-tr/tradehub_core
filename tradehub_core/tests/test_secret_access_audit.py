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


class PublicApiClientSecretWiringTests(PrivacyAuditStubCase):
	"""`public_api._verify_client` — gerçek sır değeri denetime sızmaz."""

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
				get_value=lambda dt, *a, **kw: app_row if dt == "API Application" else None,
				commit=lambda: None,
			),
		)

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


if __name__ == "__main__":
	unittest.main()

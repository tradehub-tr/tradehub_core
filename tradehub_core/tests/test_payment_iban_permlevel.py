"""B-03 (rapor 87) — Payment Transaction IBAN alanları permlevel-1 arkasında.

NEDEN BU DOSYA VAR — ÖLÇÜLMÜŞ BOŞLUK (2026-08-20)
=================================================
`seller_iban` / `seller_bank_name` permlevel-0'daydı: satırı okuyan HERKES
(Buyer if_owner, Marketplace Seller) alan düzeyi hiçbir engel olmadan IBAN'ı
okuyordu. Satır düzeyi izolasyon (`payment_transaction_query_conditions` +
`payment_transaction_has_permission`, test_payment_transaction_isolation.py)
kiracı-DIŞI sızıntıyı zaten kapatıyor; bu dosya ALAN düzeyi katmanlamayı pinler.

Taşımanın ekran KIRMADIĞI ölçüldü (rapor 92 §2):
  - Alıcının havale ekranları (`api/payment.py: get_wire_transfers`,
    `get_wire_transfer_detail`, `get_bank_interactions`) IBAN'ı
    `frappe.db.get_value` / `get_list(ignore_permissions=True)` ile okur —
    permlevel bu yolları ETKİLEMEZ (alıcı havale yapabilmek için IBAN'ı
    görmeye devam eder).
  - Satıcının kendi IBAN'ını gösteren hiçbir ekran Payment Transaction'dan
    okumaz (kaynak: Admin Seller Profile.iban).
  - IBAN yazımları sistem yollarından (`create_payment_transaction`,
    backfill patch'i) `ignore_permissions` ile yapılır — permlevel-1 write
    kısıtı onları da etkilemez.

Bu dosya frappe'yi ÇAĞIRMAZ — saf DocType JSON okuması. CI kapısında
(`scripts/run_authz_tests.sh`) koşar, bench/site GEREKTİRMEZ.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

#: .../tradehub_core (iç paket) / tradehub_core (modül namespace) / doctype
MODULE_ROOT = Path(__file__).resolve().parents[1] / "tradehub_core"

#: Alan düzeyi korumaya alınan finansal PII alanları.
IBAN_FIELDS: frozenset = frozenset({"seller_iban", "seller_bank_name"})
#: permlevel-1'de OKUYABİLEN yönetici rolleri (görüntüleme yetkisi korunur).
ADMIN_ROLES: frozenset = frozenset({"System Manager", "Marketplace Admin"})
#: permlevel-1'de görünmemesi gereken satır-okuru roller.
ROW_READER_ROLES: frozenset = frozenset({"Buyer", "Marketplace Seller"})


def _load() -> dict:
	p = MODULE_ROOT / "doctype" / "payment_transaction" / "payment_transaction.json"
	return json.loads(p.read_text(encoding="utf-8"))


class PaymentIbanPermlevelTests(unittest.TestCase):
	"""Alan düzeyi yetki: IBAN alanları permlevel-1, yönetici okur, satır-okuru okuyamaz."""

	def setUp(self) -> None:
		self.doc = _load()
		self.fields = {f["fieldname"]: f for f in self.doc.get("fields", [])}
		self.perms = self.doc.get("permissions", [])

	def test_iban_alanlari_permlevel_1(self) -> None:
		for fn in sorted(IBAN_FIELDS):
			self.assertIn(fn, self.fields, f"Alan kayboldu: {fn}")
			self.assertGreaterEqual(
				int(self.fields[fn].get("permlevel", 0)), 1,
				f"{fn} permlevel-0'a düştü — satırı okuyan herkes IBAN'ı okur (B-03 regresyonu).",
			)

	def test_yonetici_rolleri_permlevel1_okur(self) -> None:
		# Pozitif kontrol: koruma "kimse görmez" DEĞİL "yalnız yönetici görür".
		okuyan = {
			p.get("role")
			for p in self.perms
			if int(p.get("permlevel", 0)) == 1 and int(p.get("read", 0)) == 1
		}
		for rol in sorted(ADMIN_ROLES):
			self.assertIn(rol, okuyan, f"{rol} permlevel-1'de okuyamıyor — yönetici görünürlüğü düştü.")

	def test_satir_okuru_roller_permlevel1_perm_almaz(self) -> None:
		for p in self.perms:
			if int(p.get("permlevel", 0)) >= 1 and p.get("role") in ROW_READER_ROLES:
				self.fail(
					f"{p.get('role')} permlevel-1 perm'i almış — IBAN alan koruması delindi. "
					"Alıcı ekranları IBAN'ı whitelisted uçlardan alır; permlevel-1 perm'i GEREKMEZ."
				)

	def test_satir_duzeyi_permler_bozulmadi(self) -> None:
		# Taşıma yalnız ALAN katmanı ekledi; permlevel-0 satır perm'leri aynı kalmalı.
		pl0 = {p.get("role"): p for p in self.perms if int(p.get("permlevel", 0)) == 0}
		self.assertEqual(int(pl0["Buyer"].get("if_owner", 0)), 1, "Buyer if_owner kapsamı düştü.")
		self.assertEqual(int(pl0["Buyer"].get("read", 0)), 1)
		self.assertEqual(int(pl0["Marketplace Seller"].get("read", 0)), 1)
		self.assertEqual(int(pl0["System Manager"].get("write", 0)), 1)
		self.assertEqual(int(pl0["Marketplace Admin"].get("write", 0)), 1)

	def test_kontrol_gevsetilince_iddia_gercekten_kirilir(self) -> None:
		# Vacuity: Buyer'a permlevel-1 read verilseydi
		# test_satir_okuru_roller_permlevel1_perm_almaz GERÇEKTEN kırılırdı.
		sahte = list(self.perms) + [{"role": "Buyer", "permlevel": 1, "read": 1}]
		kirik = any(
			int(p.get("permlevel", 0)) >= 1 and p.get("role") in ROW_READER_ROLES
			for p in sahte
		)
		self.assertTrue(kirik, "Vacuity: gevşetilmiş matriste ihlal görünmüyor — test kör.")


if __name__ == "__main__":
	unittest.main()

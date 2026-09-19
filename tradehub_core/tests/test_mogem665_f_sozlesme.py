"""MOGEM-665 · 7. Aşama — sözleşme kilidi: misafire açık uçlar, yetki alanları, kılavuz.

`test_http_api_contracts.py` medya HTTP yüzeyini kilitler; Ürün API'si o belgenin
dışında tutuldu (ayrı ürün, ayrı kılavuz). Bu dosya aynı disiplini Ürün API'sine
uygular: `allow_guest` uç kümesi KODDAN okunur ve donmuş listeyle karşılaştırılır;
kılavuz her ucu ve her hata kodunu anlatmak zorundadır.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
CATALOG = KOK / "tradehub_core" / "api" / "v1" / "catalog.py"
AUTH = KOK / "tradehub_core" / "api" / "v1" / "_catalog_auth.py"
KILAVUZ = KOK / "docs" / "URUN-API-KILAVUZU.md"


def _whitelisted(path: Path) -> dict[str, dict]:
	agac = ast.parse(path.read_text(encoding="utf-8"))
	out = {}
	for node in ast.walk(agac):
		if not isinstance(node, ast.FunctionDef):
			continue
		for dec in node.decorator_list:
			if isinstance(dec, ast.Call) and ast.unparse(dec.func).endswith("frappe.whitelist"):
				kw = {k.arg: ast.literal_eval(k.value) for k in dec.keywords}
				out[node.name] = kw
	return out


class TestMisafirUclari(unittest.TestCase):
	def test_misafire_acik_uc_kumesi_donmus(self):
		uclar = _whitelisted(CATALOG)
		misafir = sorted(n for n, kw in uclar.items() if kw.get("allow_guest"))
		self.assertEqual(
			misafir,
			["changes", "update_stock", "upsert_products"],
			"Ürün API'sinin misafire açık uç kümesi DEĞİŞTİ — bilinçli mi? Kimlik Bearer ile içeride doğrulanır.",
		)
		for n in misafir:
			self.assertIn("POST", uclar[n].get("methods", []), f"{n}: methods kısıtı yok")

	def test_her_misafir_ucu_catalog_context_ile_baslar(self):
		"""allow_guest uçlarında yetki kapısı `catalog_context(<scope>)` olmak zorunda."""
		kaynak = CATALOG.read_text(encoding="utf-8")
		for n, scope in (
			("upsert_products", "catalog:write"),
			("update_stock", "stock:write"),
			("changes", "catalog:read"),
		):
			govde = kaynak.split(f"def {n}(")[1].split("\ndef ")[0]
			self.assertIn(f'catalog_context("{scope}")', govde, f"{n}: {scope} kapısı yok")

	def test_yetki_alanlari_api_scope_secenekleriyle_ayni(self):
		import json

		auth = AUTH.read_text(encoding="utf-8")
		m = re.search(r"CATALOG_SCOPES = \((.*?)\)", auth, re.S)
		scopes = {s.strip().strip('"') for s in m.group(1).split(",") if s.strip()}
		sema = json.loads((KOK / "tradehub_core/tradehub_core/doctype/api_scope/api_scope.json").read_text())
		secenekler = set()
		for f in sema["fields"]:
			if f["fieldname"] == "scope":
				secenekler = set((f.get("options") or "").split("\n"))
		self.assertTrue(scopes <= secenekler, f"API Scope seçeneklerinde eksik: {scopes - secenekler}")


class TestKilavuz(unittest.TestCase):
	def test_kilavuz_her_ucu_ve_her_hata_kodunu_anlatir(self):
		metin = KILAVUZ.read_text(encoding="utf-8")
		for uc in ("public_api.token", "catalog.upsert_products", "catalog.update_stock", "catalog.changes"):
			self.assertIn(uc, metin, f"kılavuzda {uc} yok")
		kaynak = CATALOG.read_text(encoding="utf-8")
		kodlar = set(re.findall(r'_Ret\(\s*"([A-Z_]+)"', kaynak)) | set(
			re.findall(r'"code": "([A-Z_]+)"', kaynak)
		)
		kodlar |= set(re.findall(r'return "([A-Z_]+)"', kaynak)) | set(
			re.findall(r'\("([A-Z_]+)" if', kaynak)
		)
		kodlar |= {"QUOTA_EXCEEDED", "FEATURE_DENIED", "REQUIRED", "VALIDATION", "DUPLICATE", "SYSTEM"}
		eksik = sorted(k for k in kodlar if k not in metin)
		self.assertEqual(eksik, [], f"kılavuzda anlatılmayan kodlar: {eksik}")
		for sinir in ("100", "500", "10", "5 MB", "X-Istoc-Signature", "1 / 5 / 15 / 60 / 360"):
			self.assertIn(sinir, metin, f"kılavuzda sınır/başlık yok: {sinir}")

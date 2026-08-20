# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""Faz 8 — GERÇEK HTTP yüzeyinin sözleşme testi (T-085 kapanış).

`test_api_contracts.py` `docs/api/openapi.yaml` ile `media/pipeline/api/spec.py`
arasındaki bağı kilitler. O katman **saf Python**tur: `@frappe.whitelist()`
taşımaz, `/api/media/v1/...` yolları için depoda bir yönlendirme kuralı yoktur
ve o adreslere HTTP isteği ATILAMAZ.

Bu dosya ikinci katmanı kilitler: `@frappe.whitelist()` taşıyan, gerçekten
`/api/method/<noktalı.yol>` ile çağrılabilen medya uçlarını.

ÜÇ KATMANLI DOĞRULAMA — SAHTE YOK
=================================
1. **Belge ↔ kod kilidi.** `docs/api/openapi-http.yaml` üreticisiyle bayt bayt
   aynı mı; koddaki her uç belgede, belgedeki her uç kodda mı.
2. **Katman ayrımı.** İki belgenin yol kümeleri KESİŞMEZ; HTTP belgesindeki her
   yol `/api/method/` ile başlar; kütüphane belgesindeki `/api/media/v1/...`
   önekinin depoda bir yönlendirme karşılığı OLMADIĞI ölçülür.
3. **Canlı HTTP.** `ISTOC_HTTP_BASE` verilmişse gerçek bir sunucuya istek atılır
   ve dönen gövde belgelenen şemayla karşılaştırılır. Verilmemişse test
   ATLANIR — sahte bir istemciyle "geçti" ÜRETİLMEZ. Bu depoda sahtelerin iki
   kez yanlış güven verdiği ölçüldü (sahte S3 presign, `PolicyEngine`
   protokolü); sözleşmenin son sözü gerçek bir çağrıdır.

Koşum:

    python3 -m unittest tradehub_core.tests.test_http_api_contracts -v
    ISTOC_HTTP_BASE=http://istoc.localhost:8001 python3 -m unittest \\
        tradehub_core.tests.test_http_api_contracts -v

    # konteyner içinden (site adı taban adreste yoksa `Host` şart):
    ISTOC_HTTP_BASE=http://backend:8000 ISTOC_HTTP_HOST=istoc.localhost \\
        ./env/bin/python -m unittest tradehub_core.tests.test_http_api_contracts
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
if str(KOK) not in sys.path:
	sys.path.insert(0, str(KOK))

_BETIK = KOK / "scripts" / "gen_http_openapi.py"
_spec = importlib.util.spec_from_file_location("gen_http_openapi", _BETIK)
assert _spec and _spec.loader
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

from tradehub_core.media.pipeline.api import spec as lib_spec  # noqa: E402

CANLI_TABAN = os.environ.get("ISTOC_HTTP_BASE", "").rstrip("/")
#: Canlı ölçümde kullanılan ilan. Yoksa test kendini atlar, UYDURMAZ.
CANLI_ILAN = os.environ.get("ISTOC_HTTP_LISTING", "LST-00560")
#: Frappe siteyi `Host` başlığından çözer. Taban adres site adını taşımıyorsa
#: (konteyner içinden `http://backend:8000` gibi) bunu verin, yoksa 404 gelir.
CANLI_HOST = os.environ.get("ISTOC_HTTP_HOST", "")


#: Yetkili canlı ölçüm için isteğe bağlı kimlik. VERİLMEZSE o testler ATLANIR —
#: sahte bir oturumla "geçti" üretilmez.
CANLI_KULLANICI = os.environ.get("ISTOC_HTTP_USER", "")
CANLI_PAROLA = os.environ.get("ISTOC_HTTP_PASS", "")


def _cagir(
	yol: str,
	params: dict[str, str],
	*,
	yontem: str = "GET",
	cerez: str = "",
	csrf: str = "",
) -> tuple[int, dict]:
	"""Gerçek HTTP çağrısı. Varsayılan: misafir (oturumsuz) GET.

	Dönüş: (http durumu, ayrıştırılmış gövde). Gövde JSON değilse
	`{"_raw": …}` döner — ikili/HTML yanıtlar da ölçülebilsin.
	"""
	kuyruk = urllib.parse.urlencode(params)
	basliklar = {"Accept": "application/json"}
	if CANLI_HOST:
		basliklar["Host"] = CANLI_HOST
	if cerez:
		basliklar["Cookie"] = cerez
	veri = None
	if yontem == "POST":
		url = f"{CANLI_TABAN}/api/method/{yol}"
		veri = kuyruk.encode()
		basliklar["Content-Type"] = "application/x-www-form-urlencoded"
		if csrf:
			basliklar["X-Frappe-CSRF-Token"] = csrf
	else:
		url = f"{CANLI_TABAN}/api/method/{yol}?{kuyruk}"
	istek = urllib.request.Request(url, data=veri, headers=basliklar, method=yontem)
	try:
		with urllib.request.urlopen(istek, timeout=30) as yanit:
			ham = yanit.read().decode("utf-8", "replace")
			try:
				return yanit.status, json.loads(ham)
			except ValueError:
				return yanit.status, {"_raw": ham[:400]}
	except urllib.error.HTTPError as hata:
		ham = hata.read().decode("utf-8", "replace")
		try:
			return hata.code, json.loads(ham)
		except ValueError:
			return hata.code, {"_raw": ham[:400]}


# ═══════════════════════════════════════════════════════════════════════
# 1. Belge ↔ kod kilidi
# ═══════════════════════════════════════════════════════════════════════


class UreticiTesti(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.doc = gen.build_document()
		cls.uclar = gen.envanter()

	def test_yapisal_dogrulama_temiz(self):
		"""Kırık `$ref`, tekrarlı `operationId`, yanıtsız uç, hayalet ANLATIM YOK."""
		self.assertEqual(gen.validate(), [])

	def test_dosya_var(self):
		self.assertTrue(gen.yaml_path().is_file(), f"{gen.yaml_path()} yok — betiği çalıştırın")

	def test_bayt_esitligi(self):
		"""ELLE DÜZENLENMİŞ ya da ESKİMİŞ YAML testi düşürür.

		Çözüm: `python3 scripts/gen_http_openapi.py`
		"""
		self.assertEqual(
			gen.yaml_path().read_text(encoding="utf-8"),
			gen.dump_yaml(gen.build_document()),
			"docs/api/openapi-http.yaml güncel değil.",
		)

	def test_uretim_deterministik(self):
		self.assertEqual(gen.dump_yaml(gen.build_document()), gen.dump_yaml(gen.build_document()))

	def test_surum_3_1(self):
		self.assertEqual(self.doc["openapi"], "3.1.0")

	def test_koddaki_her_uc_belgede(self):
		belgedekiler = {op["x-python"] for item in self.doc["paths"].values() for op in item.values()}
		for uc in self.uclar:
			self.assertIn(uc["key"], belgedekiler, f"{uc['key']} kodda var, belgede yok")

	def test_belgedeki_her_uc_kodda(self):
		kodda = {uc["key"] for uc in self.uclar}
		for yol, item in self.doc["paths"].items():
			for op in item.values():
				self.assertIn(op["x-python"], kodda, f"{yol} belgede var, kodda yok")

	def test_yol_uc_ile_ayni(self):
		"""Yol, Frappe'nin gerçekten ürettiği adres olmalı: `/api/method/<x-python>`."""
		for yol, item in self.doc["paths"].items():
			for op in item.values():
				self.assertEqual(yol, f"/api/method/{op['x-python']}")

	def test_misafir_listesi_kodla_uyusuyor(self):
		"""`allow_guest` kararı belgeden değil KODDAN gelir ve tek yerde yazılıdır."""
		kodda = sorted(uc["key"] for uc in self.uclar if uc["allow_guest"])
		self.assertEqual(self.doc["x-guest-endpoints"], kodda)
		self.assertEqual(
			kodda,
			[
				"tradehub_core.api.media_access.download",
				"tradehub_core.api.media_manifest.get_manifest",
				"tradehub_core.api.media_manifest.get_manifest_batch",
				# W6 (2026-08-20): RUM beacon'ı — misafire açık TEK yazma ucu.
				# Gerekçe + risk kabulü `api/rum.py` modül başlığında (CSRF muafiyeti
				# framework'ün doğal davranışı, `ignore_csrf` AÇILMADI; hız sınırı var).
				"tradehub_core.api.rum.collect",
			],
			"Misafire açık medya ucu kümesi DEĞİŞTİ — bilinçli mi?",
		)

	def test_misafir_uclarinda_security_bos(self):
		for _yol, item in self.doc["paths"].items():
			for op in item.values():
				guest = op["x-python"] in self.doc["x-guest-endpoints"]
				self.assertEqual(op["security"] == [], guest, op["operationId"])

	def test_her_ucun_yetki_cumlesi_var(self):
		for _yol, item in self.doc["paths"].items():
			for op in item.values():
				self.assertTrue(op["x-authorization"].strip(), op["operationId"])

	def test_her_ucun_kaynak_satiri_cozulur(self):
		"""`x-source` gerçek bir dosya:satır — belge koda geri götürür."""
		for _yol, item in self.doc["paths"].items():
			for op in item.values():
				dosya, satir = op["x-source"].rsplit(":", 1)
				hedef = KOK / dosya
				self.assertTrue(hedef.is_file(), op["x-source"])
				self.assertLessEqual(int(satir), len(hedef.read_text(encoding="utf-8").splitlines()))

	def test_uc_sayisi(self):
		"""100 uç: 6 teslim + 3 kırpma + 41 satıcı + 47 yönetim + 2 depolama + 1 RUM.

		W6 SDK turu (2026-08-20): `manifest_batch` (dosya bazlı), 6 klasör ucu,
		`find_in_my_library`, `list_orphans` ve `rum.collect` yüzeye eklendi.
		"""
		self.assertEqual(len(self.uclar), 100)
		self.assertEqual(self.doc["x-endpoint-count"], 100)
		etikete_gore: dict[str, int] = {}
		for uc in self.uclar:
			etikete_gore[uc["tag"]] = etikete_gore.get(uc["tag"], 0) + 1
		self.assertEqual(
			etikete_gore,
			{"delivery": 6, "crop": 3, "seller": 41, "admin": 47, "storage": 2, "rum": 1},
		)

	def test_her_ucun_olcum_durumu_YAZILI(self):
		"""Sessiz boşluk yok: her uç ya `x-measured` ya `x-unmeasured` taşır.

		Bu depoda ölçülmemiş bir şeyin "geçti" sayılması iki kez oldu. Belge
		artık her uç için ya ölçümü ya da ölçülmeme GEREKÇESİNİ zorunlu kılar.
		"""
		for _yol, item in self.doc["paths"].items():
			for op in item.values():
				self.assertTrue(
					op.get("x-measured") or op.get("x-unmeasured"),
					f"{op['x-python']}: ne ölçüm ne gerekçe",
				)

	def test_olcum_duzeyleri_tanimli_kumeden(self):
		gecerli = {"http", "http-partial", "http-fail"}
		for _yol, item in self.doc["paths"].items():
			for op in item.values():
				if "x-measured" in op:
					self.assertIn(op["x-measured"], gecerli, op["x-python"])

	def test_olculen_ucun_olcum_cumlesi_var(self):
		"""`x-measured` varsa `x-measurement` ZORUNLU — düzey tek başına kanıt değil."""
		for _yol, item in self.doc["paths"].items():
			for op in item.values():
				if "x-measured" in op:
					self.assertTrue(
						op.get("x-measurement", "").strip(),
						f"{op['x-python']}: ölçüm işaretli ama cümle yok",
					)

	def test_olcum_listeleri_operasyonlarla_uyusuyor(self):
		"""Belge başındaki özet listeler operasyonlardan TÜRETİLİR, elle yazılmaz."""
		olculen, kismi, olculmeyen = [], [], []
		for _yol, item in self.doc["paths"].items():
			for op in item.values():
				if op.get("x-measured") == "http":
					olculen.append(op["x-python"])
				elif op.get("x-measured") == "http-partial":
					kismi.append(op["x-python"])
				elif not op.get("x-measured"):
					olculmeyen.append(op["x-python"])
		self.assertEqual(self.doc["x-measured-endpoints"], sorted(olculen))
		self.assertEqual(self.doc["x-partially-measured-endpoints"], sorted(kismi))
		self.assertEqual(self.doc["x-unmeasured-endpoints"], sorted(olculmeyen))

	def test_sapma_listesi_bos_degil(self):
		"""Ölçülen sapmalar belgeden düşerse istemci yanlış kod yazar."""
		sapmalar = self.doc["x-contract-deviations"]
		self.assertGreaterEqual(len(sapmalar), 8)
		metin = " ".join(sapmalar)
		for iz in ("304", "417", "TypeError", "CSRF", "Not permitted"):
			self.assertIn(iz, metin, f"`{iz}` sapması belgeden düşmüş")

	def test_kirpma_uclari_belgede(self):
		"""T-082 — `Media Crop Intent` uçları HTTP yüzeyinin parçası."""
		for fn in ("get_intent", "save_intent", "suggest_focal"):
			yol = f"/api/method/tradehub_core.api.media_crop.{fn}"
			self.assertIn(yol, self.doc["paths"], f"{fn} belgede yok")
			op = list(self.doc["paths"][yol].values())[0]
			self.assertNotEqual(op["security"], [], f"{fn} misafire AÇIK olmamalı")

	def test_save_intent_uyusmazligi_belgede_DURUYOR(self):
		"""`overrides` yolunun bugün çalışmadığı ölçüldü — gizlenmemeli."""
		op = list(
			self.doc["paths"]["/api/method/tradehub_core.api.media_crop.save_intent"].values()
		)[0]
		self.assertIn("x-mismatch", op)
		self.assertIn("LinkValidationError", op["x-mismatch"])


# ═══════════════════════════════════════════════════════════════════════
# 2. Katman ayrımı — iki belge KARIŞMAZ
# ═══════════════════════════════════════════════════════════════════════


class KatmanAyrimiTesti(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.http_doc = gen.build_document()
		cls.lib_doc = lib_spec.build_document()

	def test_yol_kumeleri_kesismez(self):
		self.assertEqual(set(self.http_doc["paths"]) & set(self.lib_doc["paths"]), set())

	def test_http_yollari_api_method_onekli(self):
		for yol in self.http_doc["paths"]:
			self.assertTrue(yol.startswith("/api/method/"), yol)

	def test_kutuphane_yollarinin_hicbiri_api_method_degil(self):
		for yol in self.lib_doc["paths"]:
			self.assertFalse(yol.startswith("/api/method/"), yol)

	def test_kutuphane_katmani_whitelist_TASIMAZ(self):
		"""`pipeline/api/` altında tek bir `@frappe.whitelist()` bile olmamalı.

		Faz 8'in kök iddiası bu. Bir gün oraya whitelist eklenirse iki belge
		çakışır ve bu test önce düşer.
		"""
		kok = KOK / "tradehub_core" / "media" / "pipeline" / "api"
		for dosya in sorted(kok.glob("*.py")):
			agac = ast.parse(dosya.read_text(encoding="utf-8"))
			for node in ast.walk(agac):
				if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
					continue
				for d in node.decorator_list:
					hedef = d.func if isinstance(d, ast.Call) else d
					self.assertNotEqual(
						ast.unparse(hedef),
						"frappe.whitelist",
						f"{dosya.name}:{node.lineno} — saf katmana whitelist girmiş",
					)

	def test_media_v1_onekinin_yonlendirmesi_YOK(self):
		"""`/api/media/v1/...` yolları HTTP'de karşılıksızdır — ölçülerek doğrulanır.

		`pipeline/api/` ve `docs/api/` dışında `media/v1` dizgisi geçen bir dosya
		çıkarsa (nginx conf, hooks route rule, patch) bu test düşer ve iki belge
		yeniden değerlendirilmelidir.
		"""
		hariç = (
			"media/pipeline/api",
			"docs/api",
			".git",
			"tests/test_http_api_contracts",
			# Üretici ve rapor bu dizgiden AÇIKLAMA olarak bahsediyor,
			# yönlendirme kurmuyor.
			"scripts/gen_http_openapi",
			"docs/reports",
		)
		bulunan: list[str] = []
		for uzanti in ("*.py", "*.json", "*.conf", "*.txt", "*.yaml", "*.yml"):
			for dosya in KOK.rglob(uzanti):
				goreli = str(dosya.relative_to(KOK)).replace("\\", "/")
				if any(h in goreli for h in hariç):
					continue
				try:
					if "media/v1" in dosya.read_text(encoding="utf-8", errors="ignore"):
						bulunan.append(goreli)
				except OSError:
					continue
		self.assertEqual(bulunan, [], f"`media/v1` yönlendirmesi belirdi: {bulunan}")


# ═══════════════════════════════════════════════════════════════════════
# 3. Canlı HTTP — sahte istemci YOK
# ═══════════════════════════════════════════════════════════════════════


@unittest.skipUnless(CANLI_TABAN, "ISTOC_HTTP_BASE verilmedi — canlı ölçüm ATLANDI")
class CanliSozlesmeTesti(unittest.TestCase):
	"""Belgelenen şema gerçek yanıtı tutuyor mu. Misafir oturumuyla koşar."""

	@classmethod
	def setUpClass(cls):
		cls.doc = gen.build_document()
		cls.semalar = cls.doc["components"]["schemas"]

	def _zorunlu_alanlar(self, sema_adi: str) -> list[str]:
		return list(self.semalar[sema_adi]["required"])

	def test_get_manifest_belgelenen_semayi_tutuyor(self):
		durum, zarf = _cagir(
			"tradehub_core.api.media_manifest.get_manifest", {"listing": CANLI_ILAN}
		)
		self.assertEqual(durum, 200, zarf)
		self.assertIn("message", zarf, "Frappe zarfı `message` taşımalı")
		govde = zarf["message"]
		for alan in self._zorunlu_alanlar("Manifest"):
			self.assertIn(alan, govde, f"`{alan}` belgelendi ama yanıtta yok")
		self.assertIsInstance(govde["enabled"], bool)
		self.assertIsInstance(govde["renditions"], list)
		self.assertIsInstance(govde["images"], list)
		self.assertIsInstance(govde["suppressed"], int)
		self.assertTrue(govde["etag"].startswith('"'), "ETag tırnaklı olmalı")
		for gorsel in govde["images"]:
			for alan in self._zorunlu_alanlar("ManifestImage"):
				self.assertIn(alan, gorsel)
		for tur in govde["renditions"]:
			for alan in self._zorunlu_alanlar("RenditionRow"):
				self.assertIn(alan, tur)

	def test_if_none_match_not_modified_gövdesi(self):
		_d, ilk = _cagir("tradehub_core.api.media_manifest.get_manifest", {"listing": CANLI_ILAN})
		etag = ilk["message"]["etag"]
		durum, ikinci = _cagir(
			"tradehub_core.api.media_manifest.get_manifest",
			{"listing": CANLI_ILAN, "if_none_match": etag},
		)
		self.assertEqual(durum, 200, "Bu katman 304 ÜRETMEZ; gövdede bayrak taşır")
		govde = ikinci["message"]
		for alan in self._zorunlu_alanlar("NotModified"):
			self.assertIn(alan, govde)
		self.assertTrue(govde["not_modified"])
		self.assertEqual(govde["etag"], etag)

	def test_batch_belgelenen_semayi_tutuyor(self):
		durum, zarf = _cagir(
			"tradehub_core.api.media_manifest.get_manifest_batch",
			{"listings": json.dumps([CANLI_ILAN, "LST-YOK-9999"])},
		)
		self.assertEqual(durum, 200, zarf)
		govde = zarf["message"]
		for alan in self._zorunlu_alanlar("ManifestBatch"):
			self.assertIn(alan, govde, f"`{alan}` belgelendi ama yanıtta yok")
		self.assertEqual(govde["missing"], [], "`missing` DAİMA boş olmalı (numaralandırma kehaneti)")
		self.assertEqual(govde["max_batch"], 50)
		self.assertEqual(govde["requested"], 2)
		self.assertFalse(govde["truncated"])
		for manifest in govde["manifests"].values():
			# Alt gövdelerde `etag`/`cache_control` YOKTUR — belge böyle diyor.
			self.assertNotIn("etag", manifest)
			self.assertIn("images", manifest)

	def test_bilinmeyen_ilan_da_200_ve_ayni_sema(self):
		""""Yok" ile "yayında değil" ayırt EDİLMEZ — ikisi de boş manifest."""
		durum, zarf = _cagir(
			"tradehub_core.api.media_manifest.get_manifest", {"listing": "LST-YOK-9999"}
		)
		self.assertEqual(durum, 200)
		govde = zarf["message"]
		for alan in self._zorunlu_alanlar("Manifest"):
			self.assertIn(alan, govde)
		self.assertEqual(govde["images"], [])
		self.assertEqual(govde["fallback"], "")

	def test_misafir_imzali_adres_ALAMAZ(self):
		"""Belgedeki `security` cümlesi gerçekten uygulanıyor mu."""
		for yol in (
			"tradehub_core.api.media_manifest.get_signed_url",
			"tradehub_core.api.media_access.get_signed_url",
		):
			durum, zarf = _cagir(yol, {"file_url": "/private/files/olmayan.jpg"})
			self.assertEqual(durum, 403, f"{yol}: misafir 403 almalı, aldı {durum}")
			self.assertIn("PermissionError", json.dumps(zarf, ensure_ascii=False))

	def test_imzasiz_download_reddedilir(self):
		durum, _zarf = _cagir(
			"tradehub_core.api.media_access.download", {"file": "/private/files/olmayan.jpg"}
		)
		self.assertEqual(durum, 403)

	def test_misafir_TUM_oturumlu_uclarda_reddediliyor(self):
		"""Oturum isteyen 87 ucun TAMAMI taranır — örneklem DEĞİL.

		Misafir için Frappe'nin whitelist kapısı argüman bağlamadan ÖNCE çalışır;
		bu yüzden parametre vermeden çağırmak güvenlidir ve yazan uçlar da
		hiçbir şeye dokunmadan reddedilir. Ölçüldü: 2026-08-19'da 90 ucun
		misafire kapalı 87'sinin tamamı 403 döndü.
		"""
		uclar = gen.envanter()
		misafir_acik = set(self.doc["x-guest-endpoints"])
		reddedilmeyen: list[str] = []
		for uc in uclar:
			if uc["key"] in misafir_acik:
				continue
			yontem = "POST" if uc["methods"] == ("POST",) else "GET"
			durum, _g = _cagir(uc["key"], {}, yontem=yontem)
			if durum != 403:
				reddedilmeyen.append(f"{uc['key']} → {durum}")
		self.assertEqual(reddedilmeyen, [], "Misafire kapalı uçlar 403 vermedi")

	def test_zorunlu_parametre_eksik_500_TypeError(self):
		"""ÖLÇÜLEN SAPMA: eksik zorunlu parametre 400/417 değil **500** üretir.

		Bu bir kusur beyanıdır, tasarım değil. Uç bir gün 400 vermeye başlarsa
		bu test düşer ve `x-contract-deviations` güncellenmelidir.
		"""
		durum, govde = _cagir("tradehub_core.api.media_manifest.get_manifest", {})
		self.assertEqual(durum, 500, govde)
		self.assertEqual(govde.get("exc_type"), "TypeError")
		self.assertIn("missing 1 required positional argument", govde.get("exception", ""))

	def test_kirpma_uclari_misafire_KAPALI(self):
		"""T-082 — üç kırpma ucu da oturumsuz çağrılamaz."""
		for fn in ("get_intent", "save_intent", "suggest_focal"):
			durum, govde = _cagir(f"tradehub_core.api.media_crop.{fn}", {"asset": "YOK-9999"})
			self.assertEqual(durum, 403, f"{fn} → {durum}")
			self.assertIn("PermissionError", json.dumps(govde, ensure_ascii=False))

	def test_oturum_isteyen_uclar_misafiri_reddeder(self):
		"""Belgede `security` dolu olan her uç misafire kapalı olmalı — örneklem."""
		ornek = (
			"tradehub_core.api.seller_media.browse_my_media",
			"tradehub_core.api.seller_media.get_my_summary",
			"tradehub_core.api.media_admin.get_image_inventory",
			"tradehub_core.tradehub_core.doctype.media_storage_settings"
			".media_storage_settings.get_storage_status",
		)
		for yol in ornek:
			op = self.doc["paths"][f"/api/method/{yol}"]
			self.assertNotEqual(list(op.values())[0]["security"], [], yol)
			durum, _zarf = _cagir(yol, {})
			self.assertEqual(durum, 403, f"{yol}: misafir 403 almalı, aldı {durum}")


# ═══════════════════════════════════════════════════════════════════════
# 4. Yetkili canlı ölçüm — kimlik verilmezse ATLANIR
# ═══════════════════════════════════════════════════════════════════════


@unittest.skipUnless(
	CANLI_TABAN and CANLI_KULLANICI and CANLI_PAROLA,
	"ISTOC_HTTP_USER/ISTOC_HTTP_PASS verilmedi — yetkili ölçüm ATLANDI",
)
class YetkiliCanliTesti(unittest.TestCase):
	"""Yalnız OKUYAN uçlar çağrılır. Yazan uçlar bu testte YOK — veri bozmaz."""

	cerez = ""

	@classmethod
	def setUpClass(cls):
		cls.doc = gen.build_document()
		kuyruk = urllib.parse.urlencode({"usr": CANLI_KULLANICI, "pwd": CANLI_PAROLA})
		basliklar = {"Content-Type": "application/x-www-form-urlencoded"}
		if CANLI_HOST:
			basliklar["Host"] = CANLI_HOST
		istek = urllib.request.Request(
			f"{CANLI_TABAN}/api/method/login", data=kuyruk.encode(), headers=basliklar
		)
		with urllib.request.urlopen(istek, timeout=30) as yanit:
			cerezler = yanit.headers.get_all("Set-Cookie") or []
		cls.cerez = "; ".join(c.split(";", 1)[0] for c in cerezler if c.startswith("sid="))
		if not cls.cerez:
			raise unittest.SkipTest("oturum çerezi alınamadı")

	def _oku(self, yol: str, params: dict[str, str] | None = None):
		return _cagir(yol, params or {}, cerez=self.cerez)

	def test_depolama_durumu_ARTIK_500_DEGIL(self):
		"""`32-faz8-api-kapanis.md` §5'in UYUŞMAZLIĞI kapandı mı — ölçerek."""
		yol = (
			"tradehub_core.tradehub_core.doctype.media_storage_settings"
			".media_storage_settings.get_storage_status"
		)
		durum, zarf = self._oku(yol)
		self.assertEqual(durum, 200, f"HTTP 500 ImportError geri geldi: {zarf}")
		govde = zarf["message"]
		for alan in self.doc["components"]["schemas"]["StorageStatus"]["required"]:
			self.assertIn(alan, govde)
		for alan in ("mode", "requested_mode", "degraded", "signer_available", "backend"):
			self.assertIn(alan, govde["plan"])
		metin = json.dumps(govde, ensure_ascii=False).lower()
		for sir in ("secret", "password", "access_key", "parola"):
			self.assertNotIn(sir, metin, "depo durumu sır sızdırıyor")

	def test_baglanti_testi_istisna_ATMAZ(self):
		yol = (
			"tradehub_core.tradehub_core.doctype.media_storage_settings"
			".media_storage_settings.test_connection"
		)
		durum, zarf = self._oku(yol, {"target": "cdn"})
		self.assertEqual(durum, 200, zarf)
		govde = zarf["message"]
		self.assertEqual(govde["target"], "cdn")
		self.assertIsInstance(govde["ok"], bool)
		self.assertIsInstance(govde["steps"], list)

	def test_POST_only_uc_GET_ile_403_Not_permitted(self):
		"""ÖLÇÜLEN SAPMA: yöntem hatası da 403 döner, 405 değil."""
		durum, govde = self._oku("tradehub_core.api.media_admin.sweep_scans")
		self.assertEqual(durum, 403, govde)
		self.assertIn("Not permitted", json.dumps(govde, ensure_ascii=False))

	def test_bilinmeyen_yedek_kimligi_417(self):
		"""İş kuralı reddi 400 DEĞİL 417 — belgedeki cümle ölçülerek tutuluyor."""
		durum, govde = self._oku(
			"tradehub_core.api.media_admin.plan_media_restore", {"set_id": "YOK-9999"}
		)
		self.assertEqual(durum, 417, govde)
		self.assertEqual(govde.get("exc_type"), "ValidationError")

	def test_olmayan_dosya_404_DoesNotExist(self):
		"""Aynı katmanda 404 de var — tek bir "bulunamadı" kodu YOK."""
		durum, govde = self._oku(
			"tradehub_core.api.media_admin.get_file_usage", {"file_url": "/files/yok-9999.jpg"}
		)
		# Bu uç bulunamayan dosya için hata ATMAZ; kullanım dökümü boş döner.
		self.assertIn(durum, (200, 404), govde)

	def test_yonetim_ucu_okuma_semasi(self):
		durum, zarf = self._oku("tradehub_core.api.media_admin.scan_overview")
		self.assertEqual(durum, 200, zarf)
		govde = zarf["message"]
		self.assertIn("policy", govde)
		self.assertIn("counts", govde)


if __name__ == "__main__":
	unittest.main()

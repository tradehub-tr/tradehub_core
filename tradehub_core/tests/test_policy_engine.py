"""T-033 — PolicyEngine testleri.

Üç şeyi doğrular:

1. **Politikalar VERİ olarak yükleniyor mu**: 9 slot politikası kayıt defterine
   girer, anahtarlar tekil, motorda hiçbir slota özel dal yok. Kanıt niteliğinde
   bir test var: `test_yeni_slot_kod_degismeden_calisir` çalışma anında geçici
   bir dizine ONUNCU bir politika yazar ve motorun onu kod değişmeden
   değerlendirdiğini gösterir.

2. **Kararlar golden fixture korpusuyla uyuşuyor mu**: `tradehub_core/tests/fixtures/media/
   manifest.json` içindeki 51 fixture'ın `expected_action` alanı ile motorun
   `allow` kararı karşılaştırılır. `reject` → allow=False, `process`/
   `passthrough` → allow=True.

3. **Sınır vakaları**: `bound_short999.jpg` REDDEDİLİR, `bound_short1000.jpg`
   GEÇER. T-033'ün kabul ölçütü budur.

Çalıştırma (bench/site GEREKMEZ — bu ağaçta `import frappe` yok):

    python3 -m unittest discover -s tests -v
    python3 -m unittest tests.test_policy_engine -v
"""

from __future__ import annotations

import ast
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.core.errors import (  # noqa: E402
	ACTION_REJECT,
	ACTION_WARN,
	BLOCKING_ACTIONS,
	highest_action,
)
from tradehub_core.media.pipeline.core.probe import (  # noqa: E402
	MediaProbe,
	probe_file,
	probe_video_from_ffprobe,
)
from tradehub_core.media.pipeline.policy.engine import (  # noqa: E402
	PolicyEngine,
	PolicyNotFound,
	PolicyRegistry,
	parse_ratio,
)

FIXTURE_DIR = ROOT / "tradehub_core" / "tests" / "fixtures" / "media"
MANIFEST = FIXTURE_DIR / "manifest.json"
IMAGES = FIXTURE_DIR / "images"
SLOT_DIR = ROOT / "tradehub_core" / "media" / "pipeline" / "policy" / "slots"
ENGINE_SRC = ROOT / "tradehub_core" / "media" / "pipeline" / "policy" / "engine.py"
UPLOAD_POLICY_SRC = ROOT / "tradehub_core" / "media" / "upload_policy.py"


def _manifest() -> dict:
	with open(MANIFEST, encoding="utf-8") as fh:
		return json.load(fh)


def load_module_constants(path: Path, names) -> dict:
	"""Modülü IMPORT ETMEDEN sabitlerini oku.

	`tradehub_core/media/*.py` modülleri `import frappe` içeriyor; bu ağaçta
	frappe yok. Ayna tablolarının kaynakla aynı kaldığını doğrulamanın tek
	frappe'siz yolu kaynağı `ast` ile ayrıştırıp yalnız güvenli atamaları
	çalıştırmaktır.
	"""

	def guvenli(node) -> bool:
		if isinstance(node, (ast.Constant, ast.Name)):
			return True
		if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
			return all(guvenli(e) for e in node.elts)
		if isinstance(node, ast.Dict):
			return all(guvenli(k) for k in node.keys if k) and all(
				guvenli(v) for v in node.values
			)
		if isinstance(node, ast.Call):
			return (
				isinstance(node.func, ast.Name)
				and node.func.id in {"frozenset", "set", "tuple", "list", "dict"}
				and all(guvenli(a) for a in node.args)
			)
		if isinstance(node, ast.Starred):
			return guvenli(node.value)
		return False

	agac = ast.parse(path.read_text(encoding="utf-8"))
	ortam: dict = {"frozenset": frozenset, "set": set, "tuple": tuple, "list": list, "dict": dict}
	tanimli: set = set(ortam)

	def serbest_adlar(node) -> set:
		return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}

	for node in agac.body:
		if isinstance(node, ast.Assign):
			hedefler, deger = node.targets, node.value
		elif isinstance(node, ast.AnnAssign) and node.value is not None:
			hedefler, deger = [node.target], node.value
		else:
			continue
		if not guvenli(deger):
			continue
		# Değeri, henüz tanımlanmamış bir ada dayanıyorsa ATLA. `ALL_CODES`
		# böyle: içindeki adlar `Kod(...)` çağrısıyla üretiliyor ve o çağrı
		# güvenli listede olmadığı için atlanmış oluyor.
		if serbest_adlar(deger) - tanimli:
			continue
		if not all(isinstance(t, ast.Name) for t in hedefler):
			continue
		tekil = ast.Module(body=[ast.Assign(targets=hedefler, value=deger)], type_ignores=[])
		ast.fix_missing_locations(tekil)
		exec(compile(tekil, str(path), "exec"), ortam)  # noqa: S102
		tanimli.update(t.id for t in hedefler)
	return {ad: ortam[ad] for ad in names if ad in ortam}


class PolitikaKaydiTesti(unittest.TestCase):
	"""Politikalar veri olarak yükleniyor mu."""

	def setUp(self):
		self.registry = PolicyRegistry()
		self.engine = PolicyEngine(self.registry)

	def test_dokuz_slot_politikasi_yuklendi(self):
		self.assertEqual(len(self.registry), 9)
		self.assertEqual(len(list(SLOT_DIR.glob("*.json"))), 9)

	def test_anahtar_dosya_adindan_degil_icerikten_gelir(self):
		for slot in self.registry.keys():
			data = self.registry.get(slot)
			self.assertEqual(data["slot_key"], slot)
			# Dosya adı ile anahtar arasındaki bağ SÖZLEŞME DEĞİL: dosya
			# yeniden adlandırılabilir. Yine de bugün tutarlı olduğunu
			# gösteriyoruz — tutarsızlık bir insan hatası işareti olurdu.
			beklenen = slot.replace(".", "-").replace("_", "-") + ".json"
			self.assertEqual(self.registry.source_of(slot).name, beklenen)

	def test_bilinmeyen_slot_acik_hata_verir(self):
		with self.assertRaises(PolicyNotFound) as ctx:
			self.registry.get("yok.boyle.bir.slot")
		self.assertIn("product.image", str(ctx.exception))

	def test_her_politikanin_on_violation_ve_messages_blogu_var(self):
		for slot in self.registry.keys():
			data = self.registry.get(slot)
			with self.subTest(slot=slot):
				self.assertIn("on_violation", data)
				self.assertIn("default", data["on_violation"])
				self.assertIn("tr", (data.get("messages") or {}))

	def test_motor_kaynaginda_slot_ozel_dal_yok(self):
		"""Motor hiçbir slot anahtarını kendi içinde bilmiyor.

		Bu, "yeni slot için KOD DEĞİŞMEZ" sözünün statik kanıtı. Motor
		kaynağında `product.image` gibi bir slot anahtarı geçerse, o slota özel
		bir dal yazılmış demektir.
		"""
		kaynak = ENGINE_SRC.read_text(encoding="utf-8")
		# Docstring'lerde slot adı geçebilir; yalnız KOD satırlarına bakıyoruz.
		agac = ast.parse(kaynak)
		metinler = [
			n.value
			for n in ast.walk(agac)
			if isinstance(n, ast.Constant) and isinstance(n.value, str)
		]
		docstringler = set()
		for n in ast.walk(agac):
			if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)):
				d = ast.get_docstring(n, clean=False)
				if d:
					docstringler.add(d)
		for slot in self.registry.keys():
			for metin in metinler:
				if metin in docstringler:
					continue
				with self.subTest(slot=slot):
					self.assertNotEqual(metin, slot, f"motorda slota özel sabit: {slot}")

	def test_yeni_slot_kod_degismeden_calisir(self):
		"""ONUNCU politika: dosya eklendi, kod eklenmedi."""
		with tempfile.TemporaryDirectory() as tmp:
			hedef = Path(tmp)
			for p in SLOT_DIR.glob("*.json"):
				shutil.copy(p, hedef / p.name)
			yeni = {
				"schema_version": "1.0.0",
				"status": "draft",
				"slot_key": "test.sticker",
				"title": "Test etiketi",
				"roles": ["seller"],
				"accept": {
					"mime": ["image/png"],
					"extensions": [".png"],
					"max_bytes": 200_000,
					"max_megapixels_hard": 4,
					"allow_animated": False,
				},
				"require": {
					"min_short_edge": 300,
					"allowed_ratios": ["1:1"],
					"ratio_tolerance": 0.02,
				},
				"master": {"max_long_edge": 512, "format": "webp", "dpi_out": 72},
				"on_violation": {"default": "reject", "error_code_prefix": "sticker"},
				"messages": {"tr": {"short_edge_too_small": "Etiket en az 300 piksel olmalı."}},
			}
			(hedef / "test-sticker.json").write_text(
				json.dumps(yeni, ensure_ascii=False), encoding="utf-8"
			)
			motor = PolicyEngine(PolicyRegistry(hedef))
			self.assertEqual(len(motor.registry), 10)

			kucuk = MediaProbe(
				filename="x.png", extension=".png", byte_size=1000, kind="image",
				detected="png", mime="image/png", fmt="PNG", width=200, height=200,
				readable=True, loadable=True, animated=False,
				extension_matches_content=True,
			)
			karar = motor.evaluate("test.sticker", kucuk, role="seller")
			self.assertFalse(karar.allow)
			self.assertEqual(karar.violations[0].code, "sticker_short_edge_too_small")
			self.assertEqual(karar.violations[0].message["tr"], "Etiket en az 300 piksel olmalı.")

			buyuk = MediaProbe(
				filename="x.png", extension=".png", byte_size=1000, kind="image",
				detected="png", mime="image/png", fmt="PNG", width=400, height=400,
				readable=True, loadable=True, animated=False,
				extension_matches_content=True,
			)
			self.assertTrue(motor.evaluate("test.sticker", buyuk, role="seller").allow)


class SinirVakalariTesti(unittest.TestCase):
	"""T-033 kabul ölçütü: 999 kalır, 1000 geçer."""

	def setUp(self):
		self.engine = PolicyEngine()

	def test_bound_short999_reddedilir(self):
		karar = self.engine.evaluate(
			"product.image", probe_file(IMAGES / "bound_short999.jpg"), role="seller"
		)
		self.assertFalse(karar.allow)
		self.assertIn("product_image_short_edge_too_small", karar.codes)
		ihlal = next(v for v in karar.violations if v.rule == "short_edge_too_small")
		self.assertEqual(ihlal.action, ACTION_REJECT)
		self.assertEqual(ihlal.observed, 999)
		self.assertEqual(ihlal.expected, 1000)

	def test_bound_short1000_gecer(self):
		karar = self.engine.evaluate(
			"product.image", probe_file(IMAGES / "bound_short1000.jpg"), role="seller"
		)
		self.assertTrue(karar.allow)
		self.assertNotIn("product_image_short_edge_too_small", karar.codes)
		# Geçse de sessiz değil: 1000 piksel master tabanının (2000) altında.
		self.assertIn("product_image_master_under_spec", karar.codes)
		self.assertEqual(
			next(v for v in karar.violations if v.rule == "master_under_spec").action,
			ACTION_WARN,
		)

	def test_tek_piksel_fark_kararı_degistiriyor(self):
		"""İki fixture arasındaki TEK fark kısa kenar; karar ters dönüyor."""
		a = probe_file(IMAGES / "bound_short999.jpg")
		b = probe_file(IMAGES / "bound_short1000.jpg")
		self.assertEqual(b.short_edge - a.short_edge, 1)
		self.assertNotEqual(
			self.engine.evaluate("product.image", a, role="seller").allow,
			self.engine.evaluate("product.image", b, role="seller").allow,
		)


class FixtureKorpusuTesti(unittest.TestCase):
	"""51 golden fixture ile manifest beyanının karşılaştırılması."""

	@classmethod
	def setUpClass(cls):
		cls.engine = PolicyEngine()
		cls.manifest = _manifest()

	def _probe_for(self, kayit: dict):
		yol = ROOT / kayit["file"]
		olculen = kayit.get("olculen") or {}
		if kayit.get("slot", "").endswith(".video"):
			# Video künyesi ffprobe'dan gelir; manifest'teki ÖLÇÜLMÜŞ kopya
			# kullanılıyor — ffprobe ikinci kez çağrılmıyor.
			return probe_video_from_ffprobe(olculen, filename=yol.name)
		return probe_file(yol)

	def test_tum_fixtureler_manifest_beyaniyla_uyusuyor(self):
		uyumsuz = []
		for kayit in self.manifest["fixtures"]:
			yol = ROOT / kayit["file"]
			self.assertTrue(yol.exists(), f"fixture yok: {yol}")
			slot = kayit["slot"]
			roller = self.engine.registry.get(slot).get("roles") or ["admin"]
			karar = self.engine.evaluate(slot, self._probe_for(kayit), role=roller[0])
			beklenen_allow = kayit["expected_action"] != "reject"
			if karar.allow != beklenen_allow:
				uyumsuz.append(
					f"{yol.name} [{slot}] beklenen={kayit['expected_action']} "
					f"allow={karar.allow} kodlar={karar.codes}"
				)
		self.assertEqual(uyumsuz, [], "manifest ile motor kararı ayrıştı")

	def test_fixture_sayisi_manifestteki_ozetle_ayni(self):
		self.assertEqual(len(self.manifest["fixtures"]), self.manifest["ozet"]["fixture_sayisi"])
		self.assertEqual(len(self.manifest["fixtures"]), 51)

	def test_reddedilen_her_fixture_engelleyici_ihlal_tasiyor(self):
		for kayit in self.manifest["fixtures"]:
			if kayit["expected_action"] != "reject":
				continue
			slot = kayit["slot"]
			roller = self.engine.registry.get(slot).get("roles") or ["admin"]
			karar = self.engine.evaluate(slot, self._probe_for(kayit), role=roller[0])
			with self.subTest(fixture=Path(kayit["file"]).name):
				self.assertTrue(karar.blocking())
				self.assertIn(karar.action, BLOCKING_ACTIONS)


class IhlalSozlesmesiTesti(unittest.TestCase):
	"""Her ihlal: makine kodu + tr/en mesaj + düzeltme ipucu."""

	@classmethod
	def setUpClass(cls):
		cls.engine = PolicyEngine()
		cls.manifest = _manifest()

	def test_uretilen_her_ihlal_tam_sozlesmeyi_tasiyor(self):
		gorulen = 0
		for kayit in self.manifest["fixtures"]:
			slot = kayit["slot"]
			roller = self.engine.registry.get(slot).get("roles") or ["admin"]
			yol = ROOT / kayit["file"]
			probe = (
				probe_video_from_ffprobe(kayit.get("olculen") or {}, filename=yol.name)
				if slot.endswith(".video")
				else probe_file(yol)
			)
			for ihlal in self.engine.evaluate(slot, probe, role=roller[0]).violations:
				gorulen += 1
				with self.subTest(fixture=yol.name, kod=ihlal.code):
					self.assertTrue(ihlal.code)
					self.assertTrue(ihlal.rule)
					self.assertTrue(ihlal.block)
					self.assertIn(ihlal.action, ("warn", "auto_fix", "review", "reject"))
					self.assertTrue(ihlal.message.get("tr"))
					self.assertTrue(ihlal.message.get("en"))
					self.assertNotEqual(ihlal.message["tr"], ihlal.message["en"])
					self.assertTrue(ihlal.hint.get("tr"))
					self.assertTrue(ihlal.hint.get("en"))
					self.assertFalse(ihlal.retryable, "politika ihlali tekrar denenmez")
		self.assertGreater(gorulen, 20, "korpus hiç ihlal üretmediyse test anlamsız")

	def test_kod_slot_on_ekiyle_baslar(self):
		karar = self.engine.evaluate(
			"seller.logo", probe_file(IMAGES / "logo_short200.png"), role="seller"
		)
		self.assertFalse(karar.allow)
		for ihlal in karar.violations:
			self.assertTrue(ihlal.code.startswith("logo_"), ihlal.code)

	def test_mesaj_metni_politikadan_gelir_katalogdan_degil(self):
		"""TR metni slot politikasında varsa O kullanılır."""
		karar = self.engine.evaluate(
			"product.image", probe_file(IMAGES / "bound_short999.jpg"), role="seller"
		)
		ihlal = next(v for v in karar.violations if v.rule == "short_edge_too_small")
		politika_metni = self.engine.registry.get("product.image")["messages"]["tr"][
			"short_edge_too_small"
		]
		self.assertEqual(
			ihlal.message["tr"],
			politika_metni.format(kisa_kenar=999, gerekli_kisa_kenar=1000),
		)
		self.assertIn("999", ihlal.message["tr"])
		self.assertIn("1000", ihlal.message["tr"])
		self.assertNotIn("{", ihlal.message["tr"])

	def test_olculemeyen_kural_gecti_sayilmaz(self):
		"""Piksel analizi isteyen kurallar `skipped` listesine yazılır."""
		karar = self.engine.evaluate(
			"product.image", probe_file(IMAGES / "content_blank_white.png"), role="seller"
		)
		atlanan = {s.rule for s in karar.skipped}
		self.assertIn("entropy_bits", atlanan)
		self.assertIn("blur_laplacian_variance", atlanan)
		for s in karar.skipped:
			self.assertEqual(s.reason, "not_measurable")
		self.assertNotIn("product_image_entropy_bits", karar.codes)


class KuralDavranisiTesti(unittest.TestCase):
	"""Tek tek kuralların doğru şeye baktığı."""

	def setUp(self):
		self.engine = PolicyEngine()

	def test_exif_rotasyonu_orana_uygulanir(self):
		"""1200×1600 depolanmış, orientation=6 → görünen 1600×1200 = 4:3 → ret."""
		probe = probe_file(IMAGES / "exif_orientation6.jpg")
		self.assertEqual((probe.width, probe.height), (1200, 1600))
		self.assertEqual(probe.exif_orientation, 6)
		self.assertEqual(probe.display_size, (1600, 1200))
		karar = self.engine.evaluate("product.image", probe, role="seller")
		self.assertFalse(karar.allow)
		self.assertIn("product_image_ratio_not_allowed", karar.codes)

	def test_megapiksel_karari_dosya_boyutundan_bagimsiz(self):
		"""97 KB'lık 100 MP dosya reddedilir (decompression bomb)."""
		probe = probe_file(ROOT / "tradehub_core" / "tests" / "fixtures" / "malicious" / "bomb_100mp.png")
		self.assertLess(probe.byte_size, 200_000)
		self.assertAlmostEqual(probe.megapixels, 100.0, places=1)
		karar = self.engine.evaluate("product.image", probe, role="seller")
		self.assertIn("product_image_too_many_pixels", karar.codes)

	def test_uzanti_icerik_uyusmazligi_reddedilir(self):
		"""Geçerli PNG ama adı .jpg — 'nasılsa açılıyor' diye geçirilmez."""
		probe = probe_file(ROOT / "tradehub_core" / "tests" / "fixtures" / "malicious" / "polyglot_png_as.jpg")
		self.assertTrue(probe.readable)
		self.assertFalse(probe.extension_matches_content)
		karar = self.engine.evaluate("product.image", probe, role="seller")
		self.assertIn("product_image_content_type_mismatch", karar.codes)

	def test_gorselin_sonuna_eklenmis_yuk_avatarda_da_yakalanir(self):
		"""320×320 avatar geometriyi geçer; savunma kuyruk taramasından gelir."""
		probe = probe_file(ROOT / "tradehub_core" / "tests" / "fixtures" / "malicious" / "jpeg_with_html_tail.jpg")
		self.assertTrue(probe.appended_payload)
		karar = self.engine.evaluate("user.avatar", probe, role="buyer")
		self.assertFalse(karar.allow)
		self.assertIn("upload_appended_payload", karar.codes)

	def test_kosullu_svg_kapali_oldugu_icin_reddedilir(self):
		probe = probe_file(ROOT / "tradehub_core" / "tests" / "fixtures" / "malicious" / "script_payload.svg")
		karar = self.engine.evaluate("seller.logo", probe, role="seller")
		self.assertFalse(karar.allow)
		self.assertIn("logo_extension_conditional_closed", karar.codes)
		# Politikada svg_policy.enabled açılırsa bu kural düşer — VERİ kararı.
		self.assertFalse(
			self.engine.registry.get("seller.logo")["logo"]["svg_policy"]["enabled"]
		)

	def test_rol_disinda_kalan_kullanici_reddedilir(self):
		probe = probe_file(IMAGES / "ok_product_1x1_2400.jpg")
		self.assertTrue(self.engine.evaluate("product.image", probe, role="seller").allow)
		karar = self.engine.evaluate("product.image", probe, role="buyer")
		self.assertFalse(karar.allow)
		self.assertIn("product_image_role_not_allowed", karar.codes)

	def test_video_oran_ihlali_reddetmez_uyarir(self):
		"""product.video `on_violation.require = warn` — 9:16 kabul edilir."""
		manifest = _manifest()
		kayit = next(
			k for k in manifest["fixtures"] if k["file"].endswith("video_vertical_9x16.mp4")
		)
		probe = probe_video_from_ffprobe(kayit["olculen"], filename="video_vertical_9x16.mp4")
		karar = self.engine.evaluate("product.video", probe, role="seller")
		self.assertTrue(karar.allow)
		self.assertIn("upload_ratio_not_allowed", karar.codes)
		self.assertEqual(
			next(v for v in karar.violations if v.rule == "ratio_not_allowed").action, "warn"
		)

	def test_yuksek_bitrate_reddetmez_auto_fix_isaretler(self):
		manifest = _manifest()
		kayit = next(
			k for k in manifest["fixtures"] if k["file"].endswith("video_bloated_720p_8m.mp4")
		)
		probe = probe_video_from_ffprobe(kayit["olculen"], filename="video_bloated_720p_8m.mp4")
		karar = self.engine.evaluate("product.video", probe, role="seller")
		self.assertTrue(karar.allow)
		self.assertIn("upload_bitrate_bps", karar.codes)
		self.assertEqual(karar.action, "auto_fix")
		self.assertEqual(
			next(v for v in karar.violations if v.rule == "bitrate_bps").action, "auto_fix"
		)

	def test_adet_bilgisi_yoksa_kural_atlanir_uydurulmaz(self):
		probe = probe_file(IMAGES / "ok_product_1x1_2400.jpg")
		karar = self.engine.evaluate("product.image", probe, role="seller")
		self.assertIn("count", {s.rule for s in karar.skipped})
		karar2 = self.engine.evaluate(
			"product.image",
			probe_file(IMAGES / "ok_product_1x1_2400.jpg", existing_count=13),
			role="seller",
		)
		self.assertIn("product_image_too_many_items", karar2.codes)

	def test_en_yuksek_aksiyon_kazanir(self):
		self.assertEqual(highest_action(["warn", "auto_fix"]), "auto_fix")
		self.assertEqual(highest_action(["warn", "reject", "auto_fix"]), "reject")
		self.assertEqual(highest_action([]), "pass")

	def test_manual_review_ile_review_ayni_yukseklikte(self):
		"""Slot politikaları `review`, content_rules.json `manual_review` diyor.

		İkisini ayrı saymak, moderasyona gitmesi gereken dosyanın sessizce
		geçmesine yol açardı: bilinmeyen aksiyon `pass` seviyesine düşer.
		"""
		from tradehub_core.media.pipeline.core.errors import (
			ACTION_MANUAL_REVIEW,
			ACTION_RANK,
			ACTION_REVIEW,
			BLOCKING_ACTIONS,
		)

		self.assertEqual(ACTION_RANK[ACTION_MANUAL_REVIEW], ACTION_RANK[ACTION_REVIEW])
		self.assertIn(ACTION_MANUAL_REVIEW, BLOCKING_ACTIONS)
		self.assertEqual(highest_action(["warn", ACTION_MANUAL_REVIEW]), ACTION_MANUAL_REVIEW)

	def test_ignore_aksiyonu_kullaniciya_gosterilmez(self):
		"""`ignore` ölçüldü-umursanmadı demektir; `skipped` ile karışmaz."""
		from tradehub_core.media.pipeline.core.errors import ACTION_IGNORE, SILENT_ACTIONS

		self.assertIn(ACTION_IGNORE, SILENT_ACTIONS)
		# Veri gerçekten bu değeri kullanıyor — sabit hayali değil.
		banner = self.engine.registry.get("category.banner")
		ignore_kurallari = [
			r["rule"] for r in banner["content_rules"] if r.get("action") == ACTION_IGNORE
		]
		self.assertTrue(ignore_kurallari, "category.banner'da ignore aksiyonlu kural bekleniyordu")
		karar = self.engine.evaluate(
			"category.banner", probe_file(IMAGES / "ok_banner_2x1.jpg"), role="admin"
		)
		for ihlal in karar.violations:
			self.assertNotEqual(ihlal.action, ACTION_IGNORE)

	def test_oran_ayristirma(self):
		self.assertAlmostEqual(parse_ratio("4:5"), 0.8)
		self.assertAlmostEqual(parse_ratio("16:9"), 16 / 9)
		self.assertEqual(parse_ratio("bozuk"), 0.0)


class NormalizeHedefTesti(unittest.TestCase):
	"""`normalized_targets` — DPI kuralı ve büyütme yasağı."""

	def setUp(self):
		self.engine = PolicyEngine()

	def test_dpi_dususu_pikseli_dusurmez(self):
		"""3000×3000@300dpi → 2400×2400@72dpi. 720×720 YASAK."""
		probe = probe_file(IMAGES / "dpi_3000x3000_300dpi.tif")
		self.assertEqual(probe.dpi, (300, 300))
		karar = self.engine.evaluate("product.image", probe, role="seller")
		self.assertTrue(karar.allow)
		master = karar.normalized_targets["master"]
		self.assertEqual((master["width"], master["height"]), (2400, 2400))
		self.assertEqual(master["dpi_out"], 72)
		self.assertNotEqual(master["width"], 720)

	def test_master_upscale_yapmaz(self):
		probe = probe_file(IMAGES / "bound_short1000.jpg")
		master = self.engine.evaluate(
			"product.image", probe, role="seller"
		).normalized_targets["master"]
		self.assertEqual((master["width"], master["height"]), (1000, 1000))
		self.assertFalse(master["resize_needed"])
		self.assertFalse(master["allow_upscale"])

	def test_masterdan_buyuk_turev_upscale_isaretlenir(self):
		probe = probe_file(IMAGES / "bound_short1000.jpg")
		turevler = self.engine.evaluate(
			"product.image", probe, role="seller"
		).normalized_targets["derivatives"]
		self.assertTrue(turevler)
		buyukler = [t for t in turevler if t["upscale"]]
		self.assertTrue(buyukler, "1000 px masterda 1280/1920 türevleri işaretlenmeli")
		for t in buyukler:
			self.assertGreater(t["width"], 1000)

	def test_logo_masteri_kare_paddir(self):
		probe = probe_file(IMAGES / "logo_alpha_512.png")
		karar = self.engine.evaluate("seller.logo", probe, role="seller")
		self.assertTrue(karar.allow)
		master = karar.normalized_targets["master"]
		self.assertEqual(master["fit"], "pad")
		self.assertEqual(master["width"], master["height"])
		self.assertEqual(master["pad_color"], "transparent")
		self.assertEqual(master["encoding"], "lossless")

	def test_megapiksel_tavani_uzun_kenardan_once_baglar(self):
		"""24:5 kapak: uzun kenar tavanı 2560, MP tavanı 1,64 — küçük olan bağlar."""
		probe = probe_file(IMAGES / "ok_cover_24x5.jpg")
		karar = self.engine.evaluate("company.cover_image", probe, role="seller")
		master = karar.normalized_targets["master"]
		self.assertLessEqual(master["width"] * master["height"], 1.64 * 1_000_000 + 1)
		self.assertLessEqual(max(master["width"], master["height"]), 2560)

	def test_reddedilen_dosya_icin_hedef_uretilmez(self):
		karar = self.engine.evaluate(
			"product.image", probe_file(IMAGES / "bound_short999.jpg"), role="seller"
		)
		self.assertFalse(karar.allow)
		self.assertEqual(karar.normalized_targets, {})

	def test_video_hedefi_politikadan_turer(self):
		manifest = _manifest()
		kayit = next(k for k in manifest["fixtures"] if k["file"].endswith("video_16x9_1080p.mp4"))
		probe = probe_video_from_ffprobe(kayit["olculen"], filename="video_16x9_1080p.mp4")
		hedef = self.engine.evaluate("product.video", probe, role="seller").normalized_targets
		self.assertEqual(hedef["video"]["max_width"], 1280)
		self.assertEqual(hedef["video"]["container"], "webm")
		self.assertEqual(hedef["video"]["bitrate_cap_kbps"], 2500)


class AynaTutarliligiTesti(unittest.TestCase):
	"""`core/probe.py` içindeki aynalar kaynakla aynı mı."""

	def test_magic_imzalari_upload_policy_ile_ayni(self):
		from tradehub_core.media.pipeline.core.probe import SIGNATURES

		kaynak = load_module_constants(UPLOAD_POLICY_SRC, ["_SIGNATURES"])
		self.assertIn("_SIGNATURES", kaynak)
		self.assertEqual(tuple(SIGNATURES), tuple(kaynak["_SIGNATURES"]))

	def test_tehlikeli_isaretciler_upload_policy_ile_ayni(self):
		from tradehub_core.media.pipeline.core.probe import DANGEROUS_MARKERS

		kaynak = load_module_constants(UPLOAD_POLICY_SRC, ["_DANGEROUS_MARKERS"])
		self.assertEqual(tuple(DANGEROUS_MARKERS), tuple(kaynak["_DANGEROUS_MARKERS"]))


if __name__ == "__main__":
	unittest.main(verbosity=2)

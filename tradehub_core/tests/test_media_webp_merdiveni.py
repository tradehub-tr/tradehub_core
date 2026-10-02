"""product.image WebP türev merdiveni (2026-09-30).

Kullanıcı kararı: master tek 2000 px kare WebP kalır; türevler yalnız WebP ve
tam 4 genişlik (192, 384, 768, 1280), sabit q80. Bu modül kararın dört
tutunma noktasını kilitler:

1. Politika dosyası (ve şeması) kararı taşıyor.
2. Sınıflandırıcı zinciri yalnız AVIF olsa da teslim biçimine PROFİL karar
   veriyor (eskiden zincirin ilk adımına — AVIF'e — düşülüyordu).
3. Vitrin manifesti WebP türevini `image/webp` olarak basıyor ve geçiş
   süresince eski AVIF merdivenini de sunmaya devam ediyor.
4. `v15_9_63` patch'i `Media Profile` kayıtlarını politikayla hizalıyor.
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_manifest as api
from tradehub_core.media import pipeline_bridge
from tradehub_core.media.pipeline.image import classify
from tradehub_core.media.pipeline.image import render as R

SLOT = "product.image"
GENISLIKLER = [192, 384, 768, 1280]
#: 2026-09-30 ikinci karar: w1280 q88, diğerleri q80.
KALITE = {"w192": 80, "w384": 80, "w768": 80, "w1280": 88}


class _Profil(SimpleNamespace):
	"""`Media Profile` belgesinin `_format_plan`'ın okuduğu yüzü."""

	def get_formats(self):
		return list(self.formats)


class PolitikaTesti(unittest.TestCase):
	def test_dort_webp_basamagi_kare_kalite_haritasi(self):
		profiller = R.load_profiles(SLOT)
		self.assertEqual([p.width for p in profiller], GENISLIKLER)
		for p in profiller:
			with self.subTest(profil=p.name):
				self.assertEqual(p.formats, ("webp",))
				self.assertEqual(p.quality_for("webp"), KALITE[p.name])
				self.assertEqual(p.fit, R.FIT_PAD)
				self.assertEqual(p.target_ratio_value, 1.0)

	def test_sabit_kalite_kipi(self):
		self.assertEqual(R.load_slot_policy(SLOT)["quality"]["rendition_quality_mode"], "fixed")
		self.assertEqual(R.rendition_quality_mode(SLOT), R.QUALITY_MODE_FIXED)

	def test_master_degismedi(self):
		master = R.load_slot_policy(SLOT)["master"]
		self.assertEqual((master["max_long_edge"], master["format"]), (2000, "webp"))

	def test_sema_dogrulamasi(self):
		try:
			import jsonschema
		except ImportError:  # pragma: no cover — konteynerde kurulu
			self.skipTest("jsonschema yok")
		from pathlib import Path

		kok = Path(R.__file__).resolve().parents[1] / "policy"
		sema = json.loads((kok / "schema" / "slot-policy.schema.json").read_text(encoding="utf-8"))
		jsonschema.validate(R.load_slot_policy(SLOT), sema)


class BicimPlaniTesti(unittest.TestCase):
	"""`_format_plan`: teslim biçimi profilden, kalite kipi sınıflandırıcıdan."""

	def _siniflandirma(self):
		return SimpleNamespace(chain=(classify.FormatStep("AVIF"),), klass="photo")

	def test_zincirde_olmayan_webp_profili_webp_uretir(self):
		profil = _Profil(formats=["webp"], quality_target=80)
		plan = pipeline_bridge._format_plan(profil, self._siniflandirma())
		self.assertEqual(plan, (("webp", None),))

	def test_avif_profili_zinciri_kullanmaya_devam_eder(self):
		"""Diğer slotlar (AVIF) değişmedi: zincirle kesişen adım kalitesiyle gelir."""
		profil = _Profil(formats=["avif"], quality_target=61)
		plan = pipeline_bridge._format_plan(profil, self._siniflandirma())
		self.assertEqual(plan, (("avif", 88),))

	def test_webp_tek_teslim_bicimi(self):
		self.assertIn("webp", pipeline_bridge._TEK_TESLIM_BICIMLERI)
		self.assertIn("avif", pipeline_bridge._TEK_TESLIM_BICIMLERI)


def _satir(profil: str, bicim: str, genislik: int, kok: str = "/files/media/a1/v1") -> dict:
	return {
		"profile": profil,
		"format": bicim,
		"width": genislik,
		"height": genislik,
		"file_url": f"{kok}/{profil}-{genislik}.{bicim}",
	}


class ManifestTesti(unittest.TestCase):
	def test_webp_merdiveni_image_webp_olarak_basilir(self):
		satirlar = [_satir(f"w{w}", "webp", w) for w in GENISLIKLER]
		man = api._render_manifest(SLOT, "/files/ab/abcd.webp", satirlar, alt="x", is_lcp=False)
		self.assertIsNotNone(man)
		self.assertEqual([s["type"] for s in man["sources"]], ["image/webp"])
		self.assertEqual(
			man["sources"][0]["srcset"],
			", ".join(f"/files/media/a1/v1/w{w}-{w}.webp {w}w" for w in GENISLIKLER),
		)
		self.assertTrue(man["src"].endswith(".webp"))
		self.assertEqual(sorted(v["width"] for v in man["variants"]), GENISLIKLER)
		self.assertEqual(man["missing_profiles"], [])

	def test_eski_avif_merdiveni_gecis_boyunca_sunulur(self):
		"""Yeniden üretimi bitmemiş varlık: politikada artık olmayan w96/w1920 de dahil."""
		eski = [96, 192, 384, 640, 768, 1280, 1920]
		satirlar = [_satir(f"w{w}", "avif", w, kok="/files/media/a2/v0") for w in eski]
		man = api._render_manifest(SLOT, "/files/ab/abce.webp", satirlar, alt="x", is_lcp=False)
		self.assertIsNotNone(man, "eski AVIF merdiveni manifestten düştü")
		self.assertEqual([s["type"] for s in man["sources"]], ["image/avif"])
		self.assertEqual(sorted(v["width"] for v in man["variants"]), eski)
		self.assertTrue(all(v["type"] == "image/avif" for v in man["variants"]))
		# Yeni politikanın WebP basamakları bu varlıkta henüz yok; profil adları
		# eski merdivende de bulunduğu için eksik (profil, biçim) çifti olarak görünür.
		self.assertEqual(man["missing_profiles"], [])
		self.assertEqual(man["missing_variants"], ["w1280.webp", "w192.webp", "w384.webp", "w768.webp"])


class ProfilPatchTesti(FrappeTestCase):
	def test_patch_profilleri_politikayla_hizalar(self):
		from tradehub_core.patches import v15_9_63_product_image_webp_profiles as patch

		patch.execute()
		satirlar = frappe.get_all(
			"Media Profile",
			filters={"slot_key": SLOT},
			fields=["policy_profile", "enabled", "formats", "quality_target"],
		)
		acik = {r.policy_profile: r for r in satirlar if r.enabled}
		self.assertEqual(sorted(acik), sorted(f"w{w}" for w in GENISLIKLER))
		for ad, r in acik.items():
			self.assertEqual(json.loads(r.formats), ["webp"])
			self.assertEqual(int(r.quality_target), KALITE[ad])
		# Politikadan kalkan her kayıt (yerelde w96/w640/w1920) kapalı; satır silinmez.
		kapali = {r.policy_profile for r in satirlar if not r.enabled}
		self.assertEqual(kapali, {r.policy_profile for r in satirlar} - set(acik))
		self.assertFalse(kapali & set(acik))


class KucukResimTesti(FrappeTestCase):
	"""`thumbs.thumbs_for`: emekli varlığın / eski sürümün türevi küçük resim olmaz."""

	def _varlik(self, dosya: str, durum: str, surum: str, bicim: str, genislik: int) -> str:
		varlik = frappe.get_doc(
			{"doctype": "Media Asset", "slot_key": SLOT, "media_type": "image", "state": durum}
		).insert(ignore_permissions=True)
		# `active_version` bir Link; test sürüm kaydı açmadan ham değer yazar.
		frappe.db.set_value(
			"Media Asset", varlik.name, {"source_file": dosya, "active_version": surum}, update_modified=False
		)
		turev = frappe.get_doc(
			{
				"doctype": "Media Rendition",
				"asset": varlik.name,
				"profile": f"w{genislik}",
				"width": genislik,
				"format": bicim,
				"state": "ready",
				"version_hash": surum,
				"file_url": f"/files/media/{varlik.name}/{surum}/w{genislik}-{genislik}.{bicim}",
			}
		)
		# `version_hash` bir Link; test sürüm kaydı açmıyor.
		turev.flags.ignore_links = True
		turev.insert(ignore_permissions=True)
		return varlik.name

	def test_emekli_ve_eski_surum_turevi_secilmez(self):
		from tradehub_core.media import thumbs

		dosya = frappe.get_doc(
			{"doctype": "File", "file_name": "kucuk-resim-testi.webp", "is_private": 0, "content": b"x"}
		).insert(ignore_permissions=True)
		eski = self._varlik(dosya.name, "archived", "a" * 64, "avif", 96)
		yeni = self._varlik(dosya.name, "ready", "b" * 64, "webp", 192)
		# Aynı varlığın yayında OLMAYAN bir sürümüne ait daha küçük türev de atlanmalı.
		eski_surum = frappe.get_doc(
			{
				"doctype": "Media Rendition",
				"asset": yeni,
				"profile": "w96",
				"width": 96,
				"format": "avif",
				"state": "ready",
				"version_hash": "c" * 64,
				"file_url": f"/files/media/{yeni}/{'c' * 64}/w96-96.avif",
			}
		)
		eski_surum.flags.ignore_links = True
		eski_surum.insert(ignore_permissions=True)
		sonuc = thumbs.thumbs_for([dosya.file_url])[dosya.file_url]
		self.assertEqual(sonuc["thumb"], f"/files/media/{yeni}/{'b' * 64}/w192-192.webp")
		self.assertNotIn(eski, sonuc["thumb"] + sonuc["preview"])


class MasterAdayiTesti(unittest.TestCase):
	"""Kare WebP master, merdivenin en büyük `srcset` adayı (≤2000, 2026-09-30)."""

	def _turevler(self):
		return [_satir(f"w{w}", "webp", w) for w in GENISLIKLER]

	def test_kare_webp_master_en_ust_aday_olur(self):
		varlik = {"master_width": 1800, "master_height": 1800}
		ek = api._master_adayi(SLOT, "/files/ab/abcd.webp", varlik, self._turevler())
		self.assertEqual(len(ek), 1)
		man = api._render_manifest(SLOT, "/files/ab/abcd.webp", self._turevler() + ek, alt="x", is_lcp=False)
		srcset = man["sources"][0]["srcset"]
		self.assertTrue(srcset.endswith("/files/ab/abcd.webp 1800w"), srcset)
		self.assertEqual(max(v["width"] for v in man["variants"]), 1800)

	def test_kosul_disi_master_eklenmez(self):
		t = self._turevler()
		self.assertEqual(
			api._master_adayi(SLOT, "/files/ab/a.jpg", {"master_width": 1800, "master_height": 1800}, t), []
		)
		self.assertEqual(
			api._master_adayi(SLOT, "/files/ab/a.webp", {"master_width": 1800, "master_height": 1500}, t), []
		)
		self.assertEqual(
			api._master_adayi(SLOT, "/files/ab/a.webp", {"master_width": 2400, "master_height": 2400}, t), []
		)
		self.assertEqual(
			api._master_adayi(SLOT, "/files/ab/a.webp", {"master_width": 1280, "master_height": 1280}, t), []
		)
		self.assertEqual(
			api._master_adayi(
				"brand.logo", "/files/ab/a.webp", {"master_width": 1800, "master_height": 1800}, t
			),
			[],
		)


class LazyKapisiTesti(FrappeTestCase):
	"""Lazy profili olmayan slotta manifest okuması master'ı işlemez (2026-09-30)."""

	def test_lazy_profil_yoksa_master_hazirlanmaz(self):
		from unittest import mock

		ad = frappe.db.get_value("Media Asset", {"slot_key": SLOT, "state": "ready"}, "name")
		if not ad:
			self.skipTest("hazır ürün varlığı yok")
		with mock.patch.object(pipeline_bridge, "_prepare_image_master") as hazirla:
			sonuc = pipeline_bridge.ensure_lazy_renditions(ad)
		hazirla.assert_not_called()
		self.assertIn(sonuc["status"], {"no_lazy_profiles", "disabled", "rollout_disabled"})
		self.assertFalse(pipeline_bridge._slot_has_lazy_profiles(SLOT))

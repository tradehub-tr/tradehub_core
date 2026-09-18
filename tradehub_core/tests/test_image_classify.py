"""T-062 — İçerik sınıflandırma testleri: 5 sınıf → biçim zinciri.

DOĞRULUK NEREDE ÖLÇÜLDÜ
-----------------------
Genel media manifestindeki `class` alanı içerik sınıfı değil fixture ailesidir;
bu nedenle doğruluk kapısı ayrı, dengeli ve yeniden üretilebilir bir korpustur:
20 photo + 20 graphic + 20 transparent + 20 animation + 20 document.
Her örnek gerçek dosya baytına kodlanır ve `classify()` uçtan uca çağrılır.

Bu yüzden içerik sınıflandırma doğruluğu **canlı korpustan** ölçüldü:

    Örneklem : 4.341 dosyadan rastgele 48 görsel (seed 4242, stratifiye DEĞİL)
    Etiket   : elle, kontak sayfalarına bakılarak (2026-08-18)
    Dağılım  : 44 photo · 4 graphic (#03, #13, #21, #31)
    SONUÇ    : **46/48 = %95,8**  ·  graphic kesinliği 2/2 = %100
    Kaçanlar : #03 (soluk çizim + damga), #31 (dokulu fonda kelime-marka)
    Süre     : p50 32 ms · p90 41 ms · en kötü 137 ms

DÜRÜST SINIR — canlı %95,8 tek başına sağlam bir tahmin DEĞİLDİR:
  * 48 örnekte yalnız **4 pozitif** var. "Hep photo de" diyen boş bir
    sınıflandırıcı bile %91,7 alır; ölçülen üstünlük 2 dosyadan ibarettir.
  * Eşikler bu 4 pozitifin üzerinde kalibre edildi — aynı veride ölçülen
    doğruluk iyimserdir (in-sample).
  * Canlı örneklem beş sınıfı kapsamıyordu; dengeli korpus bu vacuity'yi
    kapatır ama sentetiktir, üretim dağılımının yerine geçmez.

Korpus büyüdüğünde `GRAPHIC_*` eşikleri yeniden kalibre edilmelidir.
Aşağıdaki testler doğruluğu, eşik davranışını ve yönlendirme sözleşmesini ayrı
ayrı sabitler; canlı örneklem repoda olmadığı için sonucu ek kanıt olarak kalır.

Çalıştırma:

    python3 -m unittest tests.test_image_classify -v
"""

from __future__ import annotations

import io
import json
import random
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.image import classify as C  # noqa: E402
from tradehub_core.media.pipeline.image.probe import GuardConfig  # noqa: E402

IMAGES = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "images"
MANIFEST = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "manifest.json"
CLASSIFY_MANIFEST = ROOT / "tradehub_core" / "tests" / "fixtures" / "image_t062" / "manifest.json"
MEDIA_VERSION_SCHEMA = (
	ROOT / "tradehub_core" / "tradehub_core" / "doctype" / "media_version" / "media_version.json"
)
MEDIA_VERSION_SPEC = ROOT / "tradehub_core" / "media" / "pipeline" / "doctype_specs" / "media_version.json"

GEVSEK = GuardConfig(max_megapixels=200.0, max_bytes=64 * 1024 * 1024, allow_animated=True)


_CLASSIFY_MEMORY_PROBE_CODE = """
import json
import resource
import sys
from tradehub_core.media.pipeline.image.classify import classify
from tradehub_core.media.pipeline.image.probe import GuardConfig

result = classify(
    sys.argv[1],
    guard=GuardConfig(max_megapixels=200.0, max_bytes=64 * 1024 * 1024, allow_animated=True),
)
raw_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
peak_bytes = int(raw_peak if sys.platform == "darwin" else raw_peak * 1024)
print(json.dumps({
    "ok": result.ok,
    "klass": result.klass,
    "peak_rss_bytes": peak_bytes,
}))
"""


def _measure_classify_peak(path: Path) -> dict:
	"""Sınıflandırmayı temiz alt süreçte ölç; fixture üretiminin RSS'ini dışla."""
	proc = subprocess.run(
		[sys.executable, "-c", _CLASSIFY_MEMORY_PROBE_CODE, str(path)],
		cwd=ROOT,
		capture_output=True,
		text=True,
		timeout=120,
		check=False,
	)
	if proc.returncode:
		raise AssertionError(proc.stderr or proc.stdout)
	return json.loads(proc.stdout.strip().splitlines()[-1])


#: Canlı örneklemde ÖLÇÜLEN doğruluk (yukarıdaki blok). Kod bu sayıyı
#: yeniden üretemez (görseller repoda değil); sabit, ölçümün kaydıdır.
CANLI_ORNEKLEM_N: int = 48
CANLI_ORNEKLEM_DOGRU: int = 46

#: Yeniden üretilebilir dengeli korpus: manifestteki 5 sınıf × N örnek.
_DENGELI_MANIFEST: dict = json.loads(CLASSIFY_MANIFEST.read_text(encoding="utf-8"))
DENGELI_SINIF_BASINA: int = int(_DENGELI_MANIFEST["samples_per_class"])
DENGELI_ORNEKLEM_N: int = len(C.SINIFLAR) * DENGELI_SINIF_BASINA

#: Fixture korpusunda manifest etiketiyle AYRILAN dosyalar. Ayrılma bir hata
#: değil, yukarıda anlatılan etiket anlamı farkıdır — hepsi "graphic"
#: etiketli sentetik gürültü. Liste sabitlendi ki sınıflandırıcı değişince
#: ayrımın nerede olduğu görülsün.
BEKLENEN_AYRIM: frozenset[str] = frozenset(
	{
		"mode_palette_p.png",
		"mode_grayscale_l.png",
		"geom_strip_400x4000.png",
		"exif_orientation6.jpg",
		"logo_jpeg_noalpha.jpg",
		"content_blank_white.png",
		"content_border_40pct.png",
		"content_border_08pct.png",
		"real_adobergb_3780x2717.png",
	}
)


def _fixtures(sinif: str | None = None) -> list[dict]:
	kayitlar = json.loads(MANIFEST.read_text(encoding="utf-8"))["fixtures"]
	if sinif is None:
		return kayitlar
	return [f for f in kayitlar if f["class"] == sinif]


def _foto() -> C.Features:
	"""Tipik bir fotoğrafın ÖLÇÜLEN profili (canlı #11, 5536×4160)."""
	return C.Features(
		frame_count=1,
		has_alpha_channel=False,
		alpha_translucent_ratio=0.0,
		unique_colors=11227,
		quantized_colors=259,
		top_color_share=0.003,
		flat_ratio=0.370,
		soft_edge_ratio=0.914,
		hard_edge_ratio=0.086,
		edge_density=0.093,
		bilevel_ratio=0.118,
		saturation_mean=42.8,
		source_format="JPEG",
		lossy_source=True,
		width=5536,
		height=4160,
		mode="RGB",
	)


def _kodla(im, fmt: str, **kwargs) -> bytes:
	buf = io.BytesIO()
	im.save(buf, fmt, **kwargs)
	im.close()
	return buf.getvalue()


def _korpus_ornegi(sinif: str, seed: int) -> tuple[bytes, str]:
	"""Arrange: beş sınıftan deterministik, gerçek kodlanmış bir örnek."""
	from PIL import Image, ImageDraw

	if sinif == C.SINIF_PHOTO:
		rng = random.Random(seed)
		im = Image.new("RGB", (192, 144))
		px = im.load()
		for y in range(im.height):
			for x in range(im.width):
				n = rng.randrange(-12, 13)
				px[x, y] = ((x * 3 + y + n) % 256, (x + y * 2 - n) % 256, (x * 2 + y * 3 + n) % 256)
		return _kodla(im, "JPEG", quality=88), f"photo-{seed}.jpg"

	if sinif == C.SINIF_GRAPHIC:
		renkler = ((12, 42, 180), (245, 190, 8), (230, 30, 70), (30, 200, 150))
		im = Image.new("RGB", (192, 144), renkler[seed % 4])
		draw = ImageDraw.Draw(im)
		draw.rectangle((20 + seed % 9, 18, 172, 52), fill=renkler[(seed + 1) % 4])
		draw.rectangle((30, 76, 160 - seed % 7, 126), fill=renkler[(seed + 2) % 4])
		draw.line((0, 70, 191, 70), fill=renkler[(seed + 3) % 4], width=5)
		return _kodla(im, "PNG"), f"graphic-{seed}.png"

	if sinif == C.SINIF_TRANSPARENT:
		im = Image.new("RGBA", (192, 144), (0, 0, 0, 0))
		draw = ImageDraw.Draw(im)
		draw.ellipse((20 + seed % 10, 15, 170, 130), fill=(30 + seed * 3 % 200, 80, 210, 255))
		draw.rectangle((60, 45, 132, 100), fill=(250, 210, 20, 160))
		return _kodla(im, "PNG"), f"transparent-{seed}.png"

	if sinif == C.SINIF_ANIMATION:
		ilk = Image.new("RGB", (192, 144), (20, 40 + seed % 100, 180))
		ikinci = Image.new("RGB", (192, 144), (220, 40, 40 + seed % 100))
		buf = io.BytesIO()
		ilk.save(buf, "GIF", save_all=True, append_images=[ikinci], duration=80, loop=0)
		ilk.close()
		ikinci.close()
		return buf.getvalue(), f"animation-{seed}.gif"

	if sinif == C.SINIF_DOCUMENT:
		# 160 px kutu: özellik küçültmesinde gri anti-alias üretmez; gerçek
		# iki-tonlu belge kenarı ölçülür.
		im = Image.new("L", (160, 120), 255)
		draw = ImageDraw.Draw(im)
		for y in range(5, 115, 5):
			for x in range(5 + (seed + y) % 4, 155, 22):
				draw.rectangle((x, y, x + 13 + (x + seed) % 5, y + 1), fill=0)
		draw.rectangle((3, 3, 4, 116), fill=0)
		draw.rectangle((155, 3, 156, 116), fill=0)
		return _kodla(im, "PNG"), f"document-{seed}.png"

	raise AssertionError(f"bilinmeyen sınıf: {sinif}")


class SinifSirasiTest(unittest.TestCase):
	"""Karar sırası anlamlıdır: kesin ölçülebilen önce gelir."""

	def test_animasyon_her_seyi_yener(self):
		"""Çok kareli girdi alfası da olsa `animation`'dır."""
		f = replace(_foto(), frame_count=6, has_alpha_channel=True, alpha_translucent_ratio=0.9)
		sinif, guven, _ = C.classify_features(f)

		self.assertEqual(sinif, C.SINIF_ANIMATION)
		self.assertEqual(guven, "exact")

	def test_saydamlik_grafigi_yener(self):
		f = replace(
			_foto(),
			has_alpha_channel=True,
			alpha_translucent_ratio=0.66,
			saturation_mean=200.0,
			top_color_share=0.9,
		)
		sinif, guven, _ = C.classify_features(f)

		self.assertEqual(sinif, C.SINIF_TRANSPARENT)
		self.assertEqual(guven, "exact")

	def test_opak_alfa_kanali_saydam_saymaz(self):
		"""Alfa kanalı VAR ama tamamı opak — kesim değil, sınıf düşmemeli.

		ÖLÇÜLDÜ (canlı): 3 PNG/P dosyada alfa kanalı var, saydam oran 0,000.
		"""
		f = replace(_foto(), has_alpha_channel=True, alpha_translucent_ratio=0.0)
		sinif, _, gerekce = C.classify_features(f)

		self.assertEqual(sinif, C.SINIF_PHOTO)
		self.assertIn("alpha_channel_present_but_opaque", gerekce)

	def test_surekli_ton_kaniti_photo_high(self):
		sinif, guven, gerekce = C.classify_features(_foto())

		self.assertEqual(sinif, C.SINIF_PHOTO)
		self.assertEqual(guven, "high")
		self.assertTrue(any("quantized_colors" in neden for neden in gerekce))

	def test_kanit_yoksa_varsayilan_photo_low(self):
		belirsiz = C.Features(
			unique_colors=12,
			quantized_colors=12,
			top_color_share=0.2,
			hard_edge_ratio=0.2,
			edge_density=0.02,
			bilevel_ratio=0.1,
			saturation_mean=20.0,
			source_format="PNG",
		)
		sinif, guven, gerekce = C.classify_features(belirsiz)

		self.assertEqual(sinif, C.SINIF_PHOTO)
		self.assertEqual(guven, "low")
		self.assertIn("default_photo", gerekce)


class SaydamlikEsigiTest(unittest.TestCase):
	def test_esik_altinda_photo_ustunde_transparent(self):
		alt = replace(
			_foto(),
			has_alpha_channel=True,
			alpha_translucent_ratio=C.ALPHA_TRANSLUCENT_MIN - 0.001,
		)
		ust = replace(
			_foto(),
			has_alpha_channel=True,
			alpha_translucent_ratio=C.ALPHA_TRANSLUCENT_MIN,
		)

		self.assertEqual(C.classify_features(alt)[0], C.SINIF_PHOTO)
		self.assertEqual(C.classify_features(ust)[0], C.SINIF_TRANSPARENT)

	def test_fixturelarda_saydam_5te5(self):
		"""Saydamlık KESİN ölçülür — burada tam isabet beklenir."""
		for f in _fixtures("transparent"):
			yol = ROOT / f["file"]
			with self.subTest(dosya=yol.name):
				r = C.classify(yol, guard=GEVSEK)
				self.assertEqual(r.klass, C.SINIF_TRANSPARENT, f"{yol.name}: {r.reasons}")
				self.assertEqual(r.confidence, "exact")

	def test_fixturelarda_animasyon_2de2(self):
		for f in _fixtures("animation"):
			yol = ROOT / f["file"]
			with self.subTest(dosya=yol.name):
				r = C.classify(yol, guard=GEVSEK)
				self.assertEqual(r.klass, C.SINIF_ANIMATION)
				self.assertEqual(r.confidence, "exact")
				self.assertTrue(r.route_to_video)
				self.assertEqual(r.job_type, C.JOB_TYPE_VIDEO_FROM_ANIMATION)
				self.assertEqual(r.chain, ())


class GrafikEsigiTest(unittest.TestCase):
	"""`graphic` demek için güçlü kanıt aranır — maliyet asimetriktir (7,86x)."""

	def test_kayipsiz_sert_kenarli_az_renkli_grafiktir(self):
		f = replace(
			_foto(),
			lossy_source=False,
			source_format="PNG",
			hard_edge_ratio=1.0,
			quantized_colors=13,
		)
		sinif, guven, gerekce = C.classify_features(f)

		self.assertEqual(sinif, C.SINIF_GRAPHIC)
		self.assertEqual(guven, "high")
		self.assertIn("lossless_source", gerekce)

	def test_kayipli_kaynakta_sert_kenar_yolu_kapali(self):
		"""ÖLÇÜLDÜ: JPEG'e gömülü düz grafiğin yumuşak geçiş oranı 0,869 —
		fotoğraftan ayırt edilemiyor. Kayıplı kaynakta bu yola girilmemeli."""
		f = replace(
			_foto(),
			lossy_source=True,
			source_format="JPEG",
			hard_edge_ratio=1.0,
			quantized_colors=13,
		)

		self.assertEqual(C.classify_features(f)[0], C.SINIF_PHOTO)

	def test_cok_renkli_sert_kenar_grafik_degildir(self):
		"""Canlı #23: PNG, sert kenar 0,594 ama 49 renk — fotoğraf. Yanlış-pozitif olmamalı."""
		f = replace(
			_foto(),
			lossy_source=False,
			source_format="PNG",
			hard_edge_ratio=0.594,
			quantized_colors=49,
		)

		self.assertEqual(C.classify_features(f)[0], C.SINIF_PHOTO)

	def test_doygun_duz_grafik_kayipli_kaynakta_da_yakalanir(self):
		"""Canlı #13: düz lacivert + sarı yazı, JPEG. Doygunluk 187,1."""
		f = replace(_foto(), saturation_mean=187.1, top_color_share=0.481)
		sinif, guven, _ = C.classify_features(f)

		self.assertEqual(sinif, C.SINIF_GRAPHIC)
		self.assertEqual(guven, "high")

	def test_doygun_ama_dagilmis_renk_grafik_degildir(self):
		"""Doygunluk tek başına yetmez; tek renk hakimiyeti de aranır."""
		f = replace(_foto(), saturation_mean=187.1, top_color_share=0.05)

		self.assertEqual(C.classify_features(f)[0], C.SINIF_PHOTO)

	def test_en_doygun_fotograf_grafik_sayilmaz(self):
		"""ÖLÇÜLDÜ: 44 fotoğrafın doygunluk tavanı 103,3 — eşik 150 ile arada 46 puan boşluk."""
		f = replace(_foto(), saturation_mean=103.3, top_color_share=0.9)

		self.assertEqual(C.classify_features(f)[0], C.SINIF_PHOTO)
		self.assertGreater(C.GRAPHIC_SATURATION_MIN, 103.3)


class BelgeSinifiTest(unittest.TestCase):
	"""Kanonik beşinci sınıf `document`; eski `text` yalnız giriş takma adı."""

	def test_document_olculdu_bayragi_dogru(self):
		self.assertTrue(C.DOCUMENT_OLCULDU)
		self.assertTrue(C.TEXT_OLCULDU)
		self.assertEqual(C.SINIF_TEXT, C.SINIF_DOCUMENT)

	def test_belge_profili_document_verir(self):
		f = replace(
			_foto(),
			bilevel_ratio=0.95,
			edge_density=0.20,
			quantized_colors=8,
			saturation_mean=4.0,
			lossy_source=False,
		)
		sinif, guven, gerekce = C.classify_features(f)

		self.assertEqual(sinif, C.SINIF_DOCUMENT)
		self.assertEqual(guven, "high")
		self.assertTrue(any("bilevel_ratio" in g for g in gerekce))

	def test_document_esiklerinin_dort_siniri_da_dahilidir(self):
		"""AAA sınırları: tam eşik document, tek ölçüt eşiği kaçırınca değil."""
		tam = replace(
			_foto(),
			bilevel_ratio=C.DOCUMENT_BILEVEL_MIN,
			edge_density=C.DOCUMENT_EDGE_DENSITY_MIN,
			quantized_colors=C.DOCUMENT_QUANT_COLORS_MAX,
			saturation_mean=C.DOCUMENT_SATURATION_MAX,
			lossy_source=False,
		)
		self.assertEqual(C.classify_features(tam)[0], C.SINIF_DOCUMENT)

		sinir_disi = (
			replace(tam, bilevel_ratio=C.DOCUMENT_BILEVEL_MIN - 0.001),
			replace(tam, edge_density=C.DOCUMENT_EDGE_DENSITY_MIN - 0.001),
			replace(tam, quantized_colors=C.DOCUMENT_QUANT_COLORS_MAX + 1),
			replace(tam, saturation_mean=C.DOCUMENT_SATURATION_MAX + 0.1),
		)
		for f in sinir_disi:
			with self.subTest(features=f):
				self.assertNotEqual(C.classify_features(f)[0], C.SINIF_DOCUMENT)

	def test_eski_text_girdisi_document_zincirine_cozulur(self):
		caps = {"AVIF": True}
		self.assertEqual(C.format_chain("text", caps), C.format_chain(C.SINIF_DOCUMENT, caps))


class BicimZinciriTest(unittest.TestCase):
	def test_tum_statik_siniflar_tek_bicim_avif(self):
		for sinif in set(C.SINIFLAR) - {C.SINIF_ANIMATION}:
			with self.subTest(sinif=sinif):
				self.assertEqual([a.fmt for a in C.FORMAT_CHAINS[sinif]], ["AVIF"])
		self.assertEqual(C.FORMAT_CHAINS[C.SINIF_ANIMATION], ())

	def test_avif_yoksa_jpeg_ve_webpye_donulmez(self):
		caps = {"AVIF": False, "JPEG": True, "PNG": True, "WEBP": True, "WEBP:lossless": True}
		for sinif in C.SINIFLAR:
			self.assertEqual(C.format_chain(sinif, caps), ())

	def test_saydam_zinciri_avif_alfa_yetenegi_ister(self):
		caps = {"AVIF": True, "AVIF:alpha": False, "PNG": True, "PNG:alpha": True}
		self.assertEqual(C.format_chain(C.SINIF_TRANSPARENT, caps), ())
		caps["AVIF:alpha"] = True
		self.assertEqual([a.fmt for a in C.format_chain(C.SINIF_TRANSPARENT, caps)], ["AVIF"])

	def test_grafik_ve_belge_yuksek_kalite_avif_kullanir(self):
		for sinif in (C.SINIF_GRAPHIC, C.SINIF_DOCUMENT):
			(step,) = C.FORMAT_CHAINS[sinif]
			self.assertEqual(step.quality_target, 100)
			self.assertFalse(step.lossless, "q100 piksel-eş kayıpsızlık iddiası değildir")

	def test_photo_baslangic_kalitesi_korunur(self):
		(step,) = C.FORMAT_CHAINS[C.SINIF_PHOTO]
		self.assertFalse(step.lossless)
		self.assertEqual(step.quality_target, 88)

	def test_dusuk_guven_yuksek_kaliteli_avif_kullanir(self):
		from PIL import Image

		kaynak = _kodla(Image.new("RGB", (96, 96), (128, 128, 128)), "PNG")
		r = C.classify(kaynak, filename="ambiguous.png", capabilities={"AVIF": True})
		self.assertTrue(r.ok, r.error)
		self.assertEqual((r.klass, r.confidence), (C.SINIF_PHOTO, "low"))
		self.assertTrue(r.safe_fallback)
		self.assertEqual([a.fmt for a in r.chain], ["AVIF"])
		self.assertEqual(r.chain[0].quality_target, 100)

	def test_yetenek_sondasi_calisir(self):
		yet = C.encoder_capabilities()
		self.assertTrue(yet["AVIF"], "AVIF encoder üretim ortamında zorunludur")
		self.assertTrue(yet["AVIF:alpha"])


class KapiTest(unittest.TestCase):
	"""Sınıflandırma için bile kötücül dosya decode edilmez."""

	def test_kotucul_dosyalar_siniflandirilmadan_reddedilir(self):
		for f in _fixtures("malicious"):
			yol = ROOT / f["file"]
			with self.subTest(dosya=yol.name):
				r = C.classify(yol)
				self.assertFalse(r.ok, f"{yol.name} sınıflandırıldı — kapıdan geçmemeliydi")
				self.assertIn("gate_reject", r.reasons)
				self.assertIsNone(r.features, "reddedilen dosyanın pikselleri okunmuş")

	def test_skip_guard_ile_kapi_atlanir(self):
		"""Kapı zaten çalıştıysa iki kez ödenmemeli."""
		r = C.classify(IMAGES / "ok_product_4x5.jpg", skip_guard=True)
		self.assertTrue(r.ok)
		self.assertIsNone(r.probe)


class YonlendirmeKontratiTest(unittest.TestCase):
	"""Bridge ajanının tüketeceği animasyon → video kontratı."""

	def test_animated_gif_varsayilan_kapida_reddedilmez_videoya_yonlenir(self):
		kaynak, ad = _korpus_ornegi(C.SINIF_ANIMATION, 7)

		r = C.classify(kaynak, filename=ad)

		self.assertTrue(r.ok, r.error)
		self.assertEqual(r.klass, C.SINIF_ANIMATION)
		self.assertEqual(r.target_pipeline, C.PIPELINE_VIDEO)
		self.assertEqual(r.job_type, "video_from_animation")
		self.assertTrue(r.route_to_video)
		self.assertEqual(r.chain, (), "animasyon görsel kodlayıcıya düşmemeli")
		self.assertEqual(r.video_targets, (("MP4", "H264"), ("WEBM", "VP9")))
		self.assertTrue(r.poster_required)

	def test_animated_gif_basliktan_yonlenir_piksel_decode_edilmez(self):
		"""Animation kesin başlık bilgisidir; pahalı özellik çıkarımı çalışmamalı."""
		kaynak, ad = _korpus_ornegi(C.SINIF_ANIMATION, 11)

		with mock.patch.object(C, "extract_features", side_effect=AssertionError("piksel decode")):
			r = C.classify(kaynak, filename=ad)

		self.assertTrue(r.ok, r.error)
		self.assertEqual((r.klass, r.confidence), (C.SINIF_ANIMATION, "exact"))
		self.assertIsNone(r.features)
		self.assertEqual((r.target_pipeline, r.job_type), (C.PIPELINE_VIDEO, C.JOB_TYPE_VIDEO_FROM_ANIMATION))

	def test_statik_girdi_image_rendition_olarak_kalir(self):
		kaynak, ad = _korpus_ornegi(C.SINIF_GRAPHIC, 3)
		r = C.classify(kaynak, filename=ad)

		self.assertTrue(r.ok, r.error)
		self.assertEqual((r.target_pipeline, r.job_type), (C.PIPELINE_IMAGE, C.JOB_TYPE_IMAGE_RENDITION))
		self.assertFalse(r.route_to_video)


class BellekButcesiTest(unittest.TestCase):
	def test_72mp_rgba_siniflandirma_peak_bellek_500mb_altinda(self):
		"""Tam-frame RGBA/RGB/gri kopyaları yerine bounded tile/thumbnail kullanılır."""
		with tempfile.TemporaryDirectory(prefix="t062-rgba-memory-") as gecici:
			kaynak = Path(gecici) / "alpha-72mp.png"
			uret = (
				"from PIL import Image; import sys; "
				"im=Image.new('RGBA',(8527,8527),(10,20,30,128)); "
				"im.save(sys.argv[1],'PNG',compress_level=9); im.close()"
			)
			subprocess.run([sys.executable, "-c", uret, str(kaynak)], check=True, timeout=120)

			olcum = _measure_classify_peak(kaynak)

		self.assertTrue(olcum["ok"], olcum)
		self.assertEqual(olcum["klass"], C.SINIF_TRANSPARENT)
		self.assertLess(olcum["peak_rss_bytes"], 500 * 1024 * 1024, olcum)


class FixtureAyrimTest(unittest.TestCase):
	"""Manifest etiketiyle ayrılan dosyalar tam olarak beklenenler mi."""

	def test_ayrim_listesi_sabit(self):
		ayrilan = set()
		for f in _fixtures():
			if f["class"] in ("malicious", "video"):
				continue
			yol = ROOT / f["file"]
			r = C.classify(yol, guard=GEVSEK)
			if r.klass != f["class"]:
				ayrilan.add(yol.name)

		self.assertEqual(
			ayrilan,
			set(BEKLENEN_AYRIM),
			"fixture ayrımı değişti — sınıflandırıcı ya da manifest güncellenmiş",
		)

	def test_ayrilanlar_manifest_fixture_aileleridir(self):
		"""Ayrımlar içerik etiketi değil fixture ailesi olduğundan beklenir."""
		etiket = {Path(f["file"]).name: f["class"] for f in _fixtures()}
		for ad in BEKLENEN_AYRIM:
			with self.subTest(dosya=ad):
				beklenen_aile = "photo" if ad == "real_adobergb_3780x2717.png" else "graphic"
				self.assertEqual(etiket[ad], beklenen_aile)

	def test_canli_olcum_kaydi(self):
		"""Ölçümün kaydı — %95,8 hedefi tutmuştu."""
		oran = CANLI_ORNEKLEM_DOGRU / CANLI_ORNEKLEM_N
		self.assertGreaterEqual(oran, 0.95)


class DengeliDogrulukTest(unittest.TestCase):
	"""Act/Assert: beş sınıfın dengeli 100 örnekte doğruluğu ≥%95."""

	def test_bes_sinif_dengeli_korpusta_yuzde_95_ustu(self):
		caps = C.encoder_capabilities()
		dogru = Counter()
		toplam = Counter()
		yanlislar: list[str] = []

		self.assertEqual(set(_DENGELI_MANIFEST["classes"]), set(C.SINIFLAR))
		minimum = float(_DENGELI_MANIFEST["minimum_accuracy"])
		for beklenen in C.SINIFLAR:
			for seed in range(DENGELI_SINIF_BASINA):
				kaynak, ad = _korpus_ornegi(beklenen, seed)
				r = C.classify(kaynak, filename=ad, capabilities=caps)
				toplam[beklenen] += 1
				if r.ok and r.klass == beklenen:
					dogru[beklenen] += 1
				else:
					yanlislar.append(f"{ad}:{r.klass}:{r.error or ','.join(r.reasons)}")

		genel = sum(dogru.values()) / DENGELI_ORNEKLEM_N
		self.assertGreaterEqual(genel, minimum, yanlislar)
		for sinif in C.SINIFLAR:
			with self.subTest(sinif=sinif):
				self.assertGreaterEqual(dogru[sinif] / toplam[sinif], minimum, yanlislar)


class SozlesmeTest(unittest.TestCase):
	def test_media_version_schema_bes_kanonik_sinifi_ve_kalite_hedefini_tasir(self):
		for path in (MEDIA_VERSION_SCHEMA, MEDIA_VERSION_SPEC):
			with self.subTest(path=path):
				schema = json.loads(path.read_text(encoding="utf-8"))
				fields = {field["fieldname"]: field for field in schema["fields"] if "fieldname" in field}
				self.assertEqual(
					set(fields["classification"]["options"].splitlines()[1:]),
					set(C.SINIFLAR),
				)
				self.assertIn("quality_target", fields["format_chain"]["description"])

	def test_bozuk_girdi_istisna_atmaz(self):
		for girdi in (b"", b"\x00\x01", b"garbage"):
			with self.subTest(girdi=girdi[:6]):
				r = C.classify(girdi, filename="x.jpg")
				self.assertFalse(r.ok)
				self.assertEqual(r.klass, C.SINIF_PHOTO, "hata hâlinde bile güvenli varsayılan")

	def test_to_dict_serilestirilebilir(self):
		r = C.classify(IMAGES / "ok_product_4x5.jpg", guard=GEVSEK)
		sozluk = r.to_dict()
		json.dumps(sozluk)
		self.assertIn("chain", sozluk)
		self.assertEqual((sozluk["target_pipeline"], sozluk["job_type"]), ("image", "rendition"))

	def test_siniflar_listesi_bes(self):
		self.assertEqual(len(C.SINIFLAR), 5)
		self.assertEqual(
			set(C.SINIFLAR),
			{"photo", "transparent", "graphic", "animation", "document"},
		)
		self.assertNotIn("text", C.SINIFLAR)

	def test_sonuc_hep_bilinen_sinif(self):
		for f in _fixtures():
			if f["class"] in ("malicious", "video"):
				continue
			with self.subTest(dosya=Path(f["file"]).name):
				r = C.classify(ROOT / f["file"], guard=GEVSEK)
				self.assertIn(r.klass, C.SINIFLAR)


if __name__ == "__main__":
	unittest.main(verbosity=2)

"""T-063 / T-064 / T-066 — türev üretimi, idempotensi ve kalite raporu testleri.

Kapsam:
  * Profil matrisinin KOD DEĞİL VERİ olduğu — `policy/slots/*.json` bağımsız
    okunur ve modülün okuduğuyla karşılaştırılır (sürüklenme kilidi)
  * Geometri: upscale yasağı (FR-028), `fit` üç kipi, dolgu, kırpma penceresi
  * Yeniden örnekleme: Lanczos3 ve çarpılmış alfa (halo yok)
  * Encode: determinizm, alfa düzleştirme, kayıpsız kip, ICC
  * Fayda kapısı INV-05: çıktı kaynaktan küçük değilse ATILIR, zincir bir alta
    düşer, zincir biterse kaynak geçer
  * Adaptif kalite: encode bütçesi (≤4) ve "kalite uydurma" yasağı
  * T-064 idempotensi: türetme anahtarı, defter, atlama, nesil kaybı
  * T-066 rapor: ölçülmeyen alanın `null` kalması, Türkçe özet, JSON'lanabilirlik

Koşum — site/bench/DB GEREKMEZ, yalnız Pillow:

    python3 -m unittest tests.test_render -v

Testler bilerek KÜÇÜK ve çoğunlukla WebP/JPEG üzerinden çalışır: AVIF encode
1920px'te ~1 sn sürüyor (docs/data/t063-render-olcum.json), tüm matrisi test
içinde koşmak süiti dakikalara çıkarırdı. Gerçek fixture ölçümü
`tests/test_render_regression.py` ve `scripts/measure_render_t063.py` içinde.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
if str(KOK) not in sys.path:
	sys.path.insert(0, str(KOK))

from tradehub_core.media.pipeline.image import render as R  # noqa: E402
from tradehub_core.media.pipeline.image import report as REP  # noqa: E402
from tradehub_core.media.pipeline.image import reprocess as RP  # noqa: E402

FIXTURE = KOK / "tradehub_core" / "tests" / "fixtures" / "media" / "images"
SLOT_DIR = KOK / "tradehub_core" / "media" / "pipeline" / "policy" / "slots"


def _pil():
	from PIL import Image

	return Image


def _lcg(seed: int):
	"""Bağımlılıksız, tekrarlanabilir sözde-rastgele üreteç (random/numpy'a bağlı değil)."""
	durum = seed & 0x7FFFFFFF
	while True:
		durum = (1103515245 * durum + 12345) & 0x7FFFFFFF
		yield durum


def gurultu(w: int, h: int, seed: int = 7):
	"""Sıkıştırılamaz görsel — fayda kapısını tetiklemek için."""
	Image = _pil()
	g = _lcg(seed)
	piksel = [((next(g) >> 15) % 256, (next(g) >> 15) % 256, (next(g) >> 15) % 256) for _ in range(w * h)]
	im = Image.new("RGB", (w, h))
	im.putdata(piksel)
	return im


def gradyan(w: int, h: int, alfa: bool = False):
	"""Sıkıştırılabilir, yumuşak görsel — normal üretim yolu için."""
	Image = _pil()
	im = Image.new("RGBA" if alfa else "RGB", (w, h))
	pks = im.load()
	for y in range(h):
		for x in range(w):
			r = (x * 255) // max(1, w - 1)
			b = (y * 255) // max(1, h - 1)
			if alfa:
				pks[x, y] = (r, 128, b, 255 if x > w // 2 else 0)
			else:
				pks[x, y] = (r, 128, b)
	return im


def kaydet(im, fmt: str = "JPEG", **kw) -> bytes:
	buf = io.BytesIO()
	im.save(buf, fmt, **kw)
	return buf.getvalue()


def profil(**kw) -> R.RenditionProfile:
	"""Test için sentetik profil. Politikaya dokunmadan tek değişken denenir."""
	veri = {
		"name": "t",
		"width": 128,
		"formats": ["webp"],
		"encoder_quality": {"webp": 80},
		"fit": "contain",
	}
	veri.update(kw)
	return R.RenditionProfile.from_dict(kw.pop("slot_key", "product.image"), veri)


# ---------------------------------------------------------------------------
# 1) Matris VERİDİR
# ---------------------------------------------------------------------------


class MatrisVeriTesti(unittest.TestCase):
	"""Profil matrisi JSON'dan okunmalı; modülde gömülü genişlik OLMAMALI."""

	def test_profiller_json_ile_birebir(self):
		for yol in sorted(SLOT_DIR.glob("*.json")):
			ham = json.loads(yol.read_text(encoding="utf-8"))
			slot = ham["slot_key"]
			bekleyen = [(p["name"], int(p["width"]), tuple(p["formats"])) for p in ham["profiles"]]
			gelen = [(p.name, p.width, p.formats) for p in R.load_profiles(slot)]
			self.assertEqual(gelen, bekleyen, f"{slot}: profiller JSON'dan sapmış")

	def test_matris_boyutu_json_toplamiyla_ayni(self):
		toplam = 0
		for yol in sorted(SLOT_DIR.glob("*.json")):
			ham = json.loads(yol.read_text(encoding="utf-8"))
			toplam += sum(len(p["formats"]) for p in ham["profiles"])
		self.assertEqual(R.matrix_size()["_toplam"], toplam)

	def test_kodda_gomulu_genislik_yok(self):
		"""Genişlikler koda yazılmış olsaydı bu liste kaynak dosyada geçerdi."""
		kaynak = (KOK / "tradehub_core" / "media" / "pipeline" / "image" / "render.py").read_text(
			encoding="utf-8"
		)
		gövde = kaynak.split('"""', 2)[-1]  # modül docstring'i hariç
		for w in ("96", "192", "384", "640", "768", "1280", "1920"):
			self.assertNotIn(f"width={w}", gövde)
			self.assertNotIn(f'"{w}"', gövde.replace('"1.0.0"', ""))

	def test_gizli_dosyalar_politika_sayilmaz(self):
		"""KUSUR REGRESYONU: AppleDouble artığı (`._x.json`) motoru komple durduruyordu.

		macOS'tan `docker cp` ile kopyalanan ağaçta `slots/` altına `._*.json`
		düşüyor; bunlar UTF-8 değil. Eskiden `_slot_files()` bunları okumaya
		çalışıp UnicodeDecodeError veriyordu ve 9 slotun 9'u da açılamıyordu.
		"""
		artik = SLOT_DIR / "._test_artigi.json"
		artik.write_bytes(b"\x00\x05\x16\xa3 bu UTF-8 degil")
		try:
			R._slot_files.cache_clear()
			self.assertEqual(set(R.slot_keys()), set(R.matrix_size()) - {"_toplam"})
			self.assertTrue(R.load_profiles("product.image"))
		finally:
			artik.unlink()
			R._slot_files.cache_clear()

	def test_bilinmeyen_slot_hata_verir(self):
		with self.assertRaises(R.RenderError):
			R.load_profiles("yok.boyle.slot")

	def test_profile_for_ve_rendition_matrix(self):
		p = R.profile_for("product.image", "w640")
		self.assertEqual(p.width, 640)
		matris = R.rendition_matrix("product.image")
		self.assertEqual(len(matris), sum(len(x.formats) for x in R.load_profiles("product.image")))
		self.assertTrue(all(isinstance(f, str) for _, f in matris))

	def test_profil_dogrulamasi(self):
		with self.assertRaises(R.RenderError):
			profil(width=0)
		with self.assertRaises(R.RenderError):
			profil(fit="squish")
		with self.assertRaises(R.RenderError):
			profil(formats=[])


# ---------------------------------------------------------------------------
# 2) Geometri — encode YOK, saf aritmetik (hızlı)
# ---------------------------------------------------------------------------


class GeometriTesti(unittest.TestCase):
	def test_upscale_yasak_contain(self):
		"""FR-028: hedef kaynaktan genişse büyütme YAPILMAZ."""
		plan = R.plan_geometry((200, 200), profil(width=1920, fit="contain"))
		self.assertEqual(plan.canvas_size, (200, 200))
		self.assertTrue(plan.upscale_blocked)
		self.assertLessEqual(plan.scale, 1.0)

	def test_upscale_yasak_pad_tuvali_de_kucultur(self):
		"""Dolgu kutusu şişip içerik ortada minik kalmamalı — tuval de küçülür."""
		p = profil(width=1920, fit="pad", target_ratio="1:1", pad_color="#FFFFFF")
		plan = R.plan_geometry((300, 150), p)
		self.assertTrue(plan.upscale_blocked)
		self.assertEqual(plan.canvas_size[0], plan.canvas_size[1], "1:1 oranı bozulmuş")
		self.assertLessEqual(plan.canvas_size[0], 300)
		self.assertEqual(plan.inner_size, (300, 150))

	def test_pad_hedef_orani_kurar(self):
		p = profil(width=640, fit="pad", target_ratio="1:1")
		plan = R.plan_geometry((2400, 1200), p)
		self.assertEqual(plan.canvas_size, (640, 640))
		self.assertEqual(plan.inner_size, (640, 320))
		self.assertTrue(plan.padded)
		self.assertEqual(plan.paste_at, (0, 160))

	def test_contain_orani_korur_dolgu_yok(self):
		plan = R.plan_geometry((2400, 1200), profil(width=600, fit="contain"))
		self.assertEqual(plan.canvas_size, (600, 300))
		self.assertEqual(plan.inner_size, plan.canvas_size)
		self.assertFalse(plan.padded)

	def test_cover_hedef_orana_kirpar(self):
		p = profil(width=600, fit="cover", target_ratio="1:1")
		plan = R.plan_geometry((2400, 1200), p)
		self.assertEqual(plan.canvas_size, (600, 600))
		_, _, cw, ch = plan.crop_box
		self.assertAlmostEqual(cw / ch, 1.0, places=2)
		self.assertLess(cw, 2400)

	def test_olcek_asla_birin_uzerinde_olmaz(self):
		for w in (16, 64, 256, 1024, 4096):
			for fit in ("contain", "cover", "pad"):
				p = profil(width=w, fit=fit, target_ratio="1:1")
				plan = R.plan_geometry((500, 500), p)
				self.assertLessEqual(plan.scale, 1.0 + 1e-9, f"{fit}/{w} büyütme yaptı")

	def test_sifir_boyut_hata(self):
		with self.assertRaises(R.RenderError):
			R.plan_geometry((0, 100), profil())

	def test_kirpma_niyeti_pencereyi_kaydirir(self):
		"""`crop_intent` gerçekten uygulanıyor mu — cover'da odak noktası."""
		p = profil(width=400, fit="cover", target_ratio="1:1")
		sol = R.plan_geometry((2000, 1000), p, {"focal_x": 0.05, "focal_y": 0.5})
		sag = R.plan_geometry((2000, 1000), p, {"focal_x": 0.95, "focal_y": 0.5})
		self.assertLess(sol.crop_box[0], sag.crop_box[0], "odak noktası pencereyi kaydırmadı")


# ---------------------------------------------------------------------------
# 3) Yeniden örnekleme
# ---------------------------------------------------------------------------


class YenidenOrneklemeTesti(unittest.TestCase):
	def test_lanczos3_kullaniliyor(self):
		Image = _pil()
		im = gradyan(64, 64)
		self.assertEqual(
			R.resize_premultiplied(im, (32, 32)).tobytes(),
			im.resize((32, 32), Image.LANCZOS).tobytes(),
		)

	def test_ayni_olcu_kopyalanir(self):
		im = gradyan(20, 20)
		out = R.resize_premultiplied(im, (20, 20))
		self.assertEqual(out.size, (20, 20))
		self.assertIsNot(out, im)

	def test_premultiplied_alfa_halo_uretmez(self):
		"""Şeffaf alandaki gizli SİYAH, opak beyaz kenara sızmamalı."""
		Image = _pil()
		im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))  # şeffaf + gizli siyah
		for y in range(64):
			for x in range(32, 64):
				im.putpixel((x, y), (255, 255, 255, 255))  # opak beyaz yarı
		kucuk = R.resize_premultiplied(im, (32, 32))
		self.assertEqual(kucuk.mode, "RGBA")
		# Tamamen opak bölgenin ortası hâlâ beyaz olmalı (halo = kararma).
		r, g, b, a = kucuk.getpixel((28, 16))
		self.assertEqual(a, 255)
		self.assertGreaterEqual(min(r, g, b), 250, f"halo tespit edildi: {(r, g, b)}")

	def test_alfasiz_gorselde_mod_degismez(self):
		self.assertEqual(R.resize_premultiplied(gradyan(40, 40), (20, 20)).mode, "RGB")


# ---------------------------------------------------------------------------
# 4) Kaynak hazırlığı (mod normalleştirme)
# ---------------------------------------------------------------------------


class KaynakHazirligiTesti(unittest.TestCase):
	def test_cmyk_srgbye_cevrilir_ve_icc_dusurulur(self):
		Image = _pil()
		veri = kaydet(Image.new("CMYK", (32, 32), (10, 20, 30, 5)), "JPEG")
		im, icc, notlar = R.prepare_source(veri)
		self.assertEqual(im.mode, "RGB")
		self.assertIsNone(icc)
		self.assertIn(R.NOTE_CMYK_TO_SRGB, notlar)

	def test_palet_alfali_rgbaya_acilir(self):
		Image = _pil()
		p = Image.new("P", (16, 16))
		p.info["transparency"] = 0
		im, _icc, notlar = R.prepare_source(kaydet(p, "PNG", transparency=0))
		self.assertEqual(im.mode, "RGBA")
		self.assertIn(R.NOTE_PALETTE_EXPANDED, notlar)

	def test_gri_rgbye_cevrilir(self):
		Image = _pil()
		im, _icc, _n = R.prepare_source(kaydet(Image.new("L", (16, 16), 128), "PNG"))
		self.assertEqual(im.mode, "RGB")

	def test_pad_color_ayristirma(self):
		self.assertEqual(R.parse_pad_color("#FFFFFF"), (255, 255, 255, 255))
		self.assertEqual(R.parse_pad_color("#f00"), (255, 0, 0, 255))
		self.assertEqual(R.parse_pad_color("transparent"), (0, 0, 0, 0))
		for kotu in ("beyaz", "#12345", "#GGGGGG"):
			with self.assertRaises((R.RenderError, ValueError), msg=kotu):
				R.parse_pad_color(kotu)


# ---------------------------------------------------------------------------
# 5) Encode
# ---------------------------------------------------------------------------


class EncodeTesti(unittest.TestCase):
	def setUp(self):
		self.im = gradyan(64, 64)

	def test_deterministik(self):
		for fmt in ("webp", "jpeg", "png"):
			a, _ = R.encode(self.im, fmt, 80)
			b, _ = R.encode(self.im, fmt, 80)
			self.assertEqual(a, b, f"{fmt} deterministik değil")

	def test_kalite_baytı_degistirir(self):
		dusuk, _ = R.encode(self.im, "webp", 40)
		yuksek, _ = R.encode(self.im, "webp", 95)
		self.assertLess(len(dusuk), len(yuksek))

	def test_jpeg_alfayi_duzlestirir_ve_notlar(self):
		veri, notlar = R.encode(gradyan(32, 32, alfa=True), "jpeg", 80, pad_color="#FFFFFF")
		self.assertIn(R.NOTE_ALPHA_FLATTENED, notlar)
		Image = _pil()
		with Image.open(io.BytesIO(veri)) as im:
			self.assertEqual(im.mode, "RGB")

	def test_webp_alfayi_korur(self):
		veri, notlar = R.encode(gradyan(32, 32, alfa=True), "webp", 80)
		self.assertNotIn(R.NOTE_ALPHA_FLATTENED, notlar)
		Image = _pil()
		with Image.open(io.BytesIO(veri)) as im:
			self.assertIn("A", im.mode)

	def test_kayipsiz_kip(self):
		veri, notlar = R.encode(self.im, "webp", R.LOSSLESS)
		self.assertIn(R.NOTE_LOSSLESS, notlar)
		Image = _pil()
		with Image.open(io.BytesIO(veri)) as im:
			self.assertEqual(im.convert("RGB").tobytes(), self.im.tobytes())

	def test_desteklenmeyen_bicim(self):
		with self.assertRaises(R.RenderError):
			R.encode(self.im, "bmp", 80)

	def test_verify_bozuk_bayti_yakalar(self):
		self.assertTrue(R._verify(R.encode(self.im, "webp", 80)[0]))
		self.assertFalse(R._verify(b"bunlar gorsel degil"))


# ---------------------------------------------------------------------------
# 6) INV-05 fayda kapısı
# ---------------------------------------------------------------------------


class FaydaKapisiTesti(unittest.TestCase):
	"""Çıktı kaynaktan küçük DEĞİLSE o türev atılır — dosya büyüten türev yazılmaz."""

	def setUp(self):
		# Gürültü + düşük kalite JPEG: yeniden encode her zaman büyütür.
		self.kucuk_kaynak = kaydet(gurultu(96, 96, seed=7), "JPEG", quality=15, optimize=True)

	def test_zincir_tukenirse_kaynak_gecer(self):
		p = R.profile_for("product.image", "w96")
		r = R.render_rendition(self.kucuk_kaynak, p)
		self.assertTrue(r.passthrough)
		self.assertEqual(r.content, self.kucuk_kaynak)
		self.assertIn(R.NOTE_PASSTHROUGH, r.notes)
		self.assertTrue(all(not a.accepted for a in r.attempts))
		self.assertTrue(all(a.reason == "no_benefit_vs_source" for a in r.attempts))

	def test_hicbir_turev_kaynaktan_buyuk_degil(self):
		p = R.profile_for("product.image", "w96")
		r = R.render_rendition(self.kucuk_kaynak, p)
		self.assertLessEqual(r.size_bytes, len(self.kucuk_kaynak))

	def test_zincir_bir_alta_duser(self):
		"""İlk biçim kapıdan dönerse ikinci biçim denenir — türev yine üretilir."""
		kaynak = kaydet(gurultu(256, 256, seed=11), "JPEG", quality=45, optimize=True)
		p = profil(width=128, formats=["png", "webp"], encoder_quality={"png": None, "webp": 80})
		r = R.render_rendition(kaynak, p)
		self.assertFalse(r.passthrough)
		self.assertEqual(r.format, "webp")
		self.assertEqual([a.format for a in r.attempts], ["png", "webp"])
		self.assertEqual(r.attempts[0].reason, "no_benefit_vs_source")
		self.assertTrue(r.attempts[1].accepted)

	def test_passthrough_yasaklanabilir(self):
		p = R.profile_for("product.image", "w96")
		with self.assertRaises(R.RenderError):
			R.render_rendition(self.kucuk_kaynak, p, allow_passthrough=False)


# ---------------------------------------------------------------------------
# 7) Adaptif kalite
# ---------------------------------------------------------------------------


class AdaptifKaliteTesti(unittest.TestCase):
	def setUp(self):
		self.kaynak = kaydet(gradyan(400, 400), "JPEG", quality=95)

	def test_encode_butcesi_asilmaz(self):
		p = R.profile_for("product.image", "w192")
		for butce in (1, 2, 4):
			r = R.render_rendition(self.kaynak, p, max_encodes=butce)
			self.assertLessEqual(r.encodes, butce, f"bütçe {butce} aşıldı: {r.encodes}")

	def test_varsayilan_butce_dort(self):
		self.assertEqual(R.DEFAULT_MAX_ENCODES, 4)

	def test_hedef_ssim_politikadan_gelir(self):
		import tradehub_core.media.pipeline.quality.ssim as S

		self.assertEqual(
			R.resolve_target_ssim("product.image", "photo"), S.target_for("product.image", "photo")
		)

	def test_kalite_uydurulmaz(self):
		"""Hedef SSIM de kalibre kalite de yoksa modül sayı UYDURMAZ, hata verir."""
		p = profil(formats=["webp"], encoder_quality={"webp": None})
		with self.assertRaises(R.RenderError) as ctx:
			R.render_rendition(self.kaynak, p, target_ssim=0.0, allow_passthrough=False)
		self.assertIn("uydurulamaz", str(ctx.exception))
		# Passthrough açıkken hata yutulmaz, GÖRÜNÜR olur: gerekçe künyeye yazılır.
		r = R.render_rendition(self.kaynak, p, target_ssim=0.0)
		self.assertTrue(r.passthrough)
		self.assertIn("uydurulamaz", r.attempts[0].reason)

	def test_kalibre_kalite_hedef_yokken_kullanilir(self):
		p = profil(formats=["webp"], encoder_quality={"webp": 77})
		r = R.render_rendition(self.kaynak, p, target_ssim=0.0)
		self.assertEqual(r.quality, 77)
		self.assertEqual(r.encodes, 1)
		self.assertIn(R.NOTE_SSIM_UNKNOWN, r.notes)

	def test_bilinmeyen_slot_reddedilir(self):
		"""Politikada olmayan slot sessizce varsayılana düşmez."""
		with self.assertRaises(R.RenderError):
			R.render_rendition(self.kaynak, profil(slot_key="yok.slot"))


# ---------------------------------------------------------------------------
# 8) render() sözleşmesi ve merdiven
# ---------------------------------------------------------------------------


class RenderSozlesmesiTesti(unittest.TestCase):
	def setUp(self):
		self.kaynak = kaydet(gradyan(600, 600), "JPEG", quality=95)

	def test_imza_bayt_dondurur(self):
		"""Görev sözleşmesi: render(source, profile, crop_intent) → bytes."""
		veri = R.render(self.kaynak, R.profile_for("product.image", "w192"), None)
		self.assertIsInstance(veri, bytes)
		self.assertTrue(R._verify(veri))

	def test_ayni_girdi_ayni_bayt(self):
		p = R.profile_for("product.image", "w192")
		self.assertEqual(R.render(self.kaynak, p, None), R.render(self.kaynak, p, None))

	def test_dosya_yolu_da_kabul_edilir(self):
		yol = FIXTURE / "ok_product_1x1_2400.jpg"
		if not yol.is_file():
			self.skipTest("fixture yok")
		im, _icc, _n = R.prepare_source(yol)
		self.assertEqual(im.size, (2400, 2400))

	def test_merdiven_profil_basina_bir_turev(self):
		sonuc = R.render_ladder(self.kaynak, "product.image")
		beklenen = [p for p in R.load_profiles("product.image") if p.width <= 600]
		self.assertEqual(len(sonuc), len(beklenen))
		self.assertEqual([r.profile.name for r in sonuc], [p.name for p in beklenen])

	def test_merdiven_yetersiz_kaynaktan_basamak_uretmez(self):
		"""INV-01: clamp edilmiş sahte basamak değil, gerçek omission gerekir."""
		kucuk = kaydet(gradyan(160, 160), "JPEG", quality=95)
		sonuc = R.render_ladder(kucuk, "product.image")
		self.assertEqual([r.profile.width for r in sonuc], [96])
		self.assertTrue(all(not r.upscale_blocked for r in sonuc))

	def test_merdiven_per_format_matrisin_tamami(self):
		sonuc = R.render_ladder(self.kaynak, "brand.logo", per_format=True)
		beklenen = [
			(p, f) for p, f in R.rendition_matrix("brand.logo") if R.profile_is_eligible((600, 600), p)
		]
		self.assertEqual(len(sonuc), len(beklenen))

	def test_merdiven_bicim_zorlanabilir(self):
		alt = R.load_profiles("product.image")[:3]
		sonuc = R.render_ladder(self.kaynak, "product.image", formats=("webp",), profiles=alt)
		self.assertEqual(len(sonuc), 3)
		self.assertTrue(all(r.format == "webp" for r in sonuc))

	def test_merdiven_desteklenmeyen_bicim_hata(self):
		with self.assertRaises(R.RenderError):
			R.render_ladder(self.kaynak, "brand.logo", formats=("gif",))

	def test_ladder_totals(self):
		sonuc = R.render_ladder(self.kaynak, "brand.logo")
		t = R.ladder_totals(sonuc)
		self.assertEqual(t["count"], len(sonuc))
		self.assertEqual(t["bytes"], sum(r.size_bytes for r in sonuc))
		self.assertEqual(R.ladder_totals([])["count"], 0)

	def test_sonuc_kunyesi_json_lanabilir(self):
		r = R.render_rendition(self.kaynak, R.profile_for("product.image", "w96"))
		json.dumps(r.as_dict(), ensure_ascii=False)
		self.assertEqual(r.name, f"{r.profile.name}.{r.format}")
		self.assertTrue(r.filename_suffix.startswith("_w96"))
		self.assertGreater(r.saving_ratio, 0.0)


# ---------------------------------------------------------------------------
# 9) T-064 — idempotensi
# ---------------------------------------------------------------------------


class TuretmeAnahtariTesti(unittest.TestCase):
	def setUp(self):
		self.p = R.profile_for("product.image", "w96")
		self.ortak = dict(master_sha256="a" * 64, slot_key="product.image", profile_name="w96", fmt="webp")

	def test_ayni_girdi_ayni_anahtar(self):
		self.assertEqual(RP.derivation_key(**self.ortak), RP.derivation_key(**self.ortak))

	def test_her_alan_anahtari_degistirir(self):
		taban = RP.derivation_key(**self.ortak)
		for alan, yeni in (
			("master_sha256", "b" * 64),
			("slot_key", "brand.logo"),
			("profile_name", "w192"),
			("fmt", "avif"),
		):
			self.assertNotEqual(RP.derivation_key(**dict(self.ortak, **{alan: yeni})), taban, alan)
		self.assertNotEqual(RP.derivation_key(**self.ortak, crop_sig="x"), taban)

	def test_motor_surumu_anahtara_katilir(self):
		self.assertNotEqual(
			RP.derivation_key(**self.ortak, engine_version="9.9.9"),
			RP.derivation_key(**self.ortak),
		)

	def test_kirpma_imzasi_anahtar_sirasindan_bagimsiz(self):
		self.assertEqual(RP.crop_signature({"x": 1, "y": 2}), RP.crop_signature({"y": 2, "x": 1}))
		self.assertEqual(RP.crop_signature(None), "")
		self.assertNotEqual(RP.crop_signature({"x": 1}), RP.crop_signature({"x": 2}))


class DefterTesti(unittest.TestCase):
	def setUp(self):
		self.kaynak = kaydet(gradyan(400, 400), "JPEG", quality=95)
		self.p = R.profile_for("product.image", "w96")

	def test_ikinci_kosum_encode_etmez(self):
		defter = RP.RenditionLedger()
		r1, k1 = RP.render_idempotent(self.kaynak, self.p, ledger=defter)
		self.assertEqual(k1.action, RP.ACTION_RENDER)
		self.assertIsNotNone(r1)
		r2, k2 = RP.render_idempotent(self.kaynak, self.p, ledger=defter)
		self.assertEqual(k2.action, RP.ACTION_SKIP)
		self.assertIsNone(r2, "atlanması gereken türev yeniden üretildi")
		self.assertFalse(k2.should_render)

	def test_force_atlamayi_bozar(self):
		defter = RP.RenditionLedger()
		RP.render_idempotent(self.kaynak, self.p, ledger=defter)
		r, k = RP.render_idempotent(self.kaynak, self.p, ledger=defter, force=True)
		self.assertEqual(k.action, RP.ACTION_RENDER)
		self.assertIsNotNone(r)

	def test_bayat_motor_surumu_tazelenir(self):
		defter = RP.RenditionLedger()
		r, _ = RP.render_idempotent(self.kaynak, self.p, ledger=defter)
		kayit = defter.records()[0]
		# Motor sürümü değişmiş gibi davran: anahtarı düşür, kaydı bırak.
		defter.by_key.clear()
		bayat = RP.RenditionRecord(**dict(vars(kayit), engine_version="0.0.1"))
		defter.by_key[bayat.key] = bayat
		karar = RP.decide(
			master_sha256=RP.content_hash(self.kaynak),
			profile=self.p,
			fmt=self.p.formats[0],
			ledger=defter,
		)
		self.assertIn(karar.action, (RP.ACTION_REFRESH, RP.ACTION_SKIP))

	def test_defter_json_gidis_donus(self):
		defter = RP.RenditionLedger()
		RP.render_idempotent(self.kaynak, self.p, ledger=defter)
		geri = RP.RenditionLedger.from_json(defter.to_json())
		self.assertEqual(len(geri), len(defter))
		self.assertEqual({r.sha256 for r in geri.records()}, {r.sha256 for r in defter.records()})

	def test_motor_ciktisi_kaynak_olarak_reddedilir(self):
		defter = RP.RenditionLedger()
		r, _ = RP.render_idempotent(self.kaynak, self.p, ledger=defter)
		hukum = RP.is_engine_output(r.content, defter)
		self.assertTrue(hukum.is_output)
		self.assertEqual(hukum.confidence, RP.CONFIDENCE_EXACT)
		self.assertTrue(hukum.proven)
		with self.assertRaises(RP.ReprocessError):
			RP.render_idempotent(r.content, self.p, ledger=defter)

	def test_yapisal_sezgi_kanit_degil(self):
		"""Defter yoksa hüküm en fazla `heuristic` olabilir — kanıt diye sunulmaz."""
		veri, _ = R.encode(gradyan(96, 96), "webp", 80)
		hukum = RP.is_engine_output(veri, None)
		self.assertIn(hukum.confidence, (RP.CONFIDENCE_HEURISTIC, RP.CONFIDENCE_NONE))
		self.assertFalse(hukum.proven)

	def test_jpeg_motor_ciktisi_sayilmaz(self):
		"""Canlının %75,5'i JPEG — JPEG'i türev saymak pahalı bir yanlış pozitif."""
		self.assertNotIn("JPEG", RP.ENGINE_OUTPUT_FORMATS)
		hukum = RP.is_engine_output(self.kaynak, None)
		self.assertFalse(hukum.is_output)

	def test_merdiven_idempotent(self):
		defter = RP.RenditionLedger()
		s1, k1 = RP.render_ladder_idempotent(self.kaynak, "brand.logo", ledger=defter)
		self.assertTrue(all(k.action == RP.ACTION_RENDER for k in k1))
		s2, k2 = RP.render_ladder_idempotent(self.kaynak, "brand.logo", ledger=defter)
		self.assertEqual(s2, [], "ikinci koşuda yeniden üretim oldu")
		self.assertTrue(all(k.action == RP.ACTION_SKIP for k in k2))
		beklenen = [
			(p, f) for p, f in R.rendition_matrix("brand.logo") if R.profile_is_eligible((400, 400), p)
		]
		self.assertEqual(len(s1), len(beklenen))

	def test_passthrough_masteri_zehirlemez(self):
		"""KUSUR REGRESYONU: passthrough kaydı master'ı 'motor çıktısı' ilan ediyordu.

		INV-05 zinciri tükendiğinde kaynak olduğu gibi geçer ve kaydın sha256'sı
		master'ın kendisidir. Bu kayıt içerik indeksine yazılırsa bir sonraki
		profil aynı master'ı verdiğinde `assert_not_engine_output` merdiveni
		ortasından koparıyordu.
		"""
		kucuk = kaydet(gurultu(128, 128, seed=3), "JPEG", quality=12, optimize=True)
		defter = RP.RenditionLedger()
		sonuclar, kararlar = RP.render_ladder_idempotent(kucuk, "product.image", ledger=defter)
		self.assertTrue(any(r.passthrough for r in sonuclar), "passthrough kurulamadı")
		self.assertTrue(all(k.action == RP.ACTION_RENDER for k in kararlar))
		self.assertIsNone(defter.by_sha(RP.content_hash(kucuk)))
		# Master hâlâ meşru bir kaynak olmalı.
		RP.assert_not_engine_output(kucuk, defter)

	def test_nesil_kaybi_olculur(self):
		"""Korumanın gerekçesi: tekrar encode bilgi yok ediyor mu — ÖLÇÜLÜR."""
		p = R.profile_for("product.image", "w96")
		satirlar = RP.generation_loss(self.kaynak, p, rounds=3)
		self.assertGreaterEqual(len(satirlar), 2)
		self.assertEqual(satirlar[0]["ssim_vs_original"], 1.0)
		for s in satirlar[1:]:
			if "ssim_vs_original" in s:
				self.assertLessEqual(s["ssim_vs_original"], 1.0)


class SecmeliYenidenIslemeTesti(unittest.TestCase):
	"""Crop değişikliği yalnız piksel planı gerçekten değişen profilleri seçer."""

	def setUp(self):
		self.contain = profil(name="contain", width=400, fit="contain", target_ratio="")
		self.cover = profil(name="cover", width=400, fit="cover", target_ratio="1:1")

	def test_yalniz_odak_degisiminde_contain_atlanir(self):
		eski = {"focal_x": 0.1, "focal_y": 0.5}
		yeni = {"focal_x": 0.9, "focal_y": 0.5}
		etkilenen = RP.affected_profile_names((1200, 800), (self.contain, self.cover), eski, yeni)
		self.assertEqual(etkilenen, ("cover",))

	def test_zoom_degisiminde_contain_de_etkilenir(self):
		eski = {"zoom": 1.0, "center_x": 0.5, "center_y": 0.5}
		yeni = {"zoom": 2.0, "center_x": 0.5, "center_y": 0.5}
		etkilenen = RP.affected_profile_names((1200, 800), (self.contain, self.cover), eski, yeni)
		self.assertIn("contain", etkilenen)


# ---------------------------------------------------------------------------
# 10) T-066 — kalite raporu
# ---------------------------------------------------------------------------


class RaporTesti(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.kaynak = kaydet(gradyan(500, 500), "JPEG", quality=95)
		# İlk üç profil: süiti hızlı tutar, SSIM yolu (product.image = ssim) çalışır.
		cls.alt = R.load_profiles("product.image")[:3]
		cls.sonuclar = R.render_ladder(cls.kaynak, "product.image", profiles=cls.alt)
		cls.rapor = REP.build_report(cls.kaynak, cls.sonuclar, slot_key="product.image", asset_id="TEST-1")

	def test_json_lanabilir_ve_semali(self):
		json.dumps(self.rapor, ensure_ascii=False)
		for alan in (
			"schema_version",
			"engine",
			"asset",
			"slot",
			"policy",
			"renditions",
			"totals",
			"quality",
			"findings",
			"verdict",
			"summary_tr",
		):
			self.assertIn(alan, self.rapor)

	def test_toplamlar_gercek(self):
		self.assertEqual(self.rapor["totals"]["count"], len(self.sonuclar))
		self.assertEqual(self.rapor["totals"]["bytes"], sum(r.size_bytes for r in self.sonuclar))
		self.assertEqual(self.rapor["policy"]["profiles_defined"], len(R.load_profiles("product.image")))

	def test_olculmeyen_alan_null_kalir_sifir_degil(self):
		"""SSIM hedefi olmayan slotta `ssim_min` 0 değil None olmalı."""
		kaynak = kaydet(gradyan(300, 300), "JPEG", quality=95)
		p = profil(formats=["webp"], encoder_quality={"webp": 80})
		r = R.render_rendition(kaynak, p, target_ssim=0.0)
		self.assertEqual(r.ssim, 0.0)
		rapor = REP.build_report(kaynak, [r], slot_key="")
		self.assertIsNone(rapor["quality"]["ssim_min"])
		self.assertEqual(rapor["quality"]["measured_count"], 0)
		self.assertEqual(rapor["quality"]["unmeasured_count"], 1)

	def test_ozet_turkce_ve_sayilari_tasir(self):
		metin = REP.summarize_tr(self.rapor)
		self.assertIn("Slot", metin)
		self.assertIn("türev", metin)
		self.assertIn("Karar", metin)
		self.assertIn(str(len(self.sonuclar)), metin)

	def test_bos_rapor_da_uretilir(self):
		rapor = REP.build_report(self.kaynak, [], slot_key="product.image")
		self.assertEqual(rapor["totals"]["count"], 0)
		self.assertIsNone(rapor["totals"]["largest"])
		self.assertIsInstance(REP.summarize_tr(rapor), str)

	def test_karar_bulgu_siddetinden_turer(self):
		self.assertEqual(REP.verdict({"findings": []}), "ok")
		self.assertEqual(REP.verdict({"findings": [{"severity": "warn"}]}), "warn")
		self.assertEqual(REP.verdict({"findings": [{"severity": "warn"}, {"severity": "error"}]}), "fail")

	def test_under_spec_bulgusu_uretilir(self):
		"""Tek-türev tanısı under-spec'i raporlar; üretim merdiveni onu atlar."""
		kucuk = kaydet(gradyan(48, 48), "PNG")
		sonuc = [R.render_rendition(kucuk, R.profile_for("brand.logo", "w64"))]
		rapor = REP.build_report(kucuk, sonuc, slot_key="brand.logo")
		kodlar = {f["code"] for f in rapor["findings"]}
		self.assertTrue(
			{"under_spec", "passthrough"} & kodlar,
			f"küçük kaynakta beklenen bulgu yok: {kodlar}",
		)

	def test_not_kodlari_turkceye_cevrilir(self):
		for kod in (R.NOTE_UNDER_SPEC, R.NOTE_PASSTHROUGH, R.NOTE_QUALITY_FLOOR):
			self.assertNotEqual(REP._tr_note(kod), kod, f"{kod} çevirisi yok")

	def test_rapor_diske_yazilir(self):
		import tempfile

		with tempfile.TemporaryDirectory() as d:
			yol = REP.write_report(Path(d) / "r.json", self.rapor)
			geri = json.loads(Path(yol).read_text(encoding="utf-8"))
			self.assertEqual(geri["totals"]["count"], self.rapor["totals"]["count"])

	def test_raporlar_birlestirilebilir(self):
		birlesik = REP.merge_reports([self.rapor, self.rapor])
		self.assertIsInstance(birlesik, dict)


if __name__ == "__main__":
	unittest.main(verbosity=2)

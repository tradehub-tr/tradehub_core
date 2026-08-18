"""T-062 — İçerik sınıflandırma testleri: 5 sınıf → biçim zinciri.

DOĞRULUK NEREDE ÖLÇÜLDÜ — ve neden fixture korpusunda ÖLÇÜLEMEZ
---------------------------------------------------------------
`tradehub_core/tests/fixtures/media/manifest.json` içindeki `class` alanı bir **içerik
sınıfı değil, fixture ailesi** etiketidir. Fixture'lar sentetik olarak
üretilmiş rastgele gürültüdür: `ok_product_1x1_2400.jpg` ("photo") ile
`geom_strip_400x4000.png` ("graphic") piksel istatistiği olarak AYNI şeydir.
"graphic" etiketi orada "bu fixture geometri kuralını sınar" demektir,
"bu görsel bir grafiktir" demez.

Bu yüzden içerik sınıflandırma doğruluğu **canlı korpustan** ölçüldü:

    Örneklem : 4.341 dosyadan rastgele 48 görsel (seed 4242, stratifiye DEĞİL)
    Etiket   : elle, kontak sayfalarına bakılarak (2026-08-18)
    Dağılım  : 44 photo · 4 graphic (#03, #13, #21, #31)
    SONUÇ    : **46/48 = %95,8**  ·  graphic kesinliği 2/2 = %100
    Kaçanlar : #03 (soluk çizim + damga), #31 (dokulu fonda kelime-marka)
    Süre     : p50 32 ms · p90 41 ms · en kötü 137 ms

DÜRÜST SINIR — bu %95,8 sağlam bir tahmin DEĞİLDİR:
  * 48 örnekte yalnız **4 pozitif** var. "Hep photo de" diyen boş bir
    sınıflandırıcı bile %91,7 alır; ölçülen üstünlük 2 dosyadan ibarettir.
  * Eşikler bu 4 pozitifin üzerinde kalibre edildi — aynı veride ölçülen
    doğruluk iyimserdir (in-sample).
  * `text` sınıfı için iki korpusta da **tek örnek yok**: eşikleri
    ÖLÇÜLMEDİ (`classify.TEXT_OLCULDU is False`).

Korpus büyüdüğünde `GRAPHIC_*` eşikleri yeniden kalibre edilmelidir.
Aşağıdaki testler bu yüzden doğruluğu değil, **eşik davranışını** ve
**sözleşmeyi** sabitler; canlı örneklem repoda olmadığı için yeniden
koşturulamaz, ölçüm sonucu belge olarak burada durur.

Çalıştırma:

    python3 -m unittest tests.test_image_classify -v
"""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.image import classify as C  # noqa: E402
from tradehub_core.media.pipeline.image.probe import GuardConfig  # noqa: E402

IMAGES = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "images"
MANIFEST = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "manifest.json"

GEVSEK = GuardConfig(max_megapixels=200.0, max_bytes=64 * 1024 * 1024, allow_animated=True)

#: Canlı örneklemde ÖLÇÜLEN doğruluk (yukarıdaki blok). Kod bu sayıyı
#: yeniden üretemez (görseller repoda değil); sabit, ölçümün kaydıdır.
CANLI_ORNEKLEM_N: int = 48
CANLI_ORNEKLEM_DOGRU: int = 46

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

	def test_kanit_yoksa_varsayilan_photo(self):
		sinif, _, gerekce = C.classify_features(_foto())

		self.assertEqual(sinif, C.SINIF_PHOTO)
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


class MetinSinifiTest(unittest.TestCase):
	"""`text` eşikleri ÖLÇÜLMEDİ — kodun bunu beyan ettiği doğrulanır."""

	def test_olculmedi_bayragi_dogru(self):
		self.assertFalse(C.TEXT_OLCULDU, "text eşikleri ölçüldüyse bu bayrak ve belge güncellenmeli")

	def test_metin_profili_text_verir(self):
		f = replace(
			_foto(),
			bilevel_ratio=0.95,
			edge_density=0.20,
			quantized_colors=8,
			saturation_mean=4.0,
			lossy_source=False,
		)
		sinif, guven, gerekce = C.classify_features(f)

		self.assertEqual(sinif, C.SINIF_TEXT)
		self.assertEqual(guven, "low")
		self.assertIn("UNVALIDATED_THRESHOLDS", gerekce)

	def test_text_sonucu_olculmedi_isaretlenir(self):
		"""`measured=False` — rapor katmanı bunu 'ölçülmedi' diye göstermeli."""
		self.assertFalse(
			C.Classification(klass=C.SINIF_TEXT, measured=C.TEXT_OLCULDU).measured,
		)


class BicimZinciriTest(unittest.TestCase):
	def test_her_sinifin_zinciri_var(self):
		for s in C.SINIFLAR:
			with self.subTest(sinif=s):
				self.assertTrue(C.FORMAT_CHAINS[s], f"{s} zinciri boş")

	def test_zincir_yetenege_gore_suzulur(self):
		yok = dict.fromkeys(("AVIF", "WEBP", "JPEG", "PNG", "GIF"), False)
		self.assertEqual(C.format_chain(C.SINIF_PHOTO, yok), ())

		yalniz_jpeg = {**yok, "JPEG": True}
		zincir = C.format_chain(C.SINIF_PHOTO, yalniz_jpeg)
		self.assertEqual([a.fmt for a in zincir], ["JPEG"])

	def test_saydam_zinciri_alfa_yetenegi_ister(self):
		"""JPEG alfa taşıyamaz; alfa yeteneği yoksa adım elenmeli."""
		yetenek = {"WEBP": True, "WEBP:alpha": False, "PNG": True, "PNG:alpha": True}
		zincir = C.format_chain(C.SINIF_TRANSPARENT, yetenek)

		self.assertEqual([a.fmt for a in zincir], ["PNG"])

	def test_grafik_zincirinde_jpeg_yok(self):
		"""Keskin kenarda 4:2:0 renk altörneklemesi görünür kaçak bırakır."""
		self.assertNotIn("JPEG", [a.fmt for a in C.FORMAT_CHAINS[C.SINIF_GRAPHIC]])

	def test_grafik_ve_metin_kalite_yukseltmesi_alir(self):
		"""Kayıpsıza dallanmak yerine kalite yükseltilir (6,40x ölçümü)."""
		for s in (C.SINIF_GRAPHIC, C.SINIF_TEXT):
			with self.subTest(sinif=s):
				ilk = C.FORMAT_CHAINS[s][0]
				self.assertGreater(ilk.quality_bump, 0)
				self.assertFalse(ilk.lossless, "ilk adım kayıpsız olmamalı")

	def test_photo_zinciri_kayipsiz_icermez(self):
		for adim in C.FORMAT_CHAINS[C.SINIF_PHOTO]:
			self.assertFalse(adim.lossless, f"{adim.fmt} kayıpsız — fotoğrafta 7,86x pahalı")

	def test_yetenek_sondasi_calisir(self):
		yet = C.encoder_capabilities()
		self.assertTrue(yet["PNG"], "PNG kodlanamıyor — ortam bozuk")
		self.assertTrue(yet["JPEG"])
		self.assertIn("WEBP:animation", yet)


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

	def test_ayrilanlarin_hepsi_graphic_etiketli(self):
		"""Ayrımın tek kaynağı etiket anlamı farkı olmalı, başka sınıf kaymamalı."""
		etiket = {Path(f["file"]).name: f["class"] for f in _fixtures()}
		for ad in BEKLENEN_AYRIM:
			with self.subTest(dosya=ad):
				self.assertEqual(etiket[ad], "graphic")

	def test_canli_olcum_kaydi(self):
		"""Ölçümün kaydı — %95,8 hedefi tutmuştu."""
		oran = CANLI_ORNEKLEM_DOGRU / CANLI_ORNEKLEM_N
		self.assertGreaterEqual(oran, 0.95)


class SozlesmeTest(unittest.TestCase):
	def test_bozuk_girdi_istisna_atmaz(self):
		for girdi in (b"", b"\x00\x01", b"garbage"):
			with self.subTest(girdi=girdi[:6]):
				r = C.classify(girdi, filename="x.jpg")
				self.assertFalse(r.ok)
				self.assertEqual(r.klass, C.SINIF_PHOTO, "hata hâlinde bile güvenli varsayılan")

	def test_to_dict_serilestirilebilir(self):
		r = C.classify(IMAGES / "ok_product_4x5.jpg", guard=GEVSEK)
		json.dumps(r.to_dict())
		self.assertIn("chain", r.to_dict())

	def test_siniflar_listesi_bes(self):
		self.assertEqual(len(C.SINIFLAR), 5)

	def test_sonuc_hep_bilinen_sinif(self):
		for f in _fixtures():
			if f["class"] in ("malicious", "video"):
				continue
			with self.subTest(dosya=Path(f["file"]).name):
				r = C.classify(ROOT / f["file"], guard=GEVSEK)
				self.assertIn(r.klass, C.SINIFLAR)


if __name__ == "__main__":
	unittest.main(verbosity=2)

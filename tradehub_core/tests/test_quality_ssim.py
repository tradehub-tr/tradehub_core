"""T-013 — `tradehub_core/media/pipeline/quality/ssim.py` testleri.

Kapsam:
  * SSIM'in matematiksel özellikleri (özdeşlik, simetri, sınırlar, bozulmayla düşüş)
  * İki arka ucun (numpy / saf Python) AYNI sayıyı vermesi
  * İkili aramanın doğruluğu — sentetik, monoton bir encoder'la tüketici taramanın
    bulduğu gerçek minimumla karşılaştırılır (görselden bağımsız, deterministik)
  * Encode bütçesinin (`max_encodes`) aşılmaması
  * `master_reference` geometrisinin `engine.optimize` ile AYNI kalması (sürüklenme kilidi)
  * Politika hedeflerinin JSON'dan doğru okunması (uydurulmaması)

Koşum — site/bench/DB GEREKMEZ, yalnız Pillow:

    python3 -m unittest discover -s /Users/ahmet/Desktop/istoc/tradehub_core/tests -v

numpy yoksa saf Python arka ucu kullanılır; `test_arka_uc_uyumu` o durumda atlanır.
Testler bilerek KÜÇÜK görsellerle çalışır: saf Python arka ucu O(piksel) Python
döngüsüdür, büyük fixture'larla test koşumu dakikalara çıkardı.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
if str(KOK) not in sys.path:
	sys.path.insert(0, str(KOK))

from tradehub_core.media.pipeline.quality import (  # noqa: E402
	DEFAULT_MAX_ENCODES,
	compute_ssim,
	guess_content_class,
	master_reference,
	search_quality,
	target_for,
	to_luma,
)
from tradehub_core.media import engine  # noqa: E402

FIXTURE = KOK / "tradehub_core" / "tests" / "fixtures" / "media" / "images"


def _numpy_var() -> bool:
	try:
		import numpy  # noqa: F401

		return True
	except Exception:
		return False


def _lcg(seed: int):
	"""Bağımlılıksız, tekrarlanabilir sözde-rastgele üreteç (numpy/random'a bağlı değil)."""
	durum = seed & 0xFFFFFFFF
	while True:
		durum = (1103515245 * durum + 12345) & 0x7FFFFFFF
		yield durum


def _gradyan_gorsel(w: int = 96, h: int = 96):
	"""Deterministik, dokulu test görseli — düz alan değil ki SSIM anlamlı olsun."""
	from PIL import Image

	rnd = _lcg(7)
	pikseller = bytearray(w * h)
	for y in range(h):
		for x in range(w):
			taban = (x * 255) // max(1, w - 1)
			gurultu = next(rnd) % 17
			pikseller[y * w + x] = min(255, (taban + gurultu + (y % 32)) % 256)
	return Image.frombytes("L", (w, h), bytes(pikseller))


def _gurultulu_kopya(im, genlik: int, seed: int = 11):
	"""Referansa `genlik` kadar deterministik gürültü ekler. genlik=0 → özdeş kopya."""
	from PIL import Image

	if genlik <= 0:
		return im.copy()
	rnd = _lcg(seed)
	ham = bytearray(im.tobytes())
	for i in range(len(ham)):
		delta = (next(rnd) % (2 * genlik + 1)) - genlik
		ham[i] = max(0, min(255, ham[i] + delta))
	return Image.frombytes("L", im.size, bytes(ham))


def _png(im) -> bytes:
	buf = io.BytesIO()
	im.save(buf, "PNG")
	return buf.getvalue()


class SsimMatematigiTesti(unittest.TestCase):
	"""SSIM'in tanımdan gelen özellikleri."""

	def setUp(self):
		self.ref = _gradyan_gorsel()

	def test_ozdes_gorseller_bir_verir(self):
		sonuc = compute_ssim(self.ref, self.ref.copy())
		self.assertAlmostEqual(sonuc.value, 1.0, places=9)

	def test_simetrik(self):
		bozuk = _gurultulu_kopya(self.ref, 20)
		a = compute_ssim(self.ref, bozuk).value
		b = compute_ssim(bozuk, self.ref).value
		self.assertAlmostEqual(a, b, places=9)

	def test_bozulma_arttikca_dusr(self):
		degerler = [compute_ssim(self.ref, _gurultulu_kopya(self.ref, g)).value for g in (0, 5, 20, 60)]
		for onceki, simdiki in zip(degerler, degerler[1:]):
			self.assertLess(simdiki, onceki, f"SSIM bozulmayla düşmedi: {degerler}")

	def test_sinirlar_icinde(self):
		for genlik in (0, 10, 40, 100):
			deger = compute_ssim(self.ref, _gurultulu_kopya(self.ref, genlik)).value
			self.assertGreaterEqual(deger, -1.0)
			self.assertLessEqual(deger, 1.0 + 1e-9)

	def test_farkli_boyut_yeniden_olceklenir(self):
		"""Aday farklı boyuttaysa referans boyutuna getirilir, hata verilmez."""
		kucuk = self.ref.resize((48, 48))
		sonuc = compute_ssim(self.ref, kucuk)
		self.assertEqual((sonuc.width, sonuc.height), self.ref.size)
		self.assertLess(sonuc.value, 1.0)

	def test_pencere_sigmayan_gorsel_patlamaz(self):
		"""1×1 gibi dejenere girdide çökmeden bir sayı döner."""
		yol = FIXTURE / "geom_1x1.png"
		if not yol.is_file():
			self.skipTest("geom_1x1.png yok")
		icerik = yol.read_bytes()
		sonuc = compute_ssim(icerik, icerik)
		self.assertAlmostEqual(sonuc.value, 1.0, places=6)


class ArkaUcTesti(unittest.TestCase):
	"""numpy ve saf Python yolları aynı formülü uygular — sayıları ayrışamaz."""

	@unittest.skipUnless(_numpy_var(), "numpy yok; karşılaştırılacak ikinci arka uç bulunmuyor")
	def test_arka_uc_uyumu(self):
		ref = _gradyan_gorsel(64, 64)
		bozuk = _gurultulu_kopya(ref, 25)
		a = compute_ssim(ref, bozuk, backend=None, max_pixels=None)
		b = compute_ssim(ref, bozuk, backend="pure", max_pixels=None)
		self.assertEqual(a.backend, "numpy")
		self.assertEqual(b.backend, "pure")
		self.assertAlmostEqual(a.value, b.value, places=10)

	def test_alfa_beyaza_kompozit_edilir(self):
		"""RGBA görsel, aynı görselin beyaza düzleştirilmişiyle piksel-eş olmalı."""
		from PIL import Image

		rgba = Image.new("RGBA", (64, 64), (200, 30, 30, 128))
		duz = Image.new("RGB", (64, 64), (255, 255, 255))
		duz = Image.alpha_composite(duz.convert("RGBA"), rgba).convert("RGB")
		self.assertEqual(to_luma(_png(rgba)).tobytes(), to_luma(_png(duz)).tobytes())


class IkiliAramaTesti(unittest.TestCase):
	"""Aramanın doğruluğu — sentetik, monoton bir encoder'la yer gerçeğine karşı."""

	def setUp(self):
		self.ref = _gradyan_gorsel(80, 80)
		self.ref_bytes = _png(self.ref)

	def _sahte_encoder(self, content, max_dim, quality):
		"""Kalite arttıkça bozulmanın azaldığı deterministik encoder.

		Gerçek bir codec DEĞİL; amacı aramanın MANTIĞINI görselden ve Pillow
		sürümünden bağımsız sınamaktır. `genlik = 95 - quality` olduğu için SSIM
		kalitede kesin artandır — yer gerçeği tüketici taramayla hesaplanabilir.
		"""
		genlik = max(0, 95 - int(quality))
		return _png(_gurultulu_kopya(self.ref, genlik)), ""

	def _tuketici_tarama(self, hedef: float, aralik=(40, 95)):
		for q in range(aralik[0], aralik[1] + 1):
			cikti, _ = self._sahte_encoder(None, 0, q)
			if compute_ssim(self.ref, cikti).value >= hedef:
				return q
		return None

	def test_aramanin_buldugu_gercek_minimumla_ayni(self):
		for hedef in (0.90, 0.95, 0.98):
			gercek = self._tuketici_tarama(hedef)
			sonuc = search_quality(
				self.ref_bytes,
				target_ssim=hedef,
				max_dim=0,
				quality_range=(40, 95),  # yer gerçeği taramasıyla AYNI aralık
				encoder=self._sahte_encoder,
				reference=self.ref,
			)
			if gercek is None:
				self.assertFalse(sonuc.ok, f"hedef {hedef} ulaşılamazken arama ok dedi")
				continue
			self.assertTrue(sonuc.ok, f"hedef {hedef}: arama bulamadı ({sonuc.reason})")
			self.assertGreaterEqual(sonuc.ssim, hedef)
			# 4 encode ile 56 basamaklı aralıkta kalan belirsizlik: 56/2^4 = 3,5 basamak.
			self.assertLessEqual(
				sonuc.quality - gercek,
				4,
				f"hedef {hedef}: arama q={sonuc.quality}, gerçek min q={gercek}",
			)
			self.assertGreaterEqual(sonuc.quality, gercek)

	def test_varsayilan_aralik_olcumle_secildi(self):
		"""Varsayılan aralık (70,95): 4 encode bütçesinde q94'e kadar ERİŞİLEBİLİR olmalı.

		(40,95) aralığında ikili aramanın gezdiği kaliteler {67,81,88,92}'dir ve
		q93+ hedefleri bütçe içinde çözülemez — ölçüm §T-013.4'te.
		"""
		from tradehub_core.media.pipeline.quality import DEFAULT_QUALITY_RANGE

		self.assertEqual(DEFAULT_QUALITY_RANGE, (70, 95))
		lo, hi = DEFAULT_QUALITY_RANGE
		gezilen = []
		for _ in range(DEFAULT_MAX_ENCODES):
			if lo > hi:
				break
			q = (lo + hi) // 2
			gezilen.append(q)
			lo = q + 1  # hep "geçmedi" varsayımı → aramanın ulaşabildiği en yüksek uç
		self.assertGreaterEqual(max(gezilen), 94, f"erişilen en yüksek kalite: {gezilen}")

	def test_encode_butcesi_asilmaz(self):
		for butce in (1, 2, DEFAULT_MAX_ENCODES):
			sonuc = search_quality(
				self.ref_bytes,
				target_ssim=0.99,
				max_dim=0,
				max_encodes=butce,
				encoder=self._sahte_encoder,
				reference=self.ref,
			)
			self.assertLessEqual(sonuc.encodes, butce)

	def test_gecmeyen_denemeler_hedefin_altinda(self):
		sonuc = search_quality(
			self.ref_bytes,
			target_ssim=0.97,
			max_dim=0,
			encoder=self._sahte_encoder,
			reference=self.ref,
		)
		for deneme in sonuc.attempts:
			self.assertEqual(deneme.passed, deneme.ssim >= sonuc.target_ssim)

	def test_ulasilamayan_hedef_basari_saymaz(self):
		"""Hedef bütçe içinde tutmuyorsa modül sessizce 'oldu' dememeli."""
		sonuc = search_quality(
			self.ref_bytes,
			target_ssim=1.0,
			max_dim=0,
			encoder=self._sahte_encoder,
			reference=self.ref,
		)
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.reason, "target_unreachable_within_budget")
		self.assertTrue(sonuc.content, "en iyi aday yine de dönmeli")

	def test_encoder_hatasi_yayilir(self):
		def bozuk_encoder(content, max_dim, quality):
			return b"", "unsupported_format"

		sonuc = search_quality(
			self.ref_bytes,
			target_ssim=0.9,
			max_dim=0,
			encoder=bozuk_encoder,
			reference=self.ref,
		)
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.reason, "unsupported_format")
		self.assertEqual(sonuc.encodes, 1)


class GercekEncodeTesti(unittest.TestCase):
	"""Gerçek fixture + gerçek `engine.optimize` yolu."""

	def setUp(self):
		self.yol = FIXTURE / "logo_jpeg_noalpha.jpg"
		if not self.yol.is_file():
			self.skipTest("logo_jpeg_noalpha.jpg yok")
		self.icerik = self.yol.read_bytes()

	def test_yuksek_kalite_dusuk_kaliteden_iyi(self):
		ref = master_reference(self.icerik, 256)
		dusuk, _ = self._encode(256, 40)
		yuksek, _ = self._encode(256, 92)
		s_dusuk = compute_ssim(ref, dusuk).value
		s_yuksek = compute_ssim(ref, yuksek).value
		self.assertGreater(s_yuksek, s_dusuk)
		self.assertGreater(len(yuksek), len(dusuk))

	def _encode(self, max_dim, q):
		sonuc = engine.optimize(self.icerik, max_dim, q)
		self.assertTrue(sonuc.ok, sonuc.reason)
		return sonuc.content, sonuc

	def test_referans_geometrisi_engine_ile_ayni(self):
		"""`master_reference`, `engine.optimize`'ın ürettiği geometriyi birebir vermeli.

		Bu test bir SÜRÜKLENME KİLİDİdir: `engine.optimize` içindeki yeniden
		boyutlandırma değişirse (ör. `thumbnail` yerine `resize`), SSIM referansı
		sessizce yanlış görsele bakmaya başlardı.
		"""
		adaylar = [
			"logo_jpeg_noalpha.jpg",
			"ok_product_1x1_2400.jpg",
			"ok_product_4x5.jpg",
			"exif_orientation6.jpg",
			"enc_webp_lossy.webp",
		]
		bakilan = 0
		for ad in adaylar:
			p = FIXTURE / ad
			if not p.is_file():
				continue
			icerik = p.read_bytes()
			for max_dim in (256, 1000):
				sonuc = engine.optimize(icerik, max_dim, 80)
				if not sonuc.ok:
					continue
				ref = master_reference(icerik, max_dim)
				self.assertEqual(
					ref.size,
					(sonuc.width, sonuc.height),
					f"{ad} @ {max_dim}: referans {ref.size} != engine {(sonuc.width, sonuc.height)}",
				)
				bakilan += 1
		self.assertGreater(bakilan, 0, "hiç fixture bulunamadı")

	def test_arama_gercek_encoder_ile_calisir(self):
		sonuc = search_quality(self.icerik, target_ssim=0.95, max_dim=256)
		self.assertLessEqual(sonuc.encodes, DEFAULT_MAX_ENCODES)
		if sonuc.ok:
			self.assertGreaterEqual(sonuc.ssim, 0.95)
			self.assertTrue(sonuc.content)


class PolitikaHedefiTesti(unittest.TestCase):
	"""Hedef SSIM politika JSON'undan okunur — kodda sabit YOKTUR."""

	def test_urun_gorseli_hedefleri(self):
		self.assertEqual(target_for("product.image", "photo"), 0.96)
		self.assertEqual(target_for("product.image", "graphic"), 0.98)
		self.assertEqual(target_for("product.image", "text"), 0.99)

	def test_logo_slotlari_kayipsiz_ister(self):
		"""`quality.metric = bit_exact` → SSIM araması YAPILMAZ, None döner."""
		self.assertIsNone(target_for("seller.logo", "photo"))
		self.assertIsNone(target_for("brand.logo", "graphic"))

	def test_bilinmeyen_slot_ve_sinif_none(self):
		self.assertIsNone(target_for("yok.olan.slot", "photo"))
		self.assertIsNone(target_for("product.image", "yok_olan_sinif"))

	def test_sinif_tahmini_gecerli_deger_uretir(self):
		for ad in ("logo_jpeg_noalpha.jpg", "ok_product_1x1_2400.jpg", "content_blank_white.png"):
			p = FIXTURE / ad
			if not p.is_file():
				continue
			self.assertIn(guess_content_class(p.read_bytes()), ("photo", "graphic"))


if __name__ == "__main__":
	unittest.main(verbosity=2)

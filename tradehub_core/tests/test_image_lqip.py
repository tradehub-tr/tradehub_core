"""T-065 — LQIP testleri: ThumbHash + baskın renk, <30 bayt / <30 ms.

Ne doğrulanır
-------------
1. **Boyut**: her fixture'da hash < 30 bayt.
2. **Hız**: hash hesabı < 30 ms.
3. **Doğruluk**: hash geri açıldığında özgün görselin bulanık hâlini verir
   (yalnız "çalışıyor" değil, "doğru şeyi kodluyor" ölçülür).
4. **Alfa**: kesim görsellerde saydamlık hash'te taşınır.
5. **En-boy oranı** hash'in içinde durur (CLS için gerekli).

Bütçe nasıl okunmalı — ÖLÇÜLDÜ
------------------------------
Görev "<30 ms" diyor; ölçüm maliyeti ikiye ayırdı (yerel, Pillow 11.3.0,
numpy YOK — saf Python yolu):

    hash hesabı (32×32 RGBA hazırken)        1,5 – 2,9 ms
    uçtan uca, dosyadan (00.jpg 1200×630)          4,5 ms
    uçtan uca, dosyadan (05.webp 1080×1080)       11,3 ms
    uçtan uca, dosyadan (11.jpg 5536×4160)        38,8 ms   ← bütçe AŞILDI

Yani 30 ms bütçesi **hash hesabı** için rahatça tutuyor; aşan şey büyük
kaynağın çözülmesidir. Üretim yolunda LQIP zaten `normalize.py`'nin ürettiği
master'dan hesaplanır (o noktada görsel çözülmüş ve küçültülmüştür), ham
5.536×4.160 dosyadan değil. Aşağıdaki hız testi bu yüzden hash hesabını
ölçer; uçtan uca süre ayrı ve bilgi amaçlı sabitlenir.

Çalıştırma:

    python3 -m unittest tests.test_image_lqip -v
"""

from __future__ import annotations

import io
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.image import lqip as L  # noqa: E402

IMAGES = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "images"
MANIFEST = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "manifest.json"

#: Görevin verdiği sözleşme sınırları.
BAYT_SINIRI: int = 30
HASH_BUTCESI_MS: float = 30.0


def _fixtures() -> list[dict]:
	kayitlar = json.loads(MANIFEST.read_text(encoding="utf-8"))["fixtures"]
	return [f for f in kayitlar if f["class"] not in ("malicious", "video")]


def _rgba32(yol: Path):
	"""Fixture'ı hash girdisi ölçüsüne indir — hız ölçümünü decode'dan ayırır."""
	from PIL import Image

	with Image.open(yol) as im:
		rgba = im.convert("RGBA")
	rgba.thumbnail((L.MAX_EDGE, L.MAX_EDGE), Image.BOX)
	return rgba.size[0], rgba.size[1], rgba.tobytes()


class BoyutTest(unittest.TestCase):
	"""Hash 30 baytın altında olmalı — LQIP'in tüm varlık sebebi bu."""

	def test_tum_fixturelarda_30_baytin_altinda(self):
		for f in _fixtures():
			yol = ROOT / f["file"]
			with self.subTest(dosya=yol.name):
				r = L.encode(yol)
				self.assertTrue(r.ok, r.reason)
				self.assertLess(r.size_bytes, BAYT_SINIRI, f"{yol.name}: {r.size_bytes} bayt")

	def test_boyut_tavani_alfaya_bagli(self):
		"""Bayt sayısı içerikten BAĞIMSIZ: alfasız ≤24, alfalı ≤25.

		Tavan kare görselde görülür; oran uzadıkça parlaklık ızgarası (lx×ly)
		küçülür ve hash KISALIR. ÖLÇÜLDÜ: fixture'larda 17–25 bayt.
		Depolama planlaması bu yüzden "görsele göre değişir" demek zorunda
		değil — üst sınır sabittir.
		"""
		for f in _fixtures():
			yol = ROOT / f["file"]
			with self.subTest(dosya=yol.name):
				r = L.encode(yol)
				ust = 25 if r.hash[2] & 0x80 else 24
				self.assertLessEqual(r.size_bytes, ust)

	def test_sinir_asilirsa_sessizce_gecilmez(self):
		self.assertEqual(L.MAX_HASH_BYTES, BAYT_SINIRI)

	def test_base64_gomulebilir(self):
		r = L.encode(IMAGES / "ok_product_4x5.jpg")
		self.assertTrue(r.ok)
		# 24 bayt → 32 karakter base64. `<img data-thumbhash="...">` için yeterli.
		self.assertLessEqual(len(r.base64), 40)


class HizTest(unittest.TestCase):
	"""Hash hesabı 30 ms bütçesinin altında kalmalı."""

	def test_hash_hesabi_butce_icinde(self):
		en_kotu = 0.0
		en_kotu_ad = ""
		for f in _fixtures():
			yol = ROOT / f["file"]
			w, h, ham = _rgba32(yol)
			sureler = []
			for _ in range(3):
				t0 = time.perf_counter()
				L.rgba_to_thumb_hash(w, h, ham)
				sureler.append((time.perf_counter() - t0) * 1000)
			medyan = sorted(sureler)[1]
			if medyan > en_kotu:
				en_kotu, en_kotu_ad = medyan, yol.name

		self.assertLess(
			en_kotu,
			HASH_BUTCESI_MS,
			f"en yavaş hash {en_kotu_ad}: {en_kotu:.1f} ms — bütçe {HASH_BUTCESI_MS} ms",
		)

	def test_kucuk_kaynakta_uctan_uca_da_butce_icinde(self):
		"""Üretim yolundaki gerçek girdi (normalize edilmiş master) boyutunda."""
		yol = IMAGES / "logo_alpha_512.png"
		L.encode(yol)  # ısıtma
		sureler = []
		for _ in range(3):
			t0 = time.perf_counter()
			L.encode(yol)
			sureler.append((time.perf_counter() - t0) * 1000)
		medyan = sorted(sureler)[1]

		self.assertLess(medyan, HASH_BUTCESI_MS, f"{medyan:.1f} ms")


class DogrulukTest(unittest.TestCase):
	"""Hash gerçekten görseli kodlamalı — sabit bir bayt yığını değil."""

	def test_geri_acilan_hash_ortalama_renge_yakin(self):
		"""ThumbHash'i çöz, özgün görselin ortalamasıyla karşılaştır.

		Tolerans geniş (kanal başına 48/255): 24 bayt bir görseli birebir
		taşıyamaz. Amaç "doğru resmi kodladı mı", "birebir mi" değil.
		"""
		from PIL import Image, ImageStat

		for ad in ("ok_product_1x1_2400.jpg", "ok_banner_2x1.jpg", "icc_srgb_embedded.jpg"):
			yol = IMAGES / ad
			with self.subTest(dosya=ad):
				r = L.encode(yol)
				self.assertTrue(r.ok, r.reason)

				w, h, px = L.thumb_hash_to_rgba(r.hash)
				cozulen = Image.frombytes("RGBA", (w, h), bytes(px)).convert("RGB")
				coz_ort = ImageStat.Stat(cozulen).mean

				with Image.open(yol) as im:
					ozgun = im.convert("RGB")
				ozgun_ort = ImageStat.Stat(ozgun).mean

				# `zip(strict=)` bilerek kullanılmadı: Python 3.9'da yok ve bu
				# dosya sistem python3'ü ile de koşuyor. Uzunluk zaten 3.
				self.assertEqual(len(coz_ort), len(ozgun_ort))
				for kanal in range(len(coz_ort)):
					a, b = coz_ort[kanal], ozgun_ort[kanal]
					self.assertLess(
						abs(a - b), 48.0, f"{ad} kanal {kanal}: çözülen {a:.0f} vs özgün {b:.0f}"
					)

	def test_farkli_gorseller_farkli_hash_uretir(self):
		hashler = {}
		for f in _fixtures():
			yol = ROOT / f["file"]
			r = L.encode(yol)
			if r.ok:
				hashler.setdefault(r.hash, []).append(yol.name)

		# Sentetik fixture'larda aynı içerik farklı ölçüde tekrarlanıyor
		# (ör. logo_alpha_512 / mode_rgba_alpha); bunların eşleşmesi doğrudur.
		# Beklenen: en az 10 ayrı hash — hash içerikten türüyor demektir.
		self.assertGreaterEqual(len(hashler), 10, f"yalnız {len(hashler)} ayrı hash")

	def test_belirlenimci(self):
		yol = IMAGES / "ok_product_4x5.jpg"
		self.assertEqual(L.encode(yol).hash, L.encode(yol).hash)

	def test_bayt_girdisi_ile_yol_girdisi_ayni(self):
		yol = IMAGES / "ok_product_4x5.jpg"
		self.assertEqual(L.encode(yol).hash, L.encode(yol.read_bytes()).hash)

	def test_duz_renk_gorselde_ortalama_dogru(self):
		"""Kontrollü girdi: saf kırmızı → ortalama renk kırmızıya yakın olmalı."""
		from PIL import Image

		buf = io.BytesIO()
		Image.new("RGB", (64, 64), (220, 30, 30)).save(buf, "PNG")

		r = L.encode(buf.getvalue())

		self.assertTrue(r.ok, r.reason)
		kirmizi = int(r.average_hex[1:3], 16)
		yesil = int(r.average_hex[3:5], 16)
		self.assertGreater(kirmizi, 150)
		self.assertLess(yesil, 90)


class NumpyParitesiTest(unittest.TestCase):
	"""Hızlı (numpy) yol ile saf Python yolu AYNI baytları üretmeli.

	İki uygulama tutmak ancak ikisi ayrılmadığı sürece güvenlidir: aynı
	görselin iki sunucuda iki farklı hash üretmesi önbelleği ve içerik-adresli
	adlandırmayı sessizce bozar. ÖLÇÜLDÜ (konteyner, numpy 2.4.6, 34 fixture):
	fark = 0.
	"""

	def setUp(self):
		if not L._numpy_var():
			self.skipTest("numpy yok — bu ortamda yalnız saf Python yolu var")

	def test_iki_yol_bayt_bayt_ayni(self):
		for f in _fixtures():
			yol = ROOT / f["file"]
			w, h, ham = _rgba32(yol)
			with self.subTest(dosya=yol.name):
				ozgun = L._numpy_var
				try:
					L._numpy_var = lambda: True
					hizli = L.rgba_to_thumb_hash(w, h, ham)
					L._numpy_var = lambda: False
					saf = L.rgba_to_thumb_hash(w, h, ham)
				finally:
					L._numpy_var = ozgun
				self.assertEqual(hizli, saf, f"{yol.name}: {hizli.hex()} != {saf.hex()}")

	def test_duz_kanalda_makine_gurultusu_kanonik_sifirdir(self):
		"""Toplama sırası sabit kanalın hash'ini değiştirememeli."""
		kanal = [1.0] * (32 * 32)

		saf = L._encode_channel(kanal, 7, 7, 32, 32)
		hizli = L._encode_channel_np(kanal, 7, 7, 32, 32)

		self.assertEqual(saf, hizli)
		self.assertEqual(saf[2], 0.0)
		self.assertTrue(all(katsayi == 0.0 for katsayi in saf[1]))


class AlfaTest(unittest.TestCase):
	"""Kesim görsellerde saydamlık hash'e girmeli (BlurHash'in yapamadığı)."""

	def test_alfali_fixturelar_alfa_bayragi_tasir(self):
		for ad in ("logo_alpha_512.png", "mode_rgba_alpha.png", "enc_webp_lossless.webp"):
			yol = IMAGES / ad
			with self.subTest(dosya=ad):
				r = L.encode(yol)
				self.assertTrue(r.ok, r.reason)
				self.assertTrue(r.has_alpha)
				self.assertTrue(r.hash[2] & 0x80, "hash başlığında alfa biti yok")
				self.assertLessEqual(r.size_bytes, 25)

	def test_opak_gorselde_alfa_biti_yok(self):
		r = L.encode(IMAGES / "ok_product_4x5.jpg")
		self.assertFalse(r.hash[2] & 0x80)
		self.assertLessEqual(r.size_bytes, 24)

	def test_saydam_bolge_geri_acildiginda_saydam(self):
		from PIL import Image

		r = L.encode(IMAGES / "logo_alpha_512.png")
		w, h, px = L.thumb_hash_to_rgba(r.hash)
		alfa = Image.frombytes("RGBA", (w, h), bytes(px)).getchannel("A")

		self.assertLess(min(alfa.getdata()), 200, "hiçbir piksel saydam değil")

	def test_baskin_renk_saydam_bolgeyi_saymaz(self):
		"""Kesim logonun baskın rengi, arkasındaki boşluk DEĞİL logonun kendisidir."""
		r = L.encode(IMAGES / "logo_alpha_512.png")

		self.assertTrue(r.ok, r.reason)
		self.assertGreater(r.dominant_share, 0.0)
		self.assertNotEqual(r.dominant_hex, "#000000")


class OranTest(unittest.TestCase):
	"""En-boy oranı hash'in İÇİNDE — ayrıca saklanmasına gerek yok."""

	def test_yatay_ve_dikey_ayirt_edilir(self):
		yatay = L.encode(IMAGES / "ok_cover_24x5.jpg")
		kare = L.encode(IMAGES / "ok_product_1x1_2400.jpg")
		dikey = L.encode(IMAGES / "ok_product_4x5.jpg")

		self.assertGreater(L.thumb_hash_aspect_ratio(yatay.hash), 1.0)
		self.assertAlmostEqual(L.thumb_hash_aspect_ratio(kare.hash), 1.0, delta=0.35)
		self.assertLess(L.thumb_hash_aspect_ratio(dikey.hash), 1.0)

	def test_oran_gercek_orana_yakin(self):
		"""24 baytta oran kabaca kodlanır; yer tutucu için yeterli olmalı."""
		from PIL import Image

		for ad in ("ok_banner_2x1.jpg", "ok_product_4x5.jpg", "ok_product_1x1_2400.jpg"):
			yol = IMAGES / ad
			with self.subTest(dosya=ad):
				with Image.open(yol) as im:
					gercek = im.width / im.height
				kodlanan = L.thumb_hash_aspect_ratio(L.encode(yol).hash)
				self.assertLess(abs(kodlanan - gercek) / gercek, 0.45)


class SozlesmeTest(unittest.TestCase):
	"""LQIP üretimi çağıranı hiçbir koşulda patlatmaz."""

	def test_bozuk_girdi_istisna_atmaz(self):
		for girdi in (b"", b"\x00\x01", b"garbage", bytes(512)):
			with self.subTest(girdi=girdi[:6]):
				r = L.encode(girdi)
				self.assertFalse(r.ok)
				self.assertEqual(r.hash, b"")
				self.assertTrue(r.reason)

	def test_olmayan_dosya(self):
		r = L.encode(ROOT / "yok" / "dosya.jpg")
		self.assertFalse(r.ok)

	def test_animasyonda_ilk_kare(self):
		r = L.encode(IMAGES / "anim_6frames.gif")
		self.assertTrue(r.ok, r.reason)
		self.assertLess(r.size_bytes, BAYT_SINIRI)

	def test_cmyk_kaynak(self):
		r = L.encode(IMAGES / "mode_cmyk.jpg")
		self.assertTrue(r.ok, r.reason)

	def test_72mp_kaynak(self):
		r = L.encode(IMAGES / "edge_72mp.jpg")
		self.assertTrue(r.ok, r.reason)
		self.assertLess(r.size_bytes, BAYT_SINIRI)

	def test_tek_piksel(self):
		r = L.encode(IMAGES / "geom_1x1.png")
		self.assertTrue(r.ok, r.reason)

	def test_to_dict_serilestirilebilir(self):
		d = L.encode(IMAGES / "ok_product_4x5.jpg").to_dict()
		json.dumps(d)
		self.assertIn("hash_b64", d)

	def test_100_pikselden_buyuk_girdi_reddedilir(self):
		"""ThumbHash sözleşmesi: girdi 100×100'ü aşamaz — sessizce kırpılmaz."""
		with self.assertRaises(ValueError):
			L.rgba_to_thumb_hash(200, 200, bytes(200 * 200 * 4))

	def test_yuvarlama_yarim_yukari(self):
		"""JS `Math.round` uyumu — bankacı yuvarlaması hash'i kaydırır."""
		self.assertEqual(L._r(0.5), 1)
		self.assertEqual(L._r(1.5), 2)
		self.assertEqual(L._r(2.5), 3)


if __name__ == "__main__":
	unittest.main(verbosity=2)

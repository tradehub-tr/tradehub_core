"""W5 — Megapiksel-bomba kaçış aralığının kapanması. **Frappe/bench gerekmez.**

Ölçülmüş kaçış (rapor 75 bulgu 4, panel E2E)
--------------------------------------------
Pillow, kendi `MAX_IMAGE_PIXELS` tavanının (89.478.485 px; istisna eşiği 2×)
ÜSTÜNDE boyut BEYAN eden başlığı hiç açmıyordu (`DecompressionBombError`),
`content_gate` ölçüyü 0 okuyordu ve 80 MP tavanı hiç değerlendirilmiyordu:
30000×30000 (900 MP) iddialı PNG kapıdan **200 ile geçti** (canlı iz:
`/files/25/25b8f950….png`). Yalnız 80–89 MP penceresi yakalanıyordu.

Bu modül kuralın FAIL-CLOSED hâlini sabitler:

1. Pillow tavanı ÜSTÜ beyan (30000×30000)      → RED (`upload_image_bomb`)
2. Eski pencere (80–89 MP ve 89–179 MP arası)  → HÂLÂ RED
3. Normal görsel                                → GEÇER
4. Bozuk/okunamayan başlık, 0 boyut beyanı      → RED (fail-closed)

Kırmızı kanıt (vacuity): düzeltme uygulanmadan önce bu modül konteynerde
koşturuldu — 30000² ve bozuk-başlık testleri DÜŞTÜ (`inspect` boş döndü),
düzeltme sonrası yeşil. Yani testler düzeltmeyi gerçekten ölçüyor.

Çalıştırma:

	python3 -m unittest tradehub_core.tests.test_media_bomb_escape -v
"""

from __future__ import annotations

import io
import struct
import sys
import unittest
import warnings
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.image import probe as P  # noqa: E402
from tradehub_core.media.pipeline.security import content_gate as G  # noqa: E402

MEDIA = ROOT / "tradehub_core" / "tests" / "fixtures" / "media"


def _chunk(tip: bytes, veri: bytes) -> bytes:
	return struct.pack(">I", len(veri)) + tip + veri + struct.pack(">I", zlib.crc32(tip + veri))


def _png(width: int, height: int) -> bytes:
	"""Boyut BEYAN eden, gövdesi bir avuç bayt olan yapısal PNG.

	Panel E2E'nin `makeBombPng()` üreticisiyle aynı yapı (helpers.ts):
	geçerli imza + IHDR + küçük IDAT + IEND. IEND kuyrukta olduğu için
	kesiklik kuralı tetiklenmez — testin ölçtüğü tek kural piksel tavanıdır.
	"""
	ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
	idat = zlib.compress(b"\x00" * 8, 9)
	return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _pillow_acilir_mi(icerik: bytes) -> bool:
	"""Pillow bu başlığı açabiliyor mu — kaçış penceresinin ölçümü."""
	from PIL import Image

	try:
		with warnings.catch_warnings():
			warnings.simplefilter("ignore")
			with Image.open(io.BytesIO(icerik)):
				return True
	except Exception:
		return False


class KacisAraligi(unittest.TestCase):
	"""content_gate: Pillow'un açtığı/açmadığı HER bölgede bomba RED."""

	def test_pillow_tavani_ustu_bomba_reddedilir(self):
		"""30000×30000 (900 MP) — rapor 75'te 200 ile geçen vaka."""
		icerik = _png(30000, 30000)
		# Kaçışın mekanizması sabitlensin: Pillow bu başlığı AÇAMIYOR.
		# (Pillow tavanı değişir de açılır olursa bu ölçüm uyarır; kural
		# yine de aşağıdaki iddia ile korunur.)
		self.assertFalse(_pillow_acilir_mi(icerik), "Pillow 900 MP başlığı açtı — kaçış penceresi kaymış")
		bulgular = G.inspect("bomba.png", icerik)
		self.assertTrue(bulgular, "900 MP bomba kapıdan GEÇTİ — kaçış aralığı hâlâ açık")
		bomba = next(b for b in bulgular if b.kod == G.KOD_BOMB)
		self.assertEqual(bomba.olculen, 900.0)
		self.assertEqual(bomba.beklenen, G.MAX_MEGAPIXELS)

	def test_eski_pencere_80_89_mp_hala_reddedilir(self):
		"""9200×9200 = 84,64 MP — Pillow uyarı eşiğinin bile altı, tavan üstü."""
		icerik = _png(9200, 9200)
		self.assertTrue(_pillow_acilir_mi(icerik), "bu bölge Pillow'un açabildiği pencere olmalı")
		kodlar = [b.kod for b in G.inspect("bomba.png", icerik)]
		self.assertIn(G.KOD_BOMB, kodlar)

	def test_uyari_bolgesi_89_179_mp_hala_reddedilir(self):
		"""12000×12000 = 144 MP — S10'un bilinçli seçtiği, uyarı-ama-açılır bölge."""
		icerik = _png(12000, 12000)
		self.assertTrue(_pillow_acilir_mi(icerik), "bu bölge Pillow'un açabildiği pencere olmalı")
		kodlar = [b.kod for b in G.inspect("bomba.png", icerik)]
		self.assertIn(G.KOD_BOMB, kodlar)

	def test_normal_gorsel_gecer(self):
		"""Gerçek (Pillow ile üretilmiş) 2000×2000 PNG — bulgu ÜRETMEZ."""
		from PIL import Image

		tampon = io.BytesIO()
		Image.new("RGB", (2000, 2000), "white").save(tampon, format="PNG")
		self.assertEqual(G.inspect("urun.png", tampon.getvalue()), ())

	def test_kucuk_beyanli_yapisal_png_gecer(self):
		"""Sentetik üreticinin kendisi yanlış pozitif üretmesin: 100×100 geçer."""
		self.assertEqual(G.inspect("urun.png", _png(100, 100)), ())


class FailClosed(unittest.TestCase):
	"""Başlık okunamıyor ya da 0/negatif beyan ediyor → RED, sessiz geçiş yok."""

	def test_sifir_boyut_beyani_reddedilir(self):
		bulgular = G.inspect("bomba.png", _png(0, 0))
		self.assertIn(G.KOD_BOMB, [b.kod for b in bulgular])

	def test_bozuk_baslik_reddedilir(self):
		"""PNG imzası + çöp IHDR: iki okuma yolu da ölçü veremez → fail-closed RED.

		Kuyruğa IEND kondu ki kesiklik kuralı değil, tam olarak fail-closed
		dalı ölçülsün.
		"""
		icerik = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4 + b"JUNK" + b"\xff" * 24 + _chunk(b"IEND", b"")
		bulgular = G.inspect("bozuk.png", icerik)
		self.assertIn(G.KOD_BOMB, [b.kod for b in bulgular])

	def test_olcusuz_gorsel_olmayan_icerik_reddedilmez(self):
		"""Fail-closed dalı yalnız tanınan görsel biçimleri içindir: sihirli
		baytı tanınmayan içerik (ör. CSV) eskisi gibi kurala GİRMEZ."""
		self.assertEqual(G.inspect("liste.csv", b"ad;fiyat\nkalem;10\n"), ())


class ProbeKapisi(unittest.TestCase):
	"""Aynı kaçış `image/probe.probe_header` kapısında da kapalı."""

	def test_probe_header_bomba_kodunu_verir(self):
		p = P.probe_header(_png(30000, 30000), filename="bomba.png")
		self.assertFalse(p.ok)
		self.assertIn("megapixel_bomb", p.codes)
		# Ölçü ham baytlardan okundu — ret bir tahmin değil, beyanın kendisi.
		self.assertEqual((p.width, p.height), (30000, 30000))
		self.assertEqual(p.codes[0], "megapixel_bomb", "kullanıcıya gösterilecek İLK gerekçe bomba olmalı")

	def test_probe_header_eski_pencere_hala_red(self):
		p = P.probe_header(_png(9200, 9200), filename="bomba.png")
		self.assertIn("megapixel_bomb", p.codes)

	def test_assert_accepted_istisna_atar(self):
		with self.assertRaises(P.ImageRejected):
			P.assert_accepted(_png(30000, 30000), filename="bomba.png")


class BeyanOlcusu(unittest.TestCase):
	"""`declared_dimensions` Pillow ile AYNI ölçüyü okumalı — gerçek korpusta."""

	def test_ham_baslik_olcusu_pillow_ile_ayni(self):
		"""Temiz fixture korpusundaki her PNG/JPEG/GIF/WebP/BMP için ham
		bayt ayrıştırıcısı Pillow'un okuduğu ölçünün aynısını vermeli."""
		from PIL import Image

		sayac = 0
		for yol in sorted(MEDIA.rglob("*")):
			if not yol.is_file() or yol.suffix.lower() == ".json":
				continue
			icerik = yol.read_bytes()
			detected = P.sniff(icerik[: P.HEAD_BYTES])
			if detected not in P.DIMENSIONS_PARSEABLE:
				continue
			with self.subTest(fixture=yol.name):
				beyan = P.declared_dimensions(icerik[: P.HEAD_BYTES], detected)
				self.assertIsNotNone(beyan, f"{yol.name}: ham başlık okunamadı")
				with Image.open(io.BytesIO(icerik)) as im:
					self.assertEqual(beyan, (im.width, im.height))
				sayac += 1
		self.assertGreaterEqual(sayac, 10, "korpus küçülmüş — ölçüm anlamını yitirir")

	def test_sentetik_png_beyani(self):
		self.assertEqual(P.declared_dimensions(_png(30000, 30000)[:64], "png"), (30000, 30000))

	def test_bilinmeyen_bicim_none(self):
		self.assertIsNone(P.declared_dimensions(b"\x00" * 64, ""))
		self.assertIsNone(P.declared_dimensions(b"II*\x00" + b"\x00" * 60, "tiff"))


if __name__ == "__main__":
	unittest.main(verbosity=2)

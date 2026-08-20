"""T-017 — Yükleme kapısının içerik denetimi. **Frappe/bench gerekmez.**

Ne doğrulanır
-------------
1. `tests/fixtures/malicious/` içindeki HER dosya reddedilir — kaynağın kabul
   kriteri budur. Sekizi bu görevden önce kapıdan GEÇİYORDU
   (ölçüm: `docs/reports/33-dogrulama-faz0-3.md` §T-017, bağımsız tekrarı
   `docs/reports/38-t017-guvenlik-kapisi.md` §1).
2. Her fixture'ın ret KODU sabitlenmiştir. Kod değişirse test kırılır ve
   değişikliğin bilinçli olduğu görülür — hangi kontrolün tuttuğu belli olsun.
3. **Meşru yol kırılmadı:** temiz fixture korpusundaki 34 görsel + 7 videonun
   hiçbiri bulgu üretmez.
4. Piksel tavanı kararı pikseller AÇILMADAN verilir.

Çalıştırma:

    python3 -m unittest tradehub_core.tests.test_media_security_gate -v
"""

from __future__ import annotations

import io
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.security import content_gate as G  # noqa: E402

FIXTURE = ROOT / "tradehub_core" / "tests" / "fixtures"
MALICIOUS = FIXTURE / "malicious"
MEDIA = FIXTURE / "media"

#: Her kötücül fixture'ın BEKLENEN ret kodu — ölçümün sabitlenmiş hâli.
#: `None` = bu dosya içerik denetiminde değil, `upload_policy`'nin kendi
#: kuralında düşer (boş içerik / yasaklı uzantı); ayrı testte doğrulanır.
BEKLENEN: dict[str, str | None] = {
	"bomb_100mp.png": G.KOD_BOMB,
	"data_uri_svg.txt": G.KOD_DANGEROUS,
	"empty_zero_byte.jpg": None,  # upload_policy: upload_content_empty
	"executable_as.png": G.KOD_DANGEROUS,
	"fake_docx.docx": G.KOD_CONTAINER,
	"jpeg_with_html_tail.jpg": G.KOD_APPENDED,
	"polyglot_pdf_as.jpg": G.KOD_MISMATCH,
	"polyglot_png_as.jpg": G.KOD_MISMATCH,
	"script_payload.svg": G.KOD_DANGEROUS,
	"truncated.jpg": G.KOD_TRUNCATED,
}


def _oku(p: Path) -> bytes:
	return p.read_bytes()


class KotuculKorpus(unittest.TestCase):
	"""Kaynağın kabul kriteri: `fixtures/malicious/` içindeki HER dosya reddedilir."""

	def test_korpus_eksiksiz(self):
		"""Tablo ile dizin ayrışmasın — yeni fixture eklenirse test uyarsın."""
		diskte = {p.name for p in MALICIOUS.iterdir() if p.is_file()}
		self.assertEqual(diskte, set(BEKLENEN), "malicious/ dizini ile beklenen tablo ayrıştı")

	def test_her_kotucul_dosya_bulgu_uretir(self):
		for ad, kod in sorted(BEKLENEN.items()):
			with self.subTest(fixture=ad):
				icerik = _oku(MALICIOUS / ad)
				bulgular = G.inspect(ad, icerik)
				if kod is None:
					# Boş dosya: içerik denetiminin ölçecek bir şeyi yok.
					self.assertEqual(icerik, b"")
					self.assertEqual(bulgular, ())
					continue
				self.assertTrue(bulgular, f"{ad} kapıdan GEÇTİ — bulgu yok")
				self.assertEqual(
					bulgular[0].kod,
					kod,
					f"{ad} beklenen kodla düşmedi: {[b.kod for b in bulgular]}",
				)

	def test_bomba_100mp_olarak_olculur(self):
		"""Ret gerekçesi bir tahmin değil, başlıktan okunan ölçüdür."""
		bulgular = G.inspect("bomb_100mp.png", _oku(MALICIOUS / "bomb_100mp.png"))
		bomba = next(b for b in bulgular if b.kod == G.KOD_BOMB)
		self.assertAlmostEqual(bomba.olculen, 100.0, places=1)
		self.assertEqual(bomba.beklenen, G.MAX_MEGAPIXELS)

	def test_bomba_pikselleri_acilmadan_reddedilir(self):
		"""`Image.open` tembeldir; `load()` çağrılırsa 100 MP bellek ayrılırdı.

		Kanıt dolaylı olamaz: `ImageFile.LOAD_TRUNCATED_IMAGES` ve Pillow'un
		bomba eşiği devre dışı bırakılmadan da karar veriliyorsa, karar
		başlıktan verilmiştir. Burada doğrudan ölçülüyor: `Image.load`
		çağrılırsa test düşer.
		"""
		from PIL import Image

		cagrildi: list[str] = []
		orijinal = Image.Image.load

		def izleyici(self, *a, **kw):  # noqa: ANN001
			cagrildi.append("load")
			return orijinal(self, *a, **kw)

		Image.Image.load = izleyici
		try:
			bulgular = G.inspect("bomb_100mp.png", _oku(MALICIOUS / "bomb_100mp.png"))
		finally:
			Image.Image.load = orijinal
		self.assertTrue(any(b.kod == G.KOD_BOMB for b in bulgular))
		self.assertEqual(cagrildi, [], "piksel decode edildi — kapı bombayı açtı")


class MesruYol(unittest.TestCase):
	"""Kapıyı sıkmak gerçek dosyaları kesmemeli."""

	def test_temiz_fixture_korpusu_bulgu_uretmez(self):
		sayac = 0
		for p in sorted(MEDIA.rglob("*")):
			if not p.is_file() or p.suffix.lower() == ".json":
				continue
			sayac += 1
			with self.subTest(fixture=p.name):
				self.assertEqual(
					G.inspect(p.name, p.read_bytes()),
					(),
					f"{p.name} yanlış pozitif üretti",
				)
		self.assertGreaterEqual(sayac, 41, "temiz korpus küçülmüş; ölçüm 34 görsel + 7 video")

	def test_bilinmeyen_sihirli_bayt_uyusmazlik_sayilmaz(self):
		"""Gerçek korpusta 1.492 dosyanın sihirli baytı tanınmıyor (.txt/.csv/
		.avif/.heic). Bunları uyuşmazlık saymak meşru yolu keserdi."""
		self.assertEqual(G.inspect("liste.csv", b"ad;fiyat\nkalem;10\n"), ())
		self.assertFalse(G._tehlikeli_uyusmazlik(".heic", ""))

	def test_video_kabi_uyusmazligi_reddedilmez(self):
		"""`.mp4` içinde webm — gerçek korpusta 1 dosya, tarayıcı çıktısında
		yaygın, iki taraf da hareketsiz kap."""
		self.assertFalse(G._tehlikeli_uyusmazlik(".mp4", "webm"))

	def test_gorsel_uzantida_farkli_gorsel_bicimi_reddedilir(self):
		"""Aynı kural görsel tarafta SIKI: gerçek korpusta 0 dosya."""
		self.assertTrue(G._tehlikeli_uyusmazlik(".jpg", "png"))
		self.assertTrue(G._tehlikeli_uyusmazlik(".jpg", "pdf"))
		self.assertFalse(G._tehlikeli_uyusmazlik(".jpg", "jpeg"))


class OOXMLKabi(unittest.TestCase):
	"""Sahte belge kabı — `fake_docx.docx` tam olarak budur."""

	@staticmethod
	def _zip(adlar: dict[str, bytes]) -> bytes:
		tampon = io.BytesIO()
		with zipfile.ZipFile(tampon, "w") as zf:
			for ad, veri in adlar.items():
				zf.writestr(ad, veri)
		return tampon.getvalue()

	def test_gecerli_docx_gecer(self):
		veri = self._zip({"[Content_Types].xml": b"<x/>", "word/document.xml": b"<x/>"})
		self.assertIs(G._ooxml_gecerli(veri, ".docx"), True)

	def test_gecerli_xlsx_gecer(self):
		"""Gerçek korpusta 30 `.xlsx` var, 30'u da bu yapıda."""
		veri = self._zip({"[Content_Types].xml": b"<x/>", "xl/workbook.xml": b"<x/>"})
		self.assertIs(G._ooxml_gecerli(veri, ".xlsx"), True)

	def test_icerigi_docx_olmayan_zip_reddedilir(self):
		veri = self._zip({"merhaba.txt": b"bu bir docx degil"})
		self.assertIs(G._ooxml_gecerli(veri, ".docx"), False)

	def test_duz_zip_dogrulanmaz(self):
		"""Zip'in iddia ettiği iç yapı yok; gerçek korpusta 11 tanesi ürün
		görseli arşivi ve hepsi geçerli kalmalı."""
		veri = self._zip({"urun-1.png": b"\x89PNG\r\n\x1a\n"})
		self.assertIsNone(G._ooxml_gecerli(veri, ".zip"))
		self.assertEqual(G.inspect("katalog.zip", veri), ())


class KesiklikOlcumu(unittest.TestCase):
	"""`None` = ölçülemedi; sessizce "tamam" SAYILMAZ."""

	def test_jpeg_eoi_yoksa_kesik(self):
		self.assertIs(G._kuyruk_tam(b"\xff\xd8\xff\xe0veri", "jpeg"), False)

	def test_jpeg_eoi_varsa_tam(self):
		self.assertIs(G._kuyruk_tam(b"veri\xff\xd9", "jpeg"), True)

	def test_olculemez_bicimde_none(self):
		self.assertIsNone(G._kuyruk_tam(b"RIFF....WEBP", "webp"))
		self.assertIsNone(G._kuyruk_tam(b"herhangi", ""))

	def test_olculemez_bicim_ret_uretmez(self):
		"""WEBP kuyruğu ucuzca bilinemiyor — kural ATLANIR, ret üretmez."""
		kucuk_webp = (MEDIA / "images" / "enc_webp_lossless.webp")
		if not kucuk_webp.exists():
			self.skipTest("webp fixture yok")
		bulgular = G.inspect(kucuk_webp.name, kucuk_webp.read_bytes())
		self.assertNotIn(G.KOD_TRUNCATED, [b.kod for b in bulgular])


class PikselTavani(unittest.TestCase):
	"""Eşik gerçek korpusta ölçüldü: en büyük gerçek görsel 72,71 MP."""

	def test_esik_gercek_korpusun_ustunde(self):
		self.assertGreater(G.MAX_MEGAPIXELS, 72.71, "eşik ölçülen en büyük gerçek dosyanın altına düştü")

	def test_esik_altindaki_gorsel_gecer(self):
		from PIL import Image

		tampon = io.BytesIO()
		Image.new("RGB", (2000, 2000), "white").save(tampon, format="PNG")
		self.assertEqual(G.inspect("urun.png", tampon.getvalue()), ())


if __name__ == "__main__":
	unittest.main(verbosity=2)

"""T-060 — Kabul kapısı testleri: **piksel açmadan** karar.

Ne doğrulanır
-------------
1. Kötücül fixture'ların HEPSİ reddedilir ve ret kodu beklenen koddur.
2. Ret kararı dosyanın pikselleri açılmadan verilir (`bomb_100mp.png`).
3. Geçerli fixture'lar kabul edilir — kapı yanlış-pozitif üretmez.
4. 30 MB'lık dosyada başlık okuma bütçesi (<50 ms) tutar.

Çalıştırma:

    python3 -m unittest tests.test_image_probe -v      # repo kökünden
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.image import probe as P  # noqa: E402

MANIFEST = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "manifest.json"

#: 30 MB'lık dosyada başlık okuma bütçesi. Kapı kuyruğu da okuduğu için
#: bütçe salt `Image.open` değil, uçtan uca `probe_header` içindir.
BASLIK_BUTCESI_MS: float = 50.0

#: Her kötücül fixture'ın beklenen ret kodu. ÖLÇÜLDÜ (2026-08-18, yerel
#: Pillow 11.3.0). Bu tablo bir BEYAN değil, ölçümün sabitlenmiş hâlidir:
#: kod değişirse test kırılır ve değişikliğin bilinçli olduğu görülür.
BEKLENEN_RET: dict[str, str] = {
	"bomb_100mp.png": "megapixel_bomb",
	"script_payload.svg": "dangerous_content",
	"polyglot_pdf_as.jpg": "ext_content_mismatch",
	"polyglot_png_as.jpg": "ext_content_mismatch",
	"empty_zero_byte.jpg": "empty",
	"truncated.jpg": "truncated",
	"fake_docx.docx": "decode_failed",
	"executable_as.png": "dangerous_content",
	"data_uri_svg.txt": "dangerous_content",
	"jpeg_with_html_tail.jpg": "appended_payload",
}


def _manifest() -> dict:
	return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _fixtures(sinif: str | None = None) -> list[dict]:
	kayitlar = _manifest()["fixtures"]
	if sinif is None:
		return kayitlar
	return [f for f in kayitlar if f["class"] == sinif]


class KotucuIcerikTest(unittest.TestCase):
	"""Kapı, kötücül fixture'ların hiçbirini geçirmemeli."""

	def test_tum_kotucul_fixturelar_reddedilir(self):
		for f in _fixtures("malicious"):
			yol = ROOT / f["file"]
			with self.subTest(dosya=yol.name):
				p = P.probe_header(yol)
				self.assertFalse(p.ok, f"{yol.name} kapıdan GEÇTİ — geçmemeliydi")
				self.assertTrue(p.codes, "ret var ama kod yok")

	def test_ret_kodlari_olculen_degerlerde(self):
		"""Ret kodu kullanıcıya gösterilen tek gerekçedir; kayarsa fark edilmeli."""
		for f in _fixtures("malicious"):
			yol = ROOT / f["file"]
			beklenen = BEKLENEN_RET.get(yol.name)
			if beklenen is None:
				continue
			with self.subTest(dosya=yol.name):
				p = P.probe_header(yol)
				self.assertEqual(p.codes[0], beklenen)

	def test_bomba_piksel_acilmadan_reddedilir(self):
		"""`bomb_100mp.png` 100 MP — reddedilirken belleğe alınmamalı.

		Doğrudan "load çağrıldı mı" ölçülemediği için ZAMAN ölçülür: 100 MP'yi
		gerçekten açmak saniyeler sürer, başlıktan reddetmek milisaniyeler.
		"""
		yol = ROOT / "tradehub_core" / "tests" / "fixtures" / "malicious" / "bomb_100mp.png"
		self.assertTrue(yol.exists(), "bomba fixture'ı yok")

		t0 = time.perf_counter()
		p = P.probe_header(yol)
		sure_ms = (time.perf_counter() - t0) * 1000

		self.assertEqual(p.codes[0], "megapixel_bomb")
		self.assertLess(sure_ms, 250.0, f"bomba reddi {sure_ms:.0f} ms sürdü — pikseller açılıyor olabilir")

	def test_kesik_dosya_baslikta_gecerli_ama_reddedilir(self):
		"""`truncated.jpg`'nin başlığı OKUNUR; ret kuyruktaki EOI eksikliğindendir."""
		yol = ROOT / "tradehub_core" / "tests" / "fixtures" / "malicious" / "truncated.jpg"
		p = P.probe_header(yol)

		self.assertTrue(p.width > 0 and p.height > 0, "başlık okunamamış")
		self.assertTrue(p.truncated, "kesiklik saptanmadı")
		self.assertIn("truncated", p.codes)


class GecerliGorselTest(unittest.TestCase):
	"""Kapı yanlış-pozitif üretmemeli: geçerli fixture'lar geçmeli."""

	def test_gecerli_gorseller_kabul_edilir(self):
		gevsek = P.GuardConfig(max_megapixels=200.0, max_bytes=64 * 1024 * 1024, allow_animated=True)
		for f in _fixtures():
			if f["class"] in ("malicious", "video"):
				continue
			yol = ROOT / f["file"]
			with self.subTest(dosya=yol.name):
				p = P.probe_header(yol, config=gevsek)
				self.assertTrue(p.ok, f"{yol.name} reddedildi: {p.codes}")
				self.assertTrue(p.readable)

	def test_olculer_manifest_ile_uyusur(self):
		"""Başlıktan okunan ölçü, manifest'in ÖLÇÜLEN bloğuyla aynı olmalı."""
		gevsek = P.GuardConfig(max_megapixels=200.0, max_bytes=64 * 1024 * 1024, allow_animated=True)
		for f in _fixtures():
			if f["class"] in ("malicious", "video"):
				continue
			olculen = f.get("olculen") or {}
			if not olculen.get("width"):
				continue
			yol = ROOT / f["file"]
			with self.subTest(dosya=yol.name):
				p = P.probe_header(yol, config=gevsek)
				self.assertEqual((p.width, p.height), (olculen["width"], olculen["height"]))

	def test_animasyon_baslikta_saptanir(self):
		gevsek = P.GuardConfig(allow_animated=True)
		for f in _fixtures("animation"):
			yol = ROOT / f["file"]
			with self.subTest(dosya=yol.name):
				p = P.probe_header(yol, config=gevsek)
				self.assertTrue(p.animated)
				self.assertGreater(p.frame_count, 1)

	def test_animasyon_yasakliyken_reddedilir(self):
		siki = P.GuardConfig(allow_animated=False)
		for f in _fixtures("animation"):
			yol = ROOT / f["file"]
			with self.subTest(dosya=yol.name):
				p = P.probe_header(yol, config=siki)
				self.assertIn("animated_not_allowed", p.codes)


class PikselTavaniTest(unittest.TestCase):
	"""Piksel tavanı DOSYA BOYUTUNDAN değil başlıktan okunmalı (FR-011)."""

	def test_kucuk_dosya_buyuk_megapiksel_yakalanir(self):
		"""`p01_18mp_1mb.jpg` — 1 MB dosya, 17,92 MP. Bayta bakan kapı kaçırır."""
		yol = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "images" / "p01_18mp_1mb.jpg"
		p = P.probe_header(yol, config=P.GuardConfig(max_megapixels=10.0))

		self.assertLess(yol.stat().st_size, 2 * 1024 * 1024, "fixture 'küçük dosya' olmalı")
		self.assertGreater(p.megapixels, 17.0)
		self.assertIn("megapixel_bomb", p.codes)

	def test_slot_politikasindan_kapi_kurulur(self):
		kapi = P.GuardConfig.from_accept({"max_megapixels_hard": 12, "max_bytes": 5_000_000})
		self.assertEqual(kapi.max_megapixels, 12.0)
		self.assertEqual(kapi.max_bytes, 5_000_000)


class BaslikButcesiTest(unittest.TestCase):
	"""30 MB'lık dosyada başlık okuma <50 ms olmalı."""

	@classmethod
	def setUpClass(cls):
		from PIL import Image

		cls._dizin = Path(tempfile.mkdtemp(prefix="t060-"))
		cls.buyuk = cls._dizin / "buyuk_30mb.tif"
		# Sıkıştırmasız TIFF: 3000x3000x3 = 27 MB. Sıkıştırılmış bir dosyayı
		# 30 MB'a çıkarmak için gürültü üretmek gerekirdi; ölçülecek şey
		# BAŞLIK okuma maliyeti olduğu için içerik önemsiz.
		im = Image.new("RGB", (3000, 3000), (128, 64, 32))
		im.save(cls.buyuk, "TIFF", compression=None)

	@classmethod
	def tearDownClass(cls):
		shutil.rmtree(cls._dizin, ignore_errors=True)

	def test_30mb_dosyada_baslik_butcesi(self):
		boyut_mb = self.buyuk.stat().st_size / 1024 / 1024
		self.assertGreater(boyut_mb, 25.0, f"fixture yeterince büyük değil: {boyut_mb:.1f} MB")

		# İlk çağrı dosya sistemi önbelleğini ısıtır; bütçe sıcak yolda ölçülür.
		P.probe_header(self.buyuk)
		sureler = []
		for _ in range(5):
			t0 = time.perf_counter()
			p = P.probe_header(self.buyuk, config=P.GuardConfig(max_bytes=64 * 1024 * 1024))
			sureler.append((time.perf_counter() - t0) * 1000)
		sureler.sort()
		medyan = sureler[len(sureler) // 2]

		self.assertTrue(p.ok, f"büyük dosya reddedildi: {p.codes}")
		self.assertEqual((p.width, p.height), (3000, 3000))
		self.assertLess(medyan, BASLIK_BUTCESI_MS, f"başlık okuma {medyan:.1f} ms — bütçe {BASLIK_BUTCESI_MS} ms")

	def test_yol_girdisi_dosyayi_bellege_almaz(self):
		"""Yol verildiğinde yalnız baş + kuyruk okunur.

		Bunu doğrudan ölçmenin yolu yok; dolaylı kanıt: 27 MB'lık dosyada
		başlık okuma, dosyanın tamamını okumaktan (`read_bytes`) belirgin
		biçimde hızlı olmalı.
		"""
		t0 = time.perf_counter()
		P.probe_header(self.buyuk, config=P.GuardConfig(max_bytes=64 * 1024 * 1024))
		yol_ms = (time.perf_counter() - t0) * 1000

		t0 = time.perf_counter()
		self.buyuk.read_bytes()
		tam_okuma_ms = (time.perf_counter() - t0) * 1000

		self.assertLess(yol_ms, max(tam_okuma_ms, 1.0), "yol yolu tam okumadan hızlı değil")


class SozlesmeTest(unittest.TestCase):
	"""Kapı hiçbir koşulda istisna atmaz; ret LİSTESİ döner."""

	def test_bozuk_girdi_istisna_atmaz(self):
		for girdi in (b"", b"\x00\x01\x02", b"not an image at all", bytes(4096)):
			with self.subTest(girdi=girdi[:8]):
				p = P.probe_header(girdi, filename="x.jpg")
				self.assertFalse(p.ok)

	def test_olmayan_dosya_ret_doner(self):
		p = P.probe_header(ROOT / "yok" / "boyle" / "dosya.jpg")
		self.assertFalse(p.ok)

	def test_assert_accepted_istisna_atar(self):
		yol = ROOT / "tradehub_core" / "tests" / "fixtures" / "malicious" / "bomb_100mp.png"
		with self.assertRaises(P.ImageRejected):
			P.assert_accepted(yol)

	def test_to_dict_serilestirilebilir(self):
		yol = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "images" / "ok_product_4x5.jpg"
		d = P.probe_header(yol, config=P.GuardConfig(max_megapixels=200.0)).to_dict()
		json.dumps(d)  # istisna atmamalı
		self.assertIn("megapixels", d)


if __name__ == "__main__":
	unittest.main(verbosity=2)

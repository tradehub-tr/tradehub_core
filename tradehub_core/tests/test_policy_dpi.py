"""T-024 — DPI ve piksel normalizasyon testleri.

İki şeyi doğrular:

1. **Slot policy JSON'ları tutarlı mı** (`docs/standards/policies/*.json`):
   `min_long_edge <= max_long_edge`, ürün slotlarında `min_long_edge >= 2000`.
2. **Motorun davranışı kuralla uyuşuyor mu** (`tradehub_core/media/pipeline.py`):
   DPI düşürmek çözünürlüğü DÜŞÜRMEZ; `im.thumbnail()` yalnız küçültür, upscale
   yapmaz.

Kural (bkz. `docs/standards/dpi-ve-cozunurluk.md`):
    DOĞRU : 3000×3000@300dpi → 2400×2400@72dpi  (piksel korunur, uzun kenar tavanı)
    YASAK : 3000×3000@300dpi →  720×720@72dpi   (DPI oranı piksele uygulanmış)

`engine.py` içinde `import frappe` YOKTUR — bu test site/bench/DB olmadan da
çalışır. İki çalıştırma biçimi:

    # 1) Bağımsız (yalnız Pillow gerekir) — bu dosyanın tercih edilen yolu
    python3 -m unittest discover -s /Users/ahmet/Desktop/istoc-medya-wt/tests -v

    # 2) Bench içinde (diğer medya testleriyle aynı koşu)
    docker exec istoc-dev-backend-1 bench --site istoc.localhost \\
        run-tests --module tradehub_core.tests.test_policy_dpi

MEVCUT TESTLERE DOKUNULMADI: `tradehub_core/tests/` altındaki dosyalar
değiştirilmedi; bu dosya repo kökündeki YENİ `tests/` klasöründe durur.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY_DIR = ROOT / "docs" / "standards" / "policies"

if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media import engine, presets  # noqa: E402

# T-024'ün mutlak tabanı: ürün görselinde uzun kenar bunun altına inemez.
URUN_MIN_LONG_EDGE = 2000

ZORUNLU_ALANLAR = (
	"slot_key",
	"doctype_field",
	"kind",
	"is_product_slot",
	"min_long_edge",
	"max_long_edge",
	"target_long_edge",
	"aspect_ratio",
	"aspect_tolerance",
	"fit",
	"dpi_policy",
	"olcum",
)


def _policy_dosyalari() -> list[Path]:
	"""`docs/standards/policies/*.json` — `_` ile başlayanlar şema/dokümandır."""
	return sorted(p for p in POLICY_DIR.glob("*.json") if not p.name.startswith("_"))


def _yukle(path: Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def _gurultulu_jpeg(w: int, h: int, dpi: int) -> bytes:
	"""Sıkışmayan (yani gerçekten büyük) bir test JPEG'i üret.

	Düz renk bir kare 3000×3000 bile birkaç KB'a sıkışır ve "boyut küçüldü"
	iddiasını ölçülemez hâle getirir. Gürültü, gerçek fotoğrafın entropisini
	kabaca taklit eder.

	`lru_cache`: aynı 3000×3000 gürültü karesi altı testte kullanılıyor; her
	seferinde yeniden üretmek koşuyu ~4 kat yavaşlatıyordu. Dönen `bytes`
	değişmez, paylaşmak güvenli.
	"""
	import random

	from PIL import Image

	im = Image.new("RGB", (w, h))
	px = im.load()
	random.seed(1)
	for y in range(0, h, 3):
		for x in range(0, w, 3):
			px[x, y] = (random.randrange(256), random.randrange(256), random.randrange(256))
	buf = io.BytesIO()
	im.save(buf, "JPEG", quality=95, dpi=(dpi, dpi))
	return buf.getvalue()


def _boyut(content: bytes) -> tuple[int, int]:
	from PIL import Image

	with Image.open(io.BytesIO(content)) as im:
		return im.size


# ---------------------------------------------------------------------------
# 1. Policy JSON tutarlılığı
# ---------------------------------------------------------------------------


class TestPolicyJsonTutarliligi(unittest.TestCase):
	"""Her slot policy JSON'u kendi içinde tutarlı olmalı."""

	def setUp(self):
		self.dosyalar = _policy_dosyalari()

	def test_policy_klasoru_bos_degil(self):
		"""Boş klasör, alttaki döngülü testleri sessizce "geçmiş" gösterirdi."""
		self.assertTrue(POLICY_DIR.is_dir(), f"policy klasörü yok: {POLICY_DIR}")
		self.assertGreater(len(self.dosyalar), 0, f"{POLICY_DIR} içinde policy JSON yok")

	def test_her_policy_gecerli_json_ve_zorunlu_alanlari_tasiyor(self):
		for path in self.dosyalar:
			with self.subTest(policy=path.name):
				pol = _yukle(path)
				for alan in ZORUNLU_ALANLAR:
					self.assertIn(alan, pol, f"{path.name}: '{alan}' alanı eksik")

	def test_dosya_adi_slot_key_ile_ayni(self):
		"""`slot_key` kanonik anahtar; dosya adıyla ayrışırsa iki ad ortaya çıkar."""
		for path in self.dosyalar:
			with self.subTest(policy=path.name):
				self.assertEqual(_yukle(path)["slot_key"], path.stem)

	def test_min_long_edge_max_long_edge_i_asmaz(self):
		"""**T-024 çekirdek kuralı.** `min > max` olan bir policy sağlanamaz —
		hiçbir dosya hem tabanı hem tavanı karşılamaz, slot her yüklemeyi reddeder.
		"""
		for path in self.dosyalar:
			with self.subTest(policy=path.name):
				pol = _yukle(path)
				mn, mx = pol["min_long_edge"], pol["max_long_edge"]
				self.assertIsInstance(mn, int)
				self.assertIsInstance(mx, int)
				self.assertGreater(mn, 0, f"{path.name}: min_long_edge pozitif olmalı")
				self.assertLessEqual(
					mn,
					mx,
					f"{path.name}: min_long_edge={mn} > max_long_edge={mx} — "
					"bu slota hiçbir dosya giremez",
				)

	def test_target_long_edge_min_max_araliginda(self):
		for path in self.dosyalar:
			with self.subTest(policy=path.name):
				pol = _yukle(path)
				self.assertGreaterEqual(pol["target_long_edge"], pol["min_long_edge"])
				self.assertLessEqual(pol["target_long_edge"], pol["max_long_edge"])

	def test_urun_slotunda_min_long_edge_en_az_2000(self):
		"""**T-024 çekirdek kuralı.** Ürün görselinde zoom 1:1 piksel ister;
		2000 px altı bir taban ürün sayfasında görünür yumuşamaya yol açar.
		"""
		urun_slotlari = [p for p in self.dosyalar if _yukle(p).get("is_product_slot")]
		self.assertGreater(
			len(urun_slotlari),
			0,
			"is_product_slot=true olan hiç policy yok — bu test boşa çalışıyor",
		)
		for path in urun_slotlari:
			with self.subTest(policy=path.name):
				mn = _yukle(path)["min_long_edge"]
				self.assertGreaterEqual(
					mn,
					URUN_MIN_LONG_EDGE,
					f"{path.name}: ürün slotu min_long_edge={mn} < {URUN_MIN_LONG_EDGE}",
				)

	def test_urun_olmayan_slot_urun_tabanini_tasimak_zorunda_degil(self):
		"""Ters yönü de bağla: ikon slotuna 2000 px taban koymak, `shipping_channel.
		icon` gibi 32 CSS px'lik bir kutuya 2000 px dosya yüklenmesini zorunlu
		kılardı. Bu test yalnız "ürün tabanı ürün-dışına sızmadı"yı ölçer.
		"""
		digerleri = [p for p in self.dosyalar if not _yukle(p).get("is_product_slot")]
		self.assertGreater(len(digerleri), 0)
		# En az bir ürün-dışı slot ürün tabanının altında olmalı — aksi hâlde
		# "ürün slotu" ayrımı anlamsızdır.
		altinda = [p for p in digerleri if _yukle(p)["min_long_edge"] < URUN_MIN_LONG_EDGE]
		self.assertGreater(
			len(altinda),
			0,
			"Hiçbir ürün-dışı slot 2000 px altında değil — is_product_slot ayrımı işlevsiz",
		)

	def test_dpi_policy_pikselin_korundugunu_soyluyor(self):
		"""DPI metadata'dır. Hiçbir slot "DPI düşünce piksel de düşer" diyemez."""
		for path in self.dosyalar:
			with self.subTest(policy=path.name):
				dpi = _yukle(path)["dpi_policy"]
				self.assertEqual(dpi["output_dpi"], 72, f"{path.name}: output_dpi 72 olmalı")
				self.assertIs(
					dpi["pixels_preserved"],
					True,
					f"{path.name}: pixels_preserved daima true olmalı — "
					"DPI değişimi çözünürlüğü düşürmez",
				)

	def test_free_oranda_tolerans_null(self):
		for path in self.dosyalar:
			with self.subTest(policy=path.name):
				pol = _yukle(path)
				if pol["aspect_ratio"] == "free":
					self.assertIsNone(pol["aspect_tolerance"])
				else:
					self.assertIsInstance(pol["aspect_tolerance"], (int, float))

	def test_max_long_edge_preset_tavanini_asmiyor(self):
		"""Policy tavanı motorun en yüksek presetinden büyük olamaz: `runner`
		`presets.resolve()` ile çalışır, policy'nin istediği 4000 px'i motor
		hiçbir presette üretemez — ilan edilen sınır yalan olurdu.
		"""
		preset_tavani = max(p["max_dim"] for p in presets.PRESETS.values())
		for path in self.dosyalar:
			with self.subTest(policy=path.name):
				self.assertLessEqual(
					_yukle(path)["max_long_edge"],
					preset_tavani,
					f"{path.name}: max_long_edge, presets.py tavanı {preset_tavani}'ı aşıyor",
				)


# ---------------------------------------------------------------------------
# 2. Motor davranışı — DPI piksel değildir
# ---------------------------------------------------------------------------


class TestEngineDpiPikselAyrimi(unittest.TestCase):
	"""`engine.optimize()` DPI'yi piksele karıştırmıyor mu."""

	def test_dpi_dususu_pikseli_dusurmez(self):
		"""DOĞRU davranış: 3000×3000@300dpi → 2400×2400 (tavan uygulandı, o kadar).

		YASAK olan 720×720 çıktısı, 72/300 oranının piksele uygulanmasıdır
		(3000 × 72/300 = 720). Bu test o hatayı yakalar.
		"""
		src = _gurultulu_jpeg(3000, 3000, dpi=300)

		res = engine.optimize(src, max_dim=2400, quality=88)

		self.assertTrue(res.ok, f"optimize başarısız: {res.reason}")
		self.assertEqual((res.width, res.height), (2400, 2400))
		self.assertEqual(_boyut(res.content), (2400, 2400))
		# YASAK çıktının açık reddi:
		self.assertNotEqual((res.width, res.height), (720, 720))
		self.assertGreaterEqual(min(res.width, res.height), 2400)

	def test_urun_tabani_2400_tavaninda_korunuyor(self):
		"""2400 px tavanla optimize edilen 300 dpi ürün fotosu, ürün slotunun
		2000 px tabanının ÜSTÜNDE kalır. (`listing.primary_image` policy'si.)
		"""
		src = _gurultulu_jpeg(3000, 3000, dpi=300)

		res = engine.optimize(src, max_dim=2400, quality=88)

		self.assertTrue(res.ok, res.reason)
		self.assertGreaterEqual(max(res.width, res.height), URUN_MIN_LONG_EDGE)

	def test_thumbnail_upscale_yapmaz(self):
		"""`engine.py:117` `im.thumbnail((max_dim, max_dim))` yalnız küçültür.

		Bu DOĞRU davranıştır: küçük dosyayı büyütmek bilgi eklemez, yalnız bayt
		ekler ve kullanıcıya "yükseltildi" yanılgısı verir. 800×600 bir dosya
		2000 px tavanla işlense bile 800×600 kalmalı.
		"""
		src = _gurultulu_jpeg(800, 600, dpi=300)

		res = engine.optimize(src, max_dim=2000, quality=88)

		if res.ok:
			self.assertEqual((res.width, res.height), (800, 600))
			self.assertEqual(_boyut(res.content), (800, 600))
		else:
			# Kazanç eşiğine takılmış olabilir; o hâlde de piksel değişmedi.
			self.assertIn(res.reason, ("gain_below_threshold", "empty_output"))

	def test_zaten_tavanin_altindaki_dosya_buyumez(self):
		"""1200 px dosya, 2560 px tavanla → hâlâ 1200 px (upscale yok)."""
		src = _gurultulu_jpeg(1200, 900, dpi=72)

		res = engine.optimize(src, max_dim=2560, quality=88)

		self.assertTrue(res.ok, res.reason)
		self.assertEqual(max(res.width, res.height), 1200)

	def test_dikdortgen_gorselde_yalniz_uzun_kenar_tavana_oturur(self):
		"""4000×2000 → tavan 2000 → 2000×1000. En-boy oranı korunur, kısa kenar
		bağımsız olarak kırpılmaz.
		"""
		src = _gurultulu_jpeg(4000, 2000, dpi=300)

		res = engine.optimize(src, max_dim=2000, quality=88)

		self.assertTrue(res.ok, res.reason)
		self.assertEqual((res.width, res.height), (2000, 1000))

	def test_optimize_ciktisinda_mutlak_dpi_metadatasi_yok(self):
		"""ÖLÇÜLEN EKSİK (T-024 §5): motor çıktıya DPI'yi AÇIKÇA 72 yazmıyor.

		`engine.py:120-123` JPEG kaydında `dpi=` parametresi geçilmediği için
		Pillow JFIF density'yi (1,1) / unit=0 yazar — yani "mutlak birim yok,
		yalnız 1:1 piksel oranı". Pratikte tüketiciler bunu 72 dpi varsayar,
		ama dosyada yazılı 72 YOKTUR.

		Bu test o durumu SABİTLER. Motora `dpi=(72,72)` eklenirse test kırılır
		ve `docs/standards/dpi-ve-cozunurluk.md` §5 güncellenmelidir — testin
		amacı budur, davranışı savunmak değil.

		Ölçüm: Pillow 11.3.0, bu makine, 2026-08-17. Üretimdeki Pillow sürümü
		doğrulanmadı (bkz. standardın §8-M1).
		"""
		from PIL import Image

		src = _gurultulu_jpeg(3000, 3000, dpi=300)
		with Image.open(io.BytesIO(src)) as kaynak:
			self.assertEqual(kaynak.info.get("dpi"), (300, 300))  # girdi 300 dpi

		res = engine.optimize(src, max_dim=2400, quality=88)
		self.assertTrue(res.ok, res.reason)

		with Image.open(io.BytesIO(res.content)) as cikti:
			# Girdinin 300 dpi'si taşınmadı — bu iyi.
			self.assertNotEqual(cikti.info.get("dpi"), (300, 300))
			# Ama yerine açıkça 72 de yazılmadı — bu eksik.
			self.assertIsNone(
				cikti.info.get("dpi"),
				"Motor artık DPI yazıyor: standardın §5 'eksik' maddesi güncellenmeli",
			)

	def test_to_webp_ciktisinda_dpi_alani_hic_yok(self):
		"""WebP biçiminde DPI alanı yoktur (yalnız isteğe bağlı EXIF/XMP chunk'ta).

		`engine.to_webp` (engine.py:180) EXIF yazmıyor → çıktıda DPI hiç bulunmaz.
		Bu, DPI'nin metadata olduğunun en somut kanıtı: piksel aynı, DPI yok.
		"""
		from PIL import Image

		src = _gurultulu_jpeg(2400, 2400, dpi=300)

		out = engine.to_webp(src, quality=80)

		with Image.open(io.BytesIO(out)) as im:
			self.assertEqual(im.format, "WEBP")
			self.assertIsNone(im.info.get("dpi"))


class TestUploadYoluTabaniKarsilamiyor(unittest.TestCase):
	"""BELGELENEN AÇIK — `docs/standards/dpi-ve-cozunurluk.md` §6-A1."""

	@unittest.expectedFailure
	def test_satici_upload_yolu_urun_slotu_tabanini_karsilar(self):
		"""BİLE BİLE BAŞARISIZ. `engine.to_webp` uzun kenarı 1920'ye sabitliyor
		(`engine.py:177` `im.thumbnail((1920, 1920))`); `api/seller_media.py:292`
		her satıcı görselini bu yoldan geçiriyor. 1920 < 2000 → ürün policy'sinin
		`min_long_edge` tabanı YÜKLEME ANINDA ihlal ediliyor.

		İstemci tarafı da aynı tavanı taşıyor:
		  - tradehubfront/src/lib/media/compress.image.ts:10 → HEDEF_GENISLIK = 1920
		  - admin-panel/frontend/src/lib/media/compress.image.js:9 → HEDEF_GENISLIK = 1920

		"expectedFailure" bilinçli: test yeşile dönerse (unexpected success)
		birisi tavanı düzeltmiş demektir ve standardın §6-A1 maddesi kapanmalıdır.
		"""
		src = _gurultulu_jpeg(3000, 3000, dpi=300)

		out = engine.to_webp(src, quality=80)

		self.assertGreaterEqual(max(_boyut(out)), URUN_MIN_LONG_EDGE)

	def test_mevcut_tavan_1920_olarak_sabitlendi(self):
		"""Yukarıdaki açığın ölçülmüş hâli — sayı değişirse burada görülür."""
		src = _gurultulu_jpeg(3000, 3000, dpi=300)

		out = engine.to_webp(src, quality=80)

		self.assertEqual(max(_boyut(out)), 1920)


if __name__ == "__main__":
	unittest.main(verbosity=2)

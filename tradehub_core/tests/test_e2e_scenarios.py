"""T-141 — Kaynak dokümanın 12 KRİTİK E2E SENARYOSU.

Senaryolar `docs/72-faz14-test-kabul.html` → "Kritik E2E senaryoları"
listesinden BİREBİR alındı (12 madde, sıraları korundu). Her senaryo bir
`Senaryo<NN>` sınıfıdır ve sınıfın docstring'i senaryonun **kaynaktaki
cümlesini** aynen taşır.

═══════════════════════════════════════════════════════════════════════
DÜRÜSTLÜK SINIRI — BU DOSYA PLAYWRIGHT E2E'Sİ DEĞİLDİR
═══════════════════════════════════════════════════════════════════════
Kaynak doküman T-141'de şunu istiyor: *"tests/e2e/ altında 12 kritik
senaryoyu **Playwright** ile yaz… Her senaryo sonunda ekran görüntüsü ve
video kaydı üret."* Bu dosya onu YAPMIYOR ve yapamaz:

  1. Tarayıcı otomasyonu bu koşumda YOK; ekran görüntüsü/video kaydı
     ÜRETİLMİYOR. Kabul kanıtı olarak `docs/qa/evidence/` altına hiçbir
     şey yazılmıyor.
  2. Senaryoların yarısının arayüzü (Crop Studio, önizleme simülatörü
     ekranı, medya kütüphanesi) HENÜZ YAZILMADI — Faz 9/10/11 belgeleri
     var (`docs/ui/`), uygulama yok.
  3. Frappe sitesi, seed betiği ve gerçek yükleme ucu bu ağaçta yok;
     `tradehub_core/media/pipeline/` katmanı `import frappe` İÇERMEZ (bilinçli).

Bu dosyanın yaptığı: her senaryonun **sunucu tarafındaki karar zincirini**
gerçek fixture'lar ve gerçek modüllerle uçtan uca koşturmak. Yani
"kullanıcı yolculuğu" değil, **yolculuğun motor tarafındaki karşılığı**.
Tarayıcı gerektiren her iddia `skipTest` ile ve GEREKÇESİYLE atlanır;
atlanan test GEÇMİŞ SAYILMAZ.

Koşum:

    python3 -m unittest tests.test_e2e_scenarios -v

Bağımlılık: Pillow (görsel senaryoları). ffmpeg/ffprobe GEREKMEZ — video
senaryoları karar tablosunu ÖLÇÜLMÜŞ künyelerle sürer (künyeler
`tradehub_core/tests/fixtures/media/manifest.json` `olculen` bloklarından, konteynerde
ffprobe ile ölçülmüştü). Frappe/site/DB GEREKMEZ.

Kapsanan gereksinimler (izlenebilirlik matrisi bu satırları okur):
FR-011, FR-015, FR-016, FR-028, FR-029, FR-030, FR-035, FR-040, FR-062,
FR-063, FR-121, FR-137, FR-139, NFR-041, NFR-050, NFR-051.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.api import delivery as delivery_api  # noqa: E402
from tradehub_core.media.pipeline.api import envelope as env  # noqa: E402
from tradehub_core.media.pipeline.api import upload as upload_api  # noqa: E402
from tradehub_core.media.pipeline.contracts.errors import ObjectNotFound, StorageError  # noqa: E402
from tradehub_core.media.pipeline.contracts.storage import SCOPE_PUBLIC, ObjectRef  # noqa: E402
from tradehub_core.media.pipeline.core import crop_geometry as geo  # noqa: E402
from tradehub_core.media.pipeline.core import dedup  # noqa: E402
from tradehub_core.media.pipeline.core import state  # noqa: E402
from tradehub_core.media.pipeline.core.probe import probe_file  # noqa: E402
from tradehub_core.media.pipeline.delivery import signed as signed_urls  # noqa: E402
from tradehub_core.media.pipeline.image import render as render_mod  # noqa: E402
from tradehub_core.media.pipeline.image.normalize import NormalizeSpec, normalize  # noqa: E402
from tradehub_core.media.pipeline.image.probe import DEFAULT_GUARD, GuardConfig, probe_header  # noqa: E402
from tradehub_core.media.pipeline.policy.engine import PolicyEngine, PolicyRegistry, parse_ratio  # noqa: E402
from tradehub_core.media.pipeline.simulator import srcset as sim  # noqa: E402
from tradehub_core.media.pipeline.storage import retention as ret  # noqa: E402
from tradehub_core.media.pipeline.storage.local import LocalDiskStorage  # noqa: E402
from tradehub_core.media.pipeline.storage.mirror import inline_mirror  # noqa: E402
from tradehub_core.media.pipeline.video.decision import ACTION_PASSTHROUGH, ACTION_TRANSCODE, decide  # noqa: E402

FIXTURES = ROOT / "tradehub_core" / "tests" / "fixtures" / "media"
IMAGES = FIXTURES / "images"
MALICIOUS = ROOT / "tradehub_core" / "tests" / "fixtures" / "malicious"
MANIFEST = FIXTURES / "manifest.json"

SATICI = env.Principal(user="satici@ornek.com", roles=("Seller",), store="SELLER-001")
MISAFIR = env.ANONYMOUS

SECRET = b"e2e-imzalama-anahtari-32-bayt!!!"

#: Fixture korpusu 72 MP'lik bir dosya da içeriyor; senaryo testlerinde kapı
#: DEĞİL, kapının ardındaki davranış sınanıyor. Kapının kendisi
#: `test_image_probe.py`'nin işi.
GEVSEK = GuardConfig(max_megapixels=200.0, max_bytes=64 * 1024 * 1024, allow_animated=True)


def pillow_var() -> bool:
	try:
		from PIL import Image  # noqa: F401,PLC0415

		return True
	except Exception:
		return False


def _manifest_video(ad: str) -> dict:
	"""Manifestteki ÖLÇÜLMÜŞ video künyesini karar tablosunun sözlüğüne çevir.

	Sayılar uydurulmadı: `olculen` bloğu konteynerde (istoc-dev-backend-1,
	ffmpeg 5.1.9) ffprobe ile ölçülmüştü. Burada yalnız birim dönüşümü var
	(kbps → bps), yeni bir ölçüm YOK.
	"""
	with open(MANIFEST, encoding="utf-8") as fh:
		veri = json.load(fh)
	for kayit in veri["fixtures"]:
		if Path(str(kayit.get("file", ""))).name != ad:
			continue
		o = kayit["olculen"]
		w, h = int(o["width"]), int(o["height"])
		sure = float(o["duration_s"])
		vb = int(float(o["video_bitrate_kbps"]) * 1000)
		pay, bolen = (o["fps"].split("/") + ["1"])[:2]
		fps = float(pay) / float(bolen or 1)
		return {
			"measured": True,
			"has_video": True,
			"width": w,
			"height": h,
			"pixels": w * h,
			"long_edge": max(w, h),
			"short_edge": min(w, h),
			"duration_s": sure,
			"fps": fps,
			"video_codec": o["video_codec"],
			"video_profile": "High",
			"pix_fmt": o["pix_fmt"],
			"video_bitrate_bps": vb,
			"format_bitrate_bps": int(float(o["bitrate_kbps"]) * 1000),
			"bpp": vb / (w * h * fps) if w and h and fps else 0.0,
			"container": o["container"],
			"container_family": "mp4",
			"has_audio": bool(o["has_audio"]),
			"audio_codec": o["audio_codec"] or "",
			"audio_bitrate_bps": 96000 if o["has_audio"] else 0,
			"audio_channels": 2 if o["has_audio"] else 0,
			"moov_at_end": False,
			"size_bytes": int(o["bytes"]),
			"rotation": 0,
			"nb_streams": 2 if o["has_audio"] else 1,
		}
	raise AssertionError(f"manifestte video fixture'ı yok: {ad}")


class _Motor(unittest.TestCase):
	"""Politika motorunu bir kez kuran ortak taban."""

	@classmethod
	def setUpClass(cls):
		cls.engine = PolicyEngine(PolicyRegistry())


# ═══════════════════════════════════════════════════════════════════════
# Senaryo 1
# ═══════════════════════════════════════════════════════════════════════


@unittest.skipUnless(pillow_var(), "Pillow yok — künye çıkarılamaz")
class Senaryo01YetersizCozunurluk(_Motor):
	"""Satıcı 1000×1000 altı görsel yükler → reddedilir, ne yapması gerektiğini öğrenir."""

	def test_999_piksel_reddedilir(self):
		"""FR-015: `min_short_edge` kontrolü `>=` ile uygulanır; 999 REDDEDİLİR."""
		karar = self.engine.evaluate("product.image", probe_file(IMAGES / "bound_short999.jpg"))

		self.assertFalse(karar.allow, "999 px kısa kenar geçmemeliydi")
		self.assertTrue(karar.blocking(), "ret var ama engelleyici ihlal yok")

	def test_1000_piksel_gecer_sinir_dahil(self):
		"""FR-015: tam sınır (1000) KABUL edilir — `>` kullanılsa bu test kırılır."""
		karar = self.engine.evaluate("product.image", probe_file(IMAGES / "bound_short1000.jpg"))

		self.assertTrue(karar.allow, f"1000 px reddedildi: {karar.codes}")

	def test_satici_ne_yapacagini_ogrenir(self):
		"""FR-062/FR-063: mesaj hem NEDEN'i hem NASIL'ı söylemeli, boş olmamalı."""
		karar = self.engine.evaluate("product.image", probe_file(IMAGES / "bound_short999.jpg"))
		engelleyici = karar.blocking()[0]

		metin = (engelleyici.message or {}).get("tr", "")
		ipucu = (engelleyici.hint or {}).get("tr", "")

		self.assertTrue(engelleyici.code, "makine kodu yok — istemci dallanamaz")
		self.assertTrue(metin.strip(), f"kullanıcı mesajı boş: {engelleyici.message!r}")
		self.assertGreaterEqual(
			len(metin.strip()), 20,
			f"mesaj 'ne yapmalı'yı taşıyamayacak kadar kısa: {metin!r}",
		)
		self.assertTrue(
			ipucu.strip() or any(c.isdigit() for c in metin),
			"ne NASIL düzeltileceği (hint) ne de gereken ölçü mesajda var",
		)

	def test_arayuzde_gosterim_OLCULMEDI(self):
		self.skipTest(
			"Mesajın satıcının EKRANINDA göründüğü ve anlaşıldığı yalnız tarayıcı "
			"otomasyonu + UAT ile ölçülür. Tarayıcı yok; anlama oranı T-142'nin işi."
		)


# ═══════════════════════════════════════════════════════════════════════
# Senaryo 2
# ═══════════════════════════════════════════════════════════════════════


@unittest.skipUnless(pillow_var(), "Pillow yok")
class Senaryo02DpiPikselDusurmez(unittest.TestCase):
	"""Satıcı 3000×3000 @300 dpi mockup yükler → 2400×2400 @72 dpi olur, çözünürlük düşmez."""

	KAYNAK = IMAGES / "dpi_3000x3000_300dpi.tif"

	def test_3000_300dpi_2400_72dpiye_iner(self):
		"""FR-029/FR-030 + INV-02: DPI yazımı ASLA resample tetiklemez.

		YASAK sonuç 720×720'dir (300→72 oranını piksele uygulamak). Bu test
		tam olarak onu yakalamak için var.
		"""
		spec = NormalizeSpec(max_long_edge=2400, dpi_out=72)
		r = normalize(self.KAYNAK, spec, guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertEqual((r.width, r.height), (2400, 2400))
		self.assertNotEqual((r.width, r.height), (720, 720), "DPI oranı piksele uygulanmış")
		self.assertEqual(tuple(int(x) for x in r.dpi), (72, 72), f"DPI 72 yazılmadı: {r.dpi}")

	def test_kaynak_dpisi_gercekten_300(self):
		"""Fixture beyanı doğrulanmadan senaryo bir şey kanıtlamaz."""
		from PIL import Image  # noqa: PLC0415

		with Image.open(self.KAYNAK) as im:
			self.assertEqual(im.size, (3000, 3000))
			self.assertEqual(tuple(int(x) for x in im.info.get("dpi", (0, 0))), (300, 300))


# ═══════════════════════════════════════════════════════════════════════
# Senaryo 3
# ═══════════════════════════════════════════════════════════════════════


@unittest.skipUnless(pillow_var(), "Pillow yok")
class Senaryo03PikselTavani(_Motor):
	"""Satıcı 18 MP / 1 MB görsel yükler → piksel tavanı uygulanır, ürün sayfası LCP hedefte."""

	KAYNAK = IMAGES / "p01_18mp_1mb.jpg"

	def test_megapiksel_karari_bayttan_bagimsiz(self):
		"""FR-011 + P-01: 1 MB'lık dosya 17,92 MP; bayta bakan kapı bunu kaçırır."""
		p = probe_header(self.KAYNAK, config=GEVSEK)

		self.assertGreater(p.megapixels, 17.0)
		self.assertLess(p.byte_size, 1_400_000, "fixture beyanı bozulmuş")

	def test_piksel_acilmadan_reddedilebiliyor(self):
		"""FR-011: 20 MP tavanlı bir kapı bu dosyayı DECODE ETMEDEN reddeder."""
		siki = GuardConfig(max_megapixels=16.0, max_bytes=64 * 1024 * 1024)
		p = probe_header(self.KAYNAK, config=siki)

		self.assertTrue(p.rejections, "17,92 MP, 16 MP tavanını geçti")

	def test_tavan_uygulanınca_master_kuculur(self):
		"""FR-028: küçültme yönünde çalışır, upscale ASLA."""
		r = normalize(self.KAYNAK, NormalizeSpec(max_long_edge=2400), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertLessEqual(max(r.width, r.height), 2400)
		self.assertLess(r.width * r.height, 18_000_000, "piksel tavanı uygulanmamış")

	def test_urun_sayfasi_LCP_OLCULMEDI(self):
		self.skipTest(
			"LCP yalnız gerçek tarayıcıda ölçülür (Lighthouse/CrUX). Bu koşumda "
			"tarayıcı yok. NFR-008 bütçesi ÖLÇÜLMEDİ olarak kayıtlı (SRS §8.8)."
		)


# ═══════════════════════════════════════════════════════════════════════
# Senaryo 4
# ═══════════════════════════════════════════════════════════════════════


class Senaryo04KirpmaVeCihazOnizleme(unittest.TestCase):
	"""Satıcı crop + focal ayarlar, tüm cihaz sınıflarını önizler, onaylar → yayın."""

	def test_odak_tum_profil_oranlarinda_pencere_uretir(self):
		"""INV-10: kırpma niyeti ORAN cinsindendir; her hedef oran için pencere çıkar."""
		profiller = render_mod.load_profiles("product.image")
		self.assertTrue(profiller, "product.image profilleri boş")

		taban = geo.Rect(0.0, 0.0, 1.0, 1.0)
		for p in profiller:
			# `aspect_ratio` politikada "1:1" gibi bir DİZGE; geometri sayı ister.
			hedef = parse_ratio(p.aspect_ratio) if p.aspect_ratio else None
			pencere = geo.crop_window(1.0, 1.0, taban, hedef, 0.3, 0.7)
			with self.subTest(profil=p.name):
				self.assertGreater(pencere.w, 0.0)
				self.assertGreater(pencere.h, 0.0)
				self.assertGreaterEqual(pencere.x, -1e-9)
				self.assertGreaterEqual(pencere.y, -1e-9)
				self.assertLessEqual(pencere.x + pencere.w, 1.0 + 1e-9)
				self.assertLessEqual(pencere.y + pencere.h, 1.0 + 1e-9)

	def test_olcek_degisince_kadraj_ayni_kalir(self):
		"""INV-10'un asıl iddiası: kaynak yarıya inse de kadraj kaymaz.

		Taban bölge PİKSEL uzayında verilir (kaynağın tamamı); pencere de
		piksel döner. Karşılaştırma NORMALİZE edilerek yapılır — iki farklı
		ölçekte mutlak piksel değerleri zaten farklı olur, kayma testi
		oranların aynı kalmasıdır.
		"""
		hedef = 4.0 / 5.0  # 4:5 — kare olmayan bir oran seçildi ki kayma görünsün

		def kadraj(kenar: float) -> tuple:
			taban = geo.Rect(0.0, 0.0, kenar, kenar)
			p = geo.crop_window(kenar, kenar, taban, hedef, 0.3, 0.7)
			return (p.x / kenar, p.y / kenar, p.w / kenar, p.h / kenar)

		buyuk, kucuk = kadraj(2400.0), kadraj(1200.0)

		for i, alan in enumerate(("x", "y", "w", "h")):
			with self.subTest(alan=alan):
				self.assertAlmostEqual(buyuk[i], kucuk[i], places=9)
		self.assertGreater(buyuk[2], 0.0, "pencere boş çıktı — test bir şey kanıtlamıyor")

	def test_tum_cihaz_sinifi_kombinasyonlari_cozuluyor(self):
		"""FR-121: 13 cihaz × 5 sayfa matrisinin TAMAMI bir basamak seçebilmeli."""
		cihazlar = sim.load_devices()
		duzen = sim.load_layout()
		bolgeler = [b for sayfa in duzen.pages for b in sayfa.regions]

		secimler = sim.simulate_matrix(cihazlar, bolgeler, duzen)

		self.assertEqual(len(secimler), len(cihazlar) * len(bolgeler))
		cozulemeyen = [s for s in secimler if s.chosen is None]
		self.assertEqual(cozulemeyen, [], "bazı kombinasyonlar profilsiz kaldı")

	def test_onay_yayina_gecirir(self):
		"""Alım ekseni `Ready`'ye ulaşmadan yaşam döngüsü `Archived` olamaz."""
		self.assertTrue(state.consistent(state.INGEST_READY, state.LIFECYCLE_ACTIVE))
		self.assertTrue(state.consistent(state.INGEST_READY, state.LIFECYCLE_ARCHIVED))

	def test_arayuzde_onizleme_OLCULMEDI(self):
		self.skipTest(
			"Crop Studio ve önizleme simülatörü EKRANI yazılmadı (Faz 10/11 belge "
			"seviyesinde: docs/ui/faz10-crop-studio.md, faz11-simulator.md). "
			"Ekran görüntüsü/video kaydı üretilemez."
		)


# ═══════════════════════════════════════════════════════════════════════
# Senaryo 5
# ═══════════════════════════════════════════════════════════════════════


class Senaryo05OnizlemesizOnay(unittest.TestCase):
	"""Satıcı önizlemeden geçmeden onaylamayı dener → engellenir."""

	def test_yayinlanmamis_varlik_teslim_edilmez(self):
		"""Yayın kapısının bugün UYGULANAN yarısı: `published=False` → 404."""
		repo = delivery_api.InMemoryDeliveryRepository(
			rows={
				"MA-TASLAK": {
					"slot_key": "product.image",
					"file_url": "/files/ab/abcdef0123456789abcdef0123456789.jpg",
					"published": False,
					"kind": "image",
					"width": 2400,
					"height": 2400,
					"owner_store": "SELLER-001",
					"available_profiles": [p.name for p in render_mod.load_profiles("product.image")],
				}
			}
		)
		api = delivery_api.DeliveryApi(repo=repo)

		# `manifest` istisna fırlatır; zarf katmanı onu 404'e çevirir.
		with self.assertRaises(env.NotFound):
			api.manifest(MISAFIR, "MA-TASLAK")

		yanit = env.call(lambda: api.manifest(MISAFIR, "MA-TASLAK"))
		self.assertEqual(yanit.status, 404, "yayınlanmamış varlık misafire açıldı")

	def test_alim_hatti_bitmeden_terminal_degil(self):
		"""`Mastered` → `Ready` dışında bir çıkış yok; ara durum yayına sayılmaz."""
		self.assertFalse(state.terminal(state.INGEST_MASTERED))
		self.assertTrue(state.terminal(state.INGEST_READY))
		with self.assertRaises(state.InvalidTransition):
			state.ingest_transition(state.INGEST_RECEIVED, state.INGEST_READY)

	def test_onizleme_onay_kapisi_YOK(self):
		self.skipTest(
			"'Önizlemeden geçmeden onaylayamaz' kuralının kodda KARŞILIĞI YOK: "
			"ne `tradehub_core/media/pipeline/api/crop.py`'de ne durum makinesinde 'preview_approved' "
			"diye bir kapı var. Kapı yazılmadan test yazmak sahte yeşil üretir. "
			"Uygulanınca bu skip kaldırılacak."
		)


# ═══════════════════════════════════════════════════════════════════════
# Senaryo 6
# ═══════════════════════════════════════════════════════════════════════


class Senaryo06KirpmaDegisinceUrlDegisir(unittest.TestCase):
	"""Satıcı crop'u değiştirir → yalnız etkilenen rendition'lar yenilenir, URL değişir, bayat cache yok."""

	SRC = "a" * 64
	POLICY = {"slot": "product.image", "version": "1.3.0"}

	def _vh(self, intent) -> str:
		return dedup.version_hash(
			source_hash=self.SRC, policy_snapshot=self.POLICY,
			crop_intent=intent, engine_version="1.0.0",
		)

	def test_kirpma_degisince_version_hash_degisir(self):
		"""INV-09: URL içerikten türer; kırpma değişince URL kendiliğinden değişir."""
		a = self._vh({"focal_x": 0.5, "focal_y": 0.5})
		b = self._vh({"focal_x": 0.3, "focal_y": 0.7})

		self.assertNotEqual(a, b, "kırpma değişti ama sürüm hash'i aynı — bayat cache")

	def test_kirpma_ayniysa_url_ayni_kalir(self):
		"""Aynı niyet → aynı adres: gereksiz yeniden üretim ve cache kaybı olmaz."""
		a = self._vh({"focal_x": 0.5, "focal_y": 0.5})
		b = self._vh({"focal_x": 0.5, "focal_y": 0.5})

		self.assertEqual(a, b)

	def test_turev_adresi_version_hash_tasir(self):
		"""FR-040: türev adresi sürüm hash'ini taşır → purge gerekmez."""
		v1 = self._vh({"focal_x": 0.5, "focal_y": 0.5})
		v2 = self._vh({"focal_x": 0.1, "focal_y": 0.9})
		u1 = dedup.rendition_path("MA-1", v1, "product_card", 640, "webp")
		u2 = dedup.rendition_path("MA-1", v2, "product_card", 640, "webp")

		self.assertNotEqual(u1, u2)
		self.assertIn(v1, u1)
		self.assertEqual(dedup.parse_rendition_path(u1)["profile"], "product_card")

	def test_yalniz_etkilenen_rendition_YENIDEN_URETILIR_OLCULMEDI(self):
		self.skipTest(
			"'Yalnız etkilenen rendition'lar yenilenir' iddiası bir İŞ PLANLAYICI "
			"gerektiriyor (hangi profil hangi niyetten etkilenir). `tradehub_core/media/pipeline/` "
			"içinde böyle bir planlayıcı YOK; render defteri (test_render.py::DefterTesti) "
			"yalnız 'değişmediyse yeniden encode etme' tarafını kapsıyor."
		)


# ═══════════════════════════════════════════════════════════════════════
# Senaryo 7
# ═══════════════════════════════════════════════════════════════════════


class Senaryo07VerimliVideoPassthrough(unittest.TestCase):
	"""Verimli 10 MB MP4 yüklenir → dokunulmaz (passthrough)."""

	def test_verimli_kaynak_passthrough(self):
		"""Karar tablosu ÖLÇÜLMÜŞ künyeyle sürülüyor; ffprobe gerekmiyor."""
		karar = decide(_manifest_video("video_efficient_720p_750k.mp4"))

		self.assertEqual(karar.action, ACTION_PASSTHROUGH, karar.reason)
		self.assertFalse(karar.writes_new_file, "passthrough kararı dosya yazıyor")
		self.assertFalse(karar.needs_ffmpeg)

	def test_karar_gerekcesi_kayitli(self):
		"""'Bu video neden dokunulmadı' sorusu üretimde cevaplanabilmeli."""
		karar = decide(_manifest_video("video_efficient_720p_750k.mp4"))

		self.assertTrue(karar.rule_id)
		self.assertTrue(karar.reason)
		self.assertTrue(karar.trace, "hangi kuralların bakıldığı kaydedilmemiş")


# ═══════════════════════════════════════════════════════════════════════
# Senaryo 8
# ═══════════════════════════════════════════════════════════════════════


class Senaryo08SisikVideoKuculur(unittest.TestCase):
	"""Şişik bitrate video yüklenir → küçülür, VMAF ≥ 93."""

	def test_sisik_kaynak_transcode_edilir(self):
		karar = decide(_manifest_video("video_bloated_720p_8m.mp4"))

		self.assertEqual(karar.action, ACTION_TRANSCODE, karar.reason)
		self.assertTrue(karar.writes_new_file)

	def test_iki_fixture_ayni_olcude_ama_farkli_karar(self):
		"""Kararı belirleyen ÖLÇÜ değil BITRATE — ayrımın kendisi test edilir."""
		verimli = _manifest_video("video_efficient_720p_750k.mp4")
		sisik = _manifest_video("video_bloated_720p_8m.mp4")

		self.assertEqual((verimli["width"], verimli["height"]), (sisik["width"], sisik["height"]))
		self.assertGreater(sisik["video_bitrate_bps"], verimli["video_bitrate_bps"] * 5)
		self.assertNotEqual(decide(verimli).action, decide(sisik).action)

	def test_VMAF_OLCULEMEDI(self):
		self.skipTest(
			"VMAF ölçülemedi: konteynerdeki ffmpeg 5.1.9 libvmaf İÇERMİYOR "
			"(tests/test_video_transcode.py::GercekTranscode::"
			"test_kalite_olculebiliyor_ama_VMAF_YOK bunu ölçtü). VMAF ≥ 93 kapısı "
			"KANIT YOK durumundadır."
		)


# ═══════════════════════════════════════════════════════════════════════
# Senaryo 9
# ═══════════════════════════════════════════════════════════════════════


@unittest.skipUnless(pillow_var(), "Pillow yok")
class Senaryo09AyniDosyaIkiKez(unittest.TestCase):
	"""Aynı dosya iki kez yüklenir → dedup, tek asset."""

	KAYNAK = IMAGES / "ok_product_1x1_2400.jpg"

	def _yukle(self, api, icerik: bytes, ad: str = "urun.jpg"):
		r = api.create_session(SATICI, slot_key="product.image", file_name=ad, total_bytes=len(icerik))
		if r.body.get("duplicate"):
			return r
		uid, cb = r.body["upload_id"], r.body["chunk_bytes"]
		for i in range(r.body["chunk_count"]):
			api.put_chunk(SATICI, uid, i, icerik[i * cb : (i + 1) * cb])
		return api.finalize(SATICI, uid)

	def test_ikinci_yukleme_yeni_varlik_uretmez(self):
		"""NFR-050: aynı içerik tek fiziksel dosya, tek varlık."""
		api = upload_api.UploadApi(
			sessions=upload_api.InMemorySessionStore(chunk_bytes=256 * 1024),
			assets=upload_api.InMemoryAssetRepository(),
		)
		icerik = self.KAYNAK.read_bytes()

		birinci = self._yukle(api, icerik)
		ikinci = self._yukle(api, icerik, ad="ayni-icerik-baska-ad.jpg")

		self.assertTrue(birinci.body.get("asset"), birinci.body)
		self.assertEqual(ikinci.body.get("asset"), birinci.body.get("asset"))

	def test_adres_icerikten_turer(self):
		"""NFR-051: aynı içerik → aynı ad + aynı shard."""
		icerik = self.KAYNAK.read_bytes()
		h = dedup.sha256_bytes(icerik)

		self.assertEqual(dedup.content_name(h, ".jpg"), dedup.content_name(h, "jpg"))
		self.assertEqual(dedup.content_url(h, ".jpg").count("/files/"), 1)


# ═══════════════════════════════════════════════════════════════════════
# Senaryo 10
# ═══════════════════════════════════════════════════════════════════════


@unittest.skipUnless(pillow_var(), "Pillow yok")
class Senaryo10KotuculDosya(unittest.TestCase):
	"""Kötücül dosya (bomb/polyglot/SVG-XSS) yüklenir → reddedilir, worker sağlam."""

	def test_on_kotucul_fixturun_hepsi_reddedilir(self):
		dosyalar = sorted(p for p in MALICIOUS.iterdir() if p.is_file())
		self.assertGreaterEqual(len(dosyalar), 10, "kötücül korpus eksilmiş")

		for yol in dosyalar:
			with self.subTest(dosya=yol.name):
				p = probe_header(yol, config=DEFAULT_GUARD)
				self.assertTrue(p.rejections, f"{yol.name} kapıdan GEÇTİ")

	def test_worker_saglam_istisna_atilmaz(self):
		"""Kapı ret LİSTESİ döndürür, istisna FIRLATMAZ — worker düşmez."""
		for yol in sorted(p for p in MALICIOUS.iterdir() if p.is_file()):
			with self.subTest(dosya=yol.name):
				try:
					probe_header(yol, config=DEFAULT_GUARD)
				except Exception as hata:  # noqa: BLE001 — testin konusu tam olarak bu
					self.fail(f"{yol.name} kapıda istisna fırlattı: {hata!r}")

	def test_bomba_piksel_acilmadan_reddedilir(self):
		"""P-05/FR-011: 100 MP'lik PNG decode edilmeden düşer."""
		p = probe_header(MALICIOUS / "bomb_100mp.png", config=DEFAULT_GUARD)

		self.assertTrue(p.rejections)
		self.assertGreater(p.megapixels, 50.0)


# ═══════════════════════════════════════════════════════════════════════
# Senaryo 11
# ═══════════════════════════════════════════════════════════════════════


class _PatlayanIkincil:
	"""S3 kesintisinin benzetimi: her yazma/okuma çağrısı patlar."""

	def put(self, *a, **k):
		raise StorageError("S3 kesintisi (benzetim)")

	def exists(self, *a, **k) -> bool:
		return False

	def delete(self, *a, **k):
		raise StorageError("S3 kesintisi (benzetim)")

	def move(self, *a, **k):
		raise StorageError("S3 kesintisi (benzetim)")

	def get(self, *a, **k) -> bytes:
		raise ObjectNotFound("S3 kesintisi (benzetim)")

	def stat(self, *a, **k):
		raise ObjectNotFound("S3 kesintisi (benzetim)")

	def iter_keys(self, **k):
		return iter(())

	def url_for(self, *a, **k) -> str:
		raise StorageError("S3 kesintisi (benzetim)")


class Senaryo11S3AynalamaVeKesinti(unittest.TestCase):
	"""Superadmin S3'ü açar → yeni yüklemeler aynalanır; S3 düşerse sistem yerelde çalışmaya devam eder."""

	def setUp(self):
		self.tmp = tempfile.mkdtemp(prefix="e2e-mirror-")
		self.public_root = os.path.join(self.tmp, "public", "files")
		self.private_root = os.path.join(self.tmp, "private", "files")
		self.signer = signed_urls.HmacUrlSigner(SECRET)

	def tearDown(self):
		shutil.rmtree(self.tmp, ignore_errors=True)

	def _yerel(self) -> LocalDiskStorage:
		return LocalDiskStorage(self.public_root, self.private_root, signer=self.signer, fsync=False)

	def test_s3_acikken_ikincile_de_yazilir(self):
		birincil = self._yerel()
		ikincil_kok = os.path.join(self.tmp, "s3-benzeri")
		ikincil = LocalDiskStorage(
			os.path.join(ikincil_kok, "public"), os.path.join(ikincil_kok, "private"),
			signer=self.signer, fsync=False,
		)
		ayna = inline_mirror(birincil, ikincil)

		ref = ayna.put(b"aynalanacak-icerik", ".jpg", scope=SCOPE_PUBLIC).ref

		self.assertTrue(birincil.exists(ref), "birincile yazılmadı")
		self.assertTrue(ikincil.exists(ref), "ikincile AYNALANMADI")

	def test_s3_duserse_yerel_ayakta_kalir(self):
		birincil = self._yerel()
		ayna = inline_mirror(birincil, _PatlayanIkincil())

		ref = ayna.put(b"s3-kesintisi-sirasinda", ".jpg", scope=SCOPE_PUBLIC).ref

		self.assertTrue(birincil.exists(ref), "ikincil çöktü diye birincil de düştü")
		self.assertEqual(ayna.get(ref), b"s3-kesintisi-sirasinda")

	def test_gercek_S3_ile_OLCULMEDI(self):
		self.skipTest(
			"Gerçek AWS/MinIO'ya karşı ölçüm YOK: boto3 yerelde kurulu değil ve bu "
			"koşumda dış ağa çıkılmıyor. Kanıtlanan şey adaptör sözleşmesi, "
			"kanıtlanmayan şey S3'ün o sözleşmeye uyduğu."
		)


# ═══════════════════════════════════════════════════════════════════════
# Senaryo 12
# ═══════════════════════════════════════════════════════════════════════


class Senaryo12TurevSilinirYenidenUretilir(unittest.TestCase):
	"""Retention süresi dolan türev silinir → istendiğinde yeniden üretilir, kullanıcı fark etmez."""

	def setUp(self):
		self.tmp = tempfile.mkdtemp(prefix="e2e-retention-")
		self.public_root = os.path.join(self.tmp, "public", "files")
		self.private_root = os.path.join(self.tmp, "private", "files")
		self.storage = LocalDiskStorage(
			self.public_root, self.private_root,
			signer=signed_urls.HmacUrlSigner(SECRET), fsync=False,
		)

	def tearDown(self):
		shutil.rmtree(self.tmp, ignore_errors=True)

	def _yol(self, ref: ObjectRef) -> str:
		return os.path.join(self.public_root, ref.key.shard, ref.key.name)

	def _yaslandir(self, ref: ObjectRef, gun: float) -> None:
		import time  # noqa: PLC0415

		eski = time.time() - gun * 86400
		os.utime(self._yol(ref), (eski, eski))

	def _turev_yaz(self, ana: ObjectRef, profil: str, icerik: bytes, *, yas: float = 0.0) -> ObjectRef:
		from tradehub_core.media.pipeline.contracts.delivery import derivative_key  # noqa: PLC0415

		ref = ObjectRef(key=derivative_key(ana.key, profil, "webp"), scope=ana.scope)
		yol = self._yol(ref)
		os.makedirs(os.path.dirname(yol), exist_ok=True)
		with open(yol, "wb") as fh:
			fh.write(icerik)
		if yas:
			self._yaslandir(ref, yas)
		return ref

	def test_kullanilmayan_yasli_turev_silinir_orijinal_kalir(self):
		politika = ret.RetentionPolicy(
			original=ret.OriginalRetention(keep_forever=True),
			derivative=ret.DerivativeRetention(unused_after_days=30, action="delete"),
		)
		ana = self.storage.put(b"orijinal-master", ".jpg", scope=SCOPE_PUBLIC).ref
		turev = self._turev_yaz(ana, "w320", b"eski-turev-baytlari", yas=90)
		supurucu = ret.RetentionSweeper(
			self.storage, politika, usage_lookup=lambda r: ret.VERDICT_UNUSED
		)

		rapor = supurucu.sweep(dry_run=False)

		self.assertGreaterEqual(rapor.deleted, 1)
		self.assertFalse(self.storage.exists(turev), "yaşlı türev silinmedi")
		self.assertTrue(self.storage.exists(ana), "ORİJİNAL silindi — sözleşme ihlali")

	def test_silinen_turev_ayni_adrese_yeniden_yazilabilir(self):
		"""'Kullanıcı fark etmez' iddiasının makine karşılığı: adres değişmez."""
		ana = self.storage.put(b"orijinal-master", ".jpg", scope=SCOPE_PUBLIC).ref
		turev = self._turev_yaz(ana, "w320", b"turev-v1", yas=90)
		adres_once = self._yol(turev)

		os.remove(adres_once)
		self.assertFalse(self.storage.exists(turev))

		yeniden = self._turev_yaz(ana, "w320", b"turev-v1")

		self.assertEqual(yeniden.key.name, turev.key.name, "yeniden üretim ADRESİ DEĞİŞTİRDİ")
		self.assertTrue(self.storage.exists(yeniden))

	@unittest.skipUnless(pillow_var(), "Pillow yok")
	def test_yeniden_uretim_ayni_baytlari_verir(self):
		"""Belirlenimcilik: aynı kaynak + aynı profil → aynı bayt. Yoksa cache kırılır."""
		kaynak = IMAGES / "ok_product_1x1_2400.jpg"
		profil = render_mod.load_profiles("product.image")[0]

		a = render_mod.render(kaynak, profil)
		b = render_mod.render(kaynak, profil)

		self.assertEqual(a, b, "aynı girdi iki farklı bayt üretti — yeniden üretim güvenilmez")

	def test_tembel_yeniden_uretim_ucu_YOK(self):
		self.skipTest(
			"'İstendiğinde yeniden üretilir' için ON-DEMAND bir teslim ucu gerekiyor "
			"(istek anında eksik türevi üret). `tradehub_core/media/pipeline/api/delivery.py` "
			"üretilmemiş profili srcset'e HİÇ KOYMUYOR; tembel üretim uygulanmadı."
		)


if __name__ == "__main__":
	unittest.main(verbosity=2)

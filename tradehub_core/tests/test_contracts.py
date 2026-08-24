"""T-031 — arayüz sözleşmesi testleri (parametrize).

Testler UYGULAMAYA değil SÖZLEŞMEYE bakar. Her sözleşme testi bir uygulama
listesi üzerinde döner (`STORAGE_IMPLS`, `IMAGE_IMPLS`, ...); bugün listelerde
yalnız `tradehub_core/media/pipeline/fakes/` altındaki uygulamalar var. Gerçek uygulama
(Pillow/ffmpeg/disk) yazıldığında listeye TEK SATIR eklenir ve aynı testler
onu da denetler — sözleşmenin "dondurulmuş" olmasının pratik anlamı budur.

Çalıştırma (bağımlılık yok — Pillow/ffmpeg/frappe/site GEREKMEZ):

    python3 -m unittest discover -s /Users/ahmet/Desktop/istoc/tradehub_core/tests -v

    docker exec -w /home/frappe/frappe-bench/sites istoc-dev-backend-1 \\
        ../env/bin/python -m unittest discover -s <repo>/tests -v

MEVCUT KODA DOKUNULMADI: `tradehub_core/media/` altındaki çalışan motor bu
testlerin kapsamında değil; burada yalnız `tradehub_core/media/pipeline/` sözleşmeleri var.
"""

from __future__ import annotations

import inspect
import json
import shutil
import sys
import tempfile
import typing
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.contracts import CORE_PROTOCOLS  # noqa: E402
from tradehub_core.media.pipeline.contracts import delivery as delivery_c  # noqa: E402
from tradehub_core.media.pipeline.contracts import errors as errors_c  # noqa: E402
from tradehub_core.media.pipeline.contracts import image as image_c  # noqa: E402
from tradehub_core.media.pipeline.contracts import policy as policy_c  # noqa: E402
from tradehub_core.media.pipeline.contracts import signatures as signatures_c  # noqa: E402
from tradehub_core.media.pipeline.contracts import storage as storage_c  # noqa: E402
from tradehub_core.media.pipeline.contracts import video as video_c  # noqa: E402
from tradehub_core.media.pipeline.fakes.delivery import SimpleDeliveryManifest  # noqa: E402
from tradehub_core.media.pipeline.fakes.image import FakeImageEngine, sentetik_gorsel  # noqa: E402
from tradehub_core.media.pipeline.fakes.policy import InMemoryPolicyEngine  # noqa: E402
from tradehub_core.media.pipeline.fakes.storage import MAX_TTL_SECONDS, InMemoryStorage  # noqa: E402
from tradehub_core.media.pipeline.fakes.video import FakeVideoEngine, sentetik_video  # noqa: E402
from tradehub_core.media.pipeline.image.engine import PillowImageEngine  # noqa: E402
from tradehub_core.media.pipeline.policy.engine import (  # noqa: E402
	PolicyEngine as UretimPolicyEngine,
)
from tradehub_core.media.pipeline.policy.engine import (  # noqa: E402
	PolicyRegistry as UretimPolicyRegistry,
)
from tradehub_core.media.pipeline.video.engine import FfmpegVideoEngine  # noqa: E402

POLICY_ROOT = ROOT / "tradehub_core" / "media" / "pipeline" / "policy" / "slots"

# ── uygulama listeleri — gerçek uygulama gelince buraya eklenir ─────────

STORAGE_IMPLS = (("InMemoryStorage", InMemoryStorage),)
IMAGE_IMPLS = (("FakeImageEngine", FakeImageEngine),)
VIDEO_IMPLS = (("FakeVideoEngine", FakeVideoEngine),)


def _fake_policy_engine() -> InMemoryPolicyEngine:
	return InMemoryPolicyEngine.from_directory(str(POLICY_ROOT))


def _uretim_policy_engine() -> UretimPolicyEngine:
	"""`api/upload.py`, `api/admin.py` ve `simulator/srcset.py` BUNU çağırır."""
	return UretimPolicyEngine(UretimPolicyRegistry(POLICY_ROOT))


#: T-033 — sözleşme artık İKİ uygulama üzerinde koşuyor. Birincisi bellek-içi
#: referans, ikincisi ÜRETİM motoru. Liste tek elemanlıyken (yalnız sahte)
#: 69 sözleşme testi üretim kodunun tek satırına bile dokunmuyordu.
POLICY_IMPLS = (
	("InMemoryPolicyEngine", _fake_policy_engine),
	("PolicyEngine", _uretim_policy_engine),
)


def _policy_engine() -> InMemoryPolicyEngine:
	"""Sözleşmenin GİRDİSİ olarak politika okuyan testler için tek örnek."""
	return _fake_policy_engine()


#: T-033 kapanış kapısı: iki okuyucu arasında bilinen karar sapması kalamaz.
POLICY_SAPMALARI: dict = {}


# ═══════════════════════════════════════════════════════════════════════
# 1. Protokol uygunluğu ve imza dondurma
# ═══════════════════════════════════════════════════════════════════════


class ProtocolConformanceTest(unittest.TestCase):
	"""Her uygulama kendi `Protocol`'ünü karşılıyor mu."""

	def _ciftler(self) -> tuple:
		motor = _policy_engine()
		uretim = _uretim_policy_engine()
		return (
			(storage_c.StorageAdapter, InMemoryStorage()),
			(image_c.ImageEngine, FakeImageEngine()),
			(image_c.ImageEngine, PillowImageEngine()),
			(video_c.VideoEngine, FakeVideoEngine()),
			(video_c.VideoEngine, FfmpegVideoEngine()),
			(policy_c.PolicyEngine, motor),
			(policy_c.PolicyEngine, uretim),
			(delivery_c.DeliveryManifest, SimpleDeliveryManifest(motor)),
			(delivery_c.DeliveryManifest, SimpleDeliveryManifest(uretim)),
		)

	def test_bes_cekirdek_protokol_var(self):
		adlar = [p.__name__ for p in CORE_PROTOCOLS]
		self.assertEqual(
			adlar,
			["StorageAdapter", "ImageEngine", "VideoEngine", "PolicyEngine", "DeliveryManifest"],
		)

	def test_uygulamalar_isinstance_gecer(self):
		for protokol, uygulama in self._ciftler():
			with self.subTest(protokol=protokol.__name__, uygulama=type(uygulama).__name__):
				self.assertIsInstance(uygulama, protokol)

	def test_uretim_motoru_protokolu_karsiliyor(self):
		"""T-033 kabul ölçütü — ÖLÇÜM, iddia değil.

		Bu testin yazıldığı gün ölçülen durum: Protokolde 13 metot,
		`policy/engine.py::PolicyEngine` yüzeyinde `evaluate` +
		`normalized_targets`, kesişim BOŞ. Aşağıdaki eşitlik o boşluğun
		kapandığını makine olarak kanıtlar.
		"""
		protokol_metotlari = {
			ad for ad, uye in vars(policy_c.PolicyEngine).items()
			if callable(uye) and not ad.startswith("_")
		}
		self.assertEqual(len(protokol_metotlari), 13)
		eksik = {ad for ad in protokol_metotlari if not hasattr(UretimPolicyEngine, ad)}
		self.assertEqual(eksik, set(), f"Üretim sınıfında olmayan sözleşme metotları: {eksik}")
		self.assertIsInstance(_uretim_policy_engine(), policy_c.PolicyEngine)

	def test_imzalar_birebir_ayni(self):
		"""`runtime_checkable` yalnız adın VARLIĞINA bakar — imza BURADA denetlenir.

		İki ayrı şey ölçülür:

		1. **Parametre listesi** metin olarak birebir aynı mı; aksi hâlde
		   parametresi değişmiş bir uygulama sessizce "uyumlu" görünürdü.
		2. **Dönüş tipi ÇÖZÜLDÜĞÜNDE** semantik olarak aynı mı. Python 3.9+
		   `tuple[str, ...]` ile eski `typing.Tuple[str, ...]` aynı tiptir;
		   yazım farkı kabul edilir, gerçek sınıf/parametre farkı edilmez.
		"""
		for protokol, uygulama in self._ciftler():
			for ad, uye in vars(protokol).items():
				if ad.startswith("_") or not callable(uye):
					continue
				with self.subTest(
					protokol=protokol.__name__, uygulama=type(uygulama).__name__, metot=ad
				):
					gercek_fn = getattr(type(uygulama), ad)
					self.assertEqual(
						_sadelestir(_parametreler(uye)),
						_sadelestir(_parametreler(gercek_fn)),
					)
					self.assertTrue(
						_tip_esdeger(
							typing.get_type_hints(uye).get("return"),
							typing.get_type_hints(gercek_fn).get("return"),
						),
						"Dönüş tipi sözleşmenin tipi değil.",
					)


def _parametreler(fn) -> str:
	"""İmzanın YALNIZ parametre kısmı — dönüş tipi ayrıca ve çözülerek ölçülür."""
	return "(" + ", ".join(str(p) for p in inspect.signature(fn).parameters.values()) + ")"


def _sadelestir(imza: str) -> str:
	"""Tırnak ve boşluk gürültüsünü at — `'str'` ile `str` aynı sayılır."""
	return imza.replace("'", "").replace('"', "").replace(" ", "")


def _tip_esdeger(sol, sag) -> bool:
	"""PEP 585 yazımı ile ``typing`` yazımını aynı, iç tipleri kesin say."""
	if sol == sag:
		return True
	sol_kok = typing.get_origin(sol)
	sag_kok = typing.get_origin(sag)
	if sol_kok != sag_kok:
		return False
	sol_args = typing.get_args(sol)
	sag_args = typing.get_args(sag)
	return len(sol_args) == len(sag_args) and all(
		_tip_esdeger(a, b) for a, b in zip(sol_args, sag_args, strict=True)
	)


class SignatureGoldenTest(unittest.TestCase):
	"""CI kapısı: imza altın dosyasıyla birebir uyuşmalı (T-031 KK-4)."""

	def test_altin_dosya_guncel(self):
		golden = signatures_c.oku_golden()
		mevcut = signatures_c.topla()
		self.assertEqual(
			json.dumps(golden, sort_keys=True, ensure_ascii=False),
			json.dumps(mevcut, sort_keys=True, ensure_ascii=False),
			"Sözleşme imzası değişmiş. Bilinçliyse: "
			"python3 -m tradehub_core.media.pipeline.contracts.signatures --write",
		)

	def test_altin_dosya_bes_protokolu_kapsiyor(self):
		golden = signatures_c.oku_golden()
		self.assertEqual(len(golden["protocols"]), 5)
		self.assertTrue(golden["value_types"])


# ═══════════════════════════════════════════════════════════════════════
# 2. StorageAdapter sözleşmesi
# ═══════════════════════════════════════════════════════════════════════


class StorageContractTest(unittest.TestCase):
	def test_anahtar_deterministik_ve_shardli(self):
		a = storage_c.key_for(b"merhaba", ".jpg")
		b = storage_c.key_for(b"merhaba", "jpg")
		self.assertEqual(a, b)
		self.assertEqual(a.shard, a.name[:2])
		self.assertEqual(len(a.name), storage_c.HASH_LENGTH + 4)

	def test_url_ayristirma_ve_yol_gecisi(self):
		key, scope = storage_c.key_from_url("/private/files/ab/abcd.jpg")
		self.assertEqual(scope, storage_c.SCOPE_PRIVATE)
		self.assertEqual(key.relative, "ab/abcd.jpg")
		for kotu in ("/files/../etc/passwd", "/etc/passwd", "", "/files/abcd.jpg"):
			with self.subTest(url=kotu):
				with self.assertRaises(ValueError):
					storage_c.key_from_url(kotu)

	def test_put_idempotent_ve_catisma(self):
		for ad, fabrika in STORAGE_IMPLS:
			with self.subTest(uygulama=ad):
				depo = fabrika()
				ilk = depo.put(b"veri", ".jpg")
				ikinci = depo.put(b"veri", ".jpg")
				self.assertTrue(ilk.created)
				self.assertFalse(ikinci.created)
				self.assertEqual(ilk.ref, ikinci.ref)
				self.assertEqual(len(depo), 1)

	def test_catisma_farkli_icerik_ayni_anahtar(self):
		depo = InMemoryStorage()
		ref = depo.put(b"veri", ".jpg").ref
		depo._objects[(ref.scope, ref.key.relative)] = (b"baska", 0.0)
		with self.assertRaises(errors_c.StorageConflict):
			depo.put(b"veri", ".jpg")

	def test_okuma_ve_yok_hatasi(self):
		for ad, fabrika in STORAGE_IMPLS:
			with self.subTest(uygulama=ad):
				depo = fabrika()
				ref = depo.put(b"veri", ".png").ref
				self.assertEqual(depo.get(ref), b"veri")
				self.assertTrue(depo.exists(ref))
				self.assertEqual(depo.stat(ref).size_bytes, 4)
				yok = storage_c.ObjectRef(key=storage_c.key_for(b"yok", ".png"))
				self.assertFalse(depo.exists(yok))
				with self.assertRaises(errors_c.ObjectNotFound):
					depo.get(yok)
				with self.assertRaises(errors_c.ObjectNotFound):
					depo.stat(yok)

	def test_delete_idempotent(self):
		for ad, fabrika in STORAGE_IMPLS:
			with self.subTest(uygulama=ad):
				depo = fabrika()
				ref = depo.put(b"veri", ".png").ref
				self.assertTrue(depo.delete(ref))
				self.assertFalse(depo.delete(ref))

	def test_move_anahtari_korur(self):
		for ad, fabrika in STORAGE_IMPLS:
			with self.subTest(uygulama=ad):
				depo = fabrika()
				ref = depo.put(b"veri", ".pdf", scope=storage_c.SCOPE_PUBLIC).ref
				yeni = depo.move(ref, storage_c.SCOPE_PRIVATE)
				self.assertEqual(yeni.key, ref.key)
				self.assertTrue(yeni.url.startswith("/private/files/"))
				self.assertFalse(depo.exists(ref))
				with self.assertRaises(errors_c.ObjectNotFound):
					depo.move(ref, storage_c.SCOPE_PRIVATE)

	def test_iter_keys_kapsam_ayirir(self):
		depo = InMemoryStorage()
		depo.put(b"a", ".jpg", scope=storage_c.SCOPE_PUBLIC)
		depo.put(b"b", ".jpg", scope=storage_c.SCOPE_PRIVATE)
		self.assertEqual(len(list(depo.iter_keys(scope=storage_c.SCOPE_PUBLIC))), 1)
		self.assertEqual(len(list(depo.iter_keys(scope=storage_c.SCOPE_PRIVATE))), 1)

	def test_url_for_public_ttl_yok_sayar_private_clamp_eder(self):
		depo = InMemoryStorage()
		acik = depo.put(b"a", ".jpg").ref
		self.assertEqual(depo.url_for(acik, ttl_seconds=99999), acik.url)
		gizli = depo.put(b"b", ".jpg", scope=storage_c.SCOPE_PRIVATE).ref
		imzali = depo.url_for(gizli, ttl_seconds=10**9)
		self.assertIn("sig=", imzali)
		expires = int(imzali.split("expires=")[1].split("&")[0])
		import time as _t

		self.assertLessEqual(expires - int(_t.time()), MAX_TTL_SECONDS + 1)


# ═══════════════════════════════════════════════════════════════════════
# 3. ImageEngine sözleşmesi
# ═══════════════════════════════════════════════════════════════════════

URUN_MASTER = image_c.MasterSpec(
	max_long_edge=2400,
	format="webp",
	min_long_edge=2000,
	max_megapixels=5.76,
	dpi_out=72,
	colorspace="srgb",
	strip_metadata={"exif": True, "gps": True, "xmp": True, "icc": False},
)


class ImageContractTest(unittest.TestCase):
	def test_probe_okunamayan_icerikte_hata_atmaz(self):
		for ad, fabrika in IMAGE_IMPLS:
			with self.subTest(uygulama=ad):
				p = fabrika().probe(b"bu bir gorsel degil")
				self.assertFalse(p.readable)
				self.assertEqual(p.width, 0)

	def test_probe_megapiksel_bombasini_reddeder(self):
		"""FR-011/FR-143 — 179 dosya >20MP ölçüldü; tavan aşılınca açılmaz."""
		icerik = sentetik_gorsel("JPEG", 12000, 9000)
		for ad, fabrika in IMAGE_IMPLS:
			with self.subTest(uygulama=ad):
				with self.assertRaises(errors_c.OversizedImage):
					fabrika().probe(icerik, max_megapixels=80)
				self.assertTrue(fabrika().probe(icerik).readable)

	def test_master_yalniz_kucultur(self):
		"""FR-028 — upscale yok."""
		kucuk = sentetik_gorsel("JPEG", 800, 600)
		for ad, fabrika in IMAGE_IMPLS:
			with self.subTest(uygulama=ad):
				m = fabrika().make_master(kucuk, URUN_MASTER)
				self.assertEqual((m.width, m.height), (800, 600))

	def test_master_uzun_kenari_tavana_indirir(self):
		buyuk = sentetik_gorsel("JPEG", 6000, 4000)
		for ad, fabrika in IMAGE_IMPLS:
			with self.subTest(uygulama=ad):
				m = fabrika().make_master(buyuk, URUN_MASTER)
				self.assertLessEqual(max(m.width, m.height), URUN_MASTER.max_long_edge)
				self.assertLessEqual((m.width * m.height) / 1e6, URUN_MASTER.max_megapixels + 0.01)

	def test_master_sabit_noktali(self):
		"""İdempotensi: master'ın master'ı bayt düzeyinde aynı."""
		kaynak = sentetik_gorsel("JPEG", 4000, 3000)
		for ad, fabrika in IMAGE_IMPLS:
			with self.subTest(uygulama=ad):
				motor = fabrika()
				bir = motor.make_master(kaynak, URUN_MASTER)
				iki = motor.make_master(bir.content, URUN_MASTER)
				self.assertEqual(bir.content, iki.content)

	def test_master_dpi_yazar_pikseli_degistirmez(self):
		"""FR-029/FR-030 — DPI düşürmek çözünürlüğü DÜŞÜRMEZ."""
		kaynak = sentetik_gorsel("JPEG", 2000, 2000, dpi=300)
		for ad, fabrika in IMAGE_IMPLS:
			with self.subTest(uygulama=ad):
				m = fabrika().make_master(kaynak, URUN_MASTER)
				self.assertEqual((m.width, m.height), (2000, 2000))
				self.assertEqual(m.dpi, 72)
				self.assertTrue(any("piksel korundu" in n for n in m.notes))

	def test_master_cmyk_srgbye_cevirir(self):
		"""FR-145 — canlı ölçümde 38 CMYK dosya var."""
		kaynak = sentetik_gorsel("TIFF", 1200, 1200, mode="CMYK")
		for ad, fabrika in IMAGE_IMPLS:
			with self.subTest(uygulama=ad):
				m = fabrika().make_master(kaynak, URUN_MASTER)
				self.assertTrue(any("colorspace:CMYK" in n for n in m.notes))

	def test_master_alfayi_dusurmez(self):
		"""FR-146 — 597 alfalı dosya ölçüldü; JPEG'e düşürmek yasak."""
		kaynak = sentetik_gorsel("PNG", 1200, 1200, mode="RGBA", alpha=True)
		jpeg_spec = image_c.MasterSpec(max_long_edge=2400, format="jpeg")
		for ad, fabrika in IMAGE_IMPLS:
			with self.subTest(uygulama=ad):
				with self.assertRaises(errors_c.UnsupportedFormat) as ctx:
					fabrika().make_master(kaynak, jpeg_spec)
				self.assertIn("alpha_lost", ctx.exception.kod)
				webp = fabrika().make_master(kaynak, URUN_MASTER)
				self.assertTrue(webp.content)

	def test_master_animasyonu_reddeder(self):
		kaynak = sentetik_gorsel("WEBP", 1200, 1200, animated=True)
		for ad, fabrika in IMAGE_IMPLS:
			with self.subTest(uygulama=ad):
				with self.assertRaises(errors_c.UnsupportedFormat):
					fabrika().make_master(kaynak, URUN_MASTER)

	def test_master_upscale_speci_reddedilir(self):
		with self.assertRaises(ValueError):
			image_c.MasterSpec(max_long_edge=2400, format="webp", allow_upscale=True)

	def test_rendition_upscale_yapmaz_under_spec_isaretler(self):
		"""FR-033 — master küçükse dosya reddedilmez, eksik profil işaretlenir."""
		master = sentetik_gorsel("WEBP", 800, 800)
		spec = image_c.RenditionSpec(name="w1600", width=1600, format="webp", quality=80)
		for ad, fabrika in IMAGE_IMPLS:
			with self.subTest(uygulama=ad):
				r = fabrika().make_rendition(master, spec)
				self.assertEqual(r.width, 800)
				self.assertIn("under_spec", r.notes)

	def test_ladder_kismi_basari_uretmez(self):
		master = sentetik_gorsel("WEBP", 2000, 2000)
		specler = (
			image_c.RenditionSpec(name="w96", width=96, format="webp"),
			image_c.RenditionSpec(name="bozuk", width=192, format="XYZ"),
		)
		for ad, fabrika in IMAGE_IMPLS:
			with self.subTest(uygulama=ad):
				with self.assertRaises(errors_c.UnsupportedFormat):
					fabrika().make_ladder(master, specler)

	def test_rendition_idempotent(self):
		master = sentetik_gorsel("WEBP", 2000, 2000)
		spec = image_c.RenditionSpec(name="w768", width=768, format="webp", quality=80)
		for ad, fabrika in IMAGE_IMPLS:
			with self.subTest(uygulama=ad):
				motor = fabrika()
				self.assertEqual(
					motor.make_rendition(master, spec).content,
					motor.make_rendition(master, spec).content,
				)

	def test_kalite_olculemiyorsa_sayi_uydurmaz(self):
		"""FR-066 — ölçüm yoksa `measured=False`, skor anlamsız."""
		a = sentetik_gorsel("WEBP", 2000, 2000)
		b = sentetik_gorsel("WEBP", 1000, 1000)
		for ad, fabrika in IMAGE_IMPLS:
			with self.subTest(uygulama=ad):
				rapor = fabrika().quality_score(a, b)
				self.assertFalse(rapor.measured)
				self.assertTrue(rapor.passed)  # fail-open


# ═══════════════════════════════════════════════════════════════════════
# 4. VideoEngine sözleşmesi
# ═══════════════════════════════════════════════════════════════════════

KAPAK_RENDITION = video_c.VideoRenditionSpec(
	id="cover_720_webm",
	width=1280,
	height=720,
	container="webm",
	video_codec="libvpx-vp9",
	crf=32,
	maxrate_kbps=2500,
	max_bytes=12_582_912,
)


class VideoContractTest(unittest.TestCase):
	def test_probe_olculemedigini_soyler_hata_atmaz(self):
		"""NFR-043 — ffprobe okunamazsa güvenli tarafa düşülür."""
		for ad, fabrika in VIDEO_IMPLS:
			with self.subTest(uygulama=ad):
				p = fabrika().probe(video_c.VideoSource(content=b"bu video degil"))
				self.assertFalse(p.measured)

	def test_olculemeyen_video_transcode_edilir(self):
		for ad, fabrika in VIDEO_IMPLS:
			with self.subTest(uygulama=ad):
				self.assertTrue(fabrika().needs_transcode(video_c.VideoProbe(measured=False)))

	def test_kosullu_atlama_esikleri(self):
		"""`transcode.py` eşikleri: 1280 px / 2,5 Mbps."""
		motor = FakeVideoEngine()
		kucuk = motor.probe(
			video_c.VideoSource(content=sentetik_video(1280, 720, bitrate_bps=1_500_000))
		)
		buyuk = motor.probe(
			video_c.VideoSource(content=sentetik_video(1920, 1080, bitrate_bps=6_000_000))
		)
		self.assertFalse(motor.needs_transcode(kucuk))
		self.assertTrue(motor.needs_transcode(buyuk))

	def test_transcode_ses_silme_ve_dosya_kapisi(self):
		kaynak = video_c.VideoSource(content=sentetik_video(1920, 1080, duration_s=30.0))
		sessiz_spec = video_c.VideoRenditionSpec(
			id="ambient",
			width=1280,
			height=720,
			container="webm",
			video_codec="libvpx-vp9",
			audio=video_c.AUDIO_STRIPPED,
			maxrate_kbps=1600,
			max_bytes=12_582_912,
		)
		for ad, fabrika in VIDEO_IMPLS:
			with self.subTest(uygulama=ad):
				motor = fabrika()
				sesli = motor.transcode(kaynak, KAPAK_RENDITION)
				sessiz = motor.transcode(kaynak, sessiz_spec)
				self.assertTrue(sesli.has_audio)
				self.assertFalse(sessiz.has_audio)
				self.assertIn("audio_stripped", sessiz.notes)
				self.assertTrue(sessiz.fits(sessiz_spec))

	def test_transcode_target_path_verilince_bayt_dondurmez(self):
		kaynak = video_c.VideoSource(content=sentetik_video(1920, 1080))
		art = FakeVideoEngine().transcode(kaynak, KAPAK_RENDITION, target_path="/tmp/x.webm")
		self.assertIsNone(art.content)
		self.assertEqual(art.path, "/tmp/x.webm")

	def test_transcode_all_tumu_ya_hic(self):
		kaynak = video_c.VideoSource(content=sentetik_video(1920, 1080))
		bozuk = video_c.VideoRenditionSpec(
			id="bozuk", width=1280, height=720, container="webm", video_codec="x"
		)
		motor = FakeVideoEngine()
		sonuc = motor.transcode_all(kaynak, (KAPAK_RENDITION, bozuk))
		self.assertEqual(set(sonuc), {"cover_720_webm", "bozuk"})
		bos = video_c.VideoSource(content=sentetik_video(1920, 1080, duration_s=0.0))
		with self.assertRaises(errors_c.TranscodeFailed):
			motor.transcode_all(bos, (KAPAK_RENDITION,))

	def test_poster_gorsel_dondurur(self):
		"""Poster bir GÖRSELDİR — `srcset` kurallarına tabi olabilsin."""
		kaynak = video_c.VideoSource(content=sentetik_video(1920, 1080, duration_s=30.0))
		poster = FakeVideoEngine().make_poster(kaynak, video_c.PosterSpec(width=1280))
		self.assertIsInstance(poster, image_c.EncodedImage)
		self.assertEqual(poster.width, 1280)

	def test_onizleme_klibi_boyut_kapisini_dayatmaz(self):
		"""Kapı kararı politikanın; motor yalnız ölçer (FR-043)."""
		kaynak = video_c.VideoSource(content=sentetik_video(1920, 1080, duration_s=30.0))
		spec = video_c.PreviewClipSpec(max_bytes=1)
		klip = FakeVideoEngine().make_preview_clip(kaynak, spec)
		self.assertEqual(klip.duration_s, 6.0)
		self.assertFalse(klip.has_audio)
		self.assertFalse(klip.fits(video_c.VideoRenditionSpec(
			id="x", width=854, height=480, container="webm", video_codec="v", max_bytes=1
		)))

	def test_video_source_tam_olarak_bir_kaynak_ister(self):
		with self.assertRaises(ValueError):
			video_c.VideoSource()
		with self.assertRaises(ValueError):
			video_c.VideoSource(content=b"x", path="/a")


# ═══════════════════════════════════════════════════════════════════════
# 5. PolicyEngine sözleşmesi — GERÇEK politika dosyalarıyla
# ═══════════════════════════════════════════════════════════════════════


class PolicyContractTest(unittest.TestCase):
	"""Sözleşme, GERÇEK politika dosyaları üzerinde İKİ uygulamayla koşar.

	`InMemoryPolicyEngine` bellek-içi referans, `PolicyEngine` ÜRETİM motoru
	(`api/upload.py`, `api/admin.py`, `simulator/srcset.py` bunu çağırır).
	T-033'e kadar bu sınıf yalnız birinciyi denetliyordu; Protokolün üretimde
	hiçbir uygulayıcısı yoktu ve testler sahteyi doğruluyordu.
	"""

	def _motorlar(self) -> list:
		return [(ad, fabrika()) for ad, fabrika in POLICY_IMPLS]

	def test_dokuz_slot_yuklendi(self):
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				self.assertEqual(len(motor.slots()), 9)
				self.assertIn("product.image", motor.slots())

	def test_bilinmeyen_slot_policy_not_found(self):
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				with self.assertRaises(errors_c.PolicyNotFound):
					motor.load("olmayan.slot")

	def test_reload_idempotent(self):
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				self.assertEqual(motor.reload(), motor.reload())
				self.assertEqual(motor.reload(), 9)

	def test_reload_bozuk_dosyada_defteri_bozmaz(self):
		"""Sözleşme: ya hep ya hiç. Yarım defter, hangi slotun eski hangisinin
		yeni olduğu bilinmeyen sistemdir."""
		for ad, _fabrika in POLICY_IMPLS:
			with self.subTest(uygulama=ad):
				with tempfile.TemporaryDirectory() as gecici:
					hedef = Path(gecici)
					for kaynak in POLICY_ROOT.glob("*.json"):
						shutil.copy(kaynak, hedef / kaynak.name)
					motor = _motor_koku(ad, hedef)
					self.assertEqual(motor.reload(), 9)
					# Ad BİLEREK alfabetik olarak İLK: `sorted(glob)` bozuk dosyayı
					# ilk okur ve istisna, defter temizlendikten SONRA ama hiçbir
					# politika okunmadan atılır. "zzz-" adıyla bu test boş çıkardı —
					# dokuz dosya zaten yüklenmiş olurdu (vacuity ölçüldü).
					(hedef / "aaa-bozuk.json").write_text("{ bu json değil", encoding="utf-8")
					with self.assertRaises(Exception):
						motor.reload()
					# Defter DEĞİŞMEDİ: dokuz politika hâlâ okunabilir.
					self.assertEqual(len(motor.slots()), 9)
					self.assertTrue(motor.load("product.image").accept)

	def test_source_root_raporlanir(self):
		"""FR-147 — hangi politika seti yürürlükte, sessiz kalınmaz."""
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				self.assertTrue(motor.source_root().endswith("slots"))

	def test_efektif_tavan_kesisimdir(self):
		"""FR-007/FR-076 — slot global tavanı GEVŞETEMEZ."""
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				limit = motor.effective_limits("product.image", plan_max_bytes=5 * 1024 * 1024)
				self.assertEqual(limit.max_bytes, 5 * 1024 * 1024)
				limit2 = motor.effective_limits("product.image")
				self.assertEqual(limit2.max_bytes, 26214400)

	def test_accept_uzanti_ve_boyut(self):
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				iyi = motor.check_accept("product.image", file_name="a.jpg", size_bytes=1024)
				self.assertTrue(iyi.allowed)
				kotu = motor.check_accept("product.image", file_name="a.gif", size_bytes=1024)
				self.assertFalse(kotu.allowed)
				self.assertEqual(kotu.first_code, "product_image_ext_not_allowed")
				buyuk = motor.check_accept(
					"product.image", file_name="a.jpg", size_bytes=99_000_000
				)
				self.assertFalse(buyuk.allowed)
				self.assertEqual(buyuk.first_code, "product_image_too_large")

	def test_uzanti_icerik_uyusmazligi(self):
		"""FR-009 — iki okuyucu aynı kanonik politika kararını verir."""
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				karar = motor.check_accept(
					"product.image", file_name="a.png", size_bytes=1024, sniffed_type="jpeg"
				)
				self.assertEqual(karar.action, policy_c.ACTION_REJECT)
				self.assertFalse(karar.allowed)
				kodlar = [v.code for v in karar.violations + karar.warnings]
				self.assertEqual(kodlar, ["product_image_ext_content_mismatch"])

	def test_sapma_tablosu_kapali_kume(self):
		"""Karar motorları arasında kabul edilmiş istisna kalmadı."""
		self.assertEqual(POLICY_SAPMALARI, {})

	def test_geometri_esitlik_gecerlidir(self):
		"""FR-015 — `>=`, tam sınırdaki dosya kabul edilir."""
		p = image_c.ImageProbe(fmt="JPEG", width=1000, height=1000)
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				karar = motor.check_geometry("product.image", p)
				self.assertTrue(karar.allowed, karar.violations)

	def test_geometri_bagil_oran_toleransi(self):
		"""FR-016 — 4:5 tam oran geçer, 1000x1400 (0,714) reddedilir."""
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				self.assertTrue(
					motor.check_geometry(
						"product.image", image_c.ImageProbe(fmt="JPEG", width=1000, height=1250)
					).allowed
				)
				kotu = motor.check_geometry(
					"product.image", image_c.ImageProbe(fmt="JPEG", width=1000, height=1400)
				)
				self.assertFalse(kotu.allowed)
				self.assertEqual(kotu.first_code, "product_image_ratio_not_allowed")

	def test_geometri_kisa_kenar_ve_adet(self):
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				kucuk = motor.check_geometry(
					"product.image", image_c.ImageProbe(fmt="JPEG", width=640, height=640)
				)
				self.assertFalse(kucuk.allowed)
				self.assertEqual(kucuk.first_code, "product_image_short_edge_too_small")
				cok = motor.check_geometry(
					"product.image",
					image_c.ImageProbe(fmt="JPEG", width=1000, height=1000),
					count=13,
				)
				self.assertFalse(cok.allowed)
				self.assertEqual(cok.first_code, "product_image_count_exceeded")

	def test_okunamayan_gorsel_reddedilir(self):
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				karar = motor.check_geometry(
					"product.image", image_c.ImageProbe(fmt="", width=0, height=0, readable=False)
				)
				self.assertFalse(karar.allowed)
				self.assertEqual(karar.first_code, "product_image_decode_failed")

	def test_belge_slotunda_geometri_uyaridir(self):
		"""FR-027 — `document.attachment` geometri ihlalinde reddetmez."""
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				karar = motor.check_geometry(
					"document.attachment", image_c.ImageProbe(fmt="PNG", width=200, height=200)
				)
				self.assertTrue(karar.allowed)
				self.assertEqual(karar.action, policy_c.ACTION_WARN)

	def test_video_olculemezse_manuel_incelemeye_duser(self):
		"""NFR-043 + FR-134 — ölçülemeyen video ne reddedilir ne sessizce geçer."""
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				karar = motor.check_video("company.cover_video", video_c.VideoProbe(measured=False))
				self.assertEqual(karar.action, policy_c.ACTION_MANUAL_REVIEW)
				self.assertTrue(karar.allowed)

	def test_video_sure_kapisi(self):
		kisa = video_c.VideoProbe(width=1920, height=1080, duration_s=2.0, measured=True)
		iyi = video_c.VideoProbe(
			width=1920, height=1080, duration_s=30.0, bitrate_bps=1_500_000, measured=True
		)
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				red = motor.check_video("company.cover_video", kisa)
				self.assertFalse(red.allowed)
				self.assertEqual(red.first_code, "cover_video_duration_out_of_range")
				self.assertTrue(motor.check_video("company.cover_video", iyi).allowed)

	def test_video_olmayan_slotta_video_kapisi_hata(self):
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				with self.assertRaises(errors_c.PolicyError):
					motor.check_video("product.image", video_c.VideoProbe(measured=True))

	def test_master_spec_upscale_yasagini_tasir(self):
		for ad, motor in self._motorlar():
			for slot in motor.slots():
				with self.subTest(uygulama=ad, slot=slot):
					spec = motor.master_spec(slot)
					self.assertFalse(spec.allow_upscale)
					self.assertGreater(spec.max_long_edge, 0)

	def test_rendition_specleri_artan_sirada(self):
		for ad, motor in self._motorlar():
			for slot in motor.slots():
				specler = motor.rendition_specs(slot)
				if not specler:
					continue
				with self.subTest(uygulama=ad, slot=slot):
					genislikler = [s.width for s in specler]
					self.assertEqual(genislikler, sorted(genislikler))

	def test_iki_uygulama_ayni_uretim_parametrelerini_verir(self):
		"""Sözleşmenin asıl sınavı: aynı JSON, iki bağımsız okuyucu, aynı çıktı.

		Bir uygulamanın diğerine göre kayması (ör. `dpi_out` varsayılanı ya da
		profil sıralaması) burada görünür; tek uygulamalı bir sözleşme testi
		bunu ölçemezdi.
		"""
		sahte = _fake_policy_engine()
		uretim = _uretim_policy_engine()
		self.assertEqual(sahte.slots(), uretim.slots())
		for slot in sahte.slots():
			with self.subTest(slot=slot):
				self.assertEqual(sahte.master_spec(slot), uretim.master_spec(slot))
				self.assertEqual(sahte.rendition_specs(slot), uretim.rendition_specs(slot))
				self.assertEqual(
					sahte.video_rendition_specs(slot), uretim.video_rendition_specs(slot)
				)
				self.assertEqual(
					sahte.effective_limits(slot), uretim.effective_limits(slot)
				)
				self.assertEqual(
					sahte.quality_threshold(slot, "photo"),
					uretim.quality_threshold(slot, "photo"),
				)

	def test_video_olmayan_slotta_video_rendition_bos(self):
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				self.assertEqual(motor.video_rendition_specs("product.image"), ())
				self.assertTrue(motor.video_rendition_specs("company.cover_video"))

	def test_dogrulama_d1_d5(self):
		"""FR-003/FR-148 — tek çıkış kodu; 9 standardın değişmezleri geçerli."""
		for ad, motor in self._motorlar():
			with self.subTest(uygulama=ad):
				karar = motor.validate()
				self.assertEqual(
					karar.violations, (), f"Değişmez ihlali: {[v.code for v in karar.violations]}"
				)

	def test_dogrulama_bozuk_politikayi_yakalar(self):
		"""Vacuity kapısı: `validate()` gerçekten bakıyor mu.

		D2 (`min_long_edge <= max_long_edge`) bilerek ihlal edilir; karar
		RET dönmüyorsa doğrulama boş bir kabuktur.
		"""
		for ad, _fabrika in POLICY_IMPLS:
			with self.subTest(uygulama=ad):
				with tempfile.TemporaryDirectory() as gecici:
					hedef = Path(gecici)
					for kaynak in POLICY_ROOT.glob("*.json"):
						shutil.copy(kaynak, hedef / kaynak.name)
					yol = hedef / "product-image.json"
					veri = json.loads(yol.read_text(encoding="utf-8"))
					veri["master"]["min_long_edge"] = veri["master"]["max_long_edge"] + 1
					yol.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
					motor = _motor_koku(ad, hedef)
					karar = motor.validate()
					self.assertFalse(karar.allowed)
					self.assertIn(
						"product_image_invariant_d2", [v.code for v in karar.violations]
					)

	def test_karar_birlesimi_en_yuksek_aksiyonu_alir(self):
		"""FR-049 — en yüksek aksiyon uygulanır, uyarılar birikir."""
		uyari = policy_c.Decision(
			slot_key="x",
			action=policy_c.ACTION_WARN,
			warnings=(
				policy_c.Violation(
					code="x_a", layer=policy_c.LAYER_ACCEPT, sebep="a", action=policy_c.ACTION_WARN
				),
			),
		)
		ret = policy_c.Decision(
			slot_key="x",
			action=policy_c.ACTION_REJECT,
			violations=(
				policy_c.Violation(code="x_b", layer=policy_c.LAYER_REQUIRE, sebep="b"),
			),
		)
		birlesik = uyari.merge(ret)
		self.assertEqual(birlesik.action, policy_c.ACTION_REJECT)
		self.assertFalse(birlesik.allowed)
		self.assertEqual(len(birlesik.warnings), 1)
		self.assertEqual(len(birlesik.violations), 1)
		with self.assertRaises(ValueError):
			uyari.merge(policy_c.Decision(slot_key="y"))

	def test_hata_yaniti_kod_ve_retryable_tasir(self):
		"""FR-060 — istemci metne değil `(kod, retryable)` çiftine bakar."""
		hata = errors_c.PolicyViolation("çok küçük", kod="product_image_short_edge_too_small")
		yanit = hata.to_response()
		self.assertEqual(yanit["error_code"], "product_image_short_edge_too_small")
		self.assertFalse(yanit["retryable"])
		self.assertTrue(errors_c.TranscodeFailed("ffmpeg düştü").retryable)


def _motor_koku(uygulama_adi: str, kok: Path):
	"""Verilen kökten okuyan motoru kur — iki uygulamanın kurulumu farklı."""
	if uygulama_adi == "PolicyEngine":
		return UretimPolicyEngine(UretimPolicyRegistry(kok))
	return InMemoryPolicyEngine.from_directory(str(kok))


# ═══════════════════════════════════════════════════════════════════════
# 6. DeliveryManifest sözleşmesi
# ═══════════════════════════════════════════════════════════════════════


class DeliveryContractTest(unittest.TestCase):
	def setUp(self) -> None:
		self.motor = _policy_engine()
		self.teslim = SimpleDeliveryManifest(
			self.motor,
			sizes_map={"product.image": {"default": "(min-width:1024px) 500px, 100vw"}},
		)
		self.base = storage_c.ObjectRef(key=storage_c.key_for(b"urun-gorseli", ".webp"))

	def test_turev_anahtari_shardi_korur(self):
		"""FR-040 — türev orijinalin yanında, aynı shard dizininde."""
		turev = delivery_c.derivative_key(self.base.key, "w768", "webp")
		self.assertEqual(turev.shard, self.base.key.shard)
		self.assertTrue(turev.name.endswith("__w768.webp"))

	def test_manifest_srcset_uretir(self):
		"""Ölçülen boşluk: srcset 31 görselin 0'ında. Manifest bunu doldurur."""
		m = self.teslim.build_image("product.image", self.base, intrinsic=(2400, 2400))
		self.assertTrue(m.sources)
		self.assertIn("w", m.srcset)
		self.assertIn("(min-width:1024px)", m.sizes)
		self.assertAlmostEqual(m.aspect_ratio, 1.0)
		sozluk = m.to_dict()
		self.assertEqual(sozluk["src"], m.fallback_url)
		self.assertTrue(sozluk["sources"])

	def test_uretilmemis_profil_srcsete_girmez(self):
		m = self.teslim.build_image("product.image", self.base, available_profiles=["w96.webp"])
		girdiler = [v for v in m.variants if v.available]
		self.assertEqual(len(girdiler), 1)
		for kaynak in m.sources:
			self.assertNotIn("w1920", kaynak.srcset)

	def test_hicbir_profil_yoksa_hata(self):
		with self.assertRaises(errors_c.NoProfileAvailable):
			self.teslim.build_image("product.image", self.base, available_profiles=[])

	def test_fallback_avif_olamaz(self):
		m = self.teslim.build_image("product.image", self.base)
		self.assertFalse(m.fallback_url.endswith(".avif"))

	def test_lcp_adayi_eager_yuklenir(self):
		m = self.teslim.build_image("product.image", self.base, is_lcp_candidate=True)
		self.assertEqual(m.loading, delivery_c.LOADING_EAGER)
		self.assertEqual(m.fetchpriority, "high")
		v = self.teslim.build_image("product.image", self.base)
		self.assertEqual(v.loading, delivery_c.LOADING_LAZY)
		self.assertEqual(v.fetchpriority, "")

	def test_bilinmeyen_baglamda_sizes_bos(self):
		"""Yanlış `sizes` yazmaktansa hiç yazmamak."""
		self.assertEqual(self.teslim.sizes_attribute("product.image", context="yok"), "")

	def test_pick_hedefi_karsilayan_en_kucugu_secer(self):
		secim = self.teslim.pick("product.image", 100.0, dpr=2.0)
		self.assertGreaterEqual(secim.width, 200)
		specler = self.motor.rendition_specs("product.image")
		daha_kucuk = [s for s in specler if s.width < secim.width and s.width >= 200]
		self.assertEqual(daha_kucuk, [])

	def test_overshoot_olculur(self):
		"""FR-123 — aşırı-servis oranı sunucuda hesaplanabilmeli."""
		oran = self.teslim.overshoot("product.image", 100.0, dpr=1.0)
		self.assertGreater(oran, 0.0)
		self.assertEqual(self.teslim.overshoot("product.image", 0.0), 0.0)

	def test_video_manifesti_poster_zorunlu(self):
		"""FR-042 — poster verilmezse politika profilinden türetilir."""
		base = storage_c.ObjectRef(key=storage_c.key_for(b"kapak-videosu", ".webm"))
		m = self.teslim.build_video("company.cover_video", base)
		self.assertTrue(m.poster_url)
		self.assertIn(base.key.shard, m.poster_url)


# ═══════════════════════════════════════════════════════════════════════
# 7. Uçtan uca — beş sözleşme birlikte
# ═══════════════════════════════════════════════════════════════════════


class PipelineIntegrationTest(unittest.TestCase):
	"""Politika → master → merdiven → depo → manifest.

	Sözleşmelerin ayrı ayrı değil BİRLİKTE tuttuğunu gösterir; SAD §4.1'deki
	yükleme sıra diyagramının yürütülebilir karşılığıdır. İki politika
	uygulamasıyla da koşar: uçtan uca akış ÜRETİM motoruyla da yürüyor mu.
	"""

	def test_urun_gorseli_uctan_uca(self):
		for ad, fabrika in POLICY_IMPLS:
			with self.subTest(uygulama=ad):
				politika = fabrika()
				gorsel = FakeImageEngine()
				depo = InMemoryStorage()
				teslim = SimpleDeliveryManifest(politika)

				ham = sentetik_gorsel("JPEG", 4000, 4000, dpi=300)

				# L1 — dosya açılmadan
				self.assertTrue(
					politika.check_accept(
						"product.image", file_name="urun.jpg", size_bytes=len(ham)
					).allowed
				)

				# L2 — açıldıktan sonra
				probe = gorsel.probe(ham, max_megapixels=80)
				self.assertTrue(politika.check_geometry("product.image", probe).allowed)

				# L3 — master
				master = gorsel.make_master(ham, politika.master_spec("product.image"))
				self.assertLessEqual(max(master.width, master.height), 2400)
				yazim = depo.put(master.content, ".webp")
				self.assertTrue(yazim.created)
				self.assertFalse(depo.put(master.content, ".webp").created)  # idempotent

				# Türev merdiveni
				specler = politika.rendition_specs("product.image")
				merdiven = gorsel.make_ladder(master.content, specler)
				self.assertEqual(len(merdiven), len(specler))
				for spec in specler:
					depo.put(merdiven[spec.name].content, f".{spec.format}")

				# Teslim
				manifest = teslim.build_image(
					"product.image", yazim.ref, intrinsic=(master.width, master.height), alt="ürün"
				)
				self.assertTrue(manifest.srcset)
				self.assertEqual(manifest.slot_key, "product.image")

	def test_kapak_videosu_uctan_uca(self):
		for ad, fabrika in POLICY_IMPLS:
			with self.subTest(uygulama=ad):
				politika = fabrika()
				vid = FakeVideoEngine()
				depo = InMemoryStorage()

				ham = sentetik_video(1920, 1080, duration_s=30.0, bitrate_bps=6_000_000)
				kaynak = video_c.VideoSource(content=ham)
				probe = vid.probe(kaynak)
				self.assertTrue(vid.needs_transcode(probe))
				self.assertTrue(politika.check_video("company.cover_video", probe).allowed)

				specler = politika.video_rendition_specs("company.cover_video")
				self.assertTrue(specler)
				ciktilar = vid.transcode_all(kaynak, specler)
				for spec in specler:
					art = ciktilar[spec.id]
					depo.put(art.content, f".{spec.container}")
					self.assertTrue(art.fits(spec), f"{spec.id} dosya kapısını aştı")
				self.assertEqual(
					len(depo), len({s.id for s in specler}) if len(specler) > 1 else 1
				)


if __name__ == "__main__":  # pragma: no cover
	unittest.main(verbosity=2)

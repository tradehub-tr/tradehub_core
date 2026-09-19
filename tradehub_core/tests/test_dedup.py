"""T-042 — `tradehub_core/media/pipeline/core/dedup.py` testleri.

Kanıtlanan değişmezler:

  INV-06  idempotency — aynı dosya iki kez yüklenince tek varlık oluşur;
                        eşzamanlı iki `finalize` yarışında da tek varlık
  INV-09  değişmez URL — içerik değişmeden rendition adresi değişmez,
                        girdilerden biri değişince zorunlu değişir

Ek olarak: akışlı hash'in bellekte hesaplananla aynı olduğu, mevcut üretim
motorunun adlandırma sözleşmesiyle uyum (`naming.py` varsa gerçekten
karşılaştırılır, yoksa test ATLANIR — sahte "geçti" verilmez).

Çalıştırma:

    python3 -m unittest discover -s /Users/ahmet/Desktop/istoc/tradehub_core/tests -v
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.core import dedup  # noqa: E402
from tradehub_core.media.pipeline.core.dedup import (  # noqa: E402
	CACHE_CONTROL_IMMUTABLE,
	DedupError,
	canonical_json,
	content_name,
	content_url,
	idempotent_create,
	parse_rendition_path,
	rendition_path,
	resolve_upload,
	sha256_bytes,
	shard_of,
	stream_sha256,
	version_hash,
)

ORNEK = b"istoc medya motoru faz 4 ornek icerik" * 1000
ORNEK_SHA = hashlib.sha256(ORNEK).hexdigest()


class AkisliHashTesti(unittest.TestCase):
	def test_bytes_ile_dogru_hash(self):
		self.assertEqual(stream_sha256(ORNEK).sha256, ORNEK_SHA)
		self.assertEqual(stream_sha256(ORNEK).bytes, len(ORNEK))

	def test_dosya_yolu_ile_ayni_sonuc(self):
		with tempfile.NamedTemporaryFile(delete=False) as fh:
			fh.write(ORNEK)
			yol = fh.name
		try:
			sonuc = stream_sha256(yol)
			self.assertEqual(sonuc.sha256, ORNEK_SHA)
			self.assertEqual(sonuc.bytes, os.path.getsize(yol))
		finally:
			os.unlink(yol)

	def test_dosya_nesnesi_ile_ayni_sonuc(self):
		self.assertEqual(stream_sha256(io.BytesIO(ORNEK)).sha256, ORNEK_SHA)

	def test_uretecle_ayni_sonuc(self):
		"""Parçalı yükleme yolunda içerik üreteç olarak gelir."""

		def parcalar():
			for i in range(0, len(ORNEK), 997):
				yield ORNEK[i : i + 997]

		self.assertEqual(stream_sha256(parcalar()).sha256, ORNEK_SHA)

	def test_parca_boyutu_sonucu_degistirmez(self):
		for boyut in (1, 7, 4096, 1024 * 1024, len(ORNEK) * 2):
			with self.subTest(boyut=boyut):
				self.assertEqual(stream_sha256(ORNEK, chunk_size=boyut).sha256, ORNEK_SHA)

	def test_bos_icerik(self):
		self.assertEqual(stream_sha256(b"").sha256, hashlib.sha256(b"").hexdigest())
		self.assertEqual(stream_sha256(b"").bytes, 0)

	def test_metin_akisi_reddedilir(self):
		with self.assertRaises(DedupError):
			stream_sha256(iter(["metin"]))

	def test_gecersiz_parca_boyutu(self):
		with self.assertRaises(DedupError):
			stream_sha256(ORNEK, chunk_size=0)


class AdlandirmaSozlesmesiTesti(unittest.TestCase):
	"""Mevcut üretim motorunun (`naming.py`) sözleşmesi korunuyor mu."""

	def test_ad_ve_shard_bicimi(self):
		ad = content_name(ORNEK_SHA, ".jpg")
		self.assertEqual(ad, ORNEK_SHA[:32] + ".jpg")
		self.assertEqual(shard_of(ad), ORNEK_SHA[:2])

	def test_uzanti_noktasiz_da_kabul(self):
		self.assertEqual(content_name(ORNEK_SHA, "png"), ORNEK_SHA[:32] + ".png")

	def test_uzanti_kucuk_harfe_iner(self):
		self.assertEqual(content_name(ORNEK_SHA, ".JPEG"), ORNEK_SHA[:32] + ".jpeg")

	def test_url_public_ve_private(self):
		self.assertEqual(
			content_url(ORNEK_SHA, ".jpg"),
			f"/files/{ORNEK_SHA[:2]}/{ORNEK_SHA[:32]}.jpg",
		)
		self.assertEqual(
			content_url(ORNEK_SHA, ".jpg", is_private=True),
			f"/private/files/{ORNEK_SHA[:2]}/{ORNEK_SHA[:32]}.jpg",
		)

	def test_gecersiz_hash_reddedilir(self):
		for kotu in ("", "kisa", "Z" * 64, ORNEK_SHA[:63]):
			with self.subTest(kotu=kotu):
				with self.assertRaises(DedupError):
					content_name(kotu, ".jpg")

	def test_uretim_motoruyla_birebir(self):
		"""`naming.py` varsa GERÇEKTEN karşılaştır; yoksa testi atla.

		Atlamak, sahte bir 'geçti' vermekten iyidir — bu testin tek işi iki
		uygulamanın ayrışmadığını KANITLAMAK.
		"""
		sonuc = dedup.verify_naming_contract(ORNEK)
		if not sonuc.get("checked"):
			self.skipTest(f"frappe/naming.py yok: {sonuc.get('reason')}")
		self.assertEqual(sonuc["name"], ORNEK_SHA[:32] + ".jpg")
		self.assertEqual(sonuc["shard"], ORNEK_SHA[:2])


class KanonikJsonTesti(unittest.TestCase):
	def test_anahtar_sirasi_onemsiz(self):
		self.assertEqual(
			canonical_json({"b": 1, "a": 2}),
			canonical_json({"a": 2, "b": 1}),
		)

	def test_ic_ice_sozlukte_de_sirali(self):
		self.assertEqual(
			canonical_json({"x": {"z": 1, "y": 2}}),
			canonical_json({"x": {"y": 2, "z": 1}}),
		)

	def test_turkce_karakter_kacirilmaz(self):
		"""`\\u0131` kaçışı aynı politikayı iki farklı metin yapardı."""
		out = canonical_json({"ad": "Adsız tasarım"})
		self.assertIn("Adsız tasarım", out)
		self.assertNotIn("\\u", out)

	def test_bosluk_yok(self):
		self.assertEqual(canonical_json({"a": [1, 2]}), '{"a":[1,2]}')

	def test_nan_reddedilir(self):
		with self.assertRaises(ValueError):
			canonical_json({"x": float("nan")})

	def test_set_sirali_hale_gelir(self):
		self.assertEqual(canonical_json({"s": {3, 1, 2}}), canonical_json({"s": {2, 3, 1}}))

	def test_bilinmeyen_tip_hata(self):
		class Tuhaf:
			pass

		with self.assertRaises(DedupError):
			canonical_json({"x": Tuhaf()})


class VersionHashTesti(unittest.TestCase):
	"""Dört girdiden biri değişince hash değişir, hiçbiri değişmeden aynı kalır."""

	POLITIKA = {"slot_key": "product.image", "master": {"max_long_edge": 2400}}
	NIYET = {"focal_x": 0.5, "focal_y": 0.4, "method": "manual"}
	MOTOR = "pillow-11.3.0"

	def _h(self, **degisiklik):
		args = {
			"source_hash": ORNEK_SHA,
			"policy_snapshot": self.POLITIKA,
			"crop_intent": self.NIYET,
			"engine_version": self.MOTOR,
		}
		args.update(degisiklik)
		return version_hash(**args)

	def test_ayni_girdi_ayni_hash(self):
		self.assertEqual(self._h(), self._h())

	def test_farkli_varliklar_ayni_surumu_paylasmaz(self):
		self.assertNotEqual(self._h(asset_key="store-a-photo"), self._h(asset_key="store-b-photo"))
		self.assertEqual(self._h(asset_key="store-a-photo"), self._h(asset_key="store-a-photo"))
		self.assertEqual(self._h(), self._h(asset_key=""))

	def test_sozluk_sirasi_hashi_degistirmez(self):
		ters = {"master": {"max_long_edge": 2400}, "slot_key": "product.image"}
		self.assertEqual(self._h(), self._h(policy_snapshot=ters))

	def test_kaynak_hash_degisince_degisir(self):
		baska = hashlib.sha256(b"baska").hexdigest()
		self.assertNotEqual(self._h(), self._h(source_hash=baska))

	def test_politika_degisince_degisir(self):
		yeni = {"slot_key": "product.image", "master": {"max_long_edge": 2000}}
		self.assertNotEqual(self._h(), self._h(policy_snapshot=yeni))

	def test_crop_degisince_degisir(self):
		yeni = dict(self.NIYET, focal_x=0.51)
		self.assertNotEqual(self._h(), self._h(crop_intent=yeni))

	def test_motor_surumu_degisince_degisir(self):
		self.assertNotEqual(self._h(), self._h(engine_version="pyvips-8.15.0"))

	def test_dort_girdi_de_etkili(self):
		"""Dördünün de gerçekten etkili olduğunu tek testte topla."""
		taban = self._h()
		farklilar = {
			taban,
			self._h(source_hash=hashlib.sha256(b"x").hexdigest()),
			self._h(policy_snapshot={"slot_key": "seller.logo"}),
			self._h(crop_intent={"focal_x": 0.1, "focal_y": 0.1}),
			self._h(engine_version="pillow-12.0.0"),
		}
		self.assertEqual(len(farklilar), 5, "girdilerden biri hash'i etkilemiyor")

	def test_niyet_yok_ile_bos_niyet_farkli(self):
		"""'Kırpma niyeti yok' ile 'niyet var, alanları boş' aynı şey değil."""
		self.assertNotEqual(self._h(crop_intent=None), self._h(crop_intent={}))

	def test_alakasiz_alan_hashi_degistirmez(self):
		"""Önizleme kaydı pikseli değiştirmez → türevleri yeniden ürettirmemeli."""
		zengin = dict(
			self.NIYET,
			previewed_placements=[{"profile": "product-main"}],
			algorithm_version="v9",
			approved_by_user=1,
		)
		self.assertEqual(self._h(), self._h(crop_intent=zengin))

	def test_override_sirasi_hashi_degistirmez(self):
		a = dict(
			self.NIYET,
			overrides=[
				{"profile": "a", "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5},
				{"profile": "b", "x": 0.2, "y": 0.2, "w": 0.5, "h": 0.5},
			],
		)
		b = dict(self.NIYET, overrides=list(reversed(a["overrides"])))
		self.assertEqual(self._h(crop_intent=a), self._h(crop_intent=b))

	def test_override_degeri_hashi_degistirir(self):
		a = dict(self.NIYET, overrides=[{"profile": "a", "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}])
		b = dict(self.NIYET, overrides=[{"profile": "a", "x": 0.11, "y": 0.1, "w": 0.5, "h": 0.5}])
		self.assertNotEqual(self._h(crop_intent=a), self._h(crop_intent=b))

	def test_ayrac_belirsizligi_yok(self):
		"""Düz birleştirme olsaydı bu iki girdi aynı diziyi üretebilirdi."""
		a = version_hash(ORNEK_SHA, "ab", None, "c")
		b = version_hash(ORNEK_SHA, "a", None, "bc")
		self.assertNotEqual(a, b)

	def test_64_hane_onaltilik(self):
		h = self._h()
		self.assertEqual(len(h), 64)
		int(h, 16)


class RenditionAdresiTesti(unittest.TestCase):
	"""INV-09 — içerik değişmeden URL değişmez."""

	VH = hashlib.sha256(b"v1").hexdigest()

	def test_bicim(self):
		self.assertEqual(
			rendition_path("abc123", self.VH, "product-main", 800, "webp"),
			f"/files/media/abc123/{self.VH}/product-main-800.webp",
		)

	def test_ayni_girdi_ayni_url(self):
		a = rendition_path("abc123", self.VH, "product-main", 800, "webp")
		b = rendition_path("abc123", self.VH, "product-main", 800, ".WEBP")
		self.assertEqual(a, b)

	def test_version_degisince_url_degisir(self):
		v2 = hashlib.sha256(b"v2").hexdigest()
		self.assertNotEqual(
			rendition_path("abc123", self.VH, "product-main", 800, "webp"),
			rendition_path("abc123", v2, "product-main", 800, "webp"),
		)

	def test_ters_cevrim(self):
		url = rendition_path("abc123", self.VH, "product-main", 1600, "avif")
		d = parse_rendition_path(url)
		self.assertEqual(d["asset"], "abc123")
		self.assertEqual(d["version_hash"], self.VH)
		self.assertEqual(d["profile"], "product-main")
		self.assertEqual(d["width"], 1600)
		self.assertEqual(d["ext"], "avif")

	def test_ters_cevrim_sorgu_dizesini_yok_sayar(self):
		url = rendition_path("abc123", self.VH, "p", 100, "webp") + "?v=2"
		self.assertIsNotNone(parse_rendition_path(url))

	def test_alakasiz_url_none(self):
		self.assertIsNone(parse_rendition_path("/files/ab/abcdef.jpg"))
		self.assertIsNone(parse_rendition_path(""))

	def test_yol_gecisi_reddedilir(self):
		for kotu in ("../etc", "a/b", "", ".gizli", "a b"):
			with self.subTest(kotu=kotu):
				with self.assertRaises(DedupError):
					rendition_path(kotu, self.VH, "p", 100, "webp")

	def test_genislik_pozitif_tamsayi(self):
		for kotu in (0, -1, 1.5, "800", True):
			with self.subTest(kotu=kotu):
				with self.assertRaises(DedupError):
					rendition_path("a", self.VH, "p", kotu, "webp")

	def test_cache_control_sabiti(self):
		self.assertEqual(CACHE_CONTROL_IMMUTABLE, "public, max-age=31536000, immutable")


class IdempotencyTesti(unittest.TestCase):
	"""INV-06 — aynı dosya iki kez yüklenirse tek varlık."""

	def test_ikinci_yukleme_yeni_dosya_yazmaz(self):
		depo = {ORNEK_SHA: "MA-0001"}
		sonuc = resolve_upload(ORNEK_SHA, depo.get)
		self.assertTrue(sonuc.is_duplicate)
		self.assertEqual(sonuc.asset, "MA-0001")
		self.assertFalse(sonuc.should_store)
		self.assertIn("zaten kütüphanenizde", sonuc.message)

	def test_ilk_yukleme_yazilir(self):
		sonuc = resolve_upload(ORNEK_SHA, {}.get)
		self.assertFalse(sonuc.is_duplicate)
		self.assertTrue(sonuc.should_store)
		self.assertIsNone(sonuc.asset)

	def test_esrarengiz_hash_reddedilir(self):
		with self.assertRaises(DedupError):
			resolve_upload("kisa", {}.get)


class YarisKosuluTesti(unittest.TestCase):
	"""Eşzamanlı aynı-dosya yüklemesi: tek varlık oluşur, ikincisi onu döner."""

	class SahteDepo:
		"""UNIQUE kısıtlı, kilitli bellek içi depo."""

		class Cakisma(Exception):
			pass

		def __init__(self):
			self.rows = {}
			self.lock = threading.Lock()
			self.create_calls = 0

		def find(self, key):
			return self.rows.get(key)

		def create(self, key, value):
			# Gerçek veritabanı gibi: kontrol ve yazma ATOMİK.
			with self.lock:
				self.create_calls += 1
				if key in self.rows:
					raise self.Cakisma(key)
				self.rows[key] = value
				return value

	def test_seri_iki_cagri_tek_kayit(self):
		depo = self.SahteDepo()
		a, yeni_a = idempotent_create(
			ORNEK_SHA,
			lambda: depo.create(ORNEK_SHA, "MA-1"),
			depo.find,
			lambda e: isinstance(e, depo.Cakisma),
		)
		b, yeni_b = idempotent_create(
			ORNEK_SHA,
			lambda: depo.create(ORNEK_SHA, "MA-2"),
			depo.find,
			lambda e: isinstance(e, depo.Cakisma),
		)
		self.assertTrue(yeni_a)
		self.assertFalse(yeni_b)
		self.assertEqual(a, b)
		self.assertEqual(len(depo.rows), 1)

	def test_paralel_iki_finalize_tek_kayit(self):
		"""İki iş parçacığı aynı anda finalize eder; sonuç tek varlık olmalı."""
		depo = self.SahteDepo()
		basla = threading.Barrier(2)
		sonuclar = []
		hatalar = []

		def calis(etiket):
			try:
				basla.wait()
				kayit, yeni = idempotent_create(
					ORNEK_SHA,
					lambda: depo.create(ORNEK_SHA, etiket),
					depo.find,
					lambda e: isinstance(e, depo.Cakisma),
				)
				sonuclar.append((kayit, yeni))
			except Exception as exc:  # noqa: BLE001 — test hatayı raporlamalı
				hatalar.append(exc)

		t1 = threading.Thread(target=calis, args=("MA-A",))
		t2 = threading.Thread(target=calis, args=("MA-B",))
		t1.start()
		t2.start()
		t1.join(5)
		t2.join(5)

		self.assertEqual(hatalar, [], f"yarışta hata: {hatalar}")
		self.assertEqual(len(sonuclar), 2)
		self.assertEqual(len(depo.rows), 1, "iki varlık oluştu — INV-06 ihlali")
		# İkisi de AYNI kaydı görmeli.
		self.assertEqual(sonuclar[0][0], sonuclar[1][0])
		# Tam olarak biri 'yeni' demeli.
		self.assertEqual(sum(1 for _k, yeni in sonuclar if yeni), 1)

	def test_cakisma_disi_hata_yutulmaz(self):
		def patla():
			raise RuntimeError("disk dolu")

		with self.assertRaises(RuntimeError):
			idempotent_create("k", patla, lambda _k: None, lambda e: False)

	def test_cakisma_var_ama_kayit_yok_tutarsizligi(self):
		def cakis():
			raise ValueError("duplicate")

		with self.assertRaises(DedupError):
			idempotent_create("k", cakis, lambda _k: None, lambda e: True)


class AlgisalHashTesti(unittest.TestCase):
	"""dHash — benzer görsel uyarısı. Pillow yoksa atlanır."""

	@classmethod
	def setUpClass(cls):
		try:
			from PIL import Image  # noqa: F401
		except ImportError:
			raise unittest.SkipTest("Pillow kurulu değil")

	def _gorsel(self, w=400, h=400, kaydir=0, kalite=90, fmt="JPEG"):
		from PIL import Image

		im = Image.new("RGB", (w, h))
		px = im.load()
		for y in range(h):
			for x in range(w):
				px[x, y] = ((x * 7 + kaydir) % 256, (y * 5) % 256, ((x + y) * 3) % 256)
		buf = io.BytesIO()
		im.save(buf, fmt, quality=kalite) if fmt == "JPEG" else im.save(buf, fmt)
		return buf.getvalue()

	def test_hash_uzunlugu(self):
		self.assertEqual(len(dedup.dhash(self._gorsel())), 16)

	def test_yeniden_boyutlandirma_ve_sikistirma_hashi_korur(self):
		"""GERÇEK fotoğrafın küçültülmüş + yeniden sıkıştırılmış hâli yakın kalmalı.

		Beklenen tekrar deseni tam olarak bu: satıcı aynı fotoğrafı farklı
		boyda/kalitede yeniden yüklüyor. Sentetik yüksek frekanslı desen
		KULLANILMADI — ölçekleme kırpışması (aliasing) dHash'i gerçek dünyada
		olmadığı kadar oynatıyor ve test motoru değil fikstürü ölçmüş olurdu.
		"""
		from PIL import Image

		yol = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "images" / "ok_product_1x1_2400.jpg"
		if not yol.is_file():
			self.skipTest(f"fikstür yok: {yol}")
		ham = yol.read_bytes()

		with Image.open(io.BytesIO(ham)) as im:
			kucuk = im.convert("RGB").resize((im.width // 2, im.height // 2), Image.LANCZOS)
		buf = io.BytesIO()
		kucuk.save(buf, "JPEG", quality=70)

		a = dedup.dhash(ham)
		b = dedup.dhash(buf.getvalue())
		mesafe = dedup.hamming_distance(a, b)
		self.assertLessEqual(
			mesafe,
			dedup.PHASH_DISTANCE_THRESHOLD,
			f"aynı fotoğrafın yarı boy/q70 hâli {mesafe} bit uzakta (eşik {dedup.PHASH_DISTANCE_THRESHOLD})",
		)

	def test_farkli_gorsel_uzak(self):
		a = dedup.dhash(self._gorsel(kaydir=0))
		b = dedup.dhash(self._gorsel(kaydir=97))
		self.assertGreater(dedup.hamming_distance(a, b), 0)

	def test_farkli_uzunlukta_hash_hata(self):
		with self.assertRaises(DedupError):
			dedup.hamming_distance("ab", "abcd")

	def test_benzer_bulma_siralamasi(self):
		hedef = "0000000000000000"
		adaylar = {"yakin": "0000000000000001", "uzak": "000000000000000f", "cok_uzak": "ffffffffffffffff"}
		bulunan = dedup.find_similar(hedef, adaylar, threshold=8)
		self.assertEqual([w.asset for w in bulunan], ["yakin", "uzak"])
		self.assertLess(bulunan[0].distance, bulunan[1].distance)
		self.assertIn("çok benzer", bulunan[0].message)

	def test_identify_upload_tum_kimlikler(self):
		icerik = self._gorsel()
		kimlik = dedup.identify_upload(icerik, ".jpg")
		self.assertEqual(kimlik.content_sha256, sha256_bytes(icerik))
		self.assertEqual(kimlik.bytes, len(icerik))
		self.assertTrue(kimlik.file_url.startswith("/files/"))
		self.assertEqual(len(kimlik.perceptual_hash), 16)

	def test_gorsel_olmayan_icerikte_phash_bos(self):
		"""PDF/video/bozuk dosya: kimlik yine üretilir, pHash boş kalır."""
		kimlik = dedup.identify_upload(b"%PDF-1.4 bu bir gorsel degil", ".pdf")
		self.assertEqual(kimlik.perceptual_hash, "")
		self.assertTrue(kimlik.file_url.endswith(".pdf"))


if __name__ == "__main__":
	unittest.main(verbosity=2)

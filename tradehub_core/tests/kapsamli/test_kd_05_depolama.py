"""KD-05 — Depolama adaptörü: içerik-adresli yazım, kapsam izolasyonu, imzalı URL.

Kaynak okundu:
  * `media/pipeline/storage/local.py` (639)     — yerel disk adaptörü
  * `media/pipeline/storage/__init__.py` (458)  — mod seçimi ve kurulum
  * `media/pipeline/contracts/storage.py`       — ObjectRef/PutResult sözleşmesi

Denetimin soruları:
  • Aynı içerik iki kez yazılınca aynı anahtar mı üretiliyor (dedup)?
  • `private` kapsamdaki dosya `public` köke sızabiliyor mu?
  • Yol kaçışı (`../`, sembolik bağ) adaptör seviyesinde kapalı mı?
  • İmzalayıcı yokken private URL isteği SESSİZCE imzasız URL mi dönüyor?
  • Yazım atomik mi (yarım dosya diskte kalıyor mu)?
  • Kapasite/kota tavanı gerçekten uygulanıyor mu?
"""

from __future__ import annotations

import os
import tempfile
import unittest

from tradehub_core.media.pipeline.contracts.storage import (
	SCOPE_PRIVATE,
	SCOPE_PUBLIC,
	ObjectRef,
)
from tradehub_core.media.pipeline.storage import MODES, normalize_mode
from tradehub_core.media.pipeline.storage.local import LocalDiskStorage
from tradehub_core.tests.kapsamli import _yardim as y


class _Temel(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.mkdtemp(prefix="kd05-")
		self.public = os.path.join(self.tmp, "public", "files")
		self.private = os.path.join(self.tmp, "private", "files")
		os.makedirs(self.public, exist_ok=True)
		os.makedirs(self.private, exist_ok=True)
		self.depo = LocalDiskStorage(self.public, self.private, fsync=False)


# ══════════════════════════════════════════════════════════════════════
# 1. İçerik-adresli yazım
# ══════════════════════════════════════════════════════════════════════


class TestYazimVeOkuma(_Temel):
	def test_bi_yazilan_icerik_aynen_okunur(self):
		icerik = y.jpeg(64, 64)
		r = self.depo.put(icerik, ".jpg")
		self.assertEqual(self.depo.get(r.ref), icerik)

	def test_bi_ayni_icerik_AYNI_anahtar_uretir(self):
		"""İçerik-adresleme: dedup'ın temeli."""
		icerik = y.jpeg(64, 64)
		a = self.depo.put(icerik, ".jpg")
		b = self.depo.put(icerik, ".jpg")
		self.assertEqual(a.ref.key.name, b.ref.key.name)
		self.assertEqual(a.ref.url, b.ref.url)

	def test_bi_farkli_icerik_FARKLI_anahtar(self):
		a = self.depo.put(y.jpeg(64, 64), ".jpg")
		b = self.depo.put(y.jpeg(65, 65), ".jpg")
		self.assertNotEqual(a.ref.key.name, b.ref.key.name)

	def test_bi_uzanti_anahtara_yansir(self):
		r = self.depo.put(y.png(16, 16), ".png")
		self.assertTrue(r.ref.key.name.endswith(".png"), r.ref.key.name)

	def test_bi_exists_ve_stat(self):
		r = self.depo.put(y.jpeg(32, 32), ".jpg")
		self.assertTrue(self.depo.exists(r.ref))
		st = self.depo.stat(r.ref)
		self.assertGreater(st.size_bytes, 0)
		self.assertEqual(len(st.content_hash), 64)

	def test_bi_iter_bytes_tam_icerigi_verir(self):
		icerik = y.jpeg(200, 200)
		r = self.depo.put(icerik, ".jpg")
		self.assertEqual(b"".join(self.depo.iter_bytes(r.ref, chunk_size=64)), icerik)

	def test_bi_silme_ve_sonrasi(self):
		r = self.depo.put(y.jpeg(32, 32), ".jpg")
		self.assertTrue(self.depo.delete(r.ref))
		self.assertFalse(self.depo.exists(r.ref))
		self.assertFalse(self.depo.delete(r.ref), "ikinci silme False dönmeli")

	def test_sn_bos_icerik_yazimi(self):
		try:
			r = self.depo.put(b"", ".bin")
		except Exception:
			return  # reddetmek de geçerli sözleşme
		self.assertEqual(self.depo.get(r.ref), b"")

	def test_bi_iter_keys_yazilanlari_listeler(self):
		self.depo.put(y.jpeg(16, 16), ".jpg")
		self.depo.put(y.png(16, 16), ".png")
		anahtarlar = list(self.depo.iter_keys(scope=SCOPE_PUBLIC))
		self.assertGreaterEqual(len(anahtarlar), 2)

	def test_bi_usage_bytes_artiyor(self):
		once = self.depo.usage_bytes()
		self.depo.put(y.jpeg(300, 300), ".jpg")
		self.assertGreater(self.depo.usage_bytes(), once)


# ══════════════════════════════════════════════════════════════════════
# 2. Kapsam izolasyonu
# ══════════════════════════════════════════════════════════════════════


class TestKapsamIzolasyonu(_Temel):
	def test_bi_private_dosya_private_kokte(self):
		r = self.depo.put(y.jpeg(32, 32), ".jpg", scope=SCOPE_PRIVATE)
		self.assertTrue(r.ref.is_private)
		self.assertIn("/private/files", r.ref.url)

	def test_gv_private_icerik_public_kokte_YOK(self):
		icerik = y.jpeg(48, 48)
		r = self.depo.put(icerik, ".jpg", scope=SCOPE_PRIVATE)
		public_ref = ObjectRef(key=r.ref.key, scope=SCOPE_PUBLIC)
		self.assertFalse(
			self.depo.exists(public_ref),
			"private dosya public kapsamda görünüyor — kapsam izolasyonu kırık",
		)

	def test_gv_ayni_icerik_iki_kapsamda_ayri_yasar(self):
		icerik = y.jpeg(48, 48)
		pub = self.depo.put(icerik, ".jpg", scope=SCOPE_PUBLIC)
		priv = self.depo.put(icerik, ".jpg", scope=SCOPE_PRIVATE)
		self.depo.delete(pub.ref)
		self.assertTrue(
			self.depo.exists(priv.ref), "public silme private kopyayı da sildi"
		)

	def test_bi_move_kapsam_degistirir(self):
		r = self.depo.put(y.jpeg(32, 32), ".jpg", scope=SCOPE_PUBLIC)
		yeni = self.depo.move(r.ref, SCOPE_PRIVATE)
		self.assertTrue(yeni.is_private)
		self.assertTrue(self.depo.exists(yeni))
		self.assertFalse(self.depo.exists(r.ref), "taşımadan sonra kaynak kalmamalı")

	def test_gv_bilinmeyen_kapsam_reddedilir(self):
		for kotu in ("gizli", "", "PUBLIC", "public/../private"):
			with self.subTest(kotu=kotu):
				with self.assertRaises(Exception):
					self.depo.root(kotu)

	def test_bi_iter_keys_kapsamlar_arasi_sizmaz(self):
		self.depo.put(y.jpeg(16, 16), ".jpg", scope=SCOPE_PUBLIC)
		self.depo.put(y.png(16, 16), ".png", scope=SCOPE_PRIVATE)
		pub = {k.name for k in self.depo.iter_keys(scope=SCOPE_PUBLIC)}
		priv = {k.name for k in self.depo.iter_keys(scope=SCOPE_PRIVATE)}
		self.assertEqual(pub & priv, set(), "iki kapsamda aynı anahtar listelendi")


# ══════════════════════════════════════════════════════════════════════
# 3. Yol güvenliği
# ══════════════════════════════════════════════════════════════════════


class TestYolGuvenligi(_Temel):
	def _ref(self, ad: str, shard: str | None = None) -> ObjectRef:
		"""Kötücül adla `ObjectRef` kur.

		`ObjectKey.__post_init__` shard/ad tutarlılığını zorluyor; saldırgan
		adı yine de tutarlı bir shard ile gelebilir (`../` → shard `..`).
		Bu yüzden shard varsayılan olarak adın ilk iki karakteri.
		"""
		from tradehub_core.media.pipeline.contracts.storage import ObjectKey

		return ObjectRef(key=ObjectKey(shard=shard if shard is not None else ad[:2], name=ad),
						 scope=SCOPE_PUBLIC)

	def test_gv_ust_dizine_cikan_ad_reddedilir(self):
		for kotu in ("../../etc/passwd", "..", "a/../../b", "/etc/passwd"):
			with self.subTest(kotu=kotu):
				with self.assertRaises(Exception):
					self.depo.get(self._ref(kotu))

	def test_gv_ust_dizine_cikan_shard_reddedilir(self):
		with self.assertRaises(Exception):
			self.depo.get(self._ref("a.jpg", shard="../.."))

	def test_gv_null_bayt_ve_kontrol_karakteri_reddedilir(self):
		for kotu in ("a\x00.jpg", "a\n.jpg", "a\r.jpg"):
			with self.subTest(kotu=repr(kotu)):
				with self.assertRaises(Exception):
					self.depo.get(self._ref(kotu))

	def test_gv_bos_ad_ObjectKey_seviyesinde_reddedilir(self):
		with self.assertRaises(Exception):
			self._ref("")

	def test_gv_sembolik_bag_ile_disari_okunamaz(self):
		disari = os.path.join(self.tmp, "gizli.txt")
		with open(disari, "w") as fh:
			fh.write("sır")
		bag = os.path.join(self.public, "ba", "bag.jpg")
		os.makedirs(os.path.dirname(bag), exist_ok=True)
		try:
			os.symlink(disari, bag)
		except OSError:
			self.skipTest("symlink oluşturulamıyor")
		# `realpath` bağı çözdüğü için hedef kök dışına çıkar ve reddedilmeli.
		with self.assertRaises(Exception):
			self.depo.get(self._ref("bag.jpg"))


# ══════════════════════════════════════════════════════════════════════
# 4. İmzalı URL
# ══════════════════════════════════════════════════════════════════════


class TestImzaliUrl(_Temel):
	def test_gv_imzalayici_YOKKEN_private_url_SESSIZCE_verilmez(self):
		"""İmzasız URL dönmek, private dosyayı imzalıymış gibi göstermek olurdu."""
		r = self.depo.put(y.jpeg(32, 32), ".jpg", scope=SCOPE_PRIVATE)
		with self.assertRaises(Exception):
			self.depo.url_for(r.ref)

	def test_bi_public_url_imzasiz_verilebilir(self):
		r = self.depo.put(y.jpeg(32, 32), ".jpg", scope=SCOPE_PUBLIC)
		url = self.depo.url_for(r.ref)
		self.assertTrue(url.startswith("/files"), url)

	def test_bi_imzalayici_varsa_private_url_uretilir(self):
		from tradehub_core.media.pipeline.delivery import signed as signed_urls

		imzalayici = signed_urls.signer_from_secret("kd-test-gizli-anahtar-32-bayt-uzun")
		depo = LocalDiskStorage(self.public, self.private, signer=imzalayici, fsync=False)
		r = depo.put(y.jpeg(32, 32), ".jpg", scope=SCOPE_PRIVATE)
		url = depo.url_for(r.ref, ttl_seconds=60)
		# Private teslim doğrudan dosya yolundan DEĞİL, imzalı bir uç üzerinden:
		# yol sorgu parametresine kodlanıyor, yanına iat/exp/sig ekleniyor.
		self.assertIn("media_access.download", url)
		self.assertIn("%2Fprivate%2Ffiles", url)
		for parametre in ("iat=", "exp=", "sig="):
			self.assertIn(parametre, url, parametre)

	def test_gv_imzali_url_TTL_tasiyor_ve_sonsuz_degil(self):
		from tradehub_core.media.pipeline.delivery import signed as signed_urls

		imzalayici = signed_urls.signer_from_secret("kd-test-gizli-anahtar-32-bayt-uzun")
		depo = LocalDiskStorage(self.public, self.private, signer=imzalayici, fsync=False)
		r = depo.put(y.jpeg(32, 32), ".jpg", scope=SCOPE_PRIVATE)
		params = signed_urls.parse_signed_params(depo.url_for(r.ref, ttl_seconds=60))
		self.assertIn("exp", params)
		self.assertIn("iat", params)
		self.assertGreater(int(params["exp"]), int(params["iat"]), "exp iat'tan büyük olmalı")
		self.assertLessEqual(
			int(params["exp"]) - int(params["iat"]), 3600,
			"TTL bir saati aşıyor — imzalı URL pratikte kalıcı olur",
		)

	def test_gv_imza_kurcalanirsa_dogrulama_DUSER(self):
		from tradehub_core.media.pipeline.delivery import signed as signed_urls

		imzalayici = signed_urls.signer_from_secret("kd-test-gizli-anahtar-32-bayt-uzun")
		depo = LocalDiskStorage(self.public, self.private, signer=imzalayici, fsync=False)
		r = depo.put(y.jpeg(32, 32), ".jpg", scope=SCOPE_PRIVATE)
		url = depo.url_for(r.ref, ttl_seconds=60)
		params = signed_urls.parse_signed_params(url)
		bozuk = params["sig"][:-1] + ("0" if params["sig"][-1] != "0" else "1")
		self.assertNotEqual(bozuk, params["sig"])
		dogrula = getattr(imzalayici, "verify", None)
		if dogrula is None:
			self.skipTest("imzalayıcıda verify() yok — doğrulama başka katmanda")
		karar = dogrula(url.replace(params["sig"], bozuk))
		self.assertFalse(getattr(karar, "ok", False), "kurcalanmış imza kabul edildi")


# ══════════════════════════════════════════════════════════════════════
# 5. Kapasite ve dayanıklılık
# ══════════════════════════════════════════════════════════════════════


class TestKapasiteVeDayaniklilik(_Temel):
	def test_gv_kullanim_tavani_asilirsa_yazim_reddedilir(self):
		depo = LocalDiskStorage(self.public, self.private, fsync=False, max_usage_bytes=1024)
		buyuk = y.jpeg(600, 600, quality=95)
		self.assertGreater(len(buyuk), 1024, "kurgu: içerik tavandan büyük olmalı")
		with self.assertRaises(Exception):
			depo.put(buyuk, ".jpg")

	def test_gv_tavan_altinda_yazim_gecer(self):
		depo = LocalDiskStorage(self.public, self.private, fsync=False, max_usage_bytes=10 * 1024 * 1024)
		self.assertTrue(depo.put(y.jpeg(64, 64), ".jpg").ref.url)

	def test_gv_basarisiz_yazimdan_sonra_YARIM_dosya_kalmaz(self):
		"""Atomik yazım: `.partial`/geçici dosya diskte kalmamalı."""
		depo = LocalDiskStorage(self.public, self.private, fsync=False, max_usage_bytes=512)
		try:
			depo.put(y.jpeg(600, 600, quality=95), ".jpg")
		except Exception:
			pass
		artiklar = []
		for kok, _dizinler, dosyalar in os.walk(self.public):
			for d in dosyalar:
				if d.endswith((".partial", ".tmp")) or d.startswith("."):
					artiklar.append(os.path.join(kok, d))
		self.assertEqual(artiklar, [], f"yarım dosya kaldı: {artiklar}")

	def test_bi_gecici_dosya_supurucusu_calisir(self):
		rapor = self.depo.sweep_temp_files(older_than_seconds=0.0)
		self.assertIsInstance(rapor, dict)

	def test_gv_olmayan_nesne_okunmasi_acik_hata(self):
		from tradehub_core.media.pipeline.contracts.storage import ObjectKey

		ad = "f" * 40 + ".jpg"
		yok = ObjectRef(key=ObjectKey(shard=ad[:2], name=ad), scope=SCOPE_PUBLIC)
		self.assertFalse(self.depo.exists(yok))
		with self.assertRaises(Exception):
			self.depo.get(yok)

	def test_bi_ObjectKey_shard_ad_ile_TUTARLI_olmak_ZORUNDA(self):
		"""Sessiz tutarsızlık kaynağı kapatılmış — sözleşme sabitleniyor."""
		from tradehub_core.media.pipeline.contracts.storage import ObjectKey

		ObjectKey(shard="ab", name="abcdef.jpg")
		with self.assertRaises(ValueError):
			ObjectKey(shard="zz", name="abcdef.jpg")
		with self.assertRaises(ValueError):
			ObjectKey(shard="", name="")

	def test_bi_len_yazilan_nesne_sayisini_verir(self):
		once = len(self.depo)
		self.depo.put(y.jpeg(16, 16), ".jpg")
		self.depo.put(y.png(16, 16), ".png")
		self.assertGreaterEqual(len(self.depo), once + 2)


# ══════════════════════════════════════════════════════════════════════
# 6. Mod seçimi
# ══════════════════════════════════════════════════════════════════════


class TestModSecimi(unittest.TestCase):
	def test_bi_bilinen_modlar(self):
		self.assertEqual(set(MODES), {"local", "s3", "mirror", "tiered"})

	def test_bi_normalize_mode_bilinmeyeni_locale_dusurur_veya_reddeder(self):
		self.assertEqual(normalize_mode("local"), "local")
		self.assertEqual(normalize_mode("LOCAL"), "local")
		self.assertEqual(normalize_mode("  s3  "), "s3")
		for kotu in ("", None, "uydurma", 5):
			with self.subTest(kotu=kotu):
				sonuc = normalize_mode(kotu)
				self.assertIn(sonuc, MODES, f"{kotu!r} → {sonuc!r}")

	def test_gv_S3_KAPALIYKEN_hicbir_kod_yolu_S3_varsaymaz(self):
		"""T-050 sözleşmesi: varsayılan modda S3 istemcisi hiç kurulmamalı."""
		with tempfile.TemporaryDirectory() as d:
			pub = os.path.join(d, "public", "files")
			priv = os.path.join(d, "private", "files")
			os.makedirs(pub)
			os.makedirs(priv)
			depo = LocalDiskStorage(pub, priv, fsync=False)
			r = depo.put(y.jpeg(32, 32), ".jpg")
			self.assertTrue(depo.exists(r.ref))
			self.assertFalse(hasattr(depo, "_s3"), "yerel adaptörde S3 durumu var")


if __name__ == "__main__":
	unittest.main()

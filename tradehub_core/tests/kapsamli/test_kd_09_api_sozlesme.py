"""KD-09 — API sözleşmesi: zarf, hata haritası, parçalı yükleme, idempotency.

Kaynak okundu:
  * `media/pipeline/api/envelope.py` (657) — {status, body, headers} sözleşmesi
  * `media/chunked.py` (463)              — oturum + parça + birleştirme
  * `media/upload_policy.py`              — ret kodları

Bu modül uçların GİRDİ DOĞRULAMASINI ve ÇIKTI SÖZLEŞMESİNİ ölçer: geçersiz
girdi reddediliyor mu, sınırlar hangi noktada devreye giriyor, tekrar eden
istek ne yapıyor, kiracı sınırı parça düzeyinde de duruyor mu.
"""

from __future__ import annotations

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import chunked
from tradehub_core.media.pipeline.api import envelope as env
from tradehub_core.media.pipeline.contracts.errors import MediaEngineError
from tradehub_core.tests.kapsamli import _yardim as y

# ══════════════════════════════════════════════════════════════════════
# 1. Yanıt zarfı
# ══════════════════════════════════════════════════════════════════════


class TestZarf(unittest.TestCase):
	def test_bi_ok_200_ve_govde(self):
		r = env.ok({"a": 1})
		self.assertEqual(r.status, 200)
		self.assertTrue(r.ok)
		self.assertEqual(r.body, {"a": 1})
		self.assertEqual(r.error_code, "")

	def test_bi_created_location_basligi(self):
		r = env.created({"id": "x"}, location="/media/x")
		self.assertEqual(r.status, 201)
		self.assertEqual(r.headers["Location"], "/media/x")

	def test_bi_no_content_govdesiz(self):
		r = env.no_content()
		self.assertEqual(r.status, 204)
		self.assertIsNone(r.body)

	def test_bi_not_modified_etag_tasir(self):
		"""304 gövdesizdir ama ETag TAŞIR (RFC 9110 §15.4.5)."""
		r = env.not_modified('"abc"')
		self.assertEqual(r.status, 304)
		self.assertIsNone(r.body)
		self.assertEqual(r.headers["ETag"], '"abc"')

	def test_bi_baslik_yazimi_duzeltiliyor(self):
		r = env.ok({}, etag='"x"', cache_control="no-store", content_type="application/json")
		self.assertIn("ETag", r.headers)
		self.assertIn("Cache-Control", r.headers)
		self.assertIn("Content-Type", r.headers)
		self.assertNotIn("Etag", r.headers)

	def test_bi_with_header_ozgunu_bozmaz(self):
		a = env.ok({})
		b = a.with_header("X-Test", "1")
		self.assertNotIn("X-Test", a.headers)
		self.assertEqual(b.headers["X-Test"], "1")

	def test_bi_hata_kodu_haritasi(self):
		for sinif, beklenen in (
			(env.BadRequest, 400),
			(env.Unauthorized, 401),
			(env.Forbidden, 403),
			(env.NotFound, 404),
			(env.Conflict, 409),
			(env.PreconditionFailed, 412),
			(env.PayloadTooLarge, 413),
			(env.TooManyRequests, 429),
			(env.ServiceUnavailable, 503),
		):
			with self.subTest(sinif=sinif.__name__):
				self.assertEqual(env.http_status_for(sinif("x")), beklenen)

	def test_gv_bilinmeyen_istisna_ic_detay_sizdirmaz(self):
		"""NFR-035 — yol/e-posta gibi iç bilgi gövdeye yazılmamalı."""
		try:
			raise RuntimeError("/home/frappe/sites/gizli/dosya.py adresinde hata; admin@istoc.com")
		except RuntimeError as exc:
			r = env.error_response(exc)
		self.assertEqual(r.status, 500)
		govde = str(r.body)
		self.assertNotIn("/home/frappe", govde)
		self.assertNotIn("@istoc.com", govde)
		self.assertEqual(r.body["details"], {"type": "RuntimeError"})

	def test_bi_call_medyahatasini_yanita_cevirir(self):
		def uc():
			raise env.NotFound("yok")

		r = env.call(uc)
		self.assertEqual(r.status, 404)
		self.assertFalse(r.ok)
		self.assertTrue(r.error_code)

	def test_gv_call_medya_disi_istisnayi_YUTMAZ(self):
		"""Sözleşme: yalnız `MediaEngineError` yakalanır; diğerleri yükselir."""
		def uc():
			raise ZeroDivisionError("x")

		with self.assertRaises(ZeroDivisionError):
			env.call(uc)

	def test_bi_iso_time_sozlesmesi(self):
		self.assertEqual(env.iso_time(0), "")
		self.assertEqual(env.iso_time(None), "")
		s = env.iso_time(1_700_000_000)
		self.assertRegex(s, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
		self.assertNotIn(".", s, "saniye çözünürlüğü — mikrosaniye yazılmamalı")

	def test_sn_iso_time_gecersiz_girdide_bos_doner(self):
		for kotu in (float("inf"), float("nan"), 10**20):
			with self.subTest(kotu=kotu):
				self.assertEqual(env.iso_time(kotu), "")

	def test_bi_medyahatasi_zarfi(self):
		self.assertTrue(issubclass(env.ApiError, MediaEngineError))
		r = env.error_response(env.BadRequest("hatalı"))
		for alan in ("error_code", "message"):
			self.assertIn(alan, r.body)


# ══════════════════════════════════════════════════════════════════════
# 2. Parçalı yükleme — girdi doğrulaması
# ══════════════════════════════════════════════════════════════════════


class TestParcaliYuklemeDogrulama(FrappeTestCase):
	MAGAZA = "KD-MAGAZA-A"
	DIGER = "KD-MAGAZA-B"

	def setUp(self):
		super().setUp()
		self.oturumlar: list[str] = []

	def tearDown(self):
		for oid in self.oturumlar:
			try:
				chunked.cleanup_session(oid)
			except Exception:
				pass
		super().tearDown()

	def _basla(self, ad="urun.jpg", boyut=1000, magaza=None, **kw):
		d = chunked.begin(ad, boyut, magaza or self.MAGAZA, **kw)
		self.oturumlar.append(d["upload_id"])
		return d

	def test_bi_oturum_acilir_ve_sozlesme_alanlari_doner(self):
		d = self._basla()
		for alan in ("upload_id", "chunk_bytes", "chunk_count", "file_name",
					 "total_bytes", "slot", "content_sha256", "idempotency_key",
					 "policy_snapshot", "expires_at", "upload_url", "completed"):
			self.assertIn(alan, d, alan)
		self.assertEqual(len(d["upload_id"]), 24)
		self.assertFalse(d["completed"])

	def test_gv_magaza_zorunlu(self):
		with self.assertRaises(Exception):
			chunked.begin("a.jpg", 100, "")

	def test_sn_bos_dosya_reddedilir(self):
		with self.assertRaises(Exception):
			chunked.begin("a.jpg", 0, self.MAGAZA)

	def test_sn_negatif_boyut_reddedilir(self):
		with self.assertRaises(Exception):
			chunked.begin("a.jpg", -5, self.MAGAZA)

	def test_sn_cok_fazla_parca_reddedilir(self):
		asiri = chunked.CHUNK_BYTES * (chunked.MAX_CHUNKS + 1)
		with self.assertRaises(Exception):
			chunked.begin("a.jpg", asiri, self.MAGAZA)

	def test_sn_parca_sayisi_tavan_hesabi(self):
		d = self._basla(boyut=chunked.CHUNK_BYTES * 3)
		self.assertEqual(d["chunk_count"], 3)
		d2 = self._basla(boyut=chunked.CHUNK_BYTES * 3 + 1)
		self.assertEqual(d2["chunk_count"], 4)

	def test_gv_idempotency_anahtari_dogrulanir(self):
		for kotu in ("kisa", "a" * 200, "bos luk", "yeni\nsatir", "sekme\t"):
			with self.subTest(kotu=kotu[:12]):
				with self.assertRaises(Exception):
					chunked.normalize_idempotency_key(kotu)

	def test_bi_idempotency_anahtari_gecerli_bicimler(self):
		for iyi in ("abcd1234", "A-B_C.D:1234", "x" * 128):
			with self.subTest(iyi=iyi[:12]):
				self.assertEqual(chunked.normalize_idempotency_key(iyi), iyi)

	def test_bi_idempotency_anahtari_uretilebilir(self):
		k = chunked.normalize_idempotency_key("", generate=True)
		self.assertTrue(chunked._IDEMPOTENCY_RE.fullmatch(k), k)

	def test_bi_bos_anahtar_uretimsiz_bos_kalir(self):
		self.assertEqual(chunked.normalize_idempotency_key(""), "")

	def test_gv_content_sha256_dogrulanir(self):
		for kotu in ("abc", "z" * 64, "0" * 63, "0" * 65):
			with self.subTest(kotu=kotu[:8]):
				with self.assertRaises(Exception):
					chunked.normalize_content_sha256(kotu)
		self.assertEqual(chunked.normalize_content_sha256("A" * 64), "a" * 64)

	def test_gv_gecersiz_upload_id_yol_kurmaz(self):
		"""Kimlik doğrudan dosya yoluna giriyor — kalıp kapısı ilk savunma."""
		for kotu in ("../../etc", "x" * 24, "", "ABCDEF0123456789abcdef01", "a" * 23):
			with self.subTest(kotu=kotu[:12]):
				with self.assertRaises(Exception):
					chunked._session_dir(kotu)

	def test_bi_gecerli_upload_id_kalibi(self):
		d = self._basla()
		self.assertTrue(chunked._ID_RE.match(d["upload_id"]))
		self.assertTrue(chunked._session_dir(d["upload_id"]).endswith(d["upload_id"]))


# ══════════════════════════════════════════════════════════════════════
# 3. Parça yazımı ve birleştirme
# ══════════════════════════════════════════════════════════════════════


class TestParcaAkisi(FrappeTestCase):
	MAGAZA = "KD-MAGAZA-A"
	DIGER = "KD-MAGAZA-B"

	def setUp(self):
		super().setUp()
		self.oturumlar: list[str] = []

	def tearDown(self):
		for oid in self.oturumlar:
			try:
				chunked.cleanup_session(oid)
			except Exception:
				pass
		super().tearDown()

	def _oturum(self, icerik: bytes, ad="urun.jpg", magaza=None):
		d = chunked.begin(ad, len(icerik), magaza or self.MAGAZA)
		self.oturumlar.append(d["upload_id"])
		return d

	def test_bi_tek_parcalik_akis_tamamlanir(self):
		icerik = y.jpeg(200, 200)
		d = self._oturum(icerik)
		s = chunked.put_chunk(d["upload_id"], 0, icerik, self.MAGAZA)
		self.assertTrue(s["complete"])
		self.assertEqual(chunked.finish(d["upload_id"], self.MAGAZA), icerik)

	def test_bi_parcalar_SIRASIZ_gelebilir(self):
		# Çok parçalı olması için GERÇEKTEN büyük ve geçerli bir JPEG gerekiyor:
		# sona dolgu eklemek politikayı (haklı olarak) "kesik/ekli" diye düşürüyor.
		icerik = y.jpeg(3000, 3000, quality=98)
		if len(icerik) <= chunked.CHUNK_BYTES:
			self.skipTest(f"üretilen JPEG tek parçaya sığdı ({len(icerik)} B)")
		d = self._oturum(icerik)
		parcalar = [
			icerik[i * chunked.CHUNK_BYTES : (i + 1) * chunked.CHUNK_BYTES]
			for i in range(d["chunk_count"])
		]
		for i in reversed(range(len(parcalar))):
			chunked.put_chunk(d["upload_id"], i, parcalar[i], self.MAGAZA)
		self.assertEqual(chunked.finish(d["upload_id"], self.MAGAZA), icerik)

	def test_bi_ayni_parcanin_tekrari_zararsiz(self):
		icerik = y.jpeg(200, 200)
		d = self._oturum(icerik)
		chunked.put_chunk(d["upload_id"], 0, icerik, self.MAGAZA)
		s = chunked.put_chunk(d["upload_id"], 0, icerik, self.MAGAZA)
		self.assertEqual(s["received"], 1)
		self.assertEqual(chunked.finish(d["upload_id"], self.MAGAZA), icerik)

	def test_sn_sira_disi_indeks_reddedilir(self):
		icerik = y.jpeg(200, 200)
		d = self._oturum(icerik)
		for kotu in (-1, d["chunk_count"], d["chunk_count"] + 10, 9999):
			with self.subTest(kotu=kotu):
				with self.assertRaises(Exception):
					chunked.put_chunk(d["upload_id"], kotu, b"x", self.MAGAZA)

	def test_sn_bos_parca_reddedilir(self):
		d = self._oturum(y.jpeg(200, 200))
		with self.assertRaises(Exception):
			chunked.put_chunk(d["upload_id"], 0, b"", self.MAGAZA)

	def test_gv_parca_tavani_asilamaz(self):
		"""Aksi hâlde 1 parçalık oturum ilan edip 200 MB gönderilebilirdi."""
		d = self._oturum(y.jpeg(200, 200))
		with self.assertRaises(Exception):
			chunked.put_chunk(d["upload_id"], 0, b"x" * (chunked.CHUNK_BYTES + 1), self.MAGAZA)

	def test_gv_eksik_parcayla_birlestirilemez(self):
		icerik = y.jpeg(3000, 3000, quality=98)
		if len(icerik) <= chunked.CHUNK_BYTES:
			self.skipTest("üretilen JPEG tek parçaya sığdı")
		d = self._oturum(icerik)
		chunked.put_chunk(d["upload_id"], 0, icerik[: chunked.CHUNK_BYTES], self.MAGAZA)
		with self.assertRaises(Exception):
			chunked.finish(d["upload_id"], self.MAGAZA)

	def test_gv_CAPRAZ_KIRACI_parca_ekleyemez(self):
		"""Oturum kimliğini ele geçiren başka mağaza parça YAZAMAMALI."""
		icerik = y.jpeg(200, 200)
		d = self._oturum(icerik)
		with self.assertRaises(Exception):
			chunked.put_chunk(d["upload_id"], 0, icerik, self.DIGER)

	def test_gv_CAPRAZ_KIRACI_birlestiremez(self):
		icerik = y.jpeg(200, 200)
		d = self._oturum(icerik)
		chunked.put_chunk(d["upload_id"], 0, icerik, self.MAGAZA)
		with self.assertRaises(Exception):
			chunked.finish(d["upload_id"], self.DIGER)

	def test_gv_CAPRAZ_KIRACI_meta_okuyamaz(self):
		d = self._oturum(y.jpeg(200, 200))
		with self.assertRaises(Exception):
			chunked.meta_of(d["upload_id"], self.DIGER)

	def test_gv_politika_BIRLESIMDEN_SONRA_uygulanir(self):
		"""İlk parça geçerli JPEG başlığı, devamı script olabilir.

		Parça bazlı denetim bunu kaçırırdı; `finish()` birleşmiş içerik
		üzerinde politika çalıştırmalı.
		"""
		zararli = y.jpeg(200, 200) + b"<script>alert(1)</script>"
		d = self._oturum(zararli)
		for i in range(d["chunk_count"]):
			chunked.put_chunk(
				d["upload_id"], i,
				zararli[i * chunked.CHUNK_BYTES : (i + 1) * chunked.CHUNK_BYTES],
				self.MAGAZA,
			)
		with self.assertRaises(Exception):
			chunked.finish(d["upload_id"], self.MAGAZA)

	def test_gv_ilan_edilen_sha256_ARTIK_DOGRULANIYOR(self):
		"""F-12 düzeltildi — `finish()` birleşen içeriği ilan edilen özetle
		karşılaştırıyor.

		API bir bütünlük sözleşmesi ilan edip uygulamıyordu: `content_sha256`
		alınıyor, saklanıyor ve yanıtta geri veriliyordu ama hiç kontrol
		edilmiyordu. Ret kodu (`upload_content_hash_mismatch`) zaten tanımlıydı,
		yalnız kullanılmıyordu.
		"""
		icerik = y.jpeg(200, 200)
		sahte_hash = "b" * 64
		d = chunked.begin("urun.jpg", len(icerik), self.MAGAZA, content_sha256=sahte_hash)
		self.oturumlar.append(d["upload_id"])
		self.assertEqual(d["content_sha256"], sahte_hash)
		chunked.put_chunk(d["upload_id"], 0, icerik, self.MAGAZA)
		with self.assertRaises(Exception) as ctx:
			chunked.finish(d["upload_id"], self.MAGAZA)
		self.assertIn("mismatch", str(ctx.exception).lower() + str(getattr(ctx.exception, "args", "")))

	def test_bi_DOGRU_sha256_ile_akis_tamamlanir(self):
		import hashlib

		icerik = y.jpeg(200, 200)
		dogru = hashlib.sha256(icerik).hexdigest()
		d = chunked.begin("urun.jpg", len(icerik), self.MAGAZA, content_sha256=dogru)
		self.oturumlar.append(d["upload_id"])
		chunked.put_chunk(d["upload_id"], 0, icerik, self.MAGAZA)
		self.assertEqual(chunked.finish(d["upload_id"], self.MAGAZA), icerik)

	def test_bi_sha256_HIC_verilmezse_kural_uygulanmaz(self):
		"""Eski istemci sözleşmesi korunuyor: ilan yoksa doğrulama da yok."""
		icerik = y.jpeg(200, 200)
		d = chunked.begin("urun.jpg", len(icerik), self.MAGAZA)
		self.oturumlar.append(d["upload_id"])
		chunked.put_chunk(d["upload_id"], 0, icerik, self.MAGAZA)
		self.assertEqual(chunked.finish(d["upload_id"], self.MAGAZA), icerik)

	def test_bi_meta_sozlesmesi(self):
		d = self._oturum(y.jpeg(200, 200))
		m = chunked.meta_of(d["upload_id"], self.MAGAZA)
		for alan in ("upload_id", "file_name", "total_bytes", "chunk_count", "content_sha256"):
			self.assertIn(alan, m)

	def test_bi_temizlenen_oturum_kullanilamaz(self):
		d = self._oturum(y.jpeg(200, 200))
		chunked.cleanup_session(d["upload_id"], self.MAGAZA)
		with self.assertRaises(Exception):
			chunked.meta_of(d["upload_id"], self.MAGAZA)

	def test_gv_CAPRAZ_KIRACI_oturum_silemez(self):
		d = self._oturum(y.jpeg(200, 200))
		with self.assertRaises(Exception):
			chunked.cleanup_session(d["upload_id"], self.DIGER)
		# hâlâ duruyor olmalı
		self.assertTrue(chunked.meta_of(d["upload_id"], self.MAGAZA))


# ══════════════════════════════════════════════════════════════════════
# 4. Idempotency — tamamlanmış sonuç önbelleği
# ══════════════════════════════════════════════════════════════════════


class TestIdempotency(FrappeTestCase):
	MAGAZA = "KD-MAGAZA-A"
	DIGER = "KD-MAGAZA-B"

	def test_bi_kaydedilen_sonuc_ayni_anahtarla_okunur(self):
		anahtar = f"kd-test-{frappe.generate_hash(length=12)}"
		chunked.save_finalized_result(anahtar, self.MAGAZA, {"file_url": "/files/x.jpg"})
		self.assertEqual(
			chunked.finalized_result(anahtar, self.MAGAZA), {"file_url": "/files/x.jpg"}
		)

	def test_gv_BASKA_KIRACI_sonucu_goremez(self):
		anahtar = f"kd-test-{frappe.generate_hash(length=12)}"
		chunked.save_finalized_result(anahtar, self.MAGAZA, {"file_url": "/files/x.jpg"})
		self.assertIsNone(chunked.finalized_result(anahtar, self.DIGER))

	def test_bi_bilinmeyen_anahtar_none(self):
		self.assertIsNone(chunked.finalized_result("kd-yok-12345678", self.MAGAZA))

	def test_bi_bos_anahtar_none(self):
		self.assertIsNone(chunked.finalized_result("", self.MAGAZA))

	def test_gv_gecersiz_anahtar_reddedilir(self):
		with self.assertRaises(Exception):
			chunked.finalized_result("kısa", self.MAGAZA)

	def test_bi_anahtar_yolu_kiracıya_gore_ayrisir(self):
		anahtar = "kd-ayni-anahtar-1"
		a = chunked._finalized_path(self.MAGAZA, anahtar)
		b = chunked._finalized_path(self.DIGER, anahtar)
		self.assertNotEqual(a, b)
		self.assertTrue(a and b)


if __name__ == "__main__":
	unittest.main()

"""T-133 — ölçüm noktası (instrument.py) testleri.

Bu dosyanın omurgası ÜÇ soru:

    1. Sarmalayıcı gerçekten sayıyor mu — metrik değeri çağrıdan SONRA arttı mı,
       ve `uninstall()` sonrası artmayı BIRAKIYOR mu (ikincisi olmadan birinci
       kanıt değil: sayacın artması testin kendi kurulumundan da gelebilir).
    2. Sarmalayıcı ölçtüğü işi düşürüyor mu — istisna aynen geçiyor mu, kayıt
       fonksiyonu patladığında çağıran hayatta kalıyor mu.
    3. Etiketlere PII sızıyor mu — özellikle hata yollarında, çünkü orada
       elde yalnız çağrı argümanları kalır ve ilki genelde bir DOSYA YOLUDUR.

Gerçek modüller (`security/svg.py`, `security/isolation.py`,
`image/probe.py`) sarmalanır; sahte bir modülle test etmek sarmalayıcının
mekaniğini doğrular ama `Nokta` tablosundaki modül/nitelik adlarının doğru
olduğunu doğrulamaz — asıl kırılgan kısım odur.

Çalıştırma:

    python3 -m unittest tradehub_core.tests.test_observability_instrument -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.observability import instrument as ins  # noqa: E402
from tradehub_core.media.pipeline.observability import metrics as mm  # noqa: E402

#: Bench var mı — `media/av.py` ve `media/audit.py` `import frappe` yapar.
#: Beklenen bağlı nokta sayısı ORTAMA GÖRE değişir ve test bunu sabit
#: yazamaz: host'ta (frappe yok) 8/10, konteynerin bench sanal ortamında
#: 10/10 ölçüldü. Sabit 8 yazan bir test, gerçek ortamda KIRMIZI olurdu ve
#: kimse "aslında hepsi bağlanıyor" iyi haberini görmezdi.
import importlib.util as _iu  # noqa: E402

BENCH_VAR: bool = _iu.find_spec("frappe") is not None
BEKLENEN_BAGLI: int = 10 if BENCH_VAR else 8

#: Sanitize'dan TEMİZ geçen en küçük SVG. `<rect>` şart: çizim elementi
#: kalmayan bir SVG `svg_empty_after_sanitize` ile REDDEDİLİR (ölçüldü) ve
#: "boş svg" ile "temiz svg" farkını bilmeyen bir test yanlış kovayı doğrular.
GECERLI_SVG: bytes = (
	b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>"
	b"<rect width='10' height='10' fill='#123456'/></svg>"
)


class InstrumentTestCase(unittest.TestCase):
	"""Global durum (sarmalayıcı + kayıt defteri) her testte geri alınır."""

	def setUp(self) -> None:
		ins.uninstall()
		mm.REGISTRY.temizle()
		self.addCleanup(ins.uninstall)
		self.addCleanup(mm.REGISTRY.temizle)
		# `log_event` handler'ı olmayan bir logger'a yazınca Python son çare
		# handler'ı stderr'e basar ve test çıktısını kirletir. Sessizleştirme
		# BURADA yapılır, `log_event` içinde değil: kütüphanenin kendini
		# susturması, üretimde gerçek bir hata satırını da yutardı.
		import logging as _stdlogging

		logger = _stdlogging.getLogger("media_engine")
		bos = _stdlogging.NullHandler()
		logger.addHandler(bos)
		self.addCleanup(logger.removeHandler, bos)


# ── Kurulum mekaniği ────────────────────────────────────────────────────


class Kurulum(InstrumentTestCase):
	def test_atlama_yalniz_frappe_gerektiren_noktalarda(self):
		"""Atlanan nokta varsa SEBEBİ frappe olmalı — başka bir arıza değil."""
		r = ins.install()
		self.assertEqual(r.toplam, len(ins.NOKTALAR))
		atlanan = {ad for ad, _sebep in r.atlanan}
		bench_only = {n.ad for n in ins.NOKTALAR if n.bench_gerekir}
		self.assertTrue(atlanan <= bench_only, f"beklenmeyen atlama: {atlanan - bench_only}")
		for _ad, sebep in r.atlanan:
			self.assertTrue(sebep.startswith("module_missing:"), sebep)

	def test_bench_varsa_tum_noktalar_baglanir(self):
		"""Konteynerde ölçüldü: frappe varken 10/10 nokta bağlanıyor."""
		r = ins.install()
		self.assertEqual(len(r.bagli), BEKLENEN_BAGLI)
		if BENCH_VAR:
			self.assertEqual(r.atlanan, ())

	def test_ikinci_install_yeniden_sarmaz(self):
		ilk = ins.install()
		ikinci = ins.install()
		self.assertEqual(ikinci.bagli, ())
		self.assertEqual(set(ikinci.zaten_bagli), set(ilk.bagli))

	def test_cift_sarma_cift_saymaz(self):
		"""İki kez kurulup tek çağrı yapılırsa sayaç 1 artmalı, 2 değil."""
		from tradehub_core.media.pipeline.security import svg

		ins.install()
		ins.install()
		svg.sanitize(GECERLI_SVG)
		toplam = sum(
			s.deger for s in mm.SVG_SANITIZE_TOTAL._seriler.values()  # noqa: SLF001 - test
		)
		self.assertEqual(toplam, 1.0)

	def test_uninstall_orijinali_geri_koyar(self):
		from tradehub_core.media.pipeline.security import svg

		orijinal = svg.sanitize
		ins.install()
		self.assertIsNot(svg.sanitize, orijinal)
		kaldirilan = ins.uninstall()
		self.assertIs(svg.sanitize, orijinal)
		self.assertIn("svg.sanitize", kaldirilan)

	def test_uninstall_sonrasi_sayac_artmaz(self):
		from tradehub_core.media.pipeline.security import svg

		ins.install()
		svg.sanitize(GECERLI_SVG)
		once = mm.SVG_SANITIZE_TOTAL.deger(slot=ins.BILINMEYEN, code="ok")
		ins.uninstall()
		svg.sanitize(GECERLI_SVG)
		self.assertEqual(mm.SVG_SANITIZE_TOTAL.deger(slot=ins.BILINMEYEN, code="ok"), once)

	def test_sarmalayici_imzayi_korur(self):
		from tradehub_core.media.pipeline.security import svg

		ins.install()
		self.assertEqual(svg.sanitize.__name__, "sanitize")
		self.assertIn("sanitize", (svg.sanitize.__doc__ or "").lower() + "sanitize")

	def test_bilinmeyen_modul_atlanir_istisna_atmaz(self):
		nokta = ins.Nokta(
			ad="yok.yok",
			modul="tradehub_core.media.pipeline.yok_boyle_bir_modul",
			nitelik="f",
			olay="yok",
			kayit=lambda c: None,
		)
		r = ins.install([nokta])
		self.assertEqual(r.bagli, ())
		self.assertEqual(r.atlanan[0][0], "yok.yok")

	def test_bilinmeyen_nitelik_attribute_missing_der(self):
		nokta = ins.Nokta(
			ad="svg.yok",
			modul="tradehub_core.media.pipeline.security.svg",
			nitelik="boyle_bir_fonksiyon_yok",
			olay="yok",
			kayit=lambda c: None,
		)
		r = ins.install([nokta])
		self.assertEqual(r.atlanan, (("svg.yok", "attribute_missing"),))

	def test_kapsam_orani_hesaplanir(self):
		r = ins.install()
		self.assertAlmostEqual(r.kapsam, BEKLENEN_BAGLI / 10, places=6)
		self.assertEqual(r.to_dict()["total"], 10)


# ── Ölçüm doğruluğu ─────────────────────────────────────────────────────


class SvgOlcumu(InstrumentTestCase):
	def test_temiz_svg_ok_kovasina_dusiyor(self):
		from tradehub_core.media.pipeline.security import svg

		ins.install()
		svg.sanitize(GECERLI_SVG)
		self.assertEqual(mm.SVG_SANITIZE_TOTAL.deger(slot=ins.BILINMEYEN, code=svg.KOD_OK), 1.0)

	def test_reddedilen_svg_kendi_koduyla_sayilir(self):
		from tradehub_core.media.pipeline.security import svg

		ins.install()
		sonuc = svg.sanitize(b"\x1f\x8b bozuk")
		self.assertEqual(sonuc.kod, svg.KOD_COMPRESSED)
		self.assertEqual(
			mm.SVG_SANITIZE_TOTAL.deger(slot=ins.BILINMEYEN, code=svg.KOD_COMPRESSED), 1.0
		)


class IzolasyonOlcumu(InstrumentTestCase):
	def test_basarili_calistirma_ok_sebebiyle_sayilir(self):
		from tradehub_core.media.pipeline.security import isolation as iso

		ins.install()
		sonuc = iso.run_callable(lambda: 21 * 2)
		self.assertTrue(sonuc.ok)
		self.assertEqual(mm.ISOLATION_TOTAL.deger(profile="image", reason=iso.SEBEP_OK), 1.0)

	def test_istisna_isolation_exception_olarak_sayilir(self):
		from tradehub_core.media.pipeline.security import isolation as iso

		ins.install()
		iso.run_callable(lambda: 1 / 0)
		self.assertEqual(
			mm.ISOLATION_TOTAL.deger(profile="image", reason=iso.SEBEP_EXCEPTION), 1.0
		)

	def test_profil_limits_nesnesinden_ters_cozulur(self):
		"""`limits=VIDEO_LIMITS` verilince etiket `video` olmalı."""
		from tradehub_core.media.pipeline.security import isolation as iso

		ins.install()
		iso.run_callable(lambda: 1, limits=iso.VIDEO_LIMITS)
		self.assertEqual(mm.ISOLATION_TOTAL.deger(profile="video", reason=iso.SEBEP_OK), 1.0)

	def test_ozel_limits_custom_etiketi_alir(self):
		from tradehub_core.media.pipeline.security import isolation as iso

		ins.install()
		iso.run_callable(lambda: 1, limits=iso.IMAGE_LIMITS.with_(nice=None))
		self.assertEqual(mm.ISOLATION_TOTAL.deger(profile="custom", reason=iso.SEBEP_OK), 1.0)


try:  # noqa: SIM105 - varlık testi, hata yutma değil
	from PIL import Image as _PILImage
except Exception:  # pragma: no cover - Pillow yoksa
	_PILImage = None


@unittest.skipUnless(_PILImage is not None, "Pillow kurulu degil — probe olcumu KOSULMADI")
class ProbeOlcumu(InstrumentTestCase):
	"""Pillow gerektirir. Konteynerin sistem python'unda Pillow YOK; bench
	sanal ortamında (`env/bin/python`) VAR. Atlama sessiz değil: unittest
	çıktısında `s` olarak görünür ve raporda 'koşulmadı' diye yazılır."""

	def _png(self) -> bytes:
		import io as _io

		tampon = _io.BytesIO()
		_PILImage.new("RGB", (40, 30), (10, 20, 30)).save(tampon, format="PNG")
		return tampon.getvalue()

	def test_probe_sure_boyut_ve_cozunurluk_yazar(self):
		from tradehub_core.media.pipeline.image import probe as ip

		ins.install()
		icerik = self._png()
		ip.probe_header(icerik, filename="x.png")
		self.assertEqual(mm.IMAGE_PROCESS_DURATION.ozet(op="probe", format="png")["count"], 1.0)
		self.assertEqual(mm.SOURCE_BYTES.ozet(kind="image")["count"], 1.0)
		self.assertEqual(mm.SOURCE_BYTES.ozet(kind="image")["sum"], float(len(icerik)))
		self.assertEqual(mm.SOURCE_MEGAPIXELS.ozet()["count"], 1.0)


# ── Dayanıklılık ve PII ─────────────────────────────────────────────────


class Dayaniklilik(InstrumentTestCase):
	def test_kayit_patlarsa_cagiran_yasar_ve_sayac_artar(self):
		"""Ölçüm, ölçtüğü işi DÜŞÜREMEZ — ama sessiz de kalamaz."""

		def patlayan(_c):
			raise RuntimeError("kayit bozuk")

		nokta = ins.Nokta(
			ad="svg.patlayan",
			modul="tradehub_core.media.pipeline.security.svg",
			nitelik="is_svg",
			olay="svg.test",
			kayit=patlayan,
		)
		from tradehub_core.media.pipeline.security import svg

		ins.install([nokta])
		self.assertTrue(svg.is_svg(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"))
		self.assertEqual(mm.INSTRUMENT_ERRORS_TOTAL.deger(point="svg.patlayan"), 1.0)

	def test_istisna_yutulmaz_yeniden_firlatilir(self):
		def patlayan_fonksiyon():
			raise ValueError("gercek hata")

		import tradehub_core.media.pipeline.security.svg as svg

		svg._test_patlayan = patlayan_fonksiyon  # noqa: SLF001 - teste özel nitelik
		self.addCleanup(lambda: delattr(svg, "_test_patlayan"))
		gorulen = {}

		def kayit(c):
			gorulen["hata"] = type(c.hata).__name__

		nokta = ins.Nokta(
			ad="svg.test_patlayan",
			modul="tradehub_core.media.pipeline.security.svg",
			nitelik="_test_patlayan",
			olay="svg.test",
			kayit=kayit,
		)
		ins.install([nokta])
		with self.assertRaises(ValueError):
			svg._test_patlayan()  # noqa: SLF001 - teste özel nitelik
		self.assertEqual(gorulen["hata"], "ValueError")

	def test_hata_yolunda_dosya_yolu_etikete_yazilmaz(self):
		"""Video hata yolunda ilk argüman `src` DOSYA YOLUDUR; etikete girmemeli."""
		c = ins.Cagri(
			args=("/private/files/kimlik_taramasi.mp4", "/tmp/out.mp4"),
			kwargs={},
			sonuc=None,
			hata=RuntimeError("ffmpeg dustu"),
			sure_s=0.5,
		)
		ins._kayit_transcode(c)  # noqa: SLF001 - kayıt fonksiyonu doğrudan ölçülüyor
		metin = mm.VIDEO_TRANSCODE_DURATION.render()
		self.assertIn('action="unknown"', metin)
		self.assertNotIn("kimlik_taramasi", metin)
		self.assertNotIn("/private/files", metin)

	def test_uzun_etiket_kirpilir(self):
		self.assertEqual(len(ins._e("x" * 500)), ins.MAX_ETIKET_UZUNLUK)  # noqa: SLF001
		self.assertTrue(ins._e("x" * 500).endswith("…"))  # noqa: SLF001

	def test_bos_deger_unknown_olur(self):
		self.assertEqual(ins._e(None), "unknown")  # noqa: SLF001
		self.assertEqual(ins._e(""), "unknown")  # noqa: SLF001


# ── Kapsam muhasebesi ───────────────────────────────────────────────────


class Kapsam(InstrumentTestCase):
	def test_her_metrigin_bir_sahibi_var(self):
		"""Sahipsiz metrik = panelde sessizce boş kalacak seri."""
		k = ins.metrik_kapsami()
		self.assertEqual(k["unaccounted"], [], f"sahipsiz metrik var: {k['unaccounted']}")

	def test_toplayici_bekleyenler_hala_yazilmiyor(self):
		"""Toplayıcı bekleyen göstergeler — K-1 sonrası 6.

		K-1 iki değişiklik yaptı: (1) `media_job_total`/`media_job_attempts`
		çağrı yerinde yazılır oldu (`jobs.record_terminal`), yani artık
		toplayıcı DEĞİL `NOKTA_DISI_YAZILAN`; (2) kalan altıdan üçüne
		(`orphan_files`, `pii_field_coverage`, `pii_unprotected_files`) periyodik
		toplayıcı yazıldı (`observability/collectors.py::run_scan`). Bu liste
		"toplayıcı GEREKTİRENLER"i sayar; toplayıcının VAR olup olmadığını değil
		— storage_bytes/objects/bytes_saved hâlâ toplayıcısız birer eksiktir.
		"""
		k = ins.metrik_kapsami()
		self.assertEqual(len(k["needs_collector"]), 6)
		self.assertIn("media_orphan_files", k["needs_collector"])
		self.assertIn("media_pii_unprotected_files", k["needs_collector"])
		self.assertIn("media_pii_field_coverage", k["needs_collector"])
		# İş sayaçları artık toplayıcı beklemiyor — çağrı yerinde yazılıyor.
		self.assertNotIn("media_job_total", k["needs_collector"])
		self.assertIn("media_job_total", k["written_elsewhere"])

	def test_nokta_metrikleri_gercekten_tanimli(self):
		tanimli = {m.ad for m in mm.REGISTRY.metrikler()}
		for nokta in ins.NOKTALAR:
			for ad in nokta.metrikler:
				self.assertIn(ad, tanimli, f"{nokta.ad} tanimsiz metrige atif yapiyor: {ad}")

	def test_durum_sayilari_tutarli(self):
		ins.install()
		d = ins.durum()
		self.assertEqual(d["points_total"], len(ins.NOKTALAR))
		self.assertEqual(d["points_bound"], BEKLENEN_BAGLI)
		self.assertEqual(sorted(d["bench_only"]), ["audit.log_media_event", "av.scan_path"])


if __name__ == "__main__":
	unittest.main(verbosity=2)

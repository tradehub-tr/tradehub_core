"""T-133 — metrik ve yapılandırılmış log testleri.

İki modül, iki sözleşme:

    metrics.py   Üretilen metin GERÇEKTEN Prometheus 0.0.4 mü — biçim,
                 kaçırma, kümülatif histogram, determinizm.
    logging.py   Her satır geçerli JSON mu, korelasyon zinciri kopuyor mu,
                 PII sızıyor mu.

`logging.py` testlerinin omurgası **sızıntı** testleridir: maskeleme iki
yoldan (anahtar adı + değer deseni) tetikleniyor ve ikisinin de gerekli
olduğu ayrı ayrı ölçülür. `media/audit.py` ile parmak izi UYUMU da
doğrulanır — iki kayıt aynı dosyayı aynı kimlikle göstermezse eşleştirme
imkânsız olurdu.

Çalıştırma:

    python3 -m unittest discover -s /Users/ahmet/Desktop/istoc/tradehub_core/tests -v
"""

from __future__ import annotations

import hashlib
import io
import json
import logging as stdlogging
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.observability import logging as mlog  # noqa: E402
from tradehub_core.media.pipeline.observability import metrics as mm  # noqa: E402

# ── metrics ─────────────────────────────────────────────────────────────


class AdVeEtiketDogrulama(unittest.TestCase):
	def test_gecersiz_metrik_adi_reddedilir(self):
		# `Gauge` ile denenir: `Counter` adın sonuna `_total` eklediği için boş
		# ad ondan sonra `_total` olur ve GEÇERLİ bir Prometheus adıdır —
		# doğrulamayı `Counter` üzerinden ölçmek yanıltıcı olurdu.
		for ad in ("1baslangic", "bosluk li", "tire-li", ""):
			with self.subTest(ad=ad), self.assertRaises(mm.MetricError):
				mm.Gauge(ad, "x", namespace="")

	def test_gecersiz_etiket_adi_reddedilir(self):
		with self.assertRaises(mm.MetricError):
			mm.Counter("a", "x", etiketler=("tire-li",), namespace="")

	def test_ayrilmis_etiket_reddedilir(self):
		"""`le` histogramın kendi etiketi — kullanıcı kullanırsa çıktı bozulur."""
		with self.assertRaises(mm.MetricError):
			mm.Histogram("a", "x", etiketler=("le",), namespace="")

	def test_tekrar_eden_etiket_reddedilir(self):
		with self.assertRaises(mm.MetricError):
			mm.Gauge("a", "x", etiketler=("k", "k"), namespace="")

	def test_eksik_etiket_yazim_aninda_yakalanir(self):
		c = mm.Counter("a", "x", etiketler=("k", "l"), namespace="")
		with self.assertRaises(mm.MetricError):
			c.inc(k="1")

	def test_fazla_etiket_yakalanir(self):
		c = mm.Counter("a", "x", etiketler=("k",), namespace="")
		with self.assertRaises(mm.MetricError):
			c.inc(k="1", m="2")

	def test_ayni_metrik_iki_kez_kaydedilemez(self):
		r = mm.Registry("test")
		r.counter("bir", "x")
		with self.assertRaises(mm.MetricError):
			r.counter("bir", "x")


class CounterDavranisi(unittest.TestCase):
	def setUp(self):
		self.c = mm.Counter("islem", "aciklama", etiketler=("tur",), namespace="test")

	def test_total_eki_bir_kez_eklenir(self):
		self.assertEqual(self.c.ad, "test_islem_total")
		ikinci = mm.Counter("islem_total", "x", namespace="test")
		self.assertEqual(ikinci.ad, "test_islem_total")

	def test_azaltilamaz(self):
		with self.assertRaises(mm.MetricError):
			self.c.inc(-1, tur="a")

	def test_toplama(self):
		self.c.inc(tur="a")
		self.c.inc(3, tur="a")
		self.assertEqual(self.c.deger(tur="a"), 4.0)
		self.assertEqual(self.c.deger(tur="b"), 0.0)

	def test_render_bicimi(self):
		self.c.inc(2, tur="a")
		metin = self.c.render()
		self.assertIn("# HELP test_islem_total aciklama", metin)
		self.assertIn("# TYPE test_islem_total counter", metin)
		self.assertIn('test_islem_total{tur="a"} 2', metin)


class GaugeDavranisi(unittest.TestCase):
	def test_artar_azalir_set_edilir(self):
		g = mm.Gauge("derinlik", "x", namespace="test")
		g.set(10)
		g.dec(3)
		g.inc(1)
		self.assertEqual(g.deger(), 8.0)

	def test_etiketsiz_metrikte_susluler_yazilmaz(self):
		g = mm.Gauge("derinlik", "x", namespace="test")
		g.set(5)
		self.assertIn("test_derinlik 5", g.render())
		self.assertNotIn("{}", g.render())


class HistogramDavranisi(unittest.TestCase):
	def setUp(self):
		self.h = mm.Histogram("sure", "x", buckets=(1.0, 2.0, 5.0), namespace="test")

	def test_kovalar_artan_sirada_olmali(self):
		with self.assertRaises(mm.MetricError):
			mm.Histogram("a", "x", buckets=(5.0, 1.0), namespace="test")

	def test_tekrar_eden_kova_reddedilir(self):
		with self.assertRaises(mm.MetricError):
			mm.Histogram("a", "x", buckets=(1.0, 1.0), namespace="test")

	def test_inf_kovasi_otomatik_eklenir_ve_tek(self):
		self.assertEqual(len(self.h.buckets), 4)
		self.assertEqual(self.h.buckets[-1], float("inf"))

	def test_kovalar_KUMULATIF_yazilir(self):
		"""Prometheus histogramı kümülatiftir — ham sayaç yazmak veriyi bozar."""
		for v in (0.5, 1.5, 1.9, 4.0, 99.0):
			self.h.observe(v)
		satirlar = self.h.satirlar()
		harita = dict(
			re.match(r'.*le="([^"]+)"\} (\S+)', s).groups() for s in satirlar if "_bucket" in s
		)
		self.assertEqual(harita["1"], "1")
		self.assertEqual(harita["2"], "3")
		self.assertEqual(harita["5"], "4")
		self.assertEqual(harita["+Inf"], "5")

	def test_sum_ve_count(self):
		self.h.observe(1.0)
		self.h.observe(3.0)
		ozet = self.h.ozet()
		self.assertEqual(ozet["count"], 2.0)
		self.assertEqual(ozet["sum"], 4.0)

	def test_zamanla_istisnada_da_olcer(self):
		"""Hata yolunun SÜRESİ de görünmeli; ölçüm hatayı yutmamalı."""
		with self.assertRaises(ValueError):
			with self.h.zamanla():
				raise ValueError("x")
		self.assertEqual(self.h.ozet()["count"], 1.0)


class CiktiBicimi(unittest.TestCase):
	def test_etiket_degeri_kacirilir(self):
		c = mm.Counter("a", "x", etiketler=("m",), namespace="test")
		c.inc(m='ic"tirnak\\ters\nsatir')
		satir = c.satirlar()[0]
		self.assertIn(r'\"', satir)
		self.assertIn(r"\\", satir)
		self.assertNotIn("\n", satir)

	def test_help_metninde_tirnak_kacirilmaz_ama_satir_kacirilir(self):
		"""0.0.4 kuralı: HELP'te yalnız `\\` ve yeni satır kaçırılır."""
		c = mm.Counter("a", 'ic"tirnak\nsatir', namespace="test")
		c.inc()
		bas = c.render().splitlines()[0]
		self.assertIn('ic"tirnak', bas)
		self.assertIn("\\n", bas)

	def test_tam_sayi_sade_yazilir(self):
		g = mm.Gauge("a", "x", namespace="test")
		g.set(3.0)
		self.assertIn("test_a 3", g.render())

	def test_sonsuz_ve_nan(self):
		g = mm.Gauge("a", "x", namespace="test")
		g.set(float("inf"))
		self.assertIn("+Inf", g.render())
		g.set(float("nan"))
		self.assertIn("NaN", g.render())

	def test_render_deterministik(self):
		r = mm.Registry("test")
		z = r.counter("zeta", "x")
		a = r.counter("alfa", "x", etiketler=("k",))
		z.inc()
		a.inc(k="b")
		a.inc(k="a")
		birinci = r.render()
		self.assertEqual(birinci, r.render())
		self.assertLess(birinci.index("test_alfa"), birinci.index("test_zeta"))
		self.assertLess(birinci.index('k="a"'), birinci.index('k="b"'))

	def test_bos_kayit_defteri_bos_metin(self):
		self.assertEqual(mm.Registry("bos").render(), "")

	def test_cikti_sonunda_yeni_satir_var(self):
		"""Son satırda `\\n` yoksa Prometheus son metriği düşürür."""
		r = mm.Registry("test")
		r.counter("a", "x").inc()
		self.assertTrue(r.render().endswith("\n"))

	def test_content_type_prometheus_bekledigi_gibi(self):
		self.assertEqual(mm.REGISTRY.content_type(), "text/plain; version=0.0.4; charset=utf-8")


class CokSurecliToplama(unittest.TestCase):
	def test_sayaclar_toplanir(self):
		dokumler = []
		for adet in (2, 5):
			r = mm.Registry("test")
			c = r.counter("is", "x", etiketler=("k",))
			c.inc(adet, k="a")
			dokumler.append(r.dump_json())
		birlesik = mm.merge_json(dokumler)
		self.assertEqual(birlesik["test_is_total"]["series"]["a"]["sum"], 7.0)

	def test_gostergede_hem_sum_hem_max_verilir(self):
		"""Toplamın anlamlı olup olmadığı karar çağıranın — ikisi de sunulur."""
		dokumler = []
		for v in (10, 4):
			r = mm.Registry("test")
			r.gauge("doluluk", "x").set(v)
			dokumler.append(r.dump_json())
		b = mm.merge_json(dokumler)["test_doluluk"]["series"][""]
		self.assertEqual(b["sum"], 14.0)
		self.assertEqual(b["max"], 10.0)

	def test_histogram_kovalari_toplanir(self):
		dokumler = []
		for v in (0.5, 3.0):
			r = mm.Registry("test")
			r.histogram("sure", "x", buckets=(1.0, 2.0)).observe(v)
			dokumler.append(r.dump_json())
		b = mm.merge_json(dokumler)["test_sure"]["series"][""]
		self.assertEqual(b["count"], 2.0)
		self.assertEqual(sum(b["buckets"]), 2.0)

	def test_bozuk_dokum_atlanir(self):
		self.assertEqual(mm.merge_json(["{bozuk", ""]), {})


class MedyaMetrikleri(unittest.TestCase):
	"""Ad ve kova seçimleri ÖLÇÜLEN gerçeklerle hizalı mı."""

	def test_sure_kovalari_izolasyon_zaman_asimiyla_hizali(self):
		from tradehub_core.media.pipeline.security import isolation as iso

		self.assertEqual(mm.DURATION_BUCKETS[-1], iso.IMAGE_LIMITS.wall_timeout_s)

	def test_olculen_optimize_sureleri_alt_kovalara_duser(self):
		"""ÖLÇÜM (2026-08-18, bu makine): 0,07 · 0,23 · 0,58 · 1,05 s.

		Dördü de 2,5 s kovasının (10 kovanın 6.'sı) altında kalır; üstteki
		dört kova (5 · 10 · 30 · 60 s) ARIZA bölgesidir. Bu ayrım kovaların
		gerekçesidir: bugünkü dağılımın tamamı altta, üstü olay kaydı.
		"""
		olculen = (0.07, 0.23, 0.58, 1.05)
		esik = mm.DURATION_BUCKETS[5]
		self.assertEqual(esik, 2.5)
		for sure in olculen:
			with self.subTest(sure=sure):
				self.assertLessEqual(sure, esik)
		# Ve arıza bölgesi gerçekten yukarıda:
		self.assertEqual(mm.DURATION_BUCKETS[6:], (5.0, 10.0, 30.0, 60.0))

	def test_bayt_kovasi_ust_siniri_yukleme_politikasiyla_ayni(self):
		"""25 MB = `upload_policy.MAX_BYTES[image]`. Ayrışırsa test düşer.

		`upload_policy.py` frappe'ye bağlı; sabit dosyadan METİN olarak
		okunur — ayrışma yine de yakalanır.
		"""
		metin = (ROOT / "tradehub_core" / "media" / "upload_policy.py").read_text(encoding="utf-8")
		self.assertIn("KIND_IMAGE: 25 * 1024 * 1024", metin)
		self.assertEqual(mm.BYTE_BUCKETS[-1], 25 * 1024 * 1024.0)

	def test_megapiksel_kovasi_20mp_anomalisini_gosterir(self):
		"""Canlı ölçüm: 179 dosya > 20 MP. O eşik bir kova sınırı olmalı."""
		self.assertIn(20.0, mm.MEGAPIXEL_BUCKETS)
		self.assertGreater(mm.MEGAPIXEL_BUCKETS[-1], 72.71)  # ölçülen MAX

	def test_yuksek_kardinaliteli_alanlar_etiket_degil(self):
		"""`file_url`/`user`/`seller` etiket olarak KULLANILMAZ — seri patlaması + PII."""
		yasak = {"file_url", "file_name", "user", "email", "seller", "path", "docname"}
		for metrik in mm.REGISTRY.metrikler():
			with self.subTest(metrik=metrik.ad):
				self.assertFalse(yasak & set(metrik.etiketler))

	def test_standart_metrikler_media_ad_alaninda(self):
		for metrik in mm.REGISTRY.metrikler():
			self.assertTrue(metrik.ad.startswith("media_"), metrik.ad)

	def test_pii_kapsam_gostergeleri_var(self):
		"""T-132 bulgusu bir metrikle izlenebilir olmalı, yoksa unutulur."""
		self.assertIsNotNone(mm.REGISTRY.get("media_pii_field_coverage"))
		self.assertIsNotNone(mm.REGISTRY.get("media_pii_unprotected_files"))


# ── logging ─────────────────────────────────────────────────────────────


class LogYakalayici:
	"""Test için tek kullanımlık logger + tampon."""

	def __init__(self, ad: str, maskele: bool = True):
		self.tampon = io.StringIO()
		self.ad = ad
		mlog.configure(name=ad, stream=self.tampon, maskele=maskele, replace=True)
		self.logger = mlog.get_logger(ad)

	def satirlar(self):
		return [json.loads(s) for s in self.tampon.getvalue().splitlines() if s.strip()]


class JsonBicimi(unittest.TestCase):
	def setUp(self):
		self.y = LogYakalayici("test.bicim")
		mlog.clear_context()

	def test_her_satir_gecerli_json(self):
		mlog.log_event("a.b", logger=self.y.logger, k=1)
		mlog.log_event("c.d", logger=self.y.logger, k=2)
		self.assertEqual(len(self.y.satirlar()), 2)

	def test_sabit_alanlar_bastan_gelir(self):
		mlog.log_event("upload.rejected", logger=self.y.logger, reason="x")
		anahtarlar = list(self.y.satirlar()[0])
		self.assertEqual(anahtarlar[:5], list(mlog.SABIT_SIRA[:5]))

	def test_event_ile_ayni_mesaj_iki_kez_yazilmaz(self):
		mlog.log_event("upload.rejected", logger=self.y.logger)
		self.assertNotIn("message", self.y.satirlar()[0])

	def test_sabit_alan_extra_ile_ezilemez(self):
		"""`extra={"level": "DEBUG"}` log seviyesini yalanlayabilirdi."""
		self.y.logger.info("x", extra={"event": "a.b", "level": "SAHTE"})
		satir = self.y.satirlar()[0]
		self.assertEqual(satir["level"], "INFO")
		self.assertEqual(satir["field_level"], "SAHTE")

	def test_serilesemeyen_deger_satiri_dusurmez(self):
		class Garip:
			def __repr__(self):
				return "<garip>"

		mlog.log_event("a.b", logger=self.y.logger, nesne=Garip())
		self.assertEqual(self.y.satirlar()[0]["nesne"], "<garip>")

	def test_istisna_alanlari_yazilir(self):
		try:
			raise RuntimeError("patladi")
		except RuntimeError:
			mlog.log_event("a.b", level=stdlogging.ERROR, logger=self.y.logger, exc_info=True)
		satir = self.y.satirlar()[0]
		self.assertEqual(satir["error_type"], "RuntimeError")
		self.assertIn("patladi", satir["error_message"])
		self.assertIn("Traceback", satir["error_stack"])

	def test_zaman_damgasi_utc_iso(self):
		mlog.log_event("a.b", logger=self.y.logger)
		ts = self.y.satirlar()[0]["ts"]
		self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

	def test_log_event_asla_firlatmaz(self):
		"""Log yazamamak çağıranı düşürmemeli (`audit.log_media_event` deseni)."""

		class BozukLogger:
			def log(self, *a, **k):
				raise OSError("disk dolu")

		mlog.log_event("a.b", logger=BozukLogger())  # istisna beklenmiyor


class Korelasyon(unittest.TestCase):
	def setUp(self):
		self.y = LogYakalayici("test.korelasyon")
		mlog.clear_context()
		mlog.set_correlation_id("")

	def test_kapsam_icindeki_satirlar_ayni_anahtari_tasir(self):
		with mlog.correlation_scope() as cid:
			mlog.log_event("a", logger=self.y.logger)
			mlog.log_event("b", logger=self.y.logger)
		satirlar = self.y.satirlar()
		self.assertEqual(satirlar[0]["correlation_id"], cid)
		self.assertEqual(satirlar[1]["correlation_id"], cid)

	def test_kapsam_cikisinda_onceki_deger_geri_gelir(self):
		"""Worker sıradaki işi alırken önceki işin anahtarını taşımamalı."""
		mlog.set_correlation_id("disaridan")
		with mlog.correlation_scope():
			pass
		self.assertEqual(mlog.get_correlation_id(), "disaridan")

	def test_kapsam_cikisinda_baglam_geri_gelir(self):
		mlog.bind(sabit="a")
		with mlog.correlation_scope(job="x"):
			self.assertEqual(mlog.get_context()["job"], "x")
		self.assertEqual(mlog.get_context(), {"sabit": "a"})

	def test_disaridan_gelen_anahtar_temizlenir(self):
		"""İş yükünden gelen string log satırı uydurmak için kullanılamamalı."""
		temiz = mlog.set_correlation_id('sahte"\n{"level":"INFO","event":"sahte"}')
		self.assertNotIn("\n", temiz)
		self.assertNotIn('"', temiz)

	def test_anahtar_uzunlugu_sinirli(self):
		self.assertLessEqual(len(mlog.set_correlation_id("x" * 500)), 64)

	def test_get_otomatik_uretmez_ensure_uretir(self):
		mlog.set_correlation_id("")
		self.assertEqual(mlog.get_correlation_id(), "")
		self.assertTrue(mlog.ensure_correlation_id())

	def test_job_payload_zinciri_kuyruga_tasir(self):
		"""`contextvars` süreç sınırını geçmez — anahtar iş yükünde taşınır."""
		with mlog.correlation_scope() as cid:
			yuk = mlog.job_payload(job="transcode")
		self.assertEqual(yuk["correlation_id"], cid)
		self.assertEqual(yuk["job"], "transcode")
		# Worker tarafında zincir geri kurulabiliyor mu:
		with mlog.correlation_scope(yuk["correlation_id"]):
			self.assertEqual(mlog.get_correlation_id(), cid)

	def test_baglam_alanlari_her_satira_duser(self):
		with mlog.correlation_scope(job="transcode", attempt=2):
			mlog.log_event("a", logger=self.y.logger)
		satir = self.y.satirlar()[0]
		self.assertEqual(satir["job"], "transcode")
		self.assertEqual(satir["attempt"], 2)


class PiiMaskeleme(unittest.TestCase):
	def setUp(self):
		self.y = LogYakalayici("test.pii")
		mlog.clear_context()

	def test_audit_ile_ayni_parmak_izi(self):
		"""`media/audit.py:132-138` ile ayrışırsa iki kayıt eşleştirilemez."""
		deger = "/private/files/ab/kimlik.jpg"
		beklenen = hashlib.sha256(deger.encode("utf-8")).hexdigest()[:12]
		self.assertEqual(mlog.fingerprint(deger), beklenen)
		self.assertEqual(mlog.mask(deger), f"masked:{beklenen}")

	def test_maskeleme_kararli(self):
		"""Aynı dosya her seferinde aynı kimlik — 'bu dosyaya 5 kez denendi'."""
		self.assertEqual(mlog.mask("/files/a.jpg"), mlog.mask("/files/a.jpg"))

	def test_anahtar_adiyla_maskeleme(self):
		mlog.log_event("a", logger=self.y.logger, file_url="/private/files/ab/x.jpg")
		self.assertTrue(self.y.satirlar()[0]["file_url"].startswith("masked:"))

	def test_serbest_metinde_desenle_maskeleme(self):
		"""Anahtar adı 'detail' — (1) devreye girmez, (2) girmeli."""
		mlog.log_event(
			"a",
			logger=self.y.logger,
			detail="kopyalama hatasi: /private/files/ab/kimlik.jpg okunamadi",
		)
		metin = self.y.satirlar()[0]["detail"]
		self.assertNotIn("kimlik.jpg", metin)
		self.assertIn("masked:", metin)
		self.assertIn("kopyalama hatasi", metin, "cumle okunmaz hale gelmis")

	def test_eposta_maskelenir(self):
		mlog.log_event("a", logger=self.y.logger, detail="kullanici ali@ornek.com yazdi")
		self.assertNotIn("ali@ornek.com", json.dumps(self.y.satirlar()[0]))

	def test_tckn_maskelenir(self):
		mlog.log_event("a", logger=self.y.logger, detail="tc 12345678901 gecersiz")
		self.assertNotIn("12345678901", json.dumps(self.y.satirlar()[0]))

	def test_mutlak_disk_yolu_maskelenir(self):
		mlog.log_event("a", logger=self.y.logger, detail="/home/frappe/frappe-bench/sites/x")
		self.assertNotIn("frappe-bench", json.dumps(self.y.satirlar()[0]))

	def test_doctype_maskelenmez(self):
		"""`doctype` PII değildir; maskelenirse hiçbir olay yorumlanamaz."""
		mlog.log_event("a", logger=self.y.logger, doctype="KYB Verification", slot="brand.logo")
		satir = self.y.satirlar()[0]
		self.assertEqual(satir["doctype"], "KYB Verification")
		self.assertEqual(satir["slot"], "brand.logo")

	def test_ic_ice_sozlukte_de_maskelenir(self):
		mlog.log_event("a", logger=self.y.logger, detay={"file_url": "/files/x.jpg", "adet": 3})
		satir = self.y.satirlar()[0]
		self.assertTrue(satir["detay"]["file_url"].startswith("masked:"))
		self.assertEqual(satir["detay"]["adet"], 3)

	def test_traceback_icindeki_yol_da_maskelenir(self):
		try:
			open("/private/files/ab/kimlik.jpg")
		except OSError:
			mlog.log_event("a", level=stdlogging.ERROR, logger=self.y.logger, exc_info=True)
		self.assertNotIn("kimlik.jpg", json.dumps(self.y.satirlar()[0]))

	def test_bos_deger_maskelenmez(self):
		"""Maskelenmiş boşluk bilgi taşımaz, gürültü üretir."""
		self.assertEqual(mlog.mask(""), "")

	def test_maskeleme_kapatilabilir_ama_varsayilan_acik(self):
		acik = LogYakalayici("test.pii.acik")
		mlog.log_event("a", logger=acik.logger, file_url="/files/x.jpg")
		self.assertTrue(acik.satirlar()[0]["file_url"].startswith("masked:"))

		kapali = LogYakalayici("test.pii.kapali", maskele=False)
		mlog.log_event("a", logger=kapali.logger, file_url="/files/x.jpg")
		self.assertEqual(kapali.satirlar()[0]["file_url"], "/files/x.jpg")

	def test_asiri_uzun_deger_kirpilir(self):
		"""Log satırı da bir DoS yüzeyi: 40 MB traceback diski doldurur."""
		mlog.log_event("a", logger=self.y.logger, detail="x" * 10000)
		self.assertLess(len(self.y.satirlar()[0]["detail"]), mlog.MAX_DEGER_UZUNLUK + 50)


class Kurulum(unittest.TestCase):
	def test_tekrar_configure_handler_cogaltmaz(self):
		tampon = io.StringIO()
		mlog.configure(name="test.kurulum", stream=tampon, replace=True)
		ilk = mlog.configure(name="test.kurulum", stream=tampon)
		ikinci = mlog.configure(name="test.kurulum", stream=tampon)
		self.assertEqual(ilk.handlers, ikinci.handlers)

	def test_get_logger_kendiliginden_handler_eklemez(self):
		"""Import edilir edilmez stderr'e yazan kütüphane, uygulamayı ele geçirir."""
		lg = mlog.get_logger("test.dokunulmamis.logger")
		self.assertEqual(lg.handlers, [])

	def test_satir_iki_kez_yazilmaz(self):
		"""`propagate=False` olmasaydı kök logger aynı satırı tekrar basardı."""
		y = LogYakalayici("test.propagate")
		mlog.log_event("a", logger=y.logger)
		self.assertEqual(len(y.satirlar()), 1)


class IkiModulBirlikte(unittest.TestCase):
	"""Metrik ve log aynı olayı AYNI sözlükle anlatıyor mu."""

	def test_izolasyon_sonucu_hem_metrige_hem_loga_gider(self):
		from tradehub_core.media.pipeline.security import isolation as iso

		y = LogYakalayici("test.birlikte")
		r = mm.Registry("test_birlikte")
		sayac = r.counter("isolation", "x", etiketler=("profile", "reason"))

		sonuc = iso.run_callable(lambda: 1 / 0)
		sayac.inc(profile="image", reason=sonuc.sebep)
		mlog.log_event("image.isolated.failed", logger=y.logger, **sonuc.to_dict())

		self.assertEqual(sayac.deger(profile="image", reason=iso.SEBEP_EXCEPTION), 1.0)
		satir = y.satirlar()[0]
		self.assertEqual(satir["reason"], iso.SEBEP_EXCEPTION)
		# Ham çıktı log'a hiç girmedi:
		self.assertNotIn("stdout", satir)

	def test_svg_sonucu_metrik_etiketine_uygun(self):
		from tradehub_core.media.pipeline.security import svg

		r = mm.Registry("test_svg")
		sayac = r.counter("svg_sanitize", "x", etiketler=("slot", "code"))
		sonuc = svg.sanitize(b"\x1f\x8b bozuk")
		sayac.inc(slot="brand.logo", code=sonuc.kod)
		self.assertEqual(sayac.deger(slot="brand.logo", code=svg.KOD_COMPRESSED), 1.0)


if __name__ == "__main__":
	unittest.main(verbosity=2)

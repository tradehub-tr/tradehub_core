"""KD-13 — Duman (smoke) ve uçtan uca (E2E) testleri.

DUMAN: hızlı, her koşumda çalışacak, "sistem ayakta mı" sorusunu cevaplayan
küçük bir küme. Bir modülün import edilememesi, bir politikanın bozulması ya
da bir uç noktanın kaybolması burada anında görünür.

E2E: gerçek Frappe `File` kaydı üzerinden yükleme → künye → politika →
normalleştirme → SEO alanları → denetim zincirinin tamamını tek akışta
koşturur. Katmanlar tek tek yeşilken zincirin kopması bu testte görünür.

Süre bütçesi: duman kümesi < 2 sn, E2E < 15 sn.
"""

from __future__ import annotations

import importlib
import time
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.tests.kapsamli import _yardim as y


#: ORTAM BAĞIMSIZLIĞI — File açan her fixture tarama kancasını nötrler.
#: Gerekçe (ölçülmüş, TUR-125): ClamAV kurulu bir makinede `after_insert`
#: kancası dosyayı `pending` damgalayıp bekletmeye alıyor; fixture'lar
#: dosyanın `public/files/`'da durduğunu varsaydığı için kırılıyor. Kurulum
#: bir kerede 6 testi düşürmüştü. Kural: bir bağımlılığın YOKLUĞU üstüne
#: test yazma.
def _av_kancasini_notrle(testcase):
	from unittest import mock as _mock

	for hedef in (
		"tradehub_core.media.av.enqueue_scan",
		"tradehub_core.media.av.maybe_scan_on_insert",
	):
		yama = _mock.patch(hedef, return_value=None)
		yama.start()
		testcase.addCleanup(yama.stop)


# ══════════════════════════════════════════════════════════════════════
# 1. Duman — import ve kayıt bütünlüğü
# ══════════════════════════════════════════════════════════════════════


class TestDumanImport(unittest.TestCase):
	"""Medya paketinin her ana modülü import edilebiliyor mu.

	Bir modülün import zamanında patlaması (eksik bağımlılık, sözdizimi,
	döngüsel import) TÜM medya uçlarını düşürür — 2026-08-20 alpha 417
	arızası tam olarak buydu. Bu yüzden en ucuz ve en değerli duman testi.
	"""

	MODULLER = (
		"tradehub_core.media.pipeline.core.probe",
		"tradehub_core.media.pipeline.image.probe",
		"tradehub_core.media.pipeline.image.normalize",
		"tradehub_core.media.pipeline.image.classify",
		"tradehub_core.media.pipeline.image.render",
		"tradehub_core.media.pipeline.image.lqip",
		"tradehub_core.media.pipeline.video.probe",
		"tradehub_core.media.pipeline.video.decision",
		"tradehub_core.media.pipeline.video.transcode",
		"tradehub_core.media.pipeline.video.poster",
		"tradehub_core.media.pipeline.video.hls",
		"tradehub_core.media.pipeline.policy.engine",
		"tradehub_core.media.pipeline.security.svg",
		"tradehub_core.media.pipeline.security.isolation",
		"tradehub_core.media.pipeline.storage",
		"tradehub_core.media.pipeline.storage.local",
		"tradehub_core.media.pipeline.storage.s3",
		"tradehub_core.media.pipeline.storage.mirror",
		"tradehub_core.media.pipeline.storage.tiered",
		"tradehub_core.media.pipeline.storage.retention",
		"tradehub_core.media.pipeline.delivery.manifest",
		"tradehub_core.media.pipeline.delivery.picture",
		"tradehub_core.media.pipeline.delivery.sizes",
		"tradehub_core.media.pipeline.delivery.signed",
		"tradehub_core.media.pipeline.delivery.rum",
		"tradehub_core.media.pipeline.api.envelope",
		"tradehub_core.media.pipeline.api.upload",
		"tradehub_core.media.pipeline.api.crop",
		"tradehub_core.media.pipeline.api.delivery",
		"tradehub_core.media.pipeline.api.admin",
		"tradehub_core.media.pipeline.api.spec",
		"tradehub_core.media.pipeline.migration.backfill",
		"tradehub_core.media.pipeline.observability.metrics",
		"tradehub_core.media.upload_policy",
		"tradehub_core.media.chunked",
		"tradehub_core.media.seo",
		"tradehub_core.media.seo_audit",
		"tradehub_core.media.seo_generate",
		"tradehub_core.media.av",
		"tradehub_core.media.transcode",
		"tradehub_core.media.inventory",
		"tradehub_core.media.browse",
		"tradehub_core.media.usage",
		"tradehub_core.media.refs",
		"tradehub_core.media.trash",
		"tradehub_core.media.backup",
		"tradehub_core.media.retro_rename",
		"tradehub_core.media.categories",
		"tradehub_core.media.path_safety",
		"tradehub_core.media.pipeline_bridge",
	)

	def test_duman_tum_moduller_import_edilebiliyor(self):
		basarisiz = []
		for mod in self.MODULLER:
			try:
				importlib.import_module(mod)
			except Exception as exc:  # noqa: BLE001 — duman testi
				basarisiz.append(f"{mod}: {type(exc).__name__}: {exc}")
		self.assertEqual(basarisiz, [], "\n".join(basarisiz))

	def test_duman_import_suresi_makul(self):
		"""Toplam import bütçesi — soğuk istek gecikmesinin tabanı."""
		basla = time.monotonic()
		for mod in self.MODULLER:
			importlib.import_module(mod)
		sure = time.monotonic() - basla
		self.assertLess(sure, 10.0, f"import {sure:.2f} sn sürdü")


class TestDumanPolitika(unittest.TestCase):
	def test_duman_dokuz_slot_yuklenip_dogrulaniyor(self):
		from tradehub_core.media.pipeline.policy import engine as pe

		r = pe.PolicyRegistry().load()
		self.assertGreaterEqual(len(r), 9)
		for slot in r.keys():
			with self.subTest(slot=slot):
				pol = r.get(slot)
				self.assertTrue(pol.get("accept"), f"{slot}: accept bloğu boş")
				self.assertTrue(pol.get("schema_version"), f"{slot}: sürüm yok")

	def test_duman_video_karar_tablosu_yukleniyor(self):
		from tradehub_core.media.pipeline.video import decision as kr

		t = kr.default_table()
		self.assertGreaterEqual(len(t.rules), 10)
		self.assertTrue(t.targets)

	def test_duman_her_slot_icin_karar_uretilebiliyor(self):
		from tradehub_core.media.pipeline.core.probe import MediaProbe
		from tradehub_core.media.pipeline.policy import engine as pe

		motor = pe.PolicyEngine()
		kunye = MediaProbe(
			filename="a.jpg", extension=".jpg", byte_size=1000, kind="image",
			detected="jpeg", mime="image/jpeg", fmt="JPEG", width=2000, height=2000,
			readable=True, loadable=True, extension_matches_content=True,
			existing_count=0, scan_clean=True,
		)
		for slot in pe.PolicyRegistry().load().keys():
			with self.subTest(slot=slot):
				k = motor.evaluate(slot, kunye, "seller")
				self.assertIsInstance(k.allow, bool)


class TestDumanCekirdekAkis(unittest.TestCase):
	"""Görsel boru hattının ana zinciri tek bir dosyada uçtan uca."""

	def test_duman_gorsel_zinciri(self):
		from tradehub_core.media.pipeline.core import probe as core_probe
		from tradehub_core.media.pipeline.image import normalize as nrm
		from tradehub_core.media.pipeline.image import probe as kapi
		from tradehub_core.media.pipeline.policy import engine as pe

		icerik = y.jpeg(2000, 2000, dpi=(300, 300))

		# 1) kapı
		kunye = kapi.probe_header(icerik, filename="kirmizi-koltuk.jpg")
		self.assertTrue(kunye.ok, kunye.codes)

		# 2) tam künye
		tam = core_probe.probe_bytes(icerik, filename="kirmizi-koltuk.jpg", existing_count=0, scan_clean=True)
		self.assertEqual(tam.detected, "jpeg")

		# 3) politika
		karar = pe.PolicyEngine().evaluate("product.image", tam, "seller")
		self.assertTrue(karar.allow, karar.codes)
		self.assertTrue(karar.normalized_targets)

		# 4) normalleştirme
		sonuc = nrm.normalize(
			icerik, nrm.NormalizeSpec(fmt="webp", max_long_edge=1600), filename="kirmizi-koltuk.jpg"
		)
		self.assertTrue(sonuc.ok, sonuc.reason)
		self.assertEqual(sonuc.fmt, "WEBP")
		self.assertEqual(max(sonuc.width, sonuc.height), 1600)
		self.assertIn("metadata:gps_removed", sonuc.notes)

	def test_duman_zararli_dosya_zincirin_ILK_adiminda_durur(self):
		from tradehub_core.media.pipeline.image import probe as kapi

		for zararli in (y.svg(zararli=True), y.calistirilabilir(), y.data_uri_metni()):
			with self.subTest(n=len(zararli)):
				self.assertFalse(kapi.probe_header(zararli, filename="urun.jpg").ok)

	def test_duman_video_zinciri(self):
		from tradehub_core.media.pipeline.video import decision as kr
		from tradehub_core.media.pipeline.video import transcode as tc
		from tradehub_core.media.pipeline.video.probe import VideoFacts

		f = VideoFacts(
			measured=True, has_video=True, width=1920, height=1080, duration_s=20.0,
			fps=30.0, video_codec="h264", pix_fmt="yuv420p", video_bitrate_bps=6_000_000,
			format_bitrate_bps=6_200_000, container_family="mp4", nb_streams=2,
			has_audio=True, audio_codec="aac", audio_bitrate_bps=128_000,
		)
		karar = kr.decide(f)
		self.assertEqual(karar.action, kr.ACTION_TRANSCODE)
		cmd = tc.build_transcode_cmd("/tmp/a.mp4", "/tmp/b.mp4", tc.H264Spec(), f, nice=False)
		self.assertIn("-maxrate", cmd)
		self.assertIn("+faststart", cmd)


# ══════════════════════════════════════════════════════════════════════
# 2. E2E — gerçek Frappe kaydı üzerinden
# ══════════════════════════════════════════════════════════════════════


class TestE2EDosyaYasamDongusu(FrappeTestCase):
	"""Gerçek `File` kaydı: yükleme → SEO alanı → denetim → silme."""

	def setUp(self):
		super().setUp()
		_av_kancasini_notrle(self)

	def _dosya(self, ad: str, icerik: bytes, *, private: int = 0):
		doc = frappe.get_doc(
			{"doctype": "File", "file_name": ad, "is_private": private, "content": icerik}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		return doc

	def test_e2e_gorsel_yukleme_seo_denetim(self):
		from tradehub_core.media import seo, seo_audit

		doc = self._dosya("kd-e2e-kirmizi-koltuk.jpg", y.jpeg(1200, 1200))
		url = doc.file_url

		# 1) SEO alanları başta boş → denetim eksikleri buluyor
		once = seo_audit.audit_file(url, deep=False)
		self.assertIn("missing_alt", {b["code"] for b in once["findings"]})
		ilk_skor = once["score"]["overall"]

		# 2) alanlar dolduruluyor
		seo.set_asset_fields(
			url,
			{
				"alt": "Kırmızı kadife üç kişilik koltuk",
				"title": "Kırmızı koltuk",
				"caption": "Salon takımı ürün görseli",
			},
		)

		# 3) denetim düzelmeyi GÖRÜYOR
		sonra = seo_audit.audit_file(url, deep=False)
		kodlar = {b["code"] for b in sonra["findings"]}
		self.assertNotIn("missing_alt", kodlar)
		self.assertGreater(
			sonra["score"]["overall"], ilk_skor,
			"alt/başlık/altyazı eklendi ama skor artmadı — zincir kopuk",
		)

	def test_e2e_zararli_dosya_File_kaydinda_reddedilir(self):
		"""`hooks.py` `File.before_insert` → `reject_unsafe_files` zinciri."""
		with self.assertRaises(Exception):
			frappe.get_doc(
				{
					"doctype": "File",
					"file_name": "kd-e2e-zararli.jpg",
					"is_private": 0,
					"content": b"<script>alert(1)</script>",
				}
			).insert(ignore_permissions=True)

	def test_e2e_parcali_yukleme_tam_akis(self):
		from tradehub_core.media import chunked

		magaza = "KD-E2E-MAGAZA"
		icerik = y.jpeg(900, 900)
		oturum = chunked.begin("kd-e2e-parcali.jpg", len(icerik), magaza)
		self.addCleanup(lambda: chunked.cleanup_session(oturum["upload_id"], magaza))

		for i in range(oturum["chunk_count"]):
			dilim = icerik[i * chunked.CHUNK_BYTES : (i + 1) * chunked.CHUNK_BYTES]
			durum = chunked.put_chunk(oturum["upload_id"], i, dilim, magaza)
		self.assertTrue(durum["complete"])
		self.assertEqual(chunked.finish(oturum["upload_id"], magaza), icerik)

	def test_e2e_ozel_dosya_public_dizine_yazilmaz(self):
		"""Gizlilik: `is_private=1` dosya public klasörde OLMAMALI."""
		doc = self._dosya("kd-e2e-ozel.jpg", y.jpeg(64, 64), private=1)
		self.assertTrue(doc.is_private)
		self.assertNotIn("/files/", doc.file_url.replace("/private/files/", "/private/"))

	def test_e2e_ayni_icerik_iki_kez_yuklenebilir(self):
		"""Dedup kayıt açmayı ENGELLEMEMELİ (farklı bağlamlar aynı görseli
		kullanabilir); yalnız depolama tekilleşir."""
		icerik = y.jpeg(200, 200)
		a = self._dosya("kd-e2e-1.jpg", icerik)
		b = self._dosya("kd-e2e-2.jpg", icerik)
		self.assertNotEqual(a.name, b.name)


class TestE2EPerformansButcesi(FrappeTestCase):
	"""Sözleşmede yazılı zaman bütçeleri — regresyon fark edilsin."""

	def test_perf_kapi_karari_50ms_altinda(self):
		from tradehub_core.media.pipeline.image import probe as kapi

		icerik = y.jpeg(3000, 3000, quality=95)
		basla = time.monotonic()
		for _ in range(5):
			kapi.probe_header(icerik, filename="a.jpg")
		sure = (time.monotonic() - basla) / 5
		self.assertLess(sure, 0.05, f"kapı kararı {sure * 1000:.1f} ms (hedef <50 ms)")

	def test_perf_politika_karari_5ms_altinda(self):
		from tradehub_core.media.pipeline.core.probe import MediaProbe
		from tradehub_core.media.pipeline.policy import engine as pe

		motor = pe.PolicyEngine()
		kunye = MediaProbe(
			filename="a.jpg", extension=".jpg", byte_size=1000, kind="image",
			detected="jpeg", mime="image/jpeg", fmt="JPEG", width=2000, height=2000,
			readable=True, loadable=True, extension_matches_content=True,
			existing_count=0, scan_clean=True,
		)
		basla = time.monotonic()
		for _ in range(50):
			motor.evaluate("product.image", kunye, "seller")
		sure = (time.monotonic() - basla) / 50
		self.assertLess(sure, 0.005, f"politika kararı {sure * 1000:.2f} ms (hedef <5 ms)")

	def test_perf_svg_sanitize_10ms_altinda(self):
		from tradehub_core.media.pipeline.security import svg as sv

		icerik = (
			'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
			+ '<path d="M0 0h24v24H0z"/>' * 20
			+ "</svg>"
		).encode()
		basla = time.monotonic()
		for _ in range(20):
			sv.sanitize(icerik)
		sure = (time.monotonic() - basla) / 20
		self.assertLess(sure, 0.01, f"sanitize {sure * 1000:.2f} ms (hedef <10 ms)")


if __name__ == "__main__":
	unittest.main()

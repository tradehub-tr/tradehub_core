# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""W7 — video çıktılarının kalıcılaşması + servis edilmesi (rapor 84).

Rapor 81'in ölçtüğü beş tasarım boşluğunun kapanışını sınar:

  1. Köprü/kuyruk yolu  — `pipeline_bridge._maybe_enqueue_video` + `_run_video_job`
     (görsel yolunun 22 testi AYNEN yeşil kalmalı — bu modül onları tekrarlamaz).
  2. DocType kaydı + kanonik adres — Media Asset(video)/Version/Rendition,
     `/files/media/{asset}/{version_hash}/…` (INV-09).
  3. `vmaf_min` kalite kapısı — `transcode()` içinde; eşik TABLODAN (93), kod
     eşiği değiştirmez.
  4. HLS basamak fayda kapısı — `hls.enforce_rung_benefit_gate`: kaynaktan
     büyük basamak İLAN EDİLMEZ (vacuity: kapısız master 720p'yi taşır).
  5. Manifest video bloğu — `get_manifest(slot=product.video)` `MediaVideo.vue`
     alanlarını döner; görsel manifesti gövdesi DEĞİŞMEDİ.

Koşum (DB'li sınıflar site ister):

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_video_servis
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tradehub_core.media.pipeline.video import hls as H
from tradehub_core.media.pipeline.video import probe as P
from tradehub_core.media.pipeline.video import transcode as T
from tradehub_core.media.pipeline.video.decision import (
	ACTION_REMUX,
	ACTION_TRANSCODE,
	VideoDecision,
	decide,
)

try:  # DB'siz koşumda (yalnız saf sınıflar) frappe importu şart değil.
	import frappe
	from frappe.tests.utils import FrappeTestCase

	from tradehub_core.api import media_manifest
	from tradehub_core.media import pipeline_bridge, pipeline_flags
except Exception:  # pragma: no cover — saf sınıflar yine koşar
	frappe = None
	FrappeTestCase = object  # type: ignore[assignment,misc]

FIXTURE_DIR = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures", "media", "video"
)
SISIRILMIS = os.path.join(FIXTURE_DIR, "video_bloated_720p_8m.mp4")
VERIMLI = os.path.join(FIXTURE_DIR, "video_efficient_720p_750k.mp4")
FFMPEG = T.ffmpeg_available() and P.ffprobe_available()


def _vmaf(puan: float) -> dict:
	return {"measured": True, "metric": "vmaf", "vmaf": puan}


# ══════════════════════════════════════════════════════════════════════════
# 3. vmaf_min kalite kapısı — transcode() içinde
# ══════════════════════════════════════════════════════════════════════════


class VmafEsigi(unittest.TestCase):
	"""Eşik TABLODAN okunur ve bu görevde DEĞİŞTİRİLMEDİ."""

	def test_esik_93_ve_tablodan(self):
		self.assertEqual(T.vmaf_min(), 93.0)


@unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe yok — konteynerde calistir")
class VmafKapisi(unittest.TestCase):
	"""Gerçek transcode + taklit VMAF: kapının dört yüzü.

	VMAF taklit ediliyor çünkü sınanan şey ÖLÇÜM değil KAPI: gerçek ölçüm
	fixture'a bağlı bir sayı verir (şişirilmiş 720p için 96,63 ölçüldü) ve
	eşiğin iki yakasını deterministik sınamaya izin vermez. Gerçek ölçümün
	kendisi rapor 84'te DEV videosuyla ayrıca koşuldu.
	"""

	def setUp(self):
		self.d = tempfile.mkdtemp(prefix="w7-vmaf-")

	def tearDown(self):
		shutil.rmtree(self.d, ignore_errors=True)

	def test_esik_alti_cikti_ATILIR(self):
		"""Rapor 81 §3.4'ün gerçek değeri (89,34) eşiğin altında → ret."""
		dst = os.path.join(self.d, "c.mp4")
		with mock.patch.object(T, "measure_quality", return_value=_vmaf(89.34)) as m:
			r = T.transcode(SISIRILMIS, dst)
		m.assert_called_once()
		self.assertFalse(r.accepted)
		self.assertTrue(r.kept_source)
		self.assertFalse(os.path.exists(dst), "kapiyi gecemeyen cikti DISKTE KALMAMALI")
		self.assertEqual(r.quality["vmaf_gate"], "DUSTU")
		self.assertEqual(r.quality["vmaf_min"], 93.0)
		self.assertTrue(any("kalite kapisi" in n for n in r.notes))

	def test_esik_ustu_cikti_KABUL(self):
		dst = os.path.join(self.d, "c.mp4")
		with mock.patch.object(T, "measure_quality", return_value=_vmaf(96.63)):
			r = T.transcode(SISIRILMIS, dst)
		self.assertTrue(r.accepted)
		self.assertTrue(os.path.exists(dst))
		self.assertEqual(r.quality["vmaf_gate"], "GECTI")

	def test_vmaf_olculemiyorsa_kapi_uygulanmaz_sayi_uydurulmaz(self):
		"""libvmaf'sız imaj davranışı: kabul + açık 'OLCULEMEDI' kaydı."""
		dst = os.path.join(self.d, "c.mp4")
		olcum = {"measured": True, "metric": "ssim", "vmaf": None, "ssim": 0.99,
			"vmaf_note": "VMAF YOK — ffmpeg libvmaf olmadan derlenmis"}
		with mock.patch.object(T, "measure_quality", return_value=olcum):
			r = T.transcode(SISIRILMIS, dst)
		self.assertTrue(r.accepted)
		self.assertIsNone(r.quality["vmaf"])
		self.assertEqual(r.quality["vmaf_gate"], "OLCULEMEDI")
		self.assertTrue(any("OLCULEMEDI" in n for n in r.notes))

	def test_vacuity_kapi_kapatilinca_ayni_cikti_KABUL(self):
		"""Reddi üreten tek şey kapının kendisi — parametre kapatılınca geçer."""
		dst = os.path.join(self.d, "c.mp4")
		with mock.patch.object(T, "measure_quality", return_value=_vmaf(89.34)) as m:
			r = T.transcode(SISIRILMIS, dst, enforce_quality_gate=False)
		m.assert_not_called()
		self.assertTrue(r.accepted)
		self.assertTrue(os.path.exists(dst))

	def test_fayda_kapisindan_dusen_icin_VMAF_OLCULMEZ(self):
		"""Sıra anlamlı: atılacak çıktı için saniyeler süren ölçüm koşulmaz."""
		dst = os.path.join(self.d, "c.mp4")
		with mock.patch.object(T, "measure_quality", return_value=_vmaf(99.0)) as m:
			r = T.transcode(VERIMLI, dst)  # kazanç %4,3 < %10 → fayda kapısı
		m.assert_not_called()
		self.assertFalse(r.accepted)

	def test_kalite_kapisindan_dusen_TRANSCODE_REMUXa_geri_cekilir(self):
		"""B-2 geri çekilmesi kalite kapısı için de çalışır: moov kusuru duran
		kaynakta ret, teslim edilebilir bir dosya bırakmalı."""
		moov_sonda = os.path.join(self.d, "moov_sonda.mp4")
		subprocess.run(["ffmpeg", "-y", "-i", SISIRILMIS, "-c", "copy", moov_sonda],
			capture_output=True, check=True, timeout=120)
		f = P.probe(moov_sonda)
		self.assertTrue(f.moov_at_end, "sentetik kaynagin moov'u sonda olmali")
		karar = VideoDecision(action=ACTION_TRANSCODE, rule_id="__w7__", code="x", reason="y")
		dst = os.path.join(self.d, "c.mp4")
		with mock.patch.object(T, "measure_quality", return_value=_vmaf(89.34)):
			r = T.apply_decision(moov_sonda, dst, karar, facts=f)
		self.assertEqual(r.action, ACTION_REMUX)
		self.assertEqual(r.fallback_from, ACTION_TRANSCODE)
		self.assertTrue(r.accepted)
		self.assertFalse(P.moov_at_end_of(dst))
		self.assertTrue(any("kalite kapisindan" in n for n in r.notes))


# ══════════════════════════════════════════════════════════════════════════
# 4. HLS basamak fayda kapısı — sentetik paket, deterministik bayt
# ══════════════════════════════════════════════════════════════════════════


class HlsBasamakKapisi(unittest.TestCase):
	"""Rapor 81 §4'ün ölçtüğü durum: 720p basamağı kaynaktan %26 büyük."""

	#: Rapor 81 §4'ün gerçek sayıları (9mb.mp4 remux çıktısı + 3 basamak).
	KAYNAK = 9_622_536
	BASAMAKLAR = (("360p", 7_299_637), ("480p", 7_905_561), ("720p", 12_095_893))

	def setUp(self):
		self.d = tempfile.mkdtemp(prefix="w7-hls-")

	def tearDown(self):
		shutil.rmtree(self.d, ignore_errors=True)

	def _paket_kur(self, basamaklar=None) -> H.HlsResult:
		"""Diske gerçek yapılı sahte bir paket yazar (ffmpeg'siz, bayt kontrollü)."""
		basamaklar = basamaklar or self.BASAMAKLAR
		out = os.path.join(self.d, "hls")
		satirlar = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-INDEPENDENT-SEGMENTS"]
		varyantlar = []
		for i, (ad, bayt) in enumerate(basamaklar):
			dizin = os.path.join(out, f"v{ad}")
			os.makedirs(dizin, exist_ok=True)
			with open(os.path.join(dizin, "seg000.ts"), "wb") as f:
				f.write(b"\x00" * max(bayt - 200, 1))
			playlist = os.path.join(dizin, "playlist.m3u8")
			with open(playlist, "w", encoding="utf-8") as f:
				f.write("#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4.0,\nseg000.ts\n#EXT-X-ENDLIST\n")
			satirlar += [
				f"#EXT-X-STREAM-INF:BANDWIDTH={800000 * (i + 1)},RESOLUTION=640x360",
				f"v{ad}/playlist.m3u8",
			]
			varyantlar.append(
				H.HlsVariantResult(
					name=ad, width=640, height=360, bitrate_kbps=800 * (i + 1),
					playlist_path=playlist, segment_count=1, bytes_total=bayt,
				)
			)
		master = os.path.join(out, H.MASTER_PLAYLIST_NAME)
		with open(master, "w", encoding="utf-8") as f:
			f.write("\n".join(satirlar) + "\n")
		return H.HlsResult(master_path=master, out_dir=out, variants=varyantlar, src_bytes=self.KAYNAK)

	def _master_uri_listesi(self, master: str) -> list:
		return [s["URI"] for s in H.parse_master(master)]

	def test_kaynaktan_buyuk_basamak_ILAN_EDILMEZ(self):
		paket = self._paket_kur()
		# VACUITY ÖN KOŞULU: kapı uygulanmadan önce 720p master'da DURUYOR —
		# yani aşağıdaki yokluk, kapının eseridir, kurulumun değil.
		self.assertIn("v720p/playlist.m3u8", self._master_uri_listesi(paket.master_path))

		sonuc = H.enforce_rung_benefit_gate(paket)

		uriler = self._master_uri_listesi(sonuc.master_path)
		self.assertNotIn("v720p/playlist.m3u8", uriler)
		self.assertEqual(uriler, ["v360p/playlist.m3u8", "v480p/playlist.m3u8"])
		durum = {v.name: (v.benefit_gate, v.published) for v in sonuc.variants}
		self.assertEqual(durum["720p"], ("DUSTU", False))
		self.assertEqual(durum["360p"], ("GECTI", True))
		self.assertFalse(
			os.path.exists(os.path.join(sonuc.out_dir, "v720p")),
			"ilan edilmeyen basamagin dosyalari diskte OKSUZ kalmamali",
		)
		self.assertEqual(sonuc.published_bytes, 7_299_637 + 7_905_561)

	def test_hicbir_basamak_kucuk_degilse_paket_ILAN_EDILMEZ(self):
		paket = self._paket_kur(basamaklar=(("360p", self.KAYNAK + 1), ("480p", self.KAYNAK + 2)))
		sonuc = H.enforce_rung_benefit_gate(paket)
		self.assertEqual(sonuc.master_path, "")
		self.assertEqual(sonuc.published_variants, [])
		self.assertFalse(os.path.exists(sonuc.out_dir), "paketin tamami silinmeli")

	def test_tum_basamaklar_kucukse_master_degismez(self):
		paket = self._paket_kur(basamaklar=(("360p", 1000), ("480p", 2000)))
		once = open(paket.master_path, encoding="utf-8").read()
		sonuc = H.enforce_rung_benefit_gate(paket)
		self.assertEqual(open(sonuc.master_path, encoding="utf-8").read(), once)
		self.assertTrue(all(v.published for v in sonuc.variants))

	def test_kaynak_boyutu_olculemezse_kapi_uygulanmaz(self):
		paket = self._paket_kur()
		paket.src_bytes = 0
		sonuc = H.enforce_rung_benefit_gate(paket)
		self.assertTrue(all(v.benefit_gate == "UYGULANMADI" for v in sonuc.variants))
		self.assertIn("v720p/playlist.m3u8", self._master_uri_listesi(sonuc.master_path))

	def test_esitlik_de_ilan_edilmez(self):
		"""'Kaynaktan KÜÇÜK değilse' — eşit basamak da kazanç taşımaz."""
		paket = self._paket_kur(basamaklar=(("360p", 1000), ("480p", self.KAYNAK)))
		sonuc = H.enforce_rung_benefit_gate(paket)
		self.assertEqual(self._master_uri_listesi(sonuc.master_path), ["v360p/playlist.m3u8"])


# ══════════════════════════════════════════════════════════════════════════
# 1-2. Köprü: kapılar, slot çözümü, worker (DB + ffmpeg gerekir)
# ══════════════════════════════════════════════════════════════════════════


def _ornek_video_baytlari(faststart: bool = True, etiket: str = "") -> bytes:
	"""2 sn'lik gerçek, KÜÇÜK bir H.264 videosu (testsrc) üretir.

	`etiket` metadata'ya yazılır: içerik-adresli adlandırma yüzünden her koşu
	BENZERSİZ baytlar üretmeli — önceki koşunun artığı idempotency kapısını
	tetikleyip testi boş yeşile çevirmesin.
	"""
	with tempfile.TemporaryDirectory() as d:
		yol = os.path.join(d, "v.mp4")
		cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=24",
			"-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast"]
		if etiket:
			cmd += ["-metadata", f"title={etiket}"]
		if faststart:
			cmd += ["-movflags", "+faststart"]
		cmd += [yol]
		subprocess.run(cmd, capture_output=True, check=True, timeout=120)
		with open(yol, "rb") as f:
			return f.read()


if frappe is not None:

	DOCTYPE_AYAR = pipeline_flags.SETTINGS_DOCTYPE
	KORUNAN_ALANLAR = (
		"media_pipeline_enabled",
		"rendition_on_upload",
		"manifest_api_enabled",
		"active_slots",
	)
	VIDEO_SLOT = "product.video"

	def _sil(doctype: str, name: str) -> None:
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			frappe.db.commit()  # nosemgrep — worker commit'lerinin simetrisi

	class _BayrakliVideoTest(FrappeTestCase):
		def setUp(self) -> None:
			self._orijinal = {
				a: frappe.db.get_single_value(DOCTYPE_AYAR, a) for a in KORUNAN_ALANLAR
			}
			self._ayarla(media_pipeline_enabled=0, rendition_on_upload=0)

		def tearDown(self) -> None:
			for alan, deger in self._orijinal.items():
				frappe.db.set_single_value(DOCTYPE_AYAR, alan, deger)
			frappe.db.commit()  # nosemgrep — bayraklar kalıcı geri dönsün
			pipeline_flags.clear_cache()

		def _ayarla(self, **degerler: object) -> None:
			for alan, deger in degerler.items():
				frappe.db.set_single_value(DOCTYPE_AYAR, alan, deger)
			pipeline_flags.clear_cache()

		def _hatti_ac(self, slotlar: str = VIDEO_SLOT) -> None:
			self._ayarla(media_pipeline_enabled=1, rendition_on_upload=1, active_slots=slotlar)

		def _dosya_ekle(self, file_name: str, icerik: bytes, **alanlar: object):
			doc = frappe.get_doc(
				{"doctype": "File", "file_name": file_name, "is_private": 0, "content": icerik}
			)
			doc.insert(ignore_permissions=True)
			self.addCleanup(lambda: _sil("File", doc.name))
			if alanlar:
				frappe.db.set_value("File", doc.name, alanlar)
				doc.reload()
			return doc

	class TestVideoSlotHaritasi(FrappeTestCase):
		"""Harita politikaların `video` bloklu `bound_to`larından okunur."""

		def test_listing_video_url_cozulur(self):
			tam, _tekil, referanslar = pipeline_bridge._video_slot_bindings()
			self.assertEqual(tam.get(("Listing", "video_url")), VIDEO_SLOT)
			self.assertIn(("Listing", "video_url", VIDEO_SLOT), referanslar)

		def test_varyant_video_url_cozulur(self):
			tam, _tekil, _ref = pipeline_bridge._video_slot_bindings()
			self.assertEqual(tam.get(("Listing Variant Item", "variant_video_url")), VIDEO_SLOT)

		def test_gorsel_slotlari_haritada_YOK(self):
			tam, _tekil, _ref = pipeline_bridge._video_slot_bindings()
			self.assertNotIn(("Listing", "primary_image"), tam)

	@unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe yok — konteynerde calistir")
	class TestVideoKuyrukKapilari(_BayrakliVideoTest):
		"""Video dosyası görsel yoluyla AYNI üç kat kapıdan geçer."""

		def setUp(self) -> None:
			super().setUp()
			self.doc = self._dosya_ekle(
				"w7-kapi.mp4",
				_ornek_video_baytlari(etiket=frappe.generate_hash(length=10)),
				attached_to_doctype="Listing",
				attached_to_field="video_url",
			)

		def _enqueue(self):
			with mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as m:
				pipeline_bridge.maybe_generate_renditions(self.doc)
			return m

		def test_bayrak_kapaliyken_enqueue_yok(self):
			self.assertFalse(self._enqueue().called)

		def test_slot_kapaliyken_enqueue_yok(self):
			"""`active_slots`ta yalnız product.image varken video işi AÇILMAZ."""
			self._hatti_ac(slotlar="product.image")
			self.assertFalse(self._enqueue().called)

		def test_bayrak_ve_slot_acikken_video_isi_kuyruga_girer(self):
			self._hatti_ac()
			m = self._enqueue()
			m.assert_called_once()
			args, kwargs = m.call_args
			self.assertEqual(args[0], "tradehub_core.media.pipeline_bridge._run_video_job")
			self.assertEqual(kwargs.get("queue"), "media-video")
			self.assertEqual(kwargs.get("timeout"), 1800)
			self.assertTrue(kwargs.get("enqueue_after_commit"))
			self.assertEqual(kwargs.get("file_url"), self.doc.file_url)

		def test_private_video_muaf(self):
			self._hatti_ac()
			doc = self._dosya_ekle(
				"w7-private.mp4",
				_ornek_video_baytlari(etiket=frappe.generate_hash(length=10)),
				is_private=1,
				attached_to_doctype="Listing",
				attached_to_field="video_url",
			)
			with mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as m:
				pipeline_bridge.maybe_generate_renditions(doc)
			m.assert_not_called()

		def test_gorsel_dosyasi_video_yoluna_SAPMAZ(self):
			"""jpg, görsel işine gider (`_run_rendition_job`) — video işine değil."""
			self._hatti_ac(slotlar="product.image,product.video")
			import io

			from PIL import Image

			buf = io.BytesIO()
			Image.new("RGB", (64, 64), (120, 40, 200)).save(buf, "JPEG")
			# Koşu başına benzersiz içerik: görsel yolunun idempotency kapısı
			# önceki koşunun Media Asset'ini bulup enqueue'yu atlamasın.
			doc = self._dosya_ekle(
				"w7-gorsel.jpg",
				buf.getvalue() + frappe.generate_hash(length=12).encode(),
				attached_to_doctype="Listing",
				attached_to_field="primary_image",
			)
			with mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as m:
				pipeline_bridge.maybe_generate_renditions(doc)
			m.assert_called_once()
			self.assertTrue(m.call_args[0][0].endswith("_run_rendition_job"))

	@unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe yok — konteynerde calistir")
	class TestVideoWorkerUctanUca(_BayrakliVideoTest):
		"""`_run_video_job` — kayıt zinciri + kanonik adres + idempotency."""

		def _temizle(self, asset_name: str) -> None:
			import glob

			for rend in frappe.get_all(
				"Media Rendition", filters={"asset": asset_name}, fields=["name"]
			):
				_sil("Media Rendition", rend.name)
			for job in frappe.get_all("Media Processing Job", filters={"asset": asset_name}, pluck="name"):
				_sil("Media Processing Job", job)
			for surum in frappe.get_all("Media Version", filters={"asset": asset_name}, pluck="name"):
				_sil("Media Version", surum)
			_sil("Media Asset", asset_name)
			for kok in glob.glob(frappe.get_site_path("public", "files", "media", asset_name)):
				shutil.rmtree(kok, ignore_errors=True)

		def _kos(self, icerik: bytes):
			doc = self._dosya_ekle(
				"w7-worker.mp4",
				icerik,
				attached_to_doctype="Listing",
				attached_to_field="video_url",
			)
			self._hatti_ac()
			pipeline_bridge._run_video_job(doc.file_url)
			parmak = pipeline_bridge.content_fingerprint(doc)
			asset_name = frappe.db.get_value(
				"Media Asset", {"content_sha256": parmak, "slot_key": VIDEO_SLOT}, "name"
			)
			self.assertTrue(asset_name, "Media Asset açılmadı")
			self.addCleanup(lambda: self._temizle(asset_name))
			return doc, asset_name

		def test_remux_kaynagi_tam_zincir(self):
			"""moov'u sonda kaynak: h264 türevi + poster + Version + Job, kanonik adreste."""
			from tradehub_core.media.pipeline.core import dedup

			doc, asset_name = self._kos(_ornek_video_baytlari(faststart=False, etiket=frappe.generate_hash(length=10)))

			asset = frappe.get_doc("Media Asset", asset_name)
			self.assertEqual(asset.media_type, "video")
			self.assertEqual(asset.state, "ready")

			surumler = frappe.get_all(
				"Media Version",
				filters={"asset": asset_name},
				fields=["name", "version_hash", "source_hash", "width", "height", "duration_s", "lqip"],
			)
			self.assertEqual(len(surumler), 1)
			surum = surumler[0]
			self.assertEqual(len(surum.version_hash), 64)
			self.assertEqual((surum.width, surum.height), (320, 240))
			self.assertAlmostEqual(surum.duration_s, 2.0, delta=0.2)
			self.assertTrue(surum.lqip, "LQIP poster baytlarından dolmalı")

			turevler = {
				t.profile: t
				for t in frappe.get_all(
					"Media Rendition",
					filters={"asset": asset_name},
					fields=["profile", "width", "height", "format", "file_url", "bytes", "benefit_gate_passed"],
				)
			}
			self.assertIn("h264", turevler, "REMUX çıktısı kayda geçmeli")
			self.assertIn("poster", turevler)
			self.assertIn("poster_192", turevler, "poster görsel merdiveninden geçmeli")
			self.assertNotIn("hls", turevler, "2 sn'lik video HLS eşiğinin altında")

			h264 = turevler["h264"]
			self.assertEqual(h264.format, "mp4")
			cozulen = dedup.parse_rendition_path(h264.file_url)
			self.assertIsNotNone(cozulen, f"kanonik adres değil: {h264.file_url}")
			self.assertEqual(cozulen["asset"], asset_name)
			self.assertEqual(cozulen["version_hash"], surum.version_hash)
			yol = frappe.get_site_path("public", h264.file_url.lstrip("/"))
			self.assertTrue(os.path.exists(yol), "türev diske yazılmadı")
			self.assertFalse(P.moov_at_end_of(yol), "REMUX'un tek amacı buydu")

			poster = turevler["poster"]
			self.assertEqual(poster.format, "webp")
			self.assertTrue(
				os.path.exists(frappe.get_site_path("public", poster.file_url.lstrip("/")))
			)

			job = frappe.get_all(
				"Media Processing Job",
				filters={"asset": asset_name},
				fields=["status", "job_type", "queue", "idempotency_key"],
			)
			self.assertEqual(len(job), 1)
			self.assertEqual(job[0].status, "success")
			self.assertEqual(job[0].job_type, "transcode")
			self.assertEqual(job[0].queue, "media-video")
			parmak = pipeline_bridge.content_fingerprint(doc)
			self.assertEqual(job[0].idempotency_key, f"video:{parmak}:{VIDEO_SLOT}")

		def test_passthrough_kaynak_h264_uretmez_poster_uretir(self):
			doc, asset_name = self._kos(_ornek_video_baytlari(faststart=True, etiket=frappe.generate_hash(length=10)))
			karar = decide(P.probe(pipeline_bridge._media_disk_path(doc.file_url)))
			self.assertEqual(karar.action, "PASSTHROUGH", "ön koşul: kaynak zaten teslim edilebilir")

			profiller = frappe.get_all(
				"Media Rendition", filters={"asset": asset_name}, pluck="profile"
			)
			self.assertNotIn("h264", profiller, "PASSTHROUGH yeni dosya YAZMAZ")
			self.assertIn("poster", profiller)

		def test_ikinci_kosum_idempotent(self):
			doc, asset_name = self._kos(_ornek_video_baytlari(faststart=False, etiket=frappe.generate_hash(length=10)))
			once = frappe.db.count("Media Rendition", {"asset": asset_name})
			with mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as m:
				pipeline_bridge.maybe_generate_renditions(doc)
			m.assert_not_called()
			pipeline_bridge._run_video_job(doc.file_url)  # kuyruğa çoktan girmiş iş de no-op
			self.assertEqual(frappe.db.count("Media Rendition", {"asset": asset_name}), once)

	# ══════════════════════════════════════════════════════════════════════
	# 5. Manifest video bloğu
	# ══════════════════════════════════════════════════════════════════════

	def _gorunur_ilan() -> dict | None:
		satirlar = frappe.db.sql(
			"""
			SELECT l.name, l.seller_profile, l.video_url
			FROM `tabListing` l
			WHERE l.storefront_visible = 1 AND l.status = 'Active'
			ORDER BY l.name ASC LIMIT 1
			""",
			as_dict=True,
		)
		return satirlar[0] if satirlar else None

	class TestManifestVideo(_BayrakliVideoTest):
		"""`get_manifest(slot=product.video)` artık GÖRSEL DEĞİL video döner."""

		VIDEO_URL = "/files/w7-manifest-test-video.mp4"

		def setUp(self) -> None:
			super().setUp()
			self.ilan = _gorunur_ilan()
			if not self.ilan:
				self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")
			self._eski_video_url = frappe.db.get_value("Listing", self.ilan["name"], "video_url")
			frappe.db.set_value(
				"Listing", self.ilan["name"], "video_url", self.VIDEO_URL, update_modified=False
			)
			self.addCleanup(self._video_url_geri_al)

		def _video_url_geri_al(self) -> None:
			frappe.db.set_value(
				"Listing", self.ilan["name"], "video_url", self._eski_video_url, update_modified=False
			)
			frappe.db.commit()  # nosemgrep — fixture kalıcı geri dönsün

		def _fixture_kur(self, h264: bool = True) -> dict:
			"""File + Media Asset(video, ready) + Version + türev satırları.

			Diske KÜÇÜK bir yer tutucu yazılır: Frappe `File.insert` içerik
			hash'i için dosyayı okur — manifest'in kendisi yalnız DB okur.
			"""
			yol = frappe.get_site_path("public", self.VIDEO_URL.lstrip("/"))
			with open(yol, "wb") as f:
				f.write(b"w7 video yer tutucu")
			self.addCleanup(lambda: os.path.exists(yol) and os.remove(yol))

			dosya = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": os.path.basename(self.VIDEO_URL),
					"file_url": self.VIDEO_URL,
					"is_private": 0,
					"is_folder": 0,
				}
			)
			dosya.flags.th_skip_transcode = True
			dosya.insert(ignore_permissions=True)
			self.addCleanup(lambda: _sil("File", dosya.name))
			# İçerik-adresli adlandırma kancası (naming.write_file_hashed) insert
			# sırasında file_url'u hash'li ada TAŞIYOR (ölçüldü: /files/c4/….mp4).
			# Fixture'ın sözleşmesi Listing.video_url == File.file_url eşleşmesi —
			# adresi geri sabitliyoruz; manifest yalnız DB okuduğu için yeterli.
			frappe.db.set_value("File", dosya.name, "file_url", self.VIDEO_URL, update_modified=False)

			asset = frappe.get_doc(
				{
					"doctype": "Media Asset",
					"slot_key": VIDEO_SLOT,
					"media_type": "video",
					"state": "ready",
					"owner_seller": self.ilan.get("seller_profile") or "",
					"source_file": dosya.name,
					"content_sha256": frappe.generate_hash(length=32),
				}
			).insert(ignore_permissions=True)
			self.addCleanup(lambda: _sil("Media Asset", asset.name))

			surum_hash = frappe.generate_hash(length=64)
			surum = frappe.get_doc(
				{
					"doctype": "Media Version",
					"asset": asset.name,
					"version_hash": surum_hash,
					"source_hash": frappe.generate_hash(length=64),
					"engine_version": "ffmpeg-test",
					"width": 1280,
					"height": 720,
					"duration_s": 540.021,
					"lqip": "w7test",
					"lqip_data_uri": "data:image/png;base64,w7",
					"dominant_color": "#112233",
					"is_active": 1,
				}
			).insert(ignore_permissions=True)
			self.addCleanup(lambda: _sil("Media Version", surum.name))
			frappe.db.set_value("Media Asset", asset.name, "active_version", surum.name)

			kok = f"/files/media/{asset.name}/{surum_hash}"
			turevler = {
				"poster": f"{kok}/poster-1280.webp",
				"poster_192": f"{kok}/poster_192-192.webp",
				"poster_1024": f"{kok}/poster_1024-1024.webp",
				"hls": f"{kok}/hls/master.m3u8",
			}
			if h264:
				turevler["h264"] = f"{kok}/h264-1280.mp4"
			bicimler = {
				"poster": "webp",
				"poster_192": "webp",
				"poster_1024": "webp",
				"hls": "m3u8",
				"h264": "mp4",
			}
			olculer = {
				"poster": (1280, 720),
				"poster_192": (192, 192),
				"poster_1024": (1024, 576),
				"hls": (1280, 720),
				"h264": (1280, 720),
			}
			for profil, url in turevler.items():
				genislik, yukseklik = olculer[profil]
				rend = frappe.get_doc(
					{
						"doctype": "Media Rendition",
						"asset": asset.name,
						"version_hash": surum.name,
						"profile": profil,
						"width": genislik,
						"height": yukseklik,
						"format": bicimler[profil],
						"file_url": url,
						"bytes": 1000,
						"benefit_gate_passed": 1,
					}
				).insert(ignore_permissions=True)
				self.addCleanup(lambda ad=rend.name: _sil("Media Rendition", ad))
			frappe.db.commit()  # nosemgrep — manifest `frappe.db.sql` ile okuyor
			return {"asset": asset.name, "kok": kok, "turevler": turevler}

		def test_video_slotu_artik_gorsel_dondurmuyor(self):
			"""Rapor 81 §7'nin ölçtüğü kusur: slot video iken galeri dönüyordu."""
			self._ayarla(media_pipeline_enabled=1, manifest_api_enabled=1)
			fx = self._fixture_kur()

			sonuc = media_manifest.get_manifest(self.ilan["name"], slot=VIDEO_SLOT)

			self.assertEqual(sonuc["slot"], VIDEO_SLOT)
			self.assertEqual(sonuc["images"], [], "video gövdesi galeri taşımaz")
			video = sonuc["video"]
			self.assertIsNotNone(video, "video bloğu dönmeli")
			self.assertEqual(video["src"], fx["turevler"]["h264"])
			self.assertEqual(video["hlsSrc"], fx["turevler"]["hls"])
			self.assertEqual(video["poster"], fx["turevler"]["poster_1024"])
			self.assertEqual(
				[(p["profile"], p["width"]) for p in video["posterSrcset"]],
				[("poster_192", 192), ("poster_1024", 1024)],
			)
			self.assertEqual(video["reducedMotion"]["poster"], fx["turevler"]["poster_1024"])
			self.assertEqual(video["reducedMotion"]["src"], "")
			self.assertEqual((video["width"], video["height"]), (1280, 720))
			self.assertAlmostEqual(video["duration_s"], 540.021, places=3)
			self.assertEqual(video["type"], "video/mp4")
			self.assertEqual(video["lqip"], "data:image/png;base64,w7")
			self.assertEqual(sonuc["fallback"], fx["turevler"]["h264"])
			self.assertEqual(len(sonuc["renditions"]), 5)

		def test_passthrough_ta_src_ham_dosyadir(self):
			self._ayarla(media_pipeline_enabled=1, manifest_api_enabled=1)
			self._fixture_kur(h264=False)

			video = media_manifest.get_manifest(self.ilan["name"], slot=VIDEO_SLOT)["video"]

			self.assertEqual(video["src"], self.VIDEO_URL)
			self.assertTrue(video["poster"])

		def test_bayrak_kapaliyken_video_bos_fallback_ham(self):
			self._ayarla(media_pipeline_enabled=0)
			self._fixture_kur()

			sonuc = media_manifest.get_manifest(self.ilan["name"], slot=VIDEO_SLOT)

			self.assertFalse(sonuc["enabled"])
			self.assertIsNone(sonuc["video"])
			self.assertEqual(sonuc["fallback"], self.VIDEO_URL)
			self.assertEqual(sonuc["renditions"], [])

		def test_gorsel_slotu_govdesi_DEGISMEDI(self):
			"""Görsel manifesti `video` anahtarı TAŞIMAZ — ETag'ler oynamaz."""
			self._ayarla(media_pipeline_enabled=1, manifest_api_enabled=1)
			sonuc = media_manifest.get_manifest(self.ilan["name"])  # product.image
			self.assertNotIn("video", sonuc)
			self.assertIn("images", sonuc)

		def test_toplu_uc_da_video_dondurur(self):
			self._ayarla(media_pipeline_enabled=1, manifest_api_enabled=1)
			fx = self._fixture_kur()
			sonuc = media_manifest.get_manifest_batch(self.ilan["name"], slot=VIDEO_SLOT)
			manifest = sonuc["manifests"].get(self.ilan["name"])
			self.assertIsNotNone(manifest)
			self.assertEqual(manifest["video"]["src"], fx["turevler"]["h264"])


if __name__ == "__main__":
	unittest.main(verbosity=2)

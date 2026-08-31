"""KD-01 — Künye çıkarımı (core.probe) ve kabul kapısı (image.probe).

Kaynak okundu: `media/pipeline/core/probe.py` (483 satır),
`media/pipeline/image/probe.py` (794 satır). Her iddia oradaki kodun
davranışından türetildi; mevcut `tests/test_image_probe.py` beklentileri
kopyalanmadı.

Bu modülde üç tür test var ve adlandırma bunu açık eder:
  * `test_bi_*`   birim  — tek fonksiyonun girdi/çıktı sözleşmesi
  * `test_sn_*`   sınır  — eşik, 0/negatif, taşma, boş
  * `test_gv_*`   güvenlik — kaçış denemesi (bulguysa gerekçesi docstring'de)
"""

from __future__ import annotations

import unittest

from tradehub_core.media.pipeline.core import probe as core_probe
from tradehub_core.media.pipeline.image import probe as kapi
from tradehub_core.tests.kapsamli import _yardim as y

# ══════════════════════════════════════════════════════════════════════
# 1. sniff() — tür sezgisi
# ══════════════════════════════════════════════════════════════════════


class TestSniff(unittest.TestCase):
	def test_bi_bilinen_imzalar(self):
		beklenen = {
			"jpeg": y.jpeg(8, 8),
			"png": y.png(8, 8),
			"webp": y.webp(8, 8),
			"gif": y.gif_animated(8, 8),
			"tiff": y.tiff(8, 8),
		}
		for tur, icerik in beklenen.items():
			with self.subTest(tur=tur):
				self.assertEqual(core_probe.sniff(icerik), tur)

	def test_bi_bos_icerik_bos_dizge(self):
		self.assertEqual(core_probe.sniff(b""), "")

	def test_bi_calistirilabilir_mz_ve_elf(self):
		self.assertEqual(core_probe.sniff(y.calistirilabilir()), "executable")
		self.assertEqual(core_probe.sniff(y.elf()), "executable")

	def test_bi_data_uri(self):
		self.assertEqual(core_probe.sniff(y.data_uri_metni()), "data_uri")

	def test_bi_svg_ve_xml_ayrimi(self):
		self.assertEqual(core_probe.sniff(y.svg()), "svg")
		self.assertEqual(core_probe.sniff(b'<?xml version="1.0"?><root/>'), "xml")

	def test_sn_bom_onunde_svg_taninmaz(self):
		"""BOM `lstrip()` ile atılmıyor (yalnız boşluk atılır) → sniff "" döner.

		Bu bir ret gerekçesi değil; kapının SVG'yi başka bir kuralla (leading
		marker) yakalaması gerekir. Aşağıdaki güvenlik testi onu ölçüyor.
		"""
		self.assertEqual(core_probe.sniff(y.svg(bom=True)), "")

	def test_gv_pdf_ftyp_polyglotu_mp4_sayiliyor(self):
		"""`content[4:8] == b"ftyp"` kontrolü SIGNATURES tablosundan ÖNCE.

		`%PDF` + `ftyp` ile başlayan dosya "mp4" olarak sınıflanır; PDF olduğu
		hâlde video kuralları uygulanır. Tespit edilen davranış budur —
		test bunu SABİTLER ki değişirse fark edilsin.
		"""
		self.assertEqual(core_probe.sniff(y.pdf_ftyp_polyglot()), "mp4")

	def test_sn_kisa_icerik_patlamaz(self):
		for n in range(0, 20):
			with self.subTest(n=n):
				self.assertIsInstance(core_probe.sniff(b"\xff" * n), str)


# ══════════════════════════════════════════════════════════════════════
# 2. kind_of / _extension_matches
# ══════════════════════════════════════════════════════════════════════


class TestTurSinifi(unittest.TestCase):
	def test_bi_kind_of_tablosu(self):
		durumlar = [
			("jpeg", ".jpg", core_probe.KIND_IMAGE),
			("mp4", ".mp4", core_probe.KIND_VIDEO),
			("webm", ".webm", core_probe.KIND_VIDEO),
			("pdf", ".pdf", core_probe.KIND_DOCUMENT),
			("zip", ".docx", core_probe.KIND_DOCUMENT),
			("svg", ".svg", core_probe.KIND_IMAGE),
			("", ".mov", core_probe.KIND_VIDEO),
			("", ".png", core_probe.KIND_IMAGE),
			("", ".bilinmiyor", core_probe.KIND_UNKNOWN),
			("", "", core_probe.KIND_UNKNOWN),
		]
		for detected, ext, beklenen in durumlar:
			with self.subTest(detected=detected, ext=ext):
				self.assertEqual(core_probe.kind_of(detected, ext), beklenen)

	def test_bi_uzanti_uyum_uc_durum(self):
		# eşleşir
		self.assertIs(core_probe._extension_matches(".png", "png"), True)
		# eşleşmez
		self.assertIs(core_probe._extension_matches(".jpg", "png"), False)
		# uzantı tabloda yok → ölçülemez (None)
		self.assertIsNone(core_probe._extension_matches(".xyz", "png"))
		# tür sezilemedi ama uzantı var → uyumsuz sayılır
		self.assertIs(core_probe._extension_matches(".jpg", ""), False)
		# ikisi de yok → ölçülemez
		self.assertIsNone(core_probe._extension_matches("", ""))

	def test_bi_docx_hem_zip_hem_docx_kabul(self):
		self.assertIs(core_probe._extension_matches(".docx", "zip"), True)
		self.assertIs(core_probe._extension_matches(".docx", "docx"), True)


# ══════════════════════════════════════════════════════════════════════
# 3. Eklenmiş yük (appended payload) — güvenlik
# ══════════════════════════════════════════════════════════════════════


class TestEklenmisYuk(unittest.TestCase):
	def test_gv_jpeg_eoi_sonrasi_script_yakalanir(self):
		icerik = y.jpeg_kuyrukta_script()
		self.assertTrue(core_probe._has_appended_payload(icerik, "jpeg"))

	def test_gv_png_iend_sonrasi_script_yakalanir(self):
		self.assertTrue(core_probe._has_appended_payload(y.png_govdesinde_script(), "png"))

	def test_gv_temiz_jpeg_yanlis_pozitif_uretmez(self):
		self.assertFalse(core_probe._has_appended_payload(y.jpeg(64, 64), "jpeg"))

	def test_gv_ikinci_eoi_ile_kacis_KAPATILDI(self):
		"""F-02 düzeltildi — `rfind` yerine `find` (İLK yapısal bitiş).

		Saldırı: `...EOI <script> EOI`. Eskiden son EOI bulunduğu için kuyruk
		boş kalıyor ve tespit kaçıyordu. Artık ilk EOI yapısal son sayılıyor,
		ondan sonrası kuyruk.
		"""
		icerik = y.jpeg_script_sonra_eoi()
		self.assertIn(y.SCRIPT, icerik, "kurgu hatalı: yük dosyada yok")
		self.assertTrue(
			core_probe._has_appended_payload(icerik, "jpeg"),
			"F-02 geri geldi — ikinci EOI ile tespit yeniden kaçıyor",
		)

	def test_gv_temiz_jpeg_ilk_eoi_kuralinda_yanlis_pozitif_uretmez(self):
		"""`find` kullanmanın bedeli ölçülüyor: gövdesinde rastgele FFD9 geçen
		TEMİZ bir JPEG yanlışlıkla "ekli yük" sayılmamalı."""
		for olcu in ((64, 64), (320, 240), (800, 600), (1200, 1200)):
			with self.subTest(olcu=olcu):
				self.assertFalse(
					core_probe._has_appended_payload(y.jpeg(*olcu), "jpeg"),
					f"{olcu}: temiz JPEG ekli yük sayıldı",
				)

	def test_gv_64kb_ustu_dolgu_ile_kacis_KAPATILDI(self):
		"""F-01 düzeltildi — bayt girdisinde TAM içerik taranıyor.

		Eskiden yalnız son 64 KB pencereye bakılıyordu; dolgu pencereyi
		aşınca yapısal bitiş işaretçisi dışarıda kalıyor ve sonuç sessizce
		`False` oluyordu. Bayt girdisi zaten bellekte olduğu için tam tarama
		ek maliyet getirmiyor.
		"""
		icerik = y.jpeg_kuyrukta_script(dolgu=kapi.TAIL_BYTES + 4096)
		self.assertTrue(core_probe._has_appended_payload(icerik, "jpeg"))
		p = kapi.probe_header(icerik, filename="urun.jpg")
		self.assertTrue(p.appended_payload, "F-01 geri geldi — kapı yükü kaçırıyor")
		self.assertIn(kapi.SEBEP_APPENDED_PAYLOAD, p.codes)
		self.assertFalse(p.ok)

	def test_gv_yol_girdisinde_de_kacis_kapali(self):
		"""Aynı saldırı dosya yolundan gelirse de yakalanmalı (≤16 MB tam okunur)."""
		import tempfile
		from pathlib import Path

		icerik = y.jpeg_kuyrukta_script(dolgu=kapi.TAIL_BYTES + 4096)
		with tempfile.TemporaryDirectory() as d:
			yol = Path(d) / "urun.jpg"
			yol.write_bytes(icerik)
			p = kapi.probe_header(yol)
		self.assertTrue(p.appended_payload, "yol girdisinde yük kaçıyor")
		self.assertIn(kapi.SEBEP_APPENDED_PAYLOAD, p.codes)

	def test_sn_olculemeyen_eklenmis_yuk_TEMIZ_sayilmaz(self):
		"""Ölçülemediğinde `None` dönmeli — `False` "temiz" demekti ve yanlıştı."""
		self.assertIsNone(
			kapi._eklenmis_yuk(None, b"", b"", "jpeg", kapi.FULL_SCAN_MAX_BYTES // 2)
		)

	def test_gv_kucuk_dolgu_kapida_yakalanir(self):
		"""Aynı saldırı 64 KB altında kalırsa kapı reddediyor — kontrast testi."""
		p = kapi.probe_header(y.jpeg_kuyrukta_script(dolgu=1024), filename="urun.jpg")
		self.assertTrue(p.appended_payload)
		self.assertIn(kapi.SEBEP_APPENDED_PAYLOAD, p.codes)
		self.assertFalse(p.ok)

	def test_bi_bilinmeyen_bicimde_tum_govde_taranir(self):
		self.assertTrue(core_probe._has_appended_payload(b"xx<?php echo 1;?>", "bilinmiyor"))


# ══════════════════════════════════════════════════════════════════════
# 4. Konteyner doğrulama (zip/docx)
# ══════════════════════════════════════════════════════════════════════


class TestKonteyner(unittest.TestCase):
	def test_bi_gercek_docx_gecerli(self):
		self.assertIs(core_probe._container_valid(y.gercek_docx(), ".docx", "zip"), True)

	def test_gv_sahte_docx_reddedilir(self):
		self.assertIs(core_probe._container_valid(y.sahte_docx(), ".docx", "zip"), False)

	def test_bi_zip_olmayan_icin_none(self):
		self.assertIsNone(core_probe._container_valid(y.jpeg(8, 8), ".jpg", "jpeg"))

	def test_gv_bozuk_zip_false_doner_patlamaz(self):
		self.assertIs(core_probe._container_valid(b"PK\x03\x04bozuk", ".docx", "zip"), False)

	def test_gv_zip_bombasi_acilmaz(self):
		"""`namelist()` decompress etmez — 8 MB'lık girdi ucuz kalmalı."""
		icerik = y.zip_bombasi_kucuk()
		self.assertLess(len(icerik), 200_000, "kurgu: sıkıştırılmış hâli küçük olmalı")
		self.assertIs(core_probe._container_valid(icerik, ".docx", "zip"), False)


# ══════════════════════════════════════════════════════════════════════
# 5. probe_bytes — künye sözleşmesi
# ══════════════════════════════════════════════════════════════════════


class TestProbeBytes(unittest.TestCase):
	def test_bi_temel_alanlar(self):
		icerik = y.jpeg(120, 80)
		p = core_probe.probe_bytes(icerik, filename="a.jpg")
		self.assertEqual(p.kind, core_probe.KIND_IMAGE)
		self.assertEqual(p.detected, "jpeg")
		self.assertEqual(p.mime, "image/jpeg")
		self.assertEqual((p.width, p.height), (120, 80))
		self.assertEqual(p.byte_size, len(icerik))
		self.assertEqual(len(p.sha256), 64)
		self.assertTrue(p.readable)
		self.assertIs(p.loadable, True)

	def test_bi_megapiksel_ve_kenarlar(self):
		p = core_probe.probe_bytes(y.jpeg(2000, 1000), filename="a.jpg")
		self.assertAlmostEqual(p.megapixels, 2.0, places=3)
		self.assertEqual(p.short_edge, 1000)
		self.assertEqual(p.long_edge, 2000)

	def test_bi_display_size_exif_donusu(self):
		for yon in (5, 6, 7, 8):
			with self.subTest(yon=yon):
				p = core_probe.probe_bytes(y.jpeg(120, 80, orientation=yon), filename="a.jpg")
				self.assertEqual(p.display_size, (80, 120))
				self.assertAlmostEqual(p.aspect, 80 / 120, places=4)
		for yon in (1, 2, 3, 4):
			with self.subTest(yon=yon):
				p = core_probe.probe_bytes(y.jpeg(120, 80, orientation=yon), filename="a.jpg")
				self.assertEqual(p.display_size, (120, 80))

	def test_sn_bos_icerik(self):
		p = core_probe.probe_bytes(b"", filename="a.jpg")
		self.assertEqual(p.byte_size, 0)
		self.assertEqual(p.detected, "")
		self.assertFalse(p.readable)
		self.assertEqual(p.megapixels, 0.0)
		self.assertEqual(p.aspect, 0.0)

	def test_sn_uzanti_MIME_yedegi_SIMETRIK(self):
		"""F-03 düzeltildi — uzantı önce türe çevriliyor.

		`MIME_BY_KIND` anahtarları TÜR adı (`jpeg`); uzantı doğrudan aranınca
		`.jpg` sessizce boş dönüyordu.
		"""
		bozuk = b"\x00\x01\x02\x03" * 32
		for ad, beklenen in (
			("a.jpg", "image/jpeg"), ("a.jpeg", "image/jpeg"), ("a.png", "image/png"),
			("a.webp", "image/webp"), ("a.mp4", "video/mp4"), ("a.webm", "video/webm"),
			("a.tif", "image/tiff"), ("a.pdf", "application/pdf"),
		):
			with self.subTest(ad=ad):
				self.assertEqual(core_probe.probe_bytes(bozuk, filename=ad).mime, beklenen)

	def test_sn_bilinmeyen_uzantida_MIME_uydurulmaz(self):
		bozuk = b"\x00\x01\x02\x03" * 32
		for ad in ("a.xyz", "a", "", "a.exe"):
			with self.subTest(ad=ad):
				self.assertEqual(core_probe.probe_bytes(bozuk, filename=ad).mime, "")

	def test_bi_baglam_alanlari_gecer(self):
		p = core_probe.probe_bytes(
			y.png(8, 8), filename="a.png", existing_count=3, is_private=True, scan_clean=False
		)
		self.assertEqual(p.existing_count, 3)
		self.assertIs(p.is_private, True)
		self.assertIs(p.scan_clean, False)

	def test_gv_bilinmeyen_baglam_anahtari_yutulur(self):
		"""Sözleşme dışı anahtar künyeye sızmamalı (TypeError da atmamalı)."""
		p = core_probe.probe_bytes(y.png(8, 8), filename="a.png", uydurma_alan=1)
		self.assertFalse(hasattr(p, "uydurma_alan"))

	def test_bi_svg_pillow_yoluna_girmez(self):
		p = core_probe.probe_bytes(y.svg(), filename="a.svg")
		self.assertEqual(p.detected, "svg")
		self.assertEqual(p.kind, core_probe.KIND_IMAGE)
		self.assertFalse(p.readable)
		self.assertEqual((p.width, p.height), (0, 0))

	def test_gv_bomlu_svg_leading_marker_ile_yakalanir(self):
		"""sniff kaçırsa da tehlikeli-işaretçi kuralı BOM'u atlayarak yakalar."""
		p = core_probe.probe_bytes(y.svg(bom=True), filename="a.svg")
		self.assertEqual(p.detected, "")
		self.assertIs(p.leading_marker, True)

	def test_bi_kesik_jpeg_loadable_false(self):
		p = core_probe.probe_bytes(y.jpeg_kesik(0.4), filename="a.jpg")
		self.assertIs(p.loadable, False)

	def test_bi_to_dict_tum_alanlari_tasir(self):
		d = core_probe.probe_bytes(y.jpeg(8, 8), filename="a.jpg").to_dict()
		for alan in ("filename", "sha256", "kind", "detected", "width", "height", "leading_marker"):
			self.assertIn(alan, d)


class TestProbeVideoFfprobe(unittest.TestCase):
	def test_bi_fps_kesirli_cozulur(self):
		p = core_probe.probe_video_from_ffprobe(y.ffprobe_ciktisi(), filename="v.mp4")
		self.assertAlmostEqual(p.frame_rate, 29.97, places=2)

	def test_sn_fps_sifir_payda_none(self):
		p = core_probe.probe_video_from_ffprobe(y.ffprobe_ciktisi(fps="30/0"), filename="v.mp4")
		self.assertIsNone(p.frame_rate)

	def test_bi_bitrate_kbps_bps_ye_cevrilir(self):
		p = core_probe.probe_video_from_ffprobe(y.ffprobe_ciktisi(bitrate_kbps=1500), filename="v.mp4")
		self.assertEqual(p.bitrate_bps, 1_500_000)

	def test_sn_eksik_alanlar_none_kalir(self):
		p = core_probe.probe_video_from_ffprobe({}, filename="v.mp4")
		self.assertIsNone(p.duration_s)
		self.assertIsNone(p.bitrate_bps)
		self.assertEqual(p.byte_size, 0)
		self.assertFalse(p.readable)

	def test_bi_webm_KENDI_turuyle_kunyeleniyor(self):
		"""F-04 düzeltildi — tür kaptan, yoksa uzantıdan türetiliyor."""
		p = core_probe.probe_video_from_ffprobe(
			y.ffprobe_ciktisi(video_codec="vp9", audio_codec="opus"), filename="v.webm"
		)
		self.assertEqual(p.detected, "webm", "F-04 geri geldi")
		self.assertEqual(p.mime, "video/webm")
		self.assertEqual(p.extension, ".webm")
		self.assertIs(p.extension_matches_content, True)

	def test_bi_kap_adi_uzantiyi_EZER(self):
		"""ffprobe kabı biliyorsa uzantıya değil ona güvenilir."""
		p = core_probe.probe_video_from_ffprobe(
			y.ffprobe_ciktisi(container="matroska,webm"), filename="v.mp4"
		)
		self.assertEqual(p.detected, "webm")
		self.assertIs(p.extension_matches_content, False, "uzantı/kap çelişkisi görünmeli")

	def test_bi_mp4_beklendigi_gibi(self):
		p = core_probe.probe_video_from_ffprobe(y.ffprobe_ciktisi(), filename="v.mp4")
		self.assertEqual(p.detected, "mp4")
		self.assertEqual(p.mime, "video/mp4")

	def test_sn_kap_ve_uzanti_yoksa_tur_olculemedi(self):
		p = core_probe.probe_video_from_ffprobe({}, filename="")
		self.assertEqual(p.detected, "")
		self.assertEqual(p.mime, "")
		self.assertIsNone(p.extension_matches_content)


# ══════════════════════════════════════════════════════════════════════
# 6. Ham başlıktan ölçü — declared_dimensions
# ══════════════════════════════════════════════════════════════════════


class TestBeyanEdilenOlcu(unittest.TestCase):
	def test_bi_png_ihdr(self):
		self.assertEqual(kapi.declared_dimensions(y.png_beyan_edilen_olcu(30000, 30000), "png"), (30000, 30000))

	def test_bi_jpeg_sof_yurumesi(self):
		icerik = y.jpeg(321, 123)
		self.assertEqual(kapi.declared_dimensions(icerik[: kapi.HEAD_BYTES], "jpeg"), (321, 123))

	def test_bi_gif_mantiksal_ekran(self):
		self.assertEqual(kapi.declared_dimensions(y.gif_animated(37, 21), "gif"), (37, 21))

	def test_bi_webp_kanvas(self):
		olcu = kapi.declared_dimensions(y.webp(77, 33), "webp")
		self.assertEqual(olcu, (77, 33))

	def test_bi_webp_lossless_kanvas(self):
		self.assertEqual(kapi.declared_dimensions(y.webp(45, 19, lossless=True), "webp"), (45, 19))

	def test_sn_desteklenmeyen_bicim_none(self):
		self.assertIsNone(kapi.declared_dimensions(y.tiff(8, 8), "tiff"))

	def test_sn_kisa_baslik_none(self):
		self.assertIsNone(kapi.declared_dimensions(b"\x89PNG", "png"))
		self.assertIsNone(kapi.declared_dimensions(b"\xff\xd8", "jpeg"))

	def test_gv_jpeg_sof_yok_ise_none(self):
		"""SOS'a SOF görmeden ulaşılırsa ölçü OKUNAMAMIŞ sayılmalı."""
		sahte = b"\xff\xd8" + b"\xff\xda\x00\x02"
		self.assertIsNone(kapi.declared_dimensions(sahte, "jpeg"))

	def test_gv_bozuk_segment_uzunlugu_none(self):
		sahte = b"\xff\xd8" + b"\xff\xc0\x00\x01"  # seg_len < 2
		self.assertIsNone(kapi.declared_dimensions(sahte, "jpeg"))


# ══════════════════════════════════════════════════════════════════════
# 7. tail_is_complete — kesiklik
# ══════════════════════════════════════════════════════════════════════


class TestKesiklik(unittest.TestCase):
	def test_bi_tam_jpeg(self):
		self.assertIs(kapi.tail_is_complete(y.jpeg(32, 32), "jpeg"), True)

	def test_bi_kesik_jpeg(self):
		self.assertIs(kapi.tail_is_complete(y.jpeg_kesik(0.4), "jpeg"), False)

	def test_bi_tam_png(self):
		self.assertIs(kapi.tail_is_complete(y.png(32, 32), "png"), True)

	def test_bi_gif_trailer(self):
		self.assertIs(kapi.tail_is_complete(y.gif_animated(8, 8), "gif"), True)

	def test_sn_olculemeyen_bicim_none(self):
		self.assertIsNone(kapi.tail_is_complete(y.tiff(8, 8), "tiff"))

	def test_sn_bos_kuyruk_none(self):
		self.assertIsNone(kapi.tail_is_complete(b"", "jpeg"))

	def test_gv_govdede_rastgele_eoi_tam_sayilir(self):
		"""Bilinen zayıflık: `rfind` gövdedeki rastgele FFD9'u da kabul eder.

		Kesik ama içinde FFD9 geçen bir JPEG "tam" görünür. Kapının kesiklik
		kuralı bu yüzden tek başına yeterli değil; `normalize` çıktıyı ayrıca
		geri açarak doğruluyor (`_verify`). Davranış sabitleniyor.
		"""
		kesik = y.jpeg_kesik(0.4) + b"\xff\xd9\x00\x00"
		self.assertIs(kapi.tail_is_complete(kesik, "jpeg"), True)


# ══════════════════════════════════════════════════════════════════════
# 8. probe_header + _guard — kabul kapısı
# ══════════════════════════════════════════════════════════════════════


class TestKabulKapisi(unittest.TestCase):
	def test_bi_temiz_gorsel_gecer(self):
		p = kapi.probe_header(y.jpeg(800, 600), filename="urun.jpg")
		self.assertTrue(p.ok, p.codes)
		self.assertEqual(p.fmt, "JPEG")
		self.assertEqual((p.width, p.height), (800, 600))
		self.assertEqual(p.source_kind, "bytes")

	def test_sn_bos_dosya_tek_ret(self):
		p = kapi.probe_header(b"", filename="a.jpg")
		self.assertEqual(p.codes, ("empty",))

	def test_gv_bomba_beyani_acilmadan_reddedilir(self):
		"""30000×30000 (900 MP) BEYAN eden PNG — piksel ayrılmadan ret."""
		p = kapi.probe_header(y.png_beyan_edilen_olcu(30000, 30000), filename="bomba.png")
		self.assertIn("megapixel_bomb", p.codes)
		self.assertFalse(p.ok)

	def test_sn_tavanin_hemen_altinda_bomba_reddi_yok(self):
		cfg = kapi.GuardConfig(max_megapixels=1.0)
		# 1000×999 = 0,999 MP < 1 MP
		p = kapi.probe_header(y.png_beyan_edilen_olcu(1000, 999), filename="a.png", config=cfg)
		self.assertNotIn("megapixel_bomb", p.codes)

	def test_sn_tavanin_hemen_ustunde_bomba_reddi_var(self):
		cfg = kapi.GuardConfig(max_megapixels=1.0)
		p = kapi.probe_header(y.png_beyan_edilen_olcu(1000, 1001), filename="a.png", config=cfg)
		self.assertIn("megapixel_bomb", p.codes)

	def test_sn_tavana_esit_reddedilmez(self):
		"""Kural `>` — tam eşitlik geçer. Sözleşme sabitleniyor."""
		cfg = kapi.GuardConfig(max_megapixels=1.0)
		p = kapi.probe_header(y.png_beyan_edilen_olcu(1000, 1000), filename="a.png", config=cfg)
		self.assertNotIn("megapixel_bomb", p.codes)

	def test_gv_calistirilabilir_reddedilir(self):
		p = kapi.probe_header(y.calistirilabilir(), filename="resim.png")
		self.assertIn("dangerous_content", p.codes)

	def test_gv_data_uri_reddedilir(self):
		p = kapi.probe_header(y.data_uri_metni(), filename="resim.png")
		self.assertIn("dangerous_content", p.codes)

	def test_gv_svg_leading_marker_reddedilir(self):
		p = kapi.probe_header(y.svg(zararli=True), filename="a.svg")
		self.assertIn("dangerous_content", p.codes)

	def test_gv_uzanti_icerik_uyusmazligi(self):
		p = kapi.probe_header(y.polyglot_png_uzantisi_jpg(), filename="urun.jpg")
		self.assertIn("ext_content_mismatch", p.codes)

	def test_bi_uyusmazlik_kapatilirsa_uyari_olur(self):
		cfg = kapi.GuardConfig(reject_extension_mismatch=False)
		p = kapi.probe_header(y.polyglot_png_uzantisi_jpg(), filename="urun.jpg", config=cfg)
		self.assertNotIn("ext_content_mismatch", p.codes)
		self.assertTrue(any(u.startswith("uzanti=") for u in p.warnings), p.warnings)

	def test_bi_animasyon_varsayilan_reddedilir(self):
		p = kapi.probe_header(y.gif_animated(), filename="a.gif")
		self.assertIn("animated_not_allowed", p.codes)

	def test_bi_animasyon_izinliyse_gecer(self):
		cfg = kapi.GuardConfig(allow_animated=True)
		p = kapi.probe_header(y.gif_animated(), filename="a.gif", config=cfg)
		self.assertNotIn("animated_not_allowed", p.codes)
		self.assertTrue(p.animated)
		self.assertGreaterEqual(p.frame_count, 2)

	def test_bi_kesik_dosya_reddedilir(self):
		p = kapi.probe_header(y.jpeg_kesik(0.35), filename="a.jpg")
		self.assertIn(kapi.SEBEP_TRUNCATED, p.codes)

	def test_bi_kesiklik_olculemezse_uyari(self):
		p = kapi.probe_header(y.tiff(16, 16), filename="a.tiff")
		self.assertTrue(any(u.startswith("kesiklik_olculmedi") for u in p.warnings), p.warnings)

	def test_sn_byte_tavani(self):
		cfg = kapi.GuardConfig(max_bytes=100)
		p = kapi.probe_header(y.jpeg(200, 200), filename="a.jpg", config=cfg)
		self.assertIn("too_large", p.codes)

	def test_sn_from_accept_SIFIR_ile_sinir_kapatilabiliyor(self):
		"""F-05 düzeltildi — anahtarın YOKLUĞU ile 0 DEĞERİ artık ayrı.

		`or` kullanmak 0'ı falsy sayıp varsayılana düşürüyordu; slot politikası
		"sınır yok" diyemiyordu.
		"""
		cfg = kapi.GuardConfig.from_accept({"max_bytes": 0, "max_megapixels_hard": 0})
		self.assertEqual(cfg.max_bytes, 0, "F-05 geri geldi")
		self.assertEqual(cfg.max_megapixels, 0.0)

	def test_sn_from_accept_anahtar_YOKSA_varsayilan(self):
		cfg = kapi.GuardConfig.from_accept({})
		self.assertEqual(cfg.max_bytes, kapi.GuardConfig.max_bytes)
		self.assertEqual(cfg.max_megapixels, kapi.GuardConfig.max_megapixels)

	def test_bi_from_accept_alanlari_okur(self):
		cfg = kapi.GuardConfig.from_accept(
			{"max_megapixels_hard": 12, "max_bytes": 999, "allow_animated": True}
		)
		self.assertEqual(cfg.max_megapixels, 12.0)
		self.assertEqual(cfg.max_bytes, 999)
		self.assertTrue(cfg.allow_animated)

	def test_bi_desteklenmeyen_bicim_reddi(self):
		cfg = kapi.GuardConfig(allowed_formats=frozenset({"PNG"}))
		p = kapi.probe_header(y.jpeg(32, 32), filename="a.jpg", config=cfg)
		self.assertIn("unsupported_format", p.codes)

	def test_gv_okunamayan_baslik_reddi(self):
		p = kapi.probe_header(b"\x01\x02\x03\x04" * 64, filename="a.jpg")
		self.assertIn("decode_failed", p.codes)

	def test_bi_guard_only_yeniden_degerlendirir(self):
		p = kapi.probe_header(y.jpeg(4000, 3000), filename="a.jpg")
		self.assertTrue(p.ok, p.codes)
		dar = kapi.guard_only(p, kapi.GuardConfig(max_megapixels=1.0))
		self.assertIn("megapixel_bomb", dar.codes)
		# Özgün künye DEĞİŞMEMELİ (frozen dataclass sözleşmesi)
		self.assertTrue(p.ok)

	def test_bi_assert_accepted_istisna_atar(self):
		with self.assertRaises(kapi.ImageRejected) as ctx:
			kapi.assert_accepted(b"", filename="a.jpg")
		self.assertTrue(ctx.exception.rejections)
		self.assertIn("empty", str(ctx.exception))

	def test_bi_assert_accepted_kabulde_kunye_doner(self):
		p = kapi.assert_accepted(y.jpeg(64, 64), filename="a.jpg")
		self.assertTrue(p.ok)

	def test_bi_yol_girdisi_ile_ayni_karar(self):
		import tempfile
		from pathlib import Path

		icerik = y.jpeg(500, 400)
		with tempfile.TemporaryDirectory() as d:
			yol = Path(d) / "urun.jpg"
			yol.write_bytes(icerik)
			pb = kapi.probe_header(icerik, filename="urun.jpg")
			py = kapi.probe_header(yol)
			self.assertEqual(py.source_kind, "path")
			self.assertEqual((py.width, py.height), (pb.width, pb.height))
			self.assertEqual(py.codes, pb.codes)
			self.assertEqual(py.detected, pb.detected)

	def test_sn_olmayan_yol_empty_reddi(self):
		p = kapi.probe_header("/olmayan/yol/xyz.jpg")
		self.assertEqual(p.codes, ("empty",))
		self.assertEqual(p.source_kind, "path")

	def test_bi_to_dict_sozlesmesi(self):
		d = kapi.probe_header(y.jpeg(64, 64), filename="a.jpg").to_dict()
		zorunlu = {
			"filename", "extension", "byte_size", "detected", "fmt", "width", "height",
			"megapixels", "mode", "animated", "frame_count", "has_alpha", "has_icc",
			"dpi", "exif_orientation", "progressive", "readable", "truncated",
			"leading_marker", "appended_payload", "extension_matches_content",
			"ok", "rejections", "warnings", "source_kind",
		}
		self.assertEqual(zorunlu - set(d), set())

	def test_bi_png_exif_okumasi_atlanir(self):
		"""PNG'de `getexif()` piksel açtığı için kapı EXIF'i ATLAMALI."""
		p = kapi.probe_header(y.png(64, 64), filename="a.png")
		self.assertTrue(p.extra.get("exif_skipped"), p.extra)
		self.assertEqual(p.exif_orientation, 1)

	def test_gv_pillow_bombayi_acmayi_reddedince_fail_closed(self):
		"""CRC'si doğru, 900 MP beyan eden PNG → Pillow `DecompressionBombError`.

		Bu, ham başlık yedeğinden FARKLI bir daldır: Pillow dosyayı tanır ama
		açmayı reddeder. Kapı bu durumda ölçüyü ham başlıktan okuyup MP
		reddini yine de üretmelidir (rapor 75 bulgu 4).
		"""
		p = kapi.probe_header(y.png_beyan_edilen_olcu(30000, 30000, crc=True), filename="b.png")
		self.assertTrue(p.extra.get("decompression_bomb"), p.extra)
		self.assertTrue(p.extra.get("size_from_raw_header"), p.extra)
		self.assertEqual((p.width, p.height), (30000, 30000))
		self.assertIn("megapixel_bomb", p.codes)

	def test_gv_taninmayan_bomba_ham_basliktan_okunur(self):
		"""CRC bozuksa Pillow hiç tanımaz; ölçü yine ham başlıktan gelmeli."""
		p = kapi.probe_header(y.png_beyan_edilen_olcu(30000, 30000, crc=False), filename="b.png")
		self.assertTrue(p.extra.get("size_from_raw_header"), p.extra)
		self.assertIn("megapixel_bomb", p.codes)
		self.assertIn("decode_failed", p.codes)

	def test_bi_pillow_tavaninin_altinda_beyan_acilir(self):
		"""25 MP beyan → Pillow başlığı açar; PNG olduğu için EXIF atlanır."""
		p = kapi.probe_header(
			y.png_beyan_edilen_olcu(5000, 5000, crc=True),
			filename="a.png",
			config=kapi.GuardConfig(max_megapixels=0),
		)
		self.assertTrue(p.readable, p.extra)
		self.assertTrue(p.extra.get("exif_skipped"), p.extra)

	def test_bi_exif_yonu_okunur_jpeg(self):
		p = kapi.probe_header(y.jpeg(120, 80, orientation=6), filename="a.jpg")
		self.assertEqual(p.exif_orientation, 6)
		self.assertEqual(p.display_size, (80, 120))

	def test_bi_dpi_okunur(self):
		p = kapi.probe_header(y.jpeg(64, 64, dpi=(300, 300)), filename="a.jpg")
		self.assertEqual(p.dpi, (300.0, 300.0))

	def test_bi_alfa_ve_palet_tespiti(self):
		self.assertTrue(kapi.probe_header(y.png(16, 16, alpha=True), filename="a.png").has_alpha)
		self.assertFalse(kapi.probe_header(y.png(16, 16), filename="a.png").has_alpha)

	def test_gv_hicbir_girdide_istisna_atmaz(self):
		"""Kapı sözleşmesi: ret listesi döner, ASLA patlamaz."""
		girdiler = [
			b"", b"\x00", b"\xff" * 3, y.elf(), y.data_uri_metni(), y.svg(bom=True),
			y.sahte_docx(), y.pdf_ftyp_polyglot(), b"PK\x03\x04", b"GIF89a",
			b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, b"RIFF" + b"\x00" * 8,
		]
		for i, g in enumerate(girdiler):
			with self.subTest(i=i):
				p = kapi.probe_header(g, filename="x.bin")
				self.assertIsInstance(p, kapi.HeaderProbe)
				self.assertIsInstance(p.codes, tuple)


class TestKapiAynasi(unittest.TestCase):
	"""Kapı ile künye modülü aynı güvenlik sezgisini kullanmalı."""

	def test_bi_sniff_ayni_fonksiyon(self):
		self.assertIs(kapi.sniff, core_probe.sniff)

	def test_bi_imza_tablosu_upload_policy_ile_ayni(self):
		from tradehub_core.media import upload_policy

		up = {k for _, k in getattr(upload_policy, "_SIGNATURES", ())}
		cp = {k for _, k in core_probe.SIGNATURES}
		if not up:
			self.skipTest("upload_policy._SIGNATURES bulunamadı — ayna testi uygulanamıyor")
		self.assertTrue(up.issubset(cp) or cp.issubset(up), f"ayrışma: {up ^ cp}")


if __name__ == "__main__":
	unittest.main()

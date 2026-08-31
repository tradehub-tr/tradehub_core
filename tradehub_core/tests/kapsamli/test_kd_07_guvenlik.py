"""KD-07 — Güvenlik: SVG/XSS, XXE, zip/decompression bomba, yol kaçışı, izolasyon.

Kaynak okundu:
  * `media/pipeline/security/svg.py` (792)       — allowlist sanitize
  * `media/pipeline/security/isolation.py` (1125) — rlimit profilleri
  * `media/path_safety.py` (38)                  — traversal kapısı
  * `media/upload_policy.py`                     — tehlikeli içerik sezgisi

Bu modül "kötü niyetli girdi" üretir ve motorun onu KABUL ETMEDİĞİNİ ölçer.
Her test tek bir saldırı sınıfını temsil eder; geçmesi o sınıfın kapalı
olduğunu, düşmesi açık olduğunu gösterir.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from tradehub_core.media.pipeline.security import isolation as izo
from tradehub_core.media.pipeline.security import svg as sv
from tradehub_core.tests.kapsamli import _yardim as y


def _svg(icerik: str) -> bytes:
	return icerik.encode("utf-8")


TEMIZ = _svg(
	'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
	'<path d="M0 0h24v24H0z"/></svg>'
)


# ══════════════════════════════════════════════════════════════════════
# 1. SVG — script ve olay işleyicileri
# ══════════════════════════════════════════════════════════════════════


class TestSvgScript(unittest.TestCase):
	def test_bi_temiz_svg_kabul(self):
		r = sv.sanitize(TEMIZ)
		self.assertTrue(r.ok, r.kod)
		self.assertEqual(r.kod, sv.KOD_OK)
		self.assertTrue(r.content)

	def test_gv_script_elementi_silinir(self):
		r = sv.sanitize(
			_svg(
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
				'<script>alert(1)</script><rect width="4" height="4"/></svg>'
			)
		)
		self.assertTrue(r.ok, r.kod)
		self.assertNotIn(b"script", r.content.lower())
		self.assertNotIn(b"alert", r.content)
		self.assertTrue(r.temizlendi)

	def test_gv_onload_olay_isleyicisi_silinir(self):
		r = sv.sanitize(
			_svg(
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" onload="alert(1)">'
				'<rect width="4" height="4" onclick="x()"/></svg>'
			)
		)
		self.assertTrue(r.ok, r.kod)
		self.assertNotIn(b"onload", r.content.lower())
		self.assertNotIn(b"onclick", r.content.lower())
		self.assertGreaterEqual(r.sayac.get("handler", 0), 2)

	def test_gv_buyuk_harfli_olay_isleyicisi_de_silinir(self):
		r = sv.sanitize(
			_svg(
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" ONLOAD="alert(1)">'
				'<rect width="4" height="4"/></svg>'
			)
		)
		self.assertTrue(r.ok, r.kod)
		self.assertNotIn(b"alert", r.content)

	def test_gv_style_elementi_silinir(self):
		r = sv.sanitize(
			_svg(
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
				'<style>@import url(http://kotu/x.css);</style><rect width="4" height="4"/></svg>'
			)
		)
		self.assertTrue(r.ok, r.kod)
		self.assertNotIn(b"@import", r.content)
		self.assertNotIn(b"kotu", r.content)

	def test_gv_foreignobject_silinir(self):
		r = sv.sanitize(
			_svg(
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
				'<foreignObject><body xmlns="http://www.w3.org/1999/xhtml">'
				'<img src="x" onerror="alert(1)"/></body></foreignObject>'
				'<rect width="4" height="4"/></svg>'
			)
		)
		self.assertTrue(r.ok, r.kod)
		self.assertNotIn(b"onerror", r.content.lower())
		self.assertNotIn(b"foreignObject", r.content)

	def test_gv_javascript_href_silinir(self):
		"""`<a>` izin listesinde değil; alt ağacıyla birlikte gider.

		Dışarıda meşru bir `<rect>` bırakılıyor ki ret sebebi
		`svg_empty_after_sanitize` olmasın ve asıl ölçüm (javascript: şemasının
		çıktıda kalmaması) yapılabilsin.
		"""
		r = sv.sanitize(
			_svg(
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
				'<a href="javascript:alert(1)"><rect width="2" height="2"/></a>'
				'<rect width="4" height="4"/></svg>'
			)
		)
		self.assertTrue(r.ok, r.kod)
		self.assertNotIn(b"javascript", r.content.lower())
		self.assertNotIn(b"alert", r.content)

	def test_gv_yalniz_zararli_icerikli_svg_bos_kalinca_reddedilir(self):
		"""Temizlik sonrası çizim kalmazsa dosya KABUL EDİLMEZ."""
		r = sv.sanitize(
			_svg(
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
				'<a href="javascript:alert(1)"><rect width="2" height="2"/></a></svg>'
			)
		)
		self.assertFalse(r.ok)
		self.assertEqual(r.kod, sv.KOD_EMPTY_AFTER_SANITIZE)
		self.assertEqual(r.content, b"")

	def test_gv_xlink_href_harici_silinir(self):
		r = sv.sanitize(
			_svg(
				'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
				'viewBox="0 0 10 10">'
				'<use xlink:href="http://kotu/x.svg#a"/><rect width="4" height="4"/></svg>'
			)
		)
		self.assertTrue(r.ok, r.kod)
		self.assertNotIn(b"kotu", r.content)

	def test_bi_ic_referansli_use_href_korunur(self):
		"""`<use href="#id">` meşrudur — sanitize onu SİLMEMELİ."""
		r = sv.sanitize(
			_svg(
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
				'<defs><path id="p" d="M0 0h4v4H0z"/></defs>'
				'<use href="#p"/><rect width="4" height="4"/></svg>'
			)
		)
		self.assertTrue(r.ok, r.kod)
		self.assertIn(b"#p", r.content)

	def test_gv_href_use_disinda_silinir(self):
		r = sv.sanitize(
			_svg(
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
				'<image href="#p"/><rect width="4" height="4"/></svg>'
			)
		)
		self.assertTrue(r.ok, r.kod)
		self.assertNotIn(b"href", r.content)

	def test_gv_izinli_attribute_degeri_harici_url_ise_silinir(self):
		"""`fill="url(http://…)"` harici istek atar — değer de denetlenmeli."""
		r = sv.sanitize(
			_svg(
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
				'<rect width="4" height="4" fill="url(http://izleyici/p.png)"/></svg>'
			)
		)
		self.assertTrue(r.ok, r.kod)
		self.assertNotIn(b"izleyici", r.content)
		self.assertGreaterEqual(r.sayac.get("external_value", 0), 1)

	def test_bi_ic_url_referansi_korunur(self):
		r = sv.sanitize(
			_svg(
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
				'<rect width="4" height="4" fill="url(#grad)"/></svg>'
			)
		)
		self.assertTrue(r.ok, r.kod)
		self.assertIn(b"url(#grad)", r.content)

	def test_gv_deger_tehlikeli_tablosu(self):
		for deger in (
			"javascript:alert(1)",
			"JaVaScRiPt:alert(1)",
			"  data:text/html;base64,PHN2Zz4=",
			"expression(alert(1))",
			"url(http://x/y)",
			"url('//x/y')",
			"vbscript:msgbox",
		):
			with self.subTest(deger=deger):
				self.assertTrue(sv._deger_tehlikeli(deger), deger)
		for deger in ("", "url(#a)", "#000000", "M0 0h4v4H0z", "1.5"):
			with self.subTest(deger=deger):
				self.assertFalse(sv._deger_tehlikeli(deger), deger)


# ══════════════════════════════════════════════════════════════════════
# 2. SVG — XXE / DTD / billion laughs
# ══════════════════════════════════════════════════════════════════════


class TestSvgXxe(unittest.TestCase):
	def test_gv_doctype_reddedilir(self):
		r = sv.sanitize(
			_svg('<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><rect/></svg>')
		)
		self.assertFalse(r.ok)
		self.assertEqual(r.kod, sv.KOD_DTD_FORBIDDEN)
		self.assertEqual(r.content, b"")

	def test_gv_entity_bildirimi_reddedilir(self):
		r = sv.sanitize(
			_svg(
				'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><rect/></svg>'
			)
		)
		self.assertFalse(r.ok)
		self.assertEqual(r.kod, sv.KOD_DTD_FORBIDDEN)

	def test_gv_billion_laughs_ayristiriciya_ULASMAZ(self):
		"""Ret kararı ham bayt taramasıyla, bellek tükenmeden verilmeli."""
		bomba = (
			'<!DOCTYPE lolz [<!ENTITY lol "lol">'
			+ "".join(
				f'<!ENTITY lol{i} "&lol{i-1};&lol{i-1};&lol{i-1};&lol{i-1};&lol{i-1};">'
				for i in range(1, 10)
			)
			+ ']><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><rect>&lol9;</rect></svg>'
		)
		r = sv.sanitize(_svg(bomba))
		self.assertFalse(r.ok)
		self.assertEqual(r.kod, sv.KOD_DTD_FORBIDDEN)

	def test_gv_yorum_icindeki_doctype_de_reddedilir(self):
		"""Fail-closed: yanlış pozitif bilinçli."""
		r = sv.sanitize(
			_svg(
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4">'
				'<!-- <!DOCTYPE x> --><rect width="4" height="4"/></svg>'
			)
		)
		self.assertFalse(r.ok)
		self.assertEqual(r.kod, sv.KOD_DTD_FORBIDDEN)

	def test_gv_bosluklu_doctype_de_yakalanir(self):
		r = sv.sanitize(_svg('<!  DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'))
		self.assertFalse(r.ok)
		self.assertEqual(r.kod, sv.KOD_DTD_FORBIDDEN)


# ══════════════════════════════════════════════════════════════════════
# 3. SVG — sınırlar ve biçim
# ══════════════════════════════════════════════════════════════════════


class TestSvgSinirlar(unittest.TestCase):
	def test_gv_svgz_reddedilir(self):
		import gzip

		r = sv.sanitize(gzip.compress(TEMIZ))
		self.assertFalse(r.ok)
		self.assertEqual(r.kod, sv.KOD_COMPRESSED)

	def test_bi_svgz_politikayla_acilabilir_ama_varsayilan_kapali(self):
		self.assertFalse(sv.SvgPolicy().allow_svgz)

	def test_gv_girdi_tavani_ayristirmadan_once(self):
		pol = sv.SvgPolicy(max_input_bytes=100)
		r = sv.sanitize(b"<svg" + b" " * 200 + b"/>", policy=pol)
		self.assertFalse(r.ok)
		self.assertEqual(r.kod, sv.KOD_INPUT_TOO_LARGE)

	def test_gv_dugum_tavani(self):
		govde = "".join(f'<rect id="r{i}" width="1" height="1"/>' for i in range(40))
		r = sv.sanitize(
			_svg(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4">{govde}</svg>'),
			policy=sv.SvgPolicy(max_nodes=10),
		)
		self.assertFalse(r.ok)
		self.assertEqual(r.kod, sv.KOD_TOO_COMPLEX)

	def test_gv_cikti_bayt_tavani(self):
		govde = "".join(f'<rect id="r{i}" width="1" height="1"/>' for i in range(60))
		r = sv.sanitize(
			_svg(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4">{govde}</svg>'),
			policy=sv.SvgPolicy(max_bytes=200, max_nodes=1000),
		)
		self.assertFalse(r.ok)
		self.assertEqual(r.kod, sv.KOD_TOO_LARGE)

	def test_bi_viewbox_zorunlu(self):
		r = sv.sanitize(_svg('<svg xmlns="http://www.w3.org/2000/svg"><rect width="4" height="4"/></svg>'))
		self.assertFalse(r.ok)
		self.assertEqual(r.kod, sv.KOD_VIEWBOX_MISSING)

	def test_gv_kok_element_svg_degilse_reddedilir(self):
		r = sv.sanitize(_svg('<html><body><svg viewBox="0 0 4 4"/></body></html>'))
		self.assertFalse(r.ok)
		self.assertEqual(r.kod, sv.KOD_NOT_SVG)

	def test_gv_bozuk_xml_reddedilir(self):
		r = sv.sanitize(_svg('<svg xmlns="http://www.w3.org/2000/svg"><rect'))
		self.assertFalse(r.ok)
		self.assertEqual(r.kod, sv.KOD_NOT_WELL_FORMED)

	def test_gv_bos_icerik(self):
		for ham in (b"", b"   ", b"\n\t"):
			with self.subTest(ham=ham):
				r = sv.sanitize(ham)
				self.assertFalse(r.ok)
				self.assertEqual(r.kod, sv.KOD_NOT_WELL_FORMED)

	def test_gv_sanitize_sonrasi_cizim_kalmazsa_reddedilir(self):
		"""Yalnız script içeren SVG temizlendikten sonra BOŞ kalır → ret."""
		r = sv.sanitize(
			_svg(
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4">'
				'<script>alert(1)</script></svg>'
			)
		)
		self.assertFalse(r.ok)
		self.assertEqual(r.kod, sv.KOD_EMPTY_AFTER_SANITIZE)
		self.assertEqual(r.content, b"")

	def test_bi_scan_karari_sanitize_ile_ayni_ama_icerik_vermez(self):
		for ham in (TEMIZ, _svg("<svg/>"), b"", y.svg(zararli=True)):
			with self.subTest(n=len(ham)):
				a = sv.sanitize(ham)
				b = sv.scan(ham)
				self.assertEqual(a.ok, b.ok)
				self.assertEqual(a.kod, b.kod)
				self.assertEqual(b.content, b"")

	def test_bi_data_uri_cozulur_ve_denetlenir(self):
		import base64

		kotu = base64.b64encode(
			b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4">'
			b'<script>alert(1)</script><rect width="4" height="4"/></svg>'
		).decode()
		r = sv.sanitize_data_uri(f"data:image/svg+xml;base64,{kotu}")
		self.assertTrue(r.ok, r.kod)
		self.assertNotIn(b"alert", r.content)

	def test_gv_data_uri_olmayan_deger_reddedilir(self):
		r = sv.sanitize_data_uri("https://x/y.svg")
		self.assertFalse(r.ok)
		self.assertEqual(r.kod, sv.KOD_NOT_SVG)

	def test_gv_hicbir_girdide_istisna_atmaz(self):
		girdiler = [
			b"", b"<", b"<svg", b"\x00\xff", TEMIZ, TEMIZ * 3,
			b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'>" + b"<g>" * 300,
			y.calistirilabilir(), y.jpeg(8, 8), y.png(8, 8),
		]
		for i, g in enumerate(girdiler):
			with self.subTest(i=i):
				r = sv.sanitize(g)
				self.assertIsInstance(r, sv.SvgSanitizeResult)
				if not r.ok:
					self.assertEqual(r.content, b"")

	def test_bi_to_dict_sozlesmesi(self):
		d = sv.sanitize(TEMIZ).to_dict()
		for alan in ("ok", "code", "message_key", "node_count", "bytes_in",
					 "bytes_out", "parser", "sanitized", "counters", "findings"):
			self.assertIn(alan, d)

	def test_bi_politika_yuklenemezse_aynaya_duser(self):
		pol = sv.policy_yukle("olmayan-slot-xyz")
		self.assertEqual(pol.kaynak, "ayna")
		self.assertTrue(pol.allowed_elements)


# ══════════════════════════════════════════════════════════════════════
# 4. Yol kaçışı (path traversal)
# ══════════════════════════════════════════════════════════════════════


class TestYolKacisi(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.mkdtemp(prefix="kd07-")
		self.kok = os.path.join(self.tmp, "files")
		os.makedirs(self.kok, exist_ok=True)

	def test_bi_kok_icindeki_yol_kabul(self):
		from tradehub_core.media.path_safety import check_path_safety

		hedef = os.path.join(self.kok, "a", "b.jpg")
		self.assertTrue(check_path_safety(self.kok, hedef))

	def test_gv_ust_dizine_cikis_reddedilir(self):
		from tradehub_core.media.path_safety import check_path_safety

		for kotu in ("../../etc/passwd", "a/../../../etc/shadow", "../" * 12 + "etc/passwd"):
			with self.subTest(kotu=kotu):
				self.assertFalse(check_path_safety(self.kok, os.path.join(self.kok, kotu)), kotu)

	def test_gv_yuzde_kodlu_traversal_BU_KATMANDA_cozulmez(self):
		"""`..%2f..%2f` işletim sistemi için sıradan bir dizin adıdır.

		`check_path_safety` yol katmanıdır ve yüzde çözmesi YAPMAZ — doğru
		davranış budur. Tehlike, çağıranın kontrolden SONRA `unquote()`
		çağırmasıdır. Bu test kuralı sabitler: kontrol, çözülmüş yol üzerinde
		yapılmalıdır; sıra bozulursa bu test hâlâ yeşil kalacağı için
		çağıran taraf ayrıca denetlenmelidir (KD-09'da uç bazında).
		"""
		from urllib.parse import unquote

		from tradehub_core.media.path_safety import check_path_safety

		kodlu = "..%2f..%2fetc%2fpasswd"
		self.assertTrue(check_path_safety(self.kok, os.path.join(self.kok, kodlu)))
		cozulmus = unquote(kodlu)
		self.assertFalse(check_path_safety(self.kok, os.path.join(self.kok, cozulmus)))

	def test_gv_sembolik_bag_ile_kacis_reddedilir(self):
		from tradehub_core.media.path_safety import check_path_safety

		disarisi = os.path.join(self.tmp, "disarisi")
		os.makedirs(disarisi, exist_ok=True)
		bag = os.path.join(self.kok, "bag")
		try:
			os.symlink(disarisi, bag)
		except OSError:
			self.skipTest("symlink oluşturulamıyor")
		self.assertFalse(check_path_safety(self.kok, os.path.join(bag, "x.jpg")))

	def test_gv_kardes_dizin_onek_tuzagi(self):
		"""`/a/files` ile `/a/files_gizli` — startswith kullanılsaydı geçerdi."""
		from tradehub_core.media.path_safety import check_path_safety

		kardes = self.kok + "_gizli"
		os.makedirs(kardes, exist_ok=True)
		self.assertFalse(check_path_safety(self.kok, os.path.join(kardes, "x.jpg")))

	def test_sn_gorece_yol_ile_karsilastirma_patlar(self):
		"""BULGU F-08 (dayanıklılık) — mutlak/görece karışımı `ValueError` atar.

		`os.path.commonpath` mutlak ve görece yolu birlikte kabul etmez.
		`check_path_safety` bunu yakalamadığı için "güvenli değil" yerine
		istisna yükselir; çağıran `except` koymamışsa istek 500 döner.
		Girdi kullanıcıdan geliyorsa bu bir DoS/bilgi sızıntısı yüzeyidir.
		"""
		from tradehub_core.media.path_safety import check_path_safety

		try:
			sonuc = check_path_safety(self.kok, "gorece/yol.jpg")
		except ValueError:
			return  # bugünkü davranış — bulgu geçerli
		self.assertFalse(sonuc, "F-08 kapanmış: artık istisna yerine False dönüyor")


# ══════════════════════════════════════════════════════════════════════
# 5. İzolasyon profilleri
# ══════════════════════════════════════════════════════════════════════


class TestIzolasyon(unittest.TestCase):
	def test_bi_profiller_tanimli(self):
		self.assertEqual(set(izo.PROFILLER), {"image", "probe", "video", "scan"})

	def test_gv_core_dump_kapali(self):
		"""Bellek dökümü PII taşır — her profilde 0 olmalı."""
		for ad, lim in izo.PROFILLER.items():
			with self.subTest(profil=ad):
				self.assertEqual(lim.core_bytes, 0)

	def test_gv_her_profilde_adres_alani_tavani_var(self):
		for ad, lim in izo.PROFILLER.items():
			with self.subTest(profil=ad):
				self.assertIsNotNone(lim.address_space_bytes)
				self.assertGreater(lim.address_space_bytes, 0)

	def test_gv_her_profilde_duvar_saati_var(self):
		for ad, lim in izo.PROFILLER.items():
			with self.subTest(profil=ad):
				self.assertGreater(lim.wall_timeout_s, 0)

	def test_bi_cpu_limiti_duvar_saatini_asmaz(self):
		for ad, lim in izo.PROFILLER.items():
			with self.subTest(profil=ad):
				if lim.cpu_seconds is not None:
					self.assertLessEqual(lim.cpu_seconds, lim.wall_timeout_s)

	def test_gv_cikti_tavani_sonsuz_degil(self):
		for ad, lim in izo.PROFILLER.items():
			with self.subTest(profil=ad):
				self.assertGreater(lim.max_output_bytes, 0)
				self.assertLessEqual(lim.max_output_bytes, 8 * 1024 * 1024)

	def test_bi_with_kopyalar_ozgunu_bozmaz(self):
		a = izo.IMAGE_LIMITS
		b = a.with_(cpu_seconds=1)
		self.assertEqual(b.cpu_seconds, 1)
		self.assertNotEqual(a.cpu_seconds, 1)

	def test_bi_sebep_siniflandirmasi(self):
		import signal as sg

		self.assertEqual(izo._sinifla(0, None, True), izo.SEBEP_TIMEOUT)
		self.assertEqual(izo._sinifla(0, None, False), izo.SEBEP_OK)
		self.assertEqual(izo._sinifla(izo.EXIT_MEMORY, None, False), izo.SEBEP_MEMORY)
		self.assertEqual(izo._sinifla(izo.EXIT_EXCEPTION, None, False), izo.SEBEP_EXCEPTION)
		self.assertEqual(izo._sinifla(izo.EXIT_PICKLE, None, False), izo.SEBEP_EXCEPTION)
		self.assertEqual(izo._sinifla(1, None, False), izo.SEBEP_EXIT)
		self.assertEqual(izo._sinifla(None, sg.SIGKILL, False), izo.SEBEP_KILLED)
		if hasattr(sg, "SIGXCPU"):
			self.assertEqual(izo._sinifla(None, sg.SIGXCPU, False), izo.SEBEP_CPU)

	def test_bi_yeniden_denenebilir_sebepler_kapali_kume(self):
		self.assertTrue(izo.RETRYABLE_SEBEPLER)
		self.assertNotIn(izo.SEBEP_OK, izo.RETRYABLE_SEBEPLER)

	def test_bi_ayna_sabitleri_upstream_ile_ayrilmadi(self):
		"""`_AYNA` upstream sabitiyle ayrışırsa profiller sessizce kayar."""
		if not izo.UPSTREAM_VIDEO_AVAILABLE:
			self.skipTest("upstream video sabitleri import edilemedi")
		from tradehub_core.media.pipeline.contracts import video as vc

		self.assertEqual(izo._AYNA["FFPROBE_TIMEOUT_SECONDS"], vc.FFPROBE_TIMEOUT_SECONDS)
		self.assertEqual(izo._AYNA["FFMPEG_TIMEOUT_SECONDS"], vc.FFMPEG_TIMEOUT_SECONDS)

	def test_bi_rlimit_ciftleri_uretiliyor(self):
		ciftler = izo._rlimit_ciftleri(izo.IMAGE_LIMITS)
		adlar = {ad for ad, _s, _h in ciftler}
		self.assertIn("RLIMIT_CORE", adlar)
		self.assertTrue(adlar & {"RLIMIT_AS", "RLIMIT_CPU"})


# ══════════════════════════════════════════════════════════════════════
# 6. Tehlikeli yükleme içeriği — upload_policy sezgisi
# ══════════════════════════════════════════════════════════════════════


class TestTehlikeliIcerik(unittest.TestCase):
	def test_gv_upload_policy_tehlikeli_isaretcileri(self):
		from tradehub_core.media import upload_policy as up

		fn = getattr(up, "is_dangerous", None)
		if fn is None:
			self.skipTest("upload_policy.is_dangerous bulunamadı")
		for icerik in (
			b"<!DOCTYPE html><html></html>",
			b"<html><body>x</body></html>",
			b"<svg xmlns='http://www.w3.org/2000/svg'/>",
			b"<?xml version='1.0'?>",
			b"<script>alert(1)</script>",
			b"<% eval %>",
			b"#!/bin/sh\necho x",
			b"\xef\xbb\xbf<script>x</script>",
			b"   \n\t<html>",
		):
			with self.subTest(icerik=icerik[:20]):
				self.assertTrue(fn(icerik), icerik[:20])
		for icerik in (y.jpeg(8, 8), y.png(8, 8), b"", b"duz metin"):
			with self.subTest(icerik=icerik[:20]):
				self.assertFalse(fn(icerik), icerik[:20])


if __name__ == "__main__":
	unittest.main()

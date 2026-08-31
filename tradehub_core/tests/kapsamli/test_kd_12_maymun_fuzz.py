"""KD-12 — Maymun (monkey) ve fuzz testleri: rastgele ve bozuk girdi dayanıklılığı.

Amaç bir "doğru cevap" aramak DEĞİL; motorun hiçbir girdide çökmediğini,
yarım çıktı üretmediğini ve tehlikeli içeriği kazara kabul etmediğini ölçmek.

Üç teknik bir arada:
  1. **Maymun**   — tamamen rastgele bayt dizileri.
  2. **Mutasyon** — GEÇERLİ dosyaların bitleri bozularak türetilenler
                    (saf rastgele bayt, ayrıştırıcının derinine hiç inmez;
                    asıl kırılgan yollar "neredeyse geçerli" dosyalarda).
  3. **Sınır**    — 0, 1, çok büyük, negatif, unicode, çok uzun.

DETERMİNİZM: tohum sabit (`TOHUM`). Bir düşüş yeniden üretilebilir olmalı;
rastgele bir testin "bazen kırmızı" olması onu işe yaramaz kılar. Tohumu
değiştirip yeni bir tur koşmak isteyen `KD_FUZZ_TOHUM` ortam değişkenini verir.
"""

from __future__ import annotations

import os
import random
import unittest

from tradehub_core.media.pipeline.core import probe as core_probe
from tradehub_core.media.pipeline.image import normalize as nrm
from tradehub_core.media.pipeline.image import probe as kapi
from tradehub_core.media.pipeline.policy import engine as pe
from tradehub_core.media.pipeline.security import svg as sv
from tradehub_core.media.pipeline.video import decision as kr
from tradehub_core.media.pipeline.video.probe import VideoFacts
from tradehub_core.tests.kapsamli import _yardim as y

TOHUM: int = int(os.environ.get("KD_FUZZ_TOHUM") or 20260828)
TUR_SAYISI: int = int(os.environ.get("KD_FUZZ_TUR") or 150)


def _rng() -> random.Random:
	return random.Random(TOHUM)


def _tohum_kaynaklari() -> list[bytes]:
	"""Mutasyona uğratılacak GEÇERLİ dosyalar."""
	return [
		y.jpeg(64, 64),
		y.png(48, 48),
		y.png(48, 48, alpha=True),
		y.webp(40, 40),
		y.gif_animated(16, 16),
		y.tiff(32, 32),
		y.svg(),
		y.gercek_docx(),
		y.png_beyan_edilen_olcu(2000, 2000),
	]


def _mutasyon(rng: random.Random, ham: bytes, adet: int = 4) -> bytes:
	"""Rastgele konumlarda bayt bozma — "neredeyse geçerli" dosya üretir."""
	if not ham:
		return ham
	b = bytearray(ham)
	for _ in range(adet):
		i = rng.randrange(len(b))
		b[i] = rng.randrange(256)
	return bytes(b)


def _kesme(rng: random.Random, ham: bytes) -> bytes:
	if len(ham) < 4:
		return ham
	return ham[: rng.randrange(1, len(ham))]

def _ekleme(rng: random.Random, ham: bytes) -> bytes:
	i = rng.randrange(len(ham) + 1) if ham else 0
	ek = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 64)))
	return ham[:i] + ek + ham[i:]


def _rastgele(rng: random.Random, n: int) -> bytes:
	return bytes(rng.randrange(256) for _ in range(n))


def _kurbanlar(rng: random.Random, adet: int) -> list[tuple[str, bytes]]:
	"""(etiket, içerik) çiftleri — etiket düşüşte hangi tekniğin bulduğunu söyler."""
	kaynaklar = _tohum_kaynaklari()
	out: list[tuple[str, bytes]] = []
	for i in range(adet):
		secim = i % 4
		kaynak = kaynaklar[rng.randrange(len(kaynaklar))]
		if secim == 0:
			out.append((f"maymun#{i}", _rastgele(rng, rng.randrange(0, 4096))))
		elif secim == 1:
			out.append((f"mutasyon#{i}", _mutasyon(rng, kaynak, rng.randrange(1, 12))))
		elif secim == 2:
			out.append((f"kesme#{i}", _kesme(rng, kaynak)))
		else:
			out.append((f"ekleme#{i}", _ekleme(rng, kaynak)))
	return out


ADLAR = [
	"a.jpg", "a.png", "a.webp", "a.gif", "a.svg", "a.mp4", "a.docx",
	"", "a", ".jpg", "a." + "x" * 200, "üründür şöyle.jpg", "a\x00.jpg",
	"../../etc/passwd.jpg", "a b c.jpg", "a.JPG", "a.jpg.exe",
]


# ══════════════════════════════════════════════════════════════════════
# 1. Künye çıkarımı
# ══════════════════════════════════════════════════════════════════════


class TestFuzzKunye(unittest.TestCase):
	def test_maymun_probe_bytes_asla_patlamaz(self):
		rng = _rng()
		for etiket, icerik in _kurbanlar(rng, TUR_SAYISI):
			ad = ADLAR[rng.randrange(len(ADLAR))]
			with self.subTest(etiket=etiket, ad=ad):
				try:
					p = core_probe.probe_bytes(icerik, filename=ad)
				except Exception as exc:  # noqa: BLE001 — sözleşme testi
					self.fail(f"{etiket} ad={ad!r} n={len(icerik)}: {type(exc).__name__}: {exc}")
				self.assertIsInstance(p.detected, str)
				self.assertGreaterEqual(p.byte_size, 0)
				self.assertEqual(len(p.sha256), 64)

	def test_maymun_sniff_her_zaman_dizge(self):
		rng = _rng()
		for etiket, icerik in _kurbanlar(rng, TUR_SAYISI):
			with self.subTest(etiket=etiket):
				self.assertIsInstance(core_probe.sniff(icerik), str)

	def test_maymun_kunyede_olcu_negatif_olmaz(self):
		rng = _rng()
		for etiket, icerik in _kurbanlar(rng, TUR_SAYISI):
			with self.subTest(etiket=etiket):
				p = core_probe.probe_bytes(icerik, filename="a.png")
				self.assertGreaterEqual(p.width, 0, etiket)
				self.assertGreaterEqual(p.height, 0, etiket)
				self.assertGreaterEqual(p.megapixels, 0.0, etiket)


# ══════════════════════════════════════════════════════════════════════
# 2. Kabul kapısı
# ══════════════════════════════════════════════════════════════════════


class TestFuzzKapi(unittest.TestCase):
	def test_maymun_kapi_asla_patlamaz_ve_liste_doner(self):
		rng = _rng()
		for etiket, icerik in _kurbanlar(rng, TUR_SAYISI):
			ad = ADLAR[rng.randrange(len(ADLAR))]
			with self.subTest(etiket=etiket, ad=ad):
				try:
					p = kapi.probe_header(icerik, filename=ad)
				except Exception as exc:  # noqa: BLE001
					self.fail(f"{etiket} ad={ad!r}: {type(exc).__name__}: {exc}")
				self.assertIsInstance(p, kapi.HeaderProbe)
				self.assertIsInstance(p.codes, tuple)
				self.assertEqual(p.ok, not p.rejections)

	def test_gv_maymun_TEHLIKELI_isaretci_asla_kabul_edilmez(self):
		"""Bozulmuş dosyanın başına çalıştırılabilir işaretçi konursa kapı
		HER DURUMDA reddetmeli — mutasyon bunu atlatamamalı."""
		rng = _rng()
		for etiket, icerik in _kurbanlar(rng, 60):
			for onek in (b"<script>", b"<html>", b"<svg ", b"#!/bin/sh\n", b"<!doctype html"):
				zararli = onek + icerik
				with self.subTest(etiket=etiket, onek=onek[:10]):
					p = kapi.probe_header(zararli, filename="urun.jpg")
					self.assertIn(
						"dangerous_content", p.codes,
						f"{etiket} önek={onek!r} kapıdan geçti: {p.codes}",
					)

	def test_gv_maymun_calistirilabilir_onek_asla_kabul_edilmez(self):
		rng = _rng()
		for etiket, icerik in _kurbanlar(rng, 60):
			for onek in (b"MZ\x90\x00", b"\x7fELF\x02"):
				with self.subTest(etiket=etiket, onek=onek[:4]):
					p = kapi.probe_header(onek + icerik, filename="urun.png")
					self.assertFalse(p.ok, f"{etiket}: çalıştırılabilir kabul edildi")

	def test_gv_maymun_rastgele_bayt_ASLA_kabul_edilmez(self):
		"""Saf rastgele bayt geçerli bir görsel olamaz; kapı geçirirse
		bu ciddi bir kusurdur (yanlış negatif)."""
		rng = _rng()
		for i in range(TUR_SAYISI):
			icerik = _rastgele(rng, rng.randrange(64, 8192))
			with self.subTest(i=i):
				p = kapi.probe_header(icerik, filename="urun.jpg")
				self.assertFalse(p.ok, f"rastgele {len(icerik)} bayt kabul edildi: {p.to_dict()}")

	def test_gv_maymun_kabul_edilen_her_dosya_gercekten_gorsel(self):
		"""Kapıdan geçen mutasyon varsa Pillow onu GERÇEKTEN açabilmeli."""
		import io

		from PIL import Image

		rng = _rng()
		gecen = 0
		for etiket, icerik in _kurbanlar(rng, TUR_SAYISI):
			p = kapi.probe_header(icerik, filename="urun.jpg")
			if not p.ok:
				continue
			gecen += 1
			with self.subTest(etiket=etiket):
				try:
					with Image.open(io.BytesIO(icerik)) as im:
						im.verify()
				except Exception as exc:  # noqa: BLE001
					self.fail(f"{etiket} kapıdan geçti ama açılamıyor: {type(exc).__name__}: {exc}")
		# Kurgu sağlığı: hiç geçen olmadıysa test hiçbir şey ölçmemiş demektir.
		self.assertGreater(gecen, 0, "hiçbir mutasyon kapıdan geçmedi — kurgu çok agresif")


# ══════════════════════════════════════════════════════════════════════
# 3. Normalleştirme
# ══════════════════════════════════════════════════════════════════════


class TestFuzzNormalize(unittest.TestCase):
	def test_maymun_normalize_asla_patlamaz(self):
		rng = _rng()
		spec = nrm.NormalizeSpec(fmt="webp", max_long_edge=512)
		for etiket, icerik in _kurbanlar(rng, TUR_SAYISI):
			with self.subTest(etiket=etiket):
				try:
					r = nrm.normalize(icerik, spec, filename="a.jpg")
				except Exception as exc:  # noqa: BLE001
					self.fail(f"{etiket}: {type(exc).__name__}: {exc}")
				self.assertIsInstance(r, nrm.NormalizeResult)

	def test_gv_maymun_basarisizlikta_ASLA_yarim_cikti(self):
		rng = _rng()
		spec = nrm.NormalizeSpec(fmt="webp", max_long_edge=512)
		for etiket, icerik in _kurbanlar(rng, TUR_SAYISI):
			r = nrm.normalize(icerik, spec, filename="a.jpg")
			with self.subTest(etiket=etiket):
				if not r.ok:
					self.assertEqual(r.content, b"", f"{etiket}: ok=False ama içerik var")
					self.assertTrue(r.reason, f"{etiket}: ok=False ama gerekçe boş")

	def test_gv_maymun_basarili_cikti_HER_ZAMAN_acilabilir(self):
		import io

		from PIL import Image

		rng = _rng()
		spec = nrm.NormalizeSpec(fmt="webp", max_long_edge=512)
		uretilen = 0
		for etiket, icerik in _kurbanlar(rng, TUR_SAYISI):
			r = nrm.normalize(icerik, spec, filename="a.jpg")
			if not r.ok:
				continue
			uretilen += 1
			with self.subTest(etiket=etiket):
				with Image.open(io.BytesIO(r.content)) as im:
					self.assertEqual(im.size, (r.width, r.height))
		self.assertGreater(uretilen, 0, "hiç çıktı üretilmedi — kurgu ölçmüyor")

	def test_gv_maymun_cikti_ASLA_buyutulmez(self):
		"""FR-028: hiçbir fuzz girdisi upscale ürettirememeli."""
		rng = _rng()
		spec = nrm.NormalizeSpec(fmt="webp", max_long_edge=4096, min_long_edge=2048)
		for etiket, icerik in _kurbanlar(rng, TUR_SAYISI):
			r = nrm.normalize(icerik, spec, filename="a.jpg")
			if not (r.ok and r.probe):
				continue
			with self.subTest(etiket=etiket):
				kaynak = r.probe.display_size
				if kaynak[0] and kaynak[1]:
					self.assertLessEqual(r.width, kaynak[0], etiket)
					self.assertLessEqual(r.height, kaynak[1], etiket)


# ══════════════════════════════════════════════════════════════════════
# 4. SVG sanitizasyonu
# ══════════════════════════════════════════════════════════════════════


class TestFuzzSvg(unittest.TestCase):
	#: İYİ BİÇİMLİ düşman parçalar. Bilinçli olarak her biri tek başına
	#: geçerli XML: amaç ayrıştırıcıyı değil SANITIZE'ı sınamak. Bozuk XML
	#: zaten `test_maymun_bozuk_bayt_dizisi` ile ayrıca ölçülüyor.
	PARCALAR = [
		"<script>alert(1)</script>",
		'<a href="javascript:alert(1)"><rect width="2" height="2"/></a>',
		'<use xlink:href="http://x/y#a"/>',
		"<style>@import url(http://x);</style>",
		'<image href="data:text/html,x"/>',
		"<foreignObject><body/></foreignObject>",
		'<g onload="alert(1)"><circle r="1"/></g>',
		"<!-- yorum -->",
		'<rect width="4" height="4" fill="url(http://izleyici/p.png)"/>',
		'<path d="M0 0h4v4H0z"/>',
		'<text onclick="x()">merhaba</text>',
		'<set attributeName="href" to="javascript:alert(1)"/>',
	]

	def _kurgu(self, rng: random.Random) -> bytes:
		"""Kök + rastgele düşman parçalar + GEÇERLİ bir çizim + kapanış.

		Sonda meşru bir `<rect>` var ki temizlik sonrası dosya boş kalmasın
		(`svg_empty_after_sanitize`); böylece KABUL yolu gerçekten ölçülür.
		"""
		n = rng.randrange(1, 8)
		ic = "".join(self.PARCALAR[rng.randrange(len(self.PARCALAR))] for _ in range(n))
		return (
			'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
			f'{ic}<rect width="4" height="4"/></svg>'
		).encode()

	def test_maymun_svg_asla_patlamaz(self):
		rng = _rng()
		for i in range(TUR_SAYISI):
			govde = self._kurgu(rng)
			with self.subTest(i=i):
				try:
					r = sv.sanitize(govde)
				except Exception as exc:  # noqa: BLE001
					self.fail(f"#{i} {govde[:80]!r}: {type(exc).__name__}: {exc}")
				self.assertIsInstance(r, sv.SvgSanitizeResult)

	def test_gv_maymun_KABUL_edilen_cikti_ASLA_script_tasimaz(self):
		"""Kabul edilen her SVG çıktısı zararlı hiçbir iz taşımamalı."""
		rng = _rng()
		kabul = 0
		for i in range(TUR_SAYISI * 2):
			r = sv.sanitize(self._kurgu(rng))
			if not r.ok:
				self.assertEqual(r.content, b"", "ret hâlinde içerik dönmemeli")
				continue
			kabul += 1
			d = r.content.lower()
			with self.subTest(i=i):
				for yasak in (b"<script", b"javascript:", b"onload=", b"onerror=", b"@import",
							  b"<foreignobject", b"vbscript:", b"expression("):
					self.assertNotIn(yasak, d, f"#{i} çıktıda {yasak!r}: {r.content[:200]!r}")
		self.assertGreater(kabul, 0, "hiçbir kurgu kabul edilmedi — test ölçmüyor")

	def test_maymun_bozuk_bayt_dizisi(self):
		rng = _rng()
		for etiket, icerik in _kurbanlar(rng, TUR_SAYISI):
			with self.subTest(etiket=etiket):
				r = sv.sanitize(icerik)
				self.assertIsInstance(r, sv.SvgSanitizeResult)
				if not r.ok:
					self.assertEqual(r.content, b"")


# ══════════════════════════════════════════════════════════════════════
# 5. Politika motoru ve video karar tablosu
# ══════════════════════════════════════════════════════════════════════


class TestFuzzKarar(unittest.TestCase):
	SLOTLAR = (
		"product.image", "seller.logo", "user.avatar", "category.banner",
		"company.cover_image", "company.cover_video", "product.video",
		"document.attachment", "brand.logo",
	)

	def test_maymun_policy_engine_asla_patlamaz(self):
		rng = _rng()
		motor = pe.PolicyEngine()
		for i in range(TUR_SAYISI):
			kunye = {
				"filename": ADLAR[rng.randrange(len(ADLAR))],
				"extension": rng.choice([".jpg", ".png", ".svg", ".mp4", "", ".xyz"]),
				"byte_size": rng.choice([0, 1, 10**3, 10**8, -1]),
				"kind": rng.choice(["image", "video", "document", "unknown", ""]),
				"detected": rng.choice(["jpeg", "png", "mp4", "zip", "", "executable"]),
				"width": rng.choice([0, 1, 100, 5000, 100000, -5]),
				"height": rng.choice([0, 1, 100, 5000, 100000, -5]),
				"duration_s": rng.choice([None, 0.0, 1.5, 3600.0, -1.0]),
				"bitrate_bps": rng.choice([None, 0, 10**9]),
				"frame_rate": rng.choice([None, 0.0, 24.0, 1000.0]),
				"readable": rng.choice([True, False]),
				"loadable": rng.choice([True, False, None]),
				"animated": rng.choice([True, False, None]),
				"existing_count": rng.choice([None, 0, 5, 10**6]),
				"scan_clean": rng.choice([True, False, None]),
				"leading_marker": rng.choice([True, False]),
				"appended_payload": rng.choice([True, False]),
				"container_valid": rng.choice([True, False, None]),
				"extension_matches_content": rng.choice([True, False, None]),
			}
			slot = self.SLOTLAR[rng.randrange(len(self.SLOTLAR))]
			rol = rng.choice(["seller", "admin", "", "uydurma_rol"])
			with self.subTest(i=i, slot=slot):
				try:
					k = motor.evaluate(slot, kunye, rol)
				except Exception as exc:  # noqa: BLE001
					self.fail(f"#{i} slot={slot} rol={rol}: {type(exc).__name__}: {exc}\n{kunye}")
				self.assertIsInstance(k.allow, bool)
				self.assertIsInstance(k.violations, tuple)
				if not k.allow:
					self.assertEqual(k.normalized_targets, {}, "ret kararında hedef üretilmiş")

	def test_gv_maymun_guvenlik_bayragi_ASLA_gecmez(self):
		"""Tehlikeli bayrak açıksa hangi rastgele künye olursa olsun ret."""
		rng = _rng()
		motor = pe.PolicyEngine()
		for i in range(80):
			for bayrak in ("leading_marker", "appended_payload"):
				kunye = {
					"filename": "urun.jpg", "extension": ".jpg", "kind": "image",
					"detected": "jpeg", "mime": "image/jpeg", "fmt": "JPEG",
					"width": rng.randrange(1000, 3000), "height": rng.randrange(1000, 3000),
					"byte_size": rng.randrange(1000, 10**6),
					"readable": True, "loadable": True, "animated": False,
					"extension_matches_content": True, "existing_count": 0, "scan_clean": True,
					bayrak: True,
				}
				with self.subTest(i=i, bayrak=bayrak):
					self.assertFalse(
						motor.evaluate("product.image", kunye, "seller").allow,
						f"#{i} {bayrak} açıkken kabul edildi",
					)

	def test_maymun_video_karar_tablosu_asla_patlamaz(self):
		rng = _rng()
		for i in range(TUR_SAYISI):
			f = VideoFacts(
				measured=rng.choice([True, False]),
				has_video=rng.choice([True, False]),
				width=rng.choice([0, 1, 640, 1920, 8000, -1]),
				height=rng.choice([0, 1, 360, 1080, 5000, -1]),
				duration_s=rng.choice([0.0, 0.5, 30.0, 100000.0]),
				fps=rng.choice([0.0, 1.0, 30.0, 240.0]),
				video_codec=rng.choice(["h264", "vp9", "av1", "", "hevc"]),
				pix_fmt=rng.choice(["yuv420p", "yuv444p", "", "rgb24"]),
				video_bitrate_bps=rng.choice([0, 1, 10**6, 10**10]),
				container_family=rng.choice(["mp4", "matroska", "other", ""]),
				nb_streams=rng.choice([0, 1, 2, 12]),
				moov_at_end=rng.choice([True, False]),
				has_audio=rng.choice([True, False]),
				audio_codec=rng.choice(["aac", "opus", "", "mp3"]),
				audio_bitrate_bps=rng.choice([0, 128_000, 10**7]),
			)
			with self.subTest(i=i):
				try:
					k = kr.decide(f)
				except Exception as exc:  # noqa: BLE001
					self.fail(f"#{i}: {type(exc).__name__}: {exc}\n{f}")
				self.assertIn(k.action, kr.ACTIONS)


# ══════════════════════════════════════════════════════════════════════
# 6. Boyut sınırları — "çok büyük" ve "çok küçük"
# ══════════════════════════════════════════════════════════════════════


class TestSinirDegerler(unittest.TestCase):
	def test_sn_tek_bayt_ve_bos(self):
		for icerik in (b"", b"\x00", b"\xff", b"a"):
			with self.subTest(n=len(icerik)):
				self.assertFalse(kapi.probe_header(icerik, filename="a.jpg").ok)
				self.assertFalse(nrm.normalize(icerik, nrm.NormalizeSpec(), filename="a.jpg").ok)

	def test_sn_cok_uzun_dosya_adi(self):
		ad = "ü" * 5000 + ".jpg"
		p = kapi.probe_header(y.jpeg(32, 32), filename=ad)
		self.assertIsInstance(p, kapi.HeaderProbe)
		self.assertEqual(p.extension, ".jpg")

	def test_gv_null_bayt_iceren_dosya_adi(self):
		p = kapi.probe_header(y.jpeg(32, 32), filename="urun\x00.jpg")
		self.assertIsInstance(p, kapi.HeaderProbe)

	def test_sn_unicode_dosya_adlari(self):
		for ad in ("ürün.jpg", "商品.jpg", "🎉.jpg", "a‮b.jpg"):
			with self.subTest(ad=ad):
				self.assertIsInstance(kapi.probe_header(y.jpeg(16, 16), filename=ad), kapi.HeaderProbe)

	def test_sn_1x1_gorsel_kabul_edilebilir(self):
		p = kapi.probe_header(y.jpeg(1, 1), filename="a.jpg")
		self.assertEqual((p.width, p.height), (1, 1))

	def test_sn_asiri_uzun_kenar_orani(self):
		"""10000×1 gibi dejenere oran hesabı patlatmamalı."""
		p = kapi.probe_header(y.png_beyan_edilen_olcu(10000, 1), filename="a.png")
		self.assertIsInstance(p.aspect, float)
		self.assertGreater(p.aspect, 0)


if __name__ == "__main__":
	unittest.main()

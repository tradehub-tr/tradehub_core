"""T-041 — `tradehub_core/media/pipeline/core/crop.py` testleri.

Beş grup:

  1. Öncelik zinciri  — her seviye için bir test + üst seviye varken altın
                        KULLANILMADIĞININ kanıtı
  2. INV-10           — kaynak 2 kat küçültülünce kadraj DEĞİŞMEZ
  3. Özellik testi    — 4.000 rastgele girdide pencere daima sınırlar içinde ve
                        oran %0,5 toleransında
  4. Altın test       — `docs/simulator.html` içindeki `cropWindow()` JS'inin
                        birebir portu ile aynı sayıyı üretiyor mu
  5. Kenar sıkıştırma — odak köşedeyken pencere dışarı taşmıyor

`hypothesis` bu ortamda KURULU DEĞİL (ne yerelde ne konteynerde kontrol edildi:
`ModuleNotFoundError`). Kaynak dokümanın istediği özellik testi bu yüzden sabit
tohumlu (`random.Random(20260818)`) tekrarlanabilir bir üreteçle yazıldı —
hypothesis'in küçültme (shrinking) yeteneği yok, ama kapsama ve tekrar
edilebilirlik var. Ortama hypothesis girerse bu sınıf ona taşınmalıdır.

Çalıştırma:

    python3 -m unittest discover -s /Users/ahmet/Desktop/istoc/tradehub_core/tests -v
"""

from __future__ import annotations

import random
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.core import crop  # noqa: E402
from tradehub_core.media.pipeline.core.crop import (  # noqa: E402
	METHOD_CENTER,
	METHOD_FOCAL,
	METHOD_OVERRIDE,
	METHOD_SAFE_FOCAL,
	METHOD_SMARTCROP,
	CropError,
	CropWindow,
	Rect,
	resolve_crop,
	verify_window,
)

TOLERANS = crop.RATIO_TOLERANCE


def asset(width: int, height: int, intent=None) -> dict:
	return {"width": width, "height": height, "crop_intent": intent}


def profile(key: str, ratio, fit: str = "cover") -> dict:
	return {"profile_key": key, "aspect_ratio": ratio, "fit": fit}


# ─────────────────────────────────────────────────────────────────────────────
# Simülatörün cropWindow() fonksiyonunun BİREBİR portu (piksel uzayında).
# Kaynak: docs/simulator.html — crop.py modül docstring'inde JS'i yazılı.
# Bu port testin ALTIN referansıdır; üretim kodu buna uymak zorundadır.
# ─────────────────────────────────────────────────────────────────────────────
def sim_crop_window(nat_w, nat_h, base, focal, target_ar):
	def clamp(v, a, b):
		return min(max(v, a), b)

	W, H = nat_w, nat_h
	bx, by = base["x"] * W, base["y"] * H
	bw, bh = base["w"] * W, base["h"] * H
	if not target_ar:
		return {"x": bx, "y": by, "w": bw, "h": bh}
	if bw / bh > target_ar:
		h = bh
		w = h * target_ar
	else:
		w = bw
		h = w / target_ar
	x = focal["x"] * W - w / 2
	y = focal["y"] * H - h / 2
	x = clamp(x, bx, bx + bw - w)
	y = clamp(y, by, by + bh - h)
	return {"x": x, "y": y, "w": w, "h": h}


class OncelikZinciriTesti(unittest.TestCase):
	"""Her seviye için bir test; üst seviye varken alt seviye KULLANILMAZ."""

	# Beş seviyenin hepsini birden taşıyan niyet: override + güvenli alan +
	# odak + smartcrop önerisi. Testler sırayla üstten bir seviye söker ve
	# bir alttakinin devraldığını doğrular.
	def _tam_niyet(self) -> dict:
		return {
			"focal_x": 0.8, "focal_y": 0.2,
			"safe_x": 0.1, "safe_y": 0.1, "safe_w": 0.6, "safe_h": 0.6,
			"suggested_x": 0.3, "suggested_y": 0.3, "suggested_w": 0.4, "suggested_h": 0.4,
			"confidence": 0.9,
			"method": "manual",
			"overrides": [{"profile": "product-card", "x": 0.2, "y": 0.2, "w": 0.5, "h": 0.5}],
		}

	def test_1_override_kazanir(self):
		niyet = self._tam_niyet()
		win = resolve_crop(asset(2000, 1000), profile("product-card", "1:1"), niyet)
		self.assertEqual(win.method, METHOD_OVERRIDE)
		self.assertEqual(win.priority, 1)
		verify_window(win)

	def test_1b_baska_profilin_overridei_kullanilmaz(self):
		"""Override PROFİLE ÖZGÜDÜR — başka profile sızmaz."""
		niyet = self._tam_niyet()
		win = resolve_crop(asset(2000, 1000), profile("product-main", "1:1"), niyet)
		self.assertNotEqual(win.method, METHOD_OVERRIDE)
		self.assertEqual(win.method, METHOD_SAFE_FOCAL)

	def test_2_guvenli_alan_ve_odak(self):
		niyet = self._tam_niyet()
		niyet.pop("overrides")
		win = resolve_crop(asset(2000, 1000), profile("p", "1:1"), niyet)
		self.assertEqual(win.method, METHOD_SAFE_FOCAL)
		# Pencere güvenli alanın İÇİNDE kalmalı.
		safe = Rect(0.1, 0.1, 0.6, 0.6)
		self.assertTrue(safe.contains(win.rect), f"{win.as_dict()} güvenli alanın dışında")
		verify_window(win)

	def test_3_genel_odak(self):
		niyet = self._tam_niyet()
		niyet.pop("overrides")
		for k in ("safe_x", "safe_y", "safe_w", "safe_h"):
			niyet.pop(k)
		win = resolve_crop(asset(2000, 1000), profile("p", "1:1"), niyet)
		self.assertEqual(win.method, METHOD_FOCAL)
		verify_window(win)

	def test_4_smartcrop_esik_ustunde(self):
		niyet = {
			"suggested_x": 0.3, "suggested_y": 0.25, "suggested_w": 0.4, "suggested_h": 0.4,
			"confidence": 0.9,
			"method": "smartcrop",
		}
		win = resolve_crop(asset(2000, 1000), profile("p", "1:1"), niyet)
		self.assertEqual(win.method, METHOD_SMARTCROP)
		self.assertAlmostEqual(win.confidence, 0.9)
		verify_window(win)

	def test_4b_smartcrop_esik_altinda_kullanilmaz(self):
		niyet = {
			"suggested_x": 0.3, "suggested_y": 0.25, "suggested_w": 0.4, "suggested_h": 0.4,
			"confidence": 0.01,
			"method": "smartcrop",
		}
		win = resolve_crop(asset(2000, 1000), profile("p", "1:1"), niyet)
		self.assertEqual(win.method, METHOD_CENTER)

	def test_4c_onaysiz_oneri_kullanilir_ama_isaretlenir(self):
		"""T-041: `approved_by_user=0` iken de kullanılır, UI'da 'öneri' der."""
		niyet = {
			"suggested_x": 0.3, "suggested_y": 0.25, "suggested_w": 0.4, "suggested_h": 0.4,
			"confidence": 0.9, "method": "smartcrop", "approved_by_user": 0,
		}
		win = resolve_crop(asset(2000, 1000), profile("p", "1:1"), niyet)
		self.assertEqual(win.method, METHOD_SMARTCROP)
		self.assertTrue(win.is_suggestion)

		niyet["approved_by_user"] = 1
		onayli = resolve_crop(asset(2000, 1000), profile("p", "1:1"), niyet)
		self.assertFalse(onayli.is_suggestion)
		# Onay kadrajı DEĞİŞTİRMEZ — yalnız rozeti değiştirir.
		self.assertAlmostEqual(win.x, onayli.x)
		self.assertAlmostEqual(win.y, onayli.y)

	def test_5_merkez_fallback(self):
		win = resolve_crop(asset(2000, 1000), profile("p", "1:1"), None)
		self.assertEqual(win.method, METHOD_CENTER)
		self.assertEqual(win.priority, 5)
		# 2:1 kaynaktan 1:1 kırpım: yükseklik tam dolar, genişlik yarıya iner.
		self.assertAlmostEqual(win.h, 1.0)
		self.assertAlmostEqual(win.w, 0.5)
		self.assertAlmostEqual(win.x, 0.25)
		verify_window(win)

	def test_zincir_sirasi_bozulmuyor(self):
		"""Üstten aşağı seviye sökülürken öncelik numarası hep artmalı."""
		niyet = self._tam_niyet()
		beklenen = [METHOD_OVERRIDE, METHOD_SAFE_FOCAL, METHOD_FOCAL, METHOD_SMARTCROP, METHOD_CENTER]
		gorulen = []

		gorulen.append(resolve_crop(asset(1600, 1200), profile("product-card", "1:1"), niyet).method)
		niyet.pop("overrides")
		gorulen.append(resolve_crop(asset(1600, 1200), profile("product-card", "1:1"), niyet).method)
		for k in ("safe_x", "safe_y", "safe_w", "safe_h"):
			niyet.pop(k)
		gorulen.append(resolve_crop(asset(1600, 1200), profile("product-card", "1:1"), niyet).method)
		niyet.pop("focal_x")
		niyet.pop("focal_y")
		niyet["method"] = "smartcrop"
		gorulen.append(resolve_crop(asset(1600, 1200), profile("product-card", "1:1"), niyet).method)
		niyet["confidence"] = 0.0
		gorulen.append(resolve_crop(asset(1600, 1200), profile("product-card", "1:1"), niyet).method)

		self.assertEqual(gorulen, beklenen)
		self.assertEqual([crop.METHOD_PRIORITY[m] for m in gorulen], [1, 2, 3, 4, 5])

	def test_yarim_override_atlanir(self):
		"""Eksik alanı olan override sessizce KULLANILMAZ, zincir alta düşer."""
		niyet = {
			"overrides": [{"profile": "p", "x": 0.2, "y": 0.2, "w": None, "h": 0.5}],
			"focal_x": 0.7, "focal_y": 0.3,
		}
		win = resolve_crop(asset(1000, 1000), profile("p", "1:1"), niyet)
		self.assertEqual(win.method, METHOD_FOCAL)


class Inv10Testi(unittest.TestCase):
	"""INV-10 — normalize koordinat, kaynak ölçeğinden bağımsız."""

	NIYETLER = (
		{"focal_x": 0.72, "focal_y": 0.31},
		{"focal_x": 0.1, "focal_y": 0.9, "safe_x": 0.05, "safe_y": 0.05, "safe_w": 0.7, "safe_h": 0.7},
		{"overrides": [{"profile": "p", "x": 0.11, "y": 0.07, "w": 0.53, "h": 0.42}]},
		None,
	)
	ORANLAR = ("1:1", "4:5", "3:4", "16:9", "21:9", None)

	def test_yari_boyutlu_kaynak_ayni_kadraji_verir(self):
		"""Kaynak 2 kat küçültülüp aynı normalize niyet uygulanırsa kadraj AYNI."""
		for niyet in self.NIYETLER:
			for oran in self.ORANLAR:
				with self.subTest(niyet=niyet, oran=oran):
					buyuk = resolve_crop(asset(3000, 2000), profile("p", oran), niyet)
					kucuk = resolve_crop(asset(1500, 1000), profile("p", oran), niyet)
					# Normalize koordinatlar BİREBİR aynı olmalı — yaklaşık değil.
					self.assertEqual(
						(buyuk.x, buyuk.y, buyuk.w, buyuk.h),
						(kucuk.x, kucuk.y, kucuk.w, kucuk.h),
					)
					self.assertEqual(buyuk.method, kucuk.method)

	def test_piksel_kutusu_olcekle_orantili(self):
		"""Aynı niyet, 2 kat küçük kaynakta tam yarı piksel kutusu vermeli."""
		niyet = {"focal_x": 0.72, "focal_y": 0.31}
		b = resolve_crop(asset(3000, 2000), profile("p", "4:5"), niyet).to_pixels(3000, 2000)
		k = resolve_crop(asset(1500, 1000), profile("p", "4:5"), niyet).to_pixels(1500, 1000)
		for buyuk_deger, kucuk_deger in zip(b, k):
			# Yuvarlama nedeniyle 1 piksel sapma kabul edilir; daha fazlası
			# kadrajın kaydığı anlamına gelir.
			self.assertLessEqual(abs(buyuk_deger / 2.0 - kucuk_deger), 1.0,
								 f"{b} vs {k}")

	def test_ucbuyuk_olcek_zinciri(self):
		"""1x / 2x / 5x küçültmede normalize kadraj hiç değişmemeli."""
		niyet = {"focal_x": 0.05, "focal_y": 0.95}
		temel = None
		for w, h in ((5000, 4000), (2500, 2000), (1000, 800)):
			win = resolve_crop(asset(w, h), profile("p", "16:9"), niyet)
			if temel is None:
				temel = (win.x, win.y, win.w, win.h)
			else:
				self.assertEqual(temel, (win.x, win.y, win.w, win.h))


class AltinSimulatorTesti(unittest.TestCase):
	"""Backend çıktısı ile `docs/simulator.html` cropWindow() çıktısı AYNI mı.

	Ayrışırlarsa kullanıcı önizlemede gördüğünden başka bir kadraj alır — bu
	testin var olma sebebi tam olarak budur.
	"""

	def test_ayni_pencere(self):
		rng = random.Random(4141)
		oranlar = (1.0, 0.8, 0.75, 4 / 3, 16 / 9, 9 / 16, 3.0, 21 / 9, None)
		for i in range(600):
			W = rng.randint(200, 6000)
			H = rng.randint(200, 6000)
			bw = rng.uniform(0.2, 1.0)
			bh = rng.uniform(0.2, 1.0)
			bx = rng.uniform(0.0, 1.0 - bw)
			by = rng.uniform(0.0, 1.0 - bh)
			fx = rng.uniform(bx, bx + bw)
			fy = rng.uniform(by, by + bh)
			ar = oranlar[i % len(oranlar)]

			base = {"x": bx, "y": by, "w": bw, "h": bh}
			beklenen = sim_crop_window(W, H, base, {"x": fx, "y": fy}, ar)

			niyet = {
				"focal_x": fx, "focal_y": fy,
				"safe_x": bx, "safe_y": by, "safe_w": bw, "safe_h": bh,
			}
			win = resolve_crop(asset(W, H), profile("p", ar), niyet)
			with self.subTest(i=i, W=W, H=H, ar=ar):
				# Normalize pencereyi piksele çevirip JS ile karşılaştır.
				self.assertAlmostEqual(win.x * W, beklenen["x"], places=6)
				self.assertAlmostEqual(win.y * H, beklenen["y"], places=6)
				self.assertAlmostEqual(win.w * W, beklenen["w"], places=6)
				self.assertAlmostEqual(win.h * H, beklenen["h"], places=6)

	def test_html_simulatorun_javascripti_backend_ile_ayni(self):
		"""Port değil, gerçek HTML içindeki fonksiyon 200 girdide doğrudan koşar."""
		node = shutil.which("node")
		if not node:
			self.skipTest("Node yok; HTML JavaScript paritesi host/frontend CI'da koşar")
		html = (ROOT / "docs" / "simulator.html").read_text(encoding="utf-8")
		match = re.search(
			r"// T010-CROPWINDOW-BEGIN\s*(.*?)\s*// T010-CROPWINDOW-END",
			html,
			flags=re.DOTALL,
		)
		self.assertIsNotNone(match, "simulator cropWindow işaretli bloğu bulunamadı")

		rng = random.Random(10010)
		cases = []
		for i in range(200):
			W, H = rng.randint(1, 8000), rng.randint(1, 8000)
			bw, bh = rng.uniform(0.05, 1.0), rng.uniform(0.05, 1.0)
			bx, by = rng.uniform(0, 1 - bw), rng.uniform(0, 1 - bh)
			fx, fy = rng.uniform(bx, bx + bw), rng.uniform(by, by + bh)
			ar = (None, 1.0, 0.8, 0.75, 16 / 9, 21 / 9)[i % 6]
			cases.append({
				"W": W, "H": H,
				"base": {"x": bx, "y": by, "w": bw, "h": bh},
				"focal": {"x": fx, "y": fy}, "ar": ar,
			})

		runner = f"""{match.group(1)}
const fs = require('fs');
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(c => cropWindow(c.W, c.H, c.base, c.focal, c.ar))));
"""
		completed = subprocess.run(
			[node, "-e", runner],
			input=json.dumps(cases), text=True, capture_output=True, check=True,
		)
		actual = json.loads(completed.stdout)
		for i, (case, js_window) in enumerate(zip(cases, actual)):
			win = resolve_crop(
				asset(case["W"], case["H"]), profile("p", case["ar"]),
				{
					"focal_x": case["focal"]["x"], "focal_y": case["focal"]["y"],
					"safe_x": case["base"]["x"], "safe_y": case["base"]["y"],
					"safe_w": case["base"]["w"], "safe_h": case["base"]["h"],
				},
			)
			for key, backend in (
				("x", win.x * case["W"]), ("y", win.y * case["H"]),
				("w", win.w * case["W"]), ("h", win.h * case["H"]),
			):
				self.assertLessEqual(abs(js_window[key] - backend), 0.5, f"case={i} alan={key}")

	def test_tam_kadraj_taban_da_ayni(self):
		"""Güvenli alan yokken taban tüm kadraj: simülatörün base=(0,0,1,1) hâli."""
		for W, H, ar in ((1920, 1080, 1.0), (1000, 2000, 16 / 9), (800, 800, 0.75)):
			beklenen = sim_crop_window(W, H, {"x": 0, "y": 0, "w": 1, "h": 1},
									   {"x": 0.5, "y": 0.5}, ar)
			win = resolve_crop(asset(W, H), profile("p", ar), {"focal_x": 0.5, "focal_y": 0.5})
			self.assertAlmostEqual(win.x * W, beklenen["x"], places=6)
			self.assertAlmostEqual(win.w * W, beklenen["w"], places=6)
			self.assertAlmostEqual(win.h * H, beklenen["h"], places=6)


class OzellikTesti(unittest.TestCase):
	"""Rastgele girdide değişmezler — sabit tohumlu, tekrarlanabilir."""

	ORANLAR = ("1:1", "4:5", "3:4", "4:3", "16:9", "9:16", "3:1", "21:9", None)

	def test_pencere_daima_sinirlar_icinde_ve_oranda(self):
		rng = random.Random(20260818)
		for i in range(4000):
			W = rng.randint(16, 12000)
			H = rng.randint(16, 12000)
			oran = self.ORANLAR[rng.randrange(len(self.ORANLAR))]
			niyet = self._rastgele_niyet(rng)
			with self.subTest(i=i, W=W, H=H, oran=oran, niyet=niyet):
				win = resolve_crop(asset(W, H), profile("p", oran), niyet)
				# 1) Sınırlar içinde
				self.assertGreaterEqual(win.x, -1e-9)
				self.assertGreaterEqual(win.y, -1e-9)
				self.assertLessEqual(win.x + win.w, 1.0 + 1e-6)
				self.assertLessEqual(win.y + win.h, 1.0 + 1e-6)
				self.assertGreater(win.w, 0.0)
				self.assertGreater(win.h, 0.0)
				# 2) Oran toleransta (verify_window aynı kontrolü yapar)
				verify_window(win)
				# 3) Piksel kutusu da kaynağın içinde
				left, top, w, h = win.to_pixels(W, H)
				self.assertGreaterEqual(left, 0)
				self.assertGreaterEqual(top, 0)
				self.assertLessEqual(left + w, W)
				self.assertLessEqual(top + h, H)

	def _rastgele_niyet(self, rng):
		secim = rng.randrange(6)
		if secim == 0:
			return None
		if secim == 1:
			return {"focal_x": rng.random(), "focal_y": rng.random()}
		if secim == 2:
			bw, bh = rng.uniform(0.05, 1.0), rng.uniform(0.05, 1.0)
			return {
				"safe_x": rng.uniform(0, 1 - bw), "safe_y": rng.uniform(0, 1 - bh),
				"safe_w": bw, "safe_h": bh,
				"focal_x": rng.random(), "focal_y": rng.random(),
			}
		if secim == 3:
			w, h = rng.uniform(0.05, 1.0), rng.uniform(0.05, 1.0)
			return {"overrides": [{
				"profile": "p", "x": rng.uniform(0, 1 - w), "y": rng.uniform(0, 1 - h),
				"w": w, "h": h,
			}]}
		if secim == 4:
			w, h = rng.uniform(0.05, 1.0), rng.uniform(0.05, 1.0)
			return {
				"method": "smartcrop", "confidence": rng.random(),
				"suggested_x": rng.uniform(0, 1 - w), "suggested_y": rng.uniform(0, 1 - h),
				"suggested_w": w, "suggested_h": h,
			}
		bw, bh = rng.uniform(0.05, 1.0), rng.uniform(0.05, 1.0)
		return {"safe_x": rng.uniform(0, 1 - bw), "safe_y": rng.uniform(0, 1 - bh),
				"safe_w": bw, "safe_h": bh}


class KenarSikistirmaTesti(unittest.TestCase):
	"""Odak köşedeyken pencere dışarı taşmaz."""

	KOSELER = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.0, 0.5), (0.5, 1.0))

	def test_kose_odaklarda_tasma_yok(self):
		for fx, fy in self.KOSELER:
			for oran in ("1:1", "16:9", "9:16", "21:9"):
				for W, H in ((3000, 1000), (1000, 3000), (2048, 2048)):
					with self.subTest(f=(fx, fy), oran=oran, boyut=(W, H)):
						win = resolve_crop(asset(W, H), profile("p", oran),
										   {"focal_x": fx, "focal_y": fy})
						verify_window(win)
						self.assertGreaterEqual(win.x, -1e-9)
						self.assertLessEqual(win.x + win.w, 1.0 + 1e-6)

	def test_odak_guvenli_alanin_disindaysa_sikistirilir(self):
		"""Kullanıcı odağı güvenli alan dışına taşımışsa güvenli alan KISITTIR."""
		niyet = {"safe_x": 0.6, "safe_y": 0.6, "safe_w": 0.3, "safe_h": 0.3,
				 "focal_x": 0.0, "focal_y": 0.0}
		win = resolve_crop(asset(2000, 2000), profile("p", "1:1"), niyet)
		safe = Rect(0.6, 0.6, 0.3, 0.3)
		self.assertTrue(safe.contains(win.rect), win.as_dict())


class OranVeFitTesti(unittest.TestCase):
	def test_oran_ayristirma(self):
		self.assertAlmostEqual(crop.parse_aspect_ratio("16:9"), 16 / 9)
		self.assertAlmostEqual(crop.parse_aspect_ratio("1:1"), 1.0)
		self.assertAlmostEqual(crop.parse_aspect_ratio(1.75), 1.75)
		self.assertIsNone(crop.parse_aspect_ratio(None))
		self.assertIsNone(crop.parse_aspect_ratio(""))
		self.assertIsNone(crop.parse_aspect_ratio("free"))
		self.assertIsNone(crop.parse_aspect_ratio("0:0"))
		with self.assertRaises(CropError):
			crop.parse_aspect_ratio("abc")

	def test_contain_kirpmaz(self):
		"""`fit='contain'` oranı ZORLAMAZ — pencere taban bölgenin tamamı."""
		niyet = {"focal_x": 0.9, "focal_y": 0.1}
		win = resolve_crop(asset(3000, 1000), profile("product-main", "1:1", fit="contain"), niyet)
		self.assertIsNone(win.target_ratio)
		self.assertAlmostEqual(win.w, 1.0)
		self.assertAlmostEqual(win.h, 1.0)

	def test_contain_guvenli_alani_korur(self):
		niyet = {"safe_x": 0.1, "safe_y": 0.2, "safe_w": 0.5, "safe_h": 0.6,
				 "focal_x": 0.3, "focal_y": 0.4}
		win = resolve_crop(asset(3000, 1000), profile("p", "1:1", fit="contain"), niyet)
		self.assertAlmostEqual(win.w, 0.5)
		self.assertAlmostEqual(win.h, 0.6)

	def test_gecersiz_kaynak_orani_hata(self):
		with self.assertRaises(CropError):
			resolve_crop({"source_ratio": -1}, profile("p", "1:1"), None)

	def test_pikselde_asgari_bir(self):
		"""Çok küçük türevlerde bile genişlik/yükseklik en az 1 piksel."""
		win = resolve_crop(asset(4000, 100), profile("p", "1:1"), None)
		_l, _t, w, h = win.to_pixels(4000, 100)
		self.assertGreaterEqual(w, 1)
		self.assertGreaterEqual(h, 1)


class RectTesti(unittest.TestCase):
	def test_sifir_boyut_reddedilir(self):
		with self.assertRaises(CropError):
			Rect(0.0, 0.0, 0.0, 0.5)

	def test_birim_kareye_sikistirma(self):
		r = Rect(0.9, 0.9, 0.5, 0.5).clamped_to_unit()
		self.assertLessEqual(r.x + r.w, 1.0 + 1e-12)
		self.assertLessEqual(r.y + r.h, 1.0 + 1e-12)

	def test_verify_window_oran_sapmasini_yakalar(self):
		bozuk = CropWindow(x=0.0, y=0.0, w=1.0, h=1.0, method="test",
						   target_ratio=2.0, source_ratio=1.0)
		with self.assertRaises(CropError):
			verify_window(bozuk)


if __name__ == "__main__":
	unittest.main(verbosity=2)

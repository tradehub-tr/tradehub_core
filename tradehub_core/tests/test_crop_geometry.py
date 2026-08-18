"""T-100 — `tradehub_core/media/pipeline/core/crop_geometry.py` testleri.

Yedi grup:

  1. Vektör testi      — 592 vektörün her biri, BAĞIMSIZ referans uygulamasının
                         verdiği değerle <= 0,5 px sapmayla eşleşmeli
  2. Hata vektörleri   — geçersiz girdide `CropGeometryError` ATMALI (sessizce
                         varsayılana düşmek yasak)
  3. TypeScript paritesi — `crop_geometry.ts` aynı vektörlerde aynı sayıyı
                         veriyor mu? node ile GERÇEKTEN koşturulur, ÖLÇÜLÜR
  4. Özellik testi     — 4.000 rastgele girdide pencere daima taban bölge
                         içinde, oran %0,5 toleransında, kenar sıkıştırma sağlam
  5. Çapraz tutarlılık — `crop.py` (normalize) ile `crop_geometry.py` (piksel)
                         aynı pencereyi veriyor mu? İkisi ayrışırsa T-041 ile
                         T-100 farklı kadraj üretir
  6. Ters fonksiyonlar — `focal_from_window` / `zoom_from_base` gidiş-dönüşü
  7. Parite disiplini  — kaynak dosyada `round(` yok, bağımlılık yok, TS ikizi
                         `import` içermiyor. Test edilen şey davranış değil,
                         paritenin bozulmasını KOLAYLAŞTIRAN kod.

`hypothesis` bu ortamda KURULU DEĞİL (`tests/test_crop.py` ile aynı durum).
Özellik testi sabit tohumlu (`random.Random(20260818)`) tekrarlanabilir bir
üreteçle yazıldı: küçültme (shrinking) yok, kapsama ve tekrar edilebilirlik var.

Çalıştırma:

    python3 -m unittest tests.test_crop_geometry -v
    python3 -m unittest discover -s /Users/ahmet/Desktop/istoc/tradehub_core/tests -v
"""

from __future__ import annotations

import json
import math
import random
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.core import crop as crop_intent  # noqa: E402
from tradehub_core.media.pipeline.core import crop_geometry as g  # noqa: E402
from tradehub_core.media.pipeline.core.crop_geometry import (  # noqa: E402
	FIT_INSIDE,
	FIT_OUTSIDE,
	PARITY_TOLERANCE_PX,
	ZOOM_MAX,
	ZOOM_MIN,
	CropGeometryError,
	Rect,
	clamp_window,
	crop_window,
	focal_from_window,
	ratio_fit,
	round_window,
	zoom_base,
	zoom_from_base,
)

VEKTOR_DOSYASI = ROOT / "tradehub_core" / "tests" / "fixtures" / "crop_vectors.json"
TS_KOSUCU = ROOT / "tradehub_core" / "tests" / "tools" / "run_ts_vectors.ts"
KAYNAK_PY = ROOT / "tradehub_core" / "media" / "pipeline" / "core" / "crop_geometry.py"
KAYNAK_TS = ROOT / "tradehub_core" / "media" / "pipeline" / "core" / "crop_geometry.ts"

TOHUM = 20260818

# `crop.py`'nin kabul ettiği oran toleransı — aynı sayıyı burada da kullanıyoruz
# ki iki modül farklı sıkılıkta doğrulanmasın.
ORAN_TOLERANSI = crop_intent.RATIO_TOLERANCE


def _paket() -> dict:
	with open(VEKTOR_DOSYASI, encoding="utf-8") as fh:
		return json.load(fh)


def _rect(d: dict) -> Rect:
	return Rect(d["x"], d["y"], d["w"], d["h"])


def _calistir(v: dict) -> dict:
	"""Vektörü üretim modülüyle koştur; sonucu düz sayı sözlüğüne indir."""
	i = v["in"]
	fn = v["fn"]
	if fn == "cropWindow":
		r = crop_window(i["source_w"], i["source_h"], _rect(i["base"]), i["target_ar"], i["focal_x"], i["focal_y"])
		return {"x": r.x, "y": r.y, "w": r.w, "h": r.h}
	if fn == "clampWindow":
		r = clamp_window(_rect(i["win"]), _rect(i["bounds"]), i["keep_ratio"])
		return {"x": r.x, "y": r.y, "w": r.w, "h": r.h}
	if fn == "ratioFit":
		w, h = ratio_fit(i["w"], i["h"], i["target_ar"], i["mode"])
		return {"w": w, "h": h}
	if fn == "zoomBase":
		r = zoom_base(i["source_w"], i["source_h"], i["zoom"], i["center_x"], i["center_y"])
		return {"x": r.x, "y": r.y, "w": r.w, "h": r.h}
	if fn == "zoomFromBase":
		return {"zoom": zoom_from_base(i["source_w"], i["source_h"], _rect(i["base"]))}
	if fn == "focalFromWindow":
		x, y = focal_from_window(_rect(i["win"]), i["source_w"], i["source_h"])
		return {"x": x, "y": y}
	if fn == "roundWindow":
		box = round_window(_rect(i["win"]), i["source_w"], i["source_h"])
		return {"box0": box[0], "box1": box[1], "box2": box[2], "box3": box[3]}
	raise AssertionError(f"Bilinmeyen fonksiyon: {fn}")


def _beklenen(v: dict) -> dict:
	out = v["out"]
	if v["fn"] == "roundWindow":
		b = out["box"]
		return {"box0": b[0], "box1": b[1], "box2": b[2], "box3": b[3]}
	return dict(out)


class VektorTesti(unittest.TestCase):
	"""592 vektör — üretim modülü, bağımsız referansla aynı sayıyı vermeli.

	Vektörlerin beklenen değerleri `crop_geometry.py` ÇAĞRILARAK üretilmedi;
	`tests/tools/gen_crop_vectors.py` içindeki ayrı bir referans uygulamadan
	geldi. Bu yüzden bu test gerçekten bir şey kanıtlar: iki bağımsız uygulama
	aynı sayıda buluşuyor.
	"""

	@classmethod
	def setUpClass(cls) -> None:
		cls.paket = _paket()
		cls.vektorler = [v for v in cls.paket["vectors"] if not v.get("error")]

	def test_vektor_dosyasi_yeterince_buyuk(self) -> None:
		# T-100 asgarisi 200 vektör.
		self.assertGreaterEqual(len(self.paket["vectors"]), 200)
		self.assertEqual(self.paket["vector_count"], len(self.paket["vectors"]))

	def test_tum_fonksiyonlar_kapsanmis(self) -> None:
		kapsanan = {v["fn"] for v in self.paket["vectors"]}
		for fn in ("cropWindow", "clampWindow", "ratioFit", "zoomBase"):
			self.assertIn(fn, kapsanan, f"{fn} için vektör yok")

	def test_sinir_vakalari_var(self) -> None:
		"""Görev metninin adıyla istediği sınır vakaları dosyada bulunmalı."""
		vakalar = " ".join(v["case"] for v in self.paket["vectors"])
		for imza in ("kare", "cok-genis", "cok-uzun", "sol-ust", "sag-alt", "serbest", "1px"):
			self.assertIn(imza, vakalar, f"sınır vakası eksik: {imza}")

	def test_tum_vektorler_eslesiyor(self) -> None:
		en_buyuk = 0.0
		en_buyuk_id = ""
		hatalar = []
		for v in self.vektorler:
			gercek = _calistir(v)
			bekle = _beklenen(v)
			self.assertEqual(set(gercek), set(bekle), f"{v['id']} alan kümesi farklı")
			sinir = 0.0 if v["fn"] == "roundWindow" else PARITY_TOLERANCE_PX
			for k, beklenen_deger in bekle.items():
				sapma = abs(gercek[k] - beklenen_deger)
				if sapma > en_buyuk:
					en_buyuk = sapma
					en_buyuk_id = f"{v['id']} {v['case']}.{k}"
				if not sapma <= sinir:
					hatalar.append(f"{v['id']} {v['case']}.{k}: beklenen={beklenen_deger} gerçek={gercek[k]} sapma={sapma}")
		self.assertEqual(hatalar, [], "\n".join(hatalar[:20]))
		# Sözleşme 0,5 px; gerçekleşen sapmayı görünür kıl — sessizce
		# 0,49'a tırmanan bir sapma testi geçer ama bir şeyin bozulduğunu söyler.
		print(f"\n  [vektör] {len(self.vektorler)} vektör · en büyük sapma = {en_buyuk} px ({en_buyuk_id or 'yok'})")
		self.assertLessEqual(en_buyuk, PARITY_TOLERANCE_PX)


class HataVektorleriTesti(unittest.TestCase):
	"""Geçersiz girdi SESSİZCE bir varsayılana düşmemeli."""

	def test_hata_vektorleri_atiyor(self) -> None:
		hatalilar = [v for v in _paket()["vectors"] if v.get("error")]
		self.assertGreaterEqual(len(hatalilar), 5)
		for v in hatalilar:
			with self.subTest(vektor=v["id"], vaka=v["case"]):
				with self.assertRaises(CropGeometryError):
					_calistir(v)

	def test_nan_ve_sonsuz_reddediliyor(self) -> None:
		tam = Rect(0.0, 0.0, 100.0, 100.0)
		for kotu in (float("nan"), float("inf"), float("-inf")):
			with self.subTest(deger=kotu):
				with self.assertRaises(CropGeometryError):
					crop_window(100.0, 100.0, tam, 1.0, kotu, 0.5)
				with self.assertRaises(CropGeometryError):
					zoom_base(100.0, 100.0, kotu, 0.5, 0.5)

	def test_sifir_boyutlu_rect_reddediliyor(self) -> None:
		with self.assertRaises(CropGeometryError):
			Rect(0.0, 0.0, 0.0, 10.0)
		with self.assertRaises(CropGeometryError):
			Rect(0.0, 0.0, 10.0, -3.0)


class TypeScriptPariteTesti(unittest.TestCase):
	"""T-100'ün ASIL sözü: TS ve Python aynı sayıyı veriyor mu?

	Bu test iddia etmez, ÖLÇER: `crop_geometry.ts`'i node ile aynı vektörler
	üzerinde koşturur. node yoksa test atlanır ve bunu açıkça söyler — sessizce
	geçmez, çünkü "atlandı" ile "geçti" farklı şeylerdir.
	"""

	def test_ts_ikizi_ayni_sayiyi_veriyor(self) -> None:
		node = shutil.which("node")
		if not node:
			self.skipTest("node bulunamadı — TS paritesi ÖLÇÜLMEDİ")
		sonuc = subprocess.run(
			[node, "--experimental-strip-types", str(TS_KOSUCU)],
			capture_output=True,
			text=True,
			cwd=str(ROOT),
			timeout=180,
		)
		satirlar = [s for s in sonuc.stdout.strip().splitlines() if s.startswith("{")]
		self.assertTrue(satirlar, f"koşucu özet üretmedi:\nSTDOUT:{sonuc.stdout}\nSTDERR:{sonuc.stderr}")
		ozet = json.loads(satirlar[-1])
		print(
			f"\n  [TS parite] {ozet['kosulan']} vektör + {ozet['hata_vakasi']} hata vakası · "
			f"uyuşmazlık = {ozet['uyusmazlik']} · en büyük sapma = {ozet['en_buyuk_sapma_px']} px"
		)
		self.assertEqual(ozet["uyusmazlik"], 0, json.dumps(ozet["ilk_uyusmazliklar"], ensure_ascii=False, indent=2))
		self.assertLessEqual(ozet["en_buyuk_sapma_px"], PARITY_TOLERANCE_PX)
		self.assertEqual(sonuc.returncode, 0)


class OzellikTesti(unittest.TestCase):
	"""4.000 rastgele girdi — değişmezler her zaman geçerli olmalı."""

	def setUp(self) -> None:
		self.rnd = random.Random(TOHUM)

	def _rastgele_kurulum(self):
		sw = float(self.rnd.randint(1, 9000))
		sh = float(self.rnd.randint(1, 9000))
		zoom = self.rnd.choice([1.0, 1.0, self.rnd.uniform(ZOOM_MIN, ZOOM_MAX)])
		base = zoom_base(sw, sh, zoom, self.rnd.random(), self.rnd.random())
		ar = None if self.rnd.random() < 0.1 else math.exp(self.rnd.uniform(-2.5, 2.5))
		return sw, sh, base, ar, self.rnd.random(), self.rnd.random()

	def test_pencere_daima_taban_bolge_icinde(self) -> None:
		for i in range(4000):
			sw, sh, base, ar, fx, fy = self._rastgele_kurulum()
			w = crop_window(sw, sh, base, ar, fx, fy)
			with self.subTest(i=i, sw=sw, sh=sh, ar=ar):
				# Kenar sıkıştırma: odak köşede olsa bile taşma yok.
				self.assertGreaterEqual(w.x, base.x - 1e-6)
				self.assertGreaterEqual(w.y, base.y - 1e-6)
				self.assertLessEqual(w.right, base.right + 1e-6)
				self.assertLessEqual(w.bottom, base.bottom + 1e-6)
				# Kaynağın da dışına çıkmamalı.
				self.assertGreaterEqual(w.x, -1e-6)
				self.assertGreaterEqual(w.y, -1e-6)
				self.assertLessEqual(w.right, sw + 1e-6)
				self.assertLessEqual(w.bottom, sh + 1e-6)

	def test_oran_toleransta(self) -> None:
		sapmalar = []
		for i in range(4000):
			sw, sh, base, ar, fx, fy = self._rastgele_kurulum()
			if ar is None:
				continue
			w = crop_window(sw, sh, base, ar, fx, fy)
			bagil = abs(w.ratio - ar) / ar
			sapmalar.append(bagil)
			with self.subTest(i=i, ar=ar):
				self.assertLessEqual(bagil, ORAN_TOLERANSI)
		print(f"\n  [oran] {len(sapmalar)} örnek · en büyük bağıl oran sapması = {max(sapmalar):.3e}")

	def test_pencere_en_buyuk_olan(self) -> None:
		"""Pencere, taban bölgeye sığan hedef-oranlı EN BÜYÜK dikdörtgen olmalı.

		Bir kenarı taban bölgeye tam değmiyorsa gereğinden küçük kırpmışız
		demektir; kullanıcı elindeki çözünürlüğü boşuna kaybeder.
		"""
		for i in range(2000):
			sw, sh, base, ar, fx, fy = self._rastgele_kurulum()
			if ar is None:
				continue
			w = crop_window(sw, sh, base, ar, fx, fy)
			deger = max(w.w / base.w, w.h / base.h)
			with self.subTest(i=i, ar=ar):
				self.assertGreaterEqual(deger, 1.0 - 1e-9, "pencere gereğinden küçük")

	def test_zoom_base_daima_kaynak_icinde(self) -> None:
		for i in range(2000):
			sw = float(self.rnd.randint(1, 9000))
			sh = float(self.rnd.randint(1, 9000))
			z = self.rnd.uniform(-5.0, 50.0)
			b = zoom_base(sw, sh, z, self.rnd.uniform(-2, 3), self.rnd.uniform(-2, 3))
			with self.subTest(i=i):
				self.assertGreaterEqual(b.x, -1e-9)
				self.assertGreaterEqual(b.y, -1e-9)
				self.assertLessEqual(b.right, sw + 1e-9)
				self.assertLessEqual(b.bottom, sh + 1e-9)
				self.assertGreater(b.w, 0.0)
				self.assertGreater(b.h, 0.0)

	def test_clamp_window_ici_pencereyi_degistirmiyor(self) -> None:
		"""Sınırların içindeki pencere BİT DÜZEYİNDE aynı dönmeli.

		`crop_window` tabanı önce `clamp_window`'dan geçirir; bu çağrı geçerli
		bir tabanda no-op değilse parite vektörleri kayar.
		"""
		sinir = Rect(0.0, 0.0, 1120.0, 747.0)
		for i in range(1000):
			w = self.rnd.uniform(1.0, 1120.0)
			h = self.rnd.uniform(1.0, 747.0)
			x = self.rnd.uniform(0.0, 1120.0 - w)
			y = self.rnd.uniform(0.0, 747.0 - h)
			win = Rect(x, y, w, h)
			out = clamp_window(win, sinir)
			with self.subTest(i=i):
				self.assertEqual(out.as_tuple(), win.as_tuple())

	def test_yuvarlanmis_kutu_kaynak_icinde(self) -> None:
		for i in range(2000):
			sw, sh, base, ar, fx, fy = self._rastgele_kurulum()
			w = crop_window(sw, sh, base, ar, fx, fy)
			left, top, bw, bh = round_window(w, sw, sh)
			with self.subTest(i=i):
				self.assertGreaterEqual(left, 0)
				self.assertGreaterEqual(top, 0)
				self.assertGreaterEqual(bw, 1)
				self.assertGreaterEqual(bh, 1)
				self.assertLessEqual(left + bw, int(math.floor(sw + 0.5)))
				self.assertLessEqual(top + bh, int(math.floor(sh + 0.5)))


class KenarSikistirmaTesti(unittest.TestCase):
	"""Odak kenarda/köşede — pencere yapışmalı, taşmamalı."""

	def test_odak_sol_ust_kosede(self) -> None:
		w = crop_window(4000.0, 3000.0, Rect(0.0, 0.0, 4000.0, 3000.0), 1.0, 0.0, 0.0)
		self.assertAlmostEqual(w.x, 0.0, places=9)
		self.assertAlmostEqual(w.y, 0.0, places=9)
		self.assertAlmostEqual(w.w, 3000.0, places=9)

	def test_odak_sag_alt_kosede(self) -> None:
		w = crop_window(4000.0, 3000.0, Rect(0.0, 0.0, 4000.0, 3000.0), 1.0, 1.0, 1.0)
		self.assertAlmostEqual(w.right, 4000.0, places=9)
		self.assertAlmostEqual(w.bottom, 3000.0, places=9)

	def test_odak_araligin_disinda_sikistiriliyor(self) -> None:
		icerde = crop_window(4000.0, 3000.0, Rect(0.0, 0.0, 4000.0, 3000.0), 1.0, 1.0, 1.0)
		disarda = crop_window(4000.0, 3000.0, Rect(0.0, 0.0, 4000.0, 3000.0), 1.0, 9.9, 4.2)
		self.assertEqual(icerde.as_tuple(), disarda.as_tuple())

	def test_cok_genis_kaynakta_kare_hedef(self) -> None:
		"""8:1 kaynaktan 1:1 kırpma — yükseklik dolar, genişlik kısılır."""
		w = crop_window(4000.0, 500.0, Rect(0.0, 0.0, 4000.0, 500.0), 1.0, 0.5, 0.5)
		self.assertAlmostEqual(w.w, 500.0, places=9)
		self.assertAlmostEqual(w.h, 500.0, places=9)
		self.assertAlmostEqual(w.x, 1750.0, places=9)

	def test_cok_uzun_kaynakta_genis_hedef(self) -> None:
		"""1:8 kaynaktan 16:9 kırpma — genişlik dolar, yükseklik kısılır."""
		ar = 16.0 / 9.0
		w = crop_window(500.0, 4000.0, Rect(0.0, 0.0, 500.0, 4000.0), ar, 0.5, 0.5)
		self.assertAlmostEqual(w.w, 500.0, places=9)
		self.assertAlmostEqual(w.h, 500.0 / ar, places=9)

	def test_serbest_oran_taban_bolgeyi_dondurur(self) -> None:
		base = zoom_base(2592.0, 1936.0, 3.0, 0.25, 0.75)
		w = crop_window(2592.0, 1936.0, base, None, 0.5, 0.5)
		self.assertEqual(w.as_tuple(), base.as_tuple())

	def test_bir_piksel_kaynak(self) -> None:
		w = crop_window(1.0, 1.0, Rect(0.0, 0.0, 1.0, 1.0), 1.0, 0.5, 0.5)
		self.assertEqual(w.as_tuple(), (0.0, 0.0, 1.0, 1.0))
		self.assertEqual(round_window(w, 1.0, 1.0), (0, 0, 1, 1))


class CaprazTutarlilikTesti(unittest.TestCase):
	"""`crop.py` (normalize) ile `crop_geometry.py` (piksel) aynı pencereyi vermeli.

	İkisi ayrışırsa T-041'in çözdüğü niyet ile T-100'ün çizdiği kadraj farklı
	olur: kullanıcı Crop Studio'da bir şey görür, boru hattı başka bir şey
	keser. Bu testin düşmesi, iki modülden birinin matematiğinin kaydığı
	anlamına gelir.
	"""

	def test_odak_seviyesi_ayni_pencere(self) -> None:
		rnd = random.Random(TOHUM + 1)
		en_buyuk = 0.0
		for i in range(1500):
			sw = float(rnd.randint(1, 9000))
			sh = float(rnd.randint(1, 9000))
			fx, fy = rnd.random(), rnd.random()
			ar = math.exp(rnd.uniform(-2.0, 2.0))

			# T-041 yolu: normalize uzayda öncelik zinciri (odak seviyesi).
			nrm = crop_intent.resolve_crop(
				{"width": sw, "height": sh},
				{"profile_key": "t100", "aspect_ratio_value": ar, "fit": "cover"},
				{"focal_x": fx, "focal_y": fy},
			)
			self.assertEqual(nrm.method, crop_intent.METHOD_FOCAL)

			# T-100 yolu: piksel uzayında doğrudan geometri.
			px = crop_window(sw, sh, Rect(0.0, 0.0, sw, sh), ar, fx, fy)

			for beklenen_deger, gercek in (
				(nrm.x * sw, px.x),
				(nrm.y * sh, px.y),
				(nrm.w * sw, px.w),
				(nrm.h * sh, px.h),
			):
				sapma = abs(beklenen_deger - gercek)
				en_buyuk = max(en_buyuk, sapma)
				with self.subTest(i=i, sw=sw, sh=sh, ar=ar):
					self.assertLessEqual(sapma, PARITY_TOLERANCE_PX)
		print(f"\n  [çapraz] crop.py ↔ crop_geometry.py en büyük sapma = {en_buyuk:.6e} px")

	def test_piksel_kutulari_da_ayni(self) -> None:
		"""Yuvarlanmış kutu da aynı olmalı — asıl kesilen şey odur."""
		rnd = random.Random(TOHUM + 2)
		farkli = 0
		toplam = 0
		for _ in range(800):
			sw = float(rnd.randint(16, 9000))
			sh = float(rnd.randint(16, 9000))
			fx, fy = rnd.random(), rnd.random()
			ar = math.exp(rnd.uniform(-1.5, 1.5))
			a = crop_intent.resolve_crop_pixels(
				{"width": sw, "height": sh},
				{"profile_key": "t100", "aspect_ratio_value": ar, "fit": "cover"},
				int(sw),
				int(sh),
				{"focal_x": fx, "focal_y": fy},
			)
			b = round_window(crop_window(sw, sh, Rect(0.0, 0.0, sw, sh), ar, fx, fy), sw, sh)
			toplam += 1
			if a != b:
				farkli += 1
				# 1 px'lik yuvarlama farkı kabul edilir; daha fazlası değil.
				for x, y in zip(a, b):
					self.assertLessEqual(abs(x - y), 1, f"kutu farkı >1 px: {a} vs {b}")
		print(f"\n  [çapraz-kutu] {toplam} örnek · 1 px yuvarlama farkı olan = {farkli}")


class TersFonksiyonTesti(unittest.TestCase):
	"""Gidiş-dönüş: pencere → odak → pencere aynı yere düşmeli."""

	def test_focal_gidis_donus(self) -> None:
		rnd = random.Random(TOHUM + 3)
		for i in range(1000):
			sw = float(rnd.randint(16, 9000))
			sh = float(rnd.randint(16, 9000))
			ar = math.exp(rnd.uniform(-2.0, 2.0))
			fx, fy = rnd.random(), rnd.random()
			tam = Rect(0.0, 0.0, sw, sh)
			bir = crop_window(sw, sh, tam, ar, fx, fy)
			gfx, gfy = focal_from_window(bir, sw, sh)
			iki = crop_window(sw, sh, tam, ar, gfx, gfy)
			with self.subTest(i=i):
				for a, b in zip(bir.as_tuple(), iki.as_tuple()):
					self.assertLessEqual(abs(a - b), PARITY_TOLERANCE_PX)

	def test_zoom_gidis_donus(self) -> None:
		rnd = random.Random(TOHUM + 4)
		for i in range(500):
			sw = float(rnd.randint(16, 9000))
			sh = float(rnd.randint(16, 9000))
			z = rnd.uniform(ZOOM_MIN, ZOOM_MAX)
			b = zoom_base(sw, sh, z, rnd.random(), rnd.random())
			geri = zoom_from_base(sw, sh, b)
			with self.subTest(i=i):
				# 1 px tabanına dayanmadıysa zoom birebir geri okunmalı.
				if b.w > g.MIN_EDGE_PX + 1e-9 and b.h > g.MIN_EDGE_PX + 1e-9:
					self.assertAlmostEqual(geri, z, places=6)


class RatioFitTesti(unittest.TestCase):
	def test_inside_kutunun_icinde(self) -> None:
		w, h = ratio_fit(1000.0, 1000.0, 2.0, FIT_INSIDE)
		self.assertAlmostEqual(w, 1000.0)
		self.assertAlmostEqual(h, 500.0)

	def test_outside_kutuyu_kapsar(self) -> None:
		w, h = ratio_fit(1000.0, 1000.0, 2.0, FIT_OUTSIDE)
		self.assertAlmostEqual(w, 2000.0)
		self.assertAlmostEqual(h, 1000.0)

	def test_serbest_oran_degistirmiyor(self) -> None:
		self.assertEqual(ratio_fit(123.0, 456.0, None), (123.0, 456.0))

	def test_inside_asla_tasmaz(self) -> None:
		rnd = random.Random(TOHUM + 5)
		for _ in range(2000):
			bw = rnd.uniform(1.0, 9000.0)
			bh = rnd.uniform(1.0, 9000.0)
			ar = math.exp(rnd.uniform(-3.0, 3.0))
			w, h = ratio_fit(bw, bh, ar, FIT_INSIDE)
			self.assertLessEqual(w, bw + 1e-9)
			self.assertLessEqual(h, bh + 1e-9)


class YuvarlamaTesti(unittest.TestCase):
	"""Python `round()` bankacı yuvarlaması yapar; JS `Math.round` yapmaz."""

	def test_yarim_yukari_yuvarlaniyor(self) -> None:
		# round(0.5) == 0 (bankacı) ama biz 1 istiyoruz — JS ile aynı olsun diye.
		self.assertEqual(round_window(Rect(0.5, 2.5, 10.5, 10.5)), (1, 3, 11, 11))
		self.assertEqual(round(0.5), 0, "Python hâlâ bankacı yuvarlaması yapıyor — not güncel")

	def test_kutu_kaynagi_asmiyor(self) -> None:
		box = round_window(Rect(99.7, 99.7, 1.4, 1.4), 100.0, 100.0)
		self.assertEqual(box[0] + box[2], 100)
		self.assertEqual(box[1] + box[3], 100)


class PariteDisiplinTesti(unittest.TestCase):
	"""Paritenin bozulmasını kolaylaştıran kod kalıplarını yakala.

	Davranış değil, kaynak metni test edilir. Sebep: bu iki dosyanın ayrışması
	sessiz bir hatadır ve testler o ayrışmayı ancak vektörler güncellenirse
	görür. Bu sınıf, ayrışmanın en olası dört yolunu peşinen kapatır.
	"""

	def test_python_round_kullanmiyor(self) -> None:
		"""Yerleşik `round()` ÇAĞRISI olmamalı.

		Metin araması değil AST kullanılıyor: docstring'de geçen `round(0.5)`
		bir çağrı değildir ve testi düşürmemeli. Aranan şey gerçek bir
		`Call(func=Name('round'))` düğümü.
		"""
		import ast

		agac = ast.parse(KAYNAK_PY.read_text(encoding="utf-8"))
		for dugum in ast.walk(agac):
			if isinstance(dugum, ast.Call) and isinstance(dugum.func, ast.Name) and dugum.func.id == "round":
				self.fail(
					f"crop_geometry.py:{dugum.lineno} — yerleşik round() çağrılmış; "
					"Python bankacı yuvarlaması yapar, JS Math.round yapmaz, ikisi ayrışır"
				)

	def test_round_denetimi_gercekten_yakaliyor(self) -> None:
		"""Denetimin kendisi çalışıyor mu? Bozuk bir örnekte YAKALAMALI.

		Yeşil kalan ama hiçbir şey ölçmeyen bir koruma, korumasızlıktan
		kötüdür — çünkü koruma var sanılır.
		"""
		import ast

		agac = ast.parse("def f(v):\n\treturn round(v)\n")
		bulundu = any(
			isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "round"
			for d in ast.walk(agac)
		)
		self.assertTrue(bulundu, "round() denetimi bozuk — bozuk örneği bile yakalamıyor")

	def test_python_bagimliligi_yok(self) -> None:
		metin = KAYNAK_PY.read_text(encoding="utf-8")
		for yasak in ("import frappe", "from frappe", "import PIL", "import numpy", "from PIL"):
			self.assertNotIn(yasak, metin, f"crop_geometry.py bağımsız olmalı: {yasak}")

	def test_ts_import_icermiyor(self) -> None:
		metin = KAYNAK_TS.read_text(encoding="utf-8")
		kod = [s for s in metin.splitlines() if s.strip().startswith("import ")]
		self.assertEqual(kod, [], "crop_geometry.ts bağımsız olmalı — import satırı bulundu")

	def test_iki_dosyada_ayni_sabitler(self) -> None:
		"""Sabitler iki dosyada da aynı sayı olmalı — parite oradan başlar."""
		ts = KAYNAK_TS.read_text(encoding="utf-8")
		for ad, deger in (
			("ZOOM_MIN", ZOOM_MIN),
			("ZOOM_MAX", ZOOM_MAX),
			("MIN_EDGE_PX", g.MIN_EDGE_PX),
			("PARITY_TOLERANCE_PX", PARITY_TOLERANCE_PX),
		):
			self.assertIn(f"export const {ad} = {deger}", ts, f"TS'de {ad} = {deger} bulunamadı")

	def test_ayni_fonksiyon_adlari(self) -> None:
		ts = KAYNAK_TS.read_text(encoding="utf-8")
		for ad in ("cropWindow", "clampWindow", "ratioFit", "zoomBase", "zoomFromBase", "focalFromWindow", "roundWindow"):
			self.assertIn(f"export function {ad}(", ts, f"TS'de {ad} yok")
			self.assertTrue(hasattr(g, ad), f"Python'da {ad} takma adı yok")


if __name__ == "__main__":
	unittest.main(verbosity=2)

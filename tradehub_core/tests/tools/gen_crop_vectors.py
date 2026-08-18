"""T-100 — `tradehub_core/tests/fixtures/crop_vectors.json` üreteci.

**Neden ayrı bir referans uygulaması var.** Vektörleri `crop_geometry.py`'yi
çağırarak üretseydik, `test_crop_geometry.py` hiçbir şey kanıtlamazdı: modül
kendi çıktısıyla karşılaştırılır, hangi hatayı yaparsa yapsın testi geçerdi.
Bu yüzden aşağıdaki `ref_*` fonksiyonları **bağımsız** yazıldı — kaynak
dokümanın `docs/simulator.html::cropWindow()` JS'inden ve ilk ilkelerden
düz transkripsiyon; üretim modülünün soyutlamalarını (Rect, clamp, ratio_fit)
KULLANMAZLAR. İki uygulama aynı sayıyı veriyorsa sayı muhtemelen doğrudur;
vermiyorsa biri yanlıştır ve test bunu söyler.

Vektörler ayrıca TS ikizini bağlar: `tests/tools/run_ts_vectors.ts` aynı
dosyayı okuyup `crop_geometry.ts` ile koşar. Böylece tek bir JSON üç uygulamayı
(referans, Python, TypeScript) birbirine kilitler.

Çalıştırma:

    python3 tests/tools/gen_crop_vectors.py

Çıktı deterministiktir (sabit tohum `20260818`); aynı kod aynı dosyayı üretir,
`git diff` gürültüsü olmaz.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Optional, Tuple

TOHUM = 20260818

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CIKTI = FIXTURES / "crop_vectors.json"

# ─────────────────────────────────────────────────────────────────────────────
# BAĞIMSIZ referans uygulaması — crop_geometry'yi import ETMEZ
# ─────────────────────────────────────────────────────────────────────────────

Kutu = Tuple[float, float, float, float]


def ref_clamp(v: float, lo: float, hi: float) -> float:
	if hi < lo:
		return lo
	return lo if v < lo else (hi if v > hi else v)


def ref_ratio_fit(w: float, h: float, ar: Optional[float], mode: str = "inside") -> Tuple[float, float]:
	"""Orana oturtma — düz transkripsiyon."""
	if ar is None:
		return (w, h)
	if mode == "inside":
		if w / h > ar:
			oh = h
			ow = oh * ar
		else:
			ow = w
			oh = ow / ar
		return (min(ow, w), min(oh, h))
	if w / h > ar:
		ow = w
		oh = ow / ar
	else:
		oh = h
		ow = oh * ar
	return (max(ow, w), max(oh, h))


def ref_clamp_window(win: Kutu, bounds: Kutu, keep_ratio: bool = False) -> Kutu:
	wx, wy, ww, wh = win
	bx, by, bw, bh = bounds
	if keep_ratio:
		s = 1.0
		if ww > bw:
			s = bw / ww
		if wh > bh:
			s2 = bh / wh
			if s2 < s:
				s = s2
		if s < 1.0:
			ww = min(ww * s, bw)
			wh = min(wh * s, bh)
	else:
		ww = min(ww, bw)
		wh = min(wh, bh)
	return (ref_clamp(wx, bx, bx + bw - ww), ref_clamp(wy, by, by + bh - wh), ww, wh)


def ref_zoom_base(sw: float, sh: float, zoom: float, cx: float, cy: float) -> Kutu:
	z = ref_clamp(zoom, 1.0, 16.0)
	bw = sw / z
	bh = sh / z
	bw = min(max(bw, min(1.0, sw)), sw)
	bh = min(max(bh, min(1.0, sh)), sh)
	px = ref_clamp(cx, 0.0, 1.0) * sw
	py = ref_clamp(cy, 0.0, 1.0) * sh
	return (ref_clamp(px - bw / 2.0, 0.0, sw - bw), ref_clamp(py - bh / 2.0, 0.0, sh - bh), bw, bh)


def ref_crop_window(sw: float, sh: float, base: Kutu, ar: Optional[float], fx: float, fy: float) -> Kutu:
	"""Simülatörün `cropWindow()`'u — piksel uzayında, birebir.

	Referans JS (kaynak doküman `docs/simulator.html`):

	    if (bw / bh > targetAR) { h = bh; w = h * targetAR; }
	    else                    { w = bw; h = w / targetAR; }
	    let x = S.focal.x*W - w/2;
	    let y = S.focal.y*H - h/2;
	    x = clamp(x, bx, bx + bw - w);
	    y = clamp(y, by, by + bh - h);
	"""
	bx, by, bw, bh = ref_clamp_window(base, (0.0, 0.0, sw, sh))
	if ar is None:
		return (bx, by, bw, bh)
	w, h = ref_ratio_fit(bw, bh, ar, "inside")
	x = ref_clamp(fx, 0.0, 1.0) * sw - w / 2.0
	y = ref_clamp(fy, 0.0, 1.0) * sh - h / 2.0
	return (ref_clamp(x, bx, bx + bw - w), ref_clamp(y, by, by + bh - h), w, h)


def ref_focal_from_window(win: Kutu, sw: float, sh: float) -> Tuple[float, float]:
	x, y, w, h = win
	return (ref_clamp((x + w / 2.0) / sw, 0.0, 1.0), ref_clamp((y + h / 2.0) / sh, 0.0, 1.0))


def ref_zoom_from_base(sw: float, sh: float, base: Kutu) -> float:
	return ref_clamp(sw / base[2], 1.0, 16.0)


def ref_round_window(win: Kutu, sw: Optional[float] = None, sh: Optional[float] = None):
	x, y, w, h = win
	left = math.floor(x + 0.5)
	top = math.floor(y + 0.5)
	rw = max(1, math.floor(w + 0.5))
	rh = max(1, math.floor(h + 0.5))
	if sw is not None and sh is not None:
		isw = math.floor(sw + 0.5)
		ish = math.floor(sh + 0.5)
		rw = min(rw, isw)
		rh = min(rh, ish)
		left = min(left, isw - rw)
		top = min(top, ish - rh)
	return [max(0, left), max(0, top), rw, rh]


# ─────────────────────────────────────────────────────────────────────────────
# Girdi uzayı — CANLI ÖLÇÜLMÜŞ dağılımdan seçildi
# ─────────────────────────────────────────────────────────────────────────────
#
# Kaynak boyutları uydurma değil: envanter ölçümünden (4.958 dosya) geliyor.
#   kısa kenar p50=1.120 · p90=2.160 · p99=4.480
#   MP p50=1,56 · p90=5,01 · p99=29,21 · MAX=72,71
#   en büyük tek görsel 32,5 MP
# Dejenere ve uç vakalar (1x1, 8:1, 1:8) ölçümden gelmiyor; sınır davranışını
# kilitlemek için bilinçli eklendi.

KAYNAKLAR = [
	("kare-p50", 1120, 1120),
	("kare-kucuk", 256, 256),
	("kare-1px", 1, 1),
	("tipik-p50", 1120, 747),  # 3:2 civarı, 0,84 MP
	("tipik-portre", 747, 1120),
	("p90", 2592, 1936),  # 5,02 MP
	("p99", 4480, 6521),  # 29,21 MP, portre
	("maks-olculen", 9000, 8079),  # 72,71 MP
	("en-buyuk-tek", 6500, 5000),  # 32,5 MP
	("cok-genis", 4000, 500),  # 8:1
	("cok-uzun", 500, 4000),  # 1:8
	("panorama", 8000, 1000),
	("ince-serit", 3, 2000),
]

# Odaklar — köşeler ve kenarlar dahil. Kenar sıkıştırmanın tek test edildiği yer
# burasıdır: odak (0,0) iken pencere sol üste yapışmalı, dışarı taşmamalı.
ODAKLAR = [
	("merkez", 0.5, 0.5),
	("sol-ust", 0.0, 0.0),
	("sag-alt", 1.0, 1.0),
	("sag-ust", 1.0, 0.0),
	("sol-alt", 0.0, 1.0),
	("sol-kenar", 0.0, 0.5),
	("sag-kenar", 1.0, 0.5),
	("ust-kenar", 0.5, 0.0),
	("alt-kenar", 0.5, 1.0),
	("ucuncu", 0.3333333333333333, 0.6666666666666666),
	("asimetrik", 0.13, 0.87),
	("tasan-negatif", -0.4, 1.7),  # sıkıştırılmalı
]

# Hedef oranlar — 9 slot politikasında geçenler + serbest + uçlar.
ORANLAR = [
	("serbest", None),
	("1:1", 1.0),
	("16:9", 16.0 / 9.0),
	("9:16", 9.0 / 16.0),
	("4:3", 4.0 / 3.0),
	("3:4", 3.0 / 4.0),
	("3:2", 3.0 / 2.0),
	("2:1", 2.0),
	("21:9", 21.0 / 9.0),
	("1:4", 0.25),
	("4:1", 4.0),
	("altin", 1.618033988749895),
]

ZOOMLAR = [("z1", 1.0), ("z1.5", 1.5), ("z2", 2.0), ("z3.7", 3.7), ("z8", 8.0), ("z16", 16.0), ("z-tasan", 40.0), ("z-alt", 0.25)]


def kutu_sozluk(k: Kutu) -> dict:
	return {"x": k[0], "y": k[1], "w": k[2], "h": k[3]}


def uret() -> dict:
	rnd = random.Random(TOHUM)
	vektorler = []
	sayac = {"n": 0}

	def ekle(fn: str, vaka: str, girdi: dict, cikti) -> None:
		sayac["n"] += 1
		vektorler.append(
			{
				"id": f"V{sayac['n']:04d}",
				"fn": fn,
				"case": vaka,
				"in": girdi,
				"out": cikti,
			}
		)

	def ekle_hata(fn: str, vaka: str, girdi: dict) -> None:
		sayac["n"] += 1
		vektorler.append({"id": f"V{sayac['n']:04d}", "fn": fn, "case": vaka, "in": girdi, "error": True})

	# ── ratioFit ────────────────────────────────────────────────────────
	for kad, kw, kh in KAYNAKLAR:
		for oad, ar in ORANLAR[:6]:
			for mod in ("inside", "outside"):
				if ar is None and mod == "outside":
					continue
				w, h = ref_ratio_fit(float(kw), float(kh), ar, mod)
				ekle(
					"ratioFit",
					f"ratioFit/{kad}/{oad}/{mod}",
					{"w": float(kw), "h": float(kh), "target_ar": ar, "mode": mod},
					{"w": w, "h": h},
				)

	# ── zoomBase ────────────────────────────────────────────────────────
	for kad, kw, kh in KAYNAKLAR:
		for zad, z in ZOOMLAR:
			cx, cy = (0.5, 0.5) if zad in ("z1", "z2") else (rnd.random(), rnd.random())
			out = ref_zoom_base(float(kw), float(kh), z, cx, cy)
			ekle(
				"zoomBase",
				f"zoomBase/{kad}/{zad}",
				{"source_w": float(kw), "source_h": float(kh), "zoom": z, "center_x": cx, "center_y": cy},
				kutu_sozluk(out),
			)
	# Pan merkezi köşede — taban bölge kenara yapışmalı, taşmamalı.
	for cx, cy in ((0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (1.0, 0.0), (-2.0, 3.0)):
		out = ref_zoom_base(2592.0, 1936.0, 4.0, cx, cy)
		ekle(
			"zoomBase",
			f"zoomBase/pan-kose/{cx}x{cy}",
			{"source_w": 2592.0, "source_h": 1936.0, "zoom": 4.0, "center_x": cx, "center_y": cy},
			kutu_sozluk(out),
		)

	# ── cropWindow · tam çarpım (kritik altküme) ────────────────────────
	kritik_kaynak = [k for k in KAYNAKLAR if k[0] in ("kare-p50", "cok-genis", "cok-uzun", "tipik-p50", "maks-olculen")]
	kritik_odak = [o for o in ODAKLAR if o[0] in ("merkez", "sol-ust", "sag-alt", "sag-kenar", "tasan-negatif")]
	kritik_oran = [o for o in ORANLAR if o[0] in ("serbest", "1:1", "16:9", "9:16", "4:1", "1:4")]
	for kad, kw, kh in kritik_kaynak:
		for oad, fx, fy in kritik_odak:
			for rad, ar in kritik_oran:
				base = (0.0, 0.0, float(kw), float(kh))
				out = ref_crop_window(float(kw), float(kh), base, ar, fx, fy)
				ekle(
					"cropWindow",
					f"cropWindow/tam/{kad}/{oad}/{rad}",
					{
						"source_w": float(kw),
						"source_h": float(kh),
						"base": kutu_sozluk(base),
						"target_ar": ar,
						"focal_x": fx,
						"focal_y": fy,
					},
					kutu_sozluk(out),
				)

	# ── cropWindow · zoomlu taban (zincirleme) ──────────────────────────
	for kad, kw, kh in KAYNAKLAR:
		for zad, z in (("z1.5", 1.5), ("z3.7", 3.7), ("z8", 8.0)):
			cx, cy = rnd.random(), rnd.random()
			base = ref_zoom_base(float(kw), float(kh), z, cx, cy)
			rad, ar = ORANLAR[rnd.randrange(len(ORANLAR))]
			oad, fx, fy = ODAKLAR[rnd.randrange(len(ODAKLAR))]
			out = ref_crop_window(float(kw), float(kh), base, ar, fx, fy)
			ekle(
				"cropWindow",
				f"cropWindow/zoomlu/{kad}/{zad}/{rad}/{oad}",
				{
					"source_w": float(kw),
					"source_h": float(kh),
					"base": kutu_sozluk(base),
					"target_ar": ar,
					"focal_x": fx,
					"focal_y": fy,
				},
				kutu_sozluk(out),
			)

	# ── cropWindow · rastgele (kaba kuvvet kapsama) ─────────────────────
	for i in range(60):
		kw = rnd.randint(1, 9000)
		kh = rnd.randint(1, 9000)
		z = rnd.choice([1.0, 1.0, rnd.uniform(1.0, 16.0)])
		base = ref_zoom_base(float(kw), float(kh), z, rnd.random(), rnd.random())
		ar = None if i % 11 == 0 else rnd.uniform(0.1, 10.0)
		fx, fy = rnd.random(), rnd.random()
		out = ref_crop_window(float(kw), float(kh), base, ar, fx, fy)
		ekle(
			"cropWindow",
			f"cropWindow/rastgele/{i:02d}",
			{
				"source_w": float(kw),
				"source_h": float(kh),
				"base": kutu_sozluk(base),
				"target_ar": ar,
				"focal_x": fx,
				"focal_y": fy,
			},
			kutu_sozluk(out),
		)

	# ── clampWindow ─────────────────────────────────────────────────────
	sinir = (0.0, 0.0, 1120.0, 747.0)
	clamp_vakalari = [
		("ici", (100.0, 100.0, 400.0, 300.0)),
		("sol-tasan", (-200.0, 100.0, 400.0, 300.0)),
		("sag-tasan", (1000.0, 100.0, 400.0, 300.0)),
		("ust-tasan", (100.0, -500.0, 400.0, 300.0)),
		("alt-tasan", (100.0, 700.0, 400.0, 300.0)),
		("cok-genis", (-50.0, 10.0, 5000.0, 300.0)),
		("cok-buyuk", (-50.0, -50.0, 5000.0, 5000.0)),
		("tam-oturan", (0.0, 0.0, 1120.0, 747.0)),
		("bir-ulp-buyuk", (0.0, 0.0, 1120.0000000001, 747.0)),
		("kose-sol-ust", (-9999.0, -9999.0, 10.0, 10.0)),
		("kose-sag-alt", (9999.0, 9999.0, 10.0, 10.0)),
	]
	for vad, win in clamp_vakalari:
		for kr in (False, True):
			out = ref_clamp_window(win, sinir, kr)
			ekle(
				"clampWindow",
				f"clampWindow/{vad}/{'kilitli' if kr else 'serbest'}",
				{"win": kutu_sozluk(win), "bounds": kutu_sozluk(sinir), "keep_ratio": kr},
				kutu_sozluk(out),
			)
	# Kaydırılmış sınır (zoomlu taban içinde tutamak çekme)
	kaydirilmis = (300.0, 200.0, 500.0, 400.0)
	for vad, win in (("ic", (350.0, 250.0, 100.0, 80.0)), ("sol", (0.0, 0.0, 100.0, 80.0)), ("buyuk", (0.0, 0.0, 900.0, 900.0))):
		for kr in (False, True):
			out = ref_clamp_window(win, kaydirilmis, kr)
			ekle(
				"clampWindow",
				f"clampWindow/kaydirilmis/{vad}/{'kilitli' if kr else 'serbest'}",
				{"win": kutu_sozluk(win), "bounds": kutu_sozluk(kaydirilmis), "keep_ratio": kr},
				kutu_sozluk(out),
			)

	# ── roundWindow ─────────────────────────────────────────────────────
	round_vakalari = [
		("yarim-yukari", (0.5, 0.5, 10.5, 10.5), 100.0, 100.0),
		("negatif-yarim", (-0.5, -0.5, 10.5, 10.5), 100.0, 100.0),
		("bankaci-tuzagi", (2.5, 3.5, 4.5, 5.5), 100.0, 100.0),
		("sag-tasma", (99.7, 99.7, 1.4, 1.4), 100.0, 100.0),
		("kucuk-pencere", (10.2, 10.2, 0.3, 0.3), 100.0, 100.0),
		("sinirsiz", (12.34, 56.78, 90.12, 34.56), None, None),
		("buyuk", (4499.5, 3000.49, 2000.5, 1999.5), 9000.0, 8079.0),
	]
	for vad, win, sw, sh in round_vakalari:
		out = ref_round_window(win, sw, sh)
		ekle(
			"roundWindow",
			f"roundWindow/{vad}",
			{"win": kutu_sozluk(win), "source_w": sw, "source_h": sh},
			{"box": out},
		)

	# ── focalFromWindow · zoomFromBase (ters fonksiyonlar) ──────────────
	for kad, kw, kh in KAYNAKLAR[:8]:
		for zad, z in (("z1", 1.0), ("z2", 2.0), ("z6.5", 6.5)):
			base = ref_zoom_base(float(kw), float(kh), z, rnd.random(), rnd.random())
			fx, fy = ref_focal_from_window(base, float(kw), float(kh))
			ekle(
				"focalFromWindow",
				f"focalFromWindow/{kad}/{zad}",
				{"win": kutu_sozluk(base), "source_w": float(kw), "source_h": float(kh)},
				{"x": fx, "y": fy},
			)
			ekle(
				"zoomFromBase",
				f"zoomFromBase/{kad}/{zad}",
				{"source_w": float(kw), "source_h": float(kh), "base": kutu_sozluk(base)},
				{"zoom": ref_zoom_from_base(float(kw), float(kh), base)},
			)

	# ── Hata vakaları — iki dilde de ATMALI ─────────────────────────────
	ekle_hata("cropWindow", "hata/kaynak-sifir", {"source_w": 0.0, "source_h": 100.0, "base": kutu_sozluk((0.0, 0.0, 10.0, 10.0)), "target_ar": 1.0, "focal_x": 0.5, "focal_y": 0.5})
	ekle_hata("cropWindow", "hata/kaynak-negatif", {"source_w": -10.0, "source_h": 100.0, "base": kutu_sozluk((0.0, 0.0, 10.0, 10.0)), "target_ar": 1.0, "focal_x": 0.5, "focal_y": 0.5})
	ekle_hata("cropWindow", "hata/oran-sifir", {"source_w": 100.0, "source_h": 100.0, "base": kutu_sozluk((0.0, 0.0, 10.0, 10.0)), "target_ar": 0.0, "focal_x": 0.5, "focal_y": 0.5})
	ekle_hata("cropWindow", "hata/oran-negatif", {"source_w": 100.0, "source_h": 100.0, "base": kutu_sozluk((0.0, 0.0, 10.0, 10.0)), "target_ar": -1.5, "focal_x": 0.5, "focal_y": 0.5})
	ekle_hata("ratioFit", "hata/genislik-sifir", {"w": 0.0, "h": 10.0, "target_ar": 1.0, "mode": "inside"})
	ekle_hata("ratioFit", "hata/yukseklik-negatif", {"w": 10.0, "h": -5.0, "target_ar": 1.0, "mode": "inside"})
	ekle_hata("ratioFit", "hata/bilinmeyen-kip", {"w": 10.0, "h": 10.0, "target_ar": 1.0, "mode": "kapak"})
	ekle_hata("zoomBase", "hata/kaynak-sifir", {"source_w": 0.0, "source_h": 100.0, "zoom": 2.0, "center_x": 0.5, "center_y": 0.5})

	return {
		"schema_version": "1.0.0",
		"gorev": "T-100",
		"aciklama": (
			"Crop Studio geometri parite vektörleri. Üç uygulamayı bağlar: "
			"tests/tools/gen_crop_vectors.py içindeki bağımsız referans (bu dosyayı üretti), "
			"tradehub_core/media/pipeline/core/crop_geometry.py ve tradehub_core/media/pipeline/core/crop_geometry.ts. "
			"Beklenen değerler referans uygulamadan gelir; üretim modülleri ONA uymak zorundadır."
		),
		"uretici": "tests/tools/gen_crop_vectors.py",
		"tohum": TOHUM,
		"tolerance_px": 0.5,
		"sabitler": {"ZOOM_MIN": 1.0, "ZOOM_MAX": 16.0, "MIN_EDGE_PX": 1.0},
		"fonksiyonlar": ["cropWindow", "clampWindow", "ratioFit", "zoomBase", "roundWindow", "focalFromWindow", "zoomFromBase"],
		"vector_count": len(vektorler),
		"vectors": vektorler,
	}


def main() -> None:
	paket = uret()
	FIXTURES.mkdir(parents=True, exist_ok=True)
	CIKTI.write_text(json.dumps(paket, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")
	sayim: dict = {}
	for v in paket["vectors"]:
		sayim[v["fn"]] = sayim.get(v["fn"], 0) + 1
	print(f"{CIKTI}: {paket['vector_count']} vektör")
	for fn in sorted(sayim):
		print(f"  {fn:18s} {sayim[fn]:4d}")


if __name__ == "__main__":
	main()

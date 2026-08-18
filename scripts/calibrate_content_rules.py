#!/usr/bin/env python3
"""T-025 — İçerik uygunluk eşiklerini gerçek görsellerle kalibre eder.

BU BETİK HENÜZ ÇALIŞTIRILMADI. Görsel korpusu yok, Docker kapalı, üretim
veritabanına erişim yok. `media_engine/policy/content_rules.json` içindeki her
eşik "KALİBRE EDİLMEDİ — başlangıç değeri" olarak işaretlidir; bu betik o
işaretleri kaldırmanın TEK yoludur.

Ne yapar
--------
1. Etiketli bir görsel korpusunu okur (manifest CSV).
2. Her görsel için ölçülebilir metrikleri hesaplar (numpy + Pillow; opencv,
   scipy, imagehash BAĞIMLILIĞI YOKTUR).
3. Her kural için eşiği süpürür ve her eşik noktasında yanlış pozitif (FP) ile
   yanlış negatif (FN) oranını çıkarır.
4. FP <= --fp-budget kısıtı altında FN'i en küçükleyen eşiği ÖNERİR.
5. Öneriyi bir JSON dosyasına yazar. Politika dosyasını KENDİ BAŞINA
   DEĞİŞTİRMEZ — insan kararı gerekir.

Ne yapmaz
---------
- NSFW skoru ÜRETMEZ. O yol mevcut kodda var ve para/ağ ister:
  tradehub_core/api/moderation.py:100-132 `_openai_vision_check()`.
  Betik yalnız o yolun ÜRETTİĞİ skorları manifest'ten okur ve eşikler.
- Politika JSON'unu yazmaz, önerir.
- Ağa çıkmaz. Hiç.

Korpus nasıl hazırlanır
-----------------------
En az 300 görsel, gerçek üretim görsellerinden örneklenmiş (sentetik korpusla
kalibrasyon yanlış güven verir). Manifest CSV, UTF-8, ilk satır başlık:

    path,listing,category,label_flat_background,label_frame_fill,\
label_overlay_text,label_border_frame,label_blur,label_extreme_blur,\
label_nsfw,nsfw_score,violence_score,vision_text_detected

  path        korpus köküne göre göreli dosya yolu (zorunlu)
  listing     aynı ürünün görsellerini gruplamak için kimlik (duplicate kuralı
              için zorunlu; boşsa o görsel duplicate analizine girmez)
  category    Product Category adı — kategori muafiyetlerini ölçmek için
  label_*     insan etiketi. Anlamı HER KURALDA AYNI:
                1 = kural TETİKLENMELİ (görsel gerçekten kusurlu)
                0 = kural TETİKLENMEMELİ (görsel kabul edilebilir)
                boş = bu kural için etiketlenmedi, analize girmez
  nsfw_score / violence_score / vision_text_detected
              Vision yolundan gelen ÖNCEDEN üretilmiş çıktılar. Nasıl
              üretilecekleri: docs/standards/icerik-kurallari.md
              § ÜRETİMDE DOĞRULANMALI

Duplicate kuralı için ayrı etiket dosyası (--dup-labels), UTF-8, başlıklı:

    listing,path_a,path_b,label_duplicate

Kullanım
--------
    python3 scripts/calibrate_content_rules.py \
        --corpus /veri/korpus \
        --manifest /veri/korpus/manifest.csv \
        --policy media_engine/policy/content_rules.json \
        --out /veri/korpus/onerilen_esikler.json

Çıkış kodları: 0 başarılı, 2 kullanım hatası, 3 bağımlılık eksik.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field

# ── Bağımlılıklar ───────────────────────────────────────────────────────
#
# Pillow: kodda yaygın kullanılıyor (tradehub_core/media/engine.py:82) ama
# pyproject.toml `dependencies` listesinde YOK — Frappe ile geldiği varsayılıyor.
# numpy: yalnız scikit-learn üzerinden DOLAYLI geliyor (requirements.txt:3).
# İkisi de doğrudan bağımlılık olmadığı için varlığı burada AÇIKÇA sınanıyor;
# ImportError ile ölmek yerine ne kurulacağını söylüyor.

try:
	import numpy as np
except ImportError:  # pragma: no cover
	sys.stderr.write(
		"HATA: numpy yok. Kurulum: pip install numpy\n"
		"(numpy projede yalnız scikit-learn üzerinden dolaylı geliyor — requirements.txt:3)\n"
	)
	raise SystemExit(3) from None

try:
	from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
	sys.stderr.write(
		"HATA: Pillow yok. Kurulum: pip install Pillow\n"
		"(Pillow pyproject.toml dependencies listesinde yok; Frappe ile geldiği varsayılıyor)\n"
	)
	raise SystemExit(3) from None

# pytesseract opsiyonel. Yoksa overlay_text kuralı YEREL yolla ölçülemez —
# betik bunu "unavailable" diye raporlar, sessizce 0 saymaz.
try:
	import pytesseract  # type: ignore

	HAS_TESSERACT = True
except Exception:
	pytesseract = None  # type: ignore
	HAS_TESSERACT = False


# ── Ön işleme ───────────────────────────────────────────────────────────
#
# content_rules.json `preprocessing` bloğuyla BİREBİR aynı olmak zorunda.
# Ayrılırsa kalibre edilen eşik üretimde farklı bir sayıyı eşikler.

ANALYSIS_LONG_EDGE = 512
MIN_LONG_EDGE = 200
LUMA = (0.299, 0.587, 0.114)


@dataclass
class Yuklenen:
	"""Ön işlemden geçmiş görsel + ölçüm için hazır diziler."""

	path: str
	rgb: "np.ndarray"  # (H, W, 3) float32, 0..255
	gray: "np.ndarray"  # (H, W) float32, 0..255
	alpha: "np.ndarray | None"  # (H, W) float32 0..255 veya None
	orig_w: int
	orig_h: int
	animated: bool

	@property
	def olculebilir(self) -> bool:
		"""content_rules.json preprocessing.skip_if ile aynı koşullar."""
		return not self.animated and max(self.orig_w, self.orig_h) >= MIN_LONG_EDGE


def yukle(path: str) -> Yuklenen | None:
	"""Görseli aç, EXIF döndür, uzun kenarı 512'ye indir, dizilere çevir.

	Açılamayan dosya None döner — kalibrasyon tek bozuk dosya yüzünden durmaz
	(media/gates.py'deki `decode_failed` skip sebebiyle aynı felsefe).
	"""
	try:
		im = Image.open(path)
		orig_w, orig_h = im.size
		animated = bool(getattr(im, "is_animated", False))
		im = ImageOps.exif_transpose(im)

		alpha_arr = None
		if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
			rgba = im.convert("RGBA")
			# Analiz boyutuna indirmeden alfayı ayır: bbox için alfa maskesi
			# zemin çıkarımından daha güvenilir (frame_fill kuralı notu).
			rgba.thumbnail((ANALYSIS_LONG_EDGE, ANALYSIS_LONG_EDGE), Image.LANCZOS)
			alpha_arr = np.asarray(rgba.split()[3], dtype=np.float32)
			# content_rules.json preprocessing.alpha_handling: beyaza kompozit
			zemin = Image.new("RGB", rgba.size, (255, 255, 255))
			zemin.paste(rgba, mask=rgba.split()[3])
			im = zemin
		else:
			im = im.convert("RGB")
			im.thumbnail((ANALYSIS_LONG_EDGE, ANALYSIS_LONG_EDGE), Image.LANCZOS)

		rgb = np.asarray(im, dtype=np.float32)
		gray = rgb[:, :, 0] * LUMA[0] + rgb[:, :, 1] * LUMA[1] + rgb[:, :, 2] * LUMA[2]
		return Yuklenen(
			path=path,
			rgb=rgb,
			gray=gray.astype(np.float32),
			alpha=alpha_arr,
			orig_w=orig_w,
			orig_h=orig_h,
			animated=animated,
		)
	except Exception as e:  # bozuk/desteklenmeyen dosya
		sys.stderr.write(f"UYARI: açılamadı, atlanıyor: {path} ({e})\n")
		return None


# ── Metrikler ───────────────────────────────────────────────────────────


def _kenar_halkasi(rgb: "np.ndarray", kalinlik: int) -> "np.ndarray":
	"""Görselin dış kenarından `kalinlik` piksellik halkanın piksel listesi (N,3)."""
	h, w, _ = rgb.shape
	k = max(1, min(kalinlik, h // 2, w // 2))
	ust = rgb[:k, :, :].reshape(-1, 3)
	alt = rgb[-k:, :, :].reshape(-1, 3)
	sol = rgb[k:-k, :k, :].reshape(-1, 3)
	sag = rgb[k:-k, -k:, :].reshape(-1, 3)
	return np.concatenate([ust, alt, sol, sag], axis=0)


def flat_bg_ratio(g: Yuklenen, tolerans: int = 12, kalinlik: int = 2) -> dict:
	"""Kenar halkasının ne kadarı tek renk — content_rules.json flat_background.

	Zemin rengi = halkanın kanal-başına medyanı. Ortalama DEĞİL: ürün kenara
	taşmışsa ortalama ürünün rengine kayar, medyan daha dayanıklıdır.
	"""
	halka = _kenar_halkasi(g.rgb, kalinlik)
	if halka.size == 0:
		return {"flat_bg_ratio": None, "bg_luma": None, "reason": "not_measurable"}
	zemin = np.median(halka, axis=0)
	fark = np.max(np.abs(halka - zemin), axis=1)
	oran = float(np.mean(fark <= tolerans))
	bg_luma = float(zemin[0] * LUMA[0] + zemin[1] * LUMA[1] + zemin[2] * LUMA[2])
	return {
		"flat_bg_ratio": oran,
		"bg_luma": bg_luma,
		"bg_rgb": [float(x) for x in zemin],
		"reason": "",
	}


def frame_fill_ratio(g: Yuklenen, tolerans: int = 20) -> dict:
	"""Ürün bbox'ının kadraja oranı — content_rules.json frame_fill.

	Alfa kanalı varsa maske ondan alınır (daha güvenilir). Yoksa kenar
	halkasından bulunan zemin rengi çıkarılır.
	"""
	h, w, _ = g.rgb.shape
	toplam = float(h * w)

	if g.alpha is not None and g.alpha.shape == (h, w):
		maske = g.alpha > 16.0
		kaynak = "alpha"
	else:
		halka = _kenar_halkasi(g.rgb, 2)
		zemin = np.median(halka, axis=0)
		maske = np.max(np.abs(g.rgb - zemin), axis=2) > tolerans
		kaynak = "background_subtraction"

	fg_oran = float(np.mean(maske))
	if fg_oran < 0.02:
		# Ölçüm anlamsız: ürün bulunamadı. UYARI ÜRETİLMEZ.
		return {
			"fill_ratio": None,
			"foreground_ratio": fg_oran,
			"mask_source": kaynak,
			"reason": "not_measurable",
		}

	# Yüzdelik ile bbox: tek tük gürültü pikseli bbox'ı kadraja şişirmesin.
	satir = maske.sum(axis=1).astype(np.float64)
	sutun = maske.sum(axis=0).astype(np.float64)

	def _sinirlar(kutle: "np.ndarray") -> tuple[int, int]:
		toplam_kutle = kutle.sum()
		if toplam_kutle <= 0:
			return 0, len(kutle) - 1
		kum = np.cumsum(kutle) / toplam_kutle
		lo = int(np.searchsorted(kum, 0.005))
		hi = int(np.searchsorted(kum, 0.995))
		return min(lo, len(kutle) - 1), min(max(hi, lo), len(kutle) - 1)

	y0, y1 = _sinirlar(satir)
	x0, x1 = _sinirlar(sutun)
	alan = float((y1 - y0 + 1) * (x1 - x0 + 1))
	return {
		"fill_ratio": alan / toplam,
		"foreground_ratio": fg_oran,
		"bbox": [x0, y0, x1, y1],
		"mask_source": kaynak,
		"reason": "",
	}


def border_frame(
	g: Yuklenen,
	max_thickness_ratio: float = 0.05,
	band_std_max: float = 6.0,
	band_contrast_min: float = 30.0,
	interior_match_max: float = 0.50,
) -> dict:
	"""Dekoratif çerçeve kalınlığı — content_rules.json border_frame.

	Üç koşul BİRLİKTE aranır. (c) koşulu (band renginin iç bölgedeki kaplama
	oranı) ana yanlış-pozitif kalkanıdır: onsuz düz beyaz zeminli her ürün
	fotoğrafı "çerçeveli" sayılırdı.
	"""
	h, w, _ = g.rgb.shape
	max_t = max(1, int(min(h, w) * max_thickness_ratio))
	band_rgb = np.median(_kenar_halkasi(g.rgb, 1), axis=0)

	kalinlik = 0
	for t in range(1, max_t + 1):
		if t * 2 >= min(h, w):
			break
		# (a) 0..t-1 halkaları band rengine yakın ve kendi içinde düz mü
		bant = _kenar_halkasi(g.rgb, t)
		if float(np.max(np.std(bant, axis=0))) > band_std_max:
			break
		# (b) t derinliğindeki halka band renginden ayrılıyor mu
		ic = g.rgb[t : h - t, t : w - t, :]
		if ic.shape[0] < 3 or ic.shape[1] < 3:
			break
		sonraki = _kenar_halkasi(ic, 1)
		if float(np.max(np.abs(np.median(sonraki, axis=0) - band_rgb))) >= band_contrast_min:
			kalinlik = t
			break

	if kalinlik == 0:
		return {"border_thickness_px": 0, "interior_match": None, "reason": ""}

	# (c) band rengi iç bölgeyi domine ediyorsa bu çerçeve değil, zemindir
	ic = g.rgb[kalinlik : h - kalinlik, kalinlik : w - kalinlik, :]
	interior_match = float(np.mean(np.max(np.abs(ic - band_rgb), axis=2) <= band_std_max * 2))
	if interior_match > interior_match_max:
		return {
			"border_thickness_px": 0,
			"interior_match": interior_match,
			"reason": "band_is_background",
		}
	return {
		"border_thickness_px": kalinlik,
		"interior_match": interior_match,
		"band_rgb": [float(x) for x in band_rgb],
		"reason": "",
	}


def laplacian_var(g: Yuklenen) -> dict:
	"""Laplacian varyansı + Tenengrad — content_rules.json blur / extreme_blur.

	Yöntem: Pech-Pacheco ve ark. (2000, ICPR), "Diatom autofocusing in
	brightfield microscopy". OpenCV KULLANILMAZ; 4-komşulu Laplacian ve Sobel
	doğrudan numpy dilimlemesiyle yazıldı.

	ÖLÇEK KRİTİK: giriş uzun kenarı 512'ye sabitlenmiş olmalı (yukle() bunu
	yapar). Ön işleme değişirse eşik anlamını yitirir.
	"""
	a = g.gray
	if a.shape[0] < 3 or a.shape[1] < 3:
		return {"laplacian_var": None, "tenengrad_mean": None, "reason": "not_measurable"}

	lap = (
		4.0 * a[1:-1, 1:-1] - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:]
	)
	lv = float(np.var(lap))

	# Tenengrad: ikinci, bağımsız netlik sinyali. RED kararının tek bir
	# metriğe dayanmaması için istenir (content_rules.json extreme_blur).
	gx = (
		(a[:-2, 2:] + 2.0 * a[1:-1, 2:] + a[2:, 2:])
		- (a[:-2, :-2] + 2.0 * a[1:-1, :-2] + a[2:, :-2])
	) / 8.0
	gy = (
		(a[2:, :-2] + 2.0 * a[2:, 1:-1] + a[2:, 2:])
		- (a[:-2, :-2] + 2.0 * a[:-2, 1:-1] + a[:-2, 2:])
	) / 8.0
	ten = float(np.mean(np.sqrt(gx * gx + gy * gy)))
	return {"laplacian_var": lv, "tenengrad_mean": ten, "reason": ""}


_DCT_CACHE: dict[int, "np.ndarray"] = {}


def _dct_matrix(n: int) -> "np.ndarray":
	"""Ortonormal DCT-II matrisi. scipy YOK — matris elle kuruluyor."""
	if n in _DCT_CACHE:
		return _DCT_CACHE[n]
	k = np.arange(n).reshape(-1, 1)
	i = np.arange(n).reshape(1, -1)
	m = np.cos(np.pi * (2 * i + 1) * k / (2 * n))
	m *= math.sqrt(2.0 / n)
	m[0, :] = 1.0 / math.sqrt(n)
	_DCT_CACHE[n] = m
	return m


def phash(g: Yuklenen, giris: int = 32, tut: int = 8) -> int:
	"""64 bitlik perceptual hash — content_rules.json duplicate_image.

	imagehash paketi KULLANILMAZ (bağımlılık yok). Yöntem klasik pHash:
	32x32 gri → 2B DCT-II → sol üst 8x8 → DC hariç medyan eşikleme.
	"""
	im = Image.fromarray(np.clip(g.gray, 0, 255).astype(np.uint8), mode="L")
	im = im.resize((giris, giris), Image.LANCZOS)
	a = np.asarray(im, dtype=np.float64)
	d = _dct_matrix(giris)
	c = d @ a @ d.T
	blok = c[:tut, :tut].flatten()
	dc_haric = blok[1:]
	med = float(np.median(dc_haric))
	bitler = 0
	for idx, v in enumerate(blok):
		if idx == 0:
			continue  # DC atlanır, sabit parlaklık hash'i kirletmesin
		if v > med:
			bitler |= 1 << (idx - 1)
	return bitler


def hamming(a: int, b: int) -> int:
	return bin(a ^ b).count("1")


def color_hist_distance(g1: Yuklenen, g2: Yuklenen, kova: int = 4) -> float:
	"""Renk histogramı L1 mesafesi (0..2) — renk varyantı FP'sini ayırmak için.

	pHash renge büyük ölçüde duyarsızdır; aynı pozda farklı renkli iki varyant
	yakın hash verir ve YANLIŞ pozitif üretir. Bu ikinci sinyal onu ayırabilir
	ama eşiği KALİBRE EDİLMEDİ — betik yalnız değeri raporlar.
	"""

	def h(g: Yuklenen) -> "np.ndarray":
		q = (g.rgb / (256.0 / kova)).astype(np.int32).clip(0, kova - 1)
		idx = (q[:, :, 0] * kova + q[:, :, 1]) * kova + q[:, :, 2]
		hist = np.bincount(idx.flatten(), minlength=kova**3).astype(np.float64)
		s = hist.sum()
		return hist / s if s > 0 else hist

	return float(np.abs(h(g1) - h(g2)).sum())


def ocr_text_signal(g: Yuklenen, min_conf: int = 60, min_word_chars: int = 3) -> dict:
	"""Yerel OCR ile metin alanı oranı — content_rules.json overlay_text yedeği.

	BİRİNCİL YOL BU DEĞİL. Mevcut kodda Vision zaten `text_detected` döndürüyor
	(tradehub_core/api/moderation.py:100-132, alan: Image Moderation Log.
	text_detected). Bu fonksiyon yalnız o çıktı yokken kullanılır.

	pytesseract yoksa None döner ve rapor "unavailable" der — 0 SAYMAZ, çünkü
    ölçülemeyeni "temiz" saymak kuralı sessizce kapatır.
	"""
	if not HAS_TESSERACT:
		return {"ocr_text_area_ratio": None, "reason": "tesseract_unavailable"}
	h, w, _ = g.rgb.shape
	im = Image.fromarray(np.clip(g.rgb, 0, 255).astype(np.uint8), mode="RGB")
	try:
		veri = pytesseract.image_to_data(  # type: ignore[union-attr]
			im, output_type=pytesseract.Output.DICT  # type: ignore[union-attr]
		)
	except Exception as e:
		return {"ocr_text_area_ratio": None, "reason": f"tesseract_failed:{e}"}

	alan = 0
	kenar_alan = 0
	kelimeler: list[str] = []
	n = len(veri.get("text", []))
	kenar_esik_x = w * 0.15
	kenar_esik_y = h * 0.15
	for i in range(n):
		metin = (veri["text"][i] or "").strip()
		try:
			conf = float(veri["conf"][i])
		except (TypeError, ValueError):
			conf = -1.0
		if conf < min_conf or len(metin) < min_word_chars:
			continue
		bw, bh = int(veri["width"][i]), int(veri["height"][i])
		bx, by = int(veri["left"][i]), int(veri["top"][i])
		alan += bw * bh
		kelimeler.append(metin)
		# Kenar bölgesindeki metin filigran/çerçeve yazısı olasılığı yüksek;
		# ürün bbox'ı içindeki metin meşru olasılığı yüksek. Ayrım kalibrasyonda
		# ölçülmeli (content_rules.json overlay_text.false_positive_risk).
		if bx < kenar_esik_x or by < kenar_esik_y or (bx + bw) > w - kenar_esik_x or (by + bh) > h - kenar_esik_y:
			kenar_alan += bw * bh
	toplam = float(h * w)
	return {
		"ocr_text_area_ratio": alan / toplam if toplam else None,
		"ocr_edge_text_area_ratio": kenar_alan / toplam if toplam else None,
		"ocr_word_count": len(kelimeler),
		"reason": "",
	}


# ── Eşik süpürme ────────────────────────────────────────────────────────


@dataclass
class SupurmeSonucu:
	kural: str
	metrik: str
	yon: str  # "lower_is_worse" | "higher_is_worse"
	n_pozitif: int  # label=1 (tetiklenmeli)
	n_negatif: int  # label=0 (tetiklenmemeli)
	noktalar: list[dict] = field(default_factory=list)
	onerilen: dict | None = None
	mevcut: dict | None = None
	not_: str = ""


def supur(
	kural: str,
	metrik: str,
	ornekler: list[tuple[float, int]],
	yon: str,
	fp_butcesi: float,
	mevcut_esik: float | None,
	adim_sayisi: int = 120,
) -> SupurmeSonucu:
	"""Eşiği süpür; her noktada FP/FN ver; FP bütçesi altında FN'i en küçükle.

	`yon="lower_is_worse"`: metrik eşiğin ALTINDA ise kural tetiklenir
	(bulanıklık, doluluk, düz zemin).
	`yon="higher_is_worse"`: metrik eşiğin ÜSTÜNDE/EŞİTİNDE ise tetiklenir
	(NSFW skoru, OCR metin alanı, çerçeve kalınlığı).

	FP = kural tetiklendi ama etiket 0 (temiz görsele uyarı bastık).
	FN = kural tetiklenmedi ama etiket 1 (kusurlu görseli kaçırdık).
	Bizim bütçemiz FP tarafında: satıcıyı yanlış uyarmak, bir kusuru kaçırmaktan
	pahalıdır (uyarı gürültüsü bütün kuralları öğrenilmiş çaresizliğe çevirir).
	"""
	poz = [v for v, l in ornekler if l == 1]
	neg = [v for v, l in ornekler if l == 0]
	sonuc = SupurmeSonucu(
		kural=kural, metrik=metrik, yon=yon, n_pozitif=len(poz), n_negatif=len(neg)
	)
	if not poz or not neg:
		sonuc.not_ = (
			f"YETERSİZ ETİKET: pozitif={len(poz)} negatif={len(neg)}. "
			"Eşik önerilemez; her iki sınıftan en az 30 örnek gerekir."
		)
		return sonuc

	degerler = sorted({v for v, _ in ornekler})
	if len(degerler) > adim_sayisi:
		idx = np.linspace(0, len(degerler) - 1, adim_sayisi).astype(int)
		adaylar = [degerler[i] for i in idx]
	else:
		adaylar = degerler

	def tetikler(v: float, t: float) -> bool:
		return v < t if yon == "lower_is_worse" else v >= t

	en_iyi = None
	for t in adaylar:
		fp = sum(1 for v in neg if tetikler(v, t))
		fn = sum(1 for v in poz if not tetikler(v, t))
		tp = len(poz) - fn
		fp_orani = fp / len(neg)
		fn_orani = fn / len(poz)
		nokta = {
			"threshold": float(t),
			"fp": fp,
			"fn": fn,
			"tp": tp,
			"fp_rate": round(fp_orani, 4),
			"fn_rate": round(fn_orani, 4),
			"precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
			"recall": round(tp / len(poz), 4),
		}
		sonuc.noktalar.append(nokta)
		if fp_orani <= fp_butcesi and (en_iyi is None or fn_orani < en_iyi["fn_rate"]):
			en_iyi = nokta

	sonuc.onerilen = en_iyi
	if en_iyi is None:
		sonuc.not_ = (
			f"FP bütçesi (%{fp_butcesi * 100:.0f}) hiçbir eşikte tutulamadı. "
			"Bu kural bu metrikle ayırt edici DEĞİL — kural devre dışı bırakılmalı "
			"ya da metrik değiştirilmeli."
		)

	if mevcut_esik is not None:
		fp = sum(1 for v in neg if tetikler(v, mevcut_esik))
		fn = sum(1 for v in poz if not tetikler(v, mevcut_esik))
		sonuc.mevcut = {
			"threshold": float(mevcut_esik),
			"fp": fp,
			"fn": fn,
			"fp_rate": round(fp / len(neg), 4),
			"fn_rate": round(fn / len(poz), 4),
			"within_budget": (fp / len(neg)) <= fp_butcesi,
		}
	return sonuc


# ── Korpus okuma ────────────────────────────────────────────────────────


def _etiket(satir: dict, anahtar: str) -> int | None:
	v = (satir.get(anahtar) or "").strip()
	if v in ("0", "1"):
		return int(v)
	return None


def _float(satir: dict, anahtar: str) -> float | None:
	v = (satir.get(anahtar) or "").strip()
	try:
		return float(v)
	except ValueError:
		return None


def manifest_oku(yol: str) -> list[dict]:
	with open(yol, encoding="utf-8", newline="") as f:
		satirlar = list(csv.DictReader(f))
	if not satirlar:
		raise SystemExit("HATA: manifest boş")
	if "path" not in satirlar[0]:
		raise SystemExit("HATA: manifest'te 'path' kolonu yok")
	return satirlar


def politika_esikleri(politika_yolu: str) -> dict:
	"""content_rules.json'daki mevcut BAŞLANGIÇ eşiklerini oku.

	Kalibrasyon çıktısı "önerilen" ile "şu an yazılı olan"ı yan yana göstermeli;
	yoksa insan neyin değiştiğini göremez.
	"""
	with open(politika_yolu, encoding="utf-8") as f:
		p = json.load(f)
	t = {r["id"]: r.get("threshold", {}) for r in p.get("rules", [])}
	return {
		"flat_background": t.get("flat_background", {}).get("flat_bg_ratio_min"),
		"frame_fill": t.get("frame_fill", {}).get("fill_ratio_min"),
		"overlay_text": t.get("overlay_text", {}).get("ocr_text_area_ratio_max"),
		"border_frame": t.get("border_frame", {}).get("border_thickness_min_px"),
		"blur": t.get("blur", {}).get("laplacian_var_warn_below"),
		"extreme_blur": t.get("extreme_blur", {}).get("laplacian_var_reject_below"),
		"nsfw_content": t.get("nsfw_content", {}).get("nsfw_score_reject_at_or_above"),
		"duplicate_image": t.get("duplicate_image", {}).get("hamming_max_for_duplicate"),
		"_fp_budget": p.get("false_positive_budget", 0.05),
	}


# ── Ana akış ────────────────────────────────────────────────────────────

# (kural id, metrik adı, manifest etiket kolonu, süpürme yönü)
TEK_GORSEL_KURALLARI: tuple[tuple[str, str, str, str], ...] = (
	("flat_background", "flat_bg_ratio", "label_flat_background", "lower_is_worse"),
	("frame_fill", "fill_ratio", "label_frame_fill", "lower_is_worse"),
	("border_frame", "border_thickness_px", "label_border_frame", "higher_is_worse"),
	("blur", "laplacian_var", "label_blur", "lower_is_worse"),
	("extreme_blur", "laplacian_var", "label_extreme_blur", "lower_is_worse"),
	("overlay_text", "ocr_text_area_ratio", "label_overlay_text", "higher_is_worse"),
	("nsfw_content", "nsfw_score", "label_nsfw", "higher_is_worse"),
)


def main(argv: list[str] | None = None) -> int:
	ap = argparse.ArgumentParser(
		description="T-025 içerik kuralı eşik kalibrasyonu (HENÜZ ÇALIŞTIRILMADI)"
	)
	ap.add_argument("--corpus", required=True, help="Görsel korpusu kök dizini")
	ap.add_argument("--manifest", required=True, help="Etiketli manifest CSV")
	ap.add_argument("--dup-labels", help="Yinelenen görsel çift etiketleri CSV")
	ap.add_argument(
		"--policy",
		default="media_engine/policy/content_rules.json",
		help="Mevcut politika JSON'u (karşılaştırma için okunur, YAZILMAZ)",
	)
	ap.add_argument("--out", required=True, help="Önerilen eşiklerin yazılacağı JSON")
	ap.add_argument("--fp-budget", type=float, default=None, help="Varsayılan: politikadaki değer")
	ap.add_argument("--limit", type=int, default=0, help="İlk N görsel (hızlı deneme)")
	a = ap.parse_args(argv)

	if not os.path.isdir(a.corpus):
		sys.stderr.write(f"HATA: korpus dizini yok: {a.corpus}\n")
		return 2

	mevcut = politika_esikleri(a.policy)
	fp_butcesi = a.fp_budget if a.fp_budget is not None else mevcut["_fp_budget"]

	satirlar = manifest_oku(a.manifest)
	if a.limit:
		satirlar = satirlar[: a.limit]

	# ── ölçüm ──
	olculen: list[dict] = []
	hashler: dict[str, int] = {}
	yuklenenler: dict[str, Yuklenen] = {}
	atlanan = {"decode_failed": 0, "not_measurable": 0}

	for s in satirlar:
		tam = os.path.join(a.corpus, s["path"])
		g = yukle(tam)
		if g is None:
			atlanan["decode_failed"] += 1
			continue
		if not g.olculebilir:
			atlanan["not_measurable"] += 1
			continue

		m: dict = {"path": s["path"], "listing": (s.get("listing") or "").strip()}
		m["category"] = (s.get("category") or "").strip()
		m.update(flat_bg_ratio(g))
		m.update(frame_fill_ratio(g))
		m.update(border_frame(g))
		m.update(laplacian_var(g))
		m.update(ocr_text_signal(g))
		m["orig_long_edge"] = max(g.orig_w, g.orig_h)
		# Vision çıktıları manifest'ten gelir — betik ağa çıkmaz.
		m["nsfw_score"] = _float(s, "nsfw_score")
		m["violence_score"] = _float(s, "violence_score")
		m["vision_text_detected_len"] = len((s.get("vision_text_detected") or "").strip())
		for _, _, kolon, _ in TEK_GORSEL_KURALLARI:
			m[kolon] = _etiket(s, kolon)
		olculen.append(m)
		hashler[s["path"]] = phash(g)
		if m["listing"]:
			yuklenenler[s["path"]] = g

	if not olculen:
		sys.stderr.write("HATA: ölçülebilir görsel yok\n")
		return 2

	# ── tek görsel kurallarını süpür ──
	supurmeler: list[SupurmeSonucu] = []
	for kural, metrik, kolon, yon in TEK_GORSEL_KURALLARI:
		ornekler = [
			(float(m[metrik]), int(m[kolon]))
			for m in olculen
			if m.get(metrik) is not None and m.get(kolon) is not None
		]
		s = supur(kural, metrik, ornekler, yon, fp_butcesi, mevcut.get(kural))
		if kural == "extreme_blur":
			s.not_ = (
				(s.not_ + " ") if s.not_ else ""
			) + (
				"RED kuralı: FP bütçesi burada %5 DEĞİL, %1 olmalı. "
				"--fp-budget 0.01 ile ayrıca çalıştırılmalı. Ayrıca guard koşulları "
				"(uzun kenar >= 800 px, tenengrad_mean < 4.0) bu süpürmede "
				"UYGULANMADI — süpürme yalnız tek metriği ölçer."
			)
		if kural == "nsfw_content":
			s.not_ = (
				(s.not_ + " ") if s.not_ else ""
			) + (
				"Skorlar manifest'ten okundu; bu betik Vision çağırmaz. "
				"Kaynak yol: tradehub_core/api/moderation.py:100-132. "
				"Anahtar yoksa üretimde _stub_check_image() her şeye allow der "
				"(tradehub_core/api/moderation.py:95-97) — stub ile üretilmiş "
				"skorlarla kalibrasyon YAPILAMAZ."
			)
		if kural == "overlay_text" and not HAS_TESSERACT:
			s.not_ = (
				(s.not_ + " ") if s.not_ else ""
			) + "pytesseract kurulu değil — yerel OCR ölçülemedi, örnek sayısı 0."
		supurmeler.append(s)

	# ── yinelenen görsel: çift bazlı ──
	dup_sonucu: SupurmeSonucu | None = None
	renk_notlari: list[dict] = []
	if a.dup_labels:
		with open(a.dup_labels, encoding="utf-8", newline="") as f:
			ciftler = list(csv.DictReader(f))
		ornekler: list[tuple[float, int]] = []
		for c in ciftler:
			pa, pb = (c.get("path_a") or "").strip(), (c.get("path_b") or "").strip()
			l = _etiket(c, "label_duplicate")
			if pa not in hashler or pb not in hashler or l is None:
				continue
			d = hamming(hashler[pa], hashler[pb])
			ornekler.append((float(d), l))
			if pa in yuklenenler and pb in yuklenenler:
				renk_notlari.append(
					{
						"path_a": pa,
						"path_b": pb,
						"phash_hamming": d,
						"color_hist_distance": round(
							color_hist_distance(yuklenenler[pa], yuklenenler[pb]), 4
						),
						"label_duplicate": l,
					}
				)
		dup_sonucu = supur(
			"duplicate_image",
			"phash_hamming_distance",
			ornekler,
			"lower_is_worse",
			fp_butcesi,
			mevcut.get("duplicate_image"),
		)
		dup_sonucu.not_ = (
			(dup_sonucu.not_ + " ") if dup_sonucu.not_ else ""
		) + (
			"Renk varyantı yanlış pozitifi için color_hist_distance değerleri "
			"çıktıda ayrıca listelenmiştir; ikinci sinyalin eşiği bu süpürmede "
			"KALİBRE EDİLMEDİ."
		)
	else:
		# Etiket yoksa yine de aynı listing içindeki mesafe dağılımını çıkar —
		# insan eşiği gözle seçebilsin.
		gruplar: dict[str, list[str]] = defaultdict(list)
		for m in olculen:
			if m["listing"]:
				gruplar[m["listing"]].append(m["path"])
		mesafeler = []
		for _, yollar in gruplar.items():
			for i in range(len(yollar)):
				for j in range(i + 1, len(yollar)):
					mesafeler.append(hamming(hashler[yollar[i]], hashler[yollar[j]]))
		renk_notlari = [{"distance_histogram": sorted(mesafeler)}] if mesafeler else []

	# ── rapor ──
	rapor = {
		"task": "T-025",
		"kind": "threshold_calibration_proposal",
		"policy_read": os.path.abspath(a.policy),
		"policy_written": False,
		"policy_written_note": "Bu betik politikayı DEĞİŞTİRMEZ. Öneriyi insan uygular.",
		"corpus": os.path.abspath(a.corpus),
		"manifest": os.path.abspath(a.manifest),
		"fp_budget": fp_butcesi,
		"images_in_manifest": len(satirlar),
		"images_measured": len(olculen),
		"skipped": atlanan,
		"tesseract_available": HAS_TESSERACT,
		"corpus_size_warning": (
			None
			if len(olculen) >= 300
			else f"Korpus küçük ({len(olculen)} görsel). 300 altındaki korpusla "
			"bulunan eşik istatistiksel olarak dayanıksızdır."
		),
		"rules": [],
		"duplicate_pairs_detail": renk_notlari[:200],
		"min_image_count": {
			"note": "Bu kural KALİBRE EDİLMEZ — ürün kararıdır, ölçüm değil. "
			"Eşik 3, mevcut kodda zaten var: "
			"tradehub_core/utils/completeness.py:231-232.",
			"listing_image_counts": None,
		},
	}

	sayimlar: dict[str, int] = defaultdict(int)
	for m in olculen:
		if m["listing"]:
			sayimlar[m["listing"]] += 1
	if sayimlar:
		dagilim: dict[str, int] = defaultdict(int)
		for _, c in sayimlar.items():
			dagilim[str(min(c, 10))] += 1
		rapor["min_image_count"]["listing_image_counts"] = dict(sorted(dagilim.items()))
		alti = sum(1 for c in sayimlar.values() if c < 3)
		rapor["min_image_count"]["listings_below_3"] = alti
		rapor["min_image_count"]["listings_total"] = len(sayimlar)

	for s in supurmeler + ([dup_sonucu] if dup_sonucu else []):
		rapor["rules"].append(
			{
				"rule": s.kural,
				"metric": s.metrik,
				"direction": s.yon,
				"n_positive": s.n_pozitif,
				"n_negative": s.n_negatif,
				"current_start_threshold": s.mevcut,
				"recommended": s.onerilen,
				"note": s.not_,
				"sweep": s.noktalar,
			}
		)

	with open(a.out, "w", encoding="utf-8") as f:
		json.dump(rapor, f, ensure_ascii=False, indent=2)

	# ── özet (stdout) ──
	print(f"Ölçülen görsel: {len(olculen)} / manifest {len(satirlar)}")
	if rapor["corpus_size_warning"]:
		print("UYARI: " + rapor["corpus_size_warning"])
	print(f"FP bütçesi: {fp_butcesi}")
	print("")
	basliklar = ("kural", "metrik", "mevcut", "önerilen", "FP", "FN")
	print("{:<18}{:<26}{:>10}{:>12}{:>8}{:>8}".format(*basliklar))

	def _g(d: dict | None, anahtar: str, bicim: str, bos: str = "-") -> str:
		if not d or d.get(anahtar) is None:
			return bos
		return format(d[anahtar], bicim)

	for r in rapor["rules"]:
		mv, on = r["current_start_threshold"], r["recommended"]
		print(
			"{:<18}{:<26}{:>10}{:>12}{:>8}{:>8}".format(
				r["rule"],
				r["metric"],
				_g(mv, "threshold", "g"),
				_g(on, "threshold", "g", bos="YOK"),
				_g(on, "fp_rate", ".1%"),
				_g(on, "fn_rate", ".1%"),
			)
		)
		if r["note"]:
			print(f"    ! {r['note']}")
	print("")
	print(f"Ayrıntılı rapor: {os.path.abspath(a.out)}")
	print("Politika dosyası DEĞİŞTİRİLMEDİ — önerileri elle uygulayın.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

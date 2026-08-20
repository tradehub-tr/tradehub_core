#!/usr/bin/env python3
"""Faz 1 (T-010…T-019) ölçüm betiği — T-013 dışındaki başlıklar.

T-013'ün kendi betiği ayrıdır: `scripts/measure_ssim_quality.py`.

Alt komutlar
------------
    guvenlik   T-017 — 51 fixture `upload_policy.check()`'ten geçirilir; hangi
               zararlı dosya yakalanıyor, hangisi geçiyor ÖLÇÜLÜR. (frappe gerekir)
    korpus     T-012 + T-018 — canlı dosyalarda DPI metadata dağılımı, uzun kenar
               dağılımı, sha256 tekilleştirme (dedup) kazancı.
    saliency   T-014 — kenar enerjisi ağırlık merkezi vs geometrik merkez; merkez
               kırpmanın kaybettiği özne enerjisi.
    preflight  T-015 — istemci ön-sıkıştırma (1920/q85) + sunucu WebP zincirinin
               ÇİFT ENCODE cezası, tek geçişli master'a karşı SSIM ile ölçülür.
    video      T-016 — video fixture'larının ffprobe künyesi + kodlayıcı envanteri.

Koşum (konteyner):
    docker exec -w /home/frappe/olcum istoc-dev-backend-1 \
        ../frappe-bench/env/bin/python measure_faz1.py korpus --out korpus.json
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
if str(KOK) not in sys.path:
	sys.path.insert(0, str(KOK))

VARSAYILAN_SITE_KOK = "/home/frappe/frappe-bench/sites/istoc.localhost"
GORSEL_UZANTILARI = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".gif", ".bmp", ".avif"}


# ── T-017 · güvenlik kapısı ──────────────────────────────────────────────


def komut_guvenlik(args) -> dict:
	"""Her fixture'ı `upload_policy.check()`'ten geçir; kararı ÖLÇ.

	Ölçülen: kapı reddetti mi, hangi kodla, ve reddetmediyse Pillow künyesi
	(megapiksel) politikanın `accept.max_megapixels_hard` sınırını aşıyor mu.
	Amaç bir iddiayı doğrulamak değil, kapının GERÇEK kapsamını çıkarmaktır.
	"""
	import frappe

	frappe.init(site=args.site)
	frappe.connect()
	from tradehub_core.media import upload_policy

	fdir = Path(args.fixtures)
	dosyalar = sorted(
		[p for p in (fdir / "media" / "images").glob("*") if p.is_file()]
		+ [p for p in (fdir / "malicious").glob("*") if p.is_file()]
		+ [p for p in (fdir / "media" / "video").glob("*") if p.is_file()]
	)

	satirlar = []
	for p in dosyalar:
		icerik = p.read_bytes()
		kayit = {
			"dosya": p.name,
			"grup": "malicious" if "malicious" in str(p) else "temiz",
			"bytes": len(icerik),
			"sniff": upload_policy.sniff(icerik),
			"is_dangerous": upload_policy.is_dangerous(icerik),
		}
		for uc in ("media_endpoint", "hook"):
			try:
				karar = upload_policy.check(
					p.name, content=icerik, media_endpoint=(uc == "media_endpoint")
				)
				kayit[uc] = {"red": False, "kod": "", "uyarilar": karar.warnings, "kind": karar.kind}
			except Exception as exc:
				mesaj = str(exc)
				kod = ""
				if "[" in mesaj and "]" in mesaj:
					kod = mesaj[mesaj.rfind("[") + 1 : mesaj.rfind("]")]
				kayit[uc] = {"red": True, "kod": kod, "uyarilar": [], "kind": ""}
		# Kapıyı geçenlerde piksel künyesi: bomba dosyası bayt kapısına takılmaz.
		kayit["probe"] = _pil_probe(icerik)
		satirlar.append(kayit)

	kacan = [
		s
		for s in satirlar
		if s["grup"] == "malicious" and not s["media_endpoint"]["red"] and not s["hook"]["red"]
	]
	return {
		"gorev": "T-017",
		"upload_policy_md5": _md5(Path(upload_policy.__file__)),
		"toplam": len(satirlar),
		"malicious_sayisi": sum(1 for s in satirlar if s["grup"] == "malicious"),
		"malicious_kacan": [s["dosya"] for s in kacan],
		"satirlar": satirlar,
	}


def _pil_probe(icerik: bytes) -> dict:
	try:
		from PIL import Image

		Image.MAX_IMAGE_PIXELS = None
		with Image.open(io.BytesIO(icerik)) as im:
			return {
				"format": im.format,
				"mode": im.mode,
				"w": im.width,
				"h": im.height,
				"mp": round(im.width * im.height / 1e6, 3),
				"animated": bool(getattr(im, "is_animated", False)),
			}
	except Exception as exc:
		return {"hata": type(exc).__name__}


def _md5(p: Path) -> str:
	return hashlib.md5(p.read_bytes()).hexdigest()


# ── T-012 + T-018 · canlı korpus ─────────────────────────────────────────


def komut_korpus(args) -> dict:
	"""Canlı dosyalarda DPI metadata, uzun kenar ve sha256 tekilleştirme ölçümü."""
	kok = Path(args.site_root)
	hedefler = [kok / "public" / "files", kok / "private" / "files"]

	dpi_sayaci: Counter = Counter()
	dpi_degerleri: Counter = Counter()
	uzun_kenar: list[int] = []
	kisa_kenar: list[int] = []
	hash_gruplari: dict[str, list[tuple[str, int]]] = defaultdict(list)
	okunamayan = 0
	gorsel = 0
	toplam_dosya = 0
	toplam_bayt = 0
	politika_alti = 0  # product.image master.min_long_edge = 2000

	from PIL import Image

	Image.MAX_IMAGE_PIXELS = None

	for taban in hedefler:
		if not taban.is_dir():
			continue
		for dirpath, _dirs, files in os.walk(taban):
			for ad in files:
				p = Path(dirpath) / ad
				try:
					boyut = p.stat().st_size
				except OSError:
					continue
				toplam_dosya += 1
				toplam_bayt += boyut
				try:
					h = hashlib.sha256(p.read_bytes()).hexdigest()
					hash_gruplari[h].append((str(p.relative_to(kok)), boyut))
				except OSError:
					continue
				if p.suffix.lower() not in GORSEL_UZANTILARI:
					continue
				gorsel += 1
				try:
					with Image.open(p) as im:
						dpi = im.info.get("dpi")
						if dpi:
							dpi_sayaci["var"] += 1
							dpi_degerleri[str(tuple(round(float(d)) for d in dpi))] += 1
						else:
							dpi_sayaci["yok"] += 1
						uk = max(im.width, im.height)
						uzun_kenar.append(uk)
						kisa_kenar.append(min(im.width, im.height))
						if uk < 2000:
							politika_alti += 1
				except Exception:
					okunamayan += 1

	tekrarli = {h: g for h, g in hash_gruplari.items() if len(g) > 1}
	tekrar_bayt = sum(sum(b for _n, b in g[1:]) for g in tekrarli.values())

	return {
		"gorev": "T-012 + T-018",
		"site_kok": str(kok),
		"toplam_dosya": toplam_dosya,
		"toplam_bayt": toplam_bayt,
		"gorsel_dosya": gorsel,
		"gorsel_okunamayan": okunamayan,
		"dpi": {
			"metadata_var": dpi_sayaci.get("var", 0),
			"metadata_yok": dpi_sayaci.get("yok", 0),
			"en_sik_degerler": dpi_degerleri.most_common(12),
		},
		"uzun_kenar": _yuzdelikler(uzun_kenar),
		"kisa_kenar": _yuzdelikler(kisa_kenar),
		"min_long_edge_2000_altinda": politika_alti,
		"dedup": {
			"benzersiz_icerik": len(hash_gruplari),
			"tekrarli_grup": len(tekrarli),
			"tekrarli_fazladan_kopya": sum(len(g) - 1 for g in tekrarli.values()),
			"geri_kazanilabilir_bayt": tekrar_bayt,
			"en_buyuk_5_grup": sorted(
				(
					{"kopya": len(g), "bayt": sum(b for _n, b in g), "ornek": g[0][0]}
					for g in tekrarli.values()
				),
				key=lambda d: d["bayt"],
				reverse=True,
			)[:5],
		},
	}


def _yuzdelikler(vals: list[int]) -> dict:
	if not vals:
		return {"n": 0}
	s = sorted(vals)

	def y(p: float) -> int:
		i = min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))
		return s[i]

	return {"n": len(s), "p50": y(0.50), "p90": y(0.90), "p99": y(0.99), "max": s[-1], "min": s[0]}


# ── T-014 · odak / saliency ──────────────────────────────────────────────


def _kenar_enerjisi(im):
	"""Sobel benzeri gradyan büyüklüğü — numpy ile, ek bağımlılık yok."""
	import numpy as np

	a = np.asarray(im.convert("L"), dtype=np.float64)
	gy = np.zeros_like(a)
	gx = np.zeros_like(a)
	gy[1:-1, :] = a[2:, :] - a[:-2, :]
	gx[:, 1:-1] = a[:, 2:] - a[:, :-2]
	return np.hypot(gx, gy)


def _canli_ornek(site_kok: Path, adet: int, tohum: int = 20260818) -> list[Path]:
	"""Canlı dosyalardan deterministik (tohumlu) görsel örneklemi."""
	import random

	hepsi = []
	for taban in (site_kok / "public" / "files", site_kok / "private" / "files"):
		if not taban.is_dir():
			continue
		for dirpath, _d, files in os.walk(taban):
			for ad in files:
				if Path(ad).suffix.lower() in GORSEL_UZANTILARI:
					hepsi.append(Path(dirpath) / ad)
	hepsi.sort()
	rnd = random.Random(tohum)
	return hepsi if len(hepsi) <= adet else rnd.sample(hepsi, adet)


def komut_saliency(args) -> dict:
	"""Kenar enerjisi ağırlık merkezi ile geometrik merkezi karşılaştır.

	İki sayı üretir:
	  * `kayma` — enerji merkezinin geometrik merkezden sapması, kısa kenarın yüzdesi.
	  * `merkez_kirpma_kaybi` — 1:1 merkez kırpmanın DIŞINDA kalan enerji oranı;
	    saliency farkında kırpmanın DIŞINDA kalan enerji oranıyla karşılaştırılır.
	"""
	import numpy as np
	from PIL import Image

	if args.kaynak == "canli":
		havuz = _canli_ornek(Path(args.site_root), args.ornek)
		kaynak_adi = f"canlı örneklem (n={len(havuz)}, tohum={args.tohum})"
	else:
		havuz = sorted(
			q for q in (Path(args.fixtures) / "media" / "images").glob("*")
			if q.suffix.lower() in GORSEL_UZANTILARI
		)
		kaynak_adi = "fixture korpusu"

	satirlar = []
	for p in havuz:
		if p.suffix.lower() not in GORSEL_UZANTILARI:
			continue
		try:
			with Image.open(p) as im:
				if getattr(im, "is_animated", False):
					continue
				im = im.convert("RGB")
				im.thumbnail((512, 512), Image.LANCZOS)
				e = _kenar_enerjisi(im)
		except Exception:
			continue
		h, w = e.shape
		toplam = float(e.sum()) or 1.0
		ys, xs = np.mgrid[0:h, 0:w]
		cx = float((e * xs).sum() / toplam)
		cy = float((e * ys).sum() / toplam)
		kisa = float(min(w, h))
		kayma = math.hypot(cx - w / 2.0, cy - h / 2.0) / kisa

		# 1:1 kırpma: merkezden vs enerji merkezinden
		k = int(kisa)
		def _kutu(mx, my):
			x0 = int(round(min(max(mx - k / 2.0, 0), w - k)))
			y0 = int(round(min(max(my - k / 2.0, 0), h - k)))
			return float(e[y0 : y0 + k, x0 : x0 + k].sum()) / toplam

		merkez = _kutu(w / 2.0, h / 2.0)
		odak = _kutu(cx, cy)
		satirlar.append(
			{
				"dosya": p.name,
				"wh": [w, h],
				"kayma_kisa_kenar_orani": round(kayma, 4),
				"merkez_kirpma_enerji": round(merkez, 4),
				"odak_kirpma_enerji": round(odak, 4),
				"kazanc": round(odak - merkez, 4),
			}
		)
	kazanclar = [s["kazanc"] for s in satirlar]
	return {
		"gorev": "T-014",
		"kaynak": kaynak_adi,
		"n": len(satirlar),
		"kazanc_ortalama": round(sum(kazanclar) / len(kazanclar), 4) if kazanclar else 0,
		"kazanc_max": round(max(kazanclar), 4) if kazanclar else 0,
		"kayma_ortalama": round(
			sum(s["kayma_kisa_kenar_orani"] for s in satirlar) / len(satirlar), 4
		)
		if satirlar
		else 0,
		"satirlar": satirlar,
	}


# ── T-015 · istemci ön-sıkıştırma / çift encode cezası ───────────────────


def komut_preflight(args) -> dict:
	"""İstemci ön-sıkıştırması + sunucu WebP zincirinin çift-encode cezası.

	İki yol karşılaştırılır, ikisi de ORİJİNALDEN türetilen master referansa göre:
	  A) tek geçiş: orijinal → WebP q80 @1920  (sunucu tek başına)
	  B) çift geçiş: orijinal → JPEG q85 @1920 (istemci) → WebP q80 (sunucu)
	Fark, `browser-image-compression`'ın araya girmesinin SSIM ve bayt maliyetidir.
	"""
	from PIL import Image, ImageOps

	sys.path.insert(0, str(KOK))
	# 1ec9b5e göçü sonrası gerçek yol (W9 T-032 düzeltmesi, 2026-08-20)
	from tradehub_core.media.pipeline.quality import compute_ssim

	def _hazirla(icerik: bytes, max_dim: int):
		im = Image.open(io.BytesIO(icerik))
		im = ImageOps.exif_transpose(im)
		if im.mode not in ("RGB", "RGBA"):
			alfali = im.mode == "LA" or (im.mode == "P" and "transparency" in im.info)
			im = im.convert("RGBA" if alfali else "RGB")
		im.thumbnail((max_dim, max_dim), Image.LANCZOS)
		return im

	fdir = Path(args.fixtures) / "media" / "images"
	adaylar = [
		"ok_product_1x1_2400.jpg",
		"ok_product_4x5.jpg",
		"enc_progressive.jpg",
		"icc_srgb_embedded.jpg",
		"exif_gps.jpg",
		"edge_short4480.jpg",
	]
	satirlar = []
	for ad in adaylar:
		p = fdir / ad
		if not p.is_file():
			continue
		icerik = p.read_bytes()
		ref = _hazirla(icerik, 1920)

		buf = io.BytesIO()
		ref.save(buf, "WEBP", quality=80, method=4)
		tek = buf.getvalue()

		# İstemci: JPEG q85, 1920 tavanı (compress.image.ts HEDEF_GENISLIK).
		cbuf = io.BytesIO()
		ref.convert("RGB").save(cbuf, "JPEG", quality=85, optimize=True, progressive=True)
		istemci = cbuf.getvalue()
		# Sunucu: engine.to_webp(quality=80) — 1920 tavanı zaten uygulanmış.
		sbuf = io.BytesIO()
		_hazirla(istemci, 1920).save(sbuf, "WEBP", quality=80, method=4)
		cift = sbuf.getvalue()

		s_tek = compute_ssim(ref, tek)
		s_cift = compute_ssim(ref, cift)
		satirlar.append(
			{
				"dosya": ad,
				"master_wh": list(ref.size),
				"tek_gecis_bytes": len(tek),
				"cift_gecis_bytes": len(cift),
				"istemci_ara_bytes": len(istemci),
				"tek_gecis_ssim": s_tek.value,
				"cift_gecis_ssim": s_cift.value,
				"ssim_cezasi": s_tek.value - s_cift.value,
				"bayt_farki": len(cift) - len(tek),
			}
		)
	return {"gorev": "T-015", "satirlar": satirlar}


# ── T-016 · video ────────────────────────────────────────────────────────


def komut_video(args) -> dict:
	"""ffprobe künyesi + ffmpeg kodlayıcı envanteri."""
	fdir = Path(args.fixtures) / "media" / "video"
	satirlar = []
	for p in sorted(fdir.glob("*")):
		try:
			ham = subprocess.run(
				[
					"ffprobe",
					"-v",
					"error",
					"-print_format",
					"json",
					"-show_format",
					"-show_streams",
					str(p),
				],
				capture_output=True,
				text=True,
				timeout=60,
			).stdout
			d = json.loads(ham)
		except Exception as exc:
			satirlar.append({"dosya": p.name, "hata": str(exc)})
			continue
		v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
		a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), {})
		fmt = d.get("format", {})
		satirlar.append(
			{
				"dosya": p.name,
				"bytes": int(fmt.get("size", 0) or 0),
				"sure_s": round(float(fmt.get("duration", 0) or 0), 2),
				"toplam_bitrate": int(fmt.get("bit_rate", 0) or 0),
				"video_codec": v.get("codec_name"),
				"w": v.get("width"),
				"h": v.get("height"),
				"video_bitrate": int(v.get("bit_rate", 0) or 0),
				"fps": v.get("avg_frame_rate"),
				"pix_fmt": v.get("pix_fmt"),
				"ses_var": bool(a),
				"ses_codec": a.get("codec_name"),
			}
		)

	kodlayicilar = {}
	try:
		cikti = subprocess.run(
			["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=60
		).stdout
		for ad in ("libvpx-vp9", "libaom-av1", "libsvtav1", "libx264", "libopus", "libwebp"):
			kodlayicilar[ad] = ad in cikti
	except Exception as exc:
		kodlayicilar["hata"] = str(exc)

	surum = ""
	try:
		surum = subprocess.run(
			["ffmpeg", "-version"], capture_output=True, text=True, timeout=30
		).stdout.splitlines()[0]
	except Exception:
		pass

	return {
		"gorev": "T-016",
		"ffmpeg_surum": surum,
		"kodlayicilar": kodlayicilar,
		"fixture_kunyeleri": satirlar,
	}


KOMUTLAR = {
	"guvenlik": komut_guvenlik,
	"korpus": komut_korpus,
	"saliency": komut_saliency,
	"preflight": komut_preflight,
	"video": komut_video,
}


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("komut", choices=sorted(KOMUTLAR))
	ap.add_argument("--fixtures", default=str(KOK / "tradehub_core" / "tests" / "fixtures"))
	ap.add_argument("--site", default="istoc.localhost")
	ap.add_argument("--site-root", default=VARSAYILAN_SITE_KOK)
	ap.add_argument("--kaynak", choices=("fixture", "canli"), default="fixture")
	ap.add_argument("--ornek", type=int, default=300)
	ap.add_argument("--tohum", type=int, default=20260818)
	ap.add_argument("--out", default="")
	args = ap.parse_args()

	t0 = time.perf_counter()
	sonuc = KOMUTLAR[args.komut](args)
	sonuc["olcum_sure_s"] = round(time.perf_counter() - t0, 2)
	metin = json.dumps(sonuc, ensure_ascii=False, indent=1)
	if args.out:
		Path(args.out).write_text(metin, encoding="utf-8")
		print(f"yazıldı: {args.out}", file=sys.stderr)
	else:
		print(metin)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

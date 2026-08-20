#!/usr/bin/env python3
"""T-013 — Hedef SSIM'e ulaşan minimum kaliteyi ÖLÇEN betik.

`docs/reports/11-faz1-arge.md` §T-013'teki her tabloyu bu betik üretir. Hiçbir
sayı elle yazılmaz; betiğin JSON çıktısı raporun kaynağıdır.

Ne ölçülür
----------
1. **Tüketici tarama**: her fixture için q=40..95 (adım 1) WebP encode edilir,
   master çözünürlükte SSIM ölçülür. Sınıf hedefini (`quality.target_ssim_per_
   class`) tutan EN DÜŞÜK kalite = `gercek_min_q` (yer gerçeği).
2. **Monotonluk**: SSIM eğrisi kalitede artan mı? İhlal sayısı ve en büyük geri
   düşüş kaydedilir — ikili aramanın dayanağı budur.
3. **İkili arama**: `tradehub_core.media.pipeline.quality.search_quality` 4 encode ile ne
   buluyor, yer gerçeğinden kaç kalite basamağı sapıyor.
4. **Bayt kazancı**: bugünkü sabit kaliteye (q80 = `engine.to_webp` varsayılanı,
   q88 = `presets.balanced`) karşı seçilen kalitenin bayt farkı.
5. **Arka uç uyumu**: numpy ve saf Python SSIM aynı sayıyı mı veriyor.
6. **Sınıflandırıcı**: `guess_content_class` fixture manifest etiketiyle uyuşuyor mu.

Koşum (konteynerde — numpy orada var):
    docker cp scripts/measure_ssim_quality.py istoc-dev-backend-1:/home/frappe/olcum/
    docker exec -w /home/frappe/olcum istoc-dev-backend-1 \
        ../frappe-bench/env/bin/python measure_ssim_quality.py --out sonuc.json
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
if str(KOK) not in sys.path:
	sys.path.insert(0, str(KOK))

# 1ec9b5e göçü sonrası gerçek yol (W9 T-032 düzeltmesi, 2026-08-20)
from tradehub_core.media.pipeline.quality import (  # noqa: E402
	compute_ssim,
	guess_content_class,
	search_quality,
	target_for,
)

# Ölçülecek fixture'lar: kalite parametresinin GERÇEKTEN etkili olduğu, animasyon
# olmayan, zararsız görseller. Sınıf etiketi manifest'ten gelir.
SECILEN = [
	"images/ok_product_1x1_2400.jpg",
	"images/ok_product_4x5.jpg",
	"images/enc_progressive.jpg",
	"images/icc_srgb_embedded.jpg",
	"images/exif_gps.jpg",
	"images/mode_cmyk.jpg",
	"images/enc_webp_lossy.webp",
	"images/content_border_08pct.png",
	"images/mode_palette_p.png",
	"images/mode_grayscale_l.png",
]

# product.image master tavanı (tradehub_core/media/pipeline/policy/slots/product-image.json).
MASTER_MAX_DIM = 2400

# Bugün kullanılan sabit kaliteler — karşılaştırma tabanı.
SABIT_KALITELER = (80, 88)

TARAMA_ARALIGI = (40, 95)


def _webp_hazirla(content: bytes, max_dim: int):
	"""WebP master'ın encode ÖNCESİ hâli — `engine.to_webp` ile aynı mod mantığı.

	`to_webp` 1920'ye sabitlenmiştir; burada `max_dim` parametrik verilir çünkü
	product.image master tavanı 2400'dür (politika). Bu fark raporun bulgusudur,
	ölçümün kendisi değil.
	"""
	from PIL import Image, ImageOps

	im = Image.open(io.BytesIO(content))
	im = ImageOps.exif_transpose(im)
	if im.mode not in ("RGB", "RGBA"):
		alfali = im.mode == "LA" or (im.mode == "P" and "transparency" in im.info)
		im = im.convert("RGBA" if alfali else "RGB")
	im.thumbnail((max_dim, max_dim), Image.LANCZOS)
	return im


def webp_encoder(content: bytes, max_dim: int, quality: int) -> tuple[bytes, str]:
	"""Politika master biçimi = webp. `(bytes, reason)` döner."""
	im = _webp_hazirla(content, max_dim)
	buf = io.BytesIO()
	im.save(buf, "WEBP", quality=quality, method=4)
	return buf.getvalue(), ""


def olc_fixture(yol: Path, sinif: str, hedef: float, max_dim: int) -> dict:
	icerik = yol.read_bytes()
	ref = _webp_hazirla(icerik, max_dim)

	egri = []
	t0 = time.perf_counter()
	for q in range(TARAMA_ARALIGI[0], TARAMA_ARALIGI[1] + 1):
		cikti, _ = webp_encoder(icerik, max_dim, q)
		olcum = compute_ssim(ref, cikti)
		egri.append({"q": q, "ssim": olcum.value, "bytes": len(cikti)})
	tarama_s = time.perf_counter() - t0

	# Yer gerçeği: hedefi tutan en düşük kalite.
	gecenler = [n for n in egri if n["ssim"] >= hedef]
	gercek_min = gecenler[0]["q"] if gecenler else None

	# Monotonluk: SSIM kalitede artan mı?
	ihlal = 0
	en_buyuk_dusus = 0.0
	for onceki, simdiki in zip(egri, egri[1:]):
		fark = simdiki["ssim"] - onceki["ssim"]
		if fark < 0:
			ihlal += 1
			en_buyuk_dusus = min(en_buyuk_dusus, fark)

	# İkili arama — 4 encode bütçesi.
	t1 = time.perf_counter()
	arama = search_quality(
		icerik,
		target_ssim=hedef,
		max_dim=max_dim,
		quality_range=TARAMA_ARALIGI,
		encoder=webp_encoder,
		reference=ref,
	)
	arama_s = time.perf_counter() - t1

	q_index = {n["q"]: n for n in egri}
	sabit = {str(q): q_index[q] for q in SABIT_KALITELER if q in q_index}

	return {
		"dosya": str(yol.name),
		"sinif": sinif,
		"tahmin_sinif": guess_content_class(icerik),
		"hedef_ssim": hedef,
		"kaynak_bytes": len(icerik),
		"master_wh": list(ref.size),
		"megapixel": round(ref.size[0] * ref.size[1] / 1e6, 3),
		"gercek_min_q": gercek_min,
		"gercek_min_ssim": q_index[gercek_min]["ssim"] if gercek_min else None,
		"gercek_min_bytes": q_index[gercek_min]["bytes"] if gercek_min else None,
		"arama_q": arama.quality,
		"arama_ssim": arama.ssim,
		"arama_bytes": arama.out_bytes,
		"arama_ok": arama.ok,
		"arama_reason": arama.reason,
		"arama_encode_sayisi": arama.encodes,
		"arama_denemeler": [
			{"q": a.quality, "ssim": a.ssim, "bytes": a.out_bytes, "gecti": a.passed}
			for a in arama.attempts
		],
		"sabit_kaliteler": sabit,
		"monotonluk_ihlal": ihlal,
		"monotonluk_en_buyuk_dusus": en_buyuk_dusus,
		"tarama_sure_s": round(tarama_s, 2),
		"arama_sure_s": round(arama_s, 3),
		"egri": egri,
	}


def arka_uc_uyumu(fixture_dir: Path) -> list[dict]:
	"""numpy ve saf Python arka uçları aynı sayıyı mı veriyor — küçük görsellerde."""
	ornekler = [
		"images/logo_alpha_512.png",
		"images/ok_avatar_96.png",
		"images/logo_jpeg_noalpha.jpg",
	]
	out = []
	for rel in ornekler:
		yol = fixture_dir / rel
		if not yol.is_file():
			continue
		icerik = yol.read_bytes()
		ref = _webp_hazirla(icerik, 512)
		cikti, _ = webp_encoder(icerik, 512, 60)
		t0 = time.perf_counter()
		a = compute_ssim(ref, cikti, backend=None, max_pixels=None)
		t_np = time.perf_counter() - t0
		t0 = time.perf_counter()
		b = compute_ssim(ref, cikti, backend="pure", max_pixels=None)
		t_pure = time.perf_counter() - t0
		out.append(
			{
				"dosya": yol.name,
				"px": a.width * a.height,
				"numpy_ssim": a.value,
				"numpy_backend": a.backend,
				"pure_ssim": b.value,
				"pure_backend": b.backend,
				"mutlak_fark": abs(a.value - b.value),
				"numpy_s": round(t_np, 4),
				"pure_s": round(t_pure, 4),
			}
		)
	return out


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--fixtures", default=str(KOK / "tradehub_core" / "tests" / "fixtures"))
	ap.add_argument("--out", default="ssim_olcum.json")
	ap.add_argument("--max-dim", type=int, default=MASTER_MAX_DIM)
	args = ap.parse_args()

	fdir = Path(args.fixtures)
	manifest = json.loads((fdir / "media" / "manifest.json").read_text(encoding="utf-8"))
	sinif_haritasi = {Path(f["file"]).name: f["class"] for f in manifest["fixtures"]}

	try:
		import numpy

		numpy_surum = numpy.__version__
	except Exception:
		numpy_surum = "YOK"
	from PIL import Image as _I

	ortam = {
		"python": sys.version.split()[0],
		"pillow": getattr(_I, "__version__", "?"),
		"numpy": numpy_surum,
		"max_dim": args.max_dim,
		"tarama_araligi": list(TARAMA_ARALIGI),
	}

	sonuclar = []
	for rel in SECILEN:
		yol = fdir / "media" / rel
		if not yol.is_file():
			print(f"ATLANDI (yok): {yol}", file=sys.stderr)
			continue
		sinif_ham = sinif_haritasi.get(yol.name, "photo")
		# manifest 'transparent' etiketini de kullanır; SSIM hedefi photo/graphic üzerinden.
		sinif = "graphic" if sinif_ham in ("graphic", "transparent") else "photo"
		hedef = target_for("product.image", sinif)
		if hedef is None:
			print(f"ATLANDI (hedef yok): {yol.name}", file=sys.stderr)
			continue
		print(f"ölçülüyor: {yol.name} sınıf={sinif} hedef={hedef}", file=sys.stderr, flush=True)
		sonuclar.append(olc_fixture(yol, sinif, hedef, args.max_dim))

	cikti = {
		"gorev": "T-013",
		"ortam": ortam,
		"fixture_olcumleri": sonuclar,
		"arka_uc_uyumu": arka_uc_uyumu(fdir / "media"),
	}
	Path(args.out).write_text(json.dumps(cikti, ensure_ascii=False, indent=1), encoding="utf-8")
	print(f"yazıldı: {args.out}", file=sys.stderr)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

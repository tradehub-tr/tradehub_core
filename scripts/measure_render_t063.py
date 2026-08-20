"""T-063 ölçüm koşumu — türev matrisinin GERÇEK maliyeti.

Tek fixture (`ok_product_1x1_2400.jpg`) üzerinde `product.image` slotunun
BÜTÜN profillerini üç biçimde üretir; süre / bayt / SSIM tablolar.

Koşum:
    python3 scripts/measure_render_t063.py

Çıktı: stdout tablosu + docs/data/t063-render-olcum.json
"""

from __future__ import annotations

import json
import platform
import sys
import time
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
if str(KOK) not in sys.path:
	sys.path.insert(0, str(KOK))

# 1ec9b5e göçü sonrası gerçek yol (W9 T-032 düzeltmesi, 2026-08-20)
from tradehub_core.media.pipeline.image import render as R  # noqa: E402
from tradehub_core.media.pipeline.image import report as REP  # noqa: E402

FIXTURE = KOK / "tradehub_core" / "tests" / "fixtures" / "media" / "images" / "ok_product_1x1_2400.jpg"
SLOT = "product.image"
BICIMLER = ("avif", "webp", "jpeg")


def main() -> int:
	import PIL
	from PIL import Image

	kaynak = FIXTURE.read_bytes()
	with Image.open(FIXTURE) as im:
		src_w, src_h, src_mode = im.width, im.height, im.mode

	profiller = R.load_profiles(SLOT)
	print(f"KAYNAK   {FIXTURE.name}  {src_w}×{src_h} {src_mode}  {len(kaynak):,} bayt")
	print(f"ORTAM    Pillow {PIL.__version__} · Python {platform.python_version()} · "
		  f"{platform.machine()} · {platform.system()}")
	print(f"SLOT     {SLOT} — politikada {len(profiller)} profil, "
		  f"{len(R.rendition_matrix(SLOT))} tanımlı rendition")
	print()

	# --- A) Tam matris: her profil × üç biçim -------------------------------
	print("A) TAM MATRİS — her profil × 3 biçim (ölçüm için biçim ZORLANDI)")
	print(f"{'profil':>7} {'biçim':>5} {'ölçü':>11} {'bayt':>9} {'KB':>8} "
		  f"{'q':>4} {'SSIM':>8} {'hedef':>6} {'enc':>4} {'ms':>8}")
	print("-" * 82)

	satirlar = []
	elenenler = []
	t_matris = time.perf_counter()
	for p in profiller:
		for f in BICIMLER:
			try:
				r = R.render_rendition(kaynak, p, None, fmt=f, allow_passthrough=False)
			except R.RenderError as exc:
				# INV-05 fayda kapısı bu biçimi eledi — ölçümün parçasıdır, hata değil.
				elenenler.append((p.name, f, str(exc)))
				print(f"{p.name:>7} {f:>5} {'—':>11} {'ELENDİ':>9} "
					  f"{'INV-05: çıktı kaynaktan büyük':>45}")
				continue
			satirlar.append(r)
			vekil = " [SSIM VEKİL]" if r.ssim_proxy else ""
			print(f"{p.name:>7} {r.format:>5} {r.width:>5}×{r.height:<5} "
				  f"{r.size_bytes:>9,} {r.size_bytes / 1024:>8.1f} "
				  f"{str(r.quality):>4} {r.ssim:>8.5f} {r.ssim_target:>6.2f} "
				  f"{r.encodes:>4} {r.elapsed_ms:>8.1f}{vekil}")
	matris_sn = time.perf_counter() - t_matris

	toplam_bayt = sum(r.size_bytes for r in satirlar)
	print("-" * 82)
	print(f"TOPLAM   {len(satirlar)} rendition · {toplam_bayt:,} bayt "
		  f"({toplam_bayt / 1024:.1f} KB) · {matris_sn:.2f} sn · "
		  f"{sum(r.encodes for r in satirlar)} encode")
	print()

	# --- B) Biçim başına toplam --------------------------------------------
	print("B) BİÇİM BAŞINA (7 profilin toplamı)")
	print(f"{'biçim':>6} {'bayt':>10} {'KB':>9} {'kaynağa oran':>13} {'sn':>7} {'SSIM min':>9}")
	print("-" * 60)
	bicim_ozet = {}
	for f in BICIMLER:
		grup = [r for r in satirlar if r.format == f]
		if not grup:
			continue
		b = sum(r.size_bytes for r in grup)
		sn = sum(r.elapsed_ms for r in grup) / 1000.0
		smin = min(r.ssim for r in grup)
		bicim_ozet[f] = {"bytes": b, "kb": round(b / 1024, 1), "seconds": round(sn, 3),
						 "ssim_min": round(smin, 6), "count": len(grup)}
		print(f"{f:>6} {b:>10,} {b / 1024:>9.1f} {b / len(kaynak):>12.3f}× "
			  f"{sn:>7.2f} {smin:>9.5f}")
	print()

	# --- C) Üretim zinciri (politika neyi seçiyor) --------------------------
	print("C) ÜRETİM ZİNCİRİ — politikanın formats[] sırası, INV-05 fayda kapısı açık")
	t_zincir = time.perf_counter()
	uretim = R.render_ladder(kaynak, SLOT)
	zincir_sn = time.perf_counter() - t_zincir
	print(f"{'profil':>7} {'kazanan':>7} {'ölçü':>11} {'bayt':>9} {'q':>4} "
		  f"{'SSIM':>8} {'elenen':>28}")
	print("-" * 82)
	for r in uretim:
		elenen = ", ".join(f"{a.format}:{a.reason}" for a in r.attempts if not a.accepted) or "—"
		print(f"{r.profile.name:>7} {r.format:>7} {r.width:>5}×{r.height:<5} "
			  f"{r.size_bytes:>9,} {str(r.quality):>4} {r.ssim:>8.5f} {elenen:>28}")
	uretim_bayt = sum(r.size_bytes for r in uretim)
	print("-" * 82)
	print(f"TOPLAM   {len(uretim)} rendition · {uretim_bayt:,} bayt "
		  f"({uretim_bayt / 1024:.1f} KB) · {zincir_sn:.2f} sn · "
		  f"kaynağın {uretim_bayt / len(kaynak):.3f}× katı")
	print()

	# --- D) Bugünkü tek çıktı ile karşılaştırma -----------------------------
	print("D) BUGÜN vs T-063")
	from tradehub_core.media import engine as canli

	t0 = time.perf_counter()
	bugun = canli.to_webp(kaynak)
	bugun_sn = time.perf_counter() - t0
	bugun_bayt = len(bugun) if isinstance(bugun, (bytes, bytearray)) else len(bugun[0])
	print(f"bugün (engine.to_webp, tek 1920px WebP): {bugun_bayt:,} bayt · {bugun_sn:.2f} sn · "
		  f"1 rendition · srcset ÜRETİLEMEZ (tek genişlik)")
	print(f"T-063 üretim zinciri:                    {uretim_bayt:,} bayt · {zincir_sn:.2f} sn · "
		  f"{len(uretim)} rendition · srcset {len(uretim)} basamak")
	print()

	rapor = REP.build_report(kaynak, uretim, slot_key=SLOT, asset_id="fixture:ok_product_1x1_2400")
	print(f"SSIM arka ucu: {rapor['quality']['backend']} · "
		  f"vekil üzerinde ölçülen türev: {rapor['quality']['proxy_measured']}/{len(uretim)}")
	print()
	print("E) KALİTE RAPORU (T-066) — Türkçe özet")
	print(REP.summarize_tr(rapor))

	cikti = {
		"fixture": FIXTURE.name,
		"source": {"width": src_w, "height": src_h, "mode": src_mode, "bytes": len(kaynak)},
		"env": {"pillow": PIL.__version__, "python": platform.python_version(),
				"machine": platform.machine(), "system": platform.system()},
		"slot": SLOT,
		"matrix_forced": {
			"formats": list(BICIMLER),
			"rejected_by_gate": [
				{"profile": a, "format": b, "reason": c} for a, b, c in elenenler
			],
			"count": len(satirlar),
			"bytes": toplam_bayt,
			"seconds": round(matris_sn, 3),
			"encodes": sum(r.encodes for r in satirlar),
			"rows": [r.as_dict() for r in satirlar],
			"by_format": bicim_ozet,
		},
		"production_chain": {
			"count": len(uretim),
			"bytes": uretim_bayt,
			"seconds": round(zincir_sn, 3),
			"rows": [r.as_dict() for r in uretim],
		},
		"today_single_output": {"bytes": bugun_bayt, "seconds": round(bugun_sn, 3), "count": 1},
		"report": rapor,
	}
	hedef = KOK / "docs" / "data" / "t063-render-olcum.json"
	hedef.parent.mkdir(parents=True, exist_ok=True)
	hedef.write_text(json.dumps(cikti, ensure_ascii=False, indent="\t"), encoding="utf-8")
	print(f"\nJSON: {hedef}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

"""T-066 — Varlık başına JSON kalite raporu + Türkçe özet.

**Çözdüğü problem.** Bir varlık için onlarca türev üretiliyor (politika
matrisi: 9 slot toplam 48 rendition tanımı; `product.image` tek başına 12).
"İyi mi oldu" sorusunun cevabı bugün hiçbir yerde yazılı değil: kod tabanında
tek bir kalite ölçümü yok (`docs/standards/policies` ve `slot-policy.schema.json`
`quality.metric` açıklaması: grep `ssim|butteraugli|dssim` → 0 anlamlı sonuç).
Bu modül her varlık için makine-okunur bir künye ve insan-okunur bir özet üretir.

Rapor **ÖLÇÜMDÜR, TAHMİN DEĞİL**. Ölçülemeyen alan `null` bırakılır ve özet
metninde "ÖLÇÜLMEDİ" diye geçer; sayı uydurulmaz. `RenditionResult.ssim`
değeri 0 ise (politika SSIM aramıyor, `bit_exact`) rapor bunu "hedef yok"
olarak yazar, "SSIM 0" olarak değil — ikisi bambaşka şeylerdir.

KULLANIM
--------
    from tradehub_core.media.pipeline.image.render import render_ladder
    from tradehub_core.media.pipeline.image.report import build_report, summarize_tr, write_report

    sonuclar = render_ladder(baytlar, "product.image", per_format=True)
    rapor = build_report(baytlar, sonuclar, slot_key="product.image", asset_id="LST-1")
    print(summarize_tr(rapor))
    write_report("raporlar/LST-1.json", rapor)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Sequence

from tradehub_core.media.pipeline.image import render as render_mod
from tradehub_core.media.pipeline.image.render import RenditionResult

REPORT_SCHEMA_VERSION: str = "1.0.0"

# Not kodlarının Türkçe karşılıkları. Kod stabil kalır (makine okur), metin
# değişebilir (insan okur) — ikisini karıştırmak i18n'i imkânsız kılar.
NOTE_TR: dict = {
	render_mod.NOTE_UNDER_SPEC: "hedef genişlik kaynaktan büyük — büyütme yapılmadı",
	render_mod.NOTE_ALPHA_FLATTENED: "alfa kanalı dolgu rengine kompozit edildi",
	render_mod.NOTE_CMYK_TO_SRGB: "CMYK → sRGB dönüşümü uygulandı",
	render_mod.NOTE_PALETTE_EXPANDED: "paletli görsel RGB/RGBA'ya açıldı",
	render_mod.NOTE_EXIF_APPLIED: "EXIF rotasyonu piksele işlendi",
	render_mod.NOTE_PREMULTIPLIED: "yeniden örnekleme çarpılmış alfa uzayında yapıldı",
	render_mod.NOTE_PADDED: "hedef orana dolgu ile tamamlandı",
	render_mod.NOTE_CROPPED: "kadraj uygulandı",
	render_mod.NOTE_PASSTHROUGH: "fayda kapısı (INV-05) tüm biçimleri eledi — kaynak olduğu gibi geçti",
	render_mod.NOTE_OVERSIZE: "türev bayt tavanını aştı",
	render_mod.NOTE_NO_DOWNSCALE: "küçültme yok — ölçü değişmedi",
	render_mod.NOTE_SSIM_UNREACHED: "hedef SSIM encode bütçesi içinde tutturulamadı",
	render_mod.NOTE_SSIM_UNKNOWN: "bu slot için SSIM hedefi yok (kayıpsız hat)",
	render_mod.NOTE_QUALITY_FLOOR: "arama kalite tabanına dayandı — gerçek minimum daha düşük olabilir",
	render_mod.NOTE_LOSSLESS: "kayıpsız kodlandı",
	render_mod.NOTE_ICC_KEPT: "ICC profili taşındı",
	render_mod.NOTE_SSIM_PROXY: (
		"SSIM tam çözünürlükte değil, küçültülmüş vekil üzerinde ölçüldü — sayı iyimser"
	),
}

SEVERITY_ERROR: str = "error"
SEVERITY_WARN: str = "warn"
SEVERITY_INFO: str = "info"


def _tr_note(code: str) -> str:
	return NOTE_TR.get(code, code)


def _kb(n: int) -> str:
	return f"{n / 1024.0:,.1f} KB".replace(",", "·")


def _yuzde(x: float) -> str:
	return f"%{x * 100:.1f}"


# --- Varlık künyesi ---------------------------------------------------------


def asset_facts(source: bytes) -> dict:
	"""Kaynağın ölçülen künyesi. Açılamıyorsa `readable=False` — hata atmaz."""
	import hashlib
	import io

	out: dict = {
		"bytes": len(source),
		"sha256": hashlib.sha256(bytes(source)).hexdigest(),
		"readable": False,
		"format": None,
		"mode": None,
		"width": None,
		"height": None,
		"megapixels": None,
		"has_alpha": None,
		"icc_profile": None,
		"dpi": None,
	}
	try:
		Image, _ = render_mod._pil()
		with Image.open(io.BytesIO(bytes(source))) as im:
			out.update(
				readable=True,
				format=(im.format or "").upper(),
				mode=im.mode,
				width=im.width,
				height=im.height,
				megapixels=round((im.width * im.height) / 1_000_000.0, 3),
				has_alpha=im.mode in render_mod.ALPHA_MODES or "transparency" in im.info,
				icc_profile=bool(im.info.get("icc_profile")),
				dpi=list(im.info["dpi"]) if im.info.get("dpi") else None,
			)
	except Exception:
		pass
	return out


# --- Bulgular ---------------------------------------------------------------


def findings(results: Sequence[RenditionResult]) -> list:
	"""Raporun "neye bakmalıyım" listesi. Her bulgu bir türeve bağlıdır."""
	out: list = []
	for r in results:
		if r.ssim_target > 0 and r.ssim and r.ssim < r.ssim_target:
			out.append(
				{
					"severity": SEVERITY_ERROR,
					"code": "ssim_below_target",
					"rendition": r.name,
					"tr": (
						f"{r.name}: SSIM {r.ssim:.4f} < hedef {r.ssim_target:.2f} "
						f"({r.content_class} sınıfı) — {r.encodes} encode bütçesi yetmedi"
					),
				}
			)
		if r.profile.max_bytes and r.size_bytes > r.profile.max_bytes:
			out.append(
				{
					"severity": SEVERITY_WARN,
					"code": "derivative_oversize",
					"rendition": r.name,
					"tr": (
						f"{r.name}: {_kb(r.size_bytes)} > tavan {_kb(r.profile.max_bytes)}"
					),
				}
			)
		if r.upscale_blocked:
			out.append(
				{
					"severity": SEVERITY_WARN,
					"code": "under_spec",
					"rendition": r.name,
					"tr": (
						f"{r.name}: hedef {r.profile.width}px, üretilen {r.width}px — "
						"kaynak yetmedi, büyütme yapılmadı (FR-028)"
					),
				}
			)
		if r.passthrough:
			out.append(
				{
					"severity": SEVERITY_WARN,
					"code": "passthrough",
					"rendition": r.name,
					"tr": f"{r.name}: fayda kapısı tüm biçimleri eledi, kaynak geçti",
				}
			)
		if r.ssim_proxy:
			out.append(
				{
					"severity": SEVERITY_WARN,
					"code": "ssim_proxy",
					"rendition": r.name,
					"tr": (
						f"{r.name}: SSIM {r.ssim:.4f} küçültülmüş vekil üzerinde ölçüldü "
						f"(arka uç={r.ssim_backend}, numpy yok). Gerçek çözünürlükte SSIM "
						"DAHA DÜŞÜKTÜR; seçilen kalite gereğinden düşük olabilir. "
						"Ölçüm ortamına numpy kurulmalı."
					),
				}
			)
		if render_mod.NOTE_QUALITY_FLOOR in r.notes:
			out.append(
				{
					"severity": SEVERITY_INFO,
					"code": "quality_floor",
					"rendition": r.name,
					"tr": (
						f"{r.name}: kalite tabanına (q={r.quality}) dayandı; daha düşük "
						"kalite de hedefi tutabilir — arama aralığı genişletilebilir"
					),
				}
			)
		if r.profile.quality_for(r.format) is None and isinstance(r.quality, int):
			out.append(
				{
					"severity": SEVERITY_INFO,
					"code": "quality_calibration",
					"rendition": r.name,
					"tr": (
						f"{r.name}: politikada encoder_quality.{r.format} null (kalibre "
						f"edilmemiş); ölçülen değer q={r.quality} — politikaya yazılabilir"
					),
				}
			)
	return out


# --- Rapor ------------------------------------------------------------------


def build_report(
	source: bytes,
	results: Sequence[RenditionResult],
	*,
	slot_key: str = "",
	asset_id: str = "",
	extra: Optional[dict] = None,
) -> dict:
	"""Varlık başına makine-okunur kalite raporu.

	`results` boş olabilir (hiç türev üretilmedi) — rapor yine üretilir ve
	`totals.count = 0` ile bunu söyler; boş rapor, rapor olmamasından iyidir.
	"""
	slot = slot_key or (results[0].slot_key if results else "")
	varlik = asset_facts(source)
	satirlar = [r.as_dict() for r in results]

	toplam_bayt = sum(r.size_bytes for r in results)
	olculen = [r for r in results if r.ssim_target > 0 and r.ssim]
	hedef_tutmayan = [r for r in results if r.ssim_target > 0 and r.ssim and r.ssim < r.ssim_target]

	matris = render_mod.rendition_matrix(slot) if slot else ()
	rapor = {
		"schema_version": REPORT_SCHEMA_VERSION,
		"engine": {"id": render_mod.ENGINE_ID, "version": render_mod.ENGINE_VERSION},
		"asset": dict(varlik, id=asset_id or None),
		"slot": slot or None,
		"policy": {
			"quality": render_mod.quality_targets(slot) if slot else {},
			"matrix_defined": len(matris),
			"profiles_defined": len(render_mod.load_profiles(slot)) if slot else 0,
		},
		"renditions": satirlar,
		"totals": {
			"count": len(results),
			"bytes": toplam_bayt,
			"kb": round(toplam_bayt / 1024.0, 1),
			"encodes": sum(r.encodes for r in results),
			"elapsed_ms": round(sum(r.elapsed_ms for r in results), 1),
			"vs_source_ratio": (
				round(toplam_bayt / varlik["bytes"], 4) if varlik["bytes"] else None
			),
			"largest": max(results, key=lambda r: r.size_bytes).name if results else None,
			"smallest": min(results, key=lambda r: r.size_bytes).name if results else None,
			"passthrough": sum(1 for r in results if r.passthrough),
			"under_spec": sum(1 for r in results if r.upscale_blocked),
		},
		"quality": {
			"measured_count": len(olculen),
			"unmeasured_count": len(results) - len(olculen),
			"ssim_min": round(min((r.ssim for r in olculen), default=0.0), 6) or None,
			"ssim_max": round(max((r.ssim for r in olculen), default=0.0), 6) or None,
			"ssim_mean": (
				round(sum(r.ssim for r in olculen) / len(olculen), 6) if olculen else None
			),
			"below_target": [r.name for r in hedef_tutmayan],
			"content_class": results[0].content_class if results else None,
			"backend": next((r.ssim_backend for r in results if r.ssim_backend), None),
			"proxy_measured": sum(1 for r in results if r.ssim_proxy),
		},
		"findings": findings(results),
	}
	if extra:
		rapor["extra"] = extra
	rapor["verdict"] = verdict(rapor)
	rapor["summary_tr"] = summarize_tr(rapor)
	return rapor


def verdict(report: dict) -> str:
	"""`ok` | `warn` | `fail`. Bulgu şiddetlerinden türetilir, ayrı kural yok."""
	seviyeler = {f["severity"] for f in report.get("findings") or ()}
	if SEVERITY_ERROR in seviyeler:
		return "fail"
	if SEVERITY_WARN in seviyeler:
		return "warn"
	return "ok"


# --- Türkçe özet ------------------------------------------------------------

_BASLIKLAR = ("profil", "biçim", "ölçü", "bayt", "q", "SSIM", "hedef", "ms")


def rendition_table(report: dict) -> str:
	"""Türevleri tek bakışta okunur bir tabloya dizer (sabit genişlik, terminal)."""
	satirlar = report.get("renditions") or []
	if not satirlar:
		return "(türev yok)"
	veriler = []
	for r in satirlar:
		veriler.append(
			(
				str(r["profile"]),
				str(r["format"]),
				f"{r['width']}×{r['height']}",
				f"{r['bytes']:,}".replace(",", "."),
				str(r["quality"]),
				f"{r['ssim']:.4f}" if r["ssim"] else "—",
				f"{r['ssim_target']:.2f}" if r["ssim_target"] else "—",
				f"{r['elapsed_ms']:.0f}",
			)
		)
	genislik = [max(len(_BASLIKLAR[i]), max(len(v[i]) for v in veriler)) for i in range(len(_BASLIKLAR))]
	cizgi = "  ".join("-" * g for g in genislik)
	out = ["  ".join(_BASLIKLAR[i].ljust(genislik[i]) for i in range(len(_BASLIKLAR))), cizgi]
	for v in veriler:
		out.append("  ".join(v[i].ljust(genislik[i]) for i in range(len(v))))
	return "\n".join(out)


def summarize_tr(report: dict) -> str:
	"""İnsan-okunur Türkçe özet. JSON'a `summary_tr` olarak da gömülür."""
	a = report["asset"]
	t = report["totals"]
	q = report["quality"]
	satirlar: list = []

	kimlik = a.get("id") or a["sha256"][:12]
	if a["readable"]:
		satirlar.append(
			f"Varlık {kimlik} — {a['format']} {a['width']}×{a['height']} ({a['megapixels']} MP), "
			f"{a['mode']}, {_kb(a['bytes'])}"
			+ (", alfa var" if a["has_alpha"] else "")
			+ (", ICC gömülü" if a["icc_profile"] else "")
		)
	else:
		satirlar.append(f"Varlık {kimlik} — OKUNAMADI ({_kb(a['bytes'])})")

	slot = report.get("slot") or "(slot yok)"
	tanimli = report["policy"]["matrix_defined"]
	satirlar.append(
		f"Slot {slot}: politikada {report['policy']['profiles_defined']} profil / "
		f"{tanimli} rendition tanımlı; bu koşuda {t['count']} türev üretildi."
	)

	if t["count"]:
		oran = t["vs_source_ratio"]
		satirlar.append(
			f"Toplam çıktı {_kb(t['bytes'])} ({t['count']} dosya), kaynağın "
			+ (f"{oran:.2f} katı" if oran is not None else "ÖLÇÜLMEDİ katı")
			+ f". {t['encodes']} encode, {t['elapsed_ms']:.0f} ms."
		)
		satirlar.append(f"En büyük türev: {t['largest']} · en küçük: {t['smallest']}.")

	if q["measured_count"]:
		satirlar.append(
			f"SSIM ({q['content_class']} sınıfı): en düşük {q['ssim_min']:.4f}, "
			f"ortalama {q['ssim_mean']:.4f}, en yüksek {q['ssim_max']:.4f} "
			f"({q['measured_count']} türevde ölçüldü)."
		)
	else:
		satirlar.append("SSIM ÖLÇÜLMEDİ — bu slotta kalite metriği SSIM değil ya da hedef tanımsız.")
	if q["unmeasured_count"]:
		satirlar.append(f"{q['unmeasured_count']} türevde kalite ölçülmedi.")

	bulgular = report.get("findings") or []
	if not bulgular:
		satirlar.append("Bulgu yok.")
	else:
		sayac: dict = {}
		for f in bulgular:
			sayac[f["severity"]] = sayac.get(f["severity"], 0) + 1
		ozet = ", ".join(f"{v} {k}" for k, v in sorted(sayac.items()))
		satirlar.append(f"Bulgular ({ozet}):")
		for f in bulgular:
			satirlar.append(f"  [{f['severity']}] {f['tr']}")

	satirlar.append(f"Karar: {report.get('verdict', '?').upper()}")
	return "\n".join(satirlar)


def render_text_report(report: dict) -> str:
	"""Özet + tablo — terminale basılacak tam metin."""
	return summarize_tr(report) + "\n\n" + rendition_table(report)


def write_report(path, report: dict) -> Path:
	"""JSON raporu diske yaz (UTF-8, sekme girintili — depoda okunabilir kalsın)."""
	p = Path(path)
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(json.dumps(report, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")
	return p


def merge_reports(reports: Sequence[dict]) -> dict:
	"""Çok varlıklı toplu özet — migration koşusu için."""
	if not reports:
		return {"schema_version": REPORT_SCHEMA_VERSION, "assets": 0}
	toplam_kaynak = sum(r["asset"]["bytes"] for r in reports)
	toplam_cikti = sum(r["totals"]["bytes"] for r in reports)
	ssimler = [r["quality"]["ssim_min"] for r in reports if r["quality"]["ssim_min"]]
	kararlar: dict = {}
	for r in reports:
		k = r.get("verdict", "?")
		kararlar[k] = kararlar.get(k, 0) + 1
	return {
		"schema_version": REPORT_SCHEMA_VERSION,
		"assets": len(reports),
		"source_bytes": toplam_kaynak,
		"output_bytes": toplam_cikti,
		"renditions": sum(r["totals"]["count"] for r in reports),
		"elapsed_ms": round(sum(r["totals"]["elapsed_ms"] for r in reports), 1),
		"ssim_min": round(min(ssimler), 6) if ssimler else None,
		"verdicts": kararlar,
		"summary_tr": (
			f"{len(reports)} varlık, {sum(r['totals']['count'] for r in reports)} türev. "
			f"Kaynak {_kb(toplam_kaynak)} → çıktı {_kb(toplam_cikti)} "
			f"({toplam_cikti / toplam_kaynak:.2f}×). "
			+ (f"En düşük SSIM {min(ssimler):.4f}. " if ssimler else "SSIM ÖLÇÜLMEDİ. ")
			+ "Kararlar: "
			+ ", ".join(f"{v} {k}" for k, v in sorted(kararlar.items()))
		),
	}


__all__ = [
	"REPORT_SCHEMA_VERSION",
	"NOTE_TR",
	"asset_facts",
	"findings",
	"build_report",
	"verdict",
	"rendition_table",
	"summarize_tr",
	"render_text_report",
	"write_report",
	"merge_reports",
]

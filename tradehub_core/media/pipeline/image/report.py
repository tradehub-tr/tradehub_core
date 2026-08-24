"""T-066 — Varlık başına JSON kalite raporu + Türkçe özet.

**Çözdüğü problem.** Bir varlık için onlarca türev üretiliyor (sayı politika
verisinden çalışma anında okunur; rapora `matrix_defined` olarak yazılır).
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
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tradehub_core.media.pipeline.image import lcp_impact
from tradehub_core.media.pipeline.image import render as render_mod
from tradehub_core.media.pipeline.image.render import RenditionResult

REPORT_SCHEMA_VERSION: str = "2.0.0"
MONTHLY_REPORT_SCHEMA_VERSION: str = "1.1.0"

BYTES_PER_GB: int = 1_000_000_000
WORST_ASSET_LIMIT: int = 20
MONTHLY_IMAGE_JOB_TYPES: tuple[str, ...] = ("normalize", "rendition")
MONTHLY_TERMINAL_JOB_STATUSES: tuple[str, ...] = ("success", "failed", "dead")
MONTHLY_FAILED_JOB_STATUSES: tuple[str, ...] = ("failed", "dead")

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


def _mb_tr(n: int) -> str:
	"""Baytı satıcı metni için Türkçe ondalık ayraçlı MB olarak biçimlendir."""
	return f"{n / 1_000_000.0:.1f} MB".replace(".", ",")


def _dpi_pair(value: Any) -> list[float] | None:
	"""Pillow/DocType DPI biçimlerini JSON uyumlu iki sayıya indirger."""
	if value is None:
		return None
	if isinstance(value, (int, float)):
		return [float(value), float(value)]
	if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and value:
		try:
			first = float(value[0])
			second = float(value[1] if len(value) > 1 else value[0])
			return [first, second]
		except (TypeError, ValueError):
			return None
	return None


def _normalized_facts(extra: Mapping[str, Any] | None) -> dict[str, Any] | None:
	"""Çağıranın gerçek normalize ölçümünü ortak rapor biçimine çevir.

	Boyut/DPI uydurulmaz. `NormalizeResult.to_dict()` ya da doğrudan sözlük
	kabul edilir; alan yoksa `None` bırakılır.
	"""
	if not extra:
		return None
	ham: Any = extra.get("normalized") or extra.get("normalize")
	if ham is None:
		return None
	if hasattr(ham, "to_dict"):
		ham = ham.to_dict()
	if not isinstance(ham, Mapping):
		return None
	return {
		"width": int(ham.get("width") or 0) or None,
		"height": int(ham.get("height") or 0) or None,
		"dpi": _dpi_pair(ham.get("dpi") or ham.get("dpi_out")),
		"format": ham.get("fmt") or ham.get("format"),
		"bytes": int(ham.get("size_bytes") or ham.get("bytes") or 0) or None,
		"notes": list(ham.get("notes") or ()),
	}


def _json_safe_extra(extra: Mapping[str, Any]) -> dict[str, Any]:
	"""Beklenen ölçüm nesnelerini kayıpsız JSON değerlerine dönüştür."""

	def convert(value: Any) -> Any:
		if hasattr(value, "to_dict"):
			return convert(value.to_dict())
		if isinstance(value, Mapping):
			return {str(key): convert(item) for key, item in value.items()}
		if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
			return [convert(item) for item in value]
		if isinstance(value, date):
			return value.isoformat()
		if value is None or isinstance(value, (str, int, float, bool)):
			return value
		raise TypeError(f"rapor extra alanı JSON'a çevrilemedi: {type(value).__name__}")

	return convert(extra)


def _profile_quality(results: Sequence[RenditionResult]) -> list[dict[str, Any]]:
	"""Profil başına ölçülen SSIM'i kalıcılaştırılabilir satırlara dönüştür."""
	return [
		{
			"profile": r.profile.name,
			"format": r.format,
			"ssim": round(r.ssim, 6) if r.ssim_target > 0 and r.ssim else None,
			"target": r.ssim_target or None,
			"measured": bool(r.ssim_target > 0 and r.ssim),
			"passed": r.ssim_ok,
			"backend": r.ssim_backend or None,
			"proxy": r.ssim_proxy,
		}
		for r in results
	]


def decisions(results: Sequence[RenditionResult]) -> list[dict[str, Any]]:
	"""Hangi kuralın neden uygulandığını stabil, makine-okunur biçimde yaz."""
	out: list[dict[str, Any]] = []
	for r in results:
		codes = list(r.notes)
		out.append(
			{
				"rendition": r.name,
				"profile": r.profile.name,
				"action": "passthrough" if r.passthrough else "encoded",
				"selected_format": r.format,
				"quality": r.quality,
				"output_bytes": r.size_bytes,
				"saving_ratio": round(r.saving_ratio, 6),
				"reason_codes": codes,
				"reasons_tr": [_tr_note(code) for code in codes],
				"attempts": [
					{
						"format": a.format,
						"accepted": a.accepted,
						"reason": a.reason or None,
						"bytes": a.out_bytes,
						"quality": a.quality,
						"ssim": round(a.ssim, 6) if a.ssim else None,
					}
					for a in r.attempts
				],
			}
		)
	return out


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
					"tr": (f"{r.name}: {_kb(r.size_bytes)} > tavan {_kb(r.profile.max_bytes)}"),
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
	version_id: str = "",
	extra: Mapping[str, Any] | None = None,
) -> dict:
	"""Varlık başına makine-okunur kalite raporu.

	`results` boş olabilir (hiç türev üretilmedi) — rapor yine üretilir ve
	`totals.count = 0` ile bunu söyler; boş rapor, rapor olmamasından iyidir.
	"""
	slot = slot_key or (results[0].slot_key if results else "")
	varlik = asset_facts(source)
	satirlar = [r.as_dict() for r in results]

	toplam_bayt = sum(r.size_bytes for r in results)
	kazanilan_bayt = varlik["bytes"] - toplam_bayt
	tasarruf_orani = round(kazanilan_bayt / varlik["bytes"], 6) if varlik["bytes"] else None
	olculen = [r for r in results if r.ssim_target > 0 and r.ssim]
	hedef_tutmayan = [r for r in results if r.ssim_target > 0 and r.ssim and r.ssim < r.ssim_target]
	bulgular = findings(results)
	normalized = _normalized_facts(extra)

	matris = render_mod.rendition_matrix(slot) if slot else ()
	rapor = {
		"schema_version": REPORT_SCHEMA_VERSION,
		"engine": {"id": render_mod.ENGINE_ID, "version": render_mod.ENGINE_VERSION},
		"asset": dict(varlik, id=asset_id or None, version=version_id or None),
		"slot": slot or None,
		"policy": {
			"quality": render_mod.quality_targets(slot) if slot else {},
			"matrix_defined": len(matris),
			"profiles_defined": len(render_mod.load_profiles(slot)) if slot else 0,
		},
		"renditions": satirlar,
		"processing": {"normalized": normalized},
		"savings": {
			"original_bytes": varlik["bytes"],
			"optimized_bytes": toplam_bayt,
			# İşaret bilinçli korunur: merdiven kaynaktan büyükse sahte bir
			# "tasarruf" yazmak yerine negatif değer raporlanır.
			"saved_bytes": kazanilan_bayt,
			"saving_ratio": tasarruf_orani,
			"has_saving": kazanilan_bayt > 0,
		},
		"totals": {
			"count": len(results),
			"bytes": toplam_bayt,
			"kb": round(toplam_bayt / 1024.0, 1),
			"encodes": sum(r.encodes for r in results),
			"elapsed_ms": round(sum(r.elapsed_ms for r in results), 1),
			"vs_source_ratio": (round(toplam_bayt / varlik["bytes"], 4) if varlik["bytes"] else None),
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
			"ssim_mean": (round(sum(r.ssim for r in olculen) / len(olculen), 6) if olculen else None),
			"below_target": [r.name for r in hedef_tutmayan],
			"content_class": results[0].content_class if results else None,
			"backend": next((r.ssim_backend for r in results if r.ssim_backend), None),
			"proxy_measured": sum(1 for r in results if r.ssim_proxy),
			"by_profile": _profile_quality(results),
		},
		"decisions": decisions(results),
		"warnings": [f for f in bulgular if f["severity"] in {SEVERITY_WARN, SEVERITY_ERROR}],
		"findings": bulgular,
	}
	if extra:
		rapor["extra"] = _json_safe_extra(extra)
		lcp = extra.get("lcp_impact_ms")
		if lcp is not None:
			rapor["impact"] = {"lcp_ms": float(lcp), "measured": True}
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


def seller_summary_tr(report: Mapping[str, Any]) -> str:
	"""Satıcıya gösterilecek tek cümlelik, ölçüme dayalı Türkçe özet.

	DPI yalnız metadata olduğundan, değer değiştiğinde piksel çözünürlüğünün DPI
	nedeniyle düşürülmediği açıkça söylenir. Normalize ölçümü verilmediyse DPI
	ve master boyutu uydurulmaz; en büyük gerçek türev boyutu kullanılır.
	"""
	asset = report["asset"]
	savings = report.get("savings") or {}
	normalized = (report.get("processing") or {}).get("normalized") or {}
	renditions = report.get("renditions") or []

	source_size = None
	if asset.get("width") and asset.get("height"):
		source_size = (int(asset["width"]), int(asset["height"]))
	target_size = None
	if normalized.get("width") and normalized.get("height"):
		target_size = (int(normalized["width"]), int(normalized["height"]))
	elif renditions:
		largest = max(renditions, key=lambda row: int(row.get("width") or 0) * int(row.get("height") or 0))
		if largest.get("width") and largest.get("height"):
			target_size = (int(largest["width"]), int(largest["height"]))

	parcalar = ["Görseliniz optimize edildi"]
	if source_size and target_size:
		parcalar.append(f"{source_size[0]}×{source_size[1]} → {target_size[0]}×{target_size[1]} piksel")
	elif source_size:
		parcalar.append(f"kaynak {source_size[0]}×{source_size[1]} piksel")

	source_dpi = _dpi_pair(asset.get("dpi"))
	target_dpi = _dpi_pair(normalized.get("dpi"))
	if source_dpi and target_dpi:
		sd = round(source_dpi[0])
		td = round(target_dpi[0])
		parcalar.append(f"{sd}→{td} dpi (DPI metadata değişti; piksel çözünürlüğü korundu)")
	elif source_dpi:
		parcalar.append(f"kaynak DPI {round(source_dpi[0])}; çıktı DPI değeri ölçülmedi")

	original = int(savings.get("original_bytes") or asset.get("bytes") or 0)
	optimized = int(savings.get("optimized_bytes") or 0)
	if original:
		ratio = savings.get("saving_ratio")
		boyut = f"{_mb_tr(original)} → {_mb_tr(optimized)}"
		if ratio is None:
			parcalar.append(boyut)
		elif ratio >= 0:
			parcalar.append(f"{boyut} ({_yuzde(float(ratio))} tasarruf)")
		else:
			parcalar.append(f"{boyut} ({_yuzde(abs(float(ratio)))} ek depolama)")

	return "; ".join(parcalar) + "."


def summarize_tr(report: dict) -> str:
	"""İnsan-okunur Türkçe özet. JSON'a `summary_tr` olarak da gömülür."""
	a = report["asset"]
	t = report["totals"]
	q = report["quality"]
	satirlar: list = [seller_summary_tr(report)]

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


# --- Aylık platform raporu --------------------------------------------------


def _iso_date(value: date | str) -> str:
	if isinstance(value, date):
		return value.isoformat()
	text = str(value or "").strip()
	# Değerin takvim tarihi olduğunu burada doğrula; DocType'a serbest metin
	# sızarsa dönem sıralaması bozulur.
	return date.fromisoformat(text).isoformat()


def _asset_row(report: Mapping[str, Any]) -> dict[str, Any]:
	asset = report.get("asset") or {}
	savings = report.get("savings") or {}
	totals = report.get("totals") or {}
	quality = report.get("quality") or {}
	impact = report.get("impact") or {}
	return {
		"asset": asset.get("id") or asset.get("sha256"),
		"slot": report.get("slot"),
		"original_bytes": int(savings.get("original_bytes") or asset.get("bytes") or 0),
		"output_bytes": int(savings.get("optimized_bytes") or totals.get("bytes") or 0),
		"saved_bytes": int(savings.get("saved_bytes") or 0),
		"saving_ratio": savings.get("saving_ratio"),
		"ssim_min": quality.get("ssim_min"),
		"elapsed_ms": float(totals.get("elapsed_ms") or 0.0),
		"lcp_impact_ms": impact.get("lcp_ms"),
		"verdict": report.get("verdict") or "?",
	}


def _worst_assets(rows: Sequence[dict[str, Any]], limit: int = WORST_ASSET_LIMIT) -> list[dict[str, Any]]:
	"""En büyük çıktılar ile en düşük SSIM'leri tek, deterministik listede birleştir."""
	if limit <= 0:
		return []
	# İki ayrı sinyalin birinin diğerini boğmaması için yarı yarıya aday alınır.
	large = sorted(rows, key=lambda row: (-row["output_bytes"], str(row["asset"])))
	measured = [row for row in rows if row.get("ssim_min") is not None]
	low_ssim = sorted(measured, key=lambda row: (float(row["ssim_min"]), -row["output_bytes"]))

	selected: list[dict[str, Any]] = []
	seen: set[str] = set()
	half = max(1, limit // 2)
	for reason, candidates in (("largest_output", large[:half]), ("lowest_ssim", low_ssim[:half])):
		for row in candidates:
			key = str(row["asset"])
			if key in seen:
				continue
			selected.append(dict(row, ranking_reason=reason))
			seen.add(key)
	for row in large:
		if len(selected) >= min(limit, len(rows)):
			break
		key = str(row["asset"])
		if key not in seen:
			selected.append(dict(row, ranking_reason="largest_output"))
			seen.add(key)
	return selected[:limit]


def build_monthly_report(
	reports: Sequence[Mapping[str, Any]],
	*,
	period_start: date | str,
	period_end: date | str,
	failure_count: int = 0,
	total_job_count: int | None = None,
	lcp_measurement: lcp_impact.LcpImpactMeasurement | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
	"""Varlık raporlarından aylık platform özeti üret.

	LCP etkisi production scheduler'da aynı RUM kohortundaki ``original`` ve
	``w*`` örneklerinden gelir. Eski/enjekte edilmiş asset raporlarındaki
	``lcp_impact_ms`` yalnız geriye uyumlu saf çağrı yoludur. Örnek yoksa
	``None`` kalır; sıfır uydurulmaz.
	"""
	baslangic = _iso_date(period_start)
	bitis = _iso_date(period_end)
	if bitis < baslangic:
		raise ValueError("period_end period_start'tan once olamaz")
	if failure_count < 0:
		raise ValueError("failure_count negatif olamaz")
	if total_job_count is None:
		raise ValueError("total_job_count ölçülmeden hata oranı hesaplanamaz")
	if total_job_count < 0:
		raise ValueError("total_job_count negatif olamaz")
	if failure_count > total_job_count:
		raise ValueError("failure_count total_job_count değerini aşamaz")

	rows = [_asset_row(report) for report in reports]
	processed = len(rows)
	saved_bytes = sum(row["saved_bytes"] for row in rows)
	lcp_values = [float(row["lcp_impact_ms"]) for row in rows if row.get("lcp_impact_ms") is not None]
	measurement_payload: dict[str, Any] | None = None
	if lcp_measurement is not None:
		measurement_payload = (
			lcp_measurement.as_dict()
			if isinstance(lcp_measurement, lcp_impact.LcpImpactMeasurement)
			else dict(lcp_measurement)
		)
		measured_average = measurement_payload.get("average_impact_ms")
		average_lcp_impact_ms = (
			round(float(measured_average), 3) if measured_average is not None else None
		)
	else:
		average_lcp_impact_ms = round(sum(lcp_values) / len(lcp_values), 3) if lcp_values else None
	elapsed = [row["elapsed_ms"] for row in rows]

	slots: dict[str, dict[str, int]] = {}
	for row in rows:
		key = str(row.get("slot") or "unknown")
		bucket = slots.setdefault(
			key, {"assets": 0, "original_bytes": 0, "output_bytes": 0, "saved_bytes": 0}
		)
		bucket["assets"] += 1
		for field in ("original_bytes", "output_bytes", "saved_bytes"):
			bucket[field] += int(row[field])

	report: dict[str, Any] = {
		"schema_version": MONTHLY_REPORT_SCHEMA_VERSION,
		"report_type": "monthly",
		"period_key": baslangic[:7],
		"period": {"start": baslangic, "end": bitis},
		"processed_assets": processed,
		"total_job_count": total_job_count,
		"failure_count": failure_count,
		# Payda asset raporu sayısı değildir: aynı asset/version için upload, lazy
		# ve retry işleri olabilir. Hata oranı dönemin terminal image işlerinden
		# ölçülür; asset raporu dedupe'u yalnız depolama/kalite toplamını etkiler.
		"failure_rate": round(failure_count / total_job_count, 6) if total_job_count else 0.0,
		"original_bytes": sum(row["original_bytes"] for row in rows),
		"output_bytes": sum(row["output_bytes"] for row in rows),
		"saved_bytes": saved_bytes,
		"saved_gb": round(saved_bytes / BYTES_PER_GB, 6),
		"average_processing_ms": round(sum(elapsed) / len(elapsed), 3) if elapsed else None,
		"average_lcp_impact_ms": average_lcp_impact_ms,
		"lcp_measured_assets": len(lcp_values),
		"lcp_measured_samples": int(
			(measurement_payload or {}).get("comparable_samples") or 0
		),
		"lcp_comparable_cohorts": int(
			(measurement_payload or {}).get("comparable_cohorts") or 0
		),
		"lcp_measurement": measurement_payload,
		"slot_distribution": dict(sorted(slots.items())),
		"worst_20": _worst_assets(rows),
	}
	report["summary_tr"] = monthly_summary_tr(report)
	report["markdown"] = render_monthly_markdown(report)
	return report


def monthly_summary_tr(report: Mapping[str, Any]) -> str:
	"""Aylık platform raporunun kısa Türkçe özeti."""
	lcp = report.get("average_lcp_impact_ms")
	lcp_text = f"{float(lcp):.1f} ms" if lcp is not None else "ÖLÇÜLMEDİ"
	return (
		f"{report['period']['start']}–{report['period']['end']}: "
		f"{report['processed_assets']} asset işlendi; net {float(report['saved_gb']):.3f} GB "
		f"tasarruf; ortalama LCP etkisi {lcp_text}; hata oranı "
		f"%{float(report['failure_rate']) * 100:.2f} "
		f"({report['failure_count']}/{report['total_job_count']} terminal iş)."
	)


def render_monthly_markdown(report: Mapping[str, Any]) -> str:
	"""Aylık raporun sürüm kontrolüne uygun Markdown karşılığı."""
	lines = [
		f"# Aylık Medya Kalite Raporu · {report['period']['start']}–{report['period']['end']}",
		"",
		str(report["summary_tr"]),
		"",
		"## Özet",
		"",
		"| Ölçüm | Değer |",
		"|---|---:|",
		f"| İşlenen asset | {report['processed_assets']} |",
		f"| Terminal image işi | {report['total_job_count']} |",
		f"| Net tasarruf | {report['saved_gb']:.6f} GB ({report['saved_bytes']} bayt) |",
		f"| Ortalama işleme | {report['average_processing_ms'] if report['average_processing_ms'] is not None else 'ÖLÇÜLMEDİ'} ms |",
		f"| Ortalama LCP etkisi | {report['average_lcp_impact_ms'] if report['average_lcp_impact_ms'] is not None else 'ÖLÇÜLMEDİ'} ms (pozitif = daha hızlı) |",
		f"| Karşılaştırılabilir LCP örneği | {report.get('lcp_measured_samples', 0)} ({report.get('lcp_comparable_cohorts', 0)} kohort) |",
		f"| Hata | {report['failure_count']} (%{report['failure_rate'] * 100:.2f}) |",
		"",
		"## En kötü 20 asset",
		"",
		"| # | Asset | Slot | Çıktı bayt | En düşük SSIM | Neden |",
		"|---:|---|---|---:|---:|---|",
	]
	for index, row in enumerate(report.get("worst_20") or (), start=1):
		asset = str(row.get("asset") or "?").replace("|", "\\|")
		ssim = "ÖLÇÜLMEDİ" if row.get("ssim_min") is None else f"{row['ssim_min']:.6f}"
		lines.append(
			f"| {index} | {asset} | {row.get('slot') or '?'} | {row['output_bytes']} | "
			f"{ssim} | {row['ranking_reason']} |"
		)
	lines.extend(["", "## Slot dağılımı", "", "| Slot | Asset | Tasarruf bayt |", "|---|---:|---:|"])
	for slot, values in (report.get("slot_distribution") or {}).items():
		lines.append(f"| {slot} | {values['assets']} | {values['saved_bytes']} |")
	return "\n".join(lines) + "\n"


def write_monthly_markdown(path: str | Path, report: Mapping[str, Any]) -> Path:
	p = Path(path)
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(str(report.get("markdown") or render_monthly_markdown(report)), encoding="utf-8")
	return p


# --- DocType kalıcılığı + Prometheus ----------------------------------------


def doctype_payload(report: Mapping[str, Any]) -> dict[str, Any]:
	"""Varlık ya da aylık raporu `Media Quality Report` alanlarına eşle."""
	if report.get("report_type") == "monthly":
		return {
			"doctype": "Media Quality Report",
			"report_type": "monthly",
			"period_key": report["period_key"],
			"period_start": report["period"]["start"],
			"period_end": report["period"]["end"],
			"processed_assets": report["processed_assets"],
			"total_job_count": report["total_job_count"],
			"failure_count": report["failure_count"],
			"failure_rate": report["failure_rate"],
			"input_bytes": report["original_bytes"],
			"output_bytes": report["output_bytes"],
			"saved_bytes": report["saved_bytes"],
			"saved_gb": report["saved_gb"],
			"average_processing_ms": report["average_processing_ms"],
			"average_lcp_impact_ms": report["average_lcp_impact_ms"],
			"slot_distribution": json.dumps(report["slot_distribution"], ensure_ascii=False),
			"worst_assets": json.dumps(report["worst_20"], ensure_ascii=False),
			"summary_tr": report["summary_tr"],
			"markdown": report["markdown"],
			"report_json": json.dumps(report, ensure_ascii=False),
		}

	asset = report.get("asset") or {}
	savings = report.get("savings") or {}
	quality = report.get("quality") or {}
	return {
		"doctype": "Media Quality Report",
		"report_type": "asset",
		"asset": asset.get("id"),
		"version": asset.get("version"),
		"slot": report.get("slot"),
		"engine_version": (report.get("engine") or {}).get("version"),
		"input_bytes": savings.get("original_bytes"),
		"output_bytes": savings.get("optimized_bytes"),
		"saved_bytes": savings.get("saved_bytes"),
		"saving_ratio": savings.get("saving_ratio"),
		"ssim": quality.get("ssim_mean"),
		"vmaf": quality.get("vmaf"),
		"ssim_by_profile": json.dumps(quality.get("by_profile") or [], ensure_ascii=False),
		"decisions": json.dumps(report.get("decisions") or [], ensure_ascii=False),
		"warnings": json.dumps(report.get("warnings") or [], ensure_ascii=False),
		"summary_tr": report.get("summary_tr"),
		"report_json": json.dumps(report, ensure_ascii=False),
	}


def persist_report(
	report: Mapping[str, Any],
	*,
	insert: Callable[[dict[str, Any]], Any] | None = None,
) -> Any:
	"""Raporu DocType'a yaz; `insert` bağımlılık enjeksiyonu AAA testleri içindir."""
	payload = doctype_payload(report)
	if insert is not None:
		return insert(payload)
	import frappe

	return frappe.get_doc(payload).insert(ignore_permissions=True)


def persist_monthly_report(
	reports: Sequence[Mapping[str, Any]],
	*,
	period_start: date | str,
	period_end: date | str,
	markdown_path: str | Path,
	failure_count: int = 0,
	total_job_count: int | None = None,
	lcp_measurement: lcp_impact.LcpImpactMeasurement | Mapping[str, Any] | None = None,
	insert: Callable[[dict[str, Any]], Any] | None = None,
) -> tuple[dict[str, Any], Any, Path]:
	"""Aylık raporu bir kez üretip hem DocType'a hem Markdown'a yazar."""
	monthly = build_monthly_report(
		reports,
		period_start=period_start,
		period_end=period_end,
		failure_count=failure_count,
		total_job_count=total_job_count,
		lcp_measurement=lcp_measurement,
	)
	path = write_monthly_markdown(markdown_path, monthly)
	doc = persist_report(monthly, insert=insert)
	return monthly, doc, path


def previous_month_period(as_of: date | str) -> tuple[date, date]:
	"""Verilen gün için tam kapanmış önceki takvim ayını döndür."""
	gun = as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of))
	bu_ay = gun.replace(day=1)
	bitis = bu_ay - timedelta(days=1)
	return bitis.replace(day=1), bitis


def monthly_failure_filters(period_start: date, period_end: date) -> list[list[Any]]:
	"""Aylık hata oranının production `Media Processing Job` sorgu sözleşmesi."""
	next_month = period_end + timedelta(days=1)
	return [
		["job_type", "in", list(MONTHLY_IMAGE_JOB_TYPES)],
		["status", "in", list(MONTHLY_FAILED_JOB_STATUSES)],
		["finished_at", ">=", f"{period_start.isoformat()} 00:00:00"],
		["finished_at", "<", f"{next_month.isoformat()} 00:00:00"],
	]


def monthly_total_job_filters(period_start: date, period_end: date) -> list[list[Any]]:
	"""Hata oranının paydasındaki tüm terminal image işlerinin sorgu sözleşmesi."""
	next_month = period_end + timedelta(days=1)
	return [
		["job_type", "in", list(MONTHLY_IMAGE_JOB_TYPES)],
		["status", "in", list(MONTHLY_TERMINAL_JOB_STATUSES)],
		["finished_at", ">=", f"{period_start.isoformat()} 00:00:00"],
		["finished_at", "<", f"{next_month.isoformat()} 00:00:00"],
	]


def _persisted_asset_reports(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
	"""DocType JSON'unu doğrula ve asset/version başına en son raporu seç.

	Upload ve lazy üretim aynı sürüm için ayrı kayıt bırakabilir. Satırlar giriş
	sırasına güvenmeden `(creation, name)` ile sıralanır; böylece aynı kalıcı
	veri her worker'da aynı aylık toplamı üretir.
	"""
	latest: dict[tuple[str, str], dict[str, Any]] = {}
	ordered = sorted(rows, key=lambda row: (str(row.get("creation") or ""), str(row.get("name") or "")))
	for row in ordered:
		raw = row.get("report_json")
		try:
			parsed = raw if isinstance(raw, Mapping) else json.loads(str(raw or ""))
		except (TypeError, ValueError, json.JSONDecodeError) as exc:
			raise ValueError(f"bozuk Media Quality Report JSON: {row.get('name') or '?'}") from exc
		if not isinstance(parsed, Mapping) or not isinstance(parsed.get("asset"), Mapping):
			raise ValueError(f"gecersiz asset kalite raporu: {row.get('name') or '?'}")
		asset = parsed["asset"]
		asset_id = asset.get("id") or asset.get("sha256")
		if not asset_id:
			raise ValueError(f"kimliksiz asset kalite raporu: {row.get('name') or '?'}")
		key = (str(asset_id), str(asset.get("version") or ""))
		latest[key] = dict(parsed)
	return [latest[key] for key in sorted(latest)]


def _document_name(document: Any) -> str | None:
	if isinstance(document, Mapping):
		return document.get("name")
	return getattr(document, "name", None)


def run_previous_month_report(
	as_of: date | str | None = None,
	*,
	fetch_rows: Callable[[date, date], Sequence[Mapping[str, Any]]] | None = None,
	fetch_failure_count: Callable[[date, date], int | None] | None = None,
	fetch_total_job_count: Callable[[date, date], int | None] | None = None,
	fetch_lcp_rows: Callable[[date, date], Sequence[Mapping[str, Any]]] | None = None,
	find_existing: Callable[[str], Any] | None = None,
	insert: Callable[[dict[str, Any]], Any] | None = None,
	markdown_path: str | Path | None = None,
) -> dict[str, Any]:
	"""Scheduler entrypoint: önceki ayın kalıcı asset raporlarını tek raporda topla.

	`period_key` hem erken dönüş kapısı hem DocType'ta unique alandır. İki
	scheduler aynı anda başlarsa yalnız bir insert kazanır; kaybeden, unique
	ihlalinden sonra oluşan kaydı okuyup `existing` döner. Bozuk JSON atlanmaz:
	eksik toplam yayımlamak yerine iş kırmızı olur.
	"""
	frappe_module: Any = None
	production_dependencies_needed = (
		fetch_rows is None
		or fetch_failure_count is None
		or fetch_total_job_count is None
		or find_existing is None
		or insert is None
		or markdown_path is None
	)
	if production_dependencies_needed:
		import frappe as frappe_module

		if not frappe_module.db.exists(
			"DocType", "Media Quality Report"
		) or not frappe_module.db.table_exists("Media Quality Report"):
			return {"status": "not_installed", "doctype": "Media Quality Report"}

	if as_of is None:
		if frappe_module is not None:
			from frappe.utils import getdate, nowdate

			as_of = getdate(nowdate())
		else:  # Yalnız tüm bağımlılıkların enjekte edildiği saf çağrı yolu.
			as_of = date.today()
	period_start, period_end = previous_month_period(as_of)
	period_key = period_start.strftime("%Y-%m")

	if find_existing is None:

		def find_existing(key: str) -> Any:
			return frappe_module.db.exists(
				"Media Quality Report", {"report_type": "monthly", "period_key": key}
			)

	if fetch_rows is None:
		next_month = period_end + timedelta(days=1)

		def fetch_rows(start: date, _end: date) -> Sequence[Mapping[str, Any]]:
			return frappe_module.get_all(
				"Media Quality Report",
				filters=[
					["report_type", "=", "asset"],
					["creation", ">=", f"{start.isoformat()} 00:00:00"],
					["creation", "<", f"{next_month.isoformat()} 00:00:00"],
				],
				fields=["name", "creation", "report_json"],
				order_by="creation asc, name asc",
				limit_page_length=0,
			)

	if fetch_failure_count is None or fetch_total_job_count is None:
		if not frappe_module.db.exists(
			"DocType", "Media Processing Job"
		) or not frappe_module.db.table_exists("Media Processing Job"):
			raise RuntimeError("Media Processing Job kurulmadığı için aylık hata oranı ölçülemedi")

	if fetch_failure_count is None:

		def fetch_failure_count(start: date, end: date) -> int:
			return int(
				frappe_module.db.count(
					"Media Processing Job",
					filters=monthly_failure_filters(start, end),
				)
			)

	if fetch_total_job_count is None:

		def fetch_total_job_count(start: date, end: date) -> int:
			return int(
				frappe_module.db.count(
					"Media Processing Job",
					filters=monthly_total_job_filters(start, end),
				)
			)

	if fetch_lcp_rows is None:
		if frappe_module is None:

			def fetch_lcp_rows(_start: date, _end: date) -> Sequence[Mapping[str, Any]]:
				return ()

		elif not frappe_module.db.exists(
			"DocType", "Media RUM Sample"
		) or not frappe_module.db.table_exists("Media RUM Sample"):

			def fetch_lcp_rows(_start: date, _end: date) -> Sequence[Mapping[str, Any]]:
				return ()

		else:

			def fetch_lcp_rows(start: date, end: date) -> Sequence[Mapping[str, Any]]:
				return frappe_module.get_all(
					"Media RUM Sample",
					filters=lcp_impact.monthly_lcp_filters(start, end),
					fields=[
						"metric",
						"value",
						"sample_rate",
						"route",
						"lcp_region",
						"device_class",
						"viewport_bucket",
						"dpr",
						"connection",
						"navigation_type",
						"lcp_profile",
						"engine_version",
					],
					limit_page_length=0,
				)

	if insert is None:

		def insert(payload: dict[str, Any]) -> Any:
			return frappe_module.get_doc(payload).insert(ignore_permissions=True)

	if markdown_path is None:
		markdown_path = frappe_module.get_site_path(
			"private", "files", "media-quality-reports", f"{period_key}.md"
		)

	existing = find_existing(period_key)
	if existing:
		return {"status": "existing", "period_key": period_key, "name": str(existing)}

	rows = list(fetch_rows(period_start, period_end))
	reports = _persisted_asset_reports(rows)
	failure_count = fetch_failure_count(period_start, period_end)
	total_job_count = fetch_total_job_count(period_start, period_end)
	lcp_measurement = lcp_impact.measure_lcp_impact(
		list(fetch_lcp_rows(period_start, period_end))
	)
	if failure_count is None:
		raise RuntimeError("Aylık Media Processing Job hata sayısı ölçülemedi")
	if total_job_count is None:
		raise RuntimeError("Aylık Media Processing Job toplam sayısı ölçülemedi")
	if int(failure_count) < 0:
		raise ValueError("Aylık Media Processing Job hata sayısı negatif olamaz")
	if int(total_job_count) < 0:
		raise ValueError("Aylık Media Processing Job toplam sayısı negatif olamaz")
	try:
		monthly, document, written = persist_monthly_report(
			reports,
			period_start=period_start,
			period_end=period_end,
			markdown_path=markdown_path,
			failure_count=int(failure_count),
			total_job_count=int(total_job_count),
			lcp_measurement=lcp_measurement,
			insert=insert,
		)
	except Exception:
		# Check-then-insert yarışında unique period_key'yi başka worker aldıysa
		# başarı say; başka her hata eksiksiz traceback ile yukarı çıksın.
		existing = find_existing(period_key)
		if existing:
			return {"status": "existing", "period_key": period_key, "name": str(existing)}
		raise

	return {
		"status": "created",
		"period_key": period_key,
		"name": _document_name(document),
		"asset_reports": len(reports),
		"failed_jobs": int(failure_count),
		"total_jobs": int(total_job_count),
		"saved_gb": monthly["saved_gb"],
		"average_lcp_impact_ms": monthly["average_lcp_impact_ms"],
		"lcp_measured_samples": monthly["lcp_measured_samples"],
		"markdown_path": str(written),
	}


def record_report_metrics(report: Mapping[str, Any]) -> None:
	"""Başarılı bir asset raporunu T-066'nın dört Prometheus serisine işler."""
	from tradehub_core.media.pipeline.observability import metrics

	slot = str(report.get("slot") or "unknown")
	outcome = str(report.get("verdict") or "ok")
	metrics.MEDIA_PROCESSED_TOTAL.inc(slot=slot, outcome=outcome)
	saved = int((report.get("savings") or {}).get("saved_bytes") or 0)
	metrics.BYTES_SAVED_TOTAL.inc(max(0, saved), preset=slot, outcome="saved" if saved > 0 else "no_saving")
	elapsed = float((report.get("totals") or {}).get("elapsed_ms") or 0.0) / 1000.0
	metrics.MEDIA_JOB_DURATION_SECONDS.observe(elapsed, job="image_render", outcome=outcome)


def record_job_failure(
	*, job: str = "image_render", reason: str = "unknown", duration_s: float = 0.0
) -> None:
	"""Rapor üretilemeyen hata yolunu süre + hata sayacıyla görünür kılar."""
	from tradehub_core.media.pipeline.observability import metrics

	metrics.MEDIA_JOB_DURATION_SECONDS.observe(max(0.0, duration_s), job=job, outcome="failed")
	metrics.MEDIA_JOB_FAILURES_TOTAL.inc(job=job, reason=reason or "unknown")


__all__ = [
	"BYTES_PER_GB",
	"MONTHLY_REPORT_SCHEMA_VERSION",
	"MONTHLY_FAILED_JOB_STATUSES",
	"MONTHLY_IMAGE_JOB_TYPES",
	"MONTHLY_TERMINAL_JOB_STATUSES",
	"REPORT_SCHEMA_VERSION",
	"NOTE_TR",
	"WORST_ASSET_LIMIT",
	"asset_facts",
	"build_monthly_report",
	"findings",
	"build_report",
	"decisions",
	"doctype_payload",
	"monthly_summary_tr",
	"monthly_failure_filters",
	"monthly_total_job_filters",
	"persist_monthly_report",
	"persist_report",
	"previous_month_period",
	"record_job_failure",
	"record_report_metrics",
	"render_monthly_markdown",
	"run_previous_month_report",
	"verdict",
	"rendition_table",
	"seller_summary_tr",
	"summarize_tr",
	"render_text_report",
	"write_report",
	"write_monthly_markdown",
	"merge_reports",
]

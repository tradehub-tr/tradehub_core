/**
 * T-100 — TypeScript parite koşucusu.
 *
 * `tests/fixtures/crop_vectors.json` içindeki her vektörü `crop_geometry.ts`
 * ile koşar ve beklenen değerle karşılaştırır. Amaç tek bir soruyu ÖLÇMEK:
 * TypeScript ikizi, Python'un uyduğu referansla aynı sayıyı veriyor mu?
 *
 * Çalıştırma (derleme adımı YOK — Node tipleri soyar):
 *
 *     node --experimental-strip-types tests/tools/run_ts_vectors.ts
 *
 * Çıktı: son satırda tek satırlık JSON özet. `tests/test_crop_geometry.py`
 * bu koşucuyu çağırır, özeti okur ve uyuşmazlık varsa DÜŞER — parite iddia
 * değil, test edilmiş bir olgudur.
 *
 * Çıkış kodu: uyuşmazlık varsa 1, yoksa 0.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import {
	CropGeometryError,
	clampWindow,
	cropWindow,
	focalFromWindow,
	ratioFit,
	rect,
	roundWindow,
	zoomBase,
	zoomFromBase,
	type FitMode,
	type Rect,
} from "../../media/pipeline/core/crop_geometry.ts";

const BURASI = dirname(fileURLToPath(import.meta.url));
const VEKTOR_DOSYASI = join(BURASI, "..", "fixtures", "crop_vectors.json");

interface Vektor {
	id: string;
	fn: string;
	case: string;
	in: Record<string, unknown>;
	out?: Record<string, unknown>;
	error?: boolean;
}

function asRect(value: unknown): Rect {
	const v = value as Record<string, number>;
	return rect(v.x, v.y, v.w, v.h);
}

function num(value: unknown): number {
	return value as number;
}

function nullableNum(value: unknown): number | null {
	return value === null || value === undefined ? null : (value as number);
}

/** Vektörü koştur; sonucu düz bir sayı sözlüğüne indir. */
function calistir(v: Vektor): Record<string, number> {
	const g = v.in;
	switch (v.fn) {
		case "cropWindow": {
			const r = cropWindow(
				num(g.source_w),
				num(g.source_h),
				asRect(g.base),
				nullableNum(g.target_ar),
				num(g.focal_x),
				num(g.focal_y),
			);
			return { x: r.x, y: r.y, w: r.w, h: r.h };
		}
		case "clampWindow": {
			const r = clampWindow(asRect(g.win), asRect(g.bounds), g.keep_ratio as boolean);
			return { x: r.x, y: r.y, w: r.w, h: r.h };
		}
		case "ratioFit": {
			const [w, h] = ratioFit(num(g.w), num(g.h), nullableNum(g.target_ar), g.mode as FitMode);
			return { w, h };
		}
		case "zoomBase": {
			const r = zoomBase(num(g.source_w), num(g.source_h), num(g.zoom), num(g.center_x), num(g.center_y));
			return { x: r.x, y: r.y, w: r.w, h: r.h };
		}
		case "zoomFromBase": {
			return { zoom: zoomFromBase(num(g.source_w), num(g.source_h), asRect(g.base)) };
		}
		case "focalFromWindow": {
			const p = focalFromWindow(asRect(g.win), num(g.source_w), num(g.source_h));
			return { x: p.x, y: p.y };
		}
		case "roundWindow": {
			const box = roundWindow(asRect(g.win), nullableNum(g.source_w), nullableNum(g.source_h));
			return { box0: box[0], box1: box[1], box2: box[2], box3: box[3] };
		}
		default:
			throw new Error(`Bilinmeyen fonksiyon: ${v.fn}`);
	}
}

function beklenen(v: Vektor): Record<string, number> {
	const o = v.out as Record<string, unknown>;
	if (v.fn === "roundWindow") {
		const box = o.box as number[];
		return { box0: box[0], box1: box[1], box2: box[2], box3: box[3] };
	}
	const out: Record<string, number> = {};
	for (const k of Object.keys(o)) {
		out[k] = o[k] as number;
	}
	return out;
}

function main(): void {
	const paket = JSON.parse(readFileSync(VEKTOR_DOSYASI, "utf-8"));
	const tolerans: number = paket.tolerance_px;
	const vektorler: Vektor[] = paket.vectors;

	const uyusmazliklar: Array<Record<string, unknown>> = [];
	let enBuyukSapma = 0.0;
	let enBuyukSapmaId = "";
	let hataVakasi = 0;
	let kosulan = 0;

	for (const v of vektorler) {
		if (v.error === true) {
			hataVakasi += 1;
			let atti = false;
			try {
				calistir(v);
			} catch (e) {
				// Yalnız BİZİM hatamız sayılır; TypeError sessiz bir kaza olurdu.
				atti = e instanceof CropGeometryError;
				if (!atti) {
					uyusmazliklar.push({ id: v.id, case: v.case, sorun: `beklenmeyen hata tipi: ${String(e)}` });
					continue;
				}
			}
			if (!atti) {
				uyusmazliklar.push({ id: v.id, case: v.case, sorun: "hata bekleniyordu, atmadı" });
			}
			continue;
		}

		kosulan += 1;
		let gercek: Record<string, number>;
		try {
			gercek = calistir(v);
		} catch (e) {
			uyusmazliklar.push({ id: v.id, case: v.case, sorun: `beklenmedik istisna: ${String(e)}` });
			continue;
		}
		const bekle = beklenen(v);
		for (const k of Object.keys(bekle)) {
			const sapma = Math.abs(gercek[k] - bekle[k]);
			if (sapma > enBuyukSapma) {
				enBuyukSapma = sapma;
				enBuyukSapmaId = `${v.id} ${v.case} .${k}`;
			}
			const sinir = v.fn === "roundWindow" ? 0 : tolerans;
			if (!(sapma <= sinir)) {
				uyusmazliklar.push({
					id: v.id,
					case: v.case,
					alan: k,
					beklenen: bekle[k],
					gercek: gercek[k],
					sapma,
				});
			}
		}
	}

	const ozet = {
		toplam: vektorler.length,
		kosulan,
		hata_vakasi: hataVakasi,
		uyusmazlik: uyusmazliklar.length,
		en_buyuk_sapma_px: enBuyukSapma,
		en_buyuk_sapma_vektor: enBuyukSapmaId,
		ilk_uyusmazliklar: uyusmazliklar.slice(0, 10),
	};
	console.log(JSON.stringify(ozet));
	process.exit(uyusmazliklar.length === 0 ? 0 : 1);
}

main();

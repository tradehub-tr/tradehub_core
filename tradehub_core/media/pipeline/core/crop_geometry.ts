/**
 * T-100 — Crop Studio'nun saf geometrisi (PİKSEL uzayı) · TypeScript ikizi.
 *
 * Bu dosya `crop_geometry.py`'nin **birebir kopyasıdır**. "Benzer" değil,
 * birebir: aynı sabitler, aynı fonksiyon adları, aynı işlem sırası, aynı
 * sıkıştırma kuralları. Tarayıcıda kullanıcının gördüğü kadraj ile sunucunun
 * kestiği kadraj ayrışırsa ortaya kimsenin yeniden üretemeyeceği bir hata
 * çıkar; bu ikizlik o hatanın panzehiridir.
 *
 * **İkisini birlikte değiştir.** Buradaki bir satırı Python'daki eşi olmadan
 * düzenlersen `tests/test_crop_geometry.py` sessiz kalır (Python hâlâ kendi
 * vektörlerini geçer) ama `tests/tools/run_ts_vectors.ts` düşer. Parite
 * ölçümü CI'da bu iki adımın ikisini de koşturmalıdır.
 *
 * Parite kuralları (Python başlığındakilerle aynı):
 *   1. Tüm aritmetik IEEE-754 double — JS `number` zaten budur.
 *   2. Yuvarlama `Math.floor(v + 0.5)`. `Math.round` doğrudan KULLANILMAZ;
 *      ikisi bu aralıkta aynıdır ama Python tarafı `floor(v+0.5)` yazdığı için
 *      burada da aynı ifade durur — okuyan kişi iki dosyayı yan yana koyup
 *      farkı gözle arayabilmeli.
 *   3. İşlem SIRASI Python ile birebir. `a*b/c` ile `a*(b/c)` farklı sayıdır.
 *   4. `Math.min`/`Math.max` yerine açık `clamp()` ve açık `if` karşılaştırmaları.
 *   5. Bağımlılık YOK. `import` satırı yoktur ve olmamalıdır.
 *
 * Yalnız silinebilir (erasable) tip sözdizimi kullanır: `enum`, `namespace`,
 * parametre-özelliği yoktur. Böylece `node --experimental-strip-types` ile
 * derlenmeden koşar ve parite ölçümü bir derleme adımına bağlı kalmaz.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Sabitler — Python ikizinde AYNI değerler
// ─────────────────────────────────────────────────────────────────────────────

/** "Aynı sayı" eşiği. */
export const EPS = 1e-9;

/** Diller arası kabul edilen azami sapma (piksel). T-100 kabul kriteri. */
export const PARITY_TOLERANCE_PX = 0.5;

/** Zoom sınırları. ZOOM_MAX ÖLÇÜLMEDİ — bkz. Python ikizindeki not. */
export const ZOOM_MIN = 1.0;
export const ZOOM_MAX = 16.0;

/** Bir pencerenin/taban bölgenin en küçük kenarı. */
export const MIN_EDGE_PX = 1.0;

/** ratioFit kipleri. */
export const FIT_INSIDE = "inside";
export const FIT_OUTSIDE = "outside";

export type FitMode = "inside" | "outside";

export const FIT_MODES: readonly FitMode[] = [FIT_INSIDE, FIT_OUTSIDE] as FitMode[];

/**
 * Geometri girdisi geçersiz — pencere üretilemez.
 *
 * Python'daki `CropGeometryError(ValueError)` ile aynı vakalarda atar. Vektör
 * dosyasında `"error": true` işaretli vakalar İKİ tarafta da atmalıdır;
 * sessizce varsayılana düşmek kullanıcıya yanlış kadrajı doğruymuş gibi
 * göstermenin en kısa yoludur.
 */
export class CropGeometryError extends Error {
	constructor(message: string) {
		super(message);
		this.name = "CropGeometryError";
	}
}

/** Piksel uzayında dikdörtgen. Kaynağın sol-üst köşesi (0, 0). */
export interface Rect {
	x: number;
	y: number;
	w: number;
	h: number;
}

/** Odak / pan merkezi — 0-1 normalize, kaynağın tamamına göre. */
export interface Point {
	x: number;
	y: number;
}

/** Tam piksel kutusu: [left, top, w, h] — PIL `crop` ile uyumlu sıra. */
export type PixelBox = [number, number, number, number];

// ─────────────────────────────────────────────────────────────────────────────
// Yardımcılar
// ─────────────────────────────────────────────────────────────────────────────

/**
 * `value`'yu [low, high] aralığına sıkıştır.
 *
 * `high < low` ise `low` döner (kayan nokta artığıyla oluşabilir). Aralık
 * içindeki bir değer DEĞİŞMEDEN döner — bu, `clampWindow`'un geçerli bir
 * pencerede tam no-op olmasını ve paritenin korunmasını sağlar.
 */
export function clamp(value: number, low: number, high: number): number {
	if (high < low) {
		return low;
	}
	if (value < low) {
		return low;
	}
	if (value > high) {
		return high;
	}
	return value;
}

/**
 * Python `math.floor(v + 0.5)` ile birebir aynı yuvarlama.
 *
 * Python'un yerleşik `round()`'u bankacı yuvarlaması yapar; oraya
 * güvenilmediği için iki tarafta da bu ifade yazılıdır.
 */
function roundHalfUp(value: number): number {
	return Math.floor(value + 0.5);
}

function requireFinite(value: number, name: string): number {
	if (typeof value !== "number" || !Number.isFinite(value)) {
		throw new CropGeometryError(`${name} sonlu bir sayı olmalı: ${String(value)}`);
	}
	return value;
}

function requirePositive(value: number, name: string): number {
	const out = requireFinite(value, name);
	if (out <= 0.0) {
		throw new CropGeometryError(`${name} pozitif olmalı: ${String(out)}`);
	}
	return out;
}

/** Doğrulanmış Rect üret. Python'daki `Rect.__post_init__` ile aynı kontroller. */
export function rect(x: number, y: number, w: number, h: number): Rect {
	requireFinite(x, "Rect.x");
	requireFinite(y, "Rect.y");
	requireFinite(w, "Rect.w");
	requireFinite(h, "Rect.h");
	if (w <= 0.0 || h <= 0.0) {
		throw new CropGeometryError(`Dikdörtgenin eni ve boyu pozitif olmalı: w=${w} h=${h}`);
	}
	return { x, y, w, h };
}

export function rectRight(r: Rect): number {
	return r.x + r.w;
}

export function rectBottom(r: Rect): number {
	return r.y + r.h;
}

export function rectCenterX(r: Rect): number {
	return r.x + r.w / 2.0;
}

export function rectCenterY(r: Rect): number {
	return r.y + r.h / 2.0;
}

/** Piksel cinsinden en-boy oranı (genişlik/yükseklik). */
export function rectRatio(r: Rect): number {
	return r.w / r.h;
}

// ─────────────────────────────────────────────────────────────────────────────
// ratioFit — orana oturtma
// ─────────────────────────────────────────────────────────────────────────────

/**
 * `w x h` kutusunu `targetAR` oranına oturt; yeni `[w, h]` döndür.
 *
 * `inside` (contain) kutunun İÇİNE sığan en büyük hedef-oranlı dikdörtgeni,
 * `outside` (cover) kutuyu KAPSAYAN en küçüğünü verir. `targetAR === null`
 * serbest orandır ve kutu değişmeden döner — kilidi açık tutamak sürüklemesi.
 */
export function ratioFit(
	w: number,
	h: number,
	targetAR: number | null,
	mode: FitMode = FIT_INSIDE as FitMode,
): [number, number] {
	const bw = requirePositive(w, "w");
	const bh = requirePositive(h, "h");
	if (targetAR === null || targetAR === undefined) {
		return [bw, bh];
	}
	const ar = requirePositive(targetAR, "target_ar");
	if (mode !== FIT_INSIDE && mode !== FIT_OUTSIDE) {
		throw new CropGeometryError(`Bilinmeyen fit kipi: ${String(mode)} (beklenen: inside, outside)`);
	}

	let outW: number;
	let outH: number;

	if (mode === FIT_INSIDE) {
		if (bw / bh > ar) {
			outH = bh;
			outW = outH * ar;
		} else {
			outW = bw;
			outH = outW / ar;
		}
		// Kutunun dışına taşma — yalnız kayan nokta artığı kadar olabilir.
		if (outW > bw) {
			outW = bw;
		}
		if (outH > bh) {
			outH = bh;
		}
		return [outW, outH];
	}

	// FIT_OUTSIDE
	if (bw / bh > ar) {
		outW = bw;
		outH = outW / ar;
	} else {
		outH = bh;
		outW = outH * ar;
	}
	if (outW < bw) {
		outW = bw;
	}
	if (outH < bh) {
		outH = bh;
	}
	return [outW, outH];
}

// ─────────────────────────────────────────────────────────────────────────────
// clampWindow — pencereyi sınırların içine hapset
// ─────────────────────────────────────────────────────────────────────────────

/**
 * `win`'i `bounds` içine sıkıştır.
 *
 * Gövde sürüklemesinin ve tutamak çekmesinin tek çıkış kapısı burasıdır:
 * kullanıcı pencereyi kaynağın dışına iteklediğinde pencere KAYAR, küçülmez.
 *
 * `keepRatio=true` iken iki kenar da AYNI çarpanla küçültülür — en-boy kilidi
 * açıkken kullanılması gereken kip budur; aksi hâlde 1:1 kilitli kullanıcı
 * 1,03:1 bir kadraj alır.
 */
export function clampWindow(win: Rect, bounds: Rect, keepRatio: boolean = false): Rect {
	let w = win.w;
	let h = win.h;

	if (keepRatio) {
		// Tek çarpan: hangi eksen daha çok taşıyorsa o belirler.
		let scale = 1.0;
		if (w > bounds.w) {
			scale = bounds.w / w;
		}
		if (h > bounds.h) {
			const other = bounds.h / h;
			if (other < scale) {
				scale = other;
			}
		}
		if (scale < 1.0) {
			w = w * scale;
			h = h * scale;
			if (w > bounds.w) {
				w = bounds.w;
			}
			if (h > bounds.h) {
				h = bounds.h;
			}
		}
	} else {
		if (w > bounds.w) {
			w = bounds.w;
		}
		if (h > bounds.h) {
			h = bounds.h;
		}
	}

	const x = clamp(win.x, bounds.x, bounds.x + bounds.w - w);
	const y = clamp(win.y, bounds.y, bounds.y + bounds.h - h);
	return rect(x, y, w, h);
}

// ─────────────────────────────────────────────────────────────────────────────
// zoomBase — zoom + pan → taban bölge
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Zoom ve pan merkezinden **taban bölgeyi** (görünür kaynak parçası) üret.
 *
 * `centerX/centerY` 0-1 normalize, kaynağın tamamına göredir — piksel değil;
 * pan merkezi kullanıcı niyetidir ve türevler arasında taşınabilir olmalıdır.
 *
 * Zoom sıkıştırması SESSİZDİR: kullanıcı fare tekerleğini çevirmeye devam
 * ettiğinde hata görmemeli, kadraj durmalıdır.
 */
export function zoomBase(
	sourceW: number,
	sourceH: number,
	zoom: number,
	centerX: number,
	centerY: number,
): Rect {
	const sw = requirePositive(sourceW, "source_w");
	const sh = requirePositive(sourceH, "source_h");
	const z = clamp(requireFinite(zoom, "zoom"), ZOOM_MIN, ZOOM_MAX);

	let bw = sw / z;
	let bh = sh / z;

	// 1 px tabanı — kaynak zaten 1 px'ten darsa kaynağın kendisi.
	const minW = sw > MIN_EDGE_PX ? MIN_EDGE_PX : sw;
	const minH = sh > MIN_EDGE_PX ? MIN_EDGE_PX : sh;
	if (bw < minW) {
		bw = minW;
	}
	if (bh < minH) {
		bh = minH;
	}
	if (bw > sw) {
		bw = sw;
	}
	if (bh > sh) {
		bh = sh;
	}

	const cx = clamp(requireFinite(centerX, "center_x"), 0.0, 1.0) * sw;
	const cy = clamp(requireFinite(centerY, "center_y"), 0.0, 1.0) * sh;

	const x = clamp(cx - bw / 2.0, 0.0, sw - bw);
	const y = clamp(cy - bh / 2.0, 0.0, sh - bh);
	return rect(x, y, bw, bh);
}

/**
 * `zoomBase`'in tersi: taban bölgeden zoom çarpanını geri oku.
 *
 * Kullanıcı pencereyi tutamaktan çekip taban bölgeyi değiştirdiğinde zoom
 * kaydırıcısının doğru yere gitmesi için gerekli.
 */
export function zoomFromBase(sourceW: number, sourceH: number, base: Rect): number {
	const sw = requirePositive(sourceW, "source_w");
	requirePositive(sourceH, "source_h");
	return clamp(sw / base.w, ZOOM_MIN, ZOOM_MAX);
}

// ─────────────────────────────────────────────────────────────────────────────
// cropWindow — çekirdek
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Taban bölge içinde, hedef orana uyan EN BÜYÜK pencereyi odakta merkezle.
 *
 * Adımlar (sıra pariteyi belirler, değiştirme):
 *   1. Taban bölge kaynağın içine sıkıştırılır (geçerli tabanda no-op).
 *   2. Hedef oran yoksa taban bölgenin kendisi döner — serbest kırpma.
 *   3. Taban bölge hedef orana `inside` kipiyle oturtulur (`ratioFit`).
 *   4. Pencere odak noktasında merkezlenir. Odak KAYNAĞIN tamamına göre
 *      normalizedir — taban bölgeye göre değil; kullanıcı zoom yaptığında
 *      odağın görsel üzerindeki yeri değişmemeli.
 *   5. Pencere taban bölgeye sıkıştırılır — kenar sıkıştırma. Odak sol üst
 *      köşede olsa bile pencere dışarı taşmaz.
 */
export function cropWindow(
	sourceW: number,
	sourceH: number,
	base: Rect,
	targetAR: number | null,
	focalX: number,
	focalY: number,
): Rect {
	const sw = requirePositive(sourceW, "source_w");
	const sh = requirePositive(sourceH, "source_h");
	const region = clampWindow(base, rect(0.0, 0.0, sw, sh));

	if (targetAR === null || targetAR === undefined) {
		return region;
	}

	const ar = requirePositive(targetAR, "target_ar");
	const fitted = ratioFit(region.w, region.h, ar, FIT_INSIDE as FitMode);
	const w = fitted[0];
	const h = fitted[1];

	const fx = clamp(requireFinite(focalX, "focal_x"), 0.0, 1.0) * sw;
	const fy = clamp(requireFinite(focalY, "focal_y"), 0.0, 1.0) * sh;

	const x = clamp(fx - w / 2.0, region.x, region.x + region.w - w);
	const y = clamp(fy - h / 2.0, region.y, region.y + region.h - h);
	return rect(x, y, w, h);
}

/**
 * `cropWindow`'un tersi: pencereden onu üreten odak noktasını geri oku.
 *
 * Kullanıcı pencereyi gövdesinden sürüklediğinde UI'nın elinde bir pencere
 * vardır, ama saklanması gereken şey odak noktasıdır. Kenar sıkıştırma
 * devredeyken birden çok odak aynı pencereyi verir; merkez bunların içinde tek
 * kararlı seçimdir.
 */
export function focalFromWindow(win: Rect, sourceW: number, sourceH: number): Point {
	const sw = requirePositive(sourceW, "source_w");
	const sh = requirePositive(sourceH, "source_h");
	return {
		x: clamp(rectCenterX(win) / sw, 0.0, 1.0),
		y: clamp(rectCenterY(win) / sh, 0.0, 1.0),
	};
}

/**
 * Pencereyi tam piksel kutusuna çevir: `[left, top, w, h]`.
 *
 * Yuvarlama SONDA yapılır; önce yuvarlayıp sonra hesaplamak 80 px'lik sepet
 * küçük resminde oranı gözle görülür biçimde kaydırır.
 */
export function roundWindow(
	win: Rect,
	sourceW: number | null = null,
	sourceH: number | null = null,
): PixelBox {
	let left = roundHalfUp(win.x);
	let top = roundHalfUp(win.y);
	let w = roundHalfUp(win.w);
	let h = roundHalfUp(win.h);
	if (w < 1) {
		w = 1;
	}
	if (h < 1) {
		h = 1;
	}
	if (sourceW !== null && sourceW !== undefined && sourceH !== null && sourceH !== undefined) {
		const sw = roundHalfUp(requirePositive(sourceW, "source_w"));
		const sh = roundHalfUp(requirePositive(sourceH, "source_h"));
		if (w > sw) {
			w = sw;
		}
		if (h > sh) {
			h = sh;
		}
		if (left > sw - w) {
			left = sw - w;
		}
		if (top > sh - h) {
			top = sh - h;
		}
	}
	if (left < 0) {
		left = 0;
	}
	if (top < 0) {
		top = 0;
	}
	return [left, top, w, h];
}

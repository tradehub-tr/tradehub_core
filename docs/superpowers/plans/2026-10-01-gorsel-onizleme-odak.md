# Görsel Önizleme ve Odak Noktası Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a seller uploads an image (or presses "Nerelerde görünecek?"), a near-full-screen window shows the image in every real storefront place at its real ratio and page context, lets the seller pick a focal point, saves it into the existing `Media Crop Intent`, and the storefront applies the same value as CSS `object-position` wherever that image is cropped (`object-fit: cover`).

**Architecture:** One registry (`placements.json → preview_places`) feeds two generated files (admin `src/lib/media/vendor/placements.js`, storefront `src/lib/media/placements.gen.ts`) through `sizes.py --emit-placements`. The admin window (`ImagePlacementModal.vue`) is built on pure geometry (`geometry.js`: `clampFocal`, `visibleFraction`, `frameRect`, `objectPosition`), a small composable (`useFocalPoint.js`) over the existing `get_intent / save_intent / suggest_focal` endpoints, and a new thin backend module (`api/media_preview.py`) that resolves *file URL + slot → Media Asset* and stores the per-user auto-open preference. The store `*_media` payloads gain `focal: {x, y}` from one shared lookup (`media/odak.py`), and the storefront turns it into `object-position`.

**Tech Stack:** Frappe v15 / Python 3.12 (ruff, tabs) · Vue 3.5 `<script setup>` + vue-i18n 11 (tr/en/ru/ar) + node:test + jsdom + axe-core (admin) · Vite 7 + Alpine 3.15 + TypeScript 5.9 strict + vitest 4 + Tailwind v4 (storefront) · Playwright (admin `tests/e2e`).

**Spec:** `/Users/ahmet/Desktop/istoc/tradehub_core/docs/superpowers/specs/2026-10-01-gorsel-onizleme-odak-design.md` · approved visual design: `/private/tmp/claude-501/-Users-ahmet-Desktop-istoc/ce4f9460-48d7-4bde-aeeb-703583ea9819/scratchpad/focal-design/project/Main.dc.html` (board 1 is binding), secondary `Mobil.dc.html`, `Giris.dc.html`, `Urun.dc.html` in the same folder.

## Global Constraints

- Three separate git repos: `tradehub_core` (branch `version-15`), `admin-panel` (`master`), `tradehubfront` (`main`). `/Users/ahmet/Desktop/istoc` itself is NOT a repo. Never run git commands from the workspace root.
- **No commits.** Every task ends with "Stage (no commit — user approves commits)". Commits/merges need the user's explicit approval each time.
- Before writing version-sensitive library code, pull docs with `context7` and name the version in the query: Frappe **v15** (`frappe.qb`, `frappe.defaults.set_user_default/get_user_default`), Vue **3.5**, vue-i18n **11**, Tailwind **v4** (no `tailwind.config.js`, no `@config`), Alpine **3.15**, TypeScript **5.9** (use the project's `tsc`, not a global 7.x), Vitest **4**. If context7 returns a different version than pinned, say so in the task report.
- Backend: ruff (tabs, line length 110), type annotations on every new whitelisted endpoint, `frappe.qb` instead of raw SQL, `frappe.throw(_("…"))` only, no bare `except Exception:` without `frappe.log_error`, `ignore_permissions=True` only with a written reason.
- Admin: `<script setup>`, no `v-html`, `@/utils/api` for HTTP, `:key` on every `v-for`, no `console.log`, SCSS `@use` only. Tests are `node:test` (no vitest in admin). Do not modify `src/composables/useCropStudio.js` (spec §4.3).
- Storefront: TS strict, no `any`, DOMPurify/`escapeHtml` for interpolated values, every new export name unique (`npm run check:dup`).
- Spec copy is Turkish and exact (design boards). Brand is written **iStoc**.
- **WCAG 2.2 AAA** (spec §5): text ≥ 7:1 using `#1d1c19`, `#3a3833`, `#4e4c45`; the panel grey `#6d6a61` is forbidden in this window; yellow `#f5b800` only as a background with `#1a1a1a` text; non-text (borders, frame, marker) ≥ 3:1; frame = white dashed + dark shadow; every target ≥ 44 × 44 px, primary buttons 48 px; focus ring `3px solid #1a1a1a`, `outline-offset: 2px`; dialog = `role="dialog"` + `aria-modal="true"` + `aria-labelledby`, place list `aria-current`, device toggle `aria-pressed`, changes via `role="status"`; focus trap, Esc closes (confirm when unsaved), focus returns to the opener.
- **Motion** (spec §6): `object-position` 260 ms; marker and frame 220 ms; easing `cubic-bezier(.2,.8,.2,1)`; stage enter 220 ms scale + opacity; dialog open 200 ms, close 160 ms; only `transform`, `opacity`, `object-position` are animated; `prefers-reduced-motion: reduce` turns all of it off.
- Focal semantics = CSS `object-position: X% Y%`; visible part = `min(1, placeRatio / imageRatio)` horizontally (vertical analogue); frame offset = `(1 − visible) × focal`. Stored as 0–1 floats in `Media Crop Intent.focal_x / focal_y`.
- Auto-open preference: Frappe user default `th_media_preview_autoopen`, default **on**, server-side (not localStorage). Opens only after a **single**-file upload, never after a batch.
- Error behaviour (spec §7): image still processing → draw with the original + "Görsel hazırlanıyor"; `suggest_focal` fails → start centred, no message; ETag conflict → "Bu görsel başka bir sekmede değiştirildi" + reload; no focal → storefront crops centre (today's behaviour); network error → window stays open, Save can be retried, the change is not lost.
- Out of scope (spec §8): share/ad images, physically cropping files, AI focal suggestion, switching product images from `contain` to `cover`.
- Local dev serves images from Docker images, not bind mounts: backend changes reach containers only via `docker cp` + restart (temporary) — the permanent fix is the source repo + image rebuild; frontends need `docker compose build` + `up -d --no-deps`.

## Review Focus

1. **Unknown image size.** `File.th_media_width/height` is 0 for most legacy files and the `<img>` has not loaded yet → the window and the badge must show ratio/size only, never "%0 görünüyor" or `NaN`, and count 0 cut places. Pinned in Task 6 (`placeVisibility(place, 0)` → `unknown: true`, `cutPlaceCount(…, 0) === 0`).
2. **URL changes after the focal is saved.** `kare.py` / `magaza_gorseli.py` move a converted image to a new content-addressed URL, archive the old `Media Asset` and create a new one on the *same* `File` row. The storefront must keep using the saved focal. Pinned in Task 3 (`odaklar()` returns an intent that sits on an **archived** asset of the same `File`).
3. **Seller previews a file they don't own** (picked from the shared library) → the endpoint must not leak another tenant's asset or focal, and the window must disable Save with "Görsel hazırlanıyor; odak noktası birkaç dakika sonra kaydedilebilir." Pinned in Task 3 (other seller gets `asset == ""`, `focal is None`) and Task 8 (Save disabled when `asset` is empty).
4. **Float formatting of the CSS value.** `0.78 * 100` is `78.00000000000001` in JS; the preview and the storefront must both emit exactly `78% 45%` so the e2e equality holds. Pinned in Task 5 (`objectPosition`) and Task 9 (`storeImgPosition`).
5. **Arabic (RTL) panel.** The focal marker and frame are image-space coordinates; in `dir="rtl"` they must not mirror. Pinned in Task 8 (`FocalEditor` image box carries `dir="ltr"`, marker uses `translate(x%, y%)` not `inset-inline-start`).

---

## File Structure

| Repo | Path | Responsibility | Task |
|---|---|---|---|
| tradehub_core | `tradehub_core/media/pipeline/simulator/placements.json` | + `preview_places` block (single source of the places) | 1 |
| tradehub_core | `tradehub_core/media/pipeline/delivery/sizes.py` | + `preview_places()`, `emit_placements_admin()`, `emit_placements_storefront()`, `--emit-placements admin\|storefront` | 1 |
| tradehub_core | `tradehub_core/tests/test_preview_places.py` (new) | pure-Python tests of the registry + emitters | 1 |
| admin-panel | `frontend/src/lib/media/vendor/placements.js` (generated) | admin copy of the registry | 1 |
| admin-panel | `frontend/src/lib/media/simulator/vendor/*` (regenerated by `npm run sync:simulator`) | keeps the simulator sha chain green | 1 |
| admin-panel | `frontend/.prettierignore` | + `src/lib/media/vendor` | 1 |
| tradehubfront | `src/lib/media/placements.gen.ts` (generated) | `STORE_PLACE_SIZES` | 1 |
| tradehubfront | `.prettierignore` | + `src/lib/media/placements.gen.ts` | 1 |
| tradehub_core | `tradehub_core/media/pipeline/api/crop.py` | fix `if_match` (ETag of the same body shape as `get_intent`) | 2 |
| tradehub_core | `tradehub_core/tests/test_api_contracts.py`, `tests/test_media_crop_intent.py` | ETag round-trip + focal-only save keeps other fields | 2 |
| tradehub_core | `tradehub_core/media/odak.py` (new) | `odaklar()` — latest focal per (file URL, seller) | 3 |
| tradehub_core | `tradehub_core/api/media_preview.py` (new) | `get_preview_target`, `get_preview_prefs`, `set_preview_prefs` | 3 |
| tradehub_core | `tradehub_core/tests/test_media_preview.py` (new) | Frappe DB tests | 3 |
| tradehub_core | `tradehub_core/api/media_manifest.py` | `magaza_gorsel_medyasi` adds `focal` (flag-independent) | 4 |
| tradehub_core | `tradehub_core/tests/test_magaza_odak.py` (new) | mock-based tests | 4 |
| admin-panel | `frontend/src/lib/media/crop/geometry.js` | + `clampFocal`, `visibleFraction`, `frameRect`, `objectPosition` | 5 |
| admin-panel | `frontend/src/lib/media/crop/cropIntentApi.js` | + `saveFocalOnly` (does NOT send `safe_area`) | 5 |
| admin-panel | `frontend/src/lib/media/preview/previewApi.js` (new) | endpoint wrappers | 5 |
| admin-panel | `frontend/src/composables/useFocalPoint.js` (new) | focal state, load/suggest/save, announcements | 5 |
| admin-panel | `frontend/src/lib/media/crop/__tests__/focalGeometry.test.js`, `src/composables/__tests__/focalPoint.test.js` (new) | tests | 5 |
| admin-panel | `frontend/src/lib/media/preview/places.js` (new) | place queries, visibility, badge count, box style | 6 |
| admin-panel | `frontend/src/lib/media/preview/messages.js` (new) | all window/button strings in tr/en/ru/ar (local i18n scope) | 6 |
| admin-panel | `frontend/src/lib/media/preview/__tests__/places.test.js`, `messages.test.js` (new) | tests | 6 |
| tradehubfront | `src/lib/media/storeImage.ts`, `storeImage.test.ts` | `focal`, `storeImageFocal`, `storeImgPosition`, style in `storeImgAttrs`; `STORE_IMAGE_SIZES` reads generated sizes | 9 |
| tradehubfront | `src/alpine/index.ts` | `$focalPos` magic | 9 |
| tradehubfront | `src/utils/seller/section-registry.ts`, `src/components/seller/StoreHeader.ts`, `src/pages/seller-shop.ts`, `src/components/manufacturers/ManufacturerList.ts` | apply `object-position` | 9 |
| tradehubfront | `src/utils/seller/section-registry.test.ts` (new) | hero focal test | 9 |
| admin-panel | `frontend/src/components/media/preview/contexts/*` (new: `contextProps.js`, `contexts.css`, `ContextImage.vue`, 9 contexts, `index.js`) | static page skeletons | 7 |
| admin-panel | `frontend/src/components/media/preview/__tests__/contexts.test.js` (new) | SSR + axe | 7 |
| admin-panel | `frontend/src/components/media/preview/{ImagePlacementModal,PlaceList,FocalEditor}.vue` (new) | the window | 8 |
| admin-panel | `frontend/src/components/media/preview/__tests__/{mountSfc.js,focalEditor.test.js,placeList.test.js,imagePlacementModal.test.js,previewAxe.test.js}` (new) | jsdom + SSR + axe tests | 8 |
| admin-panel | `frontend/src/components/media/preview/ImagePlacementButton.vue`, `src/composables/usePlacementLauncher.js` (new) | entry button + badge, open/auto-open logic | 10 |
| admin-panel | `frontend/src/components/media/preview/__tests__/placementButton.test.js`, `src/composables/__tests__/placementLauncher.test.js` (new) | tests | 10 |
| admin-panel | `frontend/src/views/seller/ListingFormView.vue` + `src/views/seller/__tests__/listingPlacementWiring.test.js` (new) | product entry points | 11 |
| admin-panel | `frontend/src/components/upload/ProfileImageDropzone.vue`, `src/views/doctype/DocTypeFormView.vue`, `src/views/seller/StorefrontLayoutEditor.vue`, `src/components/seller/LayoutSectionCard.vue` + `src/components/media/preview/__tests__/storePlacementWiring.test.js` (new) | store entry points | 12 |
| admin-panel | `frontend/tests/e2e/image-placement.spec.ts` (new) | Özgen e2e + axe | 13 |
| tradehub_core | `tradehub_core/media/odak_olcum.py` (new) | `suggest_focal` vs saved focal measurement | 13 |

## Waves (parallel execution)

Tasks in the same wave touch **disjoint files** and may run in parallel subagents. A task starts only after all its dependencies finished and were reviewed.

| Wave | Tasks (parallel) | Depends on |
|---|---|---|
| 1 | **T1** registry + emitters · **T2** ETag fix · **T3** `odak.py` + `media_preview.py` · **T5** geometry + `useFocalPoint` | — |
| 2 | **T4** manifest `focal` · **T6** `places.js` + `messages.js` · **T9** storefront `object-position` | T4←T3 · T6←T1,T5 · T9←T1 (payload shape from T4's interface; runs in parallel with T4) |
| 3 | **T7** contexts · **T8** modal · **T10** button + launcher | T7←T6 · T8←T5,T6 (imports T7's `contexts/index.js` by interface; tests stub it) · T10←T5,T6 |
| 4 | **T11** ListingFormView · **T12** store settings views | T11←T8,T10 · T12←T8,T10 |
| 5 | **T13** local deploy + e2e + axe + measurement | all |

Baseline already red before this work (do not "fix" inside this plan, but do not make it worse): `python3 -m unittest tradehub_core.tests.test_delivery_sizes` → 2 failures (`test_kart_izgarasi_ayni_telefonda_346px_ister`, `test_aciklanmamis_sapma_yok`); admin crop tests → 3 failures about `alphaToJpeg` (`cropWarnings`). Record the baseline in each task report when you touch those suites.

---

### Task 1: Placement registry, emitters and generated copies (Wave 1)

**Files:**
- Modify: `tradehub_core/tradehub_core/media/pipeline/simulator/placements.json` (add top-level key `preview_places` after `excluded_regions`)
- Modify: `tradehub_core/tradehub_core/media/pipeline/delivery/sizes.py` (new section before `def main`, extend `main`, extend `__all__`)
- Create: `tradehub_core/tradehub_core/tests/test_preview_places.py`
- Create (generated): `admin-panel/frontend/src/lib/media/vendor/placements.js`
- Regenerate: `admin-panel/frontend/src/lib/media/simulator/vendor/{placements.json,simulator_data.js,vendor.manifest.json}` via `npm run sync:simulator`
- Modify: `admin-panel/frontend/.prettierignore`
- Create (generated): `tradehubfront/src/lib/media/placements.gen.ts`
- Modify: `tradehubfront/.prettierignore`

**Interfaces:**
- Consumes: `sim.load_layout()`, `sim.load_devices()`, `sim.box_width(region, device, layout)`, `Layout.raw`, `Layout.region_of(page, region)`, `Region.render_point` (all existing in `media/pipeline/simulator/srcset.py`).
- Produces:
  - Python: `sizes.preview_places(layout=None) -> dict[str, list[dict]]`, `sizes.emit_placements_admin(layout=None) -> str`, `sizes.emit_placements_storefront(layout=None) -> str`, CLI `--emit-placements admin|storefront`.
  - Each resolved place (same field names in the admin JS): `{key: str, device: "desktop"|"mobile", label: str, labelKey: str, ratio: float, ratioLabel: str, cssW: int|null, cssH: int|null, fit: "cover"|"contain", context: str, sizesKey: str|null, sizes: str|null, derivedFrom: str}`.
  - Admin `src/lib/media/vendor/placements.js` exports `SOURCE_SHA256: string`, `STAGE: {desktopPagePx: 1200, desktopStagePx: 780, mobilePagePx: 390}`, `FULLY_VISIBLE_MIN: 0.98`, `PLACES: Record<slotKey, Place[]>`.
  - Storefront `src/lib/media/placements.gen.ts` exports `STORE_PLACE_SIZES` with keys `galleryMain`, `galleryThumb`, `manufacturerGallery`, `shopHeaderLogoDesktop`, `shopHeaderLogoMobile` (`as const`).
  - Context names used by Task 7: `StoreHeaderContext`, `StoreCardContext`, `StoreVitrinContext`, `GalleryContext`, `ProductCardContext`, `ProductPageContext`, `CartContext`, `RelatedContext`, `FavoritesContext`.

- [ ] **Step 1: Write the failing test**

Create `tradehub_core/tradehub_core/tests/test_preview_places.py`:

```python
"""Önizleme yer kaydı (`placements.json → preview_places`) ve üreteçleri — 2026-10-01.

Çalıştırma (bench/site/DB GEREKMEZ):

    cd /Users/ahmet/Desktop/istoc/tradehub_core
    python3 -m unittest tradehub_core.tests.test_preview_places -v
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.delivery import sizes as SZ  # noqa: E402
from tradehub_core.media.pipeline.simulator import PLACEMENTS_PATH  # noqa: E402
from tradehub_core.media.pipeline.simulator import srcset as sim  # noqa: E402

SLOTS = ("company.cover_image", "seller.logo", "product.image")


class YerKaydi(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.yerler = SZ.preview_places()

	def test_her_slot_her_cihazda_en_az_bir_yer(self):
		for slot in SLOTS:
			for cihaz in ("desktop", "mobile"):
				with self.subTest(slot=slot, cihaz=cihaz):
					self.assertTrue([y for y in self.yerler[slot] if y["device"] == cihaz])

	def test_alanlar_ve_sozluk(self):
		for slot, yerler in self.yerler.items():
			for y in yerler:
				with self.subTest(slot=slot, key=y["key"], device=y["device"]):
					self.assertIn(y["fit"], SZ.PREVIEW_FITS)
					self.assertIn(y["context"], SZ.PREVIEW_CONTEXTS)
					self.assertGreater(y["ratio"], 0)
					self.assertTrue(y["labelKey"].startswith("imagePlacement.place."))
					self.assertTrue(y["derivedFrom"])

	def test_bolge_turetilen_olcu_box_width_ile_ayni(self):
		yerlesim = sim.load_layout()
		cihaz = {d.id: d for d in sim.load_devices()}["macbook-air-13"]
		kart = next(
			y for y in self.yerler["product.image"] if y["key"] == "product_card" and y["device"] == "desktop"
		)
		bolge = yerlesim.region_of("listing", "card_grid")
		self.assertEqual(kart["cssW"], round(sim.box_width(bolge, cihaz, yerlesim)))
		self.assertEqual(kart["cssW"], 213)

	def test_magaza_basligi_telefonda_390x180(self):
		yer = next(
			y for y in self.yerler["company.cover_image"] if y["key"] == "store_hero" and y["device"] == "mobile"
		)
		self.assertEqual((yer["cssW"], yer["cssH"]), (390, 180))
		self.assertAlmostEqual(yer["ratio"], 390 / 180, places=4)

	def test_bolgeler_degismedi(self):
		# preview_places sayfa/bölge listesine KARIŞMAZ — sizes/srcset paritesi aynı kalır.
		self.assertEqual(len(SZ.region_keys()), 15)


class Ureticiler(unittest.TestCase):
	def test_admin_ciktisi_sha_ve_json_tasir(self):
		cikti = SZ.emit_placements_admin()
		sha = hashlib.sha256(Path(PLACEMENTS_PATH).read_bytes()).hexdigest()
		self.assertIn(f'export const SOURCE_SHA256 = "{sha}";', cikti)
		eslesme = re.search(r"export const PLACES = Object\.freeze\((\{.*\})\);\n", cikti, re.S)
		self.assertIsNotNone(eslesme)
		veri = json.loads(eslesme.group(1))
		self.assertEqual(set(veri), set(SLOTS))
		self.assertIn("export const FULLY_VISIBLE_MIN = 0.98;", cikti)

	def test_storefront_ciktisi_bes_anahtar(self):
		cikti = SZ.emit_placements_storefront()
		for anahtar, deger in {
			"galleryMain": "(min-width: 768px) 500px, 100vw",
			"galleryThumb": "120px",
			"manufacturerGallery": "(min-width: 1024px) 220px, 165px",
			"shopHeaderLogoDesktop": "140px",
			"shopHeaderLogoMobile": "48px",
		}.items():
			self.assertIn(f'  {anahtar}: "{deger}",', cikti)
		self.assertIn("} as const;", cikti)

	def test_cli_bilinmeyen_hedef_2_doner(self):
		self.assertEqual(SZ.main(["--emit-placements", "nope"]), 2)


if __name__ == "__main__":
	unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/ahmet/Desktop/istoc/tradehub_core && python3 -m unittest tradehub_core.tests.test_preview_places -v`
Expected: ERROR — `AttributeError: module 'tradehub_core.media.pipeline.delivery.sizes' has no attribute 'preview_places'`.

- [ ] **Step 3: Add `preview_places` to `placements.json`**

Insert this key as the last top-level key (after the `excluded_regions` array; add the comma after `]`). Values for store places come from the storefront CSS lines named in `derived_from`; product places are computed from the existing `pages[].regions[]` rules by the emitter:

```json
  "preview_places": {
    "$comment": "Görsel önizleme penceresinin (admin ImagePlacementModal) yer kaydı — 2026-10-01. TEK KAYNAK: admin src/lib/media/vendor/placements.js ve storefront src/lib/media/placements.gen.ts buradan `python3 -m tradehub_core.media.pipeline.delivery.sizes --emit-placements admin|storefront` ile üretilir; elle düzenlenmez. `region` taşıyan yerin ölçüsü pages[].regions[].box kuralından reference_devices cihazında HESAPLANIR. `css_size` taşıyanlar storefront CSS'inden elle türetildi (derived_from dosya:satır). `css_size: null` = ölçülmedi; pencere yalnız oranı yazar. Admin Seller Profile.banner_image'ın vitrinde canlı bir basım noktası YOK (2026-10-01 incelemesi); banner görseli fiilen vitrin slaytı olarak basılıyor, bu yüzden company.cover_image yerleri slayt/galeri basım noktalarıdır.",
    "reference_devices": { "desktop": "macbook-air-13", "mobile": "iphone-14" },
    "stage": { "desktop_page_px": 1200, "desktop_stage_px": 780, "mobile_page_px": 390 },
    "fully_visible_min": 0.98,
    "slots": {
      "company.cover_image": [
        { "key": "store_hero", "device": "desktop", "label": "Mağaza sayfası başlığı", "label_i18n": "imagePlacement.place.storeHero", "ratio": [3, 1], "ratio_label": "3:1", "css_size": [1200, 400], "fit": "cover", "context": "StoreHeaderContext", "derived_from": "tradehubfront/src/utils/seller/section-registry.ts:108 static hero `w-full ... lg:h-[400px] object-cover`; slider kabı :216 aynı yükseklik. Referans sayfa 1200 px." },
        { "key": "store_vitrin", "device": "desktop", "label": "Mağaza vitrini", "label_i18n": "imagePlacement.place.storeVitrin", "ratio": [16, 9], "ratio_label": "16:9", "css_size": [500, 281], "fit": "cover", "context": "StoreVitrinContext", "storefront_sizes_key": "galleryMain", "sizes": "(min-width: 768px) 500px, 100vw", "derived_from": "tradehubfront/src/components/seller/StoreHeader.ts:203 `lg:w-[500px]` + :299 `aspect-video` + :316 `object-cover`" },
        { "key": "store_gallery", "device": "desktop", "label": "Galeri kutusu", "label_i18n": "imagePlacement.place.storeGallery", "ratio": [4, 3], "ratio_label": "4:3", "css_size": [119, 89], "fit": "cover", "context": "GalleryContext", "storefront_sizes_key": "galleryThumb", "sizes": "120px", "derived_from": "StoreHeader.ts:381 `minmax(96px,1fr)` gap-2 (8 px) 500 px içinde 4 sütun → (500−3×8)/4 = 119; :385 `aspect-[4/3]`; :394 `object-cover`" },
        { "key": "store_card", "device": "desktop", "label": "Mağaza tanıtım kartı", "label_i18n": "imagePlacement.place.storeCard", "ratio": [1, 1], "ratio_label": "1:1", "css_size": [220, 220], "fit": "cover", "context": "StoreCardContext", "storefront_sizes_key": "manufacturerGallery", "sizes": "(min-width: 1024px) 220px, 165px", "derived_from": "tradehubfront/src/components/manufacturers/ManufacturerList.ts:354 `xl:w-[220px] xl:h-[220px]` + :364 `object-cover`; yalnız masaüstü (`isLargeLayout`)" },
        { "key": "store_hero", "device": "mobile", "label": "Mağaza sayfası başlığı", "label_i18n": "imagePlacement.place.storeHero", "ratio": [390, 180], "ratio_label": "≈2,2:1", "css_size": [390, 180], "fit": "cover", "context": "StoreHeaderContext", "derived_from": "section-registry.ts:108 `h-[180px]` (<480 px), tam genişlik; telefon 390 px" },
        { "key": "store_vitrin", "device": "mobile", "label": "Mağaza vitrini", "label_i18n": "imagePlacement.place.storeVitrin", "ratio": [16, 9], "ratio_label": "16:9", "css_size": [326, 183], "fit": "cover", "context": "StoreVitrinContext", "derived_from": "StoreHeader.ts:46 `px-4` + :128 `px-4` → 390 − 4×16 = 326; :299 `aspect-video`" },
        { "key": "store_gallery", "device": "mobile", "label": "Galeri kutusu", "label_i18n": "imagePlacement.place.storeGallery", "ratio": [4, 3], "ratio_label": "4:3", "css_size": [103, 77], "fit": "cover", "context": "GalleryContext", "derived_from": "326 px içinde `minmax(96px,1fr)` gap-2 → 3 sütun, (326−2×8)/3 = 103; :385 `aspect-[4/3]`" }
      ],
      "seller.logo": [
        { "key": "shop_logo", "device": "desktop", "label": "Mağaza başlığı logosu", "label_i18n": "imagePlacement.place.shopLogo", "ratio": [1, 1], "ratio_label": "1:1", "css_size": [140, 140], "fit": "cover", "context": "StoreHeaderContext", "storefront_sizes_key": "shopHeaderLogoDesktop", "sizes": "140px", "derived_from": "tradehubfront/src/pages/seller-shop.ts:130-135 `w-[140px] h-[140px]` + `object-cover`" },
        { "key": "shop_logo", "device": "mobile", "label": "Mağaza başlığı logosu", "label_i18n": "imagePlacement.place.shopLogo", "ratio": [1, 1], "ratio_label": "1:1", "css_size": [48, 48], "fit": "contain", "context": "StoreHeaderContext", "storefront_sizes_key": "shopHeaderLogoMobile", "sizes": "48px", "derived_from": "tradehubfront/src/pages/seller-shop.ts:210-213 `w-[50px] h-[50px]` + 1 px kenarlık → 48 px iç; `object-contain` (telefonda logo kesilmez)" }
      ],
      "product.image": [
        { "key": "product_card", "device": "desktop", "label": "Ürün kartı", "label_i18n": "imagePlacement.place.productCard", "region": "listing/card_grid", "ratio": [1, 1], "ratio_label": "1:1", "fit": "contain", "context": "ProductCardContext", "derived_from": "tradehubfront/src/components/shared/ListingCard.ts:88 varsayılan object-contain, kare kutu" },
        { "key": "product_main", "device": "desktop", "label": "Ürün sayfası · ana görsel", "label_i18n": "imagePlacement.place.productMain", "region": "product_detail/main_image", "ratio": [1, 1], "ratio_label": "1:1", "fit": "contain", "context": "ProductPageContext", "derived_from": "" },
        { "key": "product_thumb", "device": "desktop", "label": "Ürün sayfası · küçük resim", "label_i18n": "imagePlacement.place.productThumb", "region": "product_detail/thumb_rail", "ratio": [1, 1], "ratio_label": "1:1", "fit": "contain", "context": "ProductPageContext", "derived_from": "" },
        { "key": "cart", "device": "desktop", "label": "Sepet ve sipariş", "label_i18n": "imagePlacement.place.cart", "region": "cart_checkout/drawer_thumb", "ratio": [1, 1], "ratio_label": "1:1", "fit": "contain", "context": "CartContext", "derived_from": "" },
        { "key": "related", "device": "desktop", "label": "Benzer ürünler", "label_i18n": "imagePlacement.place.related", "region": "product_detail/related_slider", "ratio": [1, 1], "ratio_label": "1:1", "fit": "contain", "context": "RelatedContext", "derived_from": "" },
        { "key": "favorites", "device": "desktop", "label": "Favoriler", "label_i18n": "imagePlacement.place.favorites", "ratio": [1, 1], "ratio_label": "1:1", "css_size": null, "fit": "cover", "context": "FavoritesContext", "derived_from": "tradehubfront/src/components/favorites/FavoritesLayout.ts:624-627 `aspect-square` + `object-cover`; kutu genişliği ölçülmedi (Task 13 ölçer)" },
        { "key": "product_card", "device": "mobile", "label": "Ürün kartı", "label_i18n": "imagePlacement.place.productCard", "region": "listing/card_grid", "ratio": [1, 1], "ratio_label": "1:1", "fit": "contain", "context": "ProductCardContext", "derived_from": "tradehubfront/src/components/shared/ListingCard.ts:88 varsayılan object-contain, kare kutu" },
        { "key": "product_main", "device": "mobile", "label": "Ürün sayfası · ana görsel", "label_i18n": "imagePlacement.place.productMain", "region": "product_detail/main_image", "ratio": [1, 1], "ratio_label": "1:1", "fit": "contain", "context": "ProductPageContext", "derived_from": "" },
        { "key": "product_thumb", "device": "mobile", "label": "Ürün sayfası · küçük resim", "label_i18n": "imagePlacement.place.productThumb", "region": "product_detail/thumb_rail", "ratio": [1, 1], "ratio_label": "1:1", "fit": "contain", "context": "ProductPageContext", "derived_from": "" },
        { "key": "cart", "device": "mobile", "label": "Sepet ve sipariş", "label_i18n": "imagePlacement.place.cart", "region": "cart_checkout/drawer_thumb", "ratio": [1, 1], "ratio_label": "1:1", "fit": "contain", "context": "CartContext", "derived_from": "" },
        { "key": "related", "device": "mobile", "label": "Benzer ürünler", "label_i18n": "imagePlacement.place.related", "region": "product_detail/related_slider", "ratio": [1, 1], "ratio_label": "1:1", "fit": "contain", "context": "RelatedContext", "derived_from": "" },
        { "key": "favorites", "device": "mobile", "label": "Favoriler", "label_i18n": "imagePlacement.place.favorites", "ratio": [1, 1], "ratio_label": "1:1", "css_size": null, "fit": "cover", "context": "FavoritesContext", "derived_from": "FavoritesLayout.ts:871 `grid-cols-2` + :624 `aspect-square`; kutu genişliği ölçülmedi (Task 13 ölçer)" }
      ]
    }
  }
```

(Empty `derived_from` on region places is intentional: the emitter fills it from the region's own `render_point`, which already carries file:line.)

- [ ] **Step 4: Implement the emitters in `sizes.py`**

Add `import hashlib` and `from pathlib import Path` to the imports. Insert before `def main(`:

```python
# ── Önizleme yerleri (2026-10-01) ───────────────────────────────────────

PREVIEW_SLOTS: Tuple[str, ...] = ("company.cover_image", "seller.logo", "product.image")
PREVIEW_DEVICES: Tuple[str, ...] = ("desktop", "mobile")
PREVIEW_FITS: Tuple[str, ...] = ("cover", "contain")
PREVIEW_CONTEXTS: Tuple[str, ...] = (
	"StoreHeaderContext",
	"StoreCardContext",
	"StoreVitrinContext",
	"GalleryContext",
	"ProductCardContext",
	"ProductPageContext",
	"CartContext",
	"RelatedContext",
	"FavoritesContext",
)


def _placements_sha256() -> str:
	from tradehub_core.media.pipeline.simulator import PLACEMENTS_PATH

	return hashlib.sha256(Path(PLACEMENTS_PATH).read_bytes()).hexdigest()


def _onizleme_yeri(
	yer: Dict[str, Any], yerlesim: sim.Layout, cihazlar: Dict[str, Any], referans: Dict[str, str]
) -> Dict[str, Any]:
	cihaz_turu = yer.get("device")
	if cihaz_turu not in PREVIEW_DEVICES:
		raise SizesError(f"Önizleme yeri cihazı geçersiz: {yer.get('key')!r} → {cihaz_turu!r}")
	if yer.get("fit") not in PREVIEW_FITS:
		raise SizesError(f"Önizleme yeri `fit` geçersiz: {yer.get('key')!r}")
	if yer.get("context") not in PREVIEW_CONTEXTS:
		raise SizesError(f"Önizleme yeri bağlamı bilinmiyor: {yer.get('context')!r}")
	en, boy = (float(v) for v in yer["ratio"])
	if en <= 0 or boy <= 0:
		raise SizesError(f"Önizleme yeri oranı pozitif olmalı: {yer.get('key')!r}")
	oran = en / boy
	boyut = yer.get("css_size")
	kaynak = str(yer.get("derived_from") or "")
	if yer.get("region"):
		sayfa, _, bolge = str(yer["region"]).partition("/")
		bolge_kaydi = yerlesim.region_of(sayfa, bolge)
		cihaz = cihazlar[referans[cihaz_turu]]
		genislik = round(sim.box_width(bolge_kaydi, cihaz, yerlesim))
		boyut = [genislik, round(genislik / oran)]
		kaynak = kaynak or f"{bolge_kaydi.key} — {bolge_kaydi.render_point}"
	return {
		"key": str(yer["key"]),
		"device": cihaz_turu,
		"label": str(yer["label"]),
		"labelKey": str(yer["label_i18n"]),
		"ratio": round(oran, 6),
		"ratioLabel": str(yer["ratio_label"]),
		"cssW": int(boyut[0]) if boyut else None,
		"cssH": int(boyut[1]) if boyut else None,
		"fit": yer["fit"],
		"context": yer["context"],
		"sizesKey": yer.get("storefront_sizes_key") or None,
		"sizes": yer.get("sizes") or None,
		"derivedFrom": kaynak,
	}


def preview_places(layout: Optional[sim.Layout] = None) -> Dict[str, List[Dict[str, Any]]]:
	"""`placements.json → preview_places` çözülmüş hâli: slot → yer listesi.

	`region` taşıyan yerin ölçüsü `box_width` ile referans cihazda HESAPLANIR —
	elle yazılmış ikinci bir sayı doğmasın. `css_size: null` ölçülmedi demektir.
	"""
	yerlesim = layout or _layout()
	blok = yerlesim.raw.get("preview_places") or {}
	cihazlar = {d.id: d for d in sim.load_devices()}
	referans = dict(blok.get("reference_devices") or {})
	cikti: Dict[str, List[Dict[str, Any]]] = {}
	for slot, yerler in (blok.get("slots") or {}).items():
		if slot not in PREVIEW_SLOTS:
			raise SizesError(f"Bilinmeyen önizleme slotu: {slot!r}")
		gorulen: set = set()
		satirlar: List[Dict[str, Any]] = []
		for yer in yerler:
			satir = _onizleme_yeri(yer, yerlesim, cihazlar, referans)
			kimlik = (satir["key"], satir["device"])
			if kimlik in gorulen:
				raise SizesError(f"{slot}: yinelenen önizleme yeri {kimlik!r}")
			gorulen.add(kimlik)
			satirlar.append(satir)
		cikti[slot] = satirlar
	return cikti


def emit_placements_admin(layout: Optional[sim.Layout] = None) -> str:
	"""Admin `src/lib/media/vendor/placements.js` — dosyanın TAMAMI."""
	import json

	yerlesim = layout or _layout()
	blok = yerlesim.raw.get("preview_places") or {}
	sahne = blok.get("stage") or {}
	stage = {
		"desktopPagePx": int(sahne.get("desktop_page_px") or 1200),
		"desktopStagePx": int(sahne.get("desktop_stage_px") or 780),
		"mobilePagePx": int(sahne.get("mobile_page_px") or 390),
	}
	esik = float(blok.get("fully_visible_min") or 0.98)
	satirlar = [
		"// ÜRETİLMİŞ DOSYA — ELLE DÜZENLEME.",
		"// Kaynak: tradehub_core/tradehub_core/media/pipeline/simulator/placements.json (preview_places)",
		"// Üretici (tradehub_core kökünde): python3 -m tradehub_core.media.pipeline.delivery.sizes"
		" --emit-placements admin > ../admin-panel/frontend/src/lib/media/vendor/placements.js",
		f'export const SOURCE_SHA256 = "{_placements_sha256()}";',
		f"export const STAGE = Object.freeze({json.dumps(stage, ensure_ascii=False)});",
		f"export const FULLY_VISIBLE_MIN = {esik};",
		"export const PLACES = Object.freeze("
		+ json.dumps(preview_places(yerlesim), ensure_ascii=False, indent=2)
		+ ");",
	]
	return "\n".join(satirlar) + "\n"


def emit_placements_storefront(layout: Optional[sim.Layout] = None) -> str:
	"""Storefront `src/lib/media/placements.gen.ts` — dosyanın TAMAMI."""
	boyutlar: Dict[str, str] = {}
	for yerler in preview_places(layout).values():
		for y in yerler:
			if not y["sizesKey"]:
				continue
			onceki = boyutlar.get(y["sizesKey"])
			if onceki is not None and onceki != y["sizes"]:
				raise SizesError(f"`{y['sizesKey']}` iki farklı `sizes` taşıyor: {onceki!r} / {y['sizes']!r}")
			boyutlar[y["sizesKey"]] = y["sizes"]
	satirlar = [
		"// ÜRETİLMİŞ DOSYA — ELLE DÜZENLEME.",
		"// Kaynak: tradehub_core/tradehub_core/media/pipeline/simulator/placements.json (preview_places)",
		"// Üretici (tradehub_core kökünde): python3 -m tradehub_core.media.pipeline.delivery.sizes"
		" --emit-placements storefront > ../tradehubfront/src/lib/media/placements.gen.ts",
		"",
		"/** Önizleme penceresiyle ORTAK yerlerin `sizes` dizgeleri. */",
		"export const STORE_PLACE_SIZES = {",
	]
	satirlar += [f'  {k}: "{v}",' for k, v in sorted(boyutlar.items())]
	satirlar += ["} as const;"]
	return "\n".join(satirlar) + "\n"
```

In `main`, before the existing `if "--emit-ts" in argumanlar:` block, add:

```python
	if "--emit-placements" in argumanlar:
		i = argumanlar.index("--emit-placements")
		hedef = argumanlar[i + 1] if i + 1 < len(argumanlar) else ""
		if hedef == "admin":
			sys.stdout.write(emit_placements_admin())
			return 0
		if hedef == "storefront":
			sys.stdout.write(emit_placements_storefront())
			return 0
		sys.stderr.write("Kullanım: --emit-placements admin|storefront\n")
		return 2
```

Extend `__all__` with `"PREVIEW_SLOTS", "PREVIEW_DEVICES", "PREVIEW_FITS", "PREVIEW_CONTEXTS", "preview_places", "emit_placements_admin", "emit_placements_storefront",`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/ahmet/Desktop/istoc/tradehub_core && python3 -m unittest tradehub_core.tests.test_preview_places -v && python3 -m unittest tradehub_core.tests.test_simulator_srcset 2>&1 | tail -3 && python3 -m unittest tradehub_core.tests.test_delivery_sizes 2>&1 | tail -2 && ruff check tradehub_core/media/pipeline/delivery/sizes.py tradehub_core/tests/test_preview_places.py`
Expected: `test_preview_places` → `OK` (8 tests). `test_simulator_srcset` unchanged from before. `test_delivery_sizes` still exactly the 2 baseline failures (`FAILED (failures=2)`), not more. Ruff: `All checks passed!`.

- [ ] **Step 6: Generate the two copies and re-sync the simulator vendor**

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core
mkdir -p ../admin-panel/frontend/src/lib/media/vendor
python3 -m tradehub_core.media.pipeline.delivery.sizes --emit-placements admin > ../admin-panel/frontend/src/lib/media/vendor/placements.js
python3 -m tradehub_core.media.pipeline.delivery.sizes --emit-placements storefront > ../tradehubfront/src/lib/media/placements.gen.ts
cd ../admin-panel/frontend && npm run sync:simulator && npm run sync:simulator:check
node --test "src/lib/media/simulator/__tests__/*.test.js" "src/views/system/__tests__/mediaSimulator.test.js" 2>&1 | tail -6
```

Append to `admin-panel/frontend/.prettierignore` (below `src/lib/media/policy/vendor`):

```
src/lib/media/vendor
```

Append to `tradehubfront/.prettierignore`:

```
# ÜRETİLMİŞ — tradehub_core sizes.py --emit-placements storefront
src/lib/media/placements.gen.ts
```

Expected: `sync:simulator:check` exits 0; simulator tests report `# fail 0`. `head -5 src/lib/media/vendor/placements.js` shows the `SOURCE_SHA256` line.

- [ ] **Step 7: Stage (no commit — user approves commits)**

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core && git add tradehub_core/media/pipeline/simulator/placements.json tradehub_core/media/pipeline/delivery/sizes.py tradehub_core/tests/test_preview_places.py
cd /Users/ahmet/Desktop/istoc/admin-panel && git add frontend/src/lib/media/vendor/placements.js frontend/src/lib/media/simulator/vendor frontend/.prettierignore
cd /Users/ahmet/Desktop/istoc/tradehubfront && git add src/lib/media/placements.gen.ts .prettierignore
```

---

### Task 2: Make `if_match` work — ETag of the same body as `get_intent` (Wave 1)

**Why:** `CropApi.save_intent` compares `If-Match` against `etag_for({"asset", "intent"})`, but `get_intent` and `save_intent` hand out `etag_for(<full body>)`. Measured 2026-10-01 with the in-memory API: a fresh ETag from `get_intent` → **412**, and the ETag returned by `save_intent` → **412**. The spec's "ETag / `if_none_match` mevcut desenle" therefore cannot work without this fix.

**Files:**
- Modify: `tradehub_core/tradehub_core/media/pipeline/api/crop.py` (`get_intent` ≈ line 322, `save_intent` ≈ line 351)
- Modify: `tradehub_core/tradehub_core/tests/test_api_contracts.py` (class `KirpmaTesti`, after `test_if_match_iyimser_kilit` ≈ line 616)
- Modify: `tradehub_core/tradehub_core/tests/test_media_crop_intent.py` (class `MediaCropIntentTests`, append two tests)

**Interfaces:**
- Consumes: existing `CropApi._normalize_intent`, `_slot_of`, `_windows`, `env.etag_for`, `env.etag_matches`.
- Produces: `CropApi._govde(asset, kayit, ham) -> dict` (private). Contract for later tasks: **the `etag` returned by `tradehub_core.api.media_crop.get_intent` or `save_intent` is accepted as `if_match` by the next `save_intent`**; a stale one returns HTTP 412 (`err.status === 412` in the admin `api.js` error).

- [ ] **Step 1: Write the failing tests**

In `test_api_contracts.py`, class `KirpmaTesti`, after `test_if_match_iyimser_kilit`:

```python
	def test_taze_etag_ile_kayit_kabul_edilir(self):
		api = self.kur()
		etag = api.get_intent(SATICI, "MA-1").headers["ETag"]
		yanit = env.call(api.save_intent, SATICI, "MA-1", focal_x=0.7, focal_y=0.4, if_match=etag)
		self.assertEqual(yanit.status, 200)

	def test_kayit_yanitinin_etagi_sonraki_kayitta_gecer(self):
		api = self.kur()
		ilk = api.save_intent(SATICI, "MA-1", focal_x=0.2, focal_y=0.2)
		yanit = env.call(
			api.save_intent, SATICI, "MA-1", focal_x=0.3, focal_y=0.3, if_match=ilk.headers["ETag"]
		)
		self.assertEqual(yanit.status, 200)
```

In `test_media_crop_intent.py`, append to `MediaCropIntentTests`:

```python
	def test_fresh_etag_round_trip_through_frappe_endpoint(self):
		"""Panelin ETag deseni: get_intent.etag → save_intent(if_match) → 200."""
		frappe.set_user(self.owner)
		etag = media_crop.get_intent(asset=self.asset)["etag"]
		yazma = media_crop.save_intent(asset=self.asset, focal_x=0.78, focal_y=0.45, if_match=etag)
		self.assertEqual(yazma["status"], 200)
		ikinci = media_crop.save_intent(
			asset=self.asset, focal_x=0.5, focal_y=0.5, if_match=yazma["etag"]
		)
		self.assertEqual(ikinci["status"], 200)

	def test_focal_only_save_keeps_safe_area_and_confidence(self):
		"""Önizleme penceresi YALNIZ odak gönderir; güvenli alan ve güven korunur."""
		frappe.set_user(self.owner)
		media_crop.save_intent(
			asset=self.asset,
			focal_x=0.2,
			focal_y=0.2,
			safe_area={"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5},
			confidence=0.6,
		)
		media_crop.save_intent(asset=self.asset, focal_x=0.78, focal_y=0.45)
		frappe.set_user("Administrator")
		kayit = frappe.db.get_value(
			INTENT, self.asset, ["focal_x", "focal_y", "safe_x", "safe_w", "confidence"], as_dict=True
		)
		self.assertAlmostEqual(kayit.focal_x, 0.78, places=6)
		self.assertAlmostEqual(kayit.focal_y, 0.45, places=6)
		self.assertAlmostEqual(kayit.safe_x, 0.1, places=6)
		self.assertAlmostEqual(kayit.safe_w, 0.5, places=6)
		self.assertAlmostEqual(kayit.confidence, 0.6, places=6)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/ahmet/Desktop/istoc/tradehub_core && python3 -m unittest tradehub_core.tests.test_api_contracts.KirpmaTesti -v 2>&1 | tail -15`
Expected: `test_taze_etag_ile_kayit_kabul_edilir` and `test_kayit_yanitinin_etagi_sonraki_kayitta_gecer` FAIL with `AssertionError: 412 != 200`.

- [ ] **Step 3: Implement the fix in `crop.py`**

Add this method to `CropApi` (next to `get_intent`):

```python
	def _govde(self, asset: str, kayit: Mapping[str, Any], ham: Any) -> Dict[str, Any]:
		"""`get_intent` / `save_intent` gövdesi — ETag HER ZAMAN bu şekilden hesaplanır.

		2026-10-01: `If-Match` eskiden yalnız `{asset, intent}` üzerinden hesaplanıyordu,
		istemciye ise tam gövdenin ETag'i veriliyordu; taze ETag bile 412 alıyordu.
		"""
		intent = self._normalize_intent(ham)
		return {
			"asset": str(asset),
			"slot_key": self._slot_of(kayit),
			"exists": ham is not None,
			"intent": intent,
			"source": {
				"width": int(kayit.get("width") or 0),
				"height": int(kayit.get("height") or 0),
				"source_ratio": crop_core.source_ratio_of(kayit),
			},
			"windows": self._windows(kayit, intent),
		}
```

Replace the body construction in `get_intent` with:

```python
		kayit = self._asset(principal, asset)
		ham = self.intents.get(str(asset))
		return env.conditional_get(self._govde(asset, kayit, ham), if_none_match)
```

In `save_intent`, replace the statement `mevcut_ham = self.intents.get(str(asset))` **and** the `if if_match:` block that follows it (everything up to, not including, `yeni: Dict[str, Any] = …`) with:

```python
		mevcut_ham = self.intents.get(str(asset))
		if if_match:
			if not env.etag_matches(env.etag_for(self._govde(asset, kayit, mevcut_ham)), if_match):
				raise env.PreconditionFailed(
					"Kırpma niyeti bu arada değişti; sayfayı yenileyip tekrar deneyin.",
					kod=kod_uret(env.API_PREFIX, "precondition_failed"),
					detay={"asset": str(asset)},
				)
```

and replace the tail (from `kaydedilen = ...` through `return env.ok(...)`) with:

```python
		kaydedilen_ham = self.intents.save(str(asset), yeni) or yeni
		govde = self._govde(asset, kayit, kaydedilen_ham)
		# ETag `get_intent` ile AYNI gövde şeklinden — doğrudan `If-Match`e konabilir.
		return env.ok(govde, etag=env.etag_for(govde))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core && python3 -m unittest tradehub_core.tests.test_api_contracts -v 2>&1 | tail -4
for f in tradehub_core/media/pipeline/api/crop.py tradehub_core/tests/test_media_crop_intent.py tradehub_core/tests/test_api_contracts.py; do docker cp "$f" "istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/$f"; done
docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_crop_intent" 2>&1 | tail -5
docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site istoc.localhost run-tests --module tradehub_core.tests.test_crop_intent_zoom" 2>&1 | tail -3
ruff check tradehub_core/media/pipeline/api/crop.py
```
Expected: `test_api_contracts` → `OK` (including the existing `test_if_match_iyimser_kilit` still 412). Both bench modules end with `OK`. Ruff clean.

- [ ] **Step 5: Stage (no commit — user approves commits)**

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core && git add tradehub_core/media/pipeline/api/crop.py tradehub_core/tests/test_api_contracts.py tradehub_core/tests/test_media_crop_intent.py
```

---

### Task 3: Focal lookup (`media/odak.py`) and preview endpoints (`api/media_preview.py`) (Wave 1)

**Files:**
- Create: `tradehub_core/tradehub_core/media/odak.py`
- Create: `tradehub_core/tradehub_core/api/media_preview.py`
- Create: `tradehub_core/tradehub_core/tests/test_media_preview.py`

**Interfaces:**
- Consumes: `tradehub_core.api.media_crop._principal() -> env.Principal(user, roles, store)`, `Media Asset(name, slot_key, state, owner_seller, source_file, modified)`, `File(name, file_url, file_size, th_media_width, th_media_height)`, `Media Crop Intent(asset, focal_x, focal_y, modified)`, `Media URL Redirect(source_url, target_url, file_names JSON with [{"old_meta": {"th_media_width", "th_media_height"}}])`.
- Produces:
  - `tradehub_core.media.odak.odaklar(ogeler: Iterable[tuple[str, str]]) -> dict[tuple[str, str], dict[str, float]]` — key `(file_url, seller)`, value `{"x": float, "y": float}` (4 decimals). Latest intent by `modified` wins; archived assets count; falls back to a system (`owner_seller == ""`) intent; never returns another seller's focal.
  - Whitelisted `tradehub_core.api.media_preview.get_preview_target(file_url: str, slot_key: str) -> dict`:
    `{"file_url", "slot_key", "asset": str ("" = cannot save), "processing": bool, "source": {"width": int, "height": int, "bytes": int, "format": str}, "focal": {"x","y"} | None, "square": {"original": {"width","height"} | None, "size": int} | None}`
  - Whitelisted `get_preview_prefs() -> {"autoopen": bool}`; whitelisted POST `set_preview_prefs(autoopen: str = "1") -> {"autoopen": bool}`; user default key `PREF_KEY = "th_media_preview_autoopen"`.

- [ ] **Step 1: Write the failing test**

Create `tradehub_core/tradehub_core/tests/test_media_preview.py`:

```python
"""Görsel önizleme uçları + odak okuması (2026-10-01).

    docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && \
        bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_preview"
"""

from __future__ import annotations

import io

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tradehub_core.api import media_crop, media_preview
from tradehub_core.media import odak
from tradehub_core.tests.av_notr import setUpModule, tearDownModule  # noqa: F401

INTENT = "Media Crop Intent"
SLOT = "company.cover_image"


def _sil(doctype: str, name: str) -> None:
	if frappe.db.exists(doctype, name):
		frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
		frappe.db.commit()


def _png(w: int = 2000, h: int = 408) -> bytes:
	buf = io.BytesIO()
	Image.new("RGB", (w, h), (30, 60, 90)).save(buf, "PNG")
	return buf.getvalue()


class MediaPreviewTests(FrappeTestCase):
	def _user(self, tag: str) -> str:
		email = f"onz-{tag}-{self.suffix}@test.local"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": tag,
				"send_welcome_email": 0,
				"enabled": 1,
				"roles": [{"role": "Marketplace Seller"}, {"role": "Seller"}],
			}
		).insert(ignore_permissions=True)  # test kurulumu
		frappe.db.commit()
		self.addCleanup(lambda: _sil("User", email))
		return email

	def _store(self, tag: str, user: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_code": f"ONZ{tag}{self.suffix}",
				"seller_name": f"ONZ {tag} {self.suffix}",
				"user": user,
				"email": user,
				"status": "Active",
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)  # test kurulumu
		frappe.db.commit()
		self.addCleanup(lambda: _sil("Admin Seller Profile", doc.name))
		return doc.name

	def _asset(self, store: str, slot: str, state: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": slot,
				"media_type": "image",
				"state": state,
				"owner_seller": store,
				"content_sha256": frappe.generate_hash(length=64),
				"source_file": self.file_name,
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)  # test kurulumu
		frappe.db.commit()
		self.addCleanup(lambda: _sil(INTENT, doc.name))
		self.addCleanup(lambda: _sil("Media Asset", doc.name))
		return doc.name

	def setUp(self):
		super().setUp()
		self._orig = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self._orig))
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)
		self.owner = self._user("owner")
		self.other = self._user("other")
		self.owner_store = self._store("A", self.owner)
		self.other_store = self._store("B", self.other)
		dosya = frappe.get_doc(
			{"doctype": "File", "file_name": f"onz-{self.suffix}.png", "content": _png(), "is_private": 0}
		).insert(ignore_permissions=True)  # test kurulumu
		frappe.db.set_value("File", dosya.name, {"th_media_width": 2000, "th_media_height": 408})
		frappe.db.commit()
		self.addCleanup(lambda: _sil("File", dosya.name))
		self.file_name = dosya.name
		self.url = dosya.file_url

	# ── hedef seçimi ────────────────────────────────────────────────────

	def test_target_prefers_ready_asset_of_same_slot(self):
		self._asset(self.owner_store, "library.image", "ready")
		self._asset(self.owner_store, SLOT, "archived")
		hazir = self._asset(self.owner_store, SLOT, "ready")
		frappe.set_user(self.owner)
		hedef = media_preview.get_preview_target(file_url=self.url, slot_key=SLOT)
		self.assertEqual(hedef["asset"], hazir)
		self.assertFalse(hedef["processing"])
		self.assertEqual((hedef["source"]["width"], hedef["source"]["height"]), (2000, 408))
		self.assertIsNone(hedef["focal"])

	def test_other_seller_gets_no_asset_and_no_focal(self):
		varlik = self._asset(self.owner_store, SLOT, "ready")
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=varlik, focal_x=0.78, focal_y=0.45)
		frappe.set_user(self.other)
		hedef = media_preview.get_preview_target(file_url=self.url, slot_key=SLOT)
		self.assertEqual(hedef["asset"], "")
		self.assertIsNone(hedef["focal"])

	def test_target_returns_saved_focal(self):
		varlik = self._asset(self.owner_store, SLOT, "ready")
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=varlik, focal_x=0.78, focal_y=0.45)
		hedef = media_preview.get_preview_target(file_url=self.url, slot_key=SLOT)
		self.assertEqual(hedef["focal"], {"x": 0.78, "y": 0.45})

	def test_unknown_slot_rejected(self):
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError):
			media_preview.get_preview_target(file_url=self.url, slot_key="user.avatar")

	def test_guest_rejected(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			media_preview.get_preview_target(file_url=self.url, slot_key=SLOT)
		with self.assertRaises(frappe.PermissionError):
			media_preview.get_preview_prefs()

	# ── odak okuması ────────────────────────────────────────────────────

	def test_odaklar_latest_wins_and_archived_counts(self):
		eski = self._asset(self.owner_store, SLOT, "ready")
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=eski, focal_x=0.1, focal_y=0.1)
		frappe.set_user("Administrator")
		frappe.db.set_value("Media Asset", eski, "state", "archived", update_modified=False)
		yeni = self._asset(self.owner_store, SLOT, "ready")
		self.assertEqual(odak.odaklar([(self.url, self.owner_store)]), {
			(self.url, self.owner_store): {"x": 0.1, "y": 0.1}
		})
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=yeni, focal_x=0.78, focal_y=0.45)
		self.assertEqual(
			odak.odaklar([(self.url, self.owner_store)])[(self.url, self.owner_store)], {"x": 0.78, "y": 0.45}
		)

	def test_odaklar_never_crosses_tenants(self):
		varlik = self._asset(self.owner_store, SLOT, "ready")
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=varlik, focal_x=0.78, focal_y=0.45)
		self.assertEqual(odak.odaklar([(self.url, self.other_store)]), {})

	# ── kullanıcı tercihi ───────────────────────────────────────────────

	def test_prefs_default_on_and_per_user(self):
		frappe.set_user(self.owner)
		self.addCleanup(lambda: frappe.defaults.clear_user_default(media_preview.PREF_KEY, self.owner))
		self.assertEqual(media_preview.get_preview_prefs(), {"autoopen": True})
		self.assertEqual(media_preview.set_preview_prefs(autoopen="0"), {"autoopen": False})
		self.assertEqual(media_preview.get_preview_prefs(), {"autoopen": False})
		frappe.set_user(self.other)
		self.assertEqual(media_preview.get_preview_prefs(), {"autoopen": True})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core
docker cp tradehub_core/tests/test_media_preview.py istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/tests/test_media_preview.py
docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_preview" 2>&1 | tail -5
```
Expected: `ImportError: cannot import name 'media_preview' from 'tradehub_core.api'`.

- [ ] **Step 3: Implement `media/odak.py`**

```python
"""Odak noktası okuması — vitrin ve önizleme penceresinin TEK kaynağı (2026-10-01).

Anahtar `(file_url, satıcı)`dır, varlık değil: `kare.py` / `magaza_gorseli.py`
dönüştürdüğü dosyanın eski `Media Asset`ini `archived` yapıp AYNI `File`
satırına yeni varlık açar ve `File.file_url`i yeni adrese çevirir. Odak eski
varlıktaysa bile bu sorgu onu yeni adresle bulur (join `File` üzerinden).
Aynı adreste 5+ mükerrer `File` satırı ölçülmüştür; join `file_url` iledir.

Sistem okumasıdır: odak bir mahremiyet değeri değildir (vitrinde CSS olarak
herkese açık basılıyor) ve guest bağlamında `get_list` hiçbir şey döndürmez.
Kiracı sınırı anahtarın kendisindedir — bir satıcının odağı BAŞKA satıcının
isteğine asla dönmez; yalnız sistem (`owner_seller` boş) odağı yedektir.
"""

from __future__ import annotations

from collections.abc import Iterable

import frappe
from frappe.query_builder import DocType


def odaklar(ogeler: Iterable[tuple[str, str]]) -> dict[tuple[str, str], dict[str, float]]:
	"""`(file_url, satıcı)` → `{"x", "y"}` — o satıcının o dosya için kaydettiği EN SON odak."""
	istekler = {(str(u), str(s or "")) for u, s in ogeler if u}
	if not istekler:
		return {}
	niyet, varlik, dosya = DocType("Media Crop Intent"), DocType("Media Asset"), DocType("File")
	satirlar = (
		frappe.qb.from_(niyet)
		.join(varlik)
		.on(varlik.name == niyet.asset)
		.join(dosya)
		.on(dosya.name == varlik.source_file)
		.select(dosya.file_url, varlik.owner_seller, niyet.focal_x, niyet.focal_y, niyet.modified)
		.where(dosya.file_url.isin(sorted({u for u, _ in istekler})))
		.where(niyet.focal_x.isnotnull())
		.where(niyet.focal_y.isnotnull())
		.orderby(niyet.modified)
	).run(as_dict=True)
	son: dict[tuple[str, str], dict[str, float]] = {}
	for r in satirlar:
		# Artan `modified` sırası: sonraki satır öncekinin üstüne yazar → en son kazanır.
		son[(r["file_url"], str(r.get("owner_seller") or ""))] = {
			"x": round(float(r["focal_x"]), 4),
			"y": round(float(r["focal_y"]), 4),
		}
	cikti: dict[tuple[str, str], dict[str, float]] = {}
	for u, s in istekler:
		deger = son.get((u, s)) or son.get((u, ""))
		if deger:
			cikti[(u, s)] = deger
	return cikti
```

- [ ] **Step 4: Implement `api/media_preview.py`**

```python
"""Görsel önizleme penceresi uçları — `ImagePlacementModal` (2026-10-01).

Pencere bir DOSYA adresiyle açılır; odak ise `Media Crop Intent`te VARLIK
başına durur. `get_preview_target` köprüdür: oturumdaki satıcının bu dosya
için en uygun varlığını seçer (önce odağın durduğu canlı varlık, sonra aynı
slotun `ready` varlığı, sonra arşivlenmemiş herhangi biri). Başka satıcının
varlığı ASLA seçilmez; seçilemezse `asset: ""` döner ve pencere Kaydet'i kapatır.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.query_builder import DocType

from tradehub_core.api.media_crop import _principal
from tradehub_core.media import odak

PREF_KEY = "th_media_preview_autoopen"
SLOT_KEYS = frozenset({"company.cover_image", "seller.logo", "product.image"})
ADMIN_ROLES = frozenset({"System Manager", "Marketplace Admin"})
_HAZIR = "ready"
_EMEKLI = "archived"


def _giris_zorunlu() -> None:
	if frappe.session.user in ("Guest", "", None):
		frappe.throw(_("Bu işlem için giriş yapmalısınız."), frappe.PermissionError)


def _adaylar(url: str, magaza: str, yonetici: bool) -> list[dict[str, Any]]:
	varlik, dosya = DocType("Media Asset"), DocType("File")
	sorgu = (
		frappe.qb.from_(varlik)
		.join(dosya)
		.on(dosya.name == varlik.source_file)
		.select(varlik.name, varlik.slot_key, varlik.state, varlik.owner_seller, varlik.modified)
		.where(dosya.file_url == url)
	)
	if not yonetici:
		if not magaza:
			return []
		sorgu = sorgu.where(varlik.owner_seller == magaza)
	return sorgu.run(as_dict=True)


def _odak_varligi(adlar: list[str]) -> str:
	if not adlar:
		return ""
	niyet = DocType("Media Crop Intent")
	satir = (
		frappe.qb.from_(niyet)
		.select(niyet.asset)
		.where(niyet.asset.isin(adlar))
		.where(niyet.focal_x.isnotnull())
		.orderby(niyet.modified, order=frappe.qb.desc)
		.limit(1)
	).run(as_dict=True)
	return satir[0]["asset"] if satir else ""


def _varlik_sec(adaylar: list[dict[str, Any]], slot_key: str) -> dict[str, Any] | None:
	canli = [a for a in adaylar if a.get("state") != _EMEKLI]
	if not canli:
		return None
	odakli = _odak_varligi([a["name"] for a in canli])
	if odakli:
		return next(a for a in canli if a["name"] == odakli)
	return max(
		canli,
		key=lambda a: (a.get("slot_key") == slot_key, a.get("state") == _HAZIR, str(a.get("modified"))),
	)


def _kare_ozeti(url: str, w: int, h: int) -> dict[str, Any]:
	"""Ürün görseli kareye tamamlandıysa ilk ölçü `Media URL Redirect.file_names` künyesinde."""
	ozgun = None
	ham = frappe.db.get_value("Media URL Redirect", {"target_url": url}, "file_names")
	try:
		kayitlar = json.loads(ham or "[]")
	except (TypeError, ValueError):
		kayitlar = []
	for k in kayitlar if isinstance(kayitlar, list) else []:
		meta = (k or {}).get("old_meta") or {}
		ow, oh = int(meta.get("th_media_width") or 0), int(meta.get("th_media_height") or 0)
		if ow and oh:
			ozgun = {"width": ow, "height": oh}
			break
	return {"original": ozgun, "size": w if w and w == h else 0}


@frappe.whitelist()
def get_preview_target(file_url: str, slot_key: str) -> dict:
	"""Dosya + slot → önizleme hedefi (varlık, ölçü, kayıtlı odak)."""
	_giris_zorunlu()
	if slot_key not in SLOT_KEYS:
		frappe.throw(_("Bilinmeyen görsel yeri: {0}").format(slot_key), frappe.ValidationError)
	url = str(file_url or "").strip()
	kim = _principal()
	yonetici = bool(ADMIN_ROLES & set(kim.roles))
	adaylar = _adaylar(url, kim.store, yonetici)
	secilen = _varlik_sec(adaylar, slot_key)
	sahip = kim.store or (str(secilen.get("owner_seller") or "") if secilen else "")

	kunye = frappe.db.get_value(
		"File", {"file_url": url}, ["file_size", "th_media_width", "th_media_height"], as_dict=True
	) or {}
	w, h = int(kunye.get("th_media_width") or 0), int(kunye.get("th_media_height") or 0)
	bicim = url.rsplit(".", 1)[-1].lower() if "." in url.rsplit("/", 1)[-1] else ""
	odak_degeri = odak.odaklar([(url, sahip)]).get((url, sahip)) if secilen else None

	return {
		"file_url": url,
		"slot_key": slot_key,
		"asset": secilen["name"] if secilen else "",
		"processing": not (secilen and secilen.get("state") == _HAZIR),
		"source": {"width": w, "height": h, "bytes": int(kunye.get("file_size") or 0), "format": bicim},
		"focal": odak_degeri,
		"square": _kare_ozeti(url, w, h) if slot_key == "product.image" else None,
	}


@frappe.whitelist()
def get_preview_prefs() -> dict:
	"""Pencere tek yüklemede kendiliğinden açılsın mı — kullanıcıya özel, varsayılan AÇIK."""
	_giris_zorunlu()
	deger = frappe.defaults.get_user_default(PREF_KEY)
	return {"autoopen": deger is None or str(deger).strip().lower() not in ("0", "false")}


@frappe.whitelist(methods=["POST"])
def set_preview_prefs(autoopen: str = "1") -> dict:
	"""Tercihi sunucuda sakla (cihazdan bağımsız)."""
	_giris_zorunlu()
	acik = str(autoopen).strip().lower() not in ("0", "false", "")
	frappe.defaults.set_user_default(PREF_KEY, "1" if acik else "0")
	return {"autoopen": acik}
```

(Before writing, confirm with context7 for **Frappe v15** that `frappe.defaults.get_user_default(key, user=None)`, `set_user_default(key, value, user=None)` and `clear_user_default(key, user=None)` have these signatures.)

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core
for f in tradehub_core/media/odak.py tradehub_core/api/media_preview.py tradehub_core/tests/test_media_preview.py; do docker cp "$f" "istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/$f"; done
docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_preview" 2>&1 | tail -5
ruff check tradehub_core/media/odak.py tradehub_core/api/media_preview.py tradehub_core/tests/test_media_preview.py
```
Expected: `Ran 8 tests … OK`; ruff clean. If `test_target_prefers_ready_asset_of_same_slot` sees an extra auto-created asset (pipeline hook on `File` insert), it has `owner_seller` ≠ the test store and is filtered by `_adaylar`; if it is not, report it — do not weaken the assertion.

- [ ] **Step 6: Stage (no commit — user approves commits)**

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core && git add tradehub_core/media/odak.py tradehub_core/api/media_preview.py tradehub_core/tests/test_media_preview.py
```

---
### Task 4: `focal` in the store `*_media` payloads (Wave 2 — after T3)

**Files:**
- Modify: `tradehub_core/tradehub_core/api/media_manifest.py` (`magaza_gorsel_medyasi` ≈ line 1373)
- Create: `tradehub_core/tradehub_core/tests/test_magaza_odak.py`

**Interfaces:**
- Consumes: `tradehub_core.media.odak.odaklar(ogeler) -> {(file_url, seller): {"x","y"}}` (Task 3).
- Produces (contract for Task 9): every store body produced by `magaza_gorsel_medyasi` — and therefore `logo_media`, `banner_image_media`, `cover_image_media`, `gallery_images_media[]`, media-group `src_media` / `poster_media`, and `get_storefront_layout.image_media[url]` — carries `focal: {"x": float, "y": float}` **only** when that seller saved a focal for that file. When a focal exists but no WebP rendition is servable (or the pipeline flag is off), the body is `{"src": <file_url>, "srcset": "", "width": 0, "height": 0, "focal": {...}}`. Without a focal, bodies are byte-for-byte what they are today (and absent keys stay `None` in `magaza_medyasi_ekle`).

- [ ] **Step 1: Write the failing test**

Create `tradehub_core/tradehub_core/tests/test_magaza_odak.py`:

```python
"""Mağaza `*_media` gövdelerinde `focal` (2026-10-01).

    docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && \
        bench --site istoc.localhost run-tests --module tradehub_core.tests.test_magaza_odak"
"""

from unittest import mock

from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_manifest
from tradehub_core.media import odak

URL = "/files/c2/odak-test.webp"
SLOT = "company.cover_image"
ODAK = {"x": 0.78, "y": 0.45}


def _govde(url, slot, turevler):
	return {"src": url, "srcset": f"{url} 640w", "width": 640, "height": 131}


class MagazaOdakTests(FrappeTestCase):
	def test_turevli_govdeye_focal_eklenir(self):
		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=True),
			mock.patch.object(
				media_manifest,
				"_varliklari_getir",
				return_value={URL: {"S": {"name": "A1", "active_version": "v"}}},
			),
			mock.patch.object(media_manifest, "_turevleri_getir", return_value={"A1": [{}]}),
			mock.patch.object(media_manifest, "_magaza_govdesi", side_effect=_govde),
			mock.patch.object(odak, "odaklar", return_value={(URL, "S"): ODAK}),
		):
			sonuc = media_manifest.magaza_gorsel_medyasi([(URL, SLOT, "S")])
		self.assertEqual(sonuc[(URL, SLOT)]["focal"], ODAK)
		self.assertEqual(sonuc[(URL, SLOT)]["srcset"], f"{URL} 640w")

	def test_bayrak_kapaliyken_yalniz_odak_govdesi(self):
		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=False),
			mock.patch.object(odak, "odaklar", return_value={(URL, "S"): ODAK}),
		):
			sonuc = media_manifest.magaza_gorsel_medyasi([(URL, SLOT, "S")])
		self.assertEqual(
			sonuc[(URL, SLOT)], {"src": URL, "srcset": "", "width": 0, "height": 0, "focal": ODAK}
		)

	def test_odak_yoksa_bugunku_davranis(self):
		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=False),
			mock.patch.object(odak, "odaklar", return_value={}),
		):
			self.assertEqual(media_manifest.magaza_gorsel_medyasi([(URL, SLOT, "S")]), {})

	def test_ozel_dosyanin_odagi_vitrine_gomulmez(self):
		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=False),
			mock.patch.object(odak, "odaklar", return_value={("/private/files/x.png", "S"): ODAK}) as cagri,
		):
			sonuc = media_manifest.magaza_gorsel_medyasi([("/private/files/x.png", SLOT, "S")])
		self.assertEqual(sonuc, {})
		self.assertEqual(list(cagri.call_args.args[0]), [])

	def test_ekle_alana_focal_tasir(self):
		kayit = {"banner_image": URL, "name": "S"}
		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=False),
			mock.patch.object(odak, "odaklar", return_value={(URL, "S"): ODAK}),
		):
			media_manifest.magaza_medyasi_ekle([kayit], {"banner_image": SLOT}, "name")
		self.assertEqual(kayit["banner_image_media"]["focal"], ODAK)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core
docker cp tradehub_core/tests/test_magaza_odak.py istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/tests/test_magaza_odak.py
docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site istoc.localhost run-tests --module tradehub_core.tests.test_magaza_odak" 2>&1 | tail -6
```
Expected: FAIL — `KeyError: 'focal'` in `test_turevli_govdeye_focal_eklenir` and `{} != {...}` in `test_bayrak_kapaliyken_yalniz_odak_govdesi`. (The container must already have Task 3's `media/odak.py`; copy it if it is missing.)

- [ ] **Step 3: Implement**

In `media_manifest.py`, rename the current function body of `magaza_gorsel_medyasi` to a private helper and wrap it. Concretely:

1. Rename `def magaza_gorsel_medyasi(` to `def _magaza_turev_govdeleri(` (keep its body and its long docstring unchanged; change only the first docstring line to `"""Türev gövdeleri — `magaza_gorsel_medyasi`nin bayrağa bağlı yarısı."""`).
2. Insert above it:

```python
def magaza_gorsel_medyasi(
	ogeler: Iterable[tuple[str, str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
	"""`(url, slot, satıcı)` → `{src, srcset, width, height[, focal]}` — vitrinin `srcset`i + odağı.

	Türev kısmı `_magaza_turev_govdeleri`dir (bayrak kapalıysa boş). Odak
	(2026-10-01) bayraktan BAĞIMSIZ eklenir: odak kaydı olup türevi olmayan
	görsel `srcset: ""` gövdesi alır; vitrin ham adrese düşer ama
	`object-position`ı yine uygular. Asla hata fırlatmaz.
	"""
	ogeler = list(ogeler)
	cikti = _magaza_turev_govdeleri(ogeler)
	_odaklari_ekle(cikti, ogeler)
	return cikti


def _odaklari_ekle(cikti: dict[tuple[str, str], dict[str, Any]], ogeler: list[tuple[str, str, str]]) -> None:
	"""Odak kaydı olan görsele `focal: {x, y}` yaz (yalnız herkese açık `/files/`)."""
	try:
		from tradehub_core.media import odak as odak_mod

		istekler = [
			(u, sl, st or "") for u, sl, st in ogeler if u and sl and _yerel_url(u).startswith("/files/")
		]
		odaklar = odak_mod.odaklar((u, st) for u, _sl, st in istekler)
		for url, slot, satici in istekler:
			deger = odaklar.get((url, satici))
			if not deger:
				continue
			govde = cikti.get((url, slot))
			if govde is None:
				cikti[(url, slot)] = {"src": url, "srcset": "", "width": 0, "height": 0, "focal": dict(deger)}
			else:
				govde["focal"] = dict(deger)
	except Exception:
		# Odak bir süs değil ama vitrini düşürecek kadar da kritik değil: türev
		# gövdeleri dokunulmadan döner, hata Error Log'a düşer.
		frappe.log_error(title="media manifest mağaza odağı", message=frappe.get_traceback())
```

`_magaza_turev_govdeleri` already takes an iterable and is only called from here; `magaza_medyasi_ekle` and the `seller.py` callers keep calling `magaza_gorsel_medyasi` — no other file changes.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core
docker cp tradehub_core/api/media_manifest.py istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/api/media_manifest.py
for m in test_magaza_odak test_magaza_gorseli test_media_manifest_api test_manifest_batch; do docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site istoc.localhost run-tests --module tradehub_core.tests.$m" 2>&1 | tail -2; done
ruff check tradehub_core/api/media_manifest.py tradehub_core/tests/test_magaza_odak.py
```
Expected: four modules end with `OK` (`test_magaza_gorseli`'s existing mocks still pass because `odaklar` finds no intent for `/files/a.png`). Ruff clean.

- [ ] **Step 5: Stage (no commit — user approves commits)**

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core && git add tradehub_core/api/media_manifest.py tradehub_core/tests/test_magaza_odak.py
```

---

### Task 5: Focal geometry, `saveFocalOnly`, preview API wrappers and `useFocalPoint` (Wave 1)

**Why `saveFocalOnly`:** the existing `saveCropIntent` always sends `safe_area: JSON.stringify(guvenli || {})`, and the endpoint reads `{}` as "DELETE the safe area" (`cropIntentApi.js` comment, `_parse_safe_area`). A focal-only save through it would wipe a seller's Crop Studio safe area. The window must send only focal fields.

**Files:**
- Modify: `admin-panel/frontend/src/lib/media/crop/geometry.js` (append a section after the re-export block)
- Modify: `admin-panel/frontend/src/lib/media/crop/cropIntentApi.js` (append `saveFocalOnly`)
- Create: `admin-panel/frontend/src/lib/media/preview/previewApi.js`
- Create: `admin-panel/frontend/src/composables/useFocalPoint.js`
- Create: `admin-panel/frontend/src/lib/media/crop/__tests__/focalGeometry.test.js`
- Create: `admin-panel/frontend/src/composables/__tests__/focalPoint.test.js`

**Interfaces:**
- Consumes: `fromServerSuggestion(body) -> {x, y, algorithm, algorithmVersion, …} | null` (`lib/media/crop/focusSuggest.js`); `getCropIntent(asset)`, `suggestCropFocal(asset)` (`cropIntentApi.js`); Task 2's ETag contract; Task 3 endpoint names.
- Produces:
  - `geometry.js`: `clampFocal(value) -> number` (NaN → 0.5), `visibleFraction(imageRatio, placeRatio, fit = "cover") -> {x, y}`, `frameRect(imageRatio, placeRatio, focal, fit = "cover") -> {left, top, width, height}` (all 0–1), `objectPosition(focal) -> "78% 45%"`.
  - `cropIntentApi.js`: `saveFocalOnly({asset, focalX, focalY, ifMatch = "", previewed = [], method = "manual", algorithm = "", algorithmVersion = ""}) -> Promise<body>`.
  - `previewApi.js`: `getPreviewTarget(fileUrl, slotKey)`, `getPreviewPrefs()`, `setPreviewPrefs(autoopen: boolean)`, `getImageDimensions(fileUrl) -> {width, height}`; constants `TARGET_METHOD`, `PREFS_GET_METHOD`, `PREFS_SET_METHOD`, `DIMENSIONS_METHOD`.
  - `useFocalPoint({asset = "", initialFocal = null, deps = null}) -> { focal: Ref<{x,y}>, percent: ComputedRef<{x,y}>, dirty: ComputedRef<boolean>, loading, saving, conflict, failed: Ref<boolean>, announce: ShallowRef<{key: string, params: object} | null>, load(), suggest(), setFocal(x, y), setPercent(axis, value), nudge(dx, dy, big = false), center(), markViewed(placeKey, device), save() -> Promise<{ok: boolean, reason?: "no-asset"|"conflict"|"error"}> }`. `deps = {getIntent(asset), suggest(asset), saveFocal(payload)}`; default lazily imports `cropIntentApi.js`. Announcement keys: `imagePlacement.status.moved` (`{x, y}` integer percents), `.suggested`, `.centered`, `.saved`, `.saveFailed`, `.conflict`.

- [ ] **Step 1: Write the failing tests**

Create `admin-panel/frontend/src/lib/media/crop/__tests__/focalGeometry.test.js`:

```js
import assert from "node:assert/strict";
import { test } from "node:test";

import { clampFocal, frameRect, objectPosition, visibleFraction } from "../geometry.js";

const BANNER = 2000 / 408; // Özgen Plastik banner'ı

test("clampFocal: 0-1 aralığı, sayı değilse merkez", () => {
  assert.equal(clampFocal(0.3), 0.3);
  assert.equal(clampFocal(-1), 0);
  assert.equal(clampFocal(2), 1);
  assert.equal(clampFocal("x"), 0.5);
  assert.equal(clampFocal(undefined), 0.5);
});

test("visibleFraction: geniş görsel dar yerde yatayda kesilir", () => {
  const v = visibleFraction(BANNER, 390 / 180);
  assert.ok(Math.abs(v.x - 0.442) < 0.001);
  assert.equal(v.y, 1);
});

test("visibleFraction: dik görsel geniş yerde dikeyde kesilir; contain hiç kesmez", () => {
  assert.deepEqual(visibleFraction(0.5, 1), { x: 1, y: 0.5 });
  assert.deepEqual(visibleFraction(BANNER, 1, "contain"), { x: 1, y: 1 });
  assert.deepEqual(visibleFraction(0, 1), { x: 1, y: 1 });
});

test("frameRect: çerçeve konumu (1 − görünen) × odak", () => {
  const r = frameRect(BANNER, 390 / 180, { x: 0.78, y: 0.45 });
  assert.ok(Math.abs(r.width - 0.442) < 0.001);
  assert.ok(Math.abs(r.left - (1 - r.width) * 0.78) < 1e-9);
  assert.equal(r.top, 0);
  assert.equal(r.height, 1);
});

test("frameRect CSS object-position ile aynı pikseli verir", () => {
  // CSS: offset = (kutu − çizilen) × p; çizilen genişlik = kutuYükseklik × görselOranı.
  const kutuW = 390, kutuH = 180, p = 0.78;
  const cizilen = kutuH * BANNER;
  const solPiksel = -(kutuW - cizilen) * p;
  const r = frameRect(BANNER, kutuW / kutuH, { x: p, y: 0.5 });
  assert.ok(Math.abs(r.left * cizilen - solPiksel) < 1e-6);
});

test("objectPosition: kayan nokta artığı yok", () => {
  assert.equal(objectPosition({ x: 0.78, y: 0.45 }), "78% 45%");
  assert.equal(objectPosition({ x: 0.123, y: 1 }), "12.3% 100%");
  assert.equal(objectPosition(null), "50% 50%");
});
```

Create `admin-panel/frontend/src/composables/__tests__/focalPoint.test.js`:

```js
import assert from "node:assert/strict";
import { test } from "node:test";

import { useFocalPoint } from "../useFocalPoint.js";

function fakeDeps({ intent = null, suggestion = null, suggestError = null, saveErrors = [] } = {}) {
  const calls = { get: 0, suggest: 0, save: [] };
  return {
    calls,
    deps: {
      async getIntent() {
        calls.get += 1;
        return { etag: '"e1"', exists: !!intent, intent: intent || { focal_x: null, focal_y: null } };
      },
      async suggest() {
        calls.suggest += 1;
        if (suggestError) throw suggestError;
        return { suggestion: suggestion || { focal_x: 0.7, focal_y: 0.3, grid: 32, measured: true } };
      },
      async saveFocal(payload) {
        calls.save.push(payload);
        const err = saveErrors.shift();
        if (err) throw err;
        return { etag: '"e2"', exists: true };
      },
    },
  };
}

test("kayıtlı odak okunur; öneri istenmez; değişiklik yok", async () => {
  const { deps, calls } = fakeDeps({ intent: { focal_x: 0.78, focal_y: 0.45 } });
  const fp = useFocalPoint({ asset: "A1", deps });
  await fp.load();
  assert.deepEqual(fp.focal.value, { x: 0.78, y: 0.45 });
  assert.equal(calls.suggest, 0);
  assert.equal(fp.dirty.value, false);
});

test("odak yoksa otomatik öneri uygulanır ve bildirilir", async () => {
  const { deps } = fakeDeps();
  const fp = useFocalPoint({ asset: "A1", deps });
  await fp.load();
  assert.deepEqual(fp.focal.value, { x: 0.7, y: 0.3 });
  assert.equal(fp.announce.value.key, "imagePlacement.status.suggested");
});

test("öneri başarısız (429 dahil) → ortadan başlar, bildirim yok", async () => {
  const err = Object.assign(new Error("Too many"), { status: 429 });
  const { deps } = fakeDeps({ suggestError: err });
  const fp = useFocalPoint({ asset: "A1", deps });
  await fp.load();
  assert.deepEqual(fp.focal.value, { x: 0.5, y: 0.5 });
  assert.equal(fp.announce.value, null);
});

test("ok tuşu adımı %1, Shift %10; sınırda kalır", () => {
  const fp = useFocalPoint({ asset: "A1", deps: fakeDeps().deps });
  fp.nudge(1, 0);
  assert.equal(fp.percent.value.x, 51);
  fp.nudge(1, 0, true);
  assert.equal(fp.percent.value.x, 61);
  fp.setFocal(0.99, 0.5);
  fp.nudge(1, 0, true);
  assert.equal(fp.focal.value.x, 1);
  assert.equal(fp.announce.value.key, "imagePlacement.status.moved");
  assert.deepEqual(fp.announce.value.params, { x: 100, y: 50 });
});

test("sayı kutusuna sayı olmayan değer → %50", () => {
  const fp = useFocalPoint({ asset: "A1", deps: fakeDeps().deps });
  fp.setPercent("x", "abc");
  assert.equal(fp.focal.value.x, 0.5);
  fp.setPercent("y", "78");
  assert.equal(fp.focal.value.y, 0.78);
});

test("Kaydet yalnız odak + ETag + önizleme kanıtı gönderir", async () => {
  const { deps, calls } = fakeDeps({ intent: { focal_x: 0.5, focal_y: 0.5 } });
  const fp = useFocalPoint({ asset: "A1", deps });
  await fp.load();
  fp.markViewed("store_hero", "mobile");
  fp.setFocal(0.78, 0.45);
  const r = await fp.save();
  assert.deepEqual(r, { ok: true });
  const p = calls.save[0];
  assert.equal(p.asset, "A1");
  assert.equal(p.focalX, 0.78);
  assert.equal(p.focalY, 0.45);
  assert.equal(p.ifMatch, '"e1"');
  assert.equal(p.method, "manual");
  assert.deepEqual(p.previewed, [{ place: "store_hero", device: "mobile" }]);
  assert.equal("safe_area" in p, false);
  assert.equal(fp.dirty.value, false);
});

test("412 → çakışma; değişiklik kaybolmaz", async () => {
  const conflict = Object.assign(new Error("changed"), { status: 412 });
  const { deps } = fakeDeps({ saveErrors: [conflict] });
  const fp = useFocalPoint({ asset: "A1", deps });
  fp.setFocal(0.78, 0.45);
  const r = await fp.save();
  assert.deepEqual(r, { ok: false, reason: "conflict" });
  assert.equal(fp.conflict.value, true);
  assert.deepEqual(fp.focal.value, { x: 0.78, y: 0.45 });
  assert.equal(fp.announce.value.key, "imagePlacement.status.conflict");
});

test("ağ hatası → tekrar denenebilir, ikinci deneme başarılı", async () => {
  const { deps, calls } = fakeDeps({ saveErrors: [new Error("offline")] });
  const fp = useFocalPoint({ asset: "A1", deps });
  fp.setFocal(0.2, 0.2);
  assert.deepEqual(await fp.save(), { ok: false, reason: "error" });
  assert.equal(fp.failed.value, true);
  assert.deepEqual(await fp.save(), { ok: true });
  assert.equal(calls.save.length, 2);
});

test("varlık yoksa API çağrılmaz, kaydetme reddedilir", async () => {
  const { deps, calls } = fakeDeps();
  const fp = useFocalPoint({ asset: "", initialFocal: { x: 0.6, y: 0.4 }, deps });
  await fp.load();
  assert.equal(calls.get, 0);
  assert.deepEqual(fp.focal.value, { x: 0.6, y: 0.4 });
  assert.deepEqual(await fp.save(), { ok: false, reason: "no-asset" });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/ahmet/Desktop/istoc/admin-panel/frontend && node --test src/lib/media/crop/__tests__/focalGeometry.test.js src/composables/__tests__/focalPoint.test.js 2>&1 | tail -5`
Expected: FAIL — `SyntaxError: The requested module '../geometry.js' does not provide an export named 'clampFocal'` and `Cannot find module '…/useFocalPoint.js'`.

- [ ] **Step 3: Implement**

Append to `src/lib/media/crop/geometry.js` (below the existing `export { … } from "./vendor/crop_geometry.js";`):

```js
/*
 * ── Görünür kısım: CSS object-fit / object-position modeli (2026-10-01) ──
 *
 * Bu dört fonksiyon SUNUCUNUN kırpma penceresi DEĞİLDİR (o `crop_geometry`
 * ikizidir ve yukarıdan yeniden dışa aktarılır). Burası tarayıcının
 * `object-fit: cover` + `object-position: X% Y%` ile görseli nasıl
 * kestiğinin birebir modelidir; vitrin aynı değeri CSS olarak uyguladığı
 * için önizleme = vitrin. Spec: 2026-10-01-gorsel-onizleme-odak-design.md §4.2.
 */

/** 0-1 aralığına kelepçele; sayı değilse merkez (0.5). */
export function clampFocal(value) {
  const n = Number(value);
  if (value === null || value === undefined || !Number.isFinite(n)) return 0.5;
  return Math.min(1, Math.max(0, n));
}

/** Görselin yerde görünen payı: `min(1, yerOranı / görselOranı)` (yatay) ya da dikey eşdeğeri. */
export function visibleFraction(imageRatio, placeRatio, fit = "cover") {
  if (!(imageRatio > 0) || !(placeRatio > 0) || fit === "contain") return { x: 1, y: 1 };
  if (placeRatio < imageRatio) return { x: placeRatio / imageRatio, y: 1 };
  return { x: 1, y: imageRatio / placeRatio };
}

/** Görselin üstünde görünen çerçeve (0-1): konum = (1 − görünen) × odak. */
export function frameRect(imageRatio, placeRatio, focal, fit = "cover") {
  const v = visibleFraction(imageRatio, placeRatio, fit);
  return {
    left: (1 - v.x) * clampFocal(focal?.x),
    top: (1 - v.y) * clampFocal(focal?.y),
    width: v.x,
    height: v.y,
  };
}

/** CSS `object-position` değeri — `0.78` → `"78%"` (kayan nokta artığı yok). */
export function objectPosition(focal) {
  const p = (v) => `${Math.round(clampFocal(v) * 1000) / 10}%`;
  return `${p(focal?.x)} ${p(focal?.y)}`;
}
```

Also update the header comment's first bullet sentence "**Bu dosyada matematik YOKTUR ve olmayacaktır.**" to: "**Sunucu kırpma matematiği bu dosyada YOKTUR** (aşağıdaki görünür-kısım bölümü CSS modelidir, sunucu penceresi değildir)."

Append to `src/lib/media/crop/cropIntentApi.js`:

```js
/**
 * Yalnız odak noktasını kaydeder — önizleme penceresi (2026-10-01).
 *
 * `saveCropIntent` HER ZAMAN `safe_area` gönderir ve uç `{}` değerini
 * "güvenli alanı SİL" diye okur; bu yüzden pencere onu KULLANMAZ. Burada
 * `safe_area`, `zoom`, `center_*`, `overrides` HİÇ gönderilmez: uç `None`ı
 * "dokunma" diye okur ve Crop Studio'da çizilmiş her şey korunur.
 * Onay, önizleme kanıtıyla birlikte gider (T-114 sunucu kapısı).
 */
export async function saveFocalOnly({
  asset,
  focalX,
  focalY,
  ifMatch = "",
  previewed = [],
  method = "manual",
  algorithm = "",
  algorithmVersion = "",
}) {
  return typedApi.saveCropIntent({
    asset,
    focal_x: focalX,
    focal_y: focalY,
    if_match: ifMatch,
    approved_by_user: previewed.length ? 1 : 0,
    previewed_placements: JSON.stringify(previewed),
    method,
    algorithm,
    algorithm_version: algorithmVersion,
  });
}
```

Create `src/lib/media/preview/previewApi.js`:

```js
import api from "@/utils/api";

/** Görsel önizleme penceresi uçları — `tradehub_core/api/media_preview.py`. */
export const TARGET_METHOD = "tradehub_core.api.media_preview.get_preview_target";
export const PREFS_GET_METHOD = "tradehub_core.api.media_preview.get_preview_prefs";
export const PREFS_SET_METHOD = "tradehub_core.api.media_preview.set_preview_prefs";
export const DIMENSIONS_METHOD = "tradehub_core.api.seller_media.get_dimensions";

const unwrap = (res) => res?.message ?? res;

/** Dosya + slot → `{asset, processing, source, focal, square}`. */
export async function getPreviewTarget(fileUrl, slotKey) {
  return unwrap(await api.callMethodGET(TARGET_METHOD, { file_url: fileUrl, slot_key: slotKey }));
}

/** `{autoopen: boolean}` — kullanıcıya özel, sunucuda. */
export async function getPreviewPrefs() {
  return unwrap(await api.callMethodGET(PREFS_GET_METHOD, {}));
}

export async function setPreviewPrefs(autoopen) {
  return unwrap(await api.callMethod(PREFS_SET_METHOD, { autoopen: autoopen ? "1" : "0" }));
}

/** Rozet için gerçek piksel ölçüsü (`seller_media.get_dimensions`, sahiplik kapılı). */
export async function getImageDimensions(fileUrl) {
  return unwrap(await api.callMethodGET(DIMENSIONS_METHOD, { file_url: fileUrl }));
}
```

Create `src/composables/useFocalPoint.js`:

```js
import { computed, ref, shallowRef } from "vue";

import { clampFocal } from "../lib/media/crop/geometry.js";
import { fromServerSuggestion } from "../lib/media/crop/focusSuggest.js";

/**
 * Önizleme penceresinin odak noktası durumu (spec §4.3).
 *
 * Saf kalır: i18n yok (bildirimler `{key, params}` olarak döner), HTTP
 * `deps` ile enjekte edilir; varsayılan `cropIntentApi.js` TEMBEL yüklenir
 * çünkü `@/utils/api` Vite dışında import edilemez. `useCropStudio.js`'e
 * dokunulmaz.
 */

const STEP = 0.01;
const BIG_STEP = 0.1;
const round4 = (v) => Math.round(v * 10000) / 10000;
const pct = (v) => Math.round(clampFocal(v) * 100);
const same = (a, b) => Math.abs(a.x - b.x) < 1e-6 && Math.abs(a.y - b.y) < 1e-6;

async function defaultDeps() {
  const m = await import("../lib/media/crop/cropIntentApi.js");
  return { getIntent: m.getCropIntent, suggest: m.suggestCropFocal, saveFocal: m.saveFocalOnly };
}

export function useFocalPoint({ asset = "", initialFocal = null, deps = null } = {}) {
  const focal = ref({ x: 0.5, y: 0.5 });
  const saved = ref({ x: 0.5, y: 0.5 });
  const etag = ref("");
  const loading = ref(false);
  const saving = ref(false);
  const conflict = ref(false);
  const failed = ref(false);
  const announce = shallowRef(null);
  const viewed = new Map();
  let origin = "manual";
  let suggestion = null;
  let api = deps;

  const percent = computed(() => ({ x: pct(focal.value.x), y: pct(focal.value.y) }));
  const dirty = computed(() => !same(focal.value, saved.value));

  async function getApi() {
    api ||= await defaultDeps();
    return api;
  }
  function say(key, params = {}) {
    announce.value = { key, params };
  }

  function setFocal(x, y) {
    focal.value = { x: clampFocal(x), y: clampFocal(y) };
    origin = "manual";
    say("imagePlacement.status.moved", { ...percent.value });
  }
  function setPercent(axis, value) {
    const n = Number(value);
    const v = value === "" || !Number.isFinite(n) ? 0.5 : n / 100;
    if (axis === "x") setFocal(v, focal.value.y);
    else setFocal(focal.value.x, v);
  }
  function nudge(dx, dy, big = false) {
    const s = big ? BIG_STEP : STEP;
    setFocal(round4(focal.value.x + dx * s), round4(focal.value.y + dy * s));
  }
  function center() {
    focal.value = { x: 0.5, y: 0.5 };
    origin = "manual";
    say("imagePlacement.status.centered");
  }
  function markViewed(place, device) {
    viewed.set(`${device}:${place}`, { place, device });
  }

  async function suggest() {
    if (!asset) return false;
    try {
      const s = fromServerSuggestion(await (await getApi()).suggest(asset));
      if (!s) return false;
      focal.value = { x: s.x, y: s.y };
      origin = "smartcrop";
      suggestion = s;
      say("imagePlacement.status.suggested");
      return true;
    } catch {
      // spec §7: öneri başarısız → odak ortada kalır, bildirim yok.
      return false;
    }
  }

  async function load() {
    loading.value = true;
    conflict.value = false;
    failed.value = false;
    try {
      if (initialFocal) focal.value = { x: clampFocal(initialFocal.x), y: clampFocal(initialFocal.y) };
      if (!asset) return;
      const body = await (await getApi()).getIntent(asset);
      etag.value = body?.etag || "";
      const fx = body?.intent?.focal_x;
      const fy = body?.intent?.focal_y;
      if (fx !== null && fx !== undefined && fy !== null && fy !== undefined) {
        focal.value = { x: clampFocal(fx), y: clampFocal(fy) };
        return;
      }
      if (initialFocal) return;
      saved.value = { ...focal.value };
      await suggest();
      return;
    } catch {
      // Okuma hatası: elimizdeki değerle devam; Kaydet yine denenebilir (ETag'siz).
    } finally {
      if (!(origin === "smartcrop" && suggestion)) saved.value = { ...focal.value };
      loading.value = false;
    }
  }

  async function save() {
    if (!asset) return { ok: false, reason: "no-asset" };
    saving.value = true;
    failed.value = false;
    conflict.value = false;
    try {
      const smart = origin === "smartcrop" && suggestion;
      const body = await (await getApi()).saveFocal({
        asset,
        focalX: round4(focal.value.x),
        focalY: round4(focal.value.y),
        ifMatch: etag.value,
        previewed: [...viewed.values()],
        method: smart ? "smartcrop" : "manual",
        algorithm: smart ? suggestion.algorithm || "" : "",
        algorithmVersion: smart ? suggestion.algorithmVersion || "" : "",
      });
      etag.value = body?.etag || "";
      saved.value = { ...focal.value };
      say("imagePlacement.status.saved");
      return { ok: true };
    } catch (err) {
      if (err?.status === 412) {
        conflict.value = true;
        say("imagePlacement.status.conflict");
        return { ok: false, reason: "conflict" };
      }
      failed.value = true;
      say("imagePlacement.status.saveFailed");
      return { ok: false, reason: "error" };
    } finally {
      saving.value = false;
    }
  }

  return {
    focal,
    percent,
    dirty,
    loading,
    saving,
    conflict,
    failed,
    announce,
    load,
    suggest,
    setFocal,
    setPercent,
    nudge,
    center,
    markViewed,
    save,
  };
}
```

Note on `load()`: an applied *suggestion* is an unsaved change (`saved` stays at the centre, `dirty` is true) — closing then asks for confirmation. A focal read from the server or from `initialFocal` is not dirty.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/ahmet/Desktop/istoc/admin-panel/frontend && node --test src/lib/media/crop/__tests__/focalGeometry.test.js src/composables/__tests__/focalPoint.test.js && node --test --test-reporter=tap "src/lib/media/crop/__tests__/*.test.js" "src/composables/__tests__/crop*.test.js" 2>&1 | grep -E "^# (pass|fail)" && npx eslint src/lib/media/crop/geometry.js src/lib/media/crop/cropIntentApi.js src/lib/media/preview/previewApi.js src/composables/useFocalPoint.js`
Expected: the two new files pass (6 + 9 tests). The wider crop suites show only the 3 baseline `alphaToJpeg` failures. ESLint: no output.

- [ ] **Step 5: Stage (no commit — user approves commits)**

```bash
cd /Users/ahmet/Desktop/istoc/admin-panel && git add frontend/src/lib/media/crop/geometry.js frontend/src/lib/media/crop/cropIntentApi.js frontend/src/lib/media/preview/previewApi.js frontend/src/composables/useFocalPoint.js frontend/src/lib/media/crop/__tests__/focalGeometry.test.js frontend/src/composables/__tests__/focalPoint.test.js
```

---
### Task 6: Place queries (`places.js`) and window strings (`messages.js`) (Wave 2 — after T1, T5)

**Files:**
- Create: `admin-panel/frontend/src/lib/media/preview/places.js`
- Create: `admin-panel/frontend/src/lib/media/preview/messages.js`
- Create: `admin-panel/frontend/src/lib/media/preview/__tests__/places.test.js`
- Create: `admin-panel/frontend/src/lib/media/preview/__tests__/messages.test.js`

**Interfaces:**
- Consumes: `PLACES`, `STAGE`, `FULLY_VISIBLE_MIN`, `SOURCE_SHA256` from `../vendor/placements.js` (Task 1); `visibleFraction` from `../crop/geometry.js` (Task 5).
- Produces:
  - `places.js`: `STAGE`, `FULLY_VISIBLE_MIN`, `DEVICES = ["desktop","mobile"]`, `placesFor(slotKey, device) -> Place[]`, `devicesFor(slotKey) -> string[]`, `placeVisibility(place, imageRatio) -> {x, y, fraction, pct, full, unknown}`, `cutPlaceCount(slotKey, imageRatio) -> number` (distinct place keys across devices that are cut), `placeCount(slotKey) -> number` (distinct keys), `boxStyle(place, scale) -> {width, maxWidth, aspectRatio}`, `formatPercent(value01, locale) -> string` (`Intl` percent: tr `"%41"`, en `"41%"`), `kindKey(slotKey) -> "coverImage"|"logo"|"productImage"`.
  - `messages.js`: `export default { tr, en, ru, ar }`, each `{ imagePlacement: {...} }`. Components use it as `useI18n({ messages })` (local scope). Percent values are passed **pre-formatted** with `formatPercent` because vue-i18n treats `%{x}` as Rails-style interpolation. Keys used by Tasks 7, 8, 10 are listed in the file below; `imagePlacement.badge` is plural in `en` only (`t(key, { n }, n)`).

- [ ] **Step 1: Write the failing tests**

Create `src/lib/media/preview/__tests__/places.test.js`:

```js
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { SOURCE_SHA256 } from "../../vendor/placements.js";
import {
  boxStyle,
  cutPlaceCount,
  devicesFor,
  formatPercent,
  placeCount,
  placesFor,
  placeVisibility,
} from "../places.js";

const BANNER = 2000 / 408;
const SOURCE = fileURLToPath(
  new URL(
    "../../../../../../../tradehub_core/tradehub_core/media/pipeline/simulator/placements.json",
    import.meta.url
  )
);

test("vendor kopyası kaynak placements.json ile aynı sürümde", { skip: !existsSync(SOURCE) }, () => {
  const sha = createHash("sha256").update(readFileSync(SOURCE)).digest("hex");
  assert.equal(SOURCE_SHA256, sha, "placements.json değişmiş: sizes.py --emit-placements admin koştur");
});

test("her slot için iki cihazda da en az bir yer", () => {
  for (const slot of ["company.cover_image", "seller.logo", "product.image"]) {
    assert.deepEqual(devicesFor(slot), ["desktop", "mobile"]);
    for (const d of ["desktop", "mobile"]) assert.ok(placesFor(slot, d).length >= 1, `${slot}/${d}`);
  }
});

test("Özgen banner'ı: telefonda mağaza başlığında %44 görünür, 4 yerde kesilir", () => {
  const hero = placesFor("company.cover_image", "mobile").find((p) => p.key === "store_hero");
  const v = placeVisibility(hero, BANNER);
  assert.equal(v.pct, 44);
  assert.equal(v.full, false);
  assert.equal(cutPlaceCount("company.cover_image", BANNER), 4);
  assert.equal(placeCount("company.cover_image"), 4);
});

test("kare ürün görseli hiçbir yerde kesilmez", () => {
  assert.equal(cutPlaceCount("product.image", 1), 0);
  for (const p of placesFor("product.image", "desktop")) assert.equal(placeVisibility(p, 1).full, true);
});

test("ölçü bilinmiyorsa yüzde uydurulmaz, kesik sayılmaz", () => {
  const hero = placesFor("company.cover_image", "desktop")[0];
  assert.deepEqual(placeVisibility(hero, 0), {
    x: 1,
    y: 1,
    fraction: 1,
    pct: 100,
    full: true,
    unknown: true,
  });
  assert.equal(cutPlaceCount("company.cover_image", 0), 0);
  assert.equal(cutPlaceCount("company.cover_image", Number.NaN), 0);
});

test("boxStyle ölçeklenmiş genişlik + oran; ölçüsüz yerde %100", () => {
  const hero = placesFor("company.cover_image", "desktop").find((p) => p.key === "store_hero");
  assert.deepEqual(boxStyle(hero, 0.65), { width: "780px", maxWidth: "100%", aspectRatio: "3" });
  const fav = placesFor("product.image", "mobile").find((p) => p.key === "favorites");
  assert.equal(boxStyle(fav, 1).width, "100%");
});

test("formatPercent dile göre", () => {
  assert.equal(formatPercent(0.41, "tr"), "%41");
  assert.equal(formatPercent(0.41, "en"), "41%");
});
```

Create `src/lib/media/preview/__tests__/messages.test.js`:

```js
import assert from "node:assert/strict";
import { test } from "node:test";

import messages from "../messages.js";
import { PLACES } from "../../vendor/placements.js";

function flatten(obj, prefix = "") {
  return Object.entries(obj).flatMap(([k, v]) =>
    v && typeof v === "object" ? flatten(v, `${prefix}${k}.`) : [[`${prefix}${k}`, v]]
  );
}
const get = (obj, path) => path.split(".").reduce((o, k) => (o ? o[k] : undefined), obj);

test("dört dil aynı anahtar kümesini taşır", () => {
  const keys = (l) => flatten(messages[l]).map(([k]) => k).sort();
  const tr = keys("tr");
  for (const l of ["en", "ru", "ar"]) assert.deepEqual(keys(l), tr, l);
});

test("her yer etiketi dört dilde çözülür", () => {
  const labelKeys = new Set(Object.values(PLACES).flat().map((p) => p.labelKey));
  for (const l of ["tr", "en", "ru", "ar"])
    for (const k of labelKeys) assert.equal(typeof get(messages[l], k), "string", `${l} ${k}`);
});

test("Rails biçimli %{…} yok (vue-i18n onu yer tutucu sayar)", () => {
  for (const l of ["tr", "en", "ru", "ar"])
    for (const [k, v] of flatten(messages[l])) assert.doesNotMatch(String(v), /%\{/, `${l} ${k}`);
});

test("Türkçe kopya tasarımla birebir", () => {
  const ip = messages.tr.imagePlacement;
  assert.equal(ip.title, "Görseliniz nerelerde görünecek?");
  assert.equal(ip.button, "Nerelerde görünecek?");
  assert.equal(ip.chip.full, "Tamamı görünüyor");
  assert.equal(ip.autoOpen, "Yeni görsel yüklediğimde otomatik açılsın");
  assert.equal(ip.badge, "{n} yerde kenarlar kesiliyor");
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/ahmet/Desktop/istoc/admin-panel/frontend && node --test src/lib/media/preview/__tests__/*.test.js 2>&1 | tail -4`
Expected: FAIL — `Cannot find module '…/preview/places.js'` / `'…/preview/messages.js'`.

- [ ] **Step 3: Implement `places.js`**

```js
import { FULLY_VISIBLE_MIN, PLACES, STAGE } from "../vendor/placements.js";
import { visibleFraction } from "../crop/geometry.js";

/**
 * Önizleme yer kaydına tek erişim noktası. Veri `../vendor/placements.js`
 * (ÜRETİLMİŞ, kaynak `placements.json → preview_places`); burada yalnız
 * sorgu ve görünürlük hesabı var. Göreli içe aktarım bilinçli: node:test
 * doğrudan yükleyebilsin.
 */
export { FULLY_VISIBLE_MIN, STAGE };
export const DEVICES = Object.freeze(["desktop", "mobile"]);

const KINDS = Object.freeze({
  "company.cover_image": "coverImage",
  "seller.logo": "logo",
  "product.image": "productImage",
});

export function kindKey(slotKey) {
  return KINDS[slotKey] || "coverImage";
}

export function placesFor(slotKey, device) {
  return (PLACES[slotKey] || []).filter((p) => p.device === device);
}

export function devicesFor(slotKey) {
  return DEVICES.filter((d) => placesFor(slotKey, d).length > 0);
}

export function placeCount(slotKey) {
  return new Set((PLACES[slotKey] || []).map((p) => p.key)).size;
}

/** Yerde görünen pay. Görsel oranı bilinmiyorsa `unknown: true` — yüzde uydurulmaz. */
export function placeVisibility(place, imageRatio) {
  if (!(imageRatio > 0)) return { x: 1, y: 1, fraction: 1, pct: 100, full: true, unknown: true };
  const v = visibleFraction(imageRatio, place.ratio, place.fit);
  const fraction = v.x * v.y;
  return {
    ...v,
    fraction,
    pct: Math.round(fraction * 100),
    full: fraction >= FULLY_VISIBLE_MIN,
    unknown: false,
  };
}

/** Rozet: kenarı kesilen FARKLI yer sayısı (aynı yer iki cihazda bir kez sayılır). */
export function cutPlaceCount(slotKey, imageRatio) {
  if (!(imageRatio > 0)) return 0;
  const cut = (PLACES[slotKey] || []).filter((p) => !placeVisibility(p, imageRatio).full);
  return new Set(cut.map((p) => p.key)).size;
}

/** Bağlam kutusu: ölçeklenmiş CSS genişliği + oran. Ölçülmemiş yer kabı doldurur. */
export function boxStyle(place, scale = 1) {
  return {
    width: place.cssW ? `${Math.round(place.cssW * scale)}px` : "100%",
    maxWidth: "100%",
    aspectRatio: String(place.ratio),
  };
}

export function formatPercent(value01, locale = "tr") {
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(
    Number(value01) || 0
  );
}
```

- [ ] **Step 4: Implement `messages.js`**

```js
/**
 * Görsel önizleme penceresi metinleri — dört dil (tr/en/ru/ar), yerel kapsam.
 *
 * Bileşenler `useI18n({ messages })` ile kullanır; dev `locales/*.js`
 * dosyalarına girmez (paralel işte çakışma olmasın, pencere kendi kopyasını
 * taşısın — CropStudioModal ile aynı desen). Yüzdeler `formatPercent` ile
 * BİÇİMLİ geçirilir: vue-i18n `%{x}`i Rails yer tutucusu sayar.
 */
const tr = {
  imagePlacement: {
    title: "Görseliniz nerelerde görünecek?",
    titleShort: "Nerelerde görünecek?",
    subtitle: "{kind} · {file} · {w} × {h} px",
    subtitleNoSize: "{kind} · {file}",
    kind: { coverImage: "Mağaza görseli", logo: "Mağaza logosu", productImage: "Ürün görseli" },
    close: "Pencereyi kapat",
    device: { group: "Cihaz", desktop: "Bilgisayar", mobile: "Telefon" },
    listLabel: "Görünen yerler",
    listTitle: { desktop: "BİLGİSAYARDA {n} YER", mobile: "TELEFONDA {n} YER" },
    chip: { full: "Tamamı görünüyor", partial: "{pct} görünüyor" },
    stageScale: { desktop: "Sayfa {page} px · burada {pct} ölçekte", mobile: "Telefon {page} px · gerçek boyut" },
    focal: {
      title: "Odak noktası",
      help: "Görselde en önemli yere tıklayın. Kesikli çerçeve, ortada seçili yerde görünen kısımdır.",
      helpMobile: "Görselde en önemli yere dokunun. Aşağıdaki önizlemeler hemen güncellenir.",
      x: "Yatay (%)",
      y: "Dikey (%)",
      xShort: "Yatay",
      yShort: "Dikey",
      decX: "Yatayı azalt",
      incX: "Yatayı artır",
      decY: "Dikeyi azalt",
      incY: "Dikeyi artır",
      suggest: "Otomatik öner",
      center: "Ortaya al",
      keyboard: "Klavye: işarete gelip ok tuşları %1, Shift + ok %10, Home ortaya alır.",
      handle: "Odak noktası, yatay {x}, dikey {y}. Ok tuşlarıyla taşıyın.",
      imageAlt: "Görselin tamamı",
    },
    status: {
      moved: "Odak noktası: yatay {x}, dikey {y}",
      suggested: "Otomatik öneri uygulandı.",
      centered: "Odak noktası ortaya alındı.",
      saved: "Odak noktası kaydedildi.",
      saveFailed: "Kaydedilemedi. Bağlantınızı kontrol edip tekrar deneyin.",
      conflict: "Bu görsel başka bir sekmede değiştirildi.",
      processing: "Görsel hazırlanıyor",
      cannotSave: "Görsel hazırlanıyor; odak noktası birkaç dakika sonra kaydedilebilir.",
      loading: "Yükleniyor…",
    },
    autoOpen: "Yeni görsel yüklediğimde otomatik açılsın",
    cancel: "Vazgeç",
    save: "Kaydet",
    done: "Tamam",
    reload: "Yeniden yükle",
    confirm: {
      title: "Kaydedilmemiş değişiklik var",
      body: "Kaydetmeden kapatırsanız odak noktası değişikliği kaybolur.",
      discard: "Kaydetmeden kapat",
      keep: "Düzenlemeye dön",
    },
    tabs: { label: "Görünüm", preview: "Önizleme", focal: "Odak noktası" },
    mobilePreviews: "TELEFONDA GÖRÜNÜM",
    square: {
      title: "Kareye tamamlandı",
      body: "Görseliniz büyütülmeden {size} × {size} beyaz zeminin ortasına yerleştirildi. Ürün görselleri her yerde kare ve tam olarak gösterilir.",
      format: "Biçim",
      file: "Dosya",
    },
    summary: {
      none: "Bu görsel {n} yerde görünecek ve hiçbir yerde kesilmiyor.",
      some: "Bu görsel {n} yerde görünecek; {cut} yerde kenarlar kesiliyor.",
    },
    why: {
      title: "Odak noktası neden önemli?",
      body: "Ürün görselleri kare gösterildiği için kesilmez. Odak noktası, görsel ileride kare olmayan bir alanda (kampanya şeridi gibi) kullanılırsa neresinin görüneceğini belirler.",
    },
    button: "Nerelerde görünecek?",
    badge: "{n} yerde kenarlar kesiliyor",
    place: {
      storeHero: "Mağaza sayfası başlığı",
      storeVitrin: "Mağaza vitrini",
      storeGallery: "Galeri kutusu",
      storeCard: "Mağaza tanıtım kartı",
      shopLogo: "Mağaza başlığı logosu",
      productCard: "Ürün kartı",
      productMain: "Ürün sayfası · ana görsel",
      productThumb: "Ürün sayfası · küçük resim",
      cart: "Sepet ve sipariş",
      related: "Benzer ürünler",
      favorites: "Favoriler",
    },
    context: { storeFallback: "Mağazanız", productFallback: "Ürününüz", qty: "{n} adet" },
    alt: "{place} önizlemesi",
  },
};

const en = {
  imagePlacement: {
    title: "Where will your image appear?",
    titleShort: "Where will it appear?",
    subtitle: "{kind} · {file} · {w} × {h} px",
    subtitleNoSize: "{kind} · {file}",
    kind: { coverImage: "Store image", logo: "Store logo", productImage: "Product image" },
    close: "Close window",
    device: { group: "Device", desktop: "Desktop", mobile: "Phone" },
    listLabel: "Places shown",
    listTitle: { desktop: "{n} PLACES ON DESKTOP", mobile: "{n} PLACES ON PHONE" },
    chip: { full: "Fully visible", partial: "{pct} visible" },
    stageScale: { desktop: "Page {page} px · shown at {pct}", mobile: "Phone {page} px · actual size" },
    focal: {
      title: "Focal point",
      help: "Click the most important part of the image. The dashed frame is what the selected place shows.",
      helpMobile: "Tap the most important part of the image. The previews below update instantly.",
      x: "Horizontal (%)",
      y: "Vertical (%)",
      xShort: "Horizontal",
      yShort: "Vertical",
      decX: "Decrease horizontal",
      incX: "Increase horizontal",
      decY: "Decrease vertical",
      incY: "Increase vertical",
      suggest: "Suggest automatically",
      center: "Center",
      keyboard: "Keyboard: focus the marker, arrow keys move 1%, Shift + arrow 10%, Home centers.",
      handle: "Focal point, horizontal {x}, vertical {y}. Move with the arrow keys.",
      imageAlt: "The whole image",
    },
    status: {
      moved: "Focal point: horizontal {x}, vertical {y}",
      suggested: "Automatic suggestion applied.",
      centered: "Focal point centered.",
      saved: "Focal point saved.",
      saveFailed: "Could not save. Check your connection and try again.",
      conflict: "This image was changed in another tab.",
      processing: "Image is being prepared",
      cannotSave: "Image is being prepared; the focal point can be saved in a few minutes.",
      loading: "Loading…",
    },
    autoOpen: "Open automatically when I upload a new image",
    cancel: "Cancel",
    save: "Save",
    done: "Done",
    reload: "Reload",
    confirm: {
      title: "You have unsaved changes",
      body: "If you close without saving, the focal point change will be lost.",
      discard: "Close without saving",
      keep: "Keep editing",
    },
    tabs: { label: "View", preview: "Preview", focal: "Focal point" },
    mobilePreviews: "ON PHONE",
    square: {
      title: "Completed to a square",
      body: "Your image was placed, without enlarging, in the middle of a {size} × {size} white background. Product images are shown square and whole everywhere.",
      format: "Format",
      file: "File",
    },
    summary: {
      none: "This image appears in {n} places and is not cut anywhere.",
      some: "This image appears in {n} places; edges are cut in {cut}.",
    },
    why: {
      title: "Why does the focal point matter?",
      body: "Product images are shown square, so they are not cut. The focal point decides which part shows if the image is later used in a non-square area (such as a campaign strip).",
    },
    button: "Where will it appear?",
    badge: "Edges cut in {n} place | Edges cut in {n} places",
    place: {
      storeHero: "Store page header",
      storeVitrin: "Store showcase",
      storeGallery: "Gallery box",
      storeCard: "Store intro card",
      shopLogo: "Store header logo",
      productCard: "Product card",
      productMain: "Product page · main image",
      productThumb: "Product page · thumbnail",
      cart: "Cart and order",
      related: "Similar products",
      favorites: "Favorites",
    },
    context: { storeFallback: "Your store", productFallback: "Your product", qty: "{n} pcs" },
    alt: "{place} preview",
  },
};

const ru = {
  imagePlacement: {
    title: "Где будет показано ваше изображение?",
    titleShort: "Где будет показано?",
    subtitle: "{kind} · {file} · {w} × {h} px",
    subtitleNoSize: "{kind} · {file}",
    kind: { coverImage: "Изображение магазина", logo: "Логотип магазина", productImage: "Изображение товара" },
    close: "Закрыть окно",
    device: { group: "Устройство", desktop: "Компьютер", mobile: "Телефон" },
    listLabel: "Места показа",
    listTitle: { desktop: "НА КОМПЬЮТЕРЕ: {n}", mobile: "НА ТЕЛЕФОНЕ: {n}" },
    chip: { full: "Видно полностью", partial: "Видно {pct}" },
    stageScale: { desktop: "Страница {page} px · здесь {pct}", mobile: "Телефон {page} px · реальный размер" },
    focal: {
      title: "Точка фокуса",
      help: "Нажмите на самую важную часть изображения. Пунктирная рамка — то, что видно в выбранном месте.",
      helpMobile: "Коснитесь самой важной части изображения. Превью ниже обновятся сразу.",
      x: "По горизонтали (%)",
      y: "По вертикали (%)",
      xShort: "По горизонтали",
      yShort: "По вертикали",
      decX: "Уменьшить по горизонтали",
      incX: "Увеличить по горизонтали",
      decY: "Уменьшить по вертикали",
      incY: "Увеличить по вертикали",
      suggest: "Предложить автоматически",
      center: "По центру",
      keyboard: "Клавиатура: выберите маркер, стрелки — 1%, Shift + стрелка — 10%, Home — центр.",
      handle: "Точка фокуса: по горизонтали {x}, по вертикали {y}. Перемещайте стрелками.",
      imageAlt: "Изображение целиком",
    },
    status: {
      moved: "Точка фокуса: по горизонтали {x}, по вертикали {y}",
      suggested: "Автоматическое предложение применено.",
      centered: "Точка фокуса по центру.",
      saved: "Точка фокуса сохранена.",
      saveFailed: "Не удалось сохранить. Проверьте соединение и повторите.",
      conflict: "Это изображение изменили в другой вкладке.",
      processing: "Изображение готовится",
      cannotSave: "Изображение готовится; точку фокуса можно будет сохранить через несколько минут.",
      loading: "Загрузка…",
    },
    autoOpen: "Открывать автоматически при загрузке нового изображения",
    cancel: "Отмена",
    save: "Сохранить",
    done: "Готово",
    reload: "Обновить",
    confirm: {
      title: "Есть несохранённые изменения",
      body: "Если закрыть без сохранения, изменение точки фокуса пропадёт.",
      discard: "Закрыть без сохранения",
      keep: "Продолжить редактирование",
    },
    tabs: { label: "Вид", preview: "Превью", focal: "Точка фокуса" },
    mobilePreviews: "НА ТЕЛЕФОНЕ",
    square: {
      title: "Дополнено до квадрата",
      body: "Изображение без увеличения размещено в центре белого фона {size} × {size}. Изображения товаров везде показываются квадратными и целиком.",
      format: "Формат",
      file: "Файл",
    },
    summary: {
      none: "Изображение показывается в местах: {n}, и нигде не обрезается.",
      some: "Изображение показывается в местах: {n}; края обрезаются в местах: {cut}.",
    },
    why: {
      title: "Зачем нужна точка фокуса?",
      body: "Изображения товаров показываются квадратными, поэтому не обрезаются. Точка фокуса определяет, какая часть будет видна, если изображение позже используют в неквадратной области (например, в полосе акции).",
    },
    button: "Где будет показано?",
    badge: "Края обрезаются в местах: {n}",
    place: {
      storeHero: "Шапка страницы магазина",
      storeVitrin: "Витрина магазина",
      storeGallery: "Ячейка галереи",
      storeCard: "Карточка магазина",
      shopLogo: "Логотип в шапке магазина",
      productCard: "Карточка товара",
      productMain: "Страница товара · главное фото",
      productThumb: "Страница товара · миниатюра",
      cart: "Корзина и заказ",
      related: "Похожие товары",
      favorites: "Избранное",
    },
    context: { storeFallback: "Ваш магазин", productFallback: "Ваш товар", qty: "{n} шт." },
    alt: "Превью: {place}",
  },
};

const ar = {
  imagePlacement: {
    title: "أين ستظهر صورتك؟",
    titleShort: "أين ستظهر؟",
    subtitle: "{kind} · {file} · {w} × {h} بكسل",
    subtitleNoSize: "{kind} · {file}",
    kind: { coverImage: "صورة المتجر", logo: "شعار المتجر", productImage: "صورة المنتج" },
    close: "إغلاق النافذة",
    device: { group: "الجهاز", desktop: "الحاسوب", mobile: "الهاتف" },
    listLabel: "أماكن الظهور",
    listTitle: { desktop: "الأماكن على الحاسوب: {n}", mobile: "الأماكن على الهاتف: {n}" },
    chip: { full: "ظاهرة بالكامل", partial: "الظاهر {pct}" },
    stageScale: { desktop: "الصفحة {page} بكسل · هنا بمقياس {pct}", mobile: "الهاتف {page} بكسل · الحجم الفعلي" },
    focal: {
      title: "نقطة التركيز",
      help: "انقر على أهم جزء في الصورة. الإطار المتقطع هو ما يظهر في المكان المحدد.",
      helpMobile: "المس أهم جزء في الصورة. تتحدّث المعاينات أدناه فورًا.",
      x: "أفقي (%)",
      y: "عمودي (%)",
      xShort: "أفقي",
      yShort: "عمودي",
      decX: "تقليل الأفقي",
      incX: "زيادة الأفقي",
      decY: "تقليل العمودي",
      incY: "زيادة العمودي",
      suggest: "اقتراح تلقائي",
      center: "توسيط",
      keyboard: "لوحة المفاتيح: انتقل إلى المؤشر، الأسهم 1%، Shift + سهم 10%، Home للتوسيط.",
      handle: "نقطة التركيز، أفقي {x}، عمودي {y}. حرّكها بمفاتيح الأسهم.",
      imageAlt: "الصورة كاملة",
    },
    status: {
      moved: "نقطة التركيز: أفقي {x}، عمودي {y}",
      suggested: "تم تطبيق الاقتراح التلقائي.",
      centered: "تم توسيط نقطة التركيز.",
      saved: "تم حفظ نقطة التركيز.",
      saveFailed: "تعذّر الحفظ. تحقّق من الاتصال وحاول مجددًا.",
      conflict: "تم تغيير هذه الصورة في علامة تبويب أخرى.",
      processing: "يجري تجهيز الصورة",
      cannotSave: "يجري تجهيز الصورة؛ يمكن حفظ نقطة التركيز بعد بضع دقائق.",
      loading: "جارٍ التحميل…",
    },
    autoOpen: "افتح تلقائيًا عند رفع صورة جديدة",
    cancel: "إلغاء",
    save: "حفظ",
    done: "تم",
    reload: "إعادة التحميل",
    confirm: {
      title: "لديك تغييرات غير محفوظة",
      body: "إذا أغلقت دون حفظ فسيضيع تغيير نقطة التركيز.",
      discard: "إغلاق دون حفظ",
      keep: "متابعة التعديل",
    },
    tabs: { label: "العرض", preview: "معاينة", focal: "نقطة التركيز" },
    mobilePreviews: "على الهاتف",
    square: {
      title: "أُكملت إلى مربع",
      body: "وُضعت صورتك دون تكبير في وسط خلفية بيضاء {size} × {size}. تُعرض صور المنتجات مربعة وكاملة في كل مكان.",
      format: "الصيغة",
      file: "الملف",
    },
    summary: {
      none: "تظهر هذه الصورة في عدد من الأماكن: {n}، ولا تُقص في أي مكان.",
      some: "تظهر هذه الصورة في عدد من الأماكن: {n}؛ تُقص الحواف في: {cut}.",
    },
    why: {
      title: "لماذا تهم نقطة التركيز؟",
      body: "تُعرض صور المنتجات مربعة لذلك لا تُقص. تحدد نقطة التركيز الجزء الظاهر إذا استُخدمت الصورة لاحقًا في مساحة غير مربعة (مثل شريط حملة).",
    },
    button: "أين ستظهر؟",
    badge: "تُقص الحواف في عدد من الأماكن: {n}",
    place: {
      storeHero: "رأس صفحة المتجر",
      storeVitrin: "واجهة المتجر",
      storeGallery: "مربع المعرض",
      storeCard: "بطاقة تعريف المتجر",
      shopLogo: "شعار رأس المتجر",
      productCard: "بطاقة المنتج",
      productMain: "صفحة المنتج · الصورة الرئيسية",
      productThumb: "صفحة المنتج · صورة مصغرة",
      cart: "السلة والطلب",
      related: "منتجات مشابهة",
      favorites: "المفضلة",
    },
    context: { storeFallback: "متجرك", productFallback: "منتجك", qty: "{n} قطعة" },
    alt: "معاينة {place}",
  },
};

export default { tr, en, ru, ar };
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/ahmet/Desktop/istoc/admin-panel/frontend && node --test src/lib/media/preview/__tests__/*.test.js && npx eslint src/lib/media/preview/places.js src/lib/media/preview/messages.js && npx prettier --check src/lib/media/preview/places.js src/lib/media/preview/messages.js`
Expected: 11 tests pass (7 + 4); ESLint and Prettier clean (run `npx prettier --write` on the two files if Prettier reflows long strings, then re-run the tests).

- [ ] **Step 6: Stage (no commit — user approves commits)**

```bash
cd /Users/ahmet/Desktop/istoc/admin-panel && git add frontend/src/lib/media/preview/places.js frontend/src/lib/media/preview/messages.js frontend/src/lib/media/preview/__tests__/places.test.js frontend/src/lib/media/preview/__tests__/messages.test.js
```

---
### Task 7: Page-context skeletons (Wave 3 — after T6)

**Files (all new, under `admin-panel/frontend/src/components/media/preview/contexts/`):**
- `contextProps.js`, `contexts.css`, `ContextImage.vue`, `index.js`
- `StoreHeaderContext.vue`, `StoreVitrinContext.vue`, `GalleryContext.vue`, `StoreCardContext.vue`
- `ProductCardContext.vue`, `ProductPageContext.vue`, `CartContext.vue`, `RelatedContext.vue`, `FavoritesContext.vue`
- Test: `admin-panel/frontend/src/components/media/preview/__tests__/contexts.test.js`

**Interfaces:**
- Consumes: `boxStyle(place, scale)` (Task 6), `objectPosition(focal)` (Task 5), `messages` (Task 6), `PLACES` (Task 1).
- Produces: `contexts/index.js` → `export const CONTEXTS = Object.freeze({ StoreHeaderContext, … })` keyed by the registry `context` names. Every context takes the same props (`CONTEXT_PROPS`): `src: String` (required), `focal: {x, y}` (required), `place: Place` (required), `device: "desktop"|"mobile"`, `scale: Number` (desktop 0.65, phone 1), `data: {storeName?, productName?, price?}`. Each renders exactly one `<img class="ctx-img">` per highlighted place carrying `object-fit: place.fit` and (for `cover`) `object-position: objectPosition(focal)`; everything else is a grey skeleton. Real data shown: store name, product name, price (spec §4.2).

- [ ] **Step 1: Write the failing test**

Create `src/components/media/preview/__tests__/contexts.test.js`:

```js
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { after, before, test } from "node:test";
import vue from "@vitejs/plugin-vue";
import { createServer } from "vite";
import { createSSRApp, h } from "vue";
import { createI18n } from "vue-i18n";
import { renderToString } from "@vue/server-renderer";

import messages from "../../../../lib/media/preview/messages.js";
import { PLACES } from "../../../../lib/media/vendor/placements.js";
import { describe as describeAxe, scanHtml } from "../../a11y/axeHarness.js";

const frontendRoot = fileURLToPath(new URL("../../../../..", import.meta.url));
let server;
let CONTEXTS;

before(async () => {
  server = await createServer({
    configFile: false,
    root: frontendRoot,
    logLevel: "silent",
    plugins: [vue()],
    resolve: { alias: { "@": `${frontendRoot}/src` } },
    server: { middlewareMode: true },
    appType: "custom",
  });
  ({ CONTEXTS } = await server.ssrLoadModule("/src/components/media/preview/contexts/index.js"));
});
after(async () => server?.close());

async function render(component, props) {
  const app = createSSRApp({ render: () => h(component, props) });
  app.use(createI18n({ legacy: false, locale: "tr", fallbackLocale: "tr", messages }));
  return renderToString(app);
}

const DATA = { storeName: "Özgen Plastik", productName: "17'lik Oto Yıkama Fırçası", price: "₺60,40" };
const FOCAL = { x: 0.78, y: 0.45 };
const ALL = Object.values(PLACES).flat();

test("kayıttaki her bağlam adının bir bileşeni var", () => {
  for (const p of ALL) assert.ok(CONTEXTS[p.context], p.context);
});

test("her yer gerçek oranında ve odakla çizilir", async () => {
  for (const place of ALL) {
    const html = await render(CONTEXTS[place.context], {
      src: "/files/ozgen.webp",
      focal: FOCAL,
      place,
      device: place.device,
      scale: place.device === "desktop" ? 0.65 : 1,
      data: DATA,
    });
    const label = `${place.device}/${place.key}`;
    assert.match(html, /src="\/files\/ozgen\.webp"/, label);
    assert.match(html, new RegExp(`object-fit:\\s*${place.fit}`), label);
    if (place.fit === "cover") assert.match(html, /object-position:\s*78% 45%/, label);
    assert.match(html, /önizlemesi"/, `${label}: alt metin`);
    const veri = place.key.startsWith("store") || place.key === "shop_logo" ? DATA.storeName : DATA.productName;
    assert.ok(html.includes(veri.replace("'", "&#39;")) || html.includes(veri), `${label}: gerçek veri`);
  }
});

test("bağlamlar axe ile 0 ihlal", async () => {
  for (const place of ALL) {
    const html = await render(CONTEXTS[place.context], {
      src: "/files/ozgen.webp",
      focal: FOCAL,
      place,
      device: place.device,
      scale: 1,
      data: DATA,
    });
    const { violations } = await scanHtml(html);
    assert.equal(violations.length, 0, `${place.device}/${place.key}\n${describeAxe(violations)}`);
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/ahmet/Desktop/istoc/admin-panel/frontend && node --test src/components/media/preview/__tests__/contexts.test.js 2>&1 | tail -5`
Expected: FAIL — `Failed to load url /src/components/media/preview/contexts/index.js`.

- [ ] **Step 3: Implement the shared pieces**

`contexts/contextProps.js`:

```js
/** Bütün bağlam şablonlarının ORTAK prop sözleşmesi (ImagePlacementModal bunları geçirir). */
export const CONTEXT_PROPS = {
  src: { type: String, required: true },
  focal: { type: Object, required: true },
  place: { type: Object, required: true },
  device: { type: String, default: "desktop" },
  scale: { type: Number, default: 1 },
  data: { type: Object, default: () => ({}) },
};
```

`contexts/contexts.css`:

```css
/* Önizleme bağlam iskeletleri — yalnız ImagePlacementModal sahnesinde kullanılır.
   Renkler pencerenin AAA paletinden (spec §5); #6d6a61 bilinçli olarak yok. */
.ctx { display: flex; flex-direction: column; gap: 12px; padding: 18px; color: #1d1c19; background: #fff; }
.ctx--mobile { padding: 14px; }
.ctx--flush, .ctx--flush.ctx--mobile { padding: 0; }
.ctx-band { border-radius: 0; }
.ctx-pad { display: flex; flex-direction: column; gap: 12px; padding: 0 18px 18px; }
.ctx--mobile .ctx-pad { padding: 0 14px 14px; }
.ctx-box { display: block; overflow: hidden; border-radius: 8px; background: #f4f3f0; flex-shrink: 0; }
.ctx-skel { display: block; border-radius: 8px; background: #f4f3f0; }
.ctx-row { display: flex; align-items: center; gap: 12px; }
.ctx-col { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.ctx-name { font-size: 15px; font-weight: 700; line-height: 1.3; }
.ctx-meta { font-size: 12px; color: #3a3833; }
.ctx-price { font-size: 15px; font-weight: 700; }
.ctx-line { display: block; height: 12px; border-radius: 6px; background: #f4f3f0; }
.ctx-grid { display: grid; gap: 10px; }
.ctx-grid--2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.ctx-grid--3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.ctx-grid--4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.ctx-tile { aspect-ratio: 1; }
.ctx-card { display: flex; flex-direction: column; gap: 8px; padding: 8px; border: 1px solid #e6e3dc; border-radius: 10px; background: #fff; min-width: 0; }
.ctx-strip { display: flex; gap: 10px; overflow: hidden; }
.ctx-dots { display: flex; gap: 6px; justify-content: center; }
.ctx-dot { width: 6px; height: 6px; border-radius: 999px; background: #a8a398; }
.ctx-dot--on { width: 18px; background: #1a1a1a; }
.ctx-img { width: 100%; height: 100%; display: block; transition: object-position 260ms cubic-bezier(0.2, 0.8, 0.2, 1); }
@media (prefers-reduced-motion: reduce) { .ctx-img { transition: none; } }
```

`contexts/ContextImage.vue`:

```vue
<script setup>
  import { computed } from "vue";

  import { objectPosition } from "@/lib/media/crop/geometry.js";

  const props = defineProps({
    src: { type: String, required: true },
    focal: { type: Object, required: true },
    fit: { type: String, default: "cover" },
    alt: { type: String, default: "" },
  });
  /* `contain` kesmez; `object-position` orada anlamsız olduğu için ortada tutulur. */
  const style = computed(() => ({
    objectFit: props.fit,
    objectPosition: props.fit === "cover" ? objectPosition(props.focal) : "50% 50%",
  }));
</script>

<template>
  <img class="ctx-img" :src="src" :alt="alt" :style="style" decoding="async" />
</template>
```

`contexts/index.js`:

```js
import "./contexts.css";

import CartContext from "./CartContext.vue";
import FavoritesContext from "./FavoritesContext.vue";
import GalleryContext from "./GalleryContext.vue";
import ProductCardContext from "./ProductCardContext.vue";
import ProductPageContext from "./ProductPageContext.vue";
import RelatedContext from "./RelatedContext.vue";
import StoreCardContext from "./StoreCardContext.vue";
import StoreHeaderContext from "./StoreHeaderContext.vue";
import StoreVitrinContext from "./StoreVitrinContext.vue";

/** `placements.json → preview_places[].context` adı → bileşen. */
export const CONTEXTS = Object.freeze({
  StoreHeaderContext,
  StoreVitrinContext,
  GalleryContext,
  StoreCardContext,
  ProductCardContext,
  ProductPageContext,
  CartContext,
  RelatedContext,
  FavoritesContext,
});
```

- [ ] **Step 4: Implement the nine contexts**

Every context starts with the same `<script setup>` header (repeated in each file — do not factor it into a composable, the files must stay independent):

```js
  import { computed } from "vue";
  import { useI18n } from "vue-i18n";

  import { boxStyle } from "@/lib/media/preview/places.js";
  import messages from "@/lib/media/preview/messages.js";
  import ContextImage from "./ContextImage.vue";
  import { CONTEXT_PROPS } from "./contextProps.js";

  const props = defineProps(CONTEXT_PROPS);
  const { t } = useI18n({ messages });
  const alt = computed(() => t("imagePlacement.alt", { place: t(props.place.labelKey) }));
  const box = computed(() => boxStyle(props.place, props.scale));
```

Store contexts add `const storeName = computed(() => props.data.storeName || t("imagePlacement.context.storeFallback"));`; product contexts add `const productName = computed(() => props.data.productName || t("imagePlacement.context.productFallback"));` and `const price = computed(() => props.data.price || "");`.

`StoreHeaderContext.vue` (places `store_hero`, `shop_logo`) — script adds `const isLogo = computed(() => props.place.key === "shop_logo");` and `const tiles = computed(() => (props.device === "mobile" ? 2 : 4));`:

```vue
<template>
  <!-- Vitrin bandı storefront'ta TAM GENİŞLİK (section-registry.ts:108): kenar boşluğu yok,
       telefonda 390 × 180 px birebir — e2e ekran görüntüsü karşılaştırması buna dayanır. -->
  <div class="ctx ctx--flush" :class="`ctx--${device}`">
    <span
      v-if="isLogo"
      class="ctx-skel ctx-band"
      :style="{ aspectRatio: device === 'mobile' ? '390 / 180' : '3 / 1' }"
    />
    <span v-else class="ctx-box ctx-band" :style="{ aspectRatio: String(place.ratio) }">
      <ContextImage :src="src" :focal="focal" :fit="place.fit" :alt="alt" />
    </span>
    <div class="ctx-pad">
      <div class="ctx-row">
        <span v-if="isLogo" class="ctx-box" :style="box">
          <ContextImage :src="src" :focal="focal" :fit="place.fit" :alt="alt" />
        </span>
        <span v-else class="ctx-skel" style="width: 44px; height: 44px" />
        <strong class="ctx-name">{{ storeName }}</strong>
      </div>
      <div class="ctx-grid" :class="`ctx-grid--${tiles}`">
        <span v-for="n in tiles" :key="n" class="ctx-skel ctx-tile" />
      </div>
    </div>
  </div>
</template>
```

`StoreVitrinContext.vue` (`store_vitrin`):

```vue
<template>
  <div class="ctx" :class="`ctx--${device}`">
    <strong class="ctx-name">{{ storeName }}</strong>
    <span class="ctx-box" :style="box">
      <ContextImage :src="src" :focal="focal" :fit="place.fit" :alt="alt" />
    </span>
    <div class="ctx-dots" aria-hidden="true">
      <span class="ctx-dot ctx-dot--on" /><span class="ctx-dot" /><span class="ctx-dot" />
    </div>
  </div>
</template>
```

`GalleryContext.vue` (`store_gallery`) — script adds `const others = computed(() => (props.device === "mobile" ? 2 : 3));`:

```vue
<template>
  <div class="ctx" :class="`ctx--${device}`">
    <strong class="ctx-name">{{ storeName }}</strong>
    <div class="ctx-row" style="flex-wrap: wrap">
      <span class="ctx-box" :style="box">
        <ContextImage :src="src" :focal="focal" :fit="place.fit" :alt="alt" />
      </span>
      <span v-for="n in others" :key="n" class="ctx-skel" :style="box" />
    </div>
  </div>
</template>
```

`StoreCardContext.vue` (`store_card`):

```vue
<template>
  <div class="ctx" :class="`ctx--${device}`">
    <div class="ctx-card ctx-row" style="align-items: stretch">
      <div class="ctx-col" style="flex: 1">
        <strong class="ctx-name">{{ storeName }}</strong>
        <span class="ctx-line" style="width: 60%" />
        <div class="ctx-grid ctx-grid--3">
          <span v-for="n in 3" :key="n" class="ctx-skel ctx-tile" />
        </div>
      </div>
      <span class="ctx-box" :style="box">
        <ContextImage :src="src" :focal="focal" :fit="place.fit" :alt="alt" />
      </span>
    </div>
  </div>
</template>
```

`ProductCardContext.vue` (`product_card`) — script adds `const others = computed(() => (props.device === "mobile" ? 1 : 2));`:

```vue
<template>
  <div class="ctx" :class="`ctx--${device}`">
    <div class="ctx-row" style="align-items: flex-start">
      <div class="ctx-card" :style="{ width: box.width, maxWidth: box.maxWidth }">
        <span class="ctx-box" :style="{ aspectRatio: box.aspectRatio }">
          <ContextImage :src="src" :focal="focal" :fit="place.fit" :alt="alt" />
        </span>
        <span class="ctx-meta">{{ productName }}</span>
        <span v-if="price" class="ctx-price">{{ price }}</span>
      </div>
      <div v-for="n in others" :key="n" class="ctx-card" :style="{ width: box.width, maxWidth: box.maxWidth }">
        <span class="ctx-skel ctx-tile" />
        <span class="ctx-line" />
      </div>
    </div>
  </div>
</template>
```

`ProductPageContext.vue` (`product_main`, `product_thumb`) — script adds:

```js
  import { placesFor } from "@/lib/media/preview/places.js";
  const main = computed(
    () => placesFor("product.image", props.device).find((p) => p.key === "product_main") || props.place
  );
  const thumb = computed(
    () => placesFor("product.image", props.device).find((p) => p.key === "product_thumb") || props.place
  );
  const mainBox = computed(() => boxStyle(main.value, props.scale));
  const thumbBox = computed(() => boxStyle(thumb.value, props.scale));
```

```vue
<template>
  <div class="ctx" :class="`ctx--${device}`">
    <div class="ctx-row" style="align-items: flex-start; flex-wrap: wrap">
      <div class="ctx-col">
        <span class="ctx-box" :style="mainBox">
          <ContextImage :src="src" :focal="focal" :fit="main.fit" :alt="place.key === 'product_main' ? alt : ''" />
        </span>
        <div class="ctx-row">
          <span class="ctx-box" :style="thumbBox">
            <ContextImage :src="src" :focal="focal" :fit="thumb.fit" :alt="place.key === 'product_thumb' ? alt : ''" />
          </span>
          <span v-for="n in 3" :key="n" class="ctx-skel" :style="thumbBox" />
        </div>
      </div>
      <div class="ctx-col" style="flex: 1; min-width: 140px">
        <strong class="ctx-name">{{ productName }}</strong>
        <span v-if="price" class="ctx-price">{{ price }}</span>
        <span class="ctx-line" /><span class="ctx-line" style="width: 70%" />
      </div>
    </div>
  </div>
</template>
```

(The non-highlighted image gets `alt=""` — decorative duplicate — so screen readers hear the place once.)

`CartContext.vue` (`cart`):

```vue
<template>
  <div class="ctx" :class="`ctx--${device}`">
    <div class="ctx-card ctx-row">
      <span class="ctx-box" :style="box">
        <ContextImage :src="src" :focal="focal" :fit="place.fit" :alt="alt" />
      </span>
      <div class="ctx-col">
        <span class="ctx-meta">{{ productName }}</span>
        <span class="ctx-price">{{ t("imagePlacement.context.qty", { n: 20 }) }}<template v-if="price"> · {{ price }}</template></span>
      </div>
    </div>
    <span class="ctx-skel" style="height: 56px" />
  </div>
</template>
```

`RelatedContext.vue` (`related`):

```vue
<template>
  <div class="ctx" :class="`ctx--${device}`">
    <span class="ctx-line" style="width: 40%" />
    <div class="ctx-strip">
      <div class="ctx-card" :style="{ width: box.width, flexShrink: 0 }">
        <span class="ctx-box" :style="{ aspectRatio: box.aspectRatio }">
          <ContextImage :src="src" :focal="focal" :fit="place.fit" :alt="alt" />
        </span>
        <span class="ctx-meta">{{ productName }}</span>
      </div>
      <div v-for="n in 2" :key="n" class="ctx-card" :style="{ width: box.width, flexShrink: 0 }">
        <span class="ctx-skel ctx-tile" />
        <span class="ctx-line" />
      </div>
    </div>
  </div>
</template>
```

`FavoritesContext.vue` (`favorites`; `cssW` is null until Task 13 measures it, so the grid sets the width) — script adds `const cols = computed(() => (props.device === "mobile" ? 2 : 4));`:

```vue
<template>
  <div class="ctx" :class="`ctx--${device}`">
    <div class="ctx-grid" :class="`ctx-grid--${cols}`">
      <div class="ctx-card">
        <span class="ctx-box" :style="{ aspectRatio: String(place.ratio) }">
          <ContextImage :src="src" :focal="focal" :fit="place.fit" :alt="alt" />
        </span>
        <span class="ctx-meta">{{ productName }}</span>
        <span v-if="price" class="ctx-price">{{ price }}</span>
      </div>
      <div v-for="n in cols - 1" :key="n" class="ctx-card">
        <span class="ctx-skel ctx-tile" />
        <span class="ctx-line" />
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/ahmet/Desktop/istoc/admin-panel/frontend && node --test src/components/media/preview/__tests__/contexts.test.js && npx eslint "src/components/media/preview/contexts/**/*.{js,vue}" && npx prettier --check "src/components/media/preview/contexts/**/*.{js,vue,css}"`
Expected: 3 tests pass (axe: `violations.length === 0` for all 22 place renders). ESLint/Prettier clean (apply `npx prettier --write` and re-run if needed).

- [ ] **Step 6: Stage (no commit — user approves commits)**

```bash
cd /Users/ahmet/Desktop/istoc/admin-panel && git add frontend/src/components/media/preview/contexts frontend/src/components/media/preview/__tests__/contexts.test.js
```

---
### Task 8: The window — `ImagePlacementModal`, `PlaceList`, `FocalEditor` (Wave 3 — after T5, T6)

**Files:**
- Create: `admin-panel/frontend/src/components/media/preview/FocalEditor.vue`
- Create: `admin-panel/frontend/src/components/media/preview/PlaceList.vue`
- Create: `admin-panel/frontend/src/components/media/preview/ImagePlacementModal.vue`
- Create: `admin-panel/frontend/src/components/media/preview/__tests__/mountSfc.js`
- Create: `admin-panel/frontend/src/components/media/preview/__tests__/fixtures/noopScrollLock.js`
- Create: `admin-panel/frontend/src/components/media/preview/__tests__/focalEditor.test.js`
- Create: `admin-panel/frontend/src/components/media/preview/__tests__/placeList.test.js`
- Create: `admin-panel/frontend/src/components/media/preview/__tests__/imagePlacementModal.test.js`
- Create: `admin-panel/frontend/src/components/media/preview/__tests__/previewAxe.test.js`

**Interfaces:**
- Consumes: `useFocalPoint` (T5), `getPreviewTarget/getPreviewPrefs/setPreviewPrefs` (T5), `frameRect`, `objectPosition` (T5), `placesFor/devicesFor/placeVisibility/placeCount/cutPlaceCount/formatPercent/kindKey/STAGE` (T6), `messages` (T6), `CONTEXTS` from `./contexts/index.js` (T7 — tests stub it), `useScrollLock` (existing).
- Produces:
  - `<ImagePlacementModal v-model:open :file-url :slot-key :file-name? :context? :return-focus? @close @saved>` — `context = {storeName?, productName?, price?}`; `returnFocus` = the element focus returns to, or a function returning it (the launcher passes the trigger button, or a lookup for auto-open where the button renders after the upload). Emits `saved({x, y})` after a successful save, then closes.
  - `<FocalEditor :src :image-ratio :focal :frame? :compact? :image-alt? @set(x,y) @nudge(dx,dy,big) @center @suggest @natural({w,h})>`.
  - `<PlaceList :items :current-index :src :focal :variant="list"|"chips" @select(index)>` where `items = [{id, place, label, visibility}]`.
  - Test helper `mountSfc.js`: `installDom()`, `loadSfc(fileUrl, stubs, Vue)`, `settle(Vue, rounds = 4)`.

- [ ] **Step 1: Write the test harness and the failing tests**

`__tests__/fixtures/noopScrollLock.js`:

```js
/** SSR testinde `document` yok — kaydırma kilidi burada etkisiz. */
export function useScrollLock() {
  return { set() {} };
}
```

`__tests__/mountSfc.js`:

```js
import { readFileSync } from "node:fs";
import { setImmediate } from "node:timers";
import { JSDOM } from "jsdom";
import { compileScript, parse } from "@vue/compiler-sfc";

/**
 * Gerçek SFC'yi jsdom'da istemci tarafında çalıştırır (mediaExplorerLoad.test.js deseni).
 * İçe aktarımlar `stubs[yol]` ile değiştirilir: varsayılan içe aktarımda değer
 * doğrudan bağlanan şeydir (bileşen/nesne), adlı içe aktarımda modül nesnesidir.
 * `import "x.css"` gibi yan etki içe aktarımları atlanır.
 */
export function installDom() {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", { pretendToBeVisual: true });
  for (const key of ["window", "document", "Node", "Element", "HTMLElement", "SVGElement", "Event", "KeyboardEvent"])
    globalThis[key] = dom.window[key];
  dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  return dom;
}

export function loadSfc(fileUrl, stubs, Vue) {
  const { descriptor } = parse(readFileSync(fileUrl, "utf8"));
  const compiled = compileScript(descriptor, { id: "sfc-test", inlineTemplate: true });
  const program = compiled.content
    .replace(/^import\s+["'][^"']+["'];?\s*$/gm, "")
    .replace(/import\s+([\s\S]*?)\s+from\s+["']([^"']+)["'];?/g, (_, bindings, path) => {
      const target = path === "vue" ? "Vue" : `stubs[${JSON.stringify(path)}]`;
      if (bindings.trim().startsWith("{"))
        return `const ${bindings.replace(/\s+as\s+/g, ":")} = ${target};`;
      return `const ${bindings.trim()} = ${target};`;
    })
    .replace("export default", "return");
  const blank = Vue.defineComponent({ render: () => Vue.h("span") });
  const proxy = new Proxy(stubs, { get: (t, k) => (k in t ? t[k] : blank) });
  return new Function("Vue", "stubs", program)(Vue, proxy);
}

export async function settle(Vue, rounds = 4) {
  for (let i = 0; i < rounds; i += 1) {
    await new Promise((resolve) => setImmediate(resolve));
    await Vue.nextTick();
  }
}
```

`__tests__/focalEditor.test.js`:

```js
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { installDom, loadSfc, settle } from "./mountSfc.js";

installDom();
const Vue = await import("vue");
const places = await import("../../../../lib/media/preview/places.js");
const { default: messages } = await import("../../../../lib/media/preview/messages.js");

const FILE = new URL("../FocalEditor.vue", import.meta.url);
const FocalEditor = loadSfc(
  FILE,
  {
    "vue-i18n": { useI18n: () => ({ t: (k, p) => (p ? `${k}${JSON.stringify(p)}` : k), locale: Vue.ref("tr") }) },
    "@/lib/media/preview/places.js": places,
    "@/lib/media/preview/messages.js": messages,
  },
  Vue
);

async function mount(props) {
  const events = [];
  const host = document.createElement("div");
  document.body.append(host);
  const app = Vue.createApp({
    render: () =>
      Vue.h(FocalEditor, {
        src: "/files/ozgen.webp",
        imageRatio: 2000 / 408,
        focal: { x: 0.78, y: 0.45 },
        frame: { left: 0.43, top: 0, width: 0.44, height: 1 },
        ...props,
        onSet: (...a) => events.push(["set", ...a]),
        onNudge: (...a) => events.push(["nudge", ...a]),
        onCenter: () => events.push(["center"]),
        onSuggest: () => events.push(["suggest"]),
      }),
  });
  app.mount(host);
  await settle(Vue);
  return { host, events, close: () => (app.unmount(), host.remove()) };
}

const key = (el, k, extra = {}) =>
  el.dispatchEvent(new window.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...extra }));

test("işaret: ok %1, Shift+ok %10, Home ortalar", async () => {
  const v = await mount();
  try {
    const handle = v.host.querySelector(".fe__handle");
    assert.match(handle.getAttribute("aria-label"), /imagePlacement\.focal\.handle/);
    key(handle, "ArrowRight");
    key(handle, "ArrowUp", { shiftKey: true });
    key(handle, "Home");
    assert.deepEqual(v.events, [["nudge", 1, 0, false], ["nudge", 0, -1, true], ["center"]]);
  } finally {
    v.close();
  }
});

test("tıklama ile seçme (sürüklemeye alternatif)", async () => {
  const v = await mount();
  try {
    const box = v.host.querySelector(".fe__box");
    box.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100 });
    box.dispatchEvent(new window.MouseEvent("click", { clientX: 156, clientY: 45, bubbles: true }));
    const [kind, x, y] = v.events.at(-1);
    assert.equal(kind, "set");
    assert.ok(Math.abs(x - 0.78) < 1e-9 && Math.abs(y - 0.45) < 1e-9);
  } finally {
    v.close();
  }
});

test("sayı kutuları yüzdeyi 0-1'e çevirir", async () => {
  const v = await mount();
  try {
    const [inX] = v.host.querySelectorAll("input[type=number]");
    inX.value = "30";
    inX.dispatchEvent(new window.Event("change", { bubbles: true }));
    assert.deepEqual(v.events.at(-1), ["set", 0.3, 0.45]);
  } finally {
    v.close();
  }
});

test("RTL'de aynalanmaz: görsel kutusu dir=ltr, işaret translate ile", async () => {
  const v = await mount();
  try {
    assert.equal(v.host.querySelector(".fe__box").getAttribute("dir"), "ltr");
    assert.match(v.host.querySelector(".fe__layer--handle").getAttribute("style"), /translate\(78%, 45%\)/);
  } finally {
    v.close();
  }
});

test("telefon: artır/azalt düğmeleri adlandırılmış", async () => {
  const v = await mount({ compact: true });
  try {
    const inc = [...v.host.querySelectorAll("button")].find((b) =>
      b.getAttribute("aria-label")?.includes("imagePlacement.focal.incX")
    );
    inc.click();
    assert.deepEqual(v.events.at(-1), ["nudge", 1, 0, false]);
  } finally {
    v.close();
  }
});

test("hareket azaltma: geçişler kapanıyor", () => {
  const src = readFileSync(FILE, "utf8");
  assert.match(src, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(src, /transition: transform 220ms cubic-bezier\(0\.2, 0\.8, 0\.2, 1\)/);
  assert.doesNotMatch(src, /transition:[^;]*(left|top|width|height)/);
});
```

`__tests__/placeList.test.js`:

```js
import assert from "node:assert/strict";
import { test } from "node:test";

import { installDom, loadSfc, settle } from "./mountSfc.js";

installDom();
const Vue = await import("vue");
const geometry = await import("../../../../lib/media/crop/geometry.js");
const places = await import("../../../../lib/media/preview/places.js");
const { default: messages } = await import("../../../../lib/media/preview/messages.js");

const PlaceList = loadSfc(
  new URL("../PlaceList.vue", import.meta.url),
  {
    "vue-i18n": { useI18n: () => ({ t: (k, p) => (p ? `${k}${JSON.stringify(p)}` : k), locale: Vue.ref("tr") }) },
    "@/lib/media/crop/geometry.js": geometry,
    "@/lib/media/preview/places.js": places,
    "@/lib/media/preview/messages.js": messages,
  },
  Vue
);

const ITEMS = places.placesFor("company.cover_image", "mobile").map((place) => ({
  id: `${place.device}:${place.key}`,
  place,
  label: place.label,
  visibility: places.placeVisibility(place, 2000 / 408),
}));

test("seçili yer aria-current, rozet yazı + simge taşır, seçim olayı", async () => {
  const picked = [];
  const host = document.createElement("div");
  document.body.append(host);
  const app = Vue.createApp({
    render: () =>
      Vue.h(PlaceList, {
        items: ITEMS,
        currentIndex: 0,
        src: "/files/ozgen.webp",
        focal: { x: 0.78, y: 0.45 },
        onSelect: (i) => picked.push(i),
      }),
  });
  app.mount(host);
  await settle(Vue);
  try {
    const rows = host.querySelectorAll(".pl__row");
    assert.equal(rows[0].getAttribute("aria-current"), "true");
    assert.equal(rows[1].hasAttribute("aria-current"), false);
    const chip = rows[0].querySelector(".pl__chip");
    assert.match(chip.textContent, /imagePlacement\.chip\.partial\{"pct":"%44"\}/);
    assert.equal(chip.querySelector("svg").getAttribute("aria-hidden"), "true");
    assert.match(rows[0].querySelector(".pl__img").getAttribute("style"), /object-position: 78% 45%/);
    rows[2].click();
    assert.deepEqual(picked, [2]);
  } finally {
    app.unmount();
    host.remove();
  }
});
```

`__tests__/imagePlacementModal.test.js`:

```js
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { installDom, loadSfc, settle } from "./mountSfc.js";

installDom();
const Vue = await import("vue");
const geometry = await import("../../../../lib/media/crop/geometry.js");
const places = await import("../../../../lib/media/preview/places.js");
const { default: messages } = await import("../../../../lib/media/preview/messages.js");
const realFocal = await import("../../../../composables/useFocalPoint.js");

const FILE = new URL("../ImagePlacementModal.vue", import.meta.url);

function build({ target, prefs = { autoopen: true }, saveError = null } = {}) {
  const calls = { prefs: [], save: [] };
  const deps = {
    async getIntent() {
      return { etag: '"e1"', exists: true, intent: { focal_x: 0.5, focal_y: 0.5 } };
    },
    async suggest() {
      return null;
    },
    async saveFocal(p) {
      calls.save.push(p);
      if (saveError) throw saveError;
      return { etag: '"e2"' };
    },
  };
  const FocalEditorStub = Vue.defineComponent({
    emits: ["set", "nudge", "center", "suggest", "natural"],
    setup: (_, { emit }) => () =>
      Vue.h("button", { type: "button", "data-fe": "", onClick: () => emit("set", 0.78, 0.45) }, "fe"),
  });
  const PlaceListStub = Vue.defineComponent({
    props: ["items", "currentIndex", "src", "focal", "variant"],
    emits: ["select"],
    setup: (p, { emit }) => () =>
      Vue.h(
        "ul",
        p.items.map((it, i) =>
          Vue.h("li", { key: it.id }, [
            Vue.h(
              "button",
              {
                type: "button",
                "data-place": it.id,
                "aria-current": i === p.currentIndex ? "true" : undefined,
                onClick: () => emit("select", i),
              },
              it.label
            ),
          ])
        )
      ),
  });
  const Modal = loadSfc(
    FILE,
    {
      "vue-i18n": { useI18n: () => ({ t: (k, p) => (p ? `${k}${JSON.stringify(p)}` : k), locale: Vue.ref("tr") }) },
      "./FocalEditor.vue": FocalEditorStub,
      "./PlaceList.vue": PlaceListStub,
      "./contexts/index.js": { CONTEXTS: {} },
      "@/composables/useFocalPoint.js": { useFocalPoint: (o) => realFocal.useFocalPoint({ ...o, deps }) },
      "@/composables/useScrollLock": { useScrollLock: () => ({ set() {} }) },
      "@/lib/media/crop/geometry.js": geometry,
      "@/lib/media/preview/messages.js": messages,
      "@/lib/media/preview/places.js": places,
      "@/lib/media/preview/previewApi.js": {
        getPreviewTarget: async () =>
          target ?? {
            asset: "A1",
            processing: false,
            source: { width: 2000, height: 408, bytes: 123072, format: "webp" },
            focal: null,
            square: null,
          },
        getPreviewPrefs: async () => prefs,
        setPreviewPrefs: async (v) => {
          calls.prefs.push(v);
          return { autoopen: v };
        },
      },
    },
    Vue
  );
  return { Modal, calls };
}

async function mount(opts = {}, props = {}) {
  const { Modal, calls } = build(opts);
  const events = [];
  const open = Vue.ref(true);
  const host = document.createElement("div");
  document.body.append(host);
  const app = Vue.createApp({
    render: () =>
      Vue.h(Modal, {
        open: open.value,
        "onUpdate:open": (v) => {
          open.value = v;
          events.push(["update:open", v]);
        },
        fileUrl: "/files/c2/ozgen-banner.webp",
        slotKey: "company.cover_image",
        context: { storeName: "Özgen Plastik" },
        onClose: () => events.push(["close"]),
        onSaved: (f) => events.push(["saved", f]),
        ...props,
      }),
  });
  app.mount(host);
  await settle(Vue, 6);
  const root = () => host.querySelector('[role="dialog"]');
  const press = (k, extra = {}) =>
    root().dispatchEvent(new window.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...extra }));
  return { host, root, press, events, calls, open, close: () => (app.unmount(), host.remove()) };
}

const primary = (host) => host.querySelector(".ipm__btn--primary");

test("diyalog adı, rolü ve cihaz seçici aria-pressed", async () => {
  const v = await mount();
  try {
    const d = v.root();
    assert.equal(d.getAttribute("aria-modal"), "true");
    const title = document.getElementById(d.getAttribute("aria-labelledby"));
    assert.equal(title.textContent.trim(), "imagePlacement.title");
    const seg = [...v.host.querySelectorAll(".ipm__seg-btn")];
    assert.deepEqual(seg.map((b) => b.getAttribute("aria-pressed")), ["true", "false"]);
    seg[1].click();
    await settle(Vue);
    assert.deepEqual(
      [...v.host.querySelectorAll(".ipm__seg-btn")].map((b) => b.getAttribute("aria-pressed")),
      ["false", "true"]
    );
    assert.ok(v.host.querySelector('[role="status"][aria-live="polite"]'));
  } finally {
    v.close();
  }
});

test("yer listesinde seçim aria-current ile ilerler", async () => {
  const v = await mount();
  try {
    const rows = () => [...v.host.querySelectorAll("[data-place]")];
    assert.equal(rows()[0].getAttribute("aria-current"), "true");
    rows()[1].click();
    await settle(Vue);
    assert.equal(rows()[1].getAttribute("aria-current"), "true");
  } finally {
    v.close();
  }
});

test("Esc: değişiklik yoksa kapatır", async () => {
  const v = await mount();
  try {
    v.press("Escape");
    await settle(Vue);
    assert.deepEqual(v.events.slice(-2), [["update:open", false], ["close"]]);
  } finally {
    v.close();
  }
});

test("Esc: kaydedilmemiş değişiklikte onay ister", async () => {
  const v = await mount();
  try {
    v.host.querySelector("[data-fe]").click();
    await settle(Vue);
    v.press("Escape");
    await settle(Vue);
    assert.ok(v.host.querySelector('[role="alertdialog"]'));
    v.host.querySelector("[data-confirm-keep]").click();
    await settle(Vue);
    assert.equal(v.host.querySelector('[role="alertdialog"]'), null);
    assert.equal(v.open.value, true);
    v.press("Escape");
    await settle(Vue);
    v.host.querySelector("[data-confirm-discard]").click();
    await settle(Vue);
    assert.deepEqual(v.events.at(-1), ["close"]);
  } finally {
    v.close();
  }
});

test("odak tuzağı: son öğeden Tab başa, ilkten Shift+Tab sona", async () => {
  const v = await mount();
  try {
    const items = [
      ...v.root().querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'),
    ];
    items.at(-1).focus();
    v.press("Tab");
    assert.equal(document.activeElement, items[0]);
    v.press("Tab", { shiftKey: true });
    assert.equal(document.activeElement, items.at(-1));
  } finally {
    v.close();
  }
});

test("Kaydet: yalnız odak gider, saved yayılır, pencere kapanır", async () => {
  const v = await mount();
  try {
    v.host.querySelector("[data-fe]").click();
    await settle(Vue);
    primary(v.host).click();
    await settle(Vue);
    assert.equal(v.calls.save[0].focalX, 0.78);
    assert.equal(v.calls.save[0].ifMatch, '"e1"');
    assert.ok(v.calls.save[0].previewed.length >= 1);
    assert.deepEqual(v.events.find((e) => e[0] === "saved"), ["saved", { x: 0.78, y: 0.45 }]);
    assert.deepEqual(v.events.at(-1), ["close"]);
  } finally {
    v.close();
  }
});

test("çakışma: pencere açık kalır, yeniden yükle düğmesi çıkar", async () => {
  const v = await mount({ saveError: Object.assign(new Error("x"), { status: 412 }) });
  try {
    v.host.querySelector("[data-fe]").click();
    await settle(Vue);
    primary(v.host).click();
    await settle(Vue);
    assert.equal(v.open.value, true);
    assert.match(v.host.textContent, /imagePlacement\.reload/);
  } finally {
    v.close();
  }
});

test("varlık yoksa Kaydet kapalı ve neden yazılı; işleniyor bildirimi", async () => {
  const v = await mount({
    target: { asset: "", processing: true, source: { width: 0, height: 0, bytes: 0, format: "" }, focal: null, square: null },
  });
  try {
    assert.equal(primary(v.host).disabled, true);
    assert.match(v.host.textContent, /imagePlacement\.status\.cannotSave/);
    assert.match(v.host.textContent, /imagePlacement\.status\.processing/);
  } finally {
    v.close();
  }
});

test("otomatik açılma kutusu tercihi sunucuya yazar", async () => {
  const v = await mount();
  try {
    const box = v.host.querySelector('.ipm__check input[type="checkbox"]');
    assert.equal(box.checked, true);
    box.checked = false;
    box.dispatchEvent(new window.Event("change", { bubbles: true }));
    await settle(Vue);
    assert.deepEqual(v.calls.prefs, [false]);
  } finally {
    v.close();
  }
});

test("kapanınca odak açan düğmeye döner", async () => {
  const opener = document.createElement("button");
  document.body.append(opener);
  const v = await mount({}, { returnFocus: opener });
  try {
    v.press("Escape");
    await settle(Vue);
    assert.equal(document.activeElement, opener);
  } finally {
    v.close();
    opener.remove();
  }
});

test("hareket: süreler spec §6, hareket azaltmada kapalı, yalnız transform/opacity", () => {
  const src = readFileSync(FILE, "utf8");
  assert.match(src, /\.ipm-enter-active[^{]*\{[^}]*200ms/);
  assert.match(src, /\.ipm-leave-active[^{]*\{[^}]*160ms/);
  assert.match(src, /animation: ipm-in 220ms cubic-bezier\(0\.2, 0\.8, 0\.2, 1\)/);
  assert.match(src, /@media \(prefers-reduced-motion: reduce\)/);
  for (const m of src.matchAll(/transition:\s*([^;]+);/g))
    assert.match(m[1], /^(none|(opacity|transform) \d+ms[^,]*)$/, m[1]);
  assert.doesNotMatch(src, /#6d6a61/i);
});
```

`__tests__/previewAxe.test.js`:

```js
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { after, before, test } from "node:test";
import vue from "@vitejs/plugin-vue";
import { createServer } from "vite";
import { createSSRApp, h } from "vue";
import { createI18n } from "vue-i18n";
import { renderToString } from "@vue/server-renderer";

import messages from "../../../../lib/media/preview/messages.js";
import { placesFor, placeVisibility } from "../../../../lib/media/preview/places.js";
import { describe as describeAxe, scanHtml } from "../../a11y/axeHarness.js";

const frontendRoot = fileURLToPath(new URL("../../../../..", import.meta.url));
let server;

before(async () => {
  server = await createServer({
    configFile: false,
    root: frontendRoot,
    logLevel: "silent",
    plugins: [vue()],
    resolve: {
      alias: [
        {
          find: /^@\/composables\/useScrollLock$/,
          replacement: `${frontendRoot}/src/components/media/preview/__tests__/fixtures/noopScrollLock.js`,
        },
        { find: /^@\/utils\/api$/, replacement: `${frontendRoot}/src/components/media/__tests__/fixtures/apiMock.js` },
        { find: "@", replacement: `${frontendRoot}/src` },
      ],
    },
    server: { middlewareMode: true },
    appType: "custom",
  });
});
after(async () => server?.close());

async function render(path, props, locale = "tr") {
  const { default: C } = await server.ssrLoadModule(path);
  const app = createSSRApp({ render: () => h(C, props) });
  app.use(createI18n({ legacy: false, locale, fallbackLocale: "tr", messages }));
  return renderToString(app);
}

async function expectClean(html, label, lang = "tr") {
  const { violations } = await scanHtml(html, { lang });
  assert.equal(violations.length, 0, `${label}\n${describeAxe(violations)}`);
}

const ITEMS = placesFor("company.cover_image", "desktop").map((place) => ({
  id: `${place.device}:${place.key}`,
  place,
  label: place.label,
  visibility: placeVisibility(place, 2000 / 408),
}));

test("PlaceList (liste ve çip) 0 ihlal", async () => {
  for (const variant of ["list", "chips"]) {
    const html = await render("/src/components/media/preview/PlaceList.vue", {
      items: ITEMS,
      currentIndex: 0,
      src: "/files/ozgen.webp",
      focal: { x: 0.78, y: 0.45 },
      variant,
    });
    await expectClean(html, variant);
  }
});

test("FocalEditor (masaüstü, telefon, Arapça) 0 ihlal", async () => {
  for (const [compact, locale] of [[false, "tr"], [true, "tr"], [false, "ar"]]) {
    const html = await render(
      "/src/components/media/preview/FocalEditor.vue",
      {
        src: "/files/ozgen.webp",
        imageRatio: 2000 / 408,
        focal: { x: 0.78, y: 0.45 },
        frame: { left: 0.43, top: 0, width: 0.44, height: 1 },
        compact,
        imageAlt: "Görselin tamamı",
      },
      locale
    );
    await expectClean(html, `compact=${compact} ${locale}`, locale);
  }
});

test("pencere kabuğu (açık, veri yüklenmeden) 0 ihlal", async () => {
  const html = await render("/src/components/media/preview/ImagePlacementModal.vue", {
    open: true,
    fileUrl: "/files/c2/ozgen-banner.webp",
    slotKey: "company.cover_image",
    context: { storeName: "Özgen Plastik" },
  });
  assert.match(html, /role="dialog"/);
  await expectClean(html, "modal");
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/ahmet/Desktop/istoc/admin-panel/frontend && node --test src/components/media/preview/__tests__/focalEditor.test.js src/components/media/preview/__tests__/placeList.test.js src/components/media/preview/__tests__/imagePlacementModal.test.js src/components/media/preview/__tests__/previewAxe.test.js 2>&1 | tail -5`
Expected: FAIL — `ENOENT: no such file or directory, open '…/FocalEditor.vue'` (and the same for the other two components).

- [ ] **Step 3: Implement `FocalEditor.vue`**

```vue
<script setup>
  import { computed, ref } from "vue";
  import { useI18n } from "vue-i18n";

  import { formatPercent } from "@/lib/media/preview/places.js";
  import messages from "@/lib/media/preview/messages.js";

  /**
   * Odak noktası seçici (spec §4.2 sağ sütun, §5 2.5.7). Sürüklemeye üç
   * alternatif: tıklama/dokunma, sayı kutuları (telefonda −/+), ok tuşları.
   * Koordinatlar GÖRSEL uzayıdır: kutu `dir="ltr"`, işaret `translate(x%, y%)`
   * — Arapça arayüzde aynalanmaz.
   */
  const props = defineProps({
    src: { type: String, required: true },
    imageRatio: { type: Number, default: 0 },
    focal: { type: Object, required: true },
    frame: { type: Object, default: null },
    compact: { type: Boolean, default: false },
    imageAlt: { type: String, default: "" },
  });
  const emit = defineEmits(["set", "nudge", "center", "suggest", "natural"]);
  const { t, locale } = useI18n({ messages });

  const box = ref(null);
  let dragging = false;

  const xPct = computed(() => Math.round(props.focal.x * 100));
  const yPct = computed(() => Math.round(props.focal.y * 100));
  const fx = computed(() => formatPercent(props.focal.x, locale.value));
  const fy = computed(() => formatPercent(props.focal.y, locale.value));
  const boxStyle = computed(() => ({
    aspectRatio: props.imageRatio > 0 ? String(props.imageRatio) : "16 / 9",
  }));
  const handleLayer = computed(() => ({
    transform: `translate(${xPct.value}%, ${yPct.value}%)`,
  }));
  const frameLayer = computed(() =>
    props.frame
      ? { transform: `translate(${props.frame.left * 100}%, ${props.frame.top * 100}%)` }
      : null
  );
  const frameBox = computed(() =>
    props.frame ? { width: `${props.frame.width * 100}%`, height: `${props.frame.height * 100}%` } : null
  );

  function fromEvent(ev) {
    const r = box.value?.getBoundingClientRect();
    if (!r || !r.width || !r.height) return null;
    return { x: (ev.clientX - r.left) / r.width, y: (ev.clientY - r.top) / r.height };
  }
  function onBoxClick(ev) {
    if (ev.target.closest?.(".fe__handle")) return;
    const p = fromEvent(ev);
    if (p) emit("set", p.x, p.y);
  }
  function onPointerDown(ev) {
    dragging = true;
    ev.currentTarget.setPointerCapture?.(ev.pointerId);
  }
  function onPointerMove(ev) {
    if (!dragging) return;
    const p = fromEvent(ev);
    if (p) emit("set", p.x, p.y);
  }
  function onPointerUp() {
    dragging = false;
  }
  const KEYS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
  function onKey(ev) {
    if (KEYS[ev.key]) {
      ev.preventDefault();
      emit("nudge", KEYS[ev.key][0], KEYS[ev.key][1], ev.shiftKey);
    } else if (ev.key === "Home") {
      ev.preventDefault();
      emit("center");
    }
  }
  function onNumber(axis, ev) {
    const n = Number(ev.target.value);
    const v = ev.target.value === "" || !Number.isFinite(n) ? 0.5 : Math.min(100, Math.max(0, n)) / 100;
    if (axis === "x") emit("set", v, props.focal.y);
    else emit("set", props.focal.x, v);
  }
  function onLoad(ev) {
    emit("natural", { w: ev.target.naturalWidth || 0, h: ev.target.naturalHeight || 0 });
  }
</script>

<template>
  <div class="fe" :class="{ 'fe--compact': compact }">
    <div ref="box" class="fe__box" dir="ltr" :style="boxStyle" @click="onBoxClick">
      <div class="fe__clip">
        <img class="fe__img" :src="src" :alt="imageAlt" @load="onLoad" />
        <div v-if="frame" class="fe__layer" :style="frameLayer" aria-hidden="true">
          <span class="fe__frame" :style="frameBox" />
        </div>
      </div>
      <div class="fe__layer fe__layer--handle" :style="handleLayer">
        <button
          type="button"
          class="fe__handle"
          :aria-label="t('imagePlacement.focal.handle', { x: fx, y: fy })"
          @keydown="onKey"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerUp"
        >
          <span class="fe__dot" aria-hidden="true" />
        </button>
      </div>
    </div>

    <div v-if="!compact" class="fe__inputs">
      <label class="fe__label">
        {{ t("imagePlacement.focal.x") }}
        <input class="fe__input" type="number" min="0" max="100" step="1" :value="xPct" @change="onNumber('x', $event)" />
      </label>
      <label class="fe__label">
        {{ t("imagePlacement.focal.y") }}
        <input class="fe__input" type="number" min="0" max="100" step="1" :value="yPct" @change="onNumber('y', $event)" />
      </label>
    </div>
    <div v-else class="fe__steppers">
      <div class="fe__stepper">
        <span class="fe__step-label">{{ t("imagePlacement.focal.xShort") }}</span>
        <div class="fe__step-row">
          <button type="button" class="fe__step" :aria-label="t('imagePlacement.focal.decX')" @click="emit('nudge', -1, 0, false)">−</button>
          <span class="fe__step-value" aria-hidden="true">{{ fx }}</span>
          <button type="button" class="fe__step" :aria-label="t('imagePlacement.focal.incX')" @click="emit('nudge', 1, 0, false)">+</button>
        </div>
      </div>
      <div class="fe__stepper">
        <span class="fe__step-label">{{ t("imagePlacement.focal.yShort") }}</span>
        <div class="fe__step-row">
          <button type="button" class="fe__step" :aria-label="t('imagePlacement.focal.decY')" @click="emit('nudge', 0, -1, false)">−</button>
          <span class="fe__step-value" aria-hidden="true">{{ fy }}</span>
          <button type="button" class="fe__step" :aria-label="t('imagePlacement.focal.incY')" @click="emit('nudge', 0, 1, false)">+</button>
        </div>
      </div>
    </div>

    <div class="fe__actions">
      <button type="button" class="fe__btn" @click="emit('suggest')">{{ t("imagePlacement.focal.suggest") }}</button>
      <button v-if="!compact" type="button" class="fe__btn" @click="emit('center')">{{ t("imagePlacement.focal.center") }}</button>
    </div>
    <p v-if="!compact" class="fe__hint">{{ t("imagePlacement.focal.keyboard") }}</p>
  </div>
</template>

<style scoped>
  .fe { display: flex; flex-direction: column; gap: 14px; color: #1d1c19; }
  .fe__box { position: relative; width: 100%; cursor: crosshair; touch-action: none; }
  .fe__clip { position: absolute; inset: 0; overflow: hidden; border-radius: 8px; }
  .fe__img { width: 100%; height: 100%; display: block; object-fit: fill; pointer-events: none; }
  .fe__layer {
    position: absolute;
    inset: 0;
    pointer-events: none;
    transition: transform 220ms cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  .fe__frame {
    position: absolute;
    top: 0;
    left: 0;
    box-sizing: border-box;
    border: 2px dashed #ffffff;
    box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.55), inset 0 0 0 1px rgba(0, 0, 0, 0.55);
  }
  .fe__handle {
    position: absolute;
    top: 0;
    left: 0;
    width: 44px;
    height: 44px;
    margin: -22px 0 0 -22px;
    border: 0;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.35);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: grab;
    pointer-events: auto;
  }
  .fe__dot { width: 12px; height: 12px; border-radius: 50%; background: #f5b800; box-shadow: 0 0 0 3px #1a1a1a; }
  .fe__inputs, .fe__actions, .fe__steppers { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .fe--compact .fe__actions { grid-template-columns: 1fr; }
  .fe__label { display: flex; flex-direction: column; gap: 6px; font-size: 14px; font-weight: 600; }
  .fe__input {
    height: 44px;
    box-sizing: border-box;
    padding: 0 10px;
    border: 1px solid #8a867c;
    border-radius: 10px;
    font: inherit;
    font-weight: 500;
    color: #1d1c19;
    background: #ffffff;
  }
  .fe__btn {
    min-height: 44px;
    border-radius: 12px;
    border: 1px solid #e6e3dc;
    background: #ffffff;
    font: inherit;
    font-size: 15px;
    font-weight: 600;
    color: #1d1c19;
    cursor: pointer;
  }
  .fe__stepper { display: flex; flex-direction: column; gap: 6px; }
  .fe__step-label { font-size: 14px; font-weight: 600; }
  .fe__step-row { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
  .fe__step {
    width: 44px;
    height: 44px;
    border-radius: 12px;
    border: 1px solid #8a867c;
    background: #ffffff;
    font: inherit;
    font-size: 20px;
    font-weight: 700;
    color: #1d1c19;
    cursor: pointer;
  }
  .fe__step-value { font-size: 16px; font-weight: 700; }
  .fe__hint { margin: 0; font-size: 14px; line-height: 1.5; color: #3a3833; }
  .fe__handle:focus-visible, .fe__btn:focus-visible, .fe__input:focus-visible, .fe__step:focus-visible {
    outline: 3px solid #1a1a1a;
    outline-offset: 2px;
  }
  @media (prefers-reduced-motion: reduce) {
    .fe__layer { transition: none; }
  }
</style>
```

- [ ] **Step 4: Implement `PlaceList.vue`**

```vue
<script setup>
  import { useI18n } from "vue-i18n";

  import { objectPosition } from "@/lib/media/crop/geometry.js";
  import { formatPercent } from "@/lib/media/preview/places.js";
  import messages from "@/lib/media/preview/messages.js";

  /** Yer listesi (masaüstü sol sütun) ya da yatay çipler (telefon). Rozet = yazı + simge (1.4.1). */
  defineProps({
    items: { type: Array, required: true },
    currentIndex: { type: Number, default: 0 },
    src: { type: String, required: true },
    focal: { type: Object, required: true },
    variant: { type: String, default: "list" },
  });
  const emit = defineEmits(["select"]);
  const { t, locale } = useI18n({ messages });

  const size = (p) => (p.cssW && p.cssH ? `${p.cssW} × ${p.cssH}` : "");
  const chip = (v) =>
    v.full
      ? t("imagePlacement.chip.full")
      : t("imagePlacement.chip.partial", { pct: formatPercent(v.fraction, locale.value) });
  const imgStyle = (p, focal) => ({
    objectFit: p.fit,
    objectPosition: p.fit === "cover" ? objectPosition(focal) : "50% 50%",
  });
</script>

<template>
  <ul v-if="variant === 'list'" class="pl" role="list">
    <li v-for="(it, i) in items" :key="it.id">
      <button
        type="button"
        class="pl__row"
        :class="{ 'pl__row--on': i === currentIndex }"
        :aria-current="i === currentIndex ? 'true' : undefined"
        @click="emit('select', i)"
      >
        <span class="pl__thumb" :style="{ aspectRatio: String(it.place.ratio) }">
          <img class="pl__img ctx-img" :src="src" alt="" :style="imgStyle(it.place, focal)" />
        </span>
        <span class="pl__text">
          <span class="pl__label">{{ it.label }}</span>
          <span class="pl__meta">
            {{ it.place.ratioLabel }}<template v-if="size(it.place)"> · {{ size(it.place) }}</template>
          </span>
          <span v-if="!it.visibility.unknown" class="pl__chip" :class="it.visibility.full ? 'pl__chip--full' : 'pl__chip--cut'">
            <svg v-if="it.visibility.full" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true" focusable="false"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
            <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true" focusable="false"><circle cx="6" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M20 4L8.1 15.9M14.5 14.5L20 20M8.1 8.1L12 12" /></svg>
            {{ chip(it.visibility) }}
          </span>
        </span>
      </button>
    </li>
  </ul>
  <ul v-else class="pl pl--chips" role="list">
    <li v-for="(it, i) in items" :key="it.id">
      <button
        type="button"
        class="pl__chipbtn"
        :class="{ 'pl__row--on': i === currentIndex }"
        :aria-current="i === currentIndex ? 'true' : undefined"
        @click="emit('select', i)"
      >
        <span class="pl__label">{{ it.label }}</span>
        <span v-if="!it.visibility.unknown" class="pl__chip" :class="it.visibility.full ? 'pl__chip--full' : 'pl__chip--cut'">{{ chip(it.visibility) }}</span>
      </button>
    </li>
  </ul>
</template>

<style scoped>
  .pl { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  .pl--chips { flex-direction: row; overflow-x: auto; padding-bottom: 4px; }
  .pl__row, .pl__chipbtn {
    width: 100%;
    min-height: 44px;
    display: flex;
    gap: 10px;
    align-items: center;
    padding: 10px;
    border-radius: 12px;
    border: 2px solid transparent;
    background: transparent;
    font: inherit;
    color: #1d1c19;
    text-align: start;
    cursor: pointer;
    transition: opacity 160ms ease;
  }
  .pl__chipbtn { width: auto; flex-direction: column; align-items: flex-start; gap: 4px; white-space: nowrap; border-color: #e6e3dc; }
  .pl__row--on { background: #ffffff; border-color: #1a1a1a; }
  .pl__thumb { width: 64px; max-height: 64px; flex-shrink: 0; border-radius: 6px; overflow: hidden; background: #e6e3dc; }
  .pl__img { width: 100%; height: 100%; display: block; }
  .pl__text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .pl__label { font-size: 15px; font-weight: 600; line-height: 1.3; }
  .pl__meta { font-size: 13px; color: #3a3833; }
  .pl__chip {
    align-self: flex-start;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-top: 2px;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
  }
  .pl__chip--full { background: #e7f6ef; color: #035c43; }
  .pl__chip--cut { background: #fff7ed; color: #7c2d12; }
  .pl__row:focus-visible, .pl__chipbtn:focus-visible { outline: 3px solid #1a1a1a; outline-offset: 2px; }
  @media (prefers-reduced-motion: reduce) {
    .pl__row, .pl__chipbtn { transition: none; }
  }
</style>
```

- [ ] **Step 5: Implement `ImagePlacementModal.vue`**

```vue
<script setup>
  import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, useId, watch } from "vue";
  import { useI18n } from "vue-i18n";

  import FocalEditor from "./FocalEditor.vue";
  import PlaceList from "./PlaceList.vue";
  import { CONTEXTS } from "./contexts/index.js";
  import { useFocalPoint } from "@/composables/useFocalPoint.js";
  import { useScrollLock } from "@/composables/useScrollLock";
  import { frameRect, objectPosition } from "@/lib/media/crop/geometry.js";
  import messages from "@/lib/media/preview/messages.js";
  import {
    STAGE,
    cutPlaceCount,
    devicesFor,
    formatPercent,
    kindKey,
    placeCount,
    placesFor,
    placeVisibility,
  } from "@/lib/media/preview/places.js";
  import { getPreviewPrefs, getPreviewTarget, setPreviewPrefs } from "@/lib/media/preview/previewApi.js";

  /**
   * "Görseliniz nerelerde görünecek?" penceresi — spec 2026-10-01 §4.2, onaylı pano 1.
   * Bilgisayar (≥1024 px): üç sütun (yer listesi · sayfa bağlamı · odak noktası).
   * Telefon (<1024 px): Önizleme / Odak noktası sekmeleri + sabit alt çubuk (pano 4).
   * Diyalog kabuğu MediaModal'dan uyarlandı: Esc kaydedilmemiş değişiklikte onay
   * ister, bu yüzden MediaModal doğrudan kullanılamıyor.
   */
  const props = defineProps({
    fileUrl: { type: String, required: true },
    slotKey: { type: String, required: true },
    fileName: { type: String, default: "" },
    context: { type: Object, default: () => ({}) },
    /** Kapanınca odağın döneceği öğe ya da onu bulan fonksiyon (otomatik açılışta düğme sonradan oluşur). */
    returnFocus: { type: [Object, Function], default: null },
  });
  const emit = defineEmits(["close", "saved"]);
  const open = defineModel("open", { type: Boolean, default: false });
  const { t, locale } = useI18n({ messages });

  const uid = useId();
  const ids = {
    title: `ipm-t-${uid}`,
    focal: `ipm-f-${uid}`,
    square: `ipm-s-${uid}`,
    confirmTitle: `ipm-ct-${uid}`,
    confirmBody: `ipm-cb-${uid}`,
    tabPreview: `ipm-tp-${uid}`,
    tabFocal: `ipm-tf-${uid}`,
    panelPreview: `ipm-pp-${uid}`,
    panelFocal: `ipm-pf-${uid}`,
  };

  const root = ref(null);
  const target = shallowRef(null);
  const fp = shallowRef(null);
  const device = ref("desktop");
  const placeIdx = ref(0);
  const mobileTab = ref("preview");
  const autoopen = ref(true);
  const confirming = ref(false);
  const narrow = ref(false);
  const narrowScale = ref(0.3);
  const natural = ref({ w: 0, h: 0 });
  let lastFocused = null;
  let inerted = [];
  let mq = null;

  useScrollLock(open);

  const src = computed(() => props.fileUrl);
  const isProduct = computed(() => props.slotKey === "product.image");
  const imageRatio = computed(() => {
    const s = target.value?.source || {};
    const w = s.width || natural.value.w;
    const h = s.height || natural.value.h;
    return w > 0 && h > 0 ? w / h : 0;
  });
  const devices = computed(() => devicesFor(props.slotKey));
  const places = computed(() => placesFor(props.slotKey, device.value));
  const currentPlace = computed(
    () => places.value[Math.min(placeIdx.value, places.value.length - 1)] || null
  );
  const focal = computed(() => fp.value?.focal.value || { x: 0.5, y: 0.5 });
  const toItems = (list) =>
    list.map((place) => ({
      id: `${place.device}:${place.key}`,
      place,
      label: t(place.labelKey),
      visibility: placeVisibility(place, imageRatio.value),
    }));
  const placeItems = computed(() => toItems(places.value));
  const phoneItems = computed(() => toItems(placesFor(props.slotKey, "mobile")));
  const frame = computed(() =>
    currentPlace.value
      ? frameRect(imageRatio.value, currentPlace.value.ratio, focal.value, currentPlace.value.fit)
      : null
  );
  const scale = computed(() => {
    if (device.value === "mobile") return 1;
    return narrow.value ? narrowScale.value : STAGE.desktopStagePx / STAGE.desktopPagePx;
  });
  const stageTitle = computed(() =>
    currentPlace.value ? `${t(currentPlace.value.labelKey)} · ${currentPlace.value.ratioLabel}` : ""
  );
  const stageScale = computed(() =>
    device.value === "desktop"
      ? t("imagePlacement.stageScale.desktop", {
          page: STAGE.desktopPagePx,
          pct: formatPercent(scale.value, locale.value),
        })
      : t("imagePlacement.stageScale.mobile", { page: STAGE.mobilePagePx })
  );
  const currentContext = computed(() => (currentPlace.value && CONTEXTS[currentPlace.value.context]) || null);
  const contextData = computed(() => ({
    storeName: props.context.storeName || "",
    productName: props.context.productName || "",
    price: props.context.price || "",
  }));
  const subtitle = computed(() => {
    const s = target.value?.source || {};
    const kind = t(`imagePlacement.kind.${kindKey(props.slotKey)}`);
    const file = props.fileName || decodeURIComponent(String(props.fileUrl).split("/").pop() || "");
    return s.width && s.height
      ? t("imagePlacement.subtitle", { kind, file, w: s.width, h: s.height })
      : t("imagePlacement.subtitleNoSize", { kind, file });
  });
  const statusText = computed(() => {
    const a = fp.value?.announce.value;
    if (!a) return "";
    const p = { ...a.params };
    if (typeof p.x === "number") p.x = formatPercent(p.x / 100, locale.value);
    if (typeof p.y === "number") p.y = formatPercent(p.y / 100, locale.value);
    return t(a.key, p);
  });
  const canSave = computed(() => !!target.value?.asset);
  const dirty = computed(() => !!fp.value?.dirty.value);
  const primaryLabel = computed(() =>
    isProduct.value && !dirty.value ? t("imagePlacement.done") : t("imagePlacement.save")
  );
  const primaryDisabled = computed(() => {
    if (!fp.value || fp.value.saving.value) return true;
    if (isProduct.value && !dirty.value) return false;
    return !canSave.value;
  });
  const summary = computed(() => {
    const n = placeCount(props.slotKey);
    const cut = cutPlaceCount(props.slotKey, imageRatio.value);
    return cut ? t("imagePlacement.summary.some", { n, cut }) : t("imagePlacement.summary.none", { n });
  });
  const fileSize = computed(() => {
    const b = target.value?.source?.bytes || 0;
    return b
      ? `${new Intl.NumberFormat(locale.value, { maximumFractionDigits: 1 }).format(b / 1024)} KB`
      : "";
  });
  const chip = (v) =>
    v.full ? t("imagePlacement.chip.full") : t("imagePlacement.chip.partial", { pct: formatPercent(v.fraction, locale.value) });
  const figStyle = (place) => ({
    objectFit: place.fit,
    objectPosition: place.fit === "cover" ? objectPosition(focal.value) : "50% 50%",
  });

  function markCurrent() {
    if (fp.value && currentPlace.value) fp.value.markViewed(currentPlace.value.key, currentPlace.value.device);
  }
  function pickDevice(d) {
    device.value = d;
    placeIdx.value = 0;
    markCurrent();
  }
  function pickPlace(i) {
    placeIdx.value = i;
    markCurrent();
  }
  const onNatural = ({ w, h }) => (natural.value = { w, h });
  const onSet = (x, y) => fp.value?.setFocal(x, y);
  const onNudge = (dx, dy, big) => fp.value?.nudge(dx, dy, big);
  const onCenter = () => fp.value?.center();
  const onSuggest = () => fp.value?.suggest();
  const reload = () => fp.value?.load();

  async function onAutoOpen(ev) {
    const v = !!ev.target.checked;
    autoopen.value = v;
    try {
      await setPreviewPrefs(v);
    } catch {
      autoopen.value = !v;
    }
  }

  async function start() {
    confirming.value = false;
    mobileTab.value = "preview";
    natural.value = { w: 0, h: 0 };
    fp.value = null;
    target.value = null;
    let tgt = null;
    const prefs = getPreviewPrefs()
      .then((p) => (autoopen.value = p?.autoopen !== false))
      .catch(() => {});
    try {
      tgt = await getPreviewTarget(props.fileUrl, props.slotKey);
    } catch {
      tgt = null;
    }
    await prefs;
    target.value = tgt || {
      asset: "",
      processing: true,
      source: { width: 0, height: 0, bytes: 0, format: "" },
      focal: null,
      square: null,
    };
    const inst = useFocalPoint({ asset: target.value.asset || "", initialFocal: target.value.focal });
    fp.value = inst;
    device.value = narrow.value && devices.value.includes("mobile") ? "mobile" : devices.value[0] || "desktop";
    placeIdx.value = 0;
    markCurrent();
    await inst.load();
  }

  async function onSave() {
    if (isProduct.value && !dirty.value) return close();
    if (!canSave.value || !fp.value) return;
    const r = await fp.value.save();
    if (r.ok) {
      emit("saved", { ...fp.value.focal.value });
      close();
    }
  }
  function requestClose() {
    if (confirming.value) {
      confirming.value = false;
      return;
    }
    if (dirty.value && canSave.value) {
      confirming.value = true;
      nextTick(() => root.value?.querySelector("[data-confirm-keep]")?.focus());
      return;
    }
    close();
  }
  function close() {
    confirming.value = false;
    open.value = false;
    emit("close");
  }
  const discard = () => close();
  const keepEditing = () => (confirming.value = false);

  function onTabsKey(ev) {
    if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
    ev.preventDefault();
    mobileTab.value = mobileTab.value === "preview" ? "focal" : "preview";
    nextTick(() => root.value?.querySelector('[role="tab"][aria-selected="true"]')?.focus());
  }

  const FOCUSABLE =
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  function focusables() {
    if (!root.value) return [];
    const scope = (confirming.value && root.value.querySelector('[role="alertdialog"]')) || root.value;
    return [...scope.querySelectorAll(FOCUSABLE)].filter((el) => !el.closest("[hidden],[inert]"));
  }
  function onTab(event) {
    const items = focusables();
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !root.value.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }
  function inertOutside() {
    restoreOutside();
    let branch = root.value;
    while (branch && branch !== document.body) {
      const parent = branch.parentElement;
      if (!parent) break;
      for (const sibling of parent.children) {
        if (sibling === branch) continue;
        inerted.push({ element: sibling, value: sibling.inert });
        sibling.inert = true;
      }
      branch = parent;
    }
  }
  function restoreOutside() {
    for (let i = inerted.length - 1; i >= 0; i -= 1) inerted[i].element.inert = inerted[i].value;
    inerted = [];
  }

  watch(
    open,
    async (isOpen) => {
      if (typeof document === "undefined") return;
      if (isOpen) {
        lastFocused = document.activeElement;
        await nextTick();
        inertOutside();
        (focusables()[0] || root.value)?.focus();
        start();
        return;
      }
      restoreOutside();
      const hedef = typeof props.returnFocus === "function" ? props.returnFocus() : props.returnFocus;
      const back = hedef?.isConnected ? hedef : lastFocused?.isConnected ? lastFocused : null;
      back?.focus?.();
      lastFocused = null;
    },
    { immediate: true }
  );

  function onMq(e) {
    narrow.value = e.matches;
  }
  onMounted(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    mq = window.matchMedia("(max-width: 1023.98px)");
    narrow.value = mq.matches;
    narrowScale.value = Math.min(1, Math.max(0.2, ((window.innerWidth || 390) - 32) / STAGE.desktopPagePx));
    mq.addEventListener?.("change", onMq);
  });
  onBeforeUnmount(() => {
    mq?.removeEventListener?.("change", onMq);
    restoreOutside();
  });
</script>

<template>
  <Transition name="ipm">
    <div
      v-if="open"
      ref="root"
      class="ipm"
      :class="{ 'ipm--narrow': narrow }"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="ids.title"
      @keydown.esc.stop.prevent="requestClose"
      @keydown.tab="onTab"
    >
      <div class="ipm__backdrop" aria-hidden="true" @click="requestClose" />
      <div class="ipm__panel">
        <header class="ipm__head">
          <div class="ipm__titles">
            <h2 :id="ids.title" class="ipm__title">
              {{ narrow ? t("imagePlacement.titleShort") : t("imagePlacement.title") }}
            </h2>
            <p class="ipm__subtitle">{{ subtitle }}</p>
          </div>
          <div v-if="!narrow && devices.length > 1" role="group" :aria-label="t('imagePlacement.device.group')" class="ipm__seg">
            <button
              v-for="d in devices"
              :key="d"
              type="button"
              class="ipm__seg-btn"
              :class="{ 'ipm__seg-btn--on': device === d }"
              :aria-pressed="device === d ? 'true' : 'false'"
              @click="pickDevice(d)"
            >
              <svg v-if="d === 'desktop'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true" focusable="false"><rect x="2" y="4" width="20" height="13" rx="2" /><path d="M8 21h8M12 17v4" /></svg>
              <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true" focusable="false"><rect x="7" y="2" width="10" height="20" rx="2" /><path d="M11 18h2" /></svg>
              {{ t(`imagePlacement.device.${d}`) }}
            </button>
          </div>
          <button type="button" class="ipm__close" :aria-label="t('imagePlacement.close')" @click="requestClose">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true" focusable="false"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </header>

        <p v-if="target && target.processing" class="ipm__notice" role="note">
          {{ t("imagePlacement.status.processing") }}
        </p>

        <div v-if="!narrow" class="ipm__grid">
          <nav class="ipm__list" :aria-label="t('imagePlacement.listLabel')">
            <section v-if="isProduct && target && target.square" class="ipm__square" :aria-labelledby="ids.square">
              <h3 :id="ids.square" class="ipm__h4">{{ t("imagePlacement.square.title") }}</h3>
              <p v-if="target.square.original" class="ipm__square-dims">
                {{ target.square.original.width }} × {{ target.square.original.height }} →
                {{ target.square.size }} × {{ target.square.size }}
              </p>
              <p class="ipm__small">
                {{ t("imagePlacement.square.body", { size: target.square.size || target.source.width }) }}
              </p>
              <p class="ipm__small">
                {{ t("imagePlacement.square.format") }}: <strong>{{ (target.source.format || "").toUpperCase() }}</strong>
                · {{ t("imagePlacement.square.file") }}: <strong>{{ fileSize }}</strong>
              </p>
            </section>
            <p class="ipm__list-title">{{ t(`imagePlacement.listTitle.${device}`, { n: places.length }) }}</p>
            <PlaceList :items="placeItems" :current-index="placeIdx" :src="src" :focal="focal" variant="list" @select="pickPlace" />
          </nav>

          <section class="ipm__stage" :aria-label="stageTitle">
            <div class="ipm__stage-bar">
              <span>{{ stageTitle }}</span>
              <span class="ipm__stage-scale">{{ stageScale }}</span>
            </div>
            <p v-if="isProduct" class="ipm__summary">{{ summary }}</p>
            <div class="ipm__stage-scroll">
              <div
                :key="`${device}:${currentPlace ? currentPlace.key : ''}`"
                class="ipm__stagewrap"
                :class="device === 'mobile' ? 'ipm__phone' : 'ipm__browser'"
              >
                <div v-if="device === 'desktop'" class="ipm__chrome" aria-hidden="true">
                  <span class="ipm__chrome-dot" /><span class="ipm__chrome-dot" /><span class="ipm__chrome-dot" />
                  <span class="ipm__chrome-url">istoc.com</span>
                </div>
                <div class="ipm__sitebar" aria-hidden="true"><strong>iStoc</strong><span class="ipm__sitebar-search" /></div>
                <component
                  :is="currentContext"
                  v-if="currentContext && currentPlace"
                  :src="src"
                  :focal="focal"
                  :place="currentPlace"
                  :device="device"
                  :scale="scale"
                  :data="contextData"
                />
              </div>
            </div>
          </section>

          <section class="ipm__focal" :aria-labelledby="ids.focal">
            <h3 :id="ids.focal" class="ipm__h3">{{ t("imagePlacement.focal.title") }}</h3>
            <p class="ipm__help">{{ t("imagePlacement.focal.help") }}</p>
            <FocalEditor
              v-if="fp"
              :src="src"
              :image-ratio="imageRatio"
              :focal="focal"
              :frame="frame"
              :image-alt="t('imagePlacement.focal.imageAlt')"
              @set="onSet"
              @nudge="onNudge"
              @center="onCenter"
              @suggest="onSuggest"
              @natural="onNatural"
            />
            <p role="status" aria-live="polite" class="ipm__status">{{ statusText }}</p>
            <div v-if="fp && fp.conflict.value" class="ipm__alert">
              <span>{{ t("imagePlacement.status.conflict") }}</span>
              <button type="button" class="ipm__btn" @click="reload">{{ t("imagePlacement.reload") }}</button>
            </div>
            <p v-if="target && !canSave" class="ipm__note">{{ t("imagePlacement.status.cannotSave") }}</p>
            <section v-if="isProduct" class="ipm__why">
              <h4 class="ipm__h4">{{ t("imagePlacement.why.title") }}</h4>
              <p class="ipm__small">{{ t("imagePlacement.why.body") }}</p>
            </section>
            <div class="ipm__foot">
              <label class="ipm__check">
                <input type="checkbox" :checked="autoopen" @change="onAutoOpen" />
                {{ t("imagePlacement.autoOpen") }}
              </label>
              <div class="ipm__actions">
                <button type="button" class="ipm__btn ipm__btn--lg" @click="requestClose">{{ t("imagePlacement.cancel") }}</button>
                <button type="button" class="ipm__btn ipm__btn--primary" :disabled="primaryDisabled" @click="onSave">
                  {{ primaryLabel }}
                </button>
              </div>
            </div>
          </section>
        </div>

        <div v-else class="ipm__mobile">
          <div role="tablist" :aria-label="t('imagePlacement.tabs.label')" class="ipm__tabs" @keydown="onTabsKey">
            <button
              :id="ids.tabPreview"
              type="button"
              role="tab"
              class="ipm__tab"
              :aria-selected="mobileTab === 'preview' ? 'true' : 'false'"
              :aria-controls="ids.panelPreview"
              :tabindex="mobileTab === 'preview' ? 0 : -1"
              @click="mobileTab = 'preview'"
            >
              {{ t("imagePlacement.tabs.preview") }}
            </button>
            <button
              :id="ids.tabFocal"
              type="button"
              role="tab"
              class="ipm__tab"
              :aria-selected="mobileTab === 'focal' ? 'true' : 'false'"
              :aria-controls="ids.panelFocal"
              :tabindex="mobileTab === 'focal' ? 0 : -1"
              @click="mobileTab = 'focal'"
            >
              {{ t("imagePlacement.tabs.focal") }}
            </button>
          </div>
          <div class="ipm__mscroll">
            <div v-if="mobileTab === 'preview'" :id="ids.panelPreview" role="tabpanel" :aria-labelledby="ids.tabPreview" class="ipm__mpanel">
              <div v-if="devices.length > 1" role="group" :aria-label="t('imagePlacement.device.group')" class="ipm__seg">
                <button
                  v-for="d in devices"
                  :key="d"
                  type="button"
                  class="ipm__seg-btn"
                  :class="{ 'ipm__seg-btn--on': device === d }"
                  :aria-pressed="device === d ? 'true' : 'false'"
                  @click="pickDevice(d)"
                >
                  {{ t(`imagePlacement.device.${d}`) }}
                </button>
              </div>
              <PlaceList :items="placeItems" :current-index="placeIdx" :src="src" :focal="focal" variant="chips" @select="pickPlace" />
              <p class="ipm__stage-title">{{ stageTitle }}</p>
              <div class="ipm__mstage">
                <component
                  :is="currentContext"
                  v-if="currentContext && currentPlace"
                  :src="src"
                  :focal="focal"
                  :place="currentPlace"
                  :device="device"
                  :scale="scale"
                  :data="contextData"
                />
              </div>
            </div>
            <div v-else :id="ids.panelFocal" role="tabpanel" :aria-labelledby="ids.tabFocal" class="ipm__mpanel">
              <p class="ipm__help">{{ t("imagePlacement.focal.helpMobile") }}</p>
              <FocalEditor
                v-if="fp"
                compact
                :src="src"
                :image-ratio="imageRatio"
                :focal="focal"
                :frame="frame"
                :image-alt="t('imagePlacement.focal.imageAlt')"
                @set="onSet"
                @nudge="onNudge"
                @center="onCenter"
                @suggest="onSuggest"
                @natural="onNatural"
              />
              <p class="ipm__eyebrow">{{ t("imagePlacement.mobilePreviews") }}</p>
              <figure v-for="it in phoneItems" :key="it.id" class="ipm__fig">
                <span class="ipm__fig-box" :style="{ aspectRatio: String(it.place.ratio) }">
                  <img class="ctx-img" :src="src" :alt="t('imagePlacement.alt', { place: it.label })" :style="figStyle(it.place)" />
                </span>
                <figcaption class="ipm__figcap">
                  <span>{{ it.label }} · {{ it.place.ratioLabel }}</span>
                  <span v-if="!it.visibility.unknown">{{ chip(it.visibility) }}</span>
                </figcaption>
              </figure>
              <label class="ipm__check">
                <input type="checkbox" :checked="autoopen" @change="onAutoOpen" />
                {{ t("imagePlacement.autoOpen") }}
              </label>
            </div>
            <p role="status" aria-live="polite" class="ipm__status">{{ statusText }}</p>
            <div v-if="fp && fp.conflict.value" class="ipm__alert">
              <span>{{ t("imagePlacement.status.conflict") }}</span>
              <button type="button" class="ipm__btn" @click="reload">{{ t("imagePlacement.reload") }}</button>
            </div>
            <p v-if="target && !canSave" class="ipm__note">{{ t("imagePlacement.status.cannotSave") }}</p>
          </div>
          <div class="ipm__bar">
            <button type="button" class="ipm__btn ipm__btn--lg" @click="requestClose">{{ t("imagePlacement.cancel") }}</button>
            <button type="button" class="ipm__btn ipm__btn--primary" :disabled="primaryDisabled" @click="onSave">
              {{ primaryLabel }}
            </button>
          </div>
        </div>

        <div v-if="confirming" class="ipm__confirm-wrap">
          <div class="ipm__confirm" role="alertdialog" aria-modal="true" :aria-labelledby="ids.confirmTitle" :aria-describedby="ids.confirmBody">
            <h3 :id="ids.confirmTitle" class="ipm__h3">{{ t("imagePlacement.confirm.title") }}</h3>
            <p :id="ids.confirmBody" class="ipm__help">{{ t("imagePlacement.confirm.body") }}</p>
            <div class="ipm__actions">
              <button type="button" class="ipm__btn ipm__btn--lg" data-confirm-discard @click="discard">
                {{ t("imagePlacement.confirm.discard") }}
              </button>
              <button type="button" class="ipm__btn ipm__btn--primary" data-confirm-keep @click="keepEditing">
                {{ t("imagePlacement.confirm.keep") }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
  .ipm {
    --ipm-ink: #1d1c19;
    --ipm-ink-2: #3a3833;
    --ipm-ink-3: #4e4c45;
    --ipm-line: #e6e3dc;
    --ipm-soft: #faf9f7;
    --ipm-stage: #e9e7e1;
    --ipm-skel: #f4f3f0;
    --ipm-accent: #f5b800;
    --ipm-on-accent: #1a1a1a;
    --ipm-ok: #035c43;
    --ipm-cut: #7c2d12;
    --ipm-cut-bg: #fff7ed;
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: flex;
    padding: 16px;
    color: var(--ipm-ink);
    color-scheme: light;
    font-family: "DM Sans", system-ui, sans-serif;
  }
  .ipm--narrow { padding: 0; }
  .ipm :focus-visible { outline: 3px solid #1a1a1a; outline-offset: 2px; }
  .ipm__backdrop { position: absolute; inset: 0; background: rgba(29, 28, 25, 0.6); }
  .ipm__panel {
    position: relative;
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: #ffffff;
    border-radius: 18px;
    box-shadow: 0 24px 64px rgba(0, 0, 0, 0.3);
  }
  .ipm--narrow .ipm__panel { border-radius: 0; }
  .ipm__head { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 14px 20px; border-bottom: 1px solid var(--ipm-line); }
  .ipm__titles { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .ipm__title { margin: 0; font-size: 22px; line-height: 1.3; font-weight: 700; }
  .ipm__subtitle { margin: 0; font-size: 15px; color: var(--ipm-ink-2); overflow-wrap: anywhere; }
  .ipm__seg { display: flex; gap: 4px; padding: 4px; background: var(--ipm-skel); border-radius: 14px; }
  .ipm__seg-btn {
    min-height: 44px;
    padding: 0 14px;
    border: 0;
    border-radius: 10px;
    display: flex;
    align-items: center;
    gap: 8px;
    font: inherit;
    font-size: 15px;
    font-weight: 600;
    background: transparent;
    color: var(--ipm-ink-2);
    cursor: pointer;
  }
  .ipm__seg-btn--on { background: #ffffff; color: var(--ipm-ink); box-shadow: 0 1px 3px rgba(29, 28, 25, 0.18); }
  .ipm__close {
    width: 44px;
    height: 44px;
    flex-shrink: 0;
    border-radius: 12px;
    border: 1px solid var(--ipm-line);
    background: #ffffff;
    color: var(--ipm-ink);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
  }
  .ipm__notice { margin: 0; padding: 10px 20px; background: var(--ipm-cut-bg); color: var(--ipm-cut); font-size: 14px; font-weight: 600; }
  .ipm__grid { flex: 1; min-height: 0; display: grid; grid-template-columns: 250px minmax(0, 1fr) 330px; }
  .ipm__list { border-inline-end: 1px solid var(--ipm-line); padding: 16px 12px; display: flex; flex-direction: column; gap: 8px; overflow: auto; background: var(--ipm-soft); }
  .ipm__list-title { margin: 0 8px 4px; font-size: 13px; font-weight: 700; letter-spacing: 0.04em; color: var(--ipm-ink-3); }
  .ipm__square, .ipm__why { display: flex; flex-direction: column; gap: 6px; padding: 12px; border: 1px solid var(--ipm-line); border-radius: 12px; background: #ffffff; }
  .ipm__square-dims { margin: 0; font-size: 15px; font-weight: 700; }
  .ipm__h3 { margin: 0; font-size: 18px; font-weight: 700; }
  .ipm__h4 { margin: 0; font-size: 15px; font-weight: 700; }
  .ipm__small { margin: 0; font-size: 14px; line-height: 1.5; color: var(--ipm-ink-2); }
  .ipm__stage { min-width: 0; background: var(--ipm-stage); display: flex; flex-direction: column; overflow: hidden; }
  .ipm__stage-bar { display: flex; align-items: center; justify-content: space-between; padding: 10px 16px; background: var(--ipm-skel); border-bottom: 1px solid var(--ipm-line); font-size: 15px; font-weight: 600; }
  .ipm__stage-scale { font-size: 14px; font-weight: 400; color: var(--ipm-ink-2); }
  .ipm__summary { margin: 0; padding: 10px 16px; font-size: 15px; font-weight: 600; background: #ffffff; border-bottom: 1px solid var(--ipm-line); }
  .ipm__stage-scroll { flex: 1; min-height: 0; overflow: auto; display: flex; align-items: flex-start; justify-content: center; padding: 24px; }
  .ipm__stagewrap { background: #ffffff; overflow: hidden; animation: ipm-in 220ms cubic-bezier(0.2, 0.8, 0.2, 1); }
  .ipm__browser { width: 780px; border-radius: 10px; box-shadow: 0 8px 28px rgba(29, 28, 25, 0.18); }
  .ipm__phone { width: 410px; box-sizing: border-box; min-height: 640px; border: 10px solid #1d1c19; border-radius: 28px; box-shadow: 0 8px 28px rgba(29, 28, 25, 0.25); }
  .ipm__chrome { height: 30px; display: flex; align-items: center; gap: 6px; padding: 0 12px; background: var(--ipm-skel); }
  .ipm__chrome-dot { width: 9px; height: 9px; border-radius: 50%; background: #d3d0c8; }
  .ipm__chrome-url { margin-inline-start: 12px; flex: 1; height: 18px; border-radius: 6px; background: #ffffff; font-size: 11px; color: var(--ipm-ink-2); display: flex; align-items: center; padding: 0 8px; }
  .ipm__sitebar { height: 40px; display: flex; align-items: center; gap: 14px; padding: 0 18px; border-bottom: 1px solid #edeae3; }
  .ipm__sitebar-search { flex: 1; height: 22px; border-radius: 999px; background: var(--ipm-skel); }
  .ipm__focal { border-inline-start: 1px solid var(--ipm-line); padding: 18px; display: flex; flex-direction: column; gap: 14px; overflow: auto; }
  .ipm__help { margin: 0; font-size: 15px; line-height: 1.5; color: var(--ipm-ink-2); }
  .ipm__status { margin: 0; min-height: 20px; font-size: 14px; color: var(--ipm-ok); }
  .ipm__alert { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px; border: 1px solid var(--ipm-cut); border-radius: 10px; color: var(--ipm-cut); font-size: 14px; }
  .ipm__note { margin: 0; font-size: 14px; color: var(--ipm-cut); }
  .ipm__foot { margin-top: auto; display: flex; flex-direction: column; gap: 10px; }
  .ipm__check { display: flex; align-items: center; gap: 10px; min-height: 44px; font-size: 14px; color: var(--ipm-ink-2); }
  .ipm__check input { width: 24px; height: 24px; accent-color: #1a1a1a; } /* tasarım 22 px; axe target-size (2.5.8) için 24 */
  .ipm__actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .ipm__btn {
    min-height: 44px;
    padding: 0 14px;
    border-radius: 12px;
    border: 1px solid var(--ipm-line);
    background: #ffffff;
    font: inherit;
    font-size: 15px;
    font-weight: 600;
    color: var(--ipm-ink);
    cursor: pointer;
  }
  .ipm__btn--lg { min-height: 48px; font-size: 16px; }
  .ipm__btn--primary { min-height: 48px; border: 0; background: var(--ipm-accent); color: var(--ipm-on-accent); font-size: 16px; font-weight: 700; }
  .ipm__btn:disabled { cursor: not-allowed; opacity: 0.55; }
  .ipm__mobile { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  .ipm__tabs { display: flex; gap: 4px; margin: 12px 16px 0; padding: 4px; background: var(--ipm-skel); border-radius: 14px; }
  .ipm__tab { flex: 1; min-height: 44px; border: 0; border-radius: 10px; background: transparent; font: inherit; font-size: 15px; font-weight: 600; color: var(--ipm-ink-2); cursor: pointer; }
  .ipm__tab[aria-selected="true"] { background: #ffffff; color: var(--ipm-ink); box-shadow: 0 1px 3px rgba(29, 28, 25, 0.18); }
  .ipm__mscroll { flex: 1; min-height: 0; overflow: auto; padding: 16px 16px 24px; scroll-padding-bottom: 96px; display: flex; flex-direction: column; gap: 14px; }
  .ipm__mpanel { display: flex; flex-direction: column; gap: 14px; }
  .ipm__mstage { overflow: auto; border-radius: 10px; background: var(--ipm-stage); }
  .ipm__stage-title { margin: 0; font-size: 15px; font-weight: 600; }
  .ipm__eyebrow { margin: 0; font-size: 13px; font-weight: 700; letter-spacing: 0.04em; color: var(--ipm-ink-3); }
  .ipm__fig { margin: 0; display: flex; flex-direction: column; gap: 6px; }
  .ipm__fig-box { display: block; overflow: hidden; border-radius: 8px; background: var(--ipm-skel); }
  .ipm__figcap { display: flex; justify-content: space-between; gap: 8px; font-size: 14px; color: var(--ipm-ink-2); }
  .ipm__bar {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
    padding: 12px 16px calc(12px + env(safe-area-inset-bottom));
    background: #ffffff;
    border-top: 1px solid var(--ipm-line);
  }
  .ipm__confirm-wrap { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(29, 28, 25, 0.4); }
  .ipm__confirm { width: min(420px, calc(100% - 32px)); padding: 20px; border-radius: 16px; background: #ffffff; display: flex; flex-direction: column; gap: 12px; box-shadow: 0 16px 40px rgba(0, 0, 0, 0.3); }

  .ipm-enter-active { transition: opacity 200ms cubic-bezier(0.2, 0.8, 0.2, 1); }
  .ipm-enter-active .ipm__panel { transition: transform 200ms cubic-bezier(0.2, 0.8, 0.2, 1); }
  .ipm-leave-active { transition: opacity 160ms cubic-bezier(0.2, 0.8, 0.2, 1); }
  .ipm-leave-active .ipm__panel { transition: transform 160ms cubic-bezier(0.2, 0.8, 0.2, 1); }
  .ipm-enter-from, .ipm-leave-to { opacity: 0; }
  .ipm-enter-from .ipm__panel, .ipm-leave-to .ipm__panel { transform: scale(0.985); }
  @keyframes ipm-in {
    from { opacity: 0; transform: scale(0.985); }
    to { opacity: 1; transform: none; }
  }
  @media (prefers-reduced-motion: reduce) {
    .ipm-enter-active, .ipm-leave-active, .ipm-enter-active .ipm__panel, .ipm-leave-active .ipm__panel { transition: none; }
    .ipm__stagewrap { animation: none; }
  }
</style>
```

(The scroll body is not `position: sticky`-overlapped: the bottom bar is a flex sibling below `.ipm__mscroll`, so a focused element can never sit under it — SC 2.4.11 — and `scroll-padding-bottom` keeps keyboard scrolling clear.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/ahmet/Desktop/istoc/admin-panel/frontend && node --test src/components/media/preview/__tests__/focalEditor.test.js src/components/media/preview/__tests__/placeList.test.js src/components/media/preview/__tests__/imagePlacementModal.test.js src/components/media/preview/__tests__/previewAxe.test.js && npx eslint "src/components/media/preview/*.vue" src/components/media/preview/__tests__ && npx prettier --check "src/components/media/preview/*.vue"`
Expected: all pass (6 + 1 + 11 + 3 tests); 0 axe violations; ESLint/Prettier clean (`npx prettier --write` the three SFCs first if needed — Prettier will expand the one-line CSS rules; re-run the motion test afterwards, it matches declarations, not layout). If the modal transition regex in the motion test fails after Prettier, adjust the regex to the formatted output, not the CSS values.

- [ ] **Step 7: Stage (no commit — user approves commits)**

```bash
cd /Users/ahmet/Desktop/istoc/admin-panel && git add frontend/src/components/media/preview/FocalEditor.vue frontend/src/components/media/preview/PlaceList.vue frontend/src/components/media/preview/ImagePlacementModal.vue frontend/src/components/media/preview/__tests__/mountSfc.js frontend/src/components/media/preview/__tests__/fixtures/noopScrollLock.js frontend/src/components/media/preview/__tests__/focalEditor.test.js frontend/src/components/media/preview/__tests__/placeList.test.js frontend/src/components/media/preview/__tests__/imagePlacementModal.test.js frontend/src/components/media/preview/__tests__/previewAxe.test.js
```

---
### Task 9: Storefront applies the focal point (Wave 2 — after T1; payload contract from T4)

**Files:**
- Modify: `tradehubfront/src/lib/media/storeImage.ts`
- Modify: `tradehubfront/src/lib/media/storeImage.test.ts`
- Modify: `tradehubfront/src/alpine/index.ts` (after the `countryName` magic, ≈ line 18)
- Modify: `tradehubfront/src/components/seller/StoreHeader.ts` (video ≈ 302-306, main image ≈ 316-317, thumb images ≈ 390-394 and ≈ 400-404)
- Modify: `tradehubfront/src/pages/seller-shop.ts` (desktop logo `<img>` ≈ 131-134 only — the phone logo is `object-contain`, nothing is cut)
- Modify: `tradehubfront/src/components/manufacturers/ManufacturerList.ts` (gallery preview `<img>` ≈ 358-365)
- Create: `tradehubfront/src/utils/seller/section-registry.test.ts`
- Create: `tradehubfront/src/lib/media/focalBindings.test.ts`

**Interfaces:**
- Consumes: `STORE_PLACE_SIZES` from `./placements.gen` (Task 1); body `{src, srcset, width, height, focal?: {x, y}}` (Task 4; `srcset` may be `""` when only a focal exists).
- Produces: `storeImageFocal(media: unknown): StoreImageFocal | null`, `storeImgPosition(media: unknown): string | null` (`"78% 45%"`), `StoreImageMedia.focal?`, `storeImgAttrs(...)` now appends ` style="object-position:X% Y%"` when a focal exists (with or without `srcset`); Alpine magic `$focalPos(media) → string` (`""` when no focal, so `:style="{ objectPosition: $focalPos(x) }"` removes the property).
- Not touched on purpose: `components/seller/{CompanyInfo,Gallery,CategoryProductListing,HeroBanner}.ts` — they are only re-exported from `components/seller/index.ts` and fed by `data/seller/mockData.ts`; no page renders them (grep 2026-10-01). See the spec-gap list at the end.

- [ ] **Step 1: Write the failing tests**

Append to `src/lib/media/storeImage.test.ts` (extend the import list with `storeImageFocal, storeImgPosition`):

```ts
describe("odak noktası (2026-10-01)", () => {
  const WITH_FOCAL = { ...LOGO, focal: { x: 0.78, y: 0.45 } };
  const FOCAL_ONLY = { src: "/files/c2/a.webp", srcset: "", width: 0, height: 0, focal: { x: 0.78, y: 0.45 } };

  it("storeImageFocal doğrular, kelepçeler, yoksa null", () => {
    expect(storeImageFocal(WITH_FOCAL)).toEqual({ x: 0.78, y: 0.45 });
    expect(storeImageFocal({ focal: { x: 2, y: -1 } })).toEqual({ x: 1, y: 0 });
    expect(storeImageFocal({ focal: { x: "a", y: 0.5 } })).toBeNull();
    expect(storeImageFocal(LOGO)).toBeNull();
    expect(storeImageFocal(null)).toBeNull();
  });

  it("storeImgPosition kayan nokta artığı bırakmaz", () => {
    expect(storeImgPosition(WITH_FOCAL)).toBe("78% 45%");
    expect(storeImgPosition({ focal: { x: 0.123, y: 1 } })).toBe("12.3% 100%");
    expect(storeImgPosition(LOGO)).toBeNull();
  });

  it("türevli gövdede srcset + object-position", () => {
    const html = storeImgAttrs(WITH_FOCAL, "/files/raw.png", "galleryMain");
    expect(html).toContain('srcset="');
    expect(html).toContain(' style="object-position:78% 45%"');
  });

  it("yalnız odak gövdesi: ham adres + object-position, srcset yok", () => {
    const html = storeImgAttrs(FOCAL_ONLY, "/files/c2/a.webp", "galleryMain");
    expect(html).toContain('src="/files/c2/a.webp"');
    expect(html).toContain(' style="object-position:78% 45%"');
    expect(html).not.toContain("srcset");
  });

  it("odak yoksa style yazılmaz (bugünkü davranış)", () => {
    expect(storeImgAttrs(LOGO, "/x.png", "favoritesLogo")).not.toContain("style=");
    expect(storeImgAttrs(null, "/x.png", "favoritesLogo")).not.toContain("style=");
  });

  it("STORE_IMAGE_SIZES değerleri değişmedi (beşi üretilmiş dosyadan geliyor)", () => {
    expect(STORE_IMAGE_SIZES).toMatchObject({
      galleryMain: "(min-width: 768px) 500px, 100vw",
      galleryThumb: "120px",
      manufacturerGallery: "(min-width: 1024px) 220px, 165px",
      shopHeaderLogoDesktop: "140px",
      shopHeaderLogoMobile: "48px",
      productSellerPanelLogo: "30px",
      brandOwnerLogo: "16px",
    });
  });
});
```

Create `src/utils/seller/section-registry.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { renderDynamicSections, type LayoutConfig } from "./section-registry";

const URL = "/files/c2/ozgen-banner.webp";

function layout(media: Record<string, unknown>): LayoutConfig {
  return {
    sections: [
      {
        type: "hero_banner",
        order: 1,
        enabled: true,
        settings: {
          mode: "static",
          slides: [{ id: "s1", image: URL, title: "", subtitle: "", ctaText: "", ctaLink: "" }],
        },
      },
    ],
    image_media: media,
  } as LayoutConfig;
}

describe("vitrin slaytı odak noktası", () => {
  it("odak kaydı olan banner'da object-position basılır", () => {
    const html = renderDynamicSections(
      layout({ [URL]: { src: URL, srcset: "", width: 0, height: 0, focal: { x: 0.78, y: 0.45 } } })
    );
    expect(html).toContain('style="object-position:78% 45%"');
  });

  it("odak kaydı olmayanda object-position yok (ortadan kırpılır)", () => {
    expect(renderDynamicSections(layout({}))).not.toContain("object-position");
  });
});
```

Create `src/lib/media/focalBindings.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import alpineIndex from "../../alpine/index.ts?raw";
import storeHeader from "../../components/seller/StoreHeader.ts?raw";
import manufacturerList from "../../components/manufacturers/ManufacturerList.ts?raw";
import sellerShop from "../../pages/seller-shop.ts?raw";

describe("Alpine görsellerinde odak bağlaması", () => {
  it("$focalPos sihri kayıtlı", () => {
    expect(alpineIndex).toMatch(/Alpine\.magic\(\s*"focalPos"/);
  });
  it("mağaza başlığı ana medya, video kapağı ve küçük resimler", () => {
    expect(storeHeader).toContain("$focalPos(current.src_media)");
    expect(storeHeader).toContain("$focalPos(current.poster_media)");
    expect(storeHeader).toContain("$focalPos(item.src_media)");
    expect(storeHeader).toContain("$focalPos(item.poster_media)");
  });
  it("masaüstü dükkan logosu ve üretici galerisi", () => {
    expect(sellerShop).toContain("$focalPos(seller?.logo_media)");
    expect(manufacturerList).toContain("$focalPos(seller.gallery_images_media && seller.gallery_images_media[activeIdx])");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/ahmet/Desktop/istoc/tradehubfront && npx vitest run src/lib/media/storeImage.test.ts src/utils/seller/section-registry.test.ts src/lib/media/focalBindings.test.ts 2>&1 | tail -8`
Expected: FAIL — `storeImageFocal is not a function` / `expected … to contain 'style="object-position:78% 45%"'` / `$focalPos` not found.

- [ ] **Step 3: Implement `storeImage.ts`**

1. Add below the existing import: `import { STORE_PLACE_SIZES } from "./placements.gen";`
2. Add the focal type and extend the media interface:

```ts
/** Satıcının önizleme penceresinde seçtiği odak noktası, 0-1 (`Media Crop Intent`). */
export interface StoreImageFocal {
  x: number;
  y: number;
}
```
and add `focal?: StoreImageFocal;` as the last field of `StoreImageMedia`.

3. Replace the `STORE_IMAGE_SIZES` object so the five shared keys come from the generated file (values unchanged):

```ts
export const STORE_IMAGE_SIZES = {
  /** Ürün detay satıcı paneli: `w-10 h-10` + çerçeve + `p-1` → 30 px. */
  productSellerPanelLogo: "30px",
  /** Ürün detay Tedarikçi sekmesi: 64×64. */
  productSupplierLogo: "64px",
  /** Mağaza sayfası yan kart: `w-12 h-12` + `p-1` → 38 px. */
  storefrontSidebarLogo: "38px",
  /** Dükkan iletişim formu (56 px yuvarlak, p-1 → 46 px) ve yan mini kart (36 px). */
  shopContactLogo: "46px",
  shopSidebarLogo: "36px",
  /** Üretici hero kartı 116 px, liste kartı ~40 px. */
  manufacturerHeroLogo: "116px",
  manufacturerListLogo: "50px",
  /** Favoriler satıcı satırı: `size-10` + p-1 → 30 px. */
  favoritesLogo: "30px",
  /** Marka sayfası sahip rozeti: 16 px. */
  brandOwnerLogo: "16px",
  /**
   * Önizleme penceresiyle ORTAK yerler — galleryMain, galleryThumb,
   * manufacturerGallery, shopHeaderLogoDesktop, shopHeaderLogoMobile.
   * Tek kaynak `placements.json → preview_places`; elle yazılmaz.
   */
  ...STORE_PLACE_SIZES,
} as const;
```

4. Add after `toStoreImageMedia`:

```ts
const clamp01 = (v: number): number => Math.min(1, Math.max(0, v));

/** `focal` alanını doğrula; yoksa ya da bozuksa `null` (vitrin ortadan kırpar). */
export function storeImageFocal(value: unknown): StoreImageFocal | null {
  if (!value || typeof value !== "object") return null;
  const f = (value as Record<string, unknown>).focal;
  if (!f || typeof f !== "object") return null;
  const x = Number((f as Record<string, unknown>).x);
  const y = Number((f as Record<string, unknown>).y);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  return { x: clamp01(x), y: clamp01(y) };
}

/** CSS `object-position` — admin önizlemesiyle AYNI biçim (`geometry.js::objectPosition`). */
export function storeImgPosition(media: unknown): string | null {
  const f = storeImageFocal(media);
  if (!f) return null;
  const p = (v: number): string => `${Math.round(v * 1000) / 10}%`;
  return `${p(f.x)} ${p(f.y)}`;
}
```

Inside `toStoreImageMedia`, change the final return to keep the focal:

```ts
  const focal = storeImageFocal(v);
  return {
    src,
    srcset,
    width: Number(v.width) || 0,
    height: Number(v.height) || 0,
    ...(focal ? { focal } : {}),
  };
```

5. Replace the body of `storeImgAttrs` with:

```ts
  const pos = storeImgPosition(media);
  const style = pos ? ` style="object-position:${escapeHtml(pos)}"` : "";
  const m = toStoreImageMedia(media);
  if (!m) return ` src="${escapeHtml(sanitizeUrl(fallbackUrl ?? ""))}"${style}`;
  const srcset = safeSrcset(m.srcset);
  if (!srcset) return ` src="${escapeHtml(sanitizeUrl(fallbackUrl ?? ""))}"${style}`;
  // srcset + sizes, src'den ÖNCE: tarayıcı kaynak seçimini tek geçişte yapsın.
  return (
    ` srcset="${escapeHtml(srcset)}" sizes="${escapeHtml(sizesFor(placement))}"` +
    ` src="${escapeHtml(sanitizeUrl(m.src))}"${style}`
  );
```

- [ ] **Step 4: Register `$focalPos` and bind it**

`src/alpine/index.ts` — add the import `import { storeImgPosition } from "../lib/media/storeImage";` next to the other imports and, after the `countryName` magic:

```ts
// Odak noktası: `*_media.focal` → CSS object-position ("78% 45%"); kayıt yoksa ""
// (Alpine boş değeri yazmaz → vitrin ortadan kırpar, bugünkü davranış).
Alpine.magic("focalPos", () => (media: unknown) => storeImgPosition(media) ?? "");
```

`src/components/seller/StoreHeader.ts`:
- on the `<video x-ref="headerVideo" …>` element add `:style="{ objectPosition: $focalPos(current.poster_media) }"`;
- on the main `<img :srcset="(current.src_media && …" …>` add `:style="{ objectPosition: $focalPos(current.src_media) }"`;
- on the thumbnail image `<img :srcset="(item.src_media && …" sizes="120px" …>` add `:style="{ objectPosition: $focalPos(item.src_media) }"`;
- on the video-poster thumbnail `<img :srcset="(item.poster_media && …" sizes="120px" …>` add `:style="{ objectPosition: $focalPos(item.poster_media) }"`.

`src/pages/seller-shop.ts`, desktop logo `<img x-show="seller?.logo" … sizes="140px" …>` — replace its `:style` with:

```ts
                     :style="'border-radius:' + (seller?.logo_radius || '8') + 'px;' + ($focalPos(seller?.logo_media) ? 'object-position:' + $focalPos(seller?.logo_media) : '')" />
```

`src/components/manufacturers/ManufacturerList.ts`, gallery preview `<img …sizes="(min-width: 1024px) 220px, 165px" …>` — add:

```ts
                      :style="{ objectPosition: $focalPos(seller.gallery_images_media && seller.gallery_images_media[activeIdx]) }"
```

(`section-registry.ts` needs no edit: its hero uses `storeImgAttrs`, which now writes the style.)

- [ ] **Step 5: Run tests and checks**

Run: `cd /Users/ahmet/Desktop/istoc/tradehubfront && npx vitest run src/lib/media src/utils/seller src/components/manufacturers 2>&1 | tail -6 && npx tsc --noEmit && npm run check:dup && npx eslint src/lib/media/storeImage.ts src/alpine/index.ts src/components/seller/StoreHeader.ts src/pages/seller-shop.ts src/components/manufacturers/ManufacturerList.ts src/utils/seller/section-registry.test.ts src/lib/media/focalBindings.test.ts`
Expected: all vitest files pass (existing `storeImage.test.ts` cases unchanged); `tsc` 0 errors; `check:dup` OK (`STORE_PLACE_SIZES`, `storeImageFocal`, `storeImgPosition`, `StoreImageFocal` are new unique names); ESLint clean.

- [ ] **Step 6: Stage (no commit — user approves commits)**

```bash
cd /Users/ahmet/Desktop/istoc/tradehubfront && git add src/lib/media/storeImage.ts src/lib/media/storeImage.test.ts src/alpine/index.ts src/components/seller/StoreHeader.ts src/pages/seller-shop.ts src/components/manufacturers/ManufacturerList.ts src/utils/seller/section-registry.test.ts src/lib/media/focalBindings.test.ts
```

---

### Task 10: Entry button with badge, and the launcher (Wave 3 — after T5, T6)

**Files:**
- Create: `admin-panel/frontend/src/components/media/preview/ImagePlacementButton.vue`
- Create: `admin-panel/frontend/src/composables/usePlacementLauncher.js`
- Create: `admin-panel/frontend/src/components/media/preview/__tests__/placementButton.test.js`
- Create: `admin-panel/frontend/src/composables/__tests__/placementLauncher.test.js`

**Interfaces:**
- Consumes: `cutPlaceCount` (T6), `messages` (T6), `getImageDimensions`, `getPreviewPrefs` (T5).
- Produces:
  - `<ImagePlacementButton :file-url :slot-key :dims? :compact? :load-dims? @open({fileUrl, slotKey, trigger})>` — yellow primary button "Nerelerde görünecek?" (48 px; `compact` = full-width 44 px for tight cards) + badge "N yerde kenarlar kesiliyor" (text + icon) when `cutPlaceCount > 0`. Root carries `data-placement-url="<fileUrl>"` so the launcher can find the button for focus return.
  - `usePlacementLauncher({getPrefs?}) -> { state: {open, fileUrl, slotKey, fileName, context, returnFocus, auto}, show({fileUrl, slotKey, context?, trigger?}), afterUpload({selected, fileUrl, slotKey, context?}) -> Promise<boolean>, hide() }`. `afterUpload` opens only when `selected === 1` and the server preference is not off; its `returnFocus` is a function that finds `[data-placement-url="<url>"] .ipb__btn`.
  - Host pattern used by Tasks 11–12:

```vue
<ImagePlacementModal
  v-if="placement.state.open"
  v-model:open="placement.state.open"
  :file-url="placement.state.fileUrl"
  :slot-key="placement.state.slotKey"
  :file-name="placement.state.fileName"
  :context="placement.state.context"
  :return-focus="placement.state.returnFocus"
/>
```

- [ ] **Step 1: Write the failing tests**

`src/composables/__tests__/placementLauncher.test.js`:

```js
import assert from "node:assert/strict";
import { test } from "node:test";

import { usePlacementLauncher } from "../usePlacementLauncher.js";

const URL = "/files/c2/ozgen-banner.webp";

test("toplu yüklemede açılmaz", async () => {
  const l = usePlacementLauncher({ getPrefs: async () => ({ autoopen: true }) });
  assert.equal(await l.afterUpload({ selected: 3, fileUrl: URL, slotKey: "company.cover_image" }), false);
  assert.equal(l.state.open, false);
});

test("tek dosyada açılır; dosya adı çözülür; odak dönüşü fonksiyonla", async () => {
  const l = usePlacementLauncher({ getPrefs: async () => ({ autoopen: true }) });
  assert.equal(await l.afterUpload({ selected: 1, fileUrl: URL, slotKey: "company.cover_image" }), true);
  assert.equal(l.state.open, true);
  assert.equal(l.state.auto, true);
  assert.equal(l.state.fileName, "ozgen-banner.webp");
  assert.equal(typeof l.state.returnFocus, "function");
});

test("tercih kapalıysa açılmaz", async () => {
  const l = usePlacementLauncher({ getPrefs: async () => ({ autoopen: false }) });
  assert.equal(await l.afterUpload({ selected: 1, fileUrl: URL, slotKey: "company.cover_image" }), false);
});

test("tercih okunamazsa varsayılan açık", async () => {
  const l = usePlacementLauncher({
    getPrefs: async () => {
      throw new Error("offline");
    },
  });
  assert.equal(await l.afterUpload({ selected: 1, fileUrl: URL, slotKey: "product.image" }), true);
});

test("düğmeden açılış tetikleyiciyi saklar; adres yoksa açılmaz", () => {
  const l = usePlacementLauncher();
  const trigger = { focus() {} };
  assert.equal(l.show({ fileUrl: "", slotKey: "product.image" }), false);
  assert.equal(l.show({ fileUrl: URL, slotKey: "product.image", trigger, context: { productName: "Fırça" } }), true);
  assert.equal(l.state.returnFocus, trigger);
  assert.deepEqual(l.state.context, { productName: "Fırça" });
  l.hide();
  assert.equal(l.state.open, false);
});
```

`src/components/media/preview/__tests__/placementButton.test.js`:

```js
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { after, before, test } from "node:test";
import vue from "@vitejs/plugin-vue";
import { createServer } from "vite";
import { createSSRApp, h } from "vue";
import { createI18n } from "vue-i18n";
import { renderToString } from "@vue/server-renderer";

import messages from "../../../../lib/media/preview/messages.js";
import { describe as describeAxe, scanHtml } from "../../a11y/axeHarness.js";

const frontendRoot = fileURLToPath(new URL("../../../../..", import.meta.url));
let server;
before(async () => {
  server = await createServer({
    configFile: false,
    root: frontendRoot,
    logLevel: "silent",
    plugins: [vue()],
    resolve: {
      alias: [
        { find: /^@\/utils\/api$/, replacement: `${frontendRoot}/src/components/media/__tests__/fixtures/apiMock.js` },
        { find: "@", replacement: `${frontendRoot}/src` },
      ],
    },
    server: { middlewareMode: true },
    appType: "custom",
  });
});
after(async () => server?.close());

async function render(props, locale = "tr") {
  const { default: C } = await server.ssrLoadModule("/src/components/media/preview/ImagePlacementButton.vue");
  const app = createSSRApp({ render: () => h(C, props) });
  app.use(createI18n({ legacy: false, locale, fallbackLocale: "tr", messages }));
  return renderToString(app);
}

test("Özgen banner'ı: düğme + '4 yerde kenarlar kesiliyor' rozeti", async () => {
  const html = await render({
    fileUrl: "/files/c2/ozgen-banner.webp",
    slotKey: "company.cover_image",
    dims: { width: 2000, height: 408 },
  });
  assert.match(html, /Nerelerde görünecek\?/);
  assert.match(html, /4 yerde kenarlar kesiliyor/);
  assert.match(html, /data-placement-url="\/files\/c2\/ozgen-banner\.webp"/);
  const { violations } = await scanHtml(html);
  assert.equal(violations.length, 0, describeAxe(violations));
});

test("kare ürün görselinde rozet yok", async () => {
  const html = await render({ fileUrl: "/files/p.webp", slotKey: "product.image", dims: { width: 1000, height: 1000 } });
  assert.doesNotMatch(html, /kenarlar kesiliyor/);
});

test("İngilizce tekil/çoğul", async () => {
  const html = await render(
    { fileUrl: "/files/logo.png", slotKey: "seller.logo", dims: { width: 400, height: 200 } },
    "en"
  );
  assert.match(html, /Edges cut in 1 place\b/);
  assert.doesNotMatch(html, /Edges cut in 1 places/);
});

test("adres yoksa düğme devre dışı", async () => {
  const html = await render({ fileUrl: "", slotKey: "product.image" });
  assert.match(html, /<button[^>]*disabled/);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/ahmet/Desktop/istoc/admin-panel/frontend && node --test src/composables/__tests__/placementLauncher.test.js src/components/media/preview/__tests__/placementButton.test.js 2>&1 | tail -4`
Expected: FAIL — module / file not found.

- [ ] **Step 3: Implement `usePlacementLauncher.js`**

```js
import { shallowReactive } from "vue";

/**
 * Önizleme penceresini açan taraf (spec §4.4). Ekranlar bunu bir kez kurar,
 * `ImagePlacementButton@open` → `show`, yükleme bitince → `afterUpload`.
 * `shallowReactive`: `returnFocus` bir DOM öğesi ya da fonksiyon; derin
 * proxy'ye sokulmamalı.
 */
async function defaultPrefs() {
  const m = await import("../lib/media/preview/previewApi.js");
  return m.getPreviewPrefs();
}

function fileNameOf(url) {
  const last = String(url || "").split("/").pop() || "";
  try {
    return decodeURIComponent(last);
  } catch {
    return last;
  }
}

export function usePlacementLauncher({ getPrefs = defaultPrefs } = {}) {
  const state = shallowReactive({
    open: false,
    fileUrl: "",
    slotKey: "",
    fileName: "",
    context: {},
    returnFocus: null,
    auto: false,
  });

  function show({ fileUrl, slotKey, context = {}, trigger = null, auto = false } = {}) {
    if (!fileUrl || !slotKey) return false;
    Object.assign(state, {
      open: true,
      fileUrl,
      slotKey,
      context,
      returnFocus: trigger,
      auto,
      fileName: fileNameOf(fileUrl),
    });
    return true;
  }

  /** Yalnız TEK dosya seçilip yüklendiyse ve kullanıcı tercihi kapalı değilse açar. */
  async function afterUpload({ selected, fileUrl, slotKey, context = {} } = {}) {
    if (selected !== 1 || !fileUrl || !slotKey) return false;
    let prefs = { autoopen: true };
    try {
      prefs = (await getPrefs()) || prefs;
    } catch {
      // Tercih okunamadı: varsayılan AÇIK (spec §4.4).
    }
    if (prefs.autoopen === false) return false;
    const trigger = () =>
      document.querySelector(`[data-placement-url="${CSS.escape(fileUrl)}"] .ipb__btn`);
    return show({ fileUrl, slotKey, context, trigger, auto: true });
  }

  function hide() {
    state.open = false;
  }

  return { state, show, afterUpload, hide };
}
```

- [ ] **Step 4: Implement `ImagePlacementButton.vue`**

```vue
<script setup>
  import { computed, onMounted, ref, watch } from "vue";
  import { useI18n } from "vue-i18n";

  import { cutPlaceCount } from "@/lib/media/preview/places.js";
  import messages from "@/lib/media/preview/messages.js";

  /**
   * "Nerelerde görünecek?" — her görselin altında kalıcı giriş (pano 3).
   * Rozet: kenarı kesilen FARKLI yer sayısı; ölçü bilinmiyorsa rozet çıkmaz.
   */
  const props = defineProps({
    fileUrl: { type: String, default: "" },
    slotKey: { type: String, required: true },
    /** `{width, height}` biliniyorsa verin; yoksa `seller_media.get_dimensions` sorulur. */
    dims: { type: Object, default: null },
    compact: { type: Boolean, default: false },
    /** Test/özel kullanım için ölçü okuyucu; varsayılan `previewApi.getImageDimensions`. */
    loadDims: { type: Function, default: null },
  });
  const emit = defineEmits(["open"]);
  const { t } = useI18n({ messages });

  const btn = ref(null);
  const fetched = ref(null);
  const size = computed(() => props.dims || fetched.value);
  const cutCount = computed(() => {
    const s = size.value;
    return s && s.width > 0 && s.height > 0 ? cutPlaceCount(props.slotKey, s.width / s.height) : 0;
  });

  async function refresh() {
    fetched.value = null;
    if (props.dims || !props.fileUrl) return;
    try {
      const loader =
        props.loadDims || (await import("@/lib/media/preview/previewApi.js")).getImageDimensions;
      const d = await loader(props.fileUrl);
      if (d?.width > 0 && d?.height > 0) fetched.value = { width: d.width, height: d.height };
    } catch {
      // Ölçü okunamadı: rozet gösterilmez, düğme çalışmaya devam eder.
    }
  }
  onMounted(refresh);
  watch(() => props.fileUrl, refresh);

  function onClick() {
    emit("open", { fileUrl: props.fileUrl, slotKey: props.slotKey, trigger: btn.value });
  }
  defineExpose({ focus: () => btn.value?.focus() });
</script>

<template>
  <div class="ipb" :class="{ 'ipb--compact': compact }" :data-placement-url="fileUrl">
    <button ref="btn" type="button" class="ipb__btn" :disabled="!fileUrl" @click="onClick">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></svg>
      {{ t("imagePlacement.button") }}
    </button>
    <span v-if="cutCount > 0" class="ipb__badge">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true" focusable="false"><circle cx="6" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M20 4L8.1 15.9M14.5 14.5L20 20M8.1 8.1L12 12" /></svg>
      {{ t("imagePlacement.badge", { n: cutCount }, cutCount) }}
    </span>
  </div>
</template>

<style scoped>
  .ipb { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .ipb__btn {
    min-height: 48px;
    padding: 0 16px;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    border: 0;
    border-radius: 12px;
    background: #f5b800;
    color: #1a1a1a;
    font: inherit;
    font-size: 15px;
    font-weight: 700;
    cursor: pointer;
  }
  .ipb--compact .ipb__btn { width: 100%; min-height: 44px; justify-content: center; font-size: 14px; padding: 0 10px; }
  .ipb__btn:disabled { cursor: not-allowed; opacity: 0.55; }
  .ipb__btn:focus-visible { outline: 3px solid #1a1a1a; outline-offset: 2px; }
  .ipb__badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    border-radius: 999px;
    background: #fff7ed;
    color: #7c2d12;
    font-size: 12px;
    font-weight: 600;
  }
</style>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/ahmet/Desktop/istoc/admin-panel/frontend && node --test src/composables/__tests__/placementLauncher.test.js src/components/media/preview/__tests__/placementButton.test.js && npx eslint src/composables/usePlacementLauncher.js src/components/media/preview/ImagePlacementButton.vue && npx prettier --check src/composables/usePlacementLauncher.js src/components/media/preview/ImagePlacementButton.vue`
Expected: 5 + 4 tests pass, axe 0 violations, lint/format clean.

- [ ] **Step 6: Stage (no commit — user approves commits)**

```bash
cd /Users/ahmet/Desktop/istoc/admin-panel && git add frontend/src/components/media/preview/ImagePlacementButton.vue frontend/src/composables/usePlacementLauncher.js frontend/src/components/media/preview/__tests__/placementButton.test.js frontend/src/composables/__tests__/placementLauncher.test.js
```

---
### Task 11: Product entry points in `ListingFormView.vue` (Wave 4 — after T8, T10)

**Files:**
- Modify: `admin-panel/frontend/src/views/seller/ListingFormView.vue` (primary image ≈ 511-529, gallery card ≈ 1083-1170, modal ≈ 3163-3173, script ≈ 3217-3279, uploads ≈ 4405-4521)
- Create: `admin-panel/frontend/src/views/seller/__tests__/listingPlacementWiring.test.js`

**Interfaces:**
- Consumes: `ImagePlacementButton` (T10), `usePlacementLauncher` (T10), `ImagePlacementModal` (T8, host pattern in T10).
- Produces: product images open the window from a yellow button under the main image and under each gallery card; a single-file upload (main image, row replace, or adding exactly one gallery file) auto-opens the window unless the user turned it off. `CropStudioModal` and `openCrop` disappear from this view (spec §4.4: Crop Studio stays only for slots that really crop; `product.image` is "kırpılmaz").

- [ ] **Step 1: Write the failing test**

`src/views/seller/__tests__/listingPlacementWiring.test.js`:

```js
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const view = readFileSync(new URL("../ListingFormView.vue", import.meta.url), "utf8");
const body = (name) => {
  const m = view.match(new RegExp(`async function ${name}\\([\\s\\S]*?\\n  }\\n`));
  assert.ok(m, `${name} bulunamadı`);
  return m[0];
};

test("Kırp kısayolu ve Crop Studio bu ekrandan kalktı", () => {
  assert.doesNotMatch(view, /openCrop\(/);
  assert.doesNotMatch(view, /CropStudioModal/);
  assert.doesNotMatch(view, /media\.actions\.crop/);
});

test("ana görsel ve her galeri kartında 'Nerelerde görünecek?'", () => {
  const buttons = view.match(/<ImagePlacementButton[\s\S]*?\/>/g) || [];
  assert.equal(buttons.length, 2);
  for (const b of buttons) {
    assert.match(b, /slot-key="product\.image"/);
    assert.match(b, /@open="openPlacement"/);
  }
  assert.match(buttons[1], /compact/);
});

test("pencere bir kez barındırılıyor", () => {
  assert.equal((view.match(/<ImagePlacementModal/g) || []).length, 1);
  assert.match(view, /v-model:open="placement\.state\.open"/);
  assert.match(view, /:return-focus="placement\.state\.returnFocus"/);
});

test("tek dosyada otomatik açılış, toplu yüklemede seçilen sayı geçer", () => {
  assert.match(body("uploadImage"), /placement\.afterUpload\(\{\s*selected: 1,/);
  assert.match(body("uploadImageRow"), /placement\.afterUpload\(\{\s*selected: 1,/);
  assert.match(body("addImageRows"), /placement\.afterUpload\(\{\s*selected: files\.length,/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/ahmet/Desktop/istoc/admin-panel/frontend && node --test src/views/seller/__tests__/listingPlacementWiring.test.js 2>&1 | tail -5`
Expected: FAIL — `openCrop(` still present, 0 `ImagePlacementButton`.

- [ ] **Step 3: Template edits**

(a) Replace the comment `<!-- Kırpma kısayolu: … (bkz. cropIntentApi). -->` and the `<button v-if="form.primary_image" … @click="openCrop(form.primary_image)" …>…{{ t("media.actions.crop") }}</button>` block under the primary image with:

```vue
                    <!-- "Nerelerde görünecek?" (spec 2026-10-01 §4.4): görselin vitrinde
                         göründüğü her yer + odak noktası. Eski "Kırp" kısayolunun yerini
                         aldı; ürün görseli kare ve contain gösterildiği için kırpılmaz. -->
                    <ImagePlacementButton
                      v-if="form.primary_image"
                      :file-url="form.primary_image"
                      slot-key="product.image"
                      @open="openPlacement"
                    />
```

(b) Gallery card. Change the opening of the `v-for` card from

```vue
                  <div
                    v-for="(img, idx) in childData.listing_images"
                    :key="img._uploadKey || idx"
                    class="relative group aspect-square rounded-xl overflow-hidden border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/3"
                  >
```

to

```vue
                  <div
                    v-for="(img, idx) in childData.listing_images"
                    :key="img._uploadKey || idx"
                    class="flex flex-col gap-2"
                  >
                    <div
                      class="relative group aspect-square rounded-xl overflow-hidden border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/3"
                    >
```

remove the crop icon button inside the hover overlay:

```vue
                      <button
                        type="button"
                        class="bg-white/20 rounded-lg p-1.5 hover:bg-white/30"
                        :title="t('media.actions.crop')"
                        @click="openCrop(childData.listing_images[idx].image)"
                      >
                        <AppIcon name="crop" :size="14" class="text-white" />
                      </button>
```

and close the new wrapper right after the alt-text input (before `<!-- Ekle butonu — drop-target …`):

```vue
                    <input
                      v-model="img.alt_text"
                      type="text"
                      class="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[10px] px-2 py-1 border-0 outline-none placeholder-gray-400 opacity-0 group-hover:opacity-100 transition-opacity"
                      :placeholder="t('listingForm.altTextPlaceholder')"
                    />
                    </div>
                    <ImagePlacementButton
                      v-if="img.image"
                      compact
                      :file-url="img.image"
                      slot-key="product.image"
                      @open="openPlacement"
                    />
                  </div>
```

(c) Replace the `<!-- Crop Studio — … -->` comment and the `<CropStudioModal … />` block with:

```vue
  <!-- Görsel önizleme penceresi — tek örnek; düğmeler ve tek-dosya yüklemesi açar. -->
  <ImagePlacementModal
    v-if="placement.state.open"
    v-model:open="placement.state.open"
    :file-url="placement.state.fileUrl"
    :slot-key="placement.state.slotKey"
    :file-name="placement.state.fileName"
    :context="placement.state.context"
    :return-focus="placement.state.returnFocus"
  />
```

- [ ] **Step 4: Script edits**

(a) Replace

```js
  // Kırpma stüdyosu ağır (canvas + geometri) — yalnız Kırp'a basılınca iner.
  const CropStudioModal = defineAsyncComponent(
    () => import("@/components/media/crop/CropStudioModal.vue")
  );
```

with

```js
  // Görsel önizleme penceresi bağlam şablonlarını taşır — yalnız açılınca insin.
  const ImagePlacementModal = defineAsyncComponent(
    () => import("@/components/media/preview/ImagePlacementModal.vue")
  );
```

and add to the import block: `import ImagePlacementButton from "@/components/media/preview/ImagePlacementButton.vue";` and `import { usePlacementLauncher } from "@/composables/usePlacementLauncher";`.

(b) Delete the whole "Crop Studio kısayolu" section: the comment block, `cropOpen`, `cropBusy`, `cropSource`, `cropAssetName` refs and `async function openCrop(url) { … }`. In its place add:

```js
  // ── Görsel önizleme penceresi (spec 2026-10-01 §4.4) ──────────────────
  const placement = usePlacementLauncher();
  function placementContext() {
    const fiyat = Number(form.selling_price || form.base_price || 0);
    return {
      storeName: auth.user?.admin_seller_profile?.seller_name || "",
      productName: form.title || "",
      price:
        fiyat > 0
          ? new Intl.NumberFormat(locale.value, { style: "currency", currency: "TRY" }).format(fiyat)
          : "",
    };
  }
  function openPlacement({ fileUrl, slotKey, trigger }) {
    placement.show({ fileUrl, slotKey, trigger, context: placementContext() });
  }
```

(`auth` is declared a few lines later; `placementContext` only runs on clicks/uploads, after setup.)

(c) In `uploadImage`, after `await uploads.finish(fieldName);` add:

```js
      if (fieldName === "primary_image")
        placement.afterUpload({ selected: 1, fileUrl: url, slotKey: "product.image", context: placementContext() });
```

In `uploadImageRow`, after `await uploads.finish(key);` add:

```js
      placement.afterUpload({ selected: 1, fileUrl: url, slotKey: "product.image", context: placementContext() });
```

In `addImageRows`, after the `for (const row of newRows) { … }` loop (still inside the outer `try`) add:

```js
      // Toplu yüklemede açılmaz (spec §4.4); tek dosya başarısızsa adres boş kalır, açılmaz.
      placement.afterUpload({
        selected: files.length,
        fileUrl: newRows.length === 1 ? newRows[0].image : "",
        slotKey: "product.image",
        context: placementContext(),
      });
```

Remove `media.actions.crop` / `media.actions.cropNoDims` from nothing else — the i18n keys stay in `locales/*.js` because `MediaLibraryView` still uses Crop Studio.

- [ ] **Step 5: Run tests and build**

Run: `cd /Users/ahmet/Desktop/istoc/admin-panel/frontend && node --test src/views/seller/__tests__/listingPlacementWiring.test.js && npx eslint src/views/seller/ListingFormView.vue && npx prettier --write src/views/seller/ListingFormView.vue && node --test src/views/seller/__tests__/listingPlacementWiring.test.js && npm run build 2>&1 | tail -3`
Expected: 4 tests pass before and after Prettier; ESLint clean; `vite build` ends with `✓ built in …`.

- [ ] **Step 6: Stage (no commit — user approves commits)**

```bash
cd /Users/ahmet/Desktop/istoc/admin-panel && git add frontend/src/views/seller/ListingFormView.vue frontend/src/views/seller/__tests__/listingPlacementWiring.test.js
```

---

### Task 12: Store-settings entry points (Wave 4 — after T8, T10)

**Files:**
- Modify: `admin-panel/frontend/src/components/upload/ProfileImageDropzone.vue` (logo/banner dropzone)
- Modify: `admin-panel/frontend/src/views/doctype/DocTypeFormView.vue` (`ProfileImageDropzone` usage ≈ 441-452, image child table ≈ 701-760, `uploadToChildTable` ≈ 2527-2570, template end ≈ 1326, imports ≈ 1331-1361)
- Modify: `admin-panel/frontend/src/views/seller/StorefrontLayoutEditor.vue` (header logo ≈ 236-300, `onHeaderFileChange` ≈ 678-707, template end ≈ 427, imports ≈ 430-439)
- Modify: `admin-panel/frontend/src/components/seller/LayoutSectionCard.vue` (slide image ≈ 158-232, `onSlideFileChange` ≈ 517-570, template end ≈ 436, imports ≈ 443-447)
- Create: `admin-panel/frontend/src/components/media/preview/__tests__/storePlacementWiring.test.js`

**Interfaces:**
- Consumes: T8, T10 (same host pattern as Task 11).
- Produces: `ProfileImageDropzone` new props `placementSlot: String` (default `""` = no button) and new emits `uploaded(url)`, `placement({fileUrl, slotKey, trigger})`. Slots: logo → `seller.logo`, banner → `company.cover_image`, vitrin slide → `company.cover_image`, `Seller Gallery Image` → `company.cover_image`.

- [ ] **Step 1: Write the failing test**

`src/components/media/preview/__tests__/storePlacementWiring.test.js`:

```js
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = (p) => readFileSync(new URL(`../../../../${p}`, import.meta.url), "utf8");
const dropzone = read("components/upload/ProfileImageDropzone.vue");
const doctype = read("views/doctype/DocTypeFormView.vue");
const editor = read("views/seller/StorefrontLayoutEditor.vue");
const card = read("components/seller/LayoutSectionCard.vue");

test("logo/banner alanı düğme gösterir ve yükleme olayı yayar", () => {
  assert.match(dropzone, /placementSlot: \{ type: String, default: "" \}/);
  assert.match(dropzone, /defineEmits\(\["update:modelValue", "uploaded", "placement"\]\)/);
  assert.match(dropzone, /emit\("uploaded", url\)/);
  assert.match(dropzone, /<ImagePlacementButton[\s\S]*?:slot-key="placementSlot"/);
});

test("satıcı profili: logo seller.logo, banner company.cover_image; galeri satırı", () => {
  assert.match(doctype, /:placement-slot="field\.fieldname === 'banner_image' \? 'company\.cover_image' : 'seller\.logo'"/);
  assert.match(doctype, /@uploaded="onProfileImageUploaded\(field\.fieldname, \$event\)"/);
  assert.match(doctype, /table\.options === 'Seller Gallery Image'/);
  assert.match(doctype, /placement\.afterUpload\(\{\s*selected: files\.length,/);
  assert.equal((doctype.match(/<ImagePlacementModal/g) || []).length, 1);
});

test("vitrin düzenleyici: başlık logosu ve slayt görselleri", () => {
  assert.match(editor, /<ImagePlacementButton[\s\S]*?slot-key="seller\.logo"/);
  assert.match(editor, /placement\.afterUpload\(\{\s*selected: 1,/);
  assert.equal((editor.match(/<ImagePlacementModal/g) || []).length, 1);
  assert.match(card, /<ImagePlacementButton[\s\S]*?slot-key="company\.cover_image"/);
  assert.match(card, /placement\.afterUpload\(\{\s*selected: 1,/);
  assert.equal((card.match(/<ImagePlacementModal/g) || []).length, 1);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/ahmet/Desktop/istoc/admin-panel/frontend && node --test src/components/media/preview/__tests__/storePlacementWiring.test.js 2>&1 | tail -5`
Expected: FAIL on every assertion group.

- [ ] **Step 3: `ProfileImageDropzone.vue`**

Add the import `import ImagePlacementButton from "@/components/media/preview/ImagePlacementButton.vue";`, the prop and the emits:

```js
    recommendedSize: { type: String, default: "" },
    /** Doluysa "Nerelerde görünecek?" düğmesi bu slotla gösterilir (seller.logo / company.cover_image). */
    placementSlot: { type: String, default: "" },
  });

  const emit = defineEmits(["update:modelValue", "uploaded", "placement"]);
```

In `uploadFile`, replace `if (url) emit("update:modelValue", url);` with:

```js
      if (url) {
        emit("update:modelValue", url);
        emit("uploaded", url);
      }
```

In the template, insert right before `<div v-if="modelValue" class="flex items-center gap-2 pt-1">`:

```vue
      <ImagePlacementButton
        v-if="modelValue && placementSlot"
        :file-url="modelValue"
        :slot-key="placementSlot"
        class="pt-1"
        @open="emit('placement', $event)"
      />
```

- [ ] **Step 4: `DocTypeFormView.vue`**

Imports: add `defineAsyncComponent` to the `vue` import and:

```js
  import ImagePlacementButton from "@/components/media/preview/ImagePlacementButton.vue";
  import { usePlacementLauncher } from "@/composables/usePlacementLauncher";
```

Script (after `const formData = ref({});`):

```js
  // ── Görsel önizleme penceresi (spec 2026-10-01 §4.4) ──────────────────
  const ImagePlacementModal = defineAsyncComponent(
    () => import("@/components/media/preview/ImagePlacementModal.vue")
  );
  const placement = usePlacementLauncher();
  const placementContext = () => ({ storeName: formData.value?.seller_name || "" });
  function openPlacement({ fileUrl, slotKey, trigger }) {
    placement.show({ fileUrl, slotKey, trigger, context: placementContext() });
  }
  function onProfileImageUploaded(fieldname, url) {
    placement.afterUpload({
      selected: 1,
      fileUrl: url,
      slotKey: fieldname === "banner_image" ? "company.cover_image" : "seller.logo",
      context: placementContext(),
    });
  }
```

`<ProfileImageDropzone …>` usage: add three attributes:

```vue
                              :placement-slot="field.fieldname === 'banner_image' ? 'company.cover_image' : 'seller.logo'"
                              @placement="openPlacement"
                              @uploaded="onProfileImageUploaded(field.fieldname, $event)"
```

Image child table (`<template v-if="canEdit && isImageChildTable(table.options)">`): wrap each cell the same way as Task 11 — change the `v-for` cell class to `flex flex-col gap-2`, move the existing classes `relative group aspect-square rounded-lg overflow-hidden border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/5` onto a new inner `<div>` that contains the `<img>`, the delete button and the index badge, and after that inner `</div>` add:

```vue
                        <ImagePlacementButton
                          v-if="table.options === 'Seller Gallery Image' && getFirstImageField(row, table.options)"
                          compact
                          :file-url="getFirstImageField(row, table.options)"
                          slot-key="company.cover_image"
                          @open="openPlacement"
                        />
```

`uploadToChildTable`: declare `let tekUrl = "";` before the `for (const file of files)` loop, set `tekUrl = url;` right after `anySuccess = true;`, and after the loop (before `if (anySuccess) …`) add:

```js
      if (childDoctype === "Seller Gallery Image")
        placement.afterUpload({
          selected: files.length,
          fileUrl: files.length === 1 ? tekUrl : "",
          slotKey: "company.cover_image",
          context: placementContext(),
        });
```

Template end: insert the host block from Task 10 (the `<ImagePlacementModal v-if="placement.state.open" … />` block) immediately before the final `  </div>` that precedes `</template>` (line ≈ 1327), so it stays inside the single root element.

- [ ] **Step 5: `StorefrontLayoutEditor.vue` and `LayoutSectionCard.vue`**

Both files: add the two imports (`ImagePlacementButton`, `usePlacementLauncher`), add `defineAsyncComponent` to the `vue` import, and in the script:

```js
  const ImagePlacementModal = defineAsyncComponent(
    () => import("@/components/media/preview/ImagePlacementModal.vue")
  );
  const placement = usePlacementLauncher();
  function openPlacement({ fileUrl, slotKey, trigger }) {
    placement.show({ fileUrl, slotKey, trigger, context: {} });
  }
```

(In `StorefrontLayoutEditor.vue`, `auth` already exists: use `context: { storeName: auth.user?.admin_seller_profile?.seller_name || "" }` in both `openPlacement` and the upload hook below.)

`StorefrontLayoutEditor.vue` template, inside `<div class="flex-1">` of the company-logo block, after the remove-logo `<button v-if="storeHeader.logo" …>` add:

```vue
                    <ImagePlacementButton
                      v-if="storeHeader.logo"
                      :file-url="storeHeader.logo"
                      slot-key="seller.logo"
                      class="mt-2"
                      @open="openPlacement"
                    />
```

`onHeaderFileChange`, after `storeHeader.value[field] = fileUrl;`:

```js
        if (field === "logo")
          placement.afterUpload({
            selected: 1,
            fileUrl,
            slotKey: "seller.logo",
            context: { storeName: auth.user?.admin_seller_profile?.seller_name || "" },
          });
```

`LayoutSectionCard.vue` template, after the `{{ t("layoutSectionCard.removeImage") }}` button of a slide add:

```vue
                  <ImagePlacementButton
                    v-if="slide.image"
                    compact
                    :file-url="slide.image"
                    slot-key="company.cover_image"
                    @open="openPlacement"
                  />
```

`onSlideFileChange`, replace `if (fileUrl) { slide.image = fileUrl; }` with:

```js
      if (fileUrl) {
        slide.image = fileUrl;
        placement.afterUpload({ selected: 1, fileUrl, slotKey: "company.cover_image", context: {} });
      }
```

Template end of both files: insert the Task 10 host block immediately before the last `  </div>` preceding `</template>` (inside the root element).

- [ ] **Step 6: Run tests and build**

Run: `cd /Users/ahmet/Desktop/istoc/admin-panel/frontend && npx prettier --write src/components/upload/ProfileImageDropzone.vue src/views/doctype/DocTypeFormView.vue src/views/seller/StorefrontLayoutEditor.vue src/components/seller/LayoutSectionCard.vue && node --test src/components/media/preview/__tests__/storePlacementWiring.test.js && npx eslint src/components/upload/ProfileImageDropzone.vue src/views/doctype/DocTypeFormView.vue src/views/seller/StorefrontLayoutEditor.vue src/components/seller/LayoutSectionCard.vue && npm test 2>&1 | grep -E "^# (pass|fail)" && npm run build 2>&1 | tail -2`
Expected: 3 wiring tests pass; ESLint clean; full `npm test` shows only the 3 baseline `alphaToJpeg` failures; build `✓ built`. If Prettier wraps an asserted attribute across lines, loosen that one regex with `\s*` — never weaken what it checks.

- [ ] **Step 7: Stage (no commit — user approves commits)**

```bash
cd /Users/ahmet/Desktop/istoc/admin-panel && git add frontend/src/components/upload/ProfileImageDropzone.vue frontend/src/views/doctype/DocTypeFormView.vue frontend/src/views/seller/StorefrontLayoutEditor.vue frontend/src/components/seller/LayoutSectionCard.vue frontend/src/components/media/preview/__tests__/storePlacementWiring.test.js
```

---

### Task 13: Local deploy, end-to-end (Özgen 78/45), axe AAA, `suggest_focal` measurement (Wave 5 — after all)

**Files:**
- Create: `admin-panel/frontend/tests/e2e/image-placement.spec.ts`
- Create: `tradehub_core/tradehub_core/media/odak_olcum.py`
- Possibly modify: `tradehub_core/tradehub_core/media/pipeline/simulator/placements.json` (+ regenerate, Task 1 Step 6) if a measured box differs by more than 2 px.

**Interfaces:**
- Consumes: everything above. Local data (verified 2026-10-01): seller `SEL-00020` "Özgen Plastik", user `ozgenplastik@istoc.com`, slug `sel-00020`; banner `/files/c2/c2e69ef450fc51205bc78d6d9707ca8e.webp` (2000 × 408) is both `banner_image` and the static `hero_banner` slide; its ready `company.cover_image` asset for SEL-00020 is `hd06rdkaru`. Note `SEL-00016` (also named "Özgen Plastik", user `satis@thoptan.com`) owns another asset on the same file — the test must log in as `ozgenplastik@istoc.com`.
- Produces: e2e evidence PNGs in `admin-panel/frontend/test-results/image-placement/`; measurement JSON printed by `odak_olcum.olc`.

- [ ] **Step 1: Deploy backend code into the running containers (temporary — the image rebuild is the permanent path)**

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core
FILES="tradehub_core/media/pipeline/simulator/placements.json tradehub_core/media/pipeline/delivery/sizes.py tradehub_core/media/pipeline/api/crop.py tradehub_core/media/odak.py tradehub_core/media/odak_olcum.py tradehub_core/api/media_preview.py tradehub_core/api/media_manifest.py"
for c in istoc-dev-backend-1 istoc-dev-queue-short-1 istoc-dev-queue-long-1 istoc-dev-scheduler-1 istoc-dev-queue-media-image-live-1 istoc-dev-queue-media-image-bulk-1 istoc-dev-queue-media-video-1 istoc-dev-queue-media-ai-1 istoc-dev-queue-media-maint-1; do
  for f in $FILES; do docker cp "$f" "$c:/home/frappe/frappe-bench/apps/tradehub_core/$f"; done
done
docker restart istoc-dev-backend-1 istoc-dev-queue-short-1 istoc-dev-queue-long-1 istoc-dev-scheduler-1 istoc-dev-queue-media-image-live-1 istoc-dev-queue-media-image-bulk-1 istoc-dev-queue-media-video-1 istoc-dev-queue-media-ai-1 istoc-dev-queue-media-maint-1
docker restart istoc-dev-frappe-frontend-1
docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site istoc.localhost clear-cache"
curl -s -o /dev/null -w "%{http_code}\n" "http://istoc.localhost/api/method/tradehub_core.api.media_preview.get_preview_prefs"
```
Expected: last line `403` (guest rejected → endpoint exists; `404`/`500` means the copy or restart failed). Do NOT run `docker compose up -d` for backend services here — recreate drops `docker cp` files and a following migrate can restore stale JSON (memory note "Docker imaj canlı-kod tuzağı").

- [ ] **Step 2: Rebuild and restart the two frontends**

```bash
cd /Users/ahmet/Desktop/istoc/docker
docker compose build admin-panel storefront
docker compose up -d --no-deps admin-panel storefront
docker restart istoc-dev-gateway-1 istoc-dev-frappe-frontend-1
curl -s -o /dev/null -w "%{http_code}\n" http://istoc.localhost/panel/
curl -s -o /dev/null -w "%{http_code}\n" http://istoc.localhost/magaza/sel-00020/dukkan
```
Expected: `200` and `200`. (A `502` means the gateway holds a stale upstream IP — restart `istoc-dev-gateway-1` again.)

- [ ] **Step 3: Write the e2e spec**

`admin-panel/frontend/tests/e2e/image-placement.spec.ts`:

```ts
import axeCore from "axe-core";
import { expect, test, type Page } from "@playwright/test";

/**
 * Görsel önizleme + odak noktası — uçtan uca (spec 2026-10-01 §9).
 *
 *   E2E_SELLER_USER=ozgenplastik@istoc.com npx playwright test tests/e2e/image-placement.spec.ts
 *
 * Özgen Plastik banner'ı (2000 × 408) telefonda 390 × 180 vitrin bandında %44
 * görünür; odak %78 / %45 kaydedilince yazının bulunduğu sağ taraf görünmeli ve
 * önizlemedeki kırpım vitrindekiyle aynı olmalı.
 */
const BANNER = "/files/c2/c2e69ef450fc51205bc78d6d9707ca8e.webp";
const STORE = "http://istoc.localhost/magaza/sel-00020/dukkan";
const OUT = "test-results/image-placement";

type AxeViolation = { id: string; impact?: string | null; help: string; nodes: { target?: unknown }[] };

async function axe(page: Page, include: string): Promise<AxeViolation[]> {
  await page.addScriptTag({ content: axeCore.source });
  return page.evaluate(async (sel) => {
    const a = (globalThis as unknown as { axe: { run: (c: unknown, o: unknown) => Promise<{ violations: AxeViolation[] }> } }).axe;
    const r = await a.run(
      { include: [sel] },
      { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag2aaa", "wcag21a", "wcag21aa", "wcag22aa"] } }
    );
    return r.violations;
  }, include);
}

async function openWindow(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("storefront-layout", { waitUntil: "domcontentloaded" });
  await page.keyboard.press("Escape");
  const button = page.locator(`[data-placement-url="${BANNER}"] .ipb__btn`).first();
  if (!(await button.isVisible().catch(() => false))) {
    // Vitrin bandı kartı kapalıysa aç (başlıkta "Banner" / "Hero" geçer).
    await page.getByText(/hero|banner/i).first().click();
  }
  await expect(button).toBeVisible();
  await expect(page.locator(`[data-placement-url="${BANNER}"] .ipb__badge`)).toContainText("yerde kenarlar kesiliyor");
  await button.click();
  const dialog = page.getByRole("dialog", { name: "Görseliniz nerelerde görünecek?" });
  await expect(dialog).toBeVisible();
  return dialog;
}

test("Özgen banner'ı: %78/%45 kaydedilir, telefonda vitrin önizlemeyle aynı kırpılır", async ({ page, browser }) => {
  const dialog = await openWindow(page);
  await dialog.getByRole("button", { name: "Telefon" }).click();
  await dialog.getByRole("button", { name: /Mağaza sayfası başlığı/ }).click();
  await dialog.getByLabel("Yatay (%)").fill("78");
  await dialog.getByLabel("Yatay (%)").press("Tab");
  await dialog.getByLabel("Dikey (%)").fill("45");
  await dialog.getByLabel("Dikey (%)").press("Tab");
  await expect(dialog.getByRole("status")).toContainText("Odak noktası: yatay %78, dikey %45");

  const preview = dialog.locator(".ipm__stagewrap .ctx-band .ctx-img");
  await expect(preview).toHaveCSS("object-position", "78% 45%");
  const pBox = await preview.boundingBox();
  expect(Math.round(pBox!.width)).toBe(390);
  expect(Math.round(pBox!.height)).toBe(180);
  const previewShot = await preview.screenshot({ path: `${OUT}/preview.png` });

  const violations = await axe(page, ".ipm");
  expect(violations, violations.map((v) => `${v.id}: ${v.help}`).join("\n")).toEqual([]);

  await dialog.getByRole("button", { name: "Kaydet" }).click();
  await expect(dialog).toBeHidden();

  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, storageState: undefined });
  const store = await ctx.newPage();
  await store.goto(STORE, { waitUntil: "networkidle" });
  const hero = store.locator('[data-section="hero_banner"] img').first();
  await expect(hero).toBeVisible();
  await expect(hero).toHaveCSS("object-position", "78% 45%");
  const sBox = await hero.boundingBox();
  expect(Math.round(sBox!.width)).toBe(390);
  expect(Math.round(sBox!.height)).toBe(180);
  const storeShot = await hero.screenshot({ path: `${OUT}/storefront.png` });

  const cmp = await ctx.newPage();
  await cmp.setContent("<!doctype html><title>cmp</title>");
  const meanDiff = await cmp.evaluate(
    async ([a, b]) => {
      const load = (b64: string) =>
        new Promise<HTMLImageElement>((res, rej) => {
          const i = new Image();
          i.onload = () => res(i);
          i.onerror = rej;
          i.src = `data:image/png;base64,${b64}`;
        });
      const [ia, ib] = await Promise.all([load(a), load(b)]);
      const w = 195;
      const h = 90;
      const px = (img: HTMLImageElement) => {
        const c = document.createElement("canvas");
        c.width = w;
        c.height = h;
        const g = c.getContext("2d")!;
        g.drawImage(img, 0, 0, w, h);
        return g.getImageData(0, 0, w, h).data;
      };
      const da = px(ia);
      const db = px(ib);
      let sum = 0;
      for (let i = 0; i < da.length; i += 4)
        sum += (Math.abs(da[i] - db[i]) + Math.abs(da[i + 1] - db[i + 1]) + Math.abs(da[i + 2] - db[i + 2])) / 3;
      return sum / (w * h);
    },
    [previewShot.toString("base64"), storeShot.toString("base64")] as const
  );
  // Önizleme master WebP'yi, vitrin srcset türevini çiziyor: küçük fark doğal; kırpım farkı ≫ 20.
  expect(meanDiff).toBeLessThan(20);
  await ctx.close();
});

test("klavyeyle baştan sona: cihaz → yerler → odak işareti → kaydet; Esc onay ister", async ({ page }) => {
  const dialog = await openWindow(page);
  await expect(dialog.getByRole("button", { name: "Bilgisayar" })).toBeFocused();
  const handle = dialog.locator(".fe__handle");
  await handle.focus();
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("Shift+ArrowLeft");
  await expect(dialog.getByRole("status")).toContainText("yatay %");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("alertdialog")).toBeVisible();
  await page.getByRole("button", { name: "Kaydetmeden kapat" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.locator(`[data-placement-url="${BANNER}"] .ipb__btn`).first()).toBeFocused();
});

test("hareketi azalt açıkken geçişler kapalı", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const dialog = await openWindow(page);
  await expect(dialog.locator(".ctx-img").first()).toHaveCSS("transition-duration", "0s");
  await expect(dialog.locator(".fe__layer").first()).toHaveCSS("transition-duration", "0s");
});
```

- [ ] **Step 4: Run the e2e and inspect the evidence**

```bash
cd /Users/ahmet/Desktop/istoc/admin-panel/frontend
E2E_SELLER_USER=ozgenplastik@istoc.com npx playwright test tests/e2e/image-placement.spec.ts
open test-results/image-placement/preview.png test-results/image-placement/storefront.png
```
Expected: 3 passed. In both PNGs the banner's right-hand text block is visible (before the change the centred crop hid it). If the first test fails on `toHaveCSS` in the storefront only, check `get_storefront_layout` output: `docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site istoc.localhost execute tradehub_core.api.seller.get_storefront_layout --kwargs '{\"seller_code\": \"SEL-00020\"}'" | grep focal` must show `{"x": 0.78, "y": 0.45}`.

- [ ] **Step 5: Verify the store-place sizes on the real storefront**

```bash
cd /Users/ahmet/Desktop/istoc/admin-panel/frontend
cat > /tmp/olc.mjs <<'EOF'
import { chromium } from "@playwright/test";
const b = await chromium.launch();
for (const [w, h] of [[390, 844], [1440, 900]]) {
  const p = await b.newPage({ viewport: { width: w, height: h } });
  await p.goto("http://istoc.localhost/magaza/sel-00020", { waitUntil: "networkidle" });
  const kutu = async (sel) => p.locator(sel).first().evaluate((e) => { const r = e.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; }).catch(() => null);
  console.log(w, "vitrin", await kutu(".aspect-video"), "galeri", await kutu(".aspect-\\[4\\/3\\]"));
  await p.goto("http://istoc.localhost/magaza/sel-00020/dukkan", { waitUntil: "networkidle" });
  console.log(w, "bant", await kutu('[data-section="hero_banner"] img'));
}
await b.close();
EOF
node /tmp/olc.mjs && rm /tmp/olc.mjs
```
Expected (registry values): 390 → vitrin `[326,183]`, galeri `[103,77]`, bant `[390,180]`; 1440 → vitrin `[500,281]`, galeri `[119,89]`. If any differs by > 2 px, update that `css_size` (and `derived_from` with the measurement date) in `placements.json`, re-run Task 1 Steps 5–6, re-run the admin `places.test.js`, and redeploy (Steps 1–2). If the seller has no gallery items the gallery box prints `null` — record "ölçülemedi" in the report rather than inventing a value.

- [ ] **Step 6: Measure `suggest_focal` against the saved focal (spec §4.3)**

`tradehub_core/tradehub_core/media/odak_olcum.py`:

```python
"""`suggest_focal` öneri kalitesi ölçümü (spec 2026-10-01 §4.3) — iyileştirme AYRI iş.

Elle kaydedilmiş (`method = manual`) mağaza görseli odaklarını, aynı dosya için
`focal_from_bytes` önerisiyle karşılaştırır. Yazmaz.

    docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && \
        bench --site istoc.localhost execute tradehub_core.media.odak_olcum.olc"
"""

from __future__ import annotations

import math

import frappe
from frappe.query_builder import DocType

from tradehub_core.media.pipeline.api import crop as crop_lib


def olc(limit: int = 200) -> dict:
	niyet, varlik = DocType("Media Crop Intent"), DocType("Media Asset")
	satirlar = (
		frappe.qb.from_(niyet)
		.join(varlik)
		.on(varlik.name == niyet.asset)
		.select(niyet.asset, niyet.focal_x, niyet.focal_y, varlik.slot_key, varlik.source_file)
		.where(niyet.method == "manual")
		.where(niyet.focal_x.isnotnull())
		.where(varlik.slot_key.isin(["company.cover_image", "seller.logo"]))
		.orderby(niyet.modified, order=frappe.qb.desc)
		.limit(int(limit))
	).run(as_dict=True)
	sonuc = []
	for r in satirlar:
		try:
			icerik = frappe.get_doc("File", r["source_file"]).get_content()
		except (OSError, frappe.DoesNotExistError):
			continue
		oneri = crop_lib.focal_from_bytes(icerik)
		elle = (float(r["focal_x"]), float(r["focal_y"]))
		sonuc.append(
			{
				"asset": r["asset"],
				"slot": r["slot_key"],
				"manual": [round(elle[0], 3), round(elle[1], 3)],
				"suggested": [round(oneri.x, 3), round(oneri.y, 3)],
				"measured": oneri.measured,
				"distance": round(math.hypot(oneri.x - elle[0], oneri.y - elle[1]), 3),
			}
		)
	mesafeler = sorted(s["distance"] for s in sonuc)
	ozet = {
		"n": len(sonuc),
		"median": mesafeler[len(mesafeler) // 2] if mesafeler else None,
		"within_0_15": sum(1 for d in mesafeler if d <= 0.15),
	}
	print(frappe.as_json({"ozet": ozet, "satirlar": sonuc}))
	return {"ozet": ozet, "satirlar": sonuc}
```

Run (after Step 4 saved at least the Özgen focal):

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core && ruff check tradehub_core/media/odak_olcum.py
docker cp tradehub_core/media/odak_olcum.py istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/media/odak_olcum.py
docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site istoc.localhost execute tradehub_core.media.odak_olcum.olc"
```
Expected: JSON with `"ozet": {"n": ≥1, …}` and a row for asset `hd06rdkaru` with `"manual": [0.78, 0.45]`. Report the median distance; do not change `suggest_focal` (out of scope, spec §8).

- [ ] **Step 7: Full regression pass**

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core && python3 -m unittest tradehub_core.tests.test_preview_places tradehub_core.tests.test_api_contracts 2>&1 | tail -2
for m in test_media_preview test_magaza_odak test_media_crop_intent test_magaza_gorseli test_media_manifest_api; do docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site istoc.localhost run-tests --module tradehub_core.tests.$m" 2>&1 | tail -1; done
cd /Users/ahmet/Desktop/istoc/admin-panel/frontend && npm test 2>&1 | grep -E "^# (pass|fail)"
cd /Users/ahmet/Desktop/istoc/tradehubfront && npx vitest run 2>&1 | tail -4 && npm run check:dup
```
Expected: Python `OK`; every bench module `OK`; admin `# fail 3` (baseline only); storefront vitest all passed; `check:dup` OK.

- [ ] **Step 8: Stage (no commit — user approves commits)**

```bash
cd /Users/ahmet/Desktop/istoc/admin-panel && git add frontend/tests/e2e/image-placement.spec.ts
cd /Users/ahmet/Desktop/istoc/tradehub_core && git add tradehub_core/media/odak_olcum.py
# only if Step 5 changed it:
# cd /Users/ahmet/Desktop/istoc/tradehub_core && git add tradehub_core/media/pipeline/simulator/placements.json
# cd /Users/ahmet/Desktop/istoc/admin-panel && git add frontend/src/lib/media/vendor/placements.js frontend/src/lib/media/simulator/vendor
```

Report to the user: e2e result + the two PNG paths, axe result, measured boxes, `suggest_focal` median distance, and the reminder that the backend changes in the containers are temporary until the backend image is rebuilt from the repo (and that alpha/prod deploy is a separate, approved step — spec §10).

---

## Spec coverage map

| Spec | Task |
|---|---|
| §4.1 registry, `derived_from`, `--emit-placements`, `storeImage.ts` from the same source | 1, 9 |
| §4.2 window layout (3 columns, 250/330 px, browser frame + scale label, 390 px phone frame, device toggle) | 8 |
| §4.2 phone layout (chips, context, focal panel, sticky Save/Cancel) | 8 |
| §4.2 context templates with real store/product data | 7 |
| §4.2 crop math = `object-position` | 5 (geometry), 6 (visibility), 9 (storefront) |
| §4.2 product images "Tamamı görünüyor" + "Kareye tamamlandı" summary | 3 (`square`), 6, 8 |
| §4.3 `useFocalPoint`, `get_intent` → `suggest_focal` fallback + announcement, `save_intent` focal only, ETag | 2, 5 |
| §4.3 shared pure functions in `geometry.js` | 5 |
| §4.3 measure `suggest_focal` quality | 13 |
| §4.4 "Nerelerde görünecek?" + "N yerde kenarlar kesiliyor" in ListingFormView | 10, 11 |
| §4.4 store settings: logo, banner, vitrin slide, gallery | 12 |
| §4.4 auto-open after single upload, never batch; `th_media_preview_autoopen` server-side, default on | 3, 10, 11, 12 |
| §4.5 `focal` in manifest / `*_media`; `object-position` on live store images | 4, 9 |
| §5 WCAG 2.2 AAA (contrast, targets, keyboard, focus trap, Esc, focus return, status, aria-*) | 7, 8, 10, 13 |
| §6 motion | 7, 8, 13 |
| §7 error states | 5, 8 |
| §9 tests (unit, component, backend, storefront, e2e, axe) | 1–13 |
| §10 local only; alpha/prod separate | 13 (report) |

## Spec gaps and decisions found in the real code (2026-10-01)

1. **Focal is keyed by `Media Asset`, the window by file URL.** `Media Crop Intent` is `autoname: field:asset`; one file has many assets (the Özgen banner file has 6: two sellers × `company.cover_image`/`library.image`, several `archived`). Task 3 adds `get_preview_target(file_url, slot_key)` and `odak.odaklar()` keyed by *(file URL, seller)*, counting archived assets so a focal survives `kare`/`magaza_gorseli` URL moves.
2. **`if_match` never worked** — `save_intent` hashed `{asset, intent}` while clients receive the hash of the full body; a fresh ETag got 412 (measured). Fixed in Task 2.
3. **`saveCropIntent` always sends `safe_area: {}`** which the endpoint reads as "delete the safe area". The window uses the new `saveFocalOnly` (Task 5).
4. **"Only `focal_x`/`focal_y`" is not literally possible**: `save_intent` resets `approved_by_user` to the sent value. The window sends `approved_by_user=1` + `previewed_placements` (the places the seller actually looked at) + `method`; safe area, zoom, overrides, confidence are preserved (tested in Task 2).
5. **`placements.json` had no store regions** (only 15 `product.image` regions, no ratio/fit/context, no favorites). Places live in a new top-level `preview_places` block so `sizes.py` / simulator parity stays unchanged; favourites box size is unmeasured (`null`).
6. **`Admin Seller Profile.banner_image` has no live storefront render point** (the shop header uses a dead `header_bg_image`); the banner is visible only because the same file is the static vitrin slide. Places are therefore per slot (spec) rather than per field.
7. **Storefront components named in spec §4.5 — `CompanyInfo`, `Gallery`, `CategoryProductListing`, `HeroBanner` — are dead mock components** (only re-exported, fed by `mockData.ts`). Task 9 applies `object-position` to the live points instead: vitrin hero (`section-registry`), `StoreHeader` gallery (main/video poster/thumbs), shop desktop logo, manufacturer gallery preview. The dükkan `gallery` section reads `seller.gallery_images` without `*_media`, so it has no focal source and is not covered.
8. **No "liste küçük resmi" store place exists** (manufacturer gallery is desktop-only) → `ListThumbContext` is not built; 9 contexts instead of 10.
9. **Design numbers vs CSS:** phone header is 390 × 180 in CSS (design 390 × 195 "2:1"); the desktop hero is full-bleed (ratio depends on viewport; registry uses the design's 1200 px page); phone shop logo is `object-contain` (never cut). The registry follows the CSS.
10. **`geometry.js` says "no math here"**, and the spec both says "move `clampFocal`/`visibleFraction`/`frameRect` there, both sides use them" and "do not touch `useCropStudio.js`". `useCropStudio` has no such functions; Task 5 adds them to `geometry.js` (header amended) and leaves `useCropStudio.js` untouched.
11. **`storeImage.ts` keeps 9 hand-written `sizes`** (logos 16–116 px that are not preview places); only the 5 shared keys come from the registry.
12. **Phone layout:** spec text says chips + collapsible focal panel; approved board 4 shows "Önizleme / Odak noktası" tabs with −/+ steppers. The plan follows the board (chips sit inside the Önizleme tab).
13. **AAA tweaks to the design:** number-input border `#a09c92` is 2.8:1 → `#8a867c`; checkbox 22 → 24 px (2.5.8). Design status copy "…yazının bulunduğu alan seçildi" over-claims an edge-energy heuristic → spec copy "Otomatik öneri uygulandı."
14. **Media Library uploads (`MediaUploader`) do not auto-open** — library files have no target slot; auto-open is wired to the listing form and store settings only.
15. **Two sellers named "Özgen Plastik"** (`SEL-00016`, `SEL-00020`) share the banner file; e2e logs in as `ozgenplastik@istoc.com` (SEL-00020).
16. Window strings live in `src/lib/media/preview/messages.js` (local i18n scope, CropStudioModal pattern) instead of the 11k-line `locales/*.js`, so parallel tasks do not collide.

# Static SEO Bot Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Return current backend SEO metadata inside the complete storefront document for bots, restore favicon discovery, normalize homepage hreflang, and make Static Page SEO scoring reflect only data the editor actually owns.

**Architecture:** Keep the current Nginx bot route and backend metadata injector. The backend reads a local storefront template when available and otherwise fetches the normal public storefront HTML over bounded HTTP, validates and briefly caches that template, then injects current database metadata. Storefront favicon assets and verification contracts become explicit, while the admin analyzer gains capability flags and uses `page_path` directly for static pages.

**Tech Stack:** Frappe v15/Python `unittest`, Python standard-library HTTP client, Redis-backed Frappe cache, Vite/TypeScript/Vitest, Vue 3/Pinia, Node 22 native test runner, Nginx.

## Global Constraints

- Preserve normal storefront behavior and existing listing/category/brand/seller SEO behavior.
- Backend SEO edits must appear in the first Googlebot HTTP response without a frontend rebuild.
- Bot and user documents must expose equivalent storefront shell markers and application assets.
- Only paths resolved through `STATIC_PAGES_REGISTRY` may be fetched remotely.
- Remote template requests use bounded timeout, bounded body size, short TTL, and a non-bot User-Agent.
- No production deploy, push, live data mutation, or Search Console action is authorized.
- Work inside each owning repository; `frappe-docker-setup/` is not Git-owned and must not be edited for this solution.
- Use red-green TDD for every behavior change and preserve unrelated work.

## File Structure

### `tradehub_core/`

- Modify `tradehub_core/seo/page_resolver.py`: local/remote/safe template acquisition and final injection.
- Modify `tradehub_core/seo/meta_builder.py`: homepage static-page hreflang normalization.
- Modify `tradehub_core/seo/tests/test_page_resolver.py`: remote-template and safe-fallback regression coverage.
- Modify `tradehub_core/seo/tests/test_meta_builder.py`: homepage hreflang regression coverage.

### `tradehubfront/`

- Modify `index.html`: stable favicon declarations.
- Modify `vite.config.ts`: inject the same favicon contract into all built HTML documents.
- Modify `nginx.conf.template`: make `/favicon.ico` resolve to a valid PNG and serve `.webmanifest` with `application/manifest+json`.
- Create `public/icons/favicon-48.png`: 48×48 derivative of the existing official app icon.
- Create `public/icons/favicon-96.png`: 96×96 derivative of the existing official app icon.
- Create `src/seo/faviconContract.test.ts`: source/build favicon contract tests.
- Modify `scripts/verify-seo-bot.sh`: behavior-level live bot document checks.

### `admin-panel/frontend/`

- Create `src/utils/seoEditorModel.js`: pure field/path/capability helpers.
- Create `src/utils/__tests__/seoEditorModel.test.js`: static-page path and preview tests.
- Modify `src/components/seo/SeoTab.vue`: consume configured fields and disable static-page auto-slug.
- Modify `src/components/seo/SeoFormFields.vue`: present `page_path` as a fixed path without EN suffixing or slug hints.
- Modify `src/utils/seoAnalyzer.js`: capability-aware NA results.
- Modify `src/utils/__tests__/seoAnalyzer.test.js`: metadata-only analyzer coverage.

---

### Task 1: Normalize static homepage hreflang

**Files:**
- Modify: `tradehub_core/tradehub_core/seo/meta_builder.py:296-358`
- Test: `tradehub_core/tradehub_core/seo/tests/test_meta_builder.py`

**Interfaces:**
- Consumes: `build_hreflang_links(canonical_tr_path: str, site_url: str) -> list[dict]`
- Produces: `build_for_static_page(...)` payload whose `hreflang_links` use `page_path` rather than the intermediate `//` slug path.

- [ ] **Step 1: Write the failing homepage hreflang test**

Import `build_for_static_page` beside the existing imports, add a
`TestStaticPage` class, and use hand-derived URLs:

```python
def test_static_home_hreflang_uses_single_slash_paths(self):
	seo = build_for_static_page(
		record={"page_path": "/", "meta_title": "Anasayfa", "noindex": 0},
		page_meta={"path": "/", "title": "Anasayfa"},
		defaults=DEFAULTS,
		site_url=SITE_URL,
	)
	self.assertEqual(
		seo["hreflang_links"],
		[
			{"hreflang": "tr", "href": "https://istoc.com/"},
			{"hreflang": "en", "href": "https://istoc.com/en/"},
			{"hreflang": "x-default", "href": "https://istoc.com/"},
		],
	)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core
python -m unittest tradehub_core.seo.tests.test_meta_builder.TestStaticPage.test_static_home_hreflang_uses_single_slash_paths
```

Expected: FAIL because current values contain `https://istoc.com//`.

- [ ] **Step 3: Rebuild static-page hreflang from `page_path`**

After canonical reconstruction in `build_for_static_page`, set the links from the canonical TR path:

```python
	if page_path:
		from tradehub_core.seo.i18n import build_hreflang_links, localize_url

		canonical = f"{site_url.rstrip('/')}{localize_url(page_path, lang)}"
		seo["canonical"] = canonical
		seo["og_url"] = canonical
		seo["hreflang_links"] = build_hreflang_links(page_path, site_url)
```

Keep canonical override behavior unchanged; an override must not redefine language route discovery.

- [ ] **Step 4: Run focused and related tests and verify GREEN**

Run:

```bash
python -m unittest \
  tradehub_core.seo.tests.test_meta_builder \
  tradehub_core.seo.tests.test_i18n
```

Expected: PASS.

- [ ] **Step 5: Commit the isolated backend URL fix**

```bash
git add tradehub_core/seo/meta_builder.py tradehub_core/seo/tests/test_meta_builder.py
git commit -m "fix(seo): normalize static homepage hreflang"
```

---

### Task 2: Load the real storefront template for bot rendering

**Files:**
- Modify: `tradehub_core/tradehub_core/seo/page_resolver.py:43-103,231-243`
- Test: `tradehub_core/tradehub_core/seo/tests/test_page_resolver.py`

**Interfaces:**
- Produces:
  - `_fetch_remote_template(public_path: str, storefront_base: str, opener: Callable = urllib.request.urlopen) -> str | None`
  - `_is_valid_storefront_template(html: str, content_type: str) -> bool`
  - `_seo_safe_fallback_html(page_meta: dict) -> str`
  - `_read_template(template_relpath: str, public_path: str, page_meta: dict) -> str`
- Consumes: `storefront_url()`, `frappe.cache`, registered static page metadata.

- [ ] **Step 1: Write failing safe-fallback behavior tests**

Replace the old minimal-fallback-only assertions with behavior assertions:

```python
class TestSeoSafeFallbackHtml(unittest.TestCase):
	def test_home_fallback_exposes_discovery_content(self):
		html = page_resolver._seo_safe_fallback_html(
			{"path": "/", "title": "Anasayfa", "meta_description": "B2B toptan satış pazaryeri."}
		)
		self.assertIn(PLACEHOLDER, html)
		self.assertIn('rel="icon"', html)
		self.assertIn('href="/icons/favicon-96.png"', html)
		self.assertIn("<h1>", html)
		self.assertIn('href="/urunler"', html)
		self.assertIn('href="/kategoriler"', html)
		self.assertNotIn("LST-", html)
```

Name the break: reverting to `JavaScript gerekli.` only must fail this test.

- [ ] **Step 2: Run fallback tests and verify RED**

Run:

```bash
python -m unittest tradehub_core.seo.tests.test_page_resolver.TestSeoSafeFallbackHtml
```

Expected: FAIL because `_seo_safe_fallback_html` does not exist.

- [ ] **Step 3: Implement the complete fallback**

Implement a small deterministic document:

```python
def _seo_safe_fallback_html(page_meta: dict) -> str:
	title = html.escape(page_meta.get("title") or "iStoc")
	description = html.escape(page_meta.get("meta_description") or "iStoc B2B toptan satış pazaryeri.")
	return (
		"<!doctype html>\n"
		'<html lang="tr"><head>\n'
		'<meta charset="utf-8">\n'
		'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
		'<link rel="icon" type="image/png" sizes="48x48" href="/icons/favicon-48.png">\n'
		'<link rel="icon" type="image/png" sizes="96x96" href="/icons/favicon-96.png">\n'
		f"{seo_html_injector.PLACEHOLDER}\n"
		"</head><body><main>\n"
		f"<h1>{title}</h1><p>{description}</p>\n"
		'<nav aria-label="Keşif bağlantıları">'
		'<a href="/urunler">Toptan ürünler</a>'
		'<a href="/kategoriler">Ürün kategorileri</a>'
		'<a href="/ureticiler">Tedarikçiler</a>'
		'<a href="/ticaret-guvencesi">Ticaret güvencesi</a>'
		"</nav></main></body></html>"
	)
```

Use `html.escape`; do not interpolate unescaped registry values.

- [ ] **Step 4: Write failing remote-loader tests**

Use a real response-shaped fake only at the external socket boundary:

```python
class FakeHttpResponse:
	def __init__(self, body: bytes, content_type: str = "text/html; charset=utf-8", status: int = 200):
		self._body = body
		self.headers = {"Content-Type": content_type}
		self.status = status

	def read(self, limit: int) -> bytes:
		return self._body[:limit]

	def __enter__(self):
		return self

	def __exit__(self, *_args):
		return False


class TestRemoteTemplateLoader(unittest.TestCase):
	def test_fetches_registered_path_with_non_bot_user_agent(self):
		seen = {}
		document = b'<!doctype html><html><body><div id="app"></div><script type="module" src="/assets/app.js"></script></body></html>'

		def opener(request, timeout):
			seen["url"] = request.full_url
			seen["user_agent"] = request.headers["User-agent"]
			seen["timeout"] = timeout
			return FakeHttpResponse(document)

		html = page_resolver._fetch_remote_template("/", "https://istoc.com", opener=opener)
		self.assertEqual(seen["url"], "https://istoc.com/")
		self.assertNotIn("bot", seen["user_agent"].lower())
		self.assertLessEqual(seen["timeout"], 5)
		self.assertIn('id="app"', html)

	def test_rejects_non_html_and_missing_storefront_marker(self):
		def opener(_request, _timeout):
			return FakeHttpResponse(b'{"message":"not html"}', "application/json")

		self.assertIsNone(
			page_resolver._fetch_remote_template("/", "https://istoc.com", opener=opener)
		)
```

Also add individual tests for oversized body, HTTP error/timeout, local-file precedence, and preservation of asset references after injection.

- [ ] **Step 5: Run loader tests and verify RED**

Run:

```bash
python -m unittest tradehub_core.seo.tests.test_page_resolver.TestRemoteTemplateLoader
```

Expected: FAIL because the remote loader does not exist.

- [ ] **Step 6: Implement bounded remote acquisition**

Add constants and pure validation:

```python
REMOTE_TEMPLATE_TIMEOUT_SECONDS = 4
REMOTE_TEMPLATE_MAX_BYTES = 2 * 1024 * 1024
REMOTE_TEMPLATE_CACHE_TTL_SECONDS = 300
REMOTE_TEMPLATE_FAILURE_TTL_SECONDS = 30
REMOTE_TEMPLATE_USER_AGENT = "iStoc-SEO-Template/1.0"


def _is_valid_storefront_template(document: str, content_type: str) -> bool:
	if "text/html" not in content_type.lower():
		return False
	return 'id="app"' in document and "<script" in document
```

Implement `_fetch_remote_template` with `urllib.request.Request`,
`urljoin(storefront_base.rstrip("/") + "/", public_path.lstrip("/"))`,
`read(REMOTE_TEMPLATE_MAX_BYTES + 1)`, UTF-8 decoding, and explicit handling
for `HTTPError`, `URLError`, `TimeoutError`, `UnicodeDecodeError`, and
`ValueError`. Accept HTTP only for `localhost` and `127.0.0.1`; require HTTPS
for every other hostname. Do not log response bodies.

- [ ] **Step 7: Add short Frappe cache and local-first orchestration**

Use a stable key such as:

```python
def _remote_template_cache_key(public_path: str) -> str:
	return f"tradehub:seo:storefront-template:{public_path}"
```

`_read_template` must:

1. return the local file when present;
2. read a cached remote template;
3. fetch and cache a valid remote template for 300 seconds;
4. return `_seo_safe_fallback_html(page_meta)` on failure.

Cache exceptions must be logged and ignored. The final metadata-injected HTML
must not be stored in this cache. Cache a failure sentinel for 30 seconds so a
frontend outage does not create a request or logging storm.

- [ ] **Step 8: Pass registered path metadata from `render_static_page`**

Change the template call to:

```python
	html = _read_template(
		entry["html_path"],
		public_path=entry["path"],
		page_meta=entry,
	)
```

Keep unknown-path 404 handling and `_html_response` cache headers unchanged.

- [ ] **Step 9: Run backend tests and static checks**

Run:

```bash
python -m unittest \
  tradehub_core.seo.tests.test_page_resolver \
  tradehub_core.seo.tests.test_html_injector \
  tradehub_core.seo.tests.test_meta_builder
python -m py_compile tradehub_core/seo/page_resolver.py tradehub_core/seo/meta_builder.py
ruff check tradehub_core/seo/page_resolver.py tradehub_core/seo/meta_builder.py tradehub_core/seo/tests/test_page_resolver.py
```

Expected: PASS with no warnings.

- [ ] **Step 10: Commit backend template parity**

```bash
git add tradehub_core/seo/page_resolver.py tradehub_core/seo/tests/test_page_resolver.py
git commit -m "fix(seo): render bot metadata in storefront template"
```

---

### Task 3: Establish the storefront favicon and bot verification contract

**Files:**
- Modify: `tradehubfront/index.html`
- Modify: `tradehubfront/vite.config.ts`
- Modify: `tradehubfront/nginx.conf.template`
- Create: `tradehubfront/public/icons/favicon-48.png`
- Create: `tradehubfront/public/icons/favicon-96.png`
- Create: `tradehubfront/src/seo/faviconContract.test.ts`
- Modify: `tradehubfront/scripts/verify-seo-bot.sh`

**Interfaces:**
- Produces stable public URLs `/icons/favicon-48.png`, `/icons/favicon-96.png`, and `/favicon.ico`.
- Extends the live verifier contract for Googlebot HTML.

- [ ] **Step 1: Write the failing favicon contract test**

Create `src/seo/faviconContract.test.ts`:

```typescript
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(".");
const indexHtml = await readFile(resolve(root, "index.html"), "utf8");

async function pngDimensions(name: string): Promise<[number, number]> {
  const png = await readFile(resolve(root, "public/icons", name));
  return [png.readUInt32BE(16), png.readUInt32BE(20)];
}

describe("favicon contract", () => {
  it("declares stable 48px, 96px, ico, and Apple icon URLs", () => {
    expect(indexHtml).toContain('sizes="48x48" href="/icons/favicon-48.png"');
    expect(indexHtml).toContain('sizes="96x96" href="/icons/favicon-96.png"');
    expect(indexHtml).toContain('href="/favicon.ico"');
    expect(indexHtml).toContain('rel="apple-touch-icon"');
  });

  it("ships exact square icon dimensions", async () => {
    expect(await pngDimensions("favicon-48.png")).toEqual([48, 48]);
    expect(await pngDimensions("favicon-96.png")).toEqual([96, 96]);
  });
});
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
cd /Users/ahmet/Desktop/istoc/tradehubfront
npx vitest run src/seo/faviconContract.test.ts
```

Expected: FAIL because declarations/files do not exist.

- [ ] **Step 3: Generate exact-size derivatives from the official icon**

Use the existing tracked official `public/icons/icon-192.png` as the only
source:

```bash
sips -z 48 48 public/icons/icon-192.png --out public/icons/favicon-48.png
sips -z 96 96 public/icons/icon-192.png --out public/icons/favicon-96.png
```

Verify:

```bash
sips -g pixelWidth -g pixelHeight public/icons/favicon-48.png public/icons/favicon-96.png
```

Expected: `48 × 48` and `96 × 96`.

- [ ] **Step 4: Declare the icons in source and generated HTML**

Replace the lone 32px declaration in `index.html` with:

```html
<link rel="icon" href="/favicon.ico" sizes="any" />
<link rel="icon" type="image/png" sizes="48x48" href="/icons/favicon-48.png" />
<link rel="icon" type="image/png" sizes="96x96" href="/icons/favicon-96.png" />
<link rel="apple-touch-icon" sizes="180x180" href="/icons/apple-touch-icon.png" />
```

Extend `staticSeoPlugin()` so every generated HTML file receives missing
favicon declarations without duplicating existing tags.

- [ ] **Step 5: Add exact Nginx favicon and manifest locations**

Add behavior before the generic image regex:

```nginx
location = /favicon.ico {
    rewrite ^ /icons/favicon-96.png last;
}

location = /manifest.webmanifest {
    default_type application/manifest+json;
    try_files $uri =404;
}
```

The internal rewrite preserves a 200 response and serves valid PNG bytes from a
stable conventional URL.

- [ ] **Step 6: Extend the live verification script**

For the Googlebot homepage body, assert observable response behavior:

```bash
b_home="$(body "$BASE_URL/" "$GOOGLEBOT_UA")"
printf '%s' "$b_home" | grep -qi 'rel="icon"' \
  && ok "Googlebot / → favicon bildirimi var" \
  || bad "Googlebot / → favicon bildirimi yok"
printf '%s' "$b_home" | grep -qi '<h1[ >]' \
  && ok "Googlebot / → H1 var" \
  || bad "Googlebot / → H1 yok"
printf '%s' "$b_home" | grep -qi '<a[^>]*href="/' \
  && ok "Googlebot / → taranabilir iç bağlantı var" \
  || bad "Googlebot / → iç bağlantı yok"
printf '%s' "$b_home" | grep -qi '<script[^>]*src=' \
  && ok "Googlebot / → storefront uygulama asseti var" \
  || bad "Googlebot / → storefront uygulama asseti yok"
```

Also request `/favicon.ico`, require HTTP 200, and require an `image/` content
type.

- [ ] **Step 7: Run frontend checks and verify GREEN**

Run:

```bash
npx vitest run src/seo/faviconContract.test.ts src/security/nginxCspContract.test.ts
npm run check:nginx
npm run check:seo
npm run build
file dist/icons/favicon-48.png dist/icons/favicon-96.png
```

Expected: all tests/checks pass; build output contains both icons.

- [ ] **Step 8: Commit storefront favicon and verifier changes**

```bash
git add index.html vite.config.ts nginx.conf.template scripts/verify-seo-bot.sh \
  public/icons/favicon-48.png public/icons/favicon-96.png src/seo/faviconContract.test.ts
git commit -m "fix(seo): expose favicon and bot document contract"
```

---

### Task 4: Make Static Page SEO use `page_path` and metadata-only analysis

**Files:**
- Create: `admin-panel/frontend/src/utils/seoEditorModel.js`
- Create: `admin-panel/frontend/src/utils/__tests__/seoEditorModel.test.js`
- Modify: `admin-panel/frontend/src/components/seo/SeoTab.vue`
- Modify: `admin-panel/frontend/src/components/seo/SeoFormFields.vue`
- Modify: `admin-panel/frontend/src/utils/seoAnalyzer.js`
- Modify: `admin-panel/frontend/src/utils/__tests__/seoAnalyzer.test.js`

**Interfaces:**
- Produces:
  - `resolveSeoPathField(config, currentLang) -> string`
  - `shouldAutoGenerateSeoPath(config) -> boolean`
  - `buildSeoPreviewUrl(origin, config, fields, recordName) -> string`
  - `analysisCapabilitiesFor(doctype) -> {content: boolean, slug: boolean, primaryImage: boolean}`
- Extends `analyze(input)` with optional `capabilities`; defaults preserve all existing checks.

- [ ] **Step 1: Write failing pure editor-model tests**

Create `seoEditorModel.test.js`:

```javascript
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  analysisCapabilitiesFor,
  buildSeoPreviewUrl,
  resolveSeoPathField,
  shouldAutoGenerateSeoPath,
} from "../seoEditorModel.js";

const staticConfig = { slugField: "page_path", urlPrefix: "" };

test("Static Page SEO keeps page_path in both languages", () => {
  assert.equal(resolveSeoPathField(staticConfig, "tr"), "page_path");
  assert.equal(resolveSeoPathField(staticConfig, "en"), "page_path");
});

test("Static Page SEO never auto-generates its registered path", () => {
  assert.equal(shouldAutoGenerateSeoPath(staticConfig), false);
});

test("homepage preview is exactly the origin root", () => {
  assert.equal(
    buildSeoPreviewUrl("https://istoc.com", staticConfig, {}, "/"),
    "https://istoc.com/"
  );
});

test("Static Page SEO uses metadata-only analyzer capabilities", () => {
  assert.deepEqual(analysisCapabilitiesFor("Static Page SEO"), {
    content: false,
    slug: false,
    primaryImage: false,
  });
});
```

- [ ] **Step 2: Run editor-model tests and verify RED**

Run:

```bash
cd /Users/ahmet/Desktop/istoc/admin-panel/frontend
node --test src/utils/__tests__/seoEditorModel.test.js
```

Expected: FAIL because the helper module does not exist.

- [ ] **Step 3: Implement the pure editor model**

Create helpers with these rules:

```javascript
export function resolveSeoPathField(config, currentLang) {
  const base = config?.slugField || "slug";
  if (base === "page_path") return base;
  return currentLang === "en" ? `${base}_en` : base;
}

export function shouldAutoGenerateSeoPath(config) {
  return config?.slugField !== "page_path";
}

export function buildSeoPreviewUrl(origin, config, fields, recordName) {
  if (config?.slugField === "page_path") {
    const path = recordName?.startsWith("/") ? recordName : `/${recordName || ""}`;
    return `${origin}${path || "/"}`;
  }
  const field = resolveSeoPathField(config, "tr");
  return `${origin}${config?.urlPrefix || ""}/${fields[field] || "slug"}`;
}

export function analysisCapabilitiesFor(doctype) {
  return doctype === "Static Page SEO"
    ? { content: false, slug: false, primaryImage: false }
    : { content: true, slug: true, primaryImage: true };
}
```

- [ ] **Step 4: Write failing metadata-only analyzer tests**

Add tests that name the false-negative break:

```javascript
test("metadata-only analysis marks body, slug, and image checks NA", () => {
  const r = analyze({
    ...baseInput,
    description: "",
    slug: "/",
    primary_image_alt: "",
    capabilities: { content: false, slug: false, primaryImage: false },
  });
  for (const id of [
    "keyword_in_slug",
    "keyword_in_body",
    "keyword_in_first_paragraph",
    "keyword_density",
    "keyword_in_image_alt",
    "description_min_length",
    "slug_length",
    "sentence_length",
    "paragraph_count",
    "transition_words",
    "passive_voice",
    "consecutive_same_start",
    "heading_hierarchy",
    "image_alt_coverage",
    "internal_links",
    "keyword_in_subheadings",
    "slug_ascii_safe",
    "slug_clean",
  ]) {
    assert.equal(findCheck(r, id).status, STATUS.NA, id);
  }
});

test("default analyzer capabilities preserve listing checks", () => {
  const r = analyze(baseInput);
  assert.equal(findCheck(r, "description_min_length").status, STATUS.PASS);
  assert.equal(findCheck(r, "slug_ascii_safe").status, STATUS.PASS);
});
```

- [ ] **Step 5: Run analyzer tests and verify RED**

Run:

```bash
node --test src/utils/__tests__/seoAnalyzer.test.js
```

Expected: FAIL because capability flags are ignored.

- [ ] **Step 6: Implement analyzer capabilities**

Extend defaults:

```javascript
const DEFAULT_INPUT = {
  // existing fields
  capabilities: { content: true, slug: true, primaryImage: true },
};

function _supports(input, capability) {
  return input.capabilities?.[capability] !== false;
}
```

At the start of every body/readability/structure checker return `_na(...)`
when `content` is false. Return `_na(...)` in slug checkers when `slug` is
false, and in primary-image keyword checks when `primaryImage` is false.
Do not remove checks from `ALL_CHECKERS`; keep category layout stable and let
NA checks leave the score denominator.

- [ ] **Step 7: Wire `SeoTab` to the pure model**

Use `config.slugField` directly. Only run title-to-slug watchers when
`shouldAutoGenerateSeoPath(config.value)` is true. Build the static preview
from `recordName`, and pass:

```javascript
capabilities: analysisCapabilitiesFor(props.doctype)
```

to `analyze`. Do not write `slug`, `slug_en`, or `page_path_en` for Static Page
SEO.

- [ ] **Step 8: Show the registered static path without slug semantics**

Pass `recordName` from `SeoTab` to `SeoFormFields`, and make
`SeoFormFields`:

- resolve the field with `resolveSeoPathField`;
- show `recordName` read-only when the field is `page_path`;
- hide the auto-slug hint and character recommendation for `page_path`;
- avoid adding `_en` to `page_path`.

The fixed path never enters `store.fields`, so the existing backend save
allowlist and payload remain unchanged.

- [ ] **Step 9: Run admin tests, lint, and build**

Run:

```bash
node --test \
  src/utils/__tests__/seoEditorModel.test.js \
  src/utils/__tests__/seoAnalyzer.test.js
npm run lint
npm run build
```

Expected: PASS with no lint errors.

- [ ] **Step 10: Commit admin analyzer correctness**

```bash
git add src/utils/seoEditorModel.js src/utils/__tests__/seoEditorModel.test.js \
  src/components/seo/SeoTab.vue src/components/seo/SeoFormFields.vue \
  src/utils/seoAnalyzer.js src/utils/__tests__/seoAnalyzer.test.js
git commit -m "fix(seo): analyze static pages by editable metadata"
```

---

### Task 5: Cross-repository verification and handoff

**Files:**
- Modify only if a verification defect requires a test-first correction.

**Interfaces:**
- Consumes all previous task outputs.
- Produces an evidence-backed release handoff without deploying.

- [ ] **Step 1: Run backend SEO suite**

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core
python -m unittest discover -s tradehub_core/seo/tests -p 'test_*.py'
ruff check tradehub_core/seo
git diff --check
```

- [ ] **Step 2: Run storefront suite**

```bash
cd /Users/ahmet/Desktop/istoc/tradehubfront
npm run test:unit
npm run lint
npm run check:nginx
npm run check:seo
npm run build
git diff --check
```

- [ ] **Step 3: Run admin suite**

```bash
cd /Users/ahmet/Desktop/istoc/admin-panel/frontend
node --test src/utils/__tests__/*.test.js
npm run lint
npm run build
git -C .. diff --check
```

- [ ] **Step 4: Run local Docker HTTP parity when services are available**

```bash
cd /Users/ahmet/Desktop/istoc
curl -fsS -A 'Mozilla/5.0' http://localhost/ > /tmp/istoc-user.html
curl -fsS -A 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)' \
  http://localhost/ > /tmp/istoc-bot.html
rg '<title|rel="icon"|<h1|<a[^>]+href=|<script[^>]+src=' \
  /tmp/istoc-user.html /tmp/istoc-bot.html
```

If local services are unavailable, report this check as skipped rather than
claiming parity.

- [ ] **Step 5: Inspect each repository status and commit history**

```bash
for repo in tradehub_core tradehubfront admin-panel; do
  git -C "/Users/ahmet/Desktop/istoc/$repo" status --short --branch
  git -C "/Users/ahmet/Desktop/istoc/$repo" log -5 --oneline
done
```

Expected: only intentional commits, no unrelated modifications.

- [ ] **Step 6: Prepare production preflight commands without executing them**

The handoff must specify that, after deployment approval, production validation
will run:

```bash
BASE_URL=https://istoc.com EXPECT_NOINDEX=0 \
  /path/to/deployed/tradehubfront/scripts/verify-seo-bot.sh
```

Then manually verify normal versus Googlebot title, favicon 200/content type,
homepage hreflang, sitemap, robots, and Search Console URL Inspection. Do not
execute deployment or indexing requests in this task.

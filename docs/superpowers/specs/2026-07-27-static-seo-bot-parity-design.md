# Static SEO Bot Parity Design

## Goal

Make storefront SEO metadata updates visible in the first Googlebot HTTP
response without withholding the real storefront document, favicon, headings,
links, or JavaScript assets. Correct the related homepage hreflang and Static
Page SEO analyzer defects.

## Confirmed Current Behavior

- A normal request to `https://istoc.com/` receives the storefront build with
  the build-time title, favicon link, noscript H1, discovery links, and
  JavaScript entrypoint.
- a Googlebot request is routed by the storefront Nginx container to
  `tradehub_core.seo.page_resolver.render_static_page`.
- the production Frappe Cloud backend has no mounted `/storefront` build. The
  resolver therefore injects metadata into `_minimal_fallback_html()`.
- that fallback contains only metadata and `JavaScript gerekli.`; it has no
  favicon, H1, links, or application assets.
- the Static Page SEO analyzer maps `page_path` to a synthetic `slug` and
  analyzes an empty body, so its homepage slug, content, readability, and
  structure results do not describe the real page.
- static homepage hreflang generation builds `//` before the canonical is
  corrected to `/`.

## Chosen Architecture

Keep the existing bot-only metadata injection route, but make the resolver load
the exact storefront HTML before injection:

1. Read the configured local storefront dist first. This preserves the current
   local Docker volume contract and avoids HTTP when the artifact is available.
2. If the local template is unavailable, fetch the matching public storefront
   path from the configured `storefront_url` with an explicitly non-bot
   User-Agent.
3. Validate the response before using it: HTTPS in non-local environments,
   successful status, HTML content type, bounded response size, and an expected
   storefront marker such as the application entrypoint or `#app`.
4. Cache successful remote templates for a short, bounded TTL. Never cache the
   final SEO-injected response in this template cache; metadata must still be
   built from the current database record on each resolver execution.
5. If local and remote loading both fail, return a complete SEO-safe fallback
   rather than the current empty document. The fallback must include favicon
   links, one H1, a short homepage description where applicable, and crawlable
   navigation links. It must not claim to contain dynamic product data.
6. Inject the current backend metadata, canonical, hreflang, Open Graph,
   Twitter, and JSON-LD into the selected template.

This preserves instant backend-driven metadata while ensuring the bot receives
the same storefront application document as a user whenever the frontend is
healthy.

## Alternatives Rejected

### Cross-repository artifact delivery

Copying every frontend build into the Frappe Cloud backend would provide a
local file, but it couples independent frontend and backend release pipelines
and risks stale hashed asset references when only one repository is promoted.

### Remove bot routing

Serving the normal frontend document to every User-Agent would restore content
and favicon parity, but metadata would remain build-time until client
JavaScript fetches the backend record. It does not meet the requirement that an
admin SEO change be present in the first refreshed HTTP response.

### New SSR service

A dedicated SSR service is the preferred long-term rendering architecture, but
it is a separate project with runtime, observability, caching, and deployment
requirements beyond this corrective change.

## Component Changes

### Backend: template acquisition and injection

`tradehub_core/seo/page_resolver.py` will separate:

- local template loading;
- remote storefront template loading;
- template validation;
- safe fallback generation;
- final SEO injection.

The remote loader will use the existing centralized
`tradehub_core.seo.site_url.storefront_url()` value. It will use a short connect
and read timeout and a maximum response size. It will not accept a request URL,
host, or path from arbitrary user input beyond a path already resolved through
`STATIC_PAGES_REGISTRY`.

HTTP errors, invalid content, excessive size, and timeouts will be logged
without including secrets or response bodies. They will fall back cleanly
instead of failing the public page.

### Backend: homepage URL and structured metadata

`build_for_static_page` will build homepage hreflang directly from the canonical
`page_path`, producing:

- `https://istoc.com/`
- `https://istoc.com/en/`
- `https://istoc.com/` for `x-default`

The homepage Organization/WebSite schemas remain backend-driven. Existing site
settings remain the source of organization name, logo, and related values.

### Storefront: favicon contract

The storefront will expose stable favicon resources:

- `/favicon.ico`
- `/icons/favicon-48.png`
- `/icons/favicon-96.png`
- the existing `/icons/apple-touch-icon.png`

The document head will declare these resources. The same declarations will be
present in the backend safe fallback. The web manifest will be served with an
appropriate manifest content type through the storefront Nginx configuration.

### Admin panel: Static Page SEO analysis

`SeoTab` will use the configured `slugField` without reducing it to only
`slug` or `url_slug`.

For `Static Page SEO`:

- `page_path` is the analyzed and previewed URL;
- `/` remains `/` and is never auto-generated from the title;
- no synthetic slug is saved;
- content, readability, heading, image-alt, and internal-link checks are marked
  not applicable unless a real page-content snapshot is supplied;
- metadata, focus keyword, indexability, canonical path, and Open Graph checks
  continue to score normally.

The displayed score will therefore describe fields the editor actually owns.
It will not pretend that an empty `fallbackDescription` is the homepage body.

## Data Flow

1. Googlebot requests a registered storefront path.
2. Storefront Nginx recognizes the bot and proxies to `render_static_page`.
3. The resolver loads the current Static Page SEO record.
4. It reads the local storefront template, or fetches the normal public
   storefront HTML when the local artifact is unavailable.
5. It injects current metadata into that document and returns it.
6. Googlebot receives the favicon declarations, storefront application shell,
   crawlable fallback content, and current backend metadata in one response.
7. Normal users continue to receive the frontend container's local document;
   the existing client metadata refresh remains a consistency fallback.

## Failure Handling

- Local template missing: attempt the bounded remote fetch.
- Remote timeout or connection failure: log once per cache window and use the
  complete SEO-safe fallback.
- Non-HTML response, oversized response, or missing storefront marker: reject
  it and use the safe fallback.
- Metadata lookup failure for an unknown registered path: preserve the existing
  404 behavior.
- Cache failure: continue without cache; do not fail the public response.

## Testing Strategy

All behavior changes use red-green TDD.

### Backend unit tests

- local template wins and performs no HTTP request;
- missing local template fetches the matching storefront path;
- remote fetch uses a non-bot User-Agent and bounded timeout;
- invalid, oversized, timed-out, and failed responses use the safe fallback;
- the safe fallback contains favicon, H1, crawlable links, and no fake product
  data;
- metadata injection preserves frontend asset references and replaces stale
  title/description;
- homepage hreflang contains no double slash after the hostname;
- non-home static paths retain correct hreflang behavior.

### Storefront tests

- built/index source declares ICO, 48px, 96px, and Apple touch icons;
- all declared files exist and have the expected dimensions;
- the Nginx contract serves the manifest with a manifest-compatible content
  type;
- the live verification script fails when Googlebot HTML lacks favicon, H1,
  crawlable links, or an application entrypoint.

### Admin tests

- Static Page SEO resolves `page_path`, not `slug`;
- homepage preview URL is exactly `/`;
- title changes do not rewrite `page_path`;
- content-dependent checks are not applicable without a real content snapshot;
- non-static doctypes retain existing slug and content analysis behavior.

### Integration validation

Against a local Docker environment:

- normal and Googlebot requests return equivalent storefront shell markers;
- Googlebot receives the current backend title and description;
- both responses declare a stable favicon;
- Googlebot HTML contains one H1 or equivalent fallback H1, crawlable internal
  links, and the frontend application entrypoint;
- canonical and hreflang URLs are normalized;
- sitemap and robots behavior remains unchanged.

Production deployment and Search Console indexing requests are explicitly
outside this implementation authorization and require a separate production
preflight and confirmation.

## Acceptance Criteria

- Googlebot homepage HTML is no longer the empty minimal fallback when the
  frontend is reachable.
- Backend SEO edits appear in the first Googlebot HTTP response without a
  frontend rebuild.
- Googlebot can discover a valid 48px-or-larger favicon from the homepage.
- `/favicon.ico` returns 200.
- homepage hreflang URLs contain exactly one slash after the hostname path
  boundary.
- the Static Page SEO editor does not invent or score a homepage slug.
- the Static Page SEO editor does not report a zero-length page body when it
  has no body data source.
- existing listing, category, brand, and seller SEO behavior remains covered
  and unchanged.

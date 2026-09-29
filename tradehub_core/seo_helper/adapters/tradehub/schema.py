"""JSON-LD adaptörü — tradehub `schema_builder` (ImageObject/VideoObject/…) sarılır; sayfa düzeyi
WebPage/BreadcrumbList burada üretilir (tradehub'da karşılığı yok)."""

from __future__ import annotations

import json


def image_object(seo_fields: dict, site_url: str):
	from tradehub_core.seo.schema_builder import build_image_object

	return build_image_object(seo_fields, site_url)


def web_page(
	*,
	url: str,
	title: str,
	description: str,
	lang: str,
	date_modified: str | None = None,
	breadcrumbs: list[tuple[str, str]] | None = None,
) -> list[dict]:
	"""Builder/CMS sayfası için WebPage (+ BreadcrumbList). Saf, test edilebilir."""
	out: list[dict] = [
		{
			"@context": "https://schema.org",
			"@type": "WebPage",
			"@id": url,
			"url": url,
			"name": title,
			"description": description,
			"inLanguage": lang,
			**({"dateModified": date_modified} if date_modified else {}),
		}
	]
	if breadcrumbs:
		out.append(
			{
				"@context": "https://schema.org",
				"@type": "BreadcrumbList",
				"itemListElement": [
					{"@type": "ListItem", "position": i + 1, "name": ad, "item": link}
					for i, (ad, link) in enumerate(breadcrumbs)
				],
			}
		)
	return out


def to_script_tags(objs: list[dict]) -> str:
	return "".join(
		f'<script type="application/ld+json">{json.dumps(o, ensure_ascii=False, separators=(",", ":"))}</script>'
		for o in objs
	)

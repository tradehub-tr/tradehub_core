"""robots.txt / ortam adaptörü."""

from __future__ import annotations


def env() -> str:
	from tradehub_core.seo.robots_generator import resolve_env

	return resolve_env()


def robots_txt() -> str:
	from tradehub_core.seo.robots_generator import get_robots_txt

	return get_robots_txt()


def indexing_allowed_for_env() -> bool:
	"""prod dışı ortamlarda tradehub zaten noindex zorluyor; politika motoru bunu üstüne yazamaz."""
	return env() == "prod"

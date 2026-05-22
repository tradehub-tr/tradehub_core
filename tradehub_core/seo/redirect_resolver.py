"""
Path-bazlı redirect resolver (Faz 6).

Pure helpers (`find_matching_redirect`, `follow_redirect_chain`) Frappe
runtime'a bağımlı değildir; standalone test edilebilir.

Frappe wrapper'lar: `handle_404` (whitelist endpoint), `log_404` (queued),
`increment_hit` (queued).
"""

import re

MAX_REDIRECT_DEPTH = 3


# Pure helpers ──────────────────────────────────────────────────────────────


def find_matching_redirect(path: str, redirects: list[dict]) -> dict | None:
	"""Path için en uygun redirect bul.

	Öncelik:
	  1. Exact match (source_path == path)
	  2. Prefix match (en uzun source önce, source_path /eski/* gibi)
	  3. Regex match (ilk match)

	`redirects` listesi sadece enabled=1 olanları içermeli — bu fonksiyon
	filter yapmaz."""
	if not path or not redirects:
		return None

	# 1. Exact
	for r in redirects:
		if r.get("match_type") == "exact" and r.get("source_path") == path:
			return r

	# 2. Prefix — en uzun source önce
	prefix_candidates = [
		r for r in redirects
		if r.get("match_type") == "prefix"
		and path.startswith(_prefix_stem(r.get("source_path", "")))
	]
	if prefix_candidates:
		prefix_candidates.sort(key=lambda r: len(r.get("source_path", "")), reverse=True)
		return prefix_candidates[0]

	# 3. Regex
	for r in redirects:
		if r.get("match_type") == "regex":
			try:
				if re.match(r.get("source_path", ""), path):
					return r
			except re.error:
				continue

	return None


def _prefix_stem(source: str) -> str:
	"""Prefix source'tan '*' karakterini ve trailing /'yi temizle."""
	return source.rstrip("*").rstrip("/")


def follow_redirect_chain(
	path: str,
	redirects: list[dict],
	max_depth: int = MAX_REDIRECT_DEPTH,
) -> dict | None:
	"""Redirect zincirini takip et — loop tespiti + max depth.

	Returns:
	  {"final_path": "...", "status_code": "301"} — final hedef
	  None — match yok veya loop tespit edildi
	"""
	if not path or not redirects:
		return None

	seen = {path}
	current = path
	last_status = "301"

	for _depth in range(max_depth):
		match = find_matching_redirect(current, redirects)
		if not match:
			# İlk iterasyonda match yoksa hiç redirect yok
			return None if current == path else {"final_path": current, "status_code": last_status}

		target = match.get("target_path")
		if not target:
			return None
		if target in seen:
			# Loop
			return None

		seen.add(target)
		last_status = str(match.get("status_code") or "301")
		current = target

	# Max depth aşıldı — son hedef'i döndür (kullanıcı en azından bir yere gider)
	return {"final_path": current, "status_code": last_status}


# Frappe wrappers ───────────────────────────────────────────────────────────


def _get_active_redirects() -> list[dict]:
	"""Cache'ten veya DB'den enabled redirect listesi."""
	from tradehub_core.seo.redirect_cache import get_default_redirect_cache

	cache = get_default_redirect_cache()
	cached = cache.get_all_redirects()
	if cached is not None:
		return cached

	import frappe
	rows = frappe.get_all(
		"SEO Redirect",
		filters={"enabled": 1},
		fields=["source_path", "target_path", "status_code", "match_type"],
		limit_page_length=0,
	)
	rows = [dict(r) for r in rows]
	cache.set_all_redirects(rows)
	return rows


def increment_hit(source_path: str):
	"""Async: redirect kullanıldığında hit_count + last_hit_at update."""
	import frappe

	try:
		name = frappe.db.get_value("SEO Redirect", {"source_path": source_path}, "name")
		if not name:
			return
		frappe.db.set_value("SEO Redirect", name, {
			"hit_count": (frappe.db.get_value("SEO Redirect", name, "hit_count") or 0) + 1,
			"last_hit_at": frappe.utils.now(),
		})
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SEO redirect hit increment")


def log_404(path: str, referer: str = "", user_agent: str = ""):
	"""Async: 404 hit'i SEO 404 Log'a kaydet veya hit_count artır."""
	import frappe

	try:
		existing = frappe.db.get_value("SEO 404 Log", {"path": path}, "name")
		now = frappe.utils.now()
		if existing:
			doc = frappe.get_doc("SEO 404 Log", existing)
			doc.hit_count = (doc.hit_count or 0) + 1
			doc.last_hit_at = now
			doc.last_referer = referer[:140] if referer else doc.last_referer
			doc.last_user_agent = user_agent[:500] if user_agent else doc.last_user_agent
			doc.save(ignore_permissions=True)
		else:
			doc = frappe.new_doc("SEO 404 Log")
			doc.path = path
			doc.hit_count = 1
			doc.first_seen_at = now
			doc.last_hit_at = now
			doc.last_referer = referer[:140] if referer else None
			doc.last_user_agent = user_agent[:500] if user_agent else None
			doc.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SEO 404 log")


def handle_404(path: str = ""):
	"""Nginx error_page → bu endpoint.

	1. Redirect var mı kontrol → varsa 301/302
	2. Yoksa 404 log async + 404 sayfa servisi
	"""
	import frappe
	from werkzeug.wrappers import Response

	if not path:
		path = frappe.local.request.path if frappe.local.request else "/"

	redirects = _get_active_redirects()
	result = follow_redirect_chain(path, redirects)

	if result and result.get("final_path") and result["final_path"] != path:
		# Hit count async
		frappe.enqueue(
			"tradehub_core.seo.redirect_resolver.increment_hit",
			source_path=path,
			queue="short",
		)
		return Response(
			"",
			status=int(result["status_code"]),
			headers={"Location": result["final_path"]},
		)

	# 404 — log async
	referer = (frappe.local.request.headers.get("Referer", "")
				if frappe.local.request else "")
	user_agent = (frappe.local.request.headers.get("User-Agent", "")
					if frappe.local.request else "")
	frappe.enqueue(
		"tradehub_core.seo.redirect_resolver.log_404",
		path=path,
		referer=referer,
		user_agent=user_agent,
		queue="short",
	)

	# 404 sayfası — Faz 1 _render_404_response reuse
	from tradehub_core.seo.page_resolver import _render_404_response
	return _render_404_response()

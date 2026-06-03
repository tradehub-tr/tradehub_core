"""Sprint 6 — User.role_profile_name backfill.

Eski seed veya elle yaratılmış sub-user'larda `role_profile_name` boş kalmış
olabilir. Bu durumda `permission_resolver.get_module_mode_map` mod haritasını
boş döndürür ve sidebar tüm modülleri görünür yapar (fail-open).

Bu patch:
  1. role_profile_name boş olan tüm enabled User'ları tarar
  2. User'ın Frappe rollerine bakarak Role Profile fixture'larından en uygun
     match'i çıkarır (profile'ın tüm rolleri user'da varsa aday; en spesifik
     kazanır)
  3. Bulduğu profile'ı User kaydına yazar ve cache'i temizler

Idempotent: zaten role_profile_name set olan kullanıcılara dokunmaz.
İlk match yoksa kullanıcıyı atlar (Administrator, Guest gibi platform user'lar).
"""

from __future__ import annotations

import frappe


def execute() -> dict:
	users = frappe.get_all(
		"User",
		filters={"enabled": 1},
		fields=["name", "role_profile_name"],
	)

	updated: list[tuple[str, str]] = []
	skipped_has_profile = 0
	skipped_no_match: list[str] = []

	# Role Profile'ları bir kere yükle (N+1 önle)
	profile_specs: list[tuple[str, set[str]]] = []
	for p in frappe.get_all("Role Profile", fields=["name"]):
		try:
			doc = frappe.get_doc("Role Profile", p["name"])
		except frappe.DoesNotExistError:
			continue
		roles_set = {r.role for r in (doc.roles or []) if r.role}
		if roles_set:
			profile_specs.append((p["name"], roles_set))

	# En spesifik (en çok role içeren) profile önce denensin
	profile_specs.sort(key=lambda x: -len(x[1]))

	for u in users:
		if u["role_profile_name"]:
			skipped_has_profile += 1
			continue
		if u["name"] in ("Administrator", "Guest"):
			continue

		user_roles = set(frappe.get_roles(u["name"]))
		match: str | None = None
		best_score = 0
		for profile_name, profile_roles in profile_specs:
			if not profile_roles.issubset(user_roles):
				continue
			if len(profile_roles) > best_score:
				best_score = len(profile_roles)
				match = profile_name

		if not match:
			skipped_no_match.append(u["name"])
			continue

		frappe.db.set_value("User", u["name"], "role_profile_name", match, update_modified=False)
		updated.append((u["name"], match))

	# Cache flush — değişiklik anında etkili olsun
	from tradehub_core.utils.permission_resolver import flush_all_cache

	flush_all_cache()
	frappe.db.commit()

	return {
		"updated_count": len(updated),
		"skipped_has_profile": skipped_has_profile,
		"skipped_no_match_count": len(skipped_no_match),
		"updated": updated[:50],
	}

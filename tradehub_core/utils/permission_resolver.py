"""Sprint 6 — DB-driven RBAC resolver.

Capability ve modül kararlarını TH Capability Registry / TH Capability Grant
DocType'larından okur. Süper admin Frappe Desk'ten veya admin panelden değişiklik
yapınca anlık etki için Redis cache + doc_events flush bağlantısı.

Resolver API:
  - get_capabilities(user) -> set[str]    : User'ın efektif capability seti
  - has_capability(user, cap) -> bool      : Tek capability check
  - flush_user_cache(user) -> None         : User-bazlı cache flush
  - flush_role_profile_cache(profile)      : Profile değişince tüm cache
  - flush_all_cache() -> None              : Tüm capability cache

Cache stratejisi (POSITIVE-ONLY):
  Key: tradehub:cap:user:<user_email>
  TTL: 300 saniye (5 dakika)
  Negatif sonuç cache'lenmez (yeni grant'lar gecikmesin)

Geriye uyumluluk:
  seller_capabilities.has_seller_capability() bu modülü çağırır; DB sonucu
  None ise (capability registry'de yoksa, fail-secure) eski Python set
  fallback'i devreye girer (geçiş dönemi).
"""

from __future__ import annotations

import re

import frappe

_CACHE_KEY_PREFIX = "tradehub:cap:user:"
_MOD_CACHE_KEY_PREFIX = "tradehub:mod:user:"
_CACHE_TTL = 300  # 5 dakika


def _cache_key(user: str) -> str:
	return f"{_CACHE_KEY_PREFIX}{user}"


def get_capabilities(user: str | None = None) -> set[str]:
	"""User'ın efektif capability seti.

	Hesaplama:
	  1. User'ın role_profile_name'i çek
	  2. TH Capability Grant'tan (profile, granted=1) capability key'lerini topla
	  3. expires_at geçmiş olanları ele
	  4. is_active=0 olan capability'leri ele

	Platform admin (System Manager / Marketplace Admin) → tüm aktif capability'ler.
	Administrator → tüm capability'ler (bypass).
	Guest / boş user → boş set.
	"""
	user = user or frappe.session.user
	if not user or user in ("Guest", ""):
		return set()

	cached = frappe.cache().get_value(_cache_key(user))
	if cached is not None:
		return set(cached)

	if user == "Administrator":
		caps = _all_active_capabilities()
		frappe.cache().set_value(_cache_key(user), list(caps), expires_in_sec=_CACHE_TTL)
		return caps

	roles = set(frappe.get_roles(user))
	if {"System Manager", "Marketplace Admin"} & roles:
		caps = _all_active_capabilities()
		frappe.cache().set_value(_cache_key(user), list(caps), expires_in_sec=_CACHE_TTL)
		return caps

	role_profile = frappe.db.get_value("User", user, "role_profile_name")
	if not role_profile:
		# Profile atanmamış kullanıcı — fail-secure (boş set)
		return set()

	caps = _capabilities_for_role_profile(role_profile)
	frappe.cache().set_value(_cache_key(user), list(caps), expires_in_sec=_CACHE_TTL)
	return caps


def has_capability(user: str | None, capability: str) -> bool:
	"""Tek capability check — `get_capabilities()` üzerinden cache'li."""
	return capability in get_capabilities(user)


def _all_active_capabilities() -> set[str]:
	"""Aktif tüm capability key'leri — platform admin için."""
	rows = frappe.get_all(
		"TH Capability Registry",
		filters={"is_active": 1},
		fields=["capability_key"],
	)
	return {r["capability_key"] for r in rows}


def _capabilities_for_role_profile(role_profile: str) -> set[str]:
	"""Verilen role profile için TH Capability Grant'lardan capability seti.

	expires_at geçmiş kayıtlar elenir. capability is_active=0 olanlar elenir.
	"""
	from frappe.utils import now_datetime

	now = now_datetime()
	rows = frappe.db.sql(
		"""
		SELECT g.capability
		FROM `tabTH Capability Grant` g
		INNER JOIN `tabTH Capability Registry` r ON r.name = g.capability
		WHERE g.role_profile = %(profile)s
		  AND g.granted = 1
		  AND r.is_active = 1
		  AND (g.expires_at IS NULL OR g.expires_at > %(now)s)
		""",
		{"profile": role_profile, "now": now},
		as_dict=True,
	)
	return {r["capability"] for r in rows}


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


def flush_user_cache(user: str) -> None:
	"""Belirli user'ın capability cache'ini sil."""
	try:
		frappe.cache().delete_value(_cache_key(user))
	except Exception:
		frappe.log_error(f"flush_user_cache failed: {user}", "permission_resolver")


def flush_role_profile_cache(role_profile: str) -> None:
	"""Bu role_profile'a sahip tüm user'ların cache'ini sil.

	NOT: Frappe Redis delete_keys glob desteğine güvenir. Glob yoksa SCAN +
	per-key delete fallback'i kullanır. Bu yüzden patern: tradehub:cap:user:*
	(SCAN ile çıkar).
	"""
	try:
		# Glob ile toplu temizle — Redis SCAN
		frappe.cache().delete_keys(_CACHE_KEY_PREFIX)
	except Exception:
		frappe.log_error(f"flush_role_profile_cache failed: {role_profile}", "permission_resolver")


def flush_all_cache() -> None:
	"""Tüm capability cache (örn. Registry update sonrası)."""
	try:
		frappe.cache().delete_keys(_CACHE_KEY_PREFIX)
	except Exception:
		frappe.log_error("flush_all_cache failed", "permission_resolver")


# ---------------------------------------------------------------------------
# Hook handlers (hooks.py doc_events'ten çağrılır)
# ---------------------------------------------------------------------------


def on_capability_registry_change(doc, method=None):
	"""TH Capability Registry insert/update/delete sonrası tüm cache flush."""
	flush_all_cache()


def on_capability_grant_change(doc, method=None):
	"""TH Capability Grant insert/update/delete sonrası tüm cache flush.

	(role_profile-bazlı selective flush yerine global flush — Redis delete_keys
	zaten tüm tradehub:cap:user:* anahtarlarını siliyor.)
	"""
	flush_all_cache()


def on_user_role_change(doc, method=None):
	"""User update sonrası — role_profile_name değiştiyse cache flush."""
	if doc.has_value_changed("role_profile_name"):
		flush_user_cache(doc.name)
		_flush_module_user_cache(doc.name)


# ---------------------------------------------------------------------------
# Modül görünürlüğü (Sprint 6 — Module Registry + Module Policy)
# ---------------------------------------------------------------------------


def _mod_cache_key(user: str, panel: str) -> str:
	return f"{_MOD_CACHE_KEY_PREFIX}{user}:{panel}"


def get_module_mode_map(user: str | None = None, panel: str = "seller") -> dict[str, str]:
	"""User'ın panel'de gördüğü modüller için key → mode haritası.

	Mode:
	  - "visible" : sidebar'da göster, normal davranış
	  - "masked"  : sidebar'da göster ama field-level mask uygula (Field Mask Policy)
	  - "hidden"  : sidebar'dan komple kaldır

	Default davranış: TH Module Policy kaydı yoksa modül `visible` sayılır
	(denylist mantığı).

	Cache: Redis 5dk + user × panel granülariteli.
	"""
	user = user or frappe.session.user
	if not user or user in ("Guest", ""):
		return {}

	cached = frappe.cache().get_value(_mod_cache_key(user, panel))
	if cached is not None:
		return dict(cached)

	# Platform admin / Administrator → her şey visible
	if user == "Administrator":
		result: dict[str, str] = {}
	else:
		roles = set(frappe.get_roles(user))
		if {"System Manager", "Marketplace Admin"} & roles:
			result = {}
		else:
			role_profile = frappe.db.get_value("User", user, "role_profile_name")
			if not role_profile:
				# Eski seed / elle yaratılmış user'larda role_profile_name boş
				# kalmış olabilir. Frappe rollerinden en uygun Role Profile'ı
				# infer ederek fail-secure davranıyoruz; aksi takdirde gating
				# tamamen bypass olur.
				role_profile = _infer_role_profile_from_roles(user, roles)
			if role_profile:
				result = _module_modes_for_role_profile(role_profile, panel)
			else:
				result = {}

	frappe.cache().set_value(_mod_cache_key(user, panel), result, expires_in_sec=_CACHE_TTL)
	return result


def get_module_mode(user: str | None, module_key: str, panel: str = "seller") -> str:
	"""Belirli bir modül için mod. Policy yoksa 'visible' döner."""
	mode_map = get_module_mode_map(user, panel)
	return mode_map.get(module_key, "visible")


def get_navigation_tree(user: str | None = None, panel: str = "seller") -> list[dict]:
	"""Frontend için hazır sidebar JSON.

	Module Registry'den panel'a uyan tüm modülleri çek, Module Policy'den
	mode uygula, hidden olanları ele, kalan tree'yi return et.

	Çıktı yapısı (frontend `navigation.js`'in beklediği formatla uyumlu):
	    [
	      { section_key, label, icon, color, items: [
	          { group_label, color, items: [
	              { label, icon, route, doctype, mode, ... }
	          ]}
	      ]}
	    ]
	"""
	user = user or frappe.session.user
	mode_map = get_module_mode_map(user, panel)

	all_modules = frappe.get_all(
		"TH Module Registry",
		filters={"panel": panel, "is_active": 1},
		fields=[
			"name",
			"module_key",
			"parent_th_module_registry",
			"item_type",
			"section_key",
			"label",
			"icon",
			"color",
			"display_order",
			"route",
			"doctype_ref",
			"seller_owned",
		],
		order_by="display_order asc, label asc",
	)

	# key → record + children map
	by_key: dict[str, dict] = {}
	children_of: dict[str, list[dict]] = {}
	for m in all_modules:
		key = m["module_key"]
		mode = mode_map.get(key, "visible")
		if mode == "hidden":
			continue
		record = dict(m, mode=mode, children=[])
		by_key[key] = record
		parent = m["parent_th_module_registry"]
		if parent:
			children_of.setdefault(parent, []).append(record)

	# Tree build — section'lardan başla
	sections: list[dict] = []
	for m in all_modules:
		if m["item_type"] != "section":
			continue
		key = m["module_key"]
		if key not in by_key:
			continue
		section_record = by_key[key]
		section_record["children"] = children_of.get(key, [])
		# Group'ların item'larını da bağla
		for group in section_record["children"]:
			group["children"] = children_of.get(group["module_key"], [])
		sections.append(section_record)

	return sections


def get_hidden_module_pointers(user: str | None = None, panel: str = "seller") -> dict[str, list[str]]:
	"""Kullanıcı için "hidden" mod'a sahip modüllerin doctype/route pointerları.

	get_navigation_tree hidden modülleri tree'den tamamen düşürdüğü için
	frontend "modül bilinmiyor" durumunda fail-open davranıyordu (URL bypass).
	Bu yardımcı, router guard'ın direkt URL erişimini engelleyebilmesi için
	hidden modüllerin DocType ve route adlarını ayrı bir listede döner.
	"""
	user = user or frappe.session.user
	mode_map = get_module_mode_map(user, panel)
	if not mode_map:
		return {"doctypes": [], "routes": []}

	hidden_keys = [k for k, v in mode_map.items() if v == "hidden"]
	if not hidden_keys:
		return {"doctypes": [], "routes": []}

	rows = frappe.get_all(
		"TH Module Registry",
		filters={"module_key": ["in", hidden_keys], "is_active": 1},
		fields=["module_key", "route", "doctype_ref"],
	)
	doctypes = sorted({r["doctype_ref"] for r in rows if r.get("doctype_ref")})
	routes = sorted({r["route"] for r in rows if r.get("route")})
	return {"doctypes": doctypes, "routes": routes}


def _module_modes_for_role_profile(role_profile: str, panel: str) -> dict[str, str]:
	"""Verilen role profile için modül → mode haritası.

	effective_from/to ile aktif olan kayıtlar dahil edilir.
	"""
	from frappe.utils import getdate, today

	now = getdate(today())
	rows = frappe.db.sql(
		"""
		SELECT p.module, p.mode
		FROM `tabTH Module Policy` p
		INNER JOIN `tabTH Module Registry` r ON r.name = p.module
		WHERE p.role_profile = %(profile)s
		  AND r.panel = %(panel)s
		  AND r.is_active = 1
		  AND (p.effective_from IS NULL OR p.effective_from <= %(now)s)
		  AND (p.effective_to IS NULL OR p.effective_to >= %(now)s)
		""",
		{"profile": role_profile, "panel": panel, "now": now},
		as_dict=True,
	)
	return {r["module"]: r["mode"] for r in rows}


def _infer_role_profile_from_roles(user: str, user_roles: set[str]) -> str | None:
	"""User'ın Frappe rollerinden en uygun Role Profile'ı çıkar.

	Role Profile'lar (Has Role child table) belirli bir Frappe rol kümesini
	taşır. Kullanıcının rolleri bir profile'ın TÜM rollerini kapsıyorsa o
	profile aday olur; aday profile'lar içinden EN SPESİFİK (en çok rol içeren)
	seçilir. Bu, seller_users.invite_sub_user flow'u dışında elle ya da eski
	seed ile yaratılmış kullanıcılarda gating'in çalışmaya devam etmesini sağlar.

	Returns: profile name veya None (hiçbir uyum yoksa).
	"""
	cache_key = f"tradehub:rp_infer:{user}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached or None

	best_match: str | None = None
	best_score = 0
	profiles = frappe.get_all("Role Profile", fields=["name"])
	for p in profiles:
		try:
			doc = frappe.get_cached_doc("Role Profile", p["name"])
		except frappe.DoesNotExistError:
			continue
		profile_roles = {r.role for r in (doc.roles or []) if r.role}
		if not profile_roles or not profile_roles.issubset(user_roles):
			continue
		score = len(profile_roles)
		if score > best_score:
			best_score = score
			best_match = p["name"]

	frappe.cache().set_value(cache_key, best_match or "", expires_in_sec=_CACHE_TTL)
	return best_match


def _flush_module_user_cache(user: str) -> None:
	try:
		for panel in ("admin", "seller", "storefront", "shared"):
			frappe.cache().delete_value(_mod_cache_key(user, panel))
	except Exception:
		frappe.log_error(f"_flush_module_user_cache failed: {user}", "permission_resolver")


def flush_module_cache() -> None:
	"""Tüm module cache (Registry/Policy değişimi sonrası)."""
	try:
		frappe.cache().delete_keys(_MOD_CACHE_KEY_PREFIX)
	except Exception:
		frappe.log_error("flush_module_cache failed", "permission_resolver")


def on_module_registry_change(doc, method=None):
	"""TH Module Registry insert/update/delete sonrası tüm modül cache flush."""
	flush_module_cache()


def on_module_policy_change(doc, method=None):
	"""TH Module Policy insert/update/delete sonrası tüm modül cache flush."""
	flush_module_cache()


# ---------------------------------------------------------------------------
# Sprint 4 — Field-level maskeleme pattern'leri
# ---------------------------------------------------------------------------

_IBAN_CLEAN_RE = re.compile(r"\s+")
_EMAIL_RE = re.compile(r"^([^@]+)@(.+)$")
_BULLET = "•"


def _mask_last4(value: str) -> str:
	s = str(value)
	if len(s) <= 4:
		return _BULLET * len(s)
	return _BULLET * 4 + s[-4:]


def _mask_initials(value: str) -> str:
	"""'Ali Yılmaz' → 'A••• Y•••' (her kelimenin ilk harfi + 3 bullet)."""
	s = str(value).strip()
	if not s:
		return ""
	parts = []
	for word in s.split():
		if word:
			parts.append(word[0] + _BULLET * 3)
	return " ".join(parts)


def _mask_iban_xxx_last4(value: str) -> str:
	"""'TR74 1111 2222 3333 4444 1923' → 'TR•• •••• •••• •••• •••• 1923'.

	IBAN format genelde 26 karakter (TR), boşluklarla gruplu. Son 4 görünür,
	ülke kodu ilk 2 görünür, geri kalan maskelenir.
	"""
	s = str(value)
	cleaned = _IBAN_CLEAN_RE.sub("", s)
	if len(cleaned) < 6:
		return _BULLET * len(s)
	# İlk 2 (ülke kodu) + maskelenmiş orta + son 4
	country = cleaned[:2]
	last4 = cleaned[-4:]
	middle = _BULLET * (len(cleaned) - 6)
	# 4'lü gruplara böl (TR74 •••• •••• ••••...)
	masked = country + middle + last4
	groups = [masked[i : i + 4] for i in range(0, len(masked), 4)]
	return " ".join(groups)


def _mask_bullets(value: str) -> str:
	"""Tüm karakteri bullet'la, uzunluğu koru."""
	return _BULLET * len(str(value))


def _mask_email_domain(value: str) -> str:
	"""'ali.yilmaz@example.com' → 'a•••@example.com'."""
	s = str(value)
	m = _EMAIL_RE.match(s)
	if not m:
		# Email değil — fail-safe: tamamen maskele
		return _BULLET * len(s)
	local, domain = m.group(1), m.group(2)
	if not local:
		return s
	visible = local[0] if len(local) > 1 else local
	return f"{visible}{_BULLET * 3}@{domain}"


_MASK_PATTERNS = {
	"none": lambda _v: None,
	"last4": _mask_last4,
	"initials": _mask_initials,
	"iban_xxx_last4": _mask_iban_xxx_last4,
	"bullets": _mask_bullets,
	"email_domain": _mask_email_domain,
}


def apply_field_mask(value, pattern: str):
	"""Belirtilen pattern ile değeri maskeler.

	Args:
	    value: Maskelenecek değer (str, int, float, None vs.)
	    pattern: "none" | "last4" | "initials" | "iban_xxx_last4" | "bullets" | "email_domain"

	Returns:
	    Maskelenmiş string veya None (pattern="none" için).

	Bilinmeyen pattern → fail-secure: None döner (alanı tamamen gizle).
	None veya boş value → değer olduğu gibi (maskelenecek bir şey yok).
	"""
	if value is None or value == "":
		return value
	fn = _MASK_PATTERNS.get(pattern)
	if fn is None:
		# Tanımsız pattern fail-secure
		return None
	return fn(value)

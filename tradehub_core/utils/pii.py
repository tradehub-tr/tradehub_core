# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 1.3 — PII (Hassas Bilgi) yardımcıları.

Frappe'nin built-in `permlevel` mekanizması alan-level erişimi kontrol eder:
  - Field'a `permlevel=N` atanır
  - Role'ün o doctype × permlevel kombinasyonu için read perm'i yoksa,
    API response'larında alan değeri **null** veya **gizli** olarak gelir.

Bu modül **ek olarak**:
  - has_pii_access(user, doctype, permlevel) — explicit kontrol
  - mask_value(value, kind) — UI / log için maskeleme (örn. "TR12 **** 0034")
  - get_user_max_permlevel(user, doctype) — kullanıcının erişebildiği en üst seviye

Önemli: Bu modül permlevel mekanizmasını **bypass etmez**, onun üzerinde
güvenli helper'lar sunar.

Detay: docs/yetki/01-karar-dosyasi.md §3, docs/yetki/03-doctype-sablonlari.md
"""

from __future__ import annotations

import frappe

# Maskeleme strateji kataloğu
_MASK_STRATEGIES: dict[str, str] = {
	"tax_id": "last_4",  # 1234567890 → ******7890
	"iban": "iban",  # TR12... → TR12 **** **** **** **** **34
	"phone": "last_4",  # +905321234567 → ********4567
	"email": "email",  # ahmet@x.com → a****@x.com
	"identity": "first_3",  # 12345678901 → 123********
	"generic": "generic",  # her şey → ********
}


def has_pii_access(user: str | None, doctype: str, permlevel: int) -> bool:
	"""Kullanıcı verilen doctype'ın permlevel'ına okuma erişimine sahip mi?

	Args:
	    user: Frappe user ID (None → session.user)
	    doctype: DocType adı
	    permlevel: 0/1/2/3

	Returns:
	    True: en az bir role permlevel için read=1
	    False: erişim yok (UI'da maskeli görür)
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return permlevel == 0  # Guest sadece permlevel 0

	# System Manager bypass
	roles = set(frappe.get_roles(user))
	if "System Manager" in roles or "Administrator" in roles:
		return True

	# DocType'ın permissions'ında bu role × permlevel için read var mı?
	# Hem standart DocPerm hem Custom DocPerm'e bak.
	for source in ("DocPerm", "Custom DocPerm"):
		exists = frappe.db.exists(
			source,
			{
				"parent": doctype,
				"role": ["in", list(roles)],
				"permlevel": permlevel,
				"read": 1,
			},
		)
		if exists:
			return True

	return False


def get_user_max_permlevel(user: str | None, doctype: str) -> int:
	"""Kullanıcının verilen doctype için erişebildiği en üst permlevel.

	Returns:
	    0..3 — read=1 olan en yüksek permlevel
	    -1 — hiç erişim yok
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return 0  # default visibility

	roles = set(frappe.get_roles(user))
	if "System Manager" in roles or "Administrator" in roles:
		return 9  # max

	max_lvl = -1
	for source in ("DocPerm", "Custom DocPerm"):
		rows = frappe.get_all(
			source,
			filters={
				"parent": doctype,
				"role": ["in", list(roles)],
				"read": 1,
			},
			fields=["permlevel"],
		)
		for row in rows:
			lvl = int(row.get("permlevel") or 0)
			if lvl > max_lvl:
				max_lvl = lvl

	return max_lvl


def mask_value(value: str | None, kind: str = "generic") -> str:
	"""Verilen değeri kategorisine göre maskele (UI / log için).

	Args:
	    value: Maskelenecek string (None → boş)
	    kind: Maskeleme türü — 'tax_id', 'iban', 'phone', 'email', 'identity', 'generic'

	Returns:
	    Maskelenmiş string. value None/boş ise boş string.

	Örnekler:
	    >>> mask_value("1234567890", "tax_id")
	    '******7890'
	    >>> mask_value("TR120006200012345678901234", "iban")
	    'TR12 **** **** **** **** **34'
	    >>> mask_value("ahmet.yilmaz@firma.com", "email")
	    'a***********@firma.com'
	    >>> mask_value("+905321234567", "phone")
	    '*********4567'
	"""
	if not value:
		return ""

	value = str(value).strip()
	strategy = _MASK_STRATEGIES.get(kind, "generic")

	if strategy == "last_4":
		if len(value) <= 4:
			return "*" * len(value)
		return "*" * (len(value) - 4) + value[-4:]

	if strategy == "first_3":
		if len(value) <= 3:
			return "*" * len(value)
		return value[:3] + "*" * (len(value) - 3)

	if strategy == "iban":
		# TR12 0006 2000 1234 5678 9012 34 → TR12 **** **** **** **** **34
		# Boşlukları temizle, 4'erli grupla, ilk grup ve son 2 hane görünür
		raw = value.replace(" ", "")
		if len(raw) < 6:
			return "*" * len(value)
		first = raw[:4]
		last = raw[-2:]
		middle_groups = (len(raw) - 6) // 4
		extra = (len(raw) - 6) % 4
		masked_middle = " ".join(["****"] * middle_groups)
		if extra:
			masked_middle = (masked_middle + " " + "*" * extra).strip()
		return f"{first} {masked_middle} **{last}".strip()

	if strategy == "email":
		# a***@domain
		if "@" not in value:
			return mask_value(value, "generic")
		local, _, domain = value.partition("@")
		if len(local) <= 1:
			return f"{local}***@{domain}"
		return f"{local[0]}{'*' * (len(local) - 1)}@{domain}"

	# generic — her şey *
	if len(value) <= 4:
		return "*" * len(value)
	return value[:1] + "*" * (len(value) - 2) + value[-1:]


def get_pii_fieldnames(doctype: str, min_permlevel: int = 1) -> list[str]:
	"""DocType'ın permlevel >= min_permlevel olan field adları.

	Args:
	    doctype: DocType adı
	    min_permlevel: Eşik (varsayılan 1; permlevel >= 1 = PII)

	Returns:
	    Field adlarının listesi
	"""
	# DocField ve Custom Field'lardan çek
	docfields = frappe.get_all(
		"DocField",
		filters={"parent": doctype, "permlevel": [">=", min_permlevel]},
		pluck="fieldname",
	)
	custom_fields = frappe.get_all(
		"Custom Field",
		filters={"dt": doctype, "permlevel": [">=", min_permlevel]},
		pluck="fieldname",
	)
	# Property Setter'lardan da çek (mevcut field'ın permlevel'ı override edilmiş)
	property_setters = frappe.get_all(
		"Property Setter",
		filters={
			"doc_type": doctype,
			"property": "permlevel",
		},
		fields=["field_name", "value"],
	)
	for ps in property_setters:
		# ps dict ya da Frappe Document — hem ikisi de _get yardımıyla erişilebilir
		value = ps.get("value") if isinstance(ps, dict) else getattr(ps, "value", None)
		field_name = ps.get("field_name") if isinstance(ps, dict) else getattr(ps, "field_name", None)
		if not value or not field_name:
			continue
		try:
			if (
				int(value) >= min_permlevel
				and field_name not in docfields
				and field_name not in custom_fields
			):
				docfields.append(field_name)
		except (ValueError, TypeError):
			continue

	return list(set(docfields + custom_fields))


# ---------------------------------------------------------------------------
# FAZ 2.6 — Region-aware PII access (KVKK/GDPR uyum)
# ---------------------------------------------------------------------------


def has_pii_access_for_target(
	user: str | None,
	doctype: str,
	permlevel: int,
	target_region: str | None = None,
) -> bool:
	"""permlevel kontrolü + region check (KVKK/GDPR uyumu için).

	İki katmanlı kontrol:
	  1. has_pii_access(): rol permlevel'ı yeterli mi
	  2. region check: user'ın bölgesi target_region'ı kapsıyor mu (varsa)

	Örnek:
	  - EU buyer'ın PII'sini görmek için: user EU bölgesinde olmalı
	  - Compliance Officer global erişimli → region check bypass

	Args:
	    user: User
	    doctype: DocType
	    permlevel: 1-3
	    target_region: Kayıt sahibinin bölgesi (örn. buyer'ın region'u)

	Returns:
	    True: izin var
	    False: permlevel yok VEYA region uyumsuz
	"""
	# Önce permlevel kontrolü
	if not has_pii_access(user, doctype, permlevel):
		return False

	# Compliance Officer / System Manager region bypass
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user)) if user else set()
	if roles & {"System Manager", "Administrator", "Compliance Officer"}:
		return True

	# Region check (target_region varsa)
	if not target_region:
		return True  # Region kısıtı yok

	# User'ın bölgeleri
	from tradehub_core.services.abac_context import build_region_context

	ctx = build_region_context(user)
	user_regions = ctx.get("user_regions", [])

	return target_region in user_regions


def get_jurisdiction_for_region(region: str) -> str | None:
	"""Region → jurisdiction (KVKK/GDPR/MENA/CIS/OTHER)."""
	if not region:
		return None
	return frappe.db.get_value("Region", region, "jurisdiction")


def is_strict_jurisdiction(region: str) -> bool:
	"""Region 'sıkı' jurisdiction altında mı (KVKK veya GDPR)?

	Sıkı bölgelerde PII'ye erişim için ekstra region check şart.
	"""
	jurisdiction = get_jurisdiction_for_region(region)
	return jurisdiction in ("KVKK", "GDPR")

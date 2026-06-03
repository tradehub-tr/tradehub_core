"""Sprint 5 — Generic field-level PII maskeleme on_load handler.

Frappe `on_load` doc_event'i her `frappe.get_doc()` çağrısı sonrası tetiklenir.
Bu handler kayıt sahibi olmayan + ilgili capability'si olmayan kullanıcılar
için DocType'ın PII alanlarını maskeleyici string ile değiştirir.

Desteklenen DocType'lar:
  - Contact: e-posta + telefon (view.customer_pii)
  - Admin Seller Profile: IBAN/bank/tax_id (view.bank_info + view.tax_id)
  - User Profile: IBAN/bank/tax_id (view.bank_info + view.tax_id)
  - Gelecekte: CRM Lead, CRM Deal, CRM Organization (Frappe CRM yüklenince)

Bypass koşulları (hiç maskeleme yapmaz):
  - Administrator
  - Platform admin (System Manager / Marketplace Admin)
  - Kayıt sahibi (owner == session.user)
  - Field'a karşılık gelen capability açık

Sınırlamalar:
  - `on_load` SADECE `get_doc` çağrısında tetiklenir. `get_list` çıktısında
    maskeleme yapmaz; list endpoint override Faz 2'de eklenebilir.
  - Maskeleme okuma-zamanlı: DB'deki gerçek değer değişmez.
"""

from __future__ import annotations

import frappe

from tradehub_core.utils.permission_resolver import apply_field_mask
from tradehub_core.utils.seller_capabilities import has_seller_capability

_PLATFORM_BYPASS_ROLES = frozenset({"System Manager", "Marketplace Admin", "Administrator"})


# DocType → field eşlemesi. Her field (mask_pattern, is_child_table, capability)
# tuple'ıyla tanımlı; child_table=True ise child row'ları gezilir.
_PII_FIELDS_BY_DOCTYPE: dict[str, list[tuple[str, str, bool, str]]] = {
	"Contact": [
		("email_id", "email_domain", False, "view.customer_pii"),
		("phone", "last4", False, "view.customer_pii"),
		("mobile_no", "last4", False, "view.customer_pii"),
		("email_ids", "email_domain", True, "view.customer_pii"),
		("phone_nos", "last4", True, "view.customer_pii"),
	],
	"Admin Seller Profile": [
		("iban", "iban_xxx_last4", False, "view.bank_info"),
		("bank_name", "bullets", False, "view.bank_info"),
		("account_holder", "initials", False, "view.bank_info"),
		("tax_id", "last4", False, "view.tax_id"),
	],
	"User Profile": [
		("iban", "iban_xxx_last4", False, "view.bank_info"),
		("bank_name", "bullets", False, "view.bank_info"),
		("account_holder_name", "initials", False, "view.bank_info"),
		("tax_id", "last4", False, "view.tax_id"),
	],
	# Frappe CRM app yüklenince eklenecek:
	# "CRM Lead": [("email", "email_domain", False, "view.customer_pii"), ...]
}


def _is_platform_bypass(user: str) -> bool:
	"""Administrator / platform admin → maskeleme yok."""
	if not user or user in ("Guest", ""):
		return True
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	return bool(roles & _PLATFORM_BYPASS_ROLES)


def _is_record_owner(doc, user: str) -> bool:
	"""Kayıt sahibi kendi PII'sini her zaman açık görür.

	User Profile için: `user` field'ı session.user'a eşit ise sahip.
	Admin Seller Profile için: `user` field'ı session.user'a eşit ise sahip.
	Diğer DocType'lar için: standart `owner` field'ı.
	"""
	if doc.doctype in ("User Profile", "Admin Seller Profile"):
		return doc.get("user") == user
	return doc.get("owner") == user


def _mask_value(value, pattern: str):
	"""apply_field_mask wrapper — None/boş için no-op."""
	if value is None or value == "":
		return value
	return apply_field_mask(value, pattern)


def mask_pii_fields(doc, method=None) -> None:
	"""`on_load` doc_event handler.

	doc: Frappe Document
	method: "on_load" (otomatik)

	Her field için ayrı capability kontrolü:
	  - Field A capability'si açıksa A açık görünür
	  - Field B kapalıysa B maskelenir
	Aynı kayıtta karışık görünebilir (örn. tax_id açık, iban maskeli).
	"""
	try:
		user = frappe.session.user
		# Global bypass — Administrator / platform admin / kayıt sahibi
		if _is_platform_bypass(user):
			return

		field_spec = _PII_FIELDS_BY_DOCTYPE.get(doc.doctype)
		if not field_spec:
			return

		# Kayıt sahibi tüm field'ları açık görür
		is_owner = _is_record_owner(doc, user)

		# Performans: aynı capability'yi tekrar tekrar sorgulamamak için cache
		cap_cache: dict[str, bool] = {}

		def _can(cap: str) -> bool:
			if cap not in cap_cache:
				cap_cache[cap] = has_seller_capability(cap, user)
			return cap_cache[cap]

		masked_field_names: list[str] = []
		for fieldname, pattern, is_child, capability in field_spec:
			if is_owner or _can(capability):
				continue  # bu field açık görünür

			if is_child:
				rows = doc.get(fieldname) or []
				for row in rows:
					_mask_child_row(row, fieldname, pattern)
			else:
				val = doc.get(fieldname)
				if val:
					doc.set(fieldname, _mask_value(val, pattern))
			masked_field_names.append(fieldname)

		# Frontend için maskeleme rozeti gösterimi
		if masked_field_names:
			doc.flags._masked_fields = masked_field_names
			# Sprint 5 — Rate-limited audit log (per user+doctype, 1 saat TTL)
			_maybe_log_mask_event(doc, masked_field_names, user)
	except Exception:
		frappe.log_error(
			f"PII mask failed for {doc.doctype}/{doc.name}",
			"crm_masking.mask_pii_fields",
		)


# Rate limit window — aynı (user, doctype) için bu süre içinde yalnız 1 log
_MASK_LOG_TTL_SECONDS = 3600


def apply_list_masking(
	rows: list[dict],
	doctype: str,
	user: str | None = None,
) -> list[dict]:
	"""Sprint 5 Faz 2 — frappe.get_list çıktısına PII maskeleme uygular.

	`on_load` doc_event'i SADECE `frappe.get_doc` çağrısında tetiklenir, list
	endpoint'lerinde tetiklenmez. Custom whitelist list endpoint'leri bu
	helper'ı çağırarak satırlardaki PII field'larını maskeler.

	Args:
	    rows: frappe.get_list'in döndürdüğü liste (mutate edilir)
	    doctype: Maskeleme spec'i için DocType adı
	    user: Maskelemeyi hangi kullanıcıya göre yapacağız (default session.user)

	Returns:
	    Mutate edilmiş rows listesi (aynı obje — convenience için döner).

	Notlar:
	  - Child table field'ları list response'unda olmaz → atlanır.
	  - Owner field doctype'a göre değişir (User Profile/Admin Seller
	    Profile için "user", diğerleri için "owner").
	  - Maskelenen field'lar her satırın `_masked_fields` field'ında listelenir.
	"""
	user = user or frappe.session.user
	if _is_platform_bypass(user):
		return rows

	field_spec = _PII_FIELDS_BY_DOCTYPE.get(doctype)
	if not field_spec:
		return rows

	cap_cache: dict[str, bool] = {}

	def _can(cap: str) -> bool:
		if cap not in cap_cache:
			cap_cache[cap] = has_seller_capability(cap, user)
		return cap_cache[cap]

	# Hangi field owner kimliği taşıyor?
	owner_field = "user" if doctype in ("User Profile", "Admin Seller Profile") else "owner"

	for row in rows:
		# Kayıt sahibi → tam görür
		if row.get(owner_field) == user:
			continue

		masked: list[str] = []
		for fieldname, pattern, is_child, capability in field_spec:
			if is_child:
				continue  # list response'unda child table yok
			if _can(capability):
				continue
			val = row.get(fieldname)
			if val:
				row[fieldname] = _mask_value(val, pattern)
				masked.append(fieldname)

		if masked:
			row["_masked_fields"] = masked

	return rows


def _maybe_log_mask_event(doc, masked_fields: list[str], user: str) -> None:
	"""Best-effort rate-limited audit log.

	Aynı user + doctype için saatte 1 log yazılır. Yoğun trafikte
	authorization_decision_log şişmesini önler.
	"""
	cache_key = f"pii_mask_log:{user}:{doc.doctype}"
	try:
		if frappe.cache().get_value(cache_key):
			return
	except Exception:
		# Cache erişimi başarısız — log yazmadan çık (fail-open için değil,
		# best-effort: cache yoksa log da yazmıyoruz, aksi takdirde rate
		# limit sağlanamaz).
		return

	try:
		from tradehub_core.audit import (
			DECISION_FIELD_MASKED,
			LAYER_L3,
			SEVERITY_LOW,
			log_decision,
		)

		log_decision(
			actor=user,
			action="pii.field_masked",
			decision=DECISION_FIELD_MASKED,
			rule_id="field_masking.on_load",
			layer=LAYER_L3,
			object_doctype=doc.doctype,
			object_name=doc.get("name"),
			severity=SEVERITY_LOW,
			context={
				"masked_fields": masked_fields,
				"field_count": len(masked_fields),
			},
		)
		frappe.cache().set_value(cache_key, 1, expires_in_sec=_MASK_LOG_TTL_SECONDS)
	except Exception:
		# Log atılamadıysa bile maskeleme devam etmeli — sessizce devam
		pass


def _mask_child_row(row, parent_field: str, pattern: str) -> None:
	"""Contact Email / Contact Phone child satırlarında PII alanını maskele.

	Parent field adından child'daki gerçek field adını çıkarsa:
	  - email_ids → "email_id"
	  - phone_nos → "phone"
	"""
	child_field = None
	if parent_field == "email_ids":
		child_field = "email_id"
	elif parent_field == "phone_nos":
		child_field = "phone"

	if not child_field:
		return

	val = row.get(child_field)
	if val:
		row.set(child_field, _mask_value(val, pattern))

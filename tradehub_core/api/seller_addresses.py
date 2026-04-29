"""
Seller Addresses API — Satıcının kendi adres defteri (gönderim/pickup adresleri).

Buyer adres API'sinin kind="Seller" varyantıdır. Buyer ile aynı `Addresses`
DocType'ını kullanır; `kind` ayrımı ile birbirinden izole edilir.

Kritik fark:
- Buyer adresi: ürün buraya teslim edilecek (delivery)
- Seller adresi: ürün buradan gönderilecek (pickup/origin)

Session user → Seller Profile name çevrimi `_resolve_seller_profile()` ile yapılır;
böylece UI tarafında seller field'ını manuel doldurmaya gerek kalmaz.
"""

import re

import frappe
from frappe import _

from tradehub_core.api._address_validators import (
	AddressValidationError,
	normalize_country_code,
	parse_address_payload,
	validate_country_code,
	validate_field_lengths,
	validate_postal_code,
)
from tradehub_core.utils.phone import canonicalize_phone, split_e164

MAX_ADDRESSES = 10

# TR telefon formatı — buyer.py ile senkron
_PHONE_RE = re.compile(r"^(\+90|0)?[2-5]\d{9}$")
_INTL_PHONE_RE = re.compile(r"^\d{7,15}$")
_PHONE_CLEAN_RE = re.compile(r"[\s\-()]")


def _normalize_phone(raw):
	return _PHONE_CLEAN_RE.sub("", raw or "")


def _validate_phone(raw, prefix=None):
	normalized = _normalize_phone(raw)
	if not prefix or prefix == "+90":
		return bool(_PHONE_RE.match(normalized))
	digits_only = normalized.lstrip("+")
	return bool(_INTL_PHONE_RE.match(digits_only))


# ── helpers ──────────────────────────────────────────────────────────────────


def _require_login():
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Bu işlem için giriş yapmanız gerekiyor"), frappe.AuthenticationError)
	return user


def _resolve_seller_profile(user):
	"""Session user → Seller Profile name. Yoksa hata fırlatır."""
	sp_name = frappe.db.get_value("Seller Profile", {"user": user}, "name")
	if not sp_name:
		frappe.throw(
			_("Bu kullanıcıya bağlı bir Seller Profile bulunamadı"),
			frappe.DoesNotExistError,
		)
	return sp_name


def _check_address_owner(address_id, seller_name):
	"""Adresin bu seller'a ait olduğunu doğrular."""
	row = frappe.db.get_value("Addresses", address_id, ["seller", "kind"], as_dict=True)
	if not row:
		frappe.throw(_("Adres bulunamadı"), frappe.DoesNotExistError)
	if row.kind != "Seller" or row.seller != seller_name:
		frappe.throw(_("Bu adrese erişim yetkiniz yok"), frappe.PermissionError)


def _doc_to_dict(doc):
	return {
		"id": doc.name,
		"title": doc.title or "",
		"contact_name": doc.contact_name or "",
		"company": doc.company or "",
		"phone_prefix": doc.phone_prefix or "+90",
		"phone": doc.phone or "",
		"country": doc.country or "TR",
		"state": doc.state or "",
		"city": doc.city or "",
		"street": doc.street or "",
		"apartment": doc.apartment or "",
		"postal_code": doc.postal_code or "",
		"note": doc.note or "",
		"is_default": bool(doc.is_default),
	}


def _lock_seller_addresses(seller_name):
	"""
	Seller'ın tüm Seller adres satırlarını `FOR UPDATE` ile kilitler ve
	(name, is_default, modified) tuple'larını creation ASC sırayla döner.

	buyer.py._lock_user_addresses ile aynı amaç: adres mutation'larının
	tek bir lock order'ı paylaşması.

	Çözdüğü iki kritik bug:
	1) MAX_ADDRESSES count+insert race (count'tan önce lock → atomik)
	2) save_address vs save_address / delete_address deadlock (aynı lock
	   order = serialize, deadlock imkansız)
	"""
	return frappe.db.sql(
		"""
		SELECT name, is_default, modified
		FROM `tabAddresses`
		WHERE seller = %(seller)s AND kind = 'Seller'
		ORDER BY creation ASC
		FOR UPDATE
		""",
		{"seller": seller_name},
		as_dict=True,
	)


def _ensure_one_default(seller_name):
	"""
	Seller'ın tam olarak bir varsayılan adresi olmasını garantiler.

	Davranış:
	- Hiç default yoksa en eski adres default yapılır (stabil fallback).
	- Birden fazla default varsa (broken state) **en son modified olan** korunur,
	  diğerleri temizlenir. Bu semantik save_address'in "yeni eklenen / son
	  düzenlenen adresi default yap" kullanıcı niyetiyle tutarlıdır.
	- Seller'ın hiç adresi yoksa boş string döner.

	**Atomik default_id okuma:** Aynı transaction içinde lock'u tutarak güncel
	default'un name'ini döndürür; çağıran taraf ekstra SELECT çalıştırmadan
	return değerini doğrudan response'a koyabilir (race-free).

	Race-safe: `_lock_seller_addresses` ile row-level lock alır.
	"""
	locked = _lock_seller_addresses(seller_name)
	if not locked:
		return ""
	defaults = [row for row in locked if row.is_default]
	if len(defaults) == 1:
		return defaults[0].name
	if len(defaults) > 1:
		# Çoklu default — broken state. En son modified olanı koru (kullanıcının
		# son niyeti), diğerlerini temizle. Tie-break name ile (deterministic).
		keep = max(defaults, key=lambda r: (r.modified, r.name))
		for row in defaults:
			if row.name != keep.name:
				frappe.db.set_value("Addresses", row.name, "is_default", 0)
		return keep.name
	# Hiç default yok — en eskisini default yap
	keep = locked[0]
	frappe.db.set_value("Addresses", keep.name, "is_default", 1)
	return keep.name


# ── public endpoints ──────────────────────────────────────────────────────────


@frappe.whitelist()
def get_addresses():
	"""Oturumdaki seller'ın tüm adreslerini döndürür."""
	user = _require_login()
	seller_name = _resolve_seller_profile(user)
	rows = frappe.get_all(
		"Addresses",
		filters={"seller": seller_name, "kind": "Seller"},
		fields=[
			"name",
			"title",
			"contact_name",
			"company",
			"phone_prefix",
			"phone",
			"country",
			"state",
			"city",
			"street",
			"apartment",
			"postal_code",
			"note",
			"is_default",
		],
		order_by="is_default desc, creation asc",
	)
	return [
		{
			"id": r["name"],
			"title": r["title"] or "",
			"contact_name": r["contact_name"] or "",
			"company": r["company"] or "",
			"phone_prefix": r["phone_prefix"] or "+90",
			"phone": r["phone"] or "",
			"country": r["country"] or "TR",
			"state": r["state"] or "",
			"city": r["city"] or "",
			"street": r["street"] or "",
			"apartment": r["apartment"] or "",
			"postal_code": r["postal_code"] or "",
			"note": r["note"] or "",
			"is_default": bool(r["is_default"]),
		}
		for r in rows
	]


@frappe.whitelist()
def save_address(address_json):
	"""Adres oluşturur veya günceller. Kaydedilen adresi ve aktif default id'sini döndürür."""
	user = _require_login()
	seller_name = _resolve_seller_profile(user)

	try:
		data = parse_address_payload(address_json)
		if data.get("country"):
			data["country"] = normalize_country_code(data["country"].strip())
		validate_field_lengths(data)
	except AddressValidationError as exc:
		frappe.throw(_(str(exc)))

	address_id = (data.get("id") or "").strip()

	required_fields = {
		"title": _("Adres Başlığı"),
		"contact_name": _("İrtibat Kişisi"),
		"company": _("Şirket Adı"),
		"phone": _("Telefon"),
		"state": _("İl"),
		"street": _("Adres Satırı"),
	}
	for field, label in required_fields.items():
		if not (data.get(field) or "").strip():
			frappe.throw(_("{0} alanı zorunludur").format(label))

	# Telefon — TR için E.164 kanonikleştirme, non-TR için mevcut gevşek kontrol.
	phone_prefix_in = (data.get("phone_prefix") or "+90").strip()
	phone_raw = data.get("phone") or ""
	if phone_prefix_in == "+90":
		canonical_phone = canonicalize_phone(phone_raw)
		if not canonical_phone or not canonical_phone.startswith("+90"):
			frappe.throw(_("Geçerli bir telefon numarası giriniz (örn. 0212 555 00 00)"))
		# NB: avoid binding "_" — that shadows `from frappe import _` for the
		# entire function and breaks every i18n call that follows.
		canonical_prefix, canonical_local = split_e164(canonical_phone)
		phone_prefix_to_save = canonical_prefix
		phone_to_save = canonical_local
	else:
		cleaned_phone = _normalize_phone(phone_raw)
		intl_digits = cleaned_phone.lstrip("+")
		if not _INTL_PHONE_RE.match(intl_digits):
			frappe.throw(_("Geçerli bir telefon numarası giriniz (7-15 rakam)"))
		phone_prefix_to_save = phone_prefix_in
		phone_to_save = cleaned_phone

	# Ülke whitelist kontrolü — frontend countries listesi ile senkron.
	country_in = normalize_country_code((data.get("country") or "TR").strip())
	data["country"] = country_in
	try:
		validate_country_code(country_in)
	except AddressValidationError as exc:
		frappe.throw(_(str(exc)))

	# Posta kodu — TR için 5 hane, diğer ülkelerde gevşek kontrol. Boş izinli.
	postal_code_in = (data.get("postal_code") or "").strip()
	try:
		validate_postal_code(postal_code_in, country_in)
	except AddressValidationError as exc:
		frappe.throw(_(str(exc)))

	# Seller adreslerini transaction'ın başında kilitle. Tek helper çağrısı
	# MAX_ADDRESSES count+insert race'ini ve save_address concurrent
	# deadlock'unu birden kapatır (buyer.py ile aynı pattern). `locked` dönüşü
	# hem owner check hem de count için tek-kaynak (ekstra SELECT yok).
	locked = _lock_seller_addresses(seller_name)

	if address_id:
		# Owner check lock altında: locked rows zaten
		# `seller = X AND kind='Seller'` filter ile alındığından, address_id
		# locked'da varsa hem mevcut hem de bu seller'a ait demektir.
		if not any(row.name == address_id for row in locked):
			frappe.throw(_("Adres bulunamadı"), frappe.DoesNotExistError)
		doc = frappe.get_doc("Addresses", address_id)
	else:
		# len(locked) === count — lock altında alındığı için race-free.
		if len(locked) >= MAX_ADDRESSES:
			frappe.throw(_("En fazla {0} adres ekleyebilirsiniz").format(MAX_ADDRESSES))
		doc = frappe.new_doc("Addresses")
		doc.kind = "Seller"
		doc.seller = seller_name
		doc.user = user

	doc.title = (data.get("title") or "").strip()
	doc.contact_name = (data.get("contact_name") or "").strip()
	doc.company = (data.get("company") or "").strip()
	doc.phone_prefix = phone_prefix_to_save
	doc.phone = phone_to_save
	doc.country = country_in
	doc.state = (data.get("state") or "").strip()
	doc.city = (data.get("city") or "").strip()
	doc.street = (data.get("street") or "").strip()
	doc.apartment = (data.get("apartment") or "").strip()
	doc.postal_code = (data.get("postal_code") or "").strip()
	doc.note = (data.get("note") or "").strip()
	doc.is_default = bool(data.get("is_default", False))

	if address_id:
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)

	# Çoklu-default invariant'ı _ensure_one_default tarafından atomik şekilde
	# korunur: lock altında, "en son modified olan default'u tut, diğerlerini
	# temizle" semantiği ile. Pre-save cleanup'a gerek yok — yeni kaydedilen
	# doc'un modified'ı en tazedir, dolayısıyla kullanıcı niyeti korunur.
	current_default_id = _ensure_one_default(seller_name)

	# `doc.is_default`'u current_default_id'den türet — buyer.py ile aynı
	# pattern. _ensure_one_default fallback path'i in-memory doc'u güncellemediği
	# için reload gerekiyordu; reload commit sonrası lock-suz çalıştığından
	# concurrent silme race'ini taşıyordu. current_default_id atomik okuma
	# zaten doğru sonucu veriyor → reload'a gerek yok.
	doc.is_default = current_default_id == doc.name

	frappe.db.commit()

	return {
		"address": _doc_to_dict(doc),
		"default_id": current_default_id,
	}


@frappe.whitelist()
def delete_address(address_id):
	"""
	Bir adresi siler. Silme sonrası `_ensure_one_default` koşulsuz çağrılır:
	- silinen default ise yeni default atanır,
	- broken state varsa self-heal yapılır (çoklu-default temizlenir).

	Response'ta silme sonrası aktif olan default_id döndürülür — frontend
	ayrı bir get_addresses fetch'i atmak zorunda kalmaz.

	**Lock ordering:** Lock owner check'ten ÖNCE alınır. Aksi halde TOCTOU
	yarış penceresi açılırdı: TX1 owner check passed → TX2 lock + delete +
	commit → TX1 lock alır ama row gitmiş → frappe.delete_doc 500 verir.
	Lock altında existence kontrolü ile kibarca DoesNotExistError mesajı.
	"""
	user = _require_login()
	seller_name = _resolve_seller_profile(user)

	# Lock'u önce al — concurrent delete/save ile race window'u kapatır.
	# locked rows zaten `seller = X AND kind='Seller'` filter ile alındığından
	# owner check ekstra SELECT yapmadan locked üzerinde yapılır.
	locked = _lock_seller_addresses(seller_name)

	if not any(row.name == address_id for row in locked):
		frappe.throw(_("Adres bulunamadı"), frappe.DoesNotExistError)

	frappe.delete_doc("Addresses", address_id, ignore_permissions=True)
	new_default_id = _ensure_one_default(seller_name)

	frappe.db.commit()
	return {"success": True, "default_id": new_default_id}


@frappe.whitelist()
def set_default_address(address_id):
	"""
	Bir adresi varsayılan yapar. `_lock_seller_addresses` ile tüm seller
	adreslerini `FOR UPDATE` ile kilitleyip per-row atomik flip uygular.

	Race-safe: iki eşzamanlı set_default_address çağrısı sıralı işlenir —
	çoklu-default veya sıfır-default state oluşması imkansız. save_address /
	delete_address ile de aynı lock order'ı paylaşıldığından deadlock imkansız.

	**Lock ordering:** delete_address ile aynı pattern — owner check lock
	altında, locked rows üzerinden. target_found falsy ise DoesNotExistError.
	"""
	user = _require_login()
	seller_name = _resolve_seller_profile(user)

	locked = _lock_seller_addresses(seller_name)

	target_found = False
	for row in locked:
		desired = 1 if row.name == address_id else 0
		if int(row.is_default or 0) != desired:
			frappe.db.set_value("Addresses", row.name, "is_default", desired)
		if row.name == address_id:
			target_found = True

	if not target_found:
		# owner check geçti ama lock altında bulunamadıysa arada silinmiş demek
		frappe.throw(_("Adres bulunamadı"), frappe.DoesNotExistError)

	frappe.db.commit()
	return {"success": True, "default_id": address_id}

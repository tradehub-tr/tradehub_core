"""
Buyer API — Alıcıya özgü endpoint'ler.
Şu an: Adres defteri CRUD.
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

# TR telefon formatı — hem mobil hem sabit, prefix (+90 veya 0) opsiyonel.
# Frontend utils/tr-validation.ts ile senkron.
_PHONE_RE = re.compile(r"^(\+90|0)?[2-5]\d{9}$")
# Uluslararası (TR dışı) gevşek kontrol: yalnız rakamlar, 7-15 hane (E.164).
_INTL_PHONE_RE = re.compile(r"^\d{7,15}$")
_PHONE_CLEAN_RE = re.compile(r"[\s\-()]")


def _normalize_phone(raw):
	"""Kullanıcı girdisinden format karakterlerini (boşluk, tire, parantez) temizler."""
	return _PHONE_CLEAN_RE.sub("", raw or "")


def _validate_phone(raw, prefix=None):
	"""
	Telefon doğrulaması — prefix'e göre ayrışır.
	- `+90` veya prefix verilmemiş ise TR formatı (sabit + mobil).
	- Diğer prefix'lerde gevşek E.164 kontrolü (7-15 rakam).
	"""
	normalized = _normalize_phone(raw)
	if not prefix or prefix == "+90":
		return bool(_PHONE_RE.match(normalized))
	digits_only = normalized.lstrip("+")
	return bool(_INTL_PHONE_RE.match(digits_only))


# ── helpers ──────────────────────────────────────────────────────────────────


def _require_login():
	"""Oturum açmamış kullanıcıları reddeder; user adını döndürür."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Bu işlem için giriş yapmanız gerekiyor"), frappe.AuthenticationError)
	return user


def _check_address_owner(address_id, user):
	"""Adresin sahibi değilse PermissionError fırlatır. Sadece Buyer kayıtları."""
	row = frappe.db.get_value("Addresses", address_id, ["user", "kind"], as_dict=True)
	if not row:
		frappe.throw(_("Adres bulunamadı"), frappe.DoesNotExistError)
	if row.kind != "Buyer" or row.user != user:
		frappe.throw(_("Bu adrese erişim yetkiniz yok"), frappe.PermissionError)


def _doc_to_dict(doc):
	"""Addresses document'ını frontend'e uygun dict'e dönüştürür."""
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
		"purpose": doc.purpose or "Delivery",
		"address_type": doc.address_type or "Individual",
		"tax_no": doc.tax_no or "",
		"tax_office": doc.tax_office or "",
	}


def _lock_user_addresses(user):
	"""
	Kullanıcının tüm Buyer adres satırlarını `FOR UPDATE` ile kilitler ve
	(name, is_default, modified) tuple'larını creation ASC sırayla döner.

	Bu helper adres mutation'larının hepsinin tek bir kilit order'ı paylaşmasını
	sağlar — save_address / delete_address / set_default_address /
	_ensure_one_default hepsi bu fonksiyonu çağırır. Aynı sıralama = deadlock
	imkansız.

	İki kritik bug'ı birden çözer:

	1) **MAX_ADDRESSES count+insert race:** save_address count kontrolünden
	   önce lock'u alır; iki eşzamanlı request aynı count'u görüp sınırı
	   bypass edemez. İkinci request birinci commit'i beklemek zorunda, bu
	   sırada count güncellenmiş olur.

	2) **Concurrent save_address deadlock:** Eskiden her save önce kendi
	   doc_N row'unu kilitliyordu, sonra `_ensure_one_default` diğer tüm
	   satırları istiyordu — TX1/TX2 farklı row'larla başlayınca MariaDB
	   deadlock detect ediyordu. Artık tüm write operasyonları önce `tabula
	   rasa` ile tüm kullanıcı satırlarını kilitliyor, hiç deadlock yok.

	Çağıran return değerini ihtiyaca göre kullanır:
	- Sadece lock gerekliyse atılabilir (save_address / delete_address).
	- Row'lar self-heal / flip için kullanılacaksa assign edilir
	  (_ensure_one_default / set_default_address).
	"""
	return frappe.db.sql(
		"""
		SELECT name, is_default, modified
		FROM `tabAddresses`
		WHERE user = %(user)s AND kind = 'Buyer'
		ORDER BY creation ASC
		FOR UPDATE
		""",
		{"user": user},
		as_dict=True,
	)


def _ensure_one_default(user):
	"""
	Kullanıcının tam olarak bir varsayılan Buyer adresi olmasını garantiler.

	Davranış:
	- Hiç default yoksa en eski adres default yapılır (stabil fallback).
	- Birden fazla default varsa (broken state) **en son modified olan** korunur,
	  diğerleri temizlenir. Bu semantik save_address'in "yeni eklenen / son
	  düzenlenen adresi default yap" kullanıcı niyetiyle tutarlıdır — son yazan
	  kazanır.
	- Kullanıcının hiç adresi yoksa boş string döner.

	**Atomik default_id okuma:** Aynı transaction içinde lock'u tutarak güncel
	default'un name'ini döndürür; böylece çağıran taraf ekstra bir SELECT
	çalıştırmadan return değerini doğrudan response'a koyabilir (race-free).

	Race-safe: `_lock_user_addresses` ile row-level lock alır. Frappe her HTTP
	isteğini bir transaction'da sarmalar; kilit `frappe.db.commit()` veya
	rollback ile bırakılır.
	"""
	locked = _lock_user_addresses(user)
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
	"""
	Oturumdaki kullanıcının tüm adreslerini döndürür.
	Varsayılan adres önce, geri kalanı oluşturulma tarihine göre sıralı.
	"""
	user = _require_login()
	# Sprint 1 (2026-05-15) — purpose+address_type filter:
	# Buyer akışı sadece Delivery/Billing adreslerini gösterir (Pickup mağaza adresi).
	# Geçiş penceresi: hâlâ kind="Buyer" filter da kullanılıyor (eski kayıtlar).
	rows = frappe.get_all(
		"Addresses",
		filters={
			"user": user,
			"purpose": ["in", ["Delivery", "Billing"]],
		},
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
			"purpose",
			"address_type",
			"tax_no",
			"tax_office",
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
			"purpose": r["purpose"] or "Delivery",
			"address_type": r["address_type"] or "Individual",
			"tax_no": r["tax_no"] or "",
			"tax_office": r["tax_office"] or "",
		}
		for r in rows
	]


@frappe.whitelist()
def save_address(address_json):
	"""
	Adres oluşturur veya günceller.
	address_json: JSON string veya dict. `id` varsa güncelleme, yoksa yeni kayıt.
	Kaydedilen adresi dict olarak döndürür.
	"""
	user = _require_login()

	try:
		data = parse_address_payload(address_json)
		# Country'yi field_lengths'ten önce ISO-2'ye normalize et (eski "Turkey"
		# kayıtları formdan dönerken geçsin diye).
		if data.get("country"):
			data["country"] = normalize_country_code(data["country"].strip())
		validate_field_lengths(data)
	except AddressValidationError as exc:
		frappe.throw(_(str(exc)))

	address_id = (data.get("id") or "").strip()

	# Sprint 1 (2026-05-15) — Adres Mimarisi:
	# purpose (Delivery/Pickup/Billing) ve address_type (Individual/Business) yeni alanlar.
	# Default: purpose=Delivery, address_type=Individual.
	purpose = (data.get("purpose") or "Delivery").strip()
	if purpose not in ("Delivery", "Pickup", "Billing"):
		purpose = "Delivery"
	address_type = (data.get("address_type") or "Individual").strip()
	if address_type not in ("Individual", "Business"):
		address_type = "Individual"
	tax_no = (data.get("tax_no") or "").strip()
	tax_office = (data.get("tax_office") or "").strip()

	# Zorunlu alan doğrulaması — company sadece Business için zorunlu.
	required_fields = {
		"title": _("Adres Başlığı"),
		"contact_name": _("İrtibat Kişisi"),
		"phone": _("Telefon"),
		"state": _("İl"),
		"street": _("Adres Satırı"),
	}
	if address_type == "Business":
		required_fields["company"] = _("Şirket Adı")
		required_fields["tax_no"] = _("Vergi No")
		required_fields["tax_office"] = _("Vergi Dairesi")
	for field, label in required_fields.items():
		if not (data.get(field) or "").strip():
			frappe.throw(_("{0} alanı zorunludur").format(label))

	# Business adres için VKN/TCKN checksum doğrulaması
	if address_type == "Business" and tax_no:
		from tradehub_core.utils.tax_validation import is_valid_tax_id

		if not is_valid_tax_id(tax_no):
			frappe.throw(_("Geçerli bir VKN (10 hane) veya TCKN (11 hane) giriniz"))

	# Telefon formatı — TR için tek kanonik formata (E.164) indirgenir, non-TR
	# için mevcut gevşek E.164 kontrolü korunur.
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

	# Kullanıcı adreslerini transaction'ın başında kilitle. Bu tek helper
	# çağrısı iki bug'ı birden kapatır:
	#  1) MAX_ADDRESSES count+insert race — count'tan önce lock alındığı için
	#     iki eşzamanlı request aynı count'u görüp sınırı bypass edemez.
	#  2) save_address concurrent deadlock — tüm mutation'lar aynı lock
	#     order'ını kullandığından MariaDB deadlock'u yakalayamaz, işler
	#     sıralı serialize olur.
	# Lock validation sonrasında alınır — validation fail olursa gereksiz
	# lock tutulmaz. `locked` dönüşü hem owner check hem de count için
	# tek-kaynak olarak kullanılır (ekstra SELECT yok).
	locked = _lock_user_addresses(user)

	if address_id:
		# Owner check lock altında: locked rows zaten `user = X AND kind='Buyer'`
		# filter ile alındığından, address_id locked'da varsa hem mevcut hem de
		# bu kullanıcıya ait demektir. Yoksa "yok" / "yetkin yok" ayrımı
		# yapmadan DoesNotExistError fırlatırız (information leak'i azaltır).
		if not any(row.name == address_id for row in locked):
			frappe.throw(_("Adres bulunamadı"), frappe.DoesNotExistError)
		doc = frappe.get_doc("Addresses", address_id)
	else:
		# len(locked) === count — lock altında alındığı için race-free.
		if len(locked) >= MAX_ADDRESSES:
			frappe.throw(_("En fazla {0} adres ekleyebilirsiniz").format(MAX_ADDRESSES))
		doc = frappe.new_doc("Addresses")
		doc.kind = "Buyer"  # Sprint 1 — geçiş penceresi: kind hâlâ yazılıyor (Sprint 4'te drop)
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
	# Sprint 1 (2026-05-15) — yeni alanlar:
	doc.purpose = purpose
	doc.address_type = address_type
	doc.tax_no = tax_no
	doc.tax_office = tax_office

	if address_id:
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)

	# Çoklu-default invariant'ı _ensure_one_default tarafından atomik şekilde
	# korunur: lock altında, "en son modified olan default'u tut, diğerlerini
	# temizle" semantiği ile. Pre-save cleanup'a gerek yok — yeni kaydedilen
	# doc'un modified'ı en tazedir, dolayısıyla kullanıcı niyeti korunur.
	current_default_id = _ensure_one_default(user)

	# `doc.is_default`'u current_default_id'den türet — `_ensure_one_default`
	# fallback path'i (zero-default → en eskiyi default yap) doc'un in-memory
	# is_default'unu güncellemediği için reload gerekiyordu. Reload commit
	# sonrası lock-suz çalıştığından nadir ama gerçek bir race window vardı:
	# başka bir tab eşzamanlı silerse reload DoesNotExistError fırlatabilirdi.
	# Doc'umuz bu tx'de kilit altında save edildi → modified en tazedir →
	# multi-default cleanup'ta her zaman kazanır. Tek belirsizlik sıfır-default
	# fallback'idir; o da current_default_id == doc.name eşitliği ile
	# tam doğrulukla yakalanır. Hem reload hem race ortadan kalkar.
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
	yarış penceresi açılırdı: TX1 owner check passed → TX2 (başka tab) lock
	→ delete → commit → TX1 lock alır ama row gitmiş → frappe.delete_doc
	`DoesNotExistError` 500 döndürür. Lock altında existence kontrolü ile
	kibarca DoesNotExistError mesajı dönüyoruz.
	"""
	user = _require_login()

	# Lock'u önce al — concurrent delete/save ile race window'u kapatır.
	# locked rows zaten `user = X AND kind='Buyer'` filter ile alındığından
	# owner check ekstra bir SELECT yapmadan locked üzerinde yapılabilir.
	locked = _lock_user_addresses(user)

	if not any(row.name == address_id for row in locked):
		# Lock altında bulunamadı: ya hiç yoktu, ya başka kullanıcının, ya da
		# az önce silindi. Üçü için de aynı mesaj — information leak yok.
		frappe.throw(_("Adres bulunamadı"), frappe.DoesNotExistError)

	frappe.delete_doc("Addresses", address_id, ignore_permissions=True)
	new_default_id = _ensure_one_default(user)

	frappe.db.commit()
	return {"success": True, "default_id": new_default_id}


@frappe.whitelist()
def set_default_address(address_id):
	"""
	Bir adresi varsayılan yapar. `_lock_user_addresses` ile tüm kullanıcı
	Buyer adreslerini `FOR UPDATE` ile kilitleyip per-row atomik flip uygular.

	Race-safe: iki eşzamanlı set_default_address çağrısı sıralı işlenir
	(ikinci call birinci commit'i beklemek zorunda) — çoklu-default veya
	sıfır-default state oluşması imkansız. save_address / delete_address ile
	de aynı lock order'ı paylaşıldığından deadlock imkansız.

	**Lock ordering:** delete_address ile aynı pattern — owner check lock
	altında, locked rows üzerinden. Ekstra SELECT yok, TOCTOU yok.
	"""
	user = _require_login()

	locked = _lock_user_addresses(user)

	target_found = False
	# Sadece değişmesi gereken satırlar için write yap — gereksiz
	# modified timestamp güncellemelerini önler.
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

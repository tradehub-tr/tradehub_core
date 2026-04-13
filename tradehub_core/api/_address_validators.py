"""
Adres API'leri için saf Python validator'ları.

`buyer.py` ve `seller_addresses.py` bu modülü ortak olarak kullanır; böylece
JSON parse / ülke whitelist / posta kodu / alan uzunluğu kuralları iki taraf
arasında drift etmez.

Modül **frappe import etmez** — bu sayede unit test'ler bench/site gerektirmez.
Çağıran taraf `AddressValidationError`'ı yakalayıp `frappe.throw` ile sarmalar.
"""

import json
import re


class AddressValidationError(ValueError):
	"""Adres payload doğrulaması başarısız olduğunda fırlatılır."""


# ── Ülke whitelist'i ─────────────────────────────────────────────────────────
# Storefront tarafındaki `tradehubfront/src/data/mockCheckout.ts` `countries`
# listesi ile birebir senkron tutulur. Yeni bir ülke eklerken iki tarafı da
# güncelleyin (test_address_validators.py drift'i yakalar).
ALLOWED_COUNTRY_CODES = frozenset({
	"US", "AU", "CA", "GB", "IN", "MX", "DE", "FR", "IT", "ES",
	"BR", "JP", "KR", "NL", "RU", "SA", "AE", "TR", "PL", "SE",
	"CH", "NO", "DK", "BE", "AT", "ID", "TH", "VN", "PH", "MY",
})


def parse_address_payload(payload):
	"""
	Frontend'den gelen address payload'ını güvenli şekilde dict'e çevirir.

	Kabul edilen girdiler:
	- dict: doğrudan döndürülür
	- str: JSON olarak parse edilir; sonuç dict olmalı

	Bozuk JSON, list/int/None gibi non-dict tipler veya tamamen yabancı
	tip için `AddressValidationError` fırlatır. Frappe runtime'ında çağıran
	tarafın bu hatayı `frappe.throw` ile sarmalaması beklenir.
	"""
	if isinstance(payload, dict):
		return payload
	if not isinstance(payload, str):
		raise AddressValidationError("Geçersiz istek formatı")
	try:
		data = json.loads(payload)
	except (ValueError, TypeError):
		raise AddressValidationError("Geçersiz istek formatı")
	if not isinstance(data, dict):
		raise AddressValidationError("Geçersiz istek formatı")
	return data


def validate_country_code(country):
	"""
	Ülke kodunun whitelist'te olduğunu doğrular. Boş/None kabul etmez.
	"""
	if not country or not isinstance(country, str):
		raise AddressValidationError("Geçersiz ülke kodu")
	if country not in ALLOWED_COUNTRY_CODES:
		raise AddressValidationError("Geçersiz ülke kodu")


# ── Posta kodu doğrulaması ───────────────────────────────────────────────────
# TR posta kodu: tam 5 hane (PTT 5 haneli sistem). Diğer ülkelerde regex
# karmaşıklığı çok arttığından gevşek kontrol uygulanır (sadece uzunluk +
# karakter seti). Boş posta kodu her ülkede geçerli (alan zorunlu değil).
_TR_POSTAL_RE = re.compile(r"^\d{5}$")
_GENERIC_POSTAL_RE = re.compile(r"^[A-Za-z0-9\s\-]{2,12}$")


def validate_postal_code(postal_code, country):
	"""
	Posta kodunu ülke koduna göre doğrular.

	- Boş/None: izin verilir (alan zorunlu değil).
	- TR: tam 5 hane rakam (`^\\d{5}$`).
	- Diğer ülkeler: 2-12 karakter alfanumerik + boşluk/tire.
	"""
	if postal_code is None or postal_code == "":
		return
	if not isinstance(postal_code, str):
		raise AddressValidationError("Geçerli bir posta kodu giriniz")
	value = postal_code.strip()
	if not value:
		return
	if country == "TR":
		if not _TR_POSTAL_RE.match(value):
			raise AddressValidationError(
				"Geçerli bir posta kodu giriniz (5 haneli, örn. 34394)"
			)
		return
	if not _GENERIC_POSTAL_RE.match(value):
		raise AddressValidationError("Geçerli bir posta kodu giriniz")


# ── Alan uzunluğu doğrulaması ────────────────────────────────────────────────
# Addresses doctype field type'ları (apps/.../doctype/addresses/addresses.json):
#   Data fields → 140 char (Frappe varsayılanı)
#   Small Text  → MySQL TEXT (65535) ama UX/abuse açısından 1000'le sınırlandı
#
# Tuple format: (kullanıcı-okur Türkçe etiket, max char). Etiket frontend'deki
# label ile eşleşir; kullanıcı hangi alan için hata aldığını anlar.
ADDRESS_FIELD_LIMITS = {
	"title":        ("Adres Başlığı", 140),
	"contact_name": ("İrtibat Kişisi", 140),
	"company":      ("Şirket Adı", 140),
	"phone_prefix": ("Telefon Kodu", 10),
	"phone":        ("Telefon", 20),
	"country":      ("Ülke Kodu", 2),
	"state":        ("İl", 140),
	"city":         ("İlçe", 140),
	"street":       ("Adres Satırı", 1000),
	"apartment":    ("Daire / Bina", 140),
	"postal_code":  ("Posta Kodu", 20),
	"note":         ("Adres Notu", 1000),
}


def validate_field_lengths(data):
	"""
	Tüm metin alanlarının max char limit'ini aşmadığını doğrular.

	`data` dict olmalı (`parse_address_payload` çıktısı). Sadece string
	değerler kontrol edilir; bool/int/None alan tipi mismatch'leri burada
	kapsam dışı bırakılır (Frappe doc.save validation kendi tarafında yakalar).

	Limit aşıldığında kullanıcıya hangi alanın aşıldığını söyleyen Türkçe
	hata mesajı fırlatır.
	"""
	if not isinstance(data, dict):
		raise AddressValidationError("Geçersiz istek formatı")
	for fieldname, (label, max_len) in ADDRESS_FIELD_LIMITS.items():
		value = data.get(fieldname)
		if value is None:
			continue
		if not isinstance(value, str):
			# bool/int gibi tipleri Frappe doc.save tarafında yakalar
			continue
		# Uzunluk kontrolü strip sonrası — sadece anlamlı karakterleri sayar
		if len(value.strip()) > max_len:
			raise AddressValidationError(
				"{0} alanı çok uzun (en fazla {1} karakter)".format(label, max_len)
			)

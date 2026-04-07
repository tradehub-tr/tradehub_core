"""
Buyer API — Alıcıya özgü endpoint'ler.
Şu an: Adres defteri CRUD.
"""

import json
import frappe
from frappe import _

MAX_ADDRESSES = 10


# ── helpers ──────────────────────────────────────────────────────────────────

def _require_login():
	"""Oturum açmamış kullanıcıları reddeder; user adını döndürür."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Bu işlem için giriş yapmanız gerekiyor"), frappe.AuthenticationError)
	return user


def _check_address_owner(address_id, user):
	"""Adresin sahibi değilse PermissionError fırlatır."""
	owner = frappe.db.get_value("Buyer Address", address_id, "user")
	if not owner:
		frappe.throw(_("Adres bulunamadı"), frappe.DoesNotExistError)
	if owner != user:
		frappe.throw(_("Bu adrese erişim yetkiniz yok"), frappe.PermissionError)


def _doc_to_dict(doc):
	"""Buyer Address document'ını frontend'e uygun dict'e dönüştürür."""
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


def _ensure_one_default(user):
	"""
	Kullanıcının en az bir varsayılan adresi olmasını garantiler.
	Hiç yoksa en eski adres varsayılan yapılır.
	"""
	has_default = frappe.db.count("Buyer Address", {"user": user, "is_default": 1})
	if has_default:
		return
	oldest = frappe.get_all(
		"Buyer Address",
		filters={"user": user},
		fields=["name"],
		order_by="creation asc",
		limit=1,
	)
	if oldest:
		frappe.db.set_value("Buyer Address", oldest[0]["name"], "is_default", 1)


# ── public endpoints ──────────────────────────────────────────────────────────

@frappe.whitelist()
def get_addresses():
	"""
	Oturumdaki kullanıcının tüm adreslerini döndürür.
	Varsayılan adres önce, geri kalanı oluşturulma tarihine göre sıralı.
	"""
	user = _require_login()
	rows = frappe.get_all(
		"Buyer Address",
		filters={"user": user},
		fields=[
			"name", "title", "contact_name", "company",
			"phone_prefix", "phone",
			"country", "state", "city", "street", "apartment", "postal_code",
			"note", "is_default",
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
	"""
	Adres oluşturur veya günceller.
	address_json: JSON string veya dict. `id` varsa güncelleme, yoksa yeni kayıt.
	Kaydedilen adresi dict olarak döndürür.
	"""
	user = _require_login()

	data = json.loads(address_json) if isinstance(address_json, str) else address_json
	address_id = (data.get("id") or "").strip()

	if address_id:
		_check_address_owner(address_id, user)
		doc = frappe.get_doc("Buyer Address", address_id)
	else:
		count = frappe.db.count("Buyer Address", {"user": user})
		if count >= MAX_ADDRESSES:
			frappe.throw(
				_("En fazla {0} adres ekleyebilirsiniz").format(MAX_ADDRESSES)
			)
		doc = frappe.new_doc("Buyer Address")
		doc.user = user

	doc.title        = (data.get("title") or "").strip()
	doc.contact_name = (data.get("contact_name") or "").strip()
	doc.company      = (data.get("company") or "").strip()
	doc.phone_prefix = (data.get("phone_prefix") or "+90").strip()
	doc.phone        = (data.get("phone") or "").strip()
	doc.country      = (data.get("country") or "TR").strip()
	doc.state        = (data.get("state") or "").strip()
	doc.city         = (data.get("city") or "").strip()
	doc.street       = (data.get("street") or "").strip()
	doc.apartment    = (data.get("apartment") or "").strip()
	doc.postal_code  = (data.get("postal_code") or "").strip()
	doc.note         = (data.get("note") or "").strip()
	doc.is_default   = bool(data.get("is_default", False))

	# Varsayılan olarak ayarlanıyorsa diğer varsayılanları temizle.
	# Yeni doc henüz kaydedilmediğinden name'i yoktur; sadece mevcut doc'lar temizlenir.
	if doc.is_default and doc.name:
		frappe.db.set_value(
			"Buyer Address",
			{"user": user, "name": ("!=", doc.name)},
			"is_default",
			0,
		)
	elif doc.is_default and not doc.name:
		# Yeni doc henüz kaydedilmedi — insert sonrası temizleme yapılacak
		frappe.db.set_value(
			"Buyer Address",
			{"user": user},
			"is_default",
			0,
		)

	if address_id:
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)

	# Kullanıcının mutlaka bir varsayılanı olsun
	_ensure_one_default(user)

	frappe.db.commit()
	return _doc_to_dict(doc)


@frappe.whitelist()
def delete_address(address_id):
	"""
	Bir adresi siler.
	Silinen adres varsayılansa en eski kalan adres otomatik varsayılan yapılır.
	"""
	user = _require_login()
	_check_address_owner(address_id, user)

	was_default = bool(frappe.db.get_value("Buyer Address", address_id, "is_default"))

	frappe.delete_doc("Buyer Address", address_id, ignore_permissions=True)

	if was_default:
		_ensure_one_default(user)

	frappe.db.commit()
	return {"success": True}


@frappe.whitelist()
def set_default_address(address_id):
	"""
	Bir adresi varsayılan yapar; kullanıcının diğer varsayılanlarını temizler.
	"""
	user = _require_login()
	_check_address_owner(address_id, user)

	# Tüm varsayılanları temizle
	frappe.db.set_value("Buyer Address", {"user": user}, "is_default", 0)
	# Yeni varsayılanı ayarla
	frappe.db.set_value("Buyer Address", address_id, "is_default", 1)

	frappe.db.commit()
	return {"success": True}

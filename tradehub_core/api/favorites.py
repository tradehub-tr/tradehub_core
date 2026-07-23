"""
Buyer Favorites API — kullanıcıya özel favori ürün ve liste yönetimi.

Mimari:
- 'Buyer Favorite List' DocType: Kullanıcının özel listeleri (UUID + isim)
- 'Buyer Favorite Item' DocType: (user, listing) unique; list_ids JSON array
- Tüm endpoint'ler frappe.session.user'a göre filtrelenir; başkasının verisine erişilemez
- 'default' liste için DB kaydı YOK; varsayılan tüm itemların düştüğü "Tüm Favoriler"
  sanal listesi (frontend tarafında her zaman var sayılır)
"""

import json

import frappe
from frappe import _
from frappe.utils import get_datetime


def _require_user():
	"""Oturum açmış kullanıcıyı döner; misafirse 401 fırlatır."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Favorileri kullanmak için giriş yapmalısınız."), frappe.PermissionError)
	return user


def _parse_list_ids(raw):
	"""list_ids alanını JSON parse eder. Hatalı/boşsa ['default'] döner."""
	if not raw:
		return ["default"]
	try:
		val = json.loads(raw) if isinstance(raw, str) else raw
		if isinstance(val, list) and val:
			return [str(x) for x in val]
	except Exception:
		frappe.log_error(f"Failed to parse list_ids JSON: {raw!r}", "favorites._parse_list_ids")
		pass
	return ["default"]


def _filter_owned_list_ids(user, list_ids):
	"""Sadece `user`'in sahibi oldugu list_id'leri ve sanal 'default' listeyi dondur.
	Boş veya tamamen yabanci girdi gelirse fallback olarak ['default'] doner.
	Cross-user list_id sizmasini engeller (HATA 19)."""
	if not list_ids:
		return ["default"]
	own = set(frappe.get_all("Buyer Favorite List", filters={"user": user}, pluck="list_id"))
	own.add("default")
	filtered = [lid for lid in list_ids if lid in own]
	return filtered or ["default"]


def _get_item_doc(user, listing):
	"""(user, listing) için mevcut Buyer Favorite Item kaydını döner ya da None."""
	name = frappe.db.get_value("Buyer Favorite Item", {"user": user, "listing": listing}, "name")
	if not name:
		return None
	return frappe.get_doc("Buyer Favorite Item", name)


# ──────────────────────────── READ ─────────────────────────────────────────


@frappe.whitelist()
def get_my_favorites():
	"""
	Kullanıcının tüm favorileri ve listelerini döner.
	Frontend FavoritesState'i ile birebir uyumlu format.
	"""
	user = _require_user()

	lists_raw = frappe.get_all(
		"Buyer Favorite List",
		filters={"user": user},
		fields=["list_id", "list_name", "creation"],
		order_by="creation asc",
	)
	lists = [
		{
			"id": r["list_id"],
			"name": r["list_name"],
			"createdAt": int(r["creation"].timestamp() * 1000) if r.get("creation") else 0,
		}
		for r in lists_raw
	]

	items_raw = frappe.get_all(
		"Buyer Favorite Item",
		filters={"user": user},
		fields=[
			"listing",
			"list_ids",
			"snapshot_image",
			"snapshot_title",
			"snapshot_price_range",
			"snapshot_price",
			"snapshot_currency",
			"snapshot_min_order",
			"creation",
		],
		order_by="creation desc",
	)
	items = [
		{
			"id": r["listing"],
			"image": r.get("snapshot_image") or "",
			"title": r.get("snapshot_title") or "",
			"priceRange": r.get("snapshot_price_range") or "",
			# Native fiyat + para birimi — frontend gösterimde güncel kura çevirir.
			"price": r.get("snapshot_price") or 0,
			"currency": r.get("snapshot_currency") or "",
			"minOrder": r.get("snapshot_min_order") or "",
			"listIds": _parse_list_ids(r.get("list_ids")),
			"addedAt": int(r["creation"].timestamp() * 1000) if r.get("creation") else 0,
		}
		for r in items_raw
	]

	return {"lists": lists, "items": items}


# ──────────────────────────── WRITE: items ─────────────────────────────────


@frappe.whitelist()
def upsert_favorite(
	listing, list_ids=None, image="", title="", price_range="", min_order="", price=0, currency=""
):
	"""
	Bir favori öğeyi ekler veya günceller.
	list_ids: JSON string ya da list (örn '["default","<uuid>"]'). Boşsa ['default'].
	price/currency: native (çevrilmemiş) fiyat + para birimi — gösterimde kura çevrilir.
	"""
	user = _require_user()
	if not listing:
		frappe.throw(_("Listing zorunludur."))

	# Listing gerçekten var mı?
	if not frappe.db.exists("Listing", listing):
		frappe.throw(_("Ürün bulunamadı."), frappe.DoesNotExistError)

	parsed_ids = _filter_owned_list_ids(user, _parse_list_ids(list_ids))

	doc = _get_item_doc(user, listing)
	if doc:
		# Mevcut listIds ile birleştir + sahip kontrolu (eski kirli kayitlari da arindir)
		merged = list(dict.fromkeys(_parse_list_ids(doc.list_ids) + parsed_ids))
		merged = _filter_owned_list_ids(user, merged)
		doc.list_ids = json.dumps(merged)
		# Snapshot'ı sadece yeni değer geldiyse güncelle
		if image:
			doc.snapshot_image = image
		if title:
			doc.snapshot_title = title
		if price_range:
			doc.snapshot_price_range = price_range
		if price:
			doc.snapshot_price = price
		if currency:
			doc.snapshot_currency = currency
		if min_order:
			doc.snapshot_min_order = min_order
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.new_doc("Buyer Favorite Item")
		doc.user = user
		doc.listing = listing
		doc.list_ids = json.dumps(parsed_ids)
		doc.snapshot_image = image or ""
		doc.snapshot_title = title or ""
		doc.snapshot_price_range = price_range or ""
		doc.snapshot_price = price or 0
		doc.snapshot_currency = currency or ""
		doc.snapshot_min_order = min_order or ""
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
	return {"ok": True, "name": doc.name}


@frappe.whitelist()
def remove_favorite(listing):
	"""Bir öğeyi tüm listelerden tamamen kaldırır."""
	user = _require_user()
	if not listing:
		return {"ok": True}

	name = frappe.db.get_value("Buyer Favorite Item", {"user": user, "listing": listing}, "name")
	if name:
		frappe.delete_doc("Buyer Favorite Item", name, ignore_permissions=True)
		frappe.db.commit()
	return {"ok": True}


@frappe.whitelist()
def toggle_favorite_in_list(
	listing, list_id, image="", title="", price_range="", min_order="", price=0, currency=""
):
	"""
	Bir ürünü belirli bir listeye ekler/çıkarır.
	Eğer ürün hiçbir listeye ait kalmazsa tamamen silinir.
	Returns: {"in_list": bool, "removed": bool}
	"""
	user = _require_user()
	if not listing or not list_id:
		frappe.throw(_("Listing ve list_id zorunludur."))

	if not frappe.db.exists("Listing", listing):
		frappe.throw(_("Ürün bulunamadı."), frappe.DoesNotExistError)

	# list_id sahip kontrolu — 'default' her kullaniciya ait, diger list_id'ler
	# sadece olusturucusuna ait. Cross-user toggle'i engelle (HATA 19).
	if list_id != "default":
		if not frappe.db.exists("Buyer Favorite List", {"user": user, "list_id": list_id}):
			frappe.throw(_("Liste bulunamadi veya size ait degil."), frappe.PermissionError)

	doc = _get_item_doc(user, listing)

	if not doc:
		# Yeni öğe — bu listeye ekle
		doc = frappe.new_doc("Buyer Favorite Item")
		doc.user = user
		doc.listing = listing
		doc.list_ids = json.dumps([list_id])
		doc.snapshot_image = image or ""
		doc.snapshot_title = title or ""
		doc.snapshot_price_range = price_range or ""
		doc.snapshot_price = price or 0
		doc.snapshot_currency = currency or ""
		doc.snapshot_min_order = min_order or ""
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return {"in_list": True, "removed": False}

	current_ids = _parse_list_ids(doc.list_ids)
	if list_id in current_ids:
		# Bu listeden çıkar
		current_ids = [x for x in current_ids if x != list_id]
		if not current_ids:
			# Hiç liste kalmadı → öğeyi tamamen sil
			frappe.delete_doc("Buyer Favorite Item", doc.name, ignore_permissions=True)
			frappe.db.commit()
			return {"in_list": False, "removed": True}
		doc.list_ids = json.dumps(current_ids)
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		return {"in_list": False, "removed": False}
	else:
		# Listeye ekle
		current_ids.append(list_id)
		doc.list_ids = json.dumps(current_ids)
		# Snapshot güncelle (yeni veri geldiyse)
		if image:
			doc.snapshot_image = image
		if title:
			doc.snapshot_title = title
		if price_range:
			doc.snapshot_price_range = price_range
		if price:
			doc.snapshot_price = price
		if currency:
			doc.snapshot_currency = currency
		if min_order:
			doc.snapshot_min_order = min_order
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		return {"in_list": True, "removed": False}


# ──────────────────────────── WRITE: lists ─────────────────────────────────

# Bir kullanicinin olusturabilecegi maksimum favori liste sayisi (HATA 21).
# DoS / spam vektorunu kapatir; UI ve DB performansi icin makul ust sinir.
# `seller_addresses.MAX_ADDRESSES = 10` patterni ile tutarli (orada da sinir var).
MAX_FAVORITE_LISTS = 50


@frappe.whitelist()
def create_favorite_list(name, list_id=None):
	"""
	Yeni özel liste oluşturur. list_id verilmezse otomatik UUID üretilir.
	Returns: {"id": list_id, "name": name, "createdAt": ms}
	"""
	user = _require_user()
	if not name or not str(name).strip():
		frappe.throw(_("Liste adı boş olamaz."))

	final_id = list_id or frappe.generate_hash(length=16)
	clean_name = str(name).strip()

	# Aynı list_id varsa yok say (idempotent path) — sayim oncesi kontrol et
	# ki tekrar cagrida sinir tetiklenmesin.
	exists = frappe.db.get_value("Buyer Favorite List", {"user": user, "list_id": final_id}, "name")
	if exists:
		return {
			"id": final_id,
			"name": clean_name,
			"createdAt": 0,
		}

	# Ust sinir kontrolu (HATA 21) — kullanici basina max liste.
	current = frappe.db.count("Buyer Favorite List", {"user": user})
	if current >= MAX_FAVORITE_LISTS:
		frappe.throw(_("En fazla {0} favori liste olusturabilirsiniz.").format(MAX_FAVORITE_LISTS))

	doc = frappe.new_doc("Buyer Favorite List")
	doc.user = user
	doc.list_id = final_id
	doc.list_name = clean_name
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	return {
		"id": final_id,
		"name": clean_name,
		"createdAt": int(get_datetime(doc.creation).timestamp() * 1000) if doc.creation else 0,
	}


@frappe.whitelist()
def delete_favorite_list(list_id):
	"""
	Listeyi siler ve tüm itemlardan bu list_id'yi çıkarır.
	Hiç liste kalmayan itemları da siler.
	"""
	user = _require_user()
	if not list_id:
		return {"ok": True}

	# Listeyi sil
	list_name = frappe.db.get_value("Buyer Favorite List", {"user": user, "list_id": list_id}, "name")
	if list_name:
		frappe.delete_doc("Buyer Favorite List", list_name, ignore_permissions=True)

	# Bu listeye ait tüm itemlardan list_id'yi çıkar
	items = frappe.get_all(
		"Buyer Favorite Item",
		filters={"user": user},
		fields=["name", "list_ids"],
	)
	for it in items:
		ids = _parse_list_ids(it.get("list_ids"))
		if list_id not in ids:
			continue
		new_ids = [x for x in ids if x != list_id]
		if not new_ids:
			frappe.delete_doc("Buyer Favorite Item", it["name"], ignore_permissions=True)
		else:
			frappe.db.set_value("Buyer Favorite Item", it["name"], "list_ids", json.dumps(new_ids))

	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist()
def rename_favorite_list(list_id, new_name):
	"""Listeyi yeniden adlandırır."""
	user = _require_user()
	if not list_id or not new_name or not str(new_name).strip():
		frappe.throw(_("list_id ve new_name zorunludur."))

	list_doc_name = frappe.db.get_value("Buyer Favorite List", {"user": user, "list_id": list_id}, "name")
	if not list_doc_name:
		frappe.throw(_("Liste bulunamadı."), frappe.DoesNotExistError)

	frappe.db.set_value("Buyer Favorite List", list_doc_name, "list_name", str(new_name).strip())
	frappe.db.commit()
	return {"ok": True}


# ──────────────────────────── SYNC (login merge) ───────────────────────────


@frappe.whitelist()
def sync_favorites(state):
	"""
	Login olduğunda localStorage state'ini backend ile birleştirir.
	state: JSON string {lists: [...], items: [...]} (frontend FavoritesState formatı)

	Strateji:
	- Listeler: backend'de yoksa eklenir; aynı list_id varsa atlanır
	- Itemlar: aynı (user, listing) varsa list_ids birleştirilir, snapshot güncellenir
	  (yoksa yeni eklenir)
	"""
	user = _require_user()
	if not state:
		return get_my_favorites()

	try:
		parsed = json.loads(state) if isinstance(state, str) else state
	except Exception:
		frappe.throw(_("Geçersiz state formatı."))

	in_lists = parsed.get("lists", []) if isinstance(parsed, dict) else []
	in_items = parsed.get("items", []) if isinstance(parsed, dict) else []

	# Listeleri merge et
	for lst in in_lists:
		lid = str(lst.get("id") or "").strip()
		lname = str(lst.get("name") or "").strip()
		if not lid or not lname or lid == "default":
			continue
		exists = frappe.db.get_value("Buyer Favorite List", {"user": user, "list_id": lid}, "name")
		if exists:
			continue
		try:
			doc = frappe.new_doc("Buyer Favorite List")
			doc.user = user
			doc.list_id = lid
			doc.list_name = lname
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.db.rollback()
			continue

	# Itemları merge et
	for it in in_items:
		listing = str(it.get("id") or "").strip()
		if not listing:
			continue
		if not frappe.db.exists("Listing", listing):
			continue

		incoming_ids = it.get("listIds") or ["default"]
		incoming_ids = [str(x) for x in incoming_ids if x]

		existing = _get_item_doc(user, listing)
		if existing:
			merged = list(dict.fromkeys(_parse_list_ids(existing.list_ids) + incoming_ids))
			existing.list_ids = json.dumps(merged)
			# Snapshot güncelle (yeni gelen alanlarla)
			if it.get("image"):
				existing.snapshot_image = it["image"]
			if it.get("title"):
				existing.snapshot_title = it["title"]
			if it.get("priceRange"):
				existing.snapshot_price_range = it["priceRange"]
			if it.get("price"):
				existing.snapshot_price = it["price"]
			if it.get("currency"):
				existing.snapshot_currency = it["currency"]
			if it.get("minOrder"):
				existing.snapshot_min_order = it["minOrder"]
			try:
				existing.save(ignore_permissions=True)
			except Exception:
				frappe.db.rollback()
				continue
		else:
			try:
				doc = frappe.new_doc("Buyer Favorite Item")
				doc.user = user
				doc.listing = listing
				doc.list_ids = json.dumps(incoming_ids)
				doc.snapshot_image = it.get("image") or ""
				doc.snapshot_title = it.get("title") or ""
				doc.snapshot_price_range = it.get("priceRange") or ""
				doc.snapshot_price = it.get("price") or 0
				doc.snapshot_currency = it.get("currency") or ""
				doc.snapshot_min_order = it.get("minOrder") or ""
				doc.insert(ignore_permissions=True)
			except Exception:
				frappe.db.rollback()
				continue

	frappe.db.commit()
	return get_my_favorites()

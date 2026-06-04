"""Rezervasyon sistemi — Plus tier seller'larla mesajlaşmadan önce slot bazlı
rezervasyon zorunluluğu.

Akış:
- Seller `Seller Availability Slot` üzerinde müsait olduğu zaman dilimlerini
  açar (esnek süreli — sabit ızgara yok).
- Buyer bir slot'u kilitleyerek `Chat Reservation` oluşturur.
- Aktif rezervasyon penceresi içinde (start_at ≤ now ≤ end_at) buyer plus
  tier seller'la chat açabilir. Premium tier her zaman izinli.
- Pencere dolunca scheduler status'u Expired'a çevirir.

Bütün whitelist endpoint'leri Frappe session user'a göre çalışır; perspective
parametresine ihtiyaç yok çünkü reservation/slot DocType permission'ları zaten
buyer ve seller'ı ayırıyor.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

DOCTYPE_SLOT = "Seller Availability Slot"
DOCTYPE_RESERVATION = "Chat Reservation"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


SELLER_ROLES = {"Seller", "Marketplace Seller", "Verified Seller"}


def _is_seller(user: str) -> bool:
	if user in ("Administrator", "Guest"):
		return False
	roles = set(frappe.get_roles(user))
	return bool(SELLER_ROLES & roles)


def _require_login() -> str:
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Önce oturum aç."), frappe.AuthenticationError)
	return user


def _resolve_seller_user(seller_ref: str) -> str:
	"""seller_ref farklı formatlarda gelebilir; chat.py ile aynı mantık."""
	if not seller_ref:
		frappe.throw(_("seller_ref boş olamaz."), frappe.ValidationError)
	if "@" in seller_ref and frappe.db.exists("User", seller_ref):
		return seller_ref
	user = frappe.db.get_value("Admin Seller Profile", seller_ref, "user")
	if user:
		return user
	if frappe.db.exists("User", seller_ref):
		return seller_ref
	frappe.throw(_("Satıcı bulunamadı: {0}").format(seller_ref), frappe.DoesNotExistError)


def _seller_tier(seller_user: str) -> str:
	"""Admin Seller Profile.chat_tier — yoksa Premium."""
	tier = frappe.db.get_value("Admin Seller Profile", {"user": seller_user}, "chat_tier")
	return tier or "Premium"


def _active_reservation(buyer_user: str, seller_user: str) -> dict | None:
	"""Şu an aktif olan rezervasyonu (varsa) döndür."""
	now = frappe.utils.now_datetime()
	rows = frappe.get_all(
		DOCTYPE_RESERVATION,
		filters={
			"buyer_user": buyer_user,
			"seller_user": seller_user,
			"status": "Active",
			"start_at": ["<=", now],
			"end_at": [">=", now],
		},
		fields=["name", "start_at", "end_at", "slot"],
		limit_page_length=1,
		order_by="start_at desc",
	)
	return rows[0] if rows else None


# ─────────────────────────────────────────────────────────────────────────────
# Slot endpoint'leri
# ─────────────────────────────────────────────────────────────────────────────


@frappe.whitelist(allow_guest=True)
def list_seller_slots(seller_id: str) -> list[dict[str, Any]]:
	"""Buyer için: seller'ın gelecekteki açık (Open, rezerve edilmemiş) slot'ları.

	Guest izinlidir — buyer henüz login olmadan ürün sayfasında bile slot
	listesini görebilsin (UX için).
	"""
	seller_user = _resolve_seller_user(seller_id)
	now = frappe.utils.now_datetime()

	# Aktif rezervasyonu olan slot id'lerini bul
	reserved_slot_ids = {
		r.slot
		for r in frappe.get_all(
			DOCTYPE_RESERVATION,
			filters={"seller_user": seller_user, "status": "Active"},
			fields=["slot"],
		)
		if r.slot
	}

	slots = frappe.get_all(
		DOCTYPE_SLOT,
		filters={
			"seller_user": seller_user,
			"status": "Open",
			"end_at": [">", now],
		},
		fields=["name", "start_at", "end_at", "notes"],
		order_by="start_at asc",
		ignore_permissions=True,  # guest erişimi — sadece public read
	)

	# Rezerve olanları filtre et
	return [
		{
			"id": s.name,
			"start_at": str(s.start_at),
			"end_at": str(s.end_at),
			"notes": s.notes or "",
			"is_reserved": s.name in reserved_slot_ids,
		}
		for s in slots
		if s.name not in reserved_slot_ids
	]


@frappe.whitelist()
def create_slot(start_at: str, end_at: str, notes: str | None = None) -> dict[str, Any]:
	"""Seller kendi slot'unu açar. Esnek süre — herhangi bir aralık olabilir."""
	user = _require_login()
	if not _is_seller(user):
		frappe.throw(_("Sadece satıcılar slot oluşturabilir."), frappe.PermissionError)

	start_dt = frappe.utils.get_datetime(start_at)
	end_dt = frappe.utils.get_datetime(end_at)
	if start_dt >= end_dt:
		frappe.throw(_("Bitiş zamanı başlangıçtan sonra olmalı."), frappe.ValidationError)
	if end_dt < frappe.utils.now_datetime():
		frappe.throw(_("Geçmiş tarih için slot açılamaz."), frappe.ValidationError)

	# Çakışma kontrolü — aynı seller'ın overlapping açık slot'u olmasın
	overlap = frappe.get_all(
		DOCTYPE_SLOT,
		filters={
			"seller_user": user,
			"status": "Open",
			"start_at": ["<", end_dt],
			"end_at": [">", start_dt],
		},
		fields=["name"],
		limit_page_length=1,
	)
	if overlap:
		frappe.throw(_("Bu aralıkla çakışan açık bir slot zaten var: {0}").format(overlap[0].name))

	doc = frappe.new_doc(DOCTYPE_SLOT)
	doc.seller_user = user
	doc.start_at = start_dt
	doc.end_at = end_dt
	doc.status = "Open"
	doc.created_by_user = user
	doc.notes = (notes or "").strip()[:280]
	doc.insert()
	frappe.db.commit()
	return _slot_to_dict(doc.name)


@frappe.whitelist()
def list_my_slots(include_past: int | str = 0) -> list[dict[str, Any]]:
	"""Seller'ın kendi slot'ları (Open + Closed)."""
	user = _require_login()
	if not _is_seller(user):
		frappe.throw(_("Sadece satıcılar slot listesini görür."), frappe.PermissionError)

	filters: dict[str, Any] = {"seller_user": user}
	if not int(include_past):
		filters["end_at"] = [">", frappe.utils.now_datetime()]

	rows = frappe.get_all(
		DOCTYPE_SLOT,
		filters=filters,
		fields=["name", "start_at", "end_at", "status", "notes"],
		order_by="start_at asc",
	)
	out = []
	for s in rows:
		out.append(
			{
				"id": s.name,
				"start_at": str(s.start_at),
				"end_at": str(s.end_at),
				"status": s.status,
				"notes": s.notes or "",
				"reservation": _slot_active_reservation(s.name),
			}
		)
	return out


def _slot_active_reservation(slot_name: str) -> dict | None:
	rows = frappe.get_all(
		DOCTYPE_RESERVATION,
		filters={"slot": slot_name, "status": "Active"},
		fields=["name", "buyer_user", "start_at", "end_at"],
		limit_page_length=1,
	)
	if not rows:
		return None
	r = rows[0]
	buyer_name = frappe.db.get_value("User", r.buyer_user, "full_name") or r.buyer_user
	return {
		"id": r.name,
		"buyer_user": r.buyer_user,
		"buyer_name": buyer_name,
		"start_at": str(r.start_at),
		"end_at": str(r.end_at),
	}


def _slot_to_dict(name: str) -> dict[str, Any]:
	s = frappe.db.get_value(
		DOCTYPE_SLOT, name, ["name", "start_at", "end_at", "status", "notes"], as_dict=True
	)
	if not s:
		return {}
	return {
		"id": s.name,
		"start_at": str(s.start_at),
		"end_at": str(s.end_at),
		"status": s.status,
		"notes": s.notes or "",
	}


@frappe.whitelist()
def delete_slot(slot_id: str) -> dict[str, Any]:
	"""Seller slot'u kaldırır. Aktif rezervasyon varsa hata."""
	user = _require_login()
	slot = frappe.db.get_value(DOCTYPE_SLOT, slot_id, ["name", "seller_user", "status"], as_dict=True)
	if not slot:
		frappe.throw(_("Slot bulunamadı."), frappe.DoesNotExistError)
	if slot.seller_user != user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Yetki yok."), frappe.PermissionError)
	if _slot_active_reservation(slot.name):
		frappe.throw(
			_("Bu slot'a aktif bir rezervasyon var; önce iptal etmelisin."),
			frappe.ValidationError,
		)
	frappe.delete_doc(DOCTYPE_SLOT, slot_id, ignore_permissions=True)
	frappe.db.commit()
	return {"deleted": slot_id}


# ─────────────────────────────────────────────────────────────────────────────
# Reservation endpoint'leri
# ─────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def reserve_slot(slot_id: str) -> dict[str, Any]:
	"""Buyer slot'u kilitleyip Chat Reservation oluşturur."""
	buyer = _require_login()
	slot = frappe.db.get_value(
		DOCTYPE_SLOT,
		slot_id,
		["name", "seller_user", "start_at", "end_at", "status"],
		as_dict=True,
	)
	if not slot:
		frappe.throw(_("Slot bulunamadı."), frappe.DoesNotExistError)
	if slot.status != "Open":
		frappe.throw(_("Bu slot artık müsait değil."), frappe.ValidationError)
	if buyer == slot.seller_user:
		frappe.throw(_("Kendi slot'unuza rezervasyon yapamazsınız."), frappe.ValidationError)
	if frappe.utils.get_datetime(slot.end_at) < frappe.utils.now_datetime():
		frappe.throw(_("Geçmiş bir slot için rezervasyon yapılamaz."), frappe.ValidationError)

	# Çift rezervasyon kontrolü — slot zaten kilitliyse hata
	if _slot_active_reservation(slot.name):
		frappe.throw(_("Bu slot başka bir alıcı tarafından alınmış."), frappe.ValidationError)

	res = frappe.new_doc(DOCTYPE_RESERVATION)
	res.buyer_user = buyer
	res.seller_user = slot.seller_user
	res.slot = slot.name
	res.start_at = slot.start_at
	res.end_at = slot.end_at
	res.status = "Active"
	res.insert(ignore_permissions=True)
	frappe.db.commit()
	return _reservation_to_dict(res.name)


@frappe.whitelist()
def list_my_reservations(include_past: int | str = 0) -> list[dict[str, Any]]:
	"""Buyer kendi yaptığı, seller kendine geleni listeler."""
	user = _require_login()
	filters: dict[str, Any] = {}
	role = "seller" if _is_seller(user) else "buyer"
	if role == "seller":
		filters["seller_user"] = user
	else:
		filters["buyer_user"] = user
	if not int(include_past):
		filters["end_at"] = [">", frappe.utils.now_datetime()]

	rows = frappe.get_all(
		DOCTYPE_RESERVATION,
		filters=filters,
		fields=["name", "buyer_user", "seller_user", "start_at", "end_at", "status", "slot"],
		order_by="start_at desc",
	)
	out = []
	for r in rows:
		other = r.seller_user if role == "buyer" else r.buyer_user
		other_name = frappe.db.get_value("User", other, "full_name") or other
		out.append(
			{
				"id": r.name,
				"buyer_user": r.buyer_user,
				"seller_user": r.seller_user,
				"counterpart": other,
				"counterpart_name": other_name,
				"start_at": str(r.start_at),
				"end_at": str(r.end_at),
				"status": r.status,
				"slot": r.slot,
			}
		)
	return out


@frappe.whitelist()
def cancel_reservation(reservation_id: str) -> dict[str, Any]:
	"""Buyer veya seller kendi rezervasyonunu iptal eder."""
	user = _require_login()
	res = frappe.db.get_value(
		DOCTYPE_RESERVATION,
		reservation_id,
		["name", "buyer_user", "seller_user", "status"],
		as_dict=True,
	)
	if not res:
		frappe.throw(_("Rezervasyon bulunamadı."), frappe.DoesNotExistError)
	if user not in (res.buyer_user, res.seller_user) and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Yetki yok."), frappe.PermissionError)
	if res.status != "Active":
		frappe.throw(_("Sadece aktif rezervasyonlar iptal edilebilir."), frappe.ValidationError)

	frappe.db.set_value(
		DOCTYPE_RESERVATION,
		reservation_id,
		{"status": "Cancelled", "cancelled_at": frappe.utils.now_datetime()},
	)
	frappe.db.commit()
	return _reservation_to_dict(reservation_id)


def _reservation_to_dict(name: str) -> dict[str, Any]:
	r = frappe.db.get_value(
		DOCTYPE_RESERVATION,
		name,
		["name", "buyer_user", "seller_user", "start_at", "end_at", "status", "slot", "cancelled_at"],
		as_dict=True,
	)
	if not r:
		return {}
	return {
		"id": r.name,
		"buyer_user": r.buyer_user,
		"seller_user": r.seller_user,
		"start_at": str(r.start_at),
		"end_at": str(r.end_at),
		"status": r.status,
		"slot": r.slot,
		"cancelled_at": str(r.cancelled_at) if r.cancelled_at else None,
	}


# ─────────────────────────────────────────────────────────────────────────────
# Gating
# ─────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def can_chat(seller_id: str) -> dict[str, Any]:
	"""Buyer için: bu seller'la chat açabilir miyim?

	Frontend bunu "Sohbet Et" tıklamadan önce çağırır. allowed=false dönerse
	reason'a göre rezervasyon modal'ı açar.
	"""
	user = _require_login()
	seller_user = _resolve_seller_user(seller_id)
	if user == seller_user:
		# Kendi kendine chat — UI buna izin verebilir ama gating'i atla
		return {"allowed": True, "reason": "self_chat", "tier": "n/a"}

	tier = _seller_tier(seller_user)
	if tier != "Plus":
		return {"allowed": True, "reason": "premium_seller", "tier": tier}

	active = _active_reservation(user, seller_user)
	if active:
		return {
			"allowed": True,
			"reason": "active_reservation",
			"tier": tier,
			"active_reservation": active,
		}

	return {
		"allowed": False,
		"reason": "reservation_required",
		"tier": tier,
		"message": _(
			"Bu satıcı Plus tier'da. Mesajlaşmadan önce müsait bir slot için rezervasyon yapmalısınız."
		),
	}


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler — expired reservations
# ─────────────────────────────────────────────────────────────────────────────


def expire_old_reservations():
	"""hourly scheduler — geçmiş active rezervasyonları Expired yap."""
	now = frappe.utils.now_datetime()
	expired = frappe.get_all(
		DOCTYPE_RESERVATION,
		filters={"status": "Active", "end_at": ["<", now]},
		fields=["name"],
	)
	for r in expired:
		frappe.db.set_value(DOCTYPE_RESERVATION, r.name, "status", "Expired")
	if expired:
		frappe.db.commit()
		frappe.logger("reservation").info(f"Expired {len(expired)} reservations")

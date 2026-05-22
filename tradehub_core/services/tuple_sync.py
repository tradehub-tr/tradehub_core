# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 2.3 — Frappe doc_events → ReBAC tuple sync.

Doc create/update/trash event'leri sırasında ReBAC sidecar'a tuple yazımı
async olarak yapılır (frappe.enqueue, queue="short").

Strateji:
  - Best-effort: tuple sync hatası business flow'u BOZMAZ
  - Async: kullanıcıya gecikme yansımaz (worst-case 5 sn eventual consistency)
  - Idempotent: aynı tuple birden fazla yazılırsa OpenFGA tarafında hata yok

Hook fonksiyonları:
  - on_user_insert / on_user_update / on_user_trash
  - on_admin_seller_profile_insert / on_admin_seller_profile_trash
  - on_organization_insert / on_organization_trash
  - on_listing_insert / on_listing_trash
  - on_order_insert / on_order_trash

Detay: docs/yetki/faz-2/01-tasarim-kararlari.md §5
"""

from __future__ import annotations

import frappe

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _enqueue_write(tuples: list[tuple[str, str, str]]) -> None:
	"""Async tuple write — short queue (worst-case 5 sn)."""
	if not tuples:
		return
	frappe.enqueue(
		"tradehub_core.services.rebac_client.write_tuples",
		queue="short",
		tuples=tuples,
		enqueue_after_commit=True,  # DB commit'ten sonra çalış
	)


def _enqueue_delete(tuples: list[tuple[str, str, str]]) -> None:
	"""Async tuple delete."""
	if not tuples:
		return
	frappe.enqueue(
		"tradehub_core.services.rebac_client.delete_tuples",
		queue="short",
		tuples=tuples,
		enqueue_after_commit=True,
	)


def _user_tuples_for_seller(user_name: str, tenant: str) -> list[tuple[str, str, str]]:
	"""Bir Seller sub-user için ReBAC tuple'ları üret.

	Role atamaları `frappe.get_roles()` üzerinden okunur — role_profile_name
	string match'i kırılgan (birden çok role profile, isim çakışmaları).
	"""
	user = f"user:{user_name}"
	store = f"store:{tenant}"

	roles = set(frappe.get_roles(user_name) or [])
	tuples: list[tuple[str, str, str]] = [(user, "member", store)]

	# Owner: explicit flag (tradehub_is_owner=1) veya "Seller Owner" rolü
	is_owner = frappe.db.get_value("User", user_name, "tradehub_is_owner")
	if is_owner or "Seller Owner" in roles:
		tuples.append((user, "owner", store))

	# Co-Owner: rolü taşıyan
	if "Seller Co-Owner" in roles:
		tuples.append((user, "co_owner", store))

	return tuples


def _user_tuples_for_buyer(user_name: str, organization: str) -> list[tuple[str, str, str]]:
	"""Bir Buyer sub-user için ReBAC tuple'ları üret.

	Rol set'i `frappe.get_roles()` üzerinden okunur — eski versiyon
	`role_profile_name` üzerinde substring match yapıyordu ve:
	  - "Buyer Approver L2" rolü "Approver" içerdiği için L1'e mapleniyor,
	    L2 hiç tuple kazanmıyordu.
	  - "Buyer Procurement" rolü "Procurement" string'ini sadece role profile
	    "Buyer Operations" değilse içermediği için tuple yazılmayabiliyordu.
	"""
	user = f"user:{user_name}"
	org = f"buyer_org:{organization}"

	roles = set(frappe.get_roles(user_name) or [])
	tuples: list[tuple[str, str, str]] = [(user, "member", org)]

	# Admin: Buyer Admin rolü
	if "Buyer Admin" in roles:
		tuples.append((user, "admin", org))

	# Requisitioner: Buyer Procurement (veya legacy "Buyer Requisitioner")
	if "Buyer Procurement" in roles or "Buyer Requisitioner" in roles:
		tuples.append((user, "requisitioner", org))

	# Approver L1 (kümülatif L1 yetkisi)
	if "Buyer Approver L1" in roles or "Buyer Approver L2" in roles:
		tuples.append((user, "approver_l1", org))

	# Approver L2 (sadece L2 rolü)
	if "Buyer Approver L2" in roles:
		tuples.append((user, "approver_l2", org))

	# Finance
	if "Buyer Finance" in roles:
		tuples.append((user, "finance", org))

	# Viewer (read-only)
	if "Buyer Viewer" in roles:
		tuples.append((user, "viewer", org))

	return tuples


# ---------------------------------------------------------------------------
# User hooks
# ---------------------------------------------------------------------------


def on_user_insert(doc, method=None) -> None:
	"""User after_insert → tenant/org ilişkilerini OpenFGA'a yaz."""
	tenant = doc.get("tradehub_tenant")
	parent_org = doc.get("tradehub_parent_organization")

	tuples: list[tuple[str, str, str]] = []
	if tenant:
		tuples.extend(_user_tuples_for_seller(doc.name, tenant))
	if parent_org:
		tuples.extend(_user_tuples_for_buyer(doc.name, parent_org))

	_enqueue_write(tuples)


def on_user_update(doc, method=None) -> None:
	"""User on_update → ilişkileri tekrar sync et + stale tuple temizliği.

	D1: Eski versiyon sadece güncel tuple set'ini yazıyordu; rol değişimi
	(örn. Approver L2 → Viewer'a düşürüldü) sonrası eski tuple OpenFGA'da
	kalıyor → ex-approver hala approve edebiliyordu. Strateji:
	  1. Stale set: bu user için yazılmış olabilecek **tüm** muhtemel rol
	     tuple'larını sil (idempotent — yok olan tuple'lar OpenFGA tarafından
	     sessizce kabul edilir).
	  2. Fresh set: güncel rollere göre yeniden yaz.

	Sıralama önemli: önce delete enqueue, sonra write enqueue. `enqueue_after_commit`
	garantili FIFO değil; bu yüzden idempotency yazma tarafında — `member` gibi
	default tuple'lar hem silinip hem yazıldığında son durumu garanti eder.
	"""
	tenant = doc.get("tradehub_tenant")
	parent_org = doc.get("tradehub_parent_organization")

	user = f"user:{doc.name}"
	stale_tuples: list[tuple[str, str, str]] = []
	fresh_tuples: list[tuple[str, str, str]] = []

	if tenant:
		store = f"store:{tenant}"
		# Seller-side stale: tüm potansiyel relation'ları sil
		stale_tuples.extend(
			[
				(user, "member", store),
				(user, "owner", store),
				(user, "co_owner", store),
			]
		)
		fresh_tuples.extend(_user_tuples_for_seller(doc.name, tenant))

	if parent_org:
		org = f"buyer_org:{parent_org}"
		# Buyer-side stale: tüm potansiyel relation'ları sil
		stale_tuples.extend(
			[
				(user, "member", org),
				(user, "admin", org),
				(user, "requisitioner", org),
				(user, "approver_l1", org),
				(user, "approver_l2", org),
				(user, "finance", org),
				(user, "viewer", org),
			]
		)
		fresh_tuples.extend(_user_tuples_for_buyer(doc.name, parent_org))

	if stale_tuples:
		_enqueue_delete(stale_tuples)
	if fresh_tuples:
		_enqueue_write(fresh_tuples)


def on_user_trash(doc, method=None) -> None:
	"""User on_trash → kullanıcının tüm tuple'larını sil."""
	user = f"user:{doc.name}"
	tenant = doc.get("tradehub_tenant")
	parent_org = doc.get("tradehub_parent_organization")

	tuples: list[tuple[str, str, str]] = []
	if tenant:
		store = f"store:{tenant}"
		tuples.extend([(user, "member", store), (user, "owner", store), (user, "co_owner", store)])
	if parent_org:
		org = f"buyer_org:{parent_org}"
		tuples.extend(
			[
				(user, "member", org),
				(user, "admin", org),
				(user, "requisitioner", org),
				(user, "approver_l1", org),
				(user, "approver_l2", org),
				(user, "finance", org),
				(user, "viewer", org),
			]
		)

	# delete_tuples idempotent — olmayan tuple'lar OpenFGA tarafından sessizce
	# kabul edilir (OpenFGA write API delete'i kontrol etmez)
	_enqueue_delete(tuples)


# ---------------------------------------------------------------------------
# Admin Seller Profile hooks (store entity)
# ---------------------------------------------------------------------------


def on_admin_seller_profile_insert(doc, method=None) -> None:
	"""Admin Seller Profile after_insert → store entity oluştu, Owner tuple'ı yaz."""
	if not doc.user:
		return  # Owner henüz bağlanmamış (Faz 1.5 davet akışında olur)

	store = f"store:{doc.name}"
	user = f"user:{doc.user}"

	_enqueue_write([(user, "owner", store), (user, "member", store)])


def on_admin_seller_profile_trash(doc, method=None) -> None:
	"""Admin Seller Profile silindi → tüm store ilişkilerini sil.

	Pratik: store silinmez (status=Inactive), ama yine de defansif sil hook'u.
	"""
	# Bu store'a bağlı tüm user'ları bul
	users = frappe.get_all("User", filters={"tradehub_tenant": doc.name}, pluck="name")
	store = f"store:{doc.name}"
	tuples: list[tuple[str, str, str]] = []
	for u in users:
		user = f"user:{u}"
		tuples.extend([(user, "owner", store), (user, "co_owner", store), (user, "member", store)])
	_enqueue_delete(tuples)


# ---------------------------------------------------------------------------
# Organization (CRM) hooks — Faz 2.4'te detaylı parent_org hiyerarşisi
# ---------------------------------------------------------------------------


def on_organization_insert(doc, method=None) -> None:
	"""CRM Organization after_insert → buyer_org entity.

	parent_org varsa group hiyerarşisi tuple'ı da yaz.
	"""
	org = f"buyer_org:{doc.name}"
	tuples: list[tuple[str, str, str]] = []

	# Parent organization (hiyerarşi)
	parent = doc.get("tradehub_parent_org")
	if parent:
		# Group hiyerarşisi: bu org'u grup olarak tutarsak parent'a bağla
		# (Faz 2.4 detayına göre revise edilecek)
		group_self = f"group:{doc.name}"
		group_parent = f"group:{parent}"
		tuples.append((group_self, "parent", group_parent))

	# Bu organizasyonun ilk admin'i (varsa)
	admin = doc.get("tradehub_org_admin")
	if admin:
		tuples.append((f"user:{admin}", "admin", org))

	_enqueue_write(tuples)


def on_organization_trash(doc, method=None) -> None:
	"""Organization silinince hiyerarşi tuple'ını sil."""
	parent = doc.get("tradehub_parent_org")
	if parent:
		_enqueue_delete([(f"group:{doc.name}", "parent", f"group:{parent}")])


# ---------------------------------------------------------------------------
# Listing hooks
# ---------------------------------------------------------------------------


def on_listing_insert(doc, method=None) -> None:
	"""Listing after_insert → listing.store_link tuple."""
	if not doc.get("seller_profile"):
		return
	listing = f"listing:{doc.name}"
	store = f"store:{doc.seller_profile}"
	_enqueue_write([(listing, "store_link", store)])


def on_listing_trash(doc, method=None) -> None:
	"""Listing silindi → tüm ilişkileri sil."""
	if not doc.get("seller_profile"):
		return
	listing = f"listing:{doc.name}"
	store = f"store:{doc.seller_profile}"
	_enqueue_delete([(listing, "store_link", store)])


# ---------------------------------------------------------------------------
# Order hooks
# ---------------------------------------------------------------------------


def on_order_insert(doc, method=None) -> None:
	"""Order after_insert → store + buyer_org + requisitioner tuple'ları."""
	tuples: list[tuple[str, str, str]] = []
	order = f"order:{doc.name}"

	if doc.get("seller_profile"):
		tuples.append((order, "store_link", f"store:{doc.seller_profile}"))

	# Buyer organization (varsa)
	buyer_org = doc.get("buyer_organization") or doc.get("buyer_profile")
	if buyer_org:
		tuples.append((order, "buyer_org_link", f"buyer_org:{buyer_org}"))

	# Requisitioner (sipariş açan user)
	created_by = doc.owner  # Frappe Document owner field
	if created_by and created_by != "Administrator":
		tuples.append((order, "requisitioner", f"user:{created_by}"))

	_enqueue_write(tuples)


def on_order_trash(doc, method=None) -> None:
	"""Order silindi → tüm ilişkileri sil."""
	order = f"order:{doc.name}"
	tuples: list[tuple[str, str, str]] = []

	if doc.get("seller_profile"):
		tuples.append((order, "store_link", f"store:{doc.seller_profile}"))

	buyer_org = doc.get("buyer_organization") or doc.get("buyer_profile")
	if buyer_org:
		tuples.append((order, "buyer_org_link", f"buyer_org:{buyer_org}"))

	if doc.owner:
		tuples.append((order, "requisitioner", f"user:{doc.owner}"))

	_enqueue_delete(tuples)

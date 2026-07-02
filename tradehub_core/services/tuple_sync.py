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

	# #C1 — OpenFGA Write API transactional'dır; olmayan tuple'ı silmek 400 verir.
	# Idempotency delete_tuples içindeki per-tuple fallback ile sağlanır (batch 4xx
	# alırsa tek tek dener, "mevcut değil" hatalarını tolere eder). Bu downgrade
	# senaryosunda "tüm olası relation"ları toplu silmek artık güvenli.
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


def on_admin_seller_profile_update(doc, method=None) -> None:
	"""#C2 — Admin Seller Profile.user (owner) değişince eski owner/member
	tuple'larını sil, yeni owner'a yaz. Aksi halde eski owner store'a erişmeye
	devam eder (stale grant)."""
	before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
	if before is None:
		return
	old_user = before.get("user")
	new_user = doc.get("user")
	if old_user == new_user:
		return
	store = f"store:{doc.name}"
	if old_user:
		_enqueue_delete([(f"user:{old_user}", "owner", store), (f"user:{old_user}", "member", store)])
	if new_user:
		_enqueue_write([(f"user:{new_user}", "owner", store), (f"user:{new_user}", "member", store)])


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


# Faz 6 — alan-bazlı izin part'ları (Airbnb type:id:part). Object:
# `listing_field:<listing>:<PART>`.
LISTING_FIELD_PARTS = ("PRICE", "DESCRIPTION", "COST")


def _owner_field_tuples(listing_name: str, owner_user: str) -> list[tuple[str, str, str]]:
	"""Mağaza sahibine tüm part'larda field_editor (owner tüm alanları düzenler)."""
	u = f"user:{owner_user}"
	# Ayraç '/': OpenFGA id'sinde ':' geçersiz (bkz. registry.field_target_for).
	return [(u, "field_editor", f"listing_field:{listing_name}/{p}") for p in LISTING_FIELD_PARTS]


def on_listing_insert(doc, method=None) -> None:
	"""Listing after_insert → store_link + mağaza sahibi field_editor (tüm part'lar)."""
	if not doc.get("seller_profile"):
		return
	listing = f"listing:{doc.name}"
	store = f"store:{doc.seller_profile}"
	tuples = [(listing, "store_link", store)]
	owner = frappe.db.get_value("Admin Seller Profile", doc.seller_profile, "user")
	if owner:
		tuples.extend(_owner_field_tuples(doc.name, owner))
	_enqueue_write(tuples)


def on_listing_update(doc, method=None) -> None:
	"""#C2 — Listing başka mağazaya taşınırsa (seller_profile değişimi) eski
	store_link tuple'ını sil, yeniyi yaz (orphan tuple önle)."""
	before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
	if before is None:
		return
	old_store = before.get("seller_profile")
	new_store = doc.get("seller_profile")
	if old_store == new_store:
		return
	listing = f"listing:{doc.name}"
	if old_store:
		_enqueue_delete([(listing, "store_link", f"store:{old_store}")])
	if new_store:
		_enqueue_write([(listing, "store_link", f"store:{new_store}")])


def on_listing_trash(doc, method=None) -> None:
	"""Listing silindi → store_link + owner field_editor tuple'larını sil."""
	if not doc.get("seller_profile"):
		return
	listing = f"listing:{doc.name}"
	store = f"store:{doc.seller_profile}"
	tuples = [(listing, "store_link", store)]
	owner = frappe.db.get_value("Admin Seller Profile", doc.seller_profile, "user")
	if owner:
		tuples.extend(_owner_field_tuples(doc.name, owner))
	_enqueue_delete(tuples)


# ---------------------------------------------------------------------------
# Field-level grant/revoke (alt-hesap operasyon/finans rolleri) — Faz 6
# ---------------------------------------------------------------------------


def grant_field_access(user: str, listing_name: str, part: str, relation: str = "field_editor") -> bool:
	"""Bir kullanıcıya listing'in BELİRLİ bir alanında (part) izin ver.

	relation: 'field_editor' (düzenle) | 'field_viewer' (gör). SENKRON yazar
	(admin aksiyonu hemen etkili olsun). part LISTING_FIELD_PARTS içinde olmalı.
	"""
	if part not in LISTING_FIELD_PARTS:
		frappe.throw(frappe._("Geçersiz alan: {0}").format(part))
	from tradehub_core.services import rebac_client

	return rebac_client.write_tuples(
		[(f"user:{user}", relation, f"listing_field:{listing_name}/{part}")]
	)


def revoke_field_access(user: str, listing_name: str, part: str, relation: str = "field_editor") -> bool:
	"""grant_field_access'in tersi — alan iznini kaldır (senkron)."""
	from tradehub_core.services import rebac_client

	return rebac_client.delete_tuples(
		[(f"user:{user}", relation, f"listing_field:{listing_name}/{part}")]
	)


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


def on_order_update(doc, method=None) -> None:
	"""#C2 — Order.seller_profile / buyer_org değişince eski link tuple'larını
	sil, yenilerini yaz (reassignment sonrası orphan/stale link önle)."""
	before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
	if before is None:
		return
	order = f"order:{doc.name}"
	stale: list[tuple[str, str, str]] = []
	fresh: list[tuple[str, str, str]] = []

	old_seller = before.get("seller_profile")
	new_seller = doc.get("seller_profile")
	if old_seller != new_seller:
		if old_seller:
			stale.append((order, "store_link", f"store:{old_seller}"))
		if new_seller:
			fresh.append((order, "store_link", f"store:{new_seller}"))

	old_bo = before.get("buyer_organization") or before.get("buyer_profile")
	new_bo = doc.get("buyer_organization") or doc.get("buyer_profile")
	if old_bo != new_bo:
		if old_bo:
			stale.append((order, "buyer_org_link", f"buyer_org:{old_bo}"))
		if new_bo:
			fresh.append((order, "buyer_org_link", f"buyer_org:{new_bo}"))

	if stale:
		_enqueue_delete(stale)
	if fresh:
		_enqueue_write(fresh)


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


# ---------------------------------------------------------------------------
# Reconciliation (#C6) — Frappe = kaynak-doğru; eksik grant'ları self-heal et
# ---------------------------------------------------------------------------


def reconcile_user(user_name: str) -> int:
	"""Kullanıcının beklenen seller/buyer tuple'larını Frappe'den yeniden üretip
	OpenFGA'ya (idempotent) yazar → EKSİK grant'ları self-heal eder.

	Sınır: write-only. EXTRA/stale tuple'ların SİLİNMESİ OpenFGA Read API'si
	gerektirir (henüz yok); o yön owner-transfer event'leri (on_*_update) +
	drift_detection ile ele alınır. Bu fonksiyon "missing grant" tarafını kapatır.
	Idempotency rebac_client.write_tuples per-tuple fallback'i (#C1) ile sağlanır.
	"""
	tenant = frappe.db.get_value("User", user_name, "tradehub_tenant")
	parent_org = frappe.db.get_value("User", user_name, "tradehub_parent_organization")
	tuples: list[tuple[str, str, str]] = []
	if tenant:
		tuples.extend(_user_tuples_for_seller(user_name, tenant))
	if parent_org:
		tuples.extend(_user_tuples_for_buyer(user_name, parent_org))
	if not tuples:
		return 0
	_enqueue_write(tuples)
	return len(tuples)


def reconcile_users(limit: int = 100) -> dict:
	"""Batch reconciliation — enabled user örneğini self-heal eder (scheduler'dan
	çağrılabilir). Sidecar down ise write no-op (fail-closed)."""
	users = frappe.get_all("User", filters={"enabled": 1}, pluck="name", limit=limit) or []
	total = 0
	for u in users:
		try:
			total += reconcile_user(u)
		except Exception as exc:  # noqa: BLE001
			frappe.log_error(f"reconcile_user {u} failed: {exc}", "tuple_sync.reconcile")
	return {"users": len(users), "tuples_written": total}

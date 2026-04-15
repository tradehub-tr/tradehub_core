"""
Helpdesk team routing — marketplace akisi.

Ticket'lar sipariş referansi varsa o siparişin satıcı team'ine, yoksa
Platform Support team'ine yönlendirilir. Satıcı Admin Seller Profile
aktiflesince kendisine ait HD Team + HD Agent otomatik olusur.
"""

import contextlib

import frappe

PLATFORM_SUPPORT_TEAM = "Platform Support"


@contextlib.contextmanager
def _as_admin():
    """HD Team/HD Agent insert/save işlemleri Link permission ve helpdesk
    role kontrolünden dolayı normal müşteri user'da da patlar — her zaman
    Administrator olarak geçici impersonate (sadece Guest değil)."""
    original = frappe.session.user
    if original != "Administrator":
        frappe.set_user("Administrator")
    try:
        yield
    finally:
        if original != "Administrator":
            frappe.set_user(original)


# ── Team helpers ────────────────────────────────────────────────────────

def ensure_platform_support_team() -> str:
    """Default (genel) destek ekibi — kategori/sipariş yoksa ticket buraya dusger."""
    if not frappe.db.exists("HD Team", PLATFORM_SUPPORT_TEAM):
        with _as_admin():
            team = frappe.new_doc("HD Team")
            team.team_name = PLATFORM_SUPPORT_TEAM
            team.insert(ignore_permissions=True)
            frappe.db.commit()
    return PLATFORM_SUPPORT_TEAM


def seller_team_name(admin_seller_profile: str) -> str:
    return f"Seller-{admin_seller_profile}"


def ensure_seller_team(admin_seller_profile: str) -> str | None:
    """Admin Seller Profile icin HD Team olustur + user'i HD Agent olarak
    ekle. Sadece Active saticilar icin team kurulur. Ba$arisizsa None.
    """
    if not admin_seller_profile:
        return None

    profile = frappe.db.get_value(
        "Admin Seller Profile",
        admin_seller_profile,
        ["user", "status"],
        as_dict=True,
    )
    if not profile or not profile.get("user"):
        return None
    if profile.get("status") and profile["status"] != "Active":
        return None

    user = profile["user"]
    team_name = seller_team_name(admin_seller_profile)

    with _as_admin():
        # 1) HD Agent (user bazli unique) — yoksa olustur
        if not frappe.db.exists("HD Agent", {"user": user}):
            try:
                agent = frappe.new_doc("HD Agent")
                agent.user = user
                agent.agent_name = user
                agent.insert(ignore_permissions=True)
            except Exception:
                frappe.log_error(title="helpdesk_routing ensure HD Agent")

        # 2) HD Team — yoksa olustur, varsa user'i uyeler'e ekle
        if not frappe.db.exists("HD Team", team_name):
            team = frappe.new_doc("HD Team")
            team.team_name = team_name
            team.append("users", {"user": user})
            team.insert(ignore_permissions=True)
        else:
            team = frappe.get_doc("HD Team", team_name)
            if not any(u.user == user for u in (team.users or [])):
                team.append("users", {"user": user})
                team.save(ignore_permissions=True)

        frappe.db.commit()
    return team_name


# ── Order → team cozumleme ─────────────────────────────────────────────

def resolve_team_for_order(order_name: str) -> str | None:
    """Order'in satici team'ini dondur. Order/seller/user yoksa None."""
    if not order_name:
        return None
    seller = frappe.db.get_value("Order", order_name, "seller")
    if not seller:
        return None
    return ensure_seller_team(seller)


# ── Hook: Admin Seller Profile on_update ──────────────────────────────

def on_admin_seller_profile_update(doc, method=None):
    """Admin Seller Profile aktif oldugunda team+agent sync et.

    Note: on_update her degisiklikte calisir; ensure_* idempotent
    oldugundan ekstra kontrole gerek yok.
    """
    try:
        if doc.get("status") == "Active" and doc.get("user"):
            ensure_seller_team(doc.name)
    except Exception:
        frappe.log_error(title="helpdesk_routing on_admin_seller_profile_update")

"""Güvenlik testleri için 9 persona + iki satıcı profili seed'i (LOKAL/STAGING).

Bu script SADECE lokal/staging'de, bize ait sistemde çalıştırılmalıdır. Üretimde
ASLA çalıştırmayın (env guard ile korunur). Idempotent: var olan kullanıcıyı atlar,
yalnız eksikleri ekler. Hiçbir kaydı silmez.

Personalar (tests/security/conftest.py fixture'larıyla eşleşir):
  seller_a, seller_b, buyer_a, buyer_b, company_a, company_b,
  company_admin, normal_user, platform_admin

Çalıştırma (container içinde):
  docker exec docker-backend-1 bench --site dev.localhost execute \
    tradehub_core.setup.seed_security_test_personas.execute

Çıktıdaki bloğu tests/security/.env içine yapıştırın. Çapraz-tenant referanslarını
(order/invoice/product id) doldurmak için:
  ... execute tradehub_core.setup.seed_security_test_personas.discover_refs
"""
from __future__ import annotations

import os

import frappe

# Lokal/staging dışında çalışmayı engelleyen guard. site_config'e
# "allow_security_persona_seed": 1 eklenmiş VEYA site adı *.localhost olmalı.
_ALLOWED_SITE_SUFFIXES = (".localhost", ".local")

# Test parolası — yalnız lokal test personaları için. Üretimde kullanılmaz.
TEST_PASSWORD = os.environ.get("TH_SEED_PASSWORD", "Test-Sec-2026!")

# (env_prefix, email, first_name, roles)
# Roller yalnız DB'de mevcutsa atanır (defansif).
_PERSONAS = [
    ("TH_SELLER_A", "sec_seller_a@test.local", "Seller A", ["Marketplace Seller", "Seller Owner"]),
    ("TH_SELLER_B", "sec_seller_b@test.local", "Seller B", ["Marketplace Seller", "Seller Owner"]),
    ("TH_SELLER_A_STAFF", "sec_seller_a_staff@test.local", "Seller A Staff", ["Marketplace Seller"]),
    ("TH_BUYER_A", "sec_buyer_a@test.local", "Buyer A", ["Buyer"]),
    ("TH_BUYER_B", "sec_buyer_b@test.local", "Buyer B", ["Buyer"]),
    ("TH_COMPANY_A", "sec_company_a@test.local", "Company A User", ["Buyer"]),
    ("TH_COMPANY_B", "sec_company_b@test.local", "Company B User", ["Buyer"]),
    ("TH_COMPANY_ADMIN", "sec_company_admin@test.local", "Company Admin", ["Buyer", "Buyer Admin"]),
    ("TH_NORMAL_USER", "sec_normal_user@test.local", "Normal User", []),
    ("TH_ADMIN", "sec_platform_admin@test.local", "Platform Admin", ["System Manager", "Marketplace Admin"]),
]

# Hangi persona hangi seller tenant'ına (Admin Seller Profile) sahip olacak.
_SELLER_PROFILES = [
    {"env": "TH_SELLER_A", "seller_name": "SecTest Seller A", "user": "sec_seller_a@test.local"},
    {"env": "TH_SELLER_B", "seller_name": "SecTest Seller B", "user": "sec_seller_b@test.local"},
]


def _assert_local() -> None:
    site = frappe.local.site or ""
    cfg_ok = bool(frappe.conf.get("allow_security_persona_seed"))
    suffix_ok = any(site.endswith(s) for s in _ALLOWED_SITE_SUFFIXES)
    if not (cfg_ok or suffix_ok):
        frappe.throw(
            f"GÜVENLİK GUARD: '{site}' lokal/staging değil. Seed reddedildi. "
            "Lokal site adı *.localhost olmalı veya site_config'e "
            "'allow_security_persona_seed': 1 ekleyin."
        )


def _existing_roles(candidates: list[str]) -> list[str]:
    if not candidates:
        return []
    return frappe.get_all("Role", filters={"name": ["in", candidates]}, pluck="name")


def _ensure_user(email: str, first_name: str, roles: list[str]) -> str:
    if frappe.db.exists("User", email):
        return email
    doc = frappe.new_doc("User")
    doc.email = email
    doc.first_name = first_name
    doc.send_welcome_email = 0
    doc.user_type = "System User"
    doc.new_password = TEST_PASSWORD
    for role in _existing_roles(roles):
        doc.append("roles", {"role": role})
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    return email


def _ensure_seller_profile(spec: dict) -> None:
    if not frappe.db.exists("DocType", "Admin Seller Profile"):
        return
    if frappe.db.exists("Admin Seller Profile", {"user": spec["user"]}):
        return
    try:
        doc = frappe.new_doc("Admin Seller Profile")
        doc.user = spec["user"]
        # En yaygın alan adları; şema farklıysa try/except sessizce geçer.
        for field, value in (("seller_name", spec["seller_name"]), ("name1", spec["seller_name"])):
            if doc.meta.has_field(field):
                doc.set(field, value)
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True)
    except Exception as exc:
        frappe.log_error(f"seller profile seed failed: {exc}", "seed_security_test_personas")


def execute() -> dict:
    """9 persona + 2 satıcı profili oluştur (idempotent) ve .env bloğunu yazdır."""
    _assert_local()

    created, skipped = [], []
    for _env, email, first_name, roles in _PERSONAS:
        existed = frappe.db.exists("User", email)
        _ensure_user(email, first_name, roles)
        (skipped if existed else created).append(email)

    for spec in _SELLER_PROFILES:
        _ensure_seller_profile(spec)

    frappe.db.commit()

    # .env bloğu
    lines = ["", "# === tests/security/.env — güvenlik persona kimlikleri (LOKAL) ===",
             "TH_BASE_URL=http://localhost:8000"]
    for env, email, _fn, _roles in _PERSONAS:
        lines.append(f"{env}_USER={email}")
        lines.append(f"{env}_PASS={TEST_PASSWORD}")
    env_block = "\n".join(lines)
    print(env_block)  # noqa: T201 — bench execute çıktısına yazdırılır

    return {
        "created": created,
        "skipped": skipped,
        "password": TEST_PASSWORD,
        "env_block": env_block,
        "next": "Çapraz-tenant referansları için: ...seed_security_test_personas.discover_refs",
    }


def discover_refs() -> dict:
    """Mevcut kayıtlardan çapraz-tenant referanslarını (order/invoice/product) keşfet
    ve tests/security/.env için TH_REF_* bloğunu yazdır.

    Persona'ların gerçekten sipariş/ürünü yoksa boş döner — o testler skip olur.
    """
    _assert_local()

    def _first(doctype: str, filters: dict) -> str | None:
        if not frappe.db.exists("DocType", doctype):
            return None
        rows = frappe.get_all(doctype, filters=filters, pluck="name", limit=1)
        return rows[0] if rows else None

    seller_a = frappe.db.get_value("Admin Seller Profile", {"user": "sec_seller_a@test.local"}, "name")
    seller_b = frappe.db.get_value("Admin Seller Profile", {"user": "sec_seller_b@test.local"}, "name")

    refs = {
        "TH_REF_SELLER_A_PROFILE": seller_a,
        "TH_REF_SELLER_B_PROFILE": seller_b,
        "TH_REF_SELLER_A_PRODUCT": _first("Listing", {"seller_profile": seller_a}) if seller_a else None,
        "TH_REF_SELLER_B_PRODUCT": _first("Listing", {"seller_profile": seller_b}) if seller_b else None,
        "TH_REF_BUYER_A_ORDER": _first("Order", {"buyer": "sec_buyer_a@test.local"}),
        "TH_REF_BUYER_B_ORDER": _first("Order", {"buyer": "sec_buyer_b@test.local"}),
        "TH_REF_COMPANY_A_ORDER": _first("Order", {"buyer": "sec_company_a@test.local"}),
        "TH_REF_COMPANY_B_ORDER": _first("Order", {"buyer": "sec_company_b@test.local"}),
    }

    lines = ["", "# === tests/security/.env — çapraz-tenant referansları (keşfedildi) ==="]
    for k, v in refs.items():
        lines.append(f"{k}={v or ''}")
    block = "\n".join(lines)
    print(block)  # noqa: T201
    return {"refs": refs, "env_block": block}

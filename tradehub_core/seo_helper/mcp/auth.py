"""MCP kimlik doğrulaması (14.3) — API key + rol; mağaza izolasyonu §1.4 ile aynı kural.

- Anahtar: `X-MCP-Key: shc_<prefix>_<secret>`; DB'de yalnız sha256 özeti (`MCP Client.api_key_hash`).
- `auth_hooks` kancası YALNIZ `/api/method/tradehub_core.seo_helper.mcp.api.*` yolunda oturum kurar
  (MOGEM-665 kancasıyla aynı disiplin): istemcinin mağazası varsa mağaza sahibi oturumu,
  yoksa `MCP Agent` rollü sistem kullanıcısı `mcp-agent@seo-helper.local` (hiçbir DocType'ta
  yazma DocPerm'i yok; yazmalar taslak uçlarından `ignore_permissions` ile ve store denetimiyle).
- Kapsam (`scopes`) araç başına denetlenir; yazma araçları taslak dışında hiçbir şey üretemez.
"""

from __future__ import annotations

import hashlib
import secrets

import frappe
from frappe import _
from frappe.utils import now_datetime

MCP_PATH_PREFIX = "/api/method/tradehub_core.seo_helper.mcp.api."
HEADER = "X-MCP-Key"
AGENT_USER = "mcp-agent@seo-helper.local"
SCOPES = ("page:read", "page:draft", "metadata:suggest", "translation:draft", "audit:run", "audit:read")


def generate_key() -> tuple[str, str, str]:
	"""(tam anahtar — bir kez gösterilir, prefix, sha256)."""
	prefix = secrets.token_hex(4)
	secret = secrets.token_urlsafe(32)
	key = f"shc_{prefix}_{secret}"
	return key, prefix, hashlib.sha256(key.encode()).hexdigest()


def client_for_key(key: str | None):
	if not key or not key.startswith("shc_"):
		return None
	h = hashlib.sha256(key.encode()).hexdigest()
	row = frappe.db.get_value(
		"MCP Client",
		{"api_key_hash": h, "enabled": 1},
		["name", "role", "scopes", "store", "monthly_token_budget", "tokens_used_month"],
		as_dict=True,
	)
	return row


def ensure_agent_user() -> str:
	if not frappe.db.exists("User", AGENT_USER):
		u = frappe.get_doc(
			{
				"doctype": "User",
				"email": AGENT_USER,
				"first_name": "MCP Agent",
				"user_type": "System User",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		)
		u.flags.ignore_permissions = True
		u.insert()
		u.add_roles("MCP Agent")
	return AGENT_USER


def authenticate_mcp_client() -> None:
	"""Frappe auth_hooks — form_dict korunur (frappe.set_user sıfırlar; MOGEM-665 ölçümü)."""
	req = getattr(frappe.local, "request", None)
	if not req or not str(getattr(req, "path", "") or "").startswith(MCP_PATH_PREFIX):
		return
	client = client_for_key(req.headers.get(HEADER))
	if not client:
		return  # uç fonksiyonu `require_client` ile 401 üretir
	owner = frappe.db.get_value("Admin Seller Profile", client.store, "user") if client.store else None
	form_dict = frappe.local.form_dict
	frappe.set_user(owner or ensure_agent_user())
	frappe.local.form_dict = form_dict
	frappe.local.mcp_client = client


def require_client(scope: str):
	"""Uç kapısı: geçerli anahtar + kapsam; döner MCP Client satırı. Kota aşımında 429."""
	client = getattr(frappe.local, "mcp_client", None)
	if client is None:
		req = getattr(frappe.local, "request", None)
		client = client_for_key(req.headers.get(HEADER) if req else None)
	if not client:
		frappe.throw(_("Geçersiz ya da eksik MCP anahtarı"), frappe.AuthenticationError)
	kapsamlar = {s.strip() for s in (client.scopes or "").split(",") if s.strip()}
	if scope not in kapsamlar:
		frappe.throw(_("Bu araç için kapsam yok: {0}").format(scope), frappe.PermissionError)
	if client.monthly_token_budget and int(client.tokens_used_month or 0) >= int(client.monthly_token_budget):
		from tradehub_core.api.rate_limit import TooManyRequestsError

		raise TooManyRequestsError(_("MCP aylık token bütçesi doldu"))
	frappe.db.set_value("MCP Client", client.name, "last_used_at", now_datetime(), update_modified=False)
	return client


def store_scope(client, store: str | None) -> str | None:
	"""İstemci mağazaya bağlıysa istek o mağazayla sınırlı; platform istemcisi açık store verebilir."""
	if client.store:
		if store and store != client.store:
			frappe.throw(_("Başka mağazanın kaydına erişilemez"), frappe.PermissionError)
		return client.store
	return store

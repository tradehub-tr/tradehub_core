"""MCP sunucusu (14.3) — Frappe'den AYRI süreç; `mcp` SDK (stdio) ile OpenAI/Agents istemcisine
araç seti sunar, her aracı Frappe whitelisted uçlarına (`tradehub_core.seo_helper.mcp.api.*`) API
anahtarıyla iletir. Frappe içine import EDİLMEZ (bench dışında koşar).

Çalıştırma:
    SHC_BASE_URL=https://istoc.example.com SHC_MCP_KEY=shc_... python -m tradehub_core.seo_helper.mcp.server
Bağımlılık: `pip install "mcp>=1.0" requests` (1.x FastMCP ve 2.x MCPServer desteklenir).
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

BASE = os.environ.get("SHC_BASE_URL", "http://localhost:8001").rstrip("/")
KEY = os.environ.get("SHC_MCP_KEY", "")
HOST = os.environ.get("SHC_HOST_HEADER", "")
TIMEOUT = int(os.environ.get("SHC_TIMEOUT", "60"))
API = "tradehub_core.seo_helper.mcp.api"


def call(method: str, **params: Any) -> dict:
	"""Whitelisted uca POST; Frappe `{"message": ...}` zarfını açar, hatayı düz metne çevirir."""
	headers = {"X-MCP-Key": KEY, "Content-Type": "application/json", "Accept": "application/json"}
	if HOST:
		headers["Host"] = HOST
	r = requests.post(
		f"{BASE}/api/method/{API}.{method}",
		json={k: v for k, v in params.items() if v is not None},
		headers=headers,
		timeout=TIMEOUT,
	)
	try:
		body = r.json()
	except ValueError:
		body = {"_raw": r.text[:300]}
	if r.status_code >= 400:
		mesaj = body.get("exception") or body.get("_server_messages") or body.get("_raw") or r.text[:300]
		raise RuntimeError(f"HTTP {r.status_code}: {mesaj}")
	return body.get("message", body)


def build_server():
	try:  # mcp>=2: FastMCP → MCPServer (aynı tool() dekoratörü / run(transport))
		from mcp.server.mcpserver import MCPServer as FastMCP
	except ImportError:  # mcp 1.x
		from mcp.server.fastmcp import FastMCP

	srv = FastMCP(
		"istoc-seo-helper",
		instructions="İstoç CMS + SEO Helper. Yazma araçları yalnız TASLAK üretir; yayın insan onayı ister.",
	)

	@srv.tool()
	def page_create(
		title: str,
		route: str,
		lang: str = "tr",
		meta_description: str = "",
		blocks: list | None = None,
		store: str | None = None,
	) -> dict:
		"""Yeni CMS sayfası taslağı oluşturur (Builder Page). Yayınlamaz."""
		return call(
			"page_create",
			title=title,
			route=route,
			lang=lang,
			meta_description=meta_description,
			blocks=blocks,
			store=store,
		)

	@srv.tool()
	def page_update(builder_page: str, changes: dict, store: str | None = None) -> dict:
		"""Mevcut sayfa için değişiklik taslağı (title, meta_description, canonical_url, route)."""
		return call("page_update", builder_page=builder_page, changes=changes, store=store)

	@srv.tool()
	def block_add(
		builder_page: str, block: dict, position: int | None = None, store: str | None = None
	) -> dict:
		"""Sayfaya Builder bloğu ekleme taslağı (script içeremez)."""
		return call("block_add", builder_page=builder_page, block=block, position=position, store=store)

	@srv.tool()
	def metadata_suggest(
		builder_page: str | None = None,
		title: str = "",
		content: str = "",
		lang: str = "tr",
		store: str | None = None,
	) -> dict:
		"""OpenAI ile SEO başlık/meta açıklama önerisi → taslak + deterministik doğrulama sonucu."""
		return call(
			"metadata_suggest",
			builder_page=builder_page,
			title=title,
			content=content,
			lang=lang,
			store=store,
		)

	@srv.tool()
	def translation_draft(
		builder_page: str, target_lang: str, fields: list | None = None, store: str | None = None
	) -> dict:
		"""Sayfa metadata çeviri taslağı (tr/en/ar/ru)."""
		return call(
			"translation_draft",
			builder_page=builder_page,
			target_lang=target_lang,
			fields=fields,
			store=store,
		)

	@srv.tool()
	def seo_audit_run(routes: list | None = None, store: str | None = None) -> dict:
		"""SEO denetimi başlatır (ayrı kuyruk); crawl_run kimliği döner."""
		return call("seo_audit_run", routes=routes, store=store)

	@srv.tool()
	def result_read(crawl_run: str | None = None, draft: str | None = None, store: str | None = None) -> dict:
		"""Denetim sonucu ya da taslak durumunu okur."""
		return call("result_read", crawl_run=crawl_run, draft=draft, store=store)

	return srv


TOOLS = (
	"page_create",
	"page_update",
	"block_add",
	"metadata_suggest",
	"translation_draft",
	"seo_audit_run",
	"result_read",
)


if __name__ == "__main__":
	if not KEY:
		raise SystemExit("SHC_MCP_KEY tanımlı değil")
	build_server().run(transport=os.environ.get("SHC_TRANSPORT", "stdio"))
	print(json.dumps({"tools": TOOLS}))

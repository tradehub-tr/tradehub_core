"""Ortak test ortamı — mağaza/kullanıcı/Builder Page fixture'ları (MOGEM-665 `mogem665_ortak` deseni)."""

from __future__ import annotations

import json
import secrets
from contextlib import contextmanager

import frappe
from frappe.utils import now_datetime

BASLIK = "SEO Helper test sayfası — kategori ve öne çıkan özelliğiyle betimlenmiş başlık"
ACIKLAMA = "Toptan satış için uygun test sayfası; malzeme, ölçü ve kullanım alanı bilgileri burada ayrıntılı verilir."


class ShcOrtam:
	def setUp(self):
		super().setUp()
		# Yerel/test ortamı prod dışıdır (robots_generator.resolve_env → noindex,nofollow). Politika
		# kararlarını sınamak için ortamı prod kabul ederiz; prod-dışı davranış test_policy'de ayrıca sınanır.
		from unittest.mock import patch

		p = patch(
			"tradehub_core.seo_helper.adapters.tradehub.robots.indexing_allowed_for_env", return_value=True
		)
		p.start()
		self.addCleanup(p.stop)

	def _sonek(self) -> str:
		if not getattr(self, "_shc_sonek", None):
			self._shc_sonek = secrets.token_hex(3)
		return self._shc_sonek

	def _drop(self, doctype: str, name: str) -> None:
		try:
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, delete_permanently=True)
			frappe.db.commit()
		except Exception:  # noqa: BLE001
			frappe.db.rollback()

	def _user(self, tag: str, roles=("Seller", "Marketplace Seller")) -> str:
		email = f"shc-{tag}-{self._sonek()}@test.local"
		doc = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": f"SHC {tag}",
				"send_welcome_email": 0,
				"enabled": 1,
				"roles": [{"role": r} for r in roles if frappe.db.exists("Role", r)],
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("User", doc.name))
		from tradehub_core.utils.tenant import clear_seller_cache_for_user

		self.addCleanup(lambda: clear_seller_cache_for_user(doc.name))
		return doc.name

	def _seller(self, tag: str) -> tuple[str, str]:
		user = self._user(tag)
		seller = frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_code": f"SHC{tag.upper()}{self._sonek()}",
				"seller_name": f"SHC {tag}",
				"user": user,
				"email": user,
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Admin Seller Profile", seller.name))
		return seller.name, user

	def _builder_page(self, tag: str, published: int = 1, **alanlar) -> str:
		frappe.set_user("Administrator")
		veri = {
			"doctype": "Builder Page",
			"page_title": BASLIK,
			"route": f"shc-{tag}-{self._sonek()}",
			"published": published,
			"meta_description": ACIKLAMA,
			"language": "tr",
			"blocks": json.dumps([{"element": "div", "children": [{"element": "h1", "innerHTML": BASLIK}]}]),
		}
		veri.update(alanlar)
		doc = frappe.get_doc(veri)
		doc.flags.ignore_permissions = True
		doc.insert()
		frappe.db.commit()
		self.addCleanup(lambda: self._drop_builder_page(doc.name))
		return doc.name

	def _drop_builder_page(self, name: str) -> None:
		for p in frappe.get_all("SEO Page", filters={"builder_page": name}, pluck="name"):
			frappe.db.delete("SEO Audit Finding", {"page": p})
			frappe.db.delete("SEO Sync Job", {"payload": ["like", f'%"{p}"%']})
			self._drop("SEO Page", p)
		self._drop("Builder Page", name)

	def _seo_page(self, tag: str, **alanlar) -> str:
		veri = {
			"doctype": "SEO Page",
			"lang": "tr",
			"route": f"/shc-p-{tag}-{self._sonek()}",
			"title": BASLIK,
			"meta_description": ACIKLAMA,
			"publish_state": "published",
			"source": "static",
		}
		veri.update(alanlar)
		doc = frappe.get_doc(veri)
		doc.flags.ignore_permissions = True
		doc.insert()
		frappe.db.commit()
		self.addCleanup(lambda: frappe.db.delete("SEO Audit Finding", {"page": doc.name}))
		self.addCleanup(lambda: frappe.db.delete("SEO Sync Job", {"payload": ["like", f'%"{doc.name}"%']}))
		self.addCleanup(lambda: self._drop("SEO Page", doc.name))
		return doc.name

	def _mcp_client(
		self,
		tag: str,
		store: str | None = None,
		scopes: str = "page:read,page:draft,metadata:suggest,translation:draft,audit:run,audit:read",
		budget: int = 0,
	) -> dict:
		from tradehub_core.seo_helper.mcp.auth import generate_key

		key, prefix, h = generate_key()
		doc = frappe.get_doc(
			{
				"doctype": "MCP Client",
				"client_name": f"shc-{tag}-{self._sonek()}",
				"role": "seo_agent",
				"scopes": scopes,
				"store": store,
				"enabled": 1,
				"api_key_prefix": prefix,
				"api_key_hash": h,
				"key_rotated_at": now_datetime(),
				"monthly_token_budget": budget,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: frappe.db.delete("MCP Tool Call", {"client": doc.name}))
		self.addCleanup(lambda: frappe.db.delete("MCP Draft", {"client": doc.name}))
		self.addCleanup(lambda: self._drop("MCP Client", doc.name))
		return {"name": doc.name, "key": key}

	@contextmanager
	def mcp_istek(
		self, key: str | None, path: str = "/api/method/tradehub_core.seo_helper.mcp.api.page_create"
	):
		class _Req:
			def __init__(self):
				self.headers = {"X-MCP-Key": key} if key else {}
				self.path = path
				self.method = "POST"
				self.host = "tradehub.localhost"
				self.url = "http://tradehub.localhost" + path

		onceki_user, onceki_req = frappe.session.user, getattr(frappe.local, "request", None)
		onceki_client = getattr(frappe.local, "mcp_client", None)
		frappe.set_user("Guest")
		frappe.local.request = _Req()
		frappe.local.mcp_client = None
		try:
			yield
		finally:
			frappe.local.request = onceki_req
			frappe.local.mcp_client = onceki_client
			frappe.set_user(onceki_user)

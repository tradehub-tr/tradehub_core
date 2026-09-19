"""MOGEM-665 · Ürün API'si testlerinin ortak ortamı.

Her test kendi mağazasını kurar (User + Admin Seller Profile + aktif Store
Subscription) ve bitince siler; gerçek veriye dokunmaz. Ürün kaydı "kullanıcı
gibi" değil, Administrator olarak açılır (kota kapısı System Manager'ı atlar) —
API yolunun kendisi ise mağaza sahibi olarak koşar, çünkü test ettiğimiz şey bu.

Bearer başlığı `frappe.local.request` sahtesiyle verilir
(`test_rate_limit_guest_bucket.py` deseni); uç noktalar gerçek HTTP'de nasıl
okuyorsa burada da öyle okur.
"""

from __future__ import annotations

import secrets
from contextlib import contextmanager

import frappe
from frappe.utils import now_datetime

from tradehub_core.utils.tenant import clear_seller_cache_for_user

VARSAYILAN_PLAN = "enterprise"


class _FakeRequest:
	"""`frappe.local.request` yerine geçer: başlıklar + `get_url()`'ün okuduğu `host`."""

	def __init__(self, headers: dict[str, str], method: str = "POST"):
		self.headers = headers
		self.method = method
		self.host = "tradehub.localhost"
		self.url = "http://tradehub.localhost/api/method/tradehub_core.api.v1.catalog.upsert_products"
		self.path = "/api/method/tradehub_core.api.v1.catalog.upsert_products"
		self.remote_addr = "127.0.0.1"


class Mogem665Ortam:
	"""FrappeTestCase ile karıştırılır (mixin). `self.addCleanup` gerektirir."""

	def _sonek(self) -> str:
		if not getattr(self, "_mogem665_sonek", None):
			self._mogem665_sonek = secrets.token_hex(3)
		return self._mogem665_sonek

	def _drop(self, doctype: str, name: str) -> None:
		try:
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, delete_permanently=True)
			frappe.db.commit()
		except Exception:  # noqa: BLE001 — temizlik başka temizliği engellemesin
			frappe.db.rollback()

	def _user(self, tag: str) -> str:
		email = f"m665-{tag}-{self._sonek()}@test.local"
		doc = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": f"M665 {tag}",
				"send_welcome_email": 0,
				"enabled": 1,
				# Satıcı rolleri: panel/`get_list` yetkisi "Marketplace Seller" üzerinden.
				"roles": [
					{"role": r} for r in ("Seller", "Marketplace Seller") if frappe.db.exists("Role", r)
				],
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("User", doc.name))
		self.addCleanup(lambda: clear_seller_cache_for_user(doc.name))
		return doc.name

	def _seller(self, tag: str, plan: str = VARSAYILAN_PLAN, kota: dict | None = None) -> tuple[str, str]:
		"""(seller_profile adı, sahip kullanıcı e-postası) — aktif abonelikle.

		`kota`: Store Subscription `custom_quota_overrides` (örn. {"quota.max_products": 1}).
		"""
		import json

		user = self._user(tag)
		seller = frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_code": f"M665{tag.upper()}{self._sonek()}",
				"seller_name": f"M665 {tag} {self._sonek()}",
				"user": user,
				"email": user,
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		sub = frappe.get_doc(
			{
				"doctype": "Store Subscription",
				"store": seller.name,
				"plan": plan,
				"status": "active",
				"started_at": now_datetime(),
				"custom_quota_overrides": json.dumps(kota) if kota else None,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		# get_active_subscription 10 sn'lik negatif önbellek tutuyor — temizle.
		for k in ("subscription", "capabilities", "quotas"):
			frappe.cache().delete_value(f"tradehub:entitlement:{k}:{seller.name}")
		self.addCleanup(lambda: self._drop("Store Subscription", sub.name))
		self.addCleanup(lambda: self._drop("Admin Seller Profile", seller.name))
		return seller.name, user

	def _listing(self, seller: str, sku: str | None = None, **alanlar) -> str:
		"""Administrator olarak ürün aç (kota kapısı atlanır). Döner: Listing.name."""
		veri = {
			"doctype": "Listing",
			"title": alanlar.pop("title", f"M665 ürün {sku or self._sonek()}"),
			"seller_profile": seller,
			"seller_sku": sku,
			"currency": "TRY",
			"base_price": 100,
			"selling_price": 90,
			"stock_qty": 10,
			"track_inventory": 1,
			"status": "Active",
		}
		veri.update(alanlar)
		doc = frappe.get_doc(veri)
		doc.flags.from_admin = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Listing", doc.name))
		return doc.name

	def _api_app(
		self, seller: str | None, scopes: tuple[str, ...] = ("catalog:write", "stock:write", "catalog:read")
	):
		"""Mağazaya bağlı API Application; (name, client_id, client_secret) döner."""
		client_id = f"m665-{self._sonek()}-{secrets.token_hex(2)}"
		secret = secrets.token_urlsafe(16)
		doc = frappe.get_doc(
			{
				"doctype": "API Application",
				"app_name": f"M665 app {client_id}",
				"developer_email": "m665@test.local",
				"is_active": 1,
				"client_id": client_id,
				"client_secret": secret,
				"rate_limit_tier": "enterprise",
				"seller_profile": seller,
				"scopes": [{"scope": s} for s in scopes],
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("API Application", doc.name))
		return doc.name, client_id, secret

	def _token(self, client_id: str, secret: str) -> str:
		from tradehub_core.api.rate_limit import reset_bucket
		from tradehub_core.api.v1.public_api import token

		with self.misafir_istek({}):
			# Jeton ucu IP başına 30/dk; testler tek IP'den (127.0.0.1) yüzlerce kez
			# geçer — kovayı her çağrıda sıfırla, hız sınırı testi ayrı sınanır.
			reset_bucket("oauth_token")  # kimlik dekoratörle aynı yoldan (_bucket_identity) çözülür
			return token("client_credentials", client_id, secret)["access_token"]

	@contextmanager
	def misafir_istek(self, headers: dict[str, str]):
		"""Guest oturumu + sahte istek başlıkları; çıkışta her şey eski hâline."""
		onceki_user = frappe.session.user
		onceki_req = getattr(frappe.local, "request", None)
		onceki_ip = getattr(frappe.local, "request_ip", None)
		frappe.set_user("Guest")
		frappe.local.request = _FakeRequest(headers)
		frappe.local.request_ip = "127.0.0.1"
		try:
			yield
		finally:
			frappe.local.request = onceki_req
			frappe.local.request_ip = onceki_ip
			frappe.set_user(onceki_user)

	@contextmanager
	def bearer(self, access_token: str):
		with self.misafir_istek({"Authorization": f"Bearer {access_token}"}):
			yield

	def _api_baglantisi(
		self,
		tag: str = "a",
		scopes=("catalog:write", "stock:write", "catalog:read"),
		plan: str = VARSAYILAN_PLAN,
		kota: dict | None = None,
	):
		"""Mağaza + uygulama + jeton — API testlerinin tek satırlık kurulumu."""
		seller, user = self._seller(tag, plan=plan, kota=kota)
		app, cid, sec = self._api_app(seller, scopes)
		return {
			"seller": seller,
			"user": user,
			"app": app,
			"client_id": cid,
			"secret": sec,
			"token": self._token(cid, sec),
		}

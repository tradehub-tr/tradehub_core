"""Tenant-sınırlı medya kategorisi (MOGEM-579).

Klasör, etiket ve kategori birbirinin eş adı değildir:

* ``Media Folder Item`` bir dosyanın mağaza içindeki tek fiziksel düzen
  konumudur (1 dosya → en çok 1 klasör).
* ``File.th_media_tags`` geriye uyumlu, küçük serbest etiket kümesidir.
* ``Media Category Assignment`` iş anlamını taşır ve çoktan-çoğa ilişki
  kurar (1 dosya ↔ N kategori). Atamanın manuel mi otomatik mi olduğu bağ
  kaydında tutulur; kategori tanımına gömülmez.

Kategori kimliği hash'tir. Kullanıcının verdiği adın docname yapılmaması hem
yeniden adlandırmayı güvenli kılar hem başka tenant adlarını tahmin yoluyla
keşfetmeyi önler.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

CATEGORY_TYPES: frozenset[str] = frozenset(
	{"content_type", "usage_purpose", "tenant", "product", "campaign", "workflow", "custom"}
)
MAX_DEPTH: int = 5
MAX_NAME_LEN: int = 100
_ADMIN_ROLES: tuple[str, ...] = ("System Manager", "Marketplace Admin")


class MediaCategory(Document):
	def validate(self) -> None:
		self.parent_category = (self.parent_category or "").strip()
		self.category_type = (self.category_type or "custom").strip().lower()
		self.description = (self.description or "").strip()[:500]
		self.color = (self.color or "").strip()
		self._validate_immutable_store()
		self._clean_name()
		self._validate_type()
		self._validate_parent_and_depth()
		self._validate_unique()

	def _validate_immutable_store(self) -> None:
		if self.is_new():
			return
		previous = frappe.db.get_value("Media Category", self.name, "store")
		if previous and previous != self.store:
			frappe.throw(_("Kategori mağazası sonradan değiştirilemez."))

	def _clean_name(self) -> None:
		name = (self.category_name or "").strip()
		if not name:
			frappe.throw(_("Kategori adı boş olamaz."))
		if len(name) > MAX_NAME_LEN:
			frappe.throw(_("Kategori adı en çok {0} karakter olabilir.").format(MAX_NAME_LEN))
		self.category_name = name

	def _validate_type(self) -> None:
		if self.category_type not in CATEGORY_TYPES:
			frappe.throw(_("Geçersiz medya kategori türü."))

	def _validate_parent_and_depth(self) -> None:
		seen: set[str] = set()
		parent = self.parent_category
		depth = 1
		while parent:
			if parent == self.name or parent in seen:
				frappe.throw(_("Kategori kendi alt kategorisinin altına taşınamaz."))
			seen.add(parent)
			row = frappe.db.get_value(
				"Media Category", parent, ["store", "parent_category"], as_dict=True
			)
			if not row or row.store != self.store:
				# Başka tenant kategorisinin varlığını doğrulama.
				frappe.throw(_("Üst kategori bulunamadı."), frappe.DoesNotExistError)
			parent = row.parent_category
			depth += 1
			if depth > MAX_DEPTH:
				frappe.throw(
					_("Kategoriler en çok {0} seviye derinlikte olabilir.").format(MAX_DEPTH)
				)

		if not self.is_new():
			subtree_depth = self._subtree_depth(self.name, {self.name})
			if depth + subtree_depth - 1 > MAX_DEPTH:
				frappe.throw(
					_("Kategoriler en çok {0} seviye derinlikte olabilir.").format(MAX_DEPTH)
				)

	def _subtree_depth(self, root: str, seen: set[str]) -> int:
		children = frappe.get_all(
			"Media Category", filters={"parent_category": root}, pluck="name"
		)
		if not children:
			return 1
		deepest = 1
		for child in children:
			if child in seen:
				continue
			deepest = max(deepest, 1 + self._subtree_depth(child, seen | {child}))
		return deepest

	def _validate_unique(self) -> None:
		filters = {
			"store": self.store,
			"parent_category": self.parent_category or "",
			"category_name": self.category_name,
			"name": ["!=", self.name],
		}
		if frappe.db.exists("Media Category", filters):
			frappe.throw(
				_("Bu düzeyde '{0}' adında bir kategori zaten var.").format(self.category_name),
				frappe.DuplicateEntryError,
			)

	def on_trash(self) -> None:
		if frappe.db.exists("Media Category", {"parent_category": self.name}):
			frappe.throw(_("Kategorinin alt kategorileri var. Önce onları silin veya taşıyın."))
		if frappe.db.exists("Media Category Assignment", {"category": self.name}):
			frappe.throw(_("Kategori medyalarda kullanılıyor. Önce atamaları kaldırın."))


def _store_of(user: str | None) -> str | None:
	from tradehub_core.media import ownership

	return ownership.store_of(user)


def get_permission_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if not user or user == "Guest":
		return "1=0"
	if any(role in frappe.get_roles(user) for role in _ADMIN_ROLES):
		return ""
	store = _store_of(user)
	if not store:
		return "1=0"
	return f"`tabMedia Category`.`store` = {frappe.db.escape(store)}"


def has_permission(doc, user: str | None = None, permission_type: str = "") -> bool:
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False
	if any(role in frappe.get_roles(user) for role in _ADMIN_ROLES):
		return True
	store = _store_of(user)
	return bool(store) and getattr(doc, "store", None) == store

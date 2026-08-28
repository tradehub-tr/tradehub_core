"""Medya dosyası ↔ kategori çoktan-çoğa bağı (MOGEM-579)."""

from __future__ import annotations

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document

ASSIGNMENT_SOURCES: frozenset[str] = frozenset({"manual", "suggestion", "rule", "ai", "system"})
_ADMIN_ROLES: tuple[str, ...] = ("System Manager", "Marketplace Admin")


class MediaCategoryAssignment(Document):
	def validate(self) -> None:
		from tradehub_core.media import ownership

		self.file_url = (self.file_url or "").split("?", 1)[0].strip()
		self.file_url_hash = hashlib.sha256(self.file_url.encode()).hexdigest()
		self.assignment_source = (self.assignment_source or "manual").strip().lower()
		self.evidence = (self.evidence or "").strip()[:500]
		if not self.file_url:
			frappe.throw(_("Dosya adresi boş olamaz."))
		if self.assignment_source not in ASSIGNMENT_SOURCES:
			frappe.throw(_("Geçersiz kategori atama kaynağı."))

		category_store = frappe.db.get_value("Media Category", self.category, "store")
		if not category_store or category_store != self.store:
			# Başka tenant kategorisinin varlığını doğrulama.
			frappe.throw(_("Kategori bulunamadı."), frappe.DoesNotExistError)
		if not ownership.owns(self.store, self.file_url):
			frappe.throw(_("Dosya bulunamadı."), frappe.DoesNotExistError)

		try:
			self.confidence = float(self.confidence if self.confidence is not None else 1)
		except (TypeError, ValueError):
			frappe.throw(_("Kategori güven değeri sayı olmalıdır."))
		if not 0 <= self.confidence <= 1:
			frappe.throw(_("Kategori güven değeri 0 ile 1 arasında olmalıdır."))
		if self.assignment_source == "manual":
			self.confidence = 1
		if not self.assigned_by:
			self.assigned_by = frappe.session.user

		if frappe.db.exists(
			"Media Category Assignment",
			{
				"store": self.store,
				"file_url": self.file_url,
				"category": self.category,
				"name": ["!=", self.name],
			},
		):
			frappe.throw(_("Kategori bu medyaya zaten atanmış."), frappe.DuplicateEntryError)


def get_permission_query_conditions(user: str | None = None) -> str:
	from tradehub_core.media import ownership

	user = user or frappe.session.user
	if not user or user == "Guest":
		return "1=0"
	if any(role in frappe.get_roles(user) for role in _ADMIN_ROLES):
		return ""
	store = ownership.store_of(user)
	if not store:
		return "1=0"
	return f"`tabMedia Category Assignment`.`store` = {frappe.db.escape(store)}"


def has_permission(doc, user: str | None = None, permission_type: str = "") -> bool:
	from tradehub_core.media import ownership

	user = user or frappe.session.user
	if not user or user == "Guest":
		return False
	if any(role in frappe.get_roles(user) for role in _ADMIN_ROLES):
		return True
	store = ownership.store_of(user)
	return bool(store) and getattr(doc, "store", None) == store

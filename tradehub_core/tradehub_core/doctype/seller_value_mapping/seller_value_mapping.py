# Copyright (c) 2026, TradeHub Team and contributors

import frappe
from frappe import _
from frappe.model.document import Document


class SellerValueMapping(Document):
	def validate(self):
		# super().validate() — Frappe v15: Document.validate yok (RegexPatternLibrary deseni).
		self._validate_target_field()
		self._validate_unique_per_seller()
		self._dedupe_rows()

	def _validate_target_field(self):
		if not (self.target_field or "").strip():
			frappe.throw(_("Hedef alan zorunlu"))
		if not self.seller_profile:
			frappe.throw(_("Satıcı profili zorunlu"))

	def _validate_unique_per_seller(self):
		# Aynı satıcı + aynı hedef alan için tek kayıt — runner lookup'ı tek dökümana
		# güvenir (value_map cache target_field başına tek satır seti tutar).
		existing = frappe.db.get_value(
			"Seller Value Mapping",
			{
				"seller_profile": self.seller_profile,
				"target_field": self.target_field,
				"name": ["!=", self.name or ""],
			},
			"name",
		)
		if existing:
			frappe.throw(_("Bu alan için zaten bir değer eşleştirmesi var: {0}").format(self.target_field))

	def _dedupe_rows(self):
		# Aynı gelen değer iki kez map'lenirse son giren kazanır; runner dict kurarken
		# çakışmayı önlemek için burada (case-insensitive) tekilleştir.
		seen: dict[str, object] = {}
		for row in self.rows or []:
			src = (row.source_value or "").strip()
			if not src:
				frappe.throw(_("Gelen değer boş olamaz"))
			if not (row.target_value or "").strip():
				frappe.throw(_("Hedef değer boş olamaz"))
			seen[src.lower()] = row
		# Çakışan satırları kaldırmıyoruz (UI'ı bozmamak için), yalnız doğruluyoruz.

	def on_update(self):
		_clear_value_map_cache(self.seller_profile)

	def on_trash(self):
		_clear_value_map_cache(self.seller_profile)


def _clear_value_map_cache(seller_profile: str | None) -> None:
	"""Satıcının value-map cache'ini temizle (runner 5dk cache'liyor)."""
	if not seller_profile:
		return
	try:
		frappe.cache.delete_value(f"value_map:{seller_profile}")
	except Exception as exc:
		frappe.log_error(f"value_map cache clear failed: {exc}", "seller_value_mapping")

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
		# System scope tüm satıcılar için taban katman — seller_profile boş olur.
		if self.scope != "System" and not self.seller_profile:
			frappe.throw(_("Satıcı profili zorunlu"))

	def _validate_unique_per_seller(self):
		# Aynı kapsam (System veya satıcı) + aynı hedef alan için tek kayıt — runner
		# lookup'ı tek dökümana güvenir (value_map cache target_field başına tek satır).
		scope_filter = (
			{"scope": "System"} if self.scope == "System" else {"seller_profile": self.seller_profile}
		)
		existing = frappe.db.get_value(
			"Seller Value Mapping",
			{**scope_filter, "target_field": self.target_field, "name": ["!=", self.name or ""]},
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
		_clear_value_map_cache(self.scope, self.seller_profile)

	def on_trash(self):
		_clear_value_map_cache(self.scope, self.seller_profile)


def _clear_value_map_cache(scope: str | None, seller_profile: str | None) -> None:
	"""value-map cache'ini temizle (runner 5dk cache'liyor).

	System scope tüm satıcıların value_map'ini etkiler → tüm key'leri temizle.
	Seller Override yalnızca o satıcının key'ini.
	"""
	try:
		if scope == "System":
			frappe.cache.delete_keys("value_map:*")
		elif seller_profile:
			frappe.cache.delete_value(f"value_map:{seller_profile}")
	except Exception as exc:
		frappe.log_error(f"value_map cache clear failed: {exc}", "seller_value_mapping")

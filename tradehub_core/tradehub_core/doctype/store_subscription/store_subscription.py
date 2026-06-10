# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Store Subscription DocType controller.

Bir Admin Seller Profile (= store) ↔ Subscription Plan ilişkisini ve dönem
bilgisini tutar. Bir mağaza için yalnızca tek aktif Store Subscription olabilir.

Status state machine:
  trial → active | past_due | expired | canceled | suspended
  active → past_due | expired | canceled | suspended
  past_due → active | expired | canceled | suspended
  suspended → active | canceled
  expired → active | canceled  (yeniden abonelik / ödeme ile reaktive)
  canceled → (terminal, sadece yeniden subscription oluşturulabilir)

`expired`: deneme süresi doldu, ödeme yok → panel kilitli (paywall). Veri korunur;
ödeme/yeniden abonelikle `active`e döner (bkz. subscription.upgrade_subscription_plan).

Detay: docs/yetki/03-doctype-sablonlari.md §3
"""

import json
from datetime import datetime

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

# İzin verilen status geçişleri
_VALID_TRANSITIONS: dict[str, set[str]] = {
	"trial": {"active", "past_due", "expired", "canceled", "suspended"},
	"active": {"past_due", "expired", "canceled", "suspended"},
	"past_due": {"active", "expired", "canceled", "suspended"},
	"suspended": {"active", "canceled"},
	"expired": {"active", "canceled"},  # ödeme/yeniden abonelik ile reaktive
	"canceled": set(),  # terminal
}


class StoreSubscription(Document):
	def validate(self) -> None:
		self._validate_status_transition()
		self._validate_period_consistency()
		self._validate_unique_active_per_store()
		self._validate_overrides_json()
		self._track_plan_change()

	def before_insert(self) -> None:
		"""Yeni subscription için started_at default = now."""
		if not self.started_at:
			self.started_at = now_datetime()

	def _validate_status_transition(self) -> None:
		"""Status geçişi state machine'e uygun olmalı."""
		if not self.is_new() and self.name:
			# Eski status'u DB'den al
			old_status = frappe.db.get_value("Store Subscription", self.name, "status")
			if old_status and old_status != self.status:
				allowed = _VALID_TRANSITIONS.get(old_status, set())
				if self.status not in allowed:
					frappe.throw(
						_("Geçersiz status geçişi: {0} → {1}. İzin verilen: {2}").format(
							old_status, self.status, ", ".join(sorted(allowed)) or "(yok, terminal)"
						)
					)

	def _validate_period_consistency(self) -> None:
		"""Dönem tarihleri tutarlı olmalı."""
		if self.current_period_start and self.current_period_end:
			start = self.current_period_start
			end = self.current_period_end
			# Frappe Datetime field bazen string döner — normalize et
			if isinstance(start, str):
				start = (
					datetime.fromisoformat(start.replace("Z", "+00:00"))
					if "T" in start
					else datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
				)
			if isinstance(end, str):
				end = (
					datetime.fromisoformat(end.replace("Z", "+00:00"))
					if "T" in end
					else datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
				)
			if end <= start:
				frappe.throw(_("Current Period End, Period Start'tan sonra olmalı."))

		if self.status == "canceled" and not self.canceled_at:
			self.canceled_at = now_datetime()

	def _validate_unique_active_per_store(self) -> None:
		"""Bir mağaza için yalnızca tek non-canceled subscription olabilir."""
		if self.status == "canceled":
			return

		filters = {
			"store": self.store,
			"status": ["!=", "canceled"],
		}
		if self.name and not self.is_new():
			filters["name"] = ["!=", self.name]

		existing = frappe.db.exists("Store Subscription", filters)
		if existing:
			frappe.throw(
				_(
					"Mağaza '{0}' için zaten aktif bir Store Subscription var ({1}). "
					"Yeni plan için önce mevcut subscription'ı 'canceled' yapın."
				).format(self.store, existing)
			)

	def _validate_overrides_json(self) -> None:
		"""custom_quota_overrides ve custom_capability_overrides geçerli JSON olmalı.
		Override key'leri plan'ın mevcut key'leri ile sınırlıdır (privilege escalation önlemi)."""
		for fieldname in ("custom_quota_overrides", "custom_capability_overrides"):
			val = self.get(fieldname)
			if not val:
				continue
			parsed = val if isinstance(val, dict) else None
			if parsed is None:
				try:
					parsed = json.loads(val)
					if not isinstance(parsed, dict):
						frappe.throw(_("{0} JSON nesnesi (dict) olmalı.").format(fieldname))
				except (json.JSONDecodeError, TypeError) as e:
					frappe.throw(_("{0} geçerli JSON değil: {1}").format(fieldname, str(e)))
					return

			# Override key'leri plan'ın key'leri ile sınırla
			if self.plan and parsed:
				plan = frappe.get_cached_doc("Subscription Plan", self.plan)
				if fieldname == "custom_quota_overrides":
					allowed_keys = set(plan.get_quota_limits().keys())
				else:
					allowed_keys = set(plan.get_capability_flags().keys())
				unknown = set(parsed.keys()) - allowed_keys
				if unknown:
					frappe.throw(
						_("{0}: Geçersiz key'ler ({1}). İzin verilen: {2}").format(
							fieldname, ", ".join(sorted(unknown)), ", ".join(sorted(allowed_keys)) or "(boş)"
						)
					)

	def _track_plan_change(self) -> None:
		"""Plan değişikliğinde previous_plan alanını güncelle."""
		if self.is_new() or not self.name:
			return
		old_plan = frappe.db.get_value("Store Subscription", self.name, "plan")
		if old_plan and old_plan != self.plan:
			self.previous_plan = old_plan

	# --- Public API ---

	def get_effective_capability_flags(self) -> dict:
		"""Plan capability_flags + custom overrides birleştirilmiş hali."""
		plan = frappe.get_cached_doc("Subscription Plan", self.plan)
		flags = dict(plan.get_capability_flags())
		overrides = self._parse_overrides("custom_capability_overrides")
		if overrides:
			flags.update(overrides)
		return flags

	def get_effective_quota_limits(self) -> dict:
		"""Plan quota_limits + custom overrides birleştirilmiş hali."""
		plan = frappe.get_cached_doc("Subscription Plan", self.plan)
		quotas = dict(plan.get_quota_limits())
		overrides = self._parse_overrides("custom_quota_overrides")
		if overrides:
			quotas.update(overrides)
		return quotas

	def _parse_overrides(self, fieldname: str) -> dict:
		"""Override JSON field'ını dict olarak döner."""
		val = self.get(fieldname)
		if not val:
			return {}
		if isinstance(val, dict):
			return val
		try:
			return json.loads(val)
		except (json.JSONDecodeError, TypeError):
			return {}

	def is_active_for_use(self) -> bool:
		"""Subscription şu an kullanılabilir mi (trial veya active)?"""
		return self.status in ("trial", "active")

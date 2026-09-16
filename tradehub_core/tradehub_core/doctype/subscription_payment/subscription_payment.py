# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Subscription Payment — havale/EFT tabanlı abonelik ödeme talebi.

Ödeme gateway'i yok; satıcı paket seçince `pending` bir kayıt oluşur, banka
bilgileri + referans kodu gösterilir. Satıcı havale yapar, admin panelden
`confirmed` yapınca abonelik aktive edilir (bkz. api/v1/subscription_payment).

Status state machine (M3 — finansal bütünlük):
  pending → confirmed | rejected | canceled
  confirmed / rejected / canceled → TERMİNAL (hiçbir geçiş yok)

`canceled` şemada tanımlı bir Desk seçeneği; şu an hiçbir sistem akışı yazmıyor
(tarama 2026-09-16) ama seçenek durduğu sürece pending'den iptal edilebilir ve
terminal kalır. Ret/iptal sonrası yeni talep `create_bank_transfer_request` ile
YENİ kayıt olarak açılır — terminal kayıt asla geri açılmaz (confirmed'ı
pending'e çekip ikinci kez onaylatmak tek havaleye iki dönem yazardı).

Terminal kayıtta finansal alanlar (amount, currency, plan, billing_cycle,
reference_code, store) DONDURULUR. `rejection_reason` ve `notes` dondurma
dışıdır: finansal etkisi olmayan açıklama alanları — admin ret gerekçesini
sonradan düzeltebilmeli/netleştirebilmeli (track_changes=1 izi zaten tutar).

Not: identity.py hesap silme akışı pending talepleri `frappe.db.set_value` ile
'rejected' yapar; o yol validate'i bypass eder ama geçiş zaten tabloda tanımlı,
bu controller o akışı kırmaz.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

# İzin verilen status geçişleri (store_subscription._VALID_TRANSITIONS deseni).
_VALID_TRANSITIONS: dict[str, set[str]] = {
	"pending": {"confirmed", "rejected", "canceled"},
	"confirmed": set(),  # terminal — M3: ikinci onay/iki dönem riski
	"rejected": set(),  # terminal — yeni talep = yeni kayıt
	"canceled": set(),  # terminal — Desk seçeneği; sistem akışı yazmıyor
}

_TERMINAL_STATUSES: frozenset[str] = frozenset({"confirmed", "rejected", "canceled"})

# Terminal kayıtta değiştirilemeyen finansal/eşleştirme alanları.
# rejection_reason + notes bilinçli olarak dışarıda (modül docstring'i).
_FROZEN_FIELDS: tuple[str, ...] = (
	"amount",
	"currency",
	"plan",
	"billing_cycle",
	"reference_code",
	"store",
)


class SubscriptionPayment(Document):
	def validate(self) -> None:
		# Frappe v15'te Document tabanı validate tanımlamaz — guard'lı süper çağrısı:
		# ileride araya validate'li bir mixin/base girerse zincir kopmasın (kural 20).
		parent_validate = getattr(super(), "validate", None)
		if callable(parent_validate):
			parent_validate()
		old_status = self._get_db_status()
		self._validate_status_transition(old_status)
		self._validate_terminal_freeze(old_status)

	def before_insert(self) -> None:
		if not self.requested_at:
			self.requested_at = now_datetime()
		if not self.reference_code:
			self.reference_code = self._generate_reference_code()

	def _get_db_status(self) -> str | None:
		"""Kayıtlı (DB'deki) status — yeni kayıtta None."""
		if self.is_new() or not self.name:
			return None
		return frappe.db.get_value("Subscription Payment", self.name, "status")

	def _validate_status_transition(self, old_status: str | None) -> None:
		"""Status geçişi state machine'e uygun olmalı (yeni kayıt serbest —
		backfill/test fixture'ları doğrudan confirmed insert eder)."""
		if not old_status or old_status == self.status:
			return
		allowed = _VALID_TRANSITIONS.get(old_status, set())
		if self.status not in allowed:
			frappe.throw(
				_("Geçersiz ödeme durumu geçişi: {0} → {1}. İzin verilen: {2}").format(
					old_status, self.status, ", ".join(sorted(allowed)) or _("(yok — terminal durum)")
				)
			)

	def _validate_terminal_freeze(self, old_status: str | None) -> None:
		"""Terminal (confirmed/rejected/canceled) kayıtta finansal alanlar donuk.

		Dondurma kaydın ESKİ (DB'deki) durumuna bakar: pending→confirmed save'inde
		alanlar hâlâ serbesttir (confirm akışı confirmed_at/confirmed_by yazar),
		bir SONRAKİ save'den itibaren kilitlenir. pending kayıtta tamamen serbest —
		create_bank_transfer_request bekleyen talebin tutarını tazeler (AC-5).
		"""
		if old_status not in _TERMINAL_STATUSES:
			return
		before = self.get_doc_before_save()
		for fieldname in _FROZEN_FIELDS:
			if not self.has_value_changed(fieldname):
				continue
			# Float cast farkı (örn. Desk'ten "7188" string gelmesi) gerçek değişim
			# değil — amount için sayısal karşılaştırmayla yanlış pozitifi ele.
			if fieldname == "amount" and before is not None and flt(before.get("amount")) == flt(self.amount):
				continue
			frappe.throw(
				_(
					"Bu ödeme kaydı '{0}' durumunda ve finansal alanları değiştirilemez ({1}). "
					"Düzeltme için yeni bir ödeme talebi oluşturun."
				).format(old_status, fieldname)
			)

	def _generate_reference_code(self) -> str:
		"""Banka açıklamasına yazılacak, insan-okunur eşleştirme kodu.

		Format: ISTOC-<store>-<5hex>  (ör. ISTOC-SEL-00002-A1B2C)
		"""
		suffix = frappe.generate_hash(length=5).upper()
		return f"ISTOC-{self.store}-{suffix}"

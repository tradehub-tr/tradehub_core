# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Shipment — sevkiyat çekirdek DocType'ı (TUR-105 / LOG-037).

Order 1:N Shipment ilişkisinin sevkiyat tarafı. Maliyet alanları
logistics/permissions.py mask_shipment_cost_fields listesiyle birebir aynıdır
ve view.logistics_cost capability'si olmayan kullanıcılara onload'da maskelenir.

Tenant izolasyonu: seller_profile alanı + logistics/permissions.py
(shipment_query_conditions + shipment_has_permission); hooks.py kablolaması
LOG-055 ile yapıldı. Adres snapshot değişmezliği F.3 kuralı ile korunur.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model import no_value_fields
from frappe.model.document import Document

# logistics/permissions.py mask_shipment_cost_fields ile BİREBİR aynı liste —
# alan adı ekleme/çıkarma iki tarafta birden yapılmalı.
#
# ANA KORUMA (F5): bu alanlar shipment.json'da permlevel=1'dir — Frappe
# field-level read/write'ı get_list / report / export / /api/resource
# yollarında kendiliğinden uygular (System Manager + Logistics Manager rw,
# Platform Finance r). Aşağıdaki onload maskeleme + restore guard
# DEFENSE-IN-DEPTH katmanı olarak kalır.
# BİLİNÇLİ KARAR: view.logistics_cost capability'si olan ama permlevel-1
# rolü olmayan kullanıcıyı da permlevel kısıtlar — capability yalnız
# maskeleme katmanını açar; alan erişiminin son sözü rol tabanlı permlevel'dedir.
_COST_FIELDS: tuple[str, ...] = (
	"shipping_cost",
	"insurance_cost",
	"total_cost",
	"carrier_cost",
	"fuel_surcharge",
	"packaging_cost",
)

# Platform Finance guard'ında muaf sayılan yazma-yetkili roller
# (logistics/permissions.py _SHIPMENT_WRITE_ROLES + Logistics Operator).
_PLATFORM_WRITE_ROLES: frozenset[str] = frozenset({
	"System Manager",
	"Marketplace Admin",
	"Logistics Manager",
	"Platform Admin",
	"Logistics Operator",
})

# F.3: dolu snapshot satırlarında değişmez kabul edilen alanlar
# (Shipment Address Snapshot şemasındaki tüm veri alanları).
_SNAPSHOT_IMMUTABLE_FIELDS: tuple[str, ...] = (
	"snapshot_type",
	"source_address",
	"contact_name",
	"company",
	"phone_prefix",
	"phone",
	"country",
	"state",
	"city",
	"street",
	"apartment",
	"postal_code",
	"tax_no",
	"tax_office",
)

# F7: insert sonrası Shipment Item satırlarında değişmez kabul edilen snapshot
# alanları. qty LİSTEDE YOKTUR — bilinçli: qty düzenlenebilir kalır, çünkü
# validate_split_invariants (INV-1) her kayıtta yeniden koşar. order_item da
# F3 (order eşleşme) doğrulamasına tabidir.
_ITEM_SNAPSHOT_IMMUTABLE_FIELDS: tuple[str, ...] = (
	"item_name",
	"unit_price",
	"listing",
	"variation",
)


class Shipment(Document):
	def onload(self) -> None:
		"""view.logistics_cost capability olmayan kullanıcıya maliyet alanlarını maskele."""
		from tradehub_core.logistics.permissions import mask_shipment_cost_fields

		mask_shipment_cost_fields(self)

	def before_save(self) -> None:
		self._restore_masked_cost_fields()

	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok (carrier_account emsali)
		self._guard_platform_finance_fields()
		self._guard_address_snapshot_immutability()
		self._guard_item_snapshot_immutability()
		self._apply_package_totals()
		# NOT: Durum geçiş validasyonu logistics/hooks.py validate_state_transition
		# doc_event'i ile bağlanır (Dalga B) — motor ile aynı saf kural
		# (logistics.constants.is_transition_allowed) kullanılır.

	# -------------------------------------------------------------------
	# Desi / ağırlık toplamları (LOG-039)
	# -------------------------------------------------------------------
	def _apply_package_totals(self) -> None:
		"""Paket satırlarından desi + ağırlık toplamlarını hesaplar.

		packages doluysa her satırın desi alanı ve doc'un total_weight /
		total_desi / chargeable_weight alanları calculate_shipment_totals
		ile doldurulur (bölen: Logistics Settings.default_desi_divisor).
		packages boşsa mevcut değerlere dokunulmaz — manuel/adaptör girişi
		ezilmesin. P1-6g istisnası: paketler ÖNCEDEN doluyken tamamen
		silindiyse toplamlar 0'a çekilir (bayat toplam kalmasın); hiç paket
		kullanılmamışsa (önce de boştu) dokunulmaz.
		"""
		from tradehub_core.logistics.services.desi import (
			calculate_desi,
			calculate_shipment_totals,
			get_desi_divisor,
		)

		packages = self.get("packages") or []
		if not packages:
			# P1-6g: önce dolu → şimdi boş = kullanıcı paketleri sildi; paket
			# kaynaklı toplamlar bayatladı, sıfırlanır. Önce de boşsa packages
			# hiç kullanılmamıştır — manuel/adaptör girilen toplamlar korunur.
			before = None if self.is_new() else self.get_doc_before_save()
			if before is not None and (before.get("packages") or []):
				self.total_weight = 0.0
				self.total_desi = 0.0
				self.chargeable_weight = 0.0
			return

		divisor: int = get_desi_divisor()
		items: list[dict] = []
		# F6: negatif boyut şemada non_negative=1 ile zaten reddedilir; bu
		# try/except derin savunmadır — desi servisinin ValueError'ı 500 yerine
		# anlamlı ValidationError'a çevrilir (API/adaptör yolları dahil).
		try:
			for package in packages:
				# P1-6g: qty >= 1 zorunlu — 0/negatif adet toplam hesabını
				# sessizce bozar (şemadaki non_negative yalnız negatifi keser).
				if package.get("qty") is not None and int(package.get("qty")) < 1:
					frappe.throw(
						_("Paket adedi en az 1 olmalıdır (satır {0}).").format(package.idx),
						exc=frappe.ValidationError,
					)
				length = package.get("length_cm") or 0.0
				width = package.get("width_cm") or 0.0
				height = package.get("height_cm") or 0.0
				# Satır bazlı desi: parsel BAŞINA hacimsel ağırlık (qty ile çarpılmaz).
				package.desi = calculate_desi(length, width, height, divisor=divisor)
				items.append(
					{
						"length_cm": length,
						"width_cm": width,
						"height_cm": height,
						"weight_kg": package.get("weight_kg") or 0.0,
						"qty": package.get("qty") or 1,
						"divisor": divisor,
					}
				)

			totals = calculate_shipment_totals(items)
		except ValueError as exc:
			frappe.throw(
				_("Paket boyutları geçersiz: {0}").format(exc),
				exc=frappe.ValidationError,
			)
		self.total_weight = totals["total_weight"]
		self.total_desi = totals["total_desi"]
		self.chargeable_weight = totals["chargeable_weight"]

	# -------------------------------------------------------------------
	# Mask restore guard (Faz 3.5 kararı)
	# -------------------------------------------------------------------
	def _restore_masked_cost_fields(self) -> None:
		"""Maskelenmiş (None) maliyet alanlarını DB'deki değerden geri yükle.

		mask_shipment_cost_fields onload'da maliyet alanlarını None yapar.
		Write yetkili ama view.logistics_cost capability'siz bir kullanıcı doc'u
		kaydederse None'lar DB'deki gerçek maliyeti ezmesin diye yalnız
		None → eski değer yönünde restore edilir. Capability'li kullanıcı muaf:
		bilinçli alan temizleme (None atama) dahil değişiklikleri korunur.
		"""
		if self.is_new():
			return
		if self._user_can_view_cost():
			return

		before = self.get_doc_before_save()
		if before is None:
			return

		for field in _COST_FIELDS:
			if self.get(field) is None and before.get(field) is not None:
				self.set(field, before.get(field))

	def _user_can_view_cost(self) -> bool:
		"""Kullanıcının view.logistics_cost capability'si var mı?

		Resolver yüklenemezse False döner (fail-closed): maskeleme uygulanmış
		varsayılır ve restore guard devrede kalır — veri kaybına karşı güvenli taraf.
		"""
		user: str = frappe.session.user
		if user == "Administrator":
			return True

		try:
			from tradehub_core.utils.permission_resolver import has_capability

			return bool(has_capability(user, "view.logistics_cost"))
		except (ImportError, AttributeError):
			return False

	# -------------------------------------------------------------------
	# Platform Finance field-level guard (J.2)
	# -------------------------------------------------------------------
	def _guard_platform_finance_fields(self) -> None:
		"""J.2: Platform Finance yalnız maliyet alanlarını değiştirebilir.

		shipment_has_permission Platform Finance için tüm yazma-türü ptype'ları
		zaten reddediyor; bu kontrol İKİNCİ savunma katmanıdır — örn.
		ignore_permissions'lı bir akış PF kullanıcısı adına kaydederse
		maliyet-dışı skaler alan değişikliği burada da engellenir.
		Child tablolar no_value_fields kapsamında diff dışıdır; onların
		korunması has_permission write reddi katmanına bırakıldı.
		"""
		user: str = frappe.session.user
		if user == "Administrator":
			return

		roles: set[str] = set(frappe.get_roles(user))
		if "Platform Finance" not in roles or roles & _PLATFORM_WRITE_ROLES:
			return

		before = self.get_doc_before_save()
		if before is None:
			# Yeni doc — create zaten shipment_has_permission'da reddediliyor
			return

		changed: list[str] = [
			df.fieldname
			for df in self.meta.fields
			if df.fieldtype not in no_value_fields
			and df.fieldname not in _COST_FIELDS
			and self.get(df.fieldname) != before.get(df.fieldname)
		]
		if changed:
			frappe.throw(
				_("Platform Finance rolü yalnız maliyet alanlarını düzenleyebilir. Değişen alanlar: {0}").format(
					", ".join(changed)
				),
				frappe.PermissionError,
			)

	# -------------------------------------------------------------------
	# Adres snapshot değişmezliği (F.3)
	# -------------------------------------------------------------------
	def _guard_address_snapshot_immutability(self) -> None:
		"""F.3: dolu adres snapshot satırları değiştirilemez ve silinemez.

		Snapshot before_insert hook'unda alınır (doldurma Dalga B'de). Mevcut
		satırların alanları DB kopyasıyla karşılaştırılır; fark varsa throw.
		Yeni satır eklemek serbesttir (snapshot doldurma akışı ekleyecek).
		"""
		if self.is_new():
			return

		before = self.get_doc_before_save()
		if before is None:
			return

		before_rows = {row.name: row for row in (before.get("address_snapshots") or [])}
		if not before_rows:
			return

		seen_names: set[str] = set()
		for row in self.get("address_snapshots") or []:
			if not row.name or row.name not in before_rows:
				continue  # yeni satır — serbest
			seen_names.add(row.name)
			old = before_rows[row.name]
			for field in _SNAPSHOT_IMMUTABLE_FIELDS:
				# "" ve None eşdeğer sayılır — form kaydında yanlış pozitif olmasın
				if (row.get(field) or None) != (old.get(field) or None):
					frappe.throw(
						_("Adres snapshot satırları değiştirilemez (satır {0}, alan: {1}).").format(
							row.idx, field
						)
					)

		deleted = set(before_rows) - seen_names
		if deleted:
			frappe.throw(_("Dolu adres snapshot satırları silinemez."))

	# -------------------------------------------------------------------
	# Kalem snapshot değişmezliği (F7)
	# -------------------------------------------------------------------
	def _guard_item_snapshot_immutability(self) -> None:
		"""F7: insert sonrası kalem snapshot alanları değiştirilemez.

		Adres snapshot guard'ı emsali. item_name/unit_price/listing/variation
		before_insert snapshot'ında dondurulur; sonradan değişiklik throw eder.
		qty DÜZENLENEBİLİRDİR — split invariant'ları (INV-1) her kayıtta
		yeniden koşar. Satır SİLME de serbesttir (miktar azaltma senaryosu):
		silinen satır sonrası kalan miktar INV-1 hesaplarında zaten
		yeniden hesaplanır (get_remaining_qty DB toplamından okur).
		"""
		if self.is_new():
			return

		before = self.get_doc_before_save()
		if before is None:
			return

		before_rows = {row.name: row for row in (before.get("items") or [])}
		if not before_rows:
			return

		for row in self.get("items") or []:
			if not row.name or row.name not in before_rows:
				continue  # yeni satır — serbest (INV-1 + F3 doğrulamaları ayrıca koşar)
			old = before_rows[row.name]
			for field in _ITEM_SNAPSHOT_IMMUTABLE_FIELDS:
				# "" ve None eşdeğer sayılır — form kaydında yanlış pozitif olmasın
				if (row.get(field) or None) != (old.get(field) or None):
					frappe.throw(
						_("Sevkiyat kalemi snapshot alanları değiştirilemez (satır {0}, alan: {1}).").format(
							row.idx, field
						)
					)

# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""TUR-104 — Lojistik katalog veri modeli testleri (Faz A.6).

Çalıştırma:
	docker exec istoccom-backend-1 bash -c "cd /home/frappe/workspace/frappe-bench && \\
	  bench --site dev.localhost run-tests \\
	  --module tradehub_core.logistics.tests.test_logistics_catalogs"

Kapsam — A.6'da kapatılan veri modeli açıkları:
	* Shipping Method teslim süresi doğrulaması artık OTORİTE alanlarda
	  (`min_days`/`max_days`); çatallanmış `estimated_delivery_days_*` çifti
	  kaldırıldı.
	* `Carrier Status Mapping` ve `Service Coverage Area` benzersizliği artık
	  DB seviyesinde (`autoname: format:`) — yarış koşuluna dayanıklı.
	* Serbest metin il adları kanonik biçime (diakritikli Türkçe) normalize
	  ediliyor; aksi halde "Istanbul" ve "İstanbul" benzersizlik kısıtını deler.
	* `Logistics Provider.country` artık `Link: Country`.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase


class TestShippingMethodDeliveryDays(FrappeTestCase):
	"""Teslim süresi doğrulaması otorite alanlarda çalışır."""

	def tearDown(self):
		frappe.db.rollback()

	def test_forked_fields_are_gone(self):
		"""Çatallanmış alan çifti DocType'tan kaldırılmış olmalı.

		Alanlar dururken storefront `min_days`/`max_days` okuyor, doğrulama ise
		yalnız `estimated_*` çiftini kontrol ediyordu — iki kaynak bağımsız
		sürükleniyordu.
		"""
		meta = frappe.get_meta("Shipping Method")
		fieldnames = {f.fieldname for f in meta.fields}
		self.assertNotIn("estimated_delivery_days_min", fieldnames)
		self.assertNotIn("estimated_delivery_days_max", fieldnames)
		self.assertIn("min_days", fieldnames)
		self.assertIn("max_days", fieldnames)

	def test_invalid_range_rejected(self):
		"""NEGATİF: max_days < min_days reddedilir."""
		doc = frappe.new_doc("Shipping Method")
		doc.method_name = "ZZ Test Geçersiz Aralık"
		doc.min_days = 5
		doc.max_days = 2
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_valid_range_accepted(self):
		"""POZİTİF: geçerli aralık kabul edilir."""
		doc = frappe.new_doc("Shipping Method")
		doc.method_name = "ZZ Test Geçerli Aralık"
		doc.min_days = 1
		doc.max_days = 3
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.min_days, 1)
		self.assertEqual(doc.max_days, 3)

	def test_logistics_roles_can_manage_catalog(self):
		"""Lojistik rolleri Shipping Method'u yönetebilmeli (diğer 7 katalogla simetri)."""
		perms = {p.role: p for p in frappe.get_meta("Shipping Method").permissions}
		self.assertIn("Logistics Manager", perms)
		self.assertTrue(perms["Logistics Manager"].write)
		self.assertIn("Logistics Operator", perms)
		self.assertTrue(perms["Logistics Operator"].read)


class TestServiceCoverageAreaUniqueness(FrappeTestCase):
	"""Kapsama alanı benzersizliği + il adı normalizasyonu."""

	def setUp(self):
		self.carrier = frappe.db.get_value("Logistics Provider", {"is_active": 1}, "name")
		self.assertIsNotNone(self.carrier, "Seed edilmiş Logistics Provider bulunamadı")

	def tearDown(self):
		frappe.db.rollback()

	def _new_area(self, city: str) -> frappe.Document:
		doc = frappe.new_doc("Service Coverage Area")
		doc.carrier = self.carrier
		doc.city = city
		doc.is_active = 1
		return doc

	def test_ascii_city_normalized_to_canonical(self):
		"""'Istanbul' kanonik 'İstanbul' biçimine çevrilir."""
		doc = self._new_area("Istanbul")
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.city, "İstanbul")

	def test_duplicate_area_rejected_across_spelling_variants(self):
		"""NEGATİF: 'Sanliurfa' ve 'Şanlıurfa' aynı alandır — ikincisi reddedilir.

		ÖRNEK SEÇİMİ ÖNEMLİ: DB collation'ı `utf8mb4_unicode_ci`, yani bazı
		çiftleri kendisi eşit sayıyor ve normalizasyon olmasa da duplicate'i
		engelliyor:

		    'Istanbul'  = 'İstanbul'   COLLATE utf8mb4_unicode_ci  -> 1  (engeller)
		    'Sanliurfa' = 'Şanlıurfa'  COLLATE utf8mb4_unicode_ci  -> 0  (ENGELLEMEZ)

		İstanbul çifti ile yazılan bir test, normalizasyon tamamen kaldırılsa
		bile yeşil kalırdı — koruduğu şeyi kanıtlamazdı. Bu yüzden collation'ın
		yakalayamadığı Şanlıurfa çifti kullanılıyor.
		"""
		self._new_area("Şanlıurfa").insert(ignore_permissions=True)
		with self.assertRaises(frappe.DuplicateEntryError):
			self._new_area("Sanliurfa").insert(ignore_permissions=True)

	def test_different_city_allowed(self):
		"""POZİTİF: farklı il ayrı kayıt olabilir."""
		self._new_area("İstanbul").insert(ignore_permissions=True)
		second = self._new_area("Ankara")
		second.insert(ignore_permissions=True)
		self.assertEqual(second.city, "Ankara")


class TestCarrierStatusMappingUniqueness(FrappeTestCase):
	"""Taşıyıcı durum eşlemesi benzersizliği."""

	def setUp(self):
		self.carrier = frappe.db.get_value("Logistics Provider", {"is_active": 1}, "name")

	def tearDown(self):
		frappe.db.rollback()

	def _new_mapping(self, code: str) -> frappe.Document:
		doc = frappe.new_doc("Carrier Status Mapping")
		doc.carrier = self.carrier
		doc.carrier_status_code = code
		doc.internal_status = "In Transit"
		return doc

	def test_whitespace_stripped_from_code(self):
		"""Baş/son boşluk temizlenir — aksi halde ayrı kayıt adı üretirdi."""
		doc = self._new_mapping("  ST-01  ")
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.carrier_status_code, "ST-01")

	def test_duplicate_mapping_rejected(self):
		"""NEGATİF: aynı taşıyıcı + durum kodu ikinci kez eşlenemez.

		Eşleme çift olsaydı takip durumu çözümü non-deterministik olurdu.
		"""
		self._new_mapping("ST-01").insert(ignore_permissions=True)
		with self.assertRaises((frappe.ValidationError, frappe.DuplicateEntryError)):
			self._new_mapping("ST-01").insert(ignore_permissions=True)

	def test_invalid_internal_status_rejected(self):
		"""NEGATİF: durum makinesinde olmayan iç durum reddedilir."""
		doc = self._new_mapping("ST-02")
		doc.internal_status = "Teleported"
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)


class TestLogisticsProviderCountryLink(FrappeTestCase):
	"""Ülke alanı referanslı — TUR-102 'ülke/bölge genişleme alanları'."""

	def test_country_is_link_to_country_doctype(self):
		field = frappe.get_meta("Logistics Provider").get_field("country")
		self.assertEqual(field.fieldtype, "Link")
		self.assertEqual(field.options, "Country")

	def test_seeded_providers_reference_valid_countries(self):
		"""Seed edilmiş sağlayıcıların tamamı geçerli Country kaydına bakmalı.

		LOG-025 eskiden Türkçe metin yazıyordu ("Türkiye"); Country DocType'ı
		İngilizce adlandırıyor. LOG-039 backfill'i bunu düzeltti.
		"""
		rows = frappe.get_all("Logistics Provider", fields=["name", "country"])
		self.assertTrue(rows, "Seed edilmiş sağlayıcı yok")
		for row in rows:
			if not row.country:
				continue
			self.assertTrue(
				frappe.db.exists("Country", row.country),
				f"{row.name} geçersiz Country referansı taşıyor: {row.country!r}",
			)


class TestChannelMethodIndependence(FrappeTestCase):
	"""TUR-104: taşıma yöntemi ile işletim kanalı bağımsızdır."""

	def test_five_operating_channels_defined(self):
		"""Kargo / Ambar / Kurye / Satıcı Aracı / Alıcı Teslim Alma ayrı tanımlı."""
		codes = set(frappe.get_all("Shipping Channel", pluck="channel_code"))
		self.assertTrue(
			{"CARGO", "WAREHOUSE", "COURIER", "SELLER_VEHICLE", "BUYER_PICKUP"} <= codes
		)

	def test_no_active_method_mirrors_a_channel_name(self):
		"""NEGATİF: aktif hiçbir yöntem bir kanalın birebir kopyası olmamalı.

		LOG-024 ilk sürümü her kanal için aynı adla bir yöntem üretiyordu;
		LOG-040 bunları pasifleştirdi.
		"""
		channel_names = set(frappe.get_all("Shipping Channel", pluck="channel_name"))
		active_methods = set(
			frappe.get_all("Shipping Method", filters={"is_active": 1}, pluck="method_name")
		)
		self.assertEqual(
			channel_names & active_methods,
			set(),
			"Aktif yöntem bir kanal adının kopyası — yöntem/kanal bağımsızlığı bozuk",
		)

	def test_providers_declare_operating_channels(self):
		"""Kargo tipi sağlayıcılar hangi kanalda çalıştığını bildirmeli."""
		cargo_providers = frappe.get_all(
			"Logistics Provider", filters={"provider_type": "Kargo"}, pluck="name"
		)
		self.assertTrue(cargo_providers, "Kargo tipi sağlayıcı yok")
		for provider in cargo_providers:
			channels = frappe.get_all(
				"Provider Operating Channel",
				filters={"parent": provider, "parenttype": "Logistics Provider"},
				pluck="shipping_channel",
			)
			self.assertIn("CARGO", channels, f"{provider} CARGO kanalını bildirmiyor")

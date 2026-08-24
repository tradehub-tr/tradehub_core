"""105-D2 (ADR-0022) — kota hesabına TÜREV baytlarının eklendiğini doğrulayan
bench testleri.

`test_media_quota.py` saf-Python stub'la `check_media_storage_quota` KARARINI
ölçüyor; bu dosya ise GERÇEK DB üzerinde `media.files.storage_usage`'ın türev
(`Media Rendition`) baytlarını orijinallere kattığını ölçer. Türevler ayrı bir
`File` kaydı açmadığı için (içerik-adresli, `dedup.rendition_path`) eskiden
kotaya hiç girmiyordu; ADR-0022 ile gerçek disk kullanımını yansıtsın diye
sayılıyorlar.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_quota_renditions

Fixture'lar `FrappeTestCase` transaction'ında kurulur; test sonunda otomatik
rollback edilir (hiçbir yerde `frappe.db.commit()` çağrılmadığı için — bkz.
`test_media_pipeline_integration._delete_and_commit` notundaki uyarı, o uyarı
YALNIZ commit eden akışlar için geçerli).
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import seller_media
from tradehub_core.media import files


class TestKotaTurevBaytlari(FrappeTestCase):
	"""Satıcının kota kullanımı = orijinal baytlar + türev baytlar."""

	def _make_store(self, tag: str) -> str:
		"""Throwaway User + Admin Seller Profile — türev sahipliği için mağaza."""
		suffix = frappe.generate_hash(length=8)
		email = f"kota-turev-{tag}-{suffix}@test.local"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Kota",
				"last_name": "Turev",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		store = frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_name": f"Kota Turev Satici {tag}",
				"seller_code": frappe.generate_hash(length=10),
				"user": email,
				"email": email,
				"status": "Active",
			}
		).insert(ignore_permissions=True, ignore_mandatory=True)
		return store.name

	def _make_asset(self, store: str) -> str:
		"""`owner_seller = store` olan bir Media Asset — türevlerin bağlanacağı zincir."""
		asset = frappe.get_doc(
			{
				"doctype": "Media Asset",
				# Link alanına uydurma anahtar yazmak, Frappe bağlantı
				# doğrulamasını test etmek olurdu. Kota hesabı slot türünden
				# bağımsızdır; çekirdek fixture'daki gerçek politika yeterlidir.
				"slot_key": "product.image",
				"media_type": "image",
				"state": "ready",
				"owner_seller": store,
			}
		).insert(ignore_permissions=True, ignore_mandatory=True)
		return asset.name

	def _make_rendition(self, asset: str, bytes_: int, width: int, fmt: str = "webp") -> None:
		frappe.get_doc(
			{
				"doctype": "Media Rendition",
				"asset": asset,
				"profile": f"p{width}",
				"width": width,
				"format": fmt,
				"bytes": bytes_,
			}
		).insert(ignore_permissions=True, ignore_mandatory=True)

	def _make_job(self, asset: str, duration_ms: int) -> None:
		frappe.get_doc(
			{
				"doctype": "Media Processing Job",
				"asset": asset,
				"job_type": "rendition",
				"queue": "media-image-live",
				"status": "success",
				"idempotency_key": f"quota-job-{frappe.generate_hash(length=20)}",
				"duration_ms": duration_ms,
			}
		).insert(ignore_permissions=True, ignore_mandatory=True)

	# --- Senaryolar --------------------------------------------------------

	def test_kota_turev_baytlarini_icerir(self):
		"""storage_usage.bytes = original_bytes + türev toplamı; tek toplu SUM."""
		store = self._make_store("A")
		asset = self._make_asset(store)
		self._make_rendition(asset, 1000, 320)
		self._make_rendition(asset, 2500, 640)

		self.assertEqual(files.rendition_usage(store), 3500)

		usage = files.storage_usage(store)
		self.assertEqual(usage["rendition_bytes"], 3500)
		self.assertEqual(usage["renditions"], 2)
		# Toplam kalemi = orijinaller + türevler (ADR-0022 sözleşmesi).
		self.assertEqual(usage["bytes"], usage["original_bytes"] + 3500)
		# Türev satır sayısı `files` (orijinal sayacı) alanını ŞİŞİRMEZ.
		self.assertEqual(usage["files"], 0)
		self.assertEqual(usage["quota_mode"], "unconfigured")
		self.assertEqual(
			usage["scope"],
			{"public_originals": True, "private_originals": False, "renditions": True},
		)

	def test_turevi_olmayan_satici_degismez(self):
		"""Hiç türevi olmayan satıcıda `bytes == original_bytes`; ekleme fark yaratmaz."""
		store = self._make_store("B")
		usage = files.storage_usage(store)
		self.assertEqual(usage["rendition_bytes"], 0)
		self.assertEqual(usage["bytes"], usage["original_bytes"])

	def test_tenant_a_kotasi_b_turevleriyle_sismez(self):
		"""Kiracı kemeri: A'nın kotası B'nin türevleriyle şişmez.

		VACUITY: `rendition_usage` içindeki `owner_seller == store` filtresi
		gevşetilirse (kaldırılırsa) A, B'nin 9999 baytlık türevini de sayar ve bu
		test KIRMIZIYA döner — filtrenin gerçekten iş yaptığının kanıtı.
		"""
		store_a = self._make_store("TA")
		store_b = self._make_store("TB")
		asset_b = self._make_asset(store_b)
		self._make_rendition(asset_b, 9999, 320)

		# A'nın hiç türevi yok — B'ninki A'ya sızmamalı.
		self.assertEqual(files.rendition_usage(store_a), 0)
		self.assertEqual(files.storage_usage(store_a)["rendition_bytes"], 0)

		# Kontrol (fixture gerçekten yazıldı mı): B kendi türevini görür.
		self.assertEqual(files.rendition_usage(store_b), 9999)

	def test_aylik_is_hacmi_tenant_bazinda_raporlanir(self):
		"""İş adedi/süresi gözlem metriğidir; başka tenant sonucu şişiremez."""
		store_a = self._make_store("JA")
		store_b = self._make_store("JB")
		asset_a = self._make_asset(store_a)
		asset_b = self._make_asset(store_b)
		self._make_job(asset_a, 120)
		self._make_job(asset_a, 380)
		self._make_job(asset_b, 9999)

		usage = files.storage_usage(store_a, include_activity=True)
		self.assertEqual(usage["processing_jobs_month"], 2)
		self.assertEqual(usage["processing_duration_ms_month"], 500)
		self.assertRegex(usage["processing_period_start"], r"^\d{4}-\d{2}-01$")

		# Whitelist özeti eski bytes/quota alanlarını korurken ayrıntılı tenant
		# kota sözleşmesini de dışarı açar; mağaza gövdeden alınmaz.
		with (
			mock.patch.object(seller_media, "_store", return_value=store_a),
			mock.patch.object(
				seller_media.inventory,
				"list_files",
				side_effect=[{"total": 3}, {"total": 1}],
			),
			mock.patch.object(seller_media.metadata, "all_tags", return_value=[]),
		):
			ozet = seller_media.get_my_summary()
		self.assertEqual(ozet["store"], store_a)
		self.assertEqual(ozet["processing_jobs_month"], 2)
		self.assertEqual(ozet["renditions"], 0)
		self.assertIn("quota_state", ozet)
		self.assertEqual(ozet["scope"]["private_originals"], False)

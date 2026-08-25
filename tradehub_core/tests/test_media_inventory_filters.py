"""MOGEM-578 — medya arama/filtreleme sorgusu entegrasyon testleri.

Filtreler Python'da dönen ilk sayfaya uygulanmaz; SQL'in gruplanmış envanter
sorgusuna toplam ve LIMIT/OFFSET'ten önce girer. Bu dosya özellikle tarih,
boyut, MIME/format, yön ve çoklu etiket kombinasyonunu gerçek MariaDB üzerinde
ölçer.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_inventory_filters
"""

from __future__ import annotations

import io
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import seller_media
from tradehub_core.media import inventory


class TestMediaInventoryFilters(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.suffix = frappe.generate_hash(length=8)
		self.rows: dict[str, frappe.Document] = {}
		self._file(
			"hero",
			"kampanya-hero.webp",
			400_000,
			"2026-08-20 10:00:00",
			width=1200,
			height=800,
			tags="kampanya,hero",
			title="Yaz Kampanyası",
			favorite=1,
		)
		self._file(
			"portrait",
			"portre.jpg",
			2_000_000,
			"2026-07-01 10:00:00",
			width=800,
			height=1200,
			tags="kampanya",
		)
		self._file(
			"video",
			"tanitim.mp4",
			6_000_000,
			"2026-08-21 10:00:00",
			width=1920,
			height=1080,
			tags="hero",
		)
		self._file(
			"document",
			"katalog.pdf",
			100_000,
			"2026-08-22 10:00:00",
		)
		self._file(
			"square",
			"kare.webp",
			450_000,
			"2026-08-23 10:00:00",
			width=900,
			height=900,
			tags="kampanya,hero",
		)

	def _file(
		self,
		key: str,
		file_name: str,
		file_size: int,
		creation: str,
		*,
		width: int = 0,
		height: int = 0,
		tags: str = "",
		title: str = "",
		favorite: int = 0,
	):
		ext = file_name.rsplit(".", 1)[-1].lower()
		if ext in {"webp", "jpg", "jpeg"}:
			from PIL import Image

			buffer = io.BytesIO()
			color = (sum(key.encode()) % 255, 80, 160)
			Image.new("RGB", (2, 2), color).save(buffer, "WEBP" if ext == "webp" else "JPEG")
			content = buffer.getvalue()
		elif ext == "pdf":
			from pypdf import PdfWriter

			buffer = io.BytesIO()
			writer = PdfWriter()
			writer.add_blank_page(width=72, height=72)
			writer.write(buffer)
			content = buffer.getvalue()
		else:
			content = f"mogem-578 {self.suffix} {key}".encode()
		display_name = f"{self.suffix}-{file_name}"
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": display_name,
				"file_type": ext.upper(),
				"is_private": 0,
				"content": content,
			}
		)
		with mock.patch("tradehub_core.media.av.enqueue_scan"):
			doc.insert(ignore_permissions=True)
		self.addCleanup(
			lambda name=doc.name: (
				frappe.db.exists("File", name)
				and frappe.delete_doc("File", name, ignore_permissions=True, force=True)
			)
		)
		frappe.db.set_value(
			"File",
			doc.name,
			{
				"file_size": file_size,
				"creation": creation,
				"th_media_width": width,
				"th_media_height": height,
				"th_media_tags": tags,
				"th_media_title": title,
				"th_media_favorite": favorite,
			},
			update_modified=False,
		)
		self.rows[key] = doc
		return doc

	def _list(self, **filters):
		# Bu test kullanım taramasını değil SQL filtre sırasını ölçüyor. Global
		# kullanım kaynaklarını taramak hem ilgisiz hem fixture'a göre değişken.
		with (
			mock.patch("tradehub_core.media.usage.verdict_map_all", return_value={}),
			mock.patch("tradehub_core.media.usage.usage_counts_all", return_value={}),
		):
			return inventory.list_files(page=1, page_size=20, name_search=self.suffix, **filters)

	def test_tarih_boyut_format_yon_etiket_tek_sorguda_birlesir(self):
		result = self._list(
			formats='["WEBP"]',
			orientations='["landscape"]',
			tags='["kampanya", "hero"]',
			date_from="2026-08-20",
			date_to="2026-08-20",
			min_bytes="300000",
			max_bytes="500000",
		)

		self.assertEqual(result["total"], 1)
		self.assertEqual([row["file_url"] for row in result["items"]], [self.rows["hero"].file_url])
		self.assertEqual(result["items"][0]["mime_type"], "image/webp")

	def test_filtre_toplami_sayfalamadan_once_hesaplanir(self):
		with (
			mock.patch("tradehub_core.media.usage.verdict_map_all", return_value={}),
			mock.patch("tradehub_core.media.usage.usage_counts_all", return_value={}),
		):
			result = inventory.list_files(
				page=2,
				page_size=1,
				name_search=self.suffix,
				mime_types='["image/webp"]',
				sort_by="date",
				sort_dir="asc",
			)

		self.assertEqual(result["total"], 2)
		self.assertEqual(result["page"], 2)
		self.assertEqual(len(result["items"]), 1)
		self.assertEqual(result["items"][0]["file_url"], self.rows["square"].file_url)

	def test_boyut_kovalari_kendi_aralarinda_or_orta_boyut_haric(self):
		result = self._list(size_buckets='["small", "large"]')
		urls = {row["file_url"] for row in result["items"]}

		self.assertIn(self.rows["hero"].file_url, urls)
		self.assertIn(self.rows["video"].file_url, urls)
		self.assertIn(self.rows["document"].file_url, urls)
		self.assertNotIn(self.rows["portrait"].file_url, urls)

	def test_serbest_arama_satici_ustveri_basligini_da_bulur(self):
		result = self._list(search="Yaz Kampanyası")
		self.assertEqual(result["total"], 1)
		self.assertEqual(result["items"][0]["file_url"], self.rows["hero"].file_url)

	def test_bozuk_filtreler_validation_error_dondurur(self):
		for filters in (
			{"date_from": "20.08.2026"},
			{"formats": '["webp", "../../sql"]'},
			{"orientations": '["diagonal"]'},
			{"min_bytes": "1.5"},
			{"tags": '{"tag": "hero"}'},
			{"only_optimizable": "2"},
		):
			with self.subTest(filters=filters), self.assertRaises(frappe.ValidationError):
				inventory.list_files(**filters)


class TestSellerMediaFilterContract(FrappeTestCase):
	def test_endpoint_yeni_filtreleri_tenant_scope_ile_inventorye_iletir(self):
		with (
			mock.patch.object(seller_media, "_store", return_value="STORE-MOGEM-578"),
			mock.patch.object(
				seller_media.inventory,
				"list_files",
				return_value={"items": [], "total": 0, "page": 3, "page_size": 24},
			) as listed,
		):
			seller_media.get_my_media(
				page=3,
				page_size=24,
				formats='["WEBP"]',
				mime_types='["image/webp"]',
				orientations='["landscape"]',
				tags='["hero"]',
				date_from="2026-08-01",
				max_bytes="5000000",
			)

		kwargs = listed.call_args.kwargs
		self.assertEqual(kwargs["store"], "STORE-MOGEM-578")
		self.assertEqual(kwargs["page"], 3)
		self.assertEqual(kwargs["formats"], '["WEBP"]')
		self.assertEqual(kwargs["mime_types"], '["image/webp"]')
		self.assertEqual(kwargs["orientations"], '["landscape"]')
		self.assertEqual(kwargs["tags"], '["hero"]')
		self.assertEqual(kwargs["date_from"], "2026-08-01")
		self.assertEqual(kwargs["max_bytes"], "5000000")

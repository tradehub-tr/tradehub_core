"""Bulk Import — whitelisted REST endpoints (Frappe v15)."""

import json
import os

import frappe
from frappe import _

MAX_DATA_FILE_BYTES = 25 * 1024 * 1024  # 25 MB
MAX_IMAGES_ZIP_BYTES = 200 * 1024 * 1024  # 200 MB
DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 200


@frappe.whitelist()
def start_product_import(
	file_id: str,
	images_zip_id: str | None = None,
	mode: str = "insert_only",
	column_mapping: str | None = None,
	header_row: int = 1,
	sheet_name: str | None = None,
) -> dict:
	"""Bulk import job oluştur ve enqueue et.

	Args:
	    file_id: File DocType "name" (data file)
	    images_zip_id: File DocType "name" (resim ZIP), opsiyonel
	    mode: "insert_only" | "upsert"
	    column_mapping: JSON string {canonical_field: header}
	    header_row: 1-indexed başlık satırı
	    sheet_name: xlsx için sheet adı
	"""
	seller = frappe.db.get_value(
		"Admin Seller Profile",
		{"owner": frappe.session.user},
		"name",
	)
	if not seller:
		frappe.throw(_("Satıcı profili bulunamadı"))

	active = frappe.db.exists(
		"Bulk Import Job",
		{
			"seller_profile": seller,
			"status": ["in", ["Queued", "Running"]],
		},
	)
	if active:
		frappe.throw(_("Devam eden bir yüklemeniz var. Önce onu bitirin ya da bekleyin."))

	file_doc = frappe.get_doc("File", file_id)
	if (file_doc.file_size or 0) > MAX_DATA_FILE_BYTES:
		frappe.throw(_("Veri dosyası 25 MB'ı aşamaz"))

	zip_doc = None
	if images_zip_id:
		zip_doc = frappe.get_doc("File", images_zip_id)
		if (zip_doc.file_size or 0) > MAX_IMAGES_ZIP_BYTES:
			frappe.throw(_("Resim ZIP'i 200 MB'ı aşamaz"))

	file_format = _detect_format(file_doc.file_name)

	resolved_mode = mode if mode in ("insert_only", "upsert") else "insert_only"

	try:
		header_row_int = int(header_row or 1)
	except (ValueError, TypeError):
		header_row_int = 1

	job = frappe.new_doc("Bulk Import Job")
	job.seller_profile = seller
	job.data_file = file_doc.file_url
	job.images_zip = zip_doc.file_url if zip_doc else None
	job.file_format = file_format
	job.update_mode = resolved_mode
	job.column_mapping = column_mapping
	job.header_row = header_row_int
	job.sheet_name = sheet_name
	job.status = "Queued"
	job.insert()

	# `job_name` frappe.enqueue'un reserved kwarg'ı (RQ job ID) — runner'a iletilmez.
	# Bu yüzden runner kwarg'ını `bulk_job_name` adıyla geçiyoruz.
	frappe.enqueue(
		"tradehub_core.bulk_import.runner.run",
		queue="long",
		timeout=3600,
		enqueue_after_commit=True,
		bulk_job_name=job.name,
	)

	return {"job_name": job.name, "redirect": f"/panel/bulk-import/{job.name}"}


@frappe.whitelist()
def get_import_status(job_name: str) -> dict:
	"""Polling endpoint — Redis cache + DB fallback."""
	doc = frappe.get_doc("Bulk Import Job", job_name)
	doc.check_permission("read")

	# Hata satırları (child table) — UI "Hata Listesi" bunu okur. Redis progress
	# state'i yalnız sayaç tutar; child satırları + özeti her zaman doc'tan ekle ki
	# polling ile gelen yanıt da hata listesini içersin (önceden hiç gelmiyordu).
	error_details = [
		{
			"row_number": r.row_number,
			"sku": r.sku,
			"product_name": r.product_name,
			"error_type": r.error_type,
			"error_message": r.error_message,
		}
		for r in (doc.error_details or [])
	]

	cache_key = f"bulk_import_progress:{job_name}"
	redis_state = frappe.cache.get_value(cache_key)
	if redis_state:
		redis_state["error_details"] = error_details
		redis_state["error_summary"] = doc.error_summary or ""
		return redis_state

	processed = (
		(doc.inserted_count or 0)
		+ (doc.updated_count or 0)
		+ (doc.skipped_count or 0)
		+ (doc.error_count or 0)
	)
	return {
		"state": (doc.status or "queued").lower(),
		"total": doc.total_rows or 0,
		"processed": processed,
		"inserted": doc.inserted_count or 0,
		"updated": doc.updated_count or 0,
		"skipped": doc.skipped_count or 0,
		"error_count": doc.error_count or 0,
		"error_summary": doc.error_summary or "",
		"error_details": error_details,
	}


@frappe.whitelist()
def dry_run_preview(
	file_id: str,
	mode: str = "insert_only",
	column_mapping: str | None = None,
) -> dict:
	"""Dosyayı parse et, eklenecek/güncellenecek/atlanacak özetini döndür.

	Persist YAPMAZ — sadece parser + validator çalıştırır.
	"""
	from tradehub_core.bulk_import.ingestion import resolver
	from tradehub_core.bulk_import.parsers import csv_parser, xlsx_parser, xml_parser

	seller = frappe.db.get_value(
		"Admin Seller Profile",
		{"owner": frappe.session.user},
		"name",
	)
	if not seller:
		frappe.throw(_("Satıcı profili bulunamadı"))

	file_doc = frappe.get_doc("File", file_id)
	if (file_doc.file_size or 0) > MAX_DATA_FILE_BYTES:
		frappe.throw(_("Veri dosyası 25 MB'ı aşamaz"))
	if (file_doc.file_size or 0) == 0:
		frappe.throw(
			_(
				"Dosya boş görünüyor (0 byte). Lütfen tarayıcıyı tam yenileyin "
				"(Ctrl+Shift+R) ve dosyayı tekrar yükleyin."
			)
		)

	file_format = _detect_format(file_doc.file_name)
	file_path = _file_absolute_path(file_doc)

	try:
		if file_format == "xlsx":
			headers, rows = xlsx_parser.parse_xlsx(file_path)
		elif file_format == "csv":
			headers, rows = csv_parser.parse_csv(file_path)
		else:
			headers, rows = xml_parser.parse_xml(file_path)
	except Exception as e:
		# zipfile.BadZipFile (xlsx bozuk), openpyxl.InvalidFileException,
		# csv.Error, ElementTree.ParseError → kullanıcıya anlamlı mesaj.
		frappe.log_error(
			title=f"Bulk dry_run_preview parse failed: {type(e).__name__}",
			message=frappe.get_traceback() + f"\n\nfile={file_doc.file_name} format={file_format}",
		)
		frappe.throw(
			_(
				"Dosya okunamadı ({0}). Dosyanın bozuk olmadığından emin olun ve "
				"tarayıcıyı tam yenileyip (Ctrl+Shift+R) tekrar deneyin."
			).format(type(e).__name__)
		)

	# Manuel override geldiyse onu kullan; aksi halde 4 katmanlı resolver
	# (Profile → Regex → Attribute → Semantic) çalışır. Resolver attr:<code>,
	# product_type, variant_* hedeflerini de üretir — persister bunları tüketir.
	resolution: dict = {}
	if column_mapping:
		try:
			mapping = json.loads(column_mapping)
		except (ValueError, TypeError):
			resolution = resolver.resolve_columns(headers, seller)
			mapping = resolution.get("mapping", {})
	else:
		resolution = resolver.resolve_columns(headers, seller)
		mapping = resolution.get("mapping", {})

	return _compute_dry_run(headers, rows, mapping, resolution, seller, mode)


def _compute_dry_run(
	headers: list[str],
	rows: list[dict],
	mapping: dict,
	resolution: dict,
	seller: str,
	mode: str,
) -> dict:
	"""Dry-run çekirdek hesabı — persist YAPMAZ, sayım + güven/varyant özeti döndürür.

	`dry_run_preview` (dosyadan) ve `feed_api.feed_dry_run` (feed URL'sinden) ortak
	bu fonksiyonu çağırır; will_insert/update/skip/error mantığı tek yerde kalsın.

	Args:
	    headers: Parse edilmiş başlık listesi.
	    rows: Parse edilmiş satır dict'leri.
	    mapping: {canonical_field: header} eşlemesi (resolver ya da manuel).
	    resolution: resolver.resolve_columns çıktısı (sources/confidence/unmapped);
	        manuel override yolunda boş dict olabilir.
	    seller: Admin Seller Profile name (check_sku_exists scope'u).
	    mode: "insert_only" | "upsert".
	"""
	from tradehub_core.bulk_import import persister, validator
	from tradehub_core.bulk_import.ingestion import semantic

	# Runner ile aynı cluster mantığı: aynı `seller_sku` altındaki satırlar
	# parent + variant grubu. Aksi takdirde varyant satırlarını "hata" olarak
	# sayıp kullanıcıyı yanıltıyorduk.
	from tradehub_core.bulk_import.runner import _build_clusters

	resolved_mode = mode if mode in ("insert_only", "upsert") else "insert_only"

	will_insert = will_update = will_skip = will_error = 0
	sample_errors: list[dict] = []
	variant_clusters_count = 0
	total_variants = 0

	clusters, cluster_errors = _build_clusters(rows, mapping)

	for c_idx, _raw_row, msg in cluster_errors:
		will_error += 1
		if len(sample_errors) < 5:
			sample_errors.append({"row": c_idx, "messages": [msg]})

	for cluster in clusters:
		parent_idx = cluster["parent_idx"]
		parent_data = cluster["parent_data"]
		parent_raw = cluster["parent_raw_row"]
		variant_rows = cluster["variant_data_rows"]

		if variant_rows:
			variant_clusters_count += 1
			total_variants += len(variant_rows)

		row_errors = validator.validate_row(parent_raw, mapping)
		if row_errors:
			will_error += 1
			if len(sample_errors) < 5:
				sample_errors.append(
					{
						"row": parent_idx,
						"messages": [e["message"] for e in row_errors],
					}
				)
			continue

		sku = parent_data.get("sku")
		if not sku:
			will_error += 1
			if len(sample_errors) < 5:
				sample_errors.append({"row": parent_idx, "messages": ["SKU eksik"]})
			continue

		if persister.check_sku_exists(str(sku).strip(), seller):
			if resolved_mode == "insert_only":
				will_skip += 1
			else:
				will_update += 1
		else:
			will_insert += 1

	total = len(rows)
	mapped = len([h for h in headers if h and h in mapping.values()])
	confidence_score = (mapped / len(headers)) if headers else 0.0

	# Resolver çıktısı — manuel override yolunda boş olabilir; o durumda
	# eşlenen alanlar için makul varsayılanlar üret (FE badge/confidence için).
	sources = resolution.get("sources") or {f: "manual" for f in mapping}
	confidence_by_field = resolution.get("confidence") or {f: 1.0 for f in mapping}
	unmapped_headers = resolution.get("unmapped")
	if unmapped_headers is None:
		unmapped_headers = [h for h in headers if h and h not in mapping.values()]
	low_confidence_fields = [f for f, c in confidence_by_field.items() if c < semantic.CONFIDENCE_THRESHOLD]

	return {
		"total": total,
		"will_insert": will_insert,
		"will_update": will_update,
		"will_skip": will_skip,
		"will_error": will_error,
		"sample_errors": sample_errors,
		"confidence_score": round(confidence_score, 3),
		"detected_headers": headers,
		"resolved_mapping": mapping,
		# 4 katmanlı resolver çıktısı — FE source badge + confidence UI için
		"sources": sources,
		"confidence_by_field": confidence_by_field,
		"unmapped_headers": unmapped_headers,
		"low_confidence_fields": low_confidence_fields,
		"profile_used": resolution.get("profile_used"),
		"overall_score": resolution.get("overall_score", round(confidence_score, 3)),
		# Varyant özeti — UI gösterimi için
		"variant_clusters": variant_clusters_count,
		"total_variants": total_variants,
	}


@frappe.whitelist()
def get_my_history(limit: int = DEFAULT_HISTORY_LIMIT) -> list:
	"""Geçmiş job'ları döndür.

	- Marketplace Admin / System Manager → tüm satıcıların job'larını görür.
	- Satıcı → yalnızca kendi seller_profile'ının job'larını görür.
	"""
	try:
		limit_int = int(limit)
	except (ValueError, TypeError):
		limit_int = DEFAULT_HISTORY_LIMIT
	limit_int = max(1, min(limit_int, MAX_HISTORY_LIMIT))

	fields = [
		"name",
		"creation",
		"data_file",
		"status",
		"total_rows",
		"inserted_count",
		"updated_count",
		"skipped_count",
		"error_count",
		"duration_seconds",
		"seller_profile",
	]

	roles = set(frappe.get_roles())
	if roles & {"System Manager", "Marketplace Admin"}:
		return frappe.get_list(
			"Bulk Import Job",
			fields=fields,
			order_by="creation desc",
			limit=limit_int,
		)

	seller = frappe.db.get_value(
		"Admin Seller Profile",
		{"owner": frappe.session.user},
		"name",
	)
	if not seller:
		return []

	return frappe.get_list(
		"Bulk Import Job",
		filters={"seller_profile": seller},
		fields=fields,
		order_by="creation desc",
		limit=limit_int,
	)


@frappe.whitelist()
def download_error_excel(job_name: str) -> dict:
	"""Hatalı satırları Excel olarak indir. File URL döndür."""
	import io

	from openpyxl import Workbook

	doc = frappe.get_doc("Bulk Import Job", job_name)
	doc.check_permission("read")

	error_rows = frappe.get_all(
		"Bulk Import Job Error",
		filters={"parent": job_name, "parenttype": "Bulk Import Job"},
		fields=[
			"row_number",
			"sku",
			"product_name",
			"error_type",
			"error_message",
			"raw_row_json",
		],
		order_by="idx asc",
	)

	wb = Workbook()
	ws = wb.active
	ws.title = "Errors"
	ws.append(
		[
			"Satır",
			"SKU",
			"Ürün Adı",
			"Hata Tipi",
			"Hata Mesajı",
			"Ham Satır (JSON)",
		]
	)
	for r in error_rows:
		ws.append(
			[
				r.get("row_number"),
				r.get("sku"),
				r.get("product_name"),
				r.get("error_type"),
				r.get("error_message"),
				r.get("raw_row_json"),
			]
		)

	buf = io.BytesIO()
	wb.save(buf)
	buf.seek(0)

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"bulk_import_errors_{job_name}.xlsx",
			"content": buf.read(),
			"is_private": 1,
			"decode": False,
			"attached_to_doctype": "Bulk Import Job",
			"attached_to_name": job_name,
		}
	)
	file_doc.insert(ignore_permissions=True)

	return {"file_url": file_doc.file_url, "file_name": file_doc.file_name}


# Şablon kolonları — İngilizce header (uluslararası satıcı uyumu).
# STATİK çekirdek + mini-PIM link kolonları. Tip-bazlı dinamik üretim YOK:
# her satıcı için her zaman aynı tam set indirilir (UX-KOLAY: tek statik şablon).
# Sıra: kimlik → marka/sınıf → mini-PIM link → fiyat → stok → kargo → diğer.
# Tuple: (header_en, canonical_field, example_value). Sayı formatı EN (1,245.00).
_TEMPLATE_CORE_COLUMNS_EN: tuple[tuple[str, str, str], ...] = (
	# [ÇEKİRDEK] kimlik + marka
	("SKU", "sku", "ABC-001"),
	("Product Name", "title", "Solvent Grade A 20L"),
	("Brand", "brand", "Petkim"),
	("Condition", "condition", "New"),
	# [mini-PIM LINK] Katalog yapısı (Brand zaten çekirdekte)
	("Product Type", "product_type", ""),
	("Product Family", "product_family", ""),
	("Attribute Set", "attribute_set", ""),
	# [ÇEKİRDEK] fiyat
	("Unit Price", "base_price", "1,245.00"),
	("Discounted Price", "selling_price", ""),
	("Currency", "currency", "TRY"),
	("Discount %", "discount_percentage", ""),
	# [ÇEKİRDEK] stok
	("Stock", "stock_qty", "150"),
	("Stock Unit", "stock_uom", "Piece"),
	("Min Order", "min_order_qty", "10"),
	("Max Order", "max_order_qty", "5000"),
	("Low Stock Threshold", "low_stock_threshold", "30"),
	("Sell In MOQ Multiples", "sell_in_moq_multiples", "No"),
	("Track Inventory", "track_inventory", "Yes"),
	("Allow Backorders", "allow_backorders", "No"),
	# [ÇEKİRDEK] kargo
	("Free Shipping", "is_free_shipping", "No"),
	("Shipping Weight", "shipping_weight", "22.5"),
	("Handling Days", "handling_days", "3"),
	("Ships From Country", "ships_from_country", "Turkey"),
	("Ships From City", "ships_from_city", "Istanbul"),
	("Country Of Origin", "country_of_origin", "Turkey"),
	# [ÇEKİRDEK] diğer
	("Barcode", "barcode", "8690000000001"),
	("Video", "video_url", ""),
	("Short Description", "short_description", "ISO 9001 certified"),
	("Description", "description", "Suitable for industrial use"),
)

# [VARYANT BLOĞU] varyantsız ürünlerde boş bırak. Çekirdek + betimleyici
# attribute kolonlarından sonra eklenir. Eksen başlıkları "Name", değer "Value".
# Canonical alanlar persister'ın okuduğu `variant_axis_N_type` / `_value` kalır.
_TEMPLATE_VARIANT_COLUMNS_EN: tuple[tuple[str, str, str], ...] = (
	("Parent SKU", "parent_sku", ""),
	("Variant SKU", "variant_sku", ""),
	("Variant Axis 1 Name", "variant_axis_1_type", ""),
	("Variant Axis 1 Value", "variant_axis_1_value", ""),
	("Variant Axis 2 Name", "variant_axis_2_type", ""),
	("Variant Axis 2 Value", "variant_axis_2_value", ""),
	("Variant Axis 3 Name", "variant_axis_3_type", ""),
	("Variant Axis 3 Value", "variant_axis_3_value", ""),
	("Variant Price", "variant_price", ""),
	("Variant Stock", "variant_stock", ""),
)


def _descriptive_attribute_columns() -> list[tuple[str, str, str]]:
	"""Betimleyici (varyant-ekseni-olmayan) attribute kolonlarını üret.

	STATİK: tip seçimine bakmaz. `include_in_bulk_template=1 AND is_variant_axis=0`
	olan tüm Product Attribute'ları toplar — her şablonda aynı set çıkar.
	Kolon başlığı `attribute_label_en`, teknik ad `attr:<name>`, örnek değer boş.
	`display_order` ile sıralanır (deterministik kolon sırası).

	Returns:
	    (header_en, canonical_field, "") tuple listesi.
	"""
	rows = frappe.get_all(
		"Product Attribute",
		filters={"include_in_bulk_template": 1, "is_variant_axis": 0},
		fields=["name", "attribute_label_en"],
		order_by="display_order asc, name asc",
	)
	columns: list[tuple[str, str, str]] = []
	for r in rows:
		header = r.get("attribute_label_en") or r.get("name")
		columns.append((header, f"attr:{r['name']}", ""))
	return columns


# Sütun eşleştirme dropdown'ı için grup ataması (Sözleşme §3).
# mini-PIM link kolonları çekirdekten ayrılır; geri kalan çekirdek "Temel".
_MINI_PIM_KEYS = frozenset({"product_type", "product_family", "attribute_set"})


def _mapping_target_groups() -> list[dict]:
	"""Gruplu canonical hedefler — Temel / mini-PIM / Özellikler / Varyant.

	"Sütun Eşleştirmelerim" ve Adım 2 manuel eşleme aynı kaynaktan beslenir.
	Statik şablon tuple'ları + betimleyici attribute'lardan üretilir.
	"""
	temel = [
		{"key": canonical, "label": header}
		for header, canonical, _ex in _TEMPLATE_CORE_COLUMNS_EN
		if canonical not in _MINI_PIM_KEYS
	]
	mini_pim = [
		{"key": canonical, "label": header}
		for header, canonical, _ex in _TEMPLATE_CORE_COLUMNS_EN
		if canonical in _MINI_PIM_KEYS
	]
	ozellikler = [
		{"key": canonical, "label": header} for header, canonical, _ex in _descriptive_attribute_columns()
	]
	varyant = [{"key": canonical, "label": header} for header, canonical, _ex in _TEMPLATE_VARIANT_COLUMNS_EN]

	groups = [
		{"label": _("Temel"), "fields": temel},
		{"label": _("Mini-PIM"), "fields": mini_pim},
	]
	if ozellikler:
		groups.append({"label": _("Özellikler"), "fields": ozellikler})
	groups.append({"label": _("Varyant"), "fields": varyant})
	return groups


@frappe.whitelist()
def get_mapping_targets() -> dict:
	"""Gruplu canonical eşleştirme hedefleri (UI dropdown kaynağı).

	Returns:
	    {"groups": [{"label": str, "fields": [{"key": str, "label": str}]}]}
	"""
	return {"groups": _mapping_target_groups()}


@frappe.whitelist()
def download_template(format: str = "xlsx", product_types: str = "") -> None:
	"""Ürün şablonu indir (İngilizce başlık + örnek satır).

	**STATİK şablon** (UX-KOLAY): her zaman aynı tam kolon seti üretilir —
	çekirdek + mini-PIM link + betimleyici attribute'lar + varyant bloğu.
	Tip seçimine göre dinamik kolon üretimi YOK. `product_types` parametresi
	geriye dönük uyumluluk için kabul edilir ama kolon setini etkilemez.

	`frappe.local.response` ile direkt binary stream döndürür.
	"""
	import io

	if format not in ("xlsx", "csv", "xml"):
		frappe.throw(_("Geçersiz format"))

	columns = list(_TEMPLATE_CORE_COLUMNS_EN)
	columns.extend(_descriptive_attribute_columns())
	columns.extend(_TEMPLATE_VARIANT_COLUMNS_EN)

	headers = [c[0] for c in columns]
	canonical = [c[1] for c in columns]
	example = [c[2] for c in columns]

	if format == "xlsx":
		from openpyxl import Workbook
		from openpyxl.styles import Font, PatternFill

		wb = Workbook()
		ws = wb.active
		ws.title = "Products"
		ws.append(headers)
		ws.append(example)
		# Header satırını koyu + arka plan
		for cell in ws[1]:
			cell.font = Font(bold=True)
			cell.fill = PatternFill("solid", fgColor="EDE9FE")
		# Örnek satır italik gri tonda
		for cell in ws[2]:
			cell.font = Font(italic=True, color="888888")
		# Kolon genişlikleri
		for i, h in enumerate(headers, 1):
			ws.column_dimensions[chr(64 + i) if i <= 26 else f"A{chr(64 + i - 26)}"].width = max(
				14, len(h) + 2
			)
		buf = io.BytesIO()
		wb.save(buf)
		buf.seek(0)
		content = buf.read()
		file_name = "tradehub_bulk_upload_template.xlsx"
	elif format == "csv":
		# UTF-8 BOM — Excel karakter kodlaması için. EN ayraç = virgül.
		csv_lines = [",".join(headers), ",".join(example)]
		content = b"\xef\xbb\xbf" + ("\n".join(csv_lines) + "\n").encode("utf-8")
		file_name = "tradehub_bulk_upload_template.csv"
	else:
		# XML için canonical (snake_case) tag adları kullanılır. Attribute kolonları
		# "attr:<code>" formatında; ":" XML tag adında namespace ayracı olduğu için
		# "attr_<code>" şeklinde güvenli tag'e çevrilir.
		xml_tags = [c.replace("attr:", "attr_", 1) for c in canonical]
		product_xml = "".join(f"  <{t}>{e}</{t}>\n" for t, e in zip(xml_tags, example, strict=False))
		content = (
			'<?xml version="1.0" encoding="UTF-8"?>\n'
			"<products>\n  <product>\n" + product_xml + "  </product>\n</products>\n"
		).encode("utf-8")
		file_name = "tradehub_bulk_upload_template.xml"

	frappe.local.response.filename = file_name
	frappe.local.response.filecontent = content
	frappe.local.response.type = "binary"


@frappe.whitelist()
def download_image_archive_sample() -> None:
	"""Gorsel arsivi (ZIP) ornegi indir — saticiya dogru klasor/adlandirma yapisini
	gosterir: SKU.jpg, SKU/ klasor galeri, SKU_1.jpg suffix. Icindeki gorseller
	yer tutucu (1x1 PNG). frappe.local.response ile binary stream doner."""
	import base64
	import io
	import zipfile

	png = base64.b64decode(
		"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
	)
	readme = (
		"GORSEL ARSIVI NASIL HAZIRLANIR\n"
		"==============================\n\n"
		"Gorseller urunun STOK KODU (SKU) ile eslesir. Tek ZIP icinde yukleyin.\n\n"
		"1) Tek gorsel:      URUN-001.jpg                  (dosya adi = SKU)\n"
		"2) Coklu (klasor):  URUN-002/1.jpg, URUN-002/2.jpg (klasor adi = SKU)\n"
		"3) Coklu (suffix):  URUN-003_1.jpg, URUN-003_2.jpg (SKU_1, SKU_2 ...)\n\n"
		"Varyantli urunlerde VARYANT SKU'su ile de eslesir:\n"
		"   URUN-004-KIRMIZI-40.jpg\n\n"
		"Desteklenen formatlar: .jpg .jpeg .png .webp\n"
		"Ornek gorseller yer tutucudur; kendi gorsellerinizle degistirin.\n"
	)
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
		zf.writestr("OKUBENI.txt", readme)
		zf.writestr("URUN-001.jpg", png)
		zf.writestr("URUN-002/1.jpg", png)
		zf.writestr("URUN-002/2.jpg", png)
		zf.writestr("URUN-003_1.jpg", png)
		zf.writestr("URUN-003_2.jpg", png)

	frappe.local.response.filename = "ornek_gorsel_arsivi.zip"
	frappe.local.response.filecontent = buf.getvalue()
	frappe.local.response.type = "binary"


@frappe.whitelist()
def retry_failed_rows(job_name: str) -> dict:
	"""Job'un sadece hatalı satırlarını yeniden işle. Yeni job oluştur.

	Strategy: orijinal data_file'dan sadece error row_number'lı satırları
	yeni bir xlsx olarak çıkar, yeni job ile enqueue et.
	"""
	import io

	from openpyxl import Workbook

	from tradehub_core.bulk_import.parsers import csv_parser, xlsx_parser, xml_parser

	original = frappe.get_doc("Bulk Import Job", job_name)
	original.check_permission("read")

	if original.status not in ("Failed", "Partial", "Completed"):
		frappe.throw(_("Sadece tamamlanmış job'lar için retry yapılabilir"))

	error_rows = frappe.get_all(
		"Bulk Import Job Error",
		filters={
			"parent": job_name,
			"parenttype": "Bulk Import Job",
			"error_type": ["!=", "duplicate"],
		},
		fields=["row_number"],
		order_by="idx asc",
	)
	error_row_numbers = {r["row_number"] for r in error_rows if r.get("row_number")}
	if not error_row_numbers:
		frappe.throw(_("Yeniden işlenecek hatalı satır yok"))

	file_path = _file_absolute_path_from_url(original.data_file)
	if original.file_format == "xlsx":
		headers, rows = xlsx_parser.parse_xlsx(
			file_path,
			original.sheet_name,
			int(original.header_row or 1),
		)
	elif original.file_format == "csv":
		headers, rows = csv_parser.parse_csv(file_path, int(original.header_row or 1))
	else:
		headers, rows = xml_parser.parse_xml(file_path)

	retry_rows = [r for i, r in enumerate(rows, 1) if i in error_row_numbers]
	if not retry_rows:
		frappe.throw(_("Hatalı satırlar yeniden okunamadı"))

	wb = Workbook()
	ws = wb.active
	ws.title = "Retry"
	ws.append(headers)
	for row in retry_rows:
		ws.append([row.get(h, "") for h in headers])
	buf = io.BytesIO()
	wb.save(buf)
	buf.seek(0)

	new_file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"retry_{job_name}.xlsx",
			"content": buf.read(),
			"is_private": 1,
			"decode": False,
		}
	)
	new_file.insert(ignore_permissions=True)

	return start_product_import(
		file_id=new_file.name,
		mode=original.update_mode or "insert_only",
		column_mapping=original.column_mapping,
		header_row=1,
	)


@frappe.whitelist()
def bulk_approve_listings_from_job(job_name: str) -> dict:
	"""Admin: Bu job'tan gelen tüm Pending Listing'leri Active yap."""
	roles = frappe.get_roles()
	if "System Manager" not in roles and "Marketplace Admin" not in roles:
		frappe.throw(_("Yetki hatası"))

	listings = frappe.get_all(
		"Listing",
		filters={"created_by_bulk_job": job_name, "status": "Pending"},
		pluck="name",
	)
	count = 0
	for listing_name in listings:
		try:
			doc = frappe.get_doc("Listing", listing_name)
			doc.status = "Active"
			doc.flags.from_admin = True
			doc.save(ignore_permissions=True)
			count += 1
		except Exception as e:
			frappe.log_error(
				f"bulk_approve_listings_from_job: {listing_name}: {e}",
				"bulk_approve_listings_from_job",
			)
	return {"approved": count, "total": len(listings)}


def _detect_format(filename: str) -> str:
	"""File adından format çıkar."""
	if not filename:
		frappe.throw(_("Dosya adı boş"))
	lower = filename.lower()
	if lower.endswith(".xlsx") or lower.endswith(".xls"):
		return "xlsx"
	if lower.endswith(".csv") or lower.endswith(".tsv"):
		return "csv"
	if lower.endswith(".xml"):
		return "xml"
	frappe.throw(_("Desteklenmeyen dosya formatı: {0}").format(filename))


def _file_absolute_path(file_doc) -> str:
	"""File doc → absolute disk path."""
	if hasattr(file_doc, "get_full_path"):
		try:
			return file_doc.get_full_path()
		except Exception:
			pass
	return _file_absolute_path_from_url(file_doc.file_url)


def _file_absolute_path_from_url(file_url: str) -> str:
	"""File URL → absolute disk path."""
	if not file_url:
		frappe.throw(_("Dosya URL boş"))
	if file_url.startswith("/files/"):
		return frappe.get_site_path("public", file_url.lstrip("/"))
	if file_url.startswith("/private/files/"):
		return frappe.get_site_path(file_url.lstrip("/"))
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	return file_doc.get_full_path()


@frappe.whitelist()
def discover_xml_schema(file_id: str) -> dict:
	"""XML dosyasını parse et, tüm tag yollarını ve örnek değerleri döndür.

	Returns: {
	    "tags": [
	        {"path": "urun.kod", "sample_values": ["ABC-001", "XYZ-002"], "count": 100}
	    ],
	    "total_items": int,
	    "suggested_mapping": {canonical_field: tag_path}  # canonical_fields ile fuzzy match
	}
	"""
	from tradehub_core.bulk_import.ingestion.resolver import resolve_columns
	from tradehub_core.bulk_import.parsers import xml_parser

	file_doc = frappe.get_doc("File", file_id)
	file_doc.check_permission("read")

	# Absolute path resolve — public ya da private dizinler için
	file_path = _file_absolute_path(file_doc)

	try:
		headers, rows = xml_parser.parse_xml(file_path)
	except Exception as e:
		# defusedxml parse hatası / okuma hatası — user'a anlamlı mesaj döndür,
		# stack trace'i log'a yaz.
		frappe.log_error(f"discover_xml_schema parse failed: {e}", "bulk_import.discover_xml_schema")
		frappe.throw(_("XML parse hatası: {0}").format(str(e)[:200]))

	# Tag başına ilk 3 benzersiz, boş olmayan örnek değer + non-empty count
	tags: list[dict] = []
	for h in headers:
		seen: set[str] = set()
		samples: list[str] = []
		# İlk 50 satırı tarayarak örnek topla — büyük XML'lerde tüm rows'u tarama
		for row in rows[:50]:
			v = row.get(h)
			if v is None:
				continue
			text = str(v).strip()
			if not text or text in seen:
				continue
			seen.add(text)
			samples.append(text[:100])
			if len(samples) >= 3:
				break
		tags.append(
			{
				"path": h,
				"sample_values": samples,
				"count": sum(1 for r in rows if r.get(h)),
			}
		)

	# Önerilen mapping mevcut resolver kaskadından (profile → regex → semantic) gelir
	seller = frappe.db.get_value(
		"Admin Seller Profile",
		{"owner": frappe.session.user},
		"name",
	)
	suggested: dict = {}
	if seller:
		try:
			resolve_result = resolve_columns(headers, seller_profile=seller)
			suggested = resolve_result.get("mapping") or {}
		except Exception as e:
			# Resolver patlarsa UI yine de tag listesini göstersin
			frappe.log_error(
				f"discover_xml_schema resolver failed: {e}",
				"bulk_import.discover_xml_schema",
			)
			suggested = {}

	return {
		"tags": tags,
		"total_items": len(rows),
		"suggested_mapping": suggested,
	}


@frappe.whitelist()
def save_xml_mapping(file_id: str, mapping: str, source_format: str = "xml") -> dict:
	"""XML mapping'i Seller Template Profile'a kaydet.

	Args:
	    file_id: XML File doctype name (fingerprint için header'ları çıkarmak için)
	    mapping: JSON string {canonical_field: tag_path}
	    source_format: "xml" (varsayılan; ileride aynı endpoint diğer formatlara da hizmet edebilir)
	"""
	from tradehub_core.bulk_import.ingestion import profile_store
	from tradehub_core.bulk_import.parsers import xml_parser

	seller = frappe.db.get_value(
		"Admin Seller Profile",
		{"owner": frappe.session.user},
		"name",
	)
	if not seller:
		frappe.throw(_("Satıcı profili bulunamadı"))

	try:
		mapping_dict = json.loads(mapping) if isinstance(mapping, str) else dict(mapping)
	except (ValueError, TypeError):
		frappe.throw(_("Geçersiz mapping JSON"))

	if not isinstance(mapping_dict, dict):
		frappe.throw(_("Geçersiz mapping JSON"))

	file_doc = frappe.get_doc("File", file_id)
	file_doc.check_permission("read")
	file_path = _file_absolute_path(file_doc)

	# Fingerprint için header listesi — aynı şema gelecekte aynı profile'a düşsün
	headers, _rows = xml_parser.parse_xml(file_path)

	profile_name = profile_store.save_profile(
		headers=headers,
		seller_profile=seller,
		mapping=mapping_dict,
		source_format=source_format,
	)
	return {"profile_name": profile_name}


# Bulk import için izin verilen dosya uzantıları + max boyut (byte)
_BULK_DATA_EXTS = frozenset({".xlsx", ".xls", ".csv", ".tsv", ".xml"})
_BULK_IMAGE_EXTS = frozenset({".zip"})
_BULK_DATA_MAX = 25 * 1024 * 1024  # 25 MB
_BULK_IMAGE_MAX = 200 * 1024 * 1024  # 200 MB


@frappe.whitelist()
def upload_bulk_file(file_name: str, file_content: str, kind: str = "data") -> dict:
	"""Bulk import için özel dosya upload endpoint'i — base64 JSON POST.

	**Neden ayrı endpoint?**
	- Frappe `upload_file` multipart/form-data CSRF mismatch (417) hatasına düşer
	  → satıcı bulk yükleme tamamen başarısız oluyor. Base64 JSON POST ile bu
	  sorun ortadan kalkar (uploadCertDocument'taki aynı pattern).
	- `security.reject_unsafe_files` `.xml` uzantısını yasaklar (XSS koruması).
	  Bulk import için XML legitimate format — `doc.flags.bulk_import_safe`
	  ile security hook bypass edilir (kontrollü kanal).

	Args:
	    file_name: Orijinal dosya adı (uzantı zorunlu).
	    file_content: data URL formatında base64 (`data:...;base64,<content>`).
	    kind: "data" (xlsx/csv/xml) veya "images" (zip).

	Returns:
	    {"file_id": File.name, "file_url": file_url, "file_name": file_name}
	"""
	import base64

	if not file_name or not file_content:
		frappe.throw(_("Dosya adı ve içeriği zorunlu"))

	if kind not in ("data", "images"):
		frappe.throw(_("Geçersiz dosya tipi"))

	# Uzantı kontrolü
	ext = os.path.splitext(file_name)[1].lower()
	allowed = _BULK_DATA_EXTS if kind == "data" else _BULK_IMAGE_EXTS
	if ext not in allowed:
		frappe.throw(
			_("Bu dosya türü desteklenmiyor: {0}. İzinli: {1}").format(ext, ", ".join(sorted(allowed)))
		)

	# Base64 decode — data URL prefix'i (varsa) çıkar.
	# FileReader.readAsDataURL her zaman `data:<mime>;base64,<content>` döner.
	# Önceki bug: content[:50] içinde "," arıyorduk — xlsx MIME 60+ karakter
	# olduğu için prefix split başarısızdı.
	content = file_content
	if content.startswith("data:") and "," in content:
		content = content.split(",", 1)[1]
	try:
		raw = base64.b64decode(content)
	except Exception:
		frappe.throw(_("Dosya içeriği base64 değil"))

	# Boyut kontrolü
	max_size = _BULK_DATA_MAX if kind == "data" else _BULK_IMAGE_MAX
	if len(raw) == 0:
		frappe.throw(
			_(
				"Dosya boş (0 byte) — tarayıcı drag-drop'ta dosya referansını "
				"kaybetmiş olabilir. Lütfen sayfayı tam yenileyin (Ctrl+Shift+R) "
				"ve dosyayı tekrar yükleyin."
			)
		)
	if len(raw) > max_size:
		frappe.throw(
			_("Dosya çok büyük: {0} MB (max {1} MB)").format(
				len(raw) // (1024 * 1024), max_size // (1024 * 1024)
			)
		)

	# Satıcı yetkisi
	seller = frappe.db.get_value(
		"Admin Seller Profile",
		{"owner": frappe.session.user},
		"name",
	)
	if not seller and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Satıcı profili bulunamadı"))

	# Frappe v15 utility ile dosya kaydet.
	# `frappe.flags.in_bulk_import_upload` security hook bypass'ı için.
	from frappe.utils.file_manager import save_file

	frappe.flags.in_bulk_import_upload = True
	try:
		file_doc = save_file(
			fname=file_name,
			content=raw,
			dt="",
			dn="",
			decode=False,
			is_private=0,
		)
	except Exception as e:
		# DEBUG: tam stack trace Error Log'a düşsün ki sorunu görelim
		frappe.log_error(
			title=f"Bulk Upload save_file failed: {type(e).__name__}",
			message=frappe.get_traceback()
			+ f"\n\nfile_name={file_name}\nkind={kind}\nsize={len(raw)}\nuser={frappe.session.user}",
		)
		raise
	finally:
		frappe.flags.in_bulk_import_upload = False

	return {
		"file_id": file_doc.name,
		"file_url": file_doc.file_url,
		"file_name": file_doc.file_name,
	}

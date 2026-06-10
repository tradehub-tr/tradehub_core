"""Seller XML Feed zamanlanmis cekme — scheduler entegrasyonu.

`process_due_feeds` hourly scheduler tarafindan cagrilir; vadesi gelen feed'leri
bulur ve her birini `run_feed_once` ile long-queue'ya atar. `run_feed_once` feed'i
SSRF-korumali indirir, defusedxml ile parse eder, bir Bulk Import Job olusturur ve
mevcut bulk_import runner akisina enqueue eder.
"""

import tempfile

import frappe
from frappe.utils import add_to_date, now, now_datetime

from tradehub_core.bulk_import import feed_security
from tradehub_core.bulk_import.parsers import xml_parser
from tradehub_core.utils.notify import notify

MAX_CONSECUTIVE_FAILURES = 3

# Paket 2 — XML Feed entitlement flag (Subscription Plan capability_flags).
XML_FEED_FEATURE = "feature.import.xml_feed"


def run_feed_once(feed_name: str) -> None:
	"""Tek bir Seller XML Feed'i cek, parse et ve Bulk Import Job olarak enqueue et.

	Basari: last_fetch/last_status/last_item_count guncellenir, ardisik hata sayaci
	sifirlanir. Hata: last_status hata mesajiyla yazilir, sayac artar;
	MAX_CONSECUTIVE_FAILURES esigine ulasilirsa feed devre disi birakilir ve
	(feed.notify_on_error ise) saticiya bildirim gonderilir.
	"""
	feed = frappe.get_doc("Seller XML Feed", feed_name)

	try:
		raw = feed_security.fetch_feed(feed.feed_url)

		# defusedxml ET.parse XXE'ye karsi korumali; gecici dosyaya yazip parse et.
		with tempfile.NamedTemporaryFile(suffix=".xml", delete=True) as tmp:
			tmp.write(raw)
			tmp.flush()
			_headers, rows = xml_parser.parse_xml(tmp.name)

		item_count = len(rows)
		_enqueue_import_job(feed, raw)

		feed.db_set("last_fetch", now(), update_modified=False)
		feed.db_set("last_status", "success", update_modified=False)
		feed.db_set("last_item_count", item_count, update_modified=False)
		feed.db_set("consecutive_failures", 0, update_modified=False)
		frappe.db.commit()
	except Exception as exc:
		_handle_feed_failure(feed, exc)


def _enqueue_import_job(feed, raw: bytes) -> None:
	"""Feed icerigini File olarak kaydet, Bulk Import Job olustur ve runner'i enqueue et."""
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{feed.name}.xml",
			"is_private": 1,
			"content": raw,
		}
	)
	# security.reject_unsafe_files `.xml` uzantısını XSS gerekçesiyle bloklar;
	# bu kontrollü kanal (SSRF-doğrulanmış feed + defusedxml parse) için bypass.
	# upload_bulk_file ile aynı desen (bkz. bulk_import/api.py in_bulk_import_upload).
	file_doc.flags.bulk_import_safe = True
	file_doc.insert(ignore_permissions=True)

	job = frappe.new_doc("Bulk Import Job")
	job.seller_profile = feed.seller_profile
	# Run-history: bu job hangi feed'den dogdu — list_feed_runs bu alanla filtreler.
	job.source_feed = feed.name
	job.data_file = file_doc.file_url
	job.file_format = "xml"
	job.update_mode = feed.update_mode if feed.update_mode in ("insert_only", "upsert") else "upsert"
	# B2: feed.column_mapping normalde boş kalır (SellerFeedView elle eşleme
	# göndermez). Boş bırakıldığında runner 4 katmanlı resolver'ı otomatik
	# çalıştırır (bkz. runner.run); satıcı manuel eşleme yapmaz.
	job.column_mapping = feed.column_mapping
	job.header_row = 1
	job.status = "Queued"
	job.insert(ignore_permissions=True)

	# `job_name` frappe.enqueue'un reserved kwarg'i (RQ job ID) — runner imzasi
	# `bulk_job_name` kullanir (bkz. bulk_import/api.py start_product_import).
	frappe.enqueue(
		"tradehub_core.bulk_import.runner.run",
		queue="long",
		timeout=3600,
		enqueue_after_commit=True,
		bulk_job_name=job.name,
	)


def _handle_feed_failure(feed, exc: Exception) -> None:
	"""Hata durumunda sayaci artir, esik asilirsa feed'i devre disi birak + bildir."""
	frappe.log_error(title=f"Seller XML Feed cekme hatasi: {feed.name}")

	failures = (feed.consecutive_failures or 0) + 1
	message = str(exc)[:200]
	feed.db_set("last_fetch", now(), update_modified=False)
	feed.db_set("last_status", f"error: {message}", update_modified=False)
	feed.db_set("consecutive_failures", failures, update_modified=False)

	if failures >= MAX_CONSECUTIVE_FAILURES:
		feed.db_set("enabled", 0, update_modified=False)
		owner = frappe.db.get_value("Admin Seller Profile", feed.seller_profile, "owner")
		if owner:
			notify(
				recipient_user=owner,
				type="bulk_import",
				title="XML Feed devre disi birakildi",
				message=(
					f"{feed.feed_url} adresinden alinan feed {failures} kez ust uste "
					f"basarisiz oldu ve otomatik olarak devre disi birakildi. Son hata: {message}"
				),
				reference_doctype="Seller XML Feed",
				reference_name=feed.name,
				send_email=bool(feed.notify_on_error),
			)

	frappe.db.commit()


def process_due_feeds() -> None:
	"""Vadesi gelen tum etkin feed'leri bul ve her birini long-queue'ya enqueue et.

	Vade kosulu: enabled=1, fetch_hour suanki saate esit ve (last_fetch bos veya
	son 24 saatten eski). Sistem isi oldugu icin get_all kullaniliyor (tum
	saticilarin feed'lerini permission filtresi olmadan tarar).
	"""
	from tradehub_core.entitlement import has_feature

	current_hour = now_datetime().hour
	day_ago = add_to_date(now_datetime(), hours=-24)

	feeds = frappe.get_all(
		"Seller XML Feed",
		filters={"enabled": 1, "fetch_hour": current_hour},
		fields=["name", "last_fetch", "seller_profile"],
	)

	for feed in feeds:
		if feed.last_fetch and feed.last_fetch >= day_ago:
			continue
		# Plan dustuyse (entitlement kaybedildi) feed'i sessizce atla — kayit
		# devre disi birakilmaz, satici plani yukseltirse otomatik devam eder.
		if not has_feature(feed.seller_profile, XML_FEED_FEATURE):
			continue
		frappe.enqueue(
			"tradehub_core.bulk_import.feed_scheduler.run_feed_once",
			queue="long",
			timeout=3600,
			feed_name=feed.name,
		)

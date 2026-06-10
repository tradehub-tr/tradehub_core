"""Seller XML Feed — whitelisted REST endpoints (Frappe v15).

Satici, XML feed URL'lerini test eder, kaydeder ve onceki yuklemeleri yonetir.
Yetki modeli:
  - Satici endpoint'leri (test/save/list/delete/preview/run_now) yalnizca
    kendi Admin Seller Profile'ina bagli Seller XML Feed kayitlarina dokunur.
  - Admin endpoint'i (list_all_feeds) System Manager / Marketplace Admin gerektirir.

Feed cekme SSRF korumasi feed_security.fetch_feed icinde; XML parse defusedxml
tabanli xml_parser.parse_xml ile (XXE korumali).
"""

import json
import os
import tempfile

import frappe
from frappe import _

FEED_DOCTYPE = "Seller XML Feed"
PREVIEW_SAMPLE_LIMIT = 5
_ADMIN_ROLES = {"System Manager", "Marketplace Admin"}

# Paket 2 — XML Feed entitlement flag (Subscription Plan capability_flags).
XML_FEED_FEATURE = "feature.import.xml_feed"


def _require_xml_feed_feature(seller: str) -> None:
	"""Saticinin aktif plani XML Feed ozelligine sahip degilse nazik 403 firlat."""
	from tradehub_core.entitlement import check_feature_or_throw

	check_feature_or_throw(seller, XML_FEED_FEATURE, action_description=_("XML Feed"))


def _current_seller() -> str:
	"""Oturum kullanicisinin Admin Seller Profile name'ini dondur, yoksa throw."""
	seller = frappe.db.get_value(
		"Admin Seller Profile",
		{"owner": frappe.session.user},
		"name",
	)
	if not seller:
		frappe.throw(_("Satıcı profili bulunamadı"))
	return seller


def _get_own_feed(feed_name: str):
	"""Feed dokumanini cek ve satici sahipligini dogrula.

	Marketplace Admin / System Manager tum feed'lere erisebilir; satici yalnizca
	kendi seller_profile'ina bagli feed'e.
	"""
	doc = frappe.get_doc(FEED_DOCTYPE, feed_name)
	roles = set(frappe.get_roles())
	if roles & _ADMIN_ROLES:
		return doc
	if doc.seller_profile != _current_seller():
		frappe.throw(_("Bu feed'e erişim yetkiniz yok"), frappe.PermissionError)
	return doc


def _parse_feed_bytes(raw: bytes) -> tuple[list[str], list[dict]]:
	"""Ham feed baytlarini gecici dosyaya yazip defusedxml ile parse et.

	xml_parser.parse_xml dosya yolu bekler; fetch_feed ise bayt dondurur.
	Gecici dosya her durumda silinir.
	"""
	from tradehub_core.bulk_import.parsers import xml_parser

	tmp_path = ""
	try:
		with tempfile.NamedTemporaryFile(mode="wb", suffix=".xml", delete=False) as tmp:
			tmp.write(raw)
			tmp_path = tmp.name
		return xml_parser.parse_xml(tmp_path)
	finally:
		if tmp_path and os.path.exists(tmp_path):
			os.remove(tmp_path)


@frappe.whitelist()
def test_feed_url(feed_url: str) -> dict:
	"""Feed URL'sini cek + parse et, urun sayisini dondur.

	Returns: {"ok": bool, "item_count": int, "error": str}
	"""
	_require_xml_feed_feature(_current_seller())

	from tradehub_core.bulk_import import feed_security

	try:
		raw = feed_security.fetch_feed(feed_url)
		_headers, rows = _parse_feed_bytes(raw)
	except Exception as e:
		# SSRF reddi (frappe.throw), indirme hatasi veya XML parse hatasi —
		# kullaniciya mesaj, stack trace log'a.
		frappe.log_error(
			f"test_feed_url failed: {e}",
			"bulk_import.feed_api.test_feed_url",
		)
		return {"ok": False, "item_count": 0, "error": str(e)[:300]}

	return {"ok": True, "item_count": len(rows), "error": ""}


@frappe.whitelist()
def save_feed(payload: str | dict) -> dict:
	"""Satici feed'ini olustur veya guncelle (kendi seller_profile'i altinda).

	payload alanlari: name (opsiyonel, guncelleme icin), feed_url, enabled,
	fetch_hour, update_mode, column_mapping, notify_on_error.
	"""
	seller = _current_seller()
	_require_xml_feed_feature(seller)
	data = json.loads(payload) if isinstance(payload, str) else dict(payload)

	feed_url = (data.get("feed_url") or "").strip()
	if not feed_url:
		frappe.throw(_("Feed URL zorunludur"))

	name = data.get("name")
	if name:
		doc = _get_own_feed(name)
	else:
		doc = frappe.new_doc(FEED_DOCTYPE)
		doc.seller_profile = seller

	doc.feed_url = feed_url
	doc.update_mode = (
		data["update_mode"] if data.get("update_mode") in ("upsert", "insert_only") else "upsert"
	)
	if data.get("column_mapping") is not None:
		mapping = data["column_mapping"]
		doc.column_mapping = mapping if isinstance(mapping, str) else json.dumps(mapping)
	doc.enabled = 1 if data.get("enabled") else 0
	doc.notify_on_error = 0 if data.get("notify_on_error") is False else 1

	try:
		doc.fetch_hour = int(data.get("fetch_hour", 3))
	except (ValueError, TypeError):
		doc.fetch_hour = 3

	doc.save()
	return {"name": doc.name, "enabled": doc.enabled, "feed_url": doc.feed_url}


@frappe.whitelist()
def list_feeds() -> list:
	"""Saticinin kendi feed'lerini dondur."""
	seller = _current_seller()
	return frappe.get_list(
		FEED_DOCTYPE,
		filters={"seller_profile": seller},
		fields=[
			"name",
			"feed_url",
			"enabled",
			"fetch_hour",
			"update_mode",
			"last_fetch",
			"last_status",
			"last_item_count",
			"consecutive_failures",
		],
		order_by="modified desc",
	)


@frappe.whitelist()
def delete_feed(name: str) -> dict:
	"""Saticinin kendi feed'ini sil."""
	doc = _get_own_feed(name)
	frappe.delete_doc(FEED_DOCTYPE, doc.name)
	return {"ok": True, "name": doc.name}


@frappe.whitelist()
def preview_feed(feed_name: str) -> dict:
	"""Feed'i cek + parse et, dry-run ozeti dondur.

	Returns: {"item_count", "detected_headers", "sample_rows"}
	"""
	from tradehub_core.bulk_import import feed_security

	doc = _get_own_feed(feed_name)

	try:
		raw = feed_security.fetch_feed(doc.feed_url)
		headers, rows = _parse_feed_bytes(raw)
	except Exception as e:
		frappe.log_error(
			f"preview_feed failed for {feed_name}: {e}",
			"bulk_import.feed_api.preview_feed",
		)
		frappe.throw(_("Feed önizlemesi başarısız: {0}").format(str(e)[:200]))

	return {
		"feed_name": doc.name,
		"item_count": len(rows),
		"detected_headers": headers,
		"sample_rows": rows[:PREVIEW_SAMPLE_LIMIT],
	}


FEED_RUNS_DEFAULT_LIMIT = 20
FEED_RUNS_MAX_LIMIT = 100


@frappe.whitelist()
def list_feed_runs(feed_name: str, limit: int = FEED_RUNS_DEFAULT_LIMIT) -> dict:
	"""Bir feed'in çalıştırma geçmişi + sağlık özeti.

	Run-record olarak Bulk Import Job'lar kullanılır (source_feed=feed). Ayrı
	bir DocType yok. Sağlık = feed'in consecutive_failures + son durumları.

	Returns:
	    {
	        "feed_name", "consecutive_failures", "last_status", "last_fetch",
	        "runs": [{"job", "creation", "status", "total_rows", "inserted",
	                  "updated", "skipped", "error_count", "duration_seconds"}]
	    }
	"""
	doc = _get_own_feed(feed_name)

	try:
		limit_int = int(limit)
	except (ValueError, TypeError):
		limit_int = FEED_RUNS_DEFAULT_LIMIT
	limit_int = max(1, min(limit_int, FEED_RUNS_MAX_LIMIT))

	runs = frappe.get_list(
		"Bulk Import Job",
		filters={"source_feed": doc.name},
		fields=[
			"name as job",
			"creation",
			"status",
			"total_rows",
			"inserted_count as inserted",
			"updated_count as updated",
			"skipped_count as skipped",
			"error_count",
			"duration_seconds",
		],
		order_by="creation desc",
		limit=limit_int,
	)

	return {
		"feed_name": doc.name,
		"consecutive_failures": doc.consecutive_failures or 0,
		"last_status": doc.last_status,
		"last_fetch": doc.last_fetch,
		"runs": runs,
	}


@frappe.whitelist()
def feed_dry_run(feed_name: str) -> dict:
	"""Feed'i çek + parse et, eklenecek/güncellenecek/atlanacak özetini döndür.

	Persist YAPMAZ. dry_run_preview ile aynı çekirdek (_compute_dry_run) çalışır;
	tek fark girdinin dosya yerine feed URL'sinden gelmesi.
	"""
	from tradehub_core.bulk_import import feed_security
	from tradehub_core.bulk_import.api import _compute_dry_run
	from tradehub_core.bulk_import.ingestion import resolver

	doc = _get_own_feed(feed_name)
	_require_xml_feed_feature(doc.seller_profile)

	try:
		raw = feed_security.fetch_feed(doc.feed_url)
		headers, rows = _parse_feed_bytes(raw)
	except Exception as e:
		frappe.log_error(
			f"feed_dry_run failed for {feed_name}: {e}",
			"bulk_import.feed_api.feed_dry_run",
		)
		frappe.throw(_("Feed deneme çalıştırması başarısız: {0}").format(str(e)[:200]))

	# Feed'de manuel eşleme yoksa 4 katmanlı resolver otomatik çalışır
	# (SellerFeedView elle mapping göndermez — bkz. feed_scheduler._enqueue_import_job).
	resolution: dict = {}
	mapping: dict = {}
	if doc.column_mapping:
		try:
			mapping = json.loads(doc.column_mapping)
		except (ValueError, TypeError):
			mapping = {}
	if not mapping:
		resolution = resolver.resolve_columns(headers, doc.seller_profile)
		mapping = resolution.get("mapping", {})

	update_mode = doc.update_mode if doc.update_mode in ("insert_only", "upsert") else "upsert"
	return _compute_dry_run(headers, rows, mapping, resolution, doc.seller_profile, update_mode)


@frappe.whitelist()
def run_now(feed_name: str) -> dict:
	"""Feed'i hemen calistir — feed_scheduler.run_feed_once'i kuyruga al.

	feed_scheduler modulu sonraki ajan tarafindan yazilacak; import'u fonksiyon
	icinde tutuyoruz ki modul henuz yokken bu dosya yine de import edilebilsin.
	"""
	doc = _get_own_feed(feed_name)
	_require_xml_feed_feature(doc.seller_profile)

	frappe.enqueue(
		"tradehub_core.bulk_import.feed_scheduler.run_feed_once",
		queue="long",
		timeout=3600,
		enqueue_after_commit=True,
		feed_name=doc.name,
	)
	return {"ok": True, "feed_name": doc.name, "status": "queued"}


@frappe.whitelist()
def list_all_feeds() -> list:
	"""Admin — tum saticilarin feed'lerini durumlariyla dondur.

	Yetki: System Manager / Marketplace Admin.
	"""
	frappe.only_for(list(_ADMIN_ROLES))
	return frappe.get_list(
		FEED_DOCTYPE,
		fields=[
			"name",
			"seller_profile",
			"feed_url",
			"enabled",
			"fetch_hour",
			"update_mode",
			"last_fetch",
			"last_status",
			"last_item_count",
			"consecutive_failures",
		],
		order_by="modified desc",
	)

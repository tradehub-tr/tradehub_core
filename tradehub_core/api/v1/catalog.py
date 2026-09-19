"""Ürün API'si (MOGEM-665) — `upsert_products` · `update_stock` · `changes`.

Sözleşme (docs/URUN-API-KILAVUZU.md):
- Kimlik: `Authorization: Bearer <jeton>` (`public_api.token`, client_credentials).
- Her istek mağaza sahibinin oturumuyla koşar (`_catalog_auth.catalog_context`).
- Ürün yazma dosya içe aktarma boru hattını (`bulk_import.persister`) yeniden
  kullanır: aynı doğrulama, aynı ECA kuralları, aynı `Bulk Import Job` kaydı
  (`source = "api"`) — panelde ayrı süzgeçle görünür ve toplu onaylanır.

Satır sonuçları `status ∈ {created, updated, rejected}`; ret sebebi `code` +
`message`; başarılı satırların uyarıları `warnings: [{code, message}]`.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import cint, flt, now, time_diff_in_seconds

from tradehub_core.api.listing import _INVISIBLE_STATUSES, invalidate_listing_cache
from tradehub_core.api.v1._catalog_auth import catalog_context
from tradehub_core.bulk_import import image_url_ingest, persister
from tradehub_core.bulk_import.image_matcher import normalize_sku_key
from tradehub_core.bulk_import.runner import _record_error, _record_warnings
from tradehub_core.entitlement.core import EntitlementError
from tradehub_core.utils import stock as stock_utils
from tradehub_core.utils.seo_content import check_description, check_title

MAX_PRODUCTS_PER_CALL = 100
MAX_STOCK_ITEMS_PER_CALL = 500
MAX_CHANGES_PAGE = 500
MAX_IMAGES_PER_PRODUCT = 10
LOCK_TTL_SECONDS = 120

# API alanı → persister canonical anahtarı (sku → seller_sku çevirisini persister yapar).
FIELD_MAP: dict[str, str] = {
	"sku": "sku",
	"title": "title",
	"short_description": "short_description",
	"description": "description",
	"list_price": "base_price",
	"price": "selling_price",
	"currency": "currency",
	"stock": "stock_qty",
	"unit": "stock_uom",
	"brand": "brand",
	"category": "category",
	"product_category": "product_category",
	"product_type": "product_type",
	"condition": "condition",
	"barcode": "barcode",
	"tags": "tags",
	"video_url": "video_url",
	"min_order_qty": "min_order_qty",
	"max_order_qty": "max_order_qty",
	"low_stock_threshold": "low_stock_threshold",
	"track_inventory": "track_inventory",
	"allow_backorders": "allow_backorders",
	"shipping_weight": "shipping_weight",
	"handling_days": "handling_days",
	"country_of_origin": "country_of_origin",
}
# Listing alanı olmayan, ayrıca işlenen anahtarlar.
_SPECIAL_KEYS = {"images", "variants", "attributes"}
_NUMERIC_KEYS = {"list_price", "price", "stock", "min_order_qty", "max_order_qty", "shipping_weight"}
# Sonuç satırında hangi API alanı hangi kodla raporlanır.
_JOB_MAPPING = {"sku": "sku", "title": "title"}


class CatalogBusyError(frappe.ValidationError):
	"""Aynı mağazada eş zamanlı ikinci işlem — istemci biraz sonra tekrar dener."""

	http_status_code = 409


class CatalogUnavailableError(frappe.ValidationError):
	"""Kilit altyapısı (Redis) yanıt vermiyor — istemci sonra tekrar dener (503)."""

	http_status_code = 503


def _sku_str(v) -> str:
	"""SKU yalnız düz metin/sayı; nesne-liste gibi değerler ("{'a': 1}") SKU sayılmaz."""
	if isinstance(v, bool) or not isinstance(v, str | int | float):
		return ""
	return str(v).strip()


class _Ret(Exception):
	def __init__(self, code: str, message: str, field: str | None = None):
		super().__init__(message)
		self.code, self.message, self.field = code, message, field


# ─────────────────────────────────────────────────────────────────
# Kilit
# ─────────────────────────────────────────────────────────────────


@contextmanager
def store_lock(seller: str, op: str):
	"""Mağaza başına tek `op` (upsert | stock). Redis SET NX + TTL; çıkışta bırakılır.

	TTL, çökme durumunda kilidin asılı kalmaması için; normal yol `finally` ile siler.
	"""
	cache = frappe.cache()
	key = cache.make_key(f"catalog_lock:{seller}:{op}")
	try:
		alindi = cache.set(key, frappe.generate_hash(length=8), nx=True, ex=LOCK_TTL_SECONDS)
	except Exception:
		# Kilit olmadan yazmak eş zamanlılık sözünü bozar → fail-closed ama anlaşılır (503),
		# 500 değil. Hız sınırının aksine burada fail-open bilinçli olarak SEÇİLMEDİ.
		frappe.log_error(title="Catalog store lock Redis failed", message=f"{seller}:{op}")
		raise CatalogUnavailableError(
			_("Kilit altyapısı geçici olarak yanıt vermiyor; lütfen biraz sonra tekrar deneyin.")
		)
	if not alindi:
		raise CatalogBusyError(
			_("Bu mağaza için başka bir {0} işlemi sürüyor; lütfen biraz sonra tekrar deneyin.").format(op)
		)
	try:
		yield
	finally:
		cache.delete(key)


# ─────────────────────────────────────────────────────────────────
# Girdi doğrulama
# ─────────────────────────────────────────────────────────────────


def _parse_list(raw, limit: int, label: str) -> list:
	if isinstance(raw, str):
		try:
			raw = json.loads(raw)
		except ValueError:
			frappe.throw(_("Gövde geçerli JSON değil"), frappe.ValidationError)
	if not isinstance(raw, list) or not raw:
		frappe.throw(_("`{0}` en az bir öğe içeren bir liste olmalı").format(label), frappe.ValidationError)
	if len(raw) > limit:
		frappe.throw(
			_("Tek istekte en fazla {0} öğe gönderilebilir (gönderilen: {1})").format(limit, len(raw)),
			frappe.ValidationError,
		)
	return raw


def _parse_products(products) -> list:
	return _parse_list(products, MAX_PRODUCTS_PER_CALL, "products")


def _sayi(p: dict, key: str) -> float | None:
	"""Sayısal alan: yok/None → None; parse edilemeyen → INVALID_NUMBER."""
	v = p.get(key)
	if v is None or v == "":
		return None
	if isinstance(v, bool):
		raise _Ret("INVALID_NUMBER", _("{0} sayı olmalı").format(key), key)
	n = persister._normalize_numeric(v)
	if not isinstance(n, int | float):
		raise _Ret("INVALID_NUMBER", _("{0} sayı olmalı: {1}").format(key, v), key)
	return float(n)


def _fiyat_kurali(list_price, price, existing: dict | None) -> None:
	"""Satış fiyatı liste fiyatını geçemez — gönderilmeyen taraf mevcut değerden okunur."""
	liste = list_price if list_price is not None else (flt(existing["base_price"]) if existing else None)
	satis = price if price is not None else (flt(existing["selling_price"]) if existing else None)
	if liste and satis and satis > liste:
		raise _Ret(
			"PRICE_RULE",
			_("Satış fiyatı ({0}) liste fiyatını ({1}) geçemez").format(satis, liste),
			"price",
		)


def _varyantlar(p: dict, warnings: list[dict], is_new: bool) -> list[dict]:
	raw = p.get("variants")
	if raw in (None, "", []):
		return []
	if not isinstance(raw, list) or not all(isinstance(v, dict) for v in raw):
		raise _Ret("VARIANT_INVALID", _("`variants` nesne listesi olmalı"), "variants")
	if not is_new:
		warnings.append(
			{
				"code": "VARIANTS_NOT_UPDATED",
				"message": _(
					"Varyantlar yalnız ürün oluşturulurken yazılır; mevcut ürünün varyantları değiştirilmedi"
				),
			}
		)
		return []
	rows: list[dict] = []
	for i, v in enumerate(raw, 1):
		axes = v.get("axes")
		if not isinstance(axes, dict) or not any(
			str(k).strip() and str(val).strip() for k, val in axes.items()
		):
			raise _Ret(
				"VARIANT_INVALID", _("Varyant {0}: `axes` en az bir eksen içermeli").format(i), "variants"
			)
		price = _sayi(v, "price")
		stock = _sayi(v, "stock")
		if price is not None and price < 0:
			raise _Ret("PRICE_NEGATIVE", _("Varyant {0}: fiyat negatif olamaz").format(i), "variants")
		if stock is not None and stock < 0:
			raise _Ret("STOCK_NEGATIVE", _("Varyant {0}: stok negatif olamaz").format(i), "variants")
		row = {
			"variant_sku": str(v.get("sku") or "").strip(),
			"variant_price": price if price is not None else 0,
			"variant_stock": stock if stock is not None else 0,
		}
		for t, val in axes.items():
			if str(t).strip() and str(val).strip():
				row[f"axis:{str(t).strip()}"] = str(val).strip()
		rows.append(row)
	return rows


def _gorseller(p: dict, warnings: list[dict]) -> list[str]:
	raw = p.get("images")
	if raw in (None, "", []):
		return []
	if not isinstance(raw, list) or not all(isinstance(u, str) for u in raw):
		raise _Ret("IMAGES_INVALID", _("`images` URL listesi olmalı"), "images")
	urls = [u.strip() for u in raw if u and u.strip()]
	if len(urls) > MAX_IMAGES_PER_PRODUCT:
		warnings.append(
			{
				"code": "IMAGE_LIMIT",
				"message": _("En fazla {0} görsel alınır; {1} görsel atlandı").format(
					MAX_IMAGES_PER_PRODUCT, len(urls) - MAX_IMAGES_PER_PRODUCT
				),
			}
		)
		urls = urls[:MAX_IMAGES_PER_PRODUCT]
	return urls


def _satir_hazirla(p: dict, existing: dict | None) -> tuple[dict, list[dict], list[str], list[dict]]:
	"""Tek ürünü doğrula → (persister satırı, varyant satırları, görsel URL'leri, uyarılar).

	Ret durumunda `_Ret` fırlatır. Boş/None alanlar satıra yazılmaz (persister
	mevcut değeri korur); stok 0 sayıdır ve yazılır.
	"""
	if not isinstance(p, dict):
		raise _Ret("INVALID_PRODUCT", _("Ürün bir nesne olmalı"))
	warnings: list[dict] = []
	is_new = existing is None
	sku = _sku_str(p.get("sku"))
	if not sku:
		raise _Ret("SKU_REQUIRED", _("`sku` zorunlu"), "sku")
	title = str(p.get("title") or "").strip()
	if is_new and not title:
		raise _Ret("TITLE_REQUIRED", _("Yeni üründe `title` zorunlu"), "title")

	list_price = _sayi(p, "list_price")
	price = _sayi(p, "price")
	stock = _sayi(p, "stock")
	if is_new and list_price is None:
		raise _Ret("PRICE_REQUIRED", _("Yeni üründe `list_price` zorunlu"), "list_price")
	if (list_price is not None and list_price < 0) or (price is not None and price < 0):
		raise _Ret("PRICE_NEGATIVE", _("Fiyat negatif olamaz"), "price")
	if stock is not None and stock < 0:
		raise _Ret("STOCK_NEGATIVE", _("Stok negatif olamaz"), "stock")
	_fiyat_kurali(list_price, price, existing)
	# SEO içerik kuralı — `Listing._validate_seo_content` ile aynı kaynak (utils.seo_content).
	# Listing.validate bu kuralı test/migrate bayraklarında ATLAR; gerçek HTTP'de uygulanır
	# (15 Eyl e2e ölçümü: 5 karakterlik başlık VALIDATION ile düştü). API sözleşmesi bayrağa
	# bağlı olmasın diye kural burada her koşulda ve açık kodla uygulanır.
	if title:
		ok, msg = check_title(title)
		if not ok:
			raise _Ret("SEO_TITLE", msg, "title")
	desc = p.get("description")
	if is_new or desc not in (None, ""):
		ok, msg = check_description(desc)
		if not ok:
			raise _Ret("SEO_DESCRIPTION", msg, "description")

	row: dict = {"sku": sku}
	for api_key, value in p.items():
		if api_key in ("sku",) or api_key in _SPECIAL_KEYS:
			continue
		if api_key not in FIELD_MAP:
			warnings.append(
				{"code": "UNKNOWN_FIELD", "message": _("Bilinmeyen alan yok sayıldı: {0}").format(api_key)}
			)
			continue
		if value is None or value == "":
			continue
		if api_key in _NUMERIC_KEYS:
			value = _sayi(p, api_key)
		if api_key == "unit":
			if persister._resolve_link("UOM", value) is None:
				warnings.append(
					{
						"code": "UNIT_UNKNOWN",
						"message": _("Birim tanınmadı, varsayılan kullanıldı: {0}").format(value),
					}
				)
				continue
		row[FIELD_MAP[api_key]] = value

	attrs = p.get("attributes")
	if attrs not in (None, "", {}):
		if not isinstance(attrs, dict):
			raise _Ret("ATTRIBUTES_INVALID", _("`attributes` {kod: değer} nesnesi olmalı"), "attributes")
		for code, val in attrs.items():
			if str(code).strip() and val not in (None, ""):
				row[f"attr:{str(code).strip()}"] = val

	variants = _varyantlar(p, warnings, is_new)
	images = _gorseller(p, warnings)
	return row, variants, images, warnings


# ─────────────────────────────────────────────────────────────────
# Kayıt
# ─────────────────────────────────────────────────────────────────


def _open_job(seller: str, products: list):
	"""API çağrısı = `Bulk Import Job(source=api)`; istek gövdesi denetim için private dosya."""
	govde = json.dumps(products, ensure_ascii=False, default=str).encode("utf-8")
	frappe.flags.in_bulk_import_upload = True  # security hook + medya kotası: kontrollü kanal
	try:
		# `save_file(dt="")` attached_to_* alanlarını BOŞ DİZE bırakır; Frappe'nin
		# `attach_files_to_document` "bağsız" sorgusu IS NULL arar, bulamaz, ikinci File
		# açmaya çalışır → "Error Attaching File". Alanları hiç vermeden (NULL) açınca
		# Frappe job'ın on_update'inde dosyayı `data_file` alanına kendisi bağlar.
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"api-upsert-{frappe.utils.now_datetime().strftime('%Y%m%d-%H%M%S')}.json",
				"is_private": 1,
				"content": govde,
			}
		).insert(ignore_permissions=True)
	finally:
		frappe.flags.in_bulk_import_upload = False
	# Oturum mağaza sahibi, seller_profile bağlamdan; API kanalı sunucu-içi olduğu
	# için rol-bazlı create izni aranmaz (bulk_import.api ile aynı gerekçe).
	job = frappe.get_doc(
		{
			"doctype": "Bulk Import Job",
			"seller_profile": seller,
			"source": "api",
			"data_file": file_doc.file_url,
			"file_format": "json",
			"update_mode": "upsert",
			"remember_mapping": 0,
			"status": "Running",
			"started_at": now(),
			"total_rows": len(products),
		}
	).insert(ignore_permissions=True)
	# Dosyayı ELLE bağlama: Frappe `attach_files_to_document` (on_update) bağsız File'ı
	# `attached_to_field=data_file` ile kendisi bağlar. Elle yalnız doctype/name yazınca
	# alan eşleşmiyor, Frappe ikinci bir File açmaya çalışıp "Error Attaching File"
	# üretiyordu (gerçek HTTP e2e'de Error Log'a düştü, 15 Eyl).
	return job


def _persist(
	seller: str, job_name: str, row: dict, variants: list[dict], images: list[str], warns: list[str]
):
	sku = row["sku"]
	exists = persister.check_sku_exists(sku, seller)
	local_images = image_url_ingest.ingest_image_urls(images, seller, warns) if images else []
	if exists:
		name, _changed = persister.update_listing(sku, row, seller, job_name, local_images or None, warns)
		return "updated", name
	if variants:
		idx = {normalize_sku_key(sku): local_images} if local_images else None
		name = persister.create_listing_with_variants(row, variants, seller, job_name, idx, warns)
	else:
		name = persister.create_listing(row, seller, job_name, local_images or None, warns)
	return "created", name


def _siniflandir(e: Exception) -> tuple[str, str]:
	"""Persister/Listing.validate istisnası → (kod, mesaj)."""
	msg = str(e)
	if isinstance(e, EntitlementError):
		return ("FEATURE_DENIED" if "Varyant" in msg or "özellik" in msg.lower() else "QUOTA_EXCEEDED"), msg
	if isinstance(e, frappe.MandatoryError):
		return "REQUIRED", _("Zorunlu alan eksik: {0}").format(msg)
	if isinstance(e, frappe.ValidationError):
		if "zaten kullanılıyor" in msg:
			return "DUPLICATE", msg
		if "negatif" in msg:
			return "PRICE_NEGATIVE" if "fiyat" in msg.lower() else "STOCK_NEGATIVE", msg
		if "büyük olamaz" in msg or "geçemez" in msg:
			return "PRICE_RULE", msg
		return "VALIDATION", msg
	return "SYSTEM", _("Beklenmeyen hata; kayıt Error Log'a düştü")


def _uyari_metinleri(persister_warns: list[str]) -> list[dict]:
	out = []
	for w in persister_warns:
		if "Görsel" in w:
			code = "IMAGE_FAILED"
		elif "öznitelik" in w:
			code = "ATTRIBUTE_UNKNOWN"
		else:
			code = "WARNING"
		out.append({"code": code, "message": w})
	return out


def _mesajlari_temizle(n: int) -> None:
	"""frappe.throw'un message_log'a bıraktığı satırları at — yanıt `_server_messages` taşımaz."""
	log = getattr(frappe.local, "message_log", None)
	if isinstance(log, list) and len(log) > n:
		del log[n:]


# ─────────────────────────────────────────────────────────────────
# Uç nokta
# ─────────────────────────────────────────────────────────────────


@frappe.whitelist(allow_guest=True, methods=["POST"])
def upsert_products(products=None) -> dict:
	"""Ürünleri SKU ile oluştur/güncelle (≤100). Her ürün için ayrı sonuç döner."""
	products = _parse_products(products)
	with catalog_context("catalog:write") as ctx, store_lock(ctx.seller, "upsert"):
		return _upsert(ctx.seller, products)


def _upsert(seller: str, products: list) -> dict:
	job = _open_job(seller, products)
	results: list[dict] = []
	created = updated = rejected = 0
	seen: set[str] = set()
	onceki_bayrak = (frappe.flags.in_bulk_import, frappe.flags.bulk_import_job)
	frappe.flags.in_bulk_import = True  # ECA `bulk_only` kuralları + File hook'ları içe aktarma kanalı sayar
	frappe.flags.bulk_import_job = job.name
	try:
		for idx, p in enumerate(products, 1):
			raw = p if isinstance(p, dict) else {"_raw": p}
			sku_ham = _sku_str(raw.get("sku"))
			sonuc: dict = {"index": idx, "sku": sku_ham or None, "warnings": []}
			log_n = len(getattr(frappe.local, "message_log", None) or [])
			sp = f"m665_row_{idx}"
			frappe.db.savepoint(sp)
			try:
				if not isinstance(p, dict):
					raise _Ret("INVALID_PRODUCT", _("Ürün bir nesne olmalı"))
				if sku_ham and sku_ham.lower() in seen:
					raise _Ret("DUPLICATE_IN_BATCH", _("Aynı SKU bu istekte birden çok kez var"), "sku")
				# İlk satır reddedilse de ikincisi "yinelenen"dir — sonuç sıraya bağlı olmasın.
				seen.add(sku_ham.lower())
				existing = None
				if sku_ham:
					existing = frappe.db.get_value(
						"Listing",
						{"seller_profile": seller, "seller_sku": sku_ham},
						["name", "base_price", "selling_price"],
						as_dict=True,
					)
				row, variants, images, warnings = _satir_hazirla(raw, existing)
				pw: list[str] = []
				status, name = _persist(seller, job.name, row, variants, images, pw)
				warnings.extend(_uyari_metinleri(pw))
				sonuc.update(
					{
						"status": status,
						"listing": name,
						"listing_code": frappe.db.get_value("Listing", name, "listing_code"),
						"warnings": warnings,
					}
				)
				if status == "created":
					created += 1
				else:
					updated += 1
				if warnings:
					_record_warnings(job, idx, raw, _JOB_MAPPING, [w["message"] for w in warnings])
			except _Ret as r:
				frappe.db.rollback(save_point=sp)
				rejected += 1
				sonuc.update({"status": "rejected", "code": r.code, "message": r.message, "field": r.field})
				_record_error(job, idx, raw, _JOB_MAPPING, "validation", r.message, field=r.field)
			except Exception as e:  # satır izolasyonu: bir ürünün hatası diğerlerini düşürmez
				frappe.db.rollback(save_point=sp)
				_mesajlari_temizle(log_n)
				code, msg = _siniflandir(e)
				if code == "SYSTEM":
					frappe.log_error(
						title=f"catalog.upsert_products row {idx}: {job.name}", message=frappe.get_traceback()
					)
				rejected += 1
				sonuc.update({"status": "rejected", "code": code, "message": msg})
				_record_error(
					job, idx, raw, _JOB_MAPPING, "system" if code == "SYSTEM" else "validation", msg
				)
			results.append(sonuc)
	finally:
		frappe.flags.in_bulk_import, frappe.flags.bulk_import_job = onceki_bayrak

	_finalize_job(job, created, updated, rejected)
	return {
		"job": job.name,
		"summary": {"total": len(products), "created": created, "updated": updated, "rejected": rejected},
		"results": results,
	}


def _finalize_job(job, created: int, updated: int, rejected: int) -> None:
	job.reload()
	job.inserted_count = created
	job.updated_count = updated
	job.skipped_count = 0
	job.error_count = rejected
	job.completed_at = now()
	job.duration_seconds = time_diff_in_seconds(job.completed_at, job.started_at) if job.started_at else 0
	total = created + updated + rejected
	if total and rejected == total:
		job.status = "Failed"
	elif rejected:
		job.status = "Partial"
	else:
		job.status = "Completed"
	if rejected and not job.error_summary:
		job.error_summary = _("{0} ürün reddedildi. Ayrıntılar hata listesinde.").format(rejected)
	job.save(ignore_permissions=True)  # oturum mağaza sahibi; job kendi mağazasının


# ─────────────────────────────────────────────────────────────────
# 4. aşama — stok / fiyat güncelleme
# ─────────────────────────────────────────────────────────────────


def _to_base(currency: str | None, amount: float) -> float:
	"""`Listing._to_base_price` ile aynı formül (TRY bazlı karşılaştırma kolonu)."""
	from tradehub_core.api.currency import _get_exchange_rate

	if not currency or currency == "TRY":
		return round(flt(amount), 2)
	return round(flt(amount) * _get_exchange_rate(currency, "TRY"), 2)


def _listings_by_sku(seller: str, skus: set[str]) -> dict:
	if not skus:
		return {}
	# get_all: sistem sorgusu — tenant izolasyonu seller_profile süzgeciyle açıkça kurulur.
	rows = frappe.get_all(
		"Listing",
		filters={"seller_profile": seller, "seller_sku": ["in", list(skus)]},
		fields=[
			"name",
			"seller_sku",
			"listing_code",
			"stock_qty",
			"reserved_qty",
			"base_price",
			"selling_price",
			"currency",
			"status",
		],
	)
	return {r.seller_sku.lower(): r for r in rows}


def _variants_by_sku(seller: str, skus: set[str]) -> dict:
	if not skus:
		return {}
	rows = frappe.get_all(
		"Listing Variant Item",
		filters={"variant_sku": ["in", list(skus)], "parenttype": "Listing"},
		fields=["name", "parent", "variant_sku", "variant_stock", "variant_price"],
	)
	if not rows:
		return {}
	parents = {
		p.name: p
		for p in frappe.get_all(
			"Listing",
			filters={"name": ["in", list({r.parent for r in rows})], "seller_profile": seller},
			fields=["name", "listing_code", "status", "base_price"],
		)
	}
	out = {}
	for r in rows:
		if r.parent in parents:  # başka mağazanın varyantı görünmez
			r.update({"listing_code": parents[r.parent].listing_code, "status": parents[r.parent].status})
			out[r.variant_sku.lower()] = r
	return out


def _apply_listing_stock(row, stock, price, list_price) -> tuple[str, dict]:
	changes: dict = {}
	yeni_liste = list_price if list_price is not None else flt(row.base_price)
	yeni_satis = price if price is not None else flt(row.selling_price)
	if yeni_liste and yeni_satis and yeni_satis > yeni_liste:
		raise _Ret(
			"PRICE_RULE",
			_("Satış fiyatı ({0}) liste fiyatını ({1}) geçemez").format(yeni_satis, yeni_liste),
			"price",
		)
	if stock is not None and flt(stock) != flt(row.stock_qty):
		changes["stock_qty"] = stock
	if list_price is not None and flt(list_price) != flt(row.base_price):
		changes["base_price"] = list_price
	if price is not None and flt(price) != flt(row.selling_price):
		changes["selling_price"] = price
		changes["selling_price_base"] = _to_base(row.currency, price)
	son_stok = flt(changes.get("stock_qty", row.stock_qty))
	sonuc = {
		"listing": row.name,
		"listing_code": row.listing_code,
		"stock_qty": son_stok,
		"available_qty": max(0.0, son_stok - flt(row.reserved_qty)),
		"price": flt(changes.get("selling_price", row.selling_price)),
		"list_price": flt(changes.get("base_price", row.base_price)),
	}
	if not changes:
		return "unchanged", sonuc
	# validate() bilinçli atlanır (kriter 4): durum/onay akışına dokunulmaz, ürün
	# yeniden onaya düşmez; sayısal kurallar yukarıda uygulandı. modified/modified_by
	# oturumdaki mağaza sahibi olur (denetim izi).
	frappe.db.set_value("Listing", row.name, changes)
	if "stock_qty" in changes:
		stock_utils._recalculate_available(row.name)  # sebepsiz → giden olay ÜRETİLMEZ (yankı yok)
	return "updated", sonuc


def _open_variant_reservation(row) -> float:
	"""Bu varyant için sevk edilmemiş (stock_deducted=0), iptal edilmemiş siparişlerin rezervi.

	Varyantta ayrı `reserved_qty` yok: `utils.stock` rezervi doğrudan `variant_stock`'tan
	düşer (sevkiyatta tekrar düşmez, iptal/iadede geri ekler) → `variant_stock` =
	fiziksel stok − açık rezerv. ERP'nin gönderdiği mutlak `stock` FİZİKSEL sayımdır;
	olduğu gibi yazılsaydı açık siparişlerin rezervi silinir, aynı adet ikinci alıcıya
	satılırdı (kod incelemesi bulgusu, 15 Eyl). Hedef = stock − açık rezerv.
	"""
	from tradehub_core.utils.stock import _find_variant_item_row

	satirlar = frappe.db.sql(
		"""SELECT oi.variation, oi.quantity
		   FROM `tabOrder Item` oi JOIN `tabOrder` o ON o.name = oi.parent
		   WHERE oi.listing = %s AND COALESCE(o.stock_deducted, 0) = 0 AND o.status != 'İptal Edildi'""",
		(row.parent,),
		as_dict=True,
	)
	toplam = 0.0
	for oi in satirlar:
		if oi.variation and _find_variant_item_row(row.parent, oi.variation) == row.name:
			toplam += flt(oi.quantity)
	return toplam


def _apply_variant_stock(row, stock, price, list_price) -> tuple[str, dict]:
	if list_price is not None:
		raise _Ret(
			"VARIANT_FIELD_UNSUPPORTED",
			_("Varyant SKU'da yalnız `stock` ve `price` güncellenir"),
			"list_price",
		)
	changes: dict = {}
	rezerv = 0.0
	if stock is not None:
		rezerv = _open_variant_reservation(row)
		hedef = max(0.0, flt(stock) - rezerv)
		if hedef != flt(row.variant_stock):
			changes["variant_stock"] = hedef
	if price is not None and flt(price) != flt(row.variant_price):
		changes["variant_price"] = price
	son = flt(changes.get("variant_stock", row.variant_stock))
	sonuc = {
		"listing": row.parent,
		"listing_code": row.listing_code,
		"variant": True,
		"stock_qty": flt(stock) if stock is not None else son + rezerv,
		"reserved_qty": rezerv,
		"available_qty": son,
		"price": flt(changes.get("variant_price", row.variant_price)),
	}
	if not changes:
		return "unchanged", sonuc
	frappe.db.set_value("Listing Variant Item", row.name, changes)
	frappe.db.set_value("Listing", row.parent, "modified", now())  # üst ürünün denetim izi
	return "updated", sonuc


@frappe.whitelist(allow_guest=True, methods=["POST"])
def update_stock(items=None) -> dict:
	"""Stok ve/veya fiyatı SKU ile mutlak değer olarak yaz (≤500). Onay akışına dokunmaz."""
	items = _parse_list(items, MAX_STOCK_ITEMS_PER_CALL, "items")
	with catalog_context("stock:write") as ctx, store_lock(ctx.seller, "stock"):
		return _update_stock(ctx.seller, items)


def _update_stock(seller: str, items: list) -> dict:
	skus = {_sku_str(i.get("sku")) for i in items if isinstance(i, dict)} - {""}
	listings = _listings_by_sku(seller, skus)
	variants = _variants_by_sku(seller, {s for s in skus if s.lower() not in listings})
	results: list[dict] = []
	updated = unchanged = rejected = 0
	seen: set[str] = set()
	gorunur_degisti = False
	for idx, it in enumerate(items, 1):
		sku = _sku_str(it.get("sku")) if isinstance(it, dict) else ""
		sonuc: dict = {"index": idx, "sku": sku or None}
		try:
			if not isinstance(it, dict):
				raise _Ret("INVALID_ITEM", _("Öğe bir nesne olmalı"))
			if not sku:
				raise _Ret("SKU_REQUIRED", _("`sku` zorunlu"), "sku")
			if sku.lower() in seen:
				raise _Ret("DUPLICATE_IN_BATCH", _("Aynı SKU bu istekte birden çok kez var"), "sku")
			seen.add(sku.lower())
			stock, price, list_price = _sayi(it, "stock"), _sayi(it, "price"), _sayi(it, "list_price")
			if stock is None and price is None and list_price is None:
				raise _Ret(
					"NOTHING_TO_UPDATE",
					_("`stock`, `price` ya da `list_price` alanlarından en az biri gerekli"),
				)
			if stock is not None and stock < 0:
				raise _Ret("STOCK_NEGATIVE", _("Stok negatif olamaz"), "stock")
			if (price is not None and price < 0) or (list_price is not None and list_price < 0):
				raise _Ret("PRICE_NEGATIVE", _("Fiyat negatif olamaz"), "price")
			row = listings.get(sku.lower())
			if row:
				status, veri = _apply_listing_stock(row, stock, price, list_price)
				if status == "updated" and row.status not in _INVISIBLE_STATUSES:
					gorunur_degisti = True
			elif sku.lower() in variants:
				status, veri = _apply_variant_stock(variants[sku.lower()], stock, price, list_price)
				if status == "updated" and variants[sku.lower()].status not in _INVISIBLE_STATUSES:
					gorunur_degisti = True
			else:
				raise _Ret("NOT_FOUND", _("Bu mağazada böyle bir SKU yok"), "sku")
			sonuc.update({"status": status, **veri})
			if status == "updated":
				updated += 1
			else:
				unchanged += 1
		except _Ret as r:
			rejected += 1
			sonuc.update({"status": "rejected", "code": r.code, "message": r.message, "field": r.field})
		except Exception:
			rejected += 1
			frappe.log_error(title=f"catalog.update_stock row {idx}", message=frappe.get_traceback())
			sonuc.update({"status": "rejected", "code": "SYSTEM", "message": _("Beklenmeyen hata")})
		results.append(sonuc)
	if gorunur_degisti:
		invalidate_listing_cache()  # db.set_value hook çalıştırmaz; vitrin önbelleği burada düşürülür
	return {
		"summary": {"total": len(items), "updated": updated, "unchanged": unchanged, "rejected": rejected},
		"results": results,
	}


# ─────────────────────────────────────────────────────────────────
# 5. aşama — değişiklikleri yoklama
# ─────────────────────────────────────────────────────────────────


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def changes(since=0, limit=100) -> dict:
	"""`since` imlecinden sonraki stok olayları (artan id). Webhook'tan bağımsız yoklama kaynağı."""
	since = cint(since)
	limit = max(1, min(cint(limit) or 100, MAX_CHANGES_PAGE))
	with catalog_context("catalog:read") as ctx:
		rows = frappe.get_all(
			"Catalog Outbound Event",
			filters={"seller_profile": ctx.seller, "name": [">", since]},
			fields=[
				"name",
				"event_type",
				"reason",
				"sku",
				"listing_code",
				"stock_qty",
				"reserved_qty",
				"available_qty",
				"occurred_at",
			],
			order_by="name asc",
			limit_page_length=limit + 1,
		)
	has_more = len(rows) > limit
	rows = rows[:limit]
	events = [
		{
			"id": cint(r.name),
			"event": r.event_type,
			"reason": r.reason,
			"sku": r.sku,
			"listing_code": r.listing_code,
			"stock_qty": r.stock_qty,
			"reserved_qty": r.reserved_qty,
			"available_qty": r.available_qty,
			"occurred_at": str(r.occurred_at),
		}
		for r in rows
	]
	return {"events": events, "next_since": events[-1]["id"] if events else since, "has_more": has_more}

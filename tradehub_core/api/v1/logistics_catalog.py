# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik katalog yönetimi API'si (v1).

Operasyon panelinin bağlanacağı yüzey. On katalog, taşıyıcı hesapları ve
lojistik ayarları buradan yönetilir.

TASARIM — neden kayıt defteri (registry) + jenerik çekirdek:
	On katalog × beş işlem = elli fonksiyon eder; bunların hepsi aynı beş satırı
	tekrarlardı ve zamanla birbirinden sürüklenirdi. Bunun yerine katalogların
	API sözleşmesi `CATALOGS` sözlüğünde AÇIKÇA yazılıdır ve tek bir çekirdek
	onu uygular. Sözleşme yine açık — `docs/logistics-api.schema.json` bu
	sözlükten üretilir.

	`catalog` parametresi serbest metin DEĞİL: yalnız `CATALOGS` içindeki
	anahtarlar kabul edilir. Bu bir allowlist'tir; rastgele DocType'a erişim yolu
	açmaz.

NEDEN DOCTYPE ŞEMASI DOĞRUDAN AÇILMIYOR:
	Alan listeleri burada elle yazılı. Böylece bir DocType'a alan eklemek
	otomatik olarak API'yi genişletmiyor — sözleşme bilinçli bir karar olarak
	kalıyor. (Faz A.6'da dört DocType değiştirdik; şema doğrudan açık olsaydı
	frontend habersiz kırılırdı.)

YETKİ:
	Rol kontrolü tekrarlanmıyor — `frappe.get_list` ve `doc.save()` DocPerm'leri
	zaten uyguluyor (System Manager: tam, Logistics Manager: rwc, Logistics
	Operator: okuma). Reddedilen erişim `PermissionError` fırlatır ve zarf onu
	`PERMISSION_DENIED` (403) koduna çevirir.

	Feature flag KAPISI YOK: yönetici, modül müşteriye açılmadan ÖNCE katalogları
	yapılandırabilmeli (bkz. `logistics/__init__.py` `is_enabled` docstring'i).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import frappe
from frappe import _

from tradehub_core.logistics.api_utils import logistics_endpoint, ok

# Sayfa boyutu üst sınırı — istemci ne isterse istesin bu aşılmaz.
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


@dataclass(frozen=True)
class CatalogSpec:
	"""Bir kataloğun API sözleşmesi.

	Attributes:
		doctype: Frappe DocType adı.
		list_fields: Liste yanıtında dönen alanlar. Child table İÇEREMEZ —
			Frappe liste sorgusu child tabloyu getirmez.
		detail_fields: Tekil kayıt yanıtında dönen ek alanlar (child tablolar dahil).
		searchable: `search` parametresinin tarayacağı alanlar.
		default_sort: Varsayılan sıralama.
	"""

	doctype: str
	list_fields: tuple[str, ...]
	searchable: tuple[str, ...]
	default_sort: str
	detail_fields: tuple[str, ...] = ()
	#: child tablo adı -> yanıtta dönecek alanlar. Frappe'nin iç alanları
	#: (owner, creation, parent, docstatus, doctype ...) sözleşmenin parçası
	#: DEĞİLDİR ve dışarı sızmamalıdır; bu yüzden alanlar açıkça yazılıyor.
	child_tables: dict[str, tuple[str, ...]] = field(default_factory=dict)
	extra_filters: tuple[str, ...] = field(default=())


CATALOGS: dict[str, CatalogSpec] = {
	"shipping_channel": CatalogSpec(
		doctype="Shipping Channel",
		list_fields=("name", "channel_name", "channel_code", "is_active"),
		detail_fields=("icon", "description"),
		searchable=("channel_name", "channel_code"),
		default_sort="channel_name asc",
	),
	"shipping_method": CatalogSpec(
		doctype="Shipping Method",
		list_fields=(
			"name", "method_name", "shipping_type", "channel", "is_active",
			"min_days", "max_days", "base_cost", "currency",
		),
		detail_fields=(
			"max_weight", "max_desi", "cost_per_kg", "free_shipping_threshold", "description",
		),
		child_tables={"carrier_services": ("carrier_service", "service_name", "is_preferred", "priority")},
		searchable=("method_name",),
		default_sort="method_name asc",
		extra_filters=("channel", "shipping_type"),
	),
	"logistics_provider": CatalogSpec(
		doctype="Logistics Provider",
		list_fields=(
			"name", "provider_name", "provider_code", "provider_type",
			"integration_type", "country", "is_active",
		),
		detail_fields=("logo", "website", "support_phone", "support_email"),
		child_tables={"operating_channels": ("shipping_channel", "channel_name")},
		searchable=("provider_name", "provider_code"),
		default_sort="provider_name asc",
		extra_filters=("provider_type", "integration_type", "country"),
	),
	"carrier_service": CatalogSpec(
		doctype="Carrier Service",
		list_fields=(
			"name", "service_name", "service_code", "carrier", "service_type", "is_active",
		),
		detail_fields=(
			"max_weight", "max_desi", "estimated_days_min", "estimated_days_max",
			"supports_cod", "supports_insurance",
		),
		searchable=("service_name", "service_code"),
		default_sort="service_name asc",
		extra_filters=("carrier", "service_type"),
	),
	"carrier_branch": CatalogSpec(
		doctype="Carrier Branch",
		list_fields=(
			"name", "branch_name", "branch_code", "carrier", "branch_type",
			"city", "district", "is_active",
		),
		detail_fields=(
			"postal_code", "address", "phone", "latitude", "longitude", "operating_hours",
		),
		searchable=("branch_name", "branch_code", "city"),
		default_sort="city asc",
		extra_filters=("carrier", "city", "branch_type"),
	),
	"service_coverage_area": CatalogSpec(
		doctype="Service Coverage Area",
		list_fields=(
			"name", "carrier", "carrier_service", "city", "district", "is_active",
		),
		detail_fields=("postal_code_from", "postal_code_to", "estimated_days_override"),
		searchable=("city", "district"),
		default_sort="city asc",
		extra_filters=("carrier", "carrier_service", "city"),
	),
	"carrier_status_mapping": CatalogSpec(
		doctype="Carrier Status Mapping",
		list_fields=(
			"name", "carrier", "carrier_status_code", "carrier_status_text",
			"internal_status", "exception_code",
		),
		searchable=("carrier_status_code", "carrier_status_text"),
		default_sort="carrier asc",
		extra_filters=("carrier", "internal_status"),
	),
	"package_type": CatalogSpec(
		doctype="Package Type",
		list_fields=(
			"name", "package_name", "package_code", "is_default", "is_active", "max_weight_kg",
		),
		detail_fields=(
			"max_length_cm", "max_width_cm", "max_height_cm", "max_desi", "description",
		),
		searchable=("package_name", "package_code"),
		default_sort="package_name asc",
	),
	"vehicle_type": CatalogSpec(
		doctype="Vehicle Type",
		list_fields=(
			"name", "vehicle_name", "vehicle_code", "vehicle_category",
			"is_active", "max_weight_kg",
		),
		detail_fields=("max_volume_m3", "max_desi", "description"),
		searchable=("vehicle_name", "vehicle_code"),
		default_sort="vehicle_name asc",
		extra_filters=("vehicle_category",),
	),
	"shipment_exception_code": CatalogSpec(
		doctype="Shipment Exception Code",
		list_fields=(
			"name", "exception_name", "exception_code", "exception_category",
			"severity", "is_retriable",
		),
		detail_fields=("description", "suggested_action"),
		searchable=("exception_name", "exception_code"),
		default_sort="exception_code asc",
		extra_filters=("exception_category", "severity"),
	),
}


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _spec(catalog: str) -> CatalogSpec:
	"""Katalog anahtarını sözleşmeye çevirir; bilinmeyen anahtarı reddeder."""
	spec = CATALOGS.get(catalog)
	if not spec:
		frappe.throw(
			_("Bilinmeyen katalog: {0}. Geçerli değerler: {1}").format(
				catalog, ", ".join(sorted(CATALOGS))
			)
		)
	return spec


def _clamp_page_size(page_size: int) -> int:
	return max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))


def _as_flag(value: Any) -> int:
	"""0/1 bayrağını HTTP'den gelen her biçimden okur.

	ÖLÇÜLDÜ (2026-08-19): istemci `is_active=true` gönderdiğinde `int("true")`
	ValueError atıyor ve uç INTERNAL_ERROR dönüyordu — Manuel Sevkiyat ekranı
	(C1) bu yüzden hiç açılmıyordu. Query string'de her değer METİN olarak
	geliyor; sözleşme 0/1 diyor ama sınırda savunma yapmak, aynı tuzağa
	düşecek bir sonraki istemciyi de kurtarıyor.
	"""
	if isinstance(value, bool):
		return int(value)
	metin = str(value).strip().lower()
	if metin in ("1", "true", "yes"):
		return 1
	if metin in ("0", "false", "no"):
		return 0
	frappe.throw(_("Geçersiz is_active değeri: {0}").format(value))


def _build_filters(spec: CatalogSpec, is_active: int | None, extra: dict | None) -> dict:
	"""İstemci filtrelerini sözleşmede tanımlı alanlarla sınırlar."""
	filters: dict[str, Any] = {}
	if is_active is not None:
		filters["is_active"] = _as_flag(is_active)

	for key, value in (extra or {}).items():
		if key not in spec.extra_filters:
			# Sessizce yok saymak yerine hata ver — istemci yanlış alan adıyla
			# filtrelediğinde "sonuç yok" sanmasın
			frappe.throw(
				_("{0} kataloğunda filtrelenemeyen alan: {1}").format(spec.doctype, key)
			)
		if value not in (None, ""):
			filters[key] = value
	return filters


def _safe_order_by(spec: CatalogSpec, order_by: str | None) -> str:
	"""İstemci sıralamasını allowlist'ler; aykırı değerde varsayılana düşer.

	Ham `order_by` doğrudan SQL'e geçiyordu (denetim 2026-08-20). Yalnız
	`spec.list_fields` içindeki bir alan adı + opsiyonel asc/desc kabul edilir.
	Aykırı değer HATA DEĞİL, sessizce `spec.default_sort`'a düşer — sıralama
	parametresi kritik değil; yanlış yazan istemci yine tutarlı liste alır.
	"""
	if not order_by:
		return spec.default_sort
	parts = order_by.strip().split()
	if not parts or len(parts) > 2:
		return spec.default_sort
	fieldname = parts[0]
	direction = parts[1].lower() if len(parts) == 2 else "asc"
	if fieldname not in spec.list_fields or direction not in ("asc", "desc"):
		return spec.default_sort
	return f"{fieldname} {direction}"


def _search_or_filters(spec: CatalogSpec, search: str | None) -> list | None:
	if not search:
		return None
	term = f"%{search.strip()}%"
	return [[fieldname, "like", term] for fieldname in spec.searchable]


# ---------------------------------------------------------------------------
# Katalog endpoint'leri
# ---------------------------------------------------------------------------


@frappe.whitelist()
@logistics_endpoint()
def list_catalog(
	catalog: str,
	page: int = 1,
	page_size: int = DEFAULT_PAGE_SIZE,
	search: str | None = None,
	is_active: int | None = None,
	filters: dict | None = None,
	order_by: str | None = None,
) -> dict:
	"""Katalog kayıtlarını sayfalı listeler.

	`frappe.get_list` kullanılıyor (get_all DEĞİL) — permission_query_conditions
	böylece devreye giriyor.

	Args:
		catalog: `CATALOGS` anahtarı.
		page: 1'den başlayan sayfa numarası.
		page_size: Sayfa boyutu (üst sınır 200).
		search: Katalogun aranabilir alanlarında geçen metin.
		is_active: 1/0 filtresi.
		filters: Katalogun `extra_filters` listesindeki alanlar.
		order_by: Sıralama — yalnız `list_fields` alanı + asc/desc; aykırı
			değer sessizce katalogun varsayılanına düşer.

	Returns:
		{"items": [...], "total": int, "page": int, "page_size": int}
	"""
	spec = _spec(catalog)
	page = max(1, int(page or 1))
	page_size = _clamp_page_size(page_size)

	base_filters = _build_filters(spec, is_active, filters)
	or_filters = _search_or_filters(spec, search)

	rows = frappe.get_list(
		spec.doctype,
		filters=base_filters,
		or_filters=or_filters,
		fields=list(spec.list_fields),
		order_by=_safe_order_by(spec, order_by),
		limit_start=(page - 1) * page_size,
		limit_page_length=page_size,
	)
	total = frappe.get_list(
		spec.doctype,
		filters=base_filters,
		or_filters=or_filters,
		limit_page_length=0,
		as_list=True,
	)

	return ok(
		{
			"items": rows,
			"total": len(total),
			"page": page,
			"page_size": page_size,
		}
	)


@frappe.whitelist()
@logistics_endpoint()
def get_catalog_item(catalog: str, name: str) -> dict:
	"""Tek bir katalog kaydının tam detayını döndürür (child tablolar dahil)."""
	spec = _spec(catalog)

	doc = frappe.get_doc(spec.doctype, name)
	doc.check_permission("read")

	payload: dict[str, Any] = {"name": doc.name}
	for fieldname in (*spec.list_fields, *spec.detail_fields):
		if fieldname == "name":
			continue
		payload[fieldname] = doc.get(fieldname)

	for table, child_fields in spec.child_tables.items():
		payload[table] = [
			{fieldname: row.get(fieldname) for fieldname in child_fields}
			for row in (doc.get(table) or [])
		]

	return ok(payload)


@frappe.whitelist()
@logistics_endpoint()
def create_catalog_item(catalog: str, values: dict) -> dict:
	"""Yeni katalog kaydı oluşturur.

	Yalnız sözleşmede tanımlı alanlar yazılır — istemcinin gönderdiği tanımsız
	alanlar sessizce yok sayılmaz, hata verir.
	"""
	spec = _spec(catalog)
	doc = frappe.new_doc(spec.doctype)
	_apply_values(spec, doc, values)
	doc.insert()  # DocPerm kontrolü + validate zinciri burada çalışır
	return ok({"name": doc.name})


@frappe.whitelist()
@logistics_endpoint()
def update_catalog_item(catalog: str, name: str, values: dict) -> dict:
	"""Var olan katalog kaydını günceller."""
	spec = _spec(catalog)
	doc = frappe.get_doc(spec.doctype, name)
	_apply_values(spec, doc, values)
	doc.save()  # DocPerm kontrolü + validate zinciri
	return ok({"name": doc.name})


@frappe.whitelist()
@logistics_endpoint()
def set_catalog_item_active(catalog: str, name: str, is_active: int) -> dict:
	"""Katalog kaydını aktifleştirir veya pasifleştirir.

	Silme yerine bu tercih ediliyor: katalog kayıtları başka dokümanlardan
	referans alınabiliyor ve silmek bağlantıyı kırar.
	"""
	spec = _spec(catalog)
	doc = frappe.get_doc(spec.doctype, name)
	if not doc.meta.has_field("is_active"):
		frappe.throw(_("{0} kataloğunda aktiflik bayrağı yok").format(spec.doctype))
	doc.is_active = int(is_active)
	doc.save()
	return ok({"name": doc.name, "is_active": doc.is_active})


def _apply_values(spec: CatalogSpec, doc: frappe.Document, values: dict) -> None:
	"""Sözleşmede tanımlı alanları dokümana yazar; tanımsız alanı reddeder."""
	allowed = {
		*spec.list_fields,
		*spec.detail_fields,
		*spec.child_tables.keys(),
	} - {"name"}

	unknown = set(values or {}) - allowed
	if unknown:
		frappe.throw(
			_("{0} kataloğunda yazılamayan alan(lar): {1}").format(
				spec.doctype, ", ".join(sorted(unknown))
			)
		)

	for fieldname, value in (values or {}).items():
		if fieldname in spec.child_tables:
			child_fields = set(spec.child_tables[fieldname])
			doc.set(fieldname, [])
			for row in value or []:
				# Child satırında da yalnız sözleşmedeki alanlar yazılır
				doc.append(fieldname, {k: v for k, v in row.items() if k in child_fields})
		else:
			doc.set(fieldname, value)


@frappe.whitelist()
@logistics_endpoint()
def list_catalog_keys() -> dict:
	"""Yönetilebilir katalogların listesi — panelin menüyü kurması için."""
	return ok(
		{
			"catalogs": [
				{
					"key": key,
					"doctype": spec.doctype,
					"searchable": list(spec.searchable),
					"filters": list(spec.extra_filters),
					"has_active_flag": "is_active" in spec.list_fields,
				}
				for key, spec in sorted(CATALOGS.items())
			]
		}
	)

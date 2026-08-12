#!/usr/bin/env python3
"""Lojistik API sözleşmesinden makine çıktıları üretir.

	python3 scripts/gen_logistics_types.py            # sadece tradehub_core içine yaz
	python3 scripts/gen_logistics_types.py --sync     # kardeş frontend repo'larına da yaz
	python3 scripts/gen_logistics_types.py --check    # üretilmiş dosyalar bayat mı? (CI)

ÜRETİM ZİNCİRİ

	Python kaynak (TEK OTORİTE)
		logistics/constants.py            enum'lar, feature flag'ler
		logistics/exceptions.py           hata kodları + HTTP durumları
		api/v1/logistics_catalog.py       katalog sözleşmesi (CATALOGS)
		api/v1/logistics_admin.py         hesap/ayar/yetki sözleşmesi
		doctype/**/*.json                 alan TİPLERİ (adları değil — onlar yukarıda)
			│
			▼
	docs/logistics-api.schema.json        makine-okunur sözleşme (commit'lenir)
			│
			├──► docs/generated/fixtures/*.json    Storybook mock verisi
			└──► src/types/logistics.d.ts          storefront TypeScript tipleri

NEDEN ŞEMA ELLE YAZILMIYOR:
	Sözleşme zaten Python'da yaşıyor (`CATALOGS` sözlüğü endpoint'lerin kendisini
	besliyor). Şemayı ayrıca elle yazmak İKİNCİ bir kaynak yaratır ve ikisi
	sürüklenir — Faz A'da `Shipping Method`'un iki teslim süresi alan çiftinde
	tam olarak bunun bedelini ödedik. Burada JSON bir ARTEFAKT: frontend'in
	Python okumadan tüketebilmesi için var.

NEDEN FRAPPE STUB:
	Üretici frappe kurulu olmayan ortamda da çalışmalı (CI'da yalnız ruff var).
	Kaynak modüller içe aktarılabilsin diye repo'nun mevcut stub deseni
	kullanılıyor (bkz. tests/test_seller_manufacturer_facets.py).
"""

from __future__ import annotations

import argparse
import json
import sys
import types
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = APP_ROOT / "tradehub_core"
DOCTYPE_ROOT = PACKAGE_ROOT / "tradehub_core" / "doctype"

SCHEMA_PATH = APP_ROOT / "docs" / "logistics-api.schema.json"
GENERATED_ROOT = APP_ROOT / "docs" / "generated"
FIXTURE_ROOT = GENERATED_ROOT / "fixtures"
DTS_PATH = GENERATED_ROOT / "logistics.d.ts"

#: --sync ile yazılacak kardeş repo hedefleri (repo kökünden göreli)
#: Tek dosya hedefleri (kaynak, repo kökünden göreli hedef)
SYNC_TARGETS: tuple[tuple[Path, Path], ...] = (
	(DTS_PATH, Path("../tradehubfront/src/types/logistics.d.ts")),
)

#: Dizin hedefleri — fixture'lar Storybook story'lerini besliyor.
#: admin-panel saf JS olduğu için TİP üretilmiyor (Faz B kararı); yalnız mock
#: veri kopyalanıyor. Hedef dizindeki eski JSON'lar temizlenir ki silinen bir
#: katalogun fixture'ı geride kalmasın.
SYNC_DIR_TARGETS: tuple[tuple[Path, Path], ...] = (
	(FIXTURE_ROOT, Path("../admin-panel/frontend/src/mocks/logistics")),
)

BANNER = (
	"ÜRETİLMİŞ DOSYA — elle düzenlemeyin.\n"
	"Kaynak: tradehub_core Python sözleşmesi\n"
	"Yeniden üret: python3 scripts/gen_logistics_types.py --sync"
)

# Frappe fieldtype -> TypeScript tipi.
# Check DİKKAT: Frappe 0/1 integer döndürür, boolean değil — tip yanlış yazılırsa
# `if (row.is_active)` çalışır ama `row.is_active === true` sessizce hep false olur.
FIELDTYPE_TO_TS: dict[str, str] = {
	"Data": "string",
	"Small Text": "string",
	"Text": "string",
	"Long Text": "string",
	"Text Editor": "string",
	"Select": "string",
	"Link": "string",
	"Dynamic Link": "string",
	"Attach": "string",
	"Attach Image": "string",
	"Password": "string",
	"Date": "string",
	"Datetime": "string",
	"Time": "string",
	"Int": "number",
	"Float": "number",
	"Currency": "number",
	"Percent": "number",
	"Check": "number",
	"JSON": "Record<string, unknown> | null",
}


def _install_frappe_stub() -> None:
	"""Kaynak modüller import edilebilsin diye minimal frappe sahtesi kurar."""
	if "frappe" in sys.modules:
		return

	frappe = types.ModuleType("frappe")
	frappe.ValidationError = type("ValidationError", (Exception,), {})
	frappe.PermissionError = type("PermissionError", (Exception,), {})
	frappe.DoesNotExistError = type("DoesNotExistError", (Exception,), {})
	frappe.DuplicateEntryError = type("DuplicateEntryError", (Exception,), {})
	frappe.whitelist = lambda **_kwargs: (lambda func: func)
	frappe._ = lambda message: message
	frappe.throw = lambda *a, **k: (_ for _ in ()).throw(frappe.ValidationError())
	frappe.Document = object
	sys.modules["frappe"] = frappe

	for name in ("frappe.utils", "frappe.model", "frappe.model.document"):
		sys.modules[name] = types.ModuleType(name)
	sys.modules["frappe.model.document"].Document = object

	if str(APP_ROOT) not in sys.path:
		sys.path.insert(0, str(APP_ROOT))


# ---------------------------------------------------------------------------
# Kaynak okuma
# ---------------------------------------------------------------------------


def _load_doctype_fieldtypes(doctype: str) -> dict[str, dict[str, Any]]:
	"""DocType JSON'undan alan adı -> {fieldtype, options, label} eşlemesi."""
	folder = doctype.lower().replace(" ", "_")
	path = DOCTYPE_ROOT / folder / f"{folder}.json"
	if not path.exists():
		raise SystemExit(f"DocType JSON bulunamadı: {path}")

	schema = json.loads(path.read_text(encoding="utf-8"))
	return {
		field["fieldname"]: {
			"fieldtype": field["fieldtype"],
			"options": field.get("options"),
			"label": field.get("label"),
			"required": bool(field.get("reqd")),
		}
		for field in schema.get("fields", [])
	}


def _collect_enums() -> dict[str, list[str]]:
	from tradehub_core.logistics import constants as C

	return {
		"ShipmentStatus": list(C.ShipmentStatus.ALL),
		"ShipmentType": list(C.ShipmentType.ALL),
		"LegType": list(C.LegType.ALL),
		"LegStatus": list(C.LegStatus.ALL),
		"CostPaidBy": list(C.CostPaidBy.ALL),
		"TerminalStatus": sorted(C.TERMINAL_STATUSES),
		"FeatureFlag": sorted(C.LOGISTICS_FEATURE_FLAGS),
	}


def _collect_error_codes() -> dict[str, int]:
	"""Exception sınıflarından kod -> HTTP durumu; zarfın ürettiği kodlar dahil."""
	from tradehub_core.logistics import exceptions as E
	from tradehub_core.logistics.api_utils import _FRAPPE_ERROR_MAP, _INTERNAL_ERROR_CODE

	codes: dict[str, int] = {}
	for name in dir(E):
		obj = getattr(E, name)
		if isinstance(obj, type) and hasattr(obj, "code") and hasattr(obj, "http_status_code"):
			codes[obj.code] = obj.http_status_code

	for _exc_type, code, status in _FRAPPE_ERROR_MAP:
		codes[code] = status
	codes[_INTERNAL_ERROR_CODE] = 500
	return dict(sorted(codes.items()))


def _entity_fields(doctype: str, fieldnames: tuple[str, ...]) -> list[dict[str, Any]]:
	"""Sözleşme alanlarını DocType tipleriyle birleştirir."""
	meta = _load_doctype_fieldtypes(doctype)
	out: list[dict[str, Any]] = []
	for fieldname in fieldnames:
		if fieldname == "name":
			out.append({"name": "name", "type": "Data", "ts": "string", "required": True})
			continue
		info = meta.get(fieldname)
		if not info:
			raise SystemExit(
				f"Sözleşmede tanımlı '{fieldname}' alanı {doctype} DocType'ında YOK. "
				"Sözleşme ile şema sürüklenmiş — birini düzelt."
			)
		out.append(
			{
				"name": fieldname,
				"type": info["fieldtype"],
				"ts": FIELDTYPE_TO_TS.get(info["fieldtype"], "unknown"),
				"required": info["required"],
				**({"link": info["options"]} if info["fieldtype"] == "Link" else {}),
				**(
					{"choices": [c for c in (info["options"] or "").split("\n") if c]}
					if info["fieldtype"] == "Select"
					else {}
				),
			}
		)
	return out


def _collect_catalogs() -> dict[str, Any]:
	from tradehub_core.api.v1.logistics_catalog import CATALOGS

	catalogs: dict[str, Any] = {}
	for key, spec in CATALOGS.items():
		catalogs[key] = {
			"doctype": spec.doctype,
			"list_fields": _entity_fields(spec.doctype, spec.list_fields),
			"detail_fields": _entity_fields(spec.doctype, spec.detail_fields),
			"child_tables": {
				table: _entity_fields(_child_doctype(spec.doctype, table), fields)
				for table, fields in spec.child_tables.items()
			},
			"searchable": list(spec.searchable),
			"filters": list(spec.extra_filters),
			"default_sort": spec.default_sort,
		}
	return catalogs


def _child_doctype(parent_doctype: str, table_fieldname: str) -> str:
	"""Parent DocType'taki Table alanının hedef child DocType'ını bulur."""
	meta = _load_doctype_fieldtypes(parent_doctype)
	info = meta.get(table_fieldname)
	if not info or not info.get("options"):
		raise SystemExit(f"{parent_doctype}.{table_fieldname} child DocType'ı çözülemedi")
	return info["options"]


def _collect_provisional() -> dict[str, Any]:
	"""Geçici sevkiyat sözleşmesini şema biçimine çevirir.

	Katalog varlıklarından farkı: alan TİPLERİ bir DocType'tan okunmuyor,
	`logistics/contract.py` içinde beyan ediliyor — çünkü `Shipment` DocType'ı
	henüz yok. Bu yüzden her varlık `provisional: true` işaretlenir.
	"""
	from tradehub_core.logistics.contract import PROVISIONAL_ENTITIES

	def to_schema(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
		return [
			{
				"name": field["name"],
				"type": field["type"],
				"ts": FIELDTYPE_TO_TS.get(field["type"], "unknown"),
				"required": field["required"],
				**({"note": field["note"]} if field.get("note") else {}),
			}
			for field in fields
		]

	return {
		key: {
			"provisional": True,
			"label": entity["label"],
			"source_tasks": entity["source_tasks"],
			"list_fields": to_schema(entity["list_fields"]),
			"detail_fields": to_schema(entity["detail_fields"]),
			"child_tables": {
				table: to_schema(rows) for table, rows in entity["child_tables"].items()
			},
		}
		for key, entity in PROVISIONAL_ENTITIES.items()
	}


def _collect_admin() -> dict[str, Any]:
	from tradehub_core.api.v1 import logistics_admin as A

	return {
		"carrier_account": {
			"doctype": "Carrier Account",
			"fields": _entity_fields("Carrier Account", A.CARRIER_ACCOUNT_FIELDS),
			# Değerleri ASLA dönmeyen alanlar; yanıtta yalnız has_<alan> bayrağı olur
			"secret_fields": list(A.SECRET_FIELDS),
		},
		"settings": {
			"doctype": "Logistics Settings",
			"fields": _entity_fields("Logistics Settings", A.SETTINGS_FIELDS),
		},
		"capabilities": list(A.LOGISTICS_CAPABILITIES),
	}


def build_schema() -> dict[str, Any]:
	"""Tüm kaynakları tek sözleşme belgesine toplar."""
	from tradehub_core.api.v1.logistics_catalog import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

	return {
		"$comment": BANNER,
		"contract_version": "1.0.0",
		"envelope": {
			"success": {"ok": True, "data": "<payload>"},
			"error": {
				"ok": False,
				"error": {"code": "<ErrorCode>", "message": "<i18n>", "details": "<optional>"},
			},
			"note": (
				"İstemci error.code üzerinden dallanır; error.message yalnız kullanıcıya "
				"gösterilir ve dallanma için kullanılmaz."
			),
		},
		"pagination": {
			"default_page_size": DEFAULT_PAGE_SIZE,
			"max_page_size": MAX_PAGE_SIZE,
			"response_keys": ["items", "total", "page", "page_size"],
		},
		"idempotency": {
			"header": "Idempotency-Key",
			"applies_to": [
				"gönderi oluşturan/iptal eden uçlar (Faz F'te gelecek)",
			],
			"behavior": {
				"same_key_same_body": "ilk yanıt tekrar döner, yeni işlem yapılmaz",
				"same_key_different_body": "IDEMPOTENCY_CONFLICT (409)",
			},
			"ttl_hours": 24,
			"status": "SÖZLEŞME REZERVE — implementasyon Faz F",
		},
		"enums": _collect_enums(),
		"error_codes": _collect_error_codes(),
		"catalogs": _collect_catalogs(),
		"admin": _collect_admin(),
		# Henüz DocType'ı olmayan varlıklar. Faz F backend'i BU sözleşmeye
		# implement eder; sapma açık karar gerektirir.
		"provisional": _collect_provisional(),
	}


# ---------------------------------------------------------------------------
# Çıktı üretimi
# ---------------------------------------------------------------------------


def _pascal(text: str) -> str:
	return "".join(part.capitalize() for part in text.replace("-", "_").split("_"))


def _ts_interface(name: str, fields: list[dict[str, Any]]) -> str:
	lines = [f"export interface {name} {{"]
	for field in fields:
		optional = "" if field.get("required") else "?"
		comment = ""
		if field.get("choices"):
			comment = "  // " + " | ".join(field["choices"])
		elif field.get("link"):
			comment = f"  // -> {field['link']}"
		lines.append(f"  {field['name']}{optional}: {field['ts']};{comment}")
	lines.append("}")
	return "\n".join(lines)


def render_dts(schema: dict[str, Any]) -> str:
	out: list[str] = [
		"/**",
		*[f" * {line}" for line in BANNER.split("\n")],
		" */",
		"",
		"// ── Yanıt zarfı ──",
		"export interface LogisticsOk<T> { ok: true; data: T }",
		"export interface LogisticsErr {",
		"  ok: false;",
		"  error: { code: LogisticsErrorCode; message: string; details?: Record<string, unknown> };",
		"}",
		"export type LogisticsResponse<T> = LogisticsOk<T> | LogisticsErr;",
		"",
		"export interface CatalogPage<T> {",
		"  items: T[];",
		"  total: number;",
		"  page: number;",
		"  page_size: number;",
		"}",
		"",
		"// ── Hata kodları ──",
		"export type LogisticsErrorCode =",
		*[f"  | {json.dumps(code)}" for code in schema["error_codes"]],
		"  ;",
		"",
		"// Kod -> HTTP durumu eşlemesi bilinçli olarak BURADA DEĞİL: .d.ts bir",
		"// bildirim dosyasıdır ve değer içeremez (TS1039). Eşleme gerekiyorsa",
		"// docs/logistics-api.schema.json içindeki error_codes bölümünü kullan;",
		"// zaten HTTP durumu yanıtın kendisinde de geliyor.",
		"",
		"// ── Enum'lar ──",
	]

	for enum_name, values in schema["enums"].items():
		union = " | ".join(json.dumps(v, ensure_ascii=False) for v in values)
		out.append(f"export type {enum_name} = {union};")
	out.append("")

	out.append("// ── Kataloglar ──")
	for key, spec in schema["catalogs"].items():
		base = _pascal(key)
		out.append(_ts_interface(f"{base}ListItem", spec["list_fields"]))
		out.append("")

		detail_extra = list(spec["detail_fields"])
		for table, child_fields in spec["child_tables"].items():
			child_name = f"{base}{_pascal(table)}Row"
			out.append(_ts_interface(child_name, child_fields))
			out.append("")
			detail_extra.append(
				{"name": table, "ts": f"{child_name}[]", "required": True}
			)

		if detail_extra:
			body = _ts_interface(f"{base}Detail", detail_extra).replace(
				f"export interface {base}Detail {{",
				f"export interface {base}Detail extends {base}ListItem {{",
			)
			out.append(body)
		else:
			out.append(f"export type {base}Detail = {base}ListItem;")
		out.append("")

	out.append("// ── Sevkiyat ve ilgili varlıklar (GEÇİCİ SÖZLEŞME) ──")
	out.append("// DocType'ları henüz yok; alanlar logistics/contract.py'de beyan edildi.")
	out.append("// Faz F backend'i bu sözleşmeye implement edecek.")
	for key, entity in schema.get("provisional", {}).items():
		base = _pascal(key)
		out.append(f"/** {entity['label']} — kaynak: {', '.join(entity['source_tasks'])} */")
		out.append(_ts_interface(f"{base}ListItem", entity["list_fields"]))
		out.append("")

		extra = list(entity["detail_fields"])
		for table, child_fields in entity["child_tables"].items():
			child_name = f"{base}{_pascal(table)}Row"
			out.append(_ts_interface(child_name, child_fields))
			out.append("")
			extra.append({"name": table, "ts": f"{child_name}[]", "required": True})

		if extra:
			body = _ts_interface(f"{base}Detail", extra).replace(
				f"export interface {base}Detail {{",
				f"export interface {base}Detail extends {base}ListItem {{",
			)
			out.append(body)
		else:
			out.append(f"export type {base}Detail = {base}ListItem;")
		out.append("")

	out.append("// ── Taşıyıcı hesabı ──")
	account = schema["admin"]["carrier_account"]
	account_fields = list(account["fields"]) + [
		{"name": "is_platform_account", "ts": "boolean", "required": True},
		*[
			{"name": f"has_{secret}", "ts": "boolean", "required": True}
			for secret in account["secret_fields"]
		],
	]
	out.append(_ts_interface("CarrierAccount", account_fields))
	out.append("")
	out.append(
		"/** Gizli alan DEĞERLERİ liste/detay yanıtında dönmez; "
		"reveal_carrier_secret ile alınır. */"
	)
	out.append(
		"export type CarrierSecretField = "
		+ " | ".join(json.dumps(s) for s in account["secret_fields"])
		+ ";"
	)
	out.append("")

	out.append("// ── Ayarlar ──")
	out.append(_ts_interface("LogisticsSettings", schema["admin"]["settings"]["fields"]))
	out.append("")
	out.append(
		"export type LogisticsFeatureFlags = Record<FeatureFlag, boolean>;"
	)
	out.append("")
	out.append("// ── Yetki bildirimi ──")
	out.append("export interface LogisticsPermissions {")
	out.append("  user: string;")
	out.append("  capabilities: Record<LogisticsCapability, boolean>;")
	out.append("  roles: Record<string, boolean>;")
	out.append(
		"  doctype_permissions: Record<string, "
		"{ read: boolean; write: boolean; create: boolean; delete: boolean }>;"
	)
	out.append("  module_enabled: boolean;")
	out.append("}")
	out.append(
		"export type LogisticsCapability = "
		+ " | ".join(json.dumps(c) for c in schema["admin"]["capabilities"])
		+ ";"
	)
	out.append("")
	return "\n".join(out)


def _sample_value(field: dict[str, Any], index: int) -> Any:
	"""Alan tipine göre deterministik örnek değer."""
	if field.get("choices"):
		return field["choices"][index % len(field["choices"])]
	ts = field["ts"]
	if ts == "number":
		return 0 if field["name"].startswith(("is_", "has_")) else (index + 1) * 10
	if ts.startswith("Record"):
		return None
	return f"{field['name']}-{index + 1}"


def render_fixtures(schema: dict[str, Any]) -> dict[str, Any]:
	"""Storybook için sözleşmeye uygun mock veri.

	Gerçek seed verisi olan kataloglarda o veri kullanılıyor (tasarım incelemesi
	uydurma isimlerle değil, gerçek kargo firmalarıyla yapılsın); diğerlerinde
	alan tipinden türetilen deterministik örnekler üretiliyor.
	"""
	from tradehub_core.logistics import seed

	# Gerçek seed verisi: `name` DE dahil, çünkü katalog kayıtları kodlarıyla
	# adlandırılıyor (autoname: field:<kod>). Tasarım incelemesi "PROVIDER-001"
	# yerine "YK / Yurtiçi Kargo" görmeli.
	real_data: dict[str, list[dict[str, Any]]] = {
		"logistics_provider": [
			{
				"name": row["code"],
				"provider_name": row["provider_name"],
				"provider_code": row["code"],
				"provider_type": "Kargo",
				"integration_type": "Manual",
				"country": {"TR": "Turkey", "US": "United States", "DE": "Germany"}[row["country"]],
			}
			for row in seed.LOGISTICS_PROVIDERS
		],
		"package_type": [
			{
				"name": row["code"],
				"package_name": row["type_name"],
				"package_code": row["code"],
				"max_weight_kg": row["max_weight_kg"],
				"is_default": 1 if row["code"] == "BOX" else 0,
			}
			for row in seed.PACKAGE_TYPES
		],
		"vehicle_type": [
			{
				"name": row["code"],
				"vehicle_name": row["type_name"],
				"vehicle_code": row["code"],
				"vehicle_category": row["type_name"],
				"max_weight_kg": row["max_weight_kg"],
			}
			for row in seed.VEHICLE_TYPES
		],
		# Severity/kategori/retriable seed patch'inin okudugu sozlukten geliyor.
		# Alan tipinden turetilseydi kategori choices listesini dolasip
		# "DAMAGED / Customs" gibi gerceklikte olmayan eslesmeler uretirdi.
		"shipment_exception_code": [
			{
				"name": row["code"],
				"exception_name": row["label"],
				"exception_code": row["code"],
				"severity": seed.EXCEPTION_META[row["code"]][0],
				"exception_category": seed.EXCEPTION_META[row["code"]][1],
				"is_retriable": seed.EXCEPTION_META[row["code"]][2],
			}
			for row in seed.EXCEPTION_CODES
		],
		"shipping_channel": [
			{"name": row["code"], "channel_name": row["name"], "channel_code": row["code"]}
			for row in seed.SHIPPING_CHANNELS
		],
		# Seed'i olmayan kataloglar için gerçekçi örnekler. Tasarım incelemesi
		# "city-1" ile yapılamaz: sütun genişliği, metin taşması ve Türkçe
		# karakter davranışı ancak gerçeğe yakın veriyle değerlendirilebilir.
		"carrier_branch": [
			{
				"name": "YK-34001", "branch_name": "Yurtiçi Kargo İkitelli Şubesi",
				"branch_code": "34001", "carrier": "YK", "branch_type": "Distribution Point",
				"city": "İstanbul", "district": "Başakşehir",
			},
			{
				"name": "AK-06010", "branch_name": "Aras Kargo Ostim Aktarma Merkezi",
				"branch_code": "06010", "carrier": "AK", "branch_type": "Transfer Center",
				"city": "Ankara", "district": "Yenimahalle",
			},
			{
				"name": "MNG-35004", "branch_name": "MNG Kargo Çiğli Hub",
				"branch_code": "35004", "carrier": "MNG", "branch_type": "Hub",
				"city": "İzmir", "district": "Çiğli",
			},
		],
		"carrier_service": [
			{
				"name": "YK-STD", "service_name": "Yurtiçi Standart", "service_code": "YK-STD",
				"carrier": "YK", "service_type": "Standard",
			},
			{
				"name": "YK-EXP", "service_name": "Yurtiçi Ertesi Gün", "service_code": "YK-EXP",
				"carrier": "YK", "service_type": "Express",
			},
			{
				"name": "AK-STD", "service_name": "Aras Standart", "service_code": "AK-STD",
				"carrier": "AK", "service_type": "Standard",
			},
		],
		"service_coverage_area": [
			{
				"name": "YK-YK-STD-İstanbul-Başakşehir", "carrier": "YK",
				"carrier_service": "YK-STD", "city": "İstanbul", "district": "Başakşehir",
			},
			{
				"name": "YK-YK-STD-Şanlıurfa-Haliliye", "carrier": "YK",
				"carrier_service": "YK-STD", "city": "Şanlıurfa", "district": "Haliliye",
			},
			{
				"name": "AK-AK-STD-Ankara-Çankaya", "carrier": "AK",
				"carrier_service": "AK-STD", "city": "Ankara", "district": "Çankaya",
			},
		],
		"carrier_status_mapping": [
			{
				"name": "YK-101", "carrier": "YK", "carrier_status_code": "101",
				"carrier_status_text": "Kargo şubeye teslim edildi",
				"internal_status": "Picked Up", "exception_code": None,
			},
			{
				"name": "YK-205", "carrier": "YK", "carrier_status_code": "205",
				"carrier_status_text": "Dağıtıma çıktı",
				"internal_status": "Out for Delivery", "exception_code": None,
			},
			{
				"name": "YK-902", "carrier": "YK", "carrier_status_code": "902",
				"carrier_status_text": "Alıcı adreste bulunamadı",
				"internal_status": "Failed", "exception_code": "RECIPIENT_ABSENT",
			},
		],
		"shipping_method": [
			{
				"name": "Standart Kargo", "method_name": "Standart Kargo",
				"shipping_type": "Standard", "channel": "CARGO",
				"min_days": 2, "max_days": 4, "base_cost": 89.90, "currency": "TRY",
			},
			{
				"name": "Hızlı Kargo", "method_name": "Hızlı Kargo",
				"shipping_type": "Express", "channel": "CARGO",
				"min_days": 1, "max_days": 2, "base_cost": 149.90, "currency": "TRY",
			},
			{
				"name": "Ambar Teslim", "method_name": "Ambar Teslim",
				"shipping_type": "Land", "channel": "WAREHOUSE",
				"min_days": 3, "max_days": 7, "base_cost": 0, "currency": "TRY",
			},
		],
	}

	fixtures: dict[str, Any] = {}
	for key, spec in schema["catalogs"].items():
		overrides = real_data.get(key, [])
		count = len(overrides) or 3
		items = []
		for index in range(count):
			override = overrides[index] if index < len(overrides) else {}
			row: dict[str, Any] = {}
			for field in spec["list_fields"]:
				fieldname = field["name"]
				if fieldname in override:
					row[fieldname] = override[fieldname]
				elif fieldname == "name":
					row[fieldname] = f"{key.upper()}-{index + 1:03d}"
				elif fieldname == "is_active":
					row[fieldname] = 1
				else:
					row[fieldname] = _sample_value(field, index)
			items.append(row)

		fixtures[key] = {
			"default": {"ok": True, "data": {
				"items": items, "total": len(items), "page": 1, "page_size": 50,
			}},
			"empty": {"ok": True, "data": {
				"items": [], "total": 0, "page": 1, "page_size": 50,
			}},
			"error": {"ok": False, "error": {
				"code": "PERMISSION_DENIED",
				"message": "Bu kataloğu görüntüleme yetkiniz yok.",
			}},
		}

	fixtures.update(_render_provisional_fixtures())
	fixtures["carrier_account"] = _render_carrier_account_fixture(schema)
	return fixtures


def _render_carrier_account_fixture(schema: dict[str, Any]) -> dict[str, Any]:
	"""Taşıyıcı hesabı mock'u — gizli değer YOK, yalnız `has_<alan>` bayrakları.

	Fixture'ın gizli alan taşımaması bilinçli ve sözleşmeyle aynı: panel
	"••••• (tanımlı)" gösterip üzerine yazmayı teklif ediyor. Mock'a örnek
	bir `api_secret` koymak ekranın onu göstermesini normalleştirirdi.
	"""
	secrets = schema["admin"]["carrier_account"]["secret_fields"]

	def account(**values: Any) -> dict[str, Any]:
		row = {
			"name": values["name"],
			"account_name": values["account_name"],
			"carrier": values["carrier"],
			"seller_profile": values.get("seller_profile"),
			"environment": values.get("environment", "production"),
			"is_active": values.get("is_active", 1),
			"is_default": values.get("is_default", 0),
			"base_url": values.get("base_url"),
			"token_expiry": values.get("token_expiry"),
			"is_platform_account": not values.get("seller_profile"),
		}
		defined = values.get("defined_secrets", ())
		row.update({f"has_{field}": int(field in defined) for field in secrets})
		return row

	items = [
		account(
			name="CACC-YK-PLATFORM", account_name="Yurtiçi Kargo — Platform",
			carrier="YK", is_default=1, base_url="https://api.yurticikargo.com/v2",
			token_expiry="2026-09-01 00:00:00",
			defined_secrets=("api_key", "api_secret", "webhook_secret"),
		),
		account(
			name="CACC-AK-SEL00001", account_name="Aras Kargo — Demir Tekstil",
			carrier="AK", seller_profile="SEL-00001",
			base_url="https://api.araskargo.com.tr/v1",
			defined_secrets=("api_key", "api_secret"),
		),
		# Kimlik bilgisi hiç girilmemiş hesap: ekran "bağlantıyı test et"
		# demeden önce bunu ayırt edebilmeli.
		account(
			name="CACC-MNG-SANDBOX", account_name="MNG Kargo — Sandbox",
			carrier="MNG", environment="sandbox", is_active=0,
			base_url="https://sandbox.mngkargo.com.tr/v1", defined_secrets=(),
		),
	]

	return {
		"default": {"ok": True, "data": {
			"items": items, "total": len(items), "page": 1, "page_size": 50,
		}},
		"empty": {"ok": True, "data": {
			"items": [], "total": 0, "page": 1, "page_size": 50,
		}},
		"error": {"ok": False, "error": {
			"code": "CAPABILITY_REQUIRED",
			"message": "Taşıyıcı kimlik bilgilerini yönetme yetkiniz yok.",
		}},
	}


def render_catalog_meta(schema: dict[str, Any]) -> dict[str, Any]:
	"""Katalog ekranının sütun/filtre türetmesi için ince meta.

	Jenerik katalog ekranı 10 kataloğu tek bileşenle sürüyor; hangi sütunun
	görüneceğini, hangi alanın aranabilir/filtrelenebilir olduğunu ve Select
	seçeneklerini buradan okur. Tam şemayı frontend'e taşımak gereksiz.
	"""
	return {
		"$comment": BANNER,
		"catalogs": {
			key: {
				"doctype": spec["doctype"],
				"searchable": spec["searchable"],
				"filters": spec["filters"],
				"default_sort": spec["default_sort"],
				"list_fields": spec["list_fields"],
				"detail_fields": spec["detail_fields"],
				"child_tables": spec["child_tables"],
			}
			for key, spec in schema["catalogs"].items()
		},
	}


def _render_provisional_fixtures() -> dict[str, Any]:
	"""Sevkiyat ve ilgili varlıklar için mock veri.

	Katalog fixture'larından farkı: veriler alan tipinden TÜRETİLMİYOR, elle
	yazılmış TUTARLI örnekler kullanılıyor (`contract.py`). Sevkiyat verisi
	kendi içinde tutarlı olmak zorunda — olay akışı duruma, miktarlar
	birbirine, paket ölçüleri desi kuralına uymalı. Türetilmiş veri bu
	tutarlılığı veremez ve tasarım incelemesini yanıltır.
	"""
	from tradehub_core.logistics.contract import PROVISIONAL_SAMPLES

	out: dict[str, Any] = {}
	for key, sample in PROVISIONAL_SAMPLES.items():
		rows = sample["rows"]
		scenarios: dict[str, Any] = {
			"default": {"ok": True, "data": {
				"items": rows, "total": len(rows), "page": 1, "page_size": 50,
			}},
			"empty": {"ok": True, "data": {
				"items": [], "total": 0, "page": 1, "page_size": 50,
			}},
			"error": {"ok": False, "error": {
				"code": "PERMISSION_DENIED",
				"message": "Bu kaydı görüntüleme yetkiniz yok.",
			}},
		}
		if sample["detail"]:
			# Detay, listenin İLK satırıyla birleştirilir — iki ayrı gerçek
			# olmasın, ekran aynı kaydı gösteriyor olsun.
			scenarios["detail"] = {
				"ok": True,
				"data": {**rows[0], **sample["detail"]},
			}
		out[key] = scenarios
	return out


def _assert_samples_cover_contract(schema: dict[str, Any]) -> None:
	"""Beyan edilen her geçici alanın en az bir örnek satırda karşılığı olsun.

	Alan sözleşmeye eklenip örneğe eklenmezse ekran o alanı TASARLAYAMAZ:
	Storybook'ta hep boş görünür, tasarım onayı eksik veriyle alınır ve
	eksiklik Faz F'te gerçek veri gelince ortaya çıkar. Bu yüzden sessiz
	geçilmiyor, üretim durduruluyor.
	"""
	from tradehub_core.logistics.contract import PROVISIONAL_SAMPLES

	problems: list[str] = []
	for key, spec in schema["provisional"].items():
		sample = PROVISIONAL_SAMPLES.get(key)
		if not sample:
			problems.append(f"{key}: hiç örnek satır yok")
			continue

		merged: dict[str, Any] = {}
		for row in sample["rows"]:
			merged.update(row)
		merged.update(sample["detail"] or {})

		declared = [f["name"] for f in (*spec["list_fields"], *spec["detail_fields"])]
		missing = [name for name in declared if name not in merged]
		if missing:
			problems.append(f"{key}: örnekte yok → {', '.join(missing)}")

		for table, fields in spec["child_tables"].items():
			child_rows = merged.get(table) or []
			child_merged: dict[str, Any] = {}
			for row in child_rows:
				child_merged.update(row)
			child_missing = [f["name"] for f in fields if f["name"] not in child_merged]
			if child_missing:
				problems.append(f"{key}.{table}: örnekte yok → {', '.join(child_missing)}")

	if problems:
		raise SystemExit(
			"Sözleşme ile örnek veri uyuşmuyor:\n  " + "\n  ".join(problems)
		)


# ---------------------------------------------------------------------------
# Yazma / doğrulama
# ---------------------------------------------------------------------------


def _render_all() -> dict[Path, str]:
	schema = build_schema()
	_assert_samples_cover_contract(schema)
	outputs: dict[Path, str] = {
		SCHEMA_PATH: json.dumps(schema, indent="\t", ensure_ascii=False) + "\n",
		DTS_PATH: render_dts(schema) + "\n",
		# Jenerik katalog ekranı sütun ve filtrelerini BUNDAN türetiyor. Tam
		# şemayı frontend'e taşımak yerine yalnız ekranın ihtiyacı verilir.
		FIXTURE_ROOT
		/ "_catalog-meta.json": (
			json.dumps(render_catalog_meta(schema), indent="\t", ensure_ascii=False) + "\n"
		),
	}
	for key, payload in render_fixtures(schema).items():
		outputs[FIXTURE_ROOT / f"{key}.json"] = (
			json.dumps(payload, indent="\t", ensure_ascii=False) + "\n"
		)
	return outputs


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--sync", action="store_true", help="kardeş frontend repo'larına da yaz")
	parser.add_argument("--check", action="store_true", help="bayat mı kontrol et, yazma")
	args = parser.parse_args()

	_install_frappe_stub()
	outputs = _render_all()

	if args.check:
		stale = [
			path for path, content in outputs.items()
			if not path.exists() or path.read_text(encoding="utf-8") != content
		]
		# Kardeş repo kopyaları da kontrol edilir. Yalnız docs/generated'a
		# bakmak yeterli değildi: `--sync`siz üretim yapıldığında burası
		# "Güncel" derken admin-panel mock'ları bayat kalıyordu.
		stale.extend(_stale_synced_copies(outputs))
		if stale:
			print("BAYAT üretilmiş dosya(lar):", file=sys.stderr)
			for path in stale:
				# Kardeş repo yolları APP_ROOT'un altında değil — relative_to
				# patlar. Mutlak yol da okunabilir, kırılgan olmasın.
				printable = (
					path.relative_to(APP_ROOT) if path.is_relative_to(APP_ROOT) else path
				)
				print(f"  {printable}", file=sys.stderr)
			print(
				"\nÇöz: python3 scripts/gen_logistics_types.py --sync", file=sys.stderr
			)
			return 1
		print(f"Güncel — {len(outputs)} dosya kontrol edildi.")
		return 0

	for path, content in outputs.items():
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(content, encoding="utf-8")
	print(f"Üretildi: {len(outputs)} dosya → {GENERATED_ROOT.relative_to(APP_ROOT)}")

	if args.sync:
		for source, relative_target in SYNC_TARGETS:
			target = (APP_ROOT / relative_target).resolve()
			if not _sibling_repo_exists(target):
				print(f"  ATLANDI (repo yok): {target}", file=sys.stderr)
				continue
			target.parent.mkdir(parents=True, exist_ok=True)
			target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
			print(f"  senkron: {target}")

		for source_dir, relative_target in SYNC_DIR_TARGETS:
			target_dir = (APP_ROOT / relative_target).resolve()
			if not _sibling_repo_exists(target_dir):
				print(f"  ATLANDI (repo yok): {target_dir}", file=sys.stderr)
				continue
			target_dir.mkdir(parents=True, exist_ok=True)

			produced = {path.name for path in source_dir.glob("*.json")}
			# Kaynakta olmayan eski fixture'ları temizle — silinen bir katalogun
			# mock'u geride kalırsa story sessizce ölü veriye bağlanır.
			for stale in target_dir.glob("*.json"):
				if stale.name not in produced:
					stale.unlink()
					print(f"  temizlendi: {stale}")

			for path in sorted(source_dir.glob("*.json")):
				(target_dir / path.name).write_text(
					path.read_text(encoding="utf-8"), encoding="utf-8"
				)
			print(f"  senkron: {target_dir} ({len(produced)} fixture)")

	return 0


def _stale_synced_copies(outputs: dict[Path, str]) -> list[Path]:
	"""Kardeş repo'daki kopyalardan üretilen içerikle uyuşmayanlar.

	Kardeş repo yoksa (CI tek repo checkout eder) boş liste döner — senkron
	zaten atlanacağı için bayat sayılmaz.
	"""
	stale: list[Path] = []

	for source, relative_target in SYNC_TARGETS:
		target = (APP_ROOT / relative_target).resolve()
		if not _sibling_repo_exists(target):
			continue
		content = outputs.get(source)
		if content is None:
			continue
		if not target.exists() or target.read_text(encoding="utf-8") != content:
			stale.append(target)

	for source_dir, relative_target in SYNC_DIR_TARGETS:
		target_dir = (APP_ROOT / relative_target).resolve()
		if not _sibling_repo_exists(target_dir):
			continue
		expected = {
			path.name: content
			for path, content in outputs.items()
			if path.parent == source_dir and path.suffix == ".json"
		}
		for name, content in expected.items():
			target = target_dir / name
			if not target.exists() or target.read_text(encoding="utf-8") != content:
				stale.append(target)
		# Kaynakta olmayan artık fixture da bayat sayılır — story ölü veriye bağlanır.
		stale.extend(
			path for path in target_dir.glob("*.json") if path.name not in expected
		)

	return stale


def _sibling_repo_exists(target: Path) -> bool:
	"""Hedefin bağlı olduğu kardeş repo çalışma kopyasında var mı?

	CI'da yalnız tek repo checkout edildiği için kardeş repo bulunmaz; bu
	durumda senkron sessizce atlanır, üretim başarısız SAYILMAZ.
	"""
	# APP_ROOT/.. = orkestrasyon klasörü; hedefin ilk seviyesi repo adı
	try:
		repo_root = target.relative_to(APP_ROOT.parent).parts[0]
	except ValueError:
		return False
	return (APP_ROOT.parent / repo_root).is_dir()


if __name__ == "__main__":
	raise SystemExit(main())

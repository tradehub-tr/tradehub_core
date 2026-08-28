# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik yönetim API'si — taşıyıcı hesapları, ayarlar, yetki bildirimi (v1).

`logistics_catalog.py`'den AYRI tutuluyor: oradaki on katalog tek tip bir CRUD
şablonuna uyuyor, buradakiler uymuyor —

	* **Carrier Account**: gizli kimlik bilgisi taşır, tenant kapsamlıdır
	* **Logistics Settings**: singleton'dır, feature flag'leri yönetir
	* **Yetki bildirimi**: kayıt değil, oturumun yetenek listesi

GİZLİ BİLGİ SÖZLEŞMESİ:
	`api_key`, `api_secret`, `webhook_secret`, `access_token` değerleri liste ve
	detay yanıtlarında **hiçbir koşulda dönmez** — yalnız "tanımlı mı" bilgisi
	(`has_api_key: true`) döner. Değeri görmek ayrı bir endpoint
	(`reveal_carrier_secret`) üzerinden, `view.carrier_secret` capability'si ile
	ve **denetim kaydı bırakarak** mümkündür.

	Maskeleme yerine hiç göndermemenin nedeni: maskelenmiş değer de yanıt
	gövdesinde, tarayıcı geçmişinde ve ara sunucu loglarında dolaşır. Panel
	"••••• (tanımlı)" gösterip üzerine yazmayı teklif eder; okumaya ihtiyaç
	duyduğunda bilinçli bir eylemle ister.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from tradehub_core.logistics.api_utils import logistics_endpoint, ok
from tradehub_core.logistics.constants import CREDENTIAL_SECRET_FIELDS

#: Değerleri asla liste/detay yanıtına konmayan alanlar.
#:
#: TEK OTORİTE `logistics/constants.py::CREDENTIAL_SECRET_FIELDS` — aynı küme
#: transport katmanının değer-tabanlı redaksiyonunu da besliyor. Eskiden iki
#: yerde AYRI İÇERİKLE yazılıydı (burada dört, `http_client`'ta yedi ad) ve
#: oradaki yorum "aynı küme" diyordu. Bu ad geriye dönük bir takma addır.
SECRET_FIELDS: tuple[str, ...] = CREDENTIAL_SECRET_FIELDS

#: Carrier Account sözleşmesi — gizli alanlar hariç
CARRIER_ACCOUNT_FIELDS: tuple[str, ...] = (
	"name",
	"account_name",
	"carrier",
	"seller_profile",
	"environment",
	"is_active",
	"is_default",
	"base_url",
	"token_expiry",
)

#: Panelin gösterdiği ayar alanları
SETTINGS_FIELDS: tuple[str, ...] = (
	"logistics_enabled",
	"auto_tracking_enabled",
	"tracking_poll_interval_minutes",
	"sla_breach_notify_hours",
	"default_currency",
	"shipment_naming_series",
	"default_logistics_provider",
	"default_package_type",
	"default_vehicle_type",
	"auto_assign_carrier",
	"max_delivery_attempts",
	"return_window_days",
)


# ---------------------------------------------------------------------------
# Carrier Account
# ---------------------------------------------------------------------------


def _serialize_account(doc: frappe.Document) -> dict[str, Any]:
	"""Hesabı sözleşme şekline çevirir; gizli değerleri DIŞARIDA bırakır."""
	payload = {fieldname: doc.get(fieldname) for fieldname in CARRIER_ACCOUNT_FIELDS}
	payload["name"] = doc.name
	payload["is_platform_account"] = not doc.seller_profile
	for secret in SECRET_FIELDS:
		payload[f"has_{secret}"] = bool(doc.get(secret))
	return payload


@frappe.whitelist()
@logistics_endpoint()
def list_carrier_accounts(
	carrier: str | None = None,
	is_active: int | None = None,
	page: int = 1,
	page_size: int = 50,
) -> dict:
	"""Erişilebilen taşıyıcı hesaplarını listeler.

	`frappe.get_list` kullanılıyor — tenant izolasyonu
	`carrier_account_query_conditions` üzerinden burada devreye giriyor.
	Gizli alanlar sorguya HİÇ dahil edilmiyor.
	"""
	filters: dict[str, Any] = {}
	if carrier:
		filters["carrier"] = carrier
	if is_active is not None:
		filters["is_active"] = int(is_active)

	page = max(1, int(page or 1))
	page_size = max(1, min(int(page_size or 50), 200))

	rows = frappe.get_list(
		"Carrier Account",
		filters=filters,
		fields=list(CARRIER_ACCOUNT_FIELDS),
		order_by="account_name asc",
		limit_start=(page - 1) * page_size,
		limit_page_length=page_size,
	)
	for row in rows:
		row["is_platform_account"] = not row.get("seller_profile")

	total = frappe.get_list(
		"Carrier Account", filters=filters, limit_page_length=0, as_list=True
	)
	return ok({"items": rows, "total": len(total), "page": page, "page_size": page_size})


@frappe.whitelist()
@logistics_endpoint()
def get_carrier_account(name: str) -> dict:
	"""Tek hesabın detayı — gizli değerler yerine "tanımlı mı" bayrakları."""
	doc = frappe.get_doc("Carrier Account", name)
	doc.check_permission("read")
	return ok(_serialize_account(doc))


@frappe.whitelist()
@logistics_endpoint()
def save_carrier_account(name: str | None = None, values: dict | None = None) -> dict:
	"""Taşıyıcı hesabı oluşturur veya günceller.

	Gizli alanlar YAZILABİLİR ama okunamaz. Boş string gönderilen gizli alan
	"değiştirme" olarak yorumlanır — panel formu her kaydettiğinde mevcut
	secret'ı silmesin diye.
	"""
	values = values or {}
	writable = {*CARRIER_ACCOUNT_FIELDS, *SECRET_FIELDS} - {"name"}
	unknown = set(values) - writable
	if unknown:
		frappe.throw(
			_("Taşıyıcı hesabında yazılamayan alan(lar): {0}").format(", ".join(sorted(unknown)))
		)

	doc = frappe.get_doc("Carrier Account", name) if name else frappe.new_doc("Carrier Account")

	for fieldname, value in values.items():
		# Boş gizli alan = "dokunma"; aksi halde her form kaydı secret'ı silerdi
		if fieldname in SECRET_FIELDS and value in (None, ""):
			continue
		doc.set(fieldname, value)

	doc.save() if name else doc.insert()
	return ok(_serialize_account(doc))


@frappe.whitelist()
@logistics_endpoint(capability="view.carrier_secret")
def reveal_carrier_secret(name: str, secret_field: str) -> dict:
	"""Tek bir gizli alanın değerini döndürür — capability + denetim kaydıyla.

	Bu endpoint bilinçli olarak dar: tek kayıt, tek alan. Toplu okuma yolu yok.
	Her çağrı `Authorization Decision Log`'a ALLOW olarak yazılır; kimin hangi
	credential'ı ne zaman gördüğü izlenebilir olmalı.
	"""
	if secret_field not in SECRET_FIELDS:
		frappe.throw(_("Görüntülenebilir bir gizli alan değil: {0}").format(secret_field))

	doc = frappe.get_doc("Carrier Account", name)
	doc.check_permission("read")

	value = doc.get_password(secret_field, raise_exception=False)

	_log_secret_access(doc, secret_field)
	return ok({"name": doc.name, "field": secret_field, "value": value})


def _log_secret_access(doc: frappe.Document, secret_field: str) -> None:
	"""Credential görüntülemeyi denetim kaydına yazar (FAIL-CLOSED).

	Denetim kaydı yazılamazsa secret DÖNDÜRÜLMEZ (denetim 2026-08-20):
	credential ifşası iz bırakmadan gerçekleşemez — "best-effort" davranış
	(hata yut, secret'ı yine dön) izlenemeyen erişim yolu açıyordu.
	"""
	try:
		from tradehub_core.audit import log as audit

		audit.log_decision(
			actor=frappe.session.user,
			action="carrier_account.reveal_secret",
			decision=audit.DECISION_ALLOW,
			layer=audit.LAYER_L2,
			object_doctype="Carrier Account",
			object_name=doc.name,
			tenant=doc.seller_profile,
			rule_id="logistics.carrier_secret_access",
			severity=audit.SEVERITY_HIGH,
			context={"field": secret_field},
		)
	except Exception:  # noqa: BLE001 — fail-closed: log_error + throw, secret dönmez
		frappe.log_error(
			f"Credential erişim kaydı yazılamadı: {doc.name}/{secret_field}",
			"logistics_admin.reveal_carrier_secret",
		)
		frappe.throw(
			_("Denetim kaydı yazılamadığı için gizli değer görüntülenemedi. Lütfen tekrar deneyin.")
		)


# ---------------------------------------------------------------------------
# Logistics Settings (singleton)
# ---------------------------------------------------------------------------


@frappe.whitelist()
@logistics_endpoint()
def get_logistics_settings() -> dict:
	"""Lojistik ayarlarını ve feature flag durumlarını döndürür."""
	from tradehub_core.logistics.constants import LOGISTICS_FEATURE_FLAGS

	doc = frappe.get_cached_doc("Logistics Settings")
	doc.check_permission("read")

	stored = frappe.parse_json(doc.get("feature_flags") or "{}")
	return ok(
		{
			"settings": {fieldname: doc.get(fieldname) for fieldname in SETTINGS_FIELDS},
			# Bilinen tüm bayraklar döner; kaydedilmemiş olan varsayılanını alır.
			# Panelin listeyi kendi kodunda tutması gerekmesin.
			"feature_flags": {
				flag: bool(stored.get(flag, default))
				for flag, default in LOGISTICS_FEATURE_FLAGS.items()
			},
		}
	)


@frappe.whitelist()
@logistics_endpoint()
def update_logistics_settings(values: dict) -> dict:
	"""Ayar alanlarını günceller (feature flag'ler ayrı endpoint'ten)."""
	unknown = set(values or {}) - set(SETTINGS_FIELDS)
	if unknown:
		frappe.throw(
			_("Yazılamayan ayar alan(lar)ı: {0}").format(", ".join(sorted(unknown)))
		)

	doc = frappe.get_doc("Logistics Settings")
	for fieldname, value in (values or {}).items():
		doc.set(fieldname, value)
	doc.save()
	return ok({fieldname: doc.get(fieldname) for fieldname in SETTINGS_FIELDS})


@frappe.whitelist()
@logistics_endpoint()
def set_feature_flag(flag: str, enabled: int) -> dict:
	"""Tek bir feature flag'i açar/kapatır.

	Ayrı endpoint olmasının nedeni: bayraklar tek bir JSON alanında duruyor;
	tüm sözlüğü gönderip yazmak eşzamanlı iki yöneticinin birbirinin değişikliğini
	ezmesine yol açardı. Burada yalnız istenen anahtar değişiyor.
	"""
	from tradehub_core.logistics.constants import LOGISTICS_FEATURE_FLAGS

	if flag not in LOGISTICS_FEATURE_FLAGS:
		frappe.throw(
			_("Bilinmeyen feature flag: {0}. Geçerli değerler: {1}").format(
				flag, ", ".join(sorted(LOGISTICS_FEATURE_FLAGS))
			)
		)

	doc = frappe.get_doc("Logistics Settings")
	flags = frappe.parse_json(doc.get("feature_flags") or "{}")
	flags[flag] = bool(int(enabled))
	doc.feature_flags = frappe.as_json(flags)
	doc.save()

	return ok({"flag": flag, "enabled": flags[flag]})


# ---------------------------------------------------------------------------
# Yetki bildirimi (B.7)
# ---------------------------------------------------------------------------

#: Panelin aksiyon görünürlüğünü kurarken sorduğu capability'ler
LOGISTICS_CAPABILITIES: tuple[str, ...] = (
	"shipment.create",
	"shipment.write",
	"shipment.cancel",
	"shipment.split",
	"view.logistics_cost",
	"view.tracking",
	"carrier_credential.manage",
	"view.carrier_secret",
)


@frappe.whitelist()
@logistics_endpoint()
def get_logistics_permissions() -> dict:
	"""Oturumun lojistik yetkilerini bildirir — panel butonları buna göre gizlenir.

	GÜVENLİK SINIRI DEĞİL: bu yalnız bir kullanıcı deneyimi kolaylığıdır. Yetki
	kararı her istekte backend'de yeniden verilir; istemcinin bu yanıtı
	değiştirmesi hiçbir kapıyı açmaz (bkz. docs/LOGISTICS-ARCHITECTURE.md §1).
	"""
	from tradehub_core.logistics import MASTER_FLAG, is_enabled
	from tradehub_core.utils.permission_resolver import has_capability

	user = frappe.session.user
	roles = set(frappe.get_roles(user))

	return ok(
		{
			"user": user,
			"capabilities": {
				capability: has_capability(user, capability)
				for capability in LOGISTICS_CAPABILITIES
			},
			"roles": {
				"logistics_manager": "Logistics Manager" in roles,
				"logistics_operator": "Logistics Operator" in roles,
				"carrier_integration_manager": "Carrier Integration Manager" in roles,
				"system_manager": "System Manager" in roles,
				# G0 matrisi: Ayarlar (M3) yazma kapısı backend'de System Manager +
				# Marketplace Admin (logistics_settings.json). Panel bu kapıyı
				# capability'yle DEĞİL rolle çizecek — ikisini de bildir.
				"marketplace_admin": "Marketplace Admin" in roles,
			},
			"doctype_permissions": {
				spec_key: {
					"read": frappe.has_permission(doctype, "read"),
					"write": frappe.has_permission(doctype, "write"),
					"create": frappe.has_permission(doctype, "create"),
					"delete": frappe.has_permission(doctype, "delete"),
				}
				for spec_key, doctype in _catalog_doctypes().items()
			},
			"module_enabled": is_enabled(MASTER_FLAG),
		}
	)


def _catalog_doctypes() -> dict[str, str]:
	"""Katalog anahtarı -> DocType eşlemesi (tek kaynak: logistics_catalog)."""
	from tradehub_core.api.v1.logistics_catalog import CATALOGS

	return {key: spec.doctype for key, spec in CATALOGS.items()}

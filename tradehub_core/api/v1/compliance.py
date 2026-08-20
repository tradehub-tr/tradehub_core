# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 3.2 — Compliance + PII Mask Matrix endpoint'leri.

Endpoints:
  - get_field_policies(doctype) → UI matrix için tüm PII Field Policy'leri
  - upsert_field_policy(...) → Compliance Officer / System Manager yetkili
  - delete_field_policy(name)
  - simulate_pii_access(user, doctype, fieldname, target_region) → dry-run
  - export_pii_access_report(start_date, end_date, user_filter) → GDPR Article 30

Detay: docs/yetki/faz-3/02-faz-3-2-detayli-plan.md
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from tradehub_core.api.rate_limit import rate_limit
from tradehub_core.utils import pii_compliance

_WRITE_ROLES = {"System Manager", "Administrator", "Compliance Officer"}


def _require_compliance_role() -> None:
	roles = set(frappe.get_roles(frappe.session.user))
	if not (roles & _WRITE_ROLES):
		frappe.throw(
			_("Bu işlem için Compliance Officer veya System Manager yetkisi gerekli"),
			exc=frappe.PermissionError,
		)


@frappe.whitelist()
def get_field_policies(doctype: str | None = None) -> list[dict]:
	"""Aktif PII Field Policy'lerin listesi. doctype filtresi opsiyonel."""
	# M5 fix — PII politika konfigürasyonu hassastır; dosyadaki diğer endpoint'lerle
	# tutarlı olarak compliance/admin yetkisi gerekir (eskiden hiç kontrol yoktu).
	_require_compliance_role()
	filters: dict = {"is_active": 1}
	if doctype:
		filters["ref_doctype"] = doctype

	policies = frappe.get_all(
		"PII Field Policy",
		filters=filters,
		fields=[
			"name",
			"ref_doctype",
			"fieldname",
			"pii_category",
			"permlevel",
			"is_active",
			"description",
			"legal_basis",
		],
		order_by="ref_doctype, fieldname",
	)

	for p in policies:
		rules = frappe.get_all(
			"PII Jurisdiction Rule",
			filters={"parent": p["name"], "parenttype": "PII Field Policy"},
			fields=["jurisdiction", "mask_strategy", "cross_border_block", "require_consent"],
		)
		p["jurisdiction_rules"] = rules

	return policies


@frappe.whitelist()
def upsert_field_policy(
	ref_doctype: str,
	fieldname: str,
	pii_category: str = "other",
	permlevel: int = 1,
	is_active: bool | int = 1,
	jurisdiction_rules: list | str | None = None,
	description: str = "",
	legal_basis: str = "",
) -> dict:
	"""Create or update a PII Field Policy. Idempotent on (ref_doctype, fieldname)."""
	_require_compliance_role()

	if isinstance(jurisdiction_rules, str):
		try:
			jurisdiction_rules = json.loads(jurisdiction_rules)
		except json.JSONDecodeError:
			frappe.throw(_("jurisdiction_rules geçerli JSON olmalı"), exc=frappe.ValidationError)
	jurisdiction_rules = jurisdiction_rules or []

	existing = frappe.db.get_value(
		"PII Field Policy",
		{"ref_doctype": ref_doctype, "fieldname": fieldname},
		"name",
	)

	if existing:
		doc = frappe.get_doc("PII Field Policy", existing)
	else:
		doc = frappe.new_doc("PII Field Policy")
		doc.ref_doctype = ref_doctype
		doc.fieldname = fieldname

	doc.pii_category = pii_category
	doc.permlevel = int(permlevel)
	doc.is_active = 1 if str(is_active) in {"1", "True", "true", "yes"} else 0
	doc.description = description
	doc.legal_basis = legal_basis

	# Replace child rows
	doc.set("jurisdiction_rules", [])
	for r in jurisdiction_rules:
		if not isinstance(r, dict):
			continue
		doc.append(
			"jurisdiction_rules",
			{
				"jurisdiction": r.get("jurisdiction"),
				"mask_strategy": r.get("mask_strategy", "none"),
				"cross_border_block": 1 if r.get("cross_border_block") else 0,
				"require_consent": 1 if r.get("require_consent") else 0,
			},
		)

	doc.save()
	frappe.db.commit()

	pii_compliance.invalidate_policy_cache(ref_doctype, fieldname)
	return {"ok": True, "name": doc.name, "created": not existing}


@frappe.whitelist()
def delete_field_policy(name: str) -> dict:
	_require_compliance_role()

	doctype, fieldname = frappe.db.get_value("PII Field Policy", name, ["ref_doctype", "fieldname"]) or (
		None,
		None,
	)
	frappe.delete_doc("PII Field Policy", name, ignore_permissions=False)
	frappe.db.commit()

	if doctype and fieldname:
		pii_compliance.invalidate_policy_cache(doctype, fieldname)
	return {"ok": True}


@frappe.whitelist()
def simulate_pii_access(
	user: str,
	doctype: str,
	fieldname: str,
	target_region: str | None = None,
) -> dict:
	"""Dry-run evaluator — UI panelinden test edilir, audit log YAZILMAZ."""
	_require_compliance_role()
	decision = pii_compliance.evaluate_pii_access(
		user=user,
		doctype=doctype,
		fieldname=fieldname,
		target_region=target_region,
		audit=False,
	)
	return decision.to_dict()


@frappe.whitelist()
def export_pii_access_report(
	start_date: str,
	end_date: str,
	user_filter: str | None = None,
) -> list[dict]:
	"""GDPR Article 30 — Records of Processing.

	Authorization Decision Log'tan pii.* kayıtlarını çeker.
	"""
	_require_compliance_role()

	filters: dict = {
		"creation": ["between", [start_date, end_date]],
		"rule_id": ["like", "pii.%"],
	}
	if user_filter:
		filters["actor"] = user_filter

	rows = frappe.get_all(
		"Authorization Decision Log",
		filters=filters,
		fields=[
			"name",
			"creation",
			"actor",
			"action",
			"resource_type",
			"resource_name",
			"decision",
			"rule_id",
			"severity",
			"reason",
		],
		order_by="creation desc",
		limit=10000,
	)
	return rows


@frappe.whitelist()
def get_compliance_metadata() -> dict:
	"""UI helper — sabitler."""
	return {
		"mask_strategies": list(pii_compliance.MASK_STRATEGIES),
		"jurisdictions": list(pii_compliance.JURISDICTIONS),
		"pii_categories": [
			"identity",
			"financial",
			"contact",
			"health",
			"location",
			"other",
		],
	}


# ---------------------------------------------------------------------------
# Faz 3.5 — Data Portability (GDPR Madde 20)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def request_data_export(password: str) -> dict:
	"""Kullanıcı kendi verilerini dışa aktarma talebi oluşturur. Şifre doğrulaması zorunlu."""
	user = frappe.session.user
	if user in ("Guest", "Administrator"):
		frappe.throw(_("Bu işlem için oturum açmanız gerekir."), frappe.AuthenticationError)

	from frappe.utils.password import check_password

	check_password(user, password)

	doc = frappe.get_doc(
		{
			"doctype": "Data Export Request",
			"user": user,
			"export_format": "json_csv",
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	frappe.enqueue(
		"tradehub_core.privacy.data_export.generate_user_data_export",
		request_name=doc.name,
		queue="long",
		timeout=600,
	)

	return {"request_name": doc.name, "status": "Pending"}


@frappe.whitelist()
def get_export_status(request_name: str) -> dict:
	"""Veri dışa aktarma talebinin durumunu sorgular. Kullanıcı sadece kendininkileri görebilir."""
	user = frappe.session.user
	doc = frappe.get_doc("Data Export Request", request_name)
	if doc.user != user and "System Manager" not in frappe.get_roles(user):
		frappe.throw(_("Bu talebe erişim yetkiniz yok."), frappe.PermissionError)
	return {"status": doc.status, "completed_at": str(doc.completed_at) if doc.completed_at else None}


# T-134 / KVKK belge erişim izi — kişisel veri arşivinin (m.11 dışa aktarım
# ZIP'i) indirilmesi denetime yazılır. Desen: media/audit.py ACTION_* sabitleri
# (`media.signed_access`in KVKK karşılığı). Maskeleme kuralı: token ASLA
# yazılmaz, IP yalnız parmak izi (fingerprint) olarak girer, kullanıcı
# e-postası satıra girmez — kimlik `Data Export Request` kaydında.
ACTION_EXPORT_DOWNLOADED: str = "privacy.export_downloaded"


def _audit_export_download(request_name: str, allowed: bool, reason: str = "", zip_bytes: int = 0) -> None:
	"""Best-effort denetim satırı; red yolunda `frappe.throw` transaction'ı geri
	alacağı için commit BURADA yapılır (`media/audit._persist` ile aynı gerekçe —
	orada ölçülmüştü: commit'siz DENY kaydı throw'un rollback'iyle kayboluyordu)."""
	try:
		import hashlib

		from tradehub_core.audit.log import (
			DECISION_ALLOW,
			DECISION_DENY,
			LAYER_L3,
			SEVERITY_HIGH,
			log_decision,
		)

		# `media/audit.fingerprint` ile aynı biçim (sha256[:12]) — oradan import
		# edilmiyor çünkü media/audit modül yükünde frappe.query_builder ister;
		# bu uç guest yolunda o bağımlılığa gerek yok.
		raw_ip = getattr(frappe.local, "request_ip", "") or ""
		context: dict = {"ip_hash": hashlib.sha256(raw_ip.encode("utf-8")).hexdigest()[:12]}
		if reason:
			context["reason"] = reason
		if zip_bytes:
			context["zip_bytes"] = zip_bytes

		log_decision(
			action=ACTION_EXPORT_DOWNLOADED,
			decision=DECISION_ALLOW if allowed else DECISION_DENY,
			rule_id="kvkk.article11",
			layer=LAYER_L3,
			object_doctype="Data Export Request",
			object_name=request_name,
			severity=SEVERITY_HIGH,
			context=context,
		)
		frappe.db.commit()
	except Exception:
		frappe.log_error(
			f"Failed to write export download audit for {request_name}",
			"compliance.download_data_export",
		)


# GÜVENLİK (2026-08-20 denetimi): `request_name` = DEXP-xxxx sıralı/tahmin
# edilebilir ve uç `allow_guest`. Hız sınırı olmadan token brute-force'a açıktı.
# IP başına kova (per_user=False; misafir oturumu tek "Guest") — 20 deneme/5 dk
# meşru indirmeyi (bir kez) etkilemez, otomatik denemeyi kilitler. B-01 sayacı
# atomik olduğu için (rate_limit.py INCR) bu koruma eşzamanlılıkta da güvenilir.
@frappe.whitelist(allow_guest=True)
@rate_limit(max_calls=20, window_seconds=300, per_user=False, scope="kvkk_export_dl")
def download_data_export(request_name: str, token: str):
	"""Token doğrulamalı güvenli indirme endpoint'i."""
	import hmac
	import os

	doc = frappe.get_doc("Data Export Request", request_name)

	if doc.status != "Ready":
		_audit_export_download(request_name, allowed=False, reason="not_ready")
		frappe.throw(_("Bu dosya artık mevcut değil."))

	# Sabit-zamanlı karşılaştırma: `!=` token uzunluğu/ön eki üzerinden zamanlama
	# sızdırırdı. `compare_digest` erken çıkmaz.
	if not hmac.compare_digest(str(doc.download_token or ""), str(token or "")):
		_audit_export_download(request_name, allowed=False, reason="invalid_token")
		frappe.throw(_("Geçersiz indirme tokeni."), frappe.AuthenticationError)

	from frappe.utils import now_datetime

	if doc.expires_at and doc.expires_at < now_datetime():
		_audit_export_download(request_name, allowed=False, reason="expired")
		frappe.throw(_("İndirme linkinin süresi dolmuş."))

	# Rapor 92 §4 düzeltmesi: `os.path.basename` alt-klasörlü dosya yerleşimini
	# KIRIYORDU — `File.insert` medya motorunun içerik-adresli yerleşimiyle
	# dosyayı `/private/files/8f/8f0a...zip` gibi bir alt klasöre taşıyor,
	# basename `8f/` parçasını düşürünce indirme "Dosya bulunamadı" veriyordu
	# (canlıda ölçüldü — m.11 indirme akışı bu yüzden hiç çalışmıyordu).
	# file_url sunucu üretimidir ama yine de realpath ile private/files köküne
	# sabitlenir (path traversal emniyeti, checklists.md §1).
	rel = (doc.file_url or "").split("/private/files/", 1)[-1].lstrip("/")
	base_dir = os.path.realpath(frappe.get_site_path("private", "files"))
	file_path = os.path.realpath(os.path.join(base_dir, rel))
	if not file_path.startswith(base_dir + os.sep):
		_audit_export_download(request_name, allowed=False, reason="path_escape")
		frappe.throw(_("Dosya bulunamadı."))
	if not os.path.exists(file_path):
		_audit_export_download(request_name, allowed=False, reason="file_missing")
		frappe.throw(_("Dosya bulunamadı."))

	with open(file_path, "rb") as f:
		content = f.read()

	_audit_export_download(request_name, allowed=True, zip_bytes=len(content))

	frappe.local.response.filename = f"veri-export-{request_name}.zip"
	frappe.local.response.filecontent = content
	frappe.local.response.type = "download"


# ---------------------------------------------------------------------------
# Faz 3.5 — Consent Management
# ---------------------------------------------------------------------------


@frappe.whitelist()
def record_consent(
	consent_type: str, action: str, version: str | None = None, source: str = "settings"
) -> dict:
	"""Kullanıcı onay olayını kaydeder."""
	from tradehub_core.privacy.consent import record_consent as _record

	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Oturum açmanız gerekir."), frappe.AuthenticationError)
	name = _record(user, consent_type, action, version=version, source=source)
	return {"name": name}


@frappe.whitelist()
def get_my_consents() -> list[dict]:
	"""Oturum açmış kullanıcının onay durumlarını döner."""
	from tradehub_core.privacy.consent import get_user_consents

	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Oturum açmanız gerekir."), frappe.AuthenticationError)
	return get_user_consents(user)


@frappe.whitelist()
def withdraw_consent(consent_type: str) -> dict:
	"""Belirli bir onay türünü geri çeker."""
	from tradehub_core.privacy.consent import withdraw_consent as _withdraw

	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Oturum açmanız gerekir."), frappe.AuthenticationError)
	name = _withdraw(user, consent_type)
	return {"name": name, "action": "withdrawn"}


# ---------------------------------------------------------------------------
# Faz 3.5 — ROPA Export (GDPR Madde 30)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def export_ropa_report(fmt: str = "json") -> dict:
	"""Tüm aktif Processing Activity Record'ları dışa aktarır."""
	_require_compliance_role()

	records = frappe.get_all(
		"Processing Activity Record",
		filters={"status": "Active"},
		fields=[
			"activity_name",
			"controller",
			"controller_contact",
			"purpose",
			"legal_basis",
			"data_subjects",
			"data_categories",
			"recipients",
			"cross_border_transfers",
			"retention_period",
			"security_measures",
			"last_reviewed",
			"review_interval_days",
		],
		order_by="creation asc",
	)

	for r in records:
		links = frappe.get_all(
			"ROPA DocType Link",
			filters={"parent": r.activity_name, "parenttype": "Processing Activity Record"},
			pluck="ref_doctype",
		)
		r["ref_doctypes"] = links

	if fmt == "csv":
		import csv
		import io

		output = io.StringIO()
		if records:
			writer = csv.DictWriter(output, fieldnames=records[0].keys())
			writer.writeheader()
			for r in records:
				row = {k: (", ".join(v) if isinstance(v, list) else v) for k, v in r.items()}
				writer.writerow(row)
		return {"csv": output.getvalue(), "count": len(records)}

	return {"records": records, "count": len(records)}

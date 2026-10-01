"""Yetim Link değerleri bekçisi: var olmayan bir kaydı gösteren bağlantıları sayar.

Bir kayıt `force=True` ile silinince Frappe'nin bağlı-belge kontrolü atlanır; ona bağlanan
belgeler sessizce yetim kalır ve bir sonraki kayıtta link doğrulamasında 417 ile düşer
(MOGEM-981: toplu yükleme temizliği PROD'da 866 ilanı böyle kilitledi, 24 gün fark edilmedi).
Kod tabanında zorla silme yapan çok sayıda yol var; tek tek incelemek yerine sonucu ölçeriz.

Yalnız SAYAR ve Error Log'a yazar, hiçbir şeyi düzeltmez; bildirim göndermez (karar, 1 Eki 2026).
Kapsam: bu app'in DocType'larındaki Link alanları + tüm Custom Field Link'leri.

Bazı yetimler tasarım gereğidir (denetim kaydı silinen kullanıcının izini tutar); her gece aynı uzun
listeyi yazmak yeni sorunu o listede kaybettirir. Bu yüzden ilk koşu tabanı bir kez yazar, sonraki
koşular yalnız sayısı ARTAN ya da yeni çıkan alanları yazar. Taban her koşuda güncellenir: azalan
bir alan sonradan yeniden artarsa yine raporlanır.
"""

from __future__ import annotations

import json
import time

import frappe
from frappe.query_builder.functions import Count

APP = "tradehub_core"
BASELINE_KEY = "orphan_links_baseline"


def report_orphan_links() -> list[dict]:
	"""Zamanlanmış giriş noktası. Döndürdüğü liste Error Log'a yazılanlardır."""
	started = time.monotonic()
	findings = find_orphan_links()
	current = {_key(f): f.get("satir", 0) for f in findings}
	baseline = _load_baseline()
	if baseline is None:
		reported, title = findings, f"Yetim bağlantı tabanı: {len(findings)} alan"
	else:
		reported = [{**f, "onceki": baseline.get(_key(f), 0)} for f in findings if _increased(f, baseline)]
		title = f"Yetim bağlantı artışı: {len(reported)} alan"
	if reported:
		frappe.log_error(
			title=title,
			message=json.dumps(
				{"sure_sn": round(time.monotonic() - started, 1), "alanlar": reported},
				ensure_ascii=False,
				indent=1,
			),
		)
	_save_baseline(current)
	return reported


def _key(finding: dict) -> str:
	return f"{finding['doctype']}.{finding['alan']}"


def _increased(finding: dict, baseline: dict) -> bool:
	key = _key(finding)
	return key not in baseline or finding.get("satir", 0) > baseline[key]


# Taban `tabDefaultValue`'da durur, frappe.defaults önbelleği atlanır: önbellek DB'den farklı
# kalırsa (ör. geri alınan işlem) bekçi yanlış tabana göre karar verirdi.
def _load_baseline() -> dict | None:
	table = frappe.qb.Table("tabDefaultValue")
	row = (
		frappe.qb.from_(table)
		.select(table.defvalue)
		.where((table.parent == "__default") & (table.defkey == BASELINE_KEY))
		.run()
	)
	return json.loads(row[0][0]) if row else None


def _save_baseline(current: dict) -> None:
	frappe.db.set_default(BASELINE_KEY, json.dumps(current, ensure_ascii=False))


def find_orphan_links() -> list[dict]:
	findings = []
	for doctype, fieldname, target in _link_fields():
		try:
			rows = _count_orphans(doctype, fieldname, target)
		except frappe.db.OperationalError as e:
			# Tablolar arası collation farkı gibi şema sorunları tek alanı düşürür, taramayı değil.
			findings.append({"doctype": doctype, "alan": fieldname, "hedef": target, "hata": str(e)[:200]})
			continue
		if rows:
			findings.append({"doctype": doctype, "alan": fieldname, "hedef": target, "satir": rows})
	return findings


def _count_orphans(doctype: str, fieldname: str, target: str) -> int:
	src, tgt = frappe.qb.DocType(doctype), frappe.qb.DocType(target)
	col = src[fieldname]
	query = (
		frappe.qb.from_(src)
		.left_join(tgt)
		.on(tgt.name == col)
		.select(Count("*"))
		.where(col.isnotnull() & (col != "") & tgt.name.isnull())
	)
	return query.run()[0][0]


def _link_fields() -> list[tuple[str, str, str]]:
	app_doctypes = set(
		frappe.get_all("DocType", filters={"module": ["in", frappe.get_module_list(APP)]}, pluck="name")
	)
	standard = frappe.get_all(
		"DocField",
		filters={"fieldtype": "Link", "parent": ["in", list(app_doctypes)], "is_virtual": 0},
		fields=["parent as doctype", "fieldname", "options"],
	)
	custom = frappe.get_all(
		"Custom Field",
		filters={"fieldtype": "Link", "is_virtual": 0},
		fields=["dt as doctype", "fieldname", "options"],
	)
	tables = _tables()
	return sorted(
		{
			(f.doctype, f.fieldname, f.options)
			for f in (*standard, *custom)
			if f.options in tables and f.doctype in tables and _has_column(f.doctype, f.fieldname)
		}
	)


def _tables() -> set[str]:
	"""Gerçek tablosu olan DocType'lar — Single ve sanal DocType'ların tablosu yoktur."""
	plain = frappe.get_all("DocType", filters={"issingle": 0, "is_virtual": 0}, pluck="name")
	existing = set(frappe.db.get_tables(cached=False))
	return {dt for dt in plain if f"tab{dt}" in existing}


def _has_column(doctype: str, fieldname: str) -> bool:
	return fieldname in frappe.db.get_table_columns(doctype)

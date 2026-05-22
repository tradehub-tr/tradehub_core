"""FAZ 1.1 — Seller field consistency check.

Bu patch idempotent bir DATA SANITY CHECK'tir:

  - Hiçbir kayıt değiştirmez/silmez.
  - Seller-scoped DocType'larda seller_profile/seller field'ı NULL olan kayıtları
    sayıp Error Log'a yazar.
  - Önemli bir sızıntı tespit edilirse migrate çıktısında uyarı verir.

Faz 1.1 sonrasında yeni kayıtların seller_profile field'ı tenant.py hook'ları
sayesinde garantili dolar. Bu patch mevcut (legacy) kayıtların durumunu
raporlar; düzeltme manuel yapılır çünkü hangi seller'a atanacağı insan kararı.

Çağrı:
  patches.txt → tradehub_core.patches.v15_1_1_validate_seller_field_consistency
"""

import frappe

# Seller-scoped DocType'lar — seller_profile (veya seller) field'ı dolu olmalı.
# Hybrid (buyer+seller) doctype'lar için NULL acceptable; çünkü buyer create
# ettiğinde controller field'ı sonra dolduruyor olabilir.
_REQUIRED_SELLER_FIELD: dict[str, str] = {
	"Listing": "seller_profile",
	"Admin Seller Profile": "seller_code",  # primary key
	"Seller Balance": "seller_profile",
	"Seller Category": "seller_profile",
	"Seller Gallery Image": "seller_profile",
	"Seller Inquiry": "seller_profile",
	"KYB Verification": "seller_profile",
	"Trusted Reviewer Invitation": "seller_profile",
}

# Hybrid doctype'lar — NULL olabilir ama log'lanır (audit için).
_OPTIONAL_SELLER_FIELD: dict[str, str] = {
	"Order": "seller_profile",
	"Order Dispute": "seller_profile",
	"Listing Review": "seller_profile",
	"Listing Question": "seller_profile",
	"Seller Review": "seller_profile",
	"Review Helpful Vote": "seller_profile",
	"Review Abuse Report": "seller_profile",
}


def execute() -> None:
	"""Sanity check — seller field NULL kayıtları raporla."""
	null_counts: dict[str, int] = {}
	total_records: dict[str, int] = {}

	# Required field'lar
	for doctype, field in _REQUIRED_SELLER_FIELD.items():
		# Önce tablo var mı? (Schema sync'ten önce çağrılabilir)
		if not frappe.db.table_exists(doctype):
			continue
		try:
			if not frappe.db.has_column(f"tab{doctype}", field):
				# Column henüz install olmamış — skip
				continue
		except Exception:
			continue
		try:
			total = frappe.db.count(doctype)
			null_count = frappe.db.count(doctype, filters={field: ["is", "not set"]})
			total_records[doctype] = total
			if null_count > 0:
				null_counts[doctype] = null_count
		except Exception as e:
			frappe.log_error(
				f"FAZ 1.1 sanity check: {doctype}.{field} count başarısız: {e}",
				"v15_1_1_validate_seller_field_consistency",
			)

	# Raporla
	if null_counts:
		# Required field'larda NULL = data integrity sorunu
		report_lines = [
			"FAZ 1.1 — Seller field consistency check sonuçları:",
			"",
			"⚠️  Aşağıdaki DocType'larda seller_profile/seller_code NULL kayıtlar var.",
			"    Faz 1.1 hook'ları yeni kayıtların seller_profile alanını garantili",
			"    doldurur, ama mevcut legacy kayıtlar manuel düzeltme gerektirir.",
			"",
		]
		for doctype, count in null_counts.items():
			total = total_records.get(doctype, "?")
			field = _REQUIRED_SELLER_FIELD[doctype]
			report_lines.append(f"  - {doctype}: {count}/{total} kayıt {field}=NULL")

		report_lines.append("")
		report_lines.append(
			"Çözüm: Her doctype için Süper Admin manuel inceleme yapsın. "
			"Hangi seller'a ait olduğu kullanıcı tarafından belirlenmeli."
		)

		message = "\n".join(report_lines)
		frappe.log_error(message, "FAZ 1.1 — Seller Field Consistency Warning")
		print(f"\n{message}\n")  # noqa: T201 — patch output
	else:
		print(  # noqa: T201
			"✅ FAZ 1.1 sanity check: tüm seller-scoped DocType'larda "
			"seller_profile/seller_code field'ı dolu."
		)

	# Optional field'lar — sadece info amaçlı
	optional_nulls = {}
	for doctype, field in _OPTIONAL_SELLER_FIELD.items():
		if not frappe.db.table_exists(doctype):
			continue
		try:
			if not frappe.db.has_column(f"tab{doctype}", field):
				continue
		except Exception:
			continue
		try:
			null_count = frappe.db.count(doctype, filters={field: ["is", "not set"]})
			if null_count > 0:
				optional_nulls[doctype] = null_count
		except Exception:
			pass

	if optional_nulls:
		print(  # noqa: T201
			"ℹ️  Hybrid (buyer+seller) DocType'larda NULL seller_profile sayısı "
			"(beklenen davranış, bilgi amaçlı):"
		)
		for doctype, count in optional_nulls.items():
			print(f"     {doctype}: {count} kayıt")  # noqa: T201

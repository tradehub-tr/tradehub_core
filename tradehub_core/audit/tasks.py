# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 1.4 — Audit log scheduled task'ları.

Retention politikası (karar dosyası §4):
  - Authorization Decision Log: 90 gün sıcak DB, 10 yıl arşiv
  - Role Change Log: 1 yıl sıcak, 9 yıl arşiv (10 yıl toplam)
  - Permission Override Log: 1 yıl sıcak, 9 yıl arşiv (10 yıl toplam)

Bu modüldeki scheduled job'lar:
  - archive_old_decision_logs (daily): 90 gün eski ADL'leri arşivle
  - archive_old_role_change_logs (weekly): 1 yıl eski RCL'leri arşivle
  - archive_old_override_logs (weekly): 1 yıl eski POL'leri arşivle
  - weekly_audit_summary (weekly): Süper Admin'e haftalık özet

Arşivleme stratejisi (Faz 1.4'te minimal):
  - Şu an: sıcak DB'de "is_archived=1" flag set + S3 dump file_url alanı
    (Faz 3'te encryption + S3 entegrasyonu tamamlanacak)
  - Bu fazda: 90+ gün eski kayıtları **silmeyiz** (audit immutable);
    sadece "soğuk" işaretler ve gelecek-S3 entegrasyonu için hazır bırakırız.

Detay: docs/yetki/01-karar-dosyasi.md §4
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, now_datetime

# Retention windows (gün cinsinden)
_HOT_DAYS_DECISION = 90
_HOT_DAYS_ROLE_CHANGE = 365
_HOT_DAYS_OVERRIDE = 365


def archive_old_decision_logs() -> None:
	"""90 gün eski Authorization Decision Log kayıtlarını işaretle.

	Scheduled: daily. Bu fazda sadece sayım/işaretleme yapılır; S3 dump
	Faz 3'te eklenecek (encryption gerektirir).
	"""
	cutoff = add_days(now_datetime(), -_HOT_DAYS_DECISION)
	total = frappe.db.count("Authorization Decision Log", filters={"timestamp": ["<", cutoff]})
	if total == 0:
		return

	frappe.logger().info(
		f"FAZ 1.4 archive_old_decision_logs: {total} ADL kaydı 90 gün'den eski "
		f"(cutoff={cutoff}). Faz 3'te S3 arşivine taşınacak."
	)
	# Faz 3 placeholder: S3 dump + encryption + delete
	# ⚠ Bu fazda DB'den silmiyoruz çünkü S3 yedek yok.


def archive_old_role_change_logs() -> None:
	"""1 yıl eski Role Change Log kayıtlarını işaretle (weekly)."""
	cutoff = add_days(now_datetime(), -_HOT_DAYS_ROLE_CHANGE)
	total = frappe.db.count("Role Change Log", filters={"timestamp": ["<", cutoff]})
	if total == 0:
		return
	frappe.logger().info(f"FAZ 1.4 archive_old_role_change_logs: {total} RCL kaydı 1 yıl'dan eski.")


def archive_old_override_logs() -> None:
	"""1 yıl eski Permission Override Log kayıtlarını işaretle (weekly)."""
	cutoff = add_days(now_datetime(), -_HOT_DAYS_OVERRIDE)
	total = frappe.db.count("Permission Override Log", filters={"timestamp": ["<", cutoff]})
	if total == 0:
		return
	frappe.logger().info(f"FAZ 1.4 archive_old_override_logs: {total} POL kaydı 1 yıl'dan eski.")


def weekly_audit_summary() -> None:
	"""Haftalık audit özeti — System Manager / Compliance'a bildirim.

	Bu fazda sadece log'a yazar; Faz 1.6 Permission Console UI'da
	gerçek dashboard widget olarak görünecek.
	"""
	week_ago = add_days(now_datetime(), -7)

	stats = {
		"decisions_total": frappe.db.count(
			"Authorization Decision Log", filters={"timestamp": [">=", week_ago]}
		),
		"decisions_denied": frappe.db.count(
			"Authorization Decision Log",
			filters={"timestamp": [">=", week_ago], "decision": "DENY"},
		),
		"decisions_high_severity": frappe.db.count(
			"Authorization Decision Log",
			filters={"timestamp": [">=", week_ago], "severity": "HIGH"},
		),
		"role_changes": frappe.db.count("Role Change Log", filters={"timestamp": [">=", week_ago]}),
		"overrides": frappe.db.count("Permission Override Log", filters={"timestamp": [">=", week_ago]}),
		"critical_overrides": frappe.db.count(
			"Permission Override Log",
			filters={"timestamp": [">=", week_ago], "severity": "CRITICAL"},
		),
	}

	frappe.logger().info(
		f"FAZ 1.4 Weekly audit summary (last 7 days): "
		f"{stats['decisions_total']} kararlar ({stats['decisions_denied']} deny, "
		f"{stats['decisions_high_severity']} HIGH severity); "
		f"{stats['role_changes']} rol değişiklik; "
		f"{stats['overrides']} override ({stats['critical_overrides']} CRITICAL)."
	)


# ---------------------------------------------------------------------------
# Faz 3.5 — Privacy scheduled tasks
# ---------------------------------------------------------------------------


def run_data_retention_enforcement() -> None:
	"""Daily: veri saklama politikalarını uygula (süresi dolan kayıtları anonimleştir)."""
	from tradehub_core.privacy.data_retention import enforce_data_retention

	enforce_data_retention()


def cleanup_expired_data_exports() -> None:
	"""Daily: süresi dolan veri dışa aktarma ZIP dosyalarını sil."""
	from tradehub_core.privacy.data_export import cleanup_expired_exports

	cleanup_expired_exports()


def check_expiring_dpas() -> None:
	"""Weekly: 30 gün içinde süresi dolacak DPA'ları Compliance Officer'a bildir."""
	from frappe.utils import add_days, getdate

	threshold = add_days(getdate(), 30)
	expiring = frappe.get_all(
		"Data Processing Agreement",
		filters={
			"status": "Active",
			"expires_at": ("<=", threshold),
			"auto_renew": 0,
		},
		fields=["name", "party_name", "expires_at"],
	)

	if not expiring:
		return

	lines = []
	for d in expiring:
		lines.append(f"• {d.party_name} ({d.name}) — {d.expires_at}")

	body = (
		"Aşağıdaki Veri İşleme Sözleşmelerinin süresi 30 gün içinde dolacak:\n\n"
		+ "\n".join(lines)
	)

	compliance_users = frappe.get_all(
		"Has Role",
		filters={"role": ("in", ["System Manager", "Compliance Officer"]), "parenttype": "User"},
		pluck="parent",
	)
	if compliance_users:
		frappe.sendmail(
			recipients=list(set(compliance_users)),
			subject="DPA Süre Sonu Uyarısı",
			message=body,
		)
		frappe.logger().info(f"DPA expiry warning sent for {len(expiring)} agreements")

"""Bildirim verisi için gizlilik ve saklama işleri.

- Hesap anonimleştirme (`privacy.account_deletion`): tercih kaydı silinir, bekleyen gönderimler
  iptal edilir, teslim günlüğünde hedef ve içerik temizlenir, izin aktarım satırında hedef silinir.
- Saklama: terminal durumdaki teslim kayıtları `DELIVERY_RETENTION_DAYS` sonra silinir. Süre geçici
  bir operasyon değeridir (ürün/hukuk onayı değildir); test gönderimleri 30 gün tutulur.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, now_datetime

from tradehub_core.notifications import store

DELIVERY_RETENTION_DAYS = 180
TEST_RETENTION_DAYS = 30
TERMINAL = ("sent", "accepted", "captured", "failed", "skipped", "cancelled", "uncertain", "digested")


def anonymize_user(user: str) -> None:
	D = frappe.qb.DocType(store.DELIVERY)
	with store._Write():
		frappe.db.delete("Platform Notification Preference", {"user": user})
		(
			frappe.qb.update(D)
			.set(D.status, "cancelled")
			.set(D.error_code, "ACCOUNT_DELETED")
			.where(D.user == user)
			.where(D.status.isin(["queued", "deferred", "digest_pending"]))
		).run()
		(frappe.qb.update(D).set(D.payload, None).set(D.target_ref, None).where(D.user == user)).run()
		S = frappe.qb.DocType("Commercial Consent Sync")
		(frappe.qb.update(S).set(S.target_ref, None).set(S.target_hash, None).where(S.user == user)).run()


def cleanup_deliveries() -> dict:
	"""Günlük: eski terminal teslim kayıtlarını siler (sayfalı)."""
	D = frappe.qb.DocType(store.DELIVERY)
	now = now_datetime()
	deleted = 0
	for days, is_test in ((DELIVERY_RETENTION_DAYS, 0), (TEST_RETENTION_DAYS, 1)):
		q = (
			frappe.qb.from_(D)
			.delete()
			.where(D.status.isin(TERMINAL))
			.where(D.is_test == is_test)
			.where(D.creation < add_days(now, -days))
			.limit(5000)
		)
		q.run()
		deleted += frappe.db.sql("select row_count()")[0][0]
	frappe.db.commit()
	return {"deleted": deleted}

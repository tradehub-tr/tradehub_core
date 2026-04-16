import frappe
from frappe.utils import add_days, now_datetime

# Okunmuş bildirimler: 90 gün sonra sil
READ_RETENTION_DAYS = 90
# Okunmamış bildirimler: 180 gün sonra sil
UNREAD_RETENTION_DAYS = 180


def delete_old_notifications():
	"""Eski bildirimleri temizle. Günlük scheduler task olarak çalışır."""
	now = now_datetime()

	# Okunmuş bildirimleri temizle (90 gün)
	read_cutoff = add_days(now, -READ_RETENTION_DAYS)
	_ = frappe.db.sql(
		"""
        DELETE FROM `tabPlatform Notification`
        WHERE is_read = 1 AND creation < %s
        """,
		(read_cutoff,),
	)

	# Okunmamış bildirimleri temizle (180 gün)
	unread_cutoff = add_days(now, -UNREAD_RETENTION_DAYS)
	_ = frappe.db.sql(
		"""
        DELETE FROM `tabPlatform Notification`
        WHERE is_read = 0 AND creation < %s
        """,
		(unread_cutoff,),
	)

	frappe.db.commit()

	total = frappe.db.sql("SELECT COUNT(*) FROM `tabPlatform Notification`")[0][0]

	frappe.logger("notification_cleanup").info(
		f"Notification cleanup: read_cutoff={read_cutoff}, unread_cutoff={unread_cutoff}, remaining={total}"
	)

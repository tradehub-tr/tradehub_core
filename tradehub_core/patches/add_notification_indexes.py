import frappe


def execute():
    """Platform Notification tablosuna composite index ekle.

    Sık kullanılan sorgular:
    - WHERE recipient_user = %s ORDER BY creation DESC  (get_notifications)
    - WHERE recipient_user = %s AND creation > %s       (get_new_notifications)
    - WHERE recipient_user = %s AND is_read = 0         (get_unread_count)
    - WHERE is_read = 1 AND creation < %s               (notification_cleanup)
    """
    # Patch migrate sirasinda DocType henuz olusturulmamis olabilir
    if not frappe.db.table_exists("Platform Notification"):
        return

    # recipient_user + creation: bildirimleri listelerken ve polling'de kullanılır
    frappe.db.sql_ddl("""
        CREATE INDEX IF NOT EXISTS idx_notification_user_creation
        ON `tabPlatform Notification` (recipient_user, creation DESC)
    """)

    # recipient_user + is_read: okunmamış sayısı için kullanılır
    frappe.db.sql_ddl("""
        CREATE INDEX IF NOT EXISTS idx_notification_user_read
        ON `tabPlatform Notification` (recipient_user, is_read)
    """)

    # is_read + creation: cleanup scheduler task için kullanılır
    frappe.db.sql_ddl("""
        CREATE INDEX IF NOT EXISTS idx_notification_read_creation
        ON `tabPlatform Notification` (is_read, creation)
    """)

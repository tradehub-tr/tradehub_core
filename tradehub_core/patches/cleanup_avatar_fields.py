"""Avatar mimarisi tek doğruluk kaynağına (User.user_image) konsolide edilir.

Eski tasarımda Buyer Profile.avatar ve Seller Profile.avatar custom alanları,
User.user_image'den bağımsız ayrı kolonlarda saklanıyordu. Bu yüzden:
- Hesap Bilgilerim üst karttaki yükleme (User.user_image) Profilim'i etkilemiyor,
- Seller Profile formundaki avatar yüklemesi Hesap Bilgilerim'i etkilemiyordu.

Bu patch:
1. SP/BP'deki mevcut avatar değerlerini User.user_image boş olan kullanıcılara
   taşır (User.user_image dolu olanları ezmez — kullanıcının daha yeni
   yüklediği avatar her zaman önceliklidir).
2. tabSeller Profile ve tabBuyer Profile tablolarındaki "avatar" kolonlarını
   drop eder.

Idempotent: kolon zaten yoksa noop, taşınacak veri yoksa noop. Tekrar tekrar
çalıştırılabilir.
"""

import frappe


def execute():
	if _column_exists("tabSeller Profile", "avatar"):
		seller_rows = frappe.db.sql(
			"""
			SELECT `user`, `avatar`
			FROM `tabSeller Profile`
			WHERE IFNULL(`avatar`, '') != ''
			""",
			as_dict=True,
		)
		for row in seller_rows:
			_migrate_to_user_image(row.get("user"), row.get("avatar"))

	if _column_exists("tabBuyer Profile", "avatar"):
		buyer_rows = frappe.db.sql(
			"""
			SELECT `user`, `avatar`
			FROM `tabBuyer Profile`
			WHERE IFNULL(`avatar`, '') != ''
			""",
			as_dict=True,
		)
		for row in buyer_rows:
			_migrate_to_user_image(row.get("user"), row.get("avatar"))

	# DDL implicit commit ile çakışmasın diye veri yazımını commit'leyip
	# transaction temiz halde ALTER TABLE çalıştır.
	frappe.db.commit()

	for table in ("tabSeller Profile", "tabBuyer Profile"):
		if _column_exists(table, "avatar"):
			frappe.db.sql_ddl(f"ALTER TABLE `{table}` DROP COLUMN `avatar`")


def _migrate_to_user_image(user_name, avatar_url):
	if not user_name or not avatar_url:
		return
	if not frappe.db.exists("User", user_name):
		return
	current = frappe.db.get_value("User", user_name, "user_image") or ""
	if current:
		return
	frappe.db.set_value("User", user_name, "user_image", avatar_url)


def _column_exists(table_name: str, column_name: str) -> bool:
	rows = frappe.db.sql(
		"""
		SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
		WHERE TABLE_SCHEMA = DATABASE()
		  AND TABLE_NAME = %s AND COLUMN_NAME = %s
		""",
		(table_name, column_name),
	)
	return bool(rows)
